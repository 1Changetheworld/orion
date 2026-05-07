<div align="center">

# ORION

### Any AI Model. Same Persona. Same Brain. Same Memories.

**Your agent forgets between models. Orion doesn't.**

A portable intelligence layer that works with any AI model, on any device, with persistent memory that belongs to you. $0 per request. Zero API keys. Zero framework dependencies.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
![Status: Alpha](https://img.shields.io/badge/status-alpha-orange)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows%20%7C%20Raspberry%20Pi-lightgrey)

**2026-04-23 — Fresh-user install verified on Raspberry Pi 5.** Cross-model memory proven on ARM hardware with throwaway accounts — see [the case study](docs/pi-install-case-study.md).

</div>

<!-- DEMO: 15-30s GIF of cross-model handoff goes here. Capture script: docs/demo-capture.md -->

<div align="center">

![Orion install walkthrough — Pi 5 · 20 minutes · Cross-model memory proven](docs/images/install-walkthrough.png)

*Fresh install on a Raspberry Pi 5. Proto-Orion speaks before any model attaches. Same brain across Claude, Codex, and Gemini. Real recording, 2026-04-23.*

</div>

---

## Try it in 2 minutes

**You have Codex, Gemini, or Claude CLI installed already?**

```bash
git clone https://github.com/1Changetheworld/orion.git
cd orion
bash install.sh    # Linux / macOS — asks 4 questions, 2 min
# Or: pip install -r requirements.txt && python setup.py   (Windows)
```

When install finishes, run your AI CLI (`codex`, `gemini`, or `claude`) and ask: *"what's my name?"* — it'll know, because Orion just seeded its brain with you.

**Prove it crosses the glass:** set a fact in one CLI (`remember my favorite color is teal`), then open a *different* AI CLI and ask `what's my favorite color?`. Same brain, different fuel. That's the whole product in one test.

---

## Table of Contents

- [What is Orion?](#what-is-orion)
- [How It Works](#how-it-works)
- [Fuel System](#fuel-system)
- [Interfaces](#interfaces)
- [Operational Modes](#operational-modes)
- [Installation](#installation)
- [Verify your install](#verify-your-install)
- [Prove cross-model memory works](#prove-cross-model-memory-works-the-real-test)
- [Competitive Landscape](#competitive-landscape)
- [Documentation](#documentation)
- [What Orion Is Not](#what-orion-is-not)
- [Roadmap](#roadmap)
- [License](#license)

---

## What is Orion?

Orion is an AI brain that separates intelligence from compute.

Today, your AI conversations are locked inside whatever platform you use. Switch from ChatGPT to Claude — you start over. Use AI on your phone and your laptop — two separate contexts. The model IS the brain, and the brain resets every time.

Orion flips this. The brain is **your data** — memory, knowledge, skills, identity. The model is just fuel. Plug in Claude, ChatGPT, Ollama, Gemini, Codex — Orion uses whatever is available and adapts automatically. Switch models, switch devices, go offline — the brain persists.

**You don't need a paid subscription.** Free Ollama models, free ChatGPT tiers, free Gemini — all valid fuel. Premium subscriptions make it faster and smarter, but the brain works with anything.

**You don't need a special drive.** Install Orion on your computer and it works locally. Want portability? Put it on any USB drive and carry your brain between machines.

**You don't need API keys.** Orion runs on flat-rate subscriptions or free models. No per-token billing. No metered usage. The marginal cost of every request is zero.

**You can use it where ChatGPT is banned.** Companies block cloud AI because every prompt leaves the network. Orion in Stealth Mode with local Ollama models runs entirely on your hardware. Zero data leaves the device. No cloud calls. No telemetry. Your IT department can verify — nothing goes out. AI without the data leak.

---

## How It Works

```
USER INPUT (any interface)
     │
     ▼
ORION BRAIN (~200 lines of Python)
[identity: hardcoded — Orion always knows who it is]
[memory: graph + vector search — never forgets]
[router: classifies input in milliseconds]
     │
     ├── command ────► DISPATCH (instant, <2s, no AI model needed)
     │                 /status, /email, /scan, /docker, 20 commands
     │
     ├── greeting ──► LOCAL MODEL (phi3:mini, free, fast)
     │
     └── complex ───► FUEL ADAPTER (best available model)
                      │
              ┌───────┼───────┐
              │       │       │
         Claude CLI  Ollama  ChatGPT
         ($0/req)    (free)  (free tier)
```

**Two layers:**

| Layer | What It Is | Original? |
|-------|-----------|-----------|
| **The Brain** | Memory, identity, fuel routing, dispatch, skills, personality | Yes — ~200 lines of Python, zero dependencies, fully original |
| **The Toolkit** | Security scanning, OSINT, desktop control, offline knowledge, device mesh | Curated — existing open-source tools that Orion orchestrates |

The brain is what's new. The toolkit is what the brain knows how to use. Like a human isn't defined by the hammer they own — they're defined by the brain that knows when and how to use it.

---

## Fuel System

Orion treats AI models as fuel. Bring whatever you have:

| Fuel Source | Cost | Quality |
|------------|------|---------|
| Claude CLI (Pro subscription) | $0/request | Best — deep reasoning, unlimited |
| ChatGPT Plus | $20/mo | Strong general purpose |
| Ollama (local models) | Free forever | Good for simple tasks, no internet needed |
| ChatGPT / Gemini free tiers | Free | Capable, rate limited |
| No model (offline) | Free | Dispatch commands still work, cached knowledge accessible |

**Quality changes with fuel.** The brain stays the same — your memory, skills, and knowledge persist regardless. But reasoning quality depends on the model:
- Claude Opus → complex analysis, strategic thinking
- ChatGPT free → good conversations, basic tasks
- phi3:mini local → greetings and simple queries
- No model → dispatch commands still instant, no generative AI

Orion auto-routes: simple tasks go to free models, complex tasks go to the best available fuel. You don't configure this.

**Visual fuel indicator:** A glow appears around whatever AI model window is currently powering Orion. Claude active? Cyan glow. ChatGPT? Green. Local Ollama? Purple. You always know at a glance what's fueling your brain without checking settings.

---

## Interfaces

Eight ways to reach the same brain. A fact learned over a phone call is recalled in a text message ten minutes later.

| Interface | Status | Description |
|-----------|--------|-------------|
| Voice Headset | Live | Dedicated Poly Voyager 4310 UC wireless headset. Pick it up and talk — Whisper STT on GPU, Piper TTS, fully local. Voice ID verifies it's you before responding. |
| Phone | Real number | Call from any phone. Orion answers with synthesized speech. |
| Telegram | 50+ commands | Full command suite plus natural language processing |
| iMessage | Native macOS | Text Orion from your iPhone — same brain as every other interface |
| Terminal / CLI | Any AI tool | Open any terminal — Orion's context is pre-loaded. No setup. |
| Dashboard | Web UI | Pixel art operations center with live agent visualization |
| Webhook | `POST /chat` | Programmatic access — any script or automation can talk to Orion |
| Any AI Tool | Zero-prompt | Open ChatGPT, Claude, Gemini — Orion is already there |

### Voice Headset Details

The voice interface turns a Bluetooth headset into a dedicated Orion communication device. The pipeline runs entirely on local hardware — zero API keys, zero cloud calls:

```
Headset Mic → Voice Activity Detection → Whisper STT (GPU) → Orion Brain → Piper TTS → Headset Earpiece
```

**Voice ID:** Enroll your voice with 10 samples across different emotions and tones — normal speech, commands, whispers, excitement, fatigue. Orion builds an MFCC-based voiceprint and verifies every utterance before processing. Someone else talks? Ignored.

**Auto-start:** Launches on login. Pick up the headset and talk — no terminal, no commands.

**Multipoint:** The headset connects to your computer at the desk and your phone on the go. Same headset, same Orion, different backend — local GPU processing at home, phone-to-cloud when mobile.

---

## Operational Modes

Orion operates in distinct *modes* — each shapes how the brain behaves when the user invokes it. Status column is honest: what's live, what's partial, what's next.

### Shipping now
| Mode | What It Does | Example |
|------|-------------|---------|
| **Standard** | Conversational AI + command execution | *"Check my server status and restart the web container"* |
| **Deep Dive** | Extended reasoning, multi-source research | *"Research every competitor in the AI memory space and summarize their funding, features, and gaps"* |
| **Builder** | End-to-end project execution from a single prompt | *"Build a REST API for user authentication with JWT tokens, tests, and deploy it"* |

### Partial (working, needs polish)
| Mode | What It Does | Example |
|------|-------------|---------|
| **Absorption** | Indexes new tools and repos into the knowledge base | *Orion scans GitHub trending, reads READMEs, embeds useful tools into its knowledge — gets smarter overnight* |
| **Defense** | Hardens security on untrusted networks | *Connect to hotel WiFi — Orion auto-tightens firewall rules, enforces VPN, blocks inbound connections* |

### Coming soon
| Mode | What It'll Do | Example |
|------|-------------|---------|
| **Hive Mind** | Parallel dispatch across multiple devices | *"Scan all 4 devices for vulnerabilities simultaneously" — each device works independently, results merge* |
| **Stealth** | Zero cloud calls, local only, no telemetry | *All traffic stays on-device. No logs. No external connections. Nothing leaves the machine.* |
| **The Ant** | Hive-like mass search for deep investigation | *"Find everything about this company" — branches into dozens of search paths like ants, synthesizes findings* |
| **Autonomous** | Camera-enabled self-directed operation | *Orion sees through a camera, decides what to do, and acts without user input — monitoring, hardware control* |

Under the hood, Orion also has **adaptive discovery** (finds AI tools on your host by shape, not a hardcoded list), a **cognitive cycle** (perceive → reason → act → verify, fires at install / wake / on-command), and **self-repair** (consults another model when something's wrong — first alien-arc move of its kind in personal-AI memory). See [docs/orion-architecture.html](docs/orion-architecture.html) for the technical picture.

---

## Installation

**Local (your computer):**
```bash
git clone https://github.com/1Changetheworld/orion.git
cd orion
pip install -r requirements.txt
python setup.py
```

**Portable (USB drive):**
```bash
cd /path/to/drive
git clone https://github.com/1Changetheworld/orion.git
cd orion
pip install -r requirements.txt
python setup.py --portable
```

The setup wizard detects your OS, scans for available AI models, and asks which tier you want:

- **Personal** — brain + memory + your AI models. Simple. Just works.
- **Developer** — add fuel routing, CLI access, custom skills, device mesh.
- **Full Arsenal** — add security scanning, OSINT, offline knowledge, hardware pipelines.

### Verify your install

After setup, run the preflight check to confirm everything composes:

```bash
python orion_preflight.py
```

Green rows = healthy. Yellow = usable but has known gaps (usually an AI
tool on your host that speaks MCP but doesn't have `orion-brain` wired
— fix with `/selfcheck` inside `orion chat`). Red = broken; address
before using the brain.

### Prove cross-model memory works (the real test)

If you have two AI CLI tools installed (Codex, Gemini, Claude Code,
etc.) and they have `orion-brain` wired, this is the glass-switching
test:

1. In one terminal: `codex` (or `gemini`, or any MCP-enabled AI CLI).
   Type naturally: `remember my favorite color is teal`. Close.
2. In a different terminal: `gemini` (or any other wired tool).
   Type naturally: `what's my favorite color?`
3. The second tool should answer `teal` without you ever mentioning
   Orion, memory, or tool names. If it does — the brain crossed the
   glass. That's the whole product in one sentence.

See [docs/INSTALL.md](docs/INSTALL.md) for full details.

---

## Competitive Landscape

| Capability | Mem0 | Letta | Khoj | Open Interpreter | **Orion** |
|-----------|------|-------|------|-----------------|-----------|
| Persistent memory | Yes | Yes | Yes | No | **Yes** |
| Model-agnostic | Partial | Partial | Partial | Yes | **Yes** |
| Portable (physical) | No | No | No | No | **Yes** |
| Real phone number | No | No | No | No | **Yes** |
| 8+ interfaces | No | No | 2-3 | No | **Yes** |
| $0/request | No | No | No | No | **Yes** |
| No API keys needed | No | No | No | No | **Yes** |
| Offline fallback | No | No | Yes | Local only | **5-tier** |
| Zero dependencies | Own SDK | Heavy | Moderate | Moderate | **Zero** |

These companies have raised a combined $20M+ in venture funding. Orion was built by one person on consumer hardware.

---

## Documentation

- [**Pi install case study**](docs/pi-install-case-study.md) — real graduation test on a Raspberry Pi 5 with fresh accounts. Proof the portable-soul thesis works on stranger's hardware.
- [**Product pitch** (orion-v2.html)](docs/orion-v2.html) — the full long-form pitch. Start here for the product-level story + investor-facing narrative.
- [**Architecture** (orion-architecture.html)](docs/orion-architecture.html) — technical internals: brain layers, MCP, cognitive cycle, ontology, memory model.
- [**UI mockup** (orion-ui-mockup.html)](docs/orion-ui-mockup.html) — design target for the forthcoming desktop app. Open in a browser.
- [**Install guide** (INSTALL.md)](docs/INSTALL.md) — Windows / macOS / Linux install paths, portable drive setup, troubleshooting.

---

## What Orion Is Not

- **Not a replacement for ChatGPT.** Orion uses models like ChatGPT as fuel. If you're happy with one model and never switch, Orion's value is lower for you today.
- **Not finished.** The brain works. The interfaces work. The consumer experience — setup wizard, one-click install, polish — is in development.
- **Not magic.** Quality depends on the fuel. A free local model won't match Claude Opus. The brain is the same either way — the thinking power varies.

---

## Roadmap

### Near-term (active work)
- **Desktop app** — Orion UI with a model picker dropdown, persistent chat, personality customization, brain visualization. Mockup in [docs/orion-ui-mockup.html](docs/orion-ui-mockup.html). The CLI you're reading about today is v0; the app is what most users will meet first.
- **Self-healing observer** (`orion_sleep.py`) — replay / consolidation / adaptive forgetting cycle based on the EIMB-1 research track. Notices when a tool session failed to reach Orion and self-repairs the integration. In-progress.
- **Multi-interface expansion** — iMessage, Telegram, phone (Telnyx/Twilio), and email all routing to the same brain. Orion walks you through wiring each.
- **Coherent-information-grounded memory** — replace heuristic half-life decay with a mathematically rigorous re-anchoring trigger from the Bény–Oreshkov threshold theorem. Makes Orion's memory the first personal AI memory layer with real persistence guarantees.

### Later
- **Mesh mode** — two or more Orion installs sharing one brain (CRDT plane + consensus plane per the research spec). One you across devices, phones, and desktops.
- **Hardware intelligence** — car diagnostics via OBD-II, biosignal monitoring via commodity sensors, Orion as the interpretation layer. Hardware is cheap; integration is hard — that's where Orion lives.
- **AI literacy platform** — learn to use AI effectively, structured by career field. Like Duolingo for the AI era. Your Orion brain builds as you learn.
- **Orion as a platform** — SDK + marketplace of skills, payment rails, team/enterprise tiers. The CLI and the desktop app are surfaces; the brain is the platform.

---

## Project status snapshot

| | Status |
|---|---|
| CLI install + conversational onboarding | ✅ shipping |
| Cross-model memory (Codex ↔ Gemini ↔ Claude) | ✅ proven on fresh Pi with fresh accounts |
| MCP auto-wiring into AI CLIs | ✅ shipping |
| Ontology discipline (type caps, entity canonicalization) | ✅ shipping |
| Linux install script + launcher | ✅ shipping |
| Extraction-resistance guardrails | ✅ shipping |
| Test harness (regression-gated before every push) | ✅ shipping |
| Desktop UI app | 🔨 design landed, build next |
| Self-healing observer | 🔨 in-progress |
| Multi-interface (iMessage, phone, Telegram, email) | 🔨 in-progress |
| Mesh mode (shared brain across devices) | 📋 specced |
| Coherent-info memory architecture | 📋 specced |

---

## License

AGPL-3.0 — If you host Orion as a service, you must open-source your changes. The code is open. Your accumulated brain data (memory, knowledge, skills) is always private and always yours.

## Contributing

PRs welcome, with one rule: every commit must carry a DCO `Signed-off-by` trailer. See [`CONTRIBUTING.md`](CONTRIBUTING.md) — it takes one line: `git commit -s -m "..."`. The DCO preserves clean copyright for the project without transferring authorship away from you.

---

<div align="center">

**Built by [James England](https://github.com/1Changetheworld)**

*Started using AI to create in 2026. Nine versions in eight weeks. No team. No funding. No CS degree.*

*The model is fuel. The brain is yours.*

</div>
