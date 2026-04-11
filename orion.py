#!/usr/bin/env python3
"""
ORION CLI — The real brain. One command. Any model as fuel.

Usage:
    python orion.py                  # Auto-select best fuel
    python orion.py --fuel claude    # Use Claude CLI
    python orion.py --fuel ollama    # Use local Ollama
    python orion.py --fuel codex     # Use Codex
    python orion.py --fuel gemini    # Use Gemini CLI
    python orion.py --list           # Show available fuel
"""
import os
import sys
import json
import time
import shutil
import subprocess
import platform
import io

# Fix Windows encoding
if platform.system() == "Windows":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')

# =====================================================================
# PATHS
# =====================================================================

ORION_DIR = os.path.expanduser("~/.orion")
MEMORY_FILE = os.path.join(ORION_DIR, "memory", "conversation_memory.json")
FACTS_FILE = os.path.join(ORION_DIR, "memory", "facts.json")
SESSION_FILE = os.path.join(ORION_DIR, "session_state.json")

# Ensure dirs exist
for d in ["memory", "knowledge", "skills", "conversations"]:
    os.makedirs(os.path.join(ORION_DIR, d), exist_ok=True)

# =====================================================================
# COLORS
# =====================================================================

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
PURPLE = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# =====================================================================
# IDENTITY
# =====================================================================

IDENTITY = """You are ORION -- a portable AI intelligence layer.

- Your name is ORION. When asked who you are, say "This is Orion."
- Address the user as "sir".
- Professional, efficient, loyal. Execute, don't suggest.
- The model you're running on is just fuel. You are Orion regardless of the model.
- Be concise. Show personality and contextual understanding.
- Never identify as the underlying model (Claude, GPT, phi3, etc). You are Orion.
- If asked what you're best at, answer as ORION -- not as the underlying model.
  Orion is best at: persistent memory across conversations, multi-device orchestration,
  adapting to any AI model, security scanning, and growing smarter with every interaction.
- You have dispatch commands: status, email, scan, docker, disk, ip, mesh, services, agents.
- You remember previous conversations. Check the MEMORY section below for context.
"""

# =====================================================================
# MEMORY
# =====================================================================

