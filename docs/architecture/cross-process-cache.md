## The bug

Each AI CLI (Claude Code / Codex / Gemini) launches its OWN `orion_mcp_server.py` subprocess when it boots, with its own in-memory copy of `graph_memory.json`. When Claude's process calls `orion_memorize`, the write hits disk AND updates Claude's in-memory cache — but does NOT invalidate Codex's or Gemini's caches. Those processes are still running with the older snapshot they loaded at their boot time.

Symptom observed in the 2026-04-29 VM dog-food test: Claude wrote `favorite number 47` and `meeting in 3 days`. Gemini (started after the writes) recalled them. Codex (started before the writes) returned only the older wizard-seeded memories — never saw the new writes. The brain on disk had the new memories; Codex's process didn't.

## Why this matters

The cross-CLI memory thesis is the entire pitch. *"The memory IS the intelligence — any model that loads my memory becomes me."* If memory writes don't propagate across CLI processes in real time, the demo where you tell Claude something and ask Codex about it is unreliable — works only when CLIs were started in the right order. That's not a thesis we can ship.

## How to apply

Fix lives in `orion_brain_portable.py` (the brain core). Three options ranked by cost:

1. **Re-read graph from disk on every recall** — simplest, slow but consistent. Add `_load_from_disk()` at the start of `recall()`. File reads on a 3KB JSON are sub-millisecond.

2. **File-watcher invalidation** — each MCP process watches `graph_memory.json` mtime; if it changed since last read, reload before recall. Same effect, no per-recall I/O cost.

3. **Move to a real database** — SQLite or similar. True transactional consistency across processes. Bigger rewrite but solves the broader memory persistence problems too.

For the immediate fix: option 1 or 2. Option 3 is a future architecture decision tied to scaling the brain.

The ALSO-related discovered bug: Claude's `orion_memorize` calls said "stored" in the conversation but the memories never landed in `graph_memory.json`. Either the tool returned success without writing, or wrote to a different location. Investigate before claiming the cache fix is the only issue.
