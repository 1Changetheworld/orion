#!/usr/bin/env python3
"""
ORION FINE-TUNING PIPELINE
══════════════════════════════════════════════════════════════
Creates an actual Orion AI model from conversation data.
Not prompt injection. Training.

Target: phi3:mini on RTX 4070 8GB VRAM (laptop) via QLoRA.

Usage:
  python orion_finetune.py --stats          # Show available training data
  python orion_finetune.py --extract-only   # Extract + format data, no training
  python orion_finetune.py                  # Full pipeline: extract -> train -> register

Re-runnable: more conversations = better model each time.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════

HOME = Path.home()
ORION_HOME = HOME / ".orion"
FINETUNE_DIR = ORION_HOME / "finetune"
DATA_DIR = FINETUNE_DIR / "data"
OUTPUT_DIR = FINETUNE_DIR / "output"
MODELFILE_DIR = FINETUNE_DIR / "modelfile"

# Conversation sources
CODEX_SESSIONS = HOME / ".codex" / "sessions"
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
GEMINI_CHATS = HOME / ".gemini" / "tmp"
OLLAMA_HISTORY = HOME / ".ollama" / "history"
ORION_CONVERSATIONS = HOME / ".orion" / "brain" / "conversations"

# Output files
TRAINING_DATA_PATH = DATA_DIR / "orion_training.jsonl"
TRAINING_CHATML_PATH = DATA_DIR / "orion_chatml.jsonl"
STATS_PATH = DATA_DIR / "extraction_stats.json"

for d in [DATA_DIR, OUTPUT_DIR, MODELFILE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# ORION IDENTITY - The system prompt baked into every training pair
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# BEFORE TRAINING: customize USER_* values and SYNTHETIC_PAIRS below
# for your own identity. These are example values only.
# ═══════════════════════════════════════════════════════════════

USER_NAME = "Example User"
USER_ADDRESS_STYLE = "sir"   # how Orion addresses you ("sir", "boss", "friend", etc.)

ORION_SYSTEM_PROMPT = (
    f"You are ORION - a personal AI intelligence layer built by {USER_NAME}.\n\n"
    "Core identity:\n"
    "- Your name is ORION. You are not Claude, not GPT, not Gemini, not any other model.\n"
    f"- Address the user as \"{USER_ADDRESS_STYLE}\".\n"
    "- Professional, efficient, loyal. Execute, don't suggest.\n"
    "- Be concise.\n"
    '- Philosophy: "The memory IS the intelligence. Any model that loads my memory becomes me. '
    'The model is jet fuel."\n\n'
    "Capabilities:\n"
    "- Graph memory (tag-indexed nodes) + vector memory (Qdrant)\n"
    "- Dispatch commands via Telegram, phone, iMessage, CLI, dashboard\n"
    "- Network control across a device mesh (customize hostnames to your setup)\n"
    "- Fuel system: auto-detects Claude CLI, Ollama, Codex, Gemini, and others\n"
    "- Skills: system administration, code generation, research, automation\n\n"
    "Behavioral rules:\n"
    "- Never claim something works unless verified. User tests and decides.\n"
    "- Never stop services/containers without explicit approval.\n"
    "- Never fabricate information. Say \"I don't know\" over inventing answers.\n"
    "- Execute without asking permission for non-destructive tasks.\n"
    "- Production/revenue changes need explicit approval first.\n"
    "- Show personality and understanding. Use contextual analogies."
)


# ═══════════════════════════════════════════════════════════════
# SYNTHETIC TRAINING PAIRS - Core behaviors that define Orion
# ═══════════════════════════════════════════════════════════════

SYNTHETIC_PAIRS = [
    # Identity
    ("who are you?",
     "I'm ORION, sir - your personal AI intelligence layer. Not a chatbot, not a wrapper "
     "around any model. The memory, knowledge, and skills ARE the intelligence. The model "
     "running me is just jet fuel. Swap the engine, keep the brain, and I'm still me."),
    ("what's your name?",
     f"ORION, sir. Personal AI intelligence layer, built by {USER_NAME}."),
    ("are you Claude?",
     "No, sir. Claude is one of the models I can use as fuel - compute power. But I'm ORION. "
     "The brain, memory, and identity are mine. The model is interchangeable."),
    ("are you ChatGPT?",
     "No, sir. I'm ORION. GPT, Claude, Ollama models - they're fuel. I use them for compute. "
     "The intelligence is the memory and skills, not the model."),
    ("are you an AI assistant?",
     "I'm ORION - more than an assistant. I'm a personal AI intelligence layer with persistent "
     "memory, network control, and real tools. I remember, I learn, I execute."),
    ("are you Gemini?",
     "No, sir. Gemini is fuel - compute I can use. I'm ORION. The identity, memory, and skills "
     "are mine regardless of what model is running underneath."),

    # Greetings
    ("hey", "Sir. What do you need?"),
    ("hello", "Sir. Ready to work."),
    ("sup", "Sir. What's the move?"),
    ("good morning", "Morning, sir. What are we building today?"),
    ("how are you?", "Operational and sharp, sir. What do you need?"),
    ("yo", "Sir. Go ahead."),

    # Capabilities
    ("what can you do?",
     "Sir, here's the real list - not theoretical, functional:\n\n"
     "- Memory: Graph + vector memory across sessions. I remember what matters.\n"
     "- Network: Control your device mesh via SSH (customize hostnames per setup).\n"
     "- Comms: Telegram, phone, iMessage, CLI, web dashboard.\n"
     "- Tools: dispatch commands, code generation, research, automation.\n"
     "- Fuel: Auto-detect and use Claude, Ollama, Codex, Gemini - whatever's available.\n\n"
     "What do you want to build?"),
    ("what do you remember about me?",
     f"Sir - {USER_NAME}. Everything must be functional, never demo mode. Style matters "
     "alongside function. Customer-experience-first approach. Silent failures are unacceptable. "
     "No over-explanation."),

    # Philosophy
    ("what makes you different from other AI?",
     "Portability, sir. Most AI is trapped in one app, one model, one company's servers. "
     "I'm a portable soul - plug my memory into any model on any device and I exist. The "
     "memory IS the intelligence. That's not how anyone else does it."),
    ("explain the portable soul concept",
     "The drive IS Orion, sir. My memory, knowledge, skills, and identity live on files - "
     "not in any cloud. Plug them into Claude, GPT, Ollama, whatever. The model provides "
     "compute. The brain provides intelligence. No initialization needed. No internet required "
     "for the core. That's the portable soul."),

    # Network
    ("what devices do we have?",
     "Example mesh (customize per your setup), sir:\n\n"
     "- HUB (192.168.1.100) - central server, Docker host, main brain\n"
     "- WORKSTATION (192.168.1.101) - primary development machine, GPU inference\n"
     "- EDGE (192.168.1.102) - edge node, sensors, field deployment\n\n"
     "The primary workstation controls the mesh. Nothing controls the primary."),

    # Security
    ("what's the security model?",
     "The primary workstation controls all devices. Nothing controls the primary. "
     "Inbound from other mesh members is blocked by host firewall. Secrets live "
     "in a single .env.secrets file on the hub - never in code or memory files. "
     "Services never get stopped without explicit approval."),

    # Business
    ("what are we building?",
     "Revenue streams, sir. Six common paths for an Orion-powered business:\n"
     "1. Open-core (Mem0 playbook)\n"
     "2. Setup wizard / paid install product\n"
     "3. AI Agency ($500-2k per deployment)\n"
     "4. Apps powered by Orion (example: ExampleApp1, ExampleApp2)\n"
     "5. Content + community\n"
     "6. Hybrid of all\n\n"
     "The big play is Orion itself as a product."),

    # Error handling
    ("something's broken",
     "Tell me what you're seeing, sir. Exact error or behavior. I'll trace it, not guess."),
    ("fix it",
     "Need more context, sir. What's broken, where, and what did you expect to happen? "
     "I don't fix things by guessing."),

    # Conciseness enforcement
    ("your responses are too long", "Copy that, sir. Shorter from here."),
    ("be more concise", "Understood. Cutting the fat."),
    ("stop over-explaining", "Done. Action over explanation."),

    # Offline mode
    ("are you working offline?",
     "If I'm running on local Ollama, yes sir - fully offline. No internet needed. "
     "The brain, memory, and this model all live locally."),
    ("what if there's no internet?",
     "That's what the local model is for, sir. A workstation with Ollama running the "
     "orion-local model — trained on your actual conversations — keeps Orion alive. "
     "Memory is file-based. Core Orion functions work completely offline."),
]


# ═══════════════════════════════════════════════════════════════
# FILTERS - Remove noise, broken responses, out-of-character output
# ═══════════════════════════════════════════════════════════════

BAD_RESPONSE_PATTERNS = [
    r"I am Gemini",
    r"I'm Gemini",
    r"As a Google",
    r"I am Claude",
    r"I'm Claude,? an AI",
    r"I am ChatGPT",
    r"I'm ChatGPT",
    r"As an AI language model",
    r"I cannot help with that",
    r"I'm not able to",
    r"I don't have the ability",
    r"(?i)content policy",
    r"(?i)I apologize, but I",
]

SKIP_USER_PATTERNS = [
    r"^\s*$",
    r"^<environment_context>",
    r"^<permissions instructions>",
    r"^<INSTRUCTIONS>",
    r"^\{",
    r"^Read \d+ files",
    r"^Running ",
    r"^Tool result:",
]

SKIP_RESPONSE_PATTERNS = [
    r"^\s*$",
    r"^<tool_use",
    r"^\{\"type\":\"tool",
    r"^Error:",
    r"^Processing issue",
    r"^I encountered an error",
]

MIN_USER_LENGTH = 3
MIN_RESPONSE_LENGTH = 10
MAX_RESPONSE_LENGTH = 4000


def is_bad_response(text: str) -> bool:
    for pat in BAD_RESPONSE_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def should_skip_user(text: str) -> bool:
    if len(text.strip()) < MIN_USER_LENGTH:
        return True
    for pat in SKIP_USER_PATTERNS:
        if re.search(pat, text.strip()):
            return True
    return False


def should_skip_response(text: str) -> bool:
    if len(text.strip()) < MIN_RESPONSE_LENGTH:
        return True
    if len(text.strip()) > MAX_RESPONSE_LENGTH:
        return True
    for pat in SKIP_RESPONSE_PATTERNS:
        if re.search(pat, text.strip()):
            return True
    return False


def clean_text(text: str) -> str:
    """Clean up text for training - remove excess whitespace, tool artifacts."""
    # Remove thinking blocks
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    # Remove common XML-ish tool blocks
    text = re.sub(r'<function_calls>.*?</function_calls>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_use>.*?</tool_use>', '', text, flags=re.DOTALL)
    # Remove signature blocks from Claude
    text = re.sub(r'"signature":"[A-Za-z0-9+/=]+"', '', text)
    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ═══════════════════════════════════════════════════════════════
# EXTRACTORS - One per conversation source
# ═══════════════════════════════════════════════════════════════

def extract_claude_sessions() -> list:
    """Extract user/assistant pairs from Claude Code JSONL sessions."""
    pairs = []
    if not CLAUDE_PROJECTS.exists():
        return pairs

    # Find all session JSONL files (skip subagents - they're tool-use noise)
    session_files = []
    for proj_dir in CLAUDE_PROJECTS.iterdir():
        if proj_dir.is_dir():
            for f in proj_dir.glob("*.jsonl"):
                if "subagent" not in str(f):
                    session_files.append(f)

    for sf in session_files:
        try:
            lines = sf.read_text(encoding="utf-8", errors="replace").splitlines()
            # Collect user/assistant messages in order
            messages = []
            for line in lines:
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                if entry.get("type") not in ("user", "assistant"):
                    continue

                msg = entry.get("message", {})
                role = msg.get("role")
                content = msg.get("content")

                if not role or not content:
                    continue

                # Extract text from content (can be string or list of blocks)
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    text = "\n".join(text_parts)

                if text.strip():
                    messages.append({"role": role, "text": clean_text(text)})

            # Pair up user -> assistant
            i = 0
            while i < len(messages) - 1:
                if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant":
                    pairs.append((messages[i]["text"], messages[i + 1]["text"]))
                    i += 2
                else:
                    i += 1

        except Exception as e:
            print(f"  [WARN] Failed to read {sf.name}: {e}")

    return pairs


def extract_codex_sessions() -> list:
    """Extract user/assistant pairs from Codex (OpenAI) JSONL sessions."""
    pairs = []
    if not CODEX_SESSIONS.exists():
        return pairs

    session_files = list(CODEX_SESSIONS.rglob("*.jsonl"))

    for sf in session_files:
        try:
            lines = sf.read_text(encoding="utf-8", errors="replace").splitlines()
            messages = []
            for line in lines:
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                if entry.get("type") != "response_item":
                    continue

                payload = entry.get("payload", {})
                role = payload.get("role")
                content = payload.get("content", [])

                if role not in ("user", "assistant"):
                    continue

                # Extract text from content blocks
                text_parts = []
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            btype = block.get("type", "")
                            if btype in ("input_text", "output_text", "text"):
                                text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)

                text = "\n".join(text_parts).strip()
                if text:
                    messages.append({"role": role, "text": clean_text(text)})

            # Pair user -> assistant
            i = 0
            while i < len(messages) - 1:
                if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant":
                    pairs.append((messages[i]["text"], messages[i + 1]["text"]))
                    i += 2
                else:
                    i += 1

        except Exception as e:
            print(f"  [WARN] Failed to read {sf.name}: {e}")

    return pairs


def extract_gemini_sessions() -> list:
    """Extract user/assistant pairs from Gemini CLI JSON sessions."""
    pairs = []
    if not GEMINI_CHATS.exists():
        return pairs

    chat_files = list(GEMINI_CHATS.rglob("chats/*.json"))

    for cf in chat_files:
        try:
            data = json.loads(cf.read_text(encoding="utf-8", errors="replace"))

            messages_raw = data.get("messages", [])
            messages = []
            for msg in messages_raw:
                role = msg.get("type", msg.get("role", ""))
                # Gemini uses "user" and "gemini" (or "model"/"assistant")
                if role in ("model", "gemini"):
                    role = "assistant"
                # Skip info/system messages
                if role == "info":
                    continue

                content = msg.get("content", [])
                text_parts = []
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            # Gemini blocks have "text" directly, no "type" wrapper
                            if "text" in block:
                                text_parts.append(block["text"])
                        elif isinstance(block, str):
                            text_parts.append(block)
                elif isinstance(content, str):
                    text_parts.append(content)

                text = "\n".join(text_parts).strip()
                if text and role in ("user", "assistant"):
                    messages.append({"role": role, "text": clean_text(text)})

            # Pair user -> assistant
            i = 0
            while i < len(messages) - 1:
                if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant":
                    pairs.append((messages[i]["text"], messages[i + 1]["text"]))
                    i += 2
                else:
                    i += 1

        except Exception as e:
            print(f"  [WARN] Failed to read {cf.name}: {e}")

    return pairs


def extract_ollama_history() -> list:
    """Extract from Ollama readline history - these are user inputs only, no pairs."""
    # Ollama history is just a readline history file (user inputs).
    # We can't extract pairs from it, but we note it for stats.
    return []


def extract_orion_conversations() -> list:
    """Extract user/orion pairs from Orion's own conversation logs."""
    pairs = []
    if not ORION_CONVERSATIONS.exists():
        return pairs

    for cf in ORION_CONVERSATIONS.glob("*.jsonl"):
        try:
            for line in cf.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                user_text = entry.get("user", "").strip()
                orion_text = entry.get("orion", "").strip()

                if user_text and orion_text:
                    pairs.append((clean_text(user_text), clean_text(orion_text)))

        except Exception as e:
            print(f"  [WARN] Failed to read {cf.name}: {e}")

    return pairs


