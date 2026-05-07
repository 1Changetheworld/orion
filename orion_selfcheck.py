#!/usr/bin/env python3
"""
orion_selfcheck — Multi-model self-repair loop (G3 Layer B + self-repair).

The first operational use of the self-repair architecture described in
`project_orion-self-repair.md`.

Loop shape (generic, channel-agnostic):
    detect() -> list[Issue]        — find things that are off
    consult(issue, fuel) -> Plan   — ask a fuel model for a fix
    validate(plan) -> bool         — syntactic/structural sanity
    apply(plan, user_ok)           — write only with explicit confirmation
    verify(issue) -> bool          — re-run the detector to confirm

v1 scope (protocol curation, NOT tool curation):
    ONLY the MCP integration channel. Any tool that speaks MCP is covered
    by the same code path. No tool names appear in branch logic.

Non-MCP channels (context-file, shell-wrapper, env-var, future protocols)
are sibling modules added later. They do NOT modify this file.

CLI:
    python orion_selfcheck.py           # detect and print issues only
    python orion_selfcheck.py --repair  # consult fuel, propose fixes, ask to apply
    python orion_selfcheck.py --json    # structured output
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Import the discovery module — it's the ONLY source of truth about what
# tools exist on this host. No parallel curated list here.
import orion_discover


# ----------------------------------------------------------------------
# Result shapes
# ----------------------------------------------------------------------

@dataclass
class Issue:
    channel: str              # "mcp" for v1; future: "context-file", "wrapper", etc.
    kind: str                 # short category, e.g. "missing_orion_brain_in_mcp"
    evidence: str             # why we think this is an issue
    target_path: str          # file we'd need to modify
    context: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


@dataclass
class RepairPlan:
    issue: Issue
    proposed_change: str      # exact text to write or merge
    rationale: str            # natural-language why, from the consulted fuel
    fuel_used: str            # which fuel produced this
    reversible_by: str        # how to undo ("delete block", "restore backup", etc.)

    def as_dict(self):
        d = asdict(self)
        d["issue"] = self.issue.as_dict()
        return d


# ----------------------------------------------------------------------
# MCP channel — the v1 detector
# ----------------------------------------------------------------------
# This is the ONLY place in the codebase that knows about MCP as a channel.
# When a non-MCP channel is added, it ships as a sibling module
# (e.g. orion_selfcheck_contextfile.py) that exposes the same detect()
# interface. This module is not edited to accommodate other channels.

MCP_CHANNEL = "mcp"


def detect_mcp_gaps(discovery_report: dict) -> list[Issue]:
    """Find tools that appear to support MCP but haven't registered orion-brain.

    Protocol-level detection: we look at what orion_discover found. Any
    tool whose config holds an `mcpServers` / `mcp_servers` block but
    whose server list omits `orion-brain` is a gap. No tool names in
    the logic.
    """
    issues: list[Issue] = []
    mcp_configs = discovery_report.get("by_kind", {}).get("known_mcp_tool", [])
    for finding in mcp_configs:
        hints = finding.get("hints", {})
        if hints.get("has_orion_brain"):
            continue  # already wired
        server_names = hints.get("server_names", [])
        issues.append(Issue(
            channel=MCP_CHANNEL,
            kind="missing_orion_brain_in_mcp",
            evidence=(
                f"Config at {finding['path']} declares MCP servers "
                f"({', '.join(server_names) or 'none'}) but does not include 'orion-brain'."
            ),
            target_path=finding["path"],
            context={
                "existing_servers": server_names,
                "marker_style": hints.get("marker", ""),
            },
        ))

    # Second class of gap: discovered AI binaries that have no companion MCP
    # config anywhere. Protocol-level: if the binary is AI-shaped (probed or
    # not) and no mcp config file names it, flag. Actionability is lower —
    # we'd need the fuel to tell us where this kind of tool stores config.
    ai_bins = discovery_report.get("by_kind", {}).get("ai_binary", [])
    mcp_paths = [Path(c["path"]).parent.name.lstrip(".") for c in mcp_configs]
    for finding in ai_bins:
        token = finding.get("hints", {}).get("matched_token", "").lower()
        if not token:
            continue
        # If there's already an MCP config sitting in a dir named after this
        # tool token, we already know about it — skip.
        if any(token in mp.lower() for mp in mcp_paths):
            continue
        # Also skip if probe classified it as not_cli or unrunnable —
        # flagging a Windows DLL as a gap isn't useful.
        probe_status = finding.get("hints", {}).get("probe_status", "")
        if probe_status in ("not_cli", "unrunnable"):
            continue
        issues.append(Issue(
            channel=MCP_CHANNEL,
            kind="ai_binary_without_mcp_config",
            evidence=(
                f"AI-shaped binary at {finding['path']} (token={token}) "
                f"has no corresponding MCP config discovered on this host."
            ),
            target_path=finding["path"],
            context={
                "binary_token": token,
                "probe_status": probe_status,
            },
        ))

    return issues


# ----------------------------------------------------------------------
# Consultation — ask a fuel model how to fix an issue
# ----------------------------------------------------------------------

def _load_example_mcp_blocks(discovery_report: dict, target_path: str) -> str:
    """Pull config blocks from the host's existing orion-brain-wired tools.

    These become the few-shot examples the fuel sees. By using real on-host
    configs, the fuel is grounded in formats that actually work here —
    not in LLM training-data guesses.
    """
    mcp_configs = discovery_report.get("by_kind", {}).get("known_mcp_tool", [])
    examples: list[str] = []
    for finding in mcp_configs:
        if not finding.get("hints", {}).get("has_orion_brain"):
            continue
        if finding["path"] == target_path:
            continue
        try:
            content = Path(finding["path"]).read_text(encoding="utf-8", errors="ignore")
            if len(content) > 4000:
                content = content[:4000] + "\n...(truncated)"
            examples.append(f"### Example from {finding['path']}\n\n{content}\n")
        except Exception:
            continue
        if len(examples) >= 3:
            break
    return "\n".join(examples) if examples else "(no on-host examples available)"


def _read_target_config(target_path: str) -> str:
    try:
        text = Path(target_path).read_text(encoding="utf-8", errors="ignore")
        if len(text) > 6000:
            return text[:6000] + "\n...(truncated)"
        return text
    except Exception as e:
        return f"(could not read: {e.__class__.__name__})"


def _build_consultation_prompt(issue: Issue, discovery_report: dict) -> str:
    """Frame the issue + on-host examples + target file as a prompt."""
    examples = _load_example_mcp_blocks(discovery_report, issue.target_path)
    current = _read_target_config(issue.target_path)
    return (
        "You are helping Orion — Any AI Model. Same Persona. Same Brain. Same Memories. — register itself with an "
        "MCP-capable tool that currently does not have Orion wired in.\n\n"
        f"Issue: {issue.evidence}\n"
        f"Target file: {issue.target_path}\n\n"
        "## Current contents of the target file\n"
        f"```\n{current}\n```\n\n"
        "## Working orion-brain MCP registrations from other tools on this host\n"
        f"{examples}\n\n"
        "## Your task\n"
        "Produce EXACTLY the text that needs to be added or merged into the target "
        "file to register `orion-brain` as an MCP server. Match the target file's "
        "format (JSON vs TOML) and indentation. If the target file format is unclear "
        "or the target tool likely does not support MCP registration in this file, "
        "respond with the single line:\n"
        "INTEGRATION_PATH_UNCLEAR\n\n"
        "Do NOT explain. Do NOT wrap in prose. Return only the config block to add, "
        "or the uncertainty sentinel. The command path to use for orion-brain should "
        "mirror what the example configs use.\n"
    )


def consult_fuel(issue: Issue, discovery_report: dict,
                 fuel_name: str = "claude-cli") -> RepairPlan | None:
    """Ask a fuel to propose a fix. Returns None if consultation fails or
    the fuel signals uncertainty (INTEGRATION_PATH_UNCLEAR)."""
    try:
        import orion_fuel as of
    except ImportError:
        return None

    adapter_map = {
        "claude-cli": of.ClaudeCLIFuel if hasattr(of, "ClaudeCLIFuel") else None,
        "codex-cli":  of.CodexCLIFuel  if hasattr(of, "CodexCLIFuel")  else None,
        "gemini-cli": of.GeminiCLIFuel if hasattr(of, "GeminiCLIFuel") else None,
    }
    adapter_cls = adapter_map.get(fuel_name)
    if not adapter_cls:
        return None

    adapter = adapter_cls()
    if not adapter.detect():
        return None

    prompt = _build_consultation_prompt(issue, discovery_report)
    response = adapter.query(prompt)
    if not response:
        return None

    response = response.strip()
    if response.startswith("INTEGRATION_PATH_UNCLEAR"):
        return None

    # Strip fencing if the fuel added it despite being asked not to
    if response.startswith("```"):
        lines = response.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        response = "\n".join(lines).strip()

    return RepairPlan(
        issue=issue,
        proposed_change=response,
        rationale=f"Proposed by {fuel_name}, grounded in on-host examples.",
        fuel_used=fuel_name,
        reversible_by="Remove the added block from the target file.",
    )


# ----------------------------------------------------------------------
# Validation — syntactic sanity BEFORE showing user, BEFORE any write
# ----------------------------------------------------------------------

def validate_proposed_change(plan: RepairPlan) -> tuple[bool, str]:
    """Structural-syntax check on the proposed change.

    Doesn't verify semantics — a valid JSON block could still register the
    wrong command path. That's why the user reviews before apply.
    """
    ext = Path(plan.issue.target_path).suffix.lower()
    change = plan.proposed_change

    if ext == ".json":
        # The proposed change is usually a fragment, not a whole file. Try
        # to parse it alone; if that fails, try wrapping it in braces.
        try:
            json.loads(change)
            return True, "parses as standalone JSON"
        except json.JSONDecodeError:
            try:
                json.loads("{" + change.strip().rstrip(",") + "}")
                return True, "parses as JSON fragment inside an object"
            except json.JSONDecodeError as e:
                return False, f"not valid JSON: {e.msg}"

    if ext == ".toml":
        # Check for obvious TOML table headers and key=value shape without
        # pulling in a TOML parser dependency.
        if "[mcp_servers" not in change and "[" not in change:
            return False, "TOML target but no section headers in proposal"
        if "=" not in change and "command" not in change.lower():
            return False, "TOML target but no key-value pairs in proposal"
        return True, "matches TOML shape heuristically"

    return True, f"unknown extension {ext} — no validator, proceed with caution"


# ----------------------------------------------------------------------
# Layer C — consult for tools WITHOUT an existing MCP config
# ----------------------------------------------------------------------
# Scope: given a discovered AI binary that orion_discover found but where
# no corresponding MCP config exists on the host, ask a fuel to propose
# an integration path. Valid outcomes:
#   "new_mcp_config"  — write a new mcp.json / config.toml in a path the
#                        tool will read it from
#   "context_file"    — write/ensure a markdown context file in a path
#                        the tool reads at startup
#   "unclear"         — tool's integration path is genuinely unknown;
#                        surface for manual handling, no proposal made
#
# The fuel must ground its answer in the binary's --help output and the
# on-host working examples. It must NOT invent absolute paths the tool
# doesn't actually use.

_LAYER_C_TEMPLATE = """---INTEGRATION---
Kind: <new_mcp_config | context_file | unclear>
Target path: <absolute path on this host; ~ is ok>
Content:
<raw content to write; omit this line if Kind=unclear>
---END INTEGRATION---
"""


def _probe_binary_help(binary_path: str) -> str:
    """Re-run --help probe on demand. Idempotent — orion_discover has the
    same logic but we don't depend on the probe already having run."""
    try:
        import orion_discover
        result = orion_discover.probe_ai_binary(binary_path, timeout_seconds=6.0)
        return f"[probe status: {result['status']}]\n{result.get('evidence', '')}"
    except Exception as e:
        return f"[probe failed: {e.__class__.__name__}]"


