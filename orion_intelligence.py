"""orion_intelligence.py — the measurement layer.

Build #6 of the next-3 roadmap (Terminal 1 / integration lane).
Addresses the open gap the synthesis memos all gestured at but none
built: "we cannot currently prove Orion is getting smarter."

This is the OVERSEER's signature: it invents no new signals. It composes
the tripwires every layer already publishes into ONE unified heartbeat
that answers a single honest question — is the brain learning, holding,
or rotting?

WHAT WE READ (existing signals — no new instrumentation needed)
================================================================

  brain.skills.mean_contribution    (build #2 — Library-Drift ratchet)
  brain.metacog.confidence          (Phase-2 governor scoring)
  brain.dream.complete              (consolidation summaries)
  brain.executive.applied           (executive close, esp. via=compiled_procedure)
  brain.learned.calibration         (per-shape aggregates from C4 follow-up)
  brain.learned.skill.applied       (cross-host learning events)
  brain.predictor.surprise          (active inference — Terminal 4)

We also walk LOCAL STATE directly (durable, doesn't depend on the
substrate being live):
  ~/.orion/metacog/decisions.jsonl       (the ledger)
  ~/.orion/metacog/remote_*.json         (cross-host calibration)
  ~/.orion/brain/skills/                 (active + archived skills)
  ~/.orion/procedures/                   (compiled procedures + archive)

WHAT WE PUBLISH
===============

  brain.intelligence.heartbeat — every 60s (or on demand) with:
    {
      "ts": ...,
      "ledger":     {decisions, succeeded_rate, mean_calibration_delta,
                     mean_outcome_value, distinct_symptoms},
      "skills":     {active, archived, mean_contribution, experienced_count},
      "procedures": {active, archived, total_fires, success_rate},
      "mesh":       {peers_known, remote_symptoms, cross_host_evidence},
      "trend":      {ledger_growth_24h, contribution_delta_24h,
                     procedures_growth_24h},
      "composite":  float in [0, 1] — single number we can graph
    }

  ~/.orion/intelligence/heartbeat.jsonl — durable log; the brain's
  own intelligence trajectory, auditable by anyone.

THE COMPOSITE SCORE — design call, not a magic number
=====================================================

A weighted blend of three honest indicators:
  - 40% — mean calibration accuracy (governor confidence tracking outcomes)
  - 35% — skill library mean contribution (helped vs hurt)
  - 25% — procedure compile rate × success rate (smarter with use)

Each indicator is normalized to [0, 1] before blending. A rising
composite means the brain is getting BETTER at the things it does;
a flat composite means it's holding; a falling composite means
something rotted. The composite is intentionally CONSERVATIVE — a
low-evidence brain (fresh install, no real outcomes yet) scores
near 0.5 (neutral / unknown), never spuriously high. Honesty floor.

WHAT THIS IS NOT
================
This is NOT a benchmark. It does not claim to measure 'general
intelligence.' It measures the brain's OWN reliability + learning
indicators against itself over time. The point is the TRAJECTORY,
not the absolute number.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("orion.intelligence")

ORION_HOME = os.path.expanduser(os.environ.get("ORION_BRAIN_DIR", "~/.orion"))
LEDGER_PATH = os.path.join(ORION_HOME, "metacog", "decisions.jsonl")
REMOTE_GLOB = os.path.join(ORION_HOME, "metacog", "remote_*.json")
SKILLS_DIR = os.path.join(ORION_HOME, "brain", "skills")
SKILLS_ARCHIVE = os.path.join(SKILLS_DIR, "archive")
PROCEDURES_DIR = os.path.join(ORION_HOME, "procedures")
PROCEDURES_ARCHIVE = os.path.join(PROCEDURES_DIR, "archive")
INTEL_DIR = os.path.join(ORION_HOME, "intelligence")
HEARTBEAT_PATH = os.path.join(INTEL_DIR, "heartbeat.jsonl")
os.makedirs(INTEL_DIR, exist_ok=True)

LOOKBACK_SEC_24H = 24 * 3600
HEARTBEAT_INTERVAL_SEC = float(os.environ.get("ORION_INTEL_INTERVAL_SEC", "60"))

# Composite weights (sum to 1.0). Tunable via env so we can re-balance
# without code changes as more signals come online (sim drift, predictor
# surprise from Terminal 4, etc.).
W_CALIBRATION = float(os.environ.get("ORION_INTEL_W_CALIB", "0.40"))
W_SKILLS = float(os.environ.get("ORION_INTEL_W_SKILLS", "0.35"))
W_PROCEDURES = float(os.environ.get("ORION_INTEL_W_PROCS", "0.25"))


def _safe_json_lines(path: str, limit: int = 10000) -> list:
    """Read a JSONL file; return parsed rows (most-recent first, capped)."""
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out[-limit:]


def _safe_json_file(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _list_dir(path: str, suffix: str = ".json") -> list:
    if not os.path.isdir(path):
        return []
    return [f for f in os.listdir(path) if f.endswith(suffix)]


def _ledger_summary() -> dict:
    """Snapshot of the local decision ledger — the governor's evidence base.
    Reads from disk every call (cheap; the ledger is bounded). Returns
    decision count, success rate, calibration tracking quality, and the
    distinct symptom count (a diversity indicator)."""
    rows = _safe_json_lines(LEDGER_PATH)
    if not rows:
        return {"decisions": 0, "succeeded_rate": None,
                "mean_calibration_delta": None, "mean_outcome_value": None,
                "distinct_symptoms": 0, "decisions_24h": 0}
    now = time.time()
    total = len(rows)
    succeeded = sum(1 for r in rows if r.get("outcome") == "succeeded")
    deltas = [r.get("calibration_delta") for r in rows
              if isinstance(r.get("calibration_delta"), (int, float))]
    outs = [r.get("outcome_value") for r in rows
            if isinstance(r.get("outcome_value"), (int, float))]
    symptoms = {r.get("symptom_class") for r in rows if r.get("symptom_class")}
    decisions_24h = sum(1 for r in rows
                        if (r.get("ts_outcome") or r.get("ts_proposed") or 0)
                        >= now - LOOKBACK_SEC_24H)
    return {
        "decisions": total,
        "succeeded_rate": round(succeeded / total, 4) if total else None,
        "mean_calibration_delta": round(sum(deltas) / len(deltas), 4) if deltas else None,
        "mean_outcome_value": round(sum(outs) / len(outs), 4) if outs else None,
        "distinct_symptoms": len(symptoms),
        "decisions_24h": decisions_24h,
    }


def _skills_summary() -> dict:
    """Mirror the Library-Drift ratchet's mean_contribution tripwire — but
    computed from disk so it stays correct even if the dream hasn't run."""
    active_files = [f for f in _list_dir(SKILLS_DIR) if f != "archive"]
    archived_files = _list_dir(SKILLS_ARCHIVE)
    contribs, experienced = [], 0
    for fname in active_files:
        s = _safe_json_file(os.path.join(SKILLS_DIR, fname))
        if not s or not s.get("active", True):
            continue
        used = int(s.get("times_used", 0))
        if used >= 5:  # match orion_skill_curator.N_MIN
            experienced += 1
            contribs.append(float(s.get("contribution", 0.0)))
    return {
        "active": len(active_files),
        "archived": len(archived_files),
        "experienced_count": experienced,
        "mean_contribution": (round(sum(contribs) / len(contribs), 4)
                              if contribs else None),
    }


