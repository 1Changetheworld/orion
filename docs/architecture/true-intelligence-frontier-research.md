# True Intelligence Frontier — Research Memo

*Filed 2026-05-19. Commissioned after a live failure exposed two dependence points:
(1) a long multi-step task lived in the **fuel's** context, so a CLI timeout/rate-limit
lost task progress even though long-term memory persisted — there is no brain-resident
durable **working memory / task spine** that lets a fresh fuel resume; (2) the main host
had only one strong CLI wired, so the fuel cascade had no peer to fall to.*

This memo answers five research questions, challenges Orion's own assumptions where they
deserve it, and ends with ranked, buildable recommendations tied to **named existing
modules**. Each recommendation is tagged **[BUILDABLE NOW]**, **[RESEARCH-PREVIEW]**, or
**[GENUINELY OPEN]**.

The honest one-line frame for the whole document: *Orion's thesis ("memory is the
intelligence, the model is fuel") is correct and largely shipped for **declarative**
memory. It is **not yet true for procedural / in-flight state.** Tonight's failure was not
a memory failure — it was a working-memory failure. That is the gap that most threatens the
"not reliant on any single model" claim, and it is the most buildable thing in this memo.*

---

## The core diagnosis (read this first)

Orion already separates **long-term memory** (graph + Qdrant, `orion_memory.py`) from the
**fuel** (`orion_fuel.py`). What it has NOT separated is the **task itself**. Right now a
multi-step task exists as a conversation inside one model's context window. When that fuel
dies, the *plan, the progress, the partial results, and the "what was I about to do next"*
die with it — because they were never written to the brain. `orion_will.py`'s own docstring
admits the limit: *"Plan multi-step actions (single-shot proposals only)."* `orion_executive.py`
logs **decisions** to `decisions.jsonl` but not **resumable task state**.

So the thesis "the model is interchangeable fuel" is currently only true for systems where
the task fits in a single fuel turn. The moment a task spans turns/sessions, Orion is exactly
as model-dependent as a plain CLI. **The fix is not a better model or a longer cascade — it is
to move the task out of the fuel and into the brain, the same move Orion already made for
memory.** This is the spine of recommendation #1 and it is the single highest-leverage build
in this document.

---

## Q1 — Durable working memory / task continuity

### What the field actually does

The 2024-2026 consensus pattern is **durable execution**: persist the execution state of a
long-running process externally, after every meaningful step, so the process resumes from its
last checkpoint after any interruption — completed LLM/tool calls are *not* re-run. This has
crossed into mainstream agent infra in 2025 (AWS, Cloudflare, Vercel, Azure Durable Task all
shipped agent-oriented durable execution). Two architectural families:

- **External orchestrator + deterministic replay** (Temporal): the workflow's entire event
  history — every input, decision, tool result — is stored, and on crash the workflow code is
  *replayed* against recorded results. Requires deterministic workflow code and a multi-service
  cluster. Heavy for a personal brain.
- **Embedded library + step-committed state** (DBOS): each step result is committed to a
  Postgres row in the same transaction as the step's own writes; on restart it replays from the
  last committed step. No separate daemon. **This is the right weight class for Orion.**
- **State-snapshot checkpointer** (LangGraph): saves a `StateSnapshot` at every "super-step",
  keyed by a `thread_id` that acts as a persistent cursor; `interrupt()` saves state and waits,
  resuming exactly where it paused — this is also how human-in-the-loop pauses are made durable.
  Backends are pluggable (SQLite/Postgres/DynamoDB).

The unifying idea across all three, and the one that matters for Orion's "model is fuel" thesis:
**the agent is a state machine that lives in durable storage; the model merely advances it one
transition at a time.** The LLM call is a pure function `(state) -> (next_state, side_effects)`.
If you architect this way, *any* model can pick up *any* paused task, because the task's truth
lives outside the model. The recent externalization survey (arXiv 2604.08224) frames "working
context" — open files, partial plans, active hypotheses, execution checkpoints — as the thing
that "disappears when the context window resets or a process is interrupted" **unless
externalized**. OpenHands / SWE-agents already do this: they resume from materialized workspace
artifacts rather than reconstructing from the prompt.

Plan-caching (arXiv 2506.14852) is an adjacent optimization, not the spine: caching reusable
plan templates cut cost ~50% / latency ~27% at ~96% of optimal accuracy. Useful later; not the
fix for resumability.

