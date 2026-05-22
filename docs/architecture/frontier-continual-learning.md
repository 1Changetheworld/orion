# Frontier — Weight-Free Continual Learning

*Filed 2026-05-22. Companion to [true-intelligence-frontier-research.md](true-intelligence-frontier-research.md),
which covered durable working memory and memory-side consolidation. This memo attacks the
**procedural / learning** side: does Orion's brain actually get **better** over time, or does it
just get **bigger**?*

The hard question this memo answers: **what separates genuine continual LEARNING from a growing
log?** Orion already has the scaffolding most agents lack — a nightly `orion_dream` that
consolidates the executive's `decisions.jsonl` into plain-text playbooks (with CUSUM demotion),
an `orion_metacognition` layer (HOT-2 write-back + confidence scoring), and an `orion_consolidate`
that dedups/prunes the graph (archive-not-delete). And it correctly refuses to fine-tune weights —
that would weld the brain to one model and break the "model is fuel" thesis.

So the question is not "should Orion learn without weights?" — it already does. The question is
**whether its weight-free learning is real**, and the field has, in the last six months, produced
both a sharp definition of the failure mode and concrete mechanisms to fix it.

Each recommendation is tagged **[BUILDABLE NOW]**, **[RESEARCH-PREVIEW]**, or **[GENUINELY OPEN]**.

---

## The core claim (read this first)

**A log becomes learning at exactly three transitions, and Orion has built the first, half-built
the second, and not built the third:**

1. **Append → consolidate.** Raw experience is abstracted into reusable units (playbooks, merged
   memories). *Orion does this:* `orion_dream` groups decisions by symptom+service and writes
   playbooks; `orion_consolidate` merges duplicate nodes. **Shipped.**

2. **Consolidate → curate.** The set of learned units is *governed*: low-value units are demoted,
   conflicting units are reconciled, and the active set is bounded so retrieval doesn't rot.
   *Orion half-does this:* CUSUM demotes playbooks whose success rate drifts down, and
   archive-not-delete keeps it reversible. But there is **no bound on the active playbook/skill
   set, no per-unit contribution attribution, and no birth-time conflict check**. This is the gap
   the 2026 "Library Drift" result says is where self-evolving agents silently die. **Half-built.**

3. **Curate → compile.** A *repeatedly-solved* task stops being re-reasoned by a fuel and becomes a
   **deterministic fast path** — code/route the brain runs itself, zero fuel tokens, constant
   latency. *Orion does NOT do this for procedures.* It has a deterministic *answer* layer for
   recall, but the executive still re-reasons recurring fixes through a fuel every time. **Not
   built — and it is the single highest-value weight-free-learning move available.**

The blunt version: **learning is curation plus compilation, not accumulation.** Orion's dream is a
good consolidator but a weak curator and not yet a compiler. The rest of this memo is how the field
closes those two.

---

## Q1 — What is the actual frontier of weight-free continual learning?

### What the field settled on (2025–2026)

The consensus crystallized this year, and it is **Orion's exact thesis, validated by others**:
Letta's position paper frames an agent as the pair **(θ, C)** — frozen weights θ plus context C —
and argues continual learning should happen **in token space (C), not weight space (θ)**, because
weight updates lose the three things token-space keeps: **interpretability** (human-readable
memory), **portability across models**, and **trivial rollback**. ([Letta][letta]) Those are
verbatim Orion design values (`archive-not-delete` = rollback; plain-text playbooks =
interpretability; "model is fuel" = portability). Orion is not behind the frontier here; it is *on*
it.

The frontier *past* "store text and retrieve it" has three live directions:

1. **Memory as a non-parametric policy, not just a retrieval store** (JitRL, Jan 2026). Instead of
   retrieving past text into the prompt, JitRL stores `(state, action, return)` triplets and at
   inference computes an advantage `Â(s,a)` from neighbors, then **adds it directly to the model's
   logits**: `z'(s,a) = z(s,a) + β·Â(s,a)`. This additive rule is the closed-form optimum of
   KL-constrained policy improvement — i.e. it is *real* RL, done with no gradients, ~30× cheaper
   than RL fine-tuning (WebRL), and it beats prompt-based ICL because it doesn't degrade with
   context length. ([JitRL][jitrl]) **The catch for Orion: it needs token-logit access**, which
   the CLI fuels (Claude/Codex/Gemini chat) do not expose. So JitRL is a *local-fuel-only*
   capability (Ollama exposes logits) — important to know, important not to over-claim.

