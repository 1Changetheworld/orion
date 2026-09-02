#!/usr/bin/env python3
"""
orion_curiosity.py — THE CURIOSITY SEED (v2: ADAPTIVE).

Genuine curiosity, not performed: Orion commits GENUINELY-UNCERTAIN, machine-checkable FORWARD
PREDICTIONS about its real substrate — natively, NO model (truth-serum) — and LEARNS from its own
confirmed/refuted history so its predictions get BETTER over time. LEARNING-PROGRESS (accuracy
climbing) is the intrinsic reward; where it climbs is the fertile unknown worth pursuing; where it
stays flat is either mastered (stop betting) or noise (ignore).

v2 fix over v1: v1 used FIXED heuristics (e.g. "a drive will move 0.04") that were miscalibrated and
refuted 100% forever — no learning. v2 keeps a per-topic learned model (the real scale of change),
calibrated online toward a genuine-but-achievable bet (~60% hit), so accuracy CLIMBS as it learns and
plateaus once mastered — real learning-progress.

Built ON existing machinery: orion_temporal_ledger (record + native _probe/_eval_check + check_due).
ANTI-PATHOLOGY GATE: only external probe-checkable predictions count. Safe: predicts only, no
actuation, no self-modification, never raises.

CLI:  --tick (predict -> resolve -> learn -> reward)  |  --predict  |  --lp  |  --show  |  --model
"""
from __future__ import annotations
import json, os, re, sys, time
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/orion-code"))
import orion_temporal_ledger as tl

STATE = Path(os.path.expanduser("~/.orion/state"))
HIST = STATE / "curiosity_hist.json"
MODEL = STATE / "curiosity_model.json"      # per-topic LEARNED dynamics (the adaptive core)
LP = STATE / "curiosity_lp.json"
PRED_FILE = Path(os.path.expanduser("~/.orion/reason/predictions.jsonl"))
KEY_PREFIX = "curio:"
LEARN_MARK = STATE / "curiosity_learned_ts.json"   # high-water mark of learned resolutions

WATCH_SVCS = ["com.orion.reason", "com.orion.neuromod", "com.orion.wonder", "com.orion.dream",
              "com.orion.workspace", "com.orion.perceive", "com.orion.dmn", "com.orion.will"]
MODULATORS = ["arousal", "learning", "explore", "caution", "focus"]
TARGET_HIT = 0.60         # a genuine-but-achievable bet: calibrate deltas toward ~60% hit-rate


def _probe(e):
    try:
        return tl._probe(e)
    except Exception:
        return None


def _load(p, d):
    try:
        return json.loads(p.read_text())
    except Exception:
        return d


def _save(p, o):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        t = p.with_suffix(p.suffix + ".tmp"); t.write_text(json.dumps(o, indent=1)); t.replace(p)
    except Exception:
        pass


# ───────────── history (for the very first estimate before outcomes exist) ─────────────
def _snap():
    h = _load(HIST, [])
    s = {"ts": time.time(), "nodes": _probe("graph:nodes")}
    for m in MODULATORS:
        s[f"m_{m}"] = _probe(f"neuromod:{m}")
    for svc in WATCH_SVCS:
        s[f"r_{svc}"] = _probe(f"service:{svc}:runs")
    h.append(s)
    h = [x for x in h if x.get("ts", 0) > time.time() - 14 * 86400][-800:]
    _save(HIST, h)
    return h


# ───────────── the ADAPTIVE MODEL: per-topic learned change-scale (`delta`) ─────────────
def _model():
    return _load(MODEL, {})


def _topic_delta(model, topic, seed):
    """Current learned delta for a topic; seed it the first time from raw history."""
    m = model.get(topic)
    if m and isinstance(m.get("delta"), (int, float)):
        return float(m["delta"])
    model[topic] = {"delta": float(seed), "hits": [], "n": 0}
    return float(seed)


# ───────────── PREDICT — genuinely-uncertain bets sized by the LEARNED model ─────────────
def _commit(topic, label, claim, obs, check, horizon, prior):
    try:
        v = tl._eval_check(check)
    except Exception:
        v = None
    if v is not False:                    # only bet where it's currently FALSE (a real future-bet)
        return None
    tl.record(key=f"{KEY_PREFIX}{topic}", label=label, claim=claim, observable=obs,
              kind="operational", horizon_hours=horizon, check=check, prior=prior,
              native_supported=None)
    return (topic, check)


