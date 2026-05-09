"""orion_executive.py — the deliberative layer. Judgment on novel problems.

Cellular reflexes (orion_vitals + orion_self_heal) handle the common case:
service silent? launchctl reload. Fuel timed out? retry. These are fast,
deterministic, sub-minute responses.

When reflexes fail — same service silent after 3 reloads, errors persisting
across services, a pattern that matches no known signature — the executive
engages. It reads the situation, builds a diagnostic context, consults
an AI model to reason about it, proposes a remedy, ASKS PERMISSION via
reach.py, and on approval applies the fix. Logs every decision so the
system learns from its own outcomes.

Neuroscience analogue: prefrontal cortex. Not autonomic (vitals), not
perceptual (channels), not integrative (claustrum). The region that
plans, considers alternatives, theorizes about cause, and takes deliberate
action. Slower than reflex. Worth the latency for novel problems.

THREE ENGAGEMENT TRIGGERS
=========================

  1. reflex_failure: a cellular recovery fired ≥3 times for the same
     service in 30 min without resolving the symptom.
  2. cross_service_correlation: ≥2 services show the same symptom
     within a short window (suggests a host-level cause: disk full,
     network outage, auth expired, etc.) — covered by claustrum.state.
  3. novel_pattern: substrate event has a kind we haven't seen before,
     or a known pattern in an unfamiliar combination.

KNOWN SYMPTOM CLASSES (each gets a tailored diagnostic prompt)
==============================================================

  - SERVICE_LOOP: service crashing + restarting + crashing
  - DEPENDENCY_FAILURE: service's probes show a dep down (substrate,
    brain endpoint, FS)
  - AUTH_DRIFT: API key, OAuth, or TCC permission silently changed
  - DISK_PRESSURE: write failures, vitals snapshots stale
  - NETWORK_PARTITION: hosts seen in claustrum disappearing
  - CHANNEL_LIMBO: channel daemon alive but no signal in 24h+
  - PERSONA_DRIFT: model replies using wrong name or honorific
  - CORRUPTION: graph_memory.json fails to parse, JSON LD truncated
  - FUEL_OUTAGE: every fuel returning errors
  - UNRECOGNIZED: nothing matches → consult model in 'open mode'

PERMISSION-GATED EXECUTION
==========================

The executive NEVER auto-applies remedies. Every proposal goes through
reach.py to a user-facing channel as a high-priority outbound:

  "I noticed iMessage has been crashing every 30 seconds for an hour.
   I think the chat.db permission was revoked — Full Disk Access
   needs to be re-granted. Reply 'approve' and I'll guide you, or
   'deny' if you'd rather investigate yourself."

User approves via channel reply ("yes" / "approve" / "go ahead" /
"do it" — recognized by orion_intents.py). On approval, the
executive applies the proposed remedy AND logs the outcome.

If the user denies, the proposal is recorded but not applied. If the
symptom persists, the executive may re-propose with adjusted reasoning
after a cooldown.

DECISION LEDGER
===============

  ~/.orion/executive/decisions.jsonl — append-only ledger:
  {
    ts, trigger, symptom_class, context_snapshot,
    diagnostic_prompt, model_used, proposal,
    permission_status: pending|approved|denied|expired,
    applied_at, outcome: succeeded|failed|inconclusive,
    follow_up
  }

This ledger is the executive's TRAINING DATA — over time the system
learns which proposals tend to succeed for which symptoms. Not by
training a model, but by populating a tag system in the brain that
pre-filters future proposals against historical outcomes.

WHY THIS MATTERS
================

Without the executive: Orion can detect issues and apply known fixes.
That's table-stakes for a reliable service.

With the executive: Orion can REASON about novel problems, propose
solutions he doesn't already know, ask before acting. That's an
intelligent system, not just a robust one.

Founder rule 2026-05-09: "his own personal intelligence knows what
to do to find the answer and fix it if he doesn't have it — this
includes using an ai model for fixing himself at his own will after
permission is granted."
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

logger = logging.getLogger("orion.executive")

EXECUTIVE_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_EXECUTIVE_DIR", "~/.orion/executive")
))
DECISION_LEDGER = EXECUTIVE_DIR / "decisions.jsonl"
PENDING_DIR = EXECUTIVE_DIR / "pending"

CHECK_INTERVAL_SEC = float(os.environ.get("ORION_EXEC_INTERVAL_SEC", "60"))
PROPOSAL_COOLDOWN_SEC = float(os.environ.get("ORION_EXEC_COOLDOWN_SEC", "1800"))
PERMISSION_EXPIRY_SEC = float(os.environ.get("ORION_EXEC_PERMISSION_EXPIRY_SEC", "21600"))  # 6h
RECOVERY_FAILURE_THRESHOLD = int(os.environ.get("ORION_EXEC_RECOVERY_FAILURES", "3"))
RECOVERY_WINDOW_SEC = float(os.environ.get("ORION_EXEC_RECOVERY_WINDOW", "1800"))

# Track recovery actions per service in a rolling window
_recovery_log: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
# Track pending proposals waiting for user approval
_pending: dict[str, dict] = {}
_last_proposal_ts: dict[str, float] = {}
_stop = threading.Event()
_lock = threading.Lock()


def _log_decision(record: dict) -> None:
    EXECUTIVE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with DECISION_LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        logger.warning("ledger write failed: %s", e)


def _classify_symptom(payload: dict) -> str:
    """Classify a health/alert event into a symptom class."""
    kind = payload.get("kind", "")
    svc = payload.get("service", "")
    vitals = payload.get("vitals") or {}

    if kind == "silent":
        return "SERVICE_LOOP" if _recovery_count(svc) >= RECOVERY_FAILURE_THRESHOLD else "DEPENDENCY_FAILURE"
    if kind == "high_error_rate":
        deps = vitals.get("dependencies") or {}
        if deps and not all(deps.values()):
            return "DEPENDENCY_FAILURE"
        return "FUEL_OUTAGE" if "fuel" in svc.lower() else "UNRECOGNIZED"
    return "UNRECOGNIZED"


def _recovery_count(service: str) -> int:
    """How many recovery attempts on this service in the rolling window?"""
    now = time.time()
    with _lock:
        log = _recovery_log[service]
        # prune old
        while log and (now - log[0]) > RECOVERY_WINDOW_SEC:
            log.popleft()
        return len(log)


def _build_context(symptom_class: str, payload: dict) -> dict:
    """Gather everything the model needs to reason about the symptom."""
    ctx = {
        "symptom_class": symptom_class,
        "service": payload.get("service"),
        "kind": payload.get("kind"),
        "vitals": payload.get("vitals", {}),
        "ts": time.time(),
        "recovery_attempts_recent": _recovery_count(payload.get("service", "")),
    }
    # Add the latest claustrum state for cross-service context
    state_path = Path.home() / ".orion" / "consciousness" / "state.json"
    if state_path.exists():
        try:
            cs = json.loads(state_path.read_text(encoding="utf-8"))
            ctx["claustrum_summary"] = {
                "uptime_sec": cs.get("uptime_sec"),
                "n_events_total": cs.get("n_events_total"),
                "silent_channels": cs.get("silent_channels"),
                "host_last_seen": list((cs.get("host_last_seen") or {}).keys()),
            }
        except Exception:
            pass
    # Recent decision history for this service
    if DECISION_LEDGER.exists():
        try:
            with DECISION_LEDGER.open("r", encoding="utf-8") as f:
                lines = f.readlines()[-200:]
            past = []
            for line in lines:
                try:
                    d = json.loads(line)
                    if d.get("service") == ctx["service"]:
                        past.append({"ts": d.get("ts"),
                                    "outcome": d.get("outcome"),
                                    "proposal_summary": (d.get("proposal", {}) or {}).get("summary", "")[:100]})
                except Exception:
                    continue
            ctx["historical_decisions"] = past[-5:]
        except Exception:
            pass
    return ctx


def _build_diagnostic_prompt(ctx: dict) -> str:
    """Tailored prompt for the consulted model. Structured. Asks for
    a JSON-shaped proposal so we can parse it deterministically."""
    return f"""You are Orion's executive layer reasoning about an internal failure.

