#!/usr/bin/env python3
"""
orion_discover — Adaptive AI-tool discovery (G3 Layer A).

Finds AI tools on the host by the shape of what they produce, not by a
curated list. Replaces "is it in KNOWN_FUEL?" with "does it look like an
AI tool lives here?"

The output is a structured inventory of discovered artifacts that the rest
of Orion can act on:
  - known_mcp_tool: MCP config found pointing at an LLM-shaped command
  - session_artifact: directory holds user/assistant conversation logs
  - context_file: markdown or plain file the user writes to talk to a tool
  - ai_binary: PATH binary whose name matches AI heuristics

Intentionally does NOT:
  - Import or grow KNOWN_FUEL
  - Hand-write "if codex, do X; if gemini, do Y" logic
  - Assume any particular tool exists
  - Mutate anything — this is pure observation

Usage:
  python orion_discover.py                    # print a human report
  python orion_discover.py --json             # emit structured JSON
  from orion_discover import discover_host    # as a library
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


# ----------------------------------------------------------------------
# Heuristics (deliberately broad — false positives preferred over misses)
# ----------------------------------------------------------------------

# Binary names that smell like AI tools. Broad by design — false positives
# are fine, we probe further before acting on matches.
AI_BINARY_PATTERN = re.compile(
    r"(?:^|[-_])("
    r"claude|codex|gemini|llama|ollama|chatgpt|gpt|copilot|cursor|"
    r"letta|continue|aichat|tgpt|llm|khoj|anthropic|openai|mistral|"
    r"qwen|deepseek|phi|llava|vllm|lmstudio"
    r")(?:$|[-_])",
    re.IGNORECASE,
)

# File extensions we consider worth shape-checking for conversation content.
CONVERSATION_EXTENSIONS = {".jsonl", ".json", ".ndjson"}

# Directories we skip unconditionally — saves minutes of walking.
SKIP_DIR_NAMES = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".cache", "Cache", "Temp", "temp",
    "Recycle.Bin", "$Recycle.Bin", "OneDrive", "AppData",
    # Don't recurse into Orion's own brain — that's its output, not discovery input
    ".orion",
}

# MCP config file names we recognize — these are the signals that a tool
# is MCP-capable even if we've never heard of the tool.
MCP_CONFIG_NAMES = {
    "mcp.json",
    "claude_desktop_config.json",
    "settings.json",  # many tools put MCP under mcpServers here
    "config.toml",    # codex uses this
}

# How many files to read per shape check — first few entries tell the shape.
SHAPE_PROBE_LINES = 3


# ----------------------------------------------------------------------
# Result shapes
# ----------------------------------------------------------------------

@dataclass
class Finding:
    kind: str                # "known_mcp_tool" | "session_artifact" | "ai_binary" | "context_file"
    path: str
    confidence: float        # 0.0 - 1.0, how sure we are this is AI-shaped
    hints: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


# ----------------------------------------------------------------------
# Shape detectors — each returns a Finding or None
# ----------------------------------------------------------------------

def _looks_like_conversation_jsonl(path: Path) -> tuple[bool, dict]:
    """Peek at the first few lines. Conversation shape = dicts with role/message/etc."""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= SHAPE_PROBE_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return False, {}
                if not isinstance(obj, dict):
                    return False, {}
                keys = set(obj.keys())
                # user/assistant shape — the universal conversation marker
                if "role" in keys and any(k in keys for k in ("content", "text", "message")):
                    return True, {"first_role": obj.get("role"), "shape": "role-text"}
                # tool-output / event shape (codex style)
                if "type" in keys and any(k in keys for k in ("payload", "message", "content")):
                    return True, {"shape": "event-payload"}
                # session envelope shape
                if "messages" in keys or "conversation" in keys:
                    return True, {"shape": "nested-messages"}
        return False, {}
    except Exception:
        return False, {}


def _looks_like_conversation_json(path: Path) -> tuple[bool, dict]:
    """Single-JSON conversation dumps (Gemini tmp/chats style)."""
    try:
        # Guard file size — some JSONs are huge and not conversations
        if path.stat().st_size > 20_000_000:
            return False, {}
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            obj = json.load(f)
    except Exception:
        return False, {}
    if isinstance(obj, dict):
        if "messages" in obj and isinstance(obj.get("messages"), list):
            return True, {"shape": "top-level-messages", "count": len(obj["messages"])}
        if "conversation" in obj or "turns" in obj:
            return True, {"shape": "nested-conversation"}
        # chatlog shape — Gemini uses session metadata
        if "session" in obj or "chat_id" in obj or "sessionId" in obj:
            return True, {"shape": "session-envelope"}
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = set(obj[0].keys())
        if "role" in keys:
            return True, {"shape": "role-list", "count": len(obj)}
    return False, {}


def _looks_like_mcp_config(path: Path) -> tuple[bool, dict]:
    """TOML or JSON with an mcp_servers / mcpServers block.

    For JSON files, parse properly and extract all server keys. For TOML,
    scan for `[mcp_servers.<name>]` section headers (that's codex's shape).
    Falls back to a raw string check for `orion-brain` so has_orion_brain
    is never a false negative when the literal name is present.
    """
    try:
        if path.stat().st_size > 500_000:
            return False, {}
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False, {}

    markers = ["mcpServers", "mcp_servers", "[mcp_servers.", "mcp-servers"]
    found_marker = next((m for m in markers if m in text), None)
    if not found_marker:
        return False, {}

    names: set[str] = set()

    # Extraction strategy depends on file type
    ext = path.suffix.lower()
    if ext == ".json":
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                # Common shapes: top-level mcpServers OR nested under a client namespace
                if isinstance(obj.get("mcpServers"), dict):
                    names.update(obj["mcpServers"].keys())
                # Walk one level deeper for settings.json variants
                for v in obj.values():
                    if isinstance(v, dict) and isinstance(v.get("mcpServers"), dict):
                        names.update(v["mcpServers"].keys())
        except Exception:
            pass
    elif ext == ".toml":
        # Codex style: `[mcp_servers.orion-brain]`
        for m in re.finditer(r"\[(?:mcp_servers|mcpServers)\.([a-zA-Z0-9_\-]+)\]", text):
            names.add(m.group(1))

    # Always include a literal string check as a last resort — guards against
    # extraction misses (comments, unusual whitespace) for the specific name
    # that matters to self-check.
    has_orion_literal = bool(re.search(r'["\'\[]\s*orion[-_]brain\s*["\'\]]', text))
    if has_orion_literal:
        names.add("orion-brain")

    names.discard("command")
    names.discard("args")

    return True, {
        "marker": found_marker,
        "server_names": sorted(names)[:10],
        "has_orion_brain": ("orion-brain" in names) or ("orion_brain" in names),
    }


def _binary_is_ai_shaped(name: str) -> bool:
    return bool(AI_BINARY_PATTERN.search(name))


# ----------------------------------------------------------------------
# Probe layer — confirm ai_binary candidates are actually AI CLIs
# ----------------------------------------------------------------------

# Output tokens that signal "this is an AI CLI tool". We check the combined
# stdout+stderr of `<binary> --help` against these. Any match confirms.
AI_HELP_TOKENS = re.compile(
    r"\b(?:prompt|chat|model|LLM|completion|inference|token|message|"
    r"assistant|conversation|ask|query|agent|context\s+window)\b",
    re.IGNORECASE,
)

# Extensions that are definitely not runnable CLIs, even if the filename
# looks AI-shaped. DLLs, INIs, service configs, etc.
NON_CLI_EXTENSIONS = {
    ".dll", ".so", ".dylib", ".ini", ".cfg", ".yaml", ".yml",
    ".xml", ".manifest", ".lnk", ".log", ".md", ".txt",
}


def probe_ai_binary(path: str, timeout_seconds: float = 4.0) -> dict:
    """Gently invoke <path> --help and classify the result.

    Returns {status, confidence_delta, evidence} — never raises.

    status is one of:
      "confirmed"   — output matches AI help-text patterns
      "not_cli"     — extension or output shape says this isn't a CLI
      "inconclusive"— it ran but output doesn't mention AI concepts
      "unrunnable"  — timed out, crashed, or wouldn't execute
    """
    p = Path(path)
    ext = p.suffix.lower()

    # Hard-reject obvious non-executables by extension
    if ext in NON_CLI_EXTENSIONS:
        return {
            "status": "not_cli",
            "confidence_delta": -0.7,
            "evidence": f"extension {ext} is not a CLI binary",
        }

    # Don't probe if the file isn't actually a file we can read
    try:
        if not p.is_file():
            return {"status": "unrunnable", "confidence_delta": -0.3,
                    "evidence": "not a regular file"}
    except (OSError, PermissionError) as e:
        return {"status": "unrunnable", "confidence_delta": -0.2,
                "evidence": f"stat failed: {e.__class__.__name__}"}

    # Run the binary with --help and capture output. Hide the console window
    # on Windows so probing doesn't flash terminals.
    kwargs = {"capture_output": True, "timeout": timeout_seconds}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    try:
        result = subprocess.run([path, "--help"], **kwargs)
    except subprocess.TimeoutExpired:
        return {"status": "unrunnable", "confidence_delta": -0.1,
                "evidence": f"--help timed out after {timeout_seconds}s"}
    except (OSError, PermissionError) as e:
        return {"status": "unrunnable", "confidence_delta": -0.3,
                "evidence": f"exec failed: {e.__class__.__name__}"}
    except Exception as e:
        return {"status": "unrunnable", "confidence_delta": -0.1,
                "evidence": f"exec error: {e.__class__.__name__}: {e}"[:120]}

    text = ""
    try:
        text = (result.stdout or b"").decode("utf-8", errors="ignore")
        text += "\n" + (result.stderr or b"").decode("utf-8", errors="ignore")
    except Exception:
        pass

    if not text.strip():
        return {"status": "inconclusive", "confidence_delta": 0.0,
                "evidence": "no output on --help"}

    match = AI_HELP_TOKENS.search(text)
    if match:
        excerpt = text[max(0, match.start() - 30):match.end() + 30].replace("\n", " ").strip()
        return {
            "status": "confirmed",
            "confidence_delta": +0.25,
            "evidence": f"matched '{match.group(0)}' — …{excerpt[:120]}…",
        }

    # Ran and produced output, but no AI tokens — probably not an AI tool
    return {
        "status": "inconclusive",
        "confidence_delta": -0.15,
        "evidence": f"help output has no AI tokens (first 80 chars): {text.strip()[:80]}",
    }


def probe_findings(findings: list[dict], max_to_probe: int = 20) -> list[dict]:
    """Apply probe_ai_binary to each ai_binary finding, update confidence.

    Mutates in place and returns the list. Only probes ai_binary kind —
    other kinds already have file-shape evidence that's stronger than --help.
    """
    probed = 0
    for f in findings:
        if f.get("kind") != "ai_binary":
            continue
        if probed >= max_to_probe:
            break
        probe = probe_ai_binary(f["path"])
        f.setdefault("hints", {})
        f["hints"]["probe_status"] = probe["status"]
        f["hints"]["probe_evidence"] = probe["evidence"]
        f["confidence"] = max(0.0, min(1.0, f.get("confidence", 0.5) + probe["confidence_delta"]))
        probed += 1
    return findings


# ----------------------------------------------------------------------
# Walkers
# ----------------------------------------------------------------------

def _iter_home_files(home: Path, max_depth: int = 5):
    """Walk home dir, skipping known-noise directories."""
    stack = [(home, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            entries = list(os.scandir(current))
        except (PermissionError, OSError):
            continue
        for entry in entries:
            try:
                name = entry.name
                # SKIP_DIR_NAMES catches high-noise directories (node_modules,
                # caches, Recycle.Bin, etc.). We intentionally do NOT maintain
                # a name-based allowlist of AI-shaped dot-dirs — that would be
                # tool curation in disguise. Any new AI tool that lands in
                # ~/.newthing/ must be reachable by the scanner, even if we've
                # never heard of it.
                if name in SKIP_DIR_NAMES:
                    continue
                # Skip typical Windows/system noise at home root only
                if depth == 0 and name in {"Contacts", "Links", "Favorites", "Searches",
                                            "Saved Games", "3D Objects", "Videos",
                                            "Music", "Pictures", "NetHood", "PrintHood",
                                            "Recent", "Templates", "SendTo", "Start Menu",
                                            "IntelGraphicsProfiles", "Application Data",
                                            "My Documents", "Cookies", "Local Settings",
                                            "ntuser.dat.LOG1", "ntuser.dat.LOG2"}:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append((Path(entry.path), depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)
            except (PermissionError, OSError):
                continue


def _scan_path_binaries() -> list[Finding]:
    """Walk PATH and flag binaries whose names look AI-shaped."""
    findings = []
    seen = set()
    path_env = os.environ.get("PATH", "")
    sep = ";" if os.name == "nt" else ":"
    for directory in path_env.split(sep):
        if not directory or not os.path.isdir(directory):
            continue
        try:
            for entry in os.scandir(directory):
                try:
                    name = entry.name
                    stem = Path(name).stem
                    if stem.lower() in seen:
                        continue
                    if not entry.is_file(follow_symlinks=True):
                        continue
                    if _binary_is_ai_shaped(stem):
                        seen.add(stem.lower())
                        match = AI_BINARY_PATTERN.search(stem)
                        findings.append(Finding(
                            kind="ai_binary",
                            path=entry.path,
                            confidence=0.7,
                            hints={
                                "name": stem,
                                "matched_token": match.group(1).lower() if match else "",
                            },
                        ))
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            continue
    return findings


# ----------------------------------------------------------------------
# Main discovery
# ----------------------------------------------------------------------

def discover_host(home: str | os.PathLike | None = None,
                  max_depth: int = 5) -> dict:
    """Run the full discovery pass. Returns a structured inventory."""
    home_path = Path(home or os.path.expanduser("~"))
    findings: list[Finding] = []

    # 1. Home-dir file walk
    for filepath in _iter_home_files(home_path, max_depth=max_depth):
        name_lower = filepath.name.lower()
        ext = filepath.suffix.lower()

        # 1a. MCP config files
        if filepath.name in MCP_CONFIG_NAMES:
            is_mcp, hints = _looks_like_mcp_config(filepath)
            if is_mcp:
                findings.append(Finding(
                    kind="known_mcp_tool",
                    path=str(filepath),
                    confidence=0.95,
                    hints=hints,
                ))
                continue

        # 1b. Conversation artifacts
        if ext == ".jsonl":
            ok, hints = _looks_like_conversation_jsonl(filepath)
            if ok:
                findings.append(Finding(
                    kind="session_artifact",
                    path=str(filepath),
                    confidence=0.85,
                    hints=hints,
                ))
                continue
        elif ext == ".json" and ("chat" in name_lower or "session" in name_lower or "conversation" in name_lower):
            ok, hints = _looks_like_conversation_json(filepath)
            if ok:
                findings.append(Finding(
                    kind="session_artifact",
                    path=str(filepath),
                    confidence=0.75,
                    hints=hints,
                ))

    # 2. PATH binaries with AI-shaped names
    findings.extend(_scan_path_binaries())

    # Group by kind for a tidier report
    by_kind: dict[str, list[Finding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    # Summary: what tools does this host actually host, by heuristic?
    tool_names = set()
    for f in findings:
        if f.kind == "ai_binary":
            tool_names.add(f.hints.get("matched_token") or f.hints.get("name", ""))
        elif f.kind == "known_mcp_tool":
            # Parent dir of the config file often IS the tool's namespace
            parent = Path(f.path).parent.name.lstrip(".")
            if parent:
                tool_names.add(parent)
        elif f.kind == "session_artifact":
            # Look for ".toolname" in the path
            for part in Path(f.path).parts:
                if part.startswith(".") and len(part) > 1 and part[1:].isalpha():
                    tool_names.add(part[1:])
                    break
    tool_names.discard("")

    return {
        "home": str(home_path),
        "total_findings": len(findings),
        "by_kind": {k: [f.as_dict() for f in v] for k, v in by_kind.items()},
        "tool_guesses": sorted(tool_names),
    }


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _print_report(report: dict) -> None:
    print(f"Host: {report['home']}")
    print(f"Findings: {report['total_findings']}")
    print(f"Tool guesses: {', '.join(report['tool_guesses']) or '(none)'}")
    print()
    for kind, items in report["by_kind"].items():
        print(f"[{kind}]  {len(items)} found")
        for it in items[:15]:
            conf = it["confidence"]
            hint_bits = ", ".join(f"{k}={v}" for k, v in it.get("hints", {}).items())[:90]
            print(f"  {conf:.2f}  {it['path']}")
            if hint_bits:
                print(f"         {hint_bits}")
        if len(items) > 15:
            print(f"  ... and {len(items) - 15} more")
        print()


def main():
    emit_json = "--json" in sys.argv
    do_probe = "--probe" in sys.argv
    depth_arg = 5
    for i, a in enumerate(sys.argv):
        if a == "--depth" and i + 1 < len(sys.argv):
            try:
                depth_arg = int(sys.argv[i + 1])
            except ValueError:
                pass

    report = discover_host(max_depth=depth_arg)

    if do_probe:
        # Flatten ai_binary findings across by_kind, probe them in place,
        # then refresh the grouped view.
        ai_bins = report["by_kind"].get("ai_binary", [])
        probe_findings(ai_bins)
        # Drop findings whose confidence dropped below a useful threshold.
        report["by_kind"]["ai_binary"] = [f for f in ai_bins if f["confidence"] >= 0.4]

    if emit_json:
        json.dump(report, sys.stdout, indent=2)
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