# ── James's world ─────────────────────────────────────────────────────────────────────────────
_STOP = set(("about", "after", "again", "could", "would", "should", "there", "their", "these",
             "those", "which", "while", "where", "still", "thing", "things", "right", "going",
             "doing", "being", "because", "before", "between", "everything", "something",
             "anything", "orion", "sir", "please", "thanks", "today", "tomorrow", "yesterday",
             "tonight", "morning", "night", "know", "think", "want", "need", "make", "made",
             "have", "here", "what", "when", "your", "with", "that", "this", "from", "just",
             "like", "does", "isnt", "dont", "cant", "wont", "didnt", "youre", "thats"))


def _james_recent(hours=72, limit=60):
    """His actual words, from Apple's database. Never his own — only what James wrote."""
    import sqlite3
    out = []
    try:
        db = os.path.expanduser("~/Library/Messages/chat.db")
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        apple = (time.time() - hours * 3600 - 978307200) * 1e9
        rows = con.execute("SELECT text, attributedBody FROM message WHERE is_from_me=0 "
                           "AND date >= ? ORDER BY ROWID DESC LIMIT ?", (apple, limit))
        for r in rows:
            t = r[0]
            if not t and r[1] is not None:
                try:
                    sys.path.insert(0, os.path.expanduser("~/server_data/agents"))
                    from imessage_monitor import _decode_attributed
                    t = _decode_attributed(r[1])
                except Exception:
                    t = None
            if t:
                out.append(t)
        con.close()
    except Exception:
        return []
    return out


def _james_topics(k=2):
    """Words he is actually using — the candidates for 'will he come back to this?'. Frequency
    alone, deliberately: a cleverer selector would be another thing to be wrong about, and the
    prediction being wrong is the point."""
    import collections
    import re as _re
    counts = collections.Counter()
    for msg in _james_recent():
        for w in _re.findall(r"[a-zA-Z]{5,}", msg.lower()):
            if w not in _STOP:
                counts[w] += 1
    # something he said more than once, but not so constant it is a certainty
    return [w for w, n in counts.most_common(12) if 2 <= n <= 8][:k]


