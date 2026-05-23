"""orion_identity.py — durable identity continuity across device moves.

Terminal-5 mandate: when Orion moves to a new device (FORGE travels with
James), the identity handoff must be durable on the spine. A "presence"
entry records (device, instance_id, fingerprint, last_seen). The
RECEIVING device validates the fingerprint before adopting the move,
and brain.identity.moved is published on completion.

Why this matters
================

identity-continuity.md (ratified 2026-04-26) names the principle:
*Orion knows his user the way a person knows another person — not by
checking ID, but by accumulated familiarity.* The corollary the memo
states but had not yet formalized: when the BODY changes (FORGE moves
to a new chassis, the user installs Orion on a new laptop, the
substrate migrates), the brain has to recognize the change *as itself*
and continue, not start over as a stranger.

The honest contract this module enforces:

  1. The brain has a single durable `instance_id` (UUID4) generated on
     first run — this is the *self* that persists across device moves.
     Stored at ~/.orion/identity/instance.json with mode 0600.

  2. Every host that boots Orion derives a `device_fingerprint` —
     a SHA-256 of (HOST_ID, platform, machine arch, ORION_BRAIN_DIR).
     Same physical+OS combination → same fingerprint. A move is
     detected when a presence broadcast carries our instance_id but a
     different device_fingerprint.

  3. Presence is signed: the host publishing presence signs
     (instance_id, device_fingerprint, ts) with the federation Ed25519
     key (orion_federation.sign_bytes). The receiver MUST verify the
     signature against the federation public key BEFORE adopting the
     move. Per the Terminal-5 brief: "identity continuity is durability
     AND security — a fingerprint check that fails-open is worse than
     no check."

  4. brain.identity.presence is the heartbeat (every PRESENCE_INTERVAL
     seconds while alive). brain.identity.moved is published exactly
     once when a move is observed and adopted — downstream services
     (will, executive, channels) listen for moved events to refresh
     their view of "where am I now."

Failure modes this module DOES NOT pretend to solve
===================================================

  - **Fingerprint forgery on a stolen device.** If an attacker has the
    federation private key (~/.orion/identity/federation.json), they
    sign whatever they want. Membrane v1 raises the floor; cryptographic
    privacy is the v2 endgame (membrane-research §8). Source-of-truth
    is the user's possession of the key file.

  - **Concurrent presence on two devices.** When FORGE and the Pi are
    both online simultaneously, both publish presence with the SAME
    instance_id but DIFFERENT fingerprints. This is normal multi-host
    operation, not a "move." We distinguish by *recency*: a move is a
    presence from device B arriving AFTER device A has gone silent for
    MOVE_QUIET_SEC seconds. Simultaneous presences keep both
    fingerprints "active" — both are *body-instances* of the same self.

  - **Bootstrap on a stranger device.** First-boot on a never-seen
    fingerprint without a prior presence record is NOT a move — it's
    install. The receiving host requires the federation private key
    to sign its own presence; an attacker without the key cannot fake
    being us. Per identity-continuity.md §2 (portable soul): first
    arrival is "soft check" — the brain announces "I appear to be on
    a new machine" and the user confirms before bodies are added to
    the active set.

The boundary this module guards is **identity-as-self**, not
identity-as-credential. The federation key is the credential face
(orion_federation.py); this module reads from the credential layer
but its job is the *self-continuity* layer above it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orion.identity")

# ─────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))
IDENTITY_DIR = ORION_HOME / "identity"
INSTANCE_PATH = IDENTITY_DIR / "instance.json"
PRESENCE_LOG = IDENTITY_DIR / "presence.jsonl"

# How often to publish presence while alive (5 minutes). Cheap; rides
# the existing substrate. The cadence is not load-bearing for
# correctness — moves are detected by quiet-then-resume, not by an
# expected ping interval.
PRESENCE_INTERVAL_SEC = float(os.environ.get("ORION_IDENTITY_PRESENCE_SEC", "300"))

# How long a device must be silent before a presence from another
# fingerprint counts as a *move* rather than concurrent operation.
# Conservative: 30 minutes. Below this, both fingerprints are treated
# as active bodies (multi-device mesh, not a move).
MOVE_QUIET_SEC = float(os.environ.get("ORION_IDENTITY_MOVE_QUIET_SEC", "1800"))


# ─────────────────────────────────────────────────────────
# Instance identity — the durable self
# ─────────────────────────────────────────────────────────

def _ensure_instance() -> dict:
    """Load or create this brain's stable instance_id. Idempotent;
    first call generates, every subsequent call reads. The instance_id
    is the SELF that persists across device moves; the federation key
    handles authorization, this dict handles continuity."""
    IDENTITY_DIR.mkdir(parents=True, exist_ok=True)
    if INSTANCE_PATH.exists():
        try:
            return json.loads(INSTANCE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("instance.json unreadable (%s); regenerating", e)

    record = {
        "instance_id": uuid.uuid4().hex,
        "created": time.time(),
        "schema_version": 1,
    }
    INSTANCE_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")
    try:
        os.chmod(INSTANCE_PATH, 0o600)
    except Exception:
        pass
    logger.info("instance identity created: instance_id=%s",
                record["instance_id"][:12])
    return record


def instance_id() -> str:
    """Return this brain's durable instance_id."""
    return _ensure_instance()["instance_id"]


