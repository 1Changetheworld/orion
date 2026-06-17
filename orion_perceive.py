#!/usr/bin/env python3
"""
orion_perceive.py — PERCEPTION (Build 3, gap J). Orion's first senses.

WHY NOW: the temporal verifier (Build 3) can only confirm/refute reasoning against
CAUSALLY-INDEPENDENT evidence, and the graph received ~0 such evidence in 48h — Orion is a
disembodied text-mind. Perception writes that evidence: Orion perceiving its OWN BODY and
ENVIRONMENT (service health, host vitals, channels, fuel, brain size).

DISCERNING by construction (James's standing instruction — "a discerning self, not a hollow
absorber"): observations are stored PROVENANCE-TAGGED + UNVERIFIED (type=observation,
source=perception, low confidence) — perceived, never believed; never action-triggering.
CHANGE-DRIVEN + salience-gated (only meaningful deltas are written) — no firehose.
GPU-free, no API keys, pure stdlib + launchctl/df.

NOT yet a KeepAlive daemon — the autonomous flip is James's explicit call (like the Loom).
CLI: --once (perceive + write salient changes) · --show (current snapshot) · --dry (no writes).
"""
from __future__ import annotations
import json, os, re, time, subprocess, sys
from pathlib import Path
import urllib.request

STATE = Path(os.path.expanduser("~/.orion/state"))
PSTATE = STATE / "perception_state.json"          # last snapshot (for delta detection)
PLOG = STATE / "perception.jsonl"                 # append-only perception trace
BRAIN_URL = os.environ.get("ORION_BRAIN_URL", "http://127.0.0.1:5556")
TOKEN_FILE = Path(os.path.expanduser("~/.orion/auth-token"))

# the body Orion can feel: cognitively-relevant services
SERVICES = ["com.orion.brain-service", "com.orion.reason", "com.orion.wonder",
            "com.orion.neuromod", "com.orion.sleep", "com.orion.imessage",
            "com.orion.imessage-outbound", "com.orion.claustrum"]


def _token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _memorize(content: str, tags) -> bool:
    """Write one provenance-tagged, UNVERIFIED observation into the graph."""
    tok = _token()
    if not tok:
        return False
    body = json.dumps({"name": "orion_memorize", "arguments": {
        "content": content, "type": "observation",
        "tags": list(tags) + ["perception", "unverified"]}}).encode("utf-8")
    req = urllib.request.Request(f"{BRAIN_URL}/v1/call", data=body,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception:
        return False


def _sh(cmd: list) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return ""


def _svc(label: str) -> dict:
    out = _sh(["launchctl", "print", f"gui/{os.getuid()}/{label}"])
    runs = re.search(r"\bruns\s*=\s*(\d+)", out)
    return {"running": bool(re.search(r"state\s*=\s*running", out)),
            "runs": int(runs.group(1)) if runs else -1}


def snapshot() -> dict:
    snap = {"ts": time.time(), "services": {}, "vitals": {}, "brain": {}}
    for s in SERVICES:
        snap["services"][s] = _svc(s)
    # host vitals (cheap)
    try:
        snap["vitals"]["load1"] = round(os.getloadavg()[0], 2)
    except Exception:
        pass
    dfo = _sh(["df", "-k", "/"]).splitlines()
    if len(dfo) >= 2:
        f = dfo[-1].split()
        try:
            used, avail = int(f[2]), int(f[3])
            snap["vitals"]["disk_free_pct"] = round(100 * avail / (used + avail), 1)
        except Exception:
            pass
    # brain size
    try:
        gm = json.load(open(os.path.expanduser("~/.orion/brain/graph_memory.json")))
        snap["brain"]["nodes"] = len(gm.get("nodes", []))
    except Exception:
        pass
    return snap


def _load_last() -> dict:
    try:
        return json.loads(PSTATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _salient_changes(prev: dict, cur: dict) -> list:
    """Only MEANINGFUL deltas become observations — perception is gated, not a flood."""
    obs = []
    ps, cs = prev.get("services", {}), cur.get("services", {})
    for s, st in cs.items():
        old = ps.get(s, {})
        if old.get("running") is True and st["running"] is False:
            obs.append((f"My '{s.split('.')[-1]}' faculty has gone DOWN (was running).", ["body", "service", "alert"]))
        elif not old and st["running"] is False:
            obs.append((f"My '{s.split('.')[-1]}' faculty is not running.", ["body", "service"]))
        if old.get("runs", -1) >= 0 and st["runs"] - old.get("runs", st["runs"]) >= 2:
            obs.append((f"My '{s.split('.')[-1]}' faculty restarted {st['runs']-old['runs']}x "
                        f"(runs {old['runs']}→{st['runs']}) — possible instability.", ["body", "service", "restart"]))
    pv, cv = prev.get("vitals", {}), cur.get("vitals", {})
    if "disk_free_pct" in cv:
        if cv["disk_free_pct"] < 12:
            obs.append((f"Disk is nearly full — {cv['disk_free_pct']}% free.", ["body", "vitals", "alert"]))
        elif abs(cv["disk_free_pct"] - pv.get("disk_free_pct", cv["disk_free_pct"])) >= 5:
            obs.append((f"Disk free shifted to {cv['disk_free_pct']}%.", ["body", "vitals"]))
    if cv.get("load1", 0) >= 8 and cv.get("load1", 0) - pv.get("load1", cv.get("load1", 0)) >= 2:
        obs.append((f"System load is high ({cv['load1']}).", ["body", "vitals"]))
    pb, cb = prev.get("brain", {}), cur.get("brain", {})
    if "nodes" in cb and pb.get("nodes"):
        d = cb["nodes"] - pb["nodes"]
        if d >= 25:
            obs.append((f"My memory grew by {d} nodes (now {cb['nodes']}) since I last looked.", ["body", "brain"]))
    return obs


def perceive_once(write: bool = True) -> dict:
    cur = snapshot()
    prev = _load_last()
    changes = _salient_changes(prev, cur) if prev else [
        ("First perception: my body and environment came into view.", ["body", "onset"])]
    written = 0
    for content, tags in changes:
        rec = {"ts": cur["ts"], "content": content, "tags": tags}
        try:
            with PLOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass
        if write and _memorize(content, tags):
            written += 1
    if write:
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            PSTATE.write_text(json.dumps(cur), encoding="utf-8")
        except Exception:
            pass
    return {"changes": len(changes), "written": written,
            "observations": [c for c, _ in changes]}


def _main(argv):
    if "--show" in argv:
        print(json.dumps(snapshot(), indent=2))
        return 0
    dry = "--dry" in argv
    r = perceive_once(write=not dry)
    tail = " (dry)" if dry else (", wrote %d observation node(s)" % r["written"])
    print("perceived %d salient change(s)%s:" % (r["changes"], tail))
    for o in r["observations"]:
        print("  •", o)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
