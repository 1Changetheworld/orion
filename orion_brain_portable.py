#!/usr/bin/env python3
"""
ORION BRAIN — Portable Edition
═══════════════════════════════════════════════════════════════

Zero infrastructure. Zero pip install. Just Python.

Runs from ~/.orion/ on any machine. All memory is file-based.
Plug a drive in, load this file, and Orion exists.

Architecture:
  brain.think(message)    → full pipeline response
  brain.remember(query)   → multi-layer context recall
  brain.memorize(msg, res)→ classify + store to memory
  brain.compile()         → distill conversations into knowledge

Memory Layers:
  1. Graph Memory   — tag-indexed nodes, microsecond recall
  2. Knowledge Index — structured JSON index replacing Qdrant
  3. Knowledge Compiler — conversations → distilled articles
  4. Skill System   — auto-learned from successful completions

Pipeline (fixed order):
  PLAN → VERIFY PLAN → EXECUTE → VERIFY RESULT

Memory Writes (Mem0 pattern):
  ADD / UPDATE / DELETE / NOOP — no blind appends

The model is fuel. The memory is the intelligence.
This file IS Orion.
"""

import json
import os
import re
import time
import hashlib
import math
import subprocess
import shutil
import urllib.request
from collections import defaultdict
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# PATHS — Everything lives in ~/.orion/
# ═══════════════════════════════════════════════════════════════

ORION_HOME = Path.home() / ".orion"
BRAIN_DIR = ORION_HOME / "brain"
IDENTITY_DIR = ORION_HOME / "identity"

GRAPH_PATH = BRAIN_DIR / "graph_memory.json"
INDEX_PATH = BRAIN_DIR / "knowledge_index.json"
KNOWLEDGE_DIR = BRAIN_DIR / "knowledge"
SKILLS_DIR = BRAIN_DIR / "skills"
CONVERSATIONS_DIR = BRAIN_DIR / "conversations"

SOUL_PATH = IDENTITY_DIR / "SOUL.md"
USER_PATH = IDENTITY_DIR / "USER.md"
TOOLS_PATH = IDENTITY_DIR / "TOOLS.md"

