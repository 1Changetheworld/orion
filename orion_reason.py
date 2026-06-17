#!/usr/bin/env python3
"""orion_reason.py — "The Loom": Orion's active reasoning loop (cognition Phase 0).

The faculties already exist as separate daemons (workspace=salience spotlight,
metacognition=governor, predictor/simulate=world-model seeds, wonder=curiosity,
will=goals). What was missing is the CONDUCTOR: a process that holds a problem
across time and reasons in multiple steps, instead of every "thought" bottoming
out in one fuel call.

Design (decided 2026-06-11):
  * Cognition = continuous reduction of TENSION (contradiction / uncertainty /
    prediction-error / verification-debt) over the one persistent brain graph.
  * No new sensors: TENSION is aggregated from signals the organs already emit.
  * Durable multi-step thought reuses orion_taskspine (crash-safe, RESUMABLE by
    task_id) so a deliberation survives a reboot — duration is the property no
    base model has.
  * Each reasoning step is enriched (persona + recall) and judged by the existing
    governor; the grounded conclusion is written back THROUGH the live brain
    (dedupe + contradiction handling run), which re-enters the workspace and
    lowers the tension that spawned the thought.

No GPU, model-independent, no API keys — the brain is the intelligence; the model
is swappable fuel. This is the "truest activation": the organs think as one.

Phase 0 scope: tension intake + aggregation, threshold trigger, one durable
deliberation via taskspine with per-step governor gating, write-back, and
resume-on-start. Autonomous channel notifications are OFF. Use `--once` to run a
single deliberation by hand (the first proof + the kill/resume keystone test).
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import threading
import time
import urllib.request
from pathlib import Path

# ── config ────────────────────────────────────────────────────────────────
BRAIN_URL = os.environ.get("ORION_BRAIN_HTTP_URL", "http://127.0.0.1:5556").rstrip("/")
AUTH_PATH = os.path.expanduser(os.environ.get("ORION_AUTH_TOKEN_PATH", "~/.orion/auth-token"))
REASON_DIR = Path(os.path.expanduser("~/.orion/reason"))
ACTIVE_FILE = REASON_DIR / "active.json"          # topic -> in-flight task_id (resume)
RESOLVED_FILE = REASON_DIR / "resolved.json"      # durability: per-topic resolution history
STATE_DIR = Path(os.path.expanduser("~/.orion/state"))
TRACE_FILE = STATE_DIR / "neuromod_loom_trace.jsonl"   # closed-loop neuromod audit: per-tick join
MAX_TRACE_BYTES = 16 * 1024 * 1024                     # bounded; keep the recent tail

# Tension sources the organs already publish → weight each contributes.
# Wonder is Orion's GENUINE self-generated curiosity — the highest-value thing it can
# reason about — so it sits ABOVE the trigger threshold: a single real wonder question
# (e.g. "why do I exist?") should reliably start a deliberation, not decay unheard. This
# WIRES the curiosity engine to the reasoning engine; wonder's natural ~10-min cadence +
# the 180s gap + per-topic refractory keep it healthy, never a firehose.
TENSION_SOURCES = {
    "brain.wonder.question":        ("contradiction", 1.4),
    "brain.wonder.pondered":        ("wonder", 1.6),   # Orion's DEEP open questions ("what am I
        # beyond the model that fuels me?") — were journaled-only; now they reach reasoning. Weight
        # 1.6 (not 1.4) so a SINGLE deep question survives one decay tick (1.6*0.85=1.36 > 1.2 bar)
        # and fires — they arrive singly, ~every 10 min. Durability check holds the eternal ones open.
    "brain.metacog.miscalibration": ("verification-debt", 1.1),
    "brain.sim.drift":              ("imagination-vs-reality", 0.7),
    "brain.predictor.surprise":     ("surprise", 0.5),
    "brain.surprise.spike":         ("surprise", 0.6),
}
WORKSPACE_SUBJECT = "workspace.current"           # the salience spotlight

TRIGGER_THRESHOLD = float(os.environ.get("ORION_REASON_TRIGGER", "1.2"))
DECAY_PER_TICK = 0.85                              # tension fades if not refreshed
CONTROL_INTERVAL_SEC = 20.0
MAX_STEPS = int(os.environ.get("ORION_REASON_MAX_STEPS", "6"))
MAX_CONCURRENT = 1                                 # Phase 0: one thought at a time
DONE_MARK = "CONCLUSION:"                          # model emits this when resolved
# cadence + tension hygiene — reason on REAL tensions at a sane pace, not a telemetry firehose:
REFRACTORY_SEC = float(os.environ.get("ORION_REASON_REFRACTORY", "1800"))   # per-topic cooldown after firing
MIN_GAP_SEC = float(os.environ.get("ORION_REASON_MIN_GAP", "180"))          # min seconds between deliberations
WORKSPACE_SAL_MIN = float(os.environ.get("ORION_REASON_WS_SAL_MIN", "0.6")) # workspace salience floor to nudge tension
TELEMETRY_MARKERS = ("memory stored", "surprise spike", "workspace current",
                     "imessage inbound", "imessage outbound", "heartbeat")
# DURABILITY-DRIVEN SELF-CHECK: a resolution PREDICTS the topic won't return; a RE-FIRE
# MEASURES that it didn't hold; the CORRECTION is to escalate (native -> model -> hold-open)
# instead of falsely re-resolving the same thing forever (the observed last-contact loop).
HOLD_AFTER = int(os.environ.get("ORION_REASON_HOLD_AFTER", "2"))            # re-fires before HOLDing
HELD_REFRACTORY = float(os.environ.get("ORION_REASON_HELD_REFRACTORY", "86400"))  # 24h quiet once held

_tension: dict[str, dict] = {}                     # key -> {score,label,sources,ts}
_active: dict[str, str] = {}                       # key -> task_id
_cooldown: dict[str, float] = {}                   # key -> ts when it may fire again (per-topic refractory)
_resolved: dict[str, dict] = {}                    # key -> {n, native_n, refire, held, last_ts} (durability)
_last_deliberation_ts = 0.0                        # global pacing (MIN_GAP_SEC)
_lock = threading.RLock()
_inflight = 0
_stop = threading.Event()


# ── brain seams (mirror orion_sleep's proven pattern) ───────────────────────
def _token() -> str:
    try:
        return open(AUTH_PATH, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _brain_call(name: str, arguments: dict, timeout: int = 30) -> str:
    tok = _token()
    if not tok:
        return ""
    body = json.dumps({"name": name, "arguments": arguments}).encode("utf-8")
    req = urllib.request.Request(f"{BRAIN_URL}/v1/call", data=body,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json"})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
        try:
            obj = json.loads(raw)
            # tolerate a few shapes; fall back to raw text
            for k in ("result", "content", "text", "output"):
                if isinstance(obj, dict) and obj.get(k):
                    v = obj[k]
                    return v if isinstance(v, str) else json.dumps(v)
            return raw
        except Exception:
            return raw
    except Exception:
        return ""


def _recall(query: str, limit: int = 5) -> str:
    return _brain_call("orion_recall", {"query": query, "limit": limit}) or ""


def _memorize(content: str, node_type: str = "insight", tags=None) -> bool:
    return bool(_brain_call("orion_memorize",
                            {"content": content, "type": node_type, "tags": tags or []}))


def _persona() -> str:
    try:
        import orion_persona_render
        return orion_persona_render.render_persona() or ""
    except Exception:
        return ""


def _publish(subject: str, payload: dict) -> None:
    try:
        from orion_substrate import publish
        publish(subject, payload)
    except Exception:
        pass


def _neuromod() -> dict:
    """Read the global neuromodulators (gain control). Falls back to neutral."""
    try:
        import orion_neuromod
        return orion_neuromod.current()
    except Exception:
        return {"arousal": 0.3, "learning": 0.4, "explore": 0.5, "caution": 0.3, "focus": 0.5}


# ── tension intake + aggregation ────────────────────────────────────────────
def _topic_key(payload: dict) -> tuple[str, str]:
    """Derive a stable topic key + human label from a heterogeneous signal."""
    label = (payload.get("question") or payload.get("symptom")
             or payload.get("observation") or payload.get("subject")
             or payload.get("content") or payload.get("text") or "")
    label = str(label).strip()[:160] or "an unnamed tension"
    key = "".join(ch.lower() if ch.isalnum() else " " for ch in label)
    key = " ".join(key.split())[:80]
    return key, label


def _is_telemetry(text: str) -> bool:
    """True if `text` is a bus event / internal telemetry, not a real topic to reason about.
    A memory being stored or the workspace updating is NOT something to deliberate on."""
    s = (text or "").strip().lower()
    if not s:
        return True
    if re.match(r"^[a-z][a-z0-9_]*([.][a-z0-9_]+)+$", s):   # bare dotted subject, e.g. brain.memory.stored
        return True
    return any(m in s for m in TELEMETRY_MARKERS)


def _bump(key: str, label: str, source: str, amount: float) -> None:
    with _lock:
        t = _tension.get(key) or {"score": 0.0, "label": label, "sources": set(), "ts": 0.0}
        t["score"] += amount
        t["label"] = label or t["label"]
        t["sources"].add(source)
        t["ts"] = time.time()
        _tension[key] = t


def _on_signal(kind: str, weight: float):
    def handler(subject: str, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        sev = payload.get("severity")
        mult = {"critical": 1.6, "notice": 1.0, "info": 0.5}.get(sev, 1.0)
        # numeric intensities if present (surprise score, miscalibration error)
        for f in ("surprise", "error", "drift", "score", "magnitude"):
            v = payload.get(f)
            if isinstance(v, (int, float)):
                mult *= min(2.0, max(0.3, abs(float(v)) or 1.0))
                break
        key, label = _topic_key(payload)
        _bump(key, f"[{kind}] {label}", subject, weight * mult)
    return handler


def _on_workspace(subject: str, payload: dict) -> None:
    """The spotlight: top-K salient items each tick → small tension nudges."""
    if not isinstance(payload, dict):
        return
    items = payload.get("items") or payload.get("candidates") or payload.get("top") or []
    if isinstance(items, dict):
        items = list(items.values())
    for it in (items if isinstance(items, list) else [])[:5]:
        if not isinstance(it, dict):
            continue
        raw = (it.get("content") or it.get("text") or it.get("subject")
               or it.get("question") or "")
        if _is_telemetry(str(raw)):                    # bus events are not reasoning tensions
            continue
        sal = it.get("salience") or it.get("score") or 0.0
        try:
            sal = float(sal)
        except Exception:
            sal = 0.0
        if sal < WORKSPACE_SAL_MIN:                     # only genuinely salient items nudge tension
            continue
        key, label = _topic_key(it)
        _bump(key, f"[salient] {label}", "workspace.current", 0.25 * min(2.0, sal))


# ── deliberation (GENUINE multi-step thought: decompose → address → synthesize)
DECOMPOSE_DIRECTIVE = (
    "PHASE 1 — DECOMPOSE. Break this tension into 2-4 crisp sub-questions whose "
    "answers would together resolve it. Output ONLY a numbered list of those "
    "sub-questions. Do NOT answer them. Do NOT conclude."
)
SYNTHESIZE_DIRECTIVE = (
    "PHASE 3 — SYNTHESIZE + CRITIQUE. Combine the sub-answers above into one "
    "coherent resolution. Then adversarially name its single biggest weakness and "
    "address it. Then emit a final line beginning '" + DONE_MARK + " ' with the "
    "grounded conclusion and what (if anything) remains uncertain."
)

# PREDICT-BY-CONSTRUCTION (Build 3): the leaf-purity audit proved coherence-checking the
# graph == recall, so the only non-rented proof of reasoning is a FORWARD prediction the
# world later confirms. Make every resolution COMMIT one (or honestly declare itself analytic).
PREDICT_ENABLED = os.environ.get("ORION_LOOM_PREDICT", "1") != "0"
PREDICTION_SUFFIX = (
    "\n\nTHEN, after the '" + DONE_MARK + "' line, append a PREDICTION block in EXACTLY this "
    "five-line form (this is how your reasoning is later checked against reality, NATIVELY and "
    "with no model — be honest, a falsifiable miss is more valuable than a vague hit):\n"
    "PREDICTION: <one short, falsifiable claim about a FUTURE state that must hold IF this "
    "resolution is correct. It MUST be PASSIVE — observable on its own with NO action taken. "
    "Use the literal word NONE if the question is purely analytic/philosophical>\n"
    "OBSERVABLE: <3-8 keywords naming the concrete future evidence>\n"
    "HORIZON_HOURS: <integer hours by which that evidence should appear>\n"
    "KIND: <operational if it admits a future test, else analytic>\n"
    "PRIOR: <your HONEST confidence 0.0-1.0 that this prediction is TRUE, BEFORE reality tests it. "
    "Low = it would SURPRISE you if confirmed; high = obvious. Be honest — a confirmed surprise is "
    "worth more than a confirmed obviousness>\n"
    "CHECK: <a MACHINE-CHECKABLE expression that is TRUE iff the prediction holds, using ONE "
    "probe from this exact vocabulary, form 'probe OP number' (OP is > < >= <= == !=), or NONE "
    "if analytic. Probes: graph:nodes (live node count) | neuromod:arousal|learning|explore|"
    "caution|focus (0..1) | refire:<topic> | service:<launchd-label>:runs (restart count) | "
    "service:<launchd-label>:running . Example: service:com.orion.imessage-outbound:runs > 8>"
)
_PRED_RE = re.compile(
    r"PREDICTION:\s*(?P<claim>.+?)\s*(?:\n|$)\s*OBSERVABLE:\s*(?P<obs>.+?)\s*(?:\n|$)\s*"
    r"HORIZON_HOURS:\s*(?P<hrs>[0-9.]+).*?KIND:\s*(?P<kind>operational|analytic)",
    re.IGNORECASE | re.DOTALL)
_CHECK_LINE_RE = re.compile(r"CHECK:\s*(?P<check>.+?)\s*(?:\n|$)", re.IGNORECASE)


def _emit_prediction(key: str, label: str, last_content: str, src_content: str = "") -> None:
    """Parse the PREDICTION block a resolution committed and log it to the temporal ledger.
    Silent + best-effort — instrumentation must never break the Loom."""
    if not PREDICT_ENABLED:
        return
    try:
        m = _PRED_RE.search(last_content or "")
        if not m:
            return
        claim = m.group("claim").strip()
        obs = _keywords(m.group("obs"))
        try:
            hrs = float(m.group("hrs"))
        except Exception:
            hrs = 1.0
        cm = _CHECK_LINE_RE.search(last_content or "")
        check = cm.group("check").strip() if cm else ""
        if check.upper() == "NONE":
            check = ""
        pm = re.search(r"PRIOR:\s*([0-9.]+)", last_content or "", re.IGNORECASE)
        try:
            stated_prior = float(pm.group(1)) if pm else None
        except Exception:
            stated_prior = None
        # NATIVE structural prior: does Orion's OWN graph already entail this claim? (read-only — learn=False
        # so estimating a prior never triggers learning). If NOT entailed yet reality confirms => surprise =
        # the uncfakeable native-cognition fingerprint.
        native_prior, native_supported = None, None
        try:
            import orion_native_infer as ni
            r = ni.infer(claim, learn=False)
            native_supported = bool(r.get("resolved"))
            native_prior = float(r.get("confidence") or 0.0) if native_supported else 0.0
        except Exception:
            pass
        import orion_temporal_ledger as tl
        src_key = tl._node_key(src_content) if src_content else ""   # node-level grounding link
        tl.record(key, label, claim, list(obs), m.group("kind"), hrs, check=check, src_key=src_key,
                  prior=native_prior, stated_prior=stated_prior, native_supported=native_supported)
    except Exception:
        pass


def _strip_prediction(text: str) -> str:
    """Remove the PREDICTION block before a conclusion is memorized (keep the graph clean)."""
    return re.split(r"\n\s*PREDICTION:", text or "", maxsplit=1)[0].strip()


def _address_directive(i: int, total: int, subq: str, ctx: str) -> str:
    c = ("\nGrounded context for this sub-question:\n" + ctx) if ctx.strip() else ""
    return (f"PHASE 2 — ADDRESS sub-question {i}/{total}:\n  {subq}\n"
            "Answer ONLY this sub-question, concretely and grounded; flag anything "
            "unsupported. Do NOT conclude the whole problem yet." + c)


def _parse_subquestions(text: str) -> list:
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(?:\d+[\).:]|[-*•])\s+(.*)", line)
        if m and m.group(1).strip():
            out.append(m.group(1).strip())
    return out[:4]


def _frame(label: str) -> str:
    return ("A TENSION has arisen in your mind that wants resolving:\n"
            f"  {label}\n\nYou will resolve it in deliberate PHASES (decompose → "
            "address each part, grounded → synthesize + self-critique). Follow the "
            "PHASE instruction at each step. Do not skip ahead.")


def _conclude(task) -> str:
    steps = [s for s in (task.get("steps") or []) if s.get("role") == "assistant"]
    if not steps:
        return ""
    last = steps[-1].get("content", "")
    if DONE_MARK in last:
        return last.split(DONE_MARK, 1)[1].strip()
    return last.strip()


# ── NATIVE FAST-PATH (Independence Index): resolve from the brain's OWN structure ──
# before spending a single model call. Cheap recall + honest self-check + SAFE fallback:
# a weak native attempt just defers to the model, exactly like today. Every native success
# REMOVES a model call — the first measurable step of model-free cognition. No GPU, no LLM.
NATIVE_ENABLED = os.environ.get("ORION_REASON_NATIVE", "1") != "0"
NATIVE_OVERLAP_MIN = float(os.environ.get("ORION_REASON_NATIVE_OVERLAP", "0.55"))
_STOP_WORDS = {"the", "a", "an", "is", "are", "of", "to", "and", "or", "in", "on", "for",
               "why", "does", "my", "it", "that", "this", "with", "as", "at", "be", "by",
               "do", "how", "what", "from", "was", "were", "has", "have", "i", "you", "we",
               "our", "not", "but", "its", "a", "an"}


def _keywords(text: str) -> set:
    toks = "".join(c.lower() if c.isalnum() else " " for c in (text or "")).split()
    return {w for w in toks if len(w) > 2 and w not in _STOP_WORDS}


# leaf-purity cure (AI-study 2026-06-16): the native fast-path must NOT launder ungrounded
# model output as 'native knowledge'. A resolution counts as native only if it rests on
# GROUNDED or genuinely NATIVE-ORIGIN content — not on recalled model-insight. 92.5% of the
# graph is model-generated; refusing to launder it makes native-success honest (≈0 until real
# grounded knowledge accrues), which is the point: own the operators, don't recycle the rent.
_GRAPH_FILE = os.path.expanduser("~/.orion/brain/graph_memory.json")
_GROUNDED_TYPES = {"observation", "identity", "cross_interface_contact"}
_GROUNDED_TAGS = {"perception", "grounding:confirmed", "confirmed", "grounded"}
_MODEL_INSIGHT_TAGS = {"loom", "insight", "wonder", "sleep", "reason", "consolidated",
                       "reasoned", "study", "dream"}
_REFUTED_TAGS = {"grounding:refuted", "refuted"}


def _grounded_support(label: str, topk: int = 5) -> bool:
    """Does grounded / native-origin content support this label — or only ungrounded model
    recall? Returns True iff at least one strong keyword-match node is grounded (and none of
    the support is explicitly refuted). Pure graph read, no model."""
    lk = _keywords(label)
    if not lk:
        return False
    try:                                               # reality-earned grounding beats heuristics
        import orion_temporal_ledger as tl
        gs = tl.grounding_status(label)
        if gs == "grounded":
            return True                                # a prediction about this topic held vs reality
        if gs == "refuted":
            return False                               # reality contradicted it — never native
    except Exception:
        pass
    try:
        nodes = json.loads(open(_GRAPH_FILE, encoding="utf-8").read()).get("nodes", [])
        if isinstance(nodes, dict):
            nodes = list(nodes.values())
    except Exception:
        return False
    scored = []
    for n in nodes:
        c = (n.get("content", "") + " " + " ".join(n.get("tags", [])))
        ov = len(lk & _keywords(c))
        if ov:
            scored.append((ov, n))
    scored.sort(key=lambda x: -x[0])
    grounded = False
    for _, n in scored[:topk]:
        tags = {str(t).lower() for t in n.get("tags", [])}
        if tags & _REFUTED_TAGS:
            return False                               # explicitly refuted support → never native
        is_groundtype = n.get("type") in _GROUNDED_TYPES or (tags & _GROUNDED_TAGS)
        if is_groundtype and not (tags & _MODEL_INSIGHT_TAGS):
            grounded = True                            # grounded ONLY if not also model-authored
    return grounded


def _try_native_resolution(label: str) -> str | None:
    """Resolve a tension from prior knowledge with ZERO model calls, or return None.
    Conservative self-check: accept ONLY strong keyword coverage of substantive recalled
    knowledge (not an echo of the question), AND only if GROUNDED support exists (no laundering
    ungrounded model recall). Anything weaker falls back to the model — honestly renting."""
    if not NATIVE_ENABLED:
        return None
    lk = _keywords(label)
    if len(lk) < 2:
        return None
    recalled = _recall(label, limit=6)
    if not recalled or len(recalled.strip()) < 60:
        return None
    coverage = len(lk & _keywords(recalled)) / len(lk)
    if coverage < NATIVE_OVERLAP_MIN:
        return None
    if label.strip().lower() in recalled.lower() and len(recalled) < len(label) * 3:
        return None                                    # reject a bare echo with no substance
    if not _grounded_support(label):
        return None                                    # leaf-purity cure: refuse to launder model recall
    return recalled.strip()[:1200]


def _load_resolved() -> None:
    global _resolved
    try:
        _resolved = json.loads(RESOLVED_FILE.read_text(encoding="utf-8"))
    except Exception:
        _resolved = {}


def _save_resolved() -> None:
    try:
        REASON_DIR.mkdir(parents=True, exist_ok=True)
        tmp = RESOLVED_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_resolved), encoding="utf-8")
        os.replace(tmp, RESOLVED_FILE)
    except Exception:
        pass


def _record_resolution(key: str, native: bool) -> None:
    """A resolution claims the topic is settled — log it so a later RE-FIRE is detectable as
    a durability failure (the measure in predict->measure->correct)."""
    h = _resolved.setdefault(key, {"n": 0, "native_n": 0, "refire": 0, "held": False, "last_ts": 0.0})
    h["n"] += 1
    if native:
        h["native_n"] += 1
    h["last_ts"] = time.time()
    _save_resolved()


def deliberate(key: str, label: str, resume_task_id: str | None = None) -> dict:
    """Run (or resume) one durable, PHASED, governor-gated deliberation:
    decompose -> address each sub-question (grounded) -> synthesize + critique.
    Phase is derived from the task's step count, so resume picks up mid-thought."""
    global _inflight
    import orion_taskspine as ts
    try:
        import orion_metacognition as meta
    except Exception:
        meta = None

    if PREDICT_ENABLED and not resume_task_id:              # TEMPORAL VERIFIER: score matured predictions
        try:
            import orion_temporal_ledger as tl
            tl.check_due()
        except Exception:
            pass

    # DURABILITY-DRIVEN SELF-CHECK: if this topic was resolved before and is firing AGAIN,
    # the prior resolution did not hold — so escalate instead of falsely re-resolving it.
    hist = _resolved.get(key)
    re_fired = (hist is not None) and (not resume_task_id)
    if re_fired:
        hist["refire"] = hist.get("refire", 0) + 1
        _save_resolved()
        if hist["refire"] >= HOLD_AFTER:                   # keeps returning -> genuinely OPEN
            n = hist.get("n", 0)
            concl = (f"(HELD as a genuinely open question — resolved {n}x but it keeps "
                     f"returning; I will not force another false resolution. Held open.)")
            hist["held"] = True
            _save_resolved()
            _trace({"ts": time.time(), "rec": "conclude", "key": key, "eff_depth": 0,
                    "steps_used": 0, "resolved": False, "n_subq": 0, "native": False, "held": True})
            try:
                _publish("brain.wonder.hold", {"topic": key, "label": label, "held": True,
                                               "resolved_times": n, "ts": time.time()})
            except Exception:
                pass
            with _lock:
                _cooldown[key] = time.time() + HELD_REFRACTORY   # stop the loop
                _tension.pop(key, None); _active.pop(key, None); _save_active()
            return {"key": key, "resolved": False, "steps": 0, "held": True,
                    "subquestions": [], "conclusion": concl}

    # NATIVE FAST-PATH: try the brain's own structure before ANY model call — UNLESS a prior
    # native resolution already failed to hold here (then the cheap check is unreliable for this
    # topic, so think harder via the model).
    native_unreliable = bool(hist and hist.get("native_n", 0) > 0 and re_fired)
    if not resume_task_id and not native_unreliable:
        native = _try_native_resolution(label)
        if native:
            conclusion = "(resolved natively from prior knowledge — zero model calls)\n" + native
            _record_resolution(key, native=True)
            if PREDICT_ENABLED:                            # recall must not escape the verifier
                try:
                    import orion_temporal_ledger as tl
                    tl.record_recall(key, label)
                except Exception:
                    pass
            _trace({"ts": time.time(), "rec": "conclude", "key": key, "eff_depth": 0,
                    "steps_used": 0, "resolved": True, "n_subq": 0, "native": True})
            try:
                _publish("brain.reason.concluded",
                         {"topic": key, "label": label, "resolved": True, "steps": 0,
                          "native": True, "conclusion": conclusion[:400], "ts": time.time()})
            except Exception:
                pass
            with _lock:
                _tension.pop(key, None)
                _active.pop(key, None)
                _save_active()
            return {"key": key, "resolved": True, "steps": 0, "native": True,
                    "subquestions": [], "conclusion": conclusion}

    if resume_task_id:
        task_id = resume_task_id
    else:
        task_id = ts.create_task(_frame(label))
    with _lock:
        _active[key] = task_id
        _save_active()
        _inflight += 1

    frame = _persona()
    holder = {"directive": "", "allow_conclude": False}

    def role_fuel(prompt: str):
        try:
            import orion_fuel
        except Exception:
            return ("", "none")
        full = "\n\n---\n\n".join(p for p in (frame, holder["directive"], prompt) if p)
        try:
            text, engine = orion_fuel.get_fuel(full, interface="reason")
        except Exception:
            return ("", "error")
        # honour CONCLUSION only in the synthesis phase — refuse premature collapse
        if text and not holder["allow_conclude"] and DONE_MARK in text:
            text = text.split(DONE_MARK)[0].strip() + "\n(continuing — not yet synthesis)"
        return (text, engine)

    nm = _neuromod()
    # focus + caution => think DEEPER (more steps); independent of the trigger gain.
    eff_max = max(3, min(8, round(MAX_STEPS * (0.7 + 0.6 * nm["focus"] + 0.3 * nm["caution"]))))
    subqs: list = []
    steps_done = 0
    try:
        while steps_done < eff_max and not _stop.is_set():
            task = ts.load_task(task_id)
            asst = [s for s in (task.get("steps") or []) if s.get("role") == "assistant"]
            n = len(asst)
            if not subqs and n >= 1:                       # resume-safe re-parse
                subqs = _parse_subquestions(asst[0].get("content", ""))

            if n == 0:                                     # PHASE 1 decompose
                holder["directive"], holder["allow_conclude"] = DECOMPOSE_DIRECTIVE, False
            elif subqs and (n - 1) < len(subqs) and n < (eff_max - 1):  # PHASE 2 address
                subq = subqs[n - 1]
                ctx = _recall(subq, limit=4)
                holder["directive"] = _address_directive(n, len(subqs), subq, ctx)
                holder["allow_conclude"] = False
            else:                                          # PHASE 3 synthesize
                holder["directive"] = SYNTHESIZE_DIRECTIVE + (PREDICTION_SUFFIX if PREDICT_ENABLED else "")
                holder["allow_conclude"] = True

            synth_phase = holder["allow_conclude"]
            task = ts.advance(task_id, fuel_fn=role_fuel)
            steps_done += 1
            last = (task.get("steps") or [])[-1] if task.get("steps") else {}
            if last.get("status") == "stalled":
                break                                      # no fuel — leave resumable
            if not subqs:                                  # just produced decompose
                subqs = _parse_subquestions(last.get("content", ""))
            if meta:
                try:
                    meta.governor("reason.step", reversible=True, blast_radius="single",
                                  symptom=label, fuel=last.get("fuel", ""))
                except Exception:
                    pass
            if task.get("status") == "complete":
                break
            if synth_phase and DONE_MARK in (last.get("content") or ""):
                break

        task = ts.load_task(task_id)
        conclusion = _conclude(task)
        resolved = bool(conclusion) and "cannot resolve" not in conclusion.lower()
        clean = _strip_prediction(conclusion)               # don't pollute the graph with the block
        src_content = f"{clean}  (reasoned via the Loom from tension: {label})" if clean else ""
        if resolved:
            _record_resolution(key, native=False)          # durability: a model resolution claims it's settled
            _emit_prediction(key, label, conclusion, src_content)  # VERIFIER: forward prediction + node link
        if clean:
            _memorize(src_content, node_type="insight", tags=["reasoned", "loom", "insight"])
        conclusion = clean
        if meta:
            try:
                meta.record_outcome("reason.deliberation",
                                    "resolved" if resolved else "unresolved", symptom=label)
            except Exception:
                pass
        _publish("brain.reason.concluded",
                 {"topic": key, "label": label, "resolved": resolved, "steps": steps_done,
                  "subquestions": subqs, "conclusion": conclusion[:400], "ts": time.time()})
        _trace({"ts": time.time(), "rec": "conclude", "key": key,
                "eff_depth": eff_max, "steps_used": steps_done,
                "resolved": resolved, "n_subq": len(subqs)})   # realized effect channels
        with _lock:
            _tension.pop(key, None)                        # tension discharged
            _active.pop(key, None)
            _save_active()
        return {"key": key, "resolved": resolved, "steps": steps_done,
                "subquestions": subqs, "conclusion": conclusion}
    finally:
        with _lock:
            _inflight = max(0, _inflight - 1)


