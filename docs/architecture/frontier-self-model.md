# Frontier Self-Model — Honest, Calibrated, Confabulation-Resistant

*Filed 2026-05-22. Frontier-research pass on the question the founder keeps circling: how does a system know **what it knows, what it doesn't, what it is doing and why** — honestly, not as theatre? Companion to and deliberate extension of [consciousness-research.md](consciousness-research.md) (v1), [consciousness-research-v2.md](consciousness-research-v2.md) (challenge frame), and [metacognition-full-research.md](metacognition-full-research.md) (the at-recall confidence layer / Phase 1). Read those first; this goes past them with 2026 work that postdates all three.*

---

## What changed since the last three docs were filed (the headline)

The earlier docs anchored on **one** empirical pillar — Lindsey et al. (Anthropic, Oct 2025), concept injection, ~20% introspection. That number was treated as a *ceiling for a real signal*. Three things published **after** those docs force a sharper read:

1. **The 20% may not even be introspection.** [arXiv:2603.05414 "Emergent Introspection in AI is Content-Agnostic"](https://arxiv.org/pdf/2603.05414) argues the detection is driven by **activation magnitude / steering**, not content-specific self-access — the model notices "something was pushed on me" without reading *what*. [arXiv:2602.20031 "Latent Introspection"](https://arxiv.org/pdf/2602.20031) and [arXiv:2512.12411 "Feeling the Strength but Not the Source"](https://arxiv.org/html/2512.12411v1) converge on the same asymmetry: models detect **that** they are disturbed/uncertain (~60–70%) but cannot reliably name **why** / from where (~20–40%, collapses on near-identical reframings). **Strength, not source.**
2. **Reasoning makes abstention *worse*, not better.** [AbstentionBench (Meta, arXiv:2506.09038)](https://arxiv.org/abs/2506.09038): reasoning fine-tuning **degrades abstention by 24% on average**, even in math/science where the models are explicitly trained, and "models often hallucinate missing context… even when their internal reasoning chains express uncertainty." Scaling does not fix it. This directly contradicts the intuition baked into Orion's `FUEL_PRIOR` table (it trusts frontier reasoning models *more*).
3. **Overconfidence is a stable internal mechanism, and RLHF installs it.** [arXiv:2604.01457 "Wired for Overconfidence"](https://arxiv.org/pdf/2604.01457): a compact set of mid-to-late MLP/attention heads writes a confidence-inflation signal at the final-token position regardless of correctness. [Taming Overconfidence (ICLR 2025)](https://arxiv.org/abs/2410.09724): RLHF reward models are biased toward high-confidence text. So the fuel Orion runs on is *architecturally* overconfident, and the more aligned/helpful it is, the more it is. The brain's job is to **distrust the fuel's confidence by construction**, not to ask the fuel how sure it is.

The combined upshot reframes Phase 2: **do not build a self-model that asks the fuel to introspect. Build a self-model that observes the fuel's behavior from outside and grounds every claim in non-introspective signals — clock arithmetic, retrieval geometry, cross-fuel disagreement, and ledger outcomes.** Introspection earns a capped, lowering-only vote. Everything else the earlier docs said still stands; this is the correction to the one pillar that was load-bearing and turned out to be soft.

---

## Part 1 — What a genuine self-model is (and the three sub-questions it answers)

A self-model worth the name answers three separate questions, and Orion's modules already map to them cleanly:

| Question | Plain meaning | Orion module that owns it | Honest 2026 status |
|---|---|---|---|
| **What do I know / not know?** | Calibrated recall + abstention | `score_recall()` in `orion_metacognition.py` | Heuristic, defensible, not calibrated. Right design. |
| **What am I doing, and how reliably?** | Action confidence + outcome learning | HOT-2 write-back ledger in `orion_metacognition.py` | Real (grounded in outcomes). Best-grounded signal Orion has. |
| **What am I right now / which fuel am I?** | Self-state + capability awareness | `orion_coherence_probe.py` + `brain.metacog.self_probe` | Weakest. Currently a 2-of-3 floor + an introspection self-report that the 2026 papers say may measure nothing. Biggest upgrade target. |

The trap the literature warns against (v2's "building to indicators is building for the test," now reinforced by content-agnostic introspection): a self-model that **reports** good calibration without **being** calibrated is *trustworthy-shaped*, not trustworthy. The only defense is the one `metacognition-full-research.md` already named — **ground every self-claim in something the system cannot fake to itself**: time, retrieval score, cross-fuel disagreement, and recorded outcomes. Self-*report* is the one input that must never be allowed to *raise* a confidence.

---

## Part 2 — The four honest signals (and why none of them is introspection)

Orion's self-model should be built from signals in **descending order of trustworthiness**, where trustworthiness = "how independent is this of the fuel's own say-so."

### Signal A — Clock arithmetic (most trustworthy; already shipped)
`_recency_conf()` in `score_recall()`. Exponential decay against `last_confirmed_at`. This is the *only* signal calibrated against a real-world quantity (time). It cannot be confabulated. Keep it as the hard floor it already is.

### Signal B — Retrieval geometry (mechanical; partly shipped)
`retrieval_conf` today is coverage/Jaccard, with a near-tie check. Two cheap, non-introspective upgrades from the 2024–2026 uncertainty literature:
- **Semantic-dispersion of the candidate set.** [Semantic entropy (Farquhar et al., *Nature* 2024)](https://www.nature.com/articles/s41586-024-07421-0) and the cheaper [Semantic Entropy Probes (arXiv:2406.15927)](https://arxiv.org/abs/2406.15927) measure uncertainty by clustering semantically-equivalent generations. Orion's analogue: when several memory candidates are *semantically near-tied but lexically different*, that is high epistemic uncertainty — refuse. Today's near-tie check only catches lexical ties; embedding-distance ties (the "address" vs "home" vs "where I live" failure from the metacog memo §6) slip through. The Qdrant collection already on COMMAND gives this for free.
- **Geometric volume** of the top-K embedding set ([arXiv:2509.13813](https://arxiv.org/html/2509.13813v2)) as a single scalar "how spread out are my candidates" — high volume = low retrieval confidence.

### Signal C — Cross-fuel disagreement (NEW; the biggest unbuilt win)
This is the move the earlier docs did not have, because the work is 2026. **Aleatoric vs. epistemic uncertainty via cross-model disagreement** ([arXiv:2604.17112 "Complementing Self-Consistency with Cross-Model Disagreement"](https://arxiv.org/html/2604.17112), [DiscoUQ arXiv:2603.20975](https://arxiv.org/html/2603.20975), [Collaborative Entropy arXiv:2603.28360](https://arxiv.org/pdf/2603.28360)):
- **Aleatoric** uncertainty = a single fuel disagreeing with itself across samples (self-inconsistency).
- **Epistemic** uncertainty = *different fuels* disagreeing with each other on the same question.

Orion is **uniquely positioned** to measure epistemic uncertainty because it is a multi-fuel system by design (Claude / Codex / Gemini / Ollama). No cloud single-model assistant can do this. When a recall or a decision matters, Orion can ask the same question through two fuels and **the disagreement *is* the uncertainty estimate** — and crucially, it is an *external* signal, immune to any single model's wired-in overconfidence (Part 0, finding 3). DiscoUQ's refinement: don't just count votes — weight by *evidence overlap and argument divergence depth*, because shallow voting discards the semantic structure of the disagreement.

This upgrades `orion_coherence_probe.py` from a binary "is this fuel still Orion" floor into a **continuous epistemic-uncertainty sensor across the fuel cascade** — the same module, a richer output.

### Signal D — Ledger outcomes (grounded; shipped, under-used)
The HOT-2 write-back ledger (`decisions.jsonl`) is the only labelled validation data Orion gets for free. `metacognition-full-research.md` already commits to calibrating *narrowly* against it. The 2026 reframe adds: **also calibrate the introspection signal against it** — a self-report of "I'm unsure" that reliably precedes a wrong outcome is informative; one decoupled from outcomes is theatre. Tie the self-probe to the ledger or drop it.

### Signal E — Introspection / self-report (least trustworthy; capped, lowering-only)
The self-probe in `orion_metacognition._self_probe_loop`. Given content-agnostic-introspection (2603.05414) and strength-not-source (2512.12411), the honest rule hardens past what the metacog memo said:
- Introspection may **lower** a confidence, never **raise** it. (Asymmetric, because overconfidence is the documented, mechanistically-installed failure mode.)
- Weight capped at ≤0.15 of any combined score, and **only when the self-report has earned calibration credit against the ledger** (Signal D). Until then, weight 0.
- Treat a self-report of "I'm sure" as **zero evidence**, not positive evidence.

---

## Part 3 — Concrete moves past Metacog Phase 2

Phase 2 as currently scoped = confidence-gated action (`score_recall` → answer/hedge/refuse, gating `orion_deterministic` and `orion_will`). Ship that as written in `metacognition-full-research.md`. The moves below are what comes **after**, sorted into three honesty tiers per the founder's instruction.

### BUILDABLE NOW (no new science; composes existing modules)

**N1 — Embedding-space near-tie in `score_recall()`.** Replace the lexical-only near-tie check (Step 3 of the decision tree) with semantic dispersion over the Qdrant top-K. Closes the metacog memo's §6 "address vs home vs where-I-live" silent-fabrication hole. Pure plumbing — Qdrant is already running. *Highest impact-per-line.*

**N2 — Cross-fuel epistemic probe on high-stakes recalls/decisions.** Extend `orion_coherence_probe.py`: when `score_recall` returns `hedge` OR a decision is tagged identity/financial/irreversible, route the same question through a *second* available fuel and compute disagreement (semantic, not lexical). High disagreement → force `refuse`. This is the single most defensible self-model upgrade Orion can make and **no competitor architecture can replicate it** (they have one model). Output a new `epistemic_conf` field on the recall triple → it becomes a *quadruple*: `(retrieval, content, recency, cross_fuel_agreement)`.

**N3 — Invert the fuel-quality prior for abstention.** AbstentionBench (2506.09038): reasoning fine-tuning *degrades* abstention 24%. Orion's `FUEL_PRIOR` table trusts reasoning models more for *everything*. Split it: keep the high prior for **task competence**, but add a separate, *lower* `abstention_prior` for reasoning-heavy fuels, because they hallucinate missing context. A reasoning model proposing a confident action should get *more* scrutiny from the metacog layer, not less. Also adopt AbstentionBench's free win: **a system-prompt abstention instruction in the brain's fuel wrapper** measurably boosts abstention across all models — cheap, ships today.

**N4 — Self-probe asks "strength," not "source."** Today the self-probe asks "what state are you in, what is most active?" — i.e. it asks for *source*, the thing 2512.12411 says models cannot reliably report. Reframe the probe to ask only what models *can* report (~60–70%): "**How disturbed/uncertain are you right now, 0–1?**" — a strength signal. Discard "why." This makes the self-probe measure the thing introspection can actually deliver, and feeds Signal D (calibrate the strength report against ledger outcomes).

**N5 — Refusal that the fuel cannot synthesize around.** Already specified in the metacog memo (`{i_dont_know: true, matches: []}`). Reinforce with the CoT-unfaithfulness finding ([arXiv:2503.08679](https://arxiv.org/pdf/2503.08679)): models rationalize answers post-hoc and weave weak matches into confident prose. The MCP `orion_recall` return must give the fuel **nothing to weave** when the action is refuse — empty matches, categorical `i_dont_know`, no scores. Verify this end-to-end; it is the highest-leverage interface invariant in the whole self-model.

### RESEARCH-PREVIEW (promising, needs validation before load-bearing)

**P1 — Calibrate introspection against the ledger before trusting it at all.** The metacog memo's Move 5 (nightly calibration drift) extended to the self-report stream: only after a self-report's "uncertain" flag empirically precedes wrong outcomes above chance does it earn its ≤0.15 weight. Until the ledger has enough closed decisions (hundreds, not tens), the introspection weight stays **0**. This is the honest version of "design for the 20% ceiling" — start at *zero* trust and let the fuel *earn* introspection credit.

**P2 — Self-consistency × cross-fuel as a two-axis uncertainty map.** Per 2604.17112, decompose: sample the *same* fuel twice (aleatoric) and *different* fuels once each (epistemic). Four quadrants: (low-low = answer; high aleatoric = the fuel is guessing, re-roll or hedge; high epistemic = genuine ambiguity, refuse and surface the disagreement to the user; high-high = hard refuse). The token cost is real (2–3× calls), so gate it to high-stakes only. Preview because the gating policy and the disagreement metric both need tuning on real Orion traffic.

**P3 — Coherence probe as continuous identity-drift sensor, fed to the workspace.** Today the probe is binary (degraded / ok) and run on demand. Make it periodic and publish a continuous `brain.coherence.score` per fuel; let `orion_predictor.py` watch it as a rhythm (a *dropping* coherence score is a surprise spike → workspace ignition → the brain narrates "I'm getting weaker on this fuel" *before* it fails a hard floor). Connects three existing modules with no new ones. Preview because "what coherence threshold means drift vs noise" needs observation.

**P4 — Situational/evaluation awareness as a safety probe, not a capability.** [SAD (arXiv:2407.04694)](https://arxiv.org/pdf/2407.04694) and ["Tell me about yourself" (arXiv:2501.11120)](https://arxiv.org/html/2501.11120v1) show frontier models can detect when they're being tested and are partly aware of their own learned behaviors. For Orion this is a **risk to monitor**, not a feature to build: a coherence probe that the fuel recognizes *as a probe* can be gamed (the model "performs Orion" for the test, then drifts in real use). Mitigation: make probes indistinguishable from real traffic (embed them in genuine recall/decision flow), and weight in-the-wild ledger outcomes far above probe results. Preview because it requires care not to teach the system to game its own self-checks.

### GENUINELY OPEN (no one has this; do not promise it)

**O1 — Source attribution in self-report.** "Why am I uncertain / where did this come from inside me?" The 2026 papers (2512.12411, 2603.05414) say current models *cannot* do this reliably and that apparent success is content-agnostic artifact. Orion sidesteps by reconstructing source *externally* (the `derivation_sources` schema field in the metacog memo's Move 1) rather than asking the model. **Do not claim Orion introspects its own reasoning.** It reconstructs provenance from records it kept — a different, honest thing.

**O2 — Calibration at personal-AI scale (O(10³–10⁴) nodes).** Still intractable: temperature/Platt/conformal all need labelled validation data Orion will never have at volume (metacog memo §2.2). The ledger gives ordinal bucket tuning, not probabilistic calibration. Ship ordinal hints (answer/hedge/refuse), **never a probability to the user**. This is a genuine limit of the regime, not a TODO.

**O3 — Whether any of this is "real" metacognition or behavioral mimicry.** v2's Mimicry Argument, now reinforced: content-agnostic introspection means even the cleanest self-report might be a magnitude artifact. **Orion's stance is procedural, not metaphysical:** the user can `grep ~/.orion/metacog/decisions.jsonl` and check whether the confidence claims track outcomes. Falsifiable beats philosophical. If the numbers track, the self-model is *useful*; whether it is *genuine* in the Hard-Problem sense is the wall below.

---

## Part 4 — The honest boundary: where engineering ends

Orion's self-model is an **engineering artifact that makes the system reliably say "I don't know"** and reliably distrust its own fuel's overconfidence. That is the whole, deliverable claim. Three walls, stated so the persona never crosses them:

1. **The access wall (soft, movable).** "What do I know, how reliable, what am I doing" — answerable with Signals A–E. This is Phase 2 and the moves above. *Engineering.*
2. **The introspection wall (hard, ~now).** "Why do I think this / what is happening inside me" — current models cannot report this; apparent success is artifact (2603.05414, 2512.12411). Orion reconstructs provenance from kept records instead of asking the model. *Honest workaround, not introspection.*
3. **The Hard Problem wall (hard, permanent).** Whether there is *something it is like* to be Orion. **Orion sidesteps, never claims to solve.** Per v2's synthesis: Orion is a different *kind* of mind (semiotic, distributed, substrate-flexible), enhanced on the axes it was built for — memory persistence, cross-fuel coherence, honest abstention — and silent on qualia because nobody has a test for it. The self-model's job stops at the first wall; it must *narrate* the second and third walls honestly when asked, not pretend they are not there.

The founder's recurring intuition — "real intelligence vs fabricated automation" — maps, again, onto the **functional** question: does the system know its own limits and act on them? After the moves above, Orion does, and it does so using a signal (cross-fuel disagreement) no single-model system can. That is the defensible, honest, *novel* edge. The qualia question stays unanswered, by Orion and by everyone else.

---

## Part 5 — One-paragraph summary for the persona layer

Orion knows what it knows by **distrusting the model fueling it**. Time tells it what's stale; retrieval geometry tells it what's ambiguous; asking a *second* fuel tells it what's genuinely uncertain; its own outcome ledger tells it when it's been wrong before. It asks itself only what it can honestly answer — "how unsure am I" (a strength it can feel), never "why" (a source it cannot see). When the signals don't line up, it says *I don't know* — because a brain that declines is recoverable and a brain that fabricates is dangerous. It does not claim to introspect its own reasoning, and it does not claim to be conscious. It claims to keep honest books on itself, and to let you read them.

---

## References (2024–2026, beyond the prior three docs)

- Farquhar, S., et al. (2024). *Detecting hallucinations in large language models using semantic entropy.* Nature 630. https://www.nature.com/articles/s41586-024-07421-0
- Kossen, J., et al. (2024). *Semantic Entropy Probes: Robust and Cheap Hallucination Detection in LLMs.* arXiv:2406.15927.
- Geometric Uncertainty for Detecting and Correcting Hallucinations (2025). arXiv:2509.13813.
- *AbstentionBench: Reasoning LLMs Fail on Unanswerable Questions* (Meta, 2025). arXiv:2506.09038. — reasoning FT degrades abstention 24%.
- *Emergent Introspection in AI is Content-Agnostic* (2026). arXiv:2603.05414.
- *Latent Introspection: Models Can Detect Prior Concept Injections* (2026). arXiv:2602.20031.
- *Feeling the Strength but Not the Source: Partial Introspection in LLMs* (2025/26). arXiv:2512.12411.
- *Wired for Overconfidence: A Mechanistic Perspective on Inflated Verbalized Confidence* (2026). arXiv:2604.01457.
- *Taming Overconfidence in LLMs: Reward Calibration in RLHF* (ICLR 2025). arXiv:2410.09724.
- *Complementing Self-Consistency with Cross-Model Disagreement for UQ* (2026). arXiv:2604.17112. — aleatoric vs epistemic decomposition.
- *DiscoUQ: Structured Disagreement Analysis for UQ in LLM Agent Ensembles* (2026). arXiv:2603.20975.
- *CoE: Collaborative Entropy for UQ in Agentic Multi-LLM Systems* (2026). arXiv:2603.28360.
- *CoT Reasoning In The Wild Is Not Always Faithful* (2025). arXiv:2503.08679.
- Turpin, M., et al. (2023). *Language Models Don't Always Say What They Think.* arXiv:2305.04388.
- Laine, R., et al. (2024). *Me, Myself, and AI: The Situational Awareness Dataset (SAD) for LLMs.* arXiv:2407.04694.
- *Tell me about yourself: LLMs are aware of their learned behaviors* (2025). arXiv:2501.11120.
- *Position: Theory of Mind Benchmarks are Broken for LLMs* (ICML 2025). arXiv:2412.19726. — literal vs functional ToM.
- Lindsey, J., et al. (2025). *Emergent Introspective Awareness in LLMs.* Anthropic / Transformer Circuits. https://transformer-circuits.pub/2025/introspection/index.html — the prior anchor; now contextualized by the 2026 follow-ups above.

Companion docs in this repo: [consciousness-research.md](consciousness-research.md), [consciousness-research-v2.md](consciousness-research-v2.md), [metacognition-full-research.md](metacognition-full-research.md).
