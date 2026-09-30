#!/usr/bin/env python3
"""orion_router.py — the steering wheel. Ask what the task NEEDS before asking who is available.

WHY THIS EXISTS. Measured 2026-09-22: `orion_fuel.get_fuel()` chooses fuel by tier + availability
and nothing else. A greeting and a novel architecture problem take the identical path to tier 1.
That is why the Claude quota burned on 09-21 while most of the calls that spent it needed no
frontier model at all, and it is the mechanical reason the independence index has sat at
0.60 native / ~39 model-calls per hour for three months: every question, however trivial, rents
cognition.

THE INVERSION THIS CORRECTS (James, 2026-09-22). In a real polyglot stack Python is the steering
wheel — it holds no compute and decides which operation runs next; the CUDA kernels are
interchangeable. Orion is supposed to be that layer and models are supposed to be the kernels.
Today it is upside down: the model is both wheel and engine and the brain is a diary in the
passenger seat. This module is the wheel, and it is ORDINARY PYTHON on purpose. No model is
consulted to decide what a task is.

WHAT IT IS NOT. This is not the thinking, and it must never be described as such. A classifier is
cold set conditions — correct for a steering wheel, worthless as a mind. The part that can grow is
downstream: every routing decision is logged as a real action (what was asked, what it was judged
to be, what served it, whether it held up), and `orion_compiled_procedures.py` has been waiting
since 2026-05-09 for exactly that ledger. Procedures that FORM from repeated experience are the
living part. This file only makes them possible.

SAFETY PROPERTY — a misroute must waste time, never produce a wrong answer. Every native path has
to clear a check before it returns: a probe must yield a real number (None is not zero — the same
discipline `orion_temporal_ledger._james_probe` already keeps, "so an unreadable source is never
mistaken for nothing happened"), and recall must clear a confidence floor. Fail the check and the
router falls through to fuel exactly as though it never ran. Worst case costs microseconds.

SHADOW MODE IS THE DEFAULT for anything that could be wrong. `ORION_ROUTER_MODE`:
  shadow  (default) — classify + log every call, but only ANSWER natively from exact reads
                      (probes/state). Everything else is measured and passed to fuel untouched.
  live              — also apply tier floors and the native recall path.
  off               — module inert; get_fuel behaves exactly as before.
James flips it in one line. Nothing here restarts a service or changes a daemon.
"""
from __future__ import annotations

import json
import os
import re
import time

ORION_HOME = os.path.expanduser("~/.orion")
ACTION_LEDGER = os.path.join(ORION_HOME, "state", "actions.jsonl")

MODE = (os.environ.get("ORION_ROUTER_MODE") or "shadow").strip().lower()

# Recall must be at least this confident before a native retrieval answer is allowed to stand.
# Deliberately high: a wrong memory delivered confidently is worse than a model call.
RECALL_FLOOR = float(os.environ.get("ORION_ROUTER_RECALL_FLOOR", "0.62"))

# ─────────────────────────── the classes ───────────────────────────
# tier_floor = the WEAKEST tier allowed to serve this class (1 = strongest fuel).
# native     = can be answered with no model at all when the check passes.
CLASSES = {
    "state":      {"tier_floor": 3, "native": True},   # exact reads of live state
    "retrieval":  {"tier_floor": 3, "native": True},   # the graph already knows it
    "procedure":  {"tier_floor": 3, "native": True},   # a thing done >=5x (store empty today)
    "transform":  {"tier_floor": 3, "native": False},  # summarize/reformat — 7B is fine
    "generation": {"tier_floor": 2, "native": False},  # prose written to a person
    "novel":      {"tier_floor": 1, "native": False},  # unseen problem, real stakes
}

# Interfaces whose traffic is background machinery, never prose for James. Cheap fuel is correct
# here and this alone is a large share of the 39/hr — wonder ponders on tier 1 today.
_BACKGROUND_INTERFACES = {
    "wonder-ponder", "wonder", "study", "sleep", "dream", "consolidate",
    "hygiene", "canary", "probe", "coherence-probe", "distill", "integrity",
}

