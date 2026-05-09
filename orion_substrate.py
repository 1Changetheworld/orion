"""orion_substrate.py — Layer 1 of the Plexus.

Thin wrapper over NATS (https://nats.io) for Orion's event substrate.
Sub-millisecond pub/sub between channel daemons, brain process, MCP
servers, host wakes. Mesh-capable (NATS clusters across hosts), single
binary, no broker config required for single-host case.

DESIGN PRINCIPLE — graceful degradation:
- If NATS unreachable, every publish becomes a logged no-op.
- Subscribers fail to start cleanly; existing direct-call paths
  continue to work.
- This module is purely additive. No existing call path depends on it.

Subject taxonomy (hierarchical, wildcard-friendly):
    brain.memory.stored / contradicted / synthesized
    brain.identity.changed
    channel.{telegram,imessage,phone,email,webhook}.inbound / outbound
    host.{tag}.wake / heartbeat / first_contact / capabilities
    fuel.{claude,codex,gemini,ollama}.degraded / recovered
    substrate.heartbeat

See project_orion-plexus-architecture.md for the full design.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("orion.substrate")

DEFAULT_TIMEOUT_SEC = float(os.environ.get("ORION_NATS_TIMEOUT", "1.5"))


def _discover_substrate_url() -> str:
    """Find a reachable substrate URL.

    Order: explicit env > LAN > Tailscale > localhost. The first one
    that opens a TCP connection on :4222 wins. Discovery runs only
    once per process (cached on the singleton).

    Why not mDNS: the substrate has to work even when avahi/Bonjour
    is unreliable (Pi headless, Windows VM, USB-host without name
    resolution). Hard-coded IP fallback wins.
    """
    explicit = os.environ.get("ORION_NATS_URL")
    if explicit:
        return explicit

    candidates = [
        "10.0.0.190",       # COMMAND on LAN
        "100.109.99.21",    # COMMAND via Tailscale
        "127.0.0.1",        # local nats-server (USB / standalone host)
    ]

    import socket
    for ip in candidates:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.4)
                if s.connect_ex((ip, 4222)) == 0:
                    return f"nats://{ip}:4222"
        except Exception:
            continue
    # Nothing reachable. Return a localhost URL anyway; connect will
    # fail cleanly and publish becomes a no-op.
    return "nats://127.0.0.1:4222"


DEFAULT_URL = _discover_substrate_url()


def _read_auth_token() -> str | None:
    """Read the bearer token used by orion_brain_service. Same token is
    accepted by NATS via env-loaded credentials when configured. Returns
    None if no token file present (single-host dev mode)."""
    p = Path.home() / ".orion" / "auth-token"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return None


class Substrate:
    """Lazy NATS client. Connects on first publish/subscribe, stays
    connected, reconnects on drop, no-ops on persistent failure.

    Single instance per process — use module-level get_substrate().
    """

    def __init__(self, url: str = DEFAULT_URL):
        self.url = url
        self._nc = None              # nats.aio.client.Client when connected
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._available = False
        self._tried = False
        self._lock = threading.Lock()
        self._subscriptions: list[tuple[str, Callable]] = []

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Run a dedicated event loop in a background thread. NATS
        client is async-native; we wrap it for sync callers."""
        if self._loop and self._loop.is_running():
            return self._loop

        ready = threading.Event()

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        self._loop_thread = threading.Thread(
            target=_run, name="orion-substrate-loop", daemon=True
        )
        self._loop_thread.start()
        ready.wait(timeout=2.0)
        return self._loop

    def _connect_blocking(self) -> bool:
        """Try to connect. Idempotent. Returns True if connected."""
        with self._lock:
            if self._available:
                return True
            if self._tried and not self._available:
                # Already failed once this process; don't keep trying.
                return False
            self._tried = True

            try:
                import nats  # type: ignore
            except ImportError:
                logger.debug("nats-py not installed; substrate disabled")
                return False

            loop = self._ensure_loop()

            async def _do_connect():
                opts = {
                    "servers": [self.url],
                    "connect_timeout": DEFAULT_TIMEOUT_SEC,
                    "max_reconnect_attempts": -1,  # forever, but with backoff
                    "reconnect_time_wait": 1.0,
                }
                token = _read_auth_token()
                if token:
                    opts["token"] = token
                self._nc = await nats.connect(**opts)

            future = asyncio.run_coroutine_threadsafe(_do_connect(), loop)
            try:
                future.result(timeout=DEFAULT_TIMEOUT_SEC + 0.5)
                self._available = True
                logger.info("substrate connected at %s", self.url)
                return True
            except Exception as e:
                logger.debug("substrate connect failed: %s: %s", e.__class__.__name__, e)
                return False

    def publish(self, subject: str, payload: dict | str | bytes) -> None:
        """Publish a message to a subject. Non-blocking, fire-and-forget.
        No-op if NATS unreachable (logs at DEBUG). Safe to call from
        anywhere, including the synchronous critical path of
        GraphMemory.store() — adds < 100 µs to write latency.
        """
        if not self._available and not self._connect_blocking():
            logger.debug("substrate unavailable, dropping publish: %s", subject)
            return

        if isinstance(payload, dict):
            data = json.dumps(payload, default=str).encode("utf-8")
        elif isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = payload

        async def _do_publish():
            try:
                await self._nc.publish(subject, data)
            except Exception as e:
                logger.debug("publish failed for %s: %s", subject, e)

        # fire-and-forget — don't block the caller
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_do_publish(), self._loop)

    def subscribe(self, subject_pattern: str, handler: Callable[[str, dict], None]) -> None:
        """Subscribe to a subject (supports NATS wildcards: * and >).
        Handler receives (subject, decoded_payload_dict). Errors in
        handler are logged but never propagated.

        Subscriptions are recorded so they can be re-established on
        reconnect (NATS handles this automatically once subscribed).
        """
        self._subscriptions.append((subject_pattern, handler))

        if not self._available and not self._connect_blocking():
            logger.debug("substrate unavailable, deferring subscribe: %s", subject_pattern)
            return

        async def _do_subscribe():
            async def _msg_handler(msg):
                try:
                    payload = json.loads(msg.data.decode("utf-8"))
                except Exception:
                    payload = {"_raw": msg.data.decode("utf-8", errors="replace")}
                try:
                    handler(msg.subject, payload)
                except Exception as e:
                    logger.warning("subscribe handler error %s on %s: %s",
                                   handler, msg.subject, e)
            try:
                await self._nc.subscribe(subject_pattern, cb=_msg_handler)
            except Exception as e:
                logger.warning("subscribe failed for %s: %s", subject_pattern, e)

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_do_subscribe(), self._loop)

    @property
    def available(self) -> bool:
        return self._available


