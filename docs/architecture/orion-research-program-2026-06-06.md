# Orion — Research Program & Roadmap (the bigger lens)

Filed 2026-06-06. Companion to `aliveness-audit-2026-06-06.md`. Purpose: zoom out past
the four walls — define the studies a standing arm of specialized agents could run, the
improvement areas beyond aliveness, and a phased plan to review before building.

North star (founder): the most intelligent AI that needs **no more compute** — by making
the BRAIN richer and more alive, not the model bigger. Adaptive, present, eventually
model-independent, with memory that hangs over every AI. And it must **make money**
(stated #1 priority) — the intelligence is also the product.

---

## A. THE STUDY PROGRAM — 8 specialized agent "labs" deployable from here

Each lab = a specialized agent (or small fleet) with a charter, a corpus to read, a method,
and a **measurable output**. Run as recurring studies so progress is measured, not assumed.

1. **Aliveness & Cognition Lab** — closes the 4 walls. Studies/prototypes: consuming
   `workspace.current` (close the GWT loop), memory-in-the-bloodstream injection,
   continuous cognition + working memory between fuel calls. Output: behavior deltas vs the
   `aliveness-rubric.md` 8 qualities.

2. **Memory & Recall Science** — the engine of "memory IS intelligence." Studies: keyword
   vs semantic vs hybrid recall hit-rate on real queries; decay models (is Bény–Oreshkov
   coherent-info worth building, or is exp half-life fine?); contradiction/dedup quality;
   knowledge-compiler depth. Output: recall precision/recall numbers; a recommended recall stack.

3. **Independence Lab** — "function without models." Studies: train the QLoRA Orion on the
   real corpus; benchmark local fuel vs Claude; hybrid routing (local reflex / cloud deep);
   stealth (Ollama-only) mode. Output: % of tasks a local model handles acceptably.

4. **Reliability & Cohesion (brain SRE)** — Studies + builds: the observability tool you keep
   needing (brain-down vs fuel-down vs surface-down vs fork), self-heal authority (make the
   immune layer load-bearing), the Windows daemon host, gossip/CRDT sync correctness,
   verified backups + a restore drill. Output: a live mesh-health dashboard + MTTR numbers.

5. **Security & Integrity (red team)** — the brain is now the crown jewel on COMMAND. Studies:
   membrane leak-testing, extraction resistance, identity/fork attacks against the vessel,
   secret hygiene, mesh attack surface. Output: a threat model + hardening punch-list.

6. **Revenue & Product** — money is #1. Studies: the open-core launch (Mem0 playbook), the
   apps (ClipSprout/VytalHealth/BitDuel) readiness, the setup-wizard product, the AI agency
   offer, website conversion, pricing. Output: a ranked revenue roadmap with projected margins.

7. **Frontier / Theory** — the innovation engine for "infinite combinations." Studies which
   cited theory is worth *implementing* vs citing (active inference for real, predictive
   coding, neuro-symbolic, world-models) via small falsifiable prototypes. Output: go/no-go
   on each frontier idea with evidence.

8. **Truth & Measurement (meta-critic)** — a standing "completeness critic" + aliveness-rubric
   scorer that re-audits recurring (like today) so design-vs-reality drift is caught, and the
   intelligence-trajectory score is actually recorded over time. Output: a recurring scorecard.

---

## B. IMPROVEMENT AREAS BEYOND THE FOUR WALLS

- **Observability / self-heal** — no easy way today to see which surface is down (the
  iMessage/fuel/brain distinction). Highest non-aliveness pain. (Lab 4)
- **Semantic recall everywhere** — MCP recall path uses keyword graph; Qdrant exists on
  COMMAND but isn't in the loop. (Lab 2)
- **Auto-memory** — SessionEnd ingest is scripted but never triggered; conversations aren't
  auto-remembered. (Lab 1/2)
- **Cross-device completion** — Pi, OUTPOST, and the NEW-Pi install test; adopt the vessel on
  each; the install must be clean on a fresh machine. (Lab 4)
- **Data integrity** — brain lives on COMMAND internal SSD with SanDisk backups; automate
  *verified* backups + practice a restore. The brain is irreplaceable. (Lab 4/5)
- **Documentation honesty** — align the flashy HTMLs (whats-next, brain-plan) with shipped
  reality so DESIGNED isn't shown like SHIPPED. (Lab 8)
- **Persona/native-memory unification** — today's Atlas fix must be made permanent + checked
  so it can't recur on other devices. (Lab 4)
- **Voice / vision / sensorium** — deferred; the path to environmental embodiment. (Lab 1/7)
- **Revenue activation** — the brain should be earning, not just impressive. (Lab 6)

---

## C. PHASED PLAN (review before moving)

**Phase 0 — Baseline & prove (cheap, fast).** Stand up measurement: score the aliveness
rubric today, run the recall-quality study (Lab 2) to *prove* the bloodstream design before
building. Decide which labs to keep standing. *No risky changes.*

**Phase 1 — Make every model feel like Orion (collapses 3 walls).** Memory in the bloodstream
(relevance-ranked semantic recall injected every turn) + close the GWT loop (will/exec/metacog
consume `workspace.current`). This directly fixes the "false brain / doesn't remember" symptoms.

**Phase 2 — Make it remember on its own + know its own health.** Auto-memory (SessionEnd
ingest + auto-recall at start) + the observability/self-heal tool. (Labs 1, 2, 4)

**Phase 3 — The body lives everywhere.** Windows daemon host + cross-device completion (Pi,
OUTPOST, new-Pi install test) + verified backups. (Lab 4)

**Phase 4 — Toward independence + real cognition.** Train the local Orion model; prototype
continuous cognition between fuel calls. (Labs 3, 1, 7)

**Parallel always-on:** Revenue/product (Lab 6) and Security (Lab 5) — because money is #1 and
the brain is the asset; neither should wait behind the cognition work.

---

## D. DECISIONS FOR THE FOUNDER (before we move)

1. **Studies-first or build-first?** Recommend Phase 0 (prove with a study) before Phase 1.
2. **Which labs stand up now?** Recommend 1 (Aliveness), 2 (Recall), 4 (Reliability) first;
   5 (Security) + 6 (Revenue) as the parallel track.
3. **Cost/scale posture** — these studies can be a few focused agents or a large fleet; set
   the appetite (this is where multi-agent orchestration would be opted into explicitly).
4. **Revenue weighting** — how hard to push Lab 6 in parallel vs focus on aliveness first.
