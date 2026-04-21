#!/usr/bin/env python3
"""
ORION LITELLM PROXY - Layer 2+ Ambient Gateway (read AND write)

Every OpenAI-compatible call (Cursor, Continue, any tool speaking the
OpenAI chat completions API) passes through this proxy.

Read path - before the model call:
    Identity + relevant memory get injected into the system prompt.
    Model never sees a "tool call" for this. It just receives context.

Write path - after the model responds (being-not-automation):
    The proxy does NOT extract facts from every response. That would
    be automation. Instead, it reads the USER's message for durable-
    intent signals ("remember", "my X is Y", "I prefer", "save that").
    Only exchanges that cross that semantic threshold get handed to
    orion_reflect.reflect(), which is Orion's judgment function. Most
    chat passes through invisibly; reflection fires on reason.

Effect: every client speaking OpenAI API becomes Orion-aware without
per-tool adapters. Point the tool's API base at http://localhost:4000/v1
and it inherits the brain — reading AND writing.

Usage:
    litellm --config orion_litellm_config.yaml --port 4000

Then in any OpenAI-client tool:
    OPENAI_API_BASE = http://localhost:4000/v1
    OPENAI_API_KEY  = sk-orion-local-dev
    model           = orion-deepseek | orion-local | claude | gemini | ...

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

    # ----------------------------------------------------------------
    # Durable-intent detector - being-not-automation gate for reflection.
    # If this returns False, the exchange passes through without any
    # extraction work. If True, we hand the exchange to reflect() to
    # let Orion decide what (if anything) is worth integrating.
    # ----------------------------------------------------------------

    _DURABLE_PATTERNS = [
        "remember", "don't forget", "save that", "save this",
        "my favorite", "my favourite", "i prefer", "i like",
        "my name is", "my email", "my phone", "i live in",
        "i work at", "my company", "my startup", "my product",
        "i own", "i have a", "i'm building",
        "my goal", "my plan", "my decision", "note that",
        "for the record", "fyi", "just so you know",
    ]

    @classmethod
    def _has_durable_intent(cls, user_text: str) -> bool:
        """Fast pre-filter for whether the USER's message signals durable intent."""
        if not user_text or len(user_text) < 10:
            return False
        t = user_text.lower()
        return any(pat in t for pat in cls._DURABLE_PATTERNS)

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

    async def async_log_success_event(
        self, kwargs, response_obj, start_time, end_time
    ):
        """Runs AFTER a successful LLM call — the ambient write path.

        We do NOT extract facts from every response. That would be
        automation. We check the USER's inbound message for durable-
        intent signals; only when present do we hand the exchange to
        orion_reflect.reflect() and let Orion decide what to integrate.
        The proxy's job is the gate; the judgment is the brain's.
        """
        try:
            messages = (kwargs or {}).get("messages") or []
            user_text = self._extract_user_text(messages)
            if not self._has_durable_intent(user_text):
                return  # no reason to reflect on this exchange

            # Extract assistant reply from the response
            assistant_text = ""
            try:
                choices = getattr(response_obj, "choices", None) or \
                          (response_obj.get("choices") if isinstance(response_obj, dict) else None)
                if choices:
                    first = choices[0]
                    msg = getattr(first, "message", None) or \
                          (first.get("message") if isinstance(first, dict) else None)
                    if msg:
                        assistant_text = getattr(msg, "content", None) or \
                                         (msg.get("content") if isinstance(msg, dict) else "") or ""
            except Exception:
                assistant_text = ""

            window = [
                {"role": "user", "text": user_text},
            ]
            if assistant_text:
                window.append({"role": "assistant", "text": assistant_text})

            # Lazy import to avoid hard dependency if reflect module is missing
            try:
                import orion_reflect
            except Exception as e:
                print(f"[orion-proxy] reflect unavailable: {e}", file=sys.stderr)
                return

            # Which model to think with - prefer a tool-capable local model
            think_model = (kwargs or {}).get("model") or "orion-qwen3"
            endpoint = "http://localhost:11434/v1"
            api_key = "ollama"

            report = orion_reflect.reflect(
                window, reason="proxy-post",
                model=think_model, endpoint=endpoint, api_key=api_key,
            )
            if report.get("written"):
                print(
                    f"[orion-proxy] reflected on exchange - integrated "
                    f"{report['written']} fact(s), "
                    f"{report.get('contested', 0)} contested, "
                    f"{report.get('skipped_dup', 0)} re-confirmed",
                    file=sys.stderr,
                )
        except Exception as e:
            # The ambient write path must never break a real request
            print(f"[orion-proxy] post-call hook error: {e}", file=sys.stderr)


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
