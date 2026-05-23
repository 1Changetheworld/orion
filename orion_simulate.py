#!/usr/bin/env python3
"""orion_simulate.py — the brain's imagination layer (dream-replay).

Today Orion only learns from real-world events: a real device dropped, a real
skill fired, a real user deferred. A fresh install therefore boots with an
empty calibration ledger and the governor can earn no confidence until weeks
of lived use have populated it. This is the bootstrap problem and it's the
missing vector of Orion's brain — every install starts at zero.

Biological analogue: hippocampal replay during sleep. The cortex re-runs the
day's experiences with variations, consolidating learning *before* the next
real event. This module does the same — samples plausible scenarios from the
shape of the real ledger, plays them against the live governor, and harvests
sampled outcomes into a SEPARATE sim ledger. The governor then treats those
sim outcomes as evidence at a discounted weight (per orion_metacognition's
honesty floor), so the brain can calibrate on shapes that haven't happened
yet without ever lying to itself about what it knows.

WHAT THIS MODULE IS NOT
=======================

It is NOT a forecasting tool. It does not predict the future of a real device.
It is a *world model* for the brain's *own decision policy* — the rollout
buffer for token-space model-based RL. The "value function" is the metacog
ledger; the "policy" is the governor; the simulator supplies trajectories.

ISOLATION CONTRACT (non-negotiable)
===================================

  - Sim outcomes are written to ~/.orion/metacog/sim_decisions.jsonl ONLY.
    The real decisions.jsonl is read-only here.
  - Every sim row is tagged source="sim" so it cannot be confused for real.
  - Substrate publishes for sim activity use the "sim." subject prefix; real
    subjects (brain.metacog.*, brain.executive.*) are never touched.
  - Sandboxed plays NEVER invoke modules that side-effect on real systems
    (mesh_restore, channels.imessage_*, ssh, services). The "play" is a
    governor() call plus a sampled outcome — no I/O on real targets.

THE HONESTY FLOOR
=================

Lives in orion_metacognition.governor(): sim outcomes may LOWER confidence
(a sim warning that a shape tends to fail is allowed to make the gate more
conservative) but may NEVER RAISE it above what real outcomes alone would
have warranted. The cap is computed as:

    final_conf = min(real_only_conf, real_plus_sim_conf)

This is the wall between imagination and lived experience.

LAUNCH TRIPWIRE
===============

brain.sim.drift is published nightly — the mean |sim_rate − real_rate| over
shapes present in BOTH ledgers. A widening drift means the simulator is
hallucinating reality; we catch it before it corrupts learning. The metric
is the sim subsystem's launch tripwire (analogous to mean_contribution for
the skill ratchet, per docs/architecture/synthesis-continual-learning.md C2).

OUTPUTS
=======

  ~/.orion/metacog/sim_decisions.jsonl       — append-only sim ledger
  ~/.orion/metacog/sim_history.jsonl         — append-only per-cycle summary

Subjects published (sim namespace only):
  sim.brain.scenario          — one scenario generated
  sim.brain.metacog.confidence — governor's verdict on the scenario
  sim.brain.outcome           — the sampled outcome
  brain.sim.drift             — the tripwire (this one is in real namespace
                                deliberately, so observability dashboards
                                surface it without subscribing to sim.*)
  brain.sim.cycle_complete    — end-of-cycle summary
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orion.simulate")

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR") or str(Path.home() / ".orion"))
LEDGER_DIR = ORION_HOME / "metacog"
REAL_LEDGER_PATH = LEDGER_DIR / "decisions.jsonl"
SIM_LEDGER_PATH = LEDGER_DIR / "sim_decisions.jsonl"
SIM_HISTORY_PATH = LEDGER_DIR / "sim_history.jsonl"

# Cycle defaults. N_SCENARIOS = 20 matches the dream-cycle ask in the
# Terminal-2 brief; environment overrides exist so the tripwire can be
# tightened or loosened without code changes when traffic grows.
N_SCENARIOS = int(os.environ.get("ORION_SIM_N_SCENARIOS", "20"))
NOVELTY_PROB = float(os.environ.get("ORION_SIM_NOVELTY_PROB", "0.25"))
SIM_WEIGHT = float(os.environ.get("ORION_SIM_WEIGHT", "0.3"))   # consulted by metacog
MAX_REAL_LOAD = int(os.environ.get("ORION_SIM_MAX_REAL_LOAD", "5000"))

# Outcome mapping (mirrors orion_metacognition.OUTCOME_VALUE). Kept local
# rather than imported so this module loads cleanly during a metacog
# initialisation failure — the test path is the bootstrap path.
OUTCOME_VALUES = {"succeeded": 1.0, "failed": 0.0, "ignored": 0.3, "denied": 0.5}

# Seed library for the cold-start case (empty real ledger) and for the
# novelty injector. These are the *shapes* Orion's autonomic loops actually
# emit today (mesh_recovery, mesh_restore, self_heal, dispatch); restrict
# novelty to plausible shape combinations rather than free-form invention so
# the governor isn't asked to calibrate on tokens it would never see.
SEED_SYMPTOMS = [
    "mesh_device_returned",
    "SERVICE_LOOP",
    "DEPENDENCY_FAILURE",
    "AUTH_DRIFT",
    "NETWORK_PARTITION",
    "CHANNEL_LIMBO",
    "FUEL_OUTAGE",
    "DISK_PRESSURE",
]
SEED_ACTIONS = [
    "restart dead Orion services on {host}",
    "reload {host} launchd agent for {svc}",
    "re-probe {host} health endpoint",
    "rotate fuel adapter to fallback",
    "free disk on {host}",
    "rejoin gossip mesh from {host}",
]
SEED_FUELS = ["claude-opus", "claude-sonnet", "gemini", "codex", "ollama",
              "mesh-recovery", "self-heal"]
SEED_HOSTS = ["COMMAND", "FORGE"]


def _publish(subject: str, payload: dict) -> None:
    """Best-effort substrate publish. Never raises — sim must not be able
    to take down the dream cycle if NATS is unreachable."""
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# Ledger I/O — real is READ-ONLY, sim is APPEND-ONLY
# ─────────────────────────────────────────────────────────

def _read_jsonl(path: Path, limit: int) -> list[dict]:
    """Read up to `limit` rows from a JSONL file, oldest first. Truncated
    reads are fine — the simulator wants distributional shape, not a perfect
    census, and capping protects long-lived production hosts."""
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if len(rows) > limit:
            # Keep the MOST RECENT — the simulator should reflect the brain
            # as it lives now, not the brain as it was a year ago.
            rows = rows[-limit:]
    except OSError as e:
        logger.warning("ledger read failed (%s): %s", path, e)
    return rows


def load_real_ledger() -> list[dict]:
    """Load the real decision ledger (oldest-first within the recency window)."""
    return _read_jsonl(REAL_LEDGER_PATH, MAX_REAL_LOAD)


def load_sim_ledger() -> list[dict]:
    """Load the sim ledger. Used by drift telemetry."""
    return _read_jsonl(SIM_LEDGER_PATH, MAX_REAL_LOAD)


def _append_sim(row: dict) -> None:
    """Append one sim row to the sim ledger. Caller is responsible for
    setting source='sim' (we double-check anyway as belt-and-braces)."""
    row.setdefault("source", "sim")
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with SIM_LEDGER_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except OSError as e:
        logger.warning("sim ledger write failed: %s", e)


# ─────────────────────────────────────────────────────────
# Scenario generation
# ─────────────────────────────────────────────────────────

def _weighted_pick(items: list, weights: list[float]):
    """random.choices wrapper that tolerates empty input + zero-sum weights."""
    if not items:
        return None
    total = sum(weights)
    if total <= 0:
        return random.choice(items)
    return random.choices(items, weights=weights, k=1)[0]


def _marginals(real: list[dict]) -> dict:
    """Compute frequency tables from the real ledger. Used to sample shapes
    that reflect what Orion actually sees, not what we imagine it sees."""
    sym_freq: dict[str, int] = {}
    act_by_sym: dict[str, dict[str, int]] = {}
    fuel_freq: dict[str, int] = {}
    outcome_by_sym: dict[str, list[str]] = {}
    for r in real:
        sym = r.get("symptom_class") or "UNRECOGNIZED"
        act = r.get("proposed_action") or ""
        fuel = r.get("fuel") or ""
        oc = r.get("outcome")
        sym_freq[sym] = sym_freq.get(sym, 0) + 1
        if act:
            sub = act_by_sym.setdefault(sym, {})
            sub[act] = sub.get(act, 0) + 1
        if fuel:
            fuel_freq[fuel] = fuel_freq.get(fuel, 0) + 1
        if oc in OUTCOME_VALUES:
            outcome_by_sym.setdefault(sym, []).append(oc)
    return {
        "sym_freq": sym_freq, "act_by_sym": act_by_sym,
        "fuel_freq": fuel_freq, "outcome_by_sym": outcome_by_sym,
    }


def _novelty_scenario() -> dict:
    """A shape mixed from the seed library that the real ledger may never
    have seen. The mix is deliberately plausible (real symptom × real action
    × real fuel × real host) rather than random tokens, because we want the
    governor to calibrate on combinations it *could* meet, not gibberish."""
    sym = random.choice(SEED_SYMPTOMS)
    host = random.choice(SEED_HOSTS)
    svc = random.choice(["mesh", "imessage", "dream", "metacog", "will"])
    action = random.choice(SEED_ACTIONS).format(host=host, svc=svc)
    fuel = random.choice(SEED_FUELS)
    # Reversibility / blast_radius assignment mirrors how the autonomic loops
    # tag their own remedies — restart of a single Orion service is reversible
    # and single-host; AUTH/DISK/NETWORK at host level start non-reversible.
    risky = sym in ("AUTH_DRIFT", "DISK_PRESSURE", "NETWORK_PARTITION")
    return {
        "symptom_class": sym,
        "proposed_action": action,
        "fuel": fuel,
        "host": host,
        "reversible": not risky,
        "blast_radius": "host" if risky else "single",
        "source": "sim",
        "novelty": True,
    }


def sample_scenario(real: list[dict], novelty_prob: float = NOVELTY_PROB) -> dict:
    """Draw one (symptom, action, fuel, host) tuple. With probability
    `novelty_prob`, or when the real ledger is empty, fall through to the
    novelty injector. Otherwise weight by real frequencies so the simulator
    reflects observed traffic."""
    if not real or random.random() < novelty_prob:
        return _novelty_scenario()

    m = _marginals(real)
    sym_items = list(m["sym_freq"].keys())
    sym_weights = [m["sym_freq"][s] for s in sym_items]
    sym = _weighted_pick(sym_items, sym_weights)
    # Action conditional on symptom — keeps sampled (sym, act) pairs jointly
    # realistic, not a random product of marginals.
    sub = m["act_by_sym"].get(sym, {})
    if sub:
        act_items = list(sub.keys())
        act_weights = [sub[a] for a in act_items]
        action = _weighted_pick(act_items, act_weights)
    else:
        action = random.choice(SEED_ACTIONS).format(
            host=random.choice(SEED_HOSTS),
            svc=random.choice(["mesh", "imessage", "dream"]),
        )
    fuel_items = list(m["fuel_freq"].keys()) or SEED_FUELS
    fuel_weights = [m["fuel_freq"].get(f, 1) for f in fuel_items]
    fuel = _weighted_pick(fuel_items, fuel_weights)
    return {
        "symptom_class": sym,
        "proposed_action": action,
        "fuel": fuel,
        "host": random.choice(SEED_HOSTS),
        "reversible": True,
        "blast_radius": "single",
        "source": "sim",
        "novelty": False,
    }


# ─────────────────────────────────────────────────────────
# Outcome sampling — the world model
# ─────────────────────────────────────────────────────────

def _sample_outcome(scenario: dict, real: list[dict]) -> str:
    """Sample an outcome from the real ledger's conditional distribution on
    the scenario's symptom_class. If no real evidence exists for the shape
    (true novelty), draw from a conservative prior — slightly worse than
    chance for risky scenarios, slightly better for reversible single-host
    ones. The prior is INTENTIONALLY pessimistic on novelty so the sim
    pushes the governor toward 'ask' on unfamiliar shapes rather than
    fabricating confidence."""
    sym = scenario.get("symptom_class")
    matches = [r.get("outcome") for r in real
               if r.get("symptom_class") == sym and r.get("outcome") in OUTCOME_VALUES]
    if matches:
        return random.choice(matches)
    if scenario.get("reversible") and scenario.get("blast_radius") == "single":
        return random.choices(
            ["succeeded", "failed", "ignored"], weights=[0.55, 0.30, 0.15], k=1)[0]
    # Risky novelty — bias toward failure so the governor learns to ask.
    return random.choices(
        ["succeeded", "failed", "ignored", "denied"],
        weights=[0.30, 0.45, 0.15, 0.10], k=1)[0]


# ─────────────────────────────────────────────────────────
# One sandboxed play — governor + outcome + ledger write
# ─────────────────────────────────────────────────────────

def _play_one(scenario: dict, real: list[dict]) -> dict:
    """Play one scenario through the LIVE governor (which only reads ledger,
    so this has no side effects on real targets), sample an outcome, and
    append it to the sim ledger. Returns the recorded row."""
    decision_id = "sim-%s" % uuid.uuid4().hex[:12]
    action = scenario["proposed_action"]
    symptom = scenario["symptom_class"]
    fuel = scenario["fuel"]
    reversible = scenario.get("reversible", True)
    blast = scenario.get("blast_radius", "single")

    # The governor IS the agent under test. We do not bypass it — calling it
    # here is the whole point of the sim. It reads ledger via _similar_rows;
    # it does not write or take any external action.
    try:
        import orion_metacognition
        g = orion_metacognition.governor(
            action, reversible=reversible, blast_radius=blast,
            symptom=symptom, fuel=fuel)
    except Exception as e:
        # If metacog can't be loaded at all, log conservatively and ask.
        g = {"confidence": 0.4, "decision": "ask",
             "basis": ["governor import failed: %s" % e]}

    outcome = _sample_outcome(scenario, real)
    ov = OUTCOME_VALUES.get(outcome, 0.5)
    conf_before = g.get("confidence")
    row = {
        "decision_id": decision_id,
        "symptom_class": symptom,
        "proposed_action": action,
        "conf_before": conf_before,
        "basis": g.get("basis", []),
        "governor_decision": g.get("decision"),
        "fuel": fuel,
        "host": scenario.get("host"),
        "reversible": reversible,
        "blast_radius": blast,
        "outcome": outcome,
        "outcome_value": ov,
        "calibration_delta": (ov - conf_before) if conf_before is not None else None,
        "novelty": scenario.get("novelty", False),
        "ts_proposed": time.time(),
        "ts_outcome": time.time(),
        "source": "sim",
    }
    _append_sim(row)

    # Sim namespace publishes — any observer can subscribe and never confuse
    # these with real brain activity.
    _publish("sim.brain.scenario", {
        "decision_id": decision_id, "symptom_class": symptom,
        "fuel": fuel, "novelty": scenario.get("novelty", False),
        "ts": row["ts_proposed"],
    })
    _publish("sim.brain.metacog.confidence", {
        "decision_id": decision_id, "conf": conf_before,
        "decision": g.get("decision"), "ts": row["ts_proposed"],
    })
    _publish("sim.brain.outcome", {
        "decision_id": decision_id, "outcome": outcome,
        "calibration_delta": row["calibration_delta"], "ts": row["ts_outcome"],
    })
    return row


# ─────────────────────────────────────────────────────────
# Drift telemetry — the launch tripwire
# ─────────────────────────────────────────────────────────

def compute_drift(real: Optional[list[dict]] = None,
                  sim: Optional[list[dict]] = None) -> dict:
    """For each symptom_class present in BOTH ledgers, compare mean outcome
    value. The aggregate mean of those per-shape deltas is brain.sim.drift —
    rising means the simulator is hallucinating. Single-shape coverage is
    surfaced so a small overlap doesn't masquerade as a confident drift
    measurement."""
    real = real if real is not None else load_real_ledger()
    sim = sim if sim is not None else load_sim_ledger()

    def _mean_outcome(rows: list[dict], sym: str) -> Optional[float]:
        vals = [OUTCOME_VALUES.get(r.get("outcome")) for r in rows
                if r.get("symptom_class") == sym
                and r.get("outcome") in OUTCOME_VALUES]
        return (sum(vals) / len(vals)) if vals else None

    real_shapes = {r.get("symptom_class") for r in real
                   if r.get("outcome") in OUTCOME_VALUES}
    sim_shapes = {r.get("symptom_class") for r in sim
                  if r.get("outcome") in OUTCOME_VALUES}
    overlap = sorted(s for s in (real_shapes & sim_shapes) if s)

    by_shape: dict[str, dict] = {}
    deltas: list[float] = []
    for sym in overlap:
        r_mean = _mean_outcome(real, sym)
        s_mean = _mean_outcome(sim, sym)
        if r_mean is None or s_mean is None:
            continue
        d = abs(s_mean - r_mean)
        by_shape[sym] = {"real_mean": round(r_mean, 3),
                         "sim_mean": round(s_mean, 3),
                         "abs_drift": round(d, 3)}
        deltas.append(d)
    mean_drift = (sum(deltas) / len(deltas)) if deltas else 0.0
    return {
        "mean_drift": round(mean_drift, 3),
        "shapes_compared": len(deltas),
        "real_shape_count": len(real_shapes),
        "sim_shape_count": len(sim_shapes),
        "by_shape": by_shape,
    }


# ─────────────────────────────────────────────────────────
# Cycle entry point — what dream._run_dream_cycle() calls
# ─────────────────────────────────────────────────────────

def run_scenarios(n: int = N_SCENARIOS,
                  novelty_prob: float = NOVELTY_PROB) -> dict:
    """Generate + play `n` scenarios. Returns a summary suitable for the
    dream history JSONL. Never raises — the dream cycle must survive a
    broken simulator."""
    started = time.time()
    real = load_real_ledger()
    plays = 0
    novelty = 0
    decisions = {"auto": 0, "ask": 0}
    sampled_outcomes: dict[str, int] = {"succeeded": 0, "failed": 0,
                                        "ignored": 0, "denied": 0}
    try:
        for _ in range(max(0, int(n))):
            scenario = sample_scenario(real, novelty_prob=novelty_prob)
            row = _play_one(scenario, real)
            plays += 1
            if scenario.get("novelty"):
                novelty += 1
            d = row.get("governor_decision")
            if d in decisions:
                decisions[d] += 1
            oc = row.get("outcome")
            if oc in sampled_outcomes:
                sampled_outcomes[oc] += 1
    except Exception as e:
        logger.warning("sim cycle aborted mid-run: %s", e)

    drift = compute_drift(real=real)
    summary = {
        "ts": started,
        "duration_sec": round(time.time() - started, 3),
        "plays": plays,
        "novelty_plays": novelty,
        "governor_decisions": decisions,
        "sampled_outcomes": sampled_outcomes,
        "drift": drift,
        "real_rows_seen": len(real),
    }

    try:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        with SIM_HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, default=str) + "\n")
    except OSError as e:
        logger.warning("sim history write failed: %s", e)

    # brain.sim.drift is the tripwire — emit in the REAL brain namespace
    # so existing dashboards surface it without subscribing to sim.* (the
    # tripwire must be visible without opting in to imagination output).
    _publish("brain.sim.drift", {
        "mean_drift": drift["mean_drift"],
        "shapes_compared": drift["shapes_compared"],
        "ts": time.time(),
    })
    _publish("brain.sim.cycle_complete", {
        "plays": plays, "novelty_plays": novelty,
        "ts": time.time(),
    })

    logger.info("sim cycle: %d plays (%d novelty), drift=%.3f over %d shapes",
                plays, novelty, drift["mean_drift"], drift["shapes_compared"])
    return summary


# ─────────────────────────────────────────────────────────
# CLI — for manual smoke-tests
# ─────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("ORION_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if argv and argv[0] == "drift":
        print(json.dumps(compute_drift(), indent=2))
        return 0
    n = int(argv[0]) if argv and argv[0].isdigit() else N_SCENARIOS
    summary = run_scenarios(n=n)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
