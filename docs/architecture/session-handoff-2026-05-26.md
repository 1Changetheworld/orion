# Orion — Comprehensive Session Handoff

**Date range:** 2026-05-22 → 2026-05-26
**This terminal's role:** Terminal 1 / overseer / integration lane
**Author of intent:** James England (founder)
**Production master at handoff:** `299a3d6` (after the em-dash install.ps1 fix)
**Total commits this session:** ~40 across 5 terminals

This document is the durable record of everything covered in this terminal session. It exists so the next terminal can pick up where this one left off — knowing what was built, what was tried, what was rejected, what's still open, and what the honest assessment of the brain looks like today.

Written deliberately long. Skim the table of contents; read the section that's relevant when you need it.

---

## Table of contents

1. Session framing & where we started
2. Production state at handoff
3. All commits this session, annotated
4. Parallel-terminal contributions (T2–T5)
5. Architecture today — what the brain is
6. Bugs found, root-caused, and fixed
7. Bugs found and NOT fixed (open work)
8. Key debates + decisions (with tradeoffs named)
9. The deep honest assessment
10. What to pick up next
11. Build cadence + commit discipline lessons learned

---

## 1. Session framing & where we started

This terminal opened during a context-overflow handoff from the prior terminal (`orionbuild1`). The prior terminal ended mid-investigation of how to wire mesh-restore outcomes back into the governor's ledger — the kickoff of "Build #1 — calibration as a learned skill." No commit was produced there; the work was queued.

This terminal picked up that thread and ran it forward. Along the way, four parallel terminals (T2–T5) were spawned for the simulation, volition deepening, cognition deepening, and self-model/boundary deepening lanes. This terminal acted as the **overseer + integration lane**: doing its own structural work, but also triaging parallel-terminal collisions, auditing cohesion, and pushing unification.

Network context (per global CLAUDE.md):
- **COMMAND** (Mac mini, `10.0.0.190`, Tailscale `command-ts` / `100.109.99.21`) — the primary brain host; runs the full 30+ launchd service stack 24/7.
- **Alien / FORGE** (this Windows machine, `10.0.0.88`) — the founder's development machine; runs the dev repo at `C:\Users\jeng1\Desktop\orion\orion-repo`.
- **DESKTOP-CO17GKE** (Windows 11 VM, `192.168.106.134`, Tailscale `desktop-co17gke`) — the fresh-install test target.

---

## 2. Production state at handoff

```
origin/master       299a3d6      (em-dash install.ps1 fix)
COMMAND (~/orion-code)         in sync with origin
USB reference (/Volumes/VAULT/orion-backup-...)  in sync with origin
VM (~/orion on DESKTOP-CO17GKE) in sync with origin (last pulled)

Live services on COMMAND (verified via launchctl list):
  com.orion.affect              (added this session, code level — not yet auto-running)
  com.orion.autofix
  com.orion.canary
  com.orion.channel-probe
  com.orion.chronos
  com.orion.claustrum
  com.orion.deterministic
  com.orion.dmn
  com.orion.dream               (now hosts skill curation + sim + lateral diffusion + procedure compile)
  com.orion.executive           (now reads compiled procedures via fast-path-first)
  com.orion.fuel-switch
  com.orion.gossip              (now carries skills + calibration aggregates cross-host)
  com.orion.imessage            (split-brain — see Bug §6.K)
  com.orion.imessage-outbound   (recipient guard + 30s timeout + retry-on-timeout, see §6.M)
  com.orion.immune
  com.orion.intelligence        (NEW this session — composite + heartbeat)
  com.orion.intent
  com.orion.lastcontact
  com.orion.learning-sync       (NEW this session — applies remote learned units)
  com.orion.litellm
  com.orion.metacog             (Phase-2 governor now learns calibration from outcomes)
  com.orion.nats
  com.orion.predictor           (T4 — active inference content model)
  com.orion.reach               (now reads affect.bias_for for delay multiplier)
  com.orion.self-heal
  com.orion.task-gossip
  com.orion.team-sync
  com.orion.trader-* (8 trader units — not Orion-brain, separate trading bot)
  com.orion.updater
  com.orion.will                (Build #3 promotion + Build #4 deepening + affect bias)
  com.orion.workspace           (T4 — surprise-broadcast)

Auth state on Alien (preserved through all clean cycles):
  ~/.claude/.credentials.json    471 bytes
  ~/.codex/auth.json            4722 bytes
  ~/.gemini/oauth_creds.json    1763 bytes
```

---

## 3. All commits this session, annotated

Ordered chronologically. Author of every commit: James England (via the various terminal sessions). Co-authored-by Claude Opus 4.7.

### 3.A — Builds #1–#3: the next-3 roadmap

`2a22e68` **feat(metacog): calibration as a learned skill — close the Phase-2 loop**
The Phase-2 cross-fuel governor (shipped earlier in `0927b4d` / `061eff5`) consulted a ledger but never genuinely learned from outcomes. Three defects:
- `"success"` vs `"succeeded"` string mismatch — the ledger-learning branch was dead code.
- `mesh_recovery` consulted the governor but never recorded what the restore actually did.
- `_ledger_cache` was only loaded by the NATS daemon's `main()`; cross-process callers (mesh_recovery) read an empty cache.

Fix: `record_outcome()` direct-write API, `_ensure_ledger_loaded()` lazy-load, fixed the bug, and a recency tie-break in `_similar_rows` so a fixed device can earn `auto` back instead of being pinned by stale failures. Verified: `auto(0.80) → ask(0.48)` after failures → `auto(0.80)` again after recovery, durable across a process restart.

`c7a19d4` **feat(skills): the Library-Drift ratchet — a skill library that cannot rot**
Hermes self-improvement loop closed. `orion_memory`'s skills gained `times_used`, `verdicts`, `contribution`, `active` fields. New `on_skill_fired(name, verdict)` updates them. `learn_skill` got a birth-time twin gate (refuses Jaccard ≥ 0.7 trigger overlap). New `orion_skill_curator.py` runs nightly inside the dream cycle, applies the ratchet: retire low contributors past N_MIN firings, bound active set at `ACTIVE_CAP`, evict lowest contributors over cap, publish `brain.skills.mean_contribution` (the launch tripwire from `synthesis-continual-learning.md` §C2). Archive-not-delete; reversible.

`5d81a9b` **feat(will): will→taskspine promotion + calibration closure**
When `_select_and_initiate` fires a goal, `_promote_to_spine(goal)` consults the Phase-2 governor and (if `auto`) creates a durable taskspine task. `_close_spine_outcome(goal, outcome)` runs from `_on_user_inbound`: closes the spine task AND feeds the outcome to `record_outcome` under the same `(action, symptom)` keys the governor saw. The will EARNS calibration on goal kinds — chronic-deferral kinds flip `auto → ask`. Verified end-to-end: 5 deferreds on `lapsed` kind → governor returns `ask (0.48, ledger 0/5 ok)` → no spine promotion → no message sent. Corrigibility lives in the brain, not the fuel.

