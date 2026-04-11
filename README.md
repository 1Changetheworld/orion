<div align="center">

# ORION

### The World's First Portable AI Brain

**Your AI. Your Hardware. Your Brain.**

$0 per request. Zero API keys. Zero framework dependencies.

---

*A portable intelligence layer that works with any AI model, on any device, with persistent memory that belongs to you.*

</div>

---

## What is Orion?

Orion is an AI brain that separates intelligence from compute.

Today, your AI conversations are locked inside whatever platform you use. Switch from ChatGPT to Claude — you start over. Use AI on your phone and your laptop — two separate contexts. The model IS the brain, and the brain resets every time.

Orion flips this. The brain is **your data** — memory, knowledge, skills, identity. The model is just fuel. Plug in Claude, ChatGPT, Ollama, Gemini, Codex — Orion uses whatever is available and adapts automatically. Switch models, switch devices, go offline — the brain persists.

**You don't need a paid subscription.** Free Ollama models, free ChatGPT tiers, free Gemini — all valid fuel. Premium subscriptions make it faster and smarter, but the brain works with anything.

**You don't need a special drive.** Install Orion on your computer and it works locally. Want portability? Put it on any USB drive and carry your brain between machines.

**You don't need API keys.** Orion runs on flat-rate subscriptions or free models. No per-token billing. No metered usage. The marginal cost of every request is zero.

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

---

## Interfaces

Seven ways to reach the same brain. A fact learned over a phone call is recalled in a text message ten minutes later.

| Interface | Status | Description |
|-----------|--------|-------------|
| Phone | Real number | Call from any phone. Orion answers with synthesized speech. |
| Telegram | 50+ commands | Full command suite plus natural language processing |
| iMessage | Native macOS | Text Orion from your iPhone — same brain as every other interface |
| Terminal / CLI | Any AI tool | Open any terminal — Orion's context is pre-loaded. No setup. |
| Dashboard | Web UI | Pixel art operations center with live agent visualization |
| Webhook | `POST /chat` | Programmatic access — any script or automation can talk to Orion |
| Any AI Tool | Zero-prompt | Open ChatGPT, Claude, Gemini — Orion is already there |

---

## Operational Modes

| Mode | Status | What It Does | Example |
|------|--------|-------------|---------|
| Standard | Active | Conversational AI + command execution | *"Check my server status and restart the web container"* |
| Deep Dive | Active | Extended reasoning, multi-source research | *"Research every competitor in the AI memory space and summarize their funding, features, and gaps"* |
| Builder | Active | End-to-end project execution from a single prompt | *"Build a REST API for user authentication with JWT tokens, tests, and deploy it"* |
| Absorption | Partial | Indexes new tools and repos into the knowledge base | *Orion scans GitHub trending, reads READMEs, embeds useful tools into its knowledge — gets smarter overnight* |
| Defense | Partial | Hardens security on untrusted networks | *Connect to hotel WiFi — Orion auto-tightens firewall rules, enforces VPN, blocks inbound connections* |
| Hive Mind | Concept | Parallel dispatch across multiple devices | *"Scan all 4 devices for vulnerabilities simultaneously" — each device works independently, results merge* |
| Stealth | Concept | Zero cloud calls, local only, no telemetry | *All traffic stays on-device. No logs. No external connections. Nothing leaves the machine.* |
| The Ant | Concept | Hive-like mass search for deep investigation | *"Find everything about this company" — branches into dozens of search paths like ants, synthesizes findings* |
| Autonomous | Concept | Camera-enabled self-directed operation | *Orion sees through a camera, decides what to do, and acts without user input — monitoring, hardware control* |

---

## Installation

**Local (your computer):**
```bash
git clone https://github.com/1Changetheworld/orion.git
cd orion
python setup.py
```

**Portable (USB drive):**
```bash
cd /path/to/drive
git clone https://github.com/1Changetheworld/orion.git
cd orion
python setup.py --portable
```

The setup wizard detects your OS, scans for available AI models, and asks which tier you want:

- **Personal** — brain + memory + your AI models. Simple. Just works.
- **Developer** — add fuel routing, CLI access, custom skills, device mesh.
- **Full Arsenal** — add security scanning, OSINT, offline knowledge, hardware pipelines.

See [docs/INSTALL.md](docs/INSTALL.md) for full details.

---

## Competitive Landscape

| Capability | Mem0 | Letta | Khoj | Open Interpreter | **Orion** |
|-----------|------|-------|------|-----------------|-----------|
| Persistent memory | Yes | Yes | Yes | No | **Yes** |
| Model-agnostic | Partial | Partial | Partial | Yes | **Yes** |
| Portable (physical) | No | No | No | No | **Yes** |
| Real phone number | No | No | No | No | **Yes** |
| 7+ interfaces | No | No | 2-3 | No | **Yes** |
| $0/request | No | No | No | No | **Yes** |
| No API keys needed | No | No | No | No | **Yes** |
| Offline fallback | No | No | Yes | Local only | **5-tier** |
| Zero dependencies | Own SDK | Heavy | Moderate | Moderate | **Zero** |

These companies have raised a combined $20M+ in venture funding. Orion was built by one person on consumer hardware.

---

## What Orion Is Not

- **Not a replacement for ChatGPT.** Orion uses models like ChatGPT as fuel. If you're happy with one model and never switch, Orion's value is lower for you today.
- **Not finished.** The brain works. The interfaces work. The consumer experience — setup wizard, one-click install, polish — is in development.
- **Not magic.** Quality depends on the fuel. A free local model won't match Claude Opus. The brain is the same either way — the thinking power varies.

---

## Future

- **Hardware Intelligence** — Car diagnostics via OBD-II + AI interpretation. Biosignal monitoring via commodity sensors + AI analysis. The hardware is cheap. The integration layer is Orion.
- **AI Literacy Platform** — Learn to use AI effectively, structured by career field. Like Duolingo for the AI era. Your Orion brain builds as you learn.
- **Portable Soul** — Full auto-detection on any OS. Plug the drive in, Orion activates without configuration.

---

## License

AGPL-3.0 — If you host Orion as a service, you must open-source your changes. The code is open. Your accumulated brain data (memory, knowledge, skills) is always private and always yours.

---

<div align="center">

**Built by [James England](https://github.com/1Changetheworld)**

*Started using AI to create in 2026. Nine versions in eight weeks. No team. No funding. No CS degree.*

*The model is fuel. The brain is yours.*

</div>
