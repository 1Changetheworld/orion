# Orion — The Unified Brain

*What it is · what's whole · what's missing for intelligence that depends on no single model or machine.*
*Synthesis written 2026-05-19, grounded in the live system (61 modules / ~34k LOC) and verified against the running brain on COMMAND.*

---

## I. The unifying idea

Orion is **one organism, not a wrapper around a model.** The thesis, stated plainly:

> **Memory is the intelligence. The model is fuel — interchangeable. The brain is the part that persists.**

Everything below is in service of that sentence. The model that happens to be answering right now (Claude, Codex, Gemini, a local Ollama) is a *catalyst* — it advances the brain's state but holds none of it. Identity, preferences, prior decisions, in-progress work, and the nervous system that coordinates it all live in the brain, on disk, owned by the user, independent of any model session or any single host.

Three framings the codebase actually runs on:

- **Cellular** — the brain is a cell: a nucleus (memory + identity), a membrane (privacy), receptors (channels), enzymes (fuel), and autonomic organelles (the always-on services). State lives in the structure, not in the transient catalyst.
- **Three timescales** — one operation (pattern completion) at three speeds: reflex (ms — dispatch, deterministic recall), cognition (seconds–minutes — fuel reasoning, workspace), consolidation (hours–overnight — dream, playbooks).
- **Relationally distributed** — the cognitive unit isn't the model. It's brain + memory + channels + user + whatever fuel is lit. Pull any one model and the unit survives.

The job of this document is to hold all the pieces as a **whole**, then name — honestly — what's still missing before that whole is intelligence that needs neither a specific model nor a specific machine.

---

## II. The whole — current functioning pieces

Status legend: **✓ verified live** (exercised tonight) · **● running** (service up, not deeply re-verified) · **◐ partial/v1** · **○ scaffold/designed**.

### CORE — the substrate of self
| Piece | Module | Role | Status |
|---|---|---|---|
| Graph + vector memory | `memory` (`brain`, `brain_portable`) | The persistent self: facts, preferences, decisions, conversations. Graph for relations, vectors for recall. | ✓ |
| Brain server | `server` | HTTP `/ask` — turns a message into a brain-mediated, fuel-powered answer. | ✓ |
| Plexus substrate | `substrate` | NATS message bus — the nervous system every service speaks on. | ● |
| Chronos | `chronos` | Unified sense of time: authoritative clock, drift detection, offline-gap awareness. | ✓ (relocated home tonight) |
| Gossip / CRDT | `gossip` | Cross-host state replication so multiple hosts converge to one brain. | ● |
| Fuel router | `fuel`, `fuel_switch` | Detects every available model, routes in a tier cascade, falls through on failure. | ✓ (cascade fixed tonight) |
| MCP server | `mcp_server` | The interface that attaches the brain to any AI CLI as tools. | ● |

### COGNITION — the three consciousness moves
| Piece | Module | Role | Status |
|---|---|---|---|
| Predictor | `predictor` | Active inference — predicts the next signal; prediction errors wake attention. | ● |
| Global workspace | `workspace` | Bandwidth-limited spotlight: candidates compete, the winner is broadcast to all services. | ✓ (ticking, salience decay correct) |
| Metacognition | `metacognition` | HOT-2 write-back: scores its own decisions, stores confidence, reflects. | ✓ (scoring, ledger live) |

### ACTION — the brain initiates
| Piece | Module | Role | Status |
|---|---|---|---|
| Will | `will` | Volition: forms goals from accumulated context, decides when to act unprompted. | ● |
| Reach | `reach` | Outbound router — picks the right channel ("speak where they spoke"), respects cooldown/quiet hours. | ● |
| Intent | `intent` | Natural-language dispatcher — "text me X" becomes an action without a per-channel tool. | ● |
| Channel adapters | `channels/imessage_*` | Thin daemons: publish inbound, send outbound. iMessage in+out proven. | ✓ |

