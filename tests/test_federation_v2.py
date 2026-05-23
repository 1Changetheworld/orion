"""tests for orion_federation v2 — reputation + per-host skill privacy.

Per the Terminal-5 mandate and federation-research.md §1c (Sybil
impossibility): reputation v2 ships only the FIRST-PARTY slice — this
brain's own accumulator over its own encounter history. Cross-brain
attested reputation (ERC-8004) stays deferred to v3.

The privacy guard for skill-gossip across federation membrane is the
defense-in-depth alongside the membrane filter — skills marked private
NEVER cross to a federated peer, and skills with no visibility metadata
fail-closed to STRANGERS while remaining permissive to known peers.

All tests use tempdir ORION_BRAIN_DIR. No NATS, no live brain.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

from tests._harness import ScenarioResult, assert_equals, assert_true, run_suite


def _fresh_tempdir():
    td = tempfile.mkdtemp(prefix="orion-federation-test-")
    os.environ["ORION_BRAIN_DIR"] = td
    for mod in ("orion_federation",):
        sys.modules.pop(mod, None)
    return td


def _record(fed, fingerprint, decision, ts=None):
    """Inline encounter writer that bypasses verify_offer — these tests
    are about the reputation function, not the handshake."""
    import json
    ts = ts if ts is not None else time.time()
    row = {
        "ts": ts,
        "peer_fingerprint": fingerprint,
        "peer_safety_number": "alpha bravo cedar delta ember",
        "peer_claimed_name": "Test",
        "peer_claimed_user": "test_user",
        "decision": decision,
        "note": "",
    }
    fed.ENCOUNTER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with fed.ENCOUNTER_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def scenario_unknown_peer_is_stranger():
    r = ScenarioResult(scenario="a never-seen fingerprint is a stranger")
    _fresh_tempdir()
    import orion_federation as fed
    assert_true(r, "is_stranger=True on unknown fingerprint",
                fed.is_stranger("a" * 64))
    rep = fed.reputation("a" * 64)
    assert_equals(r, "score is 0.0", rep["score"], 0.0)
    assert_equals(r, "peers_count is 0", rep["peers_count"], 0)
    return r


def scenario_one_peer_decision_promotes_from_stranger():
    r = ScenarioResult(scenario="one accepted peer decision graduates from stranger")
    _fresh_tempdir()
    import orion_federation as fed
    fp = "b" * 64
    _record(fed, fp, "peer")
    rep = fed.reputation(fp)
    assert_equals(r, "is_stranger=False", rep["is_stranger"], False)
    assert_true(r, "score is > 0.0", rep["score"] > 0.0)
    assert_equals(r, "peers_count is 1", rep["peers_count"], 1)
    return r


def scenario_separate_decision_lowers_reputation():
    r = ScenarioResult(
        scenario="an explicit 'separate' decision keeps score honest")
    _fresh_tempdir()
    import orion_federation as fed
    fp = "c" * 64
    _record(fed, fp, "peer")  # +0.5
    _record(fed, fp, "separate")  # −0.4 floor
    rep = fed.reputation(fp)
    # Score should be near 0.1 (0.5 - 0.4).
    assert_true(r, "score is between 0.0 and 0.2",
                0.0 <= rep["score"] <= 0.2)
    assert_equals(r, "separate_count is 1", rep["separate_count"], 1)
    return r


def scenario_days_known_boost():
    r = ScenarioResult(scenario="longer-known peers earn time bonus")
    _fresh_tempdir()
    import orion_federation as fed
    fp = "d" * 64
    # First encounter 14 days ago, second now.
    long_ago = time.time() - 14 * 86400
    _record(fed, fp, "peer", ts=long_ago)
    _record(fed, fp, "peer", ts=time.time())
    rep = fed.reputation(fp)
    assert_true(r, "days_known >= 13",
                rep["days_known"] >= 13.0)
    # Score = min(0.8, 0.5*2) + 0.1*(14/7) = 0.8 + 0.2 = 1.0 (capped)
    assert_true(r, "score reaches 1.0 cap", rep["score"] >= 0.9)
    return r


def scenario_private_skill_never_crosses():
    r = ScenarioResult(
        scenario="skill with private=True is blocked from federation")
    _fresh_tempdir()
    import orion_federation as fed
    fp = "e" * 64
    _record(fed, fp, "peer")  # peer is known
    skill = {"fname": "secret_routine", "private": True}
    out = fed.skill_crosses_federation(skill, peer_fingerprint=fp)
    assert_equals(r, "private skill does not cross", out, False)
    return r


def scenario_visibility_local_never_crosses():
    r = ScenarioResult(
        scenario="skill tagged visibility:local is blocked from federation")
    _fresh_tempdir()
    import orion_federation as fed
    fp = "f" * 64
    _record(fed, fp, "peer")  # peer is known
    skill = {"fname": "local_helper", "tags": ["visibility:local"]}
    out = fed.skill_crosses_federation(skill, peer_fingerprint=fp)
    assert_equals(r, "local-tagged skill does not cross", out, False)
    return r


def scenario_no_metadata_fails_closed_to_stranger():
    r = ScenarioResult(
        scenario="skill without visibility metadata is dropped for strangers")
    _fresh_tempdir()
    import orion_federation as fed
    # Stranger fingerprint — no encounter ledger entries.
    skill = {"fname": "untagged_skill"}
    out = fed.skill_crosses_federation(skill, peer_fingerprint="z" * 64)
    assert_equals(r, "untagged skill does not cross to stranger", out, False)
    return r


def scenario_no_metadata_allows_known_peer():
    r = ScenarioResult(
        scenario="skill without visibility metadata DOES cross to known peer")
    _fresh_tempdir()
    import orion_federation as fed
    fp = "g" * 64
    _record(fed, fp, "peer")
    skill = {"fname": "untagged_skill"}
    out = fed.skill_crosses_federation(skill, peer_fingerprint=fp)
    assert_equals(r, "untagged skill crosses to known peer", out, True)
    return r


def scenario_visibility_federation_crosses():
    r = ScenarioResult(
        scenario="skill explicitly tagged visibility:federation crosses to known peer")
    _fresh_tempdir()
    import orion_federation as fed
    fp = "h" * 64
    _record(fed, fp, "peer")
    skill = {"fname": "shared_skill", "tags": ["visibility:federation"]}
    out = fed.skill_crosses_federation(skill, peer_fingerprint=fp)
    assert_equals(r, "federation-tagged skill crosses", out, True)
    return r


def scenario_mesh_tagged_skill_does_not_cross_to_stranger():
    r = ScenarioResult(
        scenario="visibility:mesh skill stays mesh-scoped vs strangers")
    _fresh_tempdir()
    import orion_federation as fed
    skill = {"fname": "mesh_skill", "tags": ["visibility:mesh"]}
    out = fed.skill_crosses_federation(skill, peer_fingerprint="i" * 64)
    assert_equals(r, "mesh skill does not cross to stranger", out, False)
    return r


SCENARIOS = [
    scenario_unknown_peer_is_stranger,
    scenario_one_peer_decision_promotes_from_stranger,
    scenario_separate_decision_lowers_reputation,
    scenario_days_known_boost,
    scenario_private_skill_never_crosses,
    scenario_visibility_local_never_crosses,
    scenario_no_metadata_fails_closed_to_stranger,
    scenario_no_metadata_allows_known_peer,
    scenario_visibility_federation_crosses,
    scenario_mesh_tagged_skill_does_not_cross_to_stranger,
]


if __name__ == "__main__":
    sys.exit(run_suite("FEDERATION v2", SCENARIOS))
