#!/usr/bin/env python3
"""orion_loom_audit.py — closed-loop neuromodulation independence audit.

Reads the synchronized per-tick trace the Loom writes (orion_reason.py →
~/.orion/state/neuromod_loom_trace.jsonl) and asks the RIGHT question — the one the
Research Center council (SPEC-closedloop-audit.md) and the complexity agent's
kill-shot forced us to: NOT "are the modulators correlated?" (a stale trailing prior
that conflates *didn't move* with *couldn't move*), but:

    "Do the modulators carry INDEPENDENT influence once the common tension drive
     E(t) that co-fires them is partialled out?"

Tonight's passive audit found arousal~learning~explore ≈ 0.95 — but the drive is
multi-component (6 independent faculties, no shared E scalar). So the hypothesis is
that 0.95 is BENIGN CO-FIRING of independent drivers, not a collapse. This audit
tests that directly, no GPU, pure-python:

  (1) PARTIAL CORRELATION controlling for E(t): corr(i,j | E). If the cluster's
      correlation COLLAPSES once E is removed, the 0.95 was co-firing → design holds.
      If it SURVIVES, the channels are genuinely slaved → escalate (circuit-selection).
  (2) PARTICIPATION RATIO of the modulator covariance (the naive metric, for contrast).
      PR = (Σ C_ii)² / Σ_ij C_ij²  — no eigendecomposition needed.
  (3) EFFECTIVE RANK of the E-residualised modulator series (Gram–Schmidt).
  (4) Everything reported PER REGIME (idle/light/busy/saturated) so 'didn't move'
      (idle) is never misread as 'couldn't move'.

Read-only. No fuel. No daemon.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

TRACE_FILE = Path(os.path.expanduser("~/.orion/state/neuromod_loom_trace.jsonl"))
MODS = ["arousal", "learning", "explore", "caution", "focus"]
MIN_SAMPLES = 20


def _load(path: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []


def _center(xs: list[float]) -> list[float]:
    m = sum(xs) / len(xs)
    return [x - m for x in xs]


def _corr(a: list[float], b: list[float]) -> float:
    """Pearson — centres its inputs, so it is safe on raw (uncentred) series."""
    a, b = _center(a), _center(b)
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return (sum(x * y for x, y in zip(a, b)) / (na * nb)) if na > 1e-12 and nb > 1e-12 else 0.0


def _partial_corr(i: list[float], j: list[float], z: list[float]) -> float:
    """Correlation of i and j with the linear influence of z removed from both.
    pcorr(i,j|z) = (r_ij - r_iz r_jz) / sqrt((1-r_iz²)(1-r_jz²)).
    Near 0 ⇒ the i–j correlation was explained by the common driver z (= E(t))."""
    rij, riz, rjz = _corr(i, j), _corr(i, z), _corr(j, z)
    den = math.sqrt(max(0.0, (1 - riz * riz) * (1 - rjz * rjz)))
    return (rij - riz * rjz) / den if den > 1e-9 else 0.0


def _participation_ratio(cols: list[list[float]]) -> float:
    """PR of the covariance — effective number of active dimensions. 1 ⇒ one shared
    mode (collapse); ~k ⇒ k independent modes."""
    n = len(cols[0])
    C = [[sum(a * b for a, b in zip(cols[p], cols[q])) / max(1, n - 1)
          for q in range(len(cols))] for p in range(len(cols))]
    tr = sum(C[p][p] for p in range(len(C)))
    fro = sum(C[p][q] ** 2 for p in range(len(C)) for q in range(len(C)))
    return (tr * tr / fro) if fro > 1e-18 else 0.0


def _grank(vecs: list[list[float]], tol: float = 1e-3) -> int:
    basis: list[list[float]] = []
    for v in vecs:
        w = list(v)
        for b in basis:
            d = sum(wi * bi for wi, bi in zip(w, b))
            nb = sum(bi * bi for bi in b)
            if nb > 0:
                w = [wi - (d / nb) * bi for wi, bi in zip(w, b)]
        if sum(wi * wi for wi in w) ** 0.5 > tol:
            basis.append(w)
    return len(basis)


def _residualise_on_E(series: dict[str, list[float]], E: list[float]) -> dict[str, list[float]]:
    """Remove the linear component of E (the common drive) from each modulator series."""
    Ec = _center(E)
    nE = sum(e * e for e in Ec)
    out = {}
    for k, xs in series.items():
        xc = _center(xs)
        beta = (sum(x * e for x, e in zip(xc, Ec)) / nE) if nE > 1e-12 else 0.0
        out[k] = [x - beta * e for x, e in zip(xc, Ec)]
    return out


def _analyse(ticks: list[dict], label: str) -> None:
    n = len(ticks)
    print(f"\n=== {label}  (n={n}) ===")
    if n < MIN_SAMPLES:
        print(f"  insufficient: {n}/{MIN_SAMPLES} ticks — let the Loom run longer.")
        return
    series = {k: [float(t["m"].get(k, 0.5)) for t in ticks] for k in MODS}
    E = [float(t.get("E", {}).get("total", 0.0)) for t in ticks]
    centered = {k: _center(v) for k, v in series.items()}
    moved = {k: (sum(x * x for x in centered[k]) ** 0.5 > 1e-4) for k in MODS}

    # the common drive itself must actually vary for conditioning to mean anything
    E_varies = (sum(e * e for e in _center(E)) ** 0.5) > 1e-4
    resid = _residualise_on_E(series, E) if E_varies else centered

    print(f"  modulators that moved: {[k for k in MODS if moved[k]]}")
    print(f"  common drive E(t) varies: {E_varies}")
    print("  pair            raw|corr|   |corr | E|   (conditioned on the common drive)")
    worst_raw = worst_cond = 0.0
    wr = wc = ""
    for a in range(len(MODS)):
        for b in range(a + 1, len(MODS)):
            ka, kb = MODS[a], MODS[b]
            if not (moved[ka] and moved[kb]):
                continue
            raw = abs(_corr(centered[ka], centered[kb]))
            cond = abs(_partial_corr(series[ka], series[kb], E)) if E_varies else raw
            flag = "  <= co-firing (drops when E removed)" if raw - cond > 0.25 else ""
            print(f"  {ka:8s}~{kb:8s}   {raw:5.2f}       {cond:5.2f}{flag}")
            if raw > worst_raw:
                worst_raw, wr = raw, f"{ka}~{kb}"
            if cond > worst_cond:
                worst_cond, wc = cond, f"{ka}~{kb}"

    pr_raw = _participation_ratio([centered[k] for k in MODS if moved[k]] or [[0.0] * n])
    pr_res = _participation_ratio([resid[k] for k in MODS if moved[k]] or [[0.0] * n])
    rank_res = _grank([resid[k] for k in MODS if moved[k]])
    print(f"\n  participation ratio: raw {pr_raw:.2f}  ·  E-residualised {pr_res:.2f}  "
          f"(of {sum(moved.values())} moving)")
    print(f"  effective rank of E-residualised modulators: {rank_res}")
    print(f"  worst raw |corr|: {worst_raw:.2f} ({wr})  ·  worst |corr|E: {worst_cond:.2f} ({wc})")

    if not E_varies:
        print("  VERDICT: E(t) ~flat in this slice — conditioning uninformative; need busier data.")
    elif worst_cond < 0.6:
        print(f"  VERDICT: BENIGN CO-FIRING — the cluster ({wr}={worst_raw:.2f}) DROPS to "
              f"{worst_cond:.2f} once the common drive is removed. Independent channels, "
              "co-driven in time. Design HOLDS — do NOT escalate to circuit-selection.")
    else:
        print(f"  VERDICT: GENUINELY SLAVED -- {wc} survives conditioning at {worst_cond:.2f}. "
              "Not mere co-firing -> escalate (decouple the drive / circuit-selection).")


def main(argv: list[str]) -> int:
    rows = _load(TRACE_FILE)
    ticks = [r for r in rows if r.get("rec") == "tick"]
    concl = [r for r in rows if r.get("rec") == "conclude"]
    print(f"trace: {TRACE_FILE}")
    print(f"rows {len(rows)} · ticks {len(ticks)} · conclusions {len(concl)}")
    if not ticks:
        print("\nNo tick data yet — the trace fills only while the Loom runs its control "
              "loop (the autonomous daemon, or a manual no-arg run).")
        return 0
    reg = Counter(t.get("regime") for t in ticks)
    print(f"regimes: {dict(reg)}")
    _analyse(ticks, "ALL TICKS")
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for t in ticks:
        by_regime[t.get("regime")].append(t)
    for r in ("idle", "light", "busy", "saturated"):
        if by_regime.get(r):
            _analyse(by_regime[r], f"REGIME = {r}")
    if concl:
        depth = [c.get("eff_depth") for c in concl if isinstance(c.get("eff_depth"), int)]
        used = [c.get("steps_used") for c in concl if isinstance(c.get("steps_used"), int)]
        res = sum(1 for c in concl if c.get("resolved"))
        print(f"\n=== deliberations: {len(concl)} · resolved {res}/{len(concl)} ·"
              f" mean depth {sum(depth)/len(depth):.1f} · mean steps {sum(used)/len(used):.1f}"
              if depth and used else f"\n=== deliberations: {len(concl)} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