def predict(model, horizon_hours: float = 2.0):
    h = _snap()
    made = []

    # GRAPH GROWTH — learned margin (starts from raw growth rate, then calibrated by outcomes)
    n = _probe("graph:nodes")
    if n is not None and not model.get("graph_growth", {}).get("mastered"):
        seed = 12.0
        if len(h) >= 2 and h[0].get("nodes") and h[-1].get("nodes"):
            dt = (h[-1]["ts"] - h[0]["ts"]) / 3600.0
            if dt > 0.5:
                seed = max(3.0, (h[-1]["nodes"] - h[0]["nodes"]) / dt * horizon_hours)
        d = _topic_delta(model, "graph_growth", seed)
        target = int(round(n + max(1.0, d)))
        r = _commit("graph_growth", f"my memory will pass {target} nodes",
                    f"graph exceeds {target} within {horizon_hours:g}h (now {int(n)}, learned +{d:.1f}).",
                    ["graph", "nodes", "growth"], f"graph:nodes >= {target}", horizon_hours, prior=0.3)
        if r: made.append(r)

    # SERVICE ACTIVITY — learned increment per service (perceive ticks fast; stable ones -> ~0,
    # so the bet becomes currently-true and is auto-skipped = curiosity abandons the mastered)
    for svc in WATCH_SVCS:
        runs = _probe(f"service:{svc}:runs")
        if runs is None or model.get(f"svc:{svc}", {}).get("mastered"):
            continue
        d = _topic_delta(model, f"svc:{svc}", 1.0)
        step = max(1, int(round(d)))
        r = _commit(f"svc:{svc}", f"{svc} will cycle ~+{step}",
                    f"{svc} runs reaches {int(runs)+step} within {horizon_hours:g}h (now {int(runs)}, learned +{d:.2f}).",
                    ["service", svc], f"service:{svc}:runs >= {int(runs)+step}", horizon_hours, prior=0.4)
        if r: made.append(r)

    # NEUROMOD DYNAMICS — learned move-scale (v1's 0.04 was too big; real is ~0.01) + recent direction
    for m in MODULATORS:
        cur = _probe(f"neuromod:{m}")
        if cur is None or model.get(f"mod:{m}", {}).get("mastered"):
            continue
        prev = next((s.get(f"m_{m}") for s in reversed(h[:-1]) if isinstance(s.get(f"m_{m}"), (int, float))), None)
        rising = (prev is None) or (cur >= prev)
        d = _topic_delta(model, f"mod:{m}", 0.012)
        thr = round(cur + (d if rising else -d), 4)
        op = ">=" if rising else "<="
        r = _commit(f"mod:{m}", f"my {m} drive moves {'up' if rising else 'down'} ~{d:.3f}",
                    f"neuromod:{m} {op} {thr} within {horizon_hours:g}h (now {cur:.4f}, learned {d:.4f}).",
                    ["neuromod", m], f"neuromod:{m} {op} {thr}", horizon_hours, prior=0.4)
        if r: made.append(r)

    # ── JAMES'S WORLD — the only genuinely uncertain, genuinely learnable thing he has ──
    now_ts = time.time()
    try:
        d = _topic_delta(model, "james:contact", 6.0)      # delta is HOURS here, not magnitude
        r = _commit("james:contact",
                    "James will message me within %.0fh" % d,
                    "James sends at least one message in the next %.0fh (learned window)." % d,
                    ["james", "contact"],
                    "james:msgs_since:%f >= 1" % now_ts, d, prior=0.5)
        if r:
            made.append(r)
        for w in _james_topics(2):
            dw = _topic_delta(model, "james:topic:%s" % w, 24.0)
            r = _commit("james:topic:%s" % w,
                        "James will bring up '%s' again within %.0fh" % (w, dw),
                        "James mentions '%s' at least once in the next %.0fh." % (w, dw),
                        ["james", "topic", w],
                        "james:mentions:%s:since:%f >= 1" % (w, now_ts), dw, prior=0.4)
            if r:
                made.append(r)
    except Exception:
        pass

    _save(MODEL, model)
    return made


# ───────────── LEARN — calibrate each topic's delta toward a genuine-but-achievable bet ─────────────
DELTA_BOUNDS = {"graph_growth": (1.0, 300.0), "mod": (0.002, 0.08), "svc": (1.0, 50.0)}


def _bounds(topic):
    if topic.startswith("mod:"):
        return DELTA_BOUNDS["mod"]
    if topic.startswith("svc:"):
        return DELTA_BOUNDS["svc"]
    if topic.startswith("james:"):
        return (0.5, 168.0)          # hours: half an hour to a week
    return DELTA_BOUNDS.get(topic, (1e-3, 1e6))