_singleton: Substrate | None = None


def get_substrate() -> Substrate:
    """Process-wide singleton. First call starts the background loop +
    attempts connection. Subsequent calls are O(1)."""
    global _singleton
    if _singleton is None:
        _singleton = Substrate()
    return _singleton


def publish(subject: str, payload: dict | str | bytes) -> None:
    """Module-level shortcut: get_substrate().publish(subject, payload)."""
    get_substrate().publish(subject, payload)


def subscribe(subject_pattern: str, handler: Callable[[str, dict], None]) -> None:
    """Module-level shortcut: get_substrate().subscribe(pattern, handler)."""
    get_substrate().subscribe(subject_pattern, handler)


# ---------------------------------------------------------------------
# Subject helpers — return canonical subject strings. Use these instead
# of hand-typed strings in callers, so the taxonomy stays consistent.
# ---------------------------------------------------------------------

def memory_stored_subject() -> str:
    return "brain.memory.stored"


def memory_contradicted_subject() -> str:
    return "brain.memory.contradicted"


def memory_recalled_subject() -> str:
    """Emitted on every successful recall (Layer 2 plasticity event).
    Payload: {node_ids: list[int], ts: float}. DMN subscribes to mine
    co-activation patterns; dispatcher subscribes for capability tagging."""
    return "brain.memory.recalled"


def channel_inbound_subject(channel: str) -> str:
    return f"channel.{channel}.inbound"


def channel_outbound_subject(channel: str) -> str:
    return f"channel.{channel}.outbound"


def host_wake_subject(host_tag: str) -> str:
    return f"host.{host_tag}.wake"


def host_heartbeat_subject(host_tag: str) -> str:
    return f"host.{host_tag}.heartbeat"


def host_capabilities_subject(host_tag: str) -> str:
    return f"host.{host_tag}.capabilities"


def fuel_degraded_subject(fuel: str) -> str:
    return f"fuel.{fuel}.degraded"


def fuel_recovered_subject(fuel: str) -> str:
    return f"fuel.{fuel}.recovered"


# ---------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    s = get_substrate()
    if s._connect_blocking():
        print("[ok] connected to substrate at", s.url)
        s.publish("substrate.heartbeat", {"node": os.uname().nodename if hasattr(os, "uname") else "unknown",
                                          "ts": time.time()})
        print("[ok] published test heartbeat")
        time.sleep(0.5)
    else:
        print("[info] substrate unavailable at", s.url, "— this is fine; falls back to no-op")
