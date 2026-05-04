#!/usr/bin/env python3
"""
orion_presence_agent.py
=======================
Linux/POSIX host presence agent — the receptor that listens for Orion to arrive.

Watches standard mount roots (/media/$USER/, /run/media/$USER/, /mnt/, /Volumes/)
for new mounts. When a new mount appears containing
<mount>/.orion/presence-beacon.json, the agent invokes orion_bootstrap.sh
in agent mode (--quiet --notify --usb <mount>) to wake Orion on this host.

Pure stdlib. No extra packages. Polls every 2 seconds — accurate enough
for plug-and-play, light enough to run forever in the background.

Cellular vocabulary mapping (per project_orion-cellular-design-vocabulary.md):
  this script = receptor on the cell membrane
  presence beacon = ligand
  bootstrap script = signaling cascade triggered by binding

Designed to run as a user-level systemd service (or launchd on macOS).
See orion_presence_install.sh for the per-host one-time install.

Behavior:
- On startup: scan mount roots, record what's there, do NOT bootstrap
  pre-existing mounts (only react to NEW arrivals).
- Loop: every 2s, scan again. Any new mount containing a beacon -> invoke
  bootstrap. Any mount that disappeared -> log only (cleanup actor in
  commit F will hook here later).
- Logs to ~/.orion-agent.log so the user can grep what fired and when.
- Handles SIGTERM/SIGINT gracefully (systemd will send SIGTERM on stop).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

POLL_INTERVAL_SEC = 2.0
LOG_PATH = Path.home() / ".orion-agent.log"
RUNNING = True


def log(msg: str) -> None:
    """Append to the agent log. Best-effort (failure here doesn't kill the agent)."""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")
    except Exception:
        pass


def get_mount_roots() -> list[Path]:
    """Standard places where removable media gets auto-mounted on POSIX systems."""
    user = os.environ.get("USER", "")
    candidates = [
        Path(f"/media/{user}") if user else None,
        Path(f"/run/media/{user}") if user else None,
        Path("/media"),
        Path("/mnt"),
        Path("/Volumes"),  # macOS
    ]
    return [p for p in candidates if p and p.is_dir()]


def scan_mounts() -> set:
    """Return the set of currently-mounted directories under known roots."""
    mounts = set()
    for root in get_mount_roots():
        try:
            for entry in os.scandir(root):
                if entry.is_dir(follow_symlinks=False):
                    mounts.add(entry.path)
        except (PermissionError, FileNotFoundError):
            continue
    return mounts


def has_orion_beacon(mount_path: str) -> tuple[bool, dict | None]:
    """Returns (True, beacon_dict) if this mount carries an Orion beacon."""
    beacon = Path(mount_path) / ".orion" / "presence-beacon.json"
    if not beacon.exists():
        return (False, None)
    try:
        data = json.loads(beacon.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "orion_id" in data and "schema_version" in data:
            return (True, data)
    except Exception as e:
        log(f"  beacon at {beacon} unreadable: {e.__class__.__name__}: {e}")
    return (False, None)


def find_bootstrap_script(mount_path: str) -> Path | None:
    """Locate orion_bootstrap.sh on the USB. Standard repo layout: <mount>/orion/orion_bootstrap.sh."""
    candidates = [
        Path(mount_path) / "orion" / "orion_bootstrap.sh",
        Path(mount_path) / "orion-repo" / "orion_bootstrap.sh",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def trigger_bootstrap(mount_path: str, beacon: dict) -> None:
    """Invoke orion_bootstrap.sh in agent (quiet + notify) mode."""
    script = find_bootstrap_script(mount_path)
    if not script:
        log(f"  beacon present at {mount_path} but bootstrap script not found")
        return

    log(f"  bootstrap script: {script}")
    log(f"  orion_id: {beacon.get('orion_id')}")

    # Build env: pass through DISPLAY so notify-send can reach the user's GUI
    env = dict(os.environ)
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"  # default for desktop session
    # Some systemd user units don't inherit DBUS_SESSION_BUS_ADDRESS by default;
    # try common path so notify-send works.
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        uid = os.getuid()
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"

    try:
        result = subprocess.run(
            ["bash", str(script), "--quiet", "--notify", "--usb", mount_path],
            timeout=180,
            capture_output=True,
            text=True,
            env=env,
        )
        log(f"  bootstrap exit code: {result.returncode}")
        if result.stdout.strip():
            log(f"  bootstrap stdout: {result.stdout.strip()[:500]}")
        if result.stderr.strip():
            log(f"  bootstrap stderr: {result.stderr.strip()[:500]}")
    except subprocess.TimeoutExpired:
        log(f"  bootstrap timed out after 180s")
    except Exception as e:
        log(f"  bootstrap exception: {e.__class__.__name__}: {e}")


def handle_signal(signum, frame) -> None:
    global RUNNING
    log(f"received signal {signum}, shutting down")
    RUNNING = False


def main() -> int:
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log("===== Orion presence agent starting =====")
    log(f"  user: {os.environ.get('USER', 'unknown')}")
    log(f"  poll interval: {POLL_INTERVAL_SEC}s")
    log(f"  watching mount roots: {[str(r) for r in get_mount_roots()]}")

    # Initial scan — record what's already mounted so we don't bootstrap on
    # mounts that pre-existed before the agent started.
    known = scan_mounts()
    log(f"  pre-existing mounts (will NOT auto-bootstrap): {sorted(known)}")

    # Check pre-existing mounts ONCE on startup — if Orion USB was already
    # plugged in when agent launched, we want to know but not auto-trigger
    # (user's choice on first run; subsequent plug-ins will trigger).
    for m in known:
        ok, beacon = has_orion_beacon(m)
        if ok:
            log(f"  ! pre-existing Orion USB at {m} (orion_id={beacon.get('orion_id')}) — not bootstrapping (run agent restart to force)")

    while RUNNING:
        time.sleep(POLL_INTERVAL_SEC)
        try:
            current = scan_mounts()
        except Exception as e:
            log(f"scan failed: {e.__class__.__name__}: {e}")
            continue

        new_mounts = current - known
        gone_mounts = known - current

        for m in new_mounts:
            log(f"new mount: {m}")
            ok, beacon = has_orion_beacon(m)
            if ok:
                log(f"  -> Orion beacon found, triggering bootstrap")
                trigger_bootstrap(m, beacon)
            else:
                log(f"  -> not an Orion USB, ignored")

        for m in gone_mounts:
            log(f"mount removed: {m}")
            # Cleanup actor (commit F) will hook here:
            #   if it was an Orion USB, run cleanup actor to strip junctions etc.

        known = current

    log("===== Orion presence agent stopped =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
