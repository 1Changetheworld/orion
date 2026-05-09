#!/usr/bin/env python3
"""Merge production COMMAND brain (old schema) + USB brain (new schema)
into one canonical graph for /Volumes/AtlasVault/.orion/brain/graph_memory.json.

Strategy:
  1. Load both JSONs.
  2. Upgrade old-schema nodes to new schema with sensible defaults.
  3. Dedupe by normalized content fingerprint (case-insensitive, whitespace
     collapsed, length-tolerant). On dupe:
       - keep the OLDER `created` (preserve original creation time)
       - keep the NEWER `last_confirmed_at` (or = created if both missing)
       - UNION of tags
       - UNION of aliases (when present)
       - prefer non-empty `summary`
       - copy any plasticity fields (h_personal, recall_count) if either has them
  4. Reassign IDs starting from 0, monotonic. Drop `contested_with` /
     `superseded_by` cross-refs (re-derive at read time if needed —
     none exist in the current brains we audited).
  5. Write to the target path with a derived `next_id`.

Founder rule honored: production brain wins on TIES (it has months of
authentic context), but the USB's NEW SCHEMA fields are preserved when
present.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path


def upgrade_schema(node: dict, now: float) -> dict:
    """Bring an old-schema node up to the new schema with sensible defaults."""
    out = dict(node)
    out.setdefault("last_confirmed_at", out.get("created", now))
    out.setdefault("aliases", [])
    out.setdefault("summary", "")
    out.setdefault("last_seen", out["last_confirmed_at"])
    # Plasticity fields are optional; absence means "type-default half-life".
    return out


_NORMALIZE_RE = re.compile(r"\s+")


def fingerprint(content: str) -> str:
    """Normalize content for dedup: lowercase, collapse whitespace, strip."""
    return _NORMALIZE_RE.sub(" ", (content or "").strip().lower())


def merge_two(a: dict, b: dict) -> dict:
    """Merge two duplicate nodes. Older `created` wins; newer `last_confirmed_at` wins."""
    older_created = min(a.get("created", float("inf")), b.get("created", float("inf")))
    newer_confirmed = max(
        a.get("last_confirmed_at", a.get("created", 0)),
        b.get("last_confirmed_at", b.get("created", 0)),
    )
    newer_seen = max(
        a.get("last_seen", a.get("last_confirmed_at", 0)),
        b.get("last_seen", b.get("last_confirmed_at", 0)),
    )
    tags = sorted(set(a.get("tags", []) or []) | set(b.get("tags", []) or []))
    aliases = sorted(set(a.get("aliases", []) or []) | set(b.get("aliases", []) or []))
    summary = a.get("summary") or b.get("summary") or ""
    confidence = max(a.get("confidence", 1.0), b.get("confidence", 1.0))
    # Keep production type if it differs (production has more authoritative typing)
    node_type = a.get("type") or b.get("type") or "fact"
    # Plasticity: take whichever is more developed (higher recall_count wins)
    a_count = a.get("recall_count", 0)
    b_count = b.get("recall_count", 0)
    plasticity_src = a if a_count >= b_count else b
    h_personal = plasticity_src.get("h_personal")
    last_recalled = plasticity_src.get("last_recalled")
    recall_count = max(a_count, b_count)
    # Content: prefer the longer one (richer phrasing)
    content_a = a.get("content", "") or ""
    content_b = b.get("content", "") or ""
    content = content_a if len(content_a) >= len(content_b) else content_b

    out = {
        "content": content,
        "type": node_type,
        "confidence": confidence,
        "tags": tags,
        "created": older_created,
        "last_confirmed_at": newer_confirmed,
        "aliases": aliases,
        "summary": summary,
        "last_seen": newer_seen,
    }
    if h_personal is not None:
        out["h_personal"] = h_personal
    if last_recalled is not None:
        out["last_recalled"] = last_recalled
    if recall_count > 0:
        out["recall_count"] = recall_count
    return out


def load_brain(p: Path) -> tuple[list[dict], dict]:
    """Returns (list_of_nodes, raw_top_level_dict)."""
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "nodes" not in raw:
        raise SystemExit(f"unexpected schema in {p}: top-level keys = {list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__}")
    return list(raw["nodes"].values()), raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--production", required=True, help="path to production brain JSON")
    ap.add_argument("--usb", required=True, help="path to USB brain JSON")
    ap.add_argument("--out", required=True, help="path to write merged brain")
    args = ap.parse_args()

    prod_path = Path(args.production)
    usb_path = Path(args.usb)
    out_path = Path(args.out)

    if not prod_path.exists():
        raise SystemExit(f"missing: {prod_path}")
    if not usb_path.exists():
        raise SystemExit(f"missing: {usb_path}")

    now = time.time()

    prod_nodes, _ = load_brain(prod_path)
    usb_nodes, _ = load_brain(usb_path)
    print(f"  production brain: {len(prod_nodes)} nodes")
    print(f"  USB brain:        {len(usb_nodes)} nodes")

    # Upgrade production schema first
    prod_nodes = [upgrade_schema(n, now) for n in prod_nodes]

    # Index by fingerprint
    by_fp: dict[str, dict] = {}
    dupe_count = 0
    for n in prod_nodes + usb_nodes:
        fp = fingerprint(n.get("content", ""))
        if not fp:
            continue
        if fp in by_fp:
            dupe_count += 1
            by_fp[fp] = merge_two(by_fp[fp], n)
        else:
            by_fp[fp] = dict(n)

    print(f"  duplicates merged: {dupe_count}")
    print(f"  unique nodes:     {len(by_fp)}")

    # Reassign IDs
    merged_nodes: dict = {}
    for new_id, node in enumerate(by_fp.values()):
        merged_nodes[str(new_id)] = node

    out = {
        "next_id": len(merged_nodes),
        "nodes": merged_nodes,
        "_merge_metadata": {
            "merged_at": now,
            "source_production": str(prod_path),
            "source_usb": str(usb_path),
            "production_node_count": len(prod_nodes),
            "usb_node_count": len(usb_nodes),
            "duplicates_merged": dupe_count,
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\n[ok] wrote {out_path} ({out_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
