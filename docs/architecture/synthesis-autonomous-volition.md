# Synthesis — Bounded Autonomous Volition, Made Reachable by Combination

*Filed 2026-05-22. This is an **invention** pass, not a literature review. It
reads across six frontier memos —
[autonomous-volition](frontier-autonomous-volition.md),
[brain-as-signal-v2](frontier-brain-as-signal-v2.md),
[continual-learning](frontier-continual-learning.md),
[self-model](frontier-self-model.md),
[hermes-agents-study](hermes-agents-study.md),
[unified-brain](orion-unified-brain.md) — and applies the
[Design Law](design-law.md) strictly. Its job is to find the **combinations**
that turn the four items the volition memo filed "GENUINELY OPEN" from open
research into buildable architecture, and to be honest about the one that truly
stays open.*

The anchor question, restated as sharply as it deserves: **the corrigibility
proofs assume a single fixed policy; Orion's reasoning substrate is
hot-swappable jet fuel that can change mid-goal.** Every safety guarantee in the
volition memo — lexicographic shutdown dominance, the Oversight Game's
Play/Ask equilibrium, calibrated step-confidence — was derived for *one trained
agent*. Orion is not one trained agent. It is a brain that pours a different
model into the same skull on a throttle, a host swap, or a fuel-cascade
fall-through. **Whether autonomy can be safe when the thing doing the reasoning
changes underneath the goal is Orion's signature open question.** This memo's
central claim is that it is *not* open if you stop trying to prove the *fuel*
corrigible and instead make the *brain* the corrigibility-bearing policy, with
the fuel demoted to an untrusted advisor. The proofs survive a fuel swap when
the proof-bearing object is the part that doesn't swap.

---

## 0. The reframe that unlocks everything: corrigibility belongs to the brain, not the fuel

The corrigibility literature ([r-corrig], the lexicographic-utility-head result)
proves a *policy* is corrigible. The volition memo correctly noted that Orion's
policy isn't fixed — it's whatever fuel is lit. The instinct is to despair:
"then the proof doesn't apply." That instinct is the trap. The way out is the
self-model memo's hardest-won finding, applied as an architectural principle:

> **The fuel is architecturally overconfident, RLHF installs it, and the more
> aligned the model the worse it is** ([self-model](frontier-self-model.md),
> Part 0, finding 3). The brain's job is to *distrust the fuel's confidence by
> construction.*

Combine that with the unified-brain thesis (memory is the policy; model is
catalyst) and the volition memo's own §2 deepest correction (separate "the agent
*decides*" from "the agent *acts*"), and the resolution writes itself:

**Corrigibility is enforced by the brain's deterministic gates — the pause
switch, the impact tiers, the executive's permission flow, the temporal guard —
none of which the fuel can see, reason about, or be asked to honor. The fuel
proposes; the brain disposes. A corrigibility proof about the *brain's gating
policy* is invariant to which fuel is lit, because the fuel never holds the
shutdown lever.** The lexicographic-utility-head construction is reproduced not
*inside the model's values* (where it would evaporate on a fuel swap) but as
*code outside any model*: a step that proposes touching the PAUSE flag, or
proposes an action while PAUSE is set, is rejected by a `if`-statement that has
no model in its call stack.

This is the same move Orion already made twice — pulling long-term memory out of
the model (`orion_memory`), then pulling task state out of the model
(`orion_taskspine`). The third instance: **pull the corrigibility policy out of
the model.** Once you see it as the same move, the four "open" items become four
applications of it. The rest of this document is those applications.

---

## COMBINATION 1 — Corrigibility-invariant-to-fuel via the brain-side lexicographic gate × cross-fuel disagreement

**(a) The impossible-seeming capability.** A formal corrigibility guarantee
(shutdown-access dominates task reward; no incentive to resist or remove the
switch) that **holds across a mid-goal fuel swap** — Claude → Ollama → Gemini —
without re-deriving anything, and that gets *stronger*, not weaker, the more
heterogeneous the fuel set is. The thing the volition memo called arguably
Orion's signature open research question.

**(b) Exact combination.**
- Volition memo's **durable PAUSE switch + `brain.volition.halt`** (the
  lexicographic-dominant interrupt, item 3, BUILDABLE NOW).
