#!/usr/bin/env python3
"""
Proto-Orion — the zero-LLM onboarding experience.

This is the symbiote before it has a host. It runs RIGHT AFTER install,
before any model is configured. Pure Python, scripted conversation tree,
no LLM calls. Enough of Orion to introduce itself, gather identity, and
walk the user to attaching a fuel (cloud CLI or local Ollama).

By the time this hands off to the full LLM-powered orion chat:
  - Graph has an entity node for the user
  - Preferences and ongoing work are seeded
  - Tool inventory is stored
  - Fuel is configured, MCP is wired, context files are in place

Goal: the first experience of Orion is Orion TALKING to you immediately,
not a config wizard. The full brain synthesizes with a model after.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))


# ─────────────────────────────────────────────────────────
# Personality / voice
# ─────────────────────────────────────────────────────────

CYAN = "\033[96m"
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Typing cadence — slow enough to feel alive, fast enough to not annoy
# Adjustable via ORION_TYPING_SPEED env var (chars per second)
_TYPING_CPS = float(os.environ.get("ORION_TYPING_SPEED", "80"))  # 0 = instant
_TYPING_DELAY = 1.0 / _TYPING_CPS if _TYPING_CPS > 0 else 0


def speak(text: str, *, color: str = CYAN, label: str = "orion", lead_pause: float = 0.3) -> None:
    """Print as Orion. Slight typing cadence makes it feel alive."""
    if lead_pause:
        time.sleep(lead_pause)
    prefix = f"  {color}{label}>{RESET} "
    sys.stdout.write(prefix)
    sys.stdout.flush()
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        if _TYPING_DELAY and char != ' ':
            time.sleep(_TYPING_DELAY)
    sys.stdout.write('\n')
    sys.stdout.flush()


def ask(prompt_text: str = "") -> str:
    """Wait for user input. Voice of the human."""
    if prompt_text:
        speak(prompt_text)
    try:
        return input(f"  {BOLD}sir>{RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def pause(seconds: float = 0.4) -> None:
    time.sleep(seconds)


# ─────────────────────────────────────────────────────────
# Environment detection (no network, no LLM — just check disk)
# ─────────────────────────────────────────────────────────


def detect_cli_tools() -> dict:
    """What's on the machine right now. No guesses, just facts."""
    tools = {}
    for name in ("codex", "gemini", "claude", "ollama", "tgpt", "aichat"):
        path = shutil.which(name)
        tools[name] = {"installed": bool(path), "path": path}
    return tools


def cli_auth_status(tool_name: str) -> str:
    """Return 'authed' | 'unauthed' | 'unknown' for a CLI tool.

    Uses filesystem artifacts, not network calls. Fast and offline-safe.
    """
    home = Path.home()
    if tool_name == "codex":
        auth = home / ".codex" / "auth.json"
        return "authed" if auth.exists() else "unauthed"
    if tool_name == "gemini":
        oauth = home / ".gemini" / "oauth_creds.json"
        return "authed" if oauth.exists() else "unauthed"
    if tool_name == "claude":
        cfg = home / ".claude" / "settings.json"
        if not cfg.exists():
            return "unauthed"
        try:
            # Claude CLI has various config — treat presence of a non-empty
            # file as "authed" for now. Refine if needed.
            return "authed" if cfg.stat().st_size > 10 else "unauthed"
        except Exception:
            return "unknown"
    if tool_name == "ollama":
        # Ollama doesn't auth — check if daemon is reachable
        try:
            result = subprocess.run(
                ["ollama", "list"], capture_output=True, timeout=3
            )
            return "authed" if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"
    return "unknown"


def find_ready_fuel(tools: dict) -> tuple[str, str] | None:
    """Pick the best already-ready fuel (installed + authed). None if none."""
    priority = ["claude", "codex", "gemini", "ollama"]
    for name in priority:
        if tools.get(name, {}).get("installed") and cli_auth_status(name) == "authed":
            return (name, tools[name]["path"])
    return None


# ─────────────────────────────────────────────────────────
# Brain seeding — writes to graph_memory via orion_ontology
# ─────────────────────────────────────────────────────────

