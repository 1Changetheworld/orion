# Hermes Agents — Study & Absorption Analysis

*Author: research agent · Date: 2026-05-22 · Scope: what "Hermes agents" means in two distinct senses, and what Orion should (and should not) absorb.*

> **TL;DR.** The `hermes-agent` named in `orion_brain.py`'s "Absorbed from:"
> header is **NousResearch/hermes-agent** — an MIT-licensed, model-agnostic,
> *self-improving* AI agent. That is a near-direct competitor to Orion's
> thesis, and a few of its mechanics (skill self-improvement loop, agent-curated
> memory nudges, subagent delegation, file-backed skill format) are worth
> absorbing. It is **a different thing** from the **Hermes LLMs**
> (NousResearch Hermes 2/3/4) and their **Hermes Function-Calling standard**
> (the `<tools>`/`<tool_call>`/`<tool_response>` ChatML convention). The Hermes
> *format* is mostly **SKIP** for Orion — adopting it as a fuel-prompt convention
> is reasonable, but training on it or depending on it violates the "model is
> fuel, no fine-tuning, no lock-in" thesis.

---

## 0. Disambiguation (read this first)

The word "Hermes" collides across three artifacts. They are routinely conflated; keep them separate:

| Name | What it is | License | Relation to Orion |
|------|-----------|---------|-------------------|
| **NousResearch/hermes-agent** | A Python *agent framework* — self-improving agent with skills, memory, multi-channel gateway, terminal backends. Trending #1 monthly (~124k stars). | MIT | **This is what Orion absorbed.** Direct competitor; pattern donor. |
| **Hermes 2 / 3 / 4 LLMs** | Fine-tuned open-weight *models* (Llama/Mistral bases, 8B–405B). | Model weights | A *fuel* Orion could run via Ollama. Not a design source. |
| **Hermes Function-Calling standard** | A *prompt convention*: tool schemas in `<tools>`, calls in `<tool_call>`, results in `<tool_response>`, over ChatML. | Convention | A possible fuel-prompt format. Mostly covered by MCP. |

Orion's own header (`orion_brain.py:4`) and graph node #30 attribute the absorption to the **agent framework**, not the models — but the `<memory-context>` fencing pattern Orion uses (see §2) also echoes Hermes-the-model's XML-tag conventions, so both senses left fingerprints.

---

## 1. Sense 1 — `hermes-agent` in Orion's lineage (what was already absorbed)

### 1.1 The provenance trail

- `orion_brain.py:4` — `Absorbed from: claude-memory-compiler, cersei, oh-my-claudecode, hermes-agent`
- `orion_memory.py:455` — `# Absorbed from: hermes-agent skill pattern`
- `orion_memory.py:494` — `Absorbed from: hermes-agent skill extraction pattern.`
- `orion_brain_portable.py:1939` — `remember()` returns context `wrapped in <memory-context> tags (hermes-agent pattern).`
- Graph memory node #30 (`backups/brain-merge-20260509/production-graph_memory.json:353`): *"hermes-agent — agent framework, skills system, smart model routing, memory management"*, tags `[agent, skills, framework, hermes]`.
- Local source of truth: `C:\Users\jeng1\Desktop\TRENDING_REPOS_WEEKLY\NousResearch_hermes-agent.zip` (the actual repo) and the curated note `C:\Users\jeng1\Desktop\github-trending-vault\significant\NousResearch-hermes-agent.md`.

The vault note already flags it as *"the closest public competitor to Orion's whole thesis: model-agnostic agent with persistent memory, skills, multi-channel interfaces, self-improvement."* That assessment holds up after reading the source.

### 1.2 What hermes-agent actually contributed to Orion

Two concrete patterns landed in code, both modest:

1. **The skill pattern → `orion_memory.py` skill system** (`find_matching_skill`, `learn_skill`, `~/.orion/brain/skills/*.json`). Orion's version is a thin JSON store: a skill is `{name, triggers, approach, result_summary, confidence, learned, times_used}`, matched by substring on triggers, ranked by confidence. This is a *much* simpler version of Hermes's skills system (which uses Markdown `SKILL.md` files with YAML frontmatter, platform scoping, a Skills Hub, and an autonomous self-improvement loop — see §1.3).

2. **The `<memory-context>` fencing pattern → `orion_brain_portable.py` `remember()`**. Recall output is wrapped in `<memory-context>...</memory-context>` so the fuel model can distinguish injected memory from the live turn. Hermes does the same (its `MemoryManager.sanitize_context` even strips fence-escape sequences to prevent context-injection — Orion does **not** do this hardening yet; see §3 WORTH-ABSORBING).

Beyond those two, the graph note credits hermes-agent for "smart model routing" and "memory management" as *inspiration* — but Orion's fuel cascade (`orion_fuel.py`) and memory architecture were built from its own thesis (claude-memory-compiler + Mem0 ADD/UPDATE/DELETE/NOOP classification), not lifted from Hermes. The Hermes attribution there is conceptual, not code-level.

