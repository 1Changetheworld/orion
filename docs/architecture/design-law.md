# Orion Design Law — the decisions that create intelligence

Ratified by the founder 2026-05-20 after the mesh→executive→taskspine recovery
loop. Apply these to **every** future layer. They are what separates evolved
software intelligence from reactive automation.

## The three laws

1. **Confirm before acting.** Re-probe / verify before treating a signal as
   real. A single missed beat is a flap, not an outage. Intelligence is not
   reacting to every input — it's knowing which inputs are real.

2. **Act at the recoverable moment, not the dramatic one.** You can't restart a
   powered-off host; the genuinely recoverable moment is the device's *return*.
   Design action for where it is actually possible and valuable, not where the
   alarm is loudest.

3. **Reuse the deliberative core, don't reinvent it.** Every real fix flows
   through the executive's existing deliberation + tiered permission-gating +
   decision ledger. New behavior inherits safety (nothing destructive
   auto-runs) and learning (dream consolidates what worked) for free. One brain,
   not many bolted-on reflexes.

## The agreed next step (do this next)

**Make the recovery loop's "act" rung real:** a `mesh_restore` remedy executed
**over the task spine** —
- resolve the device's transport (LAN at home, Tailscale away),
- SSH in, restart its Orion services / re-confirm MCP / rejoin gossip,
- permission-gated, checkpointed (a flaky-network restore resumes from the last
  step instead of restarting).

Paired with **metacognition Phase 2**: gate those autonomous actions on
calibrated confidence — auto when sure, ask when not. That is what makes
cross-host self-repair *trustworthy* rather than risky. The outcome turns
"Orion noticed and proposed" into "Orion noticed, fixed it, and learned the fix."

The loop today does observe → track → decide fully; the "act" rung is currently
gated to local remedies (`_apply_remedy`: launchctl_reload + investigate_only).
`mesh_restore` + metacog-Phase-2 gating completes it.
