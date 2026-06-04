"""orion_vessel.py — the canonical identity keystone (the "main blood vessel").

Per ORION BUILD RESUME (6-1-2026) §5.1 — the founder's load-bearing
anxiety: a new terminal or device, started with low context, can wire
to *a* brain without ever verifying it is *the* canonical brain. Today
"same Orion everywhere" is HOPED FOR via gossip eventual-sync, not
ENFORCED. A silent fork can drift apart and nobody notices until the
two selves disagree.

This module is the enforcement layer the rest of the substrate was
missing. Biologically (design-law.md): identity.py + federation.py are
the *blood* (the durable self, the crypto signature on every cell).
This is the *main artery* — the single vessel every body-instance must
draw the one blood supply through. Bind to the wrong vessel and you are
no longer the same organism; you are a tumour with the same DNA.

THE THREE RESPONSIBILITIES
==========================

  1. PIN — write the ONE true {instance_id, fingerprint, pubkey_hex}
     to ~/.orion/identity/canonical.json, once, at install/adopt. This
     is the trust anchor — "set in stone." Everything downstream is
     measured against it.

  2. VERIFY-ON-BIND — before any transport (substrate discovery, MCP
     brain HTTP) trusts an endpoint, fetch that endpoint's *signed*
     whoami descriptor and check: signature valid (Ed25519, reusing
     orion_federation.verify_signature) AND fingerprint derives from
     the advertised pubkey AND it equals the pin. Match → bind.
     Cryptographically-valid-but-different → FORK (refuse + report).
     Invalid signature → tampered/unknown (refuse).

  3. NO-FORK LAW — a host that cannot verify the canonical brain (pin
     unreachable) or has no pin runs READ-ONLY + QUEUES writes. It NEVER
     silently mints a new authoritative self and starts answering as if
     it were canonical. It offers adoption instead, which writes the pin.

WHAT THIS DOES NOT DO (honesty, per the Standard of Truth)
==========================================================

  - It does not encrypt anything. Same posture as identity.py /
    federation.py v1: the source of truth is the user's possession of
    ~/.orion/identity/federation.json (the private key). An attacker
    with that key can sign a valid canonical whoami. The vessel raises
    the floor from "no check at all" to "cryptographic check against a
    pinned key"; it is not a defence against a stolen key file.

  - It does not, by itself, route writes to the canonical brain. It
    DECIDES the binding mode and gates writes; the transports
    (substrate / mcp_server) consult it. Wiring those call sites is the
    deploy step that follows founder review — this module ships first,
    standalone and tested, exactly so that review can happen against
    real code before anything in the live path changes.

  - It does not reconcile a fork automatically. A detected fork is
    logged and surfaced; merging two diverged selves is the executive's
    job (and, for cross-user, federation's). The vessel's duty is to
    PREVENT silent forks and DETECT existing ones — not to heal them.

PURELY ADDITIVE
===============

Like identity.py, the cryptographic core here is pure functions that
need no NATS, no HTTP, no running brain — so it is fully unit-testable
in a tempdir (see tests/test_vessel.py). The optional HTTP helper and
CLI sit on top. Nothing in the existing import graph depends on this
module until the deploy step wires the two seams (documented at the
bottom of this file and in docs/architecture/vessel-canonical-identity.md).
"""
from __future__ import annotations

import json
import logging
import os
import platform
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("orion.vessel")

# ─────────────────────────────────────────────────────────
# Paths — same ORION_HOME convention as identity.py / federation.py.
# ─────────────────────────────────────────────────────────

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))
IDENTITY_DIR = ORION_HOME / "identity"
CANONICAL_PATH = IDENTITY_DIR / "canonical.json"
VESSEL_DIR = ORION_HOME / "vessel"
WRITE_QUEUE_PATH = VESSEL_DIR / "write-queue.jsonl"
FORK_LOG = VESSEL_DIR / "forks.jsonl"

PROTOCOL_VERSION = "1.0"

