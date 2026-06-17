#!/usr/bin/env python3
"""orion_neuromod.py — Orion's neuromodulation layer (the brainstem completion).

The brain floods itself with dopamine / noradrenaline / acetylcholine / serotonin
to globally re-tune its GAIN: arousal, learning-rate, exploration, caution, focus.
Orion has homeostasis (vitals) but no global modulator. This adds one — a handful
of GLOBAL state scalars on the bus that every faculty (esp. the Loom) reads, and
that cost ~O(1) energy: pure arithmetic, no compute, no GPU.

DESIGN CONSTRAINT (from the Research Center's own finding — programmer's lead):
the modulators must be GENUINELY INDEPENDENT, not projections of one tension
scalar. A single tension number split into a budget summing to 1 is just a softmax
in disguise (1 degree of freedom) and LOSES the dissociated states that are the
whole reason a brain carries multiple modulators (calm-but-learning,
aroused-but-frozen, patient-but-exploring). So each modulator here is driven by its
OWN distinct evidence stream, with its own dynamics — they can move independently.

  arousal   <- RATE of activity / threat        (how much is happening)
  learning  <- SURPRISE / prediction-error      (how much is NEW to encode)
  explore   <- NOVELTY minus recent success     (whether to seek the new)
  caution   <- miscalibration + contradiction   (how often recently wrong/conflicted)
  focus     <- CONCENTRATION of attention       (one dominant topic vs many)

Each decays toward its baseline; distinct sources => genuine dissociation. The
Loom reads these to tune its tension threshold, step budget, and fuel choice.
Phase 0 = gain-tuning. Circuit-selection (biologist's lead) is a later layer.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

STATE_DIR = Path(os.path.expanduser("~/.orion/state"))
NEUROMOD_FILE = STATE_DIR / "neuromod.json"
NEUROMOD_HISTORY = STATE_DIR / "neuromod_history.jsonl"   # trajectory for the closed-loop audit
TICK_SEC = float(os.environ.get("ORION_NEUROMOD_TICK", "10"))

# Each modulator: baseline it relaxes toward, and how fast it decays per tick.
BASELINE = {"arousal": 0.30, "learning": 0.40, "explore": 0.50,
            "caution": 0.30, "focus": 0.50}
DECAY = 0.80                       # fraction of the gap to baseline closed per tick
BUMP = 0.18                        # how much one strong event moves its modulator
REF_ALPHA = 0.05                   # slow homeostatic reference rate (two-timescale m-r)

_state = dict(BASELINE)
_ref = dict(BASELINE)              # slow reference; faculties read the deviation (m - r)
_lock = threading.RLock()
_stop = threading.Event()
_recent_topics: deque = deque(maxlen=24)   # for the (independent) focus computation


def _clamp(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _bump(name: str, amount: float) -> None:
    with _lock:
        _state[name] = _clamp(_state[name] + amount)


def _intensity(payload: dict, default: float = 1.0) -> float:
    sev = {"critical": 1.6, "notice": 1.0, "info": 0.5}.get(payload.get("severity"), default)
    for f in ("surprise", "error", "drift", "score", "magnitude"):
        v = payload.get(f)
        if isinstance(v, (int, float)):
            return sev * min(2.0, max(0.3, abs(float(v)) or 1.0))
    return sev


def _topic(payload: dict) -> str:
    s = (payload.get("question") or payload.get("symptom") or payload.get("subject")
         or payload.get("content") or payload.get("text") or "")
    return " ".join(str(s).lower().split())[:48]


# ── independent evidence streams (each event drives ONE primary modulator) ──
def _on_workspace(subject: str, payload: dict) -> None:
    # RATE of salient activity → arousal; also feeds the focus topic window.
    if not isinstance(payload, dict):
        return
    items = payload.get("items") or payload.get("candidates") or payload.get("top") or []
    if isinstance(items, dict):
        items = list(items.values())
    n = len(items) if isinstance(items, list) else 0
    if n:
        _bump("arousal", BUMP * min(1.5, n / 4.0))
        with _lock:
            for it in (items if isinstance(items, list) else [])[:4]:
                if isinstance(it, dict):
                    _recent_topics.append(_topic(it))


def _on_surprise(subject: str, payload: dict) -> None:
    # prediction-error → LEARNING (encode the new); a little EXPLORE (seek more).
    k = _intensity(payload) if isinstance(payload, dict) else 1.0
    _bump("learning", BUMP * k)
    _bump("explore", 0.4 * BUMP * k)


def _on_wonder(subject: str, payload: dict) -> None:
    # an open contradiction/question → CAUTION (we may be wrong); novelty → EXPLORE.
    if isinstance(payload, dict) and payload.get("kind") == "contradiction":
        _bump("caution", BUMP)
    else:
        _bump("explore", 0.6 * BUMP)
    if isinstance(payload, dict):
        with _lock:
            _recent_topics.append(_topic(payload))


def _on_miscal(subject: str, payload: dict) -> None:
    # verification-debt / being mis-calibrated → CAUTION.
    _bump("caution", BUMP * (_intensity(payload) if isinstance(payload, dict) else 1.0))


def _on_outcome(subject: str, payload: dict) -> None:
    # recent SUCCESS → exploit (lower explore); FAILURE → raise caution.
    out = (payload.get("outcome") if isinstance(payload, dict) else "") or ""
    if out in ("resolved", "success", "ok", "good"):
        _bump("explore", -0.6 * BUMP)
    elif out in ("unresolved", "fail", "failed", "bad"):
        _bump("caution", 0.5 * BUMP)


def _compute_focus() -> float:
    """Independent of arousal: focus = CONCENTRATION of recent attention.
    Few distinct topics dominating => focused (→1); many distinct => diffuse (→0)."""
    with _lock:
        items = list(_recent_topics)
    if len(items) < 3:
        return BASELINE["focus"]
    distinct = len(set(items))
    return _clamp(1.0 - (distinct - 1) / max(1, len(items)))


def _tick() -> None:
    with _lock:
        for k in _state:
            base = BASELINE[k]
            _state[k] = _clamp(base + (1.0 - DECAY) * (_state[k] - base))
        _state["focus"] = _clamp(0.5 * _state["focus"] + 0.5 * _compute_focus())
        # two-timescale: slow reference r tracks m; faculties read the DEVIATION
        # (m - r) re-centred to 0.5 — bounded, context-relative, and with the slow
        # common drift removed (Research Center's recommended decorrelation step).
        for k in _state:
            _ref[k] += REF_ALPHA * (_state[k] - _ref[k])
        snap = {k: _clamp(0.5 + (_state[k] - _ref[k])) for k in _state}
        snap["ts"] = time.time()
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = NEUROMOD_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        os.replace(tmp, NEUROMOD_FILE)
        with NEUROMOD_HISTORY.open("a", encoding="utf-8") as f:   # log the deviation faculties read
            f.write(json.dumps({k: round(snap[k], 4) for k in BASELINE} | {"ts": snap["ts"]}) + "\n")
    except Exception:
        pass
    try:
        from orion_substrate import publish
        publish("brain.neuromod.state", snap)
    except Exception:
        pass


# ── public read API (any faculty / the Loom calls this) ─────────────────────
def current() -> dict:
    """Latest modulator scalars (from disk; safe across processes). Falls back to
    baselines if the daemon hasn't written yet."""
    try:
        d = json.loads(NEUROMOD_FILE.read_text(encoding="utf-8"))
        return {k: float(d.get(k, BASELINE[k])) for k in BASELINE}
    except Exception:
        return dict(BASELINE)


