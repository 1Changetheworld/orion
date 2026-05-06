"""Webhook channel — universal HTTP entry point for the brain.

Anything that can POST JSON gets brain access: Zapier, n8n, IFTTT,
Slack incoming webhooks, custom apps, GitHub webhooks, etc. This is
the most generic channel — every other adapter is essentially a
specialization of "receive a message, send a reply."

Usage:
    python -m channels.webhook                  # listen on 127.0.0.1:5599
    PORT=8080 python -m channels.webhook        # different port
    BIND=0.0.0.0 python -m channels.webhook     # LAN-exposed

POST /message body:
    {"text": "what's my preferred address?", "sender": "alice"}

Response:
    {"reply": "coach"}

The webhook channel doesn't loop — each POST is one request/response.
That's why it overrides the bridge pattern instead of using run_bridge().
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

# Make the repo importable when invoked from anywhere.
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from channels.base import BrainClient, Message  # noqa: E402


PORT = int(os.environ.get("PORT", "5599"))
BIND = os.environ.get("BIND", "127.0.0.1")


class _ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    brain: BrainClient | None = None  # injected by main()

    def log_message(self, fmt, *args):
        pass

    def _respond(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            try:
                h = self.brain.health()
                self._respond(200, {"status": "ok", "brain": h})
            except Exception as e:
                self._respond(503, {"status": "brain unreachable", "error": str(e)})
            return
        self._respond(404, {"error": "POST /message"})

    def do_POST(self):
        if self.path != "/message":
            self._respond(404, {"error": "POST /message"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._respond(400, {"error": "invalid JSON"})
            return

        text = (body.get("text") or "").strip()
        if not text:
            self._respond(400, {"error": "field 'text' required"})
            return

        try:
            reply = self.brain.recall(text, limit=int(body.get("limit", 5)))
        except Exception as e:
            self._respond(502, {"error": "brain call failed", "detail": str(e)})
            return

        self._respond(200, {
            "reply": reply,
            "sender": body.get("sender", ""),
        })


def main():
    brain = BrainClient()
    _Handler.brain = brain
    server = _ThreadedServer((BIND, PORT), _Handler)
    print(f"orion webhook channel listening on http://{BIND}:{PORT}", flush=True)
    print(f"  POST /message  body: {{'text': 'your question', 'sender': 'optional'}}", flush=True)
    print(f"  GET  /health   liveness probe", flush=True)
    print(f"  brain at {brain.base_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye.", flush=True)
        server.server_close()


if __name__ == "__main__":
    main()