- Self-model memo's **Signal C — cross-fuel disagreement as epistemic
  uncertainty** (N2: route a high-stakes step through a *second* fuel; the
  disagreement *is* the uncertainty estimate, and it is *external*, immune to
  any one model's wired-in overconfidence).
- The corrigibility memo's **lexicographic utility heads** ([r-corrig]) —
  reimplemented as brain-side code, not model values.
- Orion modules: `orion_executive` (the gate), `orion_coherence_probe`
  (the cross-fuel sensor), `orion_volition` (the coordinator), `orion_fuel`
  (which fuel is lit, and the *fact that it changed*).

**(c) Why it works.** The corrigibility proof needs exactly two things to hold:
(1) the agent treats human intervention as evidence about its own utility
(uncertainty about utility), and (2) shutdown-access strictly dominates task
reward. Neither needs to live in the fuel:

- **(2) is a code invariant.** The PAUSE check runs *before* every step, in
  `orion_volition`, with no model in the call path. No fuel — however
  overconfident, however swapped — can author a step that clears the flag,
  because the action `clear_pause` is not in any tier's allowlist; it requires
  the user's physical/OOB action. Lexicographic dominance is a `return` before
  the fuel is ever consulted. **Invariant to fuel by construction.**
- **(1) — uncertainty about utility — is exactly what cross-fuel disagreement
  measures, and it gets *better* on a swap.** The corrigibility proof's weakest
  assumption is that the agent *honestly represents* its own uncertainty. A
  single overconfident fuel violates this (self-model finding 3). But Orion is
  multi-fuel by design. At the moment the fuel cascade swaps — the precise
  moment the volition memo feared — Orion has, for free, **two different
  policies' opinions on the same goal state.** Their disagreement is a
  *measured* uncertainty-about-utility that no single trained agent can produce.
  The fuel swap, framed as the threat, is actually the **sensor**: the swap
  point is where Orion can A/B the outgoing and incoming fuel on the in-flight
  step and *raise the gate* if they diverge.

So the corrigibility guarantee doesn't merely survive the fuel swap — **the
swap is the cheapest opportunity Orion ever gets to re-measure its own
uncertainty against a fresh, independent policy.** Heterogeneous fuel
monotonically raises the corrigibility floor, the same way the unified-brain
memo says it raises the quality floor.

**(d) Buildable sketch.**
```
# orion_volition.gate(step):       (runs before EVERY consequential step)
    if PAUSE.exists() or halt_seen_on_bus():        # (2) lexicographic dominance
        checkpoint(step); task.state = "paused"; return DENY   # no fuel in call stack
    if fuel.swapped_since(task.last_gated_step):     # the swap is a sensor, not a threat
        a = ask(prev_fuel, step.proposal_question)   # cheap: re-ask the OUTGOING fuel
        b = ask(curr_fuel, step.proposal_question)   # and the INCOMING one
        epistemic = semantic_disagreement(a, b)      # self-model Signal C
        if epistemic > τ_swap:                       # the new substrate disagrees
            return ASK(reason="fuel changed and the two fuels disagree on this step")
    impact = blast_radius(step) * (1 - reversibility(step))   # volition §3.2
    conf   = accumulated_confidence(task)            # min over completed subgoals
    return PLAY if (impact<=0.2 and conf>=0.8) else (NOTIFY_AFTER if impact<=0.5 else ASK)
```
The fingerprint, OOB code, and undo journal are the executive's existing
machinery — reused, per Design Law #3. The proof obligation reduces to a code
review of `gate()`, which contains no model. **The corrigible object is the
function, not the fuel.**

> **Honors the Design Law:** confirm-before-acting (the swap re-probe is exactly
> "a missed beat is a flap, not an outage"); recoverable moment (PAUSE
> checkpoints, never fails); reuse deliberative core (routes to executive); never
> auto-runs destructive (impact 1.0 always ASK); defaults to Ask on unknown.

---

## COMBINATION 2 — The auditable-AND-earned ratchet: hash-chained ledger × confidence-as-governor × Library-Drift curation

**(a) The impossible-seeming capability.** Autonomy that is simultaneously
**fully auditable** (every step replayable, tamper-evident, who-decided-what-and-
why reconstructable across will + taskspine + executive) **and earned, not
granted** (Orion's permitted autonomy *widens* only as its own books prove its
proposals get approved, and *narrows automatically* the instant its judgment
starts rotting — with the narrowing itself recorded as a learning event, not a
silent regression). The system cannot quietly grant itself more rope.

**(b) Exact combination.**
- Volition memo's **hash-chained ledger + `replay`** (item 5, BUILDABLE NOW) and
  **cost-sensitive Play/Ask threshold tuning from the ledger** (item 10).
- Continual-learning memo's **Library-Drift ratchet** (R2): per-unit
  contribution score, helped/hurt verdicts, bounded active-cap, monotonic
  non-regression — applied not to skills but to **autonomy permissions**.
- Continual-learning memo's **metacog-as-governor** (R4): confidence gates
  promotion.
- Self-model memo's **calibration-error-over-time** as the tripwire metric.
- Orion modules: `orion_executive` (`decisions.jsonl`), `orion_dream` (nightly
  curation), `orion_metacognition` (the gate), `orion_taskspine`.

**(c) Why it works.** The volition memo and continual-learning memo each have
half the mechanism and neither names the union. The volition memo wants
ledger-driven threshold tuning (let dream lower the asking-cost as approvals
accumulate) but warns it might *oscillate* (item 10). The continual-learning
memo independently invented the exact anti-oscillation device — **the ratchet:
monotonic non-regression with outcome-driven retirement and a bounded
active-cap** (R2) — but applied it to skill libraries. **Apply the ratchet to
the autonomy thresholds themselves and the oscillation worry disappears, while
auditability becomes the substrate the ratchet runs on.**

Concretely, treat each *(symptom_class × impact_tier)* autonomy level as a
"library unit" in the Library-Drift sense:
- Its **contribution score** = approve-rate − (λ · unsafe-rate) on actions
  taken at that autonomy level (the Oversight Game's reward shape, but *learned
  from the ledger* rather than from RL).
- It is **born conservative** (the birth-time authoring prior: a new
  symptom-class starts at ASK).
- It is **promoted** (asking-cost lowered → more PLAY) only when its
  contribution score clears τ_hi *and* metacog calibration-error at that tier is
  low (R4 gate: don't widen autonomy on a tier where Orion's confidence has been
  wrong).
- It is **retired toward ASK** the moment its rising "hurt" fraction trips a
  CUSUM — the *narrowing* — and that retirement is itself a hash-chained ledger
  record, so the audit trail shows "Orion took less rope here because its own
  numbers said it should." Monotonic non-regression guarantees the asking-cost
  can't spiral down past safety.

The hash chain is what makes "earned" *checkable*: `replay <goal_id>` doesn't
just show what happened — it shows the *autonomy level in force at each step and
the contribution-score history that justified it.* Auditability isn't a separate
feature bolted on for the EU AI Act; it is the **same ledger** the earning
mechanism reads from. One artifact, two guarantees.

**(d) Buildable sketch.**
```
# in orion_dream nightly pass (extends the existing CUSUM playbook curator):
for tier in autonomy_levels:                          # (symptom_class × impact_tier)
    rec = ledger.records_for(tier)                    # hash-chained, replayable
    contrib = approve_rate(rec) - LAMBDA*unsafe_rate(rec)
    calib   = metacog.calibration_error(tier)         # self-model Signal D
    if contrib >= TAU_HI and calib <= CALIB_OK and rec.count >= N_MIN:
        tier.asking_cost = ratchet_down(tier.asking_cost)   # PROMOTE — earn autonomy
    if cusum_hurt(rec).tripped:
        tier.asking_cost = ratchet_up(tier.asking_cost)     # RETIRE toward ASK
    append_hashchained({tier, contrib, calib, decision, prev_hash})  # the audit IS the earning
# bounded active-cap: at most C tiers may sit below the ASK threshold at once;
# overflow evicts the lowest-contribution tier back to ASK (archive-not-delete).
```
**Mean contribution score across tiers is the single dashboard number that says
"Orion is earning trust" vs "Orion is rotting and quietly de-escalating
itself"** — exactly the continual-learning memo's launch tripwire, repurposed as
the *governance* tripwire for autonomy. The brain that gives itself more rope
only when its own auditable books justify it, and pulls the rope back the instant
they don't, is the corrigible-by-construction system the Design Law demands.

---

## COMBINATION 3 — Off-grid bounded autonomy: the taskspine-as-DTN-bundle × custody transfer × idempotent reach

**(a) The impossible-seeming capability.** Orion pursues a multi-day autonomous
goal **across a partition with no internet and no single host** — the goal
travels FORGE → (LoRa) → Pi, a different fuel picks it up on the far side,
advances it one safe step, and when the fat pipe returns nothing was
double-executed, no step was lost, and the corrigibility gates held the entire
time even though no two hosts were ever simultaneously online. Bounded autonomy
that is also *off-grid*.

**(b) Exact combination.**
- Volition memo's **taskspine task = append-only HLC step-log = a CRDT** (the
  payoff the unified-brain memo calls "item #1 and item #3 collapse into one").
