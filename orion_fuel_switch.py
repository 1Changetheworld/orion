"""orion_fuel_switch.py — recognize fuel-switch intent + persist preference.

Subscribes to `channel.*.inbound` on the Plexus substrate. When a message
matches a fuel-switch intent (e.g. "switch to codex", "use claude sonnet",
"go ollama for now"), writes `~/.orion/fuel_preference.json` with the
chosen fuel + an expiry. orion_fuel.py reads this preference at the top
of its routing logic — the next request uses the new fuel.

Also publishes `brain.fuel.switched` on the substrate so the claustrum
sees it (and the user gets a confirmation reply through their channel).

WHY THIS LIVES IN ITS OWN FILE
==============================

Fuel-switching is an INTENT, not a piece of recall. We don't want it
buried in the brain's natural-language path where the LLM might pattern-
match on a related phrase and re-route fuel mid-conversation. By owning
the intent recognition in a small substrate subscriber, we keep the
behavior deterministic, observable, and revertible.

INTENT RECOGNITION
==================

Pure pattern match — no LLM. Two reasons:
1. Determinism: the user says "switch to codex" and the system MUST
   route to codex. No "the model thinks they meant something else."
2. Cost: this runs on every inbound message. LLM-per-message-just-to-
   classify-intent is wasteful when a regex covers the obvious cases.

Patterns:
  /\b(switch|use|change|go) (to )?(claude|claude cli|claude sonnet|
  claude opus|codex|codex cli|gemini|gemini cli|ollama|local|tgpt)\b/i

ESCAPE HATCH
============

Set ORION_FUEL_PREF_LOCKED=1 in environment to refuse switches (e.g.
during a long task you don't want interrupted by an accidental phrase).

PREFERENCE FILE SCHEMA
======================

  ~/.orion/fuel_preference.json
  {
    "fuel": "claude_cli",            # one of: claude_cli, codex_cli,
                                     #   gemini_cli, ollama, tgpt, auto
    "model_hint": "sonnet" | "opus" | null,  # subordinate to fuel
    "set_at": 1778000000,
    "set_by": "channel.imessage.inbound",
    "expires_at": null,              # if set, fuel reverts to "auto" after
    "reason": "user said: 'switch to codex'"
  }

orion_fuel.py reads this file at the top of get_fuel(); if `fuel` is not
"auto", it routes there directly (overriding the priority cascade).
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger("orion.fuel_switch")

PREF_FILE = Path(os.path.expanduser("~/.orion/fuel_preference.json"))

# Map of recognized phrases → (fuel, optional_model_hint)
FUEL_KEYWORDS = {
    "claude": ("claude_cli", None),
    "claude cli": ("claude_cli", None),
    "claude code": ("claude_cli", None),
    "claude sonnet": ("claude_cli", "sonnet"),
    "claude opus": ("claude_cli", "opus"),
    "claude haiku": ("claude_cli", "haiku"),
    "codex": ("codex_cli", None),
    "codex cli": ("codex_cli", None),
    "gpt": ("codex_cli", None),
    "gemini": ("gemini_cli", None),
    "gemini cli": ("gemini_cli", None),
    "ollama": ("ollama", None),
    "local": ("ollama", None),
    "offline": ("ollama", None),
    "tgpt": ("tgpt", None),
    "auto": ("auto", None),
    "default": ("auto", None),
}

INTENT_RE = re.compile(
    r"\b(?:switch|use|change|go|set)\s+(?:to\s+|over\s+to\s+|using\s+)?"
    r"(claude(?:\s+(?:cli|code|sonnet|opus|haiku))?|codex(?:\s+cli)?|"
    r"gemini(?:\s+cli)?|ollama|local|offline|tgpt|auto|default|gpt)\b",
    re.IGNORECASE,
)


def _detect_intent(text: str) -> tuple[str, str | None] | None:
    """Returns (fuel, model_hint) if the message contains a fuel-switch
    intent, else None."""
    if not text:
        return None
    m = INTENT_RE.search(text)
    if not m:
        return None
    keyword = m.group(1).lower().strip()
    return FUEL_KEYWORDS.get(keyword)


def _persist(fuel: str, model_hint: str | None, set_by: str, reason: str) -> None:
    PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fuel": fuel,
        "model_hint": model_hint,
        "set_at": time.time(),
        "set_by": set_by,
        "expires_at": None,
        "reason": reason,
    }
    PREF_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("fuel preference set: %s (model_hint=%s) reason=%r",
                fuel, model_hint, reason)


def _on_inbound(subject: str, payload: dict) -> None:
    if os.environ.get("ORION_FUEL_PREF_LOCKED") == "1":
        return
    text = payload.get("text") or ""
    intent = _detect_intent(text)
    if not intent:
        return
    fuel, model_hint = intent
    _persist(fuel, model_hint, set_by=subject, reason="user said: " + repr(text[:120]))

    # Confirm to the channel that produced this event
    try:
        from orion_substrate import publish, channel_outbound_subject
        parts = subject.split(".")
        channel = parts[1] if len(parts) >= 3 else "unknown"
        confirmation = (
            f"Switched fuel to {fuel}"
            + (f" ({model_hint})" if model_hint else "")
            + ". Next reply uses it."
        )
        publish(channel_outbound_subject(channel), {
            "channel": channel,
            "recipient": payload.get("sender") or "",
            "text": confirmation,
            "ts": time.time(),
            "fuel_used": "fuel_switch_confirmation",
        })
        publish("brain.fuel.switched", {
            "fuel": fuel,
            "model_hint": model_hint,
            "ts": time.time(),
            "trigger_channel": channel,
        })
    except Exception as e:
        logger.warning("confirm publish failed: %s", e)


_stop = threading.Event()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError as e:
        logger.error("orion_substrate not importable: %s", e)
        return 1

    sub = get_substrate()
    if not sub._connect_blocking():
        logger.warning("substrate unreachable on start; deferring subscribe")

    subscribe("channel.*.inbound", _on_inbound)
    logger.info("fuel-switch listener alive — watching channel.*.inbound")

    def _sigterm(_sig, _frame):
        _stop.set()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    while not _stop.is_set():
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
