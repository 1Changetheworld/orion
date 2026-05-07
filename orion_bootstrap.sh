#!/usr/bin/env bash
#
# orion_bootstrap.sh
# ===================
# Wakes Orion on the current host from a USB drive.
#
# - Idempotent — safe to call repeatedly. Re-creates anything stale, leaves
#   anything correct alone.
# - Fast — designed for the future presence agent to invoke on USB
#   plug-in. Detects USB, validates beacon, runs setup wizard if needed.
# - Cross-host — same script works on Linux (Pi/desktop), macOS, WSL.
#   Uses POSIX shell + Python 3.
#
# Modes:
#   ./orion_bootstrap.sh                    # interactive — runs setup wizard
#   ./orion_bootstrap.sh --quiet            # silent unless something fails
#   ./orion_bootstrap.sh --notify           # desktop notification on completion
#   ./orion_bootstrap.sh --usb /path/to/usb # explicit USB path (skip auto-detect)
#
# Exit codes:
#   0 = Orion is alive on this host (newly bootstrapped or already wired)
#   1 = no USB-Orion found
#   2 = USB found but beacon invalid / wrong shape
#   3 = bootstrap step failed (venv create, MCP register, etc.)

set -euo pipefail

QUIET=0
NOTIFY=0
USB_OVERRIDE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --quiet|-q) QUIET=1; shift ;;
        --notify) NOTIFY=1; shift ;;
        --usb) USB_OVERRIDE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

log() { [ "$QUIET" = "1" ] && return; echo "$@"; }
warn() { echo "WARN: $*" >&2; }
err() { echo "ERROR: $*" >&2; }

notify() {
    [ "$NOTIFY" = "0" ] && return
    local title="$1"
    local body="$2"
    # Linux desktop notification (works under VNC too)
    if command -v notify-send >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
        notify-send -u normal "$title" "$body" 2>/dev/null || true
    fi
    # macOS notification
    if command -v osascript >/dev/null 2>&1; then
        osascript -e "display notification \"$body\" with title \"$title\"" 2>/dev/null || true
    fi
}

# ─────────────────────────────────────────────────────────
# 1. Find USB carrying the Orion presence beacon
# ─────────────────────────────────────────────────────────