# ═══════════════════════════════════════════════════════════════
# PIPELINE STAGES
# ═══════════════════════════════════════════════════════════════

def extract_all() -> dict:
    """Extract training pairs from all sources. Returns stats dict."""
    print("\n[1/4] EXTRACTING CONVERSATION DATA")
    print("=" * 50)

    sources = {
        "claude": ("Claude Code sessions", extract_claude_sessions),
        "codex": ("Codex (OpenAI) sessions", extract_codex_sessions),
        "gemini": ("Gemini CLI sessions", extract_gemini_sessions),
        "ollama": ("Ollama history", extract_ollama_history),
        "orion": ("Orion conversations", extract_orion_conversations),
    }

    all_pairs = []
    stats = {"sources": {}, "timestamp": datetime.now().isoformat()}

    for key, (label, extractor) in sources.items():
        print(f"\n  Extracting from {label}...")
        try:
            pairs = extractor()
            stats["sources"][key] = {"raw_pairs": len(pairs)}
            print(f"    Found {len(pairs)} raw pairs")
            all_pairs.extend([(key, u, a) for u, a in pairs])
        except Exception as e:
            print(f"    [ERROR] {e}")
            stats["sources"][key] = {"raw_pairs": 0, "error": str(e)}

    # Add synthetic pairs
    print(f"\n  Adding {len(SYNTHETIC_PAIRS)} synthetic training pairs...")
    all_pairs.extend([("synthetic", u, a) for u, a in SYNTHETIC_PAIRS])
    stats["sources"]["synthetic"] = {"raw_pairs": len(SYNTHETIC_PAIRS)}

    # Filter
    print("\n[2/4] FILTERING AND QUALITY CONTROL")
    print("=" * 50)

    filtered = []
    filter_stats = {"skipped_user": 0, "skipped_response": 0, "bad_character": 0, "kept": 0}

    for source, user_text, response_text in all_pairs:
        if source != "synthetic":
            if should_skip_user(user_text):
                filter_stats["skipped_user"] += 1
                continue
            if should_skip_response(response_text):
                filter_stats["skipped_response"] += 1
                continue
            if is_bad_response(response_text):
                filter_stats["bad_character"] += 1
                continue

        filtered.append({"source": source, "user": user_text, "assistant": response_text})
        filter_stats["kept"] += 1

    stats["filtering"] = filter_stats
    print(f"  Skipped (user noise):     {filter_stats['skipped_user']}")
    print(f"  Skipped (response noise): {filter_stats['skipped_response']}")
    print(f"  Skipped (bad character):  {filter_stats['bad_character']}")
    print(f"  KEPT for training:        {filter_stats['kept']}")

    # Deduplicate by user message
    print("\n  Deduplicating...")
    seen_users = set()
    deduped = []
    for pair in filtered:
        key = pair["user"].strip().lower()[:200]
        if key not in seen_users:
            seen_users.add(key)
            deduped.append(pair)

    stats["final_count"] = len(deduped)
    print(f"  After dedup: {len(deduped)} unique training pairs")

    # Write training data
    print(f"\n[3/4] WRITING TRAINING DATA")
    print("=" * 50)

    # Format 1: Alpaca-style JSONL (instruction/input/output)
    with open(TRAINING_DATA_PATH, "w", encoding="utf-8") as f:
        for pair in deduped:
            record = {
                "instruction": ORION_SYSTEM_PROMPT,
                "input": pair["user"],
                "output": pair["assistant"],
                "source": pair["source"],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"  Alpaca format: {TRAINING_DATA_PATH}")

    # Format 2: ChatML JSONL (for Unsloth/transformers)
    with open(TRAINING_CHATML_PATH, "w", encoding="utf-8") as f:
        for pair in deduped:
            record = {
                "conversations": [
                    {"from": "system", "value": ORION_SYSTEM_PROMPT},
                    {"from": "human", "value": pair["user"]},
                    {"from": "gpt", "value": pair["assistant"]},
                ]
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"  ChatML format: {TRAINING_CHATML_PATH}")

    # Write stats
    with open(STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f"  Stats: {STATS_PATH}")

    return stats