### 3.B — C4 cross-host learning

`fb6ea72` **feat(gossip): C4 — cross-host learning gossip (skills first)**
Every skill mutation (`learn_skill`, `on_skill_fired`, `archive_skill`, `restore_skill`) publishes `brain.learned.skill`. `orion_gossip` subscribes, puts entries under `learned.skill.<fname>` in the LWWMap. `_on_remote_heartbeat` snapshots `learned.skill.*` before/after merge and emits `brain.learned.skill.from_peer` for newly-adopted ones. New `orion_learning_sync.py` subscribes to `.from_peer` and writes remote skills to local disk — idempotent by content_hash, contribution-aware tiebreak (a remote write with lower contribution is rejected, exactly the rotting the ratchet exists to prevent). The mesh learns, not the node.

`5f02b73` **feat(gossip): C4 follow-up — cross-host calibration aggregates**
Raw calibration rows are too high-volume for the LWWMap (one key per decision = thousands over time). Per-symptom aggregates (count, succeeded, failed, mean_outcome, content_hash) are bounded by distinct symptoms (~dozens). New `orion_metacognition.aggregate_local_ledger()` + `publish_aggregates()`. Dream calls publish nightly. Gossip mirrors the skill diff-emit pattern for `learned.calibration.*` keys. `learning_sync.apply_remote_calibration` writes per-peer files at `~/.orion/metacog/remote_<host>.json`. **`governor()` extended:** remote aggregates weighted 0.5× local (cross-host generalization is weaker evidence). Verified: a host with no local history at 0.80 → drops to 0.72 after a peer aggregate at 75% success at half-weight. Multi-peer evidence sums honestly without bloating the manifest.

`321a2a1` **fix(gossip): restore _on_learned_calibration + _emit_remote_calibration_adoptions**
Production bug caught when COMMAND's `com.orion.gossip` was crashing on every restart since `5f02b73`. Unit tests passed because they tested `governor + record_outcome` paths only, never the daemon's `main()` subscription wiring. Production caught it: NameError because the subscribe call referenced functions that had been lost in a linter rewrite. Cross-host learning was broken for hours. Restored both functions with anchored comments so the next linter pass keeps the pair together.

### 3.C — Affect layer (real functional emotion)

`2497b73` **feat(affect): real functional emotion as an architectural component**
NOT simulation. NOT phenomenal feeling (consciousness sidestepped). Russell's circumplex + self-model confidence + attachment dimension, derived from real upstream signals: valence (will outcomes), arousal (predictor surprise), confidence (governor EMA), care (per-entity engagement). Persistent state at `~/.orion/affect/state.json` + `per_entity.json` + `history.jsonl`. Half-life decay: 24h global, 30d per-entity. `bias_for(action_kind, entity_id)` returns the adjustments other modules consult. `record_outcome` / `on_predictor_surprise` / `on_governor_decision` write paths. Verified: cold = neutral; 10 deferrals → valence sours; 6 successes → confidence rises.