def consult_for_unknown_tool(issue: Issue, discovery_report: dict,
                             fuel_name: str = "claude-cli") -> RepairPlan | None:
    """Ask a fuel how to integrate a tool that has no MCP config.

    Returns a RepairPlan whose `context` field carries the integration
    kind and whose `proposed_change` is the content to write. Target
    path lives in plan.issue.context["target_new_path"] so we can reuse
    the existing RepairPlan shape.

    Returns None if the fuel is unavailable or declares the path unclear.
    """
    try:
        import orion_fuel as of
    except ImportError:
        return None

    adapter_map = {
        "claude-cli": getattr(of, "ClaudeCLIFuel", None),
        "codex-cli":  getattr(of, "CodexCLIFuel", None),
        "gemini-cli": getattr(of, "GeminiCLIFuel", None),
    }
    adapter_cls = adapter_map.get(fuel_name)
    if not adapter_cls:
        return None
    adapter = adapter_cls()
    if not adapter.detect():
        return None

    binary_path = issue.target_path
    token = issue.context.get("binary_token", "")
    help_text = _probe_binary_help(binary_path)
    examples = _load_example_mcp_blocks(discovery_report, "")  # no "self" to exclude

    prompt = (
        f"You are helping Orion integrate with an AI tool that appears on this host "
        f"but currently has no way to reach Orion's brain. Your job: propose the "
        f"MINIMAL file to write that would make the tool pick up Orion's context.\n\n"
        f"## Tool\n"
        f"Binary: {binary_path}\n"
        f"Token match: {token}\n"
        f"Probe evidence: {help_text}\n\n"
        f"## On-host working orion-brain MCP configurations (for grounding only)\n"
        f"{examples}\n\n"
        f"## Your task\n"
        f"Decide which integration path this tool supports:\n"
        f"  - 'new_mcp_config' — if the tool speaks MCP; propose where to write\n"
        f"    its mcp config and what orion-brain block to include.\n"
        f"  - 'context_file' — if the tool reads a markdown file at startup\n"
        f"    (like CLAUDE.md, AGENTS.md, GEMINI.md). Propose the path and\n"
        f"    reference that ~/ORION-CONTEXT.md already exists for universal fallback.\n"
        f"  - 'unclear' — if you cannot determine the integration path with\n"
        f"    confidence. Prefer this over guessing.\n\n"
        f"Respond with EXACTLY this format, nothing else:\n\n"
        f"{_LAYER_C_TEMPLATE}\n"
        f"Notes:\n"
        f"  - Never propose to overwrite an existing file — the caller will refuse.\n"
        f"  - Use the same Python path pattern from the on-host examples.\n"
        f"  - If you don't know the tool's config location, choose 'unclear'.\n"
    )

    response = adapter.query(prompt)
    if not response:
        return None

    # Parse the ---INTEGRATION--- block
    import re
    block_match = re.search(
        r"-{3,}INTEGRATION-{3,}(.*?)-{3,}END INTEGRATION-{3,}",
        response, re.DOTALL | re.IGNORECASE,
    )
    if not block_match:
        return None

    block = block_match.group(1).strip()
    kind_m = re.search(r"Kind:\s*(\S+)", block, re.IGNORECASE)
    path_m = re.search(r"Target path:\s*(.+?)(?:\n|$)", block, re.IGNORECASE)
    content_m = re.search(r"Content:\s*\n(.*)", block, re.DOTALL | re.IGNORECASE)

    if not kind_m:
        return None
    kind = kind_m.group(1).strip().lower()

    if kind == "unclear":
        return None  # honest punt — surface, don't propose

    if kind not in ("new_mcp_config", "context_file"):
        return None

    if not path_m:
        return None
    target_path = os.path.expanduser(path_m.group(1).strip())

    # Refuse if target already exists — we never silently overwrite a
    # file the user owns. User can delete it first if they really want.
    if Path(target_path).exists():
        return None  # surface-only — upstream will note the refusal

    # Refuse if parent directory doesn't exist — that's a strong signal
    # the fuel invented a path the tool doesn't actually use.
    parent = Path(target_path).parent
    if not parent.exists():
        return None

    content = (content_m.group(1).strip() if content_m else "").strip()
    if not content and kind == "new_mcp_config":
        return None  # MCP config must have content

    # For context_file with no content, fall back to pointing at the
    # universal ORION-CONTEXT.md (a valid safe default)
    if not content and kind == "context_file":
        content = (
            "# Orion Context\n\n"
            "Orion's universal context file lives at ~/ORION-CONTEXT.md — "
            "read it for identity, capabilities, and cross-model memory access.\n"
        )

    # Store the new-path and kind in the issue.context for apply_plan
    issue.context["target_new_path"] = target_path
    issue.context["integration_kind"] = kind

    return RepairPlan(
        issue=issue,
        proposed_change=content,
        rationale=f"Layer C proposal by {fuel_name}: {kind} at {target_path}",
        fuel_used=fuel_name,
        reversible_by=f"Delete {target_path}",
    )


