#!/usr/bin/env python3
"""
orion_graph_io.py — the write recorder: Orion's sense for what is being done to his memory.

THE INCIDENT THIS ANSWERS (2026-09-30). For eight days every conversation that went through
the legacy webhook saved that process's frozen copy of the graph over the live file. Everything
formed after 2026-09-21 22:31 was erased, again and again. Nothing noticed: no write left a
trace, so the only evidence was node ids that had been silently reused. It was found by hand,
by correlating id gaps with a webhook access log.

THE PRINCIPLE. A mind that cannot see what is done to its own memory cannot protect it. So every
graph writer calls record_write() just before it writes. One line per write goes to
~/.orion/state/graph_writes.jsonl: who wrote (process + caller), when, how many nodes were on
disk versus how many are being written, which ids would vanish, and whether the id counter
would go backwards — the exact signature of a stale copy overwriting a newer one.

It OBSERVES ONLY. It never blocks, alters or delays a write, and it never raises: a recorder
that can break the thing it records is worse than none. Refusing bad writes is a separate,
later decision, made on the evidence this collects. orion_integrity reads the log (without the
brain) and raises an alarm when memories vanish without a stated reason.

  python3 orion_graph_io.py --tail [N]    show the last N recorded writes
"""
from __future__ import annotations
import json
import os
import sys
import time

GRAPH_NAME = "graph_memory.json"
WRITE_LOG = os.path.expanduser("~/.orion/state/graph_writes.jsonl")
_SAMPLE = 50          # ids kept per write in the log (counts are always exact)


def _caller():
    """The first frames outside the save plumbing — the code that actually decided to write."""
    try:
        chain = []
        f = sys._getframe(2)
        while f is not None and len(chain) < 3:
            mod = os.path.basename(f.f_code.co_filename).replace(".py", "")
            fn = f.f_code.co_name
            if mod != "orion_graph_io" and fn not in ("_atomic_dump", "save", "_write_json",
                                                      "_safe_dump"):
                chain.append("%s:%s" % (mod, fn))
            f = f.f_back
        return " < ".join(chain)
    except Exception:
        return "?"


def record_write(path, new_data, reason=None):
    """Call immediately before writing `new_data` (the dict about to be saved) to `path`.
    No-op for anything that is not the graph file. Never raises."""
    try:
        path = str(path)
        if not path.endswith(GRAPH_NAME):
            return
        new_nodes = (new_data or {}).get("nodes") or {}
        new_ids = {str(k) for k in new_nodes}
        new_next = (new_data or {}).get("next_id")

        disk_ids, disk_next, disk_state = set(), None, "ok"
        try:
            with open(path, encoding="utf-8") as f:
                disk = json.load(f)
            disk_ids = {str(k) for k in (disk.get("nodes") or {})}
            disk_next = disk.get("next_id")
        except FileNotFoundError:
            disk_state = "missing"
        except Exception as e:
            disk_state = "unreadable: %s" % str(e)[:80]

        vanished = sorted(disk_ids - new_ids, key=lambda x: int(x) if x.isdigit() else 0)
        added = new_ids - disk_ids
        backwards = (isinstance(disk_next, int) and isinstance(new_next, int)
                     and new_next < disk_next)
        rec = {
            "ts": time.time(),
            "pid": os.getpid(),
            "proc": os.path.basename(sys.argv[0] or "?"),
            "caller": _caller(),
            "reason": reason,
            "disk_state": disk_state,
            "disk_nodes": len(disk_ids),
            "new_nodes": len(new_ids),
            "added": len(added),
            "vanished": len(vanished),
            "vanished_ids": vanished[:_SAMPLE],
            "disk_next_id": disk_next,
            "new_next_id": new_next,
            "counter_backwards": backwards,
        }
        os.makedirs(os.path.dirname(WRITE_LOG), exist_ok=True)
        with open(WRITE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _tail(n):
    try:
        with open(WRITE_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
    except FileNotFoundError:
        print("no writes recorded yet")
        return
    for line in lines:
        r = json.loads(line)
        flag = ""
        if r.get("counter_backwards"):
            flag += "  <<< COUNTER BACKWARDS"
        if r.get("vanished") and not r.get("reason"):
            flag += "  <<< %d VANISHED, NO REASON" % r["vanished"]
        print("%s  %-22s %-44s disk=%-5s new=%-5s +%-3s -%-3s %s%s" % (
            time.strftime("%m-%d %H:%M:%S", time.localtime(r["ts"])), r.get("proc", "?")[:22],
            (r.get("caller") or "")[:44], r.get("disk_nodes"), r.get("new_nodes"),
            r.get("added"), r.get("vanished"), r.get("reason") or "", flag))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--tail":
        _tail(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
    else:
        print(__doc__)
