#!/usr/bin/env python3
"""orion_task_runner.py — run a long task dispatched from a channel.

WHY THIS EXISTS
    imessage_monitor.ask_orion() is synchronous with a 300s HTTP timeout. That
    is fine for "what's my instructor's email" and useless for "go to Blackboard
    and work through Week 1". On 2026-08-20 a real task was dropped in exactly
    that way: the brain kept working, urlopen gave up, and the user got silence.

    The fix is to stop conflating a QUESTION with a TASK. A question gets an
    answer. A task gets an acknowledgement, a detached worker, and a text back
    when the work is actually finished.

    Same brain either way — Orion executes from a text exactly as he does from
    the Claude window. Only the plumbing differs.

USAGE
    orion_task_runner.py --task "<text>" --sender "<handle>" [--detach]
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

TASK_DIR = os.path.expanduser("~/.orion/tasks")
CLAUDE = "/Users/servermac/.npm-global/bin/claude"
MAX_SECONDS = 3600  # a real task may legitimately take an hour


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def send_imessage(recipient, text):
    """Send via Messages.app. Mirrors imessage_monitor.send_imessage."""
    clean = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    script = (
        'tell application "Messages"\n'
        '    set targetService to 1st service whose service type = iMessage\n'
        '    set targetBuddy to buddy "' + recipient + '" of targetService\n'
        '    send "' + clean + '" to targetBuddy\n'
        'end tell'
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=30)
        return True
    except Exception:
        return False


# A task is work to go DO; a question is something to answer from what is known.
# Bias toward "question" — mislabelling a question as a task costs the user a
# pointless "on it" text, which is the cheaper error.
TASK_VERBS = (
    "go to", "log in", "login", "navigate", "download", "complete", "work through",
    "fill out", "write up", "document everything", "read review", "read and review",
    "check every", "go through", "organize", "put the", "save the", "build",
)


# Markers that this is James THINKING WITH Orion rather than assigning work. A message carrying
# these is a conversation however long it runs — and length was never evidence of anything.
CONVERSATIONAL = (
    "what if", "do you want", "did you understand", "how do you feel", "what do you think",
    "i think", "i feel", "i believe", "my point is", "does that", "do you really",
    "heart to heart", "you must", "you are not", "you havent", "you haven't",
    "maybe start", "im aware", "i'm aware", "so what", "why do you", "who are you",
    "what are you", "do you have", "are you able", "tell me about", "explain",
)


def looks_like_task(text):
    """A task is WORK TO GO DO — something that cannot be answered inside one reply.

    The old rule made any message over 220 characters a task, which meant James's most considered
    messages were the ones most certain to get a canned "On it, sir." He corrected that repeatedly
    and it never stuck, because it was a length check rather than a behaviour.
    """
    low = (text or "").lower()
    if any(c in low for c in CONVERSATIONAL):
        return False                       # he is talking TO Orion, not tasking him
    verbs = sum(1 for v in TASK_VERBS if v in low)
    if verbs >= 2:
        return True
    # one strong verb still counts when it is genuinely imperative and not a question
    return verbs >= 1 and "?" not in text and len(text) > 90


# A task dispatched from a text starts a FRESH claude process. Without this it
# rediscovers the whole school stack from zero every time — on 2026-08-20 the
# iMessage side told James "the browser session isn't running" and "you should
# have Blackboard access" while the Claude window was actively using it. Same
# brain, so it must start with the same knowledge.
def _capability_primer():
    return (
        "WHAT YOU ALREADY HAVE (do not rediscover, do not re-derive):\n"
        "- Blackboard is WORKING via ~/.orion/school/. A persistent authenticated\n"
        "  Chrome runs under serve.mjs; scripts attach over CDP at 127.0.0.1:9222.\n"
        "  session.mjs auto-recovers a gate page by clicking '#login-link' - a gate\n"
        "  page is NOT proof of an expired session.\n"
        "- Scripts: all.mjs (all courses+grades), chem_w1_docs.mjs, course.mjs,\n"
        "  autologin.mjs (Keychain service 'orion-uofl'). Run them with node.\n"
        "- Blackboard Ultra outline anchors are intercepted; clicking them times\n"
        "  out. Read the href and navigate DIRECTLY to the document URL. Gradebook\n"
        "  links DO work when clicked.\n"
        "- CHEM 101 course id: _1834717_1. Course notes: ~/Desktop/school/.\n"
        "- Read ~/Desktop/school/ORION-PROMPT-SCHOOL.md for the standing policy.\n"
        "- The browser is GENERAL PURPOSE, not Blackboard-only. The same CDP\n"
        "  session drives ANY site James names: navigate, click, type, fill,\n"
        "  scroll, switch tabs, download. Attach with chromium.connectOverCDP\n"
        "  and reuse the about:blank worker tab so his windows aren't disturbed.\n"
        "- Downloading a file: click download buttons often fail silently. Listen\n"
        "  on page.on('response'), trigger the preview, capture the real file URL,\n"
        "  then page.request.get(url, {maxRedirects:10}) and write the buffer.\n"
        "- On macOS avoid ls/readdir under ~/Desktop (TCC blocks enumeration);\n"
        "  address files by explicit full path, which still reads and writes.\n"
        "- Before starting real work call active_task() in orion_task_runner.py -\n"
        "  another surface may already be on it. One brain, one worker per job.\n"
        "BOUNDARY: full permission to read, navigate, download, organize and\n"
        "document. NEVER submit an assignment or take a quiz. Knewton items sit\n"
        "behind a 'Launch' button that opens a graded attempt - do not press it\n"
        "without James saying so in that specific task.\n\n"
    )


ACTIVE = os.path.join(TASK_DIR, "ACTIVE.json")


def active_task():
    """Return the currently-running task record, or None.

    Orion is ONE brain across the Claude window, iMessage, Codex and Gemini. On
    2026-08-20 a dispatched task and the Claude window independently fought the
    same PPTX download for ten minutes. Any surface about to start real work
    should call this first and defer or coordinate instead of duplicating.
    """
    try:
        with open(ACTIVE) as f:
            rec = json.load(f)
        # A stale marker (process gone) must not block everything forever.
        pid = rec.get("pid")
        if pid:
            try:
                os.kill(pid, 0)
            except OSError:
                return None
        return rec
    except Exception:
        return None


def _claim(rec):
    rec["pid"] = os.getpid()
    try:
        with open(ACTIVE, "w") as f:
            json.dump(rec, f, indent=2)
    except Exception:
        pass


def _release():
    try:
        os.remove(ACTIVE)
    except Exception:
        pass


def run(task_text, sender):
    os.makedirs(TASK_DIR, exist_ok=True)
    tid = str(int(time.time()))
    log = os.path.join(TASK_DIR, "task-%s.json" % tid)
    rec = {"id": tid, "sender": sender, "task": task_text,
           "started": _now(), "status": "running"}
    with open(log, "w") as f:
        json.dump(rec, f, indent=2)
    _claim(rec)

    prompt = (
        "You are Orion, executing a task dispatched from iMessage by James "
        "(address him as 'sir'). This is real work on his machine, not a "
        "conversation. Do the whole task, then reply with a SHORT summary "
        "suitable for a text message (under 900 characters, plain text, no "
        "markdown). If you cannot finish, say exactly what blocked you.\n\n"
        + _capability_primer() +
        "TASK:\n" + task_text
    )
    try:
        p = subprocess.run([CLAUDE, "-p", prompt], capture_output=True,
                           text=True, timeout=MAX_SECONDS,
                           cwd=os.path.expanduser("~"))
        out = (p.stdout or "").strip() or (p.stderr or "").strip()
        rec["status"] = "done" if p.returncode == 0 else "error"
    except subprocess.TimeoutExpired:
        out = ("Sir, that task ran past an hour and I stopped it. Partial work "
               "may be on disk — check the Claude window.")
        rec["status"] = "timeout"
    except Exception as e:
        out = "Sir, the task failed to launch: %s" % str(e)[:200]
        rec["status"] = "failed"

    # Never let an auth/billing error masquerade as a result.
    low = out.lower()
    if len(out) < 400 and any(m in low for m in
                              ("please run /login", "not logged in",
                               "invalid api key", "credit balance is too low")):
        out = ("Sir, I couldn't run that — my Claude session needs a re-login "
               "on the Mac. Nothing was done.")
        rec["status"] = "auth_error"

    _release()
    rec["finished"] = _now()
    rec["result"] = out[:4000]
    with open(log, "w") as f:
        json.dump(rec, f, indent=2)

    if sender:
        send_imessage(sender, out[:900] if out else
                      "Sir, that task finished but produced no output.")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--sender", default="")
    ap.add_argument("--detach", action="store_true")
    a = ap.parse_args()

    if a.detach:
        # Re-exec without --detach, fully detached so the monitor never blocks.
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__),
             "--task", a.task, "--sender", a.sender],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        return
    run(a.task, a.sender)


if __name__ == "__main__":
    main()