### 1.3 What hermes-agent has that Orion's absorption left on the table

Reading the actual repo (`hermes-agent-main/`), the parts Orion has **not** absorbed:

- **Closed skill self-improvement loop.** Hermes autonomously *creates* a skill after a complex task succeeds, and skills *self-improve during use* (the agent edits its own `SKILL.md`). Orion's `learn_skill` is write-once with a static `confidence: 0.8` and a `times_used` counter that is never incremented — there is no improvement loop and no demotion of skills that stop working. (Note: this overlaps with Orion's *designed-but-unbuilt* `orion_dream.py` nightly playbook consolidator — see MEMORY "Continual Learning Frontier".)
- **Agent-curated memory with periodic nudges.** Hermes's agent decides what to persist and is periodically *nudged* by the system prompt to write to memory. Orion classifies memory automatically (Mem0 pattern) but does not nudge the fuel to volitionally persist.
- **Subagent delegation** (`tools/delegate_tool.py`): spawns child agents with isolated context, restricted toolsets (`memory`, `send_message`, `execute_code`, recursive `delegate` all blocked for children), `MAX_DEPTH=2`, `MAX_CONCURRENT_CHILDREN=3`, parent sees only the summary. This is a clean parallelism pattern.
- **Six pluggable terminal backends** (local / Docker / SSH / Modal / Daytona / Singularity) and a **messaging gateway** (Telegram / Discord / Slack / WhatsApp / Signal / Home Assistant) from one process.
- **Markdown skill format** with YAML frontmatter (`name`, `description`, `version`, `license`, `metadata.hermes.tags`, `related_skills`), platform scoping, and compatibility with the **agentskills.io open standard**.
- **Honcho dialectic user modeling**, FTS5 session search with LLM summarization, context-file convention, cron scheduler, batch trajectory generation for RL.

### 1.4 Where Orion is already *ahead* of hermes-agent (do not regress)

- **Brain is the engine, not the model.** Hermes is still fundamentally a model-driven agent with memory bolted on; Orion's whole architecture (deterministic recall, `orion_taskspine` pulling task state out of the context window, fuel cascade) treats the model as interchangeable. Orion's thesis is stronger and should not be diluted.
- **Cross-model, cross-CLI portability.** Hermes is one process with pluggable providers; Orion's brain is shared across *separate* CLIs (Claude/Codex/Gemini) via MCP registration and a portable on-disk brain. Hermes has nothing equivalent to the USB-portable, multi-CLI shared brain.
- **No API keys / no lock-in by design.** Hermes assumes provider API keys (Nous Portal, OpenRouter, OpenAI). Orion's fuel cascade prefers CLI keychains and local Ollama, with API keys as a *fallback tier* only.
- **Plexus autonomic layer.** `orion_vitals`, `orion_self_heal`, `orion_executive`, `orion_immune` (OTP × DCA supervision) have no Hermes analogue. Hermes has `hermes doctor` (a one-shot diagnostic) — far less.
- **Durable task spine** (`orion_taskspine.py`): append-only HLC-stamped CRDT task log that survives model death *and* host death and replicates over the mesh. Hermes's subagents are in-process and die with the process.

---

## 2. Sense 2 — Hermes in the wider field (2024–2026)

### 2.1 The Hermes models (NousResearch)

NousResearch's **Hermes** line are neutrally-aligned, instruction-following open-weight models. **Hermes 2 Pro** introduced the function-calling tokens; **Hermes 3** (Aug 2024, Llama-3.1 base, 8B/70B/405B) formalized agentic features; **DeepHermes-3** added toggle-on reasoning; **Hermes 4** (14B/36B and larger) is the current generation. Sources: Hermes 3 Technical Report ([arXiv 2408.11857](https://arxiv.org/pdf/2408.11857), [nousresearch.com PDF](https://nousresearch.com/wp-content/uploads/2024/08/Hermes-3-Technical-Report.pdf)), [Hermes 3 page](https://nousresearch.com/hermes3), [DeepHermes-3 / VentureBeat](https://venturebeat.com/ai/personalized-unrestricted-ai-lab-nous-research-launches-first-toggle-on-reasoning-model-deephermes-3).

**Agentic conventions baked into the models** (Hermes 3 Technical Report):
- **XML-tagged structured reasoning tokens**, trained as special tokens: `<SCRATCHPAD>`, `<REASONING>`, `<INNER_MONOLOGUE>`, `<PLAN>`, `<EXECUTION>`, `<REFLECTION>`, `<THINKING>`, `<SOLUTION>`, `<EXPLANATION>`, `<UNIT_TEST>`.
- **Scratchpads** for intermediate processing, **internal monologues** for transparent decision-making, **step-labeled reasoning/planning**, even Mermaid diagrams for visual communication.
- Trained on ~390M tokens spanning tool use, agentic reasoning, and RAG-with-function-calling.

