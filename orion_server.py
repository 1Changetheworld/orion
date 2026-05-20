#!/usr/bin/env python3
"""Orion Brain Server v6 — Clean, threaded, fast dispatch, smart email.
This server exposes the brain on port 5555.
"""
import json
import re
import sys
import os
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fast dispatch
try:
    from orion_dispatch import execute as dispatch_execute, DISPATCH_MAP
    DISPATCH_OK = True
except Exception:
    DISPATCH_OK = False
    DISPATCH_MAP = {}

NL_COMMANDS = {
    "check status": "status", "show status": "status", "system status": "status",
    "check mesh": "mesh", "device status": "mesh",
    "show services": "services", "docker status": "services",
    "show agents": "agents", "check disk": "disk", "show ip": "ip",
}

BRIDGE_URL = "http://127.0.0.1:3460"


class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def compose_with_opus(instruction):
    """Use Claude CLI to compose content. Returns text or None."""
    try:
        payload = json.dumps({
            "prompt": instruction + " Return ONLY the content, nothing else. No headers, no explanation.",
            "interface": "compose",
            "max_turns": 3
        }).encode()
        req = urllib.request.Request(BRIDGE_URL, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read())
            output = result.get("output", "").strip()
            if output and not output.startswith("Error") and not output.startswith("Not logged"):
                return output
    except Exception:
        pass
    return None


class Handler(BaseHTTPRequestHandler):
    def _respond(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == '/health':
            self._respond(200, {'status': 'ok', 'service': 'orion-brain-v6'})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            message = body.get('message', '')
            interface = body.get('interface', 'webhook')
            user_id = body.get('user_id', 'orion')

            if not message:
                self._respond(400, {'error': 'message required'})
                return

            msg_lower = message.strip().lower().rstrip('!?.')

            if DISPATCH_OK:
                # ═══ SLASH COMMANDS ═══
                if message.strip().startswith('/'):
                    parts = message.strip().split(None, 1)
                    cmd = parts[0][1:].lower()
                    args = parts[1] if len(parts) > 1 else ""
                    if cmd in DISPATCH_MAP:
                        try:
                            result = dispatch_execute(cmd, args)
                            if result:
                                self._respond(200, {"response": result, "engine": "dispatch:" + cmd, "task_type": "command", "interface": interface})
                                return
                        except Exception:
                            pass

                # ═══ NATURAL LANGUAGE COMMANDS ═══
                for phrase, cmd in NL_COMMANDS.items():
                    if phrase in msg_lower:
                        try:
                            result = dispatch_execute(cmd, "")
                            if result:
                                self._respond(200, {"response": result, "engine": "dispatch:" + cmd, "task_type": "command", "interface": interface})
                                return
                        except Exception:
                            pass
                        break

                # ═══ SMART EMAIL — Opus composes, dispatch sends ═══
                if "email" in msg_lower and "@" in message:
                    addr_match = re.search(r'[\w.+-]+@[\w.-]+', message)
                    if addr_match:
                        to_addr = addr_match.group()
                        # Opus composes the email content based on the user's instruction
                        email_body = compose_with_opus("Write an email based on this request: " + message)
                        if not email_body:
                            email_body = "This is a message from ORION."
                        subject = "From ORION"
                        try:
                            result = dispatch_execute("email", to_addr + "|" + subject + "|" + email_body)
                            if result and "sent" in result.lower():
                                self._respond(200, {"response": "Email composed and sent to " + to_addr + ", sir.", "engine": "opus+dispatch:email", "task_type": "action", "interface": interface})
                                return
                        except Exception:
                            pass

            # ═══ FULL BRAIN ═══
            from orion_brain import think
            result = think(message, interface=interface, user_id=user_id)
            self._respond(200, result)

        except Exception as e:
            self._respond(500, {'response': 'I encountered an internal issue, sir. Please try again.', 'error': str(e)})

    def log_message(self, format, *args):
        sys.stderr.write('%s %s\n' % (self.log_date_time_string(), format % args))


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5555
    server = ThreadedServer(('0.0.0.0', port), Handler)
    print('Orion Brain v6 on port %d' % port)
    server.serve_forever()
