#!/usr/bin/env python3
"""orion_fuel_steward.py — Orion's fuel self-heal reflex (the "fuel steward").

Closes the "silent 401 for two weeks" gap. Watches fuel health; when the PRIMARY
fuel (the strong CLI) is failing, it:
  1. attempts SAFE, non-credential recovery (re-scan engines, re-probe the cascade),
  2. confirms whether a backup is carrying Orion (so he is never mute),
  3. classifies the situation, and
  4. ALERTS James exactly ONCE per failure episode (rate-limited + de-duplicated)
     with the precise diagnosis + the single human step — re-auth — that a mind
     without his password cannot perform itself.

It NEVER stores or handles credentials (no-secrets rule; `claude login` is
interactive OAuth). This is Axis-B operational autonomy: keep the rented fuel
flowing and hand off the one step that genuinely needs a human — not a step
toward needing the model less (that is Axis A, native cognition).

Modes:  --once (assess + act one time)  ·  default (daemon loop)  ·  --status
         --simulate-down / --simulate-degraded (dry-run the alert path, no send)
"""
import sys, os, json, time, argparse

sys.path.insert(0, os.path.expanduser("~/orion-code"))

STATE = os.path.expanduser("~/.orion/state")
STATE_FILE = os.path.join(STATE, "fuel_steward_state.json")
HEALTH_LOG = os.path.join(STATE, "fuel_health.jsonl")

PROBE = os.environ.get("ORION_STEWARD_PROBE", "Reply with only: OK")
INTERVAL = int(os.environ.get("ORION_STEWARD_INTERVAL", "1800"))        # daemon loop, 30 min
MIN_REALERT_SEC = int(os.environ.get("ORION_STEWARD_REALERT", "21600")) # re-alert same fault at most / 6h
STALE_PROBE_SEC = int(os.environ.get("ORION_STEWARD_STALE", "3600"))    # heartbeat probe / 1h even when quiet


def _publish(subject, payload):
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"status": "unknown", "sig": "", "last_alert_ts": 0.0, "last_probe_ts": 0.0}


def _save_state(s):
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except Exception:
        pass


