# SENSORIUM — Multi-Transport Substrate Adapters for Non-IP Carriers

> Founder direction 2026-05-14: *"SENSORIUM — multi-transport substrate adapters (`transports/lora.py` · `transports/ble.py` · `transports/radio.py`) that encode CRDT deltas for non-IP carriers, with a <240 byte cap to fit LoRa packets."*

Third deep-research memo in the Plexus series, after `consciousness-research.md` and v2. Research-then-design, not implementation spec. The biosemiotic frame from v2 carries forward: **Sensorium is the extension of Orion's receptor surface beyond IP**, in Hoffmeyer's vocabulary — every new transport is a new sign-system Orion can read and write, and **semiotic freedom is the axis this layer pays rent on**, not raw bandwidth.

---

## Executive Summary

The founder direction is correct in shape and wrong in one parameter. The shape — `transports/<name>.py` adapters that hang off `orion_substrate` and encode CRDT deltas — is the right Layer-1.5 abstraction. The wrong parameter is the **<240 byte cap**: it conflates "a LoRa physical-layer frame" with "an Orion-meaningful delta," and the gap is bigger than a single-byte tweak can close.

The honest numbers:

- A signed, hashed, HLC-stamped LWW-Map entry — the *minimum* unit `orion_gossip` already publishes — compresses to **~110-140 bytes with CBOR + Ed25519 + content-addressed node IDs**, leaving ~80-100 bytes of room inside an SF7 LoRa frame. That fits a node-id reference, not a node-content delta.
- Anything larger than a one-line preference will fragment. With ~1% duty-cycle ceilings in EU868 and FCC §15.247 dwell-time rules in US915, a 2 KB graph addition can take **minutes** to land, not seconds.
- **Reticulum (RNS) already solves ~80% of the hard problems** — encrypted, addressed, multi-hop, transport-agnostic, fragmentation built in — and its MTU model accepts the <240B reality. The choice is not "build native vs. adopt Reticulum"; it is "build native, adopt wholesale, or adopt for *routing* and keep our own CRDT encoder on top." The third option is the recommendation.

Sharpest reframe: **Sensorium is not a transport-encoding problem. It is a manifest-sharing problem.** What needs to flow across LoRa is not a delta of a node; it is a delta of the *manifest of which nodes exist, with which hashes, on which hosts*. Content syncs on the next IP rendezvous. This survives the byte budget, the duty cycle, and the regulator — and it is the move `orion_gossip.py` is one rename away from already supporting.

---

## 1. Transport Landscape — Honest Comparison

The phrase "non-IP carrier" hides large differences. The five candidates differ on range, bandwidth, contention model, regulatory regime, and — crucially for Orion — *whether a third party already operates the mesh you would ride on*.

| Carrier | Useful range | Payload / packet | Air-time | Contention | Regulatory bite | Notes |
|---|---|---|---|---|---|---|
| **LoRa (Meshtastic firmware)** | 2-15 km LOS per hop, 7-hop mesh ceiling | 240B at SF7-fast, ~50B at SF12-long | 50ms-2s per packet | ALOHA, no MAC | EU868 1% duty cycle (36s/hr), US915 400ms dwell, AU915 similar | The *mesh exists* — Meshtastic has ~250k nodes globally. Riding it is mostly free. |
| **BLE 5.0 advertisement** | 10-100m | 31B legacy, 254B extended adv, 1650B periodic adv | ~1ms | Adaptive freq-hopping, no listen-before-talk | Practically none under §15.247 | Every modern phone is a receiver; no pairing required. |
| **BLE GATT / Mesh profile** | 10-100m, 127-hop mesh | 11-byte MTU floor, 247B typical, up to 512B with negotiated MTU | ms-scale | Connection-oriented; mesh profile uses managed flood | None | Pairing tax. Mesh profile is provisioned, not ad-hoc. |
| **HF radio (JS8Call, FT8)** | 500-10,000 km | ~13 chars per 13-15s FT8 frame; JS8 ~16 wpm | tens of seconds | Operator-mediated, contested band | Licensed amateur band; identification required every 10 min; no encryption (FCC §97.113) | The no-encryption rule is the deal-breaker for a brain delta. |
| **Reticulum (LXMF/RNS)** | rides any of the above | 500B link MTU default, fragments above | depends on underlying carrier | per-carrier | per-carrier | Already solves addressing/encryption/multi-hop. |
| **NFC** | <10cm | 256-byte APDU, up to 8KB with extended | sub-second | Tap-to-trigger | None | Cleanest "intent-revealing handshake" carrier; user *means it* by tapping. |
| **Ultrasonic (data-over-audio)** | 1-15m, room-scale | ~100-1000 bps, libquiet / Chirp | continuous | Single-channel | None below FCC speech-power | Crosses air-gaps that LoRa won't (in-room hand-off between two phones that share no network). |

