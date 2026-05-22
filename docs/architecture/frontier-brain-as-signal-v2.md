# Frontier: Brain as Signal v2 — State That Travels Without Internet

> *"What if online didn't mean internet? The brain we use on every model
> online and offline — what if it existed as LoRa signals in the air?"*
> — founder, 2026-05-13

This is the research successor to `brain-as-signal-frontier.md` (the North-Star
vision) and the engineering companion to `sensorium-research.md` (the transport
adapter design). Both of those are still correct. This doc does **not** repeat
them. It goes *beyond* them on three fronts where the literature moved between
when those were written and now:

1. **Set reconciliation got cheap.** Two 2024–2025 results — Rateless IBLT
   (SIGCOMM 2024) and ConflictSync (May 2025) — change the duty-cycle math for
   CRDT-over-radio in Orion's favor by roughly an order of magnitude. The
   existing docs assume "advertise manifest, fetch content on the fat pipe."
   The new results let two divergent brains discover *exactly what differs*
   using bytes proportional to the difference, not the brain.
2. **Resumability is a named, studied problem now.** "Agent checkpoint /
   restore" is a 2025–2026 research area with its own attack literature.
   Orion's "brain resumes with no single host" claim is exactly this problem,
   and the security findings (semantic rollback attacks) are a direct hazard
   for CRDT-merge-over-radio that the current code does not yet defend against.
3. **MeshCore exists.** The LoRa-mesh landscape is no longer Meshtastic-only.
   Meshtastic's flood routing — which `channels/meshtastic_node.py` rides — is
   now the *worst* fit for Orion's gossip traffic. There is a strictly better
   routing substrate for our use case, and it's already shipping.

The frame this doc commits to: **identity + critical state + reach travel over
radio; full cognition does not, and the honest architecture makes that split a
first-class design boundary rather than a disappointment.**

---

## 0. The physics, restated as a budget (not a vibe)

Every brain-as-signal claim has to survive the time-on-air arithmetic. The
existing docs gesture at this; here it is as a hard table you can compute
against. LoRa data rate is set by spreading factor (SF):

| SF | Raw rate | RX sensitivity | 20-byte frame air-time | Range (real, ground-level) |
|----|----------|----------------|------------------------|----------------------------|
| SF7 (BW500) | ~5.5 kbps | −123 dBm | ~9 ms | 200–500 m urban, 2 km LOS |
| SF7 (BW125) | ~5.5 kbps | −123 dBm | ~36 ms | as above |
| SF12 (BW125)| ~250 bps  | −137 dBm | ~1.3 s | 5–15 km LOS, ~1–3 km urban |

The killer is not frame size — it's **regulatory duty cycle stacked on top of
air-time**. At a 1% duty cycle (EU868; US915 uses dwell-time/frequency-hopping
rules that bite similarly under sustained load), a 20-byte SF12 frame's ~1.3 s
air-time forces a **~130-second silence** before the next transmit on that
channel. That is the real constraint. (Sources: Avramut SF7–SF12 throughput
data; TTN spreading-factor docs.)

**What this rules in and out, definitively:**

- **IN over radio:** identity beacons (sub-50 B, hourly), preference/decision
  deltas (one or two LWW entries), manifest *differences* (see §1), reach
  signals ("Orion-Forge alive, ask me anything, fuel=ollama"). These are the
  small, high-value bytes.
- **OUT over radio:** synthesis, multi-KB knowledge notes as a *push*, vector
  re-embedding, anything that needs the model. These ride the next IP
  rendezvous. The model is "jet fuel" — and **fuel does not fit through a
  250-bps straw.** This is not a limitation to apologize for; it's the thesis.
  The brain (state) travels over radio; the fuel (compute) is fetched locally
  wherever the brain lands.

The single most useful reframe in this whole document: **Orion over radio is a
*difference-propagation* system, not a *content-streaming* system.** Build for
"two brains discover what differs and exchange only that," never "stream the
brain through the air."

---

## 1. WHAT'S NEW: set reconciliation that fits the duty cycle

