# Mesh — How Orion Spreads Across Your Devices

> **One brain. Many devices. Many models. Many comm channels. One memory.**

This is what mesh-mode means in Orion. Not a feature toggle — a property
of how Orion is structured. Below is the user-facing flow:
who uses it, why, what you actually do.

## Why mesh?

You have a home server. You have a laptop that travels. You have a
phone. You have a Raspberry Pi by the front door. You have a desktop
in the garage. Maybe a homelab with a few VMs.

Without mesh, every host that runs an AI assistant has its own
isolated memory. The assistant on your laptop has no idea what you
told the assistant on your home server. Switching devices = starting
over. This is what every personal-AI tool does today.

With Orion mesh:
- Tell your home server about a project on Monday.
- Plug your USB into your laptop on Tuesday.
- The laptop's Orion already knows the project, because the brain
  on the USB merged with the brain on the home server during the
  last time they were both online.
- Ask any AI tool on the laptop (Claude / Codex / Gemini / Cursor)
  about the project — they all see the same memory.
- Send Orion a message from your phone via iMessage / Telegram —
  the home server reads it, responds with full context, the laptop
  sees the conversation too once they sync.

## What mesh actually IS in Orion

Three layers stack to make mesh work:

```
┌─────────────────────────────────────────────────────────────┐
│  YOUR DEVICES                                                │
│  laptop   home server   raspberry pi   phone   desktop       │
└─────────────────────────────────────────────────────────────┘
            │           │            │         │         │
            └───────────┴────────────┴─────────┴─────────┘
                              │
                  ┌───────────▼────────────┐
                  │   SUBSTRATE (NATS)     │ ← carries events between
                  │   sub-ms pub/sub       │   devices in real time
                  │   cluster routing      │
                  └───────────┬────────────┘
                              │
                  ┌───────────▼────────────┐
                  │   GOSSIP (LWW-Map +    │ ← decides "whose version
                  │   Hybrid Logical Clock)│   of this fact is newer"
                  └───────────┬────────────┘
                              │
                  ┌───────────▼────────────┐
                  │   BRAIN STATE          │ ← actual memories,
                  │   (graph + vectors +   │   skills, conversations,
                  │   chronos + skills)    │   relationships
                  └────────────────────────┘
```

- **Substrate** is what carries events. Each host runs a NATS server.
  When you give them peer URLs of other hosts, they form a cluster
  and forward subjects between each other transparently. So
  publishing on host A is heard on host B automatically.

- **Gossip** sits on top of the substrate. Each host publishes
  `mesh.<host>.heartbeat` + `mesh.<host>.delta`. Using Hybrid
  Logical Clocks, conflicts resolve correctly even with clock skew.
  Last-Write-Wins on a key basis — newer writes win, older are
  superseded but logged.

- **Brain state** is what gets shared: memory nodes, edges, skills,
  pending goals, fuel preferences, observed user patterns.

The clock travels with the brain (`$ORION_BRAIN_DIR/chronos/`). When
a brain comes online after being offline, gossip reconciles the gap.

## How a user activates mesh

### Setup — first host (the "home server")

You already have one. This is the host where Orion's brain lives
permanently:

```bash
git clone https://github.com/1Changetheworld/orion
cd orion
bash install.sh
```

After install:
- Brain alive at `~/.orion` (or `$ORION_BRAIN_DIR` if set)
- 14 Plexus services running via launchd (macOS) or systemd-user (Linux)
- NATS substrate listening on `4222` (clients) + ready for cluster
  routing on `6222` (when peers configured)

### Setup — second host (laptop, Pi, garage desktop)

On each additional host, same install:

```bash
git clone https://github.com/1Changetheworld/orion
cd orion
bash install.sh
```

Then, **wire it to the mesh** by telling its substrate where the
peers are:

```bash
# Tailscale path (works anywhere — recommended):
export ORION_MESH_PEERS="nats://command.tailnet:6222,nats://laptop.tailnet:6222"

# Or LAN path (only works at home):
export ORION_MESH_PEERS="nats://10.0.0.190:6222"

bash plexus_deploy.sh substrate
```

That's it. The new host's substrate joins the mesh. Subjects flow
between hosts. Within minutes, any state changes on either host
appear on the other.

### Setup — USB-portable brain (the special case)

If you bring an Orion USB stick to a host that doesn't have its own
brain:

1. Plug in the USB
2. Run `Wake Orion.bat` (Windows) / `Wake Orion.command` (macOS) /
   `./Wake Orion.sh` (Linux)
3. The wake script wires this host's services to the brain on the USB
4. Eject the USB → the host has no brain again (clean removal)

