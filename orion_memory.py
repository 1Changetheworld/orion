#!/usr/bin/env python3
"""
ORION Memory System v2 — Knowledge Compiler + Graph Memory + Vector Search
Absorbed from: claude-memory-compiler (Karpathy pattern), cersei (graph recall), Qdrant (vector)

Three memory layers:
1. Graph Memory — microsecond tag-indexed recall for known entities/patterns
2. Vector Memory — semantic search via Qdrant for fuzzy/contextual queries
3. Knowledge Compiler — distills conversations into structured knowledge articles

The combination: fast deterministic recall + deep semantic search + continuous learning.
"""
import json
import time
import hashlib
import os
import urllib.request
from collections import defaultdict
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct
    QDRANT_AVAILABLE = True
except Exception:
    # The vector layer is OPTIONAL. Offline/local installs — and any host
    # without qdrant — must still run the brain. Graph memory is the core;
    # vectors only enrich recall. Degrade to graph-only instead of failing.
    QdrantClient = None
    PointStruct = None
    QDRANT_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
OLLAMA_URL = "http://localhost:11434"
KNOWLEDGE_DIR = os.path.expanduser("~/.orion/brain/knowledge")
CONVERSATION_LOG = os.path.expanduser("~/.orion/brain/conversations")

os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
os.makedirs(CONVERSATION_LOG, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# LAYER 1: GRAPH MEMORY — Microsecond indexed recall
# Absorbed from: cersei/Grafeo graph memory pattern
# 77,000x faster than LLM-based recall for known entities
# ═══════════════════════════════════════════════════════════════

class GraphMemory:
    """Fast tag-indexed memory. No LLM needed for recall."""

    def __init__(self):
        self.nodes = {}           # id -> {content, type, confidence, tags, created}
        self.tag_index = defaultdict(set)  # tag -> set of node ids
        self.type_index = defaultdict(set) # type -> set of node ids
        self._next_id = 0

    def store(self, content, node_type="fact", confidence=1.0, tags=None):
        """Store a memory node with tags for instant recall."""
        node_id = self._next_id
        self._next_id += 1
        node = {
            "content": content,
            "type": node_type,
            "confidence": confidence,
            "tags": set(tags or []),
            "created": time.time(),
        }
        self.nodes[node_id] = node
        self.type_index[node_type].add(node_id)
        for tag in node["tags"]:
            self.tag_index[tag.lower()].add(node_id)
        return node_id

    def recall(self, query=None, tags=None, node_type=None, limit=5):
        """Recall memories by tag match + text search. Microseconds."""
        candidates = set(self.nodes.keys())

        # Filter by type
        if node_type:
            candidates &= self.type_index.get(node_type, set())

        # Filter by tags (intersection — all tags must match)
        if tags:
            for tag in tags:
                candidates &= self.tag_index.get(tag.lower(), set())

        # Score by text relevance if query provided
        if query:
            query_words = set(query.lower().split())
            scored = []
            for nid in candidates:
                content_words = set(self.nodes[nid]["content"].lower().split())
                overlap = len(query_words & content_words)
                if overlap > 0 or not tags:  # if tags matched, include even without text match
                    scored.append((overlap, self.nodes[nid]["confidence"], nid))
            scored.sort(reverse=True)
            return [self.nodes[nid] for _, _, nid in scored[:limit]]
        else:
            results = [self.nodes[nid] for nid in list(candidates)[:limit]]
            return results

    def tag(self, node_id, new_tag):
        """Add a tag to an existing node."""
        if node_id in self.nodes:
            self.nodes[node_id]["tags"].add(new_tag)
            self.tag_index[new_tag.lower()].add(node_id)

    def save(self, filepath):
        """Persist graph to disk."""
        data = {
            "next_id": self._next_id,
            "nodes": {
                str(k): {**v, "tags": list(v["tags"])}
                for k, v in self.nodes.items()
            }
        }
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            # Storage canary. 2026-05-10 22:19 incident: macOS TCC denied
            # /usr/bin/python3 (launchd-spawned) write access to /Volumes/
            # AtlasVault. Brain HTTP-500'd every /ask for 48h. Self-heal
            # couldn't see it because webhook didn't crash. Publishing
            # brain.storage.degraded lets immune/claustrum/reach react.
            try:
                from orion_substrate import publish as _publish
                _publish("brain.storage.degraded", {
                    "path": str(filepath),
                    "error": f"{type(e).__name__}: {e}",
                    "errno": getattr(e, "errno", None),
                })
            except Exception:
                pass  # substrate optional; never lose the original error
            raise

    def load(self, filepath):
        """Load graph from disk."""
        if not os.path.exists(filepath):
            return
        with open(filepath) as f:
            data = json.load(f)
        self._next_id = data.get("next_id", 0)
        for k, v in data.get("nodes", {}).items():
            nid = int(k)
            v["tags"] = set(v["tags"])
            self.nodes[nid] = v
            self.type_index[v["type"]].add(nid)
            for tag in v["tags"]:
                self.tag_index[tag.lower()].add(nid)


# ═══════════════════════════════════════════════════════════════
# LAYER 2: VECTOR MEMORY — Semantic search via Qdrant
# Direct calls, no Mem0 wrapper. Our code.
# ═══════════════════════════════════════════════════════════════

_qdrant = None

def get_qdrant():
    global _qdrant
    if not QDRANT_AVAILABLE:
        return None
    if _qdrant is None:
        try:
            _qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        except Exception:
            return None
    return _qdrant


def embed(text):
    """Get vector embedding via Ollama nomic-embed-text."""
    payload = json.dumps({"model": "nomic-embed-text", "prompt": text[:4000]}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["embedding"]


def vector_search(query, collections=None, limit=5):
    """Search Qdrant vector memory. Returns context string with fencing.

    Returns "" when the vector layer is unavailable (offline/local installs
    without qdrant, or qdrant server down); graph memory still answers."""
    if not QDRANT_AVAILABLE:
        return ""
    if collections is None:
        collections = ["orion_brain", "server_knowledge"]

    try:
        vector = embed(query)
    except Exception:
        return ""

    results = []
    client = get_qdrant()
    if client is None:
        return ""
    for collection in collections:
        try:
            hits = client.query_points(
                collection_name=collection,
                query=vector,
                limit=limit
            )
            for hit in hits.points:
                if hit.score < 0.3:
                    continue
                payload = hit.payload or {}
                content = payload.get("content", "") or payload.get("data", "")
                if content:
                    results.append((hit.score, content[:500]))
        except Exception:
            continue

    if not results:
        return ""

    results.sort(key=lambda x: x[0], reverse=True)

    # Memory context fencing — prevents model confusion
    # Absorbed from: research finding across multiple repos
    context = "\n".join(f"[{score:.2f}] {text}" for score, text in results[:8])
    return f"<memory-context>\n{context}\n</memory-context>"


def vector_store(text, category="conversation", interface="unknown", metadata=None):
    """Store into Qdrant vector memory. No-op when the vector layer is absent
    (offline/local installs) — graph memory remains the durable record."""
    if not QDRANT_AVAILABLE:
        return
    try:
        vector = embed(text)
        point_id = int(hashlib.md5(f"{time.time()}{text[:50]}".encode()).hexdigest()[:12], 16)
        payload = {
            "user_id": "orion",
            "data": text,
            "category": category,
            "interface": interface,
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        }
        if metadata:
            payload.update(metadata)
        get_qdrant().upsert(
            collection_name="orion_brain",
            points=[PointStruct(id=point_id, vector=vector, payload=payload)]
        )
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# LAYER 3: KNOWLEDGE COMPILER — Conversations → Distilled Knowledge
# Absorbed from: claude-memory-compiler (Karpathy pattern)
# Conversations are logged, then compiled into knowledge articles.
# ═══════════════════════════════════════════════════════════════

def log_conversation(message, response, interface="unknown"):
    """Log a conversation for later compilation."""
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "interface": interface,
        "user": message[:500],
        "orion": response[:500],
    }
    date = time.strftime("%Y-%m-%d")
    logfile = os.path.join(CONVERSATION_LOG, f"{date}.jsonl")
    try:
        with open(logfile, 'a') as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def get_uncompiled_conversations(days=1):
    """Get conversations that haven't been compiled yet."""
    conversations = []
    for i in range(days):
        date = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
        logfile = os.path.join(CONVERSATION_LOG, f"{date}.jsonl")
        if os.path.exists(logfile):
            try:
                with open(logfile) as f:
                    for line in f:
                        if line.strip():
                            conversations.append(json.loads(line))
            except Exception:
                pass
    return conversations


def compile_knowledge(conversations, fuel_fn=None):
    """
    Compile raw conversations into structured knowledge articles.
    Uses the best available model (fuel) to do the distillation.

    Absorbed from: Karpathy's "knowledge compiler" concept.
    Raw data → structured insight → indexed for future use.
    """
    if not conversations or not fuel_fn:
        return []

    # Format conversations for the compiler
    conv_text = ""
    for c in conversations[-20:]:  # last 20 conversations max
        conv_text += f"[{c['timestamp']} via {c['interface']}]\n"
        conv_text += f"User: {c['user']}\n"
        conv_text += f"Orion: {c['orion']}\n\n"

    compile_prompt = f"""You are a knowledge compiler. Analyze these conversations and extract structured knowledge articles.

<conversations>
{conv_text}
</conversations>

For each distinct topic or insight in the conversations, create a knowledge article:

<analysis>
Think about what's important, what's new information, what decisions were made, what was learned.
</analysis>

Output as JSON array:
[
  {{
    "title": "brief title",
    "content": "the distilled knowledge — facts, decisions, insights",
    "tags": ["relevant", "tags"],
    "type": "fact|decision|skill|preference"
  }}
]

Only extract genuinely useful knowledge. Skip greetings and meta-conversation."""

    response = fuel_fn(compile_prompt)
    if not response:
        return []

    # Parse the JSON from the response
    try:
        # Find JSON array in response
        start = response.index('[')
        end = response.rindex(']') + 1
        articles = json.loads(response[start:end])
        return articles
    except (ValueError, json.JSONDecodeError):
        return []


def save_compiled_knowledge(articles, graph, date=None):
    """Save compiled articles to both graph memory and vector memory."""
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

        # Store in graph memory (instant recall)
        graph.store(
            content=f"{title}: {content}",
            node_type=article_type,
            confidence=0.9,
            tags=tags + ["compiled", date]
        )

        # Store in vector memory (semantic search)
        vector_store(
            text=f"{title}: {content}",
            category="compiled_knowledge",
            metadata={"tags": tags, "type": article_type, "compiled_date": date}
        )

        saved += 1

    # Save compiled articles to file for reference
    filepath = os.path.join(KNOWLEDGE_DIR, f"compiled-{date}.json")
    try:
        with open(filepath, 'w') as f:
            json.dump(articles, f, indent=2)
    except Exception:
        pass

    return saved


# ═══════════════════════════════════════════════════════════════
# UNIFIED MEMORY INTERFACE — Used by the brain
# ═══════════════════════════════════════════════════════════════

# Global graph instance
_graph = GraphMemory()
_graph_path = os.path.expanduser("~/.orion/brain/graph_memory.json")

def init():
    """Initialize memory system. Load graph from disk."""
    _graph.load(_graph_path)
    return _graph


def remember(query, limit=5):
    """
    Multi-layer recall:
    1. Graph memory first (microseconds, deterministic)
    2. Vector memory second (milliseconds, semantic)
    Combine and deduplicate.
    """
    results = []

    # Layer 1: Graph (fast, tag-based)
    query_words = query.lower().split()
    graph_results = _graph.recall(query=query, limit=3)
    for node in graph_results:
        results.append(f"[graph] {node['content']}")

    # Layer 2: Vector (semantic search)
    vector_context = vector_search(query, limit=limit)
    if vector_context:
        results.append(vector_context)

    return "\n".join(results) if results else ""


def memorize(message, response, interface="unknown"):
    """Save to conversation log + vector memory."""
    # Log for compilation
    log_conversation(message, response, interface)

    # Store in vector memory
    text = f"[{interface}] User: {message[:200]} | Orion: {response[:200]}"
    vector_store(text, category="conversation", interface=interface)


def save():
    """Persist graph memory to disk."""
    _graph.save(_graph_path)


# ═══════════════════════════════════════════════════════════════
# SKILL SYSTEM — Auto-learned from successful task completions
# Absorbed from: hermes-agent skill pattern. Governance added per
# synthesis-continual-learning.md C2 (the Library-Drift ratchet):
#   - hermes self-improvement loop CLOSED (times_used + verdicts + contribution)
#   - birth-time conflict gate (refuse near-duplicate twins at the source)
#   - active flag + archive-not-delete (reversible curation)
#   - the nightly bound + lowest-contributor eviction lives in
#     orion_skill_curator.py and rides the dream cycle
# ═══════════════════════════════════════════════════════════════

SKILLS_DIR = os.path.expanduser("~/.orion/brain/skills")
SKILLS_ARCHIVE_DIR = os.path.join(SKILLS_DIR, "archive")
os.makedirs(SKILLS_DIR, exist_ok=True)
os.makedirs(SKILLS_ARCHIVE_DIR, exist_ok=True)

# Verdict vocabulary — the synthesis memo's one-field schema extension.
# 'helped' / 'hurt' / 'neutral' is the minimum signal that produces an
# honest contribution score; richer outcome shapes can be derived later.
SKILL_VERDICTS = ("helped", "hurt", "neutral")
SKILL_VERDICT_WEIGHT = {"helped": 1.0, "hurt": -1.0, "neutral": 0.0}
SKILL_VERDICTS_KEEP = 50          # bounded tail; older verdicts age out
SKILL_TRIGGER_TWIN_JACCARD = 0.7  # birth-time conflict threshold


def _skill_path(fname_or_name: str) -> str:
    """Resolve a skill identifier to its on-disk path. Accepts either the
    raw filename (already includes .json) or a skill 'name' that gets the
    same md5 treatment learn_skill uses, so callers can address skills by
    their human-readable name without knowing the hash convention."""
    if fname_or_name.endswith(".json"):
        return os.path.join(SKILLS_DIR, fname_or_name)
    fname = hashlib.md5(fname_or_name.encode()).hexdigest()[:8] + ".json"
    return os.path.join(SKILLS_DIR, fname)


def _read_skill(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_skill(path: str, skill: dict) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(skill, f, indent=2)
        return True
    except Exception:
        return False


def list_skills(active_only: bool = False) -> list[dict]:
    """Enumerate every learned skill on disk; the curator + any caller that
    needs the whole library uses this. `active_only` filters out archived /
    explicitly deactivated skills so a routing layer never matches a retired
    one. Reads from disk every call — the library is tiny (capped at ~50)."""
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    for fname in os.listdir(SKILLS_DIR):
        if not fname.endswith(".json"):
            continue
        s = _read_skill(os.path.join(SKILLS_DIR, fname))
        if not s:
            continue
        s["_fname"] = fname  # so the curator can address the file back
        if active_only and not s.get("active", True):
            continue
        out.append(s)
    return out


def _jaccard(a: list, b: list) -> float:
    sa, sb = {str(x).lower() for x in (a or [])}, {str(x).lower() for x in (b or [])}
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def _twin_of(triggers: list) -> dict | None:
    """Find an active skill whose triggers overlap enough to call this birth a
    'twin'. Returning the incumbent lets the caller UPDATE it via on_skill_fired
    instead of letting a near-duplicate accumulate — the synthesis memo's
    'reconcile_instead' pattern. Conservative threshold (0.7) — clear twins
    only, so legitimately distinct skills with one shared trigger still ship."""
    for s in list_skills(active_only=True):
        if _jaccard(triggers, s.get("triggers", [])) >= SKILL_TRIGGER_TWIN_JACCARD:
            return s
    return None


def find_matching_skill(message):
    """Match this message against the ACTIVE skill library and return the
    highest-confidence hit. Archived skills are never matched — that's the
    archive-not-delete contract: a retired skill stays auditable but can no
    longer fire. Trigger match is substring on lowercased message (unchanged
    behavior); ties broken by confidence × contribution so a well-performing
    skill wins over an equally-confident one with poor track record."""
    msg_lower = message.lower()
    skills_found = []
    for skill in list_skills(active_only=True):
        for trigger in skill.get("triggers", []):
            if str(trigger).lower() in msg_lower:
                skills_found.append(skill)
                break
    if not skills_found:
        return None
    # Sort by confidence × (1 + contribution): contribution is in [-1, 1], so
    # a brand-new (0.0) skill is unaffected, a proven (+0.5) skill gets a 1.5×
    # bump, and a chronically-hurting (-0.5) skill is halved before retirement.
    def _rank(s):
        conf = float(s.get("confidence", 0.0))
        contrib = float(s.get("contribution", 0.0))
        return conf * (1.0 + max(-0.9, min(1.0, contrib)))
    skills_found.sort(key=_rank, reverse=True)
    return skills_found[0]


def learn_skill(task_description, approach, result, tags=None):
    """Birth a learned skill from a successful task completion.

    Backward-compatible signature; new governance fields are written on every
    fresh skill (contribution=0.0, verdicts=[], active=True). The birth-time
    gate refuses near-duplicate TWINS — if an active skill already covers the
    same triggers, the incumbent's name is returned (a truthy string instead
    of True) and the caller is expected to either reconcile by firing
    on_skill_fired against that incumbent, or pass distinct tags. This is the
    synthesis memo's 'refuse harmful births at the source' — twins are the
    death-spiral surface the Library-Drift ratchet is built to prevent.

    Returns:
        True  — new skill written
        str   — the existing twin's name (rejected as duplicate)
        False — write failed
    """
    triggers = tags or task_description.lower().split()[:5]
    twin = _twin_of(triggers)
    if twin is not None:
        # Don't even consider it an error — the right move is to fire an
        # outcome against the incumbent. Return its name so the caller can.
        return twin.get("name") or twin.get("_fname", "")
    skill = {
        "name": task_description[:80],
        "triggers": triggers,
        "approach": approach,
        "result_summary": (result or "")[:200],
        "confidence": 0.8,
        "learned": time.strftime("%Y-%m-%d"),
        "times_used": 0,
        # Governance fields (synthesis-continual-learning.md C2):
        "contribution": 0.0,
        "verdicts": [],
        "active": True,
        "content_hash": hashlib.md5(((approach or "") + (task_description or "")).encode()).hexdigest()[:12],
    }
    fname = hashlib.md5(task_description.encode()).hexdigest()[:8] + ".json"
    return _write_skill(os.path.join(SKILLS_DIR, fname), skill)


def on_skill_fired(skill_name_or_fname: str, verdict: str) -> dict | None:
    """Record one firing of a learned skill (hermes self-improvement loop).
    Updates times_used, appends the verdict to a bounded tail, and recomputes
    contribution as the helped-minus-hurt mean over the tail — so a skill that
    starts hurting trends toward negative contribution and gets evicted by the
    nightly ratchet. `verdict` ∈ {helped, hurt, neutral}; unknown verdicts are
    coerced to 'neutral' to keep the loop fault-tolerant."""
    if verdict not in SKILL_VERDICTS:
        verdict = "neutral"
    path = _skill_path(skill_name_or_fname)
    skill = _read_skill(path)
    if skill is None:
        return None
    skill["times_used"] = int(skill.get("times_used", 0)) + 1
    verdicts = list(skill.get("verdicts", []))
    verdicts.append(verdict)
    if len(verdicts) > SKILL_VERDICTS_KEEP:
        verdicts = verdicts[-SKILL_VERDICTS_KEEP:]
    skill["verdicts"] = verdicts
    weights = [SKILL_VERDICT_WEIGHT.get(v, 0.0) for v in verdicts]
    skill["contribution"] = round(sum(weights) / max(1, len(weights)), 4)
    skill["last_fired"] = time.time()
    _write_skill(path, skill)
    return skill


def archive_skill(skill_name_or_fname: str, reason: str = "") -> bool:
    """Archive-not-delete: move the skill file to the archive dir and mark it
    inactive. Reversible — `restore_skill` (below) moves it back. This is what
    the curator calls on low contributors / over-cap evictions, so the library
    learns by curation without ever destroying provenance."""
    path = _skill_path(skill_name_or_fname)
    if not os.path.exists(path):
        return False
    skill = _read_skill(path) or {}
    skill["active"] = False
    skill["archived_at"] = time.time()
    if reason:
        skill["archived_reason"] = reason
    dest = os.path.join(SKILLS_ARCHIVE_DIR, os.path.basename(path))
    try:
        _write_skill(dest, skill)
        os.remove(path)
        return True
    except Exception:
        return False


def restore_skill(fname: str) -> bool:
    """Reverse archive_skill — bring a retired skill back into the active set.
    Useful if the curator's eviction proves premature; archive-not-delete is
    only honest if restore is a real operation."""
    src = os.path.join(SKILLS_ARCHIVE_DIR, fname)
    dest = os.path.join(SKILLS_DIR, fname)
    if not os.path.exists(src):
        return False
    skill = _read_skill(src) or {}
    skill["active"] = True
    skill.pop("archived_at", None)
    skill.pop("archived_reason", None)
    try:
        _write_skill(dest, skill)
        os.remove(src)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Initializing Orion Memory v2...")
    g = init()
    print(f"Graph: {len(g.nodes)} nodes")

    # Test graph store/recall
    g.store("nmap is a network scanning tool available on security-configured hosts", "tool", 1.0, ["security", "scan", "nmap"])
    g.store("himalaya is the email tool at {EMAIL_TOOL}", "tool", 1.0, ["email", "send", "himalaya"])
    g.store("dispatch module at orion_dispatch.py handles command execution", "tool", 1.0, ["dispatch", "execute", "command"])

    results = g.recall(query="scan network", tags=["security"])
    print(f"\nRecall 'scan network' with tag 'security': {len(results)} results")
    for r in results:
        print(f"  {r['content'][:80]}")

    results = g.recall(query="send email")
    print(f"\nRecall 'send email': {len(results)} results")
    for r in results:
        print(f"  {r['content'][:80]}")

    save()
    print(f"\nGraph saved. {len(g.nodes)} nodes.")
    print("Memory v2 ready.")
