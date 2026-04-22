#!/usr/bin/env python3
"""
orion_preflight — integration health check.

Runs a set of structured checks that verify the installed Orion codebase
composes correctly and its promised capabilities are actually wired. Not
a unit-test suite — these are integration checks about the whole brain.

Use cases:
    1. After install (fresh venv, first time) — prove the brain is healthy
       before the user starts talking to it.
    2. Before shipping changes — catch regressions in the integration
       surface (cycle engine, discovery, fuel, persistence).
    3. As a self-diagnostic when something feels off — "is my Orion ok?"

This is the G5 verification artifact: the script a stranger runs after
install to know whether to trust their setup.

Exit codes:
    0 — all green, healthy
    1 — at least one red (broken)
    2 — yellows but no reds (partial — may still be usable)

Usage:
    python orion_preflight.py
    python orion_preflight.py --json
    python orion_preflight.py --verbose
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))


# ANSI colors (disabled if stdout isn't a terminal so JSON piping stays clean)
_COLOR = sys.stdout.isatty()
def _c(code: str) -> str:
    return code if _COLOR else ""
GREEN, YELLOW, RED, DIM, BOLD, RESET = map(_c, (
    "\033[92m", "\033[93m", "\033[91m", "\033[2m", "\033[1m", "\033[0m"
))


# ----------------------------------------------------------------------
# Result shapes
# ----------------------------------------------------------------------

@dataclass
class Check:
    name: str
    status: str = "pending"   # "green" | "yellow" | "red" | "pending"
    message: str = ""
    detail: str = ""
    elapsed_ms: int = 0

    def fmt(self) -> str:
        marker = {
            "green": f"{GREEN}✓{RESET}",
            "yellow": f"{YELLOW}!{RESET}",
            "red": f"{RED}✗{RESET}",
            "pending": f"{DIM}·{RESET}",
        }[self.status]
        return f"  {marker} {self.name:40s} {self.message}"


# ----------------------------------------------------------------------
# Individual checks — each returns a Check
# ----------------------------------------------------------------------

def check_imports() -> Check:
    """Every core module imports cleanly."""
    c = Check(name="core modules import")
    t0 = time.time()
    required = [
        "orion_fuel", "orion_discover", "orion_selfcheck",
        "orion_cycle", "orion_brain_portable",
    ]
    optional = ["orion_tools", "orion_chat", "orion_reflect"]
    failed = []
    for mod in required:
        try:
            __import__(mod)
        except Exception as e:
            failed.append(f"{mod} ({e.__class__.__name__}: {str(e)[:60]})")

    soft_failed = []
    for mod in optional:
        try:
            __import__(mod)
        except Exception as e:
            soft_failed.append(f"{mod} ({e.__class__.__name__})")

    c.elapsed_ms = int((time.time() - t0) * 1000)
    if failed:
        c.status = "red"
        c.message = f"{len(failed)} required module(s) failed to import"
        c.detail = "; ".join(failed)
    elif soft_failed:
        c.status = "yellow"
        c.message = f"optional modules not importable: {len(soft_failed)}"
        c.detail = "; ".join(soft_failed)
    else:
        c.status = "green"
        c.message = f"all {len(required) + len(optional)} modules OK"
    return c


def check_brain_dirs() -> Check:
    """~/.orion/brain/ structure exists and is writable."""
    c = Check(name="brain data directory writable")
    t0 = time.time()
    brain = Path.home() / ".orion" / "brain"
    try:
        brain.mkdir(parents=True, exist_ok=True)
        test = brain / f".preflight_{int(time.time())}.tmp"
        test.write_text("ok", encoding="utf-8")
        test.unlink()
    except Exception as e:
        c.status = "red"
        c.message = f"cannot write to {brain}: {e.__class__.__name__}"
        c.elapsed_ms = int((time.time() - t0) * 1000)
        return c
    c.status = "green"
    c.message = f"{brain} writable"
    c.elapsed_ms = int((time.time() - t0) * 1000)
    return c


def check_home_context_files() -> Check:
    """Context files (AGENTS.md / GEMINI.md / ORION-CONTEXT.md) present."""
    c = Check(name="home context files present")
    t0 = time.time()
    home = Path.home()
    expected = ["ORION-CONTEXT.md", "AGENTS.md", "GEMINI.md"]
    found = [f for f in expected if (home / f).exists()]
    missing = [f for f in expected if not (home / f).exists()]
    c.elapsed_ms = int((time.time() - t0) * 1000)
    if not found:
        c.status = "red"
        c.message = "no context files in home dir — run setup wizard"
    elif missing:
        c.status = "yellow"
        c.message = f"{len(found)}/{len(expected)} present ({', '.join(found)})"
        c.detail = f"missing: {', '.join(missing)}"
    else:
        c.status = "green"
        c.message = "all context files present"
    return c


def check_discovery() -> Check:
    """orion_discover runs and returns something plausible."""
    c = Check(name="discovery runs")
    t0 = time.time()
    try:
        import orion_discover
        report = orion_discover.discover_host(max_depth=3)
    except Exception as e:
        c.status = "red"
        c.message = f"discover_host crashed: {e.__class__.__name__}"
        c.detail = str(e)[:120]
        c.elapsed_ms = int((time.time() - t0) * 1000)
        return c

    c.elapsed_ms = int((time.time() - t0) * 1000)
    total = report.get("total_findings", 0)
    tool_count = len(report.get("tool_guesses", []))
    if total == 0:
        c.status = "yellow"
        c.message = f"discovery ran but returned 0 findings — host may be bare"
    elif tool_count == 0:
        c.status = "yellow"
        c.message = f"{total} findings but no recognizable tool names"
    else:
        c.status = "green"
        c.message = f"{total} findings, {tool_count} tool type(s) identified"
        c.detail = ", ".join(report["tool_guesses"][:8])
    return c


def check_cycle_composes() -> Check:
    """orion_cycle runs a wake-trigger pass without crashing."""
    c = Check(name="cognitive cycle composes")
    t0 = time.time()
    try:
        import orion_cycle
        ctx = orion_cycle.CycleContext(trigger="wake", interactive=False)
        outcome = orion_cycle.run(ctx, ui=orion_cycle.SilentUI())
    except Exception as e:
        c.status = "red"
        c.message = f"cycle crashed: {e.__class__.__name__}"
        c.detail = str(e)[:120]
        c.elapsed_ms = int((time.time() - t0) * 1000)
        return c

    c.elapsed_ms = int((time.time() - t0) * 1000)
    status = outcome.cycle_status
    if status == "failed":
        c.status = "red"
        c.message = f"cycle reported failure"
    elif status == "clean":
        c.status = "green"
        c.message = "cycle ran clean, no gaps detected"
    else:
        gaps_mcp = sum(
            1 for io in outcome.issue_outcomes
            if io.issue.kind == "missing_orion_brain_in_mcp"
        )
        gaps_bin = sum(
            1 for io in outcome.issue_outcomes
            if io.issue.kind == "ai_binary_without_mcp_config"
        )
        if gaps_mcp > 0:
            c.status = "yellow"
            c.message = f"cycle ran; {gaps_mcp} MCP gap(s) surfaced"
            c.detail = "run /selfcheck in orion chat to repair"
        elif gaps_bin > 0:
            c.status = "green"
            c.message = f"cycle ran; {gaps_bin} non-MCP binaries surfaced (informational)"
        else:
            c.status = "green"
            c.message = f"cycle ran, {outcome.issues_found} issues surfaced"
    return c


def check_log_conversation() -> Check:
    """obp.log_conversation can write end-to-end."""
    c = Check(name="conversation log writable")
    t0 = time.time()
    try:
        import orion_brain_portable as obp
        obp.log_conversation(
            "[preflight ping]",
            "[preflight pong]",
            interface="preflight",
        )
    except Exception as e:
        c.status = "red"
        c.message = f"log_conversation crashed: {e.__class__.__name__}"
        c.elapsed_ms = int((time.time() - t0) * 1000)
        return c

    # Verify it landed
    date = time.strftime("%Y-%m-%d")
    logfile = Path.home() / ".orion" / "brain" / "conversations" / f"{date}.jsonl"
    if not logfile.exists():
        c.status = "red"
        c.message = f"log_conversation returned but file missing: {logfile}"
        c.elapsed_ms = int((time.time() - t0) * 1000)
        return c

    try:
        content = logfile.read_text(encoding="utf-8")
    except Exception as e:
        c.status = "yellow"
        c.message = f"log file exists but unreadable: {e.__class__.__name__}"
        c.elapsed_ms = int((time.time() - t0) * 1000)
        return c

    if "preflight" not in content:
        c.status = "yellow"
        c.message = "log file exists but our entry isn't in it"
    else:
        c.status = "green"
        c.message = f"write + verify roundtrip OK ({logfile.name})"
    c.elapsed_ms = int((time.time() - t0) * 1000)
    return c


def check_mcp_server_runnable() -> Check:
    """Can Python start orion_mcp_server.py and have it accept stdin close?"""
    c = Check(name="MCP server starts cleanly")
    t0 = time.time()
    import subprocess
    server = _REPO_DIR / "orion_mcp_server.py"
    if not server.exists():
        c.status = "red"
        c.message = "orion_mcp_server.py missing from repo"
        c.elapsed_ms = int((time.time() - t0) * 1000)
        return c
    try:
        proc = subprocess.Popen(
            [sys.executable, str(server)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Close stdin to signal shutdown; give it 5s to exit
        proc.stdin.close()
        try:
            rc = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            c.status = "yellow"
            c.message = "server started but didn't exit on EOF in 5s"
            c.elapsed_ms = int((time.time() - t0) * 1000)
            return c
    except Exception as e:
        c.status = "red"
        c.message = f"could not start server: {e.__class__.__name__}"
        c.elapsed_ms = int((time.time() - t0) * 1000)
        return c

    c.elapsed_ms = int((time.time() - t0) * 1000)
    if rc == 0:
        c.status = "green"
        c.message = f"server started and exited cleanly ({c.elapsed_ms}ms)"
    else:
        c.status = "yellow"
        c.message = f"server exited with code {rc}"
    return c


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------

CHECKS = [
    check_imports,
    check_brain_dirs,
    check_home_context_files,
    check_discovery,
    check_cycle_composes,
    check_log_conversation,
    check_mcp_server_runnable,
]


def run_all() -> list[Check]:
    results = []
    for fn in CHECKS:
        try:
            results.append(fn())
        except Exception as e:
            # Should never happen — checks are supposed to catch their own
            # failures. If one itself crashes, treat as a broken check.
            results.append(Check(
                name=fn.__name__,
                status="red",
                message=f"check itself crashed: {e.__class__.__name__}",
                detail=str(e)[:200],
            ))
    return results


def main():
    args = sys.argv[1:]
    emit_json = "--json" in args
    verbose = "--verbose" in args or "-v" in args

    results = run_all()

    if emit_json:
        json.dump(
            [{"name": r.name, "status": r.status, "message": r.message,
              "detail": r.detail, "elapsed_ms": r.elapsed_ms}
             for r in results],
            sys.stdout, indent=2,
        )
        print()
    else:
        print()
        print(f"{BOLD}ORION PREFLIGHT{RESET}")
        print()
        for r in results:
            print(r.fmt())
            if verbose and r.detail:
                print(f"        {DIM}{r.detail}{RESET}")
        print()
        g = sum(1 for r in results if r.status == "green")
        y = sum(1 for r in results if r.status == "yellow")
        rd = sum(1 for r in results if r.status == "red")
        summary_bits = []
        if g: summary_bits.append(f"{GREEN}{g} green{RESET}")
        if y: summary_bits.append(f"{YELLOW}{y} yellow{RESET}")
        if rd: summary_bits.append(f"{RED}{rd} red{RESET}")
        print(f"  Summary: {', '.join(summary_bits)}")
        print()

    if any(r.status == "red" for r in results):
        return 1
    if any(r.status == "yellow" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
