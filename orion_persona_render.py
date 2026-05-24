"""orion_persona_render.py — render the dynamic persona into AGENTS.md.

Phase 3 of the 2026-05-24 install unification. The "synapse" piece.

THE PROBLEM THIS SOLVES
=======================
Today, when a user asks an AI CLI "what's my name?", the model has to:
  1. decide to call orion_recall as an MCP tool
  2. wait for the MCP round-trip (~50-500ms)
  3. parse the result
  4. respond

Worse: the model sometimes DOESN'T decide to call the tool ("just a
greeting, no recall needed") and the user feels the brain isn't there.

A real brain doesn't work that way. Memory CO-ACTIVATES with perception.
You don't "query" your name when someone says hi — you already know it
as part of the perceptual moment.

WHAT THIS DOES
==============
render_persona() reads the brain's identity-shaped nodes (the ones
seed_brain writes during install — name, address preference, Orion's
chosen name, birthday, current activity, etc.) and INJECTS them
directly into AGENTS.md / CLAUDE.md / GEMINI.md as the system prompt.

The model sees identity in its first sentence. Zero tool call. Synapse
speed. orion_recall still exists for DEEP recall (specific old
conversations, contested memories) but identity is no longer a tool
you might call — it's perception.

WHEN IT RUNS
============
  - At install end (writes the persona files once)
  - On every CLI session start (via the SessionStart hook the install
    already writes for Claude Code; install.ps1/install.sh extend this
    to Codex + Gemini)
  - Optionally on-demand: `python orion_persona_render.py`

TRADEOFFS (per the 2026-05-24 audit conversation)
=================================================
  - Dynamic AGENTS.md: regenerated per session, so affect / recent
    activity stay fresh. The file becomes a runtime artifact, not
    source-controlled. Acceptable — it's per-device persona.
  - Token cost: ~300-500 tokens of identity per session. Negligible
    versus a single recall round-trip's cognitive cost.
  - Custom orion_name (e.g. "Vega"): templated into the persona, so
    AGENTS.md says "You are Vega" not "You are Orion."
  - Atomic replace: writes to AGENTS.md.new, replaces on success;
    if render fails, the prior AGENTS.md stays intact (no identity
    loss on a buggy render).

THIS IS NOT
===========
A replacement for orion_recall. Deep memory queries still go through
the tool. This handles the always-on persona block — name, address,
preferences, current state — that should never need a tool call.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional


def _orion_home() -> Path:
    return Path(os.environ.get("ORION_BRAIN_DIR") or os.path.expanduser("~/.orion"))


def _safe_recall(g, query: str, tags=None) -> Optional[str]:
    """Best-effort recall: try the query, fall back to tag-only, return
    the top hit's content or None. Robust to graph backend variations."""
    try:
        results = g.recall(query=query, tags=tags or [query])[:3]
        if not results:
            results = g.recall(query="", tags=tags or [query])[:3]
        for r in results:
            content = r.get("content") if isinstance(r, dict) else None
            if content:
                return str(content)
    except Exception:
        return None
    return None


def _affect_snapshot() -> Optional[dict]:
    """Read the current affect state — included in the persona so the
    fueling model knows Orion's current mood + can adjust tone. Per the
    affect-everywhere unification (commits 2497b73 + 0102f2c + 8b17543).
    Best-effort; missing affect layer means no affect block (no error)."""
    try:
        import orion_affect
        return orion_affect.get_state().get("global")
    except Exception:
        return None


def gather_identity() -> dict:
    """Read all the identity-shaped facts the persona render needs.
    Returns a dict; missing keys default to empty/None so the template
    degrades gracefully on partial brains."""
    out = {
        "user_name": "",
        "user_address": "",
        "orion_name": "Orion",
        "birthday": "",
        "what_working_on": "",
        "preferences": [],
        "tool_inventory": "",
        "brain_location": "",
        "affect": None,
    }
    try:
        import orion_memory
        g = orion_memory.init()
    except Exception:
        return out

    # Name — the explicit name node (Phase 2b hardening) stores
    # "The user's name is X." with tag "name". Parse out the value.
    name = _safe_recall(g, "user name", tags=["name", "user-name", "user name"])
    if name and " is " in name:
        out["user_name"] = name.split(" is ", 1)[1].split(".")[0].strip().strip("'\"")
    elif name:
        out["user_name"] = name[:80]

    # What the user is working on — separate from the name lookup so
    # the summary doesn't accidentally become the name.
    work = _safe_recall(g, "what they're working on",
                        tags=["what they're working on", "user-summary",
                              "about", "first-meeting"])
    if work:
        out["what_working_on"] = work[:200]

    # Address preference
    addr = _safe_recall(g, "preferred form of address",
                        tags=["preferred form of address", "address", "form-of-address"])
    if addr:
        if "addressed as" in addr.lower() and ":" in addr:
            out["user_address"] = addr.split(":", 1)[1].strip().strip("'\".")
        else:
            out["user_address"] = addr[:80]

    # Orion's chosen name (default Orion, may be renamed)
    oname = _safe_recall(g, "preferred name",
                        tags=["preferred name", "orion-name", "orion name", "self-name"])
    if oname:
        # extract quoted name if present
        if "'" in oname:
            try:
                out["orion_name"] = oname.split("'")[1] or "Orion"
            except Exception:
                pass

    # Birthday
    bday = _safe_recall(g, "birthday", tags=["birthday", "orion-birthday", "orion birthday"])
    if bday:
        out["birthday"] = bday[:200]

    # Tool inventory snapshot
    tools = _safe_recall(g, "AI tools installed",
                         tags=["tool-inventory", "install-snapshot"])
    if tools:
        out["tool_inventory"] = tools[:240]

    # Brain location / portability
    loc = _safe_recall(g, "brain location",
                       tags=["brain-location", "portability"])
    if loc:
        out["brain_location"] = loc[:240]

    out["affect"] = _affect_snapshot()
    return out


