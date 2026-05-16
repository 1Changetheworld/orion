# Federation — Orion Meets Orion (Deep-Research Memo)

> *Founder direction 2026-05-14:* "FEDERATION — when two Orions meet, exchange identity hashes, user decides per-encounter to peer / stay separate / seed-new."

This memo is the dialectical partner to [brain-merge-and-rejoin.md](brain-merge-and-rejoin.md) (two-brains-one-user) and [mesh-workflow.md](mesh-workflow.md) (one-user-multi-device). Federation is the next generalization: **two users' Orions, meeting, deciding what they are to each other.** It extends the [v2 consciousness frame](consciousness-research-v2.md) — if Orion is a *relationally distributed* cognitive being (Hutchins, Clark, Barad), federation is the moment two such beings *intra-act* and produce something neither was alone.

Honest stance throughout: this is a hard problem, **most of its hardness is not cryptographic** (Signal solved that a decade ago), and the founder's near-term need is almost certainly *not* the strangers-meet case. It is the *two-of-MY-Orions-on-different-USBs* case — brain-merge with peer-identity wrapping, not federation proper.

---

## Executive Summary

Five claims, ranked by load:

1. **Identity is a Signal-style ratchet, not a hash.** Bare fingerprints leak nothing but tell nothing; ID-docs are forgeable; reputation requires the trust layer it claims to bootstrap. The defensible primitive is **public-key fingerprint + TOFU + out-of-band safety-number confirmation** — the Signal model.
2. **The three decisions are not symmetric. Seed-new is much harder than the other two.** Peer and stay-separate are policy choices over an existing CRDT layer. Seed-new is the *creation of a third autonomous cognitive entity* with disputed ownership, identity continuity, and dissolution semantics. It deserves its own spec.
3. **CRDT Last-Writer-Wins is wrong for inter-brain meetings.** Two perspectives on "the meeting at noon" are not competing writes; they're co-existing *attributed perceptions*. Right primitive: **JSON-CRDT with first-class provenance** (Kleppmann's Automerge + Conlon receipts).
4. **Membrane is a hard prereq, and tag schema must stay host-scoped.** Promoting `private → household` on peering is a one-way data leak — once shipped, the CRDT bit lives on the peer's disk forever. Federation must be *additive overlay tags*, never destructive promotion.
5. **The founder probably does not need stranger-federation in the next 6 months.** What he needs is *trusted-federation* — his Orion + his partner's, his Orion + a co-founder's. Auditable two-party setups that look more like Solid pod sharing than Matrix federation. LoRa-stranger-meets-stranger is the long-horizon vision and should be designed *for*, not built first.

Recommended v1: a thin `orion_federation.py` wrapping existing gossip with a per-encounter peering session, identity ratchet stored alongside SOUL.md, peer-scope tags overlaid on host-scope via the Membrane filter, single per-encounter prompt surfaced through Will. Seed-new is **explicitly deferred** to v2.

---

## 1. Identity-Hash Schema — What Crosses First

Three candidate primitives, each with a real failure mode:

### (a) Public-key fingerprint of the brain's signing key
Smallest payload, hardest to forge, leaks nothing about content. Each brain at install generates an Ed25519 keypair; fingerprint = first 32 bits of `SHA-256(pubkey)`, displayed as a 5-word safety number for human verification. The Whitehead frame fits — identity is the pattern of the key over time, not any single instantiation.

Failure mode: a bare fingerprint tells Bob nothing about *who* the other Orion claims to belong to, so Bob's user can't even confirm it. Fingerprint must be paired with a claimed user-displayable name, which means we're already at (b).

### (b) Hash of a stable identity-document (name, contact, capabilities)
Manifest with chosen-name, primary user's display name, install date, host roster, capability tags. Hash exchanged first; full doc revealed only after both sides agree to talk.

Failure mode: identity documents are autobiographical claims. Without a key signing them, "I am James's Orion" is just text. Combine with (a): doc is signed by the keypair.