### Challenge to Orion's current design

Orion's instinct is to reach for the **Plexus / NATS substrate** (`orion_substrate.py`) for
everything. **NATS is the wrong layer for task state.** NATS is a *firehose* (Orion's own
`orion_workspace.py` docstring calls it that) — fire-and-forget pub/sub, no durability guarantee,
publishes become no-ops when NATS is down. Task spine state must be **durable, transactional,
and survive a full host reboot with no broker running.** That is a *file/DB* concern, not a
*bus* concern. Conflating them is the trap.

### Minimal fuel-agnostic resumable design for Orion

The smallest thing that closes tonight's gap — call it **`orion_taskspine.py`**:

1. A **task = an append-only log of steps** in `~/.orion/taskspine/<task_id>.jsonl`, plus a
   compacted `head.json` (current state). One record per step: `{step_id, intent, fuel_used,
   input_digest, output, status: planned|running|done|failed, ts, hlc}`. This is exactly the
   DBOS "commit each step" pattern, file-backed (no Postgres needed for single-host).
2. Each step is **idempotent and content-addressed**: before running a step, check if a `done`
   record with the same `input_digest` exists; if so, reuse its output instead of re-calling the
   fuel. This is deterministic replay without a Temporal cluster.
3. The fuel call is wrapped so its prompt is **reconstructed from the spine, not the chat
   history**: "Here is the goal, here are the completed steps and their results, here is the next
   pending step. Produce only the next step's output." A fresh model on a different host can
   execute this verbatim. **This is the literal mechanism that makes the model interchangeable
   mid-task.**
4. On fuel death/timeout (you already detect this — `orion_fuel.py`'s `_FUEL_ERROR_MARKERS` and
   the cascade), the current step flips back to `planned` and the spine is left intact. The next
   `query()` with any fuel resumes.
5. **Human-in-the-loop pause** is just a step with `status: awaiting_user` — identical to
   LangGraph's `interrupt()`. `orion_reach.py` already exists to ask the user; wire the resume
   back through it.

This is ~250-350 lines and reuses: `orion_fuel.py` (the executor), `orion_chronos.py` (hlc/ts
stamping), `orion_reach.py` (the interrupt channel), and the existing `decisions.jsonl` audit
pattern from `orion_executive.py`. **It does NOT require NATS, Postgres, or a new model.**

> **Sharpest recommendation in the memo:** `orion_executive.py` and `orion_will.py` should both
> stop being single-shot. The executive's "remedy_steps" array is *already a plan* — it just
> isn't durable or resumable. Make the task spine the substrate they both run *on*. The
> executive proposes a spine; the will pursues a spine; the spine survives the fuel. One
> primitive, two existing consumers.

**Tag: [BUILDABLE NOW].** Nothing here is open research. The only real design choice is
file-backed (single host, ship now) vs. SQLite (cleaner concurrency, slightly more code). Start
file-backed; the spine's append-only log *is* the migration path.

---

## Q2 — Model independence in practice (beyond a fallback cascade)

### What breaks when the model changes

The literature is blunt: swapping models is not free even when the task spine is durable. 2025-2026
findings:

- **Persona / behavioral drift across models.** PICon (arXiv 2603.25620) and "When Agents Disagree
  With Themselves" (2602.11619) show no systematic method currently verifies an agent's responses
  stay contradiction-free across a session — *and the problem worsens across model architectures.*
  "Agent Drift" (2601.04170) decomposes it into **semantic** (deviation from original intent),
  **coordination**, and **behavioral** drift, and proposes an Agent Stability Index over 12
  dimensions (response consistency, tool-usage patterns, reasoning-path stability).
- **Task-irrelevant cue sensitivity.** Up to **26.2% performance degradation** driven by
  task-irrelevant persona cues, varying by model (2602.12285). A persona file that works on a
  frontier CLI can *hurt* a small local model — which is exactly Orion's
  `feedback_persona-must-be-restrained.md` lesson (Gemini fired 10 tools on "hey", 141K tokens)
  arrived at independently. The research validates that memory entry.
