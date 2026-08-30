#!/usr/bin/env python3
"""
orion_perception.py — the PERCEPTION BOUNDARY (Perception Contract §2/§3/§7; build §8 step 1).

One event shape. One ingestion path. Provenance mandatory. Sensors stay dumb.

This module DEFINES the canonical event and the boundary validator + raw-stream capture. It does
NOT touch the graph and does NOT change any existing behaviour — adapters get wired to it in later
steps. This is the single gate every future sense (iMessage, Telegram, voice, the model surfaces)
will pass through, so provenance and attribution are guaranteed at the source instead of guessed.

Invariants enforced here (contract §7):
  1. No unlabelled events — missing a required field is REJECTED and logged, never guessed/defaulted.
  3. Content captured VERBATIM, untruncated.
  4. Rejections are diagnostics — logged to a file, they NEVER notify.
  (§2) meta is a junk drawer; the pipeline never branches on it.
Never raises to the caller — a bad event is rejected, not an exception.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path

STATE = Path(os.path.expanduser("~/.orion/state"))
RAW = STATE / "events_raw.jsonl"            # tier-1 raw stream: every validated event, verbatim, append-only
REJECTED = STATE / "events_rejected.jsonl"  # boundary rejections (diagnostic; never notifies — §7.4)

REQUIRED = ("ts", "provenance", "surface", "direction", "content")
PROVENANCE = ("external", "self")           # §3: the load-bearing field — did the world cause it, or Orion?
DIRECTIONS = ("inbound", "outbound")


def make_event(content, *, provenance, surface, direction, actor=None, modality="text",
               thread=None, ts=None, meta=None) -> dict:
    """Construct a canonical event (§2). content is captured VERBATIM — never truncated here."""
    return {
        "ts": float(ts if ts is not None else time.time()),
        "provenance": provenance,   # "external" | "self"
        "surface": surface,         # claude|codex|gemini|imessage|telegram|voice|...
        "actor": actor,             # who produced it; "orion" when provenance == self
        "direction": direction,     # inbound | outbound
        "modality": modality,       # text | image | audio | file | event
        "content": content,         # payload, verbatim, untruncated
        "thread": thread,           # conversation/session id for grouping
        "meta": meta or {},         # adapter junk drawer — pipeline NEVER branches on it
    }


def validate(ev) -> tuple:
    """Boundary validation → (ok, reason). REJECT on any missing/invalid field — never guess a default."""
    if not isinstance(ev, dict):
        return False, "not a dict"
    for f in REQUIRED:
        if ev.get(f) in (None, ""):
            return False, f"missing required field: {f}"
    if ev.get("provenance") not in PROVENANCE:
        return False, f"provenance must be external|self, got {ev.get('provenance')!r}"
    if ev.get("direction") not in DIRECTIONS:
        return False, f"direction must be inbound|outbound, got {ev.get('direction')!r}"
    if not isinstance(ev.get("ts"), (int, float)):
        return False, "ts must be epoch seconds (number)"
    if not isinstance(ev.get("content"), str):
        return False, "content must be a string (verbatim)"
    return True, "ok"


def ingest(ev) -> dict:
    """THE ONE ingestion path (the boundary). Validate → append to the raw stream verbatim, OR reject
    and log the rejection. Does NOT write to the graph and does NOT trigger consolidation — that is the
    salience gate's job in a later step. Returns {ok, reason}. Never raises."""
    ok, reason = validate(ev)
    try:
        STATE.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    if ok:
        norm = {  # canonical field order + optional defaults; required fields/content untouched
            "ts": float(ev["ts"]), "provenance": ev["provenance"], "surface": ev["surface"],
            "actor": ev.get("actor"), "direction": ev["direction"],
            "modality": ev.get("modality", "text"), "content": ev["content"],
            "thread": ev.get("thread"), "meta": ev.get("meta") or {},
        }
        try:
            with RAW.open("a", encoding="utf-8") as f:
                f.write(json.dumps(norm, ensure_ascii=False) + "\n")
        except Exception as e:
            return {"ok": False, "reason": f"raw write failed: {e}"}
        return {"ok": True, "reason": "captured"}
    try:                                       # rejection = diagnostic → file only, never notify (§7.4)
        with REJECTED.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "reason": reason,
                                "event": ev if isinstance(ev, dict) else str(ev)[:500]},
                               ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
    return {"ok": False, "reason": reason}


def _selftest():
    """Verify the boundary holds before anything real depends on it."""
    cases = [
        ("valid external", make_event("hi from James", provenance="external", surface="imessage",
                                      direction="inbound", actor="+12703003122"), True),
        ("valid self/efference", make_event("outbound note", provenance="self", surface="imessage",
                                            direction="outbound", actor="orion"), True),
        ("UNLABELLED (must reject)", {"ts": time.time(), "surface": "imessage",
                                      "direction": "inbound", "content": "x"}, False),
        ("bad provenance (must reject)", make_event("x", provenance="maybe", surface="cli",
                                                    direction="inbound"), False),
        ("empty content (must reject)", make_event("", provenance="external", surface="cli",
                                                   direction="inbound"), False),
        ("long content (must pass, verbatim)", make_event("Z" * 5000, provenance="external",
                                                          surface="cli", direction="inbound"), True),
    ]
    ok_all = True
    for name, ev, expect in cases:
        got, reason = validate(ev)
        mark = "PASS" if got == expect else "FAIL"
        ok_all = ok_all and (got == expect)
        print(f"  [{mark}] {name}: valid={got} ({reason})")
    long = make_event("Q" * 3000, provenance="external", surface="cli", direction="inbound")
    assert len(long["content"]) == 3000, "content was truncated!"
    print("  [PASS] content stored verbatim, untruncated (3000 chars round-trip)")
    print("SELFTEST:", "ALL PASS" if ok_all else "FAILURES PRESENT")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()
    else:
        print("orion_perception.py — the perception boundary (contract §8 step 1). "
              "Run with --selftest to verify. Nothing is wired to it yet (no behaviour change).")
