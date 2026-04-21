#!/usr/bin/env python3
"""
ORION CROSS-MODEL MEMORY DEMO

Proves in one command that multiple different local models share
one brain. Writes a fact through model A. Reads it back through
models B and C. Shows the tool calls inline.

Usage:
    python orion_crossmodel_demo.py
    python orion_crossmodel_demo.py --models orion-qwen3 llama3.1:8b qwen3:8b

This is the clearest public-facing demonstration of the moat: the
memory is not in any model. The memory is Orion. The models are fuel.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

from openai import OpenAI  # noqa: E402

import orion_brain_portable as obp  # noqa: E402
from orion_tools import TOOL_SCHEMAS, execute_tool  # noqa: E402


CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
PURPLE = "\033[95m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def run_one_turn(client: OpenAI, model: str, user_msg: str,
                 max_rounds: int = 4) -> str:
    """Single-question tool-calling loop against one model."""
    messages = [
        {"role": "system", "content": obp.get_identity()},
        {"role": "user", "content": user_msg},
    ]
    for _ in range(max_rounds):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.4,
        )
        msg = resp.choices[0].message
        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        messages.append(entry)
        if not msg.tool_calls:
            return msg.content or ""
        for tc in msg.tool_calls:
            try:
                args_preview = json.loads(tc.function.arguments or "{}")
            except Exception:
                args_preview = tc.function.arguments
            print(f"     {DIM}-> {tc.function.name}({json.dumps(args_preview)[:100]}){RESET}")
            try:
                result = execute_tool(tc.function.name, tc.function.arguments)
            except Exception as e:
                result = f"ERROR: {e}"
            preview = result[:150].replace("\n", " | ")
            print(f"     {DIM}<- {preview}{RESET}")
            messages.append({"role": "tool",
                             "tool_call_id": tc.id,
                             "content": result})
    return "[no final answer]"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="+",
                   default=["orion-qwen3", "qwen3:14b", "llama3.1:8b"],
                   help="Three+ Ollama models with tool support")
    p.add_argument("--endpoint", default="http://localhost:11434/v1")
    p.add_argument("--api-key", default="ollama")
    args = p.parse_args()

    client = OpenAI(base_url=args.endpoint, api_key=args.api_key)

    # Verify models are installed
    try:
        installed = {m.id for m in client.models.list().data}
    except Exception as e:
        print(f"ERROR: cannot reach {args.endpoint}: {e}")
        return 1

    usable = []
    for m in args.models:
        if m in installed or f"{m}:latest" in installed:
            usable.append(m if m in installed else f"{m}:latest")
    if len(usable) < 2:
        print(f"Need at least 2 models installed. Found: {usable}")
        print(f"Available: {sorted(installed)[:10]}")
        return 1

    writer = usable[0]
    readers = usable[1:]

    # Unique fact so we know this demo run produced it
    secret = f"Demo-{int(time.time())}"
    fact = (f"James's secret coffee order for this demo run is "
            f"'{secret}' — a dark roast Ethiopian pour-over.")

    print()
    print(f"{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}  ORION CROSS-MODEL MEMORY DEMO{RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    print()
    print(f"  {GREEN}Writer:{RESET}  {writer}")
    print(f"  {GREEN}Readers:{RESET} {', '.join(readers)}")
    print(f"  {GREEN}Secret:{RESET}  {secret}")
    print()

    # WRITE PHASE
    print(f"{YELLOW}[1/2] WRITE via {writer}{RESET}")
    print(f"  user> Remember this: {fact}")
    answer = run_one_turn(client, writer,
                          f"Remember this fact for future reference, and briefly confirm: {fact}")
    print(f"  {writer}> {answer[:240]}")
    print()

    # READ PHASE — each reader queries the brain fresh
    print(f"{YELLOW}[2/2] READ from {len(readers)} other models{RESET}")
    for reader in readers:
        print()
        print(f"  {PURPLE}>>> {reader}{RESET}")
        print(f"  user> What is James's secret coffee order from today's demo?")
        answer = run_one_turn(client, reader,
                              "What is James's secret coffee order from today's demo? "
                              "Use orion_recall. Include the exact code string.")
        # Check if reader found the secret
        hit = secret in answer
        marker = f"{GREEN}[PASS — saw secret {secret}]{RESET}" if hit \
                 else f"{YELLOW}[no secret string in answer]{RESET}"
        print(f"  {reader}> {answer[:320]}")
        print(f"  {marker}")

    print()
    print(f"{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}  If every reader saw '{secret}' in the response,{RESET}")
    print(f"{BOLD}  the brain is genuinely shared across models.{RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
