#!/usr/bin/env python3
"""
ORION TOOL-CALLING LOOP - Reference implementation of Layer 3.

Takes a user message, calls a local model with Orion's brain tools
available, handles any tool_calls the model emits, loops until the
model produces a final text answer, returns that answer.

Default: runs against qwen3:14b on local Ollama (proven tool support).
Works with any OpenAI-API-compatible endpoint and any model that
implements tool calling — DeepSeek-R1, Llama 3.1+, Mistral Nemo, etc.

Usage:
    python orion_tool_chat.py "what do you remember about ORIONS HOME?"
    python orion_tool_chat.py --model qwen3:14b "save that I prefer dark mode"
    python orion_tool_chat.py --endpoint http://localhost:4000/v1 "..."

This is the reference Layer 3 pattern. Integrating it into the LiteLLM
proxy as automatic server-side tool execution is a follow-on step.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

from openai import OpenAI  # noqa: E402

from orion_tools import TOOL_SCHEMAS, execute_tool  # noqa: E402
import orion_brain_portable as obp  # noqa: E402


def run(
    user_message: str,
    model: str = "qwen3:14b",
    endpoint: str = "http://localhost:11434/v1",
    api_key: str = "ollama",
    max_rounds: int = 8,
    verbose: bool = True,
) -> str:
    """Run a full tool-calling loop. Returns the final assistant text."""
    client = OpenAI(base_url=endpoint, api_key=api_key)

    messages: list[dict] = [
        {"role": "system", "content": obp.get_identity()},
        {"role": "user", "content": user_message},
    ]

    for round_num in range(1, max_rounds + 1):
        if verbose:
            print(f"[round {round_num}] calling {model}...", file=sys.stderr)

        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.5,
        )
        msg = resp.choices[0].message

        # Append assistant turn so the model has full context for follow-ups
        assistant_entry: dict = {
            "role": "assistant",
            "content": msg.content or "",
        }
        if msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_entry)

        # No tool calls = final answer
        if not msg.tool_calls:
            return msg.content or ""

        # Execute each tool call and feed results back
        for tc in msg.tool_calls:
            name = tc.function.name
            args = tc.function.arguments
            if verbose:
                print(f"  -> tool {name}({args})", file=sys.stderr)
            try:
                result = execute_tool(name, args)
            except Exception as e:
                result = f"ERROR: {e.__class__.__name__}: {e}"
            if verbose:
                preview = result[:200].replace("\n", " | ")
                print(f"  <- {preview}", file=sys.stderr)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return "[orion-tool-chat] exceeded max_rounds without a final answer"


def _cli():
    p = argparse.ArgumentParser(description="Orion Layer 3 tool-calling loop")
    p.add_argument("message", help="User question or instruction")
    p.add_argument("--model", default="qwen3:14b", help="Model name")
    p.add_argument("--endpoint", default="http://localhost:11434/v1",
                   help="OpenAI-compatible API base URL")
    p.add_argument("--api-key", default="ollama", help="API key (Ollama ignores)")
    p.add_argument("--max-rounds", type=int, default=8,
                   help="Max tool-call iterations")
    p.add_argument("--quiet", action="store_true", help="Silence tool trace")
    args = p.parse_args()

    answer = run(
        user_message=args.message,
        model=args.model,
        endpoint=args.endpoint,
        api_key=args.api_key,
        max_rounds=args.max_rounds,
        verbose=not args.quiet,
    )
    print(answer)


if __name__ == "__main__":
    _cli()
