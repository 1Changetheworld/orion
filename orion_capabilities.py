#!/usr/bin/env python3
"""
orion_capabilities.py — what Orion can actually do, learned from DOING, not from a timer.

THE PROBLEM. On 2026-09-01 he told James "I don't have live browser access to Blackboard" and
twelve minutes later "already verified, full access." Both from memory. Neither from looking. He
does not know his own hands, so he asserts and then gets corrected.

WHY THERE IS NO DAEMON HERE. James, on being offered a scheduled prober: "not a fan of scheduled
things and daemons." He is right, and it would have been the same mistake we spent this build
undoing — the 3-hour sleep clock was removed for making him chew instead of think, and a polling
prober is that clock wearing a different hat.

So capability knowledge is a BYPRODUCT OF ACTING, which is how proprioception really works: you do
not poll where your hand is, you know because you are using it, and you re-check the moment
something surprises you. Every action this system already performs generates perfect capability
evidence and currently throws it away.

  record()  — an action path reports what happened. Free: it already knows.
  check()   — an ON-DEMAND probe, only when he actually needs to know and has no fresh answer.
  block()   — what his prompt carries. NEVER probes; reads what is known and states its AGE.

IT GATES NOTHING. There is no allowlist, no permission check, no "you may not." He can attempt
anything, including things last known to be down — the map is sometimes stale and the thing works.
The only change is that he stops claiming things about himself that are not true. Knowing you have
a hand does not restrict the hand; it is what makes reaching possible instead of flailing.

STALE IS REPORTED, NEVER REFRESHED BEHIND HIS BACK. "Blackboard worked 40 minutes ago, I have not
touched it since" is honest. Silently re-polling to keep a number looking fresh is the thing being
rejected.

  --show     the block his prompt would carry
  --check X  probe one capability now
  --all      probe everything (slow; explicit only)
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STORE = Path(os.path.expanduser("~/.orion/state/capabilities.json"))
CODE = Path(os.path.expanduser("~/orion-code"))
FRESH_SEC = 900.0          # under this, an answer is treated as current
MAX_ENTRIES = 60


def _load():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STORE)
    except Exception:
        pass


def record(name, ok, detail="", source="action"):
    """An action path telling the map what just happened. Never raises — capability learning must
    never be able to break the action it is learning from."""
    try:
        d = _load()
        prev = d.get(name) or {}
        d[name] = {"ok": bool(ok), "ts": time.time(), "detail": str(detail)[:160],
                   "source": source,
                   "last_ok_ts": (time.time() if ok else prev.get("last_ok_ts")),
                   "consecutive_fail": 0 if ok else int(prev.get("consecutive_fail", 0)) + 1}
        if len(d) > MAX_ENTRIES:
            for k in sorted(d, key=lambda k: d[k].get("ts", 0))[:len(d) - MAX_ENTRIES]:
                d.pop(k, None)
        _save(d)
        return True
    except Exception:
        return False


def get(name):
    return _load().get(name)


def _human_age(sec):
    sec = max(0.0, float(sec))
    if sec < 90:
        return "%ds ago" % int(sec)
    if sec < 5400:
        return "%dm ago" % int(sec / 60)
    if sec < 172800:
        return "%.1fh ago" % (sec / 3600)
    return "%.1f days ago" % (sec / 86400)


# ── on-demand probes. Run ONLY when asked; never on a schedule. ─────────────────
def _probe_imessage_send():
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True,
                         timeout=10).stdout
    up = any(l.split()[-1] == "com.orion.imessage-outbound" for l in out.splitlines()
             if l.split())
    return up, ("outbound sender running" if up else "com.orion.imessage-outbound not loaded")


def _probe_imessage_read():
    import sqlite3
    db = os.path.expanduser("~/Library/Messages/chat.db")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    n = con.execute("SELECT COUNT(*) FROM message").fetchone()[0]
    con.close()
    return True, "chat.db readable (%d messages)" % n


def _probe_blackboard():
    p = Path(os.path.expanduser("~/.orion/school/keepalive-state.json"))
    d = json.loads(p.read_text(encoding="utf-8"))
    ok = d.get("status") == "ok"
    age = time.time() - float(d.get("last_ok") or 0)
    return ok, "session %s, last confirmed %s" % (d.get("status"), _human_age(age))


def _probe_web():
    sys.path.insert(0, str(CODE))
    import orion_web
    r = orion_web.fetch("https://en.wikipedia.org/wiki/Main_Page")
    return bool(r.get("ok")), (r.get("reason") or "")[:80]


def _probe_forge():
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                        "-o", "StrictHostKeyChecking=no", "forge", "echo ok"],
                       capture_output=True, text=True, timeout=15)
    ok = r.returncode == 0 and "ok" in r.stdout
    return ok, (r.stdout or r.stderr or "").strip()[:90]


def _probe_brain():
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:5556/health", timeout=6) as resp:
        return resp.status == 200, "brain http %s" % resp.status


def _probe_fuel():
    """Look in the real install locations, not just PATH. Probed from an SSH shell this reported
    "engines available: none" purely because that shell lacks the daemons' PATH — and a false
    "I have no fuel" is a far more damaging thing for him to believe than no answer at all."""
    import shutil
    dirs = [os.path.expanduser("~/.npm-global/bin"), "/usr/local/bin", "/opt/homebrew/bin",
            "/usr/bin"]
    found = []
    for n in ("claude", "codex", "gemini", "ollama"):
        if shutil.which(n) or any(os.path.exists(os.path.join(d, n)) for d in dirs):
            found.append(n)
    return bool(found), "engines available: " + (", ".join(found) or "none")


PROBES = {
    "imessage_send": _probe_imessage_send,
    "imessage_read": _probe_imessage_read,
    "blackboard": _probe_blackboard,
    "web": _probe_web,
    "forge": _probe_forge,
    "brain": _probe_brain,
    "fuel": _probe_fuel,
}


def check(name, force=False):
    """Probe ONE capability, right now, because he needs to know. Reuses a fresh answer unless
    forced — the point is to avoid asserting from memory, not to generate traffic."""
    if name not in PROBES:
        return None
    cur = get(name)
    if not force and cur and (time.time() - float(cur.get("ts", 0))) < FRESH_SEC:
        return cur
    try:
        ok, detail = PROBES[name]()
    except Exception as e:
        ok, detail = False, str(e)[:120]
    record(name, ok, detail, source="probe")
    return get(name)


def check_all(force=True):
    return {n: check(n, force=force) for n in PROBES}


def block():
    """What his prompt carries. Reads only — this NEVER probes, so it stays free and never turns
    into a background poller by accident."""
    d = _load()
    if not d:
        return ""
    now = time.time()
    fresh, stale = [], []
    for name in sorted(d):
        e = d[name]
        age = now - float(e.get("ts", 0))
        mark = "YES" if e.get("ok") else "NO"
        line = "  - %s: %s (%s%s)" % (name, mark, _human_age(age),
                                      ", " + e["detail"] if e.get("detail") else "")
        (fresh if age < FRESH_SEC else stale).append(line)
    lines = ["<orion-can>",
             "What you could actually do, last time it was tried or checked. This is a MIRROR, "
             "not a permission list — nothing here forbids you anything, and you may attempt "
             "something marked NO (the answer may simply be old). But do NOT claim a capability "
             "from memory: say what is here, with how old it is, and offer to check again."]
    lines += fresh
    if stale:
        lines.append("  older, may have changed since:")
        lines += stale
    lines.append("</orion-can>")
    return "\n".join(lines)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--show"
    if arg == "--check" and len(sys.argv) > 2:
        print(json.dumps(check(sys.argv[2], force=True), indent=1))
    elif arg == "--all":
        t = time.time()
        for n, v in check_all().items():
            print("  %-14s %-4s %s" % (n, "YES" if v and v.get("ok") else "NO",
                                       (v or {}).get("detail", "")[:70]))
        print("  [%.1fs — this is why it is on-demand, not a daemon]" % (time.time() - t))
    else:
        print(block() or "(nothing known yet — it fills in as he acts)")
