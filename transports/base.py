"""transports/base.py — Transport ABC and Frame primitives.

The contract every Sensorium transport (LoRa, BLE, radio, NFC,
ultrasonic) implements. Substrate gossip + orion_membrane stay
unchanged; only the carrier under the wire varies.

Per sensorium-research.md §7 architecture. Keep the surface small —
v1's three jobs are:

    1. send(frame, dest_hint=None)  fire-and-forget per frame
    2. recv() async generator       yields raw inbound frames
    3. allow_egress(node_id, name)  thin pre-check (Membrane in code)

Reassembly, retry, duty-cycle accounting all happen inside concrete
implementations — different carriers have different rules and pushing
them into the ABC bloats the contract without making it more correct.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass(frozen=True)
class Frame:
    """A single carrier-MTU-sized chunk.

    A node delta typically exceeds any one frame; reassembly uses
    (content_hash, idx, total) per memo §3 (bitswap-shaped wantlist).
    Signature is truncated to 16 bytes when the carrier budget is
    tight — memo §2 makes the case that 2^128 collision resistance is
    cosmically infeasible to forge while saving 48 bytes per frame.
    """
    subject: str          # substrate subject the frame belongs to
    content_hash: bytes   # 8-byte BLAKE2s of the full payload
    idx: int              # chunk index, 0-based
    total: int            # total chunks for this payload
    body: bytes           # carrier-encoded bytes (CBOR delta or chunk)
    hlc: Optional[tuple] = None
    sig: bytes = b""      # truncated Ed25519, 16 bytes typical
    sender_host: str = ""

    def is_singleton(self) -> bool:
        return self.total == 1


class FragmentBuffer:
    """In-memory reassembly buffer. Per memo §3: chunks arrive
    out-of-order; partials must NOT propagate as authoritative.
    Caller polls `complete()` to drain whole payloads.

    Memory-bounded — TTL evicts incomplete fragments older than 5 min
    so a permanently lost chunk doesn't pin the buffer. The lost
    payload is reconciled later via IP rendezvous (two-tier durability
    is the whole point — LoRa is best-effort gossip).
    """
    def __init__(self, ttl_sec: float = 300.0):
        self._chunks: dict[bytes, dict[int, Frame]] = defaultdict(dict)
        self._first_seen: dict[bytes, float] = {}
        self._ttl_sec = ttl_sec

    def add(self, frame: Frame) -> None:
        h = frame.content_hash
        if h not in self._first_seen:
            self._first_seen[h] = time.time()
        self._chunks[h][frame.idx] = frame

    def complete(self) -> list[tuple[bytes, list[Frame]]]:
        """Drain and return any fully assembled payloads. Caller is
        responsible for verifying content_hash against the joined body
        before merging into the brain."""
        done = []
        now = time.time()
        for h in list(self._chunks.keys()):
            buf = self._chunks[h]
            any_frame = next(iter(buf.values()))
            if len(buf) == any_frame.total:
                # All chunks present — drain.
                ordered = [buf[i] for i in range(any_frame.total)]
                done.append((h, ordered))
                del self._chunks[h]
                self._first_seen.pop(h, None)
            elif now - self._first_seen.get(h, now) > self._ttl_sec:
                # Stale partial — drop. IP rendezvous handles it later.
                del self._chunks[h]
                self._first_seen.pop(h, None)
        return done


class Transport(ABC):
    """Abstract carrier. Concrete implementations: transports/lora.py,
    transports/ble.py, transports/radio.py.

    Lifecycle:
        t = LoraTransport()
        await t.start()           # opens the carrier, joins the mesh
        await t.send(frame)       # fire-and-forget — never blocks
        async for f in t.recv():  # yields inbound frames
            handle(f)
        await t.stop()
    """
    name: str = "base"
    mtu_bytes: int = 240  # LoRa SF7-fast default; override per carrier

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, frame: Frame, dest_hint: Optional[str] = None) -> None: ...

    @abstractmethod
    def recv(self) -> AsyncIterator[Frame]: ...

    def allow_egress(self, node_id, subject: str) -> bool:
        """Thin Membrane pre-check at the transport boundary. The
        substrate publish hook is the authoritative gate (orion_substrate.
        publish → orion_membrane.egress_decision); this is the seatbelt
        in case a future caller bypasses publish() and calls a transport
        directly. Fails open if Membrane unavailable — orion_substrate.
        publish is the primary gate, not us.
        """
        try:
            from orion_membrane import egress_decision, DEST_PUBLIC
            payload = {"node_id": node_id}
            decision = egress_decision(subject, payload,
                                       dest_class=DEST_PUBLIC)
            return decision == "allow"
        except Exception:
            return True