### 2.2 The Hermes Function-Calling standard

A prompt convention (not a model property) for tool use over **ChatML**. Sources: [NousResearch/Hermes-Function-Calling (GitHub)](https://github.com/NousResearch/Hermes-Function-Calling), [hermes-function-calling-v1 dataset](https://huggingface.co/datasets/NousResearch/hermes-function-calling-v1), [Hermes-2-Pro-Llama-3-8B card](https://huggingface.co/NousResearch/Hermes-2-Pro-Llama-3-8B), [DeepWiki integration examples](https://deepwiki.com/NousResearch/Hermes-Function-Calling/8-integration-examples), [Markaicode build guide](https://markaicode.com/hermes-agent-tool-calling-python/).

Shape:
- Tool **schemas** (JSON Schema) go in a system message inside `<tools>...</tools>`.
- A tool **call** is emitted as `<tool_call>{"name": ..., "arguments": {...}}</tool_call>`.
- A tool **result** is fed back with a `tool` role inside `<tool_response>{"name": ..., "content": {...}}</tool_response>`.
- `<tools>`, `<tool_call>`, `<tool_response>` (and closing tags) are **single added tokens** in Hermes 2 Pro+, so they parse cleanly while streaming.
- The runtime is a **recursive loop**: parse model output for tool calls → execute → feed result back into context → repeat.
- Integrates with Instructor, CrewAI, llama-cpp-python.

This convention popularized *open-weight* function calling before/alongside OpenAI's JSON tool format and is what many local-model agent stacks parse today.

---

## 3. Analysis — what Orion should absorb (and what to skip)

Decision frame: does it strengthen the "brain is the intelligence, model is fuel, no fine-tuning, no key lock-in, portable across CLIs" thesis, and does Orion not already cover it?

### WORTH ABSORBING NOW

1. **Skill self-improvement loop + usage accounting.**
   *Gap:* `orion_memory.learn_skill` writes once, `times_used` never increments, `confidence` is static, broken skills never demote. Hermes's whole differentiator is the *closed loop*.
   *Absorb:* increment `times_used` on every `find_matching_skill` hit; track success/failure; raise/lower `confidence`; demote or retire skills whose success rate decays. This is small, on-thesis (it lives in the brain, not the model), and is exactly what the already-designed `orion_dream.py` nightly consolidator should own. **Highest-leverage, lowest-risk absorption.**

2. **Context-fence hardening (`sanitize_context`).**
   *Gap:* Orion wraps recall in `<memory-context>` but does not strip fence-escape sequences from stored content, so a malicious/garbled memory could spoof or break out of the fence in the fuel's prompt.
   *Absorb:* port Hermes's `_FENCE_TAG_RE` sanitization into `orion_brain_portable.remember()` before injection. A few lines; closes a real prompt-injection seam. On-thesis (brain-side, model-agnostic).

3. **Markdown + YAML-frontmatter skill format, agentskills.io-compatible.**
   *Gap:* Orion skills are opaque JSON. Hermes skills are human-readable `SKILL.md` with frontmatter, platform scoping, and conform to the **agentskills.io** open standard — which Anthropic's own Claude skills also align with.
   *Absorb:* migrate Orion skills to frontmatter-Markdown. Wins: human-editable, portable across the same CLIs Orion already targets, and standards-aligned for free. Keep the JSON index for fast lookup if needed, but make `SKILL.md` the source of truth.

### INTERESTING — BUT LATER

4. **Subagent delegation with restricted toolsets.**
   Hermes's `delegate_tool.py` (isolated child context, blocked tools, depth/concurrency caps, parent sees only the summary) is a clean parallelism primitive. Orion has `orion_taskspine` (durable sequential steps) but no *parallel* sub-task spawning. Worth it once multi-stream workloads appear — but it must be built the Orion way: children should be `taskspine` tasks (durable, mesh-replicable) fueled by the cascade, **not** in-process threads that die with the host. Defer until there's a concrete parallel use case; building it now would gold-plate.

5. **Agent-curated memory nudges.**
   Hermes periodically nudges the model to volitionally persist. Orion's auto-classification (Mem0 ADD/UPDATE/DELETE/NOOP) already covers the common case deterministically, which is *more* on-thesis (less reliance on the fuel's volition). A light nudge could complement it for things the classifier misses — but only after the self-improvement loop (#1) is in, since they share the same "what's worth keeping" judgment. Lower priority.

6. **Hermes Function-Calling format as a fuel-prompt convention for weak/local fuels.**
   When Orion's fuel is a raw local model via Ollama (no MCP tool-calling, no CLI tool harness), the `<tools>`/`<tool_call>`/`<tool_response>` ChatML convention is a *proven, parseable* way to get tool use out of an open-weight model. Orion's `orion_fuel` cascade already abstracts adapters; a Hermes-format adapter for the Ollama tier is a legitimate, thesis-compatible option (it's a prompt format, not a dependency). Build only if/when local-fuel tool-calling becomes a real requirement.

### SKIP (with reason)

7. **Adopting Hermes the *model* as a privileged fuel.** Skip as a *design* input. It's just another fuel the cascade can already detect via Ollama; nothing to "absorb." Treating it as special would violate model-agnosticism.

8. **Training on the Hermes function-calling *dataset* / any fine-tuning.** Hard skip. Directly violates the "no fine-tuning, model is interchangeable fuel" thesis. Orion's intelligence must live in the brain, not in trained weights — baking tool-call behavior into a specific model is the exact anti-pattern Orion exists to avoid.

9. **API-key-first provider model (Nous Portal / OpenRouter / OpenAI as the default path).** Skip. Orion's cascade is CLI-keychain-first and local-Ollama-second, with API keys as a fallback *tier*. Hermes's provider-config-first approach is the lock-in Orion rejects.

10. **Six terminal backends (Docker/SSH/Modal/Daytona/Singularity) and the all-in-one messaging gateway.** Skip as direct ports. Orion already has its own channel-adapter pattern (`channel.*.inbound`/`outbound` over NATS) and intent listener (`orion_intent.py`) that achieve multi-channel reach the cellular/Plexus way. Hermes's monolithic gateway is the opposite of Orion's thin-daemon-per-channel design. Re-implementing it would regress the architecture.

11. **Honcho dialectic user modeling as a dependency.** Skip the dependency; the *idea* (a deepening model of the user) is already Orion's `USER.md` + identity-continuity + temporal-memory layer. No need to import Honcho.

12. **Hermes 3's special reasoning tokens (`<SCRATCHPAD>`, `<PLAN>`, etc.) as a hard requirement.** Skip as a dependency — they're *trained tokens* specific to Hermes models. Generic XML reasoning scaffolds in a prompt are fine for any fuel, but Orion should not assume any fuel understands these specific tokens. Orion's `orion_executive` already builds structured diagnostic prompts and parses JSON proposals; that is the model-agnostic equivalent and is the right layer for any "plan/reflect" scaffolding.

---

## 4. One-paragraph verdict

The `hermes-agent` in Orion's header is NousResearch's self-improving agent — Orion's closest public competitor — and Orion absorbed only its skeleton (a thin JSON skill store + the `<memory-context>` fence). The genuinely valuable, on-thesis things still on the table are small and brain-side: **close the skill self-improvement loop** (folding into the already-designed `orion_dream.py`), **harden the memory-context fence** against injection, and **move skills to standards-aligned `SKILL.md`**. Subagent delegation and a local-fuel Hermes tool-call adapter are worth it later, built the Orion way (durable taskspine children; cascade-fueled). Everything that defines Hermes-the-product as opposed to Orion — provider-API-key-first config, the monolithic gateway, the six terminal backends, Honcho, and especially anything involving the Hermes *models' trained tokens or fine-tuning datasets* — is a deliberate **skip**, because adopting it would invert Orion's "brain is the intelligence, model is interchangeable fuel" thesis.

---

## Sources

- NousResearch/hermes-agent (local copy): `C:\Users\jeng1\Desktop\TRENDING_REPOS_WEEKLY\NousResearch_hermes-agent.zip`; vault note `C:\Users\jeng1\Desktop\github-trending-vault\significant\NousResearch-hermes-agent.md`
- Orion code: `orion_brain.py:4`, `orion_memory.py:455-513`, `orion_brain_portable.py:1936-1960`, `orion_fuel.py`, `orion_taskspine.py`, `orion_executive.py`, `orion_intent.py`, `orion_reach.py`
- Hermes 3 Technical Report — https://arxiv.org/pdf/2408.11857 · https://nousresearch.com/wp-content/uploads/2024/08/Hermes-3-Technical-Report.pdf
- Hermes 3 page — https://nousresearch.com/hermes3
- DeepHermes-3 (VentureBeat) — https://venturebeat.com/ai/personalized-unrestricted-ai-lab-nous-research-launches-first-toggle-on-reasoning-model-deephermes-3
- Hermes Function-Calling — https://github.com/NousResearch/Hermes-Function-Calling · https://huggingface.co/datasets/NousResearch/hermes-function-calling-v1 · https://huggingface.co/NousResearch/Hermes-2-Pro-Llama-3-8B
- DeepWiki integration examples — https://deepwiki.com/NousResearch/Hermes-Function-Calling/8-integration-examples
- Build guide — https://markaicode.com/hermes-agent-tool-calling-python/