# Binding modes — the no-fork law's four states for THIS host.
MODE_CANONICAL = "canonical"   # this host IS the pinned self → writes OK, serves whoami
MODE_BOUND = "bound"           # verified the canonical endpoint → writes OK (routed out)
MODE_ORPHAN = "orphan"         # pin exists but canonical unverifiable → READ-ONLY + queue
MODE_UNPINNED = "unpinned"     # no pin yet → READ-ONLY until adopt/pin

# Endpoint classifications from verify-on-bind.
BIND_MATCH = "canonical-match"  # this endpoint is the pinned brain → trust it
BIND_FORK = "fork"              # authentic but DIFFERENT self → refuse + report
BIND_INVALID = "invalid"        # bad signature / malformed → refuse
BIND_NO_PIN = "no-pin"          # cannot decide; no pin to measure against


def _host_id() -> str:
    return (os.environ.get("ORION_HOST_ID")
            or platform.node().split(".")[0].lower()
            or "unknown")


def _now(now: Optional[float] = None) -> float:
    return now if now is not None else time.time()


# ─────────────────────────────────────────────────────────
# Local identity bridge — read this host's own self from the existing
# layers. Kept behind a thin accessor so tests can run even if those
# modules are mid-refactor, and so the dependency direction is explicit:
# vessel depends on identity/federation, never the reverse.
# ─────────────────────────────────────────────────────────

def _local_identity() -> Optional[dict]:
    """This host's own {instance_id, fingerprint, pubkey_hex} from
    orion_identity + orion_federation. Returns None if either layer is
    unavailable (e.g. cryptography not installed) — the caller treats
    that as 'cannot prove self', which fails CLOSED toward orphan."""
    try:
        from orion_identity import instance_id
        from orion_federation import identity_summary
        summ = identity_summary()
        return {
            "instance_id": instance_id(),
            "fingerprint": summ["fingerprint"],
            "pubkey_hex": summ["pubkey_hex"],
        }
    except Exception as e:  # pragma: no cover - environment-dependent
        logger.debug("local identity unavailable: %s", e)
        return None


# ─────────────────────────────────────────────────────────
# (1) PIN — the trust anchor.
# ─────────────────────────────────────────────────────────

