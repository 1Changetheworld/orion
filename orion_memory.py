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
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct


# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
OLLAMA_URL = "http://localhost:11434"
KNOWLEDGE_DIR = os.path.expanduser("~/server_data/orion-brain/knowledge")
CONVERSATION_LOG = os.path.expanduser("~/server_data/orion-brain/conversations")

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
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

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
    if _qdrant is None:
        _qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
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
    """Search Qdrant vector memory. Returns context string with fencing."""
    if collections is None:
        collections = ["orion_brain", "server_knowledge"]

    try:
        vector = embed(query)
    except Exception:
        return ""

    results = []
    client = get_qdrant()
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
    """Store into Qdrant vector memory."""
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
_graph_path = os.path.expanduser("~/server_data/orion-brain/graph_memory.json")

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
# Absorbed from: hermes-agent skill pattern
# ═══════════════════════════════════════════════════════════════

SKILLS_DIR = os.path.expanduser("~/server_data/orion-brain/skills")
os.makedirs(SKILLS_DIR, exist_ok=True)


def find_matching_skill(message):
    """Check if any learned skill matches this message."""
    msg_lower = message.lower()
    skills_found = []

    if not os.path.isdir(SKILLS_DIR):
        return None

    for fname in os.listdir(SKILLS_DIR):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(SKILLS_DIR, fname)) as f:
                skill = json.load(f)
            triggers = skill.get("triggers", [])
            for trigger in triggers:
                if trigger.lower() in msg_lower:
                    skills_found.append(skill)
                    break
        except Exception:
            continue

    if skills_found:
        # Return highest confidence skill
        skills_found.sort(key=lambda s: s.get("confidence", 0), reverse=True)
        return skills_found[0]
    return None


def learn_skill(task_description, approach, result, tags=None):
    """
    Auto-learn a skill from a successful task completion.
    Absorbed from: hermes-agent skill extraction pattern.
    """
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
    filepath = os.path.join(SKILLS_DIR, fname)
    try:
        with open(filepath, 'w') as f:
            json.dump(skill, f, indent=2)
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
    g.store("nmap is the network scanning tool on ASUS Kali box", "tool", 1.0, ["security", "scan", "nmap"])
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
