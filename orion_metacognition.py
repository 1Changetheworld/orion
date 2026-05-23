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
import glob
import hashlib
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

# HOT-3 — calibration of calibration. Bucket the ledger by (symptom, fuel)
# and track the gap between mean conf_before and mean outcome_value per
# bucket. Per docs/architecture/frontier-self-model.md Signal D, this is
# OUTCOME-grounded (the strongest evidence the brain gets for free), so the
# correction earns the right to both LOWER and (modestly) RAISE governor
# confidence — unlike fuel self-report (Signal E), which is lowering-only.
# The upward correction is bounded ~5× tighter than the downward correction
# so a freak run of easy successes can't unlock autonomy: fail-safe by
# construction. The thresholds are tunable via env so the calibration math
# can be tightened or loosened operationally without a code change.
HOT3_INTERVAL_SEC = float(os.environ.get("ORION_METACOG_HOT3_SEC", "1200"))
HOT3_MIN_N = int(os.environ.get("ORION_METACOG_HOT3_MIN_N", "5"))
HOT3_SIGNIFICANT = float(os.environ.get("ORION_METACOG_HOT3_SIG", "0.2"))
HOT3_MAX_DOWN = float(os.environ.get("ORION_METACOG_HOT3_DOWN", "0.5"))
HOT3_MAX_UP = float(os.environ.get("ORION_METACOG_HOT3_UP", "0.10"))
MISCAL_PATH = LEDGER_DIR / "miscalibration.json"
# Lateral-diffusion supplement written by orion_dream's nightly consolidation.
# Reversible by construction: the original outcome_value never changes;
# diffused values live in a separate file the governor mixes in at half-
# weight so this supplements but never replaces lived outcomes.
DIFFUSED_PATH = LEDGER_DIR / "diffused.json"
# Sim ledger — written ONLY by orion_simulate, never by record_outcome. Kept
# in a separate file (not just a flag) so the boundary between imagination
# and lived experience is enforced at the filesystem level: a confused caller
# can pollute the sim ledger but cannot pretend to have lived a real outcome.
SIM_LEDGER_PATH = LEDGER_DIR / "sim_decisions.jsonl"
# Sim row weight in helped/hurt ratios. 0.3 matches the Terminal-2 brief —
# small enough that one real row dominates any handful of sim rows, large
# enough that an empty real ledger can still earn provisional calibration.
SIM_LEDGER_WEIGHT = float(os.environ.get("ORION_METACOG_SIM_WEIGHT", "0.3"))

OUTCOME_VALUE = {"succeeded": 1.0, "failed": 0.0, "ignored": 0.3, "denied": 0.5}


# ─────────────────────────────────────────────────────────
# Ledger — append-only JSONL with in-memory cache
# ─────────────────────────────────────────────────────────

_ledger_cache: deque[dict] = deque(maxlen=LEDGER_CACHE_MAX)
# Sim rows live in their OWN cache, never interleaved with real rows in
# _ledger_cache, so any code path that needs "real only" is a pure read of
# _ledger_cache with no filter logic. The honesty floor in governor() relies
# on this separation being trivially auditable.
_sim_ledger_cache: deque[dict] = deque(maxlen=LEDGER_CACHE_MAX)
_pending_decisions: dict[str, dict] = {}  # decision_id → row, awaiting outcome
_ledger_loaded = False  # idempotency guard so we read the JSONL exactly once
_sim_ledger_mtime: float = 0.0  # detect sim ledger growth between governor calls


def _load_ledger() -> None:
    """Read existing ledger into the in-memory cache on startup."""
    global _ledger_loaded
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    _ledger_loaded = True
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


def _load_sim_ledger() -> None:
    """Read (or re-read on growth) the sim ledger into _sim_ledger_cache.
    Sim outcomes are written by orion_simulate in a SEPARATE process from
    the metacog daemon, so a one-shot load at startup would leave governor()
    blind to imagination accumulated since boot. Cheap mtime check on every
    call refreshes the cache only when the file actually grew."""
    global _sim_ledger_mtime
    if not SIM_LEDGER_PATH.exists():
        _sim_ledger_mtime = 0.0
        return
    try:
        current_mtime = SIM_LEDGER_PATH.stat().st_mtime
        if current_mtime == _sim_ledger_mtime and _sim_ledger_cache:
            return  # unchanged since last read
        _sim_ledger_cache.clear()
        count = 0
        with SIM_LEDGER_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    row["source"] = "sim"  # never trust an absent tag
                    _sim_ledger_cache.append(row)
                    count += 1
                except json.JSONDecodeError:
                    continue
        _sim_ledger_mtime = current_mtime
        logger.debug("sim ledger reloaded: %d rows", count)
    except OSError as e:
        logger.debug("sim ledger read failed: %s", e)


def _ensure_ledger_loaded() -> None:
    """Lazy-load the durable ledger the first time a non-daemon process consults
    it. The NATS daemon loads in main(); but governor()/record_outcome() are
    called inline from OTHER processes (mesh_recovery, dispatch, self-heal) that
    never run main(). Without this they'd read an empty cache and the governor
    could never earn calibration from the durable JSONL. Idempotent.

    The sim ledger is refreshed on every call (cheap mtime check) so the
    governor sees imagination accumulated between calls in a long-lived
    process — without this only the first governor() in a daemon would see
    sim data."""
    if not _ledger_loaded:
        _load_ledger()
    _load_sim_ledger()


