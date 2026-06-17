#!/usr/bin/env python3
"""orion_conversation_sync.py — two-sided conversation capture across all CLIs.

Tails each CLI's own session transcript — the source of truth for what was
actually said — and records BOTH the user's prompts AND Orion's replies into one
unified, surface-attributed conversation log. This is what gives "one Orion
across windows" real two-sided recollection: not just what you asked, but what
Orion answered, visible from every other window in real time.

Why a tailer (not hooks) for this: the transcripts are written by the CLIs
themselves, so capture does NOT depend on a hook firing or being wired right.
Adaptive by design — add a parser to support a new CLI; any line that doesn't
parse is skipped, never crashes. This is a design hurdle engineered away, not
flagged. (James, 2026-06-07: "set this up to where it is adaptive and impossible
to see issues like this in the future.")

Writes  ~/.orion/synthesis/conversation_log.jsonl
        {surface, role: user|assistant, text, ts, iso}
State   ~/.orion/synthesis/convsync_state.json   {filepath: byte_offset}

Run:    python orion_conversation_sync.py           # daemon
        python orion_conversation_sync.py --test    # parse-check, no daemon
"""
from __future__ import annotations

import datetime
import glob as _glob
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

SYNTH = Path(os.path.expanduser(os.environ.get("ORION_SYNTH_DIR", "~/.orion/synthesis")))
CONV_LOG = SYNTH / "conversation_log.jsonl"
STATE = SYNTH / "convsync_state.json"
RESUME_LOG = SYNTH / "session_resume.jsonl"   # capture-on-close: "where we left off"
POLL = float(os.environ.get("ORION_CONVSYNC_POLL", "4"))
MAXTEXT = int(os.environ.get("ORION_CONVSYNC_MAXTEXT", "400"))
ACTIVE_WINDOW = float(os.environ.get("ORION_CONVSYNC_ACTIVE_SEC", "86400"))  # tail only recently-touched files
# Capture-on-close: when a session's transcript goes quiet for this long, treat
# it as closed and write a resume marker so any window can pick the thread back
# up. This is the hippocampal "the session ended, remember it" write — cheap,
# no model needed, guaranteed even if the CLI never fires a close hook.
IDLE_CLOSE_SEC = float(os.environ.get("ORION_CONVSYNC_IDLE_CLOSE_SEC", "300"))
# in-memory per-file activity: fp -> {surface, last_ts, count, recent[], closed}
_activity = {}
_stop = threading.Event()


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _ts_of(d):
    t = d.get("timestamp")
    if isinstance(t, str):
        try:
            return datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        except Exception:
            return time.time()
    if isinstance(t, (int, float)):
        return float(t)
    return time.time()


