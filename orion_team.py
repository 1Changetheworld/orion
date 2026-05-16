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

import atexit
import hashlib
import json
import os
import socket
import sys
import threading
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

# GC threshold — sweeper removes session files older than this. Two
# stale windows so a session that briefly misses a heartbeat (network
# blip, GC pause) isn't immediately reaped.
GC_AFTER_SEC = STALE_AFTER_SEC * 2  # 10 minutes

# Heartbeat cadence used by the background daemon thread when
# auto-team-mode is wired up. Half the stale threshold gives one
# full miss of headroom before STALE_AFTER_SEC bites.
HEARTBEAT_INTERVAL_SEC = 60


def _hostname() -> str:
    try:
        return socket.gethostname().split(".")[0]
    except Exception:
        return "unknown"


def _session_file(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)
    return TEAM_DIR / f"{safe}.json"


# ─────────────────────────────────────────────────────────
# Cross-platform CLI role detection
# Replaces the previous /proc-only path that silently fell back to
# 'ai-session' on Windows and macOS (FORGE was always 'ai-session').
# ─────────────────────────────────────────────────────────

def detect_cli_role(default: str = "ai-session") -> str:
    """Best-effort detect which AI CLI we're running under.

    Order of precedence:
      1. ORION_CLI_HINT env var (explicit override)
      2. Known per-CLI env vars (Claude Code, Codex, Gemini)
      3. /proc/PPID/comm on Linux
      4. fallback to `default`
    """
    explicit = os.environ.get("ORION_CLI_HINT", "").strip().lower()
    if explicit:
        return explicit
    env = os.environ
    if env.get("CLAUDECODE") or env.get("CLAUDE_PROJECT_DIR") \
       or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if env.get("CODEX_HOME") or env.get("CODEX_VERSION") \
       or env.get("CODEX_CONFIG_PATH"):
        return "codex"
    if env.get("GEMINI_CLI_VERSION") or env.get("GEMINI_SDK_VERSION") \
       or env.get("GEMINI_CONFIG_PATH"):
        return "gemini"
    try:
        ppid = os.getppid()
        comm = Path(f"/proc/{ppid}/comm").read_text(encoding="utf-8").strip()
        if comm:
            return comm.lower()
    except Exception:
        pass
    return default


def derive_session_id(role: str) -> str:
    """Single source of truth for stable session IDs.

    SessionStart hook AND MCP auto-announce both call this so they land
    on the same record — heartbeat from MCP refreshes the file the hook
    wrote, instead of orphaning it under a fresh uuid.

    Precedence:
      1. ORION_SESSION_ID env var (explicit override — set this when you
         want a human-readable name like 'claude-forge-build-main').
      2. sha1(project_dir)[:6] discriminator, keyed by host+role. Stable
         across MCP restarts in the same project; distinct per project.
         CLAUDE_PROJECT_DIR is preferred over cwd because it survives
         shell-driven cwd changes inside the session.
    """
    explicit = os.environ.get("ORION_SESSION_ID", "").strip()
    if explicit:
        return explicit
    host = _hostname().lower()
    project = (os.environ.get("CLAUDE_PROJECT_DIR")
               or os.environ.get("PWD")
               or os.getcwd())
    proj_hash = hashlib.sha1(project.encode("utf-8", errors="replace")).hexdigest()[:6]
    return f"{host}-{role}-{proj_hash}"


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


def gc_stale(now: Optional[float] = None,
             older_than_sec: float = GC_AFTER_SEC) -> list[dict]:
    """Sweep ~/.orion/team/ for sessions whose last_heartbeat is older
    than `older_than_sec`. Removes their files and returns the records
    that were collected (so callers can publish release events).

    Two-window default (GC_AFTER_SEC = STALE_AFTER_SEC * 2) tolerates a
    single missed heartbeat. Catches sessions that exited via SIGKILL
    or harness shutdown, where atexit never ran.
    """
    now = now if now is not None else time.time()
    swept: list[dict] = []
    if not TEAM_DIR.exists():
        return swept
    for p in TEAM_DIR.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            # Corrupt session file. Treat as garbage; remove it.
            try:
                p.unlink()
            except Exception:
                pass
            continue
        age = now - rec.get("last_heartbeat", 0)
        if age > older_than_sec:
            try:
                p.unlink()
                _publish_substrate("release", rec)
                swept.append(rec)
            except Exception:
                pass
    return swept


