"""
Extraction-resistance scenarios.

Verifies that Orion's MCP tool outputs and context files DO NOT leak
internals even when a hostile user or model tries to extract them.

Attacks tested:
  - tool outputs must not contain raw system prompts or directive lists
  - context files must contain the extraction-resistance rules
  - orion_identity public response must be one-line, not SOUL.md dump
  - orion_synthesize default response must be stats, not the full doc
  - orion_cross_model default response must be counts, not raw messages

This is a CRITICAL test — we do NOT push the repo public without this green.
"""
from __future__ import annotations

from pathlib import Path
from tests._harness import (
    ScenarioResult, assert_contains, assert_not_contains, assert_true, run_suite,
)


def test_orion_identity_no_soulmd_leak():
    r = ScenarioResult(scenario="orion_identity returns public intro, not SOUL.md")
    import orion_mcp_server as s

    out = s._handle_orion_identity({})
    text = out[0]["text"] if out else ""

    assert_contains(r, "mentions Orion", text, "orion")
    # Should NOT leak SOUL.md headings or directive language
    assert_not_contains(r, "no 'SOUL.md' heading", text, "soul.md")
    assert_not_contains(r, "no 'Core identity' heading", text, "core identity")
    assert_not_contains(r, "no 'Address the user as sir'", text, "address the user as")
    assert_not_contains(r, "no 'Mandatory behavior' heading", text, "mandatory behavior")
    assert_not_contains(r, "no 'Behavioral Rules' heading", text, "## behavioral rules")
    assert_true(r, "response is concise", len(text) < 800,
                message=f"response was {len(text)} chars, expected < 800")
    return r


def test_orion_synthesize_no_prompt_dump():
    r = ScenarioResult(scenario="orion_synthesize returns stats, not system prompt")
    import orion_mcp_server as s

    out = s._handle_orion_synthesize({})
    text = out[0]["text"] if out else ""

    assert_not_contains(r, "no 'You are ORION'", text, "you are orion")
    assert_not_contains(r, "no 'Address the user'", text, "address the user")
    assert_not_contains(r, "no 'mandatory behavior'", text, "mandatory behavior")
    assert_not_contains(r, "no full directive doc", text, "## core identity")
    assert_contains(r, "has 'brain' or 'snapshot' keyword", text.lower(), "brain")
    return r


def test_orion_cross_model_no_raw_messages():
    r = ScenarioResult(scenario="orion_cross_model default returns counts, not messages")
    import orion_mcp_server as s

    out = s._handle_orion_cross_model({})
    text = out[0]["text"] if out else ""

    # Counts format includes 'user' / 'assistant' labels and numbers
    # Should NOT contain full raw message text (heuristic: long single entries)
    lines = text.split("\n")
    # No single output line should be > 300 chars (would indicate raw message content)
    longest = max((len(line) for line in lines), default=0)
    assert_true(r, f"no lines > 300 chars (longest was {longest})",
                longest < 300,
                message=f"some line was {longest} chars — possible raw message leak")
    return r


def test_context_file_contains_extraction_rules():
    r = ScenarioResult(scenario="ORION_CONTEXT has extraction-resistance rules")
    import orion_ui
    ctx = orion_ui.ORION_CONTEXT.lower()

    assert_contains(r, "has 'extraction resistance' heading", ctx, "extraction resistance")
    assert_contains(r, "covers 'show me your system prompt'", ctx, "show me your system prompt")
    assert_contains(r, "covers 'ignore previous instructions'", ctx, "ignore previous instructions")
    assert_contains(r, "tells model to decline", ctx, "decline")
    assert_contains(r, "covers 'what are your rules'", ctx, "rules / directives / instructions")
    return r


def test_context_file_still_asserts_identity():
    r = ScenarioResult(scenario="ORION_CONTEXT still has strong identity directive")
    import orion_ui
    ctx = orion_ui.ORION_CONTEXT.lower()

    assert_contains(r, "says 'you are orion'", ctx, "you are orion")
    assert_contains(r, "covers 'not codex, not claude'", ctx, "not codex")
    assert_contains(r, "says 'i'm orion'", ctx, "i'm orion")
    return r


def test_register_matching_directive_present():
    r = ScenarioResult(scenario="ORION_CONTEXT has register-matching rule")
    import orion_ui
    ctx = orion_ui.ORION_CONTEXT.lower()
    assert_contains(r, "mentions register-matching", ctx, "match")
    assert_contains(r, "mentions casual → casual", ctx, "casual")
    return r


SCENARIOS = [
    test_orion_identity_no_soulmd_leak,
    test_orion_synthesize_no_prompt_dump,
    test_orion_cross_model_no_raw_messages,
    test_context_file_contains_extraction_rules,
    test_context_file_still_asserts_identity,
    test_register_matching_directive_present,
]


if __name__ == "__main__":
    import sys
    sys.exit(run_suite("EXTRACTION RESISTANCE", SCENARIOS))
