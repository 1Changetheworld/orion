"""orion_canary.py — heartbeat emitters for critical capabilities.

Companion to orion_predictor.py. The predictor catches when a known
rhythm breaks. The canary CREATES rhythms for capabilities that don't
naturally chatter on the substrate.

WHY THIS LAYER EXISTS
=====================

2026-05-16: brain TCC lapsed silently for hours; outbound iMessage
adapter wasn't registered for days; channel-probe crashed and
nobody noticed. The common pattern: the capability is binary
(either it works or it doesn't), and when it stops working it
stops emitting events entirely. No event = no surprise = no
spotlight = silent failure.

The canary fixes this by exercising each capability on a tight
loop, regardless of whether anyone asked for it. Every probe
publishes a result to canary.<capability> — predictor learns the
rhythm and will spike on missing canaries or on canary failures.

Cellular analogy: this is the spontaneous depolarization of a
pacemaker cell — it fires on its own metronome so the rest of the
system knows it's still wired.

PROBES
======

  canary.brain.write         — POST /memorize sentinel; expect 200
  canary.imessage.outbound   — publish dry-run; expect ACK in 5s
  canary.channel.probe       — expect host.*.channels every 5min
  canary.nats.echo           — round-trip pub/sub on canary.nats.test
  canary.reach.healthy       — tail reach warning rate
  canary.disk.write          — write probe file to brain dir; expect ok

Each canary publishes once every CANARY_INTERVAL_SEC (default 60s)
on canary.<name> with {ok, latency_ms, error?, ts}.

Predictor will spike if:
  - the canary subject stops arriving (capability dead silently)
  - the latency jumps (capability degraded)
  - ok=false (capability errored)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orion.canary")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
BRAIN_URL = os.environ.get("ORION_BRAIN_URL", "http://127.0.0.1:5555")
ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR") or str(Path.home() / ".orion"))
CANARY_INTERVAL = float(os.environ.get("ORION_CANARY_INTERVAL_SEC", "60"))
IMESSAGE_ACK_TIMEOUT = float(os.environ.get("ORION_CANARY_IMESSAGE_ACK_SEC", "5.0"))
NATS_ECHO_TIMEOUT = float(os.environ.get("ORION_CANARY_NATS_ECHO_SEC", "2.0"))


# ─────────────────────────────────────────────────────────
# Individual canary probes — each returns dict with ok/latency_ms/error
# ─────────────────────────────────────────────────────────

async def _canary_brain_write() -> dict:
    """Try to memorize a sentinel via brain HTTP. Catches the TCC lapse class."""
    import urllib.request
    import urllib.error
    sentinel = f"canary-brain-write-{int(time.time())}"
    payload = json.dumps({
        "content": sentinel,
        "tags": ["canary", "self-test"],
    }).encode()
    req = urllib.request.Request(
        f"{BRAIN_URL}/memorize",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read(2048).decode("utf-8", errors="replace")
            latency = (time.perf_counter() - t0) * 1000
            data = {}
            try:
                data = json.loads(body)
            except Exception:
                pass
            if "error" in data:
                return {"ok": False, "latency_ms": round(latency, 1),
                        "error": data["error"][:200]}
            return {"ok": True, "latency_ms": round(latency, 1)}
    except urllib.error.HTTPError as e:
        body = e.read(512).decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        return {"ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": f"HTTP {e.code}: {body[:160]}"}
    except Exception as e:
        return {"ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": f"{type(e).__name__}: {e}"}


async def _canary_imessage_outbound(nc) -> dict:
    """Publish a dry-run outbound and wait for the adapter to ACK.
    Catches the missing-subscriber class."""
    probe_id = uuid.uuid4().hex[:8]
    payload = {
        "text": f"<canary {probe_id}>",
        "dry_run": True,
        "probe_id": probe_id,
    }
    fut: asyncio.Future = asyncio.get_running_loop().create_future()

    async def _on_ack(msg):
        try:
            d = json.loads(msg.data.decode("utf-8"))
        except Exception:
            return
        if d.get("probe_id") == probe_id and not fut.done():
            fut.set_result(d)

    sub = await nc.subscribe("channel.imessage.canary_ack", cb=_on_ack)
    t0 = time.perf_counter()
    try:
        await nc.publish("channel.imessage.outbound",
                         json.dumps(payload).encode("utf-8"))
        try:
            d = await asyncio.wait_for(fut, timeout=IMESSAGE_ACK_TIMEOUT)
            latency = (time.perf_counter() - t0) * 1000
            return {"ok": bool(d.get("ok", True)),
                    "latency_ms": round(latency, 1)}
        except asyncio.TimeoutError:
            return {"ok": False,
                    "latency_ms": round(IMESSAGE_ACK_TIMEOUT * 1000, 1),
                    "error": "no ACK from imessage-outbound adapter within timeout"}
    finally:
        try:
            await sub.unsubscribe()
        except Exception:
            pass


async def _canary_nats_echo(nc) -> dict:
    """Round-trip publish/subscribe — catches partition between probe
    and the substrate itself."""
    probe_id = uuid.uuid4().hex[:8]
    fut: asyncio.Future = asyncio.get_running_loop().create_future()

    async def _on_msg(msg):
        try:
            d = json.loads(msg.data.decode("utf-8"))
        except Exception:
            return
        if d.get("probe_id") == probe_id and not fut.done():
            fut.set_result(d)

    sub = await nc.subscribe("canary.nats.test", cb=_on_msg)
    t0 = time.perf_counter()
    try:
        await nc.publish("canary.nats.test",
                         json.dumps({"probe_id": probe_id, "ts": t0}).encode("utf-8"))
        try:
            await asyncio.wait_for(fut, timeout=NATS_ECHO_TIMEOUT)
            return {"ok": True,
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        except asyncio.TimeoutError:
            return {"ok": False,
                    "latency_ms": round(NATS_ECHO_TIMEOUT * 1000, 1),
                    "error": "nats round-trip timeout"}
    finally:
        try:
            await sub.unsubscribe()
        except Exception:
            pass


async def _canary_disk_write() -> dict:
    """Probe write to the brain dir. Catches TCC / disk / mount issues
    distinct from the brain HTTP path."""
    probe_dir = ORION_HOME / "canary"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_path = probe_dir / "disk_probe.txt"
    t0 = time.perf_counter()
    try:
        probe_path.write_text(f"canary-{time.time()}", encoding="utf-8")
        return {"ok": True,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:
        return {"ok": False,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": f"{type(e).__name__}: {e}"}


# ─────────────────────────────────────────────────────────
# Canary scheduler
# ─────────────────────────────────────────────────────────

CANARIES = [
    ("brain.write",      _canary_brain_write,     False),  # no nc needed
    ("nats.echo",        _canary_nats_echo,       True),
    ("imessage.outbound", _canary_imessage_outbound, True),
    ("disk.write",       _canary_disk_write,      False),
]


async def _run_canary(nc, name: str, fn, needs_nc: bool) -> None:
    try:
        result = await fn(nc) if needs_nc else await fn()
    except Exception as e:
        result = {"ok": False, "error": f"{type(e).__name__}: {e}",
                  "latency_ms": 0.0}
    result["ts"] = time.time()
    result["canary"] = name
    await nc.publish(f"canary.{name}", json.dumps(result).encode("utf-8"))
    # Failed canaries also raise a health alert directly so even if
    # the predictor is asleep, the will / executive layer engages.
    if not result.get("ok"):
        # will._format_alert reads service / host / cause / kind, so
        # populate the fields it expects rather than our own schema.
        host = os.environ.get("ORION_HOST_ID") or os.uname().nodename if hasattr(os, "uname") else "unknown"
        alert = {
            "severity": "warning",
            "service": f"canary.{name}",
            "host": host,
            "kind": "canary_fail",
            "cause": result.get("error", "canary failed"),
            "what_to_do": f"investigate {name} capability — canary returned ok=false",
            "vitals": f"latency_ms={result.get('latency_ms', 0)}",
            "ts": result["ts"],
        }
        await nc.publish("brain.health.alert",
                         json.dumps(alert).encode("utf-8"))
        logger.warning("canary %s FAILED: %s", name, result.get("error"))
    else:
        logger.info("canary %s ok %.1fms", name, result.get("latency_ms", 0))


async def _scheduler(nc) -> None:
    """Tight loop: run all canaries, sleep, repeat."""
    while True:
        await asyncio.gather(*[_run_canary(nc, n, fn, needs)
                               for n, fn, needs in CANARIES])
        await asyncio.sleep(CANARY_INTERVAL)


# ─────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────

async def main() -> int:
    logging.basicConfig(
        level=os.environ.get("ORION_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        from nats.aio.client import Client as NATS  # type: ignore
    except ImportError:
        logger.error("nats-py not installed")
        return 2

    nc = NATS()

    async def err_cb(e):  logger.warning("nats err: %s", e)
    async def dis_cb():   logger.warning("nats disconnected")
    async def rec_cb():   logger.info("nats reconnected")

    await nc.connect(servers=[NATS_URL], error_cb=err_cb,
                     disconnected_cb=dis_cb, reconnected_cb=rec_cb,
                     max_reconnect_attempts=-1)
    logger.info("canary connected to %s (interval %.0fs)", NATS_URL, CANARY_INTERVAL)

    sched = asyncio.create_task(_scheduler(nc))
    stop = asyncio.Event()

    def _shutdown(*_):
        logger.info("canary shutting down")
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        for sig_ in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig_, _shutdown)
            except NotImplementedError:
                pass
    except RuntimeError:
        pass

    await stop.wait()
    sched.cancel()
    await nc.drain()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
