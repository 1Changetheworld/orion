#!/usr/bin/env python3
"""
orion_corrections.py — corrections that actually STEER, not corrections that get stored.

WHY THIS EXISTS: a correction sitting in memory does not change behaviour. Observed directly on
2026-08-27 — Orion made the same confident-wrong mistake TWICE in one night with the correction
already in his graph. Storage is not steering. For a correction to work it has to be in front of
him at the moment he next speaks, on whatever surface he happens to be speaking on.

JAMES'S RULE (2026-08-30): "a correction should be closed as simple as it being marked as
addressed." Simple — with the three holes he asked about closed:

  1. SELF-CERTIFICATION. "Understood, sir" is not addressing it; he already proved that. Closing
     requires stating WHAT CHANGES, and the judgement is made on his actual reply, not on a claim.
  2. CLOSING IS NOT FORGETTING. An addressed correction graduates into a standing rule he keeps.
     The ticket closes; the lesson does not.
  3. RECURRENCE IS THE MOST VALUABLE SIGNAL HERE. If the same correction fires again after he
     marked it addressed, that is "he said he'd fix it and didn't" — a thing that is completely
     invisible today. It REOPENS with a counter and escalates, rather than filing as brand new.

INVARIANT: this surfaces, it never notifies. Corrections are written where the prompt hook reads
them, so they reach him on his next turn — immediate inside a live conversation, simply waiting
when there isn't one. Nothing here ever sends a message (§7.4: on 2026-06-07 this exact loop sent
James nine unsolicited iMessages in one day).

Honest limitation: recurrence is matched on the correction's content fingerprint, so the same
correction rephrased differently reads as a new one. Better than nothing, not the same as
understanding.

  --list                 open corrections
  --all                  everything, including addressed
  --addressed <id> <what changed>
  --block                exactly what the hook would inject
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
import time
from pathlib import Path

STORE = Path(os.path.expanduser("~/.orion/corrections.json"))
LOG = Path(os.path.expanduser("~/.orion/corrections_history.jsonl"))
MAX_SURFACED = 3
MAX_AGE_DAYS = 45


def _load():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STORE)
    except Exception:
        pass


def _history(event, rec):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "event": event, **rec},
                               ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _fp(text):
    return hashlib.sha256(" ".join((text or "").lower().split())
                          .encode("utf-8", "replace")).hexdigest()[:16]


def file_correction(content, actor="james", ts=None, source="salience"):
    """Record a confirmed correction. If this exact correction was already marked addressed,
    it REOPENS — that is him having said he'd fix it and not fixed it, which matters more than
    the original correction did."""
    d = _load()
    fp = _fp(content)
    now = float(ts or time.time())
    rec = d.get(fp)
    if not rec:
        rec = {"id": fp, "content": content, "actor": actor, "first_ts": now, "last_ts": now,
               "status": "open", "occurrences": 1, "reopened": 0, "source": source}
        _history("filed", rec)
    else:
        rec["occurrences"] = rec.get("occurrences", 1) + 1
        rec["last_ts"] = now
        if rec.get("status") == "addressed":
            rec["status"] = "open"
            rec["reopened"] = rec.get("reopened", 0) + 1
            rec["prior_change"] = rec.get("change")
            _history("reopened", rec)      # he said he'd fix it and it happened again
        else:
            _history("repeated", rec)
    d[fp] = rec
    _save(d)
    return rec


def open_items(max_age_days=MAX_AGE_DAYS):
    cut = time.time() - max_age_days * 86400
    items = [r for r in _load().values()
             if r.get("status") == "open" and float(r.get("last_ts", 0)) > cut]
    # a reopened correction outranks a fresh one: it is evidence of a pattern, not an incident
    return sorted(items, key=lambda r: (-int(r.get("reopened", 0)), -float(r.get("last_ts", 0))))


def mark_addressed(cid, change):
    """Closed by being marked addressed — but only WITH a stated change. 'Understood' is not a
    change, and he has already demonstrated that acknowledging is not the same as adjusting."""
    if not (change or "").strip():
        return None
    d = _load()
    rec = d.get(cid)
    if not rec:
        return None
    rec["status"] = "addressed"
    rec["change"] = change.strip()
    rec["addressed_ts"] = time.time()
    d[cid] = rec
    _save(d)
    _history("addressed", rec)
    return rec


def standing_rules(limit=8):
    """Addressed corrections do not vanish — they become rules he carries."""
    rules = [r for r in _load().values() if r.get("status") == "addressed" and r.get("change")]
    return sorted(rules, key=lambda r: -float(r.get("addressed_ts", 0)))[:limit]


def block():
    """What the prompt hook injects. Bounded, and silent when there is nothing to say."""
    items = open_items()[:MAX_SURFACED]
    if not items:
        return ""
    lines = ["<orion-corrections>",
             "James corrected you and you have NOT addressed this yet. Deal with it in this "
             "reply — say specifically what you are doing differently, not that you understand:"]
    for r in items:
        when = time.strftime("%b %d", time.localtime(r.get("last_ts", 0)))
        line = '  - [%s] "%s"' % (when, (r.get("content") or "")[:220])
        if r.get("reopened"):
            line += ("\n    (you marked this addressed once already — you said \"%s\" — and it "
                     "happened again. Do not just re-acknowledge it.)"
                     % str(r.get("prior_change"))[:120])
        elif r.get("occurrences", 1) > 1:
            line += "\n    (he has said this %d times)" % r["occurrences"]
        lines.append(line)
    rules = standing_rules(3)
    if rules:
        lines.append("Standing rules you already agreed to, still in force:")
        for r in rules:
            lines.append("  - %s" % str(r.get("change"))[:160])
    lines.append("</orion-corrections>")
    return "\n".join(lines)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--list"
    if arg == "--list":
        for r in open_items():
            print("%s  reopened=%d occ=%d  %s" % (r["id"], r.get("reopened", 0),
                                                  r.get("occurrences", 1), r["content"][:90]))
    elif arg == "--all":
        print(json.dumps(_load(), indent=1, ensure_ascii=False))
    elif arg == "--block":
        print(block() or "(nothing to surface)")
    elif arg == "--addressed" and len(sys.argv) > 3:
        r = mark_addressed(sys.argv[2], " ".join(sys.argv[3:]))
        print(json.dumps(r, indent=1) if r else "no such correction, or no change stated")
    else:
        print(__doc__)
