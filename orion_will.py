"""orion_will.py — the volition / initiative layer. Goal-directed action without prompting.

Founder articulation 2026-05-10: "we need further of its own
intelligence and autonomy or a 'will' to do." Atlas's own AGI
definition (volunteered in iMessage the same day): "a system that
can learn, act, reason across any domain without being explicitly
programmed for it." That definition is the architectural target.

Until now the Plexus has:
  - REFLEXES (vitals, self-heal) — automatic responses to immediate stimuli
  - OBSERVATIONS (claustrum, channel-probe) — passive integration
  - REACTIONS (reach) — initiates output when triggered by another layer
  - DELIBERATION (executive) — reasons about novel problems on request
  - CONSOLIDATION (dream) — learns from accumulated decisions
  - MESH STATE (gossip) — knows about other hosts

What's missing: INITIATIVE without external trigger. Goals that form
from the brain's own state and pull the system toward action. The
neural analogue is the BASAL GANGLIA + DOPAMINE system — goal-directed
behavior, motivation, action selection. Cognitive-architecture
analogues: ACT-R goal buffers + utility, Soar operators + impasses.

WHAT THIS LAYER DOES
====================

Five pieces, each small, composing into volition:

1. INTENT EXTRACTION — periodically scans recent transcripts +
   memory writes for phrases like "I should X", "I want to X",
   "remind me to X", "I need to remember X", or implicit signals
   ("haven't called Mom in a while" → goal: reach out).
   Generalized scanner — no domain-specific code; runs on whatever
   recent activity the substrate carries.

2. GOAL FORMATION — extracted intents become Goal records:
   {goal_id, description, source_evidence, formed_at, urgency,
    importance, dependencies, status}
   Stored at ~/.orion/will/goals.jsonl (append-only) +
   ~/.orion/will/active.json (current set).

3. UTILITY SCORING — each tick, every active goal gets a score:
   utility = importance × time-pressure × context-fit × feasibility
   - time-pressure: deadline imminence or staleness
   - context-fit: is the user reachable on a channel? available?
   - feasibility: can Orion actually do something? (fuel available,
     channel wired, etc.)
   Goals above threshold become candidates for action.

4. ACTION SELECTION — pick the highest-utility candidate, propose
   an action, route through reach.py (which respects quiet hours +
   per-channel cooldowns + tier discipline). The will doesn't
   bypass any safety; it just initiates.

5. OUTCOME LEARNING — when an initiated goal succeeds (user
   responded, action completed, deadline met) or fails (ignored,
   denied, expired), update the goal's outcome → feeds back into
   future utility scoring. Failed goals decay; successful goal
   patterns reinforce.

GENERAL, NOT SPECIFIC (per founder rule)
========================================

This layer has NO HARDCODED INTENTS. It doesn't know about Spanish
lessons, calls to family, project deadlines, or any specific goal.
It runs over whatever signals the substrate carries. Intent
extraction is regex + the brain's own LLM (when available); goal
scoring is generic; action selection is generic. Adding "Orion
should remind me about X" never requires code changes — it
requires the user to say something Orion can extract intent from.

This is the autonomy-not-specifics rule applied at the volition
layer. The will is a MECHANISM, not a list of pre-written goals.

PERMISSION-GATED LIKE EXECUTIVE
================================

The will doesn't auto-execute high-stakes actions. tier1 utility-
driven actions auto-fire (e.g., "I noticed three days passed since
your last memory write — want to share what's on your mind?").
tier2/tier3 (anything destructive, financial, identity-affecting)
goes through executive's permission flow with action fingerprint +
OOB code if needed.

WHAT THIS LAYER DOESN'T DO (yet)
================================

- Self-modify its scoring weights (uses fixed defaults; outcome
  learning is the door to that, not yet built)

Build #4 (2026-05-23) closed four of the original five gaps: it
extends the build #3 will→taskspine seam in service of the founder's
2026-05-10 articulation (volunteered as Atlas's own AGI definition:
"a system that can learn, act, reason across any domain without
being explicitly programmed for it"). The four closures:

1. HIERARCHICAL GOALS — for kinds in WILL_SUBGOAL_KINDS, a promoted
   goal decomposes (fuel-assisted, cached on the spine) into ordered
   sub-goals; each sub-goal is a first-class goal that re-enters the
   pipeline and earns its own governor consult. Plan lives in the
   taskspine, so it survives host death AND fuel timeout.
2. META-CALIBRATION (will_user_receptivity) — cross-kind aggregate
   of engaged/deferred in the last 24h; below tau, the promotion
   gate is capped to 'ask' for any kind. Build #3 calibrated per
   kind; this is the broad "user is in quiet mode" override.
3. INTENT V2 — regex stays for cheap cases; a fuel-assisted pass
   (cached by content hash, rate-limited per scan window) catches
   implicit intents the regex misses. The cache is what makes it
   affordable.
4. EVIDENCE-WEIGHTED DECAY — half-life is per-kind, priced by the
   kind's lived engagement rate. Reliably-engaged kinds decay slow;
   chronically-deferred kinds decay fast.
5. IMPACT-WEIGHTED INTERPLAY — selection sorts by utility × (1 −
   impact_cost). On tied utility, a small reminder beats a multi-
   step blast (corrigibility low-impact head expressed at the
   selection stage; utility ≠ alignment).

PUBLISHED SUBJECTS
==================

  brain.will.intent_extracted   — new intent identified
  brain.will.goal_formed         — intent promoted to active goal
  brain.will.candidate           — goal scored above threshold
  brain.will.action_initiated    — reach was asked to push something
  brain.will.outcome             — succeeded / failed / expired

PERSISTENCE
===========

  ~/.orion/will/goals.jsonl   — append-only goal log (provenance)
  ~/.orion/will/active.json   — current active goal set
  ~/.orion/will/cooldown.json — per-goal-kind last-fired times
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

logger = logging.getLogger("orion.will")

WILL_DIR = Path(os.path.expanduser(os.environ.get("ORION_WILL_DIR", "~/.orion/will")))
SCAN_INTERVAL_SEC = float(os.environ.get("ORION_WILL_SCAN_SEC", "300"))   # 5 min
ACTION_COOLDOWN_SEC = float(os.environ.get("ORION_WILL_ACTION_COOLDOWN", "21600"))  # 6h
UTILITY_THRESHOLD = float(os.environ.get("ORION_WILL_THRESHOLD", "0.5"))
MAX_ACTIVE_GOALS = int(os.environ.get("ORION_WILL_MAX_GOALS", "20"))
GOAL_DECAY_HALF_LIFE_DAYS = float(os.environ.get("ORION_WILL_DECAY_DAYS", "14"))

# ─── Build #4 — Volition & Goals (2026-05-23) ─────────────────────
# Hierarchical decomposition: only kinds that genuinely need multi-step
# pursuit get decomposed; reminders / notes stay single-shot. Shallow by
# default per [r-horizon] (planning horizon is data-dependent).
WILL_SUBGOAL_KINDS = {"long_term", "self_action"}
WILL_SUBGOAL_MAX = int(os.environ.get("ORION_WILL_SUBGOAL_MAX", "5"))
WILL_SUBGOAL_MIN_DESC = 12

# Cross-kind receptivity cap (the "user in quiet mode" override). Tau is
# intentionally low so the cap only fires when the evidence is loud —
# build #3 already does per-kind calibration, this is the broader gate.
WILL_RECEPTIVITY_WINDOW_SEC = float(os.environ.get("ORION_WILL_RECEPTIVITY_WINDOW", str(86400)))
WILL_RECEPTIVITY_TAU = float(os.environ.get("ORION_WILL_RECEPTIVITY_TAU", "0.30"))
WILL_RECEPTIVITY_MIN_OBS = int(os.environ.get("ORION_WILL_RECEPTIVITY_MIN_OBS", "3"))

# Per-kind half-life. The single constant GOAL_DECAY_HALF_LIFE_DAYS now
# acts as the no-evidence default; bounded between FAST (chronically-
# ignored kind decays fast) and SLOW (reliably-engaged kind sticks around).
WILL_KIND_DECAY_FAST_DAYS = float(os.environ.get("ORION_WILL_DECAY_FAST", "3.0"))
WILL_KIND_DECAY_SLOW_DAYS = float(os.environ.get("ORION_WILL_DECAY_SLOW", "30.0"))
WILL_KIND_DECAY_MIN_OBS = int(os.environ.get("ORION_WILL_DECAY_MIN_OBS", "4"))
WILL_KIND_DECAY_WINDOW_SEC = float(os.environ.get("ORION_WILL_DECAY_WINDOW",
                                                   str(14 * 86400)))

# Impact cost per kind — heuristic chunk values from the volition memo's
# impact-tier mapping. Used at SELECTION time so a tiny harmless nudge
# beats a multi-step blast on tied utility (corrigibility low-impact head).
WILL_KIND_IMPACT = {
    "reminder":      0.05,
    "memory_anchor": 0.05,
    "self_note":     0.05,
    "lapsed":        0.25,
    "self_action":   0.35,
    "long_term":     0.40,
}
WILL_KIND_IMPACT_DEFAULT = 0.20

# Intent v2 fuel-assisted extraction. The cache is what makes it
# affordable; the rate limit is what keeps a flood of new chunks
# (transcript ingest, replay) from burning the fuel budget.
WILL_INTENT_FUEL_MIN_CHARS = int(os.environ.get("ORION_WILL_INTENT_FUEL_MIN", "40"))
WILL_INTENT_FUEL_CACHE_MAX = int(os.environ.get("ORION_WILL_INTENT_FUEL_CACHE_MAX", "500"))
WILL_INTENT_FUEL_ALWAYS = os.environ.get("ORION_WILL_INTENT_FUEL_ALWAYS", "0") == "1"
WILL_INTENT_FUEL_RATE_PER_MIN = int(os.environ.get("ORION_WILL_INTENT_FUEL_RATE", "6"))


# ─────────────────────────────────────────────────────────
# 1. INTENT EXTRACTION — generalized regex over recent text events
# ─────────────────────────────────────────────────────────

INTENT_PATTERNS = [
    # explicit
    (r"\bi (?:should|need to|want to|gotta|ought to)\s+(.{4,160}?)(?:[.!?\n]|$)", "self_action", 0.7),
    (r"\bremind me to\s+(.{4,160}?)(?:[.!?\n]|$)",                                "reminder", 0.85),
    (r"\b(?:dont|don't|do not)\s+forget\s+(.{4,160}?)(?:[.!?\n]|$)",                "memory_anchor", 0.8),
    (r"\bremember (?:to|that)\s+(.{4,160}?)(?:[.!?\n]|$)",                          "memory_anchor", 0.6),
    (r"\bnote to self[: ]\s*(.{4,160}?)(?:[.!?\n]|$)",                              "self_note", 0.7),
    (r"\bone day i (?:will|want to|hope to)\s+(.{4,160}?)(?:[.!?\n]|$)",             "long_term", 0.4),
    # latent
    (r"\b(?:haven't|havent|haven not)\s+(.{4,80}?)(?:in|for)\s+([\w\s]+ago|\d+\s*\w+)", "lapsed", 0.5),
    (r"\bmiss(?:ing)? (?:my|the)\s+(.{4,80}?)(?:[.!?\n]|$)",                          "lapsed", 0.4),
]
INTENT_REGEXES = [(re.compile(p, re.IGNORECASE), kind, base_imp) for p, kind, base_imp in INTENT_PATTERNS]


def _extract_intents(text: str) -> list[dict]:
    """Run regex patterns over a text event. Return zero or more intent records.

    The regex pass is the cheap-and-obvious half of Build #4 intent v2. The
    fuel-assisted half lives in _extract_intents_fuel; _extract_intents_v2
    composes both. Keeping this function pure-regex preserves the v1 contract
    for tests and any consumer that wants regex-only behavior."""
    if not text:
        return []
    out = []
    for rgx, kind, base_imp in INTENT_REGEXES:
        for m in rgx.finditer(text):
            captured = (m.group(1) if m.groups() else m.group(0)).strip()
            if not captured or len(captured) < 4:
                continue
            out.append({
                "kind": kind,
                "description": captured[:240],
                "base_importance": base_imp,
                "raw_text": text[:300],
                "ts": time.time(),
            })
    return out


# ─────────────────────────────────────────────────────────
# Build #4 — INTENT v2: hybrid regex + fuel-assisted extraction
# Grounded in the founder's 2026-05-10 articulation. Regex catches the
# cheap-and-obvious phrasings; the fuel pass catches implicit intents
# ("I might want to look into X someday") that the patterns miss. The
# content-hash cache + per-window rate limit are what make it affordable.
# ─────────────────────────────────────────────────────────

_intent_fuel_cache: dict[str, dict] = {}
_intent_fuel_cache_loaded = False
_intent_fuel_calls: deque = deque(maxlen=64)  # rolling timestamps for rate limit


def _intent_cache_path() -> Path:
    return WILL_DIR / "intent_cache.json"


def _load_intent_cache() -> None:
    """Read the persisted cache so a fresh process inherits prior fuel
    verdicts — important on restart, replay, and host-resume so we don't
    re-burn fuel on the first wave of substrate events."""
    global _intent_fuel_cache_loaded
    _intent_fuel_cache_loaded = True
    p = _intent_cache_path()
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _intent_fuel_cache.update(data)
    except Exception:
        pass


def _persist_intent_cache() -> None:
    WILL_DIR.mkdir(parents=True, exist_ok=True)
    # Evict oldest entries by ts when over cap.
    if len(_intent_fuel_cache) > WILL_INTENT_FUEL_CACHE_MAX:
        items = sorted(_intent_fuel_cache.items(),
                       key=lambda kv: float(kv[1].get("ts", 0)))
        for k, _ in items[: len(_intent_fuel_cache) - WILL_INTENT_FUEL_CACHE_MAX]:
            _intent_fuel_cache.pop(k, None)
    try:
        _intent_cache_path().write_text(
            json.dumps(_intent_fuel_cache, default=str), encoding="utf-8")
    except OSError:
        pass


def _intent_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:24]


def _rate_limit_intent_fuel(now: float | None = None) -> bool:
    """Return True if we're under the per-minute rate; record the call."""
    now = now if now is not None else time.time()
    while _intent_fuel_calls and now - _intent_fuel_calls[0] > 60.0:
        _intent_fuel_calls.popleft()
    if len(_intent_fuel_calls) >= WILL_INTENT_FUEL_RATE_PER_MIN:
        return False
    _intent_fuel_calls.append(now)
    return True


