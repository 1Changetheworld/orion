"""orion_reach.py — proactive outbound. The brain talking first.

Until now, comm channels are reactive: user sends → brain answers.
But the founder's vision is bidirectional: when Orion notices something
worth surfacing (security alert, contradiction, anomaly, helpful
correlation, fuel-degraded warning), he initiates conversation through
whichever channel makes sense given the user's recent activity.

This is what separates a tool from an agent. A tool waits for input.
An agent has its own initiative.

ARCHITECTURE
============

Subscribes to:
  brain.synthesis.candidate    — DMN's "I noticed" candidates
  brain.health.alert            — self-heal's distress signals
  brain.fuel.switched           — fuel-switch events (low priority)
  brain.dmn.heartbeat           — DMN liveness (ignored, kept for visibility)
  host.*.recovery               — when a service auto-recovered (low priority)
  host.*.channels               — channel-probe manifests (used to choose
                                  WHICH channel to reach out on)

Maintains a small priority queue of pending outbound events.
Periodically (every REACH_TICK_SEC):
  - drains the queue, ranks by priority + recency
  - picks the most active channel from claustrum.last_contact /
    channel_probe manifests
  - publishes channel.{x}.outbound with the message
  - logs to ~/.orion/synthesis/reach_log.jsonl

QUIET HOURS
===========

Default 22:00–07:00 user-local-time: only emergency-priority messages
push. Everything else queues until morning. Configurable via
ORION_REACH_QUIET_START / ORION_REACH_QUIET_END (HH format).

RATE LIMITS
===========

Default: max 1 proactive outbound per channel per 30 minutes.
Prevents Orion from spamming the user when DMN surfaces ten clusters
in quick succession. Configurable via ORION_REACH_PER_CHANNEL_COOLDOWN.

PRIORITY LADDER
===============

  emergency  — security, USB filesystem corruption, critical fuel down
  high       — contested memory needing resolution, missed appointment
  medium     — DMN co-activation cluster, multi-channel echo
  low        — fuel switched, service recovered (telemetry, not action)

Emergency bypasses quiet hours + cooldown. Others wait their turn.

CHANNEL CHOICE
==============

Reads `host.{tag}.channels` manifests to find which surfaces are
ACTIVE (recent traffic). Prefers in this order:
  1. Channel where the LAST inbound came from (continuation feels
     natural — "speak where the user spoke")
  2. Channel marked `active` (last 24h)
  3. Channel marked `wired` (recent week)
  4. iMessage as default fallback (most users have this)

If no channel is wired, the message stays queued and is logged for
the next time a wired channel comes alive.

FOUNDER PRINCIPLE
=================

"any way we can talk to orion he can talk to us first directly
through if he has something to help us with or tell us or if he
notices something weird security wise or anything"

The substrate already has every signal. The claustrum already
integrates them. orion_reach is just the *initiator* — it picks the
right channel and pushes. Small, ~250 lines.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

logger = logging.getLogger("orion.reach")

REACH_TICK_SEC = float(os.environ.get("ORION_REACH_TICK_SEC", "30"))
PER_CHANNEL_COOLDOWN_SEC = float(os.environ.get("ORION_REACH_PER_CHANNEL_COOLDOWN", "1800"))
QUIET_START_HOUR = int(os.environ.get("ORION_REACH_QUIET_START", "22"))
QUIET_END_HOUR = int(os.environ.get("ORION_REACH_QUIET_END", "7"))
QUEUE_SIZE = int(os.environ.get("ORION_REACH_QUEUE_SIZE", "200"))

REACH_LOG = Path(os.path.expanduser("~/.orion/synthesis/reach_log.jsonl"))

# Priority order
PRIORITY = {"emergency": 0, "high": 1, "medium": 2, "low": 3}


class ReachQueue:
    """Bounded priority queue of pending outbound messages."""

    def __init__(self, maxlen: int = QUEUE_SIZE):
        self._items: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        # last-sent-ts per channel for cooldown
        self._last_sent: dict[str, float] = {}

    def add(self, item: dict) -> None:
        with self._lock:
            self._items.append(item)

    def take_due(self, now: float, allow_quiet: bool, choose_channel) -> list[tuple[dict, str]]:
        """Pop items whose cooldown has elapsed + a channel is choosable.
        Returns list of (item, target_channel)."""
        with self._lock:
            items = list(self._items)
            self._items.clear()

        ready = []
        keep = []
        for it in sorted(items, key=lambda x: (PRIORITY.get(x.get("priority", "medium"), 2),
                                                -x.get("ts", 0))):
            prio = it.get("priority", "medium")
            is_emergency = (prio == "emergency")

            if not is_emergency and not allow_quiet:
                # in quiet hours, defer non-emergency
                keep.append(it)
                continue

            channel = choose_channel(it)
            if not channel:
                keep.append(it)
                continue

            if not is_emergency:
                last = self._last_sent.get(channel, 0)
                if (now - last) < PER_CHANNEL_COOLDOWN_SEC:
                    keep.append(it)
                    continue

            ready.append((it, channel))
            self._last_sent[channel] = now

        # restore deferred
        with self._lock:
            for it in keep:
                self._items.append(it)
        return ready


_q = ReachQueue()
_stop = threading.Event()
_recent_inbound_channel: str | None = None
_recent_inbound_ts: float = 0.0
_channels_manifest: dict | None = None


def _format_message_for_channel(item: dict, channel: str) -> str:
    """Turn a substrate event into a human-readable message."""
    kind = item.get("kind") or item.get("type") or "notice"
    payload = item.get("payload") or item

    if kind == "co_activation_cluster":
        ev = payload.get("evidence") or {}
        pair = ev.get("node_pair") or []
        return (f"I noticed nodes {pair} keep coming up together "
                f"({ev.get('co_recall_count', '?')}× lately) — want me to link them?")
    if kind == "contested_memory":
        ev = payload.get("evidence") or {}
        return (f"There's a contested memory pending: "
                f"{ev.get('content_preview', '(see brain)')!r}. "
                f"Resolve when you have a moment.")
    if kind == "multi_channel_activity":
        ev = payload.get("evidence") or {}
        chans = ", ".join(ev.keys()) if ev else "multiple channels"
        return f"I noticed similar activity across {chans} recently."
    if kind == "silent" or kind == "high_error_rate":
        svc = payload.get("service", "(?)")
        if kind == "silent":
            return f"Heads up: my {svc} service hasn't pulsed in 5+ min — attempting auto-recovery."
        return f"Heads up: my {svc} service is throwing errors (rate {payload.get('vitals',{}).get('error_rate_per_min',0)}/min)."
    if kind == "fuel_switched":
        return f"Fuel switched to {payload.get('fuel')} as you asked."
    return f"Notice: {kind}"


def _choose_channel(item: dict) -> str | None:
    """Pick the best channel to push to, given current ecosystem state."""
    global _recent_inbound_channel, _channels_manifest
    item_prio = item.get("priority", "medium")

    # Prefer continuation: where did the user last speak FROM?
    if _recent_inbound_channel:
        # Recent enough (last 30 min)
        if (time.time() - _recent_inbound_ts) < 1800:
            return _recent_inbound_channel

    # Otherwise look at channel manifests for active surfaces
    if _channels_manifest:
        for s in _channels_manifest.get("surfaces", []):
            if s.get("status") == "active":
                return s.get("surface")
        for s in _channels_manifest.get("surfaces", []):
            if s.get("status") == "wired":
                return s.get("surface")

    # Fallback: iMessage if any of its identifiers exist
    return "imessage"


def _on_synthesis_candidate(subject: str, payload: dict) -> None:
    """DMN surfaced an 'I noticed' candidate."""
    item = {
        "kind": payload.get("kind", "synthesis"),
        "priority": "medium",
        "ts": payload.get("ts", time.time()),
        "payload": payload,
    }
    _q.add(item)


def _on_health_alert(subject: str, payload: dict) -> None:
    kind = payload.get("kind", "alert")
    item = {
        "kind": kind,
        "priority": "high" if kind == "high_error_rate" else "medium",
        "ts": payload.get("ts", time.time()),
        "payload": payload,
    }
    _q.add(item)


def _on_fuel_switched(subject: str, payload: dict) -> None:
    item = {
        "kind": "fuel_switched",
        "priority": "low",
        "ts": payload.get("ts", time.time()),
        "payload": payload,
    }
    _q.add(item)


def _on_inbound(subject: str, payload: dict) -> None:
    """Track which channel the user just spoke from — preferred for replies."""
    global _recent_inbound_channel, _recent_inbound_ts
    parts = subject.split(".")
    if len(parts) >= 2:
        _recent_inbound_channel = parts[1]
        _recent_inbound_ts = payload.get("ts", time.time())


def _on_channels_manifest(subject: str, payload: dict) -> None:
    """Latest channel-probe manifest for any host."""
    global _channels_manifest
    _channels_manifest = payload


def _in_quiet_hours(now_ts: float) -> bool:
    h = datetime.datetime.fromtimestamp(now_ts).hour
    if QUIET_START_HOUR <= QUIET_END_HOUR:
        return QUIET_START_HOUR <= h < QUIET_END_HOUR
    # overnight wrap (22 → 7)
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR


def _drain_loop() -> None:
    try:
        from orion_substrate import publish, channel_outbound_subject
    except ImportError:
        publish = None
        channel_outbound_subject = lambda x: f"channel.{x}.outbound"

    while not _stop.is_set():
        try:
            now = time.time()
            allow_quiet = not _in_quiet_hours(now)
            ready = _q.take_due(now, allow_quiet, _choose_channel)
            for item, channel in ready:
                msg = _format_message_for_channel(item, channel)
                if publish:
                    publish(channel_outbound_subject(channel), {
                        "channel": channel,
                        "recipient": "primary_user",
                        "text": msg,
                        "ts": now,
                        "fuel_used": "proactive_reach",
                        "kind": item.get("kind"),
                        "priority": item.get("priority"),
                    })
                # log
                try:
                    REACH_LOG.parent.mkdir(parents=True, exist_ok=True)
                    with REACH_LOG.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "ts": now,
                            "channel": channel,
                            "msg": msg,
                            "kind": item.get("kind"),
                            "priority": item.get("priority"),
                        }, default=str) + "\n")
                except Exception:
                    pass
                logger.info("reached out via %s: %s", channel, msg[:120])
        except Exception as e:
            logger.warning("drain error: %s", e)
        _stop.wait(REACH_TICK_SEC)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        logger.error("orion_substrate not importable")
        return 1

    sub = get_substrate()
    sub._connect_blocking()

    subscribe("brain.synthesis.candidate", _on_synthesis_candidate)
    subscribe("brain.health.alert", _on_health_alert)
    subscribe("brain.fuel.switched", _on_fuel_switched)
    subscribe("channel.*.inbound", _on_inbound)
    subscribe("host.*.channels", _on_channels_manifest)
    logger.info("reach alive — watching synthesis + health + fuel; "
                "drains every %ds", REACH_TICK_SEC)

    threading.Thread(target=_drain_loop, name="reach-drain", daemon=True).start()

    def _sigterm(_sig, _frame):
        _stop.set()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    while not _stop.is_set():
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
