#!/usr/bin/env python3
"""
orion_distill_history.py — the one supervised pass over everything James said before the gate.

WHY THIS EXISTS. The salience gate starts from NOW (orion_salience --init), deliberately, so it
would not bury him in five months of old business the moment it woke. The consequence, which Orion
caught when reviewing the build: the 1,686 iMessages backfilled from 2026-04-08 onward are
captured in tier 1 and would be interpreted by NOTHING, ever. The trading, school, the whole
relationship — stored and unread, permanently.

This is that one pass. It is deliberately NOT the live gate:

  - SUPERVISED. It writes to a REVIEW FILE, never to the graph. Nothing becomes a belief until
    James reads it and promotes it. History is exactly where a bad distillation would be most
    expensive and least noticed, so a human reads it first.
  - BY DAY, not by episode. A day is the natural unit of "what happened", and it keeps the cost
    honest: ~60 model calls instead of ~400.
  - RESUMABLE and BOUNDED. --run N does N days and stops; state is kept, so it can be done in
    sittings and interrupted without loss.
  - IT ONLY READS THE RAW STREAM. Same verbatim, attributed events as the live path. No special
    case, no second parser (§8.6 — if history needed a special path, the contract would be wrong).

  --plan          how many days, how many messages, what it will cost. Writes nothing.
  --run [N]       distill the next N days into the review file (default 5)
  --review [N]    read what it produced
  --promote       write REVIEWED+approved days into the graph (requires editing the file first)
"""
from __future__ import annotations
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/orion-code"))

import orion_perception as P

STATE = Path(os.path.expanduser("~/.orion/state/distill_history.json"))
REVIEW = Path(os.path.expanduser("~/.orion/history_review.jsonl"))
SURFACE = "imessage"
MAX_CHARS_PER_DAY = 14000
CUTOFF_ENV = "ORION_DISTILL_BEFORE"     # only history strictly before the gate went live


