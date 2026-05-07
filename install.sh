#!/usr/bin/env bash
# orion install — Linux / macOS bootstrapper.
#
# Does exactly what a new user needs on a fresh machine:
#   1. Detect the package manager
#   2. Install Python 3 + tkinter + venv (if missing)
#   3. Create a venv inside the repo and install pip deps
#   4. Offer to install Ollama (optional, for free local fuel)
#   5. Write a bash `orion` launcher to ~/.local/bin/orion
#   6. Run the setup wizard (python setup.py)
#
# What this script does NOT do:
#   - sudo anything without explicit consent
#   - modify ~/.bashrc or ~/.zshrc unless user agrees
#   - install any AI CLI tool other than Ollama (Claude/Codex/Gemini
#     have their own installers; this script respects that)
#
# Usage:
#   curl -sL <URL>/install.sh | bash     # not recommended, prefer clone
#   OR after cloning:
#     cd orion && bash install.sh
#
# Tested on: Debian/Ubuntu (apt), Raspberry Pi OS (apt on ARM).
# Should work on: Fedora (dnf), Arch (pacman), macOS (brew) — with warnings.

set -e

# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Tell git this repo is safe even when it lives on a removable drive
# (FAT/exFAT don't record file ownership, which git treats as suspicious).
# Idempotent.
if command -v git >/dev/null 2>&1; then
    git config --global --add safe.directory "$SCRIPT_DIR" >/dev/null 2>&1 || true
fi
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
RESET='\033[0m'

say()   { printf "%b\n" "$*"; }
info()  { printf "${CYAN}%s${RESET}\n" "$*"; }
ok()    { printf "${GREEN}✓${RESET}  %s\n" "$*"; }
warn()  { printf "${YELLOW}!${RESET}  %s\n" "$*"; }
fail()  { printf "${RED}✗${RESET}  %s\n" "$*" >&2; }
ask()   { read -r -p "$(printf "${CYAN}?${RESET}  %s " "$*")" _ans; }

# ----------------------------------------------------------------
# Detect package manager (protocol curation, not distro curation —
# we care about what it can install, not which distro label)
# ----------------------------------------------------------------

PKG_MANAGER=""
PKG_INSTALL=""
PKG_UPDATE=""

if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt"
    PKG_INSTALL="sudo apt-get install -y"
    PKG_UPDATE="sudo apt-get update"
elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
    PKG_INSTALL="sudo dnf install -y"
    PKG_UPDATE="sudo dnf check-update || true"
elif command -v pacman >/dev/null 2>&1; then
    PKG_MANAGER="pacman"
    PKG_INSTALL="sudo pacman -S --noconfirm"
    PKG_UPDATE="sudo pacman -Sy"
elif command -v brew >/dev/null 2>&1; then
    PKG_MANAGER="brew"
    PKG_INSTALL="brew install"
    PKG_UPDATE="brew update"
else
    fail "No known package manager found (apt, dnf, pacman, brew)."
    warn "You can still install Orion manually: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    exit 1
fi

info "Detected package manager: $PKG_MANAGER"

# ----------------------------------------------------------------
# Check and optionally install system packages
# ----------------------------------------------------------------

NEEDED_SYS_PKGS=()

command -v python3      >/dev/null 2>&1 || NEEDED_SYS_PKGS+=("python3")
python3 -c "import venv" >/dev/null 2>&1 || NEEDED_SYS_PKGS+=("python3-venv")
python3 -c "import tkinter" >/dev/null 2>&1 || {
    case "$PKG_MANAGER" in
        apt)    NEEDED_SYS_PKGS+=("python3-tk") ;;
        dnf)    NEEDED_SYS_PKGS+=("python3-tkinter") ;;
        pacman) NEEDED_SYS_PKGS+=("tk") ;;
        brew)   ;;  # macOS python usually ships with tk
    esac
}
command -v pip3 >/dev/null 2>&1 || NEEDED_SYS_PKGS+=("python3-pip")

