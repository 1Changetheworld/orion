"""tests for orion_vessel — the canonical identity keystone.

Per ORION BUILD RESUME (6-1-2026) §5.1. The vessel enforces "one brain":
every body-instance must bind the SAME pinned self, and a host that
cannot verify the canonical brain runs read-only + queues rather than
silently minting a divergent self.

Coverage:
  - unpinned host is read-only (no silent authority).
  - pinning THIS host makes it canonical with writes allowed.
  - a host's own signed whoami is self-consistent and binds to its pin.
  - a DIFFERENT but cryptographically authentic self is classified as a
    FORK (refused + logged), not silently trusted.
  - a tampered descriptor is classified INVALID.
  - a non-canonical host with no reachable endpoint is ORPHAN (read-only),
    queues writes, and flushes them on demand.
  - a non-canonical host whose endpoint verifies to the pin is BOUND.
  - adopt requires explicit confirmation and a verifiable descriptor.
  - pin refuses to silently re-anoint a different brain without force.

All tests use a tempdir ORION_BRAIN_DIR; real ~/.orion is untouched.
The "fork" identity is minted with an independent Ed25519 key so we test
the real cryptographic path, not a mock.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import uuid

from tests._harness import ScenarioResult, assert_equals, assert_true, run_suite


def _fresh():
    """Fresh ORION_BRAIN_DIR + reimport vessel/identity/federation so
    their module-level paths bind to the tempdir. Returns the vessel
    module."""
    td = tempfile.mkdtemp(prefix="orion-vessel-test-")
    os.environ["ORION_BRAIN_DIR"] = td
    for mod in ("orion_vessel", "orion_identity", "orion_federation"):
        sys.modules.pop(mod, None)
    import orion_vessel as vessel
    return vessel


def _foreign_descriptor(host_id: str = "ghost",
                        instance_id: str = None,
                        ts: float = 1000.0) -> dict:
    """Mint an independent, cryptographically authentic whoami descriptor
    using a brand-new Ed25519 key. It is a real, signed 'self' — just not
    the one this host has pinned. This is exactly what a forked brain on
    another box would look like on the wire."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    sk = Ed25519PrivateKey.generate()
    pk_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_hex = pk_bytes.hex()
    fp = hashlib.sha256(pk_bytes).hexdigest()[:32]
    body = {
        "instance_id": instance_id or uuid.uuid4().hex,
        "fingerprint": fp,
        "pubkey_hex": pub_hex,
        "host_id": host_id,
        "ts": ts,
        "protocol_version": "1.0",
    }
    body_json = json.dumps(body, sort_keys=True).encode("utf-8")
    body["signature_hex"] = sk.sign(body_json).hex()
    return body


# ─────────────────────────────────────────────────────────

def scenario_unpinned_is_readonly():
    r = ScenarioResult(scenario="unpinned host is read-only (no silent authority)")
    vessel = _fresh()
    assert_true(r, "is_pinned() is False on a fresh host", not vessel.is_pinned())
    st = vessel.binding_status()
    assert_equals(r, "mode is UNPINNED", st["mode"], vessel.MODE_UNPINNED)
    assert_true(r, "writes are NOT allowed", not st["writes_allowed"])
    return r


def scenario_pin_makes_this_host_canonical():
    r = ScenarioResult(scenario="pinning THIS host makes it canonical + writable")
    vessel = _fresh()
    rec = vessel.pin_canonical(pinned_by="test")
    assert_true(r, "pin record has a fingerprint", bool(rec.get("fingerprint")))
    assert_true(r, "is_pinned() True after pin", vessel.is_pinned())
    assert_true(r, "am_i_canonical() True", vessel.am_i_canonical())
    st = vessel.binding_status()
    assert_equals(r, "mode is CANONICAL", st["mode"], vessel.MODE_CANONICAL)
    assert_true(r, "writes allowed on canonical host", st["writes_allowed"])
    return r


def scenario_pin_is_idempotent_but_refuses_reanoint():
    r = ScenarioResult(scenario="pin idempotent for same id, refuses different without force")
    vessel = _fresh()
    rec = vessel.pin_canonical(pinned_by="test")
    again = vessel.pin_canonical(pinned_by="test")  # same local identity
    assert_equals(r, "re-pinning same identity is idempotent",
                  again["fingerprint"], rec["fingerprint"])
    foreign = _foreign_descriptor()
    raised = False
    try:
        vessel.pin_canonical(instance_id=foreign["instance_id"],
                             fingerprint=foreign["fingerprint"],
                             pubkey_hex=foreign["pubkey_hex"])
    except Exception:
        raised = True
    assert_true(r, "refuses to overwrite a different pin without force", raised)
    forced = vessel.pin_canonical(instance_id=foreign["instance_id"],
                                  fingerprint=foreign["fingerprint"],
                                  pubkey_hex=foreign["pubkey_hex"],
                                  force=True)
    assert_equals(r, "force=True re-anoints",
                  forced["fingerprint"], foreign["fingerprint"])
    return r


def scenario_own_whoami_self_consistent_and_binds():
    r = ScenarioResult(scenario="own signed whoami is self-consistent and binds to pin")
    vessel = _fresh()
    vessel.pin_canonical(pinned_by="test")
    desc = vessel.build_whoami_descriptor()
    assert_true(r, "descriptor is signed", bool(desc.get("signature_hex")))
    ok, reason = vessel.verify_descriptor_self_consistent(desc)
    assert_true(r, "self-consistent (%s)" % reason, ok)
    bok, breason = vessel.verify_against_pin(desc)
    assert_true(r, "verifies against own pin (%s)" % breason, bok)
    assert_equals(r, "classify_endpoint -> MATCH",
                  vessel.classify_endpoint(desc), vessel.BIND_MATCH)
    return r


