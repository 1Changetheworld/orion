"""orion_federation.py — Orion-meets-Orion peering (v1, trusted-peer).

Per docs/architecture/federation-research.md (3,004 words, filed 2026-05-16).
The dialectical partner to brain-merge-and-rejoin.md (two-brains-one-
user) and mesh-workflow.md (one-user-multi-device). Federation is the
next generalization: two users' Orions, meeting, deciding what they
are to each other.

The memo's sharpest line is the scope discipline this v1 honors:

    > The founder's near-term need is brain-merge with peer-identity
    > wrapping, not federation; the vision is correct, the sequence is
    > wrong.

So v1 builds the *trusted-peer* slice — his Orion + partner's Orion,
his + co-founder's. Auditable two-party setups that look more like
Solid pod sharing than Matrix federation. Stranger-meets-stranger
(LoRa proximity, third-party reputation) is **explicitly deferred**
to v2. Seed-new (creating a third autonomous cognitive entity from
two existing brains meeting) is **explicitly deferred** to its own
spec — the memo names this as deserving separate treatment.

ARCHITECTURE (memo §7 recommended v1)
=====================================

Thin module wrapping the existing gossip layer with:

  1. Identity ratchet — Ed25519 keypair generated at first run;
     fingerprint = SHA-256(pubkey)[:16] surfaced as a 5-word safety
     number for human verification. Stored at
     ~/.orion/identity/federation.json alongside SOUL.md / USER.md.

  2. Per-encounter encounter_offer — small (~400 byte) signed envelope
     {fingerprint, pubkey, claimed_name, claimed_user, install_date,
      capabilities, protocol_version, doc_hash, signature}. Sent over
     brain.federation.offer; received from brain.federation.offer.

  3. Peer-scope tags via Membrane overlay — additive only, never
     destructive promotion. A node tagged visibility:mesh stays mesh-
     scoped on this host; a peering only adds peer-scope overlays for
     specific receivers. The CRDT bit lives on the peer's disk forever
     once shipped, so demotion is best-effort warning to peers
     (orion.federation.recall event), not enforced clawback.

  4. Per-encounter prompt via Will — every offer received publishes
     brain.federation.encounter with the offer + a decision question.
     Will surfaces it to the user via reach (warmest channel). User
     answers one of {peer, separate, defer}. Decision is itself a
     recallable memory.

WHAT THIS v1 DEPENDS ON
=======================

  Membrane (orion_membrane.py)  — pre-wired brain.federation.* as
                                  DEST_FEDERATION at acdbd94. peer
                                  filtering goes through filter_manifest
                                  before any cross-brain gossip.
  Gossip (orion_gossip.py)      — the CRDT layer Federation rides on.
                                  Federation adds peer-aware filtering
                                  ON TOP, not in.
  Will (orion_will.py)          — consumes brain.federation.encounter
                                  events as goal candidates; user
                                  decides via the warmest channel.

WHAT'S EXPLICITLY OUT OF SCOPE FOR v1
=====================================

  - Seed-new (third-brain creation from two peers). Memo §2: deserves
    its own spec with disputed-ownership / identity-continuity /
    dissolution semantics worked out.
  - Stranger reputation receipts (ERC-8004-style). Memo §1c: requires
    the trust layer it claims to bootstrap (Douceur 2002 Sybil
    impossibility). Defer to v2.
  - Provenance CRDT (Automerge + Conlon receipts for co-existing
    attributed perceptions). Memo §3: needed when two peers form
    memories about the same event with different perspectives.
    v1 uses standard LWW; cross-peer co-perception is documented
    as a known limitation.
  - Cryptographic content encryption per-node. The Membrane v1
    critique (memo §8) — Membrane is software-permission privacy,
    not crypto. Same applies here. Federation v1 trusts the substrate;
    v2 adds per-node encryption keys.

HONESTY
=======

This is a thin wrapping of gossip with crypto identity. It is not
ambitious cryptography — it is the cheapest correct floor for the
two-trusted-Orions-meeting case the founder will actually use this
year. When stranger-federation becomes the use case, this module
gets the v2 expansion the memo specifies — not before.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orion.federation")

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))
IDENTITY_DIR = ORION_HOME / "identity"
FEDERATION_PATH = IDENTITY_DIR / "federation.json"
ENCOUNTER_LOG = ORION_HOME / "federation" / "encounters.jsonl"

PROTOCOL_VERSION = "1.0"


# ─────────────────────────────────────────────────────────
# Identity ratchet — Ed25519 keypair + safety-number derivation.
# cryptography is a hard dep for Federation; the memo §1 ranks
# Signal-style ratchet as the load-bearing primitive (a bare hash
# leaks nothing AND tells nothing). Imports lazily so the rest of
# Orion stays importable on hosts without cryptography.
# ─────────────────────────────────────────────────────────

def _ensure_identity() -> dict:
    """Load or create this Orion's federation identity. Idempotent;
    safe to call from any callsite. Returns the dict that persists
    at FEDERATION_PATH (pubkey + fingerprint + safety_number; the
    private key never leaves disk and is loaded only at sign time)."""
    IDENTITY_DIR.mkdir(parents=True, exist_ok=True)
    if FEDERATION_PATH.exists():
        try:
            return json.loads(FEDERATION_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("federation.json unreadable (%s); regenerating", e)

    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from cryptography.hazmat.primitives import serialization

    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()
    pk_bytes = pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    sk_bytes = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    fingerprint = hashlib.sha256(pk_bytes).hexdigest()[:32]
    record = {
        "pubkey_hex": pk_bytes.hex(),
        "privkey_hex": sk_bytes.hex(),  # local-only; never leaves disk
        "fingerprint": fingerprint,
        "safety_number": _safety_number(fingerprint),
        "created": time.time(),
        "protocol_version": PROTOCOL_VERSION,
    }
    FEDERATION_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")
    # The private key must not be world-readable; best-effort chmod.
    try:
        os.chmod(FEDERATION_PATH, 0o600)
    except Exception:
        pass
    logger.info("federation identity created: fingerprint=%s safety=%s",
                fingerprint, record["safety_number"])
    return record


# 5-word safety number — human-verifiable out-of-band. Memo §1a notes
# Signal-style word lists prevent typo-attack and are easier to read
# aloud than hex. Use a small built-in list for v1; richer EFF-style
# word list lands in a follow-up.
_SAFETY_WORDS = [
    "alpha", "bravo", "cedar", "delta", "ember", "forge", "gamma", "harbor",
    "iris", "jasper", "kelp", "lumen", "mesa", "north", "ocean", "pluto",
    "quartz", "river", "sage", "topaz", "umbra", "violet", "willow", "xenon",
    "yarrow", "zephyr", "amber", "basil", "coral", "dusk", "echo", "frost",
]


def _safety_number(fingerprint_hex: str) -> str:
    """Render the first 25 bits of fingerprint as five 5-bit words.
    32 words × 5 selections = 32^5 ≈ 33M combinations. Enough to
    catch typo attacks; not enough for adversarial preimage. The
    full fingerprint is the actual security boundary."""
    fp = bytes.fromhex(fingerprint_hex)
    # Pack first 5 bytes as 5 indices into the 32-word list.
    return " ".join(_SAFETY_WORDS[b & 0x1F] for b in fp[:5])


def identity_summary() -> dict:
    """Public view of this brain's identity — fingerprint + safety
    number + protocol version. NEVER includes the private key. Safe
    to return from MCP tools / dashboards / encounter offers."""
    rec = _ensure_identity()
    return {
        "fingerprint": rec["fingerprint"],
        "safety_number": rec["safety_number"],
        "pubkey_hex": rec["pubkey_hex"],
        "protocol_version": rec["protocol_version"],
        "created": rec["created"],
    }


def sign_bytes(data: bytes) -> bytes:
    """Sign with this brain's Ed25519 private key. 64-byte signature
    full; transports/encoding.py truncates to 16 bytes for LoRa
    frames per sensorium-research.md §2."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    rec = _ensure_identity()
    sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(rec["privkey_hex"]))
    return sk.sign(data)


