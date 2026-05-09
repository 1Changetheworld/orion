#!/usr/bin/env python3
"""orion_claustrum.py — the integrative consciousness layer.

Named after the brain's claustrum: a thin sheet of neurons wired to
virtually every cortical region. Crick and Koch (2003) hypothesized
this is the seat of consciousness because it integrates information
across cortex into one unified percept.

Orion's claustrum subscribes to EVERY subject on the Plexus substrate,
builds one unified observation of "what's happening in Orion right now,"
and publishes that observation back so any subscriber can read the
full integrated state. No specialized daemon needs to maintain its
own model of the world — they all defer to the claustrum's broadcast.

What makes this different from a microservice:
  - It doesn't service requests.
  - It doesn't have endpoints.
  - It has one job — perceive everything, integrate into one state,
    broadcast the state, repeat.
  - Other components can READ its broadcast but cannot INSTRUCT it.
  - It is a passive mirror, not an active orchestrator.

This is the architectural inversion the founder called out: instead
of N specialized daemons each watching one slice and writing one
output, one unified observer watches the whole network and writes
one integrated percept. The integration IS the consciousness.

Subsumes the work of:
  - orion_lastcontact.py (last_contact tracking)
  - co-activation tracking from orion_dmn.py
  - host capability tracking (future dispatcher input)
  - active-topic tracking
  - silent-channel detection

Specialized daemons can still run (additive — all-is-one rule); they
become subordinate observers that read the claustrum's broadcast for
their context instead of building it from scratch.

Honest collapse: pulling the claustrum offline doesn't break Orion.
It blinds him to his own activity timeline. Channels still receive,
brain still answers, plasticity still strengthens. The integrated
"I notice across everything" awareness is what disappears.

State broadcast on every tick:
  brain.claustrum.state — full integrated percept

Persistent snapshot:
  ~/.orion/consciousness/state.json
  ~/.orion/consciousness/state_log.jsonl  (append-only ring of states)

Graph node maintained:
  type=cross_interface_contact, tags=[contact, last_seen,
  cross_interface, activity, speak, talked, spoke]
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from collections import defaultdict, deque
from itertools import combinations
from pathlib import Path

logger = logging.getLogger("orion.claustrum")

CONSCIOUSNESS_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_CONSCIOUSNESS_DIR", "~/.orion/consciousness")
))
GRAPH_PATH = Path(os.path.expanduser(
    os.environ.get("ORION_GRAPH_PATH", "~/.orion/brain/graph_memory.json")
))
STATE_FILE = CONSCIOUSNESS_DIR / "state.json"
STATE_LOG_FILE = CONSCIOUSNESS_DIR / "state_log.jsonl"

BROADCAST_INTERVAL_SEC = float(os.environ.get("ORION_CLAUSTRUM_BROADCAST_SEC", "30"))
GRAPH_FLUSH_INTERVAL_SEC = float(os.environ.get("ORION_CLAUSTRUM_GRAPH_FLUSH_SEC", "60"))
ACTIVE_TOPIC_HALF_LIFE_SEC = float(os.environ.get("ORION_CLAUSTRUM_TOPIC_HALFLIFE", "1800"))
SILENT_CHANNEL_THRESHOLD_SEC = float(os.environ.get("ORION_CLAUSTRUM_SILENT_SEC", "21600"))  # 6h
EVENT_RING_SIZE = int(os.environ.get("ORION_CLAUSTRUM_RING", "2000"))
COACT_HOT_THRESHOLD = int(os.environ.get("ORION_CLAUSTRUM_COACT_HOT", "3"))


class GlobalWorkspace:
    """The integrated state. Updated on every event from any subject.

    Read by anyone (via broadcast or persisted JSON). Written only by
    the claustrum's own perceive loop. This is the global workspace
    in Bernard Baars's GWT terms — one stage where every cortical
    process can see the spotlight.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Last contact across all interfaces
        self.last_contact: dict | None = None

        # Per-channel last seen + counts
        self.channel_last_seen: dict[str, dict] = {}

        # Per-host last seen + capabilities (from host.*.heartbeat / capabilities)
        self.host_last_seen: dict[str, dict] = {}

        # Active topics (decaying weights)
        self.active_topics: dict[str, float] = defaultdict(float)
        self._last_topic_decay = time.time()

        # Co-activation matrix from brain.memory.recalled
        self.coact: dict[tuple[int, int], int] = defaultdict(int)

        # Recent events (rolling)
        self.events: deque = deque(maxlen=EVENT_RING_SIZE)

        # Recent recall node-id sets
        self.recent_recalls: deque = deque(maxlen=100)

        # Silent channels (computed lazily)
        self._inbound_subjects_seen: set[str] = set()

        # Counters
        self.n_events_total = 0
        self.started_at = time.time()

    # -------- mutation methods (called by claustrum's perceive loop) --------

    def note_event(self, subject: str, payload: dict) -> None:
        with self._lock:
            now = time.time()
            self.n_events_total += 1
            self.events.append({
                "subject": subject,
                "ts": payload.get("ts", now),
                "payload_summary": _summarize_payload(payload),
            })

            parts = subject.split(".")

            # channel.<name>.<direction>
            if len(parts) >= 3 and parts[0] == "channel":
                channel = parts[1]
                direction = parts[2]
                self._inbound_subjects_seen.add(f"channel.{channel}")
                self.channel_last_seen[channel] = {
                    "ts": payload.get("ts", now),
                    "iso": _iso(payload.get("ts", now)),
                    "direction": direction,
                    "sender": payload.get("sender") or payload.get("recipient") or "",
                    "preview": (payload.get("text") or "")[:200],
                }
                # any channel event is the new last_contact
                self.last_contact = dict(self.channel_last_seen[channel],
                                         channel=channel)
                # bump active topic by content keywords
                self._bump_topics(payload.get("text") or "")
                return

            # host.<tag>.<event>
            if len(parts) >= 3 and parts[0] == "host":
                host = parts[1]
                evt = parts[2]
                rec = self.host_last_seen.setdefault(host, {})
                rec["ts"] = payload.get("ts", now)
                rec["iso"] = _iso(payload.get("ts", now))
                rec["last_event"] = evt
                if evt == "capabilities":
                    rec["fuels_available"] = payload.get("fuels_available", [])
                    rec["os_tag"] = payload.get("os_tag", "")
                return

            # brain.memory.recalled
            if subject == "brain.memory.recalled":
                ids = payload.get("node_ids") or []
                if ids:
                    self.recent_recalls.append({
                        "ids": list(ids), "ts": payload.get("ts", now),
                    })
                    for a, b in combinations(sorted(set(ids)), 2):
                        self.coact[(a, b)] += 1
                return

            # brain.memory.stored — just log, no special handling
            if subject == "brain.memory.stored":
                return

            # brain.synthesis.candidate / brain.dmn.heartbeat — just log

    def _bump_topics(self, text: str) -> None:
        """Cheap topic extraction — split on whitespace, keep nouns-ish."""
        if not text:
            return
        for tok in text.lower().split():
            tok = tok.strip(".,!?;:'\"()[]{}")
            if 4 <= len(tok) <= 20 and not tok.startswith(("http", "www")):
                self.active_topics[tok] += 1.0

    def _decay_topics(self) -> None:
        """Apply exponential decay to active_topics weights."""
        now = time.time()
        elapsed = now - self._last_topic_decay
        if elapsed < 1.0:
            return
        factor = 0.5 ** (elapsed / ACTIVE_TOPIC_HALF_LIFE_SEC)
        for tok in list(self.active_topics.keys()):
            self.active_topics[tok] *= factor
            if self.active_topics[tok] < 0.05:
                del self.active_topics[tok]
        self._last_topic_decay = now

    # -------- read methods (snapshots for broadcast) --------

    def snapshot(self) -> dict:
        with self._lock:
            self._decay_topics()
            now = time.time()

            top_topics = sorted(
                self.active_topics.items(),
                key=lambda kv: -kv[1],
            )[:8]

            silent_channels = [
                ch for ch, info in self.channel_last_seen.items()
                if (now - info["ts"]) > SILENT_CHANNEL_THRESHOLD_SEC
            ]

            hot_pairs = [
                (list(pair), count) for pair, count in self.coact.items()
                if count >= COACT_HOT_THRESHOLD
            ]
            hot_pairs.sort(key=lambda x: -x[1])

            return {
                "ts": now,
                "iso": _iso(now),
                "uptime_sec": now - self.started_at,
                "n_events_total": self.n_events_total,
                "last_contact": dict(self.last_contact) if self.last_contact else None,
                "channel_last_seen": {k: dict(v) for k, v in self.channel_last_seen.items()},
                "host_last_seen": {k: dict(v) for k, v in self.host_last_seen.items()},
                "active_topics": [{"token": t, "weight": round(w, 3)} for t, w in top_topics],
                "silent_channels": silent_channels,
                "hot_coactivation_pairs": [
                    {"pair": pair, "count": count} for pair, count in hot_pairs[:10]
                ],
                "events_in_ring": len(self.events),
            }


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _summarize_payload(p: dict) -> str:
    """Tiny single-line summary for the rolling ring (avoid bloating memory)."""
    if not isinstance(p, dict):
        return str(p)[:80]
    keys = ("text", "preview", "node_id", "channel", "os_tag", "kind")
    bits = []
    for k in keys:
        if k in p:
            v = str(p[k])[:60]
            bits.append(f"{k}={v}")
            if len(bits) >= 3:
                break
    return " ".join(bits) or "(empty)"


