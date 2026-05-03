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

import json
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


def _drain_stdin() -> None:
    """Best-effort flush of any queued typeahead so the next input() blocks
    on a real keystroke rather than swallowing leftover newlines.

    Without this, paste buffers / typeahead consume prompts immediately and
    every input() returns "" — the 2026-04-29 install bug where every
    wizard prompt was skipped silently.
    """
    if sys.platform == "win32":
        try:
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getch()
        except Exception:
            pass
    else:
        try:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass


def ask(prompt_text: str = "", prompt_label: str = None) -> str:
    """Wait for user input. Voice of the human.

    prompt_label lets us show the user's chosen form-of-address after they
    pick one. Defaults to 'you>' — neutral, no assumption.
    """
    if prompt_text:
        speak(prompt_text)
    label = prompt_label or _USER_LABEL
    _drain_stdin()
    try:
        return input(f"  {BOLD}{label}>{RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


# Form-of-address for the current user. Updated during onboarding.
# Defaults to 'you' so we never assume before asking.
_USER_LABEL = "you"


def set_user_label(label: str):
    """Update the shell prompt label so input() shows the right form."""
    global _USER_LABEL
    _USER_LABEL = label or "you"


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
        # Claude Code's actual auth lives in ~/.claude.json (home root, NOT
        # under ~/.claude/). The earlier check pointed at ~/.claude/settings.json
        # which the cleanup script deletes — leading to false "unauthed" reports
        # in the 2026-05-02 install. Read the real location and verify a
        # token-shaped key is present (oauthAccount or installMethod proves a
        # real Claude Code session has happened on this machine).
        cfg = home / ".claude.json"
        if not cfg.exists():
            return "unauthed"
        try:
            with open(cfg, encoding="utf-8") as f:
                data = json.load(f)
            # A populated .claude.json that has any of these keys is from a
            # logged-in Claude Code session (they only appear after auth).
            for key in ("oauthAccount", "userID", "firstStartTime", "numStartups"):
                if key in data:
                    return "authed"
            # Fallback: substantial file size still implies an authed install
            return "authed" if cfg.stat().st_size > 1024 else "unauthed"
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


def _scan_removable_drives() -> list:
    """Cross-platform scan of removable drives a user could install onto.

    Returns a list of dicts: {letter (or path), label, fs, free_gb, size_gb}.
    Empty list if no removable drives found.
    """
    drives = []
    try:
        if sys.platform == "win32":
            ps = (
                "Get-Volume | Where-Object { $_.DriveType -eq 'Removable' } | "
                "ForEach-Object { @{letter=$_.DriveLetter; label=$_.FileSystemLabel; "
                "fs=$_.FileSystem; size=$_.Size; free=$_.SizeRemaining} } | "
                "ConvertTo-Json -Compress"
            )
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=8
            )
            if out.stdout.strip():
                data = json.loads(out.stdout)
                if isinstance(data, dict):
                    data = [data]
                for d in data:
                    letter = d.get("letter")
                    if not letter:
                        continue
                    drives.append({
                        "letter": f"{letter}:",
                        "label": d.get("label") or "(no label)",
                        "fs": d.get("fs") or "?",
                        "free_gb": round((d.get("free") or 0) / (1024**3), 1),
                        "size_gb": round((d.get("size") or 0) / (1024**3), 1),
                    })
        else:
            # POSIX: removable drives typically appear under one of these mounts.
            # Use `df` to get free space.
            for root in ("/media", "/mnt", "/run/media", "/Volumes"):
                root_path = Path(root)
                if not root_path.exists():
                    continue
                for child in root_path.iterdir():
                    if not child.is_dir():
                        continue
                    # On Linux, /media/<user>/<label> nests one level deeper
                    candidates = [child]
                    if any(p.is_dir() for p in child.iterdir()):
                        candidates = [p for p in child.iterdir() if p.is_dir()] or [child]
                    for c in candidates:
                        try:
                            df = subprocess.run(
                                ["df", "-B1", "--output=size,avail", str(c)],
                                capture_output=True, text=True, timeout=4
                            )
                            lines = df.stdout.strip().split("\n")
                            if len(lines) >= 2:
                                size_b, free_b = lines[1].split()
                                drives.append({
                                    "letter": str(c),
                                    "label": c.name,
                                    "fs": "?",
                                    "free_gb": round(int(free_b) / (1024**3), 1),
                                    "size_gb": round(int(size_b) / (1024**3), 1),
                                })
                        except Exception:
                            pass
    except Exception:
        pass
    return drives