The existing `sensorium-research.md` recommends a **bitswap-shaped wantlist**
(manifest entry → `mesh.want.{id}` → chunk delivery). That is correct and
buildable, but it assumes the receiver already knows *which* node IDs to want —
i.e. it assumes manifests are exchanged in full first. For a brain of 10³–10⁴
nodes meeting after a long partition, **exchanging full manifests is itself the
expensive step**, and on a 1% duty cycle it can take minutes-to-hours.

Two results published after those docs were written solve exactly this:

### Rateless IBLT (Practical Rateless Set Reconciliation, SIGCOMM 2024)

A novel encoder incrementally encodes the *set difference* into an infinite
stream of coded symbols. The receiver pulls symbols until it can invert the
difference — communication cost proportional to the number of differing
elements, **not** to set size, and **3–4× lower communication** than
non-rateless schemes at similar compute. "Rateless" is the magic word for
radio: you don't have to know the difference size in advance (you never do
after an unknown partition), and you stop transmitting the instant the receiver
signals "decoded." That maps perfectly onto a duty-cycle-budgeted link: send a
symbol, wait out the duty cycle, send the next, stop when peer ACKs decode.
(Source: Practical Rateless Set Reconciliation, arXiv 2402.02668 / SIGCOMM 2024;
reference impl `samWighton/rateless_iblt`.)

### ConflictSync (May 2025)

The first **digest-driven** synchronization algorithm purpose-built for
*state-based CRDTs* with variable-sized elements — i.e. exactly Orion's
`LWWMap` of heterogeneous manifest entries. It combines Bloom filters with
Rateless IBLT and reports **up to 18× less total data transfer** than naive
state-based sync. (Source: ConflictSync, arXiv 2505.01144.) Crucially it
targets *divergent* state — two replicas that drifted apart — which is the
two-pocket-mesh-meets case the sensorium doc named as named-risk #2 ("merge
avalanche overflows duty cycle"). ConflictSync is the published answer to that
exact risk.

**Why this matters for Orion specifically.** `orion_gossip.LWWMap.merge()`
today takes a *full* remote `entries` dict and walks it key-by-key. Over NATS
that's fine (§"HONESTY ABOUT SCALE" in the code). Over LoRa it is the avalanche.
Replacing the wire step — not the merge semantics — with a ConflictSync exchange
means two Orion brains that have been apart for a week discover their manifest
difference in bytes proportional to *what changed that week*, then fetch only
those node bodies. The CRDT math, the HLC, the LWW conflict rule: all unchanged.
Only the **anti-entropy wire protocol** below `merge()` changes.

This is the single highest-leverage upgrade the v2 frame proposes, and it is
**buildable now** in software (no new hardware) as a pure-IP optimization first,
then reused verbatim on radio.

---

## 2. WHAT'S NEW: the resumability problem has a literature (and an attack)

The North-Star doc says the brain is "reachable and resumable with no single
host." In 2025–2026 this became a named research area: **agent checkpoint /
restore and resumable workflows** (LangGraph node-level checkpointing; Zylos
checkpointing-and-resumability survey; DataStates-LLM for the heavy weights
case). The relevant lesson for Orion is *not* the weights work — Orion has no
weights — it's two findings that apply directly to a brain that resumes from
radio fragments:

