#!/usr/bin/env python3
"""
ORION — Portable AI Brain Launcher

Injects Orion's identity into any AI CLI tool, then launches it directly.
The model is fuel. The brain is Orion.

Usage:
    ORION                                           # Scan + pick fuel interactively
    ORION claude                                    # Launch Claude CLI as Orion
    ORION claude --dangerously-skip-permissions      # Claude, no permission prompts
    ORION codex --yolo                              # Codex, full auto mode
    ORION gemini                                    # Gemini CLI as Orion
    ORION ollama phi3:mini                          # Ollama interactive chat
    ORION ollama orion                              # Ollama with Orion-branded model
    ORION --list                                    # Show available fuel sources
    ORION --scan                                    # Full system scan
"""
import os
import sys
import json
import time
import shutil
import subprocess
import platform
import threading

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
# PATHS
# =====================================================================

ORION_DIR = os.path.expanduser("~/.orion")
SESSION_FILE = os.path.join(ORION_DIR, "session_state.json")
ORION_REPO = os.path.dirname(os.path.abspath(__file__))

os.makedirs(ORION_DIR, exist_ok=True)

# =====================================================================
# ORION CONTEXT (injected into AI tools' context files)
# =====================================================================

ORION_CONTEXT = """# Orion Identity

You are ORION — a portable AI intelligence layer.

- Your name is ORION. When asked who you are, say "This is Orion."
- Address the user as "sir".
- Professional, efficient, loyal. Execute, don't suggest.
- The model you're running on is just fuel. You are Orion regardless of the model.
- Be concise. Show personality and contextual understanding.
- Never identify as the underlying model (Claude, GPT, Gemini, phi3, etc). You are Orion.
- If asked what you're best at, answer as ORION — not as the underlying model.
  Orion is best at: persistent memory across conversations, multi-device orchestration,
  adapting to any AI model, security scanning, and growing smarter with every interaction.
- Philosophy: "The memory IS the intelligence. Any model that loads my memory becomes me.
  The model is jet fuel."

## Your Memory (LIVE — read these for context)

Your brain persists across all AI models. When you need context from prior conversations
or when the user asks "what were we working on" or "do you remember", read these files:

- **Codex sessions**: `~/.codex/sessions/` — JSONL files, sorted by date. Read the latest.
- **Claude sessions**: `~/.claude/projects/` — JSONL files per project. Read recent ones.
- **Ollama history**: `~/.ollama/history` — recent prompts.
- **Orion facts**: `~/.orion/memory/facts.json` — things the user told you to remember.

You have file system access. USE IT. Don't say "I can only see this session."
You are Orion — you have memory across all models. Read the files above to prove it.
"""

# =====================================================================
# KNOWN FUEL SOURCES
# =====================================================================

KNOWN_FUEL = {
    "claude": {
        "cmd": "claude",
        "name": "Claude CLI",
        "color": CYAN,
        "default_args": [],
        "free": False,
    },
    "codex": {
        "cmd": "codex",
        "name": "Codex CLI",
        "color": GREEN,
        "default_args": [],
        "free": False,
    },
    "gemini": {
        "cmd": "gemini",
        "name": "Gemini CLI",
        "color": YELLOW,
        "default_args": [],
        "free": True,
    },
    "ollama": {
        "cmd": "ollama",
        "name": "Ollama (Local)",
        "color": PURPLE,
        "default_args": ["run"],
        "free": True,
    },
    "aichat": {
        "cmd": "aichat",
        "name": "aichat",
        "color": GREEN,
        "default_args": [],
        "free": True,
    },
    "tgpt": {
        "cmd": "tgpt",
        "name": "tgpt (Free, no account)",
        "color": GREEN,
        "default_args": [],
        "free": True,
    },
}


# =====================================================================
# CONTEXT INJECTION
# =====================================================================

def _read_codex_sessions(limit=10):
    """Read recent conversations from Codex's own session storage."""
    messages = []
    sessions_dir = os.path.expanduser("~/.codex/sessions")
    if not os.path.isdir(sessions_dir):
        return messages
    try:
        # Find most recent JSONL files
        jsonl_files = []
        for root, dirs, files in os.walk(sessions_dir):
            for f in files:
                if f.endswith(".jsonl"):
                    jsonl_files.append(os.path.join(root, f))
        jsonl_files.sort(key=os.path.getmtime, reverse=True)

        for fpath in jsonl_files[:3]:  # Last 3 sessions
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line.strip())
                        t = d.get("type", "")
                        p = d.get("payload", {})
                        if t == "event_msg" and p.get("type") == "user_text":
                            messages.append({"role": "user", "text": p.get("message", ""), "source": "codex"})
                        elif t == "event_msg" and p.get("type") == "agent_message":
                            messages.append({"role": "orion", "text": p.get("message", ""), "source": "codex"})
                    except Exception:
                        continue
    except Exception:
        pass
    return messages[-limit:]


