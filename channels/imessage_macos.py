"""iMessage channel (macOS only) — bridges Apple Messages to Orion's brain.

Uses AppleScript via osascript to send replies and SQLite to read
incoming messages from the local chat.db. Polling-based (Messages
doesn't expose a push API to user-space).

This channel is per-host (it reads the local Messages database). The
brain is shared across hosts via the network surface, so an iMessage
sent on a Mac is answered with the same memory Orion has on every
other device.

Requires:
    - macOS with Messages.app signed in
    - Full Disk Access for the python interpreter (System Settings ->
      Privacy & Security -> Full Disk Access -> add Terminal / your shell)
    - Otherwise reading ~/Library/Messages/chat.db will fail.

Setup:
    IMESSAGE_ALLOWED_HANDLES=user@example.com,+15555551234 \\
        python -m channels.imessage_macos

The handle allowlist is mandatory — without it the bridge would reply
to every message you receive, which is almost never what you want.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from channels.base import Channel, Message, run_bridge  # noqa: E402


CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"


class IMessageChannel(Channel):
    name = "imessage"

    def __init__(self, allowed_handles: list[str] | None = None, poll_interval: float = 3.0):
        if sys.platform != "darwin":
            raise RuntimeError("IMessageChannel only runs on macOS.")
        if not CHAT_DB.exists():
            raise RuntimeError(
                f"{CHAT_DB} not found. Open Messages.app at least once and "
                f"sign into iCloud."
            )
        env_handles = os.environ.get("IMESSAGE_ALLOWED_HANDLES", "")
        handles = allowed_handles or [h.strip() for h in env_handles.split(",") if h.strip()]
        if not handles:
            raise RuntimeError(
                "No allowed handles configured. Set IMESSAGE_ALLOWED_HANDLES "
                "(comma-separated, e.g. 'me@example.com,+15555551234') so the "
                "bridge only replies to YOUR messages."
            )
        self.allowed_handles = set(handles)
        self.poll_interval = poll_interval
        # Track the highest ROWID we've seen so we don't reply to history.
        self.last_rowid = self._latest_rowid()

    def _latest_rowid(self) -> int:
        try:
            conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
            cur = conn.execute("SELECT MAX(ROWID) FROM message")
            row = cur.fetchone()
            conn.close()
            return int(row[0] or 0)
        except Exception:
            return 0

    def receive(self) -> Iterator[Message]:
        while True:
            try:
                conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
                # is_from_me=0 → incoming. text NOT NULL filters tapbacks/etc.
                # handle.id is the sender (email or phone).
                cur = conn.execute(
                    """
                    SELECT m.ROWID, m.text, h.id
                    FROM message m
                    JOIN handle h ON m.handle_id = h.ROWID
                    WHERE m.ROWID > ? AND m.is_from_me = 0 AND m.text IS NOT NULL
                    ORDER BY m.ROWID ASC
                    """,
                    (self.last_rowid,),
                )
                rows = cur.fetchall()
                conn.close()
            except sqlite3.Error as e:
                # Most common cause: missing Full Disk Access permission.
                print(f"[imessage] sqlite error (Full Disk Access?): {e}", flush=True)
                time.sleep(self.poll_interval * 2)
                continue

            for rowid, text, handle in rows:
                self.last_rowid = max(self.last_rowid, rowid)
                if handle not in self.allowed_handles:
                    continue
                if not text or not text.strip():
                    continue
                yield Message(
                    text=text.strip(),
                    sender=handle,
                    channel=self.name,
                    metadata={"rowid": rowid},
                )

            time.sleep(self.poll_interval)

    def send(self, reply_text: str, reply_to: Message) -> None:
        # AppleScript via osascript is the supported way to send from
        # a script to Messages. Replace double quotes for safety.
        clean = reply_text.replace('"', "'").replace("\\", "\\\\")
        script = f'''
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{reply_to.sender}" of targetService
            send "{clean}" to targetBuddy
        end tell
        '''
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True, capture_output=True, timeout=15,
            )
        except subprocess.CalledProcessError as e:
            print(f"[imessage] send failed: {e.stderr.decode()}", flush=True)


if __name__ == "__main__":
    run_bridge(IMessageChannel())