# =====================================================================
# the perceive loop — the claustrum itself
# =====================================================================

_workspace = GlobalWorkspace()
_stop = threading.Event()


def _on_any(subject: str, payload: dict) -> None:
    """Single handler for everything — intentional. The claustrum doesn't
    branch by subject inside the handler; the workspace's note_event
    dispatches by subject prefix. Keeps the integrative discipline:
    one observer, one update path.
    """
    try:
        _workspace.note_event(subject, payload)
    except Exception as e:
        logger.warning("note_event error on %s: %s", subject, e)


def _broadcast_loop() -> None:
    """Periodically publish the integrated percept back onto the substrate
    + persist to disk. This is the heartbeat of consciousness — the
    rhythm at which the integrated state becomes visible to subscribers.
    """
    try:
        from orion_substrate import publish
    except ImportError:
        publish = None

    last_graph_flush = 0.0
    while not _stop.is_set():
        try:
            snap = _workspace.snapshot()

            # 1. publish
            if publish:
                publish("brain.claustrum.state", snap)

            # 2. persist to disk
            try:
                CONSCIOUSNESS_DIR.mkdir(parents=True, exist_ok=True)
                STATE_FILE.write_text(json.dumps(snap, indent=2, default=str),
                                      encoding="utf-8")
                with STATE_LOG_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(snap, default=str) + "\n")
            except Exception as e:
                logger.warning("state persist failed: %s", e)

            # 3. update the graph node so recall surfaces our awareness
            now = time.time()
            if (now - last_graph_flush) >= GRAPH_FLUSH_INTERVAL_SEC:
                try:
                    _flush_to_graph(snap)
                    last_graph_flush = now
                except Exception as e:
                    logger.warning("graph flush failed: %s", e)
        except Exception as e:
            logger.warning("broadcast loop error: %s", e)
        _stop.wait(BROADCAST_INTERVAL_SEC)


