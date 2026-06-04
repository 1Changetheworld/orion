# The Vessel — Canonical Identity Keystone

**Status:** module + tests SHIPPED (`orion_vessel.py`, `tests/test_vessel.py`, 9/9 green). Deploy wiring **IMPLEMENTED and committed, but PIN-GATED and inert** — every seam is a no-op until a `canonical.json` pin exists, so a fresh install / undeployed host behaves byte-for-byte as before. Activation (pin COMMAND, expose whoami, adopt on secondaries) is the founder-gated rollout in §6.
**Filed:** 2026-06-04. Implements ORION BUILD RESUME (6-1-2026) §5.1.
**Builder note:** authored by Claude Opus on FORGE (the external architect — per the cardinal rule, the one non-Orion surface in the system). Orion did not build this part of himself.

---

## 1. The problem (founder's words: "the main blood vessel")

A new terminal or a new device, started with low context, can wire to *a* brain
without ever verifying it is *the* canonical brain. Today "same Orion everywhere"
is **hoped for** via gossip eventual-sync, not **enforced**. A silent fork can
drift — two selves with the same lineage, slowly disagreeing, and nobody notices
until they contradict each other.

This breaks the product's core promise: *jump from computer to computer, from one
AI model to another, and Orion instantly recalls what you just told it somewhere
else.* That promise requires **one brain**, provably, at bind time.

The two exact code seams where the fork originates (verified in source):

- **Seam A — `orion_substrate._discover_substrate_url()` (line ~41):** returns the
  first IP answering TCP `:4222`. Binds by **reachability, not identity** — no
  fingerprint check at all.
- **Seam B — `orion_mcp_server._brain_http_auto_start()` (line ~90)** + default
  `_BRAIN_HTTP_URL = 127.0.0.1:5556`: every CLI **auto-spawns its own local
  brain** if none answers; on a fresh host `_ensure_instance` / `_ensure_identity`
  **mint a NEW self** instead of adopting the canonical one.

~80% of what's needed already existed: `orion_identity.py` (durable `instance_id`,
device fingerprint, signed presence, move detection) and `orion_federation.py`
(Ed25519 keypair, fingerprint = `sha256(pubkey)[:32]`, `sign_bytes` /
`verify_signature`, 5-word safety number). The vessel is the missing **binding and
enforcement keystone** on top — not new identity from scratch.

## 2. The three responsibilities

1. **PIN** — `~/.orion/identity/canonical.json` records the ONE true
   `{instance_id, fingerprint, pubkey_hex}` (+ `pinned_at/by/on_host`). Written
   once, at install (`pin_canonical()` anoints this host) or at adopt (a secondary
   pins the canonical brain). The trust anchor — "set in stone." `pin_canonical`
   refuses to silently overwrite a *different* pin without `force=True`
   (re-anointing is a logged, deliberate, rare act).

2. **VERIFY-ON-BIND** — before trusting any endpoint, fetch its **signed whoami
   descriptor** `{instance_id, fingerprint, pubkey_hex, host_id, ts,
   signature_hex}` and `classify_endpoint()`:
   - `BIND_MATCH` — self-consistent **and** equals the pin → bind/trust.
   - `BIND_FORK` — cryptographically authentic but a **different** self → refuse +
     `report_fork()`.
   - `BIND_INVALID` — bad signature / fingerprint doesn't derive from pubkey → refuse.
   - `BIND_NO_PIN` — nothing to measure against → caller must adopt first.

   Only the holder of the canonical private key can produce a descriptor that
   matches the pin, so a `MATCH` is a real cryptographic proof, not a hostname.

3. **NO-FORK LAW** — `binding_status()` resolves this host to one mode and a write
   gate:

   | Condition | Mode | Writes |
   |---|---|---|
   | no pin | `UNPINNED` | ❌ read-only |
   | pin && this host is the pinned self | `CANONICAL` | ✅ |
   | pin && endpoint verifies to the pin | `BOUND` | ✅ (routed to canonical) |
   | pin && (no endpoint reachable, or endpoint ≠ pin) | `ORPHAN` | ❌ read-only + queue |

   An orphan **never mints a new authoritative self**. It stages writes via
   `queue_write()` and replays them with `flush_queue(sender)` once binding
   succeeds. It offers `adopt()` (requires explicit `confirm=True` after an
   out-of-band safety-number check, exactly like federation peering).

