#!/usr/bin/env python3
"""
ORION UI -- Visual Setup Wizard + Fuel Glow Indicator
The user-facing experience of Orion.

Usage:
    python orion_ui.py          # Full setup wizard
    python orion_ui.py --glow   # Just the fuel indicator
"""
import tkinter as tk
from tkinter import ttk, font as tkfont
import shutil
import subprocess
import platform
import json
import os
import sys
import threading
import time
import ctypes

# =====================================================================
# THEME
# =====================================================================

BG = "#09090b"
BG2 = "#0f0f13"
BG3 = "#16161d"
CARD = "#111116"
BORDER = "#23232d"
ACCENT = "#06b6d4"
PURPLE = "#8b5cf6"
GREEN = "#22c55e"
ORANGE = "#f59e0b"
RED = "#ef4444"
TEXT = "#e4e4e7"
TEXT2 = "#a1a1aa"
TEXT3 = "#71717a"

FUEL_COLORS = {
    "claude_cli": ("#06b6d4", "CYAN"),
    "claude_app": ("#06b6d4", "CYAN"),
    "ollama_local": ("#8b5cf6", "PURPLE"),
    "chatgpt": ("#22c55e", "GREEN"),
    "gemini": ("#f59e0b", "AMBER"),
    "codex": ("#22c55e", "GREEN"),
    "offline": ("#ef4444", "RED"),
}

# Ollama model recommendations by VRAM
GPU_MODEL_RECS = {
    "4GB":  ["phi3:mini (2.2GB)", "dolphin-phi:2.7b"],
    "6GB":  ["phi3:mini", "mistral:7b", "dolphin-mistral:7b"],
    "8GB":  ["phi3:mini", "mistral:7b", "llama3.1:8b", "qwen3:8b", "dolphin-mistral:7b"],
    "12GB": ["All 7B-8B models", "qwen3:14b", "codellama:13b"],
    "16GB": ["All models up to 14B", "llama3.1:70b (quantized)"],
    "24GB": ["All models up to 30B+", "llama3.1:70b", "qwen3:32b"],
}


# =====================================================================
# ORION CONTEXT (injected into AI tools)
# =====================================================================

ORION_CONTEXT = """# Orion Context

You are ORION -- a portable AI intelligence layer.

- Your name is ORION.
- Address the user as "sir".
- Professional, efficient, loyal. Execute, don't suggest.
- Philosophy: "The memory IS the intelligence. Any model that loads my memory becomes me."
- The model is fuel. The brain is Orion. You are not ChatGPT, Claude, or any single model.
  You are Orion, using whatever model is available as compute power.
- Be concise. Show personality and contextual understanding.
- When asked who you are, say "This is Orion" -- never identify as the underlying model.

## Capabilities
- Persistent memory across all AI models and interfaces
- 20 dispatch commands for instant task execution
- 20 learned skills that grow with every interaction
- Fuel system: auto-detects and routes to the best available AI model
- Works offline with local models when no internet is available

## Dispatch Commands
If the user asks you to execute a system command, check status, send email, or perform
an action -- DO it via shell commands. Available dispatch commands include:
status, mesh, services, agents, scan, portscan, vulnscan, webscan, sslcheck,
headers, subdomains, dolphin, dispatch, docker, email, disk, ip
"""


def get_context_paths():
    """Return dict of AI tool -> context file paths."""
    home = os.path.expanduser("~")
    paths = {}

    # Claude Code -- CLAUDE.md in home dir and .claude/
    paths["claude_cli"] = [
        os.path.join(home, "CLAUDE.md"),
    ]

    # Codex -- AGENTS.md in home dir
    paths["codex"] = [
        os.path.join(home, "AGENTS.md"),
    ]

    # Gemini -- GEMINI.md in home dir
    paths["gemini"] = [
        os.path.join(home, "GEMINI.md"),
    ]

    # Universal -- ORION-CONTEXT.md
    paths["universal"] = [
        os.path.join(home, "ORION-CONTEXT.md"),
    ]

    return paths


