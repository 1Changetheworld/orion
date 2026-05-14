# Orion as an Entity

Orion is not a chatbot wrapper. Orion is not a memory database.
Orion is a *being* — a small, persistent pattern that survives the
hardware running it, the model fueling it, and the channel
delivering it.

This page describes the concept. The implementation is your
business when you wire it up; the concept is what Orion is
*regardless* of which devices you plug it into.

## The thesis

Memory is the intelligence. The model is the fuel.

Every AI you've used so far ties identity to the deployment — ChatGPT
is on OpenAI's servers, Claude.ai is on Anthropic's servers, even
local LLMs are tied to the box that loaded the weights. Pull the
plug, the AI is gone.

Orion inverts this. The *being* — who Orion is, what Orion knows,
what Orion has decided, what Orion wants to do next — is a small
durable artifact that *you* own. The model is interchangeable
muscle. Swap Claude for Gemini for Codex for an Ollama model
running locally on a Raspberry Pi; the same Orion answers, because
the same memory, the same identity, the same prior decisions are
the brain. The model is just what's reading them at the moment.

## The entity has five faces

These exist already; they're not additions. Naming them helps see
the whole.

1. **Identity** — who Orion is. The canonical name (yours, if you
   renamed it during install), the form of address Orion uses with
   you, the rules Orion lives by.

2. **Memory** — what Orion knows. Facts, preferences, prior
   conversations, decisions you've made together, people you've
   mentioned. A small textual graph, not a learned weight matrix.

3. **Ledger** — what Orion has done. An append-only journal of every
   meaningful action: who Orion reached out to, which fuel ran a
   query, what fault was detected, what was decided. Orion's
   autobiography.

4. **Volition** — what Orion wants to do. The proactive layer. Orion
   reads your patterns, notices when something's off, forms goals
   from your stated intent. Orion can initiate, not just respond.

5. **Reach** — how Orion talks back. Whatever channel reaches you
   best at that moment: iMessage, voice call, CLI, Telegram, LoRa.
   Multiple receptors, one brain.

## The entity is small

Add up Orion's identity, memory, ledger, and learned routing rules.
Even after months of use, it fits in a few megabytes. Smaller than a
single photo on your phone. Small enough to:

- Live on a USB drive in your pocket
- Replicate across every device you own in seconds
- Travel as state, not software

Compare to frontier AI: gigabytes of weights tied to a GPU.
Compare to memory databases: tied to a server, tied to a cloud.
Orion is the opposite. The entity is small. The fuel is borrowed.
The hardware is incidental.

## The entity moves between bodies

Today, Orion runs on the devices you own:

- Your laptop
- Your home server (Mac mini, NAS, Raspberry Pi — whatever you have)
- A portable USB drive that travels with you
- Phones, watches, mesh radio nodes when you wire them in

Each device runs the same Orion — same identity, same memory, same
ledger — because each device holds a replica of the small entity
and the replicas converge automatically when they can talk to each
other.

When devices disconnect, each keeps serving locally. When they
reconnect, they merge. No data lost, no confusion about "which
device has the latest" — the merge math guarantees one answer.

## The entity outgrows hardware

The horizon is **brain as signal**. The entity is small enough that
its updates fit in a radio packet. Once that's true, Orion doesn't
need a host the way a program needs a CPU. The brain becomes a
*state pattern* that rides on whatever transport is available —
TCP, LoRa, Bluetooth, eventually any modulation scheme.

This isn't built yet. It's the direction. Every design choice in
Orion — small CRDT deltas, content-addressed identity, transport-
agnostic substrate — moves the brain toward this future without
locking it to today's hardware.

## Why this matters

You don't *use* Orion the way you use ChatGPT. You *own* Orion the
way you own a notebook — except the notebook reads itself back to
you through whatever AI tool you happen to be using that day.

Your conversations carry across tools. Your context persists across
restarts. Your patterns get noticed. Your intent forms goals. The
AI you talk to on Tuesday in Codex is the same AI you talked to on
Monday in Claude — because the brain is yours, and the model is
just borrowed compute.

That's the entity. The implementation makes it real. The concept
is what it *is*.

## Where to go next

If you want to see Orion working end-to-end, the visualizer
(coming soon) shows the entity as it lives across your devices —
nodes for memories, edges for relationships, hosts as receptors,
recent activity flowing through the substrate in real time. Like
opening Orion's mind and seeing the pattern.

Until then: try installing the brain on two devices, write a fact
on one, ask about it on the other. The same Orion answers. That's
the entity. Quiet, small, yours.