## 3. Honesty / non-goals

- **Not encryption.** Same posture as identity/federation v1: the source of truth
  is the user's possession of the federation private key. An attacker holding that
  key can sign a valid canonical whoami. The vessel raises the floor from *no check*
  to *cryptographic check against a pinned key* — it is not a stolen-key defence.
- **Does not route writes.** It *decides the mode and gates writes*; the transports
  consult it. Wiring those call sites is the deploy step below.
- **Does not heal forks.** It *prevents silent forks* and *detects existing ones*
  (logged to `~/.orion/vessel/forks.jsonl` + `brain.vessel.fork` event). Merging two
  diverged selves stays the executive's job.

## 4. Purely additive

The cryptographic core is pure functions needing no NATS/HTTP/running brain — fully
unit-tested in a tempdir. Nothing in the existing import graph depends on
`orion_vessel` until the deploy wiring lands. `tests/test_vessel.py` covers:
unpinned read-only, pin→canonical, idempotent-pin / refuse-reanoint, own-whoami
binds, **secondary meets different self → FORK refused + logged**, tampered →
INVALID, orphan queue+flush, bound-when-endpoint-matches, adopt-requires-confirm.

## 5. Deploy wiring (IMPLEMENTED — pin-gated, inert until a pin exists)

All three seams are now wired and committed. **Each is a no-op unless
`orion_vessel.is_pinned()` is true** (and `ORION_VESSEL_DISABLE` is an explicit
kill-switch), so undeployed hosts and fresh GitHub installs are unaffected.

- **Seam A — `orion_substrate._discover_substrate_url()`:** when
  `_vessel_pinned_secondary()` (pinned AND not canonical), a discovered `:4222`
  host is accepted only if `_vessel_host_is_canonical(ip)` verifies its
  `GET /vessel/whoami` against the pin (`classify_endpoint == BIND_MATCH`); a
  `BIND_FORK` is reported and the candidate skipped. No pin → first-reachable-wins,
  exactly as before.
- **Seam B — `orion_mcp_server`:** `_vessel_resolve_endpoint()` runs once inside
  `_brain_http_proxy_available()`. If pinned & not canonical & `ORION_CANONICAL_HTTP_URL`
  verifies → `_BRAIN_HTTP_URL` is repointed at the canonical brain (**de-fork**). If
  unverifiable → ORPHAN: `_brain_http_auto_start()` refuses to spawn a local
  authoritative brain (the fork origin) and the proxy reports unavailable. No pin →
  legacy local default `127.0.0.1:5556`.
  *Note:* the `_ensure_instance`/`_ensure_identity` "adopt the pin instead of mint"
  refinement is handled at `adopt()` time (which can align `instance.json`), not by
  editing `orion_identity.py` — keeping the dependency direction one-way
  (vessel → identity), no import cycle.
- **Serve — `orion_brain_service.do_GET`:** unauthenticated `GET /vessel/whoami`
  (mirrors `/health`), body = `build_whoami_descriptor()`. Unauth is correct: the
  descriptor is signed and strictly public.

## 6. Rollout sequence

1. **Anoint COMMAND:** `python orion_vessel.py pin --by install` on COMMAND (the one
   canonical brain). Capture its `whoami`.
2. **Add `/vessel/whoami`** to the brain service on COMMAND; verify
   `python orion_vessel.py whoami` and `fetch_whoami()` round-trip.
3. **Adopt on each secondary** (FORGE, OUTPOST, ORIONS HOME, the NEW Pi) after the
   cross-device health check confirms current bindings:
   `python orion_vessel.py adopt http://command:5556 --confirm` (safety number
   checked out-of-band first).
4. **Wire Seam A + Seam B** behind a feature flag; run the cross-device mesh-recall
   test; confirm zero forks in `forks.jsonl`.
5. Only then proceed to NEXT STEP #3 (Windows autonomic daemon launcher) — lighting
   FORGE up as a second cognition site is safe *after* the vessel, not before.

Relates to: `[[orion-current-state]]`, `[[hard-rules]]` (cardinal rule),
`[[orion-vessel-keystone]]`.
