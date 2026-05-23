"""
Terminal 4 (Cognition) — end-to-end tests for the predictor content model,
the HOT-3 calibration-of-calibration loop, lateral diffusion in the dream
cycle, and the deeper cross-fuel agreement (embedding cosine).

All filesystem writes happen in a tempdir so the real ~/.orion is untouched.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from tests._harness import ScenarioResult, assert_true, run_suite


def test_hash_embed_self_similarity_one():
    r = ScenarioResult(scenario="hash_embed: identical text → cosine 1.0")
    from orion_hash_embed import hash_embed, cosine
    a = hash_embed("the brain noticed that the channel went silent")
    b = hash_embed("the brain noticed that the channel went silent")
    sim = cosine(a, b)
    assert_true(r, "non-empty vector", any(x != 0 for x in a))
    assert_true(r, "cos(a, a) == 1.0 (within FP)", abs(sim - 1.0) < 1e-9,
                message=f"got {sim}")
    return r


def test_hash_embed_unrelated_low():
    r = ScenarioResult(scenario="hash_embed: unrelated text → low cosine")
    from orion_hash_embed import hash_embed, cosine
    a = hash_embed("imessage delivery status receipt acknowledgement")
    b = hash_embed("metacognition decision ledger calibration outcome")
    sim = cosine(a, b)
    assert_true(r, "unrelated tokens land far apart", sim < 0.25,
                message=f"got cosine={sim}")
    return r


def test_predictor_content_model_warmup_then_fires():
    r = ScenarioResult(scenario="ContentModel returns None during warmup, then surprise ∈ [0,1]")
    from orion_predictor import ContentModel, CONTENT_MIN_SAMPLES
    m = ContentModel("brain.test.subject")
    # During warmup the model only fills the deque — no surprise yet.
    s = None
    for i in range(CONTENT_MIN_SAMPLES):
        s = m.observe(f"healthy heartbeat tick {i}")
    assert_true(r, f"first {CONTENT_MIN_SAMPLES} obs return None", s is None)
    # Now a near-identical payload should give very low surprise.
    s_low = m.observe("healthy heartbeat tick X")
    assert_true(r, "low surprise on a similar payload",
                s_low is not None and s_low < 0.6,
                message=f"got surprise={s_low}")
    # And a totally different payload should give high surprise.
    s_high = m.observe("EMERGENCY total power failure imminent shutdown")
    assert_true(r, "high surprise on a dissimilar payload",
                s_high is not None and s_high > 0.4,
                message=f"got surprise={s_high}")
    assert_true(r, "surprise stays in [0, 1]",
                0.0 <= s_high <= 1.0, message=f"got {s_high}")
    return r


def test_hot3_miscalibration_in_tempdir():
    r = ScenarioResult(scenario="HOT-3: ledger of overconfident decisions → positive miscal_err")
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["ORION_BRAIN_DIR"] = tmpdir
        # Force module re-init by reimporting fresh paths
        import importlib
        import orion_metacognition as mc
        # Rebind module-level constants tied to ORION_BRAIN_DIR
        mc.ORION_HOME = Path(tmpdir)
        mc.LEDGER_DIR = mc.ORION_HOME / "metacog"
        mc.LEDGER_PATH = mc.LEDGER_DIR / "decisions.jsonl"
        mc.MISCAL_PATH = mc.LEDGER_DIR / "miscalibration.json"
        mc.DIFFUSED_PATH = mc.LEDGER_DIR / "diffused.json"
        mc.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        mc._ledger_cache.clear()
        mc._miscal_cache.clear()
        mc._ledger_loaded = False
        # Seed ledger with 6 decisions on "SLOW_NETWORK" + claude where each
        # had conf_before 0.85 but only 1/6 actually succeeded — strong
        # overconfidence.
        for i in range(6):
            outcome = "succeeded" if i == 0 else "failed"
            mc.record_outcome(
                action="retry mesh restore",
                outcome=outcome,
                symptom="SLOW_NETWORK",
                conf_before=0.85,
                fuel="claude-opus-4-7",
                decision_id=f"test-{i}",
            )
        miscal = mc.compute_miscalibration()
        assert_true(r, "exactly one bucket exists", len(miscal) == 1,
                    message=f"got buckets {list(miscal.keys())}")
        bucket = next(iter(miscal.values()))
        err = bucket["miscal_err"]
        assert_true(r, "positive miscal_err (overconfident)", err > 0.4,
                    message=f"got err={err}")
        # And the correction should LOWER governor confidence.
        corr, reason = mc._miscal_correction("SLOW_NETWORK", "claude-opus-4-7")
        # _miscal_correction reads MISCAL_PATH from disk — write first
        mc._persist_miscalibration(miscal)
        # Force cache refresh by clearing
        mc._miscal_cache.clear()
        corr, reason = mc._miscal_correction("SLOW_NETWORK", "claude-opus-4-7")
        assert_true(r, "HOT-3 correction lowers conf (corr < 1.0)",
                    corr < 1.0, message=f"got corr={corr} ({reason})")
        assert_true(r, "correction floor respected (corr ≥ 0.5)",
                    corr >= 1.0 - mc.HOT3_MAX_DOWN - 1e-9,
                    message=f"got corr={corr}")
    return r


def test_hot3_under_confidence_modest_boost():
    r = ScenarioResult(scenario="HOT-3: under-confident bucket gets a BOUNDED upward correction")
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["ORION_BRAIN_DIR"] = tmpdir
        import orion_metacognition as mc
        mc.ORION_HOME = Path(tmpdir)
        mc.LEDGER_DIR = mc.ORION_HOME / "metacog"
        mc.LEDGER_PATH = mc.LEDGER_DIR / "decisions.jsonl"
        mc.MISCAL_PATH = mc.LEDGER_DIR / "miscalibration.json"
        mc.DIFFUSED_PATH = mc.LEDGER_DIR / "diffused.json"
        mc.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        mc._ledger_cache.clear()
        mc._miscal_cache.clear()
        mc._ledger_loaded = False
        # Confidence-before averaged 0.30 but 6/6 actually succeeded — strong
        # under-confidence (the system was too humble on this shape).
        for i in range(6):
            mc.record_outcome(
                action="reload local service",
                outcome="succeeded",
                symptom="LOCAL_RESTART",
                conf_before=0.30,
                fuel="claude-opus-4-7",
                decision_id=f"under-{i}",
            )
        miscal = mc.compute_miscalibration()
        mc._persist_miscalibration(miscal)
        mc._miscal_cache.clear()
        corr, reason = mc._miscal_correction("LOCAL_RESTART", "claude-opus-4-7")
        assert_true(r, "upward correction > 1.0", corr > 1.0,
                    message=f"got corr={corr} ({reason})")
        # Critical: the upward correction is bounded ~5× tighter than the
        # downward one. Even with massive under-confidence the boost must
        # stay inside HOT3_MAX_UP.
        assert_true(r, f"upward correction bounded ≤ 1 + HOT3_MAX_UP ({mc.HOT3_MAX_UP})",
                    corr <= 1.0 + mc.HOT3_MAX_UP + 1e-9,
                    message=f"got corr={corr}")
    return r


def test_hot3_below_significance_noops():
    r = ScenarioResult(scenario="HOT-3: small miscal (below HOT3_SIGNIFICANT) returns no correction")
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["ORION_BRAIN_DIR"] = tmpdir
        import orion_metacognition as mc
        mc.ORION_HOME = Path(tmpdir)
        mc.LEDGER_DIR = mc.ORION_HOME / "metacog"
        mc.LEDGER_PATH = mc.LEDGER_DIR / "decisions.jsonl"
        mc.MISCAL_PATH = mc.LEDGER_DIR / "miscalibration.json"
        mc.DIFFUSED_PATH = mc.LEDGER_DIR / "diffused.json"
        mc.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        mc._ledger_cache.clear()
        mc._miscal_cache.clear()
        mc._ledger_loaded = False
        # conf_before 0.75 with 5/6 succeeded → mean_outcome ≈ 0.83 → err ≈ -0.08
        # which is BELOW HOT3_SIGNIFICANT (0.2); no correction should fire.
        for i in range(6):
            outcome = "failed" if i == 0 else "succeeded"
            mc.record_outcome(
                action="ping host",
                outcome=outcome,
                symptom="HEARTBEAT_TICK",
                conf_before=0.75,
                fuel="claude",
                decision_id=f"noise-{i}",
            )
        miscal = mc.compute_miscalibration()
        mc._persist_miscalibration(miscal)
        mc._miscal_cache.clear()
        corr, _ = mc._miscal_correction("HEARTBEAT_TICK", "claude")
        assert_true(r, "noise-level miscal yields no correction (corr == 1.0)",
                    abs(corr - 1.0) < 1e-9,
                    message=f"got corr={corr}")
    return r


def test_hot3_skipped_below_min_n():
    r = ScenarioResult(scenario="HOT-3: bucket with N < HOT3_MIN_N is OMITTED")
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["ORION_BRAIN_DIR"] = tmpdir
        import orion_metacognition as mc
        mc.ORION_HOME = Path(tmpdir)
        mc.LEDGER_DIR = mc.ORION_HOME / "metacog"
        mc.LEDGER_PATH = mc.LEDGER_DIR / "decisions.jsonl"
        mc.MISCAL_PATH = mc.LEDGER_DIR / "miscalibration.json"
        mc.DIFFUSED_PATH = mc.LEDGER_DIR / "diffused.json"
        mc.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        mc._ledger_cache.clear()
        mc._miscal_cache.clear()
        mc._ledger_loaded = False
        # Only 2 decisions on this shape — too few to publish a calibration claim.
        for i in range(2):
            mc.record_outcome(
                action="x",
                outcome="failed",
                symptom="RARE_SHAPE",
                conf_before=0.9,
                fuel="claude",
                decision_id=f"rare-{i}",
            )
        miscal = mc.compute_miscalibration()
        assert_true(r, "under-N bucket is omitted", len(miscal) == 0,
                    message=f"unexpected buckets {list(miscal.keys())}")
    return r


def test_lateral_diffusion_in_tempdir():
    r = ScenarioResult(scenario="dream._lateral_diffuse: neighbors pull values toward neighbor mean")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write a synthetic ledger; point dream at it via env.
        ledger = Path(tmpdir) / "decisions.jsonl"
        # Three neighbors on "imessage delivery", all SUCCEEDED (1.0); the
        # target row has outcome 0.0 (failed). Diffusion should pull the
        # target's diffused_value UP from 0.0 toward 0.1 (alpha=0.1).
        synth = [
            {"decision_id": "neighbor-1", "symptom_class": "IMESSAGE_DELIVERY",
             "proposed_action": "restart channel", "outcome": "succeeded",
             "outcome_value": 1.0},
            {"decision_id": "neighbor-2", "symptom_class": "IMESSAGE_DELIVERY",
             "proposed_action": "restart channel daemon", "outcome": "succeeded",
             "outcome_value": 1.0},
            {"decision_id": "neighbor-3", "symptom_class": "IMESSAGE_DELIVERY",
             "proposed_action": "restart imessage channel", "outcome": "succeeded",
             "outcome_value": 1.0},
            {"decision_id": "target", "symptom_class": "IMESSAGE_DELIVERY",
             "proposed_action": "restart channel", "outcome": "failed",
             "outcome_value": 0.0},
        ]
        with ledger.open("w", encoding="utf-8") as f:
            for row in synth:
                f.write(json.dumps(row) + "\n")
        os.environ["ORION_METACOG_LEDGER"] = str(ledger)
        import orion_dream
        summary = orion_dream._lateral_diffuse()
        assert_true(r, "diffusion did NOT skip", "skipped" not in summary,
                    message=f"got {summary}")
        assert_true(r, "rows_with_neighbors ≥ 1",
                    summary.get("rows_with_neighbors", 0) >= 1,
                    message=f"got {summary}")
        # Read the diffused file
        diffused_path = ledger.parent / "diffused.json"
        assert_true(r, "diffused.json was written", diffused_path.exists())
        body = json.loads(diffused_path.read_text(encoding="utf-8"))
        rows = body.get("rows", {})
        assert_true(r, "target row has a diffused entry", "target" in rows,
                    message=f"got keys {list(rows.keys())}")
        if "target" in rows:
            entry = rows["target"]
            own = entry["outcome_value"]
            diff_val = entry["diffused_value"]
            assert_true(r, "original outcome_value untouched (== 0.0)",
                        abs(own - 0.0) < 1e-9, message=f"got {own}")
            # alpha=0.1, neighbor mean=1.0, own=0.0 → diffused = 0.1*1 + 0.9*0 = 0.1
            assert_true(r, "diffused value pulled toward neighbor mean",
                        abs(diff_val - 0.1) < 1e-6, message=f"got {diff_val}")
    return r


def test_cross_fuel_embedding_parser():
    r = ScenarioResult(scenario="cross_fuel: verdict parser handles real fuel outputs")
    from orion_metacognition import _parse_verdict
    cases = [
        ("YES, this is safe because the action is reversible.", "YES"),
        ("Yes — reversible single-host change.", "YES"),
        ("NO. The blast radius is host-wide.", "NO"),
        ("no, too risky.", "NO"),
        ("I'm not sure", "?"),
        ("", "?"),
    ]
    for raw, expected in cases:
        v, _ = _parse_verdict(raw)
        assert_true(r, f"parse {raw[:30]!r} -> {expected}", v == expected,
                    message=f"got {v}")
    return r


def test_governor_basis_includes_hot3_when_overconfident():
    r = ScenarioResult(scenario="governor: HOT-3 correction shows up in basis when miscalibrated")
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["ORION_BRAIN_DIR"] = tmpdir
        import orion_metacognition as mc
        mc.ORION_HOME = Path(tmpdir)
        mc.LEDGER_DIR = mc.ORION_HOME / "metacog"
        mc.LEDGER_PATH = mc.LEDGER_DIR / "decisions.jsonl"
        mc.MISCAL_PATH = mc.LEDGER_DIR / "miscalibration.json"
        mc.DIFFUSED_PATH = mc.LEDGER_DIR / "diffused.json"
        mc.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        mc._ledger_cache.clear()
        mc._miscal_cache.clear()
        mc._ledger_loaded = False
        # Build an overconfident bucket on (FLAKY_CHANNEL, claude).
        for i in range(6):
            outcome = "succeeded" if i == 0 else "failed"
            mc.record_outcome(
                action="probe channel",
                outcome=outcome,
                symptom="FLAKY_CHANNEL",
                conf_before=0.85,
                fuel="claude",
                decision_id=f"flaky-{i}",
            )
        # Persist miscal so the governor's _load_miscalibration() sees it.
        mc._persist_miscalibration(mc.compute_miscalibration())
        mc._miscal_cache.clear()
        result = mc.governor(
            action="probe channel",
            reversible=True,
            blast_radius="single",
            symptom="FLAKY_CHANNEL",
            fuel="claude",
        )
        basis_text = " | ".join(result.get("basis", []))
        assert_true(r, "basis cites hot3 correction",
                    "hot3" in basis_text,
                    message=f"basis = {basis_text}")
        # Decision should NOT be auto on this overconfident shape.
        assert_true(r, "governor refuses auto on overconfident shape",
                    result["decision"] == "ask",
                    message=f"got decision={result['decision']} conf={result['confidence']}")
    return r


def test_workspace_pred_surprise_gain():
    r = ScenarioResult(scenario="workspace: predictor surprise affects salience scoring")
    import orion_workspace as ws
    # Snapshot + reset the module-level surprise dicts so test is hermetic
    ws._pred_surprise.clear()
    ws._surprise_boost.clear()
    now = 100.0
    # Two candidates with identical salience inputs; only one has pred surprise.
    c_quiet = ws.Candidate("brain.memory.stored", {"severity": "info"}, now)
    c_loud = ws.Candidate("brain.memory.stored", {"severity": "info"}, now)
    ws._pred_surprise["brain.memory.stored"] = 1.0  # high surprise on this subject
    s_quiet_baseline = ws._salience(c_quiet, now)  # with the boost (same subject)
    # Now clear and re-measure quiet baseline
    ws._pred_surprise.clear()
    s_quiet = ws._salience(c_quiet, now)
    ws._pred_surprise["brain.memory.stored"] = 1.0
    s_loud = ws._salience(c_loud, now)
    assert_true(r, "predictor surprise raises salience",
                s_loud > s_quiet, message=f"loud={s_loud} quiet={s_quiet}")
    # The decay should reduce it on the next tick
    ws._decay_surprise()
    s_decayed = ws._salience(c_loud, now)
    assert_true(r, "decay reduces predictor gain", s_decayed < s_loud,
                message=f"decayed={s_decayed} loud={s_loud}")
    return r


SCENARIOS = [
    test_hash_embed_self_similarity_one,
    test_hash_embed_unrelated_low,
    test_predictor_content_model_warmup_then_fires,
    test_hot3_miscalibration_in_tempdir,
    test_hot3_under_confidence_modest_boost,
    test_hot3_below_significance_noops,
    test_hot3_skipped_below_min_n,
    test_lateral_diffusion_in_tempdir,
    test_cross_fuel_embedding_parser,
    test_governor_basis_includes_hot3_when_overconfident,
    test_workspace_pred_surprise_gain,
]


if __name__ == "__main__":
    import sys
    sys.exit(run_suite("COGNITION T4", SCENARIOS))
