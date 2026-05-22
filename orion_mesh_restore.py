#!/usr/bin/env python3
"""orion_mesh_restore.py — the EXECUTION rung of the mesh recovery loop.

When a dropped device REJOINS the mesh, this restores its Orion presence:
resolve the device's transport (LAN at home, Tailscale away), SSH in, check
which Orion services are healthy, and restart the dead ones — checkpointing
every step on orion_taskspine so a flaky-network restore RESUMES instead of
restarting from scratch.

Two phases, split by risk (design law):
  health_check(device)  — READ-ONLY. SSH in, report which Orion services are
                          up/dead, MCP + gossip presence. Always safe, no gate.
  restore(device, ...,  allow_restart) — restart dead services over the task
                          spine. `allow_restart` is the GATE: the executive +
                          metacognition decide it (auto when confident, ask when
                          not). With allow_restart=False this only PROPOSES.

This module only EXECUTES. Deliberation + permission live in orion_executive;
confidence lives in orion_metacognition. (Design law #3: reuse the core.)

CLI:
    python orion_mesh_restore.py DEVICE             # read-only health check
    python orion_mesh_restore.py DEVICE --restart   # also restart dead services
"""

import json
import os
import subprocess
import sys
import time

SSH_OPTS = ["-o", "ConnectTimeout=12", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes"]


def _device(name):
    import orion_mesh
    for d in orion_mesh.load_devices():
        if d.get("name") == name:
            return d
    return None


def _resolve(name):
    import orion_mesh
    d = _device(name)
    return (d, orion_mesh.resolve(d)) if d else (None, None)


def _ssh(addr, user, cmd, key=None):
    """Run a remote command. Uses BatchMode (never prompts). Honors an optional
    key; otherwise relies on the host's ssh config / agent. Returns (rc, output)."""
    base = ["ssh"] + SSH_OPTS
    if key and os.path.exists(os.path.expanduser(key)):
        base += ["-i", os.path.expanduser(key)]
    target = ("%s@%s" % (user, addr)) if user else addr
    base += [target, cmd]
    try:
        r = subprocess.run(base, capture_output=True, text=True, timeout=35)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 255, "ssh exception: %s" % e


def _dead_orion_services(listing):
    """Parse a `launchctl list` (macOS) or `systemctl --user` (Linux) listing
    for Orion services that are NOT healthy. Returns unit/label names."""
    dead = []
    for line in listing.splitlines():
        s = line.strip()
        if not s:
            continue
        # systemctl marks failed/bad units with a leading status glyph — strip it
        # so the unit name (not the dot) is parsed.
        if s[0] in "●×*•x":
            s = s[1:].strip()
        p = s.split()
        if not p:
            continue
        if "com.orion." in s and len(p) >= 3:
            # macOS launchctl: col0=PID col1=last-exit col2=label.
            # Dead = no PID ("-"). (A nonzero exit on a running PID is just a
            # prior SIGTERM restart, not a current failure.)
            if p[0] == "-":
                dead.append(p[2])
        elif p[0].startswith("orion-") and (
                "failed" in s.lower() or "dead" in s.lower() or "inactive" in s.lower()):
            # Linux systemctl: "orion-X.service loaded failed failed ..."
            dead.append(p[0])
    return dead


def health_check(name, key=None):
    """READ-ONLY Orion-presence health for a device. Never restarts anything."""
    d, r = _resolve(name)
    if not d:
        return {"device": name, "reachable": False, "error": "not in device map"}
    if not r or not r.get("online"):
        return {"device": name, "reachable": False, "error": "device offline"}
    addr, user = r["address"], d.get("user", "")
    rc, out = _ssh(addr, user,
                   "launchctl list 2>/dev/null | grep com.orion. || "
                   "systemctl --user list-units 'orion-*' --no-legend 2>/dev/null",
                   key=key or d.get("ssh_key"))
    if rc == 255:
        return {"device": name, "reachable": False, "transport": r["transport"],
                "error": "ssh failed (no key/route from this host): %s" % out[:140].strip()}
    dead = _dead_orion_services(out)
    total = len([l for l in out.splitlines() if "orion" in l.lower()])
    return {"device": name, "reachable": True, "transport": r["transport"],
            "address": addr, "user": user, "orion_services_seen": total,
            "dead_services": dead, "healthy": (total > 0 and not dead)}


def restore(name, task_id=None, allow_restart=False, key=None):
    """Health-check, then (only if allow_restart) restart dead Orion services
    over the task spine. Returns an action report."""
    rep = health_check(name, key=key)
    _checkpoint(task_id, "health: " + json.dumps(rep)[:300])
    if not rep.get("reachable"):
        return {**rep, "action": "none (unreachable for restore)"}
    dead = rep.get("dead_services", [])
    if not dead:
        return {**rep, "action": "none (Orion presence healthy)"}
    if not allow_restart:
        # Gate closed: propose only. The executive/metacog decides whether to
        # re-call with allow_restart=True.
        return {**rep, "action": "proposed", "would_restart": dead}
    d = _device(name)
    addr, user = rep["address"], rep.get("user", "")
    results = []
    for svc in dead:
        unit = svc.replace("com.orion.", "orion-")
        cmd = ("launchctl kickstart -k gui/$(id -u)/%s 2>/dev/null || "
               "systemctl --user restart %s 2>/dev/null" % (svc, unit))
        rc, _o = _ssh(addr, user, cmd, key=key or (d or {}).get("ssh_key"))
        ok = rc == 0
        results.append({"service": svc, "restarted": ok})
        _checkpoint(task_id, "restart %s -> %s" % (svc, "ok" if ok else "FAILED"))
    return {**rep, "action": "restarted", "results": results}


def _checkpoint(task_id, content):
    if not task_id:
        return
    try:
        import orion_taskspine
        orion_taskspine._append(task_id, {
            "kind": "step", "idx": 0, "role": "mesh-restore", "content": content,
            "status": "done", "fuel": "mesh-restore",
            "hash": "r-%d" % (int(time.time() * 1000) % 1000000)})
    except Exception:
        pass


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    name = argv[0]
    allow = "--restart" in argv
    print(json.dumps(restore(name, allow_restart=allow), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
