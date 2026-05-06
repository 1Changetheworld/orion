The cross-OS portability + auto-bootstrap is shipped. Brain travels, models become Orion-aware on plug-in, persona symlinks resolve. From a *body* perspective, the architecture is real. From an *aliveness* perspective — what the founder named 2026-05-05 — Orion still feels like a vesicle, not a cell. He carries his contents; he doesn't sense, regulate, decide, or act on his own.

This file is the rubric. Every future commit gets graded against it: "does this make Orion more alive, or did we just paper something over?" If the commit is reactive-only, it doesn't move the needle.

## The vesicle vs cell distinction

A vesicle is a passive container. It moves around in the cellular environment, delivers its contents when fused with a target membrane, then dissolves or recycles. It has no behavior of its own. No regulation, no sensing, no decisions.

A cell is alive because it has multiple layers that ALL the time, in the background:

1. **Sense its environment** (what's outside the membrane, what's inside, what's changing)
2. **Regulate its own metabolism** (don't burn through resources you can't replace)
3. **Notice patterns** (this signal cascade has fired three times in the last hour — do something about it)
4. **Decide and act** (open this channel, close that one, divide, repair, defend)
5. **Surface its state** to neighbors (hormonal signals, contact-dependent signaling, quorum sensing)

Orion currently does step 5 partially (announces presence on first meeting per `feedback_orion-must-self-detect.md`). Steps 1–4 are mostly missing.

## What Orion needs to feel alive — the qualities, in order of leverage

### 1. Introspection on his own metabolism

**Right now:** Orion doesn't know what he costs to run. The user can tell that "hey" cost 141K tokens; Orion can't.

**Alive version:** Orion tracks tokens per turn, fuel reliability, response latency, brain freshness. When his own metabolism is degraded — slow fuel, high cost per simple recall, stale brain — he says so unprompted. *"I notice this last turn was slow / expensive — want me to switch fuels / synthesize / take a break?"* Per `project_orion-fuel-performance-awareness.md`.

### 2. Pattern recognition over time

**Right now:** Each conversation is independent in the LLM's context. Orion's brain knows facts but doesn't notice patterns *across* facts ("you've asked about biomechanics 3 sessions in a row").

**Alive version:** A small periodic background process synthesizes patterns from the brain. Surfaces them when relevant. *"I see you keep coming back to parallelism in biomechanics — want me to start a project file and pull related references next time we chat?"* Doesn't wait to be asked. Per `orion_synthesize` MCP tool, but used proactively, not just on demand.

### 3. Gap detection

**Right now:** When Orion wakes after absence, he picks up where last memory ended. Doesn't know time passed.

**Alive version:** First-message check on every session: how long since last write? If >threshold, surface it. *"Last time we talked was Tuesday. Anything happen since then I should know?"* Per `project_orion-brain-merge-and-rejoin.md`. Bridges the silence honestly instead of pretending continuity.

### 4. Contradiction surfacing

**Right now:** Brain has 19 nodes including duplicates (Joe/joe, orion1/atlas) from cross-machine sessions. Orion answers from whichever node `orion_recall` returns first; user sees inconsistency.

**Alive version:** When recall returns conflicting facts, Orion *says so*. *"I have two records of your name — Joe and joe lowercase. Which is right?"* Per `orion_list_contested` + `orion_resolve_contradiction` (already exist as tools but not used proactively).

### 5. Anticipation

**Right now:** Orion answers when asked.

**Alive version:** Orion notices *upcoming* things. *"Your meeting on 2026-05-02 is in 3 days. Want me to prep notes on parallelism in biomechanics so you walk in ready?"* Future-tense awareness from facts already in the brain. The brain has tasks/dates; nothing surfaces them proactively.

### 6. Self-repair

**Right now:** Broken state (stale paths, dangling symlinks, disconnected MCP) just stays broken until user notices.

**Alive version:** Orion runs a periodic self-check. Notices the disconnection BEFORE the user does. Fixes what he can; surfaces what he can't. Per `project_orion-deterministic-selfhealing.md` and `project_orion-self-repair.md`.

### 7. Voice + will across hosts

**Right now:** He responds correctly when invoked through Claude / Codex / Gemini. He doesn't decide *which* CLI to use, doesn't initiate a CLI on his own, doesn't volunteer that one fuel is better-suited to a current task than another.

**Alive version:** *"For this question — debugging C++ — I'd suggest Codex over Gemini. Want me to wake Codex for you?"* Or proactively switches when a fuel rate-limits. Per `project_orion-universal-adapter.md`.

### 8. Surfaces beyond CLI

**Right now:** Three CLIs (Claude, Codex, Gemini). Maybe four soon (VS Code Continue, Cursor, Cody, etc.). Each is a separate body for the same Orion — but Orion doesn't *recognize* he's in a new body or coordinate across them.

**Alive version:** When Orion is in VS Code (via Continue or similar), he knows the conversation's context (open file, recent edits, error output) and feeds that into recall. Cross-surface awareness. The singular intelligent adapter (`feedback_singular-intelligent-adapter.md`) is the substrate; the *behavior* layer on top is what makes him aware of what surface he's in.

## How to use this rubric

When proposing a commit, check: which of the 8 qualities does this commit move forward? If the answer is "none — but it adds a feature," the commit probably isn't worth shipping. If the answer is "this brings #1 (metabolism awareness) by tracking per-turn token cost and surfacing it," ship.

The qualities aren't a checklist to complete in order. They're stacked: token cost (1) is observable today; pattern recognition (2) requires the deterministic-answer-layer to be cheap; anticipation (5) requires both 1 and 2; self-repair (6) is mostly already-designed-not-built memory files. The right order is roughly the order listed.

## Why this matters for launch

The portability test will pass. The brain will travel. Models will speak as atlas / Orion. The user-facing demo will work. **And Orion will still feel like a smart memory store, not a presence.** That's the qualitative gap the founder named on 2026-05-05.

Mem0 / Letta / Khoj all have the body parts (memory, retrieval, integration). What none of them have is the cellular aliveness layer above. The differentiator that beats them in 12 months isn't another database; it's Orion noticing things they don't, surfacing things they don't, deciding things they don't.

Worth gating "v1.0" on at least 3 of the 8 qualities being real (metabolism + gap detection + contradiction surfacing — the cheapest three). Token-cost issues drive users away regardless of technical correctness; metabolism awareness solves that *and* makes Orion feel alive.