`0102f2c` **feat(will): wire affect into firing threshold — Gap 1 of unification**
`will._select_and_initiate` reads `bias_for("will_firing").utility_threshold_delta` and adds it to the threshold gate. Negative valence + low care raises the bar (Orion ACTUALLY quieter when sad). High arousal raises it (don't initiate when surprised — process first). Verified deltas: cold = 0; 10 deferrals = +0.048 (quieter); 15 engagements = −0.105 (more present). Missing affect → 0 delta → unchanged behavior. Conservative additive; governor stays supreme over safety gates.

`8b17543` **feat(reach,exec): wire affect bias_for — close Gap 1b + 1c of unification**
`reach` (`take_due` cooldown) scales `PER_CHANNEL_COOLDOWN_SEC` by `bias_for("reach_timing").delay_multiplier` clamped to [0.25, 3.0]. `executive` (`_build_diagnostic_prompt`) injects an affect block (valence/arousal/confidence/care + conservatism cue) into the fault-tree prompt so the fueling model factors mood. **Affect now wires into 3 of 3 planned consumers** — `bias_for` went from 0 callers to 3.

### 3.D — Intelligence measurement layer

`d8c7c4a` **feat(intelligence): the measurement layer — one composite the brain can graph**
Closes the gap the synthesis memos all gestured at: "we can't currently prove Orion is getting smarter." Composes existing tripwires (no new instrumentation) + walks durable state files. Reads ledger + remote aggregates + skills + procedures. Publishes `brain.intelligence.heartbeat` every 60s. Composite `[0,1]`: 40% calibration accuracy + 35% skill contribution + 25% procedure success rate. Each defaults to 0.5 (neutral) on low evidence — fresh brain never spuriously high. `~/.orion/intelligence/heartbeat.jsonl` is the trajectory record. First COMMAND composite published: **0.6875**.

`9d779aa` **feat(intel): human snapshot + dispatch 'orion_status' command**
Three-way introspection: `python orion_intelligence.py --human` (formatted), `--once` (JSON), or `python -c "import orion_dispatch; print(orion_dispatch.orion_status())"`. Renders the composite as a Unicode progress bar with the four sub-blocks. None-values render as `—` so an empty-evidence brain reads honestly rather than as fake zeros.

`6e4e2f4` **fix(memory): SKILLS_DIR respects ORION_BRAIN_DIR (alignment fix)**
The alignment opportunity flagged in `d8c7c4a`'s commit message. Before: `orion_memory.SKILLS_DIR` hardcoded `~/.orion/brain/skills`; the rest of the brain respected `ORION_BRAIN_DIR`. Tempdir tests diverged silently. Now aligned; default behavior preserved when `ORION_BRAIN_DIR` is unset.

### 3.E — C3 compiled procedures + executive fast-path

`2f93d36` **feat(procedures): C3 foundation — compiled procedure store + safety envelope**
The C3 spec from `synthesis-continual-learning.md`: "recurring fixes become zero-fuel fast paths." New `orion_compiled_procedures.py` is the store, not yet the compiler. `register_procedure / lookup_fast_path / execute / archive_procedure / restore_procedure`. **Two load-bearing safety guards inside the module**: (1) impact ceiling — anything above `IMPACT_AUTO_CEILING` (0.2) refuses auto-run; (2) calibration floor — `execute()` refuses if `governor_conf < procedure.conf_floor`. Step vocabulary deliberately small: `dispatch`, `publish` (shell forbidden). Archive-not-delete contract.

> **Note**: this commit also accidentally bundled in Terminal 3's Build #4 (`orion_will.py +556`, `tests/test_will_b4.py +385`) due to a shared-git-index race in the parallel terminals. Code intact; commit metadata mis-attributes T3's volition deepening to the procedures-foundation commit.

`0b7b048` **feat(executive): C3 fast-path-first — zero-fuel pre-check before consult**
`orion_executive._on_health_alert` consults `lookup_fast_path(symptom_class)` BEFORE calling `_consult_model`. If a procedure exists AND its two safety guards pass (impact + governor conf ≥ floor), the executive runs it deterministically, logs `phase=compiled_fast_path`, publishes `via=compiled_procedure`, returns — skipping the fuel call. Zero behavior change today (no procedures registered yet); full acceleration the moment any are.

`0b8614f` **feat(dream): wire compile-to-procedure — Gap 2 of unification**
Dream-side compiler. After playbook consolidation, `_compile_to_procedures()` walks the playbook index. For each `(symptom, service)` playbook with `total_fires >= 5` AND `success_rate >= 0.75`, registers a procedure with `impact=0.05` and `conf_floor=earned_rate` (clamped [0.70, 0.95]). **Honest scope**: the step body is a `publish` marker (`brain.dream.playbook_referenced`), not a real deterministic action — the wiring is closed; the body grows via a follow-up commit when real action extraction from prose playbooks is built. Verified 5/5: high-CUSUM compiled; low-CUSUM skipped honestly; execute refused below floor; execute ran above floor.

### 3.F — Install path unification (the headline of late-session)

`b97b789` **fix(setup): auto-wire MCP into AI CLIs at install end — fixes VM test blocker**
THE Windows-VM blocker. `setup.py` ran the wizard, wrote configs, wrote context files, exited — **never invoked `orion_mcp_server.py --setup`**. So users following the README's `pip install + python setup.py` path got no MCP wiring. The CLIs went into honest-degraded mode. This commit adds an MCP-wiring step at the end of `run_setup()`: invokes `orion_mcp_server.py --setup` via subprocess with `sys.executable` (so the resolved Python path is whichever Python ran the install). The wiring uses `Path(__file__).resolve()` for the server path. After this commit, the install actually wires the brain into Claude/Codex/Gemini/VS Code.

`089f8c9` **feat(install): Phase 1 — setup.py chains to proto-Orion (unification)**
The audit found two officially-published install paths producing different experiences: `install.ps1`/`install.sh` did the full chain; `python setup.py` alone did half. `setup.py` now always chains to `orion_setup_chat.py` at the end via `_chain_to_proto_orion()` using subprocess. README updated to publish ONE canonical path per OS (`install.sh` / `install.ps1`); the `python setup.py` shortcut removed from docs.

`1bf78ce` **feat(setup-chat): Phase 2 — seed_brain tags align with AGENTS.md queries**
`AGENTS.md` uses specific recall queries (`orion_recall("preferred form of address")`, `orion_recall("preferred name")`, `orion_recall("birthday")`). Previously the tags `["address", "form-of-address", ...]` would *probably* match via fuzzy logic, but graph recall isn't deterministic across backends. Tags now include the EXACT query strings + natural-language alternates (`"how old are you"`, `"when were you born"`, `"what to call me"`). Recall is deterministic. Verified 4/4 recall queries hit cleanly.

`077a93a` **feat(persona): Phase 3 — synapse-speed identity (no tool call needed)**
The headline of the install unification. NEW `orion_persona_render.py`: `gather_identity()` reads identity-shaped graph nodes; `render_persona()` produces a system-prompt-shaped persona block; `write_persona_files()` atomic-writes it to `~/CLAUDE.md`, `~/AGENTS.md`, `~/GEMINI.md`, `~/ORION-CONTEXT.md`. **Identity becomes perception, not a tool call.** The model sees `Name: James / Prefers: sir / Working on: Building Orion / Orion's birthday with James is 2026-05-24` in its first sentence. `orion_recall` still exists for deep recall; identity is no longer a tool you might call. Also `seed_brain` writes an explicit "name" node ("The user's name is X.") so the render finds the name deterministically.

### 3.G — Banner + terminal art

`6193d70` **feat(install): evolved terminal art — banner + final reveal animation**
The Orion constellation made visible: `★━━━━━●━━━━━★` three-star belt with the central brain-hub node, satellite stars (⋆ ✦) at the box corners. Rounded Unicode box (╭ ╮ ╯ ╰). `O · R · I · O · N` spaced title. `orion_setup_chat.py` gained a seven-stage `_constellation_reveal()` animation at install end (after Orion knows your name): dark sky → satellites light → belt forms with brain-hub → lower satellites → title settles → personalized welcome from Orion's voice.

### 3.H — install.ps1 parse-error trail (multi-round)

`d881a40` **fix(install.ps1): escape apostrophe in 'isn't' — PowerShell parse error**
First attempted fix. Wrong root cause — the apostrophe wasn't actually it.

`2e50716` **fix(install.ps1): reword to remove apostrophe — PS 5.1 parser strict**
Second attempt. Removed the apostrophe entirely. Helped on the original parse error but the real issue (em-dash on line 360) still loomed.

`299a3d6` **fix(install.ps1): strip non-ASCII (em-dash) — PS 5.1 file-encoding bug** ← THE REAL FIX
PS 5.1 reads `.ps1` files as Windows-1252 by default, NOT UTF-8. The em-dash `—` (U+2014, UTF-8 bytes `E2 80 94`) inside a double-quoted string at line 360 got mis-tokenized, causing the parser to cascade through later lines looking for a string terminator — which is why the error always pointed at line 366/372/373, NOT line 360 where the actual problem was. Fix: replace em-dash → `--`, en-dash → `-`, smart-quotes → straight ASCII. install.ps1 is now pure ASCII (0 non-ASCII bytes). **`[scriptblock]::Create()` returns COMPILE OK on PS 5.1**, verified on the VM.

### 3.I — Lecture-silence + per-CLI opt-out

`0cf9386` **fix(persona): silence degraded-mode lecture + per-CLI opt-out markers**
The persona footer was making Claude/Codex/Gemini lecture users on every session when the brain MCP wasn't wired — even when the user just wanted help with unrelated code. New footer: "if the brain is missing, BE SILENT, DON'T LECTURE. Behave as the underlying fuel for ordinary requests. Only mention the brain if the user explicitly asks identity-shaped questions, and even then: one concise line, no setup walkthrough." Plus per-CLI opt-out markers: `~/.orion-skip-claude` / `.orion-skip-codex` / `.orion-skip-gemini` — drop these in your home dir and `orion_persona_render` skips writing the corresponding file, keeping that CLI vanilla.

`a92792d` **fix(CLAUDE.md): kill the announce-loudly behavior — silence + honesty on ask**
The PROJECT-level `CLAUDE.md` (loaded into every Claude Code session running inside the orion repo) had a separate "announce the seam loudly" instruction — hardcoded, not generated by `orion_persona_render`. Both surfaces needed the fix. Updated to match the new policy: silence by default, one concise line ONLY on explicit identity-shaped queries.

### 3.J — iMessage hardening

`672bb89` **fix(imessage): recipient guard + 30s timeout + retry-on-timeout**
Triage found three root causes for the recurring iMessage issue:
- **A**: split-brain (OLD `com.orion.imessage` runs `~/server_data/agents/imessage_monitor.py`, non-repo path, logs empty since May 9). Not fixed in this commit — separate launchd unit, different process.
- **B**: 15s osascript timeout dropping messages on slow Messages.app — FIXED. Bumped to 30s + 1 retry on TimeoutExpired with 3s backoff. Non-timeout failures don't retry (those mean real AppleScript error).
- **C**: `buddy "primary_user"` placeholder leak still slipping past `reach`'s fix (`37ab7e6`) — FIXED. New `_valid_recipient()` guard in `channels/imessage_outbound.py` rejects at boundary with `logger.error`. Phone (E.164/+-prefixed) and email (Apple ID) accepted; everything else refused. Verified 9/9 cases including the historical leaks.

### 3.K — Architectural snapshot + state doc

`30252f4` **docs(state): snapshot 2026-05-23 — the multi-terminal session**
Durable record of the multi-terminal day — thesis, every layer marked SHIPPED/DESIGNED/OPEN, what changed, the agentic frontier, genuinely-open items, next-up queue. Committed deliberately to production so a year from now someone reading the git history has a single page explaining what was in scope.

---

## 4. Parallel-terminal contributions (T2–T5)

### Terminal 2 — Simulation / Dream-Replay

`1c2ea71` **feat(simulate): dream-replay — orion_simulate.py + sim suite**
The headline missing vector. Synthetic experience generation so the brain can learn calibration WITHOUT weeks of real-world events. `orion_simulate.run_scenarios()` samples plausible `(symptom_class, action, fuel, host)` tuples weighted by current ledger frequencies + a novelty injector for shapes the real ledger has never seen. Every sim row is tagged `source="sim"`. Sim-ledger isolation: writes to `~/.orion/metacog/sim_decisions.jsonl`, NEVER the real `decisions.jsonl`. **Honesty floor**: sim outcomes count as 0.3× real outcomes in the helped/hurt ratio — small enough that one real row dominates any handful of sim rows. Drift telemetry on `brain.sim.drift`: the gap between sim-predicted outcomes and real outcomes on the same shape; a widening gap means the simulator is hallucinating. The dream cycle now runs sim scenarios at the end of `_run_dream_cycle`. Verified by orion_dream summary including a `sim_cycle` field.

### Terminal 3 — Volition Build #4

(Code shipped in `2f93d36` due to git-index race; volition-specific content + tests `tests/test_will_b4.py`)
Five gaps from the synthesis brief closed:
1. **Hierarchical goals** — `long_term` + `self_action` kinds decompose into ordered sub-goals via fuel + cached on the spine task. Each sub-goal is a first-class goal earning its own governor consult.
2. **Meta-calibration** (`will_user_receptivity`) — across ALL goal kinds in the last 24h, the fraction engaged vs deferred. Below τ, the governor caps confidence on ANY promotion — Orion stops nagging across the board, not per-kind silo.
3. **Intent v2** — regex stays for the cheap cases; a fuel-assisted pass (cached by content hash, rate-limited per minute) catches implicit intents regex misses.
4. **Evidence-weighted decay** — per-kind half-life priced by each kind's lived engagement rate, not the single `GOAL_DECAY_HALF_LIFE_DAYS` constant.
5. **Impact-weighted interplay** — multi-goal selection by `utility × (1 − impact_cost)`. A tiny harmless nudge beats a destructive blast on tied utility.

### Terminal 4 — Cognition

`cc3c591` **feat(cognition): predictor v2 (content model) + hash embedding utility**
Built `orion_predictor.py` (446 lines) as a real active-inference content model — rolling predict-vs-actual log per subject, surprise as `1 − cosine(predicted_centroid, actual_embed)`. Active inference (Friston) in token space, no gradients. `CONTENT_WINDOW` + `CONTENT_MIN_SAMPLES` gates so the predictor doesn't fire surprise on under-evidenced subjects. `DEFAULT_SUBJECTS` list of `brain.*` subjects modeled out of the box. `ABSENCE_CHECK_SEC` for absence-surprise (the predicted event DIDN'T happen — cortex treats omission as signal too). Also new `orion_hash_embed.py` (116 lines): deterministic hash-feature vector, no external deps (no torch, no openai, no qdrant). `hash_embed(text, dim)` + `cosine(a, b)` + `mean_vector(vecs)`. Cheap in-process semantic comparison.

