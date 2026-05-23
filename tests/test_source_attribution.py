"""tests for score_recall provenance — the source-attribution contract.

Per frontier-self-model.md §O1 and the Terminal-5 mandate:
  > Every brain.recall.response includes the node_ids the answer was
  > derived from. A claim with no provenance is a hallucination by
  > definition.

score_recall(query, candidates) must return a stable `provenance` list
on EVERY exit path (answer, hedge, refuse, no-candidates). The list is
the node_ids consulted, ranked by retrieval score, top→bottom. Empty
provenance means the gate had nothing to look at — refuse without
hallucinating data the system never saw.
"""
from __future__ import annotations

import sys
import time

from tests._harness import ScenarioResult, assert_equals, assert_true, run_suite


def _node(nid, content, *, conf=0.9, src=0.9,
          last_confirmed_at=None, contested=None):
    """Build a synthetic node dict shaped like graph_memory entries."""
    return {
        "id": nid,
        "content": content,
        "type": "fact",
        "tags": set(),
        "confidence": conf,
        "source_strength": src,
        "last_confirmed_at": last_confirmed_at or time.time(),
        "created": last_confirmed_at or time.time(),
        "contested_with": contested,
    }


def scenario_provenance_present_on_answer():
    r = ScenarioResult(scenario="provenance attached on action_hint=answer")
    from orion_metacognition import score_recall
    cands = [
        (_node(101, "user prefers terse replies"), 0.95),
        (_node(102, "different fact about user"), 0.10),
    ]
    out = score_recall("what does the user prefer", cands)
    assert_equals(r, "decision is answer", out["action_hint"], "answer")
    assert_equals(r, "provenance is ordered list",
                  out.get("provenance"), [101, 102])
    return r


def scenario_provenance_present_on_refuse_no_candidates():
    r = ScenarioResult(scenario="provenance=[] when no candidates")
    from orion_metacognition import score_recall
    out = score_recall("does this user know X", [])
    assert_equals(r, "decision is refuse", out["action_hint"], "refuse")
    assert_equals(r, "i_dont_know=True", out["i_dont_know"], True)
    assert_equals(r, "provenance is empty list",
                  out.get("provenance"), [])
    return r


def scenario_provenance_present_on_refuse_contested():
    r = ScenarioResult(scenario="provenance attached even when refusing contested")
    from orion_metacognition import score_recall
    cands = [
        (_node(201, "user lives in Austin", contested=[202]), 0.9),
        (_node(202, "user lives in Boston"), 0.7),
    ]
    out = score_recall("where does the user live", cands)
    assert_equals(r, "decision is refuse", out["action_hint"], "refuse")
    # Refuse must still expose the trail — user can audit "what did
    # Orion see when it declined?"
    assert_equals(r, "provenance lists both contested nodes",
                  out.get("provenance"), [201, 202])
    return r


def scenario_provenance_present_on_refuse_stale():
    r = ScenarioResult(scenario="provenance attached when refusing on staleness")
    from orion_metacognition import score_recall
    # 5 years ago → recency_conf well below floor
    very_old = time.time() - 5 * 365 * 86400
    cands = [
        (_node(301, "user's old fact", last_confirmed_at=very_old), 0.9),
    ]
    out = score_recall("ancient query", cands)
    assert_equals(r, "decision is refuse on staleness", out["action_hint"], "refuse")
    assert_equals(r, "provenance has the stale node",
                  out.get("provenance"), [301])
    return r


def scenario_provenance_fallback_to_content_hash():
    r = ScenarioResult(
        scenario="provenance falls back to content-hash for unkeyed nodes")
    from orion_metacognition import score_recall
    # Some upstream paths key the dict externally and the node body has
    # no "id" field. Provenance must still attribute, not silently drop.
    n = _node(None, "an unkeyed memory body")
    n.pop("id", None)
    out = score_recall("query", [(n, 0.9)])
    prov = out.get("provenance") or []
    assert_true(r, "provenance has exactly one item", len(prov) == 1)
    assert_true(r, "fallback entry uses ch: prefix",
                isinstance(prov[0], str) and prov[0].startswith("ch:"))
    return r


SCENARIOS = [
    scenario_provenance_present_on_answer,
    scenario_provenance_present_on_refuse_no_candidates,
    scenario_provenance_present_on_refuse_contested,
    scenario_provenance_present_on_refuse_stale,
    scenario_provenance_fallback_to_content_hash,
]


if __name__ == "__main__":
    sys.exit(run_suite("SOURCE ATTRIBUTION", SCENARIOS))
