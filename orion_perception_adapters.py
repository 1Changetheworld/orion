#!/usr/bin/env python3
"""
orion_perception_adapters.py — the CLI-surface adapters (Perception Contract §4; build §8 step 2).

Wraps the three EXISTING parsers (parse_claude / parse_gemini / parse_codex in
orion_conversation_sync.py) as thin, dumb adapters over the perception boundary. The parsers are
NOT reimplemented and NOT modified — they are imported and reused, which is what makes
"byte-identical output" provable (--verify replays real session files through both paths).

An adapter's entire job (§4): watch a source, normalize to the canonical §2 event, hand off.
It may not decide importance, may not write to the graph, and may not truncate.

    adapter -> normalize -> [ boundary validation ] -> raw stream -> (salience gate, step 5)

PROVENANCE (§3) — how it is decided here:
  role "assistant" -> self      (Orion speaking through whatever model is fuelling him)
  role "user"      -> external, UNLESS the turn is a synthetic injection (persona re-render, goal
                     decomposer, task dispatch, ...) — that is Orion's own scaffolding, i.e. self.

That synthetic test is orion_temporal.is_synthetic_turn: the CRUDE prefix-matching stopgap. The
contract (§3, §8.3) keeps it for ONE cycle, then deletes it once orion_inject_hook.py stamps
provenance at creation (step 3). Every event that leaned on it carries meta.provenance_fallback,
so after step 3 we can measure exactly what the stopgap was still carrying before removing it.

NO BEHAVIOUR CHANGE: nothing calls this yet, and it writes nothing unless you ask it to.
  --verify [N]   replay recent real session files through parser AND adapter; prove equivalence
  --sample [N]   print a few normalized events (no writes)
"""
from __future__ import annotations
import glob as _glob
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/orion-code"))

import orion_perception as P                       # the boundary (step 1)
import orion_conversation_sync as CS               # the EXISTING parsers — reused, not rewritten

try:
    from orion_temporal import is_synthetic_turn   # the one-cycle stopgap (§8.3)
except Exception:                                  # never let a missing import break perception
    def is_synthetic_turn(_t):
        return False


# ── role -> direction, and the provenance decision (§3) ─────────────────────────
def _classify(role, text):
    """Return (provenance, actor, direction, used_fallback)."""
    if role == "assistant":
        # Orion's own utterance through the fuel model: self-caused, efference copy.
        return "self", "orion", "outbound", False
    # role == "user": arriving at the model — but WHO put it there?
    if is_synthetic_turn(text):
        return "self", "orion", "inbound", True    # Orion's scaffolding talking to itself
    return "external", "james", "inbound", False


def adapt(surface, role, text, ts, thread=None, extra=None):
    """Normalize one parsed turn into the canonical §2 event. Content passes through VERBATIM."""
    prov, actor, direction, fallback = _classify(role, text)
    meta = {"role": role, "adapter": "cli_surface"}
    if fallback:
        # mark what the stopgap decided, so step 3 can measure it before deletion
        meta["provenance_fallback"] = "is_synthetic_turn"
    if extra:
        meta.update(extra)
    return P.make_event(text, provenance=prov, surface=surface, direction=direction,
                        actor=actor, modality="text", thread=thread, ts=ts, meta=meta)


def adapt_line(surface, parser, line, thread=None):
    """One raw JSONL line -> canonical event, or None if the parser ignores it."""
    try:
        d = json.loads(line)
    except Exception:
        return None
    try:
        parsed = parser(d)
    except Exception:
        return None
    if not parsed:
        return None
    role, text, ts = parsed
    return adapt(surface, role, text, ts, thread=thread)


def _recent_files(pattern, n):
    try:
        fps = [p for p in _glob.glob(pattern) if os.path.isfile(p)]
    except Exception:
        return []
    fps.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return fps[:n]


