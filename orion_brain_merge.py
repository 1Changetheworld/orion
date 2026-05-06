"""Brain merge + absence detection.

Two related capabilities, one module (per docs/architecture/brain-merge-and-rejoin.md):

(a) Brain meets brain — when a host already has Orion AND a USB Orion is
    plugged in, the wizard offers merge / keep-separate / replace.
(b) Wake from absence — when Orion comes online after time without him,
    surface the gap so the model can ask rather than pretend continuity.

Both questions surfaced 2026-05-03 during the cross-machine portability
test on the Pi. They were design-only until 2026-05-06 when this module
landed.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import orion_brain_portable as obp


# ─────────────────────────────────────────────────────────
# Merge — pull source's nodes into target
# ─────────────────────────────────────────────────────────


@dataclass
class MergeResult:
    """Outcome of merging one brain into another."""
    added: int = 0
    skipped_exact_duplicates: int = 0
    contested: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"added: {self.added}", f"duplicates skipped: {self.skipped_exact_duplicates}"]
        if self.contested:
            parts.append(f"contested: {self.contested}")
        if self.errors:
            parts.append(f"errors: {len(self.errors)}")
        return ", ".join(parts)


def merge_graphs(source: obp.GraphMemory, target: obp.GraphMemory) -> MergeResult:
    """Merge `source` graph INTO `target` graph. Mutates target.

    Strategy:
    - Exact content match in target → skip (don't double-store).
    - Otherwise → store in target with contradiction check ON. The
      existing contradiction layer (orion_brain_portable.GraphMemory's
      _find_contradictions + _apply_contradiction_policy) flags any
      conflicts as contested, so user resolves later via
      orion_resolve_contradiction. No silent overwrites.

    Caller is responsible for saving the target graph to disk.
    """
    result = MergeResult()
    if not source.nodes:
        return result

    # Pre-compute the set of exact content strings already in target
    # for fast duplicate skip. Tags + type aren't part of the
    # uniqueness check — same content with different tags is still a
    # duplicate from the user's perspective.
    target_contents = {
        n["content"].strip(): nid
        for nid, n in target.nodes.items()
        if isinstance(n.get("content"), str)
    }

    for src_node in source.nodes.values():
        content = src_node.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        if content.strip() in target_contents:
            result.skipped_exact_duplicates += 1
            continue
        try:
            new_id = target.store(
                content=content,
                node_type=src_node.get("type", "fact"),
                confidence=src_node.get("confidence", 1.0),
                tags=list(src_node.get("tags") or []),
                skip_contradiction_check=False,
            )
            # store() may have flagged the new node as contested via the
            # contradiction policy. Detect by inspecting the new node.
            new = target.nodes.get(new_id)
            if new and new.get("contested_with"):
                result.contested += 1
            else:
                result.added += 1
        except Exception as e:
            result.errors.append(f"{e.__class__.__name__}: {e}")

    return result


def archive_brain_dir(brain_dir: Path, label: str = "merge") -> Path:
    """Move a brain dir to a timestamped backup. Returns the new path.

    No data is destroyed — even if the user picks "replace," the prior
    state is recoverable from the archive. The cellular framing: this is
    apoptosis with a fossil record, not destructive lysis.
    """
    if not brain_dir.exists():
        return brain_dir
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = brain_dir.with_name(f"{brain_dir.name}-backup-{label}-{stamp}")
    shutil.move(str(brain_dir), str(archive))
    return archive


def merge_brain_dirs(source_dir: Path, target_dir: Path) -> MergeResult:
    """Higher-level helper: load both graphs, merge source into target,
    save target. Returns MergeResult.

    Both directories must contain a brain/graph_memory.json. If the
    source has no graph file, this is a no-op (returns empty result).
    """
    src_graph_path = source_dir / "brain" / "graph_memory.json"
    tgt_graph_path = target_dir / "brain" / "graph_memory.json"

    src = obp.GraphMemory()
    if src_graph_path.exists():
        src.load(src_graph_path)

    tgt = obp.GraphMemory()
    if tgt_graph_path.exists():
        tgt.load(tgt_graph_path)

    result = merge_graphs(src, tgt)
    tgt_graph_path.parent.mkdir(parents=True, exist_ok=True)
    tgt.save(tgt_graph_path)
    return result


# ─────────────────────────────────────────────────────────
# Absence detection — Orion wakes from time away
# ─────────────────────────────────────────────────────────


def last_write_timestamp(graph: obp.GraphMemory) -> Optional[float]:
    """Return the most recent created/last_confirmed_at timestamp in the
    graph. None if the graph has no nodes.

    Uses the maximum of created and last_confirmed_at since either
    indicates Orion was active. A node's last_confirmed_at advances on
    re-confirmation, which is itself a form of write.
    """
    if not graph.nodes:
        return None
    latest = 0.0
    for n in graph.nodes.values():
        for field_name in ("last_confirmed_at", "created"):
            ts = n.get(field_name)
            if isinstance(ts, (int, float)) and ts > latest:
                latest = float(ts)
    return latest if latest > 0 else None


# Absence detection threshold. Anything under this is treated as
# normal cadence — no need to surface "you've been gone." Anything
# above gets a "welcome back" message. Tuned so a user closing
# their laptop overnight (8h) doesn't trigger, but a multi-day
# absence (the actual signal) does.
ABSENCE_THRESHOLD_SECONDS = 24 * 3600


def absence_gap_seconds(graph: obp.GraphMemory, now: Optional[float] = None) -> Optional[float]:
    """Return seconds since the last brain write, or None if no nodes."""
    last = last_write_timestamp(graph)
    if last is None:
        return None
    now = now if now is not None else time.time()
    return max(0.0, now - last)


def format_absence_message(gap_seconds: Optional[float],
                           user_name: str = "") -> Optional[str]:
    """If the gap is meaningful, return a one-line proactive message
    Orion can surface at session start. Else None.

    The message is intentionally minimal and asks rather than asserts —
    per feedback_orion-must-be-alive.md, Orion should not pretend
    continuity that doesn't exist.
    """
    if gap_seconds is None or gap_seconds < ABSENCE_THRESHOLD_SECONDS:
        return None

    days = gap_seconds / 86400
    addressee = f", {user_name}" if user_name else ""

    if days >= 28:
        when = f"{int(days // 30)} month(s)"
    elif days >= 7:
        when = f"{int(days // 7)} week(s)"
    elif days >= 1:
        when = f"{int(days)} day(s)"
    else:
        # Shouldn't happen with our threshold but be defensive
        hours = gap_seconds / 3600
        when = f"{int(hours)} hour(s)"

    return (
        f"Welcome back{addressee}. The last fact I wrote was {when} ago. "
        f"What's been happening? I want to fill in the gap rather than "
        f"pretend I was there."
    )


def memorize_absence(graph: obp.GraphMemory, gap_seconds: float,
                     user_summary_of_gap: str = "") -> int:
    """Record the absence itself as a brain node. Returns the new node id.

    The user's summary of what happened during the gap is optional. Even
    without it, recording "Orion was away from this host for X" is a
    meaningful event Orion's other models should be able to recall.
    """
    days = max(1, int(gap_seconds // 86400))
    when_phrase = f"{days} day(s)" if days < 7 else f"{days // 7} week(s)"
    content = (
        f"Orion was away from this host for {when_phrase}. "
        f"Returned at {time.strftime('%Y-%m-%d %H:%M')}."
    )
    if user_summary_of_gap:
        content += f" During the gap: {user_summary_of_gap.strip()}"
    return graph.store(
        content=content,
        node_type="event",
        tags=["absence", "re-entry", "orion-state"],
        skip_contradiction_check=True,
    )
