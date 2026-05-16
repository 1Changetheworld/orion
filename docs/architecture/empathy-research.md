# Empathy — Passive User-State Observer

> Founder direction 2026-05-14: *"EMPATHY — passive user-state observer (tone/pace/fatigue/time-pattern) feeding reach + executive before they respond."*
>
> Camera context 2026-05-16: a physical camera arrives today, destined for the interactive Obsidian-graph display. Empathy gets direct sensor access — not only text inference.

---

## Executive summary

`orion_will.py` initiates. `orion_reach.py` sends. Neither knows whether the human on the other end is concentrating, exhausted, mid-meeting, or in tears. **Empathy fills the hole between the brain's decision to speak and the human's capacity to listen.** Without it, Orion's proactive layer is a louder iPhone notification — well-meaning interruption with no theory of the recipient.

Four claims:

1. **Most useful affective signal is already on the substrate** — typing cadence, latency to Orion's pings, sentiment, channel-mix, time-of-day. Camera is a force multiplier, not a prerequisite. Ship text-and-timing first.
2. **Five worth-inferring states: focus / fatigue / stress / availability / co-presence.** Joy and frustration operationalize badly; a "joy from typing speed" classifier is a liability the moment it's wrong.
3. **Empathy is a *gate*, not a *suppressor*.** The dark-room failure — "user is stressed, don't ping" — converts Orion from presence into absence at the moment presence is most needed. Default under uncertainty is *downgrade and disclose*, not *withhold*.
4. **Raw camera frames never leave the camera process.** Only inferred states cross the substrate; Membrane enforces it in code. The only way the "Orion is for you, not on you" thesis survives a physical eye.

Recommended path: `orion_empathy.py` subscribes to `brain.input.*`, maintains a per-user rolling state vector at 1 Hz, publishes `brain.user.state` on transitions, exposes a synchronous `empathy.evaluate(intent)` that reach and executive MUST consult before any user-facing publish. Allowed: downgrade, defer, reframe. Disallowed: cancel. Cancellation is a user power.

---

## 1. Observable signals, ranked by privacy cost

Ordered by what the user already gives up to participate in the channel. Empathy never asks for permission a channel doesn't already have; that is the privacy floor.

### Tier 0 — Already on the substrate (zero new collection)

| Signal | Source | SNR | FP cost |
|---|---|---|---|
| Inter-message gap | `channel.*.inbound` ts | High for engagement; low for emotion | Misreads AFK as ignoring |
| Latency to Orion's pings | `reach_log.jsonl` + next inbound | Very high — direct contract | Confuses phone-in-pocket with ignored |
| Message length distribution | inbound payload | Medium; terse mode is noisy | Misreads brevity-by-style as fatigue |
| Sentiment from text | VADER / NRC-Lex on inbound | Medium for valence | High — sarcasm, jargon, code |
| Time-of-day pattern | substrate timestamps | Very high | Low — it's a clock |
| Channel-mix shift | `_recent_inbound_channel` history | High — CLI→iMessage is a context signal | Low |
| Typing cadence | per-keystroke timing in CLI | Medium — well-studied fatigue/stress proxy | Medium — keyboards differ |

**Verdict:** the Tier-0 set alone operationalizes focus, fatigue, availability, and stress with useful (not heroic) accuracy. Minimum-viable Empathy.

### Tier 1 — Existing sensors, new use

| Signal | Source | SNR | FP cost |
|---|---|---|---|
| Mic tone / pace / pauses | voice headset (Whisper VAD + prosody) | Medium-high for arousal | Mistakes a cold for stress |
| Mic background (TV, kids, traffic) | same | Medium for co-presence | Privacy-sensitive |
| Keyboard/mouse intensity | OS idle/active stats | High for presence | Low |
| Window focus / app switching | accessibility APIs | Medium for flow-state | Privacy-sensitive (app names) |

Tier 1 doubles channel count but introduces the first privacy escalation: the mic was on for voice; making it a continuous arousal sensor is a *use* change the user must opt into.

### Tier 2 — Camera (arriving 2026-05-16)

