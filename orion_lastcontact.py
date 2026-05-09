#!/usr/bin/env python3
"""orion_lastcontact.py — temporal activity index for cross-interface awareness.

Subscribes to channel.*.inbound, channel.*.outbound, and brain.memory.recalled
on the Plexus substrate. Maintains:

  ~/.orion/synthesis/last_contact.json    — single canonical "what was the
                                             most recent contact and where"
  ~/.orion/synthesis/contact_log.jsonl    — append-only roll of every event
                                             (for "what did we talk about
                                             three hours ago" queries)

Also writes/updates a single graph node tagged ["contact","last_seen",
"cross_interface"] so any recall query about "when did we last speak"
surfaces it via the existing memory machinery — no special-case code in
orion_server.py needed.

Designed to run on COMMAND (the always-on host). Idempotent across
restarts; the JSONL log is the durable truth, the JSON cache is the
fast lookup, the graph node is for surface via recall.

Cross-channel = cross-interface. The brain doesn't care which surface
the user spoke through; what matters is a unified timeline.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger("orion.lastcontact")

SYNTH_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_SYNTH_DIR", "~/.orion/synthesis")
))
GRAPH_PATH = Path(os.path.expanduser(
    os.environ.get("ORION_GRAPH_PATH", "~/.orion/brain/graph_memory.json")
))

LAST_CONTACT_FILE = SYNTH_DIR / "last_contact.json"
CONTACT_LOG_FILE = SYNTH_DIR / "contact_log.jsonl"

# Tag this graph node uses so recall finds it
CONTACT_NODE_TAGS = ["contact", "last_seen", "cross_interface", "activity"]
CONTACT_NODE_TYPE = "cross_interface_contact"

# How often to refresh the graph node (avoid hammering disk)
GRAPH_FLUSH_INTERVAL_SEC = 60.0


_state_lock = threading.Lock()
_pending_event: dict | None = None
_last_graph_flush: float = 0.0


def _format_brief(payload: dict, direction: str) -> str:
    """Human-readable summary of a contact event."""
    ch = payload.get("channel", "unknown")
    sender = payload.get("sender") or payload.get("recipient") or ""
    text = (payload.get("text") or "")[:120]
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(
        payload.get("ts", time.time())
    ))
    return (
        f"[{when}] {direction} on {ch}"
        + (f" with {sender}" if sender else "")
        + (f" — {text!r}" if text else "")
    )


def _on_event(direction: str):
    def handler(subject: str, payload: dict) -> None:
        global _pending_event
        # subject is e.g. "channel.imessage.inbound"
        parts = subject.split(".")
        channel = parts[1] if len(parts) >= 3 else "unknown"
        ts = float(payload.get("ts") or time.time())
        record = {
            "channel": channel,
            "direction": direction,
            "sender": payload.get("sender") or payload.get("recipient") or "",
            "text": (payload.get("text") or "")[:500],
            "ts": ts,
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
            "brief": _format_brief(payload, direction),
        }
        with _state_lock:
            _pending_event = record
        try:
            CONTACT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with CONTACT_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
            LAST_CONTACT_FILE.write_text(
                json.dumps(record, indent=2, default=str), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("write failed: %s", e)
    return handler


def _on_recall(subject: str, payload: dict) -> None:
    """Track recall events too — they prove someone is using the brain
    via MCP from a CLI tool, even if no channel daemon was involved."""
    global _pending_event
    ts = float(payload.get("ts") or time.time())
    record = {
        "channel": "cli-mcp",
        "direction": "recall",
        "sender": "",
        "text": f"recall on {len(payload.get('node_ids', []))} node(s)",
        "ts": ts,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
        "brief": _format_brief({"channel": "cli-mcp", "ts": ts}, "recall"),
    }
    with _state_lock:
        _pending_event = record
    try:
        CONTACT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CONTACT_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        logger.warning("recall log write failed: %s", e)


def _flush_to_graph() -> None:
    """Write/update the cross-interface contact node in the graph so
    recall surfaces it. Idempotent: looks for an existing node with our
    tags and updates in place; otherwise creates one."""
    global _last_graph_flush, _pending_event
    with _state_lock:
        event = _pending_event
        _pending_event = None
    if not event:
        return
    if not GRAPH_PATH.exists():
        return

    try:
        graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("graph read failed: %s", e)
        return

    nodes = graph.setdefault("nodes", {})
    existing_id = None
    for nid, n in nodes.items():
        if (n.get("type") == CONTACT_NODE_TYPE
                and "last_seen" in (n.get("tags") or [])):
            existing_id = nid
            break

    content = (
        f"Last cross-interface contact: {event['iso']} "
        f"via {event['channel']} ({event['direction']})."
        + (f" Sender/recipient: {event['sender']}" if event['sender'] else "")
        + (f" Excerpt: {event['text'][:140]!r}" if event['text'] else "")
    )

    now = time.time()
    if existing_id is not None:
        n = nodes[existing_id]
        n["content"] = content
        n["last_confirmed_at"] = now
        n["last_seen"] = now
        n["confidence"] = 1.0
        n["recall_count"] = int(n.get("recall_count", 0))
    else:
        new_id = str(graph.get("next_id", len(nodes)))
        graph["next_id"] = int(new_id) + 1
        nodes[new_id] = {
            "content": content,
            "type": CONTACT_NODE_TYPE,
            "confidence": 1.0,
            "tags": list(CONTACT_NODE_TAGS),
            "created": now,
            "last_confirmed_at": now,
            "aliases": [],
            "summary": "tracks the most recent cross-interface contact",
            "last_seen": now,
        }

    try:
        GRAPH_PATH.write_text(
            json.dumps(graph, indent=2, default=str), encoding="utf-8"
        )
        _last_graph_flush = now
        logger.info("graph node updated: %s", content[:100])
    except Exception as e:
        logger.warning("graph write failed: %s", e)


def _flush_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            _flush_to_graph()
        except Exception as e:
            logger.warning("flush error: %s", e)
        stop.wait(GRAPH_FLUSH_INTERVAL_SEC)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    SYNTH_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from orion_substrate import subscribe, get_substrate, memory_recalled_subject
    except ImportError:
        logger.error("orion_substrate not importable — check PYTHONPATH")
        return 1

    sub = get_substrate()
    if not sub._connect_blocking():
        logger.warning("substrate unreachable on start; will retry on first event")

    subscribe("channel.*.inbound", _on_event("inbound"))
    subscribe("channel.*.outbound", _on_event("outbound"))
    subscribe(memory_recalled_subject(), _on_recall)
    logger.info("lastcontact daemon started — subscribed to channel.* + memory.recalled")

    stop = threading.Event()
    threading.Thread(target=_flush_loop, args=(stop,), name="lc-flush",
                     daemon=True).start()

    def _sigterm(_sig, _frame):
        logger.info("shutting down")
        stop.set()
        # one final flush
        try:
            _flush_to_graph()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    while not stop.is_set():
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