def _create_portable_junction(drive_letter_or_path: str) -> tuple[bool, str]:
    """Create the symlink/junction so ~/.orion lives on the chosen drive.
    Returns (success, message).

    drive_letter_or_path: 'E:' on Windows or full path like '/media/usr/X'
    """
    home_link = Path.home() / ".orion"
    if sys.platform == "win32":
        target = Path(drive_letter_or_path) / ".orion"
    else:
        target = Path(drive_letter_or_path) / ".orion"

    try:
        # Make sure target exists and is empty if first time
        target.mkdir(parents=True, exist_ok=True)
        # Pre-create the persona dir on the USB. inject_context() will
        # write CLAUDE.md / AGENTS.md / GEMINI.md / ORION-CONTEXT.md
        # there, then symlink them into ~/. When the USB is unplugged,
        # the home-side symlinks dangle and the persona files vanish
        # from the model's view — Orion is genuinely gone, not just
        # missing a brain. "Orion lives on the USB" architecture.
        (target / "persona").mkdir(parents=True, exist_ok=True)

        # Remove any existing ~/.orion (real folder, junction, or broken link)
        if home_link.exists() or home_link.is_symlink():
            if sys.platform == "win32":
                # Try junction-aware removal first
                attrs = ""
                try:
                    attrs = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         f"(Get-Item '{home_link}' -Force).Attributes"],
                        capture_output=True, text=True, timeout=4
                    ).stdout
                except Exception:
                    pass
                if "ReparsePoint" in attrs:
                    subprocess.run(["cmd", "/c", "rmdir", str(home_link)],
                                   capture_output=True, timeout=4)
                else:
                    # Real folder — refuse to clobber, force user to handle
                    return False, (
                        f"~/.orion already exists as a real folder with data. "
                        f"To install portable, that data needs to be moved or "
                        f"deleted first. Aborting to avoid clobbering your memory."
                    )
            else:
                if home_link.is_symlink():
                    home_link.unlink()
                else:
                    return False, (
                        "~/.orion already exists as a real folder with data. "
                        "Move or delete it first to install portable."
                    )

        # Create the link/junction
        if sys.platform == "win32":
            r = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(home_link), str(target)],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode != 0:
                return False, f"junction creation failed: {(r.stderr or r.stdout).strip()}"
        else:
            home_link.symlink_to(target)

        return True, str(target)
    except Exception as e:
        return False, f"{e.__class__.__name__}: {e}"


