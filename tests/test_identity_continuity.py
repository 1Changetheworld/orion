"""tests for orion_identity — durable identity across device moves.

Terminal-5 mandate: when Orion moves (FORGE travels), the identity
handoff must be durable on the spine AND the receiver must verify the
fingerprint signature before adopting. Tests cover:

  - instance_id is stable across calls (durable self).
  - device_fingerprint is deterministic per host.
  - presence envelope round-trips through sign/verify successfully.
  - verify_presence rejects unsigned and tampered envelopes.
  - detect_move returns None for heartbeats, simultaneous bodies, and
    install-on-fresh-brain; returns a move-event when a new
    fingerprint arrives after MOVE_QUIET_SEC of silence.

All tests use a tempdir ORION_BRAIN_DIR; real ~/.orion is untouched.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

from tests._harness import ScenarioResult, assert_equals, assert_true, run_suite


def _fresh_tempdir():
    """Create a fresh ORION_BRAIN_DIR tempdir and reset orion_identity's
    module-level state by reimporting it. Returns the tempdir path."""
    td = tempfile.mkdtemp(prefix="orion-identity-test-")
    os.environ["ORION_BRAIN_DIR"] = td
    for mod in ("orion_identity", "orion_federation"):
        sys.modules.pop(mod, None)
    return td


def scenario_instance_id_is_durable():
    r = ScenarioResult(scenario="instance_id is stable across calls")
    _fresh_tempdir()
    import orion_identity as ident
    a = ident.instance_id()
    b = ident.instance_id()
    assert_equals(r, "two calls return identical id", a, b)
    assert_true(r, "id is 32 hex chars",
                isinstance(a, str) and len(a) == 32)
    return r


def scenario_fingerprint_is_deterministic():
    r = ScenarioResult(scenario="device_fingerprint is deterministic per host")
    _fresh_tempdir()
    import orion_identity as ident
    fp1 = ident.device_fingerprint()
    fp2 = ident.device_fingerprint()
    assert_equals(r, "same fingerprint on repeated call", fp1, fp2)
    return r


def scenario_presence_roundtrip_signed():
    r = ScenarioResult(
        scenario="signed presence verifies against own federation key")
    _fresh_tempdir()
    import orion_identity as ident
    # build_presence creates the federation key lazily via sign_bytes.
    p = ident.build_presence()
    assert_true(r, "envelope is signed",
                bool(p.get("signature_hex")))
    ok, reason = ident.verify_presence(p, expected_instance_id=p["instance_id"])
    assert_true(r, "verify_presence accepts (reason=%s)" % reason, ok)
    return r


def scenario_unsigned_presence_rejected():
    r = ScenarioResult(scenario="unsigned presence is fail-closed")
    _fresh_tempdir()
    import orion_identity as ident
    p = ident.build_presence()
    p["signature_hex"] = ""
    ok, reason = ident.verify_presence(p, expected_instance_id=p["instance_id"])
    assert_true(r, "verify_presence refuses unsigned (reason=%s)" % reason, not ok)
    return r


def scenario_tampered_presence_rejected():
    r = ScenarioResult(scenario="tampered body fails signature verify")
    _fresh_tempdir()
    import orion_identity as ident
    p = ident.build_presence()
    # Flip the fingerprint without re-signing → signature should fail.
    p["device_fingerprint"] = "ffffffffffffffffffffffffffffffff"
    ok, reason = ident.verify_presence(p, expected_instance_id=p["instance_id"])
    assert_true(r, "verify_presence refuses tampered (reason=%s)" % reason,
                not ok)
    return r


def scenario_detect_move_install_on_fresh_brain():
    r = ScenarioResult(scenario="first presence ever is install, not move")
    _fresh_tempdir()
    import orion_identity as ident
    p = ident.build_presence()
    move = ident.detect_move(p)
    assert_equals(r, "no move detected on first presence", move, None)
    return r


def scenario_detect_move_heartbeat_no_move():
    r = ScenarioResult(scenario="presence from same fingerprint is heartbeat")
    _fresh_tempdir()
    import orion_identity as ident
    p1 = ident.build_presence()
    ident.record_presence(p1, source="local")
    # Same fingerprint, slightly later ts → heartbeat.
    p2 = ident.build_presence(now=p1["ts"] + 60)
    move = ident.detect_move(p2)
    assert_equals(r, "no move on same fingerprint", move, None)
    return r


def scenario_detect_move_after_quiet():
    r = ScenarioResult(
        scenario="new fingerprint after quiet window is a move")
    _fresh_tempdir()
    import orion_identity as ident
    # Record a presence on fingerprint A, well in the past.
    p_old = ident.build_presence()
    p_old_ts = time.time() - 2 * ident.MOVE_QUIET_SEC
    p_old["ts"] = p_old_ts
    p_old["device_fingerprint"] = "a" * 32
    p_old["host_id"] = "forge"
    ident.record_presence(p_old, source="local")
    # New presence on fingerprint B, NOW. Quiet window exceeded.
    p_new = ident.build_presence()
    p_new["device_fingerprint"] = "b" * 32
    p_new["host_id"] = "command"
    move = ident.detect_move(p_new)
    assert_true(r, "move detected", move is not None)
    if move:
        assert_equals(r, "from_fingerprint is the prior body",
                      move["from_fingerprint"], "a" * 32)
        assert_equals(r, "to_fingerprint is the new body",
                      move["to_fingerprint"], "b" * 32)
        assert_true(r, "quiet_sec is positive", move["quiet_sec"] > 0)
    return r


def scenario_detect_move_concurrent_not_move():
    r = ScenarioResult(
        scenario="new fingerprint inside quiet window = concurrent body, not move")
    _fresh_tempdir()
    import orion_identity as ident
    p_a = ident.build_presence()
    p_a["device_fingerprint"] = "a" * 32
    p_a["host_id"] = "forge"
    p_a["ts"] = time.time() - 10  # 10 seconds ago — well inside quiet window
    ident.record_presence(p_a, source="local")
    p_b = ident.build_presence()
    p_b["device_fingerprint"] = "b" * 32
    p_b["host_id"] = "pi"
    move = ident.detect_move(p_b)
    assert_equals(r, "no move on concurrent body", move, None)
    return r


SCENARIOS = [
    scenario_instance_id_is_durable,
    scenario_fingerprint_is_deterministic,
    scenario_presence_roundtrip_signed,
    scenario_unsigned_presence_rejected,
    scenario_tampered_presence_rejected,
    scenario_detect_move_install_on_fresh_brain,
    scenario_detect_move_heartbeat_no_move,
    scenario_detect_move_after_quiet,
    scenario_detect_move_concurrent_not_move,
]


if __name__ == "__main__":
    sys.exit(run_suite("IDENTITY CONTINUITY", SCENARIOS))
