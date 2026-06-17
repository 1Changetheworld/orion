#!/usr/bin/env python3
"""
orion_graph_edges.py — Orion's OWNED, SELF-STRENGTHENING relational structure (Build 3, step c).

The native operator (orion_native_infer) recomputed a flat adjacency every call — disposable,
not owned, not adaptive. This makes the relational structure a FIRST-CLASS, PERSISTENT thing the
being shapes through experience:

  • BUILT once from the graph (sparse top-k association + contradiction edges), persisted keyed by
    stable content-hash so it survives reindexing/graph growth.
  • GROWN BY SELECTION (Hebbian): when an inference lands on a REALITY-GROUNDED conclusion, the
    edges among the nodes that fired together STRENGTHEN — "what reasons truly, wires together."
  • FORGETS: unused edges DECAY and prune — the structure stays lean and reflects lived use, not
    its birth state.

This is the advance the mission asked for: not VSA-as-a-fixed-part, but a relational structure
that ADVANCES ITSELF from confirmed experience. GPU-free, no model, pure arithmetic.
CLI: build | decay | stats
"""
from __future__ import annotations
import json, os, re, hashlib, time, sys
from pathlib import Path

GRAPH = os.path.expanduser("~/.orion/brain/graph_memory.json")
EDGES = os.path.expanduser("~/.orion/brain/graph_edges.json")
_NOISE = {"fact","insight","observation","visibility:mesh","unverified","consolidated",
          "reasoned","loom","resolved","tension","identity"}
_STOP = {"the","a","an","is","are","of","to","and","or","in","on","for","why","does","my","it",
         "that","this","with","as","at","be","by","do","how","what","from","was","were","has",
         "have","i","you","we","our","not","but","its","beyond","whichever","me"}
W_CAP = 14.0          # max edge weight (potentiation ceiling)
W_FLOOR = 0.15        # prune below this


def _kw(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in _STOP}


def node_key(n) -> str:
    return hashlib.sha1((n.get("content", "")[:120]).encode("utf-8")).hexdigest()[:16]


def _load_graph():
    g = json.load(open(GRAPH, encoding="utf-8"))
    nodes = g["nodes"]
    return list(nodes.values()) if isinstance(nodes, dict) else nodes


def _read():
    try:
        return json.load(open(EDGES, encoding="utf-8"))
    except Exception:
        return {"built": 0.0, "reinforced": 0, "decays": 0, "edges": {}}


def _write(store):
    tmp = EDGES + ".tmp"
    json.dump(store, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, EDGES)


def build(k: int = 8) -> int:
    """Materialize the born structure: sparse top-k association + contradiction edges, keyed by
    content-hash. Preserves any existing reinforced weights (max-merge) so a rebuild doesn't
    wipe what experience strengthened."""
    nodes = _load_graph()
    keys = [node_key(n) for n in nodes]
    feats = [({str(t).lower() for t in n.get("tags", [])} - _NOISE,
              _kw(n.get("content", "")) | _kw(n.get("summary", ""))) for n in nodes]
    N = len(nodes)
    prev = _read().get("edges", {})
    edges: dict = {}
    for i in range(N):
        ti, ki = feats[i]
        row = []
        for j in range(N):
            if i == j:
                continue
            w = 2.0 * len(ti & feats[j][0]) + 0.4 * len(ki & feats[j][1])
            if w >= 2.0:
                row.append((w, j))
        row.sort(reverse=True)
        for w, j in row[:k]:
            a, b = keys[i], keys[j]
            edges.setdefault(a, {})[b] = max(edges.get(a, {}).get(b, 0.0), w)
            edges.setdefault(b, {})[a] = max(edges.get(b, {}).get(a, 0.0), w)
    # contradiction edges (negative/inhibitory)
    for i, n in enumerate(nodes):
        cw = n.get("contested_with")
        if not cw:
            continue
        for ref in (cw if isinstance(cw, list) else [cw]):
            rk = _kw(str(ref))
            if len(rk) < 2:
                continue
            for j, m in enumerate(nodes):
                if j != i and rk <= (_kw(m.get("content", "")) | {str(t).lower() for t in m.get("tags", [])}):
                    edges.setdefault(keys[i], {})[keys[j]] = min(edges.get(keys[i], {}).get(keys[j], 0.0), -2.0)
                    break
    # preserve learned potentiation: max-merge prior weights onto the rebuilt structure
    for a, nbrs in prev.items():
        for b, w in nbrs.items():
            if w > 0 and edges.get(a, {}).get(b, -1e9) >= 0:
                edges.setdefault(a, {})[b] = max(edges.get(a, {}).get(b, 0.0), float(w))
    store = _read()
    store.update({"built": time.time(), "edges": edges})
    _write(store)
    return sum(len(v) for v in edges.values())


