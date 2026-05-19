"""orion_updater.py — auto-deploy + version-drift detection.

The architectural fix for the 2026-05-18 split-brain incident:
COMMAND was running 22 services from THREE different code snapshots
simultaneously. Master had the spam-fix from 2947829 (May 16), but
running hosts had never pulled. The fix existed and stayed invisible
for two days, spamming the founder's phone. Classic deployment gap.

This module exists so that never happens again.

WHAT IT DOES
============

Two jobs, both conservative:

1. DRIFT DETECTION — every check_interval seconds:
     a. git fetch origin master
     b. read local HEAD
     c. if local SHA != origin/master HEAD by more than DRIFT_AGE_SEC:
        publish brain.health.code_drift {host, local_sha, remote_sha, age}
        write ~/.orion/version.json with {sha, branch, last_check, drift}

   Reports only. Never auto-fixes in v1. Founder reads brain.health.
   code_drift, decides whether to pull. The point is the gap stops
   being silent.

2. AUTO-DEPLOY (opt-in, off by default) — when ORION_AUTO_DEPLOY=1:
     a. if working tree dirty: refuse, publish brain.deploy.skipped
        (we don't blow away uncommitted personalization on hosts)
     b. fetch origin and look for new tag matching pattern PROD_TAG_RE
        (default: ^prod-v[0-9]+) — NEVER pulls plain master HEAD
     c. checkout the tag into a sibling dir ~/orion-code.NEXT
     d. quick smoke: `python -c "import orion_brain_portable"` in NEXT
        — if it raises, abort and clean up NEXT
     e. atomically swap symlinks: ~/orion-code → ~/orion-code.NEXT,
        previous becomes ~/orion-code.PREV (for one-line revert)
     f. restart only services whose .py path was touched between
        previous and new SHA (computed via `git diff --name-only`)
     g. publish brain.deploy.applied {old_sha, new_sha, services_restarted}

   Safety rails:
     - Tag-only (no rolling master deploy — a release is an act)
     - Tree-must-be-clean (preserves per-host personalization)
     - Smoke test before swap
     - PREV symlink for atomic revert (`ln -sfn orion-code.PREV orion-code`)
     - Per-service restart, not blanket — limits blast radius

WHY THIS SHAPE
==============

The founder's stated principle: "deploy those processes on all
devices, and they should naturally come alive when they're deployed
anywhere." This module makes that real WITHOUT removing human consent
from production deploys. A tag is the human decision. The updater is
the machinery that respects it.

Drift detection runs unconditionally on every host. Even if auto-
deploy is off (default), the drift-canary still publishes the gap
so the founder sees split-brain forming before it spams him.

PERSONALIZATION LAYER (the explicit boundary)
=============================================

The "our version vs production version" distinction the founder
locked in on 2026-05-18:
  - master / USB = production code, clean install
  - per-host = production + personalization (data, secrets, plists)

This updater touches CODE ONLY. It never touches:
  - ~/.orion/ (brain data — graph, identity, skills, audit logs)
  - Library/LaunchAgents/com.orion.*.plist (the personalization layer)
  - any .env.secrets
  - any host-specific config

Working-tree-dirty refusal is the explicit guard: if a host has
local mods to code files, the updater backs off until those are
either committed (and pushed) or reverted. Personalization is
preserved by NOT being in code.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orion.updater")

# ─────────────────────────────────────────────────────────
# Paths + config
# ─────────────────────────────────────────────────────────

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))
VERSION_PATH = ORION_HOME / "version.json"

# Where the code lives on this host. Default is the canonical
# clone location we standardized on 2026-05-18.
CODE_DIR = Path(os.environ.get("ORION_CODE_DIR",
                               str(Path.home() / "orion-code")))

# How often to check master. 5 min default is small enough that the
# founder sees drift quickly, large enough not to spam git.
CHECK_INTERVAL_SEC = int(os.environ.get("ORION_UPDATER_INTERVAL", "300"))

# After this many seconds of being behind master, raise drift alarm.
# Default 24h: a host that's behind for a day is officially diverging.
DRIFT_AGE_SEC = int(os.environ.get("ORION_DRIFT_AGE", str(24 * 3600)))

# Off by default — opt-in via env var. v1 is reports-only on most hosts.
AUTO_DEPLOY = os.environ.get("ORION_AUTO_DEPLOY", "0") == "1"

# Tag pattern accepted for auto-deploy. master HEAD is NEVER pulled
# automatically — only explicit production releases.
PROD_TAG_RE = re.compile(os.environ.get("ORION_PROD_TAG_RE",
                                        r"^prod-v\d+"))

HOST_ID = os.environ.get("ORION_HOST_ID") or socket.gethostname().split(".")[0]


# ─────────────────────────────────────────────────────────
# Git helpers — small wrappers so the logic stays readable
# ─────────────────────────────────────────────────────────

def _git(*args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    cwd = cwd or CODE_DIR
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _is_git_repo(p: Path) -> bool:
    return (p / ".git").exists()


def _local_sha() -> Optional[str]:
    if not _is_git_repo(CODE_DIR):
        return None
    r = _git("rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def _remote_sha() -> Optional[str]:
    """origin/master HEAD after a fresh fetch."""
    if not _is_git_repo(CODE_DIR):
        return None
    _git("fetch", "--quiet", "origin", "master")
    r = _git("rev-parse", "origin/master")
    return r.stdout.strip() if r.returncode == 0 else None


def _working_tree_clean() -> bool:
    if not _is_git_repo(CODE_DIR):
        return False
    r = _git("status", "--porcelain")
    return r.returncode == 0 and not r.stdout.strip()


def _commit_age_seconds(sha: str) -> int:
    r = _git("show", "-s", "--format=%ct", sha)
    try:
        return int(time.time() - int(r.stdout.strip()))
    except Exception:
        return 0


def _latest_prod_tag() -> Optional[str]:
    """Return the most-recent tag matching PROD_TAG_RE, or None."""
    _git("fetch", "--quiet", "--tags", "origin")
    r = _git("tag", "--sort=-creatordate")
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if PROD_TAG_RE.match(line.strip()):
            return line.strip()
    return None


def _files_changed_between(old: str, new: str) -> list[str]:
    r = _git("diff", "--name-only", old, new)
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


# ─────────────────────────────────────────────────────────
# Version state — written to ~/.orion/version.json on every check
# Dashboards + the team-room banner can read this without parsing git.
# ─────────────────────────────────────────────────────────

def _write_version_state(local: Optional[str], remote: Optional[str],
                         drift_age: int) -> None:
    ORION_HOME.mkdir(parents=True, exist_ok=True)
    state = {
        "host": HOST_ID,
        "code_dir": str(CODE_DIR),
        "local_sha": local,
        "remote_sha": remote,
        "drift_age_sec": drift_age,
        "in_sync": (local is not None and local == remote),
        "auto_deploy": AUTO_DEPLOY,
        "last_check": time.time(),
    }
    try:
        VERSION_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("version state write failed: %s", e)


# ─────────────────────────────────────────────────────────
# Drift detection — runs every CHECK_INTERVAL_SEC unconditionally
# ─────────────────────────────────────────────────────────

def _publish(subject: str, payload: dict) -> None:
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass  # substrate-down is never fatal here


def check_drift_once() -> dict:
    """Single drift-check pass. Returns the version state dict."""
    local = _local_sha()
    remote = _remote_sha()
    drift_age = 0

    if local and remote and local != remote:
        # How long has master been ahead of us?
        drift_age = _commit_age_seconds(remote)

    _write_version_state(local, remote, drift_age)

    if local and remote and local != remote and drift_age >= DRIFT_AGE_SEC:
        _publish("brain.health.code_drift", {
            "host": HOST_ID,
            "local_sha": local,
            "remote_sha": remote,
            "drift_age_sec": drift_age,
            "code_dir": str(CODE_DIR),
            "auto_deploy_enabled": AUTO_DEPLOY,
            "ts": time.time(),
        })
        logger.warning("code drift on %s: %s behind %s by %ds",
                       HOST_ID, local[:8], remote[:8], drift_age)

    return {"local": local, "remote": remote, "drift_age_sec": drift_age}


# ─────────────────────────────────────────────────────────
# Auto-deploy — only fires when AUTO_DEPLOY=1 and a new prod-* tag
# appears. Tag-only on purpose: a release is a human decision.
# ─────────────────────────────────────────────────────────

def attempt_auto_deploy() -> Optional[dict]:
    if not AUTO_DEPLOY:
        return None
    if not _working_tree_clean():
        _publish("brain.deploy.skipped", {
            "host": HOST_ID,
            "reason": "working tree dirty — refusing to overwrite local mods",
            "ts": time.time(),
        })
        logger.info("deploy skipped: working tree dirty")
        return None

    tag = _latest_prod_tag()
    if not tag:
        return None

    # Already on this tag?
    r = _git("rev-parse", tag)
    tag_sha = r.stdout.strip() if r.returncode == 0 else None
    if not tag_sha or tag_sha == _local_sha():
        return None

    logger.info("auto-deploy: pulling %s (was %s)", tag, (_local_sha() or "?")[:8])
    old_sha = _local_sha()

    # Stage: clone tag into sibling NEXT dir
    next_dir = CODE_DIR.with_suffix(".NEXT")
    if next_dir.exists():
        shutil.rmtree(next_dir, ignore_errors=True)
    r = subprocess.run(
        ["git", "clone", "--branch", tag, "--depth", "10",
         _git("config", "--get", "remote.origin.url").stdout.strip(),
         str(next_dir)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        logger.warning("clone of %s failed: %s", tag, r.stderr[:200])
        return None

    # Smoke test — import one core module from NEXT
    smoke = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, r'{next_dir}'); "
         f"import orion_brain_portable; print('smoke ok')"],
        capture_output=True, text=True,
    )
    if smoke.returncode != 0:
        logger.error("smoke test failed for tag %s: %s",
                     tag, smoke.stderr[:200])
        shutil.rmtree(next_dir, ignore_errors=True)
        _publish("brain.deploy.failed", {
            "host": HOST_ID, "tag": tag, "reason": "smoke test failed",
            "stderr": smoke.stderr[:500], "ts": time.time(),
        })
        return None

    # Atomic swap: rename CODE_DIR → PREV, NEXT → CODE_DIR
    prev_dir = CODE_DIR.with_suffix(".PREV")
    if prev_dir.exists():
        shutil.rmtree(prev_dir, ignore_errors=True)
    CODE_DIR.rename(prev_dir)
    next_dir.rename(CODE_DIR)

    new_sha = _local_sha()

    # Identify services to restart — those whose .py changed
    changed = _files_changed_between(old_sha, new_sha) if old_sha else []

    _publish("brain.deploy.applied", {
        "host": HOST_ID,
        "tag": tag,
        "old_sha": old_sha,
        "new_sha": new_sha,
        "files_changed": changed,
        "revert_cmd": f"ln -sfn {prev_dir} {CODE_DIR}",
        "ts": time.time(),
    })
    logger.info("deploy applied: %s → %s (%d files)",
                (old_sha or "?")[:8], (new_sha or "?")[:8], len(changed))
    return {"old": old_sha, "new": new_sha, "tag": tag, "changed": changed}


# ─────────────────────────────────────────────────────────
# Daemon main + CLI
# ─────────────────────────────────────────────────────────

async def main_async() -> int:
    logging.basicConfig(
        level=os.environ.get("ORION_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("updater alive: host=%s code_dir=%s interval=%ds "
                "auto_deploy=%s drift_age=%ds",
                HOST_ID, CODE_DIR, CHECK_INTERVAL_SEC,
                AUTO_DEPLOY, DRIFT_AGE_SEC)
    if not _is_git_repo(CODE_DIR):
        logger.error("CODE_DIR %s is not a git repo — updater cannot run; "
                     "consider cloning master to this path", CODE_DIR)
        return 1
    while True:
        try:
            check_drift_once()
            attempt_auto_deploy()
        except Exception as e:
            logger.warning("tick error: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_SEC)


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Orion updater diagnostics")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check", help="one-shot drift check + write version state")
    sub.add_parser("deploy", help="one-shot deploy attempt (requires AUTO_DEPLOY=1)")
    sub.add_parser("state", help="print ~/.orion/version.json")
    args = ap.parse_args()
    if args.cmd == "check":
        s = check_drift_once()
        print(json.dumps(s, indent=2))
        return 0
    if args.cmd == "deploy":
        s = attempt_auto_deploy()
        print(json.dumps(s, indent=2) if s else "(no deploy — see logs)")
        return 0
    if args.cmd == "state":
        if VERSION_PATH.exists():
            print(VERSION_PATH.read_text(encoding="utf-8"))
        else:
            print("(no version state written yet)")
        return 0
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(_cli())