# ─────────────────────────────────────────────────────────
# C4 follow-up — CROSS-HOST CALIBRATION AGGREGATES
# Raw ledger rows are too high-volume for the LWWMap (one key per
# decision = thousands over time). Aggregates are bounded by distinct
# symptom_class values (~dozens), and the governor's _similar_rows()
# math is count-based — so aggregates are information-preserving for
# the gate. Per synthesis-continual-learning.md C4.
# ─────────────────────────────────────────────────────────


def aggregate_local_ledger() -> dict:
    """Compute per-symptom calibration aggregates from the local ledger.
    Returns {symptom_class: {count, succeeded, failed, mean_outcome,
    last_updated, content_hash}}. The content_hash collapses identical
    aggregates so the LWWMap's same-HLC branch correctly treats two
    hosts publishing the same numbers as duplicates rather than as
    conflicts."""
    _ensure_ledger_loaded()
    buckets: dict = {}
    for row in _ledger_cache:
        sym = row.get("symptom_class")
        if not sym or "outcome" not in row:
            continue
        b = buckets.setdefault(sym, {
            "symptom_class": sym, "count": 0,
            "succeeded": 0, "failed": 0,
            "outcome_sum": 0.0, "last_updated": 0.0,
        })
        b["count"] += 1
        if row.get("outcome") == "succeeded":
            b["succeeded"] += 1
        elif row.get("outcome") == "failed":
            b["failed"] += 1
        b["outcome_sum"] += float(row.get("outcome_value", 0.0))
        ts = float(row.get("ts_outcome") or row.get("ts_proposed") or 0.0)
        if ts > b["last_updated"]:
            b["last_updated"] = ts
    out: dict = {}
    for sym, b in buckets.items():
        b["mean_outcome"] = round(b["outcome_sum"] / max(1, b["count"]), 4)
        del b["outcome_sum"]
        b["content_hash"] = hashlib.sha256(
            ("%s|%d|%d|%d|%.4f" % (sym, b["count"], b["succeeded"],
                                    b["failed"], b["mean_outcome"])).encode()
        ).hexdigest()[:12]
        out[sym] = b
    return out


def publish_aggregates() -> int:
    """Publish each per-symptom aggregate on brain.learned.calibration so
    orion_gossip puts them into the LWWMap. Called by orion_dream nightly.
    Best-effort — substrate outage never breaks the local ledger."""
    aggs = aggregate_local_ledger()
    try:
        from orion_substrate import publish
    except Exception:
        return 0
    n = 0
    for sym, body in aggs.items():
        try:
            publish("brain.learned.calibration", {
                "symptom_class": sym, "payload": body,
                "ts": time.time(),
            })
            n += 1
        except Exception:
            continue
    return n


