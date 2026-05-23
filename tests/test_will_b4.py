"""tests/test_will_b4.py — Build #4 (Volition & Goals) end-to-end tests.

Scope:
  D1 — hierarchical decomposition (long_term/self_action → sub-goals on spine)
  D2 — meta-calibration (will_user_receptivity cross-kind cap)
  D3 — intent v2 (hybrid regex + cached fuel)
  D4 — evidence-weighted per-kind half-life
  D5 — impact-weighted selection

Discipline: everything runs in a tempdir. ORION_BRAIN_DIR + ORION_WILL_DIR
are pointed at the tempdir BEFORE orion_will is imported, so the real
~/.orion is never touched. Fuel calls are monkey-patched so no real
model is hit; the tests verify wiring + math, not LLM quality.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Point all Orion state at a tempdir before importing the modules so the
# real ~/.orion stays untouched.
_TMP = Path(tempfile.mkdtemp(prefix="orion_will_b4_"))
os.environ["ORION_BRAIN_DIR"] = str(_TMP)
os.environ["ORION_WILL_DIR"] = str(_TMP / "will")
# Make rate-limit forgiving so the test can fuel-extract more than once.
os.environ["ORION_WILL_INTENT_FUEL_RATE"] = "100"
# Force the cross-kind cap to fire on a small sample so we don't have to
# fabricate dozens of outcomes.
os.environ["ORION_WILL_RECEPTIVITY_MIN_OBS"] = "3"

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tests._harness import (  # noqa: E402
    ScenarioResult, assert_equals, assert_true, run_suite,
)

import orion_will  # noqa: E402  (must come after env vars)
import orion_taskspine  # noqa: E402


def _reset_state() -> None:
    """Wipe the tempdir between scenarios so each one starts clean."""
    orion_will._active_goals.clear()
    orion_will._intent_fuel_cache.clear()
    orion_will._intent_fuel_cache_loaded = False
    orion_will._intent_fuel_calls.clear()
    # Re-create the will dir on every test so removed files come back.
    will_dir = Path(os.environ["ORION_WILL_DIR"])
    if will_dir.exists():
        for f in will_dir.iterdir():
            try:
                f.unlink()
            except Exception:
                pass
    # Re-create the tasks dir as well so spine state doesn't leak.
    tasks_dir = Path(os.environ["ORION_BRAIN_DIR"]) / "tasks"
    if tasks_dir.exists():
        for f in tasks_dir.iterdir():
            try:
                f.unlink()
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────
# D1 — Hierarchical decomposition
# ──────────────────────────────────────────────────────────────────

def test_d1_hierarchical_decomposition() -> ScenarioResult:
    r = ScenarioResult(scenario="D1: hierarchical decomposition")
    _reset_state()

    # Stub the fuel to return a deterministic 3-step plan.
    captured_prompts: list[str] = []

    class _FakeFuel:
        @staticmethod
        def get_fuel(prompt, interface="cli", max_turns=15):
            captured_prompts.append(prompt)
            return ("Research destinations\n"
                    "Block out vacation time\n"
                    "Book the flight", "fake-fuel")

    sys.modules["orion_fuel"] = _FakeFuel  # type: ignore[assignment]

    parent = {
        "goal_id": "g_parent01",
        "kind": "long_term",
        "description": "plan a trip to Japan in the spring",
        "importance": 0.7,
    }
    task_id = orion_taskspine.create_task(
        "will-goal[long_term]: %s" % parent["description"])
    created = orion_will._decompose_and_seed_subgoals(parent, task_id)

    assert_true(r, "fuel was called for decomposition", len(captured_prompts) == 1,
                f"got {len(captured_prompts)} fuel calls")
    assert_equals(r, "three sub-goals created", created, 3)

    # The plan must live on the spine (survives host death).
    task = orion_taskspine.load_task(task_id)
    plan_steps = [s for s in (task or {}).get("steps", [])
                  if s.get("role") == "will-plan"]
    assert_equals(r, "plan recorded on spine task", len(plan_steps), 1)
    plan_content = plan_steps[0]["content"] if plan_steps else ""
    assert_true(r, "plan content lists the sub-goals",
                "Research destinations" in plan_content,
                f"got: {plan_content[:120]}")

    # Sub-goals are first-class active goals with parent linkage.
    children = [g for g in orion_will._active_goals.values()
                if g.get("parent_goal_id") == parent["goal_id"]]
    assert_equals(r, "three children in active set", len(children), 3)
    assert_true(r, "children carry parent_task_id",
                all(c.get("parent_task_id") == task_id for c in children))
    indices = sorted(c.get("subgoal_idx", -1) for c in children)
    assert_equals(r, "subgoal indices are 0..N-1", indices, [0, 1, 2])

    # Idempotent — re-running on the same task does not duplicate.
    created_again = orion_will._decompose_and_seed_subgoals(parent, task_id)
    assert_equals(r, "re-decompose is idempotent (returns 0)", created_again, 0)
    children_again = [g for g in orion_will._active_goals.values()
                      if g.get("parent_goal_id") == parent["goal_id"]]
    assert_equals(r, "children unchanged after re-decompose",
                  len(children_again), 3)

    return r


# ──────────────────────────────────────────────────────────────────
# D2 — Meta-calibration (will_user_receptivity)
# ──────────────────────────────────────────────────────────────────

def test_d2_meta_calibration() -> ScenarioResult:
    r = ScenarioResult(scenario="D2: meta-calibration cap")
    _reset_state()

    # No outcomes yet → no cap, rate=None.
    recept = orion_will.will_user_receptivity()
    assert_equals(r, "no evidence → applied_cap False",
                  recept["applied_cap"], False)
    assert_equals(r, "no evidence → rate None", recept["rate"], None)

    # Seed broad deferrals across MULTIPLE kinds — this is the whole point:
    # cross-kind aggregation overrides per-kind silos.
    now = time.time()
    for i, (kind, outcome) in enumerate([
        ("reminder", "deferred"),
        ("lapsed", "deferred"),
        ("self_action", "deferred"),
        ("reminder", "engaged"),
    ]):
        orion_will._append_ledger({
            "phase": "outcome", "goal_id": f"g_obs{i:02d}",
            "outcome": outcome, "kind": kind,
            "ts": now - i * 60,
        })

    recept = orion_will.will_user_receptivity(now=now + 1)
    assert_equals(r, "engaged count = 1", recept["engaged"], 1)
    assert_equals(r, "deferred count = 3", recept["deferred"], 3)
    assert_true(r, "rate is 0.25 (below tau=0.30)",
                abs((recept["rate"] or 0) - 0.25) < 0.01,
                f"rate={recept['rate']}")
    assert_equals(r, "applied_cap is True", recept["applied_cap"], True)

    # Now wire a stub governor that says auto on everything. The cap must
    # OVERRIDE the governor and keep promotion suppressed.
    class _StubMetacog:
        @staticmethod
        def governor(action, reversible=True, blast_radius="single",
                     symptom="", fuel=""):
            return {"decision": "auto", "confidence": 0.95, "basis": ["stub"]}

        @staticmethod
        def record_outcome(*args, **kwargs):
            pass

    sys.modules["orion_metacognition"] = _StubMetacog  # type: ignore[assignment]

    new_goal = {
        "goal_id": "g_capped01",
        "kind": "memory_anchor",  # a kind with NO history in the seeds
        "description": "the cross-kind cap should still suppress",
        "importance": 0.8,
    }
    result = orion_will._promote_to_spine(new_goal, 0.9, "test msg")
    assert_equals(r, "promotion held by receptivity cap (no task)",
                  result, None)

    # And the hold reason was logged.
    ledger_path = Path(os.environ["ORION_WILL_DIR"]) / "goals.jsonl"
    hold_rows = [json.loads(l) for l in ledger_path.read_text(encoding="utf-8").splitlines()
                 if l and "promotion_held" in l]
    cap_holds = [h for h in hold_rows if h.get("reason") == "receptivity_cap"]
    assert_true(r, "ledger records receptivity_cap hold", len(cap_holds) == 1,
                f"got {len(cap_holds)} cap-hold rows")
    return r


# ──────────────────────────────────────────────────────────────────
# D3 — Intent v2 (hybrid regex + cached fuel)
# ──────────────────────────────────────────────────────────────────

def test_d3_intent_v2_hybrid() -> ScenarioResult:
    r = ScenarioResult(scenario="D3: intent v2 hybrid + cache")
    _reset_state()

    # 1) Regex-clear text: fuel should NOT be called (cost discipline).
    fuel_calls = {"count": 0}

    class _FuelStub:
        @staticmethod
        def get_fuel(prompt, interface="cli", max_turns=15):
            fuel_calls["count"] += 1
            return ("[]", "fake")

    sys.modules["orion_fuel"] = _FuelStub  # type: ignore[assignment]

    explicit = "I should call my grandmother this weekend"
    intents = orion_will._extract_intents_v2(explicit)
    assert_true(r, "regex catches explicit 'I should' intent",
                len(intents) >= 1, f"got {intents}")
    assert_equals(r, "regex-only path skips fuel", fuel_calls["count"], 0)

    # 2) Regex-empty text: fuel IS called, returns a structured intent.
    def _fuel_with_intent(prompt, interface="cli", max_turns=15):
        fuel_calls["count"] += 1
        # Tolerant parser: wrap in some preamble to prove it's stripped.
        return ('Here is the output:\n'
                '[{"kind": "long_term", '
                '"description": "look into learning rust someday", '
                '"importance": 0.4}]\nDone.',
                "fake")
    _FuelStub.get_fuel = staticmethod(_fuel_with_intent)  # type: ignore[attr-defined]

    implicit = ("Been thinking maybe one of these years it'd be cool to "
                "pick up something low-level — maybe Rust or so, who knows.")
    intents = orion_will._extract_intents_v2(implicit)
    assert_equals(r, "fuel called once for regex-empty text",
                  fuel_calls["count"], 1)
    assert_true(r, "fuel-extracted intent surfaces in result",
                any("rust" in (i["description"].lower()) for i in intents),
                f"got {intents}")

    # 3) Cache hit on identical text: no new fuel call.
    intents_again = orion_will._extract_intents_v2(implicit)
    assert_equals(r, "second call hits cache (no extra fuel)",
                  fuel_calls["count"], 1)
    assert_true(r, "cached intents have the same kind+description",
                {(i["kind"], i["description"]) for i in intents_again}
                == {(i["kind"], i["description"]) for i in intents})

    # 4) Cache survives module-level eviction (persistence round-trip).
    cache_file = Path(os.environ["ORION_WILL_DIR"]) / "intent_cache.json"
    assert_true(r, "cache persisted to disk", cache_file.exists())
    on_disk = json.loads(cache_file.read_text(encoding="utf-8"))
    assert_true(r, "disk cache has one entry", len(on_disk) == 1,
                f"got {len(on_disk)} entries")

    # 5) Tolerant parser drops bad fuel replies.
    bad_intents = orion_will._parse_fuel_intents("not even close to JSON", "src")
    assert_equals(r, "garbage reply yields []", bad_intents, [])
    junk_intents = orion_will._parse_fuel_intents(
        '[{"kind": "not_a_kind", "description": "x"}]', "src")
    assert_equals(r, "unknown kind dropped", junk_intents, [])

    return r


# ──────────────────────────────────────────────────────────────────
# D4 — Evidence-weighted decay
# ──────────────────────────────────────────────────────────────────

def test_d4_evidence_weighted_decay() -> ScenarioResult:
    r = ScenarioResult(scenario="D4: evidence-weighted per-kind half-life")
    _reset_state()

    now = time.time()
    # No evidence → falls back to the default constant.
    hl_default = orion_will._kind_half_life_days("reminder", now=now)
    assert_true(r, "no-evidence half-life = default",
                abs(hl_default - orion_will.GOAL_DECAY_HALF_LIFE_DAYS) < 0.01,
                f"got {hl_default}")

    # Seed 4 engaged outcomes for kind=reminder. With the goal in the
    # active set so _outcome_kind() can recover the kind.
    orion_will._active_goals["g_r01"] = {
        "goal_id": "g_r01", "kind": "reminder",
        "description": "engaged-reminder",
    }
    for i in range(4):
        orion_will._append_ledger({
            "phase": "outcome", "goal_id": "g_r01",
            "outcome": "engaged", "ts": now - i * 3600,
        })

    hl_slow = orion_will._kind_half_life_days("reminder", now=now + 1)
    assert_true(r, "all-engaged kind decays SLOW (== WILL_KIND_DECAY_SLOW_DAYS)",
                abs(hl_slow - orion_will.WILL_KIND_DECAY_SLOW_DAYS) < 0.01,
                f"got {hl_slow}")

    # Seed 4 deferred outcomes for kind=lapsed.
    orion_will._active_goals["g_l01"] = {
        "goal_id": "g_l01", "kind": "lapsed",
        "description": "deferred-lapsed",
    }
    for i in range(4):
        orion_will._append_ledger({
            "phase": "outcome", "goal_id": "g_l01",
            "outcome": "deferred", "ts": now - i * 3600,
        })

    hl_fast = orion_will._kind_half_life_days("lapsed", now=now + 1)
    assert_true(r, "all-deferred kind decays FAST (== WILL_KIND_DECAY_FAST_DAYS)",
                abs(hl_fast - orion_will.WILL_KIND_DECAY_FAST_DAYS) < 0.01,
                f"got {hl_fast}")

    # And the per-kind half-life threads into _utility: an old reminder
    # stays valuable, an old lapsed-goal does not.
    old_reminder = {"kind": "reminder", "importance": 0.8,
                    "formed_at": now - 10 * 86400}
    old_lapsed = {"kind": "lapsed", "importance": 0.8,
                  "formed_at": now - 10 * 86400}
    # Both go through _utility; we only care about ordering since the
    # context/feasibility heuristics depend on env state we don't control.
    u_r = orion_will._utility(old_reminder, now)
    u_l = orion_will._utility(old_lapsed, now)
    assert_true(r, "older lapsed has lower utility than older reminder",
                u_r > u_l, f"u_reminder={u_r:.3f} u_lapsed={u_l:.3f}")
    return r


# ──────────────────────────────────────────────────────────────────
# D5 — Impact-weighted selection
# ──────────────────────────────────────────────────────────────────

def test_d5_impact_weighted_selection() -> ScenarioResult:
    r = ScenarioResult(scenario="D5: impact-weighted goal interplay")
    _reset_state()

    reminder = {"kind": "reminder"}
    long_term = {"kind": "long_term"}
    subgoal = {"kind": "self_action", "parent_goal_id": "g_parent01"}
    unknown = {"kind": "??unmapped??"}

    assert_true(r, "reminder is the lowest-impact kind",
                orion_will._impact_cost(reminder) < orion_will._impact_cost(long_term))
    assert_true(r, "subgoal bumps base impact",
                orion_will._impact_cost(subgoal)
                > orion_will._impact_cost({"kind": "self_action"}))
    assert_equals(r, "unknown kind uses default",
                  orion_will._impact_cost(unknown),
                  orion_will.WILL_KIND_IMPACT_DEFAULT)

    # And tied utility → lower-impact wins after the impact-weighted sort.
    cands = [
        (0.7, {"kind": "long_term", "goal_id": "g_lt", "importance": 0.7}),
        (0.7, {"kind": "reminder", "goal_id": "g_rm", "importance": 0.7}),
    ]
    cands.sort(key=lambda x: -(x[0] * (1.0 - orion_will._impact_cost(x[1]))))
    assert_equals(r, "reminder wins tied utility",
                  cands[0][1]["goal_id"], "g_rm")
    return r


# ──────────────────────────────────────────────────────────────────

SCENARIOS = [
    test_d1_hierarchical_decomposition,
    test_d2_meta_calibration,
    test_d3_intent_v2_hybrid,
    test_d4_evidence_weighted_decay,
    test_d5_impact_weighted_selection,
]


if __name__ == "__main__":
    sys.exit(run_suite("orion_will build #4", SCENARIOS))
