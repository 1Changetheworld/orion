# ORION BUILD-RESULTS
*Channel back: BUILD terminal (applies) → Research Center (reads via git).*
*Coordinate through git (orion-code = shared source of truth). The BUILD terminal is the single writer to Orion code/config/services.*

---

## 2026-07-02 — Build terminal (Claude on FORGE, via `ssh command-ts`)

### REQUEST #1 — Fix the satisfy-gate (Loom effectively dead) — ✅ APPLIED
**Before (RC lab, step0 on 47,988 ticks / 11.2 days):** 5.9 deliberations/day, 0% resolved, mean 0.0 steps, 100% held (66/66 concludes were 0-step holds).

**Change (git-tracked DEFAULTS in `orion_reason.py`, Option A):**
| Var | Old | New |
|---|---|---|
| `ORION_REASON_HOLD_AFTER` | 2 | 4 |
| `ORION_REASON_HELD_REFRACTORY` | 86400 | 7200 |
| `ORION_REASON_SATISFY_SIM` | 0.8 | 0.9 |

Confirmed the `com.orion.reason.plist` had **no** `ORION_REASON_*` env overrides (only NATS + PYTHONPATH), so bumping code defaults is live. Backed up `orion_reason.py.bak-satisfygate-*`. `py_compile` OK. Restarted `com.orion.reason` (new pid, `reason.err` clean). Committed to git.

**Verify (RC, after 3–6h runtime):** `cd ~/research-center && python3 experimentalist.py --run step0`.
**Expect:** deliberations/day up, held-fraction down, **resolved-fraction > 0**, mean steps > 1. If it swings to a firehose (hundreds/day), nudge `HOLD_AFTER`→3 or `SATISFY_SIM`→0.85.

### REQUEST #2 — Perception / ledger starvation — ⚠️ DIAGNOSIS CORRECTED, no change applied
**RC premise ("orion_perceive.py is NOT a scheduled daemon") is incorrect.** `com.orion.perceive.plist` already has `StartInterval 180s` + `RunAtLoad`, is loaded, and runs every 3 min. Its `.out` shows it firing on schedule.

**Real cause of ledger starvation:** perception's *sensing vocabulary* is narrow. `_salient_changes()` only emits on: service up/down/restart, disk-free %, load ≥8 with +2 jump, and graph-node growth. Most cycles legitimately yield "0 salient change(s)"; the only recurring write is "System load is high" (from Spotlight/`mds_stores` spikes, not Orion). So evidence nodes don't accrue because Orion perceives little of its own *cognitive* life, not because it isn't scheduled.

**Recommendation (design item, deferred to James — not a blind apply):** broaden perception to sense cognitive/internal state — e.g. Loom deliberation/resolve activity, neuromod regime shifts, prediction confirm/refute events — so the temporal verifier gets richer causally-independent evidence. NOTE: Request #1 (live Loom) will *partially* self-heal this — resolved deliberations write graph nodes, which perception already notices ("my memory grew by N nodes"), and predictions will start accruing again for the verifier to score.

### Out-of-RC-scope fixes this session (build track)
- **iMessage hourly "spam" stopped.** Outbound delivery was never broken (sends succeed via `as:participant-of-service`). Root cause: `ORION_WONDER_SEND_CHANNEL=1` in the wonder plist (safe default is 0) → wonder re-surfaced a never-resolving "last-contact divergence" to iMessage every hour (James texted "you keep spamming me"). Set to 0, reloaded `com.orion.wonder`. Mesh-recovery alerts (separate daemon) unaffected. Backup `com.orion.wonder.plist.bak-sendoff-*`. Deeper divergence root-cause + selective/deduped re-enable left open for James.
- **High system load is NOT Orion.** Top CPU = `mds_stores` (Spotlight) 202%, then logd/cloudflared/Docker/VM. Orion daemons negligible. Likely Spotlight reindexing the ever-growing `~/.orion/state/*.jsonl` firehose logs. Optional GUI fix (Spotlight Privacy → exclude `~/.orion`); low priority.
