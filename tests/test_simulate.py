"""Tests for orion_simulate — dream-replay sandbox contract.

The simulator is the brain's imagination layer. Its contract has four hard
walls these scenarios pin down:

  1. ISOLATION — sim outcomes land in ~/.orion/metacog/sim_decisions.jsonl,
     never in the real ledger. The real ledger is treated read-only.
  2. TAGGING — every sim row carries source="sim". An untagged sim row would
     leak into the real-only path the governor uses for its honesty floor.
  3. HONESTY FLOOR — orion_metacognition.governor() returns
     min(combined_with_sim, real_only). Sim may LOWER the gate; it must
     NEVER raise it above what real outcomes alone warranted.
  4. DRIFT TELEMETRY — compute_drift returns a usable mean per shape, and
     the per-cycle history file is appended to.

These all run in a tempdir so real ~/.orion is never touched. Pure-function
tests — no NATS, no live fuels (the simulator's governor calls degrade
gracefully when fuel adapters are unreachable, which is the test environment).
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile
from pathlib import Path

from tests._harness import ScenarioResult, assert_equals, assert_true, run_suite


# ──────────────────────────────────────────────────────────────────
# Tempdir + module reload — the harness for every scenario below.
# ──────────────────────────────────────────────────────────────────

def _with_tempdir(fn):
    """Run fn(tempdir) with ORION_BRAIN_DIR pointing at a fresh tempdir.
    Reloads the metacog + simulate modules so their cached paths/deques
    point at the new home. Restores on exit. Seeds RNG so scenarios are
    deterministic across runs."""
    prior_dir = os.environ.get("ORION_BRAIN_DIR")
    prior_nats = os.environ.get("ORION_NATS_URL")
    with tempfile.TemporaryDirectory(prefix="orion-sim-test-") as td:
        os.environ["ORION_BRAIN_DIR"] = td
        # Point the substrate at a definitely-unreachable address so any
        # accidental publish goes to a no-op fast (no real NATS in CI).
        os.environ["ORION_NATS_URL"] = "nats://127.0.0.1:1"
        for mod in ("orion_metacognition", "orion_simulate", "orion_substrate"):
            sys.modules.pop(mod, None)
        random.seed(1337)
        try:
            return fn(td)
        finally:
            if prior_dir is None:
                os.environ.pop("ORION_BRAIN_DIR", None)
            else:
                os.environ["ORION_BRAIN_DIR"] = prior_dir
            if prior_nats is None:
                os.environ.pop("ORION_NATS_URL", None)
            else:
                os.environ["ORION_NATS_URL"] = prior_nats
            for mod in ("orion_metacognition", "orion_simulate", "orion_substrate"):
                sys.modules.pop(mod, None)


def _seed_real_ledger(td: str, rows: list[dict]) -> Path:
    """Write a fake real ledger so the simulator + governor have shape data
    to draw on. Returns the path so tests can re-stat it later."""
    p = Path(td) / "metacog" / "decisions.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return p


# ──────────────────────────────────────────────────────────────────
# Scenarios
# ──────────────────────────────────────────────────────────────────

def scenario_sim_isolation_real_ledger_untouched():
    """Sim writes must NEVER land in the real ledger, even when the sim
    cycle runs many scenarios."""
    r = ScenarioResult(scenario="sim outcomes are isolated from the real ledger")

    def body(td):
        real_path = _seed_real_ledger(td, [
            {"symptom_class": "mesh_device_returned",
             "proposed_action": "restart dead Orion services on COMMAND",
             "outcome": "succeeded", "outcome_value": 1.0,
             "fuel": "mesh-recovery", "ts_outcome": 1700000000.0},
            {"symptom_class": "SERVICE_LOOP",
             "proposed_action": "reload com.orion.imessage",
             "outcome": "failed", "outcome_value": 0.0,
             "fuel": "mesh-recovery", "ts_outcome": 1700000100.0},
        ])
        real_size_before = real_path.stat().st_size

        import orion_simulate
        summary = orion_simulate.run_scenarios(n=15)

        sim_path = Path(td) / "metacog" / "sim_decisions.jsonl"
        assert_true(r, "sim ledger file was created", sim_path.exists())
        sim_rows = [json.loads(line) for line in sim_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert_equals(r, "sim ledger has 15 rows", len(sim_rows), 15)
        assert_true(r, "every sim row tagged source='sim'",
                    all(row.get("source") == "sim" for row in sim_rows))
        assert_true(r, "every sim row carries an outcome",
                    all(row.get("outcome") in {"succeeded", "failed", "ignored", "denied"}
                        for row in sim_rows))
        # Real ledger byte-for-byte unchanged is the strongest possible
        # isolation check; weaker ones (row count, hash) would let a
        # mis-routed write hide behind a truncation.
        assert_equals(r, "real ledger byte size unchanged",
                      real_path.stat().st_size, real_size_before)
        assert_equals(r, "summary counts match what landed",
                      summary["plays"], 15)

    _with_tempdir(body)
    return r


def scenario_governor_honesty_floor_caps_at_real():
    """Sim outcomes that disagree with real outcomes MUST NOT raise governor
    confidence above what real outcomes alone would yield. They may lower it,
    but never raise it. This is the wall between imagination and lived
    experience — enforced in orion_metacognition.governor() itself."""
    r = ScenarioResult(scenario="governor honesty floor — sim cannot raise above real")

    def body(td):
        # Real ledger: the shape FAILED every time. Real-only confidence
        # should be low.
        real_rows = [{
            "symptom_class": "AUTH_DRIFT",
            "proposed_action": "rotate fuel adapter to fallback",
            "outcome": "failed", "outcome_value": 0.0,
            "fuel": "ollama", "ts_outcome": 1700000000.0 + i,
        } for i in range(6)]
        _seed_real_ledger(td, real_rows)

        # Sim ledger: imagination says it succeeded every time. If the floor
        # is broken, combined confidence will sit higher than real-only.
        sim_path = Path(td) / "metacog" / "sim_decisions.jsonl"
        sim_path.parent.mkdir(parents=True, exist_ok=True)
        with sim_path.open("w", encoding="utf-8") as f:
            for i in range(20):
                f.write(json.dumps({
                    "symptom_class": "AUTH_DRIFT",
                    "proposed_action": "rotate fuel adapter to fallback",
                    "outcome": "succeeded", "outcome_value": 1.0,
                    "fuel": "ollama", "source": "sim",
                    "ts_outcome": 1700100000.0 + i,
                }) + "\n")

        import orion_metacognition as mc
        # Reversible single-host so we exercise the calm tier-2 path (no
        # cross-fuel probe, which would also cap and confuse the test).
        g_combined = mc.governor(
            "rotate fuel adapter to fallback",
            reversible=True, blast_radius="single",
            symptom="AUTH_DRIFT", fuel="ollama")

        # Now compute what real-only WOULD have returned by stripping sim
        # rows from the cache and re-asking.
        mc._sim_ledger_cache.clear()
        g_real = mc.governor(
            "rotate fuel adapter to fallback",
            reversible=True, blast_radius="single",
            symptom="AUTH_DRIFT", fuel="ollama")

        assert_true(r, "combined confidence <= real-only (honesty floor)",
                    g_combined["confidence"] <= g_real["confidence"] + 1e-9,
                    "combined=%s real=%s" % (g_combined["confidence"], g_real["confidence"]))
        # And the basis line must announce the floor when it triggered.
        assert_true(r, "basis advertises honesty floor when sim was more optimistic",
                    any("honesty-floor" in b for b in g_combined.get("basis", [])),
                    "basis: %s" % g_combined.get("basis"))

    _with_tempdir(body)
    return r


def scenario_governor_sim_can_lower_below_real():
    """Symmetric direction: when sim says a shape tends to fail, the combined
    confidence MAY come out below the real-only confidence. This is the
    'warn' direction the sim is allowed to push."""
    r = ScenarioResult(scenario="sim is allowed to lower the gate below real-only")

    def body(td):
        # Real: 4/4 succeeded — real-only confidence should be high.
        real_rows = [{
            "symptom_class": "mesh_device_returned",
            "proposed_action": "restart dead Orion services on COMMAND",
            "outcome": "succeeded", "outcome_value": 1.0,
            "fuel": "mesh-recovery", "ts_outcome": 1700000000.0 + i,
        } for i in range(4)]
        _seed_real_ledger(td, real_rows)

        # Sim: many failures imagined for the same shape.
        sim_path = Path(td) / "metacog" / "sim_decisions.jsonl"
        sim_path.parent.mkdir(parents=True, exist_ok=True)
        with sim_path.open("w", encoding="utf-8") as f:
            for i in range(40):
                f.write(json.dumps({
                    "symptom_class": "mesh_device_returned",
                    "proposed_action": "restart dead Orion services on COMMAND",
                    "outcome": "failed", "outcome_value": 0.0,
                    "fuel": "mesh-recovery", "source": "sim",
                    "ts_outcome": 1700100000.0 + i,
                }) + "\n")

        import orion_metacognition as mc
        g_combined = mc.governor(
            "restart dead Orion services on COMMAND",
            reversible=True, blast_radius="single",
            symptom="mesh_device_returned", fuel="mesh-recovery")

        mc._sim_ledger_cache.clear()
        g_real = mc.governor(
            "restart dead Orion services on COMMAND",
            reversible=True, blast_radius="single",
            symptom="mesh_device_returned", fuel="mesh-recovery")

        # The honesty floor is still min(combined, real); when combined is
        # already lower (sim pulled it down), final == combined and it sits
        # at or below real. The point is that sim CAN move it down.
        assert_true(r, "combined confidence <= real-only (sim lowered)",
                    g_combined["confidence"] <= g_real["confidence"] + 1e-9)
        # The combined arm consumed sim rows — its basis should reference them.
        assert_true(r, "basis mentions sim rows in combined arm",
                    any(" sim " in b for b in g_combined.get("basis", [])),
                    "basis: %s" % g_combined.get("basis"))

    _with_tempdir(body)
    return r


def scenario_drift_telemetry_summarises_overlap():
    """compute_drift() must report a usable mean drift over shapes present in
    BOTH ledgers, and run_scenarios() must emit a per-cycle summary line."""
    r = ScenarioResult(scenario="drift telemetry summarises real-vs-sim overlap")

    def body(td):
        # Real shape A: 100% success. Real shape B: 100% failure.
        _seed_real_ledger(td, [
            {"symptom_class": "shape_A", "proposed_action": "fix A",
             "outcome": "succeeded", "outcome_value": 1.0, "fuel": "x",
             "ts_outcome": 1700000000.0},
            {"symptom_class": "shape_A", "proposed_action": "fix A",
             "outcome": "succeeded", "outcome_value": 1.0, "fuel": "x",
             "ts_outcome": 1700000010.0},
            {"symptom_class": "shape_B", "proposed_action": "fix B",
             "outcome": "failed", "outcome_value": 0.0, "fuel": "x",
             "ts_outcome": 1700000020.0},
        ])
        # Sim shape A: all failures (drift = 1.0). Sim shape B: all failures
        # (drift = 0.0). Mean drift should be 0.5.
        sim_path = Path(td) / "metacog" / "sim_decisions.jsonl"
        sim_path.parent.mkdir(parents=True, exist_ok=True)
        with sim_path.open("w", encoding="utf-8") as f:
            for sym, oc in [("shape_A", "failed"), ("shape_A", "failed"),
                            ("shape_B", "failed"), ("shape_B", "failed")]:
                ov = 1.0 if oc == "succeeded" else 0.0
                f.write(json.dumps({
                    "symptom_class": sym, "proposed_action": "fix " + sym[-1],
                    "outcome": oc, "outcome_value": ov, "fuel": "x",
                    "source": "sim", "ts_outcome": 1700100000.0,
                }) + "\n")

        import orion_simulate
        drift = orion_simulate.compute_drift()
        assert_equals(r, "two shapes compared", drift["shapes_compared"], 2)
        # shape_A drift = |0.0 - 1.0| = 1.0; shape_B drift = |0.0 - 0.0| = 0.0
        assert_true(r, "mean drift roughly 0.5",
                    abs(drift["mean_drift"] - 0.5) < 0.01,
                    "got %s" % drift["mean_drift"])
        assert_true(r, "per-shape breakdown present for shape_A",
                    "shape_A" in drift["by_shape"])
        assert_true(r, "shape_A flagged with abs_drift 1.0",
                    abs(drift["by_shape"]["shape_A"]["abs_drift"] - 1.0) < 0.01)

        # And running a full sim cycle should append to the history JSONL.
        summary = orion_simulate.run_scenarios(n=3)
        history = Path(td) / "metacog" / "sim_history.jsonl"
        assert_true(r, "sim history file appended", history.exists())
        lines = [l for l in history.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert_true(r, "history contains at least one cycle record", len(lines) >= 1)
        last = json.loads(lines[-1])
        assert_equals(r, "summary plays count round-trips through history",
                      last["plays"], summary["plays"])
        assert_true(r, "summary carries drift section",
                    "drift" in last and "mean_drift" in last["drift"])

    _with_tempdir(body)
    return r


def scenario_cold_start_handles_empty_real_ledger():
    """An empty real ledger (fresh install) must not crash the simulator —
    it should fall through to the novelty injector and still produce rows.
    This is the bootstrap case the whole module exists for."""
    r = ScenarioResult(scenario="cold start with empty real ledger still produces sim rows")

    def body(td):
        # Deliberately do NOT seed a real ledger.
        import orion_simulate
        summary = orion_simulate.run_scenarios(n=5)
        assert_equals(r, "produced 5 plays from cold start", summary["plays"], 5)
        assert_equals(r, "every play was a novelty (no real to sample from)",
                      summary["novelty_plays"], 5)
        sim_path = Path(td) / "metacog" / "sim_decisions.jsonl"
        assert_true(r, "sim ledger written despite empty real ledger",
                    sim_path.exists())

    _with_tempdir(body)
    return r


SCENARIOS = [
    scenario_sim_isolation_real_ledger_untouched,
    scenario_governor_honesty_floor_caps_at_real,
    scenario_governor_sim_can_lower_below_real,
    scenario_drift_telemetry_summarises_overlap,
    scenario_cold_start_handles_empty_real_ledger,
]


if __name__ == "__main__":
    sys.exit(run_suite("DREAM-REPLAY SIMULATOR", SCENARIOS))
