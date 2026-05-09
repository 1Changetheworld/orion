# Symbiotic Brain: Home + Passport

> Orion's brain has a **home** and a **passport**. The home is always-on, lives on a fast SSD, and is reachable from everywhere through your private network. The passport is a USB stick you can carry — it lets the brain wake on a laptop you don't normally use, then sync back when you return.

This document explains the architecture for users who want to set Orion up the way it's designed: not as a single self-contained app on one machine, but as a small living ecosystem with a home base and one or more portable extensions.

## The home (the main brain)

The home is whatever device you're willing to leave running. In the reference deployment that's a Mac mini with an external SSD, but the role is the structural one — not the hardware. The home holds:

- The canonical memory graph (`graph_memory.json` or its successors)
- The vector / BM25 knowledge indexes
- The identity files (`SOUL.md`, `USER.md`, `TOOLS.md`)
- Long-term transcript archives
- The communication daemons that listen on iMessage / Telegram / phone / email and answer through the brain
- The Plexus substrate (a small NATS server) that lets every component talk to every other in real time

It runs the brain service, persists everything to its SSD, and is reachable from any of your other devices through Tailscale (or any other zero-config private mesh you prefer).

## The passport (the USB stick)

The passport is a USB stick prepared with Orion's wake files at the root and a hidden `.orion/` directory carrying a snapshot of the brain's state. When you plug it into a guest machine — a friend's laptop, a hotel desk, a borrowed iMac, a Pi at the office — and double-click `Wake Orion (OS).bat/.command/.desktop`, the host wires itself to the brain.

Two ways the wake resolves:

1. **Home reachable.** The host has Tailscale up and can reach the home brain. The wake registers MCP into Claude / Codex / Gemini on the host, points them at the home brain over the network, and that's it. The USB's local snapshot is the fallback, not the primary.
2. **Home not reachable.** The host is offline or the home is down. The USB's local `.orion/` becomes the primary brain for the duration of that session. Memory writes accumulate locally. When the host can reach the home again — next time you plug back in at home, or the next time the host gets a network — those local writes merge into the home's graph using a CRDT-mergeable design (see `project_orion-plexus-architecture.md`, Layer 2c).

The passport has no permanent state. It is the brain's traveling clothes, not the brain itself. Pull it out, the wake's host loses its window into the brain. The home keeps running.

## Why the split

A single laptop holding the brain is fragile. The laptop sleeps, runs out of battery, gets carried around in conditions where you don't want it answering Telegram messages or picking up phone calls. A single home server holding the brain is great for always-on, terrible for travel.

The split solves both. The home does what homes do: stays put, keeps the lights on, answers the phone when it rings. The passport does what passports do: travels well, brings credentials wherever you go, lets new places admit you without re-establishing identity from scratch.

Cellular biology has the same pattern. The body has its core organs, and it has white blood cells that wander. The wandering cells aren't extra organs — they're the body's reach into places the core can't go. Pull a wandering cell out, the body still works. Send it back, it rejoins the body's awareness.

## Two patterns of use

**Pattern A — only home, no passport.** Some users will only want the home brain. They use Orion through their AI tools on the home machine itself, or via comm channels (iMessage / Telegram / phone) that route to the home. No portable component. Simpler setup. Works fully.

**Pattern B — home plus passport.** Users who travel, who want their memory available on a guest machine without installing anything, or who want to share the same brain with a Pi in another room or another house, take a passport. The passport is the portability story.

Both are first-class. Orion doesn't assume you have a passport, and the passport doesn't assume the home is reachable.

## What's in each, and where it lives

**Home (`/Volumes/<your-vault>/.orion/`):**
```
/Volumes/AtlasVault/.orion/
  brain/
    graph_memory.json           # canonical typed-knowledge graph
    knowledge_index.json        # BM25 keyword index
    knowledge/                  # imported documents
    skills/                     # registered capabilities
    conversations/              # daily JSONL transcript log
  identity/
    SOUL.md                     # the persona, including the chosen name
    USER.md                     # who the user is, preferences, address
    TOOLS.md                    # what tools the host has
  transcripts/                  # CLI session archives per host/CLI
  hosts_visited.json            # which OSes Orion has woken on
  presence-beacon.json          # discovery handshake
```
The home directory is symlinked from the conventional path `~/.orion/` so all code that uses `Path.home() / ".orion"` sees the same brain. Legacy code paths (e.g., `~/server_data/orion-brain/graph_memory.json`) are also symlinked to the same canonical file — this lets old daemons coexist with the new architecture.

