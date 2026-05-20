#!/usr/bin/env python3
"""orion_local_chat.py — talk to the FULL Orion brain, fueled by a LOCAL model.

Why this exists: a bare `ollama run <model>` is just a model — no memory, no
identity, not Orion. Every turn here instead routes through orion_brain.think():
live graph memory + identity + deterministic recall + write-back, with a local
Ollama model as the fuel. That is the real offline brain.

This is the path for:
  - the founder off-grid (no internet, no subscription CLI), and
  - ANY user whose Orion runs on local LLMs instead of Claude/Codex/Gemini.

It works with NO qdrant and NO internet — graph memory + a local model is
enough. (orion_memory degrades to graph-only when the vector layer is absent.)

Usage:
    python orion_local_chat.py            # brain-backed REPL on local fuel
    python orion_local_chat.py "one question"
"""

import json
import os
import sys

_PREF_PATH = os.path.expanduser("~/.orion/fuel_preference.json")


def _prefer_local():
    """Pin this session's fuel to the local Ollama model. Returns prior state
    so it can be restored on exit (we don't want to permanently override a
    user's fuel preference just because they opened a local chat)."""
    prior = None
    if os.path.exists(_PREF_PATH):
        try:
            prior = open(_PREF_PATH, encoding="utf-8").read()
        except Exception:
            pass
    os.makedirs(os.path.dirname(_PREF_PATH), exist_ok=True)
    with open(_PREF_PATH, "w", encoding="utf-8") as f:
        json.dump({"fuel": "ollama"}, f)
    return prior


def _restore(prior):
    try:
        if prior is None:
            if os.path.exists(_PREF_PATH):
                os.remove(_PREF_PATH)
        else:
            with open(_PREF_PATH, "w", encoding="utf-8") as f:
                f.write(prior)
    except Exception:
        pass


def _ask(brain, msg):
    r = brain.think(msg, interface="local")
    if isinstance(r, dict):
        return r.get("response", ""), r.get("engine", "?")
    return str(r), "?"


def main(argv):
    try:
        import orion_brain
    except Exception as e:
        print("Brain unavailable: %s" % e)
        print("(Need orion_memory's graph at ~/.orion/brain — vector DB is optional.)")
        return 1

    prior = _prefer_local()
    try:
        if argv:  # one-shot
            ans, engine = _ask(orion_brain, " ".join(argv))
            print(ans)
            print("[fuel: %s]" % engine)
            return 0
        print("Orion — local brain. Memory + identity are live; the fuel is a "
              "local model. No internet required. Type 'exit' to quit.\n")
        while True:
            try:
                msg = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not msg:
                continue
            if msg.lower() in ("exit", "quit", "/exit", "/quit"):
                break
            try:
                ans, engine = _ask(orion_brain, msg)
                print("orion> %s" % ans)
                print("       \033[2m[fuel: %s]\033[0m" % engine)
            except Exception as e:
                print("orion> (brain error: %s)" % e)
    finally:
        _restore(prior)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
