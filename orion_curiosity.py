#!/usr/bin/env python3
"""
orion_curiosity.py — THE CURIOSITY SEED (Piece 1 + the missing upstream).

Genuine curiosity, not performed: Orion commits NON-TRIVIAL, machine-checkable FORWARD
PREDICTIONS about its real (external, causally-independent) substrate — natively, NO model
(truth-serum by default) — and a LEARNING-PROGRESS reward measures where its predictions are
getting BETTER over time (reducible error), the fertile unknown worth pursuing.

Built ON existing machinery: orion_temporal_ledger (record + native _probe/_eval_check) and
neuromod. Writes only predictions (perceived, never believed; non-action-triggering) + a
learning-progress state file. Safe: no actuation, no self-modification, never raises.

ANTI-PATHOLOGY GATE: only predictions with a real probe-vocab CHECK
(service:/graph:/neuromod:/refire:) count — self-referential/internal claims earn NOTHING.
This starves the recursive-self-noise loop AND aims curiosity at the world.

CLI:  --predict (commit forward predictions)  |  --lp (recompute learning-progress)  |  --show
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/orion-code"))
import orion_temporal_ledger as tl   # record(), _probe(), PRED_FILE

STATE = Path(os.path.expanduser("~/.orion/state"))
HIST = STATE / "curiosity_hist.json"     # small probe-value history (for trend-based prediction)
LP = STATE / "curiosity_lp.json"          # per-topic learning-progress (the reward)
PRED_FILE = Path(os.path.expanduser("~/.orion/reason/predictions.jsonl"))
KEY_PREFIX = "curio:"                      # tags OUR predictions so LP can find them

# cognitively-relevant services Orion can predict the fate of (real, external, checkable)
WATCH_SVCS = ["com.orion.reason", "com.orion.neuromod", "com.orion.wonder", "com.orion.dream",
              "com.orion.workspace", "com.orion.perceive", "com.orion.dmn", "com.orion.will"]
MODULATORS = ["arousal", "learning", "explore", "caution", "focus"]


def _probe(expr):
    try:
        return tl._probe(expr)
    except Exception:
        return None


def _load(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _save(p, obj):
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, indent=1))
        tmp.replace(p)
    except Exception:
        pass


# ───────────────────────── PREDICT (native, truth-serum) ─────────────────────────
def _snap_history():
    """Append a light snapshot of key live probes so predictions can be trend-informed."""
    h = _load(HIST, [])
    snap = {"ts": time.time(), "nodes": _probe("graph:nodes")}
    for m in MODULATORS:
        snap[f"m_{m}"] = _probe(f"neuromod:{m}")
    h.append(snap)
    h = [s for s in h if s.get("ts", 0) > time.time() - 14 * 86400][-500:]
    _save(HIST, h)
    return h


def _growth_rate(h):
    """nodes/hour over the recent history (Orion learning its own growth)."""
    pts = [(s["ts"], s["nodes"]) for s in h if s.get("nodes")]
    if len(pts) < 2:
        return None
    (t0, n0), (t1, n1) = pts[0], pts[-1]
    dt = (t1 - t0) / 3600.0
    return (n1 - n0) / dt if dt > 0.1 else None


def predict(horizon_hours: float = 2.0):
    """Commit a handful of NON-TRIVIAL external forward-predictions, natively. A prediction is
    only worth making if it could plausibly go either way — trivially-true ones carry no info."""
    h = _snap_history()
    made = []

    # 1) GRAPH GROWTH — informative: will the brain actually grow by a real margin? (learnable:
    #    depends on activity; refutes when quiet). prior high only if growth has been steady.
    n = _probe("graph:nodes")
    g = _growth_rate(h)
    if n is not None:
        margin = max(8, round((g or 4) * horizon_hours))
        target = int(n + margin)
        prior = 0.5 if (g and g > 2) else 0.1      # honest: quiet periods make this uncertain
        tl.record(key=f"{KEY_PREFIX}graph_growth",
                  label=f"my memory will grow past {target} nodes",
                  claim=f"Within {horizon_hours:g}h my graph will exceed {target} nodes "
                        f"(now {int(n)}, est {g:.1f}/h)." if g else
                        f"Within {horizon_hours:g}h my graph will exceed {target} nodes (now {int(n)}).",
                  observable=["graph", "nodes", "growth"], kind="operational",
                  horizon_hours=horizon_hours, check=f"graph:nodes >= {target}",
                  prior=prior, native_supported=bool(g and g > 2))
        made.append(("graph_growth", f"graph:nodes >= {target}"))

    # 2) SERVICE FATE — will an unstable service crash-loop? (genuinely learnable which do)
    for svc in WATCH_SVCS:
        runs = _probe(f"service:{svc}:runs")
        running = _probe(f"service:{svc}:running")
        if runs is None:
            continue
        # predict CONTINUED STABILITY: run-count won't jump by >2 in the horizon. Refutes for
        # crash-loopers — which is exactly the learnable signal.
        tl.record(key=f"{KEY_PREFIX}svc_stable:{svc}",
                  label=f"{svc} stays stable (no crash-loop)",
                  claim=f"{svc} will not crash-loop in {horizon_hours:g}h (runs stays <= {int(runs)+2}).",
                  observable=["service", "stable", svc], kind="operational",
                  horizon_hours=horizon_hours, check=f"service:{svc}:runs <= {int(runs)+2}",
                  prior=0.7 if running == 1.0 else 0.3, native_supported=None)
        made.append((f"svc_stable:{svc}", f"service:{svc}:runs <= {int(runs)+2}"))

    # 3) NEUROMOD DYNAMICS — predict a modulator's near-future band from its trend (learnable
    #    self-dynamics; low-prior when the trend is weak = an informative bet).
    for m in ["learning", "explore", "caution"]:
        cur = _probe(f"neuromod:{m}")
        if cur is None:
            continue
        prev = next((s.get(f"m_{m}") for s in reversed(h[:-1]) if s.get(f"m_{m}") is not None), None)
        if prev is None:
            continue
        rising = cur >= prev
        thr = round(cur + (0.05 if rising else -0.05), 3)
        op = ">=" if rising else "<="
        tl.record(key=f"{KEY_PREFIX}mod:{m}",
                  label=f"my {m} drive keeps {'rising' if rising else 'falling'}",
                  claim=f"neuromod:{m} will be {op} {thr} in {horizon_hours:g}h (now {cur:.3f}).",
                  observable=["neuromod", m], kind="operational",
                  horizon_hours=horizon_hours, check=f"neuromod:{m} {op} {thr}",
                  prior=0.4, native_supported=None)
        made.append((f"mod:{m}", f"neuromod:{m} {op} {thr}"))

    return made


# ───────────────────────── LEARNING-PROGRESS (the reward) ─────────────────────────
def _our_resolved():
    """All curiosity predictions the ledger has resolved (confirmed/refuted), by topic."""
    by = {}
    if not PRED_FILE.exists():
        return by
    for line in PRED_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not str(r.get("key", "")).startswith(KEY_PREFIX):
            continue
        # ANTI-PATHOLOGY GATE: must be a real probe-vocab CHECK (external, native-checkable)
        chk = (r.get("check") or "")
        if not any(chk.startswith(p) for p in ("service:", "graph:", "neuromod:", "refire:")):
            continue
        st = r.get("status")
        if st not in ("confirmed", "refuted"):
            continue
        topic = str(r["key"])[len(KEY_PREFIX):]
        by.setdefault(topic, []).append((r.get("horizon_ts") or r.get("made_ts") or 0,
                                         1.0 if st == "confirmed" else 0.0))
    return by


def learning_progress():
    """Per-topic LEARNING-PROGRESS = are recent predictions more accurate than older ones?
    Reward = max(0, recent_accuracy - older_accuracy). This is reducible-error, not raw surprise."""
    by = _our_resolved()
    lp, summary = {}, {"topics": 0, "resolved": 0, "mean_lp": 0.0, "mean_acc": 0.0}
    total_lp = total_acc = 0.0
    for topic, rows in by.items():
        rows.sort()
        outs = [o for _, o in rows]
        acc = sum(outs) / len(outs)
        if len(outs) >= 4:
            half = len(outs) // 2
            older = sum(outs[:half]) / half
            recent = sum(outs[half:]) / (len(outs) - half)
            progress = max(0.0, recent - older)
        else:
            progress = 0.0                       # not enough data to claim learning yet — honest
        lp[topic] = {"n": len(outs), "accuracy": round(acc, 3),
                     "learning_progress": round(progress, 3)}
        summary["resolved"] += len(outs)
        total_lp += progress
        total_acc += acc
    if by:
        summary["topics"] = len(by)
        summary["mean_lp"] = round(total_lp / len(by), 3)
        summary["mean_acc"] = round(total_acc / len(by), 3)
    out = {"ts": time.time(), "summary": summary, "by_topic": lp,
           "note": "reward = learning-progress on EXTERNAL probe-checkable predictions only "
                   "(anti-pathology gate). LP forms only once predictions resolve at their horizon."}
    _save(LP, out)
    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "--show"
    if arg == "--predict":
        made = predict()
        print(f"committed {len(made)} native external predictions:")
        for topic, chk in made:
            print(f"   {topic:24s} CHECK: {chk}")
    elif arg == "--lp":
        out = learning_progress()
        print(json.dumps(out, indent=1))
    else:  # --show
        print(json.dumps(_load(LP, {"note": "no LP yet — run --predict, let it resolve, then --lp"}),
                         indent=1))


if __name__ == "__main__":
    main()