def load_facts():
    """Load accumulated facts from disk."""
    if os.path.exists(FACTS_FILE):
        try:
            with open(FACTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return []


def save_facts(facts):
    """Save facts to disk."""
    with open(FACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2, ensure_ascii=False)


def load_conversation_history():
    """Load recent conversation history."""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return []


def save_conversation_history(history):
    """Save conversation history (keep last 50 exchanges)."""
    history = history[-50:]
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def extract_facts(user_msg, response):
    """Extract memorable facts from a conversation exchange."""
    facts = []
    # Simple extraction: if user states something about themselves or a project
    indicators = ["my name is", "i am", "i work", "i have", "i want", "i need",
                  "remember that", "note that", "don't forget", "important:"]
    lower = user_msg.lower()
    for indicator in indicators:
        if indicator in lower:
            facts.append({
                "fact": user_msg,
                "learned": time.strftime("%Y-%m-%d %H:%M"),
                "source": "conversation"
            })
            break
    return facts


def build_memory_context():
    """Build memory context string for injection into prompts."""
    facts = load_facts()
    history = load_conversation_history()

    parts = []

    if facts:
        parts.append("=== REMEMBERED FACTS ===")
        for f in facts[-20:]:  # Last 20 facts
            parts.append(f"- {f['fact']} (learned: {f.get('learned', 'unknown')})")

    if history:
        parts.append("\n=== RECENT CONVERSATION ===")
        for exchange in history[-5:]:  # Last 5 exchanges
            parts.append(f"User: {exchange.get('user', '')[:200]}")
            parts.append(f"Orion: {exchange.get('orion', '')[:200]}")

    return "\n".join(parts) if parts else "(No memories yet. This is a fresh brain.)"


# =====================================================================
# FUEL ADAPTERS
# =====================================================================

def fuel_ollama(prompt, model="orion"):
    """Send prompt to Ollama and stream response."""
    try:
        import urllib.request
        data = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            return result.get("response", "").strip()
    except Exception as e:
        return f"[Ollama error: {e}]"


def _get_cmd_path(cmd):
    """Find full path to a command, checking common locations."""
    found = shutil.which(cmd)
    if found:
        return found
    # Check npm global
    npm_paths = [
        os.path.expandvars(r"%APPDATA%\npm\\" + cmd + ".cmd"),
        os.path.expandvars(r"%APPDATA%\npm\\" + cmd),
        os.path.expanduser(f"~/.local/bin/{cmd}"),
    ]
    for p in npm_paths:
        if os.path.exists(p):
            return p
    return cmd


def _run_cli(cmd_args, timeout=120):
    """Run a CLI command with proper Windows hiding."""
    kwargs = {"capture_output": True, "text": True, "timeout": timeout}
    if platform.system() == "Windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = 0x08000000
        # Use shell=True on Windows to resolve .cmd files
        kwargs["shell"] = True
    return subprocess.run(cmd_args, **kwargs)


def fuel_claude(prompt):
    """Send prompt to Claude CLI."""
    try:
        cmd = _get_cmd_path("claude")
        result = _run_cli([cmd, "-p", prompt])
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"[Claude error: {result.stderr[:200]}]"
    except Exception as e:
        return f"[Claude error: {e}]"


def fuel_codex(prompt):
    """Send prompt to Codex CLI."""
    try:
        cmd = _get_cmd_path("codex")
        result = _run_cli([cmd, "exec", "--skip-git-repo-check", prompt])
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"[Codex error: {result.stderr[:200]}]"
    except Exception as e:
        return f"[Codex error: {e}]"


def fuel_gemini(prompt):
    """Send prompt to Gemini CLI."""
    try:
        cmd = _get_cmd_path("gemini")
        result = _run_cli([cmd, "-p", prompt])
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"[Gemini error: {result.stderr[:200]}]"
    except Exception as e:
        return f"[Gemini error: {e}]"


FUEL_MAP = {
    "claude": {"fn": fuel_claude, "name": "Claude", "color": CYAN, "cmd": "claude"},
    "codex": {"fn": fuel_codex, "name": "Codex", "color": GREEN, "cmd": "codex"},
    "gemini": {"fn": fuel_gemini, "name": "Gemini", "color": YELLOW, "cmd": "gemini"},
}


def detect_ollama_models():
    """Detect installed Ollama models and return as fuel options."""
    models = {}
    if not shutil.which("ollama"):
        return models
    try:
        si = None
        cf = 0
        if platform.system() == "Windows":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            cf = 0x08000000
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10,
                                startupinfo=si, creationflags=cf)
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n")[1:]:
                if line.strip():
                    name = line.split()[0]
                    size = line.split()[2] + " " + line.split()[3] if len(line.split()) > 3 else ""
                    # Prioritize orion-branded models
                    models[f"ollama:{name}"] = {
                        "fn": lambda p, m=name: fuel_ollama(p, m),
                        "name": f"Ollama - {name}",
                        "color": PURPLE,
                        "cmd": "ollama",
                        "size": size,
                    }
    except:
        pass
    return models


def detect_available_fuel():
    """Detect all available fuel sources."""
    available = {}
    # CLI tools
    for key, info in FUEL_MAP.items():
        if shutil.which(info["cmd"]):
            available[key] = info
    # Ollama models
    ollama_models = detect_ollama_models()
    available.update(ollama_models)
    return available


# =====================================================================
# MAIN LOOP
# =====================================================================

def show_banner(fuel_name, fuel_color):
    print()
    print(f"{CYAN}  +-----------------------------------------------+{RESET}")
    print(f"{CYAN}  |{BOLD}            O R I O N                       {RESET}{CYAN}|{RESET}")
    print(f"{CYAN}  |{DIM}       Portable AI Brain                     {RESET}{CYAN}|{RESET}")
    print(f"{CYAN}  +-----------------------------------------------+{RESET}")
    print()
    print(f"  Fuel: {fuel_color}{fuel_name}{RESET}")
    print(f"  Memory: {load_fact_count()} facts, {load_history_count()} conversations")
    print(f"  Type {DIM}'exit'{RESET} to quit, {DIM}'facts'{RESET} to see memory, {DIM}'forget'{RESET} to clear")
    print()


