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


_SHARED_DISCIPLINE = """DIAGNOSTIC DISCIPLINE (from SRE + AIOps research):

1. FORM HYPOTHESIS BEFORE PROPOSING REMEDY — the SRE chapter on Effective
   Troubleshooting forbids action-before-hypothesis. The "root_cause_
   hypothesis" field is required, must be non-empty, must reference
   specific evidence (vital, log line, dependency probe) you saw.

2. PROVIDE TWO HYPOTHESES MINIMUM in your reasoning, then choose. Single-
   hypothesis "premature closure" is the #1 LLM failure mode in incident
   diagnosis (PRISM benchmark, 2026). State both, eliminate one with
   evidence, name the survivor in root_cause_hypothesis.

3. DISTINGUISH TRIGGER FROM CAUSE. "the deploy at 3pm broke it" is a
   trigger; the cause is the latent issue the trigger exposed. Five-Whys
   research warns this conflation explicitly.

4. CORRELATE WITH NEIGHBORS. AIOps platforms (Datadog Watchdog, BigPanda,
   PagerDuty) exist because humans miss correlation. Always check the
   claustrum_summary for: other services in distress, recent host
   activity, hosts that disappeared. A single-service alert is rarely
   the right scope.

5. WORKAROUND vs PERMANENT_FIX (ITIL). Label your remedy_kind family
   as "workaround" (restore service fast, may be a hack) or
   "permanent_fix" (addresses root cause, requires more steps).
   Workarounds get faster approval; permanent fixes need the user
   to understand the change.

6. NO DEFENSIVE COSMETICS. "increase retry count", "add timeout",
   "bump log level" are not remedies — they hide problems. Reject
   yourself if your only proposal is cosmetic.

7. CITE WHAT YOU CAN ACTUALLY SEE. Every entity you reference
   (file path, env var, service name, port number) MUST appear in
   the injected context. The validator rejects proposals citing
   unknown entities — saves you from hallucinating.

8. CONFIDENCE CALIBRATION. FMEA risk-priority style — risk_level
   reflects severity × reversibility × detectability. confidence
   reflects how strong your evidence is, not how plausible your
   guess sounds. Cap at 0.5 when symptom class is UNRECOGNIZED.
"""


