"""imessage_outbound.py — substrate-driven iMessage sender.

Closes the loop opened by orion_intent: subscribes to
channel.imessage.outbound, sends the text payload as an iMessage to
the founder's handle via AppleScript. Plexus service candidate.

Built 2026-05-15 to make the natural-language intent loop reach the
user's phone. Pairs with orion_intent.py (which dispatches outbound
events from recognized intents like 'text me X').

Spam-fix 2026-05-16: dedupe identical (text, recipient) within
DEDUPE_WINDOW_SEC. Two wills (COMMAND + Pi) both narrate the same
substrate event → without dedupe the phone gets each message twice.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import OrderedDict

logger = logging.getLogger("orion.imessage.outbound")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
DEFAULT_RECIPIENT = os.environ.get("ORION_IMESSAGE_RECIPIENT", "+12703003122")
DEDUPE_WINDOW_SEC = float(os.environ.get("ORION_IMESSAGE_DEDUPE_SEC", "120"))

# (text_hash, recipient) -> last_sent_ts. Bounded to keep memory small.
_recent_sends: "OrderedDict[tuple[str,str], float]" = OrderedDict()
_RECENT_MAX = 256


def _should_send(text: str, recipient: str) -> bool:
    now = time.time()
    # Evict old entries
    expired = [k for k, ts in _recent_sends.items() if now - ts > DEDUPE_WINDOW_SEC]
    for k in expired:
        _recent_sends.pop(k, None)
    key = (hashlib.sha1(text.encode("utf-8")).hexdigest()[:16], recipient)
    if key in _recent_sends:
        return False
    _recent_sends[key] = now
    while len(_recent_sends) > _RECENT_MAX:
        _recent_sends.popitem(last=False)
    return True


import re as _re

# Recipients that should NEVER reach AppleScript. These are placeholder
# strings that have leaked through the routing layer in the past
# (e.g. commit 37ab7e6's "primary_user" misroute). Sending these to
# Messages.app fails silently and the user never gets the message.
# Hard-reject at the boundary instead of failing in osascript.
_INVALID_RECIPIENT_LITERALS = {
    "primary_user", "user", "default", "default_user",
    "", "None", "null", "undefined",
}
# A valid recipient is either a phone number (E.164 or +-prefixed) or
# an email address (Apple ID iMessage). Anything else is a routing bug.
_PHONE_RE = _re.compile(r"^\+?[0-9][0-9\-\s\(\)\.]{6,}$")
_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_recipient(recipient: str) -> tuple[bool, str]:
    """Return (is_valid, reason). The boundary guard against placeholder
    leaks like 'primary_user'. Added 2026-05-25 after audit showed the
    leak survived even after commit 37ab7e6's reach-side fix."""
    if not recipient or not isinstance(recipient, str):
        return False, "empty/non-string recipient"
    r = recipient.strip()
    if r in _INVALID_RECIPIENT_LITERALS or r.lower() in _INVALID_RECIPIENT_LITERALS:
        return False, "placeholder literal: %r" % r
    if _PHONE_RE.match(r) or _EMAIL_RE.match(r):
        return True, "ok"
    return False, "not a phone number or email: %r" % r


# Osascript timeout — Messages.app on a loaded mac can take >15s to
# respond when starting up or processing prior sends. 30s removes the
# false-timeout noise we saw on 2026-05-21. With retry-on-timeout below,
# a transient slow Messages.app no longer drops messages silently.
_OSASCRIPT_TIMEOUT_SEC = 30
_OSASCRIPT_RETRIES = 1   # 1 retry after first timeout → 2 attempts total
_RETRY_BACKOFF_SEC = 3


def _send_via_applescript(recipient: str, text: str) -> bool:
    """Send through Messages via the resilient multi-strategy sender.

    Rewired 2026-06-04: delegates to channels/imessage_send.py, which
    cascades shortcuts-CLI → unqualified-buddy → participant → legacy
    forms. macOS 15 Sequoia removed the `service`/`account`/`buddy`
    nouns this used to rely on, so a single AppleScript form is no
    longer reliable. The recipient guard, 30s timeout, and retry now
    live in the shared module and apply to every strategy. Name kept for
    call-site compatibility with _on_outbound.
    """
    try:
        from channels.imessage_send import send_imessage
    except ImportError:
        from imessage_send import send_imessage  # run from channels/ dir
    return send_imessage(recipient, text)


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
    if not _should_send(text, recipient):
        logger.info("duplicate suppressed (within %.0fs): %s", DEDUPE_WINDOW_SEC, text[:60])
        await _publish_status(nc, recipient, text, True, error="deduped")
        return
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