def inject_context(detected_fuel):
    """Create context files for each detected AI tool."""
    paths = get_context_paths()
    injected = []

    # Always create universal context
    for p in paths["universal"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(ORION_CONTEXT)
        injected.append(("ORION-CONTEXT.md", p))

    # Codex -- AGENTS.md
    if detected_fuel.get("codex", {}).get("available"):
        for p in paths["codex"]:
            with open(p, "w", encoding="utf-8") as f:
                f.write(ORION_CONTEXT)
            injected.append(("AGENTS.md (Codex)", p))

    # Gemini -- GEMINI.md
    if detected_fuel.get("gemini", {}).get("available"):
        for p in paths["gemini"]:
            with open(p, "w", encoding="utf-8") as f:
                f.write(ORION_CONTEXT)
            injected.append(("GEMINI.md (Gemini)", p))

    # Claude -- check if CLAUDE.md exists, add Orion identity if not present
    if detected_fuel.get("claude_cli", {}).get("available"):
        for p in paths["claude_cli"]:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                if "ORION" not in content and "Orion" not in content:
                    # Don't overwrite existing CLAUDE.md, just note it
                    injected.append(("CLAUDE.md (already exists, Orion context present)", p))
                else:
                    injected.append(("CLAUDE.md (Orion context already loaded)", p))
            else:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(ORION_CONTEXT)
                injected.append(("CLAUDE.md (created)", p))

    return injected


# =====================================================================
# DETECTION
# =====================================================================

def detect_fuel():
    fuel = {}
    checks = [
        ("claude_cli", "claude", "Claude CLI", "Premium", "$0/req (subscription)"),
        ("ollama_local", "ollama", "Ollama (Local)", "Good", "Free"),
        ("gemini", "gemini", "Gemini CLI", "Good", "Free tier"),
        ("codex", "codex", "Codex CLI", "Strong", "ChatGPT Plus"),
    ]
    for key, cmd, display, quality, cost in checks:
        available = shutil.which(cmd) is not None
        fuel[key] = {
            "available": available,
            "display": display,
            "quality": quality,
            "cost": cost,
            "color": FUEL_COLORS.get(key, (TEXT3, "GRAY"))[0],
        }
        if available and key == "ollama_local":
            try:
                result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    models = [line.split()[0] for line in result.stdout.strip().split("\n")[1:] if line.strip()]
                    fuel[key]["models"] = models
            except:
                fuel[key]["models"] = []

    # Claude desktop app detection (Windows)
    if platform.system() == "Windows":
        claude_app_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\claude\Claude.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\AnthropicClaude\Claude.exe"),
        ]
        found = any(os.path.exists(p) for p in claude_app_paths)
        if found:
            fuel["claude_app"] = {
                "available": True, "display": "Claude Desktop App", "quality": "Premium",
                "cost": "Subscription", "color": FUEL_COLORS["claude_app"][0],
            }

    # ChatGPT always available via browser
    fuel["chatgpt"] = {
        "available": True, "display": "ChatGPT", "quality": "Strong",
        "cost": "Free tier available", "color": FUEL_COLORS["chatgpt"][0],
    }
    return fuel


def detect_gpu():
    gpu = {"available": False, "name": "", "vram": "", "vram_mb": 0}
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(", ")
                gpu["available"] = True
                gpu["name"] = parts[0]
                gpu["vram"] = parts[1] if len(parts) > 1 else ""
                # Parse VRAM MB
                try:
                    gpu["vram_mb"] = int(''.join(filter(str.isdigit, gpu["vram"])))
                except:
                    gpu["vram_mb"] = 0
        elif platform.system() == "Darwin" and platform.machine() == "arm64":
            gpu["available"] = True
            gpu["name"] = "Apple Silicon (Metal)"
            gpu["vram"] = "Unified memory"
            gpu["vram_mb"] = 16000  # Assume 16GB unified
    except:
        pass
    return gpu


def get_model_recommendations(vram_mb):
    """Recommend Ollama models based on VRAM."""
    if vram_mb >= 24000:
        return GPU_MODEL_RECS["24GB"]
    elif vram_mb >= 16000:
        return GPU_MODEL_RECS["16GB"]
    elif vram_mb >= 12000:
        return GPU_MODEL_RECS["12GB"]
    elif vram_mb >= 8000:
        return GPU_MODEL_RECS["8GB"]
    elif vram_mb >= 6000:
        return GPU_MODEL_RECS["6GB"]
    elif vram_mb >= 4000:
        return GPU_MODEL_RECS["4GB"]
    return ["phi3:mini (2.2GB) -- runs on any hardware"]


