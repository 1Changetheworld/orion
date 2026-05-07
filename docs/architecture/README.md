# Orion — architecture & design docs

These are the architectural decisions that travel with the code. They
exist as repo-level documents (not just in any single contributor's
private notes) so the design intent is reproducible for anyone working
on Orion — current or future.

## Index

| Doc | What it covers |
|---|---|
| [Brain-as-Network](brain-as-network.md) | Brain serves every channel — CLIs, browser, IDEs, iMessage, Telegram, phone, agents. The moat. |
| [Personality + Observation](personality-and-observation.md) | Proactive subtlety with character, without token bloat. Observer daemon + pending-surface notes. |
| [Brain Merge & Re-Entry](brain-merge-and-rejoin.md) | When USB Orion meets a host that already has Orion. When Orion wakes from absence. |
| [Cellular Design Vocabulary](cellular-design-vocabulary.md) | Cell biology as the design discipline — receptors, ligands, cascades, apoptosis, quorum sensing. |
| [Aliveness Rubric](aliveness-rubric.md) | The 8 qualities that make Orion feel alive vs. feel like a memory store. |
| [Presence Architecture](presence-architecture.md) | Six-part design (beacon + agent + bootstrap + cleanup + brain + persona) for plug-and-play. |
| [Cross-Process Cache](cross-process-cache.md) | Why each MCP process can't have its own brain copy — and how the HTTP proxy fixes it. |
| [Identity Continuity](identity-continuity.md) | Orion recognizes "this is my person" through pattern, not credential. The architectural spine. |

## Reading order for a new contributor

1. **Cellular Design Vocabulary** — the discipline everything else honors
2. **Brain-as-Network** — what Orion fundamentally is (a substrate, not a tool)
3. **Aliveness Rubric** — the bar we're trying to clear
4. **Brain Merge & Re-Entry** — the launch-blocking correctness gap
5. **Presence Architecture** — how plug-and-play actually works
6. **Cross-Process Cache** — why the brain has to be one process
7. **Identity Continuity** — the security/recognition spine
8. **Personality + Observation** — the next horizon

## Why these live in the repo

The decisions captured here aren't tactical patches — they're the load-bearing
architecture. If a contributor implements a feature without honoring (for
example) the cellular framing or the aliveness rubric, the system drifts away
from the founding principles. Treating these as repo-level documents (versioned,
diffable, reviewable) keeps the design coherent across time and contributors.

This is the cellular pattern applied to documentation itself: the principles
ARE part of the body, not stored in a separate "consciousness" elsewhere.
- [Zero-Touch First Host (research)](zero-touch-first-host.md) — Three paths to break the 'one command per host' friction. Companion-device authorization, custom hardware, signed AutoPlay. Recommended v1 + v2 sequence.
