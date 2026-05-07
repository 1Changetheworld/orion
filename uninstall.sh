#!/usr/bin/env bash
# orion uninstall — cleanly remove Orion from a Linux / macOS / Pi host.
#
# What this DOES remove:
#   - Brain data:  ~/.orion/
#   - Launcher:    ~/.local/bin/orion
#   - Context files: ORION-CONTEXT.md, AGENTS.md, CLAUDE.md, GEMINI.md
#     at $HOME and in ~/.codex, ~/.claude, ~/.gemini
#   - MCP config entries named `orion-brain` in:
#       ~/.codex/config.toml
#       ~/.codex/mcp.json
#       ~/.claude/settings.json
#       ~/.gemini/settings.json  (if present)
#   - The cloned repo directory (only if you confirm)
#
# What this DOES NOT remove:
#   - Ollama (you installed it, you own it — keep it or remove via ollama itself)
#   - Any AI CLI tool (codex, gemini, claude code)
#   - Python, pip, system packages
#   - Anything else on your machine
#
# Usage:
#   bash uninstall.sh              # interactive — asks before removing the repo
#   bash uninstall.sh --yes        # no prompts, full cleanup, removes repo too
#   bash uninstall.sh --keep-repo  # removes brain + configs but leaves the repo
#
# Safe to run even if some parts were never installed. Missing files are skipped
# silently.

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; DIM='\033[2m'; RESET='\033[0m'
say()   { printf "%b\n" "$*"; }
info()  { printf "${CYAN}%s${RESET}\n" "$*"; }
ok()    { printf "${GREEN}✓${RESET}  %s\n" "$*"; }
warn()  { printf "${YELLOW}!${RESET}  %s\n" "$*"; }
fail()  { printf "${RED}✗${RESET}  %s\n" "$*" >&2; }
ask()   { read -r -p "$(printf "${CYAN}?${RESET}  %s " "$*")" _ans; }

YES=0; KEEP_REPO=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y)    YES=1 ;;
        --keep-repo) KEEP_REPO=1 ;;
        -h|--help)   sed -n '2,30p' "$0"; exit 0 ;;
        *)           warn "Unknown flag: $arg" ;;
    esac
done

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

say ""
info "Orion uninstall"
say "  ${DIM}Working on:${RESET}  $(uname -s) / $(uname -m)"
say "  ${DIM}Home:${RESET}        $HOME"
say ""

# ----------------------------------------------------------------
# 1. Brain data  —  ~/.orion/
# ----------------------------------------------------------------

if [ -d "$HOME/.orion" ]; then
    SIZE=$(du -sh "$HOME/.orion" 2>/dev/null | cut -f1 || echo "?")
    if [ "$YES" -eq 1 ]; then
        rm -rf "$HOME/.orion"
        ok "Removed brain data at ~/.orion ($SIZE)"
    else
        ask "Remove ~/.orion (brain memory, $SIZE)? [y/N]:"
        if [[ "$_ans" =~ ^[Yy]$ ]]; then
            rm -rf "$HOME/.orion"
            ok "Removed ~/.orion"
        else
            warn "Kept ~/.orion — your brain data remains"
        fi
    fi
else
    say "  ${DIM}(no ~/.orion — skipping)${RESET}"
fi

# ----------------------------------------------------------------
# 2. Launcher  —  ~/.local/bin/orion
# ----------------------------------------------------------------

LAUNCHER="$HOME/.local/bin/orion"
if [ -f "$LAUNCHER" ]; then
    rm -f "$LAUNCHER"
    ok "Removed launcher: $LAUNCHER"
else
    say "  ${DIM}(no launcher — skipping)${RESET}"
fi

# ----------------------------------------------------------------
# 3. Context files (home + per-CLI dirs)
# ----------------------------------------------------------------

CTX_PATHS=(
    "$HOME/ORION-CONTEXT.md"
    "$HOME/AGENTS.md"
    "$HOME/.codex/AGENTS.md"
    "$HOME/CLAUDE.md"
    "$HOME/.claude/CLAUDE.md"
    "$HOME/GEMINI.md"
    "$HOME/.gemini/GEMINI.md"
)

CTX_REMOVED=0
for p in "${CTX_PATHS[@]}"; do
    if [ -f "$p" ]; then
        # Only remove if it looks like an Orion-written context file.
        # Orion's file starts with "# Orion — IDENTITY OVERRIDE".
        if grep -q "Orion — IDENTITY OVERRIDE" "$p" 2>/dev/null; then
            rm -f "$p"
            CTX_REMOVED=$((CTX_REMOVED+1))
        else
            warn "Left $p alone — doesn't look Orion-written"
        fi
    fi
done

if [ "$CTX_REMOVED" -gt 0 ]; then
    ok "Removed $CTX_REMOVED context file(s)"
else
    say "  ${DIM}(no Orion context files found)${RESET}"
fi

# ----------------------------------------------------------------
# 4. MCP server entries (orion-brain) — surgical removal
# ----------------------------------------------------------------
#
# We parse each known config and remove only the orion-brain entry.
# If Python3 isn't available we fall back to cruder sed surgery.

