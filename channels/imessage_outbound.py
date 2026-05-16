"""imessage_outbound.py — substrate-driven iMessage sender.

Closes the loop opened by orion_intent: subscribes to
channel.imessage.outbound, sends the text payload as an iMessage to
the founder's handle via AppleScript. Plexus service candidate.

Built 2026-05-15 to make the natural-language intent loop reach the
user's phone. Pairs with orion_intent.py (which dispatches outbound
events from recognized intents like 'text me X').
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys

logger = logging.getLogger("orion.imessage.outbound")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
# Founder's iMessage handles. Default to first; can be overridden per
# event by including 'recipient' in the payload.
DEFAULT_RECIPIENT = os.environ.get("ORION_IMESSAGE_RECIPIENT", "+12703003122")


def _send_via_applescript(recipient: str, text: str) -> bool:
    """Run osascript to send through Messages.app. Returns success."""
    # Escape double-quotes and backslashes for AppleScript string literal
    clean = text.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        'tell application "Messages"\n'
        '    set targetService to 1st service whose service type = iMessage\n'
        f'    set targetBuddy to buddy "{recipient}" of targetService\n'
        f'    send "{clean}" to targetBuddy\n'
        'end tell'
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            logger.info("sent to %s: %s", recipient, text[:80])
            return True
        logger.warning("osascript rc=%s stderr=%s", r.returncode, r.stderr[:200])
        return False
    except Exception as e:
        logger.warning("osascript failed: %s", e)
        return False


async def _publish_status(nc, recipient: str, text: str, ok: bool, error: str = ""):
    """Tell the substrate whether delivery succeeded — feeds v1.7 fallback chain."""
    await nc.publish(
        "channel.imessage.delivery_status",
        json.dumps({
            "ok": ok,
            "recipient": recipient,
            "text_preview": text[:80],
            "error": error,
        }).encode()
    )


async def _on_outbound(msg, nc):
    try:
        payload = json.loads(msg.data.decode())
    except Exception as e:
        logger.warning("bad outbound payload: %s", e)
        return
    # Canary dry-run: do not actually send; just ACK so the canary
    # confirms this subscriber is alive and reachable.
    if payload.get("dry_run"):
        ack = {"ok": True, "probe_id": payload.get("probe_id"),
               "kind": "imessage.outbound", "ts": __import__("time").time()}
        await nc.publish("channel.imessage.canary_ack",
                         json.dumps(ack).encode())
        return
    text = payload.get("text") or ""
    if not text:
        logger.debug("empty text, skipping")
        return
    recipient = payload.get("recipient") or DEFAULT_RECIPIENT
    ok = _send_via_applescript(recipient, text)
    await _publish_status(nc, recipient, text, ok,
                          error="" if ok else "osascript-failed")


async def main_async() -> int:
    try:
        import nats
    except ImportError:
        print("nats-py not installed", file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("connecting to %s; default recipient %s",
                NATS_URL, DEFAULT_RECIPIENT)

    async def _err_cb(e): logger.debug("nats err: %s", e)
    async def _dis_cb(): logger.debug("nats disconnected")
    async def _rec_cb(): logger.debug("nats reconnected")

    nc = await nats.connect(NATS_URL, error_cb=_err_cb,
                            disconnected_cb=_dis_cb, reconnected_cb=_rec_cb)

    async def _cb(msg): await _on_outbound(msg, nc)
    await nc.subscribe("channel.imessage.outbound", cb=_cb)
    logger.info("imessage outbound subscriber alive")

    stop = asyncio.Event()
    try:
        import signal
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, stop.set)
        loop.add_signal_handler(signal.SIGINT, stop.set)
    except NotImplementedError:
        pass
    await stop.wait()
    await nc.close()
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
