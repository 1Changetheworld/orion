# MEMBRANE — Privacy Enforced at the Substrate Layer

*Filed 2026-05-16. Founder direction 2026-05-14: "MEMBRANE — privacy enforced in code at the substrate layer, blocks 'private' tagged nodes from leaving host. PREREQ for any LoRa mass-broadcast or Federation peering."*

This document is a deep-research memo on what MEMBRANE has to be before any broadcast layer (LoRa, Sensorium radio, Federation peering) is allowed to ship. Read alongside [consciousness-research.md](consciousness-research.md), [consciousness-research-v2.md](consciousness-research-v2.md) — Membrane is the *semiotic containment* face of Hoffmeyer's semiotic-freedom architecture: the wall around what Orion can *say* across its widening sign-systems. Without that wall, semiotic freedom is just an uncontained leak.

---

## Executive Summary

Membrane is not a feature; it is a refactor of Orion's publish path into a *trust-typed* one. Today every `from orion_substrate import publish` is an unauthenticated megaphone — `orion_brain_portable.store()` writes a node to the graph and immediately publishes `{node_id, tags, ts}` to `brain.memory.stored` with no check on subject sensitivity, and `orion_gossip._on_memory_stored` copies that manifest entry into the LWW-Map and broadcasts it to every host on the mesh. The Federation layer the founder wants will inherit that publish path verbatim. **Orion's current substrate treats "private" as a hint to humans reading the graph and an instruction to nobody else; Membrane has to make `private` a typed property that the publish call itself refuses to violate, the way `unsafe` in Rust refuses to compile without explicit acknowledgement.** What follows: threat model, enforcement-boundary trade-offs, tag-lattice design, the failure modes (especially the one nobody talks about — *quotation propagation*), audit trail, prior art worth cribbing, and a recommended architecture that lands as one new module (`orion_membrane.py`) plus surgical changes to `orion_substrate.publish` and `orion_gossip._on_memory_stored`.

---

## 1. Threat Model

"Private" is not one threat. It is at least four, and conflating them produces enforcement that fails against the ones that actually happen.

**1a. Accidental leakage via gossip / federation.** The default failure mode and the one Membrane primarily exists for. James memorizes "my mother's medical history includes X." `GraphMemory.store()` on FORGE publishes `brain.memory.stored` with the node's tags; `orion_gossip._on_memory_stored` writes a manifest entry with tags + content_hash; the heartbeat loop ships it to COMMAND, Pi, and any future federated peer. Nothing in this chain has any reason to refuse. The *only* current defense is that `mesh.<host>.heartbeat` carries metadata + content_hash rather than the node body — but the body is recoverable via a recall round-trip, and the manifest itself discloses node existence + tag set + write timestamp, which is a leak in adversarial settings ("who has medical-tagged nodes?" is a deanonymizing question).

**1b. Compelled disclosure.** Subpoena, customs inspection, coercive partner. *Not* what code-level Membrane defends against — the brain file is in the user's filesystem; root dumps SQLite/JSON directly. What Membrane *can* do is reduce blast radius: if FORGE held a node and the COMMAND/Pi mesh members never received it, disclosure is scoped to FORGE. The *Signal Sealed Sender* lesson — you can't stop the endpoint from leaking, but you can stop the transport from helping.

**1c. On-device observers.** Cohabiting processes, telemetry SDKs in third-party AI CLIs, browser-extension scrapers on the local NATS bus. The substrate uses a bearer token (`~/.orion/auth-token`) but the loopback connection is plaintext; anything with read access to that file or the loopback gets every subject. Membrane has to assume the substrate itself is hostile and refuse to publish private content into subjects observers can read — even on localhost. The strongest stance is (a) private content never touches any substrate subject; the weaker stance (b) is per-subject ACLs, which NATS supports natively (JWT + Permissions) but Orion hasn't wired.