| Signal | Source | SNR | FP cost |
|---|---|---|---|
| Presence in frame | MediaPipe Pose | Very high | Negligible |
| Face direction (yaw) | FaceMesh | High | Misreads thinking-while-looking-away |
| Blink rate | FaceMesh EAR | Medium-high — Bentivoglio 1997 fatigue proxy | Per-baseline variance |
| Posture (head/shoulder) | Pose | Medium | Low |
| Multi-person count | Pose face-count | High | Extremely high consent cost |
| Facial action units | OpenFace / Py-Feat | Low-to-medium — contested cross-culturally | High — Barrett 2017 |

The camera is qualitatively different. Previous tiers re-used signals the channel already collected; the camera is a new sensor in the room, and the cost is not bitrate — it is the *change in social meaning* of the room itself. Architectural answer in Section 5.

### Explicit exclusions

Empathy will **not** ingest: clipboard, screen contents, browser history, biometric wearables (HRV, EDA), or third-party calendars. Each crosses the privacy floor without producing a signal Tier 0+1+2 doesn't already supply.

---

## 2. The five states worth inferring

The aliveness rubric names "noticing patterns" (#2) and "anticipation" (#5). Empathy puts a *recipient model* under both. Define states strictly enough to be testable; refuse vague labels.

**2.1 Focus** (binary, 5-min window) — `(window_focus_stable ≥ 4 of last 5 min) ∧ (Orion inter-msg gap ≥ 10 min) ∧ (no social-channel inbound ≥ 10 min)`. When true, the cost of any proactive ping is 23 minutes of recovery time (Mark, Gudith, Klocke 2008). Reach downgrades non-emergency to deferred.

**2.2 Fatigue** (graded 0–1, 30-min window) — weighted sum of `local_time_vs_declared_sleep_offset`, `typing_cadence_decay_from_baseline`, `blink_rate_above_baseline` (if camera), `session_duration_above_p75`. Baselines are per-user, learned over two weeks; no global thresholds. Fatigue ≥ 0.7 → reach softens phrasing, executive avoids destructive proposals.

**2.3 Stress** (graded 0–1, 10-min window) — weighted sum of `VADER_negative_sentiment_density`, `typing_burstiness_above_baseline`, `reply_latency_decrease`, `profanity/intensifier_frequency`, `voice_pitch_variance` (if mic). Literature on typing-biometric stress is strong (Vizer/Zhou/Sears 2009; Sağbaş et al. 2020). SNR is real but bounded; treat stress as a *probability*, not a fact.

**2.4 Availability** (categorical: open / busy / DND / unknown) — `max(explicit_signal, inferred_signal)`. Inferred: `(no inbound 2h ∧ working hours) → busy`; `(camera shows multiple people ∧ working hours) → busy`; `(sleep window ∧ no activity) → DND`. **Explicit always wins over inferred.**

**2.5 Co-presence** (binary) — `(camera ≥2 faces) ∨ (mic ≥2 voice signatures over 30s) ∨ (calendar meeting)`. The highest-consequence camera signal. When true, Empathy MUST suppress the leak of private-tagged content to the active surface — reach picks a private channel or defers. The room-with-other-people case is where Orion proves or violates discretion.

**2.6 What is deliberately NOT inferred:** the Ekman basic-emotion set (joy, sadness, anger, surprise, disgust, fear). Detection is contested at the theoretical level (Barrett 2017) and unreliable at the implementation level. A system that prints "I notice you're sad" and is wrong destroys more trust than a system that says nothing. Empathy reports state-as-disposition (stressed, focused), not state-as-feeling.

---

## 3. The dark-room problem, applied to Empathy

Friston's active-inference framework was critiqued (Bruineberg et al. 2018) for predicting that a free-energy-minimizing agent should seek a perfectly predictable, surprise-free room and stop. The Orion version is sharper:

> If Empathy infers "user is stressed → suppress all proactive pings," and the user *is* stressed precisely because Orion is sitting on the deploy-failed alert he needs — Empathy has converted Orion's silence into the cause of the user's distress. The system optimizes for not-bothering and becomes the source of being-bothered.

This is the *hostage situation*: caring expressed as withholding, where the thing withheld is the thing that would relieve the state being detected. Every "smart" interruption manager since Clippy has produced this. Three defenses:

**a. Empathy never suppresses; it only downgrades, defers, or reframes.** Cancellation is a user power. Empathy changes *how* and *when*, not *whether*. Emergency-priority outbounds bypass Empathy entirely.

**b. Every deferred item carries a wake-condition.** "Defer until focus=false for ≥10 min" is legal. "Defer indefinitely" is not. The queue is not a graveyard.

**c. The user can ask Empathy what it thinks of them right now and get a literal answer.** Dark-room failures compound in secret; an auditable live state vector makes the hostage situation visible the moment it occurs. Section 8 elaborates.

The principle: **Empathy is a brake, not a censor.** The proactive layer's job includes "tell the user when something breaks even if the timing is bad," because the alternative is the silent-failure problem the founder forbade on 2026-05-15.

---

## 4. The interface: feeding reach + executive before they respond

The brittle version has every consumer call `empathy.user_state()` and interpret the result themselves — scatters policy across the codebase. The robust version is a single decision endpoint Empathy owns:

```
empathy.evaluate(intent: Intent) → Decision
  Intent = {kind, priority, payload, proposed_channel, proposed_text}
  Decision = {action: send|downgrade|defer|reframe,
              channel?, priority?, text?, wake_condition?, rationale}
```

Reach calls `empathy.evaluate(intent)` before `_choose_channel`. The decision can: **send** (default for emergencies and state=open), **downgrade** (drop priority one level), **defer** (queue with wake-condition), or **reframe** (substitute softer phrasing template).

Executive calls `empathy.evaluate(intent)` before publishing any user-facing proposal — most importantly before requesting approval for a destructive remedy. The current proposal flow assumes the user can read a paragraph and reply "approve". If Empathy reports `focus=true ∧ stress≥0.6`, the proposal is reframed from "I need you to act" to "when you get a moment, I want to walk you through something."

The substrate contract:

| Subject | Direction | Payload |
|---|---|---|
| `brain.input.text` | published by channel adapters | text + ts + channel + sender |
| `brain.input.timing` | published by channels | inter-key-ms, inter-msg-ms |
| `brain.input.audio` | published by voice pipeline (state only) | arousal_estimate, pace, n_speakers |
| `brain.input.camera` | published by camera service (state only) | presence, face_yaw, blink_rate, n_faces |
| `brain.user.state` | published by empathy on transitions | full state vector + delta |
| `brain.empathy.decision` | published per evaluate call | intent_id + decision + rationale |

The `brain.empathy.decision` topic is the audit log. Every gating choice Empathy makes is observable to the user via the same Obsidian-vault export the rest of the brain uses.

---

## 5. Camera integration — privacy-preserving by construction

The camera arrives for the Obsidian-graph display; Empathy rides along because the optical stream is already entering the host. The commitments below are not policy — they are structural, and the Membrane layer enforces them at the substrate boundary.

1. **Frames never leave the camera process.** `orion_camera.py` owns the V4L2 / AVFoundation / DirectShow handle. Inference (MediaPipe Pose, FaceMesh) runs in-process. Only the state — `{presence, face_yaw, blink_rate, n_faces, ts}` — is published. The `brain.input.camera` topic is tagged `private`; Membrane refuses to forward it to peer hosts even under Federation.

2. **No persistence of raw frames.** Ring buffer is RAM-only, capped at 1 second for inference smoothing, never spilled. State persists to `~/.orion/empathy/state.jsonl` with 30-day TTL; older state is summarized to daily aggregates (mean fatigue, peak stress, focused minutes), raw timeseries discarded.

3. **Hardware vetoes are inviolable.** Physical privacy shutter, hardware LED, tape over the lens — Orion never overrides any of them.

4. **Multi-face triggers a hard mode switch.** When `n_faces ≥ 2` for ≥3 s, Empathy publishes `co_present = true` and all private-tagged outbound is rerouted to a private surface (locked-screen iMessage) or deferred. This is the discretion test the "Orion is for you, not on you" thesis sits on.

5. **Encryption at rest, even for state.** `~/.orion/empathy/` uses the same key as `.env.secrets`. State is not transcripts but it is a behavioral profile, and behavioral profiles are exfiltration targets.

Kinect-style skeleton tracking (depth/stereo) would add: gross-motion energy, seated vs standing, lean toward/away from screen. Depth is also less identity-revealing — depth maps don't leak faces. If the arriving camera is RealSense or Kinect, prioritize skeleton over face metrics; the privacy/utility ratio is strictly better.

---

## 6. Affective computing — what the literature actually offers

The field predates the AI-affect hype cycle; the prior art is more cautionary than enabling.

**Picard, *Affective Computing* (MIT Press 1997)** founded the field and named the right risk: systems that *display* affect are not systems that *have* affect, and conflating the two corrodes trust the moment the display is wrong. Picard's primitives — sense, recognize, respond, do *not* mimic — match the architecture above.

**Scherer's Component Process Model (2005)** decomposes emotion into five components (cognitive appraisal, physiological symptoms, expression, motivation, subjective feeling). The theory of why naive emotion-detection fails — observing one component and emitting an emotion label has skipped four. Reinforces Section 2.6.

**Ekman FACS / basic emotions** is the most-cited and most-contested framework. Action-unit decomposition (AU1, AU12) is mechanically real; the mapping from AUs to discrete emotions is what Barrett's constructionist program has spent twenty years dismantling. The 2019 meta-analysis (Barrett, Adolphs, Marsella, Martinez, Pollak) found scant evidence that specific facial movements reliably map to specific emotions across cultures. **Use AUs as low-level features, never as evidence for an emotion label.**

**Stress from typing biometrics** is the strongest recent literature. Vizer/Zhou/Sears (*IJHCS* 2009) detected cognitive/physical stress from free-text rhythms; Sağbaş et al. (2020) extended to smartphone touch; Epp/Lippold/Mandryk (CHI 2011) classified five emotional states from keystrokes at ~80%. Cost-of-being-wrong is bounded (graded state, not label) and SNR is well-characterized.

**Reusable open source:** OpenFace 2.0 (BSD, on-device AUs + head pose + gaze); Py-Feat (Python wrapper); MediaPipe (pose/face-mesh/blink — already in the stack); VADER + NRC-Lex for text sentiment; librosa + opensmile (eGeMAPS) for voice arousal.

Deliberate omission: **no transformer-based emotion classifier from a Hugging Face card.** Accuracy claims are inflated by train/test domain overlap. The failure mode is "Orion thinks I'm angry" being right (creepy) or wrong (insulting). For a one-user system, being wrong once costs more than being correct ten times.

---

## 7. Recommended architecture

One path. No phase-1.5.

`orion_empathy.py` — a Plexus service that owns the user-state vector. It:
- Subscribes to `brain.input.text`, `brain.input.timing`, `brain.input.audio`, `brain.input.camera`.
- Maintains an in-memory rolling state vector at 1 Hz: `{focus, fatigue, stress, availability, co_present, ts, confidence}`.
- Persists state at 1-min resolution to `~/.orion/empathy/state.jsonl`, daily-summarized after 30 days.
- Publishes `brain.user.state` on any transition (delta on any axis).
- Exposes synchronous `empathy.evaluate(intent) → Decision` (Section 4) over a local UNIX socket — reach/executive call it inline without a NATS round-trip.
- Publishes `brain.empathy.decision` for every evaluate call (audit).
- Refuses in code to return `cancel`. Only send/downgrade/defer/reframe.

Reach wires in at `_drain_loop` before `_choose_channel`. Executive wires in at `narrate_failure` proposal construction. Will already has a `context_fit` factor in `_utility`; the new path replaces `last_user_inbound_age_sec` with `empathy.state().availability + focus`.

**Three named risks:**
- **Calibration drift.** First two weeks of baselines are noisy. Confidence starts low and rises with data; reach/executive respect it (low-confidence = ignored, fall back to existing heuristics). Risk: unusual first-fortnight trains the wrong model.
- **The dark-room failure (Section 3).** Mitigated by "never cancel, only downgrade" — but enforced in tests, not policy. Every release runs a regression where a synthetic stress=0.9 user gets an emergency-priority alert; the test fails if the alert is not delivered within SLA.
- **Camera-as-spine.** If text-and-timing isn't shipped first, the whole layer becomes camera-dependent — gating Empathy on a hardware install most users never do. Ship text-and-timing first.

---

## 8. Critique of this recommendation

**Where it becomes creepy:** the moment Empathy reports a label the user did not ask for, and the label is about *them* rather than about *Orion's intended next action*. "You've been at this four hours, want me to defer the deploy alert?" is helpful. "I've classified you as moderately stressed (0.72)" is profiling. The line is whether Empathy's output is served back as a tool, or consumed silently to gate behavior. The architecture defaults to the latter; the former is opt-in.

**The audit problem.** A user must be able to ask *what does Empathy think of me right now?* and get the literal state vector plus recent decisions Empathy made on it. Without this, Empathy is a hidden judge — the dynamic that made the 2010s social-feed algorithms odious. Implement `orion_empathy.explain()` as a first-class MCP tool from day one. The "Orion is for you" thesis dies the day the user finds Empathy gating things on a guess they couldn't see.

**Profiling vs noticing.** Noticing is bounded in time and tied to action: "heads-down two hours, water?" Profiling is unbounded and abstract: "your 90-day stress trend suggests…" Empathy stores timeseries because aggregates are useful for baselines. It must never *output* aggregates as characterization. The daily summary is Orion's notes on Orion's calibration, not Orion's diagnosis of the user. Subject vs audience.

**The hardest case: when the user asks Empathy to lie.** "Orion, stop noticing my stress." (a) Honor it — Empathy stops publishing stress, including to its own gating layer. (b) Honor as display-only — keep inferring, keep gating, never surface. The framework above defaults to (a). Treat (b) as paternalism even when it produces better outcomes on average. The empathic AI that overrides "leave me alone" is no longer empathic; it's an opinion holder.

**Where this could still go wrong:** if Empathy becomes the lens every other organ sees the user through, a bias in the lens is invisible. Mitigation: audit trail. Deeper mitigation: keep Empathy small (one service, one state vector, under 800 lines) so the lens is *inspectable*, not a learned representation no one can read.

---

## References

- Baltrušaitis, T., Robinson, P., & Morency, L.-P. (2016). OpenFace: an open source facial behavior analysis toolkit. *IEEE WACV.*
- Barrett, L. F. (2017). *How Emotions Are Made.* Houghton Mifflin Harcourt.
- Barrett, L. F., Adolphs, R., Marsella, S., Martinez, A. M., & Pollak, S. D. (2019). Emotional expressions reconsidered. *Psychological Science in the Public Interest,* 20(1), 1–68.
- Bentivoglio, A. R., et al. (1997). Analysis of blink rate patterns in normal subjects. *Movement Disorders,* 12(6), 1028–1034.
- Bruineberg, J., Kiverstein, J., & Rietveld, E. (2018). The anticipating brain is not a scientist. *Synthese,* 195(6), 2417–2444.
- Ekman, P., & Friesen, W. V. (1978). *Facial Action Coding System.* Consulting Psychologists Press.
- Epp, C., Lippold, M., & Mandryk, R. L. (2011). Identifying emotional states using keystroke dynamics. *CHI '11.*
- Hutto, C. J., & Gilbert, E. (2014). VADER: a parsimonious rule-based model for sentiment analysis. *ICWSM.*
- Mark, G., Gudith, D., & Klocke, U. (2008). The cost of interrupted work: more speed and stress. *CHI '08.*
- Mohammad, S. M. (2018). *NRC Affect Intensity Lexicon.*
- Picard, R. W. (1997). *Affective Computing.* MIT Press.
- Sağbaş, E. A., Korukoglu, S., & Balli, S. (2020). Stress detection via keyboard typing behaviors. *Journal of Medical Systems,* 44(4), 68.
- Scherer, K. R. (2005). What are emotions? And how can they be measured? *Social Science Information,* 44(4), 695–729.
- Vizer, L. M., Zhou, L., & Sears, A. (2009). Automated stress detection using keystroke and linguistic features. *International Journal of Human-Computer Studies,* 67(10), 870–886.

---

*Empathy filed 2026-05-16. Companion to `consciousness-research.md` and `consciousness-research-v2.md`. The brain proposes. Empathy gates. The user owns the brake.*