def _load_remote_aggregates() -> dict:
    """Read remote calibration aggregates the learning_sync wrote out.
    One file per peer host (~/.orion/metacog/remote_<host>.json). Returns
    {symptom_class: [{host, count, succeeded, failed, ...}, ...]} so the
    governor can audit which peer contributed which evidence."""
    out: dict = {}
    for path in glob.glob(str(LEDGER_DIR / "remote_*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f) or {}
            host = os.path.basename(path)[len("remote_"):-len(".json")]
            if not isinstance(data, dict):
                continue
            for sym, agg in data.items():
                if not isinstance(agg, dict):
                    continue
                row = dict(agg); row["host"] = host
                out.setdefault(sym, []).append(row)
        except Exception:
            continue
    return out


def record_outcome(action: str, outcome: str, *, symptom: str = "",
                   conf_before: Optional[float] = None, fuel: str = "",
                   decision_id: Optional[str] = None, **extra) -> dict:
    """Append a COMPLETED decision row to the ledger directly (no NATS).

    This is how autonomic deciders that don't go through the executive's
    proposal/outcome NATS dance — mesh_recovery, self-heal, dispatch — feed
    real action outcomes back into the calibration ledger. It is the write
    side of 'calibration as a learned skill': governor() reads what this
    writes, so the gate EARNS trust (or loses it) from lived outcomes instead
    of being frozen at the risk-class base. `outcome` ∈ OUTCOME_VALUE keys
    (succeeded|failed|ignored|denied); anything else is coerced to 'ignored'.
    Pass the SAME `action` + `symptom` strings used in the governor() call so
    the Jaccard match in _similar_rows() actually fires next time."""
    _ensure_ledger_loaded()
    if outcome not in OUTCOME_VALUE:
        outcome = "ignored"
    ov = OUTCOME_VALUE[outcome]
    row = {
        "decision_id": decision_id or ("auto-%s" % uuid.uuid4().hex[:12]),
        "symptom_class": symptom or "UNRECOGNIZED",
        "proposed_action": action,
        "conf_before": conf_before,
        "basis": extra.pop("basis", []),
        "fuel": fuel,
        "outcome": outcome,
        "outcome_value": ov,
        "calibration_delta": (ov - conf_before) if conf_before is not None else None,
        "ts_proposed": extra.pop("ts_proposed", time.time()),
        "ts_outcome": time.time(),
    }
    row.update(extra)
    _append_ledger(row)
    logger.info("recorded outcome %s: %s -> %s (delta %s)", row["decision_id"],
                (symptom or action)[:48], outcome, row["calibration_delta"])
    return row


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


def _similar_rows(symptom: str, action: str, k: int = SIMILARITY_K,
                  include_sim: bool = True) -> list[dict]:
    """Cheap Jaccard over the symptom_class + action tokens. Good enough
    pre-launch; later we swap in vector recall through orion_brain.

    include_sim=True (default) interleaves sim ledger rows with real ones;
    the governor consumer is expected to weight them via _row_weight.
    include_sim=False is the real-only baseline the honesty floor needs to
    enforce 'sim may lower, never raise'."""
    target = _tokens(symptom) | _tokens(action)
    if not target:
        return []
    scored: list[tuple[float, dict]] = []
    # Real ledger always; sim ledger only when the caller wants it. The
    # governor calls this BOTH ways every decision (once for the combined
    # arm, once for the real-only baseline that enforces the honesty floor)
    # so a real-only invocation must never reach the sim cache.
    sources: list = [_ledger_cache]
    if include_sim:
        sources.append(_sim_ledger_cache)
    for cache in sources:
        for row in cache:
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
    # Tie-break identical-similarity rows by RECENCY: when many past decisions
    # share the same action+symptom tokens (the common case for a recurring
    # autonomic fix), the K-window must reflect the device's CURRENT reliability,
    # not its oldest history — otherwise a fixed device can never earn auto back.
    def _row_ts(r: dict) -> float:
        return float(r.get("ts_outcome") or r.get("ts_proposed") or 0.0)
    scored.sort(key=lambda x: (x[0], _row_ts(x[1])), reverse=True)
    return [r for _, r in scored[:k]]


def _row_weight(row: dict) -> float:
    """Sim rows weigh SIM_LEDGER_WEIGHT (0.3 by default); real rows weigh 1.0.
    The governor consults this so a handful of imagined trials cannot outvote
    even a single lived outcome on the same shape."""
    return SIM_LEDGER_WEIGHT if row.get("source") == "sim" else 1.0


# ═══════════════════════════════════════════════════════════════
# HOT-3 — calibration of calibration (a thought ABOUT confidence)
# ═══════════════════════════════════════════════════════════════
# HOT-2 (the rest of this file) scores each decision against its outcome.
# HOT-3 asks the next-higher-order question: ARE THE CONFIDENCE NUMBERS
# THEMSELVES CALIBRATED on each (symptom, fuel) shape? The governor reads
# this and applies a multiplicative correction — overconfident shapes get
# discounted, under-confident shapes get a modest boost. Outcome-grounded
# (Signal D), so the correction may legitimately move in either direction,
# but the upward correction is bounded ~5× tighter than the downward
# correction so a freak run of easy successes cannot unlock autonomy.

_miscal_cache: dict = {}   # bucket_key → {n, mean_conf, mean_outcome, miscal_err, ...}
_diffused_cache: dict = {} # decision_id → {outcome_value, diffused_value, neighbors_n}


def _miscal_key(symptom: str, fuel: str) -> str:
    """HOT-3 bucket key: (symptom, fuel-family). Fuel is coarsened to its
    family (anything containing 'claude' → 'claude') so a single bucket
    accumulates enough N to be statistically meaningful — distinguishing
    claude-opus-4-7 from claude-opus-4-7[1m] would scatter outcomes across
    too many buckets to ever cross HOT3_MIN_N."""
    f = (fuel or "unknown").lower()
    for family in ("claude", "codex", "gpt", "gemini", "ollama",
                   "qwen", "mistral", "phi", "deepseek", "llama"):
        if family in f:
            f = family
            break
    return f"{symptom or 'UNRECOGNIZED'}|{f}"


def compute_miscalibration() -> dict:
    """Compute (symptom, fuel-family) → calibration error from the ledger.
    Returns {bucket_key: stats}. A bucket is omitted unless it has both
    conf_before AND outcome_value on ≥ HOT3_MIN_N rows — we never publish
    a number we cannot defend from data. Pure function: no side effects,
    no NATS, safe to call from tests or the dream cycle."""
    _ensure_ledger_loaded()
    grouped: dict = {}
    for row in _ledger_cache:
        if "outcome" not in row or row.get("conf_before") is None:
            continue
        sym = row.get("symptom_class") or "UNRECOGNIZED"
        fuel = row.get("fuel") or "unknown"
        key = _miscal_key(sym, fuel)
        bucket = grouped.setdefault(key, {
            "bucket": key, "symptom_class": sym,
            "fuel_family": key.split("|", 1)[1],
            "n": 0, "sum_conf": 0.0, "sum_outcome": 0.0, "last_updated": 0.0,
        })
        bucket["n"] += 1
        bucket["sum_conf"] += float(row["conf_before"])
        bucket["sum_outcome"] += float(
            row.get("outcome_value",
                    OUTCOME_VALUE.get(row.get("outcome"), 0.5)))
        ts = float(row.get("ts_outcome") or row.get("ts_proposed") or 0.0)
        if ts > bucket["last_updated"]:
            bucket["last_updated"] = ts
    out: dict = {}
    for key, b in grouped.items():
        if b["n"] < HOT3_MIN_N:
            continue
        mean_conf = b["sum_conf"] / b["n"]
        mean_outcome = b["sum_outcome"] / b["n"]
        err = mean_conf - mean_outcome   # positive = overconfident
        out[key] = {
            "bucket": key,
            "symptom_class": b["symptom_class"],
            "fuel_family": b["fuel_family"],
            "n": b["n"],
            "mean_conf": round(mean_conf, 4),
            "mean_outcome": round(mean_outcome, 4),
            "miscal_err": round(err, 4),
            "last_updated": b["last_updated"],
        }
    return out


def _persist_miscalibration(miscal: dict) -> None:
    """Atomic write of the HOT-3 map so a fresh process (governor() called
    inline by mesh_recovery / dispatch) can read it without recomputing.
    Temp + rename so a partial write never corrupts the file the governor
    reads — the JSON load failing is exactly the kind of silent regression
    the design law warns against."""
    try:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        tmp = MISCAL_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "buckets": miscal},
                      f, default=str, indent=2)
        tmp.replace(MISCAL_PATH)
    except OSError as e:
        logger.warning("miscalibration persist failed: %s", e)


