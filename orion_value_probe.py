#!/usr/bin/env python3
"""orion_value_probe.py — the τ-CALIBRATION PROBE (value/judgment compass, step 0).

Before Orion can have a value compass — a preference structure on its memory graph,
Hodge-decomposed into an optimizable GRADIENT, a 'reason-more' CURL, and a
'defer-to-James' HARMONIC residual — the whole construction rests on ONE load-bearing
assumption (SPEC-value-v0.md, its own flagged crux):

    Is the Loom's tension-drop  τ  COMPARABLE across contexts? — does a unit of τ measured
    in one episode mean the same 'value' as a unit measured in another?

If the Loom's tension has CONTEXT-DEPENDENT GAIN (τ inflates when the context is 'loud' —
busy regime, high arousal, high ambient tension), the aggregated preference 1-form is
BIASED toward loud contexts and the defer/autonomous verdict is meaningless. So this probe
must PASS — or τ must be normalised — before ANY downstream value structure is built.

Method (pure read on the existing trace, no new instrument): τ ≈ the tension magnitude
discharged at a firing (E.peak at the fired tick); context = regime, arousal, ambient
E.total. Test whether τ is INTRINSIC (independent of how loud the context is) or TRACKS the
ambient. Strong tracking ⇒ context-dependent gain ⇒ τ must be normalised first.
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


def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    ca = [x - ma for x in a]
    cb = [y - mb for y in b]
    na = math.sqrt(sum(x * x for x in ca))
    nb = math.sqrt(sum(y * y for y in cb))
    return (sum(x * y for x, y in zip(ca, cb)) / (na * nb)) if na > 1e-9 and nb > 1e-9 else 0.0


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


def main(argv: list[str]) -> int:
    since = float(argv[argv.index("--since") + 1]) if "--since" in argv else 0.0
    rows = _load(since)
    # a "firing" = the moment a tension is addressed; τ = the magnitude discharged (E.peak),
    # context = how loud the surroundings were at that moment.
    fires = [t for t in rows if t.get("rec") == "tick" and t.get("eff", {}).get("fired")]
    print("=" * 70)
    print(f"τ-CALIBRATION PROBE   ·   firings observed: {len(fires)}"
          + (f"  (since {since:.0f})" if since else ""))
    print("=" * 70)
    if len(fires) < 20:
        print(f"insufficient: {len(fires)}/20 firings — let the (healthy, wonder-driven) Loom")
        print("run longer. The verdict is only meaningful on real reasoning, not the old firehose.")
        return 0

    tau = [float(t["E"]["peak"]) for t in fires]
    ambient = [float(t["E"]["total"]) for t in fires]
    arousal = [float(t["m"]["arousal"]) for t in fires]
    by_regime: dict[str, list[float]] = defaultdict(list)
    for t in fires:
        by_regime[t.get("regime", "?")].append(float(t["E"]["peak"]))

    c_amb = _corr(tau, ambient)
    c_aro = _corr(tau, arousal)
    meds = {r: _median(v) for r, v in by_regime.items() if len(v) >= 5}
    mlo, mhi = (min(meds.values()), max(meds.values())) if meds else (0, 0)
    ratio = (mhi / mlo) if mlo > 1e-6 else float("inf")

    print(f"τ  median {_median(tau):.2f}   range [{min(tau):.2f}, {max(tau):.2f}]")
    print(f"context-tracking:  corr(τ, ambient E) = {c_amb:+.2f}   corr(τ, arousal) = {c_aro:+.2f}")
    print("median τ per regime:  " + "  ".join(f"{r}={m:.2f}" for r, m in meds.items()))
    print(f"cross-regime τ ratio (loudest/quietest): {ratio:.1f}x")

    comparable = abs(c_amb) < 0.4 and abs(c_aro) < 0.4 and ratio < 2.0
    print()
    if comparable:
        print("VERDICT: τ looks INTRINSIC (weak context-tracking) — comparable enough that the")
        print("value 1-form is viable. Re-confirm on more healthy data, then build the Hodge core.")
    else:
        why = []
        if abs(c_amb) >= 0.4: why.append(f"τ tracks ambient ({c_amb:+.2f})")
        if abs(c_aro) >= 0.4: why.append(f"τ tracks arousal ({c_aro:+.2f})")
        if ratio >= 2.0: why.append(f"{ratio:.1f}x scale gap across regimes")
        print("VERDICT: CONTEXT-DEPENDENT GAIN — " + "; ".join(why) + ".")
        print("τ is NOT directly comparable. NORMALISE it first (e.g. τ / ambient-gain per")
        print("context) and re-probe — building the 1-form on raw τ would bias it toward loud")
        print("contexts and make the defer/autonomous verdict meaningless.")
    # ── τ-NORMALISATION (context-relative) — remove the ambient GAIN, mirroring the
    #    proven neuromod (m−r) fix: τ_norm = τ / slow causal reference of the ambient. ──
    alpha = 0.05
    R = ambient[0]
    tnorm = []
    for tau_i, amb_i in zip(tau, ambient):
        tnorm.append(tau_i / max(R, 1e-6))      # normalise by the PAST reference (causal)
        R += alpha * (amb_i - R)
    cn_amb, cn_aro = _corr(tnorm, ambient), _corr(tnorm, arousal)
    print("\n--- τ NORMALISED  (context-relative: τ / slow ambient reference) ---")
    print(f"corr(τ_norm, ambient) = {cn_amb:+.2f}   corr(τ_norm, arousal) = {cn_aro:+.2f}"
          f"   median τ_norm {_median(tnorm):.2f}")
    if abs(cn_amb) < 0.4 and abs(cn_aro) < 0.4:
        print("=> NORMALISED τ is DECORRELATED from context — comparable. The value 1-form")
        print("   should be built on τ_norm, not raw τ. (Re-confirm on healthy regime-diverse data.)")
    else:
        print("=> normalisation insufficient — context-dependence survives; the gain model is")
        print("   richer than a single ambient scalar. Hold the 1-form; investigate further.")

    print("\nHONEST LIMIT: we cannot fully separate 'genuinely higher value in busy contexts'")
    print("from 'inflated gain' without ground truth, and this runs largely on pre-fix data —")
    print("the decorrelation shows the transform WORKS mechanically; the real verdict still")
    print("needs healthy, regime-diverse, wonder-driven reasoning. This gates the compass either way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
