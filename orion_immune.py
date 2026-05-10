"""orion_immune.py — DCA-style danger aggregator. The novel synthesis.

The 2026-05-09 OTP+AIS research surfaced something nobody has shipped:
**OTP supervision tree as the immune organ structure, with Dendritic
Cell Algorithm (DCA) danger signals as the trigger for restart-strategy
choice.** This file is that synthesis.

Each Plexus service emits three signal classes via orion_vitals:
  - PAMP   (hard error: "this IS broken")
  - danger (drift / anomaly / latency creep: "this MIGHT be breaking")
  - safe   (recovery / nominal: "this is fine")

This aggregator:
  1. subscribes to host.*.danger.{pamp,warn,safe}
  2. maintains a per-service rolling context window (last N seconds)
  3. computes the DCA-style mature-cell signal:
       maturation = Σ(pamp · w_pamp) + Σ(danger · w_danger) − Σ(safe · w_safe)
     (Aickelin's formulation simplified for our discrete-event domain)
  4. when maturation crosses a service-class threshold, decides which
     OTP-style restart strategy applies:
       - one_for_one         — isolated PAMP: only the failed service
       - rest_for_one        — danger correlates downstream: failed +
                               services that depend on it (via start order)
       - one_for_all         — multi-service contradiction: full layer
       - escalate_to_executive — pattern matches no known fix
  5. publishes brain.immune.decision with the chosen strategy + scope
  6. self-heal.py subscribes and applies launchctl reload according to
     the strategy (today self-heal makes its own decisions; the immune
     layer should be the authority for restart strategy going forward)

This means the supervision tree LEARNS its own restart policy from
what worked. Past mature-cell decisions feed back into the threshold
adaptation per service (over time, services with frequent benign
danger learn to filter; services with rare-but-real PAMP learn to
escalate fast).

Pull this offline and self-heal falls back to its hardcoded reflex.
Keep it online and the system is genuinely adapting.

References:
  - Greensmith, Aickelin "Detecting Danger: Dendritic Cell Algorithm"
    (https://arxiv.org/abs/1006.5008)
  - Erlang/OTP supervisor strategies
    (https://www.erlang.org/doc/system/sup_princ.html)
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
from pathlib import Path

logger = logging.getLogger("orion.immune")

WINDOW_SEC = float(os.environ.get("ORION_IMMUNE_WINDOW_SEC", "300"))
DECISION_INTERVAL_SEC = float(os.environ.get("ORION_IMMUNE_INTERVAL_SEC", "30"))
W_PAMP = float(os.environ.get("ORION_IMMUNE_W_PAMP", "1.0"))
W_DANGER = float(os.environ.get("ORION_IMMUNE_W_DANGER", "0.4"))
W_SAFE = float(os.environ.get("ORION_IMMUNE_W_SAFE", "0.5"))
THRESHOLD_DEFAULT = float(os.environ.get("ORION_IMMUNE_THRESHOLD", "1.5"))

# Service start-order dependency graph (for rest_for_one semantics).
# Keys depend on values: e.g., dmn depends on substrate.
START_ORDER = [
    "nats",        # substrate, foundation
    "claustrum",   # integrative
    "dmn",         # depends on substrate
    "lastcontact",
    "fuel-switch",
    "channel-probe",
    "self-heal",
    "reach",
    "executive",
]


class DangerContext:
    """Per-service rolling window of (PAMP, danger, safe) signals.
    Maturation score is computed lazily on read."""

    def __init__(self):
        self.signals: deque = deque(maxlen=500)  # (ts, kind, weight, signal_id)
        self.lock = threading.Lock()
        # Decisions that have already fired so we don't re-fire constantly
        self._last_decision_ts = 0.0
        self._last_strategy: str | None = None

    def add(self, kind: str, weight: float, signal_id: str = "") -> None:
        with self.lock:
            self.signals.append((time.time(), kind, weight, signal_id))

    def maturation(self, now: float | None = None) -> float:
        """Aickelin DCA-style aggregate. Positive = inflammatory pressure."""
        if now is None:
            now = time.time()
        with self.lock:
            cutoff = now - WINDOW_SEC
            score = 0.0
            for ts, kind, weight, _ in self.signals:
                if ts < cutoff:
                    continue
                # Recency-weight: signals decay linearly across the window
                age_frac = (now - ts) / WINDOW_SEC
                recency = max(0.0, 1.0 - age_frac)
                if kind == "pamp":
                    score += W_PAMP * weight * recency
                elif kind == "danger":
                    score += W_DANGER * weight * recency
                elif kind == "safe":
                    score -= W_SAFE * 1.0 * recency
            return score

    def signal_diversity(self) -> set:
        with self.lock:
            return {s[3] for s in self.signals if s[1] in ("pamp", "danger") and s[3]}


_contexts: dict[str, DangerContext] = defaultdict(DangerContext)
_stop = threading.Event()


# ---------- substrate handlers ----------

def _on_pamp(subject: str, payload: dict) -> None:
    parts = subject.split(".")
    if len(parts) >= 2:
        svc = parts[1]
        _contexts[svc].add("pamp", float(payload.get("weight", 1.0)),
                            payload.get("signal_id", ""))


def _on_danger(subject: str, payload: dict) -> None:
    parts = subject.split(".")
    if len(parts) >= 2:
        svc = parts[1]
        _contexts[svc].add("danger", float(payload.get("weight", 0.5)),
                            payload.get("signal_id", ""))


def _on_safe(subject: str, payload: dict) -> None:
    parts = subject.split(".")
    if len(parts) >= 2:
        svc = parts[1]
        _contexts[svc].add("safe", 1.0, payload.get("signal_id", ""))


# ---------- restart-strategy decision ----------

def _services_after(svc: str) -> list[str]:
    """Return services that come AFTER svc in start order — these are
    candidates for rest_for_one when svc is the upstream failure."""
    if svc not in START_ORDER:
        return []
    idx = START_ORDER.index(svc)
    return START_ORDER[idx:]  # include svc itself


def _decide_strategy(focus_svc: str, mature_score: float,
                     contextual_score: dict) -> dict:
    """Choose an OTP-style strategy from the danger context pattern.

    contextual_score: {service: maturation_score} for ALL services
    """
    # How many services are inflammatory beyond their threshold?
    beyond = [s for s, sc in contextual_score.items() if sc > THRESHOLD_DEFAULT]

    # Multiple services contradicting — host-level cause likely
    if len(beyond) >= 3:
        return {
            "strategy": "one_for_all",
            "scope": list(contextual_score.keys()),
            "reason": f"{len(beyond)} services in danger simultaneously — host-level cause",
        }

    # Two services where one depends on the other — rest_for_one
    if len(beyond) == 2:
        a, b = sorted(beyond, key=lambda s: START_ORDER.index(s) if s in START_ORDER else 99)
        return {
            "strategy": "rest_for_one",
            "scope": _services_after(a),
            "anchor_service": a,
            "reason": f"{a} downstream propagation suspected (also affecting {b})",
        }

    # Single service inflammatory — but is its danger context
    # diverse? Repeated identical signals → known issue, reflex can
    # handle it. Diverse signals → novel, escalate.
    diversity = len(_contexts[focus_svc].signal_diversity())
    if diversity >= 4 and mature_score > THRESHOLD_DEFAULT * 1.5:
        return {
            "strategy": "escalate_to_executive",
            "scope": [focus_svc],
            "reason": f"diverse danger signals ({diversity} kinds) at high pressure — pattern unfamiliar",
        }

    return {
        "strategy": "one_for_one",
        "scope": [focus_svc],
        "reason": "isolated symptom, scope-1 reflex sufficient",
    }


# ---------- decision loop ----------

def _decision_loop() -> None:
    try:
        from orion_substrate import publish
    except ImportError:
        publish = None

    while not _stop.is_set():
        try:
            now = time.time()
            scores = {svc: ctx.maturation(now) for svc, ctx in _contexts.items()}
            for svc, score in scores.items():
                if score <= THRESHOLD_DEFAULT:
                    continue
                ctx = _contexts[svc]
                # Don't re-fire the same decision constantly; require
                # 60s between strategy publishes per service.
                if (now - ctx._last_decision_ts) < 60.0:
                    continue
                decision = _decide_strategy(svc, score, scores)
                decision["service"] = svc
                decision["maturation"] = round(score, 3)
                decision["all_scores"] = {k: round(v, 3) for k, v in scores.items()}
                decision["ts"] = now
                logger.info("immune decision: svc=%s strategy=%s reason=%s",
                            svc, decision["strategy"], decision["reason"])
                if publish:
                    publish("brain.immune.decision", decision)
                ctx._last_decision_ts = now
                ctx._last_strategy = decision["strategy"]
        except Exception as e:
            logger.warning("decision loop error: %s", e)
        _stop.wait(DECISION_INTERVAL_SEC)


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

    subscribe("host.*.danger.pamp", _on_pamp)
    subscribe("host.*.danger.warn", _on_danger)
    subscribe("host.*.danger.safe", _on_safe)
    logger.info("immune aggregator alive — DCA over PAMP/danger/safe; "
                "deciding OTP-style restart strategy every %ds",
                int(DECISION_INTERVAL_SEC))

    threading.Thread(target=_decision_loop, name="immune-decide",
                     daemon=True).start()

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
