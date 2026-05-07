#!/usr/bin/env python3
"""
ORION SETUP WIZARD
Detects your environment, scans for available AI models,
and configures Orion for your system.

Usage:
    python setup.py              # Local install
    python setup.py --portable   # Portable drive install
"""
import os
import sys
import json
import shutil
import subprocess
import platform

# ═══════════════════════════════════════════════════════════════
# COLORS
# ═══════════════════════════════════════════════════════════════

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
PURPLE = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

def c(color, text):
    return f"{color}{text}{RESET}"

def banner():
    print()
    print(c(CYAN, "  +-----------------------------------------------+"))
    print(c(CYAN, "  |") + c(BOLD, "            O R I O N                       ") + c(CYAN, "|"))
    print(c(CYAN, "  |") + c(DIM, "   Any AI Model. Same Persona. Same Brain. Same Memories.  ") + c(CYAN, "|"))
    print(c(CYAN, "  +-----------------------------------------------+"))
    print()

# ═══════════════════════════════════════════════════════════════
# DETECTION
# ═══════════════════════════════════════════════════════════════

def detect_os():
    system = platform.system()
    info = {
        "os": system,
        "version": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    if system == "Darwin":
        info["display"] = "macOS"
    elif system == "Windows":
        info["display"] = "Windows"
    elif system == "Linux":
        # Check if Kali
        try:
            with open("/etc/os-release") as f:
                content = f.read()
                if "kali" in content.lower():
                    info["display"] = "Kali Linux"
                else:
                    info["display"] = "Linux"
        except:
            info["display"] = "Linux"
    else:
        info["display"] = system
    return info


def check_command(cmd):
    """Check if a command exists on the system."""
    return shutil.which(cmd) is not None


def detect_fuel():
    """Scan for available AI model sources."""
    fuel = {}

    # Claude CLI
    if check_command("claude"):
        fuel["claude_cli"] = {"available": True, "quality": "Premium", "cost": "$0/req (subscription)", "glow": "cyan"}
        # Check if authenticated
        try:
            result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
            fuel["claude_cli"]["version"] = result.stdout.strip() if result.returncode == 0 else "unknown"
        except:
            fuel["claude_cli"]["version"] = "detected"
    else:
        fuel["claude_cli"] = {"available": False}

    # Ollama (local)
    if check_command("ollama"):
        fuel["ollama_local"] = {"available": True, "quality": "Good", "cost": "Free", "glow": "purple"}
        # List models
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                models = []
                for line in result.stdout.strip().split("\n")[1:]:  # Skip header
                    if line.strip():
                        name = line.split()[0] if line.split() else ""
                        if name:
                            models.append(name)
                fuel["ollama_local"]["models"] = models
            else:
                fuel["ollama_local"]["models"] = []
        except:
            fuel["ollama_local"]["models"] = []
    else:
        fuel["ollama_local"] = {"available": False}

    # Ollama remote (check common LAN addresses)
    fuel["ollama_remote"] = {"available": False, "endpoints": []}
    # Will be configured manually in developer/arsenal tiers

    # ChatGPT (via browser -- always technically available)
    fuel["chatgpt"] = {"available": True, "quality": "Strong", "cost": "Free tier available", "glow": "green",
                       "note": "Via browser or API key"}

    # Gemini CLI
    if check_command("gemini"):
        fuel["gemini"] = {"available": True, "quality": "Good", "cost": "Free tier", "glow": "amber"}
    else:
        fuel["gemini"] = {"available": False}

    # Codex CLI
    if check_command("codex"):
        fuel["codex"] = {"available": True, "quality": "Strong", "cost": "ChatGPT Plus sub", "glow": "green"}
    else:
        fuel["codex"] = {"available": False}

    # tgpt
    if check_command("tgpt"):
        fuel["tgpt"] = {"available": True, "quality": "Varies", "cost": "Free", "glow": "amber"}
    else:
        fuel["tgpt"] = {"available": False}

    return fuel


def detect_gpu():
    """Check for GPU availability."""
    gpu = {"available": False, "name": "", "vram": ""}

    system = platform.system()
    if system == "Windows":
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(", ")
                gpu["available"] = True
                gpu["name"] = parts[0] if len(parts) > 0 else "NVIDIA GPU"
                gpu["vram"] = parts[1] if len(parts) > 1 else "Unknown"
        except:
            pass
    elif system == "Darwin":
        # Apple Silicon detection
        if platform.machine() == "arm64":
            gpu["available"] = True
            gpu["name"] = "Apple Silicon (Metal)"
            gpu["vram"] = "Unified memory"
    elif system == "Linux":
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(", ")
                gpu["available"] = True
                gpu["name"] = parts[0]
                gpu["vram"] = parts[1] if len(parts) > 1 else "Unknown"
        except:
            pass

    return gpu


# ═══════════════════════════════════════════════════════════════
# DISPLAY
# ═══════════════════════════════════════════════════════════════

def show_fuel_report(fuel, gpu):
    """Display detected fuel sources with visual indicators."""
    print(c(CYAN, "  ── Fuel Sources Detected ──────────────────────"))
    print()

    for name, info in fuel.items():
        if name == "ollama_remote":
            continue
        display_name = {
            "claude_cli": "Claude CLI",
            "ollama_local": "Ollama (Local)",
            "chatgpt": "ChatGPT",
            "gemini": "Gemini CLI",
            "codex": "Codex CLI",
            "tgpt": "tgpt",
        }.get(name, name)

        if info.get("available"):
            status = c(GREEN, "[+] DETECTED")
            quality = info.get("quality", "")
            cost = info.get("cost", "")
            detail = f"  {c(DIM, quality)}  {c(DIM, '|')}  {c(DIM, cost)}"

            # Show models for Ollama
            if name == "ollama_local" and info.get("models"):
                models = ", ".join(info["models"][:5])
                if len(info["models"]) > 5:
                    models += f" (+{len(info['models']) - 5} more)"
                detail += f"\n              Models: {c(PURPLE, models)}"
            # Show version for Claude
            elif name == "claude_cli" and info.get("version"):
                detail += f"  {c(DIM, info['version'])}"

            print(f"    {status}  {display_name}{detail}")
        else:
            print(f"    {c(DIM, '[ ] not found')}  {c(DIM, display_name)}")
        print()

    # GPU
    if gpu["available"]:
        print(f"    {c(GREEN, '[+] GPU')}      {gpu['name']}  {c(DIM, gpu['vram'])}")
    else:
        print(f"    {c(DIM, '[ ] no GPU')}   {c(DIM, 'CPU inference only (slower but functional)')}")
    print()


def show_tier_menu():
    """Display tier selection."""
    print(c(CYAN, "  ── Choose Your Tier ──────────────────────────"))
    print()
    print(f"    {c(GREEN, '[1]')}  {c(BOLD, 'Personal')}")
    print(f"         Brain + memory + your AI models")
    print(f"         {c(DIM, 'For everyone. Simple. Just works.')}")
    print()
    print(f"    {c(CYAN, '[2]')}  {c(BOLD, 'Developer')}")
    print(f"         + Multi-model routing, CLI access, custom skills")
    print(f"         {c(DIM, 'For engineers and builders.')}")
    print()
    print(f"    {c(PURPLE, '[3]')}  {c(BOLD, 'Full Arsenal')}")
    print(f"         + Security scanning, OSINT, device mesh, offline")
    print(f"         {c(DIM, 'For power users and security pros.')}")
    print()


# ═══════════════════════════════════════════════════════════════
# SETUP
# ═══════════════════════════════════════════════════════════════

def create_data_dir(config):
    """Create Orion's data directory."""
    data_dir = config["data_dir"]
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "memory"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "knowledge"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "skills"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "conversations"), exist_ok=True)
    return data_dir


