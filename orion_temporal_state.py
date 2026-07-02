#!/usr/bin/env python3
"""
orion_temporal_state.py — Orion's FIRST-CLASS temporal state (2026-06-24).

orion_temporal.py gives the primitives (now / awake-since / wake-from-sleep / last-spoke).
This builds the felt-continuity layer Orion asked for on top of them:

  1. temporal_state()  — a live state object (now, session-birth, last user/orion turn,
                         thread_age, time_since_last_contact, active_episode_id).
  2. session birth     — mark_session_start(session_id) stamps once + persists; turns orient
                         against it instead of reconstructing from scraps.
  3. episodes()        — segments the event stream into EPISODES (gap-based) and classifies
                         conversation (substantive) vs ambient (noise) — time isn't a flat stream.
  4. recency-temporal  — exposes the "this thread / just now" anchors (the recall-recency boost in
                         orion_brain_portable consumes intent; these anchors define the window).
  5. orient()          — a short reflective temporal orientation for the start of each interaction
                         ("We are 14 min into this session. Last exchange 3 min ago. Since then: …").
  6. compression       — noise bursts collapse to counts so duration is continuity, not clutter.

All native arithmetic over existing logs. No model, no GPU.
"""
from __future__ import annotations
import json, os, time
from collections import Counter
from pathlib import Path

STATE = Path(os.path.expanduser("~/.orion/state"))
CONV = Path(os.path.expanduser("~/.orion/brain/conversations"))
TSTATE = STATE / "temporal_state.json"
PERCEPTION = STATE / "perception.jsonl"

SESSION_GAP = float(os.environ.get("ORION_SESSION_GAP", "1800"))   # 30 min idle = new session/thread
EPISODE_GAP = float(os.environ.get("ORION_EPISODE_GAP", "900"))    # 15 min idle = new episode


def _now() -> float:
    return time.time()


