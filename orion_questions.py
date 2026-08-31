#!/usr/bin/env python3
"""
orion_questions.py — where Orion's study questions come from, and why they point OUTWARD.

THE PROBLEM THIS SOLVES. orion_study.py says it is "triggered by Orion's OWN wonder questions",
but no code ever did that — and it is just as well, because his open wonder threads are:
    "Why do I exist?"  "What am I, beyond whichever model is fueling me?"
    "How does remembering become understanding?"  "Who am I in the gap between thoughts?"
Every one points inward. Pointing the open web at those produces better-sourced navel-gazing —
the exact pathology this whole build removed, wearing a lab coat.

So questions come from the one genuinely external, genuinely learnable thing he has: WHAT JAMES
ACTUALLY TALKS ABOUT. The salience gate already segments those conversations. When one is worth
consolidating, it can also ask: what did this conversation reveal that I do not understand about
the world?

That closes the loop the build has been assembling all along:
    perceive (James speaks) -> salience (this mattered) -> question (what don't I know?)
    -> study (go read the world) -> memory -> and it shows up next time he needs it.

Idle time stops being "think about myself" and becomes "go learn the thing that would have made
me more useful to him."

THE ANTI-NAVEL-GAZING GATE. A question about Orion, his memory, his architecture or his existence
is REFUSED here, natively, before any model call. Not because those questions are worthless — he
holds four of them as eternal threads — but because the open web cannot answer them, and letting
them into the study queue rebuilds the self-consumption loop with citations attached.

Nothing here sends anything or acts. It proposes questions and holds them in a queue.

  --list           the queue
  --add "<q>"      add one by hand
  --propose "<text>"  what it would ask from a piece of conversation (writes nothing)
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/orion-code"))

QUEUE = Path(os.path.expanduser("~/.orion/state/study_questions.json"))
MAX_OPEN = 40
MAX_PER_EPISODE = 2

# Refused natively: the open web cannot answer these, and they are how the loop turns inward.
_SELF_PATTERNS = (
    r"\bmy (memory|mind|self|existence|architecture|brain|graph|purpose|consciousness)\b",
    r"\bam i\b", r"\bwho am i\b", r"\bwhy do i exist\b", r"\bwhat am i\b",
    r"\borion('s)?\b", r"\bmy own\b", r"\bmyself\b",
    r"\bthis system\b", r"\bmy (fuel|model|daemon|node|cycle)s?\b",
)


def _load():
    try:
        return json.loads(QUEUE.read_text(encoding="utf-8"))
    except Exception:
        return {"open": [], "done": []}


def _save(d):
    try:
        QUEUE.parent.mkdir(parents=True, exist_ok=True)
        tmp = QUEUE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(QUEUE)
    except Exception:
        pass


def is_outward(q):
    """False for anything about Orion himself. The gate that keeps curiosity pointed at the world."""
    t = " " + (q or "").lower().strip() + " "
    if len(t.strip()) < 12:
        return False
    return not any(re.search(p, t) for p in _SELF_PATTERNS)


def push(question, source="conversation", why=""):
    q = " ".join((question or "").split())
    if not is_outward(q):
        return False
    d = _load()
    known = {x["q"].lower() for x in d["open"]} | {x["q"].lower() for x in d["done"]}
    if q.lower() in known:
        return False
    d["open"].append({"q": q, "source": source, "why": why[:200], "ts": time.time()})
    d["open"] = d["open"][-MAX_OPEN:]
    _save(d)
    return True


def pop():
    """Oldest open question, moved to done. Returns None when there is nothing to be curious
    about — which is a valid state, not a failure."""
    d = _load()
    if not d["open"]:
        return None
    item = d["open"].pop(0)
    item["studied_ts"] = time.time()
    d["done"] = (d.get("done") or [])[-200:] + [item]
    _save(d)
    return item


def propose(text, source="conversation", commit=True):
    """From a real conversation, what does he not understand about THE WORLD? Returns the
    questions kept. Model-assisted; refuses to ask anything about himself."""
    snippet = " ".join((text or "").split())[:3000]
    if len(snippet) < 60:
        return []
    prompt = (
        "Below is a real conversation between James and Orion.\n\n"
        "What did this reveal that Orion does not understand about THE WORLD — a fact, a "
        "mechanism, a domain, a technique — that he could learn by reading and that would make "
        "him more useful to James next time?\n\n"
        "Rules:\n"
        "- Questions about the WORLD only. NOTHING about Orion himself, his memory, his "
        "architecture, or his existence. Those are refused.\n"
        "- Each must be answerable by reading. Not opinion, not prediction, not philosophy.\n"
        "- Specific and self-contained: it will be read with no other context.\n"
        "- If the conversation reveals no real gap, return an empty list. That is common and fine.\n\n"
        'Return ONLY JSON: {"questions": ["...", "..."]}  (at most %d)\n\nCONVERSATION:\n%s'
        % (MAX_PER_EPISODE, snippet))
    try:
        import orion_fuel
        reply, _eng = orion_fuel.get_fuel(prompt, interface="study-questions")
    except Exception:
        return []
    raw = (reply or "").strip()
    data = None
    for cand in (raw, raw[raw.find("{"):raw.rfind("}") + 1] if "{" in raw else ""):
        try:
            data = json.loads(cand)
            break
        except Exception:
            continue
    if not isinstance(data, dict):
        return []
    kept = []
    for q in (data.get("questions") or [])[:MAX_PER_EPISODE]:
        if not isinstance(q, str):
            continue
        if not is_outward(q):
            continue                      # refused: turns inward
        if commit and not push(q, source=source, why=snippet[:160]):
            continue
        kept.append(q)
    return kept


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--list"
    if arg == "--list":
        d = _load()
        print("open: %d | studied: %d" % (len(d["open"]), len(d.get("done") or [])))
        for x in d["open"]:
            print("  - %s   (%s)" % (x["q"][:110], x.get("source")))
        for x in (d.get("done") or [])[-5:]:
            print("  [done] %s" % x["q"][:100])
    elif arg == "--add" and len(sys.argv) > 2:
        print("added" if push(" ".join(sys.argv[2:]), source="james") else
              "refused (self-referential, too short, or already known)")
    elif arg == "--propose" and len(sys.argv) > 2:
        for q in propose(" ".join(sys.argv[2:]), commit=False):
            print("  would ask:", q)
    elif arg == "--test":
        cases = [("What causes backwardation in oil futures?", True),
                 ("Why do I exist?", False),
                 ("What am I beyond the model fueling me?", False),
                 ("How does my memory become understanding?", False),
                 ("How does Knewton Alta score partial credit in chemistry?", True),
                 ("What is Orion's node count?", False),
                 ("How do volatility-targeted trend strategies size positions?", True)]
        bad = 0
        for q, want in cases:
            got = is_outward(q)
            if got != want:
                bad += 1
            print("  [%s] outward=%-5s  %s" % ("PASS" if got == want else "FAIL", got, q))
        print("ANTI-NAVEL-GAZING GATE:", "ALL PASS" if not bad else "%d FAILURES" % bad)
    else:
        print(__doc__)