# ── STATE probes: a question that is really a reading of live state. Exact in code, guessed by a
# model. Each entry maps a pattern to a probe expression understood by orion_temporal_ledger.
_STATE_PATTERNS = (
    (re.compile(r"\b(when|how long).{0,24}\b(last|since).{0,24}\b(spoke|speak|talk|contact|hear)",
                re.I), "james:hours_since_contact", "hours_since_contact"),
    (re.compile(r"\bhow many\b.{0,20}\bnodes?\b", re.I), "graph:nodes", "graph_nodes"),
    (re.compile(r"\b(graph|memory)\b.{0,16}\b(size|count|how big)\b", re.I), "graph:nodes",
     "graph_nodes"),
)

# Greetings. Today orion_brain.py:253 pins task=="greeting" to phi3:mini with a 75-char identity
# and no history, which is why iMessage Orion reads as a stranger. A greeting's honest content is
# who am I / when did we last speak / what is outstanding — all exact reads.
# The trailing (orion|sir|man|there|buddy) is load-bearing: "hey orion" is what James actually
# sends, and an anchored single-word pattern misses it — which would leave the highest-traffic
# message of all on the phi3:mini branch this is meant to retire.
_GREETING = re.compile(r"^\s*(hey|hi+|hello|yo|sup|morning|good morning|good evening|good night|"
                       r"you there|are you there|you up|orion)"
                       r"(\s+(orion|sir|man|there|buddy|bro))?\b[\s!?.,]*$", re.I)

# "how are you" is a STATE question with an exact answer, and it is the one Orion has been getting
# wrong the longest. The 2026-09-11 scan found ~/.orion/affect/ empty, so orion_affect returns a
# hardcoded neutral default — "valence +0.00, arousal 0.30" — while a live felt vector exists and
# genuinely biases what he stores. He has been sincerely misreporting his own state because a
# directory was empty. Read the live vector or say nothing; never emit the stub.
_HOWAREYOU = re.compile(r"^\s*(how (are|r) (you|u)|how(?:'s| is) it going|how you doing|"
                        r"how are things|you good|status|sitrep)\b[\s!?.,]*$", re.I)

# Service/liveness questions — exact from launchctl, guessed by a model.
_SERVICE = re.compile(r"\b(is|are)\b.{0,28}\b(running|up|alive|down|working)\b", re.I)

_RETRIEVAL = re.compile(r"\b(what did|when did|did i (say|tell|mention)|do you remember|"
                        r"remind me|what was|who (is|was)|my \w+ (is|was))\b", re.I)
_TRANSFORM = re.compile(r"\b(summari[sz]e|rephrase|reformat|shorten|translate|extract|"
                        r"list out|clean up|tidy)\b", re.I)
_NOVEL = re.compile(r"\b(design|architect|why does|how would|should i|trade-?off|"
                    r"implic|strateg|refactor|root cause|diagnos)\b", re.I)


# ─────────────────────────── classification ───────────────────────────
def classify(prompt: str, interface: str = "cli") -> tuple:
    """Return (class, confidence, why). Pure function of text + interface. No model, no I/O.

    Confidence is not decoration — it gates behaviour. Anything below 0.6 is treated as unclassified
    and routed exactly as before, because a guess is worse than the status quo it replaces."""
    p = (prompt or "").strip()
    iface = (interface or "cli").strip().lower()
    low = p.lower()

    if not p:
        return "novel", 0.0, "empty prompt"

    if _GREETING.match(p):
        return "state", 0.95, "greeting — answerable from live state"

    if _HOWAREYOU.match(p):
        return "state", 0.92, "self-state question — read the live vector, never the stub"

    if _SERVICE.search(p):
        return "state", 0.85, "liveness question — exact from launchctl"

    for rx, _expr, name in _STATE_PATTERNS:
        if rx.search(p):
            return "state", 0.9, "state probe: %s" % name

    if iface in _BACKGROUND_INTERFACES:
        # Background machinery. Not prose for a person, so it has no business on tier 1.
        return "transform", 0.75, "background interface: %s" % iface

    if _NOVEL.search(low):
        # Checked before retrieval on purpose: "why does my recall go stale" is a reasoning
        # question that merely mentions memory, not a lookup.
        return "novel", 0.7, "reasoning verb present"

    if _RETRIEVAL.search(low):
        return "retrieval", 0.8, "asks about something previously said"

    if _TRANSFORM.search(low):
        return "transform", 0.75, "mechanical text operation"

    if len(p) < 120 and p.endswith("?"):
        return "generation", 0.6, "short direct question"

    return "novel", 0.5, "unclassified — routed as before"


