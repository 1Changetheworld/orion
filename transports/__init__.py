"""Sensorium — multi-transport substrate adapters for non-IP carriers.

Per docs/architecture/sensorium-research.md (3,202 words, filed 2026-05-16).
Extension of Orion's receptor surface beyond IP. Each transport hangs off
orion_substrate and carries CRDT deltas using the carrier's native MTU.

This is v1 scaffolding — the abstract Transport + Frame + the first impl
(LoRa via Reticulum). BLE / radio / NFC / ultrasonic adapters land in
follow-ups; their shape is fixed by the ABC here.

Memo's sharpest reframe:

    > Sensorium is not a transport-encoding problem. It is a manifest-
    > sharing problem. What needs to flow across LoRa is not a delta of
    > a node; it is a delta of the manifest of which nodes exist, with
    > which hashes, on which hosts. Content syncs on the next IP
    > rendezvous.

Two-tier durability: LoRa is best-effort gossip; IP is the consistency
authority. Transports advertise manifest references; full content fetch
happens over whatever fatter pipe shows up next.

Membrane (orion_membrane.py) already gates transport.lora.* /
transport.ble.* / transport.radio.* as DEST_PUBLIC at publish time —
private-tagged nodes never reach a Transport.send(). Build on that
floor; don't re-implement privacy at this layer.
"""
from __future__ import annotations

from .base import Transport, Frame, FragmentBuffer  # noqa: F401

# Registry — populated by importing modules calling register_transport().
_registry: dict[str, Transport] = {}


def register_transport(name: str, transport: Transport) -> None:
    """Register a transport so plexus_deploy / orion_substrate can find
    it by name. Idempotent — re-registering replaces."""
    _registry[name] = transport


def get_transport(name: str) -> Transport | None:
    return _registry.get(name)


def list_transports() -> list[str]:
    return sorted(_registry.keys())


__all__ = [
    "Transport", "Frame", "FragmentBuffer",
    "register_transport", "get_transport", "list_transports",
]
