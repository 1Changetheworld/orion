"""transports/lora.py — LoRa carrier via Reticulum (RNS).

Per sensorium-research.md §1 (LoRa landscape) + §6 (Reticulum as
adopted middleware) + §7 (recommended architecture). Adopts Reticulum
for routing / addressing / encryption / multi-hop and keeps Orion's
own CRDT encoding on top — the third option of the three the memo
named, with the reasoning that RNS solves ~80% of the hard problems
already and reinventing them is poor use of build time.

V1 SCOPE
========

This file is *scaffolding* — it exposes the LoraTransport class shape
matching the ABC in transports/base.py, attempts a clean Reticulum
import path, and degrades to a clearly-marked ImportError when RNS
is not installed (FORGE without Heltec hardware will hit this; Pi-
build with hardware can install reticulum and validate live).

Real hardware loop validation is task #10 on the Pi-build side. This
patch lands the abstraction so the Pi session can fill in concrete
RNS wiring without coordination overhead.

Subject convention (matches the prefix Membrane already gates as
DEST_PUBLIC at orion_substrate.publish):

    transport.lora.outbound.<peer_hint>   frames Orion wants to ship
    transport.lora.inbound                frames received from the mesh
    transport.lora.status                  carrier liveness, RSSI

Duty cycle accounting (memo §7 risk 1) is left to a follow-up — the
shape of the accounting module is a per-region tally + a publish
budget the transport consults before send(). v1 logs send attempts
but doesn't throttle; Pi-build's first deploy will surface whether
EU868 / US915 limits bite in practice.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from .base import Frame, Transport

logger = logging.getLogger("orion.transports.lora")

# Reticulum RNS — optional dependency. Memo §6 picks this as the
# routing+encryption substrate; we adopt rather than reimplement.
try:
    import RNS  # type: ignore
    _RNS_AVAILABLE = True
except ImportError:
    RNS = None  # type: ignore
    _RNS_AVAILABLE = False


class LoraTransport(Transport):
    """LoRa via Reticulum. Concrete RNS wiring is filled in on the
    host that has actual Heltec v3 hardware (Pi-build); this class
    on FORGE imports cleanly but raises on start() if RNS isn't
    installed, so misconfiguration is loud-not-silent."""

    name = "lora"
    mtu_bytes = 240  # SF7-fast — per sensorium-research.md §1 table

    def __init__(self, config_dir: Optional[str] = None,
                 interface_name: str = "orion-lora") -> None:
        self.config_dir = config_dir
        self.interface_name = interface_name
        self._reticulum = None
        self._destination = None
        self._running = False

    async def start(self) -> None:
        """Open the Reticulum stack and bind to the LoRa interface.

        Pi-build hardware loop fills in the concrete RNS calls:
            self._reticulum = RNS.Reticulum(self.config_dir)
            identity = RNS.Identity()
            self._destination = RNS.Destination(
                identity, RNS.Destination.IN, RNS.Destination.SINGLE,
                "orion", "transport.lora")
            self._destination.set_packet_callback(self._on_packet)

        Until that lands, raise ImportError loudly on hosts without RNS
        instead of silently no-op'ing — silent failures are unacceptable
        per founder rule and memo's audit-trail principle."""
        if not _RNS_AVAILABLE:
            raise ImportError(
                "Reticulum (RNS) is not installed on this host. "
                "Install with: pip install rns. "
                "Hardware loop validation lives on Pi-build "
                "(3 Heltec v3 nodes staged). "
                "See docs/architecture/sensorium-research.md §7."
            )
        # Concrete RNS init happens here once the Pi-build session
        # validates against real hardware. v1 stops at the loud-import
        # boundary so FORGE without LoRa hardware doesn't pretend.
        self._running = True
        logger.info("lora transport scaffolding loaded (RNS available); "
                    "concrete wiring pending Pi-build hardware loop")

    async def stop(self) -> None:
        self._running = False
        # Pi-build fills in: self._reticulum.exit_handler() etc.

    async def send(self, frame: Frame,
                   dest_hint: Optional[str] = None) -> None:
        if not self._running:
            logger.warning("send dropped — lora transport not started")
            return
        # Membrane belt-and-suspenders at the transport boundary
        # (substrate.publish is the primary gate; this is the seatbelt).
        if not self.allow_egress(node_id=None, subject=frame.subject):
            logger.info("membrane refused lora send subject=%s", frame.subject)
            return
        # Concrete RNS packet send fills in here. Frame.body is the
        # CBOR-encoded chunk already; just wrap in RNS.Packet and send.
        logger.debug("lora send subject=%s idx=%d/%d body=%dB",
                     frame.subject, frame.idx, frame.total, len(frame.body))

    async def recv(self) -> AsyncIterator[Frame]:
        """Yield frames as they arrive from the LoRa mesh. Pi-build
        wires the RNS packet callback to feed an asyncio.Queue this
        method drains."""
        if False:
            # Placeholder so this is a valid async generator. Yields
            # only happen once RNS wiring is in place on Pi-build.
            yield  # type: ignore[unreachable]
        return


def has_reticulum() -> bool:
    """Diagnostics — true when RNS is importable on this host. Used
    by plexus_deploy.sh preflight and by orion_sensorium status."""
    return _RNS_AVAILABLE
