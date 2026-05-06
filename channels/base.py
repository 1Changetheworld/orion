"""Channel framework — the contract every comm endpoint implements.

A Channel is anything that can:
    1. Yield incoming messages (subclass Channel.receive)
    2. Send a reply back (subclass Channel.send)

The framework provides:
    - BrainClient: thin HTTP client for orion_brain_service.py /v1/call
    - run_bridge(channel): forever-loop that wires a channel to the brain

Usage (~30 lines for a new channel):

    from channels import Channel, Message, run_bridge

    class MyChannel(Channel):
        name = "my-thing"

        def receive(self):
            while True:
                # ... fetch / poll / listen
                yield Message(text="hello", sender="alice")

        def send(self, reply_text, reply_to):
            # ... deliver reply_text via your channel
            print(f"-> {reply_to.sender}: {reply_text}")

    run_bridge(MyChannel())
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional


# ─────────────────────────────────────────────────────────────────
# Message — what flows through any channel
# ─────────────────────────────────────────────────────────────────


@dataclass
class Message:
    """An incoming message from any channel.

    Channels populate as much as they can; missing fields stay empty.
    The brain doesn't care about transport details, only `text` and
    optionally `sender` for memory attribution.
    """
    text: str
    sender: str = ""
    channel: str = ""
    metadata: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# BrainClient — talk to orion_brain_service.py
# ─────────────────────────────────────────────────────────────────


class BrainClient:
    """Thin client for the local Orion brain HTTP service.

    Reads the bearer token from ~/.orion/auth-token by default. Hits
    /v1/call with {name: tool, arguments: {...}} and returns the
    flattened text content.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5556",
        token: Optional[str] = None,
        token_path: Optional[Path] = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if token:
            self.token = token
        else:
            tp = token_path or Path(os.path.expanduser("~/.orion/auth-token"))
            try:
                self.token = tp.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                raise RuntimeError(
                    f"Orion auth token not found at {tp}. Start the brain "
                    f"service once (python orion_brain_service.py) to generate it."
                )

    def call(self, tool: str, arguments: dict | None = None) -> dict:
        """Invoke a brain tool. Returns the parsed JSON response."""
        body = json.dumps({
            "name": tool,
            "arguments": arguments or {},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/call",
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def recall(self, query: str, limit: int = 5) -> str:
        """Convenience: orion_recall and return joined text content."""
        res = self.call("orion_recall", {"query": query, "limit": limit})
        return _flatten_content(res.get("content", []))

    def memorize(self, content: str, tags: list[str] | None = None) -> str:
        """Convenience: store a fact in the brain."""
        args = {"content": content}
        if tags:
            args["tags"] = tags
        res = self.call("orion_memorize", args)
        return _flatten_content(res.get("content", []))

    def health(self) -> dict:
        """GET /health — no auth required."""
        with urllib.request.urlopen(f"{self.base_url}/health", timeout=5) as r:
            return json.loads(r.read())


def _flatten_content(content_list: list) -> str:
    """Brain returns [{"type": "text", "text": "..."}, ...] — join into a string."""
    if not isinstance(content_list, list):
        return str(content_list)
    parts = []
    for item in content_list:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────
# Channel — base class
# ─────────────────────────────────────────────────────────────────


class Channel:
    """Base class for any communication channel that wants Orion's brain.

    Subclass and implement receive() + send(). The framework handles the
    brain call between them via run_bridge().
    """

    name: str = "unknown"

    def receive(self) -> Iterator[Message]:
        """Yield incoming messages forever (or until the channel closes)."""
        raise NotImplementedError(f"{self.__class__.__name__}.receive must be implemented")

    def send(self, reply_text: str, reply_to: Message) -> None:
        """Deliver `reply_text` back through this channel as a reply."""
        raise NotImplementedError(f"{self.__class__.__name__}.send must be implemented")


# ─────────────────────────────────────────────────────────────────
# Bridge — connect a channel to the brain
# ─────────────────────────────────────────────────────────────────


def run_bridge(
    channel: Channel,
    brain: BrainClient | None = None,
    on_error: str = "log",
) -> None:
    """Forever loop: receive from channel, call brain, send reply.

    on_error: "log" (default) prints and continues; "raise" propagates.
    """
    if brain is None:
        brain = BrainClient()

    print(f"[{channel.name}] bridge started, brain at {brain.base_url}", flush=True)
    try:
        health = brain.health()
        print(f"[{channel.name}] brain health: {health.get('status')} "
              f"({health.get('tool_count')} tools)", flush=True)
    except Exception as e:
        print(f"[{channel.name}] WARN brain not reachable: {e}", flush=True)

    for msg in channel.receive():
        try:
            # The brain's orion_recall is the default verb for "answer this
            # using my memory." Channels that want different behaviour can
            # bypass this loop and call brain.call() directly.
            reply = brain.recall(msg.text, limit=5)
            if not reply.strip():
                reply = "I don't have a stored answer for that yet."
            channel.send(reply, reply_to=msg)
        except Exception as e:
            err = f"{e.__class__.__name__}: {e}"
            print(f"[{channel.name}] error handling message: {err}", flush=True)
            if on_error == "raise":
                raise
            try:
                channel.send(f"(error reaching the brain: {err})", reply_to=msg)
            except Exception:
                pass
