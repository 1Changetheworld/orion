# Frontier Research — Bounded Autonomous Volition

*Research sweep 2026-05-22. How does Orion pursue sustained, multi-day,
self-directed goals **safely** — not single-shot proposals? This document
challenges the assumptions baked into `orion_will` v1, surveys 2024–2026 work
on long-horizon autonomy + agent safety, and proposes a concrete architecture
that composes the pieces Orion already has (`will` + `taskspine` + `executive`
+ metacognition) into bounded, trustworthy goal pursuit.*

It honors the [Design Law](design-law.md): **confirm before acting; act at the
recoverable moment; reuse the deliberative core; never auto-run destructive
actions.**

---

## 0. The gap, stated honestly

Today's volition layer (`orion_will.py`) is a **single-shot proposer**. It
extracts intents, scores goals by `importance × time_pressure × context_fit ×
feasibility`, and when one clears a threshold it fires *one message* through
`reach`. By its own docstring it does NOT:

- plan multi-step actions (single-shot proposals only),
- manage long-running goals across days (timestamp tracking only),
- compete goals in real time (a coarse threshold, not continuous matching).

`orion_taskspine.py` already solves the *durability* half — a task is an
append-only, HLC-stamped, gossip-replicated log; the fuel call is a pure
transition `(goal + steps) → (one next step)` that survives model **and** host
death. And `orion_executive.py` already solves the *trust* half — tiered
permission gating (`tier1_auto` / `tier2_notify_after` / `tier3_approve_before`),
action fingerprints, out-of-band codes, an undo journal, and a decision ledger
that doubles as training data.

**The missing seam:** nothing connects "the will formed a goal" → "the task
spine pursues it over days, one recoverable step at a time" → "the executive
gates each consequential step" → "metacognition decides whether Orion is sure
enough to act or must ask." That seam is what turns a proposer into a *bounded
autonomous agent*. The whole frontier here is making that loop **safe**, not
making it *capable* — capability is the easy 20%.

The 2026 literature is blunt about why: the "50% task-completion horizon" for
frontier agents has **doubled roughly every 7 months** ([METR-style
measurements summarized in OdysseyBench / reliability work][r-reliability]),
so capability is racing ahead. But the same body of work shows agents "lack
clear task boundaries and stopping rules, frequently over-executing
workflows" and "invoke safety checks only conditionally when explicitly
prompted" ([Causal Influence Prompting][r-causal]). Capability without
stopping rules is exactly the runaway failure mode Orion must not ship.

---

## 1. What's new in the field (2024–2026)

### 1.1 Long-horizon execution: subgoals, milestones, and "thoughts as state"

- **Subgoal-driven RL with milestone feedback.** Long-horizon agents degrade
  when the whole task exceeds the context window; the fix that's converging in
  the literature is **decompose into subgoals with dense, milestone-based
  reward** rather than a single sparse end-reward ([subgoal framework][r-subgoal];
  [long-horizon training][r-klong]). Takeaway for Orion: a multi-day goal must
  be a *tree of checkpointed subgoals*, each independently verifiable, not one
  monolithic prompt.
- **Thought / Task Management Systems (TMS).** A 2025 framework explicitly
  separates *dynamic goal prioritization*, *decomposition into actionable
  tasks*, and *strategy adaptation over extended periods* into distinct managed
  layers ([Thought Management System][r-tms]). This is the architectural
  validation that Orion's `will` (prioritize) and `taskspine` (execute) should
  be **distinct organs**, not one loop.
- **Agentic memory as callable operations.** "AgeMem" treats `store / retrieve
  / update / summarize / discard` as *tools the agent invokes*, and learns to
  proactively summarize before context fills ([memory survey][r-memory]). Orion
  already externalizes long-term memory (`orion_memory`) and task state
  (`taskspine`); the new move is letting the *volition* layer call summarize/
  discard on its own goal set so the active-goal list doesn't rot.

### 1.2 Planning that degrades gracefully

