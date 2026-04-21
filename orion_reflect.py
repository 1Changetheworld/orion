#!/usr/bin/env python3
"""
ORION REFLECT - Reflection as a brain capability.

A being does not poll. A being reflects.

When Orion has a reason to look back on recent context — waking up for
a new session, finishing a conversation, detecting a conflict, or being
asked to — it reviews what happened, reasons about what is durable vs
ephemeral, and integrates selectively into graph memory.

The intelligence lives in the decision of what to keep, made by Orion's
own model at a moment Orion chooses. There is no watcher, no cron, no
background job. Reflection fires on semantic events, not clock events.

This module exposes:

    reflect(messages, reason, model=..., endpoint=..., dry_run=...)
        Review a window of messages, extract durable facts, write them
        through GraphMemory.store() with full dedup + contradiction
        handling. Returns a ReflectionReport.

    should_reflect_on_wake()
        Called by orion chat on launch. Returns True if enough time has
        passed since the last reflection that reviewing would be useful.
        Stored gap, not a timer.

Integration points (all semantic, not scheduled):
    - orion chat startup: reflect on conversations since last wake
    - orion chat /reflect command: explicit user invitation
    - orion chat /exit: reflect on the session just ending
    - Future: proxy hook invokes reflect() when a conversation ends,
      chosen by content heuristics (meaningful exchange), not per-call
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

import orion_brain_portable as obp  # noqa: E402


# ----------------------------------------------------------------
# Last reflection marker - used for semantic wake-up decision
# ----------------------------------------------------------------

_LAST_REFLECTION_PATH = obp.SOUL_PATH.parent.parent / "brain" / "last_reflection.json"


def _load_last_reflection() -> dict:
    if not _LAST_REFLECTION_PATH.exists():
        return {}
    try:
        return json.loads(_LAST_REFLECTION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_last_reflection(record: dict) -> None:
    _LAST_REFLECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        _LAST_REFLECTION_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[reflect] persist failed: {e}", file=sys.stderr)


def should_reflect_on_wake(min_gap_hours: float = 1.0) -> bool:
    """Semantic wake-up decision: was the last reflection long enough ago?

    This is NOT a timer. It's Orion deciding, when it wakes up, whether
    enough has changed to be worth reviewing. Same way a person deciding
    to check email in the morning is not a cron job — the act of waking
    is the semantic event; the decision to check is judgment.
    """
    rec = _load_last_reflection()
    last = rec.get("timestamp", 0)
    if last <= 0:
        return True  # never reflected - should absolutely reflect on wake
    gap_hours = (time.time() - last) / 3600.0
    return gap_hours >= min_gap_hours


# ----------------------------------------------------------------
# The reflection prompt - the heart of the capability
# ----------------------------------------------------------------

_REFLECT_PROMPT = """You are ORION reflecting on recent context. Your task is to decide what to integrate into long-term memory.

Review the exchanges below. For each durable claim the user made about themselves, their work, their preferences, their devices, their projects, their decisions, or their relationships, output one line.

Rules for what counts:
- Durable: true beyond this moment (preferences, identity, plans, ownership)
- Specific: concrete enough to be useful later ("my laptop is an RTX 4070" not "I have a laptop")
- Stated by the user: not opinions you inferred, not assistant replies

Rules for what to skip:
- Ephemeral states ("I'm tired right now", "hold on a second")
- Questions the user asked
- Greetings, thanks, chit-chat
- Anything the assistant said (even if true)
- Anything already obvious from prior memory

Output format (one per line, nothing else):
  TYPE | TAG1,TAG2 | the durable fact sentence

TYPE is one of: identity, preference, hardware, person, skill, fact, network, service, project, task.

If nothing durable appears in this context, output exactly: NOTHING

---
Context (most recent last):
{context}
---