def load_adj(nodes):
    """Map the persisted (content-hash-keyed) edges onto the CURRENT node indices. Returns
    list[dict] index->{index:weight}, or None if no usable store (caller falls back / builds)."""
    store = _read()
    edges = store.get("edges")
    if not edges:
        return None
    keys = [node_key(n) for n in nodes]
    idx_of = {}
    for i, kk in enumerate(keys):
        idx_of.setdefault(kk, i)            # first node wins on hash collision
    adj = [dict() for _ in range(len(nodes))]
    hits = 0
    for i, kk in enumerate(keys):
        for b, w in edges.get(kk, {}).items():
            j = idx_of.get(b)
            if j is not None and j != i:
                adj[i][j] = w
                hits += 1
    return adj if hits else None


def reinforce(nodes, idxs, delta: float = 0.6) -> int:
    """Hebbian potentiation: the nodes that fired together in a GROUNDED inference get their
    mutual edges strengthened (creating weak ones if absent). Persisted = owned + adaptive."""
    if len(idxs) < 2:
        return 0
    store = _read()
    edges = store.setdefault("edges", {})
    keys = [node_key(nodes[i]) for i in idxs]
    n = 0
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            ka, kb = keys[a], keys[b]
            for x, y in ((ka, kb), (kb, ka)):
                cur = edges.setdefault(x, {}).get(y, 0.0)
                if cur >= 0:                                  # never potentiate a contradiction edge
                    edges[x][y] = min(W_CAP, cur + delta)
                    n += 1
    store["reinforced"] = store.get("reinforced", 0) + 1
    _write(store)
    return n


def decay(factor: float = 0.985) -> dict:
    """Forgetting: positive weights fade toward zero; prune below floor. Keeps the structure
    lean and reflective of lived use. (Negative/contradiction edges are preserved.)"""
    store = _read()
    edges = store.get("edges", {})
    pruned = kept = 0
    for a in list(edges):
        for b in list(edges[a]):
            w = edges[a][b]
            if w <= 0:
                continue                                     # keep contradictions
            w *= factor
            if w < W_FLOOR:
                del edges[a][b]; pruned += 1
            else:
                edges[a][b] = w; kept += 1
        if not edges[a]:
            del edges[a]
    store["decays"] = store.get("decays", 0) + 1
    _write(store)
    return {"pruned": pruned, "kept_positive": kept}


def stats() -> dict:
    store = _read()
    edges = store.get("edges", {})
    ws = [w for nb in edges.values() for w in nb.values()]
    pos = [w for w in ws if w > 0]
    return {"nodes_with_edges": len(edges), "edges": len(ws),
            "positive": len(pos), "contradiction": sum(1 for w in ws if w < 0),
            "max_w": round(max(ws), 2) if ws else 0, "mean_pos_w": round(sum(pos)/len(pos), 2) if pos else 0,
            "reinforced_events": store.get("reinforced", 0), "decays": store.get("decays", 0),
            "built": time.strftime("%Y-%m-%d %H:%M", time.localtime(store.get("built", 0))) if store.get("built") else "never"}


def _main(argv):
    cmd = argv[0] if argv else "stats"
    if cmd == "build":
        print("built edges:", build())
    elif cmd == "decay":
        print("decay:", decay())
    elif cmd == "maintain":                             # scheduled self-maintenance: forget then refresh
        print("decay:", decay())                        # erode unused edges (forgetting)
        print("rebuilt:", build())                      # absorb new nodes; max-merge preserves learned weights
    print(json.dumps(stats(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