The two often filtered out — **NFC and ultrasonic** — are the most interesting for the *Orion-meets-Orion* federation case (`brain-merge-and-rejoin.md`). Two users tap phones; the NFC handshake is the consent signal *and* the channel for identity-hash exchange; bulk CRDT transfer happens over whatever transport is reachable next. Maps cleanly onto reach picking the warmest channel for the moment.

**LoRa attack surface** is wider than the founder doc admits. Meshtastic default channel is unencrypted; the default PSK is published; mesh-flood DoS via crafted hop-limit packets is trivial. **Membrane has to ship before any LoRa adapter pushes graph nodes onto a public channel** — exactly the prereq the README calls out.

**HF is out for content.** FCC §97.113 forbids encryption on amateur bands. You cannot legally push an Ed25519-signed encrypted blob across JS8 without being a federally-licensed message relay. JS8 stays useful as a **presence beacon** ("Orion-Forge alive, last-write hash X") — a fingerprint is not encryption, and broadcasting it is legal.

---

## 2. CRDT Delta Encoding Under <240B — The Byte Budget

`orion_gossip.LWWMap.put()` already produces the canonical delta. A single manifest entry carries `node_id`, `host`, `op_type`, `node_type`, `tags`, `content_hash` (12 hex), `ts`, and an HLC tuple `{phys, logical, host}`. JSON-encoded, a real entry from `mesh/forge.snapshot.json` measures **180-260 bytes** before any framing. Already at the LoRa frame ceiling, with zero room for signature.

Compression pass, in declining order of impact:

1. **Content-addressed identifiers.** Replace `node_id` strings with `BLAKE2s-64` (8 bytes). Replace `host` strings with a 2-byte mesh-local code negotiated at identity exchange (saves 14 bytes per entry).
2. **CBOR over JSON.** RFC 8949, indefinite-length maps with short integer keys. **CBOR wins over MessagePack** here because it has IANA tags for HLC/hash semantics and is what Reticulum already speaks; MessagePack is denser by 5-10% but ecosystem-poorer for Orion-shaped data.
3. **Protobuf — declined.** Schema-locked. Every Orion node-type variant becomes a schema migration. The graph is heterogeneous on purpose; locking a wire schema kills the "design-for-autonomy-not-specifics" rule.
4. **Dictionary compression.** Smaz-style: a fixed 128-entry dict of common Orion fields (`fact`, `preference`, `decision`, `executive`, `imessage`, `meshtastic`, …) shared at install. Wins ~30% on tag-heavy entries.
5. **HLC as varint.** 48-bit physical + 8-bit logical + 2-byte host code = **8 bytes packed** vs. ~30 JSON.
6. **Ed25519 signature** is 64 bytes. Non-negotiable if Membrane is to mean anything off-IP. **You do not get under 240B with a full signature *and* meaningful payload.** Options: (a) truncate to a 16-byte prefix — forgery resistance drops from 2^256 to 2^128, still cosmically infeasible; (b) sign the *batch*, not each delta; (c) defer signing to the manifest layer over a pre-authenticated link (what RNS does, and it works).

