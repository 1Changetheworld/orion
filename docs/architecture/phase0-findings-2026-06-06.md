This is a synthesis-and-delivery task. All five labs plus both compiler passes are complete; my job is to produce the final founder-facing Phase-0 document. No tools needed — the inputs are complete and I'm writing the decision artifact.

# ORION — PHASE-0 FINDINGS & PLAN
**For: James | 2026-06-06 | Status: ground-truth, post-audit**

---

## 1. WHERE ORION TRULY STANDS (5 lines)

1. Orion is a living **body**, not yet a thinking **cortex**: reflexes, ~28 autonomic daemons, and a metacognition layer that genuinely learns — but nothing reasons between fuel calls.
2. **Four walls** block aliveness: (1) the attention spotlight is broadcast but no module acts on it; (2) all reasoning bottoms out in an LLM call; (3) memory is never injected into context — the model must *choose* to recall; (4) the living layer is dead on Windows.
3. These are not four problems — they are **one missing loop**: memory → attention → injection → outcome → memory. Build it once, three walls fall together.
4. The thesis ("memory IS the intelligence") is **plausible but unproven** — the recall path that would prove it (fusion + rerank, already shipped in `orion_brain_portable.py`) is bypassed on the live MCP path.
5. The one irreplaceable asset — the graph — is saved to a single JSON file **without `fsync`**: a power-loss window that can erase the entire thesis. Fix that today.

---

## 2. THE 5 HIGHEST-LEVERAGE MOVES
*Each: the move → the cheap prove-it → the Phase-1 build it unlocks.*

### Move 0 (Tier 0) — `fsync` the brain
- **Prove-it (P0-A):** kill-and-resurrect drill — 20 power-loss cycles during save; pass = zero corruption. *1 line + 1 afternoon.*
- **Unlocks:** safe to take any risk with the moves below — every one writes to or reranks over this file. **This is the only item with unrecoverable downside if skipped. Do it before anything else.**

### Move 1 (Tier 1, spine) — Fused, plasticity-reranked recall on the live path
Rewrite `_handle_orion_recall` (lines 746–802) to call hybrid recall (graph keyword + BM25 + Qdrant via local `nomic-embed-text`), reranked by `relevance × retrievability`. Every part already exists and is bypassed.
- **Prove-it (P0-B, the keystone experiment):** recall bake-off on 30–50 real query/answer pairs from session logs — keyword vs BM25 vs Qdrant vs fused+plasticity. Score hit-rate@5 **and decision-hit rate**. *One offline afternoon, zero fuel.*
- **Kill criterion:** fused ≯ keyword → the bottleneck is injection, not retrieval; skip this, go to Move 3.
- **Unlocks:** kills the named failure ("phrased differently = invisible"); closes the retrieval half of Wall 3.

### Move 2 (Tier 1, spine) — Consume `workspace.current` as attention-prior + gate acting modules
Three ~3-line subscribes: `executive`/`will`/`metacog` engage on high-salience unresolved spotlight items; recall biases ranking toward in-spotlight entities. **Deterministic, zero fuel.**
- **Prove-it (P0-C):** consumed-broadcast test — log every spotlight + whether any module acts within 5s (expect ~0% baseline), measure working-set entropy. *One instrumented day.*
- **Kill criterion:** coupling stays <60% OR entropy collapses (fixation) → tune the loop-guard before shipping.
- **Unlocks:** makes the workspace non-decorative; **closes Wall 1.** Ship the loop-guard (Three-Cycle Rule) in the *same PR*.

### Move 3 (Tier 1, spine) — Per-turn bloodstream injection + SessionEnd auto-memorize
`UserPromptSubmit` hook prepends a token-budgeted `<memory-context>` (top 5–8 fused-reranked, spotlight-biased facts) every turn; `orion_session_save.py` (exists, never triggered) fires on SessionEnd.
- **Prove-it:** piggybacks on P0-B — inject the top-5 from the winning ranker, eyeball 10 turns for relevance.
- **Hard ordering:** only after Move 1 wins, or you inject garbage every turn and Orion feels *worse*.
- **Unlocks:** the model no longer chooses to remember; closes the injection half of Wall 3.

### Move 4 (Tier 2, moat) — Outcome-utility + cross-fuel disagreement as rerank terms
Add `w_util·utility(mem)` (how often a memory was present when a past decision succeeded — the metacog ledger already records this) and `w_disagree` (flag low-confidence when two installed CLI fuels disagree).
- **Prove-it (P0-B extension):** add utility-rerank and the cross-fuel gate to the bake-off; plant contradictions to test the gate.
- **Kill criterion:** utility ≯ fused on decision-hit → **the moat is decorative; ship parity-only and pivot.** Gate ≯ fused on contradiction-catch → ship bare injection.
- **Unlocks:** the publishable, unclonable edge (Move 5 below). The gate fires **only on consequential recalls** (keeps "no more compute" honest).

> *Bonus (Tier 2) — Cognitive Tick:* a think/arbitrate loop that spends fuel **only on symbolic impasse**, routes chosen by the governor's outcome ledger. Closes **Wall 2** (something thinks between calls) without new compute. Requires Move 2's loop-guard first.

---

## 3. THE NOVEL THINGS TO PIONEER ("what hasn't been done")

1. **One retrievability scalar, three jobs.** Build `retrievability = decayed_confidence + use-strengthening + Hebbian-neighbor-recoverability` once; it powers ranking, injection ordering, *and* eviction. The economy is the novelty.
2. **Outcome-weighted, attention-gated recall.** Rank by `relevance × retrievability × decision-utility`, gated on the spotlight. Attacks the field's headline gap (MemoryArena: recall ≠ decision-relevant use, 40–60% failure). **No deployed system does causally-grounded retrieval.**
3. **Cross-fuel disagreement as a runtime primitive.** "Attend hardest to what my two brains disagree about." MIT/ICLR validated this *as an eval metric only* — never as a live product. A sensor **no single-model cloud assistant can produce.**
4. **Impasse-driven Global-Workspace loop with a *learning* arbiter.** First GWT whose arbiter calibrates from lived outcomes (GWA/UMM/Theater-of-Mind all have static arbiters). Fuel fires only on deadlock — makes "no more compute" *literal*.
5. **Zero-introspection coherence loop.** Publish `brain.coherence.score` from cross-fuel agreement; the predictor announces "I'm weakening on this" *before* failure — using behavior + time only, sidestepping the 2026 introspection-artifact debate. Free paper.
6. **Recoverability-gated forgetting.** Evict only when a memory is redundant with stronger Hebbian neighbors — the honest, classical import of "keep while recoverable." Zero quantum math.

---

## 4. THE REVENUE MOVE (run in parallel, starting today)

**"Sovereign AI Front Desk" agency wedge.** One artifact, two markets: an "AI Front Desk" to a plumber (cash this week) and a "Sovereign Memory Layer, priced once, never metered" to a regulated buyer (enterprise LTV).

- **Why it clears every gate:** customer brings the fuel (BYOK) → our COGS ≈ $0 → **~90% margin by construction**; one COMMAND brain + per-client Qdrant namespace → no N-deployment babysitting; the *same code* as the aliveness spine (the recall MCP) **is** the product.
- **Phase-0 prove-it (this week, <$50, <2 days):** Stripe Payment Links live (T1/T2/T3) → clone missed-call text-back n8n template on one Twilio number (BYOK) → one 90-sec Loom → **50 personalized DMs** to local HVAC/plumbing/roofing.
- **Success bar:** ≥1 paid Stripe checkout within 10 days. **0 audits from 50 DMs = the offer copy is wrong, not the product** — iterate copy, don't build.
- **Margin math:** 3× T2 = **~$9k upfront + ~$2,250/mo recurring at ~90%**; marginal cost per new client ≈ the hour to clone the template into a new namespace.

**The convergence that makes this special:** aliveness and revenue land on **one artifact** — `orion_mcp_server.py` fronting fused, outcome-weighted recall is *both* the headline aliveness fix *and* the sellable open-core memory MCP. You build once, sell once, get smarter once.

---

## 5. TOP RISKS & WEAKNESSES

