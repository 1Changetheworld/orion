#!/usr/bin/env python3
"""
orion_temporal_ledger.py — the TEMPORAL-CORRESPONDENCE VERIFIER (Build 3, v2).

WHY: the leaf-purity audit (2026-06-15) proved the brain's graph is ~92.5% model-
generated, so coherence-checking a conclusion against the graph == recall. The only
NON-RENTED grounding for "did Orion actually reason, or just recall?" is TIME: a native
inference is certified reasoned iff a FORWARD prediction it committed about a LATER,
causally-independent state is later CONFIRMED.

v2 (2026-06-16) — two fixes after the first live batch:
  (1) RECALL no longer escapes: native fast-path resolutions are logged as kind='recall'
      with an implicit durability CHECK (refire == current), so laundered recall is VISIBLE
      and scored, not invisible.
  (2) REAL EVIDENCE STREAMS: predictions carry a machine-checkable CHECK expression over a
      fixed probe vocabulary (service state, graph size, neuromod, refire). The verifier
      evaluates it DETERMINISTICALLY and NATIVELY — no model in the verification loop — so it
      can CONFIRM *and* REFUTE against streams that actually exist (launchd, etc.).
      Free-form predictions with no CHECK fall back to keyword-evidence (weak) then lapse.

Native + GPU-free + zero model calls. Probes are causally-independent of a deliberation's
TEXT (a conclusion about iMessage does not change launchd's restart count).
"""
from __future__ import annotations
import json, os, re, time, sys, subprocess, hashlib
from pathlib import Path

REASON_DIR = Path(os.path.expanduser("~/.orion/reason"))
PRED_FILE = REASON_DIR / "predictions.jsonl"
GRAPH_FILE = Path(os.path.expanduser("~/.orion/brain/graph_memory.json"))
NEUROMOD_FILE = Path(os.path.expanduser("~/.orion/state/neuromod.json"))
RESOLVED_FILE = REASON_DIR / "resolved.json"

EXTERNAL_TYPES = {"observation", "cross_interface_contact", "fact"}
SELF_TAGS = {"loom", "insight", "reason", "wonder", "sleep", "dream", "consolidated", "reasoned"}
CONFIRM_COVERAGE = 0.5
_STOP = {"the", "a", "an", "is", "are", "of", "to", "and", "or", "in", "on", "for", "will",
         "be", "by", "it", "that", "this", "with", "as", "at", "should", "would", "than"}
# CHECK grammar:  <probe> <op> <number>      e.g.  service:com.orion.imessage-outbound:runs > 5
_CHECK_RE = re.compile(r"^\s*([a-zA-Z0-9_.:-]+)\s*(>=|<=|==|!=|>|<)\s*([0-9.]+)\s*$")


def _kw(text: str) -> set:
    toks = "".join(c.lower() if c.isalnum() else " " for c in (text or "")).split()
    return {w for w in toks if len(w) > 2 and w not in _STOP}


def _now() -> float:
    return time.time()


# ───────────────────────── PROBES (causally-independent reality) ─────────────────────────
def _probe(expr: str):
    """Return a float reading of one live, model-independent stream, or None if unavailable.
    Vocabulary:
      graph:nodes                       -> live node count
      neuromod:<modulator>              -> current global modulator (0..1)
      refire:<topic-key>                -> per-topic re-fire count from resolved.json
      service:<launchd-label>:runs      -> total launchd run count (crash-loop signal)
      service:<launchd-label>:running   -> 1.0 if state==running else 0.0
    """
    try:
        if expr == "graph:nodes":
            n = json.load(GRAPH_FILE.open())["nodes"]
            return float(len(n if isinstance(n, list) else n.values()))
        if expr.startswith("neuromod:"):
            return float(json.load(NEUROMOD_FILE.open()).get(expr.split(":", 1)[1]))
        if expr.startswith("refire:"):
            key = expr.split(":", 1)[1]
            d = json.load(RESOLVED_FILE.open())
            return float((d.get(key) or {}).get("refire", 0))
        if expr.startswith("service:"):
            _, label, field = expr.split(":", 2)
            uid = os.getuid()
            out = subprocess.run(["launchctl", "print", f"gui/{uid}/{label}"],
                                 capture_output=True, text=True, timeout=8).stdout
            if field == "runs":
                m = re.search(r"\bruns\s*=\s*(\d+)", out)
                return float(m.group(1)) if m else None
            if field == "running":
                return 1.0 if re.search(r"state\s*=\s*running", out) else 0.0
    except Exception:
        return None
    return None