def _load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(p, o):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(o, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


def days():
    """Group the archived conversation by calendar day. Only days James actually spoke on —
    a day of Orion talking to himself is not a day worth interpreting."""
    cutoff = float(os.environ.get(CUTOFF_ENV) or 0)
    by = defaultdict(list)
    try:
        for line in P.RAW.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("surface") != SURFACE:
                continue
            if cutoff and float(r.get("ts") or 0) >= cutoff:
                continue
            by[time.strftime("%Y-%m-%d", time.localtime(r["ts"]))].append(r)
    except Exception:
        return {}
    return {d: sorted(v, key=lambda e: e["ts"]) for d, v in by.items()
            if any(e.get("provenance") == "external" for e in v)}


def _transcript(evs):
    lines = []
    for e in evs:
        who = "JAMES" if e.get("provenance") == "external" else "ORION"
        lines.append("[%s] %s: %s" % (time.strftime("%H:%M", time.localtime(e["ts"])), who,
                                      (e.get("content") or "").replace("\n", " ")))
    t = "\n".join(lines)
    return t[:MAX_CHARS_PER_DAY]


PROMPT = (
    "Below is one day of real conversation between James and Orion, verbatim, with who said what.\n"
    "Extract ONLY what is durably worth remembering about JAMES and his world — his preferences,\n"
    "decisions, projects, constraints, corrections he gave, and what matters to him.\n\n"
    "Rules:\n"
    "- Ground everything in what is actually here. Never infer or embellish.\n"
    "- Skip small talk, logistics, and anything that stopped being true.\n"
    "- Skip anything about Orion's own internals unless James stated a decision about them.\n"
    "- If the day holds nothing durable, return empty lists. That is a valid and common answer.\n\n"
    'Return ONLY JSON: {"facts": ["..."], "corrections": ["..."], "open": ["..."]}\n\n'
    "CONVERSATION:\n")


def distill_day(day, evs):
    try:
        import orion_fuel
        reply, engine = orion_fuel.get_fuel(PROMPT + _transcript(evs), interface="history-distill")
    except Exception as e:
        return {"day": day, "error": str(e)[:120]}
    raw = (reply or "").strip()
    data = None
    for cand in (raw, raw[raw.find("{"):raw.rfind("}") + 1] if "{" in raw else ""):
        try:
            data = json.loads(cand)
            break
        except Exception:
            continue
    if not isinstance(data, dict):
        return {"day": day, "error": "unparseable model output", "raw": raw[:300]}
    ext = sum(1 for e in evs if e.get("provenance") == "external")
    return {"day": day, "messages": len(evs), "from_james": ext, "engine": engine,
            "facts": [f for f in (data.get("facts") or []) if isinstance(f, str)][:12],
            "corrections": [c for c in (data.get("corrections") or []) if isinstance(c, str)][:6],
            "open": [o for o in (data.get("open") or []) if isinstance(o, str)][:6],
            "approved": False,          # <- James flips this to true; nothing is promoted until then
            "distilled_ts": time.time()}


def plan():
    d = days()
    done = set(_load(STATE, {}).get("done", []))
    todo = sorted(set(d) - done)
    msgs = sum(len(v) for v in d.values())
    ext = sum(1 for v in d.values() for e in v if e.get("provenance") == "external")
    print("days James spoke on : %d  (%d already distilled, %d to go)" % (len(d), len(done), len(todo)))
    print("messages in scope   : %d  (%d from James)" % (msgs, ext))
    print("model calls needed  : %d  (one per day, not one per episode)" % len(todo))
    print("span                : %s -> %s" % (min(d) if d else "-", max(d) if d else "-"))
    print("output              : %s  (REVIEW FILE — nothing reaches the graph)" % REVIEW)
    if todo:
        print("next days           :", ", ".join(todo[:8]))


def run(n=5):
    d = days()
    st = _load(STATE, {"done": []})
    done = set(st.get("done", []))
    todo = [x for x in sorted(d) if x not in done]
    if not todo:
        print("nothing left to distill")
        return
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    for day in todo[:n]:
        res = distill_day(day, d[day])
        with REVIEW.open("a", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
        done.add(day)
        st["done"] = sorted(done)
        _save(STATE, st)
        if res.get("error"):
            print("  %s  ERROR: %s" % (day, res["error"]))
        else:
            print("  %s  %d msgs (%d from James) -> %d facts, %d corrections"
                  % (day, res["messages"], res["from_james"],
                     len(res["facts"]), len(res["corrections"])))
    print("\n%d days done. NOTHING has been written to the graph." % len(done))
    print("Read it:    python3 orion_distill_history.py --review")
    print("Approve:    set \"approved\": true on the entries you want, then --promote")


def review(n=6):
    if not REVIEW.exists():
        print("nothing distilled yet")
        return
    rows = [json.loads(l) for l in REVIEW.read_text(encoding="utf-8").splitlines() if l.strip()]
    print("%d days distilled, %d approved\n" % (len(rows), sum(1 for r in rows if r.get("approved"))))
    for r in rows[-n:]:
        if r.get("error"):
            print("%s  ERROR %s" % (r["day"], r["error"]))
            continue
        print("=== %s === (%d msgs, %d from James)%s"
              % (r["day"], r.get("messages", 0), r.get("from_james", 0),
                 "  [APPROVED]" if r.get("approved") else ""))
        for f in r.get("facts", []):
            print("   fact       : %s" % f[:150])
        for c in r.get("corrections", []):
            print("   CORRECTION : %s" % c[:150])
        for o in r.get("open", []):
            print("   open       : %s" % o[:150])
        print()


def promote():
    """Write ONLY approved days into the graph, tagged so their origin is never ambiguous."""
    if not REVIEW.exists():
        print("nothing to promote")
        return
    rows = [json.loads(l) for l in REVIEW.read_text(encoding="utf-8").splitlines() if l.strip()]
    approved = [r for r in rows if r.get("approved") and not r.get("promoted")]
    if not approved:
        print("no entries marked approved. Edit %s and set \"approved\": true first." % REVIEW)
        return
    try:
        import orion_sleep
    except Exception as e:
        print("cannot reach the memoriser:", e)
        return
    n = 0
    for r in approved:
        for f in r.get("facts", []):
            if orion_sleep._memorize("[%s] %s" % (r["day"], f), node_type="fact",
                                     tags=["history", "distilled", "imessage", r["day"]]):
                n += 1
        for c in r.get("corrections", []):
            if orion_sleep._memorize("[%s] CORRECTION from James: %s" % (r["day"], c),
                                     node_type="fact",
                                     tags=["history", "distilled", "correction", r["day"]]):
                n += 1
        r["promoted"] = True
    REVIEW.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                      encoding="utf-8")
    print("promoted %d items from %d approved days" % (n, len(approved)))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--plan"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if arg == "--plan":
        plan()
    elif arg == "--run":
        run(n or 5)
    elif arg == "--review":
        review(n or 6)
    elif arg == "--promote":
        promote()
    else:
        print(__doc__)
