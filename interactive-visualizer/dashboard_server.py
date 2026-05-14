#!/usr/bin/env python3
"""orion_dashboard — a window into Orion's mind.

Founder ask 2026-05-14: visualization of the brain as an entity. An
Obsidian-graph-style view where memory nodes connect by tag/type,
hosts appear as receptors, and the substrate's recent activity
flows through the picture in real time.

This is the central viewing hub (task #48). NOT a separate dashboard
listing services — the visualization IS the dashboard. Services
appear inside the graph as receptor nodes; their vitals modulate
their visual state.

Architecture (kept additive — no removal of existing endpoints):
  - Same Python, no new deps beyond stdlib
  - Reads ~/.orion/brain/graph_memory.json (the entity)
  - Reads ~/.orion/consciousness/state.json (claustrum's percept)
  - Reads ~/.orion/vitals/*.json (per-service vitals)
  - Serves a single HTML page at /
  - Serves JSON at /api/graph (graph_memory + derived edges)
  - Serves JSON at /api/pulse (claustrum + vitals snapshot)
  - SSE stream at /events for live updates (deferred to v0.2)

Run:  python dashboard_server.py [--port 5556]
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
from collections import Counter, defaultdict
from pathlib import Path

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))

GRAPH_PATH = ORION_HOME / "brain" / "graph_memory.json"
CLAUSTRUM_PATH = ORION_HOME / "consciousness" / "state.json"
VITALS_DIR = ORION_HOME / "vitals"

PORT = 5557


def _load_graph() -> dict:
    """Return the entity's memory graph as JSON-serializable dict.

    Nodes: every memory item. Edges: derived from shared tags
    (Obsidian-style) — two nodes that share a non-trivial tag get an
    edge. Cheap, deterministic, lights up the visualization without
    needing an explicit relation table.
    """
    if not GRAPH_PATH.exists():
        return {"nodes": [], "links": [], "stats": {"total": 0}}
    try:
        raw = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"could not read graph: {e}", "nodes": [], "links": []}

    raw_nodes = raw.get("nodes", {})
    # Tag-based edges (skip common stopword-like tags)
    SKIP_TAGS = {"fact", "preference", "project", "identity", "task",
                 "ephemeral", "person", "skill"}

    nodes = []
    tag_to_ids = defaultdict(list)
    type_counts = Counter()

    for nid_str, node in raw_nodes.items():
        try:
            nid = int(nid_str)
        except Exception:
            continue
        ntype = node.get("type", "fact")
        type_counts[ntype] += 1
        content = node.get("content", "")
        if isinstance(content, str):
            preview = content[:140]
        else:
            preview = str(content)[:140]
        tags = node.get("tags", []) or []
        if isinstance(tags, set):
            tags = list(tags)
        nodes.append({
            "id": nid,
            "type": ntype,
            "preview": preview,
            "tags": tags[:8],
            "confidence": node.get("confidence", 1.0),
            "created": node.get("created", 0),
        })
        for t in tags:
            tlow = (t or "").strip().lower()
            if tlow and tlow not in SKIP_TAGS:
                tag_to_ids[tlow].append(nid)

    # Build edges from co-occurring tags (cap at 5 edges per pair)
    seen_pair = set()
    links = []
    for tag, ids in tag_to_ids.items():
        if len(ids) < 2:
            continue
        # Connect each node to the chronologically nearest sibling
        # rather than fully meshing — keeps the graph readable.
        for i, a in enumerate(ids):
            for b in ids[i+1:i+3]:
                pair = (min(a, b), max(a, b))
                if pair in seen_pair:
                    continue
                seen_pair.add(pair)
                links.append({"source": a, "target": b, "via": tag})

    return {
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_nodes": len(nodes),
            "total_links": len(links),
            "by_type": dict(type_counts),
        },
    }


def _load_pulse() -> dict:
    """Snapshot claustrum + vitals + recent substrate signal."""
    import platform
    pulse = {"claustrum": None, "vitals": {}, "host": platform.node()}

    try:
        if CLAUSTRUM_PATH.exists():
            pulse["claustrum"] = json.loads(
                CLAUSTRUM_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    if VITALS_DIR.exists():
        for f in VITALS_DIR.glob("*.json"):
            try:
                pulse["vitals"][f.stem] = json.loads(
                    f.read_text(encoding="utf-8"))
            except Exception:
                continue

    return pulse


# ─────────────────────────────────────────────────────────
# HTTP handler
# ─────────────────────────────────────────────────────────

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/graph":
            return self._json(_load_graph())
        if self.path == "/api/pulse":
            return self._json(_load_pulse())
        if self.path in ("/", "/index.html"):
            return self._serve_static("index.html", "text/html; charset=utf-8")
        return super().do_GET()

    def _json(self, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, name: str, ctype: str) -> None:
        path = Path(__file__).resolve().parent / name
        if not path.exists():
            self.send_error(404, name)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Quieter than default
        sys.stderr.write(f"[dashboard] {fmt % args}\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args(argv[1:])

    print(f"[orion-dashboard] serving on http://127.0.0.1:{args.port}")
    print(f"  graph from: {GRAPH_PATH}")
    print(f"  pulse from: {CLAUSTRUM_PATH}, {VITALS_DIR}")

    with socketserver.ThreadingTCPServer(("0.0.0.0", args.port), Handler) as srv:
        srv.allow_reuse_address = True
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n[orion-dashboard] bye")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
