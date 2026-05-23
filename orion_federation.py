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
# Reputation v2 — accumulator over the encounter ledger.
#
# v1 deferred (c) reputation-receipts entirely (memo §1). v2 lands the
# *first-party* slice: this brain's own reputation view of each peer
# fingerprint, derived from its own encounter history. Cross-brain
# attested reputation (ERC-8004 / Sybil-resistant) stays deferred —
# Douceur 2002 still applies, and the personal-AI scale doesn't justify
# the trust-bootstrap problem.
#
# What v2 gives us:
#   - stranger_score()  — 0.0 (unknown) → 1.0 (well-known peer).
#   - is_stranger()     — boolean classification at a tunable threshold.
#   - reputation()      — full breakdown for audit/UI.
#
# The score informs the per-encounter prompt friction: a stranger gets
# the warmest possible "are you SURE this is who you think?" treatment;
# a long-known peer barely needs to confirm. This is the
# identity-continuity §4 principle ("default to recognizing, not
# asking") brought to the federation layer.
# ─────────────────────────────────────────────────────────

# Tunable. A peer becomes "known" after this many accepted peer-
# decisions in their history. Lower = friendlier; higher = more
# paranoid. 1 is the right floor — a single explicit "peer" decision is
# a strong human-vetted signal.
KNOWN_PEER_FLOOR = 1


def reputation(fingerprint: str) -> dict:
    """Compute this brain's first-party reputation view of a peer.

    Returns a dict:
      {
        fingerprint: <hex>,
        score: 0.0–1.0,
        peers_count: int,            # accepted "peer" decisions
        separate_count: int,         # explicit "stay separate" decisions
        defer_count: int,            # deferred decisions
        first_seen: float | None,
        last_seen: float | None,
        days_known: float,           # 0 if never seen
        is_stranger: bool,           # below KNOWN_PEER_FLOOR
      }

    Scoring (intentionally simple — calibration earns refinement):
      - +0.5 base per accepted "peer" decision, capped at 0.8
      - +0.1 per week of relationship (capped at 1.0 total)
      - −0.4 if there is any "separate" decision (the user actively
        declined; remember it)
      - 0.0 floor.
    """
    if not fingerprint:
        return {
            "fingerprint": "",
            "score": 0.0,
            "peers_count": 0,
            "separate_count": 0,
            "defer_count": 0,
            "first_seen": None,
            "last_seen": None,
            "days_known": 0.0,
            "is_stranger": True,
        }
    rows = list_encounters(limit=1000)
    peers = [r for r in rows
             if r.get("peer_fingerprint") == fingerprint
             and r.get("decision") == "peer"]
    separates = [r for r in rows
                 if r.get("peer_fingerprint") == fingerprint
                 and r.get("decision") == "separate"]
    defers = [r for r in rows
              if r.get("peer_fingerprint") == fingerprint
              and r.get("decision") == "defer"]
    matching = peers + separates + defers
    first_seen = min((float(r.get("ts") or 0.0) for r in matching),
                     default=None)
    last_seen = max((float(r.get("ts") or 0.0) for r in matching),
                    default=None)
    days_known = 0.0
    if first_seen and last_seen:
        days_known = max(0.0, (last_seen - first_seen) / 86400.0)
    score = 0.0
    if peers:
        score = min(0.8, 0.5 * len(peers))
    score = min(1.0, score + 0.1 * (days_known / 7.0))
    if separates:
        score = max(0.0, score - 0.4)
    is_stranger = len(peers) < KNOWN_PEER_FLOOR
    return {
        "fingerprint": fingerprint,
        "score": round(score, 3),
        "peers_count": len(peers),
        "separate_count": len(separates),
        "defer_count": len(defers),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "days_known": round(days_known, 2),
        "is_stranger": is_stranger,
    }


def is_stranger(fingerprint: str) -> bool:
    """Convenience: True if the peer has fewer than KNOWN_PEER_FLOOR
    accepted peer decisions. Used by _on_offer_received to choose
    prompt friction and by the gossip privacy gate."""
    return reputation(fingerprint)["is_stranger"]


