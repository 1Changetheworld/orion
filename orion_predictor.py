"""orion_predictor.py — generative predictor + surprise signal.

The v2 consciousness research demoted active inference from "third
pillar" to "prefetch / interest layer." This file is that layer.
It is NOT the spine; it is the part of the body that notices when
something is off-rhythm.

WHY THIS LAYER EXISTS
=====================

2026-05-16: three stacked silent failures all went unnoticed for 24+
hours (channel-probe crashed → reach.WARNING loop → no proactive
iMessages → brain TCC lapsed → /memorize silently 500'd). The pattern
across all of them: nothing on the substrate said "the rhythm of X
just broke." Heartbeats kept ticking from other services, so the
substrate looked alive. The cellular vitals layer reported per-service
internal health — but it couldn't observe the absence of expected
cross-service traffic.

This file builds the model of "what normal substrate rhythm looks
like" and emits brain.surprise.spike when the observed rhythm
deviates. The workspace boosts the spike. The will narrates. The
executive proposes a remedy. The metacog learns the symptom→action
pattern. Silent failures become loud — because the brain now has a
prediction it can be wrong about.

WHAT THIS LAYER DOES
====================

Two complementary signals — TEMPORAL (does the rhythm match?) and
CONTENT (does this event match what recent events looked like?). They
fire on different failure modes and are computed independently.

Temporal — per subject:
  1. Track inter-arrival time (IAT) — gap between consecutive events.
  2. Maintain rolling mean (mu) + stddev (sigma) of IAT in a window of
     last N=128 events.
  3. On each new event, compute surprise = |IAT_new - mu| / max(sigma, 0.5).
     Z-score of how off-rhythm this gap is.
  4. Accumulate per-subject cumulative surprise (with decay).
  5. When cumulative surprise crosses THRESHOLD, publish:
     brain.surprise.spike {subject, surprise, cumulative, mu, sigma, last_iat, last_seen}
  6. Reset cumulative after spike (so we don't re-fire on the same
     spike — only when a NEW deviation accumulates).
  7. Also detect ABSENCE: if a known subject hasn't been seen in
     MISSING_GRACE_MULTIPLIER × mu seconds, treat as surprise spike
     with cause=missing.

Content — per subject (this is the active-inference-in-token-space layer
from synthesis-continual-learning §C5 + frontier-self-model Signal C):
  1. Keep a rolling deque of the last N=16 payload feature-hash vectors
     (orion_hash_embed — stdlib only, no Ollama dependency).
  2. The "prediction" of the next payload is the L2-normalized mean of
     that deque.
  3. On each new event, surprise = 1 - cos(predicted, actual) ∈ [0, 1].
     0 = exactly what we expected; 1 = orthogonal to expectation.
  4. Publish brain.predictor.surprise {subject, surprise, ts} per event
     once we have enough history (≥ CONTENT_MIN_SAMPLES). Workspace
     listens to that subject directly as a continuous gain channel —
     this is the prediction-error gain modulation cortical analogue.
  5. Also push workspace.feedback at high content-surprise so the spike
     gets attention on the NEXT tick, not after the gain decays in.

WHY THIS IS NOT ACTIVE INFERENCE (per v2 research)
==================================================

Friston's free energy principle is unfalsifiable as written and falls
into the dark-room trap (a perfect-predictor agent would seek a
dark room and stop). We're not minimizing free energy and we're not
acting to reduce expected free energy. We maintain two per-subject
rolling models — rhythm and content — and emit a divergence number
when reality doesn't match. Active-inference-flavored, not the full
theory. Per the v2 verdict: "use it as a thin prefetch layer that
tells reach what's most surprising right now." The content layer
inherits the same discipline: it only LIGHTS UP attention; it never
proposes action, never gates a decision, never narrates.

WHAT IT SUBSCRIBES TO
=====================

Curated list — high-signal subjects only, to avoid surprise spam:

  - brain.health.alert           (rare; any change is signal)
  - brain.executive.proposal     (rare; rhythm matters)
  - brain.executive.outcome      (rare; gap to proposal is signal)
  - brain.intent.detected        (rare; user intent)
  - brain.will.alerted           (rare; will is acting)
  - brain.memory.stored          (medium; healthy ~1/min)
  - brain.metacog.confidence     (medium; healthy ~1/decision)
  - channel.imessage.inbound     (medium; depends on user)
  - channel.imessage.outbound    (medium; absence here = the bug we just hit)
  - channel.*.delivery_status    (medium; absence = broken pipe)
  - host.*.vitals                (medium; baseline metronome)
  - host.*.channels              (rare; channel-probe heartbeat — its
                                   absence is exactly the channel-probe-
                                   crashed silent failure)
  - workspace.current            (every tick; baseline)
  - canary.*                     (orion_canary.py heartbeats per capability)

Add subjects via the ORION_PREDICTOR_SUBJECTS env var (comma-sep) at
runtime if you want a different watch list.
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
from collections import defaultdict, deque
from typing import Optional

logger = logging.getLogger("orion.predictor")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
WINDOW = int(os.environ.get("ORION_PREDICTOR_WINDOW", "128"))
SURPRISE_THRESHOLD = float(os.environ.get("ORION_PREDICTOR_THRESHOLD", "4.0"))
CUMULATIVE_DECAY = float(os.environ.get("ORION_PREDICTOR_DECAY", "0.92"))
MIN_SAMPLES = int(os.environ.get("ORION_PREDICTOR_MIN_SAMPLES", "6"))
MISSING_GRACE_MULT = float(os.environ.get("ORION_PREDICTOR_MISSING_MULT", "3.0"))
ABSENCE_CHECK_SEC = float(os.environ.get("ORION_PREDICTOR_ABSENCE_SEC", "30"))
MIN_SIGMA = float(os.environ.get("ORION_PREDICTOR_MIN_SIGMA", "0.5"))

# Content-prediction tunables (active inference in token space).
CONTENT_WINDOW = int(os.environ.get("ORION_PREDICTOR_CONTENT_WIN", "16"))
CONTENT_MIN_SAMPLES = int(os.environ.get("ORION_PREDICTOR_CONTENT_MIN", "3"))
CONTENT_FEEDBACK_THRESHOLD = float(
    os.environ.get("ORION_PREDICTOR_CONTENT_FB", "0.65"))

DEFAULT_SUBJECTS = [
    "brain.health.alert",
    "brain.executive.proposal",
    "brain.executive.outcome",
    "brain.intent.detected",
    "brain.will.alerted",
    "brain.memory.stored",
    "brain.metacog.confidence",
    "channel.*.inbound",
    "channel.*.outbound",
    "channel.*.delivery_status",
    "host.*.vitals",
    "host.*.channels",
    "workspace.current",
    "canary.*",
]


def _subjects() -> list[str]:
    env = os.environ.get("ORION_PREDICTOR_SUBJECTS")
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    return list(DEFAULT_SUBJECTS)


# ─────────────────────────────────────────────────────────
# Rhythm model — per-subject inter-arrival stats
# ─────────────────────────────────────────────────────────

class RhythmModel:
    __slots__ = ("subject", "history", "last_ts", "cumulative", "last_spike_ts")

    def __init__(self, subject: str):
        self.subject = subject
        self.history: deque[float] = deque(maxlen=WINDOW)  # IATs in seconds
        self.last_ts: Optional[float] = None
        self.cumulative: float = 0.0
        self.last_spike_ts: float = 0.0

    @property
    def n(self) -> int:
        return len(self.history)

    @property
    def mu(self) -> float:
        if not self.history:
            return 0.0
        return sum(self.history) / len(self.history)

    @property
    def sigma(self) -> float:
        n = len(self.history)
        if n < 2:
            return MIN_SIGMA
        m = self.mu
        var = sum((x - m) ** 2 for x in self.history) / (n - 1)
        return max(math.sqrt(var), MIN_SIGMA)

    def observe(self, ts: float) -> Optional[float]:
        """Returns surprise z-score for this gap, or None if first event."""
        if self.last_ts is None:
            self.last_ts = ts
            return None
        iat = max(ts - self.last_ts, 0.001)
        self.last_ts = ts
        if self.n < MIN_SAMPLES:
            self.history.append(iat)
            return None
        # Score BEFORE adding to history (otherwise we self-anchor)
        z = abs(iat - self.mu) / self.sigma
        self.history.append(iat)
        return z

    def absence_surprise(self, now: float) -> Optional[float]:
        """If we haven't seen this subject in > MISSING_GRACE × mu, return z."""
        if self.last_ts is None or self.n < MIN_SAMPLES:
            return None
        gap = now - self.last_ts
        if gap < MISSING_GRACE_MULT * self.mu:
            return None
        z = gap / max(self.mu, MIN_SIGMA)
        return z


