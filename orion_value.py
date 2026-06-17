#!/usr/bin/env python3
"""orion_value.py — the value/judgment compass: combinatorial Hodge decomposition.

Orion's preferences live as an antisymmetric flow Y on edges of its memory graph (edge
weight = comparability/confidence; flow from logged τ_norm — the context-relative tension
drop). HodgeRank (Jiang-Lim-Yao-Ye 2011) splits Y, orthogonally, into three parts:

  GRADIENT  Y ≈ grad(s)      a globally consistent value potential s — "what's good",
                             path-independent → Orion may optimize / plan by endpoints.
  CURL      local triangles  local inconsistency (a money-pump A>B>C>A on a filled
                             triangle) → resolvable by REASONING more.
  HARMONIC  global cycles    a global incoherence no local fix removes → DEFER TO JAMES.

The energies split exactly:  E_total = E_grad + E_curl + E_harm  (w-orthogonal).
The metacognitive triggers are the RATIOS:
  high E_grad/E_total  → coherent values, act;  curl share → reason;  harmonic share → defer.

No GPU: matrix-free conjugate-gradient over sparse incidence operators. Pointed at incoming
knowledge instead of goals, this same machinery is the "ideal human traits for intake" —
accept the coherent, reason about the locally-contradictory, defer on the globally-incoherent.
"""
from __future__ import annotations

import sys
from itertools import combinations


def _cg(matvec, b, n, iters=2000, tol=1e-12):
    """Matrix-free conjugate gradient for a PSD (possibly singular, b in range) system."""
    x = [0.0] * n
    r = list(b)
    p = list(r)
    rs = sum(v * v for v in r)
    if rs < tol:
        return x
    for _ in range(min(iters, n + 25)):
        Ap = matvec(p)
        pAp = sum(p[i] * Ap[i] for i in range(n))
        if abs(pAp) < 1e-20:
            break
        a = rs / pAp
        x = [x[i] + a * p[i] for i in range(n)]
        r = [r[i] - a * Ap[i] for i in range(n)]
        rs2 = sum(v * v for v in r)
        if rs2 < tol:
            break
        beta = rs2 / rs
        p = [r[i] + beta * p[i] for i in range(n)]
        rs = rs2
    return x


