# Installing Orion

Orion runs wherever you want it. You don't need special hardware. You don't need a dedicated drive. You don't need an API key.

---

## Option 1: Local Install (Recommended for most people)

Install Orion directly on your computer. Your brain lives on your machine and unifies every AI model you use.

**What you need:**
- Any computer (Windows, macOS, or Linux)
- Python 3.9+
- At least one AI model available (see Fuel Sources below)

**What you get:**
- Persistent memory across all AI models on this machine
- 20 dispatch commands for instant task execution
- Skill system that grows with every interaction
- All 9 operational modes

**Setup (Windows / macOS manual):**
```
git clone https://github.com/1Changetheworld/orion.git
cd orion
pip install -r requirements.txt
python setup.py
python orion_preflight.py    # verify
```

**Setup (Linux / macOS bootstrapped):**
```
git clone https://github.com/1Changetheworld/orion.git
cd orion
bash install.sh
```

The bootstrapper does the same work as the manual steps plus:
- Detects your package manager (apt, dnf, pacman, brew)
- Installs python3 + tkinter + venv if missing (asks first)
- Creates an isolated `.venv` inside the repo
- Offers to install Ollama for free local fuel
- Writes an `orion` launcher to `~/.local/bin/orion` so you can type `orion chat` from any shell
- Runs the setup wizard and preflight check at the end

On a Raspberry Pi (ORIONS HOME) the bootstrapper is the recommended path.

The setup wizard will:
1. Detect your operating system
2. Scan for available AI models (Ollama, Claude CLI, ChatGPT, Gemini, Codex, tgpt)
3. Ask which tier you want (Personal, Developer, Full Arsenal)
4. Configure Orion for your environment
5. Start the brain

No API keys are entered during setup. Orion uses whatever models are already installed or available through your existing subscriptions.

---

## Option 2: Portable Drive Install

Install Orion on an external drive or USB. Your brain travels with you between machines.

**What you need:**
- Any external drive (USB stick, SSD, SD card — any size works, 1GB+ recommended)
- Python 3.9+ on any computer you plug into

**What you get:**
- Everything from Local Install, plus:
- Plug into any machine and your brain is already there
- Same memory, same skills, same personality — different computer
- Auto-detects available models on whatever machine you plug into

**Setup:**
```
# From the drive
cd /path/to/drive
git clone https://github.com/1Changetheworld/orion.git
cd orion

# Run setup wizard in portable mode
python setup.py --portable
```

The `--portable` flag tells Orion to store all data on the drive itself rather than the host machine. When you unplug and move to another computer, everything comes with you.

---

## Fuel Sources (AI Models)

Orion doesn't require any specific AI subscription. It uses whatever is available:

| Fuel Source | Cost | How to Get It | Quality |
|------------|------|---------------|---------|
| Ollama (local models) | Free | [ollama.com](https://ollama.com) — download, install, `ollama pull phi3:mini` | Good for simple tasks |
| Claude CLI | $20-200/mo subscription | [claude.ai](https://claude.ai) — subscribe, install CLI | Best reasoning available |
| ChatGPT | Free tier available | [chatgpt.com](https://chatgpt.com) — create account | Good general purpose |
| Gemini CLI | Free tier available | Google account | Good for web search |
| Codex CLI | ChatGPT Plus subscription | Install via npm | Fast code generation |
| tgpt | Free | `go install github.com/aandrew-me/tgpt@latest` | Multi-provider, free |

**You can use Orion with zero paid subscriptions.** Free Ollama + free ChatGPT tier = a fully functional brain at no cost. Paid subscriptions make it faster and smarter — like premium fuel in a car — but the brain works with anything.

### Does quality change with different models?

Yes. The brain stays the same — your memory, skills, and knowledge don't change. But the quality of reasoning depends on the fuel:

- **Claude Opus** → Complex multi-step analysis, deep code generation, strategic thinking
- **ChatGPT free** → Good conversations, basic analysis, rate limited
- **phi3:mini local** → Handles greetings and simple queries, struggles with complex reasoning
- **No model available** → Dispatch commands still work (<2s), cached knowledge still accessible, but no generative AI

Orion is smart about this. It routes simple tasks to cheap/free models and saves complex work for the best available fuel. You don't configure this — it happens automatically.

---

## Setup Wizard Tiers

During setup, you choose your tier:

### Personal
*For everyone. Your mom. Your friend. You.*

- Portable AI brain with persistent memory
- Works with whatever AI model you already use
- Simple interface — no terminal required after setup
- Memory grows as you interact

### Developer
*Engineers, builders, tinkerers.*

- Everything in Personal
- Multi-model fuel routing with priority control
- CLI access and API endpoints
- Custom skill creation
- Device mesh support (connect multiple machines)

### Full Arsenal
*Power users, security professionals, infrastructure operators.*

- Everything in Developer
- Security scanning and OSINT tools (requires Kali Linux device or VM)
- Multi-device orchestration across a hardware mesh
- Offline knowledge server (Project NOMAD)
- Desktop and cursor control on connected devices
- Hardware intelligence pipelines (car diagnostics, biosignal monitoring)

Each tier enables different capabilities. Tools you don't need are never installed. You can upgrade tiers anytime.

---

## After Setup

Once the wizard completes:

```
Orion is active.

Brain:     orion_server.py running
Memory:    graph (0 nodes) + vector (0 points) — grows with use
Fuel:      Claude CLI detected, Ollama detected (phi3:mini, mistral:7b)
Dispatch:  20 commands ready
Skills:    20 base skills loaded

Talk to Orion through any AI tool on this machine.
He already knows who he is.
```

Your brain starts empty and grows with every conversation. Every fact it learns, every preference it picks up, every tool it discovers — all stored permanently. The longer you use Orion, the smarter he gets. But the models stay the same — Orion is what evolves.