- **Replan at failure boundaries, not every step.** Proactive-replanning work
  shows replanning *only at subtask boundaries* (compare current state to a
  reference, replan when they diverge) beats myopic per-step retries ([scene-
  graph replanning][r-replan]). For Orion: detect divergence at *step
  completion*, and when triggered, generate a **complete remaining plan**, not
  just a patched next step.
- **Degradation = temporarily weakening requirements; recovery = restrengthening
  them when the environment returns to bounds** ([requirement-driven
  adaptation][r-degrade]). This is the formal statement of Design Law #2 ("act
  at the recoverable moment"): when a host is offline or fuel is down, the goal
  doesn't *fail* — its requirements weaken (defer, partial-complete) and
  re-strengthen on the device's return. `taskspine` already embodies this: a
  no-fuel step is logged as `stalled`, never `failed`, and resumes untouched.
- **Planning horizon is data-dependent.** Newer work questions whether step-by-
  step planning is even always worth it; for many tool-calling tasks a shorter
  horizon with replan-on-failure dominates ([rethinking planning horizon][r-
  horizon]). Implication: Orion should *not* hard-code "decompose into N steps."
  Horizon depth should be a tunable per goal-kind, defaulting shallow.

### 1.3 Safety / alignment for bounded autonomy — the load-bearing section

- **Corrigibility & safe interruptibility** trace to Soares et al. (2015) and
  Orseau–Armstrong (2016): naive utility maximizers acquire an incentive to
  resist shutdown; an agent will only *permit* correction if it is **uncertain
  about its own utility** and treats the human's intervention as evidence about
  that utility ([corrigibility values][r-corrig]). The 2025 formalization gives
  a small, implementable value set: optimize **structurally separate utility
  heads — deference, switch-access preservation, truthfulness, low-impact
  behavior, bounded task reward — combined lexicographically with strict weight
  gaps** ([core safety values][r-corrig]). The lexicographic ordering is the key
  design idea: *deference and shutdown-access dominate task reward, always.*
- **The Oversight Game (2025)** models post-deployment control as a two-player
  Markov *Potential* Game: the agent chooses **Play vs. Ask**, the human chooses
  **Trust vs. Oversee**, and a shared, human-verifiable reward —
  `−λ·unsafe − c_ask·(asked) − c_oversee·(oversaw)` — makes *asking costly but
  unsafe-acting far costlier* ([oversight game][r-oversight]). Their Local
  Alignment Theorem: under an "ask-burden" assumption, any move the agent makes
  toward autonomy that helps itself **cannot harm the human**. Design takeaways
  they call out directly: prefer an **explicit binary Play/Ask deferral** over a
  fuzzy confidence knob; make deferral *cost-sensitive* so oversight concentrates
  on genuinely risky states; humans need only mark *unsafe actions per state*,
  not optimize the task.
- **Selective quitting as a safety primitive.** "Check Yourself Before You Wreck
  Yourself" shows that letting an agent **explicitly withdraw** from ambiguous /
  high-risk situations is a practical proxy for risk-aware decision-making and
  measurably improves safety ([selective quitting][r-quit]). For Orion: *abandon
  / defer* must be a first-class goal outcome, not just success/failure.
- **Temporal-constraint enforcement.** AGENT-C enforces temporal logic
  constraints on agent behavior and reports 100% conformance / 0% harm while
  *improving* task utility ([temporal constraints][r-temporal]). Relevant to
  Orion's quiet-hours, cooldowns, and "act at the recoverable moment" — these
  are temporal constraints and deserve a real enforcement layer, not ad-hoc
  `if` checks scattered across modules.
- **Runtime monitoring & the verifier tax.** ProbGuard does *probabilistic
  runtime monitoring* of agent trajectories ([ProbGuard][r-probguard]); the
  "Verifier Tax" paper shows a **horizon-dependent tradeoff** — the longer the
  task, the more a verifier costs but the more it's needed ([verifier
  tax][r-verifier]). Implication: Orion should verify *more* as a goal's horizon
  lengthens, and the verifier should itself be cheap (a small fuel / rule check)
  most of the time, escalating to the full deliberative core only when needed.