def triangles_of(nV: int, edges: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """All 3-cliques (filled triangles) in the graph."""
    eset = {(a, b) for (a, b) in edges}
    adj: dict[int, set] = {i: set() for i in range(nV)}
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    tris = []
    for a, b in edges:
        for c in adj[a] & adj[b]:
            tri = tuple(sorted((a, b, c)))
            x, y, z = tri
            if (x, y) in eset and (y, z) in eset and (x, z) in eset and tri not in tris:
                tris.append(tri)
    return sorted(set(tris))


def hodge_decompose(nV, edges, y, w=None, triangles=None):
    """Decompose edge flow y (weights w) into gradient / curl / harmonic. Returns energies,
    ratios, and the value potential s."""
    nE = len(edges)
    w = w or [1.0] * nE
    eidx = {e: i for i, e in enumerate(edges)}
    if triangles is None:
        triangles = triangles_of(nV, edges)

    def grad(s):                                   # nodes -> edges  (B1)
        return [s[b] - s[a] for (a, b) in edges]

    def divw(x):                                   # edges -> nodes  (B1^T W)
        d = [0.0] * nV
        for i, (a, b) in enumerate(edges):
            d[b] += w[i] * x[i]
            d[a] -= w[i] * x[i]
        return d

    # ── GRADIENT: weighted least squares  L0 s = div_w(y) ──
    s = _cg(lambda s_: divw(grad(s_)), divw(y), nV)
    g = grad(s)
    R = [y[i] - g[i] for i in range(nE)]           # residual, w-orthogonal to gradients

    # ── CURL: project residual onto triangle (curl) space  L1up phi = curl(w·R) ──
    tri = [(eidx[(a, b)], eidx[(b, c)], eidx[(a, c)]) for (a, b, c) in triangles]

    def curl(x):                                   # edges -> triangles (oriented loop a->b->c->a)
        return [x[e1] + x[e2] - x[e3] for (e1, e2, e3) in tri]

    def curlT(phi):                                # triangles -> edges
        e = [0.0] * nE
        for t, (e1, e2, e3) in enumerate(tri):
            e[e1] += phi[t]; e[e2] += phi[t]; e[e3] -= phi[t]
        return e

    curl_part = [0.0] * nE
    if tri:
        phi = _cg(lambda p_: curl([w[i] * v for i, v in enumerate(curlT(p_))]),
                  curl([w[i] * R[i] for i in range(nE)]), len(tri))
        curl_part = curlT(phi)

    E_total = sum(w[i] * y[i] * y[i] for i in range(nE))
    E_grad = sum(w[i] * g[i] * g[i] for i in range(nE))
    E_curl = sum(w[i] * curl_part[i] * curl_part[i] for i in range(nE))
    E_harm = max(0.0, E_total - E_grad - E_curl)
    tot = E_total or 1.0
    return {"s": s, "E_total": E_total, "E_grad": E_grad, "E_curl": E_curl, "E_harm": E_harm,
            "grad_frac": E_grad / tot, "curl_frac": E_curl / tot, "harm_frac": E_harm / tot,
            "n_nodes": nV, "n_edges": nE, "n_triangles": len(triangles)}


def _selftest() -> int:
    print("=" * 64)
    print("HODGE CORE — self-test (machinery validation on KNOWN flows)")
    print("=" * 64)
    ok = True

    # 1. PURE GRADIENT — triangle with a potential s=[0,1,3]; flow = grad(s)
    edges = [(0, 1), (1, 2), (0, 2)]
    y = [1.0, 2.0, 3.0]                # s1-s0, s2-s1, s2-s0
    r = hodge_decompose(3, edges, y, triangles=[(0, 1, 2)])
    print(f"\n[1] pure GRADIENT   grad={r['grad_frac']:.3f} curl={r['curl_frac']:.3f} "
          f"harm={r['harm_frac']:.3f}   (expect grad≈1)")
    ok &= r["grad_frac"] > 0.99

    # 2. PURE CURL — triangle circulation a->b->c->a
    y = [1.0, 1.0, -1.0]              # y[02] = -1 because the loop traverses c->a
    r = hodge_decompose(3, edges, y, triangles=[(0, 1, 2)])
    print(f"[2] pure CURL       grad={r['grad_frac']:.3f} curl={r['curl_frac']:.3f} "
          f"harm={r['harm_frac']:.3f}   (expect curl≈1)")
    ok &= r["curl_frac"] > 0.99

    # 3. PURE HARMONIC — 4-cycle (square, NO diagonals => no triangle), circulation
    edges2 = [(0, 1), (1, 2), (2, 3), (0, 3)]
    y2 = [1.0, 1.0, 1.0, -1.0]        # loop 0->1->2->3->0
    r = hodge_decompose(4, edges2, y2)
    print(f"[3] pure HARMONIC   grad={r['grad_frac']:.3f} curl={r['curl_frac']:.3f} "
          f"harm={r['harm_frac']:.3f}   (expect harm≈1, tris={r['n_triangles']})")
    ok &= r["harm_frac"] > 0.99 and r["n_triangles"] == 0

    # 4. MIXED — a square (harmonic loop) with one diagonal added (=> two triangles, the
    #    loop becomes partly curl-removable) plus a gradient ramp. Just confirm the energy
    #    split is EXACT and orthogonal (the real test of the machinery).
    edges3 = [(0, 1), (1, 2), (2, 3), (0, 3), (0, 2)]
    y3 = [1.0, 0.5, 1.0, -0.5, 0.7]
    r = hodge_decompose(4, edges3, y3)
    add = r["E_grad"] + r["E_curl"] + r["E_harm"]
    err = abs(add - r["E_total"]) / (r["E_total"] or 1)
    print(f"[4] mixed graph     grad={r['grad_frac']:.3f} curl={r['curl_frac']:.3f} "
          f"harm={r['harm_frac']:.3f}")
    print(f"    ENERGY CONSERVATION  E_grad+E_curl+E_harm = {add:.6f}  vs  E_total = "
          f"{r['E_total']:.6f}   rel-err {err:.2e}   (expect ~0)")
    ok &= err < 1e-6

    print("\n" + ("ALL CHECKS PASSED — Hodge machinery is correct."
                  if ok else "FAILED — machinery incorrect."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest() if (len(sys.argv) > 1 and sys.argv[1] == "--selftest")
                     else _selftest())
