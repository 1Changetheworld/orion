#!/usr/bin/env python3
"""orion_session_save.py — auto-save workflow snapshots into the brain.

Founder ask 2026-05-13 (memorized as node 32): "every CLI session,
every conversation, every workflow auto-documented in brain with
timestamp + context + active thread."

Design philosophy:
  - NOT auto-save individual tool calls. That's noise.
  - Auto-save the WORKFLOW SHAPE: what was being built, what blockers
    were hit, where the thread paused.
  - Free in tokens — pure jsonl parse + heuristic extraction. No
    model call. Brain's "I noticed" surface, not its judgment.

How it integrates:
  - Claude Code SessionEnd hook calls this script with the session
    UUID. We read ~/.claude/projects/.../UUID.jsonl, extract beats,
    memorize one node per session.
  - Also callable manually:  python orion_session_save.py --save
    or with a specific session id.
  - Combines with v1.8 continuity-on-greeting: next time any CLI
    opens, the resume brief pulls these snapshots so the user feels
    Orion remember without having to ask "where were we?"

Three layers extracted from each session:
  1. WORKFLOW SHAPE — last user prompt, active task subject from
     TaskList state in jsonl, top-3 file paths touched.
  2. THREAD — most recent user prompts (last 3) condensed; tells
     future-Orion what the conversation was about.
  3. PAUSE STATE — last assistant turn's closing words (first 200
     chars) + any open question. Often this is where the user closed
     the lid mid-decision.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


def _find_latest_session_jsonl() -> Path | None:
    """Find the most-recently-written .jsonl across all claude projects."""
    if not CLAUDE_PROJECTS.exists():
        return None
    candidates = []
    for proj in CLAUDE_PROJECTS.iterdir():
        if not proj.is_dir():
            continue
        for f in proj.glob("*.jsonl"):
            candidates.append(f)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _session_jsonl_for_uuid(uuid: str) -> Path | None:
    """Locate the jsonl for a given session UUID across all projects."""
    for proj in CLAUDE_PROJECTS.iterdir():
        if not proj.is_dir():
            continue
        candidate = proj / f"{uuid}.jsonl"
        if candidate.exists():
            return candidate
    return None


def _iter_records(path: Path):
    """Stream jsonl records. Skip lines that don't parse."""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _extract_workflow_shape(path: Path) -> dict:
    """Pull the workflow signal — pure heuristic extraction, no model."""
    last_user_prompt = ""
    user_prompts: list[str] = []
    last_assistant_text = ""
    touched_files: list[str] = []
    tasks_in_progress: list[str] = []
    last_commit_msgs: list[str] = []
    cwd = ""

    for rec in _iter_records(path):
        rtype = rec.get("type")
        if not cwd and rec.get("cwd"):
            cwd = rec.get("cwd", "")
        # Capture last-prompt markers (Claude Code writes these)
        if rtype == "last-prompt" and rec.get("lastPrompt"):
            last_user_prompt = rec["lastPrompt"]
        # User messages (sequenced)
        if rtype == "user":
            msg = rec.get("message", {})
            content = msg.get("content")
            if isinstance(content, str) and content.strip() and not content.startswith("<"):
                user_prompts.append(content)
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                        user_prompts.append(c["text"])
        # Assistant content
        if rtype == "assistant":
            msg = rec.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        t = c.get("text", "")
                        if t:
                            last_assistant_text = t
                    # File touches via tool_use inputs
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        inp = c.get("input", {}) or {}
                        fp = inp.get("file_path") or inp.get("path")
                        if fp and isinstance(fp, str):
                            touched_files.append(fp)
                        cmd = inp.get("command", "")
                        if isinstance(cmd, str):
                            # Pull commit subjects out of bash commands
                            for m in re.finditer(r'git commit -m ["\']([^"\']{8,120})', cmd):
                                last_commit_msgs.append(m.group(1).strip())
        # Task list attachments (Claude Code embeds task state in attachments)
        if rtype == "user":
            attach = rec.get("attachment")
            if isinstance(attach, dict) and attach.get("type") == "task_reminder":
                for item in attach.get("content", []) or []:
                    if isinstance(item, dict) and item.get("status") == "in_progress":
                        subj = item.get("subject")
                        if subj:
                            tasks_in_progress.append(subj)

    # Dedupe + trim
    def _last_unique(seq, n):
        seen, out = set(), []
        for x in reversed(seq):
            if x and x not in seen:
                seen.add(x)
                out.append(x)
            if len(out) >= n:
                break
        return list(reversed(out))

    return {
        "session_file": str(path),
        "cwd": cwd,
        "last_user_prompt": last_user_prompt[:600],
        "recent_user_prompts": [p[:400] for p in _last_unique(user_prompts, 5)],
        "last_assistant_closing": last_assistant_text[:600],
        "tasks_in_progress": _last_unique(tasks_in_progress, 5),
        "touched_files": _last_unique(touched_files, 8),
        "commits_landed": _last_unique(last_commit_msgs, 5),
    }


def _format_snapshot_for_memorize(shape: dict, session_id: str) -> str:
    """Render the snapshot as a single durable memory body."""
    lines = [
        f"SESSION SNAPSHOT {session_id}",
        f"  cwd: {shape.get('cwd', '(unknown)')}",
    ]
    if shape["tasks_in_progress"]:
        lines.append("  in-progress: " + " | ".join(shape["tasks_in_progress"][:3]))
    if shape["commits_landed"]:
        lines.append("  committed: " + " | ".join(shape["commits_landed"][:3]))
    if shape["last_user_prompt"]:
        lines.append(f"  last user ask: {shape['last_user_prompt'][:200]}")
    if shape["last_assistant_closing"]:
        lines.append(f"  paused at: {shape['last_assistant_closing'][:200]}")
    if shape["touched_files"]:
        lines.append("  files touched: " + " ".join(
            os.path.basename(f) for f in shape["touched_files"][:5]
        ))
    return "\n".join(lines)


def _memorize_via_brain(content: str, tags: list[str]) -> bool:
    """Best-effort push to the local brain HTTP endpoint.

    Tries 127.0.0.1:5555 first (host has a brain), then bails silently
    on failure. The hook is fire-and-forget — never block session exit.
    """
    import urllib.request
    payload = json.dumps({
        "message": f"[auto-save] memorize the following session snapshot: {content}",
        "interface": "session_save",
    }).encode()
    for url in ("http://127.0.0.1:5555/ask", "http://127.0.0.1:5555/"):
        try:
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                if r.status == 200:
                    return True
        except Exception:
            continue
    return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", help="Specific session UUID to snapshot")
    ap.add_argument("--latest", action="store_true",
                    help="Snapshot the most-recently-written session")
    ap.add_argument("--print-only", action="store_true",
                    help="Render the snapshot but skip the brain write")
    args = ap.parse_args(argv[1:])

    if args.session_id:
        path = _session_jsonl_for_uuid(args.session_id)
    else:
        path = _find_latest_session_jsonl()
    if path is None:
        print("no session jsonl found", file=sys.stderr)
        return 1

    sid = path.stem
    shape = _extract_workflow_shape(path)
    body = _format_snapshot_for_memorize(shape, sid)
    print(body)

    if args.print_only:
        return 0

    ok = _memorize_via_brain(body, tags=["session-snapshot", "auto-save", sid[:8]])
    print(f"\nbrain-write: {'ok' if ok else 'failed (snapshot still printed above)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
