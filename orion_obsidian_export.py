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

# Identical to dashboard_server's KNOWN_* so the exported vault matches
# the nervous system the visualizer renders.
KNOWN_DEVICES = [
    {"id": "command",     "label": "COMMAND",      "role": "canonical brain",  "ip": "10.0.0.190"},
    {"id": "forge",       "label": "FORGE",        "role": "mobile + dev",     "ip": "10.0.0.88"},
    {"id": "orions-home", "label": "ORIONS HOME",  "role": "offline twin",     "ip": "10.0.0.56"},
]
KNOWN_CHANNELS = [
    {"id": "imessage", "label": "iMessage",  "host": "command", "transport": "native macOS"},
    {"id": "voice",    "label": "Voice",     "host": "command", "transport": "Telnyx + STT/TTS"},
    {"id": "telegram", "label": "Telegram",  "host": "command", "transport": "@HomelandServbot"},
    {"id": "cli",      "label": "CLI",       "host": "any",     "transport": "MCP over stdio"},
    {"id": "webhook",  "label": "Webhook",   "host": "command", "transport": "HTTP :5555"},
    {"id": "lora",     "label": "LoRa",      "host": "orions-home", "transport": "Meshtastic v3"},
]


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


def export_vault(out_dir: Path) -> dict:
    """Build the vault. Returns summary stats."""
    out_dir = out_dir.resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    stats = {"memories": 0, "devices": 0, "channels": 0, "services": 0, "wiki_links": 0}

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
        "- `Channels/` — communication points (iMessage / Voice / Telegram / LoRa / …)\n"
        "- `Services/` — Plexus services running on this host (if any)\n",
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
        body = (
            f"# {d['label']}\n\n"
            f"- **role:** {d['role']}\n"
            f"- **IP:** {d['ip']}\n\n"
            f"## Channels hosted here\n"
            + "".join(f"- [[{ch['label']}]]\n" for ch in KNOWN_CHANNELS
                     if ch['host'] == d['id']) +
            f"\n## Mesh peers\n"
            + "".join(f"- [[{o['label']}]]\n" for o in KNOWN_DEVICES if o['id'] != d['id'])
        )
        (dev_dir / f"{_safe_filename(d['label'])}.md").write_text(
            _frontmatter({"kind": "device", "id": d["id"], "role": d["role"],
                          "ip": d["ip"], "tags": ["device", d["id"]]}) + body,
            encoding="utf-8")
        stats["devices"] += 1

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
            related_links = "".join(f"- [[mem-{r}]]\n" for r in sorted(related)[:12])
            stats["wiki_links"] += min(len(related), 12)

            title_seed = content.split(":")[0].strip()[:60] or f"memory {nid}"
            fname = f"mem-{nid}.md"

            fm = _frontmatter({
                "kind": "memory",
                "id": nid,
                "type": mtype,
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


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Export Orion's brain as an Obsidian vault.")
    ap.add_argument("--out", default="./orion-vault",
                    help="output vault directory (default: ./orion-vault)")
    ap.add_argument("--open", action="store_true",
                    help="open the vault in Obsidian after export (uses obsidian:// URI)")
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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