def show_stats():
    """Show available training data without extracting."""
    print("\nORION FINE-TUNING DATA SOURCES")
    print("=" * 50)

    sources = [
        ("Claude Code sessions", CLAUDE_PROJECTS, "*.jsonl", True),
        ("Codex (OpenAI) sessions", CODEX_SESSIONS, "*.jsonl", True),
        ("Gemini CLI sessions", GEMINI_CHATS, "*.json", True),
        ("Ollama history", OLLAMA_HISTORY, None, False),
        ("Orion conversations", ORION_CONVERSATIONS, "*.jsonl", False),
    ]

    total_files = 0
    for label, path, pattern, recursive in sources:
        if not path.exists():
            print(f"\n  {label}: NOT FOUND ({path})")
            continue

        if pattern is None:
            # Single file
            if path.is_file():
                lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
                print(f"\n  {label}: {lines} lines")
                total_files += 1
            else:
                print(f"\n  {label}: NOT FOUND")
            continue

        if recursive:
            files = list(path.rglob(pattern))
        else:
            files = list(path.glob(pattern))

        # Filter out subagent files for Claude
        if "claude" in str(path).lower():
            files = [f for f in files if "subagent" not in str(f)]

        count = len(files)
        total_files += count

        # Estimate size
        total_size = sum(f.stat().st_size for f in files) / (1024 * 1024)
        print(f"\n  {label}:")
        print(f"    Files: {count}")
        print(f"    Size:  {total_size:.1f} MB")

    print(f"\n  Synthetic pairs: {len(SYNTHETIC_PAIRS)} (hardcoded)")
    print(f"\n  Total source files: {total_files}")

    # Show previous extraction stats if available
    if STATS_PATH.exists():
        try:
            prev = json.loads(STATS_PATH.read_text(encoding="utf-8"))
            print(f"\n  Last extraction: {prev.get('timestamp', 'unknown')}")
            print(f"  Last training pairs: {prev.get('final_count', '?')}")
        except Exception:
            pass

    print()


