"""orion_channel_probe.py — type-aware channel discovery.

The breakthrough: stop coding per-channel daemons as one-offs. Code
per-channel-TYPE primitives, then probe the host for which specific
surfaces are present. The brain learns:

  "this host has iMessage available + wired + active"
  "this host has Telegram available + wired but dormant 7 days"
  "this host has Slack available but NOT wired — user could enable"
  "this host has Discord NOT available — would need pip install discord.py"

The probe is the discovery layer; the channel-adapter pattern is the
runtime layer; conversational setup ("hey orion, hook up my Slack") is
the user-facing layer. Three layers, each small.

CHANNEL TYPES
=============

  text_bidirectional    — iMessage, Telegram, Slack, Discord, WhatsApp,
                           Matrix, IRC, Signal-cli — any 2-way text
  text_inbound_only     — RSS feeds, mailing lists, news watchers
  text_outbound_only    — Twitter posts, status pages, broadcasts
  voice_bidirectional   — Telnyx phone, Twilio voice, ElevenLabs realtime
  email_async           — Gmail, IMAP/SMTP, Microsoft Graph
  webhook_inbound       — generic HTTP receiver (Stripe, Linear, GitHub)
  radio_mesh            — Meshtastic LoRa, ham digital, off-grid
  gui_desktop           — system notifications, popup dialogs

Each TYPE shares a publish/subscribe contract. Each SURFACE (specific
service) is a thin daemon honoring that contract.

DETECTION SIGNATURES
====================

For each known surface, the probe knows what to look for:

  iMessage:
    - macOS only
    - exists if ~/Library/Messages/chat.db readable

  Telegram:
    - python or node telegram client installed
    - bot token present in env or stored config
    - existing bot session active (TG getMe call)

  Gmail:
    - OAuth credentials present at ~/.config/google/...
    - or n8n workflow with Gmail node (the founder's existing setup)

  Slack:
    - SLACK_TOKEN env or Slack workspace logged in via cli

  Discord:
    - bot token in env or python discord.py installed

  Meshtastic:
    - serial USB device with VID/PID matching Heltec/RAK/T-Beam
    - meshtastic-python importable

The probe runs on every host (or just on the always-on home), publishes
host.{tag}.channels with a manifest of {type, surface, status, hints}.
The claustrum integrates into the global workspace. The brain endpoint
can answer "what comm channels do I have set up?" using this manifest.

OUTPUTS
=======

Subjects:
  host.{tag}.channels — full manifest, every PROBE_INTERVAL_SEC

Persisted:
  ~/.orion/channels/{tag}.json — latest manifest snapshot

STATUS VALUES
=============
  available    — surface is technically present (binary, db file, env)
  wired        — channel adapter daemon is running and connected
  active       — wired AND has had recent traffic (last 24h)
  dormant      — wired but no traffic in 7+ days
  unconfigured — available but not wired (could be wired with N steps)

The user can ask Orion conversationally to wire any "available but
unconfigured" surface. The brain runs the appropriate setup script,
publishes activation events, and the surface joins the live mesh.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger("orion.channel_probe")

CHANNELS_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_CHANNELS_DIR", "~/.orion/channels")
))
PROBE_INTERVAL_SEC = float(os.environ.get("ORION_PROBE_INTERVAL_SEC", "300"))

# ---------- detection per surface ----------

def _probe_imessage() -> dict:
    db = Path.home() / "Library" / "Messages" / "chat.db"
    available = sys.platform == "darwin" and db.exists()
    can_read = False
    if available:
        try:
            import sqlite3
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            con.execute("SELECT 1 FROM message LIMIT 1")
            con.close()
            can_read = True
        except Exception:
            can_read = False
    return {
        "type": "text_bidirectional",
        "surface": "imessage",
        "available": available,
        "wired_hint": "com.orion.imessage launchd plist",
        "needs_grant": (available and not can_read),
        "grant_hint": "macOS Full Disk Access for /usr/bin/python3"
            if (available and not can_read) else None,
    }


def _probe_telegram() -> dict:
    """Richer Telegram detection — find existing bot configs the user
    set up previously, not just env vars. Founder noted having had two
    channels working before; the probe should see them."""
    has_pytelegrambotapi = False
    try:
        __import__("telebot")
        has_pytelegrambotapi = True
    except Exception:
        pass
    has_token = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))

    # Existing daemons + configs the founder may have set up
    found_configs = []
    candidates = [
        Path.home() / "server_data" / "agents" / "agent08_telegram_commander.py",
        Path.home() / ".telegram-bot",
        Path("/Volumes/AtlasVault/atlas/telegram"),
        Path("/Volumes/AtlasVault/backups/telegram"),
    ]
    for c in candidates:
        if c.exists():
            found_configs.append(str(c))

    # Check if any active telegram daemon is publishing on substrate
    # (we can't synchronously check the substrate here without slow
    # round-trip; rely on the wired_hint check below + lastcontact log)

    available = has_token or has_pytelegrambotapi or bool(found_configs)
    return {
        "type": "text_bidirectional",
        "surface": "telegram",
        "available": available,
        "wired_hint": "agent08_telegram_commander.py / channels/telegram_bot.py",
        "found_configs": found_configs,
        "needs_setup": (not has_token and not found_configs),
        "setup_hint": "Talk to @BotFather on Telegram, set TELEGRAM_BOT_TOKEN env. "
                      "If you've used a bot before, the token is likely in your "
                      "old config files — Orion can pick it up automatically.",
    }


def _probe_gmail() -> dict:
    """Richer Gmail detection — credentials at standard paths, n8n
    workflows, plus historical config files the founder set up before."""
    candidates = [
        Path.home() / ".config" / "google" / "credentials.json",
        Path.home() / ".gmail" / "credentials.json",
        Path.home() / ".credentials" / "gmail.json",
        Path.home() / ".credentials" / "credentials.json",
        Path.home() / ".gcloud" / "application_default_credentials.json",
    ]
    found_creds = [str(p) for p in candidates if p.exists()]

    # n8n workflows referencing Gmail (the founder's existing setup)
    n8n_workflows = []
    for d in (Path.home() / "Desktop" / "Mac server configurations" / "n8n_workflows",
              Path("/Volumes/AtlasVault/atlas/n8n_workflows")):
        if d.exists():
            for p in d.glob("*[Gg]mail*"):
                n8n_workflows.append(str(p))

    # n8n's encrypted credentials store
    n8n_creds_db = Path.home() / ".n8n" / "database.sqlite"
    has_n8n_db = n8n_creds_db.exists()

    available = bool(found_creds or n8n_workflows or has_n8n_db)
    return {
        "type": "email_async",
        "surface": "gmail",
        "available": available,
        "wired_hint": "channels/gmail.py (planned) or n8n Gmail trigger",
        "found_creds": found_creds,
        "n8n_workflows": n8n_workflows,
        "n8n_db_present": has_n8n_db,
        "setup_hint": (
            "Existing n8n Gmail workflow detected — Orion can adopt it "
            "as a substrate publisher with a small wrapper, OR write "
            "channels/gmail.py for native Python control."
            if (n8n_workflows or has_n8n_db) else
            "Run gcloud OAuth flow + grant readonly + send scopes, "
            "or use n8n's Gmail trigger node for visual setup."
        ),
    }


def _probe_slack() -> dict:
    return {
        "type": "text_bidirectional",
        "surface": "slack",
        "available": bool(os.environ.get("SLACK_BOT_TOKEN")),
        "wired_hint": "channels/slack.py (planned)",
        "setup_hint": "Slack app config + bot token + channels:history scope",
    }


def _probe_discord() -> dict:
    has_lib = False
    try:
        __import__("discord")
        has_lib = True
    except Exception:
        pass
    return {
        "type": "text_bidirectional",
        "surface": "discord",
        "available": has_lib or bool(os.environ.get("DISCORD_BOT_TOKEN")),
        "wired_hint": "channels/discord.py (planned)",
        "setup_hint": "pip install discord.py + create bot in Discord developer portal",
    }


def _probe_meshtastic() -> dict:
    """Detect Meshtastic library + USB devices + historical config.
    Founder has used Meshtastic before — the probe should find old
    node IDs / config files even if no device is plugged right now."""
    has_lib = False
    try:
        __import__("meshtastic")
        has_lib = True
    except Exception:
        pass

    # Look for serial devices that match Meshtastic-class hardware
    found_devices = []
    dev_dir = Path("/dev")
    if dev_dir.exists():
        for entry in os.listdir("/dev"):
            full = "/dev/" + entry
            if (entry.startswith("cu.SLAB_USBtoUART") or
                entry.startswith("cu.usbserial") or
                entry.startswith("cu.wchusbserial") or
                entry.startswith("cu.usbmodem") or
                entry.startswith("ttyUSB") or
                entry.startswith("ttyACM")):
                found_devices.append(full)

    # Existing config / past sessions
    found_configs = []
    for c in (Path.home() / ".meshtastic.yaml",
              Path.home() / ".config" / "meshtastic",
              Path("/Volumes/AtlasVault/atlas/meshtastic"),
              Path.home() / "Desktop" / "orion-lora-bridge"):
        if c.exists():
            found_configs.append(str(c))

    return {
        "type": "radio_mesh",
        "surface": "meshtastic",
        "available": has_lib or bool(found_devices) or bool(found_configs),
        "found_devices": found_devices,
        "found_configs": found_configs,
        "wired_hint": "channels/meshtastic_node.py",
        "setup_hint": (
            "Meshtastic library + previous configs detected. Plug a node "
            "in via USB and Orion will recognize it automatically."
            if (has_lib or found_configs) else
            "pip install meshtastic pypubsub + USB-attach a Heltec/RAK node"
        ),
    }


def _probe_cursor() -> dict:
    """Cursor IDE — talks to Orion via MCP-over-stdio. Detect Cursor's
    config dir + check if orion-brain is registered as an MCP server."""
    cursor_dir = Path.home() / ".cursor"
    mcp_config = cursor_dir / "mcp.json"
    has_cursor = cursor_dir.exists()
    orion_registered = False
    if mcp_config.exists():
        try:
            cfg = json.loads(mcp_config.read_text(encoding="utf-8"))
            orion_registered = "orion-brain" in (cfg.get("mcpServers") or {})
        except Exception:
            pass
    return {
        "type": "ide_assistant",
        "surface": "cursor",
        "available": has_cursor,
        "orion_registered": orion_registered,
        "wired_hint": "register orion_mcp_server in ~/.cursor/mcp.json (orion_mcp_server.py --setup)",
        "setup_hint": (
            "Cursor present and orion-brain MCP already registered."
            if (has_cursor and orion_registered) else
            "Run: python orion_mcp_server.py --setup to register Orion as "
            "an MCP server in Cursor's config."
        ),
    }


def _probe_browser_extension() -> dict:
    """Orion browser extension (MV3) — runs in Chrome/Edge/Safari.
    Detect installed extension by checking the user's browser extension
    directories. Each browser stores extensions differently."""
    home = Path.home()
    candidates = [
        # Chrome (macOS)
        home / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "Extensions",
        # Chrome (Linux)
        home / ".config" / "google-chrome" / "Default" / "Extensions",
        # Edge
        home / "Library" / "Application Support" / "Microsoft Edge" / "Default" / "Extensions",
        # Safari (macOS) — extensions live elsewhere; harder to probe
        home / "Library" / "Containers",
    ]
    has_browser_dir = any(c.exists() for c in candidates)
    # Rough: if any extension dir contains 'orion' in its files, count as installed
    extension_installed = False
    for c in candidates:
        if c.exists():
            try:
                for ext in c.iterdir():
                    if "orion" in ext.name.lower():
                        extension_installed = True
                        break
            except Exception:
                continue
    return {
        "type": "browser_overlay",
        "surface": "browser_extension",
        "available": has_browser_dir,
        "extension_installed": extension_installed,
        "wired_hint": "load extensions/browser/ as unpacked extension or install from store",
        "setup_hint": (
            "Browser detected. Load Orion's MV3 extension from extensions/browser/ "
            "(Chrome → Manage Extensions → Load Unpacked) — talks to brain over Native Messaging."
        ),
    }


def _probe_voice_telnyx() -> dict:
    has_token = bool(os.environ.get("TELNYX_API_KEY"))
    return {
        "type": "voice_bidirectional",
        "surface": "telnyx",
        "available": has_token,
        "wired_hint": "atlas-voice-webhook.js / com.atlas.voice-webhook",
        "setup_hint": "Telnyx account + webhook URL + verified caller ID",
    }


def _probe_webhook() -> dict:
    return {
        "type": "webhook_inbound",
        "surface": "generic_http",
        "available": True,  # always — we can spin up an HTTP listener anywhere
        "wired_hint": "channels/webhook.py",
        "setup_hint": "Configure your sender (Stripe / Linear / GitHub) to POST to your endpoint",
    }


PROBES = [
    _probe_imessage,
    _probe_telegram,
    _probe_gmail,
    _probe_slack,
    _probe_discord,
    _probe_meshtastic,
    _probe_voice_telnyx,
    _probe_webhook,
    _probe_cursor,
    _probe_browser_extension,
]


# ---------- per-surface status enrichment ----------

def _enrich_with_runtime_status(surfaces: list[dict]) -> None:
    """Augment each surface with status: available | wired | active | dormant
    | unconfigured. Reads ~/.orion/vitals/{svc}.json for wired services and
    ~/.orion/synthesis/contact_log.jsonl for activity recency.
    """
    vitals_dir = Path(os.path.expanduser("~/.orion/vitals"))
    log_path = Path(os.path.expanduser("~/.orion/synthesis/contact_log.jsonl"))

    # Build channel→last_seen from contact log (cheap tail read)
    channel_last = {}
    if log_path.exists():
        try:
            with log_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()[-2000:]  # last 2k events
            for line in lines:
                try:
                    e = json.loads(line)
                    ch = e.get("channel")
                    ts = float(e.get("ts", 0))
                    if ch:
                        channel_last[ch] = max(channel_last.get(ch, 0.0), ts)
                except Exception:
                    continue
        except Exception:
            pass

    now = time.time()
    for s in surfaces:
        surface = s["surface"]
        if not s.get("available"):
            s["status"] = "unconfigured"
            continue

        # Wired? check vitals files for an associated service name
        wired_pattern_match = any(
            (vitals_dir / f"{svc}.json").exists()
            for svc in (surface, f"{surface}_bot", surface.replace("_", "-"))
        )

        last_signal = channel_last.get(surface, 0.0)
        age_days = (now - last_signal) / 86400.0 if last_signal else None

        if wired_pattern_match or last_signal:
            if last_signal and age_days is not None and age_days < 1.0:
                s["status"] = "active"
            elif last_signal and age_days is not None and age_days < 7.0:
                s["status"] = "wired"
            elif last_signal:
                s["status"] = "dormant"
                s["dormant_days"] = round(age_days, 1)
            else:
                s["status"] = "wired"
        else:
            s["status"] = "available_unwired"

        if last_signal:
            s["last_signal_iso"] = time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(last_signal)
            )


# ---------- main loop ----------

_stop = threading.Event()


def _probe_loop() -> None:
    try:
        from orion_substrate import publish
    except ImportError:
        publish = None

    CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
    host_tag = platform.node().split(".")[0].lower() or "unknown"
    out_path = CHANNELS_DIR / f"{host_tag}.json"

    while not _stop.is_set():
        try:
            surfaces = []
            for probe_fn in PROBES:
                try:
                    surfaces.append(probe_fn())
                except Exception as e:
                    logger.debug("probe %s failed: %s", probe_fn.__name__, e)
            _enrich_with_runtime_status(surfaces)

            manifest = {
                "host": host_tag,
                "ts": time.time(),
                "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "surfaces": surfaces,
                "summary": {
                    "available_count": sum(1 for s in surfaces if s.get("available")),
                    "active_count": sum(1 for s in surfaces if s.get("status") == "active"),
                    "wired_count": sum(1 for s in surfaces if s.get("status") in ("wired","active","dormant")),
                    "unconfigured_count": sum(1 for s in surfaces if s.get("status") == "available_unwired"),
                },
            }

            out_path.write_text(json.dumps(manifest, indent=2, default=str),
                                encoding="utf-8")
            if publish:
                publish(f"host.{host_tag}.channels", manifest)
        except Exception as e:
            logger.warning("probe loop error: %s", e)
        _stop.wait(PROBE_INTERVAL_SEC)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("channel_probe alive — probing every %ds", PROBE_INTERVAL_SEC)

    threading.Thread(target=_probe_loop, name="channel-probe", daemon=True).start()

    def _sigterm(_sig, _frame):
        _stop.set()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    while not _stop.is_set():
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
