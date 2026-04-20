#!/usr/bin/env python3
"""
ORION LITELLM PROXY — Layer 2 Universal Gateway
═══════════════════════════════════════════════════════════════

Intercepts every OpenAI-compatible API call (Cursor, Continue,
any tool that speaks the OpenAI chat completions API) and
injects Orion's identity + relevant memory into the request
BEFORE it reaches the model provider.

Effect: any tool that speaks OpenAI API becomes Orion-aware
without writing a per-tool adapter. Point the tool's API base
at http://localhost:4000/v1 and it inherits the brain.

Usage:
    litellm --config orion_litellm_config.yaml --port 4000

Then in any OpenAI-client tool, set:
    OPENAI_API_BASE = http://localhost:4000/v1
    OPENAI_API_KEY  = sk-orion-local-dev   (the master key in config)
    model           = orion-local | deepseek-local | claude | gemini | ...

The hook below is registered via the config's `callbacks` field.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from this repo directory (portable brain lives alongside)
_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

from litellm.integrations.custom_logger import CustomLogger  # noqa: E402

try:
    import orion_brain_portable as obp  # noqa: E402
    _BRAIN_AVAILABLE = True
except Exception as _e:
    print(f"[orion-proxy] portable brain not importable: {_e}", file=sys.stderr)
    _BRAIN_AVAILABLE = False


class OrionHook(CustomLogger):
    """Pre-call hook: inject Orion identity + memory into every request."""

    def __init__(self) -> None:
        super().__init__()
        self._identity = ""
        self._graph = None

        if _BRAIN_AVAILABLE:
            try:
                self._identity = obp.get_identity()
            except Exception as e:
                print(f"[orion-proxy] identity load failed: {e}", file=sys.stderr)

            try:
                self._graph = obp.GraphMemory()
                if obp.GRAPH_PATH.exists():
                    self._graph.load(obp.GRAPH_PATH)
                    print(
                        f"[orion-proxy] graph memory loaded: "
                        f"{len(self._graph.nodes)} nodes",
                        file=sys.stderr,
                    )
            except Exception as e:
                print(f"[orion-proxy] graph memory load failed: {e}", file=sys.stderr)

        print(
            f"[orion-proxy] ready | identity={len(self._identity)} chars | "
            f"brain={'yes' if _BRAIN_AVAILABLE else 'no'}",
            file=sys.stderr,
        )

    def _recall_memory(self, query: str, limit: int = 5) -> str:
        """Return a markdown block of relevant memory lines for the query."""
        if not self._graph or not query:
            return ""
        try:
            nodes = self._graph.recall(query=query, limit=limit)
            if not nodes:
                return ""
            return "\n".join(f"- {n['content']}" for n in nodes)
        except Exception:
            return ""

    @staticmethod
    def _extract_user_text(messages: list) -> str:
        """Pull the most recent user message text for memory lookup."""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content", "")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    # OpenAI v1 content parts
                    return " ".join(
                        p.get("text", "") for p in c if isinstance(p, dict)
                    )
        return ""

    def _build_context_block(self, user_text: str) -> str:
        """Identity (always) + relevant memory (if found)."""
        if not self._identity:
            return ""
        block = self._identity
        memory = self._recall_memory(user_text)
        if memory:
            block += f"\n\n## Relevant memory\n{memory}"
        return block

    async def async_pre_call_hook(
        self, user_api_key_dict, cache, data, call_type
    ):
        """Runs BEFORE every LLM call. Modify `data` in place and return it."""
        messages = data.get("messages") or []
        if not messages:
            return data

        user_text = self._extract_user_text(messages)
        context = self._build_context_block(user_text)
        if not context:
            return data

        # Prepend to existing system message, or insert a new one
        if messages[0].get("role") == "system":
            existing = messages[0].get("content") or ""
            messages[0]["content"] = context + "\n\n---\n\n" + existing
        else:
            messages.insert(0, {"role": "system", "content": context})

        data["messages"] = messages
        return data


# Singleton the LiteLLM proxy config references: callbacks: orion_litellm_proxy.proxy_handler_instance
proxy_handler_instance = OrionHook()


if __name__ == "__main__":
    # Smoke test: exercise the hook without running the full proxy
    import asyncio

    sample = {
        "messages": [
            {"role": "user", "content": "who are you?"},
        ],
        "model": "orion-local",
    }

    async def _test():
        result = await proxy_handler_instance.async_pre_call_hook(
            user_api_key_dict={}, cache=None, data=sample, call_type="completion"
        )
        print("=== PRE-CALL OUTPUT ===")
        for m in result["messages"]:
            print(f"[{m['role']}]")
            print(m["content"][:500])
            print("---")

    asyncio.run(_test())