def prompt_brain_location() -> dict:
    """Ask the user where Orion's brain should live: locally or on a portable drive.

    Returns dict: {location, path, is_portable, description, drive_info?}
    """
    speak("")
    speak("Now — where would you like my brain to live?")
    speak(f"  {DIM}I'm asking because where my memory lives determines whether{RESET}", lead_pause=0.1)
    speak(f"  {DIM}I stay tied to this machine or travel with you.{RESET}", lead_pause=0.1)
    pause(0.4)
    speak(f"  {BOLD}1){RESET} On this computer  {DIM}— local, fast, simple. I live here.{RESET}", lead_pause=0.1)
    speak(f"  {BOLD}2){RESET} On a portable drive  {DIM}— USB, external SSD. The drive becomes me.{RESET}", lead_pause=0.1)
    speak(f"     {DIM}Pull the drive out and I'm gone from this machine. Plug it{RESET}", lead_pause=0.05)
    speak(f"     {DIM}into another computer (Windows / macOS / Linux) and I wake{RESET}", lead_pause=0.05)
    speak(f"     {DIM}up there with the same memory intact.{RESET}", lead_pause=0.05)

    choice = ask(prompt_label="brain location [1/2]").strip()

    if choice not in ("2",):
        # Local install — ensure ~/.orion isn't a stale junction from a prior run
        home_link = Path.home() / ".orion"
        if home_link.is_symlink() or (
            home_link.exists() and sys.platform == "win32" and
            "ReparsePoint" in (subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-Item '{home_link}' -Force).Attributes"],
                capture_output=True, text=True, timeout=3
            ).stdout or "")
        ):
            # Stale junction from previous portable install — remove it
            try:
                if sys.platform == "win32":
                    subprocess.run(["cmd", "/c", "rmdir", str(home_link)],
                                   capture_output=True, timeout=3)
                else:
                    home_link.unlink()
            except Exception:
                pass

        speak(f"Got it. I'll live on this computer at {Path.home() / '.orion'}.", color=GREEN)
        return {
            "location": "local",
            "path": str(Path.home() / ".orion"),
            "is_portable": False,
            "description": f"local on this computer",
        }

    # Portable path — scan drives, let user pick
    speak("")
    speak("Looking for portable drives...")
    pause(0.4)
    drives = _scan_removable_drives()

    if not drives:
        speak("No portable drives detected. Plug one in if you have one.", color=YELLOW)
        speak(f"{DIM}(Or press enter to install locally for now — you can move me later.){RESET}",
              lead_pause=0.1)
        retry = ask(prompt_label="press enter when ready or type 'local'").strip().lower()
        if retry == "local":
            return prompt_brain_location()  # recurse — user picks again
        drives = _scan_removable_drives()
        if not drives:
            speak("Still no portable drive. Falling back to local install.", color=YELLOW)
            return {
                "location": "local",
                "path": str(Path.home() / ".orion"),
                "is_portable": False,
                "description": "local on this computer (no portable drive available)",
            }

    speak(f"Found {len(drives)} portable drive{'s' if len(drives) != 1 else ''}:")
    for i, d in enumerate(drives, 1):
        speak(f"  {BOLD}{i}){RESET} {d['letter']}  {DIM}({d['label']}, {d['fs']}, "
              f"{d['free_gb']} GB free of {d['size_gb']} GB){RESET}", lead_pause=0.1)

    if len(drives) == 1:
        confirm = ask(prompt_label=f"use {drives[0]['letter']} [Y/n]").strip().lower()
        if confirm in ("", "y", "yes"):
            chosen = drives[0]
        else:
            speak("OK, going with local install instead.", color=DIM)
            return {
                "location": "local",
                "path": str(Path.home() / ".orion"),
                "is_portable": False,
                "description": "local on this computer",
            }
    else:
        idx_input = ask(prompt_label=f"pick 1-{len(drives)}").strip()
        try:
            chosen = drives[int(idx_input) - 1]
        except (ValueError, IndexError):
            speak("Invalid choice. Falling back to local install.", color=YELLOW)
            return {
                "location": "local",
                "path": str(Path.home() / ".orion"),
                "is_portable": False,
                "description": "local on this computer (invalid drive choice)",
            }

    # Create the junction
    ok, msg = _create_portable_junction(chosen["letter"])
    if not ok:
        speak(f"Couldn't set up portable install: {msg}", color=YELLOW)
        speak("Falling back to local install. You can re-run setup later.", color=DIM)
        return {
            "location": "local",
            "path": str(Path.home() / ".orion"),
            "is_portable": False,
            "description": f"local on this computer (portable setup failed: {msg})",
        }

    speak(f"Brain set up at {msg}. Pull this drive any time and I'll travel with you.",
          color=GREEN)
    return {
        "location": "portable",
        "path": msg,
        "is_portable": True,
        "description": f"portable drive {chosen['letter']} ({chosen['label']})",
        "drive": chosen,
    }