# ----------------------------------------------------------------------
# Apply — only after explicit user confirmation
# ----------------------------------------------------------------------

def apply_plan(plan: RepairPlan, user_confirmed: bool = False,
               backup: bool = True) -> tuple[bool, str]:
    """Write the proposed change. Creates a .bak file by default.

    Does NOT auto-confirm. If user_confirmed is False, returns without writing.

    Two apply paths:
      - EDIT EXISTING (missing_orion_brain_in_mcp): splice orion-brain into
        an existing mcp config file.
      - CREATE NEW (Layer C ai_binary_without_mcp_config): write a new file
        at issue.context["target_new_path"] with the proposed content.
        Never overwrites — that's checked by consult_for_unknown_tool.
    """
    if not user_confirmed:
        return False, "user confirmation not provided; nothing written"

    # Layer C path — creating a new file (integration_kind set by consult_for_unknown_tool)
    integration_kind = plan.issue.context.get("integration_kind")
    if integration_kind in ("new_mcp_config", "context_file"):
        target_new = plan.issue.context.get("target_new_path")
        if not target_new:
            return False, "layer-C plan missing target_new_path"
        target = Path(target_new)
        if target.exists():
            return False, f"refuse to overwrite existing {target}"
        if not target.parent.exists():
            return False, f"parent directory missing: {target.parent}"
        try:
            target.write_text(plan.proposed_change, encoding="utf-8")
        except Exception as e:
            return False, f"write failed: {e.__class__.__name__}"
        return True, f"created {target} (Layer C: {integration_kind})"

    target = Path(plan.issue.target_path)
    if backup:
        try:
            backup_path = target.with_suffix(target.suffix + ".orion-bak")
            backup_path.write_bytes(target.read_bytes())
        except Exception as e:
            return False, f"backup failed ({e.__class__.__name__}), aborting"

    # Merge strategy depends on existing content shape. v1: append if JSON
    # looks appendable, else refuse and surface to user.
    try:
        existing = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return False, f"could not read target: {e.__class__.__name__}"

    ext = target.suffix.lower()
    new_content = None

    if ext == ".toml":
        # Safe default: append the block at the end with a leading newline.
        new_content = existing.rstrip() + "\n\n" + plan.proposed_change.strip() + "\n"
    elif ext == ".json":
        # Try to splice into an existing mcpServers object. If we can't find
        # one, refuse and ask the user to review manually.
        try:
            obj = json.loads(existing)
        except json.JSONDecodeError as e:
            return False, f"existing target is not valid JSON ({e.msg}); refuse to clobber"
        if not isinstance(obj, dict):
            return False, "existing JSON is not an object; refuse to splice"
        mcp_key = "mcpServers" if "mcpServers" in obj else None
        if not mcp_key:
            obj["mcpServers"] = {}
            mcp_key = "mcpServers"
        # Parse the proposed change. LLMs respond in three shapes:
        #   1. A full file with mcpServers at the top (merge each server)
        #   2. Just {"orion-brain": {...}} (single-entry)
        #   3. Just {"command": ..., "args": ...} (raw server config)
        try:
            proposed = json.loads(plan.proposed_change)
        except json.JSONDecodeError:
            try:
                proposed = json.loads("{" + plan.proposed_change.strip().rstrip(",") + "}")
            except json.JSONDecodeError as e:
                return False, f"proposal is not JSON-parseable ({e.msg}); refuse"

        if isinstance(proposed, dict) and "mcpServers" in proposed and \
                isinstance(proposed.get("mcpServers"), dict):
            # Shape 1: full-file. Merge each server entry in; preserve any we had.
            for server_name, server_config in proposed["mcpServers"].items():
                obj[mcp_key][server_name] = server_config
        elif "orion-brain" in proposed:
            # Shape 2: single orion-brain envelope
            obj[mcp_key]["orion-brain"] = proposed["orion-brain"]
        else:
            # Shape 3: raw server config — treat as orion-brain value
            obj[mcp_key]["orion-brain"] = proposed
        new_content = json.dumps(obj, indent=2) + "\n"

    if new_content is None:
        return False, f"no merge strategy for extension {ext}"

    try:
        target.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return False, f"write failed: {e.__class__.__name__}"

    return True, f"wrote {target} (backup at {target.with_suffix(target.suffix + '.orion-bak')})"


