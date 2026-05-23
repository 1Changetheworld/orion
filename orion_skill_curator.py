"""orion_skill_curator.py — the Library-Drift ratchet for learned skills.

The hermes self-improvement loop edits skills as they're used; this module is
the GOVERNOR that keeps the active set from rotting under that loop. It is
build #2 of the next-3 roadmap, the C2 combination from
docs/architecture/synthesis-continual-learning.md:

    "A skill library that provably cannot rot — hermes gives the missing
    improvement loop; the ratchet gives the loop the governance hermes
    itself lacks."

WHAT THIS LAYER DOES
====================
Nightly (from inside orion_dream._run_dream_cycle, the same cadence that
consolidates playbooks and memory), call `curate()`. It walks every active
skill in orion_memory's store and applies three rules in order:

  1. RETIRE LOW CONTRIBUTORS — any skill with times_used >= N_MIN whose
     contribution score falls below TAU_RETIRE gets archived. Archive,
     not delete; orion_memory.restore_skill reverses it if eviction
     proves premature.

  2. BOUND THE ACTIVE SET — if more than ACTIVE_CAP skills are still
     active, archive the lowest-contributors until we are at cap.
     The cap exists because an unbounded library that grows on every
     success will eventually contain skills whose triggers overlap
     with newer, better skills' triggers, and the routing layer's
     conflict-resolution becomes the bottleneck. Library-Drift in the
     wild.

  3. PUBLISH THE TRIPWIRE — the mean contribution over experienced
     skills is published on `brain.skills.mean_contribution`. The
     continual-learning memo names this as the SINGLE LAUNCH TRIPWIRE:
     a rising or flat line means the library is learning; a falling
     line means it is rotting, and we catch the rot BEFORE any
     end-task metric moves.

The verdict source is orion_memory.on_skill_fired(name, verdict ∈
{helped, hurt, neutral}). Callers — the executive's outcome close,
the metacog ledger, or any agent that fires a learned skill — call
that function with the verdict; the contribution score updates on
write. The curator then reads what they wrote.

DESIGN LAW (#3 — reuse the core)
================================
The curator does NOT have its own ledger, its own loop, or its own
NATS subscriber. It is a pure function called from the dream cycle.
That means a) you can unit-test it without any infrastructure, and
b) if the dream is down, the ratchet is paused but the library is
not corrupted — exactly the failure mode you want.
"""
from __future__ import annotations

import os
import time
from typing import Optional

# Defaults from the synthesis memo. Tunable via env without code changes so
# we can probe the ratchet's behavior on real traffic without redeploying.
ACTIVE_CAP = int(os.environ.get("ORION_SKILL_ACTIVE_CAP", "50"))
TAU_RETIRE = float(os.environ.get("ORION_SKILL_TAU_RETIRE", "-0.2"))
N_MIN = int(os.environ.get("ORION_SKILL_N_MIN", "5"))

# Verdict-tagging policy when the caller doesn't supply one explicitly.
# Outcome strings here mirror orion_metacognition.OUTCOME_VALUE so the
# executive can feed its own outcome row through tag_outcome() without
# translation. 'ignored'/'denied' are 'neutral' — the skill didn't run
# its course; counting it as hurt would punish the skill for our gate.
_OUTCOME_TO_VERDICT = {
    "succeeded": "helped",
    "success": "helped",
    "failed": "hurt",
    "failure": "hurt",
    "error": "hurt",
    "ignored": "neutral",
    "denied": "neutral",
    "skipped": "neutral",
}


def tag_outcome(outcome: str) -> str:
    """Map a generic outcome string to a skill verdict. Same-fuel-as-fix
    tagging is honest only when an outcome is unambiguous; everything else
    becomes 'neutral' so a noisy outcome doesn't drag a contribution score
    around unfairly. Keep this dictionary tiny on purpose — it is the
    governance interface, not a parser."""
    return _OUTCOME_TO_VERDICT.get((outcome or "").lower(), "neutral")