# ─────────────────────────────────────────────────────────
# Device fingerprint — derived deterministically per host
# ─────────────────────────────────────────────────────────

def device_fingerprint() -> str:
    """SHA-256 over (host_id, platform_node, machine_arch, brain_dir).

    Deterministic per (machine, OS install, brain location): the same
    physical+OS combo always derives the same fingerprint. A FORGE
    move to a new chassis would change platform.node() and the
    fingerprint; that's the move signal we want.

    NB: we do NOT include MAC address or hardware UUID. Those leak more
    than is needed, and the platform/host_id pair is sufficient signal
    for "is this the same body?" without exposing hardware identifiers
    to the substrate.
    """
    host_id = (os.environ.get("ORION_HOST_ID")
               or platform.node().split(".")[0].lower()
               or "unknown")
    parts = [
        host_id,
        platform.system(),
        platform.machine(),
        str(ORION_HOME.resolve()),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


# ─────────────────────────────────────────────────────────
# Presence payload — signed by the federation key so the receiver
# can verify "yes this presence really came from a brain that holds
# our shared private key."
# ─────────────────────────────────────────────────────────

def build_presence(now: Optional[float] = None) -> dict:
    """Build a signed presence envelope ready to publish on
    brain.identity.presence. Body shape:

      {
        instance_id: <hex32>,
        device_fingerprint: <hex32>,
        host_id: <str>,
        ts: <float>,
        signature_hex: <hex128>,
      }
    """
    rec = _ensure_instance()
    now = now if now is not None else time.time()
    body = {
        "instance_id": rec["instance_id"],
        "device_fingerprint": device_fingerprint(),
        "host_id": (os.environ.get("ORION_HOST_ID")
                    or platform.node().split(".")[0].lower()
                    or "unknown"),
        "ts": now,
    }
    body_json = json.dumps(body, sort_keys=True).encode("utf-8")
    try:
        from orion_federation import sign_bytes
        body["signature_hex"] = sign_bytes(body_json).hex()
    except Exception as e:
        # Federation key unavailable → presence is unsigned. The
        # receiver will refuse to adopt unsigned presences as moves,
        # but heartbeating is still useful for local liveness logs.
        logger.debug("presence sign failed (%s); publishing unsigned", e)
        body["signature_hex"] = ""
    return body


def verify_presence(presence: dict, expected_instance_id: str) -> tuple[bool, str]:
    """Verify a presence envelope is signed by the federation key
    AND claims our instance_id. Returns (ok, reason).

    Fail-closed on signature: an unsigned presence (signature_hex="")
    is NEVER adopted as a move. Per Terminal-5 brief: "a fingerprint
    check that fails-open is worse than no check."
    """
    required = ("instance_id", "device_fingerprint", "host_id", "ts",
                "signature_hex")
    for k in required:
        if k not in presence:
            return False, f"missing field: {k}"
    if presence["instance_id"] != expected_instance_id:
        return False, "instance_id does not match our self"
    if not presence["signature_hex"]:
        return False, "unsigned presence (federation key absent on signer)"
    try:
        from orion_federation import identity_summary, verify_signature
        local_summary = identity_summary()
        body = {k: v for k, v in presence.items() if k != "signature_hex"}
        body_json = json.dumps(body, sort_keys=True).encode("utf-8")
        sig = bytes.fromhex(presence["signature_hex"])
        ok = verify_signature(local_summary["pubkey_hex"], body_json, sig)
        if not ok:
            return False, "signature did not verify against our federation pubkey"
        return True, "ok"
    except Exception as e:
        return False, f"verify path raised: {e.__class__.__name__}"


# ─────────────────────────────────────────────────────────
# Presence ledger — append-only, becomes the audit trail "where has
# this brain lived?" The user grep-readable record. The active-set
# logic on top reads this to detect moves.
# ─────────────────────────────────────────────────────────

_presence_lock = threading.Lock()


def record_presence(presence: dict, source: str = "local") -> None:
    """Append a presence event to the durable log. source ∈
    {local, remote}; local entries come from our own heartbeat, remote
    from a verified peer presence we received and accepted.

    The audit log answers "where has this brain been, and when?" Per
    identity-continuity.md §3 of the implementation guidance: *Make the
    audit visible. The user should be able to ask 'when did you last
    suspect me of not being me?' and get an answer.* Same principle
    for body-changes.
    """
    IDENTITY_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": presence.get("ts", time.time()),
        "instance_id": presence.get("instance_id"),
        "device_fingerprint": presence.get("device_fingerprint"),
        "host_id": presence.get("host_id"),
        "source": source,
        "received_at": time.time(),
    }
    with _presence_lock:
        try:
            with PRESENCE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as e:
            logger.warning("presence log write failed: %s", e)