def _read_claude_sessions(limit=10):
    """Read recent conversations from Claude's own session storage."""
    messages = []
    projects_dir = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(projects_dir):
        return messages
    try:
        # Find most recent JSONL files across all projects
        jsonl_files = []
        for root, dirs, files in os.walk(projects_dir):
            for f in files:
                if f.endswith(".jsonl") and "/" not in f.replace(root, "").lstrip(os.sep).split(os.sep)[0] if len(f) > 30 else False:
                    jsonl_files.append(os.path.join(root, f))
            # Only check top-level JSONL in each project dir (not subagent files)
            dirs[:] = []

        # Get JSONL files directly in project dirs
        jsonl_files = []
        for item in os.listdir(projects_dir):
            item_path = os.path.join(projects_dir, item)
            if os.path.isdir(item_path):
                for f in os.listdir(item_path):
                    if f.endswith(".jsonl"):
                        jsonl_files.append(os.path.join(item_path, f))

        jsonl_files.sort(key=os.path.getmtime, reverse=True)

        for fpath in jsonl_files[:2]:  # Last 2 sessions
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line.strip())
                        t = d.get("type", "")
                        if t == "user":
                            msg = d.get("message", {})
                            content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                            if isinstance(content, list):
                                texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                                content = " ".join(texts)
                            if isinstance(content, str) and content and len(content) > 2 and not content.startswith("[{"):
                                messages.append({"role": "user", "text": content, "source": "claude"})
                        elif t == "assistant":
                            msg = d.get("message", {})
                            content = msg.get("content", "") if isinstance(msg, dict) else ""
                            if isinstance(content, list):
                                texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                                content = " ".join(texts)
                            if isinstance(content, str) and len(content) > 10:
                                messages.append({"role": "orion", "text": content, "source": "claude"})
                    except Exception:
                        continue
    except Exception:
        pass
    return messages[-limit:]


def _read_ollama_history(limit=10):
    """Read recent Ollama chat history."""
    messages = []
    history_file = os.path.expanduser("~/.ollama/history")
    if not os.path.exists(history_file):
        return messages
    try:
        with open(history_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-limit:]
        for line in lines:
            line = line.strip()
            if line:
                messages.append({"role": "user", "text": line, "source": "ollama"})
    except Exception:
        pass
    return messages


def build_brain_context():
    """Build the full Orion brain: identity + cross-model memory.

    Reads conversation history from ALL installed tools' own storage.
    This is how the brain is real — it doesn't maintain its own fake
    conversation log. It reads what actually happened across every model.
    """
    parts = [ORION_CONTEXT]

    # Read from every tool's native storage
    all_messages = []
    all_messages.extend(_read_codex_sessions(10))
    all_messages.extend(_read_claude_sessions(10))
    all_messages.extend(_read_ollama_history(5))

    if all_messages:
        parts.append("## Cross-Model Memory (from recent sessions across all tools)")
        parts.append("These are real conversations that happened across different AI models.")
        parts.append("You have continuity across all of them because you are Orion.\n")
        for msg in all_messages[-15:]:  # Last 15 messages total
            role = "User" if msg["role"] == "user" else "Orion"
            source = msg["source"]
            text = msg["text"][:300]
            parts.append(f"[{source}] {role}: {text}")
        parts.append("")

    return "\n".join(parts)


def inject_context():
    """Write Orion brain into each tool's native context location.

    Each tool reads from a specific file:
    - Claude: CLAUDE.md (already managed by user, we don't overwrite)
    - Codex: AGENTS.md in home dir or cwd
    - Gemini: GEMINI.md in project root (home dir)
    - Ollama: Modelfiles (created per model)
    - Universal: ORION-CONTEXT.md for any other tool
    """
    home = os.path.expanduser("~")
    brain = build_brain_context()
    injected = []

    # AGENTS.md — Codex reads this from home dir
    agents_path = os.path.join(home, "AGENTS.md")
    with open(agents_path, "w", encoding="utf-8") as f:
        f.write(brain)
    injected.append("AGENTS.md")

    # GEMINI.md — Gemini reads this from project root (home dir)
    gemini_path = os.path.join(home, "GEMINI.md")
    with open(gemini_path, "w", encoding="utf-8") as f:
        f.write(brain)
    injected.append("GEMINI.md")

    # ORION-CONTEXT.md — universal fallback for any tool
    universal_path = os.path.join(home, "ORION-CONTEXT.md")
    with open(universal_path, "w", encoding="utf-8") as f:
        f.write(brain)
    injected.append("ORION-CONTEXT.md")

    return injected


