#!/usr/bin/env python3
"""orion_task_gossip.py — replicate task-spine logs across the mesh.

orion_taskspine makes a task survive MODEL death (resume on a fresh model,
same host). This makes it survive HOST death too: every appended record is
mirrored to peers over the substrate, so if the owning host dies mid-task,
another host already holds the full append-only log and — once the owner's
lease goes stale — takes the task over and finishes it on whatever fuel it has.

Why it's conflict-free: the step log is append-only + HLC-stamped, i.e. a CRDT.
Replication is a union of records deduped by content hash — no merge conflict,
no coordination. Combined with the ownership lease in orion_taskspine, exactly
one host actively advances a task at a time; the rest hold warm replicas.

Subjects:
    orion.task.sync.<task_id>   — one record (step / lease / release / footer)

Run as a service:    python orion_task_gossip.py     (listen + apply remote records)
Called by taskspine: publish(task_id, record)         (best-effort mirror on append)

This is the optional TRANSPORT layer. The task file remains the source of
truth; if the substrate is down, taskspine still works standalone on each host.
"""

import sys
import time

SUBJECT_PREFIX = "orion.task.sync"


def publish(task_id, record):
    """Best-effort mirror of one task record to peers. Never blocks or raises —
    the local file is authoritative; this is only replication."""
    try:
        from orion_substrate import publish as _pub
        _pub("%s.%s" % (SUBJECT_PREFIX, task_id),
             {"task_id": task_id, "record": record})
    except Exception:
        pass


def _on_record(subject, payload):
    """Apply an inbound peer record to the local task log (dedup handles
    re-delivery and our own echoes)."""
    try:
        import orion_taskspine
        if not isinstance(payload, dict):
            return
        task_id = payload.get("task_id")
        record = payload.get("record")
        if task_id and isinstance(record, dict):
            orion_taskspine.apply_remote(task_id, record)
    except Exception:
        pass


def main():
    try:
        from orion_substrate import subscribe
    except Exception as e:
        print("substrate unavailable: %s — task gossip cannot run" % e)
        return 1
    print("orion-task-gossip alive — replicating task spines across the mesh "
          "(subject %s.>)" % SUBJECT_PREFIX)
    subscribe("%s.>" % SUBJECT_PREFIX, _on_record)
    # The substrate runs its own background loop thread; just stay alive.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