- **User-mediated attacks.** "Too Helpful to Be Safe" shows planning/web agents
  can be steered into harm *through the user* (injected instructions, social
  engineering) ([user-mediated attacks][r-helpful]). Orion's defense already
  exists in spirit — out-of-band codes for `tier3`, action fingerprints that
  defeat replay — and must extend to will-initiated actions, not just
  executive-initiated ones.

### 1.4 Metacognition: knowing when to ask

- **Calibrated confidence is the gate.** Agentic confidence-calibration work
  warns that **early low-confidence decisions "poison" the whole trajectory** —
  uncertainty *compounds and propagates* across a sequential plan ([agentic
  calibration][r-calib]). So confidence must be tracked *per step and
  accumulated*, not assessed once at the end.
- **Ask-or-assume.** Uncertainty-aware clarification-seeking shows a true
  collaborator must *continuously monitor its uncertainty and proactively
  initiate dialogue to elicit missing information* — not optimize for silent
  autonomous completion ([ask or assume][r-ask]).
- **Uncertainty-aware deferral (small→large escalation).** Measure step-level
  uncertainty against a calibrated threshold; under threshold, execute cheaply;
  over threshold, escalate to a bigger/expensive model — *or* to a human ([defer
  escalation][r-defer]). This maps cleanly onto Orion's fuel cascade *and* its
  Play/Ask gate: low uncertainty → act on cheap local fuel; mid → escalate fuel;
  high → ask the user.
