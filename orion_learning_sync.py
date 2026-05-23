"""orion_learning_sync.py — the local applier for cross-host learned units.

This is the RECEIVE side of C4 (synthesis-continual-learning.md): a host's
gossip layer merges remote learned-skill entries into its LWWMap, emits
`brain.learned.skill.from_peer` per adopted entry, and this module writes
the remote skill to the local disk so `find_matching_skill` can match it
on this host immediately.

What it does (cellular-discipline scope):
  - Subscribes to `brain.learned.skill.from_peer`.
  - Applies the remote skill to the local skills dir (or archive dir if
    op == "archived"), idempotent by content_hash.
  - Contribution-aware tiebreak per the synthesis memo: if a local skill
    exists with HIGHER contribution than the incoming one, the local wins
    (the merge's HLC alone would prefer NEWER, but a newer-but-worse
    skill is a regression — the ratchet's whole point is non-regression).
  - Never modifies the executive's decisions ledger, the will state, or
    the memory graph — this is the SKILL applier only. Calibration row
    aggregation is a follow-up; raw rows are too high-volume for the LWWMap.

Honest scope notes:
  - The applier writes the file directly; it does NOT re-publish a
    `brain.learned.skill` event for the local write (which would loop
    through gossip and create a feedback storm). The local write is
    silent — gossip already knows about this skill, that's how we
    received it.
  - Membrane / privacy: a skill marked private (membrane=private) is
    filtered at the OUTBOUND step by orion_gossip._filtered_for_mesh
    (via orion_membrane). So a private skill from a peer can only land
    here if the peer's membrane authorized it — receiver trusts the
    membrane chain. Future hardening (brain-as-signal-v2 §2: per-author
    HLC high-water, replay defense) is a tightening, not a redesign.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from typing import Optional

logger = logging.getLogger("orion.learning_sync")


def apply_remote_skill(payload: dict) -> dict:
    """Apply one remote skill payload to local disk. Pure function, no
    substrate, no daemons — so cross-process / unit tests can drive it.
    Returns a stats dict for diagnostics and the substrate publish below."""
    fname = payload.get("fname")
    op = payload.get("op", "fired")
    skill = payload.get("skill") or {}
    if not fname or not skill:
        return {"applied": False, "reason": "empty payload"}

    try:
        import orion_memory
    except Exception as e:
        return {"applied": False, "reason": "orion_memory import: %s" % e}

    active_path = os.path.join(orion_memory.SKILLS_DIR, fname)
    archive_path = os.path.join(orion_memory.SKILLS_ARCHIVE_DIR, fname)
    incoming_contrib = float(skill.get("contribution", 0.0))
    incoming_hash = skill.get("content_hash")

    # Archived: move the local active copy (if any) to archive; write the
    # remote payload to archive too so we keep provenance. archive_skill
    # would re-emit a gossip event — call the raw file ops directly here.
    if op == "archived":
        if os.path.exists(active_path):
            try:
                os.remove(active_path)
            except Exception:
                pass
        try:
            with open(archive_path, "w", encoding="utf-8") as f:
                json.dump(skill, f, indent=2)
            return {"applied": True, "op": "archived", "fname": fname}
        except Exception as e:
            return {"applied": False, "reason": "archive write: %s" % e}

    # Active write (learned/fired/restored). If a local exists, contribution
    # is the tiebreak: a remote write with LOWER contribution is the very
    # rotting the ratchet exists to prevent — keep the local incumbent.
    local = None
    if os.path.exists(active_path):
        try:
            with open(active_path, encoding="utf-8") as f:
                local = json.load(f)
        except Exception:
            local = None

    if local is not None:
        local_hash = local.get("content_hash")
        if local_hash and local_hash == incoming_hash:
            return {"applied": False, "reason": "same content_hash (no-op)"}
        local_contrib = float(local.get("contribution", 0.0))
        if local_contrib > incoming_contrib:
            return {"applied": False, "reason":
                    "local contribution %.3f > remote %.3f — keep local"
                    % (local_contrib, incoming_contrib)}

    try:
        os.makedirs(orion_memory.SKILLS_DIR, exist_ok=True)
        with open(active_path, "w", encoding="utf-8") as f:
            json.dump(skill, f, indent=2)
        # Also remove from archive if present (a remote restore lands here
        # as op == "restored"; we already wrote the active copy above).
        if op == "restored" and os.path.exists(archive_path):
            try:
                os.remove(archive_path)
            except Exception:
                pass
        return {"applied": True, "op": op, "fname": fname,
                "contribution": incoming_contrib}
    except Exception as e:
        return {"applied": False, "reason": "write failed: %s" % e}


def _on_from_peer(subject: str, payload: dict) -> None:
    rep = apply_remote_skill(payload)
    logger.info("from_peer fname=%s op=%s -> %s",
                payload.get("fname"), payload.get("op"), rep)
    try:
        from orion_substrate import publish
        publish("brain.learned.skill.applied", {
            "source_host": payload.get("source_host"),
            "fname": payload.get("fname"),
            "applied": rep.get("applied"),
            "reason": rep.get("reason"),
            "ts": time.time(),
        })
    except Exception:
        pass


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        logger.error("orion_substrate not importable — learning_sync cannot run")
        return 1
    sub = get_substrate()
    sub._connect_blocking()
    subscribe("brain.learned.skill.from_peer", _on_from_peer)
    logger.info("learning-sync alive — applying remote learned skills to local disk")
    stop = False

    def _sigterm(_sig, _frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    while not stop:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