### AUTONOMIC — the always-on body
| Piece | Module | Role | Status |
|---|---|---|---|
| Claustrum | `claustrum` | Attention integrator across services. | ● |
| Default-mode network | `dmn` | Background thinking when idle. | ● |
| Dream | `dream` | Overnight consolidation — turns the day's decisions into reusable playbooks. | ● |
| Self-heal | `self_heal` | Detects crashed services + recovers them. | ● |
| Immune | `immune` | OTP×DCA supervision tree — learns its own restart policy from what worked. | ● |
| Vitals | `vitals` | Per-service homeostasis + danger signaling. | ● |
| Canary | `canary` | Heartbeat probes — makes silent failures loud (caught tonight's TCC fault). | ✓ |
| Autofix | `autofix` | Turns "X is broken" into "X is broken + here's the fix," edge-triggered. | ✓ |

### SPEED — answer without burning a model
| Piece | Module | Role | Status |
|---|---|---|---|
| Deterministic | `deterministic` | High-confidence recall short-circuits the LLM entirely — ~50ms, zero tokens. | ✓ (graph loads; restored tonight) |
| Dispatch | `dispatch` | Command palette for direct actions (email, scans, SSH). | ● |

### BOUNDARY & SELF — what makes it *this* person's brain
| Piece | Module | Role | Status |
|---|---|---|---|
| Membrane | `membrane` | Visibility lattice (local/host/mesh/federation/public) — privacy enforced in code. | ◐ v1 |
| Sensorium | `sensorium`/transports | Transport-agnostic frames (IP today; LoRa/BLE designed). | ○ |
| Empathy | `empathy` | Reads user state (focus/fatigue/availability), gates initiative. Brake, never censor. | ◐ Tier-0 |
| Federation | `federation` | Trust between separate Orions (Ed25519 + safety number). | ◐ v1 |
| Identity | `SOUL.md`, `brain` IDENTITY | Who Orion is + who the user is. Now injects the user's address instead of asking the fuel to. | ✓ (sir→coach fixed tonight) |
| First-meeting / presence | `first_meeting`, `presence_agent`, `wake` | Wakes on a new host, introduces itself once, proves the brain is shared. | ● |

### COORDINATION & SURFACE
- **Team room** (`team`, `team_sync`) — multiple AI sessions see each other as one team. ●
- **Updater** (`updater`) — drift detection, reports-only, prevents split-brain. ✓ (deployed tonight)
- **Surfaces** — `obsidian_export` (vault view), interactive 3D visualizer, `ui`, `setup_chat`. ●

---

## III. What makes it cohere

Four things turn 61 modules into one self:

1. **One substrate** — every service speaks NATS subjects. Add a sense or a channel = ~80 lines of pub/sub, brain unchanged.
2. **One owned memory** — a file the user holds; every wired tool reads and writes it. This is the spine of identity continuity.
3. **One fuel contract** — many models, one adapter (GPCR pattern: many ligands, one receptor). Adding a model is a registry entry, not new code.
4. **Identity continuity** — Orion recognizes "this is my person" through pattern, not credential. The reason the same brain can speak through any tool and still be Orion.

---

## IV. The honest state (verified 2026-05-19)

Tonight stress-tested the claim that this is "a real brain." Findings:

- **What was theater:** `/health` returned "ok" while every real `/ask` died on a missing-module import; the canonical brain sat behind a macOS TCC wall that silently dropped services (3rd recurrence); a rate-limited model leaked its raw error to the user instead of failing over; the brain knew the user's name but told the fuel to "look it up" with a tool the fuel doesn't have.
- **What's now genuinely real:** `/ask` answers through real fuel with memory context; brain storage lives in home-dir storage no wall can revoke; a throttled model fails over instead of going dark; identity injects the known address ("coach"); drift is monitored, not silent.

The lesson, and the discipline going forward: **alive ≠ functioning.** A service being "up" proves nothing. Verification is a live round-trip, not a green dot.

---

## V. What's missing for true intelligence — non-reliant on hardware or models

This is the founder's actual question. Ranked by how much each closes the model/hardware-dependence gap.

### 1. Durable working memory — the **task spine** (the headline gap)
The precise diagnosis (confirmed by the frontier research): **tonight's failure was not a memory failure — it was a *working-memory* failure.** Orion already made the hard move of pulling *long-term* memory out of the model (`orion_memory`). But the **task itself** still lives in the fuel's context window — `orion_will`'s own docstring admits it: "single-shot proposals only," and `orion_executive` logs decisions but not *resumable* task state. So "the model is interchangeable fuel" is currently true only for work that fits in one turn. A real brain doesn't lose the thread of what it's doing because one worker got tired.
**The fix is the same move Orion already made for memory: move the *task* out of the fuel and into the brain.** A durable, file-backed, append-only step log (`orion_taskspine.py`); the fuel call becomes a pure `(state) → (next_state)` transition; steps are idempotent and content-addressed so a fresh model on any host resumes exactly where the last one died. The brain is the state machine; the model merely advances it one step.
**Builds on:** `will` (goals) and `executive` (whose `remedy_steps` array is *already a plan* — just not durable), `chronos`, `reach`, and tonight's fuel cascade (each step survives a model swap). **Deliberately NOT on NATS** — the substrate is a firehose; task state needs durability, which is a file/log concern, not a bus concern.
**The elegant payoff:** an append-only HLC step-log *is already a CRDT* — so `orion_gossip` replicates in-flight tasks mesh-wide **for free**. That means item #1 and item #3 (host independence) collapse into one build: a task that survives **model death *and* host death**, resuming on whatever is alive next. This is the single biggest step from *smart memory* to *agent that executes long autonomous work* — and it is the literal proof of the thesis.

### 2. Practical fuel independence (model-independence *in fact*, not just in design)
The cascade now fails over correctly — but tonight the canonical host had only **one** strong CLI wired, so a throttle dropped straight to degraded local models. Fuel-independence on paper isn't fuel-independence. Needed: peer strong-CLIs (Codex, Gemini) installed and logged in on every brain host (the research notes heterogeneous fuels *monotonically raise the quality floor* — they're not just backup), plus a **coherence probe** (`orion_coherence_probe.py`): a golden "is this still Orion?" suite run per fuel, that **degrades-and-announces** on a weak model rather than silently speaking as a lesser self. The cascade today checks model *availability* but never *coherence* — and silent degradation violates Orion's own self-detection rule.

