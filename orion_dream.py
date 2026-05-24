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


# ─────────────────────────────────────────────────────────
# Lateral diffusion — CA-style supplement to the calibration ledger.
# Each row gets a small contribution from its token-neighbors' outcomes
# so learning on one shape can generalize laterally to similar shapes
# *within the same host*. Per the T4 cognition brief:
#   - alpha small (~0.1) — diffusion supplements, never replaces
#   - reversible — original outcome_value untouched; diffused values live
#     in a separate JSON file the governor mixes in at half-weight
#   - neighbors found via Jaccard > LATERAL_NEIGHBOR_SIM on the same token
#     bag used by _similar_rows, so the neighbor relation is consistent
# ─────────────────────────────────────────────────────────

LATERAL_ALPHA = float(os.environ.get("ORION_DREAM_LATERAL_ALPHA", "0.1"))
LATERAL_NEIGHBOR_SIM = float(os.environ.get("ORION_DREAM_LATERAL_SIM", "0.3"))
LATERAL_MIN_NEIGHBORS = int(os.environ.get("ORION_DREAM_LATERAL_MIN_N", "2"))


def _tokens_lower(s: str) -> set[str]:
    """Same token shape orion_metacognition._tokens uses, kept inline so
    the dream cycle doesn't need to import the daemon for one set-builder."""
    return {t for t in (s or "").lower().replace("/", " ").replace("_", " ").split()
            if len(t) > 2}


def _lateral_diffuse() -> dict:
    """One CA-style diffusion pass over the metacognition decision ledger.

    For each closed ledger row, find token-neighbors (Jaccard ≥
    LATERAL_NEIGHBOR_SIM on symptom+action tokens), compute
    diffused_value = alpha * mean(neighbors.outcome_value) + (1-alpha) * own,
    and write the result to ~/.orion/metacog/diffused.json. Original
    ledger untouched — this is supplementary signal the governor mixes in
    at half-weight against own outcome_value. Skipped silently when the
    ledger is absent or under-populated.

    Returns a summary dict with the row counts + the mean absolute shift
    so the dream history captures whether diffusion is actually doing
    work (high mean shift) vs. spinning (~0)."""
    ledger_path = Path(os.path.expanduser(
        os.environ.get("ORION_METACOG_LEDGER")
        or "~/.orion/metacog/decisions.jsonl"))
    out_path = ledger_path.parent / "diffused.json"
    if not ledger_path.exists():
        return {"skipped": "no ledger yet"}
    rows: list[dict] = []
    try:
        with ledger_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "outcome" not in r or "outcome_value" not in r:
                    continue
                if not r.get("decision_id"):
                    continue
                rows.append(r)
    except OSError:
        return {"skipped": "ledger read failed"}
    if len(rows) < LATERAL_MIN_NEIGHBORS + 1:
        return {"skipped": "ledger too small (%d rows)" % len(rows)}
    # Pre-tokenize once so the N^2 neighbor search is cheap. Bound the
    # search at LATERAL_CAP rows from the tail so a megaledger doesn't
    # turn diffusion into a multi-second pass.
    cap = int(os.environ.get("ORION_DREAM_LATERAL_CAP", "1000"))
    rows = rows[-cap:]
    toks = [_tokens_lower(r.get("symptom_class", "") + " "
                          + (r.get("proposed_action") or ""))
            for r in rows]
    diffused: dict = {}
    rows_with_neighbors = 0
    total_abs_shift = 0.0
    for i, r in enumerate(rows):
        if not toks[i]:
            continue
        neighbor_vals: list[float] = []
        for j in range(len(rows)):
            if j == i:
                continue
            if not toks[j]:
                continue
            inter = len(toks[i] & toks[j])
            union = len(toks[i] | toks[j])
            if union == 0:
                continue
            if inter / union < LATERAL_NEIGHBOR_SIM:
                continue
            neighbor_vals.append(float(rows[j]["outcome_value"]))
        if len(neighbor_vals) < LATERAL_MIN_NEIGHBORS:
            continue
        own = float(r["outcome_value"])
        neighbor_mean = sum(neighbor_vals) / len(neighbor_vals)
        diffused_val = LATERAL_ALPHA * neighbor_mean + (1.0 - LATERAL_ALPHA) * own
        diffused[r["decision_id"]] = {
            "outcome_value": round(own, 4),
            "diffused_value": round(diffused_val, 4),
            "neighbors_n": len(neighbor_vals),
        }
        rows_with_neighbors += 1
        total_abs_shift += abs(diffused_val - own)
    # Atomic write so a partial diffusion pass never corrupts the file
    # the governor reads. Empty diffused → still write {"rows": {}} so
    # the governor sees "diffusion ran, no neighbors found" not "no diff
    # file at all" (which is harmless but ambiguous).
    summary = {
        "ts": time.time(),
        "alpha": LATERAL_ALPHA,
        "neighbor_sim_threshold": LATERAL_NEIGHBOR_SIM,
        "min_neighbors": LATERAL_MIN_NEIGHBORS,
        "rows_scanned": len(rows),
        "rows_with_neighbors": rows_with_neighbors,
        "mean_abs_shift": round(
            total_abs_shift / max(1, rows_with_neighbors), 4),
    }
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({"summary": summary, "rows": diffused},
                      f, default=str, indent=2)
        tmp.replace(out_path)
    except OSError as e:
        return {"skipped": "write failed: %s" % e}
    return summary


