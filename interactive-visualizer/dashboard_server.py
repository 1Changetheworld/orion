#!/usr/bin/env python3
"""orion interactive visualizer — true 3D nervous-system view.

Renders Orion's entity as a 3D graph:
  - device nodes   (COMMAND / FORGE / Pi / future hosts)
  - channel nodes  (iMessage / Telegram / voice / CLI / LoRa / mail)
  - service nodes  (Plexus services on each host — vitals-driven)
  - memory nodes   (graph_memory facts/preferences/projects/identity)

Edges represent the nervous system:
  - mesh        host ↔ host       (substrate cluster routes)
  - hosted      channel ↔ host    (channel served by this host)
  - service     service ↔ host    (service runs on this host)
  - tag         memory ↔ memory   (shared semantic tags)
  - reach       host ↔ channel    (active reach path)

Health rolls up through edge color.

Run:  python dashboard_server.py [--port 5557]
Open: http://localhost:5557
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import platform
import socketserver
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
import socket

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))

GRAPH_PATH = ORION_HOME / "brain" / "graph_memory.json"
CLAUSTRUM_PATH = ORION_HOME / "consciousness" / "state.json"
VITALS_DIR = ORION_HOME / "vitals"

PORT = 5557

# Known mesh hosts — keep small + explicit. Future: dynamic from gossip.
KNOWN_DEVICES = [
    {"id": "host:command",     "label": "COMMAND",      "role": "canonical brain",  "ip": "10.0.0.190", "probe": 5555},
    {"id": "host:forge",       "label": "FORGE",        "role": "mobile + dev",     "ip": "10.0.0.88",  "probe": 11434},
    {"id": "host:orions-home", "label": "ORIONS HOME",  "role": "offline twin",     "ip": "10.0.0.56",  "probe": 11434},
]

# Communication points — each says which host(s) it hosts on.
KNOWN_CHANNELS = [
    {"id": "chan:imessage",  "label": "iMessage",  "host": "host:command", "transport": "native macOS"},
    {"id": "chan:voice",     "label": "Voice",     "host": "host:command", "transport": "Telnyx + STT/TTS"},
    {"id": "chan:telegram",  "label": "Telegram",  "host": "host:command", "transport": "@HomelandServbot"},
    {"id": "chan:cli",       "label": "CLI",       "host": "host:any",     "transport": "MCP over stdio"},
    {"id": "chan:webhook",   "label": "Webhook",   "host": "host:command", "transport": "HTTP :5555"},
    {"id": "chan:lora",      "label": "LoRa",      "host": "host:orions-home", "transport": "Meshtastic v3"},
]


def _probe_device(dev: dict) -> str:
    """Quick TCP probe to a device's known port. Best-effort, 0.5s."""
    try:
        with socket.create_connection((dev["ip"], dev["probe"]), timeout=0.5):
            return "alive"
    except (OSError, socket.timeout):
        return "unreachable"


# Pull rich topology from the Obsidian-export module so the 3D
# visualizer renders the SAME nervous system you see in Obsidian.
# Founder ask 2026-05-15: "make a copy of nodes and what's in
# obsidian and put it into http://127.0.0.1:5557/ — this version
# has good spacial depth."
try:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from orion_obsidian_export import (
        KNOWN_DEVICES as _RICH_DEVICES,
        KNOWN_CHANNELS as _RICH_CHANNELS,
        KNOWN_CLIS, KNOWN_LLMS, KNOWN_PERIPHERALS, KNOWN_SYSTEMS,
        DEVICE_DETAILS, CLI_DETAILS, LLM_DETAILS, CHANNEL_DETAILS,
    )
    # Override the local stubs with the canonical Obsidian-export
    # constants so a single source of truth drives both surfaces.
    _DEFAULT_PROBES = {"command": 5555, "forge": 11434, "orions-home": 11434,
                       "outpost": 22}
    KNOWN_DEVICES = []
    for _d in _RICH_DEVICES:
        _nd = dict(_d)
        if not _nd["id"].startswith("host:"):
            _nd["id"] = f"host:{_nd['id']}"
        _nd.setdefault("probe", _DEFAULT_PROBES.get(_d["id"], 22))
        KNOWN_DEVICES.append(_nd)
    KNOWN_CHANNELS = []
    for _c in _RICH_CHANNELS:
        _nc = dict(_c)
        if not _nc["id"].startswith("chan:"):
            _nc["id"] = f"chan:{_nc['id']}"
        _h = _nc.get("host", "")
        if _h and not _h.startswith("host:"):
            _nc["host"] = "host:any" if _h == "any" else f"host:{_h}"
        KNOWN_CHANNELS.append(_nc)
    RICH_TOPOLOGY = True
