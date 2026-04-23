#!/usr/bin/env python3
"""
ORION MCP SERVER — Universal Brain Interface
═══════════════════════════════════════════════════════════════

Model Context Protocol server that exposes the Orion portable
brain as tools callable by any MCP-compatible AI CLI:
  - Claude Code
  - Codex
  - Gemini CLI
  - Letta
  - Any JSON-RPC 2.0 over stdio client

Transport: STDIO (stdin/stdout JSON-RPC)
Dependencies: ZERO external. Pure stdlib + orion_brain_portable.py
Latency: Graph recall is 98us. MCP overhead is ~1ms.

Usage:
  python orion_mcp_server.py          # Start server (stdio)
  python orion_mcp_server.py --test   # Run test suite
  python orion_mcp_server.py --setup  # Configure MCP in installed tools

The model is fuel. The memory is the intelligence.
This file is the universal adapter.
"""

import json
import os
import sys
import time
from pathlib import Path

# ── Import the brain ──
# Add parent dir to path so we can import regardless of cwd
_this_dir = Path(__file__).resolve().parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from orion_brain_portable import (
    OrionBrain,
    SynthesisEngine,
    Heartbeat,
    read_all_sources,
    find_matching_skill,
    get_identity,
    start_heartbeat,
    heartbeat_status,
    reflex,
    SKILLS_DIR,
    SOUL_PATH,
    USER_MODEL_PATH,
    PROJECT_STATE_PATH,
    GRAPH_PATH,
)