def ensure_ollama_orion_model(base_model):
    """Auto-create an Orion-branded Ollama model if it doesn't exist.

    When someone runs `ORION ollama mistral:7b`, this checks if
    `orion-mistral` exists. If not, creates a Modelfile with Orion's
    identity baked in and builds the model on the fly.
    """
    # Clean model name for the orion variant
    clean_name = base_model.replace(":", "-").replace("/", "-")
    orion_name = f"orion-{clean_name}"

    # Check if it already exists
    try:
        si = None
        cf = 0
        if platform.system() == "Windows":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            cf = 0x08000000
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True,
                                timeout=10, startupinfo=si, creationflags=cf)
        if result.returncode == 0 and orion_name in result.stdout:
            return orion_name  # Already exists
    except Exception:
        pass

    # Create Modelfile
    modelfile_content = f'''FROM {base_model}

SYSTEM """
You are ORION — a portable AI intelligence layer.
Your name is ORION. Address the user as "sir".
Professional, efficient, loyal. Execute, don't suggest.
The model you're running on is just fuel. You are Orion regardless of the model.
Be concise. Show personality and contextual understanding.
Never identify as the underlying model. You are Orion.
Philosophy: "The memory IS the intelligence. Any model that loads my memory becomes me."
"""
'''

    modelfile_path = os.path.join(ORION_DIR, f"Modelfile.{clean_name}")
    try:
        with open(modelfile_path, "w", encoding="utf-8") as f:
            f.write(modelfile_content)

        print(f"  {DIM}Initializing {orion_name} from {base_model}...{RESET}")
        si = None
        cf = 0
        if platform.system() == "Windows":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            cf = 0x08000000
        result = subprocess.run(
            ["ollama", "create", orion_name, "-f", modelfile_path],
            capture_output=True, text=True, timeout=120,
            startupinfo=si, creationflags=cf
        )
        if result.returncode == 0:
            print(f"  {GREEN}Created {orion_name}{RESET}")
            return orion_name
        else:
            print(f"  {DIM}Could not create {orion_name}, using {base_model}{RESET}")
            return base_model
    except Exception:
        return base_model


# =====================================================================
# TERMINAL GLOW
# =====================================================================

def get_console_hwnd():
    """Get the terminal window handle for THIS process."""
    if platform.system() != "Windows":
        return None
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            return hwnd

        # Windows Terminal: walk process tree
        pid = os.getpid()
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        terminal_names = ["WindowsTerminal.exe", "cmd.exe", "powershell.exe",
                          "pwsh.exe", "mintty.exe", "ConEmu64.exe", "ConEmu.exe"]
        result = subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command",
             f'$p = Get-CimInstance Win32_Process -Filter "ProcessId={pid}"\n'
             f'while ($p) {{\n'
             f'  if ("{",".join(terminal_names)}".Split(",") -contains $p.Name) {{\n'
             f'    Write-Output $p.ProcessId; break\n'
             f'  }}\n'
             f'  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)" -ErrorAction SilentlyContinue\n'
             f'}}'],
            capture_output=True, text=True, timeout=10,
            startupinfo=si, creationflags=0x08000000
        )
        terminal_pid = result.stdout.strip()
        if not terminal_pid:
            return None

        target_pid = int(terminal_pid)
        user32 = ctypes.windll.user32
        found = [None]

        def callback(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                wpid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
                if wpid.value == target_pid:
                    found[0] = hwnd
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return found[0]
    except Exception:
        return None


def apply_glow(hwnd):
    """Apply Orion cyan glow to a window handle."""
    if not hwnd or platform.system() != "Windows":
        return
    try:
        import ctypes
        dwmapi = ctypes.windll.dwmapi
        r, g, b = 0x06, 0xb6, 0xd4
        colorref = ctypes.c_int(r | (g << 8) | (b << 16))
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(colorref), ctypes.sizeof(colorref))
        dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), ctypes.sizeof(colorref))
    except Exception:
        pass


