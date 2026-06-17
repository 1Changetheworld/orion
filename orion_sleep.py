#!/usr/bin/env python3
"""orion_sleep.py — memory consolidation, the "sleep" where understanding emerges.

This is the autonomous between-session thinking. While no one is talking, Orion
REPLAYS the recent conversation and does what a base model cannot on its own:

  1. turns episodic chatter into durable, deduplicated SEMANTIC memory
  2. forms higher-order INSIGHTS — patterns ACROSS separate memories that were
     never stated in any single turn — each one GROUNDED IN and citing the
     memories it came from (provenance, so it's reconstruction, not confabulation)
  3. notes what's still UNRESOLVED (open threads to wonder about)
  4. runs hygiene (exact-dedup + archive-not-delete via orion_consolidate)
  5. writes a human-readable "while you were away" digest

DISCIPLINE (from the continual-learning literature, see orion_dream.py):
real-time consolidation self-degrades (arXiv 2505.17716). So this runs ASYNC —
scheduled + on session-close + idle — NEVER on the live turn path.

Complements orion_dream.py (which consolidates the executive's DECISION ledger
into incident playbooks). This is the EPISODIC/SEMANTIC analogue for the user's
actual conversations. Model is fuel; the brain doing this on its own is the point.

Run:  python orion_sleep.py --once     # one consolidation cycle, then exit
      python orion_sleep.py            # daemon: on session-close + schedule
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import urllib.request
from pathlib import Path

ORION = Path(os.path.expanduser("~/.orion"))
SYNTH = ORION / "synthesis"
CONV_LOG = SYNTH / "conversation_log.jsonl"
SLEEP_DIR = ORION / "sleep"
STATE = SLEEP_DIR / "state.json"
GRAPH_PATH = ORION / "brain/graph_memory.json"

BRAIN_URL = os.environ.get("ORION_BRAIN_HTTP_URL", "http://127.0.0.1:5556").rstrip("/")
AUTH_PATH = os.path.expanduser(os.environ.get("ORION_AUTH_TOKEN_PATH", "~/.orion/auth-token"))

CYCLE_SEC = float(os.environ.get("ORION_SLEEP_CYCLE_SEC", "10800"))   # periodic: 3h
DEBOUNCE_SEC = float(os.environ.get("ORION_SLEEP_DEBOUNCE_SEC", "180"))  # after session-close
MIN_NEW_TURNS = int(os.environ.get("ORION_SLEEP_MIN_TURNS", "4"))
MAX_TURNS = int(os.environ.get("ORION_SLEEP_MAX_TURNS", "60"))
MAX_INSIGHTS = int(os.environ.get("ORION_SLEEP_MAX_INSIGHTS", "3"))
MAX_FACTS = int(os.environ.get("ORION_SLEEP_MAX_FACTS", "8"))

_stop = threading.Event()
_pending = threading.Event()

# JSON shape we ask the fuel to return (single-quoted Python string, so the
# double quotes inside need no escaping).
_SCHEMA_HINT = ('{"facts":["..."],'
                '"insights":[{"insight":"...","grounded_in":"...","significance":0.0}],'
                '"open":["..."]}')


# ── small io ──────────────────────────────────────────────────────

def _load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(s):
    try:
        SLEEP_DIR.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(s), encoding="utf-8")
    except Exception:
        pass


def _token():
    try:
        return open(AUTH_PATH, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _memorize(content, node_type="fact", tags=None):
    """Store through the brain so dedupe-on-write + contradiction handling run."""
    tok = _token()
    if not tok:
        return False
    body = json.dumps({"name": "orion_memorize",
                       "arguments": {"content": content, "type": node_type,
                                     "tags": tags or []}}).encode("utf-8")
    req = urllib.request.Request(f"{BRAIN_URL}/v1/call", data=body,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception:
        return False


# ── fuel: reason AS Orion (persona-framed, model-agnostic) ─────────

def _think(prompt: str) -> str:
    try:
        import orion_fuel
    except Exception:
        return ""
    frame = ""
    try:
        import orion_persona_render
        frame = orion_persona_render.render_persona() or ""
    except Exception:
        frame = ""
    full = (frame + "\n\n---\n\n" + prompt) if frame else prompt
    try:
        reply, _ = orion_fuel.get_fuel(full, interface="sleep-consolidation")
        return (reply or "").strip()
    except Exception:
        return ""


# ── replay source ─────────────────────────────────────────────────

def _recent_turns(since_ts: float):
    if not CONV_LOG.exists():
        return []
    out = []
    for line in CONV_LOG.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = (d.get("text") or "").strip()
        if not t:
            continue
        if float(d.get("ts") or 0) <= since_ts:
            continue
        out.append(d)
    return out[-MAX_TURNS:]


def _parse_json(raw: str):
    if not raw:
        return None
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(raw[a:b + 1])
    except Exception:
        return None


# ── the cycle ─────────────────────────────────────────────────────

def run_cycle(reason="schedule"):
    st = _load_state()
    since = float(st.get("cursor_ts", 0))
    turns = _recent_turns(since)
    if len(turns) < MIN_NEW_TURNS:
        return {"skipped": "only %d new turns" % len(turns)}

    transcript = "\n".join(
        "[%s/%s] %s" % (t.get("surface", "?"), t.get("role", "?"),
                        (t.get("text") or "")[:300]) for t in turns)

    prompt = (
        "You are consolidating your own recent memory while no one is talking — "
        "your 'sleep'. Below are recent conversation turns across your interfaces. "
        "Do three things, GROUNDED ONLY in what is actually here (never invent):\n"
        "1. FACTS: durable facts genuinely worth remembering long-term (preferences, "
        "decisions, identity, project state). One sentence each. Skip small talk.\n"
        "2. INSIGHTS: patterns or realizations ACROSS turns that were NOT explicitly "
        "stated — your own understanding forming. For each, name which turns it came "
        "from. Only genuine ones; if none, return [].\n"
        "3. OPEN: what's unresolved / worth returning to.\n"
        "Be conservative and concrete. Return ONLY JSON of this shape:\n"
        + _SCHEMA_HINT + "\n\nRECENT TURNS:\n" + transcript)

    raw = _think(prompt)
    data = _parse_json(raw)
    if not data:
        # fuel unavailable / unparseable → don't fail; still advance hygiene + cursor
        _hygiene()
        st["cursor_ts"] = float(turns[-1].get("ts") or since)
        st["last_run"] = time.time()
        _save_state(st)
        return {"consolidated": 0, "note": "no parseable fuel output (degraded)"}

    facts = [f for f in (data.get("facts") or []) if isinstance(f, str) and f.strip()][:MAX_FACTS]
    insights = [i for i in (data.get("insights") or []) if isinstance(i, dict)][:MAX_INSIGHTS]
    open_threads = [o for o in (data.get("open") or []) if isinstance(o, str)][:6]

    stored_f = 0
    for f in facts:
        if _memorize(f.strip(), node_type="fact", tags=["consolidated", "sleep"]):
            stored_f += 1

    stored_i = 0
    for i in insights:
        text = (i.get("insight") or "").strip()
        if not text:
            continue
        try:
            sig = float(i.get("significance", 0.5))
        except Exception:
            sig = 0.5
        if sig < 0.4:  # salience gate — don't flood the graph with weak insights
            continue
        grounded = (i.get("grounded_in") or "").strip()
        if not grounded:  # ungrounded "insight" = confabulation; drop it
            continue
        content = "[insight, derived in sleep — grounded in: %s]: %s" % (grounded[:160], text)
        if _memorize(content, node_type="insight", tags=["insight", "derived", "sleep"]):
            stored_i += 1

    _hygiene()

    now = time.time()
    digest = _write_digest(reason, turns, facts, insights, open_threads, stored_f, stored_i)
    st["cursor_ts"] = float(turns[-1].get("ts") or since)
    st["last_run"] = now
    _save_state(st)
    _publish("brain.sleep.completed", {"reason": reason, "turns": len(turns),
                                       "facts": stored_f, "insights": stored_i,
                                       "digest": str(digest), "ts": now})
    return {"turns": len(turns), "facts_stored": stored_f,
            "insights_stored": stored_i, "open": len(open_threads), "digest": str(digest)}


def _hygiene():
    """Safe exact-dedup + archive-not-delete via the existing consolidator."""
    try:
        import orion_consolidate
        orion_consolidate.consolidate(str(GRAPH_PATH), apply=True)
    except Exception:
        pass


def _write_digest(reason, turns, facts, insights, open_threads, sf, si):
    SLEEP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    path = SLEEP_DIR / ("digest-%s.md" % ts)
    lines = ["# Sleep consolidation — %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
             "trigger: %s | replayed %d turns | stored %d facts, %d insights\n"
             % (reason, len(turns), sf, si)]
    if facts:
        lines.append("## Facts kept")
        lines += ["- %s" % f for f in facts]
    if insights:
        lines.append("\n## Insights formed (grounded)")
        for i in insights:
            lines.append("- %s\n  (from: %s)" % (i.get("insight", ""), i.get("grounded_in", "")))
    if open_threads:
        lines.append("\n## Still open")
        lines += ["- %s" % o for o in open_threads]
    try:
        path.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass
    return path


def _publish(subject, payload):
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass


# ── daemon ────────────────────────────────────────────────────────

def _on_session_closed(subject, payload):
    _pending.set()  # debounced trigger; the loop picks it up


def main():
    if "--once" in sys.argv:
        print(json.dumps(run_cycle(reason="manual"), indent=2, default=str))
        return 0

    SLEEP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from orion_substrate import subscribe, get_substrate
        get_substrate()._connect_blocking()
        subscribe("brain.session.closed", _on_session_closed)
    except Exception:
        pass

    def _sig(_s, _f):
        _stop.set()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    last_periodic = 0.0
    while not _stop.is_set():
        now = time.time()
        fire = False
        if _pending.is_set():
            # debounce: wait a bit so a closing session settles
            _stop.wait(DEBOUNCE_SEC)
            _pending.clear()
            fire = True
        elif (now - last_periodic) >= CYCLE_SEC:
            fire = True
        if fire and not _stop.is_set():
            try:
                run_cycle(reason="session-close" if _pending else "schedule")
            except Exception:
                pass
            last_periodic = time.time()
        _stop.wait(30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
