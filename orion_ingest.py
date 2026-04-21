#!/usr/bin/env python3
"""
ORION INGEST - Absorb existing AI history into the brain at install.

On first run of Orion, this pipeline reads every AI conversation history
on the machine (Claude Code, Codex, Gemini, Letta, Ollama, Orion's own
logs, context files, knowledge base) and populates the graph memory so
the user's new Orion does not start from zero — it already knows what
the user has told previous AIs.

Two-speed design, honoring the ambient-not-invoked principle:

  Pass 1 (instant):  heuristic fact extraction via regex + patterns.
                     Runs in seconds. Covers explicit claims like
                     "my favorite X is Y" / "I prefer X" / "my X is Y".
                     This is what the wizard shows finishing immediately.

  Pass 2 (ambient):  local-model deep extraction over time. Runs as a
                     background job — walks segments, asks the local
                     model to list factual claims, writes each as a
                     graph node. Brain deepens silently over the next
                     hour without the user doing anything.

All writes flow through GraphMemory.store() — the same path orion chat
and MCP use. Dedup + contradiction detection + temporal decay apply
automatically. Re-running ingest is safe; it re-confirms facts rather
than duplicating them.

Usage:
    orion ingest                     # run heuristic pass + queue deep pass
    orion ingest --deep-only         # skip heuristic, just run LLM pass
    orion ingest --sources claude codex gemini    # limit sources
    orion ingest --dry-run           # show what would be stored, don't write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

import orion_brain_portable as obp  # noqa: E402


# ----------------------------------------------------------------
# Source registry - maps nice names to the portable-brain readers
# ----------------------------------------------------------------

SOURCES = {
    "claude":        obp._read_claude_source,
    "codex":         obp._read_codex_source,
    "gemini":        obp._read_gemini_source,
    "letta":         obp._read_letta_source,
    "ollama":        obp._read_ollama_source,
    "orion":         obp._read_orion_conversations,
    "memory-files":  obp._read_memory_files,
    "knowledge":     obp._read_knowledge_docs,
    "context":       obp._read_context_files,
}


# ----------------------------------------------------------------
# Heuristic fact extractor - fast, runs on install, covers obvious claims
# ----------------------------------------------------------------

# Patterns ordered from most specific to most general. Each produces a
# (fact, inferred_tags, inferred_type) tuple when it matches.
_PATTERNS: list[tuple[re.Pattern, str, list[str], str]] = [
    (re.compile(r"\bmy (?:favorite |favourite )?(\w+) is ([^.!?\n]+)", re.I),
     "{0} is {1}", ["preference"], "preference"),
    (re.compile(r"\bI prefer ([^.!?\n]+)", re.I),
     "prefers {0}", ["preference"], "preference"),
    (re.compile(r"\bI (?:live|am based) in ([^.!?\n]+)", re.I),
     "lives in {0}", ["location", "identity"], "identity"),
    (re.compile(r"\bI work (?:at|for) ([^.!?\n]+)", re.I),
     "works at {0}", ["work", "identity"], "identity"),
    (re.compile(r"\bmy (?:company|startup|product|project) (?:is )?(?:called )?([A-Z][^.!?\n]+)", re.I),
     "has a project: {0}", ["project"], "project"),
    (re.compile(r"\bI own (?:a |an )?([^.!?\n]+)", re.I),
     "owns {0}", ["ownership", "hardware"], "hardware"),
    (re.compile(r"\b(?:my|our) (?:phone|number) is ([\d\-\(\)\s\+]+)", re.I),
     "phone is {0}", ["phone", "contact"], "preference"),
    (re.compile(r"\bmy email is ([\w.\-]+@[\w.\-]+)", re.I),
     "email is {0}", ["email", "contact"], "preference"),
    (re.compile(r"\bremember (?:that )?([^.!?\n]{10,200})", re.I),
     "{0}", ["explicit-memory"], "fact"),
    (re.compile(r"\bsave (?:this|that) (?:fact|note)?:?\s*([^.!?\n]{10,200})", re.I),
     "{0}", ["explicit-memory"], "fact"),
]


def heuristic_extract(text: str) -> list[tuple[str, list[str], str]]:
    """Return list of (content, tags, type) tuples extracted from text."""
    results: list[tuple[str, list[str], str]] = []
    if not text or len(text) < 8:
        return results
    for pat, template, tags, node_type in _PATTERNS:
        for m in pat.finditer(text):
            try:
                groups = [g.strip() for g in m.groups() if g]
                if not groups:
                    continue
                content = template.format(*groups).strip()
                if len(content) < 5 or len(content) > 400:
                    continue
                # Lowercase trivial-content filter
                if content.lower() in {"yes", "no", "ok", "sure", "thanks"}:
                    continue
                results.append((content, tags, node_type))
            except (IndexError, KeyError):
                continue
    return results


# ----------------------------------------------------------------
# Deep extractor - uses local model, much slower, higher quality
# ----------------------------------------------------------------

_DEEP_PROMPT = """From the following conversation segment, list every durable factual claim the USER made about themselves, their work, their preferences, their devices, their projects, or their decisions. One claim per line. No intro, no commentary. If the segment contains no durable facts about the user, output exactly: NONE.