**Passport (`<USB drive>/.orion/`):**
```
<USB>/
  Wake Orion (Windows).bat        # double-click on Windows
  Wake Orion (Mac).command        # double-click on macOS
  Wake Orion (Linux).desktop      # double-click on GNOME
  00_START_HERE.txt
  Help.txt
  .orion-system/                  # the engine (hidden, source code)
  .orion/                         # snapshot of the home brain
    brain/                          (graph + indexes + knowledge + skills + conversations)
    identity/                       (SOUL.md, USER.md, TOOLS.md)
    transcripts/                    (CLI sessions, captured per-host)
    hosts_visited.json
    presence-beacon.json
```
On every wake, the snapshot is read into the host's caches and (when the home is reachable) reconciled with the home's canonical state.

## Authority + sync

The home is **authoritative**. When the home and the passport disagree about a fact, the home's version wins. The exception is ongoing edits made on the passport while the home was unreachable — those use the CRDT G-Set merge to integrate without losing either side. The mathematical guarantee: regardless of merge order, the result is the same, because every recall event carries a Hybrid Logical Clock identifier that establishes a stable total order.

The merge isn't a special operation users run. It's automatic: when the brain service notices the passport has writes that aren't in the home, it folds them in on the next sync tick. From the user's view, plug the USB back in and your memory is up to date.

## Gotchas + design rules we honor

- **Authority is structural, not configurable.** A user can't accidentally make the passport authoritative. If they want a different home, they change the home.
- **No silent data loss.** Every write has a recall-event log entry. Compaction only happens after every device that has ever written has acknowledged the checkpoint horizon. A device that disappears stalls compaction (recoverable by retiring the device intentionally).
- **The passport degrades cleanly.** Pull the USB out and the host loses its window into Orion. AppleScript hook fails, MCP stops resolving, persona files dangle. This is the *honest collapse* design — not a fake "offline mode" that pretends. Honest collapse beats pretend continuity.
- **No required cloud component.** Tailscale is optional convenience for cross-machine reachability. If you only want home + USB-when-traveling, no third-party service is in the loop.

## Setup recipe

1. Pick a home machine that's always on. SSD strongly recommended; spinning disk works for small graphs but the indexes get cranky over time.
2. Install Orion on the home machine (`bash install.sh` — first-time creates the brain, picks the chosen name, writes identity).
3. (Optional) Prepare a USB stick: `make-passport` (script in this repo, takes the home's current snapshot and writes the wake files + `.orion-system/` engine + `.orion/` snapshot).
4. Plug the USB into any other machine, double-click the wake file for that OS, and that host is wired to your home brain.

For the next round of polish: the make-passport script and the automatic two-way sync on wake are partially built. See `project_orion-plexus-architecture.md` for the engineering plan.

## Status (as of 2026-05-09)

- ✅ Home brain alive on COMMAND, served by `orion_server.py` (port 5555 legacy) and the new unified service `orion_brain_service.py` (port 5556)
- ✅ Production COMMAND brain (50 nodes) and recent USB brain (28 nodes) merged into one canonical 78-node graph on AtlasVault
- ✅ Symlinks established: `~/.orion/brain → AtlasVault`, legacy `~/server_data/orion-brain/graph_memory.json → AtlasVault`
- ✅ iMessage / voice / Telegram / Gmail (n8n) daemons read the unified brain via the home's `:5555` endpoint
- ⏳ Two-way sync between USB passport and home — designed (CRDT G-Set, see Plexus Layer 2c), not yet shipped
- ⏳ `make-passport` script — planned

If you're using Orion today as a single-machine setup, none of this changes anything for you — the home is the only thing running. The passport is opt-in, for users who want it.