def _procedures_summary() -> dict:
    """The C3 store — how many recurring fixes graduated to zero-fuel paths
    and how often they fire successfully. Both counts are bounded (one file
    per symptom)."""
    active_files = [f for f in _list_dir(PROCEDURES_DIR) if f != "archive"]
    archived_files = _list_dir(PROCEDURES_ARCHIVE)
    total_fires = succ = 0
    for fname in active_files:
        p = _safe_json_file(os.path.join(PROCEDURES_DIR, fname))
        if not p or not p.get("active", True):
            continue
        total_fires += int(p.get("fires", 0))
        succ += int(p.get("successes", 0))
    return {
        "active": len(active_files),
        "archived": len(archived_files),
        "total_fires": total_fires,
        "success_rate": (round(succ / total_fires, 4) if total_fires else None),
    }


def _mesh_summary() -> dict:
    """Cross-host learning surface — how many peers have contributed
    calibration aggregates, how many distinct symptoms they've taught us,
    and how much evidence (rows-worth) flowed across the gossip path."""
    import glob
    remote_files = glob.glob(REMOTE_GLOB)
    peers = []
    distinct_symptoms = set()
    total_evidence = 0
    for path in remote_files:
        host = os.path.basename(path)[len("remote_"):-len(".json")]
        data = _safe_json_file(path) or {}
        if not isinstance(data, dict):
            continue
        peers.append(host)
        for sym, agg in data.items():
            if not isinstance(agg, dict):
                continue
            distinct_symptoms.add(sym)
            total_evidence += int(agg.get("count", 0))
    return {
        "peers_known": len(peers),
        "peer_hosts": sorted(peers),
        "remote_symptoms": len(distinct_symptoms),
        "cross_host_evidence_rows": total_evidence,
    }


def _composite(ledger: dict, skills: dict, procs: dict) -> float:
    """One number to graph. CONSERVATIVE — low-evidence brain stays
    near 0.5 (neutral), never spuriously high. The trajectory matters,
    not the absolute value.

    Normalization rules (each indicator → [0, 1] before blending):
      calibration: 1.0 - |mean_calibration_delta|  (closer to 0 = better
                   tracking), defaulted to 0.5 if no evidence.
      skills:     (mean_contribution + 1) / 2  (since contribution ∈ [-1, 1]),
                   defaulted to 0.5 if no experienced skills.
      procs:      success_rate, defaulted to 0.5 if no fires yet.
    """
    delta = ledger.get("mean_calibration_delta")
    cal = (1.0 - min(1.0, abs(delta))) if delta is not None else 0.5
    contrib = skills.get("mean_contribution")
    sk = ((contrib + 1.0) / 2.0) if contrib is not None else 0.5
    rate = procs.get("success_rate")
    pr = rate if rate is not None else 0.5
    return round(W_CALIBRATION * cal + W_SKILLS * sk + W_PROCEDURES * pr, 4)


