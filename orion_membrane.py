"""orion_membrane.py — privacy enforcement at the substrate boundary.

Founder strategic clarification 2026-05-14: privacy enforced in code at
the substrate layer, blocks 'private' tagged nodes from leaving host.
Hard prereq for any LoRa mass-broadcast or Federation peering.

Per docs/architecture/membrane-research.md (3,673 words, filed
2026-05-16). Three-layer defense-in-depth:

  Layer 0 — classify(content, tags) at write time. GraphMemory.store()
            and the MCP memorize handler call this so every new node
            arrives in the graph with a visibility:* tag attached.
            NER + regex find third-party PII and obvious secrets; the
            default is conservative (visibility:local on uncertainty)
            because false positives are user-promotable in one keystroke
            and false negatives are the breach.

  Layer 1 — egress_decision(subject, payload, dest_class) inside
            orion_substrate.publish. The chokepoint: every NATS publish
            consults Membrane before it goes out. O(1) on tag-set
            inspection; no regex per call, no I/O. Returns
            'allow' | 'redact' | 'block'.

  Layer 2 — filter_manifest(entries) inside orion_gossip._publish_
            heartbeat and ._publish_delta. The highest-risk subject
            (`mesh.<host>.*`) goes through a second filter that drops
            private entries before serialization — belt-over-suspenders
            so a bug in Layer 1 still can't leak the manifest.

Audit log at ~/.orion/membrane/audit.jsonl. Every block/redact decision
is recorded with subject, node_id (if available), reason, and ts so
"what did Membrane decide today?" stays grep-able. Without that, the
classifier becomes a hidden judge and the "Orion is for you, not on
you" thesis dies the day the user can't see what was withheld.

Visibility lattice (memo §3):

  visibility:local       → never leaves the host process
  visibility:host        → this host's mesh members only (localhost)
  visibility:mesh        → trusted devices on this user's mesh
  visibility:federation  → this user's federated peers only
  visibility:public      → anything goes, including LoRa broadcast

Default for hand-memorized: visibility:mesh.
Default when classifier finds third-party PII / secrets / 'private'
keywords: visibility:local.

This v1 is software-permission privacy, not cryptographic privacy
(memo §8 critique). Raises the floor for accidental leakage — the
dominant threat for a single-user personal AI — and shrinks the
compelled-disclosure blast radius. The endgame is content-addressable
storage with per-node encryption keys; Membrane v1 ships now and
buys time to build the cryptographic story. Treat as v1, not endgame.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("orion.membrane")

# ─────────────────────────────────────────────────────────
# Paths & layout
# ─────────────────────────────────────────────────────────

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))
MEMBRANE_DIR = ORION_HOME / "membrane"
POLICY_PATH = MEMBRANE_DIR / "policy.json"
AUDIT_PATH = MEMBRANE_DIR / "audit.jsonl"

# ─────────────────────────────────────────────────────────
# Visibility lattice. Ordered most-restrictive to most-permissive.
# An egress decision picks the strictest tag present on the payload
# and asks: does the destination class satisfy it?
# ─────────────────────────────────────────────────────────

V_LOCAL = "visibility:local"
V_HOST = "visibility:host"
V_MESH = "visibility:mesh"
V_FEDERATION = "visibility:federation"
V_PUBLIC = "visibility:public"

# Ordinal rank — lower number = more restrictive ceiling.
_VISIBILITY_RANK = {
    V_LOCAL: 0,
    V_HOST: 1,
    V_MESH: 2,
    V_FEDERATION: 3,
    V_PUBLIC: 4,
}

# Destination classes a publish call can declare. The substrate hook
# resolves the subject to a class; gossip uses 'mesh' explicitly.
DEST_LOCALHOST = "localhost"   # in-process / loopback NATS subscribers
DEST_HOST_MESH = "host"        # localhost NATS subjects observers can read
DEST_MESH = "mesh"             # CRDT gossip to trusted mesh devices
DEST_FEDERATION = "federation" # peered third-party Orions
DEST_PUBLIC = "public"         # LoRa broadcast, public radio, etc.

# Same ordinal rank as visibility — destination must be ≤ ceiling.
_DEST_RANK = {
    DEST_LOCALHOST: 0,
    DEST_HOST_MESH: 1,
    DEST_MESH: 2,
    DEST_FEDERATION: 3,
    DEST_PUBLIC: 4,
}

# ─────────────────────────────────────────────────────────
# Classifier. Cheap, conservative, additive. NER + regex hits flip
# the default down to visibility:local; explicit user override (a
# visibility:* tag already on the input) wins.
# ─────────────────────────────────────────────────────────

# Patterns that, when matched against memorize content, force the node
# down to visibility:local. Conservative on purpose — user can promote
# via dashboard / `orion_team`-style override in one keystroke. The
# breach is the false negative, not the false positive.
_SECRET_PATTERNS = [
    re.compile(r"\b(api[_\-]?key|token|secret|password|passwd|passphrase|"
               r"bearer|cred(ential)?s?|private[_\-]?key)\b", re.I),
    re.compile(r"\b(sk|pk|ghp|gho|github_pat|xox[abp])[_-][A-Za-z0-9_\-]{20,}"),
    # Email — third-party-mention or self-disclosure either way
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # Phone (US-ish + international)
    re.compile(r"\b\+?\d{1,3}[\s.\-]?\(?\d{2,4}\)?[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}\b"),
    # Street address (loose — number + street word)
    re.compile(r"\b\d{1,5}\s+\w+\s+(street|st|ave|avenue|road|rd|blvd|"
               r"lane|ln|drive|dr|court|ct|way|place|pl)\b", re.I),
    # Card-shaped (Luhn not validated — we just refuse to publish things
    # that look card-shaped; false positives are cheap)
    re.compile(r"\b(?:\d[ \-]?){13,19}\b"),
    # SSN-shaped
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # Explicit user signals
    re.compile(r"\b(do not share|don'?t share|keep this private|"
               r"between us|confidential|nda|under nda|hipaa|phi)\b", re.I),
]

# Third-party first-name regex is intentionally narrow — proper-noun
# detection without NER is a recipe for false positives on every word
# that happens to be capitalized. v1 uses an explicit list-prompt
# instead. Future: hook spaCy NER if installed, falling back to this.
_THIRD_PARTY_HINT = re.compile(
    r"\b(my (mom|mother|dad|father|wife|husband|partner|sister|brother|"
    r"daughter|son|friend|neighbor|boss|colleague|coworker|therapist|"
    r"doctor|lawyer))\b",
    re.I,
)


def _has_explicit_visibility(tags: Iterable[str]) -> Optional[str]:
    """Return the user-declared visibility tag if any, else None."""
    for t in tags or []:
        if isinstance(t, str) and t.startswith("visibility:"):
            return t
    return None


def classify(content: str, tags: Optional[Iterable[str]] = None,
             default: str = V_MESH) -> list[str]:
    """Augment tags with a visibility:* level based on content inspection.

    If the caller already specified visibility:*, honor it (user override
    always wins). Otherwise: scan for PII / secret patterns / third-party
    references; drop to visibility:local on any hit. Else apply `default`
    (visibility:mesh for hand-memorized).

    Returns a new tag list (order preserved, single visibility:* tag
    guaranteed at most once). Caller writes the list into the node.
    """
    tags_list = list(tags or [])
    explicit = _has_explicit_visibility(tags_list)
    if explicit:
        return tags_list  # User knows what they're doing.

    # Conservative scan. Each hit independently flips to local.
    text = content or ""
    found_secret = any(p.search(text) for p in _SECRET_PATTERNS)
    found_third_party = bool(_THIRD_PARTY_HINT.search(text))
    visibility = V_LOCAL if (found_secret or found_third_party) else default

    tags_list.append(visibility)
    return tags_list


# ─────────────────────────────────────────────────────────
# Egress decision — Layer 1 hook into orion_substrate.publish.
# Hot path; O(1) on tag inspection only. NO regex, NO disk I/O.
# ─────────────────────────────────────────────────────────

# Subject → destination class. Catches the publishers that actually
# leak: anything mesh.* is gossip; channel.*.outbound exits the host
# via external networks; brain.* is local-only by convention. New
# transports add their own prefix.
_SUBJECT_DEST: list[tuple[str, str]] = [
    ("mesh.", DEST_MESH),
    ("brain.federation.", DEST_FEDERATION),
    ("transport.lora.", DEST_PUBLIC),     # Sensorium (future)
    ("transport.ble.", DEST_PUBLIC),
    ("transport.radio.", DEST_PUBLIC),
    ("channel.imessage.outbound", DEST_PUBLIC),
    ("channel.telegram.outbound", DEST_PUBLIC),
    ("channel.voice.outbound", DEST_PUBLIC),
    ("channel.email.outbound", DEST_PUBLIC),
    # Default: anything else (brain.*, orion.team.*, etc.) is localhost.
]


def subject_destination(subject: str) -> str:
    for prefix, dest in _SUBJECT_DEST:
        if subject.startswith(prefix):
            return dest
    return DEST_LOCALHOST


def _payload_visibility_ceiling(payload) -> Optional[str]:
    """Inspect a publish payload for the strictest visibility:* tag
    embedded in it. Returns None if no visibility tag found anywhere
    (caller defaults to permissive). Recognizes the shapes the existing
    publishers actually use — top-level `tags`, nested `entries[k].
    payload.tags`. Adding new shapes is a one-line addition here."""
    if not isinstance(payload, dict):
        return None

    candidates: list[Iterable] = []
    if "tags" in payload and payload["tags"]:
        candidates.append(payload["tags"])
    # gossip manifest entries — entries: { key: {payload: {tags: [...]}}}
    entries = payload.get("entries")
    if isinstance(entries, dict):
        for v in entries.values():
            inner = (v or {}).get("payload") or {}
            inner_tags = inner.get("tags")
            if inner_tags:
                candidates.append(inner_tags)
    # gossip manifest entries — entries: { key: {tags: [...]}}
            elif (v or {}).get("tags"):
                candidates.append(v["tags"])

    strictest_rank = None
    strictest_tag: Optional[str] = None
    for tags in candidates:
        for t in tags or []:
            if isinstance(t, str) and t.startswith("visibility:"):
                rank = _VISIBILITY_RANK.get(t)
                if rank is None:
                    continue
                if strictest_rank is None or rank < strictest_rank:
                    strictest_rank = rank
                    strictest_tag = t
    return strictest_tag


def egress_decision(subject: str, payload,
                    dest_class: Optional[str] = None) -> str:
    """Return 'allow' | 'redact' | 'block' for a pending publish.

    'allow'  → caller proceeds with the original payload
    'redact' → caller publishes a redacted envelope (cover-traffic so
               subscribers can't infer the block from silence — memo §4d)
    'block'  → caller drops the publish entirely (only when even the
               envelope would leak useful structure)
    """
    dest = dest_class or subject_destination(subject)
    dest_rank = _DEST_RANK.get(dest, _DEST_RANK[DEST_PUBLIC])

    ceiling_tag = _payload_visibility_ceiling(payload)
    if ceiling_tag is None:
        # No visibility metadata on the payload. Permissive — but the
        # write-time classifier (Layer 0) should have added one. If we
        # see no tag on a high-destination publish, log it as a
        # provenance gap so it can be fixed upstream.
        if dest_rank >= _DEST_RANK[DEST_FEDERATION]:
            _log("provenance_gap", subject, dest, None,
                 "publish without visibility tag at federation/public dest")
        return "allow"

    ceiling_rank = _VISIBILITY_RANK[ceiling_tag]
    if dest_rank <= ceiling_rank:
        return "allow"

    # Destination exceeds ceiling. Choose redact vs block:
    # local-tagged content is too sensitive even to publish a redacted
    # envelope for (the *fact* of a write at a known time is itself a
    # leak — memo §4d). Anything more permissive than local emits a
    # cover envelope.
    decision = "block" if ceiling_tag == V_LOCAL else "redact"
    _log(decision, subject, dest, ceiling_tag, "visibility ceiling exceeded")
    return decision


# ─────────────────────────────────────────────────────────
# Manifest filter — Layer 2 hook into orion_gossip.
# Drops private entries from the snapshot before serialization.
# ─────────────────────────────────────────────────────────

def filter_manifest(entries: dict, dest_class: str = DEST_MESH) -> dict:
    """Return a copy of a gossip-manifest dict with any entry whose
    visibility ceiling exceeds dest_class removed.

    Manifest shape (from orion_gossip._manifest.snapshot()):
        { "<node_id>": {"hlc": [...], "tags": [...], "content_hash": ...} }
    or nested under .payload, depending on the version. Tries both.
    """
    if not isinstance(entries, dict):
        return entries
    dest_rank = _DEST_RANK.get(dest_class, _DEST_RANK[DEST_PUBLIC])
    out = {}
    dropped = 0
    for k, v in entries.items():
        tags = []
        if isinstance(v, dict):
            tags = v.get("tags") or (v.get("payload") or {}).get("tags") or []
        ceiling_rank = _VISIBILITY_RANK[V_PUBLIC]  # default permissive
        ceiling_tag = None
        for t in tags:
            if isinstance(t, str) and t.startswith("visibility:"):
                r = _VISIBILITY_RANK.get(t)
                if r is not None and r < ceiling_rank:
                    ceiling_rank = r
                    ceiling_tag = t
        if dest_rank > ceiling_rank:
            dropped += 1
            _log("manifest_drop", f"mesh.*.manifest", dest_class,
                 ceiling_tag, f"manifest entry {k} above {dest_class}")
            continue
        out[k] = v
    if dropped:
        logger.info("membrane filtered %d/%d manifest entries for dest=%s",
                    dropped, len(entries), dest_class)
    return out


# ─────────────────────────────────────────────────────────
# Policy + audit
# ─────────────────────────────────────────────────────────

_policy_lock = threading.Lock()
_policy_cache: Optional[dict] = None


def load_policy(force: bool = False) -> dict:
    """Read the user-editable policy file. Defaults shipped in repo;
    overrides survive upgrades. Cached after first read."""
    global _policy_cache
    with _policy_lock:
        if _policy_cache is not None and not force:
            return _policy_cache
        try:
            if POLICY_PATH.exists():
                _policy_cache = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            else:
                _policy_cache = {}
        except Exception as e:
            logger.warning("policy load failed (%s); using empty policy", e)
            _policy_cache = {}
        return _policy_cache


_audit_lock = threading.Lock()


def _log(decision: str, subject: str, dest: str,
         visibility_tag: Optional[str], reason: str) -> None:
    """Append an audit row. Best-effort — never raises into the publish
    hot path. Dir is created lazily so import is side-effect-free."""
    try:
        with _audit_lock:
            MEMBRANE_DIR.mkdir(parents=True, exist_ok=True)
            row = {
                "ts": time.time(),
                "decision": decision,
                "subject": subject,
                "dest": dest,
                "visibility": visibility_tag,
                "reason": reason,
            }
            with AUDIT_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    except Exception:
        # Audit failure must not become a publish failure. Failing-loud
        # at the audit layer is worse than failing-loud at the publish
        # layer — it tries to block the original write.
        pass


def recent_decisions(limit: int = 50) -> list[dict]:
    """Return the most recent audit rows. Used by the MCP audit tool
    and by the dashboard 'what did Membrane decide today?' view."""
    if not AUDIT_PATH.exists():
        return []
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()
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
# CLI for diagnostics
# ─────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Orion Membrane diagnostics")
    sub = ap.add_subparsers(dest="cmd")
    p_cls = sub.add_parser("classify", help="classify a string of content")
    p_cls.add_argument("content")
    p_egress = sub.add_parser("egress", help="test egress decision")
    p_egress.add_argument("subject")
    p_egress.add_argument("--tags", default="",
                          help="comma-separated tags on the payload")
    sub.add_parser("audit", help="show recent audit decisions")
    sub.add_parser("policy", help="show loaded policy")

    args = ap.parse_args()
    if args.cmd == "classify":
        tags = classify(args.content)
        print(json.dumps(tags))
        return 0
    if args.cmd == "egress":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        payload = {"tags": tags}
        d = egress_decision(args.subject, payload)
        print(f"decision={d} subject={args.subject} "
              f"dest={subject_destination(args.subject)} tags={tags}")
        return 0
    if args.cmd == "audit":
        for r in recent_decisions(50):
            print(json.dumps(r))
        return 0
    if args.cmd == "policy":
        print(json.dumps(load_policy(), indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