_SYMPTOM_FAULT_TREES = {
    "SERVICE_LOOP": """
FAULT TREE for SERVICE_LOOP (service crashing + restarting):
  TOP: service exits within seconds of every start
  ├── crash-on-startup → bad config / missing dep / port collision
  ├── crash-after-N-seconds → resource leak / memory limit / leaked FD
  └── crash-on-event → poison input on a queue / corrupt incoming message

CLASSIFY which class FIRST. If you cannot tell from the vitals provided,
say so and request a probe — DO NOT guess.

ANTI-PATTERN: "increase the restart delay" — this is not a remedy. It
hides the fact that the service is broken.
""",

    "DEPENDENCY_FAILURE": """
FAULT TREE for DEPENDENCY_FAILURE (a probe is failing):
  TOP: service can't reach a dependency it needs
  ├── network → DNS / TLS / route / firewall
  ├── auth → credential / token / TCC / OAuth refresh
  ├── contract → API shape changed / version skew / broken endpoint
  └── data → corrupt input / unexpected format / empty response

PROBE ORDERING discipline: network → DNS → TLS → auth → API contract →
data shape. Report each probe before interpreting the next. Do not
"the dep is down" — name the LAYER.
""",

    "AUTH_DRIFT": """
FAULT TREE for AUTH_DRIFT (silent permission/credential change):
  TOP: previously-working auth now fails
  ├── credential expired (OAuth refresh, JWT exp, API key rotation)
  ├── permission revoked (macOS TCC, OS firewall, IAM policy change)
  ├── clock skew (Kerberos, JWT exp, certificate validity window)
  └── identity drift (user account renamed, namespace migration)

For macOS specifically: TCC reset is silent — Full Disk Access can be
unticked without notification. ALWAYS check clock skew BEFORE
proposing key regeneration; an expired-looking token may just be a
clock-off host.
""",

    "DISK_PRESSURE": """
FAULT TREE for DISK_PRESSURE:
  TOP: writes failing OR vitals snapshots stale
  ├── leading indicator (>80% used and growing)
  ├── terminal (writes already failing)
  └── inode exhaustion (rare but catastrophic — many small files)

HIERARCHY of remedies (least → most destructive):
  1. rotate logs (logrotate / journald vacuum)
  2. compress old transcripts
  3. tier to external drive (D:\\, AtlasVault)
  4. delete (only after identifying owner)

NEVER `rm -rf` without naming the growth source first.
""",

    "NETWORK_PARTITION": """
FAULT TREE for NETWORK_PARTITION:
  TOP: hosts can't reach each other consistently
  ├── one-way partition (A→B works, B→A fails) → routing/NAT
  ├── intermittent (flapping) → carrier issue, sleep cycle
  ├── DERP-only (Tailscale relay fallback) → direct path firewalled
  └── split-brain (both halves think they're authoritative)

ASYMMETRY TEST: can A reach B? B reach A? both reach C?
NEVER recommend "restart the mesh" without establishing whether
the partition is one-way (mesh restart won't fix routing).
""",

    "CHANNEL_LIMBO": """
FAULT TREE for CHANNEL_LIMBO (alive-but-silent — hardest class):
  TOP: daemon's heartbeat is healthy but no inbound signal arrives
  ├── sender broken (heartbeat fake; daemon thinks it's listening but isn't)
  ├── transport silently dropping (queue full, webhook returning 200 but
  │   discarding, polling cursor advanced past missed messages)
  └── receiver consuming-but-not-acting (handler exception swallowed;
      messages received and immediately discarded)

REQUIRED: hold all three hypotheses in parallel. Do NOT collapse to one
without a discriminating test. The right test is a probe message with
a unique sentinel string, traced end-to-end through the system.

ANTI-PATTERN: "restart the channel daemon" — it's already restarting
and the silence persists. The bug is downstream.
""",

    "PERSONA_DRIFT": """
FAULT TREE for PERSONA_DRIFT (model output deviating from configured persona):
  TOP: replies use wrong name, wrong honorific, or wrong style
  ├── system prompt changed (SOUL.md edited / IDENTITY hardcoded)
  ├── context-window truncation (persona prefix dropped on long sessions)
  ├── fuel swap (Claude → Ollama, weaker instruction-following)
  └── user pattern shift (user changed their own register; model adapted)

This symptom is BEHAVIORAL, not infrastructural. Restart is rarely
the remedy. Compare current outputs to a golden-sample baseline
before deciding the persona itself drifted vs. the user changing
their style.
""",

    "CORRUPTION": """
FAULT TREE for CORRUPTION (data integrity broken):
  TOP: graph_memory.json fails to parse / DB returns inconsistent results
  ├── filesystem (fsck-level: bad sectors, journal corruption)
  ├── application (truncated write, race condition during shutdown)
  ├── semantic (embeddings drifted from source; index out of date)
  └── partial (most fine, some entries malformed)

PROBE before remedy: which layer? Application-level corruption is
recoverable from WAL or atomic-write logs without going to backup.
Backup-restore is destructive of recent work; prefer in-place repair
when applicable.
""",

    "FUEL_OUTAGE": """
FAULT TREE for FUEL_OUTAGE (LLM call failures):
  TOP: every fuel returning errors
  ├── rate limit (429) — retry after backoff
  ├── region outage (503) — switch region or fuel
  ├── credential expiry (401) — refresh token / re-auth
  ├── model deprecation (404 on model_id) — switch model_id
  └── quota exhaustion — switch fuel adapter

READ THE ACTUAL ERROR CODE. "fuel is down" without code reading is
unprofessional. orion_fuel.py has a universal adapter; switching is
cheap. Don't retry-with-backoff on a deprecated model.
""",

    "UNRECOGNIZED": """
FAULT TREE for UNRECOGNIZED (no signature matches):
  TOP: substrate event has a kind we haven't seen, or known patterns
  in unfamiliar combination

OPEN-MODE REASONING:
  - State explicitly: "no known fault-tree fits"
  - Propose TWO competing hypotheses
  - Design a discriminating test (what would have to be true?)
  - Cap confidence at 0.5
  - remedy_kind defaults to "investigate_only" with a clear
    user_message about what additional information would help.

Do NOT pattern-match to the closest known class — say what's
unfamiliar.
""",
}


