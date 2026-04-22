#!/usr/bin/env python3
"""
orion_cycle — the unified perceive → reason → act → verify loop.

A single reusable harness that fires at any semantic moment Orion finds
useful: install, wake, /selfcheck, encounter. Not tied to install time.

Scope discipline:
    The cycle itself is generic. The specific detectors and fixes are
    plugged in from orion_selfcheck (MCP channel). Adding a new channel
    (context-file, shell-wrapper, etc.) happens by adding a new detector
    module — this file does not change.

Public surface:
    CycleContext(trigger, home=None, interactive=True, auto_apply_reversible=False)
    run(context, ui=None) -> CycleOutcome
    simple_cli_ui()       — default stdin-based UI callbacks

UI contract:
    Callers pass a `ui` object with three callbacks:
      ui.status(msg)                — progress line, no response needed
      ui.confirm(plan) -> bool      — show plan, return True to apply
      ui.error(msg)                 — non-fatal error reporting
    If `ui` is None we use `simple_cli_ui()` which prints to stdout and
    reads from stdin. Wizard UIs pass their own tkinter-shaped callbacks.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_DIR = Path(__file__).resolve().parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

import orion_discover  # noqa: E402
import orion_selfcheck  # noqa: E402


# ----------------------------------------------------------------------
# Types
# ----------------------------------------------------------------------

VALID_TRIGGERS = {"install", "wake", "selfcheck", "encounter"}


@dataclass
class CycleContext:
    trigger: str                         # which semantic moment fired the cycle
    home: str | None = None              # discovery root, default = user home
    interactive: bool = True             # stop for confirmations?
    auto_apply_reversible: bool = False  # auto-apply fixes with backups? (future)
    fuel_preference: str = "claude-cli"  # which fuel to consult
    max_findings_shown: int = 10         # for UI surfaces with limited space

    def __post_init__(self):
        if self.trigger not in VALID_TRIGGERS:
            raise ValueError(
                f"Unknown trigger '{self.trigger}'. "
                f"Valid: {sorted(VALID_TRIGGERS)}"
            )


@dataclass
class IssueOutcome:
    issue: orion_selfcheck.Issue
    status: str          # "surfaced" | "consulted" | "applied" | "verified" | "refused" | "skipped"
    message: str = ""


@dataclass
class CycleOutcome:
    trigger: str
    discovery_summary: dict = field(default_factory=dict)
    issues_found: int = 0
    issue_outcomes: list[IssueOutcome] = field(default_factory=list)
    cycle_status: str = "completed"

    def human_summary(self) -> str:
        lines = [f"Cycle '{self.trigger}' — {self.cycle_status}"]
        lines.append(f"  Discovery: {self.discovery_summary.get('total_findings', '?')} findings, "
                     f"tools: {', '.join(self.discovery_summary.get('tool_guesses', []))}")
        lines.append(f"  Issues detected: {self.issues_found}")
        for io in self.issue_outcomes:
            lines.append(f"  [{io.status}] {io.issue.kind} at {io.issue.target_path}")
            if io.message:
                lines.append(f"      {io.message}")
        return "\n".join(lines)


# ----------------------------------------------------------------------
# Default UI — stdin/stdout based, suitable for CLI
# ----------------------------------------------------------------------

class SimpleCLIUI:
    """Default UI. Prints progress, asks y/N on stdin."""

    def status(self, msg: str) -> None:
        print(msg, flush=True)

    def error(self, msg: str) -> None:
        print(f"  [error] {msg}", flush=True)

    def confirm(self, plan: orion_selfcheck.RepairPlan) -> bool:
        print()
        print("  Proposed change:")
        for line in plan.proposed_change.splitlines():
            print(f"    {line}")
        print(f"  Rationale: {plan.rationale}")
        print(f"  Reversible by: {plan.reversible_by}")
        try:
            ans = input("  Apply? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return ans in ("y", "yes")


class SilentUI:
    """No prompts. Auto-declines confirmations. For non-interactive runs."""

    def __init__(self, log_sink=None):
        self.log = log_sink or (lambda _m: None)

    def status(self, msg: str) -> None:
        self.log(msg)

    def error(self, msg: str) -> None:
        self.log(f"[error] {msg}")

    def confirm(self, plan: orion_selfcheck.RepairPlan) -> bool:
        self.log(f"[non-interactive] declined to apply change at {plan.issue.target_path}")
        return False


# ----------------------------------------------------------------------
# The cycle itself
# ----------------------------------------------------------------------

def run(context: CycleContext, ui=None) -> CycleOutcome:
    if ui is None:
        ui = SimpleCLIUI() if context.interactive else SilentUI()

    outcome = CycleOutcome(trigger=context.trigger)

    # ---- PERCEIVE ----
    ui.status(f"[{context.trigger}] perceiving host...")
    try:
        report = orion_discover.discover_host(home=context.home, max_depth=4)
    except Exception as e:
        ui.error(f"discovery failed: {e.__class__.__name__}: {e}")
        outcome.cycle_status = "failed"
        return outcome

    outcome.discovery_summary = {
        "total_findings": report.get("total_findings", 0),
        "tool_guesses": report.get("tool_guesses", []),
    }
    ui.status(
        f"  perceived: {outcome.discovery_summary['total_findings']} findings, "
        f"tools: {', '.join(outcome.discovery_summary['tool_guesses']) or '(none)'}"
    )

    # ---- REASON: detect gaps ----
    issues = orion_selfcheck.detect_mcp_gaps(report)
    outcome.issues_found = len(issues)
    ui.status(f"[{context.trigger}] reasoning: {len(issues)} issue(s) detected")

    if not issues:
        outcome.cycle_status = "clean"
        return outcome

    # For each actionable issue: consult → propose → confirm → apply → verify
    # Two actionable classes in v1:
    #   * missing_orion_brain_in_mcp     (edit existing mcp config)
    #   * ai_binary_without_mcp_config   (Layer C — create new integration)
    for issue in issues:
        io = IssueOutcome(issue=issue, status="surfaced")

        # Wake trigger: never consult at wake. Avoids burning fuel quota on
        # every chat start. Explicit /selfcheck or install is where we act.
        if context.trigger == "wake":
            io.message = f"wake trigger — surfaced; /selfcheck to act"
            outcome.issue_outcomes.append(io)
            ui.status(f"  [surfaced] {issue.kind}: {issue.target_path}")
            continue

        # Classes we know how to act on
        if issue.kind == "missing_orion_brain_in_mcp":
            consult_fn = orion_selfcheck.consult_fuel
            action_desc = "wire orion-brain into MCP config"
        elif issue.kind == "ai_binary_without_mcp_config":
            consult_fn = orion_selfcheck.consult_for_unknown_tool
            action_desc = "propose integration for unknown tool (Layer C)"
        else:
            # Unknown issue kind — surface, don't guess
            io.message = f"unrecognized issue class; v1 does not auto-repair"
            outcome.issue_outcomes.append(io)
            ui.status(f"  [surfaced] {issue.kind}: {issue.target_path}")
            continue

        # ---- ACT: consult ----
        ui.status(f"  consulting {context.fuel_preference}: {action_desc} for {issue.target_path}...")
        plan = consult_fn(
            issue, report, fuel_name=context.fuel_preference
        )
        if plan is None:
            io.status = "refused"
            io.message = "fuel returned no plan (uncertain or unavailable)"
            outcome.issue_outcomes.append(io)
            ui.error(io.message)
            continue

        # Validate before showing to user — never propose invalid changes
        valid, vmsg = orion_selfcheck.validate_proposed_change(plan)
        if not valid:
            io.status = "refused"
            io.message = f"validation failed: {vmsg}"
            outcome.issue_outcomes.append(io)
            ui.error(io.message)
            continue

        io.status = "consulted"

        # Confirm with user (via UI — stdin, GUI dialog, whatever)
        ok = ui.confirm(plan)
        if not ok:
            io.message = "user declined"
            outcome.issue_outcomes.append(io)
            continue

        # ---- ACT: apply ----
        applied, amsg = orion_selfcheck.apply_plan(plan, user_confirmed=True)
        if not applied:
            io.status = "refused"
            io.message = f"apply failed: {amsg}"
            outcome.issue_outcomes.append(io)
            ui.error(io.message)
            continue
        io.status = "applied"
        io.message = amsg

        # ---- VERIFY ----
        verified, verify_msg = orion_selfcheck.verify_issue_resolved(issue)
        if verified:
            io.status = "verified"
            io.message = f"{amsg}; {verify_msg}"
            ui.status(f"  [verified] {issue.target_path}")
        else:
            io.status = "applied-unverified"
            io.message = f"{amsg}; VERIFY FAILED: {verify_msg}"
            ui.error(f"apply succeeded but verification failed — check backup")

        outcome.issue_outcomes.append(io)

    return outcome


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main():
    import argparse
    p = argparse.ArgumentParser(description="Orion cognitive cycle runner.")
    p.add_argument("--trigger", default="selfcheck", choices=sorted(VALID_TRIGGERS))
    p.add_argument("--home", default=None, help="discovery root (default: user home)")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--fuel", default="claude-cli")
    args = p.parse_args()

    ctx = CycleContext(
        trigger=args.trigger,
        home=args.home,
        interactive=not args.non_interactive,
        fuel_preference=args.fuel,
    )

    outcome = run(ctx)
    print()
    print(outcome.human_summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