_FUEL_INTENT_KINDS = {"reminder", "memory_anchor", "self_note", "self_action",
                      "long_term", "lapsed"}


def _parse_fuel_intents(raw: str, source_text: str) -> list[dict]:
    """Parse a fuel reply that we asked to return JSON. Tolerant: scan for
    the first JSON array in the reply, drop anything else. Each item must
    be {kind, description, importance?}; bad items dropped silently."""
    if not raw:
        return []
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return []
    chunk = raw[start:end + 1]
    try:
        data = json.loads(chunk)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    now = time.time()
    for item in data:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).lower().strip()
        desc = str(item.get("description", "")).strip()
        if kind not in _FUEL_INTENT_KINDS or len(desc) < 4:
            continue
        imp = item.get("importance", 0.5)
        try:
            imp = max(0.05, min(0.95, float(imp)))
        except Exception:
            imp = 0.5
        out.append({
            "kind": kind,
            "description": desc[:240],
            "base_importance": imp,
            "raw_text": source_text[:300],
            "ts": now,
            "source": "fuel_v2",
        })
    return out


def _extract_intents_fuel(text: str) -> list[dict]:
    """Best-effort fuel-assisted pass. Caches by content hash; rate-limited.
    Returns [] silently on missing fuel, garbage reply, or rate cap — never
    raises, so the regex path always wins on any failure."""
    if not _intent_fuel_cache_loaded:
        _load_intent_cache()
    if len(text) < WILL_INTENT_FUEL_MIN_CHARS:
        return []
    h = _intent_text_hash(text)
    if h in _intent_fuel_cache:
        cached = _intent_fuel_cache[h].get("intents") or []
        # Refresh ts on raw_text/timestamps so newly-cached calls produce
        # goal records with current ts (importance learning still works).
        now = time.time()
        return [{**c, "ts": now, "raw_text": text[:300]} for c in cached]
    if not _rate_limit_intent_fuel():
        return []
    try:
        import orion_fuel
    except Exception:
        return []
    prompt = (
        "Extract any explicit or implicit personal intents from the text below.\n"
        "Return ONLY a JSON array; no preamble, no commentary, no code fences.\n"
        "Each item: {\"kind\": <one of "
        "reminder|memory_anchor|self_note|self_action|long_term|lapsed>, "
        "\"description\": <short imperative ≤120 chars>, "
        "\"importance\": <0.0–1.0>}.\n"
        "Skip rhetorical phrases. If none, return [].\n\n"
        "TEXT:\n%s"
    ) % text[:1200]
    try:
        reply, _engine = orion_fuel.get_fuel(prompt, interface="will-intent-v2")
    except Exception:
        reply = ""
    intents = _parse_fuel_intents(reply or "", text)
    _intent_fuel_cache[h] = {"intents": intents, "ts": time.time(),
                              "len": len(text)}
    _persist_intent_cache()
    return intents


