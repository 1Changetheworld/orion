#!/usr/bin/env python3
"""orion_mesh.py — location-aware device mesh ("mesh mode").

Monitor Orion's devices the SAME whether you're home or traveling. At home the
mesh runs over the LAN (10.0.0.x) — fast and local. Away from home the LAN is
unreachable, so the same devices are reached over Tailscale. This resolves each
device to its best available transport automatically — **LAN first, Tailscale
fallback** — and reports which devices are online and how. So Orion monitors a
multi-device server mesh "as if home" from anywhere, and picks devices back up
the moment they come online.

This is what makes Orion powerful on a server / across a device mesh: one brain,
many machines, reachable from any network.

Device map (per-instance — personal IPs stay OUT of the repo):
    ~/.orion/mesh/devices.json
    [{"name":"COMMAND","lan":"10.0.0.190","ts":"100.109.99.21","user":"servermac"}, ...]
If absent, devices are discovered live from `tailscale status`.

CLI:
    python orion_mesh.py                 # status of every device + transport
    python orion_mesh.py resolve NAME    # best reachable address for one device
    python orion_mesh.py --json          # machine-readable
"""

import json
import os
import shutil
import socket
import subprocess
import sys

MESH_DIR = os.path.join(os.environ.get("ORION_BRAIN_DIR") or os.path.expanduser("~/.orion"), "mesh")
DEVICES_PATH = os.path.join(MESH_DIR, "devices.json")
PROBE_PORT = 22          # ssh — present on every Orion host
LAN_TIMEOUT = 0.6        # LAN should answer fast; if not, we're probably away
TS_TIMEOUT = 2.5         # Tailscale relay can be slower


def _tcp_open(host, port, timeout):
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _tailscale_peers():
    """Discover devices from `tailscale status` when there's no device map."""
    exe = shutil.which("tailscale")
    for cand in (exe, r"C:\Program Files\Tailscale\tailscale.exe", "/usr/bin/tailscale",
                 "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if cand and os.path.exists(cand) or cand == exe and exe:
            try:
                out = subprocess.run([cand, "status"], capture_output=True, text=True, timeout=8).stdout
                peers = []
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].count(".") == 3:
                        peers.append({"name": parts[1], "lan": "", "ts": parts[0], "user": ""})
                if peers:
                    return peers
            except Exception:
                continue
    return []


def load_devices():
    if os.path.exists(DEVICES_PATH):
        try:
            with open(DEVICES_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return _tailscale_peers()


def resolve(device):
    """Return best transport for one device dict: LAN if reachable, else Tailscale.
    Returns {name, online, transport, address}."""
    name = device.get("name") or device.get("ts") or "?"
    lan, ts = device.get("lan"), device.get("ts")
    if lan and _tcp_open(lan, PROBE_PORT, LAN_TIMEOUT):
        return {"name": name, "online": True, "transport": "lan", "address": lan}
    if ts and _tcp_open(ts, PROBE_PORT, TS_TIMEOUT):
        return {"name": name, "online": True, "transport": "tailscale", "address": ts}
    return {"name": name, "online": False, "transport": None, "address": ts or lan or ""}


def status():
    return [resolve(d) for d in load_devices()]


STATE_PATH = os.path.join(MESH_DIR, "state.json")


def _publish_imessage(text):
    """Send a proactive iMessage via the substrate's outbound channel (the
    imessage_outbound subscriber delivers it). Best-effort."""
    try:
        from orion_substrate import publish
        publish("channel.imessage.outbound", {"text": text, "channel": "imessage"})
        return True
    except Exception:
        return False


def _publish_event(subject, payload):
    """Emit a structured mesh event on the substrate so the recovery loop
    (orion_mesh_recovery) and other services can react. Best-effort."""
    try:
        from orion_substrate import publish
        publish(subject, payload)
        return True
    except Exception:
        return False


def monitor(interval=60):
    """Probe all devices on a loop and TEXT the user on online<->offline
    transitions. Edge-triggered (state stored in mesh/state.json) so a sustained
    outage alerts ONCE, not every cycle — and announces recovery."""
    import time
    prev = {}
    if os.path.exists(STATE_PATH):
        try:
            prev = json.load(open(STATE_PATH, encoding="utf-8"))
        except Exception:
            prev = {}
    os.makedirs(MESH_DIR, exist_ok=True)
    print("orion-mesh monitor alive — %d devices, every %ds" % (len(load_devices()), interval))
    while True:
        cur = {}
        for r in status():
            cur[r["name"]] = r["online"]
            was = prev.get(r["name"])
            if was is True and r["online"] is False:
                _publish_imessage("Heads up, sir — %s just went OFFLINE on the mesh." % r["name"])
                _publish_event("brain.mesh.device_offline",
                               {"device": r["name"], "last_transport": r.get("transport"),
                                "address": r.get("address"), "ts": __import__("time").time()})
            elif was is False and r["online"] is True:
                _publish_imessage("%s is back ONLINE on the mesh, sir." % r["name"])
                _publish_event("brain.mesh.device_online",
                               {"device": r["name"], "transport": r.get("transport"),
                                "address": r.get("address"), "ts": __import__("time").time()})
        prev = cur
        try:
            json.dump(cur, open(STATE_PATH, "w", encoding="utf-8"))
        except Exception:
            pass
        time.sleep(interval)


def _main(argv):
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if argv and argv[0] == "monitor":
        interval = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 60
        return monitor(interval)
    if argv and argv[0] == "resolve" and len(argv) > 1:
        target = argv[1].lower()
        for d in load_devices():
            if (d.get("name", "").lower() == target) or (d.get("ts", "").lower() == target):
                r = resolve(d)
                print(json.dumps(r) if as_json else
                      "%s -> %s via %s" % (r["name"], r["address"] or "(offline)", r["transport"] or "offline"))
                return 0
        print("no such device: %s" % argv[1])
        return 1
    rows = status()
    if as_json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No devices mapped. Create ~/.orion/mesh/devices.json or install Tailscale.")
        return 0
    print("ORION MESH — devices (LAN-first, Tailscale-fallback):")
    for r in rows:
        mark = "online " if r["online"] else "OFFLINE"
        print("  %-14s %s  %-9s %s" % (r["name"], mark, r["transport"] or "-", r["address"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