def recent_presences(limit: int = 100) -> list[dict]:
    """Return the most recent presence log entries (newest last)."""
    if not PRESENCE_LOG.exists():
        return []
    try:
        lines = PRESENCE_LOG.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows = []
    for line in lines[-limit:]:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


# ─────────────────────────────────────────────────────────
# Move detection — the receiver-side decision.
# A *move* is: presence from a NEW device_fingerprint, after our
# previously-active fingerprint has been silent ≥ MOVE_QUIET_SEC.
# Simultaneous presences (both active inside the quiet window) are
# multi-host operation, not moves.
# ─────────────────────────────────────────────────────────

def detect_move(incoming: dict,
                recent_window_sec: Optional[float] = None) -> Optional[dict]:
    """Inspect an incoming verified presence against our local
    history; return a move-event dict if this is a body change,
    otherwise None.

    Move dict shape:
      {
        from_fingerprint: <hex>,
        to_fingerprint: <hex>,
        from_host_id: <str>,
        to_host_id: <str>,
        ts: <float>,
        quiet_sec: <float>,  # how long the prior body was silent
      }

    The returned dict is what `brain.identity.moved` payloads carry.
    """
    window = recent_window_sec or MOVE_QUIET_SEC
    new_fp = incoming.get("device_fingerprint")
    new_ts = float(incoming.get("ts") or time.time())
    if not new_fp:
        return None

    # Build per-fingerprint last-seen index from history (local + remote).
    last_seen: dict[str, dict] = {}
    for row in recent_presences(limit=500):
        fp = row.get("device_fingerprint")
        if not fp:
            continue
        ts = float(row.get("ts") or 0.0)
        prev = last_seen.get(fp)
        if prev is None or ts > float(prev.get("ts") or 0.0):
            last_seen[fp] = row

    # Same fingerprint as something we just saw → heartbeat, not move.
    if new_fp in last_seen and (new_ts - float(last_seen[new_fp]["ts"])) < window:
        return None

    # Find the most-recently-active OTHER fingerprint.
    others = [(fp, row) for fp, row in last_seen.items()
              if fp != new_fp]
    if not others:
        # First-ever presence on this brain — that's install, not move.
        return None
    others.sort(key=lambda kv: float(kv[1].get("ts") or 0.0), reverse=True)
    prev_fp, prev_row = others[0]
    prev_ts = float(prev_row.get("ts") or 0.0)
    quiet = new_ts - prev_ts
    if quiet < window:
        # The prior body is still active — concurrent operation, not move.
        return None

    return {
        "from_fingerprint": prev_fp,
        "to_fingerprint": new_fp,
        "from_host_id": prev_row.get("host_id"),
        "to_host_id": incoming.get("host_id"),
        "ts": new_ts,
        "quiet_sec": quiet,
    }