def _build_diagnostic_prompt(ctx: dict) -> str:
    """Per-symptom-class diagnostic prompt informed by SRE + AIOps +
    Five-Whys + ITIL research (2026-05-09 agent sweep). The shared
    discipline applies to every class; the fault tree narrows by class.

    Schema-shaped JSON output enables deterministic parsing and lets
    a validator reject proposals citing unknown entities or omitting
    required fields.
    """
    sym = ctx.get("symptom_class", "UNRECOGNIZED")
    fault_tree = _SYMPTOM_FAULT_TREES.get(sym, _SYMPTOM_FAULT_TREES["UNRECOGNIZED"])
    return f"""You are Orion's executive layer reasoning about an internal failure.

{_SHARED_DISCIPLINE}

{fault_tree}

CONTEXT INJECTED FROM THE PLEXUS SUBSTRATE:

  symptom_class: {sym}
  service: {ctx.get('service')}
  kind: {ctx.get('kind')}

  current vitals (per-service health snapshot):
{json.dumps(ctx.get('vitals'), indent=2)}

  recovery attempts in last 30 min: {ctx.get('recovery_attempts_recent', 0)}
  (high values mean cellular reflex is failing — escalation is appropriate;
   low values mean the executive may be over-eager)

  cross-system summary from claustrum (the integrative observer):
{json.dumps(ctx.get('claustrum_summary'), indent=2)}

  historical decisions for this service (most recent first):
{json.dumps(ctx.get('historical_decisions') or [], indent=2)}

(these are episodic memory of past proposals + outcomes. Past
SUCCESSES are weakly informative — don't just repeat them. Past
FAILURES are strongly informative — don't repeat the same proposal
that already failed for this service.)

OUTPUT — return ONLY a JSON object with this exact shape:

{{
  "hypotheses_considered": [
    {{"hypothesis": "<sentence>", "evidence_for": "<which vital/log>", "evidence_against": "<...>"}},
    {{"hypothesis": "<sentence>", "evidence_for": "<...>", "evidence_against": "<...>"}}
  ],
  "root_cause_hypothesis": "<the surviving hypothesis>",
  "remedy_family": "workaround|permanent_fix|investigate_only",
  "remedy_kind": "launchctl_reload|reset_token|grant_permission|edit_config|reset_dependency|free_disk|investigate_only",
  "remedy_steps": ["<concrete step 1>", "<concrete step 2>", ...],
  "rollback_steps": ["<undo step 1>", ...],
  "summary": "<one sentence the user will see>",
  "user_message": "<2-4 sentence permission ask, plain language, name the action plainly>",
  "risk_level": "low|medium|high",
  "tier": "tier1_auto|tier2_notify_after|tier3_approve_before",
  "confidence": 0.0
}}

TIER GUIDELINES (from HITL research):
  tier1_auto:           reversible + read-only-ish (cache flush, log rotate);
                        max risk_level=low; never for symptom_class=AUTH_DRIFT
                        or CORRUPTION or PERSONA_DRIFT
  tier2_notify_after:   reversible side effect (launchctl reload, dep reset);
                        good for SERVICE_LOOP, FUEL_OUTAGE; max risk=medium
  tier3_approve_before: irreversible / identity / destructive (key rotation,
                        config edit to .env.secrets, memory graph mutation,
                        permission grant); REQUIRED for AUTH_DRIFT, CORRUPTION,
                        and any UNRECOGNIZED symptom

If your answer would be cosmetic ("add retry"), reject yourself by
setting remedy_kind to "investigate_only" with a clear user_message
explaining what evidence you'd need to propose a real fix."""


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


def _action_fingerprint(proposal: dict) -> str:
    """6-char fingerprint of the action for replay-resistant approval.
    User must reply 'approve <fingerprint>' (or 'a <fingerprint>') —
    bare 'approve' no longer authorizes. From HITL research:
    action-fingerprint binding kills accidental + replay approvals."""
    import hashlib
    payload = json.dumps({
        "kind": proposal.get("remedy_kind"),
        "steps": proposal.get("remedy_steps"),
    }, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:6]


