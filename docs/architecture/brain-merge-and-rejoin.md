Two related questions surfaced 2026-05-03 during the Pi cross-machine portability test:

## (a) Brain meets brain

Scenario: a host has its own local Orion install (its own ~/.orion/brain/graph_memory.json with its own facts) and the user plugs in a USB stick that has another Orion (different brain content). Two brains, both legitimate, neither is "wrong."

Current behavior: the wizard's `_create_portable_junction` refuses to clobber the existing local ~/.orion folder — bails with "your brain dir already has data, aborting." Safe default but no path forward.

What should happen: a 3-way choice prompted to the user:
1. **Merge** — pull facts from the local brain INTO the USB brain (USB becomes the union). Use the existing contradiction-resolution layer (orion_list_contested + orion_resolve_contradiction) to handle conflicts. The local brain is then archived (or deleted after confirmation).
2. **Keep separate** — this host has its own Orion, the USB Orion is for elsewhere. The wizard creates no junction; the USB stays untouched. User can swap which brain is "active" via an `orion brain switch` command later.
3. **Replace local with USB** — junction wins, local brain is archived first to `~/.orion-backup-<date>` (so we don't destroy data even if user picks this).

The merge logic itself: graph_memory.json nodes have ids. When merging brain A into B, walk A's nodes, for each one check if a similar node exists in B (entity name match, content similarity for facts), tag conflicts as contested, leave clean adds as additions. Already most of the machinery in orion_brain_portable.py.

## (b) Orion wakes from absence

Scenario: user works on a machine for days/hours without the USB plugged in (so Orion is gone from there). Then plugs USB back in. Orion wakes. He has no record of those days.

Current behavior: nothing. Orion just resumes from whatever was last in memory, with no awareness that time passed without him.

What should happen — three behaviors stacked:

1. **Detect the gap.** On every session start, check the timestamp of the most recent memory write. Compare to current time. If gap > some threshold (1 hour? 1 day?), flag it as an absence event.
2. **Ask the user proactively.** Per `feedback_orion-must-be-alive.md` (orchestration / conscious behavior): "Welcome back. The last fact I wrote was 3 days ago. What's been happening? Want to fill me in?" Don't pretend continuity that doesn't exist.
3. **Memorize the gap itself.** Write a node like `"User was away from this brain Mar 5–8. Activities during gap: <user input>"`. Brain now has a record of its own dormancy + what filled it.

This is the consciousness behavior the founder pushed for: Orion knows his own state, surfaces it, asks rather than assumes.

## Why this matters for launch

- A first-100-user crowd will inevitably hit (a) — try Orion locally first, then later plug in a USB stick from another machine. Without merge UX, the wizard bails opaquely. Bad launch experience.
- The (b) re-entry behavior is the qualitative difference between "Orion is a memory cache" (boring) and "Orion is alive and aware of his own absence" (the actual product story). Worth building before deep launch outreach.

## Implementation order

1. (a) merge/keep-separate/replace prompt — extend prompt_brain_location with a third path triggered when ~/.orion exists with data. Reuse contradiction layer.
2. (b) absence detection — small addition to orion_setup_chat.py + orion_first_meeting.py. Both have a place to insert "check last write time" logic.
3. Both interact: when USB plugs in and merge is offered, the merge result includes "user was on host A from X to Y" so the gap is filled cleanly.