_models: dict[str, RhythmModel] = {}


def _model_for(subject: str) -> RhythmModel:
    if subject not in _models:
        _models[subject] = RhythmModel(subject)
    return _models[subject]


# ─────────────────────────────────────────────────────────
# Content model — per-subject rolling payload vectors.
# Surprise = 1 - cos(EMA-of-recent-payload-vectors, this-payload-vector).
# This is the active-inference-in-token-space half of the predictor.
# ─────────────────────────────────────────────────────────

class ContentModel:
    """Rolling deque of payload feature-hash vectors per subject. The
    'prediction' of the next payload is the L2-normalized mean of the
    deque; surprise is 1 - cosine to that prediction.

    Deliberately stateless beyond the deque — no model fit, no learning
    rate, no theta. Per the v2 research, the predictor LIGHTS UP
    attention; it does not learn a world model. Keeping it dumb keeps
    the dark-room problem from biting."""
    __slots__ = ("subject", "vectors")

    def __init__(self, subject: str):
        self.subject = subject
        self.vectors: deque[list[float]] = deque(maxlen=CONTENT_WINDOW)

    def observe(self, payload) -> Optional[float]:
        """Returns surprise ∈ [0, 1] for this payload, or None if not
        enough history yet. ALWAYS appends the new vector — even when
        we returned None — so the rolling window fills."""
        try:
            from orion_hash_embed import hash_embed, cosine, mean_vector
        except Exception:
            return None  # stdlib-only utility; missing == bug, not runtime fault
        new_vec = hash_embed(payload)
        if not new_vec or all(x == 0.0 for x in new_vec):
            return None  # empty payload — no signal to score
        if len(self.vectors) < CONTENT_MIN_SAMPLES:
            self.vectors.append(new_vec)
            return None
        # Score BEFORE adding to history so we don't self-anchor.
        pred = mean_vector(list(self.vectors))
        sim = cosine(pred, new_vec) if pred else 0.0
        self.vectors.append(new_vec)
        # 1 - sim ∈ [0, 2] mathematically but practically [0, 1] for
        # non-negatively-correlated content. Clamp to [0, 1] so the
        # downstream workspace gain stays bounded and interpretable.
        return max(0.0, min(1.0, 1.0 - sim))


