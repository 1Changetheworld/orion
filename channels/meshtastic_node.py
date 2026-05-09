"""channels/meshtastic_node.py — off-grid LoRa channel for Orion.

Listens on a Meshtastic radio (USB-attached host node) and bridges
inbound text messages into the Plexus substrate as
`channel.meshtastic.inbound`. Subscribes to `channel.meshtastic.outbound`
and sends replies back over the radio.

ARCHITECTURE
============

You have at least two Meshtastic v3 nodes:

  Pocket node (travels with you, BT-paired to your phone)
        │
        ▼  LoRa  (1-15 mile range per hop, US 915 MHz)
        │
  Host node (USB to FORGE / Pi / COMMAND)
        │
        ▼  USB serial
        │
  meshtastic_node.py daemon
        │
        ▼  publishes channel.meshtastic.inbound
        │
  Plexus substrate (NATS on COMMAND, Tailscale-reachable)
        │
        ▼
  Brain answers using whichever fuel is locally available
        │
        ▼  publishes channel.meshtastic.outbound
        │
  meshtastic_node.py subscribes, sends reply via radio
        │
        ▼
  LoRa → pocket node → BT → your phone

The off-grid story: even if home WiFi is dead AND you're outside cell
coverage, your pocket node can reach the host node by LoRa. The host
node's brain (FORGE Ollama, Pi Ollama, or USB-portable brain) answers
locally without internet. Reply travels back the same path. No cloud
dependency, no internet dependency. Just radio.

This pattern uses the `meshtastic-python` library
(https://github.com/meshtastic/python). Install with `pip install meshtastic`.

USAGE
=====

  # On the host machine with the USB-attached Meshtastic node:
  python channels/meshtastic_node.py --port /dev/cu.SLAB_USBtoUART

  # Or auto-detect:
  python channels/meshtastic_node.py

  # As a daemon (launchd / systemd / Task Scheduler):
  com.orion.meshtastic.plist on macOS, etc.

DESIGN DISCIPLINE
=================

This file follows the channel-adapter contract from
docs/architecture/channel-adapter.md exactly:
  1. Listen on the surface (Meshtastic serial)
  2. Publish channel.meshtastic.inbound on substrate
  3. Subscribe to channel.meshtastic.outbound and emit on the surface

No model code, no fuel code, no brain code. The brain handles answer
generation; this daemon just bridges the radio to the substrate.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger("orion.channels.meshtastic")


def _connect_substrate():
    """Find orion_substrate, connect to NATS. Returns (publish, subscribe)
    or (None, None) if substrate is unreachable."""
    # Make orion_substrate importable regardless of where this file lives
    here = Path(__file__).resolve().parent
    repo_root = here.parent
    sys.path.insert(0, str(repo_root))
    try:
        from orion_substrate import (
            publish, subscribe, get_substrate,
            channel_inbound_subject, channel_outbound_subject,
        )
    except ImportError as e:
        logger.error("orion_substrate not importable: %s", e)
        return None, None, None, None
    sub = get_substrate()
    if not sub._connect_blocking():
        logger.warning("substrate unreachable on start; will retry per-publish")
    return publish, subscribe, channel_inbound_subject, channel_outbound_subject


def _connect_radio(port: str | None):
    """Open the Meshtastic serial connection. meshtastic-python auto-detects
    the right serial port if you omit `port`."""
    try:
        import meshtastic
        import meshtastic.serial_interface
    except ImportError:
        logger.error(
            "meshtastic-python not installed. Run: pip install meshtastic"
        )
        return None

    try:
        if port:
            iface = meshtastic.serial_interface.SerialInterface(devPath=port)
        else:
            iface = meshtastic.serial_interface.SerialInterface()
        logger.info("Meshtastic serial connected: %s", iface)
        return iface
    except Exception as e:
        logger.error("Meshtastic connect failed: %s", e)
        return None


_iface = None
_publish = None
_inbound_subject = None
_outbound_subject = None
_stop = threading.Event()


def _on_radio_message(packet, interface):
    """Called by meshtastic-python on every incoming text message.

    packet is a dict; interesting keys: fromId, toId, decoded.text.
    """
    if not _publish:
        return
    try:
        decoded = packet.get("decoded", {}) or {}
        text = decoded.get("text") or decoded.get("payload") or ""
        if not text:
            return
        sender = packet.get("fromId") or packet.get("from") or "unknown"
        ts = packet.get("rxTime") or time.time()
        _publish(_inbound_subject("meshtastic"), {
            "channel": "meshtastic",
            "sender": str(sender),
            "text": str(text),
            "ts": float(ts),
            "rssi": packet.get("rxRssi"),
            "snr": packet.get("rxSnr"),
            "hop_count": packet.get("hopLimit"),
        })
        logger.info("inbound from %s: %s", sender, str(text)[:120])
    except Exception as e:
        logger.warning("on_radio_message error: %s", e)


def _on_substrate_outbound(subject: str, payload: dict) -> None:
    """Called when the brain publishes a reply for the meshtastic channel.

    payload: {channel, recipient, text, ts}. We send via the radio.
    """
    if not _iface:
        logger.warning("radio not connected; dropping outbound: %s", payload.get("text", "")[:80])
        return
    try:
        text = payload.get("text") or ""
        recipient = payload.get("recipient")  # node id or '^all' for broadcast
        if not text:
            return
        if recipient and recipient != "^all":
            _iface.sendText(text, destinationId=recipient)
        else:
            _iface.sendText(text)
        logger.info("outbound to %s: %s", recipient or "broadcast", text[:120])
    except Exception as e:
        logger.warning("send via radio failed: %s", e)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="serial device path (e.g. /dev/cu.SLAB_USBtoUART)")
    args = ap.parse_args()

    global _publish, _inbound_subject, _outbound_subject, _iface
    _publish, subscribe_fn, _inbound_subject, _outbound_subject = _connect_substrate()
    if not _publish:
        return 1

    _iface = _connect_radio(args.port)
    if not _iface:
        logger.error("radio unavailable — exiting")
        return 2

    # Subscribe to outbound on the substrate so brain replies get sent
    if subscribe_fn:
        subscribe_fn(_outbound_subject("meshtastic"), _on_substrate_outbound)

    # Subscribe to incoming radio messages
    try:
        from pubsub import pub
        pub.subscribe(_on_radio_message, "meshtastic.receive.text")
    except ImportError:
        logger.error("pubsub library missing — pip install pypubsub")
        return 3

    logger.info("meshtastic channel adapter alive")

    def _sigterm(_sig, _frame):
        _stop.set()
        try:
            if _iface:
                _iface.close()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    while not _stop.is_set():
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
