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
_channel_failures: dict[str, list[float]] = {}  # surface → [ts of recent fails]


# ───────────────────────────────────────────────────────────────
# Failure narrator — when something breaks, tell the user clearly.
# Founder rule 2026-05-11: "this is where orion is to come in as
# the intelligence and reach out to me letting me know a
# communication vector was compromised and if he couldnt fix it
# what he tried - if he fixes it i would still like to know."
# ───────────────────────────────────────────────────────────────

def _format_failure_narration(p: dict) -> str:
    component = p.get("component", "an unknown component")
    cause = p.get("cause", "unknown")
    attempts = p.get("attempts") or []
    recommendation = p.get("recommendation")
    auto_resolved = p.get("auto_resolved", False)
    severity = p.get("severity", "info")  # info / warning / critical

    if auto_resolved:
        head = f"Recovered: {component}"
        body_intro = "Was failing, I fixed it."
    elif severity == "critical":
        head = f"Critical: {component} is down"
        body_intro = "I could not auto-recover. I need you to act."
    else:
        head = f"Heads up: {component} is degraded"
        body_intro = "I'm still trying to recover."

    lines = [head, "", body_intro]
    if cause and cause != "unknown":
        lines.append(f"Cause: {cause}")
    if attempts:
        lines.append("What I tried:")
        for a in attempts:
            mark = "[+]" if a.get("ok") else "[-]"
            descr = a.get("action") or a.get("descr") or "(no description)"
            note = f" — {a['note']}" if a.get("note") else ""
            lines.append(f"  {mark} {descr}{note}")
    if recommendation and not auto_resolved:
        lines.append(f"What you can do: {recommendation}")
    return "\n".join(lines)


def narrate_failure(component: str, cause: str, attempts: list[dict] | None = None,
                    recommendation: str | None = None, auto_resolved: bool = False,
                    severity: str = "warning") -> None:
    """Public API: any Plexus service calls this to surface a failure to
    the user via reach with full context. Bypasses no-channel silence
    by going through the same fallback chain — if iMessage is down,
    Telegram or telnyx-call gets the message.

    Example call from self-heal after trying to recover a service:

        from orion_reach import narrate_failure
        narrate_failure(
            component="iMessage fuel (claude-cli auth)",
            cause="macOS Keychain entry for Claude CLI returned no credentials",
            attempts=[
                {"action": "retry CLI call after 30s", "ok": False},
                {"action": "switch to anthropic-api fuel", "ok": False,
                 "note": "no ANTHROPIC_API_KEY in .env.secrets"},
                {"action": "fall back to ollama (local)", "ok": True,
                 "note": "but personality is different — running on qwen3:8b"},
            ],
            recommendation="run `claude /login` on COMMAND OR add ANTHROPIC_API_KEY "
                           "to /Volumes/AtlasVault/.orion/.env.secrets",
            auto_resolved=False,
            severity="critical",
        )
    """
    item = {
        "kind": "failure_narration",
        "priority": "high" if severity == "critical" else "medium",
        "ts": time.time(),
        "payload": {
            "component": component,
            "cause": cause,
            "attempts": attempts or [],
            "recommendation": recommendation,
            "auto_resolved": auto_resolved,
            "severity": severity,
        },
    }
    _q.add(item)


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
    if kind == "failure_narration":
        return _format_failure_narration(payload)
    return f"Notice: {kind}"


def _active_surfaces() -> list[str]:
    """Return surface names currently marked 'active' in the probe manifest,
    sorted by preference (sticky priority order for the fallback chain)."""
    if not _channels_manifest:
        return []
    PREF = ["imessage", "telegram", "telnyx_sms", "telnyx_call", "gmail",
            "slack", "discord", "meshtastic", "generic_http", "push"]
    actives = {s.get("surface"): s for s in _channels_manifest.get("surfaces", [])
               if s.get("status") == "active"}
    ordered = [c for c in PREF if c in actives]
    extras = [c for c in actives if c not in PREF]
    return ordered + extras


def _failed_recently(channel: str, window_sec: float = 300) -> bool:
    """True if this channel has reported a delivery failure in the recent window."""
    failures = _channel_failures.get(channel)
    if not failures:
        return False
    return any(time.time() - ts < window_sec for ts in failures[-3:])


def _choose_channel(item: dict) -> str | None:
    """Pick the best channel — with fallback when primary is failing.

    Founder rule 2026-05-11: "the brain should be adaptive enough to find
    a way to reach out to me via other communication points to inform me
    of this issue." When the channel the user last spoke from has had
    recent delivery failures, fall through to the next active channel.

    Order of consideration:
      1. Last-inbound channel (continuation), IF active AND not failing
      2. Active channels in preference order (imessage / telegram / sms /
         call / gmail / slack / discord / mesh / http / push)
      3. None — message stays queued, brain.reach.no_channel published so
         executive/dream can reason about the gap
    """
    global _recent_inbound_channel, _channels_manifest

    actives = set(_active_surfaces())

    # 1. Prefer continuation IF active AND not failing
    if _recent_inbound_channel and (time.time() - _recent_inbound_ts) < 1800:
        cont = _recent_inbound_channel
        if cont in actives and not _failed_recently(cont):
            return cont
        # Continuation channel is down or flapping — log it and fall through
        logger.info("reach: continuation channel %s unavailable (active=%s failing=%s); falling back",
                    cont, cont in actives, _failed_recently(cont))

    # 2. Fall back through active surfaces in preference order, skipping
    #    any that are currently failing
    for surface in _active_surfaces():
        if not _failed_recently(surface):
            return surface

    # 3. No active channel — surface the gap so executive can act
    logger.warning("reach: NO active channel available — message queued, will retry")
    try:
        from orion_substrate import publish
        publish("brain.reach.no_channel", {
            "ts": time.time(),
            "item_kind": item.get("kind"),
            "item_priority": item.get("priority"),
            "actives_seen": list(actives),
            "host": os.environ.get("ORION_HOST_ID", "unknown"),
        })
    except Exception:
        pass
    return None


def _on_delivery_status(subject: str, payload: dict) -> None:
    """Track per-channel delivery success/failure for the fallback chain.
    Channel adapters should publish channel.<name>.delivery_status with
    {ok: bool, error: str, ts: float} after attempting a send."""
    parts = subject.split(".")
    if len(parts) < 3:
        return
    channel = parts[1]
    ok = payload.get("ok", False)
    if not ok:
        _channel_failures.setdefault(channel, []).append(payload.get("ts", time.time()))
        # Keep only last 10 failures per channel
        _channel_failures[channel] = _channel_failures[channel][-10:]
        logger.info("reach: channel %s delivery failed: %s", channel, payload.get("error", "(?)"))


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
    # Spam-fix 2026-05-16: skip canary-class alerts. orion_autofix
    # handles known symptoms with the FIX in the message; orion_will
    # handles plain-English narration for unknown ones. Reach
    # narrating "Notice: canary_fail" was the third sender per cycle
    # causing the iMessage flood.
    if kind in ("canary_fail", "ok_to_fail", "sustained_escalation",
                "canary_recovered"):
        return
    service = (payload or {}).get("service", "")
    if isinstance(service, str) and service.startswith("canary."):
        return
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
    subscribe("channel.*.delivery_status", _on_delivery_status)
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