_strip_orion_mcp_via_python() {
    local file="$1"
    local kind="$2"  # 'toml' | 'json'
    python3 - "$file" "$kind" <<'PY' 2>/dev/null || return 1
import sys, json, pathlib, re

file = pathlib.Path(sys.argv[1])
kind = sys.argv[2]

if not file.exists():
    sys.exit(0)

if kind == "json":
    try:
        data = json.loads(file.read_text())
    except Exception:
        sys.exit(1)
    changed = False
    # Common shapes: {"mcpServers": {"orion-brain": {...}}}
    for key in ("mcpServers", "mcp_servers"):
        if key in data and isinstance(data[key], dict) and "orion-brain" in data[key]:
            del data[key]["orion-brain"]
            changed = True
            # If that emptied the dict and the whole file was just orion, delete
            if not data[key]:
                del data[key]
    if changed:
        if data:
            file.write_text(json.dumps(data, indent=2))
        else:
            file.unlink()
        print("changed")

elif kind == "toml":
    # Walk line-by-line. Any section whose key is [mcp_servers.orion-brain]
    # OR [mcp_servers.orion-brain.<anything>] is skipped until we hit a
    # section header that is NOT under that tree.
    lines = file.read_text().splitlines(keepends=True)
    out = []
    skipping = False
    header_re = re.compile(r"^\[([^\]]+)\]")
    orion_re  = re.compile(r"^mcp_servers\.orion-brain(\.|$)")
    for line in lines:
        m = header_re.match(line)
        if m:
            skipping = bool(orion_re.match(m.group(1)))
            if skipping:
                continue
        if skipping:
            continue
        out.append(line)
    new_text = "".join(out)
    new_text = re.sub(r"\n{3,}", "\n\n", new_text).rstrip() + "\n" if new_text.strip() else ""
    if new_text != file.read_text():
        if new_text.strip():
            file.write_text(new_text)
        else:
            file.unlink()
        print("changed")
PY
}

_removed_any_mcp=0

# Codex — config.toml
if [ -f "$HOME/.codex/config.toml" ]; then
    if out=$(_strip_orion_mcp_via_python "$HOME/.codex/config.toml" toml); then
        if [ "$out" = "changed" ]; then
            ok "Cleaned orion-brain from ~/.codex/config.toml"
            _removed_any_mcp=1
        fi
    fi
fi

# Codex — mcp.json (forward-compat file)
if [ -f "$HOME/.codex/mcp.json" ]; then
    if out=$(_strip_orion_mcp_via_python "$HOME/.codex/mcp.json" json); then
        if [ "$out" = "changed" ]; then
            ok "Cleaned orion-brain from ~/.codex/mcp.json"
            _removed_any_mcp=1
        fi
    fi
fi

# Claude Code — settings.json
if [ -f "$HOME/.claude/settings.json" ]; then
    if out=$(_strip_orion_mcp_via_python "$HOME/.claude/settings.json" json); then
        if [ "$out" = "changed" ]; then
            ok "Cleaned orion-brain from ~/.claude/settings.json"
            _removed_any_mcp=1
        fi
    fi
fi

# Gemini — settings.json
if [ -f "$HOME/.gemini/settings.json" ]; then
    if out=$(_strip_orion_mcp_via_python "$HOME/.gemini/settings.json" json); then
        if [ "$out" = "changed" ]; then
            ok "Cleaned orion-brain from ~/.gemini/settings.json"
            _removed_any_mcp=1
        fi
    fi
fi

if [ "$_removed_any_mcp" -eq 0 ]; then
    say "  ${DIM}(no orion-brain MCP entries found — already clean)${RESET}"
fi

# ----------------------------------------------------------------
# 5. Repo directory
# ----------------------------------------------------------------

# Only offer to remove the repo if uninstall.sh is running from inside a
# clone that contains the expected Orion files. We don't want to nuke
# a random directory.

IS_ORION_REPO=0
if [ -f "$SCRIPT_DIR/orion_mcp_server.py" ] && [ -f "$SCRIPT_DIR/orion_setup_chat.py" ]; then
    IS_ORION_REPO=1
fi

if [ "$KEEP_REPO" -eq 1 ]; then
    say "  ${DIM}(--keep-repo — leaving repo in place at $SCRIPT_DIR)${RESET}"
elif [ "$IS_ORION_REPO" -eq 1 ]; then
    SIZE=$(du -sh "$SCRIPT_DIR" 2>/dev/null | cut -f1 || echo "?")
    if [ "$YES" -eq 1 ]; then
        PARENT=$(dirname "$SCRIPT_DIR")
        cd "$PARENT"
        rm -rf "$SCRIPT_DIR"
        ok "Removed repo at $SCRIPT_DIR ($SIZE)"
    else
        say ""
        warn "Repo lives at: $SCRIPT_DIR ($SIZE)"
        say "  ${DIM}Including the venv at $SCRIPT_DIR/.venv and this uninstall.sh itself.${RESET}"
        ask "Remove the repo? [y/N]:"
        if [[ "$_ans" =~ ^[Yy]$ ]]; then
            PARENT=$(dirname "$SCRIPT_DIR")
            cd "$PARENT"
            rm -rf "$SCRIPT_DIR"
            ok "Removed $SCRIPT_DIR"
        else
            say "  ${DIM}(repo preserved)${RESET}"
        fi
    fi
else
    warn "Running from outside an Orion repo — not touching any directory."
fi

# ----------------------------------------------------------------
# Done
# ----------------------------------------------------------------

say ""
ok "Uninstall complete."
say ""
say "  ${DIM}Not removed (intentionally):${RESET}"
say "    - Ollama:         remove with the Ollama uninstaller if you want"
say "    - ~/.bashrc PATH: the '~/.local/bin' line (harmless, many tools use it)"
say "    - AI CLIs:        codex / gemini / claude — still installed"
say ""
say "  ${DIM}To reinstall Orion later:${RESET}"
say "      git clone https://github.com/1Changetheworld/orion.git"
say "      cd orion && bash install.sh"
say ""