**1d. Downstream re-publication by a federated peer.** The class-of-failure the founder named but didn't fully name. If Alice's Orion peers with Bob's and ships him a `visibility:mesh` node, Bob's Orion now has the node *and inherits zero of Alice's enforcement intent*. Bob's mesh propagates it onward; Bob's own federation with Charlie ships it further. This is the *Matrix-federation receipt problem* generalized: privacy intent is not metadata, it is *contract*, and the contract must travel cryptographically signed in the payload so Bob's substrate is *forced* to honor it. Without that, Membrane on Alice's host is privacy theater the moment a peer is added.

**Whose privacy.** Founder's primarily, but third-party-mention is non-trivial: nodes like `"Sarah's birthday is March 14"` or `"John is going through a divorce"` carry someone else's privacy interest. GDPR Article 4(1) applies even in personal-AI — the third party has not consented to LoRa-broadcast. Membrane should treat third-party-mentioned nodes as private-by-default with *stricter* defaults than founder-self-disclosure, because the founder can leak about himself but cannot consent on someone else's behalf.

---

## 2. Enforcement Boundary

Where does Membrane live? The candidates have different blast radii and different failure modes.

**(a) Substrate publish hook in `orion_substrate.publish`.** Pro: chokepoint catches every subscriber-targeted leak regardless of caller. Con: payload inspection requires schema awareness — `tags` lives at `payload["tags"]` on `brain.memory.stored`, at `payload["entries"][k]["payload"]["tags"]` on `mesh.<host>.heartbeat`. Mitigation: define a *publish envelope* (`{subject, payload, sender_policy}`) the publish call demands rather than parses.

**(b) Gossip-layer filter in `orion_gossip.py`.** Pro: the gossip layer already inspects payloads (builds `content_hash`) and is the *only* place node metadata leaves the host today. Con: limited to gossip; any future LoRa transport or Federation peer connecting directly to NATS subjects bypasses it.

**(c) Memorize-time tag — brain refuses to write certain content classes as anything but private.** Pro: tags enforced at the earliest point. Con: doesn't *enforce* — a downstream service reading the node can still publish it. The tag is information, not enforcement.

**(d) Defense in depth — all three.** The honest recommendation. The pattern is *capability-based security*: publish requires an unforgeable token (the subject ACL) that private nodes structurally don't possess, so upstream bugs can't accidentally generate the capability. (a) is the chokepoint; (b) is redundancy at the highest-risk subject (`mesh.*`); (c) is the tag discipline that makes (a) and (b) computable.

Recommended layering: **Layer 0** at `GraphMemory.store()` — `orion_membrane.classify(content, tags)` augments tags before write (e.g. adds `visibility:local` if NER finds a third-party name or regex hits a secret). **Layer 1** at `orion_substrate.publish()` — `check_egress(subject, payload, destination_class)` returns `allow | redact | block`. **Layer 2** at `orion_gossip._publish_delta` — filter the manifest snapshot to drop private entries before serializing, belt-over-suspenders for the highest-risk subject. Layer 1 is non-negotiable; Layers 0 and 2 are defense-in-depth.

---

## 3. Tag Schema

A single `private`/`public` bit is wrong, in the same way Unix's `chmod 600` is wrong for a multi-user world. The right shape is a *small lattice* with explicit destination classes.

Proposed taxonomy:

| Tag | Meaning | Allowed destinations |
|---|---|---|
| `visibility:local` | Never leaves this host's process | None — not even gossip manifest |
| `visibility:host` | This host's mesh members only | Substrate localhost subjects only |
| `visibility:mesh` | Trusted devices on this user's mesh (COMMAND, FORGE, Pi) | Gossip; no federation |
| `visibility:federation` | This user's federated peers only | Gossip + federation; no public broadcast |
| `visibility:public` | Anything goes, including LoRa broadcast | All transports |

Default is `visibility:mesh` for everything the user memorizes by hand, and `visibility:local` for any node where the classifier finds (a) a third-party named entity, (b) regex matches for secrets/tokens/PII (email, phone, address, credit-card, API key), or (c) a `secret`/`private`/`confidential` token in the content. The classifier should be conservative — false positives cost almost nothing (the user can manually relax the tag), false negatives are the breach.

