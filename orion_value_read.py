#!/usr/bin/env python3
"""
orion_value_read.py — first REAL (provisional) value-compass reading (Build 3).

Feeds Orion's logged Loom tension-drops into the validated Hodge core (orion_value) to
produce its FIRST value reading on real data. ADVISORY ONLY — NOT wired to act/reason/defer
control, because the τ-calibration probe shows τ_norm still tracks context (+0.90); until
τ-normalization v2 lands, the absolute grad/curl/harmonic verdict reflects the calibration
artifact as much as genuine value. This makes the pipeline run + accrue so it's ready the
moment τ is trustworthy.

Construction (non-degenerate by design): preferences are built from WITHIN-CONTEXT pairwise
τ_norm comparisons (per regime). Because different contexts can rank the same pair
oppositely, the aggregated 1-form CAN carry curl/harmonic — so the reading is informative,
not a trivial gradient-of-a-scalar.
"""
from __future__ import annotations
import json, os, sys, time, collections
from pathlib import Path
import orion_value as V

TRACE = Path(os.path.expanduser("~/.orion/state/neuromod_loom_trace.jsonl"))


def _fires(since: float):
    out = []
    try:
        for l in TRACE.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if r.get("rec") != "tick" or not r.get("eff", {}).get("fired"):
                continue
            if r.get("ts", 0) < since:
                continue
            out.append(r)
    except Exception:
        pass
    return out


def main(argv):
    since = float(argv[argv.index("--since") + 1]) if "--since" in argv else 0.0
    fires = _fires(since)
    print("=" * 62)
    print("VALUE COMPASS — first reading (ADVISORY, provisional)")
    print("=" * 62)
    print(f"fired tensions observed: {len(fires)} (since {since})")
    if len(fires) < 6:
        print("insufficient firing data — let the Loom accrue more before a reading.")
        return 0

    # slow ambient reference (the probe's τ_norm = τ / slow ambient) — decorrelate loudness
    amb = [float(f["E"]["total"]) for f in fires]
    ref = sum(amb) / len(amb) or 1.0
    # per (topic, regime): mean τ_norm
    cell = collections.defaultdict(list)
    for f in fires:
        topic = f.get("fired_key") or "unnamed"
        reg = f.get("regime", "?")
        tau = float(f["E"]["peak"])
        cell[(topic, reg)].append(tau / ref)
    topics = sorted({t for (t, _) in cell})
    if len(topics) < 3:
        print(f"only {len(topics)} distinct topics — need ≥3 for a meaningful field.")
        return 0
    idx = {t: i for i, t in enumerate(topics)}

    # within-regime pairwise comparisons -> aggregate antisymmetric flow per edge
    pair_flow = collections.defaultdict(list)
    regimes = {r for (_, r) in cell}
    for reg in regimes:
        present = [(t, sum(v) / len(v)) for (t, rg), v in cell.items() if rg == reg]
        for a in range(len(present)):
            for b in range(a + 1, len(present)):
                ta, va = present[a]
                tb, vb = present[b]
                i, j = idx[ta], idx[tb]
                if i < j:
                    pair_flow[(i, j)].append(va - vb)
                else:
                    pair_flow[(j, i)].append(vb - va)
    edges = sorted(pair_flow)
    y = [sum(v) / len(v) for k in edges for v in [pair_flow[k]]]
    w = [float(len(pair_flow[k])) for k in edges]   # comparability = #contexts comparing the pair

    r = V.hodge_decompose(len(topics), edges, y, w=w)
    et = r["E_total"] or 1e-12
    g, c, h = r["E_grad"] / et, r["E_curl"] / et, r["E_harm"] / et
    print(f"nodes(topics)={len(topics)}  edges={len(edges)}  regimes={len(regimes)}")
    print(f"E_total={r['E_total']:.4f}")
    print(f"  GRADIENT  share = {g:5.1%}   (coherent value → ACT autonomously)")
    print(f"  CURL      share = {c:5.1%}   (local contradiction → REASON more)")
    print(f"  HARMONIC  share = {h:5.1%}   (global incoherence → DEFER to James)")
    dominant = max((("act", g), ("reason", c), ("defer", h)), key=lambda x: x[1])
    print(f"  → dominant signal: {dominant[0].upper()}  ({dominant[1]:.0%})")
    print("\nADVISORY ONLY — τ_norm not yet context-comparable (+0.90); this reflects the")
    print("calibration artifact as much as real value. Gate to TRUST: τ-normalization v2.")
    # persist the advisory reading (accrues; never action-triggering)
    try:
        out = Path(os.path.expanduser("~/.orion/state/value_readings.jsonl"))
        with out.open("a", encoding="utf-8") as fo:
            fo.write(json.dumps({"ts": time.time(), "advisory": True,
                                 "grad": g, "curl": c, "harm": h,
                                 "topics": len(topics), "edges": len(edges)}) + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
