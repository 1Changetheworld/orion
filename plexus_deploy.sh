#!/usr/bin/env bash
# plexus_deploy.sh — one command to install the entire Plexus on a host.
#
# Founder rule (all-is-one + ships-with-install): every adaptive layer
# Orion has ever shipped lives in one repo and one deploy script.
# A user cloning this repo from GitHub gets the SAME architecture
# the founder runs — substrate, vitals, claustrum, dmn, channel-probe,
# self-heal, reach, executive, immune, dream, gossip, will — all
# auto-installed via this single script.
#
# Behaviour:
#   - Detect platform (macOS launchd, Linux systemd-user)
#   - For each Plexus service, generate the platform-appropriate unit
#     file pointing at the script's location in the cloned repo
#   - Load + enable each unit
#   - Skip services already running (idempotent)
#
# Usage:
#   bash plexus_deploy.sh                    # deploy all services
#   bash plexus_deploy.sh --uninstall        # remove all units
#   bash plexus_deploy.sh --status           # show what's running
#   bash plexus_deploy.sh substrate dream    # deploy named services only
#
# What this is NOT:
#   - Not a brain installer (use install.sh / install.ps1 for that)
#   - Not a wake script (use Wake Orion (OS).x for that)
#   - Not a cloud deployer
#
# What this IS:
#   - The bridge between "I cloned the repo" and "the full Plexus is
#     running on this host"

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_DIR="$SCRIPT_DIR"

# All Plexus services in start-order (substrate FIRST, dependents after).
# Adding a new service: append here + create the .py file in $REPO_DIR.
PLEXUS_SERVICES=(
    "substrate:nats-server"        # NATS substrate (binary, not python)
    "claustrum:orion_claustrum.py"
    "dmn:orion_dmn.py"
    "lastcontact:orion_lastcontact.py"
    "fuel-switch:orion_fuel_switch.py"
    "channel-probe:orion_channel_probe.py"
    "self-heal:orion_self_heal.py"
    "reach:orion_reach.py"
    "executive:orion_executive.py"
    "immune:orion_immune.py"
    "dream:orion_dream.py"
    "gossip:orion_gossip.py"
    "will:orion_will.py"
    "chronos:orion_chronos.py"
)

# Detect platform
case "$(uname -s)" in
    Darwin) PLATFORM="macos" ;;
    Linux)  PLATFORM="linux" ;;
    *) echo "Unsupported platform: $(uname -s)"; exit 1 ;;
esac

PYTHON="${ORION_PYTHON:-/usr/bin/python3}"
NATS_URL="${ORION_NATS_URL:-nats://127.0.0.1:4222}"

