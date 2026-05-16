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
    """Non-destructive probe of the brain write path. Verifies the brain
    server is responsive AND that the graph file is writable from the
    SAME process context the brain uses — without polluting graph_memory.

    History: an earlier version POSTed sentinels to /memorize, which
    (a) created junk memory nodes, and (b) raced with concurrent writers
    on the brain server's read-modify-write loop, overwriting legitimate
    memory writes. Disastrous. Fixed 2026-05-16 by switching to a
    read-only health probe plus a side-channel file write at a separate
    path that tests the same TCC / disk / mount class without touching
    graph_memory.json.
    """
    import urllib.request
    import urllib.error
    # Part 1: brain HTTP responsiveness
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(f"{BRAIN_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp.read(1024)
        http_ok = True
        http_err = ""
    except urllib.error.HTTPError as e:
        # /health may not exist on older brain servers; try /recall as a
        # GET-shape fallback that older brains accept without writing
        if e.code in (404, 405):
            try:
                req2 = urllib.request.Request(
                    f"{BRAIN_URL}/recall?query=canary-probe",
                    method="GET",
                )
                with urllib.request.urlopen(req2, timeout=8) as resp:
                    resp.read(1024)
                http_ok = True
                http_err = ""
            except Exception as ee:
                http_ok = False
                http_err = f"{type(ee).__name__}: {ee}"
        else:
            http_ok = False
            http_err = f"HTTP {e.code}"
    except Exception as e:
        http_ok = False
        http_err = f"{type(e).__name__}: {e}"

    # Part 2: graph file write-permission probe (separate file, never the graph)
    graph_dir = Path("/Volumes/AtlasVault/.orion/brain")
    probe_path = graph_dir / ".canary_probe"
    fs_ok = False
    fs_err = ""
    try:
        if graph_dir.exists():
            probe_path.write_text(f"canary-{time.time()}", encoding="utf-8")
            fs_ok = True
        else:
            # Brain dir not mounted — not a TCC issue, a disk issue
            fs_ok = False
            fs_err = f"brain dir missing: {graph_dir}"
    except PermissionError as e:
        fs_err = f"PermissionError (likely TCC): {e}"
    except Exception as e:
        fs_err = f"{type(e).__name__}: {e}"

    latency = (time.perf_counter() - t0) * 1000
    if http_ok and fs_ok:
        return {"ok": True, "latency_ms": round(latency, 1)}
    return {
        "ok": False,
        "latency_ms": round(latency, 1),
        "error": (
            f"http_ok={http_ok} ({http_err}); "
            f"graph_writable={fs_ok} ({fs_err})"
        )[:240],
    }


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

# Per-probe state for edge-triggered alerting + exponential backoff.
# Spam-fix 2026-05-16: alerts fire on transitions + escalating intervals,
# never on every-failure-tick. State: {last_state, fail_count, last_alert_ts}.
_probe_state: dict[str, dict] = {}

# Backoff schedule for SUSTAINED failures (in seconds). After a transition
# alert fires once, the same failure re-alerts only at these multiples
# from the FIRST failure: 5min, 30min, 2hr, 24hr. After that, silent.
_BACKOFF_SCHEDULE_SEC = [300, 1800, 7200, 86400]


def _should_alert(name: str, ok: bool, now: float) -> tuple[bool, str]:
    """Returns (should_emit_alert, transition_kind).
    transition_kind ∈ {'ok_to_fail', 'fail_to_ok', 'sustained_escalation', 'none'}."""
    state = _probe_state.get(name, {"last_state": None, "fail_count": 0,
                                     "first_fail_ts": 0.0, "alert_idx": 0})
    last = state["last_state"]
    transition = "none"
    emit = False

    if ok:
        if last is False:
            transition = "fail_to_ok"
            emit = True
            state["fail_count"] = 0
            state["alert_idx"] = 0
            state["first_fail_ts"] = 0.0
    else:
        if last is not False:
            transition = "ok_to_fail"
            emit = True
            state["first_fail_ts"] = now
            state["fail_count"] = 1
            state["alert_idx"] = 0
        else:
            state["fail_count"] += 1
            # Sustained — only emit if we've hit the next backoff threshold
            elapsed = now - state["first_fail_ts"]
            idx = state["alert_idx"]
            if idx < len(_BACKOFF_SCHEDULE_SEC) and elapsed >= _BACKOFF_SCHEDULE_SEC[idx]:
                transition = "sustained_escalation"
                emit = True
                state["alert_idx"] = idx + 1

    state["last_state"] = ok
    _probe_state[name] = state
    return emit, transition


async def _run_canary(nc, name: str, fn, needs_nc: bool) -> None:
    try:
        result = await fn(nc) if needs_nc else await fn()
    except Exception as e:
        result = {"ok": False, "error": f"{type(e).__name__}: {e}",
                  "latency_ms": 0.0}
    result["ts"] = time.time()
    result["canary"] = name
    await nc.publish(f"canary.{name}", json.dumps(result).encode("utf-8"))

    emit, transition = _should_alert(name, bool(result.get("ok")), result["ts"])
    if not emit:
        if result.get("ok"):
            logger.debug("canary %s ok %.1fms (no transition)", name, result.get("latency_ms", 0))
        else:
            logger.debug("canary %s still failing (suppressed; next alert per backoff)", name)
        return

    host = os.environ.get("ORION_HOST_ID") or (os.uname().nodename if hasattr(os, "uname") else "unknown")

    if transition == "fail_to_ok":
        recovery = {
            "severity": "info",
            "service": f"canary.{name}",
            "host": host,
            "kind": "canary_recovered",
            "vitals": f"latency_ms={result.get('latency_ms', 0)}",
            "ts": result["ts"],
        }
        await nc.publish("brain.health.recovered",
                         json.dumps(recovery).encode("utf-8"))
        logger.info("canary %s RECOVERED", name)
        return

    # Failure alert (either ok_to_fail or sustained_escalation)
    fail_count = _probe_state[name]["fail_count"]
    alert = {
        "severity": "warning" if transition == "ok_to_fail" else "critical",
        "service": f"canary.{name}",
        "host": host,
        "kind": transition,  # 'ok_to_fail' or 'sustained_escalation'
        "cause": result.get("error", "canary failed"),
        "what_to_do": f"investigate {name} capability — {fail_count} consecutive failures",
        "vitals": f"latency_ms={result.get('latency_ms', 0)} fails={fail_count}",
        "ts": result["ts"],
    }
    await nc.publish("brain.health.alert",
                     json.dumps(alert).encode("utf-8"))
    logger.warning("canary %s ALERT (%s) — %s", name, transition, result.get("error"))


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