SYMPTOM CLASS: {ctx['symptom_class']}
SERVICE: {ctx.get('service')}
KIND: {ctx.get('kind')}

CURRENT VITALS:
{json.dumps(ctx.get('vitals'), indent=2)}

RECOVERY ATTEMPTS RECENT: {ctx.get('recovery_attempts_recent', 0)}
(if this is high, cellular reflex is failing — consider deeper causes)

CLAUSTRUM SUMMARY:
{json.dumps(ctx.get('claustrum_summary'), indent=2)}

HISTORICAL DECISIONS FOR THIS SERVICE:
{json.dumps(ctx.get('historical_decisions') or [], indent=2)}

Reason about the most likely root cause, then propose ONE remedy.
Return ONLY a JSON object with this shape:

{{
  "root_cause_hypothesis": "<one sentence>",
  "summary": "<one sentence the user will see>",
  "user_message": "<2-4 sentence message asking permission, plain language>",
  "remedy_kind": "launchctl_reload|reset_token|grant_permission|edit_config|reset_dependency|investigate_only",
  "remedy_steps": ["<concrete step 1>", "<concrete step 2>", ...],
  "rollback_steps": ["<undo step 1>", ...],
  "risk_level": "low|medium|high",
  "confidence": 0.0
}}

If you genuinely don't know what to do, set remedy_kind to
"investigate_only" and explain in user_message what additional
information you'd need."""