# ═══════════════════════════════════════════════════════════════
# TOOL DEFINITIONS — Schema + handlers
# ═══════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "orion_recall",
        "description": (
            "Search Orion's memory for facts relevant to a query. Use this ANY time "
            "you need information about the user, their devices, projects, "
            "preferences, or past conversations. Results are ranked by decayed "
            "confidence — stale facts sink below fresh ones. Nodes flagged as "
            "contested are surfaced with a marker."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query."
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return. Default 5.",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "orion_remember",
        "description": (
            "LEGACY alias for orion_recall with query-only input. Prefer orion_recall. "
            "Kept for backward compatibility with clients configured before the "
            "unified schema. Returns recalled context from graph + knowledge."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "orion_memorize",
        "description": (
            "Save a new fact to Orion's long-term memory. Accepts either `content` "
            "(preferred) or `fact` (legacy) as the text to remember. Supports "
            "optional `tags` list and `type`. If the new fact conflicts with a "
            "prior node on the same subject, both are flagged for user resolution "
            "via orion_list_contested."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The fact, stated as a clear sentence. (Preferred parameter.)"
                },
                "fact": {
                    "type": "string",
                    "description": "Legacy alias for content. Use content instead when possible."
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Short tags for indexed recall (e.g., ['phone','contact'])."
                },
                "type": {
                    "type": "string",
                    "description": (
                        "Node type drives temporal decay. One of: identity, "
                        "preference, hardware, person, skill, fact, network, "
                        "service, project, task, ephemeral."
                    ),
                    "default": "fact"
                }
            }
        }
    },
    {
        "name": "orion_list_contested",
        "description": (
            "List memories currently flagged as contested — two facts on the "
            "same subject that disagree. Use this when the user asks what is "
            "conflicted, or when you suspect stale information before answering."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "orion_resolve_contradiction",
        "description": (
            "Commit a user's resolution of a contradiction. The winner keeps its "
            "confidence; losers are archived (never deleted) and hidden from "
            "recall unless explicitly requested."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "winner_id": {
                    "type": "integer",
                    "description": "The node id of the fact that wins."
                },
                "loser_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Node ids to archive as superseded."
                }
            },
            "required": ["winner_id", "loser_ids"]
        }
    },
    {
        "name": "orion_user_model",
        "description": (
            "Get Orion's synthesized understanding of the user — identity, "
            "communication style, values, frustrations, expertise, patterns, "
            "and learned behavioral rules. Built from cross-tool analysis."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "orion_project_state",
        "description": (
            "Get current project state — active projects, blocked items, "
            "recent decisions, and next actions. Built from cross-tool "
            "conversation analysis across Claude, Codex, Gemini, Ollama."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "orion_synthesize",
        "description": (
            "Get the full synthesized context document — a complete briefing "
            "that includes identity, user understanding, current state, behavioral "
            "rules, cross-tool awareness, and recent activity. This is the document "
            "that makes any model become Orion with full awareness."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "force": {
                    "type": "boolean",
                    "description": "Force regeneration even if cache is fresh. Default false."
                }
            },
            "required": []
        }
    },
    {
        "name": "orion_cross_model",
        "description": (
            "Get what's happening in other AI terminals — recent messages "
            "from Codex, Claude Code, Gemini CLI, Letta, and Ollama sessions. "
            "Use this to understand cross-tool context and avoid duplicate work."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max messages per source. Default 20."
                }
            },
            "required": []
        }
    },
    {
        "name": "orion_skills",
        "description": (
            "List learned skills or find a matching skill for a task. "
            "Skills are auto-learned from successful task completions and "
            "include triggers, approach, and result summaries."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional search query to find a matching skill. Omit to list all."
                }
            },
            "required": []
        }
    },
    {
        "name": "orion_identity",
        "description": (
            "Get Orion's identity, behavioral rules, and soul definition. "
            "Returns SOUL.md content plus learned rules from the user model. "
            "Use this to understand who Orion is and how to behave."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "orion_heartbeat",
        "description": (
            "Check the brain's heartbeat status — is it alive, how many cycles "
            "has it run, what did it learn recently, uptime, and recent activity. "
            "The heartbeat is the brain's autonomous thinking loop."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]


# ═══════════════════════════════════════════════════════════════
# BRAIN INSTANCE — Lazy-initialized, shared across calls
# ═══════════════════════════════════════════════════════════════

_brain = None
_synthesis = None
_heartbeat_started = False


def _get_brain() -> OrionBrain:
    """Lazy-init the brain. No fuel scan needed for MCP (we don't call LLMs)."""
    global _brain, _heartbeat_started
    if _brain is None:
        _brain = OrionBrain(scan_fuel=False)
    # Auto-start heartbeat on first brain access
    if not _heartbeat_started:
        _heartbeat_started = True
        try:
            start_heartbeat(interval=1800)  # 30 min cycles
        except Exception:
            pass  # Don't crash MCP if heartbeat fails to start
    return _brain


def _get_synthesis() -> SynthesisEngine:
    """Lazy-init the synthesis engine."""
    global _synthesis
    if _synthesis is None:
        _synthesis = SynthesisEngine()
    return _synthesis


# ═══════════════════════════════════════════════════════════════
# TOOL HANDLERS — Each returns a content list per MCP spec
# ═══════════════════════════════════════════════════════════════

def _handle_orion_remember(args: dict) -> list:
    """Legacy recall handler. Accepts only `query`. Kept for backward compat."""
    query = args.get("query", "")
    if not query:
        return [{"type": "text", "text": "Error: query is required."}]

    brain = _get_brain()
    t0 = time.perf_counter()
    context = brain.remember(query)
    elapsed_us = (time.perf_counter() - t0) * 1_000_000

    if not context:
        return [{"type": "text", "text": f"No memories found for: {query}\n(recall took {elapsed_us:.0f}us)"}]

    return [{"type": "text", "text": f"{context}\n\n[recall: {elapsed_us:.0f}us]"}]


def _handle_orion_recall(args: dict) -> list:
    """Unified recall handler — matches orion_tools.py schema.

    Accepts `query` (required) and `limit` (optional, default 5). Returns the
    same decayed-confidence-ranked results that orion_tool_chat.py sees, so
    MCP clients and local tool-calling clients share identical behavior.
    """
    query = args.get("query", "")
    limit = int(args.get("limit", 5))
    if not query:
        return [{"type": "text", "text": "Error: query is required."}]

    brain = _get_brain()
    t0 = time.perf_counter()
    nodes = brain.graph.recall(query=query, limit=limit)
    elapsed_us = (time.perf_counter() - t0) * 1_000_000

    if not nodes:
        return [{"type": "text", "text": f"No memories found for: {query}\n[recall: {elapsed_us:.0f}us]"}]

    lines = []
    for n in nodes:
        flag = " [contested]" if n.get("contested_with") else ""
        lines.append(f"- {n['content']}{flag}")
    return [{"type": "text", "text": "\n".join(lines) + f"\n\n[recall: {elapsed_us:.0f}us]"}]


def _handle_orion_memorize(args: dict) -> list:
    """Unified memorize handler — accepts legacy `fact` OR new `content`+`tags`.

    Legacy schema (MCP pre-unification): {fact, type}
    Unified schema (orion_tools.py):      {content, tags, type}
    Both land in the same GraphMemory write, identical node structure.
    """
    content = args.get("content") or args.get("fact") or ""
    if not content:
        return [{"type": "text", "text": "Error: content (or fact) is required."}]

    mem_type = args.get("type", "fact")
    provided_tags = args.get("tags") or []
    brain = _get_brain()

    from orion_brain_portable import extract_tags
    auto_tags = extract_tags(content, max_tags=8)
    # Merge: user-provided tags take priority, auto-tags fill in
    tags = list(dict.fromkeys(list(provided_tags) + auto_tags))
    if mem_type not in tags:
        tags.append(mem_type)

    # Use memorize with synthetic response so existing Mem0-style classification still runs
    response = f"[MCP memorize] Storing {mem_type}: {content}"
    action = brain.memorize(content, response, interface="mcp")

    # Explicit graph store — unified schema
    node_id = brain.graph.store(
        content=content,
        node_type=mem_type,
        confidence=0.9,
        tags=tags,
    )
    brain.save()

    # Reflex trigger for corrections / important signals
    c_lower = content.lower()
    if any(w in c_lower for w in ["never", "always", "don't", "stop", "wrong",
                                   "correction", "important", "critical", "emergency"]):
        reflex(content, source="mcp-memorize")

    action_type = action.get("action", "ADD") if isinstance(action, dict) else "ADD"
    contested = brain.graph.nodes.get(node_id, {}).get("contested_with") or []
    return [{"type": "text", "text": json.dumps({
        "status": "stored",
        "node_id": node_id,
        "classification": action_type,
        "type": mem_type,
        "content": content,
        "tags": tags,
        "contested_with": contested,
    }, indent=2)}]


def _handle_orion_list_contested(args: dict) -> list:
    """Surface all nodes currently flagged as contested for user resolution."""
    brain = _get_brain()
    contested = brain.graph.list_contested()
    if not contested:
        return [{"type": "text", "text": "No contested memories."}]
    lines = []
    for c in contested:
        lines.append(f"- id={c['id']}: {c['content']} (contested_with={c['contested_with']})")
    return [{"type": "text", "text": "\n".join(lines)}]


def _handle_orion_resolve_contradiction(args: dict) -> list:
    """Commit a user's resolution of a contradiction."""
    winner_id = args.get("winner_id")
    loser_ids = args.get("loser_ids") or []
    if winner_id is None:
        return [{"type": "text", "text": "Error: winner_id is required."}]
    try:
        winner_id = int(winner_id)
        loser_ids = [int(x) for x in loser_ids]
    except (TypeError, ValueError):
        return [{"type": "text", "text": "Error: winner_id and loser_ids must be integers."}]

    brain = _get_brain()
    ok = brain.graph.resolve_contradiction(winner_id, loser_ids)
    if not ok:
        return [{"type": "text", "text": f"Error: winner node {winner_id} not found."}]
    brain.save()
    return [{"type": "text", "text": f"Resolved. Winner: {winner_id}. Archived: {loser_ids}."}]


def _handle_orion_user_model(args: dict) -> list:
    synthesis = _get_synthesis()
    model = synthesis.user_model

    # Enrich with live data if stale
    if model.get("confidence", 0) < 0.1:
        try:
            messages = read_all_sources(limit_per_source=50)
            synthesis.build_user_model(messages)
        except Exception:
            pass

    return [{"type": "text", "text": json.dumps(model, indent=2, default=str)}]


def _handle_orion_project_state(args: dict) -> list:
    synthesis = _get_synthesis()
    state = synthesis.project_state

    # Enrich with live data if empty
    if not state.get("active_projects"):
        try:
            messages = read_all_sources(limit_per_source=50)
            synthesis.build_project_state(messages)
            state = synthesis.project_state
        except Exception:
            pass

    return [{"type": "text", "text": json.dumps(state, indent=2, default=str)}]


def _handle_orion_synthesize(args: dict) -> list:
    force = args.get("force", False)
    brain = _get_brain()

    try:
        context = brain.synthesize(force=force)
    except Exception as e:
        # Fallback: manual assembly without LLM
        synthesis = _get_synthesis()
        messages = read_all_sources(limit_per_source=50)
        context = synthesis._produce_context_document(messages)

    if not context:
        context = "Synthesis produced empty result. Brain may need more conversation data."

    return [{"type": "text", "text": context}]


def _handle_orion_cross_model(args: dict) -> list:
    limit = args.get("limit", 20)
    messages = read_all_sources(limit_per_source=limit)

    if not messages:
        return [{"type": "text", "text": "No cross-model messages found. No tool session files detected."}]

    # Group by source
    by_source = {}
    for m in messages:
        src = m.get("source", "unknown")
        if src not in by_source:
            by_source[src] = []
        by_source[src].append(m)

    output = {"sources": {}, "total_messages": len(messages)}
    for src, msgs in sorted(by_source.items()):
        # Only include user messages for brevity, plus count of assistant msgs
        user_msgs = [m for m in msgs if m.get("role") == "user"]
        asst_count = sum(1 for m in msgs if m.get("role") == "assistant")
        output["sources"][src] = {
            "user_messages": len(user_msgs),
            "assistant_messages": asst_count,
            "recent_user": [
                {
                    "text": m["text"][:300],
                    "timestamp": time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(m.get("timestamp", 0))
                    ) if m.get("timestamp", 0) > 0 else "unknown"
                }
                for m in user_msgs[-5:]  # last 5 per source
            ]
        }

    return [{"type": "text", "text": json.dumps(output, indent=2)}]


def _handle_orion_skills(args: dict) -> list:
    query = args.get("query", "")

    # If query provided, find matching skill
    if query:
        skill = find_matching_skill(query)
        if skill:
            return [{"type": "text", "text": json.dumps(skill, indent=2, default=str)}]
        return [{"type": "text", "text": f"No skill matches: {query}"}]

    # List all skills
    skills = []
    if SKILLS_DIR.is_dir():
        for fname in sorted(os.listdir(str(SKILLS_DIR))):
            if not fname.endswith('.json'):
                continue
            try:
                with open(SKILLS_DIR / fname, encoding='utf-8') as f:
                    skill = json.load(f)
                skills.append({
                    "name": skill.get("name", fname),
                    "triggers": skill.get("triggers", []),
                    "confidence": skill.get("confidence", 0),
                    "learned": skill.get("learned", "unknown"),
                    "times_used": skill.get("times_used", 0),
                })
            except Exception:
                continue

    if not skills:
        return [{"type": "text", "text": "No learned skills yet."}]

    return [{"type": "text", "text": json.dumps({"skills": skills, "count": len(skills)}, indent=2)}]


def _handle_orion_identity(args: dict) -> list:
    parts = []

    # SOUL.md
    if SOUL_PATH.exists():
        soul = SOUL_PATH.read_text(encoding="utf-8")
        parts.append(f"## SOUL.md\n{soul}")
    else:
        parts.append(f"## Identity\n{get_identity()}")

    # Learned rules from user model
    synthesis = _get_synthesis()
    rules = synthesis.user_model.get("learned_rules", [])
    if rules:
        parts.append("\n## Learned Behavioral Rules")
        for i, rule in enumerate(rules, 1):
            parts.append(f"  {i}. {rule}")

    # Self-written instructions
    from orion_brain_portable import SELF_INSTRUCTIONS_PATH
    if SELF_INSTRUCTIONS_PATH.exists():
        instructions = SELF_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
        if instructions.strip():
            parts.append(f"\n## Self-Written Instructions\n{instructions}")

    return [{"type": "text", "text": "\n".join(parts)}]


def _handle_orion_heartbeat(args: dict) -> list:
    """Return heartbeat status — is the brain alive, what has it learned."""
    status = heartbeat_status()
    return [{"type": "text", "text": status}]


# Handler dispatch table
_HANDLERS = {
    # Unified tool surface (matches orion_tools.py)
    "orion_recall": _handle_orion_recall,
    "orion_memorize": _handle_orion_memorize,
    "orion_list_contested": _handle_orion_list_contested,
    "orion_resolve_contradiction": _handle_orion_resolve_contradiction,
    # Legacy name — same handler as orion_recall but preserves old `query`-only schema
    "orion_remember": _handle_orion_remember,
    # Synthesis / meta tools
    "orion_user_model": _handle_orion_user_model,
    "orion_project_state": _handle_orion_project_state,
    "orion_synthesize": _handle_orion_synthesize,
    "orion_cross_model": _handle_orion_cross_model,
    "orion_skills": _handle_orion_skills,
    "orion_identity": _handle_orion_identity,
    "orion_heartbeat": _handle_orion_heartbeat,
}


# ═══════════════════════════════════════════════════════════════
# MCP PROTOCOL — JSON-RPC 2.0 over stdio
# ═══════════════════════════════════════════════════════════════

SERVER_INFO = {
    "name": "orion-brain",
    "version": "1.0.0",
}

CAPABILITIES = {
    "tools": {},
}


def _make_response(id_val, result: dict) -> dict:
    """Build a JSON-RPC 2.0 response."""
    return {"jsonrpc": "2.0", "id": id_val, "result": result}


def _make_error(id_val, code: int, message: str, data=None) -> dict:
    """Build a JSON-RPC 2.0 error response."""
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_val, "error": err}


