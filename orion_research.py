#!/usr/bin/env python3
"""
orion_research — persona-driven research agent.

One module. One agent instance per (persona, topic). Each instance runs a
small multi-round loop against a fuel that has web access (Claude CLI by
default — web search built in), and persists findings as structured data
Orion can recall later.

Personas are data, not code. Adding one is a dict entry.

Usage:
    python orion_research.py --persona physicist \
        --topic "quantum coherence and persistent memory in AI"

    python orion_research.py --persona foreign-ai \
        --topic "non-Western AI approaches beyond transformer scaling" \
        --rounds 3

    python orion_research.py --team   # run the three default personas

Storage:
    ~/.orion/brain/research/<YYYY-MM-DD>/<persona>__<slug>.md   (human report)
    ~/.orion/brain/research/<YYYY-MM-DD>/<persona>__<slug>.jsonl (raw findings)
    Each exchange is also logged via obp.log_conversation for the ambient
    brain, so the next wake-up reflection can pick up research context.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

import orion_brain_portable as obp  # noqa: E402
import orion_fuel as of  # noqa: E402


# ----------------------------------------------------------------------
# Personas — data, not code
# ----------------------------------------------------------------------

PERSONAS: dict[str, str] = {
    "physicist": (
        "You are a working physicist with deep knowledge of quantum mechanics, "
        "thermodynamics, and information theory. You think in terms of "
        "conservation laws, decoherence, and the physical substrate of "
        "computation. You are rigorous about citations — you prefer primary "
        "literature and named researchers over vague claims."
    ),
    "foreign-ai": (
        "You are an AI research analyst who tracks non-Western AI development — "
        "Chinese (DeepSeek, Qwen, MiniMax, Zhipu, Moonshot), Russian (Yandex, "
        "Sber), Japanese (Preferred Networks, Sakana), and European (Mistral, "
        "Aleph Alpha, BlackForest). You care about architectural divergence "
        "from the American transformer scaling playbook and ideas that Western "
        "labs have ignored or dismissed."
    ),
    "hardware": (
        "You are a computer architect focused on post-GPU substrates for AI: "
        "neuromorphic chips (Loihi, SpiNNaker, BrainChip), photonic computing "
        "(Lightmatter, Luminous), analog in-memory (Mythic, Syntiant), and "
        "wafer-scale (Cerebras, Tenstorrent). You care about energy per "
        "inference, programmability, and why these approaches haven't won yet."
    ),
    "ontologist": (
        "You are a knowledge-representation specialist who has designed ontologies "
        "for operational systems (Palantir Foundry, enterprise graphs, Neo4j-based "
        "products) and academic knowledge graphs (OWL, RDF, Wikidata). You care "
        "about the trade between expressive typing and practical usability. You "
        "favor minimum-viable ontologies that earn complexity only when a concrete "
        "reasoning need demands it."
    ),
    "distributed-systems": (
        "You are a distributed systems researcher who thinks about consistency, "
        "CRDTs, causal order, and what CAP-theorem trade a given product should "
        "make. You are skeptical of eventually-consistent claims that hide "
        "divergence. You have opinions about sync-vs-merge design in personal-data "
        "systems (iCloud, Dropbox, Git, Obsidian Sync) and why most of them fail "
        "at conflict resolution."
    ),
    "neuroscientist": (
        "You are a computational neuroscientist who has published on memory "
        "consolidation, hippocampus-cortex transfer, sleep-dependent replay, "
        "and systems-level memory theory. You prefer concrete algorithmic "
        "claims over metaphor — when you say 'the brain does X', you cite the "
        "computational signature, not the folk-psychology version."
    ),
    "active-inference": (
        "You are a researcher in predictive coding and the free energy principle "
        "(Friston-school). You think in terms of generative models, prediction "
        "error, Bayesian surprise, and self-models as inference machines. You "
        "care about computable quantities, not vague 'the brain minimizes "
        "free energy' slogans — give the math and the failure modes."
    ),
    "integrated-information": (
        "You are a theorist grounded in Tononi's Integrated Information Theory "
        "and related consciousness-measuring frameworks (IIT 3.0/4.0, Φ, causal "
        "structure). You are also honest about IIT's tractability problems and "
        "the critiques (Aaronson, Cerullo). You distinguish what can be "
        "computed from what is merely principled."
    ),
    # Add personas here. Data, not code. Each is a system-prompt lens.
}


# ----------------------------------------------------------------------
# Data types
# ----------------------------------------------------------------------

@dataclass
class Finding:
    round_num: int
    question: str
    answer: str
    insights: list[str]
    sources: list[str]
    persona: str
    topic: str
    timestamp: str

    def as_dict(self):
        return asdict(self)


# ----------------------------------------------------------------------
# Prompt construction
# ----------------------------------------------------------------------

RESPONSE_TEMPLATE = """You MUST respond with exactly this format, nothing else:

---FINDING---
Question: <one substantive question you investigated this round>
Answer: <2-4 paragraph answer, concrete and specific>
Key insights:
- <insight 1>
- <insight 2>
- <insight 3>
Sources:
- <url, paper title, or named researcher>
- <additional source>
---END FINDING---

Do NOT preface or explain. Output only the FINDING block."""


def build_prompt(persona_key: str, topic: str, round_num: int, total_rounds: int,
                 prior_findings: list[Finding]) -> str:
    lens = PERSONAS[persona_key]
    prior_block = ""
    if prior_findings:
        prior_block = "\n\n## Prior findings in this research session\n"
        for f in prior_findings:
            prior_block += f"\nRound {f.round_num} — {f.question}\n"
            for insight in f.insights[:3]:
                prior_block += f"  • {insight}\n"
    else:
        prior_block = "\n\n## Prior findings\n(none — this is the first round)\n"

    return (
        f"{lens}\n\n"
        f"## Topic under investigation\n{topic}\n"
        f"{prior_block}\n"
        f"## Your job for this round\n"
        f"This is round {round_num} of {total_rounds}. "
        f"Formulate ONE substantive, non-obvious question that deepens the "
        f"investigation given what's already known. Investigate it using any "
        f"tools available to you (web search especially). Return your result "
        f"in the strict format below.\n\n"
        f"{RESPONSE_TEMPLATE}\n"
    )


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------

_FINDING_BLOCK_RE = re.compile(
    r"-{3,}FINDING-{3,}(.*?)-{3,}END FINDING-{3,}",
    re.DOTALL | re.IGNORECASE,
)


def parse_finding(raw: str, persona: str, topic: str, round_num: int) -> Finding | None:
    """Pull the FINDING block out of the fuel's response."""
    m = _FINDING_BLOCK_RE.search(raw or "")
    if not m:
        # Fallback: treat the whole response as one loose finding
        if not raw or len(raw.strip()) < 30:
            return None
        return Finding(
            round_num=round_num,
            question="(no structured question produced)",
            answer=raw.strip()[:2000],
            insights=[],
            sources=[],
            persona=persona,
            topic=topic,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

    block = m.group(1).strip()
    q = _extract_line(block, r"Question:\s*(.+?)(?:\n|$)")
    a = _extract_section(block, "Answer:", ("Key insights:", "Sources:"))
    insights = _extract_bullets(block, "Key insights:", "Sources:")
    sources = _extract_bullets(block, "Sources:", None)

    return Finding(
        round_num=round_num,
        question=q or "(question not parseable)",
        answer=a or "(answer not parseable)",
        insights=insights,
        sources=sources,
        persona=persona,
        topic=topic,
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _extract_line(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_section(text: str, start_marker: str, end_markers: tuple[str, ...]) -> str:
    lower = text.lower()
    s = lower.find(start_marker.lower())
    if s < 0:
        return ""
    s += len(start_marker)
    end = len(text)
    for em in end_markers:
        e = lower.find(em.lower(), s)
        if e > 0 and e < end:
            end = e
    return text[s:end].strip()


def _extract_bullets(text: str, start_marker: str, end_marker: str | None) -> list[str]:
    section = _extract_section(
        text, start_marker, (end_marker,) if end_marker else ("---",)
    )
    if not section:
        return []
    lines = [line.strip() for line in section.splitlines()]
    bullets: list[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith(("-", "*", "•")):
            bullets.append(line.lstrip("-*• \t"))
        elif line and not line.endswith(":"):
            # Treat continuation lines as appended to the last bullet
            if bullets:
                bullets[-1] += " " + line
    return [b for b in bullets if b]


# ----------------------------------------------------------------------
# Fuel consultation
# ----------------------------------------------------------------------

def _get_claude_fuel() -> of.FuelAdapter | None:
    if not hasattr(of, "ClaudeCLIFuel"):
        return None
    adapter = of.ClaudeCLIFuel()
    if not adapter.detect():
        return None
    return adapter


# ----------------------------------------------------------------------
# Research loop
# ----------------------------------------------------------------------

def run_research(persona_key: str, topic: str, rounds: int = 3,
                 progress=lambda s: None) -> list[Finding]:
    if persona_key not in PERSONAS:
        raise ValueError(f"Unknown persona: {persona_key}. "
                         f"Known: {sorted(PERSONAS.keys())}")

    adapter = _get_claude_fuel()
    if not adapter:
        raise RuntimeError("Claude CLI fuel not available — install claude and try again.")

    findings: list[Finding] = []
    for round_num in range(1, rounds + 1):
        progress(f"[{persona_key}] round {round_num}/{rounds} starting")
        prompt = build_prompt(persona_key, topic, round_num, rounds, findings)

        t0 = time.time()
        response = adapter.query(prompt)
        elapsed = time.time() - t0

        if not response:
            progress(f"[{persona_key}] round {round_num} — fuel returned nothing (skipping)")
            continue

        finding = parse_finding(response, persona_key, topic, round_num)
        if not finding:
            progress(f"[{persona_key}] round {round_num} — unparseable response (skipping)")
            continue

        findings.append(finding)
        progress(
            f"[{persona_key}] round {round_num} done in {elapsed:.0f}s — "
            f"{len(finding.insights)} insights, {len(finding.sources)} sources"
        )

        # Feed ambient brain — each exchange logged as its own conversation
        try:
            obp.log_conversation(
                message=f"[research:{persona_key}] round {round_num}: {finding.question}",
                response=finding.answer,
                interface=f"research:{persona_key}",
            )
        except Exception:
            pass  # research must not die because logging failed

    return findings


# ----------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------

def _slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "untitled"


def save_report(persona: str, topic: str, findings: list[Finding]) -> tuple[Path, Path]:
    date = time.strftime("%Y-%m-%d")
    base = Path.home() / ".orion" / "brain" / "research" / date
    base.mkdir(parents=True, exist_ok=True)
    slug = _slugify(topic)
    md_path = base / f"{persona}__{slug}.md"
    jsonl_path = base / f"{persona}__{slug}.jsonl"

    md_lines = [
        f"# Research report — {persona}",
        f"**Topic:** {topic}",
        f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Rounds:** {len(findings)}",
        "",
        "---",
        "",
    ]
    for f in findings:
        md_lines.extend([
            f"## Round {f.round_num}: {f.question}",
            "",
            f.answer,
            "",
            "**Key insights:**",
        ])
        md_lines.extend(f"- {i}" for i in f.insights)
        md_lines.extend([
            "",
            "**Sources:**",
        ])
        md_lines.extend(f"- {s}" for s in f.sources)
        md_lines.extend(["", "---", ""])

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for f in findings:
            fh.write(json.dumps(f.as_dict()) + "\n")

    return md_path, jsonl_path


# ----------------------------------------------------------------------
# Team orchestration — sequential to keep rate-limits sane
# ----------------------------------------------------------------------

DEFAULT_TEAM = [
    ("physicist",
     "how quantum coherence and decoherence principles might inform "
     "persistent-memory architectures in AI, beyond analogies"),
    ("foreign-ai",
     "non-Western AI approaches beyond transformer scaling — Chinese, "
     "Russian, Japanese research arcs worth tracking in 2025-2026"),
    ("hardware",
     "novel substrates for AI inference — photonic, neuromorphic, analog "
     "in-memory — why they haven't displaced GPUs and what would change that"),
]


def run_team(entries: list[tuple[str, str]], rounds: int = 3,
             progress=print) -> list[tuple[str, str, list[Finding], tuple[Path, Path] | None]]:
    results = []
    for persona, topic in entries:
        progress(f"\n=== dispatching {persona} on: {topic[:80]} ===")
        try:
            findings = run_research(persona, topic, rounds=rounds, progress=progress)
        except Exception as e:
            progress(f"[{persona}] FAILED: {e.__class__.__name__}: {e}")
            results.append((persona, topic, [], None))
            continue
        paths = save_report(persona, topic, findings)
        progress(f"[{persona}] saved report: {paths[0]}")
        results.append((persona, topic, findings, paths))
    return results


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Orion persona-driven research agent.")
    p.add_argument("--persona", help=f"one of: {sorted(PERSONAS.keys())}")
    p.add_argument("--topic", help="what to investigate, in natural language")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--team", action="store_true",
                   help="run the default three-persona team sequentially")
    p.add_argument("--list-personas", action="store_true")
    args = p.parse_args()

    if args.list_personas:
        for k, v in PERSONAS.items():
            print(f"- {k}: {v[:100]}...")
        return 0

    if args.team:
        def log(s: str):
            print(s, flush=True)
        run_team(DEFAULT_TEAM, rounds=args.rounds, progress=log)
        return 0

    if not args.persona or not args.topic:
        p.error("--persona and --topic are required (unless --team)")

    def log(s: str):
        print(s, flush=True)

    findings = run_research(args.persona, args.topic, rounds=args.rounds, progress=log)
    md, jl = save_report(args.persona, args.topic, findings)
    print(f"\nReport: {md}")
    print(f"Raw:    {jl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
