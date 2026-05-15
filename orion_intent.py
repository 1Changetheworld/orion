"""orion_intent.py — natural-language intent listener.

Founder direction 2026-05-15: stop wiring channel-specific MCP tools. The
real adaptability is the model understanding what you mean and Orion's
own intelligence routing the action. Any AI fueling Orion (Claude /
Codex / Gemini / Letta / Ollama / future) just memorizes a normal
sentence — this service watches every fresh memory, recognizes
intent, and dispatches via reach.

How it fits into the Plexus
---------------------------
Subscribes:  brain.memory.stored                (every new memorize)
             channel.*.inbound                  (raw user messages on any channel)
Publishes:   brain.intent.detected              (structured intent)
             channel.<chosen>.outbound          (the action — text / call / etc)

Patterns recognized (deliberately small + extensible):
  - text me <X>           -> iMessage / fallback chain
  - call me [in Nm]       -> Telnyx voice (Nm = N minutes from now)
  - remind me <X> [at T]  -> deferred reach via chronos+will at T
  - telegram me <X>       -> Telegram bot
  - email me <X>          -> gmail / email channel
  - ping <X> on <channel> -> explicit-channel reach
  - send <X> to everyone  -> fan-out to every active surface

If no pattern matches, publishes brain.intent.unrecognized so future
training / refinement has a record. Never auto-acts without a pattern
match — the model's own choice to call orion_memorize is the implicit
consent; we don't escalate beyond reach-without-permission.

NEVER auto-fires destructive actions; reach handles channel-specific
delivery_status feedback and the v1.7 fallback chain takes it from
there.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path

logger = logging.getLogger("orion.intent")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
INTENT_LOG = Path(os.path.expanduser(
    os.environ.get("ORION_INTENT_LOG", "~/.orion/intent/detected.jsonl")
))
INTENT_LOG.parent.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────
# Intent patterns — keep simple + readable. Add to this list
# rather than building an LLM classifier; the fuel model already
# did the language understanding by choosing to memorize.
# ─────────────────────────────────────────────────────────

PATTERNS = [
    # (regex, action, channel hint, payload group index, extra extractor)
    (re.compile(r"(?:text|imessage)\s+me\s+(.{3,400})", re.I),
     "send_message", "imessage", 1, None),
    (re.compile(r"telegram\s+me\s+(.{3,400})", re.I),
     "send_message", "telegram", 1, None),
    (re.compile(r"email\s+me\s+(.{3,400})", re.I),
     "send_message", "email", 1, None),
    (re.compile(r"(?:call|phone|ring)\s+me(?:\s+in\s+(\d+)\s*m(?:in)?)?", re.I),
     "place_call", "voice", None, "delay_minutes"),
    (re.compile(r"remind\s+me\s+(?:to\s+)?(.{3,300?})(?:\s+(?:at|in)\s+(.+))?", re.I),
     "schedule_reminder", "auto", 1, "when"),
    (re.compile(r"ping\s+(.{3,300})\s+on\s+(\w+)", re.I),
     "send_message", None, 1, "channel_explicit"),
    (re.compile(r"(?:send|broadcast|tell)\s+(.{3,300})\s+to\s+everyone", re.I),
     "fan_out", "all", 1, None),
]


def detect_intent(text: str) -> dict | None:
    """Pattern-match a memorized line for actionable intent.

    Returns a structured intent dict or None.
    """
    if not text or len(text) > 2000:
        return None
    text = text.strip()
    for rx, action, channel_hint, payload_idx, extra_key in PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        intent = {"action": action, "ts": time.time(), "raw": text[:200]}
        if channel_hint:
            intent["channel"] = channel_hint
        if payload_idx and m.lastindex and payload_idx <= m.lastindex:
            intent["payload"] = m.group(payload_idx).strip()
        if extra_key == "delay_minutes" and m.group(1):
            intent["delay_seconds"] = int(m.group(1)) * 60
        if extra_key == "when" and m.lastindex >= 2 and m.group(2):
            intent["when"] = m.group(2).strip()
        if extra_key == "channel_explicit" and m.lastindex >= 2:
            intent["channel"] = m.group(2).strip().lower()
        return intent
    return None


# ─────────────────────────────────────────────────────────
# NATS plumbing
# ─────────────────────────────────────────────────────────

async def _publish(nc, subject: str, payload: dict):
    await nc.publish(subject, json.dumps(payload).encode())


def _log_intent(intent: dict, dispatched: bool):
    try:
        with open(INTENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({**intent, "dispatched": dispatched}) + "\n")
    except Exception as e:
        logger.warning("intent-log write failed: %s", e)


async def _on_memory_stored(msg, nc):
    try:
        payload = json.loads(msg.data.decode())
    except Exception:
        return
    content = payload.get("content") or payload.get("body") or ""
    intent = detect_intent(content)
    if not intent:
        return
    intent["source"] = "memory.stored"
    intent["node_id"] = payload.get("node_id")
    await _publish(nc, "brain.intent.detected", intent)
    await _dispatch(nc, intent)
    _log_intent(intent, True)


async def _on_channel_inbound(msg, nc):
    try:
        payload = json.loads(msg.data.decode())
    except Exception:
        return
    text = payload.get("text") or payload.get("body") or ""
    src_channel = msg.subject.split(".")[1] if "." in msg.subject else "unknown"
    intent = detect_intent(text)
    if not intent:
        return
    intent["source"] = f"channel.{src_channel}.inbound"
    await _publish(nc, "brain.intent.detected", intent)
    await _dispatch(nc, intent)
    _log_intent(intent, True)


async def _dispatch(nc, intent: dict):
    """Convert a recognized intent into a concrete reach action."""
    action = intent.get("action")
    if action == "send_message":
        chan = intent.get("channel") or "auto"
        await _publish(nc, f"channel.{chan}.outbound", {
            "text": intent.get("payload", ""),
            "ts": intent["ts"],
            "via": "orion_intent",
        })
    elif action == "place_call":
        delay = intent.get("delay_seconds", 0)
        if delay:
            # Schedule via chronos; for now publish with delay hint
            await _publish(nc, "brain.intent.scheduled", {
                **intent, "fire_at": intent["ts"] + delay,
            })
        else:
            await _publish(nc, "channel.voice.outbound", {
                "action": "place_call", "ts": intent["ts"],
                "via": "orion_intent",
            })
    elif action == "schedule_reminder":
        # Hand off to will + chronos; they handle the deferred fire
        await _publish(nc, "brain.intent.scheduled", intent)
    elif action == "fan_out":
        # Publish to a wildcard subject the channel-probe service can
        # multiplex; or pre-resolve here. For v0, publish once per
        # known channel id from channel-probe state if present.
        for chan in ("imessage", "telegram", "voice", "email", "webhook"):
            await _publish(nc, f"channel.{chan}.outbound", {
                "text": intent.get("payload", ""),
                "ts": intent["ts"],
                "via": "orion_intent.fanout",
            })


# ─────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────

async def main_async() -> int:
    try:
        import nats
    except ImportError:
        print("[orion-intent] nats-py not installed; pip install nats-py",
              file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("connecting to %s", NATS_URL)

    async def _err_cb(e): logger.debug("nats err: %s", e)
    async def _dis_cb(): logger.debug("nats disconnected")
    async def _rec_cb(): logger.debug("nats reconnected")

    nc = await nats.connect(NATS_URL,
                            error_cb=_err_cb,
                            disconnected_cb=_dis_cb,
                            reconnected_cb=_rec_cb)

    async def _mem_cb(msg):
        await _on_memory_stored(msg, nc)
    async def _chan_cb(msg):
        await _on_channel_inbound(msg, nc)

    await nc.subscribe("brain.memory.stored", cb=_mem_cb)
    await nc.subscribe("channel.*.inbound", cb=_chan_cb)
    logger.info("orion-intent alive — watching memory.stored + channel.*.inbound")

    stop = asyncio.Event()

    def _stop_handler(*_):
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, _stop_handler)
        loop.add_signal_handler(signal.SIGINT, _stop_handler)
    except NotImplementedError:
        # Windows
        pass

    await stop.wait()
    await nc.close()
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
