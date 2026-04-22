#!/usr/bin/env python3
"""
ORION TOOLS - Layer 3 of the universal brain interface.

Exposes the Orion brain as OpenAI-format function-calling tools so any
local or remote model that emits tool_calls can actively query memory,
store new facts, and surface contradictions instead of just receiving
pre-injected context.

Used by:
- orion_tool_chat.py    reference tool-calling loop
- orion_mcp_server.py   maps these same operations onto MCP
- future LiteLLM proxy integration for automatic Layer 3

The tool schemas follow the OpenAI chat.completions tools spec and work
with any provider LiteLLM supports that implements function calling:
Ollama (qwen3, llama3.1, mistral-nemo, deepseek-r1), OpenAI, Anthropic,
Gemini, etc.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

import orion_brain_portable as obp  # noqa: E402


# ----------------------------------------------------------------
# Singleton graph memory, loaded once per process
# ----------------------------------------------------------------

_graph: obp.GraphMemory | None = None


def _get_graph() -> obp.GraphMemory:
    global _graph
    if _graph is None:
        _graph = obp.GraphMemory()
        if obp.GRAPH_PATH.exists():
            _graph.load(obp.GRAPH_PATH)
    return _graph


# ----------------------------------------------------------------
# Tool schemas (OpenAI chat.completions tools format)
# ----------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "orion_recall",
            "description": (
                "Search Orion's memory for facts relevant to a query. "
                "Use this ANY time you need information about the user, "
                "their devices, projects, preferences, or past conversations. "
                "Returns results ranked by decayed confidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language search query",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orion_memorize",
            "description": (
                "Save a new fact to Orion's long-term memory. Use when the "
                "user tells you something worth remembering across sessions "
                "(preferences, decisions, device details, state changes). "
                "If a prior fact contradicts this one, both will be flagged "
                "for the user to resolve."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The fact, stated as a clear sentence",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Short tags for indexed recall (e.g., ['phone','contact'])",
                    },
                    "type": {
                        "type": "string",
                        "description": (
                            "Node type controls decay half-life. One of: "
                            "identity, preference, hardware, person, skill, "
                            "fact, network, service, project, task, ephemeral."
                        ),
                        "default": "fact",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orion_list_contested",
            "description": (
                "List memories that have unresolved contradictions (two facts "
                "about the same subject that disagree). Use this when the user "
                "asks 'what's conflicted' or when you suspect stale info."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orion_resolve_contradiction",
            "description": (
                "Commit a user's resolution to a contradiction. Winner keeps "
                "confidence; losers are archived but not deleted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "winner_id": {
                        "type": "integer",
                        "description": "The node id of the fact that wins",
                    },
                    "loser_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Node ids to archive as superseded",
                    },
                },
                "required": ["winner_id", "loser_ids"],
            },
        },
    },
]


# ----------------------------------------------------------------
# Executor — takes a tool_call from any provider, runs it, returns JSON string
# ----------------------------------------------------------------

def execute_tool(name: str, arguments: dict[str, Any] | str) -> str:
    """Run a tool and return a string result (safe for tool role messages)."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"ERROR: invalid JSON arguments: {arguments!r}"

    g = _get_graph()

    if name == "orion_recall":
        nodes = g.recall(
            query=arguments.get("query", ""),
            limit=int(arguments.get("limit", 5)),
        )
        if not nodes:
            return "No relevant memories found."
        lines = []
        for n in nodes:
            flag = " [contested]" if n.get("contested_with") else ""
            lines.append(f"- {n['content']}{flag}")
        return "\n".join(lines)

    if name == "orion_memorize":
        content = arguments.get("content", "").strip()
        if not content:
            return "ERROR: content required"

        raw_type = arguments.get("type", "fact")
        raw_tags = list(arguments.get("tags", []) or [])

        # --- Ontology discipline (from research round-3 ontologist) ---
        # Lazy import so this tool still works if orion_ontology is unavailable
        try:
            import orion_ontology as ont
            existing_types = {n.get("type", "?") for n in g.nodes.values()}
            accepted, reason = ont.validate_node_type(raw_type, existing_types=existing_types)
            if not accepted:
                # Auto-demote to closest canonical type + preserve subtype as tag
                # (Innovation answer: cap is not a wall, it's a migration signal)
                demoted_type = "fact"  # safest default
                raw_tags = list(set(raw_tags) | {ont.as_subtype_tag(raw_type)})
                note = (
                    f"[ontology: type '{raw_type}' rejected ({reason}); "
                    f"auto-demoted to '{demoted_type}' + tag '{ont.as_subtype_tag(raw_type)}']"
                )
                raw_type = demoted_type
            else:
                note = ""
        except Exception:
            ont = None
            note = ""

        # --- Entity-as-entity fast path ---
        # If type is entity, route through resolve_entity so the bias-toward-NEW
        # + alias-merging + last_seen-update discipline runs.
        if ont and raw_type == ont.ENTITY_TYPE:
            try:
                summary = next(
                    (t[len("summary:"):] for t in raw_tags if isinstance(t, str) and t.startswith("summary:")),
                    "",
                )
                extra_aliases = [t[len("alias:"):] for t in raw_tags
                                 if isinstance(t, str) and t.startswith("alias:")]
                nid = ont.resolve_entity(g, content, summary=summary, extra_aliases=extra_aliases)
                try:
                    g.save()
                except Exception as e:
                    return f"Stored entity as node {nid} (persist failed: {e})"
                n = g.nodes[nid]
                return (
                    f"Resolved entity to node {nid}. "
                    f"aliases={len(n.get('aliases', []))}, last_seen updated. {note}"
                ).strip()
            except Exception as e:
                # Fall through to generic store if entity-resolution breaks
                note = (note + f" [entity-resolve fallback: {e.__class__.__name__}]").strip()

        # --- Standard store path (same as before) ---
        nid = g.store(
            content=content,
            node_type=raw_type,
            tags=raw_tags,
        )
        try:
            g.save()
        except Exception as e:
            return f"Stored as node {nid} (but failed to persist: {e}){(' ' + note) if note else ''}"

        contested = g.nodes[nid].get("contested_with")
        if contested:
            return (
                f"Stored as node {nid}. Contradicts existing nodes: "
                f"{contested}. Surface for user resolution.{(' ' + note) if note else ''}"
            )
        return f"Stored as node {nid}.{(' ' + note) if note else ''}"

    if name == "orion_list_contested":
        contested = g.list_contested()
        if not contested:
            return "No contested memories."
        lines = [
            f"- id={c['id']}: {c['content']}  (contested_with={c['contested_with']})"
            for c in contested
        ]
        return "\n".join(lines)

    if name == "orion_resolve_contradiction":
        winner = int(arguments["winner_id"])
        losers = [int(x) for x in arguments.get("loser_ids", [])]
        ok = g.resolve_contradiction(winner, losers)
        if not ok:
            return f"ERROR: winner node {winner} not found."
        try:
            g.save()
        except Exception as e:
            return f"Resolved but persist failed: {e}"
        return f"Resolved. Winner: {winner}. Archived: {losers}."

    return f"ERROR: unknown tool {name!r}"


if __name__ == "__main__":
    # Smoke-test the executor
    print("=== orion_recall ===")
    print(execute_tool("orion_recall", {"query": "phone", "limit": 3}))
    print()
    print("=== orion_list_contested ===")
    print(execute_tool("orion_list_contested", {}))
    print()
    print("=== tool schemas ===")
    print(f"exposed {len(TOOL_SCHEMAS)} tools: {[t['function']['name'] for t in TOOL_SCHEMAS]}")