def learn(model):
    """Ingest predictions resolved since last learn into per-topic hit-windows, THEN nudge each
    touched topic's delta ONCE (based on its recent hit-rate) — not once per outcome (that
    compounded and blew up). A topic whose hit-rate is stuck extreme (always/never, with enough
    data) is DETERMINISTIC/unlearnable -> mark it 'mastered' so predict() abandons it. That's
    correct curiosity: stop betting the certain/impossible, spend attention on the learnable."""
    last = float(_load(LEARN_MARK, {"ts": 0}).get("ts", 0))
    newmax = last
    if not PRED_FILE.exists():
        return {"updated": 0, "touched": 0}
    touched = {}
    for line in PRED_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not str(r.get("key", "")).startswith(KEY_PREFIX):
            continue
        if r.get("status") not in ("confirmed", "refuted"):
            continue
        rts = float(r.get("resolved_ts") or 0)
        if rts <= last:
            continue
        newmax = max(newmax, rts)
        topic = str(r["key"])[len(KEY_PREFIX):]
        m = model.setdefault(topic, {"delta": 1.0, "hits": [], "n": 0})
        m["hits"] = (m.get("hits", []) + [1 if r["status"] == "confirmed" else 0])[-20:]
        m["n"] = m.get("n", 0) + 1
        touched[topic] = m
    # ONE nudge per touched topic, from its recent window
    for topic, m in touched.items():
        hits = m.get("hits", [])
        if not hits:
            continue
        rate = sum(hits) / len(hits)
        lo, hi = _bounds(topic)
        d = min(hi, max(lo, float(m.get("delta", lo))))
        # For a machine topic delta is a MAGNITUDE (missing = bet too big -> shrink). For a
        # james: topic it is a HORIZON (missing = did not wait long enough -> GROW). Same loop,
        # opposite sign; getting this backwards would train the window toward zero and guarantee
        # he is always wrong.
        horizon = topic.startswith("james:")
        if rate < TARGET_HIT - 0.05:
            d = min(hi, d * 1.25) if horizon else max(lo, d * 0.85)
        elif rate > TARGET_HIT + 0.05:
            d = max(lo, d * 0.85) if horizon else min(hi, d * 1.15)
        m["delta"] = d
        # deterministic / unlearnable? (stuck at a rail despite calibration) -> abandon it
        m["mastered"] = (len(hits) >= 8 and (rate >= 0.92 or rate <= 0.08))
    _save(MODEL, model)
    _save(LEARN_MARK, {"ts": newmax})
    return {"updated": sum(1 for _ in touched), "touched": len(touched)}


# ───────────── LEARNING-PROGRESS reward (accuracy climbing = the fertile unknown) ─────────────
def _resolved_by_topic():
    by = {}
    if not PRED_FILE.exists():
        return by
    for line in PRED_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not str(r.get("key", "")).startswith(KEY_PREFIX):
            continue
        chk = r.get("check") or ""
        if not any(chk.startswith(p) for p in ("service:", "graph:", "neuromod:", "refire:")):
            continue          # anti-pathology gate: external probe-checkable only
        if r.get("status") not in ("confirmed", "refuted"):
            continue
        by.setdefault(str(r["key"])[len(KEY_PREFIX):], []).append(
            (r.get("resolved_ts") or r.get("made_ts") or 0, 1.0 if r["status"] == "confirmed" else 0.0))
    return by


def learning_progress():
    by = _resolved_by_topic()
    lp, tot_lp, tot_acc = {}, 0.0, 0.0
    for topic, rows in by.items():
        rows.sort()
        outs = [o for _, o in rows][-30:]           # recent window
        acc = sum(outs) / len(outs)
        if len(outs) >= 6:
            half = len(outs) // 2
            prog = max(0.0, sum(outs[half:]) / (len(outs) - half) - sum(outs[:half]) / half)
        else:
            prog = 0.0
        lp[topic] = {"n": len(outs), "accuracy": round(acc, 3), "learning_progress": round(prog, 3)}
        tot_lp += prog; tot_acc += acc
    summ = {"topics": len(by), "resolved": sum(len(v) for v in by.values()),
            "mean_lp": round(tot_lp / len(by), 3) if by else 0.0,
            "mean_acc": round(tot_acc / len(by), 3) if by else 0.0,
            "max_lp": round(max((d["learning_progress"] for d in lp.values()), default=0.0), 3)}
    out = {"ts": time.time(), "summary": summ, "by_topic": lp}
    _save(LP, out)
    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "--show"
    model = _model()
    if arg == "--predict":
        made = predict(model)
        print(f"committed {len(made)}:"); [print("  ", t, "->", c) for t, c in made]
    elif arg == "--lp":
        print(json.dumps(learning_progress(), indent=1))
    elif arg == "--model":
        print(json.dumps(model, indent=1))
    elif arg == "--tick":
        made = predict(model)
        try:
            swept = tl.check_due()
        except Exception as e:
            swept = {"error": str(e)[:80]}
        learned = learn(_model())
        out = learning_progress()
        print(f"tick: +{len(made)} preds | swept={swept} | learned={learned} | "
              f"LP topics={out['summary']['topics']} mean_lp={out['summary']['mean_lp']} "
              f"max_lp={out['summary']['max_lp']} mean_acc={out['summary']['mean_acc']}")
    else:
        print(json.dumps(_load(LP, {"note": "run --tick"}), indent=1))


if __name__ == "__main__":
    main()
