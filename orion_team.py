"""orion_team.py — multi-terminal Orion coordination.

Founder pain 2026-05-15: 'I have 3 terminals — one on Pi, one for
marketing, one for building. They're teammates in the same room, but
none of them knows what the others are doing. The irony is that Orion
exists to solve exactly this kind of coordination.'

This module makes that not-true. Every Orion CLI session that imports
this announces itself + heartbeats its current focus. Any session can
call list_active() to see who else is awake and what they're touching.

Storage layer: piggybacks on the existing memorize/recall infrastructure.
Active sessions are 'ephemeral' typed memories tagged 'active-session'
with a heartbeat timestamp. Stale sessions (>5 min since heartbeat)
are filtered out at list time. No new schema; works through gossip
so all hosts see the same team room.

Usage from any Orion CLI session:

    import orion_team as team
    team.announce("building", session="claude-forge-build",
                  focus="orion_reach MCP tool")
    # ... do work ...
    team.update_focus("testing orion_reach with Gemini")
    # ... finish ...
    team.release()

From the SessionStart hook, list_active() prints the team room so the
model sees teammates the moment a session opens. No 'what is the other
Claude doing' confusion ever again.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# Where active-session entries live. JSONL, one record per heartbeat.
# Lives in the local brain dir; gossip layer replicates cross-host.
TEAM_DIR = Path(os.environ.get("ORION_BRAIN_DIR")
                or str(Path.home() / ".orion")) / "team"
TEAM_DIR.mkdir(parents=True, exist_ok=True)

# Stale threshold — sessions whose last heartbeat is older than this
# are considered offline, not actively in the team room.
STALE_AFTER_SEC = 300  # 5 minutes


def _hostname() -> str:
    try:
        return socket.gethostname().split(".")[0]
    except Exception:
        return "unknown"


def _session_file(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)
    return TEAM_DIR / f"{safe}.json"


# ─────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────

def _publish_substrate(event: str, rec: dict) -> None:
    """Publish to the NATS substrate so other hosts see the event.
    Best-effort — silent no-op if substrate unreachable."""
    try:
        from orion_substrate import publish
        publish(f"orion.team.{event}", rec)
    except Exception:
        pass


def announce(role: str,
             session: Optional[str] = None,
             focus: str = "",
             host: Optional[str] = None) -> dict:
    """Announce this Orion session to the team room.

    role:    short label — 'building' / 'marketing' / 'pi-ops' / ...
    session: stable session ID. If not provided, a host+pid+random one
             is generated and saved for the duration of the process.
    focus:   what you're working on right now (1 sentence).
    host:    override hostname. Defaults to socket.gethostname().

    Returns the session record dict (with id + timestamp).
    """
    sid = session or f"{_hostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    rec = {
        "session_id": sid,
        "role": role,
        "focus": focus,
        "host": host or _hostname(),
        "pid": os.getpid(),
        "announced_at": time.time(),
        "last_heartbeat": time.time(),
    }
    _session_file(sid).write_text(json.dumps(rec, indent=2), encoding="utf-8")
    _publish_substrate("announce", rec)
    return rec


def update_focus(focus: str, session: Optional[str] = None) -> bool:
    """Update what this session is currently working on."""
    sid = session or _find_my_session()
    if not sid:
        return False
    p = _session_file(sid)
    if not p.exists():
        return False
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["focus"] = focus
        rec["last_heartbeat"] = time.time()
        p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        _publish_substrate("update", rec)
        return True
    except Exception:
        return False


def heartbeat(session: Optional[str] = None) -> bool:
    """Refresh this session's last_heartbeat. Call periodically (~60s)."""
    sid = session or _find_my_session()
    if not sid:
        return False
    p = _session_file(sid)
    if not p.exists():
        return False
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["last_heartbeat"] = time.time()
        p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        _publish_substrate("heartbeat", rec)
        return True
    except Exception:
        return False


