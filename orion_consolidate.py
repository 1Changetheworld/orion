#!/usr/bin/env python3
"""orion_consolidate.py — turn the brain's growing log into curated memory.

Memory that only ever grows is a log, not learning. This consolidates the
graph. ARCHIVE-NOT-DELETE: everything removed goes to graph_memory.archive.json
and can be restored; nothing is destroyed.

Two passes, deliberately split by risk:
  1. SAFE (applied with --apply): merge EXACT-duplicate nodes (keep the newest)
     and drop empty nodes. Identical content is unambiguously redundant.
  2. SALIENCE REPORT (never auto-applied): list low-value nodes — old AND
     low-confidence — that COULD be archived, so a human approves before the
     brain forgets anything judgment-laden.

    python orion_consolidate.py --graph <path>          # dry-run report
    python orion_consolidate.py --graph <path> --apply  # apply SAFE pass only
"""

import argparse
import json
import os
import time


def consolidate(graph_path, apply=False, decay_days=45, decay_conf=0.4):
    archive_path = graph_path.replace(".json", ".archive.json")
    with open(graph_path, encoding="utf-8") as f:
        d = json.load(f)
    nodes = d.get("nodes", {})
    if not isinstance(nodes, dict):
        return {"error": "unexpected graph shape"}

    # ── SAFE pass: exact-content dedup (keep newest) + drop empties ──
    order = sorted(nodes.items(), key=lambda kv: (kv[1].get("created") or 0))
    winner, archived = {}, {}
    for nid, n in order:
        content = (n.get("content") or "").strip()
        if not content:
            archived[nid] = n
            continue
        key = content  # EXACT match only — never merge merely-similar nodes
        if key in winner:
            archived[winner[key]] = nodes[winner[key]]  # older copy out
            winner[key] = nid                            # newest stays
        else:
            winner[key] = nid
    kept = {nid: n for nid, n in nodes.items() if nid not in archived}

    # ── SALIENCE report (not applied): old AND low-confidence among kept ──
    now = time.time()
    cutoff = now - decay_days * 86400
    decay_candidates = [
        nid for nid, n in kept.items()
        if (n.get("created") or now) < cutoff
        and (n.get("confidence") or 1.0) < decay_conf
    ]

    result = {
        "before": len(nodes),
        "exact_dups_and_empty_archived": len(archived),
        "after_safe": len(kept),
        "salience_decay_candidates": len(decay_candidates),
        "applied": False,
    }

    if apply:
        existing = {}
        if os.path.exists(archive_path):
            try:
                with open(archive_path, encoding="utf-8") as f:
                    existing = json.load(f).get("nodes", {})
            except Exception:
                existing = {}
        existing.update(archived)
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump({"nodes": existing}, f, ensure_ascii=False)
        d["nodes"] = kept
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        result["applied"] = True
        result["archive_path"] = archive_path
        result["archive_total"] = len(existing)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default=os.path.expanduser("~/.orion/brain/graph_memory.json"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--decay-days", type=int, default=45)
    args = ap.parse_args()
    print(json.dumps(consolidate(args.graph, apply=args.apply,
                                 decay_days=args.decay_days), indent=2))


if __name__ == "__main__":
    main()
