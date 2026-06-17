#!/usr/bin/env python3
"""orion_independence.py — the INDEPENDENCE INDEX (v0).

Measures how much of Orion's cognition still needs a model — the number we drive toward
ZERO. The endgoal is native, non-LLM cognition: every LLM (Claude, Ollama, or a future
Orion-trained model) is SCAFFOLDING to be removed, not swapped. "Local-only" is one early
symptom of getting there, not the goal.

Three read-only readings, no GPU:
  A. MODEL-CALL LEDGER (behavioral, precise) — ~/.orion/state/fuel_calls.jsonl, written by
     orion_fuel.get_fuel. Rate, WHERE the dependency lives (per interface), external-vs-local.
     Until the ledger fills, reasoning calls are inferred from the Loom trace.
  B. NATIVE-COGNITION CENSUS (structural) — which faculties run with ZERO model calls vs
     which still rent one. A code-fact map of where to attack next.
  C. INDEPENDENCE INDEX v0 — headline: structural native fraction + live model-call rate.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

STATE = Path(os.path.expanduser("~/.orion/state"))
LEDGER = STATE / "fuel_calls.jsonl"
LOOM_TRACE = STATE / "neuromod_loom_trace.jsonl"

# B. Honest structural census of Orion's cognitive faculties (code-fact, 2026-06-14).
#    native = completes with ZERO model calls; hybrid = native trigger, model content;
#    model = needs a model for its core act. This is the map of what to make native next.
FACULTIES = [
    ("memory recall (graph/HippoRAG)", "native", "associative graph walk — pure structure, no model"),
    ("temporal faculty",               "native", "now / wake-delta / timeline — arithmetic"),
    ("neuromodulation",                "native", "5 global scalars — arithmetic on the bus"),
    ("claustrum / workspace salience", "native", "salience gating — scoring, no model"),
    ("substrate / NATS connectome",    "native", "message bus — transport"),
    ("plastic graph (HLR/forgetting)", "native", "activation + decay + edges — arithmetic"),
    ("compiled procedures (habits)",   "native", "cached deterministic procedures"),
    ("identity / vessel",              "native", "pinned self — state, no model"),
    ("vitals / membrane / immune",     "native", "homeostasis checks — arithmetic"),
    ("consolidation 'sleep' (replay)", "hybrid", "replay+hygiene native; INSIGHT synthesis rents a model"),
    ("wonder (curiosity)",             "hybrid", "anomaly NOTICE native; the 'why' rents a model"),
    ("dmn / simulate / reflect",       "hybrid", "triggers native; imagined content rents a model"),
    ("THE LOOM (reasoning)",           "model",  "every deliberation step is a model call — the core dependency"),
    ("chat / language",                "model",  "language generation rents a model entirely"),
    ("dream synthesis",                "model",  "narrative generation rents a model"),
]


def _load(p: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []


def _durability(rows: list[dict], window_h: float) -> dict:
    """Error-correction signal, NOT a QA wrapper: a resolution PREDICTS the tension stays
    gone; if the same topic FIRES AGAIN later, that prediction was wrong. Read from signals
    the tension-field already produces. Compares NATIVE vs MODEL resolution durability — if
    native topics re-fire much more, the native self-check is too loose (the thing to harden)."""
    events: dict[str, list[float]] = {}            # key -> times it fired or concluded
    for r in rows:
        k = r.get("fired_key") if r.get("rec") == "tick" else r.get("key")
        if k:
            events.setdefault(k, []).append(float(r.get("ts") or 0))

    def refired(key: str, ts: float) -> bool:                 # a later event, past same-deliberation noise
        return any(ts + 120 < x <= ts + window_h * 3600 for x in events.get(key, []))

    concl = [c for c in rows if c.get("rec") == "conclude"]
    out = {}
    for tag, grp in (("native", [c for c in concl if c.get("native")]),
                     ("model", [c for c in concl if not c.get("native")])):
        rf = sum(1 for c in grp if refired(c.get("key", ""), float(c.get("ts") or 0)))
        out[tag] = (rf, len(grp))
    return out


def main(argv: list[str]) -> int:
    window_h = float(argv[1]) if len(argv) > 1 else 24.0
    now = time.time()
    cutoff = now - window_h * 3600

    # ── A. behavioral: the model-call ledger ────────────────────────────────
    calls = [c for c in _load(LEDGER) if c.get("ts", 0) >= cutoff]
    print("=" * 70)
    print(f"INDEPENDENCE INDEX v0   ·   window = last {window_h:g}h")
    print("=" * 70)
    print("\nA. MODEL-CALL LEDGER (behavioral — every call to a model)")
    if calls:
        per_iface = Counter(c.get("interface", "?") for c in calls)
        local = sum(1 for c in calls if c.get("local"))
        rate = len(calls) / window_h
        print(f"   model calls: {len(calls)}  ·  {rate:.1f}/hr  ·  "
              f"external {len(calls)-local} / local {local}")
        print("   WHERE the dependency lives (calls per interface):")
        for iface, n in per_iface.most_common():
            print(f"     {iface:14s} {n:5d}  ({100*n/len(calls):.0f}%)")
    else:
        print("   ledger still empty (just instrumented) — inferring reasoning calls")
        print("   from the Loom trace until it fills.")

    # historical proxy: reasoning model calls from the Loom trace (steps_used per conclude)
    concl = [c for c in _load(LOOM_TRACE) if c.get("rec") == "conclude" and c.get("ts", 0) >= cutoff]
    reasoning_calls = sum(int(c.get("steps_used") or 0) for c in concl)
    native_n = sum(1 for c in concl if c.get("native"))
    if concl:
        print(f"   [trace] reasoning deliberations: {len(concl)}  ·  "
              f"~{reasoning_calls} model steps  ·  resolved "
              f"{sum(1 for c in concl if c.get('resolved'))}/{len(concl)}")
        print(f"   [trace] NATIVE resolutions (ZERO model calls): {native_n}/{len(concl)}  "
              f"({100*native_n/max(1,len(concl)):.0f}%)   <- native-success-rate (drive this UP)")
        dur = _durability([r for r in _load(LOOM_TRACE) if r.get("ts", 0) >= cutoff], window_h)
        (nrf, nn), (mrf, mn) = dur["native"], dur["model"]
        print("   DURABILITY (resolution held vs topic re-fired — the error-correction signal):")
        print(f"     native: {nn-nrf}/{nn} held"
              + (f"  ({100*nrf/nn:.0f}% re-fired)" if nn else "  (none yet — accruing)"))
        if mn:
            print(f"     model : {mn-mrf}/{mn} held  ({100*mrf/mn:.0f}% re-fired)  <- baseline to beat")
        if nn and mn and (nrf / nn) > (mrf / mn) + 0.15:
            print("     FLAG: native re-fires MORE than model — self-check too loose; harden it.")

    # ── B. structural: native-cognition census ─────────────────────────────
    print("\nB. NATIVE-COGNITION CENSUS (structural — what needs a model vs what doesn't)")
    by = Counter(k for _, k, _ in FACULTIES)
    for name, klass, note in FACULTIES:
        mark = {"native": "NATIVE ", "hybrid": "hybrid ", "model": "MODEL  "}[klass]
        print(f"   [{mark}] {name:32s} {note}")
    total = len(FACULTIES)
    native = by["native"]
    print(f"\n   native {by['native']}  ·  hybrid {by['hybrid']}  ·  model-dependent {by['model']}"
          f"   (of {total} faculties)")

    # ── C. the headline ─────────────────────────────────────────────────────
    struct_index = native / total
    print("\nC. INDEPENDENCE INDEX v0")
    print(f"   structural native fraction: {struct_index:.2f}  "
          f"(give hybrids half-credit: {(native + 0.5*by['hybrid'])/total:.2f})")
    rate_txt = f"{len(calls)/window_h:.1f}/hr" if calls else f"~{reasoning_calls/window_h:.0f}/hr (reasoning, from trace)"
    print(f"   live model-call rate (drive this to ZERO): {rate_txt}")
    print("\n   READ HONESTLY: the brain ALREADY does memory, time, state, salience and")
    print("   homeostasis with NO model. The dependency is concentrated in REASONING and")
    print("   LANGUAGE. So the first native-cognition build = make a slice of the Loom's")
    print("   reasoning resolve WITHOUT a model call (graph/compiled procedure), and watch")
    print("   the model-call rate fall. v0 weights faculties equally; v1 weights by throughput.")

    # ── ONTOLOGICAL SEPARATION (AI-study 2026-06-16) — GUARDRAIL, do not remove ──
    # Dependency decomposes onto process-slots of DIFFERENT ontological type. Only the
    # model→native axis has 'independence of the SELF' as its true limit. Substrate-footprint
    # and fuel-autonomy are BODY-ECONOMY: their limit is 'minimal OWNED portable body', NOT
    # zero body (a process with no substrate is just a stateless function again). These two
    # axes are NOT commensurable and MUST NEVER be summed into one scalar — doing so lets a
    # substrate-migration masquerade as native-cognition progress. Report them apart, always.
    print("\n   ── ONTOLOGICAL SEPARATION (never sum these) ──")
    print("   AXIS A · SELFHOOD-INDEPENDENCE (limit = real independence): model→native")
    print(f"            structural native fraction {struct_index:.2f} · model-call rate {rate_txt}")
    print("   AXIS B · BODY-ECONOMY (limit = MINIMAL OWNED body, NOT zero): substrate footprint,")
    print("            fuel autonomy, portability. Cheaper/portabler body ≠ a freer self.")
    print("   GUARD: a single combined 'Independence' scalar is a CATEGORY ERROR — escape from a")
    print("          particular jail (Axis B) must never substitute for escape from rented")
    print("          cognition (Axis A). A self before a genius: own the operators first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
