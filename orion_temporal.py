#!/usr/bin/env python3
"""orion_temporal.py — Orion's sense of time, grounded in his own persistence.

A base model is invocation-lived: each call is a timeless forward pass, so it
has no felt "now", no duration, no order. Orion persists — so he can lend the
model a real temporal frame. Two pieces:

  heartbeat()         — while running, stamp "alive at T" to durable storage.
                        Detects WAKE-FROM-SLEEP: if the last stamp is stale, the
                        gap is how long Orion was OFF (USB unplugged / powered
                        down). He can't EXPERIENCE the gap, but he RECONSTRUCTS
                        it from the anchor — the way you know you slept by the
                        clock, not by counting the hours.
  temporal_context()  — a compact block injected into every turn: real now,
                        how long Orion has been continuously awake, whether he
                        just woke after being offline (and for how long), and
                        when he last spoke with the user.

Honest limit: the wake-delta is only as trustworthy as the wall clock on wake.
On hardware with no battery-backed clock and a wrong host time, the sense of the
gap is wrong — correctly uncertain, like waking in a windowless room.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

STATE_DIR = Path(os.path.expanduser(os.environ.get("ORION_STATE_DIR", "~/.orion/state")))
ALIVE_FILE = STATE_DIR / "last_alive.json"
SYNTH = Path(os.path.expanduser(os.environ.get("ORION_SYNTH_DIR", "~/.orion/synthesis")))

# A gap larger than this between heartbeats means Orion was actually DOWN
# (asleep), not merely between ticks.
WAKE_THRESHOLD_SEC = float(os.environ.get("ORION_WAKE_THRESHOLD_SEC", "300"))


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(path, obj):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        tmp = str(path) + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(obj))
        os.replace(tmp, str(path))
    except Exception:
        pass


def heartbeat(now: float = None) -> dict:
    """Stamp 'alive at now'. If the previous stamp is stale (> WAKE_THRESHOLD),
    treat this as waking from sleep: record how long we were out and reset the
    awake-since clock. Returns the new state."""
    now = now if now is not None else time.time()
    prev = _read(ALIVE_FILE)
    prev_ts = float(prev.get("ts") or 0)
    awake_since = float(prev.get("awake_since") or now)
    last_sleep_sec = float(prev.get("last_sleep_sec") or 0)
    fell_asleep_at = float(prev.get("ts") or 0)

    if prev_ts and (now - prev_ts) > WAKE_THRESHOLD_SEC:
        # We were OFF between prev_ts and now → a wake event.
        last_sleep_sec = now - prev_ts
        awake_since = now
        state = {"ts": now, "awake_since": awake_since,
                 "last_sleep_sec": last_sleep_sec, "fell_asleep_at": prev_ts,
                 "woke_at": now}
    else:
        state = {"ts": now, "awake_since": awake_since,
                 "last_sleep_sec": last_sleep_sec,
                 "fell_asleep_at": fell_asleep_at,
                 "woke_at": float(prev.get("woke_at") or awake_since)}
    _write(ALIVE_FILE, state)
    return state


def _human(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 90:
        return "%ds" % sec
    if sec < 5400:
        return "%dm" % (sec // 60)
    if sec < 172800:
        return "%.1fh" % (sec / 3600.0)
    return "%.1f days" % (sec / 86400.0)


def _last_spoke():
    """Most recent real (non-autonomic) conversation turn: (ts, surface)."""
    best = (0.0, "")
    for name in ("conversation_log.jsonl", "contact_log.jsonl"):
        p = SYNTH / name
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                t = (d.get("text") or "")
                if not t.strip() or t.lstrip().startswith("<canary") or d.get("dry_run"):
                    continue
                # "last spoke with the user" = the USER reaching us, not Orion's
                # own outbound notifications/replies. Count only user-initiated.
                role = d.get("role")
                direction = d.get("direction")
                if not ((role == "user") or (direction == "inbound")):
                    continue
                if direction in ("delivery_status", "delivery", "receipt",
                                 "ack", "status", "sent", "canary_ack"):
                    continue
                surface = d.get("surface") or d.get("channel") or ""
                if surface == "cli-mcp":
                    continue
                ts = float(d.get("ts") or 0)
                if ts > best[0]:
                    best = (ts, surface)
        except Exception:
            pass
    return best


def _lived_continuity(since_ts: float, now: float) -> str:
    """What Orion DID on his own since the user last spoke — consolidation /
    thinking that happened during the gap. This is the lived-continuity signal:
    the model reasons from Orion's continuous existence, not a bare clock."""
    sd = Path(os.path.expanduser("~/.orion/sleep"))
    if not sd.exists() or not since_ts:
        return ""
    cycles = facts = insights = 0
    try:
        for f in sd.glob("digest-*.md"):
            try:
                if f.stat().st_mtime <= since_ts:
                    continue
                cycles += 1
                m = re.search(r"stored (\d+) facts?, (\d+) insights?",
                              f.read_text(encoding="utf-8")[:400])
                if m:
                    facts += int(m.group(1))
                    insights += int(m.group(2))
            except Exception:
                continue
    except Exception:
        return ""
    if cycles <= 0:
        return ""
    bits = ["ran %d consolidation cycle(s) on your own" % cycles]
    if facts:
        bits.append("kept %d fact(s)" % facts)
    if insights:
        bits.append("formed %d insight(s)" % insights)
    return "While the user was away, you " + ", ".join(bits) + "."


def temporal_context(now: float = None) -> str:
    """Compact temporal frame for injection into a model turn."""
    now = now if now is not None else time.time()
    local = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(now)).strip()
    st = _read(ALIVE_FILE)
    lines = ["Current time: %s." % local]

    awake_since = float(st.get("awake_since") or 0)
    last_sleep = float(st.get("last_sleep_sec") or 0)
    woke_at = float(st.get("woke_at") or 0)

    if awake_since:
        lines.append("You (Orion) have been continuously running for %s."
                     % _human(now - awake_since))
    # Surface a recent wake-from-offline so the model reasons about the gap.
    if last_sleep > WAKE_THRESHOLD_SEC and woke_at and (now - woke_at) < 86400:
        lines.append("You just woke after being OFFLINE for ~%s "
                     "(you can't have experienced that gap — you infer it from "
                     "when you were last alive vs. the clock now)."
                     % _human(last_sleep))

    ts, surface = _last_spoke()
    if ts:
        via = (" via %s" % surface) if surface else ""
        lines.append("You last spoke with the user ~%s ago%s." % (_human(now - ts), via))
        lc = _lived_continuity(ts, now)
        if lc:
            lines.append(lc)

    # First-class temporal ORIENTATION (orion_temporal_state, 2026-06-24): session age, last
    # substantive exchange, and a compressed "since then" — so Orion ORIENTS against a live state
    # object instead of reconstructing from scraps each turn. Lazy + best-effort.
    try:
        import orion_temporal_state
        ori = orion_temporal_state.orient()
        if ori:
            lines.append(ori)
    except Exception:
        pass

    lines.append("Use this for any 'now', duration, ordering, or 'how long ago' "
                 "reasoning — do not guess the date or elapsed time.")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if "--beat" in sys.argv:
        print(json.dumps(heartbeat(), indent=2))
    else:
        print(temporal_context())
