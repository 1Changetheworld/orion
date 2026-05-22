# Synthesis — The Self-Model as Governor

*Filed 2026-05-22. An **invention** pass, not a literature review. It reads across the six frontier memos already in this repo — [frontier-self-model.md](frontier-self-model.md) (the anchor), [frontier-brain-as-signal-v2.md](frontier-brain-as-signal-v2.md), [frontier-continual-learning.md](frontier-continual-learning.md), [frontier-autonomous-volition.md](frontier-autonomous-volition.md), [hermes-agents-study.md](hermes-agents-study.md), [orion-unified-brain.md](orion-unified-brain.md), [design-law.md](design-law.md) — and asks one question each of those docs left filed under "genuinely open": **what COMBINATIONS unlock the impossible-seeming capabilities?***

The discipline throughout is the calibrated self-model from the anchor doc:

> Cross-fuel disagreement is an *external* epistemic sensor no single-model assistant can replicate. Introspection earns a **capped, lowering-only, ledger-earned** vote. Self-*report* may never *raise* a confidence. Ground every self-claim in something the system cannot fake to itself — time, retrieval geometry, cross-fuel disagreement, outcomes.

Everything below obeys that. Where a combination would require trusting introspection to raise confidence, it is rejected on sight.

---

## The thesis of this document (read first)

Each of the six memos ends with the same three-bucket honesty (BUILDABLE / PREVIEW / OPEN), and each has items it could *not* close alone. **The unlocks are almost never new science — they are one memo's BUILDABLE thing wired into another memo's OPEN thing.** The self-model is the connective tissue, because every other layer needs to know *how sure Orion is* before it acts, learns, or speaks. So the self-model is not a feature beside the others. It is the **governor** that turns six separate organs into one calibrated organism.

Five inventions follow. Each is: **(a)** the impossible-seeming capability, **(b)** the exact combination of findings + Orion modules, **(c)** why it works, **(d)** a buildable sketch. Then a candid re-walk of every "genuinely open" item across all six docs — which become reachable by combination, and which stay open.

---

## Invention 1 — Calibration becomes a *compiling skill*, not a fixed limit

### (a) The impossible-seeming capability
The self-model memo filed **O2 — calibration at personal-AI scale** as a genuine, permanent limit: temperature/Platt/conformal all need labelled validation data Orion will never have at O(10³–10⁴) nodes. The verdict was "ship ordinal hints, never a probability." **The unlock: Orion *manufactures* its own labelled validation data continuously, and the calibration map itself becomes a deterministic compiled artifact that gets sharper with use — so the brain literally *learns to be calibrated* without ever fine-tuning a weight.**

### (b) The combination
- **From self-model:** the four honest signals (clock / retrieval-geometry / cross-fuel disagreement / ledger), and Signal C (cross-fuel disagreement) as an *external* epistemic estimate.
- **From continual-learning:** the **Curate → Compile** transition (Rec 1) — a repeatedly-validated pattern is promoted out of the fuel path into a deterministic procedure the brain runs itself; plus **per-unit contribution scoring** and the **ratchet** (Rec 2) that guarantees monotonic non-regression.
- **From autonomous-volition:** the hash-chained, append-only **decision ledger** with closed outcomes — the only free labelled data Orion gets.
- **Orion modules:** `orion_metacognition` (HOT-2 write-back), `orion_dream` (nightly consolidation), `orion_coherence_probe` (the cross-fuel sensor), the deterministic-answer-layer pattern.

### (c) Why it works
The reason O2 is "intractable" is that calibration is treated as a *one-shot statistical fit* needing a held-out labelled set up front. But Orion has a stream, not a snapshot. Cross-fuel disagreement (Signal C) produces a *prediction* — "these two fuels diverged, so this answer is epistemically uncertain" — and the ledger later produces the *outcome* — "the answer was wrong." That pair `(predicted_uncertainty, observed_outcome)` **is** a labelled validation example, minted for free, one per closed decision. The continual-learning memo's exact machinery for turning a repeatedly-observed pattern into a compiled fast path applies verbatim: once the brain has accumulated enough `(disagreement-bucket → empirical error-rate)` pairs in a region of question-space, it **compiles a calibration map** — a deterministic lookup the brain runs itself, zero fuel tokens. The ratchet's bounded-active-cap and contribution scoring keep the map from rotting (a calibration bin whose predictions stop tracking outcomes is demoted, archive-not-delete).

