# Synthesis — Where hermes-agent Patterns Supercharge Orion's Frontier

*Filed 2026-05-22. Invention pass, not literature review. Companion to and
dependent on [hermes-agents-study.md](hermes-agents-study.md) (what was absorbed
and what to skip). Cross-anchored in the five frontier memos
([continual-learning](frontier-continual-learning.md),
[autonomous-volition](frontier-autonomous-volition.md),
[self-model](frontier-self-model.md),
[brain-as-signal-v2](frontier-brain-as-signal-v2.md),
[unified-brain](orion-unified-brain.md)) and gated by [design-law.md](design-law.md).*

> **The thesis of this doc.** The hermes-agent study correctly catalogued the
> *parts* worth absorbing (skill self-improvement loop, SKILL.md standard,
> subagent delegation, sanitize_context, agent-curated memory nudges). But a
> part bolted on is cosmetic. The value is in **fusion**: each hermes pattern,
> when wired into an Orion organ *and* a frontier-memo mechanism, unlocks a
> capability that neither hermes nor Orion has alone. This doc invents those
> three-way fusions, ranks them transformative-vs-cosmetic, and is ruthless
> about the thesis violations the fusions must avoid.

---

## 0. The frame: absorption is a fusion reaction, not a graft

Hermes-agent is Orion's closest competitor *and* a donor of validated mechanics.
The trap is treating its parts as features to copy. A hermes feature copied into
Orion is at best redundant (Orion already has a stronger version) and at worst a
thesis violation (its provider-key-first config, its monolithic gateway). The
only absorptions worth doing are the ones where a hermes pattern is the **missing
catalyst** that lets an Orion organ + a frontier finding combine into something
new.

The selection rule, applied to every candidate below:

1. **Does a hermes pattern supply a mechanic Orion lacks?** (If Orion already
   has it stronger — fuel routing, cross-CLI portability — skip.)
2. **Does an Orion organ supply the durability/portability/autonomic substrate
   the hermes pattern lacks?** (Hermes skills die with the process; Orion's
   taskspine/gossip/dream do not.)