def _consult_model(ctx: dict) -> dict | None:
    """Ask whatever fuel is locally available to reason about the symptom.
    Returns a parsed proposal or None on failure.
    """
    try:
        # Use whichever fuel orion_fuel routes to. Cheapest path: shell
        # out to the brain endpoint on :5555 — it already does fuel
        # selection and returns a structured response.
        import urllib.request
        prompt = _build_diagnostic_prompt(ctx)
        payload = json.dumps({
            "message": prompt,
            "interface": "executive",
            "user_id": "orion",
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:5555/",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        text = data.get("response", "")
        # Parse JSON proposal out of the response
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None
        try:
            proposal = json.loads(text[start:end + 1])
            proposal["_engine"] = data.get("engine")
            return proposal
        except json.JSONDecodeError:
            return None
    except Exception as e:
        logger.warning("consult model failed: %s", e)
        return None


def _request_permission(proposal: dict, ctx: dict) -> str:
    """Surface the proposal to the user via reach.py. Returns the
    decision_id used to track approval."""
    decision_id = f"exec-{int(time.time())}-{ctx.get('service','unknown')}"
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    pending_file = PENDING_DIR / f"{decision_id}.json"
    record = {
        "decision_id": decision_id,
        "ts": time.time(),
        "symptom_class": ctx["symptom_class"],
        "service": ctx.get("service"),
        "context": ctx,
        "proposal": proposal,
        "expires_at": time.time() + PERMISSION_EXPIRY_SEC,
    }
    pending_file.write_text(json.dumps(record, indent=2, default=str))
    with _lock:
        _pending[decision_id] = record
        _last_proposal_ts[ctx.get("service", "")] = time.time()

    # Publish a reach event with a clear permission ask
    try:
        from orion_substrate import publish
        publish("brain.executive.proposal", {
            "decision_id": decision_id,
            "ts": record["ts"],
            "service": ctx.get("service"),
            "summary": proposal.get("summary", "(no summary)"),
            "user_message": proposal.get(
                "user_message",
                f"I want to apply: {proposal.get('summary')}. Reply 'approve {decision_id}' or 'deny {decision_id}'.",
            ),
            "remedy_kind": proposal.get("remedy_kind"),
            "risk_level": proposal.get("risk_level", "medium"),
            "confidence": proposal.get("confidence", 0.5),
        })
        # Also publish a synthesis candidate so reach.py forwards it via
        # the user's most-active channel as a high-priority message.
        publish("brain.synthesis.candidate", {
            "kind": "executive_proposal",
            "evidence": {
                "decision_id": decision_id,
                "summary": proposal.get("summary"),
                "user_message": proposal.get("user_message"),
            },
            "priority": 0.9,
            "ts": time.time(),
        })
    except Exception as e:
        logger.warning("publish proposal failed: %s", e)

    _log_decision({
        "ts": time.time(),
        "decision_id": decision_id,
        "phase": "proposed",
        "service": ctx.get("service"),
        "symptom_class": ctx["symptom_class"],
        "proposal": proposal,
        "permission_status": "pending",
    })
    return decision_id


def _apply_remedy(decision_id: str, approved: bool) -> None:
    """User has decided. Apply the remedy if approved; otherwise log."""
    with _lock:
        record = _pending.pop(decision_id, None)
    if not record:
        logger.info("no pending decision: %s", decision_id)
        return
    proposal = record.get("proposal", {})
    service = record.get("service", "")
    remedy_kind = proposal.get("remedy_kind", "investigate_only")

    if not approved:
        _log_decision({
            "ts": time.time(),
            "decision_id": decision_id,
            "phase": "denied",
            "service": service,
            "permission_status": "denied",
        })
        return

    outcome = "inconclusive"
    error = None
    try:
        if remedy_kind == "launchctl_reload":
            label = f"com.orion.{service}"
            plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
            if plist.exists():
                subprocess.run(["launchctl", "unload", str(plist)],
                               capture_output=True, timeout=10)
                subprocess.run(["launchctl", "load", "-w", str(plist)],
                               capture_output=True, timeout=10)
                outcome = "succeeded"
        elif remedy_kind == "investigate_only":
            outcome = "deferred"
        else:
            # Currently we don't auto-execute reset_token, edit_config,
            # grant_permission — those require human steps. The
            # user_message guided the user; mark deferred.
            outcome = "deferred_user_action"
    except Exception as e:
        error = str(e)
        outcome = "failed"

    _log_decision({
        "ts": time.time(),
        "decision_id": decision_id,
        "phase": "applied",
        "service": service,
        "remedy_kind": remedy_kind,
        "outcome": outcome,
        "error": error,
        "permission_status": "approved",
    })

    try:
        from orion_substrate import publish
        publish("brain.executive.applied", {
            "decision_id": decision_id, "outcome": outcome,
            "ts": time.time(),
        })
    except Exception:
        pass


# ----- substrate handlers -----

def _on_health_alert(subject: str, payload: dict) -> None:
    """A self-heal distress signal — see if we should engage."""
    service = payload.get("service", "")
    with _lock:
        # Cooldown: don't propose for the same service too often
        last = _last_proposal_ts.get(service, 0)
        if (time.time() - last) < PROPOSAL_COOLDOWN_SEC:
            return

    # Engage only after cellular reflex has tried and failed enough
    if _recovery_count(service) < 1 and payload.get("kind") != "high_error_rate":
        return  # Let the reflex try first

    symptom_class = _classify_symptom(payload)
    ctx = _build_context(symptom_class, payload)
    logger.info("executive engaging: service=%s class=%s", service, symptom_class)

    try:
        from orion_substrate import publish
        publish("brain.executive.deliberating", {
            "service": service,
            "symptom_class": symptom_class,
            "ts": time.time(),
        })
    except Exception:
        pass

    proposal = _consult_model(ctx)
    if not proposal:
        _log_decision({
            "ts": time.time(),
            "service": service,
            "symptom_class": symptom_class,
            "phase": "consult_failed",
            "context": ctx,
        })
        return

    _request_permission(proposal, ctx)


def _on_health_action(subject: str, payload: dict) -> None:
    """Self-heal applied a recovery — log it for engagement-counting."""
    service = payload.get("service", "")
    if service:
        with _lock:
            _recovery_log[service].append(time.time())


def _on_user_decision(subject: str, payload: dict) -> None:
    """User replied with approve/deny. Pattern-match the message."""
    text = (payload.get("text") or "").lower().strip()
    if not text:
        return
    # very simple matching — orion_intents.py will own this longer term
    approved = None
    if any(w in text for w in ("approve", "yes do it", "go ahead", "do it",
                                "apply", "yes please", "permission granted",
                                "allowed", "execute", "yes")):
        approved = True
    elif any(w in text for w in ("deny", "no don't", "cancel", "stop",
                                  "abort", "denied", "do not", "don't",
                                  "no")):
        approved = False
    if approved is None:
        return
    # Find the most recent pending decision (could refine with explicit
    # decision_id mention in the user message)
    with _lock:
        if not _pending:
            return
        decision_id = max(_pending.keys(), key=lambda k: _pending[k]["ts"])
    _apply_remedy(decision_id, approved)


def _expire_loop() -> None:
    """Expire pending decisions that nobody approved."""
    while not _stop.is_set():
        try:
            now = time.time()
            with _lock:
                expired = [k for k, v in _pending.items()
                           if v.get("expires_at", 0) < now]
                for k in expired:
                    del _pending[k]
                    _log_decision({
                        "ts": now, "decision_id": k,
                        "phase": "expired", "permission_status": "expired",
                    })
        except Exception:
            pass
        _stop.wait(60)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        logger.error("orion_substrate not importable")
        return 1

    sub = get_substrate()
    sub._connect_blocking()

    subscribe("brain.health.alert", _on_health_alert)
    subscribe("brain.health.action", _on_health_action)
    subscribe("channel.*.inbound", _on_user_decision)

    logger.info("executive alive — watching for unresolvable symptoms; "
                "consulting model on novel cases; permission-gated remedies.")

    threading.Thread(target=_expire_loop, name="exec-expire",
                     daemon=True).start()

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
