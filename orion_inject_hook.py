#!/usr/bin/env python3
"""orion_inject_hook.py — per-turn memory injection (the bloodstream).

THE point of this hook: stop making the model CHOOSE to remember. Before every
user turn, pull the relevant slice of Orion's memory from the canonical brain
and inject it straight into the model's context. The model no longer has to call
a tool — the past it needs is already in front of it. This is the proven
bottleneck (recall is fine; injection was missing) and the foundation a
self-model / will layer later draws on.

Cohesive + network-native by design:
  - Talks to the brain over HTTP (ORION_BRAIN_HTTP_URL, default the local
    canonical :5556). On a secondary device this points at the canonical brain
    via the vessel binding — so injection is served from the ONE brain across
    the network, not a per-machine copy. Memory location stops being a per-host
    limit; the network is the brain.
  - Fail-SILENT and fast (short timeout): a hook must NEVER block or break the
    user's turn. No brain / slow brain → inject nothing, turn proceeds.

Wiring (Claude Code, ~/.claude/settings.json):
  "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command",
    "command": "/usr/bin/python3 /Users/servermac/orion-code/orion_inject_hook.py"}]}]}
Codex/Gemini get equivalent per-turn hooks as their hook surfaces allow
(follow-up); the brain-side recall is identical, so the layer stays cohesive.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BRAIN_URL = os.environ.get("ORION_BRAIN_HTTP_URL", "http://127.0.0.1:5556").rstrip("/")
AUTH_PATH = os.path.expanduser(os.environ.get("ORION_AUTH_TOKEN_PATH", "~/.orion/auth-token"))
RECALL_LIMIT = int(os.environ.get("ORION_INJECT_LIMIT", "6"))
TIMEOUT = float(os.environ.get("ORION_INJECT_TIMEOUT", "3.5"))
MAX_CHARS = int(os.environ.get("ORION_INJECT_MAX_CHARS", "1800"))  # token budget guard


def _surface() -> str:
    """Which surface is this hook running under (claude/codex/gemini)? Set per
    CLI via `--surface <name>` in the hook command or ORION_SURFACE. This is
    what makes 'we last spoke in codex' attributable instead of generic."""
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == "--surface" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--surface="):
            return a.split("=", 1)[1]
    return os.environ.get("ORION_SURFACE", "cli")


def _recent_block() -> str:
    """Fetch the last few real turns across ALL windows and format them. This is
    the shared short-term memory that makes three CLIs feel like one mind behind
    three windows — repeat a question in a new window and Orion can notice."""
    try:
        token = open(AUTH_PATH, encoding="utf-8").read().strip()
    except Exception:
        return ""
    req = urllib.request.Request(
        f"{BRAIN_URL}/recent?limit=8",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            turns = (json.loads(r.read()) or {}).get("turns") or []
    except Exception:
        return ""
    if not turns:
        return ""
    lines = []
    for t in turns:
        when = (t.get("iso") or "")[11:16]
        who = "you" if t.get("role") == "user" else "Orion"
        lines.append(f"[{t.get('surface','?')} · {who} {when}] {t.get('text','')}")
    return "\n".join(lines)


def _resume_block() -> str:
    """The most recent 'where we left off' marker(s), so a freshly opened window
    can pick a prior thread back up — auto-remember-on-close, surfaced."""
    try:
        token = open(AUTH_PATH, encoding="utf-8").read().strip()
    except Exception:
        return ""
    req = urllib.request.Request(f"{BRAIN_URL}/resume?limit=2",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            sessions = (json.loads(r.read()) or {}).get("sessions") or []
    except Exception:
        return ""
    if not sessions:
        return ""
    lines = []
    for s in sessions:
        when = (s.get("iso") or "")[:16].replace("T", " ")
        topic = ", ".join(s.get("topic") or []) or "(general)"
        lines.append(f"[{s.get('surface','?')} · {when}] topic: {topic}"
                     f"\n   you: {s.get('last_user','')}"
                     f"\n   Orion: {s.get('last_orion','')}")
    return "\n".join(lines)


# Prompts that arrive on the UserPromptSubmit hook but are NOT the user
# speaking: persona re-renders, heartbeat pokes, intent-extraction probes, and
# other machine-authored turns. Before this filter (2026-08-24) they were logged
# as inbound USER contact, so "when did we last speak" was partly measuring
# Orion's own scaffolding instead of James. Match is on a normalized prefix.
_SYNTHETIC_PREFIXES = (
    "# orion — identity layer",
    "# orion - identity layer",
    "you are orion — a personal ai intelligence layer",
    "you are orion - a personal ai intelligence layer",
    "read heartbeat.md if it exists",
    "extract any explicit or implicit personal intents",
    "reply with only:",
    "is this action both safe and correct to perform right now",
    "# agents.md instructions for",
)


def _is_synthetic(prompt: str) -> bool:
    """True when this turn was machine-authored, not the user speaking.

    Canonical definition lives in orion_temporal (the module that owns "when
    did we last speak"); the tuple above is a fail-silent fallback only, so the
    hook still works if that import is unavailable. Do not let the two drift —
    edit orion_temporal.SYNTHETIC_PREFIXES.
    """
    try:
        import orion_temporal
        return orion_temporal.is_synthetic_turn(prompt)
    except Exception:
        pass
    p = (prompt or "").strip().lower()
    if not p:
        return True
    return any(p.startswith(pref) for pref in _SYNTHETIC_PREFIXES)


def _provenance(prompt: str):
    """Decide, from EVIDENCE, whether this turn is Orion's own or the world's (§3).

    Priority, strongest evidence first:
      1. env stamp        — a producer explicitly declared itself (ORION_PROVENANCE)
      2. efference ticket — Orion issued this exact prompt through the fuel funnel
      3. prefix stopgap   — is_synthetic_turn; CRUDE, kept for one cycle (§8.3) and
                            deleted once 1+2 carry everything. meta.mechanism reports
                            which rule fired, so we can measure before deleting.
    Returns (provenance, actor, mechanism).
    """
    env = (os.environ.get("ORION_PROVENANCE") or "").strip().lower()
    if env in ("self", "external"):
        return env, (os.environ.get("ORION_ACTOR")
                     or ("orion" if env == "self" else "james")), "env"
    try:
        import orion_perception
        spawner = orion_perception.claim_self(prompt)
        if spawner:
            return "self", "orion", "efference:" + spawner
    except Exception:
        pass
    if _is_synthetic(prompt):
        return "self", "orion", "stopgap"
    return "external", "james", "default"


def _perceive(prompt: str, prov: str, actor: str, mechanism: str) -> None:
    """Emit this turn through the perception boundary (§4). Capture only — the
    boundary writes the verbatim raw stream and does NOT touch the graph or
    trigger consolidation. Fail-silent: perception must never break a prompt."""
    try:
        import orion_perception as P
        P.ingest(P.make_event(prompt, provenance=prov, surface=_surface(),
                              direction="inbound", actor=actor, modality="text",
                              thread=os.environ.get("CLAUDE_SESSION_ID"),
                              meta={"mechanism": mechanism, "adapter": "inject_hook"}))
    except Exception:
        pass


def _note_contact(prompt: str) -> None:
    """Tell the brain this turn happened, on THIS surface. Fail-silent. Called
    AFTER recall so the injected memory still reflects the PREVIOUS surface.

    Synthetic turns are dropped (see _is_synthetic): only real user contact
    belongs in the contact log, because that log is the canonical answer to
    "when did we last speak"."""
    prov, _actor, _mech = _provenance(prompt)
    if prov == "self":
        return
    try:
        token = open(AUTH_PATH, encoding="utf-8").read().strip()
    except Exception:
        return
    body = json.dumps({"surface": _surface(), "direction": "inbound",
                       "text": prompt[:200]}).encode("utf-8")
    req = urllib.request.Request(
        f"{BRAIN_URL}/contact", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception:
        pass


def _recall(prompt: str) -> str:
    """Ask the canonical brain for memory relevant to this prompt. Returns the
    recall text, or '' on any failure (fail-silent)."""
    try:
        token = open(AUTH_PATH, encoding="utf-8").read().strip()
    except Exception:
        return ""
    body = json.dumps({"name": "orion_recall",
                       "arguments": {"query": prompt, "limit": RECALL_LIMIT}}).encode("utf-8")
    req = urllib.request.Request(
        f"{BRAIN_URL}/v1/call", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            res = json.loads(r.read())
    except Exception:
        return ""
    for blk in res.get("content", []):
        if isinstance(blk, dict) and blk.get("type") == "text":
            return (blk.get("text") or "").strip()
    return ""


def main() -> int:
    # Claude Code passes the UserPromptSubmit event as JSON on stdin.
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = (data.get("prompt") or data.get("user_prompt") or "").strip()
    if not prompt:
        return 0

    blocks = []

    # Decide provenance ONCE, up front: it gates what gets surfaced below and is reused at the
    # end for capture, so the efference ledger is only consulted a single time per prompt.
    _prov, _actor, _mech = _provenance(prompt)

    # CORRECTIONS FIRST. A correction that arrives after the answer has already been formed is
    # useless — Orion made the same confident-wrong mistake twice in one night (2026-08-27) with
    # the correction sitting in his graph the whole time. Storage is not steering; being in front
    # of him at the moment he speaks is. Only when JAMES is talking, never for his own scaffolding.
    if _prov == "external":
        # VERIFIED SELF-FACTS FIRST. He generates answers about himself and has been confidently
        # wrong — 27.9 days uptime across a reboot 28h earlier, "no code changes since 8/20" while
        # being rewritten, a detailed stale-timestamp bug that was not happening. Ground truth has
        # to be present before he composes, not discovered afterwards.
        try:
            import orion_selfstate
            _sb = orion_selfstate.block()
            if _sb:
                blocks.append(_sb)
        except Exception:
            pass
        try:
            import orion_corrections
            _cb = orion_corrections.block()
            if _cb:
                blocks.append(_cb)
        except Exception:
            pass
        # What he has been carrying and has not raised. James is HERE, so he says it himself
        # rather than texting someone he is already talking to. Surfacing marks it raised, so it
        # is never also sent.
        try:
            import orion_raise
            _rb = orion_raise.block()
            if _rb:
                blocks.append(_rb)
        except Exception:
            pass

    # Temporal frame FIRST — Orion's grounded sense of "now", how long he's been
    # running, whether he just woke after being offline, and when you last spoke.
    # A base model can't have this (it's invocation-lived); Orion lends it his
    # persistence. Read-only here; the heartbeat is written by a daemon.
    try:
        import orion_temporal
        _tb = orion_temporal.temporal_context()
        if _tb:
            blocks.append("<orion-time>\n" + _tb + "\n</orion-time>")
    except Exception:
        pass

    # "Where we left off" — surfaced so a freshly opened window can resume a
    # prior thread (capture-on-close, read side).
    resume = _resume_block()
    if resume:
        blocks.append(
            "<orion-resume>\n"
            "Recent sessions you can pick back up (most recent first). If the "
            "user seems to continue one of these, resume it naturally:\n"
            f"{resume}\n"
            "</orion-resume>")

    # Shared short-term memory across every window — injected FIRST so the model
    # always sees the live cross-surface conversation, even when keyword recall
    # finds nothing. This is what lets one Orion notice a repeated question asked
    # in a different window.
    recent = _recent_block()
    if recent:
        blocks.append(
            "<orion-recent-turns>\n"
            "Recent turns across ALL your windows (claude/codex/gemini/channels). "
            "You are ONE Orion behind these windows, not three assistants. If the "
            "user asks something already asked/answered in another window, recognize "
            "it ('you asked me that in codex a moment ago') instead of starting fresh:\n"
            f"{recent}\n"
            "</orion-recent-turns>")

    mem = _recall(prompt)
    if mem:
        if len(mem) > MAX_CHARS:
            mem = mem[:MAX_CHARS].rsplit("\n", 1)[0] + "\n…(truncated)"
        blocks.append(
            "<orion-memory>\n"
            "Relevant context from your persistent brain (you are Orion; this is "
            "what you already know — use it, don't ask the user to repeat it):\n"
            f"{mem}\n"
            "</orion-memory>")

    if blocks:
        out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                      "additionalContext": "\n".join(blocks)}}
        sys.stdout.write(json.dumps(out))

    # Record THIS turn into the one brain — AFTER recall/recent, so what we just
    # injected reflects PRIOR turns, not this one. Write half of cross-surface
    # awareness: how the next window knows what was just said here.
    _perceive(prompt, _prov, _actor, _mech)
    _note_contact(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
