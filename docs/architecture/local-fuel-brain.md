# Running Orion on a local model (offline / no subscription)

Orion's thesis is "the model is fuel." That has to hold when the fuel is a
**local** model — for users who run Orion on Ollama instead of a subscription
CLI, and for anyone off-grid. This note describes how the local path actually
delivers the *brain*, not just a model.

## The trap we closed

`ollama run <model>` — even an "Orion-branded" one — is **just a model**. It
has the persona baked into a Modelfile, but **no live memory, no `orion_recall`,
no write-back**. Ask it who it is and you get a generic assistant. That is not
Orion; it's fuel with a costume.

The fix is the same move Orion makes for the strong CLIs (which get the brain
via MCP): **route every turn through the brain.** Locally, MCP tool-calling
isn't available, so instead the brain wraps the local model — it injects live
graph-memory context + identity into the prompt, runs the deterministic recall
short-circuit, and writes the exchange back to memory. The local model supplies
only the language. That *is* Orion.

## How to use it

```
ORION local                 # brain-backed REPL, fueled by your local model
ORION local "a question"    # one-shot
```

(`orion_local_chat.py` pins the session's fuel preference to the local model,
runs each turn through `orion_brain.think()`, and restores your prior fuel
preference on exit.)

Verified: asked "who are you, and are you using the cloud right now?" on a
local model with **no internet and no vector DB**, the answer was —
> *"I am ORION — a personal AI intelligence layer, not a cloud-based model. I
> operate locally on your devices… My memory and processing are self-contained."*

## What makes the offline fallback *real* (not theater)

1. **The vector layer is optional.** `orion_memory` degrades to graph-only when
   `qdrant_client` (or the qdrant server) is absent. The graph (`graph_memory.json`)
   is the durable core; vectors only enrich recall. A lean local install with no
   qdrant still loads the full brain.
2. **The fuel cascade reaches local fuel.** When the strong CLIs are unavailable
   (offline, or not installed), `orion_fuel` falls through to Ollama; a throttled
   or missing fuel returns `None` so the cascade continues rather than leaking an
   error. (See `_is_error_response` in `orion_fuel.py`.)
3. **The task survives the model.** Long work runs on `orion_taskspine` — a
   durable on-disk step log — so even if the local model stalls mid-task, a fresh
   model resumes from the checkpoint.

## For users whose Orion runs on local LLMs

This is a first-class path, not a degraded mode. If you don't have (or don't want)
a Claude/Codex/Gemini subscription, point Orion at Ollama and use `ORION local`:
you get the same brain — your memory, your identity, your continuity — with a
model that runs entirely on your own hardware. The brain is yours; the fuel is
whatever you can run.

**Honest limits of local fuel:** a small local model reasons less capably than a
frontier model, so complex multi-step tasks are slower and rougher. The memory,
identity, and continuity are identical; the *reasoning horsepower* scales with
the model you can run. A future coherence probe (`orion_coherence_probe.py`,
planned) will announce when the active fuel is below Orion's quality floor rather
than silently degrading.
