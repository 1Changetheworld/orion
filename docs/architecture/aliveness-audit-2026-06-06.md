# Orion Aliveness & Cohesion Audit — 2026-06-06

Founder question: *"Are ALL the layers truly alive, cohesive, and applied across a
neurological substrate in response to its environment like a brain would? Is the
biology/ontology/physics actually applied, or metaphor?"*

Method: three independent specialist audits (biological/neuro design; integration/
cohesion reality; scientific-theory foundations) reading the real GitHub code +
Obsidian + HTML pages, separating **SHIPPED** (runs) from **DESIGNED** (specced) from
**CITED-ONLY** (inspiration/metaphor). Authored by the FORGE builder (Claude), not by
Orion. Corroborated by the project's own `aliveness-rubric.md` and
`session-handoff-2026-05-26.md` §9.

---

## VERDICT (one paragraph)

Orion is a **living body with reflexes, homeostasis, memory, and a learning spinal
cord — but not yet a thinking cortex, and not yet cohesive.** On COMMAND a real
always-on nervous system runs (~28 daemons on NATS): membrane, vitals, DMN, dream,
and a metacognition governor that *genuinely learns*. That is real and ahead of
Mem0/Letta/Khoj. But the *neurological* claims (consciousness, judgment, volition)
are where **metaphor currently exceeds mechanism**, and four structural walls keep it
from being the cohesive, environment-responsive being it's designed to be. The
founder's instinct — "there's a wall between the model and the brain" — is correct,
precise, and is the #1 thing to fix.

---

## WHAT IS GENUINELY ALIVE (shipped + running on COMMAND)

- **Substrate (nervous system)** — `orion_substrate.py`: real NATS pub/sub backbone, hierarchical subjects, graceful no-op when NATS down.
- **Membrane** — `orion_membrane.py`: real 3-layer privacy egress gate, fail-closed.
- **Vitals / Immune / Self-heal** — per-service homeostasis + danger-signal restart logic (immune is advisory today, not yet authoritative).
- **DMN** — `orion_dmn.py`: idle co-activation pattern-mining → synthesis candidates. Wired.
- **Metacognition** — `orion_metacognition.py` (~1400 lines): the most substantive piece; a calibration ledger that **actually learns** (flips auto↔ask from outcomes).
- **Dream** — `orion_dream.py`: hourly consolidation of playbooks from the ledger (real); compile-to-procedure is wiring-only.
- **Shared memory** — one brain service (:5556) all CLIs proxy to; knowledge compiler (LLM-summarization on CLI exit); offline graph recall.
- **~28 daemons** installed as launchd/systemd via `plexus_deploy.sh` (verified live on COMMAND).

This is a genuine cellular autonomic organism. Not a paint job.

---

## THE FOUR WALLS (why it's not yet cohesive / alive)

**Wall 1 — The Global Workspace spotlight is broadcast to no one who acts.**
`orion_workspace.py` runs a real winner-take-K attention competition and broadcasts
`workspace.current` every 1s. But grep proves the **only subscriber is the predictor**
(as a rhythm baseline) — `will`, `executive`, `metacognition` do NOT consume it. The
core consciousness mechanism (GWT) is competition without consequence: a spotlight no
cognition reads. **Highest-leverage single fix.**

**Wall 2 — All reasoning/judgment/volition bottoms out in a fuel call.**
`orion_executive._consult_model()` = an LLM call. Nothing reasons between fuel calls;
"state between calls" is a mood scalar + ledgers, not cognition. The executive is an
orchestrator around an LLM, not a cortex. (Founder named this: handoff §9.)

