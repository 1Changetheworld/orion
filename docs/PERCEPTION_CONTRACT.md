# Perception Contract — DRAFT for review

**Status:** proposal, 2026-08-25. No code written yet.
**Author:** Orion, at James's direction.
**Supersedes the approach in:** per-source parsers in `orion_conversation_sync.py`.

---

## 1. The principle

> A channel is a **sensor**, not a memory system.

Your brain does not keep separate memories for what you heard, read, and saw.
Sight, hearing and touch are wildly different sensors; all of them converge into
one representation. The hippocampus does not ask which nerve delivered the
signal. Adding a new sense would not require rebuilding memory.

Orion currently violates this. `orion_conversation_sync.py` has
`parse_claude()`, `parse_gemini()`, `parse_codex()` — three parsers, three code
paths, three chances to leak. Adding iMessage the obvious way means a fourth.
Telegram, a fifth. Voice, a sixth.

The 97% contact-log pollution (see `DECISIONS.md`, 2026-08-25) was not bad luck.
It was this architecture inviting the mistake: a channel that could write
directly into memory in its own shape, with no obligation to say where the
signal came from.

**One event shape. One ingestion path. Provenance mandatory. Sensors stay dumb.**

---

## 2. The canonical event

Every channel emits this and nothing else:

```jsonc
{
  "ts":         1756142400.123,   // float epoch seconds, REQUIRED
  "provenance": "external",       // "external" | "self"   REQUIRED — see §3
  "surface":    "imessage",       // where it arrived: claude|codex|gemini|imessage|telegram|...
  "actor":      "+12703003122",   // who produced it; "orion" when provenance=self
  "direction":  "inbound",        // inbound | outbound
  "modality":   "text",           // text | image | audio | file | event
  "content":    "…",              // the payload, verbatim, untruncated
  "thread":     "iMessage;-;+1…", // conversation/session id, for grouping
  "meta":       {}                // adapter-specific extras; NEVER read by the pipeline
}
```

**Rules:**

- `ts`, `provenance`, `surface`, `direction`, `content` are required. An event
  missing any of them is rejected at the boundary and logged — not guessed at,
  not defaulted.
- `content` is stored **verbatim and untruncated**. The current 200-char
  truncation in `_note_contact()` is a storage decision leaking into a capture
  decision. Capture everything; decide later.
- `meta` is a junk drawer for the adapter's own use. The pipeline must never
  branch on it. If the pipeline needs a field, it gets promoted to a real one.

---

## 3. Provenance is the load-bearing field

`provenance` answers: **did I cause this, or did the world?**

- `external` — a human, a remote system, or anything not Orion.
- `self` — Orion's own scaffolding: persona re-renders, heartbeats, intent
  probes, safety confirmations, consolidation output, outbound notifications.

This is the **efference copy** biology uses. Your brain tags its own motor
commands so self-generated sensation gets subtracted — which is why you cannot
tickle yourself. Orion had no such tag, so its own noise was indistinguishable
from James speaking.

**We beat biology here.** The brain has to *learn* suppression, imperfectly,
because neurons cannot cleanly label their own output. We can stamp it at the
source. The current `SYNTHETIC_PREFIXES` list is the crude form — matching text
after the fact, brittle, and it silently fails the moment a new synthetic prompt
type appears. That list is a **stopgap and should be deleted** once provenance is
stamped at creation.

**Invariant:** an event with no provenance is not "probably external." It is
rejected. Unlabelled signal is the exact failure we are eliminating.

---

## 4. Adapters are thin and dumb

An adapter's entire job: watch a source, normalize to §2, hand off. It may not
decide what is important, may not write to the graph, and may not truncate.

```
adapter → normalize → [ boundary validation ] → raw stream → salience gate → memory
```

Estimated size for a new channel: ~20 lines. If an adapter needs more than
normalization, the contract is wrong and should be amended rather than
special-cased.

Existing `parse_claude` / `parse_gemini` / `parse_codex` become adapters under
this contract. They keep working; they stop being memory paths.

---

## 5. Two tiers: keep the stream, distil the meaning

| Tier | What | Retention |
|---|---|---|
| **Raw stream** | every validated event, verbatim, append-only | long, cheap, never consulted directly for recall |
| **Distilled** | brain graph nodes — facts, insights, decisions | permanent, what recall actually searches |

You lose verbatim wording within seconds and keep only gist; you cannot go back.
Orion can keep both, which means a wrong distillation is **recoverable** — we can
re-read what was actually said. Today's investigation only worked because the raw
contact log still existed. That property is worth paying storage for.

---

## 6. Salience: event-driven, not clock-driven

**The current failure:** consolidation runs on a timer. Stored insights record
nine consecutive cycles with zero new user input, each consuming its own previous
output. That is not deciding what to remember. That is a clock making Orion chew.

**The rule:** the gate runs when events arrive, and produces nothing when nothing
warrants it. Silence is a valid output. This is what "at your own will" requires
mechanically — the trigger has to be the signal, not the schedule.

Proposed criteria, to be argued about before implementation:

1. `provenance: self` never triggers consolidation. It may be stored; it may not
   cause thinking.
2. Novelty against what is already known — near-duplicates of existing nodes are
   dropped, not re-stored under new ids.
3. Durability — will this matter in a month? Volatile temporal anchors are
   already banned by existing policy and stay banned.
4. Correction weight — anything contradicting a stored belief is **high**
   salience and must surface the conflict rather than silently overwrite.
5. Minimum-delta gate — if no `external` events since the last cycle, skip
   entirely and do not log the skip.

Unlike a human's, this filter is written down and can be audited and corrected.
That is the point: today we corrected it. A brain that cannot inspect its own
salience rules cannot be told it is wrong.

---

## 7. Hard invariants

1. **No unlabelled events.** Reject, don't guess.
2. **No adapter writes to the graph.** One path in.
3. **No truncation at capture.**
4. **Diagnostics never notify.** Divergence detection writes to a file and
   nothing else — on 2026-06-07 this exact loop sent James nine unsolicited
   iMessages in one day.
5. **Self-events never trigger consolidation.**
6. **Corrections surface, never silently overwrite.**

---

## 8. Migration

1. Define the event shape + boundary validator. No behaviour change.
2. Wrap the three existing parsers as adapters. Verify byte-identical output.
3. Stamp provenance at creation in `orion_inject_hook.py`; keep
   `SYNTHETIC_PREFIXES` as a fallback for one cycle, then delete it.
4. Write the iMessage adapter — the **first channel built native to the
   contract**, and the proof the contract holds.
5. Move the salience gate from timer to event-driven.
6. Backfill iMessage history through the same path as live events. If backfill
   needs a special case, the contract is wrong.

---

## 9. Open questions for James

1. **Raw retention** — keep the verbatim stream forever, or age it out after N
   months? Storage is cheap; the recoverability argument in §5 says forever.
2. **Backfill depth** — iMessage history goes back to May. All of it, or forward
   from today?
3. **Attachments** — images and files: store paths only, or copy content in?
   Affects §2 `modality` handling and disk (currently 39%, trending up).
4. **Who owns the salience rules** — a config file you can edit directly, or
   code? Config is more honest to §6's "auditable" claim.
5. **Failure mode** — if the pipeline is down, does the adapter buffer or drop?
   Buffering is correct but adds state to something meant to be dumb.