# ── persistence of in-flight deliberations (resume-on-start) ────────────────
def _save_active() -> None:
    try:
        REASON_DIR.mkdir(parents=True, exist_ok=True)
        tmp = ACTIVE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_active), encoding="utf-8")
        os.replace(tmp, ACTIVE_FILE)
    except Exception:
        pass


def _resume_open() -> None:
    """Keystone: finish any deliberation interrupted by a restart."""
    try:
        saved = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    for key, task_id in list(saved.items()):
        if _stop.is_set():
            break
        try:
            import orion_taskspine as ts
            task = ts.load_task(task_id)
            if not task or task.get("status") != "open":
                with _lock:
                    _active.pop(key, None); _save_active()
                continue
            label = (task.get("goal") or key)[:160]
            print(f"[loom] resuming interrupted deliberation {task_id} ({key})")
            deliberate(key, label, resume_task_id=task_id)
        except Exception as e:
            print(f"[loom] resume failed for {key}: {e}")


# ── closed-loop neuromod audit trace ────────────────────────────────────────
# A synchronized per-tick row joining what the closed-loop independence audit needs:
# the modulator vector (m), the common tension drive E(t) to CONDITION on, and the
# Loom EFFECT channels the modulators actually gate (threshold, depth, fire-branch,
# load). Per the council's agreed schema (SPEC-closedloop-audit.md). Purely
# OBSERVATIONAL — it never changes a Loom decision and spends no fuel.
def _regime(total: float, peak: float, n: int, inflight: int) -> str:
    """Observable task-demand regime — derived from LOAD, deliberately NOT from the
    modulators (we are auditing whether the modulators independently gate the Loom;
    binning by them would be circular)."""
    if inflight >= MAX_CONCURRENT and peak > 0:
        return "saturated"
    if total < 0.05 and inflight == 0:
        return "idle"
    if total >= TRIGGER_THRESHOLD or inflight > 0:
        return "busy"
    return "light"


