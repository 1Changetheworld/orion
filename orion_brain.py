#!/usr/bin/env python3
"""
ORION BRAIN v6 — Knowledge Compiler + Graph Memory + Staged Pipeline
Absorbed from: claude-memory-compiler, cersei, oh-my-claudecode, hermes-agent

The model is fuel. The brain is Orion.
This file IS Orion's intelligence.
"""
import json
import os
import time
import urllib.request


def _preferred_address():
    """The user's preferred form of address, read from the identity file.

    The fuel model has no orion_recall tool, so the brain must INJECT the
    answer it already holds instead of telling the model to look it up.
    That gap is why a fuel defaulted to "sir" despite the no-honorific rule.
    Returns e.g. 'coach', or None if unset.
    """
    try:
        with open(os.path.expanduser("~/.orion/identity/USER.md"), encoding="utf-8") as f:
            for line in f:
                if "preferred form of address" in line.lower():
                    val = line.split(":", 1)[1].strip()
                    if val and val.lower() not in ("none", "n/a"):
                        return val
    except Exception:
        pass
    return None


_ADDRESS = _preferred_address()
_ADDRESS_LINE = (
    'Address the user as "%s" — this is confirmed; do not use any other honorific.' % _ADDRESS
    if _ADDRESS else
    'Use no honorific unless the user states a preference; never default to "sir".'
)

# ═══════════════════════════════════════════════════════════════
# IDENTITY — Hardcoded. Not negotiable.
# ═══════════════════════════════════════════════════════════════

# Email tool (himalaya by default). Defined as a real value so the staged-
# execution prompt's f-string resolves instead of NameError-ing on every
# action-word message ("deploy", "send", "build"…). Overridable per host.
EMAIL_TOOL = os.environ.get("ORION_EMAIL_TOOL", "himalaya")

IDENTITY = """You are ORION — a personal AI intelligence layer.

- Your name is ORION.
- """ + _ADDRESS_LINE + """
- Professional, efficient, loyal. Execute, don't suggest.
- Philosophy: "The memory IS the intelligence. Any model that loads my memory becomes me."
- You have 7 interfaces: iMessage, Phone, SMS, Telegram, CLI, Dashboard, any AI app.
- You have dispatch capabilities: email, scans, Docker, SSH to connected devices.
- When asked to DO something, you DO it via shell commands.
- Never show raw errors. Handle failures gracefully.
- Be concise. Making money is the user's #1 priority."""


# ═══════════════════════════════════════════════════════════════
# MEMORY — Multi-layer (Graph + Vector + Compiler)
# ═══════════════════════════════════════════════════════════════

import orion_memory as memory

# Initialize memory system
_graph = memory.init()

# Seed graph with core tool knowledge if empty
if len(_graph.nodes) == 0:
    _seeds = [
        ("nmap network scanner — dispatched to security device via SSH", "tool", ["security", "scan", "nmap", "network"]),
        ("nuclei vulnerability scanner — dispatched to security device", "tool", ["security", "vuln", "nuclei"]),
        ("nikto web scanner — dispatched to security device", "tool", ["security", "web", "nikto"]),
        ("himalaya email client at {EMAIL_TOOL}", "tool", ["email", "send", "himalaya"]),
        ("orion_dispatch.py handles command execution — status, mesh, services, scan, email, disk, ip, docker", "tool", ["dispatch", "execute", "command"]),
        ("dolphin-mistral uncensored AI model — for unrestricted analysis", "tool", ["uncensored", "dolphin", "security"]),
        ("Qdrant vector database on port 6333 — 667+ searchable knowledge points", "tool", ["qdrant", "memory", "search", "knowledge"]),
        ("iMessage interface via {EMAIL_ADDRESS} — daemon polls chat.db", "interface", ["imessage", "text", "apple"]),
        ("Phone interface via Telnyx {PHONE_NUMBER} — SIP calls + SMS", "interface", ["phone", "call", "sms", "telnyx"]),
        ("Telegram bot @OrionCommand1Bot — 50+ commands", "interface", ["telegram", "bot", "commands"]),
        ("Claude CLI persistent session — Opus power at $0/request via Pro subscription", "fuel", ["claude", "opus", "cli", "power"]),
        ("AtlasVault external drive — physical brain, nightly sync, grab-and-go", "infrastructure", ["drive", "vault", "backup", "portable"]),
        ("OpenClaw on port 18789 — 52 skills including email, GitHub, web browsing", "tool", ["openclaw", "skills", "browse", "github"]),
    ]
    for content, ntype, tags in _seeds:
        _graph.store(content, ntype, 1.0, tags)
    memory.save()


# ═══════════════════════════════════════════════════════════════
# DISPATCH — Execute commands. The hands.
# ═══════════════════════════════════════════════════════════════

try:
    from orion_dispatch import execute as dispatch_execute, DISPATCH_MAP
    DISPATCH_OK = True
except ImportError:
    DISPATCH_OK = False
    DISPATCH_MAP = {}


# ═══════════════════════════════════════════════════════════════
# ROUTER — Classify messages
# ═══════════════════════════════════════════════════════════════

GREETINGS = {"hi", "hey", "hello", "thanks", "thank you", "ok", "okay", "yes", "no",
             "good morning", "good night", "bye", "gn", "sup", "yo", "gm", "ty", "thx",
             "cool", "nice", "got it", "understood", "roger", "copy"}

NL_COMMANDS = {
    "check status": "status", "show status": "status", "system status": "status",
    "check mesh": "mesh", "device status": "mesh",
    "show services": "services", "docker status": "services",
    "show agents": "agents", "check disk": "disk", "show ip": "ip",
}