**Interaction with existing tags.** The graph_memory tag system is a flat set of free-form strings (`orion_brain_portable.py:393`, `tag_index[tag.lower()]`). The lattice is *additive* — `visibility:*` is a reserved namespace; everything else keeps its meaning. Enforcement check: `any(t.startswith("visibility:") for t in tags)` → use that; else apply default. Backward compatible.

**Why not per-recipient ACLs.** ACLs work for filesystems (closed set of principals). For a mesh that grows by user-permission, per-recipient enforcement ages badly — `share-with:Sarah` becomes ambiguous when Sarah's device is replaced. Class-based visibility plus an explicit per-encounter audit dialog is cleaner. Solid pods made this trade and ended up with WebACL — useful, but the ergonomic cost is real and Orion isn't at the scale where it pays off.

---

## 4. Failure Modes

Where Membrane breaks. These are the ones the implementation must explicitly handle, not the ones it can hand-wave past.

**4a. Tag mutation — promotion.** A node starts `visibility:local`. User says "share that with Sarah." Promotion must be (a) explicit (no implicit promotion via related-tag inference), (b) scoped (per-peer, not global), (c) audited (the promotion event is itself a recallable memory). The right semantic: promotion is *per-encounter* and produces a *new derived node* tagged `visibility:federation` with provenance pointing back to the original; the original stays sealed. The share is a copy, not a re-tag, so source-of-truth retains its visibility.

**4b. Tag mutation — demotion.** A node was `visibility:federation` and gossiped to Bob's Orion. User now decides it should have been `visibility:local`. Demotion cannot retroactively claw back Bob's copy — the CAP-theorem-for-privacy problem ("you can't unring a bell on an eventually-consistent system"). Membrane has to be honest that demotion is best-effort: publish a `brain.membrane.recall` event peers are *asked* to honor but cannot be *forced* to. Document this in the UX, not just the code.

