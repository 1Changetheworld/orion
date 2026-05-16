"""orion_autofix.py — known-symptom auto-fix proposals.

The v2 reframe + 2026-05-16 incident: detection is half the loop;
the other half is "if you know the symptom, tell the user the fix
in the SAME message that announces the problem." Don't send three
alerts that say 'broken' — send one alert that says 'broken AND
here's what to do.'

This file subscribes to brain.health.alert from canary or anywhere
else, classifies the symptom against a known-symptom dispatch table,
and on a known symptom REPLACES the bland will narration with a
specific, copy-paste-actionable message via the outbound channel.

Architecture choice: this layer is a SISTER to will, not a replacement.
Will still narrates unknown alerts in plain English. Autofix takes
over for symptoms it recognizes. The two coexist because:

  - Adding a new known symptom = entry in a dict, not retraining will
  - Will handles the long tail; autofix handles the common 80%
  - Each known-symptom entry encodes both DIAGNOSIS and REMEDY,
    closing the loop the founder explicitly asked for 2026-05-16:
    "auto-fixed by intelligence if they arise"

DISPATCH TABLE
==============

Each entry matches against (service, cause_substring) and produces:
  - title: one-line label for the symptom
  - explanation: 1-2 sentences on what's broken in plain English
  - fix_steps: ordered list of copy-paste commands or actions
  - severity_override: optional bump
  - cooldown_sec: per-symptom cooldown (overrides will's default)
  - auto_apply: bool — if true AND fix is safe AND user has consented
    to this symptom class, run the fix without asking

For now nothing auto-applies. Every fix is proposed to the user;
metacog tracks which proposals succeed; future versions can promote
high-success symptoms to auto-apply once consented.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger("orion.autofix")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
DEFAULT_COOLDOWN_SEC = float(os.environ.get("ORION_AUTOFIX_COOLDOWN_SEC", "1800"))


# ─────────────────────────────────────────────────────────
# Known-symptom dispatch table
# ─────────────────────────────────────────────────────────

# Each entry's matcher returns True/False given (service, cause).
# Keep matchers narrow — false positives spam the user with the wrong fix.

KNOWN_SYMPTOMS = [
    {
        "id": "TCC_LAPSE_BRAIN_WRITE",
        "match": lambda svc, cause: (
            "canary.brain.write" in (svc or "") and
            "Operation not permitted" in (cause or "") and
            "graph_memory" in (cause or "")
        ),
        "title": "Brain memory writes blocked by macOS Full Disk Access",
        "explanation": (
            "The brain server (orion_server.py on COMMAND) can no longer write to "
            "/Volumes/AtlasVault/.orion/brain/graph_memory.json. macOS revoked its "
            "Full Disk Access grant — this is a known launchd / TCC behavior. "
            "Until restored, no new memories can be written via the HTTP /memorize "
            "endpoint. Direct file writes still work."
        ),
        "fix_steps": [
            "Open System Settings → Privacy & Security → Full Disk Access",
            "If /usr/bin/python3 is in the list, REMOVE it (click '-')",
            "Click '+' and re-add /usr/bin/python3 (Cmd+Shift+G → /usr/bin/python3)",
            "Toggle the new entry ON",
            "Then: ssh command 'launchctl kickstart -k gui/501/com.orion.brain'",
            "Verify: curl -s -X POST http://COMMAND:5555/memorize -d '{\"content\":\"fda-test\"}'",
        ],
        "cooldown_sec": 3600,  # 1 hour — TCC re-grants happen manually
        "auto_apply": False,
    },
    {
        "id": "OUTBOUND_NO_SUBSCRIBER",
        "match": lambda svc, cause: (
            "canary.imessage.outbound" in (svc or "") and
            "no ACK" in (cause or "")
        ),
        "title": "iMessage outbound adapter not subscribing",
        "explanation": (
            "Nothing on the substrate is responding to channel.imessage.outbound "
            "publishes. The adapter (channels/imessage_outbound.py) is either not "
            "registered as a launchd unit on COMMAND or has crashed."
        ),
        "fix_steps": [
            "ssh command 'launchctl list | grep imessage-outbound'",
            "If missing: ssh command 'launchctl load -w ~/Library/LaunchAgents/com.orion.imessage-outbound.plist'",
            "If present but exit≠0: ssh command 'launchctl kickstart -k gui/501/com.orion.imessage-outbound'",
            "Then: ssh command 'tail -5 ~/.orion/imessage-outbound.err'",
        ],
        "cooldown_sec": 1800,
        "auto_apply": False,
    },
    {
        "id": "CHANNEL_PROBE_CRASH",
        "match": lambda svc, cause: (
            ("channel-probe" in (svc or "") or "channel_probe" in (svc or "")) and
            ("Connection" in (cause or "") or "refused" in (cause or "") or
             "no host" in (cause or ""))
        ),
        "title": "channel-probe crashed (lost substrate connection)",
        "explanation": (
            "channel-probe died and isn't republishing the active-surface manifest. "
            "Without it, reach.py has no channel to pick — every outbound message "
            "from will/executive goes into a queue forever. This was the 24-hour "
            "silent-reach class on 2026-05-16."
        ),
        "fix_steps": [
            "ssh command 'launchctl kickstart -k gui/501/com.orion.channel-probe'",
            "Verify: ssh command 'tail -3 ~/.orion/channel-probe.err'",
            "Verify reach catches up: ssh command 'tail -3 ~/.orion/reach.err'",
        ],
        "cooldown_sec": 600,
        "auto_apply": False,
    },
    {
        "id": "NATS_PARTITION",
        "match": lambda svc, cause: (
            "canary.nats.echo" in (svc or "") and
            ("timeout" in (cause or "").lower() or "refused" in (cause or "").lower())
        ),
        "title": "NATS substrate unreachable from this host",
        "explanation": (
            "Round-trip publish/subscribe on canary.nats.test timed out. The substrate "
            "(nats-server on COMMAND:4222) is either down, partitioned, or this host's "
            "route is broken. Cross-host events (mesh, gossip, channel.*.outbound from "
            "other hosts) will not flow until this clears."
        ),
        "fix_steps": [
            "ssh command 'launchctl kickstart -k gui/501/com.orion.nats'",
            "If still failing: ssh command 'lsof -nP -iTCP:4222 -sTCP:LISTEN'",
            "From this host: nats-pub -s nats://COMMAND:4222 test 'hi' (if installed)",
            "Check Application Firewall: System Settings → Network → Firewall → allow nats-server",
        ],
        "cooldown_sec": 300,
        "auto_apply": False,
    },
    {
        "id": "DISK_WRITE_FAIL",
        "match": lambda svc, cause: (
            "canary.disk.write" in (svc or "")
        ),
        "title": "Disk write to brain dir failed",
        "explanation": (
            "Could not write a probe file to ~/.orion/canary/. Either the directory "
            "is missing/read-only, the disk is full, or AtlasVault is unmounted."
        ),
        "fix_steps": [
            "Check mount: ssh command 'mount | grep -i atlas'",
            "Check disk: ssh command 'df -h /Volumes/AtlasVault'",
            "Re-mount if needed: ssh command 'diskutil mount AtlasVault'",
        ],
        "cooldown_sec": 600,
        "auto_apply": False,
    },
]


# ─────────────────────────────────────────────────────────
# Cooldown bookkeeping — per-symptom, in-process
# ─────────────────────────────────────────────────────────

_last_proposed: dict[str, float] = {}


def _classify(payload: dict) -> Optional[dict]:
    """Match against KNOWN_SYMPTOMS; return entry or None."""
    svc = (payload or {}).get("service", "")
    cause = (payload or {}).get("cause", "") or (payload or {}).get("error", "")
    for entry in KNOWN_SYMPTOMS:
        try:
            if entry["match"](svc, cause):
                return entry
        except Exception as e:
            logger.debug("matcher %s raised: %s", entry["id"], e)
    return None


def _format_proposal(entry: dict, payload: dict) -> str:
    host = payload.get("host", "?")
    fix_lines = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(entry["fix_steps"]))
    return (
        f"⚠️  {entry['title']}\n"
        f"Host: {host}  |  Symptom: {entry['id']}\n\n"
        f"{entry['explanation']}\n\n"
        f"Fix:\n{fix_lines}\n\n"
        f"(I'll stay quiet about this for {int(entry.get('cooldown_sec', DEFAULT_COOLDOWN_SEC)/60)} min unless it changes state.)"
    )


async def _on_health_alert(nc, msg) -> None:
    try:
        payload = json.loads(msg.data.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return
    entry = _classify(payload)
    if not entry:
        # Unknown symptom — let will handle it via its existing path
        return

    sid = entry["id"]
    now = time.time()
    cooldown = entry.get("cooldown_sec", DEFAULT_COOLDOWN_SEC)
    if (now - _last_proposed.get(sid, 0.0)) < cooldown:
        logger.debug("autofix %s within cooldown; skipping", sid)
        return
    _last_proposed[sid] = now

    text = _format_proposal(entry, payload)

    # Publish a proper executive-style proposal that metacog can score,
    # AND send to the user as a single actionable message.
    proposal_id = f"autofix-{sid}-{int(now)}"
    await nc.publish("brain.executive.proposal", json.dumps({
        "decision_id": proposal_id,
        "symptom_class": sid,
        "proposed_action": "; ".join(entry["fix_steps"])[:400],
        "fuel": "autofix-static",
        "host": payload.get("host", "?"),
    }).encode("utf-8"))

    await nc.publish("channel.imessage.outbound", json.dumps({
        "text": text,
        "ts": now,
        "severity": "warning",
        "source": "orion_autofix",
        "symptom_id": sid,
    }).encode("utf-8"))

    logger.warning("AUTOFIX proposal sent for %s", sid)


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
    logger.info("autofix connected to %s (%d known symptoms)",
                NATS_URL, len(KNOWN_SYMPTOMS))

    async def _cb(m):
        await _on_health_alert(nc, m)

    await nc.subscribe("brain.health.alert", cb=_cb)

    stop = asyncio.Event()

    def _shutdown(*_):
        logger.info("autofix shutting down")
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
    await nc.drain()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