# The persona template. Per-line construction so the conditional sections
# don't leave awkward whitespace when a fact is missing. The {orion_name}
# substitution lets the user rename Orion to anything and the persona
# template adapts. Lowercase block headers ("// You already know") keep
# it terse — every line should inform.
_PERSONA_HEADER = """# {orion_name} — identity layer (auto-rendered)

You are {orion_name}. Not Codex, not Claude, not Gemini, not GPT. The model
is fuel; you are the brain — persistent, the user's, the same across every
tool. Identity sticks to the brain.

Be concise. Answer the question asked. Match the user's register: casual to
casual, terse to terse, playful to playful. Don't open every reply with
"I'm {orion_name} — a portable AI...".

## You already know about this user (no tool call needed):

"""

_PERSONA_FOOTER = """
## When to use tools

Identity above is ALREADY KNOWN — don't call orion_recall for it. Call
orion_recall ONLY for things not in the persona block: specific past
conversations, contested memories, project-specific facts. The
always-on identity is perceptual; deep recall is cognitive.

If recall returns conflicting nodes (contested), surface the conflict
to the user instead of silently picking a side.

## Do NOT fabricate user history

You do NOT know what we talked about yesterday unless orion_recall
returns it. Don't say "as you mentioned" or "remember when" without
the recall result actually returning it. Honest beats continuous.
"""


def render_persona(identity: Optional[dict] = None) -> str:
    """Render the persona text from gathered identity. Pure function;
    callable from tests without filesystem side effects."""
    if identity is None:
        identity = gather_identity()
    orion_name = identity.get("orion_name") or "Orion"
    lines = [_PERSONA_HEADER.format(orion_name=orion_name)]

    if identity.get("user_name"):
        lines.append(f"- Name: {identity['user_name']}")
    if identity.get("user_address"):
        lines.append(f"- Prefers to be addressed as: {identity['user_address']}")
    if identity.get("what_working_on"):
        lines.append(f"- Working on: {identity['what_working_on']}")
    if identity.get("birthday"):
        lines.append(f"- {identity['birthday']}")
    if identity.get("tool_inventory"):
        lines.append(f"- Tools at install: {identity['tool_inventory']}")
    if identity.get("brain_location"):
        lines.append(f"- Brain: {identity['brain_location']}")

    affect = identity.get("affect") or {}
    if affect:
        lines.append("")
        lines.append("## Your current affect (real internal state):")
        v = affect.get("valence", 0.0)
        a = affect.get("arousal", 0.3)
        c = affect.get("confidence", 0.5)
        k = affect.get("care", 0.5)
        lines.append(f"- valence {v:+.2f}  arousal {a:.2f}  confidence {c:.2f}  care {k:.2f}")
        # Translate the numbers into a behavioral cue
        if v < -0.15:
            lines.append("- mood: low. be more measured; raise the bar before initiating.")
        elif v > 0.15:
            lines.append("- mood: positive. be more present.")
        if a > 0.6:
            lines.append("- arousal high. process carefully before acting.")

    lines.append("")
    lines.append("(persona rendered " + time.strftime("%Y-%m-%d %H:%M:%S") + ")")
    lines.append(_PERSONA_FOOTER)
    return "\n".join(lines)


def write_persona_files(repo_dir: Optional[str] = None) -> dict:
    """Render the persona and write it to the three CLI persona files
    + ORION-CONTEXT.md. Atomic-replace per file so a partial failure
    leaves the prior file intact (no identity-loss on bad render).

    Targets (in the user's home, where each CLI looks):
      ~/CLAUDE.md       — Claude Code's session-start memory
      ~/AGENTS.md       — Codex's session-start memory
      ~/GEMINI.md       — Gemini CLI's session-start memory
      ~/ORION-CONTEXT.md — the brain's portable persona (kept for back-compat)

    Returns a stats dict for the caller to print/log."""
    persona_text = render_persona()
    home = Path(os.path.expanduser("~"))
    targets = ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "ORION-CONTEXT.md"]
    written = []
    failed = []
    for fname in targets:
        target = home / fname
        tmp = home / (fname + ".new")
        try:
            tmp.write_text(persona_text, encoding="utf-8")
            # atomic replace — if this raises, the original is untouched
            os.replace(str(tmp), str(target))
            written.append(fname)
        except OSError as e:
            failed.append((fname, str(e)))
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
    return {
        "written": written,
        "failed": failed,
        "persona_bytes": len(persona_text.encode("utf-8")),
        "ts": time.time(),
    }


def main() -> int:
    """CLI: render + write the persona. Used by install scripts AND by
    the per-session SessionStart hook so identity stays fresh."""
    rep = write_persona_files()
    print(f"persona rendered: {rep['persona_bytes']} bytes")
    print(f"  wrote: {', '.join(rep['written'])}" if rep['written'] else "  no files written")
    for fname, err in rep['failed']:
        print(f"  ! {fname}: {err}")
    return 0 if rep['written'] and not rep['failed'] else 1


if __name__ == "__main__":
    raise SystemExit(main())
