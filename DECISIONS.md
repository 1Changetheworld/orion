# DECISIONS.md

Running record of engineering conclusions for Orion — what we decided, why, and
what turned out to be wrong. Newest first.

**Why this file exists:** a plan written from a wrong premise stays
authoritative-looking forever. Someone (including a future Orion session) picks
it up cold months later and executes surgery on healthy code. Conclusions belong
somewhere durable and dated, separate from the plans that produced them.

## Conventions

- **Newest entry at the top.** Never rewrite history; add a correcting entry.
- Any superseded document gets this header block prepended, verbatim shape:

  ```
  > ## SUPERSEDED — <date>
  > - Premise (wrong): <what it assumed>
  > - Actual cause: <what was true>
  > - What was actually done: <numbered list>
  > - Superseded by: <file / node id>
  ```

- Every entry states **how it was verified**, not just what was concluded.
  "Verified by" is mandatory. If it wasn't verified, say so explicitly.
- Record disproven theories too. Knowing what it *isn't* has saved more time
  here than knowing what it is.

---

## 2026-08-25 — Contact log was 97% self-generated noise

**Conclusion.** The "stale timestamp" symptom was not drift, not a race, and not
multi-writer contention. Orion's own scaffolding — persona re-renders, heartbeat
pokes, intent-extraction probes, "Reply with only: OK" — arrived on the same
prompt hook as James's messages and was recorded as inbound *user* contact.

**Numbers.** 19,345 of 19,778 inbound entries (97%) were machine-authored.
Walking the full history, filtered and unfiltered answers to "when did we last
speak" disagree at 19,336 of 19,836 points.

**Per surface.** claude 19,446 entries / 99% synthetic; codex 157 / 51%;
gemini 2 / 0%; imessage 202 / 0%. Claude was ~98% of the total problem — the
persona re-render fires there and nowhere else. iMessage contact data was always
clean.

**Framing.** This is a missing *efference copy*. Biology tags its own motor
commands so self-generated sensation is subtracted (why you can't tickle
yourself). Orion had no such tag, so it could not tell its own noise from James.

**Fixes applied.**
1. `orion_inject_hook.py` — `_note_contact()` drops synthetic turns before POST.
2. `orion_temporal.py` — injected line reworded to "Before the message you are
   reading now, you last spoke…". The old wording implied it covered the
   in-flight message; it never could.
3. `orion_temporal._last_spoke()` — same filter applied at read time, so the
   ~19k pre-fix entries can no longer win as most-recent. Nothing deleted.
4. Canonical list is `orion_temporal.SYNTHETIC_PREFIXES`. The hook imports it
   and keeps a fail-silent fallback copy. Do not let the two drift.

**Verified by.** Both modules compile; 12/12 classification test on real logged
prompts; before/after replay over the full 19,836-entry history; live
`temporal_context()` output confirmed correct.

**Disproven — do not revisit without new evidence.**
- *Multi-writer contention* (the 08-24 plan's premise). Four writers exist, but
  they were not causing this.
- *Snapshot frozen at session init.* `_last_spoke()` re-reads both logs on every
  call; there is no cache.

**Deliberately NOT changed.** `temporal_context()` is computed before
`_note_contact()` by design, so recall still reflects the previous surface for
cross-window handoff. Reordering would fix the timestamp and break that feature.

**Still open.** Whether iMessage conversation *content* is absorbed into the
brain graph or only visible through the live cross-window feed.
`orion_conversation_sync.py` ingests claude/gemini/codex only — no iMessage
parser as of 2026-08-19. Contact metadata is clean; content persistence is
unverified.

**Artifacts.** Brain node 4506. Backups: `orion_inject_hook.py.bak-20260824`,
`orion_temporal.py.bak-20260824`. Superseded plan:
`~/Desktop/ORION_STALE_TIMESTAMP_FIX_PLAN_2026-08-24.md`.

---

## 2026-06-07 — (recorded retroactively) Divergence detection must never page the user

On this date the stale-contact bug sent James nine near-identical iMessages,
hourly, each announcing a detected discrepancy. Cause and fix are covered in the
2026-08-25 entry; the standing rule from it is separate and applies to all future
work:

**Rule.** Divergence and self-diagnostic detection is diagnostic-only. It writes
to a file. It must never reach a notification path. Any instrumentation added
during debugging must be explicitly checked against this rule before it ships —
the June 7 loop is exactly what "log every divergence" produces when wired to an
outbound channel.