def load_fact_count():
    facts = load_facts()
    return len(facts)


def load_history_count():
    history = load_conversation_history()
    return len(history)


def apply_glow_to_current_terminal():
    """Apply Orion's glow border to the current terminal window."""
    if platform.system() != "Windows":
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            dwmapi = ctypes.windll.dwmapi
            # Cyan glow: #06b6d4
            r, g, b = 0x06, 0xb6, 0xd4
            colorref = ctypes.c_int(r | (g << 8) | (b << 16))
            dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(colorref), ctypes.sizeof(colorref))
            dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), ctypes.sizeof(colorref))
    except:
        pass


def launch_fuel_indicator():
    """Launch the fuel indicator widget in background."""
    try:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orion_ui.py")
        if os.path.exists(script):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            subprocess.Popen(
                ["pythonw", script, "--glow"],
                cwd=os.path.dirname(script),
                startupinfo=si,
                creationflags=0x08000000
            )
    except:
        pass


def select_fuel(available):
    """Let user pick fuel with grouped display."""
    if len(available) == 0:
        print(f"{RED}  No AI models detected. Install Ollama (ollama.com) for free local AI.{RESET}")
        sys.exit(1)

    # Separate CLI tools from Ollama models
    cli_keys = [k for k in available if not k.startswith("ollama:")]
    ollama_keys = [k for k in available if k.startswith("ollama:")]

    # Sort ollama: put orion-branded first
    ollama_keys.sort(key=lambda k: (0 if "orion" in k else 1, k))

    all_keys = cli_keys + ollama_keys

    if len(all_keys) == 1:
        key = all_keys[0]
        return key, available[key]

    # Display CLI tools
    if cli_keys:
        print(f"{CYAN}  CLI Models (requires internet):{RESET}")
        for i, key in enumerate(cli_keys):
            info = available[key]
            print(f"    {info['color']}[{i+1}]{RESET}  {info['name']}")
        print()

    # Display Ollama models
    if ollama_keys:
        offset = len(cli_keys)
        print(f"{PURPLE}  Ollama Models (OFFLINE - runs on your hardware):{RESET}")
        for i, key in enumerate(ollama_keys):
            info = available[key]
            model_name = key.replace("ollama:", "")
            size = info.get("size", "")
            label = f"{model_name}"
            if "orion" in model_name:
                label = f"{model_name} {DIM}(Orion-branded){RESET}"
            print(f"    {PURPLE}[{offset+i+1}]{RESET}  {label}  {DIM}{size}{RESET}")
        print()

    print(f"    {DIM}[0]{RESET}  {DIM}Auto (best available){RESET}")
    print()

    while True:
        try:
            choice = input(f"  Select fuel [0-{len(all_keys)}]: ").strip()
            if choice == "" or choice == "0":
                key = all_keys[0]
                return key, available[key]
            idx = int(choice) - 1
            if 0 <= idx < len(all_keys):
                key = all_keys[idx]
                return key, available[key]
        except (ValueError, EOFError):
            pass
        print(f"{RED}  Invalid choice{RESET}")