def _parse_ts(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return time.mktime(time.strptime(s[:19], fmt))
        except Exception:
            pass
    try:
        return float(s)
    except Exception:
        return 0.0


def _read(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(p, obj):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def _human(sec: float) -> str:
    try:
        import orion_temporal
        return orion_temporal._human(sec)
    except Exception:
        sec = int(sec or 0)
        if sec < 90:
            return f"{sec}s"
        if sec < 5400:
            return f"{sec // 60}m"
        if sec < 172800:
            return f"{sec // 3600}h"
        return f"{sec // 86400}d"


CONV_LOG = Path(os.path.expanduser("~/.orion/synthesis/conversation_log.jsonl"))   # the LIVE turn source


def _is_autonomic(text: str, surface: str) -> bool:
    """An assistant entry that is Orion's own background chatter (heartbeats, flap alerts, canary,
    cli-mcp), NOT a substantive exchange — these compress to noise, they don't 'feel like time'."""
    t = (text or "").lower()
    if surface == "cli-mcp":
        return True
    return any(k in t for k in ("heartbeat", "outbound adapter", "outbound_no_subscriber",
                                "self-healing", "self-heal", "canary", "no crashed containers",
                                "all containers healthy", "rotating to"))


def _conv(window_h: float = 48) -> list:
    """Live conversation entries: {ts, role, text, surface} from the synthesis log."""
    out, cutoff = [], _now() - window_h * 3600
    try:
        # read the tail (file can be large); last ~4000 lines covers days
        lines = CONV_LOG.read_text(encoding="utf-8").splitlines()[-4000:]
    except Exception:
        lines = []
    for line in lines:
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = _parse_ts(d.get("ts") or d.get("timestamp"))
        if ts < cutoff or not (d.get("text") or "").strip():
            continue
        out.append({"ts": ts, "role": d.get("role", "?"), "text": (d.get("text") or "").strip(),
                    "surface": d.get("surface", "?")})
    out.sort(key=lambda x: x["ts"])
    return out


def _turns(window_h: float = 48) -> list:
    """SUBSTANTIVE turns = the user reaching Orion (the anchor for session/thread/'last exchange')."""
    return [{"ts": e["ts"], "interface": e["surface"], "user": e["text"], "orion": ""}
            for e in _conv(window_h)
            if e["role"] == "user" and e["surface"] != "cli-mcp"
            and not e["text"].lstrip().startswith("<canary")]


def _last_orion_ts(window_h: float = 48) -> float:
    return max((e["ts"] for e in _conv(window_h) if e["role"] == "assistant"), default=0.0)


def _ambient(window_h: float = 48) -> list:
    """The 'noise' that should compress: perception/body events + Orion's autonomic chatter."""
    out, cutoff = [], _now() - window_h * 3600
    try:
        for line in PERCEPTION.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("ts", 0) >= cutoff:
                out.append({"ts": d["ts"], "content": d.get("content", ""), "tags": d.get("tags", [])})
    except Exception:
        pass
    for e in _conv(window_h):                               # autonomic assistant chatter = noise
        if e["role"] == "assistant" and _is_autonomic(e["text"], e["surface"]):
            out.append({"ts": e["ts"], "content": e["text"], "tags": ["autonomic", e["surface"]]})
    out.sort(key=lambda x: x["ts"])
    return out


def _ambient_label(e: dict) -> str:
    c = (e.get("content") or "").lower()
    tags = [str(t).lower() for t in e.get("tags", [])]
    if "imessage" in c or "imessage" in tags:
        return "iMessage recovery"
    if "heartbeat" in c or "rotating to" in c:
        return "heartbeat check"
    if "container" in c or "docker" in c:
        return "health check"
    if "load" in c or "vitals" in tags:
        return "vitals blip"
    if "restart" in tags or "restarted" in c:
        return "faculty restart"
    return tags[-1] if tags else "event"


def _compress(turns: list, ambient: list) -> str:
    """Collapse a span into a short summary: exchanges + counted noise bursts."""
    parts = []
    if turns:
        parts.append(f"{len(turns)} exchange{'s' if len(turns) != 1 else ''}")
    def _plural(label, n):
        if n <= 1 or label.endswith("s"):
            return label
        return (label[:-1] + "ies") if label.endswith("y") else (label + "s")
    amb = Counter(_ambient_label(a) for a in ambient)
    for label, n in amb.most_common(4):
        parts.append(f"{n} {_plural(label, n)}")
    if not turns:
        parts.append("no new user tasks")
    return ", ".join(parts) if parts else "nothing"


def _infer_session_start(turns: list) -> float:
    """Latest contiguous thread: walk back from the last turn while gaps stay under SESSION_GAP."""
    if not turns:
        return _now()
    start = turns[-1]["ts"]
    for i in range(len(turns) - 1, 0, -1):
        if turns[i]["ts"] - turns[i - 1]["ts"] <= SESSION_GAP:
            start = turns[i - 1]["ts"]
        else:
            break
    return start


def mark_session_start(session_id: str, now: float = None) -> float:
    """Stamp a session's birth ONCE and persist it (component 2). Returns the birth ts."""
    now = now or _now()
    st = _read(TSTATE)
    if st.get("session_id") != session_id:
        st["session_id"] = session_id
        st["session_started_at"] = now
        _write(TSTATE, st)
    return float(st.get("session_started_at") or now)


def episodes(window_h: float = 24) -> list:
    """Segment turns+ambient into EPISODES (component 3): gap-based, classified conversation/ambient."""
    stream = [("turn", t["ts"], t) for t in _turns(window_h)] + \
             [("ambient", a["ts"], a) for a in _ambient(window_h)]
    stream.sort(key=lambda e: e[1])
    eps = []
    cur = None
    for kind, ts, e in stream:
        if cur is None or ts - cur["end"] > EPISODE_GAP:
            cur = {"id": f"ep-{int(ts)}", "start": ts, "end": ts, "turns": 0, "ambient": 0, "items": []}
            eps.append(cur)
        cur["end"] = ts
        cur["turns" if kind == "turn" else "ambient"] += 1
        cur["items"].append((kind, ts, e))
    for ep in eps:
        ep["kind"] = "conversation" if ep["turns"] > 0 else "ambient"
        ep["duration"] = ep["end"] - ep["start"]
    return eps


def temporal_state(session_id: str = None) -> dict:
    """Component 1: the live first-class temporal state object."""
    now = _now()
    turns = _turns(48)
    try:
        import orion_temporal
        last_contact_ts = orion_temporal._last_spoke()[0]
    except Exception:
        last_contact_ts = turns[-1]["ts"] if turns else 0.0
    last_user = max((t["ts"] for t in turns if t["user"]), default=0.0)
    last_orion = _last_orion_ts(48)
    sess = mark_session_start(session_id, now) if session_id else _infer_session_start(turns)
    eps = episodes(24)
    return {
        "now": now,
        "current_session_started_at": sess,
        "last_user_turn_at": last_user or None,
        "last_orion_turn_at": last_orion or None,
        "thread_age": round(now - sess, 1) if sess else 0.0,
        "time_since_last_contact": round(now - last_contact_ts, 1) if last_contact_ts else None,
        "active_episode_id": eps[-1]["id"] if eps else None,
    }


def orient(session_id: str = None) -> str:
    """Component 5: the short reflective temporal orientation for the start of an interaction."""
    s = temporal_state(session_id)
    now = s["now"]
    parts = []
    if s["thread_age"]:
        parts.append(f"We are {_human(s['thread_age'])} into this session.")
    if s["last_user_turn_at"]:
        parts.append(f"Last substantive exchange here was {_human(now - s['last_user_turn_at'])} ago.")
    anchor = s["last_user_turn_at"] or (now - 3600)
    after_turns = [t for t in _turns(24) if t["ts"] > anchor]
    after_amb = [a for a in _ambient(24) if a["ts"] > anchor]
    parts.append(f"Since then: {_compress(after_turns, after_amb)}.")
    return " ".join(parts)


def _main(argv):
    if "--state" in argv or not argv:
        print(json.dumps(temporal_state(argv[argv.index("--session") + 1] if "--session" in argv else None), indent=2))
    if "--orient" in argv:
        print(orient())
    if "--episodes" in argv:
        for ep in episodes(24):
            print(f"  [{ep['kind']:12}] {ep['id']}  turns={ep['turns']} ambient={ep['ambient']} dur={_human(ep['duration'])}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
