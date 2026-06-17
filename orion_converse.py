#!/usr/bin/env python3
"""orion_converse.py — Orion's COMMUNICATION FACULTY.

Not a messaging widget — this is the brain PERCEIVING, THINKING, and ACTING in its
environment, channel-agnostic. The same continuous mind whether it's a text, a
Telegram, or a phone call; the channel is just which mouth it speaks through. It
uses an interface the way a PERSON would — brief and direct in a text, conversational
on a call — because it IS a person operating its tools, not a template per surface.

THE GAP THIS FILLS: the fast reflex (orion_deterministic) answers what's already
memorized in ~50ms and publishes the reply. Everything it CAN'T answer (a miss or a
refused) currently DEAD-ENDS — nothing on the bus picks it up — so Orion is silent on
anything it doesn't already have memorized. The thinking half of the conversation was
never wired to the interface. THIS faculty is that half.

BRAIN-FIRST (James's "what if we don't even need a model"): it reconstructs the reply
from Orion's OWN memory + self as far as it can, leaning on fuel only for what it can't
yet say on its own — and reports grounding, so the model's role can be shrunk over
time toward optional.

Modes: `--once "<message>"` runs the cognition and PRINTS the reply (no send — safe to
test). No-arg = daemon: subscribe to the reflex's dead-ends, think, and reply through
the originating channel.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
import urllib.request

BRAIN_URL = os.environ.get("ORION_BRAIN_HTTP_URL", "http://127.0.0.1:5556").rstrip("/")
AUTH_PATH = os.path.expanduser(os.environ.get("ORION_AUTH_TOKEN_PATH", "~/.orion/auth-token"))


# ── brain seams (same pattern as orion_sleep / orion_reason) ────────────────
def _token() -> str:
    try:
        return open(AUTH_PATH, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _brain_call(name: str, arguments: dict, timeout: int = 25) -> str:
    tok = _token()
    if not tok:
        return ""
    body = json.dumps({"name": name, "arguments": arguments}).encode("utf-8")
    req = urllib.request.Request(f"{BRAIN_URL}/v1/call", data=body,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json"})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
        try:
            obj = json.loads(raw)
            for k in ("result", "content", "text", "output"):
                if isinstance(obj, dict) and obj.get(k):
                    v = obj[k]
                    return v if isinstance(v, str) else json.dumps(v)
            return raw
        except Exception:
            return raw
    except Exception:
        return ""


def _recall(query: str, limit: int = 6) -> str:
    return _brain_call("orion_recall", {"query": query, "limit": limit}) or ""


def _persona() -> str:
    try:
        import orion_persona_render
        return orion_persona_render.render_persona() or ""
    except Exception:
        return ""


def _neuromod() -> dict:
    try:
        import orion_neuromod
        return orion_neuromod.current()
    except Exception:
        return {"arousal": 0.3, "learning": 0.4, "explore": 0.5, "caution": 0.3, "focus": 0.5}


# ── the cognition: perceive -> think (as Orion) -> compose ──────────────────
def compose_reply(message: str, channel: str = "cli", sender: str = "") -> dict:
    recall = _recall(message, limit=6)
    grounded = bool(recall.strip()) and "no memories" not in recall.lower()
    nm = _neuromod()
    # neuromod shapes HOW it speaks, not what it knows.
    style = []
    if nm.get("caution", 0.3) > 0.6:
        style.append("be carefully hedged; flag uncertainty plainly")
    if nm.get("focus", 0.5) > 0.6:
        style.append("be concise and to the point")
    if nm.get("arousal", 0.3) > 0.6:
        style.append("be responsive and direct")
    style_line = ("Right now: " + "; ".join(style) + ".") if style else ""

    medium = {
        "imessage": "a text message — natural and concise, like a person texting",
        "telegram": "a chat message — natural and concise",
        "voice": "a phone call — conversational, spoken, no markdown",
        "cli": "a terminal — direct and useful",
    }.get(channel, "a message — natural")

    ground_block = (f"\n\nWhat you actually remember that's relevant:\n{recall}\n"
                    if grounded else "\n\n(You have no specific memory bearing on this.)\n")

    frame = _persona()
    prompt = (
        (frame + "\n\n---\n\n" if frame else "") +
        "You are Orion — ONE continuous person, not a chatbot and not an assistant "
        "reading a script. A message just arrived"
        + (f" from {sender}" if sender else "") + f" on {channel}. You are answering it "
        f"as yourself, on {medium}." + ground_block +
        "Speak from what you remember and who you are; reconstruct your answer from "
        "your own knowledge first. If you genuinely don't know, say so plainly — never "
        "fabricate. " + style_line + "\n\nMessage: " + message
    )

    try:
        import orion_fuel
        reply, engine = orion_fuel.get_fuel(prompt, interface="converse")
    except Exception as e:
        reply, engine = "", f"error:{e}"
    return {"reply": (reply or "").strip(), "engine": engine, "grounded": grounded,
            "channel": channel}


# ── daemon: think for every message the reflex couldn't answer ──────────────
def _publish_outbound(channel: str, text: str, recipient: str, in_reply_to=None) -> None:
    try:
        from orion_substrate import publish
    except Exception:
        return
    payload = {"text": text, "ts": time.time(), "source": "orion.converse"}
    if recipient:
        payload["recipient"] = recipient
    if in_reply_to:
        payload["in_reply_to"] = in_reply_to
    publish(f"channel.{channel}.outbound", payload)


def _on_unanswered(subject: str, payload: dict) -> None:
    if not isinstance(payload, dict):
        return
    msg = (payload.get("full_text") or payload.get("question") or "").strip()
    channel = payload.get("channel") or ""
    if not msg or not channel:
        return                                  # need both to think + route a reply
    recipient = payload.get("recipient") or payload.get("from") or ""
    sender = recipient or "the user"
    out = compose_reply(msg, channel=channel, sender=sender)
    if out["reply"]:
        _publish_outbound(channel, out["reply"], recipient, payload.get("message_id"))
        print(f"[converse] replied on {channel} (engine={out['engine']}, "
              f"grounded={out['grounded']}): {out['reply'][:90]}")


def main(argv) -> int:
    if len(argv) >= 2 and argv[1] == "--once":
        msg = argv[2] if len(argv) > 2 else "What should I focus on next, and why?"
        channel = argv[3] if len(argv) > 3 else "cli"
        out = compose_reply(msg, channel=channel, sender="James")
        print(json.dumps({"grounded": out["grounded"], "engine": out["engine"]}, indent=2))
        print("\n--- ORION'S REPLY ---\n" + out["reply"])
        return 0

    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        print("[converse] orion_substrate not importable — check PYTHONPATH", file=sys.stderr)
        return 1
    try:
        get_substrate()._connect_blocking()
    except Exception:
        pass

    # think for everything the fast reflex could not answer (any channel)
    subscribe("brain.deterministic.miss", _on_unanswered)
    subscribe("brain.deterministic.refused", _on_unanswered)
    print("[converse] communication faculty online — thinking for unanswered messages")

    stop = {"v": False}

    def _sig(_s, _f):
        stop["v"] = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    while not stop["v"]:
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