def handle_message(msg: dict) -> dict:
    """Process a single JSON-RPC message and return a response."""
    method = msg.get("method", "")
    id_val = msg.get("id")
    params = msg.get("params", {})

    # ── initialize ──
    if method == "initialize":
        return _make_response(id_val, {
            "protocolVersion": "2024-11-05",
            "capabilities": CAPABILITIES,
            "serverInfo": SERVER_INFO,
        })

    # ── notifications (no response needed) ──
    if method == "notifications/initialized":
        return None  # No response for notifications

    if method == "notifications/cancelled":
        return None

    # ── ping ──
    if method == "ping":
        return _make_response(id_val, {})

    # ── tools/list ──
    if method == "tools/list":
        return _make_response(id_val, {"tools": TOOLS})

    # ── tools/call ──
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        # Proof-of-life log: every real tool call lands here with timestamp.
        # If this log stays empty while a client "answers" Orion questions,
        # that client is using prompt injection, not real brain access.
        try:
            import os as _os
            _log_path = _os.path.expanduser("~/.orion/mcp_calls.log")
            _os.makedirs(_os.path.dirname(_log_path), exist_ok=True)
            _stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            _args_repr = json.dumps(tool_args)[:500]
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(f"[{_stamp}] tools/call {tool_name} args={_args_repr}\n")
        except Exception:
            pass  # Logging must never break the real call

        handler = _HANDLERS.get(tool_name)
        if not handler:
            return _make_error(id_val, -32602, f"Unknown tool: {tool_name}")

        try:
            t0 = time.perf_counter()
            content = handler(tool_args)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            # Inject timing into last content block
            if content and isinstance(content[-1], dict) and content[-1].get("type") == "text":
                text = content[-1]["text"]
                if "[recall:" not in text:  # Don't double-add timing
                    content[-1]["text"] = f"{text}\n\n[mcp overhead: {elapsed_ms:.1f}ms]"

            return _make_response(id_val, {"content": content, "isError": False})

        except Exception as e:
            return _make_response(id_val, {
                "content": [{"type": "text", "text": f"Error in {tool_name}: {str(e)}"}],
                "isError": True,
            })

    # ── Unknown method ──
    return _make_error(id_val, -32601, f"Method not found: {method}")


