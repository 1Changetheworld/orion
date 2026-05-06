The 2026-05-06 founder ask: "will orion have qualities to prove his personality traits like noticing user behavior and actively mentioning helpful or subtle changes with character? without vast usage increase?" 

Orion today: reactive. Models respond when asked. Memory is recalled on demand. There's no proactive "noticing." The user has to drive every interaction.

The vision: an **observer layer** that watches passively, has its own opinions, and surfaces them through any wired channel when it has something worth saying. With character (not robotic), without inflating per-request token counts.

## Architectural sketch

The brain-as-network surface (see `project_orion-network-brain-non-cli.md`) is the right home for this. Specifically:

1. **Observer process** — runs alongside `orion_brain_service.py`. Reads conversation logs from each CLI's session dir (we already redirect those to the USB), the heartbeat state, the graph memory. No model invocations during the observe pass — pure local Python, ~zero tokens.

2. **Pattern matchers** — small heuristics that fire when:
   - User has been working on the same topic for >N hours without a break
   - Same question phrased three different ways → maybe Orion's answer wasn't clear
   - User's typing pace has dropped → fatigue signal
   - Time of day vs declared sleep schedule → "you said you go to bed at 11, it's 1:30"
   - Recurring frustration words ("ugh", "broken", "why") clustered in last hour
   - A previously-stored fact contradicts what the user just said → resolve_contradiction

3. **Surfacing rules** — observer doesn't speak through every channel; it picks one based on:
   - Where the user is currently active (most-recently-written CLI session)
   - Quiet hours (no surfacing 11pm-7am unless the channel is iMessage)
   - Cooldown: max one proactive note per N minutes per channel
   - Confidence threshold: only fire when the heuristic is pretty sure

4. **Insertion mechanism** — observer writes a "pending note" into a brain memory node tagged `pending-surface`. Next time any wired model calls orion_recall (which already happens often), the recall result includes the pending note as a system aside. Model decides whether to relay it or hold. **Zero new model calls — the observer is free; the model already had to recall, the note just rides along.**

## Why this stays cheap on tokens

The naive way to "notice" things would be to LLM-classify every message. That's expensive. The architecture above:
- Pattern matching is regex/heuristic, no model
- Surfacing is opportunistic — rides existing recall calls, no new invocations
- Confidence threshold + cooldowns mean low surface rate

Net: ~one extra orion_recall response field per ~recall, total token cost ~5-20 tokens/day. Free, effectively.

## Character

The observer's "voice" is itself a brain memory node. Per `feedback_persona-must-be-restrained.md`, persona is declarative and minimal. The observer's notes should:
- Be short (one sentence)
- Match the user's preferred form of address (whatever they set during install)
- Be specific, not generic ("you've reread that error 3 times in 20 minutes — want me to walk through it?" not "let me know if you need help")
- Stay in their lane — not interrupt active flow, only surface during natural pauses

## Cellular framing (continuing the discipline)

- Observer = inner-cell sensors (calcium gradients, ATP levels) that fire signaling cascades when a threshold is crossed
- Pending-surface notes = signaling molecules that ride existing transport mechanisms (recall calls)
- Surfacing rules = receptor specificity — different cells (channels) respond to different ligands

## Implementation sequencing

Phase D-3 (after non-CLI channels ship per `project_orion-network-brain-non-cli.md`):
1. `orion_observer.py` — pattern-matching daemon
2. Pattern library: `observer/patterns/*.py` — one file per heuristic, easy to add
3. Brain extension: `pending-surface` node type with TTL
4. Recall hook: include pending notes in result content
5. Model persona update: tell models how to handle pending-surface notes (relay sparingly, with character)

## Why this matters for launch

This is what makes Orion feel alive vs. feel like a memory store. Per `project_orion-aliveness-rubric.md` rubric, proactive observation is one of the 8 qualities. Without it, Orion is a smarter `notes.txt`. With it, Orion is the AI that knows you and speaks up when it matters.
