#!/usr/bin/env python3
"""orion_predictability.py — THE GATE for predict-measure-correct.

The whole self-verification mechanism (a forward-model whose prediction residual tells
Orion whether it actually solved something) rests on ONE unproven assumption:

    "Can a cheap, no-GPU, no-LLM model predict Orion's own reasoning event-stream well
     enough that the residual MEANS something — and does that residual SHRINK WITH DATA?"

If yes, the journal is learnable and the corrector is worth building. If the residual is
flat noise, the design fails cleanly and we rethink — better to learn that now than after
building it. This is that test. Pure arithmetic over the Loom trace.

Method: online order-k Markov predictors (add-1 smoothed) over event streams from the
trace. Report bits/symbol per order (order>0 << order-0 ⇒ exploitable structure) and
first-half vs second-half bits/symbol (second < first ⇒ the model LEARNS — the residual
shrinks with data). Honest segmentation: pre-fix firehose data is degenerate (a few junk
keys repeating) and will look trivially 'predictable' — that is the tool working, not a
real verdict; the real verdict needs healthy post-fix reasoning. Pass --since <ts> to
restrict to the healthy window.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

TRACE = Path(os.path.expanduser("~/.orion/state/neuromod_loom_trace.jsonl"))


def _load(since: float) -> list[dict]:
    try:
        rows = [json.loads(l) for l in TRACE.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []
    return [r for r in rows if r.get("ts", 0) >= since]


def _markov(seq: list[str], order: int) -> tuple[float, float, float]:
    """Online add-1 Markov coder. Returns (bits/sym overall, first-half, second-half)."""
    counts: dict = defaultdict(lambda: defaultdict(int))
    ctx_tot: dict = defaultdict(int)
    vocab = set(seq)
    V = max(1, len(vocab))
    hist: list[str] = []
    bits: list[float] = []
    for sym in seq:
        ctx = tuple(hist[-order:]) if order else ()
        p = (counts[ctx].get(sym, 0) + 1) / (ctx_tot[ctx] + V)
        bits.append(-math.log(p, 2))
        counts[ctx][sym] += 1
        ctx_tot[ctx] += 1
        hist.append(sym)
    if not bits:
        return 0.0, 0.0, 0.0
    h = len(bits) // 2
    avg = sum(bits) / len(bits)
    first = sum(bits[:h]) / max(1, h)
    second = sum(bits[h:]) / max(1, len(bits) - h)
    return avg, first, second


def _report(name: str, seq: list[str]) -> None:
    print(f"\n--- stream: {name}   (n={len(seq)}, vocab={len(set(seq))}) ---")
    if len(seq) < 30:
        print("    too few events for a verdict — let the healthy Loom run longer.")
        return
    o0, _, _ = _markov(seq, 0)
    o1, f1, s1 = _markov(seq, 1)
    o2, f2, s2 = _markov(seq, 2)
    print(f"    bits/symbol:  order-0 {o0:.2f}   order-1 {o1:.2f}   order-2 {o2:.2f}")
    gain = (o0 - min(o1, o2)) / o0 if o0 > 0 else 0.0
    learns = s1 < f1 * 0.95 or s2 < f2 * 0.95
    print(f"    structure gain over base rate: {100*gain:.0f}%   "
          f"(order-1 learning: 1st-half {f1:.2f} -> 2nd-half {s1:.2f})")
    if gain > 0.15 and learns:
        print("    VERDICT: PREDICTABLE & LEARNS — residual is meaningful here. Corrector viable.")
    elif gain > 0.15:
        print("    VERDICT: structured but not clearly improving — watch with more data.")
    else:
        print("    VERDICT: ~NOISE at this symbolization — residual would be meaningless.")


def main(argv: list[str]) -> int:
    since = float(argv[argv.index("--since") + 1]) if "--since" in argv else 0.0
    rows = _load(since)
    ticks = [r for r in rows if r.get("rec") == "tick"]
    concl = [r for r in rows if r.get("rec") == "conclude"]
    print("=" * 68)
    print(f"JOURNAL-PREDICTABILITY GATE   ·   ticks={len(ticks)}  conclusions={len(concl)}"
          + (f"  (since ts {since:.0f})" if since else ""))
    print("=" * 68)
    if since == 0 and ticks:
        print("NOTE: includes the pre-fix firehose — degenerate junk looks 'predictable'.")
        print("      Use --since <restart_ts> for the real (healthy-Loom) verdict.")

    # stream 1: cognitive-load regime sequence
    _report("regime (cognitive-load state)", [t.get("regime", "?") for t in ticks])
    # stream 2: the reasoning-event stream — which tension fired, in order
    _report("fired tension (reasoning events)",
            [str(t.get("fired_key")) for t in ticks if t.get("fired_key")])
    # stream 3: resolution outcome stream (native/model x held/refired is the real target,
    # but at minimum: the sequence of resolved/unresolved)
    _report("resolution outcome",
            [("res" if c.get("resolved") else "unres") + ("|nat" if c.get("native") else "|mod")
             for c in concl])

    print("\nThe load-bearing stream is 'fired tension' — that IS the reasoning journal.")
    print("If it proves PREDICTABLE & LEARNS on healthy data, the forward-model residual")
    print("can distinguish 'actually solved' from 'looked solved' and we build the corrector.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
