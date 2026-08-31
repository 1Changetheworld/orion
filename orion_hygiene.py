#!/usr/bin/env python3
"""
orion_hygiene.py — graph housekeeping, on its own schedule.

WHY THIS EXISTS: hygiene (exact-dedup + archive-not-delete) has always run INSIDE
orion_sleep.run_cycle. That was fine while sleep fired on a 3-hour clock. It is not fine once
the salience gate takes over, because the gate deliberately fires far less — only after James
actually says something. Cleanup would silently drop by ~86% and nothing would announce it; the
graph would just start accumulating duplicates again while consolidation looked healthier.

Housekeeping must never depend on whether anyone talked. Many things write to that graph — sleep,
wonder, dream, the MCP server, manual writes — and nothing else deduplicates. Duplicates rot
recall, which is a failure already observed here (stale consolidated memory beating live context).

This changes no behaviour on its own: it calls exactly the same orion_consolidate.consolidate()
that sleep has always called. It just gives it a heartbeat of its own.

  --once     run it (apply=True)
  --report   what it WOULD do, changing nothing (apply=False)
"""
from __future__ import annotations
import json
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/orion-code"))

GRAPH = os.path.expanduser("~/.orion/brain/graph_memory.json")


def run(apply=True):
    try:
        import orion_consolidate
    except Exception as e:
        return {"ok": False, "error": "import failed: %s" % e}
    try:
        res = orion_consolidate.consolidate(GRAPH, apply=apply)
        return {"ok": True, "apply": apply, "ts": time.time(), "result": res}
    except Exception as e:
        return {"ok": False, "apply": apply, "error": str(e)[:200]}


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--report"
    out = run(apply=(arg == "--once"))
    print(json.dumps(out, default=str))
    sys.exit(0 if out.get("ok") else 1)