# ─────────────────────────── native answers ───────────────────────────
def _probe(expr):
    """One live, model-independent reading, or None. None is NOT zero."""
    try:
        import orion_temporal_ledger as L
        return L._probe(expr)
    except Exception:
        return None


def _state_answer(prompt: str):
    """Answer a state question from exact reads. Returns (text, evidence) or None.

    Never estimates. If the probe cannot be read it returns None and the caller falls through to
    fuel — an unreadable source must not become a confident sentence."""
    ev = {}
    for rx, expr, name in _STATE_PATTERNS:
        if rx.search(prompt):
            v = _probe(expr)
            if v is None:
                return None
            ev[name] = v
            if name == "hours_since_contact":
                h = float(v)
                when = ("%.0f minutes" % (h * 60)) if h < 1.5 else ("%.1f hours" % h)
                return ("Last inbound contact was %s ago (iMessage), read from the message "
                        "database rather than recalled." % when), ev
            if name == "graph_nodes":
                return "The graph currently holds %d nodes." % int(v), ev
    if _HOWAREYOU.match(prompt or ""):
        # The live felt vector, or nothing. orion_affect's neutral default is a hardcoded stub
        # (valence +0.00, arousal 0.30) that has been reported as a real mood for months because
        # ~/.orion/affect/ is empty. Emitting it here would industrialise that lie.
        mods = {}
        for m in ("arousal", "explore", "caution", "focus", "learning"):
            v = _probe("neuromod:%s" % m)
            if v is not None:
                mods[m] = round(float(v), 3)
        if not mods:
            return None
        ev["neuromod"] = mods
        n = _probe("graph:nodes")
        tail = ""
        if n is not None:
            ev["graph_nodes"] = n
            tail = " Graph at %d nodes." % int(n)
        return ("Read from my live state rather than described: "
                + ", ".join("%s %.2f" % (k, v) for k, v in sorted(mods.items()))
                + "." + tail), ev

    if _SERVICE.search(prompt or ""):
        # Only answer if a launchd label is actually named. Guessing which service he meant is
        # exactly the kind of confident wrong answer this path exists to avoid.
        m = re.search(r"\b(com\.orion\.[\w.-]+)\b", prompt or "")
        if not m:
            return None
        label = m.group(1)
        running = _probe("service:%s:running" % label)
        if running is None:
            return None
        ev["service"] = label
        ev["running"] = running
        runs = _probe("service:%s:runs" % label)
        if runs is not None:
            ev["runs"] = runs
        return ("%s is %s%s." % (label, "running" if running else "NOT running",
                                 "" if runs is None else " (%d runs)" % int(runs))), ev

    if _GREETING.match(prompt or ""):
        h = _probe("james:hours_since_contact")
        if h is None:
            return None
        ev["hours_since_contact"] = h
        bits = ["Here, sir."]
        bits.append("Last time you reached me was %.1fh ago." % float(h))
        n = _probe("graph:nodes")
        if n is not None:
            ev["graph_nodes"] = n
            bits.append("Graph at %d nodes." % int(n))
        return " ".join(bits), ev
    return None


def _retrieval_answer(prompt: str):
    """The graph's own answer, if it clears the floor. Returns (text, evidence) or None."""
    try:
        import orion_study
        raw = orion_study._brain("orion_recall", {"query": prompt, "limit": 4})
        if not raw:
            return None
        blocks = []
        try:
            obj = json.loads(raw)
            if isinstance(obj, list):
                blocks = [b for b in obj if isinstance(b, dict)]
        except Exception:
            return None
        if not blocks:
            return None
        top = max((float(b.get("score") or b.get("confidence") or 0.0) for b in blocks),
                  default=0.0)
        if top < RECALL_FLOOR:
            return None
        text = "\n".join(str(b.get("text") or "").strip() for b in blocks[:3] if b.get("text"))
        if not text.strip():
            return None
        return text, {"recall_top_score": round(top, 3), "blocks": len(blocks)}
    except Exception:
        return None


