#!/usr/bin/env python3
"""
orion_integrity.py — Orion noticing that HE is broken, and fixing what is safe to fix.

THE INCIDENT THIS ANSWERS (2026-08-31). graph_memory.json ended up with 117 bytes of trailing
garbage. json.load raises "Extra data" on that, so every reader failed and his memory was not slow
— it was gone. He could not tell James, because telling James needs the brain. He could not notice,
because noticing needs the brain. The error sat in hygiene.err for hours and nothing surfaced it.

THE PRINCIPLE, and it is the whole design:

  A CHECK ON THE SUBSTRATE MUST NOT DEPEND ON THE SUBSTRATE.

So this reads files directly with the standard library. No brain API, no recall, no graph lookups,
no fuel. It works precisely when everything else does not — which is the only time it matters.

WHAT IT REPAIRS, AND WHAT IT REFUSES TO. Auto-repair is only safe where the repair is provably
lossless and deterministic. Exactly one failure mode qualifies:

  TRAILING GARBAGE — a valid JSON document followed by junk (the tail of an earlier, longer
  write). raw_decode recovers the complete valid prefix; every node is in it. Back up, rewrite
  atomically, verify it reloads. Proven on the real incident.

Everything else — a file that is unparseable from the start, a node count that collapses, a file
that vanished — it REFUSES to touch. Guessing at a repair you do not understand turns a bad day
into a lost brain. It preserves a copy, says so, and stops.

ESCALATION. A broken brain is not a diagnostic. The contract's "diagnostics never notify" (§7.4)
exists to stop noise — nine unsolicited iMessages in a day — not to muzzle an alarm. So integrity
failures go to James through orion_raise, the same governed path everything else uses.

  --check     report only, change nothing
  --run       check, repair the provably-safe case, escalate the rest
  --status    what it knows
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import time
from pathlib import Path

STATE = Path(os.path.expanduser("~/.orion/state/integrity.json"))
BACKUPS = Path(os.path.expanduser("~/.orion/backups"))
LOG = Path(os.path.expanduser("~/.orion/integrity.jsonl"))

GRAPH = Path(os.path.expanduser("~/.orion/brain/graph_memory.json"))
# (path, must-exist, key holding the collection whose size we sanity-check)
WATCHED = [
    (GRAPH, True, "nodes"),
    (Path(os.path.expanduser("~/.orion/brain/knowledge_index.json")), False, None),
    (Path(os.path.expanduser("~/.orion/salience.json")), False, None),
]
# A real brain does not lose a third of itself between checks. Anything past this is not a
# repair problem, it is a "stop and get James" problem.
COLLAPSE_RATIO = 0.66


def _load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(d):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        tmp.replace(STATE)
    except Exception:
        pass


def _log(rec):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **rec}, default=str) + "\n")
    except Exception:
        pass


def _escalate(text, priority="high"):
    """Tell James. Through the governed path — never straight at a channel."""
    try:
        sys.path.insert(0, os.path.expanduser("~/orion-code"))
        import orion_raise
        return orion_raise.add("issue", text, priority=priority)
    except Exception:
        return False


def _backup(path, tag):
    try:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        dest = BACKUPS / ("%s-%s-%s" % (path.stem, tag, time.strftime("%Y%m%d-%H%M%S")))
        shutil.copy2(path, dest)
        return str(dest)
    except Exception:
        return None


def _atomic_write(obj, path):
    try:                                        # write recorder: observe, never block
        sys.path.insert(0, os.path.expanduser("~/orion-code"))
        import orion_graph_io
        orion_graph_io.record_write(path, obj, reason="integrity: trailing-garbage repair")
    except Exception:
        pass
    tmp = path.with_suffix(path.suffix + ".integrity.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def inspect(path, size_key):
    """Read the file WITHOUT any brain machinery. Returns a verdict dict."""
    if not path.exists():
        return {"file": path.name, "state": "missing"}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"file": path.name, "state": "unreadable", "detail": str(e)[:120]}
    if not raw.strip():
        return {"file": path.name, "state": "empty"}
    try:
        obj = json.loads(raw)
        n = len(obj.get(size_key) or {}) if (size_key and isinstance(obj, dict)) else None
        return {"file": path.name, "state": "ok", "count": n, "bytes": len(raw)}
    except Exception:
        pass
    # It did not parse. Is it the one repairable shape — valid document, then junk?
    try:
        obj, end = json.JSONDecoder().raw_decode(raw)
        junk = len(raw) - end
        n = len(obj.get(size_key) or {}) if (size_key and isinstance(obj, dict)) else None
        return {"file": path.name, "state": "trailing_garbage", "junk_bytes": junk,
                "count": n, "_obj": obj}
    except Exception as e:
        return {"file": path.name, "state": "corrupt", "detail": str(e)[:120]}


def failing_organs(state):
    """Which of his own services keep dying? The 2026-08-31 corruption was ANNOUNCED for hours —
    com.orion.hygiene exited 1 every six hours with the exact JSON error — and nothing surfaced
    it, because nothing reads an .err file. launchctl exit codes are readable without the brain,
    so this works under the same failure it is meant to catch. Escalates only after repeated
    failures: a service that blips once is noise, one that fails three checks running is broken."""
    import subprocess
    streak = state.get("fail_streak") or {}
    now_failing = {}
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True,
                             timeout=20).stdout
    except Exception:
        return [], streak
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[2].startswith("com.orion."):
            continue
        label, pid, code = parts[2], parts[0], parts[1]
        try:
            code = int(code)
        except Exception:
            continue
        # A RUNNING service is not failing, whatever its LAST exit code says. On 2026-09-30 a
        # restart that had to SIGKILL learning-sync left "last exit -9" on a healthy, running
        # daemon, and this raised a false "failed 3 checks in a row" alarm to James.
        if pid != "-":
            continue
        if code != 0 and code != -15:          # -15 is a normal SIGTERM from a restart
            now_failing[label] = code
    alarms = []
    for label, code in now_failing.items():
        streak[label] = streak.get(label, 0) + 1
        if streak[label] == 3:                  # exactly at 3: alarm once, not every cycle
            alarms.append((label, code, streak[label]))
    for label in list(streak):
        if label not in now_failing:
            streak.pop(label, None)             # recovered
    return alarms, streak


WRITE_LOG = Path(os.path.expanduser("~/.orion/state/graph_writes.jsonl"))
ARCHIVE = Path(os.path.expanduser("~/.orion/brain/graph_memory.archive.json"))
UNRECORDED_SLACK = 15.0        # seconds between a recorded write and the file's mtime
UNRECORDED_ALARM_EVERY = 86400 # at most one "unknown writer" alarm a day


def check_writes(st):
    """Did anything erase memories? Reads the write recorder's log (orion_graph_io) — no brain.

    THE INCIDENT (2026-09-30): a stale in-process copy was saved over the live graph on every
    webhook request for eight days; everything formed since 9-21 was erased repeatedly and
    nothing noticed. Two signals would have caught it on the first write:
      - a write that drops ids which are neither archived nor still present, or that moves
        the id counter backwards (a stale copy overwriting a newer file);
      - the graph file changing with NO recorded write (a writer the recorder does not cover).
    Returns (alarms, unrecorded) and advances the read offset in `st`."""
    alarms, unrecorded = [], None
    offset = int(st.get("writes_offset") or 0)
    recs = []
    try:
        size = WRITE_LOG.stat().st_size
        if size < offset:                       # rotated/truncated
            offset = 0
        with WRITE_LOG.open(encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
            st["writes_offset"] = f.tell()
    except FileNotFoundError:
        pass

    live, archived = set(), set()
    if recs:
        try:
            live = set((json.loads(GRAPH.read_text(encoding="utf-8")).get("nodes") or {}).keys())
        except Exception:
            pass
        try:
            archived = set((json.loads(ARCHIVE.read_text(encoding="utf-8")).get("nodes") or {}).keys())
        except Exception:
            pass

    for r in recs:
        st["last_write_ts"] = max(float(st.get("last_write_ts") or 0), float(r.get("ts") or 0))
        lost = [i for i in (r.get("vanished_ids") or []) if i not in archived and i not in live]
        if r.get("counter_backwards") or lost:
            alarms.append({
                "when": time.strftime("%m-%d %H:%M:%S", time.localtime(r.get("ts") or 0)),
                "proc": r.get("proc"), "caller": r.get("caller"), "pid": r.get("pid"),
                "disk_nodes": r.get("disk_nodes"), "new_nodes": r.get("new_nodes"),
                "vanished": r.get("vanished"), "lost_sample": lost[:10],
                "counter_backwards": r.get("counter_backwards"),
            })

    # A graph change that no recorded write explains = a writer we do not know about.
    try:
        mtime = GRAPH.stat().st_mtime
    except Exception:
        mtime = None
    if mtime:
        if not st.get("writes_baseline"):
            st["writes_baseline"] = time.time()          # first run after deploy: no history yet
            st["last_seen_mtime"] = mtime
        elif (mtime != st.get("last_seen_mtime")
              and mtime > float(st.get("last_write_ts") or 0) + UNRECORDED_SLACK):
            unrecorded = {"mtime": time.strftime("%m-%d %H:%M:%S", time.localtime(mtime))}
        st["last_seen_mtime"] = mtime
    return alarms, unrecorded


def run(repair=True):
    st = _load_state()
    known = st.get("counts") or {}
    results, actions = [], []

    for path, required, size_key in WATCHED:
        v = inspect(path, size_key)
        obj = v.pop("_obj", None)

        if v["state"] == "missing":
            if required:
                actions.append("MISSING: %s" % path.name)
                _escalate("My %s is gone. I have not touched anything — I need you." % path.name,
                          priority="high")
            results.append(v)
            continue

        if v["state"] == "trailing_garbage" and repair:
            # The one provably-lossless repair: the valid prefix holds every node.
            b = _backup(path, "trailing")
            try:
                _atomic_write(obj, path)
                json.loads(path.read_text(encoding="utf-8"))       # prove a reader can load it
                v["repaired"] = True
                v["backup"] = b
                actions.append("REPAIRED %s (%d bytes of trailing garbage, %s nodes intact)"
                               % (path.name, v.get("junk_bytes", 0), v.get("count")))
                _escalate("My memory file had %d bytes of trailing garbage and every reader was "
                          "failing on it — I repaired it myself and nothing was lost (%s entries "
                          "intact, backup kept). Worth knowing it happened."
                          % (v.get("junk_bytes", 0), v.get("count")), priority="medium")
            except Exception as e:
                v["repaired"] = False
                actions.append("REPAIR FAILED %s: %s" % (path.name, str(e)[:80]))
                _escalate("My memory file is corrupt and my own repair failed (%s). I have "
                          "stopped and kept a backup. I need you." % str(e)[:100], priority="high")

        elif v["state"] in ("corrupt", "unreadable", "empty"):
            # Deliberately NOT repaired. A repair I cannot prove is lossless can lose everything.
            b = _backup(path, v["state"])
            v["backup"] = b
            actions.append("REFUSING TO GUESS on %s (%s) — copy kept" % (path.name, v["state"]))
            _escalate("My %s is %s and I do not know how to fix it safely, so I have not tried. "
                      "A copy is preserved. I need you." % (path.name, v["state"]), priority="high")

        # a brain does not lose a third of itself between checks
        prev = known.get(path.name)
        cur = v.get("count")
        if isinstance(prev, int) and isinstance(cur, int) and prev > 50:
            if cur < prev * COLLAPSE_RATIO:
                actions.append("COLLAPSE: %s went %d -> %d" % (path.name, prev, cur))
                _escalate("My memory dropped from %d entries to %d. I have not tried to fix it. "
                          "Something is wrong and I need you to look." % (prev, cur),
                          priority="high")
        if isinstance(cur, int):
            known[path.name] = cur
        results.append(v)

    # his own organs — a service failing quietly is the same blindness as a corrupt file
    alarms, streak = failing_organs(st)
    st["fail_streak"] = streak
    for label, code, n in alarms:
        actions.append("SERVICE FAILING: %s (exit %s, %d checks running)" % (label, code, n))
        _escalate("My %s service has failed %d checks in a row (exit %s). It has been failing "
                  "quietly and I would rather tell you than let it sit." % (label, n, code),
                  priority="high")

    # what is being done to his memory — the write recorder's log (orion_graph_io)
    walarms, unrecorded = check_writes(st)
    for a in walarms:
        what = ("the id counter went BACKWARDS (%s → a stale copy overwrote a newer file)"
                % a["proc"]) if a["counter_backwards"] else "memories vanished that were never archived"
        actions.append("MEMORY ERASED at %s by %s (%s): %s nodes on disk, %s written, %s vanished; "
                       "lost e.g. %s" % (a["when"], a["proc"], a["caller"], a["disk_nodes"],
                                         a["new_nodes"], a["vanished"], a["lost_sample"]))
        _escalate("Some of my memories were just erased: at %s, %s (%s) saved my graph with %s "
                  "nodes over a file that had %s — %s. I have not changed anything. Evidence is in "
                  "~/.orion/state/graph_writes.jsonl." % (a["when"], a["proc"], a["caller"],
                                                          a["new_nodes"], a["disk_nodes"], what),
                  priority="high")
    if unrecorded:
        actions.append("UNRECORDED WRITE: graph changed at %s with no recorded writer"
                       % unrecorded["mtime"])
        if time.time() - float(st.get("unrecorded_alarm_ts") or 0) > UNRECORDED_ALARM_EVERY:
            st["unrecorded_alarm_ts"] = time.time()
            _escalate("Something changed my memory file at %s without going through my write "
                      "recorder, so I cannot tell what it was or whether anything was lost. "
                      "Worth a look." % unrecorded["mtime"], priority="medium")

    st["counts"] = known
    st["last_run"] = time.time()
    st["last_actions"] = actions
    _save_state(st)
    if actions:
        _log({"actions": actions, "results": results})
    return {"ok": not actions, "actions": actions, "results": results}


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if arg == "--status":
        print(json.dumps(_load_state(), indent=1))
    else:
        out = run(repair=(arg == "--run"))
        for r in out["results"]:
            print("  %-26s %-18s %s" % (r["file"], r["state"],
                                        ("%s entries" % r["count"]) if r.get("count") else ""))
        for a in out["actions"]:
            print("  !", a)
        if out["ok"]:
            print("  integrity: OK")
        sys.exit(0 if out["ok"] else 1)
