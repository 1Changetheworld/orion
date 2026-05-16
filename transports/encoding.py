"""transports/encoding.py — CBOR delta encoding for the <240B LoRa budget.

Per sensorium-research.md §2 (the byte budget walk). The shape:

    raw graph delta (JSON-ish, ~180-260B per manifest entry)
        ↓ encode_delta()
    list[Frame] — each frame <= MTU after carrier framing overhead

    incoming list[Frame] (possibly reordered + lossy)
        ↓ FragmentBuffer.add(), .complete()
        ↓ decode_delta()
    reassembled dict ready to merge into orion_gossip._manifest

Two tiers:

    Tier A — fits in one frame (under 170-180 useful bytes after
             frame header + truncated sig). Most manifest references
             land here. Single-frame fast path.

    Tier B — multi-frame, chunked with content_hash + idx + total.
             Receiver reassembles via FragmentBuffer; partials never
             merge until content_hash verifies. Lost chunks resync
             over IP rendezvous (two-tier durability — memo §3).

CBOR over MessagePack because Reticulum speaks CBOR natively (and
memo §2.3 step 2 picks it explicitly). Falls back to compact JSON
when cbor2 is not installed so this module imports cleanly anywhere.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Iterable

from .base import Frame

logger = logging.getLogger("orion.transports.encoding")

# cbor2 is the canonical encoder per memo §2.3 step 2. Optional dep —
# fall back to compact JSON so the module imports cleanly on hosts
# without cbor2 (Pi-build can install it; FORGE may not have it yet).
try:
    import cbor2  # type: ignore
    _CBOR_AVAILABLE = True
except ImportError:
    cbor2 = None  # type: ignore
    _CBOR_AVAILABLE = False


def _encode(payload: dict) -> bytes:
    if _CBOR_AVAILABLE:
        return cbor2.dumps(payload)
    # Compact JSON is ~30-40% larger than CBOR but still small enough
    # for single-frame manifest references during dev. The byte budget
    # accounting in sensorium-research.md assumed CBOR; bench against
    # real frames before flipping to fail-loud-on-missing.
    return json.dumps(payload, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")


def _decode(body: bytes) -> dict:
    if _CBOR_AVAILABLE:
        try:
            return cbor2.loads(body)
        except Exception:
            pass
    return json.loads(body.decode("utf-8"))


def _content_hash(body: bytes) -> bytes:
    """8-byte BLAKE2s — fits the <80B manifest-reference budget
    in memo §2 concrete budget."""
    return hashlib.blake2s(body, digest_size=8).digest()


def encode_delta(subject: str, payload: dict, mtu_bytes: int = 240,
                 sender_host: str = "", hlc: tuple | None = None,
                 sig: bytes = b"") -> list[Frame]:
    """Encode a single delta into one-or-more Frames.

    Caller passes the *whole* logical payload (a manifest entry, a
    node body, a wantlist); this function decides single-frame vs
    multi-frame and returns the chunk list. Each frame body has been
    CBOR-encoded so the carrier just has to wrap framing around it.

    Frame budget accounting (memo §2 concrete budget at SF7 LoRa):
        carrier framing  12B
        content_hash      8B
        idx + total       4B
        hlc packed        8B
        truncated sig    16B
        ----              48B overhead → useful payload ~190B per frame
    """
    raw = _encode(payload)
    ch = _content_hash(raw)

    # Reserve overhead for the FRAMING the carrier adds; the body
    # itself doesn't include that. mtu_bytes is the carrier MTU
    # (LoRa SF7-fast = 240); we slice raw into chunks that, after
    # encoding overhead and signature, fit.
    overhead = 48  # accounting matches sensorium-research.md §2
    chunk_size = max(32, mtu_bytes - overhead)

    if len(raw) <= chunk_size:
        return [Frame(
            subject=subject,
            content_hash=ch,
            idx=0,
            total=1,
            body=raw,
            hlc=hlc,
            sig=sig,
            sender_host=sender_host,
        )]

    chunks = [raw[i:i + chunk_size] for i in range(0, len(raw), chunk_size)]
    total = len(chunks)
    return [
        Frame(
            subject=subject,
            content_hash=ch,
            idx=i,
            total=total,
            body=chunk,
            hlc=hlc,
            sig=sig if i == 0 else b"",  # sign first frame only — memo §2.6 (b)
            sender_host=sender_host,
        )
        for i, chunk in enumerate(chunks)
    ]


def decode_delta(frames: list[Frame]) -> dict:
    """Reassemble a list of frames belonging to ONE payload into the
    original dict. Caller must have already verified completeness
    (FragmentBuffer.complete()) and content_hash. Raises ValueError
    on hash mismatch."""
    if not frames:
        raise ValueError("decode_delta got empty frame list")
    frames_sorted = sorted(frames, key=lambda f: f.idx)
    body = b"".join(f.body for f in frames_sorted)
    expected = frames_sorted[0].content_hash
    actual = _content_hash(body)
    if expected != actual:
        raise ValueError(
            f"content_hash mismatch: expected {expected.hex()}, "
            f"got {actual.hex()}"
        )
    return _decode(body)


def has_cbor() -> bool:
    """Report whether cbor2 is available. Useful for diagnostics and
    plexus_deploy.sh preflight."""
    return _CBOR_AVAILABLE


def overhead_budget_bytes() -> int:
    """The fixed overhead reserved per frame for header + hash + idx +
    HLC + truncated sig. Exposed so callers can size payloads
    intelligently. Matches sensorium-research.md §2 accounting."""
    return 48