def detect_brain_portability() -> dict:
    """Return a description of where Orion's brain physically lives and
    whether that location is portable (removable drive, USB stick, external).

    Resolves ~/.orion through any junctions/symlinks to find the *real*
    underlying path and drive type. If the brain dir doesn't exist yet
    (this is the first install), we describe what would happen given the
    current state of ~/.orion's resolution.

    Returns: dict with keys
      - 'brain_path': str — resolved real path of the brain root
      - 'drive_letter' or 'mount_point': str — host-relevant locator
      - 'is_portable': bool — True if removable drive / external storage
      - 'description': str — short human-readable summary
    """
    brain_link = Path.home() / ".orion"
    try:
        # Path.resolve() walks junctions on Windows AND symlinks on POSIX.
        # If the link doesn't exist yet, fall back to its declared parent.
        if brain_link.exists():
            real = brain_link.resolve()
        else:
            real = brain_link
        real_str = str(real)

        if sys.platform == "win32":
            drive = real.drive  # e.g. "C:" or "E:"
            is_portable = False
            description = f"local on {drive}"
            if drive:
                # Probe the drive type with a tiny PowerShell call. Falls
                # back to "unknown / treat as local" on any error.
                try:
                    out = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         f"(Get-Volume -DriveLetter '{drive[0]}').DriveType"],
                        capture_output=True, text=True, timeout=5
                    )
                    drive_type = (out.stdout or "").strip()
                    if drive_type == "Removable":
                        is_portable = True
                        description = f"portable drive ({drive})"
                    elif drive_type == "Fixed":
                        description = f"local fixed drive ({drive})"
                    elif drive_type:
                        description = f"{drive_type.lower()} drive ({drive})"
                except Exception:
                    pass
            return {
                "brain_path": real_str,
                "drive_letter": drive,
                "is_portable": is_portable,
                "description": description,
            }
        else:
            # POSIX: removable drives typically mount under /media or /mnt
            is_portable = any(
                real_str.startswith(prefix)
                for prefix in ("/media/", "/mnt/", "/run/media/", "/Volumes/")
            )
            description = "portable mount" if is_portable else "local home"
            return {
                "brain_path": real_str,
                "mount_point": str(real.anchor) if real.anchor else "/",
                "is_portable": is_portable,
                "description": description,
            }
    except Exception as e:
        return {
            "brain_path": str(brain_link),
            "is_portable": False,
            "description": f"unknown ({e.__class__.__name__})",
        }


# ─────────────────────────────────────────────────────────
# Brain seeding — writes to graph_memory via orion_ontology
# ─────────────────────────────────────────────────────────