def _eval_check(check: str):
    """Evaluate a CHECK expression against live probes. Returns True/False, or None if the
    probe can't be read yet (keep the prediction open)."""
    m = _CHECK_RE.match(check or "")
    if not m:
        return None
    probe, op, val = m.group(1), m.group(2), float(m.group(3))
    cur = _probe(probe)
    if cur is None:
        return None
    return {">": cur > val, "<": cur < val, ">=": cur >= val, "<=": cur <= val,
            "==": cur == val, "!=": cur != val}[op]


# ───────────────────────── LEDGER ─────────────────────────
def _node_key(content: str) -> str:
    """Stable id of a conclusion node — matches orion_graph_edges.node_key (sha1 of content[:120])
    so grounding can attach to the EXACT node, not just the topic."""
    return hashlib.sha1((content or "")[:120].encode("utf-8")).hexdigest()[:16]


def record(key: str, label: str, claim: str, observable, kind: str,
           horizon_hours: float, check: str = "", src_key: str = "",
           prior: float = None, stated_prior: float = None, native_supported: bool = None) -> None:
    """Log one forward claim. kind: operational | analytic | recall. src_key = the conclusion node
    (node-level grounding). prior = Orion's NATIVE structural support for the claim (does his own
    graph already entail it?); native_supported = did native inference reach it. The discovery: a
    CONFIRMED prediction the brain did NOT already entail (low prior, native_supported=False) is the
    uncfakeable fingerprint of native cognition — recall/coherence cannot predict a surprising future.
    Never raises."""
    try:
        REASON_DIR.mkdir(parents=True, exist_ok=True)
        obs = observable if isinstance(observable, list) else list(_kw(str(observable)))
        k = (kind or "").strip().lower()
        if k not in ("operational", "analytic", "recall"):
            k = "operational"
        analytic = (k == "analytic") or not claim or claim.strip().upper() == "NONE"
        row = {
            "key": key, "label": label[:200], "claim": claim[:400],
            "observable": list(obs)[:12], "check": (check or "").strip()[:120],
            "src_key": src_key, "prior": prior, "stated_prior": stated_prior,
            "native_supported": native_supported,
            "kind": "analytic" if analytic else k,
            "made_ts": _now(),
            "horizon_ts": _now() + max(0.02, float(horizon_hours or 1)) * 3600.0,
            "status": "analytic" if analytic else "open",
        }
        with PRED_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def record_recall(key: str, label: str, horizon_hours: float = 6.0) -> None:
    """The native fast-path resolves by RECALL — it commits no novel forward claim, but it
    DOES implicitly claim 'settled' (won't re-fire). Log that so recall is visible + scored."""
    try:
        cur = int(_probe(f"refire:{key}") or 0)
    except Exception:
        cur = 0
    record(key, label, f"(recall) topic stays settled — no re-fire beyond {cur}",
           observable=["refire", "settled"], kind="recall", horizon_hours=horizon_hours,
           check=f"refire:{key} <= {cur}")