1. **Checkpoint/restore cannot undo external side effects.** A restored agent
   re-runs actions whose effects already happened (the 2025 finding that
   restore "saves and restores local process state but cannot undo external
   service actions"). For Orion this means: a brain resumed from a stale radio
   snapshot must treat already-fired *reach* and *will* actions as
   possibly-replayed. Orion's `decision_ledger.jsonl` is the right place to
   carry an idempotency key per action so a resumed brain doesn't re-send a
   text it already sent before the partition.

2. **Semantic rollback attacks** (ACRFence, arXiv 2603.20625): an adversary
   feeds an agent an *older but validly-signed* checkpoint to roll its state
   back to a pre-decision point — defeating naive "the signature checks out"
   trust. **This is a live hazard for CRDT-over-radio.** Orion's LWW-by-HLC rule
   is monotonic *if* HLCs only move forward, but an attacker who captures a
   valid old `mesh.*.delta` frame and re-injects it is harmless under LWW
   (older HLC loses) — *good* — **whereas** an attacker who captures a frame and
   re-injects it claiming a *future* HLC wins the merge and rolls a node's
   content backward. The HLC's `host` tie-breaker and Ed25519 signature bound
   the author, but **nothing today bounds the freshness window.** Defense:
   sign `(delta, observed_max_remote_hlc)` so a frame asserting an HLC far ahead
   of any the signer could plausibly have seen is rejected; and keep a
   per-author HLC high-water mark so a replayed-as-future frame fails the
   monotonicity check. This belongs in `transports/identity.py`, not as an
   afterthought.

**Net:** "resumable" is achievable and the prior art validates the approach, but
the radio path adds a freshness/replay attack surface that the IP path (where
HLCs flow continuously) mostly hides. The sensorium doc's Membrane gate handles
*egress* privacy; this is the missing *ingress* integrity rule.

---

## 3. WHAT'S NEW: MeshCore changes the routing recommendation

When `channels/meshtastic_node.py` and the sensorium doc were written,
Meshtastic was the only credible hobbyist LoRa mesh. As of 2025–2026 there is a
direct competitor with a routing model that is **strictly better for Orion's
traffic shape**:

| | Meshtastic | MeshCore |
|---|---|---|
| Routing | Managed **flood** — every node rebroadcasts every packet | **Source-routed**: flood once to discover a path, then unicast along the learned route |
| Hop ceiling | 3 default, 7 max | up to 64 hops |
| Cost model | Every message costs N×air-time across the mesh | First message expensive, subsequent messages cheap |
| Best for | Small/mid mesh, broadcast chat | Larger, busier, topologically complex meshes |
| Field latency | seconds | sub-second nearby, sub-2 s at 9 hops (Austin testing) |

(Sources: Austin Mesh, NodakMesh, Mesh America comparisons 2025–2026.)

**Why this matters.** Orion gossip is *mostly point-to-point anti-entropy*
between known hosts (FORGE ↔ Pi ↔ COMMAND), not broadcast chat. On Meshtastic's
flood model, every manifest delta between two specific hosts is rebroadcast by
every node in earshot — the duty-cycle avalanche the sensorium doc warned about,
made worse by the routing layer itself. MeshCore's source-routing means a
FORGE→Pi delta travels only the FORGE→Pi path. **For Orion's traffic shape,
source-routed beats flood by exactly the factor that makes the duty-cycle budget
survivable.**

This does **not** mean rip out Meshtastic. It means: the transport abstraction
in `transports/lora.py` should treat *routing protocol* as a swappable backend,
and the recommended default for the multi-host Orion mesh (point-to-point
anti-entropy) is **source-routed (MeshCore or Reticulum's own routing), not
Meshtastic flood.** Meshtastic flood stays the right choice for the *broadcast
identity beacon* (§4) — one packet, everyone should hear it. Two routing modes,
chosen by message class:

- **Identity beacon / "Orion alive" → flood** (Meshtastic-style; everyone hears)
- **Manifest anti-entropy / node fetch → source-routed** (MeshCore/RNS; only the path)

---

## 4. The honest split: what is the "brain in the air," concretely

Decompose the brain into what radio can and cannot carry, by byte budget:

| Layer | Size | Over radio? | Carrier | Cadence |
|---|---|---|---|---|
| **Identity fingerprint** | <50 B | YES — trivially | flood beacon | hourly |
| **Preference / address / name** | <200 B | YES — one delta | source-routed | on change |
| **Decision / reach idempotency keys** | ~100 B ea | YES — batched | source-routed | on change |
| **Manifest difference** (which nodes differ) | ∝ difference | YES — ConflictSync | source-routed, rateless | on rendezvous |
| **Node bodies** (fact text, edges) | KB ea | DEGRADED — fragmented, slow | wantlist/bitswap | request-driven |
| **Knowledge notes** | KB–MB | NO (push) — IP only | — | next IP link |
| **Vector embeddings** | MB | NO — IP only | — | next IP link |
| **The model (fuel)** | GB | NEVER | — | fetched locally |

The product claim that survives this table: **"Orion's *identity and the part of
its memory that just changed* can reach you over the air with no internet; the
bulky knowledge catches up the next time a fat pipe appears, and the thinking
happens on whatever compute is near you when you land."** That is true,
defensible, and still first-of-its-kind. The over-claim to avoid: "your whole
brain lives in the air." It does not, and the physics says it cannot. The
*living edge* of the brain — identity, latest deltas, the ability to be
reached — does. That's enough to be remarkable.

---

## 5. DTN / Bundle Protocol as the resumability spine

The piece neither existing doc names: **delay/disruption-tolerant networking
(DTN) and Bundle Protocol v7 (RFC 9171)** are the standardized answer to
"store-and-forward across links that are never simultaneously up." Orion's
gossip already does a hand-rolled version of this — `orion_gossip` persists a
snapshot to disk and re-gossips on reconnect; `orion_mesh_recovery` opens a
durable task on partition and reconciles on return. That is **DTN custody
transfer reinvented in miniature.**

The mature pattern to borrow (not necessarily the wire format) from BPv7 / DTN7:

- **Bundles, not packets.** A unit of brain state to move is a self-describing
  bundle (payload + HLC + author + content-hash + TTL), independent of which
  carrier hops it across. This is what makes a delta *resumable*: a half-arrived
  bundle is identifiable and re-requestable. Orion's manifest entry is already
  90% a bundle; add an explicit TTL and a custody flag.
- **Custody transfer.** When host A hands a bundle to host B, B accepts
  *custody* — it now owns getting that bundle onward. This is exactly the
  `mesh_recovery` "make the returned device whole" job, generalized to data.
- **Convergence layers.** BPv7 separates the bundle from the link that carries
  it (TCPCL, etc. — RFC 9174). This is *precisely* the `transports/base.py`
  abstraction the sensorium doc proposes. The lesson: keep the bundle format
  carrier-agnostic; let each `transports/*.py` be a convergence layer.

**Recommendation:** do *not* adopt BPv7 wire format wholesale (it carries IPND/
routing baggage Orion doesn't need, and Reticulum already gives transport-agnostic
addressing + encryption + fragmentation that the sensorium doc correctly
recommends composing with). **Do** adopt BPv7's *conceptual* model — bundle +
TTL + custody + convergence-layer separation — as the vocabulary for
`transports/base.py`. DTN7-go and the lightweight RFC 9171 subset
implementations are the reference to read, not necessarily to link against.
(Sources: RFC 9171; DTN7 project; lightweight BPv7 subset work, IEEE 10289381.)

---

## 6. Concrete architecture for Orion's existing pieces

This slots into the files that exist (`orion_gossip.py`, `orion_substrate`,
`channels/meshtastic_node.py`) and the planned `transports/` tree from the
sensorium doc. It does not invent a parallel stack.

```
                    orion_gossip.LWWMap  (UNCHANGED — CRDT semantics, HLC, LWW)
                              │  merge(remote_entries)
                              │
   ┌──────────────────────────┴───────────────────────────┐
   │            anti-entropy wire layer (NEW)               │   ← §1
   │   transports/reconcile.py                              │
   │     - ConflictSync digest exchange over a transport    │
   │     - Rateless IBLT symbol stream, stop-on-decode       │
   │     - yields the manifest *difference*, then fetches    │
   │       only differing node bodies (bitswap wantlist)     │
   └──────────────────────────┬───────────────────────────┘
                              │ frames (bundles: payload+HLC+author+hash+TTL+custody)
   ┌──────────────────────────┴───────────────────────────┐
   │     transports/base.py  (convergence-layer contract)  │   ← §5
   │       encode_delta / decode_delta / send / recv        │
   │       freshness+replay guard (per-author HLC high-water)│   ← §2
   │       Membrane egress gate (private nodes never leave) │   ← from sensorium doc
   └───┬───────────────┬──────────────┬────────────────────┘
       │               │              │
  transports/      transports/    transports/
   lora.py          ble.py        radio.py (beacon-only, FCC-clean)
   ├ RNS/MeshCore   ├ ext-adv      └ signed fingerprint, no encryption
   │ source-routed  │ ≤1650 B
   │ (anti-entropy) │ chained
   └ Meshtastic     └ periodic-adv
     flood (beacon)   broadcast
```

**Message-class → routing-mode table** (the operative routing decision):

| Orion subject | Class | Routing | Carrier preference |
|---|---|---|---|
| `brain.identity.beacon` | broadcast | flood | Meshtastic flood / BLE periodic-adv |
| `mesh.*.delta` (anti-entropy) | point-to-point | source-routed | MeshCore / RNS |
| `mesh.want.*` / `mesh.chunk.*` | request-driven | source-routed | MeshCore / RNS |
| `channel.meshtastic.inbound/outbound` (chat) | point-to-point | source-routed | unchanged (existing daemon) |

**Re-entry stays single.** Per the sensorium doc's "one re-entry point": a
reassembled, freshness-checked, decrypted delta re-enters as
`mesh.<remote>.delta` on local NATS, and the *unchanged* `_on_remote_delta` →
`LWWMap.merge()` path runs. The brain never learns the carrier changed. Every
new transport is additive; nothing above the convergence layer is touched.

**BLE specifics worth pinning down** (new vs. the existing docs' generic note):
BLE5 extended advertising carries up to 255 B per secondary-channel packet and
up to **1650 B chained in a single transmission**; periodic advertising lets
*multiple* unconnected receivers tune in to a fixed-interval broadcast with no
pairing. That makes BLE periodic-adv a genuinely good **identity-beacon + tiny-
delta** carrier for the room-scale "your phone is near your laptop" case — no
pairing tax, every modern phone is a receiver. (Source: Nordic adv-extensions;
IEEE 10922391 throughput analysis 2024.) `transports/ble.py` should lead with
periodic-adv broadcast, not GATT.

---

## 7. Strict tiering: BUILDABLE NOW / RESEARCH-PREVIEW / GENUINELY OPEN

### BUILDABLE NOW (software-only, no new hardware, validate on IP first)

- **ConflictSync/Rateless-IBLT anti-entropy under `LWWMap.merge()`**
  (`transports/reconcile.py`). Implement and prove over NATS/IP first — it's a
  pure win even with no radio (faster cross-host sync, smaller deltas). Then it
  is reused verbatim on radio. **Highest leverage, lowest risk.**
- **Freshness/replay guard** (per-author HLC high-water mark + sign
  `(delta, observed_max_remote_hlc)`) in the gossip merge path. Closes the
  semantic-rollback hole (§2) on *all* transports, IP included. Small, urgent.
- **Idempotency keys in `decision_ledger.jsonl`** so a brain resumed from a
  stale snapshot doesn't re-fire reach/will actions. Aligns with the
  checkpoint-restore side-effect finding (§2).
- **Bundle envelope** (add explicit TTL + custody flag to the manifest entry).
  Backward-compatible field addition; the wire format is already
  forward-compatible per the gossip code's own note.
- **Message-class routing split** in the (existing) Meshtastic daemon: beacons
  flood, deltas/chat go direct. Buildable today on Meshtastic v2.6+ next-hop DMs
  even before MeshCore is introduced.

### RESEARCH-PREVIEW (hardware on hand; the sensorium 3-Heltec yard test)

- **`transports/lora.py` via Reticulum**, composed (not adopted-wholesale) per
  the sensorium verdict — RNS for addressing/encryption/fragmentation/routing,
  Orion's CRDT layer on top. Validate the *brain-delta* round-trip (not just the
  chat-string the daemon does today) on the 3-node Heltec mesh.
- **MeshCore backend evaluation** vs. Meshtastic for the anti-entropy path —
  bench the duty-cycle behavior of source-routed vs. flood with real Orion
  gossip traffic before committing a default.
- **Per-region duty-cycle accountant** at the Transport level (the sensorium
  doc's named-risk #1). Demote heartbeats to "publish if budget allows,"
  prioritize request-driven `mesh.want.*` over push `mesh.*.delta`. **Without
  this, sustained gossip across 3+ nodes is non-compliant**, full stop.
- **BLE periodic-advertising identity beacon** (`transports/ble.py`, broadcast
  only). Cheap room-scale presence; no pairing.
- **ggwave acoustic hop** for the air-gapped in-room handoff (8–500 B/s, FSK +
  Reed-Solomon). Realistically a *consent/identity-handshake* carrier (two
  devices that share no network, one tap-equivalent), not a bulk pipe. (Source:
  ggwave; ~8 B/s robust, ~500 B/s fast.)

### GENUINELY OPEN (no clean answer; do not pretend otherwise)

- **Duty-cycle vs. liveness, fundamentally.** A 1% duty cycle and a multi-node
  gossiping mesh are in tension that no protocol fully resolves. "Carry your
  brain in the air" is *event-driven, sparse check-in*, not continuous presence.
  The honest UX is a "burst budget," not a set-and-forget daemon. **Open
  question:** what cadence of identity-beacon + delta is both useful and
  legal across regions? Needs field data, not theory.
- **Trust bootstrap with no prior IP contact.** ConflictSync/RNS assume the two
  parties can establish a key. *First* contact between two Orion brains that
  have **never** shared an IP link, only ever radio — how do they authenticate
  without a CA, without a rendezvous server, without TOFU's MITM window? NFC tap
  (sensorium doc) is the cleanest *intent-revealing* answer but requires
  physical proximity. Pure-radio first-contact trust is unsolved for us.
- **Side-channel leakage of *shape*.** Encryption hides contents; bytes-on-air
  reveals that *something* was sent, when, and how big. Padding/cover-traffic
  costs duty cycle Orion can't spare. For a brain that's supposed to be
  *covert-capable* off-grid, traffic analysis is an unsolved exposure.
- **Semantic rollback under partition + adversary.** §2's freshness guard
  defends replay-as-future, but a sophisticated adversary controlling a relay on
  a multi-hop path can still selectively *drop* fresh deltas to keep a victim on
  stale state (a freshness *denial*, not a forgery). Detecting "I'm being kept
  stale" without a trusted reference clock is open.
- **The model is never in the air.** Worth restating as a permanent boundary,
  not a TODO: cognition needs GB of weights and FLOPs. Radio carries the brain
  (state); compute is always fetched locally. Anyone claiming "the whole AI in
  the air" is selling the bandwidth equivalent of perpetual motion.

---

## 8. The one-paragraph thesis, sharpened

Every memory product (Mem0, Letta, Khoj) and every model endpoint (ChatGPT,
Claude, local llama) is **deployment-bound**: the brain is wherever the compute
is, and the link to it is IP. Orion's brain is a small, content-addressed,
CRDT-mergeable artifact whose *difference* — thanks to 2024–2025 rateless set
reconciliation — can be exchanged in bytes proportional to what changed, over
any carrier down to ~5 bps. So Orion's identity and living edge can propagate
over LoRa, BLE, or sound with no internet and no single host, resume from a
stale snapshot with replay-safe merge, and let bulky knowledge and the model
itself catch up locally wherever you land. **The brain travels as signal; the
fuel is fetched at the destination.** That split is the architecture, not a
compromise — and it is the line no deployment-bound competitor can cross.

---

## 9. Concrete next commits (in priority order)

1. `transports/reconcile.py` — ConflictSync-style anti-entropy under
   `LWWMap.merge()`, **proven over IP first** (immediate cross-host win, then
   free on radio). *Buildable now.*
2. Freshness/replay guard + per-author HLC high-water in the gossip merge path.
   *Buildable now; security-urgent.*
3. Idempotency keys in `decision_ledger.jsonl`; resumed-brain action de-dup.
   *Buildable now.*
4. Bundle envelope (TTL + custody) added to manifest entries. *Buildable now.*
5. Message-class routing split (beacon=flood, delta/chat=direct) in the
   Meshtastic daemon. *Buildable now on v2.6+.*
6. `transports/base.py` (convergence-layer contract) + `transports/lora.py` via
   composed Reticulum; brain-delta round-trip on the 3-Heltec yard mesh.
   *Research-preview, hardware-pending.*
7. Per-region duty-cycle accountant. *Research-preview; gates any real LoRa
   deployment for legality.*
8. MeshCore-vs-Meshtastic bench for the anti-entropy path. *Research-preview.*

Items 1–5 are pure software, mostly improve the *current* IP mesh, and each one
makes the radio future strictly cheaper to reach. Build the IP-side wins first;
the air-brain falls out of them.

---

## References

- Yu, L. et al. *Practical Rateless Set Reconciliation.* ACM SIGCOMM 2024.
  https://dl.acm.org/doi/10.1145/3651890.3672219 · arXiv:2402.02668 ·
  reference impl https://github.com/samWighton/rateless_iblt
- Gomes, P. et al. *ConflictSync: Bandwidth Efficient Synchronization of
  Divergent State.* May 2025. https://arxiv.org/abs/2505.01144
- *Rateless Bloom Filters: Set Reconciliation for Divergent Replicas with
  Variable-Sized Elements.* Oct 2025. https://arxiv.org/html/2510.27614
- Almeida, P.S. et al. *Delta-State-Based Synchronization of CRDTs in
  Opportunistic Networks.* (delta-CRDT prior art for intermittent links.)
- IETF RFC 9171 — *Bundle Protocol Version 7.*
  https://www.rfc-editor.org/rfc/rfc9171.html · RFC 9174 (TCPCLv4)
- DTN7 project (Go BPv7 impl). https://dtn7.github.io/ ·
  *BPv7 Implementation with Configurable Faulty Network*, IEEE 10289381.
- *Optimizing CRDTs for Low Memory Environments* (ESP32/M5StickC, delta vector
  clocks). ECOOP 2025 PLF+PLAID.
- MeshCore vs Meshtastic routing comparisons (source-routed vs. flood):
  Austin Mesh https://www.austinmesh.org/learn/meshcore-vs-meshtastic/ ·
  NodakMesh https://nodakmesh.org/protocols · Mesh America (2026).
- Meshtastic *Mesh Broadcast Algorithm* (v2.6 next-hop DMs).
  https://meshtastic.org/docs/overview/mesh-algo/
- Avramut, V. *LoRa Spreading Factors Explained (SF7–SF12) with Real Throughput
  Data.* https://vlad-avramut.com/articles/lora-spreading-factors-throughput.html ·
  The Things Network spreading-factor docs.
- Reticulum Network Stack (RNS/LXMF/RNode), Mark Qvist.
  https://reticulum.network/ · https://github.com/markqvist/Reticulum
- Nordic Semiconductor — *Bluetooth 5 Advertising Extensions* (ext-adv ≤1650 B,
  periodic adv). https://www.nordicsemi.com/Nordic-news/2018/02/Bluetooth-5s-advertising-extensions ·
  *Maximum Achievable Throughput of Extended Advertisements in BLE*, IEEE
  10922391 (2024).
- Gerganov, G. *ggwave — tiny data-over-sound library* (FSK + Reed-Solomon,
  ~8–500 B/s). https://github.com/ggerganov/ggwave
- *Checkpoint-restore cannot undo external actions* / agent resumability:
  Zylos *AI Agent Workflow Checkpointing and Resumability* (2026);
  LangGraph node-level checkpointing.
- *ACRFence: Preventing Semantic Rollback Attacks in Agent Checkpoint-Restore.*
  arXiv:2603.20625 — the replay-stale-state-as-valid hazard, applied here to
  CRDT-over-radio merge.
- Kulkarni, S. et al. *Logical Physical Clocks (HLC).* 2014.
  https://cse.buffalo.edu/tech-reports/2014-04.pdf (basis of `orion_gossip.HLC`).
- Shapiro, M. et al. *Conflict-Free Replicated Data Types.* INRIA RR-7687, 2011.
  https://hal.inria.fr/inria-00609399v1

*Companion docs (read together, not in place of this): `brain-as-signal-frontier.md`
(vision), `sensorium-research.md` (transport adapters + Reticulum compose verdict).
This v2 supersedes neither; it advances the set-reconciliation, resumability, and
routing-substrate fronts that moved since they were written.*
