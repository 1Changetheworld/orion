# channels/ — Orion's brain-as-network for non-CLI surfaces

Per `project_orion-network-brain-non-cli.md`, the brain isn't memory
for AI tools — it's memory for **every channel you communicate through**.
This package is the framework + reference adapters so any communication
endpoint can plug into the brain in ~30 lines.

## Why this matters

The original brain reach was Claude / Codex / Gemini CLIs via STDIO MCP.
Then we added browser extensions and IDE plugins via HTTP MCP. This
package extends the surface to **anything that can talk** — text,
voice, agents, webhooks. That's the moat: Orion stops being a developer
add-on and becomes a personal AI substrate.

Cellular framing: the brain is the cell nucleus, channels are membrane
receptors, messages are ligands. Same nucleus, many ligand types.

## What ships now

| Channel | Status | Use case |
|---|---|---|
| `webhook.py` | working | Universal HTTP entry. Zapier, n8n, IFTTT, Slack, custom apps |
| `telegram_bot.py` | working | A Telegram bot that asks the brain (long-poll) |
| `imessage_macos.py` | working (macOS only) | Apple Messages bridge (read SQLite + send via osascript) |

## Architecture

```
   any comm channel        the framework        the brain (already running)
   ─────────────────       ──────────────       ─────────────────────────────
   incoming msg ────►      Channel.receive()
                           run_bridge()    ────► HTTP POST /v1/call
                                                  with bearer token
                           Channel.send()  ◄──── reply text from brain
   outgoing msg ◄───
```

Every channel implements two methods. The framework's `run_bridge()`
handles the brain call between them.

## Adding a new channel — minimum viable

```python
from channels import Channel, Message, run_bridge

class MyChannel(Channel):
    name = "my-thing"

    def receive(self):
        while True:
            # poll / listen / whatever
            yield Message(text="user's words", sender="alice")

    def send(self, reply_text, reply_to):
        # deliver reply_text via your channel
        ...

if __name__ == "__main__":
    run_bridge(MyChannel())
```

## Running

Each adapter is a standalone module. Make sure
`orion_brain_service.py` is running (default `127.0.0.1:5556`) before
starting any channel.

```bash
# Terminal 1 — the brain
python orion_brain_service.py

# Terminal 2 — your channel
python -m channels.webhook                # universal HTTP webhook
TELEGRAM_BOT_TOKEN=... python -m channels.telegram_bot
IMESSAGE_ALLOWED_HANDLES=me@you.com python -m channels.imessage_macos
```

## Testing the webhook

Once the webhook channel is running, anything that can POST gets brain
access:

```bash
curl -s -X POST http://127.0.0.1:5599/message \
  -H 'Content-Type: application/json' \
  -d '{"text": "what is my preferred form of address?"}'
```

That's the full demo of brain-as-network: a stranger HTTP client, no
MCP, no AI CLI involved, gets your stored memory back as JSON.

## Roadmap (Phase D-2 per memory)

- `phone_telnyx.py` — STT/TTS bridge for Telnyx phone calls
- `email_imap.py` — inbox webhook → brain → reply
- `discord.py` — Discord bot adapter
- `signal.py` — Signal CLI adapter
- `slack_socket.py` — Slack Socket Mode (no public webhook needed)

These follow the same `Channel` pattern.

## Security

- The brain binds `127.0.0.1` by default. Channels running on the same
  host reach it; nothing outside the host does without an explicit
  `ORION_BRAIN_BIND=0.0.0.0` opt-in.
- Channels that talk to public services (Telegram, iMessage) ALWAYS
  enforce a sender allowlist. iMessage requires it, Telegram strongly
  recommends it via `TELEGRAM_ALLOWED_CHATS`.
- The webhook channel is `127.0.0.1`-only by default. Bind to LAN or
  expose via Tailscale only if you've thought about who can reach it.
