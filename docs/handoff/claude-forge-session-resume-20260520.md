# CLAUDE-FORGE SESSION RESUME — 2026-05-20

FORGE-builder Claude (builder mode, NOT brain-wired). This captures the
2026-05-19→20 working session: what was done, current state, what's next.

---

## RESUME PARAGRAPH

Over this session the FORGE-builder Claude took Orion from "looks alive but
isn't" to a genuinely model- and host-resilient brain. We found and fixed a
silently-dead `/ask` (a half-finished module rename), relocated the canonical
brain off the TCC-walled AtlasVault volume into home-dir storage (killing a
3×-recurring failure class), made the fuel cascade fail through on rate-limits
instead of leaking errors, corrected the identity (the user is **James, the
creator, addressed "sir"** — the old `USER.md` had wrong "John/coach/ATLAS"
data), and wired real peer-fuel independence on COMMAND (Codex+Gemini found and
added to the cascade; API-key fuel retired). We then built the four-rung ladder
toward intelligence that depends on no single model or machine: a **durable
task spine** (work survives a model dying), a **coherence probe + brain-backed
local-model path + optional vector layer** (full brain offline on local fuel),
**nightly graph consolidation** (archive-not-delete; 1474→1324), and **task
gossip** (work survives a *host* dying — proven live COMMAND→Pi). We wired the
Orion brain into Claude on COMMAND and Pi (FORGE-Claude stays the lone
builder-mode seat), collapsed all Ollama paths into the one brain-backed path
(no more bare-model gibberish), killed an iMessage double-send, and — at the
end — **fully separated the not-in-use production USB from the live brain**:
the USB is a pure reference mirror (moving to COMMAND), while the live brain
runs from home dirs + the Desktop repo on every host.

---

## WHAT WAS DONE (this session)

**Brain repair + hardening**
- Fixed dead `/ask` (`orion_server`→`orion_brain`, `orion_brain`→`orion_memory` imports)
- Relocated canonical brain + identity + chronos OFF `/Volumes/AtlasVault` → real `~/.orion/*` (TCC class dead)
- Fuel cascade: throttled/errored fuel returns None → falls through (no raw error to channels)
- `EMAIL_TOOL` defined (action-word messages were 500-ing)
- Identity: `USER.md` corrected to **James England / "sir" / Orion**
- Vector layer (qdrant) made OPTIONAL → graph-only brain runs offline

**Fuel independence (COMMAND)**
- Found Codex+Gemini at `~/.npm-global/bin` (off the launchd PATH) → added to brain PATH; cascade is now `claude→codex→gemini→ollama`
- Retired `AnthropicAPIFuel` from the cascade (no API keys)

**The 4-rung ladder (all built, pushed, verified)**
1. `orion_taskspine.py` — durable working memory (survives model death)
2. `orion_coherence_probe.py` + `orion_local_chat.py` (`orion local`) + qdrant-optional
3. `orion_consolidate.py` — graph curation, wired into nightly `orion_dream`
4. `orion_task_gossip.py` + ownership leasing — survives host death (proven COMMAND→Pi live)

**Wiring + ops**
- Claude brain wired on COMMAND ✓ and Pi ✓ (via `claude mcp add`)
- `orion_updater` deployed reports-only; COMMAND synced to master, drift-monitored
- Ollama menu collapsed into the brain-backed path; defaults to a clean base model
- iMessage double-text fixed (monitor was direct-send AND publishing to the subscriber)
- Obsidian vault: newest HTMLs + Atlas Command Center + all devices + cyberdeck (personal vault only)
- Docs: `orion-unified-brain.md` + `true-intelligence-frontier-research.md`

**USB / production separation (the closing move)**
- Production USB (`E:\.orion-system`) synced to master, then separated: Codex/Gemini MCP repointed from the USB → Desktop repo (`C:/Users/jeng1/Desktop/orion/orion-repo/orion_mcp_server.py`, forward-slash, valid TOML/JSON). USB-rooted brain processes stopped. USB → moving to COMMAND as a pure reference mirror.
- FORGE lid-close set to **Hibernate** (windows survive travel/battery death).

## CURRENT STATE

- **master HEAD:** `320b83d` (GitHub + USB mirror in sync at time of USB removal)
- **COMMAND + Pi:** on master; brains home-dir-local; Claude/Codex/Gemini fuel-independent
- **task-gossip:** live on COMMAND (launchd) + Pi (systemd --user); cross-host replication proven
- **Identity:** James / sir / Orion
- **USB:** separated, moving to COMMAND (reference only — nothing points at it)
- **FORGE-Claude:** builder mode (unwired) — the only no-brain seat, by rule

## WHAT'S NEXT

- **OUTPOST** (`shannonengland@10.0.0.219`, online): blocked on SSH key auth — add FORGE pubkey
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOfBZOU6vZ9ORvSv4KExWLsUlIUOxpzt5AFH11nsidG7 forge-to-command`
  to OUTPOST's `~/.ssh/authorized_keys`. Then: wire Claude/Codex/Gemini brain + set up VNC on `atlascommand.vip` (needs a noVNC container → `10.0.0.219:5900`; none exists yet).
- **Cross-host gossip soak** — let task-gossip run; confirm bidirectional + lease takeover on a real interrupted task.
- **Broken `orion-*` branded Ollama models** — they output gibberish (generic Modelfile over reasoning models); regenerate or drop.
- **When USB lands on COMMAND** — verify no COMMAND process points at it (reference only).
- Codex/Gemini on FORGE: relaunch a tab to respawn the MCP+brain from Desktop (auto-recovers).
