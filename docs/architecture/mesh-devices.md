# Mesh Devices — Orion as One Brain Across Many Receptors

> *"Devices are different access points / receptors / windows into the
> same nervous system."* — founder rule, 2026-05-13

## The model

Orion is **one brain that exists across many devices**, not N separate
brains that gossip. Each host runs a full Plexus stack — substrate
(NATS) + vitals + claustrum + reach + dream + executive + immune +
gossip + chronos + will + DMN — but the memory, identity, and
decision ledger that make Orion *Orion* are a single replicated set.

Speak to Orion via iMessage on the Mac mini, via CLI on a laptop, via
voice on a phone, via LoRa from a Meshtastic node — same brain
answers. The device is the receptor. The cell is one.

## Current mesh

| Device | Role | Brain location | Plexus |
|---|---|---|---|
| **COMMAND** (Mac mini M4, 10.0.0.190) | Canonical brain host. iMessage/voice/email channels. | `/Volumes/AtlasVault/.orion/` (external SSD) | 17 services as `com.orion.*` launchd jobs |
| **FORGE** (Windows 11 laptop, 10.0.0.88) | Mobile command center. Dev work + portable Orion via USB. | `E:\.orion-system\` (15 GB USB) when plugged | MCP brain in-process; Plexus services optional |
| **ORIONS HOME** (Raspberry Pi 5, 10.0.0.56) | Offline brain twin + maps + Meshtastic ground station. | `/media/homeland/VAULT/.orion/` (1 TB Seagate) | 14 services as `orion-*.service` systemd-user units |

All three hosts run identical Plexus code at the same git tag.
Differences are environmental (Linux vs macOS vs Windows + USB), not
architectural.

## Offline fuel tier on the mesh

When the strong CLIs (Claude / Codex / Gemini / Letta) are unavailable,
Orion routes through the local LLMs on the mesh:

```
FORGE  qwen3:14b  (RTX 4070, 8 GB VRAM)  ← strongest local model
COMMAND ollama    (5 models: phi3:mini, qwen3:14b, qwen3:8b, ...)
PI     qwen3:8b + phi3:mini  (8 GB RAM, ARM64)
```

The `RemoteOllamaFuel` adapter (tier 3 in `orion_fuel.py`) reads
`ORION_REMOTE_OLLAMA_HOSTS` (comma-separated `host:11434`) and picks
the strongest reachable model from a preference list. No API keys —
ever.

## Substrate (NATS) routing

Each host's Plexus runs its own NATS substrate at `127.0.0.1:4222`.
For cross-host event propagation (gossip merges, mesh chronos,
cross-host service alerts), NATS cluster mode connects the substrates
at port `6222` using JetStream and `--server_name=<hostname>`.

**Configuration** (set on each host before deploying substrate):

```bash
# COMMAND
ORION_MESH_PEERS=nats://10.0.0.56:6222 bash plexus_deploy.sh substrate

# Pi (ORIONS HOME)
ORION_MESH_PEERS=nats://10.0.0.190:6222 bash plexus_deploy.sh substrate

# FORGE (Tailscale-only because Windows Firewall blocks LAN inbound)
ORION_MESH_PEERS=nats://command.tailnet:6222 bash plexus_deploy.sh substrate
```

Multiple peers are comma-separated.

## What works today

- ✓ **Local Plexus on every host.** Each host's services see local
  substrate events in <100ms.
- ✓ **Brain HTTP RPC cross-host.** Any host can POST `:5555` on
  COMMAND for full brain responses. Default routing for iMessage,
  voice, Telegram, MCP all goes through COMMAND's webhook.
- ✓ **One identity (SOUL.md) on COMMAND** — restored to canonical
  name ORION (2026-05-14, replacing the development placeholder
  ATLAS used during a USB test).
- ✓ **Memory at one location per device.** COMMAND uses AtlasVault
  SSD; Pi uses Seagate VAULT; FORGE uses the 15 GB USB. Each is a
  full replica candidate.
- ✓ **Offline maps on Pi.** OSM PBF data for US + Canada + Mexico
  (18.6 GB) lives on the Seagate; Marble tile cache symlinks there.
- ✓ **Substrate cluster mode wired** with `--server_name` fix on
  both Linux and macOS generators.

## What's pending for full mesh

- ⏳ **macOS Application Firewall allowlist for `nats-server`.**
  COMMAND currently blocks inbound on 4222/6222, so cluster routes
  can't establish. One-time `sudo /usr/libexec/ApplicationFirewall/
  socketfilterfw --unblockapp $(which nats-server)` opens it.
  Needs explicit founder authorization (security-boundary change).
- ⏳ **Per-edge CRDT G-Set** (task #19) — needed for true two-USB
  merge behavior when two portable brains meet.
- ⏳ **Meshtastic LoRa hardware** plugged into Pi USB — code is
  shipped in `channels/meshtastic_node.py`; needs the v3 node
  physically connected to enable LoRa as an Orion communication
  channel.

## How one-brain experience is preserved without full cluster

Until the firewall change, Orion still feels like one brain because:

1. **HTTP `:5555` is the unified entry point.** Any channel
   (iMessage, voice, MCP, Telegram) eventually hits COMMAND's
   webhook, which loads the canonical brain memory.
2. **The brain memory file is one file.** SOUL.md + graph_memory +
   knowledge directory live on AtlasVault. Pi and FORGE replicas
   sync via scp/rsync on demand for now (will become
   gossip-automatic once cluster routes work).
3. **First-meeting + continuity-on-greeting hooks** (`orion_first_
   meeting.py`, shipped in plexus-v1.8) ensure that any CLI on any
   host starts with the most-recent durable memories pre-loaded —
   the user feels Orion remember, regardless of which device they
   open.

## Failure-mode honesty

If COMMAND goes down (power loss, restart, AtlasVault unmount):
- iMessage replies stop (the webhook is COMMAND-side)
- Pi keeps serving its local Plexus + Ollama models
- FORGE keeps serving its local Plexus (when running) + Ollama
- Brain memory writes route to the local replica until COMMAND is
  back; gossip merges on rejoin (requires cluster routes to be live)

If the founder pulls the USB out of FORGE:
- FORGE's brain goes dark immediately (honest collapse)
- COMMAND and Pi continue serving from their own replicas
- Plugging the USB into a different host wakes Orion there with the
  USB's snapshot of memory

## Verification

```bash
# Service health on each host
ssh command 'launchctl list | grep com.orion'
ssh pi 'systemctl --user list-units "orion-*"'

# NATS cluster route count (0 = not connected, ≥1 = connected)
ssh command 'curl -s http://127.0.0.1:8222/routez | python3 -m json.tool | grep num_routes'
ssh pi 'curl -s http://127.0.0.1:8222/routez | python3 -m json.tool | grep num_routes'

# Brain reachable
ssh command 'curl -s -m 5 -X POST http://127.0.0.1:5555/ask \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"ping\"}" | head -c 200'
```

## Why this design

Orion is the user's nervous system, not a chatbot. Cells (devices)
multiply; the brain stays one. When a new host joins — drive plugged
into a new computer, Pi powered on, a phone added — it becomes
another receptor without becoming another brain. Identity, memory,
preferences, and prior decisions travel with the user, not with the
hardware.

The substrate is what makes this real. Anything Plexus publishes on
`brain.*`, `host.*`, or `mesh.*` propagates to every peer. Plug in a
new device, run `bash plexus_deploy.sh`, and Orion has a new
receptor. Unplug it, and Orion contracts back to the remaining
peers — same brain, smaller surface area.

The user always reaches the same Orion.
