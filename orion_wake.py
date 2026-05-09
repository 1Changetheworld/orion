#!/usr/bin/env python3
"""orion_wake.py - wire this host to an existing Orion brain on USB.

Replaces the inline Python heredoc that used to live in orion_bootstrap.sh.
Now both the Linux/macOS bootstrap (bash) AND the Windows installer
(PowerShell) call this same script, so the wake path is identical across
platforms - and Windows no longer requires git-bash to wake a host.

Usage:
    python orion_wake.py <usb-root> [<engine-root>]

If <engine-root> is omitted, it defaults to <usb-root>/.orion-system
(production ship layout) and falls back to <usb-root>/orion (dev clone).
"""
import os
import subprocess
import sys
from pathlib import Path


def wake_host(usb: str, repo: str) -> int:
    """Wire current host to the brain at <usb>/.orion using engine at <repo>.

    Returns 0 on success, non-zero on serious failure (junction failure
    is a warning, not a hard error - host can still reach brain via
    direct path).
    """
    sys.path.insert(0, repo)

    # 1. Junction / symlink ~/.orion -> <usb>/.orion so the brain is
    # reachable via the standard $HOME/.orion path that the rest of the
    # codebase assumes.
    home_orion = Path.home() / ".orion"
    target = Path(usb) / ".orion"

    if not home_orion.exists() and not home_orion.is_symlink():
        if sys.platform == "win32":
            r = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(home_orion), str(target)],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                print(f"  junctioned ~/.orion -> {target}")
            else:
                print(
                    f"  WARN: junction failed ({r.stderr.strip() or 'unknown'}). "
                    f"Brain still reachable at {target} directly.",
                    file=sys.stderr,
                )
        else:
            try:
                home_orion.symlink_to(target)
                print(f"  symlinked ~/.orion -> {target}")
            except FileExistsError:
                pass
            except OSError as e:
                print(f"  WARN: symlink failed: {e}", file=sys.stderr)

    # 2. Persona files + Claude SessionStart hook. Auto-detects which
    # CLIs are installed on this host and only injects for those.
    try:
        from orion_setup_chat import detect_cli_tools
        from orion_ui import inject_context
    except ImportError as e:
        print(f"ERROR: cannot import engine modules from {repo}: {e}", file=sys.stderr)
        return 2

    tools = detect_cli_tools()
    detected_fuel = {
        "claude_cli": {"available": tools.get("claude", {}).get("installed", False)},
        "codex":      {"available": tools.get("codex", {}).get("installed", False)},
        "gemini":     {"available": tools.get("gemini", {}).get("installed", False)},
    }
    results = inject_context(detected_fuel)
    for label, _path in results:
        print(f"  inject_context: {label}")

    # 3. MCP registration in detected CLIs (Claude / Codex / Gemini).
    mcp_setup = Path(repo) / "orion_mcp_server.py"
    if mcp_setup.exists():
        mcp_result = subprocess.run(
            [sys.executable, str(mcp_setup), "--setup"],
            capture_output=True, text=True, timeout=30,
        )
        for line in (mcp_result.stdout or "").splitlines():
            print(f"  mcp: {line}")
        if mcp_result.returncode != 0 and (mcp_result.stderr or "").strip():
            print(f"  mcp WARN: {mcp_result.stderr.strip()}", file=sys.stderr)
    else:
        print(f"  WARN: orion_mcp_server.py not found at {mcp_setup}", file=sys.stderr)

    # 4. Refresh per-CLI transcript junctions to point at <usb>/.orion/transcripts/.
    # The wizard does this on first install but wake skipped it - so junctions
    # from previous installs (or older USB layouts) went stale. Codex hit
    # "os error 183" trying to write through a dangling junction. Caught
    # 2026-05-07 on Windows VM.
    try:
        from orion_setup_chat import _redirect_cli_transcripts
        for cli_name, status in _redirect_cli_transcripts(usb):
            print(f"  transcripts {cli_name}: {status}")
    except Exception as e:
        print(f"  WARN: transcript refresh failed: {e.__class__.__name__}: {e}",
              file=sys.stderr)

    # 5. Record host visit + announce first-time-on-this-OS.
    # Cell-biology framing: a cell knows when it's in a new tissue. Orion
    # should know when he's on a new OS for the first time and acknowledge
    # it - that's substrate awareness, the foundation of aliveness.
    # Founder rule 2026-05-08: "if Orion's never been on Mac make sure if
    # he ever is he recognizes that in first intro."
    _record_host_visit(usb)

    # 6. Plexus substrate (Layer 1) — advertise this host's capabilities
    # on the event bus so the dispatcher (when built) can route to us.
    # No-op if substrate unreachable; existing wake completes regardless.
    # See project_orion-plexus-architecture.md.
    _advertise_capabilities(repo)

    return 0


