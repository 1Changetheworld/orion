#!/usr/bin/env python3
"""orion_dmn.py — Plexus Layer 3a: Default Mode Network process.

The DMN (Default Mode Network in neuroscience) is what the brain does
when it isn't actively answering a question — pattern mining, memory
consolidation, "I noticed" generation, contradiction surfacing. In
fMRI it's measurable as a coordinated activity pattern across cortex
during rest.

Orion's DMN does the analogous work for a personal AI:
  - Subscribes to brain.memory.recalled and brain.memory.stored on
    the Plexus substrate (Layer 1).
  - Maintains a rolling co-activation matrix: which nodes are recalled
    together, how often.
  - On idle (substrate quiet >= IDLE_THRESHOLD_SEC) OR every N events,
    runs a consolidation pass:
      - Detects co-activation clusters that aren't yet linked.
      - Surfaces contested memories that haven't been resolved.
      - Notices stale projects (project nodes with old last_recalled
        but recent mentions in transcripts).
      - Publishes brain.synthesis.candidate events for each finding.
  - Channel daemons / the conversational shell can subscribe to
    brain.synthesis.candidate to inject "I noticed" prompts at the
    next user interaction.

This is the deliberate version of what Atlas did accidentally on
2026-05-08 — surfacing the contested test memories unprompted.

DESIGN PRINCIPLES:
  - Runs on COMMAND only (the always-on host).
  - All work is read-only on the brain except for synthesis cache
    updates (writes to ~/.orion/synthesis/).
  - Cooperative — yields to substrate traffic; runs at lowest priority.
  - Bounded memory (rolling window, max N=1000 events).
  - Idempotent — restartable, no required state to recover.

Subscribe topics:
  brain.memory.recalled  — co-activation tracking
  brain.memory.stored    — new-knowledge tracking
  channel.*.inbound      — passive channel awareness
  channel.*.outbound

Publish topics:
  brain.synthesis.candidate — "I noticed" candidate, payload:
      {kind, scope, evidence: [...], priority, ts}
  brain.dmn.heartbeat       — proves DMN is alive, every 60s
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

logger = logging.getLogger("orion.dmn")

# Tunable via env. Defaults are conservative for COMMAND.
IDLE_THRESHOLD_SEC = float(os.environ.get("ORION_DMN_IDLE_SEC", "300"))   # 5 min
EVENT_WINDOW = int(os.environ.get("ORION_DMN_WINDOW", "1000"))            # rolling
MIN_COACTIVATION = int(os.environ.get("ORION_DMN_MIN_COACT", "3"))        # pair seen >=N times
HEARTBEAT_SEC = float(os.environ.get("ORION_DMN_HEARTBEAT_SEC", "60"))
SYNTH_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_SYNTH_DIR", "~/.orion/synthesis")
))


class DMNProcess:
    """Background-mode pattern miner over the Plexus substrate.

    Stateless across restarts (rolling window starts fresh on boot),
    by design — DMN is a *mode of activity*, not a persistent record.
    Persistent insights live in the brain (graph_memory.json) via
    synthesis cache files; the rolling window itself is ephemeral.
    """

    def __init__(self):
        self._events: deque = deque(maxlen=EVENT_WINDOW)
        self._last_event_ts: float = time.time()
        self._coact: dict[tuple[int, int], int] = defaultdict(int)
        self._reported_pairs: set[tuple[int, int]] = set()
        self._channel_recent: deque = deque(maxlen=200)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._vitals = None  # set by start()

    # ---------- lifecycle ----------

    def start(self) -> None:
        SYNTH_DIR.mkdir(parents=True, exist_ok=True)
        try:
            from orion_substrate import (
                subscribe, publish, memory_recalled_subject,
                memory_stored_subject, get_substrate,
            )
        except ImportError:
            logger.error("orion_substrate not importable; DMN cannot start")
            return

        sub = get_substrate()
        if not sub._connect_blocking():
            logger.warning("substrate unreachable; DMN starting in degraded mode "
                           "(will keep trying on next event)")

        # Per-service vitals (cellular homeostasis). DMN gets its own
        # nervous-ending so it can probe itself + recover from stuck states.
        try:
            from orion_vitals import Vitals
            self._vitals = Vitals(service_name="dmn")
            self._vitals.add_dependency_probe("substrate", lambda: bool(sub.available))
            self._vitals.add_dependency_probe("synth_dir_writable", lambda: SYNTH_DIR.exists())
            # Reflex: if no events in 30 min while DMN is supposed to be observing,
            # something's wrong with substrate routing. Try reconnect.
            def _stuck(v):
                return v.uptime_sec() > 60 and v.last_event_age_sec() > 1800
            def _try_reconnect(v):
                try:
                    get_substrate()._connect_blocking()
                    v.note_event()
                except Exception as e:
                    v.note_error(e)
            self._vitals.register_recovery("silent_30min", _stuck, _try_reconnect)
            self._vitals.start_pulse()
            logger.info("DMN vitals primitive attached")
        except Exception as e:
            logger.warning("vitals attach failed (non-fatal): %s", e)
            self._vitals = None

        subscribe(memory_recalled_subject(), self._on_recall)
        subscribe(memory_stored_subject(), self._on_store)
        subscribe("channel.*.inbound", self._on_channel)
        subscribe("channel.*.outbound", self._on_channel)
        logger.info("DMN started — subscribed to brain.memory.* and channel.*")

        # Heartbeat + idle-detection thread
        threading.Thread(target=self._heartbeat_loop, name="dmn-heartbeat",
                         daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # ---------- substrate handlers ----------

    def _on_recall(self, subject: str, payload: dict) -> None:
        if self._vitals: self._vitals.note_event()
        with self._lock:
            self._last_event_ts = time.time()
            ids = payload.get("node_ids") or []
            if not ids:
                return
            self._events.append(("recall", tuple(ids), payload.get("ts", time.time())))
            # update co-activation matrix on every pair in this recall
            for a, b in combinations(sorted(set(ids)), 2):
                self._coact[(a, b)] += 1

    def _on_store(self, subject: str, payload: dict) -> None:
        with self._lock:
            self._last_event_ts = time.time()
            self._events.append(
                ("store", payload.get("node_id"), payload.get("ts", time.time()))
            )

    def _on_channel(self, subject: str, payload: dict) -> None:
        with self._lock:
            self._last_event_ts = time.time()
            self._channel_recent.append((subject, payload, time.time()))

    # ---------- the DMN cycle ----------

    def _consolidate(self) -> list[dict]:
        """Run a consolidation pass. Returns a list of synthesis
        candidates; caller publishes them. Read-only on the brain.

        Three detectors:
          1. Co-activation clusters: pairs that recur >= MIN_COACTIVATION
             times and aren't already explicitly linked.
          2. Contested memories: brain reports any contested_with
             nodes via orion_brain_portable.GraphMemory.list_contested.
          3. Stale projects: project-type nodes whose last_recalled is
             > h_personal days old AND have appeared in recent channel
             traffic.
        """
        candidates: list[dict] = []

        # 1. Co-activation clusters not yet reported
        with self._lock:
            hot_pairs = [
                (pair, count)
                for pair, count in self._coact.items()
                if count >= MIN_COACTIVATION and pair not in self._reported_pairs
            ]
        hot_pairs.sort(key=lambda x: -x[1])
        for (a, b), count in hot_pairs[:5]:
            candidates.append({
                "kind": "co_activation_cluster",
                "scope": "graph",
                "evidence": {"node_pair": [a, b], "co_recall_count": count},
                "priority": min(1.0, count / 10.0),
                "ts": time.time(),
            })
            self._reported_pairs.add((a, b))

        # 2. Contested memories surface — read-only snapshot of the brain
        # via the on-disk JSON. Don't import GraphMemory (it would spawn
        # extra heartbeat threads); the JSON is canonical.
        try:
            brain_path = Path.home() / ".orion" / "brain" / "graph_memory.json"
            if brain_path.exists():
                snapshot = json.loads(brain_path.read_text(encoding="utf-8"))
                for nid_str, node in snapshot.get("nodes", {}).items():
                    contested = node.get("contested_with")
                    if contested:
                        sig = tuple(sorted([int(nid_str)] + sorted(contested)))
                        if sig in self._reported_pairs:
                            continue
                        candidates.append({
                            "kind": "contested_memory",
                            "scope": "graph",
                            "evidence": {
                                "node_id": int(nid_str),
                                "contested_with": contested,
                                "content_preview": node.get("content", "")[:120],
                            },
                            "priority": 0.7,
                            "ts": time.time(),
                        })
                        self._reported_pairs.add(sig)
                        if len(candidates) >= 8:
                            break
        except Exception as e:
            logger.debug("contested-memory detection skipped: %s", e)

        # 3. Channel echo — has the same topic landed on multiple
        # surfaces in the last hour? (Email + iMessage about the
        # same deadline, etc.) Cheapest version: just count distinct
        # channels in recent buffer.
        recent_by_channel = defaultdict(int)
        with self._lock:
            for subject, _, _ in self._channel_recent:
                # subject = channel.imessage.inbound -> imessage
                parts = subject.split(".")
                if len(parts) >= 2:
                    recent_by_channel[parts[1]] += 1
        if len(recent_by_channel) >= 2 and sum(recent_by_channel.values()) >= 4:
            candidates.append({
                "kind": "multi_channel_activity",
                "scope": "channels",
                "evidence": dict(recent_by_channel),
                "priority": 0.5,
                "ts": time.time(),
            })

        return candidates

    def _publish_candidates(self, candidates: list[dict]) -> None:
        if not candidates:
            return
        try:
            from orion_substrate import publish
            for c in candidates:
                publish("brain.synthesis.candidate", c)
            # Also persist to the synthesis cache so the conversational
            # shell can pick them up even if it wasn't subscribed live.
            cache = SYNTH_DIR / "dmn_candidates.jsonl"
            with cache.open("a", encoding="utf-8") as f:
                for c in candidates:
                    f.write(json.dumps(c, default=str) + "\n")
        except Exception as e:
            logger.warning("publish candidates failed: %s", e)

    # ---------- heartbeat + idle detection loop ----------

    def _heartbeat_loop(self) -> None:
        from orion_substrate import publish
        last_cycle = 0.0
        while not self._stop.is_set():
            now = time.time()
            try:
                publish("brain.dmn.heartbeat", {
                    "ts": now,
                    "events_in_window": len(self._events),
                    "coact_pairs_tracked": len(self._coact),
                    "channels_recent": len(self._channel_recent),
                })
            except Exception:
                pass

            # Fire consolidation when substrate idle long enough
            # AND we haven't run too recently. Idle = "substrate
            # quiet for IDLE_THRESHOLD_SEC".
            idle_for = now - self._last_event_ts
            since_cycle = now - last_cycle
            if idle_for >= IDLE_THRESHOLD_SEC and since_cycle >= IDLE_THRESHOLD_SEC:
                logger.info("DMN cycle: idle=%.1fs window=%d", idle_for, len(self._events))
                cands = self._consolidate()
                if cands:
                    logger.info("DMN surfaced %d candidates", len(cands))
                    self._publish_candidates(cands)
                last_cycle = now

            self._stop.wait(HEARTBEAT_SEC)


_dmn: DMNProcess | None = None


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    global _dmn
    _dmn = DMNProcess()

    def _sigterm(_sig, _frame):
        logger.info("DMN shutting down")
        if _dmn:
            _dmn.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    _dmn.start()
    # Block forever; the heartbeat thread does the work.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
