"""overnight_agent/run.py — drive the build-analysis agent via Anthropic API.

Usage:
    export ANTHROPIC_API_KEY="<key>"
    python overnight_agent/run.py

Writes REPORT.md when complete. Streams progress to stdout.

Designed to be the simplest possible driver: one Claude conversation
with tool use, looping until the model says it's done writing the
report. No external dependencies beyond anthropic SDK.

Founder rule (no-fabrication): the agent must cite real files. If
ANTHROPIC_API_KEY is missing, this script refuses to run rather
than silently fail.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
REPORT_PATH = Path(__file__).parent / "REPORT.md"

# The SYSTEM PROMPT BEGINS marker splits the meta from the actual prompt
if "# SYSTEM PROMPT BEGINS" in PROMPT:
    PROMPT = PROMPT.split("# SYSTEM PROMPT BEGINS", 1)[1].strip()


def require_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        print("This script is designed for an explicit, founder-approved overnight run.")
        print("Set the key, then re-run:")
        print('    export ANTHROPIC_API_KEY="sk-ant-..."')
        sys.exit(2)
    return key


def main() -> int:
    require_key()
    try:
        import anthropic
    except ImportError:
        print("Installing anthropic SDK...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "anthropic"])
        import anthropic

    client = anthropic.Anthropic()
    print(f"Overnight agent starting. Output: {REPORT_PATH}")
    print(f"Repo: {REPO}")
    print(f"Model: claude-opus-4-7")
    print()

    # Tool definitions — minimal: read files, list dirs, run grep/git
    tools = [
        {
            "name": "read_file",
            "description": "Read a file from the local filesystem.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "list_dir",
            "description": "List the contents of a directory.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "grep",
            "description": "ripgrep over the repo. Args is the full rg command after 'rg'.",
            "input_schema": {
                "type": "object",
                "properties": {"args": {"type": "string"}},
                "required": ["args"],
            },
        },
        {
            "name": "git",
            "description": "Run a git command in the repo. Args is the command after 'git'.",
            "input_schema": {
                "type": "object",
                "properties": {"args": {"type": "string"}},
                "required": ["args"],
            },
        },
        {
            "name": "write_report",
            "description": "Write the final REPORT.md. Call exactly once at the end.",
            "input_schema": {
                "type": "object",
                "properties": {"markdown": {"type": "string"}},
                "required": ["markdown"],
            },
        },
    ]

    def tool_handler(name: str, args: dict) -> str:
        if name == "read_file":
            p = Path(args["path"]).expanduser()
            if not p.is_absolute():
                p = REPO / p
            try:
                return p.read_text(encoding="utf-8")[:50_000]
            except Exception as e:
                return f"[error reading {p}: {e}]"
        if name == "list_dir":
            p = Path(args["path"]).expanduser()
            if not p.is_absolute():
                p = REPO / p
            try:
                return "\n".join(sorted(x.name + ("/" if x.is_dir() else "")
                                       for x in p.iterdir()))[:20_000]
            except Exception as e:
                return f"[error listing {p}: {e}]"
        if name == "grep":
            try:
                out = subprocess.run(
                    ["rg"] + args["args"].split(),
                    cwd=REPO, capture_output=True, text=True, timeout=30,
                )
                return (out.stdout or out.stderr)[:30_000]
            except Exception as e:
                return f"[grep error: {e}]"
        if name == "git":
            try:
                out = subprocess.run(
                    ["git"] + args["args"].split(),
                    cwd=REPO, capture_output=True, text=True, timeout=30,
                )
                return (out.stdout or out.stderr)[:30_000]
            except Exception as e:
                return f"[git error: {e}]"
        if name == "write_report":
            REPORT_PATH.write_text(args["markdown"], encoding="utf-8")
            return f"[report written to {REPORT_PATH} — {len(args['markdown'])} chars]"
        return f"[unknown tool: {name}]"

    messages = [{"role": "user", "content": PROMPT}]
    turns = 0
    MAX_TURNS = 200

    while turns < MAX_TURNS:
        turns += 1
        resp = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=8192,
            tools=tools,
            messages=messages,
        )
        # Collect tool uses + text from response
        tool_results = []
        for block in resp.content:
            if block.type == "text":
                print(f"[turn {turns}] {block.text[:200]}")
            elif block.type == "tool_use":
                print(f"[turn {turns}] using {block.name}({json.dumps(block.input)[:120]})")
                result = tool_handler(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
                if block.name == "write_report":
                    print(f"\n=== REPORT WRITTEN to {REPORT_PATH} after {turns} turns ===")
                    return 0
        messages.append({"role": "assistant", "content": resp.content})
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        elif resp.stop_reason == "end_turn":
            print("[end_turn without write_report — agent finished without producing report]")
            return 1

    print(f"[max turns ({MAX_TURNS}) hit without report]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
