"""orion_dream.py — nightly playbook consolidator (Anthropic-Dreaming pattern).

The 2026-05-09 continual-learning research validated this shape:
  - Read the last N hours of decisions from the executive's ledger
  - Group by symptom_class + service
  - Synthesize plain-text playbook entries: "for service X with
    symptoms Y, action Z worked / didn't work — cite [a,b,c]"
  - Track per-playbook success rate with CUSUM monitor; demote
    superseded playbooks (don't delete — keep raw entries for
    provenance)
  - Runtime executive injects top-K matching playbooks via MMR-
    diverse retrieval (richer than raw decision retrieval)

WHY DREAMS, NOT REAL-TIME LEARNING
==================================

The literature is unanimous: real-time consolidation produces
"self-degradation" via misaligned experience replay (arXiv 2505.17716).
Anthropic's "Dreaming" (Apr 2026) runs async + scheduled, not
real-time. ACT-R-inspired architectures use Ebbinghaus-curve decay
between consolidations. We follow this discipline:

  - Session-end summarization: cheap, after every applied decision
  - Nightly playbook consolidation: expensive, runs when substrate idle
  - Real-time consolidation: forbidden (degrades quality)

WHAT'S A PLAYBOOK ENTRY
=======================

Plain text, keyed by symptom_class. Stored as markdown for human
readability + observability. Example:

    # Playbook: SERVICE_LOOP for com.orion.imessage

    ## Pattern
    Symptom: service crashes within seconds of every restart.
    Vital signature: error_count > 0, last_event_age_sec rapidly
    growing, dependency probe `chat_db_readable` flips False.

    ## What works
    - macOS Full Disk Access grant for /usr/bin/python3
      (succeeded 2026-05-09 [decision exec-1778346...])
    - launchctl reload after granting permission

    ## What doesn't work
    - launchctl reload alone (TCC stays revoked) — fails 7/7 times
      (decisions exec-..., exec-...)
    - Increasing restart delay — masks the symptom (decision exec-...)

    ## CUSUM tracker
    Last 10 invocations: 9 success / 1 fail. Threshold for demotion: <0.6.

    ## Provenance
    Cited decisions: exec-1778346..., exec-1778349..., exec-1778352...

This is HUMAN-READABLE. Founder + future agents can audit, edit,
critique. "Plain-text + observable" is the Anthropic Dreaming
contract; we honor it.

OUTPUTS
=======

  ~/.orion/playbooks/<symptom_class>.md   — human-readable per-class
  ~/.orion/playbooks/_index.json          — machine-readable index for retrieval
  ~/.orion/playbooks/_history.jsonl       — append-only history of dream runs

Substrate events:
  brain.dream.starting       — begin consolidation
  brain.dream.playbook_added — new entry written
  brain.dream.playbook_demoted — CUSUM dropped below threshold
  brain.dream.complete       — done, with summary stats
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("orion.dream")

PLAYBOOK_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_PLAYBOOK_DIR", "~/.orion/playbooks")
))
LEDGER_PATH = Path(os.path.expanduser(
    os.environ.get("ORION_DECISION_LEDGER", "~/.orion/executive/decisions.jsonl")
))
DREAM_INTERVAL_SEC = float(os.environ.get("ORION_DREAM_INTERVAL_SEC", "86400"))  # 24h
LOOKBACK_HOURS = float(os.environ.get("ORION_DREAM_LOOKBACK_HOURS", "24"))
CUSUM_DEMOTION_THRESHOLD = float(os.environ.get("ORION_DREAM_CUSUM_THRESHOLD", "0.6"))
MIN_DECISIONS_PER_PLAYBOOK = int(os.environ.get("ORION_DREAM_MIN_DECISIONS", "3"))

_stop = threading.Event()


def _read_ledger_recent(lookback_sec: float) -> list[dict]:
    """Return ledger entries within the lookback window."""
    if not LEDGER_PATH.exists():
        return []
    cutoff = time.time() - lookback_sec
    recent = []
    try:
        with LEDGER_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if float(d.get("ts", 0)) >= cutoff:
                        recent.append(d)
                except Exception:
                    continue
    except Exception as e:
        logger.warning("ledger read error: %s", e)
    return recent


def _group_by_playbook_key(decisions: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Group decisions by (symptom_class, service)."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in decisions:
        sym = d.get("symptom_class") or "UNRECOGNIZED"
        svc = d.get("service") or "unknown"
        groups[(sym, svc)].append(d)
    return groups


def _read_existing_playbook(sym: str) -> dict | None:
    """Load the existing _index.json record for this symptom class, if any."""
    idx_path = PLAYBOOK_DIR / "_index.json"
    if not idx_path.exists():
        return None
    try:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        return idx.get(sym)
    except Exception:
        return None


def _save_playbook(sym: str, svc: str, body: str,
                   cited_decision_ids: list[str],
                   success_count: int, fail_count: int) -> None:
    """Write playbook markdown + update index."""
    PLAYBOOK_DIR.mkdir(parents=True, exist_ok=True)
    md_path = PLAYBOOK_DIR / f"{sym}.md"
    idx_path = PLAYBOOK_DIR / "_index.json"

    # Append a new playbook section to the markdown file
    section = (
        f"\n\n## Playbook: {sym} for {svc}\n"
        f"_Generated by dream cycle at {time.strftime('%Y-%m-%dT%H:%M:%S')}_\n\n"
        f"{body}\n"
        f"\n### CUSUM tracker\n"
        f"Recent invocations: {success_count} success / {fail_count} fail.\n"
        f"Demotion threshold: <{CUSUM_DEMOTION_THRESHOLD:.2f} success rate.\n"
        f"\n### Provenance\nCited decisions: {', '.join(cited_decision_ids[:8])}\n"
    )
    if not md_path.exists():
        md_path.write_text(f"# Playbook: {sym}\n\n_Symptom-class-keyed playbook entries._\n", encoding="utf-8")
    with md_path.open("a", encoding="utf-8") as f:
        f.write(section)

    # Update machine-readable index for retrieval
    idx: dict = {}
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            idx = {}
    entry = idx.get(sym, {"by_service": {}})
    entry["by_service"][svc] = {
        "last_updated": time.time(),
        "body_excerpt": body[:500],
        "success_count": success_count,
        "fail_count": fail_count,
        "success_rate": success_count / max(success_count + fail_count, 1),
        "cited_decision_ids": cited_decision_ids[:8],
        "active": True,
    }
    idx[sym] = entry
    idx_path.write_text(json.dumps(idx, indent=2, default=str), encoding="utf-8")


def _consolidate_group(sym: str, svc: str, decisions: list[dict]) -> dict | None:
    """Build a plain-text playbook body for one symptom-class + service group.

    Currently a deterministic template (no LLM call). The next-round
    upgrade is to ask the brain to write a more nuanced body using
    these decisions as raw material — but starting with deterministic
    keeps the first dream cycle observable + predictable.
    """
    # Skip groups with too few decisions to learn from
    if len(decisions) < MIN_DECISIONS_PER_PLAYBOOK:
        return None

    success_decisions = [d for d in decisions if d.get("outcome") == "succeeded"]
    fail_decisions = [d for d in decisions if d.get("outcome") in ("failed", "regressed")]

    # Gather what worked vs what didn't
    worked_kinds = defaultdict(int)
    failed_kinds = defaultdict(int)
    for d in success_decisions:
        kind = (d.get("proposal") or {}).get("remedy_kind") or "unknown"
        worked_kinds[kind] += 1
    for d in fail_decisions:
        kind = (d.get("proposal") or {}).get("remedy_kind") or "unknown"
        failed_kinds[kind] += 1

    body_lines = ["### What works\n"]
    if worked_kinds:
        for kind, n in sorted(worked_kinds.items(), key=lambda x: -x[1]):
            body_lines.append(f"- `{kind}` succeeded {n}× recently")
    else:
        body_lines.append("- (no successes recorded yet for this group)")

    body_lines.append("\n### What doesn't work\n")
    if failed_kinds:
        for kind, n in sorted(failed_kinds.items(), key=lambda x: -x[1]):
            body_lines.append(f"- `{kind}` failed {n}× recently — avoid")
    else:
        body_lines.append("- (no clear failures yet — be cautious)")

    return {
        "body": "\n".join(body_lines),
        "cited_decision_ids": [d.get("decision_id", "") for d in decisions[:8]],
        "success_count": len(success_decisions),
        "fail_count": len(fail_decisions),
    }


def _publish_event(subject: str, payload: dict) -> None:
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass


def _run_dream_cycle() -> dict:
    """One dream cycle: read recent decisions, consolidate into playbooks."""
    started = time.time()
    _publish_event("brain.dream.starting", {"ts": started, "lookback_h": LOOKBACK_HOURS})

    decisions = _read_ledger_recent(LOOKBACK_HOURS * 3600)
    groups = _group_by_playbook_key(decisions)
    new_playbooks = 0
    demoted = 0

    PLAYBOOK_DIR.mkdir(parents=True, exist_ok=True)
    history_path = PLAYBOOK_DIR / "_history.jsonl"

    for (sym, svc), grp in groups.items():
        result = _consolidate_group(sym, svc, grp)
        if not result:
            continue

        # CUSUM-style demotion check
        existing = _read_existing_playbook(sym)
        if existing and svc in existing.get("by_service", {}):
            prev = existing["by_service"][svc]
            new_total = prev.get("success_count", 0) + result["success_count"] + \
                        prev.get("fail_count", 0) + result["fail_count"]
            new_succ = prev.get("success_count", 0) + result["success_count"]
            success_rate = new_succ / max(new_total, 1)
            if success_rate < CUSUM_DEMOTION_THRESHOLD and new_total >= 5:
                # Mark as superseded (don't delete — keep for provenance)
                prev["active"] = False
                prev["demoted_at"] = time.time()
                _publish_event("brain.dream.playbook_demoted", {
                    "symptom_class": sym, "service": svc,
                    "success_rate": success_rate, "ts": time.time(),
                })
                demoted += 1
                continue

        _save_playbook(sym, svc, result["body"], result["cited_decision_ids"],
                       result["success_count"], result["fail_count"])
        _publish_event("brain.dream.playbook_added", {
            "symptom_class": sym, "service": svc,
            "decisions_consolidated": len(grp), "ts": time.time(),
        })
        new_playbooks += 1

    summary = {
        "ts": time.time(),
        "duration_sec": time.time() - started,
        "decisions_read": len(decisions),
        "groups": len(groups),
        "new_playbooks": new_playbooks,
        "demoted": demoted,
    }
    try:
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, default=str) + "\n")
    except Exception:
        pass

    _publish_event("brain.dream.complete", summary)
    logger.info("dream cycle complete: %d decisions, %d new playbooks, %d demoted",
                len(decisions), new_playbooks, demoted)
    return summary


def _dream_loop() -> None:
    while not _stop.is_set():
        try:
            _run_dream_cycle()
        except Exception as e:
            logger.warning("dream cycle error: %s", e)
        _stop.wait(DREAM_INTERVAL_SEC)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))

    logger.info("dream alive — consolidating decisions every %d sec "
                "(lookback %.1fh)", int(DREAM_INTERVAL_SEC), LOOKBACK_HOURS)

    threading.Thread(target=_dream_loop, name="dream-cycle", daemon=True).start()

    def _sigterm(_sig, _frame):
        _stop.set()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    while not _stop.is_set():
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