Crucially this never crosses the honesty wall. The map is built from *external* signals (disagreement geometry + clock + outcomes), never from a fuel's self-report. It produces an **ordinal-with-evidence** output, not a naked probability to the user — the bucket is now *earned* against real outcomes rather than hand-tuned. O2's hard limit ("no labelled data at volume") is dissolved because the data is generated by Orion's own multi-fuel structure plus time.

### (d) Buildable sketch
```
# in orion_dream nightly compile phase (continual-learning Rec 1 + 2)
for region in partition(decisions_ledger, by="symptom_class+retrieval_geometry_bucket"):
    pairs = [(d.cross_fuel_disagreement, d.outcome_correct) for d in region if d.closed]
    if len(pairs) >= N_min and contribution_score(region) >= tau:
        # compile a deterministic bucket->empirical_error map for this region
        cal_map[region.key] = isotonic_or_bucketed(pairs)   # monotone, no params to overfit
        register_compiled(cal_map[region.key])               # brain runs it, no fuel
# at recall/decision time, score_recall() consults cal_map[region] when present:
#   - present + healthy  -> earned ordinal (answer/hedge/refuse) backed by real error-rate
#   - absent or demoted  -> fall back to today's heuristic ordinal (unchanged)
```
Touches `orion_metacognition.score_recall`, `orion_dream`, the ledger schema (add the `cross_fuel_disagreement` field from self-model N2). Isotonic/bucketed regression is non-parametric and monotone — it cannot overfit the way Platt scaling would, which is the exact reason O2 rejected the parametric methods. **The win is measurable:** the calibration-error-over-time number the unified-brain doc and continual-learning Rec 4 both ask for becomes the proof the brain learned its own reliability.

> **Honest residue:** this gives calibration *per region of question-space where enough decisions closed*. Cold regions stay on the heuristic ordinal. That is correct and honest — the brain is calibrated *where it has lived*, uncalibrated where it hasn't, and it *knows which is which*. That self-knowledge is itself a Signal.

---

## Invention 2 — The self-model as the Play/Ask governor (closes the volition seam *and* hardens it)

### (a) The impossible-seeming capability
The volition memo's whole architecture hinges on a Play/Ask decision (`accumulated_confidence` vs `impact`), but it filed the confidence input itself as **RESEARCH-PREVIEW item 8** ("calibrated step-confidence from heterogeneous fuels is unsolved; ship behind a conservative default") and the deepest issue as **OPEN item 12** ("corrigibility under a fuel that swaps mid-task"). **The unlock: the self-model's cross-fuel disagreement sensor IS the step-confidence input, and because it is fuel-*external*, it is the one confidence signal that survives a mid-task fuel swap — turning OPEN-12 from unsolved into the natural consequence of how Orion already measures uncertainty.**