Rules:
- Only claims the USER stated as fact. Not opinions, not questions, not assistant replies.
- Each claim must be a short self-contained sentence.
- Skip greetings, thanks, chit-chat.
- Skip facts that are only true for a moment ("I'm tired right now").

Conversation segment:
{segment}

Durable facts from this segment:"""


def deep_extract(segments: list[str], model: str, endpoint: str) -> list[tuple[str, list[str], str]]:
    """Call the local model to extract facts from conversation segments."""
    try:
        from openai import OpenAI
    except ImportError:
        print("[ingest:deep] openai package not installed - skipping deep pass", file=sys.stderr)
        return []

    client = OpenAI(base_url=endpoint, api_key="ollama")
    results: list[tuple[str, list[str], str]] = []

    for i, segment in enumerate(segments):
        if not segment or len(segment) < 40:
            continue
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": _DEEP_PROMPT.format(segment=segment[:3000])}],
                temperature=0.2,
                max_tokens=400,
            )
            out = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"[ingest:deep] segment {i} failed: {e}", file=sys.stderr)
            continue

        if out.upper().startswith("NONE"):
            continue

        for line in out.splitlines():
            line = line.strip().lstrip("-*0123456789.) ").strip()
            if len(line) < 10 or len(line) > 400:
                continue
            tags = _infer_tags(line)
            node_type = _infer_type(line, tags)
            results.append((line, tags, node_type))

    return results


def _infer_tags(text: str) -> list[str]:
    """Cheap tag inference from keywords."""
    t = text.lower()
    tags: list[str] = []
    if any(w in t for w in ["favorite", "prefer", "like", "love", "hate"]):
        tags.append("preference")
    if any(w in t for w in ["email", "phone", "contact", "address"]):
        tags.append("contact")
    if any(w in t for w in ["work", "job", "company", "employer"]):
        tags.append("work")
    if any(w in t for w in ["project", "startup", "product", "app"]):
        tags.append("project")
    if any(w in t for w in ["wife", "husband", "kid", "child", "family", "friend", "partner"]):
        tags.append("relationship")
    if any(w in t for w in ["laptop", "pc", "mac", "phone", "iphone", "android", "device"]):
        tags.append("hardware")
    if any(w in t for w in ["ip", "server", "network", "router", "wifi"]):
        tags.append("network")
    return tags or ["general"]


def _infer_type(text: str, tags: list[str]) -> str:
    if "preference" in tags:
        return "preference"
    if "hardware" in tags:
        return "hardware"
    if "network" in tags:
        return "network"
    if "project" in tags:
        return "project"
    if "work" in tags or "relationship" in tags or "contact" in tags:
        return "identity"
    return "fact"


# ----------------------------------------------------------------
# Main pipeline
# ----------------------------------------------------------------

def _user_segments(messages: list[dict]) -> list[str]:
    """Keep user-authored text only - the source of durable claims."""
    segs: list[str] = []
    for m in messages:
        if m.get("role") not in ("user", "context"):
            continue
        text = m.get("text") or ""
        if text and len(text) > 10:
            segs.append(text)
    return segs


def run(
    sources: Iterable[str] | None = None,
    deep: bool = False,
    deep_only: bool = False,
    dry_run: bool = False,
    max_per_source: int = 1000,
    model: str = "orion-qwen3",
    endpoint: str = "http://localhost:11434/v1",
    progress=None,
) -> dict:
    """Run the ingest pipeline. Returns a report dict."""
    selected = list(sources) if sources else list(SOURCES.keys())
    report = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sources": {},
        "heuristic_facts": 0,
        "deep_facts": 0,
        "written": 0,
        "skipped_dup": 0,
        "contested": 0,
        "duration_ms": 0,
        "dry_run": dry_run,
    }
    t0 = time.perf_counter()

    # Phase 1 - read all selected sources
    all_messages: list[dict] = []
    for name in selected:
        reader = SOURCES.get(name)
        if not reader:
            report["sources"][name] = "unknown"
            continue
        try:
            msgs = reader(max_per_source)
            report["sources"][name] = len(msgs)
            all_messages.extend(msgs)
            if progress:
                progress(f"read {len(msgs)} messages from {name}")
        except Exception as e:
            report["sources"][name] = f"error: {e}"

    report["total_messages"] = len(all_messages)
    segments = _user_segments(all_messages)

    # Phase 2 - heuristic pass
    extracted: list[tuple[str, list[str], str]] = []
    if not deep_only:
        if progress:
            progress(f"heuristic pass on {len(segments)} user segments...")
        for seg in segments:
            extracted.extend(heuristic_extract(seg))
        report["heuristic_facts"] = len(extracted)

    # Phase 3 - deep pass (optional)
    if deep or deep_only:
        if progress:
            progress(f"deep pass via {model} - this may take a while...")
        deep_results = deep_extract(segments, model=model, endpoint=endpoint)
        extracted.extend(deep_results)
        report["deep_facts"] = len(deep_results)

    # Phase 4 - write to graph
    if dry_run:
        report["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        report["sample"] = extracted[:20]
        return report

    graph = obp.GraphMemory()
    if obp.GRAPH_PATH.exists():
        graph.load(obp.GRAPH_PATH)

    written = 0
    contested = 0
    for content, tags, node_type in extracted:
        # Dedup via exact-content check (store() also handles via contradiction,
        # but avoiding the write cuts overhead when lots of segments repeat)
        existing = graph.find_by_content(content)
        if existing:
            # Touch last_confirmed_at so repeated occurrences re-confirm the fact
            for nid, _ in existing:
                graph.confirm(nid)
            report["skipped_dup"] += 1
            continue
        nid = graph.store(content=content, node_type=node_type, tags=tags)
        written += 1
        if graph.nodes[nid].get("contested_with"):
            contested += 1

    graph.save()
    report["written"] = written
    report["contested"] = contested
    report["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    if progress:
        progress(f"wrote {written} new facts ({contested} contested, {report['skipped_dup']} re-confirmed)")
    return report


def _cli():
    p = argparse.ArgumentParser(prog="orion ingest",
                                description="Absorb existing AI history into the brain.")
    p.add_argument("--sources", nargs="+", choices=list(SOURCES.keys()),
                   help="Limit to specific sources (default: all).")
    p.add_argument("--deep", action="store_true",
                   help="Run local-model deep extraction after heuristic pass.")
    p.add_argument("--deep-only", action="store_true",
                   help="Skip heuristic, only run deep.")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be stored, don't write.")
    p.add_argument("--max-per-source", type=int, default=1000)
    p.add_argument("--model", default="orion-qwen3",
                   help="Local model for deep extraction.")
    p.add_argument("--endpoint", default="http://localhost:11434/v1")
    args = p.parse_args()

    print("ORION INGEST - absorbing your AI history into the brain")
    print("=" * 60)

    report = run(
        sources=args.sources,
        deep=args.deep,
        deep_only=args.deep_only,
        dry_run=args.dry_run,
        max_per_source=args.max_per_source,
        model=args.model,
        endpoint=args.endpoint,
        progress=lambda msg: print(f"  . {msg}"),
    )

    print()
    print("Source read counts:")
    for name, count in report["sources"].items():
        print(f"  {name:16}{count}")
    print()
    print(f"Total user segments read: {report.get('total_messages', 0)}")
    print(f"Heuristic facts:          {report['heuristic_facts']}")
    print(f"Deep facts:               {report['deep_facts']}")
    print(f"Written to graph:         {report['written']}")
    print(f"Re-confirmed duplicates:  {report['skipped_dup']}")
    print(f"Contested on write:       {report['contested']}")
    print(f"Duration:                 {report['duration_ms']} ms")
    if report.get("dry_run") and report.get("sample"):
        print()
        print("Sample extractions (dry run - not written):")
        for content, tags, node_type in report["sample"]:
            print(f"  [{node_type}] {content}  ({', '.join(tags)})")
    return 0


if __name__ == "__main__":
    sys.exit(_cli() or 0)