3. **Does a frontier-memo finding supply the *governance* that makes the fusion
   safe and non-rotting?** (Hermes's self-improvement loop has no Library-Drift
   ratchet; Orion's volition loop has no skill that compiles.)

A fusion that needs all three legs is transformative. A fusion missing leg 3
(governance) is the exact silent-failure the continual-learning memo warns
about. A fusion missing leg 2 (Orion substrate) is just running hermes.

---

## 1. THE COMPILING SKILL LIBRARY — hermes's closed loop × Library-Drift ratchet × dream's compile phase

**(a) Capability unlocked.** A skill library that doesn't just *grow* and doesn't
just *self-edit* — it **compiles**. A procedure Orion has solved enough times,
reliably enough, with a stable enough action sequence, stops being prose advice
for a fuel and becomes a deterministic fast path the brain runs itself: zero
tokens, constant latency, no model dependency. And the library is *governed* so
it can't silently rot below the no-skill baseline. This is the single most
on-thesis learning capability available, and hermes is the catalyst that makes
it concrete.

**(b) The exact combination.**

- **hermes pattern:** the *closed skill self-improvement loop* — hermes
  autonomously creates a skill after a complex task succeeds, edits its own
  `SKILL.md` during use, and (critically) treats the skill file as the durable
  unit of learned procedure. Orion absorbed only the *skeleton* (`learn_skill`
  writes once, `times_used` never increments, `confidence` static). The live
  loop is what's on the table.
- **Orion organs:** `orion_dream` (nightly consolidator — already groups
  decisions by symptom+service, already CUSUM-demotes), `orion_executive`
  (decision ledger = the firing record), the **deterministic-answer-layer
  pattern** (`orion_deterministic` already bypasses the fuel for *recall*), and
  the dispatch table (the executable steps a compiled procedure runs).
- **Frontier finding:** continual-learning memo's **three transitions**
  (append→consolidate→**curate**→**compile**) plus the **Library-Drift ratchet**
  (per-skill contribution score, helped/hurt verdicts, bounded active-cap with
  lowest-contributor eviction, birth-time conflict check). The memo's
  Recommendation 1 (compile phase) and Recommendation 2 (curator-grade dream)
  *are* the missing legs 2 and 3.

The fusion: **hermes's loop gives the "skill self-improves during use" mechanic;
Orion's dream gives it durability + a host that survives model death; the
Library-Drift ratchet gives it the governance that keeps the self-improvement
from drifting below baseline; and the deterministic-answer-layer pattern gives
the *terminal state* of a fully-learned skill — compiled out of the fuel path
entirely.** Hermes self-improves a skill *in prose forever*; Orion self-improves
it until it's stable, then **graduates it out of the LLM**.

**(c) Why it's on-thesis.** Hermes's self-improving skill still runs through a
model every time — the skill is advice the model re-reads. That keeps hermes
model-bound: a worse fuel re-reasons a solved problem worse. Orion's compiled
procedure has *no fuel at all* on the hot path — it is *more* portable than any
skill hermes can write, because portability across models is trivial when there
is no model. This is "memory is the intelligence, model is fuel" taken to its
limit: the most-learned procedures need *no* fuel. The Library-Drift ratchet is
what makes it honest rather than a slow lie — the continual-learning memo is
blunt that an ungoverned self-evolving library degrades below baseline in the
field, which is exactly what hermes ships without.

**(d) Buildable sketch.**

```
# orion_dream.py — add a compile phase AFTER consolidate, BEFORE sleep
# Each playbook/skill gains the Library-Drift instrumentation:
#   contribution_score, firings[{verdict: helped|hurt|neutral, hlc}], action_seq[]

for skill in active_skills:                       # the hermes loop, governed
    update_contribution(skill)                    # success/fail ratio (R2)
    if skill.contribution < TAU_LO and skill.firings >= N_MIN:
        archive(skill)                            # outcome-driven retirement (ratchet)
if len(active_skills) > ACTIVE_CAP:               # bounded cap (ratchet, C~50)
    archive(lowest_contributor())                 # evict, archive-not-delete

for skill in active_skills:                       # the COMPILE transition
    if (skill.contribution >= TAU_HI               # high success
        and skill.firings >= N_MIN                 # repeated
        and edit_distance_variance(skill.action_seq) < EPS  # stable sequence
        and metacog_confidence(skill) >= 0.8):     # self-model gate (see §4)
        proc = compile_to_procedure(skill.action_seq)   # ordered dispatch steps + guards
        register_fast_path(orion_executive, proc)  # tried BEFORE any fuel call
        skill.compiled = True                      # prose kept as fallback if a guard fails

# birth-time check when dream WRITES a new skill (authoring prior):
def author_skill(candidate):
    if conflicts_with_active(candidate) or duplicates_active(candidate):
        reconcile(candidate)                       # don't add a contradicting unit
    else:
        add(candidate)
```

The compiled procedure is registered with `orion_executive` exactly where
`remedy_steps` already live — the executive *already* runs ordered steps with
permission tiers; a compiled skill is just a `remedy_steps` array promoted out of
the fuel-reasoning path. **Measurable proof of learning:** fuel-tokens-per-
recurring-fix → ~0 on compiled cases; mean contribution score is the "is the
brain still learning vs rotting" tripwire on the dashboard.

**Verdict: TRANSFORMATIVE.** This is the headline fusion. Hermes alone never
compiles (stays prose, stays model-bound). Orion alone has the dream but the
continual-learning memo says it "consolidates without curating and never
compiles." Hermes's *loop* is the catalyst that turns Orion's dream from a
consolidator into a compiler.

---

## 2. DURABLE MESH-REPLICATED SUBAGENTS — hermes delegation × taskspine children × gossip × bounded volition

**(a) Capability unlocked.** Parallel sub-task pursuit that survives model death
*and* host death and load-balances across the mesh — children that are durable,
resumable, gossip-replicated, and individually permission-gated. Hermes has
clean *parallelism*; Orion has clean *durability*; neither has both.

**(b) The exact combination.**

- **hermes pattern:** `delegate_tool.py` — spawn child agents with isolated
  context, restricted toolsets (children can't recurse, can't touch memory,
  can't `send_message`), `MAX_DEPTH=2`, `MAX_CONCURRENT_CHILDREN=3`, parent sees
  only the summary. This is a *well-bounded* delegation contract — the depth and
  concurrency caps and tool-restriction are the valuable parts.
- **Orion organs:** `orion_taskspine` (append-only HLC step log, fuel = pure
  `(state)→(next)` transition, survives model + host death), `orion_gossip`
  (the step-log *is already a CRDT* — replicates mesh-wide for free, per
  unified-brain §V.1), `orion_volition`/`orion_executive` (the Play/Ask gate +
  tiered permissions).
- **Frontier finding:** autonomous-volition memo's **subgoal trees with
  milestone checkpoints** ([r-tms], [r-subgoal]) and **per-step confidence
  that compounds** ([r-calib], "a single poisoned early step caps the whole").
  The memo explicitly says a multi-day goal must be "a tree of checkpointed
  subgoals, each independently verifiable, not one monolithic prompt."

The fusion: **hermes's delegation contract (depth cap, concurrency cap, tool
restriction, parent-sees-summary) becomes the *spawning rule* for taskspine
children.** A volition goal that decomposes into independent subgoals spawns each
subgoal as a *child taskspine task* — not an in-process thread that dies with the
host (hermes's fatal limitation), but a durable, gossip-replicated task another
host can lease and advance. The hermes restriction set ("children can't recurse,
can't touch memory directly") maps onto Orion's *membrane* visibility lattice and
the executive's tier gates: a child runs at a *narrower* permission tier than its
parent, can't spawn its own children past `MAX_DEPTH`, and surfaces only a signed
summary back to the parent task.

**(c) Why it's on-thesis.** The hermes-agents-study already flagged this as
"build it the Orion way: children should be taskspine tasks (durable,
mesh-replicable), not in-process threads." This fusion *is* that — but it adds the
two legs the study left implicit: (1) the gossip leg makes a child resumable on
*another host*, which hermes cannot do at all, and (2) the volition leg makes
each child *permission-gated and confidence-tracked*, so a fanned-out parallel
workload still obeys Design Law #1 (confirm before acting) and #3 (reuse the
deliberative core). A child task is just a taskspine task with a `parent_id` and a
narrower tier — no new permission mechanism, per the volition memo's discipline.

**(d) Buildable sketch.**

```
# orion_volition.py — when a goal decomposes into independent subgoals:
def fan_out(goal, subgoals):
    assert depth(goal) < MAX_DEPTH                 # hermes cap (2)
    children = []
    for sg in independent(subgoals)[:MAX_CONCURRENT]:  # hermes cap (3)
        child = taskspine.create(
            parent_id=goal.task_id,
            steps=sg.steps,
            tier=narrower(goal.tier),              # child < parent permission (hermes restriction)
            tools=restrict(goal.tools),            # no recurse, no direct memory, membrane-gated
            verify=sg.milestone_predicate)         # subgoal checkpoint ([r-subgoal])
        children.append(child)                     # CRDT entry → gossiped mesh-wide for free
    return children

# Any host with spare fuel leases an unclaimed child via existing gossip lease:
#   child advances one pure (state)->(next) step, checkpoints, releases lease.
# Parent task's verify predicate fires when all children report signed summaries.
# accumulated_confidence(parent) = min over children (poisoned-step cap, [r-calib]).
# A PAUSE flag (volition kill switch) halts new child steps; in-flight checkpoint to `paused`.
```

**Verdict: TRANSFORMATIVE, but build only on a concrete parallel workload.**
The hermes-agents-study correctly says "defer until there's a concrete parallel
use case; building it now would gold-plate." That holds. But when the use case
arrives, this fusion — not a hermes-style in-process delegate — is the design.
The transformative part is that Orion's children are the *first* durable,
mesh-leasable, permission-gated subagents; hermes's die with the process and run
at the parent's full privilege.

---

## 3. THE SKILL.md STANDARD AS THE COMPILE ARTIFACT — agentskills.io format × deterministic fast-paths × portability

**(a) Capability unlocked.** The unit that a compiled skill (§1) is *written as*
becomes a **human-readable, version-controlled, standards-aligned `SKILL.md`** —
not opaque JSON, not a fuel-prompt string. Wins three things at once:
auditability (the user can read and edit what the brain learned), portability
(the same SKILL.md is consumed by every CLI Orion already targets, and conforms
to the agentskills.io standard Claude skills also align with), and a clean
*two-layer* artifact: the YAML frontmatter is the deterministic guard/route
metadata, the body is the prose fallback.

**(b) The exact combination.**

- **hermes pattern:** the `SKILL.md` Markdown + YAML-frontmatter format (`name`,
  `description`, `version`, `license`, `metadata.hermes.tags`, `related_skills`),
  platform scoping, agentskills.io compatibility.
- **Orion organs:** `orion_deterministic` (the fast-path executor), the compiled
  procedure from §1, `orion_memory`'s skill store (currently opaque JSON).
- **Frontier finding:** continual-learning memo's compile transition (a stable
  high-success skill becomes "a structured, executable step list the brain runs
  itself") + self-model memo's **provenance reconstruction** (O1: Orion
  reconstructs source from *records it kept*, not from introspection — the
  SKILL.md `derivation_sources` frontmatter field is exactly such a record).