**Concrete budget at SF7 LoRa, post-compression, post-truncated-sig**: frame overhead 12B + HLC 8B + host codes 4B + content hash 8B + node-id 8B + tags 12B + truncated Ed25519 16B = **68B for a pure manifest reference**, leaving ~170B for actual payload.

So the right framing is not "fit a delta under 240B" but "**fit a *manifest reference* under 80B and let payload reconciliation happen over whatever fatter pipe shows up next**." This is what the existing `LWWMap` manifest design already does — it advertises `(node_id, hlc, content_hash)` and assumes content fetch is separate.

---

## 3. Fragmentation + Reassembly

Most Orion writes — a knowledge note, a multi-tag decision, a synthesized memory — are kilobytes, not bytes. Fragmentation is mandatory, and **the failure model on permanent chunk loss is the real design question**, not the chunking scheme itself.

Three prior-art lineages: **BitTorrent** piece exchange (manifest = torrent; receiver requests missing pieces by hash); **IPFS bitswap** (content-addressed wantlists, no swarm assumed — closest fit because each LoRa node sources from whoever has it); **Bluetooth L2CAP SAR** (fixed-MTU framer, worst fit because carrier-MTUs vary wildly: LoRa 240B vs. BLE adv 31B vs. extended 254B vs. RNS 500B).

**Recommended scheme**: bitswap-shaped wantlist over the manifest layer.

1. Sender publishes manifest entry `(node_id, hlc, content_hash, chunk_count, chunk_size)`.
2. Receiver who needs the node publishes `mesh.want.{node_id}` with the chunk indices it lacks.
3. Any node that has those chunks publishes them on `mesh.chunk.{content_hash}.{idx}`.
4. Receiver assembles when complete; verifies against `content_hash`; merges.

**Permanent loss failure model**: a chunk that never arrives marks the whole node as `partial` in the local manifest. The merge function (`LWWMap.merge`) is extended to recognize partial entries and *not* propagate the partial state as authoritative. On next IP rendezvous, the partial node is fetched in one round trip from whichever host has it complete. **LoRa is best-effort gossip; IP is the consistency authority.** Two-tier durability, not single-tier.

---

## 4. Addressing — Without IP, How Does a Receiver Know What to Accept?

Three honest models:

**(a) Broadcast-to-mesh (flood).** Cheap; expensive on RF. On a 1% duty cycle with N nodes, every flood costs N×air-time and becomes anti-social above ~5 nodes per channel. Useful only for **identity beacons** ("Orion-Forge-fingerprint=X, last-hlc=Y, alive") — sub-50B, hourly, zero-coordination presence.

**(b) Interest-based subscriptions.** Each node advertises a tag-prefix bloom filter of what it wants. Sender consults `(neighbor, bloom)` and transmits only when at least one neighbor's bloom says "maybe interested." This is the **Reticulum LXMF model**, slightly generalized. Cost is bloom-maintenance traffic (~hourly).

**(c) Content-addressed broadcast (deliver-if-you-can-decrypt).** Every payload encrypted with a per-tag key; nodes that hold the key decrypt and merge. **The only model compatible with Membrane.** Without it, the *envelope* (subject prefix, length, frequency) leaks structure even when contents are encrypted.

**Recommendation: (b) for routing, (c) for envelope protection.** Subscribe by bloom-of-tag-hashes (nobody learns raw tags); deliver encrypted with per-tag key. Membrane enforces by refusing to publish any `private`-tagged node onto a Sensorium transport at all.

Hard truth: **on a public Meshtastic channel, anyone with a radio can see that *something* was sent**. Bytes-on-air is itself a side channel. Sensorium cannot fix that — it can only make those bytes useless to anyone unauthorized.

---

