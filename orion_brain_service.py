#!/usr/bin/env python3
"""
ORION BRAIN SERVICE — Unified HTTP transport for the brain.

The single network endpoint for Orion's brain. Today it runs alongside
orion_mcp_server.py (STDIO MCP) and orion_server.py (legacy HTTP).
Once browser extensions, IDE plugins, and desktop AI apps are wired
to this surface, the legacy servers get retired.

Why this exists:
    Orion is no longer "AI memory for terminal CLIs." Per the
    2026-05-05 founder reframe, the brain serves EVERYTHING on the
    host — browser extensions, IDE plugins, native AI desktop apps,
    phones on the same WiFi, anything that speaks HTTP.

Strangler-fig pattern:
    This module imports the tool registry and dispatch logic from
    orion_mcp_server.py — same handlers, additive HTTP transport.
    No changes to the STDIO server that's currently working.

Endpoints:
    GET  /health       Liveness probe (no auth — for loadbalancers)
    GET  /v1/tools     List all brain tools (REST, auth required)
    POST /v1/call      Invoke a tool by name (REST, auth required)
                       Body: {"name": "orion_recall", "arguments": {...}}
    POST /mcp          MCP JSON-RPC 2.0 (auth required)
                       For clients that speak MCP-over-HTTP. v1 is
                       simple POST/JSON; full Streamable HTTP transport
                       (the 2025-03-26 spec) is a Phase 2 add-on.
    OPTIONS *          CORS preflight

Security model:
    - Bearer token auth via Authorization: Bearer <token>
    - Token auto-generated at first start, stored at ~/.orion/auth-token
    - Host-header allowlist (DNS-rebinding defense — public DNS pointing
      at 127.0.0.1 would otherwise let a malicious site call this service)
    - Origin allowlist for CORS (browser extensions get explicit ALLOW)
    - Default bind: 127.0.0.1 only. Set ORION_BRAIN_BIND=0.0.0.0 to expose
      to LAN (only do this when the user explicitly opts in).

Configuration (all via env vars):
    ORION_BRAIN_PORT             default 5556 (5555 is reserved for legacy
                                  orion_server.py during transition)
    ORION_BRAIN_BIND             default 127.0.0.1
    ORION_AUTH_TOKEN_PATH        default ~/.orion/auth-token
    ORION_BRAIN_EXTRA_HOSTS      comma-separated additional Host values
                                  (use when binding to LAN IP)
    ORION_BRAIN_ALLOWED_ORIGINS  comma-separated additional CORS origins

Usage:
    python orion_brain_service.py                  # 127.0.0.1:5556
    ORION_BRAIN_PORT=5557 python orion_brain_service.py
    ORION_BRAIN_BIND=0.0.0.0 \
        ORION_BRAIN_EXTRA_HOSTS=192.168.1.42 \
        python orion_brain_service.py              # LAN-exposed
"""

import json
import os
import secrets
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn

_this_dir = Path(__file__).resolve().parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

# Reuse the existing MCP tool surface and dispatch logic — strangler-fig.
# orion_mcp_server.py keeps working as a STDIO server; we add an HTTP
# transport that calls the same handlers.
from orion_mcp_server import (
    TOOLS,
    _HANDLERS,
    handle_message,
    SERVER_INFO,
    CAPABILITIES,
)


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

PORT = int(os.environ.get("ORION_BRAIN_PORT", "5556"))
BIND = os.environ.get("ORION_BRAIN_BIND", "127.0.0.1")
AUTH_TOKEN_PATH = Path(os.path.expanduser(os.environ.get(
    "ORION_AUTH_TOKEN_PATH", "~/.orion/auth-token"
)))

# Contact attribution (the /contact endpoint). The brain owns the single
# "who we last spoke through" record; per-turn hooks POST their surface here.
GRAPH_PATH = Path(os.path.expanduser(os.environ.get(
    "ORION_GRAPH_PATH", "~/.orion/brain/graph_memory.json")))
SYNTH_DIR = Path(os.path.expanduser(os.environ.get(
    "ORION_SYNTH_DIR", "~/.orion/synthesis")))

