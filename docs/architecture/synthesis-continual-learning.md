# Synthesis — Continual Learning by Combination

*Filed 2026-05-22. Invention pass, not literature review. Companion that builds **on top of**
[frontier-continual-learning.md](frontier-continual-learning.md),
[frontier-brain-as-signal-v2.md](frontier-brain-as-signal-v2.md),
[frontier-autonomous-volition.md](frontier-autonomous-volition.md),
[frontier-self-model.md](frontier-self-model.md), the [hermes-agents-study.md](hermes-agents-study.md),
[orion-unified-brain.md](orion-unified-brain.md), and the [design-law.md](design-law.md).*

Those memos each answered their own question well, then filed the hardest items as **GENUINELY
OPEN**. This document does one thing the per-domain memos structurally could not: it asks **what
becomes reachable when their findings are multiplied together**, using Orion modules that already
exist as the connective tissue. The thesis-anchor for every combination below is the same single
sentence from the continual-learning memo:

> **Learning is curation plus compilation, not accumulation.**

So the bar for "this is genuine learning, not a growing log" is fixed: a combination earns its place
here only if it makes the brain **measurably better with use** — faster, cheaper, more correct, or
more honest — **without touching a model weight, without an API key being required, and without
welding the brain to one fuel.** Everything is token-space learning (the Letta (θ, C) frame): we
improve C, never θ. Where a combination would need θ, this memo says so plainly and parks it.

A combination is recorded in four parts:
**(a)** the impossible-seeming capability, **(b)** the exact combination of findings + Orion modules,
**(c)** why it works, **(d)** a buildable sketch grounded in the real APIs
(`orion_dream._consolidate_group`, `orion_executive._log_decision` / `_action_fingerprint` /
the tiered `_request_permission` flow, `orion_metacognition.score_confidence` / `_fuel_prior` /
`score_recall`, `orion_coherence_probe.probe_fuel`, `orion_gossip.LWWMap` + `HLC`,
`orion_deterministic`'s graph short-circuit, `orion_taskspine`'s HLC step log).

---

## The shape of the insight

Each domain memo isolated one organ and found its frontier. But the organs share a substrate (NATS),
a ledger format (HLC-stamped append-only JSONL), and one governing discipline (curate→compile). That
shared spine means a *signal* produced as a by-product in one organ is **already in the right format**
to be a *training input* for another. Nothing here invents a new mechanism; every combination is a
**rewiring** that turns a by-product of one organ into food for another, closing a loop that makes
the whole brain learn where today only one part does.

The five combinations, in dependency order (each later one stands on the earlier):

| # | Combination | Unlocks | Net new mechanism |
|---|---|---|---|
| **C1** | self-model × skill-compilation | the brain compiles its **own calibration** into a skill | none — rewiring |
| **C2** | hermes self-improve loop × dream Library-Drift ratchet | a skill library that **provably cannot rot** | one counter + one cap |
| **C3** | executive ledger × deterministic-answer layer | recurring fixes become **zero-fuel fast paths** (gradient-free "training") | one promotion gate |
| **C4** | C1–C3 outputs × gossip CRDT | learning **propagates across hosts** as merge-safe playbook deltas | one envelope field |
| **C5** | cross-fuel disagreement × in-context distillation × volition Play/Ask | a **self-pricing** student/teacher/ask economy | one cost term |

Then a re-examination of every **GENUINELY OPEN** item across the four source memos: which fall to
combination, and which are genuinely, permanently open (with the honest reason).

---

## C1 — The brain compiles its own calibration as a skill

**(a) The impossible-seeming capability.** Orion's *reliability becomes a learned, improving skill*,
not a fixed heuristic. Today `score_recall` / `score_confidence` are hand-tuned heuristics; the
self-model memo's whole warning is that a system can be "trustworthy-shaped" without being
calibrated. The capability: the brain notices the *recurring shapes of question on which its own
confidence was later proven wrong*, and compiles a **per-shape calibration correction** that fires
deterministically — so the brain's sense of "how sure am I here" gets sharper with use, the same way
a procedural skill does. Self-knowledge stops being a static formula and becomes a curated,
compiling skill library *about itself*.

**(b) The exact combination.**
- *Self-model memo, Signal D + P1*: the HOT-2 ledger (`decisions.jsonl`) is the only free labelled
  validation data; introspection must earn calibration credit against it before it gets any weight.
