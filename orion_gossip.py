"""orion_gossip.py — mesh state propagation below the brain surface.

The 2026 published answer for multi-host LLM agent state is gossip
+ CRDTs (arXiv 2512.03285, 2604.19540). Eventually consistent,
no central coordinator, partition-tolerant by design. This file
implements the FIRST LAYER of that pattern for Orion's mesh —
each host advertises what it knows about brain state, and other
hosts gossip those advertisements together into a coherent view.

WHAT THIS LAYER DOES (and what it doesn't, yet)
================================================

Does:
  - Each host maintains an HLC-versioned manifest of "nodes I know
    about, when each was last written/recalled here, who wrote it"
  - Periodic publish of the manifest to mesh.<host>.state
  - Subscribe to other hosts' manifests; merge into local view
  - LWW (Last-Write-Wins by HLC) on per-node metadata conflicts
  - Expose query API: "is node X stale on this host vs. the mesh?"
  - Signals divergence so the executive can deliberate on conflicts

Doesn't (deferred to next-round):
  - Full CRDT G-Set per recall event (the per-edge merge from
    project_orion-plexus-architecture.md Layer 2c) — needs the
    edge-level Hebbian state to be CRDT-shaped first
  - Automatic content-level merge of conflicting node mutations —
    flagged for executive review instead
  - Mesh-wide rebalancing (move nodes to where they're hot)

This first layer is the SUBSTRATE for those upgrades. Per the
founder's autonomy rule (feedback_design-for-autonomy-not-specifics):
keep this layer general — it knows nothing about "brain" specifics;
it's a metadata-CRDT for any per-key timestamp+host record. Could
later carry channel state, identity state, plasticity state — same
machinery.

ARCHITECTURE
============

  Each host has a HOST_ID (defaults to platform.node()).
  Each host maintains:
    local_clock: HLC (physical_ms, logical_counter, host_id)
    manifest: Dict[node_id, ManifestEntry]
                    where ManifestEntry = {hlc, host, op_type,
                                           content_hash, summary}

  Substrate subjects:
    mesh.<host>.heartbeat   — full manifest snapshot, every 60s
    mesh.<host>.delta       — diff since last publish, more frequent
    mesh.conflict           — when two hosts diverge on the same node

  On every brain.memory.stored or brain.memory.recalled the local
  gossip daemon updates its manifest and publishes a delta.

  On every received heartbeat or delta from another host, merge:
    if remote_hlc > local_hlc for same node_id → adopt remote
    if remote_hlc < local_hlc → ignore (we're newer)
    if HLCs are concurrent (rare given clock-bound) → publish
       mesh.conflict for executive deliberation

PARTITION TOLERANCE
===================

A host that's offline accumulates writes locally. When it reconnects,
it gossips its full manifest at the next heartbeat. Other hosts merge
its updates by HLC. No coordinator, no quorum, no leader election.
This is exactly what the founder needs for the USB-portable brain
that travels and reconciles when it returns home.

HONESTY ABOUT SCALE
===================

At 78 nodes / 5 hosts / sub-Hz write rate, full-manifest heartbeats
every 60s are trivial (~2KB). Deltas are smaller. As the brain grows
to 10⁴ nodes, switch to compact manifests (just node_id + hlc) and
fetch full content on demand. The wire format is forward-compatible.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import signal
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("orion.gossip")

HOST_ID = os.environ.get("ORION_HOST_ID", platform.node().split(".")[0].lower() or "unknown")
GOSSIP_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_GOSSIP_DIR", "~/.orion/mesh")
))
HEARTBEAT_INTERVAL_SEC = float(os.environ.get("ORION_GOSSIP_HEARTBEAT_SEC", "60"))
DELTA_INTERVAL_SEC = float(os.environ.get("ORION_GOSSIP_DELTA_SEC", "10"))


# ─────────────────────────────────────────────────────────
# Hybrid Logical Clock — Kulkarni 2014
# (https://cse.buffalo.edu/tech-reports/2014-04.pdf)
# Tolerates clock skew + gives total order.
# ─────────────────────────────────────────────────────────

class HLC:
    """Per-host monotonic clock, robust to wall-clock skew."""
    __slots__ = ("phys", "logical", "host")

    def __init__(self, phys: int, logical: int, host: str):
        self.phys = int(phys)
        self.logical = int(logical)
        self.host = str(host)

    @classmethod
    def now(cls, host: str, last: "HLC | None" = None) -> "HLC":
        wall = int(time.time() * 1000)
        if last is None:
            return cls(wall, 0, host)
        if wall > last.phys:
            return cls(wall, 0, host)
        # Clock didn't advance (or went backward) — bump logical
        return cls(last.phys, last.logical + 1, host)

    @classmethod
    def update(cls, local: "HLC", remote: "HLC", host: str) -> "HLC":
        wall = int(time.time() * 1000)
        max_phys = max(wall, local.phys, remote.phys)
        if max_phys == wall and max_phys > local.phys and max_phys > remote.phys:
            return cls(wall, 0, host)
        if max_phys == local.phys == remote.phys:
            return cls(max_phys, max(local.logical, remote.logical) + 1, host)
        if max_phys == local.phys:
            return cls(max_phys, local.logical + 1, host)
        if max_phys == remote.phys:
            return cls(max_phys, remote.logical + 1, host)
        return cls(wall, 0, host)

    def gt(self, other: "HLC") -> bool:
        return (self.phys, self.logical, self.host) > (other.phys, other.logical, other.host)

    def to_tuple(self) -> tuple:
        return (self.phys, self.logical, self.host)

    def to_dict(self) -> dict:
        return {"phys": self.phys, "logical": self.logical, "host": self.host}

    @classmethod
    def from_dict(cls, d: dict) -> "HLC":
        return cls(d["phys"], d["logical"], d["host"])


# ─────────────────────────────────────────────────────────
# LWW Map — last-write-wins per key, HLC-ordered
# Generic CvRDT primitive; the brain manifest is one instance.
# Could later host channel-state, identity-state, plasticity-state.
# ─────────────────────────────────────────────────────────

class LWWMap:
    """Last-write-wins map keyed by string. Each entry has HLC + payload."""

    def __init__(self):
        self._lock = threading.Lock()
        self.entries: dict[str, dict] = {}  # key -> {hlc: dict, payload: dict}
        self.local_clock: HLC = HLC.now(HOST_ID)

    def put(self, key: str, payload: dict) -> dict:
        with self._lock:
            self.local_clock = HLC.now(HOST_ID, self.local_clock)
            entry = {"hlc": self.local_clock.to_dict(), "payload": payload}
            self.entries[str(key)] = entry
            return entry

    def merge(self, remote_entries: dict[str, dict]) -> tuple[int, int, list[str]]:
        """Merge remote entries via LWW.
        Returns (n_adopted, n_ignored, conflict_keys)."""
        adopted = 0
        ignored = 0
        conflicts: list[str] = []
        with self._lock:
            for k, rem in remote_entries.items():
                rem_hlc = HLC.from_dict(rem["hlc"])
                cur = self.entries.get(k)
                if cur is None:
                    self.entries[k] = rem
                    adopted += 1
                    self.local_clock = HLC.update(self.local_clock, rem_hlc, HOST_ID)
                    continue
                cur_hlc = HLC.from_dict(cur["hlc"])
                if rem_hlc.gt(cur_hlc):
                    self.entries[k] = rem
                    adopted += 1
                    self.local_clock = HLC.update(self.local_clock, rem_hlc, HOST_ID)
                elif cur_hlc.gt(rem_hlc):
                    ignored += 1
                else:
                    # Same HLC tuple — same write or genuine concurrent
                    # write that happens to share clock. Compare content
                    # hash; if different, that's a real divergence
                    cur_hash = (cur.get("payload") or {}).get("content_hash")
                    rem_hash = (rem.get("payload") or {}).get("content_hash")
                    if cur_hash != rem_hash:
                        conflicts.append(k)
                    else:
                        ignored += 1
        return adopted, ignored, conflicts

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.entries)


# ─────────────────────────────────────────────────────────
# Manifest tracker — what THIS host knows about brain state
# ─────────────────────────────────────────────────────────

_manifest = LWWMap()
_dirty_keys: set = set()
_dirty_lock = threading.Lock()
_stop = threading.Event()


def _content_hash(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:12]


def _on_memory_stored(subject: str, payload: dict) -> None:
    """A new node was written to the brain on this host."""
    nid = str(payload.get("node_id"))
    if not nid:
        return
    entry = {
        "host": HOST_ID,
        "op_type": "store",
        "node_type": payload.get("type", "fact"),
        "tags": payload.get("tags", []),
        "content_hash": _content_hash(json.dumps(payload, sort_keys=True, default=str)),
        "ts": float(payload.get("ts", time.time())),
    }
    _manifest.put(nid, entry)
    with _dirty_lock:
        _dirty_keys.add(nid)


def _on_memory_recalled(subject: str, payload: dict) -> None:
    """Recall events also update the manifest (last_recalled per node)."""
    ids = payload.get("node_ids") or []
    now = time.time()
    for nid in ids:
        nid_s = str(nid)
        entry = {
            "host": HOST_ID,
            "op_type": "recall",
            "ts": now,
            "content_hash": "",
        }
        # Recall doesn't replace store entries — preserve content_hash
        existing = _manifest.entries.get(nid_s)
        if existing:
            entry["content_hash"] = (existing.get("payload") or {}).get("content_hash", "")
            entry["node_type"] = (existing.get("payload") or {}).get("node_type")
            entry["tags"] = (existing.get("payload") or {}).get("tags", [])
        _manifest.put(nid_s, entry)
        with _dirty_lock:
            _dirty_keys.add(nid_s)


def _on_remote_heartbeat(subject: str, payload: dict) -> None:
    """Another host published its full manifest. Merge it."""
    parts = subject.split(".")
    if len(parts) < 3:
        return
    remote_host = parts[1]
    if remote_host == HOST_ID:
        return
    entries = payload.get("entries") or {}
    if not isinstance(entries, dict):
        return
    adopted, ignored, conflicts = _manifest.merge(entries)
    if adopted or conflicts:
        logger.info(
            "merged %s: adopted=%d ignored=%d conflicts=%d",
            remote_host, adopted, ignored, len(conflicts),
        )
    if conflicts:
        try:
            from orion_substrate import publish
            for k in conflicts[:10]:
                publish("mesh.conflict", {
                    "node_id": k,
                    "local_host": HOST_ID,
                    "remote_host": remote_host,
                    "ts": time.time(),
                })
        except Exception:
            pass


def _on_remote_delta(subject: str, payload: dict) -> None:
    """Smaller / more-frequent than heartbeat; same merge logic."""
    _on_remote_heartbeat(subject, payload)


def _filtered_for_mesh(entries: dict) -> dict:
    """Apply Membrane Layer 2 to a manifest snapshot before it leaves
    the host. Belt-and-suspenders over the orion_substrate.publish hook
    (Layer 1) — even if a future bug let a private entry through the
    publish gate, the manifest filter still drops it. See
    docs/architecture/membrane-research.md §7. Membrane unavailable →
    fail-open with a warning; the substrate hook is the primary gate."""
    try:
        from orion_membrane import filter_manifest, DEST_MESH
        return filter_manifest(entries, dest_class=DEST_MESH)
    except Exception:
        return entries


def _publish_heartbeat() -> None:
    try:
        from orion_substrate import publish
        snap = _filtered_for_mesh(_manifest.snapshot())
        publish(f"mesh.{HOST_ID}.heartbeat", {
            "host": HOST_ID,
            "ts": time.time(),
            "entry_count": len(snap),
            "entries": snap,
        })
    except Exception as e:
        logger.warning("heartbeat publish failed: %s", e)


def _publish_delta() -> None:
    with _dirty_lock:
        if not _dirty_keys:
            return
        keys = list(_dirty_keys)
        _dirty_keys.clear()
    try:
        from orion_substrate import publish
        snap = _manifest.snapshot()
        delta = _filtered_for_mesh({k: snap[k] for k in keys if k in snap})
        publish(f"mesh.{HOST_ID}.delta", {
            "host": HOST_ID,
            "ts": time.time(),
            "entry_count": len(delta),
            "entries": delta,
        })
    except Exception as e:
        logger.warning("delta publish failed: %s", e)


def _heartbeat_loop() -> None:
    while not _stop.is_set():
        try:
            _publish_heartbeat()
        except Exception as e:
            logger.warning("heartbeat loop error: %s", e)
        # Persist snapshot to disk for offline-merge recovery
        try:
            GOSSIP_DIR.mkdir(parents=True, exist_ok=True)
            (GOSSIP_DIR / f"{HOST_ID}.snapshot.json").write_text(
                json.dumps(_manifest.snapshot(), default=str), encoding="utf-8",
            )
        except Exception:
            pass
        _stop.wait(HEARTBEAT_INTERVAL_SEC)


def _delta_loop() -> None:
    while not _stop.is_set():
        try:
            _publish_delta()
        except Exception as e:
            logger.warning("delta loop error: %s", e)
        _stop.wait(DELTA_INTERVAL_SEC)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    try:
        from orion_substrate import subscribe, get_substrate, memory_stored_subject, memory_recalled_subject
    except ImportError:
        logger.error("orion_substrate not importable")
        return 1

    sub = get_substrate()
    sub._connect_blocking()

    # Local brain events → manifest updates
    subscribe(memory_stored_subject(), _on_memory_stored)
    subscribe(memory_recalled_subject(), _on_memory_recalled)
    # Remote hosts' state → merge into local view
    subscribe("mesh.*.heartbeat", _on_remote_heartbeat)
    subscribe("mesh.*.delta", _on_remote_delta)

    # Recover prior snapshot (offline-merge support)
    snap_path = GOSSIP_DIR / f"{HOST_ID}.snapshot.json"
    if snap_path.exists():
        try:
            prior = json.loads(snap_path.read_text(encoding="utf-8"))
            for k, v in prior.items():
                if k not in _manifest.entries:
                    _manifest.entries[k] = v
            logger.info("recovered %d entries from prior snapshot", len(prior))
        except Exception as e:
            logger.warning("snapshot recover failed: %s", e)

    logger.info(
        "gossip alive — host=%s heartbeat=%ds delta=%ds; "
        "subscribing to brain.memory.* and mesh.*",
        HOST_ID, int(HEARTBEAT_INTERVAL_SEC), int(DELTA_INTERVAL_SEC),
    )

    threading.Thread(target=_heartbeat_loop, name="gossip-heartbeat",
                     daemon=True).start()
    threading.Thread(target=_delta_loop, name="gossip-delta",
                     daemon=True).start()

    def _sigterm(_sig, _frame):
        _stop.set()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    while not _stop.is_set():
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