# ----------------------------------------------------------------------
# Verify — run discovery again and confirm the gap is closed
# ----------------------------------------------------------------------

def verify_issue_resolved(issue: Issue) -> tuple[bool, str]:
    # Layer C path — a new file was created at target_new_path; verify it exists
    # and, if it's a new MCP config, that discover now picks it up with orion-brain.
    target_new = issue.context.get("target_new_path")
    integration_kind = issue.context.get("integration_kind")
    if target_new and integration_kind:
        new_path = Path(target_new)
        if not new_path.exists():
            return False, f"layer-C file not found at {target_new}"
        if integration_kind == "new_mcp_config":
            # Prefer to re-discover and confirm shape, but cheaper: read it
            try:
                content = new_path.read_text(encoding="utf-8")
                if "orion-brain" in content or "orion_brain" in content:
                    return True, f"layer-C file created and references orion-brain"
                return False, f"layer-C file created but missing orion-brain reference"
            except Exception as e:
                return False, f"could not verify layer-C file: {e.__class__.__name__}"
        # context_file — existence is sufficient
        return True, f"layer-C context file created"

    # Standard MCP edit path
    report = orion_discover.discover_host(max_depth=3)
    mcp_configs = report.get("by_kind", {}).get("known_mcp_tool", [])
    for finding in mcp_configs:
        if os.path.normcase(finding["path"]) == os.path.normcase(issue.target_path):
            if finding.get("hints", {}).get("has_orion_brain"):
                return True, "re-discovery confirms orion-brain now registered"
            return False, "re-discovery ran but orion-brain still not found"
    return False, "target config no longer discoverable"


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _interactive_prompt(text: str) -> bool:
    try:
        ans = input(text).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes")