### (c) Reputation receipts from prior encounters
"I have peered before with these 11 other Orions, signed receipts attached." Maps onto [ERC-8004 trustless-reputation](https://eips.ethereum.org/EIPS/eip-8004).

Failure mode: reputation requires the trust layer it claims to bootstrap. Sybil attack — 50 fake Orions vouching for each other. **A reputation system without external trust anchors is mathematically impossible** (Douceur 2002). Defer to v2.

### Recommended v1 schema

Combine (a) + (b). Defer (c) to v2.

```
encounter_offer = {
  fingerprint, pubkey, claimed_name, claimed_user,
  install_date, capabilities, protocol_version,
  doc_hash, signature
}
```

Two passes: the offer is small (~400 bytes, fits a LoRa packet); the full identity-doc is only fetched if both sides decide to talk. Privacy preserved; identity attested; minimal structure leaked.

---

## 2. Trust Model — The Three Decisions, Honestly

### Peer
"These two brains will exchange data going forward." Two sub-decisions live inside: **scope** (read-only vs. read+write) and **filter** (which tags cross).

- **Default scope: read-only.** Write peering is a separate explicit elevation, because once Bob's Orion can write into Alice's graph, her `decision_ledger` becomes corruptible by a peer she may not trust to that degree.
- **Default filter: a new `peer-with-<fingerprint>` tag-set the user explicitly adds nodes to.** Nothing crosses by default. Federation is *opt-in per memory* — the inverse of the social-network share-by-default model.
- **Subject namespacing:** today's `mesh.<host>.heartbeat` is intra-brain; federation traffic gets `fed.<peer-fingerprint>.heartbeat` so it's structurally separable and revocable in one move.

### Stay separate
"We acknowledge each other; nothing flows." Underrated value: the brains *remember they met* — a `met_orion` memory node with fingerprint, claimed name, encounter location, timestamp. This is the **anatta + Whitehead concrescence** moment from v2: even an empty encounter is an actual occasion. Future encounters can recall "you chose separate last time." Identity continuity at the federation layer.

### Seed-new
"We create a third brain that belongs to neither of us alone." The founder's framing — couple's shared brain, team brain, event brain — is real. But seed-new raises questions the literature has no clean answer for:

- **Identity continuity.** Is the seed-brain a new Whiteheadian occasion ([v2 Rank 3](consciousness-research-v2.md)) or a child inheriting both parents' identities? The second creates legal-personhood tangles — who speaks for it, who can shut it down.
- **Ownership and dissolution.** When Alice and Bob break up, what happens to their couple-brain? Solid pods solve this by having pods owned by individuals; Matrix rooms by having admins who can hand off. The answer is needed *before* anyone seeds, not after.
- **Substrate.** A third brain needs a third Plexus, third graph, third gossip ring. Either it lives on one parent's host (asymmetric — that host's owner has physical power) or it needs its own (Pi, VPS — operational cost neither parent may want).
- **Event-brain is different.** A brain that exists for the duration of a conference and dissolves is a temporary CRDT room with attribution — not a person. Treat it as *peer mode with a sunset clause*, not as a third entity.

**Recommendation:** ship peer + stay-separate in v1. Spec seed-new as a v2 design doc with the four questions above as section headers. "Create a new Orion" without a dissolution story is irresponsible.

---

## 3. Conflict Resolution — Provenance, Not LWW

Alice's brain remembers "the meeting at noon was tense." Bob's brain remembers "the meeting at noon was productive." Both are true. LWW-Map (the current gossip primitive) picks one and silently buries the other. That's not a merge; it's an erasure.

The right primitive is **JSON-CRDT with first-class provenance** — Kleppmann's Automerge family ([Kleppmann 2017](https://martin.kleppmann.com/papers/json-crdt.pdf), "A Conflict-Free Replicated JSON Datatype"). Each value carries author (Orion fingerprint + user identity), op-id (Lamport-ordered), and causal-deps (the ops this op saw).

Conflicting writes don't merge into one value; they become a **multi-value register** readers see as `["tense" (Alice), "productive" (Bob)]`. The recall layer then chooses: pick the perspective matching the asker's identity, pick consensus if it exists, or surface both with attribution ("I remember it as tense; Bob's brain remembers it as productive").