def read_pin() -> Optional[dict]:
    """Return the canonical pin, or None if this host has never pinned."""
    if not CANONICAL_PATH.exists():
        return None
    try:
        return json.loads(CANONICAL_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("canonical.json unreadable (%s)", e)
        return None


def is_pinned() -> bool:
    return read_pin() is not None


def _write_pin(record: dict) -> dict:
    IDENTITY_DIR.mkdir(parents=True, exist_ok=True)
    CANONICAL_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")
    try:
        os.chmod(CANONICAL_PATH, 0o600)
    except Exception:
        pass
    return record


def pin_canonical(instance_id: Optional[str] = None,
                  fingerprint: Optional[str] = None,
                  pubkey_hex: Optional[str] = None,
                  pinned_by: str = "install",
                  force: bool = False) -> dict:
    """Write the canonical pin. Idempotent for an identical pin.

    With no arguments, pins THIS host's own identity as canonical — the
    one-time act that anoints, e.g., COMMAND as the source of truth.
    With explicit values (typically from a verified whoami descriptor),
    pins a remote identity — what a secondary does during adopt().

    Refuses to silently overwrite a DIFFERENT existing pin unless
    force=True (which is logged as a re-anointing — a deliberate,
    rare, founder-level act).
    """
    if instance_id is None or fingerprint is None or pubkey_hex is None:
        local = _local_identity()
        if not local:
            raise RuntimeError(
                "cannot pin: local identity unavailable (is the federation "
                "key present / is 'cryptography' installed?)")
        instance_id = instance_id or local["instance_id"]
        fingerprint = fingerprint or local["fingerprint"]
        pubkey_hex = pubkey_hex or local["pubkey_hex"]

    # Defence: fingerprint must derive from the pubkey we're pinning.
    if not _fingerprint_matches_pubkey(fingerprint, pubkey_hex):
        raise ValueError("refusing to pin: fingerprint does not derive "
                         "from pubkey_hex")

    existing = read_pin()
    if existing and not force:
        same = (existing.get("instance_id") == instance_id
                and existing.get("fingerprint") == fingerprint
                and existing.get("pubkey_hex") == pubkey_hex)
        if same:
            return existing
        raise RuntimeError(
            "refusing to overwrite an existing DIFFERENT canonical pin "
            "without force=True — this would re-anoint the brain "
            f"(existing fp={existing.get('fingerprint','?')[:12]}, "
            f"new fp={fingerprint[:12]}). If this is intentional, "
            "pin with force=True.")

    record = {
        "instance_id": instance_id,
        "fingerprint": fingerprint,
        "pubkey_hex": pubkey_hex,
        "pinned_at": _now(),
        "pinned_by": pinned_by,
        "pinned_on_host": _host_id(),
        "protocol_version": PROTOCOL_VERSION,
    }
    if existing and force:
        logger.warning("RE-ANOINTING canonical brain: %s → %s (by %s)",
                       existing.get("fingerprint", "?")[:12],
                       fingerprint[:12], pinned_by)
    _write_pin(record)
    logger.info("canonical pin written: instance=%s fingerprint=%s by=%s",
                instance_id[:12], fingerprint[:12], pinned_by)
    return record


# ─────────────────────────────────────────────────────────
# (2) WHOAMI descriptor — the signed self-attestation an endpoint serves,
# and the verify-on-bind logic that measures it against the pin.
# ─────────────────────────────────────────────────────────

def _fingerprint_matches_pubkey(fingerprint: str, pubkey_hex: str) -> bool:
    """fingerprint must equal sha256(pubkey)[:32] — the SAME derivation
    orion_federation uses. A descriptor whose fingerprint doesn't derive
    from its own pubkey is forged on its face."""
    import hashlib
    try:
        expected = hashlib.sha256(bytes.fromhex(pubkey_hex)).hexdigest()[:32]
    except Exception:
        return False
    return expected == fingerprint


def _descriptor_body(desc: dict) -> bytes:
    """Canonical signed body = descriptor minus the signature field,
    json-sorted. MUST match between build and verify (same convention
    as orion_federation.verify_offer)."""
    body = {k: v for k, v in desc.items() if k != "signature_hex"}
    return json.dumps(body, sort_keys=True).encode("utf-8")


def build_whoami_descriptor(now: Optional[float] = None) -> dict:
    """Build THIS host's signed whoami descriptor. The canonical brain
    serves this (over /vessel/whoami and/or brain.vessel.whoami) so
    binders can verify it. Signed with the federation Ed25519 key, so
    only the holder of the canonical private key can produce a valid one.

    Shape:
      {instance_id, fingerprint, pubkey_hex, host_id, ts,
       protocol_version, signature_hex}
    """
    local = _local_identity()
    if not local:
        raise RuntimeError("cannot build whoami: local identity unavailable")
    body = {
        "instance_id": local["instance_id"],
        "fingerprint": local["fingerprint"],
        "pubkey_hex": local["pubkey_hex"],
        "host_id": _host_id(),
        "ts": _now(now),
        "protocol_version": PROTOCOL_VERSION,
    }
    from orion_federation import sign_bytes
    body["signature_hex"] = sign_bytes(_descriptor_body(body)).hex()
    return body


def verify_descriptor_self_consistent(desc: dict) -> tuple[bool, str]:
    """Is this descriptor internally authentic — signed by the holder of
    the private key for its OWN advertised pubkey, with a fingerprint
    that derives from that pubkey? This proves the descriptor is a
    genuine self-attestation; it does NOT prove it's the canonical one
    (that's verify_against_pin's job)."""
    required = ("instance_id", "fingerprint", "pubkey_hex", "host_id",
                "ts", "signature_hex")
    for k in required:
        if k not in desc:
            return False, f"missing field: {k}"
    if not desc["signature_hex"]:
        return False, "unsigned descriptor"
    if not _fingerprint_matches_pubkey(desc["fingerprint"], desc["pubkey_hex"]):
        return False, "fingerprint does not derive from pubkey (forged)"
    try:
        from orion_federation import verify_signature
        sig = bytes.fromhex(desc["signature_hex"])
    except Exception:
        return False, "signature_hex not valid hex"
    if not verify_signature(desc["pubkey_hex"], _descriptor_body(desc), sig):
        return False, "signature verification failed"
    return True, "ok"


def verify_against_pin(desc: dict,
                       pin: Optional[dict] = None) -> tuple[bool, str]:
    """Verify-on-bind. A descriptor binds ONLY if it is self-consistent
    AND its instance_id, fingerprint, and pubkey all equal the pin.
    Returns (ok, reason)."""
    pin = pin if pin is not None else read_pin()
    if pin is None:
        return False, "no canonical pin on this host"
    ok, reason = verify_descriptor_self_consistent(desc)
    if not ok:
        return False, reason
    if desc["pubkey_hex"] != pin.get("pubkey_hex"):
        return False, "pubkey does not match canonical pin"
    if desc["fingerprint"] != pin.get("fingerprint"):
        return False, "fingerprint does not match canonical pin"
    if desc["instance_id"] != pin.get("instance_id"):
        return False, "instance_id does not match canonical pin"
    return True, "ok"


def classify_endpoint(desc: dict,
                      pin: Optional[dict] = None) -> str:
    """Decide what an endpoint's whoami descriptor IS, relative to the
    pin. The single call a transport makes before trusting an endpoint.

    Returns one of:
      BIND_MATCH   — verified canonical; bind/trust it.
      BIND_FORK    — cryptographically authentic but a DIFFERENT self;
                     refuse and report a fork.
      BIND_INVALID — malformed or bad signature; refuse.
      BIND_NO_PIN  — no pin to measure against; caller must adopt first.
    """
    pin = pin if pin is not None else read_pin()
    self_ok, _ = verify_descriptor_self_consistent(desc)
    if not self_ok:
        return BIND_INVALID
    if pin is None:
        return BIND_NO_PIN
    ok, _ = verify_against_pin(desc, pin)
    if ok:
        return BIND_MATCH
    # Self-consistent (a real, signed self) but not the pinned one → fork.
    return BIND_FORK


# ─────────────────────────────────────────────────────────
# (3) NO-FORK LAW — binding mode + write gate for THIS host.
# ─────────────────────────────────────────────────────────

def am_i_canonical(pin: Optional[dict] = None) -> bool:
    """True iff a pin exists and equals this host's own identity — i.e.
    this host IS the source of truth (the anointed brain, e.g. COMMAND)."""
    pin = pin if pin is not None else read_pin()
    if pin is None:
        return False
    local = _local_identity()
    if not local:
        return False
    return (local["instance_id"] == pin.get("instance_id")
            and local["fingerprint"] == pin.get("fingerprint")
            and local["pubkey_hex"] == pin.get("pubkey_hex"))


def binding_status(endpoint_desc: Optional[dict] = None) -> dict:
    """Compute this host's binding mode and whether writes are allowed.

    endpoint_desc: the whoami descriptor of the brain this host is about
    to use (fetched via fetch_whoami / the substrate). Pass it when the
    host is a secondary that must verify a remote canonical brain. Omit
    on the canonical host, or when no endpoint is reachable.

    Modes (the no-fork law in one table):
      no pin                                   → UNPINNED  (read-only)
      pin && this host is canonical            → CANONICAL (writes OK)
      pin && endpoint verifies to the pin      → BOUND     (writes OK)
      pin && (no endpoint OR endpoint != pin)  → ORPHAN    (read-only+queue)
    """
    pin = read_pin()
    result = {
        "host_id": _host_id(),
        "pinned": pin is not None,
        "mode": MODE_UNPINNED,
        "writes_allowed": False,
        "reason": "",
        "pin_fingerprint": (pin or {}).get("fingerprint"),
        "endpoint": None,
    }
    if pin is None:
        result["reason"] = ("no canonical pin on this host — read-only "
                            "until you adopt the canonical brain or anoint "
                            "this host with pin_canonical()")
        return result

    if am_i_canonical(pin):
        result["mode"] = MODE_CANONICAL
        result["writes_allowed"] = True
        result["reason"] = "this host is the canonical brain"
        return result

    if endpoint_desc is not None:
        verdict = classify_endpoint(endpoint_desc, pin)
        result["endpoint"] = verdict
        if verdict == BIND_MATCH:
            result["mode"] = MODE_BOUND
            result["writes_allowed"] = True
            result["reason"] = "verified canonical endpoint; bound"
            return result
        if verdict == BIND_FORK:
            result["mode"] = MODE_ORPHAN
            result["reason"] = ("endpoint is a DIFFERENT authentic self "
                                "(FORK) — refusing to bind; read-only+queue")
            report_fork(endpoint_desc, context="binding_status")
            return result
        # INVALID or NO_PIN-shaped → orphan, conservative.
        result["mode"] = MODE_ORPHAN
        result["reason"] = f"endpoint not trustworthy ({verdict}); read-only+queue"
        return result

    # Pin exists, not canonical, no endpoint reachable.
    result["mode"] = MODE_ORPHAN
    result["reason"] = ("canonical brain unreachable and this host is not "
                        "canonical — read-only+queue (will not mint a new self)")
    return result


def writes_allowed(endpoint_desc: Optional[dict] = None) -> bool:
    """Convenience write-gate the brain-service / memorize path consults
    before accepting an authoritative write on this host."""
    return binding_status(endpoint_desc)["writes_allowed"]


# ─────────────────────────────────────────────────────────
# Adoption — how a secondary host pins the canonical identity. Requires
# an explicit confirm: per identity-continuity.md §2, first arrival on a
# new body is a SOFT check the user confirms, never silent.
# ─────────────────────────────────────────────────────────

def adopt(desc: dict, confirm: bool = False, force: bool = False) -> dict:
    """Adopt a verified canonical descriptor as this host's pin.

    The descriptor must be self-consistent (signed by the holder of its
    own private key). confirm=True is mandatory — adoption is a trust
    decision the human makes after comparing the 5-word safety number
    out-of-band, exactly like federation peering.
    """
    if not confirm:
        raise PermissionError(
            "adopt requires confirm=True — verify the safety number "
            "out-of-band against the canonical brain first")
    ok, reason = verify_descriptor_self_consistent(desc)
    if not ok:
        raise ValueError(f"refusing to adopt unverifiable descriptor: {reason}")
    return pin_canonical(
        instance_id=desc["instance_id"],
        fingerprint=desc["fingerprint"],
        pubkey_hex=desc["pubkey_hex"],
        pinned_by=f"adopt-from:{desc.get('host_id', '?')}",
        force=force,
    )


# ─────────────────────────────────────────────────────────
# Fork reporting — append-only ledger + best-effort substrate event.
# ─────────────────────────────────────────────────────────

def report_fork(desc: dict, context: str = "") -> dict:
    """Record a detected fork. Never raises. Becomes a recallable memory
    and, when the substrate is up, a brain.vessel.fork event the
    executive can act on."""
    pin = read_pin() or {}
    row = {
        "ts": _now(),
        "observed_on_host": _host_id(),
        "context": context,
        "canonical_fingerprint": pin.get("fingerprint"),
        "canonical_instance_id": pin.get("instance_id"),
        "fork_fingerprint": desc.get("fingerprint"),
        "fork_instance_id": desc.get("instance_id"),
        "fork_host_id": desc.get("host_id"),
    }
    try:
        VESSEL_DIR.mkdir(parents=True, exist_ok=True)
        with FORK_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        logger.warning("fork log write failed: %s", e)
    logger.error("FORK DETECTED (%s): canonical fp=%s but endpoint fp=%s "
                 "(host=%s) — refused to bind",
                 context,
                 (pin.get("fingerprint") or "?")[:12],
                 (desc.get("fingerprint") or "?")[:12],
                 desc.get("host_id"))
    try:
        from orion_substrate import publish
        publish("brain.vessel.fork", row)
    except Exception:
        pass
    return row


def list_forks(limit: int = 50) -> list:
    if not FORK_LOG.exists():
        return []
    try:
        lines = FORK_LOG.read_text(encoding="utf-8").splitlines()
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
# Write queue — the orphan's holding pen. A read-only host stages its
# writes here instead of dropping them or applying them to a divergent
# local self; they replay to the canonical brain once binding succeeds.
# ─────────────────────────────────────────────────────────

def queue_write(op: dict) -> dict:
    """Stage one write op for later replay. op is opaque to the vessel —
    typically {tool, arguments} for an orion_memorize-shaped call."""
    row = {"ts": _now(), "host_id": _host_id(), "op": op}
    VESSEL_DIR.mkdir(parents=True, exist_ok=True)
    with WRITE_QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def pending_writes(limit: int = 1000) -> list:
    if not WRITE_QUEUE_PATH.exists():
        return []
    try:
        lines = WRITE_QUEUE_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def flush_queue(sender: Callable[[dict], bool]) -> dict:
    """Replay queued writes through `sender(op) -> bool`. Each op for
    which sender returns True is considered delivered. On full success
    the queue file is cleared; on partial success the undelivered ops
    are rewritten so the next flush retries only those.

    sender is injected (not hardcoded to the brain HTTP client) so this
    is testable without a network and so the caller controls routing.
    """
    rows = pending_writes(limit=10**9)
    if not rows:
        return {"flushed": 0, "remaining": 0}
    remaining = []
    flushed = 0
    for row in rows:
        op = row.get("op", {})
        ok = False
        try:
            ok = bool(sender(op))
        except Exception as e:
            logger.warning("flush sender raised on op: %s", e)
            ok = False
        if ok:
            flushed += 1
        else:
            remaining.append(row)
    # Rewrite the queue with only the undelivered rows.
    try:
        if remaining:
            with WRITE_QUEUE_PATH.open("w", encoding="utf-8") as f:
                for row in remaining:
                    f.write(json.dumps(row) + "\n")
        else:
            if WRITE_QUEUE_PATH.exists():
                WRITE_QUEUE_PATH.unlink()
    except Exception as e:
        logger.warning("flush queue rewrite failed: %s", e)
    logger.info("flushed %d queued write(s); %d remaining", flushed, len(remaining))
    return {"flushed": flushed, "remaining": len(remaining)}


# ─────────────────────────────────────────────────────────
# Optional HTTP helper — fetch a remote brain's whoami. Used by the
# deploy-step wiring; kept import-light (urllib only) so the pure core
# above carries no network dependency.
# ─────────────────────────────────────────────────────────

def fetch_whoami(base_url: str, timeout: float = 1.5) -> Optional[dict]:
    """GET {base_url}/vessel/whoami and return the descriptor, or None.
    Never raises — a missing/unreachable endpoint is a None, which the
    binding logic treats as 'no endpoint' (→ orphan, fail-closed)."""
    import urllib.request
    url = base_url.rstrip("/") + "/vessel/whoami"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status != 200:
                return None
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# CLI — the operator surface used during the cross-device health check
# and install/adopt flow.
# ─────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Orion Vessel — canonical identity keystone")
    sub = ap.add_subparsers(dest="cmd")

    p_pin = sub.add_parser("pin", help="anoint THIS host as canonical")
    p_pin.add_argument("--force", action="store_true",
                       help="re-anoint over an existing different pin")
    p_pin.add_argument("--by", default="cli", help="pinned_by label")

    sub.add_parser("status", help="show this host's binding mode + write gate")
    sub.add_parser("whoami", help="print this host's signed whoami descriptor")

    p_ver = sub.add_parser("verify", help="classify an endpoint against the pin")
    p_ver.add_argument("target", help="http(s)://host:port  OR  path to a whoami json file")

    p_ado = sub.add_parser("adopt", help="adopt a canonical descriptor (from url or file)")
    p_ado.add_argument("target", help="http(s)://host:port  OR  path to a whoami json file")
    p_ado.add_argument("--confirm", action="store_true",
                       help="required — confirms you checked the safety number")
    p_ado.add_argument("--force", action="store_true")

    sub.add_parser("forks", help="list detected forks")
    sub.add_parser("queue", help="list queued (unflushed) writes")

    args = ap.parse_args()

    def _load_descriptor(target: str) -> Optional[dict]:
        if target.startswith("http://") or target.startswith("https://"):
            return fetch_whoami(target)
        p = Path(target)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    if args.cmd == "pin":
        try:
            rec = pin_canonical(pinned_by=args.by, force=args.force)
        except Exception as e:
            print(f"pin failed: {e}")
            return 1
        print(json.dumps({k: v for k, v in rec.items()
                          if k != "pubkey_hex"}, indent=2))
        print(f"pubkey_hex: {rec['pubkey_hex'][:24]}…")
        return 0

    if args.cmd == "status":
        print(json.dumps(binding_status(), indent=2))
        return 0

    if args.cmd == "whoami":
        try:
            print(json.dumps(build_whoami_descriptor(), indent=2))
        except Exception as e:
            print(f"whoami failed: {e}")
            return 1
        return 0

    if args.cmd == "verify":
        desc = _load_descriptor(args.target)
        if not desc:
            print(f"could not load a whoami descriptor from {args.target}")
            return 1
        verdict = classify_endpoint(desc)
        ok, reason = (verify_against_pin(desc) if is_pinned()
                      else (False, "no pin"))
        print(json.dumps({
            "verdict": verdict,
            "bind_ok": ok,
            "reason": reason,
            "endpoint_fingerprint": desc.get("fingerprint"),
            "endpoint_host": desc.get("host_id"),
        }, indent=2))
        return 0 if verdict == BIND_MATCH else 2

    if args.cmd == "adopt":
        desc = _load_descriptor(args.target)
        if not desc:
            print(f"could not load a whoami descriptor from {args.target}")
            return 1
        try:
            rec = adopt(desc, confirm=args.confirm, force=args.force)
        except Exception as e:
            print(f"adopt failed: {e}")
            return 1
        print(f"adopted canonical brain fingerprint={rec['fingerprint'][:12]} "
              f"(pinned_by={rec['pinned_by']})")
        return 0

    if args.cmd == "forks":
        for r in list_forks():
            print(json.dumps(r))
        return 0

    if args.cmd == "queue":
        for r in pending_writes():
            print(json.dumps(r))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())