def configure_devices():
    """Interactive device configuration for developer/arsenal tiers."""
    print(c(CYAN, "  ── Device Mesh Setup ─────────────────────────"))
    print(f"    {c(DIM, 'Add devices Orion can SSH into and control.')}")
    print(f"    {c(DIM, 'Press Enter with empty name to finish.')}")
    print()

    devices = {}
    while True:
        name = input(f"    Device name (e.g., server, kali): ").strip().lower()
        if not name:
            break
        ip = input(f"    IP address: ").strip()
        user = input(f"    SSH user: ").strip()
        role = input(f"    Role (e.g., Central hub, Security): ").strip()
        devices[name] = {"ip": ip, "user": user, "role": role}
        print(f"    {c(GREEN, '+')} Added {name} ({ip})")
        print()

    return devices


def run_setup():
    """Main setup flow."""
    banner()

    # Check args
    portable = "--portable" in sys.argv

    if portable:
        print(c(YELLOW, "  >>> Portable mode -- data will stay on this drive"))
        print()

    # Step 1: Detect OS
    os_info = detect_os()
    print(c(CYAN, "  ── System ────────────────────────────────────"))
    print(f"    OS:      {c(BOLD, os_info['display'])} {c(DIM, os_info['version'][:30])}")
    print(f"    Arch:    {os_info['machine']}")
    print(f"    Python:  {os_info['python']}")
    print()

    # Step 2: Detect fuel
    print(c(DIM, "  Scanning for AI models..."))
    print()
    fuel = detect_fuel()
    gpu = detect_gpu()
    show_fuel_report(fuel, gpu)

    # Count available fuel
    available_count = sum(1 for k, v in fuel.items()
                         if k != "ollama_remote" and v.get("available"))
    if available_count == 0:
        print(c(RED, "  [!]  No AI models detected."))
        print(c(DIM, "     Install Ollama (ollama.com) for free local AI."))
        print(c(DIM, "     Or install Claude CLI, Gemini CLI, or tgpt."))
        print()
        proceed = input("  Continue anyway? (y/n): ").strip().lower()
        if proceed != "y":
            print(c(DIM, "\n  Setup cancelled. Install a fuel source and try again.\n"))
            return
    else:
        print(f"    {c(GREEN, f'{available_count} fuel source(s) ready')}")
        print()

    # Step 3: Choose tier
    show_tier_menu()
    while True:
        choice = input("    Select tier [1/2/3]: ").strip()
        if choice in ("1", "2", "3"):
            break
        print(c(RED, "    Please enter 1, 2, or 3"))

    tier_map = {"1": "personal", "2": "developer", "3": "arsenal"}
    tier_names = {"1": "Personal", "2": "Developer", "3": "Full Arsenal"}
    tier = tier_map[choice]
    print(f"\n    {c(GREEN, '[OK]')} Selected: {c(BOLD, tier_names[choice])}")
    print()

    # Step 4: Build config
    config = {
        "tier": tier,
        "portable": portable,
        "data_dir": os.path.dirname(os.path.abspath(__file__)) if portable else os.path.expanduser("~/.orion"),
        "brain_port": 5555,
        "fuel": {},
        "devices": {},
        "email": {"enabled": False, "tool_path": "", "address": ""},
        "gpu": gpu,
        "os": os_info,
    }

    # Map fuel detection to config
    for name, info in fuel.items():
        if name == "ollama_remote":
            config["fuel"]["ollama_remote"] = info.get("endpoints", [])
        else:
            config["fuel"][name] = info.get("available", False)

    # Step 5: Device mesh (developer/arsenal only)
    if tier in ("developer", "arsenal"):
        add_devices = input("  Configure device mesh now? (y/n): ").strip().lower()
        if add_devices == "y":
            print()
            config["devices"] = configure_devices()

    # Step 6: Email (optional)
    if tier in ("developer", "arsenal"):
        setup_email = input("  Configure email sending? (y/n): ").strip().lower()
        if setup_email == "y":
            email_tool = input("    Email tool path (e.g., /usr/local/bin/himalaya): ").strip()
            email_addr = input("    Email address: ").strip()
            config["email"] = {"enabled": True, "tool_path": email_tool, "address": email_addr}
            print(f"    {c(GREEN, '[OK]')} Email configured")
            print()

    # Step 7: Create data directory
    data_dir = create_data_dir(config)
    print(f"    {c(GREEN, '[OK]')} Data directory: {data_dir}")

    # Step 8: Save config
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orion_user_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"    {c(GREEN, '[OK]')} Config saved: {config_path}")

    # Step 8b: Inject context files into home dir so detected AI CLIs see Orion.
    # Without this, the preflight's "home context files present" check fails
    # right after a fresh install via the CLI wizard.
    try:
        import orion_ui as _ui
        injected = _ui.inject_context(fuel if isinstance(fuel, dict) else {})
        if injected:
            print(f"    {c(GREEN, '[OK]')} Context files injected: {', '.join(name for name, _ in injected[:4])}")
    except Exception as _e:
        print(f"    {c(YELLOW, '[!]')} Context file injection skipped: {_e.__class__.__name__}")

    # Step 9: Create .gitignore for user data
    gitignore_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gitignore")
    gitignore_entries = [
        "orion_user_config.json",
        "*.pyc",
        "__pycache__/",
        ".orion/",
        "conversations/",
        "knowledge/",
        "memory/",
        "graph_memory.json",
    ]
    # Append if exists, create if not
    existing = set()
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r") as f:
            existing = set(f.read().strip().split("\n"))
    with open(gitignore_path, "w") as f:
        all_entries = existing | set(gitignore_entries)
        f.write("\n".join(sorted(all_entries)) + "\n")

    # Step 10: Summary
    print()
    print(c(CYAN, "  +-----------------------------------------------+"))
    print(c(CYAN, "  |") + c(GREEN, "          Orion is configured.               ") + c(CYAN, "|"))
    print(c(CYAN, "  +-----------------------------------------------+"))
    print()
    print(f"    Brain:     orion_server.py")
    print(f"    Memory:    graph (0 nodes) + vector (0 points) -- grows with use")

    # Fuel summary
    active_fuel = [k for k, v in config["fuel"].items()
                   if v and k != "ollama_remote"]
    if active_fuel:
        fuel_display = ", ".join(active_fuel).replace("_", " ").title()
        print(f"    Fuel:      {c(GREEN, fuel_display)}")
    else:
        print(f"    Fuel:      {c(YELLOW, 'None detected -- install Ollama for free local AI')}")

    print(f"    Dispatch:  20 commands ready")
    print(f"    Skills:    20 base skills loaded")
    print(f"    Tier:      {c(BOLD, tier_names[choice])}")
    print(f"    Mode:      {'Portable (drive)' if portable else 'Local (this machine)'}")
    print()

    # How to start
    print(c(CYAN, "  ── To start Orion ────────────────────────────"))
    print(f"    python orion_server.py")
    print()
    print(c(DIM, "    The brain starts empty and grows with every conversation."))
    print(c(DIM, "    The model is fuel. The brain is yours."))
    print()


if __name__ == "__main__":
    run_setup()
