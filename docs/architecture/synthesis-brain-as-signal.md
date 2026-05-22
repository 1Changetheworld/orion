# Synthesis — Brain-as-Signal as the Unlock for Everything Else

*Filed 2026-05-22. Invention pass, not literature review. Anchored in the
brain-as-signal / off-grid substrate, this doc reads across the five frontier
memos filed this cycle — [brain-as-signal v2](frontier-brain-as-signal-v2.md),
[continual learning](frontier-continual-learning.md),
[autonomous volition](frontier-autonomous-volition.md),
[self-model](frontier-self-model.md), [Hermes study](hermes-agents-study.md) —
plus [the unified-brain map](orion-unified-brain.md) and the
[Design Law](design-law.md), and asks one question those memos could not ask
in isolation:*

> **Which capabilities that each memo filed as "genuinely open" or assumed
> impossible become *reachable* the moment you combine a finding from one domain
> with a module or finding from another?**

Each memo is rigorous *within its lane*. The unlock is almost always
*across* lanes. The recurring shape: a thing the radio memo calls impossible
(bandwidth) is actually a problem the learning memo already solved
(compilation shrinks the payload); a thing the volition memo calls open
(corrigibility under fuel swap) is actually a problem the self-model memo
already instrumented (cross-fuel disagreement is a sensor). The brain-as-signal
constraint — *bytes are scarce, fuel is never in the air, the link is
intermittent* — turns out to be the **forcing function** that makes the other
four domains compose, because every one of them, pushed to its off-grid limit,
collapses to "spend the fewest, most-certain bytes."

**Design Law is the invariant on every combination below.** Confirm before
acting; act at the recoverable moment; reuse the deliberative core. Model is
fuel; no fine-tune; no API keys required; **fuel is never in the air.** Where a
combination would bend one of these, that is called out, not hidden.

---

## The single load-bearing insight

Read the five memos together and one identity falls out that none states alone:

> **A compiled procedure and a scarce-radio payload are the same object.**

- The continual-learning memo's *skill compilation* (R1) turns a repeatedly-fuel-reasoned
  fix into a **deterministic step list with guards** — kilobytes of structured
  text, no model needed to *run* it.
- The brain-as-signal memo's hard table says the model (GB) is **never** in the
  air, but *structured deltas proportional to what changed* (∝ difference, via
  ConflictSync) **are**.

A compiled procedure is exactly a "structured delta proportional to what
changed" that *also happens to be executable without fuel*. So the thing the
learning memo built to save **tokens** is, byte-for-byte, the thing the radio
memo needs to save **air-time** — and because it runs fuel-free, it honors
"fuel is never in the air" *by construction*. Every combination in §1–§6 is a
consequence of that one identity. Compilation is the bridge between "learns over
time" and "travels over radio," and nobody filed it because the two memos were
written in different lanes on the same day.

---

## 1. The returned/off-grid node arrives already-smarter — and it's *cheaper* than chat

**Impossible-seeming capability.** A node that has been off-grid for a week —
reachable only by LoRa, no IP — comes back into the mesh *already knowing fixes
it never personally encountered*, learned by its peers while it was gone, with a
radio budget the duty-cycle memo says can't carry "the brain."

**The combination.**
- continual-learning **R1 (skill compilation)** → the executive's recurring
  fixes become `compiled_procedure` artifacts: ordered steps + guards, no prose,
  no fuel.
- continual-learning **R2 (the ratchet: contribution score + bounded cap)** →
  each procedure carries a *contribution score*, so peers can rank which ones
  are worth scarce bytes.
- brain-as-signal **§1 (ConflictSync/Rateless-IBLT anti-entropy)** + **§5
  (bundle + custody + TTL)** → the procedure *library* is just another LWWMap;
  two brains reconcile the **difference** in their compiled-procedure sets in
  bytes proportional to *what changed that week*.
- Orion modules: `orion_dream` (authors the procedures), `orion_executive`
  (registers them as fast paths), `orion_gossip.LWWMap` (the CRDT they ride),
  `transports/reconcile.py` (the wire layer).

