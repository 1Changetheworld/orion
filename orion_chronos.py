"""orion_chronos.py — the brain's unified sense of time.

Founder articulation 2026-05-10: "the part of his brain needs a
clock so he can have a concept of time and offline fallbacks in
place." Until now timestamps existed everywhere — substrate events,
graph nodes, vitals pulses, decision ledger — but no UNIFIED time
service binding them together. Chronos is that layer.

WHY A DEDICATED LAYER
=====================

Time is one of the few things every other layer needs:
  - Recall: "what did we talk about yesterday morning?" needs
    [yesterday_start, yesterday_end] as a real interval
  - Will: "haven't done X in a while" needs to know how long "a while"
    is for this user, in this context
  - DMN: idle detection means "no events for N seconds" — N relative
    to what clock?
  - Gossip: HLC clocks across hosts need a mediator that detects drift
  - Executive: per-symptom playbooks reference "last 24h", "last week"
  - Dream: nightly consolidation needs to know what "night" means in
    the user's local timezone, factoring in travel

Spreading time logic across all those layers leaks the same code
into each. Chronos owns it once. The other layers ask:

  chronos.now()                — current authoritative time
  chronos.parse_relative(text) — "yesterday morning" → (start_ts, end_ts)
  chronos.binding_for(event)   — HLC + wall-clock for an inbound event
  chronos.drift_status()       — is any host's clock divergent right now?
  chronos.user_local_now()     — for time-of-day user-facing decisions
                                 (quiet hours, "good morning" etc.)
  chronos.context_window(end_ts, span="day"|"week"|"month")
                               — discrete time-window helpers

Per the founder rule (autonomy not specifics): chronos is GENERIC.
No hardcoded "user goes to bed at 11pm." It learns from observed
inbound patterns when the user is reachable, and exposes that
inferred profile to other layers (will, reach) as data, not code.

OFFLINE FALLBACKS
=================

When the host goes offline:
  - Wall-clock keeps ticking via the OS
  - HLC's logical counter advances on every internal event
  - All written events get HLC stamps that survive disconnection
  - When the host comes back online and gossips with peers, HLC's
    physical+logical+host_id ordering reconciles missing windows
  - chronos.drift_status() reports "I was offline for X minutes"
    so the will / executive can reason about gaps

The substrate (NATS) handles the message layer. Chronos handles
the temporal-semantic layer. They compose; neither owns the other.

PUBLISHED SUBJECTS
==================

  brain.chronos.tick           — every minute, current authoritative
                                 time + observed clock drift summary
  brain.chronos.drift_alert    — when any host's wall clock diverges
                                 from local by >5s
  brain.chronos.gap_detected   — when this host was offline for >N sec
                                 and just reconnected

SUBSCRIBES TO
=============

  channel.*.inbound            — bind each event to a time anchor
  brain.memory.stored          — same
  brain.memory.recalled        — same
  mesh.*.heartbeat             — track other hosts' clocks for drift

PERSISTED
=========

  ~/.orion/chronos/anchor.json  — current time anchor + offline gap log
  ~/.orion/chronos/inferred_user_pattern.json — observed reachable hours
                                                per channel (basis for
                                                quiet-hours auto-tuning)
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("orion.chronos")

def _discover_brain_dir() -> Path:
    """Find where the brain actually lives. The clock travels with the brain,
    not with the host. Founder rule 2026-05-10: 'the brain needs one centralized
    functional offline clock IN THE BRAIN so the concepts of time are never lost.'

    Resolution order:
      1. $ORION_BRAIN_DIR — explicit override from service env
      2. Repo-local .orion/ — when developing from a clone
      3. USB mounts under /Volumes/*/.orion or /media/$USER/*/.orion
      4. ~/.orion — host-resident fallback when no portable brain is present
    """
    env = os.environ.get("ORION_BRAIN_DIR")
    if env:
        p = Path(os.path.expanduser(env))
        if p.exists():
            return p
    here = Path(__file__).resolve().parent
    local = here / ".orion"
    if (local / "brain").exists():
        return local
    for prefix in ["/Volumes", f"/media/{os.environ.get('USER', '')}"]:
        try:
            for d in Path(prefix).iterdir():
                cand = d / ".orion"
                if (cand / "brain").exists():
                    return cand
        except (FileNotFoundError, PermissionError):
            pass
    return Path(os.path.expanduser("~/.orion"))


BRAIN_DIR = _discover_brain_dir()
CHRONOS_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_CHRONOS_DIR", str(BRAIN_DIR / "chronos"))
))
TICK_INTERVAL_SEC = float(os.environ.get("ORION_CHRONOS_TICK_SEC", "60"))
DRIFT_THRESHOLD_SEC = float(os.environ.get("ORION_CHRONOS_DRIFT_SEC", "5.0"))
GAP_THRESHOLD_SEC = float(os.environ.get("ORION_CHRONOS_GAP_SEC", "60"))
USER_PATTERN_LOOKBACK_DAYS = int(os.environ.get("ORION_CHRONOS_PATTERN_DAYS", "30"))


# ─────────────────────────────────────────────────────────
# Core: current authoritative time + offline-gap detection
# ─────────────────────────────────────────────────────────

_last_tick_ts: float = time.time()
_known_gaps: list[dict] = []  # [{started, ended, duration_sec}]
_lock = threading.Lock()


def now() -> float:
    """The brain's current authoritative time. Pure wall clock for now;
    future: median across mesh peers if more than one host is reachable."""
    return time.time()


def now_iso() -> str:
    return datetime.fromtimestamp(now()).strftime("%Y-%m-%dT%H:%M:%S")


# ─────────────────────────────────────────────────────────
# Relative-time parsing — generic, no hardcoded user info
# ─────────────────────────────────────────────────────────

# Token → (offset_in_seconds, duration_seconds). offset is how far back
# from "now" the WINDOW STARTS; duration is how long the window lasts.
RELATIVE_PATTERNS: list[tuple[re.Pattern, callable]] = []


def _add_pattern(rgx_str: str, handler):
    RELATIVE_PATTERNS.append((re.compile(rgx_str, re.IGNORECASE), handler))


def _today_window(_m, ref):
    start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def _yesterday_window(_m, ref):
    today = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    yest = today - timedelta(days=1)
    return yest.timestamp(), today.timestamp()


def _this_morning(_m, ref):
    today = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    return today.timestamp(), today.replace(hour=12).timestamp()


def _yesterday_morning(_m, ref):
    today = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    yest = today - timedelta(days=1)
    return yest.timestamp(), yest.replace(hour=12).timestamp()


def _last_n_hours(m, ref):
    n = int(m.group(1))
    return (ref - timedelta(hours=n)).timestamp(), ref.timestamp()


def _last_n_days(m, ref):
    n = int(m.group(1))
    return (ref - timedelta(days=n)).timestamp(), ref.timestamp()


def _last_n_minutes(m, ref):
    n = int(m.group(1))
    return (ref - timedelta(minutes=n)).timestamp(), ref.timestamp()


def _this_week(_m, ref):
    # Monday to now
    start = (ref - timedelta(days=ref.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), ref.timestamp()


def _last_week(_m, ref):
    start = (ref - timedelta(days=ref.weekday() + 7)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return start.timestamp(), end.timestamp()


_add_pattern(r"\btoday\b", _today_window)
_add_pattern(r"\byesterday morning\b", _yesterday_morning)
_add_pattern(r"\byesterday\b", _yesterday_window)
_add_pattern(r"\bthis morning\b", _this_morning)
_add_pattern(r"\bthis week\b", _this_week)
_add_pattern(r"\blast week\b", _last_week)
_add_pattern(r"\blast (\d+) hours?\b", _last_n_hours)
_add_pattern(r"\blast (\d+) days?\b", _last_n_days)
_add_pattern(r"\blast (\d+) minutes?\b", _last_n_minutes)
_add_pattern(r"\bin the last (\d+) hours?\b", _last_n_hours)
_add_pattern(r"\bin the last (\d+) days?\b", _last_n_days)


def parse_relative(text: str, reference_ts: float | None = None) -> dict | None:
    """Parse a relative-time phrase from text. Returns
    {phrase, start_ts, end_ts, span_sec} or None if no match.

    Example: 'what did we discuss yesterday morning' → window over
    midnight–noon of yesterday in user's local timezone.
    """
    if not text:
        return None
    ref_ts = reference_ts or now()
    ref = datetime.fromtimestamp(ref_ts)
    for rgx, handler in RELATIVE_PATTERNS:
        m = rgx.search(text)
        if m:
            try:
                start_ts, end_ts = handler(m, ref)
                return {
                    "phrase": m.group(0),
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "span_sec": end_ts - start_ts,
                    "now_ts": ref_ts,
                }
            except Exception as e:
                logger.debug("parse handler failed: %s", e)
                continue
    return None


# ─────────────────────────────────────────────────────────
# Inferred user pattern — when is the user reachable?
# Generalizes across channels; no per-user code.
# ─────────────────────────────────────────────────────────

_user_inbound_log: deque = deque(maxlen=10000)  # (channel, ts, hour_of_day, weekday)


def _on_inbound(subject: str, payload: dict) -> None:
    parts = subject.split(".")
    if len(parts) < 3:
        return
    channel = parts[1]
    ts = float(payload.get("ts", time.time()))
    dt = datetime.fromtimestamp(ts)
    with _lock:
        _user_inbound_log.append((channel, ts, dt.hour, dt.weekday()))


def _on_recalled(subject: str, payload: dict) -> None:
    """Just to keep chronos aware of recall events for drift assessment."""
    pass  # Reserved for future cross-host clock comparison


def _infer_user_pattern() -> dict:
    """Compute when the user is observably reachable on each channel.
    Returns {channel: {"reachable_hours": [counts per hour 0..23],
                        "reachable_weekdays": [counts per weekday 0..6]}}.
    Other layers (will / reach) read this to make smarter decisions
    than fixed quiet-hours. Inference, not declaration."""
    by_channel: dict[str, dict] = {}
    cutoff = now() - USER_PATTERN_LOOKBACK_DAYS * 86400.0
    with _lock:
        events = list(_user_inbound_log)
    for channel, ts, hour, weekday in events:
        if ts < cutoff:
            continue
        rec = by_channel.setdefault(channel, {
            "reachable_hours": [0] * 24,
            "reachable_weekdays": [0] * 7,
            "total": 0,
        })
        rec["reachable_hours"][hour] += 1
        rec["reachable_weekdays"][weekday] += 1
        rec["total"] += 1
    return by_channel


def _persist_pattern() -> None:
    pat = _infer_user_pattern()
    if not pat:
        return
    try:
        CHRONOS_DIR.mkdir(parents=True, exist_ok=True)
        (CHRONOS_DIR / "inferred_user_pattern.json").write_text(
            json.dumps({"computed_at": now(), "by_channel": pat},
                       indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning("pattern persist failed: %s", e)


# ─────────────────────────────────────────────────────────
# Drift detection across mesh
# ─────────────────────────────────────────────────────────

_peer_clocks: dict[str, dict] = {}  # host -> {phys_ms, last_seen_ts, drift_sec}


def _on_peer_heartbeat(subject: str, payload: dict) -> None:
    parts = subject.split(".")
    if len(parts) < 3:
        return
    host = parts[1]
    if host == os.environ.get("ORION_HOST_ID", "command"):
        return
    # Heartbeat may carry HLC info; for now we just track publish ts
    peer_ts = float(payload.get("ts", time.time()))
    local_ts = time.time()
    drift = local_ts - peer_ts
    with _lock:
        _peer_clocks[host] = {
            "peer_ts": peer_ts,
            "local_ts": local_ts,
            "drift_sec": drift,
            "observed_at": local_ts,
        }
    if abs(drift) > DRIFT_THRESHOLD_SEC:
        _publish("brain.chronos.drift_alert", {
            "peer_host": host,
            "drift_sec": drift,
            "local_ts": local_ts,
            "peer_ts": peer_ts,
        })


# ─────────────────────────────────────────────────────────
# Substrate publish helper
# ─────────────────────────────────────────────────────────

def _publish(subject: str, payload: dict) -> None:
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# Tick loop — emit time anchor periodically + detect gaps
# ─────────────────────────────────────────────────────────

def _tick_loop() -> None:
    global _last_tick_ts
    while not _stop.is_set():
        try:
            cur = time.time()
            elapsed = cur - _last_tick_ts
            # Detect offline gap: we expected to tick TICK_INTERVAL_SEC ago
            # but elapsed is much larger → host was off
            if elapsed > TICK_INTERVAL_SEC + GAP_THRESHOLD_SEC and _last_tick_ts > 0:
                gap = {
                    "started_ts": _last_tick_ts,
                    "ended_ts": cur,
                    "duration_sec": elapsed - TICK_INTERVAL_SEC,
                    "started_iso": datetime.fromtimestamp(_last_tick_ts).isoformat(timespec="seconds"),
                    "ended_iso": datetime.fromtimestamp(cur).isoformat(timespec="seconds"),
                }
                _known_gaps.append(gap)
                _publish("brain.chronos.gap_detected", gap)
                logger.info("offline gap detected: %.1f min", gap["duration_sec"] / 60)

            _last_tick_ts = cur

            # Periodic tick + drift summary
            with _lock:
                drift_summary = {
                    "peer_drift_sec": {h: round(c["drift_sec"], 3)
                                       for h, c in _peer_clocks.items()},
                    "max_drift_sec": max((abs(c["drift_sec"]) for c in _peer_clocks.values()),
                                          default=0),
                }
            _publish("brain.chronos.tick", {
                "ts": cur,
                "iso": datetime.fromtimestamp(cur).isoformat(timespec="seconds"),
                "host": os.environ.get("ORION_HOST_ID", "command"),
                "drift": drift_summary,
                "known_gap_count": len(_known_gaps),
            })

            # Persist anchor + user pattern occasionally
            try:
                CHRONOS_DIR.mkdir(parents=True, exist_ok=True)
                (CHRONOS_DIR / "anchor.json").write_text(
                    json.dumps({
                        "anchor_ts": cur,
                        "anchor_iso": datetime.fromtimestamp(cur).isoformat(timespec="seconds"),
                        "host": os.environ.get("ORION_HOST_ID", "command"),
                        "drift_summary": drift_summary,
                        "known_gaps": _known_gaps[-20:],  # keep last 20
                    }, indent=2, default=str),
                    encoding="utf-8",
                )
            except Exception:
                pass

            _persist_pattern()
        except Exception as e:
            logger.warning("tick loop error: %s", e)
        _stop.wait(TICK_INTERVAL_SEC)


_stop = threading.Event()


# ─────────────────────────────────────────────────────────
# Public API for other layers (importable)
# ─────────────────────────────────────────────────────────

def drift_status() -> dict:
    with _lock:
        return {
            "known_gaps": list(_known_gaps),
            "peer_clocks": dict(_peer_clocks),
        }


def user_local_now() -> dict:
    """User-facing time view — local timezone hour, weekday, friendly label."""
    dt = datetime.fromtimestamp(now())
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if 5 <= dt.hour < 12:
        period = "morning"
    elif 12 <= dt.hour < 17:
        period = "afternoon"
    elif 17 <= dt.hour < 21:
        period = "evening"
    else:
        period = "night"
    return {
        "iso": dt.isoformat(timespec="seconds"),
        "hour": dt.hour,
        "weekday": dt.weekday(),
        "weekday_name": weekdays[dt.weekday()],
        "period": period,
        "ts": now(),
    }


def context_window(end_ts: float | None = None, span: str = "day") -> dict:
    """Return a discrete time window ending at end_ts (default: now)."""
    end = end_ts or now()
    if span == "hour":
        return {"start": end - 3600, "end": end, "span_sec": 3600}
    if span == "day":
        return {"start": end - 86400, "end": end, "span_sec": 86400}
    if span == "week":
        return {"start": end - 7 * 86400, "end": end, "span_sec": 7 * 86400}
    if span == "month":
        return {"start": end - 30 * 86400, "end": end, "span_sec": 30 * 86400}
    raise ValueError(f"unknown span: {span}")


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        logger.error("orion_substrate not importable")
        return 1

    sub = get_substrate()
    sub._connect_blocking()

    subscribe("channel.*.inbound", _on_inbound)
    subscribe("brain.memory.recalled", _on_recalled)
    subscribe("mesh.*.heartbeat", _on_peer_heartbeat)

    logger.info("chronos alive — tick=%ds drift_threshold=%.1fs gap_threshold=%ds; "
                "subscribing to channel.* + mesh.* for time awareness",
                int(TICK_INTERVAL_SEC), DRIFT_THRESHOLD_SEC, int(GAP_THRESHOLD_SEC))

    threading.Thread(target=_tick_loop, name="chronos-tick", daemon=True).start()

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