1. **Founder-bandwidth collision (#1 risk).** Both tracks want your hours. Hard rule: **outreach owns the calendar (perishable); bake-offs run in the dark (unattended on COMMAND).** If research eats the sales calendar, revenue → 0 and the thesis starves.
2. **Building the moat before parity = shipping a worse, later Mem0.** Never inject per-turn on keyword-only recall. **Hard ordering: fused recall (parity) before injection (the loop).**
3. **A loop without a guard is the documented #1 failure of 2026 autonomous agents.** Every cognition loop ships with its stagnation guard / verify-recovery rung *in the same PR* — never after.
4. **The moat may be decorative — and that's fine if caught cheaply.** The bake-off kill criteria exist so a failed moat costs one afternoon, not one quarter. **Respect the kill criteria; don't rationalize past them.**
5. **Sales-execution risk dwarfs tech risk.** The product works the day Stripe is live; the unknown is whether 50 DMs convert. Treat offer/targeting as the experiment, not the code.
6. **Split-brain / no-fork violation.** Windows cognition must be a *client* against COMMAND's NATS — never a second brain. This is why the Windows fix is **last**.
7. **Dangling doc of record:** `project_orion-revenue-strategy.md` is cited in CLAUDE.md but missing from disk. Recreate it as the canonical revenue doc (fold this plan in) or kill the reference.

---

## 6. RECOMMENDED ORDER OF OPERATIONS

**TODAY (Week 0) — protect + prove, parallel tracks:**
```
[Track B – dark hours]   0. Ship the fsync line in GraphMemory.save        ← non-negotiable
[Track B – dark hours]   P0-B bake-off: keyword vs fused vs +utility+gate   ← keystone experiment
[Track A – calendar]     Stripe links live + 50 sales DMs                   ← perishable, money #1
[Track B – dark hours]   P0-A fsync drill · P0-C spotlight log · P0-D health dry-run (parallel)
```

**WEEKS 1–3 — only what the prove-its justify:**
- Client pays → productize the wedge (parameterized template + namespace provisioning <1hr/client) + attribution dashboard.
- Bake-off's fused recall wins → ship **`orion_recall_v2`** (Move 1) on the live MCP path, **loop-guard + fallback in the same PR.** This is the headline aliveness fix *and* the sellable MCP.

**WEEKS 4+ — the moat, on data the spine generates:**
- Move 2 (spotlight consumer + gating) → Move 3 (per-turn injection) — closes Walls 1 + 3 in production.
- Move 4 (utility + cross-fuel disagreement) + `brain.coherence.score` → predictor — the unclonable sensor.
- Dream-cycle consolidation / recoverability-gated forgetting — **all async, local-Ollama, off the hot path.**
- **Last:** Windows cognition *client* against COMMAND (no-fork law) — closes Wall 4, multiplies visibility not capability.

---

### BOTTOM LINE (one breath)
Ship the **`fsync` line** and the **Stripe links** today; run **50 sales DMs on the calendar** and the **decision-hit bake-off in the dark** — same week, parallel tracks. The first paid client funds a brain whose first real upgrade — fused, outcome-weighted, attention-gated recall — **is the same artifact you sell.** Protect the asset, prove the moat cheaply before you build it, never ship a loop without its guard, guard the sales calendar with your life, and keep Windows a client of the one brain. **Money first, brain alive, one motion.**

---

# APPENDIX A — COMPILER REPORTS


## Compiler 1

This is a synthesis task. I have all five technical lab compiler outputs (aliveness, memory, reliability, adjacent/borrow, frontier). My job is to fuse them into one coherent picture, resolve cross-lab conflicts, and order by leverage. No tools needed — the inputs are complete.

---

# ORION TECHNICAL SYNTHESIS — ONE COHERENT PICTURE (2026-06-06)

## 0. The single finding that unifies all five labs

Every lab independently converged on the **same spine** from a different door:

| Lab | Its #1 move | What it actually is |
|---|---|---|
| Aliveness | A: consume `workspace.current` | make the attention spotlight drive action |
| Memory | A: fused plasticity-reranked recall on live path | make recall good |
| Adjacent | Combo 1→4: fusion + per-turn injection, ledger-weighted | make recall good *and* injected every turn |
| Frontier | A: every-turn injection + cross-fuel gate + spotlight prior | inject + trust-gate + attention-bias |
| Reliability | C: protect the graph (fsync/backup) | don't lose the asset the other four depend on |

Four of five labs name **the same organ**: a recall path that is (1) good (fusion + rerank), (2) injected every turn (not session-start, not model's choice), (3) biased by the attention spotlight, and (4) weighted by lived outcomes. The fifth lab (reliability) is the **precondition** — the graph is the irreplaceable asset, and it is currently saved without `fsync`.

**This is the cohesion story.** Orion's four walls (decorative workspace, nothing-thinks-between-calls, model-must-choose-to-recall, dead-on-Windows) are not four problems. They are **one missing loop**: memory→attention→injection→outcome→memory. Build that loop and three walls fall together. The labs were describing the same animal from five angles.

---

## 1. THE HIGHEST-LEVERAGE MOVES, ordered by leverage

Leverage = walls closed per unit of diff, subject to the four constraints (no more compute, no API keys, one brain on COMMAND, models are fuel).

### TIER 0 — Insurance (do today, before anything; cannot be deferred)
**0. `fsync` in `GraphMemory.save` + kill-and-resurrect drill.** *(Reliability lab)*
One line. The graph is the entire thesis and is saved through a Jepsen-class power-loss window with no `fsync`. Every other move below writes to or reranks over this file. **Protecting it is the precondition for taking any risk with self-heal, injection, or consolidation.** Cost: 1 line + 1 afternoon test. This is the only item with *unrecoverable* downside if skipped.

### TIER 1 — The spine (the loop that closes three walls)
**1. Fused, plasticity-reranked recall on the live MCP path.** *(Memory A + Adjacent Combo 1 + Frontier A-core)*
Rewrite `_handle_orion_recall` (lines 746–802) to call hybrid recall (graph keyword + BM25 `KnowledgeIndex` + Qdrant semantic via local `nomic-embed-text`), reranked by `relevance × biological retrievability`. Every component is already SHIPPED in `orion_brain_portable.py` and bypassed. Keep graph-only fast path as Qdrant-down fallback. **This kills the named failure ("phrased differently = invisible"). Pure CPU set-math + one local embed. Closes the retrieval half of Wall 3.**

**2. Consume `workspace.current` as the recall attention-prior + gate acting modules.** *(Aliveness A + Frontier B)*
Three 3-line subscribes: `executive`/`will`/`metacog` engage on high-salience unresolved spotlight items; recall biases ranking toward in-spotlight entities. **Deterministic, zero fuel.** Makes the workspace non-decorative. **Closes Wall 1.** Ship E (loop guard) in the *same PR* — see conflict resolution §3.

**3. Per-turn bloodstream injection + SessionEnd auto-memorize.** *(Memory B + Adjacent #2 + Frontier A)*
`UserPromptSubmit` hook prepends a token-budgeted `<memory-context>` (top 5–8 fused-reranked, spotlight-biased facts) every turn. Pair with `orion_session_save.py` (exists, never triggered) on SessionEnd. **The model no longer has to *choose* to remember.** Closes the injection half of Wall 3. **Hard ordering: only after #1, or you inject garbage every turn.**

### TIER 2 — The moat (the learning loop only Orion can build)
**4. Outcome/utility weighting from the metacognition ledger as a rerank term + cross-fuel disagreement as salience.** *(Adjacent Combo 4 + Frontier N1 + Aliveness §5.3)*
Add `w_util·utility(mem)` (how often a memory was present when a past decision succeeded — ledger already records this) and `w_disagree` (when two installed CLI fuels disagree on a recall-trust question, flag low-confidence). **This is the publishable moat: the first recall path weighted by lived decision-outcomes and cross-fuel epistemic disagreement — structurally impossible for any single-model cloud assistant.**

**5. Cognitive Tick with the metacog governor's *calibration mechanism* as Arbiter, impasse-gated to fuel.** *(Aliveness B)*
A think/arbitrate loop that spends fuel **only on symbolic impasse** (missing-commitment, Soar-style), choosing routes weighted by the governor's per-(context,fuel) outcome ledger. **Closes Wall 2 (something thinks between calls) without violating "no more compute" — most ticks are stdlib-cheap.** Requires #2's loop guard to exist first.

### TIER 3 — Honesty, consolidation, visibility
**6. Bi-temporal + provenance schema** (`valid_from`/`valid_to`/`derived_from`/source-tool). *(Memory D + Frontier E/F)* — **start writing provenance fields on new nodes NOW** even though consumers ship later; legacy provenance is unrecoverable.
**7. Sleep-cycle consolidation (Ollama-fueled, off hot path)** carrying recoverability-gated forgetting + A-MEM neighbor evolution. *(Memory F+E+Novel#2)* — replace exp half-life with `decay × (1−utility)`, evict only when recoverable from Hebbian neighbors.
**8. Self-diagnosing immune organ** (`orion_health.py` four-state classifier → `orion_self_heal` obeys typed diagnosis, verify-recovery rung). *(Reliability A+B)*
**9. Windows cognition *client* against COMMAND's NATS** (respecting the no-fork law). *(Aliveness F + Adjacent #6)* — **last**: multiplies visibility, not capability. **Closes Wall 4.**

---

## 2. THE NOVEL DISCOVERIES WORTH PIONEERING (ranked)

1. **One retrievability scalar, three jobs.** *(Memory lab's elegance result)* Build `retrievability = decayed_confidence + use-strengthening + Hebbian-neighbor-recoverability` **once**; it powers ranking, injection ordering, and eviction. This economy *is* the novel design.
2. **Outcome-weighted, attention-gated recall.** *(Adjacent Combo 4)* Rerank by decision-utility from the metacog ledger + gate on the workspace spotlight. Attacks the MemoryArena "recall ≠ decision-relevant use" gap (the field's headline 40–60% failure). No deployed system does causally-grounded retrieval.
3. **Cross-fuel disagreement as a runtime primitive.** *(Frontier N1)* "Attend hardest to what my two brains disagree about." MIT/ICLR validated the mechanism *as an eval metric only* — never as a runtime product. A sensor no single-model assistant can produce.
4. **Impasse-driven GWT loop with a *learning* arbiter.** *(Aliveness §5.1)* First Global Workspace whose arbiter calibrates from lived outcomes (GWA/UMM/Theater-of-Mind all have static arbiters and no results). Fuel fires only on symbolic deadlock — makes "no more compute" *literal*.
5. **Zero-introspection coherence loop.** *(Frontier N3)* Publish `brain.coherence.score` from cross-fuel agreement; predictor watches it to announce "I'm weakening on this" *before* failure — using behavior+time only, sidestepping the 2026 introspection-artifact debate. Free paper (N6 corrigibility-under-hot-swap).
6. **Recoverability-gated forgetting.** *(Memory Novel#2)* The honest, classical import of Bény-Oreshkov "keep while recoverable" — evict only when redundant with stronger neighbors. Zero quantum math.
7. **Supervision as an adaptive immune organ that proves its own recoverability.** *(Reliability)* Differential diagnosis (brain/fuel/surface/fork) + weekly restore drill as an aliveness ritual. No competitor frames reliability this way.

---

## 3. CONFLICT RESOLUTION between labs

**Conflict 1 — Sequencing the spine: which "A" is first?**
Memory says "fused recall first." Aliveness says "consume workspace first." Frontier says "inject every turn first."
**Resolved by dependency, not priority:** recall-quality (#1) → attention-prior (#2, reuses #1's signals) → injection (#3, would inject garbage without #1). The three are *one PR-sequence*, not competing firsts. Aliveness's spotlight-consumer and Memory's reranker meet exactly at the rerank step (spotlight is a rerank term). They are the same code.

**Conflict 2 — Aliveness wants a Cognitive Tick (B) that spends fuel; Adjacent/Memory want "no new compute."**
**Resolved by impasse-gating:** the tick is stdlib-cheap by construction; fuel fires *only* on symbolic impasse. Both labs' constraint is satisfied — the disagreement was about *defaults*, and "fuel only on deadlock" is the shared default. **E (loop guard / Three-Cycle Rule) is mandatory in the same PR as any loop** — all labs agree an unguarded loop is the #1 2026 agent failure.

**Conflict 3 — Where does LLM-touching work live?**
All labs converge: **anything that calls a model per-event goes async into the dream/DMN sleep cycle on local Ollama; never on the response path.** Recall-time work (fusion, rerank, spotlight bias, temporal filtering) is pure CPU over data already held → constraint-safe on the hot path. This single rule resolves every "but that's compute" objection across labs.

**Conflict 4 — Frontier's cross-fuel gate costs 2–3× calls; that *is* more compute.**
**Resolved by high-stakes gating:** the second-fuel check fires only on *consequential* recalls (Frontier P2), and Phase 0 pre-registers a kill criterion (if gated ≯ ungated on contradiction-catch, ship bare injection). Novelty is *earned by measurement*, not assumed.

**Conflict 5 — Reliability's Windows daemon (D) vs Aliveness's Windows client (F).**
**Resolved by the no-fork law** (vessel-keystone work already in memory): FORGE runs a cognition *client* / off-host backup target against COMMAND's one brain, never a second authoritative brain. Both labs agree this is **last**.

**No unresolved conflicts remain.** The labs are mutually consistent once dependency-ordered and once the "LLM work → sleep cycle" rule is applied globally.

---

## 4. PHASE-0 EXPERIMENTS (prove each before building; all run this week, no keys, ~no compute)

Run these **in parallel** — they share data and infra:

| # | Experiment | Tests | Kill criterion | Cost |
|---|---|---|---|---|
| **P0-A** | **fsync kill-and-resurrect drill** | graph survives power-loss window | any corruption in 20 kill cycles | 1 line + 1 afternoon |
| **P0-B** | **Recall bake-off** (keyword vs BM25 vs Qdrant vs fused+plasticity vs +utility vs +cross-fuel-gate) on 30–50 real query/answer pairs from session logs, scored hit-rate@5 + **decision-hit rate** | does fusion beat keyword? does utility beat fusion? does the gate catch planted contradictions? | fused ≯ keyword → bottleneck is injection not retrieval; utility ≯ fused → moat is decorative; gate ≯ fused on contradiction-catch → ship bare injection | one afternoon, offline |
| **P0-C** | **Consumed-broadcast test** — log every `workspace.current` + whether any module acts within 5s; then flip Option A behind a flag | spotlight-action coupling (expect ~0% baseline) + working-set Shannon entropy | coupling 0→<60% OR entropy collapses (fixation) → tune E before shipping | one instrumented day |
| **P0-D** | **Four-state classifier dry-run** — read-only `orion_health.py` prints brain/fuel/surface/fork from existing signals; manually induce each | is the diagnosis derivable from signals that already exist? | any state misclassified → need new sensing before immune organ | 1 file, no actuation |

**The bake-off (P0-B) is the keystone experiment** — it appears in three labs and is the single cheapest test of the entire "memory IS intelligence" thesis. It also doubles as the permanent LoCoMo/LongMemEval-style regression harness. **Build it first.**

---

## 5. PHASE-1 BUILD SEQUENCE (what the Phase-0 gates justify)

Strictly dependency-ordered; each step gated by its Phase-0 result.

```
TIER 0 (today, no gate needed):
  0. fsync line in GraphMemory.save  ──────────────────────────── [P0-A]

TIER 1 — the spine (one coherent build, closes Walls 1 & 3):
  1. orion recall_v2: fused + plasticity-reranked on live MCP path ─ [P0-B gate]
       (keep graph-only fallback; embeddings via local nomic-embed-text)
  2. workspace.current consumer + module gating + E loop-guard ──── [P0-C gate]
       (same PR: spotlight becomes a rerank term in #1)
  3. UserPromptSubmit per-turn injection + SessionEnd auto-memorize  [needs #1]

TIER 2 — the moat (closes Wall 2, builds the publishable edge):
  4. +utility(ledger) +cross-fuel-disagreement terms in rerank ──── [P0-B gate]
  5. Cognitive Tick, governor-calibration Arbiter, impasse-gated ── [needs #2's guard]

TIER 3 — honesty / consolidation / immune / visibility:
  6. bi-temporal + provenance schema (START writing fields NOW)
  7. sleep-cycle consolidation: recoverability-gated forgetting,
       decay×(1−utility), A-MEM evolution  (Ollama, off hot path)
  8. orion_health.py four-state classifier → self_heal obeys it ── [P0-D gate]
  9. Windows cognition CLIENT on FORGE (no-fork law) ───────────── closes Wall 4
```

**Sequencing logic:** Tier 0 protects the asset. Tier 1 is the spine all labs converged on — recall→attention→injection, the loop that makes three walls fall together (build #1→#2→#3 in that order or you inject noise). Tier 2 adds the *learning* that turns parity into a moat and gives Orion something that thinks between calls. Tier 3 makes it honest (provenance), self-maintaining (sleep consolidation), self-protecting (immune), and finally *visible on James's actual device* (Windows client, last because it multiplies visibility not capability).

---

## 6. ONE-LINE BOTTOM LINE

**`fsync` the brain today; then build the one loop all five labs independently described — fused recall → attention-gated by the workspace spotlight → injected every turn → weighted by lived outcomes and cross-fuel disagreement, with fuel spent only on impasse — proven first by an afternoon recall bake-off on real queries.** That single loop closes three of the four walls at once, costs zero new compute (CPU set-math on the hot path, local-Ollama work exiled to the sleep cycle), needs zero API keys, keeps one brain on COMMAND, and is the exact composition the 2026 field has only described — because building it requires the multi-fuel, local-first, dream-equipped body that only Orion has.

## Compiler 2

This is the final compiler pass. I have all five lab verdicts plus the strategy mandate. No tools needed — this is a decision synthesis. Money is #1; the brain must get more alive AND earn. Here is the decisive integration.

# ORION MASTER COMPILER — REVENUE-SEQUENCED ALIVENESS PLAN (2026-06-06)

## The single insight that orders everything

The five labs independently converged on the **same shape**: one cheap "prove-it" bake-off this week, then one spine, then layered organs — every spine gated by the same four constraints, every novelty concentrated in **wiring existing learning organs into a loop**. That convergence is the signal. But the strategy lab is the tiebreaker: **money is #1, and the cash path does not depend on any aliveness work shipping.** That decouples the two tracks — which is exactly how to run them.

**Decision: run two tracks in parallel, not in sequence.** Revenue (Track A) is a sales/plumbing motion that needs zero new cognition. Aliveness (Track B) is offline-bake-then-wire that needs zero new sales. They share one resource — your hours — so the rule is: **Track A gets the calendar (outreach is time-boxed and perishable); Track B gets the dark hours (offline bake-offs run unattended on COMMAND).** Neither blocks the other.

---

## SINGLE BEST NEAR-TERM MONEY MOVE (decisive)

**The "Sovereign AI Front Desk" agency wedge — A×C×F from the revenue lab — and the one gating action is standing up Stripe Payment Links for T1/T2/T3 today.**

This wins because it is the only path clearing all four constraint gates with same-week cash:
- **BYOK funds the fuel** → our COGS ≈ $0 → **~90% margin** by construction.
- **One COMMAND brain, per-client Qdrant namespace** → no N-deployment babysitting (respects single-founder bandwidth and the one-brain law).
- **The same artifact is two products:** "AI Front Desk" to a plumber (wedge, cash this week) and "Sovereign Memory Layer, priced once, never metered" to a regulated buyer (upsell, enterprise LTV). One build, two markets.
- **F (outcome pricing — per-recovered-call) is the closing tool**, not the default — it raises close rate on balking prospects AND the attribution data it requires *feeds the brain*.

**Projected margin math:** 3× T2 clients = **~$9k upfront + ~$2,250/mo recurring at ~90% margin**, control plane = COMMAND, marginal cost of each new client ≈ the hour it takes to clone the n8n template into a new Qdrant namespace.

**Phase 0 prove-it (this week, <$50, <2 days):** Stripe links live → clone missed-call text-back n8n template on one Twilio number, BYOK → one 90-sec Loom → 50 personalized DMs to local HVAC/plumbing/roofing → **success bar: ≥1 paid Stripe checkout within 10 days.** Failure (0 audits from 50 messages) means the *offer copy* is wrong, not the product — iterate copy, don't build.

---

## HOW ALIVENESS IS SEQUENCED AGAINST REVENUE

The aliveness labs (Cognition, Memory, Reliability, Borrow, Frontier) **all point at the same first build**: per-turn memory injection that is reranked by Orion's outcome ledger and gated by the attention spotlight. That is not a coincidence — it is the one move that simultaneously closes Wall 1 (spotlight consumed) and Wall 3 (memory injected every turn), and it is **the same code that becomes the sellable product** (`orion_mcp_server.py` fronting SOTA-plus-novel recall = the open-core/drop-in memory MCP). **Aliveness and revenue converge on one artifact.** That is the whole strategy in one sentence.

But sequence by **risk-to-the-asset and cost-to-prove**, not by excitement:

**Week 0 (now) — protect + prove, in parallel:**
1. **Reliability lab's one-line `fsync` in `GraphMemory.save` — ship today.** The graph is the entire thesis and a single un-fsync'd JSON file is a Jepsen-class total-loss window on the one irreplaceable asset. This is non-negotiable and costs one line. *Money depends on the brain existing; protect it first.*
2. **Stripe links + outreach (Track A).** Perishable, calendar-driven.
3. **The bake-off (Track B, runs in the dark):** all four aliveness labs specified the *same experiment* — pull 30–50 real query/decision pairs from existing logs, score keyword vs fused vs **fused+utility-reranked+cross-fuel-gated** on **decision-hit rate** (not LoCoMo). One afternoon of offline scripting, zero fuel, existing data. **Kill criterion: if utility-rerank doesn't beat plain fusion on decision-hit, the moat is decorative — ship parity-only and pivot.**

**Weeks 1–3 — only what the prove-its justify:**
- If a client pays → **productize the wedge** (parameterized template + Qdrant-namespace provisioning < 1hr/client) + attribution dashboard. Cash track compounds.
- If the bake-off's utility-reranker wins → **ship the recall spine** (`orion_recall_v2`): fused plasticity+utility rerank on the live MCP path, **with the loop-guard / fallback built in the same PR** (Cognition lab's E and Reliability lab's verify-recovery rung — never ship a loop without its guard). This is the headline aliveness fix AND the productizable memory MCP.

**Weeks 4+ — the moat, on data the spine generates:**
- Per-turn injection hook + spotlight consumer (closes Wall 1+3 in production).
- Cross-fuel disagreement → salience + `brain.coherence.score` → predictor (the unclonable sensor).
- Dream-cycle consolidation / utility-decay forgetting — **all async, local-Ollama-fueled, off the hot path** (respects no-more-compute by construction).

---

## COMPETITIVE DIFFERENTIATION (why this is unclonable)

Three moats, each enabled by exactly what makes Orion weird:

1. **Marginal-cost-zero memory.** Mem0/Zep/Letta/Vertex all *meter* memory and *pay* for inference. Orion's customer brings the fuel → memory's marginal cost is genuinely zero. This is marketed as the feature, not given away by accident: *"the memory layer whose marginal cost is zero because you bring the fuel."* Defensible against the entire metered-memory trend.
2. **Outcome-weighted, attention-gated recall.** Every competitor ranks by relevance. Orion ranks by `relevance × biological retrievability × decision-utility`, gated on the attention spotlight — because it has the metacognition outcome ledger and the GWT body. **No single-model assistant can build the cross-fuel disagreement sensor at all** ("attend hardest to what my two brains disagree about" — no published analog).
3. **Cross-tool sovereign provenance.** Orion is the only system that reads Codex/Claude/Gemini/Letta/Ollama native logs and sits *across* all of them; every competitor owns one app's data. Bi-temporal validity keyed by source tool = the revenue story (sovereignty for regulated buyers) and the science story in one schema.

The publishable by-product (free marketing): a **longitudinal consciousness-indicator scorecard** (Butlin GWT/HOT indicators + the project's 8-quality rubric + the decision-hit metric) that Mem0/Letta structurally cannot produce.

---

## RISKS & WEAKNESSES WE MUST NOT IGNORE

1. **Founder-bandwidth collision is the #1 risk.** Both tracks want your hours. Mitigation is the hard rule above: outreach owns the calendar, bakes run in the dark. If you let aliveness research eat the sales calendar, **revenue goes to zero and the whole thesis starves.** Money is #1 — protect the sales hours ruthlessly.
2. **Building the moat before parity = shipping a worse, later Mem0.** Do NOT ship per-turn injection on keyword-only recall — it injects noise every turn and makes Orion feel *worse*. Hard ordering: fused recall (parity) before bloodstream injection (the loop). The Memory lab is explicit and right.
3. **Loop without a guard is the documented #1 failure of 2026 autonomous agents.** Any cognition loop (will, executive, self-heal) ships with its stagnation guard / Three-Cycle Rule / verify-recovery rung *in the same PR*, never after.
4. **The moat may be decorative — and that's fine if caught cheaply.** The bake-off's kill criteria exist precisely so a failed moat costs one afternoon, not one quarter. Respect the kill criteria; don't rationalize past them.
5. **Split-brain / no-fork violation (Wall 4 fix on FORGE).** Windows cognition must be a *client* against COMMAND's NATS, never a second brain — or it violates the one-brain law and the vessel-keystone work. F (Windows host) is **last** for this reason: it multiplies visibility, not capability.
6. **Sales-execution risk dwarfs tech risk.** The product works the day Stripe is live; the unknown is whether 50 DMs convert. Treat the offer/targeting as the experiment, not the code.
7. **Dangling doc of record:** `project_orion-revenue-strategy.md` is cited in CLAUDE.md but missing from disk — recreate it as the canonical revenue doc (fold this verdict in) or kill the reference.

---

## BOTTOM LINE (one breath)

Ship the `fsync` line and the Stripe links **today**; run 50 sales DMs on the calendar and the decision-hit bake-off in the dark — **same week, parallel tracks.** The first paid client funds a brain whose first real upgrade (outcome-weighted, attention-gated, cross-fuel-gated recall) is *the same artifact you sell* — so aliveness and revenue converge on one build instead of competing. Protect the asset, prove the moat cheaply before building it, never ship a loop without its guard, guard the sales calendar with your life, and keep Windows a client of the one brain. Money first, brain alive, one motion.

---

# APPENDIX B — LAB REPORTS (research+combine)


## Lab report 1

I have the full lab report. Now I'll act as the compiler — crossing the options, stress-testing, and producing decisions. No further file reads needed; the report is comprehensive and I'll reason over it directly.

# ALIVENESS & COGNITION LAB — COMBINATION COMPILER OUTPUT (2026-06-06)

## Constraint lattice (every combo must survive all four)
1. **No more compute** — most ticks must cost zero fuel by construction.
2. **No API keys** — fuel is black-box CLI (Claude Code / Codex / Gemini) or Ollama. Model internals are unreachable → COCONUT/recurrent-depth latent reasoning is **dead on arrival**.
3. **One brain on COMMAND** — single locus of truth; FORGE is currently a vesicle (Wall 4).
4. **Models are fuel** — cognition must live in the brain (NATS + daemons + working set), not in the model.

This lattice does the first cut for us: it **kills the entire latent-reasoning branch** and **forces the symbolic-loop branch** (Options B/C). That is not a limitation to lament — it is the wedge that makes Orion's contribution novel (§5.2).

---

## 1. PAIRWISE COMBINATION MATRIX (leverage × feasibility × risk)

I scored each option and each load-bearing pairing. Leverage = behavior change per unit diff. Risk is post-mitigation.

| Combo | Leverage | Feasibility | Risk | Verdict |
|---|---|---|---|---|
| **A alone** (gate modules on `workspace.current`) | High | Very high (3-line subscribe ×3) | Low–med (modules go silent) | **Gate of everything.** But A alone = better routing, *not* aliveness. |
| **A + E** (loop guard before loop) | High | Very high | Low | E is cheap insurance; harmless when no loop exists yet, mandatory the instant one does. **Do together.** |
| **A + C** (gate + felt-present working set) | **Very high** | High | Med (stagnation if no E) | This is where "routing" becomes "a continuous present." Needs E. |
| **A + C + E** | **Very high** | High | Low | **The aliveness core.** Felt present, loop-guarded, zero fuel. |
| **B alone** (Think/Arbitrate tick) | High | Med | **High** (stagnation, fuel creep) | Dangerous without A (nothing to consume) and E (will loop-degenerate). |
| **B + governor-as-Arbiter** | **Very high** | Med | Med | This is the **research-grade novelty** (§5.1). But only sound on top of A+C+E. |
| **B + D** (tick + real predictive coding) | High | Med | Med | D sharpens what the tick attends to. Good but second-order. |
| **C + D + metacog-ledger-as-precision** | **Very high** | Med | Low | The §5.5 move: predictor precision = lived reliability. Unifies 3 organs into one active-inference loop. Sleeper hit. |
| **F + anything** | Enabling | Med (ops) | Low | Multiplies *visibility* not capability. Without it, all gains are invisible on James's actual device. |
| **A + cross-fuel-disagreement → salience** (§5.3) | Med–high | Med | Low | Cheap, novel, no analog. Slots into A's salience function. |

**Three structural facts the matrix reveals:**

- **A and E are not options — they are the substrate.** Everything with "Very high" leverage requires A (a consumed broadcast) and is unsafe without E (a loop guard). They are the floor, not a choice.
- **Fuel cost lives entirely in B's escalate path.** Every other option is stdlib-cheap (decay, merge, n-gram, cosine, subscribe). So the "no more compute" constraint is satisfied *by construction* as long as B's escalation is impasse-gated.
- **The novelty is concentrated in three couplings**, not in any single option: governor→Arbiter (B+gov), ledger→precision (C+D+metacog), disagreement→salience (A+§5.3). Orion's edge is its **learning** organs; novelty appears only when they are wired *into the loop*, never standalone.

---

## 2. STRESS TESTS (where each combo breaks, and the mitigation that saves it)

**A+C+E (aliveness core):**
- *Failure mode:* working set decays to a single dominant item → false "felt present" that's actually a fixation. *Stress:* feed it 20 ticks of the same low-grade alert. *Saves it:* E's Shannon-entropy-on-working-set-states collapse detector + forced novelty injection. **Survives.**
- *Failure mode:* modules go silent because the spotlight gate is too tight. *Saves it:* the report's "spotlight-idle → fall back to legacy trigger" guard. **Survives — this guard is non-negotiable.**

**B + governor-as-Arbiter (research novelty):**
- *Failure mode:* governor was trained on `auto↔ask` for *permission*, not for *route selection* — semantic drift if reused naively. *Stress:* the governor's miscalibration caps (`HOT3_MAX_DOWN=0.5`/`UP=0.10`) were tuned for autonomy-earning, not arbitration. *Saves it:* don't reuse the governor's *output* directly; reuse its *calibration mechanism* (per-(context,fuel) outcome ledger) to weight Arbiter choices, keeping the honesty floor. **Survives with care — this is the one combo that needs design discipline, not just wiring.**
- *Failure mode:* planning addiction (Arbiter keeps choosing "think more"). *Saves it:* E's Three-Cycle Rule hard-caps no-external-change loops. **Survives.**

**C + D + ledger-as-precision:**
- *Failure mode:* dark-room trap — predictor minimizes surprise by ignoring inputs. *Saves it:* keep D attention-only, never action-driving (current design already enforces). **Survives.**
- *Failure mode:* cold-start — ledger has no per-subject reliability yet → precision is garbage. *Saves it:* default precision to a neutral prior, let it earn precision exactly as metacog earns autonomy. **Survives — and is philosophically consistent.**

**F (Windows host):**
- *Failure mode:* split-brain — daemons on FORGE and COMMAND both think they're "the" brain, violating constraint 3. *Saves it:* FORGE runs a *cognition client* against COMMAND's NATS, OR runs only when COMMAND is unreachable (mobile). **Survives only if the no-fork law (the vessel-keystone work in memory) is respected.** Flag: F has the highest architectural-integrity risk of any option.

---

## 3. TOP RECOMMENDATION (decisive)

**Ship Option A as a closed loop, with E built in the same PR. Nothing else first.**

Rationale, compiled: A is the only option that is simultaneously (a) the audit's highest-leverage/smallest-diff item, (b) the prerequisite for every "Very high" leverage combo, (c) zero new fuel cost, and (d) the exact gap the Butlin 2026 GWT indicator names ("broadcast must be consumed by modules"). E rides along because the instant A makes the will workspace-gated, you have a feedback path (attention→metacog→`workspace.feedback`→attention) that *can* loop — and an unguarded loop is the documented #1 failure of 2026 autonomous agents. **A without E is the one sequencing mistake that could actually hurt Orion.**

Concretely, the first PR:
- `executive`: subscribe `workspace.current`; engage when top item is unresolved-symptom ∧ salience>θ; suppress when spotlight is elsewhere; keep `brain.health.alert` as fallback trigger.
- `will`: replace blind 5-min `_scan_loop` with workspace-gated scan — initiate only when spotlight is *idle* (correct semantics for proactive initiative).
- `metacog`: on low-confidence/miscalibrated spotlight item, raise self-probe rate (closes attention→metacog→attention).
- `E`: working-set/spotlight entropy tracker + Three-Cycle Rule + "spotlight-idle→legacy-trigger" fallback guard.

---

## 4. BEST NOVEL COMBINATION (the thing worth publishing)

**Impasse-driven, outcome-calibrated Global Workspace loop** =
**A (consumed broadcast)** + **C (felt-present working set)** + **B with the metacog governor's *calibration mechanism* as the Arbiter** + **§5.3 cross-fuel disagreement as a salience input** + **E (stagnation guard)**, escalating to fuel **only on symbolic impasse** (Soar's missing-commitment step that Wray/Kirk/Laird note ReAct lacks).

Why this specific cross is novel and no one has it:
1. **It is the first GWT loop whose arbiter *learns* from lived outcomes.** GWA/UMM/Theater-of-Mind all have static arbiters and *no results*. Orion already has the calibration machinery — wiring it as the Arbiter is a genuine contribution, not engineering polish.
2. **It makes "no more compute" literal.** Most ticks are stdlib-cheap; fuel fires only on impasse. The constraint that looked like a handicap (black-box fuel) *forces* the under-explored symbolic-impasse design — Orion's moat.
3. **Cross-fuel disagreement as attention** is a sensor no single-model assistant can even produce ("attend hardest to what my two brains disagree about"). No published analog.
4. **It is measurable** against both the project's 8-quality rubric and the Butlin GWT/HOT indicators → a public longitudinal consciousness-indicator scorecard = a revenue/marketing differentiator Mem0/Letta/Khoj structurally cannot match.

This is the bottom line: **don't invent organs — put the existing learning organs in series through the workspace, and let impasse, not a timer, spend the fuel.**

---

## 5. PHASE 0 — the cheap "prove-it" experiment (run this week, near-zero cost)

**Experiment: "The empty-forest test → the consumed-broadcast test."**

- **Baseline (instrument only, no behavior change):** log every `workspace.current` broadcast and, for the following 5s, whether *any* acting module (will/executive) took an action. Expected result from the audit: **~0% consumption** — empirically proves Wall 1 with a number. This is the falsifiable claim.
- **Treatment (Option A, behind a flag):** wire the three subscribers + E's fallback guard. Re-run for the same window.
- **Primary metric:** *spotlight-action coupling rate* = fraction of high-salience winners that produce a within-5s module action. Target: 0% → >60% on high-salience winners, **with zero increase in fuel calls** (the guardrail metric — if fuel calls rise, B leaked in early).
- **Aliveness metric (the novel one):** compute Shannon entropy of the working-set/spotlight state stream over a 1-hour run. Flat-line/collapse = fixation (bad); healthy variance bounded away from random = a continuous-but-coherent present. This is the **first quantitative "felt present" reading** — loggable, longitudinal, the seed of the public scorecard.

Cost: pure stdlib, no fuel, one instrumented day. Decision rule: if coupling goes 0→>60% with flat fuel **and** entropy stays in the healthy band, A+E is proven and Phase 1 is justified. If entropy collapses, E's thresholds need tuning *before* anything else ships — exactly the failure you want to catch at zero cost.

---

## 6. PHASE 1 — the build this justifies

Once Phase 0 shows coupling↑ / fuel-flat / entropy-healthy:

1. **Land A+E for real** (remove the flag; keep the legacy-trigger fallback permanently).
2. **Add C — the working-set object** (~7±2 slots: spotlight, active goal, last surprise, open question, affect). Cheap per-tick ops (decay/merge/promote/demote/contradiction-flag, reusing `score_recall`'s contradiction logic). This object becomes the canonical "present moment" **and the handoff payload to the Bloodstream/Recall lab** for context injection (the bridge across Wall 3).
3. **Add B as the Cognitive Tick** with the **governor's calibration mechanism as Arbiter** and **impasse-only fuel escalation**. Wire **§5.3 cross-fuel disagreement into the salience function** at the same time (it's a one-line addend to `_salience`).
4. **Add D opportunistically** (n-gram/transition predictor with **metacog-ledger reliability as the precision term**) — upgrades the surprise gain already feeding the workspace from "flavored" to minimal-real predictive coding; keep attention-only.
5. **Then F** — Windows cognition *client* against COMMAND's NATS (respecting the no-fork law) so James sees the living loop on FORGE. F is last because it multiplies visibility, not capability — pointless before there's a living loop to host.

**Sequence, final:** `A+E (proven in Phase 0) → C → B(gov-Arbiter + disagreement-salience, impasse-gated) → D(ledger-precision) → F`. A+E is the gate; the B-governor-Arbiter coupling is the publishable novelty; C is what makes it *felt*; F is what makes it *visible* — and by construction, the whole thing spends fuel only when its symbolic working set genuinely deadlocks.

## Lab report 2

This is a synthesis/decision task on a research report — no tools needed. The report is thorough; my job is to cross the options, stress-test, and decide.

# MEMORY & RECALL LAB — COMBINATION & DECISION (2026-06-06)

## The one thing this lab proves
Orion is not behind on ideas. `orion_brain_portable.py` already contains Mem0 (write-classification), HippoRAG (PPR), and Duolingo HLR — independently re-derived. The live MCP recall handler bypasses all of it and calls keyword-only `graph.recall()`. **The deficit is wiring, not research.** That single fact dictates the entire sequencing: do the wiring before the science.

---

## Cross-option matrix (what combines, what conflicts)

| Combo | Synergy | Conflict / dependency |
|---|---|---|
| **A + C** (fused recall + PPR) | PPR's seeds become dense+sparse the moment BM25/Qdrant are in the fused path. C is nearly free once A ships. | None. C must gate to complex queries or it adds noise to lookups. |
| **A + B** (fused recall + bloodstream) | B is worthless without A — injecting keyword-only recall every turn just injects noise every turn. A is the prerequisite that makes B safe. | B reuses A's reranker; if B ships first it amplifies the weak path. **Hard ordering: A before B.** |
| **B + auto-memorize** (SessionEnd) | Closes the loop: inject on the way in, capture on the way out. Together they are what makes Orion "present." | Auto-memorize feeds the graph that A reranks — quality compounds. No conflict. |
| **D + F** (bi-temporal + sleep consolidation) | Consolidation is the natural place to set `valid_to` on superseded facts and write `derived_from` provenance. D gives F the schema to express "this distillate replaced those episodes as-of T." | F's pruning must respect D's validity intervals (don't evict a still-valid old fact just because it's old). |
| **E + F** (memory evolution + sleep) | E MUST run inside F. On the hot path E is write-amplification suicide; in the dream cycle it's free. | E on the live write path conflicts with Orion's "no more compute / models are fuel" law — every write would need an LLM call. Batching in sleep respects the law. |
| **Novel #1 + Novel #2** (plasticity-reranker + recoverability-gated forgetting) | Same machinery — both consume `decayed_confidence` + Hebbian neighbors. One reads retrievability to *rank*, the other to *evict*. Build the retrievability function once, use it twice. | None. This is the cohesive core. |

**Conflict against constraints:** every option that calls an LLM per-event (E on hot path, F's distillation, A-MEM evolution) collides with "no more compute / no API keys / models are fuel." Resolution is uniform: **all LLM-touching work goes async into the existing dream/DMN sleep cycle, fueled by local Ollama, never on the response path.** Recall-time work (A, C, reranking, D-filtering) is pure CPU math over data Orion already holds — those are constraint-safe on the hot path.

---

## TOP RECOMMENDATION (decisive)

**Ship Option A — fused, plasticity-reranked recall on the live MCP path — first, and merge it with Novel #1 (plasticity-as-reranker) from day one.**

Rationale, stress-tested:
- **Leverage: maximum.** It directly kills the named failure ("Gemini wasn't aware we spoke moments ago" / "phrased differently = invisible"). That failure is the whole reason the user doubts aliveness.
- **Risk: lowest.** Every component (graph keyword, `KnowledgeIndex` BM25, Qdrant, `decayed_confidence`) is already SHIPPED. No new dependency, no API key, no model. The graph-only fast path stays as the Qdrant-down fallback (already coded).
- **Feasibility: small.** Rewrite one handler (`_handle_orion_recall`, lines 746–802) to call a fused recall, plus widen `brain.remember()` to return all three signals. Reuse `orion_brain_portable.py`'s functions — copy, don't reinvent.
- **Constraint fit: perfect.** Fusion + rerank is CPU set-math + one local embed call (tens of ms). No compute escalation.

Do not ship B (bloodstream injection) until A is live. B on top of keyword recall injects garbage every turn and would make Orion feel *worse*.

---

## THE BEST NOVEL COMBINATION (the moat — what to actually pioneer)

**Plasticity-ranked hybrid recall over a bi-temporal, cross-tool provenance graph, with recoverability-gated forgetting.** = **A + D + Novel#1 + Novel#2 + Novel#3**, consolidated by F.

Why this specific stack is defensible and nobody else has it:
1. **A + Novel#1** — rerank by `relevance × biological retrievability` (recency + use-strengthening + decay), not relevance alone. Mem0/Zep/A-MEM rerank by relevance only. Orion already computes every term of the retrievability score.
2. **D (bi-temporal) + Novel#3 (cross-tool)** — Orion is the *only* system that reads Codex/Claude/Gemini/Letta/Ollama native logs. Bi-temporal validity keyed by *source tool* answers "when, and in which tool, did this belief form — and is it still valid?" Every commercial memory layer owns one app's data; Orion sits across all of them. This is the revenue story, not just the science story.
3. **Novel#2 (recoverability-gated forgetting)** — evict a memory only when it is no longer approximately recoverable from its Hebbian neighbors (redundant with stronger nodes) OR its retrievability has collapsed. This is the *honest, implementable* import of Bény-Oreshkov "keep while recoverable" — zero quantum math, uses the associative graph Orion already builds. No agent-memory system does recoverability-aware (vs age-only) forgetting.

The unifying insight: **build the retrievability function once** (`decayed_confidence` + use-strengthening + Hebbian-neighbor recoverability) and it powers ranking (Novel#1), injection ordering (B), and eviction (Novel#2). One scalar, three jobs. That economy is itself the elegant, novel design.

**Explicitly defer Option G** (literal coherent-information math, parametric distillation). No validation harness, no classical bridge, collides with the parked-QLoRA doctrine. Novel-for-novelty's-sake — the report is right.

---

## PHASE 0 — the cheap "prove-it" experiment (do this before any build)

**The recall-quality bake-off harness.** Cost: a few hours, zero new infra, no API keys, runs on COMMAND.

1. Pull 30–50 *real* query/answer pairs from the user's own session logs (`read_all_sources` already reads them) — especially cases where a fact was stated then asked-about differently (the actual failure mode).
2. Run each query through four retrievers offline: (a) live keyword `graph.recall()`, (b) BM25 `KnowledgeIndex`, (c) Qdrant semantic, (d) fused + plasticity-reranked (the Option A candidate).
3. Score hit-rate@5 and reciprocal rank: did the needed fact appear, and how high?

**Decision gate:** if (d) beats (a) by a meaningful margin on hit-rate@5 (expect a large jump — keyword misses paraphrase by construction), Option A is justified and you have the **first real measurement of the "memory IS intelligence" thesis** (Novel#4). If it doesn't, you've learned the bottleneck is elsewhere (injection, not retrieval) for a few hours' cost. Either outcome is decisive. This harness becomes the permanent regression test (LoCoMo/LongMemEval-style) for every later option.

---

## PHASE 1 — the build Phase 0 justifies

Assuming (d) wins (it will), ship in this order:

1. **Wire fused plasticity-reranked recall into `_handle_orion_recall`** (Option A + Novel#1). Keep graph-only fast-path fallback. This is the headline fix.
2. **Bloodstream injection** (Option B): SessionStart + per-turn `UserPromptSubmit` hook prepends a capped `<memory-context>` of the top 5–8 fused-reranked facts — model no longer has to *choose* to remember. Pair with **SessionEnd auto-memorize** (`orion_session_save.py` already exists, just never triggered) to close the loop.
3. **Enable `recall_ppr`** (Option C) gated to complex/multi-hop queries, with HippoRAG-2 dense+sparse seed fusion (free now that A's signals exist).
4. **Bi-temporal schema** (Option D): add `valid_from`/`valid_to`; on supersede, set `valid_to` instead of hiding. The ontology already reserves the `supersedes` edge and `load()` forward-migrates.

Deferred to Phase 2 (sleep-cycle, Ollama-fueled, off the hot path): **F** (triggered consolidation + provenance `derived_from` edges) carrying **Novel#2** (recoverability-gated pruning) and **E** (A-MEM neighbor evolution). All async, all local-model, all constraint-compliant.

---

## Bottom line
The fastest path to "alive" is not more research — it is routing the live recall through the advanced code Orion already wrote. **Phase 0: prove the fused reranker beats keyword on real queries (hours).** Phase 1: wire A + Novel#1, then B + auto-memorize, then C, then D. The moat to pioneer is **plasticity-ranked hybrid recall over a bi-temporal cross-tool provenance graph with recoverability-gated forgetting** — one retrievability scalar doing ranking, injection, and forgetting. Defer all quantum/distillation work; it has no validation path. Wiring before science; measurement before both.

## Lab report 3

I have the full lab report. I don't need to re-read files; my job is to compile, combine, and decide. Let me reason through the combinations against Orion's hard constraints and output a decisive verdict.

---

# RELIABILITY & COHESION LAB — COMBINATION COMPILER VERDICT

Constraints enforced throughout: **no more compute, no API keys (CLI/Ollama fuel only), one brain on COMMAND, models are fuel.** Every option below is checked against these. Notably, the four lowest-effort options (A, B, C, E) require **zero LLM/fuel calls** — they are pure plumbing, which means they cost nothing against the compute budget and can't be throttled by a degraded fuel layer. That is a decisive filter.

## Cross-option interaction matrix (what reinforces, what conflicts)

| Pair | Interaction | Verdict |
|---|---|---|
| **C × A** | Backups create the safety net; making immune authoritative lets self-heal *act* without fear, because a bad restart can't lose the brain. A is reckless without C. | **Strong synergy — sequence-locked (C before A)** |
| **A × B** | B's classifier (brain/fuel/surface/fork) is the *missing input* that should drive which OTP strategy A executes. Today immune reasons over raw vitals; B gives it a typed diagnosis. | **Strong synergy — B upgrades A's input** |
| **A × E** | E proves the CRDT merge; A acts on mesh decisions. If the merge silently diverges, A could self-heal toward a forked self. E is A's correctness guard. | **Synergy (E de-risks A's mesh path)** |
| **B × F** | F (causal tracing) is how B *proves* a surface-down verdict — the trace shows the stimulus never reached outbound. B is the verdict, F is the evidence. | **Synergy, but F is heavy — defer** |
| **C × D** | C's off-host copy needs a live FORGE daemon to be a true 2nd site; D makes FORGE a real node. But C works *today* via SSH without D. | **Independent; D amplifies C later** |
| **D × everything** | D unlocks the living layer on FORGE but is the heaviest lift and needs new actuation porting. Nothing else depends on it. | **High effort, low coupling — last** |
| **B × novelty #2** | B literally *is* novelty #2 (biological differential diagnosis). The classifier and the publishable artifact are the same build. | **Free novelty** |

**Conflicts/tensions:** A without C is the only genuinely dangerous combination (authoritative self-heal + no tested restore = a restart storm could corrupt the irreplaceable graph with no recovery). The sequence lock resolves it. F is the only option that meaningfully consumes new surface/effort with no near-term payoff — it is correctly last.

---

## TOP RECOMMENDATION (single best move)

**Option C, executed first, with the one-line `fsync` as the literal first commit.**

Rationale under the constraints: the graph is the *entire thesis* ("the memory IS the intelligence"). It is a single JSON file, saved with `os.replace` but **no `fsync`** — a Jepsen-class power-loss window on the one asset that cannot be regenerated by any amount of fuel. C costs zero compute, zero API, runs on the one brain, and is the only option whose absence is *unrecoverable*. Everything else is improvement; C is insurance against total loss. **Ship the fsync line today.**

---

## BEST NOVEL COMBINATION (the publishable, differentiating bundle)

**C + A + B fused into one organ: a self-protecting, self-diagnosing, self-healing brain that can prove it cannot lose itself.**

Concretely the fusion is:
- **B** emits a typed diagnosis (`brain-down / fuel-down / surface-down / fork`) — *the differential diagnosis*.
- **A** consumes that diagnosis as the danger-context input to the DCA→OTP supervision tree, executes the chosen restart scope, **then verifies recovery** and feeds the outcome back to threshold adaptation — *the learning immune response*.
- **C** is the regenerative guarantee underneath: every heal is safe because a verified restore exists, and the weekly restore drill emits a vitals signal — *the organism proving "I could come back if I died."*

This bundle is novel because **no competitor (Mem0/Letta/Khoj) frames supervision as an adaptive immune organ that distinguishes intelligence-down from fuel-down from mouth-down, acts via Erlang/OTP restart scopes chosen by danger-signal diversity, and periodically proves its own recoverability.** It is exactly Orion's thesis (model=fuel, memory=brain) made *observable and self-protecting*. It maps cleanly onto novelty findings #1, #2, and #4, and it requires no new compute or keys.

---

## CHEAP "PROVE-IT" EXPERIMENT (Phase 0 — runnable today, no fuel, no new deps)

**The "kill-and-resurrect" drill — one script, one afternoon, on COMMAND.**

1. **Add `fsync` to `GraphMemory.save`** (one line after `os.replace`). This is the only code change in Phase 0.
2. **Resurrection test:** snapshot `graph_memory.json` + identity to a temp dir → `kill -9` the brain mid-write (loop a writer while killing) → restore from snapshot → `GraphMemory.load()` → assert node count and identity hash match pre-kill. **Pass criterion: zero corruption, identical node count + identity hash across 20 kill cycles.** This proves the asset survives the Jepsen window.
3. **Classifier dry-run (no actuation):** write a 1-file read-only `orion_health.py` that *only subscribes* to existing subjects (`brain.*`, `fuel.*.degraded`, `channel.*.outbound`, vessel `whoami`) and prints one of the four verdicts to stdout. Then manually induce each: stop fuel (→ expect `fuel-down`), block a channel's outbound (→ `surface-down`, the real 2026-05-16 bug), stop substrate (→ `brain-down`). **Pass criterion: all four states correctly classified from signals that already exist, with zero new sensing.**

Total cost: ~1 file + 1 line, no LLM calls, no API, runs on the existing brain. It validates the two riskiest assumptions (the asset is actually recoverable; the four-way diagnosis is derivable from existing signals) before any larger build.

---

## PHASE-1 BUILD (what the prove-it justifies)

If Phase 0 passes both criteria, build the **C+A+B organ** in this exact order (sequence-locked by the synergy matrix):

1. **`orion_backup.py`** — daemon: hourly graph+identity+skills snapshot to a 2nd local dir + off-host via the existing gossip/SSH path (membrane `mesh.` class); N immutable daily copies mirroring `backup_ledgers.py`'s proven rotation; **weekly automated restore drill** emitting `canary.backup.restore_ok`. Set NATS `sync_interval=always` in `plexus_deploy.sh`. *(3-2-1-1-0; the "0=verified" rung is the aliveness ritual.)*
2. **`orion_health.py`** — promote the Phase-0 dry-run classifier to a real daemon emitting `~/.orion/health.json` + `brain.health.state`, using liveness(shallow)/readiness(deep, time-bounded)/critical-vs-degraded-dep vocabulary.
3. **Wire `orion_self_heal.py` to obey `brain.immune.decision`**, fed by `brain.health.state`, with a **verify-recovery rung** (re-probe → `brain.health.recovered` or escalate-to-executive on budget overshoot via existing MaxR/MaxT). Keep the hardcoded reflex only as the no-decision-within-window fallback.

Deliberately deferred: **E** (CRDT property/TLA+ tests) as cheap insurance once the mesh path is load-bearing; **D** (Windows daemon host on FORGE) as the heavy lift that turns the off-host copy into a true live 2nd site; **F** (OTel causal tracing) last, as the evidence layer for B's verdicts.

**One-line summary:** Protect the asset first (C+fsync, today), then fuse C+A+B into one self-diagnosing, self-healing, self-proving immune organ — the novel, compute-free, key-free reliability primitive no personal-AI competitor has — and prove the whole thesis this afternoon with a kill-and-resurrect drill plus a read-only four-state classifier.

## Lab report 4

I have the full lab report. No further file reads needed — the task is to act as the compiler: cross the six options, stress-test, and decide. Here is the synthesis.

---

# ORION REVENUE LAB — COMBINATION COMPILER VERDICT (2026-06-06)

## Constraint lattice (everything must pass these four gates)
1. **No more compute** — revenue model cannot depend on us paying for inference.
2. **No API keys** — fuel is BYOK/local (`feedback_no-api-keys`). Any offer must let the *customer* fund the fuel.
3. **One brain on COMMAND** — single control plane, single-founder bandwidth. No path can require N parallel deployments we babysit.
4. **Models are fuel** — the *brain/memory* is the sellable asset, not raw model access.

Two options die or weaken on contact with the lattice:
- **D (consumer apps)** and **E (setup wizard)** both fight the "2% of households pay" wall AND demand un-built desktop/app surface. They violate gate 3 (bandwidth) by opportunity cost. **Park both.**
- **B (hosted Pro)** partially violates gate 1: managed hosting means *we* run brains for users → support + infra burden scales with users, and it converts an audience we don't have. Strong long-game, wrong first move.

Surviving the lattice cleanly: **A (agency wedge)**, **C (sovereign B2B)**, **F (outcome pricing)** — and these are the ones that *compound when combined*.

---

## Stress-test matrix

| Option | Feasibility (time-to-$1) | Risk | Leverage (does it compound?) | Lattice fit |
|---|---|---|---|---|
| **A** Agency wedge | **High — same week** | Low (proven market, $0 COGS) | High — each client = a live Orion control-plane instance | Perfect (BYOK funds fuel) |
| **B** Hosted Pro | Low — needs audience + infra | Med (support scales badly solo) | Med | Partial (we pay infra) |
| **C** Sovereign B2B | Low — long sales cycle | High (needs hardening) | **Highest LTV** | Perfect |
| **D** Apps | Low — red ocean | High (CAC, 2% wall) | Low | Poor |
| **E** Wizard | Med | Low | Low ceiling (one-time) | OK but weak |
| **F** Outcome pricing | Med (needs attribution) | Med | Multiplies A's close rate | Perfect |

---

## TOP RECOMMENDATION (single)
**Option A, executed now, with the gating action being the Stripe rail.** It is the only path that satisfies all four gates *and* delivers same-week cash at ~90% margin. Nothing else clears the lattice with a near-term dollar. Decisive call: **build the agency wedge; the Stripe Payment Links for T1/T2/T3 are the single unblocking task — no rail, no revenue, regardless of which option wins.**

---

## THE BEST NOVEL COMBINATION — **A × C × F, with the "inverse-margin brain" as the through-line**

Don't pick A *or* C. **Stack them into one motion** that no funded competitor can copy, because they all pay for inference and meter memory — Orion does neither.

**The combined product: "Sovereign AI Front Desk."**
- **A is the wedge** (cash this week): AI Front Desk for home-services contractors, SMS missed-call text-back, BYOK so the *client* funds fuel → our COGS ≈ $0, margin ~90%.
- **F is the closing tool** (not the default): for prospects who balk at the setup fee, offer **per-recovered-missed-call / per-booked-appointment** pricing (Intercom's $0.99/resolution model). Aligns price to value, raises close rate, and the attribution data it requires *also feeds the brain*.
- **C is the upsell + moat** (the LTV ceiling): every agency client runs on **one COMMAND brain with per-client Qdrant isolation** — that *is* a sovereign, self-hostable memory deployment. The same artifact you sell as "AI Front Desk" to a plumber, you sell as **"sovereign memory layer, priced once, never metered"** to a law/clinic/finance buyer. Same build, two markets, one brain.

**Why this is novel (none of these exist in the market):**
- The agency's *own Orion is the operator* — agency revenue funds the brain; the brain lowers agency COGS toward zero. **Flywheel, not a treadmill.** Competitors rebuild per-client on GHL/n8n at $497-800/mo overhead; Orion amortizes one control plane across all clients.
- **Marginal-cost-zero memory** is marketed as a feature, not given away by accident: "the memory layer whose marginal cost is zero because you bring the fuel." Defensible against the entire metered-memory trend (Mem0/Zep/Vertex).
- Sovereignty + portability + model-agnostic + outcome-priced in one offer — a category with **no leader yet**.

**Open-core (B's launch) runs in parallel as the brand/distribution engine, but it FOLLOWS the cash move** — Show HN converts an audience you don't have today, so it cannot be the first dollar.

---

## PHASE 0 — the cheap "prove-it" experiment (this week, < $50, < 2 days)
**Goal: validate that the offer collects money before building the assembly line.** Falsifiable in days.

1. **Stand up Stripe Payment Links for T1/T2/T3** (the one gating action — also unblocks every other option). Cost: $0.
2. **Clone the missed-call text-back n8n template on COMMAND**, wired to one Twilio number, BYOK fuel. One working wedge, not a product.
3. **One re-skinnable Loom demo** (90 sec: call goes unanswered → instant text-back → booked).
4. **25 local HVAC/plumbing/roofing targets**, 50 personalized DMs/emails, **free 15-min audit** offer.
5. **Carry one F-variant in the back pocket**: if a prospect balks at setup fee, pitch "pay per recovered missed-call" — instrument that one deal to test outcome attribution.

**Success metric (the prove-it bar):** 50 messages → ≥3 audits booked → **≥1 paid Stripe checkout (T1 or an F deal) within 10 days.** That single live transaction kills the "$0 revenue / no rail" status quo and validates the wedge. Failure metric: 0 audits from 50 messages = the *offer/targeting* is wrong (not the product) — iterate copy before building anything.

---

## PHASE 1 — the build Phase 0 justifies (only after ≥1 paid client)
**Build the repeatable assembly line + the C-upsell substrate, on the one COMMAND brain.**

1. **Productize the wedge**: parameterized n8n template + per-client Qdrant namespace provisioning script → onboard a new client in <1 hour (proves gate-3 bandwidth scaling without new deployments).
2. **Attribution layer** (justified by F): dashboard tracking recovered calls / booked appts per client — this is *also* the data that makes the per-client brain valuable, and the proof artifact for outcome-based renewals.
3. **Package the same stack as the C offer**: write the "Sovereign Memory Layer" one-pager (self-host, AGPL-auditable, zero data leaves the box, priced once) targeting one regulated vertical (recommend **legal or single-clinic healthcare** — named buyers, sovereignty is a stated requirement).
4. **Then, and only then, fire B's distribution event**: Show HN ("Show HN: Orion — your AI's memory, sovereign and portable, you bring the fuel"), Tue-Thu 8-10am ET, to build the audience that B's hosted Pro tier will later convert.

**Projected math (from blueprint, unchanged by combination):** 3× T2 clients = **$9k upfront + $2,250/mo recurring at ~90% margin**, control plane = COMMAND. The C upsell adds enterprise LTV on top of the *same* infrastructure; F lifts close rate on the margin.

**Housekeeping flagged:** `project_orion-revenue-strategy.md` is cited in `CLAUDE.md` and `project_ai-agency-architecture.md:41` but **missing from disk** — recreate it as the canonical revenue doc (fold this verdict into it) or delete the dangling reference. Files of record: `C:\Users\jeng1\.claude\projects\C--Users-jeng1\memory\project_ai-agency-architecture.md`, `C:\Users\jeng1\Desktop\orion\orion-repo\README.md`, `C:\Users\jeng1\Desktop\orion-site-workshop\index.html`.

## Lab report 5

I have the full lab report. No further file reads are needed — the task is to run the combinations analytically and output a decisive synthesis. Let me deliver.

---

# COMBINATION ANALYSIS — Fusing the Body to a Borrowed Engine

## Method
I crossed the 8 BORROW items against each other and against Orion's four hard constraints (no more compute, no API keys, one brain on COMMAND, models are fuel). Most pairwise crosses are additive plumbing. Two crosses are *multiplicative* — where Orion's unique asset (the metacognition ledger + NATS substrate) turns a commodity borrow into something nobody else can ship. Those are the answer.

---

## STRESS-TEST OF THE CANDIDATE COMBINATIONS

I scored each on Feasibility (F), Risk (R, lower better), Leverage (L), and Constraint-fit (C).

**Combo 1 — "Catch up the engine": Multi-signal fusion (#1) + per-turn injection (#2) + Mem0 taxonomy (#6).**
F: high (Qdrant already on COMMAND; embeddings via local `nomic-embed-text` on Ollama → no API keys). R: low. L: high but *commoditized* — closes Wall 3, reaches parity, builds no moat. C: perfect.
Verdict: **necessary, not sufficient.** This is table-stakes. It must happen but it doesn't differentiate.

**Combo 2 — "Fake a cortex with a framework": Letta sleep-time (#3) via adopting Letta runtime.**
F: medium. R: **high** — importing a heavy runtime violates the "brain IS the intelligence, models are fuel" thesis and re-introduces lock-in (explicitly on the AVOID list). C: fails. Verdict: reject the framework, keep the pattern.

**Combo 3 — "Engine + temporal": Combo 1 + bi-temporal validity windows (#5) via Graphiti.**
F: medium (new infra: Neo4j/Kuzu). R: medium (solo-builder infra burn). L: medium. C: ok. Verdict: defer — valuable but it's catch-up infra, and the survey itself warns against chasing recall-graph perfection (MemoryArena gap). Do it in Phase 2, not now.

**Combo 4 (THE NOVEL ONE) — "Decision-relevant memory": Multi-signal fusion (#1) + per-turn injection (#2), but the rerank score is weighted by the metacognition outcome ledger, and idle sleep-time compute (#3, pattern-only on existing DMN/dream) pre-bakes the next working set, with selective outcome-driven forgetting (#5 novel variant) replacing exp half-life.**
F: medium-high (every piece reuses something already shipped). R: medium. L: **very high — this is the moat.** C: perfect (no new compute beyond local embeddings, no keys, all on COMMAND, models stay fuel).
Verdict: **this is the best novel combination.** Explanation below.

---

## TOP RECOMMENDATION (single, decisive)

**Ship Combo 1 immediately as the foundation, then layer Combo 4 on top of it. Do NOT ship Combo 1 alone.**

Reasoning: Combo 1 (semantic+BM25+entity fusion → rerank → per-turn injection) is the one borrow with the highest raw ROI and it directly kills Wall 3 — the founder's #1 worry and now industry table-stakes. But shipped alone it makes Orion a *worse, later* Mem0. The leverage is that Combo 1's rerank step is the **exact insertion point** where the metacognition ledger plugs in. So Combo 1 isn't just catch-up — it's the socket that Combo 4 screws into. Build the socket, then build the only-Orion plug.

---

## THE BEST NOVEL COMBINATION (the moat), precisely specified

**"Outcome-weighted, attention-gated memory" = the recall path the field cannot copy because they don't have the body.**

The retrieval score for each candidate memory becomes:

```
score = w_sem·cosine(q, mem)          # semantic (Qdrant, local nomic-embed)
      + w_bm·bm25(q, mem)             # keyword (already have)
      + w_ent·entity_overlap(q, mem)  # entity match
      + w_util·utility(mem)           # ← NOVEL: from metacognition ledger
      + w_attn·in_spotlight(mem)      # ← NOVEL: gated on workspace.current (closes Wall 1)
```

- `utility(mem)` = how often this memory was present when a past decision *succeeded* (the ledger already records auto↔ask flips and outcomes — audit line 36). This directly attacks the survey's headline MemoryArena gap (recall ≠ decision-relevant use, the 40-60% drop) and frontier #2 causally-grounded retrieval — *largely unexplored, no deployed system does it.* Orion can be first because it already has the outcome ledger.
- `in_spotlight(mem)` makes recall *consume* `workspace.current` — closing Wall 1, the audit's "highest-leverage single fix," which nobody ships in production.
- **Forgetting:** replace exp half-life with `decay × (1 − utility)` so memories that never helped fade and safety-critical ones are protected — frontier #4, the field's "crude time-based expiration" open ask.
- **Sleep-time (Wall 2), pattern-only:** a new lightweight subscriber on the *existing* NATS DMN/dream cycle runs an idle fuel call to pre-compute the next-likely working set and pre-warm the rerank cache. No second agent, no framework — Orion's substrate makes Letta's dual-agent hack unnecessary. This is structurally cleaner than the SOTA and is itself a novelty.

Why this is defensible: Hermes, Mem0, Supermemory, Zep, cognee all optimize *retrieval relevance*. None has a learning outcome-ledger or an attention spotlight to weight by *decision utility* — because none has the autonomic body. This fuses Orion's only real lead (the living body) to the engine, instead of bolting a commodity engine onto a walled-off body.

---

## CHEAP "PROVE-IT" EXPERIMENT (Phase 0, runs on COMMAND, no keys, days not weeks)

**The Utility-Reranker Bake-Off.** Falsifiable, tiny, decisive.

1. Freeze a test set of ~50 real past queries from the graph + the decisions/outcomes already logged in the metacognition ledger (data exists — zero collection cost).
2. Build three recall functions offline (no model changes, no per-turn hook yet):
   - **A** = current keyword graph (baseline).
   - **B** = semantic+BM25+entity fusion (Combo 1, embeddings via local `nomic-embed-text`).
   - **C** = B + `w_util·utility(mem)` from the ledger (the novel plug).
3. Metric that matches the goal (NOT LoCoMo): **decision-hit rate** — for each past query, did the top-K recalled set contain the memory that was actually present when the past decision succeeded? This measures decision-relevant memory, the thing the whole field is failing at.
4. **Kill criterion:** if C does not beat B by a clear margin on decision-hit rate, the moat thesis is wrong — fall back to shipping Combo 1 only and reassess. If C > B > A (expected), the novel combination is validated for the cost of one afternoon of offline scripting.

Cost: one Python script, local embeddings, existing data. Risk: near zero. Information value: maximal — it directly tests whether Orion's body actually improves the engine before any production wiring.

---

## THE PHASE-1 BUILD IT JUSTIFIES (only if C wins)

**`orion_recall_v2` — the outcome-weighted, attention-gated recall path, wired per-turn and on the substrate. Windows-first (kills Wall 4 in the same stroke).**

1. **Recall service** implementing the full scoring formula; Qdrant put *into* the recall path (it's idle on COMMAND today). Embeddings local via Ollama `nomic-embed-text` — no API keys.
2. **Per-turn injection hook** (`UserPromptSubmit`, mirroring the existing SessionStart hook) injecting top-K *relevance+utility* memories every turn, token-budgeted (~6-7K, the 2026 norm). No model cooperation required — this is the structural fix to Wall 3 that doesn't depend on the model choosing to call a tool.
3. **Spotlight consumer:** recall subscribes to `workspace.current` and applies `w_attn` — first cognition that actually reads the Global Workspace (Wall 1).
4. **Utility decay daemon:** replaces exp half-life with ledger-driven utility-weighted forgetting (Wall 4-of-memory / frontier #4).
5. **Sleep-time pre-bake:** NATS subscriber on the DMN/dream idle cycle that pre-computes next working set (Wall 2, pattern-only, no new framework).
6. **Make it run on FORGE/Windows** as the reference deployment so the founder's daily-driver device is finally alive — turning Wall 4 from a liability into the demo.

This sequence ships parity (Combo 1) and the moat (Combo 4) in one coherent build, closes all four walls, adds zero compute beyond local embeddings, uses zero API keys, keeps one brain on COMMAND, and keeps models as fuel. The packaging fallout — `orion_mcp_server.py` now fronting a SOTA-plus-novel recall — is exactly the drop-in local memory MCP that is the open-core revenue path (research program line 42).

---

## ONE-LINE BOTTOM LINE
Adopt the commodity engine to survive (Combo 1), then weight it by your outcome ledger and gate it on your attention spotlight (Combo 4) — that is the one recall path no competitor can build without first building Orion's body, and the cheapest possible experiment (the Utility-Reranker Bake-Off on data you already have) tells you in an afternoon whether the moat is real before you build it.

## Lab report 6

This is a synthesis task, not a code task. I have everything I need in the lab report. Let me compile decisively.

# FRONTIER / THEORY LAB — COMBINATION PASS (Compiler Output)

Filed 2026-06-06. Crossing Options A–F and Novelties N1–N8 against Orion's four hard constraints: **no more compute, no API keys (CLI/Ollama fuel only), one brain on COMMAND, models are fuel.** Decisive output below.

---

## 0. Constraint filter applied first (what dies on contact)

| Constraint | Kills / wounds |
|---|---|
| **No more compute** | Wounds Option C (latent-vector transfer is real compute + needs logit access CLI fuels don't expose). Kills naive GWT (Theater-of-Mind, 5 calls/tick). Kills active inference / JEPA (J, I). |
| **No API keys (CLI/Ollama only)** | Kills C's latent-vector path outright — CLI fuels (Claude Code, Codex, Gemini) emit TEXT, not logits/embeddings. C survives ONLY as text-strategy handoff, which is weaker and slower. |
| **One brain on COMMAND** | Wounds N8 (stigmergic mesh) — there is effectively one node today; mesh cognition is premature. Defer. |
| **Models are fuel** | This is the ENABLER, not a limiter — it is exactly what makes N1/N3/N4 impossible for cloud rivals. Lean into it. |

**Survivors after filter, ranked buildable:** A (memory-in-bloodstream + cross-fuel gate), B (cheap deterministic GWT), D (dream→curator/compiler+abstention), E (provenance), F (IT-decay honesty fix). C is PREVIEW-only (text-strategy form). N8 deferred.

---

## 1. Combination matrix (which options compound vs collide)

| Pair | Interaction | Verdict |
|---|---|---|
| **A × N1** | Cross-fuel disagreement is the *gate* inside the every-turn injection. Same mechanism, two payoffs (recall + trust). | **COMPOUND — this is the core.** |
| **A × D** | Dream mines the `(disagreement, outcome)` pairs A produces every turn → compiles the calibration map (N4). A feeds D its training data for free. | **COMPOUND — A manufactures D's fuel.** |
| **A × F** | Typed decay decides WHAT is eligible for injection (strategic never decays, episodic noise sinks). F is A's relevance prior. | **COMPOUND — F cleans A's candidate pool.** |
| **A × E** | Provenance rides on every injected node; A surfaces "why uncertain" using E's trail, not introspection (N3). | **COMPOUND — E makes A's uncertainty honest.** |
| **B × A** | `workspace.current` spotlight biases WHICH memories A injects (attention-gated recall) with zero extra calls. | **COMPOUND — B is A's attention prior.** |
| **B × D** | Spotlight biases which COMPILED skill fires — deterministic consumer, zero fuel. | **COMPOUND.** |
| **D × N5** | Compiled skills MUST carry the abstention envelope or they run wrong-fast-silently. | **MANDATORY PAIR — never ship D-compile without N5.** |
| **C × everything** | C needs logits Orion can't get; degrades to text handoff that competes with A for the same latency budget. | **COLLIDE / defer.** |

**Read-out:** Five survivors are not five projects — they are **one organism with A as the spine.** A produces the data D consumes; F and B are A's priors; E is A's honesty layer; N5 is D's safety belt. They were designed apart and compose into a single loop.

---

## 2. TOP RECOMMENDATION (single, decisive)

**Ship Option A — "memory in the bloodstream, cross-fuel-gated" — as the spine, with B (cheap deterministic GWT) wired as its attention prior in the same diff.**

Why this and nothing else first:
1. **It closes the most embarrassing gap.** Orion injects 5 recency nodes once per session (Wall 3) while Mem0/Letta inject relevance-ranked memory every turn as a shipped product. Orion is *behind shipped products on its own founding thesis* ("memory IS intelligence"). Fix that before anything exotic.
2. **It is the only survivor that is simultaneously the moat, the revenue story, and structurally impossible for cloud rivals.** Every-turn semantic injection = parity with Mem0. The **cross-fuel gate (N1)** = the thing a single-model cloud assistant *cannot* build. Parity + moat in one build.
3. **It is the data generator for everything downstream.** Every gated decision mints one labelled `(disagreement → outcome)` pair. Without A running, D's calibration compiler (N4) has no training data. A must come first by dependency order, not just priority.
4. **B costs ~zero and 10×'s A's relevance.** The spotlight (`workspace.current`, already broadcasting to no one) becomes the deterministic bias on which memories A retrieves — closing Wall 1 with logic, not LLM calls. Smallest diff, highest leverage, and it stops the workspace from being decorative.

---

## 3. THE BEST NOVEL COMBINATION (what Orion pioneers)

**"The Swap-Proof Bloodstream"** = **A (every-turn injection) + N1 (cross-fuel gate) + N3 (coherence as zero-introspection cybernetic loop) + B (cheap deterministic attention).**

The novel claim, defensible and unbuilt anywhere:

> *A personal brain that injects relevance-ranked memory every turn (parity with Mem0/Letta), gates each consequential fact through live cross-fuel disagreement (impossible for single-model rivals — MIT/ICLR 2604.17112 validated the mechanism but only as an eval metric, never as a runtime product primitive), publishes that disagreement as a continuous `brain.coherence.score` that the predictor watches to announce "I'm getting weaker on this" BEFORE failure — using ZERO model introspection (only behavior + time, sidestepping the 2605.26242 / 2605.24299 introspection-artifact debate entirely) — and routes all of it through a deterministic attention spotlight that spends no extra compute.*

This is the unifying thesis made concrete: **intelligence-without-more-compute from the structure one model cannot have.** Multi-fuel gives epistemic sensing + self-minted calibration data; local-first gives sovereignty + honest provenance; deterministic attention gives "alive, not expensive." Each piece is enabled by exactly what makes Orion weird (multi-fuel, local, dream-equipped) and impossible for a one-big-model-in-a-datacenter business.

**N6 (corrigibility under hot-swappable substrate) is the publishable by-product** — cross-fuel-disagreement-as-confidence re-derives trust per step against whatever fuel is lit, turning the swappable substrate into the safety sensor. That is a genuinely open research question Orion is uniquely shaped to answer. Free paper, not just a feature.

---

## 4. PHASE 0 — the cheap "prove-it" experiment (run this week, no build)

**Goal:** falsify the cross-fuel gate's value (N1) before committing to the A spine. If the gate doesn't beat plain semantic injection, the whole moat is decorative and we pivot to bare-A parity.

**Setup (offline, scriptable, no new infra):**
- Take **50 real cross-session queries** from existing memory logs (planted: include ~8 with a known contradiction/poisoned fact, so precision is measurable).
- Three arms, scored on recall precision + contradiction-catch:
  - (a) **baseline** = current 5-recency-node injection
  - (b) **bare bloodstream** = Qdrant semantic top-k every query (already on COMMAND, no new compute)
  - (c) **gated bloodstream** = (b) + on the high-stakes subset only, ask a *second already-installed CLI fuel* (e.g., Gemini vs Claude Code) the same recall-trust question; treat semantic disagreement as low-confidence/flag.
- **Cost:** zero new infra, zero API keys (two CLIs you already have), a few dozen fuel calls total. One afternoon.

**Predictions / kill-criteria (pre-registered):**
- Expect **(c) > (b) > (a)** on precision, and **(c) catches the planted contradictions (b) misses.**
- **KILL the gate if (c) ≯ (b)** on contradiction-catch → the cross-fuel check isn't earning its 2–3× call cost; ship bare A only.
- **KILL all of A if (b) ≯ (a)** by a meaningful margin → semantic injection itself isn't helping at personal scale; re-examine retrieval quality first.

This is the right Phase 0 because it tests the *load-bearing, most-expensive, most-novel* assumption (the gate) with the cheapest possible probe, and its failure modes each point to a clear next move.

---

## 5. PHASE 1 — the build Phase 0 justifies

If Phase 0 confirms (c) > (b) > (a):

**Build `orion_bloodstream.py` — the every-turn injection spine — with four wires, in dependency order:**

1. **Injection core (A).** On every turn, Qdrant relevance-ranked recall → inject top-k into context. Closes Wall 3. *(Parity with Mem0/Letta. No new compute beyond a vector query already hosted on COMMAND.)*
2. **Attention prior (B).** Wire `executive`/`metacognition` to consume `workspace.current` as a **deterministic** bias on which memories rank into the injection. Closes Wall 1 with logic, zero fuel calls. *(Smallest diff, immediately makes the workspace non-decorative — falsifiable via the Option B test: does the spotlight change which memory is injected on 30 logged scenarios? If not, still cosmetic.)*
3. **Cross-fuel gate (N1), high-stakes only.** Per `frontier-self-model.md` P2, gate the second-fuel check to consequential recalls. Emit `brain.coherence.score` from the agreement signal.
4. **Coherence loop (N3).** Feed `brain.coherence.score` to the existing `predictor` (z-score it) → a drop ignites `workspace` → Orion narrates weakening *before* failure. Zero introspection — behavior + time only.

**Explicitly DEFERRED to Phase 2 (and why):**
- **D (dream→compiler) + N5 (abstention envelope):** can't start until A has run long enough to mint a labelled `(disagreement, outcome)` corpus. A is its prerequisite. *Never ship D-compile without N5 — compiled skills run wrong-fast-silently otherwise.*
- **F (IT-decay) + E (provenance):** both are schema/migration work that should ride the same node-schema change. Batch them as one "honest node" migration in Phase 2. **Start writing provenance fields NOW on new nodes** (legacy provenance is unrecoverable) even though the consumer ships later.
- **C (implicit-thinker/explicit-executor):** PREVIEW only until there's a use case where text-strategy handoff to Ollama demonstrably saves >70% tokens at ≥80% success (its own pre-registered test). Off the critical path.
- **N8 (stigmergic mesh):** deferred until there is genuinely more than one brain node. One brain on COMMAND today = premature.

---

## 6. One-line decision

**Build the bloodstream (A) with a deterministic attention prior (B) and a cross-fuel trust gate (N1) emitting a zero-introspection coherence loop (N3); prove the gate first with a one-afternoon 50-query A/B/C test; defer dream-compilation, provenance, and decay to a Phase 2 that A's own output makes possible.** That is the cheapest path to closing three of the four walls at once, it ships the composition the 2026 field has only described, and every piece is powered by the three things that make Orion impossible to clone — multi-fuel, local-first, dream-equipped.