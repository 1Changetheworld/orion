#!/usr/bin/env bash
#
# orion_presence_install.sh
# ==========================
# One-time per-host installer for the Orion presence agent.
#
# Installs the agent to ~/.orion-agent/, registers it as a user-level
# systemd service, enables it to start at login, and starts it now.
#
# After this runs once on a host:
#   - Plugging in any Orion-shaped USB triggers automatic bootstrap.
#   - No user action required; models become Orion-aware seconds after plug-in.
#   - Pulling the USB is detected (logged) — full cleanup actor lands later.
#
# This script does NOT install Orion itself (no brain, no persona, no MCP wiring).
# It only installs the receptor that listens for Orion to arrive.
# Per the cellular design vocabulary: this is the host expressing the receptor;
# Orion-the-symbiote arrives later via USB.
#
# Idempotent. Safe to re-run.
#
# Linux only for now. macOS launchd version + Windows Task Scheduler version
# come in commits C + D.

set -euo pipefail

if [ "$(uname -s)" != "Linux" ]; then
    echo "ERROR: this installer is Linux-only for now. macOS + Windows installers coming."
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "ERROR: systemctl not found. Agent requires systemd."
    exit 1
fi

# Locate where this script lives (the orion repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_SRC="$SCRIPT_DIR/orion_presence_agent.py"

if [ ! -f "$AGENT_SRC" ]; then
    echo "ERROR: orion_presence_agent.py not found next to this installer ($SCRIPT_DIR)"
    exit 1
fi

INSTALL_DIR="$HOME/.orion-agent"
AGENT_DEST="$INSTALL_DIR/orion_presence_agent.py"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/orion-presence-agent.service"

mkdir -p "$INSTALL_DIR"
mkdir -p "$SERVICE_DIR"

# Copy the agent (vs symlink) — this way the host has a self-contained
# install. The USB can come and go; the agent stays.
cp "$AGENT_SRC" "$AGENT_DEST"
chmod +x "$AGENT_DEST"
echo "agent installed: $AGENT_DEST"

# Find a Python 3 to use. Prefer system /usr/bin/python3 (always present on Pi).
PY=$(command -v python3)
if [ -z "$PY" ]; then
    echo "ERROR: python3 not found on PATH"
    exit 1
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Orion presence agent — listens for Orion-shaped USB on plug-in
After=default.target

[Service]
Type=simple
ExecStart=$PY $AGENT_DEST
Restart=on-failure
RestartSec=5
# Inherit the desktop env so notify-send can reach the user's session
Environment=DISPLAY=:0

[Install]
WantedBy=default.target
EOF

echo "service unit installed: $SERVICE_FILE"

# Reload systemd, enable + start
systemctl --user daemon-reload
systemctl --user enable orion-presence-agent.service
systemctl --user restart orion-presence-agent.service

# Tiny sleep so we can report a real status
sleep 1
echo ""
echo "===== Service status ====="
systemctl --user status orion-presence-agent.service --no-pager --lines=5 || true

echo ""
echo "===== Done ====="
echo "  agent log:  ~/.orion-agent.log"
echo "  service:    ~/.config/systemd/user/orion-presence-agent.service"
echo "  manage:"
echo "    systemctl --user status   orion-presence-agent"
echo "    systemctl --user restart  orion-presence-agent"
echo "    systemctl --user stop     orion-presence-agent"
echo "    systemctl --user disable  orion-presence-agent  # auto-start at login off"
echo ""
echo "Plug in an Orion-shaped USB and watch ~/.orion-agent.log for the bootstrap event."