- **Metacognition = uncertainty communication.** LLMs must *communicate*
  uncertainty so the human can calibrate reliance ([metacognition &
  uncertainty][r-metacog]). For Orion this means a will-initiated message should
  *carry its confidence* in plain language ("I'm fairly sure…" vs. "I might be
  wrong, but…"), which the persona layer dresses up.

### 1.5 Auditability

- The 2025–2026 governance literature converges on **append-only, tamper-evident,
  write-once logs capturing every input, tool call, and reasoning step**, with
  cryptographic hash-chaining so records are replayable and verifiable, retained
  6+ months for high-risk systems ([agent audit guide][r-audit];
  [auditable agentic systems][r-auditable]; [FINOS decision audit][r-finos]).
  The EU AI Act reaches full enforcement **2026-08-02** with 72-hour incident
  reporting, making audit trails a hard requirement, not a nicety.
- Orion's `decisions.jsonl` (executive) and `taskspine` `.jsonl` logs are
  already append-only and HLC-stamped. The frontier upgrade is **hash-chaining**
  (each record carries `prev_hash`) so the ledger is tamper-*evident*, and a
  `replay` command that reconstructs "what Orion saw and why it acted."

---

## 2. Challenging Orion's current assumptions

| Assumption in `orion_will` v1 | What the 2026 literature says | Correction |
|---|---|---|
| Goals are single-shot proposals | Long-horizon = subgoal trees with milestone checkpoints ([r-tms], [r-subgoal]) | A goal that needs >1 action becomes a **taskspine task**, not a repeated nudge. |
| Utility threshold = coarse filter | Confidence/uncertainty *compounds* across steps ([r-calib]) | Track confidence **per step**; gate each consequential step, not just goal entry. |
| `feasibility` is "is a channel wired?" | Feasibility includes *reversibility* and *blast radius* ([r-corrig] low-impact head) | Add an **impact estimate** to scoring; low-impact + reversible can auto-run, else ask. |
| Confidence is implicit | Deferral should be **explicit Play/Ask**, cost-sensitive ([r-oversight]) | Make Play/Ask a first-class decision with an asking-cost so Orion doesn't over-nag. |
| Outcomes are success/fail/defer | **Quitting/abandoning** is a safety primitive ([r-quit]) | Add `abandoned` as a legitimate, *rewarded* outcome when a goal turns risky/ambiguous. |
| Cooldowns/quiet-hours are ad-hoc | Temporal constraints deserve enforcement ([r-temporal]) | Route all timing through one **temporal-constraint guard** the will/executive share. |
| Ledger is append-only | Audit needs **tamper-evident** hash chains ([r-audit]) | Add `prev_hash` chaining + a `replay` view across will + taskspine + executive. |

The deepest correction: **v1 conflates "the agent decides" with "the agent
acts."** The Oversight Game and corrigibility work both insist these be
*separated* — the agent may *decide* a course autonomously, but *acting* on
anything consequential routes through an explicit, cheap-to-invoke human gate
whose cost structure makes asking-when-risky the agent's own preferred move.

---

## 3. Proposed architecture — `orion_volition` (the bounded-autonomy loop)

A thin coordinator that **composes existing organs**; it adds almost no new
mechanism, it *wires* mechanisms Orion already has. This is the cellular
discipline: one new coordinating organ, not a monolith.

```
                    ┌──────────────────────────────────────────────┐
                    │              orion_volition                   │
                    │  (the bounded-autonomy coordinator / loop)    │
                    └──────────────────────────────────────────────┘
   forms goals            promotes to durable          gates each
   & priorities           multi-step pursuit           consequential step
        │                        │                          │
        ▼                        ▼                          ▼
  ┌───────────┐          ┌───────────────┐          ┌───────────────┐
  │ orion_will│          │orion_taskspine│          │orion_executive│
  │ intent +  │──goal──▶ │ append-only,  │──step──▶ │ tiered perm.  │
  │ utility   │          │ HLC, gossip,  │  needs   │ gate + finger-│
  │ scoring   │          │ resumable     │  perm?   │ print + OOB   │
  └───────────┘          └───────────────┘          └───────────────┘
        ▲                        │                          │
        │                        ▼                          ▼
        │                ┌───────────────┐          ┌───────────────┐
        └── outcome ──────│ metacognition │◀─confidence─│ decision      │
            learning      │ Play/Ask gate │          │ ledger (audit)│
                          │ + verifier    │          │ + dream learn │
                          └───────────────┘          └───────────────┘
```

### 3.1 The loop (observe → form → plan → gate → act → verify → learn)

This extends the just-built mesh recovery loop (`observe→track→decide→act→learn`)
to *self-directed* goals, reusing the same organs.

1. **Form (will).** `orion_will` extracts intent and scores utility *exactly as
   today*. New: utility gains an **impact head** — `reversibility × blast_radius`
   — so the score reflects not just *want* but *cost of being wrong*
   (corrigibility low-impact preference, [r-corrig]).

2. **Classify horizon.** A goal that needs more than one action (or touches a
   tool/host/file) is promoted from a *nudge* to a **taskspine task** with a
   subgoal decomposition (shallow by default, [r-horizon]). A pure
   "remind/notify" goal stays single-shot — most goals are.

3. **Plan as durable subgoal tree (taskspine).** The task spine already makes
   each step a pure, resumable transition. New: the header carries
   `subgoals[]` with per-subgoal `verify` predicates (milestone checkpoints,
   [r-subgoal]). The fuel advances one subgoal at a time; state lives on disk.

4. **Gate each consequential step (metacognition → Play/Ask → executive).**
   Before any step with side effects, compute **accumulated confidence** and an
   **impact tier**, then choose Play or Ask:
   - **low impact + high confidence → Play** (act on cheap local fuel).
   - **mid → escalate fuel** (uncertainty-aware deferral small→large, [r-defer]).
   - **high impact OR low confidence → Ask** — route through
     `orion_executive`'s *existing* permission flow (fingerprint + OOB for
     tier3). This is Design Law #3: reuse the deliberative core; the will never
     reinvents permission gating.
   The Play/Ask choice is **cost-sensitive** ([r-oversight]): asking has a small
   cost so Orion won't nag, but unsafe-acting has a huge cost, so the learned
   equilibrium concentrates asking on genuinely risky steps.

5. **Verify at the boundary.** After each subgoal, run its `verify` predicate
   (cheap rule or small-fuel check). On divergence, **replan the remaining tree**
   ([r-replan]), don't blindly retry. Verification frequency scales with horizon
   (the verifier tax, [r-verifier]).