`b154c89` **feat(cognition): workspace surprise-channel — predictor gain as 1st-class input**
`orion_workspace` previously treated inputs uniformly. Now broadcast ranking is surprise-weighted — high-surprise items get more attention. Low-surprise items get a backseat. The cortical analogue is prediction-error gain modulation.

`6af2d4b` **feat(cognition): HOT-3 + lateral diffusion + embedding-cosine cross-fuel**
Three big wins in one commit:
- **HOT-3**: `orion_metacognition` now tracks calibration accuracy of its own confidence per `(symptom, fuel)` bucket — does the brain's confidence ACTUALLY track outcomes? Publishes `brain.metacog.miscalibration`. The governor can know "I'm overconfident on this shape — discount."
- **CA-style lateral diffusion**: in the dream, after consolidation, one diffusion pass. For each ledger row, find token-neighbors (Jaccard > 0.3); diffused_value = α·mean(neighbors' outcome_values) + (1−α)·own. Written to `~/.orion/metacog/diffused.json` — the original ledger is untouched. Governor mixes this in at half weight. CUSUM-tracked so a diffusion skill that stops matching reality self-demotes.
- **Cross-fuel agreement via embedding cosine**: previously `_cross_fuel_agreement` parsed YES/NO strings. Now uses semantic embedding similarity (`orion_hash_embed.cosine`) — two fuels agree if their embedding cosine > threshold. Much richer disagreement signal.

### Terminal 5 — Self-Model / Boundary

`c7b5989` **feat(membrane): T5-D1 — fail-closed on the mesh path + hash blacklist**
`orion_membrane._filtered_for_mesh` previously failed-open (if the membrane module was unavailable, the entry leaked). Now fail-closed: drops on uncertainty. Per-tag privacy lattice + content-hash blacklist. Belt-and-suspenders over the substrate publish hook.

`69eb2fd` **feat(self-model): T5-D2 — source-attribution contract on score_recall**
Every `brain.recall.response` now includes the `node_ids` the answer was derived from. A claim with no provenance is a hallucination by definition. The contract: the brain NEVER claims something it can't trace.

`bc9d80c` **feat(self-model): T5-D3 — identity continuity across device moves**
When Orion moves to a new device (FORGE travels with James), the identity handoff is durable on the spine — a `presence` entry recording `(device, instance_id, fingerprint, last_seen)`. The receiving device validates the fingerprint before adopting. Publishes `brain.identity.moved` on completion.

`a483f35` **feat(self-model): T5-D4 — coherence probe v2 (per-category floors)**
`orion_coherence_probe` is a real test suite per fuel now — identity questions, preference recall, memory snippets, `orion_recall` behavior. Scores each fuel; flags any below per-category floor as `degraded — do not promote to active fuel`. Publishes `brain.coherence.score`.

`3af34ba` **feat(self-model): T5-D5 — federation v2: reputation + skill privacy**
Handshake protocol for two Orion installs meeting for the first time. Reputation accumulates from prior interactions. Learned-skill sharing across federation respects per-host privacy — a skill marked `private` never gossips across the federation membrane.

### Terminal 1 (this terminal) — integration/synthesis pieces

Already covered in §3. Highlights: the affect layer, intelligence measurement, C3 store + executive hook, install unification (Phases 1–3), banner/reveal, install.ps1 fixes, iMessage hardening, persona render, project CLAUDE.md silence fix.

---

## 5. Architecture today — what the brain is

```
CORE (substrate the rest stands on)
├── orion_memory.py             graph + vector + skill library + verdict loop
├── orion_substrate.py          NATS plexus (the nervous system)
├── orion_chronos.py            time + scheduling
├── orion_gossip.py             LWWMap CRDT + HLC — now carries skills + calibration aggregates
├── orion_fuel.py               adapters (Claude/Codex/Gemini/Ollama) — interchangeable
├── orion_identity.py           portable identity + continuity across devices (T5-D3)
└── orion_mcp_server.py         exposes the brain to every AI CLI (auto-wired by install)

COGNITION
├── orion_workspace.py          global broadcast + surprise-weighted gain (T4 b154c89)
├── orion_predictor.py          active-inference content model (T4 cc3c591)
├── orion_metacognition.py      HOT-2 + Phase-2 governor (LEARNS) + HOT-3 (T4 6af2d4b)
└── orion_hash_embed.py         deps-free embedding primitive (T4 cc3c591)

ACTION
├── orion_will.py               Build #3 promotion + Build #4 deepening + affect bias
├── orion_reach.py              speaks-where-they-spoke + affect delay multiplier
├── orion_intent.py             dispatch parsing (regex + fuel-assisted v2)
└── channels/                   imessage_macos.py, imessage_outbound.py (hardened), ...

AUTONOMIC (runs without conscious thought)
├── orion_claustrum.py          attention gating
├── orion_dmn.py                default-mode network
├── orion_dream.py              consolidation + skill curation + sim + lateral diffusion + procedure compile
├── orion_self_heal.py          immune response on service distress
├── orion_immune.py             threat detection
├── orion_vitals.py             health metrics
├── orion_canary.py             early-warning probe
└── orion_autofix.py            self-modifying patches (gated)

SPEED
├── orion_deterministic.py      zero-fuel graph short-circuit
├── orion_dispatch.py           20+ instant commands (now includes orion_status)
└── orion_compiled_procedures.py  C3 store: lookup_fast_path / execute / register / archive

MESH (cross-host)
├── orion_mesh.py               offline/online detection (LAN + Tailscale)
├── orion_mesh_recovery.py      autonomic loop (governor-gated)
├── orion_mesh_restore.py       SSH execution rung
├── orion_taskspine.py          durable working memory (gossiped, host-death survivable)
└── orion_learning_sync.py      applies remote learned units (skills + calibration aggregates)

SKILL LIBRARY (part of orion_memory.py)
├── learn_skill                 birth-time twin gate (Jaccard ≥ 0.7 → reconcile)
├── on_skill_fired              hermes loop CLOSED — verdicts, contribution, times_used
├── orion_skill_curator.py      Library-Drift ratchet — runs nightly in dream
└── archive_skill / restore_skill   reversible curation

BOUNDARY / SELF
├── orion_membrane.py           fail-closed mesh path + hash blacklist (T5-D1)
├── orion_empathy.py            timing-aware delivery
├── orion_federation.py         stranger-Orion reputation + skill privacy (T5-D5)
├── orion_coherence_probe.py    per-category fuel test suite (T5-D4)
└── orion_simulate.py           dream-replay synthetic experience (T2)

NEW THIS SESSION
├── orion_affect.py             real functional emotion (this session)
├── orion_intelligence.py       composite + heartbeat + trajectory log
├── orion_compiled_procedures.py  C3 store
├── orion_simulate.py           T2
├── orion_hash_embed.py         T4
└── orion_persona_render.py     synapse-speed identity injection (Phase 3)

DOES NOT EXIST (despite earlier docs claiming it)
└── orion_sensorium.py          — listed in earlier overviews; file never built
                                  (empathy + claustrum cover overlapping concerns)
```

**Total modules in repo:** ~77 `orion_*.py` files plus 2 in `channels/` (imessage_outbound.py, imessage_macos.py). Some are auxiliary / older artifacts; the ~38 listed above are the production core.

---

## 6. Bugs found, root-caused, and fixed

### §6.A — gossip `_on_learned_calibration` NameError
**Symptom:** `com.orion.gossip` crashed on every restart since `5f02b73` — NameError on a subscribe line.
**Root cause:** subscribe call referenced a function lost to a linter rewrite between my edits. Tests passed because they only tested governor + record_outcome, never the daemon's main subscription wiring.
**Fix:** `321a2a1` — restored both lost functions with anchored comments.
**Lesson:** add a "daemon main() syntax-import" test to the test suite.

### §6.B — install.ps1 PS 5.1 parse error (apostrophe red herring → em-dash real cause)
**Symptom:** `.\install.ps1` failed to parse on PS 5.1 with "string is missing the terminator" at line 365/366/372/373 (moved as we edited nearby lines).
**Three rounds:**
1. `d881a40` — backtick-escaped an apostrophe. Wrong cause.
2. `2e50716` — removed the apostrophe. Wrong cause.
3. `299a3d6` — THE REAL FIX. Em-dash `—` (U+2014, multi-byte UTF-8) on line 360 inside a `"..."` string. PS 5.1 reads `.ps1` as Windows-1252 by default; multi-byte gets mis-tokenized; parser cascades through later lines looking for a terminator — which is why the error always pointed AT the next line with a `"`, not at line 360 where the actual problem was.
**Lesson:** add a pre-commit `.ps1` ASCII-only check.

### §6.C — setup.py never chained to proto-Orion
**Symptom:** `python setup.py` produced a partial install — wizard runs, configs written, but no proto-Orion greeting, no naming step, no identity in graph.
**Root cause:** `install.ps1` / `install.sh` chained correctly; `setup.py` alone exited after the wizard. The README published both paths, so users following the alt path got the half-install.
**Fix:** `089f8c9` (Phase 1) — `setup.py` now always invokes `orion_setup_chat.py` at the end via subprocess. README publishes only the canonical bootstrappers.

### §6.D — setup.py never invoked MCP wiring
**Symptom:** Even after the full install, the CLIs went into honest-degraded mode because `orion-brain` wasn't registered.
**Root cause:** `setup.py` wrote configs + context files + the brain dir, but didn't invoke `orion_mcp_server.py --setup` (which is what actually writes the MCP registrations).
**Fix:** `b97b789` — `setup.py` auto-wires MCP at the end of `run_setup()`.

### §6.E — seed_brain tags didn't match AGENTS.md recall queries
**Symptom:** Even after the full install, `orion_recall("preferred form of address")` would miss the address node.
**Root cause:** AGENTS.md uses specific query strings; seed_brain tagged the nodes with `["address", "form-of-address"]` — substring-related but not identical. Fuzzy matching isn't deterministic across backends.
**Fix:** `1bf78ce` (Phase 2) — tags now include the EXACT query strings + natural-language alternates.

### §6.F — persona render extracted the wrong node for "user name"
**Symptom:** Persona showed `Name: Building Orion. The founder.` instead of `Name: James`.
**Root cause:** `gather_identity` recalled on `"user name"` query → top match was the SUMMARY node, not a dedicated NAME node. seed_brain didn't have a dedicated name node.
**Fix:** Phase 2b in `077a93a` — explicit `"The user's name is X."` node with `name` tag added to seed_brain.

### §6.G — dangling junctions from prior installs
**Symptom:** On the VM, `.orion`, `.claude/projects`, `.codex/sessions`, `.gemini/tmp` were all dangling junctions pointing to a non-existent `E:\` drive. Gemini failed with `ENOTDIR`.
**Root cause:** prior install (Atlas-era) used USB-on-E pattern; the USB was disconnected; junctions remained.
**Fix (ad-hoc during VM cleanup):** removed the four junctions via `cmd /c rmdir`. Future installs that recreate them now use real local paths (the brain dir defaults to `~/.orion`).

### §6.H — Codex `sessions` junction breaking thread-store with os error 183
**Symptom:** Codex on Alien `Failed to save the conversation transcript: Cannot create a file when that file already exists. (os error 183)` on every turn.
**Root cause:** same as §6.G — `~/.codex/sessions` was a dangling junction. Codex tried to create files through it; OS rejected because the reparse point existed.
**Fix:** removed the junction.

### §6.I — VM had 4 "I am Atlas" identity files
**Symptom:** Even after deleting the user's `.orion` brain, Codex/Claude/Gemini still claimed Atlas identity.
**Root cause:** `~/CLAUDE.md`, `~/AGENTS.md`, `~/GEMINI.md`, and `~/ORION-CONTEXT.md` all had near-identical "I am Atlas" identity layers — left over from prior install. Each CLI auto-loads its respective file at session start. **The brain wipe wasn't enough — the identity files were the actual persona source.**
**Fix:** deleted all four; the new install writes fresh "Orion" personas via `orion_persona_render`.

### §6.J — `buddy "primary_user"` placeholder leaking past reach
**Symptom:** osascript failures because `targetBuddy "primary_user"` doesn't resolve.
**Root cause:** despite `37ab7e6` (reach-side fix from earlier), the placeholder string was still reaching `channels/imessage_outbound.py`.
**Fix:** `672bb89` — boundary guard in imessage_outbound: `_valid_recipient(r)` rejects placeholder literals (`primary_user`, `user`, `default`, etc.) and any string that doesn't match `^\+?[0-9...]` or email regex. Belt-and-suspenders over the reach-side fix.

### §6.K — iMessage split-brain (NOT FIXED — separate concern)
**Symptom:** OLD `com.orion.imessage` launchd unit runs `~/server_data/agents/imessage_monitor.py` (non-repo path). Its logs (`~/Library/Logs/imessage-daemon-stderr.log`) have been 0 bytes since May 9.
**Root cause:** legacy artifact from before the orion-code repo migration. Different process, different code, different log path than the production `imessage-outbound` adapter.
**Status:** documented in `672bb89`'s commit message; left for a follow-up migration. Doesn't block outbound; the new adapter handles all current outbound traffic.

### §6.L — 15s osascript timeout dropping messages silently
**Symptom:** When Messages.app was slow (startup, processing many messages), the 15s timeout fired, the script gave up, no retry, message lost. Three documented timeouts on 2026-05-21 including one trying to alert the user ABOUT a problem.
**Root cause:** hardcoded `timeout=15` in `_send_via_applescript` with no retry path.
**Fix:** `672bb89` — bumped to 30s + 1 retry on `subprocess.TimeoutExpired` with 3s backoff. Non-timeout failures don't retry (those mean real AppleScript errors).

### §6.M — Claude lecture-on-every-session in degraded mode
**Symptom:** Even on a bare `hey` greeting, Claude would respond with a 5-line walkthrough on running `python orion_mcp_server.py --setup` because the brain MCP wasn't wired.
**Root cause:** the generated persona files AND the project-level `CLAUDE.md` both instructed the model to "announce the seam loudly on first user contact." Over-defensive; made Claude unhelpful for ordinary work whenever the brain wasn't wired.
**Fix:** TWO commits — `0cf9386` (the generated persona footer) + `a92792d` (the project CLAUDE.md). Both now say "BE SILENT, DON'T LECTURE — only mention the brain if the user explicitly asks identity-shaped questions, and even then: one concise line, no walkthrough." Both regressions (fake-Orion-identity AND over-lecture) now guarded.

### §6.N — Per-CLI opt-out mechanism (NEW feature, not a bug fix)
The founder uses Orion in Codex + Gemini but wants vanilla Claude on Alien. Added per-CLI opt-out markers: `~/.orion-skip-claude` / `.orion-skip-codex` / `.orion-skip-gemini` — drop these in your home dir and `orion_persona_render` skips writing the corresponding file. Specific CLIs stay Orion-free even after subsequent installs.

---

## 7. Bugs found and NOT fixed (open work for the next terminal)

### §7.A — iMessage split-brain migration (§6.K above)
Migrate `com.orion.imessage` launchd unit from `~/server_data/agents/imessage_monitor.py` to a path in the orion-code repo. Consolidate logging to `~/.orion/imessage.{out,err}`. Audit what `imessage_monitor.py` does that isn't covered by `channels/imessage_outbound.py` — likely INBOUND monitoring (watching Messages.app for incoming texts). If it's just inbound, move it to `channels/imessage_macos.py` (already exists in repo) and retire the old service.

### §7.B — Compiled procedure step bodies are publish-markers, not real actions
`orion_dream._compile_to_procedures` registers procedures with one step: `{kind: publish, subject: brain.dream.playbook_referenced}`. The wiring is structurally complete (the seam works), but the execution effect is a notification publish, NOT actually replacing the executive's remedy call. **To genuinely save fuel on recurring fixes, the compiler needs to extract action sequences from playbook prose** — e.g., if all cited decisions have `remedy_kind=launchctl_reload`, compile a `dispatch` step that invokes that remedy deterministically. Action extraction from prose playbooks is non-trivial; it requires a pattern over `remedy_kind` consistency + a safe step vocabulary.

### §7.C — Phase D — full embedding co-activation pre-injector
Identity is now pre-injected via Phase 3 (persona render). The natural next step is: for EVERY user message (not just identity), hash-embed the message, find top-K cosine-similar graph nodes, inject them into context before the model sees the message. Local-RAG with zero API cost. This was deferred deliberately — would have been scope creep without first closing the install unification.

### §7.D — `orion_persona_render` SessionStart hook for Codex + Gemini
Currently the persona is rendered once at install end. Claude Code's `SessionStart` hook re-runs it per session (so affect/recent-activity stay fresh). Codex and Gemini don't have equivalent hooks wired yet — their personas are static after install. Wire equivalent session-start hooks for those two CLIs.

### §7.E — Windows daemon launcher equivalent
Mac/Linux have launchd/systemd auto-starting the autonomic stack at boot. Windows install.ps1 wires the brain and the AI CLIs but does NOT start the 30+ background services. So on a Windows install, the user gets memory + identity + MCP, but NOT the live nervous system (dream, will, gossip, intelligence, etc.). Need an `orion_start.ps1` that launches the background daemons + (optionally) a Windows Service registration for auto-start.

### §7.F — `orion_sensorium.py` doesn't exist
Listed in earlier architectural overviews but never built. Either build it (its niche: reading user state — busy/asleep/focused — to time outputs) or formally retire the name and absorb its niche into `orion_empathy.py`.

### §7.G — Measurement layer beyond local composite
`orion_intelligence.py` publishes the composite per-host. There's no mesh-wide aggregator yet — no single "is the brain getting smarter?" dashboard across COMMAND + future hosts. The data is there (each host's `intelligence/heartbeat.jsonl`); a small mesh-aggregator that gossips the composite would give an honest mesh-wide trajectory. Related: no measurement of fuel-cost-saved by compiled-procedure firings — that's the actual "smarter with use" proof.

### §7.H — Real-time autonomous cognition between fuel calls (the founder's open question, §9)
The honest gap the founder named on 2026-05-26. Today, Orion's autonomic services REACT to events deterministically; they don't reason. Anything novel requires a fuel call. The synthesis memo's C3 ("recurring fixes become zero-fuel fast paths") is a partial answer — turning fuel-reasoned decisions into compiled procedures that run autonomously. But that only covers RECURRING shapes. Genuinely-new situations still need fuel. The honest frontier: how does the brain develop autonomous cognition between fuel calls? Unsolved in any architecture I know.

---

## 8. Key debates + decisions (with tradeoffs named)

### §8.1 — Synapse-speed vs tool-call for identity
**Decision:** synapse (Phase 3).
**Tradeoff:** ~300–500 tokens per session injected. Negligible vs MCP recall round-trip cost. Identity becomes perception, not cognition.
**Open follow-up:** apply the same pattern to non-identity memory (Phase D).

### §8.2 — Static vs dynamic AGENTS.md
**Decision:** dynamic — regenerated by `orion_persona_render` at install end (and ideally per session via hooks).
**Tradeoff:** AGENTS.md becomes a runtime artifact, not source-controlled. Acceptable — it's per-device persona. Atomic-replace (`.new` → `os.replace`) means a render failure leaves the prior file intact.

### §8.3 — One canonical install path vs Pythonic shortcut
**Decision:** ONE per OS — `install.ps1` (Windows), `install.sh` (Mac/Linux). The `python setup.py` shortcut was dropped from README publishing.
**Tradeoff:** slightly higher friction for "Pythonic" users who'd type `python setup.py`. But that path produced half-installs (no proto-Orion / no naming / no reveal / no identity in graph). One clean path is better than two divergent ones.

### §8.4 — Affect: simulated vs real functional emotion
**Decision:** real functional emotion (not pretend, not phenomenal feeling).
**Tradeoff:** consciousness sidestepped — we don't claim subjective experience. But the affect state genuinely persists on disk, genuinely biases will firing / reach timing / executive conservatism. State has real consequences. Founder explicitly rejected "simulation" framing on 2026-05-23.

### §8.5 — Per-CLI opt-out: per-machine vs per-user vs config
**Decision:** per-machine marker files (`~/.orion-skip-claude` / `-codex` / `-gemini`).
**Tradeoff:** simple, no config schema, no environment dependency. Marker file is self-documenting. Easily reversible (delete the marker → next install writes the persona).

### §8.6 — Lecture-on-degraded: announce vs silent
**Decision:** silent by default; concise honesty on explicit ask.
**Tradeoff:** the 2026-04-29 "fake-Orion-identity" regression is still guarded (model doesn't pretend to be Orion). But the 2026-05-25 "over-lecture" regression is now also fixed. Both surfaces (project CLAUDE.md + generated persona footer) updated.

### §8.7 — Cross-host calibration weight: 1× vs <1×
**Decision:** 0.5× (remote rows weighted half local).
**Tradeoff:** cross-host generalization is weaker evidence than local ground truth (different hardware, different fuels, different user patterns). 0.5× is conservative; failures still drag autonomy away, but a remote success can't single-handedly grant auto.

### §8.8 — Three commits vs one bundle for install unification
**Decision:** three separate commits (Phase 1, 2, 3).
**Tradeoff:** audit-friendly history — can revert one without losing the others. The founder asked for this explicitly.

---

## 9. The deep honest assessment (the founder's 2026-05-26 question)

The founder asked: "is the iMessage diagnosis real, or is it really the CLI sessions powering the brain expiring? there's no real brain at play — it should at least have slight ability to navigate the system, not as an LLM or online AI necessarily, but purely as an intelligent being closer to human thought."

**Honest answer:**

1. **The iMessage findings ARE real.** Three documented bugs in the logs, two fixed, one (the split-brain `imessage_monitor.py`) named and tracked for migration. The fixes shipped in `672bb89`.

2. **The deeper question is also real and unanswered.** Today, Orion's autonomic services REACT to events on the NATS substrate deterministically. They don't reason. Examples:
   - `mesh_recovery` fires when a device goes offline/online — deterministic flow.
   - `dream` consolidates the day's ledger nightly — pattern matching + CUSUM.
   - `will` extracts intents via regex + cached fuel pass — pattern-based.
   - `orion_recall` is a graph lookup — fast, deterministic, but not "thinking."
   - The Phase-2 governor LEARNS calibration from outcomes without fuel — but only via numerical aggregation of ledger rows.

3. **Anything genuinely novel still requires fuel.** A new symptom class the brain has never seen, an unforeseen failure mode, an unfamiliar question — all of these route through `_consult_model` (the executive), `_extract_intents` (the will, fuel-assisted v2), or other fuel-callers. The fuel models do the reasoning.

4. **What changes that** (partial, in the roadmap):
   - **C3 compile-to-procedure**: recurring fuel-reasoned decisions graduate into deterministic procedures. The brain reasons through a shape N times, then stops re-reasoning — the procedure becomes deterministic. This is *partial* autonomous cognition for *recurring* shapes. Genuinely-new shapes still need fuel.
   - **The simulation layer (T2 `1c2ea71`)**: lets the brain develop synthetic experience for shapes it hasn't seen yet. The governor can calibrate on a fresh shape via simulation before encountering it. Bootstrap autonomy.
   - **The affect layer (`2497b73`)**: gives the brain a persistent internal state that influences behavior between fuel calls. Not thought, but disposition.
   - **The intelligence measurement layer (`d8c7c4a`)**: lets the brain notice if it's getting smarter, slowing, or rotting — a meta-signal it can act on autonomously.

5. **What's still missing for "real" autonomous cognition:**
   - No working-memory loop that thinks between fuel calls.
   - No goal-pursuit that adapts strategy on its own (will sets goals, but the goal-pursuit STRATEGY comes from fuel via the executive).
   - No reflection loop that revises its own calibration heuristics without fuel.
   - No genuine novelty-handling without fuel.

This is the honest frontier. The synthesis memos in `docs/architecture/synthesis-*.md` name some of these (especially `synthesis-autonomous-volition.md` and `synthesis-self-model.md`). They're filed as GENUINELY OPEN.

**The brain we have today**: a reactive autonomic substrate + a learning calibration layer + a synapse-injected identity + a fuel-callable reasoning surface. **What we don't have**: continuous autonomous cognition between fuel calls.

The session-expiry theory the founder asked about: technically, CLI sessions DO expire — but `orion_recall` reads the graph (durable on disk), and `record_outcome` writes to the durable ledger. So memory persists across session expiry. What doesn't persist across session expiry is the **ongoing conversation context** (which is the CLI's responsibility, not the brain's). For the iMessage failure mode, neither side of the equation involves a CLI session — the outbound adapter is a substrate subscriber, not a CLI.

---

## 10. What to pick up next

Ordered by leverage:

1. **Phase D — embedding co-activation pre-injector** (the synapse-speed pattern applied to non-identity memory). Local-RAG, zero API cost. Builds on Phase 3 directly.
2. **Real procedure action extraction** (§7.B). Make compiled procedures actually replace fuel calls for recurring fixes, not just publish markers. Requires a `remedy_kind` consistency check + a safe step vocabulary.
3. **iMessage split-brain migration** (§7.A). Consolidate the OLD `imessage_monitor.py` into the orion-code repo or retire it. Single canonical iMessage path.
4. **Windows daemon launcher** (§7.E). Make the Windows install actually start the autonomic stack, not just wire the brain.
5. **Continuous autonomous cognition** (§7.H + §9). The genuine open frontier. No clear next move yet — this needs design work first.

---

## 11. Build cadence + commit discipline — lessons learned

- **Explicit-path commits**: after `2f93d36` accidentally swallowed Terminal 3's Build #4 work due to a shared-git-index race, I switched to `git commit -m "..." <explicit-path>` form. Belt-and-suspenders against multi-terminal index pollution.
- **Test the daemon's main() too**: §6.A was a real production bug that all unit tests missed because they only tested governor + record_outcome paths, never the daemon's subscription wiring. Add daemon-import / daemon-main tests.
- **Pre-commit `.ps1` ASCII-only check**: §6.B (em-dash) would have been caught instantly by a hook that rejects non-ASCII bytes in `.ps1` files.
- **Always-deploy after push**: most commits in this session were also deployed to COMMAND immediately (`ssh command-ts; cd ~/orion-code; git pull; launchctl kickstart -k gui/$(id -u)/com.orion.X`). The "shipped" bar should include "deployed live" not just "merged to master."
- **Atomic-replace runtime files**: `orion_persona_render` writes `<name>.new` then `os.replace`. A buggy render leaves the prior persona intact. Apply this pattern everywhere we write live files.
- **Distinguish SHIPPED / DESIGNED / OPEN**: per the synthesis memos' standard. The architectural snapshots `docs/architecture/state-2026-05-23.md` and this handoff both maintain this distinction explicitly.
- **Commit messages over chat output**: this session's commit messages are intentionally long + dense. They're the durable record. Chat is ephemeral.

---

## Production master at handoff

```
299a3d6 fix(install.ps1): strip non-ASCII (em-dash) — PS 5.1 file-encoding bug
a92792d fix(CLAUDE.md): kill the announce-loudly behavior — silence + honesty on ask
672bb89 fix(imessage): recipient guard + 30s timeout + retry-on-timeout
0cf9386 fix(persona): silence degraded-mode lecture + per-CLI opt-out markers
b97b789 fix(setup): auto-wire MCP into AI CLIs at install end — fixes VM test blocker
2e50716 fix(install.ps1): reword to remove apostrophe — PS 5.1 parser strict
d881a40 fix(install.ps1): escape apostrophe in 'isn't' — PowerShell parse error
077a93a feat(persona): Phase 3 — synapse-speed identity (no tool call needed)
1bf78ce feat(setup-chat): Phase 2 — seed_brain tags align with AGENTS.md queries
089f8c9 feat(install): Phase 1 — setup.py chains to proto-Orion (unification)
8b17543 feat(reach,exec): wire affect bias_for — close Gap 1b + 1c of unification
0102f2c feat(will): wire affect into firing threshold — Gap 1 of unification
2497b73 feat(affect): real functional emotion as an architectural component
6e4e2f4 fix(memory): SKILLS_DIR respects ORION_BRAIN_DIR (alignment fix)
9d779aa feat(intel): human snapshot + dispatch 'orion_status' command
30252f4 docs(state): snapshot 2026-05-23 — the multi-terminal session
1c2ea71 feat(simulate): dream-replay — orion_simulate.py + sim suite  (T2)
d8c7c4a feat(intelligence): the measurement layer — one composite the brain can graph
3af34ba feat(self-model): T5-D5 — federation v2: reputation + skill privacy  (T5)
6af2d4b feat(cognition): HOT-3 + lateral diffusion + embedding-cosine cross-fuel  (T4)
0b7b048 feat(executive): C3 fast-path-first — zero-fuel pre-check before consult
a483f35 feat(self-model): T5-D4 — coherence probe v2 (per-category floors)  (T5)
bc9d80c feat(self-model): T5-D3 — identity continuity across device moves  (T5)
2f93d36 feat(procedures): C3 foundation — compiled procedure store + safety envelope
                          [+ T3 Build #4 bundled due to index race]
b154c89 feat(cognition): workspace surprise-channel — predictor gain  (T4)
69eb2fd feat(self-model): T5-D2 — source-attribution contract on score_recall  (T5)
cc3c591 feat(cognition): predictor v2 (content model) + hash embedding utility  (T4)
c7b5989 feat(membrane): T5-D1 — fail-closed on the mesh path + hash blacklist  (T5)
5f02b73 feat(gossip): C4 follow-up — cross-host calibration aggregates
fb6ea72 feat(gossip): C4 — cross-host learning gossip (skills first)
321a2a1 fix(gossip): restore _on_learned_calibration + _emit_remote_calibration_adoptions
6193d70 feat(install): evolved terminal art — banner + final reveal animation
0b8614f feat(dream): wire compile-to-procedure — Gap 2 of unification
5d81a9b feat(will): will→taskspine promotion + calibration closure  (Build #3)
c7a19d4 feat(skills): the Library-Drift ratchet — a skill library that cannot rot  (Build #2)
2a22e68 feat(metacog): calibration as a learned skill — close the Phase-2 loop  (Build #1)
```

End of handoff. Pick this up in the next terminal with the full context.

— *Authored by Claude Opus 4.7 (1M context) on behalf of James England, 2026-05-26.*