2. **Distillation in context, not into weights** (In-Context Distillation w/ self-consistency
   cascades, Dec 2025). A cheap frozen "student" answers; you sample it k times; if the samples
   agree you trust it, if they diverge you escalate to the expensive "teacher." Over time the
   student's *context* (not weights) accumulates the teacher's resolved cases. ([ICD][icd]) This is
   a token-cost-reduction loop that maps cleanly onto Orion's fuel cascade.

3. **Token-to-weight distillation as a deferred bridge.** Even the token-space camp concedes a
   future where consolidated memory is distilled into weights "for additional personalization and
   efficiency" *across model generations* — generating synthetic training data / eval rubrics from
   the brain rather than fine-tuning on raw logs. ([Letta][letta]) For Orion this is **GENUINELY
   OPEN** and thesis-adjacent: it would only be safe if the brain remained canonical and the
   distilled weights were a disposable *cache* of the brain, never the source of truth. Worth a
   one-paragraph design note, not a build.

### Honest hype-check

- **"Agents that learn continuously" marketing** is mostly retrieval-augmented logging. The
  field's own benchmarks say so: *MemoryAgentBench* reports that **no current system masters all
  four memory competencies, and most fail conspicuously on selective forgetting.** ([Memory
  survey][memsurvey]) Growing memory is easy; *governing* it is the unsolved part — exactly Orion's
  curate gap.
- **JitRL's logit math is real and elegant**, but the "30× cheaper than RL" headline hides that it
  only applies where you have logit access and reusable trajectories. For a personal brain whose
  primary fuels are black-box CLIs, it is a niche local-fuel feature, not a centerpiece.
- **Sleep-time / dream consolidation is real and Orion already has it** — the novelty others are
  publishing (Letta "sleep-time compute") is something Orion shipped as `orion_dream`. Don't
  re-buy it; *harden* it.

---

## Q2 — Skill compilation: the missing third transition

This is where Orion has the most to gain and the field has the clearest recipe.

### What the field does

The 2026 "**Compiled AI**" architecture names the asymmetry exactly: *generating* correct logic
benefits from LLM reasoning; *executing* it thousands of times does not. Runtime agents conflate
the two by invoking a model on every transaction. The fix: **confine LLM invocation to a one-time
compilation step, then deploy validated static code for all subsequent executions**, with a
proactive cache of operator outputs to skip even that. ([Compiled AI][compiled])

**ProcMEM** (Feb 2026) does the agent-side version: it learns **reusable procedural memory** from
experience via non-parametric PPO, so recurring situations map situation→action without redoing the
full reasoning. ([ProcMEM][procmem]) **Voyager** (the origin, 2023) is the proof that
frozen-LLM agents accumulate reusable *executable* skills with self-verification gating admission to
the library. ([Voyager][voyager])

### What this means for Orion concretely

Orion's `orion_executive` re-reasons recurring fixes through a fuel every time, then `orion_dream`
writes a *prose* playbook about it. **Prose is the wrong artifact for a thing that always runs the
same way.** When a playbook's CUSUM success rate is high *and* its action sequence is stable across
N firings, that playbook is no longer "advice for a fuel" — it is a **deterministic procedure** that
should be promoted out of the fuel path entirely into a structured, executable step list the brain
runs itself.

This is the procedural twin of Orion's existing **deterministic answer layer** (which already
bypasses the fuel for recall). The recall layer answers "what do I know" from the brain; this would
answer "what do I do here" from the brain. Same move, procedural side. **It is the single most
on-thesis weight-free-learning feature Orion can build**: it makes the brain measurably faster and
cheaper the more it's used, with zero model dependency, and the deterministic path is *more*
portable than any fuel because it has no fuel at all.

> **Recommendation 1 — Skill compilation in the dream. [BUILDABLE NOW]**
> Extend `orion_dream` with a *compile* phase after consolidation: for each playbook where
> (a) CUSUM success ≥ τ_hi, (b) firing count ≥ N_min, and (c) the recorded action sequence is
> stable (low edit-distance variance across firings), emit a structured `compiled_procedure`
> (ordered tool/dispatch steps + guards) and register it with `orion_executive` as a fast path
> tried *before* any fuel call. Keep the prose playbook as the fallback if a guard fails.
> Archive-not-delete on demotion. Ingredients all exist: dream scheduler, CUSUM, the executive's
> decision ledger, the dispatch table. **Measurable win:** fuel-token-per-recurring-fix and
> time-to-fix both drop to ~zero on compiled cases; that delta is the proof the brain *learned*.

---