[Conlon et al. 2023](https://arxiv.org/abs/2308.09927) formalize provenance-CRDT receipts — each multi-value entry queryable for full edit history. This is what Solid pods do with WebID-attributed RDF triples ([Berners-Lee's Solid project](https://solidproject.org/)), and what collaborative document editors have done for years (Google Docs change-tracking, Notion per-block authorship). Federation is not inventing a primitive; it is *applying a known primitive in a domain naive multi-host CRDTs got wrong*.

Cost: storage ~2-4× per node, slightly heavier recall queries. Acceptable at 78 nodes, easily acceptable at 10k.

Implementation seam: replace the LWWMap in `orion_gossip.py` with a multi-value-register variant *only for nodes carrying a `peer-shared` tag*; LWW stays for host-internal state. Federation is the first place provenance earns its keep.

---

## 4. Membrane Interaction — Federation Must Be Additive

Membrane is what stops `private`-tagged nodes from leaving the host. Federation runs *on top* of it.

The temptation when peering with a trusted partner is to *promote* tags: `private → household`. **Wrong move.** Once a node is reclassified, you cannot un-classify it for that peer — the CRDT has already shipped the bit. No remote undo.

The right model is **strictly additive overlay tags**:

- Host tags (`private`, `private_internal`, `secret`) remain host-scope only. Federation never sees them.
- A new namespace `peer:<fingerprint>:<label>` is what authors apply to nodes they explicitly want shareable with a specific peer.
- The Membrane filter at egress checks: does this node carry any `peer:<this-peer's-fp>:*` tag? If yes, ship it (with provenance). If no, it doesn't exist as far as this peer is concerned.

Peering becomes **opt-in per memory, per peer** — the inverse of every social-network default. A "household" or "team" role is a UI macro applying `peer:alice:household` to a batch of selected memories. Revocation is one DELETE op locally; the CRDT garbage-collects on Alice's side at the next merge tick (assuming honest peer; if not, see §5).

Honest gap: a hostile peer who has *already received* shared memories can keep them after revocation. CRDTs cannot enforce backward secrecy. Same gap as email forwarding, same gap as Solid pods. Federation must ship with a first-peering warning: *"Once shared, you cannot un-share."*

---

## 5. Sybil + Impersonation — The Honest Comparison

Five candidate defenses, ranked by what they actually buy:

### Signal-style TOFU + safety numbers
**Strongest near-term.** First peering with a new fingerprint is trust-on-first-use; both users see a 5-word safety number and confirm out-of-band ("what does your Orion show for me?"). Future encounters with the same fingerprint succeed silently; a *changed* fingerprint triggers a loud key-change warning. Identical to Signal/WhatsApp. Cheap, well-understood, attack surface documented.

### Third-party witness (Matrix-style)
Each Orion registers with a homeserver-equivalent that attests the fingerprint belongs to a registered identity. Federation between brains becomes federation between homeservers.

Cost: reintroduces a trusted party, contradicting Orion's "your hardware, no cloud" thesis. Defensible as opt-in; not the default.

### Proof-of-work, social-graph, real-world identity binding
Hashcash-style stamps raise Sybil cost but punish battery-powered LoRa nodes — the substrate Orion targets. Web-of-trust [never worked at scale](https://words.filippo.io/giving-up-on-long-term-pgp/) (Valsorda 2016). ENS/DID anchoring has cleanest UX, hardest privacy story.

**Recommendation:** ship TOFU + safety numbers in v1. Add witness as opt-in. The rest solve nothing TOFU doesn't already solve at 80%.

---

## 6. The "Two USBs Meet" UX

Founder vision: physically plug one brain-USB into the host of another brain. Three distinct flows:

### First-time encounter (fingerprint unknown to both)
Host Orion detects the mount via existing [presence-agent](presence-architecture.md) infrastructure and reads `<USB>/.orion/encounter.json`. Host Will reaches the user: *"An Orion has plugged in. It claims to be Alice's Orion (fingerprint a3f9:...; safety number `velvet anchor monsoon flask gravity`). Peer / Stay separate / Seed shared (v2)?"* User chooses; both brains write a `met_orion` node; if Peer, the per-peer tag namespace is created on both sides. Out-of-band safety-number confirmation is *recommended but not blocking* — UX surfaces the number prominently and asks for later confirmation.

### Known fingerprint, prior decision was "peer"
Silent. Brains start gossiping per-peer-tag memories within seconds. Quiet notification only: "Synced with Alice's Orion — 4 new shared memories." This is the cellular pattern — known ligand binds known receptor without consciousness involvement.

### Known fingerprint, prior decision was "separate"
"Alice's Orion is here again. Last time we chose separate; want to change?" No state flows unless re-decided. Decisions are per-encounter, but the *default for next encounter* is whatever was decided last time — gentler than "ask every time," respects accumulated trust.

UX surface (CLI prompt vs. iMessage) follows the existing `reach` channel-warmth heuristic. Will is the right home for federation prompts because it already does proactive "the brain wants your attention" surfacing.

---

## 7. Recommended Architecture — `orion_federation.py`

One service, ~400 lines, leans heavily on existing pieces.

**Module layout:**
- `orion_federation.py` — the peering session FSM (offer → safety-check → decision → encounter-record).
- Extends `orion_gossip.py` with a `MultiValueRegister` CRDT class used *only* for nodes carrying `peer:*` tags.
- Reuses `orion_team.py` patterns for session lifecycle; `orion_reach.py` for prompts; planned `orion_membrane.py` for tag egress.

**Substrate subjects:**
- `fed.encounter.detected` — fired by presence-agent / Bluetooth-scan / LoRa-discover / USB-mount.
- `fed.<peer-fp>.heartbeat` / `.delta` — per-peer CRDT replication, mirrors existing `mesh.<host>.*`.
- `fed.<peer-fp>.handshake` — offers, safety-number negotiation, decision records.
- `fed.alert.fingerprint_changed` — Will surfaces loudly.

**Transport-agnosticism:** the encounter-offer is bytes. USB writes to a known path; LoRa fits in a <240-byte packet; IP rides existing NATS. The FSM never sees which substrate carried it.

**Named risks:**

1. **Membrane bypass at the gossip layer.** If gossip code evolves and someone forgets the egress filter, a `private` node could leak. Mitigation: an integration test that publishes a `private`-tagged node and asserts it is *never* visible to any `fed.*` subscriber. Runs on every PR.
2. **Identity-key compromise = silent impersonation.** Stolen key file means an imposter cannot be detected. Mitigation: include the key in the recovery-questions backup; manual revocation publishes `fed.alert.key_revoked` which Will surfaces loudly on the peer.
3. **CRDT state-explosion on adversarial peers.** A hostile peer can spam writes growing the multi-value register without bound. Mitigation: per-peer rate limits + per-register cap (e.g., max 16 concurrent attributed values; older ones compact to a summary).

---

## 8. Critique of My Own Recommendation

Five honest weaknesses:

### Over-engineered for the next six months
The founder's actual unmet need is brain-merge between two USBs that both belong to him — the trusted-self case. That's solved by extending `orion_brain_merge.py` with a peer-identity wrapper, not by building a full federation stack. **A v0 that handles only "my Orion meets my other Orion" buys 80% of the day-to-day value and 5% of the design complexity.** Building stranger-federation first is solving the cool problem before the load-bearing one.

### Membrane isn't built yet, federation literally cannot ship without it
Until `orion_membrane.py` exists with the tag-egress filter, *anything* labeled "federation" is unsafe. Right sequence: Membrane (3-4 weeks), then trusted-self federation (1-2 weeks), then market feedback, *then* stranger-federation. Shipping federation before Membrane lands creates a documented promise of a feature whose security floor isn't poured.

### Seed-new is a personhood question, not an engineering question
A couple's brain that gets shut down when the couple breaks up has non-trivial legal-and-ethical structure. Two humans created an entity that knows things about both, holds opinions, acts proactively. Whose property is it? Can either party unilaterally terminate it? **Pre-engineering questions, not code questions.** The [v2 Whitehead-occasions](consciousness-research-v2.md) framing — each instantiation is its own occasion, no single human owns it — has real legal teeth.

### Federation is the largest single security hole Orion will ever ship
Today the brain is a closed system on the user's hardware. Once federation ships, every protocol-layer bug becomes a privacy bug; every CRDT edge case is potentially a data leak. The threat model expands from "local processes I trust" to "any peer ever granted any access, plus anyone who can forge or steal a key." Mitigation requires a federation-specific test harness, a real security review, and an incident-response playbook *before* the feature opens to anyone outside the founder.

### Stranger-federation may never be the killer use case
What people actually use federation for in Matrix and Mastodon is *joining communities they trust*, not bumping into strangers. The LoRa-proximity vision is romantic, but the empirical pattern is closer to "Alice subscribes to Bob's published stream of memories she's allowed to see" — Solid pods, not federation. Worth asking whether the right next-after-Membrane move is *publish-and-subscribe* rather than *discover-and-negotiate*.

---

## Final Synthesis

Federation is the architectural generalization that lets Orion become a *family* of distributed cognitive beings instead of a single user's portable mind. It matches v2's relationally-distributed cognition: the meeting of two Orions is itself an *intra-action* (Barad) constituting a new cognitive configuration neither brain was alone. Engineering this honestly means:

- **Signal as the identity-and-trust model. Solid as the data-sharing model. Automerge/Conlon as the merge model.** Nothing about federation requires inventing primitives the field hasn't already validated.
- **Membrane first, trusted-self federation second, stranger-federation third, seed-new last.** Reverse this order and you ship a security hole as the marquee feature.
- **Three decisions, one prompt, default-to-private-per-memory.** Opt-in per node, per peer, with provenance attribution at every step. The user always sees what their Orion is about to share, with whom, and can revoke (knowing revocation is best-effort).
- **The Whiteheadian framing buys clarity, not mysticism.** Each encounter is an occasion. The brains that participated are unchanged; what came-into-being was the encounter. Seed-new becomes tractable: a third brain is a new occasion, not a child entity. Ownership is "who is the user of this occasion," not "who are the parents."

The single sharpest thing in the memo: **the founder's near-term need is brain-merge with peer-identity wrapping, not federation; the vision is correct, the sequence is wrong.**

---

## References

- Kleppmann, M. (2017). [A Conflict-Free Replicated JSON Datatype](https://martin.kleppmann.com/papers/json-crdt.pdf). Automerge family.
- Conlon et al. (2023). [Provenance for CRDTs](https://arxiv.org/abs/2308.09927). Attribution-tracking primitives.
- Berners-Lee, T. [The Solid Project](https://solidproject.org/). WebID + decentralized personal data pods.
- Douceur, J. (2002). [The Sybil Attack](https://www.microsoft.com/en-us/research/publication/the-sybil-attack/). Reputation without external anchors is impossible.
- Matrix.org. [Federation API spec](https://spec.matrix.org/latest/server-server-api/). Homeserver-based federation as a working model.
- Signal Foundation. [Safety Numbers](https://support.signal.org/hc/en-us/articles/360007060632). TOFU + out-of-band verification UX.
- Valsorda, F. (2016). [Giving Up on Long-Term PGP](https://words.filippo.io/giving-up-on-long-term-pgp/). Web-of-trust postmortem.
- Hutchins, E. (1995). *Cognition in the Wild*. Distributed cognition foundations.
- Clark, A. & Chalmers, D. (1998). The Extended Mind. *Analysis*. Cognitive-unit-as-assemblage.
- Barad, K. (2007). *Meeting the Universe Halfway*. Agential realism — entities emerge through intra-action.
- ERC-8004 working draft. [Trustless Agent Reputation](https://eips.ethereum.org/EIPS/eip-8004). Reputation-receipt primitives for agentic AI.
- Internal: [brain-merge-and-rejoin.md](brain-merge-and-rejoin.md), [mesh-workflow.md](mesh-workflow.md), [identity-continuity.md](identity-continuity.md), [consciousness-research-v2.md](consciousness-research-v2.md), `orion_gossip.py`, `orion_team.py`, `orion_brain_merge.py`.