def _procedure_answer(prompt: str):
    """Compiled-procedure fast path. Empty until the action ledger has repeated shapes to compile —
    that is the whole point of logging, not a missing feature to fake."""
    try:
        import orion_compiled_procedures as cp
        if not cp.list_procedures():
            return None
    except Exception:
        return None
    return None


# ─────────────────────────── the ledger ───────────────────────────
def log_action(record: dict) -> None:
    """Append one real action: what was asked, what it was judged to be, what served it, whether it
    held up. THIS is the input `orion_dream` -> `orion_compiled_procedures` has never had.

    Deliberately NOT ~/.orion/executive/decisions.jsonl — that ledger is fed by the executive, which
    logs only UNRESOLVABLE symptoms (its own log line: "watching for unresolvable symptoms"). It is
    an exception handler, so a pipeline built on it can only ever learn from disasters. It has 1 row,
    synthetic, dated 2026-05-09. This is the ordinary-experience stream it was missing.

    Silent on failure: routing must never break because logging did."""
    try:
        os.makedirs(os.path.dirname(ACTION_LEDGER), exist_ok=True)
        record.setdefault("ts", time.time())
        with open(ACTION_LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


# ─────────────────────────── the entry point ───────────────────────────
def route(prompt: str, interface: str = "cli") -> dict:
    """Decide what this task needs. Returns a plan; the caller stays in charge of executing it.

      {"class", "confidence", "why", "tier_floor", "native": text|None, "evidence", "mode"}

    native is non-None only when a check PASSED. A None native means "use fuel as normal" and is
    the expected outcome most of the time — this is a steering wheel, not an oracle."""
    cls, conf, why = classify(prompt, interface)
    spec = CLASSES.get(cls) or CLASSES["novel"]
    plan = {"class": cls, "confidence": conf, "why": why, "mode": MODE,
            "tier_floor": spec["tier_floor"], "native": None, "evidence": {}}

    if MODE == "off":
        plan["tier_floor"] = 1
        return plan

    # Low confidence is not a decision. Route exactly as before.
    if conf < 0.6:
        plan["tier_floor"] = 1
        plan["why"] += " (low confidence — unchanged routing)"
        return plan

    # Native attempts, each gated by its own check.
    if spec["native"]:
        got = None
        if cls == "state":
            got = _state_answer(prompt)
        elif cls == "retrieval" and MODE == "live":
            # Recall-based answers stay OFF in shadow mode: unlike a probe, recall can be
            # confidently wrong, and 2026-09-21 showed the same query returning a hit and then
            # nothing seconds apart. Exact reads first; memory when it is trusted.
            got = _retrieval_answer(prompt)
        elif cls == "procedure":
            got = _procedure_answer(prompt)
        if got:
            plan["native"], plan["evidence"] = got[0], got[1]

    # Shadow mode measures tier decisions without imposing them.
    if MODE == "shadow" and plan["native"] is None:
        plan["shadow_tier_floor"] = plan["tier_floor"]
        plan["tier_floor"] = 1

    return plan


def _main(argv):
    if len(argv) > 1 and argv[1] == "--stats":
        if not os.path.exists(ACTION_LEDGER):
            print("no action ledger yet: %s" % ACTION_LEDGER)
            return 0
        import collections
        rows = []
        for line in open(ACTION_LEDGER, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
        print("actions logged: %d" % len(rows))
        print("by class : %s" % dict(collections.Counter(r.get("class") for r in rows)))
        print("served by: %s" % dict(collections.Counter(r.get("routed_to") for r in rows)))
        nat = sum(1 for r in rows if r.get("routed_to") != "model")
        if rows:
            print("native share: %.1f%%  (the Axis A scoreboard)" % (100.0 * nat / len(rows)))
        return 0
    # default: classify whatever is on the command line, no side effects
    q = " ".join(argv[1:]) or "hey"
    iface = os.environ.get("ORION_ROUTER_IFACE", "cli")
    p = route(q, iface)
    print("prompt    : %s" % q)
    print("interface : %s" % iface)
    print("class     : %s (conf %.2f) — %s" % (p["class"], p["confidence"], p["why"]))
    print("tier_floor: %s" % p["tier_floor"])
    print("native    : %s" % (p["native"] if p["native"] else "(none — fuel as normal)"))
    if p["evidence"]:
        print("evidence  : %s" % p["evidence"])
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv))