_content_models: dict[str, ContentModel] = {}


def _content_for(subject: str) -> ContentModel:
    if subject not in _content_models:
        _content_models[subject] = ContentModel(subject)
    return _content_models[subject]


# ─────────────────────────────────────────────────────────
# Event handling
# ─────────────────────────────────────────────────────────

async def _on_event(nc, msg) -> None:
    subject = msg.subject
    now = time.time()
    # ── Content-prediction surprise (active inference in token space).
    # Computed BEFORE rhythm so a content-spike still emits even if the
    # rhythm model is in its warm-up phase.
    try:
        payload = json.loads(msg.data.decode("utf-8"))
    except Exception:
        payload = msg.data.decode("utf-8", errors="replace")[:512]
    cmodel = _content_for(subject)
    content_surprise = cmodel.observe(payload)
    if content_surprise is not None:
        await _emit_content_surprise(nc, subject, content_surprise, now)
    # ── Temporal rhythm surprise.
    model = _model_for(subject)
    z = model.observe(now)
    if z is None:
        return
    if z < 1.0:
        # Healthy rhythm — decay any accumulated surprise.
        model.cumulative *= CUMULATIVE_DECAY
        return
    model.cumulative = model.cumulative * CUMULATIVE_DECAY + z
    if model.cumulative >= SURPRISE_THRESHOLD and (now - model.last_spike_ts) > 30:
        await _emit_spike(nc, model, kind="rhythm_break", z=z)
        model.cumulative = 0.0
        model.last_spike_ts = now