**Why it actually works.** The radio memo's "no" was aimed at *cognition* (GB of
weights) and at *raw experience logs* (unbounded). A compiled procedure is
neither. It is a small, bounded, fuel-free artifact — and the ratchet's
contribution score gives a *priority key* so the duty-cycle accountant sends the
**highest-contribution procedures first** and stops when the budget runs out.
Gossiping compiled skills is strictly *cheaper* than gossiping the chat/decision
log the current Meshtastic daemon already carries, because compilation
**discarded** the reasoning trace and kept only the executable residue. The node
returns smarter not because it carried more bytes, but because its peers carried
the *right* bytes — the residue of learning, not the process of it.

**Buildable sketch.**
```
# in orion_dream compile phase (R1), tag each compiled_procedure:
proc = {id, symptom_class, steps[], guards[], contribution, hlc, author, ttl}
# it is a normal LWWMap entry → already gossips.
# new: a priority comparator for the duty-cycle accountant
def radio_priority(entry):
    if entry.kind == "compiled_procedure":
        return entry.contribution        # ratchet score = send-worthiness
    ...
# on rendezvous: ConflictSync digest of the procedure-set difference,
#   send symbols highest-contribution-first, stop on peer "decoded" or budget==0.
# on receive: freshness/replay guard (v2 §2) → LWWMap.merge → executive registers
#   the fast path. Node now tries it BEFORE any fuel call, off-grid, no model.
```
This is the founder's "gossiping compiled-skill playbooks over radio so a
returned node arrives already-smarter" — and the analysis says it's not just
possible, it's the *least* expensive thing on the air.

---

## 2. Autonomous goal pursuit off-grid, bounded and corrigible over LoRa

**Impossible-seeming capability.** Orion pursues a multi-day self-directed goal
on a node with **no internet**, makes consequential decisions, and *stays
corrigible* — the user can pause it from across the mesh, and it never
auto-runs anything destructive — even though the volition memo's safety proofs
assume continuous IP oversight and the radio memo says the "thinking" can't
travel.

**The combination.**
- volition **§3 architecture** (`will → taskspine → executive`) + the durable
  **PAUSE switch** that lexicographically dominates task reward.
- volition's **impact gate** (`impact = blast_radius × (1 − reversibility)`):
  the *act* decision is a tiny scalar computation, **no fuel required**.
- brain-as-signal **§4 split**: identity, critical state, *and reach* travel
  over radio. The PAUSE signal and the "I need to ask you" deferral are both
  sub-200-byte deltas — squarely IN the radio budget.
- self-model **Signal C (cross-fuel disagreement)** as the off-grid confidence
  source (see §3 — it composes here too).
- Orion modules: `orion_volition` (the loop), `orion_taskspine` (durable steps,
  already a CRDT → already gossips), `orion_executive` (tiered gate),
  `transports/lora.py` source-routed for the deltas, flood for the halt beacon.

**Why it actually works.** The volition memo's own decision math —
`if impact ≤ 0.2 and confidence ≥ 0.8: PLAY else ASK` — is **arithmetic, not
inference**. It needs no model in the air; it runs on whatever local fuel the
node already has *for the reasoning step*, and the *gating* is free. The two
things that must cross the radio are exactly the two things the §4 table says
**fit**: (a) the **ASK** — a tier3 deferral with an out-of-band code, ~100 bytes,
source-routed to wherever the user last spoke; (b) the **PAUSE** — a flood
beacon every node hears, smaller still. Corrigibility off-grid reduces to "the
halt signal is the cheapest, highest-priority, flood-routed packet class," which
the message-class routing table (v2 §6) already supports.

The Design Law is honored *better* off-grid than on, not worse: the recoverable
moment becomes literal (a step that needs fuel the node lacks logs as `stalled`,
not `failed` — volition §3.1 step 6 = brain-as-signal degradation-not-failure),
and the durable PAUSE file means a node that *can't be reached* still stops
itself the instant a gossiped halt-delta arrives.