# ── verification: parser output must survive the adapter byte-identically ───────
def verify(n_files=6):
    """Replay real session files through the ORIGINAL parser and through the adapter, and prove:
      1. content is byte-identical to the parser's text (and untruncated — §7.3)
      2. ts is preserved exactly
      3. role round-trips through direction (inbound<->user, outbound<->assistant)
      4. every event passes the boundary validator (§7.1)
    Also reports the provenance split and how much the LEGACY path destroys at capture."""
    totals = {"turns": 0, "events": 0, "mismatch": 0, "invalid": 0,
              "external": 0, "self": 0, "fallback": 0,
              "legacy_truncated_turns": 0, "legacy_chars_lost": 0}
    per_surface = {}
    maxtext = getattr(CS, "MAXTEXT", 400)
    for surface, pattern, parser in CS.SURFACES:
        s = {"files": 0, "turns": 0, "events": 0, "mismatch": 0,
             "external": 0, "self": 0, "fallback": 0}
        for fp in _recent_files(pattern, n_files):
            s["files"] += 1
            try:
                lines = open(fp, encoding="utf-8", errors="replace").read().splitlines()
            except Exception:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                try:
                    parsed = parser(d)
                except Exception:
                    parsed = None
                if not parsed:
                    continue
                role, text, ts = parsed
                s["turns"] += 1
                totals["turns"] += 1
                if len(text) > maxtext:
                    totals["legacy_truncated_turns"] += 1
                    totals["legacy_chars_lost"] += len(text) - maxtext
                ev = adapt(surface, role, text, ts, thread=os.path.basename(fp))
                s["events"] += 1
                totals["events"] += 1
                bad = []
                if ev["content"] != text:
                    bad.append("content differs from parser text")
                if ev["ts"] != float(ts):
                    bad.append("ts changed")
                back = "user" if ev["direction"] == "inbound" else "assistant"
                if back != role:
                    bad.append("role did not round-trip: " + str(role) + " -> " + ev["direction"])
                ok, why = P.validate(ev)
                if not ok:
                    totals["invalid"] += 1
                    bad.append("boundary rejected: " + why)
                if bad:
                    s["mismatch"] += 1
                    totals["mismatch"] += 1
                    if totals["mismatch"] <= 5:
                        print("  MISMATCH [" + surface + "] " + "; ".join(bad))
                s[ev["provenance"]] += 1
                totals[ev["provenance"]] += 1
                if ev["meta"].get("provenance_fallback"):
                    s["fallback"] += 1
                    totals["fallback"] += 1
        per_surface[surface] = s

    print("=== per surface ===")
    for surface, s in per_surface.items():
        print("  %-8s files=%-3d turns=%-6d events=%-6d mismatch=%-3d external=%-5d self=%-5d (stopgap caught %d)"
              % (surface, s["files"], s["turns"], s["events"], s["mismatch"],
                 s["external"], s["self"], s["fallback"]))
    print("=== totals ===")
    print("  turns parsed        : %d" % totals["turns"])
    print("  events produced     : %d" % totals["events"])
    print("  MISMATCHES          : %d   (must be 0 — byte-identical)" % totals["mismatch"])
    print("  boundary rejections : %d   (must be 0)" % totals["invalid"])
    ext, slf = totals["external"], totals["self"]
    tot = max(1, ext + slf)
    print("  provenance          : external=%d (%.1f%%)  self=%d (%.1f%%)"
          % (ext, 100.0 * ext / tot, slf, 100.0 * slf / tot))
    print("  stopgap-dependent   : %d  (user-role turns only the prefix list caught)" % totals["fallback"])
    print("  legacy truncation   : %d turns would lose %d chars at capture (MAXTEXT=%d); adapters lose 0"
          % (totals["legacy_truncated_turns"], totals["legacy_chars_lost"], maxtext))
    verdict = (totals["mismatch"] == 0 and totals["invalid"] == 0 and totals["events"] > 0)
    print("VERIFY:", "BYTE-IDENTICAL — adapters equivalent to parsers" if verdict
          else "FAILED (or no data to compare)")
    return verdict


def sample(n=4):
    for surface, pattern, parser in CS.SURFACES:
        shown = 0
        for fp in _recent_files(pattern, 3):
            try:
                lines = open(fp, encoding="utf-8", errors="replace").read().splitlines()
            except Exception:
                continue
            for line in reversed(lines):
                ev = adapt_line(surface, parser, line, thread=os.path.basename(fp))
                if not ev:
                    continue
                c = ev["content"].replace("\n", " ")
                print("[%s] prov=%-8s dir=%-8s actor=%-6s len=%-6d :: %s"
                      % (surface, ev["provenance"], ev["direction"], str(ev["actor"]),
                         len(ev["content"]), c[:90]))
                shown += 1
                if shown >= n:
                    break
            if shown >= n:
                break


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--verify"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    if arg == "--verify":
        raise SystemExit(0 if verify(n) else 1)
    elif arg == "--sample":
        sample(n)
    else:
        print(__doc__)
