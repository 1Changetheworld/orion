# Meta-Cognition Full — Confidence-Aware Recall

*Filed 2026-05-16 in response to founder direction 2026-05-14: "META-COGNITION — confidence-aware recall, brain admits ignorance instead of fabricating." Companion document to [consciousness-research.md](consciousness-research.md) and [consciousness-research-v2.md](consciousness-research-v2.md). The HOT-2 write-back loop already shipped as [`orion_metacognition.py`](../../orion_metacognition.py); this memo specifies the at-recall loop that has to land next.*

---

## Executive summary

Orion's metacognition module already scores decisions *after* the fact and stores the trace; that is HOT-2 write-back. The missing half — and the one the founder named on 2026-05-14 — is at-*recall* confidence: a brain that says **"I don't know"** instead of fabricating a confident wrong answer from a high-coverage lexical match. The current `orion_deterministic.py` short-circuit is the failure surface; "coverage × node-confidence" is not calibrated confidence and a coverage hit can fire on a stale memory the user updated three months ago.

Three things this memo establishes and one it recommends:

1. **Confidence in Orion is at least three different quantities** — retrieval, content, and derivation — and the current schema (`graph_memory.json`) collapses them into one float on the node, which is why the short-circuit can be confidently wrong.
2. **Real probabilistic calibration is not tractable** for a personal brain with O(10³–10⁴) nodes. Temperature scaling, Platt scaling, and ensembles need labelled validation data we do not have. The honest substitute is a **multi-signal heuristic** treated as monotone evidence, not as a probability.
3. **Anthropic's October 2025 introspection result is a ceiling, not a baseline.** ~20% reliable self-detection in a frontier model is the design ceiling for any Orion introspection signal. Introspection participates in confidence; it never grounds it.
4. **Recommendation (single path, concrete):** extend `orion_metacognition.py` with a recall-time scorer that returns a *triple* — `(retrieval_conf, content_conf, recency_conf)` — plus an `i_dont_know` boolean, gate `orion_deterministic` and `orion_will` against the triple, and surface contestation-aware refusal/hedge/answer behavior to the MCP `orion_recall` return shape. The honest backstop, when calibration is bad, is **refusal-first** instead of hedging-first: a brain that declines is recoverable; a brain that hedges teaches the user to ignore the hedge.

The sharpest line: **a confidence score without ground-truth feedback is decoration; what makes Orion's number real is the decision-ledger outcomes already being written by HOT-2 write-back, not the number itself.**

---

## 1. What "confidence" means here — and why one float is wrong

Walk a memory through the system and at least three different uncertainties stack up before it becomes an answer. The current `GraphMemory` node carries exactly one — `confidence: float` — assigned at write time and never reconciled with the others. That is the silent fabrication channel.

**Retrieval confidence — how well does this match the query?** The `orion_deterministic._best_match` function returns `score = coverage × (0.5 + 0.5 × node.confidence) × length_penalty`. That score is **lexical relevance**, not match-quality. A long memorized incident report ("2026-05-10 storage canary fired because TCC denied python3…") will score high coverage on the query "what's wrong with my storage?" even when the canary memory is a closed historical artifact. Better retrieval signals in cost order: BM25 normalization (free upgrade over Jaccard), dense retrieval against the Qdrant collection already running on COMMAND (the `vector_search` `hit.score < 0.3` gate is a *crude* retrieval-confidence signal already — it should be exposed, not hidden), cross-encoder re-ranking of top-K (one extra LLM call), and HippoRAG PPR rank (already implemented as `recall_ppr` in `orion_brain_portable.py`). None of these answer "is the fact still true."

**Content confidence — how sure was the writer?** When `orion_memorize` stores a fact, the writer (almost always an LLM) sets `confidence = 1.0` by default. This is a lie. The model that summarized "the user prefers casual address" from one ambiguous greeting had nothing close to 1.0 evidence. The model that recorded the user's home Wi-Fi password from a direct unambiguous statement did. Both end up as `confidence: 1.0`. The simplest fix is the most useful: split into **`source_strength`** (explicit user statement = 0.95, inferred from context = 0.6, model summary of summary = 0.3) and **`writer_certainty`** (commitment to this exact phrasing). The current single float averages these implicitly into a meaningless number.