## Q3 — Library Drift: why Orion's curate gap is a launch risk, not a nicety

The most directly relevant 2026 result is **"Library Drift: Diagnosing and Fixing a Silent Failure
Mode in Self-Evolving LLM Skill Libraries."** It is almost a written warning addressed to Orion's
dream module.

### The failure mode, defined operationally

Library Drift = the library accumulates artifacts until **expected pass@1 with accumulated skills
falls *below* the no-skill baseline.** It is *silent* — no errors, no obvious broken skill, just a
slow slide. Three compounding sub-modes ([Library Drift][drift]):

1. **Stagnation** — skills accumulate but never reach the solver (no routing signal). *Orion risk:*
   playbooks written but the executive never consults them at decision time.
2. **Bloat** — unbounded growth degrades retrieval precision until injected context becomes
   *harmful*. *Orion risk:* the prior memo already flagged 1474-node graph bloat; the playbook set
   has the same unbounded shape, and there is no active-set cap.
3. **Erosion** — over-aggressive governance deletes useful skills faster than they form. *Orion
   risk:* an over-tuned CUSUM threshold demoting good playbooks on noise.

### The diagnostics — which Orion does not yet collect

The paper's key insight: **drift is invisible in end-task scores but visible in per-skill
diagnostics first.** They instrument:

- **Per-skill contribution score** (success/failure ratio attributable to *that* unit),
- **Attribution verdicts** — an LLM categorizes each firing as helped / hurt / neutral,
- **Router engagement** — fraction of tasks that actually receive an injection (healthy 70–80%;
  drift case dropped to 19%).

A **declining mean contribution score** and a **rising "hurt" fraction** flag drift *before*
aggregate metrics move. ([Library Drift][drift])

### The fix — "the ratchet"

Three mechanisms that together guarantee monotonic non-regression:

1. **Outcome-driven retirement** — retire a unit after `N_min` trials if contribution < τ.
2. **Bounded active-cap** — a hard limit (their C=50) on simultaneously active units, evicting the
   lowest performer on overflow.
3. **Authoring prior** — constrain the synthesizer to consistent, scoped units to reduce harmful
   births at the source (a *birth-time* conflict/dup check, not just death-time cleanup).

> **Recommendation 2 — Make `orion_dream` a curator, not just a consolidator. [BUILDABLE NOW]**
> Add to each playbook a **contribution score** and **firing verdicts** (the executive already logs
> outcomes — extend the schema with a helped/hurt/neutral tag, cheaply scored by the same fuel that
> ran the fix). Then implement the ratchet: a **bounded active-playbook cap** with eviction of the
> lowest contributor (archive-not-delete, reversible), and a **birth-time conflict/dup check** in
> the consolidator (don't write a playbook that contradicts or duplicates an active one — reconcile
> instead). This converts CUSUM-on-success (already shipped) into the full SSGM/ratchet governance
> the field says is the actual hard part. **Measurable win:** mean contribution score is the
> single number that says "the brain is still learning" vs "the brain is rotting" — surface it on
> the dashboard. CUSUM on *that* aggregate is the launch tripwire.

This is not gold-plating: Library Drift's whole point is that a self-evolving library that *looks*
fine in demos degrades below baseline in the field. Orion's dream is exactly such a library. Curate
is the difference between the thesis being true and being a slow lie.

---

## Q4 — Principled forgetting and decay: what to prune, when, reversibly

Orion's `orion_consolidate` already does archive-not-delete dedup/prune, and the prior memo
recommended moving memory decay into the dream. The 2026 work adds *shape* and *taxonomy* worth
adopting deliberately rather than ad hoc.

### Borrow the decay *shape*, not just a heuristic

The SSGM framework prunes/archives by a **freshness threshold**, and Huang et al. propose a
**Weibull decay** on time-since-last-successful-*retrieval* — more expressive than plain exponential
because the shape parameter `k` tunes *fast-early* vs *delayed* forgetting per domain.
([SSGM/survey][memsurvey], [FadeMem][fademem]) **Dual-layer** designs (FadeMem) split a slow-decay
**strategic** layer (identity, preferences, durable decisions — should barely decay) from a
fast-decay **episodic** layer (one-off interactions). ([FadeMem][fademem])

Orion already has the right primitives — temporal half-life and contested flags. The upgrade is:
**decay on last-successful-retrieval (not creation time), reset on re-anchor (recall refreshes
salience), and route node *type* to a decay curve** (preferences/identity → near-flat; transient
status → fast). That is the difference between forgetting *stale* facts and forgetting *unused-but-
permanent* ones (your birthday is rarely retrieved and must never decay).

