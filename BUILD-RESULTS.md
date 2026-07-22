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

---

## 2026-07-22 — Build terminal (Claude on FORGE)

### LOOM REVIVAL — the dead-Loom root cause (RC "satisfy-gate" follow-up) — FIXED + PROVEN
The 07-02 gate loosening raised throughput (5.9->103 delib/day) but step0 stayed
100% HELD / 0 steps / 0 resolved for ~5 weeks. Root cause was NOT tuning: the hold
branch in `deliberate()` gated on `refire` (how many times a topic FIRED), so every
recurring topic hit a permanent 0-step hold — the Loom never took a single reasoning
step (the code did the OPPOSITE of its own "escalate, don't falsely re-resolve" comment).

FIX (orion_reason.py, committed 29c9015):
  - hold now gates on `delib_n` (GENUINE multi-step deliberations >= HOLD_AFTER) — a
    topic is held as "eternal" only after being truly thought-through and still returning
    (an EARNED hold), never merely for firing often.
  - re-firing topics skip the native-recall shortcut and ESCALATE into real deliberation,
    accumulating delib_n toward that earned hold.
  - _record_resolution tracks delib_n (deliberated when steps_used > 0).

PROOF: a re-fired topic (refire=9, delib_n=0) that OLD code held at 0 steps now runs a
real 6-step / 4-subquestion deliberation and RESOLVES (127s via Claude fuel). Its first
real conclusion in weeks self-diagnosed the monotony ("recursive self-analysis, zero state
change"). com.orion.reason restarted on the fix.

CAVEAT for the center: the reasoning ENGINE is revived, but topic DIET is still monotonous
(~10 recurring existential tensions). Input diversity (wonder/perception/conversation) is a
separate downstream lever; re-measure step0 in 24-48h (expect resolved-fraction > 0, mean
steps > 1).

### FUEL FAILOVER REFLEX (out-of-RC-scope) — FIXED + PROVEN (committed a9d41e3)
The cascade forwarded a strong CLI's "API Error: 401" as if it were an answer (auth errors
weren't in _FUEL_ERROR_MARKERS), so Orion went mute for ~2 weeks instead of failing over.
Added auth-failure markers (specific phrases, no bare 401/403) + surfacing (brain.fuel.degraded
+ fuel_health.jsonl). Proven: get_fuel now skips a 401ing claude and answers via codex; the
reflex already fired in production (sleep-consolidation rode Ollama through the outage). James
re-authed Claude 07-21 -> Claude primary again, codex/ollama live backups.
