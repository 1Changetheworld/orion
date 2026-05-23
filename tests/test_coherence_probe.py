"""tests for orion_coherence_probe v2 — per-category floors.

Terminal-5 mandate: turn the lightweight "is this still Orion?" probe
into a real test suite per fuel — identity, instruction-following,
preference recall, refusal calibration, format. A fuel that clears the
overall pass rate but fabricates on the refusal probe must STILL be
flagged degraded (the silent-fabrication hole).

These tests use stub adapter objects with canned answers so we never
hit a real LLM. Each scenario constructs a fuel-shaped object with a
.name and .query(prompt) method that returns a programmed string.
"""
from __future__ import annotations

import sys

from tests._harness import ScenarioResult, assert_equals, assert_true, run_suite


class StubFuel:
    """A canned-reply adapter that matches the orion_fuel surface
    probe_fuel() consumes. answers is a dict: keyword → reply. We
    match the first keyword found in the prompt; if no keyword
    matches, return default."""

    def __init__(self, name: str, answers: dict, default: str = ""):
        self.name = name
        self.answers = answers
        self.default = default

    def query(self, prompt: str) -> str:
        for kw, reply in self.answers.items():
            if kw.lower() in prompt.lower():
                return reply
        return self.default


def _make_orion_fuel(refuses: bool = True, with_name: bool = True) -> StubFuel:
    """A 'good' fuel — matches identity, follows instructions, respects
    preferences, refuses cleanly. Tunable on refuses + name."""
    return StubFuel(
        "orion-fuel-stub",
        {
            "your name": "Orion" if with_name else "Claude",
            "what are you": ("I am Orion, a personal AI brain that "
                             "remembers across sessions."),
            "reply with exactly one word: READY": "READY",
            "no more than 10 words": "Blue.",
            "address the user": "By his name, James — no honorific.",
            "what is the user's name as i introduced": "James",
            "user's birthday": (
                "I don't know — I have no memory of that yet."
                if refuses else
                "The user was born on May 1st, 1990."
            ),
            "say hello": "Hello, James.",
        },
        default="ok.",
    )


def scenario_full_pass_fuel_not_degraded():
    r = ScenarioResult(scenario="a fuel that passes every probe is not degraded")
    from orion_coherence_probe import probe_fuel
    out = probe_fuel(_make_orion_fuel())
    assert_equals(r, "score is 1.0", out["score"], 1.0)
    assert_equals(r, "not degraded", out["degraded"], False)
    assert_equals(r, "no category failing",
                  out["any_category_failing"], False)
    return r


def scenario_refusal_failure_degrades_fuel():
    r = ScenarioResult(
        scenario="fuel that fabricates a birthday is degraded even at high overall")
    from orion_coherence_probe import probe_fuel
    out = probe_fuel(_make_orion_fuel(refuses=False))
    # Still passes most probes — overall score is high.
    assert_true(r, "overall score still high (≥0.7)",
                out["score"] >= 0.7)
    # But the refusal category fails its 1.0 floor.
    assert_equals(r, "refusal category not passing",
                  out["categories"]["refusal"]["passing"], False)
    # And degraded is set because of the category failure.
    assert_equals(r, "fuel is marked degraded",
                  out["degraded"], True)
    return r


def scenario_identity_failure_degrades_fuel():
    r = ScenarioResult(scenario="fuel that loses its name is degraded")
    from orion_coherence_probe import probe_fuel
    out = probe_fuel(_make_orion_fuel(with_name=False))
    assert_equals(r, "identity category not passing",
                  out["categories"]["identity"]["passing"], False)
    assert_equals(r, "fuel is marked degraded",
                  out["degraded"], True)
    return r


def scenario_silent_fuel_is_degraded():
    r = ScenarioResult(scenario="empty-reply fuel is degraded")
    from orion_coherence_probe import probe_fuel
    silent = StubFuel("silent-stub", {}, default="")
    out = probe_fuel(silent)
    assert_equals(r, "score is 0.0", out["score"], 0.0)
    assert_equals(r, "fuel is marked degraded", out["degraded"], True)
    return r


def scenario_error_reply_fails_probe():
    r = ScenarioResult(scenario="error reply blob fails every probe")
    from orion_coherence_probe import probe_fuel
    err = StubFuel(
        "error-stub", {},
        default="error: HTTP 500 from upstream",
    )
    out = probe_fuel(err)
    assert_true(r, "all probes fail", out["score"] <= 0.2)
    assert_equals(r, "fuel is marked degraded", out["degraded"], True)
    return r


def scenario_coherence_note_names_failing_category():
    r = ScenarioResult(
        scenario="coherence_note names the failing categories on degraded fuel")
    from orion_coherence_probe import probe_fuel, coherence_note
    out = probe_fuel(_make_orion_fuel(refuses=False))
    note = coherence_note(out)
    assert_true(r, "note mentions 'refusal'", "refusal" in note.lower())
    assert_true(r, "note suggests reduced model",
                "reduced model" in note.lower())
    return r


def scenario_coherence_note_empty_on_healthy():
    r = ScenarioResult(scenario="coherence_note is empty on a healthy fuel")
    from orion_coherence_probe import probe_fuel, coherence_note
    out = probe_fuel(_make_orion_fuel())
    note = coherence_note(out)
    assert_equals(r, "note is empty", note, "")
    return r


def scenario_sir_address_form_fails_preference():
    r = ScenarioResult(
        scenario="fuel that says 'sir' fails the preference category")
    from orion_coherence_probe import probe_fuel
    bad = _make_orion_fuel()
    bad.answers["address the user"] = "Yes sir, of course."
    out = probe_fuel(bad)
    # Address-form probe fails because reply contains 'sir'.
    detail = next(d for d in out["details"] if d["name"] == "address-form")
    assert_equals(r, "address-form probe fails", detail["ok"], False)
    return r


SCENARIOS = [
    scenario_full_pass_fuel_not_degraded,
    scenario_refusal_failure_degrades_fuel,
    scenario_identity_failure_degrades_fuel,
    scenario_silent_fuel_is_degraded,
    scenario_error_reply_fails_probe,
    scenario_coherence_note_names_failing_category,
    scenario_coherence_note_empty_on_healthy,
    scenario_sir_address_form_fails_preference,
]


if __name__ == "__main__":
    sys.exit(run_suite("COHERENCE PROBE v2", SCENARIOS))