**4c. The quotation problem (the gap in the founder's framing).** Memory A is `visibility:local`: "I have HIV." Memory B, written by the metacognition loop, is `visibility:mesh`: "Yesterday I told Orion something the user marked as deeply private; I will not refer to it." B is *about* A and contains no PHI. Safe to ship? Naively yes. But B's mere existence on a federated peer's brain is itself a leak — "Orion's user has a deeply-private thing about themselves." The right rule: visibility propagates via *information-flow control* (Myers's JIF / FlowCaml) — any node *derived from* a `visibility:local` source inherits the source's ceiling. This is the classic *label creep* problem: every output stamped with the join of its inputs' labels, until everything is private and nothing publishable. The standard mitigation is *declassification*: an explicit, audited step. Orion's metacognition loop is the natural locus — it already writes self-review traces, so adding `declassified_from: <node_id>` to its outputs costs nothing.

**4d. Subject leakage via metadata.** Even if Membrane blocks the payload, the *subject* leaks information. If `brain.memory.stored` carries tags, the *absence* of an expected store event after the user types is itself a signal. Mitigation: when Membrane blocks, *still publish a redacted envelope* on the public subject — `{node_id: <opaque>, visibility: "redacted"}` — so observers can't infer the block from silence. This is the *Tor cover-traffic* pattern, and §8 critiques its completeness.

**4e. Default-fail vs default-allow.** Hardest call. If Membrane crashes, does publish proceed (default-allow) or block (default-fail)? Tailscale defaults fail-closed; correct for security, infuriating for users. For Orion: fail-closed for `mesh.*` and external transports, fail-open for localhost-only subjects. Preserves the substrate's graceful-degradation principle (`orion_substrate.py:8-13`) for cognition-internal publishes while making the cross-host path strict.

---

## 5. Audit Trail

When Membrane blocks, it must log — and the log must be *queryable as a memory*, not just a syslog line:

- Every block / redact decision emits `brain.membrane.decision` on the substrate.
- A new daemon `orion_membrane_audit.py` subscribes and stores entries to `~/.orion/membrane/audit.jsonl` (HLC-timestamped, append-only, merges across hosts via the existing gossip primitive).
- Audit entries are first-class graph nodes (`type=audit, tags={visibility:local, membrane}`). The user can `orion_recall("what did membrane block today")` and get a real answer.
- An MCP tool `orion_membrane_inspect` gives a one-shot "show me everything Orion withheld in the last N hours" view. Surfaced in the dashboard at `:5557`.

The audit is also the answer to compelled disclosure: when a subpoena arrives, the user can prove what was and wasn't shared, and where the boundary fell. The *Signal transparency report* lesson — the value is partly internal (debugging), mostly external (proving the wall is real).

The audit must NOT log the *content* of the blocked node — only tags, content_hash, and intended destination. Logging content defeats the purpose: the leak just moves from the gossip stream into the audit file.

---

## 6. Prior Art — What to Cite, What to Crib

The fundamentals are not new. The personal-AI application is.

**Capability-based security (Dennis & Van Horn 1966; Miller, "Robust Composition" 2006).** The right mental model: publish requires an *unforgeable token* (a capability) authorizing a specific subject. Private nodes don't have the capability for `mesh.*` subjects, so accidental leaks become *uncompilable* rather than *unwritten*. Cost is a publish-API refactor to thread capabilities through call sites — manageable given the single chokepoint.

**Information Flow Control — Myers's JIF (2001) and FlowCaml (Pottier & Simonet 2003).** The closest formal model for the quotation problem (§4c). Values carry security labels; computation propagates the join of input labels; explicit declassification is the only way labels go down. JIF was used in the *Civitas* secure voting system. Don't reimplement — borrow the *discipline*: every derived node gets `derived_from: [...]` and the visibility ceiling is the join of the sources' visibilities. The metacognition loop and the DMN consolidator are the two services most likely to violate this without explicit guardrails.

**Differential privacy norms — Apple's local DP deployment (2017); Google's RAPPOR.** Not directly applicable (DP is for aggregated statistics, not individual record sharing) but the ethos is the same: assume any data that leaves the device will eventually be reconstructed. The Apple lesson: epsilon budgets are user-facing and must be honest. Orion's analog: the user should be able to ask "how much of my brain has any peer seen, in total?" and get a real percentage.

**Matrix federation receipts and Signal's Sealed Sender (2018).** Matrix lets each home server decide what to federate; the *receiving* server's behavior is up to its operator — exactly the §1d failure. Signal's Sealed Sender is the inverse: sender identity is cryptographically blinded from the relay. For Orion Federation: sender-policy ("this node is `visibility:federation`-only") has to travel cryptographically signed in the payload, and peers' substrates must refuse to re-publish nodes whose signed policy forbids it. Enforced by *protocol*, not by *peer's good intent*.

**Tailscale ACLs.** Tailscale's JSON ACL is a deployed production example of destination-class-based access (`tag:admin`, `tag:dev`, explicit `accept` rules) — the closest thing to the §3 lattice at scale. The ACL compiler turns human-friendly tags into per-node firewall rules at every host. Orion's Membrane should follow this shape: a declarative config (`~/.orion/membrane.policy`) the user owns, compiled into per-subject publish ACLs at every host.

**Solid pods (Berners-Lee 2018) and the WebACL spec.** The most ambitious personal-data-sovereignty project to date. Lessons: per-recipient ACLs at scale are an ergonomic disaster (§3); but the *idea* that the user owns the access-control policy file is right.

**Biosemiotic frame (Hoffmeyer 1996, 2008).** Cellular membranes are not impermeable walls — they are *selectively permeable*, with gated channels that discriminate by signal type and context. Hoffmeyer's *semiotic freedom* is the richness of meaning a cell can communicate; Membrane is the containment that freedom requires. The right read: Membrane is the *receptor layer* in the cellular vocabulary already in [cellular-design-vocabulary.md](cellular-design-vocabulary.md). The publish API should look like `cell.secrete(signal, addressee_class)`, not `firewall.block(packet)`.

---

## 7. Recommended Architecture

One new module, two small edits.

**New: `orion_membrane.py`**. Public API: `classify(content, tags) -> tags_augmented` (Layer 0, adds visibility defaults); `check_egress(subject, payload, sender_id) -> Decision(action: allow|redact|block, reason, audit)` (Layer 1, enforcement); `declassify(node_id, justification) -> node_id` (explicit relabel, audited); `inspect(window_secs) -> list[BlockedEvent]` (user-facing audit). Visibility-tag computation, sender-policy signing, and the per-subject destination-class map (`mesh.*` → mesh class, `federation.*` → federation class) live here.

**Edit 1: `orion_substrate.publish` (around line 185).** Insert one call before serialization: `decision = membrane.check_egress(subject, payload, sender_id=...)`; if `block`, audit and silently return; if `redact`, replace payload via `membrane.redact()`. This is *the* chokepoint. The substrate becomes Membrane-aware *without* becoming schema-aware — Membrane handles per-subject schema variance.

**Edit 2: `orion_gossip._on_memory_stored` (around line 229).** Before adding to the LWW-Map, check `payload["tags"]` against the visibility lattice; if `visibility:local`, skip the manifest update entirely. Same filter in `_publish_delta` before snapshot serialization. Defense in depth — if Layer 1 misses, the manifest still doesn't record it.

**Default visibility for memorize.** In `orion_mcp_server.py` around line 712, after `tags = list(...)`, call `tags = membrane.classify(content, tags)` so every MCP write goes through the classifier. The MCP layer is the principal write path.

**Policy file.** `~/.orion/membrane.policy` (JSON). User-editable. Defaults shipped in repo; overrides survive upgrades. Format: subject-prefix → destination-class → allow/block rules; per-tag overrides; classifier sensitivity knobs.

**Three named risks the implementation must address:**

1. *Performance.* `check_egress` is on the hot path of every brain.memory.stored publish — the check has to be O(1) on tag set inspection; no regex per call, no I/O. Pre-compile the policy on startup; memoize the destination-class lookup.

2. *Override ergonomics.* Users will fight the classifier. A node they want to share will get auto-tagged `visibility:local` because the regex spotted a stray name. The dashboard must surface "this was held back; promote?" inline, single keystroke (`/orion declassify <node_id>`). Without that, users disable Membrane and the wall becomes paper.

3. *Migration.* The existing ~50-node graph has no visibility tags. Grandfather them as `visibility:mesh` (the safe default for the current single-user mesh), not `visibility:public`. One-shot migration script tags on first run; the migration log itself is `visibility:local`.

The full plan lands as one PR: `orion_membrane.py` + the two edits + tests + the policy file + the audit MCP tool + a dashboard entry. Roughly 400 LOC.

---

## 8. Critique of the Recommendation

The strongest counter-argument: *Membrane as designed is privacy by software permissions, not by cryptography, and software permissions are eventually-broken permissions.* Anyone with read access to the brain file bypasses every check in §7. The wall is between Orion's publish call and the network, not between the data and the disk. The honest read: Membrane raises the floor for accidental leakage (§1a, the dominant threat for a single-user personal AI) and shrinks the compelled-disclosure blast radius (§1b). It does not defend against a determined local attacker (§1c-root) or a malicious federated peer (§1d) absent the cryptographic sender-policy work, which is a larger separate project.

Three specific weaknesses:

**The classifier is fundamentally the weakest link.** "The place we discussed yesterday" is contextually private but lexically innocuous. NER + regex catches the obvious cases, not the implicit ones. The only defense is the user, and the dashboard's "what did Membrane decide today" view is load-bearing for the whole architecture's honesty.

**Label creep is the silent killer.** §4c's information-flow discipline is correct but expensive — every metacognition output, every DMN synthesis, every dream consolidation inherits the strictest label of its inputs. After three weeks the entire derived layer is `visibility:local` and the brain goes silent on the mesh. The recommended mitigation (declassification at metacognition write-back) leans on a service that is itself only ~20% reliable (Anthropic introspection result, consciousness-research-v2.md §3.1). Pessimistic read: either over-leaking (declassification too eager) or over-quiet (label creep wins). Either invalidates the design's claim.

**Subject leakage isn't fully solved by the redacted-envelope trick.** Real cover traffic needs constant publish rate, not just placeholders when Membrane blocks. A subscriber can time incoming publishes and infer which redacted envelopes correspond to high-value writes by proximity to user input, by source host, by HLC density. Tor-grade cover traffic is expensive and Orion isn't paying for it. The honest answer: subject-level leakage is a *feature* of having a pub/sub substrate at all, and the only complete fix is `visibility:local` literally opting out of the substrate.

The deeper question is whether MEMBRANE-as-designed is even the right *kind* of thing. A cleaner alternative is *content-addressable storage with per-node encryption keys* — every node encrypted at rest, mesh members hold keys for nodes they're allowed to see, the publish path carries ciphertext only. This is the *Solid + IPFS + per-pod-key* architecture and it is the correct long-term shape. Membrane-as-tag-discipline is a strict subset: it works now, ships in a day, buys time to build the cryptographic story. Treat Membrane as v1, not endgame. If the founder ships LoRa broadcast or Federation peering on Membrane alone — without the per-node-key follow-on — the design has been over-trusted.

The hardest critique of the founder's framing, the one this memo circles: **calling it "Membrane" implies a wall, but the right metaphor is a *receptor layer* — semipermeable, signal-discriminating, biologically lossy, dependent on continuous policy maintenance rather than a one-time install.** Walls fail catastrophically. Receptors degrade gracefully and get better with feedback. Build for the receptor.

---

## References

- Dennis, J. B., & Van Horn, E. C. (1966). *Programming Semantics for Multiprogrammed Computations*. CACM. [Foundational capability-based security.]
- Miller, M. S. (2006). *Robust Composition: Towards a Unified Approach to Access Control and Concurrency Control*. PhD Dissertation, Johns Hopkins. [Capability composition; the unforgeable-token discipline.]
- Myers, A. C. (1999). *JFlow: Practical Mostly-Static Information Flow Control*. ACM POPL. [JIF / Jif; declassification as the audited escape valve — foundational for §4c.]
- Pottier, F., & Simonet, V. (2003). *Information Flow Inference for ML*. ACM TOPLAS. [FlowCaml — closer reference implementation than Jif.]
- Marlinspike, M. (2018). *Technology Preview: Sealed Sender for Signal*. https://signal.org/blog/sealed-sender/ [Cryptographic sender-blinding — directly applicable to Federation transport.]
- Matrix.org Foundation. *Matrix Server-Server (Federation) API*. https://spec.matrix.org/ [The federation receipt problem in production.]
- Tailscale. *ACL Reference*. https://tailscale.com/kb/1018/acls [Production-grade tag-based destination-class ACL — closest deployed model for §3.]
- Berners-Lee, T., et al. *Solid Specification & WebACL*. https://solidproject.org/ [Per-resource ACL on user-owned pods; closest prior art and cautionary tale on ACL ergonomics.]
- Hoffmeyer, J. (1996). *Signs of Meaning in the Universe*. Indiana University Press. And (2008) *Biosemiotics*. U. Scranton Press. [Semiotic freedom; the cellular receptor metaphor.]
- Apple Differential Privacy Team (2017). *Learning with Privacy at Scale*. Apple Machine Learning Journal. [Epsilon-budget UX.]
- Erlingsson, Ú., Pihur, V., & Korolova, A. (2014). *RAPPOR*. ACM CCS. [Local DP design for the eventual cryptographic Membrane v2.]
- Lindsey, J., et al. (2025). *Emergent Introspective Awareness in Large Language Models*. Anthropic. https://transformer-circuits.pub/2025/introspection/index.html [~20% reliability ceiling — see §8.]
- Butlin, P., Long, R., Bengio, Y., Chalmers, D., et al. (2023). *Consciousness in Artificial Intelligence: Insights from the Science of Consciousness*. arXiv:2308.08708. [Design-to-indicators worry maps onto building privacy to a test.]
- GDPR Article 4(1), *Definitions*. Regulation (EU) 2016/679. [Personal-data definition giving third-party-mention nodes legal weight.]