if [ ${#NEEDED_SYS_PKGS[@]} -gt 0 ]; then
    warn "Missing system packages: ${NEEDED_SYS_PKGS[*]}"
    ask "Install them now via $PKG_MANAGER? [y/N]:"
    if [[ "$_ans" =~ ^[Yy]$ ]]; then
        eval "$PKG_UPDATE"
        eval "$PKG_INSTALL ${NEEDED_SYS_PKGS[*]}"
        ok "System packages installed"
    else
        fail "Skipping. Install manually and re-run install.sh."
        exit 1
    fi
else
    ok "System packages present"
fi

# ----------------------------------------------------------------
# Per-host Python venv (NEVER on USB — repo carries source code,
# each host runs its own OS-correct binaries)
# ----------------------------------------------------------------
#
# Caught 2026-05-07 Pi dog-food: the Win VM's install left a Windows-
# format venv at <USB>/.venv (Scripts/, .exe binaries). When the user
# moved the USB to the Pi and ran install.sh, line 130's
# "$SCRIPT_DIR/.venv/bin/pip" failed because Linux expects bin/, not
# Scripts/. The fix is structural: the venv is per-host runtime
# (cell-specific ribosomes), not a USB-side artifact (genome). The
# USB stays platform-neutral.
#
# Aligns with project_orion-portability-validated.md which already had
# the bootstrap creating ~/.orion-runtime/<os>/ on auto-wire — first-
# time install just wasn't following the same convention.

case "$(uname -s)" in
    Darwin) RUNTIME_OS="macos" ;;
    Linux)  RUNTIME_OS="linux" ;;
    *)      RUNTIME_OS="$(uname -s | tr '[:upper:]' '[:lower:]')" ;;
esac
VENV_DIR="$HOME/.orion-runtime/$RUNTIME_OS"

# If a USB-side .venv exists from a prior install on a different OS,
# leave it alone — it's harmless on disk but we're not using it.
if [ ! -x "$VENV_DIR/bin/pip" ]; then
    info "Creating per-host venv at $VENV_DIR"
    mkdir -p "$(dirname "$VENV_DIR")"
    rm -rf "$VENV_DIR"  # Wipe any partial / wrong-OS leftover
    python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
# --quiet matches the signal-to-noise the user expects from official
# installers. Failures still surface because pip prints errors anyway.
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet
ok "Python deps installed in venv ($VENV_DIR)"

# ----------------------------------------------------------------
# Optional: Ollama (free local fuel)
# ----------------------------------------------------------------

if ! command -v ollama >/dev/null 2>&1; then
    ask "Install Ollama for free local AI fuel? [y/N]:"
    if [[ "$_ans" =~ ^[Yy]$ ]]; then
        info "Running Ollama's official installer (curl | sh)"
        curl -fsSL https://ollama.com/install.sh | sh
        ok "Ollama installed"
    fi
else
    ok "Ollama already installed"
fi

# Model selection — orion chat requires a tool-capable model.
# phi3:mini is small but doesn't reliably do tool calling, so chat mode
# won't work with it. Offer the real-capable options, warn about phi3:mini.
if command -v ollama >/dev/null 2>&1; then
    say ""
    say "  ${DIM}Orion chat needs a tool-capable model. Pick one:${RESET}"
    say "    1) qwen3:8b        ${DIM}~5 GB  — recommended, works on 8GB+ RAM${RESET}"
    say "    2) qwen3:14b       ${DIM}~9 GB  — best quality, 16GB+ RAM${RESET}"
    say "    3) llama3.1:8b     ${DIM}~5 GB  — Meta, similar size to qwen3:8b${RESET}"
    say "    4) deepseek-r1:7b  ${DIM}~4.7 GB — reasoning focus${RESET}"
    say "    5) phi3:mini       ${DIM}~2.2 GB — small, but chat mode won't work (no tool calls)${RESET}"
    say "    6) skip            ${DIM}— pull a model later with: ollama pull <name>${RESET}"
    ask "Pull which model? [1-6]:"
    case "$_ans" in
        1|"") ollama pull qwen3:8b ;;
        2)    ollama pull qwen3:14b ;;
        3)    ollama pull llama3.1:8b ;;
        4)    ollama pull deepseek-r1:7b ;;
        5)    ollama pull phi3:mini
              warn "phi3:mini installed — chat mode won't work. Pull qwen3:8b to enable chat.";;
        *)    say "  ${DIM}Skipped. Pull later with: ollama pull qwen3:8b${RESET}" ;;
    esac
fi

# ----------------------------------------------------------------
# Write bash launcher — equivalent of Windows ORION.bat
# ----------------------------------------------------------------