- *Continual-learning memo, R1 (skill compilation) + R4 (metacog as gate)*: a high-success, stable
  pattern is promoted out of the fuel path into a deterministic fast path.
- *Orion modules*: `orion_metacognition` (`score_confidence`, `_fuel_prior`, the ledger), the
  `orion_dream` consolidation cycle (`_group_by_playbook_key`, `_consolidate_group`), and the
  `orion_deterministic` graph short-circuit as the **pattern for** a zero-fuel fast path.

The rewiring: today the dream compiles playbooks keyed by `(symptom, service)`. Add a **second
compile axis keyed by `(question_shape, fuel)`** whose *outcome label* is not "did the fix work" but
"was the confidence claim correct" — i.e. the dream consolidates the brain's **calibration error**,
not its task success.

**(c) Why it works.** The ledger already records, per decision, the confidence the brain asserted and
(later) the outcome. That pairing *is* a calibration dataset — it was just never read as one. The
self-model memo says calibration at personal scale is intractable as a *global* probability
(O2, genuinely open) — but it never has to be global. Grouped by question-shape × fuel, each bucket
is small, local, and ordinal ("on stale-address questions through Ollama, my 'sure' was wrong 4 of 6
times → demote 'sure' to 'hedge' for this shape"). That is exactly the curate→compile move applied to
the self-model's own output. It honors the memo's hard rule (**introspection may only *lower*
confidence, never raise it**) by making the *only* compiled correction a downgrade: a learned
calibration skill can turn `answer→hedge` or `hedge→refuse`, never the reverse. So the failure mode
of overconfidence is structurally unreachable through this path.

**(d) Buildable sketch.**
```
# in orion_dream._run_dream_cycle(), after the existing playbook consolidation:
calib_groups = group_ledger_by(decisions, key=lambda d: (shape(d.query), d.fuel))
for (shape_key, fuel), rows in calib_groups.items():
    if len(rows) < N_MIN:                      # need evidence (R1 firing-count gate)
        continue
    asserted = [r.confidence_bucket for r in rows]      # answer / hedge / refuse
    correct  = [r.outcome_matched_claim for r in rows]  # bool from later ledger close
    overconf = mean(1 for a,c in zip(asserted,correct) if a=="answer" and not c)
    if overconf >= TAU_DOWNGRADE:
        save_calibration_skill(shape_key, fuel,
            correction="cap_bucket:hedge", evidence=len(rows), drift=cusum(correct))

# score_recall() consults the compiled skill BEFORE returning (zero extra fuel):
def score_recall(query, fuel, ...):
    bucket = _heuristic_bucket(...)                 # existing path, unchanged
    skill = lookup_calibration_skill(shape(query), fuel)
    if skill: bucket = min(bucket, skill.cap_bucket)  # lowering-only, by construction
    return bucket
```
`shape(query)` is the same cheap token-bucketing `orion_metacognition._tokens` already does — no
embeddings required for v1 (Qdrant dispersion is a v2 sharpening, per self-model N1). CUSUM on the
per-bucket correctness reuses the dream's existing drift machinery so a calibration skill that stops
matching reality self-demotes. **Measurable win:** calibration error per question-shape becomes a
tracked, falling number — the self-model memo's O3 "grep the ledger and check the claims track
outcomes" becomes a *closed loop* instead of a manual audit. The brain learns its own limits, in
token space, with zero weight change.

---

## C2 — A skill library that provably cannot rot

**(a) The impossible-seeming capability.** Orion runs the hermes-agent **self-improvement loop**
(skills that edit themselves as they're used) *without* inheriting hermes's silent-death risk —
because the same loop is wrapped in the Library-Drift **ratchet** that guarantees the active set
cannot regress below the no-skill baseline. The hermes study flagged the loop as worth absorbing; the
continual-learning memo flagged Library Drift as a launch risk. **Combined, each fixes the other's
exposed flank**: hermes gives Orion the missing improvement loop; the ratchet gives the loop the
governance hermes itself lacks.

**(b) The exact combination.**
- *Hermes study, WORTH-ABSORBING #1*: close the skill self-improvement loop — increment `times_used`,
  track success/failure, raise/lower `confidence`, demote decayed skills (Orion's `learn_skill` is
  write-once today; this is the named gap).
- *Continual-learning memo, R2 (curator-grade dream)*: per-skill **contribution score**, helped/hurt
  **firing verdicts**, a **bounded active-cap** with lowest-contributor eviction, and a **birth-time**
  conflict/dup check ("the ratchet").
- *Orion modules*: `orion_memory`'s skill store (`find_matching_skill` / `learn_skill`), the dream as
  the nightly governor, the executive ledger as the verdict source.

**(c) Why it works.** Hermes's loop and the ratchet are the **two halves of one mechanism** that were
published separately. Hermes answers "how does a skill get better?" (edit it on success). The ratchet
answers "how do we stop the library getting worse?" (bound it, score it, evict the worst, refuse bad
births). Run one without the other and you get either a static store (Orion today) or an
unbounded-growth death spiral (hermes's own exposure, per the study). Run them together and you get
the only honest definition of a learning library: monotonic non-regression with continuous local
improvement. Critically, **the verdict signal is free** — the executive already logs whether a fix
worked; tagging that outcome `helped / hurt / neutral` is a one-field schema extension scored by the
same fuel that ran the fix, not a new model call.

**(d) Buildable sketch.**
```
# orion_memory: skills gain governance fields (backward-compatible additions)
skill = {..., "times_used":0, "contribution":0.0, "verdicts":[], "active":True}

def on_skill_fired(skill, outcome_row):          # called from executive close
    skill.times_used += 1
    verdict = tag_helped_hurt_neutral(outcome_row)   # cheap, same fuel that ran it
    skill.verdicts.append(verdict)
    skill.contribution = helped_minus_hurt_ratio(skill.verdicts)

# nightly, in orion_dream — the ratchet:
def curate_skills():
    active = [s for s in all_skills if s.active]
    for s in active:
        if s.times_used >= N_MIN and s.contribution < TAU_RETIRE:
            archive(s)                            # archive-not-delete, reversible
    if len(active) > ACTIVE_CAP:                  # bounded cap (Library-Drift C=50)
        for s in lowest_contributors(active, n=len(active)-ACTIVE_CAP):
            archive(s)
    publish("brain.skills.mean_contribution", mean(s.contribution for s in active))

# birth-time gate (authoring prior) — refuse harmful births at the source:
def learn_skill(name, triggers, approach, ...):
    if conflicts_with_active(triggers, approach):  # don't add a contradicting twin
        return reconcile_instead(...)              # update the incumbent, not a rival
    ...
```
**Measurable win:** `brain.skills.mean_contribution` is the single launch tripwire the
continual-learning memo asked for — a *rising or flat* line means the library is learning; a falling
line means it's rotting, caught before any end-task metric moves. The hermes loop supplies the
improvement; the ratchet supplies the proof it's safe.

---

## C3 — Recurring fixes become zero-fuel fast paths (gradient-free training)

**(a) The impossible-seeming capability.** The executive's **decision ledger becomes training data**
that the brain *compiles into deterministic code*, with no gradients and no weights — the
gradient-free analogue of fine-tuning. A fix that the brain has reasoned through a fuel N times, with
a stable action sequence and a high contribution score, stops being re-reasoned: it becomes a
**compiled procedure** the executive runs *before* any fuel call, exactly as `orion_deterministic`
already short-circuits recall. The volition memo's worry that capability is racing ahead of stopping
rules is *inverted* here: the more a procedure runs, the *less* fuel autonomy it needs, because it
graduates out of the reasoning loop entirely.

**(b) The exact combination.**
- *Continual-learning memo, R1*: compile stable high-success playbooks into deterministic procedures.
- *Self-model memo, R4 / C1*: the **compile-to-deterministic promotion is gated on calibrated
  confidence** — and now (via C1) on *learned* calibration, so the gate itself improves.
- *Autonomous-volition memo, §3.2*: the impact tier (`blast_radius × (1 − reversibility)`) decides
  whether a compiled procedure may auto-run or must still route through the executive's Ask gate.
- *Orion modules*: `orion_executive` (`_log_decision`, `_action_fingerprint`, `remedy_steps` —
  *already a plan*), `orion_deterministic` (the proven zero-fuel short-circuit pattern),
  `orion_taskspine` (durable steps for multi-step compiled procedures).

**(c) Why it works.** This is the literal restatement of the continual-learning memo's "third
transition" (curate→**compile**), but the combination is what makes it *safe to auto-run*. Compilation
alone is dangerous: a deterministic procedure that fires on the wrong situation is a runaway with no
fuel to second-guess it. Bolting on the volition memo's impact tier means the compiled fast path
inherits the design law (#3, reuse the deliberative core): a `read-only / local-msg` procedure
(impact ≤ 0.2) auto-runs at reflex speed; a `cross-host / destructive` procedure still compiles, but
its execution routes through the executive's existing tier3 OOB approval. So the brain gets faster
*and* the safety envelope is preserved — the procedure is compiled, but its *permission* is not. And
gating promotion on C1's learned calibration means a procedure is only compiled when the brain is
*calibratedly* sure it's stable, not heuristically sure. This is gradient-free training in the
strict sense: experience (ledger) → consolidated unit (playbook) → compiled fast-path (procedure),
each step token-space, each step reversible (archive-not-delete), the model never specialized.

**(d) Buildable sketch.**
```
# orion_dream compile phase (extends R1 with the C1 + volition gates):
for (sym, svc), rows in playbook_groups.items():
    pb = existing_playbook(sym, svc)
    stable = action_seq_edit_variance(rows) < EPS        # R1 stability
    calibrated = calibration_skill_ok(shape=(sym,svc))    # C1 — learned, not heuristic
    if pb.cusum_success >= TAU_HI and pb.fires >= N_MIN and stable and calibrated:
        proc = compile_procedure(rows)        # ordered tool/dispatch steps + guards
        proc.impact = max(step_impact(s) for s in proc.steps)   # volition tiering
        register_fast_path(proc)              # tried BEFORE any fuel call

# orion_executive, on a matching symptom — fast path first:
def handle(symptom, payload):
    proc = lookup_fast_path(symptom)
    if proc and guards_pass(proc, payload):
        if proc.impact <= 0.2:        return run_deterministic(proc)      # zero fuel
        else:                         return _request_permission(proc)     # tier-gated
    return _consult_model(...)        # fall back to fuel + prose playbook
```
**Measurable win:** fuel-tokens-per-recurring-fix and time-to-fix drop to ~zero on compiled cases;
that delta *is* the proof the brain learned a procedure. The decision ledger — designed for audit —
turns out to be the training corpus, read gradient-free.

---

## C4 — Learning propagates across hosts as merge-safe deltas

**(a) The impossible-seeming capability.** Everything learned in C1–C3 on FORGE — a calibration skill,
a curated skill library, a compiled fast-path — **appears on COMMAND and the Pi without a sync
protocol, a conflict, or a server**, because learned units ride the *same* CRDT gossip path the brain
already uses for memory. The unified-brain memo's observation that "an append-only HLC step-log *is
already a CRDT*, so gossip replicates it for free" generalizes: **any learned unit expressed as an
HLC-stamped, content-addressed entry replicates for free.** Orion becomes a brain that learns on one
host and *is* smarter on all of them — the network learns, not the node.

**(b) The exact combination.**
- *Unified-brain memo, §V.1*: the step-log-is-a-CRDT insight → gossip replicates in-flight state free.
- *Continual-learning C1–C3 outputs*: calibration skills, governed skills, compiled procedures —
  each is already an append-only, outcome-scored, content-addressable record.
- *Brain-as-signal-v2, §1 + §2*: ConflictSync/Rateless-IBLT anti-entropy means the *difference*
  between two hosts' learned sets transfers in bytes proportional to what changed; the per-author HLC
  high-water freshness guard means a replayed-old learned unit can't roll a host's skills backward.
- *Orion modules*: `orion_gossip.LWWMap` + `HLC` (the merge is `LWWMap.merge`, unchanged), the
  `_filtered_for_mesh` membrane gate (private units never leave), `orion_dream` as the producer.

**(c) Why it works.** The learned units from C1–C3 are *already in CRDT shape* — they have an author
(the host that learned them), a timestamp (when the dream compiled them), and content (the skill /
procedure body). They were built as append-only ledger derivatives because that's how the dream
works. So replicating them needs **no new mechanism**: put them in the `LWWMap` under a
`learned.<kind>.<id>` key and the existing `merge()` does last-writer-wins by HLC, the existing
gossip loop ships the delta, and the existing membrane gate keeps private ones home. The two
brain-as-signal findings are exactly the guards a *learning* CRDT needs that a *memory* CRDT could
mostly ignore: (1) anti-entropy keeps the cross-host learning-sync cheap enough to run continuously
rather than only at rendezvous; (2) the freshness guard is *more* important for skills than for facts,
because a semantic-rollback attack on a compiled procedure (re-injecting an old, worse version as if
newer) would silently *de-learn* a host — the v2 memo's replay-as-future attack, applied to
procedures. **Conflict resolution is principled, not arbitrary:** when two hosts learned competing
versions of the same skill, LWW-by-HLC picks the newer, but C2's contribution score is the *tiebreak
the merge should consult* — keep the higher-contribution unit, not merely the later one. That is a
~10-line `merge()` policy hook, and it's the one place this combination adds logic rather than
plumbing.

**(d) Buildable sketch.**
```
# orion_dream, after compiling a learned unit (C1/C2/C3):
gossip.put(f"learned.{kind}.{unit.id}", {
    "body": unit.body, "contribution": unit.contribution,
    "cusum": unit.drift, "author": HOST, "hlc": HLC.now(HOST).to_dict(),
})  # rides existing LWWMap → existing _publish_delta → existing merge on peers

# orion_gossip.LWWMap.merge() — contribution-aware tiebreak (the only new logic):
def merge(self, remote_entries):
    for k, remote in remote_entries.items():
        local = self.entries.get(k)
        if local and k.startswith("learned."):
            # prefer higher contribution; HLC breaks true ties (replay-safe via high-water)
            if remote["contribution"] < local["contribution"] and not _much_newer(remote, local):
                continue
        ... existing LWW-by-HLC merge ...

# brain-as-signal guards (already recommended there, now load-bearing for learning):
#  - per-author HLC high-water: reject a "learned" delta claiming an implausibly-future HLC
#  - _filtered_for_mesh: a skill marked membrane=private never enters the delta at all
```
**Measurable win:** a fast-path compiled on FORGE fires on COMMAND the next gossip round; the mesh's
aggregate `brain.skills.mean_contribution` is a *fleet* health number. Orion stops being "smart on
the host you taught it" and becomes "smart everywhere it lives" — the model-and-host-independence
thesis, extended from memory to *learning*.

---

## C5 — A self-pricing student / teacher / ask economy

**(a) The impossible-seeming capability.** Orion **decides for itself, per question, whether to answer
on cheap local fuel, escalate to an expensive fuel, or ask the human** — and the *thresholds that
govern those choices price themselves* from observed outcomes, so the brain gets cheaper over time
without ever getting less safe. The three memos each supplied one leg of this (a way to detect
uncertainty, a way to act on it cheaply, a way to ask safely); combined they form a closed economic
loop where the cost of each route is *learned*, not configured.

**(b) The exact combination.**
- *Self-model memo, Signal C / N2*: **cross-fuel disagreement** is the epistemic-uncertainty sensor —
  an *external* signal immune to any single fuel's wired-in overconfidence (the memo's strongest,
  most novel claim: no single-model assistant can do this).
- *Continual-learning memo, R5*: **in-context distillation cascade** — cheap student answers, escalate
  to teacher on divergence, accumulate resolved cases in context.
- *Autonomous-volition memo, §3.1 step 4*: the **cost-sensitive Play/Ask** gate — asking has a small
  cost so Orion won't nag, unsafe-acting has a huge cost, and the equilibrium concentrates asking on
  genuinely risky states.
- *Orion modules*: `orion_fuel` (the cascade), `orion_coherence_probe.probe_fuel` (already runs a
  prompt through an adapter — reused as the *second-fuel* probe), `orion_metacognition`
  (the gate), the executive ledger (the price-discovery data).

**(c) Why it works.** Each memo's leg is incomplete alone. Cross-fuel disagreement *measures*
uncertainty but doesn't say what to do with it. In-context distillation *acts* (student vs teacher)
but uses self-consistency (one fuel disagreeing with itself = aleatoric) as its trigger, which the
self-model memo shows is the *weaker* signal. Play/Ask *gates safely* but needs an uncertainty input.
Wire them in series and the disagreement signal feeds the distillation trigger feeds the Play/Ask
decision: **low disagreement → trust the student (cheap local fuel), accumulate the resolved case in
context; mid → escalate to teacher fuel; high disagreement OR high impact → Ask the human.** The
self-pricing comes from the volition memo's cost-sensitive equilibrium realized as *ledger-driven
threshold tuning* (the memo's own item 10): the dream watches approve/deny/ignore rates and the
fuel-cost-vs-outcome record, and nudges the disagreement thresholds — if the student's trusted answers
keep getting confirmed, lower the escalation bar (cheaper); if a Play later proved wrong, raise it
(safer). The economy prices itself toward the cheapest routing that history shows is safe. And
because the disagreement sensor is *external* to any one fuel, the loop can't be fooled by a single
overconfident model — the exact failure the self-model memo says architecturally-overconfident RLHF'd
fuels are prone to.

**(d) Buildable sketch.**
```
def route(query, impact):
    a_student = cheap_fuel.answer(query)             # local Ollama tier
    if impact <= IMPACT_LOW and self_consistent(a_student):   # cheap pre-check
        return play(a_student)                       # trust student, accumulate in context
    a_second  = probe_fuel(other_adapter, prompt=query)       # reuse coherence-probe machinery
    disagree  = semantic_disagreement(a_student, a_second)    # NOT lexical (self-model N2)
    if disagree < TAU_LOW and impact <= IMPACT_LOW:  return play(a_student)
    if disagree < TAU_MID:                            return play(teacher_fuel.answer(query))
    return ask_human(query, surface=disagreement_summary)     # executive tier3, OOB if needed

# nightly self-pricing (volition item 10, ledger-driven; validate it doesn't oscillate):
def reprice():
    for shape, rows in ledger_by_shape():
        if confirmed_student_rate(rows) > 0.9:  TAU_LOW[shape] *= 1.05   # cheaper
        if any_play_later_wrong(rows):          TAU_LOW[shape] *= 0.8    # safer, dominates
```
**Measurable win:** tokens-per-resolved-question falls as the student earns trust on stable shapes,
while the rate of "Played and was later wrong" stays bounded by the asymmetric repricing (safety
dominates cost, lexicographically, per the volition memo's corrigibility ordering). The brain gets
*cheaper with use* and *no less safe* — and it does so using a multi-fuel signal a single-model
competitor structurally cannot produce. **Honest caveat (carried from both source memos):** the
disagreement metric and the repricing loop both need tuning on real traffic and a guard against
oscillation; ship behind a conservative default (unknown → Ask) and let the ledger earn the
cheapening. Cross-fuel adds 2× calls on the gated high-stakes path only — never on the cheap student
path.

---

## Revisiting the "GENUINELY OPEN" items — which fall, which stand

The four source memos filed open items. Combination resolves several. The discipline: an item *falls*
only if the combination delivers the capability **within the thesis** (token-space, no required key,
fuel-agnostic). If the combination would need a weight change or breaks fuel-independence, the item
**stands**, and the reason is stated honestly.

### Falls to combination (reachable now or near-now)

- **Self-model O3 — "is this real metacognition or mimicry?"** → *Falls to functional, not
  metaphysical, resolution via **C1**.* The question of *genuineness* stays philosophical (see below),
  but the **operational** version — "do the confidence claims track outcomes, and does the gap
  shrink?" — becomes a closed, measurable loop the moment calibration is a compiled, drift-tracked
  skill. The brain doesn't *claim* honesty; it *demonstrates* a falling calibration-error number. The
  memo wanted "grep the ledger and check"; C1 makes the brain do that grep on itself nightly.

- **Continual-learning R2 governance gap (Library Drift) treated as merely "buildable"** → *Falls
  from a per-host build to a **fleet** guarantee via **C2 × C4**.* Each host's ratchet keeps its own
  library non-regressing; gossiping the contribution-scored units with the contribution-aware merge
  tiebreak means the *mesh* converges on the best-performing version of each skill. The open worry
  ("a self-evolving library silently dies") is closed not just locally but network-wide.

- **Self-model N2 / Signal C — cross-fuel epistemic uncertainty "the biggest unbuilt win"** →
  *Falls to a self-improving routing economy via **C5**.* It was filed as a sensor; combined with
  distillation and Play/Ask it becomes a *controller* whose thresholds learn. The sensor was the hard
  part and it already exists in `probe_fuel`; C5 is the wiring that makes it pay for itself.

- **Volition item 10 — cost-sensitive Play/Ask "needs a trainable loop Orion lacks"** → *Falls via
  **C5**'s ledger-driven repricing.* Orion doesn't have RL training, but it has the dream + ledger,
  which is a gradient-free price-discovery loop. The published RL formulation isn't required; the
  ordinal threshold-nudging adjacent to it is enough, and stays in token space.

### Stands open — and the honest reason

- **Continual-learning R7 / Letta's deferred bridge — token→weight distillation.** *Stands, and
  should.* This is the one item where the combination would have to cross the line: distilling
  consolidated memory into weights *requires producing weights*, which welds the brain to a model
  generation and breaks portability (the (θ, C) frame's whole point is improving C, not θ). The
  combinations above deliberately route around it: **C3 is the in-thesis substitute for
  weight-distillation** — it gives the *efficiency* benefit of "baking knowledge in" (zero-fuel fast
  paths, constant latency) **without** baking anything into weights. The only honest place
  weight-distillation could ever live is as a *disposable cache of the canonical brain* — generate
  synthetic training data *from* the brain, distil a throwaway local model, and treat the brain as
  still canonical so the cache can be discarded on any model swap. That is a one-paragraph design
  note, not a build, and the combinations make it *unnecessary* rather than merely deferred. Verdict:
  **permanently parked by choice**, because C3 captures its value on-thesis.

- **Volition #12 — provable corrigibility under hot-swappable fuel.** *Stands.* C5's safety dominance
  is *empirical* (ledger-priced, asymmetric) not *proven*; the published corrigibility proofs assume a
  single trained policy, and Orion's defining trait is that the policy changes mid-task on a fuel
  swap. Combination *mitigates* (the Play/Ask gate and impact tiering survive a swap because they live
  in the brain, not the fuel) but does not *prove*. This remains Orion's signature open research
  question, and no combination of current findings closes it — it needs new theory about
  corrigibility of a substrate-swapping agent.

- **Volition #13 — compounding uncertainty across a multi-host handed-off task.** *Partially falls,
  partially stands.* **C4** gives the mechanism (accumulated confidence is a ledger field that
  gossips with the task), so host B *can* inherit host A's accumulated confidence rather than
  re-deriving it. But *whether it should* — whether confidence composes correctly across a lease
  handoff or should decay on transfer — is unstudied. The plumbing falls to C4; the *semantics* stay
  open.

- **Volition #14 — goal-implantation via a watched channel.** *Stands.* No learning combination
  defends the *intent-extraction surface*; this is a membrane / input-integrity problem, not a
  continual-learning one. The brain-as-signal freshness guard (C4) defends *replay* of learned units
  but not *first-time implantation* of a malicious latent goal. Correctly out of scope here.

- **Self-model O1 (source attribution in self-report) and O2 (probabilistic calibration at scale).**
  *Stand, as the memo said.* C1 sidesteps O1 honestly (reconstruct provenance from kept records,
  don't ask the model to introspect *why*) and sidesteps O2 honestly (ordinal buckets per shape, never
  a probability). These are genuine limits of the regime, not TODOs — and the combinations respect the
  wall rather than pretending to scale it.

- **Brain-as-signal genuinely-open items** (duty-cycle vs. liveness, pure-radio first-contact trust,
  traffic-shape side-channel, freshness *denial* under an adversarial relay, "the model is never in
  the air"). *All stand.* They are physics/transport/crypto problems orthogonal to whether the brain
  *learns*; C4 rides the gossip path but inherits, not resolves, its open transport questions.

---

## The one-line frame

*The per-domain memos each found their frontier and then hit a wall they couldn't cross alone. The
walls fall not to new mechanisms but to **rewiring**: the self-model's ledger feeds the dream's
compiler so the brain learns its own calibration as a skill (C1); hermes's improvement loop and the
Library-Drift ratchet are two halves of one non-regressing library (C2); the executive's audit ledger
is gradient-free training data the dream compiles into zero-fuel fast paths (C3); every learned unit
is already a CRDT, so learning gossips across hosts for free with a contribution-aware merge (C4); and
cross-fuel disagreement, in-context distillation, and cost-sensitive Play/Ask compose into a routing
economy that prices itself cheaper without ever pricing itself less safe (C5). Each is buildable from
modules that already exist, each makes the brain measurably better with use, and none touches a model
weight — because the value of weight-distillation (efficiency without re-reasoning) is captured
on-thesis by C3. The genuinely open items that remain — provable corrigibility under fuel-swap, the
semantics of confidence across a host handoff, goal-implantation defense, source-attribution, and the
hard problem — stand because crossing them would break the thesis or the physics, and Orion's edge is
that it knows the difference.*