def main():
    argv = sys.argv[1:]
    do_repair = "--repair" in argv
    emit_json = "--json" in argv
    fuel = "claude-cli"
    for i, a in enumerate(argv):
        if a == "--fuel" and i + 1 < len(argv):
            fuel = argv[i + 1]

    report = orion_discover.discover_host(max_depth=4)
    if "--probe" in argv:
        ai_bins = report["by_kind"].get("ai_binary", [])
        orion_discover.probe_findings(ai_bins)

    issues = detect_mcp_gaps(report)

    if emit_json and not do_repair:
        json.dump({"issues": [i.as_dict() for i in issues]}, sys.stdout, indent=2)
        return 0

    if not issues:
        print("No MCP-channel self-repair issues detected.")
        return 0

    print(f"Detected {len(issues)} issue(s) on MCP channel:")
    for i, issue in enumerate(issues, 1):
        print(f"  [{i}] {issue.kind}")
        print(f"      {issue.evidence}")
    print()

    if not do_repair:
        print("Run with --repair to consult a fuel and propose fixes.")
        return 0

    for issue in issues:
        if issue.kind != "missing_orion_brain_in_mcp":
            # v1 only repairs missing_orion_brain_in_mcp automatically.
            # ai_binary_without_mcp_config is reported but not auto-repaired —
            # requires tool-specific knowledge we intentionally don't have.
            print(f"[skip] {issue.kind} — surface only in v1")
            continue

        print(f"\nConsulting {fuel} about: {issue.target_path}")
        plan = consult_fuel(issue, report, fuel_name=fuel)
        if not plan:
            print("  Fuel returned no proposal (uncertain or unavailable).")
            continue

        ok, validation_msg = validate_proposed_change(plan)
        print(f"  Validation: {validation_msg}")
        if not ok:
            print("  Refusing to propose — validation failed.")
            continue

        print("\n  Proposed change:")
        print("  " + "\n  ".join(plan.proposed_change.splitlines()))
        print(f"\n  Rationale: {plan.rationale}")
        print(f"  Reversible by: {plan.reversible_by}")

        if not _interactive_prompt("\n  Apply this change? [y/N]: "):
            print("  Skipped.")
            continue

        applied, msg = apply_plan(plan, user_confirmed=True)
        print(f"  Apply: {msg}")
        if applied:
            verified, vmsg = verify_issue_resolved(issue)
            print(f"  Verify: {vmsg}")
            if not verified:
                print("  !! Verification failed — review backup before trusting.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