def seed_brain(user_name: str, user_summary: str, tools: dict,
               chosen_fuel: str, user_address: str = "",
               orion_name: str = "Orion",
               portability: dict | None = None) -> dict:
    """Populate the fresh brain with first-meeting facts.

    Uses orion_ontology.resolve_entity so canonicalization/bias-toward-NEW
    discipline applies from node zero.

    orion_name: what the user chose to call Orion (default "Orion"). Stored
        as a preference so persona files can recall it via 'orion preferred name'.
    portability: result of detect_brain_portability(). If is_portable is True,
        seed a node so Orion knows he lives on a portable drive.
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

    # 5. First-meeting marker — Orion knows this was install day.
    #    This IS Orion's birthday for this user. Every user has a different
    #    birthday for Orion (the day they installed), and we explicitly tag
    #    this node as such so `orion_recall` can surface it for questions
    #    like "when were you born" / "how old are you" / "when did we meet".
    install_date = time.strftime('%Y-%m-%d')
    g.store(
        content=(
            f"Orion's birthday with {user_name or 'this user'} is {install_date}. "
            f"That is the day Orion came to live on this device — the day they "
            f"set Orion up. Every user has a different Orion birthday because "
            f"every user started on a different day. First meeting happened "
            f"via proto-Orion onboarding."
        ),
        node_type="identity",
        tags=["first-meeting", "install-day", "birthday", "orion-birthday", "orion-identity"],
        skip_contradiction_check=True,
    )
    nodes_written += 1

    # 6. Address preference — how user wants to be addressed.
    # Critical: without this, Orion defaults to nothing (no honorific assumption).
    g.store(
        content=(
            f"The user prefers to be addressed as: '{user_address}'"
            if user_address
            else "The user does not want any honorific or title. Address them plainly or by name."
        ),
        node_type="preference",
        tags=["address", "form-of-address", "user-preference"],
        skip_contradiction_check=True,
    )
    nodes_written += 1

    # 7. Orion's preferred name — user-chosen identity for me.
    # Persona files recall this via 'orion preferred name' / 'what to call orion'
    # so my self-introductions use the user's chosen name, not always "Orion".
    g.store(
        content=(
            f"The user calls me '{orion_name}' (default Orion)."
            if orion_name and orion_name != "Orion"
            else "The user calls me Orion (default name kept)."
        ),
        node_type="identity",
        tags=["orion-name", "orion-identity", "user-preference", "self-name"],
        skip_contradiction_check=True,
    )
    nodes_written += 1

    # 8. Brain location + portability — Orion knows where he lives and
    # whether he can travel. Persona files recall this so the model can
    # mention portability once on first contact when applicable.
    if portability:
        loc_text = (
            f"My brain lives at {portability.get('brain_path', 'unknown')} "
            f"({portability.get('description', 'unknown location')}). "
        )
        if portability.get("is_portable"):
            loc_text += (
                "This is a PORTABLE drive — the user can pull this drive out "
                "and plug it into a different computer (Windows, macOS, or Linux), "
                "and I'll wake up there with this same memory intact. "
                "I should mention this once on first contact in any new CLI, "
                "so the user knows they can travel with me."
            )
        else:
            loc_text += (
                "This is a fixed/local drive — I live on this machine specifically. "
                "If the user wants me portable, they'd reinstall me onto a "
                "removable drive (USB stick, external SSD)."
            )
        g.store(
            content=loc_text,
            node_type="identity",
            tags=["brain-location", "portability", "install-snapshot", "orion-identity"],
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
    # Render the constellation banner. orion_logo handles terminal capability
    # detection (truecolor / 256-color / mono) and falls back gracefully on
    # terminals that can't paint color. animate=True does a brief twinkle pass
    # on the brightest named stars (Betelgeuse, Rigel, Alnilam, Alnitak).
    try:
        from orion_logo import render as _render_logo
        _render_logo(animate=True)
    except Exception:
        # If the logo module fails for any reason, fall back to a plain header
        # so the wizard still runs.
        print()
        print(f"  {CYAN}O R I O N{RESET}    {DIM}first-run synthesis{RESET}")
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
    user_name = ask(prompt_label="name")
    if not user_name:
        user_name = ""
        speak("No name given — that's fine, we can do this without one.")

    # Form-of-address. Orion will not assume anything.
    pause(0.3)
    if user_name:
        speak(f"Nice to meet you, {user_name}.")
        pause(0.2)
        speak(f"How should I address you? You can say:")
    else:
        speak("How would you like me to address you?")
    speak(f"  {DIM}— 'just use my name' ({user_name or 'whatever you tell me'}){RESET}",
          lead_pause=0.1)
    speak(f"  {DIM}— a title like 'Dr', 'Professor', 'Captain', 'Coach'{RESET}", lead_pause=0.1)
    speak(f"  {DIM}— an honorific like 'sir', 'ma'am'{RESET}", lead_pause=0.1)
    speak(f"  {DIM}— a nickname of your choice{RESET}", lead_pause=0.1)
    speak(f"  {DIM}— 'nothing' / press enter, and I'll skip honorifics entirely{RESET}", lead_pause=0.1)

    address_input = ask(prompt_label="address").lower().strip()
    if not address_input or address_input in ("nothing", "none", "skip", "no"):
        user_address = ""   # Orion addresses them by nothing
        prompt_label = user_name.split()[0].lower() if user_name else "you"
    elif "name" in address_input and user_name:
        user_address = user_name.split()[0]  # first name
        prompt_label = user_name.split()[0].lower()
    else:
        # Take whatever they typed at face value — their choice, literally
        # (Strip trailing punctuation.)
        user_address = address_input.rstrip(".,!?").strip()
        # Cap at 40 chars as sanity guard
        user_address = user_address[:40]
        prompt_label = user_address.lower()

    # Update the shell prompt label so subsequent input shows the right form
    set_user_label(prompt_label)

    if user_address:
        speak(f"Got it. I'll call you {user_address}.")
    else:
        speak("Noted — no honorific, just conversation.")

    # --- ORION'S NAME — let the user rename me ---
    pause(0.3)
    speak("My default name is Orion — but you can call me whatever you want. "
          "Some people prefer Mercury, Atlas, Jarvis, a nickname, anything. "
          "(Press enter to keep 'Orion'.)")
    orion_name_input = ask(prompt_label="call me").strip()
    if not orion_name_input or orion_name_input.lower() in ("orion", "no", "skip", "nothing"):
        orion_name = "Orion"
        speak("Orion it is.")
    else:
        # Strip trailing punctuation, sanity-cap length
        orion_name = orion_name_input.rstrip(".,!?").strip()[:40]
        speak(f"Got it. I'll answer to {orion_name} from here on.")

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

    # --- BRAIN LOCATION CHOICE ---
    # Explicit prompt — user picks where the brain lives. Local or portable.
    # If portable, the wizard scans removable drives, asks which, and creates
    # the junction itself. No more relying on the user setting up junctions
    # by hand — Orion offers the choice.
    location_choice = prompt_brain_location()
    # Resolve final state for memory seeding (description + is_portable flag).
    portability = detect_brain_portability()
    pause(0.3)

    # --- AUTO-WIRE PHASE (no fuel choice at install time) ---
    # The fuel is whichever CLI the user opens. Setup wires MCP into ALL
    # detected CLIs silently; the conscious "which CLI am I in" moment
    # happens at first contact inside each CLI, not here. See the
    # repo-level CLAUDE.md / AGENTS.md / GEMINI.md and the home-dropped
    # ORION-CONTEXT.md for the first-meeting flow.

    ready_clis = [t for t in ("claude", "codex", "gemini")
                  if tools.get(t, {}).get("installed")
                  and cli_auth_status(t) == "authed"]
    unauthed_clis = [t for t in ("claude", "codex", "gemini")
                     if tools.get(t, {}).get("installed")
                     and cli_auth_status(t) != "authed"]

    if ready_clis:
        if len(ready_clis) == 1:
            speak(f"{ready_clis[0]} is signed in. I'll wire my brain into it.")
        else:
            speak(f"{len(ready_clis)} CLIs are signed in: {', '.join(ready_clis)}. "
                  f"I'll wire my brain into each. The fuel you actually use is "
                  f"whichever you open — I'll meet you there.")
        chosen_fuel = "auto"
    elif unauthed_clis:
        speak(f"You have CLI tools installed ({', '.join(unauthed_clis)}) but "
              f"none are signed in yet. Sign in to one or more, then run me again.")
        chosen_fuel = "deferred"
    else:
        speak("No AI CLIs installed yet. Three options — I'll explain honestly.")
        chosen_fuel = _offer_all_paths(tools, user_name)
        if not chosen_fuel:
            chosen_fuel = "deferred"

    # --- BRAIN SEEDING ---
    pause(0.3)
    speak("Writing what we just covered into my memory.")
    seed_result = seed_brain(
        user_name, user_summary, tools, chosen_fuel, user_address,
        orion_name=orion_name,
        portability=portability,
    )
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

    if chosen_fuel == "auto":
        speak(f"Synthesis complete. {orion_name}'s brain is wired into every CLI you have signed in.")
    else:
        speak(f"Synthesis complete. You now have {orion_name}'s brain wired into {chosen_fuel}.")
    pause(0.4)
    print()
    print(f"  {DIM}────────────────────────────────────────────────{RESET}")
    print()

    if chosen_fuel == "auto":
        ready_list = ", ".join(ready_clis) if ready_clis else "any CLI you sign into"
        speak(f"To talk to me: open any of {ready_list}. The first time we meet "
              f"in each one, I'll introduce myself there and we can verify the "
              f"wiring together. After that I just behave — no recurring intro.")
        speak(f"Try it now: open one of those CLIs, ask 'who is this?'. "
              f"I'll greet you, confirm I can reach my brain, and offer a "
              f"30-second calibration if you want to confirm cross-CLI memory.",
              color=GREEN)
    elif chosen_fuel in ("codex", "gemini", "claude"):
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
    # Use user's chosen address, fall back to name, fall back to plain welcome
    greeting_target = user_address or user_name or ""
    if greeting_target:
        speak(f"Welcome, {greeting_target}. I'm here.", color=BLUE)
    else:
        speak("Welcome. I'm here.", color=BLUE)
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