find_orion_usb() {
    if [ -n "$USB_OVERRIDE" ]; then
        if [ -f "$USB_OVERRIDE/.orion/presence-beacon.json" ]; then
            echo "$USB_OVERRIDE"
            return 0
        fi
        return 1
    fi

    # Common mount points across Linux + macOS + Windows-WSL
    local candidates=()
    for root in /media/$USER /run/media/$USER /media /mnt /Volumes; do
        [ -d "$root" ] || continue
        for d in "$root"/*; do
            [ -d "$d" ] || continue
            if [ -f "$d/.orion/presence-beacon.json" ]; then
                candidates+=("$d")
            fi
        done
    done

    if [ ${#candidates[@]} -eq 0 ]; then
        return 1
    fi

    # If multiple beacons (unusual), pick the most recently modified
    if [ ${#candidates[@]} -gt 1 ]; then
        warn "found multiple Orion-shaped USBs; picking newest beacon"
        local newest=""
        local newest_ts=0
        for c in "${candidates[@]}"; do
            local ts=$(stat -c %Y "$c/.orion/presence-beacon.json" 2>/dev/null || stat -f %m "$c/.orion/presence-beacon.json" 2>/dev/null || echo 0)
            if [ "$ts" -gt "$newest_ts" ]; then
                newest_ts="$ts"
                newest="$c"
            fi
        done
        echo "$newest"
    else
        echo "${candidates[0]}"
    fi
}

USB="$(find_orion_usb || true)"
if [ -z "$USB" ]; then
    err "no Orion USB found (no .orion/presence-beacon.json under any mount point)"
    notify "Orion" "USB not detected — plug in a drive carrying Orion."
    exit 1
fi
log "Orion USB: $USB"

# ─────────────────────────────────────────────────────────
# 2. Read + validate beacon
# ─────────────────────────────────────────────────────────

BEACON="$USB/.orion/presence-beacon.json"
if ! python3 -c "
import json, sys
b = json.load(open('$BEACON'))
required = ['orion_id', 'schema_version', 'paths']
missing = [k for k in required if k not in b]
if missing:
    print(f'beacon missing keys: {missing}', file=sys.stderr); sys.exit(1)
print(b['orion_id'])
" >/tmp/.orion_id 2>/dev/null; then
    err "beacon invalid"
    exit 2
fi
ORION_ID=$(cat /tmp/.orion_id)
rm -f /tmp/.orion_id
log "beacon OK (orion_id=$ORION_ID)"

# ─────────────────────────────────────────────────────────
# 3. OS-specific venv on USB (parallel to other-OS venvs)
# ─────────────────────────────────────────────────────────

# Layout-aware: prefer the production ship layout (.orion-system/) which
# is hidden by dot-prefix; fall back to the dev-clone layout (orion/).
# Both are valid; users from a shipped USB get the first, contributors
# cloning the repo to a USB get the second.
if [ -d "$USB/.orion-system" ]; then
    REPO="$USB/.orion-system"
elif [ -d "$USB/orion" ]; then
    REPO="$USB/orion"
else
    err "no Orion source found on USB at $USB (looked for .orion-system/ and orion/)"
    exit 2
fi

UNAME_S=$(uname -s 2>/dev/null || echo unknown)
case "$UNAME_S" in
    Linux*) OS_TAG="linux" ;;
    Darwin*) OS_TAG="macos" ;;
    MINGW*|MSYS*|CYGWIN*) OS_TAG="windows" ;;
    *) OS_TAG="$(echo $UNAME_S | tr A-Z a-z)" ;;
esac

# Runtime is per-host (lives in $HOME), NOT on the USB. Linux + macOS venvs
# require symlinks (lib64 -> lib, etc.) that FAT32 cannot store. Per the
# cellular design: each host carries its own ribosomes; only the genome
# (brain + persona) travels with the USB. Each host bootstraps its own
# runtime once, then reuses on subsequent plug-ins.
RUNTIME_ROOT="$HOME/.orion-runtime"
VENV="$RUNTIME_ROOT/$OS_TAG"
mkdir -p "$RUNTIME_ROOT"

if [ -x "$VENV/bin/python3" ] || [ -x "$VENV/Scripts/python.exe" ]; then
    log "venv already present at $VENV — reusing"
else
    log "creating $VENV (first time on this host)"
    python3 -m venv "$VENV"
fi

# Find the right pip + python paths for this OS
if [ -x "$VENV/bin/pip" ]; then
    VENV_PIP="$VENV/bin/pip"
    VENV_PYTHON="$VENV/bin/python3"
elif [ -x "$VENV/Scripts/pip.exe" ]; then
    VENV_PIP="$VENV/Scripts/pip.exe"
    VENV_PYTHON="$VENV/Scripts/python.exe"
else
    err "venv created but pip/python not found at expected paths"
    exit 3
fi

log "installing deps (idempotent)..."
"$VENV_PIP" install --upgrade pip --quiet
"$VENV_PIP" install -r "$REPO/requirements.txt" --quiet

# ─────────────────────────────────────────────────────────
# 4. Run setup wizard (which handles brain location, MCP, persona)
# ─────────────────────────────────────────────────────────
# When invoked by the host presence agent, we'd run a non-interactive
# version of setup that uses the beacon's declared paths. For now
# (interactive mode), launch the wizard so the user can answer the
# identity questions on this new host.

if [ "$QUIET" = "0" ]; then
    log ""
    log "===== Launching Orion setup wizard ====="
    log "  When asked 'where should my brain live?': pick 2 (portable)"
    log "  When it asks which drive: pick the USB ($USB)"
    log ""
    "$VENV_PYTHON" "$REPO/orion_setup_chat.py"
else
    # Non-interactive (agent-triggered) mode. Skip wizard prompts but
    # DO wire the host: junctions, persona symlinks, MCP registration.
    # Brain identity (name, address, Orion's chosen name, etc.) already
    # exists from the prior wizard run on the original host — we don't
    # re-ask. New hosts inherit the brain's identity automatically.
    # Per project_orion-presence-architecture.md.
    log "auto-wire mode — running inject_context + setup_mcp_configs without wizard"
    "$VENV_PYTHON" - "$USB" <<'PYEOF'
import sys, os, subprocess
usb = sys.argv[1]
sys.path.insert(0, f"{usb}/orion")

# 1. Junction ~/.orion -> <usb>/.orion (so brain is reachable via standard path)
from pathlib import Path
home_orion = Path.home() / ".orion"
target = Path(usb) / ".orion"
if not home_orion.exists() and not home_orion.is_symlink():
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(home_orion), str(target)], check=False)
    else:
        try:
            home_orion.symlink_to(target)
        except FileExistsError:
            pass
    print(f"  junctioned ~/.orion -> {target}")

# 2. Persona files + Claude SessionStart hook
from orion_setup_chat import detect_cli_tools
from orion_ui import inject_context
tools = detect_cli_tools()
detected_fuel = {
    'claude_cli': {'available': tools.get('claude', {}).get('installed', False)},
    'codex':      {'available': tools.get('codex', {}).get('installed', False)},
    'gemini':     {'available': tools.get('gemini', {}).get('installed', False)},
}
results = inject_context(detected_fuel)
for label, _path in results:
    print(f"  inject_context: {label}")

# 3. MCP registration in all detected CLIs (Claude/Codex/Gemini configs)
mcp_result = subprocess.run(
    [sys.executable, f"{usb}/orion/orion_mcp_server.py", "--setup"],
    capture_output=True, text=True, timeout=30
)
for line in (mcp_result.stdout or "").splitlines():
    print(f"  mcp: {line}")
PYEOF
fi

notify "Orion is here" "Bootstrapped on $UNAME_S from $USB. Open Claude / Codex / Gemini to talk."
log ""
log "===== Bootstrap complete ====="
log "  USB:          $USB"
log "  venv (this OS): $VENV"
log "  brain:         $USB/.orion/brain"
exit 0