# Host-header allowlist. Anything not in this set is rejected even
# if the connection itself is bound to localhost — guards against
# DNS-rebinding where a public domain points at 127.0.0.1 to trick
# the user's browser into calling the brain on behalf of an attacker.
ALLOWED_HOSTS = {
    "127.0.0.1", f"127.0.0.1:{PORT}",
    "localhost", f"localhost:{PORT}",
}
for h in os.environ.get("ORION_BRAIN_EXTRA_HOSTS", "").split(","):
    h = h.strip()
    if h:
        ALLOWED_HOSTS.add(h)
        ALLOWED_HOSTS.add(f"{h}:{PORT}")

# Origins permitted to call from a browser context. The patterns
# ending in `*` match anything starting with the prefix — this is
# how we whitelist all browser-extension installs without knowing
# their exact extension IDs ahead of time.
DEFAULT_ALLOWED_ORIGINS = {
    "chrome-extension://*",
    "moz-extension://*",
    "safari-web-extension://*",
    "vscode-webview://*",
    "http://localhost",
    "http://127.0.0.1",
}
ALLOWED_ORIGINS = set(DEFAULT_ALLOWED_ORIGINS)
for o in os.environ.get("ORION_BRAIN_ALLOWED_ORIGINS", "").split(","):
    o = o.strip()
    if o:
        ALLOWED_ORIGINS.add(o)


# ─────────────────────────────────────────────────────────────────
# Auth: bearer token, auto-generated on first start
# ─────────────────────────────────────────────────────────────────

def get_or_create_auth_token() -> str:
    """Return the bearer token, generating one if it doesn't exist."""
    AUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if AUTH_TOKEN_PATH.exists():
        existing = AUTH_TOKEN_PATH.read_text().strip()
        if existing:
            return existing
    token = secrets.token_urlsafe(32)
    AUTH_TOKEN_PATH.write_text(token)
    try:
        AUTH_TOKEN_PATH.chmod(0o600)  # owner-only on Unix; no-op on Windows
    except (OSError, NotImplementedError):
        pass
    return token


AUTH_TOKEN = get_or_create_auth_token()


def origin_allowed(origin: str) -> bool:
    """Match origin against ALLOWED_ORIGINS (supports glob suffix `*`)."""
    if not origin:
        return False
    if origin in ALLOWED_ORIGINS:
        return True
    for pattern in ALLOWED_ORIGINS:
        if pattern.endswith("*") and origin.startswith(pattern[:-1]):
            return True
    return False


# ─────────────────────────────────────────────────────────────────
# Contact attribution — the brain owns one "who we last spoke through" record
# ─────────────────────────────────────────────────────────────────

_AUTONOMIC_DIRS = {"canary_ack", "canary", "heartbeat", "probe", "ping", "keepalive",
                   "delivery_status", "delivery", "receipt", "read_receipt",
                   "ack", "status", "sent"}


def _real_contacts(limit_runs=3):
    """Read the durable contact log, drop autonomic reflexes, collapse runs of
    the same surface, and return the most-recent few distinct contacts. This is
    the short trail that lets ANY surface answer 'where did we last speak' with
    the PREVIOUS surface, not just itself."""
    path = SYNTH_DIR / "contact_log.jsonl"
    runs = []
    if not path.exists():
        return runs
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("text") or ""
        if d.get("dry_run") or d.get("probe_id") or t.lstrip().startswith("<canary") \
                or d.get("direction") in _AUTONOMIC_DIRS:
            continue
        ch = d.get("channel") or "unknown"
        # 'cli-mcp' is the generic recall machinery (a brain lookup with no known
        # surface), not a real conversation. Now that turns are surface-attributed
        # via /contact, exclude it so the trail reads claude/codex/gemini cleanly.
        if ch == "cli-mcp" or d.get("direction") == "recall":
            continue
        # "where did we last speak" = where the USER last reached us. Only INBOUND
        # counts — Orion's own outbound notifications (Wonder/will iMessages) are
        # Orion talking AT the user, not contact. This is why claude reported
        # iMessage: an outbound notification was the most recent "contact". (2026-06-08)
        if d.get("direction") != "inbound":
            continue
        if runs and runs[-1]["channel"] == ch:
            runs[-1] = d  # collapse consecutive same-surface; keep newest
        else:
            runs.append(d)
    return runs[-limit_runs:][::-1]  # newest first


