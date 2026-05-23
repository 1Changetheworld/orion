"""orion_compiled_procedures.py — the zero-fuel fast-path store.

Build #5 of the next-3 roadmap (Terminal 1 / integration lane). Implements
C3 from docs/architecture/synthesis-continual-learning.md:

    "Recurring fixes become zero-fuel fast paths — the brain stops re-reasoning
     a problem it has already solved N times. Gradient-free training in the
     strict sense: experience (ledger) → consolidated unit (playbook) →
     compiled fast-path (procedure)."

WHAT THIS LAYER IS (and what it isn't)
======================================

This is the STORE — the bounded, audit-able home for compiled procedures.
It is NOT:
  - the COMPILER (orion_dream writes here when a playbook is stable + calibrated)
  - the EXECUTOR's gate (orion_executive's permission flow still owns risky tiers)

It is:
  - a typed schema for compiled procedures (ordered dispatch/publish steps +
    impact tier + calibration floor + provenance)
  - register / lookup / archive / restore (archive-not-delete, like skills)
  - deterministic execution with guards (no fuel call, no re-reasoning)
  - the volition memo's impact-tier check: impact ≤ 0.2 auto-runs; above
    that the caller MUST route through the executive's tier-gated permission
    flow before invoking execute()

THE SAFETY ENVELOPE (this is load-bearing)
==========================================

A compiled procedure that fires on the wrong situation is a runaway with no
fuel to second-guess it. Two guarantees keep the envelope tight:

1. IMPACT TIER GATING. impact is in [0.0, 1.0] (blast_radius × (1 −
   reversibility) per the volition memo). lookup_fast_path() returns the
   procedure body, but execute() refuses to run anything above
   IMPACT_AUTO_CEILING (default 0.2) — the caller MUST have routed it
   through executive permission first. The procedure is compiled; its
   permission is not.

2. CALIBRATION FLOOR. Each procedure carries a conf_floor — the minimum
   metacog governor confidence its symptom-class must currently meet for the
   procedure to fire. If the governor's ledger has soured on that shape, the
   compiled procedure is automatically held — the fast path inherits the
   slow path's learned caution. The dream sets conf_floor at registration
   time based on the playbook's CUSUM success rate.

Both guarantees are checked INSIDE this module, so no caller can bypass them
by simply invoking execute() directly.

ARCHIVE-NOT-DELETE
==================

A procedure that starts misfiring (the dream's CUSUM drops below the
demotion threshold) gets archived, not deleted — the dream's curator can
move it to procedures/archive/ and restore it later if eviction proved
premature. Same contract as the skill library (build #2).

STORAGE
=======
  ~/.orion/procedures/<symptom>.json        — active compiled procedures
  ~/.orion/procedures/archive/<symptom>.json — archived (reversible)
  ~/.orion/procedures/_history.jsonl        — append-only register/archive log

WIRE FORMAT (one procedure)
===========================
{
  "symptom_class": "SERVICE_LOOP_DISPATCH",
  "version": 1,
  "steps": [
    {"kind": "dispatch", "module": "orion_dispatch", "command": "restart_service",
     "args": {"service": "dispatch"}, "timeout_sec": 12},
    {"kind": "publish", "subject": "brain.executive.applied",
     "body": {"outcome": "succeeded", "via": "compiled_procedure"}},
  ],
  "impact": 0.15,
  "conf_floor": 0.70,
  "source_decision_ids": ["exec-..."],
  "compiled_at": 1779000000.0,
  "fires": 0,
  "successes": 0,
  "failures": 0,
  "active": true,
  "content_hash": "abcd1234ef56"
}
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("orion.procedures")

PROCEDURES_DIR = os.path.expanduser(
    os.environ.get("ORION_PROCEDURES_DIR", "~/.orion/procedures"))
ARCHIVE_DIR = os.path.join(PROCEDURES_DIR, "archive")
HISTORY_PATH = os.path.join(PROCEDURES_DIR, "_history.jsonl")
os.makedirs(PROCEDURES_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# Volition memo §3.2: the impact tier where auto-run stops. Above this,
# the caller must route through executive permission. 0.2 chosen because
# the design-law tier-2 ("reversible, single-host") sits at 0.0-0.2, and
# tier-3 ("multi-host or destructive") starts above.
IMPACT_AUTO_CEILING = float(os.environ.get("ORION_PROC_AUTO_IMPACT", "0.2"))

# Step kinds. Deliberately small — every new kind is a new attack surface;
# shell execution is forbidden here on purpose (the executive owns that).
ALLOWED_STEP_KINDS = ("dispatch", "publish")


def _proc_path(symptom: str, archived: bool = False) -> str:
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in symptom)
    return os.path.join(ARCHIVE_DIR if archived else PROCEDURES_DIR, safe + ".json")


def _content_hash(steps: list, impact: float, conf_floor: float) -> str:
    blob = json.dumps({"steps": steps, "impact": impact, "conf_floor": conf_floor},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _validate_steps(steps: list) -> Optional[str]:
    """Return None if valid, an error string otherwise. Cheap structural
    check; the EXECUTOR re-validates per step at runtime."""
    if not isinstance(steps, list) or not steps:
        return "steps must be a non-empty list"
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            return "step %d: not a dict" % i
        kind = s.get("kind")
        if kind not in ALLOWED_STEP_KINDS:
            return "step %d: kind %r not in %s" % (i, kind, ALLOWED_STEP_KINDS)
        if kind == "dispatch" and not s.get("command"):
            return "step %d: dispatch step missing 'command'" % i
        if kind == "publish" and not s.get("subject"):
            return "step %d: publish step missing 'subject'" % i
    return None


def _append_history(record: dict) -> None:
    try:
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass


def register_procedure(symptom_class: str, steps: list, impact: float,
                       conf_floor: float, source_decision_ids: list,
                       version: int = 1) -> dict:
    """Write a compiled procedure for a symptom class. Called by the dream
    when a playbook's CUSUM success rate + calibration both clear thresholds.
    Returns the persisted procedure dict (with content_hash) or {'error': ...}.

    NOT idempotent on identical content_hash — a re-register IS an update,
    captured in the _history.jsonl log for audit. The procedure file always
    reflects the latest version; archive_procedure() is how a stale one gets
    rolled back."""
    err = _validate_steps(steps)
    if err:
        return {"error": err}
    if not (0.0 <= impact <= 1.0):
        return {"error": "impact must be in [0, 1]"}
    if not (0.0 <= conf_floor <= 1.0):
        return {"error": "conf_floor must be in [0, 1]"}

    proc = {
        "symptom_class": symptom_class,
        "version": int(version),
        "steps": steps,
        "impact": float(impact),
        "conf_floor": float(conf_floor),
        "source_decision_ids": list(source_decision_ids or []),
        "compiled_at": time.time(),
        "fires": 0, "successes": 0, "failures": 0,
        "active": True,
        "content_hash": _content_hash(steps, impact, conf_floor),
    }
    path = _proc_path(symptom_class)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(proc, f, indent=2)
    except OSError as e:
        return {"error": "write failed: %s" % e}
    _append_history({"op": "register", "symptom_class": symptom_class,
                     "content_hash": proc["content_hash"], "ts": proc["compiled_at"]})
    return proc


def lookup_fast_path(symptom_class: str) -> Optional[dict]:
    """Return the active compiled procedure for this symptom, or None.
    Archived procedures are NEVER returned — they exist for provenance,
    not for firing. The caller still has to consult governor() against
    the procedure's conf_floor before executing."""
    path = _proc_path(symptom_class)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            proc = json.load(f)
        if not proc.get("active", True):
            return None
        return proc
    except (OSError, json.JSONDecodeError):
        return None