def _publish(subject: str, payload: dict) -> None:
    """Best-effort substrate publish; the curator must never raise out of the
    dream cycle just because NATS is down. The published tripwire is the most
    valuable side-effect we have — but a silent log is still useful when the
    substrate is offline (e.g. on FORGE while travelling)."""
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass


def curate(active_cap: int = ACTIVE_CAP,
           tau_retire: float = TAU_RETIRE,
           n_min: int = N_MIN) -> dict:
    """Run the ratchet once. Returns a stats dict for the dream summary.

    Three-step ratchet (synthesis-continual-learning.md C2):
      1. RETIRE on low contribution after N_MIN firings.
      2. CAP at active_cap, evicting lowest-contributors over the line.
      3. PUBLISH brain.skills.mean_contribution (the launch tripwire).

    Conservative by construction: a skill with fewer than N_MIN firings is
    NEVER retired — we don't punish skills we haven't tested. The cap only
    fires on experienced skills too; brand-new skills always survive their
    first N_MIN tries. That keeps the ratchet from eating a skill before it
    has had a chance to prove itself.
    """
    started = time.time()
    try:
        import orion_memory
    except Exception as e:
        return {"ok": False, "error": "orion_memory import failed: %s" % e}

    all_skills = orion_memory.list_skills(active_only=True)
    retired: list[dict] = []
    evicted: list[dict] = []

    # Step 1 — retire low contributors past evidence threshold.
    survivors: list[dict] = []
    for s in all_skills:
        used = int(s.get("times_used", 0))
        contrib = float(s.get("contribution", 0.0))
        if used >= n_min and contrib < tau_retire:
            if orion_memory.archive_skill(
                    s.get("_fname") or s.get("name", ""),
                    reason="contribution %.2f < tau_retire %.2f after %d firings"
                           % (contrib, tau_retire, used)):
                retired.append({"name": s.get("name"), "contribution": contrib,
                                "times_used": used})
                continue
        survivors.append(s)

    # Step 2 — bound the active set; evict lowest contributors over the cap.
    # Only EXPERIENCED skills (>= n_min firings) are eligible for eviction;
    # we don't pre-emptively kill a brand-new skill just because the cap is
    # tight. If the cap is breached but every survivor is under-tested,
    # we accept the temporary overshoot — the next cycle catches it once
    # firings accumulate.
    if len(survivors) > active_cap:
        experienced = [s for s in survivors if int(s.get("times_used", 0)) >= n_min]
        experienced.sort(key=lambda s: float(s.get("contribution", 0.0)))
        overshoot = len(survivors) - active_cap
        for s in experienced[:overshoot]:
            if orion_memory.archive_skill(
                    s.get("_fname") or s.get("name", ""),
                    reason="over active_cap (%d), lowest contribution %.2f"
                           % (active_cap, float(s.get("contribution", 0.0)))):
                evicted.append({"name": s.get("name"),
                                "contribution": float(s.get("contribution", 0.0))})
                survivors.remove(s)

    # Step 3 — the launch tripwire. Mean over EXPERIENCED skills only; an
    # untested skill's 0.0 would dilute the signal and mask actual rot.
    experienced_survivors = [s for s in survivors if int(s.get("times_used", 0)) >= n_min]
    if experienced_survivors:
        mean_contrib = round(
            sum(float(s.get("contribution", 0.0)) for s in experienced_survivors)
            / len(experienced_survivors), 4)
    else:
        mean_contrib = None  # no experienced skills yet — nothing to report

    summary = {
        "ts": time.time(),
        "duration_sec": round(time.time() - started, 3),
        "active_before": len(all_skills),
        "active_after": len(survivors),
        "retired": retired,
        "evicted_over_cap": evicted,
        "mean_contribution": mean_contrib,
        "experienced_count": len(experienced_survivors),
        "config": {"active_cap": active_cap, "tau_retire": tau_retire,
                   "n_min": n_min},
    }
    _publish("brain.skills.mean_contribution", summary)
    return summary


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(curate(), indent=2, default=str))