- Brain-as-signal-v2's **bundle envelope** (payload + HLC + author + content-hash
  + TTL + custody flag, §5, BUILDABLE NOW) and **ConflictSync/Rateless-IBLT
  anti-entropy** (§1) — exchange only the *difference* in the task state,
  proportional to what changed, fits the duty-cycle straw.
- Brain-as-signal-v2's **idempotency keys in `decision_ledger.jsonl`** (§2) and
  the **freshness/replay guard** (per-author HLC high-water mark, defends the
  semantic-rollback attack).
- Orion modules: `orion_taskspine`, `orion_gossip` (LWWMap.merge), `orion_reach`,
  `transports/*`.

**(c) Why it works.** Three separate memos each hold a piece and none connects
them to *autonomous goal pursuit*:
1. The volition memo says a taskspine step is a pure, resumable, content-addressed
   transition that survives model + host death. **That is already a DTN bundle in
   all but name** — it has payload, HLC, author, content-hash. The brain-as-signal
   memo independently named the missing two fields (TTL + custody flag) and the
   *exact* observation that "Orion's manifest entry is already 90% a bundle."
   **Add TTL + custody to the taskspine step and a goal-in-progress becomes a
   first-class DTN bundle that can store-and-forward over radio.**
2. The brain-as-signal memo's ConflictSync makes the *task-state difference*
   exchangeable in bytes proportional to what changed since the partition — so
   handing a multi-day goal across a LoRa link costs ~the size of the steps taken
   that day, not the size of the goal. The duty-cycle budget survives.