The fusion: **the frontmatter holds the deterministic contract (trigger
predicate, guards, ordered dispatch steps, contribution_score, compiled-flag,
derivation_sources); the Markdown body holds the prose fallback the fuel reads
when a guard fails.** One file is *both* the fast-path definition *and* the
graceful-degradation advice. The compile phase (§1) writes the frontmatter; the
self-improvement loop (hermes) edits the body; the Library-Drift ratchet (§1)
governs the active set; the deterministic layer reads the frontmatter to run the
fast path with zero fuel.

**(c) Why it's on-thesis.** A compiled procedure stored as opaque JSON is a black
box — the user can't audit what their brain learned, and it isn't portable to the
other CLIs. SKILL.md makes the learned procedure a *thing the user owns and can
read*, which is the same property the brain-file has and the same reason Orion's
memory is plain-text. It is also the only format that's simultaneously
machine-executable (frontmatter) and the audit artifact the volition memo demands
(hash-chainable, replayable). Crucially: adopting the *format* is not adopting
hermes's runtime — the hermes-agents-study is right that this is "standards-
aligned for free" without importing any hermes dependency.

**(d) Buildable sketch.**

```markdown
---
name: restart-stalled-imessage-daemon
version: 3                          # bumped by the hermes self-improve loop
compiled: true                      # §1 promoted it out of the fuel path
trigger: { symptom_class: CHANNEL_LIMBO, service: imessage }
contribution_score: 0.94            # Library-Drift ratchet (§1)
firings: 27
tier: tier2_notify_after            # executive permission (reused, not reinvented)
steps:                              # deterministic dispatch sequence — NO fuel
  - { dispatch: probe_channel, args: {svc: imessage}, guard: status==dormant }
  - { dispatch: launchctl_reload, args: {label: imessage}, rollback: prior_state }
  - { dispatch: probe_channel, args: {svc: imessage}, verify: status==active }
derivation_sources: [decision:8f2a, decision:9c1b]   # self-model O1 provenance, kept not introspected
---
## Fallback (read only if a guard fails)
If the daemon won't reload, the cause is usually a stale lock at
`~/.orion/channels/imessage.lock`. Remove it, then re-run the reload step.
```