def _recent_turns(limit=8):
    """The last N real turns across ALL surfaces — BOTH sides (your prompts and
    Orion's replies) — for the shared short-term memory injected into every
    window. Prefers the two-sided conversation_log (from orion_conversation_sync)
    and falls back to the user-only contact_log. This is the three-windows-in-a-
    wall analogy: one Orion that notices a repeat across windows AND remembers
    what it itself answered (James, 2026-06-07)."""
    rows = []

    def _ingest(path, surface_key, role_fn):
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = (d.get("text") or "").strip()
            if not t or t.lstrip().startswith("<canary") or d.get("dry_run") or d.get("probe_id"):
                continue
            surface = d.get(surface_key) or "?"
            role = role_fn(d)
            if surface == "cli-mcp" or role in (_AUTONOMIC_DIRS | {"recall"}):
                continue
            rows.append({"surface": surface, "role": role, "text": t[:240],
                         "ts": float(d.get("ts") or 0), "iso": d.get("iso", "")})

    # two-sided conversation (tailer): both your prompts and Orion's replies
    _ingest(SYNTH_DIR / "conversation_log.jsonl", "surface", lambda d: d.get("role") or "user")
    # user prompts from the per-turn hook — covers any surface the tailer misses
    _ingest(SYNTH_DIR / "contact_log.jsonl", "channel",
            lambda d: "user" if d.get("direction") == "inbound" else (d.get("direction") or "user"))

    rows.sort(key=lambda r: r["ts"])
    # dedup the hook+tailer double-count of the same user turn (same surface/role/
    # text within a few seconds)
    deduped = []
    for r in rows:
        if any(s["role"] == r["role"] and s["surface"] == r["surface"]
               and s["text"][:60] == r["text"][:60] and abs(s["ts"] - r["ts"]) < 12
               for s in deduped[-8:]):
            continue
        deduped.append(r)
    return deduped[-limit:]


def _resume_markers(limit=3):
    """Latest 'where we left off' markers written by orion_conversation_sync when
    a session goes quiet. Lets any newly-opened window resume a prior thread."""
    path = SYNTH_DIR / "session_resume.jsonl"
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("last_user") or d.get("last_orion"):
            out.append(d)
    return out[-limit:][::-1]  # newest first


def _upsert_contact(surface, direction, text):
    """Append this contact to the durable log, then rebuild the single
    cross_interface_contact node as a short newest-first trail. Atomic write."""
    now = time.time()
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    with (SYNTH_DIR / "contact_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"channel": surface, "direction": direction,
                            "text": (text or "")[:500], "ts": now, "iso": iso}) + "\n")

    trail = _real_contacts(limit_runs=3)
    if trail:
        head = trail[0]
        parts = ["via %s at %s" % (c.get("channel", "?"), c.get("iso", "?")) for c in trail]
        content = ("Last cross-interface contact: %s via %s (%s). "
                   "Where we last spoke (most recent first): %s."
                   % (head.get("iso", iso), head.get("channel", surface),
                      head.get("direction", direction), "; ".join(parts)))
    else:
        content = "Last cross-interface contact: %s via %s (%s)." % (iso, surface, direction)

    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    nodes = graph.setdefault("nodes", {})
    cid = None
    for nid, n in nodes.items():
        if n.get("type") == "cross_interface_contact" and "last_seen" in (n.get("tags") or []):
            cid = nid
            break
    if cid is not None:
        n = nodes[cid]
        n["content"] = content
        n["last_confirmed_at"] = now
        n["last_seen"] = now
        n["confidence"] = 1.0
    else:
        nid = str(graph.get("next_id", len(nodes)))
        graph["next_id"] = int(nid) + 1
        nodes[nid] = {"content": content, "type": "cross_interface_contact",
                      "confidence": 1.0,
                      "tags": ["contact", "last_seen", "cross_interface", "activity",
                               "speak", "talked", "spoke"],
                      "created": now, "last_confirmed_at": now, "last_seen": now,
                      "aliases": [], "summary": "most recent cross-interface contact"}
    tmp = GRAPH_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(graph, indent=2, default=str), encoding="utf-8")
    os.replace(str(tmp), str(GRAPH_PATH))
    return content


# ─────────────────────────────────────────────────────────────────
# HTTP server + handler
# ─────────────────────────────────────────────────────────────────