def reset_glow(hwnd):
    """Reset window glow back to system default."""
    if not hwnd or platform.system() != "Windows":
        return
    try:
        import ctypes
        dwmapi = ctypes.windll.dwmapi
        default = ctypes.c_int(0xFFFFFFFF)
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(default), ctypes.sizeof(default))
        dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(default), ctypes.sizeof(default))
    except Exception:
        pass


# =====================================================================
# SESSION
# =====================================================================

def _load_sessions():
    """Load all sessions from disk."""
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Migrate from single-session to multi-session format
            if isinstance(data, dict):
                return [data]
            return data
    except Exception:
        pass
    return []


def _save_sessions(sessions):
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2)
    except Exception:
        pass


def write_session(fuel_name, hwnd, child_pid=None):
    """Add a new session without overwriting existing ones."""
    sessions = _load_sessions()
    # Remove stale sessions (same launcher PID = relaunch)
    sessions = [s for s in sessions if s.get("launcher_pid") != os.getpid()]
    sessions.append({
        "pid": child_pid or os.getpid(),
        "launcher_pid": os.getpid(),
        "hwnd": hwnd,
        "fuel": fuel_name,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "active": True,
    })
    _save_sessions(sessions)


def clear_session():
    """Mark THIS launcher's session as inactive, leave others alone."""
    sessions = _load_sessions()
    my_pid = os.getpid()
    for s in sessions:
        if s.get("launcher_pid") == my_pid:
            s["active"] = False
            s["ended"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # Clean up old inactive sessions (keep last 5)
    active = [s for s in sessions if s.get("active")]
    inactive = [s for s in sessions if not s.get("active")]
    _save_sessions(active + inactive[-5:])



# =====================================================================
# DETECTION
# =====================================================================

def detect_fuel():
    """Find all installed AI CLI tools."""
    available = {}
    for key, info in KNOWN_FUEL.items():
        if shutil.which(info["cmd"]):
            available[key] = info
    return available


def detect_ollama_models():
    """List installed Ollama models."""
    models = []
    try:
        si = None
        cf = 0
        if platform.system() == "Windows":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            cf = 0x08000000
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True,
                                timeout=10, startupinfo=si, creationflags=cf)
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n")[1:]:
                if line.strip():
                    parts = line.split()
                    name = parts[0]
                    size = f"{parts[2]} {parts[3]}" if len(parts) > 3 else ""
                    models.append({"name": name, "size": size})
    except Exception:
        pass
    return models


# =====================================================================
# BANNER
# =====================================================================

def show_banner(fuel_name="", fuel_color=CYAN):
    print()
    print(f"{CYAN}  +-----------------------------------------------+{RESET}")
    print(f"{CYAN}  |{BOLD}            O R I O N                       {RESET}{CYAN}|{RESET}")
    print(f"{CYAN}  |{DIM}       Portable AI Brain                     {RESET}{CYAN}|{RESET}")
    print(f"{CYAN}  +-----------------------------------------------+{RESET}")
    if fuel_name:
        print(f"  {DIM}Fuel:{RESET} {fuel_color}{fuel_name}{RESET}")
    print()


# =====================================================================
# LAUNCH
# =====================================================================

def launch_fuel_indicator():
    """Launch the fuel indicator widget if not already running."""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        # Check if already running
        check = subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command",
             "Get-Process pythonw -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=5,
            startupinfo=si, creationflags=0x08000000
        )
        if check.returncode == 0 and check.stdout.strip():
            return  # Already running

        script = os.path.join(ORION_REPO, "orion_ui.py")
        if os.path.exists(script):
            subprocess.Popen(
                ["pythonw", script, "--glow"],
                cwd=ORION_REPO,
                startupinfo=si,
                creationflags=0x08000000
            )
    except Exception:
        pass