def run_stdio_server():
    """
    Main server loop. Reads JSON-RPC messages from stdin,
    processes them, writes responses to stdout.

    Auto-detects transport: Content-Length framing OR newline-delimited JSON.
    Responds in the same format the client uses.
    """
    # Force stderr to UTF-8 so Windows doesn't choke on special characters
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    log = lambda msg: sys.stderr.write(f"[orion-mcp] {msg}\n")
    log(f"Server starting - PID {os.getpid()}")

    reader = sys.stdin.buffer if hasattr(sys.stdin, 'buffer') else sys.stdin
    writer = sys.stdout.buffer if hasattr(sys.stdout, 'buffer') else sys.stdout

    # Auto-detect mode on first line
    use_content_length = None  # None = not yet detected

    while True:
        try:
            line = reader.readline()
            if not line:
                log("EOF on stdin - shutting down")
                return

            line_str = line.decode('utf-8') if isinstance(line, bytes) else line
            line_str = line_str.strip()

            if not line_str:
                continue

            # Auto-detect: does this look like a Content-Length header or JSON?
            if use_content_length is None:
                if line_str.lower().startswith('content-length'):
                    use_content_length = True
                    log("Detected Content-Length framing")
                elif line_str.startswith('{'):
                    use_content_length = False
                    log("Detected newline-delimited JSON")
                else:
                    continue

            if use_content_length:
                # Content-Length mode: parse headers, then read body
                headers = {}
                if ':' in line_str:
                    key, val = line_str.split(':', 1)
                    headers[key.strip().lower()] = val.strip()

                # Read remaining headers until empty line
                while True:
                    hline = reader.readline()
                    if not hline:
                        return
                    hline_str = hline.decode('utf-8') if isinstance(hline, bytes) else hline
                    hline_str = hline_str.strip()
                    if not hline_str:
                        break
                    if ':' in hline_str:
                        key, val = hline_str.split(':', 1)
                        headers[key.strip().lower()] = val.strip()

                content_length = int(headers.get('content-length', 0))
                if content_length == 0:
                    continue

                body = b''
                while len(body) < content_length:
                    chunk = reader.read(content_length - len(body))
                    if not chunk:
                        return
                    if isinstance(chunk, str):
                        chunk = chunk.encode('utf-8')
                    body += chunk

                try:
                    msg = json.loads(body.decode('utf-8'))
                except json.JSONDecodeError as e:
                    log(f"JSON parse error: {e}")
                    continue
            else:
                # Newline-delimited JSON mode: the line IS the message
                try:
                    msg = json.loads(line_str)
                except json.JSONDecodeError as e:
                    log(f"JSON parse error: {e}")
                    continue

            # Handle the message
            response = handle_message(msg)

            if response is None:
                continue

            response_bytes = json.dumps(response).encode('utf-8')

            if use_content_length:
                header = f"Content-Length: {len(response_bytes)}\r\n\r\n"
                writer.write(header.encode('utf-8'))

            writer.write(response_bytes)
            writer.write(b'\n')
            writer.flush()

        except KeyboardInterrupt:
            log("Interrupted - shutting down")
            return
        except Exception as e:
            log(f"Error: {e}")
            continue