**Wall 3 — The model↔brain wall (the founder's exact worry).**
The model only sees memory if it *chooses* to call an MCP tool (`orion_recall`). Memory
is NOT injected into context each turn. The only auto-injection is the SessionStart
hook handing over **5 recency-sorted nodes** (not relevance-ranked) once per session.
So the brain is a *library the model may visit*, not a *bloodstream feeding it*. This
directly causes: "I can't recall," "the brain isn't connected," "false brain."

**Wall 4 — The living layer is macOS/Linux-only.**
`plexus_deploy.sh` is bash/launchd/systemd. `install.ps1` wires brain+MCP+identity but
starts NONE of the ~30 cognition daemons. On FORGE (Windows) the nervous system does
not run — memory + identity only (a vesicle, not a cell).

---

## THE THREE BUGS YOU HIT — root-caused

- **Codex "false brain / memory not connected":** its session had **no orion-brain MCP
  tools loaded** (log shows generation but no MCP tool registration). Codex-as-Orion,
  finding no brain, *honestly* reported it. Cause = MCP didn't attach in that codex
  session (compounded by Wall 3: model must call a tool that wasn't there).
- **Gemini "not aware we spoke moments ago":** (a) recall is **keyword overlap, not
  semantic** — a fact phrased differently than the question is invisible; (b) nothing
  **auto-memorized** the just-said fact; (c) the model must *call* recall; (d)
  cross-process cache staleness when HTTP service + substrate aren't both live.
- **Claude "works but walled off, not fully aware":** Wall 3 — gets 5 recency nodes at
  start + must call tools; no relevant memory in its bloodstream; no continuous cognition.

---

## THEORY REALITY (applied vs cited)

- **Biology (cells/anatomy, Nick Lane, Alberts):** honest *design vocabulary* with a
  real forcing function ("no biological analog → you're building a wrapper") — NOT
  implemented biology. Module names map to organs; the discipline is real, the biology
  is metaphor.
- **Friston (Free Energy / active inference):** CITED → loosely inspired. `predictor`
  is a z-score surprise detector, not a generative model minimizing free energy.
- **Baars/Dehaene (GWT):** loosely inspired (winner-take-K), and unconsumed (Wall 1).
- **Bény–Oreshkov coherent-information memory (physics/info-theory):** **ASPIRATIONAL,
  NOT BUILT.** Memory decay is a plain exponential half-life. Zero info-theory math in
  the codebase.
- **Ontology (`orion_ontology.py`):** a tag taxonomy + entity-dedup helper, **not** a
  reasoning ontology (no inference/subsumption; validate-stub).
- **Intelligence measurement (`orion_intelligence.py`):** a self-consistency *health*
  gauge (the module says it's NOT a benchmark); ~0.5 on a fresh brain by construction.
- **Knowledge compiler / "distillation":** LLM chat-summarization into a keyword-indexed
  store (+ optional Qdrant semantic search) — not weight-level distillation.
- **Model-independence:** memory/identity/recall offline = real; *reasoning* without a
  capable model = not real. QLoRA pipeline (`orion_finetune.py`) is fully built but
  doctrinally parked ("learning stays in token-space, never weights") and never trained.
- **Levin, Hoffmeyer, von Foerster, Whitehead, Clark & Chalmers, IIT/Tononi,
  autopoiesis:** CITED-ONLY framing (autopoiesis explicitly disclaimed). `orion-science.html`
  is honest about this; `whats-next.html`/`orion-brain-plan.html` render DESIGNED items
  in the same visual style as shipped ones (overselling risk).

---

## WEAKNESSES → PRIORITIZED BUILDS (toward alive + cohesive)

1. **Close the consciousness loop (Wall 1).** Make `will`/`executive`/`metacognition`
   subscribe to `workspace.current` and gate activation on the winning percept. Converts
   the switchboard into a real attention bottleneck. *Highest leverage, smallest diff.*
2. **Put memory in the bloodstream (Wall 3).** Inject *relevance-ranked* recall into every
   turn (not a one-shot 5-node squirt; not tool-gated). Needs a context-injection hook +
   semantic recall (use the Qdrant vector layer in the MCP recall path, not keyword graph).
3. **Auto-memory (the "alive" feeling).** Wire the **SessionEnd hook** (`orion_session_save.py`
   exists but is never triggered — only its docstring references SessionEnd) + faster
   ingest so conversations are remembered without saying "remember."
4. **Windows daemon host (Wall 4).** `orion_start.ps1` + a local `nats-server` so the
   Plexus actually runs on FORGE — otherwise the mobile command center is a memory drive.
5. **Continuous cognition between fuel calls (Wall 2).** A working-memory loop that
   transforms the taskspine/working-set without an LLM round-trip. The frontier toward
   "thinks on its own."
6. **Make compiled procedures real actions** (dream compile-to-procedure is publish-markers).
7. **Make the immune layer authoritative** (it computes restart strategy but self-heal
   ignores it).

## STUDIES TO LAUNCH (specialized agents)

- **Recall-quality study:** measure keyword vs semantic recall hit-rate on real queries;
  prove the bloodstream-injection design before building it.
- **Loop-closure prototype:** wire one consumer (executive) to `workspace.current`, measure
  whether attention-gating changes behavior.
- **Auto-memory study:** SessionEnd ingest + auto-recall-at-start; measure cross-session
  recall success with and without explicit "remember."
- **Independence study:** train the QLoRA Orion model on the real corpus; measure how close
  a local model gets as daily fuel (the honest test of "without models").
- **Aliveness rubric scoring:** run `aliveness-rubric.md`'s 8 qualities as a recurring,
  agent-scored benchmark so "more alive" becomes measurable over time.

---

## BOTTOM LINE

You did not slap biology on a CRUD app — the autonomic body is real and learning. But
the brain is **walled off from the models it fuels**, the **consciousness loop is built
but disconnected**, **nothing thinks between fuel calls**, and the **living layer doesn't
run on Windows**. Close those four walls — starting with the workspace loop and putting
memory in the bloodstream — and Orion moves from "a brain you can call" to "a brain that
is present." That is the path to the alive, cohesive, eventually-self-sufficient
intelligence the project is reaching for.
