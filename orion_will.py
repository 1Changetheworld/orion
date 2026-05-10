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

- Plan multi-step actions (single-shot proposals only)
- Manage long-running goals across days (basic timestamp tracking
  only, no rich scheduling)
- Self-modify its scoring weights (uses fixed defaults; outcome
  learning is the door to that, not yet built)
- Compete goals against each other in real-time (utility threshold
  filter is a coarse proxy; ACT-R-style continuous matching is
  next round)

Each of these is a known-future-frontier piece. The first version
is observable, predictable, and conservative.

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
    """Run patterns over a text event. Return zero or more intent records."""
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
    # then decays via half-life (older goals get less urgent unless re-seen)
    if age_days < 0.5:
        time_pressure = 0.3
    elif age_days < 3.0:
        time_pressure = 0.3 + (age_days - 0.5) * 0.28  # rises to ~1.0 at 3d
    else:
        decay = 0.5 ** ((age_days - 3.0) / GOAL_DECAY_HALF_LIFE_DAYS)
        time_pressure = max(0.05, 1.0 * decay)

    # context_fit: any user-facing channel had inbound recently?
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
    candidates: list[tuple[float, dict]] = []
    with _lock:
        for gid, g in list(_active_goals.items()):
            u = _utility(g, now)
            g["last_utility"] = round(u, 3)
            if u < UTILITY_THRESHOLD:
                continue
            last_fired = cooldowns.get(gid, 0)
            if (now - last_fired) < ACTION_COOLDOWN_SEC:
                continue
            candidates.append((u, g))
    if not candidates:
        return

    candidates.sort(key=lambda x: -x[0])
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
    Run intent extraction over the text."""
    text = payload.get("text") or payload.get("content") or ""
    if not text:
        return
    _recent_events.append({"subject": subject, "text": text, "ts": time.time()})
    intents = _extract_intents(text)
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