Durable integrations:"""


def _format_messages_for_prompt(messages: list[dict], max_chars: int = 8000) -> str:
    """Render messages into the prompt context block, truncating oldest first."""
    lines = []
    for m in messages:
        role = m.get("role", "?")
        text = m.get("text") or m.get("content") or ""
        if not text:
            continue
        if isinstance(text, list):
            text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
        lines.append(f"[{role}] {text[:2000]}")

    joined = "\n".join(lines)
    if len(joined) > max_chars:
        # Keep the most recent portion
        joined = "... (earlier context elided)\n" + joined[-max_chars:]
    return joined


def _parse_reflection_output(raw: str) -> list[tuple[str, list[str], str]]:
    results: list[tuple[str, list[str], str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.upper().startswith("NOTHING"):
            continue
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) != 3:
            continue
        node_type, tag_str, content = parts
        node_type = node_type.lower().strip() or "fact"
        tags = [t.strip() for t in tag_str.split(",") if t.strip()]
        if not tags:
            tags = ["general"]
        if len(content) < 5 or len(content) > 400:
            continue
        results.append((content, tags, node_type))
    return results


# ----------------------------------------------------------------
# Reflect - the capability
# ----------------------------------------------------------------

def reflect(
    messages: list[dict],
    reason: str = "explicit",
    model: str = "orion-qwen3",
    endpoint: str = "http://localhost:11434/v1",
    api_key: str = "ollama",
    dry_run: bool = False,
) -> dict:
    """Orion reflects on a window of messages and integrates durable facts.

    Args:
        messages: list of {"role": "user"|"assistant", "text"|"content": str}
        reason: semantic trigger — "wake", "session-end", "explicit",
                "conflict-detected", "proxy-post"
        model: local model to think with
        endpoint: OpenAI-compatible API
        dry_run: do not write to graph

    Returns:
        {
            "reason": str,
            "candidate_count": int,
            "written": int,
            "skipped_dup": int,
            "contested": int,
            "duration_ms": int,
            "narrative": str,       # what Orion concluded
            "rejected": []          # empty in heuristic-less reflection
        }
    """
    t0 = time.perf_counter()
    report = {
        "reason": reason,
        "candidate_count": 0,
        "written": 0,
        "skipped_dup": 0,
        "contested": 0,
        "duration_ms": 0,
        "narrative": "",
        "integrations": [],
    }

    if not messages:
        report["narrative"] = "Nothing to reflect on — no recent context."
        report["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return report

    try:
        from openai import OpenAI
    except ImportError:
        report["narrative"] = "openai package not available; cannot reflect."
        report["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return report

    client = OpenAI(base_url=endpoint, api_key=api_key)
    context = _format_messages_for_prompt(messages)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": obp.get_identity()},
                {"role": "user", "content": _REFLECT_PROMPT.format(context=context)},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        report["narrative"] = f"Reflection model call failed: {e}"
        report["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return report

    candidates = _parse_reflection_output(raw)
    report["candidate_count"] = len(candidates)

    if dry_run:
        report["integrations"] = candidates
        report["narrative"] = (
            f"Dry run: Orion found {len(candidates)} durable facts worth integrating."
        )
        report["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return report

    # Write through unified GraphMemory - contradiction detection + dedup apply
    graph = obp.GraphMemory()
    if obp.GRAPH_PATH.exists():
        graph.load(obp.GRAPH_PATH)

    integrations = []
    for content, tags, node_type in candidates:
        existing = graph.find_by_content(content)
        if existing:
            for nid, _ in existing:
                graph.confirm(nid)
            report["skipped_dup"] += 1
            continue
        nid = graph.store(content=content, node_type=node_type, tags=tags)
        report["written"] += 1
        node = graph.nodes[nid]
        if node.get("contested_with"):
            report["contested"] += 1
        integrations.append({
            "id": nid,
            "type": node_type,
            "tags": tags,
            "content": content,
            "contested_with": node.get("contested_with") or [],
        })
    graph.save()

    report["integrations"] = integrations
    report["narrative"] = (
        f"Orion reviewed {len(messages)} recent exchanges on '{reason}', "
        f"identified {len(candidates)} durable facts, integrated {report['written']} "
        f"({report['contested']} contested, {report['skipped_dup']} re-confirmed)."
    )
    report["duration_ms"] = int((time.perf_counter() - t0) * 1000)

    _save_last_reflection({
        "timestamp": time.time(),
        "reason": reason,
        "written": report["written"],
        "narrative": report["narrative"],
    })

    return report


if __name__ == "__main__":
    # Self-test on Orion's own recent conversation log
    print("=== Reflection self-test — orion log ===")
    msgs = obp._read_orion_conversations(limit=30)
    # Normalize for reflect's expected shape
    normalized = []
    for m in msgs[-12:]:
        text = m.get("text") or ""
        role = m.get("role") or "user"
        if role not in ("user", "assistant"):
            role = "user"
        normalized.append({"role": role, "text": text})

    report = reflect(normalized, reason="self-test", dry_run=True)
    print(f"Reason:          {report['reason']}")
    print(f"Candidate count: {report['candidate_count']}")
    print(f"Written:         {report['written']} (dry-run, so 0 expected)")
    print(f"Narrative:       {report['narrative']}")
    print()
    print("Candidate integrations:")
    for content, tags, node_type in report.get("integrations", [])[:10]:
        print(f"  [{node_type}] {content}  ({','.join(tags)})")
