# Channel Adapter Pattern

> How to wire any communication surface — iMessage, Telegram, Discord, Slack, WhatsApp, email, voice, custom — to a single Orion brain.

Orion's design separates **where messages come from** (channels) from **what answers them** (the brain + fuel). A channel daemon does only three things:

1. Listens on its surface
2. Hands the message to the brain with an interface tag
3. Sends the brain's reply back on the same surface

The brain selects the model (Claude CLI, Codex CLI, Gemini CLI, Anthropic API, OpenAI API, Ollama, or whatever else is installed) based on what's available on the host and the user's preferences. The daemon never knows or cares which model answered.

This is the *receptor / ligand* pattern from cell biology applied to software: many channels (ligands) plug into one brain (receptor) through a uniform substrate.

## Why this matters

Three kinds of users coexist without code branching:

| User has | Brain auto-routes to | Marginal cost |
|---|---|---|
| Claude Pro / ChatGPT Plus subscription | `subprocess(["claude" or "codex" or "gemini", …])` | $0 (subscription covers it) |
| Anthropic / OpenAI API key | SDK call | metered per token |
| Local Ollama only | `localhost:11434` OpenAI-compatible endpoint | free, private, slower |

Adding a fourth user shape (mesh of two homes? offline phone? company-licensed Bedrock endpoint?) doesn't require touching channels. It's a fuel-adapter concern, not a channel concern.

## The contract

Every channel daemon honors three substrate operations.

### 1. Publish on inbound

When a message arrives on the channel, publish to `channel.{name}.inbound`:

```python
from orion_substrate import publish, channel_inbound_subject

publish(channel_inbound_subject("discord"), {
    "channel":  "discord",
    "sender":   user_handle_or_id,
    "text":     message_body,
    "ts":       time.time(),
    "thread":   thread_id_if_any,    # optional
    "history_hint": recent_turns,     # optional, last 5–10 turns
})
```

### 2. Subscribe to outbound

The brain (or any subscriber that wants to relay) publishes `channel.{name}.outbound`. Your daemon listens and emits on its surface:

```python
from orion_substrate import subscribe

def on_outbound(subject, payload):
    # payload looks like: {"channel": "discord", "recipient": "...",
    #                      "text": "...", "ts": ..., "fuel_used": "..."}
    discord_send(payload["recipient"], payload["text"])

subscribe(f"channel.discord.outbound", on_outbound)
```

### 3. (Optional) Health heartbeat

If your daemon is long-running, publish `channel.{name}.heartbeat` every 60 seconds with a small status payload. Lets Orion notice when a channel goes silent.

## Reference implementations

The repo ships working daemons for a few channels. Read these to see the pattern in real code:

- **iMessage (macOS)** — `channels/imessage_macos.py` polls the iMessage SQLite database and replies via AppleScript. Demonstrates the poll-and-publish loop. Requires macOS Full Disk Access for the Python interpreter (one-time grant in System Settings).
- **Telegram** — `channels/telegram_bot.py` long-polls the Bot API and replies via the same. Demonstrates the webhook-friendly variant where the channel is naturally async.
- **Webhook (generic)** — `channels/webhook.py` exposes a small HTTP server that any external service can POST to. Use this as the easy on-ramp for SaaS products that send outbound webhooks (Stripe, Linear, GitHub, etc.).

Each is ~80–150 lines and follows the same shape.

## Adding a new channel

Concrete recipe to wire, say, Discord:

1. Pick or write a thin client for the channel's native protocol. For Discord that's `discord.py` (websocket) or your own bot framework.
2. Inside the client's "message received" handler, call `orion_substrate.publish(channel_inbound_subject("discord"), {...})`.
3. Register a subscriber for `channel.discord.outbound` that calls the client's `send()` method.
4. (Optional) Heartbeat every 60s.
5. Run it as a daemon — launchd / systemd / Docker / whatever fits your OS.

That's the whole job. No model code. No fuel code. No brain code. The brain sees `channel.discord.inbound`, picks fuel, replies, publishes `channel.discord.outbound`, your subscriber emits.

## Why daemons stay thin

The brain (`orion_brain_service.py` plus `orion_fuel.py`) handles every concern that's *not* channel-specific:

- Which model to call
- Memory storage and recall
- Cross-channel awareness (the same user texting you on Telegram while also emailing you)
- Plasticity — paths you use stay fresh; unused ones decay
- Contradiction detection — if an old fact and a new fact disagree, surface for resolution
- Transcript persistence

If a future channel needs something the brain doesn't yet do, that's a brain-level upgrade — every channel benefits at once. This is the opposite of the typical pattern where each integration carries a duplicate prompt template, a duplicate retry loop, a duplicate "did the user mean A or B?" disambiguator. We're saying: one brain, many surfaces, no per-surface logic creep.

## What's pluggable, what's not

| Pluggable per user | Not pluggable (system-level) |
|---|---|
| Channels the user wants (any subset of iMessage, Telegram, voice, email, custom) | The substrate (NATS pub/sub) |
| Fuel the user has (any subset of CLIs, API keys, Ollama models) | The fuel adapter shape (`orion_fuel.py`) |
| Where the brain runs (always-on home server, USB-portable, mesh) | The brain contract (recall + memorize + identity) |
| What memory lives where (graph + vector store choices) | Pattern completion across timescales (substrate / plasticity / DMN) |

The system-level pieces are deliberate constraints — they're what makes "all is one" tractable. The user-level pieces are open frontier.

## Status

- ✅ Substrate (NATS) live in production on the reference home server (COMMAND)
- ✅ HLR plasticity per-node (paths thicken with use)
- ✅ DMN process surfacing co-activation patterns
- ⏳ Existing channel daemons being migrated to publish on substrate (additive — keeps existing direct-call paths)
- ⏳ Gmail and other OAuth-required channels: native Python daemon planned to replace n8n workflow

See `project_orion-channel-adapter-pattern.md` (memory) and `project_orion-plexus-architecture.md` (memory) for deeper design notes and the cell-biology vocabulary used throughout.
