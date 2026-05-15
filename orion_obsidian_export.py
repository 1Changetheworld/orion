#!/usr/bin/env python3
"""orion_obsidian_export — render the brain as an Obsidian vault.

Founder pivot 2026-05-14: stop competing with Obsidian's graph view.
Export Orion's brain as a real Obsidian vault — one markdown file per
memory node with proper frontmatter + [[wiki-links]] for tag relations
+ separate folders for devices, channels, services. The user opens
the vault in Obsidian and gets the elite visualization for free:
zoom, pan, filter by tag, fold groups, beautiful rendering, all the
plugins they already know.

Why this is the right move:
  - Obsidian is polished, cross-platform, free
  - Their graph view already does what we'd spend months matching
  - Users can edit memories in Obsidian and re-import later
  - The vault is a portable artifact — copy it anywhere, view it
    in Obsidian on any OS

What this writes:
  vault/
    README.md                — vault overview
    Identity/                — the canonical SOUL of Orion
      Orion.md               — pulled from SOUL.md
    Memories/                — every graph_memory node
      mem-0.md, mem-1.md, …  — one per node, frontmatter + body + links
    Devices/                 — known mesh hosts
      COMMAND.md, FORGE.md, ORIONS HOME.md
    Channels/                — communication points
      iMessage.md, Voice.md, Telegram.md, CLI.md, Webhook.md, LoRa.md
    Services/                — Plexus services on this host
      claustrum.md, gossip.md, …

Run:
  python orion_obsidian_export.py             # default: ./orion-vault/
  python orion_obsidian_export.py --out PATH  # custom destination
  python orion_obsidian_export.py --open      # open in Obsidian (URI scheme)

Then in Obsidian:  Open vault -> pick the orion-vault directory.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
import webbrowser
from collections import defaultdict
from pathlib import Path

ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR")
                  or str(Path.home() / ".orion"))
GRAPH_PATH = ORION_HOME / "brain" / "graph_memory.json"
SOUL_PATH = ORION_HOME / "identity" / "SOUL.md"
VITALS_DIR = ORION_HOME / "vitals"
MCP_LOG_PATH = ORION_HOME / "mcp_calls.log"
DECISIONS_PATH = ORION_HOME / "executive" / "decisions.jsonl"

# Identical to dashboard_server's KNOWN_* so the exported vault matches
# the nervous system the visualizer renders.
KNOWN_DEVICES = [
    {"id": "command",     "label": "COMMAND",      "role": "canonical brain",       "ip": "10.0.0.190"},
    {"id": "forge",       "label": "FORGE",        "role": "mobile + dev",          "ip": "10.0.0.88"},
    {"id": "orions-home", "label": "ORIONS HOME",  "role": "offline twin + maps",   "ip": "10.0.0.56"},
    {"id": "outpost",     "label": "OUTPOST",      "role": "tailscale-only node",   "ip": "100.112.80.14"},
]
KNOWN_CHANNELS = [
    {"id": "imessage", "label": "iMessage",  "host": "command", "transport": "native macOS"},
    {"id": "voice",    "label": "Voice",     "host": "command", "transport": "Telnyx + STT/TTS"},
    {"id": "telegram", "label": "Telegram",  "host": "command", "transport": "@HomelandServbot"},
    {"id": "cli",      "label": "CLI",       "host": "any",     "transport": "MCP over stdio"},
    {"id": "webhook",  "label": "Webhook",   "host": "command", "transport": "HTTP :5555"},
    {"id": "lora",     "label": "LoRa",      "host": "orions-home", "transport": "Meshtastic v3"},
]


def _ssh_pull(host_alias: str, command: str, timeout: int = 6) -> str:
    """Run a small shell command on a remote host via ssh alias.
    Best-effort: returns "" on any error so the vault always renders.
    """
    import subprocess
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes",
             "-o", f"ConnectTimeout={timeout}",
             host_alias, command],
            capture_output=True, text=True, timeout=timeout + 2)
        return (r.stdout or "") if r.returncode == 0 else ""
    except Exception:
        return ""


def _pull_remote_host(dev: dict) -> dict:
    """Pull live state from a known device via ssh."""
    alias_map = {
        "command":     "command",
        "orions-home": "pi",
        "forge":       None,
    }
    alias = alias_map.get(dev["id"])
    info = {"services": [], "activity_lines": []}
    if alias is None:
        return info
    if dev["id"] == "command":
        out = _ssh_pull(alias, "launchctl list 2>/dev/null | awk '/com\\.orion\\./{print $3}' | sort")
    else:
        # systemctl --user over ssh needs XDG_RUNTIME_DIR set explicitly.
        out = _ssh_pull(alias,
            "XDG_RUNTIME_DIR=/run/user/$(id -u) "
            "systemctl --user list-units 'orion-*' --no-pager --no-legend 2>/dev/null "
            "| awk '/orion-/{for(i=1;i<=NF;i++) if($i ~ /^orion-/) print $i}'")
    info["services"] = [s.strip() for s in out.splitlines()
                        if s.strip() and s.strip() != "●"]
    log = _ssh_pull(alias, "tail -20 ~/.orion/mcp_calls.log 2>/dev/null")
    info["activity_lines"] = [l for l in log.splitlines() if l.strip()][:20]
    return info


def _safe_filename(name: str) -> str:
    """Trim a string into something Obsidian likes as a filename."""
    s = re.sub(r"[\\/:*?\"<>|]", "-", str(name))
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:80] or "node"


def _frontmatter(d: dict) -> str:
    """Render a dict as YAML frontmatter."""
    lines = ["---"]
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        elif isinstance(v, (int, float, bool)) or v is None:
            lines.append(f"{k}: {v}")
        else:
            sv = str(v).replace('"', '\\"')
            lines.append(f'{k}: "{sv}"')
    lines.append("---\n")
    return "\n".join(lines)


def _load_recent_activity(limit: int = 200) -> list:
    """Pull recent brain activity. Sources (any host): mcp_calls.log
    (recall / memorize / identity calls) and executive/decisions.jsonl
    (autonomous deliberations). Each event carries when, what, and
    enough context to wiki-link from the timeline back into the graph.
    """
    events = []
    if MCP_LOG_PATH.exists():
        try:
            with open(MCP_LOG_PATH, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    m = re.match(r"^\[([^\]]+)\] (\S+)\s+(.+)$", line)
                    if not m:
                        continue
                    ts, kind, rest = m.groups()
                    # Extract tool name from "tools/call orion_recall args=..."
                    tool = None
                    tm = re.match(r"tools/call (\w+)", rest)
                    if tm:
                        tool = tm.group(1)
                    # Extract query/content snippet for context
                    snippet = ""
                    sm = re.search(r'"(?:query|content|fact)":\s*"([^"]{1,140})', rest)
                    if sm:
                        snippet = sm.group(1)
                    events.append({
                        "ts": ts, "source": "mcp", "kind": kind,
                        "tool": tool or kind, "snippet": snippet,
                    })
        except Exception:
            pass
    if DECISIONS_PATH.exists():
        try:
            with open(DECISIONS_PATH, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    events.append({
                        "ts": d.get("ts") or d.get("timestamp") or "",
                        "source": "executive",
                        "kind": d.get("symptom_class") or "decision",
                        "tool": d.get("service") or "executive",
                        "snippet": str(d.get("proposal") or d.get("outcome") or "")[:140],
                    })
        except Exception:
            pass
    # newest first; cap
    events.sort(key=lambda e: e["ts"], reverse=True)
    return events[:limit]


def _deploy_obsidian_preset(out_dir: Path) -> bool:
    """Copy the curated .obsidian/ config into the vault if none exists.
    This is what makes every user's first vault open look like Orion's —
    color-coded graph nodes, dark theme, graph view open by default,
    sensible workspace layout.

    Idempotent: if user already configured .obsidian/, we don't overwrite.
    """
    preset_root = Path(__file__).resolve().parent / "vault-presets" / "dot-obsidian"
    if not preset_root.exists():
        return False
    target = out_dir / ".obsidian"
    if target.exists():
        return False  # respect existing user config
    target.mkdir()
    for src in preset_root.iterdir():
        if src.is_file():
            shutil.copy2(src, target / src.name)
    return True


def export_vault(out_dir: Path) -> dict:
    """Build the vault. Returns summary stats."""
    out_dir = out_dir.resolve()
    # Preserve any existing .obsidian/ config across re-exports.
    existing_obsidian = out_dir / ".obsidian"
    saved_obsidian = None
    if existing_obsidian.exists():
        saved_obsidian = out_dir.parent / f".obsidian-cache-{os.getpid()}"
        if saved_obsidian.exists():
            shutil.rmtree(saved_obsidian)
        shutil.move(str(existing_obsidian), str(saved_obsidian))
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    if saved_obsidian:
        shutil.move(str(saved_obsidian), str(out_dir / ".obsidian"))

    # Deploy default preset if no user config present
    preset_applied = _deploy_obsidian_preset(out_dir)

    stats = {"memories": 0, "devices": 0, "channels": 0, "services": 0,
             "wiki_links": 0, "activity_days": 0, "activity_events": 0,
             "preset_applied": preset_applied}
    activity = _load_recent_activity(limit=500)
    # Group by date for daily activity files + per-channel/per-tool indexes.
    by_date = defaultdict(list)
    by_tool = defaultdict(list)
    for ev in activity:
        # Normalize date prefix YYYY-MM-DD
        date_key = (ev["ts"] or "")[:10] or "unknown"
        by_date[date_key].append(ev)
        by_tool[ev.get("tool", "?")].append(ev)

    # README ───────────────────────────────────────
    (out_dir / "README.md").write_text(
        "# Orion · Vault\n\n"
        "This vault is a snapshot of Orion's brain rendered as Obsidian-readable "
        "markdown. Each memory, device, communication point, and Plexus service "
        "is a note. Tags become Obsidian tags. Relationships become wiki-links.\n\n"
        "Open Obsidian, choose 'Open folder as vault', and pick this directory. "
        "Then `Cmd/Ctrl + G` opens the graph view — the elite visualization of "
        "Orion's nervous system you came here for.\n\n"
        "Folders:\n"
        "- `Identity/` — who Orion is\n"
        "- `Memories/` — every fact, preference, project, decision Orion holds\n"
        "- `Devices/` — the hosts in the mesh (COMMAND / FORGE / ORIONS HOME)\n"
        "- `Channels/` — communication points (iMessage / Voice / Telegram / LoRa / ...)\n"
        "- `Services/` — Plexus services running on this host (if any)\n"
        "- `Activity/` — timeline of recent brain activity (recalls / memorizes / decisions)\n",
        encoding="utf-8",
    )

    # IDENTITY ─────────────────────────────────────
    ident_dir = out_dir / "Identity"
    ident_dir.mkdir()
    soul_text = SOUL_PATH.read_text(encoding="utf-8") if SOUL_PATH.exists() \
        else "(SOUL.md not present on this host)"
    (ident_dir / "Orion.md").write_text(
        _frontmatter({"kind": "identity", "tags": ["identity", "orion"]}) +
        soul_text, encoding="utf-8")

    # DEVICES ──────────────────────────────────────
    dev_dir = out_dir / "Devices"
    dev_dir.mkdir()
    for d in KNOWN_DEVICES:
        remote = _pull_remote_host(d)
        # services live: from remote pull, or locally if this IS the host
        services = remote["services"]
        if not services and d["id"] in platform.node().lower():
            # We're running on this host — read local vitals dir
            if VITALS_DIR.exists():
                services = sorted(f.stem for f in VITALS_DIR.glob("*.json"))
        activity_lines = remote["activity_lines"]
        body = (
            f"# {d['label']}\n\n"
            f"- **role:** {d['role']}\n"
            f"- **IP:** {d['ip']}\n"
            f"- **services running:** {len(services)}\n\n"
            f"## Channels hosted here\n"
            + ("".join(f"- [[{ch['label']}]]\n" for ch in KNOWN_CHANNELS
                       if ch['host'] == d['id']) or "_(none)_\n")
        )
        if services:
            body += (
                f"\n## Plexus services on this host ({len(services)})\n"
                + "".join(f"- `{s}`\n" for s in services[:30])
            )
        body += (
            f"\n## Mesh peers\n"
            + "".join(f"- [[{o['label']}]]\n" for o in KNOWN_DEVICES if o['id'] != d['id'])
        )
        if activity_lines:
            body += "\n## Recent brain activity (this host)\n```\n"
            for line in activity_lines[-10:]:
                body += line[:120] + "\n"
            body += "```\n"
        (dev_dir / f"{_safe_filename(d['label'])}.md").write_text(
            _frontmatter({
                "kind": "device", "id": d["id"], "role": d["role"],
                "ip": d["ip"],
                "service_count": len(services),
                "tags": ["device", d["id"]]
            }) + body,
            encoding="utf-8")
        stats["devices"] += 1

    # ACTIVITY (timeline) ──────────────────────────
    act_dir = out_dir / "Activity"
    act_dir.mkdir()
    for date_key, evs in sorted(by_date.items(), reverse=True):
        if date_key == "unknown":
            continue
        lines = [f"# Activity — {date_key}", ""]
        for ev in evs:
            tool = ev.get("tool", "?")
            snippet = ev.get("snippet", "").strip()
            ts = ev.get("ts", "")
            tool_link = f"[[{tool}]]"
            line = f"- `{ts[11:19] if len(ts) >= 19 else ts}` · {tool_link}"
            if snippet:
                line += f" — {snippet[:100]}"
            lines.append(line)
        (act_dir / f"{date_key}.md").write_text(
            _frontmatter({"kind": "activity", "date": date_key,
                          "event_count": len(evs),
                          "tags": ["activity", date_key]}) + "\n".join(lines),
            encoding="utf-8")
        stats["activity_days"] += 1
        stats["activity_events"] += len(evs)

    # Per-tool index — Memories/recalls.md, Memories/memorizes.md, etc.
    # Each lets Obsidian show "what tool fired most often"
    for tool, evs in by_tool.items():
        if not tool or tool == "?":
            continue
        fname = _safe_filename(tool) + ".md"
        body_lines = [
            f"# {tool}", "",
            f"_{len(evs)} invocation{'s' if len(evs) != 1 else ''} recorded._",
            "",
            "## Recent uses",
        ]
        for ev in evs[:30]:
            ts = ev.get("ts", "")[:19]
            snip = ev.get("snippet", "")[:80]
            body_lines.append(f"- `{ts}` — {snip}" if snip else f"- `{ts}`")
        (act_dir / fname).write_text(
            _frontmatter({"kind": "tool", "name": tool,
                          "tags": ["tool", tool]}) + "\n".join(body_lines),
            encoding="utf-8")

    # CHANNELS ─────────────────────────────────────
    chan_dir = out_dir / "Channels"
    chan_dir.mkdir()
    label_for_dev = {d["id"]: d["label"] for d in KNOWN_DEVICES}
    for ch in KNOWN_CHANNELS:
        host_label = label_for_dev.get(ch["host"], "(any host)")
        host_link = f"[[{host_label}]]" if ch["host"] != "any" else "any host"
        body = (
            f"# {ch['label']}\n\n"
            f"- **transport:** {ch['transport']}\n"
            f"- **hosted on:** {host_link}\n\n"
            f"This is a communication point — a way to reach Orion. The brain "
            f"is the same regardless of which channel you arrive through.\n"
        )
        (chan_dir / f"{_safe_filename(ch['label'])}.md").write_text(
            _frontmatter({"kind": "channel", "id": ch["id"],
                          "host": ch["host"], "transport": ch["transport"],
                          "tags": ["channel", ch["id"]]}) + body,
            encoding="utf-8")
        stats["channels"] += 1

    # SERVICES (from local vitals dir, if any) ─────
    svc_dir = out_dir / "Services"
    svc_dir.mkdir()
    if VITALS_DIR.exists():
        for f in sorted(VITALS_DIR.glob("*.json")):
            svc = f.stem
            try:
                snap = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                snap = {}
            body = (
                f"# {svc}\n\n"
                f"- **uptime (s):** {snap.get('uptime_sec', '?')}\n"
                f"- **last event age (s):** {snap.get('last_event_age_sec', '?')}\n"
                f"- **error rate / min:** {snap.get('error_rate_per_min', 0)}\n\n"
                "Plexus service running on this host. Part of the nervous "
                "system Orion uses to perceive and act.\n"
            )
            (svc_dir / f"{_safe_filename(svc)}.md").write_text(
                _frontmatter({"kind": "service", "id": svc,
                              "tags": ["service", svc]}) + body,
                encoding="utf-8")
            stats["services"] += 1

    # MEMORIES ─────────────────────────────────────
    mem_dir = out_dir / "Memories"
    mem_dir.mkdir()
    if GRAPH_PATH.exists():
        try:
            raw = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] could not read graph_memory: {e}", file=sys.stderr)
            raw = {"nodes": {}}

        # Build tag -> node-ids index so we can wiki-link siblings
        tag_to_ids = defaultdict(list)
        for nid_str, node in raw.get("nodes", {}).items():
            try:
                nid = int(nid_str)
            except Exception:
                continue
            for t in node.get("tags", []) or []:
                tag_to_ids[(t or "").strip().lower()].append(nid)

        for nid_str, node in raw.get("nodes", {}).items():
            try:
                nid = int(nid_str)
            except Exception:
                continue
            content = node.get("content", "")
            content = content if isinstance(content, str) else str(content)
            tags = list(node.get("tags", []) or [])
            mtype = node.get("type", "fact")

            # Wiki-links to siblings sharing any non-stopword tag
            STOPWORDS = {"fact", "preference", "project", "identity", "task",
                         "ephemeral", "person", "skill", "tool"}
            related = set()
            for t in tags:
                tlow = (t or "").strip().lower()
                if not tlow or tlow in STOPWORDS:
                    continue
                for sib in tag_to_ids.get(tlow, []):
                    if sib != nid:
                        related.add(sib)
            # Build a slug index so wiki-links resolve to renamed files
            related_sorted = sorted(related)[:12]
            related_links = "".join(f"- [[mem-{r}]]\n" for r in related_sorted)
            stats["wiki_links"] += min(len(related), 12)

            # Readable filename: mem-<id>-<slug>.md — what Obsidian shows
            # in the graph by default. Slug is the first meaningful chunk
            # of content so the graph reads naturally instead of "mem-37".
            title_seed = content.split(":")[0].split("\n")[0].strip()[:50] or f"memory {nid}"
            slug = re.sub(r"[^\w\s-]", "", title_seed).strip()
            slug = re.sub(r"\s+", "-", slug)[:40].lower() or f"node-{nid}"
            fname = f"mem-{nid}-{slug}.md"

            fm = _frontmatter({
                "kind": "memory",
                "id": nid,
                "type": mtype,
                "aliases": [title_seed, f"mem-{nid}"],
                "tags": [mtype] + tags[:8],
                "confidence": node.get("confidence", 1.0),
                "created": node.get("created", 0),
            })
            body = (
                f"# {title_seed}\n\n"
                f"> Memory node #{nid} · type: `{mtype}`\n\n"
                f"{content}\n"
            )
            if related_links:
                body += f"\n## Related\n{related_links}"
            (mem_dir / fname).write_text(fm + body, encoding="utf-8")
            stats["memories"] += 1

    return stats


def _watch(out: Path, interval: float = 5.0) -> int:
    """Re-export whenever graph_memory.json or SOUL.md mtime changes.

    Cheap parallel-with-functions wiring: poll source files, re-render
    on change. Future: subscribe to brain.memory.stored on the substrate
    and re-render event-driven. For now polling keeps the path simple.
    """
    import time
    last_seen = {}
    print(f"[orion-obsidian-watch] watching {GRAPH_PATH} and {SOUL_PATH} every {interval}s")
    print(f"[orion-obsidian-watch] re-exporting to {out.resolve()} on change")
    print("[orion-obsidian-watch] Ctrl-C to stop.")
    while True:
        changed = False
        for p in (GRAPH_PATH, SOUL_PATH):
            try:
                m = p.stat().st_mtime if p.exists() else 0
            except OSError:
                m = 0
            if last_seen.get(p) != m:
                last_seen[p] = m
                changed = True
        if changed:
            try:
                stats = export_vault(out)
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] re-exported: "
                      f"{stats['memories']} memories, "
                      f"{stats['wiki_links']} links")
            except Exception as e:
                print(f"[orion-obsidian-watch] export error: {e}")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[orion-obsidian-watch] stopped")
            return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Export Orion's brain as an Obsidian vault.")
    ap.add_argument("--out", default="./orion-vault",
                    help="output vault directory (default: ./orion-vault)")
    ap.add_argument("--open", action="store_true",
                    help="open the vault in Obsidian after export (uses obsidian:// URI)")
    ap.add_argument("--watch", action="store_true",
                    help="watch graph_memory + SOUL and re-export on change")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="watch poll interval seconds (default: 5)")
    args = ap.parse_args(argv[1:])

    out = Path(args.out)
    print(f"[orion-obsidian] exporting brain to {out.resolve()}")
    stats = export_vault(out)
    print("[orion-obsidian] done:")
    for k, v in stats.items():
        print(f"  {k:>12}: {v}")
    print(f"\nNext: open Obsidian -> 'Open folder as vault' -> {out.resolve()}")
    print("Then Cmd/Ctrl+G for graph view.")

    if args.open:
        # Obsidian URI: obsidian://open?path=<absolute path>
        uri = "obsidian://open?path=" + str(out.resolve()).replace(" ", "%20")
        print(f"\nopening: {uri}")
        webbrowser.open(uri)

    if args.watch:
        return _watch(out, args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
