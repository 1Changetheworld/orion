"""orion_team_sync.py — Plexus service that mirrors team-room events
from the NATS substrate into the local ~/.orion/team/ directory.

This is what makes orion_team cross-host: any session that announces
on host A publishes orion.team.announce; this service on host B
subscribes and writes the announcement to host B's local team dir.

So when the founder runs `python orion_team.py list` from any host,
they see every active Orion session on every host that's reachable
through the substrate (LAN cluster or Tailscale).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

logger = logging.getLogger("orion.team.sync")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
TEAM_DIR = Path(os.environ.get("ORION_BRAIN_DIR")
                or str(Path.home() / ".orion")) / "team"
TEAM_DIR.mkdir(parents=True, exist_ok=True)


def _session_file(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)
    return TEAM_DIR / f"{safe}.json"


async def _on_announce_or_update(rec: dict):
    sid = rec.get("session_id")
    if not sid:
        return
    p = _session_file(sid)
    try:
        p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        logger.info("synced %s (%s on %s)", sid, rec.get("role"), rec.get("host"))
    except Exception as e:
        logger.warning("write %s failed: %s", p, e)


async def _on_release(rec: dict):
    sid = rec.get("session_id")
    if not sid:
        return
    p = _session_file(sid)
    if p.exists():
        try:
            p.unlink()
            logger.info("removed %s (released)", sid)
        except Exception:
            pass


async def main_async() -> int:
    try:
        import nats
    except ImportError:
        print("nats-py not installed", file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("team-sync connecting to %s; team dir %s", NATS_URL, TEAM_DIR)

    async def _err_cb(e): logger.debug("nats err: %s", e)
    async def _dis_cb(): logger.debug("nats disconnected")
    async def _rec_cb(): logger.debug("nats reconnected")

    nc = await nats.connect(NATS_URL, error_cb=_err_cb,
                            disconnected_cb=_dis_cb, reconnected_cb=_rec_cb)

    async def _cb(msg):
        try:
            rec = json.loads(msg.data.decode())
        except Exception:
            return
        if msg.subject in ("orion.team.announce", "orion.team.update",
                           "orion.team.heartbeat"):
            await _on_announce_or_update(rec)
        elif msg.subject == "orion.team.release":
            await _on_release(rec)

    await nc.subscribe("orion.team.>", cb=_cb)
    logger.info("team-sync alive — mirroring orion.team.* events to %s", TEAM_DIR)

    stop = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, stop.set)
        loop.add_signal_handler(signal.SIGINT, stop.set)
    except NotImplementedError:
        pass
    await stop.wait()
    await nc.close()
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
