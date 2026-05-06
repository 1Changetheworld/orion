"""Telegram channel — a Telegram bot that asks Orion's brain.

Long-poll based. No external dependencies — uses urllib for the
Telegram Bot API directly. About 70 lines of actual logic.

Setup:
    1. Talk to @BotFather on Telegram, create a bot, get its token
    2. Set TELEGRAM_BOT_TOKEN in your environment
    3. python -m channels.telegram_bot

The bot replies to direct messages with whatever orion_recall returns.
Group chats only respond to messages addressed at the bot (e.g. /ask).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterator

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from channels.base import Channel, Message, run_bridge  # noqa: E402


TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, token: str | None = None, allowed_chat_ids: list[int] | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not self.token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN missing. Get one from @BotFather on Telegram, "
                "then set the environment variable before running this channel."
            )
        # Optional allowlist — restrict the bot to specific users/groups by chat id.
        # Anyone can DM a public bot otherwise.
        self.allowed_chat_ids = set(allowed_chat_ids or [])
        if not self.allowed_chat_ids:
            extra = os.environ.get("TELEGRAM_ALLOWED_CHATS", "")
            self.allowed_chat_ids = {
                int(x.strip()) for x in extra.split(",") if x.strip()
            }
        self.last_update_id = 0

    def _api(self, method: str, params: dict) -> dict:
        url = TELEGRAM_API.format(token=self.token, method=method)
        data = urllib.parse.urlencode(params).encode("utf-8")
        with urllib.request.urlopen(url, data=data, timeout=35) as r:
            return json.loads(r.read())

    def receive(self) -> Iterator[Message]:
        while True:
            try:
                resp = self._api("getUpdates", {
                    "offset": self.last_update_id + 1,
                    "timeout": 30,
                })
            except Exception as e:
                print(f"[telegram] poll error: {e}", flush=True)
                time.sleep(5)
                continue

            for update in resp.get("result", []):
                self.last_update_id = max(self.last_update_id, update.get("update_id", 0))
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue
                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
                    continue
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                # In groups, only respond to /ask <text> or messages mentioning the bot.
                if chat.get("type") in ("group", "supergroup"):
                    if not text.startswith("/ask"):
                        continue
                    text = text[len("/ask"):].strip()
                    if not text:
                        continue
                sender = msg.get("from", {}).get("username") or str(msg.get("from", {}).get("id", ""))
                yield Message(
                    text=text,
                    sender=sender,
                    channel=self.name,
                    metadata={"chat_id": chat_id, "message_id": msg.get("message_id")},
                )

    def send(self, reply_text: str, reply_to: Message) -> None:
        chat_id = reply_to.metadata.get("chat_id")
        if not chat_id:
            return
        try:
            self._api("sendMessage", {
                "chat_id": chat_id,
                "text": reply_text[:4096],  # Telegram limit
                "reply_to_message_id": reply_to.metadata.get("message_id", 0),
            })
        except Exception as e:
            print(f"[telegram] send error: {e}", flush=True)


if __name__ == "__main__":
    run_bridge(TelegramChannel())