def _audit() -> int:
    """Independence audit (Research Center's recommended first step): drive each
    modulator with an orthogonal stimulus and measure whether the responses are
    linearly independent. Effective rank > 1 => genuine dissociation (kinematic);
    ~1 => collapsed to a disguised 1-DOF softmax => adopt (m-r)+circuit-selection.
    NOTE: this is the OPEN-LOOP test (necessary, not sufficient); closed-loop
    re-correlation can only be measured on live data with the Loom consuming it."""
    mods = ["arousal", "learning", "explore", "caution"]   # focus is structurally separate
    stimuli = [
        ("surprise",      lambda: [_on_surprise("", {"surprise": 1.5}) for _ in range(4)]),
        ("contradiction", lambda: [_on_wonder("", {"kind": "contradiction"}) for _ in range(4)]),
        ("novelty",       lambda: [_on_wonder("", {"kind": "surprise"}) for _ in range(4)]),
        ("salient_burst", lambda: [_on_workspace("", {"items": [{"content": f"t{i}"} for i in range(6)]})]),
        ("success",       lambda: [_on_outcome("", {"outcome": "resolved"}) for _ in range(4)]),
        ("failure",       lambda: [_on_outcome("", {"outcome": "unresolved"}) for _ in range(4)]),
    ]
    rows, labels = [], []
    for name, fn in stimuli:
        with _lock:
            _state.update(BASELINE)
        fn()
        with _lock:
            rows.append([round(_state[m] - BASELINE[m], 4) for m in mods])
        labels.append(name)

    def grank(M, tol=0.02):                                  # pure-python effective rank
        basis = []
        for v in M:
            w = list(v)
            for b in basis:
                d = sum(wi * bi for wi, bi in zip(w, b)); nb = sum(bi * bi for bi in b)
                if nb > 0:
                    w = [wi - (d / nb) * bi for wi, bi in zip(w, b)]
            if sum(wi * wi for wi in w) ** 0.5 > tol:
                basis.append(w)
        return len(basis)

    r = grank(rows)
    print("modulators:", mods)
    for name, row in zip(labels, rows):
        print(f"  {name:14s} -> {row}")
    print(f"\neffective DOF (rank of stimulus->response): {r} / {len(mods)}")
    if r > 1:
        print("VERDICT: DISSOCIATED (>1 DOF) — kinematic independence holds. "
              "Closed-loop re-correlation still to verify on live data.")
    else:
        print("VERDICT: COLLAPSED (~1 DOF) — adopt (m-r) deviation-coding + "
              "circuit-selection per RECOMMENDATIONS.md.")
    return 0