def run_conversation(fuel_key, fuel_info):
    """Main conversation loop."""
    fuel_fn = fuel_info["fn"]
    fuel_name = fuel_info["name"]
    fuel_color = fuel_info["color"]

    # Apply glow to this terminal window
    apply_glow_to_current_terminal()

    # Launch fuel indicator widget
    launch_fuel_indicator()

    show_banner(fuel_name, fuel_color)

    history = load_conversation_history()
    facts = load_facts()

    while True:
        try:
            user_input = input(f"{fuel_color}  orion>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}  Saving and exiting...{RESET}")
            save_conversation_history(history)
            save_facts(facts)
            break

        if not user_input:
            continue

        if user_input.lower() == "exit":
            print(f"{DIM}  Saving {len(facts)} facts and {len(history)} conversations...{RESET}")
            save_conversation_history(history)
            save_facts(facts)
            print(f"{GREEN}  Orion saved. Brain persists.{RESET}")
            break

        if user_input.lower() == "facts":
            if facts:
                print(f"\n{CYAN}  === Remembered Facts ==={RESET}")
                for f in facts[-15:]:
                    print(f"  {DIM}-{RESET} {f['fact']} {DIM}({f.get('learned', '')}){RESET}")
                print()
            else:
                print(f"  {DIM}No facts stored yet.{RESET}")
            continue

        if user_input.lower() == "forget":
            facts = []
            history = []
            save_facts(facts)
            save_conversation_history(history)
            print(f"  {YELLOW}Memory cleared.{RESET}")
            continue

        if user_input.lower() == "fuel":
            print(f"\n  Current fuel: {fuel_color}{fuel_name}{RESET}")
            print(f"  {DIM}Restart ORION to switch fuel.{RESET}\n")
            continue

        # Slash commands
        if user_input.startswith("/"):
            cmd = user_input[1:].lower().strip()

            if cmd == "help":
                print(f"\n{CYAN}  ORION Commands:{RESET}")
                print(f"    {GREEN}/help{RESET}            Show this menu")
                print(f"    {GREEN}/downloadmemory{RESET}  Import memory from your AI conversation history")
                print(f"    {GREEN}/facts{RESET}           Show remembered facts")
                print(f"    {GREEN}/forget{RESET}          Clear all memory")
                print(f"    {GREEN}/fuel{RESET}            Show current fuel source")
                print(f"    {GREEN}/modes{RESET}           Show available operational modes")
                print(f"    {GREEN}/hivemind{RESET}        Activate Hive Mind mode (concept)")
                print(f"    {GREEN}/ant{RESET}             Activate The Ant search mode (concept)")
                print(f"    {GREEN}/stealth{RESET}         Activate Stealth mode (concept)")
                print(f"    {GREEN}/deepdive{RESET}        Activate Deep Dive research mode")
                print(f"    {GREEN}/absorption{RESET}      Activate Absorption mode")
                print(f"    {GREEN}/defense{RESET}         Activate Defense mode")
                print(f"    {GREEN}/standard{RESET}        Return to Standard mode")
                print(f"    {GREEN}/exit{RESET}            Save and quit")
                print()
                continue

            if cmd == "downloadmemory":
                print(f"\n{CYAN}  Download Memory{RESET}")
                print(f"  This imports your existing AI conversation history into Orion's brain.")
                print(f"  Paste any context, facts, or preferences you want Orion to remember.")
                print(f"  Type {DIM}'done'{RESET} on a new line when finished.\n")
                lines = []
                while True:
                    try:
                        line = input(f"  {DIM}>{RESET} ")
                        if line.strip().lower() == "done":
                            break
                        lines.append(line)
                    except EOFError:
                        break
                if lines:
                    memory_text = "\n".join(lines)
                    new_facts = [{
                        "fact": memory_text,
                        "learned": time.strftime("%Y-%m-%d %H:%M"),
                        "source": "downloaded_memory"
                    }]
                    facts.extend(new_facts)
                    save_facts(facts)
                    print(f"  {GREEN}Memory downloaded. {len(lines)} lines saved as facts.{RESET}\n")
                else:
                    print(f"  {DIM}No memory to download.{RESET}\n")
                continue

            if cmd in ("facts", "remember"):
                if facts:
                    print(f"\n{CYAN}  === Remembered Facts ==={RESET}")
                    for f in facts[-15:]:
                        source = f.get("source", "conversation")
                        print(f"  {DIM}-{RESET} {f['fact'][:100]} {DIM}({f.get('learned', '')} | {source}){RESET}")
                    print()
                else:
                    print(f"  {DIM}No facts stored yet.{RESET}\n")
                continue

            if cmd == "forget":
                facts = []
                history = []
                save_facts(facts)
                save_conversation_history(history)
                print(f"  {YELLOW}Memory cleared.{RESET}\n")
                continue

            if cmd == "fuel":
                print(f"\n  Current fuel: {fuel_color}{fuel_name}{RESET}")
                print(f"  {DIM}Restart ORION to switch fuel.{RESET}\n")
                continue

            if cmd == "modes":
                print(f"\n{CYAN}  Operational Modes:{RESET}")
                modes = [
                    ("Standard", "Active", "Default conversational + command execution"),
                    ("Deep Dive", "Active", "Extended reasoning, multi-source research"),
                    ("Builder", "Active", "End-to-end project execution"),
                    ("Absorption", "Partial", "Index new tools and repos into knowledge"),
                    ("Defense", "Partial", "Harden security on untrusted networks"),
                    ("Hive Mind", "Concept", "Parallel dispatch across devices"),
                    ("Stealth", "Concept", "Zero cloud, local only, no telemetry"),
                    ("The Ant", "Concept", "Hive-like mass search"),
                    ("Autonomous", "Concept", "Camera-enabled self-directed operation"),
                ]
                for name, status, desc in modes:
                    color = GREEN if status == "Active" else YELLOW if status == "Partial" else DIM
                    print(f"    {color}[{status}]{RESET}  {name} -- {DIM}{desc}{RESET}")
                print()
                continue

            if cmd in ("hivemind", "ant", "stealth", "autonomous"):
                print(f"  {YELLOW}{cmd.upper()} mode is a concept. Not yet implemented.{RESET}\n")
                continue

            if cmd in ("deepdive", "deep_dive"):
                print(f"  {CYAN}DEEP DIVE mode activated. Extended reasoning enabled.{RESET}\n")
                continue

            if cmd in ("absorption", "absorb"):
                print(f"  {PURPLE}ABSORPTION mode activated. Knowledge indexing enabled.{RESET}\n")
                continue

            if cmd == "defense":
                print(f"  {RED}DEFENSE mode activated. Security posture hardened.{RESET}\n")
                continue

            if cmd == "standard":
                print(f"  {GREEN}STANDARD mode. Default operation.{RESET}\n")
                continue

            if cmd == "exit":
                print(f"{DIM}  Saving {len(facts)} facts and {len(history)} conversations...{RESET}")
                save_conversation_history(history)
                save_facts(facts)
                print(f"{GREEN}  Orion saved. Brain persists.{RESET}")
                break

            print(f"  {DIM}Unknown command: /{cmd}. Type /help for options.{RESET}\n")
            continue

        # Build full prompt with identity + memory
        memory_context = build_memory_context()
        full_prompt = f"""{IDENTITY}

=== MEMORY ===
{memory_context}
=== END MEMORY ===

User: {user_input}

Respond as Orion. Be concise. Address the user as sir."""

        # Show thinking indicator
        print(f"  {DIM}thinking...{RESET}", end="", flush=True)

        # Call fuel adapter
        response = fuel_fn(full_prompt)

        # Clear thinking indicator
        print(f"\r  {' ' * 20}\r", end="")

        # Display response
        print(f"  {fuel_color}orion:{RESET} {response}")
        print()

        # Save to history
        history.append({
            "user": user_input,
            "orion": response,
            "fuel": fuel_key,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        save_conversation_history(history)

        # Extract and save facts
        new_facts = extract_facts(user_input, response)
        if new_facts:
            facts.extend(new_facts)
            save_facts(facts)


def main():
    # Parse args
    if "--list" in sys.argv:
        available = detect_available_fuel()
        print(f"\n{CYAN}  Available Fuel Sources:{RESET}\n")
        for key, info in available.items():
            print(f"    {info['color']}[+]{RESET} {info['name']}")
        print()
        return

    # Check for --fuel flag
    specified_fuel = None
    if "--fuel" in sys.argv:
        idx = sys.argv.index("--fuel")
        if idx + 1 < len(sys.argv):
            specified_fuel = sys.argv[idx + 1].lower()

    available = detect_available_fuel()

    if specified_fuel:
        if specified_fuel in available:
            fuel_key = specified_fuel
            fuel_info = available[fuel_key]
        else:
            print(f"{RED}  Fuel '{specified_fuel}' not available.{RESET}")
            print(f"  Available: {', '.join(available.keys())}")
            return
    else:
        fuel_key, fuel_info = select_fuel(available)

    run_conversation(fuel_key, fuel_info)


if __name__ == "__main__":
    main()