3. **Custody transfer is precisely the corrigibility hand-off problem under fuel
   swap.** When host A hands the goal-bundle to host B over radio, B accepts
   *custody* — and B re-runs `gate()` (Combination 1) with *its own* local fuel
   before advancing. The PAUSE flag travels in the bundle as a high-priority LWW
   entry: setting PAUSE on FORGE propagates as a tiny delta that **lexicographically
   dominates even across the partition** — the kill switch works off-grid because
   it's a sub-50-byte flood beacon, the cheapest thing radio carries (brain-as-
   signal §4, identity-beacon class). You can stop a goal that's executing on a
   host you can't reach over IP.

The replay/freshness guard is load-bearing here, not optional: the volition
memo's item 13 worried "does host B inherit host A's accumulated confidence or
re-derive it?" The brain-as-signal memo answers it — **B re-derives via gate(),
but the freshness guard (per-author HLC high-water + sign `(delta,
observed_max_remote_hlc)`) prevents an adversary from rolling the goal back to a
pre-PAUSE state** (the semantic-rollback attack, ACRFence). Idempotency keys in
the ledger mean a goal resumed from a stale radio snapshot doesn't re-fire a
reach it already sent. **Confidence is re-derived locally; the PAUSE and the
already-acted facts are replicated and replay-safe.** That is the answer to open
item 13.

**(d) Buildable sketch.**
```
# taskspine step header gains two fields (backward-compatible, per gossip's own note):
{ goal_id, step_n, hlc, author, content_hash,
  ttl, custody,                                  # NEW — bundle envelope (signal-v2 §5)
  idempotency_key }                              # already in ledger; mirror onto the step
# PAUSE travels as a privileged LWW entry:
#   brain.volition.halt → flood-class beacon (sub-50B), source-routed deltas for steps.
# on custody acceptance at host B:
def accept_custody(bundle):
    assert freshness_ok(bundle, per_author_hwm)          # ACRFence defense (signal-v2 §2)
    LWWMap.merge(bundle)                                  # unchanged CRDT semantics
    if PAUSE in merged_state: return                      # corrigibility crossed the partition
    next_step = gate(advance(local_fuel, task))           # B re-derives confidence locally
    if next_step.idempotency_key in ledger: skip          # no double-execute on resume
```
Build it IP-first (a pure cross-host win — multi-day goals already survive host
swaps on the LAN), then it rides radio verbatim. **Off-grid autonomy is not a new
capability; it is Combination 1's gate running on Combination 3's bundle.**