def release(session: Optional[str] = None) -> bool:
    """Mark this session as offline. Removes the file."""
    sid = session or _find_my_session()
    if not sid:
        return False
    p = _session_file(sid)
    if p.exists():
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            rec = {"session_id": sid}
        try:
            p.unlink()
            _publish_substrate("release", rec)
            return True
        except Exception:
            return False
    return False


def list_active(include_stale: bool = False) -> list[dict]:
    """Return every session that has heartbeated within STALE_AFTER_SEC.

    include_stale: also include older sessions (useful for diagnostics).
    """
    now = time.time()
    out = []
    if not TEAM_DIR.exists():
        return out
    for p in TEAM_DIR.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        age = now - rec.get("last_heartbeat", 0)
        if not include_stale and age > STALE_AFTER_SEC:
            continue
        rec["age_seconds"] = int(age)
        out.append(rec)
    out.sort(key=lambda r: r.get("last_heartbeat", 0), reverse=True)
    return out


def format_team_room(sessions: Optional[list[dict]] = None) -> str:
    """Render a human-readable team-room summary for the SessionStart hook.

    Example output:
      ## Active Orion sessions (the team room)

        - building   forge   2 min ago  — wiring orion_reach MCP tool
        - marketing  forge   8 min ago  — drafting Show HN copy
        - pi-ops     orions-home  just now  — testing Meshtastic bridge
    """
    sessions = sessions if sessions is not None else list_active()
    if not sessions:
        return ""
    lines = ["## Active Orion sessions (the team room)", ""]
    for s in sessions:
        age = s.get("age_seconds", 0)
        if age < 30:
            age_s = "just now"
        elif age < 120:
            age_s = "1 min ago"
        elif age < 3600:
            age_s = f"{age // 60} min ago"
        else:
            age_s = f"{age // 3600}h ago"
        role = s.get("role", "?")
        host = s.get("host", "?")
        focus = s.get("focus", "(idle)")
        lines.append(f"- **{role}** on {host}, {age_s} — {focus}")
    lines.append("")
    lines.append("If your work overlaps with anyone above, coordinate via "
                 "brain memorize before duplicating effort.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────

_MY_SESSION: Optional[str] = None


def _find_my_session() -> Optional[str]:
    """Best-effort identify this process's session ID by matching pid."""
    global _MY_SESSION
    if _MY_SESSION:
        return _MY_SESSION
    pid = os.getpid()
    for p in TEAM_DIR.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if rec.get("pid") == pid:
            _MY_SESSION = rec["session_id"]
            return _MY_SESSION
    return None


# ─────────────────────────────────────────────────────────
# CLI (for diagnostics)
# ─────────────────────────────────────────────────────────

def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="Orion team-room utilities")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="show active sessions")
    p_ann = sub.add_parser("announce", help="manually announce a session")
    p_ann.add_argument("--role", required=True)
    p_ann.add_argument("--focus", default="")
    p_ann.add_argument("--session")
    p_upd = sub.add_parser("update", help="update focus")
    p_upd.add_argument("--focus", required=True)
    p_upd.add_argument("--session")
    p_rel = sub.add_parser("release", help="mark session offline")
    p_rel.add_argument("--session")

    args = ap.parse_args()
    if args.cmd == "list" or args.cmd is None:
        sessions = list_active()
        if not sessions:
            print("(no active Orion sessions)")
            return 0
        print(format_team_room(sessions))
        return 0
    if args.cmd == "announce":
        rec = announce(args.role, session=args.session, focus=args.focus)
        print(f"announced: {rec['session_id']}")
        return 0
    if args.cmd == "update":
        ok = update_focus(args.focus, session=args.session)
        print("updated" if ok else "no matching session")
        return 0
    if args.cmd == "release":
        ok = release(session=args.session)
        print("released" if ok else "nothing to release")
        return 0


if __name__ == "__main__":
    sys.exit(_cli())
