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

    return 0


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