LAUNCHER_DIR="$HOME/.local/bin"
LAUNCHER="$LAUNCHER_DIR/orion"
mkdir -p "$LAUNCHER_DIR"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# orion launcher — created by install.sh
# Runs orion.py via the repo's venv so deps are always available.
exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/orion.py" "\$@"
EOF
chmod +x "$LAUNCHER"
ok "Launcher installed: $LAUNCHER"

# Check PATH for ~/.local/bin
if ! echo ":$PATH:" | grep -q ":$LAUNCHER_DIR:"; then
    warn "$LAUNCHER_DIR is not in your PATH."
    say "  ${DIM}Add this to your shell config (~/.bashrc, ~/.zshrc, ~/.profile):${RESET}"
    say "  ${DIM}    export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
    ask "Add it to ~/.bashrc now? [y/N]:"
    if [[ "$_ans" =~ ^[Yy]$ ]]; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
        ok "Added to ~/.bashrc — source it or open a new terminal"
    fi
fi

# ----------------------------------------------------------------
# Wake mode vs Create mode
# ----------------------------------------------------------------
# CREATE: no existing brain anywhere → run the conversational wizard
#         (proto-Orion introduces, asks identity / address / chosen
#         name / fuel, seeds brain, wires the host). This is Orion's
#         "birth" — happens once, ever, per Orion-instance.
#
# WAKE:   an existing brain is present on this drive (we're plugging
#         the same Orion into a new device he hasn't lived on yet).
#         Skip the wizard entirely — Orion already has identity, name,
#         address, history. Just wire THIS host: junction ~/.orion to
#         the drive, symlink persona files, register MCP in detected
#         CLIs, install the SessionStart hook + presence agent so
#         future plug-ins on this host auto-fire. orion_bootstrap.sh
#         is the existing script that does all of that.
#
# Caught 2026-05-07 founder feedback: "the entire install wizard runs??
# how about we make a 'Orion wake' command for when you insert the usb
# into new devices that's all you have to do." This is exactly that —
# the launch UX where new devices wake an already-existing Orion in
# seconds without re-introducing him.

BRAIN_GRAPH="$SCRIPT_DIR/.orion/brain/graph_memory.json"
USB_BRAIN_GRAPH="$(dirname "$SCRIPT_DIR")/.orion/brain/graph_memory.json"

say ""
if [ -f "$BRAIN_GRAPH" ] || [ -f "$USB_BRAIN_GRAPH" ]; then
    info "Existing Orion brain detected on this drive."
    info "Waking Orion on this device — no wizard, just wire this host up."
    say ""
    bash "$SCRIPT_DIR/orion_bootstrap.sh" --quiet --notify --usb "$SCRIPT_DIR"
elif [[ "$*" == *"--classic"* ]]; then
    info "Running classic setup wizard..."
    say ""
    "$VENV_DIR/bin/python" "$SCRIPT_DIR/setup.py"
else
    info "First-time Orion creation — running the conversational wizard."
    say ""
    "$VENV_DIR/bin/python" "$SCRIPT_DIR/orion_setup_chat.py"
fi

# ----------------------------------------------------------------
# Preflight
# ----------------------------------------------------------------

say ""
info "Running preflight health check..."
say ""
"$VENV_DIR/bin/python" "$SCRIPT_DIR/orion_preflight.py" || true

say ""
ok "Install complete."
say ""

# If ~/.local/bin isn't on the current PATH, the just-written launcher
# won't be callable by name in THIS shell — bash only loads .bashrc for
# new shells. Detect and tell the user clearly.
if ! echo ":$PATH:" | grep -q ":$HOME/.local/bin:"; then
    warn "Your current shell doesn't yet have ~/.local/bin on PATH."
    say "  ${DIM}Run one of these before 'orion chat' works by name:${RESET}"
    say "      source ~/.bashrc          ${DIM}# reload in this shell${RESET}"
    say "      exec bash -l              ${DIM}# or start a fresh login shell${RESET}"
    say "  ${DIM}Or use the full path:${RESET}  ~/.local/bin/orion chat"
    say ""
fi

say "  ${DIM}Start talking to Orion:${RESET}  orion chat"
say "  ${DIM}Re-run health check:${RESET}     python orion_preflight.py"
say ""