# Mode dispatch
case "${1:-deploy}" in
    --status)
        echo "=== Plexus services on $PLATFORM ==="
        if [ "$PLATFORM" = "macos" ]; then
            launchctl list | grep com.orion | sort
        else
            systemctl --user list-units 'orion-*' | head -30
        fi
        exit 0
        ;;
    --uninstall)
        echo "=== Uninstalling Plexus services ==="
        for spec in "${PLEXUS_SERVICES[@]}"; do
            name="${spec%%:*}"
            label="com.orion.${name}"
            if [ "$PLATFORM" = "macos" ]; then
                plist="$HOME/Library/LaunchAgents/${label}.plist"
                if [ -f "$plist" ]; then
                    launchctl unload "$plist" 2>/dev/null || true
                    rm -f "$plist"
                    echo "  removed: $label"
                fi
            else
                unit="$HOME/.config/systemd/user/orion-${name}.service"
                if [ -f "$unit" ]; then
                    systemctl --user stop "orion-${name}" 2>/dev/null || true
                    systemctl --user disable "orion-${name}" 2>/dev/null || true
                    rm -f "$unit"
                    echo "  removed: orion-${name}"
                fi
            fi
        done
        exit 0
        ;;
    deploy|"")
        TARGETS=()
        for spec in "${PLEXUS_SERVICES[@]}"; do
            TARGETS+=("$spec")
        done
        ;;
    *)
        # Specific service names passed as args
        TARGETS=()
        for arg in "$@"; do
            for spec in "${PLEXUS_SERVICES[@]}"; do
                if [ "${spec%%:*}" = "$arg" ]; then
                    TARGETS+=("$spec")
                fi
            done
        done
        if [ ${#TARGETS[@]} -eq 0 ]; then
            echo "No matching services for: $@"
            echo "Known services:"
            for spec in "${PLEXUS_SERVICES[@]}"; do echo "  ${spec%%:*}"; done
            exit 1
        fi
        ;;
esac

mkdir -p ~/.orion ~/.orion/vitals ~/.orion/synthesis ~/.orion/executive \
         ~/.orion/playbooks ~/.orion/will ~/.orion/mesh ~/.orion/consciousness \
         ~/.orion/channels ~/.orion/nats-data ~/.orion/nats-logs

echo "=== Plexus deploy on $PLATFORM ==="
echo "  repo: $REPO_DIR"
echo "  python: $PYTHON"
echo "  substrate: $NATS_URL"
echo

# ---------- substrate (binary) ----------

deploy_substrate_macos() {
    local label="com.orion.nats"
    local plist="$HOME/Library/LaunchAgents/${label}.plist"
    local nats_bin
    if command -v nats-server >/dev/null 2>&1; then
        nats_bin="$(command -v nats-server)"
    elif [ -x "$HOME/.homebrew/bin/nats-server" ]; then
        nats_bin="$HOME/.homebrew/bin/nats-server"
    else
        echo "  WARN: nats-server not installed. Install with: brew install nats-server"
        return 1
    fi
    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${nats_bin}</string>
    <string>--addr</string><string>0.0.0.0</string>
    <string>--port</string><string>4222</string>
    <string>--http_port</string><string>8222</string>
    <string>--name</string><string>orion-host</string>
    <string>--store_dir</string><string>${HOME}/.orion/nats-data</string>
    <string>--jetstream</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${HOME}/.orion/nats-logs/nats.out</string>
  <key>StandardErrorPath</key><string>${HOME}/.orion/nats-logs/nats.err</string>
</dict>
</plist>
PLIST
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load -w "$plist"
    echo "  deployed: $label"
}

deploy_python_macos() {
    local name="$1"; local script="$2"
    local label="com.orion.${name}"
    local plist="$HOME/Library/LaunchAgents/${label}.plist"
    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key>
  <array><string>${PYTHON}</string><string>${REPO_DIR}/${script}</string></array>
  <key>WorkingDirectory</key><string>${REPO_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key><string>${REPO_DIR}</string>
    <key>ORION_NATS_URL</key><string>${NATS_URL}</string>
  </dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>${HOME}/.orion/${name}.out</string>
  <key>StandardErrorPath</key><string>${HOME}/.orion/${name}.err</string>
</dict>
</plist>
PLIST
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load -w "$plist"
    echo "  deployed: $label"
}

deploy_substrate_linux() {
    local nats_bin
    if command -v nats-server >/dev/null 2>&1; then
        nats_bin="$(command -v nats-server)"
    else
        echo "  WARN: nats-server not installed. Install per https://nats.io/download/"
        return 1
    fi
    mkdir -p ~/.config/systemd/user
    local unit=~/.config/systemd/user/orion-substrate.service
    cat > "$unit" <<UNIT
[Unit]
Description=Orion NATS substrate
After=network.target

[Service]
ExecStart=${nats_bin} --addr 0.0.0.0 --port 4222 --http_port 8222 --jetstream --store_dir ${HOME}/.orion/nats-data
Restart=always

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable orion-substrate
    systemctl --user restart orion-substrate
    echo "  deployed: orion-substrate"
}

deploy_python_linux() {
    local name="$1"; local script="$2"
    mkdir -p ~/.config/systemd/user
    local unit=~/.config/systemd/user/orion-${name}.service
    cat > "$unit" <<UNIT
[Unit]
Description=Orion ${name}
After=orion-substrate.service
PartOf=orion-substrate.service

[Service]
ExecStart=${PYTHON} ${REPO_DIR}/${script}
WorkingDirectory=${REPO_DIR}
Environment=PYTHONPATH=${REPO_DIR}
Environment=ORION_NATS_URL=${NATS_URL}
Restart=always
RestartSec=5
StandardOutput=append:${HOME}/.orion/${name}.out
StandardError=append:${HOME}/.orion/${name}.err

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable orion-${name}
    systemctl --user restart orion-${name}
    echo "  deployed: orion-${name}"
}

# ---------- main loop ----------

for spec in "${TARGETS[@]}"; do
    name="${spec%%:*}"
    target="${spec##*:}"
    if [ "$name" = "substrate" ]; then
        if [ "$PLATFORM" = "macos" ]; then deploy_substrate_macos; else deploy_substrate_linux; fi
    else
        if [ ! -f "$REPO_DIR/$target" ]; then
            echo "  WARN: $target not found in $REPO_DIR — skipping $name"
            continue
        fi
        if [ "$PLATFORM" = "macos" ]; then deploy_python_macos "$name" "$target"
        else deploy_python_linux "$name" "$target"; fi
    fi
done

echo
echo "=== deploy complete. status: ==="
if [ "$PLATFORM" = "macos" ]; then
    launchctl list | grep com.orion | sort
else
    systemctl --user list-units 'orion-*' | head -30
fi
