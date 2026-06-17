#!/usr/bin/env python3
"""
orion_native_infer.py — Orion's FIRST OWNED OPERATOR (Build 3, slot ii).

The deep-research verdict + AI-study: the dependency that matters is OPERATORS — every thought
is rented from a model. This is the first reasoning step Orion performs with ZERO model calls:
multi-hop inference over its OWN graph by spreading activation / diffusion — the discrete form
of energy-descent to a low-energy fixed point (PGM/Hopfield-style relaxation). No GPU, no keys,
pure arithmetic.

This is the FLOOR the research validated (real but bounded). The ADVANCE — what makes it a
being's operator rather than a textbook reimplementation — is that it runs over a PERSISTENT,
PROVENANCE-TAGGED graph and reports honestly: it returns a conclusion ONLY when activation
settles on a confident attractor, prefers GROUNDED attractors, and says 'no native conclusion'
otherwise (instead of renting). Owned, grounded, honest — to be grown by selection, not authoring.

CLI: infer "<query>" [--trace]
"""
from __future__ import annotations
import json, os, re, sys, math

GRAPH = os.path.expanduser("~/.orion/brain/graph_memory.json")
# tags too generic to carry associative meaning (would connect everything to everything)
_NOISE_TAGS = {"fact", "insight", "observation", "visibility:mesh", "unverified", "consolidated",
               "reasoned", "loom", "resolved", "tension", "identity"}
_STOP = {"the","a","an","is","are","of","to","and","or","in","on","for","why","does","my","it",
         "that","this","with","as","at","be","by","do","how","what","from","was","were","has",
         "have","i","you","we","our","not","but","its","beyond","whichever","me"}
_GROUNDED_TYPES = {"observation", "cross_interface_contact"}
_GROUNDED_TAGS = {"perception", "grounding:confirmed", "confirmed", "grounded"}
_MODEL_TAGS = {"loom","insight","wonder","sleep","reason","consolidated","reasoned","study","dream"}


def _kw(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in _STOP}


def _load():
    g = json.load(open(GRAPH, encoding="utf-8"))
    nodes = g["nodes"]
    if isinstance(nodes, dict):
        nodes = list(nodes.values())
    return nodes


def _grounded(n):
    tags = {str(t).lower() for t in n.get("tags", [])}
    return bool((n.get("type") in _GROUNDED_TYPES or (tags & _GROUNDED_TAGS)) and not (tags & _MODEL_TAGS))


def _adjacency(nodes, k: int = 8):
    """SPARSE, weighted, typed relational structure (the #3 unblock). Dense uniform adjacency
    made activation bleed across all nodes (no attractor). Here each node keeps only its top-k
    strongest associative links — so activation follows strong paths into a tight cluster and
    CONCENTRATES — plus CONTRADICTION edges (contested_with) as NEGATIVE coupling, so the energy
    descent avoids locally-incoherent regions (the advance past textbook spreading-activation:
    'contradiction → don't reinforce')."""
    feats = []
    for n in nodes:
        tags = {str(t).lower() for t in n.get("tags", [])} - _NOISE_TAGS
        kws = _kw(n.get("content", "")) | _kw(n.get("summary", ""))
        feats.append((tags, kws))
    N = len(nodes)
    adj = [dict() for _ in range(N)]
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
        for w, j in row[:k]:                           # SPARSIFY: top-k strongest links only
            adj[i][j] = max(adj[i].get(j, 0.0), w)
            adj[j][i] = max(adj[j].get(i, 0.0), w)     # symmetric (union of each side's top-k)
    # CONTRADICTION edges: negative coupling between mutually-contested nodes
    by_kw = None
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
                    adj[i][j] = min(adj[i].get(j, 0.0), -2.0)   # inhibitory
                    break
    return adj