### Borrow the forgetting *taxonomy* for governance

The survey's four-way taxonomy — **passive decay / active deletion / safety-triggered / adaptive
reinforcement** — is a useful governance checklist. ([Memory survey][memsurvey]) Orion does passive
decay and (via consolidate) a form of active merge. It lacks **safety-triggered forgetting** (active
removal of malicious/poisoned inputs) — relevant because anything that ingests into a brain is an
injection surface, and the `governing-evolving-memory` work explicitly flags memory poisoning as the
risk that forgetting mitigates. ([Governing memory][memsurvey])

> **Recommendation 3 — Typed, retrieval-anchored decay + safety-triggered forgetting in the dream.
> [BUILDABLE NOW]**
> In the nightly dream: (a) decay salience on **time-since-last-successful-retrieval**, reset on
> recall; (b) route each node to a decay curve by **type** (Weibull-shaped if you want the
> early/late knob, but even typed exponential is a real improvement), strategic layer near-flat;
> (c) add a **safety-triggered** path that flags + archives memories matching injection/poison
> signatures (contradicts a high-confidence identity fact, arrived via an untrusted channel,
> spikes after a single session) for review rather than silent trust. All archive-not-delete.
> **Measurable win:** strategic facts survive disuse, episodic noise sinks, and the brain has an
> immune response to memory poisoning — three things the field says almost no system does.

---

## Q5 — Does metacognition close the log→learning gap, or just label the log?

Candid take: `orion_metacognition`'s HOT-2 write-back and confidence scoring is **the right
substrate but it currently observes more than it governs.** Confidence scores that don't *change a
decision* are decoration. The frontier use of metacognition that matters here is **using the
confidence signal as the gate for the cascades above**:

- It is the **uncertainty detector** for In-Context Distillation (trust the cheap student when
  confidence/self-consistency is high, escalate when low). ([ICD][icd])
