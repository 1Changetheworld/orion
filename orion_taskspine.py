#!/usr/bin/env python3
"""orion_taskspine.py — durable working memory for long, multi-step tasks.

The thesis, applied to TASKS. Orion already pulled *long-term memory* out of
the model (orion_memory). But a multi-step task still lived in the fuel's
context window, so a CLI timeout or rate-limit lost the task's progress even
though memory survived. This module makes the same move for the task itself:
pull it out of the fuel and into the brain.

A task is an append-only log of steps on disk. The fuel call is a pure
transition: (goal + steps so far) -> (one next step). If a model times out or
a whole host dies mid-task, a fresh fuel on any host loads the log and resumes
exactly where the last one stopped. The brain is the state machine; the model
merely advances it one step.

Append-only + HLC-stamped => the log is a CRDT => orion_gossip can replicate
in-flight tasks across the mesh for free, so a task survives model death AND
host death.

Storage:  ~/.orion/tasks/<task_id>.jsonl   (one JSON record per line)
            line 0  = {"kind":"task",  id, goal, created, hlc, status}
            line N  = {"kind":"step",  idx, role, content, status, fuel, hash, hlc}
            last    = {"kind":"task",  id, status:"complete"|"failed", hlc}  (footer)

Deliberately NOT on NATS: task state needs durability, which is a log/ledger
concern, not a message-bus concern. The substrate is a firehose; this is the
ledger the firehose can't be.

CLI:
    python orion_taskspine.py run "research X and write a summary"
    python orion_taskspine.py create "goal"      -> prints task_id
    python orion_taskspine.py advance <task_id>   # one step
    python orion_taskspine.py resume <task_id>    # advance to completion
    python orion_taskspine.py status <task_id>
    python orion_taskspine.py list
"""

import hashlib
import json
import os
import socket
import sys
import time
import uuid

ORION_HOME = os.environ.get("ORION_BRAIN_DIR") or os.path.expanduser("~/.orion")
TASKS_DIR = os.path.join(ORION_HOME, "tasks")
HOST = socket.gethostname().split(".")[0]

# A task is "done" when the fuel emits this sentinel as its whole reply.
DONE_SENTINEL = "TASK COMPLETE"
# Safety rail: never let a single run loop forever burning fuel.
DEFAULT_MAX_STEPS = 25

_hlc_counter = [0]


def _hlc():
    """Hybrid logical clock stamp: wall_ms-counter-host.

    Monotonic + host-tagged so the append-only log is a conflict-free CRDT
    that orion_gossip can merge across hosts without coordination.
    """
    _hlc_counter[0] += 1
    return "%d-%04d-%s" % (int(time.time() * 1000), _hlc_counter[0] % 10000, HOST)


def _hash(role, content):
    return hashlib.sha256(("%s\x00%s" % (role, content)).encode("utf-8")).hexdigest()[:16]


def _task_path(task_id):
    return os.path.join(TASKS_DIR, "%s.jsonl" % task_id)