`orion_deterministic` reads the frontmatter and runs `steps` with zero tokens;
on a guard miss it hands the body to the fuel. **Migrate the existing JSON skill
store to SKILL.md with the JSON kept only as a fast lookup index** (the
hermes-agents-study's exact recommendation), then the compile phase (§1) writes
into this format natively.

**Verdict: TRANSFORMATIVE as the *artifact* of §1; cosmetic as a standalone
migration.** Migrating opaque JSON to SKILL.md *by itself* is a nice-to-have
(human-editable, portable). But as the **storage format for compiled procedures**,
it's load-bearing: it's what makes the learned fast-path auditable, ownable, and
portable — the difference between "the brain learned something" and "the brain
learned something the user can read, edit, and carry to another tool."

---

## 4. CONFIDENCE-GATED SELF-IMPROVEMENT — hermes's autonomous skill-edit × cross-fuel disagreement × the compile gate

**(a) Capability unlocked.** Hermes's most dangerous mechanic — *the agent edits
its own skills autonomously* — made **safe** by gating every self-edit on a
confidence signal the editing fuel *cannot fake to itself*. A skill is only
self-improved (or compiled) when an *independent* signal says the improvement is
trustworthy. This is the antidote to the self-model memo's central finding:
the fuel is architecturally overconfident, so an agent that trusts its own
"this skill is better now" judgment will confidently rot its own library.

**(b) The exact combination.**

- **hermes pattern:** autonomous skill self-edit during use (the agent decides
  its own skill needs changing and rewrites the SKILL.md).
- **Orion organs:** `orion_coherence_probe` (multi-fuel), `orion_metacognition`
  (HOT-2 ledger, confidence scoring), `orion_dream` (the compile gate from §1).
- **Frontier finding:** self-model memo's **Signal C — cross-fuel disagreement
  as the epistemic-uncertainty sensor** (the biggest unbuilt win; "no competitor
  architecture can replicate it — they have one model") + the hard rule that
  **self-report may *lower* a confidence, never *raise* it** (overconfidence is
  the mechanistically-installed failure mode) + **AbstentionBench**: reasoning
  fuels are *worse* at knowing when to abstain, so a reasoning fuel proposing a
  confident self-edit deserves *more* scrutiny.

The fusion: **before any autonomous skill-edit or compile-promotion, route the
proposed change through a *second* fuel and measure disagreement.** Hermes lets a
single model rewrite its own skill on that model's say-so — exactly the
overconfidence trap. Orion, being multi-fuel by design, asks: does a *different*
fuel agree this skill should change this way? High cross-fuel disagreement →
refuse the self-edit (or refuse the compile). The editing model's own confidence
can only *block* a change, never authorize one.

**(c) Why it's on-thesis.** This is the self-model memo's thesis applied to the
hermes loop: "the brain's job is to distrust the fuel's confidence by
construction." Hermes's self-improvement is *single-fuel introspection* — the
exact thing the 2026 papers (content-agnostic introspection, wired-for-
overconfidence) say is unreliable. Orion turns the hermes loop's biggest liability
into a showcase of Orion's structural advantage: it is the *only* architecture
that can cross-check a self-edit against an independent fuel, because it's the
only one with more than one fuel. The §1 compile gate (`metacog_confidence ≥
0.8`) becomes a *cross-fuel-agreement* gate, not a single-model self-report.

**(d) Buildable sketch.**

```
# orion_dream.py compile/self-improve gate — replace single-model confidence
def safe_to_evolve(skill, proposed_change):
    a = current_fuel.evaluate(skill, proposed_change)        # may LOWER, never RAISE
    b = second_available_fuel.evaluate(skill, proposed_change)
    epistemic = semantic_disagreement(a, b)                  # Signal C, not lexical
    if epistemic > THRESH:                                   # fuels disagree → genuine uncertainty
        log_refusal(skill, reason="cross_fuel_disagreement") # surface, don't silently edit
        return False
    # reasoning-heavy fuel proposing a confident edit gets MORE scrutiny (AbstentionBench)
    if is_reasoning_fuel(current_fuel) and a.confidence > 0.9:
        return require_extra_corroboration(skill)
    return min(a.confidence, b.confidence) >= 0.8            # the LOWER bound gates, asymmetric
```

Gate fires only on high-stakes evolutions (compile-promotion, skill retirement,
identity-adjacent skills) — the token cost (2 fuel calls) is real, so it's gated
to the cases that matter, exactly as the self-model memo's P2 prescribes.

**Verdict: TRANSFORMATIVE.** This is the fusion that makes hermes's signature
mechanic (autonomous self-edit) *safe* in a way hermes itself cannot be, using
the one structural property hermes lacks (multiple fuels). It directly converts
"the closest competitor's risky feature" into "the thing only Orion can do
safely."

---

## 5. NUDGE-AS-WORKSPACE-CANDIDATE — hermes's memory nudge × global workspace × empathy gate

**(a) Capability unlocked.** Volitional "should I persist this?" memory writes
that compete for attention *the right way* — not as a periodic system-prompt
interrupt (hermes's blunt version), but as a candidate in Orion's global
workspace, gated by the empathy layer's read of user state. The brain decides to
remember something *because that candidate won the salience competition*, not
because a timer fired.

**(b) The exact combination.**

- **hermes pattern:** agent-curated memory with **periodic nudges** — the system
  prompt periodically reminds the model to volitionally write to memory.
- **Orion organs:** `orion_workspace` (bandwidth-limited salience competition,
  winner broadcast — *verified live, ticking, salience decay correct*),
  `orion_empathy` (reads focus/fatigue/availability, "brake never censor"),
  Mem0-style auto-classification already in `orion_memory`.
- **Frontier finding:** self-model memo's principle that signals enter the
  workspace by *surprise/salience* (P3: a dropping coherence score is a surprise
  spike → workspace ignition) — the workspace is the right arbiter of "is this
  worth attention," far better than a timer.

The fusion: **hermes's nudge becomes a workspace candidate.** When the brain
encounters something the deterministic Mem0 classifier marks NOOP but that has
high salience (novel, emotionally weighted, contradicts a held belief), it doesn't
nudge the fuel on a timer — it injects a "consider persisting X" candidate into
the workspace, where it competes against everything else for the limited
spotlight. If it wins *and* the empathy layer says the user isn't mid-focus, the
brain volitionally persists (or surfaces a "want me to remember this?" via reach).

**(c) Why it's on-thesis.** The hermes-agents-study ranks the nudge "lower
priority" because Orion's deterministic Mem0 classifier already covers the common
case "more on-thesis (less reliance on the fuel's volition)." Correct — and this
fusion *keeps* that property: the nudge isn't replacing the deterministic
classifier, it's the *complement for what the classifier misses*, and it routes
through the **workspace** (deterministic salience competition) rather than the
fuel's volition. So the volitional-feeling behavior is actually arbitrated by an
Orion organ, not the model. The empathy gate ("brake never censor") ensures it
respects user state — hermes's periodic nudge has no such governor and will
interrupt regardless.

**(d) Buildable sketch.**

```
# orion_memory.py classify() — when Mem0 says NOOP but salience is high:
verdict = mem0_classify(item)                      # ADD/UPDATE/DELETE/NOOP (deterministic, primary)
if verdict == NOOP and salience(item) > S_HI:      # novel / contradicts-held / emotionally-weighted
    workspace.submit_candidate(                    # NOT a timer nudge — a salience competitor
        kind="consider_persist", payload=item, salience=salience(item))

# orion_workspace tick (already running): if this candidate wins the spotlight:
def on_workspace_winner(c):
    if c.kind == "consider_persist" and empathy.user_available():   # brake, never censor
        memory.persist(c.payload, source="volitional")
    elif c.kind == "consider_persist":
        reach.queue("Want me to remember this?", payload=c.payload) # ask, respect quiet hours
```

**Verdict: COSMETIC-LEANING, worth doing only after §1/§4.** Honest grading: the
deterministic Mem0 classifier already does the heavy lifting on-thesis, and the
workspace already exists. This fusion is a *refinement* — it makes the
edge-case-volitional-persist feel alive and routes it through the right organ
rather than a crude timer. It's the *correct* way to absorb hermes's nudge (don't
copy the timer; make it a workspace candidate), but it's not transformative. Build
it as polish, not as a headline. The hermes-agents-study's "lower priority" call
holds.

---

## 6. FENCE-HARDENING AS THE INGRESS IMMUNE GATE — hermes's sanitize_context × safety-triggered forgetting × the freshness guard

**(a) Capability unlocked.** A single, coherent **ingress integrity boundary** for
everything entering the brain — recall injection, mesh deltas, channel inbound —
that defends three distinct attacks with one discipline: prompt-injection via
memory content, memory-poisoning via untrusted channels, and semantic-rollback
via replayed-as-future deltas.

**(b) The exact combination.**

- **hermes pattern:** `sanitize_context` — hermes strips fence-escape sequences
  from stored content before injecting it, so a malicious memory can't break out
  of the `<memory-context>` fence and spoof instructions to the fuel. Orion uses
  the fence but does *not* harden it (hermes-agents-study WORTH-ABSORBING #2).
- **Orion organs:** `orion_brain_portable.remember()` (the fence injection point),
  `orion_membrane` (visibility lattice), `transports/identity.py` (the gossip
  ingress).
- **Frontier findings:** (1) continual-learning memo's **safety-triggered
  forgetting** (R3: flag + archive memories matching injection/poison signatures
  — contradicts a high-confidence identity fact, arrived via untrusted channel,
  spikes after a single session); (2) brain-as-signal-v2's **freshness/replay
  guard** (§2: per-author HLC high-water mark + sign `(delta,
  observed_max_remote_hlc)` to defeat semantic-rollback / replay-as-future).

The fusion: **the fence-sanitization, the poison-signature archival, and the HLC
freshness guard are three faces of one rule — *nothing enters the brain's trusted
state without passing an integrity gate scoped to its channel*.** Recall content
gets fence-sanitized (hermes). Channel-inbound memory gets poison-signature
screened (continual-learning R3). Mesh deltas get freshness-checked (brain-as-
signal v2 §2). Implementing them as one `ingress_gate` discipline — rather than
three scattered checks — is the cellular-membrane pattern the unified-brain doc
already names (`orion_membrane` is the *egress* lattice; this is the matching
*ingress* lattice the brain-as-signal memo explicitly says is "the missing
ingress integrity rule").

**(c) Why it's on-thesis.** The brain is the intelligence; anything that can write
to the brain is an attack on the intelligence itself. Hermes hardened only the
fuel-prompt fence; Orion's attack surface is wider (mesh, channels, recall) *and*
its defense should be unified, because the membrane is already the place privacy
is "enforced in code" (unified-brain §II). This adds the ingress half of a
boundary Orion already has half of. It's small, urgent (the brain-as-signal memo
tags the freshness guard "security-urgent"), and entirely brain-side / model-
agnostic.

**(d) Buildable sketch.**

```
# A single ingress discipline, one gate per source-class:
def ingress_gate(item, source_class):
    if source_class == "recall":
        item.content = strip_fence_escapes(item.content)     # hermes sanitize_context
    elif source_class == "channel":
        if poison_signature(item):                            # continual-learning R3
            archive_for_review(item); return REJECT           # safety-triggered forgetting
    elif source_class == "mesh_delta":
        if item.hlc > per_author_high_water[item.author] + DRIFT_MAX:
            return REJECT                                     # brain-as-signal v2 §2 replay-as-future
        if not verify_sig(item, includes=item.observed_max_remote_hlc):
            return REJECT
    return ACCEPT

# poison_signature: contradicts a high-confidence identity fact
#                   OR arrived via an untrusted channel
#                   OR spikes after a single session (continual-learning R3)
```

**Verdict: TRANSFORMATIVE as a unified gate; the hermes piece alone is a
few-line patch.** The hermes `sanitize_context` port by itself is the small
"absorb now" the study flagged. But *fusing* it with safety-triggered forgetting
and the HLC freshness guard into one ingress-integrity organ is the
transformative move — it gives the brain a complete immune boundary (egress
membrane + ingress gate) that no single one of the three findings delivers alone.

---

## 7. The ruthless ledger — transformative vs cosmetic vs thesis-violating

| # | Fusion | hermes part | Orion organs | Frontier leg | Verdict |
|---|---|---|---|---|---|
| 1 | **Compiling skill library** | closed self-improvement loop | dream + executive + deterministic-layer + dispatch | compile transition + Library-Drift ratchet | **TRANSFORMATIVE** (headline) |
| 2 | **Durable mesh subagents** | delegation contract (caps, restriction) | taskspine + gossip + volition/executive | subgoal trees + compounding confidence | **TRANSFORMATIVE** (build on real workload only) |
| 3 | **SKILL.md as compile artifact** | SKILL.md / agentskills.io format | deterministic + memory store | compile transition + provenance (O1) | **TRANSFORMATIVE as §1's artifact**; cosmetic standalone |
| 4 | **Confidence-gated self-improve** | autonomous skill self-edit | coherence_probe + metacognition + dream gate | cross-fuel disagreement (Signal C) + AbstentionBench | **TRANSFORMATIVE** (makes hermes's risky feature only-Orion-safe) |
| 5 | **Nudge-as-workspace-candidate** | periodic memory nudge | workspace + empathy + memory | salience-ignition (P3) | **COSMETIC-leaning** (correct absorption, polish not headline) |
| 6 | **Ingress immune gate** | sanitize_context | brain_portable + membrane + transports/identity | safety-triggered forgetting (R3) + freshness guard (v2 §2) | **TRANSFORMATIVE as unified gate**; few-line patch alone |

### Genuinely transformative (do these)
- **§1 the compiling skill library** is the one to build first. It's the fusion
  the founder's own example named, it closes the continual-learning memo's
  highest-value gap (compile), and hermes's loop is the precise catalyst.
- **§4 confidence-gated self-improvement** rides directly on §1's gate and turns
  hermes's most-dangerous mechanic into Orion's most-defensible (cross-fuel,
  which no competitor has). Build it *as* the §1 compile gate, not separately.
- **§6 ingress immune gate** is small, security-urgent, and completes a boundary
  Orion already half-owns. The hermes `sanitize_context` port is the seed.

### Real but conditional
- **§2 durable subagents** — transformative, but the hermes-agents-study's
  "defer until a concrete parallel workload" is correct. When it's time, this
  fusion (durable + gossiped + permission-gated children) is the design, not a
  hermes in-process delegate.
- **§3 SKILL.md** — build it *as the storage format for §1's compiled
  procedures*, where it's load-bearing; not as a standalone migration, where it's
  merely nice.

### Cosmetic (do last, or not at all as a headline)
- **§5 nudge-as-workspace-candidate** — the *correct* way to absorb hermes's
  nudge, but the deterministic Mem0 classifier already does the on-thesis work.
  Polish, not a centerpiece.

### Thesis violations the fusions must never cross (restated as guardrails)
- **No fine-tuning on hermes datasets.** Every fusion above lives in the brain
  (dream, taskspine, membrane), never in trained weights. §1's compiled procedure
  is *less* model-dependent than any skill, not more. (hermes-agents-study SKIP #8.)
- **No API-key-first config.** Nothing here touches the fuel cascade's
  CLI-keychain-first ordering. §4 uses *whatever two fuels are available*, not a
  privileged provider. (SKIP #9.)
- **No monolithic gateway, no six terminal backends.** §2's subagents are
  taskspine tasks on the existing substrate, not a hermes-style in-process
  delegate or a provider-config gateway. §6's ingress gate is a brain-side
  discipline, not a gateway. Orion's cellular channel/intent pattern already wins;
  none of these fusions regress it. (SKIP #10.)
- **No trusting the fuel's own confidence.** §4 hard-codes the self-model rule:
  a fuel's self-report may *lower* a gate, never *raise* it. The fusions that
  involve self-improvement (§1, §4) are *only* safe because the authorizing signal
  is cross-fuel disagreement, not single-model introspection.

---

## 8. One-paragraph synthesis

Hermes-agent is worth absorbing in exactly the places where one of its validated
mechanics is the missing catalyst for a fusion of an Orion organ and a frontier
finding — and nowhere else. The transformative fusions are three, and they
cluster: **hermes's closed self-improvement loop turns Orion's dream from a
consolidator into a compiler** (§1) — a genuine skill library where the
most-learned procedures graduate out of the fuel path entirely into deterministic
fast paths, governed by the Library-Drift ratchet so it can't silently rot;
**hermes's autonomous skill-edit, the competitor's riskiest feature, becomes
only-Orion-safe** (§4) by gating every self-edit on cross-fuel disagreement, the
one signal a single-model agent structurally cannot produce; and **hermes's
context-fence sanitization seeds a unified ingress immune gate** (§6) that
completes the brain boundary Orion already half-owns. Durable mesh-replicated
subagents (§2) and SKILL.md as the compile artifact (§3) are real and worth
building, but conditionally — §2 on a concrete parallel workload, §3 as the
storage format for §1. The memory-nudge (§5) is cosmetic: the correct absorption
is to make it a workspace candidate, but the deterministic classifier already
carries the load. Every fusion stays brain-side, model-agnostic, and CLI-keychain-
first — because the moment an absorption requires fine-tuning, a privileged
provider, or a monolithic gateway, it has stopped supercharging Orion's thesis and
started inverting it.
