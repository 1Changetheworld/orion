#!/usr/bin/env python3
"""orion_mesh_recovery.py — the autonomic recovery loop for the device mesh.

Closes the loop the mesh monitor opens. When a device drops, Orion doesn't just
text — it opens a DURABLE recovery task, confirms the outage (re-probe, so a
single missed beat isn't a false alarm), and hands the EXECUTIVE a tailored
symptom so any actual fix is deliberated and permission-gated. On the device's
return it closes the task and asks the executive to make the device WHOLE again
(verify its Orion services / MCP / gossip and restore what's missing). The
decision ledger that comes out the other side is what `dream` consolidates into
a recovery playbook — so the mesh teaches itself how its own devices heal.

The full cycle, end to end:
  observe   orion_mesh.monitor      -> brain.mesh.device_offline / device_online
  track     this module             -> durable task on orion_taskspine
  decide    orion_executive         -> brain.health.alert -> proposal + gating
  act       executive / task spine  -> permission-gated remedy
  learn     orion_dream             -> recovery playbook from decisions.jsonl

Design note (why triage matters): you cannot "restart" a powered-off host
remotely, so blindly proposing a restart is noise. We CONFIRM first, and the
real recoverable moment is the RETURN — when a device rejoins, restoring its
Orion presence is both possible and the thing that keeps the mesh unified.

This module never texts the user directly — the mesh monitor owns user-facing
offline/online alerts; the executive owns proposal/approval comms. This module
is pure autonomic plumbing.

Subjects in:  brain.mesh.device_offline / brain.mesh.device_online
Subjects out: brain.health.alert (to the executive)
"""

import json
import os
import sys
import time

ORION_HOME = os.environ.get("ORION_BRAIN_DIR") or os.path.expanduser("~/.orion")
STATE_PATH = os.path.join(ORION_HOME, "mesh", "recovery_state.json")


def _load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(s):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except Exception:
        pass


def _publish(subject, payload):
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass


def _confirm_offline(device):
    """Re-probe the device. Returns (still_offline, resolve_result). A single
    missed probe is a flap, not an outage — we don't act until re-confirmed."""
    try:
        import orion_mesh
        for d in orion_mesh.load_devices():
            if d.get("name") == device:
                r = orion_mesh.resolve(d)
                return (not r["online"]), r
    except Exception:
        pass
    return True, None


def _open_task(goal):
    try:
        import orion_taskspine
        return orion_taskspine.create_task(goal)
    except Exception:
        return None


def _task_note(task_id, content, status="done"):
    if not task_id:
        return
    try:
        import orion_taskspine
        orion_taskspine._append(task_id, {
            "kind": "step", "idx": 0, "role": "mesh-recovery",
            "content": content, "status": status, "fuel": "mesh-recovery",
            "hash": "note-%d" % (int(time.time() * 1000) % 1000000)})
    except Exception:
        pass


def _close_task(task_id, status="complete"):
    if not task_id:
        return
    try:
        import orion_taskspine
        orion_taskspine._append(task_id, {"kind": "task", "id": task_id, "status": status})
    except Exception:
        pass


def _on_offline(subject, payload):
    device = payload.get("device")
    if not device:
        return
    state = _load_state()
    if device in state:
        return  # already tracking this outage
    still_down, r = _confirm_offline(device)
    if not still_down:
        return  # flap — recovered on re-probe; no task, no symptom
    task_id = _open_task(
        "Mesh recovery for %s: confirmed offline (last transport %s). Watch for "
        "return, then restore its Orion presence and learn the pattern."
        % (device, payload.get("last_transport")))
    _task_note(task_id, "%s confirmed unreachable on LAN + Tailscale at %s."
               % (device, time.strftime("%Y-%m-%d %H:%M")), status="open")
    state[device] = {"task_id": task_id, "offline_since": time.time(),
                     "last_transport": payload.get("last_transport")}
    _save_state(state)
    # Hand the executive the symptom. An unreachable host is investigate-only
    # (nothing to safely auto-do) — the executive deliberates + logs, gated.
    _publish("brain.health.alert", {
        "symptom_class": "NETWORK_PARTITION",
        "host": device, "source": "mesh",
        "detail": ("%s is unreachable on both LAN and Tailscale (mesh monitor). "
                   "If powered off it is not remotely recoverable; recovery task "
                   "open, watching for its return to auto-restore Orion presence."
                   % device),
        "ts": time.time(),
    })


def _on_online(subject, payload):
    device = payload.get("device")
    state = _load_state()
    if device not in state:
        return  # we weren't tracking an outage for this one
    info = state.pop(device)
    _save_state(state)
    transport = payload.get("transport")
    down_for = int(time.time() - info.get("offline_since", time.time()))
    task_id = info.get("task_id")
    _task_note(task_id, "%s returned via %s after %ds offline." % (device, transport, down_for))
    _close_task(task_id, "complete")
    # The recoverable moment: ask the executive to make the returned device whole
    # again — verify its Orion services / MCP / gossip and restore what's missing.
    # Permission-gated; the executive owns the proposal + approval + ledger.
    _publish("brain.health.alert", {
        "symptom_class": "NETWORK_PARTITION",
        "host": device, "source": "mesh-return",
        "detail": ("%s rejoined the mesh via %s after %ds offline. Verify its Orion "
                   "presence is healthy (services up, MCP connected, gossip rejoined) "
                   "and restore anything missing." % (device, transport, down_for)),
        "ts": time.time(),
    })


def main():
    try:
        from orion_substrate import subscribe
    except Exception as e:
        print("substrate unavailable: %s — mesh recovery cannot run" % e)
        return 1
    print("orion-mesh-recovery alive — observe -> track -> decide -> act -> learn")
    subscribe("brain.mesh.device_offline", _on_offline)
    subscribe("brain.mesh.device_online", _on_online)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
