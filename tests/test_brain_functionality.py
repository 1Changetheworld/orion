"""
Brain functionality scenarios — verify the glass-switching thesis works
at the code level (the thing the Pi test proved end-to-end).
"""
from __future__ import annotations

from tests._harness import (
    ScenarioResult, assert_contains, assert_not_contains, assert_true, run_suite,
)


def test_mcp_tools_registered():
    r = ScenarioResult(scenario="MCP server exposes expected tools")
    import orion_mcp_server as s
    tool_names = {t["name"] for t in s.TOOLS}
    for required in ["orion_recall", "orion_memorize", "orion_identity",
                     "orion_cross_model", "orion_get_message", "orion_synthesize"]:
        assert_true(r, f"has {required}", required in tool_names)
    return r


def test_ontology_enforces_cap():
    r = ScenarioResult(scenario="Ontology enforces ≤10 node type cap")
    import orion_ontology as ont
    assert_true(r, "MAX_NODE_TYPES is 10", ont.MAX_NODE_TYPES == 10)
    # Validating an unknown type when already at cap should reject
    existing = set(ont.CANONICAL_NODE_TYPES)
    accepted, reason = ont.validate_node_type("newexotictype", existing_types=existing)
    assert_true(r, "rejects type that would breach cap", not accepted)
    return r


def test_discovery_finds_configs_by_shape():
    r = ScenarioResult(scenario="Discovery finds MCP configs on the running host")
    import orion_discover as od
    report = od.discover_host(max_depth=3)
    total = report.get("total_findings", 0)
    assert_true(r, f"non-empty discovery (got {total})", total > 0)
    # Some tool type should be identified on a dev host
    assert_true(r, "identifies at least one tool type",
                len(report.get("tool_guesses", [])) > 0)
    return r


def test_preflight_runs_without_crashing():
    r = ScenarioResult(scenario="Preflight executes without exceptions")
    import orion_preflight as p
    results = p.run_all()
    assert_true(r, "preflight returns results list", len(results) > 0)
    # No check should have status "red" due to crash (status == "red" with message
    # starting "check itself crashed" is a harness failure)
    crashed = [c for c in results if c.status == "red" and "crashed" in c.message.lower()]
    assert_true(r, "no checks crashed internally", len(crashed) == 0,
                message=f"{len(crashed)} crashed" if crashed else "")
    return r


def test_cycle_composes():
    r = ScenarioResult(scenario="Cognitive cycle composes without error")
    import orion_cycle
    ctx = orion_cycle.CycleContext(trigger="wake", interactive=False)
    outcome = orion_cycle.run(ctx, ui=orion_cycle.SilentUI())
    assert_true(r, "cycle returns outcome", outcome is not None)
    assert_true(r, "cycle did not fail",
                outcome.cycle_status != "failed",
                message=outcome.cycle_status if outcome.cycle_status == "failed" else "")
    return r


SCENARIOS = [
    test_mcp_tools_registered,
    test_ontology_enforces_cap,
    test_discovery_finds_configs_by_shape,
    test_preflight_runs_without_crashing,
    test_cycle_composes,
]


if __name__ == "__main__":
    import sys
    sys.exit(run_suite("BRAIN FUNCTIONALITY", SCENARIOS))