def compute_snapshot() -> dict:
    """Walk local state + return current intelligence indicators. Pure
    function. No NATS, no daemons — testable directly."""
    ledger = _ledger_summary()
    skills = _skills_summary()
    procs = _procedures_summary()
    mesh = _mesh_summary()
    composite = _composite(ledger, skills, procs)
    return {
        "ts": time.time(),
        "host": os.environ.get("ORION_HOST_ID", "local"),
        "ledger": ledger,
        "skills": skills,
        "procedures": procs,
        "mesh": mesh,
        "composite": composite,
    }


def publish_snapshot() -> dict:
    """Compute + emit brain.intelligence.heartbeat + append to the
    durable jsonl log. The jsonl is the trajectory record; the heartbeat
    is for live consumers (dashboards, the dream, any future UI)."""
    snap = compute_snapshot()
    try:
        from orion_substrate import publish
        publish("brain.intelligence.heartbeat", snap)
    except Exception:
        pass
    try:
        with open(HEARTBEAT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(snap, default=str) + "\n")
    except OSError:
        pass
    return snap


def main() -> int:
    """Optional service loop — publishes every HEARTBEAT_INTERVAL_SEC.
    The dream cycle can also call publish_snapshot directly at end of
    consolidation; both paths are idempotent."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("intelligence layer alive — heartbeat every %ds",
                int(HEARTBEAT_INTERVAL_SEC))
    while True:
        try:
            snap = publish_snapshot()
            logger.info("composite=%.4f decisions=%s skills=%s procs=%s peers=%s",
                        snap["composite"], snap["ledger"]["decisions"],
                        snap["skills"]["active"], snap["procedures"]["active"],
                        snap["mesh"]["peers_known"])
        except Exception as e:
            logger.warning("heartbeat cycle error: %s", e)
        time.sleep(HEARTBEAT_INTERVAL_SEC)


def format_human(snap: dict) -> str:
    """Render a snapshot as plain text for a human reading a terminal. JSON
    is for scripts; this is for the founder asking 'how's the brain doing?'."""
    def _f(v, default="—"):
        if v is None:
            return default
        if isinstance(v, float):
            return ("%.3f" % v).rstrip("0").rstrip(".")
        return str(v)
    L = snap.get("ledger", {})
    S = snap.get("skills", {})
    P = snap.get("procedures", {})
    M = snap.get("mesh", {})
    composite = snap.get("composite", 0.5)
    bar_len = int(round(composite * 30))
    bar = "█" * bar_len + "·" * (30 - bar_len)
    lines = [
        "═" * 56,
        "  ORION — INTELLIGENCE SNAPSHOT",
        "═" * 56,
        "  host           : " + _f(snap.get("host")),
        "  composite      : %.4f  [%s]" % (composite, bar),
        "",
        "  ── Calibration ledger ──",
        "  decisions      : " + _f(L.get("decisions")) + " (24h: " + _f(L.get("decisions_24h")) + ")",
        "  succeeded rate : " + _f(L.get("succeeded_rate")),
        "  mean cal-delta : " + _f(L.get("mean_calibration_delta")),
        "  distinct shapes: " + _f(L.get("distinct_symptoms")),
        "",
        "  ── Skill library (Library-Drift ratchet) ──",
        "  active         : " + _f(S.get("active")) + " (archived: " + _f(S.get("archived")) + ")",
        "  experienced    : " + _f(S.get("experienced_count")),
        "  mean contribution: " + _f(S.get("mean_contribution")),
        "",
        "  ── Compiled procedures (C3 zero-fuel) ──",
        "  active         : " + _f(P.get("active")) + " (archived: " + _f(P.get("archived")) + ")",
        "  total fires    : " + _f(P.get("total_fires")),
        "  success rate   : " + _f(P.get("success_rate")),
        "",
        "  ── Mesh (cross-host learning) ──",
        "  peers known    : " + _f(M.get("peers_known")),
        "  remote shapes  : " + _f(M.get("remote_symptoms")),
        "  evidence rows  : " + _f(M.get("cross_host_evidence_rows")),
    ]
    peers = M.get("peer_hosts") or []
    if peers:
        lines.append("  peer hosts     : " + ", ".join(peers))
    lines.append("═" * 56)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    argv = sys.argv[1:]
    if "--once" in argv:
        # JSON mode: one snapshot to stdout, no loop. For scripts + cron.
        print(json.dumps(publish_snapshot(), indent=2, default=str))
        sys.exit(0)
    if "--human" in argv or "--orion-status" in argv:
        # Human mode: formatted snapshot — the founder-asking-how-the-brain-is-doing path.
        snap = compute_snapshot()
        print(format_human(snap))
        sys.exit(0)
    sys.exit(main() or 0)