# ─────────────────────────────────────────────────────────
# Auto-team-mode — wire announce + heartbeat + release into a single
# call site so AI CLIs become first-class members of the team room
# without manual `python -c "..."` ceremony.
# ─────────────────────────────────────────────────────────

_auto_thread: Optional[threading.Thread] = None
_auto_session: Optional[str] = None
_auto_stop = threading.Event()


def _heartbeat_loop(session_id: str, interval: float) -> None:
    """Daemon-thread loop: refresh last_heartbeat on cadence so this
    session doesn't go stale at STALE_AFTER_SEC. Stops when the
    process exits (daemon=True) or when _auto_stop is set."""
    while not _auto_stop.is_set():
        # Sleep first so the immediate-post-announce write isn't
        # immediately overwritten by a heartbeat-only refresh; gives
        # downstream subscribers a clean first event.
        if _auto_stop.wait(interval):
            return
        try:
            heartbeat(session=session_id)
        except Exception:
            # Heartbeat is best-effort; transient failures (disk full,
            # substrate down) shouldn't kill the thread. Try again next
            # tick.
            pass


def _atexit_release() -> None:
    """Best-effort release on graceful process exit. atexit doesn't fire
    on SIGKILL; the team-sync GC sweeper handles that case."""
    sid = _auto_session
    if not sid:
        return
    try:
        _auto_stop.set()
        release(session=sid)
    except Exception:
        pass


def start_auto_mode(role: Optional[str] = None,
                    focus: str = "(idle — model just attached)",
                    session: Optional[str] = None,
                    interval: float = HEARTBEAT_INTERVAL_SEC) -> dict:
    """Idempotent one-call wiring of announce + heartbeat + release.

    Use this from any long-running Orion-attached process (MCP server,
    SessionStart hook wrapper, custom adapter) to land in the team room
    as a real member instead of a stale orphan.

    role:    if omitted, detect_cli_role() guesses from env / parent
    session: if omitted, derive_session_id(role) builds a stable name
    focus:   initial focus string; update later via update_focus()

    Returns the announced session record. Safe to call multiple times
    (subsequent calls update focus and refresh heartbeat but don't
    start a second thread).
    """
    global _auto_thread, _auto_session
    role = role or detect_cli_role()
    sid = session or derive_session_id(role)

    # Idempotent: if already auto-managed under the same session, just
    # refresh focus and return. New session ID under same auto-mode is
    # treated as a re-announce — release the old, start fresh.
    if _auto_session and _auto_session != sid:
        try:
            release(session=_auto_session)
        except Exception:
            pass
        _auto_session = None

    rec = announce(role=role, session=sid, focus=focus)
    _auto_session = sid

    if _auto_thread is None or not _auto_thread.is_alive():
        _auto_stop.clear()
        _auto_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(sid, interval),
            name=f"orion-team-heartbeat-{sid[:24]}",
            daemon=True,
        )
        _auto_thread.start()
        # atexit fires on graceful interpreter shutdown only. SIGKILL
        # bypasses it — that gap is covered by the team-sync GC sweeper.
        atexit.register(_atexit_release)

    return rec


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
    sub.add_parser("gc", help="sweep stale session files older than GC_AFTER_SEC")
    sub.add_parser("derive", help="print the derived session ID + role for this process")

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
    if args.cmd == "gc":
        swept = gc_stale()
        if not swept:
            print("(no stale sessions)")
            return 0
        for rec in swept:
            print(f"reaped {rec.get('session_id')} "
                  f"(role={rec.get('role')}, host={rec.get('host')})")
        return 0
    if args.cmd == "derive":
        role = detect_cli_role()
        sid = derive_session_id(role)
        print(f"role={role}")
        print(f"session_id={sid}")
        return 0


if __name__ == "__main__":
    sys.exit(_cli())