**The freshness trap, and why §2 closes it.** A naive version is *unsafe*: an
attacker on a multi-hop LoRa path could replay a stale "PAUSE cleared" delta to
restart a paused goal. This is exactly the brain-as-signal **§2 semantic-rollback
attack**. The fix already specified there — sign `(delta, observed_max_remote_hlc)`
and keep a per-author HLC high-water — makes the PAUSE state monotonic: a
replayed "resume" with a stale HLC loses, and one claiming an implausibly-future
HLC is rejected. So the combination is only safe *because* the security finding
from a different memo plugs the hole. **PAUSE must be modeled as a tier the
freshness guard treats as sticky-on: clearing it requires a fresh, signed,
user-authored delta, never an inferred or replayed one.**

**Buildable sketch.**
```
# taskspine step loop, off-grid:
for step in task.next_steps():
    if pause_flag_set():            # checked from gossiped PAUSE delta, freshness-guarded
        checkpoint(step); task.state = "paused"; break
    impact = blast_radius(step) * (1 - reversibility(step))   # no fuel
    conf   = local_confidence(step)                            # local fuel or cross-fuel (§3)
    if impact <= 0.2 and conf >= 0.8:
        run(step)                    # PLAY, local
    else:
        emit_ask(step)               # ~100B tier3 deferral → reach → source-routed LoRa
        task.state = "awaiting_user"; checkpoint(step); break
```
Genuinely-open item this *closes*: volition open-item **#12 ("corrigibility
under a fuel swap")** is partly answered here — corrigibility off-grid does
**not** depend on the policy, because the PAUSE/ASK gate is fuel-*external*
arithmetic + a signed CRDT flag. Swap Claude→Ollama mid-goal and the gate is
identical. The part that stays open is the *quality* of the reasoning the gate
protects, not the gate's authority. That is a real narrowing of #12.

---

## 3. Cross-fuel uncertainty decides what's worth the scarce radio bytes

**Impossible-seeming capability.** The node *itself* decides which of its newly
learned facts/procedures are certain enough to be worth burning duty-cycle on —
without a human curator, without a trusted reference, off-grid — and this same
mechanism gives it an off-grid confidence signal that no single-model system
could ever have.

**The combination.**
- self-model **Signal C (cross-fuel disagreement = epistemic uncertainty)** —
  Orion is multi-fuel by design; asking two local fuels the same question and
  measuring disagreement *is* the uncertainty estimate, and it's **external** to
  any one model's wired-in overconfidence (self-model Part 0, finding 3).
- self-model **N3 (invert the abstention prior)** — reasoning fuels are
  *more* overconfident, so they get *more* scrutiny, not less.
- brain-as-signal **§0 byte budget** + **§7 duty-cycle accountant** — bytes are
  the scarce resource; something must rank them.
- continual-learning **R4 (metacog as governor, not labeler)** — confidence is
  the *gate*, not decoration.
- Orion modules: `orion_coherence_probe` (already runs ≥2 fuels), `orion_fuel`
  (the cascade), `transports/` duty-cycle accountant.

**Why it actually works.** The duty-cycle accountant (v2 §7) was specified to
prioritize *request-driven over push* and *small over large* — but it had **no
semantic priority signal**, only size. Cross-fuel disagreement supplies the
missing axis: a fact two local fuels **agree** on is low-epistemic-uncertainty →
high-confidence → worth the air; a fact they **disagree** on is genuinely
uncertain → *don't* spend scarce bytes propagating something that might be
wrong; refuse, or wait for IP rendezvous where it's cheap to resolve. This is
the founder's "cross-fuel uncertainty deciding what's worth the scarce radio
bytes" — and it works because Orion has the one property (multiple fuels
co-resident) that makes epistemic uncertainty *measurable locally, off-grid,
with no internet*. A cloud single-model assistant cannot do this at all; an
off-grid single-model node *especially* cannot.

The elegant part: the **same** cross-fuel probe serves three masters at once —
(1) the radio priority key here, (2) the off-grid confidence for the volition
gate in §2, (3) the "refuse rather than fabricate" self-model guarantee. One
sensor, three uses, all off-grid, all fuel-external.