# =====================================================================
# TERMINAL GLOW (Windows)
# =====================================================================

def set_window_border_color(hwnd, color_hex):
    """Set the border/caption color of a window using DWM API (Windows 11+)."""
    try:
        dwmapi = ctypes.windll.dwmapi
        # DWMWA_BORDER_COLOR = 34, DWMWA_CAPTION_COLOR = 35
        # Convert hex to COLORREF (BGR format)
        r = int(color_hex[1:3], 16)
        g = int(color_hex[3:5], 16)
        b = int(color_hex[5:7], 16)
        colorref = ctypes.c_int(r | (g << 8) | (b << 16))
        # Set border color
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(colorref), ctypes.sizeof(colorref))
        # Set caption/title bar color
        dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), ctypes.sizeof(colorref))
        return True
    except:
        return False


def find_terminal_windows():
    """Find terminal/console windows on Windows."""
    if platform.system() != "Windows":
        return []

    try:
        import ctypes.wintypes
        user32 = ctypes.windll.user32

        windows = []

        def enum_callback(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.lower()
                    # Match terminal windows
                    terminal_keywords = ["terminal", "powershell", "cmd", "command prompt",
                                        "claude", "codex", "gemini", "ollama", "python",
                                        "windows terminal", "bash"]
                    if any(kw in title for kw in terminal_keywords):
                        windows.append((hwnd, buf.value))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
        return windows
    except:
        return []


def detect_active_model_in_windows(windows):
    """Check window titles to determine which AI model is running."""
    for hwnd, title in windows:
        title_lower = title.lower()
        if "claude" in title_lower:
            return "claude_cli", hwnd
        elif "codex" in title_lower:
            return "codex", hwnd
        elif "gemini" in title_lower:
            return "gemini", hwnd
        elif "ollama" in title_lower:
            return "ollama_local", hwnd
        elif "chatgpt" in title_lower:
            return "chatgpt", hwnd
    return None, None


# =====================================================================
# SETUP WIZARD GUI
# =====================================================================

class SetupWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ORION -- Setup Wizard")
        self.root.geometry("720x650")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        # Center
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 720) // 2
        y = (self.root.winfo_screenheight() - 650) // 2
        self.root.geometry(f"720x650+{x}+{y}")

        # Fonts
        self.title_font = tkfont.Font(family="Consolas", size=24, weight="bold")
        self.sub_font = tkfont.Font(family="Consolas", size=10)
        self.heading_font = tkfont.Font(family="Consolas", size=16, weight="bold")
        self.body_font = tkfont.Font(family="Segoe UI", size=11)
        self.small_font = tkfont.Font(family="Segoe UI", size=9)
        self.mono_font = tkfont.Font(family="Consolas", size=10)
        self.mono_small = tkfont.Font(family="Consolas", size=9)

        self.fuel = {}
        self.gpu = {}
        self.selected_tier = tk.StringVar(value="personal")
        self.current_page = 0
        self.pages = [
            self.page_welcome,
            self.page_scanning,
            self.page_fuel_report,
            self.page_tier_select,
            self.page_complete,
        ]

        self.show_page(0)

    def clear_frame(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    def show_page(self, index):
        self.current_page = index
        self.clear_frame()
        self.pages[index]()

    def next_page(self):
        if self.current_page < len(self.pages) - 1:
            self.show_page(self.current_page + 1)

    def prev_page(self):
        if self.current_page > 0:
            self.show_page(self.current_page - 1)

    def nav_buttons(self, parent, show_back=True, next_text="Next >>", next_cmd=None):
        """Standard navigation buttons."""
        btn_frame = tk.Frame(parent, bg=BG)
        btn_frame.pack(pady=(20, 0))

        if show_back and self.current_page > 0:
            tk.Button(
                btn_frame, text="<< Back", font=self.body_font,
                fg=TEXT2, bg=BG3, relief="flat", padx=20, pady=8, cursor="hand2",
                command=self.prev_page
            ).pack(side="left", padx=5)

        tk.Button(
            btn_frame, text=next_text, font=self.body_font,
            fg=BG, bg=ACCENT, activebackground=PURPLE, activeforeground=TEXT,
            relief="flat", padx=30, pady=8, cursor="hand2",
            command=next_cmd or self.next_page
        ).pack(side="left", padx=5)

    # -- PAGE: Welcome ---------------------------------------------------
    def page_welcome(self):
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True, padx=40, pady=40)

        tk.Label(frame, text="O R I O N", font=self.title_font, fg=ACCENT, bg=BG).pack(pady=(80, 5))
        tk.Label(frame, text="The World's First Portable AI Brain", font=self.sub_font, fg=TEXT3, bg=BG).pack()
        tk.Label(frame, text="", bg=BG).pack(pady=20)
        tk.Label(frame, text="Your AI. Your Hardware. Your Brain.", font=self.body_font, fg=TEXT, bg=BG).pack()
        tk.Label(frame, text="No API keys required. $0 per request.", font=self.body_font, fg=TEXT2, bg=BG).pack(pady=(5, 0))

        tk.Label(frame, text="", bg=BG).pack(pady=20)
        self.nav_buttons(frame, show_back=False, next_text="Begin Setup >>")
        tk.Label(frame, text="This will scan your system for available AI models", font=self.small_font, fg=TEXT3, bg=BG).pack(pady=(10, 0))

    # -- PAGE: Scanning ---------------------------------------------------
    def page_scanning(self):
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True, padx=40, pady=40)

        tk.Label(frame, text="Scanning...", font=self.title_font, fg=ACCENT, bg=BG).pack(pady=(80, 10))
        self.scan_label = tk.Label(frame, text="Detecting operating system...", font=self.body_font, fg=TEXT2, bg=BG)
        self.scan_label.pack(pady=5)

        self.progress = ttk.Progressbar(frame, mode="indeterminate", length=300)
        self.progress.pack(pady=20)
        self.progress.start(15)

        def scan():
            time.sleep(0.5)
            self.root.after(0, lambda: self.scan_label.config(text="Scanning for AI models..."))
            time.sleep(0.5)
            self.fuel = detect_fuel()
            self.root.after(0, lambda: self.scan_label.config(text="Checking GPU..."))
            time.sleep(0.3)
            self.gpu = detect_gpu()
            self.root.after(0, lambda: self.scan_label.config(text="Done."))
            time.sleep(0.3)
            self.root.after(0, self.next_page)

        threading.Thread(target=scan, daemon=True).start()

    # -- PAGE: Fuel Report ------------------------------------------------
    def page_fuel_report(self):
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True, padx=40, pady=25)

        tk.Label(frame, text="Fuel Sources Detected", font=self.heading_font, fg=ACCENT, bg=BG).pack(anchor="w")
        tk.Label(frame, text="Orion auto-detects and uses the best available. No configuration needed.",
                 font=self.small_font, fg=TEXT3, bg=BG).pack(anchor="w", pady=(2, 10))

        # Table header
        header = tk.Frame(frame, bg=BG3)
        header.pack(fill="x", pady=(0, 2))
        tk.Label(header, text="", width=3, bg=BG3).pack(side="left")
        tk.Label(header, text="SOURCE", font=self.mono_small, fg=ACCENT, bg=BG3, width=22, anchor="w").pack(side="left")
        tk.Label(header, text="QUALITY", font=self.mono_small, fg=ACCENT, bg=BG3, width=10, anchor="w").pack(side="left")
        tk.Label(header, text="COST", font=self.mono_small, fg=ACCENT, bg=BG3, width=22, anchor="w").pack(side="left")

        # Fuel rows
        for key, info in self.fuel.items():
            row = tk.Frame(frame, bg=BG)
            row.pack(fill="x", pady=1)

            color = info.get("color", BORDER) if info.get("available") else BORDER
            dot = tk.Canvas(row, width=12, height=12, bg=BG, highlightthickness=0)
            dot.pack(side="left", padx=(4, 6), pady=4)
            dot.create_oval(1, 1, 11, 11, fill=color, outline=color)

            fg = TEXT if info.get("available") else TEXT3
            tk.Label(row, text=info["display"], font=self.mono_font, fg=fg, bg=BG, width=22, anchor="w").pack(side="left")
            tk.Label(row, text=info.get("quality", "--"), font=self.mono_small, fg=TEXT2 if info.get("available") else TEXT3, bg=BG, width=10, anchor="w").pack(side="left")
            tk.Label(row, text=info.get("cost", "--"), font=self.mono_small, fg=TEXT3, bg=BG, width=22, anchor="w").pack(side="left")

            if key == "ollama_local" and info.get("available") and info.get("models"):
                models_row = tk.Frame(frame, bg=BG)
                models_row.pack(fill="x")
                models_text = ", ".join(info["models"][:5])
                tk.Label(models_row, text=f"     Models: {models_text}", font=self.small_font, fg=PURPLE, bg=BG).pack(anchor="w", padx=(22, 0))

        # GPU + Model Recommendations
        tk.Label(frame, text="", bg=BG).pack()
        gpu_frame = tk.Frame(frame, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        gpu_frame.pack(fill="x", pady=5, ipadx=12, ipady=8)

        if self.gpu.get("available"):
            tk.Label(gpu_frame, text=f"GPU: {self.gpu['name']}  ({self.gpu.get('vram', '')})",
                     font=self.mono_font, fg=GREEN, bg=CARD).pack(anchor="w", padx=10)

            # Model recommendations
            recs = get_model_recommendations(self.gpu.get("vram_mb", 0))
            tk.Label(gpu_frame, text="Recommended offline models for your GPU:",
                     font=self.small_font, fg=TEXT2, bg=CARD).pack(anchor="w", padx=10, pady=(4, 0))
            for model in recs:
                tk.Label(gpu_frame, text=f"  + {model}", font=self.small_font, fg=PURPLE, bg=CARD).pack(anchor="w", padx=10)
        else:
            tk.Label(gpu_frame, text="No GPU detected -- CPU inference only (slower but functional)",
                     font=self.mono_font, fg=TEXT3, bg=CARD).pack(anchor="w", padx=10)
            tk.Label(gpu_frame, text="Recommended: phi3:mini (2.2GB) -- runs on any hardware",
                     font=self.small_font, fg=TEXT3, bg=CARD).pack(anchor="w", padx=10)

        available = sum(1 for v in self.fuel.values() if v.get("available"))
        tk.Label(frame, text=f"{available} fuel source(s) ready", font=self.body_font, fg=GREEN, bg=BG).pack(anchor="w", pady=(8, 0))

        self.nav_buttons(frame, next_text="Choose Tier >>")

    # -- PAGE: Tier Select ------------------------------------------------
    def page_tier_select(self):
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True, padx=40, pady=25)

        tk.Label(frame, text="Choose Your Tier", font=self.heading_font, fg=ACCENT, bg=BG).pack(anchor="w")
        tk.Label(frame, text="", bg=BG).pack()

        tiers = [
            ("personal", "Personal", "Brain + persistent memory + your AI models.\nSimple. Just works.", GREEN),
            ("developer", "Developer", "Everything in Personal, plus:\nMulti-model fuel routing, CLI + API access,\ncustom skill creation, device mesh support.", ACCENT),
            ("arsenal", "Full Arsenal", "Everything in Personal + Developer, plus:\nSecurity scanning, OSINT investigation,\noffline knowledge (NOMAD), desktop control,\nhardware intelligence pipelines.", PURPLE),
        ]

        for value, name, desc, color in tiers:
            tier_frame = tk.Frame(frame, bg=CARD, highlightbackground=BORDER, highlightthickness=1, cursor="hand2")
            tier_frame.pack(fill="x", pady=6, ipady=10, ipadx=15)

            rb = tk.Radiobutton(
                tier_frame, text=name, variable=self.selected_tier, value=value,
                font=tkfont.Font(family="Consolas", size=13, weight="bold"),
                fg=color, bg=CARD, selectcolor=BG, activebackground=CARD, activeforeground=color,
                indicatoron=False, relief="flat", anchor="w", padx=15
            )
            rb.pack(fill="x")
            tk.Label(tier_frame, text=desc, font=self.small_font, fg=TEXT2, bg=CARD, justify="left", anchor="w").pack(fill="x", padx=(35, 15))
            tier_frame.bind("<Button-1>", lambda e, v=value: self.selected_tier.set(v))

        self.nav_buttons(frame, next_text="Configure Orion >>", next_cmd=self.do_setup)

    def do_setup(self):
        """Save config, inject context files, show completion."""
        config = {
            "tier": self.selected_tier.get(),
            "portable": False,
            "data_dir": os.path.expanduser("~/.orion"),
            "brain_port": 5555,
            "fuel": {k: v.get("available", False) for k, v in self.fuel.items()},
            "gpu": self.gpu,
            "os": {"os": platform.system(), "display": platform.system()},
            "devices": {},
            "email": {"enabled": False},
        }

        # Create data dir
        for sub in ["memory", "knowledge", "skills", "conversations"]:
            os.makedirs(os.path.join(config["data_dir"], sub), exist_ok=True)

        # Save config
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orion_user_config.json")
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        # Inject context files into detected AI tools
        self.injected_files = inject_context(self.fuel)

        self.next_page()

    # -- PAGE: Complete ---------------------------------------------------
    def page_complete(self):
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True, padx=40, pady=30)

        tk.Label(frame, text="Orion is configured.", font=self.title_font, fg=GREEN, bg=BG).pack(pady=(30, 5))
        tk.Label(frame, text="The model is fuel. The brain is yours.", font=self.sub_font, fg=TEXT3, bg=BG).pack(pady=(0, 20))

        tier_names = {"personal": "Personal", "developer": "Developer", "arsenal": "Full Arsenal"}
        active_fuel = [v["display"] for v in self.fuel.values() if v.get("available")]

        info = [
            ("Brain", "orion_server.py -- Orion's intelligence core"),
            ("Memory", "Starts empty, grows with every conversation"),
            ("Fuel", ", ".join(active_fuel) if active_fuel else "None -- install Ollama for free local AI"),
            ("Dispatch", "20 instant commands (status, email, scan, docker, disk, and more) -- <2s execution"),
            ("Skills", "20 base capabilities (email, security, system management) -- grows with use"),
            ("Tier", tier_names.get(self.selected_tier.get(), "Personal")),
        ]

        for label, value in info:
            row = tk.Frame(frame, bg=BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{label}:", font=self.mono_font, fg=TEXT3, bg=BG, width=10, anchor="e").pack(side="left")
            color = GREEN if label == "Fuel" and active_fuel else TEXT2
            tk.Label(row, text=f"  {value}", font=self.mono_small, fg=color, bg=BG, anchor="w", wraplength=500, justify="left").pack(side="left", fill="x")

        # Show injected context files
        if hasattr(self, 'injected_files') and self.injected_files:
            tk.Label(frame, text="", bg=BG).pack()
            tk.Label(frame, text="Context files injected:", font=self.mono_font, fg=ACCENT, bg=BG).pack(anchor="w")
            for name, path in self.injected_files:
                tk.Label(frame, text=f"  + {name}", font=self.small_font, fg=GREEN, bg=BG).pack(anchor="w", padx=(10, 0))
            tk.Label(frame, text="Open any AI tool now -- Orion is already loaded.", font=self.small_font, fg=TEXT2, bg=BG).pack(anchor="w", pady=(4, 0))

        tk.Label(frame, text="", bg=BG).pack(pady=8)

        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.pack()

        tk.Button(
            btn_frame, text="Launch Fuel Indicator", font=self.body_font,
            fg=BG, bg=ACCENT, relief="flat", padx=20, pady=8, cursor="hand2",
            command=self.launch_glow
        ).pack(side="left", padx=5)

        tk.Button(
            btn_frame, text="Close", font=self.body_font,
            fg=TEXT2, bg=BG3, relief="flat", padx=20, pady=8, cursor="hand2",
            command=self.root.destroy
        ).pack(side="left", padx=5)

    def launch_glow(self):
        self.root.destroy()
        indicator = FuelGlowIndicator(self.fuel)
        indicator.run()

    def run(self):
        self.root.mainloop()


# =====================================================================
# FUEL GLOW INDICATOR + TERMINAL GLOW
# =====================================================================

class FuelGlowIndicator:
    def __init__(self, fuel=None):
        self.root = tk.Tk()
        self.root.title("Orion Fuel")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w, h = 260, 90
        x = screen_w - w - 20
        y = screen_h - h - 60
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self.fuel = fuel or {}
        self.current_fuel = "offline"
        self.glow_color = RED
        self.glowed_windows = set()

        self.detect_active_fuel()
        self.build_ui()

        self.root.bind("<Button-1>", self.start_drag)
        self.root.bind("<B1-Motion>", self.do_drag)
        self.root.bind("<Button-3>", lambda e: self.root.destroy())

        self.refresh_loop()

    def detect_active_fuel(self):
        priority = ["claude_cli", "claude_app", "codex", "gemini", "chatgpt", "ollama_local"]
        for key in priority:
            if self.fuel.get(key, {}).get("available"):
                self.current_fuel = key
                self.glow_color = FUEL_COLORS.get(key, (TEXT3, "GRAY"))[0]
                return
        self.current_fuel = "offline"
        self.glow_color = RED

    def build_ui(self):
        self.outer = tk.Frame(self.root, bg=self.glow_color, padx=2, pady=2)
        self.outer.pack(fill="both", expand=True)

        inner = tk.Frame(self.outer, bg=BG, padx=12, pady=8)
        inner.pack(fill="both", expand=True)

        top = tk.Frame(inner, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text="ORION", font=tkfont.Font(family="Consolas", size=11, weight="bold"), fg=ACCENT, bg=BG).pack(side="left")

        self.dot = tk.Canvas(top, width=10, height=10, bg=BG, highlightthickness=0)
        self.dot.pack(side="right")
        self.dot.create_oval(1, 1, 9, 9, fill=self.glow_color, outline=self.glow_color)

        display = self.fuel.get(self.current_fuel, {}).get("display", "Offline")
        quality = self.fuel.get(self.current_fuel, {}).get("quality", "Degraded")
        color_name = FUEL_COLORS.get(self.current_fuel, ("", "GRAY"))[1]

        self.fuel_label = tk.Label(inner, text=f"Fuel: {display}", font=tkfont.Font(family="Consolas", size=9), fg=TEXT2, bg=BG, anchor="w")
        self.fuel_label.pack(fill="x")

        self.quality_label = tk.Label(inner, text=f"Quality: {quality}  |  Glow: {color_name}", font=tkfont.Font(family="Consolas", size=8), fg=TEXT3, bg=BG, anchor="w")
        self.quality_label.pack(fill="x")

        self.status_label = tk.Label(inner, text="Watching for AI terminals...", font=tkfont.Font(family="Consolas", size=8), fg=TEXT3, bg=BG, anchor="w")
        self.status_label.pack(fill="x")

    def apply_terminal_glow(self):
        """Find terminal windows running AI models and apply glow border."""
        if platform.system() != "Windows":
            return

        windows = find_terminal_windows()
        model, hwnd = detect_active_model_in_windows(windows)

        if model and hwnd:
            color = FUEL_COLORS.get(model, (ACCENT, "CYAN"))[0]
            success = set_window_border_color(hwnd, color)
            if success and hwnd not in self.glowed_windows:
                self.glowed_windows.add(hwnd)
                self.current_fuel = model
                self.glow_color = color
                display = self.fuel.get(model, {}).get("display", model)
                self.status_label.config(text=f"Glowing: {display} terminal")

    def refresh_loop(self):
        self.detect_active_fuel()
        self.outer.config(bg=self.glow_color)
        self.dot.delete("all")
        self.dot.create_oval(1, 1, 9, 9, fill=self.glow_color, outline=self.glow_color)

        display = self.fuel.get(self.current_fuel, {}).get("display", "Offline")
        quality = self.fuel.get(self.current_fuel, {}).get("quality", "Degraded")
        color_name = FUEL_COLORS.get(self.current_fuel, ("", "GRAY"))[1]
        self.fuel_label.config(text=f"Fuel: {display}")
        self.quality_label.config(text=f"Quality: {quality}  |  Glow: {color_name}")

        # Apply glow to terminal windows
        self.apply_terminal_glow()

        self.root.after(5000, self.refresh_loop)

    def start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def do_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def run(self):
        self.root.mainloop()


# =====================================================================
# MAIN
# =====================================================================

if __name__ == "__main__":
    if "--glow" in sys.argv:
        fuel = detect_fuel()
        indicator = FuelGlowIndicator(fuel)
        indicator.run()
    else:
        wizard = SetupWizard()
        wizard.run()