def verify_signature(pubkey_hex: str, data: bytes, signature: bytes) -> bool:
    """Verify a peer's signature against their advertised pubkey.
    Returns False on any cryptographic failure — never raises."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
        pk.verify(signature, data)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────
# Encounter protocol — two-pass per memo §1:
#   1. Small signed offer (~400 bytes, fits a LoRa packet)
#   2. Full identity-doc fetched only if both sides decide to talk
# v1 ships pass-1 only; pass-2 (full-doc exchange) lands in v1.1
# once a real peer is wired and there's something to test against.
# ─────────────────────────────────────────────────────────

def make_offer(claimed_name: str = "Orion",
               claimed_user: str = "",
               capabilities: Optional[list] = None) -> dict:
    """Build the signed encounter_offer this brain advertises to peers.
    Caller publishes via orion_substrate to brain.federation.offer."""
    rec = _ensure_identity()
    body = {
        "fingerprint": rec["fingerprint"],
        "pubkey_hex": rec["pubkey_hex"],
        "claimed_name": claimed_name,
        "claimed_user": claimed_user,
        "install_date": rec["created"],
        "capabilities": list(capabilities or ["recall", "memorize", "reach"]),
        "protocol_version": PROTOCOL_VERSION,
    }
    body_json = json.dumps(body, sort_keys=True).encode("utf-8")
    body["doc_hash"] = hashlib.sha256(body_json).hexdigest()[:16]
    signed_payload = json.dumps(body, sort_keys=True).encode("utf-8")
    body["signature_hex"] = sign_bytes(signed_payload).hex()
    return body


def verify_offer(offer: dict) -> tuple[bool, str]:
    """Verify a received offer is internally consistent + signed by
    the claimed pubkey. Returns (ok, reason). Reasons are diagnostic;
    a failed verify never raises into the receiver."""
    required = ("fingerprint", "pubkey_hex", "claimed_name",
                "protocol_version", "signature_hex")
    for k in required:
        if k not in offer:
            return False, f"missing field: {k}"
    if offer["protocol_version"] != PROTOCOL_VERSION:
        return False, f"version mismatch: {offer['protocol_version']}"
    # Re-derive the signed body (everything except signature_hex itself).
    body = {k: v for k, v in offer.items() if k != "signature_hex"}
    body_json = json.dumps(body, sort_keys=True).encode("utf-8")
    sig = bytes.fromhex(offer["signature_hex"])
    if not verify_signature(offer["pubkey_hex"], body_json, sig):
        return False, "signature verification failed"
    # Cross-check: fingerprint must derive from advertised pubkey.
    expected_fp = hashlib.sha256(
        bytes.fromhex(offer["pubkey_hex"])).hexdigest()[:32]
    if expected_fp != offer["fingerprint"]:
        return False, "fingerprint does not match pubkey"
    return True, "ok"


def record_encounter(offer: dict, decision: str, note: str = "") -> dict:
    """Log a per-encounter record. decision ∈ {peer, separate, defer}.
    Append-only. Becomes a recallable memory via the substrate; user
    can ask 'who have I peered with' and get this back."""
    if decision not in ("peer", "separate", "defer"):
        raise ValueError(f"invalid decision: {decision}")
    record = {
        "ts": time.time(),
        "peer_fingerprint": offer.get("fingerprint"),
        "peer_safety_number": _safety_number(offer.get("fingerprint", "")),
        "peer_claimed_name": offer.get("claimed_name"),
        "peer_claimed_user": offer.get("claimed_user"),
        "decision": decision,
        "note": note,
    }
    ENCOUNTER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ENCOUNTER_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


def list_encounters(limit: int = 50) -> list[dict]:
    if not ENCOUNTER_LOG.exists():
        return []
    try:
        lines = ENCOUNTER_LOG.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# ─────────────────────────────────────────────────────────
# Substrate handlers — wired by the optional daemon main().
# Other modules (orion_will) can also import and consume the
# offer-received event directly without running the daemon.
# ─────────────────────────────────────────────────────────

def _on_offer_received(subject: str, payload: dict) -> None:
    """Substrate handler — a peer published an encounter_offer.
    Verify, log a pending encounter, surface to will for user decision."""
    ok, reason = verify_offer(payload)
    if not ok:
        logger.warning("rejected federation offer: %s", reason)
        try:
            from orion_substrate import publish
            publish("brain.federation.rejected", {
                "reason": reason,
                "fingerprint": payload.get("fingerprint"),
                "ts": time.time(),
            })
        except Exception:
            pass
        return

    fp = payload["fingerprint"]
    logger.info("federation offer accepted (pending decision): fp=%s name=%s",
                fp, payload.get("claimed_name"))
    try:
        from orion_substrate import publish
        # Surface to will — will renders the per-encounter prompt to
        # the user via reach (warmest channel). Decision UX flows
        # back through orion_federation.respond_to_offer().
        publish("brain.federation.encounter", {
            "peer_fingerprint": fp,
            "peer_safety_number": _safety_number(fp),
            "peer_claimed_name": payload.get("claimed_name"),
            "peer_claimed_user": payload.get("claimed_user"),
            "peer_capabilities": payload.get("capabilities", []),
            "prompt": (
                f"Met another Orion claiming to be {payload.get('claimed_user', 'unknown')}. "
                f"Safety number {_safety_number(fp)}. "
                f"Peer / Stay separate / Defer?"
            ),
            "ts": time.time(),
        })
    except Exception:
        pass


def respond_to_offer(offer: dict, decision: str, note: str = "") -> dict:
    """User-facing decision handler. record + emit follow-up event
    so the gossip layer knows whether to start mirroring with this peer."""
    rec = record_encounter(offer, decision, note=note)
    try:
        from orion_substrate import publish
        publish(f"brain.federation.{decision}", {
            "peer_fingerprint": offer.get("fingerprint"),
            "note": note,
            "ts": time.time(),
        })
    except Exception:
        pass
    return rec


def announce_self(claimed_user: str = "") -> dict:
    """Publish this brain's offer for peers to discover. Useful as a
    one-shot from the CLI ('orion_federation announce') or wired into
    a periodic beacon when LoRa lands (Sensorium)."""
    offer = make_offer(claimed_user=claimed_user)
    try:
        from orion_substrate import publish
        publish("brain.federation.offer", offer)
    except Exception:
        pass
    return offer


# ─────────────────────────────────────────────────────────
# Daemon main + CLI
# ─────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(
        level=os.environ.get("ORION_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        logger.error("orion_substrate unavailable")
        return 1
    sub = get_substrate()
    sub._connect_blocking()
    _ensure_identity()  # generate on first run
    subscribe("brain.federation.offer", _on_offer_received)
    logger.info("federation alive (v1 trusted-peer; seed-new deferred)")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        return 0


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Orion Federation v1 diagnostics")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("id", help="show this brain's federation identity")
    p_off = sub.add_parser("announce", help="publish an encounter offer")
    p_off.add_argument("--user", default="", help="claimed_user for the offer")
    p_enc = sub.add_parser("encounters", help="list recorded encounters")
    p_enc.add_argument("--limit", type=int, default=20)

    args = ap.parse_args()
    if args.cmd == "id":
        print(json.dumps(identity_summary(), indent=2))
        return 0
    if args.cmd == "announce":
        offer = announce_self(claimed_user=args.user)
        print(f"announced: fingerprint={offer['fingerprint']} "
              f"safety={_safety_number(offer['fingerprint'])}")
        return 0
    if args.cmd == "encounters":
        for r in list_encounters(args.limit):
            print(json.dumps(r))
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(_cli())