def _recent_degraded(since_ts):
    """Cheap signal: did the failover reflex log any fuel_degraded events lately?
    (The reflex in orion_fuel.get_fuel writes these when it falls off the primary.)"""
    try:
        n = 0
        with open(HEALTH_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("event") == "fuel_degraded" and r.get("ts", 0) >= since_ts \
                        and r.get("interface") != "fuel-steward":   # ignore our own probes
                    n += 1
        return n
    except Exception:
        return 0


def assess():
    """One cheap probe through the real cascade. If the answer comes from the
    PRIMARY, fuel is healthy; if from a backup, the primary failed but Orion is
    carried; if from nothing, fuel is down."""
    import orion_fuel as F
    F.fuel.scan()                                   # safe recovery: re-detect engines
    primary = F.fuel.available[0].name if F.fuel.available else None
    resp, engine = F.get_fuel(PROBE, interface="fuel-steward")
    cascade_ok = bool(resp) and engine and engine != "none" and not F._is_error_response(resp)
    primary_ok = bool(cascade_ok and engine == primary)
    return {"primary": primary, "engine": engine,
            "cascade_ok": cascade_ok, "primary_ok": primary_ok}


def classify(a):
    if a["primary_ok"]:
        return "HEALTHY"
    if a["cascade_ok"]:
        return "DEGRADED_FUNCTIONAL"     # primary down, a backup is carrying Orion
    return "DOWN"                         # no fuel answered


def _recovery_command(primary):
    p = (primary or "the primary fuel").lower()
    if "claude" in p:
        return ("re-authenticate the Claude CLI on COMMAND: open a Terminal and run "
                "`claude` to complete login (or re-log into your Claude subscription).")
    if "codex" in p:
        return "re-authenticate the Codex CLI on COMMAND (run `codex` and log in)."
    if "gemini" in p:
        return "re-authenticate the Gemini CLI on COMMAND (run `gemini` and log in)."
    return "re-authenticate %s on COMMAND." % primary


def _alert_text(status, a):
    fix = _recovery_command(a["primary"])
    if status == "DEGRADED_FUNCTIONAL":
        return ("Sir — fuel note: my primary fuel (%s) is failing to authenticate. "
                "I'm still thinking — running on backup (%s) — so nothing is broken. "
                "To restore full power, %s"
                % (a["primary"], a["engine"], fix))
    return ("Sir — URGENT: all my fuel sources are failing (primary %s; no backup "
            "answered). I can't reason until fuel is restored. To fix, %s "
            "Details in ~/.orion/fuel_steward.err."
            % (a["primary"], fix))


def _emit(status, a, do_send=True):
    """Rate-limited + de-duplicated alert. One message per failure EPISODE; a
    'recovered' note when it clears. Respects 'notify all errors' without spam."""
    st = _load_state()
    now = time.time()
    sig = "%s:%s" % (status, a["primary"])
    changed = sig != st.get("sig")
    stale = (now - st.get("last_alert_ts", 0)) > MIN_REALERT_SEC

    action = None
    if status in ("DEGRADED_FUNCTIONAL", "DOWN"):
        if changed or stale:
            action = ("alert", _alert_text(status, a))
    elif status == "HEALTHY" and st.get("status") in ("DEGRADED_FUNCTIONAL", "DOWN"):
        action = ("recovered", "Sir — fuel restored: %s is answering again. Back to full power." % a["primary"])

    if action:
        kind, text = action
        rec = {"ts": now, "event": "fuel_steward_%s" % kind, "status": status,
               "primary": a["primary"], "engine": a["engine"], "text": text}
        try:
            os.makedirs(STATE, exist_ok=True)
            with open(HEALTH_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass
        _publish("brain.fuel.steward", rec)
        if do_send:
            _publish("channel.imessage.outbound", {"text": text, "channel": "imessage"})
            st["last_alert_ts"] = now
        print("  ALERT[%s]: %s" % (kind, text))
    else:
        print("  (no alert — status=%s, unchanged & within re-alert window)" % status)

    st["status"] = status
    st["sig"] = sig
    st["last_probe_ts"] = now
    _save_state(st)


def run_once(force_probe=False, dry=False):
    st = _load_state()
    now = time.time()
    # Event-driven + slow heartbeat: probe if there's a reason to, else stay quiet.
    reason = None
    if force_probe:
        reason = "forced"
    elif st.get("status") not in ("HEALTHY", "unknown"):
        reason = "prior status not healthy"
    elif _recent_degraded(st.get("last_probe_ts", 0)):
        reason = "reflex logged fuel_degraded since last check"
    elif (now - st.get("last_probe_ts", 0)) > STALE_PROBE_SEC:
        reason = "heartbeat"
    if not reason:
        print("fuel-steward: quiet (healthy, no degradation signal).")
        return "HEALTHY"
    print("fuel-steward: probing (%s)..." % reason)
    a = assess()
    status = classify(a)
    print("  primary=%s engine=%s cascade_ok=%s primary_ok=%s -> %s"
          % (a["primary"], a["engine"], a["cascade_ok"], a["primary_ok"], status))
    _emit(status, a, do_send=not dry)
    return status


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--simulate-down", action="store_true")
    ap.add_argument("--simulate-degraded", action="store_true")
    args = ap.parse_args(argv)

    if args.status:
        print(json.dumps(_load_state(), indent=2)); return 0
    if args.simulate_down or args.simulate_degraded:
        a = {"primary": "claude-cli", "engine": "none" if args.simulate_down else "codex-cli",
             "cascade_ok": not args.simulate_down, "primary_ok": False}
        status = classify(a)
        print("SIMULATE %s -> %s (DRY, no send):" % ("DOWN" if args.simulate_down else "DEGRADED", status))
        _emit(status, a, do_send=False)
        return 0
    if args.once:
        run_once(force_probe=True); return 0

    print("orion-fuel-steward alive — watching fuel health every %ss" % INTERVAL)
    while True:
        try:
            run_once()
        except Exception as e:
            print("fuel-steward run error: %s" % e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