def _guards_pass(proc: dict, payload: Optional[dict] = None) -> tuple[bool, str]:
    """Runtime preconditions. The structural checks duplicated from
    _validate_steps are intentional belt-and-braces — a procedure file
    on disk could have been edited out-of-band since registration."""
    err = _validate_steps(proc.get("steps") or [])
    if err:
        return False, "invalid steps: %s" % err
    impact = float(proc.get("impact", 1.0))
    if impact > IMPACT_AUTO_CEILING:
        return False, ("impact %.2f exceeds auto ceiling %.2f — caller must "
                       "route through executive permission" % (impact, IMPACT_AUTO_CEILING))
    return True, "ok"


def execute(proc: dict, payload: Optional[dict] = None,
            governor_conf: Optional[float] = None) -> dict:
    """Run the compiled procedure deterministically. Refuses to run if:
      - guards fail (invalid steps or impact above auto ceiling)
      - governor_conf is below the procedure's conf_floor

    The caller is RESPONSIBLE for passing governor_conf — typically by
    calling orion_metacognition.governor() with the same symptom_class
    just before invoking execute(). This module does NOT consult metacog
    directly to keep the dependency tree clean and the unit-testable."""
    sym = proc.get("symptom_class", "?")
    ok, reason = _guards_pass(proc, payload)
    if not ok:
        return {"executed": False, "reason": reason, "symptom_class": sym}
    if governor_conf is not None:
        floor = float(proc.get("conf_floor", 0.0))
        if governor_conf < floor:
            return {"executed": False,
                    "reason": "governor conf %.2f below procedure floor %.2f"
                              % (governor_conf, floor),
                    "symptom_class": sym}

    results: list = []
    all_ok = True
    for i, step in enumerate(proc.get("steps") or []):
        rep = _run_step(step, payload or {})
        results.append(rep)
        if not rep.get("ok", False):
            all_ok = False
            break  # halt on first failure — partial procedures are dangerous

    _bump_counters(proc, success=all_ok)
    return {"executed": True, "symptom_class": sym, "all_ok": all_ok,
            "steps_run": len(results), "results": results}


