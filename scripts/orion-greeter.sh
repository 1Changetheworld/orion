#!/usr/bin/env bash
# orion-greeter.sh — terminal-takeover greeter for Orion-activated hosts.
#
# Sourced from ~/.bashrc on Pi (and any other Orion-activated machine).
# Shows on every interactive shell open:
#   - Identity + host role in the mesh
#   - Brain liveness (substrate ping, current memory node count)
#   - Team room (other Orion sessions active right now)
#   - 3 most-recent memorized facts (so the brain narrates its own state)
#   - Recent proactive reach outbounds (so user sees what Orion just did)
#   - `orion` command reference
#
# All checks are best-effort, non-blocking, and exit silently if the
# brain isn't reachable — never let the greeter break a login shell.
#
# Install:
#   add `source ~/.orion-bin/orion-greeter.sh` to ~/.bashrc
#   make sure ~/.orion-bin is on PATH and contains the `orion` wrapper

# ─────────────────────────────────────────────────────────
# Only run for interactive shells; skip cron / scp / non-tty contexts.
# ─────────────────────────────────────────────────────────
case $- in
    *i*) ;;
    *) return 0 2>/dev/null ;;
esac

# ─────────────────────────────────────────────────────────
# Identity + host role
# ─────────────────────────────────────────────────────────

ORION_CODE_DIR="${ORION_CODE_DIR:-$HOME/orion-code}"
ORION_DIR="${ORION_BRAIN_DIR:-$HOME/.orion}"
HOST_LABEL="$(hostname -s 2>/dev/null || echo "$HOSTNAME")"

# ANSI color helpers (degrade to plain if no tty colors)
if [ -t 1 ] && command -v tput >/dev/null 2>&1; then
    _C_RESET="$(tput sgr0)"
    _C_DIM="$(tput dim 2>/dev/null || echo)"
    _C_BOLD="$(tput bold)"
    _C_CYAN="$(tput setaf 6)"
    _C_GREEN="$(tput setaf 2)"
    _C_YELLOW="$(tput setaf 3)"
    _C_MAGENTA="$(tput setaf 5)"
else
    _C_RESET="" _C_DIM="" _C_BOLD="" _C_CYAN="" _C_GREEN="" _C_YELLOW="" _C_MAGENTA=""
fi

echo
echo "${_C_BOLD}${_C_CYAN}  ⬣ ORION  ${_C_RESET}${_C_DIM}//${_C_RESET}${_C_BOLD} ${HOST_LABEL}${_C_RESET}${_C_DIM} — the brain is yours${_C_RESET}"

# ─────────────────────────────────────────────────────────
# Brain liveness (substrate + memory)
# ─────────────────────────────────────────────────────────

if command -v nats >/dev/null 2>&1; then
    _NATS_OK="$(timeout 1 nats --server nats://127.0.0.1:4222 server check connection 2>&1 | grep -c OK)"
elif command -v curl >/dev/null 2>&1; then
    _NATS_OK="$(curl -s -m 1 http://127.0.0.1:8222/healthz 2>/dev/null | grep -c status)"
else
    _NATS_OK=0
fi
if [ "${_NATS_OK:-0}" -gt 0 ]; then
    _STATE="${_C_GREEN}● substrate alive${_C_RESET}"
else
    _STATE="${_C_YELLOW}○ substrate offline${_C_RESET}"
fi

_NODE_COUNT="?"
if [ -f "$ORION_DIR/brain/graph_memory.json" ]; then
    _NODE_COUNT="$(python3 -c "import json; print(len(json.load(open('$ORION_DIR/brain/graph_memory.json')).get('nodes', {})))" 2>/dev/null || echo "?")"
fi
echo "  ${_STATE} ${_C_DIM}//${_C_RESET} ${_C_BOLD}${_NODE_COUNT}${_C_RESET}${_C_DIM} memory nodes${_C_RESET}"

# ─────────────────────────────────────────────────────────
# Team room — other Orion sessions awake right now
# ─────────────────────────────────────────────────────────

if [ -f "$ORION_CODE_DIR/orion_team.py" ]; then
    _TEAM="$(python3 "$ORION_CODE_DIR/orion_team.py" list 2>/dev/null | grep -v '^$' | head -4)"
    if [ -n "$_TEAM" ] && ! echo "$_TEAM" | grep -q 'no active'; then
        echo "  ${_C_MAGENTA}team room:${_C_RESET}"
        echo "$_TEAM" | sed 's/^/    /'
    fi
fi

# ─────────────────────────────────────────────────────────
# 3 most-recent memorized facts (Orion narrating its own state)
# ─────────────────────────────────────────────────────────

if [ -f "$ORION_DIR/brain/graph_memory.json" ]; then
    _RECENT="$(python3 - <<'PYEOF' 2>/dev/null
import json, os
from pathlib import Path
p = Path(os.environ.get("ORION_BRAIN_DIR", str(Path.home() / ".orion"))) / "brain" / "graph_memory.json"
try:
    data = json.loads(p.read_text(encoding="utf-8"))
    nodes = sorted(
        (v for v in data.get("nodes", {}).values()
         if v.get("type") in ("project", "preference", "fact", "identity")),
        key=lambda v: v.get("created", 0),
        reverse=True,
    )[:3]
    for n in nodes:
        c = (n.get("content") or "")[:100].replace("\n", " ")
        print(f"  · {c}")
except Exception:
    pass
PYEOF
)"
    if [ -n "$_RECENT" ]; then
        echo "  ${_C_DIM}recent memories:${_C_RESET}"
        echo "$_RECENT" | sed "s/^  · /    ${_C_DIM}·${_C_RESET} /"
    fi
fi

# ─────────────────────────────────────────────────────────
# Recent proactive outbound (what Orion just did)
# ─────────────────────────────────────────────────────────

_REACH_LOG="$ORION_DIR/synthesis/reach_log.jsonl"
if [ -f "$_REACH_LOG" ]; then
    _LAST_REACH="$(tail -1 "$_REACH_LOG" 2>/dev/null | python3 -c 'import json,sys; r=json.loads(sys.stdin.read()); print(r.get("msg","")[:90])' 2>/dev/null)"
    if [ -n "$_LAST_REACH" ]; then
        echo "  ${_C_DIM}last reach:${_C_RESET} ${_LAST_REACH}"
    fi
fi

# ─────────────────────────────────────────────────────────
# Command reference (only on first prompt of session)
# ─────────────────────────────────────────────────────────

if [ -z "$ORION_GREETED" ]; then
    echo
    echo "  ${_C_DIM}commands:${_C_RESET}  ${_C_BOLD}orion${_C_RESET} (chat)   ${_C_BOLD}orion recall${_C_RESET} <q>   ${_C_BOLD}orion list${_C_RESET} (team)   ${_C_BOLD}orion status${_C_RESET}"
    export ORION_GREETED=1
fi
echo

# Clean up locals so they don't leak into the shell environment
unset _C_RESET _C_DIM _C_BOLD _C_CYAN _C_GREEN _C_YELLOW _C_MAGENTA
unset _NATS_OK _STATE _NODE_COUNT _TEAM _RECENT _REACH_LOG _LAST_REACH
unset HOST_LABEL