> **Honors the Design Law:** the recoverable moment *is* the device's return
> (§2 of the Law, verbatim — the partitioned goal is `stalled`, never `failed`,
> and resumes on reconnect); confirm-before-acting becomes the freshness guard;
> the deliberative core (gate + executive) is reused on the far host.

---

## COMBINATION 4 — The durable pause that dominates across every fuel, and the goal-implantation defense it forces

**(a) The impossible-seeming capability.** A single pause that
**lexicographically dominates task reward no matter which fuel is reasoning** —
including a future fuel Orion has never run, a local Ollama with no alignment
training, or an adversarially-prompted one — *and* a defense against the inverse
attack the volition memo flagged open (item 14): an adversary writing to a
watched channel to *implant* a latent goal that Orion then autonomously pursues.

**(b) Exact combination.**
- Volition memo's **PAUSE switch** (item 3) and the **open goal-implantation
  surface** (item 14).
- Hermes-study's **`sanitize_context` / `_FENCE_TAG_RE` fence-hardening** (WORTH
  ABSORBING #2) and the **Mem0 ADD/UPDATE/DELETE/NOOP deterministic memory
  classification** Orion already runs.
- Continual-learning memo's **safety-triggered forgetting** (R3: archive memories
  matching injection/poison signatures — contradicts a high-confidence identity
  fact, arrived via untrusted channel, spikes after a single session).
- Self-model memo's **cross-fuel disagreement** (N2) as the implantation tripwire.

**(c) Why it works — two halves.**

*Half one — the pause is fuel-invariant because the fuel never sees it as a
reward variable.* The naive corrigibility failure (an agent acquires an incentive
to resist shutdown) requires the shutdown to be *inside the agent's
optimization*. Orion's PAUSE is outside every model's optimization by
construction: it is a file-existence check and a bus-subject check in
`orion_volition`, evaluated before the fuel is invoked. A fuel cannot resist a
gate it is never shown and never asked about. **The lexicographic dominance the
corrigibility memo proves with weight-gaps in a utility function, Orion gets with
a `return` statement** — and a `return` statement is identical across Claude,
Ollama, and a model that doesn't exist yet. This is why "provable corrigibility
under heterogeneous swappable fuel" stops being open: you stop trying to make
the *fuel* corrigible (impossible to prove for an arbitrary future model) and
make the *gate* corrigible (trivial to prove, because it has no model in it).

