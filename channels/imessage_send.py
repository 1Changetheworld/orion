"""imessage_send.py — resilient iMessage delivery for modern macOS.

WHY THIS EXISTS (2026-06-04)
============================
macOS 15.x "Sequoia" removed `service`, `account`, and `buddy` from the
Messages AppleScript dictionary. The classic construction every Orion
sender used —

    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy "X" of targetService
    send "T" to targetBuddy

— now silently no-ops or raises `-1728` ("Can't get name of every
account") / `-2753` ("variable buddies is not defined"). It is NOT the
code rotting; Apple deprecated the scripting surface. This is the
"same iMessage issue again and again" the founder reported.

WHAT THIS DOES
==============
Tries several delivery strategies IN ORDER and returns on the first that
exits cleanly, logging WHICH strategy worked so the field can prune to
the survivor per macOS version (we cannot test every macOS from the
build host, so we ship the cascade and let the canonical host reveal the
winner):

  1. shortcuts CLI  — Apple-native, most future-proof. Runs a user
     Shortcut named by $ORION_IMESSAGE_SHORTCUT that takes the message
     text on stdin and sends it. Skipped if the env var is unset.
  2. AppleScript `send to buddy "X"` — the UNQUALIFIED buddy form, which
     still resolves on several Sequoia point releases (no `service`/
     `account` noun needed).
  3. AppleScript participant-of-service — newer dictionary nouns.
  4. AppleScript legacy buddy-of-targetService — pre-Sequoia hosts.

Shared guard: a validated recipient (phone or email; placeholder
literals like 'primary_user' are hard-rejected), a 30s osascript
timeout, and one retry-on-timeout — the protections the hardened
single-strategy sender already had, now applied to every strategy.

NO API KEYS. Everything here is local OS tooling (osascript / shortcuts).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys

logger = logging.getLogger("orion.imessage.send")

# Osascript timing — Messages.app on a loaded mac can take >15s.
_OSASCRIPT_TIMEOUT_SEC = int(os.environ.get("ORION_IMESSAGE_TIMEOUT", "30"))
_OSASCRIPT_RETRIES = 1
_RETRY_BACKOFF_SEC = 3

_INVALID_RECIPIENT_LITERALS = {
    "primary_user", "user", "default", "default_user",
    "", "none", "null", "undefined",
}
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s\(\)\.]{6,}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_recipient(recipient: str) -> tuple[bool, str]:
    """(is_valid, reason). The boundary guard against placeholder leaks
    (e.g. 'primary_user') that fail silently inside Messages.app."""
    if not recipient or not isinstance(recipient, str):
        return False, "empty/non-string recipient"
    r = recipient.strip()
    if r.lower() in _INVALID_RECIPIENT_LITERALS:
        return False, "placeholder literal: %r" % r
    if _PHONE_RE.match(r) or _EMAIL_RE.match(r):
        return True, "ok"
    return False, "not a phone number or email: %r" % r


def _escape_applescript(text: str) -> str:
    """Escape backslashes then double-quotes for an AppleScript string."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _run_osascript(script: str) -> tuple[bool, str]:
    """Run one osascript program with timeout + one retry-on-timeout.
    Returns (ok, error). A non-timeout failure does NOT retry (a returncode
    is usually an AppleScript ERROR — re-sending won't help)."""
    import time
    last_err = ""
    for attempt in range(_OSASCRIPT_RETRIES + 1):
        try:
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True,
                timeout=_OSASCRIPT_TIMEOUT_SEC,
            )
            if r.returncode == 0:
                return True, ""
            last_err = "rc=%s stderr=%s" % (r.returncode, (r.stderr or "")[:200])
            return False, last_err
        except subprocess.TimeoutExpired:
            last_err = "timeout after %ds (attempt %d/%d)" % (
                _OSASCRIPT_TIMEOUT_SEC, attempt + 1, _OSASCRIPT_RETRIES + 1)
            if attempt < _OSASCRIPT_RETRIES:
                time.sleep(_RETRY_BACKOFF_SEC)
                continue
        except FileNotFoundError:
            return False, "osascript not found (not macOS?)"
        except Exception as e:
            return False, "%s: %s" % (e.__class__.__name__, e)
    return False, last_err