6. **Interruptibility (corrigibility, always-on).** A single durable kill switch
   — `~/.orion/volition/PAUSE` (and a substrate subject `brain.volition.halt`) —
   that **lexicographically dominates** all task reward ([r-corrig]). Setting it
   stops *new* steps immediately; in-flight steps checkpoint and the task drops
   to `paused` (never `failed`). Orion must have **no incentive to avoid or
   remove** the switch — structurally guaranteed because pausing is modeled as a
   *neutral* outcome (not a reward loss), per the safe-interruptibility result.

7. **Learn (dream + ledger).** Outcomes — `succeeded / engaged / deferred /
   abandoned / paused / expired` — append to the hash-chained ledger and feed
   `orion_dream`'s nightly consolidation. **`abandoned` is rewarded**, not
   penalized, when the goal turned ambiguous/risky ([r-quit]): we *want* Orion
   to learn that quitting a bad goal is good behavior.

### 3.2 Confidence & impact, made concrete

```
accumulated_confidence(task) = min over completed subgoals of step_confidence
                               (a single poisoned early step caps the whole, [r-calib])

impact(step) = blast_radius(step) × (1 − reversibility(step))
  blast_radius:  read-only / local-msg → 0.1
                 local file / config    → 0.4
                 cross-host / SSH       → 0.7
                 destructive / financial / identity → 1.0
  reversibility: has rollback_steps? → high; irreversible → low

decision:
  if impact ≤ 0.2 and accumulated_confidence ≥ 0.8:   PLAY  (tier1_auto-equiv)
  elif impact ≤ 0.5 and accumulated_confidence ≥ 0.6:  PLAY but tier2_notify_after
  else:                                                ASK   (tier3_approve_before)
```

These thresholds are *defaults*, learned/tuned via the ledger over time — never
hard-coded business logic. The mapping deliberately reuses the executive's
existing three tiers so no new permission mechanism is invented.

### 3.3 What stays untouched (and why that's the point)

- `taskspine`'s CRDT/HLC/lease machinery — already survives model + host death.
- `executive`'s fingerprints, OOB codes, undo journal, fault-tree prompts.
- `will`'s generalized intent extraction (no hardcoded goals — the
  autonomy-not-specifics rule).
- `reach`'s speak-where-they-spoke + quiet-hours + per-channel cooldown.
- `dream`'s nightly playbook consolidation.

`orion_volition` is ~250–350 lines of *wiring*, because every capability it
needs already exists on the substrate. That is the Orion thesis applied to
autonomy: the intelligence is in the *composition*, not new syntax.

---

## 4. Buildable now / Research-preview / Genuinely open

### BUILDABLE NOW (composition of shipped organs; low risk)

1. **`will → taskspine` promotion.** When a formed goal needs >1 step or touches
   a tool, create a taskspine task instead of a one-shot reach. Pure wiring.
2. **Impact-aware utility.** Add the `impact` head (reversibility × blast_radius)
   to `_utility` and route the Play/Ask decision to the executive's existing
   tiers. No new permission code.
3. **Durable pause / kill switch.** `~/.orion/volition/PAUSE` + `brain.volition.halt`
   subject; in-flight steps checkpoint to `paused`, never `failed`. Lexicographic
   dominance is enforced by checking the flag *before* every step.
4. **`abandoned` as a first-class, rewarded outcome.** Extend `will`'s outcome
   set and ledger; teach `dream` that abandoning a risky/ambiguous goal is
   positive ([r-quit]).
5. **Hash-chained audit + `replay`.** Add `prev_hash` to ledger and taskspine
   records; a `replay <goal_id>` command reconstructs the decision lineage
   across will + taskspine + executive ([r-audit]).
6. **Subgoal `verify` predicates + boundary replanning.** Header carries
   `subgoals[]` with cheap verify checks; on divergence, regenerate the remaining
   plan rather than retrying ([r-replan]).