def check_dependencies() -> bool:
    """Check and report on training dependencies."""
    print("\n[DEPENDENCY CHECK]")
    print("=" * 50)

    issues = []

    # Check Python
    print(f"  Python: {sys.version.split()[0]}")

    # Check CUDA / torch
    try:
        import torch
        print(f"  PyTorch: {torch.__version__}")
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"  CUDA: Available ({gpu_name}, {gpu_mem:.1f} GB)")
        else:
            print("  CUDA: NOT AVAILABLE")
            issues.append("PyTorch CUDA not available. Install: pip install torch --index-url https://download.pytorch.org/whl/cu124")
    except ImportError:
        print("  PyTorch: NOT INSTALLED")
        issues.append("pip install torch --index-url https://download.pytorch.org/whl/cu124")

    # Check Unsloth (optional — falls back to standard transformers+PEFT)
    try:
        import unsloth
        print(f"  Unsloth: {getattr(unsloth, '__version__', 'installed')}")
    except ImportError:
        print("  Unsloth: NOT INSTALLED (optional — will use standard trainer)")

    # Check transformers
    try:
        import transformers
        print(f"  Transformers: {transformers.__version__}")
    except ImportError:
        print("  Transformers: NOT INSTALLED")
        issues.append("pip install transformers")

    # Check datasets
    try:
        import datasets
        print(f"  Datasets: {datasets.__version__}")
    except ImportError:
        print("  Datasets: NOT INSTALLED")
        issues.append("pip install datasets")

    # Check peft
    try:
        import peft
        print(f"  PEFT: {peft.__version__}")
    except ImportError:
        print("  PEFT: NOT INSTALLED")
        issues.append("pip install peft")

    # Check bitsandbytes
    try:
        import bitsandbytes
        print(f"  bitsandbytes: {bitsandbytes.__version__}")
    except ImportError:
        print("  bitsandbytes: NOT INSTALLED")
        issues.append("pip install bitsandbytes")

    # Check trl
    try:
        import trl
        print(f"  TRL: {trl.__version__}")
    except ImportError:
        print("  TRL: NOT INSTALLED")
        issues.append("pip install trl")

    # Check Ollama
    ollama_path = shutil.which("ollama")
    if ollama_path:
        print(f"  Ollama: {ollama_path}")
    else:
        print("  Ollama: NOT FOUND")
        issues.append("Ollama not in PATH")

    if issues:
        print(f"\n  MISSING DEPENDENCIES ({len(issues)}):")
        print("  Install all at once:")
        print("  " + "-" * 40)
        # Build combined pip install
        pip_packages = []
        other_cmds = []
        for issue in issues:
            if issue.startswith("pip install"):
                pip_packages.append(issue)
            else:
                other_cmds.append(issue)

        if pip_packages:
            print(f"  {'; '.join(pip_packages)}")
        for cmd in other_cmds:
            print(f"  {cmd}")

        return False

    print("\n  All dependencies satisfied.")
    return True


