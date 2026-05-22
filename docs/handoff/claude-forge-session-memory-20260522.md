# CLAUDE-FORGE FULL SESSION MEMORY — through 2026-05-22

The complete working memory of the FORGE-builder Claude session (builder mode,
NOT brain-wired). Read this to resume with full context after a compaction.
Supersedes `claude-forge-session-resume-20260520.md`.

---

## 0. WHO / WHERE / RULES
- User: **James England — the creator. Address as "sir."** (The old `USER.md`
  said "John / coach / ATLAS" — all wrong data; corrected this session.)
- FORGE-Claude = builder mode, NOT fueled by the orion-brain MCP (founder rule).
  Codex + Gemini on FORGE ARE brain-wired (MCP → Desktop repo).
- master HEAD at last write: **`37ab7e6`**. FORGE = COMMAND = Pi all on it.
- SSH from the road: home LAN (10.0.0.x) fails when traveling — use Tailscale
  aliases (`command-ts`) or tailnet IPs (Pi `homeland@100.90.248.69`).
- **Production USB** = `E:\.orion-system`, a git repo, **reference mirror only**,
  now on COMMAND. NOTHING points a live brain at it. Live brain = `~/.orion/brain`.

## 1. DESIGN LAW (ratified — apply to every layer) — docs/architecture/design-law.md
1. **Confirm before acting** (re-probe; a missed beat ≠ an outage).
2. **Act at the recoverable moment, not the dramatic one** (you can't restart a
   dead host; act on its *return*).
3. **Reuse the deliberative core** (route fixes through the executive's
   permission-gating + ledger; inherit safety + learning for free).

## 2. WHAT WAS DONE (this session, chronological-ish)
**Brain repair / hardening**
- Fixed dead `/ask` (half-finished rename: server→orion_brain, brain→orion_memory).
- Relocated canonical brain + identity + chronos OFF the TCC-walled
  `/Volumes/AtlasVault` into real `~/.orion/*` (killed a 3×-recurring failure class).
- **Recurring-issue final fix (5-22):** `deterministic`'s plist pinned
  `ORION_GRAPH_PATH` to AtlasVault (a *different* env var than chronos's) — repointed
  to home. That was the "we keep seeing this" TCC error.
- Fuel cascade now falls through on rate-limit/error (no raw error leaks).
- `EMAIL_TOOL` defined (action-word messages were 500-ing).
- Vector layer (qdrant) made OPTIONAL → graph-only brain runs offline.
- Identity corrected to James / sir / Orion.

**Fuel independence**
- Found Codex+Gemini on COMMAND (`~/.npm-global/bin`, off the launchd PATH) →
  added to brain PATH. Cascade: claude → codex → gemini → ollama. **API-key fuel
  (AnthropicAPIFuel) retired** (founder rule: never API keys).

**The 4-rung ladder (built, deployed, verified)**
1. `orion_taskspine.py` — durable working memory; task survives MODEL death.
2. `orion_coherence_probe.py` + `orion_local_chat.py` (`orion local`) + qdrant-optional.
3. `orion_consolidate.py` — graph curation (archive-not-delete), wired into nightly `orion_dream`.
4. `orion_task_gossip.py` + ownership leasing — task survives HOST death (proven COMMAND→Pi live).

**Wiring / ops**
- Claude brain wired into COMMAND ✓ + Pi ✓ (FORGE stays the lone builder seat).
- Ollama paths collapsed into ONE brain-backed path (`orion local`); broken auto-branded `orion-*` models avoided (default to clean base like qwen3).
- `orion_updater` deployed reports-only; drift monitored.
- Obsidian vault (founder's personal): newest HTMLs + Atlas Command Center + all devices + cyberdeck.

**Mesh layer (server-ecosystem unification)**
- `orion_mesh.py` — location-aware device monitor (LAN-first, Tailscale-fallback);
  `orion mesh` mode; offline-alert monitor on COMMAND. Device map (5 devices incl.
  cyberdeck Pi + ARSENAL) at `~/.orion/mesh/devices.json` (per-instance, not in repo).
- README now leads with the server/mesh value prop + a Mesh Mode section.
- **iMessage spam fixed (3 fixes):** debounce (3 consecutive misses before
  "offline"); mesh-recovery no longer alerts the executive on offline (only on
  return); `reach` refuses bare "Notice: <kind>" stubs (killed the `primary_user`
  misroute). One real outage → one text; a blip → zero.

**First agentic loop (the headline)**
- `orion_mesh_recovery.py` — observe→track→decide→act→learn. On a device drop:
  confirm (re-probe), open a durable `orion_taskspine` task; on RETURN, feed the
  executive (gated) to restore the device's Orion presence; `orion_dream` learns
  the recovery from the decision ledger. Live on COMMAND.

## 3. WHAT WE ARE WORKING ON NOW (resume here)
**`mesh_restore` execution rung + metacognition Phase 2** (the agreed next build):
- A `mesh_restore` remedy executed **over the task spine**: resolve the returned
  device's transport (LAN/Tailscale), SSH in, restart its Orion services /
  re-confirm MCP / rejoin gossip — permission-gated, checkpointed (resumes on a
  flaky network). This makes the recovery loop's "act" rung REAL (today it's
  gated to local `launchctl_reload` + `investigate_only`).
- **Metacognition Phase 2**: gate those autonomous actions on calibrated
  confidence — auto when sure, ask when not. Makes cross-host self-repair
  *trustworthy*. Turns "Orion noticed + proposed" into "Orion noticed, fixed it,
  and learned the fix."

## 4. WHAT'S PLANNED (frontier — 4 research agents dispatched 2026-05-22)
Studying the parts of the brain AFTER the current work; memos landing in docs/architecture/:
- `frontier-brain-as-signal-v2.md` — brain state over LoRa/BLE/radio (off-grid, no host).
- `frontier-continual-learning.md` — genuine learning vs accumulation (weight-free).
- `frontier-autonomous-volition.md` — bounded multi-day autonomous goal pursuit.
- `frontier-self-model.md` — calibrated self-model / introspection past metacog Phase 2.

## 5. KEY STATE / SERVICES (COMMAND, the always-on hub)
- 39 launchd `com.orion.*` services live. New ones this session: `updater`,
  `task-gossip`, `mesh-monitor`, `mesh-recovery` (+ Pi runs `task-gossip` via systemd).
- Brain: `/ask` → claude-cli, graph 1324 nodes, home-dir, writable.
- All hosts cohesive at master; 68 modules parse; no orphaned imports
  (orion_brain_v6 / orion_memory_v2 / AnthropicAPIFuel all gone).

## 6. OPEN ITEMS / FLAGS
- **OUTPOST** (`shannonengland@10.0.0.219` / ts `100.112.80.14`): online but SSH
  needs FORGE's key authorized (`ssh-ed25519 AAAAC3...sidG7 forge-to-command`) →
  then wire its CLIs + set up VNC on atlascommand.vip (no noVNC container exists yet).
- USB reference mirror on COMMAND should `git pull` to current master when mounted.
- 2 cosmetic `server_data/orion-brain` display-strings in orion_obsidian_export.py.
- Broken auto-branded `orion-*` Ollama models (gibberish) — regenerate or drop.