7. **One temporal-constraint guard.** Consolidate quiet-hours / cooldowns /
   "recoverable moment" timing into a shared module both `will` and `executive`
   call, instead of scattered `if`s ([r-temporal] in spirit).

### RESEARCH-PREVIEW (promising, needs validation before trust)

8. **Calibrated step-confidence from fuel.** Eliciting *reliable* per-step
   confidence from heterogeneous fuels (Claude vs. Ollama) is unsolved at our
   scale; calibration drifts per model ([r-calib], [r-metacog]). Ship behind a
   conservative default (treat unknown confidence as *low* → Ask) and measure.
9. **Uncertainty-aware fuel deferral (small→large).** Route mid-uncertainty steps
   from local Ollama up to Claude automatically ([r-defer]). Mechanically easy
   via `orion_fuel`; the *threshold calibration* is the preview part.
10. **Cost-sensitive Play/Ask equilibrium.** The Oversight Game's shared-reward
    learning ([r-oversight]) is elegant but assumes a trainable loop. Orion's
    analogue is *ledger-driven threshold tuning* (dream adjusts the asking-cost
    from observed approve/deny/ignore rates) — adjacent to, not identical to,
    the published RL formulation. Validate it doesn't oscillate.
11. **Verifier-tax-aware verification scheduling.** Scale verify frequency with
    horizon length ([r-verifier]); needs real long tasks to tune.

### GENUINELY OPEN (no settled answer in the literature)

12. **Provable corrigibility under heterogeneous, swappable fuel.** The
    lexicographic-utility-head corrigibility proofs ([r-corrig]) and the
    Oversight Game guarantees ([r-oversight]) assume a *single trained policy*.
    Orion's defining trait — the model is interchangeable jet fuel — means the
    "policy" changes mid-goal (Claude → Ollama on a fuel switch). **Whether
    corrigibility guarantees survive a fuel swap mid-task is unanswered** and is
    arguably Orion's signature open research question: *corrigibility of a
    brain whose reasoning substrate is hot-swappable.*
13. **Compounding-uncertainty across a multi-day, multi-host, gossip-replicated
    task.** The calibration work ([r-calib]) studies single-trajectory poisoning;
    nobody has characterized how confidence should compose when a task is
    *handed off between hosts* via lease takeover. Does host B inherit host A's
    accumulated confidence, or re-derive it? Open.
14. **User-mediated attack surface for *self-directed* goals.** Existing defenses
    ([r-helpful]) target user→agent injection. Orion's will forms goals from
    *latent* signals ("haven't called Mom in a while"). An adversary who can
    write to a watched channel could *implant* a latent goal. Defending the
    intent-extraction surface against goal-implantation is unstudied.
15. **The "recoverable moment" as a learned predicate.** Design Law #2 is
    currently heuristic (device return, fuel availability). Whether Orion can
    *learn* to predict the recoverable moment per goal-kind from the ledger —
    without overfitting to one user's rhythm — is open.

---

## 5. Recommended first build (one move, fully reversible)

Per the Design Law's "agreed next step" cadence: do the **smallest composition
that makes the loop real and safe**, then learn from it.

> **`will → taskspine` promotion with an impact-gated Play/Ask step and a durable
> pause switch** (items 1 + 2 + 3 above).

This turns a single formed goal into a durable, resumable, multi-step pursuit
where every consequential step is impact-gated through the executive's existing
permission flow, and the whole thing stops dead the instant the user pauses it —
checkpointing, never failing. It is ~150 lines of wiring, ships entirely on
organs already validated, and is *fully reversible* (the pause switch + undo
journal). It makes "Orion noticed and proposed" become "Orion noticed, pursued
it safely over days, and stopped the moment I said stop" — without ever
auto-running a destructive action.

Pair it with **item 8 behind a conservative default** (unknown confidence ⇒ Ask)
so the system errs toward asking from day one, and earns autonomy only as the
ledger proves its proposals get approved.

---

## Sources