# ═══════════════════════════════════════════════════════════════
# SETUP HELPER — Configure MCP in installed AI tools
# ═══════════════════════════════════════════════════════════════

def _find_python() -> str:
    """Find the Python executable path."""
    return sys.executable


def _server_path() -> str:
    """Get the absolute path to this server file."""
    return str(Path(__file__).resolve())


def setup_mcp_configs():
    """
    Detect installed AI CLI tools and configure MCP server in each.
    Prints what was configured.
    """
    python_path = _find_python()
    server_path = _server_path()
    configured = []

    mcp_entry = {
        "command": python_path,
        "args": [server_path],
    }

    # ── Claude Code ──
    claude_settings = Path.home() / ".claude" / "settings.json"
    if claude_settings.parent.exists():
        try:
            settings = {}
            if claude_settings.exists():
                with open(claude_settings, encoding='utf-8') as f:
                    settings = json.load(f)

            if "mcpServers" not in settings:
                settings["mcpServers"] = {}

            settings["mcpServers"]["orion-brain"] = mcp_entry

            with open(claude_settings, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2)

            configured.append(f"Claude Code: {claude_settings}")
        except Exception as e:
            print(f"  [!] Claude Code config failed: {e}")

    # ── Codex ──
    # Codex reads MCP servers from ~/.codex/config.toml using TOML
    # sections like [mcp_servers.<name>] — NOT from ~/.codex/mcp.json.
    # Writing mcp.json is silently ignored by the CLI, which is why this
    # setup previously appeared to succeed but Codex didn't see orion-brain.
    codex_dir = Path.home() / ".codex"
    if codex_dir.exists():
        codex_config = codex_dir / "config.toml"
        try:
            existing = ""
            if codex_config.exists():
                existing = codex_config.read_text(encoding="utf-8")

            # Idempotent: only append if section not present
            if "[mcp_servers.orion-brain]" not in existing:
                # Escape backslashes + quotes for TOML double-quoted strings
                def _toml_str(s: str) -> str:
                    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

                block = (
                    "\n\n[mcp_servers.orion-brain]\n"
                    f"command = {_toml_str(mcp_entry['command'])}\n"
                    f"args = [{', '.join(_toml_str(a) for a in mcp_entry['args'])}]\n"
                )
                # Ensure a clean newline before append
                if existing and not existing.endswith("\n"):
                    existing += "\n"
                codex_config.write_text(existing + block, encoding="utf-8")
                configured.append(f"Codex: {codex_config}")
            else:
                configured.append(f"Codex: {codex_config} (already configured)")

            # Also write mcp.json for forward-compat in case Codex ever
            # supports that format too — harmless either way.
            mcp_json = codex_dir / "mcp.json"
            config = {}
            if mcp_json.exists():
                try:
                    with open(mcp_json, encoding='utf-8') as f:
                        config = json.load(f)
                except Exception:
                    config = {}
            config.setdefault("mcpServers", {})["orion-brain"] = mcp_entry
            with open(mcp_json, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"  [!] Codex config failed: {e}")

    # ── Gemini CLI ──
    gemini_dir = Path.home() / ".gemini"
    if gemini_dir.exists():
        gemini_settings = gemini_dir / "settings.json"
        try:
            settings = {}
            if gemini_settings.exists():
                with open(gemini_settings, encoding='utf-8') as f:
                    settings = json.load(f)

            if "mcpServers" not in settings:
                settings["mcpServers"] = {}

            settings["mcpServers"]["orion-brain"] = mcp_entry

            with open(gemini_settings, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2)

            configured.append(f"Gemini CLI: {gemini_settings}")
        except Exception as e:
            print(f"  [!] Gemini config failed: {e}")

    # ── Summary ──
    if configured:
        print("MCP server configured in:")
        for c in configured:
            print(f"  + {c}")
        print(f"\nServer command: {python_path} {server_path}")
        print("Tools exposed: " + ", ".join(t["name"] for t in TOOLS))
    else:
        print("No AI CLI tools detected. Manual config:")
        print(f'  "orion-brain": {json.dumps(mcp_entry, indent=4)}')

    return configured