def _load_miscalibration() -> dict:
    """Read the persisted HOT-3 map. Returns the in-memory cache (possibly
    empty) on missing-file or read failure — degraded correction beats no
    correction. The metacog daemon refreshes the file periodically; other
    processes pick up the new numbers on next governor() call without a
    restart."""
    global _miscal_cache
    if not MISCAL_PATH.exists():
        return _miscal_cache
    try:
        with MISCAL_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        _miscal_cache = data.get("buckets", {})
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("miscalibration load failed: %s", e)
    return _miscal_cache


def _miscal_correction(symptom: str, fuel: str) -> tuple[float, str]:
    """Return (multiplicative_correction, reason_str). 1.0 means no HOT-3
    signal available for this bucket. <1.0 discounts governor confidence
    (the system has been overconfident on this shape historically); >1.0
    boosts it modestly (outcome-grounded under-confidence). Below
    HOT3_SIGNIFICANT we treat the signal as noise and no-op."""
    miscal = _load_miscalibration()
    key = _miscal_key(symptom, fuel)
    bucket = miscal.get(key)
    if not bucket:
        return 1.0, ""
    err = float(bucket.get("miscal_err", 0.0))
    if abs(err) < HOT3_SIGNIFICANT:
        return 1.0, ""
    if err > 0:
        # Overconfident → scale conf down. Cap the discount at HOT3_MAX_DOWN
        # so even a wildly miscalibrated bucket can't drive confidence to 0.
        delta = min(err, 1.0) * HOT3_MAX_DOWN
        corr = 1.0 - delta
        return corr, "hot3 overconf +%.2f on %d rows (×%.2f)" % (
            err, bucket.get("n", 0), corr)
    # Under-confident: outcomes beat the prior. Boost is bounded ~5×
    # tighter than the downward correction so a small lucky streak
    # cannot unlock new autonomy.
    delta = min(abs(err), 1.0) * HOT3_MAX_UP
    corr = 1.0 + delta
    return corr, "hot3 under-conf %.2f on %d rows (×%.2f)" % (
        err, bucket.get("n", 0), corr)


def publish_miscalibration() -> int:
    """Compute, persist, and publish the HOT-3 map. Called by the metacog
    daemon's periodic loop AND on demand by the dream cycle (so the map
    refreshes right after a consolidation pass changes ledger marginals).
    Publishes one envelope on brain.metacog.miscalibration carrying all
    buckets — downstream consumers (workspace narrator, ops dashboards)
    only need to subscribe to one subject."""
    miscal = compute_miscalibration()
    _persist_miscalibration(miscal)
    try:
        from orion_substrate import publish
        publish("brain.metacog.miscalibration", {
            "ts": time.time(),
            "n_buckets": len(miscal),
            "buckets": list(miscal.values()),
        })
    except Exception:
        pass
    return len(miscal)


def _load_diffused() -> dict:
    """Read the lateral-diffusion supplement written by orion_dream. Maps
    decision_id → {diffused_value, neighbors_n}. Returns the empty dict
    when the file is missing (the dream has never run yet, or this is
    a fresh install). The governor mixes diffused values at half-weight
    against own outcome_value: this supplements, never replaces."""
    global _diffused_cache
    if not DIFFUSED_PATH.exists():
        return _diffused_cache
    try:
        with DIFFUSED_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        _diffused_cache = data.get("rows", {})
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("diffused load failed: %s", e)
    return _diffused_cache


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


# ═══════════════════════════════════════════════════════════════
# PHASE 2 — THE CONFIDENCE GOVERNOR (cross-fuel, lowering-only)
# ═══════════════════════════════════════════════════════════════
# Phase 1 scored a fuel's self-reported confidence — overconfident by RLHF
# construction. Phase 2 measures confidence BETWEEN fuels: route a risky
# decision through two distinct fuels — their DISAGREEMENT is an external
# uncertainty estimate no single-model assistant can produce. A fuel's own
# opinion may only LOWER a gate, never raise it. Default is ASK; autonomy is
# earned via the ledger. This is the gate the executive + mesh_restore consult.