def scenario_fork_is_detected_not_trusted():
    r = ScenarioResult(scenario="a secondary meeting a DIFFERENT self refuses to bind (FORK)")
    vessel = _fresh()
    # This host is a secondary: it has adopted the real canonical brain.
    canonical = _foreign_descriptor(host_id="the-real-command")
    vessel.adopt(canonical, confirm=True)
    assert_true(r, "secondary is not itself canonical", not vessel.am_i_canonical())
    # On the wire it now meets a DIFFERENT, also-authentic self.
    rogue = _foreign_descriptor(host_id="rogue-box")
    ok, _ = vessel.verify_descriptor_self_consistent(rogue)
    assert_true(r, "rogue descriptor is self-consistent (authentic)", ok)
    # ...but it is NOT our pinned canonical self → fork.
    assert_equals(r, "classify_endpoint -> FORK",
                  vessel.classify_endpoint(rogue), vessel.BIND_FORK)
    bok, _ = vessel.verify_against_pin(rogue)
    assert_true(r, "rogue does NOT verify against our pin", not bok)
    st = vessel.binding_status(endpoint_desc=rogue)
    assert_equals(r, "binding mode is ORPHAN (refused to bind fork)",
                  st["mode"], vessel.MODE_ORPHAN)
    assert_true(r, "writes blocked when facing a fork", not st["writes_allowed"])
    assert_true(r, "fork was logged", len(vessel.list_forks()) >= 1)
    return r


def scenario_tampered_descriptor_is_invalid():
    r = ScenarioResult(scenario="tampered descriptor is classified INVALID")
    vessel = _fresh()
    vessel.pin_canonical(pinned_by="test")
    desc = vessel.build_whoami_descriptor()
    bad = dict(desc)
    sig = bad["signature_hex"]
    bad["signature_hex"] = ("00" if sig[:2] != "00" else "11") + sig[2:]
    ok, _ = vessel.verify_descriptor_self_consistent(bad)
    assert_true(r, "tampered descriptor fails self-consistency", not ok)
    assert_equals(r, "classify_endpoint -> INVALID",
                  vessel.classify_endpoint(bad), vessel.BIND_INVALID)
    return r


def scenario_orphan_queues_and_flushes():
    r = ScenarioResult(scenario="non-canonical host with no endpoint is ORPHAN; queues+flushes")
    vessel = _fresh()
    foreign = _foreign_descriptor(host_id="the-real-command")
    vessel.adopt(foreign, confirm=True)  # this host adopts a remote canonical
    assert_true(r, "not canonical after adopting a remote identity",
                not vessel.am_i_canonical())
    st = vessel.binding_status()  # no endpoint reachable
    assert_equals(r, "mode is ORPHAN", st["mode"], vessel.MODE_ORPHAN)
    assert_true(r, "writes blocked in orphan mode", not st["writes_allowed"])
    # Queue two writes; flush with a sender that accepts only the first.
    vessel.queue_write({"tool": "orion_memorize", "arguments": {"content": "A"}})
    vessel.queue_write({"tool": "orion_memorize", "arguments": {"content": "B"}})
    assert_equals(r, "two writes queued", len(vessel.pending_writes()), 2)

    def sender(op):
        return op.get("arguments", {}).get("content") == "A"

    res = vessel.flush_queue(sender)
    assert_equals(r, "one flushed", res["flushed"], 1)
    assert_equals(r, "one remains", res["remaining"], 1)
    assert_equals(r, "queue file now holds the undelivered op",
                  len(vessel.pending_writes()), 1)
    return r


def scenario_bound_when_endpoint_matches_pin():
    r = ScenarioResult(scenario="non-canonical host BOUND when endpoint verifies to pin")
    vessel = _fresh()
    foreign = _foreign_descriptor(host_id="the-real-command")
    vessel.adopt(foreign, confirm=True)
    st = vessel.binding_status(endpoint_desc=foreign)
    assert_equals(r, "endpoint classified MATCH", st["endpoint"], vessel.BIND_MATCH)
    assert_equals(r, "mode is BOUND", st["mode"], vessel.MODE_BOUND)
    assert_true(r, "writes allowed once bound to canonical", st["writes_allowed"])
    return r


def scenario_adopt_requires_confirm_and_validity():
    r = ScenarioResult(scenario="adopt requires confirm=True and a verifiable descriptor")
    vessel = _fresh()
    foreign = _foreign_descriptor()
    raised = False
    try:
        vessel.adopt(foreign, confirm=False)
    except PermissionError:
        raised = True
    assert_true(r, "adopt without confirm raises PermissionError", raised)
    # Tampered descriptor cannot be adopted even with confirm.
    bad = dict(foreign)
    sig = bad["signature_hex"]
    bad["signature_hex"] = ("00" if sig[:2] != "00" else "11") + sig[2:]
    raised2 = False
    try:
        vessel.adopt(bad, confirm=True)
    except ValueError:
        raised2 = True
    assert_true(r, "adopting a tampered descriptor raises ValueError", raised2)
    assert_true(r, "still unpinned after failed adopts", not vessel.is_pinned())
    return r


SCENARIOS = [
    scenario_unpinned_is_readonly,
    scenario_pin_makes_this_host_canonical,
    scenario_pin_is_idempotent_but_refuses_reanoint,
    scenario_own_whoami_self_consistent_and_binds,
    scenario_fork_is_detected_not_trusted,
    scenario_tampered_descriptor_is_invalid,
    scenario_orphan_queues_and_flushes,
    scenario_bound_when_endpoint_matches_pin,
    scenario_adopt_requires_confirm_and_validity,
]


if __name__ == "__main__":
    raise SystemExit(run_suite("VESSEL — CANONICAL IDENTITY", SCENARIOS))