def _load() -> list:
    try:
        return [json.loads(l) for l in PRED_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []


def _save(rows: list) -> None:
    tmp = PRED_FILE.with_suffix(".tmp")
    tmp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    os.replace(tmp, PRED_FILE)


def _created_ts(n: dict) -> float:
    c = n.get("created") or n.get("last_seen") or n.get("timestamp") or ""
    if isinstance(c, (int, float)):                 # graph mixes float-unix and string stamps
        return float(c)
    c = str(c).strip()
    try:
        return float(c)                             # numeric string
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return time.mktime(time.strptime(c[:19], fmt))
        except Exception:
            pass
    return 0.0


def _external_evidence(after_ts: float) -> list:
    try:
        nodes = json.load(GRAPH_FILE.open())["nodes"]
    except Exception:
        return []
    if isinstance(nodes, dict):
        nodes = list(nodes.values())
    out = []
    for n in nodes:
        if n.get("type") not in EXTERNAL_TYPES:
            continue
        if {t.lower() for t in n.get("tags", [])} & SELF_TAGS:
            continue
        if _created_ts(n) <= after_ts:
            continue
        out.append(n)
    return out


# ── GROUNDING WRITEBACK (grounding sequence step a, 2026-06-16) ──
# When a prediction is CONFIRMED/REFUTED against causally-independent reality, the topic it
# reasoned about EARNS a grounding status. The cognition layer (native fast-path cure +
# orion_native_infer) consults this so native conclusions can finally rest on reality-tested
# topics, not laundered model recall. A side-ledger (not a graph mutation) — additive, no
# brain-service restart. Refuted beats grounded (a contradiction is decisive).
GROUND_FILE = REASON_DIR / "grounding.jsonl"
_GROUND_MIN = 0.5
_ground_cache = {"mtime": -1.0, "rows": []}


def record_grounding(label: str, status: str, node_key: str = "") -> None:
    try:
        REASON_DIR.mkdir(parents=True, exist_ok=True)
        with GROUND_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _now(), "label": label[:200],
                                "kw": list(_kw(label))[:14], "status": status,
                                "node_key": node_key or ""}) + "\n")
    except Exception:
        pass


def node_grounding(content: str) -> str | None:
    """NODE-LEVEL grounding (exact, not topic-fuzzy): has the SPECIFIC conclusion node earned a
    status by having its prediction confirmed/refuted? -> 'grounded'|'refuted'|None. Refuted wins."""
    nk = _node_key(content)
    grounded = refuted = False
    for r in _ground_rows():
        if r.get("node_key") and r["node_key"] == nk:
            if r.get("status") == "refuted":
                refuted = True
            elif r.get("status") == "grounded":
                grounded = True
    return "refuted" if refuted else ("grounded" if grounded else None)