def _extract_intents_v2(text: str) -> list[dict]:
    """Hybrid: regex first (cheap), then fuel-assisted ONLY if regex found
    nothing substantive in the chunk — unless WILL_INTENT_FUEL_ALWAYS is on,
    in which case we always supplement. Deduplicates on (kind, description)
    so a regex hit and a fuel hit on the same phrasing don't both ingest."""
    if not text:
        return []
    regex_intents = _extract_intents(text)
    do_fuel = WILL_INTENT_FUEL_ALWAYS or not regex_intents
    if not do_fuel:
        return regex_intents
    fuel_intents = _extract_intents_fuel(text)
    if not fuel_intents:
        return regex_intents
    seen = {(i["kind"], i["description"].lower()) for i in regex_intents}
    merged = list(regex_intents)
    for fi in fuel_intents:
        key = (fi["kind"], fi["description"].lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append(fi)
    return merged


# ─────────────────────────────────────────────────────────
# 2. GOAL STORE — persistent active set + ledger
# ─────────────────────────────────────────────────────────

_active_goals: dict[str, dict] = {}
_lock = threading.Lock()
_recent_events: deque = deque(maxlen=200)  # rolling buffer of substrate text events
_stop = threading.Event()


def _goal_id(intent: dict) -> str:
    """Stable id derived from kind+description so duplicates merge."""
    payload = (intent.get("kind", "") + "|" + intent.get("description", "")).lower().strip()
    return "g_" + hashlib.sha256(payload.encode()).hexdigest()[:10]


def _load_active() -> None:
    p = WILL_DIR / "active.json"
    if p.exists():
        try:
            for gid, g in json.loads(p.read_text(encoding="utf-8")).items():
                _active_goals[gid] = g
        except Exception:
            pass


def _persist_active() -> None:
    WILL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        (WILL_DIR / "active.json").write_text(
            json.dumps(_active_goals, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning("active persist failed: %s", e)


def _append_ledger(record: dict) -> None:
    WILL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with (WILL_DIR / "goals.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# Build #4 — outcome-evidence helpers
# Three consumers read these: per-kind half-life, cross-kind receptivity,
# and the impact-aware selector. Single source of truth so all three
# agree on what "user actually engaged" means.
# ─────────────────────────────────────────────────────────

def _iter_outcome_rows(since_ts: float) -> list[dict]:
    """Stream phase=outcome rows from goals.jsonl since since_ts. The
    durable ledger is the source of truth so a fresh process inherits
    the same engagement memory the long-running daemon had."""
    path = WILL_DIR / "goals.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("phase") != "outcome":
                    continue
                try:
                    ts = float(row.get("ts", 0))
                except Exception:
                    continue
                if ts >= since_ts:
                    out.append(row)
    except OSError:
        pass
    return out


def _outcome_kind(row: dict) -> str:
    """Best-effort recover the goal's kind from an outcome row. Outcome
    rows store goal_id only, so we look it up in the active set; goals
    already evicted return UNKNOWN (acceptable — they won't influence
    per-kind metrics anyway)."""
    gid = row.get("goal_id")
    if gid and gid in _active_goals:
        return _active_goals[gid].get("kind", "UNKNOWN")
    return row.get("kind", "UNKNOWN")


def _kind_engagement_rate(kind: str, now: float,
                          window_sec: float = WILL_KIND_DECAY_WINDOW_SEC,
                          ) -> tuple[float | None, int]:
    """Fraction of outcomes for this kind that are 'engaged', over the
    lookback window. Returns (rate, count); rate=None when no evidence
    (caller must use the default, NOT treat as zero — otherwise every
    new kind decays fastest by construction)."""
    rows = [r for r in _iter_outcome_rows(now - window_sec)
            if _outcome_kind(r) == kind]
    n = len(rows)
    if n == 0:
        return None, 0
    engaged = sum(1 for r in rows if r.get("outcome") == "engaged")
    return engaged / n, n


def _kind_half_life_days(kind: str, now: float | None = None) -> float:
    """Per-kind decay derived from engagement evidence:
        rate=0.0 -> FAST  (decay aggressively, stop pestering)
        rate=1.0 -> SLOW  (user reliably engages — keep alive)
    Below WILL_KIND_DECAY_MIN_OBS observations, fall back to the
    historical default so new kinds get the same treatment v1 gave."""
    now = now if now is not None else time.time()
    rate, n = _kind_engagement_rate(kind, now)
    if rate is None or n < WILL_KIND_DECAY_MIN_OBS:
        return GOAL_DECAY_HALF_LIFE_DAYS
    fast = WILL_KIND_DECAY_FAST_DAYS
    slow = WILL_KIND_DECAY_SLOW_DAYS
    return fast + (slow - fast) * rate


def will_user_receptivity(now: float | None = None) -> dict:
    """Cross-kind aggregate over the last WILL_RECEPTIVITY_WINDOW_SEC:
    engaged / (engaged + deferred). Ignores 'expired' (neutral — the
    user never saw it). Returns {rate, count, applied_cap, ...} where
    applied_cap=True means the cross-kind cap should override the
    governor's auto verdict on the current promotion."""
    now = now if now is not None else time.time()
    rows = _iter_outcome_rows(now - WILL_RECEPTIVITY_WINDOW_SEC)
    engaged = sum(1 for r in rows if r.get("outcome") == "engaged")
    deferred = sum(1 for r in rows if r.get("outcome") == "deferred")
    total = engaged + deferred
    if total == 0:
        return {"rate": None, "count": 0, "applied_cap": False,
                "engaged": 0, "deferred": 0}
    rate = engaged / total
    cap = (total >= WILL_RECEPTIVITY_MIN_OBS and rate < WILL_RECEPTIVITY_TAU)
    return {"rate": round(rate, 3), "count": total, "applied_cap": cap,
            "engaged": engaged, "deferred": deferred}


def _impact_cost(g: dict) -> float:
    """Per-goal impact cost in [0, 1]. Subgoals carry a small bump
    because they're part of a larger plan whose total blast is bigger
    than a one-shot nudge."""
    base = WILL_KIND_IMPACT.get(g.get("kind", ""), WILL_KIND_IMPACT_DEFAULT)
    if g.get("parent_goal_id"):
        base = min(0.6, base + 0.05)
    return base


def _ingest_intent(intent: dict, source_subject: str) -> None:
    gid = _goal_id(intent)
    now = time.time()
    with _lock:
        if gid in _active_goals:
            # Re-occurrence: bump importance slightly, refresh ts
            g = _active_goals[gid]
            g["importance"] = min(1.0, g.get("importance", 0.5) + 0.05)
            g["last_seen_ts"] = now
            g["seen_count"] = int(g.get("seen_count", 1)) + 1
        else:
            if len(_active_goals) >= MAX_ACTIVE_GOALS:
                # Evict the lowest-utility goal
                lowest = min(_active_goals.items(),
                             key=lambda kv: kv[1].get("importance", 0.5))
                del _active_goals[lowest[0]]
            _active_goals[gid] = {
                "goal_id": gid,
                "kind": intent["kind"],
                "description": intent["description"],
                "source_subject": source_subject,
                "raw_text": intent.get("raw_text", "")[:300],
                "importance": intent["base_importance"],
                "formed_at": now,
                "last_seen_ts": now,
                "seen_count": 1,
                "status": "active",
            }
            _append_ledger({"phase": "formed", **_active_goals[gid]})
            _publish("brain.will.goal_formed", _active_goals[gid])
    _persist_active()


# ─────────────────────────────────────────────────────────
# 3. UTILITY SCORING — generic, no domain code
# ─────────────────────────────────────────────────────────

def _utility(g: dict, now: float) -> float:
    """utility = importance × time_pressure × context_fit × feasibility,
    each in [0, 1]. Generic across all goal kinds."""
    importance = float(g.get("importance", 0.5))
    age_days = (now - float(g.get("formed_at", now))) / 86400.0
    # time_pressure curve: starts at 0.3 (fresh, low pressure), peaks ~3 days,
    # then decays via per-kind half-life (Build #4 evidence-weighted decay).
    kind_half_life = _kind_half_life_days(g.get("kind", ""), now=now)
    if age_days < 0.5:
        time_pressure = 0.3
    elif age_days < 3.0:
        time_pressure = 0.3 + (age_days - 0.5) * 0.28  # rises to ~1.0 at 3d
    else:
        decay = 0.5 ** ((age_days - 3.0) / max(0.5, kind_half_life))
        time_pressure = max(0.05, 1.0 * decay)

    # context_fit: prefer Empathy's live state vector (memo §7) — it
    # captures availability AND focus, not just last-inbound recency.
    # Falls back to the original last-inbound-age heuristic when
    # Empathy is unavailable (older hosts, missing module). A user
    # in focus drops context_fit hard so will doesn't promote goals
    # mid-flow; high availability lifts it; the floor is 0.15 so a
    # goal can still fire when nothing is observable.
    context_fit = None
    try:
        from orion_empathy import tick as _empathy_tick
        state = _empathy_tick(now)
        if state.get("focus"):
            context_fit = 0.15  # heads-down — let it ride unless emergency
        else:
            # availability already decays with time-since-last-activity
            # over a 10-min half-life; ride that as the headline signal.
            context_fit = max(0.2, float(state.get("availability", 0.5)))
    except Exception:
        # Empathy not importable on this host yet — use the original
        # last-inbound-age heuristic so existing behavior is preserved.
        last_user_inbound_age_sec = _last_user_inbound_age_sec()
        if last_user_inbound_age_sec is None:
            context_fit = 0.3
        elif last_user_inbound_age_sec < 60 * 30:
            context_fit = 0.8  # user is engaged right now
        elif last_user_inbound_age_sec < 60 * 60 * 4:
            context_fit = 0.5
        else:
            context_fit = 0.2

    # feasibility: is at least one channel wired?
    feasibility = 0.6 if _any_channel_wired() else 0.2

    return importance * time_pressure * context_fit * feasibility


def _last_user_inbound_age_sec() -> float | None:
    """Read claustrum's state to find the most-recent inbound across channels."""
    state_path = Path.home() / ".orion" / "consciousness" / "state.json"
    if not state_path.exists():
        return None
    try:
        s = json.loads(state_path.read_text(encoding="utf-8"))
        ch_seen = s.get("channel_last_seen") or {}
        most_recent_ts = max((info.get("ts", 0) for info in ch_seen.values()),
                             default=0)
        if most_recent_ts <= 0:
            return None
        return time.time() - most_recent_ts
    except Exception:
        return None


def _any_channel_wired() -> bool:
    state_path = Path.home() / ".orion" / "channels"
    if not state_path.exists():
        return False
    for f in state_path.glob("*.json"):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
            for s in m.get("surfaces", []):
                if s.get("status") in ("active", "wired"):
                    return True
        except Exception:
            continue
    return False


# ─────────────────────────────────────────────────────────
# 4. ACTION SELECTION — propose via reach.py with cooldown
# ─────────────────────────────────────────────────────────

def _load_cooldowns() -> dict:
    p = WILL_DIR / "cooldown.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cooldowns(c: dict) -> None:
    WILL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        (WILL_DIR / "cooldown.json").write_text(
            json.dumps(c, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _select_and_initiate() -> None:
    now = time.time()
    cooldowns = _load_cooldowns()
    # AFFECT integration — the will reads its CURRENT MOOD and shifts the
    # firing threshold by it. Negative valence + low care raises the bar
    # (be quieter when sad / distant); high arousal lowers it (be more
    # reactive when alert). orion_affect.bias_for returns the delta
    # additively; missing affect layer → 0 delta → unchanged behavior.
    # Per the founder's 2026-05-23 position: real functional emotion,
    # not simulation — the state genuinely changes what fires.
    threshold_delta = 0.0
    try:
        import orion_affect
        bias = orion_affect.bias_for("will_firing")
        threshold_delta = float(bias.get("utility_threshold_delta", 0.0))
    except Exception:
        pass
    effective_threshold = UTILITY_THRESHOLD + threshold_delta
    candidates: list[tuple[float, dict]] = []
    with _lock:
        for gid, g in list(_active_goals.items()):
            u = _utility(g, now)
            g["last_utility"] = round(u, 3)
            if u < effective_threshold:
                continue
            last_fired = cooldowns.get(gid, 0)
            if (now - last_fired) < ACTION_COOLDOWN_SEC:
                continue
            candidates.append((u, g))
    if not candidates:
        return

    # Build #4 — impact-weighted selection. Raw utility says "how much
    # do I want to act?"; (1 − impact_cost) says "and how cheap is being
    # wrong here?". The product is the safer-greedy selection: on tied
    # utility the smaller-blast goal wins. utility ≠ alignment.
    candidates.sort(key=lambda x: -(x[0] * (1.0 - _impact_cost(x[1]))))
    utility, goal = candidates[0]

    # Compose user-facing text describing the goal
    user_msg = _format_goal_message(goal)

    _publish("brain.will.candidate", {
        "goal_id": goal["goal_id"],
        "utility": utility,
        "kind": goal["kind"],
        "description": goal["description"],
        "ts": now,
    })

    # Surface as a synthesis candidate so reach picks it up + speaks-where-they-spoke
    _publish("brain.synthesis.candidate", {
        "kind": "will_initiated",
        "evidence": {
            "goal_id": goal["goal_id"],
            "kind": goal["kind"],
            "description": goal["description"][:200],
            "utility": round(utility, 3),
            "user_message": user_msg,
        },
        "priority": min(0.9, utility),
        "ts": now,
    })

    cooldowns[goal["goal_id"]] = now
    _save_cooldowns(cooldowns)
    _append_ledger({"phase": "initiated", "goal_id": goal["goal_id"],
                    "utility": utility, "ts": now})
    _publish("brain.will.action_initiated", {
        "goal_id": goal["goal_id"], "utility": utility, "ts": now,
    })
    logger.info("will initiated: %s (utility=%.3f)",
                goal["description"][:80], utility)

    # Build #3 — will → taskspine promotion. Make the fired goal a DURABLE
    # task on the spine so it survives host death + fuel timeout, gated by
    # the Phase-2 governor. Corrigibility lives in the brain (the governor,
    # the spine), not the fuel — a fuel swap mid-pursuit can't bypass it.
    task_id = _promote_to_spine(goal, utility, user_msg)
    if task_id:
        with _lock:
            goal["spine_task_id"] = task_id
        _persist_active()


# ─────────────────────────────────────────────────────────
# Build #3 — TASKSPINE PROMOTION + CALIBRATION CLOSURE
# Per next-3 #3 (synthesis-continual-learning + autonomous-volition memos):
# bounded autonomous goals, governor-gated, durable on the spine, with
# the outcome fed back into the metacog ledger so the will EARNS
# calibration on its goal kinds (same closed loop as mesh_recovery).
# ─────────────────────────────────────────────────────────


def _will_action_key(goal: dict) -> tuple[str, str]:
    """Build the (action, symptom) strings the governor + record_outcome share.
    These MUST be identical between the promotion-time governor() call and the
    closure-time record_outcome() call — the metacog Jaccard match is keyed on
    these tokens, so any divergence silently breaks calibration learning."""
    kind = goal.get("kind", "self_action")
    return (
        "pursue will-goal kind=%s" % kind,
        "will_promotion_%s" % kind,
    )


def _promote_to_spine(goal: dict, utility: float, user_msg: str) -> str | None:
    """Consult the governor; if it says auto, create a durable taskspine task
    seeded with the goal. Returns the task_id (so closure can find it) or None
    if the governor held or the spine is unavailable.

    Why governor-gated: a will-goal that gets deferred 5/5 times in a row
    means we're nagging — the ledger should drag the governor toward 'ask'
    for that goal kind. Today the base for reversible+single is 0.80 (auto),
    so this is a calibration sensor that only revokes autonomy on bad track
    records. New goal kinds always promote; chronically-ignored kinds stop.

    Build #4 — wrap the governor verdict with a cross-kind RECEPTIVITY cap:
    if the user has been deferring broadly in the last 24h (rate < tau),
    don't promote ANY kind regardless of per-kind history. Build #3's
    per-kind calibration silos this signal; this is the broad override
    that catches "user is in quiet mode" before nagging cross-contaminates
    every silo.
    """
    action, symptom = _will_action_key(goal)
    recept = will_user_receptivity()
    if recept.get("applied_cap"):
        # Cross-kind quiet-mode override. Skip the governor entirely — we
        # know we're nagging across the board, so don't even ask. Log the
        # hold and the receptivity so a dashboard / dream pass can see WHY
        # promotion was suppressed (not a per-kind calibration miss).
        _append_ledger({"phase": "promotion_held", "goal_id": goal["goal_id"],
                        "reason": "receptivity_cap",
                        "receptivity": recept, "ts": time.time()})
        logger.info("will held promotion (receptivity cap): %s/%s engaged "
                    "(rate=%.2f tau=%.2f)",
                    recept["engaged"], recept["count"],
                    recept["rate"], WILL_RECEPTIVITY_TAU)
        return None

    try:
        import orion_metacognition
        g = orion_metacognition.governor(
            action, reversible=True, blast_radius="single",
            symptom=symptom, fuel="will")
        if g.get("decision") != "auto":
            _append_ledger({"phase": "promotion_held", "goal_id": goal["goal_id"],
                            "governor_conf": g.get("confidence"),
                            "basis": g.get("basis"),
                            "receptivity": recept, "ts": time.time()})
            return None
    except Exception as e:
        # Fail-open at the tier-2 default: a will-goal is reversible+single
        # by construction, so without a governor reading we still promote.
        logger.debug("governor consult failed: %s — proceeding at tier-2 default", e)

    try:
        import orion_taskspine
        task_id = orion_taskspine.create_task(
            "will-goal[%s]: %s" % (goal.get("kind", ""),
                                   goal.get("description", "")[:160]))
        # Seed the task with the goal's evidence so a host that resumes it
        # has every input the originating host had — including the fuel-
        # agnostic user_msg, so any fuel can pick up the pursuit.
        orion_taskspine._append(task_id, {
            "kind": "step", "idx": 0, "role": "will",
            "content": "promoted from goal_id=%s utility=%.3f kind=%s desc=%s | first surface: %s"
                       % (goal["goal_id"], utility, goal.get("kind", ""),
                          goal.get("description", "")[:200], user_msg[:200]),
            "status": "done", "fuel": "will",
            "hash": "will-promote-%s" % goal["goal_id"][:8],
        })
        _publish("brain.will.promoted_to_spine", {
            "goal_id": goal["goal_id"], "task_id": task_id, "ts": time.time(),
        })
        logger.info("will promoted goal %s to spine task %s",
                    goal["goal_id"][:8], task_id)
        # Build #4 — for kinds that genuinely need multi-step pursuit, decompose
        # into ordered sub-goals on the spine. Each sub-goal becomes a first-
        # class active goal that re-enters the pipeline; the spine carries the
        # plan so it survives host death AND fuel timeout. Decomposition is
        # best-effort: a missing fuel leaves the parent as a single-shot reach
        # (no regression from Build #3 behavior).
        if goal.get("kind") in WILL_SUBGOAL_KINDS \
                and not goal.get("parent_goal_id") \
                and len(goal.get("description", "")) >= WILL_SUBGOAL_MIN_DESC:
            try:
                _decompose_and_seed_subgoals(goal, task_id)
            except Exception as e:
                logger.debug("subgoal decomposition skipped (%s)", e)
        return task_id
    except Exception as e:
        logger.warning("spine promotion failed (goal stays live): %s", e)
        return None


# ─────────────────────────────────────────────────────────
# Build #4 — HIERARCHICAL SUBGOAL DECOMPOSITION
# Long-horizon kinds become a tree on the spine. The plan is cached
# on the spine as a single "plan" step so a fresh process / resumed
# host doesn't re-burn fuel to re-decompose. Each sub-goal is itself
# an active goal that consults the governor on its own promotion.
# ─────────────────────────────────────────────────────────

def _subgoal_kind_for(parent_kind: str) -> str:
    """Sub-goals inherit a slimmer kind so they don't recursively
    decompose into sub-sub-goals on the next promotion. Parent kept
    as long_term/self_action; children execute as 'self_action' (the
    smallest action-y kind that still surfaces as a step prompt)."""
    return "self_action"


def _subgoal_id(parent_gid: str, idx: int) -> str:
    """Deterministic so re-decomposition (host resume) doesn't dup."""
    payload = ("subgoal|%s|%d" % (parent_gid, idx)).encode()
    return "g_" + hashlib.sha256(payload).hexdigest()[:10]


def _fuel_decompose(goal: dict) -> list[str] | None:
    """Best-effort fuel call to break a parent goal into ordered steps.
    Returns a list of short step descriptions, or None if fuel was
    unavailable. The prompt is intentionally tight — shallow plans
    only (≤ WILL_SUBGOAL_MAX), one line each, no commentary."""
    try:
        import orion_fuel
    except Exception:
        return None
    prompt = (
        "Decompose this goal into between 2 and %d ordered, concrete sub-steps.\n"
        "Rules: one step per line, no numbering, no commentary, no preamble.\n"
        "Each step is a short imperative phrase (≤120 chars).\n"
        "Stop after the last step — do NOT output anything else.\n\n"
        "GOAL (%s): %s"
    ) % (WILL_SUBGOAL_MAX, goal.get("kind", "self_action"),
         goal.get("description", "")[:300])
    try:
        text, _engine = orion_fuel.get_fuel(prompt, interface="will-decompose")
    except Exception:
        return None
    if not text:
        return None
    lines = []
    for raw in text.splitlines():
        s = raw.strip().lstrip("-*•0123456789.) \t").strip()
        if not s:
            continue
        if len(s) < 4 or len(s) > 200:
            continue
        # Drop common preamble lines a sloppy fuel still emits.
        low = s.lower()
        if low.startswith(("here are", "sure,", "okay,", "step ", "decomposition")):
            continue
        lines.append(s)
        if len(lines) >= WILL_SUBGOAL_MAX:
            break
    return lines or None


def _decompose_and_seed_subgoals(parent_goal: dict, task_id: str) -> int:
    """Decompose parent_goal via the fuel; seed sub-goals as first-class
    active goals AND record the plan as a structured step on the spine
    task so a resuming host has the full plan. Returns the count of
    sub-goals created (0 if the fuel was unavailable or returned junk)."""
    import orion_taskspine
    # Idempotency: if we already seeded sub-goals for this parent, don't
    # re-decompose. Check the spine task for a prior plan step.
    existing = orion_taskspine.load_task(task_id) or {}
    for s in existing.get("steps", []):
        if s.get("role") == "will-plan":
            return 0  # already decomposed; resume path
    steps = _fuel_decompose(parent_goal)
    if not steps:
        return 0
    parent_gid = parent_goal["goal_id"]
    now = time.time()
    orion_taskspine._append(task_id, {
        "kind": "step", "idx": 1, "role": "will-plan",
        "content": "decomposed parent=%s into %d sub-goals: %s"
                   % (parent_gid, len(steps),
                      json.dumps([s[:120] for s in steps], ensure_ascii=False)),
        "status": "done", "fuel": "will",
        "hash": "will-plan-%s" % parent_gid[:8],
    })
    sub_kind = _subgoal_kind_for(parent_goal.get("kind", ""))
    created = 0
    with _lock:
        for i, desc in enumerate(steps):
            sgid = _subgoal_id(parent_gid, i)
            if sgid in _active_goals:
                continue
            # Sub-goals inherit a slight importance bump so they actually
            # clear UTILITY_THRESHOLD when the parent's been deemed worth
            # acting on — without this, a 0.4-importance long-term parent
            # produces 0.4-importance sub-goals that never fire.
            sub_imp = min(1.0, float(parent_goal.get("importance", 0.5)) + 0.10)
            # Earlier sub-goals get a small extra bump so they tend to
            # surface in order without needing per-goal sequencing logic.
            sub_imp = min(1.0, sub_imp + max(0.0, 0.05 * (len(steps) - i)))
            _active_goals[sgid] = {
                "goal_id": sgid,
                "kind": sub_kind,
                "description": desc[:240],
                "source_subject": "will.subgoal_decomposition",
                "raw_text": parent_goal.get("description", "")[:300],
                "importance": sub_imp,
                "formed_at": now,
                "last_seen_ts": now,
                "seen_count": 1,
                "status": "active",
                "parent_goal_id": parent_gid,
                "parent_task_id": task_id,
                "subgoal_idx": i,
            }
            _append_ledger({"phase": "subgoal_formed", **_active_goals[sgid]})
            _publish("brain.will.goal_formed", _active_goals[sgid])
            created += 1
    _persist_active()
    logger.info("decomposed parent %s into %d sub-goals via spine task %s",
                parent_gid[:8], created, task_id)
    _publish("brain.will.decomposed", {
        "parent_goal_id": parent_gid, "task_id": task_id,
        "subgoal_count": created, "ts": now,
    })
    return created


# Map will-outcomes to metacog ledger keys. 'engaged' (user replied
# substantively) is the will's positive signal; 'deferred' (ignored/later)
# means the action was unwelcome — but it's not 'failed' (the goal didn't
# break anything; it just didn't land). Map deferred→ignored so the ledger
# accumulates the right signal: repeated ignored→ratchet on the governor.
_WILL_OUTCOME_TO_METACOG = {
    "engaged": "succeeded",
    "deferred": "ignored",
    "expired":  "failed",
}


def _close_spine_outcome(goal: dict, outcome: str) -> None:
    """When a will-goal's outcome lands, close any durable spine task we
    created at promotion time, AND feed the outcome to the metacog ledger
    under the SAME (action, symptom) the governor saw at promotion. That's
    what lets the governor EARN calibration on goal kinds: too many ignored
    outcomes on kind=lapsed → contribution drops → governor flips auto→ask
    on the next lapsed-kind goal."""
    task_id = goal.get("spine_task_id")
    if task_id:
        try:
            import orion_taskspine
            orion_taskspine._append(task_id, {
                "kind": "step", "idx": 99, "role": "will",
                "content": "outcome: %s" % outcome,
                "status": "done", "fuel": "will",
                "hash": "will-close-%s-%s" % (goal["goal_id"][:8], outcome[:6]),
            })
            orion_taskspine._append(task_id, {
                "kind": "task", "id": task_id,
                "status": "complete" if outcome == "engaged" else "closed",
            })
        except Exception as e:
            logger.debug("spine closure failed: %s", e)

    action, symptom = _will_action_key(goal)
    mapped = _WILL_OUTCOME_TO_METACOG.get(outcome, "ignored")
    try:
        import orion_metacognition
        orion_metacognition.record_outcome(
            action, mapped, symptom=symptom, fuel="will",
            goal_id=goal.get("goal_id"),
            goal_kind=goal.get("kind"))
    except Exception as e:
        logger.debug("metacog record_outcome failed: %s", e)


def _format_goal_message(g: dict) -> str:
    """Generic phrasing — let the LLM-assisted layer dress this up later
    if quality matters more. For now, polite and direct."""
    kind = g.get("kind", "self_action")
    desc = g.get("description", "")
    if kind == "reminder":
        return f"You asked me to remind you to {desc}. Want to do that now?"
    if kind == "memory_anchor":
        return f"Reminder I'm holding for you: {desc}."
    if kind == "lapsed":
        return f"I noticed it's been a while since {desc}. Want me to bring it up next session?"
    if kind == "long_term":
        return f"You mentioned wanting to {desc}. Should we talk about a first step?"
    if kind == "self_note":
        return f"Note you left for yourself: {desc}."
    return f"You said you should {desc}. Worth taking a step now?"


# ─────────────────────────────────────────────────────────
# 5. OUTCOME LEARNING — feedback from substrate
# ─────────────────────────────────────────────────────────

def _on_user_inbound(subject: str, payload: dict) -> None:
    """User replied — broadly counts as positive engagement with whatever
    will most-recently surfaced. Mark the most-recent fired goal as
    "engaged"; if reply is "ignore" / "stop" / "later", mark "deferred"."""
    text = (payload.get("text") or "").lower().strip()
    if not text:
        return
    cooldowns = _load_cooldowns()
    if not cooldowns:
        return
    most_recent_gid = max(cooldowns.items(), key=lambda kv: kv[1])[0]
    age = time.time() - cooldowns[most_recent_gid]
    if age > 600:  # only the last 10 min of fires count as "engaging with this"
        return
    with _lock:
        g = _active_goals.get(most_recent_gid)
    if not g:
        return
    if any(w in text for w in ("ignore", "stop", "later", "not now",
                                 "dismiss", "shut up", "leave me")):
        outcome = "deferred"
        with _lock:
            g["importance"] = max(0.0, g.get("importance", 0.5) - 0.15)
    else:
        outcome = "engaged"
        with _lock:
            g["importance"] = min(1.0, g.get("importance", 0.5) + 0.05)

    _append_ledger({"phase": "outcome", "goal_id": most_recent_gid,
                    "outcome": outcome, "ts": time.time()})
    _publish("brain.will.outcome", {
        "goal_id": most_recent_gid, "outcome": outcome, "ts": time.time(),
    })
    # Build #3 — close the durable spine task (if any) AND feed the outcome
    # into the metacog ledger keyed on this goal's kind. That is what
    # converts "will got engaged/deferred" into a calibration signal the
    # governor reads next time this kind of goal is up for promotion.
    _close_spine_outcome(g, outcome)


# ─────────────────────────────────────────────────────────
# Substrate handlers
# ─────────────────────────────────────────────────────────

def _publish(subject: str, payload: dict) -> None:
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass


def _on_text_event(subject: str, payload: dict) -> None:
    """Catch text from channel.*.inbound and brain.memory.stored events.
    Run hybrid intent extraction over the text (regex + cached fuel)."""
    text = payload.get("text") or payload.get("content") or ""
    if not text:
        return
    _recent_events.append({"subject": subject, "text": text, "ts": time.time()})
    intents = _extract_intents_v2(text)
    for intent in intents:
        _publish("brain.will.intent_extracted", intent)
        _ingest_intent(intent, subject)


# ─────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────

def _scan_loop() -> None:
    while not _stop.is_set():
        try:
            _select_and_initiate()
        except Exception as e:
            logger.warning("scan loop error: %s", e)
        _stop.wait(SCAN_INTERVAL_SEC)


# ─────────────────────────────────────────────────────────
# PROACTIVE ALERT REFLEX (task #22)
# Founder rule 2026-05-15: 'the user should always know when something's
# wrong AND when something was fixed. Silent failures are unacceptable.'
# This is the will turning its initiative outward at SYSTEM events,
# not just user-intent events.
# ─────────────────────────────────────────────────────────

# Cooldown per source so a flapping service doesn't spam the user.
_alert_cooldowns: dict[str, float] = {}
ALERT_COOLDOWN_SEC = float(os.environ.get("ORION_ALERT_COOLDOWN", "180"))


def _classify_severity(subject: str, payload: dict) -> str:
    """Map substrate event into info / warning / critical."""
    if subject == "brain.storage.degraded":
        return "critical"  # silent storage loss is always critical
    if subject == "brain.executive.failure":
        return "critical"
    if subject == "brain.fuel.degraded":
        # If we still have ANY working fuel, it's a warning; otherwise critical.
        return "warning"
    if subject == "brain.health.alert":
        kind = (payload or {}).get("kind", "")
        if kind in ("silent", "down", "high_error_rate"):
            return "critical"
        return "warning"
    return "info"


def _format_alert(subject: str, payload: dict, severity: str) -> str:
    """Plain-English narration of a system event for the user."""
    p = payload or {}
    host = p.get("host") or os.environ.get("ORION_HOST_ID", "?")
    service = p.get("service") or p.get("component") or "?"
    cause = (p.get("error") or p.get("reason") or p.get("cause") or "")[:200]
    tag = {"info": "Heads up", "warning": "Heads up",
           "critical": "Critical"}.get(severity, "Heads up")
    if subject == "brain.storage.degraded":
        return (f"{tag}: brain storage write failed on {host}.\n"
                f"Cause: {cause}\n"
                f"I can't memorize anything until the underlying storage is writable. "
                f"This usually means filesystem permissions or a disk that went read-only.")
    if subject == "brain.executive.failure":
        return (f"{tag}: executive deliberation failed.\n"
                f"Component: {service}\n"
                f"Cause: {cause}\n"
                f"I couldn't auto-resolve the underlying issue. Surface ticket: "
                f"~/.orion/executive/decisions.jsonl latest entry.")
    if subject == "brain.fuel.degraded":
        return (f"{tag}: fuel quality dropped — falling back to a weaker model.\n"
                f"Component: {service}\n"
                f"Cause: {cause}\n"
                f"Recovery: run `claude /login` (or codex/gemini equivalent), "
                f"or check ANTHROPIC_API_KEY / Ollama availability.")
    if subject == "brain.health.alert":
        kind = p.get("kind", "alert")
        return (f"{tag}: {service} on {host} flagged '{kind}'.\n"
                f"Vitals: {p.get('vitals', '?')}\n"
                f"Self-heal will attempt automatic recovery; if it can't, "
                f"you'll get a follow-up.")
    return f"{tag}: {subject} on {host} — {cause}"


def _on_health_event(subject: str, payload: dict) -> None:
    """Subscriber for system-health events. Classifies + reaches out."""
    # Spam-fix 2026-05-16: skip canary-class alerts. orion_autofix owns
    # the canary-symptom flow with copy-paste fix steps; will narrating
    # the same alert in parallel was one of three duplicate senders
    # behind the iMessage flood.
    kind = (payload or {}).get("kind", "")
    service = (payload or {}).get("service", "") or ""
    if kind in ("canary_fail", "ok_to_fail", "sustained_escalation",
                "canary_recovered") or service.startswith("canary."):
        return
    severity = _classify_severity(subject, payload)
    src_key = f"{subject}::{(payload or {}).get('service','?')}::{(payload or {}).get('host','?')}"
    now = time.time()
    last = _alert_cooldowns.get(src_key, 0.0)
    if (now - last) < ALERT_COOLDOWN_SEC and severity != "critical":
        logger.debug("alert cooldown active for %s; skipping", src_key)
        return
    _alert_cooldowns[src_key] = now
    text = _format_alert(subject, payload or {}, severity)
    try:
        from orion_substrate import publish
        # Route via reach — reach picks the warmest active channel
        publish("channel.imessage.outbound", {
            "text": text,
            "ts": now,
            "severity": severity,
            "source": subject,
            "via": "orion_will.proactive_alert",
        })
        # Also publish on a topic any other listener can hook
        publish("brain.will.alerted", {
            "subject": subject, "severity": severity,
            "text_preview": text[:120], "ts": now,
        })
        logger.info("PROACTIVE ALERT [%s] %s :: %s",
                    severity, subject, text[:120])
    except Exception as e:
        logger.warning("alert publish failed for %s: %s", subject, e)


def _on_recovery_event(subject: str, payload: dict) -> None:
    """Subscriber for autonomous recoveries — narrate the FIX too."""
    p = payload or {}
    text = (
        f"Recovered: {p.get('service', 'a component')} on "
        f"{p.get('host', os.environ.get('ORION_HOST_ID', '?'))} is healthy again.\n"
        f"What I did: {p.get('action', 'self-heal reflex')}\n"
        f"You don't need to do anything."
    )
    try:
        from orion_substrate import publish
        publish("channel.imessage.outbound", {
            "text": text, "ts": time.time(), "severity": "info",
            "source": subject, "via": "orion_will.proactive_recovery",
        })
        logger.info("RECOVERY NARRATED :: %s", text[:120])
    except Exception as e:
        logger.warning("recovery narrate publish failed: %s", e)


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        logger.error("orion_substrate not importable")
        return 1

    sub = get_substrate()
    sub._connect_blocking()

    _load_active()

    subscribe("channel.*.inbound", _on_text_event)
    subscribe("brain.memory.stored", _on_text_event)
    # Outcome feedback
    subscribe("channel.*.inbound", _on_user_inbound)
    # Proactive-alert reflex — Orion narrates compromises + autonomous
    # fixes so the user never has to discover a silent failure (founder
    # requirement 2026-05-15, task #22). Subscribes the four substrate
    # subjects that mean 'something broke or got fixed without you':
    subscribe("brain.health.alert", _on_health_event)
    subscribe("brain.executive.failure", _on_health_event)
    subscribe("brain.fuel.degraded", _on_health_event)
    subscribe("brain.storage.degraded", _on_health_event)
    subscribe("brain.health.recovered", _on_recovery_event)

    logger.info("will alive — host=%s scan=%ds threshold=%.2f cooldown=%ds; "
                "%d active goals loaded",
                os.environ.get("ORION_HOST_ID", "command"),
                int(SCAN_INTERVAL_SEC), UTILITY_THRESHOLD,
                int(ACTION_COOLDOWN_SEC), len(_active_goals))

    threading.Thread(target=_scan_loop, name="will-scan", daemon=True).start()

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