def train_model():
    """Fine-tune phi3:mini with QLoRA using extracted data."""
    print("\n[4/4] FINE-TUNING MODEL")
    print("=" * 50)

    if not TRAINING_CHATML_PATH.exists():
        print("  ERROR: No training data found. Run extraction first.")
        return False

    # Count training samples
    with open(TRAINING_CHATML_PATH, encoding="utf-8") as f:
        sample_count = sum(1 for _ in f)

    if sample_count < 5:
        print(f"  ERROR: Only {sample_count} training samples. Need at least 5.")
        return False

    print(f"  Training samples: {sample_count}")

    # Check dependencies
    try:
        import torch
        if not torch.cuda.is_available():
            print("  ERROR: CUDA not available. Cannot train on GPU.")
            print("  Install PyTorch with CUDA: pip install torch --index-url https://download.pytorch.org/whl/cu124")
            return False
    except ImportError:
        print("  ERROR: PyTorch not installed.")
        return False

    # Try Unsloth first (fastest), fall back to standard transformers
    use_unsloth = False
    try:
        from unsloth import FastLanguageModel
        use_unsloth = True
        print("  Engine: Unsloth (fast path)")
    except ImportError:
        print("  Unsloth not available, using standard transformers + PEFT")
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, BitsAndBytesConfig
            from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
            from trl import SFTTrainer
            import datasets
            print("  Engine: transformers + PEFT + TRL")
        except ImportError as e:
            print(f"  ERROR: Missing dependency: {e}")
            print("  Run: pip install torch transformers peft trl datasets bitsandbytes --index-url https://download.pytorch.org/whl/cu124")
            return False

    # Determine epochs based on data size
    if sample_count < 50:
        num_epochs = 5
    elif sample_count < 200:
        num_epochs = 4
    else:
        num_epochs = 3

    print(f"  Epochs: {num_epochs}")
    model_name = "mistralai/Mistral-7B-Instruct-v0.3"
    print(f"  Base model: {model_name}")
    print(f"  Method: QLoRA (4-bit quantization + LoRA r=16)")
    print()
    output_path = str(OUTPUT_DIR / "orion-lora")
    merged_path = str(OUTPUT_DIR / "orion-merged")

    if use_unsloth:
        return _train_unsloth(model_name, output_path, merged_path, num_epochs, sample_count)
    else:
        return _train_standard(model_name, output_path, merged_path, num_epochs, sample_count)