def _applescript_variants(recipient: str, clean: str) -> list[tuple[str, str]]:
    """(strategy_name, script) pairs, ordered most-modern-first."""
    return [
        ("as:buddy-unqualified",
         'tell application "Messages"\n'
         f'    send "{clean}" to buddy "{recipient}"\n'
         'end tell'),
        ("as:participant-of-service",
         'tell application "Messages"\n'
         '    set svc to 1st service whose service type = iMessage\n'
         f'    send "{clean}" to participant "{recipient}" of svc\n'
         'end tell'),
        ("as:legacy-buddy-of-service",
         'tell application "Messages"\n'
         '    set targetService to 1st service whose service type = iMessage\n'
         f'    set targetBuddy to buddy "{recipient}" of targetService\n'
         f'    send "{clean}" to targetBuddy\n'
         'end tell'),
    ]


def _strategy_shortcuts(recipient: str, text: str) -> tuple[bool, str]:
    """Run a user Shortcut named by $ORION_IMESSAGE_SHORTCUT, piping the
    message text on stdin. The Shortcut owns the recipient + the Messages
    'Send Message' action — the Apple-blessed, scripting-dictionary-proof
    path. Skipped (returns (False, 'skip')) when the env var is unset."""
    name = os.environ.get("ORION_IMESSAGE_SHORTCUT")
    if not name:
        return False, "skip"
    try:
        r = subprocess.run(
            ["shortcuts", "run", name],
            input=text, capture_output=True, text=True,
            timeout=_OSASCRIPT_TIMEOUT_SEC,
        )
        if r.returncode == 0:
            return True, ""
        return False, "rc=%s stderr=%s" % (r.returncode, (r.stderr or "")[:200])
    except FileNotFoundError:
        return False, "shortcuts CLI not found"
    except Exception as e:
        return False, "%s: %s" % (e.__class__.__name__, e)


def send_imessage(recipient: str, text: str) -> bool:
    """Deliver `text` to `recipient` via the first working strategy.

    Logs the winning strategy at INFO and every miss at WARNING, so the
    canonical host's logs reveal which method survives the running macOS
    version. Returns True on the first clean send, False if all fail.
    """
    valid, reason = validate_recipient(recipient)
    if not valid:
        logger.error("REFUSING send — invalid recipient (%s). text=%r",
                     reason, text[:80])
        return False

    # Strategy 1: shortcuts CLI (if configured).
    ok, err = _strategy_shortcuts(recipient, text)
    if ok:
        logger.info("sent to %s via shortcuts:%s",
                    recipient, os.environ.get("ORION_IMESSAGE_SHORTCUT"))
        return True
    if err != "skip":
        logger.warning("imessage strategy shortcuts failed: %s", err)

    # Strategies 2-4: AppleScript variants.
    clean = _escape_applescript(text)
    for name, script in _applescript_variants(recipient, clean):
        ok, err = _run_osascript(script)
        if ok:
            logger.info("sent to %s via %s: %s", recipient, name, text[:80])
            return True
        logger.warning("imessage strategy %s failed: %s", name, err)

    logger.error("ALL iMessage strategies failed for %s — surface is DOWN "
                 "(macOS may have changed the Messages scripting surface again)",
                 recipient)
    return False


def _cli() -> int:
    """On-device tester: python channels/imessage_send.py <recipient> <text...>
    Prints which strategy won. Run this on COMMAND to find the survivor."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if len(sys.argv) < 3:
        print("usage: imessage_send.py <recipient> <text...>", file=sys.stderr)
        return 2
    recipient = sys.argv[1]
    text = " ".join(sys.argv[2:])
    ok = send_imessage(recipient, text)
    print("DELIVERED" if ok else "FAILED — see warnings above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