def _append(task_id, record):
    os.makedirs(TASKS_DIR, exist_ok=True)
    record.setdefault("hlc", _hlc())
    with open(_task_path(task_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_task(task_id):
    """Reconstruct task state purely from the on-disk log. This is the whole
    point: state lives in the file, not in any process or model."""
    path = _task_path(task_id)
    if not os.path.exists(path):
        return None
    header, steps, status = None, [], "open"
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("kind") == "task":
                if header is None:
                    header = rec
                # later task records are status updates (footer)
                if rec.get("status"):
                    status = rec["status"]
            elif rec.get("kind") == "step":
                steps.append(rec)
    if header is None:
        return None
    return {"id": task_id, "goal": header.get("goal", ""),
            "created": header.get("created"), "status": status, "steps": steps}


# ═══════════════════════════════════════════════════════════════
# FUEL TRANSITION — the only place a model is touched
# ═══════════════════════════════════════════════════════════════

def _default_fuel(prompt):
    """Route one step through the brain's fuel cascade. Returns (text, engine).

    Imported lazily so the module is usable (and testable) without a live
    fuel — callers can pass their own fuel_fn.
    """
    try:
        import orion_fuel
        return orion_fuel.get_fuel(prompt, interface="taskspine")
    except Exception as e:
        return None, "none:%s" % type(e).__name__


def _build_prompt(task):
    """Compose the next-step prompt from durable state only."""
    lines = [
        "You are Orion, executing a long task ONE step at a time.",
        "Do exactly one next step toward the goal, then stop.",
        "If the goal is fully met, reply with exactly: " + DONE_SENTINEL,
        "",
        "GOAL: " + task["goal"],
        "",
    ]
    if task["steps"]:
        lines.append("STEPS COMPLETED SO FAR:")
        for s in task["steps"]:
            lines.append("  [%d] %s" % (s["idx"], s["content"][:400]))
        lines.append("")
        lines.append("Produce the NEXT step's work (or %s)." % DONE_SENTINEL)
    else:
        lines.append("Produce the FIRST step's work.")
    return "\n".join(lines)


def create_task(goal):
    task_id = uuid.uuid4().hex[:12]
    _append(task_id, {"kind": "task", "id": task_id, "goal": goal,
                      "created": time.time(), "status": "open"})
    return task_id


def advance(task_id, fuel_fn=None):
    """Advance the task by exactly one durable step. Returns the task state.

    Crash-safe: state is read from disk and the new step is appended to disk
    before returning, so an interruption at any point loses at most the step
    currently being computed — which simply re-runs on resume (idempotent by
    content hash).
    """
    fuel_fn = fuel_fn or _default_fuel
    task = load_task(task_id)
    if task is None:
        raise ValueError("no such task: %s" % task_id)
    if task["status"] in ("complete", "failed"):
        return task

    prompt = _build_prompt(task)
    text, engine = fuel_fn(prompt)

    if not text:
        # Every fuel was unavailable. Do NOT mark failed — leave the task
        # open so a later run (different fuel / host) resumes it untouched.
        _append(task_id, {"kind": "step", "idx": len(task["steps"]),
                          "role": "system", "content": "(no fuel available; task left open for resume)",
                          "status": "stalled", "fuel": engine,
                          "hash": _hash("system", "stall-%d" % len(task["steps"]))})
        return load_task(task_id)

    text = text.strip()
    if text.upper().startswith(DONE_SENTINEL):
        _append(task_id, {"kind": "task", "id": task_id,
                          "status": "complete"})
        return load_task(task_id)

    h = _hash("assistant", text)
    # Idempotency: if the last real step is identical, don't double-write.
    if task["steps"] and task["steps"][-1].get("hash") == h:
        return task
    _append(task_id, {"kind": "step", "idx": len(task["steps"]),
                      "role": "assistant", "content": text,
                      "status": "done", "fuel": engine, "hash": h})
    return load_task(task_id)


def run(goal=None, task_id=None, fuel_fn=None, max_steps=DEFAULT_MAX_STEPS):
    """Create (or resume) a task and advance it to completion, checkpointing
    every step. Resumable: pass an existing task_id to continue it."""
    if task_id is None:
        if not goal:
            raise ValueError("run() needs a goal or a task_id")
        task_id = create_task(goal)
    task = load_task(task_id)
    steps_taken = 0
    while task and task["status"] == "open" and steps_taken < max_steps:
        before = len(task["steps"])
        task = advance(task_id, fuel_fn=fuel_fn)
        steps_taken += 1
        # A stall (no fuel) means stop and leave the task resumable.
        if task["steps"] and task["steps"][-1].get("status") == "stalled":
            break
        if len(task["steps"]) == before and task["status"] == "open":
            break  # no progress; avoid spin
    return task


def list_tasks():
    if not os.path.isdir(TASKS_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(TASKS_DIR)):
        if fn.endswith(".jsonl"):
            t = load_task(fn[:-6])
            if t:
                out.append(t)
    return out


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def _print_task(t):
    print("task %s  [%s]  %d steps" % (t["id"], t["status"], len(t["steps"])))
    print("  goal: %s" % t["goal"])
    for s in t["steps"]:
        print("  [%d] (%s via %s) %s" % (s["idx"], s["status"], s.get("fuel", "?"),
                                         s["content"][:120]))


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "create":
        print(create_task(" ".join(argv[1:])))
    elif cmd == "run":
        _print_task(run(goal=" ".join(argv[1:])))
    elif cmd == "advance":
        _print_task(advance(argv[1]))
    elif cmd == "resume":
        _print_task(run(task_id=argv[1]))
    elif cmd == "status":
        t = load_task(argv[1])
        if t:
            _print_task(t)
        else:
            print("no such task")
    elif cmd == "list":
        for t in list_tasks():
            print("%s  [%s]  %d steps  — %s" % (t["id"], t["status"],
                                                len(t["steps"]), t["goal"][:60]))
    else:
        print("unknown command: %s" % cmd)
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
