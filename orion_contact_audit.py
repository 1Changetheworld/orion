#!/usr/bin/env python3
"""Audit the contact log for machine turns masquerading as the user.

WHY THIS EXISTS
---------------
`orion_temporal.SYNTHETIC_PREFIXES` can only filter synthetic prompts somebody
already noticed. On 2026-08-30 James asked "we spoke four hours ago?" — and the
answer was no: the goal decomposer had fired 10x that day and every one was
classified REAL. The prefix list didn't know that prompt existed.

This does NOT look for known text. It looks for machine SIGNATURES, so it can
flag prompt types nobody has seen yet:

  1. REPETITION  — byte-identical text sent many times. Humans don't.
  2. PERIODICITY — low variance between sends. A 5-minute clock is not a person.
  3. NOCTURNAL   — sustained activity in the small hours.
  4. BURSTINESS  — many sends inside a tight window.

Read-only. Prints a report. Per DECISIONS.md, diagnostics NEVER notify.

Usage:
    python3 orion_contact_audit.py [--days N] [--min-count N]
"""
import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict

LOG = os.path.expanduser("~/.orion/synthesis/contact_log.jsonl")


def load(days):
    """Inbound user-ish events within the window."""
    cutoff = time.time() - days * 86400
    out = []
    try:
        with open(LOG, encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if not (d.get("direction") == "inbound" or d.get("role") == "user"):
                    continue
                ts = float(d.get("ts") or 0)
                if ts < cutoff:
                    continue
                text = (d.get("text") or "").strip()
                if not text:
                    continue
                out.append((ts, d.get("surface") or d.get("channel") or "?", text))
    except FileNotFoundError:
        sys.exit("contact log not found: %s" % LOG)
    out.sort()
    return out


def already_filtered(text):
    """Does the current prefix list already catch this?"""
    try:
        import orion_temporal
        return orion_temporal.is_synthetic_turn(text)
    except Exception:
        return False


def fingerprint(text):
    """Group by opening words — catches templated prompts with varying tails."""
    return " ".join(text.split()[:8]).lower()


def periodicity(times):
    """(median gap, coefficient of variation). Low CV => clock-driven."""
    if len(times) < 3:
        return None, None
    gaps = [b - a for a, b in zip(times, times[1:])]
    gaps = [g for g in gaps if g > 0]
    if len(gaps) < 2:
        return None, None
    med = statistics.median(gaps)
    try:
        cv = statistics.pstdev(gaps) / (statistics.mean(gaps) or 1)
    except Exception:
        cv = None
    return med, cv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-count", type=int, default=3)
    args = ap.parse_args()

    rows = load(args.days)
    if not rows:
        print("no inbound events in window")
        return

    groups = defaultdict(list)
    for ts, surface, text in rows:
        groups[fingerprint(text)].append((ts, surface, text))

    suspects = []
    for fp, items in groups.items():
        if len(items) < args.min_count:
            continue
        times = [i[0] for i in items]
        med, cv = periodicity(times)
        sample = items[0][2]
        caught = already_filtered(sample)

        score, why = 0, []
        if len(items) >= 10:
            score += 2; why.append("repeated %dx" % len(items))
        elif len(items) >= 5:
            score += 1; why.append("repeated %dx" % len(items))

        if cv is not None and cv < 0.35 and len(items) >= 4:
            score += 2; why.append("clock-like (CV=%.2f, ~%.0fs apart)" % (cv, med))

        hours = [int(time.strftime("%H", time.localtime(t))) for t in times]
        night = sum(1 for h in hours if h < 6)
        if night >= 3:
            score += 1; why.append("%d sends between 00:00-06:00" % night)

        uniq = len({i[2] for i in items})
        if uniq == 1 and len(items) >= 3:
            score += 2; why.append("byte-identical every time")

        if score >= 3:
            suspects.append((score, len(items), caught, sample, why, times))

    suspects.sort(reverse=True, key=lambda x: (x[0], x[1]))

    print("CONTACT LOG AUDIT — last %d days, %d inbound events" % (args.days, len(rows)))
    print("=" * 72)
    unc = [s for s in suspects if not s[2]]
    print("suspect patterns: %d   ALREADY FILTERED: %d   *** UNCAUGHT: %d ***"
          % (len(suspects), len(suspects) - len(unc), len(unc)))
    print()

    if not suspects:
        print("nothing looks machine-generated. (Absence of evidence only —")
        print("a slow or irregular generator would not trip these heuristics.)")
        return

    for score, n, caught, sample, why, times in suspects:
        tag = "[filtered]" if caught else "[UNCAUGHT] <-- leaking into 'last spoke'"
        print("%-12s score=%d  n=%d" % (tag, score, n))
        print("   text : %r" % sample[:88])
        print("   why  : %s" % "; ".join(why))
        print("   span : %s -> %s" % (
            time.strftime("%m-%d %H:%M", time.localtime(times[0])),
            time.strftime("%m-%d %H:%M", time.localtime(times[-1]))))
        print()

    if unc:
        print("-" * 72)
        print("SUGGESTED additions to orion_temporal.SYNTHETIC_PREFIXES:")
        for _, _, _, sample, _, _ in unc:
            print('    "%s",' % " ".join(sample.split()[:5]).lower().replace('"', ""))
        print()
        print("NOTE: adding these treats symptoms. The durable fix is provenance")
        print("stamped at event creation — see docs/PERCEPTION_CONTRACT.md §3.")


if __name__ == "__main__":
    main()