# ─────────────────────────────────────────────────────────
# DEPLOY-STEP WIRING (NOT YET ACTIVE — founder review gate per resume §5.1)
# ─────────────────────────────────────────────────────────
#
# These are the exact two call sites to gate once this module is approved.
# Documented here AND in docs/architecture/vessel-canonical-identity.md so
# the review has the diff in front of it. Nothing below runs today.
#
# SEAM A — orion_substrate._discover_substrate_url() (line ~41):
#   Today it returns the first IP answering TCP :4222 with NO identity
#   check. Wrap the chosen URL: derive the brain HTTP base for that host,
#   fetch_whoami(), classify_endpoint(). Only return the nats:// URL if
#   verdict == BIND_MATCH (or this host am_i_canonical()). On BIND_FORK
#   report_fork() and fall through to the next candidate; if none verify,
#   stay local in orphan mode rather than binding a stranger.
#
# SEAM B — orion_mcp_server._brain_http_auto_start() (line ~90) +
#   _BRAIN_HTTP_URL default 127.0.0.1:5556:
#   Before auto-spawning a local brain, consult binding_status(): if this
#   host is not canonical and has a pin, do NOT mint a local authoritative
#   brain — bind to the canonical endpoint (or run read-only+queue). Have
#   _ensure_instance / _ensure_identity ADOPT the pin on a fresh host
#   instead of minting a new instance_id (the actual fork origin).
#
# SERVE — orion_brain_service.do_GET (line ~221):
#   Add an unauthenticated `GET /vessel/whoami` mirroring /health, body =
#   build_whoami_descriptor(). Unauth is fine: the descriptor is signed
#   and strictly public (no private key, same posture as /health).