def _trace(row: dict) -> None:
    """Append one synchronized audit row. Bounded by a cheap tail-rotation. Silent on
    failure — instrumentation must never break the Loop."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with TRACE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        if TRACE_FILE.stat().st_size > MAX_TRACE_BYTES:
            lines = TRACE_FILE.read_text(encoding="utf-8").splitlines()[-40000:]
            tmp = TRACE_FILE.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(tmp, TRACE_FILE)
    except Exception:
        pass


def _trace_report() -> int:
    """Read-only summary of the audit trace (no fuel, no daemon)."""
    from collections import Counter
    try:
        rows = [json.loads(l) for l in TRACE_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        rows = []
    ticks = [r for r in rows if r.get("rec") == "tick"]
    concl = [r for r in rows if r.get("rec") == "conclude"]
    print(f"trace file: {TRACE_FILE}")
    print(f"rows: {len(rows)}  ·  ticks: {len(ticks)}  ·  conclusions: {len(concl)}")
    if not ticks:
        print("no tick rows yet — accrues only while the Loom runs as the no-arg daemon.")
        return 0
    reg = Counter(r.get("regime") for r in ticks)
    fired = sum(1 for r in ticks if r.get("eff", {}).get("fired"))
    print("regimes:", dict(reg), " · fired ticks:", f"{fired}/{len(ticks)}")
    print("latest tick:", json.dumps(ticks[-1]))
    return 0


# ── control loop ────────────────────────────────────────────────────────────
def _control_loop() -> None:
    global _last_deliberation_ts
    while not _stop.is_set():
        trace = None
        now = time.time()
        with _lock:
            for k in list(_tension):
                _tension[k]["score"] *= DECAY_PER_TICK
                if _tension[k]["score"] < 0.05:
                    _tension.pop(k, None)
            for k in list(_cooldown):                      # prune expired refractory entries
                if now >= _cooldown[k]:
                    del _cooldown[k]
            total = sum(t["score"] for t in _tension.values())
            peak = max((t["score"] for t in _tension.values()), default=0.0)
            n_tensions = len(_tension)
            inflight = _inflight
            at_capacity = not (_inflight < MAX_CONCURRENT)
            nm = _neuromod()                               # read each tick (cheap; for decide + trace)
            # the effect channels the modulators gate (SAME formulas the Loom acts on):
            # arousal + curiosity LOWER the bar to start a thought; focus + caution DEEPEN it.
            eff_threshold = TRIGGER_THRESHOLD * max(0.5, 1.4 - 0.5 * nm["arousal"] - 0.3 * nm["explore"])
            eff_depth = max(3, min(8, round(MAX_STEPS * (0.7 + 0.6 * nm["focus"] + 0.3 * nm["caution"]))))
            candidate = None
            gap_ok = (now - _last_deliberation_ts) >= MIN_GAP_SEC   # global cadence — no firehose
            if not at_capacity and gap_ok:
                ranked = sorted(_tension.items(), key=lambda kv: kv[1]["score"], reverse=True)
                for k, t in ranked:
                    if k in _active or (k in _cooldown and now < _cooldown[k]):
                        continue
                    if _is_telemetry(k):                   # purge bus telemetry that slipped in
                        _tension.pop(k, None)
                        continue
                    if t["score"] >= eff_threshold:
                        candidate = (k, t["label"])
                        _cooldown[k] = now + REFRACTORY_SEC  # per-topic refractory
                        break
            trace = {
                "ts": time.time(), "rec": "tick",
                "regime": _regime(total, peak, n_tensions, inflight),
                "m": {k: round(nm[k], 4) for k in ("arousal", "learning", "explore", "caution", "focus")},
                "E": {"total": round(total, 4), "peak": round(peak, 4), "n": n_tensions},
                "eff": {"threshold": round(eff_threshold, 4), "depth": eff_depth,
                        "fired": bool(candidate), "inflight": inflight, "at_capacity": at_capacity},
                "fired_key": candidate[0] if candidate else None,
            }
        if candidate:
            k, label = candidate
            _last_deliberation_ts = now
            threading.Thread(target=deliberate, args=(k, label),
                             name="loom-deliberate", daemon=True).start()
        if trace is not None:
            _trace(trace)                                  # observational; outside the lock
        _stop.wait(CONTROL_INTERVAL_SEC)


def main(argv) -> int:
    REASON_DIR.mkdir(parents=True, exist_ok=True)
    _load_resolved()                                  # durability ledger (re-fire detection)

    # read-only audit summary (no fuel, no daemon)
    if len(argv) >= 2 and argv[1] == "--trace":
        return _trace_report()

    # manual single-shot: prove a deliberation + the kill/resume keystone test
    if len(argv) >= 2 and argv[1] == "--once":
        label = argv[2] if len(argv) > 2 else "Why does my last-contact memory feel uncertain?"
        key, _ = _topic_key({"text": label})
        out = deliberate(key, label)
        print(json.dumps(out, indent=2))
        return 0

    # resume any deliberation interrupted by a crash/restart (keystone), then exit
    if len(argv) >= 2 and argv[1] == "--resume":
        _resume_open()
        print("[loom] resume pass complete")
        return 0

    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        print("[loom] orion_substrate not importable — check PYTHONPATH", file=sys.stderr)
        return 1

    sub = get_substrate()
    try:
        sub._connect_blocking()
    except Exception:
        pass

    for subject, (kind, weight) in TENSION_SOURCES.items():
        subscribe(subject, _on_signal(kind, weight))
    subscribe(WORKSPACE_SUBJECT, _on_workspace)
    print("[loom] reasoning loop online — listening for tension")

    def _sig(_s, _f):
        _stop.set()
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    _resume_open()                                       # keystone resume on start
    t = threading.Thread(target=_control_loop, name="loom-control", daemon=True)
    t.start()
    while not _stop.is_set():
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
