"""orion_metacognition.py — the HOT-2 metacognitive write-back loop.

Per the v2 consciousness research (docs/architecture/consciousness-
research-v2.md), this is **Rank 1** of the recommended architectural
moves. It has the strongest current empirical legs: Anthropic's
October 2025 introspection paper (Lindsey et al.) showed Claude Opus 4.1
can detect concept-injected activations ~20% of the time and distinguish
its own outputs from artificial prefills. That capacity emerged with
scale and has no current mechanistic story.

We can't do residual-stream injection on a black-box fuel model. But we
CAN do the architectural equivalent: every decision Orion makes gets a
*before-confidence* and *after-outcome* score, archived to a ledger,
queryable next time a similar question shows up. The system observes
its own judgments and learns its own calibration.

WHAT THIS LAYER DOES
====================

Five pieces, each small, composing into metacognition:

1. PRE-DECISION SCORING — when the executive publishes
   brain.executive.proposal, this layer scores confidence BEFORE the
   action runs. Score = combination of:
     - recall hit-rate for the symptom class
     - prior outcome rate on similar decisions (from ledger)
     - novelty (have we seen this exact symptom before?)
     - fuel quality (which model is fueling this decision)
   Published on brain.metacog.confidence with {decision_id, conf, basis}.

2. POST-DECISION SCORING — when the executive publishes
   brain.executive.outcome, this layer reads the outcome (succeeded/
   failed/ignored), computes calibration_delta = outcome_value -
   conf_before, and appends a ledger row.

3. CONFIDENCE-AWARE RECALL — when any service publishes
   brain.recall.requested, this layer surfaces past ledger entries on
   similar questions on brain.metacog.recall_meta with
   {query, prior_judgments[], avg_confidence, avg_outcome}. The asking
   service can use this to ground its own response.

4. WORKSPACE SURPRISE FEEDBACK — when confidence is low (< THRESHOLD)
   OR when calibration_delta is large (|delta| > 0.5), publish
   workspace.feedback with surprise=1.0 to push the item up the
   workspace ranking next tick. Low-confidence things deserve more
   attention; mis-calibrated things deserve even more.

5. PERIODIC SELF-PROBE — every PROBE_SEC seconds, publish
   brain.metacog.self_probe asking "what state are you in right now?"
   The will/executive subscribers can respond by publishing
   brain.metacog.self_report; whatever lands gets archived. This is
   the closest software equivalent of concept-injection: forcing the
   system to attend to its own attention and store the result.

LEDGER FORMAT (append-only JSONL at ~/.orion/metacog/decisions.jsonl)
====================================================================

  {
    "decision_id": "exec-<uuid>",
    "symptom_class": "SERVICE_LOOP",
    "proposed_action": "...",
    "conf_before": 0.62,
    "basis": ["recall:3/4 similar succeeded", "fuel:claude-opus", "novelty:0.2"],
    "fuel": "claude-opus-4-7",
    "outcome": "succeeded" | "failed" | "ignored" | "denied",
    "outcome_value": 1.0 | 0.0 | 0.5,
    "calibration_delta": 0.38,
    "ts_proposed": 1747...,
    "ts_outcome": 1747...
  }

The ledger is the durable artifact. Everything else is derivable.
Future Orion versions read this on boot and inherit calibration.

NOT a replacement for the executive — the executive still proposes
and the user still grants permission. This sits BESIDE the executive,
scoring its own confidence and learning from outcomes.

HOT-2: every decision is now a higher-order thought *about* a
first-order action, with an outcome that grounds the higher-order
thought. That is the actual minimal definition of metacognition.

Honest caveat: this is not phenomenal consciousness. It is functional
metacognition — calibration-awareness as engineering. The 20%
introspection rate from Lindsey et al. is our ceiling, not our floor.
Design for unreliability.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import signal
import sys
import time
import uuid
from collections import deque, defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orion.metacog")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR") or str(Path.home() / ".orion"))
LEDGER_DIR = ORION_HOME / "metacog"
LEDGER_PATH = LEDGER_DIR / "decisions.jsonl"
PROBE_SEC = float(os.environ.get("ORION_METACOG_PROBE_SEC", "300"))  # 5min default
LOW_CONF_THRESHOLD = float(os.environ.get("ORION_METACOG_LOW_CONF", "0.35"))
MISCAL_THRESHOLD = float(os.environ.get("ORION_METACOG_MISCAL", "0.5"))
SIMILARITY_K = int(os.environ.get("ORION_METACOG_SIM_K", "5"))  # nearest neighbors in ledger
LEDGER_CACHE_MAX = int(os.environ.get("ORION_METACOG_CACHE_MAX", "2000"))

OUTCOME_VALUE = {"succeeded": 1.0, "failed": 0.0, "ignored": 0.3, "denied": 0.5}


# ─────────────────────────────────────────────────────────
# Ledger — append-only JSONL with in-memory cache
# ─────────────────────────────────────────────────────────

_ledger_cache: deque[dict] = deque(maxlen=LEDGER_CACHE_MAX)
_pending_decisions: dict[str, dict] = {}  # decision_id → row, awaiting outcome


def _load_ledger() -> None:
    """Read existing ledger into the in-memory cache on startup."""
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    if not LEDGER_PATH.exists():
        return
    count = 0
    try:
        with LEDGER_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    _ledger_cache.append(json.loads(line))
                    count += 1
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning("ledger read failed: %s", e)
    logger.info("ledger loaded: %d rows", count)


def _append_ledger(row: dict) -> None:
    """Append a complete row to the ledger + in-memory cache."""
    try:
        with LEDGER_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except OSError as e:
        logger.warning("ledger write failed: %s", e)
    _ledger_cache.append(row)


# ─────────────────────────────────────────────────────────
# Similarity — match a query/symptom to past ledger rows
# ─────────────────────────────────────────────────────────

def _tokens(s: str) -> set[str]:
    return {t for t in (s or "").lower().replace("/", " ").replace("_", " ").split() if len(t) > 2}


def _similar_rows(symptom: str, action: str, k: int = SIMILARITY_K) -> list[dict]:
    """Cheap Jaccard over the symptom_class + action tokens. Good enough
    pre-launch; later we swap in vector recall through orion_brain."""
    target = _tokens(symptom) | _tokens(action)
    if not target:
        return []
    scored: list[tuple[float, dict]] = []
    for row in _ledger_cache:
        if "outcome" not in row:
            continue
        candidate = _tokens(row.get("symptom_class", "")) | _tokens(row.get("proposed_action", ""))
        if not candidate:
            continue
        inter = len(target & candidate)
        union = len(target | candidate)
        if union == 0:
            continue
        sim = inter / union
        if sim > 0:
            scored.append((sim, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:k]]


# ─────────────────────────────────────────────────────────
# Confidence scoring
# ─────────────────────────────────────────────────────────

# Fuel-quality prior — we trust frontier CLIs more than tiny local models.
# Numbers are PRIORS not measurements; they get updated as the ledger fills.
FUEL_PRIOR = {
    "claude": 0.75,
    "claude-opus": 0.80,
    "claude-sonnet": 0.75,
    "codex": 0.70,
    "gpt": 0.70,
    "gemini": 0.65,
    "ollama": 0.50,
    "qwen": 0.55,
    "mistral": 0.50,
    "phi": 0.45,
    "deepseek": 0.55,
    "llama": 0.50,
}


def _fuel_prior(fuel: str) -> float:
    if not fuel:
        return 0.6
    f = fuel.lower()
    for key, val in FUEL_PRIOR.items():
        if key in f:
            return val
    return 0.6


def _score_confidence(proposal: dict) -> tuple[float, list[str]]:
    """Return (conf_in_[0,1], basis_lines[])."""
    symptom = proposal.get("symptom_class", "UNRECOGNIZED")
    action = proposal.get("proposed_action") or proposal.get("action") or ""
    fuel = proposal.get("fuel") or proposal.get("model") or ""

    basis: list[str] = []
    similar = _similar_rows(symptom, action)

    # Prior-outcome rate on similar decisions.
    if similar:
        outcomes = [OUTCOME_VALUE.get(r.get("outcome"), 0.5) for r in similar]
        prior = sum(outcomes) / len(outcomes)
        basis.append(f"recall:{sum(1 for o in outcomes if o > 0.5)}/{len(outcomes)} similar succeeded")
    else:
        prior = 0.5
        basis.append("recall:no prior similar decisions")

    # Novelty — if we've never seen this exact symptom, we're less confident.
    seen_exact = sum(1 for r in _ledger_cache if r.get("symptom_class") == symptom)
    if seen_exact == 0:
        novelty_penalty = 0.15
        basis.append("novelty:never-seen-symptom (-0.15)")
    elif seen_exact < 3:
        novelty_penalty = 0.05
        basis.append(f"novelty:rare-symptom ({seen_exact} prior) (-0.05)")
    else:
        novelty_penalty = 0.0
        basis.append(f"novelty:familiar ({seen_exact} prior)")

    # Fuel quality prior.
    fuel_w = _fuel_prior(fuel)
    basis.append(f"fuel:{fuel or 'unknown'} (prior {fuel_w:.2f})")

    # Combine: weighted average of prior + fuel, minus novelty penalty.
    raw = (prior * 0.65) + (fuel_w * 0.35) - novelty_penalty
    conf = max(0.05, min(0.95, raw))  # clip to [0.05, 0.95] — never claim certainty
    basis.append(f"final:{conf:.2f}")

    return conf, basis


# ─────────────────────────────────────────────────────────
# NATS plumbing
# ─────────────────────────────────────────────────────────

async def _on_executive_proposal(nc, msg) -> None:
    try:
        proposal = json.loads(msg.data.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return
    decision_id = proposal.get("decision_id") or proposal.get("id") or f"exec-{uuid.uuid4().hex[:12]}"
    conf, basis = _score_confidence(proposal)

    row = {
        "decision_id": decision_id,
        "symptom_class": proposal.get("symptom_class", "UNRECOGNIZED"),
        "proposed_action": proposal.get("proposed_action") or proposal.get("action") or "",
        "conf_before": conf,
        "basis": basis,
        "fuel": proposal.get("fuel") or proposal.get("model") or "",
        "ts_proposed": time.time(),
    }
    _pending_decisions[decision_id] = row

    out = {"decision_id": decision_id, "conf": conf, "basis": basis,
           "symptom_class": row["symptom_class"], "ts": row["ts_proposed"]}
    await nc.publish("brain.metacog.confidence", json.dumps(out).encode("utf-8"))

    # If we're under-confident, ask the workspace to attend harder.
    if conf < LOW_CONF_THRESHOLD:
        fb = {"subject": "brain.executive.proposal", "surprise": 1.0,
              "reason": f"low_confidence:{conf:.2f}", "decision_id": decision_id}
        await nc.publish("workspace.feedback", json.dumps(fb).encode("utf-8"))

    logger.info("scored proposal %s conf=%.2f symptom=%s",
                decision_id, conf, row["symptom_class"])


async def _on_executive_outcome(nc, msg) -> None:
    try:
        outcome_msg = json.loads(msg.data.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return
    decision_id = outcome_msg.get("decision_id") or outcome_msg.get("id")
    if not decision_id or decision_id not in _pending_decisions:
        return

    row = _pending_decisions.pop(decision_id)
    outcome = outcome_msg.get("outcome", "ignored")
    outcome_value = OUTCOME_VALUE.get(outcome, 0.5)
    calibration_delta = outcome_value - row["conf_before"]

    row["outcome"] = outcome
    row["outcome_value"] = outcome_value
    row["calibration_delta"] = calibration_delta
    row["ts_outcome"] = time.time()
    _append_ledger(row)

    # Strong miscalibration → tell the workspace this is worth attending to.
    if abs(calibration_delta) > MISCAL_THRESHOLD:
        fb = {"subject": "brain.executive.outcome", "surprise": 1.0,
              "reason": f"miscalibrated:{calibration_delta:+.2f}",
              "decision_id": decision_id}
        await nc.publish("workspace.feedback", json.dumps(fb).encode("utf-8"))

    logger.info("ledgered decision %s outcome=%s delta=%+.2f",
                decision_id, outcome, calibration_delta)


async def _on_recall_requested(nc, msg) -> None:
    """Publish past judgments on similar questions so the asking
    service can ground its response in calibration history."""
    try:
        req = json.loads(msg.data.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return
    query = req.get("query") or req.get("question") or ""
    if not query:
        return
    similar = _similar_rows(symptom=query, action="", k=SIMILARITY_K)
    if not similar:
        out = {"query": query, "prior_judgments": [], "avg_confidence": None,
               "avg_outcome": None, "note": "no_prior_similar"}
    else:
        confs = [r["conf_before"] for r in similar if "conf_before" in r]
        outs = [r["outcome_value"] for r in similar if "outcome_value" in r]
        out = {
            "query": query,
            "prior_judgments": [
                {"symptom_class": r.get("symptom_class"),
                 "proposed_action": r.get("proposed_action", "")[:120],
                 "conf_before": r.get("conf_before"),
                 "outcome": r.get("outcome"),
                 "calibration_delta": r.get("calibration_delta")}
                for r in similar
            ],
            "avg_confidence": (sum(confs) / len(confs)) if confs else None,
            "avg_outcome": (sum(outs) / len(outs)) if outs else None,
        }
    await nc.publish("brain.metacog.recall_meta",
                     json.dumps(out, default=str).encode("utf-8"))


async def _self_probe_loop(nc) -> None:
    """Every PROBE_SEC seconds, ask the brain to attend to its own
    attention. Subscribers (will / executive) can respond with a
    self-report on brain.metacog.self_report; whatever lands gets
    archived as a memory candidate."""
    probe_id = 0
    while True:
        try:
            probe_id += 1
            payload = {
                "probe_id": probe_id,
                "ts": time.time(),
                "question": "What state are you in right now? What is most active?",
                "instruction": (
                    "Respond on brain.metacog.self_report with a short JSON "
                    "{state, most_active, surprises[], confidence}. "
                    "This is HOT-2 — a higher-order thought about your "
                    "first-order activity."
                ),
            }
            await nc.publish("brain.metacog.self_probe",
                             json.dumps(payload).encode("utf-8"))
            logger.debug("self_probe %d emitted", probe_id)
        except Exception as e:
            logger.warning("self_probe emit failed: %s", e)
        await asyncio.sleep(PROBE_SEC)


async def _on_self_report(nc, msg) -> None:
    """Archive whatever the self-probe receivers report. Goes on the
    workspace AND into a self-reports JSONL for offline review."""
    try:
        report = json.loads(msg.data.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return
    report["received_at"] = time.time()
    path = LEDGER_DIR / "self_reports.jsonl"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report, default=str) + "\n")
    except OSError as e:
        logger.warning("self_report archive failed: %s", e)
    # Surface to workspace as a memory-stored candidate.
    cand = {"kind": "self_report", "summary": str(report.get("state", ""))[:160],
            "ts": report["received_at"]}
    await nc.publish("brain.memory.stored", json.dumps(cand).encode("utf-8"))


# ─────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────

async def main() -> int:
    logging.basicConfig(
        level=os.environ.get("ORION_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _load_ledger()

    try:
        from nats.aio.client import Client as NATS  # type: ignore
    except ImportError:
        logger.error("nats-py not installed — run: pip install nats-py")
        return 2

    nc = NATS()

    async def err_cb(e):
        logger.warning("nats error: %s", e)

    async def disc_cb():
        logger.warning("nats disconnected")

    async def recon_cb():
        logger.info("nats reconnected")

    await nc.connect(
        servers=[NATS_URL],
        error_cb=err_cb,
        disconnected_cb=disc_cb,
        reconnected_cb=recon_cb,
        max_reconnect_attempts=-1,
    )
    logger.info("metacog connected to %s", NATS_URL)

    async def _cb_proposal(m):
        await _on_executive_proposal(nc, m)

    async def _cb_outcome(m):
        await _on_executive_outcome(nc, m)

    async def _cb_recall(m):
        await _on_recall_requested(nc, m)

    async def _cb_self_report(m):
        await _on_self_report(nc, m)

    await nc.subscribe("brain.executive.proposal", cb=_cb_proposal)
    await nc.subscribe("brain.executive.outcome", cb=_cb_outcome)
    await nc.subscribe("brain.recall.requested", cb=_cb_recall)
    await nc.subscribe("brain.metacog.self_report", cb=_cb_self_report)

    probe_task = asyncio.create_task(_self_probe_loop(nc))

    stop = asyncio.Event()

    def _shutdown(*_):
        logger.info("metacog shutting down")
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown)
            except NotImplementedError:
                pass  # Windows
    except RuntimeError:
        pass

    await stop.wait()
    probe_task.cancel()
    await nc.drain()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
