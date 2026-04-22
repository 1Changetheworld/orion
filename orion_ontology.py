#!/usr/bin/env python3
"""
orion_ontology — schema discipline for graph_memory.

Implements the findings from research round-3 (ontologist persona). Keeps
the graph from drifting into an unusable state at personal scale.

Three rules this module enforces (as HELPERS — not mandatory; existing
code paths still work unmodified):

  1. Type cap: ≤10 node types, ≤10 edge types. Zep's empirical production
     cap — LLM extraction degrades above it. Adding a type requires that
     type to satisfy the add-a-type rule (see docstring of
     `validate_new_node_type`).

  2. Entity canonicalization: the `entity` node type is special. Every
     entity must have `aliases[]`, `summary`, `last_seen`. This is what
     lets "James", "user", "the boss", "sir" collapse into one node
     rather than proliferating into five memories.

  3. Bias-toward-NEW entity resolution: when an incoming mention could
     match an existing entity, default to NEW unless match confidence
     is very high. Spurious merges silently corrupt memory. Missed
     merges are cheap to fix later via the review queue.

This module is a wrapper/helper — it does not replace orion_brain_portable's
graph. It provides functions the write path can call BEFORE invoking
the graph's store() method.

Usage:
    from orion_ontology import (
        validate_node_type, ensure_entity_fields,
        resolve_entity, merge_entities, pending_merge_reviews,
        CANONICAL_NODE_TYPES, MAX_NODE_TYPES, MAX_EDGE_TYPES,
    )
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ----------------------------------------------------------------------
# Caps + canonical types (from research round-3 ontologist findings)
# ----------------------------------------------------------------------

MAX_NODE_TYPES = 10
MAX_EDGE_TYPES = 10

# Subtype tag prefix — when specificity beyond the 10-type cap is needed,
# capture it as a tag rather than a new type. Example:
#   node.type = "tool", node.tags includes "role:fuel"
# reads as "a tool playing the fuel role." Ten broad types stay LLM-
# extractable; unlimited subtypes captured in tags.
#
# This is the innovation answer to the cap question. The cap is not a
# wall — it's where semantic precision migrates from types to tags.
SUBTYPE_TAG_PREFIX = "role:"


def as_subtype_tag(subtype: str) -> str:
    """Return the tag form for a subtype. Example: 'fuel' -> 'role:fuel'."""
    return f"{SUBTYPE_TAG_PREFIX}{subtype.strip().lower()}"


def extract_subtype(tags: set | list | None) -> str | None:
    """Inverse of as_subtype_tag — pull the subtype out of a tag set."""
    if not tags:
        return None
    for tag in tags:
        if isinstance(tag, str) and tag.startswith(SUBTYPE_TAG_PREFIX):
            return tag[len(SUBTYPE_TAG_PREFIX):]
    return None

# Seeded canonical set. These are the types currently in the graph as of
# 2026-04-22 plus the `entity` type for canonical people/projects/etc.
# Not hardcoded as tool-curation — the set is overridable and the cap is
# what matters. If a production site needs different types, change this
# tuple; just don't breach MAX_NODE_TYPES.
CANONICAL_NODE_TYPES: tuple[str, ...] = (
    "entity",          # canonical people/projects/places — has aliases, summary
    "fact",            # ground-truth statements the user has asserted
    "preference",      # the user's stated preferences
    "schedule",        # time-bound events
    "identity",        # claims about Orion's own identity/capability
    "architecture",    # structural facts about Orion's own code/design
    "tool",            # external tools Orion works with
    "hardware",        # physical devices, specs, configurations
    "interface",       # channels Orion is reachable through
    "conversation",    # raw conversation artifacts (may be demoted later)
)

ENTITY_TYPE = "entity"

# Edge types enforced the same way — bi-temporal validity is the one
# OWL-adjacent feature that earns its complexity (contradiction + decay).
CANONICAL_EDGE_TYPES: tuple[str, ...] = (
    "references",      # node A points at entity B
    "supersedes",      # A replaces B (for contradiction resolution)
    "contradicts",     # A and B both claim true, user hasn't resolved
    "derived_from",    # A was consolidated/synthesized from B
    "confirmed_by",    # A is re-confirmed by the observation in B
    "tagged_with",     # A has tag B (if tags become first-class)
    # Reserved slots for future edge types — keep count ≤ MAX_EDGE_TYPES
)


# ----------------------------------------------------------------------
# Entity canonicalization fields
# ----------------------------------------------------------------------

ENTITY_REQUIRED_FIELDS = ("aliases", "summary", "last_seen")


# ----------------------------------------------------------------------
# Merge review queue — the human-in-loop path
# ----------------------------------------------------------------------

REVIEW_QUEUE_PATH = Path.home() / ".orion" / "brain" / "merge_review_queue.jsonl"


@dataclass
class MergeReview:
    proposed_keep: int        # existing entity node ID
    proposed_drop: int        # incoming entity node ID
    reason: str               # why the resolver thought these might be the same
    confidence: float         # resolver's confidence, 0.0 - 1.0
    created: float            # timestamp

    def as_dict(self):
        from dataclasses import asdict
        return asdict(self)


# ----------------------------------------------------------------------
# Validation helpers
# ----------------------------------------------------------------------

def validate_node_type(node_type: str,
                       existing_types: set[str] | None = None,
                       canonical: tuple[str, ...] = CANONICAL_NODE_TYPES,
                       max_types: int = MAX_NODE_TYPES) -> tuple[bool, str]:
    """Return (accepted, reason).

    accepted=True when:
      - node_type is in the canonical set, OR
      - adding it would not breach the cap AND it passes `validate_new_node_type`
        (which in v1 is liberal — the cap itself is the enforcer).
    """
    if node_type in canonical:
        return True, "canonical type"

    # Adding a new type — check cap
    known = set(existing_types or canonical)
    known.add(node_type)
    if len(known) > max_types:
        return False, (
            f"adding '{node_type}' would breach type cap ({max_types}); "
            f"consider reusing one of: {', '.join(sorted(canonical))}"
        )

    # We allow the new type (caller is responsible for add-a-type rule
    # review — this module captures the cap but does not yet automate
    # the two-question test).
    return True, f"new type accepted (under cap)"


def validate_new_node_type(node_type: str,
                            sample_content: str,
                            existing_types: set[str]) -> tuple[bool, str]:
    """The add-a-type rule from round-3 research — MORE STRICT.

    A new type is justified only when BOTH:
      (a) it has at least one property no existing type holds, AND
      (b) at least one query needs to filter on that type.

    This function returns a non-binding recommendation — the caller may
    choose to add the type anyway. We surface the reasoning so future
    audits can catch ontology creep.
    """
    # This is a stub — full implementation would inspect schema of existing
    # types + query patterns. For v1 we just surface the rule's text.
    accepted, cap_reason = validate_node_type(
        node_type, existing_types=existing_types
    )
    if not accepted:
        return False, cap_reason
    return True, (
        f"cap-ok; please verify add-a-type rule: "
        f"does '{node_type}' have a property no existing type holds, AND "
        f"does at least one query need to filter on it?"
    )


def ensure_entity_fields(node: dict) -> dict:
    """Augment a node dict to carry the mandatory entity fields.

    Called on nodes with type='entity' before store(). No-op on non-entities.
    Idempotent — safe to call on a node that already has the fields.
    """
    if node.get("type") != ENTITY_TYPE:
        return node

    if "aliases" not in node:
        node["aliases"] = []
    elif isinstance(node["aliases"], (set, tuple)):
        node["aliases"] = list(node["aliases"])

    if "summary" not in node:
        # Default summary is a truncated content — caller can override
        node["summary"] = (node.get("content") or "")[:200]

    if "last_seen" not in node:
        node["last_seen"] = node.get("last_confirmed_at") or time.time()

    return node


# ----------------------------------------------------------------------
# Entity resolution — bias toward NEW
# ----------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    return "".join(c.lower() for c in (name or "") if c.isalnum() or c.isspace()).strip()


def find_entity_candidates(graph, name_or_alias: str) -> list[tuple[int, float, str]]:
    """Return list of (node_id, confidence_hint, reason) for possible matches.

    Doesn't merge anything — just surfaces candidates. The caller decides.
    Confidence_hint is a heuristic (exact name match, partial alias, etc.);
    it's not a probability.
    """
    target = _normalize_name(name_or_alias)
    if not target:
        return []

    results: list[tuple[int, float, str]] = []
    for nid, node in graph.nodes.items():
        if node.get("type") != ENTITY_TYPE:
            continue

        # Exact content match
        if _normalize_name(node.get("content", "")) == target:
            results.append((nid, 0.95, "exact content match"))
            continue

        # Alias match
        aliases = node.get("aliases", []) or []
        for alias in aliases:
            n = _normalize_name(alias)
            if n == target:
                results.append((nid, 0.9, f"exact alias match: '{alias}'"))
                break
            elif target and n and (target in n or n in target) and min(len(n), len(target)) >= 3:
                results.append((nid, 0.5, f"partial alias overlap: '{alias}'"))
                break
    return results


def resolve_entity(graph, name_or_alias: str,
                   summary: str = "", extra_aliases: list[str] | None = None,
                   confidence_threshold: float = 0.85,
                   review_queue_path: Path = REVIEW_QUEUE_PATH) -> int:
    """Find existing entity OR create new. Biased toward NEW.

    Behavior:
      - If a candidate with confidence >= threshold: add the incoming
        name+aliases to that entity's alias list (idempotent), update
        last_seen, return its ID.
      - If candidates exist BUT confidence < threshold: create a NEW entity
        AND enqueue a merge review (human-in-loop).
      - If no candidates: create a NEW entity.

    The bias-toward-NEW behavior is per research finding: spurious merges
    silently corrupt, missed merges are cheap to fix later.

    Returns the ID of the (possibly new) entity node.
    """
    candidates = find_entity_candidates(graph, name_or_alias)

    # Strong match — merge alias into existing, return existing
    for nid, conf, reason in candidates:
        if conf >= confidence_threshold:
            node = graph.nodes[nid]
            aliases = set(node.get("aliases", []) or [])
            aliases.add(name_or_alias)
            if extra_aliases:
                aliases.update(extra_aliases)
            node["aliases"] = sorted(aliases)
            node["last_seen"] = time.time()
            if summary and not node.get("summary"):
                node["summary"] = summary[:200]
            return nid

    # Weak candidates — create NEW and enqueue review
    # (No candidates — just create, no review)
    new_node_content = name_or_alias
    new_aliases = list({name_or_alias, *(extra_aliases or [])})
    # Use graph's store() API so indexes get updated
    new_id = graph.store(
        content=new_node_content,
        node_type=ENTITY_TYPE,
        tags=["entity"],
        skip_contradiction_check=True,  # entity creation is not a contradiction
    )
    node = graph.nodes[new_id]
    node["aliases"] = new_aliases
    node["summary"] = summary[:200] if summary else new_node_content[:200]
    node["last_seen"] = time.time()

    # Enqueue reviews for ambiguous candidates
    if candidates:
        for nid, conf, reason in candidates:
            if conf < confidence_threshold:
                _enqueue_merge_review(
                    proposed_keep=nid,
                    proposed_drop=new_id,
                    reason=f"{reason} (resolver conf={conf:.2f}, threshold={confidence_threshold})",
                    confidence=conf,
                    review_queue_path=review_queue_path,
                )

    return new_id


def _enqueue_merge_review(proposed_keep: int, proposed_drop: int,
                           reason: str, confidence: float,
                           review_queue_path: Path = REVIEW_QUEUE_PATH) -> None:
    review_queue_path.parent.mkdir(parents=True, exist_ok=True)
    review = MergeReview(
        proposed_keep=proposed_keep,
        proposed_drop=proposed_drop,
        reason=reason,
        confidence=confidence,
        created=time.time(),
    )
    try:
        with review_queue_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(review.as_dict()) + "\n")
    except Exception:
        pass  # review queue is advisory — must not break writes


def pending_merge_reviews(review_queue_path: Path = REVIEW_QUEUE_PATH) -> list[dict]:
    """Read the queue without resolving. User/UI can present these for review."""
    if not review_queue_path.exists():
        return []
    reviews: list[dict] = []
    try:
        with review_queue_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        reviews.append(json.loads(line))
                    except Exception:
                        continue
    except Exception:
        pass
    return reviews


def merge_entities(graph, keep_id: int, drop_id: int,
                   merge_aliases: bool = True) -> tuple[bool, str]:
    """Manually merge two entity nodes. Called from a review-queue UI.

    Moves drop's aliases into keep, marks drop as superseded_by keep,
    leaves drop in the graph (cheap to undo vs. destroy). Callers should
    run this only after human review.
    """
    keep = graph.nodes.get(keep_id)
    drop = graph.nodes.get(drop_id)
    if not keep or not drop:
        return False, "one or both node IDs not found"
    if keep.get("type") != ENTITY_TYPE or drop.get("type") != ENTITY_TYPE:
        return False, "both nodes must be of type 'entity'"

    if merge_aliases:
        combined = set(keep.get("aliases", []) or [])
        combined.update(drop.get("aliases", []) or [])
        combined.add(drop.get("content", ""))  # drop's own name becomes alias
        combined.discard("")
        keep["aliases"] = sorted(combined)

    # Merge summary conservatively — prefer non-empty
    if not keep.get("summary") and drop.get("summary"):
        keep["summary"] = drop["summary"]

    # Update last_seen to most recent
    keep["last_seen"] = max(
        keep.get("last_seen", 0),
        drop.get("last_seen", 0),
        time.time(),
    )

    drop["superseded_by"] = keep_id
    drop["superseded_at"] = time.time()

    return True, f"merged {drop_id} into {keep_id} ({len(keep['aliases'])} aliases total)"


# ----------------------------------------------------------------------
# Snapshot / audit helpers
# ----------------------------------------------------------------------

def audit_graph(graph) -> dict:
    """Return a structured view of graph ontology health."""
    from collections import Counter
    type_counts: Counter = Counter()
    entity_missing_fields: list[int] = []
    orphan_types: set[str] = set()

    for nid, node in graph.nodes.items():
        t = node.get("type", "?")
        type_counts[t] += 1
        if t == ENTITY_TYPE:
            missing = [f for f in ENTITY_REQUIRED_FIELDS if f not in node]
            if missing:
                entity_missing_fields.append(nid)
        if t not in CANONICAL_NODE_TYPES:
            orphan_types.add(t)

    return {
        "total_nodes": len(graph.nodes),
        "distinct_types": len(type_counts),
        "type_counts": dict(type_counts.most_common()),
        "at_cap": len(type_counts) >= MAX_NODE_TYPES,
        "over_cap": len(type_counts) > MAX_NODE_TYPES,
        "canonical_type_coverage": sum(
            1 for t in CANONICAL_NODE_TYPES if t in type_counts
        ),
        "orphan_types": sorted(orphan_types),
        "entity_count": type_counts.get(ENTITY_TYPE, 0),
        "entity_missing_required_fields": entity_missing_fields,
        "pending_merge_reviews": len(pending_merge_reviews()),
    }