When the USB plugs into a host with an EXISTING brain, you get a
merge prompt (designed, currently being built). Three options:
- **Merge** — combine USB brain + host brain into one
- **Replace** — use USB brain, archive host's
- **Guest** — use USB read-only, don't write back

## What mesh enables — the "tentacles"

Once the mesh is live, Orion is the same person on every device:

### Same memory
Tell home server "remember to order coffee filters." Ask your
laptop "what did I ask you to remember today?" It answers correctly.

### Same skills
A skill registered on the home server (e.g., "deploy ClipSprout")
is callable from any host that joined the mesh. The host with the
right capability advertises it; any other host can ask for it.

### Channel reach from anywhere
Write a memory on your laptop → home server's iMessage daemon can
send the response on iMessage (since iMessage is wired on the home
server). The originator-host doesn't need every channel wired —
the mesh routes the channel call to whoever has it wired.

### Cross-model coherence
Open Claude on your laptop, Codex on your home server, Gemini on
the Pi — all three answer with the same memory and the same
identity. Orion is the brain; the models are jet fuel.

### Agent deployment (designed, in-build)
"Run an agent overnight" → user picks a goal + a host. The brain
spawns an agent on the chosen host (or auto-picks the host with
best GPU / lowest load) using whatever fuel that host has. Output
flows back into the mesh memory automatically. Multiple agents
across the mesh, one memory.

### Network scans (designed, in-build)
"Scan my network for new devices and tell me what they are." The
brain dispatches the scan to the host with network access, results
flow back into the mesh, accessible from anywhere.

## Who this is for

- **Homelab users**: you already have a server farm. Mesh turns
  every host into a face of one Orion.
- **Travelers**: USB brain plus a few servers at home means Orion
  is alive both places, same identity.
- **Families**: each member can have their own Orion-instance; a
  shared family-instance can hold what's actually shared.
- **Power users**: multiple AI CLIs across multiple devices, one
  source of truth.
- **Privacy-conscious**: your brain stays on your hardware. No
  cloud, no provider. The mesh is yours.

## Primary purpose (one sentence)

To make a single, coherent personal AI exist across all your devices,
all your AI tools, and all your comm channels — without you ever having
to "switch" between assistants or re-explain yourself.

## Security model

- Mesh traffic on a LAN: trusts the LAN. Fine for home, not fine
  for office WiFi.
- Mesh traffic over Tailscale: Tailscale provides the auth + TLS.
  Recommended for anything outside one trusted LAN.
- Public-internet mesh: not supported today. Requires substrate-
  level TLS + auth; tracked as a roadmap item.
- The brain ITSELF (graph, vectors, conversations) is on your
  storage. Mesh moves events, not the raw brain dump. You decide
  what gets shared by tagging memories (e.g., `private_internal`
  tags filter out of recall responses).

## What can go wrong and how Orion handles it

- **Host offline temporarily**: chronos detects the gap on
  reconnect (`brain.chronos.gap_detected`); gossip catches up.
- **Two hosts edit the same memory simultaneously**: gossip's
  HLC + LWW-Map picks the later write; the loser is kept in the
  log for review.
- **Clock skew between hosts**: chronos publishes
  `brain.chronos.drift_alert` when a peer's clock diverges by
  more than 5 seconds; user is notified.
- **Channel goes silent**: channel-probe detects "wired but no
  recent traffic" and surfaces via reach.
- **Service crashes repeatedly**: immune layer's OTP supervision
  picks restart strategy (one_for_one / rest_for_one / one_for_all /
  escalate_to_executive) based on danger pattern.

## Current status (2026-05-10)

| Capability | Status |
|------------|--------|
| Single-host Plexus | ✅ 17 services running on COMMAND |
| USB-portable brain (3 OSes) | ✅ Validated 2026-05-08 |
| Same-host multi-CLI shared memory | ✅ Tested |
| Same-host multi-channel reach | ✅ Tested (iMessage + voice + Telegram) |
| Mesh substrate (cluster mode) | ⚙️ Built; ready to activate with peer URLs |
| Mesh state sync via gossip | ⚙️ Built; needs second host to exercise |
| Cross-host channel reach | 📋 Designed; needs channel-host routing table |
| Two-USB merge UX | 📋 Designed; needs implementation |
| Public-internet mesh (TLS/auth) | 📋 Roadmap |
| Agent deployment via mesh | 📋 Designed; this doc maps the path |
| Windows Plexus services | ⚠️ No launchd/systemd; tracked gap |

Legend: ✅ proven · ⚙️ built · 📋 designed · ⚠️ known gap