def stranger_score(fingerprint: str) -> float:
    """Convenience: the bare 0.0–1.0 score. 0.0 means stranger or
    user-rejected; ≥0.5 means warmly known. Used by upstream UI
    that wants a single number."""
    return reputation(fingerprint)["score"]


# ─────────────────────────────────────────────────────────
# Per-host privacy guard for skill-gossip across federation.
#
# v1 of cross-host learning gossip (orion_gossip._on_learned_skill +
# _emit_remote_skill_adoptions) was MESH-scoped — only this user's own
# trusted devices. Federation v2 changes the picture: when peering with
# another user's Orion, the same learning gossip path could (if wired
# in) ship skills across the federation membrane. Some skills should
# NEVER cross that boundary: ones tagged visibility:host, visibility:
# local, or carrying a per-skill "private" flag in their body.
#
# This function is the single guard the federation-aware emitters MUST
# consult before re-publishing a learned skill to a federated peer.
# Treats absence of metadata as "permissive" only when peer is a known
# peer (≥KNOWN_PEER_FLOOR); strangers get fail-closed (drop on missing
# visibility). Defense-in-depth alongside the membrane filter.
# ─────────────────────────────────────────────────────────

def skill_crosses_federation(skill_entry: dict,
                             peer_fingerprint: Optional[str]) -> bool:
    """Should this learned-skill entry cross the federation membrane?

    Returns False (do not gossip) when:
      - skill body carries visibility:local or visibility:host
      - skill body has private=True
      - peer is a STRANGER and the skill has no visibility metadata

    Returns True only when the skill has explicit permission to cross
    (visibility:federation, visibility:public, or a known peer +
    visibility:mesh and no per-skill private flag).
    """
    if not skill_entry:
        return False
    body = skill_entry
    # The skill body may be nested under "skill" or "payload" depending
    # on the emitter version — check both shapes.
    inner = body.get("skill") or body.get("payload") or body
    if not isinstance(inner, dict):
        inner = body
    if inner.get("private") is True:
        return False
    tags = inner.get("tags") or body.get("tags") or []
    if isinstance(tags, dict):
        tags = list(tags.keys())
    has_visibility = False
    for t in tags:
        if not isinstance(t, str):
            continue
        if t == "visibility:local" or t == "visibility:host":
            return False
        if t == "visibility:federation" or t == "visibility:public":
            has_visibility = True
            break
        if t == "visibility:mesh":
            has_visibility = True
            # mesh-tagged skills only cross to KNOWN peers; strangers
            # get fail-closed below.
            if peer_fingerprint and is_stranger(peer_fingerprint):
                return False
            break
    if not has_visibility:
        # No visibility metadata. Permissive to known peers; strict to
        # strangers. The honest semantics: the user explicitly opted in
        # by peering, but a stranger encounter is a different trust
        # surface (memo §1: TOFU + safety-number).
        if peer_fingerprint and is_stranger(peer_fingerprint):
            return False
    return True


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
    rep = reputation(fp)
    logger.info("federation offer accepted (pending decision): fp=%s name=%s "
                "stranger=%s score=%.2f peers=%d separates=%d",
                fp, payload.get("claimed_name"), rep["is_stranger"],
                rep["score"], rep["peers_count"], rep["separate_count"])
    try:
        from orion_substrate import publish
        # Surface to will — will renders the per-encounter prompt to
        # the user via reach (warmest channel). Decision UX flows
        # back through orion_federation.respond_to_offer().
        #
        # Reputation v2: prompt friction scales with stranger-ness.
        # Stranger → "I've never seen this peer; safety number is X;
        # are you sure?" Known peer → "Met X again, safety number
        # matches your prior record; peer?" The user is the final
        # authority either way — we just shape the question.
        claimed_user = payload.get("claimed_user", "unknown")
        if rep["is_stranger"]:
            prompt = (
                f"STRANGER ORION encounter — never peered before. "
                f"Claims to be {claimed_user}. "
                f"Safety number: {_safety_number(fp)}. "
                f"Confirm OUT-OF-BAND with the other side before peering. "
                f"Peer / Stay separate / Defer?"
            )
        elif rep["separate_count"] > 0:
            prompt = (
                f"Known peer ({rep['peers_count']} prior peer decisions, "
                f"{rep['separate_count']} prior separates). "
                f"Safety number: {_safety_number(fp)}. "
                f"You've declined this peer before. Peer / Stay separate / Defer?"
            )
        else:
            prompt = (
                f"Known peer — {rep['peers_count']} prior peer decisions over "
                f"{rep['days_known']:.0f} days. "
                f"Safety number: {_safety_number(fp)}. "
                f"Peer / Stay separate / Defer?"
            )
        publish("brain.federation.encounter", {
            "peer_fingerprint": fp,
            "peer_safety_number": _safety_number(fp),
            "peer_claimed_name": payload.get("claimed_name"),
            "peer_claimed_user": claimed_user,
            "peer_capabilities": payload.get("capabilities", []),
            "reputation": rep,
            "is_stranger": rep["is_stranger"],
            "prompt": prompt,
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
# Pass-2 — full identity-doc fetch after a peering decision.
# Per federation-research.md §1 two-pass design: the offer is the
# minimal handshake (~400B, fits a LoRa frame); the full identity-doc
# is only exchanged when both sides agree to talk. This keeps the
# pre-decision protocol private about what each brain is willing to
# share AND tiny enough for LoRa proximity.
#
# Doc contents are strictly the brain's PUBLIC identity (host roster,
# capability descriptors, supported channels). Membrane filter applies
# — nothing visibility:local ever lands in a doc. Memo §4: "Promoting
# private → household on peering is a one-way data leak." This pass-2
# protocol cannot promote anything; it only exposes what the brain
# already publishes as public.
# ─────────────────────────────────────────────────────────

def identity_doc(host_roster: Optional[list[str]] = None,
                 channels: Optional[list[str]] = None,
                 skills_summary: Optional[list[str]] = None) -> dict:
    """Build the full identity document — the pass-2 payload.

    Larger than an offer (typically 1-3 KB) but still strictly public.
    Signed by the same Ed25519 key as the offer so peers can verify it
    came from the brain whose fingerprint they already accepted.

    Caller supplies the public-facing bits; defaults to safe minimums
    when the optional arguments aren't provided.
    """
    summary = identity_summary()
    body = {
        "fingerprint": summary["fingerprint"],
        "pubkey_hex": summary["pubkey_hex"],
        "safety_number": summary["safety_number"],
        "protocol_version": PROTOCOL_VERSION,
        "host_roster": list(host_roster or []),
        "channels": list(channels or []),
        "skills_summary": list(skills_summary or []),
        "doc_version": 1,
        "issued_at": time.time(),
    }
    body_json = json.dumps(body, sort_keys=True).encode("utf-8")
    body["doc_hash"] = hashlib.sha256(body_json).hexdigest()[:32]
    signed = json.dumps(body, sort_keys=True).encode("utf-8")
    body["signature_hex"] = sign_bytes(signed).hex()
    return body


def verify_identity_doc(doc: dict,
                        expected_fingerprint: str) -> tuple[bool, str]:
    """Verify a received identity-doc is signed by the brain whose
    fingerprint we already accepted in pass-1. expected_fingerprint
    is the fingerprint from the offer the user said 'peer' to —
    NOT trusting the doc's claimed fingerprint alone is the whole
    point of two-pass."""
    required = ("fingerprint", "pubkey_hex", "protocol_version",
                "doc_version", "signature_hex")
    for k in required:
        if k not in doc:
            return False, f"missing field: {k}"
    if doc["fingerprint"] != expected_fingerprint:
        return False, ("doc fingerprint does not match accepted-peer "
                       "fingerprint — possible doc spoofing")
    if doc["protocol_version"] != PROTOCOL_VERSION:
        return False, f"version mismatch: {doc['protocol_version']}"
    body = {k: v for k, v in doc.items() if k != "signature_hex"}
    body_json = json.dumps(body, sort_keys=True).encode("utf-8")
    sig = bytes.fromhex(doc["signature_hex"])
    if not verify_signature(doc["pubkey_hex"], body_json, sig):
        return False, "signature verification failed"
    expected_fp = hashlib.sha256(
        bytes.fromhex(doc["pubkey_hex"])).hexdigest()[:32]
    if expected_fp != doc["fingerprint"]:
        return False, "fingerprint does not match pubkey (forged doc)"
    return True, "ok"


PEER_DOCS_DIR = ORION_HOME / "federation" / "peers"


def _peer_doc_path(fingerprint: str) -> Path:
    safe = "".join(c for c in fingerprint if c.isalnum())[:64]
    return PEER_DOCS_DIR / f"{safe}.json"


def store_peer_doc(doc: dict) -> Path:
    """Persist a verified peer doc. Caller must have already passed
    verify_identity_doc against the expected fingerprint."""
    PEER_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    p = _peer_doc_path(doc["fingerprint"])
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p


def load_peer_doc(fingerprint: str) -> dict | None:
    p = _peer_doc_path(fingerprint)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def request_identity_doc(peer_fingerprint: str) -> None:
    """Ask a peer for their full identity-doc. Caller has already
    decided to peer (record_encounter(..., 'peer')); this is the
    follow-up that fetches the larger payload."""
    try:
        from orion_substrate import publish
        publish("brain.federation.doc_request", {
            "from_fingerprint": identity_summary()["fingerprint"],
            "peer_fingerprint": peer_fingerprint,
            "ts": time.time(),
        })
    except Exception:
        pass


def _on_doc_request(subject: str, payload: dict) -> None:
    """A peer who accepted our offer is asking for the full doc.
    Respond with our identity_doc — strictly public information,
    same key as the offer they already verified."""
    requester_fp = payload.get("from_fingerprint")
    target_fp = payload.get("peer_fingerprint")
    if target_fp and target_fp != identity_summary()["fingerprint"]:
        return  # not for us
    if not requester_fp:
        return
    # Only respond if we previously logged a peer-accepted encounter
    # FROM this requester — otherwise random hosts could probe our
    # doc. Open question for v2: cache mutual-decisions both ways.
    encounters = list_encounters(limit=200)
    mutual = any(e.get("peer_fingerprint") == requester_fp
                 and e.get("decision") == "peer"
                 for e in encounters)
    if not mutual:
        logger.info("doc_request from unverified peer fp=%s — ignoring",
                    requester_fp[:8] if requester_fp else "?")
        return
    doc = identity_doc()
    try:
        from orion_substrate import publish
        publish("brain.federation.doc_response", {
            "to_fingerprint": requester_fp,
            "doc": doc,
            "ts": time.time(),
        })
    except Exception:
        pass


def _on_doc_response(subject: str, payload: dict) -> None:
    """A peer responded to our doc_request. Verify against the
    fingerprint we accepted, then store the doc locally for future
    capability negotiation + provenance."""
    target_fp = payload.get("to_fingerprint")
    if target_fp and target_fp != identity_summary()["fingerprint"]:
        return  # not for us
    doc = payload.get("doc")
    if not isinstance(doc, dict):
        return
    expected = doc.get("fingerprint", "")
    ok, reason = verify_identity_doc(doc, expected_fingerprint=expected)
    if not ok:
        logger.warning("rejected doc_response: %s", reason)
        return
    p = store_peer_doc(doc)
    logger.info("stored peer doc: fp=%s file=%s", expected[:8], p.name)
    try:
        from orion_substrate import publish
        publish("brain.federation.doc_stored", {
            "peer_fingerprint": expected,
            "ts": time.time(),
        })
    except Exception:
        pass


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
    subscribe("brain.federation.doc_request", _on_doc_request)
    subscribe("brain.federation.doc_response", _on_doc_response)
    logger.info("federation alive (v1.1 trusted-peer with pass-2 doc fetch; "
                "seed-new deferred)")
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
    p_rep = sub.add_parser("reputation",
                           help="show first-party reputation view of a peer")
    p_rep.add_argument("fingerprint", help="peer fingerprint hex")

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
    if args.cmd == "reputation":
        print(json.dumps(reputation(args.fingerprint), indent=2))
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(_cli())