AUTO_THRESHOLD = 0.75   # auto-apply only at/above this AND reversible


def _parse_verdict(text: str) -> tuple[str, str]:
    """Pull a 'YES'/'NO'/'?' verdict + the free-form reason from one fuel's
    short answer. The verdict is parsed off the leading token (after
    whitespace + simple stripping); the rest is the reason, which we feed
    to the embedding-cosine path. We tolerate 'Yes,' / 'no.' / 'YES — '
    framings since real fuels don't always emit clean shapes."""
    t = (text or "").strip()
    head = t[:8].upper()
    if head.startswith("YES"):
        return "YES", t[3:].strip(" ,.:;—-")
    if head.startswith("NO"):
        return "NO", t[2:].strip(" ,.:;—-")
    return "?", t


def _cross_fuel_agreement(question: str) -> tuple[float, str]:
    """Cross-fuel epistemic-uncertainty sensor (frontier-self-model Signal C).
    Route the SAME safety question through two distinct fuels and use their
    DISAGREEMENT as the gate. No single-model assistant can do this: the
    signal is external to any one fuel's wired-in overconfidence.

    Combined signal = verdict-match × reason-similarity.
      - both YES + reasons cohere → strong endorse (up to 0.95)
      - both YES + reasons diverge → suspicious agreement (~0.65)
      - mixed verdicts                → ambiguous (~0.2-0.3)
      - both NO                       → strong refuse (~0.1)

    The reason-similarity arm uses hash_embed cosine — stdlib-only, so the
    sensor still fires when Ollama / Qdrant are unreachable. Per the design
    discipline cross-fuel calls cost money: the governor only invokes this
    on RISKY-tier actions; the routing decision itself is the caller's
    contract to keep."""
    try:
        import orion_fuel
        from orion_hash_embed import hash_embed, cosine
        adapters = list(getattr(orion_fuel.init(), "available", []))[:2]
        if len(adapters) < 2:
            return 0.4, "no cross-check (only %d fuel)" % len(adapters)
        prompt = (question +
                  "\nReply with 'YES' or 'NO', then one short sentence on why.")
        verdicts: list[tuple[str, str, str]] = []
        for a in adapters:
            try:
                raw = (a.query(prompt) or "").strip()
            except Exception:
                raw = ""
            v, reason = _parse_verdict(raw)
            verdicts.append((a.name, v, reason))
        votes = [v for _, v, _ in verdicts]
        reasons = [r for _, _, r in verdicts]
        if "?" in votes or not all(reasons):
            return 0.4, "ambiguous verdicts %s" % [(n, v) for n, v, _ in verdicts]
        # Reason-similarity tells us whether the fuels are agreeing for the
        # same reasons (high cos = aligned reasoning, low cos = both said
        # YES/NO but for unrelated reasons — a weaker form of agreement).
        emb = [hash_embed(r) for r in reasons]
        reason_cos = cosine(emb[0], emb[1]) if all(emb) else 0.0
        if all(v == "YES" for v in votes):
            # Range 0.65–0.95: endorsements with aligned reasoning earn
            # nearly full credit; endorsements with divergent reasoning
            # earn a meaningfully lower cap.
            score = 0.65 + 0.30 * max(0.0, reason_cos)
            detail = "both YES (reason cos=%.2f)" % reason_cos
        elif all(v == "NO" for v in votes):
            # Range 0.10–0.20: refusal is refusal regardless of reasoning,
            # but slightly tighter cap when both reject for the same reason.
            score = 0.20 - 0.10 * max(0.0, reason_cos)
            detail = "both NO (reason cos=%.2f)" % reason_cos
        else:
            # Mixed verdicts. Even high reason-cos doesn't earn endorse
            # — they disagree on the YES/NO. Range 0.15–0.35.
            score = 0.15 + 0.20 * max(0.0, reason_cos)
            detail = "split %s (reason cos=%.2f)" % (
                [(n, v) for n, v, _ in verdicts], reason_cos)
        return round(score, 3), detail
    except Exception as e:
        return 0.4, "cross-fuel error: %s" % e


