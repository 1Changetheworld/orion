#!/usr/bin/env python3
"""
orion_salience.py — the SALIENCE GATE (Perception Contract §6; build §8 step 5).

What decides that something is worth thinking about.

THE FAILURE THIS REPLACES: consolidation fires on a 3-hour clock (orion_sleep CYCLE_SEC=10800),
8 times a day, whether or not anyone said anything — replaying a log that is 80% Orion's own
output with no provenance to tell his voice from James's. That produced nine consecutive cycles
consuming their own previous output. As Orion described it himself: "a tape recorder playing back
into its own microphone... there's no one home during those cycles." The bug was never in the
consolidation logic. It was in the input and the trigger.

THE RULE (§6): the gate runs when EVENTS ARRIVE, and produces nothing when nothing warrants it.
Silence is a valid output. That is what "at your own will" requires mechanically — the trigger has
to be the signal, not the schedule.

────────────────────────────────────────────────────────────────────────────────────────────────
WHAT TRIGGERS REFLECTION — settled with James, 2026-08-30

He turned the design question back on himself: "what tells ME a conversation is over? I may know
it is but want to still talk." And: "maybe that interaction made me feel a way that caused me to
later reflect." That reframed the whole trigger. Humans do NOT reflect at conversation boundaries;
they reflect when something LANDS, or when something DOESN'T FIT.

So the quiet period decides the UNIT of thought; it does not decide WHETHER to think:

  NECESSARY  external events (§6.1/§7.5 — provenance:self can never cause a cycle)
  AMPLIFIERS affect delta ("something landed") and prediction error ("something didn't fit")

Affect and surprise raise priority; they can never START a cycle on their own, because a cycle
with no external cause is exactly the self-consumption loop being removed.

SELF IS A PASSENGER, NEVER A DRIVER. Orion's own replies are half of every conversation and are
included in the episode — excluding them would destroy its meaning. They simply cannot cause one.

REPETITION MEANS SOMETHING (§6.2, extended by James). The contract says drop near-duplicates. He
argued the point is not the count but the inference: "what he should gather is that it clearly is
important to me." So a repeat REINFORCES the existing memory rather than duplicating it, and once
it crosses a threshold it derives a second-order belief — a fact about JAMES, not about content.

CORRECTIONS ARE IMMEDIATE WHEN SOMEONE IS TALKING (§6.4/§7.6, corrected by James). He rejected
queueing everything: "he needs to immediately address it... rather than time going on with the
carried issues on his mind." The 2026-06-07 incident (nine unsolicited iMessages in one day) was
about pushing NOTIFICATIONS with nobody there — a different thing. So corrections are written
where the prompt hook surfaces them on the very next turn: immediate inside a live conversation,
simply available when there isn't one. Pulled, never pushed.

INVARIANT — SALIENCE GATES MEMORY, NEVER VOICE. This module decides what is STORED. It has no
authority over what Orion notices or says, and it is not on the speaking path at all. Carrying an
unresolved contradiction in silence is the failure being prevented, not a behaviour to add.

CONSTITUTIONAL vs TUNABLE (§9.4): ~/.orion/salience.json is James's to edit and is re-read every
tick. The four invariants below are hard-coded and deliberately NOT configurable — they are what
keep Orion honest, and should not be a number someone can set to zero.

Safe: never raises, writes no graph nodes itself, and fires nothing unless config.enabled is true.

  --dry-run    decide over the real raw stream, fire NOTHING, print every decision
  --tick       the live gate (fires consolidation when config.enabled)
  --init       start from now (skip replaying the archive)
  --status     offset, episodes, model budget
  --config     print the live config
  --decisions  recent decisions and why
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/orion-code"))

import orion_perception as P

STATE = Path(os.path.expanduser("~/.orion/state"))
CONFIG_PATH = Path(os.path.expanduser("~/.orion/salience.json"))     # James's, hot-read
OFFSET = STATE / "salience_offset.json"                              # byte offset — never a full scan
DECISIONS = STATE / "salience_decisions.jsonl"                       # what it decided, and why
SEEN = STATE / "salience_seen.json"                                  # episode fingerprints (novelty)
REINFORCE = STATE / "salience_reinforce.json"                        # repeat counts -> derived beliefs
CORRECTIONS = Path(os.path.expanduser("~/.orion/pending_corrections.jsonl"))
BUDGET = STATE / "salience_model_budget.json"
PENDING = STATE / "salience_pending.json"    # events of conversations still in flight

# ── CONSTITUTIONAL. Not in the config file, on purpose. ──────────────────────────────────────
INVARIANTS = (
    "provenance:self can never trigger a cycle",
    "corrections surface, never silently overwrite",
    "diagnostics never notify",
    "salience gates memory, never voice",
)

DEFAULTS = {
    "enabled": False,             # cutover is a deliberate act, not a side effect of installing
    "quiet_seconds": 90,          # the UNIT of thought: conversation considered settled
    "max_episode_events": 25,     # force-close a long conversation so it is not held forever
    "min_external_events": 1,     # NECESSARY condition — below this, nothing happens at all
    "reinforce_threshold": 3,     # repeats before deriving "this matters to James"
    "affect_delta": 0.02,         # "something landed" (his drives currently wobble ~0.01)
    "allow_model": True,          # James, 2026-08-30: yes — for genuinely ambiguous cases only
    "model_calls_per_day": 24,    # "rarely"
    "max_turn_chars": 2000,       # what consolidation may SEE per turn (was hard-capped at 300)
    # SOLICITED surfaces: external in provenance (the world really did produce them), but Orion
    # ASKED for them. Found by the shadow run 2026-08-30: 9 of the first 10 decisions were web
    # pages he fetched himself during a study, each firing its own consolidation cycle. Study
    # already consolidates its findings with citations, so this double-counts — and under
    # autonomous study it becomes a new self-driven loop wearing external clothes. These may ride
    # along in an episode; they may never start one. The world speaking to him is the driver.
    "passenger_surfaces": ["web"],
}

# crude, deliberately conservative correction cues. Native first; the model adjudicates the
# ambiguous ones when allowed. This list only ever knows the phrasings someone thought of —
# the same weakness as SYNTHETIC_PREFIXES, and it is why the model is permitted here.
_CORRECTION_CUES = (
    "that's wrong", "thats wrong", "that is wrong", "you're wrong", "youre wrong",
    "incorrect", "not what i said", "i didn't say", "i did not say", "you didn't",
    "you did not", "don't do", "dont do", "stop doing", "no it", "no, ", "actually no",
    "that's not", "thats not", "correction", "you misread", "you assumed",
)


def _load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(p, o):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(o, indent=1), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


def config():
    """Hot-read every tick so James can retune without restarting anything (§6: auditable)."""
    cfg = dict(DEFAULTS)
    if not CONFIG_PATH.exists():
        _save(CONFIG_PATH, {"_comment": "Orion's salience rules — yours to edit, re-read every "
                                        "tick. The four invariants are hard-coded and not here "
                                        "on purpose: " + "; ".join(INVARIANTS), **DEFAULTS})
    cfg.update({k: v for k, v in _load(CONFIG_PATH, {}).items() if k in DEFAULTS})
    return cfg


# ── reading the raw stream by OFFSET (constant cost as the archive grows) ────────────────────
def _read_new(commit=False):
    """Events appended since last tick. Returns (events, new_offset)."""
    off = int(_load(OFFSET, {"offset": 0}).get("offset", 0))
    evs = []
    try:
        size = P.RAW.stat().st_size
    except Exception:
        return [], off
    if off > size:                      # file rotated/truncated — restart cleanly
        off = 0
    try:
        with P.RAW.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(off)
            for line in f:
                if not line.endswith("\n"):
                    break               # partial write in flight; pick it up next tick
                off += len(line.encode("utf-8"))
                line = line.strip()
                if line:
                    try:
                        evs.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return [], off
    if commit:
        _save(OFFSET, {"offset": off, "ts": time.time()})
    return evs, off


# ── episodes: the UNIT of thought (not the decision to think) ────────────────────────────────
def episodes(evs, cfg):
    """Group events into conversations: same thread, gaps under quiet_seconds, bounded size."""
    out, cur = [], {}
    for ev in sorted(evs, key=lambda e: e.get("ts") or 0):
        key = "%s|%s" % (ev.get("surface"), ev.get("thread"))
        b = cur.get(key)
        if (b and ((ev["ts"] - b["last_ts"]) > cfg["quiet_seconds"]
                   or len(b["events"]) >= cfg["max_episode_events"])):
            out.append(b)
            b = None
        if not b:
            b = {"surface": ev.get("surface"), "thread": ev.get("thread"),
                 "events": [], "first_ts": ev["ts"]}
            cur[key] = b
        b["events"].append(ev)
        b["last_ts"] = ev["ts"]
    out.extend(cur.values())
    return sorted(out, key=lambda b: b["first_ts"])


def _closed(ep, cfg, now=None):
    """A conversation is settled once it has been quiet for long enough (or ran long)."""
    now = now if now is not None else time.time()
    return ((now - ep["last_ts"]) > cfg["quiet_seconds"]
            or len(ep["events"]) >= cfg["max_episode_events"])


# ── the amplifiers: did something LAND, did something NOT FIT ───────────────────────────────
def _neuromod():
    try:
        import orion_temporal_ledger as tl
        return {m: tl._probe("neuromod:" + m) for m in
                ("arousal", "learning", "explore", "caution", "focus")}
    except Exception:
        return {}


def _affect_delta(now_state):
    """How much his internal state moved since the last episode — 'something landed'."""
    prev = _load(STATE / "salience_last_affect.json", {})
    d = 0.0
    for k, v in (now_state or {}).items():
        pv = prev.get(k)
        if isinstance(v, (int, float)) and isinstance(pv, (int, float)):
            d = max(d, abs(v - pv))
    return d


def _prediction_error(since_ts):
    """Refuted predictions since the last tick — 'something didn't fit'. This is the signal the
    curiosity engine already produces every hour, and it is what carries the amplifier load while
    his drives are still nearly flat (they wobble ~0.01; 100% of movement bets were refuted)."""
    if since_ts <= 0:
        return 0        # no baseline (first run or history replay) — absence of a comparison is
                        # not evidence of surprise. Counting every refutation ever made the
                        # amplifier fire on all 906 episodes, which is noise wearing a signal's coat.
    p = Path(os.path.expanduser("~/.orion/reason/predictions.jsonl"))
    n = 0
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("status") == "refuted" and float(r.get("resolved_ts") or 0) > since_ts:
                n += 1
    except Exception:
        pass
    return n


def _goal_relevance(text):
    """How much this touches what James has shown he cares about. Grounded, not guessed: the
    reinforce store holds what he has said more than once, and repetition is his own stated
    signal of importance. Self-improving — the more he repeats, the sharper this gets."""
    try:
        store = _load(REINFORCE, {})
    except Exception:
        return 0.0
    t = (text or "").lower()
    if not t or not store:
        return 0.0
    best = 0.0
    for rec in store.values():
        sample = str(rec.get("sample") or "").lower()
        words = [w for w in sample.split() if len(w) > 5][:12]
        if not words:
            continue
        hits = sum(1 for w in words if w in t)
        if hits >= 2:
            best = max(best, min(1.0, hits / max(4.0, len(words))) * min(3, rec.get("count", 1)))
    return round(best, 3)


def _learning_weight(text):
    """What he is actively LEARNING should be what he KEEPS. Wired now, near-zero today
    (mean learning-progress ~0.002) — the socket exists so it needs no retrofit later."""
    lp = _load(STATE / "curiosity_lp.json", {}).get("by_topic", {})
    t = (text or "").lower()
    best = 0.0
    for topic, d in lp.items():
        tail = topic.split(":")[-1].split(".")[-1]
        if tail and len(tail) > 3 and tail in t:
            best = max(best, float(d.get("learning_progress") or 0))
    return best


# ── novelty and repetition ──────────────────────────────────────────────────────────────────
def _fingerprint(ep):
    ext = " ".join(e.get("content", "") for e in ep["events"] if e.get("provenance") == "external")
    return hashlib.sha256(" ".join(ext.lower().split()).encode("utf-8", "replace")).hexdigest()[:20]


def _note_repeat(fp, sample):
    """Repetition REINFORCES rather than duplicates, and once it crosses the threshold it derives
    a second-order belief — a fact about James, not about the content (his correction to §6.2)."""
    d = _load(REINFORCE, {})
    rec = d.get(fp) or {"count": 0, "sample": sample[:160], "derived": False}
    rec["count"] += 1
    rec["last_ts"] = time.time()
    d[fp] = rec
    if len(d) > 4000:
        d = dict(sorted(d.items(), key=lambda kv: kv[1].get("last_ts", 0))[-2000:])
    _save(REINFORCE, d)
    return rec


# ── corrections: surfaced where the hook picks them up on the NEXT turn ─────────────────────
_NEGATION = (" not ", "n't ", " no ", " never ", " stop ", " wrong ", " isn", " don", " dont ",
             " shouldn", " didn", " won't ", " wasn")
_AIMED = ("you ", "your ", "you'", "youre ", "u ")


def _looks_like_correction(text):
    """Detect the SHAPE of a correction rather than its wording: a negation aimed at Orion, or an
    imperative starting with one. Broader than a phrase list on purpose — a phrase list only ever
    catches what somebody already noticed, which is exactly how the contact log leaked for eight
    days and how the 2026-08-28 correction was missed here."""
    t = " " + (text or "").lower().strip() + " "
    if any(c in t for c in _CORRECTION_CUES):
        return True
    neg = any(n in t for n in _NEGATION)
    if not neg:
        return False
    return any(a in t for a in _AIMED) or t.strip().startswith(("don", "stop", "no ", "never"))


def _correction_candidates(ep):
    hits = []
    for e in ep["events"]:
        if e.get("provenance") != "external":
            continue                      # only the world can correct him
        if _looks_like_correction(e.get("content")):
            hits.append({"ts": e["ts"], "actor": e.get("actor"),
                         "content": e.get("content"), "detector": "shape"})
    return hits


def _file_corrections(hits, live):
    """Written where the prompt hook surfaces them next turn: IMMEDIATE inside a live conversation,
    simply available when there is none. Never a push (§7.4 — the nine-iMessage incident)."""
    try:
        CORRECTIONS.parent.mkdir(parents=True, exist_ok=True)
        with CORRECTIONS.open("a", encoding="utf-8") as f:
            for h in hits:
                f.write(json.dumps({**h, "filed_ts": time.time(), "live": bool(live),
                                    "status": "open"}, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── the model, for genuinely ambiguous cases only (James: yes, rarely, always recorded) ──────
def _budget_left(cfg):
    day = time.strftime("%Y-%m-%d")
    b = _load(BUDGET, {})
    return int(cfg["model_calls_per_day"]) - int(b.get(day, 0))


def _spend(n=1):
    day = time.strftime("%Y-%m-%d")
    b = _load(BUDGET, {})
    b[day] = int(b.get(day, 0)) + n
    _save(BUDGET, {k: v for k, v in b.items() if k >= time.strftime("%Y-%m-%d",
                                                                   time.localtime(time.time() - 7 * 86400))})


def _ask_model_durable(ep, cfg):
    """Only for the ambiguous middle. Returns (verdict, judged_by) — judged_by is recorded so we
    can always see whether the model is helping or just being expensive."""
    if not cfg["allow_model"] or _budget_left(cfg) <= 0:
        return None, "native"
    ext = [e for e in ep["events"] if e.get("provenance") == "external"]
    snippet = "\n".join("- " + (e.get("content") or "")[:300] for e in ext[:8])
    try:
        import orion_fuel
        reply, _eng = orion_fuel.get_fuel(
            "Will anything in this exchange still matter in a month? Answer ONLY 'yes' or 'no'.\n"
            "Say yes for preferences, decisions, identity, project state, corrections.\n"
            "Say no for pleasantries, one-off logistics, and small talk.\n\n" + snippet,
            interface="salience-gate")
        _spend(1)
        v = (reply or "").strip().lower()
        return (True if v.startswith("yes") else False if v.startswith("no") else None), "model"
    except Exception:
        return None, "native"


def _adjudicate_correction(hits, cfg):
    """Corrections are the HIGHEST-consequence path in this gate: +5 salience and injected into
    Orion's context on his next turn. A false one puts a thing James never said into his head,
    which is worse than missing a real one. Shape-detection runs ~50% precise on real messages
    ("correct me if I'm wrong" is not a correction), so this is exactly the ambiguous middle the
    model was authorized for. Cheap: James sends ~2 messages a day and ~7% get flagged.
    Returns the subset the model confirms; on any failure, keeps them (fail toward surfacing)."""
    if not hits or not cfg["allow_model"] or _budget_left(cfg) <= 0:
        return hits, "native"
    try:
        import orion_fuel
        nl = chr(10)
        listing = nl.join("%d. %s" % (i + 1, (h.get("content") or "")[:220])
                          for i, h in enumerate(hits[:5]))
        reply, _eng = orion_fuel.get_fuel(
            "Which of these messages from James are CORRECTING you?" + nl + nl +
            "A message IS a correction if it does ANY of these:" + nl +
            "  - says something you did, said, or believe is wrong" + nl +
            "  - tells you to STOP doing something, or to do it differently" + nl +
            "  - gives you a rule or instruction about your behaviour "
            "(e.g. \"don't reply unless it's a task\")" + nl +
            "  - disputes a claim you made" + nl +
            "A message is NOT a correction if it is only a question, only a request for work, "
            "or merely contains the word 'not' (e.g. 'correct me if I am wrong')." + nl + nl +
            "Answer ONLY with the numbers, comma-separated, or NONE." + nl + nl + listing,
            interface="salience-correction")
        _spend(1)
        raw = (reply or "").strip().lower()
        if "none" in raw:
            return [], "model"
        import re
        picked = {int(x) for x in re.findall(r"\b([1-5])\b", raw)}   # parse integers, not substrings
        if not picked:
            return hits, "native"          # unparseable -> fail toward surfacing, not toward silence
        return [h for i, h in enumerate(hits[:5]) if (i + 1) in picked], "model"
    except Exception:
        return hits, "native"


def _ambiguous(ep):
    """Clear cases are decided natively. Only the genuine middle costs a model call."""
    ext = [e for e in ep["events"] if e.get("provenance") == "external"]
    chars = sum(len(e.get("content") or "") for e in ext)
    if chars < 60:
        return False        # clearly trivial
    if chars > 300 or len(ext) >= 3:
        return False        # clearly substantial
    return True


# ── the gate ────────────────────────────────────────────────────────────────────────────────
def judge(ep, cfg, since_ts, may_call_model=True):
    """Decide whether this settled conversation is worth thinking about, and why. Never raises.
    may_call_model=False keeps a dry run genuinely dry — it reports where a model WOULD have been
    consulted instead of spending fuel (and wall-clock) to replay months of history."""
    ext = [e for e in ep["events"] if e.get("provenance") == "external"]
    slf = [e for e in ep["events"] if e.get("provenance") == "self"]
    d = {"surface": ep["surface"], "thread": ep["thread"], "first_ts": ep["first_ts"],
         "last_ts": ep["last_ts"], "n_events": len(ep["events"]),
         "external": len(ext), "self": len(slf), "judged_by": "native"}

    # SOLICITED input cannot drive a cycle (see passenger_surfaces): he asked for it, so it is
    # not the world arriving. Silent, like any other non-event.
    if ep["surface"] in (cfg.get("passenger_surfaces") or []):
        d.update(decision="skip", reason="solicited surface — passenger, never driver", silent=True)
        return d

    # NECESSARY condition. Below this nothing happened, and §6.5 says do not even log the skip.
    if len(ext) < cfg["min_external_events"]:
        d.update(decision="skip", reason="no external cause", silent=True)
        return d

    fp = _fingerprint(ep)
    seen = _load(SEEN, {})
    if fp in seen:
        rec = _note_repeat(fp, ext[0].get("content", "") if ext else "")
        d.update(decision="reinforce", reason="already known — strengthened not duplicated",
                 repeat_count=rec["count"], fingerprint=fp)
        if rec["count"] >= cfg["reinforce_threshold"] and not rec.get("derived"):
            belief = ("James has said this %d times — it matters to him disproportionately: %s"
                      % (rec["count"], str(rec.get("sample") or "")[:140]))
            d["derive_belief"] = belief
            # (A) A belief that lives only in a decision log is not a belief. Write it, and mark
            # it derived so it is formed once rather than every time he repeats himself again.
            try:
                import orion_sleep as _sl
                if _sl._memorize(belief, node_type="insight",
                                 tags=["derived", "importance", "james", "repetition"]):
                    store = _load(REINFORCE, {})
                    if fp in store:
                        store[fp]["derived"] = True
                        _save(REINFORCE, store)
            except Exception:
                pass
        return d

    # CORRECTIONS FIRST — before any novelty check. Something that genuinely CHANGED often looks
    # textually similar to the belief it overturns, so a similarity gate running first would
    # suppress exactly the update that matters most (§6.4 ordering).
    hits = _correction_candidates(ep)

    text = " ".join(e.get("content", "") for e in ext)
    affect = _affect_delta(_neuromod())
    perr = _prediction_error(since_ts)
    lw = _learning_weight(text)

    verdict, judged_by = (None, "native")
    if hits:
        # highest-consequence path -> adjudicate before it can reach his head
        if may_call_model:
            hits, judged_by = _adjudicate_correction(hits, cfg)
        else:
            judged_by = "would-adjudicate-correction"
    elif _ambiguous(ep):
        if may_call_model:
            verdict, judged_by = _ask_model_durable(ep, cfg)
        else:
            judged_by = "would-ask-model"
    d["judged_by"] = judged_by

    ext_chars = sum(len(e.get("content") or "") for e in ext)
    score = 1.0
    why = ["external input"]
    if ext_chars < 25 and not hits:
        score -= 1.0        # "hey" is external input and still not worth a thought
        why.append("pleasantry only (%d chars)" % ext_chars)
    if hits:
        score += 5.0
        why.append("CORRECTION (%d)" % len(hits))
    if affect >= cfg["affect_delta"]:
        score += 1.0
        why.append("something landed (affect %.3f)" % affect)
    if perr:
        score += 1.0
        why.append("something didn't fit (%d refuted)" % perr)
    if lw > 0:
        score += lw * 10
        why.append("actively learning (lp %.3f)" % lw)
    gr = _goal_relevance(text)
    if gr > 0:
        score += gr
        why.append("matters to James (goal-relevance %.2f)" % gr)
    d["goal_relevance"] = gr
    d["felt"] = {k: (round(v, 4) if isinstance(v, (int, float)) else None)
                 for k, v in (_neuromod() or {}).items()}
    if verdict is False:
        score -= 1.5
        why.append("model: not durable")
    elif verdict is True:
        score += 1.0
        why.append("model: durable")

    d.update(decision="consolidate" if score >= 1.0 else "drop",
             reason=", ".join(why), score=round(score, 2), fingerprint=fp,
             corrections=len(hits), affect=round(affect, 4), pred_error=perr,
             learning=round(lw, 3))
    d["_corrections"] = hits
    return d


def _turns_for(ep, cfg):
    """Episode -> the shape orion_sleep consumes. Attributed and VERBATIM, replacing a log that
    was truncated at 400 chars and could not tell his voice from James's."""
    return [{"surface": e.get("surface"), "role": "user" if e.get("direction") == "inbound"
             else "assistant", "text": (e.get("content") or "")[:cfg["max_turn_chars"]],
             "ts": e.get("ts"), "actor": e.get("actor"), "provenance": e.get("provenance")}
            for e in ep["events"]]