- It is the **promotion gate** for skill compilation (only compile a procedure to deterministic
  when metacog confidence in its stability is high — Voyager's self-verification gate, reused).
- It is the **birth filter** for the Library-Drift authoring prior (don't write a low-confidence
  playbook into the active set).

> **Recommendation 4 — Wire metacog confidence into the learning gates, don't just store it.
> [BUILDABLE NOW]**
> Make `orion_metacognition`'s confidence the explicit gate on: (1) student-vs-teacher fuel
> escalation, (2) compile-to-deterministic promotion, (3) playbook birth admission. This is the
> minimal change that turns metacognition from a labeler of the log into a *governor* of learning.
> No new module — three call-sites. **Measurable win:** the rate at which high-confidence
> predictions are later contradicted (calibration error) becomes a tracked number; if it falls over
> time, the brain is genuinely learning its own reliability.

---

## What is hype, what is real, what to skip

- **Skip token-to-weight distillation for now** — **[GENUINELY OPEN]**, thesis-risky, only safe as a
  disposable cache of the brain. One design paragraph, no build.
- **JitRL logit-space RL** — **[RESEARCH-PREVIEW]**, real and elegant but **needs logit access**, so
  it is a *local-fuel-only* (Ollama) capability. Park it as "the way Orion does RL when running on a
  white-box local model"; do not build it as a core path while CLIs are primary fuel. Do not
  over-claim it.
- **"Continuously learning agent" products** — mostly retrieval logging. The field's own
  benchmarks (MemoryAgentBench) say selective forgetting is unsolved across the board. Orion's edge
  is that it already has the dream + consolidate scaffolding; the win is *governance*, not more
  storage.
- **Real and buildable now:** skill compilation (R1), library-drift curation (R2), typed
  retrieval-anchored decay + safety forgetting (R3), metacog-as-gate (R4). All four use existing
  modules and existing signals. None touch model weights. All four make the brain *measurably*
  better with use — which is the only honest definition of learning.

---

## Ranked recommendations

| # | Move | Tag | Touches | Why it matters |
|---|---|---|---|---|
| **1** | **Skill compilation in the dream** — promote stable, high-success playbooks into deterministic executable procedures the executive runs *before* any fuel call. | **BUILDABLE NOW** | `orion_dream`, `orion_executive`, dispatch table, deterministic-answer-layer pattern | The procedural twin of the recall fast-path. Brain gets faster + cheaper the more it's used, with *zero* fuel dependency. Most on-thesis learning feature available. |
| **2** | **Curator-grade dream** — per-playbook contribution scores + helped/hurt verdicts + bounded active-cap with lowest-contributor eviction + birth-time conflict/dup check (the "ratchet"). | **BUILDABLE NOW** | `orion_dream`, `orion_executive` ledger, dashboard | Directly closes the **Library Drift** failure mode the 2026 paper says silently kills self-evolving libraries. Mean contribution score = the "is the brain still learning" tripwire. |
| **3** | **Typed, retrieval-anchored decay + safety-triggered forgetting** — decay on last-successful-retrieval, per-type curves (strategic near-flat), poison-signature archival. All reversible. | **BUILDABLE NOW** | `orion_dream`, `orion_consolidate`, `orion_memory`, temporal/contested flags | Stops forgetting permanent-but-unused facts (birthday) while sinking episodic noise; adds an immune response to memory poisoning. Field says almost no system does this. |
| **4** | **Metacog as governor, not labeler** — confidence gates student/teacher escalation, compile-promotion, and playbook birth. | **BUILDABLE NOW** | `orion_metacognition`, `orion_fuel`, `orion_dream`, `orion_executive` | Three call-sites turn stored confidence into decisions. Calibration-error-over-time becomes a measurable proof of self-reliability learning. |
| **5** | **In-context distillation cascade** — cheap student fuel + self-consistency check, escalate to teacher on divergence, accumulate resolved cases in context. | **RESEARCH-PREVIEW** | `orion_fuel`, `orion_metacognition` | Token-cost reduction loop on the existing cascade. Real, but secondary to 1–4; build after the gates (R4) exist. |
| **6** | **JitRL logit-space soft updates** for white-box local fuel only. | **RESEARCH-PREVIEW** | `orion_fuel` (Ollama), local-model path | Genuine gradient-free RL, ~30× cheaper than fine-tune — but needs logit access CLIs don't expose. Local-fuel niche, not core. Don't over-claim. |
| **7** | **Token-to-weight distillation** of consolidated memory across model generations. | **GENUINELY OPEN** | — | Thesis-risky; only safe as a disposable cache of the canonical brain. Design note, not a build. |

---

## The one-line frame

*Orion already learns in token space — the field just validated that as the right call. But it
**consolidates** without fully **curating** and never **compiles**. Genuine continual learning is
curation plus compilation, not accumulation: bound and govern the playbook set so it can't silently
rot (Library Drift), and promote the procedures that always work into deterministic fast paths the
brain runs without any fuel at all. Both are buildable now, both use modules that already exist, and
both make the brain measurably faster, cheaper, and more correct the more it's used — without ever
touching a model weight.*

---

## Sources

- [letta]: Letta — *Continual Learning in Token Space.* https://www.letta.com/blog/continual-learning
- [jitrl]: *Just-In-Time Reinforcement Learning: Continual Learning in LLM Agents Without Gradient Updates* (arXiv 2601.18510). https://arxiv.org/html/2601.18510v1
- [icd]: *In-Context Distillation with Self-Consistency Cascades* (arXiv 2512.02543). https://arxiv.org/pdf/2512.02543
- [drift]: *Library Drift: Diagnosing and Fixing a Silent Failure Mode in Self-Evolving LLM Skill Libraries* (arXiv 2605.19576). https://arxiv.org/html/2605.19576
- [compiled]: *Compiled AI: Deterministic Code Generation for LLM-Based Workflow Automation* (arXiv 2604.05150). https://arxiv.org/html/2604.05150
- [procmem]: *ProcMEM: Learning Reusable Procedural Memory from Experience via Non-Parametric PPO for LLM Agents* (arXiv 2602.01869). https://arxiv.org/pdf/2602.01869
- [voyager]: *Voyager: An Open-Ended Embodied Agent with Large Language Models* (arXiv 2305.16291). https://arxiv.org/abs/2305.16291
- [memsurvey]: *Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers* (arXiv 2603.07670) and *Governing Evolving Memory in LLM Agents (SSGM)* (arXiv 2603.11768). https://arxiv.org/html/2603.07670v1 · https://arxiv.org/html/2603.11768v1
- [fademem]: *FadeMem: Biologically-Inspired Forgetting for Efficient Agent Memory* (arXiv 2601.18642). https://arxiv.org/pdf/2601.18642
- [amem]: *A-MEM: Agentic Memory for LLM Agents* (NeurIPS 2025, arXiv 2502.12110). https://arxiv.org/abs/2502.12110

*Note: arXiv IDs with 26xx prefixes are 2026 filings surfaced in current search; verify exact
identifiers before citing externally.*