# C3 compile-to-procedure thresholds. Conservative on purpose — a procedure
# that fires on the wrong symptom is a runaway with no fuel to second-guess
# it. These thresholds + the procedure store's internal safety envelope
# (impact ≤ 0.2 auto ceiling, governor conf ≥ conf_floor) mean a compiled
# procedure cannot auto-run until calibration has genuinely earned it.
COMPILE_MIN_FIRES = int(os.environ.get("ORION_DREAM_COMPILE_MIN_FIRES", "5"))
COMPILE_MIN_RATE = float(os.environ.get("ORION_DREAM_COMPILE_MIN_RATE", "0.75"))


def _compile_to_procedures() -> dict:
    """Walk the current playbook index; register a compiled procedure for
    every (symptom, service) where the CUSUM success rate and fire count
    both meet the thresholds. Returns {compiled, skipped, reasons}.

    Safety: each registered procedure carries impact=0.05 (well below the
    0.2 auto-ceiling) and conf_floor = the playbook's measured success
    rate — so the executive's fast-path-first hook can match it, but
    execute() refuses to run it until the LIVE governor confidence on
    that symptom meets the floor. Calibration gates fire; the dream just
    earns the candidacy."""
    idx_path = PLAYBOOK_DIR / "_index.json"
    if not idx_path.exists():
        return {"compiled": 0, "skipped": 0, "reason": "no index yet"}
    try:
        with idx_path.open("r", encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"compiled": 0, "skipped": 0, "reason": "index read: %s" % e}
    try:
        import orion_compiled_procedures as cp
    except ImportError:
        return {"compiled": 0, "skipped": 0, "reason": "cp module unavailable"}

    compiled = 0
    skipped = 0
    skipped_reasons: list[str] = []
    for sym, entry in (idx.items() if isinstance(idx, dict) else []):
        if not isinstance(entry, dict):
            continue
        by_service = entry.get("by_service") or {}
        for svc, pb in by_service.items():
            if not pb.get("active", True):
                continue
            succ = int(pb.get("success_count", 0))
            fail = int(pb.get("fail_count", 0))
            total = succ + fail
            if total < COMPILE_MIN_FIRES:
                skipped += 1
                skipped_reasons.append("%s/%s: only %d fires" % (sym, svc, total))
                continue
            rate = succ / max(1, total)
            if rate < COMPILE_MIN_RATE:
                skipped += 1
                skipped_reasons.append("%s/%s: rate %.2f below %.2f" % (sym, svc, rate, COMPILE_MIN_RATE))
                continue
            # Honest minimal step: publish a marker. Real action extraction
            # from the prose playbook body is a follow-up commit; the wiring
            # is the unification win, the body grows over time. The procedure
            # exists so lookup_fast_path returns non-None and the calibration
            # floor logic can fire — but until the body is upgraded with a
            # real dispatch step, this stays a no-op-effective announcement.
            steps = [{
                "kind": "publish",
                "subject": "brain.dream.playbook_referenced",
                "body": {"symptom_class": sym, "service": svc,
                         "success_rate": round(rate, 4),
                         "cited_decision_ids": pb.get("cited_decision_ids") or []},
            }]
            result = cp.register_procedure(
                symptom_class=sym, steps=steps,
                impact=0.05,
                conf_floor=min(0.95, max(0.70, rate)),
                source_decision_ids=pb.get("cited_decision_ids") or [],
            )
            if "error" in result:
                skipped += 1
                skipped_reasons.append("%s/%s: %s" % (sym, svc, result["error"]))
            else:
                compiled += 1
    return {"compiled": compiled, "skipped": skipped,
            "skipped_reasons": skipped_reasons[:10]}


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

    # C3 compile-to-procedure (Gap 2 of unification audit: the procedure
    # store shipped at 2f93d36 had 0 register-callers; the dream is the
    # right writer). For each playbook with sufficient CUSUM success rate
    # AND fire count, register a compiled procedure with HIGH conf_floor
    # and LOW impact so it's safe-by-construction: the executive's fast-
    # path-first will only fire it when the governor's confidence on the
    # symptom is at the playbook's earned level. Until calibration agrees,
    # the procedure exists but never auto-runs.
    #
    # Honest scope: this closes the WIRING gap. Action extraction from
    # prose playbook bodies is a follow-up — the procedure's only step
    # for now is a publish marker (brain.dream.playbook_referenced).
    # The seam exists; the body grows over time as the action extractor
    # is built. Per the founder's 2026-05-24 unification priority.
    compiled_procs = None
    try:
        compiled_procs = _compile_to_procedures()
        if compiled_procs.get("compiled"):
            logger.info("compiled %d playbook(s) → procedures (skipped %d)",
                        compiled_procs["compiled"], compiled_procs["skipped"])
    except Exception as e:
        logger.warning("procedure compile skipped: %s", e)

    # Memory consolidation — turn the growing graph into curated memory.
    # Archive-not-delete: exact-duplicate + empty nodes move to the archive
    # file so the brain learns instead of merely accumulating. Best-effort;
    # never breaks the dream cycle. (Runs nightly when the substrate is idle,
    # so the brain's own save() rarely races it; growth stays bounded either
    # way since consolidation is idempotent.)
    mem_consolidation = None
    try:
        import orion_consolidate
        graph_path = os.path.expanduser(
            os.environ.get("ORION_GRAPH_PATH") or "~/.orion/brain/graph_memory.json")
        mem_consolidation = orion_consolidate.consolidate(graph_path, apply=True)
        _publish_event("brain.dream.memory_consolidated", mem_consolidation)
        logger.info("memory consolidation: %s -> %s (archived %s)",
                    mem_consolidation.get("before"),
                    mem_consolidation.get("after"),
                    mem_consolidation.get("exact_dups_and_empty_archived"))
    except Exception as e:
        logger.warning("memory consolidation skipped: %s", e)

    # Skill curation — the Library-Drift ratchet (synthesis-continual-learning.md
    # C2). Retires low-contribution skills past N_MIN firings, bounds the active
    # set at ACTIVE_CAP, and publishes brain.skills.mean_contribution — the
    # single tripwire that tells us the library is learning (rising/flat) vs
    # rotting (falling). Conservative by construction: untested skills survive.
    skill_curation = None
    try:
        import orion_skill_curator
        skill_curation = orion_skill_curator.curate()
        logger.info("skill curation: %s active (retired %d, evicted %d, mean %s)",
                    skill_curation.get("active_after"),
                    len(skill_curation.get("retired", [])),
                    len(skill_curation.get("evicted_over_cap", [])),
                    skill_curation.get("mean_contribution"))
    except Exception as e:
        logger.warning("skill curation skipped: %s", e)

    # Dream-replay — hippocampal-replay analogue. Sample plausible scenarios
    # weighted by ledger marginals (plus a novelty injector for shapes we've
    # never seen) and play them through the LIVE governor so the brain
    # accumulates calibration BEFORE the next real event. Outcomes land in a
    # SEPARATE sim ledger that orion_metacognition.governor weights at
    # SIM_LEDGER_WEIGHT — and caps at the real-only baseline (honesty floor).
    # brain.sim.drift is the launch tripwire: rising = the world model is
    # hallucinating, caught before it can corrupt learning.
    sim_cycle = None
    try:
        import orion_simulate
        sim_cycle = orion_simulate.run_scenarios()
        logger.info("sim cycle: %d plays (%d novelty), drift=%.3f over %d shapes",
                    sim_cycle.get("plays", 0),
                    sim_cycle.get("novelty_plays", 0),
                    sim_cycle.get("drift", {}).get("mean_drift", 0.0),
                    sim_cycle.get("drift", {}).get("shapes_compared", 0))
    except Exception as e:
        logger.warning("sim cycle skipped: %s", e)

    # Lateral diffusion (CA-style) — supplement each decision's lived outcome
    # with a small contribution from its token-neighbors' outcomes. Per the
    # T4 cognition brief: alpha small (~0.1), original outcome_value NEVER
    # changes, diffused values live in a separate file the governor mixes
    # in at half-weight. Reversible by construction: deleting diffused.json
    # restores the pre-diffusion behavior exactly.
    diffusion = None
    try:
        diffusion = _lateral_diffuse()
        if diffusion:
            logger.info("lateral diffusion: %d rows w/ neighbors (alpha=%.2f, "
                        "mean shift=%.3f)",
                        diffusion.get("rows_with_neighbors", 0),
                        diffusion.get("alpha", 0.0),
                        diffusion.get("mean_abs_shift", 0.0))
            _publish_event("brain.dream.lateral_diffusion", diffusion)
    except Exception as e:
        logger.warning("lateral diffusion skipped: %s", e)

    # HOT-3 refresh — recompute the (symptom, fuel) calibration error map
    # right after the dream changed ledger marginals. Without this, the
    # governor's HOT-3 correction stays stale until the next periodic
    # daemon refresh (~20 min); doing it here closes the loop on the
    # dream's own pass so the next morning's governor() reads the new
    # numbers immediately.
    hot3 = None
    try:
        import orion_metacognition
        hot3 = orion_metacognition.publish_miscalibration()
        logger.info("hot3 refreshed: %d buckets", hot3)
    except Exception as e:
        logger.warning("hot3 refresh skipped: %s", e)

    summary = {
        "ts": time.time(),
        "duration_sec": time.time() - started,
        "decisions_read": len(decisions),
        "groups": len(groups),
        "new_playbooks": new_playbooks,
        "demoted": demoted,
        "memory_consolidation": mem_consolidation,
        "skill_curation": skill_curation,
        "sim_cycle": sim_cycle,
        "lateral_diffusion": diffusion,
        "hot3_buckets": hot3,
        "compiled_procedures": compiled_procs,
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