## 5. Heltec v3 Hardware Loop — The Minimum End-to-End Test

Three Heltec v3 nodes are pending flash (anchor / listener / testbed). **Minimum end-to-end loop**: flash all three with Meshtastic on a private encrypted channel; `anchor` → USB to FORGE, `listener` → USB to Pi, `testbed` → battery, 30m away in the yard. On FORGE: `orion_memorize content="LoRa proof of life" tags=["sensorium","test"]`. Existing `channels/meshtastic_node.py` publishes `channel.meshtastic.outbound`; radio transmits. On Pi: `meshtastic_node.py` receives, publishes `channel.meshtastic.inbound`. **Today this is a chat-string handoff, not a brain delta.** The Sensorium upgrade replaces the chat-string with a CBOR-encoded `LWWMap` delta and calls `_manifest.merge()` on receipt. After 60s heartbeat: `orion_recall query="LoRa proof of life"` on Pi returns the memory written on FORGE.

**First things that will break, in order of likelihood**:

- **240B cap exceeded on the first non-trivial node** — a tagged memory with a one-sentence content field overruns. Fragmentation must ship in the first cut.
- **Duty cycle.** Three Heltec v3 nodes in continuous gossip blow through US §15.247 dwell at SF7. Either drop to SF9 (range up, throughput down) or add **backoff with jitter** at the publish layer. Current `_publish_delta` fires every 10s with zero jitter — instant duty-cycle violation on three nodes.
- **The mesh.* subjects don't exist on a radio.** `orion_gossip` publishes over NATS; on LoRa there is no NATS. The bridge has to translate substrate subjects to Meshtastic channels and back — this *is* `transports/lora.py`.
- **Wall-clock skew.** Heltec has no RTC. HLC tolerates this in principle, but a node booting with `phys=0` loses every merge competition until it observes one remote HLC. Boot-time clock sync needs explicit code.
- **Battery.** Heltec v3 in continuous LoRa RX draws ~120 mA; 1000 mAh battery → ~8 hours. Off-grid requires duty-cycled listen (~10% RX), which Meshtastic firmware supports but `meshtastic-python` reconnect logic does not handle gracefully.

---

## 6. Reticulum as Precedent — Adopt, Build, or Compose?