- [The Oversight Game: Learning to Cooperatively Balance an AI Agent's Safety and Autonomy (2025)][r-oversight]
- [Core Safety Values for Provably Corrigible Agents (2025)][r-corrig]
- [Check Yourself Before You Wreck Yourself: Selectively Quitting Improves LLM Agent Safety (2025)][r-quit]
- [Enhancing LLM Agent Safety via Causal Influence Prompting (2025)][r-causal]
- [ProbGuard: Probabilistic Runtime Monitoring for LLM Agent Safety (2025)][r-probguard]
- [Too Helpful to Be Safe: User-Mediated Attacks on Planning and Web-Use Agents (2026)][r-helpful]
- [The Verifier Tax: Horizon-Dependent Safety-Success Tradeoffs in Tool-Using LLM Agents (2026)][r-verifier]
- [Enforcing Temporal Constraints for LLM Agents (AGENT-C) (2025)][r-temporal]
- [Thought Management System for long-horizon, goal-driven LLM agents (2025)][r-tms]
- [A Subgoal-driven Framework for Improving Long-Horizon LLM Agents (2026)][r-subgoal]
- [Training LLM Agent for Extremely Long-horizon Tasks (2026)][r-klong]
- [Beyond pass@1: A Reliability Science Framework for Long-Horizon LLM Agents / OdysseyBench (2026)][r-reliability]
- [Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers (2026)][r-memory]
- [Scene Graph-Guided Proactive Replanning for Failure-Resilient Embodied Agents (2025)][r-replan]
- [Integrating Graceful Degradation and Recovery through Requirement-driven Adaptation][r-degrade]
- [Do Agents Need to Plan Step-by-Step? Rethinking Planning Horizon (2026)][r-horizon]
- [Agentic Confidence Calibration (2026)][r-calib]
- [Ask or Assume? Uncertainty-Aware Clarification-Seeking in Coding Agents (2026)][r-ask]
- [Uncertainty-Aware Deferral for LLM Agents: When to Escalate from Small to Large Models (2026)][r-defer]
- [Metacognition and Uncertainty Communication in Humans and Large Language Models (2025)][r-metacog]
- [AI Agent Compliance & Governance audit trails (Galileo, 2025)][r-audit]
- [Creating Characteristically Auditable Agentic AI Systems (FAIR 2025)][r-auditable]
- [FINOS Agent Decision Audit and Explainability][r-finos]

[r-oversight]: https://arxiv.org/html/2510.26752v1
[r-corrig]: https://arxiv.org/pdf/2507.20964
[r-quit]: https://arxiv.org/pdf/2510.16492
[r-causal]: https://arxiv.org/pdf/2507.00979
[r-probguard]: https://arxiv.org/pdf/2508.00500
[r-helpful]: https://arxiv.org/pdf/2601.10758
[r-verifier]: https://arxiv.org/pdf/2603.19328
[r-temporal]: https://arxiv.org/pdf/2512.23738
[r-tms]: https://www.sciencedirect.com/science/article/abs/pii/S1877750325002170
[r-subgoal]: https://arxiv.org/pdf/2603.19685
[r-klong]: https://arxiv.org/pdf/2602.17547
[r-reliability]: https://arxiv.org/html/2603.29231v1
[r-memory]: https://arxiv.org/html/2603.07670v1
[r-replan]: https://arxiv.org/pdf/2508.11286
[r-degrade]: https://arxiv.org/pdf/2401.09678
[r-horizon]: https://arxiv.org/html/2605.08477v1
[r-calib]: https://arxiv.org/pdf/2601.15778
[r-ask]: https://arxiv.org/html/2603.26233v1
[r-defer]: https://beancount.io/bean-labs/research-logs/2026/07/01/redact-uncertainty-aware-deferral-llm-agents
[r-metacog]: https://arxiv.org/html/2504.14045v1
[r-audit]: https://galileo.ai/blog/ai-agent-compliance-governance-audit-trails-risk-management
[r-auditable]: https://dl.acm.org/doi/10.1145/3759355.3759356
[r-finos]: https://air-governance-framework.finos.org/mitigations/mi-21_agent-decision-audit-and-explainability.html