async def _absence_loop(nc) -> None:
    """Periodically check for known subjects that have gone quiet
    longer than their expected rhythm would predict."""
    while True:
        await asyncio.sleep(ABSENCE_CHECK_SEC)
        now = time.time()
        for model in list(_models.values()):
            z = model.absence_surprise(now)
            if z is None:
                continue
            if (now - model.last_spike_ts) < 60:
                continue
            await _emit_spike(nc, model, kind="missing", z=z,
                              last_seen_ago=now - (model.last_ts or now))
            model.last_spike_ts = now


async def _emit_content_surprise(nc, subject: str, surprise: float,
                                 ts: float) -> None:
    """Publish brain.predictor.surprise per event so the workspace can
    use it as a continuous gain channel (prediction-error gain
    modulation). Above CONTENT_FEEDBACK_THRESHOLD we ALSO push
    workspace.feedback so the spike gets attention NEXT tick rather
    than waiting for the natural gain channel to integrate."""
    payload = {"subject": subject,
               "surprise": round(surprise, 4),
               "ts": ts}
    try:
        await nc.publish("brain.predictor.surprise",
                         json.dumps(payload).encode("utf-8"))
    except Exception as e:
        logger.debug("content-surprise publish failed: %s", e)
    if surprise >= CONTENT_FEEDBACK_THRESHOLD:
        fb = {"subject": subject, "surprise": float(surprise),
              "reason": f"predictor:content:{surprise:.2f}"}
        try:
            await nc.publish("workspace.feedback",
                             json.dumps(fb).encode("utf-8"))
        except Exception:
            pass


async def _emit_spike(nc, model: RhythmModel, kind: str, z: float,
                      last_seen_ago: Optional[float] = None) -> None:
    payload = {
        "subject": model.subject,
        "kind": kind,
        "z": round(z, 2),
        "cumulative": round(model.cumulative, 2),
        "mu_iat_sec": round(model.mu, 3),
        "sigma_iat_sec": round(model.sigma, 3),
        "n_samples": model.n,
        "ts": time.time(),
    }
    if last_seen_ago is not None:
        payload["last_seen_ago_sec"] = round(last_seen_ago, 1)

    await nc.publish("brain.surprise.spike",
                     json.dumps(payload).encode("utf-8"))

    # Also push surprise=1.0 into the workspace so the spike gets
    # attention NEXT tick, not eventually.
    fb = {"subject": model.subject, "surprise": 1.0,
          "reason": f"predictor:{kind}:{z:.1f}"}
    await nc.publish("workspace.feedback",
                     json.dumps(fb).encode("utf-8"))

    logger.warning("SURPRISE %s on %s z=%.2f cum=%.2f mu=%.2fs",
                   kind, model.subject, z, model.cumulative, model.mu)


# ─────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────

async def main() -> int:
    logging.basicConfig(
        level=os.environ.get("ORION_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        from nats.aio.client import Client as NATS  # type: ignore
    except ImportError:
        logger.error("nats-py not installed — pip install nats-py")
        return 2

    nc = NATS()

    async def err_cb(e):  logger.warning("nats err: %s", e)
    async def dis_cb():   logger.warning("nats disconnected")
    async def rec_cb():   logger.info("nats reconnected")

    await nc.connect(servers=[NATS_URL], error_cb=err_cb,
                     disconnected_cb=dis_cb, reconnected_cb=rec_cb,
                     max_reconnect_attempts=-1)
    logger.info("predictor connected to %s", NATS_URL)

    async def _cb(m):
        await _on_event(nc, m)

    subjects = _subjects()
    for s in subjects:
        await nc.subscribe(s, cb=_cb)
        logger.info("predictor watching: %s", s)

    absence = asyncio.create_task(_absence_loop(nc))
    stop = asyncio.Event()

    def _shutdown(*_):
        logger.info("predictor shutting down")
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        for sig_ in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig_, _shutdown)
            except NotImplementedError:
                pass
    except RuntimeError:
        pass

    await stop.wait()
    absence.cancel()
    await nc.drain()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