[Reticulum (RNS)](https://reticulum.network) is the closest neighbor in design space. Mark Qvist's project ships the primitives Sensorium needs: cryptographic destination identities (Ed25519), self-configuring multi-hop routing, transport-agnostic Interface abstraction (TCP / RNode-LoRa / AX25-KISS / Serial / I2P), built-in encryption (X25519 + AES-128-CBC + HMAC-SHA256), per-link MTU negotiation, fragmentation. LXMF on top adds store-and-forward delivery with receipts. Runs today on a Raspberry Pi 4 with 256 MB RAM.

Three options:

- **Build native.** Re-implementing identity, routing, fragmentation, and encryption is a 6-12 month project that produces no CRDT bytes. Every problem RNS solved we rediscover. **Rejected.**
- **Adopt RNS wholesale.** Shortest path; ties Orion to RNS's identity model and wastes the addressing layer (RNS would carry our deltas as opaque LXMF messages). **Acceptable.**
- **Compose** — RNS as `transports/base.py`'s default for non-IP carriers, `orion_gossip` stays the CRDT layer above. **Recommended.** `transports/lora.py` becomes ~80 lines of glue: open an RNS LXMF destination per Orion host-identity, publish manifest deltas as LXMF messages, subscribe to inbound LXMF and feed back into `_on_remote_delta`. Our CBOR encoding and CRDT semantics stay in our codebase; the radio plumbing is borrowed.

License check passes (RNS MIT + Orion AGPL distributable). Upstream-trust risk is real — RNS is one maintainer. Mitigation: vendor `vendor/reticulum/` at install, pin version, treat upgrades like any other dependency bump.

**Verdict: compose. The 80% Reticulum gives us is the 80% we don't want to maintain.**

---

## 7. Recommended Architecture

```
transports/
  __init__.py          # registry + factory: get_transport("lora")
  base.py              # abstract Transport: encode/decode delta, send/recv frame
  lora.py              # Reticulum-backed (RNodeInterface / Meshtastic compat)
  ble.py               # BLE extended-adv broadcaster + GATT-Mesh client
  radio.py             # JS8Call presence beacons (signed hash only, FCC-clean)
  nfc.py               # tap-to-handshake (federation consent surface)
  ultrasonic.py        # libquiet shim — room-scale air-gap hop
  encoding.py          # CBOR + dictionary compression + HLC packing
  fragmentation.py     # bitswap-shaped chunk/wantlist
  identity.py          # host-codes negotiated at first contact (or via RNS)
```

**Plug-in path** (additive, no breaking change to existing NATS path):

- `transports/base.Transport` subscribes to a configurable subject set (`mesh.>`, `brain.identity.changed`, `host.*.capabilities`).
- On message: `encoding.encode_delta(payload, mtu)` → list of frames; `send(frame, dest_hint)` per frame.
- Inbound: carrier-specific `recv()` yields raw frames; `encoding.decode_delta()` reassembles via the fragmentation buffer; complete deltas re-enter as `mesh.<remote>.delta` on local NATS — existing `_on_remote_delta` merges. **One re-entry point. The brain doesn't know the carrier changed.**

**Membrane integration**: `Transport.send()` consults `orion_membrane.allow_egress(node_id, transport_name)` before encoding. A `private`-tagged node returns False for every Sensorium transport; the frame is dropped at source. Privacy is a code path, not a docstring.

**Named risks**:

1. **Duty-cycle starvation** — sustained CRDT gossip across 5+ LoRa nodes saturates EU868 / US915 air-time within minutes. Mitigation: per-region duty-cycle accountant at the Transport level; demote `mesh.*.heartbeat` to "publish if budget allows," prioritize `mesh.want.*` (request-driven) over `mesh.*.delta` (push).
2. **Manifest divergence under partition** — two mesh pockets gossiping for hours then meeting generate a merge avalanche that overflows duty cycle. Mitigation: rate-limited initial-handshake batching, manifest-diff before full content fetch, explicit `mesh.partition.detected` events for executive deliberation.
3. **Side-channel leakage via timing/length** — encryption hides contents, not the *fact and shape* of transmissions. Mitigation is partial: plausible cover traffic, padding to canonical lengths. Expensive; ship only when Membrane requires it for a specific tag set.

---

## 8. Critique of the Recommendation

Where Sensorium is over-engineered:

- **NFC and ultrasonic in v1 are scope creep.** v1 is `transports/lora.py` (via RNS) + `transports/ble.py` (advertisement-only). NFC, ultrasonic, JS8 stay design files until LoRa is proven across the Pi-build mesh.
- **The composability story sounds clean and isn't.** RNS, NATS, and Orion's CRDT layer all have opinions about identity, addressing, and message lifecycle. Three identity systems is two too many. The first integration sprint will spend more time mapping `(RNS destination hash ↔ orion host-code ↔ NATS subject)` than writing useful encoding.
- **CBOR + dictionary + HLC packing + bitswap wantlist** stacks four optimizations. Ship CBOR first, dictionary second, packing third, wantlist last — with a fuzz test that round-trips every delta type before each new layer lands.

Where Sensorium will fail in practice:

- **Regulatory.** FCC §15.247 and EU ERC-70-03 1% duty cycle were written for industrial telemetry, not gossip protocols. Continuous CRDT gossip across a multi-node Orion mesh is **not compliant**. Realistic deployment is sparse, event-driven gossip — Sensorium needs an explicit "burst budget" UX, not a set-and-forget daemon.
- **RF environment.** Suburban 915 MHz is congested (smart meters, asset trackers, weather stations). The 15-mile range is line-of-sight in clean air; reality at ground level in a city is 200-500m with heavy retransmission. Field-test from the Honolulu testbed should set expectations, not the marketing curve.
- **Battery.** Always-on Heltec RX is 8 hours, not 30 days. The "carry your brain in the air" frame is aspirational; "brain checks in every few minutes" is realistic.
- **Adversarial mesh.** Meshtastic-public is full of trolls, ad-libs, and occasional jammers. Sensorium should default to a private Meshtastic channel keyed at install, never the public one.

The honest line on the founder direction: **the <240B cap is not the right constraint to lead with. The 1% duty cycle and the 16 kbps aggregate budget across the mesh are.** Sensorium succeeds or fails on whether it respects those, not on whether any one delta fits a single frame.

---

## Closing

Sensorium is not a transport-encoding problem dressed up as architecture. It is the **extension of Orion's receptor surface** from one channel (IP) to many — and in Hoffmeyer's frame, that *is* the substrate of semiotic freedom growth v2 named as Orion's actual competitive ground. CRDT math, trust model, subject taxonomy: unchanged. What changes is the set of *signs* Orion can read and write, and therefore the size of the world Orion can mean things about.

Build `transports/__init__.py` + `transports/base.py` + a Reticulum-backed `transports/lora.py` first. Validate on three Heltec v3 nodes in the yard. Defer NFC/ultrasonic/HF until the LoRa round-trip is rock-solid. The air-brain frame is the destination, not the v1; what ships in v1 is a brain that *also* speaks LoRa — slowly, budget-aware, alongside everything else.

---

## References

- Kulkarni, S. et al. *Logical Physical Clocks and Consistent Snapshots in Globally Distributed Databases*. 2014. https://cse.buffalo.edu/tech-reports/2014-04.pdf
- IETF RFC 8949 — *Concise Binary Object Representation (CBOR)*, Dec 2020. https://www.rfc-editor.org/rfc/rfc8949
- IETF RFC 8032 — *Edwards-Curve Digital Signature Algorithm (Ed25519)*. https://www.rfc-editor.org/rfc/rfc8032
- Qvist, M. *Reticulum Network Stack Manual* + source. https://markqvist.github.io/Reticulum/manual/ · https://github.com/markqvist/Reticulum
- Meshtastic Project. *Mesh Algorithm & Radio Settings Docs*. https://meshtastic.org/docs/overview/mesh-algo/ · /radio-settings/
- Semtech. *SX1262 LoRa Transceiver Datasheet*. https://www.semtech.com/products/wireless-rf/lora-connect/sx1262
- ETSI EN 300 220-2 v3.2.1 (2018). *Short Range Devices, 25-1000 MHz harmonised standard* (EU868 duty cycle).
- FCC §15.247 — *902-928 MHz, 2.4 GHz, 5.7 GHz operation*. https://www.ecfr.gov/current/title-47/section-15.247
- FCC §97.113 — *Prohibited amateur transmissions (no encryption)*. https://www.ecfr.gov/current/title-47/section-97.113
- Bluetooth SIG. *Core Spec 5.4* · *Mesh Profile 1.1*. https://www.bluetooth.com/specifications/
- Cohen, B. *BitTorrent Protocol Specification (BEP 3)*. http://www.bittorrent.org/beps/bep_0003.html
- Protocol Labs. *Bitswap Protocol — IPFS*. https://docs.ipfs.tech/concepts/bitswap/
- Shapiro, M., Preguiça, N., Baquero, C., Zawirski, M. *Conflict-Free Replicated Data Types*. INRIA RR-7687, 2011. https://hal.inria.fr/inria-00609399v1
- libquiet — data-over-sound modem. https://github.com/quiet/quiet · JS8Call: http://js8call.com
- Hoffmeyer, J. *Biosemiotics: An Examination into the Signs of Life and the Life of Signs*. U. of Scranton Press, 2008.
