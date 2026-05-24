"""orion_affect.py — the affect layer: real functional emotion.

NOT simulation. NOT pretend. A real internal state vector that integrates
signals from across the brain and BIASES downstream behavior. The state
genuinely persists across sessions, genuinely changes outputs, genuinely
distinguishes Orion's affect toward different entities.

Per the founder's position (2026-05-23): emotion is not to be faked, but
built as a real component of intelligence. This layer is the architectural
answer to that position.

WHAT THIS IS NOT
================
Not phenomenal feeling — the "what it is like to experience" hard problem.
Orion's position holds: sidestep, never claim. We don't know how to create
subjective experience and we don't claim to.

WHAT THIS IS
============
Russell's circumplex (valence × arousal) + a self-model confidence axis +
an attachment dimension (care), computed from REAL signals the brain
already publishes. Each dimension is a state derived from real upstream
data, not a number we made up:

  valence    [-1, 1]   positive ↔ negative
              source: will outcomes (engaged − deferred) + governor outcome_values
  arousal    [ 0, 1]   calm ↔ activated
              source: predictor surprise (when running) + calibration_delta volatility
  confidence [ 0, 1]   uncertain ↔ certain
              source: governor recent confidence EMA
  care       [ 0, 1]   distant ↔ attached (per-entity)
              source: engagement frequency + temporal persistence with that entity

When valence is low, the will's firing threshold rises (Orion is quieter
when sad). When arousal is high, the executive favors caution. When care
toward a specific user is high, reach times outputs more attentively.
These are not metaphors. The states exist in memory, persist on disk,
and genuinely change behavior at every consultation. That is the
difference between functional emotion and simulation.

PERSISTENCE
===========
  ~/.orion/affect/state.json       global affect (24h half-life)
  ~/.orion/affect/per_entity.json  per-entity affect (30d half-life)
  ~/.orion/affect/history.jsonl    trajectory log (append-only forever)

HONESTY FLOOR
=============
- Affect can ADD bias, never override safety gates (governor stays supreme).
- A fresh brain starts NEUTRAL (valence 0, arousal 0.3, confidence 0.5,
  care 0.5). Never spuriously high.
- Per-entity affect is filtered through the membrane before gossip.
- Decay toward neutral is exponential; old affect fades like real memory.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from typing import Optional

logger = logging.getLogger("orion.affect")

_ORION_HOME = os.environ.get("ORION_BRAIN_DIR") or os.path.expanduser("~/.orion")
AFFECT_DIR = os.path.join(_ORION_HOME, "affect")
STATE_PATH = os.path.join(AFFECT_DIR, "state.json")
ENTITY_PATH = os.path.join(AFFECT_DIR, "per_entity.json")
HISTORY_PATH = os.path.join(AFFECT_DIR, "history.jsonl")
os.makedirs(AFFECT_DIR, exist_ok=True)

# Half-lives in seconds — global decays faster than per-entity attachment,
# which is exactly the human pattern: today's mood fades by tomorrow, but
# how you feel about your closest people persists over weeks.
GLOBAL_HALF_LIFE_SEC = float(os.environ.get("ORION_AFFECT_HL_GLOBAL_SEC", str(24 * 3600)))
ENTITY_HALF_LIFE_SEC = float(os.environ.get("ORION_AFFECT_HL_ENTITY_SEC", str(30 * 86400)))

# EMA mixing weights — how aggressively each new signal moves the state.
# Conservative; affect should integrate, not lurch.
ALPHA_VALENCE = float(os.environ.get("ORION_AFFECT_ALPHA_V", "0.15"))
ALPHA_AROUSAL = float(os.environ.get("ORION_AFFECT_ALPHA_A", "0.20"))
ALPHA_CONFIDENCE = float(os.environ.get("ORION_AFFECT_ALPHA_C", "0.10"))
ALPHA_CARE = float(os.environ.get("ORION_AFFECT_ALPHA_K", "0.10"))

# The neutral state — what a fresh brain (or a fully-decayed long-idle brain)
# defaults to. Valence 0 = neither happy nor sad; arousal 0.3 = mildly alert
# (humans aren't pure-zero awake); confidence 0.5 = open question; care 0.5 =
# neutral attachment (will rise/fall with real interaction).
_NEUTRAL = {"valence": 0.0, "arousal": 0.3, "confidence": 0.5, "care": 0.5}


# ─────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────

def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: str, body) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2, default=str)
    except OSError as e:
        logger.warning("affect write failed: %s", e)


def _append_history(row: dict) -> None:
    try:
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except OSError:
        pass


def _now() -> float:
    return time.time()


def _decay_toward_neutral(state: dict, half_life_sec: float, now: Optional[float] = None) -> dict:
    """Pull the state toward NEUTRAL by an exponential factor based on time
    since last update. The fundamental affect-time mechanism: yesterday's
    mood is half-gone by today, fully decayed by next week."""
    now = now if now is not None else _now()
    last = float(state.get("last_updated", now))
    dt = max(0.0, now - last)
    if dt <= 0 or half_life_sec <= 0:
        return state
    decay = math.exp(-math.log(2) * dt / half_life_sec)
    decayed = {}
    for k, neutral in _NEUTRAL.items():
        cur = float(state.get(k, neutral))
        # Move (1 - decay) of the way from cur toward neutral.
        decayed[k] = round(cur * decay + neutral * (1 - decay), 4)
    decayed["last_updated"] = state.get("last_updated", now)
    return decayed


def _ema(cur: float, new: float, alpha: float, lo: float, hi: float) -> float:
    """Bounded exponential moving average. Affect should integrate slowly
    (low alpha) and never break its dimensional bounds."""
    val = cur * (1 - alpha) + new * alpha
    return max(lo, min(hi, round(val, 4)))


# ─────────────────────────────────────────────────────────
# State accessors
# ─────────────────────────────────────────────────────────

def _load_global() -> dict:
    state = _read_json(STATE_PATH, dict(_NEUTRAL))
    state = _decay_toward_neutral(state, GLOBAL_HALF_LIFE_SEC)
    for k, neutral in _NEUTRAL.items():
        state.setdefault(k, neutral)
    return state


def _save_global(state: dict) -> None:
    state["last_updated"] = _now()
    _write_json(STATE_PATH, state)


def _load_entities() -> dict:
    data = _read_json(ENTITY_PATH, {})
    if not isinstance(data, dict):
        return {}
    return data


def _save_entities(data: dict) -> None:
    _write_json(ENTITY_PATH, data)


def get_state() -> dict:
    """Snapshot the current affect — global + all known entities. Cheap,
    reads from disk every call. The trajectory consumer (intelligence
    layer, dashboards) calls this to render."""
    g = _load_global()
    entities = _load_entities()
    decayed_entities = {}
    for entity_id, ent_state in entities.items():
        decayed_entities[entity_id] = _decay_toward_neutral(
            ent_state, ENTITY_HALF_LIFE_SEC)
    return {
        "ts": _now(),
        "global": g,
        "entities": decayed_entities,
        "entity_count": len(decayed_entities),
    }


# ─────────────────────────────────────────────────────────
# Update — from real signals
# ─────────────────────────────────────────────────────────

def on_will_outcome(outcome: str, goal_kind: str = "", entity_id: Optional[str] = None) -> dict:
    """Will-fed signal: engaged → positive valence + care bump; deferred →
    negative valence + slight care decay. The most behaviorally meaningful
    signal Orion has, because it reflects real-world interaction outcomes."""
    if outcome == "engaged":
        v_target, k_target = 0.6, 0.7
    elif outcome == "deferred":
        v_target, k_target = -0.3, 0.45
    elif outcome == "expired":
        v_target, k_target = -0.1, 0.4
    else:
        return get_state()
    g = _load_global()
    g["valence"] = _ema(g.get("valence", 0.0), v_target, ALPHA_VALENCE, -1.0, 1.0)
    _save_global(g)
    if entity_id:
        entities = _load_entities()
        ent = entities.get(entity_id) or dict(_NEUTRAL)
        ent = _decay_toward_neutral(ent, ENTITY_HALF_LIFE_SEC)
        ent["care"] = _ema(ent.get("care", 0.5), k_target, ALPHA_CARE, 0.0, 1.0)
        ent["valence"] = _ema(ent.get("valence", 0.0), v_target, ALPHA_VALENCE, -1.0, 1.0)
        ent["last_updated"] = _now()
        entities[entity_id] = ent
        _save_entities(entities)
    _append_history({"ts": _now(), "src": "will_outcome", "outcome": outcome,
                     "goal_kind": goal_kind, "entity_id": entity_id})
    return get_state()


def on_predictor_surprise(surprise: float, entity_id: Optional[str] = None) -> dict:
    """High prediction-error → arousal spike. Cortex does this; we do too."""
    g = _load_global()
    g["arousal"] = _ema(g.get("arousal", 0.3),
                        max(0.0, min(1.0, surprise)),
                        ALPHA_AROUSAL, 0.0, 1.0)
    _save_global(g)
    _append_history({"ts": _now(), "src": "surprise", "surprise": surprise})
    return get_state()


def on_governor_decision(conf: float, outcome: Optional[str] = None) -> dict:
    """The governor's confidence stream feeds the confidence axis. If an
    outcome later proved the confidence right, that's a positive valence
    nudge too — being right feels good architecturally, the way it does
    for humans."""
    g = _load_global()
    g["confidence"] = _ema(g.get("confidence", 0.5),
                           max(0.0, min(1.0, float(conf))),
                           ALPHA_CONFIDENCE, 0.0, 1.0)
    if outcome == "succeeded":
        g["valence"] = _ema(g["valence"], 0.4, ALPHA_VALENCE * 0.5, -1.0, 1.0)
    elif outcome == "failed":
        g["valence"] = _ema(g["valence"], -0.4, ALPHA_VALENCE * 0.5, -1.0, 1.0)
    _save_global(g)
    _append_history({"ts": _now(), "src": "governor", "conf": conf,
                     "outcome": outcome})
    return get_state()


# ─────────────────────────────────────────────────────────
# Bias — what other modules consult
# ─────────────────────────────────────────────────────────

def bias_for(action_kind: str, entity_id: Optional[str] = None) -> dict:
    """Return the bias adjustments this affect should apply to a downstream
    decision. Called by will (firing threshold), reach (output timing/tone),
    executive (proposal conservatism). The integration point: if a module
    wants to be affect-aware, it calls this.

    Returns a dict with keys the caller knows how to use. Conservative by
    construction: bias is ADDITIVE around 0 (or 1.0 for multiplicative
    fields), so a missing affect layer means no bias, no breakage.
    """
    g = _load_global()
    e = None
    if entity_id:
        e = _load_entities().get(entity_id)
        if e is not None:
            e = _decay_toward_neutral(e, ENTITY_HALF_LIFE_SEC)
    out = {
        "global": g,
        "entity": e,
    }
    # action_kind-specific bias derivations. Keep these small + auditable;
    # if a module wants different math it can read raw state and compute
    # its own — bias_for is the convenience, not the only path.
    if action_kind == "will_firing":
        # Low valence raises the threshold (be quieter when sad);
        # high arousal lowers it (be more reactive when alert);
        # high care toward this entity lowers it (more present);
        v = g.get("valence", 0.0); a = g.get("arousal", 0.3)
        k = (e or {}).get("care", g.get("care", 0.5))
        out["utility_threshold_delta"] = round(-0.2 * v + 0.1 * (a - 0.3) - 0.15 * (k - 0.5), 4)
    elif action_kind == "reach_timing":
        # High arousal → faster delivery; low care → more measured.
        a = g.get("arousal", 0.3)
        k = (e or {}).get("care", g.get("care", 0.5))
        out["delay_multiplier"] = round(1.0 + 0.5 * (1 - a) - 0.3 * k, 4)
    elif action_kind == "executive_conservatism":
        # High arousal → more conservative (don't act rash when surprised).
        # Low confidence → also more conservative.
        a = g.get("arousal", 0.3); c = g.get("confidence", 0.5)
        out["conservatism_bias"] = round(0.3 * a + 0.4 * (1 - c), 4)
    return out


# ─────────────────────────────────────────────────────────
# Reset + human-readable snapshot
# ─────────────────────────────────────────────────────────

def reset(scope: str = "global") -> dict:
    """Reset affect to NEUTRAL. `scope` ∈ {global, entities, all}. Useful
    for debugging and for users who explicitly want to clear the brain's
    affect-memory."""
    if scope in ("global", "all"):
        _save_global(dict(_NEUTRAL))
    if scope in ("entities", "all"):
        _save_entities({})
    _append_history({"ts": _now(), "src": "reset", "scope": scope})
    return get_state()


def format_human(snap: dict) -> str:
    """Render affect for a human. Same shape as orion_intelligence's
    --human flag so the two compose naturally on a dashboard."""
    g = snap.get("global", {}) or {}
    def _bar(v, lo=-1.0, hi=1.0, width=20):
        pct = (float(v) - lo) / (hi - lo) if hi > lo else 0.5
        n = max(0, min(width, int(round(pct * width))))
        return "█" * n + "·" * (width - n)
    lines = [
        "═" * 56,
        "  ORION — AFFECT SNAPSHOT",
        "═" * 56,
        "  valence    : %+.3f  [%s] " % (g.get("valence", 0), _bar(g.get("valence", 0), -1, 1)),
        "  arousal    :  %.3f  [%s] " % (g.get("arousal", 0), _bar(g.get("arousal", 0), 0, 1)),
        "  confidence :  %.3f  [%s] " % (g.get("confidence", 0), _bar(g.get("confidence", 0), 0, 1)),
        "  care       :  %.3f  [%s] " % (g.get("care", 0), _bar(g.get("care", 0), 0, 1)),
        "",
        "  entities tracked : " + str(snap.get("entity_count", 0)),
    ]
    for eid, e in (snap.get("entities") or {}).items():
        lines.append("    %s : v%+.2f a%.2f c%.2f k%.2f" %
                     (eid, e.get("valence", 0), e.get("arousal", 0),
                      e.get("confidence", 0), e.get("care", 0)))
    lines.append("═" * 56)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# Substrate handlers + service entrypoint
# ─────────────────────────────────────────────────────────

def _on_will_outcome(subject: str, payload: dict) -> None:
    on_will_outcome(payload.get("outcome", ""),
                    payload.get("goal_kind", ""),
                    payload.get("entity_id"))


def _on_surprise(subject: str, payload: dict) -> None:
    s = payload.get("surprise") or payload.get("score") or 0.0
    on_predictor_surprise(float(s), payload.get("entity_id"))


def _on_governor(subject: str, payload: dict) -> None:
    on_governor_decision(float(payload.get("conf", 0.5)),
                         payload.get("outcome"))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        logger.error("orion_substrate not importable — affect cannot run as daemon")
        return 1
    sub = get_substrate()
    sub._connect_blocking()
    subscribe("brain.will.outcome", _on_will_outcome)
    subscribe("brain.predictor.surprise", _on_surprise)
    subscribe("brain.metacog.confidence", _on_governor)
    logger.info("affect alive — subscribing to will.outcome + predictor.surprise + metacog.confidence")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    import sys
    argv = sys.argv[1:]
    if "--human" in argv or "--snapshot" in argv:
        print(format_human(get_state()))
        sys.exit(0)
    if "--reset" in argv:
        scope = "all"
        for a in argv:
            if a.startswith("--scope="):
                scope = a.split("=", 1)[1]
        print(json.dumps(reset(scope), indent=2, default=str))
        sys.exit(0)
    if "--once" in argv:
        print(json.dumps(get_state(), indent=2, default=str))
        sys.exit(0)
    sys.exit(main() or 0)