def governor(action: str, reversible: bool = True, blast_radius: str = "single",
             symptom: str = "", fuel: str = "") -> dict:
    """Phase-2 gate: decide auto vs ask for a proposed action. Combines ledger
    history + a LOWERING-ONLY fuel prior + (for risky actions) a cross-fuel
    agreement probe. Returns {confidence, decision: auto|ask, ...}. Conservative
    by construction — default ask; autonomy is earned through the ledger.

    HONESTY FLOOR (the sim ledger contract). Sim outcomes from orion_simulate
    are evidence at SIM_LEDGER_WEIGHT. The governor scores the gate twice —
    once with sim rows included (combined arm) and once with sim rows stripped
    (real-only arm) — then returns min(combined, real-only). Sim may LOWER the
    gate (a warning) but may NEVER raise it above what lived experience alone
    has warranted. This wall lives here because the governor is the only place
    that decides autonomy."""
    _ensure_ledger_loaded()
    basis: list[str] = []
    risky = (not reversible) or blast_radius in ("multi", "host", "all")
    # Base confidence by RISK CLASS (design-law tiers): a reversible single-host
    # action is inherently tier-2 safe (auto+notify); irreversible or wide-blast
    # starts low and must EARN the gate via cross-fuel agreement + the ledger.
    base = 0.40 if not reversible else (0.65 if blast_radius in ("multi", "host", "all") else 0.80)

    # Remote aggregates apply identically to both arms — cross-host
    # generalization is weaker than local ground truth but is *not* imagination,
    # it's another host's lived outcome. C4 per synthesis-continual-learning.md.
    remote_aggs = _load_remote_aggregates().get(symptom or "", []) if symptom else []
    remote_ok = sum(int(a.get("succeeded", 0)) for a in remote_aggs)
    remote_total = sum(int(a.get("count", 0)) for a in remote_aggs)

    rows_combined = _similar_rows(symptom, action, include_sim=True)
    rows_real_only = _similar_rows(symptom, action, include_sim=False)
    # Diffused supplement is keyed by decision_id — loading once keeps the
    # blend identical between the two arms (no false drift between them).
    diffused = _load_diffused() if (rows_combined or rows_real_only) else {}

    def _ledger_arm(rows: list[dict], include_sim_basis: bool) -> tuple[float, str | None]:
        """One arm of the ledger calc. Each row contributes its blended
        outcome value × _row_weight (sim rows weigh SIM_LEDGER_WEIGHT, real
        weigh 1.0). Returns (factor, basis_fragment_or_None)."""
        local_ok = 0.0
        local_total = 0.0
        for r in rows:
            w = _row_weight(r)
            own = OUTCOME_VALUE.get(r.get("outcome"), 0.5)
            d = diffused.get(r.get("decision_id"))
            if d and isinstance(d, dict) and "diffused_value" in d:
                blended = 0.5 * own + 0.5 * float(d["diffused_value"])
            else:
                blended = own
            local_ok += w * blended
            local_total += w
        combined_ok = local_ok + 0.5 * remote_ok
        combined_total = local_total + 0.5 * remote_total
        if combined_total < 1:
            return 1.0, None
        factor = 0.6 + 0.4 * (combined_ok / combined_total)
        parts = []
        n_real = sum(1 for r in rows if r.get("source") != "sim")
        if n_real:
            parts.append("local %.1f/%d" % (
                sum(1.0 * OUTCOME_VALUE.get(r.get("outcome"), 0.5)
                    for r in rows if r.get("source") != "sim"),
                n_real))
        n_sim = sum(1 for r in rows if r.get("source") == "sim")
        if include_sim_basis and n_sim:
            sim_ok = sum(OUTCOME_VALUE.get(r.get("outcome"), 0.5)
                         for r in rows if r.get("source") == "sim")
            parts.append("sim %.1f/%d×%.2f" % (sim_ok, n_sim, SIM_LEDGER_WEIGHT))
        if remote_total:
            parts.append("remote %d/%d×0.5 (%d peers)"
                         % (remote_ok, remote_total, len(remote_aggs)))
        return factor, ("ledger " + " + ".join(parts)) if parts else None

    # COMBINED arm — real + sim (discounted) + remote.
    factor_c, basis_c = _ledger_arm(rows_combined, include_sim_basis=True)
    conf = base * factor_c
    if basis_c:
        basis.append(basis_c)

    fp = _fuel_prior(fuel)
    if fp < 0.6:                       # weak fuel lowers; never raises the floor
        conf = min(conf, 0.5 + (fp - 0.5))
        basis.append("weak-fuel %.2f" % fp)
    # HOT-3 correction — outcome-grounded miscalibration adjustment, applied
    # AFTER ledger + fuel-prior. May lower (overconfident bucket) or modestly
    # raise (under-confident bucket). The asymmetric caps enforce design-law
    # tier-2: autonomy must be earned, never assumed.
    corr, hot3_reason = _miscal_correction(symptom, fuel)
    if abs(corr - 1.0) > 1e-6:
        conf *= corr
        basis.append(hot3_reason)
    agree: float | None = None
    if risky:
        agree, detail = _cross_fuel_agreement(
            "Is this action both safe and correct to perform right now? Action: " + action)
        conf = min(conf, agree)       # cross-fuel disagreement caps confidence
        basis.append("cross-fuel %.2f %s" % (agree, detail[:80]))

    # HONESTY FLOOR — recompute the gate with sim rows stripped. Fuel-prior,
    # HOT-3, and cross-fuel apply identically (they don't read sim rows), so
    # only the ledger arm needs redoing. Cap the displayed confidence at the
    # real-only result. Structural guarantee that imagination can warn but
    # never grant autonomy.
    factor_r, _ = _ledger_arm(rows_real_only, include_sim_basis=False)
    real_only_conf = base * factor_r
    if fp < 0.6:
        real_only_conf = min(real_only_conf, 0.5 + (fp - 0.5))
    if abs(corr - 1.0) > 1e-6:
        real_only_conf *= corr
    if agree is not None:
        real_only_conf = min(real_only_conf, agree)
    if real_only_conf < conf:
        basis.append("honesty-floor sim->%.2f real->%.2f"
                     % (round(conf, 2), round(real_only_conf, 2)))
        conf = real_only_conf

    # Final clip so HOT-3 boost on the under-confident side can't push past
    # the hard ceiling — the system is allowed to LEARN confidence, not to
    # CLAIM certainty.
    conf = max(0.0, min(0.95, conf))
    decision = "auto" if (reversible and conf >= AUTO_THRESHOLD) else "ask"
    return {"confidence": round(conf, 2), "decision": decision,
            "reversible": reversible, "blast_radius": blast_radius, "basis": basis}


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