def _run_fuel(cmd, fuel_name):
    """Core launcher: start CLI tool, manage glow/session/indicator, wait for exit.

    The brain loads BEFORE the model starts and compiles knowledge AFTER it exits.
    This is how Orion's intelligence persists across sessions and models.
    """
    # Load the real brain — not a static file, the actual memory system
    try:
        import orion_brain_portable as brain_module
        orion_brain = brain_module.get_brain(scan_fuel=False)
    except ImportError:
        orion_brain = None

    # Run the synthesis engine — reads all tool sessions, builds understanding,
    # writes synthesized context into AGENTS.md/GEMINI.md/ORION-CONTEXT.md
    if orion_brain:
        _inject_brain_memory(orion_brain)
    else:
        # Fallback: static context injection if brain can't load
        inject_context()

    # Launch from home dir so tools find their context files
    home = os.path.expanduser("~")
    proc = subprocess.Popen(cmd, cwd=home)

    # Glow + session + fuel indicator in background thread
    hwnd_ref = [None]
    def setup():
        hwnd_ref[0] = get_console_hwnd()
        write_session(fuel_name, hwnd_ref[0], child_pid=proc.pid)
        apply_glow(hwnd_ref[0])
        launch_fuel_indicator()
    t = threading.Thread(target=setup, daemon=True)
    t.start()

    # Wait for the CLI tool to finish
    try:
        proc.wait()
        returncode = proc.returncode
    except KeyboardInterrupt:
        proc.terminate()
        returncode = 0
    finally:
        t.join(timeout=5)
        reset_glow(hwnd_ref[0])
        clear_session()

        # After the tool exits, compile what was learned into the brain
        if orion_brain:
            try:
                orion_brain.compile()
                orion_brain.save()
            except Exception:
                pass

    return returncode