except Exception as _e:
    KNOWN_CLIS = KNOWN_LLMS = KNOWN_PERIPHERALS = KNOWN_SYSTEMS = []
    DEVICE_DETAILS = CLI_DETAILS = LLM_DETAILS = CHANNEL_DETAILS = {}
    RICH_TOPOLOGY = False


def _load_graph() -> dict:
    """Return the entity as a richly-typed nervous-system graph."""
    nodes = []
    links = []
    type_counts = Counter()
    kind_counts = Counter()

    # ── DEVICES ──
    device_status = {}
    for dev in KNOWN_DEVICES:
        status = _probe_device(dev)
        device_status[dev["id"]] = status
        nodes.append({
            "id": dev["id"],
            "kind": "device",
            "type": "device",
            "label": dev["label"],
            "preview": f'{dev["label"]} — {dev["role"]} @ {dev["ip"]}',
            "status": status,
            "size": 14,
        })
        kind_counts["device"] += 1

    # mesh edges: every device pair (substrate cluster topology)
    dev_ids = [d["id"] for d in KNOWN_DEVICES]
    for i, a in enumerate(dev_ids):
        for b in dev_ids[i+1:]:
            sa, sb = device_status[a], device_status[b]
            health = "alive" if sa == "alive" and sb == "alive" else "degraded"
            links.append({"source": a, "target": b, "kind": "mesh", "status": health})

    # ── CLIs (AI tools) ──
    for c in KNOWN_CLIS:
        nodes.append({
            "id": f"cli:{c['id']}",
            "kind": "cli",
            "type": "cli",
            "label": c["label"],
            "preview": (CLI_DETAILS.get(c['id'], {}).get('what')
                        or f"{c['label']} — {c.get('vendor', '?')}"),
            "size": 11,
        })
        kind_counts["cli"] += 1
    # ── LLMs (fuel models) ──
    for m in KNOWN_LLMS:
        nodes.append({
            "id": f"llm:{m['id']}",
            "kind": "llm",
            "type": "llm",
            "label": m["label"],
            "preview": LLM_DETAILS.get(m['id'], f"{m['label']} — tier {m.get('tier','?')}"),
            "size": 8,
        })
        kind_counts["llm"] += 1
        # Link LLM to its host (device for local, CLI for frontier)
        host_id = m.get("host", "")
        if m.get("kind") == "local":
            host_node = f"host:{host_id}"
        else:
            host_node = f"cli:{host_id}"
        if any(n["id"] == host_node for n in nodes):
            links.append({"source": f"llm:{m['id']}", "target": host_node,
                          "kind": "fuels", "status": "alive"})

    # ── HARDWARE PERIPHERALS ──
    for p in KNOWN_PERIPHERALS:
        nodes.append({
            "id": f"hw:{p['id']}",
            "kind": "hardware",
            "type": "hardware",
            "label": p["label"],
            "preview": f"{p['kind']} — {p['role']}",
            "size": 8,
        })
        kind_counts["hardware"] += 1
        host_node = f"host:{p['host']}"
        if any(n["id"] == host_node for n in nodes):
            links.append({"source": f"hw:{p['id']}", "target": host_node,
                          "kind": "attached", "status": "alive"})

    # ── SYSTEMS (Plexus subsystems) ──
    for s in KNOWN_SYSTEMS:
        nodes.append({
            "id": f"sys:{s['id']}",
            "kind": "system",
            "type": "system",
            "label": s["label"],
            "preview": s["what"],
            "size": 14,
        })
        kind_counts["system"] += 1
        # Each subsystem orbits the identity (linked below)

    # ── IDENTITY (central node) ──
    nodes.append({
        "id": "identity:orion",
        "kind": "identity",
        "type": "identity",
        "label": "ORION",
        "preview": "The entity itself — small persistent pattern: memory + identity + decisions + volition + reach. The brain that travels.",
        "size": 22,
    })
    kind_counts["identity"] = 1
    # Identity links to every system
    for s in KNOWN_SYSTEMS:
        links.append({"source": f"sys:{s['id']}", "target": "identity:orion",
                      "kind": "subsystem", "status": "alive"})
    # Identity also links to every device (the entity exists on each)
    for d in KNOWN_DEVICES:
        links.append({"source": "identity:orion", "target": d["id"],
                      "kind": "incarnates", "status": "alive"})

    # ── CHANNELS ──
    for ch in KNOWN_CHANNELS:
        nodes.append({
            "id": ch["id"],
            "kind": "channel",
            "type": "channel",
            "label": ch["label"],
            "preview": f'{ch["label"]} — {ch["transport"]}',
            "host": ch["host"],
            "size": 10,
        })
        kind_counts["channel"] += 1
        if ch["host"].startswith("host:") and ch["host"] != "host:any":
            host_status = device_status.get(ch["host"], "unknown")
            links.append({
                "source": ch["id"], "target": ch["host"],
                "kind": "hosted",
                "status": "alive" if host_status == "alive" else "degraded",
            })
        elif ch["host"] == "host:any":
            # CLI can reach any device — connect to each
            for h in dev_ids:
                links.append({
                    "source": ch["id"], "target": h,
                    "kind": "hosted",
                    "status": "alive" if device_status[h] == "alive" else "degraded",
                })

    # ── SERVICES (from vitals dir on local host) ──
    local_host_id = None
    hostname = platform.node().lower()
    for d in KNOWN_DEVICES:
        if d["label"].lower() in hostname or hostname in d["label"].lower():
            local_host_id = d["id"]
            break

    if VITALS_DIR.exists() and local_host_id:
        for f in sorted(VITALS_DIR.glob("*.json")):
            svc = f.stem
            try:
                snap = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                snap = {}
            status = "alive"
            if snap.get("error_rate_per_min", 0) > 5:
                status = "degraded"
            sid = f"svc:{svc}@{local_host_id.split(':')[1]}"
            nodes.append({
                "id": sid,
                "kind": "service",
                "type": "service",
                "label": svc,
                "preview": f"{svc} service",
                "host": local_host_id,
                "size": 6,
            })
            kind_counts["service"] += 1
            links.append({"source": sid, "target": local_host_id, "kind": "service", "status": status})

    # ── MEMORIES (graph_memory.json) ──
    if GRAPH_PATH.exists():
        try:
            raw = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            return {"error": f"could not read graph: {e}", "nodes": nodes, "links": links}

        SKIP_TAGS = {"fact", "preference", "project", "identity", "task",
                     "ephemeral", "person", "skill"}
        raw_nodes = raw.get("nodes", {})
        tag_to_ids = defaultdict(list)

        for nid_str, node in raw_nodes.items():
            try:
                nid = int(nid_str)
            except Exception:
                continue
            mtype = node.get("type", "fact")
            type_counts[mtype] += 1
            content = node.get("content", "")
            preview = (content if isinstance(content, str) else str(content))[:140]
            tags = list(node.get("tags", []) or [])
            mid = f"mem:{nid}"
            nodes.append({
                "id": mid,
                "kind": "memory",
                "type": mtype,
                "label": preview.split(":")[0][:40] if preview else f"mem:{nid}",
                "preview": preview,
                "tags": tags[:8],
                "confidence": node.get("confidence", 1.0),
                "created": node.get("created", 0),
                "size": 5,
            })
            kind_counts["memory"] += 1
            for t in tags:
                tlow = (t or "").strip().lower()
                if tlow and tlow not in SKIP_TAGS:
                    tag_to_ids[tlow].append(mid)

        # tag-based edges (chronologically nearest neighbors only)
        seen_pair = set()
        for tag, ids in tag_to_ids.items():
            if len(ids) < 2:
                continue
            for i, a in enumerate(ids):
                for b in ids[i+1:i+3]:
                    pair = (min(a, b), max(a, b))
                    if pair in seen_pair:
                        continue
                    seen_pair.add(pair)
                    links.append({"source": a, "target": b, "kind": "tag", "via": tag})

    return {
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_nodes": len(nodes),
            "total_links": len(links),
            "by_kind": dict(kind_counts),
            "by_memory_type": dict(type_counts),
        },
    }


def _load_pulse() -> dict:
    pulse = {"claustrum": None, "vitals": {}, "host": platform.node()}
    try:
        if CLAUSTRUM_PATH.exists():
            pulse["claustrum"] = json.loads(CLAUSTRUM_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    if VITALS_DIR.exists():
        for f in VITALS_DIR.glob("*.json"):
            try:
                pulse["vitals"][f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
    return pulse


# ── HTTP handler ───────────────────────────────────────────

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
        try:
            body = json.dumps(data, default=str).encode("utf-8")
        except Exception as e:
            body = json.dumps({"error": f"serialize: {e}"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, name: str, ctype: str) -> None:
        path = Path(__file__).resolve().parent / name
        if not path.exists():
            self.send_error(404, name); return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[visualizer] {fmt % args}\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args(argv[1:])
    print(f"[orion-visualizer] serving on http://127.0.0.1:{args.port}")
    print(f"  graph: {GRAPH_PATH}")
    print(f"  pulse: {CLAUSTRUM_PATH} + {VITALS_DIR}")
    with socketserver.ThreadingTCPServer(("0.0.0.0", args.port), Handler) as srv:
        srv.allow_reuse_address = True
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n[orion-visualizer] bye")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