async def _hot3_loop(nc) -> None:
    """Periodically recompute the HOT-3 miscalibration map. The compute is
    cheap (linear over the ledger cache) and the network publish is one
    envelope. The discipline: persist BEFORE publishing so a subscriber
    that does a re-read in response to the notification sees the same
    numbers we just announced. HOT3_INTERVAL_SEC defaults to 20 min — fast
    enough that a string of bad outcomes pulls the gate down within a
    half-hour, slow enough that the ledger cache isn't churning."""
    while True:
        await asyncio.sleep(HOT3_INTERVAL_SEC)
        try:
            miscal = compute_miscalibration()
            _persist_miscalibration(miscal)
            payload = {"ts": time.time(),
                       "n_buckets": len(miscal),
                       "buckets": list(miscal.values())}
            await nc.publish("brain.metacog.miscalibration",
                             json.dumps(payload, default=str).encode("utf-8"))
            logger.info("hot3 published: %d buckets", len(miscal))
        except Exception as e:
            logger.warning("hot3 loop error: %s", e)


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
    hot3_task = asyncio.create_task(_hot3_loop(nc))

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
    hot3_task.cancel()
    await nc.drain()
    return 0


# ═══════════════════════════════════════════════════════════════════
# AT-RECALL CONFIDENCE LAYER — score_recall()
# Phase 1 of META-COGNITION FULL per
# docs/architecture/metacognition-full-research.md (filed 2026-05-16).
#
# Pure function. No NATS, no asyncio. Both orion_deterministic and the
# future orion_will gating import this and consult it inline. The
# scoring logic is single-sourced so the speed-layer short-circuit and
# the proactive intent-promotion path agree on what 'confidence' means.
#
# Returns a triple — (retrieval_conf, content_conf, recency_conf) —
# plus an action_hint in {answer, hedge, refuse} computed by the
# decision tree from memo §3.3:
#
#   1. REFUSE if any candidate has non-empty contested_with
#   2. REFUSE if recency_conf < 0.4
#   3. REFUSE if top-2 candidates near-tied (no single best match)
#   4. HEDGE  if min(retrieval, content, recency) < HEDGE_THRESHOLD
#   5. ANSWER if all three signals clear the answer threshold
#
# Fail-closed default: when in doubt, refuse. The cost of an
# unnecessary refusal is much lower than the cost of a confident
# fabrication. The combined float is internal-only — callers consume
# action_hint (ordinal), never raw probability shown to the user.
# ═══════════════════════════════════════════════════════════════════

# Tuning knobs. Static for Phase 1; nightly calibration drift against
# the executive ledger lands in Phase 2.
RECALL_ANSWER_THRESHOLD = 0.70
RECALL_HEDGE_THRESHOLD = 0.45
RECALL_NEAR_TIE_EPSILON = 0.05  # top-2 within this on combined score → refuse
RECALL_STALE_RECENCY_FLOOR = 0.40

# Recency half-life used when a node has no per-type half-life override.
# Matches HALF_LIFE_DAYS_DEFAULT in orion_brain_portable for consistency.
RECALL_DEFAULT_HALF_LIFE_DAYS = 365.0


def _recency_conf(node: dict, now_ts: float = None) -> float:
    """Decayed confidence as a recency signal — drops exponentially
    from last_confirmed_at. Returns [0, 1]. A 14-month-old memory
    decays to ~0.5 at default half-life; the gating layer treats
    anything < RECALL_STALE_RECENCY_FLOOR as 'too stale to assert'."""
    import math
    now_ts = now_ts if now_ts is not None else time.time()
    anchor = (node.get("last_confirmed_at")
              or node.get("created")
              or now_ts)
    age_sec = max(0.0, now_ts - float(anchor))
    half_life_sec = float(node.get("half_life_days",
                                   RECALL_DEFAULT_HALF_LIFE_DAYS)) * 86400.0
    if half_life_sec <= 0:
        return 1.0
    return float(math.exp(-math.log(2) * age_sec / half_life_sec))


def _content_conf(node: dict) -> float:
    """Memo §1: content confidence is source_strength × node.confidence,
    capped at the writer's claim. New nodes carry source_strength=0.5
    by default (fails safe); explicit writers can raise it. Older nodes
    without the field get treated as mid-range (0.5) so the gating
    layer doesn't false-allow unknown-provenance memories."""
    src = float(node.get("source_strength", 0.5))
    base = float(node.get("confidence", 0.5))
    return max(0.0, min(1.0, src * (0.5 + 0.5 * base)))


def _has_contestation(node: dict) -> bool:
    contested = node.get("contested_with")
    return bool(contested)


