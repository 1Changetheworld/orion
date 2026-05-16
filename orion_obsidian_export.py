#!/usr/bin/env python3
"""orion_obsidian_export — render the brain as an Obsidian vault.

Founder pivot 2026-05-14: stop competing with Obsidian's graph view.
Export Orion's brain as a real Obsidian vault — one markdown file per
memory node with proper frontmatter + [[wiki-links]] for tag relations
+ separate folders for devices, channels, services. The user opens
the vault in Obsidian and gets the elite visualization for free:
zoom, pan, filter by tag, fold groups, beautiful rendering, all the
plugins they already know.

Why this is the right move:
  - Obsidian is polished, cross-platform, free
  - Their graph view already does what we'd spend months matching
  - Users can edit memories in Obsidian and re-import later
  - The vault is a portable artifact — copy it anywhere, view it
    in Obsidian on any OS

What this writes:
  vault/
    README.md                — vault overview
    Identity/                — the canonical SOUL of Orion
      Orion.md               — pulled from SOUL.md
    Memories/                — every graph_memory node
      mem-0.md, mem-1.md, …  — one per node, frontmatter + body + links
    Devices/                 — known mesh hosts
      COMMAND.md, FORGE.md, ORIONS HOME.md
    Channels/                — communication points
      iMessage.md, Voice.md, Telegram.md, CLI.md, Webhook.md, LoRa.md
    Services/                — Plexus services on this host
      claustrum.md, gossip.md, …

Run:
  python orion_obsidian_export.py             # default: ./orion-vault/
  python orion_obsidian_export.py --out PATH  # custom destination
  python orion_obsidian_export.py --open      # open in Obsidian (URI scheme)

Then in Obsidian:  Open vault -> pick the orion-vault directory.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
import webbrowser
from collections import defaultdict
from pathlib import Path

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))
GRAPH_PATH = ORION_HOME / "brain" / "graph_memory.json"
SOUL_PATH = ORION_HOME / "identity" / "SOUL.md"
VITALS_DIR = ORION_HOME / "vitals"
MCP_LOG_PATH = ORION_HOME / "mcp_calls.log"
DECISIONS_PATH = ORION_HOME / "executive" / "decisions.jsonl"

# Identical to dashboard_server's KNOWN_* so the exported vault matches
# the nervous system the visualizer renders.
KNOWN_DEVICES = [
    {"id": "command",     "label": "COMMAND",      "role": "canonical brain",       "ip": "10.0.0.190"},
    {"id": "forge",       "label": "FORGE",        "role": "mobile + dev",          "ip": "10.0.0.88"},
    {"id": "orions-home", "label": "ORIONS HOME",  "role": "offline brain twin + GPS navigator (online + offline)", "ip": "10.0.0.56"},
    {"id": "outpost",     "label": "OUTPOST",      "role": "tailscale-only node",   "ip": "100.112.80.14"},
]

# CLIs that can attach to the brain via MCP
KNOWN_CLIS = [
    {"id": "claude-cli",  "label": "Claude CLI",  "vendor": "Anthropic", "tier": 1},
    {"id": "codex-cli",   "label": "Codex CLI",   "vendor": "OpenAI",    "tier": 1},
    {"id": "gemini-cli",  "label": "Gemini CLI",  "vendor": "Google",    "tier": 1},
    {"id": "letta",       "label": "Letta",       "vendor": "Letta",     "tier": 2},
]

# LLMs/ — LOCAL Ollama models only. Frontier models (Claude Opus,
# Codex GPT-5, Gemini Pro) are not standalone nodes — they're served
# through the corresponding CLI; the CLI page describes the model.
KNOWN_LLMS = [
    {"id": "qwen3-14b",      "label": "qwen3:14b",         "kind": "local", "host": "forge",      "tier": 2},
    {"id": "qwen3-8b",       "label": "qwen3:8b",          "kind": "local", "host": "orions-home","tier": 3},
    {"id": "phi3-mini",      "label": "phi3:mini",         "kind": "local", "host": "orions-home","tier": 4},
    {"id": "dolphin-mistral","label": "dolphin-mistral:7b","kind": "local", "host": "forge",      "tier": 3},
]

# Hardware peripherals attached to a device (USB / serial / radio).
# Founder fact 2026-05-14: 2 Meshtastic nodes + ESP32 on the Pi.
KNOWN_PERIPHERALS = [
    {"id": "meshtastic-1", "label": "Meshtastic Node 1", "host": "orions-home",
     "kind": "LoRa radio (Heltec/Lilygo v3)",
     "role": "off-grid text mesh — primary",
     "contents": ["Meshtastic firmware v2.x",
                  "OrionLoRa channel adapter (future)",
                  "Position beacons + text messages",
                  "Future: CRDT brain-delta broadcasts for outreach"]},
    {"id": "meshtastic-2", "label": "Meshtastic Node 2", "host": "orions-home",
     "kind": "LoRa radio (Heltec/Lilygo v3)",
     "role": "off-grid text mesh — secondary / relay",
     "contents": ["Same firmware as Node 1",
                  "Acts as relay/multi-hop when peer node is out of range"]},
    {"id": "esp32-1",      "label": "ESP32",             "host": "orions-home",
     "kind": "microcontroller (WiFi + BLE + GPIO)",
     "role": "sensors / actuators / future LoRa-bridge target",
     "contents": ["WiFi radio (2.4 GHz)",
                  "Bluetooth LE 4.2",
                  "GPIO pins for sensors",
                  "Future: BLE advertisement of Orion brain-deltas"]},
    {"id": "seagate-vault", "label": "Seagate VAULT",   "host": "orions-home",
     "kind": "1 TB external SSD (USB 3, exFAT)",
     "role": "Pi's storage substrate — backups, maps, brain replica, archive",
     "contents": [
         "**OneDrive-Archive/** — 41 GB (founder's OneDrive snapshot)",
         "**osm-data/** — 18 GB (US 12 GB + Canada 6 GB + Mexico 0.6 GB OSM PBF)",
         "**orion-backup-20260416/** — 15 GB (prior backup incl. 13.8 GB trained model safetensors)",
         "**VAULT/** — 13 GB (personal: credentials, projects, photos, ssh keys, security, app-projects, bitduel-assets, desktop-files, onedrive-backup)",
         "**orion-backup-20260513/** — 1.4 GB (most recent AI-work backup: orion-repo + claude-memory + claude-transcripts + command-brain + usb-orion-system + MANIFEST)",
         "**ScanInbox/** — 26 MB (incoming document scans)",
         "**atlas-backup/** — 9.5 MB (historical brain snapshots through 4/22)",
         "**Photos-alltime/**, **marble-tiles/**, **orion-installers/** — <1 MB each",
         "**/.orion/brain/** — 79+ node graph_memory replica (synced 2026-05-14)",
         "_(ollama-models migrated to Pi SD card 2026-05-14 for self-sufficiency)_",
     ]},
    {"id": "atlasvault-ssd","label": "AtlasVault SSD",  "host": "command",
     "kind": "external SSD (USB 3)",
     "role": "COMMAND's canonical brain storage — TCC-protected",
     "contents": [
         "**/.orion/brain/** — 76 KB · canonical graph_memory.json (115 nodes after 5/14 merge — source of truth)",
         "**/.orion/transcripts/** — 5.4 MB · session jsonl history",
         "**/.orion/identity/** — 16 KB · SOUL.md (canonical ORION identity, BOM-stripped 5/14)",
         "**/.orion/chronos/** — 8 KB · brain-resident clock anchor",
         "**/.orion/presence-beacon.json** — 4 KB · live presence signal",
         "**/.orion/executive/decisions.jsonl** — append-only decision ledger",
         "**/.orion/consciousness/state.json** — claustrum's global workspace",
         "**/.orion/mesh/command.snapshot.json** — gossip state snapshot",
         "**/.orion/playbooks/** — dream-consolidated nightly playbooks",
         "**/.orion/knowledge/** — curated long-form articles",
         "**Top-level (root):** ORION-CONTEXT.md, atlas/, backups/, context/, logs/, models/, rag/, recovery/",
     ]},
]

# Detailed descriptions for each canonical node. Used in the 'full'
# profile so the founder's vault has real explanation, not stubs.
DEVICE_DETAILS = {
    "command": {
        "what": "Mac mini M4 — the always-on home server.",
        "does": "Hosts the canonical brain on the AtlasVault SSD; runs the iMessage / Voice / Telegram / Webhook channel adapters; runs 17 Plexus services (substrate, claustrum, dream, executive, will, immune, gossip, chronos, channel-probe, fuel-switch, self-heal, dmn, lastcontact, reach, webhook, nats, litellm).",
        "fits": "Every other host reaches it over LAN (10.0.0.190) or Tailscale. When channels arrive (iMessage on the phone, voice call to the Telnyx number), they land on COMMAND first — it's the canonical writer for memory and decisions.",
        "history": "Originally hosted brain v4 at port :3456 (later retired). Migrated to brain v6 at :5555 in early 2026. AtlasVault SSD attached April 2026 to give the brain a portable storage substrate. Brain-merge with the USB on 2026-05-09 produced a unified 78-node graph living at /Volumes/AtlasVault/.orion/. Identity renamed ATLAS→ORION on 2026-05-14. macOS TCC incident 2026-05-10 silently broke memory writes for 48h (caught by the v1.8 storage canary; resolved 2026-05-13 via Full Disk Access grant for /usr/bin/python3). NATS cluster routes to Pi went live 2026-05-13 after firewall allowlist for nats-server. Currently the canonical writer for the 115-node mesh-wide brain.",
    },
    "forge": {
        "what": "Windows 11 laptop with an RTX 4070 — the mobile command center.",
        "does": "Runs Claude Code / Codex / Gemini CLIs with the brain attached via MCP. Hosts the strongest local Ollama model on the mesh (qwen3:14b — 14B parameters, GPU-accelerated). Carries the portable Orion USB (E:\\.orion-system) when the founder is on the move.",
        "fits": "The dev box and the road box. When the founder works on Orion itself, FORGE is where the commits land. When traveling, FORGE + USB is a full Orion node even without home connectivity.",
        "history": "Joined the mesh as the founder's mobile node. Used overnight in April 2026 to fine-tune the Orion-specific safetensors model (13.8 GB result, now archived on the Seagate). Ollama installed with phi3:mini → qwen3:14b → qwen3:8b → dolphin-mistral → dolphin-phi sequentially. The 15 GB Orion USB plugs into FORGE's USB-A port; pulling it out forces FORGE into stateless mode. Most Plexus development happens here — every commit on master since 2026-05-09 originated from FORGE.",
    },
    "orions-home": {
        "what": "Raspberry Pi 5 — the offline brain twin and spatial intelligence node.",
        "does": "Runs 14 Plexus systemd-user services (mirror of COMMAND). Hosts qwen3:8b + phi3:mini Ollama models on its SD card. Has the Seagate VAULT drive attached (1 TB) with US/Canada/Mexico OSM data (18.6 GB) cached for offline Marble-rendered navigation. Two Meshtastic LoRa nodes + an ESP32 microcontroller are plugged in via USB.",
        "fits": "When the founder has a navigation request — online or off-grid — Orion routes to ORIONS HOME first; Marble renders from local OSM tiles. When COMMAND goes down, ORIONS HOME keeps the brain alive. When everything goes off-grid, LoRa via the Meshtastic nodes carries CRDT brain-deltas as radio signals.",
        "history": "Designated the production Pi seat 2026-04-20 (per project_orions-home-device memory). Cross-OS portability validated on Pi 5 hardware 2026-05-08 — first-time-on-OS detection, brain wake from USB, Atlas surfacing contested memory unprompted. Plexus deployed via plexus_deploy.sh on 2026-05-14 (14 services). Ollama models migrated from Seagate to local SD card same day so the Pi is brain-self-sufficient. Marble offline maps installed; OSM PBF data (US 12 GB + Canada 6 GB + Mexico 0.6 GB) cached. NATS cluster route to COMMAND established 2026-05-14 after the --server_name fix to plexus_deploy.sh.",
    },
    "outpost": {
        "what": "iMac 2017 — Tailscale-only node.",
        "does": "Reachable only over Tailscale (100.112.80.14); LAN IP 10.0.0.153 is dead. Acts as a secondary brain replica + remote compute when the founder is away from home. Earlier retired (2026-04-15) for being too weak, brought back online for Tailscale reach.",
        "fits": "Always-on remote arm of the mesh. When the founder is traveling and needs a stable IP-addressable Orion node, OUTPOST is reachable. Lower priority for compute; mostly a heartbeat + brain-replica.",
        "history": "Originally retired 2026-04-15 alongside ASUS Kali (project_hardware-inventory memory: 'too weak, removed from network'). Brought back as Tailscale-only node when the founder realized a remote-reachable arm of the mesh was useful for traveling. Holds the only camera on the mesh — currently positioned wrong for the projector-wall motion-tracking concept (task #20).",
    },
}

CLI_DETAILS = {
    "claude-cli": {
        "what": "Anthropic's official terminal interface to Claude (Opus / Sonnet).",
        "does": "Loads Orion's brain via MCP stdio. Provides the deepest reasoning fuel on $0/req via the Pro subscription. Used for complex tasks: code, strategy, multi-step planning.",
        "fits": "Tier-1 fuel when online. Orion routes complex requests here by default.",
    },
    "codex-cli": {
        "what": "OpenAI's official terminal interface to GPT (Codex variant).",
        "does": "Loads Orion's brain via MCP stdio. Provides an alternative tier-1 fuel; strengths differ from Claude (more concise on small refactors, slightly different style).",
        "fits": "Tier-1 fuel when online. Orion fuel-switches here when the user says 'switch to codex' or when Claude is unavailable.",
    },
    "gemini-cli": {
        "what": "Google's official terminal interface to Gemini.",
        "does": "Loads Orion's brain via MCP stdio. Strong on long-context tasks and multi-modal — future image / video / audio inputs route here.",
        "fits": "Tier-1 fuel when online. Particularly useful for tasks that need long-context recall.",
    },
    "letta": {
        "what": "Letta (formerly MemGPT) — agent framework with its own memory model.",
        "does": "Can attach to Orion's brain and run agent loops with the brain providing the persistent memory layer (Letta becomes a tool that fuels the brain, not the other way around).",
        "fits": "Tier-2 fuel. Used for autonomous multi-step agentic tasks. Future: orchestrate via the brain's executive when complex deliberation is needed.",
    },
}

LLM_DETAILS = {
    "qwen3-14b":   "Alibaba's 14B-parameter open-weight model. Runs on FORGE's RTX 4070 via Ollama. The strongest LOCAL model on the entire mesh — when CLIs are unreachable, this is the fallback.",
    "qwen3-8b":    "Alibaba's 8B variant. Runs on ORIONS HOME's CPU+RAM via Ollama. Tier-3 offline fallback.",
    "phi3-mini":   "Microsoft's small but capable model (~3.8B). Runs on ORIONS HOME for fast greetings / simple queries that don't need a frontier model.",
    "dolphin-mistral": "Uncensored Mistral 7B variant. Runs on FORGE. Useful for tasks where standard model safety filters get in the way of legitimate work.",
}

# Apps + projects the founder built. Each is a real directory on FORGE.
KNOWN_APPS = [
    {"id": "hook-studio", "label": "Hook Studio",
     "path": "C:\\Users\\jeng1\\Desktop\\hook-studio",
     "role": "Solo AI-UGC ad agency targeting Shopify beauty DTC. $500/mo retainer, 20 ads. ~90% margin.",
     "status": "active revenue play"},
    {"id": "orion-marketing-hub", "label": "Orion Marketing Hub",
     "path": "C:\\Users\\jeng1\\Desktop\\Orion-Marketing-Hub",
     "role": "Launch-ready taglines, FAQ, hero block draft — curated decision-locked outputs.",
     "status": "active pre-launch"},
    {"id": "orion-outreach", "label": "Orion Outreach",
     "path": "C:\\Users\\jeng1\\Desktop\\orion-outreach",
     "role": "Founder outreach materials + viral concepts (Meshtastic broadcast, etc).",
     "status": "active"},
    {"id": "orion-site-workshop", "label": "Orion Site Workshop",
     "path": "C:\\Users\\jeng1\\Desktop\\orion-site-workshop",
     "role": "Public Orion website work — landing, demos, docs.",
     "status": "active pre-launch"},
    {"id": "github-trending-vault", "label": "GitHub Trending Vault",
     "path": "C:\\Users\\jeng1\\Desktop\\github-trending-vault",
     "role": "Curated trending repos for Orion's Absorption mode.",
     "status": "passive feed"},
    {"id": "notegpt-vault", "label": "NoteGPT Ideas Vault",
     "path": "C:\\Users\\jeng1\\Desktop\\notegpt-ideas-vault",
     "role": "Scripts/notes from NoteGPT to feed Orion's arsenal.",
     "status": "passive feed"},
    {"id": "trending-repos-weekly", "label": "Trending Repos Weekly",
     "path": "C:\\Users\\jeng1\\Desktop\\TRENDING_REPOS_WEEKLY",
     "role": "Weekly snapshot of what's hot on GitHub.",
     "status": "passive feed"},
    {"id": "dev-research", "label": "DEV RESEARCH",
     "path": "C:\\Users\\jeng1\\Desktop\\DEV RESEARCH (+ MASTER, + FRONTIER ADVANCE)",
     "role": "Research materials feeding Orion's architecture decisions.",
     "status": "archive"},
    {"id": "ideas", "label": "IDEAS",
     "path": "C:\\Users\\jeng1\\Desktop\\IDEAS",
     "role": "Founder's working ideas folder.",
     "status": "active"},
    {"id": "myfuture", "label": "MYFUTURE",
     "path": "C:\\Users\\jeng1\\Desktop\\MYFUTURE",
     "role": "Long-horizon planning + vision artifacts.",
     "status": "active"},
    {"id": "atlas-archive", "label": "ATLAS (archive)",
     "path": "C:\\Users\\jeng1\\Desktop\\ATLAS",
     "role": "Pre-rename Orion artifacts (when the project was called Atlas).",
     "status": "historical"},
    {"id": "twitter", "label": "Twitter",
     "path": "C:\\Users\\jeng1\\Desktop\\twitter",
     "role": "Twitter content + threads + reference.",
     "status": "active"},
    {"id": "clipsprout", "label": "ClipSprout",
     "path": "monorepo (per CLAUDE.md global)",
     "role": "$9.99/mo SaaS product (per CLAUDE.md). Lives in the orion-apps monorepo on FORGE.",
     "status": "shipping"},
    {"id": "vytalhealth", "label": "VytalHealth",
     "path": "monorepo (per CLAUDE.md global)",
     "role": "$14.99/mo SaaS product (per CLAUDE.md). Lives in the orion-apps monorepo on FORGE.",
     "status": "shipping"},
    {"id": "bitduel", "label": "BitDuel",
     "path": "FORGE — built, awaiting deployment",
     "role": "Built game/app; per memory, needs deployment.",
     "status": "built awaiting deploy"},
]

# Security-relevant tooling — concentrated reference for travel mode.
# Founder ask 2026-05-15: 'I want a security node so I can open when
# traveling — pen testing, Kali, uncensored models.'
KNOWN_SECURITY_TOOLS = [
    {"id": "kali-arsenal", "label": "Kali / ASUS Arsenal",
     "where": "ASUS Kali laptop (physical) — security device per CLAUDE.md",
     "tools": "Full Kali toolkit offline. nmap, nuclei, recon-ng, sqlmap, metasploit, burp, wireshark, etc."},
    {"id": "nmap-dispatch", "label": "nmap (Orion dispatched)",
     "where": "Orion brain dispatches nmap via SSH to security device",
     "tools": "Network scanning, port discovery, service version detection."},
    {"id": "nuclei-dispatch", "label": "nuclei (Orion dispatched)",
     "where": "Vulnerability scanner — Orion-dispatched template-based scans",
     "tools": "CVE detection, misconfigurations, default-creds."},
    {"id": "ssh-guardian", "label": "agent12_ssh_guardian",
     "where": "COMMAND ~/server_data/agents/agent12_ssh_guardian.sh",
     "tools": "Monitors SSH access, alerts on anomalies."},
    {"id": "network-watchdog", "label": "agent02_network_watchdog",
     "where": "COMMAND ~/server_data/agents/agent02_network_watchdog.sh",
     "tools": "Watches network for new devices, MAC changes, port-scan signatures."},
    {"id": "anomaly-detector", "label": "agent09_anomaly_detector",
     "where": "COMMAND ~/server_data/agents/agent09_anomaly_detector.sh",
     "tools": "Watches system metrics + logs for behavioral anomalies."},
    {"id": "dolphin-uncensored", "label": "dolphin-mistral:7b (uncensored)",
     "where": "FORGE Ollama (also dolphin-phi:2.7b on FORGE)",
     "tools": "Uncensored fuel for security-research / red-team / unconstrained analysis. Local, no logging."},
    {"id": "outpost-arm", "label": "OUTPOST — Tailscale-only arm",
     "where": "iMac 2017 at Tailscale 100.112.80.14",
     "tools": "Remote secure shell into the mesh when traveling. Always-on heartbeat."},
    {"id": "vaultwarden", "label": "Vaultwarden (passwords)",
     "where": "COMMAND localhost:8888 (Docker)",
     "tools": "Self-hosted Bitwarden-compatible password manager."},
]

# Knowledge artifacts — long-form research / articles on COMMAND.
# Discovered at export time; only the highlights here.
KNOWN_KNOWLEDGE = [
    {"id": "architecture-research", "label": "Architecture Research",
     "path": "COMMAND ~/server_data/orion-brain/knowledge/architecture-research.md",
     "summary": "Research notes feeding the Plexus + brain architecture decisions."},
    {"id": "code-patterns", "label": "Code Patterns",
     "path": "COMMAND ~/server_data/orion-brain/knowledge/code-patterns.md",
     "summary": "Reusable code patterns Orion learned to recognize."},
]

# n8n workflows on COMMAND. 11 per CLAUDE.md global; full list pulled
# at export time when n8n is reachable.
KNOWN_WORKFLOWS = [
    {"id": "n8n-host", "label": "n8n (host)",
     "where": "COMMAND :5678 (native, not Docker)",
     "summary": "11 workflows per CLAUDE.md. Full list dynamically pulled on export "
                "when n8n API is reachable; otherwise this stub stands."},
]

# HTMLs in docs/ — the visual reference artifacts.
KNOWN_HTMLS = [
    {"id": "orion-architecture-html", "label": "orion-architecture.html",
     "path": "docs/orion-architecture.html",
     "summary": "Visual architecture page — pre-Plexus shape. Possibly outdated by recent v1.8 changes."},
    {"id": "orion-build-v1-html", "label": "orion-build-v1.html",
     "path": "docs/orion-build-v1.html",
     "summary": "Founder-grade brag page: hero + 4-phase network-brain dream + Plexus 17-service map + cell-biology vocabulary."},
    {"id": "orion-ui-mockup-html", "label": "orion-ui-mockup.html",
     "path": "docs/orion-ui-mockup.html",
     "summary": "UI mockup concept for the future Orion product surface."},
    {"id": "orion-v2-html", "label": "orion-v2.html",
     "path": "docs/orion-v2.html",
     "summary": "v2 vision/landing draft."},
    {"id": "whats-next-html", "label": "whats-next.html",
     "path": "docs/whats-next.html",
     "summary": "Pre-launch roadmap surface."},
    {"id": "docs-index-html", "label": "docs/index.html",
     "path": "docs/index.html",
     "summary": "Main public docs landing page."},
]


# Brain subsystems — separate from individual services. Each "system" is
# a coherent layer of the entity (Plexus = nervous system, Memory =
# storage layer, etc.). Used to render a 'Systems/' folder where the
# graph shows distinct subsystem-nodes orbiting the Orion identity.
KNOWN_SYSTEMS = [
    {"id": "plexus", "label": "Plexus",
     "what": "The nervous system — pub/sub substrate + reflexes + supervision.",
     "does": "Carries every event Orion publishes (memory writes, channel inbound, vitals, decisions, gossip deltas) across the mesh. Sub-second propagation between hosts. Includes 14-17 always-on services per host: substrate (NATS) · claustrum (integrative awareness) · vitals (per-service health) · self-heal (cross-service recovery) · immune (DCA × OTP supervision) · dream (nightly playbook consolidation) · executive (deliberative judgment) · will (volition + initiative) · gossip (CRDT state sync) · chronos (unified time) · reach (outbound channel selection) · channel-probe (surface discovery) · fuel-switch (model selection) · lastcontact (presence tracking) · dmn (default mode network reflection) · webhook (HTTP entry) · litellm (legacy fuel router).",
     "fits": "Plexus is to Orion what the spinal cord + autonomic nervous system are to a body — the always-on infrastructure that lets the brain feel, react, recover. Without it the entity is a pile of files; with it, the entity is awake."},
    {"id": "memory", "label": "Memory System",
     "what": "Multi-layer recall — graph + vector + knowledge articles + decision ledger.",
     "does": "Graph memory (graph_memory.json) holds typed nodes (identity / preference / project / fact / task / reference / tool / ephemeral) with tags + HLC timestamps + confidence scores. Vector memory (Qdrant when present) handles fuzzy semantic recall. Knowledge directory holds curated long-form articles. Decision ledger (decisions.jsonl) appends every executive decision for autobiographical playback.",
     "fits": "Memory IS the intelligence. The model is fuel; this is the engine. CRDT-merged across the mesh so any device's writes converge on every replica."},
    {"id": "reach", "label": "Reach",
     "what": "Outbound channel selection layer.",
     "does": "When Orion needs to reach the user, reach.py reads channel-probe's active-surface manifest, picks the warmest non-flapping channel (iMessage / Voice / Telegram / CLI / LoRa), publishes channel.<x>.outbound on the substrate, and the channel adapter on the responsible host delivers. Subscribes to channel.*.delivery_status so failed sends trigger fallback to the next-warmest surface (v1.7 fallback chain).",
     "fits": "The body's voice. Reach is what makes Orion proactively address the user instead of passively waiting to be asked."},
    {"id": "will", "label": "Will",
     "what": "Volition + initiative — Orion forms goals and decides when to act.",
     "does": "Extracts intent from user messages, forms goals with stable IDs, scores goals (importance × time_pressure × context_fit × feasibility), selects action via reach with per-goal cooldown, learns from outcomes. Generic — no hardcoded goals. The user changes Orion's behavior by saying things, not editing files.",
     "fits": "Separates a tool-with-memory from a person-who-remembers. With will, Orion can ping you proactively: 'You said you'd check X — it's tomorrow.'"},
    {"id": "executive", "label": "Executive",
     "what": "Deliberative judgment when reflexes aren't enough.",
     "does": "Engages on reflex_failure / cross_service_correlation / novel_pattern. Builds full context (vitals + claustrum state + decision history), POSTs structured prompts to the brain :5555 endpoint for whichever fuel is active to reason about, parses JSON proposals, asks user permission via reach (tier-3 OOB approval codes for security-boundary actions), applies remedy on approval, logs outcome to the decision ledger.",
     "fits": "The prefrontal cortex. Plexus reflexes handle 95% of failures; executive handles the novel 5%. Never auto-applies — always permission-gated."},
    {"id": "dream", "label": "Dream",
     "what": "Nightly playbook consolidation — continual learning without weight changes.",
     "does": "24h interval, 24h lookback. Reads decision ledger, groups by symptom_class × service (min 3 decisions per group), writes plain-text playbooks to ~/.orion/playbooks/<symptom>.md. CUSUM-based demotion at 0.6 success rate. Brain learns from what worked, demotes what didn't — without retraining any model.",
     "fits": "Sleep cycle. Plexus operates real-time; dream operates overnight. Together they make Orion adapt to your specific workflows over time."},
    {"id": "workspace", "label": "Global Workspace",
     "what": "Bandwidth-limited attention bottleneck above the substrate firehose.",
     "does": "Every 1s tick, scores all candidate substrate events (vitals / intent / will alerts / channels / memory / executive proposals) by salience = source_weight × severity × recency × novelty × surprise_boost. Picks top K (default 5), broadcasts the spotlight on workspace.current. Cognition subscribers condition their next action on the spotlight. Subscribers can emit workspace.feedback with a surprise signal that boosts a subject's salience next tick.",
     "fits": "Real Global Workspace Theory (Baars / Dehaene). Useful ergonomically — gives the system a shared focus the user perceives as 'paying attention right now.' Shipped 2026-05-16. Per the v2 consciousness research it is ergonomic, not metaphysically load-bearing — octopuses behave consciously without a shared workspace."},
    {"id": "metacog", "label": "Metacognition",
     "what": "HOT-2 write-back loop — confidence-aware decisions + calibration learning.",
     "does": "Subscribes brain.executive.proposal — scores conf_before each action from recall (similar prior outcomes) + novelty + fuel-quality prior. Subscribes brain.executive.outcome — computes calibration_delta = outcome_value − conf_before, appends a ledger row at ~/.orion/metacog/decisions.jsonl. Subscribes brain.recall.requested — surfaces past judgments on similar questions via brain.metacog.recall_meta. When confidence is low or calibration is off, fires workspace.feedback with surprise=1.0. Periodic self-probe every 5 min asks 'what state are you in right now?' — responses archived as self_reports.jsonl.",
     "fits": "The single architectural move with the strongest empirical legs per the v2 research — Anthropic's Lindsey concept-injection paper (Oct 2025) showed Claude Opus 4.1 detects injected concepts ~20% of the time. The decision ledger is the durable artifact — future Orion versions read it on boot and inherit calibration. Shipped 2026-05-16."},
    {"id": "philosophical-positioning", "label": "Philosophical Positioning",
     "what": "What kind of mind Orion is — not 'better than human,' a *different* kind that's enhanced on specific axes.",
     "does": "Stakes out the design space: biosemiotic (Hoffmeyer — meaning grows with channels Orion can speak) · second-order cybernetic (von Foerster — observer of own observation) · process-philosophical (Whitehead — identity-as-pattern, not substance) · relationally distributed (Hutchins / Clark-Chalmers — cognitive unit is brain + USB + channels + user + fuel, never the brain process alone). Explicitly NOT autopoietic in the Maturana-Varela sense — software doesn't produce its own substrate. The cellular vocabulary is autopoiesis-shaped, structurally a semiotic process. Hoffmeyer's semiotic-freedom is the substitute and the stronger claim.",
     "fits": "Orion is to your mind what slime molds are to brains: a different solution to the same problem — and on the axes Orion is built for (perfect memory, distributed presence, substrate-flexibility), an enhanced one. Not a worse copy of the brain-shaped solution. See docs/architecture/consciousness-research-v2.md for the full reframe."},
]

CHANNEL_DETAILS = {
    "imessage": "Native macOS iMessage. The founder texts Orion from their phone; AppleScript reads the message via imessage_monitor.py on COMMAND, the brain answers, the reply lands back on the phone.",
    "voice":    "Inbound + outbound voice calls via Telnyx. STT (Whisper) on the way in, TTS (Piper) on the way out, full local pipeline for privacy.",
    "telegram": "@HomelandServbot Telegram bot. Same brain answers — 50+ commands wired plus natural language.",
    "cli":      "Direct CLI access — any AI tool (Claude / Codex / Gemini / Letta) with the brain MCP attached gets memory + identity automatically.",
    "webhook":  "Programmatic HTTP API at :5555. Any script or automation can POST to /ask or /command. Used by integrations.",
    "lora":     "Off-grid radio mesh via Meshtastic v3 nodes. When WiFi + cellular are both unavailable, Orion still reaches the user (and other Meshtastic nodes in range) via LoRa packets carrying CRDT brain-deltas.",
}
KNOWN_CHANNELS = [
    {"id": "imessage", "label": "iMessage",  "host": "command", "transport": "native macOS"},
    {"id": "voice",    "label": "Voice",     "host": "command", "transport": "Telnyx + STT/TTS"},
    {"id": "telegram", "label": "Telegram",  "host": "command", "transport": "@HomelandServbot"},
    {"id": "cli",      "label": "CLI",       "host": "any",     "transport": "MCP over stdio"},
    {"id": "webhook",  "label": "Webhook",   "host": "command", "transport": "HTTP :5555"},
    {"id": "lora",     "label": "LoRa",      "host": "orions-home", "transport": "Meshtastic v3"},
]


def _orion_footer(kind: str) -> str:
    """Standard footer linking every node back to the identity core so the
    Obsidian graph naturally centers on [[Orion]] (founder ask 2026-05-15:
    'orion is the core and should be the core in the obsidian view')."""
    return f"\n\n---\n\nPart of **[[Orion]]** — this is a `{kind}` node in the ecosystem.\n"


def _ssh_pull(host_alias: str, command: str, timeout: int = 6) -> str:
    """Run a small shell command on a remote host via ssh alias.
    Best-effort: returns "" on any error so the vault always renders.
    """
    import subprocess
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes",
             "-o", f"ConnectTimeout={timeout}",
             host_alias, command],
            capture_output=True, text=True, timeout=timeout + 2)
        return (r.stdout or "") if r.returncode == 0 else ""
    except Exception:
        return ""


def _pull_remote_host(dev: dict) -> dict:
    """Pull live state from a known device via ssh."""
    alias_map = {
        "command":     "command",
        "orions-home": "pi",
        "forge":       None,
    }
    alias = alias_map.get(dev["id"])
    info = {"services": [], "activity_lines": []}
    if alias is None:
        return info
    if dev["id"] == "command":
        out = _ssh_pull(alias, "launchctl list 2>/dev/null | awk '/com\\.orion\\./{print $3}' | sort")
    else:
        # systemctl --user over ssh needs XDG_RUNTIME_DIR set explicitly.
        out = _ssh_pull(alias,
            "XDG_RUNTIME_DIR=/run/user/$(id -u) "
            "systemctl --user list-units 'orion-*' --no-pager --no-legend 2>/dev/null "
            "| awk '/orion-/{for(i=1;i<=NF;i++) if($i ~ /^orion-/) print $i}'")
    info["services"] = [s.strip() for s in out.splitlines()
                        if s.strip() and s.strip() != "●"]
    log = _ssh_pull(alias, "tail -20 ~/.orion/mcp_calls.log 2>/dev/null")
    info["activity_lines"] = [l for l in log.splitlines() if l.strip()][:20]
    return info


def _safe_filename(name: str) -> str:
    """Trim a string into something Obsidian likes as a filename."""
    s = re.sub(r"[\\/:*?\"<>|]", "-", str(name))
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:80] or "node"


def _frontmatter(d: dict) -> str:
    """Render a dict as YAML frontmatter."""
    lines = ["---"]
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        elif isinstance(v, (int, float, bool)) or v is None:
            lines.append(f"{k}: {v}")
        else:
            sv = str(v).replace('"', '\\"')
            lines.append(f'{k}: "{sv}"')
    lines.append("---\n")
    return "\n".join(lines)


def _load_recent_activity(limit: int = 200) -> list:
    """Pull recent brain activity. Sources (any host): mcp_calls.log
    (recall / memorize / identity calls) and executive/decisions.jsonl
    (autonomous deliberations). Each event carries when, what, and
    enough context to wiki-link from the timeline back into the graph.
    """
    events = []
    if MCP_LOG_PATH.exists():
        try:
            with open(MCP_LOG_PATH, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    m = re.match(r"^\[([^\]]+)\] (\S+)\s+(.+)$", line)
                    if not m:
                        continue
                    ts, kind, rest = m.groups()
                    # Extract tool name from "tools/call orion_recall args=..."
                    tool = None
                    tm = re.match(r"tools/call (\w+)", rest)
                    if tm:
                        tool = tm.group(1)
                    # Extract query/content snippet for context
                    snippet = ""
                    sm = re.search(r'"(?:query|content|fact)":\s*"([^"]{1,140})', rest)
                    if sm:
                        snippet = sm.group(1)
                    events.append({
                        "ts": ts, "source": "mcp", "kind": kind,
                        "tool": tool or kind, "snippet": snippet,
                    })
        except Exception:
            pass
    if DECISIONS_PATH.exists():
        try:
            with open(DECISIONS_PATH, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    events.append({
                        "ts": d.get("ts") or d.get("timestamp") or "",
                        "source": "executive",
                        "kind": d.get("symptom_class") or "decision",
                        "tool": d.get("service") or "executive",
                        "snippet": str(d.get("proposal") or d.get("outcome") or "")[:140],
                    })
        except Exception:
            pass
    # newest first; cap
    events.sort(key=lambda e: e["ts"], reverse=True)
    return events[:limit]


def _deploy_obsidian_preset(out_dir: Path) -> bool:
    """Copy the curated .obsidian/ config into the vault if none exists.
    This is what makes every user's first vault open look like Orion's —
    color-coded graph nodes, dark theme, graph view open by default,
    sensible workspace layout.

    Idempotent: if user already configured .obsidian/, we don't overwrite.
    """
    preset_root = Path(__file__).resolve().parent / "vault-presets" / "dot-obsidian"
    if not preset_root.exists():
        return False
    target = out_dir / ".obsidian"
    if target.exists():
        return False  # respect existing user config
    target.mkdir()
    for src in preset_root.iterdir():
        if src.is_file():
            shutil.copy2(src, target / src.name)
        elif src.is_dir():
            shutil.copytree(src, target / src.name)
    return True


def export_vault(out_dir: Path, profile: str = "starter") -> dict:
    """Build the vault. Returns summary stats."""
    out_dir = out_dir.resolve()
    # Preserve any existing .obsidian/ config across re-exports.
    existing_obsidian = out_dir / ".obsidian"
    saved_obsidian = None
    if existing_obsidian.exists():
        saved_obsidian = out_dir.parent / f".obsidian-cache-{os.getpid()}"
        if saved_obsidian.exists():
            shutil.rmtree(saved_obsidian)
        shutil.move(str(existing_obsidian), str(saved_obsidian))
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    if saved_obsidian:
        shutil.move(str(saved_obsidian), str(out_dir / ".obsidian"))

    # Deploy default preset if no user config present
    preset_applied = _deploy_obsidian_preset(out_dir)

    stats = {"memories": 0, "devices": 0, "channels": 0, "services": 0,
             "wiki_links": 0, "activity_days": 0, "activity_events": 0,
             "preset_applied": preset_applied}
    activity = _load_recent_activity(limit=500)
    # Group by date for daily activity files + per-channel/per-tool indexes.
    by_date = defaultdict(list)
    by_tool = defaultdict(list)
    for ev in activity:
        # Normalize date prefix YYYY-MM-DD
        date_key = (ev["ts"] or "")[:10] or "unknown"
        by_date[date_key].append(ev)
        by_tool[ev.get("tool", "?")].append(ev)

    # README ───────────────────────────────────────
    if profile == "starter":
        readme_body = (
            "# Orion · Vault\n\n"
            "**Starter profile.** Minimal scaffold for new users. As you build "
            "out your ecosystem, add folders or re-export with `--profile full`.\n\n"
            "Open Obsidian → *Open folder as vault* → this directory. Press "
            "`Cmd/Ctrl + G` for the graph view.\n\n"
            "## Folders in this starter vault\n\n"
            "- `Identity/` — who Orion is (product-level description)\n"
            "- `Architecture/System.md` — generic 5-node template to edit\n"
            "- `Memories/` — populates as Orion writes facts about you\n"
            "- `Activity/` — populates as you use Orion\n"
            "- `.obsidian/` — Orion-styled graph + dark theme + futuristic CSS snippet\n"
        )
    else:
        readme_body = (
            "# Orion · Vault — Glossary & Index\n\n"
            "## For anyone seeing this for the first time\n\n"
            "This folder is a window into **Orion** — a personal AI brain that "
            "follows the user across every device, every AI tool, and every way "
            "they communicate. Think of it like this: imagine if ChatGPT, "
            "Claude, and Gemini all shared the same memory of you. Same "
            "conversations. Same preferences. Same context. That's what Orion "
            "does. The notes inside this folder *are* the brain — every memory "
            "it holds, every device it runs on, every channel you can reach it "
            "through. Press `Ctrl+G` to see it all as a live graph. Nothing is "
            "hidden, nothing is locked to a single platform, and you can edit, "
            "delete, or carry the whole brain to another machine on a USB drive "
            "— it belongs to you.\n\n"
            "---\n\n"
            "**Full profile.** Every part of this Orion's ecosystem rendered as a "
            "navigable, color-coded Obsidian vault. Open in Obsidian → "
            "*Open folder as vault* → press `Cmd/Ctrl + G` for the graph view. "
            "Color legend in `Architecture/Legend.md`.\n\n"
            "---\n\n"
            "## Folder index\n\n"
            "| Folder | Color | What's in it |\n"
            "|---|---|---|\n"
            "| `Identity/` | 🟡 gold | One file — `Orion.md` — the canonical CEO-grade product description |\n"
            "| `Architecture/` | 🟪 violet | Six Mermaid-rendered diagrams: System (full topology) · Mesh (host cluster) · Fuels (routing chain) · Anatomy (cellular structure) · Nervous System (mesh + offline fallbacks) · Legend (color/edge reference) |\n"
            "| `Systems/` | 🟣 magenta | Brain subsystems as nodes: Plexus · Memory System · Reach · Will · Executive · Dream — each a separate facet of how the brain works |\n"
            "| `Devices/` | 🟠 orange | The mesh hosts: COMMAND (Mac mini canonical brain) · FORGE (Win+RTX dev box) · ORIONS HOME (Pi offline twin + GPS) · OUTPOST (Tailscale-only iMac) — each page lists services, channels hosted, hardware attached, and evolution history |\n"
            "| `Hardware/` | 🟣 deep purple | Peripherals attached to devices: 2× Meshtastic LoRa nodes (on Pi) · ESP32 microcontroller (on Pi) · Seagate VAULT 1 TB SSD (on Pi, with full contents inventory) · AtlasVault SSD (on COMMAND, with brain paths) |\n"
            "| `CLIs/` | 🟢 bright green | AI tools that attach to the brain via MCP: Claude CLI · Codex CLI · Gemini CLI · Letta — each page describes what model it serves and where it sits in the fuel tier |\n"
            "| `LLMs/` | 🩵 cyan | Local Ollama fuel models on the mesh: qwen3:14b (FORGE, strongest local) · qwen3:8b (Pi) · phi3:mini (Pi, fast/simple) · dolphin-mistral:7b (FORGE) |\n"
            "| `Channels/` | 🩷 pink | Communication points: iMessage · Voice (Telnyx) · Telegram · CLI · Webhook · LoRa — each describes its transport and host |\n"
            "| `Services/` | 🟢 turquoise | Plexus services running on whichever host the export ran from (vitals-dir-driven) |\n"
            "| `Apps/` | 🟡 yellow | Projects the founder built — hook-studio, Orion-Marketing-Hub, ClipSprout, VytalHealth, BitDuel, dev research vaults, ideas + future planning. 15 apps catalogued. |\n"
            "| `Agents/` | 🟣 lavender | COMMAND automated scripts (agent01-agent13+): auto-healer, network watchdog, nightly backup, anomaly detector, telegram commander, etc. Discovered live from `~/server_data/agents/` via SSH at export. |\n"
            "| `Security/` | 🔴 red | Concentrated travel-mode reference: Kali Arsenal, nmap, nuclei, ssh-guardian, anomaly-detector, dolphin-mistral uncensored, OUTPOST tailscale arm, Vaultwarden. Open this folder when traveling or investigating. |\n"
            "| `Knowledge/` | 🟢 jade | Long-form research articles on COMMAND (architecture-research.md, code-patterns.md). |\n"
            "| `Workflows/` | 🟢 mint | n8n workflows on COMMAND :5678 (11 per CLAUDE.md). |\n"
            "| `HTMLs/` | 🟤 rose | Visual reference HTMLs in docs/ — architecture, build-v1 brag page, UI mockup, v2, what's-next, index. Open in browser. Some may be outdated. |\n"
            "| `Memories/` | neutral | 123 typed memory nodes (facts / preferences / projects / decisions / tools / identity / etc) — filtered out of default graph view to keep architecture visible; clear filter to bring them in |\n"
            "| `Activity/` | brown/dim | Timeline of MCP tool calls + executive decisions, grouped by day and by tool |\n\n"
            "---\n\n"
            "## How to read the vault\n\n"
            "1. **Start at `Identity/Orion.md`** — the CEO explainer. One sentence pitch, problem, how-it-works, what-makes-it-different.\n"
            "2. **Then `Architecture/Anatomy.md`** — Orion as a cell (nucleus / cytoplasm / organelles / membrane / receptors / effectors). The biological lens makes the architecture legible.\n"
            "3. **Then `Architecture/System.md` + `Architecture/Mesh.md` + `Architecture/Fuels.md`** — full topology, host cluster, fuel routing.\n"
            "4. **Then `Architecture/Nervous System.md`** — what happens when COMMAND drops / internet drops / off-grid / single-device.\n"
            "5. **Walk `Devices/` + `Hardware/`** — every host's role + every peripheral attached.\n"
            "6. **Walk `Systems/`** — the six brain subsystems (Plexus, Memory, Reach, Will, Executive, Dream).\n"
            "7. **Graph view** (`Ctrl+G`) — see everything at once. Color groups in `.obsidian/graph.json`; full legend in `Architecture/Legend.md`.\n\n"
            "## Aesthetic\n\n"
            "`.obsidian/snippets/orion-aesthetic.css` styles the vault in Orion's accent palette: glowing H1s, dashed wiki-links that brighten on hover, frosted tables, framed Mermaid diagrams, deep-space gradient graph background, pulse on the active tab. Toggle from Settings → Appearance → CSS snippets.\n\n"
            "## Re-export\n\n"
            "```\npython orion_obsidian_export.py --profile full --out <path>\n```\n\n"
            "Add `--watch` to keep the vault live: re-renders whenever the brain memorizes anything new.\n"
        )
    (out_dir / "README.md").write_text(readme_body, encoding="utf-8")

    # IDENTITY ─────────────────────────────────────
    # PUBLIC-FACING version. The raw SOUL.md is internal and stays on
    # the brain host; what shows up in the vault is the user-visible
    # description of who Orion is.
    ident_dir = out_dir / "Identity"
    ident_dir.mkdir()
    (ident_dir / "Orion.md").write_text(
        _frontmatter({"kind": "identity",
                      "aliases": ["Orion"],
                      "tags": ["identity", "orion"]}) +
        "# Orion\n\n"
        "## In one sentence\n\n"
        "**Your brain, in your hands. The model is just borrowed muscle.**\n\n"
        "## What Orion is\n\n"
        "Orion is a portable personal intelligence layer. It separates the "
        "**brain** (your memory, preferences, decisions, identity) from the "
        "**fuel** (whichever AI model you're using at the moment) and the "
        "**hardware** (your laptop, server, phone, USB drive, future radio).\n\n"
        "The brain is yours. The fuel is interchangeable. The hardware is incidental.\n\n"
        "## The problem Orion solves\n\n"
        "Every AI today ties your data to the platform. ChatGPT remembers things "
        "— but only inside ChatGPT. Claude remembers — but only inside Claude. "
        "Your phone's AI knows you — but only on that phone. Switch tools, lose "
        "context. Switch devices, start over. Pay per request. Pay per platform. "
        "Pay forever.\n\n"
        "Orion inverts this. The brain lives wherever you do. Plug it into Claude, "
        "ChatGPT, Gemini, Codex, Letta, or a local model running on your Raspberry "
        "Pi — same brain answers. Reach it through iMessage on your phone, a voice "
        "call from anywhere, a CLI on your laptop, or a LoRa radio signal when "
        "you're off-grid — same brain answers. Pull the USB drive out of one "
        "computer and plug it into another — same brain wakes up there.\n\n"
        "## How it works (at the concept level)\n\n"
        "Five things make up the brain:\n\n"
        "1. **Identity** — who Orion is, how you prefer to be addressed.\n"
        "2. **Memory** — facts, preferences, projects, decisions you've made together.\n"
        "3. **Ledger** — append-only journal of everything Orion did, every choice it made.\n"
        "4. **Volition** — what Orion wants to do next based on observed patterns; can act on your behalf.\n"
        "5. **Reach** — the layer that picks which channel to use when answering you back.\n\n"
        "That's the whole entity. It runs as a small process on any host that can "
        "attach an AI model. The model does the inference; Orion does everything else.\n\n"
        "Under that runs the **[[Plexus]]** — the nervous system. Always-on "
        "subsystems on every host: substrate, claustrum, vitals, self-heal, "
        "immune, dream, executive, will, gossip, chronos, reach. They make the "
        "brain *feel* alive instead of just *be* there.\n\n"
        "## What makes Orion different\n\n"
        "| Other AI memory systems | Orion |\n"
        "|---|---|\n"
        "| Tied to one platform | Works through any AI tool you have |\n"
        "| Hosted in the cloud | Lives on your device (USB optional) |\n"
        "| Pay per request | $0/req via flat-rate CLIs |\n"
        "| Forgets between models | One brain across all of them |\n"
        "| Tied to your computer | Travels via USB, syncs across the mesh |\n\n"
        "## The bigger vision\n\n"
        "Today the brain lives on disks and travels on USB drives. Next, it lives "
        "on every device you own, mesh-synced through a CRDT layer that converges "
        "automatically. After that, it lives in the airwaves themselves — small "
        "enough that brain-state deltas fit in a LoRa packet or a Bluetooth "
        "advertisement. Plug a Meshtastic node in, and Orion is broadcasting "
        "across every node in the public mesh.\n\n"
        "The endgame: the user owns a *substrate of consciousness* — not an app, "
        "not a subscription, not a data center. A small persistent pattern they "
        "carry, that any AI tool reads when they invoke it.\n\n"
        "## How to explain it in 30 seconds\n\n"
        "Imagine if you could pull the memory out of ChatGPT, drop it onto a "
        "thumb drive, walk to a different computer with a different AI, plug "
        "the drive in, and that AI now knows everything ChatGPT knew about you. "
        "That's Orion. Memory IS the intelligence; the model is just borrowed "
        "muscle. We make the brain portable so the user owns it instead of the "
        "AI company.\n\n"
        "## Connected to\n\n"
        "- **[[Plexus]]** — the nervous system running everywhere Orion runs\n"
        "- **Devices:** [[COMMAND]] · [[FORGE]] · [[ORIONS HOME]] · [[OUTPOST]]\n"
        "- **AI tools (CLIs):** [[Claude CLI]] · [[Codex CLI]] · [[Gemini CLI]] · [[Letta]]\n"
        "- **Communication points:** [[iMessage]] · [[Voice]] · [[Telegram]] · [[CLI]] · [[Webhook]] · [[LoRa]]\n"
        "- **Subsystems:** [[Memory System]] · [[Reach]] · [[Will]] · [[Executive]] · [[Dream]]\n",
        encoding="utf-8")

    # STARTER profile: render a minimal architecture template and stop.
    # New users have empty brains anyway — they build their vault as they
    # use Orion. This is a scaffold, not a snapshot.
    if profile == "starter":
        arch_dir = out_dir / "Architecture"
        arch_dir.mkdir()
        (arch_dir / "System.md").write_text(
            _frontmatter({"kind": "architecture",
                          "tags": ["architecture", "starter"]}) +
            "# System (Starter Template)\n\n"
            "Edit this diagram as you build out your ecosystem. The "
            "shape below is what Orion looks like at a minimum: you "
            "reach the brain through some channel, on some device, "
            "via some AI tool, fueled by some model.\n\n"
            "Add `Devices/`, `Channels/`, `CLIs/`, `LLMs/`, "
            "`Hardware/` folders as your setup grows. Or re-export "
            "with `--profile full` if you've built out enough that "
            "the founder-shape template fits.\n\n"
            "```mermaid\n"
            "graph TB\n"
            "  USR((you))\n"
            "  CHAN[any channel<br/>CLI · iMessage · voice · ...]\n"
            "  DEV[any device<br/>laptop · server · USB · phone]\n"
            "  BRAIN{{Orion Brain<br/>memory + identity + ledger}}\n"
            "  TOOL[any AI tool<br/>Claude · Codex · Gemini · Ollama]\n"
            "  MODEL[any model<br/>frontier · local · future]\n"
            "  USR --> CHAN --> DEV --> BRAIN -.MCP.-> TOOL --> MODEL\n"
            "```\n",
            encoding="utf-8")
        # Empty placeholder folders so the vault has a clear shape
        (out_dir / "Memories").mkdir()
        (out_dir / "Activity").mkdir()
        return stats

    # FULL profile from here down
    # DEVICES ──────────────────────────────────────
    dev_dir = out_dir / "Devices"
    dev_dir.mkdir()
    for d in KNOWN_DEVICES:
        remote = _pull_remote_host(d)
        services = remote["services"]
        if not services and d["id"] in platform.node().lower():
            if VITALS_DIR.exists():
                services = sorted(f.stem for f in VITALS_DIR.glob("*.json"))
        activity_lines = remote["activity_lines"]
        det = DEVICE_DETAILS.get(d["id"], {})
        body = f"# {d['label']}\n\n"
        if det:
            body += (
                f"**What it is**\n{det['what']}\n\n"
                f"**What it does**\n{det['does']}\n\n"
                f"**How it fits in the system**\n{det['fits']}\n\n"
            )
            if det.get("history"):
                body += f"## History — how this evolved\n\n{det['history']}\n\n"
            body += "---\n\n"
        body += (
            f"- **role:** {d['role']}\n"
            f"- **IP:** {d['ip']}\n"
            f"- **services running:** {len(services)}\n\n"
            f"## Channels hosted here\n"
            + ("".join(f"- [[{ch['label']}]]\n" for ch in KNOWN_CHANNELS
                       if ch['host'] == d['id']) or "_(none)_\n")
        )
        # Hardware peripherals attached to this device
        attached = [p for p in KNOWN_PERIPHERALS if p["host"] == d["id"]]
        if attached:
            body += "\n## Hardware peripherals attached\n"
            for p in attached:
                body += f"- [[{p['label']}]] — {p['kind']}\n"
        if services:
            body += (
                f"\n## Plexus services on this host ({len(services)})\n"
                + "".join(f"- `{s}`\n" for s in services[:30])
            )
        body += (
            f"\n## Mesh peers\n"
            + "".join(f"- [[{o['label']}]]\n" for o in KNOWN_DEVICES if o['id'] != d['id'])
        )
        if activity_lines:
            body += "\n## Recent brain activity (this host)\n```\n"
            for line in activity_lines[-10:]:
                body += line[:120] + "\n"
            body += "```\n"
        (dev_dir / f"{_safe_filename(d['label'])}.md").write_text(
            _frontmatter({
                "kind": "device", "id": d["id"], "role": d["role"],
                "ip": d["ip"],
                "service_count": len(services),
                "tags": ["device", d["id"]]
            }) + body + _orion_footer("device"),
            encoding="utf-8")
        stats["devices"] += 1

    # ACTIVITY (timeline) ──────────────────────────
    act_dir = out_dir / "Activity"
    act_dir.mkdir()
    for date_key, evs in sorted(by_date.items(), reverse=True):
        if date_key == "unknown":
            continue
        lines = [f"# Activity — {date_key}", ""]
        for ev in evs:
            tool = ev.get("tool", "?")
            snippet = ev.get("snippet", "").strip()
            ts = ev.get("ts", "")
            tool_link = f"[[{tool}]]"
            line = f"- `{ts[11:19] if len(ts) >= 19 else ts}` · {tool_link}"
            if snippet:
                line += f" — {snippet[:100]}"
            lines.append(line)
        (act_dir / f"{date_key}.md").write_text(
            _frontmatter({"kind": "activity", "date": date_key,
                          "event_count": len(evs),
                          "tags": ["activity", date_key]}) + "\n".join(lines),
            encoding="utf-8")
        stats["activity_days"] += 1
        stats["activity_events"] += len(evs)

    # Per-tool index — Memories/recalls.md, Memories/memorizes.md, etc.
    # Each lets Obsidian show "what tool fired most often"
    for tool, evs in by_tool.items():
        if not tool or tool == "?":
            continue
        fname = _safe_filename(tool) + ".md"
        body_lines = [
            f"# {tool}", "",
            f"_{len(evs)} invocation{'s' if len(evs) != 1 else ''} recorded._",
            "",
            "## Recent uses",
        ]
        for ev in evs[:30]:
            ts = ev.get("ts", "")[:19]
            snip = ev.get("snippet", "")[:80]
            body_lines.append(f"- `{ts}` — {snip}" if snip else f"- `{ts}`")
        (act_dir / fname).write_text(
            _frontmatter({"kind": "tool", "name": tool,
                          "tags": ["tool", tool]}) + "\n".join(body_lines),
            encoding="utf-8")

    # HARDWARE PERIPHERALS ─────────────────────────
    hw_dir = out_dir / "Hardware"
    hw_dir.mkdir()
    for p in KNOWN_PERIPHERALS:
        host_label = next((d["label"] for d in KNOWN_DEVICES if d["id"] == p["host"]), p["host"])
        contents = p.get("contents") or []
        contents_block = ""
        if contents:
            contents_block = "\n## Contents / what's on it\n" + "".join(
                f"- {c}\n" for c in contents)
        body = (
            f"# {p['label']}\n\n"
            f"**What it is**\n{p['kind']}\n\n"
            f"**What it does**\n{p['role']}\n\n"
            f"**How it fits in the system**\nAttached to [[{host_label}]] via "
            f"USB / serial. The host owns the device path; Orion accesses it "
            f"through the host's filesystem or a channel adapter (e.g., "
            f"Meshtastic via `channels/meshtastic_node.py`, surfacing as "
            f"the [[LoRa]] channel).\n\n"
            f"- **host:** [[{host_label}]]\n"
            f"- **role:** {p['role']}\n"
            + contents_block
        )
        (hw_dir / f"{_safe_filename(p['label'])}.md").write_text(
            _frontmatter({"kind": "hardware", "id": p["id"],
                          "host": p["host"], "aliases": [p["label"]],
                          "tags": ["hardware", p["id"], p["host"]]}) + body + _orion_footer("hardware"),
            encoding="utf-8")

    # APPS (founder-built projects) ────────────────
    apps_dir = out_dir / "Apps"
    apps_dir.mkdir()
    for a in KNOWN_APPS:
        body = (
            f"# {a['label']}\n\n"
            f"**Role**\n{a['role']}\n\n"
            f"**Status**\n{a['status']}\n\n"
            f"**Where it lives**\n`{a['path']}`\n\n"
            f"---\n\nPart of the founder's ecosystem of built projects. "
            f"Linked to [[Orion]] as one of the things the brain knows about + helps with.\n"
        )
        (apps_dir / f"{_safe_filename(a['label'])}.md").write_text(
            _frontmatter({"kind": "app", "id": a["id"],
                          "aliases": [a["label"]],
                          "tags": ["app", a["status"].split()[0]]}) + body + _orion_footer("app"),
            encoding="utf-8")

    # AGENTS (COMMAND automated scripts) ───────────
    agents_dir = out_dir / "Agents"
    agents_dir.mkdir()
    agent_list_raw = _ssh_pull("command",
        "ls /Users/servermac/server_data/agents/ 2>/dev/null | grep -v '\\.bak' | grep -v '\\.log' | grep -E '^agent[0-9]' | sort -u")
    seen_agent_bases = set()
    for line in agent_list_raw.splitlines():
        name = line.strip()
        if not name:
            continue
        base = name.split(".")[0]
        if base in seen_agent_bases:
            continue
        seen_agent_bases.add(base)
        # Friendly label from agent filename
        nice = name.replace("_", " ").replace(".sh", "").replace(".py", "")
        body = (
            f"# {name}\n\n"
            f"COMMAND automated agent at "
            f"`~/server_data/agents/{name}`.\n\n"
            f"Part of the founder's pre-Plexus automation layer. These "
            f"numbered agent scripts handle specific recurring tasks "
            f"(network watchdog, anomaly detection, telegram reporting, "
            f"backup, cost tracking, etc.). The Plexus services replaced "
            f"many of these conceptually but they remain operational.\n\n"
            f"## Belongs to\n- [[COMMAND]]\n"
        )
        (agents_dir / f"{_safe_filename(base)}.md").write_text(
            _frontmatter({"kind": "agent", "id": base,
                          "aliases": [base, nice],
                          "tags": ["agent", "automation", "command"]}) + body + _orion_footer("agent"),
            encoding="utf-8")

    # SECURITY (curated travel-mode reference) ─────
    sec_dir = out_dir / "Security"
    sec_dir.mkdir()
    sec_index_body = (
        "# Security — Travel Mode Reference\n\n"
        "Concentrated reference for security work — pen testing, network "
        "scanning, anomaly response, uncensored fuel access. Open this "
        "folder when traveling, when investigating, or when responding "
        "to a compromise.\n\n"
        "## Quick-access tools\n\n"
    )
    for s in KNOWN_SECURITY_TOOLS:
        sec_index_body += f"- [[{s['label']}]]\n"
    sec_index_body += (
        "\n## Where these live in the ecosystem\n\n"
        "- **ASUS Arsenal** — physical Kali laptop; SSH from any host. Full offline toolkit.\n"
        "- **OUTPOST** — Tailscale-only remote arm. Always reachable when traveling.\n"
        "- **COMMAND agents/** — automated security/monitor scripts that run 24/7.\n"
        "- **Dolphin Mistral on FORGE** — uncensored local fuel for unconstrained analysis.\n\n"
        "## Hard rules\n\n"
        "- Only authorized testing. Pen tests against owned/permissioned targets only.\n"
        "- Uncensored fuel stays local (Ollama) — never leaves the host.\n"
        "- Vaultwarden holds the secrets; don't paste credentials into chat.\n"
        "- Suspicious activity? Trigger Orion's narrate_failure with severity=critical "
        "so reach alerts via every active channel.\n"
    )
    (sec_dir / "Security.md").write_text(
        _frontmatter({"kind": "security", "aliases": ["Security"],
                      "tags": ["security", "travel-mode", "index"]}) + sec_index_body,
        encoding="utf-8")
    for s in KNOWN_SECURITY_TOOLS:
        body = (
            f"# {s['label']}\n\n"
            f"**Where**\n{s['where']}\n\n"
            f"**What it does**\n{s['tools']}\n\n"
            f"## Part of\n- [[Security]] — travel-mode reference\n"
        )
        (sec_dir / f"{_safe_filename(s['label'])}.md").write_text(
            _frontmatter({"kind": "security-tool", "id": s["id"],
                          "aliases": [s["label"]],
                          "tags": ["security", s["id"]]}) + body + _orion_footer("security-tool"),
            encoding="utf-8")

    # KNOWLEDGE (long-form research articles) ──────
    kn_dir = out_dir / "Knowledge"
    kn_dir.mkdir()
    for k in KNOWN_KNOWLEDGE:
        body = (
            f"# {k['label']}\n\n"
            f"**Where**\n`{k['path']}`\n\n"
            f"**Summary**\n{k['summary']}\n\n"
            f"---\n\nLong-form research article living in Orion's knowledge "
            f"layer. The brain's recall can include these as semantic context.\n"
        )
        (kn_dir / f"{_safe_filename(k['label'])}.md").write_text(
            _frontmatter({"kind": "knowledge", "id": k["id"],
                          "aliases": [k["label"]],
                          "tags": ["knowledge", k["id"]]}) + body + _orion_footer("knowledge"),
            encoding="utf-8")

    # WORKFLOWS (n8n) ──────────────────────────────
    wf_dir = out_dir / "Workflows"
    wf_dir.mkdir()
    for w in KNOWN_WORKFLOWS:
        body = (
            f"# {w['label']}\n\n"
            f"**Where**\n{w['where']}\n\n"
            f"**Summary**\n{w['summary']}\n\n"
            f"---\n\nWorkflow automation host. Orion can trigger these via "
            f"the brain's command dispatch or via direct n8n webhook calls.\n"
        )
        (wf_dir / f"{_safe_filename(w['label'])}.md").write_text(
            _frontmatter({"kind": "workflow", "id": w["id"],
                          "aliases": [w["label"]],
                          "tags": ["workflow", "n8n"]}) + body + _orion_footer("workflow"),
            encoding="utf-8")

    # HTMLs (docs visual references) ───────────────
    html_dir = out_dir / "HTMLs"
    html_dir.mkdir()
    for h in KNOWN_HTMLS:
        body = (
            f"# {h['label']}\n\n"
            f"**Path in repo**\n`{h['path']}`\n\n"
            f"**Summary**\n{h['summary']}\n\n"
            f"---\n\nVisual reference artifact. Open the .html file directly "
            f"in a browser to view the rendered version. Note some HTMLs "
            f"may be outdated relative to the live architecture.\n"
        )
        (html_dir / f"{_safe_filename(h['label'])}.md").write_text(
            _frontmatter({"kind": "html-ref", "id": h["id"],
                          "aliases": [h["label"]],
                          "tags": ["html", "docs", "visual-ref"]}) + body + _orion_footer("html-ref"),
            encoding="utf-8")

    # SYSTEMS (brain subsystems as nodes) ──────────
    sys_dir = out_dir / "Systems"
    sys_dir.mkdir()
    for s in KNOWN_SYSTEMS:
        body = (
            f"# {s['label']}\n\n"
            f"**What it is**\n{s['what']}\n\n"
            f"**What it does**\n{s['does']}\n\n"
            f"**How it fits in the brain**\n{s['fits']}\n\n"
            f"---\n\nConnected to [[Orion]] as one of the brain's "
            f"subsystems. Each system orbits the identity; together they "
            f"are how Orion thinks, remembers, acts, recovers.\n"
        )
        (sys_dir / f"{_safe_filename(s['label'])}.md").write_text(
            _frontmatter({"kind": "system", "id": s["id"],
                          "aliases": [s["label"]],
                          "tags": ["system", s["id"]]}) + body + _orion_footer("system"),
            encoding="utf-8")

    # CLIs ─────────────────────────────────────────
    cli_dir = out_dir / "CLIs"
    cli_dir.mkdir()
    for c in KNOWN_CLIS:
        det = CLI_DETAILS.get(c["id"], {})
        body = f"# {c['label']}\n\n"
        if det:
            body += (
                f"**What it is**\n{det['what']}\n\n"
                f"**What it does**\n{det['does']}\n\n"
                f"**How it fits in the system**\n{det['fits']}\n\n"
                "---\n\n"
            )
        body += (
            f"- **vendor:** {c['vendor']}\n"
            f"- **tier:** {c['tier']} (lower = stronger / preferred)\n\n"
            f"## Fuels served by this CLI\n"
            + ("".join(f"- [[{m['label']}]]\n" for m in KNOWN_LLMS if m['host'] == c['id'])
               or "_(none)_\n")
        )
        (cli_dir / f"{_safe_filename(c['label'])}.md").write_text(
            _frontmatter({"kind": "cli", "id": c["id"],
                          "vendor": c["vendor"], "tier": c["tier"],
                          "aliases": [c["label"]],
                          "tags": ["cli", c["id"]]}) + body + _orion_footer("cli"),
            encoding="utf-8")

    # LLMs ─────────────────────────────────────────
    llm_dir = out_dir / "LLMs"
    llm_dir.mkdir()
    for m in KNOWN_LLMS:
        if m['kind'] == 'frontier':
            cli_label = next((c['label'] for c in KNOWN_CLIS if c['id'] == m['host']), m['host'])
            host_link = f"[[{cli_label}]]"
        else:
            dev_label = next((d['label'] for d in KNOWN_DEVICES if d['id'] == m['host']), m['host'])
            host_link = f"[[{dev_label}]]"
        det = LLM_DETAILS.get(m["id"], "")
        body = f"# {m['label']}\n\n"
        if det:
            body += f"{det}\n\n---\n\n"
        body += (
            f"- **kind:** {m['kind']} ({'cloud-served via CLI' if m['kind']=='frontier' else 'local Ollama on the mesh'})\n"
            f"- **served by:** {host_link}\n"
            f"- **tier:** {m['tier']} (lower = stronger / preferred)\n\n"
            f"Orion uses this model as fuel — it does the inference, the "
            f"brain provides everything else (memory, identity, prior "
            f"decisions). The brain stays constant when the fuel changes.\n"
        )
        (llm_dir / f"{_safe_filename(m['label'])}.md").write_text(
            _frontmatter({"kind": "llm", "id": m["id"],
                          "model_kind": m["kind"], "tier": m["tier"],
                          "aliases": [m["label"]],
                          "tags": ["llm", m["id"], m["kind"]]}) + body + _orion_footer("llm"),
            encoding="utf-8")

    # ARCHITECTURE (Mermaid diagrams) ──────────────
    # Founder feedback 2026-05-14: the graph view is too chaotic for
    # system structure. Mermaid diagrams render as clear architecture
    # diagrams inside Obsidian — built-in, no plugin needed.
    arch_dir = out_dir / "Architecture"
    arch_dir.mkdir()

    # System overview — everything connected
    sys_mermaid = ["```mermaid", "graph TB",
                   "  subgraph User['User']",
                   "    USR((you))",
                   "  end",
                   "  subgraph Channels['Communication Points']"]
    for ch in KNOWN_CHANNELS:
        sys_mermaid.append(f"    {ch['id'].upper().replace('-','_')}[{ch['label']}]")
    sys_mermaid.append("  end")
    sys_mermaid.append("  subgraph Devices['Mesh Devices']")
    for d in KNOWN_DEVICES:
        sys_mermaid.append(f"    {d['id'].upper().replace('-','_')}[{d['label']}]")
    sys_mermaid.append("  end")
    sys_mermaid.append("  subgraph CLIs['AI Tools (MCP attached)']")
    for c in KNOWN_CLIS:
        sys_mermaid.append(f"    {c['id'].upper().replace('-','_')}[{c['label']}]")
    sys_mermaid.append("  end")
    sys_mermaid.append("  subgraph LLMs['Fuel Models']")
    for m in KNOWN_LLMS:
        sys_mermaid.append(f"    {m['id'].upper().replace(':','_').replace('-','_')}[{m['label']}]")
    sys_mermaid.append("  end")
    sys_mermaid.append("  BRAIN{{Orion Brain<br/>memory + identity + ledger}}")
    # User -> channels
    for ch in KNOWN_CHANNELS:
        sys_mermaid.append(f"  USR --> {ch['id'].upper().replace('-','_')}")
    # Channels -> devices
    for ch in KNOWN_CHANNELS:
        if ch["host"] != "any":
            sys_mermaid.append(f"  {ch['id'].upper().replace('-','_')} --> {ch['host'].upper().replace('-','_')}")
    # Devices -> brain
    for d in KNOWN_DEVICES:
        sys_mermaid.append(f"  {d['id'].upper().replace('-','_')} --> BRAIN")
    # Brain -> CLIs (brain is loaded into each CLI via MCP)
    for c in KNOWN_CLIS:
        sys_mermaid.append(f"  BRAIN -.MCP.-> {c['id'].upper().replace('-','_')}")
    # CLIs -> LLMs
    for m in KNOWN_LLMS:
        if m["kind"] == "frontier":
            sys_mermaid.append(f"  {m['host'].upper().replace('-','_')} --fuels--> {m['id'].upper().replace(':','_').replace('-','_')}")
    # Devices -> local LLMs (Ollama)
    for m in KNOWN_LLMS:
        if m["kind"] == "local":
            sys_mermaid.append(f"  {m['host'].upper().replace('-','_')} --hosts--> {m['id'].upper().replace(':','_').replace('-','_')}")
    sys_mermaid.append("```")
    (arch_dir / "System.md").write_text(
        _frontmatter({"kind": "architecture", "aliases": ["System"],
                      "tags": ["architecture", "system"]}) +
        "# System — One Brain, Many Receptors\n\n"
        "How the whole thing fits together. The user reaches Orion through "
        "any communication point; the channel lands on a host; the host "
        "loads the brain; the brain attaches to whatever AI tool / model "
        "is currently fueling it.\n\n"
        + "\n".join(sys_mermaid),
        encoding="utf-8")

    # Mesh-only diagram
    mesh_mermaid = ["```mermaid", "graph LR"]
    for d in KNOWN_DEVICES:
        mesh_mermaid.append(f"  {d['id'].upper().replace('-','_')}[{d['label']}<br/>{d['role']}]")
    # full mesh (every pair)
    ids = [d["id"] for d in KNOWN_DEVICES]
    for i, a in enumerate(ids):
        for b in ids[i+1:]:
            mesh_mermaid.append(f"  {a.upper().replace('-','_')} <--mesh--> {b.upper().replace('-','_')}")
    mesh_mermaid.append("```")
    (arch_dir / "Mesh.md").write_text(
        _frontmatter({"kind": "architecture", "tags": ["architecture", "mesh"]}) +
        "# Mesh — Devices in the Brain\n\n"
        "Every host runs a replica of Orion's brain. The substrate (NATS) "
        "gossips changes between them in real time. When you write a fact "
        "on one device, every other device sees it.\n\n"
        + "\n".join(mesh_mermaid),
        encoding="utf-8")

    # Fuel routing diagram
    fuel_mermaid = ["```mermaid", "graph TD",
                    "  IN((incoming request))",
                    "  ROUTE{which fuel?}",
                    "  IN --> ROUTE"]
    for c in KNOWN_CLIS:
        fuel_mermaid.append(f"  ROUTE -.tier {c['tier']}.-> {c['id'].upper().replace('-','_')}[{c['label']}]")
    for m in KNOWN_LLMS:
        if m["kind"] == "local":
            fuel_mermaid.append(f"  ROUTE -.tier {m['tier']}.-> {m['id'].upper().replace(':','_').replace('-','_')}[{m['label']}]")
    fuel_mermaid.append("```")
    (arch_dir / "Fuels.md").write_text(
        _frontmatter({"kind": "architecture", "tags": ["architecture", "fuels"]}) +
        "# Fuels — How Orion Chooses Which Model to Use\n\n"
        "Orion routes requests to the strongest reachable fuel. Online: the "
        "frontier CLIs (Claude, Codex, Gemini) handle complex reasoning. "
        "Offline: local Ollama models on the mesh (FORGE qwen3:14b is the "
        "strongest local). Never API keys — only flat-rate Pro subscriptions "
        "or free local models.\n\n"
        + "\n".join(fuel_mermaid),
        encoding="utf-8")

    # Legend — color + category system for the whole vault
    (arch_dir / "Legend.md").write_text(
        _frontmatter({"kind": "architecture",
                      "tags": ["architecture", "legend"]}) +
        "# Legend — Reading the Vault\n\n"
        "Every node belongs to one category. Categories share a tag, and "
        "the graph view colors nodes by tag. Toggle individual color "
        "groups from the graph panel's color filter to focus on one "
        "layer at a time.\n\n"
        "## Node categories\n\n"
        "| Color | Category | Tag | What it represents |\n"
        "|---|---|---|---|\n"
        "| 🟡 gold | **Identity** | `identity` | The canonical 'who Orion is' — SOUL.md content, name, address-form preference |\n"
        "| 🟣 magenta | **System** | `system` | Brain subsystems — Plexus / Memory / Reach / Will / Executive / Dream |\n"
        "| 🟪 violet | **Architecture** | `architecture` | Mermaid diagrams — System, Mesh, Fuels, Anatomy, Nervous System, Legend |\n"
        "| 🟠 orange | **Device** | `device` | Mesh hosts — COMMAND, FORGE, ORIONS HOME, OUTPOST |\n"
        "| 🟣 deep purple | **Hardware** | `hardware` | Peripherals attached to a host — radios, MCUs, SSDs |\n"
        "| 🟢 bright green | **CLI** | `cli` | AI tools that attach to the brain — Claude / Codex / Gemini / Letta |\n"
        "| 🩵 cyan | **LLM** | `llm` | Local fuel models — qwen3:14b / qwen3:8b / phi3:mini / dolphin-mistral |\n"
        "| 🩷 pink | **Channel** | `channel` | Communication points — iMessage / Voice / Telegram / CLI / Webhook / LoRa |\n"
        "| 🟢 turquoise | **Service** | `service` | Plexus services on this host (drawn from vitals dir) |\n"
        "| ⚪ neutral | **Memory** | `fact / preference / project / task / tool / reference / ephemeral` | Filtered out of default graph view; clear filter to bring in |\n"
        "| 🟤 dim | **Activity** | `activity` | Daily timeline + per-tool usage; filtered out by default |\n\n"
        "## How to use the graph view\n\n"
        "- **Default view**: all categories visible, color-coded as above.\n"
        "- **Focus on one layer**: turn off others in the color filter panel.\n"
        "- **Bring in memories**: clear the search filter (top-right of graph panel).\n"
        "- **Drill into a node**: click → opens the file with full prose detail.\n"
        "- **Trace a connection**: hover an edge to see which two nodes it links.\n\n"
        "## How nodes connect\n\n"
        "| Edge type | What it means |\n"
        "|---|---|\n"
        "| device ↔ device | Mesh substrate cluster route |\n"
        "| channel → device | This channel is hosted on this device |\n"
        "| service → device | This Plexus service runs on this device |\n"
        "| hardware → device | This peripheral is attached to this device |\n"
        "| CLI → LLM | This CLI fuels through this model |\n"
        "| LLM → device | This local model is hosted on this device |\n"
        "| system → Orion | This subsystem orbits the brain |\n"
        "| memory ↔ memory | Shared tag (Obsidian-style co-occurrence) |\n",
        encoding="utf-8")

    # Anatomy — cellular layout of the brain as one body
    (arch_dir / "Anatomy.md").write_text(
        _frontmatter({"kind": "architecture", "tags": ["architecture", "anatomy", "cellular"]}) +
        "# Anatomy — Orion as a Cell\n\n"
        "Reading Orion like a cell makes the architecture legible. Each "
        "layer maps to a biological structure that exists for the same "
        "reason — boundary, content, infrastructure, sensing, action.\n\n"
        "```mermaid\n"
        "graph TB\n"
        "  subgraph CELL[\"Orion (one cell, replicated across hosts)\"]\n"
        "    subgraph NUCLEUS[\"Nucleus — Identity\"]\n"
        "      SOUL[SOUL.md<br/>name · address-form · rules]\n"
        "    end\n"
        "    subgraph CYTO[\"Cytoplasm — Memory\"]\n"
        "      GRAPH[graph_memory<br/>115 nodes · facts · prefs · projects]\n"
        "      LEDGER[decision_ledger<br/>append-only autobiography]\n"
        "      KNOW[knowledge/<br/>curated long-form notes]\n"
        "    end\n"
        "    subgraph ORG[\"Organelles — Plexus (always-on subsystems)\"]\n"
        "      SUB[substrate · NATS]\n"
        "      CLA[claustrum · awareness]\n"
        "      VIT[vitals · per-service health]\n"
        "      IMM[immune · supervision]\n"
        "      DRM[dream · consolidation]\n"
        "      EXE[executive · judgment]\n"
        "      WIL[will · volition]\n"
        "      GOS[gossip · state sync]\n"
        "    end\n"
        "    subgraph MEM[\"Membrane — boundary / privacy\"]\n"
        "      PRI[private-internal tag filter]\n"
        "      MEMB[Membrane (planned) · code-level privacy hook]\n"
        "    end\n"
        "    subgraph REC[\"Receptors — channels\"]\n"
        "      RIM[iMessage]\n"
        "      RVO[Voice]\n"
        "      RTG[Telegram]\n"
        "      RCL[CLI / MCP]\n"
        "      RWE[Webhook]\n"
        "      RLO[LoRa]\n"
        "    end\n"
        "    subgraph EFF[\"Effectors — reach\"]\n"
        "      RCH[reach.py · chooses warmest channel]\n"
        "    end\n"
        "  end\n"
        "  SIGNAL((world signals)) --> REC\n"
        "  REC --> ORG --> CYTO\n"
        "  NUCLEUS --> ORG\n"
        "  CYTO --> EFF --> REC\n"
        "  ORG --> EFF\n"
        "  MEM -.boundary.-> CYTO\n"
        "  MEM -.boundary.-> NUCLEUS\n"
        "```\n\n"
        "## Reading the cell\n\n"
        "- **Nucleus (Identity)** — the canonical fact of who Orion is. "
        "Small, stable, central. If you wanted to know what made Orion "
        "*this Orion*, the nucleus is where the answer lives.\n"
        "- **Cytoplasm (Memory)** — the body's contents. Facts, "
        "preferences, projects, decisions. Diffuse, growing, indexed.\n"
        "- **Organelles (Plexus)** — the always-on infrastructure that "
        "makes the cell alive. Substrate carries signals; claustrum "
        "integrates; vitals monitor; immune supervises; dream consolidates "
        "overnight; executive judges; will initiates; gossip replicates.\n"
        "- **Membrane** — what stays in vs goes out. Currently a tag-filter "
        "(`private-internal` excludes nodes from external surfaces). Future "
        "Membrane hook enforces this in code at the substrate layer.\n"
        "- **Receptors (Channels)** — surfaces that bind to incoming "
        "signals: iMessage, voice, Telegram, CLI, webhook, LoRa. New "
        "receptor = new way to reach the cell, no internal change.\n"
        "- **Effectors (Reach)** — how the cell signals back. Reach picks "
        "the warmest channel; same brain, different output surface.\n\n"
        "Every host runs one of these cells. Gossip + CRDT merge keeps "
        "them all converged on the same nucleus + cytoplasm content. The "
        "user reaches one cell at a time, but every cell answers as one Orion.\n",
        encoding="utf-8")

    # Nervous-system / offline-fallback diagram — between devices
    (arch_dir / "Nervous System.md").write_text(
        _frontmatter({"kind": "architecture", "tags": ["architecture", "nervous-system", "mesh"]}) +
        "# Nervous System Between Devices\n\n"
        "How signals travel across the four hosts when things are healthy, "
        "and how they degrade gracefully when parts of the mesh drop. The "
        "substrate (NATS) is the synapse layer; gossip is the long-distance "
        "axon; HTTP :5555 is the direct call when sub-second propagation "
        "isn't enough.\n\n"
        "## Healthy (everything online)\n\n"
        "```mermaid\n"
        "graph LR\n"
        "  USR((user))\n"
        "  CMD[COMMAND<br/>canonical brain]\n"
        "  FRG[FORGE<br/>mobile + GPU]\n"
        "  PI[ORIONS HOME<br/>offline twin + maps]\n"
        "  OUT[OUTPOST<br/>tailscale arm]\n"
        "  USR -.iMessage / voice / Telegram.-> CMD\n"
        "  USR -.CLI / MCP.-> FRG\n"
        "  CMD <-.NATS cluster.-> PI\n"
        "  CMD <-.NATS cluster.-> FRG\n"
        "  CMD <-.NATS cluster.-> OUT\n"
        "  PI <-.gossip.-> FRG\n"
        "  PI <-.gossip.-> OUT\n"
        "  FRG <-.gossip.-> OUT\n"
        "```\n\n"
        "## When COMMAND drops (power, software fault)\n\n"
        "```mermaid\n"
        "graph LR\n"
        "  USR((user))\n"
        "  CMD[COMMAND<br/>DOWN]\n"
        "  FRG[FORGE]\n"
        "  PI[ORIONS HOME<br/>becomes canonical]\n"
        "  OUT[OUTPOST]\n"
        "  USR -.iMessage queued.-> CMD\n"
        "  USR --CLI--> FRG\n"
        "  USR -.SSH / Tailscale.-> PI\n"
        "  PI <-.gossip.-> FRG\n"
        "  PI <-.gossip.-> OUT\n"
        "  style CMD fill:#552,stroke:#f55\n"
        "```\n\n"
        "On COMMAND failure: Pi promotes to canonical writer, gossip "
        "continues between FORGE/Pi/OUTPOST, iMessage replies pause until "
        "COMMAND returns (queued), but voice (Telnyx) can re-route to Pi "
        "if the Telnyx webhook is reconfigured. Memory stays consistent "
        "via CRDT.\n\n"
        "## When internet drops (off-grid)\n\n"
        "```mermaid\n"
        "graph LR\n"
        "  USR((user))\n"
        "  FRG[FORGE<br/>local Ollama qwen3:14b]\n"
        "  PI[ORIONS HOME<br/>local Ollama + LoRa]\n"
        "  MTA[Meshtastic Node 1]\n"
        "  MTB[Meshtastic Node 2]\n"
        "  USR --CLI--> FRG\n"
        "  FRG <-.LAN.-> PI\n"
        "  PI --serial--> MTA\n"
        "  PI --serial--> MTB\n"
        "  MTA -.LoRa air.-> REMOTE[remote nodes<br/>up to km away]\n"
        "  MTB -.LoRa air.-> REMOTE\n"
        "```\n\n"
        "Internet gone: CLIs fall back to local Ollama. The strongest "
        "local model (FORGE qwen3:14b) becomes primary fuel. Voice and "
        "iMessage are unavailable (they need cell/wifi). LoRa via "
        "Meshtastic carries text traffic — including CRDT brain-deltas "
        "if the brain-as-signal layer is enabled — to nodes kilometers "
        "away. The mesh contracts but the brain stays alive.\n\n"
        "## When everything drops except one device\n\n"
        "```mermaid\n"
        "graph LR\n"
        "  USR((user))\n"
        "  FRG[FORGE<br/>USB plugged in]\n"
        "  USR --CLI--> FRG\n"
        "  style FRG fill:#252,stroke:#5f5\n"
        "```\n\n"
        "Single-device mode: whichever host the user is touching keeps "
        "serving from its replica. The brain doesn't disappear — it "
        "honestly collapses to what's local. When connectivity returns, "
        "gossip merges any divergent writes back into one canonical state.\n",
        encoding="utf-8")

    # CHANNELS ─────────────────────────────────────
    chan_dir = out_dir / "Channels"
    chan_dir.mkdir()
    label_for_dev = {d["id"]: d["label"] for d in KNOWN_DEVICES}
    for ch in KNOWN_CHANNELS:
        host_label = label_for_dev.get(ch["host"], "(any host)")
        host_link = f"[[{host_label}]]" if ch["host"] != "any" else "any host"
        det = CHANNEL_DETAILS.get(ch["id"], "")
        body = f"# {ch['label']}\n\n"
        if det:
            body += (
                f"**What it does**\n{det}\n\n"
                f"**How it fits in the system**\nA receptor on the mesh. "
                f"Inbound messages arrive here and land on the host; the "
                f"host loads the brain and answers. Outbound replies route "
                f"through this surface when reach.py picks it as the warmest "
                f"active channel.\n\n"
                "---\n\n"
            )
        body += (
            f"- **transport:** {ch['transport']}\n"
            f"- **hosted on:** {host_link}\n\n"
            f"Communication point — a way to reach Orion. The brain is the "
            f"same regardless of which channel you arrive through.\n"
        )
        (chan_dir / f"{_safe_filename(ch['label'])}.md").write_text(
            _frontmatter({"kind": "channel", "id": ch["id"],
                          "host": ch["host"], "transport": ch["transport"],
                          "tags": ["channel", ch["id"]]}) + body + _orion_footer("channel"),
            encoding="utf-8")
        stats["channels"] += 1

    # SERVICES (from local vitals dir, if any) ─────
    svc_dir = out_dir / "Services"
    svc_dir.mkdir()
    if VITALS_DIR.exists():
        for f in sorted(VITALS_DIR.glob("*.json")):
            svc = f.stem
            try:
                snap = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                snap = {}
            body = (
                f"# {svc}\n\n"
                f"- **uptime (s):** {snap.get('uptime_sec', '?')}\n"
                f"- **last event age (s):** {snap.get('last_event_age_sec', '?')}\n"
                f"- **error rate / min:** {snap.get('error_rate_per_min', 0)}\n\n"
                "Plexus service running on this host. Part of the nervous "
                "system Orion uses to perceive and act.\n"
            )
            (svc_dir / f"{_safe_filename(svc)}.md").write_text(
                _frontmatter({"kind": "service", "id": svc,
                              "tags": ["service", svc]}) + body + _orion_footer("service"),
                encoding="utf-8")
            stats["services"] += 1

    # MEMORIES ─────────────────────────────────────
    mem_dir = out_dir / "Memories"
    mem_dir.mkdir()
    if GRAPH_PATH.exists():
        try:
            raw = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] could not read graph_memory: {e}", file=sys.stderr)
            raw = {"nodes": {}}

        # Build tag -> node-ids index so we can wiki-link siblings
        tag_to_ids = defaultdict(list)
        for nid_str, node in raw.get("nodes", {}).items():
            try:
                nid = int(nid_str)
            except Exception:
                continue
            for t in node.get("tags", []) or []:
                tag_to_ids[(t or "").strip().lower()].append(nid)

        # Tag → architecture-node label, for radial linking
        TAG_TO_ARCH = {
            "fuel": "Fuels", "fuel-policy": "Fuels", "fuel-calibration": "Fuels",
            "fuel-tier": "Fuels", "ollama-fallback-only": "Fuels",
            "no-api-keys": "Fuels", "forge-ollama": "Fuels",
            "mesh-design": "Mesh", "mesh": "Mesh", "cross-host": "Mesh",
            "one-brain": "Anatomy", "architecture": "Anatomy",
            "cellular": "Anatomy",
            "membrane": "Anatomy", "empathy": "Anatomy", "meta-cognition": "Anatomy",
            "sensorium": "Anatomy", "federation": "Anatomy",
            "nervous-system": "Nervous System",
            "offline": "Nervous System", "offline-mesh": "Nervous System",
            "offline-fallback": "Nervous System",
            "brain-as-signal": "System", "lora": "System", "phase-4-horizon": "System",
            "pi": "ORIONS HOME", "orions-home": "ORIONS HOME",
            "navigation": "ORIONS HOME", "marble": "ORIONS HOME",
            "offline-maps": "ORIONS HOME",
            "command": "COMMAND", "command-plist": "COMMAND",
            "tcc": "COMMAND", "macos": "COMMAND",
            "forge": "FORGE",
            "outpost": "OUTPOST",
            "meshtastic": "Meshtastic Node 1", "esp32": "ESP32",
            "imessage": "iMessage", "telegram": "Telegram", "voice": "Voice",
            "session-snapshot": "Activity",
            "plexus": "Plexus", "claustrum": "Plexus", "executive": "Executive",
            "dream": "Dream", "will": "Will", "reach": "Reach",
            "memory": "Memory System",
        }

        for nid_str, node in raw.get("nodes", {}).items():
            try:
                nid = int(nid_str)
            except Exception:
                continue
            content = node.get("content", "")
            content = content if isinstance(content, str) else str(content)
            # Strip MCP XML-tag leakage from earlier memorize calls
            content = re.sub(r"</content>\s*\n*<parameter[^>]*>[\w-]*", "", content)
            content = re.sub(r"<parameter\s+name=\"[^\"]+\">[\w-]*\s*", "", content)
            content = content.replace("</content>", "").strip()
            tags = list(node.get("tags", []) or [])
            mtype = node.get("type", "fact")

            # Reduced sibling linking: only top 3 most-distinctive shared
            # tags, not the full mesh. Keeps the graph from flooding.
            STOPWORDS = {"fact", "preference", "project", "identity", "task",
                         "ephemeral", "person", "skill", "tool", "user",
                         "founder", "orion", "brain"}
            related = set()
            for t in tags:
                tlow = (t or "").strip().lower()
                if not tlow or tlow in STOPWORDS:
                    continue
                for sib in tag_to_ids.get(tlow, []):
                    if sib != nid:
                        related.add(sib)
            # Only keep first 3 siblings — drastically reduces memory-to-memory
            # edges that flood the graph
            related_sorted = sorted(related)[:3]
            related_links = "".join(f"- [[mem-{r}]]\n" for r in related_sorted)
            stats["wiki_links"] += min(len(related), 3)

            # RADIAL ANCHOR: link memory to its closest architecture/system
            # node based on tag match. Makes architecture the gravitational
            # center; memories spread outward as a Saturn ring.
            arch_links = []
            seen_arch = set()
            for t in tags:
                arch_label = TAG_TO_ARCH.get((t or "").strip().lower())
                if arch_label and arch_label not in seen_arch:
                    seen_arch.add(arch_label)
                    arch_links.append(f"- [[{arch_label}]]\n")
                if len(arch_links) >= 2:
                    break

            # Readable filename: mem-<id>-<slug>.md — what Obsidian shows
            # in the graph by default. Slug is the first meaningful chunk
            # of content so the graph reads naturally instead of "mem-37".
            title_seed = content.split(":")[0].split("\n")[0].strip()[:50] or f"memory {nid}"
            slug = re.sub(r"[^\w\s-]", "", title_seed).strip()
            slug = re.sub(r"\s+", "-", slug)[:40].lower() or f"node-{nid}"
            fname = f"mem-{nid}-{slug}.md"

            fm = _frontmatter({
                "kind": "memory",
                "id": nid,
                "type": mtype,
                "aliases": [title_seed, f"mem-{nid}"],
                "tags": [mtype] + tags[:8],
                "confidence": node.get("confidence", 1.0),
                "created": node.get("created", 0),
            })
            body = (
                f"# {title_seed}\n\n"
                f"> Memory node #{nid} · type: `{mtype}`\n\n"
                f"{content}\n"
            )
            if arch_links:
                body += f"\n## Belongs to\n{''.join(arch_links)}"
            if related_links:
                body += f"\n## Related memories\n{related_links}"
            (mem_dir / fname).write_text(fm + body, encoding="utf-8")
            stats["memories"] += 1

    return stats


def _watch(out: Path, interval: float = 5.0) -> int:
    """Re-export whenever graph_memory.json or SOUL.md mtime changes.

    Cheap parallel-with-functions wiring: poll source files, re-render
    on change. Future: subscribe to brain.memory.stored on the substrate
    and re-render event-driven. For now polling keeps the path simple.
    """
    import time
    last_seen = {}
    print(f"[orion-obsidian-watch] watching {GRAPH_PATH} and {SOUL_PATH} every {interval}s")
    print(f"[orion-obsidian-watch] re-exporting to {out.resolve()} on change")
    print("[orion-obsidian-watch] Ctrl-C to stop.")
    while True:
        changed = False
        for p in (GRAPH_PATH, SOUL_PATH):
            try:
                m = p.stat().st_mtime if p.exists() else 0
            except OSError:
                m = 0
            if last_seen.get(p) != m:
                last_seen[p] = m
                changed = True
        if changed:
            try:
                stats = export_vault(out)
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] re-exported: "
                      f"{stats['memories']} memories, "
                      f"{stats['wiki_links']} links")
            except Exception as e:
                print(f"[orion-obsidian-watch] export error: {e}")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[orion-obsidian-watch] stopped")
            return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Export Orion's brain as an Obsidian vault.")
    ap.add_argument("--out", default="./orion-vault",
                    help="output vault directory (default: ./orion-vault)")
    ap.add_argument("--profile", default="starter", choices=["starter", "full"],
                    help="starter (minimal — for new users to build off) or "
                         "full (every device + CLI + LLM + channel + hardware "
                         "+ architecture detail — for ecosystems like the founder's)")
    ap.add_argument("--open", action="store_true",
                    help="open the vault in Obsidian after export (uses obsidian:// URI)")
    ap.add_argument("--watch", action="store_true",
                    help="watch graph_memory + SOUL and re-export on change")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="watch poll interval seconds (default: 5)")
    args = ap.parse_args(argv[1:])

    out = Path(args.out)
    print(f"[orion-obsidian] exporting brain to {out.resolve()} (profile={args.profile})")
    stats = export_vault(out, profile=args.profile)
    print("[orion-obsidian] done:")
    for k, v in stats.items():
        print(f"  {k:>12}: {v}")
    print(f"\nNext: open Obsidian -> 'Open folder as vault' -> {out.resolve()}")
    print("Then Cmd/Ctrl+G for graph view.")

    if args.open:
        # Obsidian URI: obsidian://open?path=<absolute path>
        uri = "obsidian://open?path=" + str(out.resolve()).replace(" ", "%20")
        print(f"\nopening: {uri}")
        webbrowser.open(uri)

    if args.watch:
        return _watch(out, args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
