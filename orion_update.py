#!/usr/bin/env python3
"""orion update — pull the latest Orion from origin and re-wire.

Run via:
    orion update                    # if the orion launcher is on PATH
    python orion_update.py          # always works from the install dir

What it does:
    1. Verify this install is a git checkout (not a dumb file copy)
    2. Compare local HEAD to origin/master
    3. If behind: stash any local changes, fast-forward pull, re-apply stash
    4. If requirements.txt changed: pip install -r requirements.txt --quiet
    5. Re-run the MCP wiring so any new tools / config get registered
    6. Print a summary, exit 0 on success / 1 on failure

What it does NOT do:
    - Run the full setup wizard again (that would clobber your identity)
    - Touch your brain memory at ~/.orion (that's yours, not ours)
    - Force-push or rebase — fast-forward only, abort if you have diverged

How users get this:
    The first install dropped this file into the repo. After install,
    `orion update` is just running this script through the launcher.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
REQUIREMENTS = REPO_DIR / "requirements.txt"
STATE_DIR = Path.home() / ".orion"
LAST_REQ_HASH_FILE = STATE_DIR / "last-requirements-hash"


def _git(*args, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO_DIR,
        capture_output=capture, text=True,
    )


def _venv_python() -> Path | None:
    candidates = [
        REPO_DIR / ".venv" / "Scripts" / "python.exe",   # Windows
        REPO_DIR / ".venv" / "bin" / "python",           # POSIX
        REPO_DIR / ".venv" / "bin" / "python3",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _hash_requirements() -> str:
    if not REQUIREMENTS.exists():
        return ""
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _read_last_hash() -> str:
    try:
        return LAST_REQ_HASH_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def _write_last_hash(h: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_REQ_HASH_FILE.write_text(h, encoding="utf-8")
    except Exception:
        pass


def _is_git_checkout() -> bool:
    return (REPO_DIR / ".git").exists()


def _short(sha: str) -> str:
    return (sha or "")[:7] if sha else "?"


def main() -> int:
    print(f"orion update — {REPO_DIR}", flush=True)

    if not _is_git_checkout():
        print("  This install isn't a git checkout, so it can't auto-update.", flush=True)
        print("  Re-clone via the install one-liner and re-run setup:", flush=True)
        print("    git clone https://github.com/1Changetheworld/orion.git <path>", flush=True)
        return 1

    # ---- 1. Compare local to remote ----
    cur = _git("rev-parse", "HEAD").stdout.strip()
    fetch = _git("fetch", "origin", "master", capture=False)
    if fetch.returncode != 0:
        print("  git fetch failed — check your network or git config.", flush=True)
        return 1
    remote = _git("rev-parse", "origin/master").stdout.strip()

    if cur and cur == remote:
        print(f"  Already up to date ({_short(cur)}).", flush=True)
        # Still verify deps + MCP — they might have drifted from a partial
        # earlier install. Cheap insurance.
        _maybe_pip_sync()
        _rewire_mcp()
        return 0

    print(f"  current: {_short(cur)}", flush=True)
    print(f"  remote:  {_short(remote)}", flush=True)

    # ---- 2. Pull, fast-forward only ----
    # Stash any local changes (defensive — a user-edit shouldn't block update)
    stash = _git("stash", "push", "--include-untracked", "-m", f"orion-update-{int(time.time())}")
    stashed = "No local changes" not in stash.stdout

    pull = _git("pull", "--ff-only", "origin", "master", capture=False)
    if pull.returncode != 0:
        print("  Fast-forward pull failed — your branch may have diverged.", flush=True)
        print("  Resolve manually:", flush=True)
        print(f"    cd {REPO_DIR}", flush=True)
        print("    git status", flush=True)
        if stashed:
            print("  Your stashed changes are at:  git stash list", flush=True)
        return 1

    if stashed:
        # Re-apply user changes
        pop = _git("stash", "pop")
        if pop.returncode != 0:
            print("  Pulled cleanly, but your stashed local changes need manual merge:", flush=True)
            print("    git stash list / git stash apply", flush=True)

    new_cur = _git("rev-parse", "HEAD").stdout.strip()
    print(f"  Updated to {_short(new_cur)}.", flush=True)

    # ---- 3. Sync deps if requirements.txt changed ----
    _maybe_pip_sync()

    # ---- 4. Re-wire MCP so new tools surface in every CLI ----
    _rewire_mcp()

    print("", flush=True)
    print("Update complete. Restart any open AI CLIs to load the new wiring.", flush=True)
    return 0


def _maybe_pip_sync() -> None:
    """Run pip install -r requirements.txt only when the file's hash changed."""
    venv_py = _venv_python()
    if not venv_py or not REQUIREMENTS.exists():
        return
    cur_hash = _hash_requirements()
    if cur_hash == _read_last_hash():
        return  # No change since last sync
    print("  requirements.txt changed — syncing pip deps...", flush=True)
    rc = subprocess.run(
        [str(venv_py), "-m", "pip", "install", "-r", str(REQUIREMENTS), "--quiet"],
    ).returncode
    if rc == 0:
        _write_last_hash(cur_hash)
        print("  pip deps in sync.", flush=True)
    else:
        print(f"  pip sync failed (rc={rc}). Re-run: {venv_py} -m pip install -r {REQUIREMENTS}", flush=True)


def _rewire_mcp() -> None:
    """Re-run the MCP setup so any new tools land in each CLI's config."""
    venv_py = _venv_python()
    mcp_setup = REPO_DIR / "orion_mcp_server.py"
    if not venv_py or not mcp_setup.exists():
        return
    print("  re-wiring MCP into each detected CLI...", flush=True)
    subprocess.run([str(venv_py), str(mcp_setup), "--setup"])


if __name__ == "__main__":
    sys.exit(main())