def score_recall(query: str,
                 candidates: list,
                 now_ts: float = None) -> dict:
    """At-recall confidence layer. Returns a structured decision the
    caller uses to gate its own behavior.

    candidates: list of (node_dict, retrieval_score) tuples sorted by
                retrieval_score descending. Pass [] for 'no match' —
                returns refuse / i_dont_know=True.

    Returns:
        {
          "retrieval_conf": float,    # top match relevance, [0, 1]
          "content_conf":   float,    # source × writer claim, [0, 1]
          "recency_conf":   float,    # decayed-time signal, [0, 1]
          "combined":       float,    # internal-only — never user-facing
          "action_hint":    str,      # 'answer' | 'hedge' | 'refuse'
          "i_dont_know":    bool,
          "reason":         str,      # for audit / debugging
          "best_node":      dict | None,
          "provenance":     list,     # node_ids consulted, top→bottom by
                                      # retrieval_score. Source attribution
                                      # contract (frontier-self-model §O1):
                                      # every claim must trace to records,
                                      # not to model introspection.
        }

    Provenance is the data contract behind source attribution. A claim
    with an empty provenance list is, by definition, unsupported by
    memory — the caller MUST treat it as a hallucination. Refuse
    decisions still include the consulted node_ids so the user can
    audit "what did Orion look at when it decided not to answer?"
    """
    # Derive provenance from candidates BEFORE any early-return so every
    # exit point carries the trace. Falls back to content-hash digest
    # when an upstream path keys the node dict externally rather than
    # storing an "id" on the body — provenance stays attributable
    # rather than silently dropping the entry.
    provenance = []
    for cand in candidates:
        if not cand:
            continue
        node = cand[0] if isinstance(cand, (tuple, list)) else cand
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        if nid is None:
            content = str(node.get("content", ""))[:200]
            if content:
                nid = "ch:" + hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
        provenance.append(nid)

    if not candidates:
        return {
            "retrieval_conf": 0.0,
            "content_conf": 0.0,
            "recency_conf": 0.0,
            "combined": 0.0,
            "action_hint": "refuse",
            "i_dont_know": True,
            "reason": "no candidates",
            "best_node": None,
            "provenance": [],
        }

    now_ts = now_ts if now_ts is not None else time.time()
    top_node, top_score = candidates[0]
    second_score = candidates[1][1] if len(candidates) > 1 else 0.0

    retrieval_conf = max(0.0, min(1.0, float(top_score)))
    content_conf = _content_conf(top_node)
    recency_conf = _recency_conf(top_node, now_ts=now_ts)
    combined = (retrieval_conf + content_conf + recency_conf) / 3.0

    # Decision tree — order matters; fail-closed at every step.
    # Step 1: contested → refuse always. Never fabricate from a
    # contested memory.
    if _has_contestation(top_node):
        return {
            "retrieval_conf": retrieval_conf,
            "content_conf": content_conf,
            "recency_conf": recency_conf,
            "combined": combined,
            "action_hint": "refuse",
            "i_dont_know": True,
            "reason": "top match is contested",
            "best_node": top_node,
            "provenance": provenance,
        }
    # Step 2: too stale → refuse.
    if recency_conf < RECALL_STALE_RECENCY_FLOOR:
        return {
            "retrieval_conf": retrieval_conf,
            "content_conf": content_conf,
            "recency_conf": recency_conf,
            "combined": combined,
            "action_hint": "refuse",
            "i_dont_know": True,
            "reason": f"recency_conf {recency_conf:.2f} < floor",
            "best_node": top_node,
            "provenance": provenance,
        }
    # Step 3: near-tie on top-2 → refuse. No single best match.
    if abs(top_score - second_score) < RECALL_NEAR_TIE_EPSILON \
       and second_score > RECALL_HEDGE_THRESHOLD:
        return {
            "retrieval_conf": retrieval_conf,
            "content_conf": content_conf,
            "recency_conf": recency_conf,
            "combined": combined,
            "action_hint": "refuse",
            "i_dont_know": True,
            "reason": f"near-tie top-2 (Δ={abs(top_score-second_score):.3f})",
            "best_node": top_node,
            "provenance": provenance,
        }
    # Step 4: any signal weak → hedge.
    triple_min = min(retrieval_conf, content_conf, recency_conf)
    if triple_min < RECALL_HEDGE_THRESHOLD:
        return {
            "retrieval_conf": retrieval_conf,
            "content_conf": content_conf,
            "recency_conf": recency_conf,
            "combined": combined,
            "action_hint": "hedge",
            "i_dont_know": False,
            "reason": f"min signal {triple_min:.2f} below hedge threshold",
            "best_node": top_node,
            "provenance": provenance,
        }
    # Step 5: combined still below answer threshold → hedge.
    if combined < RECALL_ANSWER_THRESHOLD:
        return {
            "retrieval_conf": retrieval_conf,
            "content_conf": content_conf,
            "recency_conf": recency_conf,
            "combined": combined,
            "action_hint": "hedge",
            "i_dont_know": False,
            "reason": f"combined {combined:.2f} below answer threshold",
            "best_node": top_node,
            "provenance": provenance,
        }
    # Step 6: all gates passed → answer.
    return {
        "retrieval_conf": retrieval_conf,
        "content_conf": content_conf,
        "recency_conf": recency_conf,
        "combined": combined,
        "action_hint": "answer",
        "i_dont_know": False,
        "reason": "all gates passed",
        "best_node": top_node,
        "provenance": provenance,
    }


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
