"""orion_empathy.py — passive user-state observer (TIER 0).

Per docs/architecture/empathy-research.md (3,128 words, filed 2026-05-16).
The hole between Will's decision to speak and the user's capacity to
listen. Without Empathy, Orion's proactive layer is a louder iPhone
notification — well-meaning interruption with no theory of the recipient.

TIER 0 SCOPE (this file)
========================

Five inferable states, text + timing signals only — the Tier-0 set
from memo §1 that operationalizes useful (not heroic) accuracy with
zero new hardware. Camera tier layers on after orion_camera.py lands
(task #14, blocked on hardware arriving 2026-05-16).

  focus        — user heads-down, do not interrupt unless emergency
  fatigue      — soften phrasing, avoid destructive proposals
  stress       — downgrade non-emergency, don't pile on
  availability — recent two-way activity in any channel
  co_present   — multi-speaker detected (off in Tier 0; camera/mic only)

THE GATE CONTRACT
=================

evaluate(intent) → Decision in {send, downgrade, defer, reframe}.

NEVER 'cancel'. The dark-room failure mode from memo §3:

  > Caring expressed as withholding becomes the hostage situation in
  > which Orion's silence is the cause of the user's distress.

Cancellation is a user power, not Orion's. Empathy is a brake, not a
censor — every intent eventually fires; Empathy only modulates when,
how, and at what priority.

AUDIT TRAIL
===========

Every evaluate() call publishes brain.empathy.decision with the full
state vector + reason. ~/.orion/empathy/state.jsonl persists the state
timeline at 1-min resolution; daily-summarized after 30 days. The user
must always be able to ask "what does Empathy think of me right now?"
and get the literal state plus recent decisions — otherwise Empathy
becomes a hidden judge, the dynamic that made 2010s social-feed
algorithms odious (memo §8).

INTEGRATION POINTS
==================

  orion_reach._drain_loop      → empathy.evaluate(item) before publish
  orion_will (future Phase 2)  → consult availability before promoting
  orion_executive (Phase 2)    → reframe destructive proposals

Phase 1 wires reach only. Will + executive Phase 2 follows the same
pattern (one inline call, decision modulates behavior).
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orion.empathy")

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))
EMPATHY_DIR = ORION_HOME / "empathy"
STATE_PATH = EMPATHY_DIR / "state.jsonl"


# ─────────────────────────────────────────────────────────
# State vector — the live read of who the user is right now.
# Single source of truth; updated by ingest_*, read by evaluate.
# ─────────────────────────────────────────────────────────

class UserState:
    """Per-user rolling state. Five axes, each in [0, 1] except booleans.

    Updates are best-effort signal arithmetic — defensible, not
    calibrated (memo §2.3). The architecture is deliberately built so
    every signal is monotone evidence; bad calibration degrades to
    'Empathy doesn't help' not 'Empathy makes wrong calls.'
    """
    def __init__(self):
        self.focus: bool = False             # heads-down flag, 5-min window
        self.fatigue: float = 0.0            # 30-min window
        self.stress: float = 0.0             # 10-min window
        self.availability: float = 1.0       # presence-by-recent-activity
        self.co_present: bool = False        # Tier-0: always False (no mic/cam)
        self.confidence: float = 0.0         # rises with observed signal volume
        self.last_update: float = time.time()

        # Per-user baselines learned over time. Two-week warmup; until
        # then `confidence` stays low and reach/will fall back to their
        # existing heuristics. Risk in memo §7: unusual first-fortnight
        # trains the wrong model.
        self._typing_cadence_baseline: Optional[float] = None
        self._reply_latency_baseline: Optional[float] = None

        # Rolling windows for the signals we DO consume in Tier 0.
        # Bounded so the in-memory cost stays tiny.
        self._inbound_timestamps: deque = deque(maxlen=200)
        self._message_lengths: deque = deque(maxlen=200)
        self._reply_latencies: deque = deque(maxlen=200)

    def snapshot(self) -> dict:
        """Serializable read of the current state vector."""
        return {
            "focus": self.focus,
            "fatigue": round(self.fatigue, 3),
            "stress": round(self.stress, 3),
            "availability": round(self.availability, 3),
            "co_present": self.co_present,
            "confidence": round(self.confidence, 3),
            "ts": self.last_update,
        }


_state = UserState()
_state_lock = threading.Lock()


# ─────────────────────────────────────────────────────────
# Signal ingest — called by main() subscriber or by callers
# that have inputs to push (e.g. wrapping channel adapters).
# Pure functions; no NATS dependency so they're unit-testable.
# ─────────────────────────────────────────────────────────

def ingest_text(text: str, ts: Optional[float] = None) -> None:
    """A text input arrived from any channel. Updates message-length +
    sentiment-proxy signals. Tier-0 sentiment is a tiny lexicon-based
    proxy — VADER lands when the dependency budget allows; until then
    a handful of obvious markers is better than no signal at all."""
    ts = ts or time.time()
    if not text:
        return
    with _state_lock:
        _state._message_lengths.append(len(text))
        _state.last_update = ts
        # Tiny lexicon proxy — biases stress upward on a real hit, never
        # downward (memo §2.3: monotone evidence). VADER replaces this.
        lower = text.lower()
        stress_markers = ("!!!", "wtf", "stop", "fix it", "now", "urgent",
                          "broken", "fuck", "shit", "asap", "help")
        if any(m in lower for m in stress_markers):
            _state.stress = min(1.0, _state.stress + 0.15)
            _state.confidence = min(1.0, _state.confidence + 0.05)


def ingest_timing(channel: str, inter_msg_sec: float,
                  ts: Optional[float] = None) -> None:
    """A timing event from a channel — inter-message gap. Long gaps
    drop availability; very short bursts add to stress."""
    ts = ts or time.time()
    with _state_lock:
        _state._inbound_timestamps.append(ts)
        _state.last_update = ts
        if inter_msg_sec is None or inter_msg_sec < 0:
            return
        # Update availability — long gaps mean the user is away.
        # Half-life ~10 min: gap of 10min → availability cuts in half.
        decay = math.exp(-inter_msg_sec / (10 * 60))
        _state.availability = max(0.05, _state.availability * decay + 0.05)
        # Burst detection — many messages in a short window → stress signal.
        # Three messages within 15s without Orion ack is a real signal.
        if inter_msg_sec < 5.0:
            _state.stress = min(1.0, _state.stress + 0.05)
        _state.confidence = min(1.0, _state.confidence + 0.02)


def tick(now: Optional[float] = None) -> dict:
    """Periodic recompute — call from the daemon loop (~1Hz) or before
    each evaluate(). Decays state, recomputes focus, returns snapshot."""
    now = now or time.time()
    with _state_lock:
        dt = max(0.001, now - _state.last_update)
        # Stress decays fast (10-min window). Fatigue decays slowly
        # (30-min window). Focus is recomputed from activity gap.
        _state.stress = max(0.0, _state.stress * math.exp(-dt / (10 * 60)))
        _state.fatigue = max(0.0, _state.fatigue * math.exp(-dt / (30 * 60)))

        # Focus: no inbound on any channel for >= 10 min AND it's not
        # late at night (treating quiet-at-night as 'asleep' not 'focused').
        recent = [t for t in _state._inbound_timestamps if now - t < 600]
        hour = time.localtime(now).tm_hour
        is_working_hours = 8 <= hour < 22
        _state.focus = (len(recent) == 0
                        and _state.availability < 0.5
                        and is_working_hours)

        # Time-of-day → fatigue bias. Late-night activity adds fatigue.
        if hour >= 23 or hour < 6:
            _state.fatigue = min(1.0, _state.fatigue + 0.01)

        _state.last_update = now
        snap = _state.snapshot()

    _maybe_persist_state(snap, now)
    return snap


# ─────────────────────────────────────────────────────────
# evaluate() — the load-bearing gate. Reach + future will + future
# executive all call this BEFORE publishing user-facing intents.
# Never returns 'cancel'.
# ─────────────────────────────────────────────────────────

# Action constants. Imported by callers so they don't string-match.
ACTION_SEND = "send"
ACTION_DOWNGRADE = "downgrade"
ACTION_DEFER = "defer"
ACTION_REFRAME = "reframe"

# Priorities used by reach. Mirror orion_reach's ladder.
_PRIO_RANK = {"emergency": 4, "high": 3, "medium": 2, "low": 1}


def _priority_rank(p: str) -> int:
    return _PRIO_RANK.get((p or "medium").lower(), 2)


def evaluate(intent: dict, now: Optional[float] = None) -> dict:
    """Modulate a pending outbound intent against current user state.

    intent: dict with at least {priority, kind, text} — the shape
            orion_reach already uses for queue items.

    Returns:
        {
          "action": send | downgrade | defer | reframe,
          "reason": short string for audit,
          "intent": intent (possibly modified — softer text on reframe,
                    lower priority on downgrade, defer_sec on defer),
          "state": snapshot,
        }

    Decision discipline:
      1. EMERGENCY ALWAYS SENDS. Dark-room fix from memo §3 — Orion's
         silence must never be the cause of a missed safety message.
      2. FOCUS active + non-emergency → DEFER (5 min). Mark, Gudith,
         Klocke 2008: an interruption costs 23 min of recovery time;
         a 5-min wait is far cheaper than that recovery cost.
      3. HIGH STRESS + medium/low → DOWNGRADE one rung. Don't pile on.
      4. HIGH FATIGUE + non-emergency → REFRAME with softer preamble.
      5. Default → SEND unchanged.

    NEVER returns 'cancel'. Cancellation is a user power.
    """
    snap = tick(now)
    priority = (intent or {}).get("priority", "medium").lower()
    prio_rank = _priority_rank(priority)

    # Rule 1: emergency always sends. No gate. Period.
    if priority == "emergency":
        return _decide(ACTION_SEND, intent, snap, "emergency bypass")

    # Rule 2: focused + non-emergency → defer.
    if snap["focus"] and prio_rank < _PRIO_RANK["emergency"]:
        modified = dict(intent)
        modified["defer_sec"] = 5 * 60
        return _decide(ACTION_DEFER, modified, snap,
                       "user in focus; deferring 5min")

    # Rule 3: high stress + medium/low → downgrade.
    if snap["stress"] >= 0.6 and prio_rank <= _PRIO_RANK["medium"]:
        modified = dict(intent)
        modified["priority"] = "low"
        return _decide(ACTION_DOWNGRADE, modified, snap,
                       f"stress {snap['stress']:.2f} >= 0.6, downgrading")

    # Rule 4: high fatigue + non-emergency → reframe.
    if snap["fatigue"] >= 0.6 and prio_rank < _PRIO_RANK["emergency"]:
        modified = dict(intent)
        original = modified.get("text", "")
        if original and not original.startswith("When you get a moment"):
            modified["text"] = "When you get a moment — " + original
        return _decide(ACTION_REFRAME, modified, snap,
                       f"fatigue {snap['fatigue']:.2f} >= 0.6, softening")

    # Default — send unchanged.
    return _decide(ACTION_SEND, intent, snap, "no gate triggered")


def _decide(action: str, intent: dict, snap: dict, reason: str) -> dict:
    """Build the decision record + publish audit. The audit publish
    is best-effort and never blocks the caller."""
    decision = {
        "action": action,
        "reason": reason,
        "intent": intent,
        "state": snap,
    }
    try:
        from orion_substrate import publish
        publish("brain.empathy.decision", {
            "action": action,
            "reason": reason,
            "intent_kind": intent.get("kind"),
            "intent_priority": intent.get("priority"),
            "state": snap,
            "ts": time.time(),
        })
    except Exception:
        pass  # Audit must never block evaluate().
    return decision


def explain() -> dict:
    """User-facing 'what does Empathy think of me right now?' answer.
    Returns the live state vector plus rationale fields the user can
    read. Wired through an MCP tool in the follow-up patch."""
    return {
        "state": tick(),
        "thresholds": {
            "focus_window_min": 10,
            "stress_downgrade_at": 0.6,
            "fatigue_reframe_at": 0.6,
            "emergency_always_sends": True,
        },
        "tier": 0,
        "note": ("Tier-0 signals only (text + timing). Camera tier "
                 "layers on after the camera input adapter lands."),
    }


# ─────────────────────────────────────────────────────────
# State persistence — 1-min resolution, summarized after 30 days
# ─────────────────────────────────────────────────────────

_last_persist_min = 0.0


def _maybe_persist_state(snap: dict, now: float) -> None:
    """Write a state row at most once per minute. Memo §5.2: state
    persists at 1-min resolution to ~/.orion/empathy/state.jsonl with
    30-day TTL; older state is summarized to daily aggregates (mean
    fatigue, peak stress, focused minutes), raw timeseries discarded."""
    global _last_persist_min
    if now - _last_persist_min < 60:
        return
    _last_persist_min = now
    try:
        EMPATHY_DIR.mkdir(parents=True, exist_ok=True)
        with STATE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snap) + "\n")
    except Exception:
        pass  # Persistence is best-effort.


# ─────────────────────────────────────────────────────────
# Daemon main — Plexus service that subscribes to inbound channels
# and feeds the ingest functions automatically. Optional — callers
# can also push signals directly via ingest_text / ingest_timing.
# ─────────────────────────────────────────────────────────

def _on_channel_inbound(subject: str, payload: dict) -> None:
    """Channel adapters publish channel.X.inbound on every received
    user message. Empathy listens and harvests both text and timing."""
    if not isinstance(payload, dict):
        return
    text = (payload.get("text") or payload.get("message")
            or payload.get("body") or "")
    ts = float(payload.get("ts") or time.time())

    # Compute inter-message gap from the rolling window.
    with _state_lock:
        prev = (_state._inbound_timestamps[-1]
                if _state._inbound_timestamps else None)
    inter = (ts - prev) if prev else 0.0

    ingest_text(text, ts=ts)
    ingest_timing(subject.split(".")[1] if "." in subject else "unknown",
                  inter, ts=ts)


def _tick_loop(stop: threading.Event) -> None:
    while not stop.wait(1.0):
        try:
            tick()
        except Exception as e:
            logger.warning("tick error: %s", e)


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("ORION_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        logger.error("orion_substrate unavailable")
        return 1

    sub = get_substrate()
    sub._connect_blocking()
    subscribe("channel.*.inbound", _on_channel_inbound)
    # Future: subscribe brain.input.audio + brain.input.camera when
    # those publishers exist. Tier-0 doesn't need them.

    logger.info("empathy alive (tier 0 — text+timing only)")

    stop = threading.Event()
    t = threading.Thread(target=_tick_loop, args=(stop,),
                         name="empathy-tick", daemon=True)
    t.start()

    try:
        while not stop.is_set():
            time.sleep(60)
    except KeyboardInterrupt:
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