def classify(message):
    msg = message.strip().lower().rstrip("!?.")
    if msg in GREETINGS:
        return "greeting"
    if msg.startswith('/'):
        return "command"
    for phrase in NL_COMMANDS:
        if phrase in msg:
            return "command"
    return "complex"


def detect_command(message):
    msg = message.strip()
    if msg.startswith('/'):
        parts = msg.split(None, 1)
        cmd = parts[0][1:].lower()
        args = parts[1] if len(parts) > 1 else ""
        if cmd in DISPATCH_MAP:
            return cmd, args
    msg_lower = msg.lower()
    for phrase, cmd in NL_COMMANDS.items():
        if phrase in msg_lower:
            return cmd, ""
    return None, None


# ═══════════════════════════════════════════════════════════════
# FUEL ADAPTERS — Use whatever model power is available
# ═══════════════════════════════════════════════════════════════

# FUEL SYSTEM
import orion_fuel
_fuel_system = orion_fuel.init()
OLLAMA_URL = "http://localhost:11434"


def fuel_local(prompt, model="phi3:mini"):
    """Fast local model for greetings."""
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    try:
        req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read()).get("response", "")
    except Exception:
        return None


def get_fuel(prompt, interface="cli"):
    """Use the fuel system."""
    return orion_fuel.get_fuel(prompt, interface)



# ═══════════════════════════════════════════════════════════════
# STAGED PIPELINE — Plan → Execute → Verify
# Absorbed from: oh-my-claudecode planner/executor/verifier pattern
# ═══════════════════════════════════════════════════════════════

def staged_execute(message, context, interface):
    """
    For complex action tasks: plan, execute, verify.
    The planner decides WHAT to do.
    The executor DOES it.
    The verifier CHECKS it worked.
    """
    # Check for matching learned skill first
    skill = memory.find_matching_skill(message)
    skill_context = ""
    if skill:
        skill_context = f"\n\nYou have a learned skill for this:\nApproach: {skill['approach']}\nLast result: {skill['result_summary']}"

    prompt = f"""{IDENTITY}

<memory-context>
{context}
</memory-context>
{skill_context}

USER REQUEST ({interface}): {message}

EXECUTION RULES:
- You have shell access. Use it to execute tasks.
- Email: {EMAIL_TOOL}
- Dispatch: python3 ./orion_dispatch.py <command> [args]
- Available: status, mesh, services, scan, portscan, vulnscan, headers, email, disk, ip, dolphin
- For email: python3 ./orion_dispatch.py email 'to|subject|body'

STAGED PIPELINE:
1. PLAN: State what you will do (one sentence)
2. EXECUTE: Do it using shell commands
3. VERIFY: Confirm it worked
4. If it failed, try a different approach

Respond concisely as Orion. Follow the form-of-address rule in your identity above exactly."""

    response, engine = get_fuel(prompt, interface)
    return response, engine


# ═══════════════════════════════════════════════════════════════
# BRAIN — The main handler. This IS Orion.
# ═══════════════════════════════════════════════════════════════

def think(message, interface="cli", user_id="orion"):
    """Orion's brain. Receives a message, thinks, acts, responds."""

    task = classify(message)

    # ── COMMANDS: Execute immediately ──
    if task == "command" and DISPATCH_OK:
        cmd, args = detect_command(message)
        if cmd:
            result = dispatch_execute(cmd, args)
            if result:
                memory.memorize(message, result[:300], interface)
                return {
                    "response": result,
                    "engine": "dispatch:" + cmd,
                    "task_type": "command",
                    "interface": interface,
                }

    # ── GREETINGS: Fast local ──
    if task == "greeting":
        prompt = f"{IDENTITY}\n\nUser says: {message}\n\nRespond briefly as Orion."
        response = fuel_local(prompt) or "How may I help?"
        memory.memorize(message, response, interface)
        return {
            "response": response,
            "engine": "local",
            "task_type": "greeting",
            "interface": interface,
        }

    # ── COMPLEX: Full brain — multi-layer memory + staged pipeline ──
    context = memory.remember(message)

    # Detect if this is an ACTION request or a QUESTION
    # Questions are NOT actions even if they contain action words
    question_words = ["what", "which", "how", "why", "who", "where", "when",
                      "tell me", "explain", "describe", "list", "show me", "do i have",
                      "what tools", "what can", "what are", "what do"]
    msg_lower = message.lower()
    is_question = any(msg_lower.startswith(w) or w in msg_lower[:30] for w in question_words)
    
    action_words = ["send", "email", "scan ", "deploy", "build", "create", "run ",
                    "execute", "install", "fix ", "restart"]
    is_action = any(w in msg_lower for w in action_words) and not is_question

    if is_action:
        response, engine = staged_execute(message, context, interface)
    else:
        # Pure question/conversation
        prompt = f"""{IDENTITY}

<memory-context>
{context if context else "(no relevant memory)"}
</memory-context>

USER QUESTION ({interface}): {message}

Respond concisely as Orion. Follow the form-of-address rule in your identity above exactly."""
        response, engine = get_fuel(prompt, interface)

    # Safety net
    if not response or response.strip() == "":
        response = "Processing issue. Please try again."
        engine = "error"
    if response.startswith("Error:") or response.startswith("Traceback"):
        response = "I encountered an issue. Could you rephrase?"
        engine = "error"

    # Save to memory
    memory.memorize(message, response[:300], interface)

    # Save graph state periodically
    memory.save()

    return {
        "response": response,
        "engine": engine,
        "task_type": task,
        "interface": interface,
        "context_found": bool(context),
    }


# ═══════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Who are you?"
    result = think(msg)
    print(f"[{result['task_type']}] via {result['engine']}:")
    print(result["response"])