**Derivation confidence — propagated uncertainty for inferred facts.** A node "the user works on AI memory systems" was *derived* from many statements about Orion. Its confidence must be a function of the source-node confidences, not an independent assertion. The current schema has no source-link, so derivation chains are invisible. The cheapest honest fix is multiplicative: `derived_conf = prod(source_confs) × derivation_step_strength`. **Without source-link metadata at write time, derivation confidence cannot be reconstructed after the fact.** This is the schema-change-or-give-up moment for this layer.

**Recency confidence — implicit but underused.** `orion_brain_portable.py` already implements `decayed_confidence(node, half_life)` and uses it during ranking. This is the only confidence signal Orion currently calibrates against a real-world quantity (time). It is also the most reliable. The next move is to surface decayed confidence into the **return value** of `orion_recall`, not just into the internal sort, so downstream consumers see *how stale* the fact they got is.

The founder's example — "I have a match but I'm not confident enough to assert it" — is exactly the case where retrieval-conf is high (coverage hit on "address"), content-conf was high at the time, derivation-conf is unknowable, and recency-conf is low (the memory is 14 months old; the user moved). One float cannot represent that. A triple — `(retrieval, content, recency)` — can, and three monotone signals are easier to reason about (refuse if min < threshold) than one over-aggregated number.

---

## 2. Calibration — and the honest assessment that we mostly can't

A confidence score is only useful if it is *calibrated*: 90% confidence should mean 90% accurate over the long run. The literature on this is mature for classifier outputs and largely inapplicable to a personal-AI memory layer.

### 2.1 What the literature offers

- **Temperature scaling** (Guo et al. 2017, ICML): single-parameter post-hoc calibration of deep network logits against a held-out validation set. Cheapest move that works for many networks. *Requires labelled validation data.* Orion has none.
- **Platt scaling** (Platt 1999) and **isotonic regression** (Niculescu-Mizil & Caruana 2005): post-hoc score→probability maps. Same data requirement.
- **Deep ensembles** (Lakshminarayanan et al. 2017): K independent models, use disagreement as uncertainty. The "K independent models" cost is fatal for a Pi-deployable brain.
- **LLM calibration recent work** (Tian et al. 2023 "Just Ask for Calibration"; Kadavath et al. 2022 "Language Models (Mostly) Know What They Know"): verbalized probabilities are approximately calibrated for some questions, reliably overconfident overall. The Anthropic introspection line (Lindsey et al. October 2025) is the frontier — see Part 5.
- **Conformal prediction** (Vovk et al. 2005; Angelopoulos & Bates 2023): wraps any predictor in a prediction-set with frequentist coverage. Needs exchangeable calibration data, which Orion has even less of than the others.

### 2.2 Why the labelled-data requirement is structural for Orion

Every classical calibration technique assumes a corpus of `(prediction, true_outcome)` pairs to fit the calibration map. Orion's recall predictions are mostly statements about the user; the ground-truth signal is the user's reaction, which is sparse, ambiguous, and slow. A user who silently accepts a wrong recall is indistinguishable from a user who silently accepts a right one until the wrong recall causes a downstream incident days later.

One place ground truth comes in fast and clean: the **HOT-2 write-back ledger already shipping** in `orion_metacognition.py`. Every executive decision is scored before and given an outcome after. That ledger is the only labelled validation data Orion will accumulate for free. **The recall-confidence layer should treat the executive ledger as its sole calibration source, scoped narrowly to decision-shaped recalls.** Arbitrary recall questions get heuristic-only treatment. That is a real limit and should be documented as such.

Calibration techniques want N in the thousands to millions of examples. Orion at 30 days of usage has, generously, hundreds. The variance on any calibration estimate at that N is so wide that the calibrated number is almost certainly worse than a sensible heuristic. **Probabilistic calibration is not tractable for a personal AI at Orion's scale.** The honest move is to *not pretend it is* and to publish heuristics under names that don't claim probabilistic semantics.

### 2.3 What does work at personal-AI scale

Three heuristics that don't require labelled data, used as *monotone evidence* rather than probability:

1. **Recency decay against type-specific half-lives.** Already in `orion_brain_portable.py` (`HALF_LIFE_DAYS_DEFAULT`). Half-lives are guesses, but they degrade gracefully — a memory from 14 months ago is *correctly* less trusted than one from yesterday, even if absolute calibration is wrong.
2. **Re-confirmation count.** A fact repeated three times across separate sessions deserves more weight than a fact stated once. `last_confirmed_at` + `recall_count` already exist; the scorer should consume them.
3. **Contestation flag.** A `contested_with` node is, by definition, low confidence. This must hard-gate the deterministic short-circuit (Part 6).

These are not calibrated. They are *defensible* — each points the same direction as ground truth would, even when we cannot measure it.

---

## 3. The fabrication failure mode

`orion_deterministic.py` is the most concrete "confident wrong" risk in the system.

**The concrete failure.** A user asks "what's my address?" via iMessage. `_extract_recall_target` returns `"address"`. `_best_match` runs token-Jaccard against every node and finds one with `content: "user lives at 123 Maple St, Old Town"` from 14 months ago, `confidence: 1.0`, `tags: ["address", "user", "personal"]`. Coverage = high; score = 0.85. THRESHOLD = 0.65. **The deterministic layer publishes "123 Maple St" to `channel.imessage.outbound` and the LLM is never called.** The user moved in January and updated their address in three previous Orion conversations — none tripped contradiction detection because they were stored with different tag sets ("home", "moving", "new place"), and `_find_contradictions` only fires on tag overlap. This is silent fabrication at the speed-layer, exactly what HOT-2 *write-back* cannot catch — the decision never reaches the executive, so metacognition never scores it.

**Taxonomy of "I have a match but I'm not confident":**

| Symptom | Signal that should fire | Current detection |
|---|---|---|
| Match is stale | `decayed_confidence(node) < τ_stale` | Used in ranking, not surfaced |
| Match contradicts another node | `len(node.contested_with) > 0` | Stored, not gated on |
| Match is one of several plausible | Top-2 scores within ε of each other | Not computed |
| Match is on weak source | `source_strength < τ_strong` | Field doesn't exist |
| Query out-of-distribution | `top_score < τ_ood` | Threshold gate exists but additive only |
| Match leaking private-internal data | `"private_internal" in tags` | Filtered already |

The middle four rows are the failure surface the at-recall layer has to close.

**The decision tree the deterministic layer should run**, in order, fail-closed:

1. **Reject** if `contested_with` is non-empty — never fabricate from a contested memory. Refer to LLM path with contestation surfaced.
2. **Reject** if `recency_conf < 0.4` — too stale to short-circuit.
3. **Reject** if top-2 candidates are within ε on combined score — no single best match.
4. **Hedge** if `min(retrieval, content, recency) < HEDGE_THRESHOLD` — answer with explicit uncertainty ("I have it as X, recorded ~Y months ago — still right?").
5. **Refuse** if even hedging is unsafe (private-internal contamination, identity-affecting, financial): "I don't have a confident answer — what is it?"
6. **Answer** only when all three signals exceed the hard threshold AND no contestation AND no near-tie.

Numbers are placeholders; what matters is the *order* and the *fail-closed default*. The current layer has only step 6 with an under-specified threshold and skips steps 1–5.

---

## 4. Refusal vs hedging vs guessing — the decision tree

"I don't know" is a refusal; "I think it's teal, but I'm not sure" is hedging; "It's teal" with no caveat is guessing. The third is the worst possible failure — it teaches the user that Orion's confident statements are unreliable, destroying the *value* of every future confident statement.

First principle: **the cost of a confident wrong answer is asymmetrically higher than the cost of an unnecessary refusal.** A user refused on a question Orion knew is mildly annoyed once. A user confidently misinformed and acting on it loses trust in the entire system. Calibration in the absence of ground truth should bias hard toward refusal.

The mapping by quintile:

| Combined confidence | Behavior | Surface |
|---|---|---|
| 0.9 – 1.0 | Answer | "It's teal." |
| 0.7 – 0.9 | Answer with provenance | "Teal — you mentioned that last Tuesday." |
| 0.5 – 0.7 | Hedge with offered confirmation | "I have it as teal, but it's been a while — still right?" |
| 0.3 – 0.5 | Refuse with offer to learn | "I don't have a confident answer. What's your favorite color?" |
| 0.0 – 0.3 | Refuse, surface contestation if any | "I don't know, and I have conflicting older notes — want to resolve them?" |

The wrong design move is uniform hedging — answering everything with "I think… maybe… probably." Users learn within days to ignore the caveats. **Hedging only works as a signal if Orion uses it rarely.** Refusal is louder, recoverable, and trains the right user behavior (state the fact again) instead of the wrong one (ignore the hedge).

A subtler point: refusal requires the LLM-fueling-Orion to *honor* the brain's refusal rather than synthesizing around it. The recall return shape has to be unambiguous — `{kind: "i_dont_know", reason: "..."}` rather than `{matches: [], note: "..."}` — because every LLM in the loop will, given a list of even weak matches, attempt to "be helpful" by stitching them into an answer.

---

## 5. The Anthropic October 2025 introspection result — ceiling, not baseline

