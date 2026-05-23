"""orion_hash_embed.py — stdlib-only feature-hash embedding.

The cognition layer (predictor surprise, cross-fuel agreement, lateral
diffusion neighbor-match) needs a content-similarity signal that ALWAYS
works — including when Ollama is down, Qdrant is unreachable, the host
is offline, or the substrate is degraded. This is that signal: a
deterministic, dependency-free, ~50µs feature-hash embedding.

It is NOT a replacement for a real semantic embedder. nomic-embed-text
through Ollama (orion_memory.embed) gives genuine semantic structure;
this gives token-overlap structure. The trade-off is deliberate: the
cognition layer must degrade *gracefully*, not *silently*. When Ollama
is healthy the consumer can swap in the real embedder; when it isn't,
this keeps the brain learning.

Properties:
- pure stdlib (hashlib + math)
- deterministic across hosts (same text → same vector)
- L2-normalized so cosine == dot-product
- bounded cost (one sha256 per token, capped at 256 tokens)
- handles arbitrary payload shapes (dict / list / str)

Cosine score interpretation in this layer:
    >= 0.85  near-identical token bags
    0.55–0.85  same topic / overlapping vocabulary
    0.25–0.55  weak overlap (a few shared tokens)
    < 0.25     essentially unrelated content
"""
from __future__ import annotations

import hashlib
import json
import math
import re

DEFAULT_DIM = 128
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_MAX_TOKENS = 256


def _tokens(text: str) -> list[str]:
    if not text:
        return []
    toks = _TOKEN_RE.findall(text.lower())
    # Drop stop-ish very-short tokens; cap length so a pathological huge
    # payload can't blow up the vectorizer cost.
    return [t for t in toks if len(t) > 1][:_MAX_TOKENS]


def _flatten(obj) -> str:
    """Coerce any payload (dict/list/str) into a flat token string."""
    if obj is None:
        return ""
    if isinstance(obj, (str, int, float, bool)):
        return str(obj)
    try:
        return json.dumps(obj, default=str, sort_keys=True)
    except Exception:
        return str(obj)


def hash_embed(text_or_obj, dim: int = DEFAULT_DIM) -> list[float]:
    """Return an L2-normalized dim-vector encoding the token bag of the input.

    Each token contributes a signed +1 to one bucket (index + sign both
    derived from sha256 of the token, so collisions are unbiased). The
    final vector is L2-normalized so cosine reduces to a dot product."""
    text = _flatten(text_or_obj)
    vec = [0.0] * dim
    toks = _tokens(text)
    if not toks:
        return vec
    for t in toks:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if (h[4] & 1) else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    """Dot product of two L2-normalized vectors. Returns 0.0 if either is
    the zero vector (an all-empty payload). Range [-1, 1] in theory; for
    non-negative token bags the practical range is [0, 1]."""
    if not a or not b or len(a) != len(b):
        return 0.0
    s = sum(x * y for x, y in zip(a, b))
    # Clamp away tiny FP overshoot so downstream `1 - cos` stays in [0, 1].
    if s > 1.0:
        return 1.0
    if s < -1.0:
        return -1.0
    return s


def mean_vector(vectors: list[list[float]]) -> list[float]:
    """Element-wise mean of a list of equal-length vectors, then L2-normalized.
    Returns an empty vector if input is empty or shapes disagree."""
    if not vectors:
        return []
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        return []
    out = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            out[i] += x
    n = len(vectors)
    out = [x / n for x in out]
    norm = math.sqrt(sum(x * x for x in out))
    if norm <= 0:
        return out
    return [x / norm for x in out]
