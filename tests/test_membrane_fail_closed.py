"""tests for orion_membrane fail-closed behavior on the mesh path.

Terminal-5 hardening (frontier-self-model + membrane-research §4e):
the membrane MUST never get less strict. Specifically:

  - the gossip _filtered_for_mesh helper must drop the manifest when
    membrane import/filter raises (not pass it through);
  - the substrate publish hook must drop cross-host publishes when
    membrane import/decision raises (localhost subjects remain fail-open
    so cognition-internal traffic still flows during a membrane outage);
  - the content-hash blacklist must drop entries whose hash matches a
    user-revoked one even when their tags would otherwise allow them.

These tests use a tempdir for ORION_BRAIN_DIR so we touch real ~/.orion
zero times. They are pure-function tests — no NATS, no live brain.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from tests._harness import ScenarioResult, assert_equals, assert_true, run_suite


def _with_tempdir(fn):
    """Run fn with ORION_BRAIN_DIR pointing at a fresh tempdir; restore on exit."""
    prior = os.environ.get("ORION_BRAIN_DIR")
    with tempfile.TemporaryDirectory(prefix="orion-membrane-test-") as td:
        os.environ["ORION_BRAIN_DIR"] = td
        # Force module-level paths to repick up the env var.
        for mod in ("orion_membrane", "orion_gossip"):
            sys.modules.pop(mod, None)
        try:
            return fn(td)
        finally:
            if prior is None:
                os.environ.pop("ORION_BRAIN_DIR", None)
            else:
                os.environ["ORION_BRAIN_DIR"] = prior
            for mod in ("orion_membrane", "orion_gossip"):
                sys.modules.pop(mod, None)


def scenario_blacklist_blocks_matching_hash():
    r = ScenarioResult(scenario="blacklist drops outbound entry by content_hash")

    def body(_td):
        import orion_membrane as m
        m.blacklist_hash("deadbeefcafe", reason="user revoke")
        assert_true(r, "blacklisted hash returns True",
                    m.egress_hash_blocked("deadbeefcafe"))
        assert_true(r, "non-blacklisted hash returns False",
                    not m.egress_hash_blocked("0123456789ab"))
        assert_true(r, "empty hash returns False",
                    not m.egress_hash_blocked(""))
    _with_tempdir(body)
    return r


def scenario_gossip_filter_fail_closed_on_membrane_crash():
    r = ScenarioResult(
        scenario="gossip _filtered_for_mesh drops manifest when filter raises")

    def body(_td):
        import orion_gossip as g
        # Monkey-patch membrane.filter_manifest to raise; the gossip
        # helper must return {} rather than ship the unfiltered snapshot.
        import orion_membrane as m

        def boom(*a, **kw):
            raise RuntimeError("membrane offline")
        original = m.filter_manifest
        m.filter_manifest = boom
        try:
            entries = {"node-1": {"tags": ["visibility:mesh"], "content_hash": "abc"}}
            out = g._filtered_for_mesh(entries)
            assert_equals(r, "manifest dropped on filter crash", out, {})
        finally:
            m.filter_manifest = original
    _with_tempdir(body)
    return r


def scenario_gossip_filter_drops_blacklisted_entry():
    r = ScenarioResult(
        scenario="gossip _filtered_for_mesh applies hash blacklist")

    def body(_td):
        import orion_membrane as m
        import orion_gossip as g
        m.blacklist_hash("revoked-hash-1234")
        entries = {
            "ok-node": {"tags": ["visibility:mesh"], "content_hash": "fresh-hash"},
            "revoked-node": {"tags": ["visibility:mesh"],
                             "content_hash": "revoked-hash-1234"},
        }
        out = g._filtered_for_mesh(entries)
        assert_true(r, "non-blacklisted entry passes", "ok-node" in out)
        assert_true(r, "blacklisted entry dropped", "revoked-node" not in out)
    _with_tempdir(body)
    return r


def scenario_membrane_filter_drops_local_visibility():
    r = ScenarioResult(scenario="filter_manifest drops visibility:local entries")

    def body(_td):
        import orion_membrane as m
        entries = {
            "share": {"tags": ["visibility:mesh"], "content_hash": "h1"},
            "secret": {"tags": ["visibility:local"], "content_hash": "h2"},
        }
        out = m.filter_manifest(entries, dest_class=m.DEST_MESH)
        assert_true(r, "mesh entry survives", "share" in out)
        assert_true(r, "local entry dropped", "secret" not in out)
    _with_tempdir(body)
    return r


SCENARIOS = [
    scenario_blacklist_blocks_matching_hash,
    scenario_gossip_filter_fail_closed_on_membrane_crash,
    scenario_gossip_filter_drops_blacklisted_entry,
    scenario_membrane_filter_drops_local_visibility,
]


if __name__ == "__main__":
    sys.exit(run_suite("MEMBRANE FAIL-CLOSED", SCENARIOS))
