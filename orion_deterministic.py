"""orion_deterministic.py — short-circuit LLM calls when the brain knows.

The founder's question 2026-05-16: "can orions intellegence speed up
llm response?" The answer is yes, and this is the first concrete
move. Memorized as project_orion-deterministic-answer-layer.md long
before today: "the brain answers from itself when it has the data."

WHY THIS LAYER EXISTS
=====================

Routine recall queries — "what's my name?", "what color does X
prefer?", "where do I keep my brain?" — already live in
graph_memory with high confidence. Round-tripping them through an
LLM is wasteful: 2-8 second latency, token cost, and the LLM
sometimes hallucinates around a fact the brain already had.

This layer sits BETWEEN inbound channel and LLM. Subscribes
channel.*.inbound, classifies whether the question is recall-shaped,
matches against graph_memory, and if confidence × match_score
crosses threshold, publishes the answer DIRECTLY on
channel.<x>.outbound — zero LLM call, ~50ms latency.

When the layer fires, it ALSO publishes brain.deterministic.hit so
metacog can score: did the user accept the direct answer or follow
up asking for more? Acceptance reinforces the threshold; pushback
demotes it.

When it does NOT fire (low confidence, non-recall question, etc),
the message proceeds to the existing LLM path unchanged. This layer
is additive — never destructive.

CLASSIFICATION
==============

A question is "recall-shaped" if it matches any of:

  - "what (is|are|was)? (my|your|the) X"
  - "what's (my|your|the) X"
  - "do you (know|remember) (my|your|when|where|how) X"
  - "tell me (my|about|what) X"
  - "who (is|was) X"
  - "where (is|do) X"
  - "when (is|was|did) X"
  - "remind me (of|about|what) X"

This is intentionally narrow. False positives are worse than false
negatives — sending a wrong direct answer is bad, missing a chance
to skip the LLM is just unrealized speedup.

MATCHING
========

Token Jaccard against node.content for nodes that share at least
one significant tag with extracted question terms. Top match by
(node.confidence × jaccard_similarity). Fire if combined > 0.65.

Honest caveat: this is bag-of-words, not semantic. Phase 2 should
plug into the existing vector recall layer (Qdrant) when available
for fuzzier match. Today's version handles the common case where
the question literally contains the key noun ("favorite color",
"phone number", "wifi password"). Good enough to ship.

WHAT NEVER GOES THROUGH HERE
============================

Anything that requires reasoning, multi-step inference, action
generation, creative writing, code generation, summarization. The
classifier rejects those by shape. The threshold rejects fuzzy
matches. Both gates have to fail-closed for safety.
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
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orion.deterministic")

NATS_URL = os.environ.get("ORION_NATS_URL", "nats://127.0.0.1:4222")
ORION_HOME = Path(os.environ.get("ORION_BRAIN_DIR") or str(Path.home() / ".orion"))
GRAPH_PATH = Path(os.environ.get("ORION_GRAPH_PATH")
                  or str(ORION_HOME / "brain" / "graph_memory.json"))
THRESHOLD = float(os.environ.get("ORION_DETERMINISTIC_THRESHOLD", "0.65"))
RELOAD_SEC = float(os.environ.get("ORION_DETERMINISTIC_RELOAD_SEC", "60"))
MIN_TOKEN_LEN = 3

# Recall-shape patterns. Narrow on purpose — false positives are worse
# than false negatives.
RECALL_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bwhat(?:'s| is| are| was)?\s+(?:my|your|the|a)\s+(\w+(?:\s+\w+){0,5})\??",
        r"\bdo\s+you\s+(?:know|remember)\s+(?:my|your|when|where|how|that|the|a|what|about)?\s*(\w+(?:\s+\w+){0,6})\??",
        r"\btell\s+me\s+(?:my|about|what|the|a)\s+(\w+(?:\s+\w+){0,6})\??",
        r"\bwho\s+(?:is|was)\s+(\w+(?:\s+\w+){0,3})\??",
        r"\bwhere\s+(?:is|do|did|are)\s+(\w+(?:\s+\w+){0,6})\??",
        r"\bwhen\s+(?:is|was|did|are)\s+(\w+(?:\s+\w+){0,6})\??",
        r"\bremind\s+me\s+(?:of|about|what)\s+(\w+(?:\s+\w+){0,6})\??",
        r"\bremember\s+(?:that|when|where|how|the|my|your|a)\s+(\w+(?:\s+\w+){0,6})\??",
    ]
]

# Words that don't carry recall signal — strip from match tokens.
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "for", "in", "on", "at", "by", "with", "and", "or", "but",
    "my", "your", "their", "our", "his", "her", "its",
    "what", "when", "where", "who", "how", "why", "which", "that", "this",
    "do", "does", "did", "have", "has", "had", "will", "would", "could", "should",
    "you", "i", "me", "we", "us", "them", "him", "she", "he", "they", "it",
    "tell", "know", "remember", "remind", "say", "said",
}


def _tokens(s: str) -> set[str]:
    """Significant tokens — lowercased, stopworded, min-length."""
    if not s:
        return set()
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", s.lower())
    return {t for t in raw if len(t) >= MIN_TOKEN_LEN and t not in STOPWORDS}


# ─────────────────────────────────────────────────────────
# Graph loader — hot-reload periodically so new memories surface
# ─────────────────────────────────────────────────────────

_graph_nodes: list[dict] = []
_graph_loaded_at: float = 0.0


def _load_graph() -> None:
    global _graph_nodes, _graph_loaded_at
    try:
        with GRAPH_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        nodes_raw = data.get("nodes", {})
        if isinstance(nodes_raw, dict):
            nodes = [{"id": k, **(v or {})} for k, v in nodes_raw.items()]
        else:
            nodes = list(nodes_raw)
        # Precompute token sets to speed match lookups
        for n in nodes:
            n["_tokens"] = _tokens(n.get("content", ""))
        _graph_nodes = nodes
        _graph_loaded_at = time.time()
        logger.info("graph loaded: %d nodes", len(nodes))
    except Exception as e:
        logger.warning("graph load failed: %s", e)


async def _graph_reload_loop() -> None:
    while True:
        await asyncio.sleep(RELOAD_SEC)
        _load_graph()


# ─────────────────────────────────────────────────────────
# Question classification + matching
# ─────────────────────────────────────────────────────────

def _extract_recall_target(text: str) -> Optional[str]:
    """If text is recall-shaped, return the extracted noun phrase
    (the X in 'what's my X'). Otherwise None."""
    if not text:
        return None
    for pat in RECALL_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip(" ?.,!")
    return None


def _best_match(query_tokens: set[str]) -> tuple[Optional[dict], float]:
    """Coverage-based: what fraction of the query tokens does the node contain?
    Jaccard fails for long nodes (memorized research/incident notes) because
    their token-set dwarfs the query. Coverage answers the right question:
    'does this node mention most of what I'm asking about?'"""
    if not query_tokens or not _graph_nodes:
        return None, 0.0
    qsize = len(query_tokens)
    best_node = None
    best_score = 0.0
    for node in _graph_nodes:
        ntok: set[str] = node.get("_tokens") or set()
        if not ntok:
            continue
        inter = len(query_tokens & ntok)
        if inter == 0:
            continue
        coverage = inter / qsize
        # Tiny penalty for noisy long nodes — favor focused matches.
        length_penalty = 1.0 if len(ntok) < 50 else (50.0 / len(ntok)) ** 0.25
        conf = float(node.get("confidence", 0.5))
        score = coverage * (0.5 + 0.5 * conf) * length_penalty
        if score > best_score:
            best_score = score
            best_node = node
    return best_node, best_score


def _summarize_answer(node: dict, query_target: str) -> str:
    """Render a node's content as a short answer to query_target.
    For now this is just the first 280 chars of the content — future
    versions can ask a tiny extractor model to pull just the relevant
    fact."""
    content = node.get("content", "")
    if not content:
        return ""
    # If content fits a "X: Y" pattern, return Y. Otherwise return first
    # sentence or 280 chars.
    head = content.split("\n", 1)[0]
    if ":" in head and len(head) < 240:
        return head.strip()
    sent = re.split(r"(?<=[.!?])\s+", content, maxsplit=1)[0]
    return sent[:280].strip()


# ─────────────────────────────────────────────────────────
# NATS handlers
# ─────────────────────────────────────────────────────────

async def _on_inbound(nc, msg) -> None:
    subject = msg.subject  # e.g. channel.imessage.inbound
    try:
        payload = json.loads(msg.data.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return

    text = payload.get("text") or payload.get("message") or payload.get("body") or ""
    if not text:
        return

    target = _extract_recall_target(text)
    if not target:
        # Not recall-shaped; let the LLM path handle it.
        return

    qtokens = _tokens(target) | _tokens(text)
    # Drop tokens that match the user's pronouns; the question is about THEM
    node, score = _best_match(qtokens)

    if node is None or score < THRESHOLD:
        await nc.publish("brain.deterministic.miss", json.dumps({
            "question": text[:160], "target": target,
            "best_score": round(score, 3),
            "ts": time.time(),
        }).encode("utf-8"))
        return

    answer = _summarize_answer(node, target)
    if not answer:
        return

    # Route the answer back to the same channel + recipient.
    # subject is "channel.X.inbound" — outbound subject is "channel.X.outbound"
    parts = subject.split(".")
    if len(parts) != 3 or parts[0] != "channel" or parts[2] != "inbound":
        return  # unexpected subject shape
    out_subject = f"channel.{parts[1]}.outbound"

    outbound = {
        "text": answer,
        "ts": time.time(),
        "recipient": payload.get("from") or payload.get("recipient"),
        "in_reply_to": payload.get("message_id"),
        "source": "orion.deterministic",
        "via_node": node.get("id"),
        "match_score": round(score, 3),
    }
    # Drop None recipient — outbound adapters fall back to default
    outbound = {k: v for k, v in outbound.items() if v is not None}
    await nc.publish(out_subject, json.dumps(outbound).encode("utf-8"))

    await nc.publish("brain.deterministic.hit", json.dumps({
        "channel": parts[1],
        "question": text[:160],
        "target": target,
        "answer_preview": answer[:120],
        "node_id": node.get("id"),
        "node_confidence": node.get("confidence"),
        "match_score": round(score, 3),
        "tokens_saved_estimate": max(50, len(text.split()) + len(answer.split())),
        "ts": time.time(),
    }).encode("utf-8"))

    logger.info("HIT [%s] '%s' -> node=%s score=%.2f", parts[1], target,
                node.get("id"), score)


# ─────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────

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

    _load_graph()
    if not _graph_nodes:
        logger.warning("graph empty / failed to load — running in pass-through mode")

    nc = NATS()

    async def err_cb(e):  logger.warning("nats err: %s", e)
    async def dis_cb():   logger.warning("nats disconnected")
    async def rec_cb():   logger.info("nats reconnected")

    await nc.connect(servers=[NATS_URL], error_cb=err_cb,
                     disconnected_cb=dis_cb, reconnected_cb=rec_cb,
                     max_reconnect_attempts=-1)
    logger.info("deterministic connected to %s threshold=%.2f",
                NATS_URL, THRESHOLD)

    async def _cb(m):
        await _on_inbound(nc, m)

    await nc.subscribe("channel.*.inbound", cb=_cb)

    reload_task = asyncio.create_task(_graph_reload_loop())
    stop = asyncio.Event()

    def _shutdown(*_):
        logger.info("deterministic shutting down")
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
    reload_task.cancel()
    await nc.drain()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
