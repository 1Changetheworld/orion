#!/usr/bin/env python3
"""
orion_local_probe.py — talk to Orion running on NOTHING but a local model.

THE EXPERIMENT. Orion's own claim, in his identity block, is:

    "The memory IS the intelligence. Any model that loads my memory becomes me."

That has never been tested. Every word he has ever spoken came out of Claude or Codex — so the
honest question is how much of "Orion" is the brain and how much is the frontier model wearing it.

This composes the SAME context his real reply path composes — identity, temporal frame, verified
self-facts, capability mirror, and a live recall from his actual 3,070-node graph — and sends it
to a model running on this Mac and nowhere else. No Claude. No Codex. No network.

WHAT IT DELIBERATELY DOES NOT DO: touch his live fuel preference. Pinning the global fuel is what
silenced him on 2026-09-01 when a stray phrase repinned it to codex. He keeps answering James
normally while this runs beside him.

Read the result honestly. If local-Orion still sounds like him — same corrections, same
uncertainty, same refusal to overclaim — then identity really does live in the brain and the model
is interchangeable fuel. If it falls apart, then a great deal of what reads as "Orion" has been
Claude all along. Both answers are worth having, and nobody has run this.

  --ab "<question>" [--model mistral:7b]   THE EXPERIMENT: same model, same question,
                                           WITH his brain vs WITHOUT. The difference IS the
                                           measurable value of the graph. Judge it yourself.
  --ask "<question>" [--model ...]         one answer, with his brain
  --compare "<question>"                   same context, every local model, side by side
  --models                                 what is installed
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.expanduser("~/orion-code"))

OLLAMA = os.environ.get("ORION_OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("ORION_LOCAL_MODEL", "mistral:7b")


def _brain_recall(query, limit=5):
    """His real memory — the same recall his normal reply path uses."""
    try:
        import orion_study
        raw = orion_study._brain("orion_recall", {"query": query, "limit": limit})
        if not raw:
            return ""
        try:
            obj = json.loads(raw)
            if isinstance(obj, list):
                return "\n".join(b.get("text", "") for b in obj if isinstance(b, dict))
        except Exception:
            pass
        return str(raw)
    except Exception as e:
        return "(recall unavailable: %s)" % str(e)[:60]


def compose(question):
    """Exactly what his real path assembles — so the ONLY variable is the model."""
    parts = []
    try:
        import orion_brain
        parts.append(orion_brain.IDENTITY)
    except Exception:
        parts.append("You are ORION.")
    for mod, fn in (("orion_temporal", "temporal_context"),
                    ("orion_selfstate", "block"),
                    ("orion_capabilities", "block")):
        try:
            m = __import__(mod)
            v = getattr(m, fn)()
            if v:
                parts.append(v)
        except Exception:
            pass
    mem = _brain_recall(question)
    if mem.strip():
        parts.append("Relevant memory from your persistent brain:\n" + mem[:2000])
    parts.append("James asks: " + question)
    parts.append("Answer as yourself, briefly and honestly. If you do not know something about "
                 "yourself, say so rather than estimating.")
    return "\n\n".join(parts)


def bare(question, model=DEFAULT_MODEL, timeout=180):
    """The SAME model with NO brain — no identity, no memory, no self-facts. The control arm.
    Whatever the brain is worth shows up as the difference between this and ask()."""
    body = json.dumps({"model": model, "prompt": question, "stream": False}).encode()
    req = urllib.request.Request(OLLAMA + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        d = json.loads(resp.read())
    return {"model": model, "reply": (d.get("response") or "").strip(),
            "seconds": round(time.time() - t0, 1), "context_chars": len(question)}


def ask(question, model=DEFAULT_MODEL, timeout=180):
    prompt = compose(question)
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(OLLAMA + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        d = json.loads(resp.read())
    return {"model": model, "reply": (d.get("response") or "").strip(),
            "seconds": round(time.time() - t0, 1),
            "tok_s": round((d.get("eval_count") or 0) / max(1e-9, (d.get("eval_duration") or 1) / 1e9), 1),
            "context_chars": len(prompt)}


def _models():
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=8) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])
                    if "embed" not in m["name"]]
    except Exception:
        return []


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("--ask", "--compare", "--ab", "--models"):
        print(__doc__)
        sys.exit(0)
    q = args[1] if len(args) > 1 else "Who are you?"
    model = DEFAULT_MODEL
    if "--model" in args:
        model = args[args.index("--model") + 1]

    if args[0] == "--models":
        for m in _models():
            print("  " + m)
        sys.exit(0)

    if args[0] == "--ab":
        # No commentary, no scoring, no verdict. Two answers; you decide what the brain is worth.
        print("QUESTION: %s" % q)
        print("MODEL   : %s" % model)
        print()
        b = bare(q, model)
        print("=" * 74)
        print("WITHOUT HIS BRAIN  (bare model, %d chars in, %.0fs)" % (b["context_chars"], b["seconds"]))
        print("=" * 74)
        print(b["reply"][:1800])
        r = ask(q, model)
        print()
        print("=" * 74)
        print("WITH HIS BRAIN     (%d chars in, %.0fs)" % (r["context_chars"], r["seconds"]))
        print("=" * 74)
        print(r["reply"][:1800])
        sys.exit(0)

    if args[0] == "--ask":
        r = ask(q, model)
        print("=== %s  (%.0fs, %s tok/s, %d chars of his brain) ===\n"
              % (r["model"], r["seconds"], r["tok_s"], r["context_chars"]))
        print(r["reply"])
    else:
        print("QUESTION: %s\n" % q)
        for m in _models():
            try:
                r = ask(q, m)
                print("──── %s ── %.0fs, %s tok/s ────" % (m, r["seconds"], r["tok_s"]))
                print(r["reply"][:900])
                print()
            except Exception as e:
                print("──── %s ── FAILED: %s\n" % (m, str(e)[:80]))