The most-cited and most-misread paper in the room is Lindsey et al. 2025, ["Emergent Introspective Awareness in Large Language Models"](https://transformer-circuits.pub/2025/introspection/index.html). The result, accurately:

- **Concept injection**: artificial activation patterns are inserted into Claude's residual stream; the model is asked whether it noticed.
- **Best result**: Claude Opus 4.1 detects and *correctly labels* the injected concept ~20% of the time, can distinguish injected "thoughts" from text input, and can identify whether outputs were genuinely intended versus artificially prefilled.
- The capacity *emerges with model sophistication*; smaller models perform near chance; refusal-trained variants perform *worse* than base models.
- The authors explicitly disclaim: *"we do not seek to address the question of whether AI systems possess human-like self-awareness or subjective experience."* The mechanism may be "shallow and narrowly specialized."

What this implies for Orion:

1. **The ceiling for introspection-based confidence is ~20% true-positive rate at the frontier**, on the cleanest possible probe. Any Orion design that treats model self-report as *grounding* for confidence will be wrong 80% of the time at best.
2. The 20% is also *not zero* in a regime where the null is zero. Introspection is a *useful* signal; it is just never *authoritative*.
3. Orion cannot do residual-stream injection on a fuel model. The architectural analogue — already shipped in `orion_metacognition._self_probe_loop` — is asking the fuel model "what state are you in right now?" and archiving the response. This is the right cheap version. Its outputs should be treated as *another input* to the confidence triple, never as the confidence itself.

The honest design rule: **introspection participates in the confidence triple as a tiebreaker**, weighted no more than 0.15 in the combined score, and never permitted to *raise* confidence above what the other signals support — only to lower it. A self-report of "I'm unsure" lowers confidence; a self-report of "I'm sure" does not raise it. Asymmetric treatment, because the failure mode of model overconfidence is much better-documented than the failure mode of model underconfidence.

The deeper worry — the one the v2 consciousness memo named — is that *building to introspection indicators* is exactly building for the test. A system tuned to produce well-calibrated-looking introspection reports has not necessarily become well-calibrated; it has become well-tuned-for-introspection-reports. The mitigation is the same one HOT-2 write-back already implements: tie introspection to *outcomes* via the ledger. A self-report of "I'm unsure" that consistently precedes a wrong answer is informative; a self-report decoupled from outcomes is theatre.

---

## 6. Contested memories — lifecycle and confidence interaction

The `contested_with` field already exists in `orion_brain_portable.py` and the MCP server already returns `[contested]` flags in recall results. Lifecycle from the existing code:

- **Becomes contested when:** a `store()` call finds a prior node with the same `type` and overlapping tags but different content. Both nodes get `contested_with: [other_id]` pointers under the default `coexist` policy.
- **Stays contested until:** the user calls `orion_resolve_contradiction(winner_id, loser_ids)`. Losers get `superseded_by: winner_id` (archived, never deleted); winner gets `last_confirmed_at: now`. Without user action, contestation is permanent.
- **Fails to detect when:** conflicting facts are stored with non-overlapping tag sets, different types, or semantic-but-not-lexical overlap. The detector is `len(tags_a & tags_b) >= 1` — it misses "address" vs "home" vs "where I live."

For at-recall confidence, contestation is the cleanest hard-no signal Orion has. A contested node should never short-circuit the LLM and should never be the basis for proactive will-narration. One-line check in `orion_deterministic._on_inbound`; one condition in `orion_will`'s action selection.

Beyond hard-gating, contestation should *promote* the node through the workspace (`orion_workspace.py`) the next time it is touched — contested information is the kind the system needs to attend to most. Already supported by the `workspace.feedback` channel `orion_metacognition` publishes on; the recall layer should publish `{surprise: 1.0, reason: "contested_recalled"}` events when a contested node is retrieved.

The CRDT equivalent: **last-writer-wins under hybrid logical clocks** vs **multi-value registers** (Shapiro et al. 2011, "Conflict-Free Replicated Data Types"). Orion's gossip layer uses HLC + LWW for cross-host replication; the *memory* layer correctly uses multi-value (both kept until user resolves), the right call for facts where wrong-merge has high cost. The CRDT lesson: **keep the merge function out of the hot path; surface the conflict to the user**. Memory does this. The deterministic layer is currently violating it by not even checking.

---

## 7. Recommended architecture — one path

Single concrete recommendation, in five moves, each small enough to land in a session.

### Move 1 — Schema extension on the node

Add three fields to graph_memory nodes:

- `source_strength: float` — how strong was the evidence at write time (0.3 inferred, 0.6 stated indirectly, 0.9 stated explicitly, 1.0 confirmed twice).
- `derivation_sources: list[int]` — node ids this fact was derived from, empty for primary observations.
- `recall_outcomes: list[{ts, outcome}]` — append-only mini-ledger of whether past recalls of this node led to correct downstream behavior (populated by metacognition when the executive ledger closes a decision that touched this node).

`confidence` stays for backward compatibility but is recomputed at recall time from the new fields, not used directly. Migrations: a one-time backfill sets `source_strength = confidence`, `derivation_sources = []`, `recall_outcomes = []` for existing nodes.

### Move 2 — Recall-time scorer in `orion_metacognition.py`

Add a function `score_recall(node, query, now) -> {retrieval_conf, content_conf, recency_conf, combined, basis, action}` where:

- `retrieval_conf` is the existing coverage/PPR/vector score for the (query, node) pair, exposed not hidden.
- `content_conf` = `source_strength × outcome_history_modifier` where the modifier shifts toward 1.0 if the node's past recalls led to correct outcomes, toward 0.0 if they led to wrong ones.
- `recency_conf` = `decayed_confidence(node, half_life_for_type)` already implemented.
- `combined` = `min(retrieval_conf, content_conf, recency_conf)` — minimum, not product, because "weakest signal wins" is the safer aggregation when each component is independently noisy.
- `action` ∈ `{answer, answer_with_provenance, hedge, refuse_unknown, refuse_contested}` per the table in Part 4.

This is the only new code path. Everything downstream consumes the structured return.

### Move 3 — Confidence-aware MCP `orion_recall` return shape

Today `orion_recall` returns a markdown list of contents. The new contract:

```json
{
  "matches": [{"id": 42, "content": "...", "score_triple": [0.8, 0.6, 0.3], "combined": 0.3, "action_hint": "hedge"}],
  "best_action": "hedge",
  "i_dont_know": false,
  "contested_count": 0,
  "stale_count": 1,
  "explanation": "Top match is 14 months old; recommend asking the user to confirm."
}
```

When `best_action == "refuse_unknown"`, set `i_dont_know: true` and `matches: []` — the LLM cannot synthesize what it cannot see. This is the most important interface change and the one that prevents downstream fuel models from "helpfully" weaving weak matches into a confident answer.

### Move 4 — Gate `orion_deterministic` and `orion_will` against the triple

In `orion_deterministic._on_inbound`, replace `if score < THRESHOLD` with: query the new recall-scorer, run the decision tree from Part 3.3, fire only on `action == "answer"`. The deterministic layer becomes correctness-gated, not just relevance-gated.

In `orion_will`, when an intent extraction depends on a recalled memory, require `combined >= 0.6` before promoting the intent to a goal. A goal formed from a low-confidence memory ("user wanted me to text Mom" when the memory is contested) is the worst proactive failure mode — Orion sends an unwanted message based on a misremembered fact.

### Move 5 — Calibration over the executive ledger, narrowly scoped

In `orion_metacognition.py`, add a nightly job: read the closed decisions from `decisions.jsonl`, group by `symptom_class`, compute the empirical accuracy of decisions that used each confidence-triple bucket. Adjust the bucket boundaries (the placeholders in Part 4) so that the `answer` bucket is empirically ~80%+ correct, the `hedge` bucket ~60%, etc. *Do not export these as probabilities.* Export them as ordered bucket labels. This is calibration without claiming calibration — empirical bucket boundary tuning rather than probabilistic mapping.

### Named risks

1. **Threshold tuning is unrelenting.** The bucket boundaries from Move 5 will need re-tuning every time the underlying corpus changes (new user, new topic mix, new fuel model). Without a forcing function, they will drift out of usefulness within months. Mitigation: a weekly `brain.metacog.calibration_drift` alert when bucket accuracy deviates more than 15% from target.
2. **The user trains the system to over-refuse.** If a user says "yes, that's right" to every hedged answer, the ledger will learn that hedging was unnecessary and confidence thresholds will drift lower over time. Mitigation: weight explicit user *corrections* much more heavily than passive acceptances, and surface a "you've been overconfident on X" alert when corrections cluster.
3. **The schema change is invasive.** `source_strength` and `derivation_sources` have to be written by every code path that calls `store()`. Anything that forgets writes `None` and the new scorer has to handle that gracefully. The mitigation is a default of `source_strength = 0.5` (mid-range) for any node missing the field, which biases the scorer toward refusal — failing safe.

---

## 8. Critique of this recommendation

Honest pre-mortem. Three ways this approach is theatre and one way it ships anyway.

**The combined number is decoration.** Move 2 returns a `combined: float` made from three other floats that are estimates of unmeasurable quantities. A user looking at it will assume it means "probability this fact is right," and it means nothing of the kind. *Mitigation:* never expose the float to the user. The MCP return uses `action_hint ∈ {answer, hedge, refuse}`, not a number. Internal modules consume the float; the user-facing surface is categorical only.

**Calibrating against the executive ledger is circular at low N.** The ledger is itself shaped by the triple — if hedge-bucket recalls lead to "user denied," that may be because the recalls were wrong *or* because the user denies anything Orion hedges on. At N in the hundreds, circularity matters more than the data. *Mitigation:* weight explicit user corrections higher than passive acceptances; treat calibration as ordinal ("hedge < answer in accuracy") rather than cardinal ("hedge is exactly 60%").

**The Anthropic introspection finding could undermine the whole project.** If model self-report is ~20% reliable at the frontier, leaning on any introspective signal is building on quicksand. The honest answer is in the layering: `content_conf` is grounded in `source_strength + recall_outcomes`, not introspection. `retrieval_conf` is mechanical (coverage/vector scores). `recency_conf` is clock arithmetic. The introspective signal (the self-probe in `orion_metacognition._self_probe_loop`) enters only as a capped-weight tiebreaker. The architecture is deliberately designed to be robust to introspection unreliability — if the 20% number falls to 0%, the recall layer still works at degraded quality.

**The honest fallback when calibration is bad** is *refusal-first by default*. Raise the answer threshold to 0.85 and accept that Orion refuses more than feels comfortable. **A brain that refuses too often is annoying; a brain that fabricates is dangerous.** Ship Move 1–4 even if Move 5 never converges — the decision tree in Part 3.3 with hand-tuned static thresholds is still strictly better than today's coverage-only gate, which has *no* refusal branch at all.

The deepest critique — the v2 consciousness memo's "building to indicators is exactly building for the test" — applies here. A system that produces well-calibrated-*looking* numbers without being internally calibrated has become trustworthy-shaped, not trustworthy. The mitigation is procedural: **the user must be able to verify calibration by reading the ledger.** Make `~/.orion/metacog/decisions.jsonl` boring and grep-able and the confidence claims become falsifiable — which is the only thing that makes them mean anything.

---

## 9. What this memo commits Orion to

- **Schema change:** three new fields on graph_memory nodes (`source_strength`, `derivation_sources`, `recall_outcomes`). Backfill default values for existing nodes.
- **One new function:** `score_recall()` in `orion_metacognition.py` returning the confidence triple and an `action_hint`.
- **One MCP contract change:** `orion_recall` returns a structured object with `best_action` and `i_dont_know`, not a markdown list. This is breaking; downstream callers must migrate.
- **Two gating changes:** `orion_deterministic` consults `score_recall` before short-circuit; `orion_will` consults it before promoting an intent.
- **One nightly job:** calibration drift check against the executive ledger, scoped to decision-shaped recalls only.
- **No claim of probabilistic calibration.** The system reports ordinal action hints (answer/hedge/refuse), never raw probabilities to the user.
- **Fail-closed default:** when in doubt, refuse. The cost of an unnecessary refusal is much lower than the cost of a confident fabrication.

---

## References

- Angelopoulos, A. N. & Bates, S. (2023). *A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification.* Foundations and Trends in ML.
- Baars, B. J. (1988). *A Cognitive Theory of Consciousness.* Cambridge University Press.
- Butlin, P., Long, R., Elmoznino, E., Bengio, Y., Birch, J., Constant, A., Deane, G., et al. (2023). *Consciousness in Artificial Intelligence: Insights from the Science of Consciousness.* arXiv:2308.08708.
- Guo, C., Pleiss, G., Sun, Y., Weinberger, K. Q. (2017). *On Calibration of Modern Neural Networks.* ICML 2017.
- Kadavath, S., Conerly, T., Askell, A., et al. (2022). *Language Models (Mostly) Know What They Know.* arXiv:2207.05221.
- Lakshminarayanan, B., Pritzel, A., Blundell, C. (2017). *Simple and Scalable Predictive Uncertainty Estimation using Deep Ensembles.* NeurIPS 2017.
- Lindsey, J., et al. (2025). *Emergent Introspective Awareness in Large Language Models.* Transformer Circuits Thread, Anthropic, October 2025. https://transformer-circuits.pub/2025/introspection/index.html
- Niculescu-Mizil, A., Caruana, R. (2005). *Predicting Good Probabilities with Supervised Learning.* ICML 2005.
- Platt, J. (1999). *Probabilistic Outputs for Support Vector Machines.* Advances in Large Margin Classifiers.
- Schaeffer, R., Miranda, B., Koyejo, S. (2023). *Are Emergent Abilities of Large Language Models a Mirage?* arXiv:2304.15004.
- Shapiro, M., Preguiça, N., Baquero, C., Zawirski, M. (2011). *Conflict-Free Replicated Data Types.* INRIA Research Report 7687 / SSS 2011.
- Tian, K., Mitchell, E., Zhou, A., Yao, H., Yang, C., Liang, P., Finn, C., Manning, C. D. (2023). *Just Ask for Calibration: Strategies for Eliciting Calibrated Confidence Scores from Language Models Fine-Tuned with Human Feedback.* EMNLP 2023.
- Vovk, V., Gammerman, A., Shafer, G. (2005). *Algorithmic Learning in a Random World.* Springer.
- Gutiérrez, B. J., et al. (2024). *HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models.* NeurIPS 2024. arXiv:2405.14831.
- Maturana, H., Varela, F. (1980). *Autopoiesis and Cognition.* D. Reidel.
- Friston, K., Stephan, K. E. (2007). *Free-energy and the brain.* Synthese 159(3).

Companion documents in this repo:
- [consciousness-research.md](consciousness-research.md) — v1 frame, three architectural moves.
- [consciousness-research-v2.md](consciousness-research-v2.md) — challenge frame; the indicator critique and the Anthropic Oct 2025 introspection reading.
- [aliveness-rubric.md](aliveness-rubric.md) — the contestation-surfacing requirement at the persona layer.
- [brain-merge-and-rejoin.md](brain-merge-and-rejoin.md) — CRDT and contestation lifecycle across hosts.