def _log(d):
    """Record what it DECIDED, not just its rules. Over-filtering is the failure we could not
    otherwise see — and because the raw tier is complete, anything wrongly dropped is replayable."""
    if d.get("silent"):
        return                       # §6.5: nothing happened; do not log the non-event
    try:
        DECISIONS.parent.mkdir(parents=True, exist_ok=True)
        with DECISIONS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in d.items() if not k.startswith("_")},
                               ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def tick(dry=True):
    cfg = config()
    since = float(_load(OFFSET, {"ts": 0}).get("ts", 0))
    evs, _off = _read_new(commit=not dry)
    # Carry UNFINISHED conversations across ticks. The read offset advances every tick, but an
    # episode is only judged once it has gone quiet — so without this buffer the early messages
    # of a live conversation are consumed and thrown away, and the episode is finally judged on
    # nothing but its last message. Every real-time conversation would arrive amputated.
    pend = _load(PENDING, []) if not dry else []
    allev = pend + evs
    if not allev:
        return {"new_events": 0, "episodes": 0, "consolidated": 0, "note": "silence"}
    grouped = episodes(allev, cfg)
    eps = [e for e in grouped if _closed(e, cfg)]
    if not dry:
        still = [ev for e in grouped if not _closed(e, cfg) for ev in e["events"]]
        _save(PENDING, still[-500:])
    stats = {"new_events": len(evs), "carried": len(pend), "episodes": len(eps), "consolidate": 0,
             "reinforce": 0, "drop": 0, "skip": 0, "corrections": 0, "model_calls": 0,
             "fired": 0, "dry_run": dry}
    for ep in eps:
        d = judge(ep, cfg, since, may_call_model=not dry)
        stats[d["decision"] if d["decision"] in stats else "skip"] = \
            stats.get(d["decision"], 0) + 1
        if d.get("judged_by") in ("model", "would-ask-model"):
            stats["model_calls"] += 1
        if d.get("_corrections"):
            stats["corrections"] += len(d["_corrections"])
            if not dry:
                _file_corrections(d["_corrections"], live=not _closed(ep, cfg))
        if d["decision"] == "consolidate":
            if not dry:
                seen = _load(SEEN, {})
                seen[d["fingerprint"]] = time.time()
                if len(seen) > 8000:
                    seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-4000:])
                _save(SEEN, seen)
                if cfg["enabled"]:
                    try:
                        import orion_sleep
                        orion_sleep.run_cycle(reason="episode:%s" % d["thread"],
                                              turns=_turns_for(ep, cfg))
                        stats["fired"] += 1
                    except Exception as e:
                        d["fire_error"] = str(e)[:120]
                    # FELT MEMORY (B). Record the state he was in while this happened, so the
                    # memory has a texture instead of being a database row. Honest caveat: his
                    # drives barely move yet, so early entries will look alike — recording costs
                    # nothing and cannot be reconstructed later if we skip it.
                    try:
                        import orion_sleep as _sl
                        felt = d.get("felt") or {}
                        if felt:
                            _sl._memorize(
                                "While talking with James on %s (%s), my state was %s."
                                % (time.strftime("%b %d %H:%M", time.localtime(ep["last_ts"])),
                                   ep["surface"],
                                   ", ".join("%s=%.3f" % (k, v) for k, v in sorted(felt.items())
                                             if isinstance(v, (int, float)))),
                                node_type="fact", tags=["felt", "affect", "episode", "self"])
                    except Exception:
                        pass
                    # ...and ask what this revealed about THE WORLD that he could go learn.
                    # This is where idle time stops being "think about myself": the questions
                    # come from what James actually talks about, never from Orion's own
                    # navel (orion_questions refuses self-referential questions natively).
                    try:
                        import orion_questions
                        qs = orion_questions.propose(
                            " ".join(e.get("content", "") for e in ep["events"]),
                            source="conversation:%s" % ep["surface"])
                        if qs:
                            d["questions_raised"] = qs
                            stats["questions"] = stats.get("questions", 0) + len(qs)
                    except Exception:
                        pass
        if not dry:
            _log(d)
        else:
            print("  %-11s %-9s ext=%-3d self=%-3d score=%-5s [%s] %s"
                  % (d["decision"], (d.get("surface") or "")[:9], d["external"], d["self"],
                     d.get("score", "-"), d.get("judged_by"), d.get("reason", "")[:70]))
    if not dry:
        _save(STATE / "salience_last_affect.json", _neuromod())
        # Anything he has been carrying that no conversation picked up goes out through the
        # governor. Piggybacks on this tick so it needs no daemon of its own.
        try:
            import orion_raise
            # confirm FIRST: anything we tried to send is either proven delivered (chat.db) or
            # becomes due again. Marking "raised" on a fire-and-forget publish lost a question
            # permanently on 2026-08-31 — proof comes from Apple's record or it did not happen.
            orion_raise.confirm_or_retry()
            orion_raise.send_due()
        except Exception:
            pass
    return stats