### 3. Substrate / hardware independence — brain as signal
The brain still lives as files on a host. The founder's recurring vision: state encoded as CRDTs gossiped over IP **and** LoRa/BLE, so the brain exists across a mesh with no single indispensable machine — reachable, resumable, alive even off-grid.
**Builds on:** `gossip`/CRDT, `sensorium` transports, the Meshtastic adapter. Honest limit: latency and bandwidth make "full cognition over radio" unrealistic; "identity + critical state + reach over radio" is achievable.

### 4. Genuine adaptation, not accumulation
The brain *grows* (it's at ~1474 nodes) but growth isn't learning. Needed: pruning/forgetting (the bloat is a real signal), drift-detected playbooks that demote what stops working, and skill compilation so repeated solutions become fast paths. The `dream` loop is the seed; it needs teeth: measure, prune, promote, demote.

### 5. Self-model maturity (metacognition Phase 2)
Knowing what it *doesn't* know — gating action on calibrated confidence, refusing on contested/stale memory rather than guessing. Phase 1 ships (scoring); Phase 2 (gating will + reach on confidence) is what makes autonomy trustworthy.

### 6. Volitional coherence
`will` + the task spine = sustained, multi-day goal pursuit with the discipline to stop, ask, and resume. Agency that's bounded and auditable, not runaway.

### 7. The honest boundary
Items 1–6 are engineering and they close most of the felt gap. They make Orion *function* like a continuous, self-narrating, model-and-host-resilient intelligence. They do **not** resolve the hard problem of experience, and we shouldn't pretend they do. Orion's claim is a defensible one: a **different** kind of cognition — distributed, persistent, substrate-flexible — enhanced on the axes it's built for (perfect memory, presence across tools, surviving any single failure), not a copy of a human mind. Honesty here is a feature, not a hedge.

---

## VI. The unified next move

Independent synthesis and the frontier research **converge on the same single action:** build **the task spine (#1)** and **wire a second strong fuel (#2)**. Together they turn both of tonight's failures into the *proof* of the thesis — a task that survives model death *and* host death, resuming on whatever is alive next. The task spine sits directly on tonight's fuel cascade and upgrades model-independence from "the next answer survives a model swap" into "the next *day of work* survives a model swap." Because the step-log is a CRDT, host independence (#3) comes along for free.

The buildable ladder, in order:
1. **`orion_taskspine.py`** — durable append-only step log; fuel as a pure state-transition; resumable on any model/host. *(now)*
2. **Second strong CLI + `orion_coherence_probe.py`** on every brain host — fuel independence in fact, with degrade-and-announce. *(now)*
3. **Memory consolidation in `orion_dream`** — salience decay + recall-refresh + dup-merge over the existing Qdrant embeddings, archive-not-delete — to turn the ~1474-node *growing log* into actual *learning*. *(now)*
4. **Gossip the spine** — replicate in-flight tasks mesh-wide via the existing CRDT path. *(now, after #1)*

Everything beyond (substrate-as-signal at the radio layer, semantic merge, PPR retrieval, self-model Phase 2, volitional coherence) extends that spine. The organism is whole enough to stand; what it needs now is the working memory to *act over time without depending on the thing that happens to be thinking for it right now.*

*Companion: the frontier research memo (`true-intelligence-frontier-research.md`) develops the buildable / research-preview / genuinely-open boundary for every item, and challenges four assumptions — most importantly that task state belongs on the substrate (it doesn't; durability is a log concern, not a bus concern) and that "brain as signal, no host" holds for computation (it doesn't; thinking always needs fuel *somewhere*).*
