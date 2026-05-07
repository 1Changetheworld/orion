# Zero-touch on a fresh host — research direction

## The problem

The current install requires one user action on a fresh host:

| OS | First plug-in action | Subsequent plug-ins |
|---|---|---|
| Windows | Double-click `Install Orion.bat` | Auto-fire (agent already installed) |
| macOS | Double-click `Install Orion.command` | Auto-fire |
| Linux | Run `bash <USB>/orion/install.sh` | Auto-fire |

This contradicts the launch promise *"plug Orion in, models become Orion."*
The friction is real on first-touch per host. Every subsequent plug-in is
genuinely magic — but the first time on each new computer breaks the spell.

## The actual constraint

A standard USB drive is **dumb storage**. It has no compute, cannot
announce itself, cannot trigger code on the host. The host must
already have software watching for new USBs to react. Microsoft (KB971029,
2011) and Apple deliberately disabled autorun-on-USB because it was the
BadUSB attack vector. Every direct path is closed.

Cellular framing: a ligand needs an existing receptor on the cell. An
inert membrane ignores an inert ligand. For Orion to bind to a fresh
host with zero pre-install, **either the host has a receptor (prior
install) or the USB has its own machinery (compute on board).**

## Three breakthrough paths

### Path A — Receptor-on-companion-device (software-only)

Reframe: the user's *other* devices are not blank. If Orion is on the
user's phone (or any of their computers), that device authorizes
the new host on the user's behalf.

```
1. User plugs Orion-USB into a fresh laptop.
2. Phone (running Orion companion app) detects proximity via Bluetooth
   advertisement OR a paired Orion-on-LAN sees the host's mDNS service.
3. Phone shows: "You plugged your Orion drive into <hostname>.
   Authorize install here?"
4. User taps Approve (Face ID / Touch ID).
5. Phone pushes the bootstrap command to the new host via:
   - Tailscale tunnel (if user has Tailscale on both)
   - LAN socket (if same WiFi)
   - The brain-as-network surface we already shipped
6. New host runs install via that channel. User never touches it.
```

First device the user adopts: one touch (the unavoidable consent gate).
Every device after that: zero touches.

**Implementation primitives we already have:**
- `orion_brain_service.py` — listens on localhost, can be exposed to LAN
- `channels/` framework — adding a phone-pair channel is ~30 lines
- mDNS broadcast on the brain service (need to add — small)

**Implementation gap:**
- Companion phone app (iOS/Android) — significant work
- Bluetooth proximity / push notification routing
- Tailscale / LAN handshake protocol

### Path B — USB-carries-its-own-machinery (custom hardware)

Pi Zero 2 W in a USB-stick form factor (~$15 BOM premium over a regular
flash drive). On board: SoC, RAM, storage, optional network. The drive
emulates keyboard + mass storage + USB-network composite device.

Plug-in sequence:
```
1. Drive boots from USB power (~5 seconds)
2. Enumerates as keyboard (HID), storage (MSC), network (RNDIS/ECM)
3. HID types the bootstrap command in the active terminal/shell
   (or just opens a file manager via OS shortcut + typing)
4. Bootstrap reads from the storage portion, runs install
5. Optionally: USB-net connects host to brain running ON the drive's
   own SoC — no install needed at all
```

Existing prior art: Hak5 Bash Bunny, O.MG Cable, P4wnP1 — all do
exactly this for security testing. Re-aiming for benign product use
is straightforward.

**Tradeoffs:**
- Per-unit cost: ~$15 vs. $5 for a flash drive. Not a launch blocker.
- Fully self-contained: no companion device needed. Truly plug-and-play
  even if the user has nothing else with Orion on it.
- Hardware OEM/manufacturing pipeline. Real cost is sourcing + assembly,
  not BOM.

### Path C — Signed OS-cooperated AutoPlay (regular hardware, best UX without breakthroughs)

What modern OSes still allow with a regular USB:
- Windows: AutoPlay dialog appears on plug-in. With `autorun.inf`'s `label=`
  and `icon=` (still respected post-2011), shows a recognizable Orion entry.
  User clicks once → File Explorer opens at drive root. User double-clicks
  the obvious `Install Orion.bat`. **Two physical actions.**
- macOS: Finder auto-opens the drive window. User sees `Install Orion.command`.
  Double-click. **One physical action** (Finder open is automatic).
- Linux: file manager auto-opens. User clicks `.AppImage` or `.desktop`.
  Filesystem matters: ext4/NTFS preserve +x; exFAT/FAT do not (AppImage
  won't run from FAT). Format USB as ext4 or NTFS for universal +x.

With Apple Developer ID + Microsoft Authenticode reputation, the
double-click is silent. Zero security warnings.

**This is the v1 launch path.** It's not zero-touch but it's "plug + click."
Most consumer products are this. The friction is acceptable.

## The study to run

20 fresh users (no prior Orion exposure). Mix of Win 11, macOS Sequoia,
Ubuntu 24.04 hosts.

Measure: time from plug-in to first successful Orion conversation.

Conditions to compare:
1. **Plain USB + standard install scripts** (current v1)
2. **Plain USB + signed installers + AutoPlay-friendly autorun.inf**
3. **Plain USB + companion phone authorization (Path A)** — even with stub
   that just shows a "Pretend Approve" button, measure UX feel
4. **Pi-Zero-composite hardware (Path B)** — prototype with one unit
5. **Control: best-known competitor** (1Password manual setup, Mem0 wiring,
   Letta personal install) — for comparison anchor

Hypothesis ranking by median time-to-Orion:
- B (hardware): <10 seconds
- A (companion): <20 seconds
- C (signed AutoPlay): 30-60 seconds
- 1 (current): 60-180 seconds (familiar with terminal) / "never finishes"
  (non-technical users)

Funnel data: where do users abandon? At which click?

## Recommendation

**Ship v1 with Path C (signed AutoPlay) — the "two-click magic" that
ALL software products live in.** That's the launch.

In parallel, prototype **Path A (companion device)** — software-only,
leverages infrastructure we already have. Phone app or even just a
small Mac/Win tray app that listens for "new Orion-USB plugged in"
events from the user's other Orion installations. First magic version
ships within weeks, not quarters.

**Path B (custom hardware)** is the v2 product — the "Orion drive"
that's truly magic from day one. Ship it once Path A is validated and
revenue justifies the hardware spend.

The breakthrough framing: **the host doesn't need to be aware of
Orion. Another device the user already has does, and that device can
adopt the new host on the user's behalf.** That's the cellular pattern
applied honestly — the colony recognizes its own and authorizes
expansion. No virus needed.
