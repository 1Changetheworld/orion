"""orion_self_heal.py — cross-service reconciliation when cellular recovery fails.

The vitals primitive (orion_vitals.py) gives every Plexus service its
own homeostasis — recovery reflexes that fire on stuck states.
Sometimes those reflexes succeed (cell heals itself). Sometimes they
fail repeatedly. This daemon is the body's immune system: subscribes
to host.*.vitals, watches for services in chronic distress, runs
stronger reconciliation actions.

CELLULAR LAYER vs IMMUNE LAYER
==============================

  Cellular (per-service vitals)
    - 30-second pulse cadence
    - Self-knowledge of own state
    - Reflexes for known stuck states
    - Single-service scope
    - Fast (sub-minute response)

  Immune (this file — orion_self_heal)
    - Reads pulses from all services
    - Cross-service reasoning
    - Stronger actions: launchctl reload, process kill, env reset
    - Single-host scope (one self_heal per host)
    - Slower (minutes to hours)

Both run. Cellular handles the common case (substrate hiccups, transient
errors). Immune handles the cellular-failure case (service can't recover
itself; daemon down; permission revoked).

Honest collapse: pull this offline → individual cells keep adapting.
What disappears is the 'recover from un-recoverable states' capability.

DESIGN
======

For each known service, define:
  - distress_signal: predicate over the latest vitals snapshot
  - remedy: action to take (launchctl reload by default)

The daemon polls ~/.orion/vitals/ every CHECK_INTERVAL_SEC. When a
service's snapshot matches a distress_signal AND the service hasn't
been rescued in COOLDOWN_SEC, run the remedy and publish
brain.health.action on the substrate.

This is not magic. It's three folder reads + a launchctl call. The
discipline is in the LATENCIES (cellular fast, immune slow) and the
REASONING (when do you rescue vs let the service work it out itself).

KNOWN DISTRESS PATTERNS
=======================

  service has not pulsed in 5+ minutes
    → try launchctl reload of com.orion.{svc}
  service has high error_rate_per_min (>5)
    → log + escalate notification (don't auto-restart on errors;
      restart could cause cascade)
  dependency probe failed for >10 min
    → run a re-discovery (the service's cell-level reflex should
      already be retrying; we surface it as visible problem)

PUBLISHED EVENTS
================
  brain.health.alert  — distress signal detected
  brain.health.action — remedy attempted
  brain.health.recovered — vitals back to normal
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
from pathlib import Path

logger = logging.getLogger("orion.self_heal")

VITALS_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_VITALS_DIR", "~/.orion/vitals")
))
CHECK_INTERVAL_SEC = float(os.environ.get("ORION_SELFHEAL_INTERVAL", "60"))
COOLDOWN_SEC = float(os.environ.get("ORION_SELFHEAL_COOLDOWN", "600"))
SILENCE_THRESHOLD_SEC = float(os.environ.get("ORION_SELFHEAL_SILENCE", "300"))
ERROR_RATE_THRESHOLD = float(os.environ.get("ORION_SELFHEAL_ERROR_RATE", "5"))

# Map known service names to their launchd Label so we can launchctl them
LAUNCHD_LABELS = {
    "claustrum": "com.orion.claustrum",
    "dmn": "com.orion.dmn",
    "lastcontact": "com.orion.lastcontact",
    "fuel_switch": "com.orion.fuel-switch",
}


_last_action_ts: dict[str, float] = {}
_stop = threading.Event()


def _load_snapshot(svc: str) -> dict | None:
    p = VITALS_DIR / f"{svc}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _service_silent(snap: dict) -> bool:
    """Cell-level silence: vitals haven't been pulsed in too long."""
    age = snap.get("last_event_age_sec") or 0
    uptime = snap.get("uptime_sec") or 0
    return uptime > 60 and age > SILENCE_THRESHOLD_SEC


def _service_unhealthy(snap: dict) -> bool:
    return snap.get("error_rate_per_min", 0) >= ERROR_RATE_THRESHOLD


def _try_remedy(svc: str, kind: str) -> bool:
    """Run the remedy. Currently: launchctl unload + load."""
    label = LAUNCHD_LABELS.get(svc)
    if not label:
        logger.info("no launchd label known for %s — skipping remedy", svc)
        return False
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not plist.exists():
        logger.info("no plist at %s — skipping remedy", plist)
        return False
    try:
        subprocess.run(["launchctl", "unload", str(plist)],
                       capture_output=True, timeout=10)
        subprocess.run(["launchctl", "load", "-w", str(plist)],
                       capture_output=True, timeout=10)
        logger.info("remedy applied: launchctl reload %s (kind=%s)", label, kind)
        return True
    except Exception as e:
        logger.warning("remedy failed for %s: %s", label, e)
        return False


def _publish(subject: str, payload: dict) -> None:
    try:
        from orion_substrate import publish as _p
        _p(subject, payload)
    except Exception:
        pass


def _check_loop() -> None:
    while not _stop.is_set():
        try:
            now = time.time()
            for svc in LAUNCHD_LABELS.keys():
                snap = _load_snapshot(svc)
                if not snap:
                    continue

                # cooldown check
                last = _last_action_ts.get(svc, 0.0)
                if (now - last) < COOLDOWN_SEC:
                    continue

                if _service_silent(snap):
                    _publish("brain.health.alert", {
                        "service": svc, "kind": "silent",
                        "vitals": snap, "ts": now,
                    })
                    if _try_remedy(svc, kind="silent"):
                        _last_action_ts[svc] = now
                        _publish("brain.health.action", {
                            "service": svc, "remedy": "launchctl reload",
                            "reason": "no vitals pulse", "ts": now,
                        })
                elif _service_unhealthy(snap):
                    _publish("brain.health.alert", {
                        "service": svc, "kind": "high_error_rate",
                        "vitals": snap, "ts": now,
                    })
                    # don't auto-remedy on errors — could cascade.
                    # Just surface the alert; user / DMN can act.
        except Exception as e:
            logger.warning("check loop error: %s", e)
        _stop.wait(CHECK_INTERVAL_SEC)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("self_heal alive — watching %s every %ds",
                VITALS_DIR, CHECK_INTERVAL_SEC)

    threading.Thread(target=_check_loop, name="self-heal", daemon=True).start()

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
