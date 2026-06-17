#!/usr/bin/env python3
"""orion_absorb.py — discover, rank, and selectively absorb what the user's
existing AI models already know.

The "don't re-teach" problem (founder, 2026-06-06): nobody wants to teach a
fresh brain what their most-used models already know. orion_ingest.py can already
READ claude/codex/gemini/letta/ollama histories — but it (a) uses hardcoded
default paths, (b) has no usage RANKING, and (c) has no measured, consent-based
selection. This module adds exactly that layer on top of orion_ingest:

  discover()      → probe every known AI-tool memory location (+ custom paths),
                    measure usage (file count, bytes, last-active), RANK by how
                    much each is actually used. Handles varying paths via a
                    per-tool registry + an explicit override map.
  format_menu()   → render the ranked findings as a menu a HUMAN or an AI
                    (in-model config mode) can present and act on.
  absorb()        → import ONLY the selected sources, measured (heuristic now,
                    optional local-model deep pass), via orion_ingest.run().

Design rules honored:
  - Measured + consent-based: nothing is imported unless explicitly selected.
  - Re-runnable: import re-confirms facts, never duplicates (orion_ingest dedup).
  - No API keys: deep pass uses local Ollama only.
  - Cross-path: KNOWN_PATHS registry per tool + per-OS variants + a custom-path
    override so non-standard installs still work.
  - MCP-ready: discover()/absorb() return plain dicts so an in-model tool can
    drive the whole flow conversationally (no terminal menu required).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))


# ─────────────────────────────────────────────────────────────
# Per-tool path registry. Each tool maps to an ingest source name
# (must exist in orion_ingest.SOURCES) + candidate paths across OSes.
# First existing path wins; a custom override (see discover(overrides=))
# takes precedence so non-standard installs still absorb.
# ─────────────────────────────────────────────────────────────

H = Path.home()
KNOWN_PATHS: dict[str, dict] = {
    "claude": {
        "ingest": "claude",
        "label": "Claude Code",
        "paths": [H / ".claude" / "projects", H / ".config" / "claude" / "projects"],
        "glob": "**/*.jsonl",
    },
    "codex": {
        "ingest": "codex",
        "label": "Codex",
        "paths": [H / ".codex" / "sessions", H / ".codex"],
        "glob": "**/*.jsonl",
    },
    "gemini": {
        "ingest": "gemini",
        "label": "Gemini CLI",
        "paths": [H / ".gemini" / "tmp"],
        "glob": "**/*.json",
    },
    "letta": {
        "ingest": "letta",
        "label": "Letta",
        "paths": [H / ".letta" / "agents"],
        "glob": "**/*",
    },
    "ollama": {
        "ingest": "ollama",
        "label": "Ollama",
        "paths": [H / ".ollama" / "history", H / ".ollama"],
        "glob": "**/*",
    },
    "chatgpt-desktop": {
        "ingest": None,  # no reader yet — discovery only (flag for future reader)
        "label": "ChatGPT Desktop",
        "paths": [
            H / "Library" / "Application Support" / "com.openai.chat",
            H / ".config" / "OpenAI",
        ],
        "glob": "**/*",
    },
    "cursor": {
        "ingest": None,  # discovery only for now
        "label": "Cursor",
        "paths": [
            H / "Library" / "Application Support" / "Cursor" / "User",
            H / ".cursor",
            H / ".config" / "Cursor" / "User",
        ],
        "glob": "**/*.json",
    },
}


def _measure(path: Path, glob: str) -> dict:
    """Cheap usage signal for ranking: file count, total bytes, last-active.
    Stat-only (no content read) so discovery is instant even on big histories."""
    files = 0
    nbytes = 0
    latest = 0.0
    try:
        for p in path.glob(glob):
            if p.is_file():
                files += 1
                try:
                    st = p.stat()
                    nbytes += st.st_size
                    latest = max(latest, st.st_mtime)
                except OSError:
                    pass
            if files > 50000:  # safety cap; enough signal for ranking
                break
    except OSError:
        pass
    return {"files": files, "bytes": nbytes, "last_active": latest}


def _usage_score(m: dict, now: float) -> float:
    """Rank by usage = volume × recency. Recent + heavily-used tools first.
    Volume = log-ish via bytes; recency = exponential decay over ~60 days."""
    import math
    vol = math.log10(max(m["bytes"], 1) + 1)  # 0..~9
    age_days = (now - m["last_active"]) / 86400.0 if m["last_active"] else 9999
    recency = math.exp(-age_days / 60.0)       # 1.0 today → ~0.37 at 60d
    return round(vol * (0.3 + recency), 3)     # always weight volume a little


def discover(overrides: dict | None = None) -> list[dict]:
    """Probe every known AI tool. Returns a list ranked by usage (most-used
    first), each: {tool, label, path, found, importable, files, bytes,
    last_active_iso, score}. `overrides` = {tool: '/custom/path'} for
    non-standard installs (varying-path problem)."""
    overrides = overrides or {}
    now = time.time()
    out: list[dict] = []
    for tool, spec in KNOWN_PATHS.items():
        # custom override path wins
        candidates = []
        if tool in overrides:
            candidates.append(Path(os.path.expanduser(overrides[tool])))
        candidates += list(spec["paths"])
        found_path = next((p for p in candidates if p.exists()), None)
        rec = {
            "tool": tool,
            "label": spec["label"],
            "path": str(found_path) if found_path else None,
            "found": found_path is not None,
            "importable": bool(spec["ingest"]),  # has an ingest reader?
            "files": 0, "bytes": 0, "last_active": 0.0, "score": 0.0,
        }
        if found_path:
            m = _measure(found_path, spec["glob"])
            rec.update(m)
            rec["score"] = _usage_score(m, now) if rec["importable"] else 0.0
        rec["last_active_iso"] = (
            time.strftime("%Y-%m-%d", time.localtime(rec["last_active"]))
            if rec["last_active"] else None
        )
        out.append(rec)
    out.sort(key=lambda r: (r["found"], r["importable"], r["score"]), reverse=True)
    return out


def format_menu(discovered: list[dict]) -> str:
    """Render the ranked findings as a measured menu (for CLI or in-model use)."""
    lines = ["Sources Orion can absorb (ranked by how much you use them):", ""]
    rank = 0
    for r in discovered:
        if not r["found"]:
            continue
        rank += 1
        mb = r["bytes"] / 1e6
        imp = "" if r["importable"] else "  (discovery only — no reader yet)"
        lines.append(
            f"  {rank}. {r['label']:16} score {r['score']:>5}  "
            f"{r['files']:>5} files  {mb:6.1f} MB  last {r['last_active_iso']}{imp}"
        )
        lines.append(f"       {r['path']}")
    not_found = [r["label"] for r in discovered if not r["found"]]
    if not_found:
        lines += ["", "Not found on this machine: " + ", ".join(not_found)]
    lines += ["", "Import measured: orion_absorb import --sources <tool> [<tool>...]",
              "Or import the top N: orion_absorb import --top 3"]
    return "\n".join(lines)


def _pick_model(endpoint: str = "http://localhost:11434") -> str:
    """Pick an available local Ollama chat model for deep extraction (prefer
    instruct models; never an embedding model). No API keys — local only."""
    try:
        import requests
        names = [m["name"] for m in
                 requests.get(endpoint + "/api/tags", timeout=5).json().get("models", [])]
        for pref in ("llama3.1:8b", "mistral:7b", "phi3:mini"):
            if pref in names:
                return pref
        for n in names:
            if "embed" not in n:
                return n
    except Exception:
        pass
    return "llama3.1:8b"


def absorb(sources: list[str], deep: bool = False, dry_run: bool = False,
           overrides: dict | None = None, deep_cap: int = 40) -> dict:
    """Import the SELECTED sources into the brain (measured, consent-based).
    Reuses orion_ingest.run (dedup + contradiction + decay).

    deep=True uses a LOCAL Ollama model auto-detected from what's installed
    (the prior default 'orion-qwen3' didn't exist on COMMAND -> 0 facts). The
    deep pass is SLOW (~15s/segment on 8GB VRAM) so it is capped to deep_cap
    most-recent segments; full-history deep extraction must run as an ambient
    background job, not interactively.

    Honest note: for technical/work histories, fact-extraction yields little —
    the higher-value path is embed-the-history + per-turn injection (separate
    build). overrides affect discovery ranking; reader custom-path injection is
    a follow-up (portable readers still use default paths)."""
    import orion_ingest
    valid = [s for s in sources if KNOWN_PATHS.get(s, {}).get("ingest")]
    skipped = [s for s in sources if s not in valid]
    model = _pick_model() if deep else "orion-qwen3"
    max_per_source = deep_cap if deep else 1000
    report = orion_ingest.run(sources=valid, deep=deep, dry_run=dry_run,
                              model=model, endpoint="http://localhost:11434/v1",
                              max_per_source=max_per_source)
    report["requested"] = sources
    report["imported_sources"] = valid
    report["skipped_no_reader"] = skipped
    if deep:
        report["deep_model"] = model
        report["deep_cap"] = deep_cap
    return report


def _cli() -> int:
    ap = argparse.ArgumentParser(prog="orion_absorb",
                                 description="Discover + selectively absorb existing model memory.")
    sub = ap.add_subparsers(dest="cmd")
    pd = sub.add_parser("discover", help="show ranked menu of absorbable sources")
    pd.add_argument("--json", action="store_true")
    pi = sub.add_parser("import", help="import selected sources (measured)")
    pi.add_argument("--sources", nargs="+", help="tool names, e.g. claude codex gemini")
    pi.add_argument("--top", type=int, help="import the top N most-used importable sources")
    pi.add_argument("--deep", action="store_true", help="local-model deep pass after heuristic")
    pi.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.cmd == "discover" or args.cmd is None:
        disc = discover()
        if getattr(args, "json", False):
            print(json.dumps(disc, indent=2))
        else:
            print(format_menu(disc))
        return 0

    if args.cmd == "import":
        disc = discover()
        if args.top:
            picks = [r["tool"] for r in disc if r["found"] and r["importable"]][:args.top]
        elif args.sources:
            picks = args.sources
        else:
            print("specify --sources <tool>... or --top N (see: orion_absorb discover)")
            return 2
        print(f"Absorbing (measured): {', '.join(picks)}{' [dry-run]' if args.dry_run else ''}")
        rep = absorb(picks, deep=args.deep, dry_run=args.dry_run)
        print(f"  imported sources: {rep.get('imported_sources')}")
        print(f"  read {rep.get('total_messages',0)} segments | "
              f"heuristic {rep.get('heuristic_facts',0)} | deep {rep.get('deep_facts',0)}")
        print(f"  written {rep.get('written',0)} | re-confirmed {rep.get('skipped_dup',0)} | "
              f"contested {rep.get('contested',0)}")
        if rep.get("skipped_no_reader"):
            print(f"  skipped (no reader yet): {rep['skipped_no_reader']}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