def _text_from_content(content):
    """Pull human text out of a string or a list of content blocks; ignore
    tool_use / non-text blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text") \
                    and b.get("text"):
                parts.append(b["text"])
        return " ".join(parts)
    return ""


# ── per-CLI parsers: line dict -> (role, text, ts) or None ──

def parse_claude(d):
    m = d.get("message")
    if not isinstance(m, dict):
        return None
    role = m.get("role")
    if role not in ("user", "assistant"):
        return None
    text = _text_from_content(m.get("content"))
    return (role, text, _ts_of(d)) if text.strip() else None


def parse_gemini(d):
    t = d.get("type")
    if t == "user":
        role = "user"
    elif t in ("gemini", "assistant", "model"):
        role = "assistant"
    else:
        return None
    text = d.get("content")
    if not isinstance(text, str):
        text = _text_from_content(text)
    return (role, text or "", _ts_of(d)) if (text or "").strip() else None


def parse_codex(d):
    if d.get("type") != "response_item":
        return None
    p = d.get("payload") or {}
    if p.get("type") != "message":
        return None
    role = p.get("role")
    if role not in ("user", "assistant"):
        return None  # 'developer'/'system' skipped
    text = _text_from_content(p.get("content"))
    # codex wraps system/permission instructions in <...> input_text blocks
    if text.strip().startswith("<"):
        return None
    return (role, text, _ts_of(d)) if text.strip() else None


SURFACES = [
    ("claude", os.path.expanduser("~/.claude/projects/*/*.jsonl"), parse_claude),
    ("gemini", os.path.expanduser("~/.gemini/tmp/*/chats/*.jsonl"), parse_gemini),
    ("codex",  os.path.expanduser("~/.codex/sessions/*/*/*/*.jsonl"), parse_codex),
]


def _load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(s):
    try:
        SYNTH.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(s), encoding="utf-8")
        os.replace(str(tmp), str(STATE))
    except Exception:
        pass


_write_lock = threading.Lock()


def _append(surface, role, text, ts):
    rec = {"surface": surface, "role": role, "text": text[:MAXTEXT],
           "ts": ts, "iso": _iso(ts)}
    with _write_lock:
        with CONV_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def _tick(state):
    now = time.time()
    for surface, pattern, parser in SURFACES:
        for fp in _glob.glob(pattern):
            try:
                st = os.stat(fp)
            except Exception:
                continue
            if (now - st.st_mtime) > ACTIVE_WINDOW:
                continue
            off = state.get(fp)
            if off is None:
                # first sighting → start at EOF so we capture only new turns,
                # not the whole history. (Backfill is out of scope; recent
                # conversation is what cross-window awareness needs.)
                state[fp] = st.st_size
                continue
            if st.st_size < off:  # rotated / truncated
                off = 0
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(off)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                        except Exception:
                            continue
                        try:
                            r = parser(d)
                        except Exception:
                            r = None
                        if r:
                            role, text, ts = r
                            _append(surface, role, text, ts)
                            _note_activity(fp, surface, role, text, now)
                    state[fp] = f.tell()
            except Exception:
                continue
    _check_closes(now)
    _save_state(state)


def _note_activity(fp, surface, role, text, now):
    """Track per-session activity so we can detect when a session goes quiet."""
    a = _activity.get(fp)
    if a is None:
        a = {"surface": surface, "last_ts": now, "count": 0, "recent": [], "closed": False}
        _activity[fp] = a
    a["last_ts"] = now
    a["count"] += 1
    a["closed"] = False  # new activity reopens the session
    a["recent"].append({"role": role, "text": text[:200]})
    a["recent"] = a["recent"][-12:]


def _keywords(turns):
    """Cheap topic signal from the user turns — no model needed."""
    from collections import Counter
    stop = {"the","a","an","and","or","but","is","are","was","to","of","in","on",
            "it","this","that","you","i","we","me","my","your","what","how","do",
            "can","with","for","be","as","at","so","if","not","have","has"}
    c = Counter()
    for t in turns:
        if t.get("role") != "user":
            continue
        for w in (t.get("text") or "").lower().split():
            w = w.strip(".,!?;:'\"()[]{}")
            if 4 <= len(w) <= 20 and w not in stop:
                c[w] += 1
    return [w for w, _ in c.most_common(6)]


_AUTONOMIC_DIRS = {"canary_ack", "canary", "heartbeat", "probe", "ping", "keepalive",
                   "delivery_status", "delivery", "receipt", "read_receipt",
                   "ack", "status", "sent"}


def _on_channel(subject, payload):
    """UNIVERSAL intake — any non-CLI interface (iMessage, Telegram, voice, web,
    anything that publishes channel.<name>.<inbound|outbound>) is captured into
    the SAME conversation memory and gets the SAME capture-on-close as CLIs.
    This is the interface-agnostic design: memory does not care which surface a
    turn came through. (2026-06-08)"""
    try:
        parts = (subject or "").split(".")
        if len(parts) < 3:
            return
        channel, direction = parts[1], parts[2]
        if direction in _AUTONOMIC_DIRS:
            return
        p = payload or {}
        text = p.get("text") or ""
        if not isinstance(text, str) or not text.strip():
            return
        if text.lstrip().startswith("<canary") or p.get("dry_run") or p.get("probe_id"):
            return
        # Orion's own autonomous outbound notifications (Wonder/will alerts) carry
        # a 'via' source — they're Orion talking AT the user, not conversation.
        # Don't let them pollute recent-turns / memory. (2026-06-08)
        if direction != "inbound" and p.get("via"):
            return
        role = "user" if direction == "inbound" else "assistant"
        ts = float(p.get("ts") or time.time())
        _append(channel, role, text, ts)
        _note_activity("channel:" + channel, channel, role, text, time.time())
    except Exception:
        pass


def _check_closes(now):
    """A session that's been quiet past IDLE_CLOSE_SEC is treated as closed:
    write a resume marker so any window can pick the thread back up."""
    for fp, a in list(_activity.items()):
        if a["closed"] or a["count"] == 0:
            continue
        if (now - a["last_ts"]) < IDLE_CLOSE_SEC:
            continue
        a["closed"] = True
        recent = a["recent"]
        last_user = next((t["text"] for t in reversed(recent) if t["role"] == "user"), "")
        last_orion = next((t["text"] for t in reversed(recent) if t["role"] != "user"), "")
        marker = {
            "surface": a["surface"],
            "closed_at": now,
            "iso": _iso(now),
            "turns": a["count"],
            "topic": _keywords(recent),
            "last_user": last_user[:240],
            "last_orion": last_orion[:240],
        }
        try:
            with RESUME_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(marker, default=str) + "\n")
        except Exception:
            pass
        try:
            from orion_substrate import publish
            publish("brain.session.closed", marker)
        except Exception:
            pass
        # reset the per-session counter so a re-opened file starts fresh
        a["count"] = 0


def _test():
    """Parse-check: show what each surface's newest transcript would yield."""
    for surface, pattern, parser in SURFACES:
        files = sorted(_glob.glob(pattern), key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
        print("=== %s ===" % surface)
        if not files:
            print("  (no transcripts)")
            continue
        fp = files[-1]
        print("  file:", fp)
        got = 0
        for line in Path(fp).read_text(encoding="utf-8", errors="replace").splitlines()[-40:]:
            try:
                d = json.loads(line)
            except Exception:
                continue
            try:
                r = parser(d)
            except Exception:
                r = None
            if r:
                role, text, ts = r
                print("   [%s] %s" % (role, text[:80].replace("\n", " ")))
                got += 1
        if not got:
            print("  (no parseable turns in last 40 lines)")


def main():
    if "--test" in sys.argv:
        _test()
        return 0
    SYNTH.mkdir(parents=True, exist_ok=True)
    state = _load_state()

    # UNIVERSAL intake: also capture every non-CLI interface from the substrate
    # (iMessage / Telegram / voice / web — anything publishing channel.*), into
    # the SAME conversation memory + capture-on-close. Best-effort; the CLI
    # file-tailer keeps working if the substrate is unavailable.
    try:
        from orion_substrate import subscribe, get_substrate
        get_substrate()._connect_blocking()
        subscribe("channel.*.inbound", _on_channel)
        subscribe("channel.*.outbound", _on_channel)
    except Exception:
        pass

    def _sig(_s, _f):
        _stop.set()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    while not _stop.is_set():
        try:
            _tick(state)
        except Exception:
            pass
        _stop.wait(POLL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