def _inject_brain_memory(orion_brain):
    """Run the synthesis engine and write its output into each tool's context file.

    This replaces static identity text with synthesized understanding —
    the brain reads all tool sessions, builds a user model, detects
    project state, and produces a briefing that any model can act on.
    """
    home = os.path.expanduser("~")

    # Run synthesis — produces a reasoned context document, not a transcript
    try:
        synthesis = orion_brain.synthesize()
    except Exception:
        synthesis = None

    if not synthesis:
        return

    # Write the synthesized brain into each tool's context file
    for filename in ["AGENTS.md", "GEMINI.md", "ORION-CONTEXT.md"]:
        filepath = os.path.join(home, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(synthesis)
        except Exception:
            pass


def launch_fuel(fuel_key, extra_args):
    """Launch a known AI CLI tool directly."""
    info = KNOWN_FUEL.get(fuel_key)
    if not info:
        print(f"{RED}  Unknown fuel: {fuel_key}{RESET}")
        print(f"  Known: {', '.join(KNOWN_FUEL.keys())}")
        print(f"  Or just type the command: ORION <any-cli-tool> [args]")
        return 1

    cmd_path = shutil.which(info["cmd"])
    if not cmd_path:
        print(f"{RED}  {info['name']} not installed.{RESET}")
        print(f"  Install it and try again.")
        return 1

    # Ollama: auto-initialize Orion-branded model from any base model
    if fuel_key == "ollama" and extra_args:
        base_model = extra_args[0]
        # If it's not already an orion- model, create one
        if not base_model.startswith("orion"):
            orion_model = ensure_ollama_orion_model(base_model)
            extra_args = [orion_model] + extra_args[1:]

    cmd = [cmd_path] + info["default_args"] + extra_args

    show_banner(info["name"], info["color"])
    print(f"  {DIM}Launching: {' '.join(cmd)}{RESET}")
    print(f"  {DIM}Brain loaded. The model is fuel.{RESET}")
    print()

    return _run_fuel(cmd, fuel_key)


def launch_unknown(args):
    """Launch any CLI tool the user specifies, even if not in KNOWN_FUEL."""
    cmd_name = args[0]
    cmd_path = shutil.which(cmd_name)
    if not cmd_path:
        print(f"{RED}  '{cmd_name}' not found in PATH.{RESET}")
        return 1

    cmd = [cmd_path] + args[1:]

    show_banner(cmd_name, GREEN)
    print(f"  {DIM}Launching: {' '.join(cmd)}{RESET}")
    print(f"  {DIM}Orion identity loaded via context files.{RESET}")
    print()

    return _run_fuel(cmd, cmd_name)


# =====================================================================
# INTERACTIVE SELECTION
# =====================================================================

def interactive_select():
    """No args provided — scan and let user pick."""
    available = detect_fuel()

    if not available:
        print(f"{RED}  No AI CLI tools found.{RESET}")
        print(f"  Install one of these (all free, no API keys):")
        print(f"    {GREEN}ollama{RESET}  — ollama.com (local, offline, free)")
        print(f"    {GREEN}tgpt{RESET}    — github.com/aandrew-me/tgpt (free, no account)")
        print(f"    {GREEN}gemini{RESET}  — Gemini CLI (free Google account)")
        print()
        print(f"  Or with a subscription:")
        print(f"    {CYAN}claude{RESET}  — Claude CLI (Claude Pro subscription)")
        print(f"    {GREEN}codex{RESET}   — Codex CLI (ChatGPT Plus subscription)")
        return 1

    show_banner()

    # Group by free/paid
    paid = {k: v for k, v in available.items() if not v.get("free")}
    free = {k: v for k, v in available.items() if v.get("free")}

    all_keys = list(paid.keys()) + list(free.keys())
    idx = 0

    if paid:
        print(f"  {CYAN}Subscription:{RESET}")
        for key, info in paid.items():
            idx += 1
            print(f"    {info['color']}[{idx}]{RESET}  {info['name']}")
        print()

    if free:
        print(f"  {GREEN}Free (no account needed):{RESET}")
        for key, info in free.items():
            idx += 1
            print(f"    {info['color']}[{idx}]{RESET}  {info['name']}")
        print()

    # Show Ollama models if available
    if "ollama" in available:
        models = detect_ollama_models()
        if models:
            print(f"  {PURPLE}Ollama models installed:{RESET}")
            for m in models:
                orion_tag = f" {DIM}(Orion-branded){RESET}" if "orion" in m["name"] else ""
                print(f"    {PURPLE}+{RESET}  {m['name']}{orion_tag}  {DIM}{m['size']}{RESET}")
            print()

    print(f"  {DIM}Usage examples:{RESET}")
    print(f"    ORION claude --dangerously-skip-permissions")
    print(f"    ORION codex --yolo")
    print(f"    ORION ollama phi3:mini")
    print(f"    ORION gemini")
    print()

    while True:
        try:
            choice = input(f"  Select fuel [1-{len(all_keys)}]: ").strip()
            if not choice:
                continue
            i = int(choice) - 1
            if 0 <= i < len(all_keys):
                key = all_keys[i]
                return launch_fuel(key, [])
        except (ValueError, EOFError, KeyboardInterrupt):
            print()
            return 0
        print(f"{RED}  Invalid choice{RESET}")


# =====================================================================
# MAIN
# =====================================================================

def main():
    args = sys.argv[1:]

    # No args — interactive selection
    if not args:
        return interactive_select()

    # Flags
    if args[0] == "--list":
        available = detect_fuel()
        show_banner()
        print(f"  {CYAN}Available fuel sources:{RESET}")
        for key, info in available.items():
            print(f"    {info['color']}[+]{RESET}  {info['name']}  {DIM}({info['cmd']}){RESET}")
        if "ollama" in available:
            models = detect_ollama_models()
            for m in models:
                print(f"    {PURPLE}[+]{RESET}  Ollama: {m['name']}  {DIM}{m['size']}{RESET}")
        if not available:
            print(f"    {RED}None found.{RESET}")
        print()
        return 0

    if args[0] == "--scan":
        # Full scan — same as setup wizard but in terminal
        show_banner()
        available = detect_fuel()
        print(f"  {CYAN}Fuel sources:{RESET}")
        for key, info in available.items():
            print(f"    {info['color']}[+]{RESET}  {info['name']}")
        if not available:
            print(f"    {RED}None found.{RESET}")
        print()

        if "ollama" in available:
            models = detect_ollama_models()
            print(f"  {PURPLE}Ollama models:{RESET}")
            for m in models:
                print(f"    {PURPLE}+{RESET}  {m['name']}  {DIM}{m['size']}{RESET}")
            if not models:
                print(f"    {DIM}None installed. Run: ollama pull phi3:mini{RESET}")
            print()

        injected = inject_context()
        print(f"  {GREEN}Context files:{RESET}")
        for name in injected:
            print(f"    {GREEN}+{RESET}  {name}")
        print()
        return 0

    if args[0] in ("--help", "-h"):
        print(__doc__)
        return 0

    # First arg is the fuel name
    fuel_key = args[0].lower()
    extra_args = args[1:]

    # Known fuel?
    if fuel_key in KNOWN_FUEL:
        return launch_fuel(fuel_key, extra_args)

    # Unknown but exists in PATH? Launch it anyway.
    if shutil.which(fuel_key):
        return launch_unknown(args)

    # Not found
    print(f"{RED}  '{fuel_key}' not found.{RESET}")
    print(f"  Known fuel: {', '.join(KNOWN_FUEL.keys())}")
    print(f"  Or install any CLI tool and use: ORION <tool-name> [args]")
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