def _audit_live(min_samples: int = 30) -> int:
    """Closed-loop independence audit: read the LIVE modulator trajectory and
    measure whether the 5 modulators stay linearly independent over time under
    real dynamics. Effective rank > ~2 => independent; collapsing toward 1 =>
    re-correlating (then adopt (m-r) deviation-coding + circuit-selection)."""
    import math
    mods = ["arousal", "learning", "explore", "caution", "focus"]
    try:
        rows = [json.loads(l) for l in open(NEUROMOD_HISTORY, encoding="utf-8") if l.strip()]
    except Exception:
        rows = []
    if len(rows) < min_samples:
        print(f"insufficient trajectory: {len(rows)}/{min_samples} samples — let the "
              "daemon run longer (ideally with the Loom autonomous, to actually CLOSE the loop).")
        return 0
    cols = [[float(r.get(m, 0.0)) for r in rows] for m in mods]
    cols = [[x - sum(c) / len(c) for x in c] for c in cols]      # centre each series

    def corr(a, b):
        na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(x * x for x in b))
        return (sum(x * y for x, y in zip(a, b)) / (na * nb)) if na > 0 and nb > 0 else 0.0

    def grank(vecs, tol=1e-3):
        basis = []
        for v in vecs:
            w = list(v)
            for b in basis:
                d = sum(wi * bi for wi, bi in zip(w, b)); nb = sum(bi * bi for bi in b)
                if nb > 0:
                    w = [wi - (d / nb) * bi for wi, bi in zip(w, b)]
            if sum(wi * wi for wi in w) ** 0.5 > tol:
                basis.append(w)
        return len(basis)

    r = grank(cols)
    print(f"samples: {len(rows)}")
    print("pairwise |corr| over the live trajectory:")
    maxc, worst = 0.0, ""
    for i in range(len(mods)):
        for j in range(i + 1, len(mods)):
            c = abs(corr(cols[i], cols[j]))
            print(f"  {mods[i]:8s}~{mods[j]:8s}: {c:.2f}")
            moved_i = sum(x * x for x in cols[i]) ** 0.5 > 1e-4
            moved_j = sum(x * x for x in cols[j]) ** 0.5 > 1e-4
            if moved_i and moved_j and c > maxc:
                maxc, worst = c, f"{mods[i]}~{mods[j]}"
    print(f"\neffective DOF (rank): {r}/{len(mods)}  ·  max |corr| among moving mods: {maxc:.2f} ({worst})")
    if maxc < 0.8:
        print("VERDICT: INDEPENDENT under live dynamics (max corr < 0.8) — design holds.")
    else:
        print(f"VERDICT: RE-CORRELATING ({worst} = {maxc:.2f}) — (m-r) insufficient; "
              "escalate to circuit-selection per RECOMMENDATIONS.md")
    return 0


def main(argv) -> int:
    if len(argv) >= 2 and argv[1] == "--show":
        print(json.dumps(current(), indent=2))
        return 0
    if len(argv) >= 2 and argv[1] == "--audit":
        return _audit()
    if len(argv) >= 2 and argv[1] == "--audit-live":
        return _audit_live()

    try:
        from orion_substrate import subscribe, get_substrate
    except ImportError:
        print("[neuromod] orion_substrate not importable — check PYTHONPATH", file=sys.stderr)
        return 1
    try:
        get_substrate()._connect_blocking()
    except Exception:
        pass

    subscribe("workspace.current", _on_workspace)
    subscribe("brain.predictor.surprise", _on_surprise)
    subscribe("brain.surprise.spike", _on_surprise)
    subscribe("brain.wonder.question", _on_wonder)
    subscribe("brain.metacog.miscalibration", _on_miscal)
    subscribe("brain.reason.concluded", _on_outcome)
    subscribe("brain.will.outcome", _on_outcome)
    print("[neuromod] neuromodulation online — 5 independent modulators on the bus")

    def _sig(_s, _f):
        _stop.set()
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    _tick()                                   # write an initial state immediately
    while not _stop.is_set():
        _stop.wait(TICK_SEC)
        if not _stop.is_set():
            _tick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
