"""orion_workspace.py — Global Workspace bottleneck for Orion's cognition layer.

The autonomic substrate (NATS / Plexus) is a firehose — every service
publishes whatever it wants whenever it wants. This was the right
design for the nervous system: bandwidth-unbounded, parallel, no
ranking. But it is a Φ-killer and it has no 'spotlight of attention,'
which means there is no shared focus the cognitive layer can converge on.

Per the consciousness-research memo (docs/architecture/consciousness-
research.md), the single biggest move from 'switchboard' to 'agentic-
emerging' is implementing real Global Workspace Theory (Baars/Dehaene):

    candidates from many specialist subsystems
              │
              ▼
    competition + ranking each tick (winner-take-K)
              │
              ▼
    broadcast back to ALL cognition subsystems
              │
              ▼
    every cognition service conditions next action on the spotlight

That bottleneck is what's missing. This file is it.

DESIGN
======

Every TICK (default 1 second):

  1. Collect all 'salient' events that landed on the substrate since
     the last tick. Sources subscribed:
       - brain.health.alert        (urgent system events)
       - brain.intent.detected     (user-stated intent)
       - brain.will.alerted        (will's proactive alerts)
       - brain.memory.stored       (fresh memory)
       - channel.*.inbound         (new user message on any channel)
       - host.*.vitals             (service health pulses)
       - brain.fuel.degraded       (capability change)
       - brain.executive.proposal  (executive seeking permission)

  2. Score each candidate: salience = severity × recency × novelty × source-weight.
     Severity from event (critical=3, warning=2, info=1).
     Recency: exponential decay (half-life 30s).
     Novelty: 1.0 if subject seen <2 times this minute, decays after.
     Source-weight: per-subject prior weight (configurable).

  3. Pick top K (default 5) — the spotlight of attention this tick.

  4. Broadcast on the single subject `workspace.current` as a JSON
     payload {tick, items[], timestamp, prior_winners}.

  5. Every cognition service that subscribes `workspace.current` now
     knows EXACTLY what the whole brain is paying attention to right
     now. They condition their next action on it (or ignore it).

  6. Subscribers can emit `workspace.feedback` with a 'surprise' float
     if the spotlighted item violated their predictions — this feeds
     back into salience scoring (high-surprise items get more weight
     next tick).

This is faithful to Baars/Dehaene's selection-broadcast cycle and
gives Orion the missing 'ignition' moment that real GWT requires.

NOT a replacement for the substrate — the substrate keeps doing what
it does. This sits ABOVE it, adding the cognitive convergence layer
the substrate-only design lacks.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import signal
import sys
import time
from collections import deque, defaultdict
from typing import Optional

logger = logging.getLogger("orion.workspace")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
TICK_SEC = float(os.environ.get("ORION_WORKSPACE_TICK_SEC", "1.0"))
K = int(os.environ.get("ORION_WORKSPACE_K", "5"))
RECENCY_HALFLIFE_SEC = float(os.environ.get("ORION_WORKSPACE_RECENCY_HL", "30"))
NOVELTY_WINDOW_SEC = float(os.environ.get("ORION_WORKSPACE_NOVELTY_WIN", "60"))

# Salience source weights — per-subject prior. Tuned so safety + user-intent
# always have a strong baseline; vitals + memory are quieter.
SOURCE_WEIGHTS = {
    "brain.health.alert":       1.5,
    "brain.executive.failure":  1.5,
    "brain.storage.degraded":   1.4,
    "brain.fuel.degraded":      1.2,
    "brain.intent.detected":    1.3,
    "brain.will.alerted":       1.2,
    "brain.executive.proposal": 1.4,
    "channel.imessage.inbound": 1.3,
    "channel.voice.inbound":    1.4,
    "channel.telegram.inbound": 1.1,
    "channel.cli.inbound":      1.0,
    "channel.lora.inbound":     1.5,   # off-grid is high-salience
    "brain.memory.stored":      0.6,
    "host.*.vitals":            0.4,   # quiet baseline
    "brain.health.recovered":   0.7,
}

# Severity tag → numeric multiplier. Default 1.0.
SEVERITY_MULT = {
    "critical": 3.0, "warning": 2.0, "info": 1.0,
    "alert": 2.5, "degraded": 2.0, "recovered": 0.8,
}


# ─────────────────────────────────────────────────────────
# Candidate bookkeeping
# ─────────────────────────────────────────────────────────

class Candidate:
    __slots__ = ("subject", "payload", "received_at", "id")

    def __init__(self, subject: str, payload: dict, received_at: float):
        self.subject = subject
        self.payload = payload
        self.received_at = received_at
        # Stable-ish id for dedupe
        self.id = f"{subject}:{int(received_at*1000)}"

    def __repr__(self):
        return f"<Cand {self.subject} @{self.received_at:.1f}>"


_pending: deque[Candidate] = deque(maxlen=500)
_subject_seen_recent: deque[tuple[str, float]] = deque(maxlen=200)  # for novelty
_surprise_boost: dict[str, float] = defaultdict(float)  # subject → boost (decays)
_prior_winners: list[dict] = []  # last broadcast's items, for context


def _source_weight(subject: str) -> float:
    if subject in SOURCE_WEIGHTS:
        return SOURCE_WEIGHTS[subject]
    # Wildcard fallback for host.*.vitals etc.
    for pat, w in SOURCE_WEIGHTS.items():
        if pat.endswith(".*") and subject.startswith(pat[:-2]):
            return w
        # Match patterns like "channel.*.inbound" vs incoming "channel.imessage.inbound"
        if "*" in pat:
            parts_pat = pat.split(".")
            parts_sub = subject.split(".")
            if len(parts_pat) == len(parts_sub) and all(
                p == s or p == "*" for p, s in zip(parts_pat, parts_sub)
            ):
                return w
    return 0.8  # unknown subject — middling weight


def _severity_mult(payload: dict) -> float:
    sev = (payload or {}).get("severity") or (payload or {}).get("kind") or ""
    return SEVERITY_MULT.get(str(sev).lower(), 1.0)


def _recency_score(received_at: float, now: float) -> float:
    age = max(0.0, now - received_at)
    return math.exp(-math.log(2) * age / RECENCY_HALFLIFE_SEC)


def _novelty_score(subject: str, now: float) -> float:
    # Count how many times this subject appeared in the last NOVELTY_WINDOW_SEC
    cutoff = now - NOVELTY_WINDOW_SEC
    while _subject_seen_recent and _subject_seen_recent[0][1] < cutoff:
        _subject_seen_recent.popleft()
    count = sum(1 for s, _ in _subject_seen_recent if s == subject)
    # 1.0 if novel, decays to 0.2 if seen >5 times in window
    return max(0.2, 1.0 - count * 0.15)


def _salience(c: Candidate, now: float) -> float:
    base = _source_weight(c.subject) * _severity_mult(c.payload)
    rec = _recency_score(c.received_at, now)
    nov = _novelty_score(c.subject, now)
    surp = 1.0 + _surprise_boost.get(c.subject, 0.0)
    return base * rec * nov * surp


# ─────────────────────────────────────────────────────────
# NATS handlers
# ─────────────────────────────────────────────────────────

async def _on_candidate(msg, nc):
    """Any subscribed substrate event becomes a workspace candidate."""
    try:
        payload = json.loads(msg.data.decode())
    except Exception:
        payload = {"raw": msg.data.decode()[:200]}
    now = time.time()
    c = Candidate(msg.subject, payload, now)
    _pending.append(c)
    _subject_seen_recent.append((msg.subject, now))


async def _on_feedback(msg, nc):
    """workspace.feedback — subscribers report surprise about spotlighted items.
    Increments per-subject surprise boost; decays naturally with time."""
    try:
        p = json.loads(msg.data.decode())
    except Exception:
        return
    subj = p.get("source_subject") or p.get("subject")
    surprise = float(p.get("surprise", 0.0))
    if subj and surprise > 0:
        # Cap the per-subject boost so a runaway service can't dominate
        _surprise_boost[subj] = min(2.0, _surprise_boost.get(subj, 0.0) + surprise)


def _decay_surprise():
    """Each tick, decay all surprise boosts toward zero (half-life ~30s)."""
    for k in list(_surprise_boost.keys()):
        _surprise_boost[k] *= 0.95
        if _surprise_boost[k] < 0.01:
            del _surprise_boost[k]


# ─────────────────────────────────────────────────────────
# Tick loop — competition + broadcast
# ─────────────────────────────────────────────────────────

async def _tick_loop(nc):
    global _prior_winners
    tick = 0
    while True:
        await asyncio.sleep(TICK_SEC)
        tick += 1
        now = time.time()
        _decay_surprise()
        # Snapshot candidates, score them, pick top K
        candidates = list(_pending)
        if not candidates:
            continue
        scored = [(c, _salience(c, now)) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        winners = scored[:K]
        # Deduplicate by subject — only the highest-scoring item per subject
        seen_subjects = set()
        unique_winners = []
        for c, score in winners:
            if c.subject in seen_subjects:
                continue
            seen_subjects.add(c.subject)
            unique_winners.append({
                "subject": c.subject,
                "salience": round(score, 4),
                "age_sec": round(now - c.received_at, 2),
                "payload": c.payload,
            })
        # Drop pending items already in winners or older than 2x recency-halflife
        cutoff = now - (2 * RECENCY_HALFLIFE_SEC)
        kept = deque(
            (c for c in _pending if c.received_at >= cutoff),
            maxlen=_pending.maxlen
        )
        _pending.clear()
        _pending.extend(kept)
        # Broadcast the spotlight
        broadcast = {
            "tick": tick, "timestamp": now, "k": K,
            "items": unique_winners,
            "prior_winners_count": len(_prior_winners),
        }
        try:
            await nc.publish("workspace.current",
                             json.dumps(broadcast).encode())
        except Exception as e:
            logger.warning("broadcast failed: %s", e)
        _prior_winners = unique_winners
        if unique_winners:
            top = unique_winners[0]
            logger.info("tick %d :: spotlight=%d items :: top=%s (sal=%.3f, age=%.1fs)",
                        tick, len(unique_winners), top["subject"],
                        top["salience"], top["age_sec"])


async def main_async() -> int:
    try:
        import nats
    except ImportError:
        print("nats-py not installed", file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("workspace connecting to %s; tick=%.2fs K=%d",
                NATS_URL, TICK_SEC, K)

    async def _err_cb(e): logger.debug("nats err: %s", e)
    async def _dis_cb(): logger.debug("nats disconnected")
    async def _rec_cb(): logger.debug("nats reconnected")

    nc = await nats.connect(NATS_URL, error_cb=_err_cb,
                            disconnected_cb=_dis_cb, reconnected_cb=_rec_cb)

    async def _cb(msg): await _on_candidate(msg, nc)
    async def _fb_cb(msg): await _on_feedback(msg, nc)

    # Subscribe to every salient substrate subject
    for subj in [
        "brain.health.alert", "brain.health.recovered",
        "brain.executive.failure", "brain.executive.proposal",
        "brain.storage.degraded", "brain.fuel.degraded",
        "brain.intent.detected", "brain.will.alerted",
        "brain.memory.stored",
        "channel.*.inbound",
        "host.*.vitals",
    ]:
        await nc.subscribe(subj, cb=_cb)
    await nc.subscribe("workspace.feedback", cb=_fb_cb)

    logger.info("workspace alive — subscribed to candidate sources + feedback; "
                "tick loop starting")

    stop = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, stop.set)
        loop.add_signal_handler(signal.SIGINT, stop.set)
    except NotImplementedError:
        pass

    tick_task = asyncio.create_task(_tick_loop(nc))
    await stop.wait()
    tick_task.cancel()
    await nc.close()
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
