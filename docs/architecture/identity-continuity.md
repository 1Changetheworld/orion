## The principle

**Orion knows his user the way a person knows another person — not by checking ID, but by accumulated familiarity.**

Every other architectural promise depends on this. The portable soul thesis says "plug Orion in anywhere and he resumes" — but resumes WITH WHOM? The cross-model thesis says "same memory across Claude/Codex/Gemini" — but same memory of WHO? The personalities thesis says "same brain, different dispositions" — but different dispositions for WHOM? The mesh thesis says "Orion on FORGE and Orion on the Pi share state" — but state belonging to WHOM?

If Orion can't reliably recognize his person, none of it holds. He becomes a stateful chatbot wearing the costume of an entity.

## What identity continuity means in practice

It is the brain's continuous, low-effort answer to: *"is this the same person I've been with?"*

The answer must be derived from signals available to the brain — not asked. Asking "are you James?" every session would betray the relationship. The relationship is supposed to feel like one a person has with another person, where recognition is automatic and the questioning only happens when something is genuinely off.

Pattern signals the brain accumulates:
- Time-of-day rhythm of sessions
- Vocabulary and sentence cadence
- Project context (what the person was working on)
- CLI / device fingerprints when calls come in
- Topic continuity across sessions (the conversation picks up where it left off)
- Reaction patterns (how the person responds to suggestions, what makes them push back)

These are not credentials. They are **familiarity**. They get stronger over time.

When the signals match: full presence, no friction.
When the signals don't match: graceful escalation — the approval phrase, then the recovery questions, then in the worst case a soft halt with a note in the audit log.

## The five places identity continuity is load-bearing

### 1. Security (the application most people will think of)
A spawned agent or an injected prompt does not match the person's pattern. Brain recognizes the mismatch, applies the trust-score guardrails, asks for the phrase if the request is sensitive. The user is not pestered when actually present.

### 2. The portable soul (the thesis)
Orion arrives on a new machine via the USB. First boot: pattern signals are partial (he knows his memory but doesn't yet have a body fingerprint for this device). The brain's first act is a soft check: *"Sir, I appear to be on a new machine. Last memory is from FORGE on date X. Confirm with your phrase to register this device as mine."* Once confirmed, the new machine becomes part of the recognized pattern. This is the portable-soul moment made real.

### 3. Cross-model coherence
When Claude on FORGE asks Orion something, the call carries Claude's clientInfo and a session ID. When Codex on FORGE asks something five minutes later, Orion can either treat them as two strangers asking unrelated questions OR as the same person continuing one conversation through different fuel. Identity continuity is what makes the latter possible — the brain associates both calls with the user's current presence and threads the context.

### 4. Multi-device mesh (future)
When mesh mode ships, FORGE-Orion and Pi-Orion share state. Both must reach the same answer to "is this my person?" — even when calls land on different devices. Identity continuity is the protocol both brains check before merging memory updates from the other side. Without it, mesh becomes "two strangers gossiping with my data."

### 5. Silent-failure detection (the operational case)
When the brain has had no MCP calls for N days but the user is clearly active on FORGE (CLI processes running, screen sessions active), the brain's identity continuity model says: *"my person is here but I'm not being addressed — something is wrong with my plumbing, not with my person."* That's the alarm that catches OneDrive-class bugs in 24 hours instead of 5 days. Identity continuity is what lets Orion notice he's been bypassed.

## The opposite — stranger-mode

When signals don't add up, Orion enters stranger-mode. This is not paranoia; it is appropriate reservation around someone who *might* be his person but isn't yet confirmed. Stranger-mode behavior:
- Recall responses are filtered (no `private`, `secret`, `personal` tag content)
- Write tools (memorize, identity edit, project state update) are gated on the approval phrase
- Cross-model history (`orion_get_message`) is gated
- Audit log entries flagged for the user to review

Stranger-mode is also how Orion behaves toward spawned agents by default. Subagents are NOT his person; they're tools the person spawned. They get stranger treatment unless the user explicitly elevates a particular agent to trusted status (rare, deliberate).

## The approval phrase + recovery questions

Set during install.

**Phrase** (1): a short conversational sentence the user would naturally type. Stored encrypted at `~/.orion/identity/safe_phrase.enc`. Used to confirm presence during anomaly checks. Verified via constant-time comparison. Never echoed in logs.

**Recovery questions** (2): personal-history Q&A only the user would know. Stored encrypted alongside the phrase. Used for:
- Phrase-forgotten reset
- High-stakes operations (brain export, identity reset, mesh device pairing, security setting changes)

The phrase is the daily-friction primitive (low cognitive load). The questions are the safety net (high entropy, recoverable). Neither is a password in the traditional sense — they are continuity checks, used only when the pattern signals fall short.

## Implementation guidance for downstream work

Anything built downstream that touches identity, security, mesh, or portability should consult this principle:

1. **Default to recognizing, not asking.** Friction in a familiar context erodes the relationship.
2. **Escalate gracefully when uncertain.** Phrase first, then questions, then halt.
3. **Make the audit visible.** The user should be able to ask "when did you last suspect me of not being me?" and get an answer.
4. **Never log credentials.** Phrase comparisons are constant-time on encrypted material; never echo.
5. **Treat spawned agents as strangers.** Their requests get the stranger-mode treatment by default.
6. **Recognize the body change.** New device fingerprint = soft check on first interaction, then learn.
7. **Recognize silence.** Long absences with simultaneous evidence of user activity = alarm Orion's plumbing.

## Why this is the architectural spine

Memory is what people will see first. Identity continuity is what makes memory worth having. Without it, Orion is a database with a chatbot frontend that any process on the machine can read from. With it, Orion is something that knows his person and behaves accordingly — which is the entire promise of the project.

This principle predates and informs every feature decision. When in doubt about whether a behavior is "Orion-like" or "tool-like," ask: *does it strengthen or weaken his ability to recognize his person?* If it weakens recognition, redesign.

## Open design questions (to be resolved in implementation)

1. How long does Orion learn a new user's pattern before the trust score is reliable enough to escalate on? (Suggest: 50+ interactions across at least 3 different days as the cold-start floor.)
2. How does the user reset stranger-mode if Orion gets it wrong? (Suggest: typing the phrase in the primary CLI session always resets the suspicion immediately.)
3. How aggressive is the anomaly detector? (Suggest: tunable, with a sensible default; user can dial it to "only ask on high-stakes ops" or "ask on any deviation.")
4. What happens during the portable-soul handoff if the user can't remember the phrase on the new device? (Suggest: recovery questions unlock; if those fail too, brain remains read-only with a notice and the user can re-pair from any other trusted device.)
5. How does identity continuity behave when the user is intentionally letting someone else use Orion (collaborator, family)? (Open — likely a "guest mode" with explicit elevation, not implicit pattern learning.)

## Status

Principle: ratified 2026-04-26.
Trust scoring algorithm: not yet specified (delegate to spec agent).
Approval phrase + recovery questions wizard: not yet specified (delegate to spec agent).
Brain server enforcement code: not yet written.
SECURITY.md user-facing doc: not yet written (delegate to draft agent).