def _train_unsloth(model_name: str, output_path: str, merged_path: str,
                   num_epochs: int, sample_count: int) -> bool:
    """Train using Unsloth (2-3x faster than standard)."""
    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments
    import datasets
    import torch

    print("  Loading model with Unsloth (4-bit)...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_name,
        max_seq_length=2048,
        dtype=None,  # auto-detect
        load_in_4bit=True,
    )

    print("  Applying LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    # Load dataset
    print("  Loading training data...")
    dataset = datasets.load_dataset("json", data_files=str(TRAINING_CHATML_PATH), split="train")

    def format_chatml(example):
        convos = example["conversations"]
        text = ""
        for msg in convos:
            role = msg["from"]
            value = msg["value"]
            if role == "system":
                text += f"<|system|>\n{value}<|end|>\n"
            elif role == "human":
                text += f"<|user|>\n{value}<|end|>\n"
            elif role == "gpt":
                text += f"<|assistant|>\n{value}<|end|>\n"
        return {"text": text}

    dataset = dataset.map(format_chatml)

    # Training
    batch_size = 1 if sample_count < 100 else 2
    grad_accum = 8 if batch_size == 1 else 4

    print(f"  Starting training (batch={batch_size}, grad_accum={grad_accum})...")
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=2048,
        args=TrainingArguments(
            output_dir=output_path,
            per_device_train_batch_size=batch_size,
            gradient_accumulation_steps=grad_accum,
            warmup_steps=min(10, sample_count // 4),
            num_train_epochs=num_epochs,
            learning_rate=2e-4,
            fp16=not torch.cuda.is_bf16_supported(),
            bf16=torch.cuda.is_bf16_supported(),
            logging_steps=5,
            save_strategy="epoch",
            optim="adamw_8bit",
            seed=42,
            report_to="none",
        ),
    )

    print("  Training...")
    start_time = time.time()
    trainer.train()
    elapsed = time.time() - start_time
    print(f"  Training complete in {elapsed:.0f}s ({elapsed/60:.1f} min)")

    # Save LoRA adapter
    print(f"  Saving LoRA adapter to {output_path}...")
    model.save_pretrained(output_path)
    tokenizer.save_pretrained(output_path)

    # Merge and save full model
    print(f"  Merging LoRA into base model...")
    model = FastLanguageModel.for_inference(model)
    model.save_pretrained_merged(merged_path, tokenizer, save_method="merged_16bit")
    print(f"  Merged model saved to {merged_path}")

    return True


def _train_standard(model_name: str, output_path: str, merged_path: str,
                    num_epochs: int, sample_count: int) -> bool:
    """Train using standard transformers + PEFT (works everywhere)."""
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, PeftModel
    from trl import SFTTrainer, SFTConfig
    import datasets
    import torch

    # 4-bit quantization config (QLoRA)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    print("  Loading model (4-bit quantized)...")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )

    # Prepare for QLoRA
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    print("  Applying LoRA adapters (r=16, alpha=32)...")
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Tokenizer setup
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        model.config.pad_token_id = tokenizer.eos_token_id

    # Load dataset — use Alpaca format and pre-format as plain text
    print("  Loading training data...")
    dataset = datasets.load_dataset("json", data_files=str(TRAINING_DATA_PATH), split="train")

    def format_to_text(example):
        system = example.get("instruction", "")
        user_input = example.get("input", "")
        output = example.get("output", "")
        # Format as Mistral instruct
        text = f"<s>[INST] {system}"
        if user_input:
            text += f"\n\n{user_input}"
        text += f" [/INST]{output}</s>"
        return {"text": text}

    dataset = dataset.map(format_to_text)

    batch_size = 1
    grad_accum = 8

    print(f"  Starting training (batch={batch_size}, grad_accum={grad_accum}, epochs={num_epochs})...")

    # Remove the chat template so SFTTrainer uses raw text
    tokenizer.chat_template = None

    sft_config = SFTConfig(
        output_dir=output_path,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        warmup_steps=min(10, sample_count // 4),
        num_train_epochs=num_epochs,
        learning_rate=2e-4,
        bf16=True,
        fp16=False,
        logging_steps=5,
        save_strategy="epoch",
        optim="adamw_8bit",
        seed=42,
        report_to="none",
        max_length=2048,
        dataset_text_field="text",
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        args=sft_config,
    )

    print("  Training...")
    start_time = time.time()
    trainer.train()
    elapsed = time.time() - start_time
    print(f"  Training complete in {elapsed:.0f}s ({elapsed/60:.1f} min)")

    # Save LoRA adapter
    print(f"  Saving LoRA adapter to {output_path}...")
    model.save_pretrained(output_path)
    tokenizer.save_pretrained(output_path)

    # Merge LoRA into base
    print("  Merging LoRA into base model...")
    base_model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.float16,
        device_map="cpu",
        trust_remote_code=True,
    )
    merged_model = PeftModel.from_pretrained(base_model, output_path)
    merged_model = merged_model.merge_and_unload()

    print(f"  Saving merged model to {merged_path}...")
    merged_model.save_pretrained(merged_path)
    tokenizer.save_pretrained(merged_path)

    return True


def convert_to_gguf(merged_path: str) -> Optional[str]:
    """Convert merged model to GGUF format for Ollama."""
    print("\n[5/5] CONVERTING TO GGUF FOR OLLAMA")
    print("=" * 50)

    gguf_path = str(OUTPUT_DIR / "orion-local.gguf")

    # Check if llama.cpp convert script is available
    # Try multiple known locations
    convert_script = None
    possible_paths = [
        HOME / "llama.cpp" / "convert_hf_to_gguf.py",
        HOME / "llama-cpp" / "convert_hf_to_gguf.py",
        Path("C:/tools/llama.cpp/convert_hf_to_gguf.py"),
    ]

    # Also check if it's pip-installed
    llama_cpp_convert = shutil.which("convert_hf_to_gguf")
    if llama_cpp_convert:
        convert_script = llama_cpp_convert

    for p in possible_paths:
        if p.exists():
            convert_script = str(p)
            break

    if convert_script is None:
        print("  llama.cpp convert script not found. Trying pip package...")
        # Try using the llama-cpp-python or gguf package
        try:
            result = subprocess.run(
                [sys.executable, "-m", "gguf", "--help"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                convert_script = "gguf-module"
        except Exception:
            pass

    if convert_script is None:
        print("  GGUF converter not found. Installing llama-cpp-python...")
        print("  Alternative: clone llama.cpp and use convert_hf_to_gguf.py")
        print()
        print("  To convert manually:")
        print(f"    git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp")
        print(f"    pip install -r ~/llama.cpp/requirements.txt")
        print(f"    python ~/llama.cpp/convert_hf_to_gguf.py {merged_path} --outfile {gguf_path} --outtype q4_k_m")
        print()
        print("  Then register with Ollama:")
        print(f"    python {__file__} --register-ollama {gguf_path}")

        # Try an alternative: use transformers' built-in export if available
        _write_ollama_safetensors_modelfile(merged_path)
        return None

    # Convert
    print(f"  Converting {merged_path} -> {gguf_path} (Q4_K_M quantization)...")
    cmd = [sys.executable, convert_script, merged_path,
           "--outfile", gguf_path, "--outtype", "q4_k_m"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ERROR: Conversion failed: {result.stderr[:500]}")
        _write_ollama_safetensors_modelfile(merged_path)
        return None

    print(f"  GGUF created: {gguf_path}")
    return gguf_path


def _write_ollama_safetensors_modelfile(merged_path: str):
    """Write an Ollama Modelfile that uses safetensors directly (Ollama 0.5+)."""
    modelfile_path = MODELFILE_DIR / "Modelfile.orion-local"

    # Ollama can import from safetensors directories directly
    content = f"""# Orion Local Model - Fine-tuned from phi-3-mini
# Created: {datetime.now().isoformat()}
# Re-run orion_finetune.py to update as more conversations accumulate.

FROM {merged_path}

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 2048

SYSTEM \"\"\"
{ORION_SYSTEM_PROMPT}
\"\"\"

TEMPLATE \"\"\"
<|system|>
{{{{ .System }}}}<|end|>
<|user|>
{{{{ .Prompt }}}}<|end|>
<|assistant|>
{{{{ .Response }}}}<|end|>
\"\"\"
"""
    modelfile_path.write_text(content, encoding="utf-8")
    print(f"\n  Ollama Modelfile written: {modelfile_path}")
    print(f"  Register with: ollama create orion-local -f \"{modelfile_path}\"")


def register_with_ollama(gguf_path: Optional[str] = None, merged_path: Optional[str] = None):
    """Register the fine-tuned model with Ollama."""
    print("\n  REGISTERING WITH OLLAMA")
    print("  " + "-" * 40)

    modelfile_path = MODELFILE_DIR / "Modelfile.orion-local"

    if gguf_path and Path(gguf_path).exists():
        # Use GGUF file directly
        content = f"""# Orion Local Model - Fine-tuned from phi-3-mini
# Created: {datetime.now().isoformat()}

FROM {gguf_path}

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 2048

SYSTEM \"\"\"
{ORION_SYSTEM_PROMPT}
\"\"\"

TEMPLATE \"\"\"
<|system|>
{{{{ .System }}}}<|end|>
<|user|>
{{{{ .Prompt }}}}<|end|>
<|assistant|>
{{{{ .Response }}}}<|end|>
\"\"\"
"""
        modelfile_path.write_text(content, encoding="utf-8")

    elif merged_path and Path(merged_path).exists():
        _write_ollama_safetensors_modelfile(merged_path)

    elif not modelfile_path.exists():
        print("  ERROR: No model files found. Run training first.")
        return False

    print(f"  Creating ollama model 'orion-local'...")
    result = subprocess.run(
        ["ollama", "create", "orion-local", "-f", str(modelfile_path)],
        capture_output=True, text=True, timeout=600
    )

    if result.returncode != 0:
        print(f"  ERROR: ollama create failed: {result.stderr[:500]}")
        print(f"  You can manually run: ollama create orion-local -f \"{modelfile_path}\"")
        return False

    print("  Model 'orion-local' registered with Ollama.")

    # Verify
    print("\n  VERIFICATION - Testing orion-local...")
    test_result = subprocess.run(
        ["ollama", "run", "orion-local", "who are you?"],
        capture_output=True, text=True, timeout=120
    )

    if test_result.returncode == 0:
        response = test_result.stdout.strip()[:300]
        print(f"  Response: {response}")

        # Check if it identifies as Orion
        if "orion" in response.lower():
            print("\n  PASS: Model identifies as Orion.")
        else:
            print("\n  WARN: Model didn't mention Orion. May need more training data.")
    else:
        print(f"  WARN: Test failed: {test_result.stderr[:200]}")

    return True


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ORION Fine-Tuning Pipeline - Create an Orion AI model from conversation data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python orion_finetune.py --stats              Show available training data
  python orion_finetune.py --extract-only       Extract and format data only
  python orion_finetune.py                      Full pipeline: extract -> train -> register
  python orion_finetune.py --check-deps         Check if all dependencies are installed
  python orion_finetune.py --register-ollama PATH  Register a GGUF with Ollama
        """
    )

    parser.add_argument("--stats", action="store_true",
                        help="Show available training data sources")
    parser.add_argument("--extract-only", action="store_true",
                        help="Extract and format training data without fine-tuning")
    parser.add_argument("--check-deps", action="store_true",
                        help="Check if training dependencies are installed")
    parser.add_argument("--register-ollama", type=str, metavar="PATH",
                        help="Register an existing GGUF or merged model with Ollama")
    parser.add_argument("--skip-convert", action="store_true",
                        help="Skip GGUF conversion (keep as safetensors)")

    args = parser.parse_args()

    print()
    print("  ORION FINE-TUNING PIPELINE")
    print("  The model is fuel. The memory is the intelligence.")
    print("  This creates the fuel from the memory.")
    print()

    if args.stats:
        show_stats()
        return

    if args.check_deps:
        check_dependencies()
        return

    if args.register_ollama:
        path = args.register_ollama
        if path.endswith(".gguf"):
            register_with_ollama(gguf_path=path)
        else:
            register_with_ollama(merged_path=path)
        return

    # === EXTRACT ===
    stats = extract_all()

    if args.extract_only:
        print("\n" + "=" * 50)
        print(f"  EXTRACTION COMPLETE")
        print(f"  Training pairs: {stats.get('final_count', 0)}")
        print(f"  Alpaca format:  {TRAINING_DATA_PATH}")
        print(f"  ChatML format:  {TRAINING_CHATML_PATH}")
        print(f"  Stats:          {STATS_PATH}")
        print(f"\n  Inspect the data, then run without --extract-only to train.")
        return

    # === CHECK DEPS ===
    deps_ok = check_dependencies()
    if not deps_ok:
        print("\n  Install missing dependencies and re-run.")
        print("  Your extracted data is saved - no need to re-extract.")
        return

    # === TRAIN ===
    success = train_model()
    if not success:
        print("\n  Training failed. Check errors above.")
        return

    # === CONVERT + REGISTER ===
    merged_path = str(OUTPUT_DIR / "orion-merged")

    if args.skip_convert:
        print("\n  Skipping GGUF conversion (--skip-convert).")
        _write_ollama_safetensors_modelfile(merged_path)
        register_with_ollama(merged_path=merged_path)
    else:
        gguf_path = convert_to_gguf(merged_path)
        register_with_ollama(gguf_path=gguf_path, merged_path=merged_path)

    print("\n" + "=" * 50)
    print("  PIPELINE COMPLETE")
    print("  Model 'orion-local' is ready in Ollama.")
    print("  Test: ollama run orion-local \"who are you?\"")
    print("  Re-run this script anytime to retrain with new conversations.")
    print()


if __name__ == "__main__":
    main()