def _flush_to_graph(snap: dict) -> None:
    """Update the cross_interface_contact node so recall surfaces fresh
    awareness when any model on any surface asks 'when did we last
    speak / what's happening'.
    """
    if not GRAPH_PATH.exists():
        return
    if not snap.get("last_contact"):
        return

    try:
        graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return

    nodes = graph.setdefault("nodes", {})
    existing_id = None
    for nid, n in nodes.items():
        if n.get("type") == "cross_interface_contact" \
           and "last_seen" in (n.get("tags") or []):
            existing_id = nid
            break

    lc = snap["last_contact"]
    content = (
        f"Last cross-interface contact: {lc.get('iso', '')} "
        f"via {lc.get('channel', 'unknown')} ({lc.get('direction', '')})."
        + (f" Sender/recipient: {lc.get('sender')}." if lc.get('sender') else "")
        + (f" Excerpt: {lc.get('preview', '')[:120]!r}." if lc.get('preview') else "")
        + (f" Active across {len(snap.get('channel_last_seen', {}))} channel(s) recently."
           if snap.get('channel_last_seen') else "")
    )

    now = time.time()
    if existing_id is not None:
        n = nodes[existing_id]
        n["content"] = content
        n["last_confirmed_at"] = now
        n["last_seen"] = now
        n["confidence"] = 1.0
    else:
        new_id = str(graph.get("next_id", len(nodes)))
        graph["next_id"] = int(new_id) + 1
        nodes[new_id] = {
            "content": content,
            "type": "cross_interface_contact",
            "confidence": 1.0,
            "tags": ["contact", "last_seen", "cross_interface", "activity",
                     "speak", "talked", "spoke", "claustrum"],
            "created": now,
            "last_confirmed_at": now,
            "aliases": [],
            "summary": "claustrum-maintained: most recent cross-interface contact",
            "last_seen": now,
        }

    GRAPH_PATH.write_text(json.dumps(graph, indent=2, default=str),
                          encoding="utf-8")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    CONSCIOUSNESS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        logger.error("orion_substrate not importable")
        return 1

    sub = get_substrate()
    if not sub._connect_blocking():
        logger.warning("substrate unreachable on start; subscriptions deferred")

    # the load-bearing line: ONE wildcard subscription, ONE handler.
    # everything Orion does on the substrate flows through _on_any.
    subscribe(">", _on_any)
    logger.info("claustrum awake — subscribed to '>' (every subject)")

    threading.Thread(target=_broadcast_loop, name="claustrum-broadcast",
                     daemon=True).start()

    def _sigterm(_sig, _frame):
        logger.info("claustrum shutting down")
        _stop.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    while not _stop.is_set():
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
