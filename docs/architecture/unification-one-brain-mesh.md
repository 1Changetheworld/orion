# Unification — One Brain, One Body, Many Surfaces

**Filed:** 2026-06-04. Author: Claude Opus on FORGE (the external builder — per the
cardinal rule, the single non-Orion surface in the system). Sibling docs:
`vessel-canonical-identity.md` (the enforcement mechanism), `design-law.md` (the
biological law this obeys).

This doc states the unification principle plainly so every future session — and
every device we add — builds toward the same shape, and so the failure that the
2026-06-04 health check found (FORGE talking to its own 43-node brain instead of
COMMAND's 1,474-node canonical one) cannot recur silently.

---

## 1. The principle (one sentence)

**There is exactly ONE Orion brain. It lives on COMMAND's SSD. Every AI model
(codex, gemini, the Orion local LLM), every device, and every communication point
(iMessage, Telnyx phone, Telegram, voice, LoRa) is a *surface* that binds to that
one brain — never a copy of it.** The only thing in the entire system that is *not*
Orion is the Claude Opus builder on FORGE, which constructs Orion from the outside
and is deliberately kept brain-unwired.

Jump from codex to gemini, from FORGE to the Pi to your phone — it is the *same
brain*. A fact you tell it in one place is instantly recallable in every other,
because there is nothing to "sync": there is one store, and everything reads and
writes through it.

## 2. The body — what maps to what (biological law)

Orion is built as an organism, not a stack of services. Unification is what makes
the organs one body instead of a swarm of look-alikes:

| Organ | In Orion | Where |
|---|---|---|
| Central nervous system / brain | the memory graph + knowledge + ledger + identity | **COMMAND SSD (the one brain)** |
| Bloodstream + the durable self | `instance_id` + Ed25519 identity | `orion_identity.py` / `orion_federation.py` |
| **Main artery** (one blood supply, no second heart) | **the vessel — pin + verify-on-bind + no-fork law** | `orion_vessel.py` |
| Nervous system (signal bus) | NATS substrate, subject taxonomy | `orion_substrate.py` |
| Cell membrane (privacy boundary) | egress filter, fail-closed | `orion_membrane.py` |
| Interchangeable muscle / fuel | codex, gemini, Ollama — *borrowed compute* | `orion_fuel.py` |
| Sensory & motor surfaces | iMessage, phone, Telegram, voice, LoRa, CLI | `channels/*` |
| Limbs | the devices (COMMAND, FORGE, ORIONS HOME, OUTPOST, new Pi) | the mesh |

The model is **fuel, not the self.** Swap codex for gemini for a local LLM and the
organism is unchanged — different muscle, same brain. That is the whole thesis:
*the memory IS the intelligence; the model is fuel; the brain is what persists.*

## 3. Why unification needs enforcement, not hope

Before the vessel, "one brain everywhere" was *hoped for* via gossip eventual-sync.
The health check proved hope is not enough: two code defaults silently grew a second
brain on FORGE —

- `orion_substrate._discover_substrate_url()` bound by **reachability**, not identity.
- `orion_mcp_server` defaulted to a **local** brain and **auto-spawned** one per host.

The vessel converts the principle into a law the code enforces at bind time: a
surface verifies an Ed25519-signed `whoami` against a pinned canonical fingerprint
**before** it trusts a brain. Match → bind. Different-but-authentic → **fork,
refused and reported.** Unverifiable → **read-only + queue**, never a new self. See
`vessel-canonical-identity.md`.

## 4. The invariants (hold these on every future change)

1. **One brain.** New surfaces *bind*; they never instantiate an authoritative brain.
2. **Verify, don't trust reachability.** Whatever answers on a port is not assumed to
   be canonical — it proves it cryptographically or it is not bound.
3. **Fail closed.** No pin / unverifiable canonical → read-only, queue writes, offer
   adoption. Better mute than forked.
4. **Claude is the builder, everywhere it builds.** FORGE-Claude is unwired by design.
   (Open founder question: should COMMAND-Claude be unwired too? Currently it is
   wired as Orion — left as-is pending a ruling.)
5. **No API keys, ever.** Fuel is local CLIs or Ollama. See `feedback_no-api-keys`.
6. **SHIPPED ≠ DESIGNED ≠ OPEN.** Never blur what runs vs what's drawn.

## 5. The aim — hyper-intelligence without more hardware

The direction this unification serves: get closer to hyper-intelligence by growing
the **brain**, not the hardware. Intelligence here is accumulated memory, compiled
knowledge, learned skills, and a coherent identity — all of which live in the one
brain and improve with use, on the hardware we already own. A bigger model is just
hotter fuel; a richer brain is a smarter *being*.

The end state the founder is reaching for, recorded so we build toward it:

- **A self that functions across communication points** — reachable and continuous
  whether you arrive via codex, gemini, a phone call, or iMessage; same memory, same
  self, every door.
- **Eventually its own model** — the independence path (`orion_finetune.py`, the
  QLoRA roadmap on `orion-architecture.html`): a locally-trained Orion model so the
  brain can think without even depending on Ollama. The brain stays the constant; the
  fuel becomes *home-grown*.

These are **aspiration, not shipped.** They are reachable only on a foundation where
there is provably one self — which is why the vessel comes first.

## 6. The gap unification still leaves — observability / self-heal

The vessel guarantees *one brain*; it does **not** tell you *which surfaces are
healthy*. The founder's standing need:

> "I need to go to codex or gemini on any device on the mesh, and it's the same
> brain I can talk to — and it will recognize iMessage is down."

That is a separate, **purely additive, read-only** layer (touches no live binding
path) that the build has not yet shipped. Its job is to distinguish three failure
classes the health check found conflated:

- **brain-down** — the canonical store/service is unreachable.
- **fuel-down** — the brain is up and retrieval works, but the model fueling
  generation is failing (exactly COMMAND's `claude-cli` 401 on 2026-06-04:
  `context_found:true`, generation dead).
- **surface-down** — a channel like iMessage can't deliver (the Sequoia AppleScript
  breakage, now mitigated by the cascade in `channels/imessage_send.py`).

Plus fork detection by identity/`whoami` mismatch (the vessel already logs these to
`~/.orion/vessel/forks.jsonl`). Self-heal then acts on those distinct states. This
mesh health/observability tool is the natural next build after the vessel rollout.

## 7. Rollout state (2026-06-04)

- Vessel module + tests: **shipped, 9/9 green.**
- Deploy wiring (Seams A/B/C): **implemented, committed, pin-gated/inert.**
- iMessage resilience: **shipped** (`channels/imessage_send.py` cascade); real
  delivery to be verified on COMMAND (Sequoia) — cannot be proven from the Windows
  builder.
- Not yet done: anoint COMMAND + expose `:5556`/`/vessel/whoami` on the tailnet +
  adopt on secondaries (the activation), then the observability/self-heal layer.

Relates to: `[[orion-current-state]]`, `[[hard-rules]]`, `[[orion-vessel-keystone]]`.