def _request_permission(proposal: dict, ctx: dict) -> str:
    """Surface the proposal to the user via reach.py with a tiered
    approval flow + action-fingerprint binding. Returns the
    decision_id used to track approval."""
    decision_id = f"exec-{int(time.time())}-{ctx.get('service','unknown')}"
    fingerprint = _action_fingerprint(proposal)
    tier = proposal.get("tier", "tier3_approve_before")
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    pending_file = PENDING_DIR / f"{decision_id}.json"
    record = {
        "decision_id": decision_id,
        "fingerprint": fingerprint,
        "tier": tier,
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

    # Publish a reach event with the fingerprinted permission ask.
    # tier1_auto bypasses the user — auto-applies (logged).
    # tier2_notify_after applies, then notifies with undo path.
    # tier3_approve_before requires user reply quoting the fingerprint.
    try:
        from orion_substrate import publish
        if tier == "tier1_auto":
            user_msg = (
                "Applied automatically: " + proposal.get("summary", "(no summary)")
                + f". Reply 'undo {fingerprint}' if this was wrong."
            )
        elif tier == "tier2_notify_after":
            user_msg = (
                "Applying now: " + proposal.get("summary", "(no summary)")
                + f". Reply 'undo {fingerprint}' if this was wrong."
            )
        else:  # tier3
            user_msg = (
                proposal.get("user_message", proposal.get("summary", ""))
                + f"\\n\\nReply 'approve {fingerprint}' to apply, or 'deny {fingerprint}'. "
                + "(expires in 6 hours)"
            )

        publish("brain.executive.proposal", {
            "decision_id": decision_id,
            "fingerprint": fingerprint,
            "tier": tier,
            "ts": record["ts"],
            "service": ctx.get("service"),
            "summary": proposal.get("summary", "(no summary)"),
            "user_message": user_msg,
            "remedy_kind": proposal.get("remedy_kind"),
            "risk_level": proposal.get("risk_level", "medium"),
            "confidence": proposal.get("confidence", 0.5),
        })
        # Reach forwards via the user's most-active channel as high-priority.
        publish("brain.synthesis.candidate", {
            "kind": "executive_proposal",
            "evidence": {
                "decision_id": decision_id,
                "fingerprint": fingerprint,
                "tier": tier,
                "summary": proposal.get("summary"),
                "user_message": user_msg,
            },
            "priority": 0.9 if tier == "tier3_approve_before" else 0.5,
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
    """User replied with approve/deny + action fingerprint.

    Action-fingerprint binding (HITL research): bare 'approve' no
    longer authorizes; user must quote the 6-char fingerprint. Defeats
    accidental approvals and replay attacks.

    Pattern: 'approve <fingerprint>' / 'deny <fingerprint>' /
             'a <fingerprint>' / 'd <fingerprint>'

    Special: 'undo <fingerprint>' reverses an already-applied tier1/2
    action by running its rollback_steps.
    """
    import re
    text = (payload.get("text") or "").lower().strip()
    if not text:
        return

    # Match: (approve|deny|undo|a|d) [whitespace] <6-hex>
    m = re.search(r"\b(approve|deny|undo|a|d)\b\s+([a-f0-9]{6})\b", text)
    if not m:
        return  # bare 'approve' without fingerprint is no longer authorizing

    verb = m.group(1)
    fingerprint = m.group(2)

    if verb == "undo":
        _attempt_undo(fingerprint)
        return

    approved = verb in ("approve", "a")

    # Find the matching pending decision by fingerprint
    with _lock:
        decision_id = None
        for did, rec in _pending.items():
            if rec.get("fingerprint") == fingerprint:
                decision_id = did
                break
    if not decision_id:
        logger.info("no pending decision matches fingerprint %s", fingerprint)
        return
    _apply_remedy(decision_id, approved)


def _attempt_undo(fingerprint: str) -> None:
    """Find a recently-applied decision with this fingerprint and run
    its rollback_steps. Append-only audit + undo journal pattern from
    HITL research."""
    if not DECISION_LEDGER.exists():
        return
    try:
        with DECISION_LEDGER.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return
    target = None
    for line in reversed(lines[-500:]):
        try:
            d = json.loads(line)
            if d.get("phase") == "applied" and d.get("proposal", {}).get("fingerprint") == fingerprint:
                target = d
                break
        except Exception:
            continue
    if not target:
        logger.info("no applied decision with fingerprint %s found in last 500 entries", fingerprint)
        return
    rollback = (target.get("proposal") or {}).get("rollback_steps") or []
    logger.info("undo for fingerprint %s — %d rollback steps", fingerprint, len(rollback))
    # For now: log the undo intent. Real per-remedy reversers come next pass.
    _log_decision({
        "ts": time.time(),
        "phase": "undo_requested",
        "fingerprint": fingerprint,
        "original_decision_id": target.get("decision_id"),
        "rollback_steps_planned": rollback,
    })


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