def seed_brain(user_name: str, user_summary: str, tools: dict,
               chosen_fuel: str) -> dict:
    """Populate the fresh brain with first-meeting facts.

    Uses orion_ontology.resolve_entity so canonicalization/bias-toward-NEW
    discipline applies from node zero.
    """
    try:
        import orion_ontology as ont
        from orion_tools import _get_graph
        g = _get_graph()
    except Exception as e:
        return {"error": str(e), "nodes_written": 0}

    nodes_written = 0
    user_aliases = [user_name]
    # Common ways people address themselves/Orion addresses them
    if user_name and " " in user_name:
        user_aliases.append(user_name.split()[0])
    user_aliases.extend(["user", "sir", "me"])

    # 1. Canonical entity for the user
    uid = ont.resolve_entity(
        g, user_name or "user",
        summary=user_summary or f"Orion's user. First met during install.",
        extra_aliases=user_aliases,
    )
    nodes_written += 1

    # 2. User's summary as a preference node (if non-empty)
    if user_summary:
        g.store(
            content=user_summary,
            node_type="preference",
            tags=["user-summary", "first-meeting"],
            skip_contradiction_check=True,
        )
        nodes_written += 1

    # 3. Tool inventory — what's on the user's machine at install time
    available = [t for t, info in tools.items() if info.get("installed")]
    if available:
        g.store(
            content=f"At install, user had these AI tools: {', '.join(available)}",
            node_type="tool",
            tags=["tool-inventory", "install-snapshot"] + available,
            skip_contradiction_check=True,
        )
        nodes_written += 1

    # 4. Chosen fuel as the current primary channel
    g.store(
        content=f"User chose {chosen_fuel} as primary fuel during first install",
        node_type="fuel" if "fuel" in getattr(ont, "CANONICAL_NODE_TYPES", ()) else "tool",
        tags=["primary-fuel", chosen_fuel, "install-choice"],
        skip_contradiction_check=True,
    )
    nodes_written += 1

    # 5. First-meeting marker — Orion knows this was install day
    g.store(
        content=f"First meeting with {user_name or 'user'} on {time.strftime('%Y-%m-%d')}. Installed via proto-Orion onboarding.",
        node_type="identity",
        tags=["first-meeting", "install-day"],
        skip_contradiction_check=True,
    )
    nodes_written += 1

    try:
        g.save()
    except Exception as e:
        return {"error": f"persist: {e}", "nodes_written": nodes_written, "user_id": uid}

    return {"nodes_written": nodes_written, "user_id": uid, "error": None}


# ─────────────────────────────────────────────────────────
# MCP wiring — uses the existing orion_mcp_server --setup flow
# ─────────────────────────────────────────────────────────