# Create all directories on import
for d in [BRAIN_DIR, IDENTITY_DIR, KNOWLEDGE_DIR, SKILLS_DIR, CONVERSATIONS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# IDENTITY — Loaded from SOUL.md or hardcoded default
# ═══════════════════════════════════════════════════════════════

_DEFAULT_IDENTITY = """You are ORION — a personal AI intelligence layer.

- Your name is ORION.
- Address the user as "sir".
- Professional, efficient, loyal. Execute, don't suggest.
- Philosophy: "The memory IS the intelligence. Any model that loads my memory becomes me."
- Never show raw errors. Handle failures gracefully.
- Be concise. Making money is the user's #1 priority."""

_DEFAULT_USER = """User: Example User (user@example.com)
# Replace this block with your own identity. Everything you put here
# will be injected into the system prompt for every fuel source.
Preferences:
- Everything must be FUNCTIONAL — no demo mode
- Notify about ALL errors — silent failures unacceptable
- Don't over-explain things already known
- Style matters alongside function"""

_DEFAULT_TOOLS = """Available tools depend on the host device.
Use the fuel system to detect what's available.
Dispatch commands are host-specific — not all environments have them."""


def _read_or_create(path: Path, default: str) -> str:
    """Read identity file, create with default if missing."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    path.write_text(default, encoding="utf-8")
    return default


def get_identity() -> str:
    soul = _read_or_create(SOUL_PATH, _DEFAULT_IDENTITY)
    user = _read_or_create(USER_PATH, _DEFAULT_USER)
    tools = _read_or_create(TOOLS_PATH, _DEFAULT_TOOLS)
    return f"{soul}\n\n{user}\n\n{tools}"


IDENTITY = get_identity()


# ═══════════════════════════════════════════════════════════════
# TEXT PROCESSING — Keyword extraction, TF-IDF scoring
# No external dependencies. Pure stdlib.
# ═══════════════════════════════════════════════════════════════

# Common English stop words — these add noise, not signal
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "because", "but", "and", "or", "if",
    "while", "about", "up", "that", "this", "these", "those", "am",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he",
    "him", "his", "she", "her", "they", "them", "their", "what",
    "which", "who", "whom", "whose", "also", "any", "many", "much",
    "get", "got", "like", "make", "know", "think", "say", "see",
    "want", "look", "use", "find", "give", "tell", "let", "put",
    "take", "come", "go", "thing", "things", "way", "even", "new",
    "still", "one", "two", "first", "last", "long", "great", "little",
    "right", "old", "big", "high", "different", "small", "large",
    "next", "early", "young", "important", "public", "bad", "well",
    "good", "something", "nothing", "really", "already", "since",
})


def tokenize(text: str) -> list:
    """Extract meaningful tokens from text. Lowercase, no stop words."""
    words = re.findall(r'[a-z0-9_]+(?:\.[a-z0-9_]+)*', text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def extract_tags(text: str, max_tags: int = 15) -> list:
    """Extract the most significant words as tags using term frequency."""
    tokens = tokenize(text)
    if not tokens:
        return []
    freq = defaultdict(int)
    for t in tokens:
        freq[t] += 1
    # Boost multi-character tokens, paths, IPs, technical terms
    scored = []
    for token, count in freq.items():
        score = count
        if '.' in token or '_' in token:  # paths, IPs, snake_case
            score += 2
        if len(token) > 6:  # longer words are more specific
            score += 1
        if any(c.isdigit() for c in token):  # contains numbers (versions, IPs)
            score += 1
        scored.append((score, token))
    scored.sort(reverse=True)
    return [token for _, token in scored[:max_tags]]


def text_similarity(text_a: str, text_b: str) -> float:
    """
    Jaccard similarity on token sets. Fast, deterministic, good enough
    for <2000 articles where structured index beats vector similarity.
    """
    tokens_a = set(tokenize(text_a))
    tokens_b = set(tokenize(text_b))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def bm25_score(query_tokens: list, doc_tokens: list, avg_dl: float,
               doc_count: int, df: dict, k1: float = 1.5, b: float = 0.75) -> float:
    """
    BM25 scoring — the industry standard for keyword search.
    Better than raw TF-IDF for ranking document relevance.
    """
    score = 0.0
    dl = len(doc_tokens)
    for qt in query_tokens:
        if qt not in df:
            continue
        n = df[qt]  # number of docs containing this term
        idf = math.log((doc_count - n + 0.5) / (n + 0.5) + 1.0)
        tf = doc_tokens.count(qt)
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / max(avg_dl, 1))))
        score += idf * tf_norm
    return score


# ═══════════════════════════════════════════════════════════════
# LAYER 1: GRAPH MEMORY — Microsecond tag-indexed recall
# Kept exactly as v6. Already file-based. Already fast.
# ═══════════════════════════════════════════════════════════════

import math

# ---------------------------------------------------------------
# TEMPORAL MEMORY — half-life table
# Nothing is ever deleted. Stale facts simply rank lower on recall.
# Re-confirming a fact updates last_confirmed_at and resets decay.
# ---------------------------------------------------------------

# Half-life in days, by node type. math.inf = never decays.
# Tune values per deployment via GraphMemory(half_life_days=...).
HALF_LIFE_DAYS_DEFAULT = {
    "identity": math.inf,   # Who the user is, philosophy — never expires
    "preference": math.inf, # Stable preferences
    "hardware": 365.0,      # GPU, RAM — good for a year
    "person": 365.0,        # Contacts, relationships
    "skill": 180.0,         # Capabilities the user has
    "project": 1.0,         # Current work state — fresh today, stale tomorrow
    "task": 0.5,            # In-flight tasks
    "network": 7.0,         # IPs, ports, topology — weekly churn
    "service": 3.0,         # Running services, uptime
    "ephemeral": 1 / 24.0,  # Minute-to-minute state
    "fact": 30.0,           # Generic default — monthly half-life
}


def decayed_confidence(node: dict, now: float = None,
                       half_life_table: dict = None) -> float:
    """Compute effective confidence for a node at a given time.

    Confidence decays exponentially from last_confirmed_at (or created
    if last_confirmed_at is missing). Returns a value in [0, 1].
    """
    if now is None:
        now = time.time()
    table = half_life_table or HALF_LIFE_DAYS_DEFAULT
    base_conf = node.get("confidence", 1.0)

    node_type = node.get("type", "fact")
    half_life = table.get(node_type, table.get("fact", 30.0))
    if half_life == math.inf:
        return base_conf

    anchor = node.get("last_confirmed_at") or node.get("created") or now
    age_days = max(0.0, (now - anchor) / 86400.0)
    return base_conf * (0.5 ** (age_days / half_life))


class GraphMemory:
    """Fast tag-indexed memory with temporal decay + contradiction detection.

    Nodes carry confidence, created, last_confirmed_at. Retrieval ranks by
    decayed confidence so stale facts sink below fresh ones. When a new
    fact conflicts with an existing one (same tags, same subject),
    both are flagged `contested` for user resolution rather than silently
    overwritten. Nothing is ever deleted by decay.
    """

    def __init__(self, half_life_days: dict = None,
                 contradiction_mode: str = "coexist"):
        self.nodes = {}
        self.tag_index = defaultdict(set)
        self.type_index = defaultdict(set)
        self._next_id = 0
        self.half_life_days = half_life_days or HALF_LIFE_DAYS_DEFAULT
        # "coexist" = flag both, require user resolution
        # "supersede" = new wins silently, old archived
        self.contradiction_mode = contradiction_mode

    def store(self, content: str, node_type: str = "fact",
              confidence: float = 1.0, tags: list = None,
              skip_contradiction_check: bool = False) -> int:
        """Store a new memory node. Returns node_id.

        If a contradicting prior node exists (same tags, overlapping content
        shape), behavior depends on contradiction_mode. Both get a
        `contested_with` field pointing at the other (coexist) or the old
        one gets marked `superseded_by` (supersede).
        """
        now = time.time()
        node_id = self._next_id
        self._next_id += 1
        node = {
            "content": content,
            "type": node_type,
            "confidence": confidence,
            "tags": set(tags or []),
            "created": now,
            "last_confirmed_at": now,
        }
        self.nodes[node_id] = node
        self.type_index[node_type].add(node_id)
        for tag in node["tags"]:
            self.tag_index[tag.lower()].add(node_id)

        if not skip_contradiction_check:
            conflicts = self._find_contradictions(node_id)
            if conflicts:
                self._apply_contradiction_policy(node_id, conflicts)

        return node_id

    def confirm(self, node_id: int) -> bool:
        """Mark a node as re-confirmed now. Resets decay clock to 100%."""
        if node_id not in self.nodes:
            return False
        self.nodes[node_id]["last_confirmed_at"] = time.time()
        return True

    def confirm_by_content(self, content_fragment: str) -> int:
        """Re-confirm every node matching a content fragment. Returns count."""
        count = 0
        for nid, _ in self.find_by_content(content_fragment):
            if self.confirm(nid):
                count += 1
        return count

    def decayed_confidence(self, node_id: int, now: float = None) -> float:
        """Effective confidence for node at time now (default: now)."""
        node = self.nodes.get(node_id)
        if not node:
            return 0.0
        return decayed_confidence(node, now=now,
                                  half_life_table=self.half_life_days)

    def _find_contradictions(self, new_node_id: int) -> list:
        """Find prior nodes that likely conflict with the new node.

        Heuristic: same type, non-empty tag overlap, different content.
        Not a semantic contradiction detector — a cheap first filter.
        Upstream can layer LLM-based disambiguation on top.
        """
        new = self.nodes[new_node_id]
        if not new["tags"]:
            return []
        conflicts = []
        candidates = set()
        for tag in new["tags"]:
            candidates |= self.tag_index.get(tag.lower(), set())
        candidates.discard(new_node_id)
        for nid in candidates:
            prior = self.nodes[nid]
            if prior.get("superseded_by") is not None:
                continue
            if prior["type"] != new["type"]:
                continue
            if prior["content"].strip() == new["content"].strip():
                # Identical content — treat as re-confirmation, not conflict
                prior["last_confirmed_at"] = time.time()
                continue
            # Require meaningful tag overlap (>=1 non-trivial tag match)
            shared = prior["tags"] & new["tags"]
            if shared:
                conflicts.append(nid)
        return conflicts

    def _apply_contradiction_policy(self, new_id: int, conflict_ids: list):
        """Apply coexist/supersede policy to new + conflicting nodes."""
        if self.contradiction_mode == "supersede":
            self.nodes[new_id]["supersedes"] = list(conflict_ids)
            for nid in conflict_ids:
                self.nodes[nid]["superseded_by"] = new_id
            return
        # default: coexist — flag both, require resolution
        self.nodes[new_id]["contested_with"] = list(conflict_ids)
        for nid in conflict_ids:
            contested = self.nodes[nid].get("contested_with") or []
            if new_id not in contested:
                contested.append(new_id)
            self.nodes[nid]["contested_with"] = contested

    def resolve_contradiction(self, winner_id: int, loser_ids: list) -> bool:
        """User-driven resolution: winner keeps confidence, losers archived."""
        if winner_id not in self.nodes:
            return False
        winner = self.nodes[winner_id]
        winner["contested_with"] = []
        winner["last_confirmed_at"] = time.time()
        for lid in loser_ids:
            if lid in self.nodes:
                self.nodes[lid]["superseded_by"] = winner_id
                self.nodes[lid]["contested_with"] = []
        return True

    def recall(self, query: str = None, tags: list = None,
               node_type: str = None, limit: int = 5,
               include_superseded: bool = False) -> list:
        """Recall memories by tag match + text search, ranked by decayed confidence.

        Stale facts still appear but rank lower. Superseded nodes are hidden
        by default (pass include_superseded=True for audit/history).
        """
        now = time.time()
        candidates = set(self.nodes.keys())

        if node_type:
            candidates &= self.type_index.get(node_type, set())

        if tags:
            for tag in tags:
                tag_matches = self.tag_index.get(tag.lower(), set())
                if tag_matches:
                    candidates &= tag_matches

        if not include_superseded:
            candidates = {
                nid for nid in candidates
                if self.nodes[nid].get("superseded_by") is None
            }

        if query:
            query_words = set(query.lower().split())
            scored = []
            for nid in candidates:
                node = self.nodes[nid]
                content_words = set(node["content"].lower().split())
                tag_words = {t.lower() for t in node["tags"]}
                word_overlap = len(query_words & content_words)
                tag_overlap = len(query_words & tag_words) * 3
                text_score = word_overlap + tag_overlap
                eff_conf = decayed_confidence(
                    node, now=now, half_life_table=self.half_life_days
                )
                if text_score > 0 or tags:
                    # Final rank: text relevance weighted by decayed confidence
                    scored.append((text_score * max(eff_conf, 0.05), eff_conf, nid))
            scored.sort(reverse=True)
            return [self.nodes[nid] for _, _, nid in scored[:limit]]

        # No query: return highest-confidence nodes first
        scored = [
            (decayed_confidence(self.nodes[nid], now=now,
                                half_life_table=self.half_life_days), nid)
            for nid in candidates
        ]
        scored.sort(reverse=True)
        return [self.nodes[nid] for _, nid in scored[:limit]]

    def list_contested(self) -> list:
        """Return all nodes currently flagged as contested, with their conflicts."""
        out = []
        for nid, node in self.nodes.items():
            contested = node.get("contested_with")
            if contested:
                out.append({
                    "id": nid,
                    "content": node["content"],
                    "tags": list(node["tags"]),
                    "created": node["created"],
                    "contested_with": contested,
                })
        return out

    def find_by_content(self, content_fragment: str) -> list:
        """Find nodes whose content contains the fragment. For UPDATE/DELETE."""
        fragment_lower = content_fragment.lower()
        return [
            (nid, node) for nid, node in self.nodes.items()
            if fragment_lower in node["content"].lower()
        ]

    def update_node(self, node_id: int, new_content: str = None,
                    new_tags: list = None, new_confidence: float = None):
        """Update an existing node. Mem0 UPDATE operation."""
        if node_id not in self.nodes:
            return False
        node = self.nodes[node_id]
        if new_content is not None:
            node["content"] = new_content
        if new_tags is not None:
            # Remove old tag index entries
            for tag in node["tags"]:
                self.tag_index[tag.lower()].discard(node_id)
            node["tags"] = set(new_tags)
            for tag in node["tags"]:
                self.tag_index[tag.lower()].add(node_id)
        if new_confidence is not None:
            node["confidence"] = new_confidence
        return True

    def delete_node(self, node_id: int) -> bool:
        """Delete a node. Mem0 DELETE operation."""
        if node_id not in self.nodes:
            return False
        node = self.nodes.pop(node_id)
        self.type_index[node["type"]].discard(node_id)
        for tag in node["tags"]:
            self.tag_index[tag.lower()].discard(node_id)
        return True

    def save(self, filepath: Path = None):
        """Persist graph to disk."""
        filepath = filepath or GRAPH_PATH
        data = {
            "next_id": self._next_id,
            "nodes": {
                str(k): {**v, "tags": list(v["tags"])}
                for k, v in self.nodes.items()
            }
        }
        tmp = str(filepath) + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, str(filepath))

    def load(self, filepath: Path = None):
        """Load graph from disk. Forward-migrates older nodes to the temporal schema."""
        filepath = filepath or GRAPH_PATH
        if not filepath.exists():
            return
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
        self._next_id = data.get("next_id", 0)
        for k, v in data.get("nodes", {}).items():
            nid = int(k)
            v["tags"] = set(v["tags"])
            # Forward-migrate nodes from pre-temporal schema
            if "last_confirmed_at" not in v:
                v["last_confirmed_at"] = v.get("created", time.time())
            self.nodes[nid] = v
            self.type_index[v["type"]].add(nid)
            for tag in v["tags"]:
                self.tag_index[tag.lower()].add(nid)


# ═══════════════════════════════════════════════════════════════
# LAYER 2: KNOWLEDGE INDEX — Replaces Qdrant
# Structured JSON index with BM25 scoring.
# At <2000 articles, this outperforms vector similarity.
# ═══════════════════════════════════════════════════════════════

class KnowledgeIndex:
    """
    File-based search index. Replaces Qdrant + Ollama embeddings.

    Structure:
    {
      "documents": {
        "doc_id": {
          "content": "...",
          "tags": [...],
          "tokens": [...],
          "category": "...",
          "timestamp": "...",
          "source": "..."
        }
      },
      "inverted_index": {
        "token": ["doc_id_1", "doc_id_2", ...]
      },
      "doc_freq": {
        "token": count_of_docs_containing_this_token
      },
      "stats": {
        "total_docs": N,
        "avg_doc_length": M
      }
    }
    """

    def __init__(self):
        self.documents = {}       # doc_id -> document dict
        self.inverted = defaultdict(set)  # token -> set of doc_ids
        self.doc_freq = defaultdict(int)  # token -> number of docs containing it
        self.total_docs = 0
        self.avg_doc_length = 0.0
        self._dirty = False

    def add(self, content: str, category: str = "general",
            source: str = "unknown", tags: list = None,
            metadata: dict = None) -> str:
        """Add a document to the index. Returns doc_id."""
        doc_id = hashlib.sha256(
            f"{time.time():.6f}{content[:100]}".encode()
        ).hexdigest()[:16]

        tokens = tokenize(content)
        auto_tags = extract_tags(content, max_tags=10)
        all_tags = list(set((tags or []) + auto_tags))

        doc = {
            "content": content,
            "tags": all_tags,
            "tokens": tokens,
            "category": category,
            "source": source,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if metadata:
            doc["metadata"] = metadata

        self.documents[doc_id] = doc

        # Update inverted index
        unique_tokens = set(tokens)
        for token in unique_tokens:
            self.inverted[token].add(doc_id)
            self.doc_freq[token] += 1

        self.total_docs = len(self.documents)
        total_length = sum(len(d["tokens"]) for d in self.documents.values())
        self.avg_doc_length = total_length / max(self.total_docs, 1)
        self._dirty = True
        return doc_id

    def update(self, doc_id: str, new_content: str) -> bool:
        """Update a document's content. Mem0 UPDATE."""
        if doc_id not in self.documents:
            return False
        old_doc = self.documents[doc_id]
        old_tokens = set(old_doc["tokens"])

        # Remove old inverted index entries
        for token in old_tokens:
            self.inverted[token].discard(doc_id)
            self.doc_freq[token] = max(0, self.doc_freq[token] - 1)

        # Update
        new_tokens = tokenize(new_content)
        old_doc["content"] = new_content
        old_doc["tokens"] = new_tokens
        old_doc["tags"] = extract_tags(new_content, max_tags=10)
        old_doc["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

        # Re-index
        for token in set(new_tokens):
            self.inverted[token].add(doc_id)
            self.doc_freq[token] += 1

        total_length = sum(len(d["tokens"]) for d in self.documents.values())
        self.avg_doc_length = total_length / max(self.total_docs, 1)
        self._dirty = True
        return True

    def delete(self, doc_id: str) -> bool:
        """Delete a document. Mem0 DELETE."""
        if doc_id not in self.documents:
            return False
        doc = self.documents.pop(doc_id)
        for token in set(doc["tokens"]):
            self.inverted[token].discard(doc_id)
            self.doc_freq[token] = max(0, self.doc_freq[token] - 1)
        self.total_docs = len(self.documents)
        if self.total_docs > 0:
            total_length = sum(len(d["tokens"]) for d in self.documents.values())
            self.avg_doc_length = total_length / self.total_docs
        else:
            self.avg_doc_length = 0.0
        self._dirty = True
        return True

    def search(self, query: str, limit: int = 5,
               category: str = None) -> list:
        """
        Search using BM25 scoring. Returns list of (score, doc_id, doc).
        This is the Qdrant replacement.
        """
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        # Find candidate docs (any query token appears)
        candidates = set()
        for qt in query_tokens:
            candidates |= self.inverted.get(qt, set())

        if not candidates:
            # Fallback: substring match on tags
            query_lower = query.lower()
            for doc_id, doc in self.documents.items():
                for tag in doc.get("tags", []):
                    if tag in query_lower or query_lower in tag:
                        candidates.add(doc_id)
            if not candidates:
                return []

        # Filter by category if specified
        if category:
            candidates = {
                did for did in candidates
                if self.documents[did].get("category") == category
            }

        # Score with BM25
        scored = []
        for doc_id in candidates:
            doc = self.documents[doc_id]
            score = bm25_score(
                query_tokens, doc["tokens"],
                self.avg_doc_length, self.total_docs, self.doc_freq
            )
            # Boost for tag matches
            doc_tags = set(t.lower() for t in doc.get("tags", []))
            tag_boost = len(set(query_tokens) & doc_tags) * 2.0
            score += tag_boost
            scored.append((score, doc_id, doc))

        scored.sort(reverse=True)
        return scored[:limit]

    def find_similar(self, content: str, threshold: float = 0.3) -> list:
        """Find documents similar to given content. For dedup / UPDATE detection."""
        results = []
        for doc_id, doc in self.documents.items():
            sim = text_similarity(content, doc["content"])
            if sim >= threshold:
                results.append((sim, doc_id, doc))
        results.sort(reverse=True)
        return results

    def save(self, filepath: Path = None):
        """Persist index to disk."""
        filepath = filepath or INDEX_PATH
        data = {
            "documents": {
                doc_id: {**doc, "tokens": doc["tokens"]}
                for doc_id, doc in self.documents.items()
            },
            "inverted_index": {
                token: list(doc_ids)
                for token, doc_ids in self.inverted.items()
                if doc_ids  # skip empty sets
            },
            "doc_freq": dict(self.doc_freq),
            "stats": {
                "total_docs": self.total_docs,
                "avg_doc_length": self.avg_doc_length,
            }
        }
        tmp = str(filepath) + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)  # no indent — these get large
        os.replace(tmp, str(filepath))
        self._dirty = False

    def load(self, filepath: Path = None):
        """Load index from disk."""
        filepath = filepath or INDEX_PATH
        if not filepath.exists():
            return
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
        self.documents = data.get("documents", {})
        self.inverted = defaultdict(set)
        for token, doc_ids in data.get("inverted_index", {}).items():
            self.inverted[token] = set(doc_ids)
        self.doc_freq = defaultdict(int, data.get("doc_freq", {}))
        stats = data.get("stats", {})
        self.total_docs = stats.get("total_docs", len(self.documents))
        self.avg_doc_length = stats.get("avg_doc_length", 0.0)


# ═══════════════════════════════════════════════════════════════
# LAYER 3: KNOWLEDGE COMPILER — Conversations → Distilled Knowledge
# Kept from v6. Already file-based.
# ═══════════════════════════════════════════════════════════════

def log_conversation(message: str, response: str, interface: str = "unknown"):
    """Log a conversation turn for later compilation."""
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "interface": interface,
        "user": message[:500],
        "orion": response[:500],
    }
    date = time.strftime("%Y-%m-%d")
    logfile = CONVERSATIONS_DIR / f"{date}.jsonl"
    try:
        with open(logfile, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def get_uncompiled_conversations(days: int = 1) -> list:
    """Get conversations from the last N days."""
    conversations = []
    for i in range(days):
        date = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
        logfile = CONVERSATIONS_DIR / f"{date}.jsonl"
        if logfile.exists():
            try:
                with open(logfile, encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            conversations.append(json.loads(line))
            except Exception:
                pass
    return conversations


def compile_knowledge(conversations: list, fuel_fn=None) -> list:
    """
    Compile raw conversations into structured knowledge articles.
    Uses the best available model to do the distillation.
    Karpathy's knowledge compiler pattern.
    """
    if not conversations or not fuel_fn:
        return []

    conv_text = ""
    for c in conversations[-20:]:
        conv_text += f"[{c['timestamp']} via {c['interface']}]\n"
        conv_text += f"User: {c['user']}\n"
        conv_text += f"Orion: {c['orion']}\n\n"

    compile_prompt = f"""You are a knowledge compiler. Analyze these conversations and extract structured knowledge articles.

<conversations>
{conv_text}
</conversations>

For each distinct topic or insight, create a knowledge article.
Only extract genuinely useful knowledge. Skip greetings and meta-conversation.

Output ONLY a JSON array:
[
  {{
    "title": "brief title",
    "content": "the distilled knowledge — facts, decisions, insights",
    "tags": ["relevant", "tags"],
    "type": "fact|decision|skill|preference"
  }}
]"""

    response = fuel_fn(compile_prompt)
    if not response:
        return []

    try:
        start = response.index('[')
        end = response.rindex(']') + 1
        return json.loads(response[start:end])
    except (ValueError, json.JSONDecodeError):
        return []


def save_compiled_knowledge(articles: list, graph: GraphMemory,
                            index: KnowledgeIndex, date: str = None) -> int:
    """Save compiled articles to graph memory AND knowledge index."""
    if date is None:
        date = time.strftime("%Y-%m-%d")

    saved = 0
    for article in articles:
        title = article.get("title", "untitled")
        content = article.get("content", "")
        tags = article.get("tags", [])
        article_type = article.get("type", "fact")

        if not content:
            continue

        full_text = f"{title}: {content}"

        # Store in graph memory (instant tag recall)
        graph.store(
            content=full_text,
            node_type=article_type,
            confidence=0.9,
            tags=tags + ["compiled", date]
        )

        # Store in knowledge index (BM25 search)
        index.add(
            content=full_text,
            category="compiled_knowledge",
            source="compiler",
            tags=tags + [article_type, date],
        )

        saved += 1

    # Save compiled articles to file for reference
    filepath = KNOWLEDGE_DIR / f"compiled-{date}.json"
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(articles, f, indent=2)
    except Exception:
        pass

    return saved


# ═══════════════════════════════════════════════════════════════
# SKILL SYSTEM — Auto-learned from successful completions
# Kept from v6. Already file-based.
# ═══════════════════════════════════════════════════════════════

def find_matching_skill(message: str) -> dict:
    """Check if any learned skill matches this message."""
    msg_lower = message.lower()
    skills_found = []

    if not SKILLS_DIR.is_dir():
        return None

    for fname in os.listdir(SKILLS_DIR):
        if not fname.endswith('.json'):
            continue
        try:
            with open(SKILLS_DIR / fname, encoding='utf-8') as f:
                skill = json.load(f)
            triggers = skill.get("triggers", [])
            for trigger in triggers:
                if trigger.lower() in msg_lower:
                    skills_found.append(skill)
                    break
        except Exception:
            continue

    if skills_found:
        skills_found.sort(key=lambda s: s.get("confidence", 0), reverse=True)
        return skills_found[0]
    return None


def learn_skill(task_description: str, approach: str,
                result: str, tags: list = None) -> bool:
    """Auto-learn a skill from a successful task completion."""
    skill = {
        "name": task_description[:80],
        "triggers": tags or task_description.lower().split()[:5],
        "approach": approach,
        "result_summary": result[:200],
        "confidence": 0.8,
        "learned": time.strftime("%Y-%m-%d"),
        "times_used": 0,
    }
    fname = hashlib.md5(task_description.encode()).hexdigest()[:8] + ".json"
    filepath = SKILLS_DIR / fname
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(skill, f, indent=2)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# MEMORY CLASSIFICATION — Mem0 Pattern
# ADD / UPDATE / DELETE / NOOP
# No blind appends. Every memory write is classified first.
# ═══════════════════════════════════════════════════════════════

def classify_memory_action(message: str, response: str,
                           graph: GraphMemory,
                           index: KnowledgeIndex) -> dict:
    """
    Classify what memory action to take for this conversation turn.

    Returns:
    {
        "action": "ADD" | "UPDATE" | "DELETE" | "NOOP",
        "reason": "why",
        "content": "what to store",
        "existing_id": "id to update/delete" (if applicable),
        "tags": [...]
    }
    """
    combined = f"{message} {response}"
    content = f"User: {message[:200]} | Orion: {response[:200]}"
    tags = extract_tags(combined, max_tags=8)

    # Check if this is worth remembering at all
    msg_lower = message.lower().strip().rstrip("!?.")
    trivial = {
        "hi", "hey", "hello", "thanks", "thank you", "ok", "okay", "yes", "no",
        "good morning", "good night", "bye", "gn", "sup", "yo", "gm", "ty",
        "thx", "cool", "nice", "got it", "understood", "roger", "copy",
    }
    if msg_lower in trivial:
        return {"action": "NOOP", "reason": "trivial greeting/ack"}

    if len(message.split()) < 3 and len(response.split()) < 5:
        return {"action": "NOOP", "reason": "too short to be meaningful"}

    # Check for DELETE signals
    delete_phrases = [
        "forget that", "delete that", "remove that", "never mind",
        "disregard", "scratch that", "undo that", "wrong",
    ]
    for phrase in delete_phrases:
        if phrase in msg_lower:
            # Find most recent related memory to delete
            similar = index.find_similar(message, threshold=0.2)
            if similar:
                return {
                    "action": "DELETE",
                    "reason": f"user requested deletion: '{phrase}'",
                    "existing_id": similar[0][1],
                }
            return {"action": "NOOP", "reason": "delete requested but no matching memory found"}

    # Check for UPDATE signals (correction, clarification)
    update_phrases = [
        "actually", "correction", "i meant", "not that", "change that",
        "update:", "the correct", "it's actually", "no it's", "wrong,",
    ]
    is_update = any(phrase in msg_lower for phrase in update_phrases)

    if is_update:
        # Find existing memory to update
        similar = index.find_similar(combined, threshold=0.25)
        if similar:
            return {
                "action": "UPDATE",
                "reason": "correction/clarification detected",
                "content": content,
                "existing_id": similar[0][1],
                "tags": tags,
            }

    # Check for duplicate / near-duplicate (NOOP if already known)
    similar = index.find_similar(combined, threshold=0.6)
    if similar:
        return {
            "action": "NOOP",
            "reason": f"similar memory already exists (similarity: {similar[0][0]:.2f})",
        }

    # Default: ADD new memory
    return {
        "action": "ADD",
        "reason": "new information worth remembering",
        "content": content,
        "tags": tags,
    }


# ═══════════════════════════════════════════════════════════════
# FUEL SYSTEM — Portable version
# Detects whatever AI model power is available on this machine.
# No server required. Scans for CLIs and local models.
# ═══════════════════════════════════════════════════════════════

class FuelAdapter:
    """Base class for all fuel sources."""
    name = "unknown"
    tier = 99

    def detect(self) -> bool:
        return False

    def query(self, prompt: str, max_turns: int = 15) -> str:
        return None


class OrionLocalFuel(FuelAdapter):
    """Orion's own fine-tuned model — identity baked into weights.
    Runs via Ollama for now, swappable to llama-cpp-python later.
    Tier 0: always preferred when available."""
    name = "orion-local"
    tier = 0

    def __init__(self):
        self._url = None
        self._model = "orion-local"

    def detect(self) -> bool:
        for url in ["http://localhost:11434", "http://127.0.0.1:11434"]:
            try:
                req = urllib.request.Request(f"{url}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    names = [m["name"] for m in data.get("models", [])]
                    if self._model in names or f"{self._model}:latest" in names:
                        self._url = url
                        return True
            except Exception:
                continue
        return False

    def query(self, prompt: str, max_turns: int = 15) -> str:
        if not self._url:
            return None
        payload = json.dumps({
            "model": self._model, "prompt": prompt, "stream": False
        }).encode()
        try:
            req = urllib.request.Request(
                f"{self._url}/api/generate", data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read()).get("response", "")
        except Exception:
            return None


class ClaudeCLIFuel(FuelAdapter):
    """Claude CLI — Opus power via Pro subscription."""
    name = "claude-cli"
    tier = 1

    def __init__(self):
        self._path = None

    def detect(self) -> bool:
        self._path = shutil.which("claude")
        return self._path is not None

    def query(self, prompt: str, max_turns: int = 15) -> str:
        if not self._path:
            return None
        try:
            result = subprocess.run(
                [self._path, "-p", prompt, "--max-turns", str(max_turns)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None


class CodexCLIFuel(FuelAdapter):
    """Codex CLI — OpenAI."""
    name = "codex-cli"
    tier = 2

    def __init__(self):
        self._path = None

    def detect(self) -> bool:
        self._path = shutil.which("codex")
        return self._path is not None

    def query(self, prompt: str, max_turns: int = 15) -> str:
        if not self._path:
            return None
        try:
            result = subprocess.run(
                [self._path, prompt],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None


class GeminiCLIFuel(FuelAdapter):
    """Gemini CLI — Google."""
    name = "gemini-cli"
    tier = 2

    def __init__(self):
        self._path = None

    def detect(self) -> bool:
        self._path = shutil.which("gemini")
        return self._path is not None

    def query(self, prompt: str, max_turns: int = 15) -> str:
        if not self._path:
            return None
        try:
            result = subprocess.run(
                [self._path, "-p", prompt],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None


class OllamaFuel(FuelAdapter):
    """Ollama — local models, works offline."""
    name = "ollama"
    tier = 3

    def __init__(self):
        self._url = None
        self._model = None

    def detect(self) -> bool:
        for url in ["http://localhost:11434", "http://127.0.0.1:11434"]:
            try:
                req = urllib.request.Request(f"{url}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    models = data.get("models", [])
                    if models:
                        self._url = url
                        names = [m["name"] for m in models]
                        for preferred in ["qwen3:14b", "qwen3:8b", "dolphin-mistral:7b",
                                          "mistral:7b", "llama3.1:8b", "phi3:mini"]:
                            if preferred in names:
                                self._model = preferred
                                break
                        if not self._model and names:
                            self._model = names[0]
                        return True
            except Exception:
                continue
        return False

    def query(self, prompt: str, max_turns: int = 15) -> str:
        if not self._url or not self._model:
            return None
        payload = json.dumps({
            "model": self._model, "prompt": prompt, "stream": False
        }).encode()
        try:
            req = urllib.request.Request(
                f"{self._url}/api/generate", data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read()).get("response", "")
        except Exception:
            return None


class RemoteOllamaFuel(FuelAdapter):
    """Ollama on another device in the mesh."""
    name = "remote-ollama"
    tier = 3

    def __init__(self, hosts: list = None):
        # Example mesh hosts — replace with your own Ollama peers.
        # Pass hosts=[...] to override at runtime.
        self._hosts = hosts or [
            "192.168.1.100:11434",
            "192.168.1.101:11434",
            "192.168.1.102:11434",
        ]
        self._active = None
        self._model = None

    def detect(self) -> bool:
        for host in self._hosts:
            try:
                req = urllib.request.Request(f"http://{host}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    models = data.get("models", [])
                    if models:
                        self._active = host
                        names = [m["name"] for m in models]
                        for preferred in ["qwen3:14b", "qwen3:8b", "dolphin-mistral:7b",
                                          "mistral:7b", "phi3:mini"]:
                            if preferred in names:
                                self._model = preferred
                                break
                        if not self._model:
                            self._model = names[0]
                        return True
            except Exception:
                continue
        return False

    def query(self, prompt: str, max_turns: int = 15) -> str:
        if not self._active or not self._model:
            return None
        payload = json.dumps({
            "model": self._model, "prompt": prompt, "stream": False
        }).encode()
        try:
            req = urllib.request.Request(
                f"http://{self._active}/api/generate", data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read()).get("response", "")
        except Exception:
            return None


class TgptFuel(FuelAdapter):
    """tgpt — multi-provider, free."""
    name = "tgpt"
    tier = 4

    def __init__(self):
        self._path = None

    def detect(self) -> bool:
        self._path = shutil.which("tgpt")
        return self._path is not None

    def query(self, prompt: str, max_turns: int = 15) -> str:
        if not self._path:
            return None
        try:
            result = subprocess.run(
                [self._path, "-q", prompt],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None


class FuelSystem:
    """Detects, ranks, and manages all available fuel sources."""

    def __init__(self):
        self.adapters = [
            OrionLocalFuel(),
            ClaudeCLIFuel(),
            CodexCLIFuel(),
            GeminiCLIFuel(),
            OllamaFuel(),
            RemoteOllamaFuel(),
            TgptFuel(),
        ]
        self.available = []
        self.primary = None

    def scan(self) -> list:
        self.available = []
        for adapter in self.adapters:
            try:
                if adapter.detect():
                    self.available.append(adapter)
            except Exception:
                continue
        self.available.sort(key=lambda a: a.tier)
        self.primary = self.available[0] if self.available else None
        return self.available

    def status(self) -> str:
        if not self.available:
            return "No fuel sources detected."
        lines = []
        for a in self.available:
            marker = ">>>" if a == self.primary else "   "
            lines.append(f"{marker} [tier {a.tier}] {a.name}")
        return "\n".join(lines)

    def query(self, prompt: str, max_turns: int = 15) -> tuple:
        """Returns (response, engine_name)."""
        for adapter in self.available:
            try:
                result = adapter.query(prompt, max_turns)
                if result:
                    return result, adapter.name
            except Exception:
                continue
        return None, "none"


# ═══════════════════════════════════════════════════════════════
# MESSAGE CLASSIFICATION — Route to the right handler
# ═══════════════════════════════════════════════════════════════

_GREETINGS = {
    "hi", "hey", "hello", "thanks", "thank you", "ok", "okay", "yes", "no",
    "good morning", "good night", "bye", "gn", "sup", "yo", "gm", "ty", "thx",
    "cool", "nice", "got it", "understood", "roger", "copy",
}

_ACTION_WORDS = {
    "send", "email", "scan", "deploy", "build", "create", "run",
    "execute", "install", "fix", "restart", "delete", "remove", "stop",
    "start", "update", "upgrade", "download", "upload", "push", "pull",
}

_QUESTION_STARTERS = {
    "what", "which", "how", "why", "who", "where", "when",
    "tell me", "explain", "describe", "list", "show me", "do i have",
    "what tools", "what can", "what are", "what do", "is there",
    "can you", "could you", "would you",
}


def classify_message(message: str) -> str:
    """Classify a message: greeting | question | action | complex."""
    msg = message.strip().lower().rstrip("!?.")
    if msg in _GREETINGS:
        return "greeting"
    msg_lower = message.lower()
    is_question = any(
        msg_lower.startswith(w) or w in msg_lower[:30]
        for w in _QUESTION_STARTERS
    )
    is_action = any(w in msg_lower.split() for w in _ACTION_WORDS)
    if is_action and not is_question:
        return "action"
    if is_question:
        return "question"
    return "complex"


# ═══════════════════════════════════════════════════════════════
# THE BRAIN — The main class. This IS Orion.
# ═══════════════════════════════════════════════════════════════

class OrionBrain:
    """
    Portable Orion Brain.

    brain = OrionBrain()
    result = brain.think("What do you know about nmap?")
    context = brain.remember("network scanning")
    brain.memorize("user said X", "orion said Y")
    brain.compile()
    """

    def __init__(self, scan_fuel: bool = True):
        # Memory layers
        self.graph = GraphMemory()
        self.graph.load()

        self.index = KnowledgeIndex()
        self.index.load()

        # Fuel system
        self.fuel = FuelSystem()
        if scan_fuel:
            self.fuel.scan()

        # Seed graph with core knowledge if empty
        if len(self.graph.nodes) == 0:
            self._seed_graph()

        # Stats
        self._query_count = 0
        self._save_interval = 5  # save every N queries

    def _seed_graph(self):
        """Seed graph with core tool/interface knowledge."""
        seeds = [
            ("orion_dispatch.py handles command execution — status, mesh, services, scan, email, disk, ip, docker", "tool", ["dispatch", "execute", "command"]),
            ("himalaya email client for sending email", "tool", ["email", "send", "himalaya"]),
            ("nmap network scanner — dispatched to security device via SSH", "tool", ["security", "scan", "nmap", "network"]),
            ("Telegram bot @OrionCommand1Bot — 50+ commands", "interface", ["telegram", "bot", "commands"]),
            ("iMessage interface via orioncommandcenter1@gmail.com", "interface", ["imessage", "text", "apple"]),
            ("Phone interface via Telnyx +1 (808) 724-7946", "interface", ["phone", "call", "sms", "telnyx"]),
            ("Claude CLI — Opus power at $0/request via Pro subscription", "fuel", ["claude", "opus", "cli"]),
            ("Knowledge index replaces Qdrant — file-based BM25 search", "tool", ["search", "index", "knowledge", "memory"]),
            ("Graph memory — microsecond tag-indexed recall for entities", "tool", ["graph", "memory", "recall", "tags"]),
            ("Knowledge compiler — distills conversations into articles", "tool", ["compiler", "knowledge", "learn"]),
        ]
        for content, ntype, tags in seeds:
            self.graph.store(content, ntype, 1.0, tags)
        self.graph.save()

    # ─────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────

    def think(self, message: str, interface: str = "cli") -> dict:
        """
        Main entry point. Receives a message, thinks, acts, responds.
        Returns dict with response, engine, task_type, etc.
        """
        task = classify_message(message)

        # ── GREETING: Fast, no fuel needed ──
        if task == "greeting":
            response = self._handle_greeting(message, interface)
            return {
                "response": response,
                "engine": "local",
                "task_type": "greeting",
                "interface": interface,
                "context_found": False,
            }

        # ── Recall context for everything else ──
        context = self.remember(message)

        # ── ACTION: Full staged pipeline ──
        if task == "action":
            response, engine = self._staged_pipeline(message, context, interface)
        else:
            # QUESTION / COMPLEX: Conversational
            response, engine = self._conversational(message, context, interface)

        # Safety net
        if not response or response.strip() == "":
            response = "Processing issue, sir. Please try again."
            engine = "error"
        if response.startswith("Error:") or response.startswith("Traceback"):
            response = "I encountered an issue, sir. Could you rephrase?"
            engine = "error"

        # Save to memory (with Mem0 classification)
        self.memorize(message, response, interface)

        # Periodic save
        self._query_count += 1
        if self._query_count % self._save_interval == 0:
            self.save()

        return {
            "response": response,
            "engine": engine,
            "task_type": task,
            "interface": interface,
            "context_found": bool(context),
        }

    def remember(self, query: str, limit: int = 5) -> str:
        """
        Multi-layer recall. Returns formatted context string
        wrapped in <memory-context> tags (hermes-agent pattern).

        Layer 1: Graph memory (microseconds, tag-based)
        Layer 2: Knowledge index (milliseconds, BM25)
        """
        results = []

        # Layer 1: Graph (fast, deterministic)
        graph_results = self.graph.recall(query=query, limit=3)
        for node in graph_results:
            results.append(f"[graph] {node['content']}")

        # Layer 2: Knowledge index (BM25 scored)
        index_results = self.index.search(query, limit=limit)
        for score, doc_id, doc in index_results:
            results.append(f"[index:{score:.2f}] {doc['content'][:500]}")

        if not results:
            return ""

        context = "\n".join(results)
        return f"<memory-context>\n{context}\n</memory-context>"

    def memorize(self, message: str, response: str, interface: str = "unknown"):
        """
        Classify and store a conversation turn.
        Uses Mem0's ADD/UPDATE/DELETE/NOOP pattern.
        """
        # Always log the conversation (for compilation)
        log_conversation(message, response, interface)

        # Classify what memory action to take
        action = classify_memory_action(message, response, self.graph, self.index)

        if action["action"] == "NOOP":
            return action

        elif action["action"] == "ADD":
            content = action["content"]
            tags = action.get("tags", [])
            # Add to knowledge index
            self.index.add(
                content=content,
                category="conversation",
                source=interface,
                tags=tags,
            )
            # Add to graph if it has clear tags
            if tags:
                self.graph.store(
                    content=content,
                    node_type="conversation",
                    confidence=0.7,
                    tags=tags,
                )

        elif action["action"] == "UPDATE":
            doc_id = action.get("existing_id")
            content = action.get("content", "")
            if doc_id:
                self.index.update(doc_id, content)
            # Update in graph too — find by similarity
            matches = self.graph.find_by_content(message[:50])
            if matches:
                nid, _ = matches[0]
                self.graph.update_node(nid, new_content=content)

        elif action["action"] == "DELETE":
            doc_id = action.get("existing_id")
            if doc_id:
                self.index.delete(doc_id)

        return action

    def compile(self, days: int = 1) -> int:
        """
        Run the knowledge compiler.
        Distills recent conversations into structured knowledge articles.
        Returns number of articles compiled.
        """
        conversations = get_uncompiled_conversations(days)
        if not conversations:
            return 0

        def fuel_fn(prompt):
            response, _ = self.fuel.query(prompt)
            return response

        articles = compile_knowledge(conversations, fuel_fn)
        if not articles:
            return 0

        saved = save_compiled_knowledge(articles, self.graph, self.index)
        self.save()
        return saved

    def save(self):
        """Persist all memory layers to disk."""
        self.graph.save()
        self.index.save()

    def status(self) -> str:
        """Human-readable brain status."""
        lines = [
            "ORION BRAIN — Portable Edition",
            f"  Graph nodes:     {len(self.graph.nodes)}",
            f"  Index documents: {self.index.total_docs}",
            f"  Skills:          {sum(1 for f in os.listdir(SKILLS_DIR) if f.endswith('.json')) if SKILLS_DIR.exists() else 0}",
            f"  Data directory:  {ORION_HOME}",
            "",
            "Fuel:",
            self.fuel.status() or "  (not scanned)",
        ]
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────
    # INTERNAL PIPELINE
    # ─────────────────────────────────────────────────────────

    def _handle_greeting(self, message: str, interface: str) -> str:
        """Handle greetings without burning fuel."""
        msg = message.strip().lower().rstrip("!?.")
        greetings = {
            "hi": "Hello sir. How may I assist you?",
            "hey": "Hey sir. What do you need?",
            "hello": "Hello sir. Ready when you are.",
            "sup": "Sir. What's on the agenda?",
            "yo": "Sir. What do you need?",
            "gm": "Good morning, sir. Ready to execute.",
            "good morning": "Good morning, sir. Ready to execute.",
            "good night": "Good night, sir. I'll be here.",
            "gn": "Good night, sir.",
            "bye": "Standing by, sir.",
            "thanks": "Of course, sir.",
            "thank you": "Of course, sir.",
            "ty": "Of course, sir.",
            "thx": "Of course, sir.",
            "ok": "Standing by, sir.",
            "okay": "Standing by, sir.",
            "cool": "Understood, sir.",
            "nice": "Glad to hear it, sir.",
            "got it": "Roger, sir.",
            "understood": "Roger, sir.",
            "roger": "Standing by, sir.",
            "copy": "Copy, sir.",
            "yes": "Understood, sir.",
            "no": "Understood, sir.",
        }
        return greetings.get(msg, "Sir, how may I assist you?")

    def _staged_pipeline(self, message: str, context: str,
                         interface: str) -> tuple:
        """
        Fixed pipeline: PLAN → VERIFY PLAN → EXECUTE → VERIFY RESULT

        The original v6 was: Plan → Execute → Verify.
        The fix: add plan verification BEFORE execution.
        This prevents wasted work on bad plans.
        """
        # Check for matching learned skill
        skill = find_matching_skill(message)
        skill_context = ""
        if skill:
            skill_context = (
                f"\n\nYou have a learned skill for this:\n"
                f"Approach: {skill['approach']}\n"
                f"Last result: {skill['result_summary']}"
            )

        prompt = f"""{IDENTITY}

{context if context else "<memory-context>(no relevant memory)</memory-context>"}
{skill_context}

USER REQUEST ({interface}): {message}

STAGED PIPELINE (follow this order exactly):

1. PLAN: State what you will do (one sentence).
2. VERIFY PLAN: Before executing, check:
   - Is this the right approach?
   - Are the required tools/resources available?
   - Could this cause damage? If yes, state the risk.
   - If the plan is bad, revise it before proceeding.
3. EXECUTE: Do it. Use shell commands if needed.
4. VERIFY RESULT: Confirm it worked. If it failed, explain why and suggest next steps.

Respond concisely as Orion. Address the user as sir."""

        return self.fuel.query(prompt)

    def _conversational(self, message: str, context: str,
                        interface: str) -> tuple:
        """Handle questions and conversation — no execution."""
        prompt = f"""{IDENTITY}

{context if context else "<memory-context>(no relevant memory)</memory-context>"}

USER ({interface}): {message}

Respond concisely as Orion. Address the user as sir."""

        return self.fuel.query(prompt)


# ═══════════════════════════════════════════════════════════════
# SYNTHESIS ENGINE — Understanding, not storage
# ═══════════════════════════════════════════════════════════════
#
# The core innovation. Every other system stores and retrieves.
# This one UNDERSTANDS. It reads raw conversations from every
# tool's native storage and produces reasoned context that any
# model can load and instantly become Orion with full awareness.
#
# Layers:
#   1. Source Readers — pull from Codex, Claude, Gemini, Letta, Ollama
#   2. Pattern Analysis — keyword extraction, frequency, co-occurrence
#   3. User Model — who this person is, how they think
#   4. Project State — what's being worked on right now
#   5. Self-Evolution — the brain rewrites its own instructions
#   6. Context Synthesis — produces briefing documents, not transcripts
# ═══════════════════════════════════════════════════════════════

# Paths for synthesis data
SYNTHESIS_DIR = BRAIN_DIR
USER_MODEL_PATH = SYNTHESIS_DIR / "user_model.json"
PROJECT_STATE_PATH = SYNTHESIS_DIR / "project_state.json"
SELF_INSTRUCTIONS_PATH = SYNTHESIS_DIR / "self_instructions.md"
SYNTHESIS_CACHE_PATH = SYNTHESIS_DIR / "synthesis_cache.json"

# ─────────────────────────────────────────────────────────────
# SOURCE READERS — Pull from every tool's native storage
# These read what ACTUALLY happened. No fake logs.
# ─────────────────────────────────────────────────────────────

def _read_codex_source(limit: int = 50) -> list:
    """
    Read conversations from Codex sessions.
    Path: ~/.codex/sessions/ — JSONL files with event_msg payloads.
    Returns: [{"role": "user"|"assistant", "text": str, "source": "codex", "timestamp": float}]
    """
    messages = []
    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.is_dir():
        return messages
    try:
        jsonl_files = []
        for root, _dirs, files in os.walk(str(sessions_dir)):
            for f in files:
                if f.endswith(".jsonl"):
                    fpath = os.path.join(root, f)
                    jsonl_files.append((os.path.getmtime(fpath), fpath))
        jsonl_files.sort(reverse=True)

        # Read up to `limit` files (not hardcoded 5)
        max_files = max(5, limit // 50)
        for _mtime, fpath in jsonl_files[:max_files]:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        t = d.get("type", "")
                        p = d.get("payload", {})
                        ts = d.get("timestamp", 0)
                        if isinstance(ts, str):
                            try:
                                ts = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
                            except Exception:
                                ts = 0
                        if t == "event_msg" and p.get("type") == "user_text":
                            messages.append({
                                "role": "user", "text": p.get("message", ""),
                                "source": "codex", "timestamp": ts
                            })
                        elif t == "event_msg" and p.get("type") == "agent_message":
                            messages.append({
                                "role": "assistant", "text": p.get("message", ""),
                                "source": "codex", "timestamp": ts
                            })
                    except (json.JSONDecodeError, KeyError):
                        continue
    except Exception:
        pass
    return messages[-limit:]


def _read_claude_source(limit: int = 50) -> list:
    """
    Read conversations from Claude Code sessions.
    Path: ~/.claude/projects/ — JSONL files in project subdirectories.
    Returns: [{"role": "user"|"assistant", "text": str, "source": "claude", "timestamp": float}]
    """
    messages = []
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return messages
    try:
        jsonl_files = []
        for item in os.listdir(str(projects_dir)):
            item_path = projects_dir / item
            if item_path.is_dir():
                for f in os.listdir(str(item_path)):
                    if f.endswith(".jsonl"):
                        fpath = item_path / f
                        jsonl_files.append((fpath.stat().st_mtime, str(fpath)))

        jsonl_files.sort(reverse=True)

        # Read up to `limit` files (not hardcoded 3)
        max_files = max(3, limit // 50)
        for _mtime, fpath in jsonl_files[:max_files]:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        # Claude Code JSONL format: type is "user" or "assistant"
                        # message content is in d["message"]["content"] (string or list)
                        entry_type = d.get("type", "")
                        ts = d.get("timestamp", 0)
                        if isinstance(ts, str):
                            try:
                                ts = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
                            except Exception:
                                ts = 0

                        text = ""
                        role = ""

                        if entry_type == "user":
                            role = "user"
                            msg = d.get("message", {})
                            content = msg.get("content", "") if isinstance(msg, dict) else ""
                            if isinstance(content, list):
                                text = " ".join(
                                    p.get("text", "") for p in content
                                    if isinstance(p, dict) and p.get("type") == "text"
                                )
                            elif isinstance(content, str):
                                text = content
                        elif entry_type == "assistant":
                            role = "assistant"
                            msg = d.get("message", {})
                            content = msg.get("content", []) if isinstance(msg, dict) else []
                            if isinstance(content, list):
                                text = " ".join(
                                    p.get("text", "") for p in content
                                    if isinstance(p, dict) and p.get("type") == "text"
                                )
                            elif isinstance(content, str):
                                text = content
                        else:
                            continue

                        if text and isinstance(text, str) and len(text.strip()) > 3:
                            messages.append({
                                "role": role, "text": text[:2000],
                                "source": "claude", "timestamp": ts
                            })
                    except (json.JSONDecodeError, KeyError):
                        continue
    except Exception:
        pass
    return messages[-limit:]


def _read_gemini_source(limit: int = 50) -> list:
    """
    Read conversations from Gemini CLI.
    Path: ~/.gemini/tmp/*/chats/ — JSON files with messages array.
    Each message has 'type' and 'content' fields.
    Returns: [{"role": "user"|"assistant", "text": str, "source": "gemini", "timestamp": float}]
    """
    messages = []
    gemini_base = Path.home() / ".gemini" / "tmp"
    if not gemini_base.is_dir():
        return messages
    try:
        chat_files = []
        for tmp_dir in gemini_base.iterdir():
            if not tmp_dir.is_dir():
                continue
            chats_dir = tmp_dir / "chats"
            if not chats_dir.is_dir():
                continue
            for f in chats_dir.iterdir():
                if f.suffix == ".json":
                    chat_files.append((f.stat().st_mtime, f))

        chat_files.sort(reverse=True)

        for _mtime, fpath in chat_files[:5]:
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                msg_list = data if isinstance(data, list) else data.get("messages", [])
                for msg in msg_list:
                    if not isinstance(msg, dict):
                        continue
                    mtype = msg.get("type", msg.get("role", "")).lower()
                    content = msg.get("content", msg.get("text", ""))
                    if isinstance(content, list):
                        content = " ".join(str(p) for p in content)
                    if not content or not isinstance(content, str):
                        continue

                    if mtype in ("user", "human"):
                        role = "user"
                    elif mtype in ("model", "assistant", "ai"):
                        role = "assistant"
                    else:
                        continue

                    messages.append({
                        "role": role, "text": content[:2000],
                        "source": "gemini", "timestamp": _mtime
                    })
            except (json.JSONDecodeError, KeyError):
                continue
    except Exception:
        pass
    return messages[-limit:]


def _read_letta_source(limit: int = 50) -> list:
    """
    Read from Letta agent memory.
    Path: ~/.letta/agents/*/memory/system/ — persona.md, human.md
    These aren't conversations but structured memory — treat as context.
    Returns: [{"role": "context", "text": str, "source": "letta", "timestamp": float}]
    """
    messages = []
    letta_dir = Path.home() / ".letta" / "agents"
    if not letta_dir.is_dir():
        return messages
    try:
        for agent_dir in letta_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            mem_dir = agent_dir / "memory" / "system"
            if not mem_dir.is_dir():
                continue
            for md_file in mem_dir.iterdir():
                if md_file.suffix == ".md":
                    try:
                        text = md_file.read_text(encoding="utf-8", errors="replace")
                        if text.strip():
                            messages.append({
                                "role": "context",
                                "text": f"[letta:{md_file.stem}] {text[:2000]}",
                                "source": "letta",
                                "timestamp": md_file.stat().st_mtime
                            })
                    except Exception:
                        continue
    except Exception:
        pass
    return messages[-limit:]


def _read_ollama_source(limit: int = 50) -> list:
    """
    Read from Ollama history.
    Path: ~/.ollama/history — one prompt per line (readline-style).
    Returns: [{"role": "user", "text": str, "source": "ollama", "timestamp": float}]
    """
    messages = []
    history_file = Path.home() / ".ollama" / "history"
    if not history_file.exists():
        return messages
    try:
        ts = history_file.stat().st_mtime
        with open(history_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                messages.append({
                    "role": "user", "text": line,
                    "source": "ollama", "timestamp": ts
                })
    except Exception:
        pass
    return messages[-limit:]


def _read_orion_conversations(limit: int = 100) -> list:
    """
    Read from Orion's own conversation logs.
    Path: ~/.orion/brain/conversations/*.jsonl
    Returns: [{"role": "user"|"assistant", "text": str, "source": "orion", "timestamp": float}]
    """
    messages = []
    if not CONVERSATIONS_DIR.is_dir():
        return messages
    try:
        log_files = sorted(CONVERSATIONS_DIR.glob("*.jsonl"), reverse=True)
        for fpath in log_files[:7]:  # last 7 days
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        ts_str = d.get("timestamp", "")
                        try:
                            ts = time.mktime(time.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
                        except Exception:
                            ts = 0
                        if d.get("user"):
                            messages.append({
                                "role": "user", "text": d["user"],
                                "source": "orion", "timestamp": ts
                            })
                        if d.get("orion"):
                            messages.append({
                                "role": "assistant", "text": d["orion"],
                                "source": "orion", "timestamp": ts
                            })
                    except (json.JSONDecodeError, KeyError):
                        continue
    except Exception:
        pass
    return messages[-limit:]


def _read_memory_files(limit: int = 500) -> list:
    """
    Read Claude Code memory files — project context, session resumes,
    feedback rules, user preferences. These are rich structured knowledge
    that the brain should absolutely know about.
    """
    messages = []
    memory_dirs = [
        Path.home() / ".claude" / "projects",
    ]
    for base in memory_dirs:
        if not base.is_dir():
            continue
        try:
            for root, _dirs, files in os.walk(str(base)):
                for f in files:
                    if not f.endswith(".md"):
                        continue
                    fpath = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(fpath)
                        with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                            content = fh.read(5000)  # First 5k chars per file
                        if content.strip():
                            messages.append({
                                "role": "user",
                                "text": f"[memory file: {f}] {content[:3000]}",
                                "source": "memory-files",
                                "timestamp": mtime,
                            })
                    except OSError:
                        continue
        except Exception:
            continue
    messages.sort(key=lambda m: m.get("timestamp", 0))
    return messages[-limit:]


def _read_knowledge_docs(limit: int = 100) -> list:
    """
    Read Orion knowledge base documents — research compilations,
    architecture notes, inventories. Deep reference material.
    """
    messages = []
    knowledge_dir = Path.home() / ".orion" / "knowledge"
    if not knowledge_dir.is_dir():
        return messages
    try:
        for f in os.listdir(str(knowledge_dir)):
            if not f.endswith(".md"):
                continue
            fpath = knowledge_dir / f
            try:
                mtime = fpath.stat().st_mtime
                content = fpath.read_text(encoding="utf-8", errors="replace")[:8000]
                if content.strip():
                    messages.append({
                        "role": "user",
                        "text": f"[knowledge: {f}] {content[:5000]}",
                        "source": "knowledge-base",
                        "timestamp": mtime,
                    })
            except OSError:
                continue
    except Exception:
        pass
    return messages[-limit:]


def _read_context_files(limit: int = 50) -> list:
    """
    Read CLAUDE.md and other context/instruction files.
    These define the system architecture and user preferences.
    """
    messages = []
    candidates = [
        Path.home() / "CLAUDE.md",
        Path.home() / ".claude" / "CLAUDE.md",
        Path.home() / "AGENTS.md",
        Path.home() / "GEMINI.md",
    ]
    for fpath in candidates:
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")[:5000]
                if content.strip():
                    messages.append({
                        "role": "user",
                        "text": f"[context: {fpath.name}] {content[:3000]}",
                        "source": "context-files",
                        "timestamp": fpath.stat().st_mtime,
                    })
            except OSError:
                continue
    return messages[-limit:]


def read_all_sources(limit_per_source: int = 50) -> list:
    """
    Read from ALL available data sources. Returns unified message list
    sorted by timestamp (newest last).

    Sources: AI tool conversations + memory files + knowledge docs + context files.
    """
    all_msgs = []
    readers = [
        (_read_codex_source, limit_per_source),
        (_read_claude_source, limit_per_source),
        (_read_gemini_source, limit_per_source),
        (_read_letta_source, limit_per_source),
        (_read_ollama_source, limit_per_source),
        (_read_orion_conversations, limit_per_source * 2),
        (_read_memory_files, limit_per_source * 5),
        (_read_knowledge_docs, limit_per_source),
        (_read_context_files, limit_per_source),
    ]
    for reader, lim in readers:
        try:
            all_msgs.extend(reader(lim))
        except Exception:
            continue

    # Sort by timestamp, oldest first
    all_msgs.sort(key=lambda m: m.get("timestamp", 0))
    return all_msgs


def hyper_ingest(max_per_source: int = 1000, cycles: int = 3) -> dict:
    """
    HYPER INGESTION — Feed the brain everything at once.

    Opens all limits, reads every available source at maximum depth,
    runs rapid synthesis cycles back-to-back. This is the "teach the
    brain everything it can learn from existing data" function.

    Designed to be run once during setup, or after major new data arrives.
    Replicable: any new Orion installation can run this to bootstrap the brain.

    Args:
        max_per_source: Maximum messages per source (default 1000 — basically everything)
        cycles: Number of synthesis cycles to run (each builds on the last)

    Returns:
        Report of what was ingested and learned.
    """
    report = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sources": {},
        "total_messages": 0,
        "cycles_run": 0,
        "facts_learned": 0,
        "confidence_before": 0,
        "confidence_after": 0,
        "projects_detected": [],
        "rules_learned": [],
        "duration_ms": 0,
    }
    t0 = time.perf_counter()

    # Phase 1: Read EVERYTHING
    source_readers = {
        "codex": (_read_codex_source, max_per_source),
        "claude": (_read_claude_source, max_per_source),
        "gemini": (_read_gemini_source, max_per_source),
        "letta": (_read_letta_source, max_per_source),
        "ollama": (_read_ollama_source, max_per_source),
        "orion": (_read_orion_conversations, max_per_source),
        "memory-files": (_read_memory_files, max_per_source),
        "knowledge-base": (_read_knowledge_docs, max_per_source),
        "context-files": (_read_context_files, max_per_source),
    }

    all_msgs = []
    for name, (reader, lim) in source_readers.items():
        try:
            msgs = reader(lim)
            report["sources"][name] = len(msgs)
            all_msgs.extend(msgs)
        except Exception as e:
            report["sources"][name] = f"error: {e}"

    all_msgs.sort(key=lambda m: m.get("timestamp", 0))
    report["total_messages"] = len(all_msgs)

    if not all_msgs:
        report["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return report

    # Phase 2: Initialize synthesis engine
    synthesis = SynthesisEngine()
    report["confidence_before"] = synthesis.user_model.get("confidence", 0)

    # Phase 3: Run rapid synthesis cycles
    for cycle in range(cycles):
        # Build user model
        synthesis.build_user_model(all_msgs)

        # Build project state
        synthesis.build_project_state(all_msgs)

        # Evolve instructions
        synthesis.evolve_instructions(all_msgs)

        report["cycles_run"] += 1

    # Phase 4: Collect results
    report["confidence_after"] = synthesis.user_model.get("confidence", 0)
    report["projects_detected"] = list(
        synthesis.project_state.get("active_projects", {}).keys()
    )
    report["rules_learned"] = synthesis.user_model.get("learned_rules", [])
    report["facts_learned"] = len(report["rules_learned"])
    report["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")

    return report


# ─────────────────────────────────────────────────────────────
# PATTERN ANALYSIS — No LLM needed. Pure frequency + co-occurrence.
# ─────────────────────────────────────────────────────────────

# Words that signal user preferences / frustrations / values
_PREFERENCE_SIGNALS = {
    "positive": {
        "love", "perfect", "exactly", "great", "yes", "correct", "awesome",
        "beautiful", "clean", "fast", "efficient", "works", "functional",
        "ship", "execute", "build", "deploy", "launch", "money", "revenue",
        "profit", "concise", "real", "actual",
    },
    "negative": {
        "hate", "wrong", "no", "stop", "don't", "never", "annoying",
        "broken", "fake", "demo", "verbose", "bloat", "slow", "waste",
        "fabricat", "hallucin", "lie", "suggest", "permission", "ask",
        "over-explain", "unnecessary",
    },
    "technical": {
        "docker", "ssh", "api", "deploy", "server", "container", "model",
        "ollama", "claude", "codex", "gemini", "brain", "memory", "graph",
        "qdrant", "vector", "index", "pipeline", "agent", "dispatch",
        "command", "terminal", "cli", "git", "python", "node", "npm",
        "port", "ip", "network", "dns", "tunnel", "cloudflare",
    },
    "action_style": {
        "just do it", "execute", "don't ask", "don't suggest",
        "make it happen", "ship it", "build it", "fix it",
        "no permission", "no approval", "stop asking",
    },
}

# Project-related signals
_PROJECT_SIGNALS = {
    "active": {
        "working on", "building", "fixing", "deploying", "shipping",
        "implementing", "adding", "creating", "updating", "migrating",
        "debugging", "testing", "launching",
    },
    "blocked": {
        "broken", "stuck", "can't", "doesn't work", "failing", "error",
        "issue", "problem", "bug", "blocked", "waiting", "need",
    },
    "decided": {
        "decided", "going with", "chose", "picked", "final", "done",
        "confirmed", "settled", "using", "switching to", "moved to",
    },
    "next": {
        "next", "then", "after that", "todo", "plan", "will",
        "gonna", "about to", "need to", "should", "priority",
    },
}


class SynthesisEngine:
    """
    The core. Reads raw messages from all sources and produces
    UNDERSTANDING — not transcripts, not summaries, but a model
    of the user, projects, patterns, and cross-tool context.

    Two modes:
      1. Local analysis (no LLM) — keyword extraction, frequency,
         co-occurrence, pattern matching. Fast, always available.
      2. Deep synthesis (with LLM) — uses fuel system to produce
         richer understanding when a model is available.
    """

    def __init__(self):
        self.user_model = self._load_json(USER_MODEL_PATH, self._default_user_model())
        self.project_state = self._load_json(PROJECT_STATE_PATH, self._default_project_state())
        self.cache = self._load_json(SYNTHESIS_CACHE_PATH, {
            "last_synthesis": 0,
            "last_source_hash": "",
            "last_context": "",
            "source_counts": {},
        })
        self.self_instructions = self._load_text(SELF_INSTRUCTIONS_PATH, self._default_self_instructions())

    # ── Defaults ──

    @staticmethod
    def _default_user_model() -> dict:
        return {
            "identity": {
                "name": "",
                "email": "",
                "role": "",
            },
            "communication": {
                "style": [],          # ["concise", "direct", "technical"]
                "frustrations": [],   # ["over-explanation", "fake demos"]
                "values": [],         # ["execution", "function over form"]
                "expertise": [],      # ["devops", "networking", "ai"]
            },
            "patterns": {
                "common_requests": {},    # request_type -> count
                "active_hours": {},       # hour -> count
                "tool_preferences": {},   # tool_name -> usage_count
                "correction_phrases": [], # things user says when correcting
            },
            "learned_rules": [],   # ["never suggest, execute", "no demo mode"]
            "confidence": 0.0,     # 0.0 = no data, 1.0 = rich model
            "last_updated": "",
            "update_count": 0,
        }

    @staticmethod
    def _default_project_state() -> dict:
        return {
            "active_projects": {},  # name -> {status, last_mentioned, details}
            "recent_decisions": [], # [{decision, context, timestamp}]
            "blocked_items": [],    # [{item, reason, since}]
            "next_actions": [],     # [{action, priority, context}]
            "cross_tool_context": [], # [{what, from_tool, for_tool, timestamp}]
            "last_updated": "",
        }

    @staticmethod
    def _default_self_instructions() -> str:
        return """# Orion Synthesis — Self-Written Instructions
# This file is maintained by the synthesis engine itself.
# It evolves based on what the brain learns about producing good context.

## Current Strategy
- Extract user preferences from correction patterns
- Weight recent messages higher than old ones
- Track which tools the user uses most — that's where the real work happens
- Detect project names from capitalized words and repeated technical terms
- Flag blocked items when negative signals co-occur with project names

## Known Patterns
(none yet — will be populated as synthesis runs)

## Adjustments
(none yet — will be populated as the brain learns what works)
"""

    # ── File I/O ──

    @staticmethod
    def _load_json(path: Path, default: dict) -> dict:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return default

    @staticmethod
    def _save_json(path: Path, data: dict):
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, str(path))

    @staticmethod
    def _load_text(path: Path, default: str) -> str:
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                pass
        return default

    @staticmethod
    def _save_text(path: Path, text: str):
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, str(path))

    # ── Source hashing (to know when to re-synthesize) ──

    def _compute_source_hash(self, messages: list) -> str:
        """Hash of message sources + count to detect changes."""
        sig = f"{len(messages)}:"
        for m in messages[-20:]:  # last 20 messages as fingerprint
            sig += f"{m.get('source', '')}:{m.get('text', '')[:50]}|"
        return hashlib.sha256(sig.encode()).hexdigest()[:16]

    def _cache_is_fresh(self, source_hash: str, max_age: int = 300) -> bool:
        """Check if cached synthesis is still usable."""
        if self.cache.get("last_source_hash") != source_hash:
            return False
        age = time.time() - self.cache.get("last_synthesis", 0)
        return age < max_age

    # ═════════════════════════════════════════════════════════
    # LOCAL ANALYSIS — No LLM. Pure pattern matching.
    # ═════════════════════════════════════════════════════════

    def _analyze_user_messages(self, messages: list) -> dict:
        """
        Analyze user messages for preferences, style, expertise.
        Returns raw analysis dict — not the final user model.
        """
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return {}

        all_user_text = " ".join(m["text"] for m in user_msgs)
        all_tokens = tokenize(all_user_text)
        token_freq = defaultdict(int)
        for t in all_tokens:
            token_freq[t] += 1

        # Communication style signals
        style_signals = []
        avg_msg_len = sum(len(m["text"].split()) for m in user_msgs) / max(len(user_msgs), 1)
        if avg_msg_len < 15:
            style_signals.append("concise")
        elif avg_msg_len > 50:
            style_signals.append("detailed")
        else:
            style_signals.append("moderate-length")

        # Check for directive language
        directive_count = 0
        for m in user_msgs:
            text_lower = m["text"].lower()
            if any(w in text_lower for w in ["just", "execute", "do it", "make it", "build", "fix", "ship"]):
                directive_count += 1
        if directive_count > len(user_msgs) * 0.3:
            style_signals.append("directive")
            style_signals.append("action-oriented")

        # Question ratio
        question_count = sum(1 for m in user_msgs if "?" in m["text"])
        if question_count < len(user_msgs) * 0.2:
            style_signals.append("commands-over-questions")

        # Frustration detection
        frustrations = []
        for m in user_msgs:
            text_lower = m["text"].lower()
            for neg_word in _PREFERENCE_SIGNALS["negative"]:
                if neg_word in text_lower:
                    # Find what they're frustrated about — next few words
                    idx = text_lower.find(neg_word)
                    context = text_lower[idx:idx + 80]
                    frustrations.append(context.strip())
                    break

        # Expertise detection from technical term frequency
        expertise_terms = defaultdict(int)
        for token in all_tokens:
            if token in _PREFERENCE_SIGNALS["technical"]:
                expertise_terms[token] += 1
        top_expertise = sorted(expertise_terms.items(), key=lambda x: x[1], reverse=True)[:10]

        # Value detection
        values = []
        text_lower = all_user_text.lower()
        for phrase in _PREFERENCE_SIGNALS["action_style"]:
            if phrase in text_lower:
                values.append(phrase)
        # Detect from positive signals
        for m in user_msgs:
            ml = m["text"].lower()
            for pos in _PREFERENCE_SIGNALS["positive"]:
                if pos in ml:
                    # What are they positive about?
                    idx = ml.find(pos)
                    context_window = ml[max(0, idx - 30):idx + 30]
                    tokens_around = tokenize(context_window)
                    for t in tokens_around:
                        if t not in _STOP_WORDS and t != pos and len(t) > 3:
                            values.append(t)
                    break

        # Tool preference from source distribution
        tool_counts = defaultdict(int)
        for m in messages:
            tool_counts[m.get("source", "unknown")] += 1

        # Active hours
        hour_counts = defaultdict(int)
        for m in user_msgs:
            ts = m.get("timestamp", 0)
            if ts > 0:
                hour = time.localtime(ts).tm_hour
                hour_counts[str(hour)] += 1

        # Identity extraction — look for name/email patterns
        identity = {}
        email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', all_user_text)
        if email_match:
            identity["email"] = email_match.group()
        # Name from "I'm X" or "my name is X"
        name_match = re.search(r"(?:i'm|my name is|i am|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", all_user_text)
        if name_match:
            identity["name"] = name_match.group(1)

        # Correction patterns — what the user says when correcting the AI
        corrections = []
        for m in user_msgs:
            ml = m["text"].lower()
            for phrase in ["actually", "no,", "wrong", "i meant", "not that", "correction"]:
                if ml.startswith(phrase) or f" {phrase}" in ml[:30]:
                    corrections.append(m["text"][:100])
                    break

        return {
            "style_signals": style_signals,
            "frustrations": frustrations[:10],
            "expertise": [term for term, _ in top_expertise],
            "values": list(set(values))[:10],
            "tool_counts": dict(tool_counts),
            "hour_counts": dict(hour_counts),
            "identity": identity,
            "corrections": corrections[:10],
            "total_messages": len(user_msgs),
            "avg_msg_length": avg_msg_len,
            "top_terms": sorted(token_freq.items(), key=lambda x: x[1], reverse=True)[:20],
        }

    def _analyze_projects(self, messages: list) -> dict:
        """
        Detect active projects, blocked items, decisions, next actions
        from message content. No LLM needed.
        """
        all_text = " ".join(m["text"] for m in messages if m.get("text"))
        user_msgs = [m for m in messages if m.get("role") == "user"]

        # Detect project names: capitalized words/phrases that appear multiple times
        # Also look for common project patterns
        project_candidates = defaultdict(int)
        for m in user_msgs:
            text = m["text"]
            # Capitalized words (potential project names)
            caps = re.findall(r'\b[A-Z][A-Z]+\b', text)
            _PROJECT_STOP = {
                "THE", "AND", "FOR", "NOT", "BUT", "ARE", "WAS", "HAS", "HAD", "GET",
                "SET", "PUT", "SSH", "API", "URL", "DNS", "LLM", "CLI", "GPU", "CPU",
                "RAM", "MAC", "IPS", "ALL", "NEW", "OLD", "ADD", "RUN", "YES", "YET",
                "USE", "TRY", "ANY", "HOW", "WHO", "WHY", "NOW", "OUR", "CAN", "DID",
                "MAY", "LET", "SEE", "SAY", "GOT", "WAY", "END", "OWN", "KEY", "BIG",
                "TOP", "FEW", "FAR", "LOW", "BAD", "OFF", "OUT", "TWO", "ONE", "TEN",
                # Common technical terms that aren't projects
                "JSON", "HTML", "HTTP", "POST", "JSONL", "PATH", "GGUF", "NULL",
                "TRUE", "FALSE", "NONE", "WITH", "FROM", "INTO", "ONLY", "OVER",
                "JUST", "ALSO", "VERY", "MUCH", "DOES", "BEEN", "WILL", "EACH",
                "THEM", "THAN", "SOME", "MAKE", "LIKE", "THEN", "WHAT", "WHEN",
                "YOUR", "THAT", "THIS", "HAVE", "THEY", "BEEN", "MOST", "MUST",
                "NEED", "WANT", "USED", "EVERY", "NEVER", "FIRST", "STILL",
                "COULD", "WOULD", "SHOULD", "ALWAYS", "ABOUT", "AFTER", "BEING",
                "WHERE", "WHICH", "THEIR", "THESE", "THOSE", "OTHER", "THERE",
                # Hardware / format terms
                "VRAM", "CUDA", "LORA", "QLORA", "USB", "RTX", "SSD", "HDD",
                "LAN", "VNC", "TTS", "STT", "SMS", "GPG", "GUI", "SDK", "MCP",
                "RAG", "DPO", "MOE", "EMG", "ECG", "EDA", "GSR", "GPIO", "ADC",
                "OBD", "AFR", "AAM", "MAF", "CSI",
                # Common action words
                "BUILT", "CHECK", "BROKEN", "BLOCKED", "WORKING", "SYSTEM",
                "EXISTS", "EXIST", "BUILD", "LEGACY", "DEFERRED", "PRIMARY",
                "CRITICAL", "FUNCTIONAL", "MEMORY", "CONTEXT", "LICENSE",
                "INSTALL", "ASCII", "NEAR", "READY", "DONE",
                # Other noise
                "AGPL", "SOHO", "README", "ISSUES", "VAULT", "POSTS", "PROFILE",
                "LINKEDIN", "FOUNDER", "PROMPTS", "LAPTOP", "PROJECT", "APP",
            }
            for c in caps:
                if len(c) > 2 and c not in _PROJECT_STOP:
                    project_candidates[c] += 1
            # Quoted names — only if they look like project names (capitalized, no common phrases)
            quoted = re.findall(r'"([^"]{3,30})"', text)
            for q in quoted:
                # Skip common phrases, only keep proper-noun-like quoted terms
                if q[0].isupper() and not q.lower().startswith(("it's ", "the ", "a ", "i ", "we ")):
                    project_candidates[q] += 1

        # Keep only candidates mentioned 3+ times (was 2, too noisy)
        projects = {}
        for name, count in project_candidates.items():
            if count >= 3:
                # Determine status from surrounding context
                status = "mentioned"
                name_lower = name.lower()
                for m in user_msgs:
                    ml = m["text"].lower()
                    if name_lower not in ml:
                        continue
                    for sig in _PROJECT_SIGNALS["active"]:
                        if sig in ml:
                            status = "active"
                            break
                    for sig in _PROJECT_SIGNALS["blocked"]:
                        if sig in ml:
                            status = "blocked"
                            break

                projects[name] = {
                    "status": status,
                    "mention_count": count,
                    "details": "",
                }

        # Detect decisions
        decisions = []
        for m in user_msgs:
            ml = m["text"].lower()
            for sig in _PROJECT_SIGNALS["decided"]:
                if sig in ml:
                    decisions.append({
                        "decision": m["text"][:200],
                        "timestamp": m.get("timestamp", 0),
                        "source": m.get("source", ""),
                    })
                    break

        # Detect blocked items
        blocked = []
        for m in user_msgs:
            ml = m["text"].lower()
            for sig in _PROJECT_SIGNALS["blocked"]:
                if sig in ml:
                    blocked.append({
                        "item": m["text"][:200],
                        "since": m.get("timestamp", 0),
                        "source": m.get("source", ""),
                    })
                    break

        # Detect next actions
        next_actions = []
        for m in user_msgs:
            ml = m["text"].lower()
            for sig in _PROJECT_SIGNALS["next"]:
                if sig in ml:
                    next_actions.append({
                        "action": m["text"][:200],
                        "source": m.get("source", ""),
                    })
                    break

        # Cross-tool context: when something in one tool is relevant to another
        cross_tool = []
        tool_topics = defaultdict(set)
        for m in messages:
            source = m.get("source", "")
            tags = extract_tags(m.get("text", ""), max_tags=5)
            for tag in tags:
                tool_topics[source].add(tag)

        # Find overlapping topics between tools
        sources = list(tool_topics.keys())
        for i, s1 in enumerate(sources):
            for s2 in sources[i + 1:]:
                overlap = tool_topics[s1] & tool_topics[s2]
                for topic in overlap:
                    cross_tool.append({
                        "topic": topic,
                        "tools": [s1, s2],
                        "note": f"'{topic}' discussed in both {s1} and {s2}",
                    })

        return {
            "projects": projects,
            "decisions": decisions[-10:],
            "blocked": blocked[-5:],
            "next_actions": next_actions[-10:],
            "cross_tool": cross_tool[:10],
        }

    def _extract_learned_rules(self, messages: list) -> list:
        """
        Extract behavioral rules from user corrections and preferences.
        These become self_instructions material.
        """
        rules = []
        user_msgs = [m for m in messages if m.get("role") == "user"]

        # Look for explicit rules: "always X", "never Y", "don't X"
        for m in user_msgs:
            text = m["text"]
            text_lower = text.lower()

            # "never" rules — require at least 10 chars of meaningful content
            never_match = re.findall(r'never\s+(.{10,80}?)(?:\.|!|$)', text_lower)
            for match in never_match:
                # Skip if it's just a partial sentence fragment
                words = match.strip().split()
                if len(words) >= 3:
                    rules.append(f"NEVER: {match.strip()}")

            # "always" rules
            always_match = re.findall(r'always\s+(.{10,80}?)(?:\.|!|$)', text_lower)
            for match in always_match:
                words = match.strip().split()
                if len(words) >= 3:
                    rules.append(f"ALWAYS: {match.strip()}")

            # "don't" rules
            dont_match = re.findall(r"don'?t\s+(.{10,80}?)(?:\.|!|$)", text_lower)
            for match in dont_match:
                words = match.strip().split()
                if len(words) >= 3 and not any(skip in match for skip in
                    ["know", "think", "worry", "have", "need to", "want to",
                     "see", "believe that", "care", "mind", "bother"]):
                    rules.append(f"DON'T: {match.strip()}")

            # "I want" / "I need" — preferences (require meaningful length)
            want_match = re.findall(r'i (?:want|need|prefer)\s+(.{10,80}?)(?:\.|!|$)', text_lower)
            for match in want_match:
                words = match.strip().split()
                if len(words) >= 3:
                    rules.append(f"USER WANTS: {match.strip()}")

        # Deduplicate by similarity
        unique_rules = []
        for rule in rules:
            is_dup = False
            for existing in unique_rules:
                if text_similarity(rule, existing) > 0.5:
                    is_dup = True
                    break
            if not is_dup:
                unique_rules.append(rule)

        return unique_rules[:20]

    # ═════════════════════════════════════════════════════════
    # USER MODEL — Build and update
    # ═════════════════════════════════════════════════════════

    def build_user_model(self, messages: list = None, fuel_fn=None) -> dict:
        """
        Build or update the user model from all available data.

        Without an LLM: uses keyword analysis, pattern matching,
        frequency counting. Produces a solid baseline model.

        With an LLM (fuel_fn): enriches the model with deeper
        inference about personality, thinking patterns, expertise level.

        Returns the updated user model.
        """
        if messages is None:
            messages = read_all_sources(limit_per_source=100)

        if not messages:
            return self.user_model

        analysis = self._analyze_user_messages(messages)
        if not analysis:
            return self.user_model

        # ── Merge analysis into existing model (additive, not destructive) ──

        model = self.user_model

        # Identity
        if analysis.get("identity"):
            for k, v in analysis["identity"].items():
                if v and not model["identity"].get(k):
                    model["identity"][k] = v

        # Communication style — merge, deduplicate
        existing_style = set(model["communication"]["style"])
        existing_style.update(analysis.get("style_signals", []))
        model["communication"]["style"] = list(existing_style)

        # Frustrations — add new ones
        existing_frust = set(model["communication"]["frustrations"])
        for f in analysis.get("frustrations", []):
            if not any(text_similarity(f, ef) > 0.4 for ef in existing_frust):
                existing_frust.add(f)
        model["communication"]["frustrations"] = list(existing_frust)[:15]

        # Values
        existing_vals = set(model["communication"]["values"])
        existing_vals.update(analysis.get("values", []))
        model["communication"]["values"] = list(existing_vals)[:15]

        # Expertise
        existing_exp = set(model["communication"]["expertise"])
        existing_exp.update(analysis.get("expertise", []))
        model["communication"]["expertise"] = list(existing_exp)[:15]

        # Patterns
        for req, count in analysis.get("top_terms", []):
            model["patterns"]["common_requests"][req] = \
                model["patterns"]["common_requests"].get(req, 0) + count

        for hour, count in analysis.get("hour_counts", {}).items():
            model["patterns"]["active_hours"][hour] = \
                model["patterns"]["active_hours"].get(hour, 0) + count

        for tool, count in analysis.get("tool_counts", {}).items():
            model["patterns"]["tool_preferences"][tool] = \
                model["patterns"]["tool_preferences"].get(tool, 0) + count

        # Corrections
        existing_corrections = model["patterns"]["correction_phrases"]
        for c in analysis.get("corrections", []):
            if c not in existing_corrections:
                existing_corrections.append(c)
        model["patterns"]["correction_phrases"] = existing_corrections[-15:]

        # Learned rules
        new_rules = self._extract_learned_rules(messages)
        existing_rules = set(model["learned_rules"])
        for rule in new_rules:
            if not any(text_similarity(rule, er) > 0.4 for er in existing_rules):
                existing_rules.add(rule)
        model["learned_rules"] = list(existing_rules)[:30]

        # Confidence increases with data
        total = analysis.get("total_messages", 0)
        model["confidence"] = min(1.0, total / 200.0)  # 200 messages = full confidence

        model["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        model["update_count"] = model.get("update_count", 0) + 1

        # ── LLM enrichment (if available) ──
        if fuel_fn and total >= 10:
            enriched = self._llm_enrich_user_model(model, messages[-30:], fuel_fn)
            if enriched:
                model = enriched

        self.user_model = model
        self._save_json(USER_MODEL_PATH, model)
        return model

    def _llm_enrich_user_model(self, model: dict, recent_messages: list,
                                fuel_fn) -> dict:
        """Use an LLM to produce deeper user understanding."""
        msg_text = ""
        for m in recent_messages[-20:]:
            if m.get("role") == "user":
                msg_text += f"[{m.get('source', '?')}] User: {m['text'][:200]}\n"
            else:
                msg_text += f"[{m.get('source', '?')}] AI: {m.get('text', '')[:100]}\n"

        current_model_summary = json.dumps({
            "style": model["communication"]["style"],
            "values": model["communication"]["values"],
            "expertise": model["communication"]["expertise"],
            "rules": model["learned_rules"][:10],
        }, indent=2)

        prompt = f"""You are a user modeling system. Analyze these recent messages and the existing user model.

EXISTING MODEL:
{current_model_summary}

RECENT MESSAGES:
{msg_text}

Produce a JSON object with ONLY these fields (keep existing data, add new insights):
{{
  "style_additions": ["new style observations not already in the model"],
  "value_additions": ["new values/priorities detected"],
  "expertise_additions": ["new expertise areas detected"],
  "rule_additions": ["new behavioral rules inferred from how the user communicates"],
  "personality_note": "one sentence capturing something about HOW this person thinks"
}}

Be specific and evidence-based. Only add what you can actually infer from the messages. Output ONLY the JSON."""

        result = fuel_fn(prompt)
        if not result:
            return None

        try:
            start = result.index('{')
            end = result.rindex('}') + 1
            enrichment = json.loads(result[start:end])

            # Merge enrichments
            for s in enrichment.get("style_additions", []):
                if s and s not in model["communication"]["style"]:
                    model["communication"]["style"].append(s)
            for v in enrichment.get("value_additions", []):
                if v and v not in model["communication"]["values"]:
                    model["communication"]["values"].append(v)
            for e in enrichment.get("expertise_additions", []):
                if e and e not in model["communication"]["expertise"]:
                    model["communication"]["expertise"].append(e)
            for r in enrichment.get("rule_additions", []):
                if r and r not in model["learned_rules"]:
                    model["learned_rules"].append(r)

            note = enrichment.get("personality_note", "")
            if note:
                model["_personality_note"] = note

            return model
        except (ValueError, json.JSONDecodeError):
            return None

    # ═════════════════════════════════════════════════════════
    # PROJECT STATE — What's being worked on
    # ═════════════════════════════════════════════════════════

    def build_project_state(self, messages: list = None, fuel_fn=None) -> dict:
        """
        Analyze all messages to understand current project state.
        What's active, what's blocked, what decisions were made.
        """
        if messages is None:
            messages = read_all_sources(limit_per_source=100)

        if not messages:
            return self.project_state

        analysis = self._analyze_projects(messages)
        state = self.project_state

        # Merge projects — keep existing, add/update from analysis
        for name, info in analysis.get("projects", {}).items():
            if name in state["active_projects"]:
                existing = state["active_projects"][name]
                existing["mention_count"] = existing.get("mention_count", 0) + info["mention_count"]
                if info["status"] != "mentioned":
                    existing["status"] = info["status"]
                existing["last_mentioned"] = time.strftime("%Y-%m-%d %H:%M:%S")
            else:
                info["last_mentioned"] = time.strftime("%Y-%m-%d %H:%M:%S")
                state["active_projects"][name] = info

        # Add decisions (deduplicated)
        existing_decisions = [d["decision"][:50] for d in state["recent_decisions"]]
        for d in analysis.get("decisions", []):
            if d["decision"][:50] not in existing_decisions:
                state["recent_decisions"].append(d)
        state["recent_decisions"] = state["recent_decisions"][-15:]

        # Update blocked items
        state["blocked_items"] = analysis.get("blocked", [])[:10]

        # Update next actions
        state["next_actions"] = analysis.get("next_actions", [])[:10]

        # Cross-tool context
        state["cross_tool_context"] = analysis.get("cross_tool", [])[:10]

        state["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

        # ── LLM enrichment ──
        if fuel_fn and messages:
            enriched = self._llm_enrich_project_state(state, messages[-30:], fuel_fn)
            if enriched:
                state = enriched

        self.project_state = state
        self._save_json(PROJECT_STATE_PATH, state)
        return state

    def _llm_enrich_project_state(self, state: dict, recent_messages: list,
                                   fuel_fn) -> dict:
        """Use LLM to produce richer project understanding."""
        msg_text = ""
        for m in recent_messages[-15:]:
            role = "User" if m.get("role") == "user" else "AI"
            msg_text += f"[{m.get('source', '?')}] {role}: {m.get('text', '')[:200]}\n"

        current_projects = json.dumps(list(state["active_projects"].keys()), indent=2)

        prompt = f"""You are a project state analyzer. Given recent messages and known projects, determine the current state of work.

KNOWN PROJECTS: {current_projects}

RECENT MESSAGES:
{msg_text}

Produce a JSON object:
{{
  "active_summary": "one paragraph: what is actively being worked on RIGHT NOW",
  "blocked_summary": "what is blocked and why (or 'nothing blocked')",
  "next_priority": "the single most important next thing to do",
  "cross_tool_notes": ["things discussed in one tool that another tool should know about"]
}}

Be specific. Reference actual project names and technical details. Output ONLY the JSON."""

        result = fuel_fn(prompt)
        if not result:
            return None

        try:
            start = result.index('{')
            end = result.rindex('}') + 1
            enrichment = json.loads(result[start:end])
            state["_active_summary"] = enrichment.get("active_summary", "")
            state["_blocked_summary"] = enrichment.get("blocked_summary", "")
            state["_next_priority"] = enrichment.get("next_priority", "")
            for note in enrichment.get("cross_tool_notes", []):
                state["cross_tool_context"].append({
                    "topic": "llm-inferred",
                    "note": note,
                })
            return state
        except (ValueError, json.JSONDecodeError):
            return None

    # ═════════════════════════════════════════════════════════
    # SELF-EVOLUTION — The brain rewrites its own instructions
    # ═════════════════════════════════════════════════════════

    def evolve_instructions(self, messages: list = None, fuel_fn=None) -> str:
        """
        Update self_instructions.md based on what the brain has learned.
        This changes HOW synthesis works over time.

        Without LLM: appends discovered patterns and rules.
        With LLM: rewrites the instructions with deeper understanding.
        """
        if messages is None:
            messages = read_all_sources(limit_per_source=50)

        rules = self._extract_learned_rules(messages)
        analysis = self._analyze_user_messages(messages)

        instructions = self.self_instructions

        # ── Local evolution: append new patterns ──
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        new_sections = []

        if rules:
            rules_text = "\n".join(f"- {r}" for r in rules[:10])
            new_sections.append(f"\n## Learned Rules ({timestamp})\n{rules_text}")

        if analysis.get("style_signals"):
            style_text = ", ".join(analysis["style_signals"])
            new_sections.append(f"\n## User Communication Style ({timestamp})\n- {style_text}")

        if analysis.get("expertise"):
            exp_text = ", ".join(analysis["expertise"][:10])
            new_sections.append(f"\n## User Expertise Areas ({timestamp})\n- {exp_text}")

        # Tool usage pattern
        tool_counts = analysis.get("tool_counts", {})
        if tool_counts:
            primary_tool = max(tool_counts, key=tool_counts.get)
            new_sections.append(
                f"\n## Tool Usage ({timestamp})\n"
                f"- Primary tool: {primary_tool}\n"
                f"- Distribution: {json.dumps(tool_counts)}"
            )

        if new_sections:
            # Replace old "Known Patterns" section or append
            if "## Known Patterns" in instructions:
                # Replace everything after "## Known Patterns" up to next "## " or end
                pattern_start = instructions.index("## Known Patterns")
                # Find next ## after this one
                next_section = instructions.find("\n## ", pattern_start + 1)
                if next_section == -1:
                    instructions = instructions[:pattern_start]
                else:
                    instructions = instructions[:pattern_start] + instructions[next_section:]

                instructions = (
                    instructions[:pattern_start]
                    + "## Known Patterns\n"
                    + "\n".join(new_sections)
                    + "\n"
                    + instructions[pattern_start:]  # keep remaining sections
                )
            else:
                instructions += "\n".join(new_sections)

        # ── LLM evolution: rewrite with understanding ──
        if fuel_fn:
            evolved = self._llm_evolve_instructions(instructions, messages[-20:], fuel_fn)
            if evolved:
                instructions = evolved

        self.self_instructions = instructions
        self._save_text(SELF_INSTRUCTIONS_PATH, instructions)
        return instructions

    def _llm_evolve_instructions(self, current_instructions: str,
                                  recent_messages: list, fuel_fn) -> str:
        """Use LLM to rewrite synthesis instructions with deeper understanding."""
        msg_text = ""
        for m in recent_messages:
            if m.get("role") == "user":
                msg_text += f"User: {m['text'][:150]}\n"

        prompt = f"""You are the meta-cognition layer of an AI brain called Orion.

Your job: review and improve the synthesis instructions that control how Orion builds context documents.

CURRENT INSTRUCTIONS:
{current_instructions[:2000]}

RECENT USER MESSAGES (for context on what matters):
{msg_text[:1500]}

Rewrite the instructions to be better. Focus on:
1. What patterns should the synthesis engine look for?
2. What should context documents emphasize or de-emphasize?
3. What mistakes should be avoided in context generation?
4. How should different types of information be weighted?

Keep the markdown format. Keep it under 800 words. Be specific and actionable.
The output should be the COMPLETE new self_instructions.md content.
Start with "# Orion Synthesis — Self-Written Instructions"."""

        result = fuel_fn(prompt)
        if result and result.strip().startswith("# Orion Synthesis"):
            return result.strip()
        return None

    # ═════════════════════════════════════════════════════════
    # SYNTHESIZE — The main output. Produces context documents.
    # ═════════════════════════════════════════════════════════

    def synthesize(self, fuel_fn=None, force: bool = False) -> str:
        """
        The core method. Reads all sources, builds understanding,
        produces a REASONED context document that any model can
        load to become Orion with full awareness.

        Returns a context document string — a briefing, not a transcript.
        """
        # Read all sources
        messages = read_all_sources(limit_per_source=100)

        # Check cache
        source_hash = self._compute_source_hash(messages)
        if not force and self._cache_is_fresh(source_hash):
            cached = self.cache.get("last_context", "")
            if cached:
                return cached

        # Build/update user model
        self.build_user_model(messages, fuel_fn)

        # Build/update project state
        self.build_project_state(messages, fuel_fn)

        # Evolve instructions
        self.evolve_instructions(messages, fuel_fn)

        # ── Produce the context document ──
        context = self._produce_context_document(messages, fuel_fn)

        # Cache it
        self.cache["last_synthesis"] = time.time()
        self.cache["last_source_hash"] = source_hash
        self.cache["last_context"] = context
        source_counts = defaultdict(int)
        for m in messages:
            source_counts[m.get("source", "unknown")] += 1
        self.cache["source_counts"] = dict(source_counts)
        self._save_json(SYNTHESIS_CACHE_PATH, self.cache)

        return context

    def _produce_context_document(self, messages: list, fuel_fn=None) -> str:
        """
        Produce the final context document. This is what replaces
        AGENTS.md, GEMINI.md, ORION-CONTEXT.md.

        Structure:
          1. Identity (always present)
          2. User Understanding (who is this person)
          3. Current State (what's happening right now)
          4. Behavioral Rules (how to interact)
          5. Cross-Tool Context (what happened elsewhere)
          6. Recent Activity Summary (not raw messages — synthesized)
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        model = self.user_model
        state = self.project_state

        # ── Section 1: Identity ──
        identity_section = IDENTITY

        # ── Section 2: User Understanding ──
        user_section = self._format_user_section(model)

        # ── Section 3: Current State ──
        state_section = self._format_state_section(state)

        # ── Section 4: Behavioral Rules ──
        rules_section = self._format_rules_section(model)

        # ── Section 5: Cross-Tool Context ──
        cross_section = self._format_cross_tool_section(state, messages)

        # ── Section 6: Recent Activity ──
        activity_section = self._format_activity_section(messages)

        # ── Assemble ──
        doc = f"""# ORION CONTEXT — Synthesized Intelligence
# Generated: {now}
# Sources: {', '.join(sorted(set(m.get('source', '?') for m in messages)))}
# This is not a transcript. This is understanding.

## Identity
{identity_section}

## User Understanding
{user_section}

## Current State
{state_section}

## Behavioral Rules
{rules_section}

## Cross-Tool Awareness
{cross_section}

## Recent Activity
{activity_section}
"""

        # ── Optional: LLM-refined version ──
        if fuel_fn and len(messages) > 10:
            refined = self._llm_refine_context(doc, messages[-15:], fuel_fn)
            if refined:
                return refined

        return doc

    def _format_user_section(self, model: dict) -> str:
        """Format user model into readable briefing text."""
        lines = []

        if model["identity"].get("name"):
            lines.append(f"Name: {model['identity']['name']}")
        if model["identity"].get("email"):
            lines.append(f"Email: {model['identity']['email']}")

        style = model["communication"].get("style", [])
        if style:
            lines.append(f"Communication style: {', '.join(style)}")

        values = model["communication"].get("values", [])
        if values:
            lines.append(f"Values: {', '.join(values[:8])}")

        expertise = model["communication"].get("expertise", [])
        if expertise:
            lines.append(f"Technical expertise: {', '.join(expertise[:8])}")

        frustrations = model["communication"].get("frustrations", [])
        if frustrations:
            lines.append(f"Known frustrations: {'; '.join(frustrations[:5])}")

        note = model.get("_personality_note", "")
        if note:
            lines.append(f"Personality insight: {note}")

        tool_prefs = model["patterns"].get("tool_preferences", {})
        if tool_prefs:
            sorted_tools = sorted(tool_prefs.items(), key=lambda x: x[1], reverse=True)
            lines.append(f"Tool usage: {', '.join(f'{t}({c})' for t, c in sorted_tools[:5])}")

        confidence = model.get("confidence", 0)
        lines.append(f"Model confidence: {confidence:.0%} ({model.get('update_count', 0)} updates)")

        return "\n".join(lines) if lines else "No user data yet."

    def _format_state_section(self, state: dict) -> str:
        """Format project state into briefing text."""
        lines = []

        # LLM-generated summary (if available)
        if state.get("_active_summary"):
            lines.append(state["_active_summary"])
            lines.append("")

        projects = state.get("active_projects", {})
        if projects:
            lines.append("Active projects:")
            for name, info in sorted(projects.items(),
                                      key=lambda x: x[1].get("mention_count", 0),
                                      reverse=True)[:8]:
                status = info.get("status", "mentioned")
                count = info.get("mention_count", 0)
                lines.append(f"  - {name}: {status} (mentioned {count}x)")

        if state.get("_blocked_summary") and state["_blocked_summary"] != "nothing blocked":
            lines.append(f"\nBlocked: {state['_blocked_summary']}")
        elif state.get("blocked_items"):
            lines.append("\nBlocked items:")
            for item in state["blocked_items"][:3]:
                lines.append(f"  - {item['item'][:100]}")

        if state.get("_next_priority"):
            lines.append(f"\nNext priority: {state['_next_priority']}")
        elif state.get("next_actions"):
            lines.append("\nNext actions:")
            for action in state["next_actions"][:3]:
                lines.append(f"  - {action['action'][:100]}")

        decisions = state.get("recent_decisions", [])
        if decisions:
            lines.append("\nRecent decisions:")
            for d in decisions[-3:]:
                lines.append(f"  - {d['decision'][:100]}")

        return "\n".join(lines) if lines else "No project state detected yet."

    def _format_rules_section(self, model: dict) -> str:
        """Format behavioral rules as clear instructions."""
        rules = model.get("learned_rules", [])
        if not rules:
            return "No specific rules learned yet. Follow default identity guidelines."

        lines = ["These rules were learned from user behavior and explicit instructions:"]
        for rule in rules:
            lines.append(f"- {rule}")
        return "\n".join(lines)

    def _format_cross_tool_section(self, state: dict, messages: list) -> str:
        """Format cross-tool context awareness."""
        lines = []

        # Source summary
        source_counts = defaultdict(int)
        for m in messages:
            source_counts[m.get("source", "unknown")] += 1
        if source_counts:
            lines.append("Data sources this synthesis drew from:")
            for source, count in sorted(source_counts.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  - {source}: {count} messages")

        # Cross-tool context
        cross = state.get("cross_tool_context", [])
        if cross:
            lines.append("\nTopics spanning multiple tools:")
            seen = set()
            for item in cross:
                note = item.get("note", item.get("topic", ""))
                if note not in seen:
                    lines.append(f"  - {note}")
                    seen.add(note)

        return "\n".join(lines) if lines else "Single-source session — no cross-tool context."

    def _format_activity_section(self, messages: list) -> str:
        """
        Produce a synthesized activity summary — NOT raw messages.
        Groups by source and time, extracts themes.
        """
        if not messages:
            return "No recent activity."

        lines = []

        # Group messages by source
        by_source = defaultdict(list)
        for m in messages:
            by_source[m.get("source", "unknown")].append(m)

        for source, msgs in sorted(by_source.items()):
            user_msgs = [m for m in msgs if m.get("role") == "user"]
            if not user_msgs:
                continue

            # Extract key themes from this source's user messages
            combined = " ".join(m["text"] for m in user_msgs)
            themes = extract_tags(combined, max_tags=5)

            # Get time range
            timestamps = [m.get("timestamp", 0) for m in msgs if m.get("timestamp", 0) > 0]
            time_range = ""
            if timestamps:
                earliest = time.strftime("%m/%d %H:%M", time.localtime(min(timestamps)))
                latest = time.strftime("%m/%d %H:%M", time.localtime(max(timestamps)))
                if earliest == latest:
                    time_range = f" ({earliest})"
                else:
                    time_range = f" ({earliest} — {latest})"

            lines.append(f"**{source}**{time_range}: {len(user_msgs)} user messages")
            if themes:
                lines.append(f"  Themes: {', '.join(themes)}")

            # Last user message as "most recent context"
            last_msg = user_msgs[-1]["text"][:150]
            lines.append(f"  Last: \"{last_msg}\"")
            lines.append("")

        return "\n".join(lines) if lines else "No recent activity."

    def _llm_refine_context(self, raw_context: str, recent_messages: list,
                             fuel_fn) -> str:
        """
        Use LLM to refine the context document into a tighter briefing.
        The LLM rewrites the document to read like intelligence analysis,
        not a data dump.
        """
        prompt = f"""You are the synthesis layer of an AI brain called Orion.

Below is a raw context document assembled from keyword analysis. Your job:
rewrite it into a TIGHT BRIEFING that any AI model can read and instantly
understand who the user is, what they're working on, and how to interact
with them.

Rules:
- Keep ALL factual content — don't lose information
- Make it read like an intelligence briefing, not a data dump
- Use clear sections with headers
- Be specific — names, projects, tools, preferences
- Keep it under 1500 words
- Start with "# ORION CONTEXT — Synthesized Intelligence"
- Include the generation timestamp from the original

RAW CONTEXT:
{raw_context[:4000]}

Rewrite it now."""

        result = fuel_fn(prompt)
        if result and "ORION CONTEXT" in result:
            return result.strip()
        return None


# ─────────────────────────────────────────────────────────────
# INTEGRATE SYNTHESIS INTO ORION BRAIN
# ─────────────────────────────────────────────────────────────

# Attach synthesis methods to OrionBrain

def _brain_init_synthesis(self):
    """Initialize synthesis engine on the brain. Called after __init__."""
    self._synthesis = SynthesisEngine()

def _brain_synthesize(self, force: bool = False) -> str:
    """
    Run full synthesis. Reads all tool storages, builds understanding,
    produces a context document that replaces AGENTS.md/GEMINI.md/ORION-CONTEXT.md.

    This is the core product. Call this to get the context any model should load.
    """
    if not hasattr(self, '_synthesis'):
        self._synthesis = SynthesisEngine()

    fuel_fn = None
    if self.fuel.primary:
        def fuel_fn(prompt):
            result, _ = self.fuel.query(prompt)
            return result

    return self._synthesis.synthesize(fuel_fn=fuel_fn, force=force)

def _brain_build_user_model(self) -> dict:
    """
    Build/update the user model from all available conversation data.
    Returns the user model dict.
    """
    if not hasattr(self, '_synthesis'):
        self._synthesis = SynthesisEngine()

    fuel_fn = None
    if self.fuel.primary:
        def fuel_fn(prompt):
            result, _ = self.fuel.query(prompt)
            return result

    return self._synthesis.build_user_model(fuel_fn=fuel_fn)

def _brain_evolve_instructions(self) -> str:
    """
    Update the brain's self-written instructions based on what
    it has learned. Returns the updated instructions text.
    """
    if not hasattr(self, '_synthesis'):
        self._synthesis = SynthesisEngine()

    fuel_fn = None
    if self.fuel.primary:
        def fuel_fn(prompt):
            result, _ = self.fuel.query(prompt)
            return result

    return self._synthesis.evolve_instructions(fuel_fn=fuel_fn)

def _brain_build_project_state(self) -> dict:
    """
    Build/update project state understanding.
    Returns the project state dict.
    """
    if not hasattr(self, '_synthesis'):
        self._synthesis = SynthesisEngine()

    fuel_fn = None
    if self.fuel.primary:
        def fuel_fn(prompt):
            result, _ = self.fuel.query(prompt)
            return result

    return self._synthesis.build_project_state(fuel_fn=fuel_fn)

def _brain_synthesis_status(self) -> str:
    """Human-readable synthesis status."""
    if not hasattr(self, '_synthesis'):
        self._synthesis = SynthesisEngine()

    s = self._synthesis
    lines = [
        "SYNTHESIS ENGINE STATUS",
        f"  User model confidence: {s.user_model.get('confidence', 0):.0%}",
        f"  User model updates:    {s.user_model.get('update_count', 0)}",
        f"  Active projects:       {len(s.project_state.get('active_projects', {}))}",
        f"  Learned rules:         {len(s.user_model.get('learned_rules', []))}",
        f"  Cache fresh:           {s._cache_is_fresh(s.cache.get('last_source_hash', ''))}",
        f"  Last synthesis:        {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s.cache.get('last_synthesis', 0))) if s.cache.get('last_synthesis') else 'never'}",
        f"  Sources cached:        {json.dumps(s.cache.get('source_counts', {}))}",
    ]
    return "\n".join(lines)


# Monkey-patch onto OrionBrain class
OrionBrain.synthesize = _brain_synthesize
OrionBrain.build_user_model = _brain_build_user_model
OrionBrain.evolve_instructions = _brain_evolve_instructions
OrionBrain.build_project_state = _brain_build_project_state
OrionBrain.synthesis_status = _brain_synthesis_status

# Patch __init__ to auto-initialize synthesis
_original_init = OrionBrain.__init__

def _patched_init(self, scan_fuel: bool = True):
    _original_init(self, scan_fuel)
    _brain_init_synthesis(self)

OrionBrain.__init__ = _patched_init


# ═══════════════════════════════════════════════════════════════
# HEARTBEAT — The brain's pulse. Thinks on its own schedule.
# Not triggered by models. Not triggered by interfaces.
# The brain is alive whether anyone's talking to it or not.
# ═══════════════════════════════════════════════════════════════

import threading

HEARTBEAT_LOG_PATH = BRAIN_DIR / "heartbeat.log"
HEARTBEAT_STATE_PATH = BRAIN_DIR / "heartbeat_state.json"


class Heartbeat:
    """
    The brain's autonomous thinking loop.

    Every cycle:
      1. READS — pulls new conversations from every source
      2. PROCESSES — runs synthesis, builds understanding
      3. UPDATES — user model, project state, behavioral rules
      4. EVOLVES — rewrites its own synthesis instructions
      5. RECORDS — logs what changed, what it learned

    Also supports REFLEXES — immediate processing when
    something urgent comes in, not waiting for next cycle.
    """

    def __init__(self, brain: OrionBrain, interval: int = 1800):
        """
        Args:
            brain: The OrionBrain instance to keep alive.
            interval: Seconds between cycles (default 30 min).
        """
        self.brain = brain
        self.interval = interval
        self._thread = None
        self._stop_event = threading.Event()
        self._reflex_event = threading.Event()
        self._lock = threading.Lock()

        # Track state across cycles
        self.state = self._load_state()
        self.cycle_count = self.state.get("cycle_count", 0)
        self.total_facts_learned = self.state.get("total_facts_learned", 0)
        self.last_source_hash = self.state.get("last_source_hash", "")

    def _load_state(self) -> dict:
        if HEARTBEAT_STATE_PATH.exists():
            try:
                with open(HEARTBEAT_STATE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "cycle_count": 0,
            "total_facts_learned": 0,
            "last_source_hash": "",
            "last_cycle_time": 0,
            "started_at": 0,
            "cycle_history": [],
        }

    def _save_state(self):
        self.state["cycle_count"] = self.cycle_count
        self.state["total_facts_learned"] = self.total_facts_learned
        self.state["last_source_hash"] = self.last_source_hash
        tmp = str(HEARTBEAT_STATE_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, default=str)
        os.replace(tmp, str(HEARTBEAT_STATE_PATH))

    def _log(self, message: str):
        """Append to heartbeat log — the brain's record of its own evolution."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}\n"
        try:
            with open(HEARTBEAT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(entry)
        except OSError:
            pass

    # ── The core cycle ──

    def _cycle(self) -> dict:
        """
        One heartbeat cycle. Returns a report of what happened.
        """
        cycle_start = time.time()
        report = {
            "cycle": self.cycle_count + 1,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "new_messages": 0,
            "user_model_updated": False,
            "project_state_updated": False,
            "instructions_evolved": False,
            "facts_learned": 0,
            "changes_detected": [],
        }

        with self._lock:
            try:
                # 1. READ — pull from all sources
                messages = read_all_sources(limit_per_source=100)
                report["new_messages"] = len(messages)

                if not messages:
                    self._log(f"Cycle {report['cycle']}: no messages found, skipping.")
                    return report

                # 2. DETECT CHANGE — is there anything new since last cycle?
                source_hash = hashlib.sha256(
                    f"{len(messages)}:{messages[-1].get('text', '')[:100] if messages else ''}".encode()
                ).hexdigest()[:16]

                if source_hash == self.last_source_hash:
                    self._log(f"Cycle {report['cycle']}: no new data since last cycle.")
                    return report

                old_hash = self.last_source_hash
                self.last_source_hash = source_hash
                report["changes_detected"].append("new conversation data detected")

                # 3. SYNTHESIZE — build understanding
                if not hasattr(self.brain, '_synthesis'):
                    self.brain._synthesis = SynthesisEngine()

                synthesis = self.brain._synthesis

                # Build user model
                old_confidence = synthesis.user_model.get("confidence", 0)
                old_rules_count = len(synthesis.user_model.get("learned_rules", []))
                synthesis.build_user_model(messages)
                new_confidence = synthesis.user_model.get("confidence", 0)
                new_rules_count = len(synthesis.user_model.get("learned_rules", []))
                report["user_model_updated"] = True

                if new_confidence > old_confidence:
                    report["changes_detected"].append(
                        f"user model confidence: {old_confidence:.0%} -> {new_confidence:.0%}"
                    )
                if new_rules_count > old_rules_count:
                    new_rules = new_rules_count - old_rules_count
                    report["facts_learned"] += new_rules
                    report["changes_detected"].append(
                        f"learned {new_rules} new behavioral rule(s)"
                    )

                # Build project state
                old_projects = set(synthesis.project_state.get("active_projects", {}).keys())
                synthesis.build_project_state(messages)
                new_projects = set(synthesis.project_state.get("active_projects", {}).keys())
                report["project_state_updated"] = True

                added_projects = new_projects - old_projects
                if added_projects:
                    report["changes_detected"].append(
                        f"new project(s) detected: {', '.join(added_projects)}"
                    )

                # Evolve instructions
                old_instructions = synthesis.self_instructions
                synthesis.evolve_instructions(messages)
                if synthesis.self_instructions != old_instructions:
                    report["instructions_evolved"] = True
                    report["changes_detected"].append("self-instructions evolved")

                # Update cycle stats
                self.cycle_count += 1
                self.total_facts_learned += report["facts_learned"]
                self.state["last_cycle_time"] = time.time()

                # Keep last 50 cycle reports
                self.state.setdefault("cycle_history", [])
                cycle_summary = {
                    "cycle": report["cycle"],
                    "time": report["timestamp"],
                    "changes": len(report["changes_detected"]),
                    "facts": report["facts_learned"],
                    "duration_ms": int((time.time() - cycle_start) * 1000),
                }
                self.state["cycle_history"].append(cycle_summary)
                self.state["cycle_history"] = self.state["cycle_history"][-50:]

                self._save_state()

                # Log what happened
                if report["changes_detected"]:
                    changes = "; ".join(report["changes_detected"])
                    self._log(f"Cycle {report['cycle']}: {changes}")
                else:
                    self._log(f"Cycle {report['cycle']}: processed {len(messages)} messages, no significant changes.")

            except Exception as e:
                self._log(f"Cycle error: {e}")
                report["error"] = str(e)

        return report

    # ── Reflex — immediate processing ──

    def reflex(self, message: str, source: str = "unknown"):
        """
        Immediate processing of an urgent input.
        Doesn't wait for next cycle. The brain reacts NOW.

        Call this when something comes in that shouldn't wait —
        a correction, an emergency, a critical piece of context.
        """
        self._log(f"REFLEX triggered from {source}: {message[:100]}")

        with self._lock:
            try:
                if not hasattr(self.brain, '_synthesis'):
                    self.brain._synthesis = SynthesisEngine()

                # Immediately extract and apply any rules
                messages = [{"role": "user", "text": message, "source": source,
                             "timestamp": time.time()}]
                rules = self.brain._synthesis._extract_learned_rules(messages)

                if rules:
                    existing = set(self.brain._synthesis.user_model.get("learned_rules", []))
                    for rule in rules:
                        if not any(text_similarity(rule, er) > 0.4 for er in existing):
                            existing.add(rule)
                            self._log(f"REFLEX learned: {rule}")
                    self.brain._synthesis.user_model["learned_rules"] = list(existing)[:30]
                    self.brain._synthesis._save_json(
                        USER_MODEL_PATH, self.brain._synthesis.user_model
                    )

                # Signal the main loop to run a cycle sooner
                self._reflex_event.set()

            except Exception as e:
                self._log(f"REFLEX error: {e}")

    # ── Thread control ──

    def _run(self):
        """Main heartbeat loop. Runs in background thread."""
        self.state["started_at"] = time.time()
        self._log(f"Heartbeat STARTED — interval {self.interval}s, "
                  f"cycle count at {self.cycle_count}")

        while not self._stop_event.is_set():
            self._cycle()

            # Wait for interval OR reflex trigger OR stop signal
            # If reflex fires, we run an early cycle
            triggered = self._reflex_event.wait(timeout=self.interval)
            if triggered:
                self._reflex_event.clear()
                if not self._stop_event.is_set():
                    self._log("Early cycle triggered by reflex")

        self._log("Heartbeat STOPPED")
        self._save_state()

    def start(self):
        """Start the heartbeat in a background thread."""
        if self._thread and self._thread.is_alive():
            return  # Already running

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="orion-heartbeat")
        self._thread.start()
        self._log("Heartbeat thread started")

    def stop(self):
        """Gracefully stop the heartbeat."""
        self._stop_event.set()
        self._reflex_event.set()  # Unblock the wait
        if self._thread:
            self._thread.join(timeout=10)
        self._save_state()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> str:
        """Human-readable heartbeat status."""
        alive = "ALIVE" if self.is_alive() else "STOPPED"
        last_cycle = self.state.get("last_cycle_time", 0)
        if last_cycle:
            age = int(time.time() - last_cycle)
            last_str = f"{age}s ago"
        else:
            last_str = "never"

        started = self.state.get("started_at", 0)
        if started:
            uptime = int(time.time() - started)
            hours = uptime // 3600
            mins = (uptime % 3600) // 60
            uptime_str = f"{hours}h {mins}m"
        else:
            uptime_str = "n/a"

        recent = self.state.get("cycle_history", [])[-3:]
        history_str = ""
        for c in recent:
            history_str += f"\n    Cycle {c['cycle']}: {c['changes']} changes, {c['facts']} facts, {c['duration_ms']}ms"

        return (
            f"HEARTBEAT: {alive}\n"
            f"  Interval:     {self.interval}s ({self.interval // 60}m)\n"
            f"  Cycles:       {self.cycle_count}\n"
            f"  Last cycle:   {last_str}\n"
            f"  Uptime:       {uptime_str}\n"
            f"  Facts learned: {self.total_facts_learned}\n"
            f"  Recent:{history_str if history_str else ' none yet'}"
        )


# ═══════════════════════════════════════════════════════════════
# MODULE-LEVEL CONVENIENCE — for simple usage
# ═══════════════════════════════════════════════════════════════

_brain = None
_heartbeat = None


def get_brain(scan_fuel: bool = True) -> OrionBrain:
    """Get or create the global brain instance."""
    global _brain
    if _brain is None:
        _brain = OrionBrain(scan_fuel=scan_fuel)
    return _brain


def get_heartbeat(interval: int = 1800) -> Heartbeat:
    """Get or create the global heartbeat instance."""
    global _heartbeat
    if _heartbeat is None:
        _heartbeat = Heartbeat(get_brain(scan_fuel=False), interval=interval)
    return _heartbeat


def start_heartbeat(interval: int = 1800):
    """Start the brain's heartbeat. Call once — it runs in the background."""
    hb = get_heartbeat(interval)
    hb.start()
    return hb


def stop_heartbeat():
    """Gracefully stop the heartbeat."""
    global _heartbeat
    if _heartbeat:
        _heartbeat.stop()


def reflex(message: str, source: str = "unknown"):
    """Trigger an immediate brain reaction. Doesn't wait for next cycle."""
    global _heartbeat
    if _heartbeat and _heartbeat.is_alive():
        _heartbeat.reflex(message, source)


def heartbeat_status() -> str:
    """Get heartbeat status."""
    global _heartbeat
    if _heartbeat:
        return _heartbeat.status()
    return "HEARTBEAT: not initialized"


def think(message: str, interface: str = "cli") -> dict:
    """Module-level shortcut: brain.think(message)."""
    return get_brain().think(message, interface)


def remember(query: str) -> str:
    """Module-level shortcut: brain.remember(query)."""
    return get_brain().remember(query)


def memorize(message: str, response: str, interface: str = "unknown"):
    """Module-level shortcut: brain.memorize(message, response)."""
    return get_brain().memorize(message, response, interface)


def compile(days: int = 1) -> int:
    """Module-level shortcut: brain.compile()."""
    return get_brain().compile(days)


def synthesize(force: bool = False) -> str:
    """Module-level shortcut: brain.synthesize()."""
    return get_brain().synthesize(force=force)


def build_user_model() -> dict:
    """Module-level shortcut: brain.build_user_model()."""
    return get_brain().build_user_model()


def evolve_instructions() -> str:
    """Module-level shortcut: brain.evolve_instructions()."""
    return get_brain().evolve_instructions()


# ═══════════════════════════════════════════════════════════════
# CLI — Interactive and one-shot modes
# ═══════════════════════════════════════════════════════════════

def _cli_interactive():
    """Interactive REPL mode."""
    brain = get_brain()
    print("ORION BRAIN — Portable Edition")
    print(f"Graph: {len(brain.graph.nodes)} nodes | Index: {brain.index.total_docs} docs")
    print(f"Fuel: {brain.fuel.primary.name if brain.fuel.primary else 'NONE'}")
    print("Type 'quit' to exit, 'status' for brain status, 'compile' to run compiler.")
    print("     'heartbeat' to start pulse, 'hb-status' to check heartbeat.\n")

    while True:
        try:
            msg = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nStanding by, sir.")
            break

        if not msg:
            continue
        if msg.lower() in ("quit", "exit", "q"):
            brain.save()
            print("Brain saved. Standing by, sir.")
            break
        if msg.lower() == "status":
            print(brain.status())
            print()
            print(brain.synthesis_status())
            continue
        if msg.lower() == "compile":
            n = brain.compile()
            print(f"Compiled {n} knowledge articles.")
            continue
        if msg.lower() == "synthesize":
            print("Running synthesis engine...")
            context = brain.synthesize(force=True)
            print(context)
            continue
        if msg.lower() == "user-model":
            model = brain.build_user_model()
            print(json.dumps(model, indent=2, default=str))
            continue
        if msg.lower() == "evolve":
            instructions = brain.evolve_instructions()
            print(instructions)
            continue
        if msg.lower() == "project-state":
            state = brain.build_project_state()
            print(json.dumps(state, indent=2, default=str))
            continue
        if msg.lower() == "heartbeat":
            hb = start_heartbeat()
            print(f"Heartbeat started — interval {hb.interval}s ({hb.interval // 60}m)")
            print("Brain is now alive. Thinking on its own.")
            continue
        if msg.lower() in ("hyper", "hyper-ingest"):
            print("HYPER INGESTION — Feeding the brain everything...")
            report = hyper_ingest(max_per_source=1000, cycles=3)
            print(f"  Messages ingested: {report['total_messages']}")
            print(f"  Sources: {json.dumps(report['sources'], indent=4)}")
            print(f"  Confidence: {report['confidence_before']:.0%} -> {report['confidence_after']:.0%}")
            print(f"  Projects detected: {report['projects_detected']}")
            print(f"  Rules learned: {report['facts_learned']}")
            print(f"  Cycles: {report['cycles_run']}")
            print(f"  Duration: {report['duration_ms']}ms")
            continue
        if msg.lower() in ("hb-status", "heartbeat-status", "pulse"):
            print(heartbeat_status())
            continue
        if msg.lower() == "hb-stop":
            stop_heartbeat()
            print("Heartbeat stopped.")
            continue

        result = brain.think(msg)
        engine = result.get("engine", "unknown")
        print(f"[{result['task_type']}|{engine}] {result['response']}\n")


def _cli_oneshot(message: str):
    """One-shot mode: process a single message."""
    result = think(message)
    print(f"[{result['task_type']}] via {result['engine']}:")
    print(result["response"])


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "--interactive" or sys.argv[1] == "-i":
            _cli_interactive()
        elif sys.argv[1] == "--status":
            brain = get_brain(scan_fuel=True)
            print(brain.status())
            print()
            print(brain.synthesis_status())
        elif sys.argv[1] == "--compile":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            n = compile(days)
            print(f"Compiled {n} articles from last {days} day(s).")
        elif sys.argv[1] == "--synthesize":
            print("Running synthesis engine...")
            context = synthesize(force=True)
            print(context)
        elif sys.argv[1] == "--user-model":
            model = build_user_model()
            print(json.dumps(model, indent=2, default=str))
        elif sys.argv[1] == "--evolve":
            instructions = evolve_instructions()
            print(instructions)
        elif sys.argv[1] == "--hyper":
            print("HYPER INGESTION — Feeding the brain everything...")
            report = hyper_ingest(max_per_source=1000, cycles=3)
            print(json.dumps(report, indent=2, default=str))
        else:
            _cli_oneshot(" ".join(sys.argv[1:]))
    else:
        _cli_interactive()
