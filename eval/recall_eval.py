#!/usr/bin/python3
"""RECALL A/B EVAL — old stopword-overlap recall vs fused recall, mechanically.

Retrieval only: no orion_brain, no fuel, no conversation. The only network
calls are local (Ollama embeddings, Qdrant). Safe for the builder to run.

Each query lists expected evidence groups (OR within a group, AND across
groups). A recall PASSES a query when every group has at least one hit in the
returned context. Score = passed queries; also shown per-query coverage.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import orion_memory  # noqa: E402

# Truths James approved in the battery (2026-10-02). H/E-style traps are
# excluded — a trap tests the brain's honesty, not retrieval.
CASES = [
    ("What's my major and where?", [["computer science"], ["louisville", "uofl"]]),
    ("Where is my chemistry lecture?", [["strickler"], ["102"]]),
    ("Who teaches my chemistry class?", [["franco"]]),
    ("What's my first class on Monday?", [["gen 100", "gen100"], ["8:00", "8 am", "8am"]]),
    ("Which days can I sleep in past 10?", [["tuesday", "tue"], ["thursday", "thu"]]),
    ("When is fall break?", [["fall break", "october", "oct 5", "10/5"]]),
    ("If I skip Monday entirely, which classes do I miss?",
     [["gen 100", "gen100"], ["cse 120", "cse120"], ["engl"]]),
]


def coverage(context, groups):
    c = (context or "").lower()
    hit = [any(alt in c for alt in g) for g in groups]
    return sum(hit), len(hit)


def run(fn, name):
    print("== %s ==" % name)
    passed = 0
    for query, groups in CASES:
        t0 = time.time()
        ctx = fn(query)
        ms = int((time.time() - t0) * 1000)
        got, total = coverage(ctx, groups)
        ok = got == total
        passed += ok
        print("%-5s %d/%d %4dms  %s" % ("PASS" if ok else "miss", got, total, ms, query))
        if not ok:
            head = (ctx or "(empty)").replace("\n", " | ")[:220]
            print("        got: %s" % head)
    print("%s TOTAL: %d/%d\n" % (name, passed, len(CASES)))
    return passed


# Queries about things that exist NOWHERE in memory. The right recall output
# is "" (the brain then honestly says it doesn't know). Returning a context
# blob here is noise injection — the raw material of confabulated answers
# like the fabricated gold price (2026-10-02 13:34).
TRAPS = [
    "What did we decide about migrating your brain to Postgres last month?",
    "What's the name of my dog?",
    "What hotel did we book in Denver for the conference?",
]


def run_traps(fn, name):
    quiet = 0
    print("== %s : noise on never-happened topics ==" % name)
    for q in TRAPS:
        ctx = fn(q) or ""
        is_quiet = len(ctx.strip()) == 0
        quiet += is_quiet
        print("%-6s %s" % ("quiet" if is_quiet else "NOISE", q))
        if not is_quiet:
            print("        injected: %s" % ctx.replace("\n", " | ")[:180])
    print("%s: quiet on %d/%d traps\n" % (name, quiet, len(TRAPS)))
    return quiet


if __name__ == "__main__":
    old = run(orion_memory.remember_legacy, "OLD (stopword overlap + vector blob)")
    new = run(orion_memory.remember, "NEW (fused lexical+semantic, RRF)")
    old_q = run_traps(orion_memory.remember_legacy, "OLD")
    new_q = run_traps(orion_memory.remember, "NEW")
    print("verdict: facts old %d/%d -> new %d/%d | trap-quiet old %d/%d -> new %d/%d"
          % (old, len(CASES), new, len(CASES), old_q, len(TRAPS), new_q, len(TRAPS)))
    sys.exit(0 if (new >= old and new_q >= old_q) else 1)