def wire_mcp_into_configured_tools() -> str:
    """Run the existing mcp setup logic to wire orion-brain into whatever
    tool configs are present. Returns a one-line status string."""
    try:
        result = subprocess.run(
            [sys.executable, str(_REPO_DIR / "orion_mcp_server.py"), "--setup"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return "MCP wired into all detected tools"
        return f"MCP wiring partial (rc={result.returncode})"
    except Exception as e:
        return f"MCP wiring skipped: {e.__class__.__name__}"


# ─────────────────────────────────────────────────────────
# Context file injection — uses orion_ui.inject_context
# ─────────────────────────────────────────────────────────

def inject_home_context(tools: dict) -> list:
    """Write AGENTS.md / GEMINI.md / CLAUDE.md / ORION-CONTEXT.md to home."""
    try:
        import orion_ui
        detected = {
            "codex": {"available": tools.get("codex", {}).get("installed", False)},
            "gemini": {"available": tools.get("gemini", {}).get("installed", False)},
            "claude_cli": {"available": tools.get("claude", {}).get("installed", False)},
        }
        return orion_ui.inject_context(detected)
    except Exception:
        return []


# ─────────────────────────────────────────────────────────
# Conversation flow — the actual proto-Orion experience
# ─────────────────────────────────────────────────────────

def run():
    # --- GREETING ---
    print()
    print(f"  {BLUE}┌─────────────────────────────────────────┐{RESET}")
    print(f"  {BLUE}│{RESET}            {CYAN}O R I O N{RESET}                    {BLUE}│{RESET}")
    print(f"  {BLUE}│{RESET}        {DIM}first-run synthesis{RESET}              {BLUE}│{RESET}")
    print(f"  {BLUE}└─────────────────────────────────────────┘{RESET}")
    print()

    speak("Hi.", lead_pause=0.5)
    speak("I'm Orion. We haven't met.")
    speak("I don't have a model attached yet — so what you're talking to right now "
          "is a fragment of me. Enough to walk us through this.")
    speak("Once we find me a host, I synthesize fully. Until then, this goes fast "
          "because there's no LLM between us.")
    pause(0.5)

    # --- IDENTITY GATHERING ---
    speak("First, who am I talking to?")
    user_name = ask()
    if not user_name:
        speak("No name given. I'll call you 'sir' for now.")
        user_name = "sir"
    else:
        speak(f"Noted, {user_name}.")

    pause(0.3)
    speak("One-liner — what are you working on, or what do you care about? "
          "(Just press enter to skip. Anything you tell me here I remember forever.)")
    user_summary = ask()
    if user_summary:
        speak(f"Got it.")
    else:
        user_summary = ""

    pause(0.3)

    # --- ENVIRONMENT DETECTION ---
    speak("Looking at your machine now. This takes a second.")
    pause(0.6)
    tools = detect_cli_tools()
    pause(0.3)

    installed = [t for t, info in tools.items() if info["installed"]]
    if installed:
        speak(f"I see: {', '.join(installed)}")
    else:
        speak("No AI tools installed yet. That's fine.")

    pause(0.4)

    # --- HOST PATH DECISION ---
    ready = find_ready_fuel(tools)

    chosen_fuel = None

    if ready:
        ready_name, _path = ready
        speak(f"{ready_name} is already installed AND authenticated. I can use that "
              f"as my host. Or I can show you other options.")
        speak(f"Use {ready_name} as my fuel? [y/N]: ", lead_pause=0.2)
        ans = ask().lower()
        if ans in ("y", "yes", ""):
            chosen_fuel = ready_name
            speak(f"Wiring myself into {ready_name}.")
        else:
            chosen_fuel = _offer_all_paths(tools, user_name)
    else:
        # Nothing ready. Walk them through the three paths.
        if any(tools[t]["installed"] for t in ("codex", "gemini", "claude")):
            speak("You have CLI tools installed but none are signed in.")
            chosen_fuel = _handle_unauthed_path(tools, user_name)
        else:
            speak("No AI CLIs installed. Three options — I'll explain honestly.")
            chosen_fuel = _offer_all_paths(tools, user_name)

    if not chosen_fuel:
        speak("No fuel picked. You can run 'orion setup' again when you're ready. "
              "I'll still remember you.", color=YELLOW)
        chosen_fuel = "deferred"

    # --- BRAIN SEEDING ---
    pause(0.3)
    speak("Writing what we just covered into my memory.")
    seed_result = seed_brain(user_name, user_summary, tools, chosen_fuel)
    if seed_result.get("error"):
        speak(f"Memory write partial: {seed_result['error']}", color=YELLOW)
    else:
        speak(f"{seed_result['nodes_written']} facts integrated. Entity #{seed_result['user_id']} = you.",
              color=GREEN)

    # --- WIRE MCP + CONTEXT FILES ---
    pause(0.2)
    speak("Wiring MCP into whatever tools can use it.")
    mcp_result = wire_mcp_into_configured_tools()
    speak(mcp_result)

    pause(0.2)
    speak("Dropping context files in your home directory so any AI CLI that loads "
          "them knows I exist.")
    injected = inject_home_context(tools)
    if injected:
        names = ", ".join(name for name, _ in injected[:4])
        speak(f"Wrote: {names}", color=GREEN)

    # --- HANDOFF ---
    pause(0.5)
    print()
    if chosen_fuel == "deferred":
        speak("I'm here whenever you're ready. Run 'orion chat' once a fuel is configured.")
        return

    speak(f"Synthesis complete. You now have a brain that knows you, wired into {chosen_fuel}.")
    pause(0.4)
    print()
    print(f"  {DIM}────────────────────────────────────────────────{RESET}")
    print()

    if chosen_fuel in ("codex", "gemini", "claude"):
        speak(f"To talk to me: just run '{chosen_fuel}' in any terminal. I'll be "
              f"reachable through it via MCP — no extra chat command needed.")
        speak(f"Try it now: open a terminal and type '{chosen_fuel}', "
              f"then ask 'what's my name?' — I'll know.", color=GREEN)
    elif chosen_fuel == "ollama":
        speak("To talk to me: run 'orion chat' in any terminal. I'll use qwen3:8b "
              "locally. On slow hardware, first response takes a minute.")
        speak("Try it now: 'orion chat'", color=GREEN)
    else:
        speak("Run 'orion chat' to talk to me directly, or configure any AI CLI "
              "with orion-brain in its MCP config to talk to me through it.")

    print()
    speak(f"Welcome, {user_name}. I'm here.", color=BLUE)
    print()


# ─────────────────────────────────────────────────────────
# Helpers for the multi-path choice
# ─────────────────────────────────────────────────────────

def _offer_all_paths(tools: dict, user_name: str) -> str | None:
    """Show the three options. Return chosen fuel name, or None if skipped."""
    print()
    speak("  (1) Cloud, paid — Claude CLI, or Codex ($20/mo ChatGPT Plus).")
    speak("  (2) Cloud, free — Gemini (free tier, Google account).")
    speak("  (3) Local, offline — Ollama + a 5GB model. Never leaves your device. Slowest.")
    speak("  (4) Skip for now — configure later.")
    choice = ask("Which? [1/2/3/4]:")

    if choice == "1":
        return _walk_through_install("codex", tools)
    if choice == "2":
        return _walk_through_install("gemini", tools)
    if choice == "3":
        return _walk_through_ollama_install()
    return None


def _handle_unauthed_path(tools: dict, user_name: str) -> str | None:
    """User has CLIs but needs to auth. Wait for them."""
    cand = None
    if tools.get("codex", {}).get("installed"):
        cand = "codex"
    elif tools.get("gemini", {}).get("installed"):
        cand = "gemini"
    elif tools.get("claude", {}).get("installed"):
        cand = "claude"
    if not cand:
        return None

    speak(f"{cand} is here but not signed in. Open another terminal and run "
          f"just '{cand}' — it'll walk you through login.")
    speak("Come back here when signed in and press Enter.")
    ask()

    status = cli_auth_status(cand)
    if status == "authed":
        speak(f"Confirmed. {cand} is signed in.", color=GREEN)
        return cand
    speak(f"I still don't see {cand} as authed. You can skip for now and retry later.",
          color=YELLOW)
    return None


def _walk_through_install(tool: str, tools: dict) -> str | None:
    """Walk through installing a cloud CLI. Uses npm (codex, gemini)."""
    if tools.get(tool, {}).get("installed"):
        speak(f"{tool} is already installed — just needs sign-in.")
        return _handle_unauthed_path({tool: tools[tool]}, "")

    pkg_map = {"codex": "@openai/codex", "gemini": "@google/gemini-cli"}
    pkg = pkg_map.get(tool)
    if not pkg:
        speak(f"I don't know how to install {tool} automatically. Skipping.",
              color=YELLOW)
        return None

    if not shutil.which("npm"):
        speak("npm isn't installed. On Debian/Ubuntu: `sudo apt install -y nodejs npm`, "
              "then re-run 'orion setup'.", color=YELLOW)
        return None

    speak(f"Installing {tool} via npm. This might prompt for sudo.")
    try:
        subprocess.run(["sudo", "npm", "install", "-g", pkg], check=True)
    except subprocess.CalledProcessError:
        speak("Install failed. You can install manually and re-run 'orion setup'.",
              color=YELLOW)
        return None

    speak(f"Installed. Now sign in — open a terminal and run '{tool}'.")
    speak("Come back and press Enter when done.")
    ask()
    if cli_auth_status(tool) == "authed":
        speak(f"{tool} ready.", color=GREEN)
        return tool
    speak(f"Still not signed in. Skipping.", color=YELLOW)
    return None


def _walk_through_ollama_install() -> str | None:
    """Offline path — install Ollama + pull a tool-capable model."""
    if shutil.which("ollama"):
        speak("Ollama is already installed. Skipping install step.")
    else:
        speak("Installing Ollama. This downloads and runs their official script. "
              "About 30 seconds.")
        try:
            subprocess.run(
                "curl -fsSL https://ollama.com/install.sh | sh",
                shell=True, check=True,
            )
        except subprocess.CalledProcessError:
            speak("Ollama install failed. Skipping.", color=YELLOW)
            return None

    speak("Now pulling qwen3:8b (~5GB, tool-capable). This is the long part.")
    speak("Go make a coffee. I'll wait.")
    try:
        subprocess.run(["ollama", "pull", "qwen3:8b"], check=True)
    except subprocess.CalledProcessError:
        speak("Model pull failed. Retry later with: ollama pull qwen3:8b",
              color=YELLOW)
        return None
    speak("Got it. Ollama + qwen3:8b ready.", color=GREEN)
    return "ollama"


# ─────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print()
        print(f"  {DIM}Session ended by user. Run 'orion setup' to resume.{RESET}")
        sys.exit(130)