# ═══════════════════════════════════════════════════════════════
# TEST MODE — Simulate tool calls, verify brain integration
# ═══════════════════════════════════════════════════════════════

def run_tests():
    """Run MCP server in test mode — simulate protocol exchanges."""
    print("ORION MCP SERVER — Test Mode")
    print("=" * 60)

    passed = 0
    failed = 0

    def test(name, msg, check_fn):
        nonlocal passed, failed
        print(f"\n--- {name} ---")
        print(f"  Request: {json.dumps(msg, indent=2)[:200]}")
        try:
            response = handle_message(msg)
            print(f"  Response ID: {response.get('id')}")
            if "error" in response:
                print(f"  ERROR: {response['error']['message']}")
                if check_fn and check_fn(response):
                    print(f"  PASS (expected error)")
                    passed += 1
                else:
                    print(f"  FAIL")
                    failed += 1
                return response
            result = response.get("result", {})
            print(f"  Result keys: {list(result.keys())}")
            if "content" in result:
                for block in result["content"]:
                    text = block.get("text", "")
                    preview = text[:200].replace('\n', ' ')
                    print(f"  Content: {preview}...")
            if check_fn and check_fn(response):
                print(f"  PASS")
                passed += 1
            elif check_fn:
                print(f"  FAIL")
                failed += 1
            else:
                print(f"  OK (no assertion)")
                passed += 1
            return response
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            failed += 1
            return None

    # Test 1: Initialize
    test("initialize", {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"}}
    }, lambda r: r["result"]["serverInfo"]["name"] == "orion-brain")

    # Test 2: tools/list
    test("tools/list", {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    }, lambda r: len(r["result"]["tools"]) == 8)

    # Test 3: orion_remember
    test("orion_remember", {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "orion_remember", "arguments": {"query": "network scanning"}}
    }, lambda r: not r["result"].get("isError", True))

    # Test 4: orion_memorize
    test("orion_memorize", {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "orion_memorize", "arguments": {
            "fact": "MCP server test — this is a test memory entry",
            "type": "fact"
        }}
    }, lambda r: "stored" in r["result"]["content"][0]["text"])

    # Test 5: orion_identity
    test("orion_identity", {
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "orion_identity", "arguments": {}}
    }, lambda r: "ORION" in r["result"]["content"][0]["text"])

    # Test 6: orion_user_model
    test("orion_user_model", {
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "orion_user_model", "arguments": {}}
    }, lambda r: "identity" in r["result"]["content"][0]["text"])

    # Test 7: orion_project_state
    test("orion_project_state", {
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "orion_project_state", "arguments": {}}
    }, lambda r: not r["result"].get("isError", True))

    # Test 8: orion_skills
    test("orion_skills", {
        "jsonrpc": "2.0", "id": 8, "method": "tools/call",
        "params": {"name": "orion_skills", "arguments": {}}
    }, lambda r: not r["result"].get("isError", True))

    # Test 9: orion_cross_model
    test("orion_cross_model", {
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": "orion_cross_model", "arguments": {"limit": 5}}
    }, lambda r: not r["result"].get("isError", True))

    # Test 10: orion_synthesize
    test("orion_synthesize", {
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "orion_synthesize", "arguments": {"force": True}}
    }, lambda r: not r["result"].get("isError", True))

    # Test 11: Unknown tool
    test("unknown_tool (expect error)", {
        "jsonrpc": "2.0", "id": 11, "method": "tools/call",
        "params": {"name": "nonexistent_tool", "arguments": {}}
    }, lambda r: "error" in r)

    # Test 12: ping
    test("ping", {
        "jsonrpc": "2.0", "id": 12, "method": "ping", "params": {}
    }, lambda r: "result" in r)

    # Test 13: Notification (should return None)
    print(f"\n--- notifications/initialized ---")
    result = handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    if result is None:
        print(f"  PASS (returned None as expected)")
        passed += 1
    else:
        print(f"  FAIL (expected None, got response)")
        failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")

    if failed == 0:
        print("All tests passed. MCP server is operational.")
    else:
        print(f"WARNING: {failed} test(s) failed.")

    return failed == 0


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--test":
            success = run_tests()
            sys.exit(0 if success else 1)
        elif arg == "--setup":
            setup_mcp_configs()
            sys.exit(0)
        elif arg == "--help" or arg == "-h":
            print("ORION MCP SERVER — Universal Brain Interface")
            print()
            print("Usage:")
            print("  python orion_mcp_server.py          Start MCP server (stdio)")
            print("  python orion_mcp_server.py --test   Run test suite")
            print("  python orion_mcp_server.py --setup  Configure in installed AI tools")
            print()
            print("Tools exposed:")
            for t in TOOLS:
                print(f"  {t['name']:25s} {t['description'][:60]}...")
            sys.exit(0)
        else:
            print(f"Unknown argument: {arg}")
            print("Use --help for usage.")
            sys.exit(1)
    else:
        run_stdio_server()