def _run_step(step: dict, payload: dict) -> dict:
    kind = step.get("kind")
    try:
        if kind == "publish":
            try:
                from orion_substrate import publish
                publish(step["subject"], step.get("body") or {})
                return {"ok": True, "kind": "publish",
                        "subject": step["subject"]}
            except Exception as e:
                return {"ok": False, "kind": "publish", "error": str(e)}
        if kind == "dispatch":
            try:
                import orion_dispatch
                fn = getattr(orion_dispatch, "execute", None) \
                    or getattr(orion_dispatch, "run", None)
                if fn is None:
                    return {"ok": False, "kind": "dispatch",
                            "error": "orion_dispatch has no execute/run"}
                out = fn(step.get("command"), **(step.get("args") or {}))
                return {"ok": True, "kind": "dispatch",
                        "command": step.get("command"), "out": str(out)[:200]}
            except Exception as e:
                return {"ok": False, "kind": "dispatch", "error": str(e)}
        return {"ok": False, "kind": kind, "error": "unknown kind"}
    except Exception as e:
        return {"ok": False, "kind": kind, "error": str(e)}


def _bump_counters(proc: dict, success: bool) -> None:
    """Update the on-disk procedure's fires/successes/failures counters.
    Fire-and-forget; if the write fails the counter is wrong but the
    procedure's body is intact. The dream's CUSUM curator reads these."""
    sym = proc.get("symptom_class")
    if not sym:
        return
    path = _proc_path(sym)
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            cur = json.load(f)
        cur["fires"] = int(cur.get("fires", 0)) + 1
        if success:
            cur["successes"] = int(cur.get("successes", 0)) + 1
        else:
            cur["failures"] = int(cur.get("failures", 0)) + 1
        cur["last_fired"] = time.time()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2)
    except (OSError, json.JSONDecodeError):
        pass


def archive_procedure(symptom_class: str, reason: str = "") -> bool:
    """Move the active procedure to archive/. Reversible via restore_procedure.
    Called by the dream's curator when a procedure's CUSUM drops below the
    demotion threshold — same archive-not-delete contract as skills."""
    src = _proc_path(symptom_class)
    if not os.path.exists(src):
        return False
    try:
        with open(src, encoding="utf-8") as f:
            proc = json.load(f)
        proc["active"] = False
        proc["archived_at"] = time.time()
        if reason:
            proc["archived_reason"] = reason
        with open(_proc_path(symptom_class, archived=True), "w", encoding="utf-8") as f:
            json.dump(proc, f, indent=2)
        os.remove(src)
        _append_history({"op": "archive", "symptom_class": symptom_class,
                         "reason": reason, "ts": proc["archived_at"]})
        return True
    except (OSError, json.JSONDecodeError):
        return False


def restore_procedure(symptom_class: str) -> bool:
    """Reverse archive_procedure — bring it back as active."""
    src = _proc_path(symptom_class, archived=True)
    if not os.path.exists(src):
        return False
    try:
        with open(src, encoding="utf-8") as f:
            proc = json.load(f)
        proc["active"] = True
        proc.pop("archived_at", None)
        proc.pop("archived_reason", None)
        with open(_proc_path(symptom_class), "w", encoding="utf-8") as f:
            json.dump(proc, f, indent=2)
        os.remove(src)
        _append_history({"op": "restore", "symptom_class": symptom_class,
                         "ts": time.time()})
        return True
    except (OSError, json.JSONDecodeError):
        return False


def list_procedures(include_archived: bool = False) -> list:
    """Enumerate all compiled procedures on disk. Cheap (bounded by
    distinct symptom_class values), used by the dream's curator and any
    audit tooling."""
    out = []
    for d in [PROCEDURES_DIR] + ([ARCHIVE_DIR] if include_archived else []):
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not fname.endswith(".json") or fname.startswith("_"):
                continue
            try:
                with open(os.path.join(d, fname), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, json.JSONDecodeError):
                continue
    return out