def _advertise_capabilities(repo: str) -> None:
    """Publish a capability manifest for this host on the Plexus
    substrate. Run once at the end of wake. The dispatcher (Layer 3,
    not yet built) will use these advertisements to route requests
    to the best-fit node. Octopus pattern: each arm announces what it
    can do; brain decides where to send work. See Agent 4 research in
    project_orion-plexus-architecture.md (Layer 3c).
    """
    import platform
    import shutil

    sys.path.insert(0, repo)
    try:
        from orion_substrate import (
            publish, host_capabilities_subject, host_wake_subject,
        )
    except Exception:
        return  # Substrate module not importable; silent skip.

    if sys.platform == "darwin":
        os_tag = "macos"
    elif sys.platform == "win32":
        os_tag = "windows"
    elif sys.platform.startswith("linux"):
        os_tag = "linux"
    else:
        os_tag = sys.platform

    fuels_available = []
    for cmd in ("claude", "codex", "gemini", "ollama"):
        if shutil.which(cmd):
            fuels_available.append(cmd)

    try:
        host_tag = platform.node().split(".")[0].lower() or "unknown"
    except Exception:
        host_tag = "unknown"

    manifest = {
        "node_id": host_tag,
        "os_tag": os_tag,
        "machine": platform.machine() if hasattr(platform, "machine") else "",
        "fuels_available": fuels_available,
        "wake_ts": __import__("time").time(),
    }

    # One wake event + one capabilities advertisement.
    publish(host_wake_subject(host_tag), manifest)
    publish(host_capabilities_subject(host_tag), manifest)


def _record_host_visit(usb: str) -> None:
    """Track which OSes Orion has been woken on. Writes to
    <usb>/.orion/hosts_visited.json. On first contact with a new OS,
    prints an announcement and stores a recallable memory so future
    intros surface it.
    """
    import json
    import datetime
    from pathlib import Path

    hosts_path = Path(usb) / ".orion" / "hosts_visited.json"

    if sys.platform == "darwin":
        os_tag, os_label = "macos", "macOS"
    elif sys.platform == "win32":
        os_tag, os_label = "windows", "Windows"
    elif sys.platform.startswith("linux"):
        os_tag, os_label = "linux", "Linux"
    else:
        os_tag = os_label = sys.platform

    now = datetime.datetime.now().isoformat(timespec="seconds")
    visited = {}
    if hosts_path.exists():
        try:
            visited = json.loads(hosts_path.read_text(encoding="utf-8"))
        except Exception:
            visited = {}

    is_first = os_tag not in visited
    if is_first:
        visited[os_tag] = {"first_seen": now, "last_seen": now, "count": 1}
        prior = sorted(k for k in visited.keys() if k != os_tag)
        prior_label = ", ".join(p.capitalize() for p in prior) or "(none)"
        print(f"\n  [first contact] this is the first time I've been on {os_label}.")
        print(f"  [first contact] prior hosts: {prior_label}")
        print(f"  [first contact] now living across: {', '.join(sorted(visited.keys()))}")
    else:
        visited[os_tag]["last_seen"] = now
        visited[os_tag]["count"] = int(visited[os_tag].get("count", 0)) + 1

    try:
        hosts_path.parent.mkdir(parents=True, exist_ok=True)
        hosts_path.write_text(json.dumps(visited, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  WARN: could not record host visit: {e}", file=sys.stderr)
        return

    # Plant a memory node so models can answer "what OSes have you been on"
    # via orion_recall without needing to read this file directly.
    if is_first:
        try:
            import urllib.request
            auth_token_path = Path.home() / ".orion" / "auth-token"
            if auth_token_path.exists():
                token = auth_token_path.read_text(encoding="utf-8").strip()
                payload = json.dumps({
                    "name": "orion_memorize",
                    "arguments": {
                        "user_message": f"[host first contact] First wake on {os_label} at {now}.",
                        "ai_response": f"Logged. I now live across {len(visited)} operating system(s): {', '.join(sorted(visited.keys()))}.",
                    },
                }).encode("utf-8")
                req = urllib.request.Request(
                    "http://127.0.0.1:5556/v1/call",
                    data=payload,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=4).read()
        except Exception:
            pass  # Brain service may not be running; the json file is the fallback.


def _resolve_repo(usb: str) -> str:
    ship = Path(usb) / ".orion-system"
    if ship.is_dir():
        return str(ship)
    dev = Path(usb) / "orion"
    if dev.is_dir():
        return str(dev)
    raise SystemExit(
        f"ERROR: no engine source at {ship} or {dev}. Wake aborted."
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: orion_wake.py <usb-root> [<engine-root>]", file=sys.stderr)
        return 2
    usb = os.path.abspath(sys.argv[1])
    repo = os.path.abspath(sys.argv[2]) if len(sys.argv) >= 3 else _resolve_repo(usb)
    return wake_host(usb, repo)


if __name__ == "__main__":
    raise SystemExit(main())