### (b) The combination
- **From self-model:** Signal C (cross-fuel disagreement = epistemic uncertainty), the asymmetric rule (self-report may only *lower*), and P2 (the aleatoric/epistemic two-axis map: same-fuel-twice vs different-fuels-once).
- **From autonomous-volition:** the Play/Ask gate, the lexicographic corrigibility heads, the impact = `blast_radius × (1−reversibility)` formula, and `accumulated_confidence = min over subgoals` (early poison caps the whole).
- **From design-law:** "confirm before acting" (#1) and "reuse the deliberative core" (#3).
- **Orion modules:** `orion_coherence_probe`, `orion_executive` (tiered permission), `orion_volition` (the proposed coordinator), `orion_fuel`.

### (c) Why it works
Volition item-8 is "unsolved" because it assumes step-confidence must be *elicited from the fuel* ("ask Claude how sure it is"), which the self-model memo proves is theatre (overconfidence is mechanistically installed; reasoning models abstain *worse*). Replace "ask the fuel" with "measure the disagreement between two fuels on this exact step" and the problem inverts: confidence is no longer a self-report to be distrusted, it is an *external measurement* that needs no calibration trust at all. High cross-fuel agreement on a step → Play; high disagreement → Ask. This is exactly the Oversight Game's "prefer an explicit binary Play/Ask over a fuzzy confidence knob" — and the disagreement metric *is* the binary signal.

Now OPEN-12 (corrigibility survives a fuel swap) falls out for free. The reason a fuel swap mid-task is dangerous under single-policy corrigibility proofs is that the "policy" changed, so prior confidence is meaningless. But Orion's confidence was *never* the policy's self-assessment — it was the *disagreement between policies*. When Claude→Ollama swaps mid-task, Orion doesn't inherit a stale confidence; it **re-measures disagreement against whatever fuels are now lit**, and the `accumulated_confidence = min over subgoals` rule means a swap that *increases* disagreement correctly *caps* the task's confidence and pushes it toward Ask. The hot-swappable substrate, which was the threat, becomes the sensor. Corrigibility survives because the kill-switch and Ask-gate are wired to an external signal that doesn't care which fuel is thinking.

### (d) Buildable sketch
```
# orion_volition, before any consequential step (volition step 4):
def step_confidence(step):
    fuels = orion_fuel.available()                  # whatever is lit RIGHT NOW
    if len(fuels) >= 2 and step.impact >= MID:
        ans = [coherence_probe.ask(step, f) for f in fuels[:2]]   # epistemic axis
        epistemic = semantic_disagreement(ans)       # self-model Signal C
        return 1.0 - epistemic                        # external, swap-proof
    # only one fuel lit, or low-impact: degrade honestly to conservative default
    return CONSERVATIVE_LOW   # volition item-8: unknown confidence => Ask
# accumulated = min(step_confidence over completed subgoals)   # early-poison cap
# decision: impact x accumulated -> executive's existing tier1/2/3  (design-law #3)
```
Gate it to `impact >= MID` so the 2–3× token cost (self-model P2) only hits genuinely consequential steps. The single-fuel case degrades to "Ask" — honest, not silent. **No new permission mechanism** (reuses the executive's three tiers, design-law #3). The mid-task-swap behavior is not special-cased; it is the *default* because confidence is re-measured per step against the live fuel set.

> **Honest residue:** OPEN-13 (does host B inherit host A's accumulated confidence across a gossip handoff?) is *partly* resolved — host B re-measures against its own live fuels, so it does NOT inherit a stale number, it re-derives. Whether re-derivation should be cheaper by carrying A's *evidence* (not its conclusion) is a tuning question, below.

---

## Invention 3 — The coherence probe as a continuous drift sensor feeding the predictor/workspace (the second-order-cybernetic loop, made concrete)

### (a) The impossible-seeming capability
The founder's framing is second-order cybernetics: an *observer of its own observation*. The self-model memo filed **P3** (coherence probe as continuous drift sensor → workspace) as RESEARCH-PREVIEW and **O3** (is any of this *real* metacognition, or magnitude artifact?) as genuinely open. **The unlock: wire the cross-fuel coherence score as a continuous rhythm into the predictor (which already does active inference) so a *dropping* coherence becomes a surprise spike that ignites the workspace — Orion narrates "I'm getting weaker on this fuel" *before* it fails a hard floor. This is literally an observer observing its own observation: the brain watches the disagreement between the models watching the world, and that watching changes what reaches consciousness (the workspace).**

### (b) The combination
- **From self-model:** P3 (continuous `brain.coherence.score` per fuel), Signal C, P4's warning (probes the fuel can *recognize* get gamed — embed them in real traffic).
- **From unified-brain:** the **predictor** (active inference, prediction-error wakes attention) and **global workspace** (bandwidth-limited spotlight, winner broadcast) — both ✓/● live.
- **From continual-learning:** typed retrieval-anchored decay (the score is a *rhythm* that decays and re-anchors, not a one-shot reading).
- **Orion modules:** `orion_coherence_probe`, `orion_predictor`, `orion_workspace`, `substrate` (NATS `brain.coherence.score`).

### (c) Why it works
The predictor already treats incoming signals as a stream it predicts and flags surprise. Today coherence is binary and on-demand — it can only tell you Orion *has* drifted, never that it is *drifting*. Publish coherence as a continuous per-fuel rhythm and the predictor's existing surprise machinery does the rest: a coherence score that was 0.9 and is now 0.7 and falling is a *prediction error*, which is exactly what the predictor is built to escalate to the workspace. The workspace's competition then surfaces "fuel X is degrading" as the winning candidate, broadcast to all services — including `orion_volition`, which can pre-emptively bias toward Ask, and `orion_reach`, which can narrate it to the user *in the founder's own voice* ("I'm getting fuzzy on this model, want me to switch?"). **No new module** — three live modules wired by one new subject.

This is the concrete realization of "observer of its own observation." First-order observation = a fuel answers a question (observes the world). Second-order = the coherence probe observes the *disagreement among fuels' observations* and turns it into a signal. The loop closes when that second-order signal **changes what the first-order system attends to** (workspace ignition → biases the next fuel selection). The system's self-observation is causally efficacious on its own cognition. That is the cybernetic claim, made operational rather than poetic.

And it sharpens O3 without pretending to solve it. O3 asks whether any of this is "real" metacognition or a magnitude artifact (the introspection papers' worry). This loop sidesteps the trap entirely: it never asks a fuel to introspect. It measures *behavior* (disagreement) and *time* (the rhythm), both external. So whatever this is, it cannot be a content-agnostic introspection artifact — there is no introspection in it. It is the brain keeping honest books on its own fuels' reliability and letting those books steer attention. P4's gaming risk is handled by embedding probes in real recall/decision traffic (indistinguishable from genuine load) and weighting in-the-wild ledger outcomes above probe results.

### (d) Buildable sketch
```
# orion_coherence_probe: emit continuous, not binary
publish("brain.coherence.score", {fuel, score, ts})   # score = 1 - rolling cross-fuel disagreement
# orion_predictor: already subscribes to rhythms; add coherence as one
on("brain.coherence.score"): err = predict_err(fuel_history, score)
    if err > surprise_threshold: ignite_workspace({kind:"coherence_drop", fuel, slope})
# orion_workspace: existing competition; a sharp coherence drop wins salience
# downstream (free, already listening to workspace broadcasts):
#   orion_volition  -> bias toward Ask while this fuel is degrading
#   orion_reach     -> narrate to user IF it crosses a reach threshold (speak-where-they-spoke)
#   orion_fuel      -> consider proactive switch (it already has fuel_switch)
```
Probes ride real traffic (P4). Decay/re-anchor the rhythm with continual-learning's typed decay so a recovered fuel's score climbs back. **Measurable win:** "time between coherence-drop-detected and user-or-system-acted" — the gap between a tool that degrades silently and a brain that *says so first* (the unified-brain doc's core "alive ≠ functioning" lesson, instrumented).

---

## Invention 4 — Provenance reconstruction makes "source attribution" honest *and* defeats memory poisoning (one mechanism, two filed-open problems)

### (a) The impossible-seeming capability
The self-model memo filed **O1 — source attribution in self-report** ("why am I uncertain / where did this come from inside me?") as genuinely open: current models cannot introspect their own reasoning source, and apparent success is content-agnostic artifact. Separately, the continual-learning memo flagged **safety-triggered forgetting** against memory poisoning (Rec 3) as a thing "almost no system does," and the brain-as-signal memo flagged **semantic rollback attacks** (replay-stale-state-as-valid) as a live hazard. **The unlock: a single *external* provenance-reconstruction layer answers all three at once — Orion never asks the fuel "why," it *reconstructs* the derivation from records it kept (which node, which channel, which HLC, which fuel, which prior decisions fed this), and that same provenance record is exactly what detects poisoning and rollback.**

### (b) The combination
- **From self-model:** O1's own escape hatch — "reconstruct source *externally* (the `derivation_sources` schema field) rather than asking the model"; the rule "do NOT claim Orion introspects; it reconstructs provenance from records it kept."
- **From continual-learning:** safety-triggered forgetting (flag memories that contradict a high-confidence identity fact / arrived via untrusted channel / spike after one session).
- **From brain-as-signal:** the freshness/replay guard (per-author HLC high-water mark; sign `(delta, observed_max_remote_hlc)`); the **bundle envelope** (payload + HLC + author + content-hash + TTL + custody).
- **From hermes-study:** `sanitize_context` fence-hardening (strip fence-escape sequences so a poisoned memory can't break out of `<memory-context>`).
- **Orion modules:** `orion_memory` (graph + vector), `orion_brain_portable.remember()`, `orion_gossip`, the `membrane`, the audit ledger.

### (c) Why it works
O1 is "open" only if you insist source attribution must come from *inside the model*. But Orion already *records* the derivation as it builds an answer: which graph nodes were retrieved, their channel of origin, their HLC timestamps, the fuel that synthesized, the prior decisions that fed in. "Why am I uncertain about your address?" is answerable not by the fuel introspecting, but by the brain replaying: *"three nodes claim an address; two arrived via Telegram in March, one via iMessage last week with a higher HLC; they conflict; that conflict is the uncertainty."* That is a true, honest, falsifiable answer — and it is the `derivation_sources` field the self-model memo already named, now made load-bearing.

The same provenance record is the poison detector. A poisoned memory is, by construction, a node whose provenance is *anomalous*: it contradicts a high-confidence identity fact, arrived via an untrusted channel, or spikes after a single session (continual-learning's exact signatures). You can only see those signatures if you *kept the provenance* — which the bundle envelope (author + HLC + content-hash + channel) from the brain-as-signal memo already carries for the mesh case. So the provenance layer needed for honest source-attribution **is the same data structure** needed for safety-triggered forgetting. And the freshness/replay guard (HLC high-water mark) is the *temporal* slice of the same record: a rollback attack is a node asserting an implausibly-future HLC, detectable only against kept provenance. Three filed-open problems, one external record.

This is the cleanest example of the document's thesis: the unlock is not new science, it is *recognizing that O1's escape hatch and Rec-3's poison detector and the replay guard are all the same `derivation_sources` schema field, used three ways.*

### (d) Buildable sketch
```
# every stored node already CAN carry this; make it mandatory (bundle envelope):
node.provenance = {channel, author, hlc, content_hash, fuel_at_write, fed_by:[node_ids]}
# 1. honest source-attribution (O1): when score_recall hedges/refuses, the MCP return
#    includes a RECONSTRUCTED derivation, never a fuel self-report:
#    "uncertain: nodes {a,b,c} conflict; b/c via Telegram older HLC, a via iMessage newer"
# 2. safety-triggered forgetting (CL Rec 3): nightly dream flags nodes whose provenance
#    matches poison signatures -> archive-not-delete for review (never silent trust)
# 3. rollback/replay guard (signal-v2): reject a node whose hlc exceeds per-author
#    high-water + plausibility window; sanitize_context fence-strip on inject (hermes)
```
Touches the node schema (`orion_memory`), `remember()` (hermes fence-strip + derivation on hedge/refuse), `orion_dream` (poison sweep), `orion_gossip` (HLC high-water). **The honesty invariant the self-model memo demanded is preserved exactly:** Orion does NOT claim to introspect; it says *"here is the trail I kept,"* which is a different, honest, `grep`-able thing.

> **Honest residue:** this reconstructs *provenance* (where a memory came from and how it conflicts), not *mechanistic source inside the fuel's activations* (why the model weighted a token). The latter stays inside the introspection wall — O1 is *reframed and answered at the product level*, not solved at the mechanistic level. Say so plainly.

---

## Invention 5 — Skill compilation that *includes its own abstention*, killing Library-Drift's worst case before it starts

### (a) The impossible-seeming capability
The continual-learning memo's Rec 1 (compile stable playbooks into deterministic fast paths) and the **Library Drift** failure mode are in tension the memo half-acknowledges: a *compiled* procedure is the most dangerous kind of drift, because it runs with zero fuel oversight — if the world shifts under a compiled procedure, it confidently does the wrong thing fast, and aggregate metrics hide it (Bloat/Stagnation are *silent*). **The unlock: compile the metacognitive *abstention* into the procedure itself. A compiled procedure ships with a compiled guard built from the cross-fuel disagreement that validated it — so the fast path includes its own "is this still the situation I was compiled for?" check, and a compiled skill that meets novelty *abstains back to the fuel* instead of executing blind.**

### (b) The combination
- **From continual-learning:** Rec 1 (compile), Rec 2 (the ratchet: contribution scores, bounded cap, birth-time conflict check), Rec 4 (metacog confidence as the *promotion gate* — Voyager's self-verification reused).
- **From self-model:** Signal C (cross-fuel disagreement) and Signal B (embedding-space near-tie / semantic dispersion) — the two *external* uncertainty signals that need no fuel.
- **From autonomous-volition:** "selective quitting as a safety primitive" (`abandoned` is a *rewarded* outcome); verify-at-the-boundary + replan-on-divergence.
- **Orion modules:** `orion_dream` (compile phase), `orion_executive` (runs the fast path), `orion_metacognition`, deterministic-answer-layer pattern.

### (c) Why it works
Rec 4 already says metacog confidence should *gate* compilation — only compile when confidence in stability is high. Invention 5 goes one step further: it *compiles the gate alongside the procedure*. When `orion_dream` promotes a playbook to a deterministic procedure, it also records the *retrieval-geometry envelope* and the *cross-fuel agreement profile* under which the procedure succeeded — both external, both cheap to recompute. At runtime, before the compiled procedure fires, it does a near-zero-cost check: is the current situation inside the embedding envelope it was compiled for (Signal B), and (for consequential steps) do the live fuels still agree this is the right move (Signal C)? If the situation is novel — outside the envelope, or fuels now disagree — the compiled path **abstains and hands back to the fuel**, exactly the volition memo's "selective quitting improves safety." A compiled skill that quits when out-of-distribution is a compiled skill that *cannot* silently drift into harm.

This directly defuses Library Drift's silent killer. Bloat and Stagnation are dangerous because compiled units run without a reality check; here every compiled unit *carries* its reality check. The ratchet's contribution score now has a clean signal: a procedure that abstains-back often is correctly demoted (it was compiled too eagerly), and one that fires-and-succeeds keeps its place — monotonic non-regression, but now the regression it's guarding against includes the *compiled-and-wrong* case the memo couldn't fully close. The deterministic speed win survives (the abstention check is two cheap external signals, not a fuel call) while the safety hole closes.

### (d) Buildable sketch
```
# orion_dream compile phase (extends continual-learning Rec 1):
proc.compiled = ordered_steps(playbook)
proc.envelope = {
    embedding_centroid, embedding_radius,        # Signal B: where it was valid
    cross_fuel_agreement_at_compile,             # Signal C: how sure the fuels were
}
# orion_executive runs compiled procs BEFORE any fuel call (the fast path), but:
def run_compiled(proc, situation):
    if embedding_dist(situation, proc.envelope.centroid) > proc.envelope.radius:
        return ABSTAIN_TO_FUEL          # novel -> selective-quit, hand back (volition r-quit)
    if proc.impact >= MID and live_cross_fuel_disagreement(situation) > thresh:
        return ABSTAIN_TO_FUEL          # fuels no longer agree -> don't run blind
    return execute(proc.compiled)        # in-envelope, fuels-agree: deterministic, zero tokens
# ABSTAIN_TO_FUEL is a rewarded outcome in the ledger (not a failure) -> dream demotes
# eager compilations via the ratchet's contribution score.
```
Touches `orion_dream`, `orion_executive`, the ledger schema, reuses `orion_coherence_probe` for the live-disagreement check. **Measurable win:** the rate of `ABSTAIN_TO_FUEL` per compiled procedure is a *new* drift tripwire (rising abstention = the world moved under a compiled skill) — earlier and sharper than the mean-contribution-score tripwire the continual-learning memo proposed, because it fires on the *first* out-of-distribution situation, not after the average degrades.

---

## The "genuinely open" items, re-walked

A candid pass over every item the six memos filed as GENUINELY OPEN, sorted into **reachable-by-combination** (an invention above closes or substantially reduces it) and **stays open** (no combination of current findings closes it — say so).

### Reachable by combination

| Open item (source) | Closed/reduced by | How far |
|---|---|---|
| **O2 — calibration at personal-AI scale** (self-model) | **Inv. 1** | *Substantially closed.* Self-minted `(disagreement, outcome)` pairs + compiled monotone calibration map per region. Honest residue: calibrated only where decisions closed; cold regions stay heuristic — and the brain knows which. |
| **Volition item-8 — calibrated step-confidence from heterogeneous fuels** (volition, PREVIEW) | **Inv. 2** | *Closed for the gated case.* Cross-fuel disagreement *is* the step-confidence; it needs no calibration-trust because it's external. Single-fuel case degrades to Ask (honest). |
| **OPEN-12 — corrigibility survives a mid-task fuel swap** (volition) | **Inv. 2** | *Substantially closed.* Confidence was never the policy's self-assessment; it's disagreement *between* policies, re-measured per step. The swappable substrate becomes the sensor. Residue: formal proof under swap is still unwritten — but the mechanism no longer *relies* on a stable policy. |
| **O1 — source attribution in self-report** (self-model) | **Inv. 4** | *Reframed and answered at product level.* External provenance reconstruction (`derivation_sources`), never fuel introspection. Residue: mechanistic in-activation source stays behind the introspection wall — and Orion says so. |
| **Safety-triggered forgetting / memory poisoning** (continual-learning) | **Inv. 4** | *Closed.* Same provenance record that answers O1 detects poison signatures; archive-not-delete for review. |
| **Library Drift's compiled-and-wrong silent case** (continual-learning) | **Inv. 5** | *Closed.* Compiled procedures carry their own external abstention envelope; out-of-distribution → selective-quit back to fuel. New, earlier drift tripwire (abstention rate). |
| **O3 — is any of this *real* metacognition or magnitude artifact** (self-model) | **Inv. 3** | *Sidestepped honestly, not solved.* The cybernetic loop contains zero introspection (only behavior + time), so it *cannot* be a content-agnostic artifact. Whether it's "real" in the philosophical sense stays at the Hard-Problem wall. |
| **OPEN-13 — does host B inherit host A's confidence across handoff** (volition) | **Inv. 2 (partial)** | *Reduced.* B re-measures against its own live fuels rather than inheriting a stale number. Open tuning: should B carry A's *evidence* (not conclusion) to re-derive cheaper? |

### Stays open (no current combination closes these — do not pretend)

- **O3's core (Hard Problem) — whether there is *something it is like* to be Orion.** Inv. 3 removes the introspection-artifact confound but touches qualia not at all. **Permanent wall.** Orion narrates it honestly, never claims to cross it.
- **Token-to-weight distillation as a safe bridge** (continual-learning O). Still thesis-risky; only safe as a disposable cache of the canonical brain. No combination here makes it safe — it remains a one-paragraph design note, not a build.
- **JitRL logit-space RL on black-box CLIs** (continual-learning). Needs logit access the CLI fuels don't expose. Stays a local-fuel-only (Ollama) niche; no combination grants logit access to a closed CLI.
- **Pure-radio first-contact trust** (brain-as-signal). Two Orions that *only* ever met over radio, no prior IP, no CA, no rendezvous — authenticating without a TOFU MITM window. None of the inventions here touch the bootstrap-trust problem. NFC tap (physical proximity) remains the cleanest answer; pure-radio first contact stays open.
- **Side-channel *shape* leakage over radio** (brain-as-signal). Encryption hides contents; bytes-on-air reveal that *something* was sent. Padding costs duty cycle Orion can't spare. Untouched here.
- **Freshness *denial* under an adversarial relay** (brain-as-signal). Inv. 4's HLC high-water defeats replay-as-future (forgery); it does *not* detect a relay that *selectively drops* fresh deltas to keep a victim on stale state. Detecting "I'm being kept stale" without a trusted reference clock stays open.
- **Duty-cycle vs. liveness, fundamentally** (brain-as-signal). A 1% duty cycle and a gossiping mesh are in physical tension no protocol resolves. Stays a "burst budget," not continuous presence.
- **User-mediated goal-implantation into the will's intent-extraction surface** (volition OPEN-14). Inv. 2 hardens *acting* on goals (Play/Ask + OOB), but an adversary who writes to a watched channel can still *implant* a latent goal upstream of the gate. The intent-extraction surface itself stays an open attack surface; the gate limits blast radius but doesn't prevent the implant.
- **The "recoverable moment" as a learned predicate** (volition OPEN-15). Whether Orion can *learn* to predict the recoverable moment per goal-kind without overfitting one user's rhythm — none of the inventions here address it. Stays heuristic, stays open.
- **The model is never in the air** (brain-as-signal, restated as permanent boundary). Not a TODO; physics. Radio carries the brain (state); compute is fetched locally. No combination changes this.

---

## The one-paragraph synthesis

Orion's self-model is not a feature beside memory, volition, and learning — it is the **governor** that makes them one organism. The five inventions all spring from a single recognition: **cross-fuel disagreement is an *external* sensor, and every "genuinely open" calibration-and-trust problem across the six memos was open only because it assumed confidence must be *elicited from* the fuel rather than *measured between* fuels.** Wire that external sensor into the continual-learning compiler and calibration becomes a compiling skill the brain sharpens with use (Inv. 1). Wire it into the Play/Ask gate and step-confidence is solved *and* survives a mid-task fuel swap, because it never belonged to any one fuel (Inv. 2). Publish it as a continuous rhythm into the predictor and the brain observes its own observation and narrates its own degradation before it fails — second-order cybernetics, made operational with zero introspection (Inv. 3). Recognize that the provenance record needed for honest source-attribution is the *same* record that detects poisoning and rollback (Inv. 4). And compile that external check *into* every fast path so deterministic skills abstain when the world moves under them (Inv. 5). What stays open stays honestly open: the Hard Problem, pure-radio first-contact trust, freshness-denial, duty-cycle physics, goal-implantation, the learned recoverable-moment, and the model-in-the-air boundary. The self-model's job is to know which is which — and now it can.