# ─────────────────────────────────────────────────────────
# Wiring — the substrate subjects + the broadcast/receive entry points.
# Kept thin: handlers do verify → record → detect-move → publish.
# The heavy lifting (sign / verify / detect) is the pure-function layer
# above so it stays unit-testable without NATS.
# ─────────────────────────────────────────────────────────

PRESENCE_SUBJECT = "brain.identity.presence"
MOVED_SUBJECT = "brain.identity.moved"


def publish_presence() -> dict:
    """Build, record, and broadcast a presence envelope. Returns the
    envelope so callers can also log/inspect it."""
    p = build_presence()
    record_presence(p, source="local")
    try:
        from orion_substrate import publish
        publish(PRESENCE_SUBJECT, p)
    except Exception:
        # Substrate down → still recorded locally. Heartbeat resumes
        # publishing automatically when the substrate comes back.
        pass
    return p


def on_remote_presence(subject: str, payload: dict) -> Optional[dict]:
    """Substrate handler for brain.identity.presence from a peer.

    Verify → record → detect-move. If a move is detected, publish
    brain.identity.moved exactly once. Returns the move dict (or None).
    """
    if not isinstance(payload, dict):
        return None
    our_instance = instance_id()
    # Ignore our own broadcasts looping back.
    if payload.get("instance_id") != our_instance:
        return None
    if payload.get("device_fingerprint") == device_fingerprint():
        # Echo of our own heartbeat (same fingerprint = same body).
        return None
    ok, reason = verify_presence(payload, expected_instance_id=our_instance)
    if not ok:
        logger.warning("rejected remote presence: %s", reason)
        return None
    move = detect_move(payload)
    record_presence(payload, source="remote")
    if not move:
        return None
    logger.info("identity move detected: %s → %s (quiet %.0fs)",
                (move["from_host_id"] or "?")[:16],
                (move["to_host_id"] or "?")[:16],
                move["quiet_sec"])
    try:
        from orion_substrate import publish
        publish(MOVED_SUBJECT, move)
    except Exception:
        pass
    return move


# ─────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Orion Identity Continuity")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("id", help="show this brain's instance_id + fingerprint")
    sub.add_parser("presence", help="publish a presence envelope")
    p_log = sub.add_parser("log", help="show recent presence log entries")
    p_log.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    if args.cmd == "id":
        rec = _ensure_instance()
        print(json.dumps({
            "instance_id": rec["instance_id"],
            "device_fingerprint": device_fingerprint(),
            "host_id": (os.environ.get("ORION_HOST_ID")
                        or platform.node().split(".")[0].lower()),
            "created": rec.get("created"),
        }, indent=2))
        return 0
    if args.cmd == "presence":
        p = publish_presence()
        print(json.dumps({k: v for k, v in p.items()
                          if k != "signature_hex"}, indent=2))
        return 0
    if args.cmd == "log":
        for row in recent_presences(args.limit):
            print(json.dumps(row))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