def status():
    cfg = config()
    print("enabled          :", cfg["enabled"], "(false = decides but fires nothing)")
    print("offset           :", _load(OFFSET, {"offset": 0}).get("offset", 0),
          "of", (P.RAW.stat().st_size if P.RAW.exists() else 0), "bytes")
    print("model budget     : %d of %d left today" % (max(0, _budget_left(cfg)),
                                                      cfg["model_calls_per_day"]))
    print("decisions logged :", sum(1 for _ in DECISIONS.open()) if DECISIONS.exists() else 0)
    print("open corrections :", sum(1 for _ in CORRECTIONS.open()) if CORRECTIONS.exists() else 0)
    print("invariants (hard-coded, not configurable):")
    for i in INVARIANTS:
        print("   -", i)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--status"
    if arg == "--dry-run":
        print(json.dumps(tick(dry=True), indent=1))
    elif arg == "--tick":
        print(json.dumps(tick(dry=False), indent=1))
    elif arg == "--status":
        status()
    elif arg == "--init":
        # Start the gate from NOW. Without this its first live tick replays the entire archive
        # from offset 0 and files five months of historical corrections at once — which would
        # bury him in old business the moment the gate wakes up.
        sz = P.RAW.stat().st_size if P.RAW.exists() else 0
        _save(OFFSET, {"offset": sz, "ts": time.time()})
        print("gate offset initialised at %d bytes — it starts from now, not from history" % sz)
    elif arg == "--config":
        print(json.dumps(config(), indent=1))
    elif arg == "--decisions":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        if DECISIONS.exists():
            for line in DECISIONS.read_text(encoding="utf-8").splitlines()[-n:]:
                print(" ", line[:200])
    else:
        print(__doc__)