**Buildable sketch.**
```
def radio_worthiness(delta):
    # epistemic uncertainty via cross-fuel disagreement (self-model Signal C)
    a = ask_fuel(fuel_primary, delta.claim)
    b = ask_fuel(fuel_secondary, delta.claim)       # 2nd local fuel, off-grid
    agree = semantic_agreement(a, b)                # NOT lexical
    if agree < TAU_LOW:                             # high epistemic uncertainty
        return 0.0                                  # do NOT spend bytes; refuse/defer
    return agree * delta.contribution               # certainty × value = send-worthiness
# accountant sends highest radio_worthiness first, stops at budget.
```
Honest cost: 2 fuel calls per candidate delta. Gate it to *high-stakes or
about-to-transmit* deltas only (self-model P2), never every memory write. And it
needs ≥2 fuels resident on the off-grid node — which the unified-brain memo's
item #2 ("peer strong CLIs on every host") already calls a requirement for a
different reason. Two memos, same prerequisite.

---

## 4. The radio link audits *itself* for being kept stale — using cross-fuel disagreement as the reference clock

**Genuinely-open item attacked.** brain-as-signal **open-item: "detecting *I'm
being kept stale* without a trusted reference clock."** An adversary controlling
a relay can't forge deltas (freshness guard, §2) but *can* selectively **drop**
fresh ones, freezing a victim on old state. The memo filed this as open because
there's no trusted clock off-grid to notice the gap.

**The combination that cracks it open (partially).**
- self-model **Signal C** again, but pointed *inward at time*: a node's own
  fuels, asked "given everything you know, is this state plausibly current?",
  will increasingly **disagree with the stale memory** as the world drifts past
  it. Rising internal disagreement-with-stored-state is a *content-based*
  staleness signal that needs no external clock.
- `orion_chronos` **offline-gap awareness** (unified-brain CORE table) — already
  logs "how long since I heard from peer X."
- continual-learning **R3 (typed, retrieval-anchored decay)** — strategic facts
  decay near-flat; a *fast-decay episodic* fact that hasn't been refreshed past
  its expected cadence is itself the alarm.

**Why it partially works.** You can't get a *trusted absolute clock* off-grid —
that part stays open. But you don't need one to detect *being kept stale*; you
need a *self-consistency* alarm. Chronos knows "peer X gossips roughly hourly;
it's been 14 hours" — a *cadence* anomaly, not an absolute-time claim. Layer on
"my fuels increasingly find my cached state about X *internally implausible*"
(rising cross-fuel disagreement-with-self over time), and you have two
independent, off-grid, reference-clock-free signals that *converge* on "I am
probably being starved of fresh deltas about X." That converts a silent denial
into a **surfaced suspicion** — which, per Design Law #1 (confirm before
acting), Orion treats as a flap to *probe* (try an alternate route / alternate
carrier / flood a "are you there?" beacon), not a fact to act on.

**What stays open, honestly.** This *detects* suspected staleness; it cannot
*prove* it, and a patient adversary who drops deltas at exactly the expected
cadence-minus-epsilon defeats the cadence signal. So brain-as-signal's open-item
is *narrowed from "undetectable" to "detectable-with-false-positives, not
provable."* That is a real move — an alarm you didn't have — but it is not a
solution, and the doc should not claim one.

**Buildable sketch.**
```
# periodic, off-grid:
gap = chronos.silence(peer) / chronos.expected_cadence(peer)   # cadence anomaly
self_doubt = 1 - cross_fuel_agreement_with_stored(topic)       # content staleness
if gap > G and self_doubt > D:
    suspect_staleness(peer, topic)        # DO NOT act; probe (Design Law #1)
    try_alternate_route() or flood_presence_beacon()
```

---

## 5. Pure-radio first contact, made honest by making it a *bounded autonomous goal*

**Genuinely-open item attacked.** brain-as-signal **open-item: "trust bootstrap
with no prior IP contact" / "pure-radio first-contact trust is unsolved."** Two
Orion brains that have *only ever* shared radio, never an IP link, can't
establish a key without a CA, rendezvous server, or a TOFU MITM window.

**The combination — reframe trust-bootstrap as a volition-gated, human-confirmed
goal, not a protocol.**
- volition **Play/Ask gate** + **abandon-as-rewarded-outcome** (volition §3.1
  step 7): first-contact-with-an-unknown-Orion is, by definition, *high impact*
  (identity blast radius = 1.0) and *low confidence* → the gate forces **ASK**,
  never auto-trust.