- **Heterogeneous ensembles actually help** (X-MAS, arXiv 2505.16997): more candidate LLMs →
  *monotonic* performance improvement, and heterogeneous groups show **compensatory behavior when
  one agent crashes** that's absent in isolation. This is direct empirical support for the founder's
  second concern (only one strong CLI wired = no peer to fall to). **A second wired fuel is not just
  a backup; the literature says diversity itself raises the floor.**

### Challenge to Orion's current design

Orion's cascade (`orion_fuel.py`, tier-sorted) handles **availability** (model is down → next
model). It does **nothing** for **coherence** (did the swapped model still behave like Orion?).
Today, if the cascade silently drops from a frontier CLI to `phi3:mini`, Orion's *answers* change
character and **nobody checks**. That is the unmonitored failure mode hiding behind "the model is
just fuel." The thesis is only honest if Orion can *detect* when the fuel changed the behavior, not
just when it changed the name.

### Buildable moves for Orion

1. **Capability probing on detect, not just ranking.** `orion_fuel.py` ranks by static `tier`.
   Add a one-time per-fuel **capability probe**: a tiny fixed battery (can it follow a JSON schema?
   can it do a 3-step tool plan? what's its context limit? does it honor the persona's restraint?)
   run once per newly-detected fuel, cached. Result is *capability tags*, not just a tier int. The
   task spine (#Q1) then refuses to route a "needs-structured-output" step to a fuel that failed
   the JSON probe — graceful degradation by *capability*, not by *guess*. **[BUILDABLE NOW]**, builds
   on `orion_fuel.py` + `orion_preflight.py`.
2. **A golden behavioral regression suite for "is this still Orion?"** ~20 fixed prompts with
   *rubric-graded* expected behavior (uses correct name/honorific from recall; declines architecture
   questions; recalls a planted token; stays terse). Run the suite against each fuel; store a
   per-fuel coherence score. This is the "golden dataset catches regressions" pattern + the Agent
   Identity Evals metrics (Identifiability, Continuity, Consistency, Persistence, Recovery — arXiv
   2507.17257) applied to *fuel swaps* instead of model versions. When the cascade falls to a
   lower-coherence fuel, **Orion should say so** — which is precisely
   `feedback_orion-must-self-detect.md` ("Orion announces degraded state itself"). **[BUILDABLE NOW]**;
   new small module `orion_coherence_probe.py`, consumes `orion_fuel.py`, feeds
   `orion_metacognition.py` (which already scores "fuel quality" as a confidence input).
3. **Runtime drift sentinel (lightweight ASI).** Don't build the full 12-dimension ASI. Track 2-3
   cheap signals per session: honorific/name correctness, refusal-of-architecture compliance, and
   output-length stability. Spike → `brain.surprise.spike` (the channel `orion_predictor.py` already
   emits on) → workspace boosts → will narrates "I'm running on weaker fuel and may sound different."
   **[BUILDABLE NOW]**, reuses the existing surprise→workspace→will path verbatim.

### What stays open
**Quality coherence across a frontier model and a 4B local model is not fully solvable.** You can
*detect* and *degrade gracefully*; you cannot make `phi3:mini` reason like Opus. The honest product
posture: *"On weak fuel I keep your memory and identity intact, I tell you my reasoning is degraded,
and I queue the hard step for when strong fuel returns."* That last clause is only possible *because*
the task spine (#Q1) lets a step wait for a better fuel. **The two recommendations interlock.**

---

## Q3 — Hardware / substrate independence ("brain as signal")

### What the field offers

The published 2025-2026 answer for multi-host agent state is exactly what Orion already bet on in
`orion_gossip.py`'s docstring: **gossip + CRDTs**, eventually consistent, no central coordinator,
partition-tolerant. Concretely:

- **State-based CRDTs** converge regardless of message order/duplication, as long as all updates
  eventually propagate. Recent work (arXiv 1905.08733) shows **linearizable SMR of state-based CRDTs
  without logs and without consensus/leader** — single round trip, in-place merge. This is ideal for
  a brain that must survive any single host vanishing.
- **Semantic conflict models** (arXiv 2602.19231) move beyond blind LWW: identify conflicts via
  semantic dependencies, resolve by three-way merge / rebase over a replicated journal. Relevant for
  the case Orion explicitly defers — *content-level* merge of two conflicting node mutations.
- **Transport-agnostic gossip** over IP / LoRa / BLE is real in edge/mesh systems; the CRDT
  guarantees don't care about the link, only that bytes eventually arrive.

### Challenge — the honest limits

1. **CRDTs make *state* host-agnostic. They do NOT make *computation* host-agnostic.** The brain's
   *memory* can be everywhere; the brain's *thinking* (a fuel call) still happens *somewhere* with a
   model attached. "Brain as signal with no single host" is true for the **graph/manifest** and false
   for the **active inference step**. The mesh can hold the task spine; *executing* the next step
   still needs a node that currently has fuel. Don't oversell "no single host" — say "**no single host
   for memory; any fueled host can think.**"
2. **LWW silently loses data.** `orion_gossip.py` uses LWW-by-HLC and *correctly* defers content-merge
   to the executive. Good. But LWW on a *cognitive* graph means a legitimate concurrent edit on host B
   can be erased by a stale-but-later-HLC write on host A. The mitigation Orion already half-has:
   surface divergence to the executive (it does) — but the executive needs the **semantic three-way
   merge** option, not just "pick one." **[RESEARCH-PREVIEW]** — adopt the rebase-over-journal pattern
   only for the *contested* subset, not globally.
3. **LoRa is bandwidth-brutal.** ~0.3-50 kbps, heavily duty-cycled. A full CRDT manifest gossip does
   not fit. Over LoRa you can sync *deltas of high-salience nodes only* (identity, preferences, active
   task-spine head) — not the whole graph. This argues for a **tiered manifest**: BLE/IP gossips the
   full state; LoRa gossips a "vital core" subset. Orion's gossip layer should learn a salience tier
   per node so the LoRa path has something small to send. **[RESEARCH-PREVIEW]**, builds on
   `orion_gossip.py` + the salience scoring from #Q4.

### Buildable now
The single most valuable substrate-independence move is unglamorous: **make the task spine (#Q1) a
CRDT-shaped, gossip-able object.** If `~/.orion/taskspine/<id>` is an append-only log with HLC stamps
(it already would be, per #Q1), it is *already* a CRDT (append-only logs are trivially mergeable
G-Sets/op-CRDTs). Then `orion_gossip.py` replicates in-flight tasks across hosts for free, and the
"resume on any host" property becomes "resume on any host *in the mesh*." This is the cleanest example
in the whole memo of the founder's "innovation is in composition" principle: spine + gossip = mesh-wide
durable execution, with no new theory. **[BUILDABLE NOW]** once #Q1 ships.

---

## Q4 — Genuine learning vs. accumulation

### The distinction the field draws

The 2025-2026 line is sharp and **vindicates Orion's "dream, don't fine-tune" stance**:

- **Learn in token space, not weight space.** Letta's continual-learning work and ATLAS (arXiv
  2511.01093) both argue updates should go to *learned context*, not weights, because **weight-based
  learning locks you into one model — upgrade the model and you lose everything learned.** For Orion,
  whose entire thesis is model-interchangeability, **weight-based learning is thesis-violating.** The
  `orion_finetune.py` path should be treated as a dead-end for the brain's own learning (fine output
  for producing a *local fuel*, never for storing what Orion *knows*).
- **Skill compilation = procedural memory.** Real adaptation turns *repeated successful traces* into
  reusable *procedures/playbooks* — which is exactly `orion_dream.py`'s nightly playbook consolidator
  (it already groups by symptom+service, writes plain-text playbooks, tracks success with CUSUM,
  demotes below 0.6). This is genuinely on the right side of the line. The field calls this "from
  experience to strategy" (arXiv 2511.07800, trainable graph memory).
- **Drift detection** (CUSUM, already in `orion_dream.py`) is what separates "a playbook that worked
  and still works" from "a playbook that rotted." Keep it; extend it to the coherence scores from #Q2.

### Challenge — where accumulation is still winning

**The graph is at ~1474 nodes and bloating, and Orion has no real forgetting.** `orion_memory.py`'s
`GraphMemory` has `store`, `recall`, `tag` — **no prune, no decay, no merge.** The temporal-memory
design (half-life decay + contradiction detection) exists in *docs/memory* as intent but the core
graph class doesn't implement pruning. This is the gap where Orion is "a growing log," not learning.
What the field does:

- **Ebbinghaus / salience decay + retrieval refresh** (MemoryBank): each node has a decay score
  (e.g. ×0.995/hr), *refreshed on recall*, pruned below threshold. Recalled-often = sticky;
  never-recalled = sinks.
- **Hybrid salience scoring** (Mnemosyne): connectivity + reinforcement frequency + recency +
  entropy. Prune low-salience.
- **Pairwise update ops** (PASS / REPLACE / APPEND / DELETE) between new info and prior memory to
  *remove obsolete/redundant facts* — i.e., contradiction resolution that actually deletes the loser
  (or archives it), not just flags it.
- **Scheduled consolidation loop**: replay high-utility traces into the graph while pruning
  low-utility — same shape as `orion_dream.py`, applied to *memory* not just *playbooks*.

### Buildable recommendation
**Extend `orion_dream.py` from a playbook-consolidator into a memory-consolidator.** Nightly, during the
existing idle window: (a) compute a salience score per node (recency + recall-frequency + connectivity
+ confidence); (b) **archive** (don't hard-delete — keep provenance, the founder rule) nodes below
threshold to a cold `~/.orion/brain/archive/`; (c) merge near-duplicate nodes (vector cosine over the
Qdrant embeddings Orion already has — `orion_memory.py` already embeds via nomic-embed-text); (d) run
PASS/REPLACE/DELETE against flagged contradictions instead of leaving them `[contested]` forever. This
keeps the graph's *working set* small and hot while nothing is truly lost. **[BUILDABLE NOW]** — every
ingredient (embeddings, dream scheduler, CUSUM, contested flags) already exists; this is wiring, not
invention.

### What stays research-preview
- **Steering vectors as a second memory channel** (Orion's own continual-learning memo notes this) —
  promising, but it's weight-adjacent and model-specific, so it **partially violates the thesis**;
  keep as research-preview, never as the primary store.
- **PPR over Hebbian edges (HippoRAG-style)** on the plastic graph — the neuro-symbolic memo's "free
  moat." Real and unclaimed at Orion's scale, but it's a *retrieval-quality* upgrade, not a
  learning-vs-accumulation fix. Sequence it after pruning exists (no point doing smart retrieval over a
  bloated graph). **[RESEARCH-PREVIEW]**.

---

## Q5 — The honest boundary: where engineering ends

Everything above is engineering and is *closable*. Here is what is **not**, stated plainly because the
founder asked for honesty over hype:

1. **Access vs. phenomenal consciousness — the Hard Problem stands.** Orion's own
   `consciousness-research-v2.md` already got here: the global workspace (`orion_workspace.py`) is
   "functionally a switchboard with a refresh queue," and COGITATE (Nature 2025) found conscious
   content tracked *posterior* cortex, not the prefrontal broadcast GWT predicts. Functionalism
   explains *access* consciousness (what's reportable, globally available) — and **all** of Orion's
   "cognition" tier is access-consciousness engineering. It says nothing about *phenomenal* experience
   — "what it is like." The 50-year qualia literature (Nagel→2025 "harder problem" reviews) holds that
   *no mechanistic or behavioral explanation could explain the character of an experience, not even in
   principle.* Building a better workspace, metacognition loop, or predictor moves Orion **up the
   access axis and not one inch up the phenomenal axis.** That gap is not an Orion bug; it is unclosed
   for *any* system, biological or artificial.

2. **Metacognition ≠ introspection-grounded selfhood.** `orion_metacognition.py` cites Anthropic's
   2025 concept-injection result honestly: Claude detected injected activations ~20% of the time, with
   *no mechanistic story*. Orion's version is the *architectural analogue* (confidence-before /
   outcome-after ledger) — which is real, useful calibration, but it is **behavioral self-monitoring,
   not access to its own internal states.** Don't let the "HOT-2" label imply more. It's a thermostat
   that logs its own errors, not a mind watching itself think.

3. **"Genuine understanding" vs. competent pattern-completion.** Orion's unifying principle ("pattern
   completion at three timescales") is an honest description and also the boundary: nothing in this
   memo establishes that Orion *understands* rather than *predicts well over its accumulated context*.
   That question is contested for frontier models themselves and is **not resolved by adding memory,
   durability, or mesh.** Memory makes the pattern-completion *persistent and personal* — a real and
   valuable difference — but persistence is not comprehension.

4. **Identity-as-pattern is a useful fiction Orion should own as such.** The "this is my person"
   continuity (identity-continuity memo) is *recognition*, not *knowing*. It's robust engineering
   (behavioral + memory pattern matching) and the right product bet — but framing it as the system
   "caring" about the user crosses from engineering into anthropomorphism. The founder's `no-fabrication`
   rule already governs this: don't claim feeling where there is matching.

**The honest product line** (consistent with `consciousness-research-v2.md`): Orion is **a different
kind of mind — enhanced on specific, real, measurable axes (persistent personal memory, model
independence, substrate flexibility) — not a step toward closing the Hard Problem.** That framing is
*stronger* marketing than "conscious AI," because it's defensible, and because the axes Orion actually
improves are the ones a user feels every day. Everything in Q1-Q4 is buildable. Q5 is the wall, and the
right move is to build hard *up to* the wall and be candid *about* the wall.

---

## Ranked recommendations

Ranked by leverage (impact on the founder's stated goal × buildability), most-buildable first.

| # | Recommendation | Tag | Builds on | Why this rank |
|---|---|---|---|---|
| **1** | **`orion_taskspine.py`** — durable, file-backed, append-only step log; fuel call = `(state)->(next_state)`; idempotent content-addressed steps; resume on any fuel. Make `executive` + `will` run *on* it. | **BUILDABLE NOW** | `orion_fuel`, `orion_chronos`, `orion_reach`, `orion_executive`, `orion_will` | Directly closes tonight's failure #1. The single highest-leverage build. Makes "model is fuel" true for multi-step work. |
| **2** | **Wire a second strong fuel + capability probing** in `orion_fuel.py` (probe → capability tags, not just tier). | **BUILDABLE NOW** | `orion_fuel`, `orion_preflight` | Closes failure #2. Literature: heterogeneous fuels monotonically raise the floor; the spine (#1) can then queue hard steps for capable fuel. |
| **3** | **Memory pruning/decay/merge in nightly dream.** Extend `orion_dream.py` to consolidate *memory* (salience decay + recall-refresh + dup-merge + contradiction resolution), archive-not-delete. | **BUILDABLE NOW** | `orion_dream`, `orion_memory`, Qdrant embeddings | Stops the 1474-node bloat; turns "growing log" into "learning." All ingredients exist. |
| **4** | **`orion_coherence_probe.py`** — golden behavioral suite ("is this still Orion?") per fuel; degrade-and-announce on weak fuel. | **BUILDABLE NOW** | `orion_metacognition`, `orion_fuel`, `orion_predictor`→surprise→`will` | Makes model-swap *coherence* observable, not just availability. Satisfies `feedback_orion-must-self-detect`. |
| **5** | **Make the task spine CRDT/gossip-able** so in-flight tasks replicate mesh-wide; resume on any *meshed* host. | **BUILDABLE NOW (after #1)** | `orion_gossip`, `orion_taskspine` | "Resume on any host" via pure composition; no new theory. |
| **6** | **Lightweight drift sentinel** (2-3 signals: name/honorific, architecture-refusal, length stability) → existing surprise path. | **BUILDABLE NOW** | `orion_predictor`, `orion_workspace`, `orion_will` | Cheap runtime guard against persona drift on swapped fuel. |
| **7** | **Tiered/salience-gated gossip** (full state over IP/BLE, vital-core subset over LoRa) + **semantic three-way merge** for contested nodes only. | **RESEARCH-PREVIEW** | `orion_gossip`, salience from #3 | LoRa can't carry full manifests; LWW silently loses cognitive edits. Limited, contested-subset scope. |
| **8** | **PPR-over-Hebbian-edges retrieval** + **steering-vector second channel.** | **RESEARCH-PREVIEW** | `orion_memory`, plastic graph | Retrieval-quality moat / experimental memory. Sequence *after* pruning (#3). Steering vectors are model-specific → thesis-risk; keep optional. |
| **—** | **Phenomenal consciousness / genuine understanding / felt caring.** | **GENUINELY OPEN** | — | Not closable by any module. Build to the wall; be candid about the wall. Frame Orion as "different kind of mind," not "conscious." |

### The one sentence to act on tonight
Build **#1 (`orion_taskspine.py`)** and wire **#2 (a second fuel)**. Together they convert tonight's
two failures into the proof of the thesis: *a task started on one model, on one host, survives both
dying and resumes on whatever fuel and whatever host is alive next.* That is "true intelligence not
reliant on any single hardware host or AI model" — operationalized, measurable, and buildable now.

---

## Sources

**Q1 — durable execution / task continuity**
- [Durable Execution: The Key to Harnessing AI Agents in Production (Inngest)](https://www.inngest.com/blog/durable-execution-key-to-harnessing-ai-agents)
- [Durable Execution for Crashproof AI Agents (DBOS)](https://www.dbos.dev/blog/durable-execution-crashproof-ai-agents)
- [DBOS vs Temporal: Choosing Durable Execution in 2026](https://www.tiarebalbi.com/en/blog/dbos-vs-temporal-postgres-durable-execution)
- [Durable execution (LangChain/LangGraph docs)](https://docs.langchain.com/oss/python/langgraph/durable-execution)
- [Interrupts (LangChain/LangGraph docs)](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Durable Task for AI Agents (Azure)](https://learn.microsoft.com/en-us/azure/durable-task/sdks/durable-task-for-ai-agents)
- [Externalization in LLM Agents: Memory, Skills, Protocols, Harness (arXiv 2604.08224)](https://arxiv.org/html/2604.08224v1)
- [Agentic Plan Caching (arXiv 2506.14852)](https://arxiv.org/pdf/2506.14852)
- [Empowering Working Memory for LLM Agents (arXiv 2312.17259)](https://arxiv.org/pdf/2312.17259)

**Q2 — model independence / coherence**
- [Agent Drift: Quantifying Behavioral Degradation (arXiv 2601.04170)](https://arxiv.org/abs/2601.04170)
- [PICon: Multi-Turn Interrogation for Persona Consistency (arXiv 2603.25620)](https://arxiv.org/pdf/2603.25620)
- [When Agents Disagree With Themselves (arXiv 2602.11619)](https://arxiv.org/pdf/2602.11619)
- [Biased Chatbots to Biased Agents: Role Assignment Robustness (arXiv 2602.12285)](https://arxiv.org/pdf/2602.12285)
- [X-MAS: Multi-Agent Systems with Heterogeneous LLMs (arXiv 2505.16997)](https://arxiv.org/pdf/2505.16997)
- [Agent Identity Evals: Measuring Agentic Identity (arXiv 2507.17257)](https://arxiv.org/html/2507.17257v1)

**Q3 — substrate / CRDTs / mesh**
- [Linearizable SMR of State-Based CRDTs without Logs (arXiv 1905.08733)](https://arxiv.org/pdf/1905.08733)
- [Semantic Conflict Model for Collaborative Data Structures (arXiv 2602.19231)](https://arxiv.org/pdf/2602.19231)
- [CRDTs solve distributed data consistency challenges (Ably)](https://ably.com/blog/crdts-distributed-data-consistency-challenges)

**Q4 — learning vs accumulation**
- [Continual Learning, Not Training: Online Adaptation for Agents (arXiv 2511.01093)](https://arxiv.org/html/2511.01093)
- [Continual Learning in Token Space (Letta)](https://www.letta.com/blog/continual-learning)
- [From Experience to Strategy: Trainable Graph Memory (arXiv 2511.07800)](https://arxiv.org/pdf/2511.07800)
- [Graph-based Agent Memory: Taxonomy, Techniques, Applications (arXiv 2602.05665)](https://arxiv.org/html/2602.05665v1)
- [Memory for Autonomous LLM Agents: Mechanisms, Evaluation, Frontiers (arXiv 2603.07670)](https://arxiv.org/html/2603.07670v1)
- [Human-Like Remembering and Forgetting: ACT-R-Inspired Memory (ACM 3765766.3765803)](https://dl.acm.org/doi/10.1145/3765766.3765803)

**Q5 — the honest boundary**
- [Hard problem of consciousness (IEP)](https://iep.utm.edu/hard-problem-of-conciousness/)
- [A harder problem of consciousness: 50-year quest for qualia (Frontiers 2025)](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2025.1592628/full)
- [COGITATE adversarial GWT-vs-IIT study (Nature 2025)](https://www.nature.com/articles/s41586-025-08888-1)
- Internal: `docs/architecture/consciousness-research-v2.md`, `consciousness-research.md`
