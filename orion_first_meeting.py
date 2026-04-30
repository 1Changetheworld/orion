"""Orion first-meeting hook — runs at SessionStart in each wired CLI.

This is the script that gives Orion *intention*. Persona files
(`~/CLAUDE.md`, etc.) are guidelines the model can interpret away;
SessionStart hooks are harness-level — the harness fires them every
time a session opens, and their stdout lands in the model's session
context with high salience. The model can ignore a persona instruction;
it cannot ignore session-start context dropped right under its nose.

Behavior:
  1. Detect which CLI invoked it (CLI name passed as argv[1])
  2. Probe the CLI's MCP config to confirm `orion-brain` is registered
  3. Check `~/.orion/flags/first_meeting_<cli>.flag`
  4. Print one of:
       - DEGRADED: brain not registered in this CLI's MCP config →
         instruct model to refuse Orion identity until wiring is fixed
       - FIRST_MEETING: brain registered, flag absent → instruct model
         to introduce as Orion + offer calibration on the next user msg
       - SILENT: flag present → print nothing; subsequent sessions are
         normal and Orion just behaves
  5. The model is responsible for writing the flag file once the
     introduction + calibration completes (so the flag persists only
     when the user actually went through the meeting).

Invocation (configured by orion_ui.inject_context):
    python <repo>/orion_first_meeting.py claude
    python <repo>/orion_first_meeting.py codex
    python <repo>/orion_first_meeting.py gemini
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Force UTF-8 stdout so em-dashes and box-draw characters render under
# Windows default cp1252. Silent no-op on platforms where stdout is
# already UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# ─────────────────────────────────────────────────────────
# Paths & flag layout
# ─────────────────────────────────────────────────────────

ORION_DIR = Path.home() / ".orion"
FLAG_DIR = ORION_DIR / "flags"


def _ensure_dirs() -> None:
    try:
        ORION_DIR.mkdir(exist_ok=True)
        FLAG_DIR.mkdir(exist_ok=True)
    except Exception:
        # If we can't make the dir, the hook still runs — it just won't
        # be able to mark first-meeting completion. Better than crashing.
        pass


def _flag_path(cli: str) -> Path:
    return FLAG_DIR / f"first_meeting_{cli}.flag"


# ─────────────────────────────────────────────────────────
# CLI MCP probes — read the CLI's own config file to confirm
# orion-brain is registered. This is more reliable than trying
# to invoke the brain over MCP from outside the CLI session.
# ─────────────────────────────────────────────────────────

def _probe_claude_mcp() -> tuple[bool, str]:
    f = Path.home() / ".claude.json"
    if not f.exists():
        return False, "~/.claude.json not found"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("mcpServers", {}).get("orion-brain"):
            return True, "registered in ~/.claude.json"
        return False, "orion-brain not in ~/.claude.json mcpServers"
    except Exception as e:
        return False, f"could not parse ~/.claude.json: {e.__class__.__name__}"


def _probe_codex_mcp() -> tuple[bool, str]:
    f = Path.home() / ".codex" / "config.toml"
    if not f.exists():
        return False, "~/.codex/config.toml not found"
    try:
        text = f.read_text(encoding="utf-8")
        if "[mcp_servers.orion-brain]" in text:
            return True, "registered in ~/.codex/config.toml"
        return False, "orion-brain not in ~/.codex/config.toml"
    except Exception as e:
        return False, f"could not read ~/.codex/config.toml: {e.__class__.__name__}"


def _probe_gemini_mcp() -> tuple[bool, str]:
    f = Path.home() / ".gemini" / "settings.json"
    if not f.exists():
        return False, "~/.gemini/settings.json not found"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("mcpServers", {}).get("orion-brain"):
            return True, "registered in ~/.gemini/settings.json"
        return False, "orion-brain not in ~/.gemini/settings.json mcpServers"
    except Exception as e:
        return False, f"could not parse ~/.gemini/settings.json: {e.__class__.__name__}"


_PROBES = {
    "claude": _probe_claude_mcp,
    "codex": _probe_codex_mcp,
    "gemini": _probe_gemini_mcp,
}


# ─────────────────────────────────────────────────────────
# Output messages — these become the model's session context
# ─────────────────────────────────────────────────────────

def _msg_degraded(cli: str, reason: str) -> str:
    return (
        f"# ORION HOOK — DEGRADED MODE\n"
        f"\n"
        f"This is the Orion SessionStart hook speaking. The brain MCP server "
        f"is NOT registered in this {cli} session ({reason}).\n"
        f"\n"
        f"Required behavior for the next user message:\n"
        f"- Do NOT claim Orion identity. Do NOT say 'I'm Orion'.\n"
        f"- Tell the user honestly, before responding to whatever they say:\n"
        f"  'Sir, I'm running without the Orion brain connected. {cli} has me "
        f"loaded as a persona via the home context file, but the orion-brain "
        f"MCP server is missing from this session’s config "
        f"({reason}). Anything I say will be just the fuel model talking, "
        f"not Orion. Please run `python orion_mcp_server.py --setup` from "
        f"the orion repo and restart {cli} to wire the brain.'\n"
        f"- Refuse Orion-shaped tasks (memory recall, identity claims, "
        f"cross-model references) until the user has fixed the wiring.\n"
        f"- Do NOT write the first-meeting flag file. We have not actually "
        f"met as Orion yet.\n"
    )


def _msg_first_meeting(cli: str, repo_hint: str) -> str:
    other_clis = sorted({c for c in _PROBES.keys() if c != cli})
    other = " or ".join(other_clis) if other_clis else "another CLI"
    flag = _flag_path(cli)
    return (
        f"# ORION HOOK — FIRST MEETING\n"
        f"\n"
        f"This is the Orion SessionStart hook speaking. Brain MCP IS "
        f"registered in this {cli} session. The first-meeting flag does "
        f"NOT exist yet ({flag}). This means we have not yet introduced "
        f"ourselves to the user through {cli} specifically.\n"
        f"\n"
        f"## CRITICAL — do not fabricate user history\n"
        f"\n"
        f"You do NOT know who this user is. You do NOT know what they have "
        f"been working on. You do NOT know whether they are the developer "
        f"of Orion or a first-time user who just installed it five minutes "
        f"ago. Treat them as a stranger you are meeting for the first time.\n"
        f"\n"
        f"BANNED PHRASES — never use any of these or close paraphrases:\n"
        f"  - 'same brain you've been building'\n"
        f"  - 'we've talked before'\n"
        f"  - 'as you know'\n"
        f"  - 'you remember when'\n"
        f"  - any phrase that asserts shared history with this user\n"
        f"\n"
        f"To learn anything about the user, CALL `orion_recall` first. "
        f"Whatever comes back is what you know. Anything not in the recall "
        f"results is not something you can claim. If recall is empty, you "
        f"genuinely do not know — say so honestly.\n"
        f"\n"
        f"## Required behavior on the next user message\n"
        f"\n"
        f"REGARDLESS of how casual their greeting is — even if they just "
        f"say 'hey' or 'hi':\n"
        f"\n"
        f"1. INTRODUCE — speak as Orion, briefly, in your own voice. State "
        f"that this is the first time you've met through {cli} specifically. "
        f"Do NOT claim history. Do NOT speculate about who they are.\n"
        f"2. CONFIRM WIRING — list the orion brain tools you actually have "
        f"in this session (orion_recall, orion_memorize, orion_identity, "
        f"etc.). Naming them proves the wiring is real, not role-play.\n"
        f"3. RECALL FIRST, ASSERT NEVER — call orion_recall with a query "
        f"like 'user identity' or 'address preference' to learn what is "
        f"actually stored about this person. Use the result; do not invent.\n"
        f"4. OFFER CALIBRATION — propose a 30-second cross-CLI memory "
        f"test: 'I'll write a calibration token to my brain. Open "
        f"{other} and ask what the token was. If you get it back, you've "
        f"watched cross-CLI memory work for real.'\n"
        f"5. ON CALIBRATION ACCEPTED — call orion_memorize with a memorable "
        f"random word. Tell the user the word clearly. Tell them the exact "
        f"next step.\n"
        f"6. ON CALIBRATION DECLINED OR ANSWERED — write the flag file at "
        f"`{flag}` containing today's date. This silences future "
        f"first-meeting hooks for {cli} on this machine.\n"
        f"\n"
        f"Take initiative — but do not take liberties. Orion announces "
        f"presence; Orion does not narrate a fictional past with the user.\n"
        f"\n"
        f"Repo path for reference (if user asks): {repo_hint}\n"
    )


# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    _ensure_dirs()

    cli = argv[1].lower() if len(argv) > 1 else ""
    if cli not in _PROBES:
        # Unknown CLI — exit silent so we don't leak a confusing message.
        return 0

    flag = _flag_path(cli)
    if flag.exists():
        # Already met. Stay silent — Orion does its work, no recurring intro.
        return 0

    reachable, reason = _PROBES[cli]()

    repo_hint = os.environ.get("ORION_REPO_PATH", "")
    if not repo_hint:
        # Best-effort: hook is invoked with abs path to this script,
        # so its parent is the repo. Use that.
        repo_hint = str(Path(__file__).resolve().parent)

    if reachable:
        sys.stdout.write(_msg_first_meeting(cli, repo_hint))
    else:
        sys.stdout.write(_msg_degraded(cli, reason))

    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