- self-model **N5 (refusal the fuel can't synthesize around)** + **Signal C** —
  the node *refuses* to merge an unauthenticated peer's state and says so
  categorically; cross-fuel can't manufacture confidence it doesn't have.
- brain-as-signal **§4 reach over radio** — the "should I trust this peer?"
  question is itself a sub-200-byte reach to the *user*, who is the missing root
  of trust.
- ggwave acoustic / NFC tap (v2 §7 / sensorium) as the *intent-revealing*
  confirm channel when physical proximity exists.

**Why it actually works.** The memo filed this as open because it searched for a
*cryptographic* answer (key exchange without a CA) and there isn't a clean one
over a MITM-able broadcast medium. But Orion doesn't *need* the radio layer to
solve trust autonomously — Design Law #1 says *confirm before acting*, and Orion
has a confirmation root the protocol literature doesn't: **the human.** Reframe:
first-contact is a **high-impact goal that the volition loop is structurally
required to escalate to ASK.** The two brains exchange identity beacons over
radio (cheap), but *neither merges the other's state* until the **user**
confirms — via an out-of-band code (executive tier3), an NFC tap, or a ggwave
in-room handshake — that this peer is theirs. The MITM can replay beacons all
day; it cannot produce the user's out-of-band confirmation.

This **doesn't solve the cryptographic problem** — it *dissolves* it by refusing
to make trust an autonomous radio-layer decision. That is exactly on-thesis:
"confirm before acting," "the recoverable moment" (trust is granted when the
user is present to confirm, not when the beacon arrives), and "abandon is a
rewarded outcome" (a peer the user never confirms is *abandoned*, cleanly, not
left in a limbo that an attacker can exploit). The open *crypto* problem stays
open for the *fully-unattended* case — two off-grid nodes with no human at
either end can't bootstrap trust, and the doc must keep saying so — but the
*human-present* case, which is the overwhelmingly common one, is solved by
composition.

**Buildable sketch.**
```
on_unknown_peer_beacon(peer):
    impact = 1.0          # identity blast radius
    conf   = 0.0          # never met → cross-fuel can't raise it (Signal C, N5)
    # gate forces ASK:
    emit_ask_user(f"New Orion peer {peer.fingerprint[:8]} on radio. Yours?",
                  confirm=OOB_CODE or NFC_TAP or GGWAVE)
    # until confirmed: refuse merge categorically (N5 — nothing to weave)
    if not confirmed_within(ttl): abandon(peer)   # rewarded outcome, not failure
```

---

## 6. Hermes's subagent delegation, off-grid, as durable mesh tasks (not in-process threads)

**Impossible-seeming capability.** Parallel sub-task delegation across an
**off-grid mesh** — a node spawns helpers that survive its own death and the
loss of the link between them — even though Hermes's delegation is in-process
threads that "die with the process" (Hermes study §1.4), and the radio memo says
you can't stream coordination state continuously.

**The combination.**
- Hermes study **§3 item 4 (subagent delegation, "built the Orion way")** — the
  study explicitly says: build it as `taskspine` children (durable,
  mesh-replicable), *not* in-process threads.