class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class BrainHandler(BaseHTTPRequestHandler):
    server_version = f"OrionBrain/{SERVER_INFO['version']}"

    def log_message(self, fmt, *args):
        # Quiet by default; flip to write to a log file once we have one.
        pass

    # ── CORS + security helpers ──
    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Credentials", "true")
            # Chromium Private Network Access — required for fetches
            # from public-origin pages reaching localhost.
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Mcp-Session-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "600")

    def _check_host(self) -> bool:
        host = self.headers.get("Host", "")
        return host in ALLOWED_HOSTS

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return secrets.compare_digest(auth[7:].strip(), AUTH_TOKEN)

    def _respond_json(self, code, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _respond_error(self, code, message, detail=None):
        payload = {"error": message}
        if detail:
            payload["detail"] = detail
        self._respond_json(code, payload)

    # ── HTTP method handlers ──
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if not self._check_host():
            self._respond_error(403, "host header not allowed")
            return

        # /health is unauthenticated so loadbalancers / monitors can probe.
        if self.path == "/health":
            self._respond_json(200, {
                "status": "ok",
                "service": SERVER_INFO["name"],
                "version": SERVER_INFO["version"],
                "transport": ["rest", "mcp-over-http"],
                "tool_count": len(TOOLS),
            })
            return

        # VESSEL SEAM C (SERVE): the signed canonical whoami descriptor.
        # Unauthenticated like /health — it carries NO private key and is
        # Ed25519-signed, so any secondary host can verify-on-bind against
        # its pin. This is the off-box surface that makes the mesh's
        # one-brain guarantee enforceable. See
        # docs/architecture/vessel-canonical-identity.md.
        if self.path == "/vessel/whoami":
            try:
                import orion_vessel
                self._respond_json(200, orion_vessel.build_whoami_descriptor())
            except Exception as e:
                self._respond_error(503, "vessel whoami unavailable", str(e))
            return

        if not self._check_auth():
            self._respond_error(401, "unauthorized — bearer token required")
            return

        if self.path == "/v1/tools":
            self._respond_json(200, {"tools": TOOLS})
            return

        # /recent — shared short-term conversational memory across all windows.
        if self.path.startswith("/recent"):
            try:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                limit = max(1, min(20, int((q.get("limit") or ["6"])[0])))
            except Exception:
                limit = 6
            try:
                self._respond_json(200, {"turns": _recent_turns(limit)})
            except Exception as e:
                self._respond_error(500, "recent error", str(e))
            return

        # /resume — latest "where we left off" session markers (capture-on-close)
        if self.path.startswith("/resume"):
            try:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                limit = max(1, min(10, int((q.get("limit") or ["3"])[0])))
            except Exception:
                limit = 3
            try:
                self._respond_json(200, {"sessions": _resume_markers(limit)})
            except Exception as e:
                self._respond_error(500, "resume error", str(e))
            return

        self._respond_error(404, "not found")

    def do_POST(self):
        if not self._check_host():
            self._respond_error(403, "host header not allowed")
            return
        if not self._check_auth():
            self._respond_error(401, "unauthorized — bearer token required")
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            self._respond_error(400, "invalid JSON body")
            return

        # ── REST: simple tool invocation ──
        if self.path == "/v1/call":
            tool_name = payload.get("name")
            tool_args = payload.get("arguments", {})
            handler = _HANDLERS.get(tool_name)
            if not handler:
                self._respond_error(404, f"unknown tool: {tool_name}")
                return
            try:
                t0 = time.perf_counter()
                result = handler(tool_args)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                self._respond_json(200, {
                    "content": result,
                    "elapsed_ms": round(elapsed_ms, 2),
                })
            except Exception as e:
                self._respond_error(500, "tool execution error", str(e))
            return

        # ── /contact — per-turn surface attribution ──
        # A per-turn hook (any CLI / channel) POSTs {surface, direction?, text?}.
        # The brain updates the single contact trail on disk and RINGS THE BELL
        # so the brain service + every per-CLI MCP cache reload it. This is what
        # lets model B answer "we last spoke in <model A>" — the surface is
        # recorded into the one brain, live, the moment a turn happens.
        if self.path == "/contact":
            surface = (payload.get("surface") or "unknown").strip() or "unknown"
            direction = payload.get("direction") or "inbound"
            text = payload.get("text") or ""
            try:
                content = _upsert_contact(surface, direction, text)
                try:
                    from orion_substrate import publish as _pub
                    _pub("brain.memory.stored", {
                        "source": "contact-endpoint",
                        "node_type": "cross_interface_contact",
                        "ts": time.time(),
                    })
                except Exception:
                    pass
                self._respond_json(200, {"status": "ok", "surface": surface,
                                         "content": content})
            except Exception as e:
                self._respond_error(500, "contact update error", str(e))
            return

        # ── /chat — legacy-compatible communication-channel endpoint ──
        # Existing iMessage / Telegram / phone daemons (per
        # docs/architecture/brain-as-network.md) POST to a brain endpoint
        # with shape {message, interface, user_id, sender}. The legacy
        # orion_server.py on port 5555 handled this. As we unify the brain
        # under one service, this endpoint preserves that contract so
        # existing channel daemons keep working unchanged when migrated to
        # the new service.
        #
        # Authenticated like everything else (bearer token). If a channel
        # daemon needs to call from another host (e.g., a macOS box running
        # the iMessage bridge hitting a cloud-mode brain), it presents the bearer.
        if self.path == "/chat":
            message = (payload.get("message") or "").strip()
            interface = payload.get("interface") or "unknown"
            sender = payload.get("sender") or payload.get("user_id") or "unknown"
            if not message:
                self._respond_error(400, "field 'message' required")
                return
            try:
                # Recall what the brain knows about this sender's last context,
                # then memorize the incoming message. Models reading the brain
                # later see the channel's traffic as part of one continuous
                # memory stream.
                handler = _HANDLERS.get("orion_recall")
                recall = handler({"query": message, "limit": 5}) if handler else []
                recall_text = ""
                for blk in recall:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        recall_text = blk.get("text", "")
                        break
                # Memorize the inbound message attributed to its channel + sender
                mem_handler = _HANDLERS.get("orion_memorize")
                if mem_handler:
                    mem_handler({
                        "content": f"[{interface}/{sender}] {message}",
                        "tags": ["inbound-message", interface, sender],
                        "type": "conversation",
                    })
                # The brain's job here is recall + memorize. The channel
                # adapter is responsible for synthesizing a reply (via its
                # fuel of choice — Claude CLI, Codex, Ollama, etc.). We
                # return the recall context so the adapter can compose.
                # If the caller wants pure context, they get it; if they
                # want a generated response, they call orion_chat (TBD)
                # or compose locally.
                self._respond_json(200, {
                    "status": "ok",
                    "interface": interface,
                    "sender": sender,
                    "context": recall_text,
                    "response": recall_text or "Message stored. No prior context found.",
                })
            except Exception as e:
                self._respond_error(500, "chat dispatch error", str(e))
            return

        # ── MCP over HTTP: delegate to the JSON-RPC dispatcher ──
        if self.path == "/mcp":
            try:
                response = handle_message(payload)
                if response is None:
                    # Notification — no response per JSON-RPC 2.0 spec.
                    self.send_response(204)
                    self._cors_headers()
                    self.end_headers()
                    return
                self._respond_json(200, response)
            except Exception as e:
                self._respond_error(500, "mcp dispatch error", str(e))
            return

        self._respond_error(404, "not found")


# ─────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────

def serve():
    # Mark ourselves so orion_mcp_server.py (which we re-import for the
    # /mcp endpoint dispatch) skips its proxy logic. Without this, every
    # /mcp tools/call would HTTP-loop back to /v1/call on the same process.
    os.environ["ORION_INSIDE_BRAIN_SERVICE"] = "1"
    server = ThreadedServer((BIND, PORT), BrainHandler)
    print(f"Orion Brain Service listening on http://{BIND}:{PORT}", flush=True)
    print(f"Bearer token: {AUTH_TOKEN_PATH}", flush=True)
    print(f"Tools registered: {len(TOOLS)}", flush=True)
    print(f"", flush=True)
    print(f"Endpoints:", flush=True)
    print(f"  GET  /health        liveness (no auth)", flush=True)
    print(f"  GET  /v1/tools      list tools (auth)", flush=True)
    print(f"  POST /v1/call       invoke tool (auth)", flush=True)
    print(f"  POST /mcp           MCP JSON-RPC (auth)", flush=True)
    print(f"", flush=True)
    print(f"Smoke test:", flush=True)
    print(f"  curl -s http://{BIND}:{PORT}/health", flush=True)
    print(f"  curl -s -H 'Authorization: Bearer '$(cat {AUTH_TOKEN_PATH}) "
          f"http://{BIND}:{PORT}/v1/tools | head -c 200", flush=True)
    print(f"", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
        server.server_close()


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        # Self-test: import-only sanity check (no server start).
        # Used by CI / pre-commit to catch import errors fast.
        print(f"OK — imported {len(TOOLS)} tools, {len(_HANDLERS)} handlers")
        print(f"Auth token path: {AUTH_TOKEN_PATH}")
        sys.exit(0)
    serve()