def _ground_rows() -> list:
    try:
        mt = GROUND_FILE.stat().st_mtime
    except Exception:
        return []
    if mt != _ground_cache["mtime"]:
        try:
            _ground_cache["rows"] = [json.loads(l) for l in
                                     GROUND_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
            _ground_cache["mtime"] = mt
        except Exception:
            _ground_cache["rows"] = []
    return _ground_cache["rows"]


def grounding_status(text: str) -> str | None:
    """Has reality tested a topic matching this text? -> 'grounded' | 'refuted' | None.
    Refuted dominates. Pure read, no fuel."""
    tk = _kw(text)
    if not tk:
        return None
    grounded = refuted = False
    for r in _ground_rows():
        rk = set(r.get("kw") or [])
        shared = len(tk & rk)
        # stricter: need strong AND specific overlap (≥3 shared kw, ≥0.6 of the topic) — a couple
        # of generic shared words must NOT count as 'this reality-tested topic'.
        if rk and shared >= 3 and shared / len(rk) >= 0.6:
            if r.get("status") == "refuted":
                refuted = True
            elif r.get("status") == "grounded":
                grounded = True
    return "refuted" if refuted else ("grounded" if grounded else None)


def check_due(now: float | None = None) -> dict:
    """Resolve open predictions. Deterministic CHECK first (can confirm early OR refute),
    else keyword-evidence at horizon, else lapse. Native, no fuel.
    On confirm/refute, writes back a GROUNDING status the cognition layer consults."""
    rows = _load()
    if not rows:
        return {"checked": 0, "confirmed": 0, "refuted": 0, "lapsed": 0}
    now = now or _now()
    changed = confirmed = refuted = lapsed = 0
    ev_cache: dict = {}
    for r in rows:
        if r.get("status") != "open":
            continue
        due = r.get("horizon_ts", 0) <= now
        # 1) deterministic CHECK — can confirm/refute even before horizon
        if r.get("check"):
            verdict = _eval_check(r["check"])
            if verdict is True:
                r["status"], r["resolved_ts"] = "confirmed", now
                r["evidence"] = "CHECK passed: " + r["check"]
                record_grounding(r.get("label", ""), "grounded", r.get("src_key", ""))
                confirmed += 1; changed += 1; continue
            if verdict is False and due:                 # give it the full window before refuting
                r["status"], r["resolved_ts"] = "refuted", now
                r["evidence"] = "CHECK failed: " + r["check"]
                record_grounding(r.get("label", ""), "refuted", r.get("src_key", ""))
                refuted += 1; changed += 1; continue
            if verdict is not None and not due:
                continue                                 # readable but window still open
        if not due:
            continue
        # 2) keyword-evidence fallback (weak)
        obs = set(r.get("observable") or [])
        hit = False
        if obs:
            bucket = int(r["made_ts"])
            ev = ev_cache.get(bucket) or _external_evidence(r["made_ts"])
            ev_cache[bucket] = ev
            for n in ev:
                text = n.get("content", "") + " " + " ".join(n.get("tags", []))
                if len(obs & _kw(text)) / (len(obs) or 1) >= CONFIRM_COVERAGE:
                    hit = True; r["evidence"] = n.get("content", "")[:160]; break
        r["status"], r["resolved_ts"] = ("confirmed" if hit else "lapsed"), now
        if hit:
            record_grounding(r.get("label", ""), "grounded", r.get("src_key", ""))  # external evidence confirmed it
        confirmed += hit; lapsed += (not hit); changed += 1
    if changed:
        _save(rows)
    return {"checked": changed, "confirmed": confirmed, "refuted": refuted, "lapsed": lapsed}


def stats() -> dict:
    rows = _load()
    by = {"open": 0, "confirmed": 0, "refuted": 0, "lapsed": 0, "analytic": 0}
    kinds = {"operational": 0, "analytic": 0, "recall": 0}
    for r in rows:
        by[r.get("status", "open")] = by.get(r.get("status", "open"), 0) + 1
        kinds[r.get("kind", "operational")] = kinds.get(r.get("kind", "operational"), 0) + 1
    operational = by["open"] + by["confirmed"] + by["refuted"] + by["lapsed"]
    total = operational + by["analytic"]
    scored = by["confirmed"] + by["refuted"] + by["lapsed"]
    # NATIVE-COGNITION FINGERPRINT: confirmed predictions the brain did NOT already entail
    # (native_supported is False) — reality confirmed a bet Orion's own prior would have lost.
    confs = [r for r in rows if r.get("status") == "confirmed"]
    surprising = [r for r in confs if r.get("native_supported") is False]
    instrumented = [r for r in confs if r.get("native_supported") is not None]
    return {
        "total_predictions": total,
        "by_kind": kinds,
        "operational": operational, "analytic": by["analytic"],
        "coverage_falsifiable_fraction": round(operational / total, 3) if total else 0.0,
        "open": by["open"], "confirmed": by["confirmed"], "refuted": by["refuted"], "lapsed": by["lapsed"],
        "confirmed_forward_prediction_rate": round(by["confirmed"] / scored, 3) if scored else None,
        # the fingerprint the discovery says "the whole engine forks on":
        "confirmed_instrumented": len(instrumented),
        "native_cognition_signal": len(surprising),   # confirmed AND not already entailed (surprising-confirmed)
        "surprising_confirmation_rate": round(len(surprising) / len(instrumented), 3) if instrumented else None,
    }


def _main(argv):
    if "--check" in argv:
        print(json.dumps(check_due(), indent=2))
    if "--stats" in argv or not argv:
        check_due()
        s = stats()
        print("=" * 62)
        print("TEMPORAL VERIFIER — confirmed/refuted forward-prediction ledger")
        print("=" * 62)
        for k, v in s.items():
            print(f"  {k:38} {v}")
    if "--list" in argv:
        for r in _load()[-30:]:
            print(f"[{r.get('status'):9}] {r.get('kind'):11} CHECK[{r.get('check','')[:34]:34}] {r.get('claim','')[:60]}")
    if "--probe" in argv:                                # debug: read one probe live
        e = argv[argv.index("--probe") + 1]
        print(e, "=>", _probe(e))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