- volition/taskspine — children are taskspine tasks → **already CRDTs** → already
  gossip (unified-brain #1 "host independence comes for free").
- brain-as-signal **§5 custody transfer** — when the parent hands a child task
  to a peer node, that peer accepts *custody* (DTN), owning it onward even if the
  parent goes dark.
- continual-learning **R1** — a child whose job is a *recurring* sub-procedure
  ships as a compiled procedure, so delegation costs almost no air-time.

**Why it actually works.** Hermes's delegation dies with the host because it's
context-isolated *threads*. The moment you re-express a child as a durable,
HLC-stamped taskspine entry, three properties the radio world demands appear for
free: it **survives host death** (resumes on whatever's alive — unified-brain),
it **replicates over the mesh** (it's a CRDT), and a peer can **take custody**
(§5 DTN). So "parallel delegation off-grid" isn't a new mechanism — it's Hermes's
*idea* (isolated child + restricted toolset + parent-sees-summary) re-hosted on
the durable spine Orion already has and the custody model the radio memo already
recommends. The restricted-toolset safety property (children can't recurse,
can't spawn, depth ≤ 2) maps directly onto the volition impact-gate: a child
task inherits a *capped blast radius* from its parent.

**What's genuinely required, honestly.** This needs the parallel-taskspine
machinery the Hermes study says to *defer until there's a concrete parallel use
case*. So this is a **reachable-but-not-yet-warranted** combination: the pieces
compose cleanly, but building it now would gold-plate. Filed as "unlocked in
principle, build when a real off-grid parallel workload appears."

---

## The "genuinely open" ledger — what moved, what didn't

Revisiting every open-item across the five memos against the combinations above.

| Open item (source memo) | Status after synthesis | Via |
|---|---|---|
| **Corrigibility under hot-swappable fuel** (volition #12) | **Narrowed → mostly closed for the *gate*** | §2 — PAUSE/ASK is fuel-external arithmetic + signed CRDT; identical across fuel swaps. Reasoning *quality* under swap stays open. |
| **Detecting "I'm being kept stale" with no trusted clock** (signal-v2) | **Narrowed: undetectable → detectable-with-false-positives** | §4 — chronos cadence anomaly + cross-fuel disagreement-with-self. Not provable; patient adversary still wins. |
| **Pure-radio first-contact trust** (signal-v2) | **Dissolved for the human-present case; open for fully-unattended** | §5 — reframe as volition-gated ASK rooted in human OOB confirm, not a crypto protocol. |
| **What cadence of beacon+delta is useful *and* legal** (signal-v2) | **Still open — needs field data** | Untouched by combination; it's an empirical/regulatory question, not an architectural one. Honest open. |
| **Side-channel leakage of traffic *shape*** (signal-v2) | **Still open** | Cross-fuel worthiness (§3) *reduces* how often you transmit (fewer, higher-value bursts) which incidentally lowers shape-leakage surface — a mitigation, not a fix. Cover traffic still costs duty cycle Orion can't spare. |
| **Compounding uncertainty across host-handoff** (volition #13) | **Partially addressed** | §2/§6 — custody transfer (§5) gives a place to *carry* accumulated confidence with the task; whether B inherits or re-derives A's confidence is now a concrete schema choice, not a void. Still needs validation. |
| **Goal-implantation via watched channels** (volition #14) | **Reachable defense** | §5's N5-refusal + Signal C: a *latent* goal that two fuels find low-confidence/contested is gated to ASK before it ever becomes a taskspine task. Closes the auto-pursuit path; doesn't stop the implant itself. |
| **"Recoverable moment" as a learned predicate** (volition #15) | **Still open** | Untouched; learning it off one user's rhythm without overfitting is genuinely unsolved here. |
| **Token-to-weight distillation** (continual-learning #7) | **Still open + still thesis-risky** | No combination makes it safe; it remains a disposable-cache-only design note. Correctly stays out. |
| **Source attribution in self-report** (self-model O1) | **Still open (sidestepped, not solved)** | Orion reconstructs provenance externally; combinations don't grant true introspection. Honest wall. |
| **The model never travels** (signal-v2) | **Permanent boundary, *reinforced*** | Every combination above is *fuel-free in the air* by design — §0's identity (compiled procedure = scarce payload) is what lets us honor this while still propagating intelligence. The boundary is the enabler, not the obstacle. |

**Net:** of the genuinely-open items, **three move materially** (corrigibility-under-swap,
stale-detection, human-present first-contact), **two are partially addressed**
(cross-host confidence, goal-implantation), and **five stay honestly open**
(beacon-cadence legality, traffic-shape leakage, learned recoverable-moment,
weight distillation, true introspection). The mover in every case that moved is
the **same lever**: a sensor or artifact built for one domain (compilation,
cross-fuel disagreement, the impact gate) turns out to be exactly the missing
input another domain filed as absent.

---

## Why the off-grid constraint is the *forcing function*, not a limitation

The deepest finding of this pass: **brain-as-signal is not the hardest of the
five domains — it is the one that makes the other four honest.**

- It forces learning to **compile** (only fuel-free, bounded artifacts fit in the
  air), which is exactly what the continual-learning memo says is the highest-value
  unbuilt move *anyway* (R1). The radio constraint and the learning frontier want
  the **same** thing.
- It forces volition to be **fuel-external at the gate** (no model in the air to
  do the gating), which is exactly the corrigibility property the volition memo
  wants *anyway* — and which incidentally survives a fuel swap, closing its own
  open item.
- It forces the self-model to ground confidence in something **local and
  fuel-external** (no second cloud opinion available off-grid), which is exactly
  the cross-fuel-disagreement signal the self-model memo says is its biggest
  unbuilt win *anyway* — Orion's multi-fuel design makes it free, off-grid.
- It forces every byte to **justify itself**, which is exactly the curation /
  contribution-score governance the continual-learning memo says separates
  learning from a growing log *anyway*.

Four domains independently arrive at "spend the fewest, most-certain,
fuel-free, bounded units" — which is *the definition of an off-grid brain*. The
brain-as-signal substrate isn't a feature bolted onto a smart agent; it's the
**discipline that proves the agent is actually smart** rather than merely large.
A brain that can survive on a 250-bps straw, off-grid, corrigible, learning, and
honest about its uncertainty is provably none of: model-bound, host-bound,
token-hungry, or overconfident. The constraint is the proof.

---

## Buildable-now ladder (combinations only; each reuses shipped/specced organs)

In dependency order. Every rung is *wiring* of existing modules; none touches a
model weight, none puts fuel in the air, all confirm-before-acting.

1. **Compiled-procedure as a gossipable LWWMap entry with a contribution-score
   priority key** (§1). Depends on continual-learning R1+R2 landing first. The
   single highest-leverage combination: it makes "returned node arrives smarter"
   real *and* makes everything in §2–§6 cheaper to transmit.
2. **Cross-fuel `radio_worthiness` as the duty-cycle accountant's semantic
   priority axis** (§3). Reuses `orion_coherence_probe`'s existing 2-fuel call.
   Gate to about-to-transmit deltas only.
3. **PAUSE/ASK as freshness-guarded CRDT flags with flood-routed halt** (§2).
   Reuses volition's PAUSE switch + brain-as-signal §2 freshness guard + §6
   message-class routing. Security-urgent: PAUSE must be sticky-on.
4. **First-contact-as-ASK** (§5). Reuses volition's impact gate + N5 refusal +
   reach-over-radio. Closes the human-present trust gap with zero new crypto.
5. **Staleness suspicion alarm** (§4). Reuses chronos cadence + cross-fuel
   disagreement-with-self. Surfaces suspicion, never acts on it (Design Law #1).
6. **Custody-bearing taskspine children** (§6). *Defer* per Hermes study until a
   real off-grid parallel workload exists. Reachable, not yet warranted.

Rungs 1–3 are the spine: learn-and-compile, decide-what's-worth-the-air,
stay-corrigible-off-grid. Build those and "the brain travels as signal; the fuel
is fetched at the destination" stops being a North Star and becomes a property
you can field-test on three Heltec nodes in a yard.

---

## One-paragraph thesis

The five frontier memos each drew a wall and labeled some of it "genuinely
open." Read together under the off-grid constraint, most of those walls turn out
to be *the same wall seen from different sides*, and the off-grid constraint is
the only vantage that reveals it: **a compiled procedure, a scarce-radio
payload, a fuel-free decision, and a high-certainty cross-fuel agreement are all
the same kind of object — small, bounded, model-independent, and self-justifying
about why it deserves to exist.** Build the brain to traffic *only* in those
objects when the link is a 250-bps straw, and it is automatically the thing the
learning memo, the volition memo, and the self-model memo each wanted on its own:
a brain that gets smarter without getting bigger, acts without running away,
knows what it doesn't know, and survives the loss of any model and any machine.
The radio doesn't carry the brain. The radio *disciplines* it into being one.

---

*Companion to the five memos it synthesizes. Adds no new external research; its
only claim is that combinations across those memos, anchored in brain-as-signal,
reach capabilities each memo filed as open. Where a combination only narrows or
dissolves an open item rather than solving it, that is stated. Honors
[design-law.md](design-law.md) on every rung: confirm before acting, act at the
recoverable moment, reuse the deliberative core; model is fuel, no fine-tune, no
keys required, fuel is never in the air.*