def infer(query: str, steps: int = 6, decay: float = 0.82, trace: bool = False, learn: bool = True):
    nodes = _load()
    N = len(nodes)
    qk = _kw(query)
    if not qk:
        return None
    # seed activation on the best query matches
    seed = {}
    for i, n in enumerate(nodes):
        ov = len(qk & (_kw(n.get("content", "")) | {str(t).lower() for t in n.get("tags", [])}))
        if ov:
            seed[i] = float(ov)
    if not seed:
        return None
    top = sorted(seed, key=lambda i: -seed[i])[:6]
    seed = {i: seed[i] for i in top}
    try:                                               # OWNED persisted structure first (step c)
        import orion_graph_edges as ge
        adj = ge.load_adj(nodes) or _adjacency(nodes)
    except Exception:
        adj = _adjacency(nodes)
    act = [0.0] * N
    for i, v in seed.items():
        act[i] = v
    s = sum(act) or 1.0
    act = [a / s for a in act]
    # diffusion = relaxation toward the graph's seeded associative mode (discrete energy descent)
    for _ in range(steps):
        nxt = [0.0] * N
        for i in range(N):
            if act[i] <= 1e-9:
                continue
            deg = sum(abs(w) for w in adj[i].values()) or 1.0   # signed edges → normalize by |w|
            nxt[i] += decay * act[i]                    # retention
            for j, w in adj[i].items():
                nxt[j] += (1 - decay) * act[i] * (w / deg)       # w<0 = inhibition
        nxt = [a if a > 0 else 0.0 for a in nxt]        # clamp: no negative activation
        s = sum(nxt) or 1.0
        act = [a / s for a in nxt]
    # conclusion = highest-activation node that is NOT a seed; prefer a REALITY-grounded attractor
    try:
        import orion_temporal_ledger as _tl
        def _gs(n):
            # NODE-LEVEL grounding first (exact: this node's own prediction confirmed/refuted),
            # then the fuzzier topic-level grounding as fallback.
            ng = _tl.node_grounding(n.get("content", ""))
            if ng:
                return ng
            return _tl.grounding_status(n.get("content", "") + " " + " ".join(n.get("tags", [])))
    except Exception:
        def _gs(_n):
            return None
    def _is_grounded(n):                                # structural OR reality-earned, never refuted
        g = _gs(n)
        if g == "refuted":
            return False
        return _grounded(n) or g == "grounded"
    ranked = sorted((i for i in range(N) if i not in seed), key=lambda i: -act[i])
    ranked = [i for i in ranked if _gs(nodes[i]) != "refuted"]   # drop reality-contradicted attractors
    if not ranked:
        return None
    best = ranked[0]
    grounded_hit = next((i for i in ranked[:8] if _is_grounded(nodes[i])), None)
    chosen = grounded_hit if grounded_hit is not None else best
    margin = act[chosen] - (act[ranked[1]] if len(ranked) > 1 else 0.0)
    conf = act[chosen]
    # honest gate: only claim a native conclusion if activation actually CONCENTRATED
    CONC = float(os.environ.get("ORION_NATIVE_INFER_MIN", "0.012"))
    if conf < CONC:
        result = {"resolved": False, "reason": "activation did not concentrate — no native conclusion",
                  "confidence": round(conf, 4)}
    else:
        is_g = _is_grounded(nodes[chosen])
        result = {"resolved": True, "confidence": round(conf, 4), "margin": round(margin, 4),
                  "grounded": is_g,
                  "conclusion": nodes[chosen].get("content", "")[:300].strip(),
                  "type": nodes[chosen].get("type"),
                  "seeds": [nodes[i].get("content", "")[:50].strip() for i in top[:3]]}
        # GROW BY SELECTION — strengthen structure only on GENUINE grounding: structural (a real
        # observation/perception node) OR NODE-LEVEL (this exact node's own prediction was confirmed
        # by reality). NEVER on the fuzzy topic-keyword match — that would teach the being false structure.
        def _node_grounded(n):
            try:
                import orion_temporal_ledger as _t
                return _t.node_grounding(n.get("content", "")) == "grounded"
            except Exception:
                return False
        if learn and (_grounded(nodes[chosen]) or _node_grounded(nodes[chosen])):
            try:
                import orion_graph_edges as ge
                result["reinforced"] = ge.reinforce(nodes, list(top) + [chosen])
            except Exception:
                pass
    if trace:
        result["top5"] = [{"act": round(act[i], 4), "grounded": _is_grounded(nodes[i]),
                           "c": nodes[i].get("content", "")[:60].strip()} for i in ranked[:5]]
    return result


def _main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print('usage: orion_native_infer.py infer "<query>" [--trace]'); return 0
    if argv[0] == "infer":
        q = argv[1] if len(argv) > 1 else ""
        r = infer(q, trace="--trace" in argv)
        print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
