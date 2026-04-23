#!/usr/bin/env python3
"""
ORION CHAT - The unified Frankenstein entry point.

One interactive loop that wires every layer of the Orion brain together:

    Layer 5   Identity        baked into model via Ollama Modelfile
    Layer 4   MCP tools       same tool set, but via JSON-RPC (separate entry)
    Layer 3   Tool calling    model actively queries and writes memory
    Layer 2   Identity push   injected as system prompt even if Modelfile lacks it
    Layer 1   Memory          graph + temporal decay + contradiction detection
    Layer 0   Static context  orion-brain-portable identity files

When you type `orion chat`, every one of those is active at once.
This is the moment the brain feels like one thing.

Usage:
    orion chat                            # default: orion-qwen3 via local Ollama
    orion chat --fuel qwen3:14b           # any Ollama model with tool support
    orion chat --fuel orion-deepseek      # reasoning-grade (tool support varies)
    orion chat --endpoint http://...:4000/v1 --fuel orion-deepseek

Slash commands inside the loop:
    /facts      list recent memories ranked by decayed confidence
    /contested  list unresolved contradictions
    /layers     show which layers are active for this session
    /selfcheck  run the perceive -> reason -> act cycle (MCP gap repair)
    /reflect    reflect on this session now, integrate durable facts
    /fuel <m>   switch to a different model mid-conversation
    /help       this list
    /exit       quit
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

import orion_brain_portable as obp  # noqa: E402
from orion_tools import TOOL_SCHEMAS, execute_tool, _get_graph  # noqa: E402
import orion_reflect  # noqa: E402


# ----------------------------------------------------------------
# Terminal colors
# ----------------------------------------------------------------

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
PURPLE = "\033[95m"
RED = "\033[91m"
WHITE = "\033[97m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


# Ordered by observed tool-calling reliability on Ollama (top = most reliable).
PROVEN_TOOL_FUELS = [
    "orion-qwen3",
    "qwen3:14b",
    "qwen3:8b",
    "llama3.1:8b",
    "orion-deepseek",
    "deepseek-r1:7b",
]


def pick_default_fuel(endpoint: str, api_key: str) -> str | None:
    """Return the highest-ranked installed model from PROVEN_TOOL_FUELS, or None.

    Ollama's OpenAI-compat endpoint returns IDs with :latest suffix; match
    both bare and :latest forms so `orion-qwen3` in the priority list finds
    the installed `orion-qwen3:latest` model.
    """
    try:
        client = OpenAI(base_url=endpoint, api_key=api_key)
        installed = {m.id for m in client.models.list().data}
    except Exception:
        return None
    for name in PROVEN_TOOL_FUELS:
        if name in installed:
            return name
        tagged = f"{name}:latest"
        if tagged in installed:
            return tagged
    return None


def show_splash(fuel: str, endpoint: str) -> None:
    """Banner + active layers so the user feels the brain come online."""
    g = _get_graph()
    contested = g.list_contested()
    identity_preview = obp.get_identity().splitlines()[0] if obp.get_identity() else "(none)"

    print()
    print(f"{CYAN}  +-----------------------------------------------+{RESET}")
    print(f"{CYAN}  |{BOLD}            O R I O N                          {RESET}{CYAN}|{RESET}")
    print(f"{CYAN}  |{DIM}       Unified Brain - chat mode             {RESET}{CYAN}|{RESET}")
    print(f"{CYAN}  +-----------------------------------------------+{RESET}")
    print()
    print(f"  {GREEN}Active layers:{RESET}")
    print(f"    {PURPLE}[5]{RESET} Identity via Modelfile   {DIM}(fuel: {fuel}){RESET}")
    print(f"    {PURPLE}[4]{RESET} MCP server tools         {DIM}(orion_mcp_server.py){RESET}")
    print(f"    {PURPLE}[3]{RESET} Tool calling             {DIM}({len(TOOL_SCHEMAS)} tools exposed){RESET}")
    print(f"    {PURPLE}[2]{RESET} Identity system prompt   {DIM}({len(obp.get_identity())} chars injected){RESET}")
    print(f"    {PURPLE}[1]{RESET} Temporal memory          {DIM}({len(g.nodes)} nodes, "
          f"{len(contested)} contested){RESET}")
    print(f"    {PURPLE}[0]{RESET} Static context           {DIM}(ORION-CONTEXT identity file){RESET}")
    print()
    print(f"  {DIM}Endpoint: {endpoint}{RESET}")
    if contested:
        print(f"  {YELLOW}WARNING: {len(contested)} contested memories — type /contested to review{RESET}")
    print()
    print(f"  {DIM}Commands: /facts /contested /layers /selfcheck /reflect /fuel <m> /help /exit{RESET}")
    print()


def show_facts(limit: int = 10) -> None:
    g = _get_graph()
    nodes = g.recall(limit=limit)
    if not nodes:
        print(f"  {DIM}No memories yet.{RESET}")
        return
    import time as _t
    now = _t.time()
    print(f"  {CYAN}Top memories (ranked by decayed confidence):{RESET}")
    for n in nodes:
        # decayed confidence via the shared helper
        eff = obp.decayed_confidence(n, now=now, half_life_table=g.half_life_days)
        age_days = (now - n.get("last_confirmed_at", n["created"])) / 86400
        flag = f" {YELLOW}[contested]{RESET}" if n.get("contested_with") else ""
        print(f"    {DIM}eff={eff:.2f}  age={age_days:.1f}d  type={n['type']}{RESET}{flag}")
        print(f"      {n['content'][:160]}")
    print()


def show_contested() -> None:
    g = _get_graph()
    contested = g.list_contested()
    if not contested:
        print(f"  {GREEN}No contested memories.{RESET}")
        return
    print(f"  {YELLOW}Contested memories (both sides kept until resolved):{RESET}")
    for c in contested:
        print(f"    id={c['id']}  <-> {c['contested_with']}")
        print(f"      {c['content']}")
    print()
    print(f"  {DIM}Use orion_resolve_contradiction via the model, or edit graph by hand.{RESET}")
    print()


def show_layers(fuel: str, endpoint: str) -> None:
    g = _get_graph()
    print(f"  {CYAN}Universal brain layers — current session:{RESET}")
    print(f"    Fuel:        {fuel}")
    print(f"    Endpoint:    {endpoint}")
    print(f"    Identity:    {len(obp.get_identity())} chars loaded")
    print(f"    Memory:      {len(g.nodes)} nodes, {len(g.list_contested())} contested")
    print(f"    Tools:       {', '.join(t['function']['name'] for t in TOOL_SCHEMAS)}")
    print(f"    Half-lives:  {', '.join(f'{k}={v}' for k, v in list(g.half_life_days.items())[:4])}, ...")
    print()


def stream_round(
    client: OpenAI,
    messages: list[dict],
    fuel: str,
    max_rounds: int = 8,
) -> str:
    """Tool-call loop. Shows tool activity inline. Returns the final answer."""
    for _ in range(max_rounds):
        resp = client.chat.completions.create(
            model=fuel,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.5,
        )
        msg = resp.choices[0].message

        entry: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
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
        messages.append(entry)

        if not msg.tool_calls:
            return msg.content or ""

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args_preview = json.loads(tc.function.arguments or "{}")
            except Exception:
                args_preview = tc.function.arguments
            print(f"  {DIM}-> {name}({json.dumps(args_preview)[:120]}){RESET}")
            try:
                result = execute_tool(name, tc.function.arguments)
            except Exception as e:
                result = f"ERROR: {e.__class__.__name__}: {e}"
            preview = result[:200].replace("\n", " | ")
            print(f"  {DIM}<- {preview}{RESET}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
    return f"{YELLOW}[exceeded max_rounds]{RESET}"


def _lookup_user_label(graph) -> str:
    """Read the user's preferred form-of-address from graph_memory.

    Falls back to 'you' (neutral, no assumption) if the user hasn't set one.
    """
    try:
        import re
        for node in graph.nodes.values():
            if node.get("type") != "preference":
                continue
            tags = node.get("tags") or set()
            if isinstance(tags, (list, tuple)):
                tags = set(tags)
            if "address" not in tags and "form-of-address" not in tags:
                continue
            content = node.get("content", "")
            m = re.search(r"addressed as:\s*'([^']+)'", content)
            if m:
                return m.group(1).lower()
            if "does not want any honorific" in content:
                return ""  # user explicitly wanted no honorific
    except Exception:
        pass
    return "you"


def chat(fuel: str, endpoint: str, api_key: str) -> int:
    client = OpenAI(base_url=endpoint, api_key=api_key)

    # Look up user's preferred form of address. Defaults to "you" (neutral)
    # rather than assuming "sir". User sets this during proto-Orion onboarding.
    _user_label = _lookup_user_label(_get_graph())
    _prompt_label = _user_label or "you"

    show_splash(fuel, endpoint)

    # Wake-up reflection — semantic, not timed. Orion decides if enough has
    # changed since last reflection to be worth reviewing recent context.
    #
    # CRITICAL GUARDS (learned the hard way on Pi 5 CPU-only qwen3:8b):
    #   1. Skip if graph is empty/near-empty — nothing to contextualize against
    #   2. Skip if the conversation window only contains test/preflight entries
    #   3. Allow user override via ORION_SKIP_WAKE_REFLECT=1 (useful on slow
    #      hardware where a 5-minute wake wait is not acceptable)
    import os as _os
    if _os.environ.get("ORION_SKIP_WAKE_REFLECT", "").lower() in ("1", "true", "yes"):
        pass  # explicit user opt-out
    elif len(_get_graph().nodes) < 3:
        # Fresh brain — no prior context worth reflecting on. Skip silently.
        pass
    elif orion_reflect.should_reflect_on_wake(min_gap_hours=1.0):
        try:
            recent = obp._read_orion_conversations(limit=40)
            # Drop test/preflight/smoke entries — they're never worth reflecting on
            def _meaningful(entry):
                iface = (entry.get("interface") or "").lower()
                if iface in ("preflight", "g4-smoke", "g5-smoke"):
                    return False
                text = (entry.get("user") or entry.get("text") or "")
                if text.startswith("[preflight") or text.startswith("[g4-"):
                    return False
                return bool(text.strip())

            window = [
                {"role": "user", "text": m.get("user") or m.get("text", "")}
                for m in recent[-30:] if _meaningful(m)
            ]
            # Need at least 2 real exchanges to reflect against — a single
            # message isn't a context worth a full LLM turn.
            if len(window) >= 2:
                print(f"  {DIM}Catching up on recent context...{RESET}")
                r = orion_reflect.reflect(window, reason="wake",
                                          model=fuel, endpoint=endpoint, api_key=api_key)
                if r.get("written"):
                    print(f"  {GREEN}Integrated {r['written']} new facts from recent context."
                          f" {r['skipped_dup']} re-confirmed.{RESET}")
                elif r.get("candidate_count", 0) > 0:
                    print(f"  {DIM}Reviewed recent context — nothing new to integrate.{RESET}")
                print()
        except Exception as e:
            # Reflection failure must never block chat
            print(f"  {DIM}[reflection skipped: {e}]{RESET}")

    # Wake-trigger cognitive cycle — surface-only at wake. Runs in non-
    # interactive (silent-except-status) mode so Orion notices integration
    # gaps without blocking the user's first prompt. If gaps exist, a hint
    # is printed pointing to /selfcheck for the full consult/apply loop.
    try:
        import orion_cycle
        wake_ctx = orion_cycle.CycleContext(
            trigger="wake",
            interactive=False,  # wake should never prompt — user hasn't spoken yet
        )
        wake_outcome = orion_cycle.run(wake_ctx, ui=orion_cycle.SilentUI())
        unwired_mcp = sum(
            1 for io in wake_outcome.issue_outcomes
            if io.issue.kind == "missing_orion_brain_in_mcp"
        )
        if unwired_mcp > 0:
            print(f"  {YELLOW}{unwired_mcp} tool(s) on this host speak MCP but don't have "
                  f"orion-brain wired — type /selfcheck to review.{RESET}")
            print()
    except Exception as e:
        # Wake-cycle failure must never block chat
        print(f"  {DIM}[wake cycle skipped: {e}]{RESET}")

    messages: list[dict] = [
        {"role": "system", "content": obp.get_identity()},
    ]

    # Track session messages separately so session-end reflection can look at
    # just this conversation, not the system prompt
    session_exchanges: list[dict] = []

    while True:
        try:
            user_input = input(f"  {BOLD}{WHITE}{_prompt_label}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd, *rest = user_input[1:].split(maxsplit=1)
            arg = rest[0] if rest else ""
            if cmd in ("exit", "quit", "q"):
                # Session-end reflection — Orion reviews what just happened
                # and integrates before shutting down. Chosen moment, not timer.
                if session_exchanges:
                    try:
                        r = orion_reflect.reflect(session_exchanges, reason="session-end",
                                                  model=fuel, endpoint=endpoint, api_key=api_key)
                        if r.get("written"):
                            print(f"  {GREEN}Session reflection: integrated {r['written']} "
                                  f"durable facts before closing.{RESET}")
                    except Exception as e:
                        print(f"  {DIM}[session reflection skipped: {e}]{RESET}")
                print(f"  {DIM}Standing down, sir.{RESET}")
                return 0
            if cmd == "facts":
                show_facts()
                continue
            if cmd == "contested":
                show_contested()
                continue
            if cmd == "layers":
                show_layers(fuel, endpoint)
                continue
            if cmd == "reflect":
                # Explicit invitation — Orion reviews this session right now
                if not session_exchanges:
                    print(f"  {DIM}Nothing to reflect on yet — we just started.{RESET}")
                    continue
                print(f"  {DIM}Reflecting on this session...{RESET}")
                try:
                    r = orion_reflect.reflect(session_exchanges, reason="explicit",
                                              model=fuel, endpoint=endpoint, api_key=api_key)
                    print(f"  {GREEN}{r['narrative']}{RESET}")
                    for it in r.get("integrations", [])[:8]:
                        flag = f" {YELLOW}[contested]{RESET}" if it.get("contested_with") else ""
                        print(f"    {DIM}[{it['type']}]{RESET} {it['content']}{flag}")
                except Exception as e:
                    print(f"  {RED}Reflection failed: {e}{RESET}")
                continue
            if cmd == "fuel":
                if not arg:
                    print(f"  {DIM}usage: /fuel <model-name>{RESET}")
                    continue
                fuel = arg.strip()
                print(f"  {GREEN}Fuel swapped to: {fuel}{RESET}")
                continue
            if cmd == "selfcheck":
                # Fire the unified cognitive cycle from inside chat. Uses the
                # SimpleCLIUI so proposals print to this terminal and y/N is
                # read from stdin — same stream the user is already typing in.
                print(f"  {DIM}Running perceive → reason → act cycle...{RESET}")
                try:
                    import orion_cycle
                    ctx = orion_cycle.CycleContext(
                        trigger="selfcheck",
                        interactive=True,
                        fuel_preference="claude-cli",
                    )
                    outcome = orion_cycle.run(ctx)
                    print()
                    print(f"  {CYAN}{outcome.human_summary()}{RESET}")
                except Exception as e:
                    print(f"  {RED}Cycle failed: {e.__class__.__name__}: {e}{RESET}")
                continue
            if cmd == "help":
                print(__doc__)
                continue
            print(f"  {RED}Unknown command: /{cmd}{RESET}")
            continue

        messages.append({"role": "user", "content": user_input})
        session_exchanges.append({"role": "user", "text": user_input})
        try:
            answer = stream_round(client, messages, fuel)
        except KeyboardInterrupt:
            print(f"\n  {YELLOW}[interrupted]{RESET}")
            continue
        except Exception as e:
            print(f"  {RED}ERROR: {e.__class__.__name__}: {e}{RESET}")
            continue

        session_exchanges.append({"role": "assistant", "text": answer})

        # Persist each exchange to ~/.orion/brain/conversations/<date>.jsonl so
        # the next wake-up reflection has real direct-chat context to review,
        # not only artifacts from other tools. Truncation to 500 chars happens
        # inside log_conversation — we don't second-guess it here.
        try:
            obp.log_conversation(user_input, answer, interface="orion-chat")
        except Exception:
            # Chat must never die because logging failed. Silent is correct.
            pass

        print(f"  {CYAN}orion>{RESET} {answer}")
        print()


def _cli():
    p = argparse.ArgumentParser(
        prog="orion chat",
        description="Unified Orion brain chat - all 6 layers active.",
    )
    p.add_argument(
        "--fuel",
        default=None,
        help="Ollama model to use (default: highest-ranked installed tool-capable model)",
    )
    p.add_argument(
        "--endpoint",
        default="http://localhost:11434/v1",
        help="OpenAI-compatible API base URL (default: local Ollama)",
    )
    p.add_argument(
        "--api-key",
        default="ollama",
        help="API key (Ollama ignores)",
    )
    args = p.parse_args()

    fuel = args.fuel or pick_default_fuel(args.endpoint, args.api_key)
    if not fuel:
        print(f"{RED}  No tool-capable model found on {args.endpoint}.{RESET}")
        print(f"  Install one of: {', '.join(PROVEN_TOOL_FUELS)}")
        print(f"  Example: ollama pull qwen3:14b")
        return 1

    return chat(fuel, args.endpoint, args.api_key)


if __name__ == "__main__":
    sys.exit(_cli() or 0)