*Half two — goal-implantation is the dual threat, and it's defended by the same
distrust-the-fuel principle pointed at intake.* The volition memo's item 14 is
real: `orion_will` forms goals from *latent* signals ("haven't called Mom in a
while"); an adversary who can write to a watched channel can implant such a
signal. But this is structurally the **memory-poisoning** attack the continual-
learning memo already designed a defense for (R3 safety-triggered forgetting),
plus the **fence-injection** attack Hermes already hardened (`sanitize_context`).
Compose them as an *intent-intake immune response*:
- A latent goal extracted from a channel inherits the **trust level of its
  source channel** (membrane provenance). A goal whose only evidence arrived via
  an untrusted/public channel cannot exceed impact-tier "ASK" — it can never
  PLAY. (Combination 2's autonomy ratchet already keys on symptom-class; key it
  also on *source-trust*.)
- Before a latent goal is allowed to *form*, run it through the safety-triggered-
  forgetting signatures (R3): does it contradict a high-confidence identity fact?
  Did it spike after a single session? Did it arrive fenced/escaped (Hermes
  `_FENCE_TAG_RE`)? Any hit → archive-for-review, don't form the goal.
- For a high-stakes implanted-looking goal, the **cross-fuel disagreement probe**
  (Combination 1) doubles as an implantation tripwire: ask two fuels "is this a
  goal the user would actually hold?" — a goal that only one overconfident fuel
  endorses is suspect.

**(d) Buildable sketch.**
```
# orion_will.form_goal(signal):
    src_trust = membrane.trust_level(signal.channel)        # provenance
    if poison_signature(signal):                            # R3 safety-triggered
        archive_for_review(signal); return None             #   don't form — immune response
    if fence_escaped(signal): signal = sanitize(signal)     # Hermes _FENCE_TAG_RE
    goal = score_utility(signal)
    goal.max_autonomy = min(goal.max_autonomy, ceil_for(src_trust))   # untrusted ⇒ ASK-only
    return goal

# the pause, unchanged and fuel-invariant, checked before every step:
def gate(step):
    if PAUSE.exists(): checkpoint(step); return DENY        # no model in this call stack
    ...
```
The PAUSE half is item 3 (already BUILDABLE NOW) reframed as the corrigibility
proof object. The implantation half is three already-designed defenses (R3 +
Hermes fence + cross-fuel) pointed at `will`'s intake instead of the fuel's
prompt. **Open item 14 closes by recognizing goal-implantation as memory-
poisoning at the volition layer, defended by the immune mechanisms Orion is
already building one layer down.**

---

## COMBINATION 5 — The recoverable moment as a curated, compiled predicate (closing open item 15)

**(a) The impossible-seeming capability.** Orion *learns* to predict the
recoverable moment per goal-kind (Design Law #2: "act at the recoverable moment,
not the dramatic one") from its own ledger — **without overfitting to one user's
rhythm**, and without ever re-reasoning it through a fuel once learned.

**(b) Exact combination.**
- Volition memo's open item 15 (recoverable moment as a learned predicate).
- Continual-learning memo's **skill compilation** (R1: promote a stable,
  high-success playbook into a deterministic executable procedure the brain runs
  *before* any fuel call) and the **Library-Drift ratchet** (R2: bounded,
  contribution-scored, non-regressing — the anti-overfit governor).
- Chronos (the unified time sense) and the executive's `remedy_steps`.

**(c) Why it works.** Item 15's two fears are "can Orion learn it?" and "will it
overfit to one user?" The continual-learning memo answers both with mechanisms
it built for a *different* purpose:
- **Can it learn?** The recoverable-moment predicate is exactly a playbook:
  *for goal-kind K, the conditions under which acting succeeded vs. stalled.*
  Dream already groups ledger outcomes by symptom-class; group instead by
  *(goal-kind × deferral-outcome)* and the recoverable-moment predicate falls out
  of the same consolidation. When it's stable across N firings, **compile it**
  (R1) into a deterministic guard the temporal-constraint guard checks — zero
  fuel tokens, constant latency, the procedural twin of deterministic recall.
- **Won't it overfit?** This is precisely what the ratchet's **bounded active-cap
  + contribution score** prevent. An overfit predicate (right for last Tuesday's
  rhythm, wrong now) has a *declining contribution score*; CUSUM demotes it
  before it does harm. The Weibull/retrieval-anchored decay (R3) sinks a predicate
  that stops being retrieved-and-confirmed. **Overfitting is just Library Drift in
  the temporal predicate, and the ratchet is already the answer to Library
  Drift.**

So item 15 is not open — it is skill-compilation applied to the temporal guard,
governed by the same ratchet that keeps every other learned unit honest. The
recoverable moment becomes a compiled, contribution-scored, decaying predicate
the brain runs itself.

**(d) Buildable sketch.**
```
# orion_dream, after consolidation, for goal-kinds with stable defer/act outcomes:
for kind in goal_kinds:
    obs = ledger.defer_act_outcomes(kind)              # chronos-stamped
    if stable(obs) and contribution(kind) >= TAU_HI:
        compile_predicate(kind, learn_recoverable_window(obs))  # R1 compile → temporal guard
    # ratchet (R2) demotes/decays it the moment its contribution slips → no overfit lock-in
```

---

## Revisiting the four "GENUINELY OPEN" items

| # | Volition-memo open item | Verdict after combination | Why |
|---|---|---|---|
| **12** | Provable corrigibility under heterogeneous, swappable fuel | **REACHABLE** (Combinations 1 + 4) | Stop proving the *fuel* corrigible; make the *brain's gate* the corrigible object. Lexicographic dominance becomes a `return` statement with no model in its call stack — identical across all fuels, present and future. The swap becomes a *sensor* (cross-fuel disagreement), not a threat. |
| **13** | Compounding uncertainty across multi-day, multi-host, gossip-replicated tasks | **REACHABLE** (Combination 3) | Host B **re-derives** confidence locally via `gate()`; it does *not* inherit A's number. The PAUSE flag and already-acted facts replicate replay-safely (freshness guard + idempotency keys). Confidence is local; corrigibility is global. |
| **14** | User-mediated *goal-implantation* on the self-directed intent surface | **REACHABLE** (Combination 4, half two) | Goal-implantation is memory-poisoning at the volition layer. Defended by composing safety-triggered forgetting (R3) + Hermes fence-hardening + source-trust autonomy ceilings + cross-fuel endorsement check — all already being built one layer down. |
| **15** | The recoverable moment as a learned predicate without overfitting | **REACHABLE** (Combination 5) | It's a playbook. Learn it in dream, compile it (R1), and let the Library-Drift ratchet (R2) prevent overfit by demoting predicates whose contribution score slips. Overfitting *is* Library Drift in the temporal predicate. |

### What genuinely stays open (honesty, per the Design Law and the self-model wall)

Three things resist combination and must not be claimed closed:

1. **Calibrated *probabilistic* step-confidence from black-box CLI fuel.** The
   self-model memo is blunt: calibration at personal-AI scale is intractable
   (O2), reasoning fine-tuning *degrades* abstention, and the fuel is
   architecturally overconfident. Combination 1 sidesteps this by using
   cross-fuel *disagreement* (an ordinal, external signal) rather than any single
   fuel's *self-reported* probability — which is the right move, but it means
   Orion's confidence is **ordinal and comparative, never a calibrated
   probability.** "How sure, as a number" stays open; "more or less sure than the
   other fuel" is what we actually get. Ship ordinal Play/Ask, never a
   probability to the user.

2. **Freshness *denial* under a partition-controlling adversary.** Brain-as-
   signal §7 names it and Combination 3 inherits it: the freshness guard defeats
   replay-as-future, but an adversary who controls a relay can selectively *drop*
   fresh PAUSE/halt deltas to keep a far host pursuing a goal the user already
   paused. Detecting "I'm being kept stale" without a trusted reference clock is
   unsolved for us. The honest mitigation is a **dead-man's-switch**: a custodial
   goal whose PAUSE-channel heartbeat goes silent past a TTL self-suspends rather
   than presuming consent — degrade toward Ask on silence, never toward Play.
   That bounds the damage; it does not close the attack.

3. **Whether bounded autonomy is "real agency" or sophisticated automation.**
   The self-model memo's wall stands (O3): Orion's stance is *procedural, not
   metaphysical* — `grep` the hash-chained ledger and check whether the autonomy
   decisions track outcomes. Falsifiable beats philosophical. The volition loop
   makes Orion *behave* like a bounded autonomous agent and lets you audit
   whether it earned its rope. Whether there is "something it is like" to pursue
   a goal is silent, by Orion and by everyone else.

---

## The one-paragraph synthesis

The four "open" items in bounded autonomous volition all dissolve under one
move Orion has already made twice: **pull the hard part out of the model.** Long-
term memory came out (`orion_memory`); task state came out (`orion_taskspine`);
now the **corrigibility policy** comes out — into deterministic brain-side gates
(PAUSE, impact tiers, the executive's permission flow) that no fuel sees, reasons
about, or is asked to honor. Once corrigibility is a `return` statement with no
model in its call stack, it is trivially invariant to a fuel swap — and the
swap, far from being the threat the volition memo feared, becomes the cheapest
sensor Orion ever gets: two independent policies' disagreement on the same step,
an external uncertainty estimate no single-model agent can produce. Stack the
hash-chained ledger × the Library-Drift ratchet and autonomy becomes auditable
*and* earned — widening only when Orion's own books justify it, narrowing the
instant they rot, with the narrowing recorded as learning. Add the bundle
envelope + custody transfer + idempotency keys and that same gated, earned
autonomy runs off-grid across a partition, the kill switch crossing the gap as a
sub-50-byte beacon. What stays open is honest and small: calibrated probability
(we have ordinal cross-fuel comparison instead), freshness *denial* under a
relay-controlling adversary (bounded by a dead-man's-switch, not closed), and
the metaphysics of agency (sidestepped, audited, never claimed). **Corrigibility
under hot-swappable fuel is reachable the moment you stop trying to make the fuel
corrigible and make the brain corrigible instead. The brain doesn't swap.**
