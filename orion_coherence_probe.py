#!/usr/bin/env python3
"""orion_coherence_probe.py — "is this still Orion?" per fuel.

The fuel cascade checks model *availability* (is it up?) but never model
*coherence* (does it still behave like Orion?). A tiny local model that's
"available" can still be too weak to follow identity or instructions — and
silently speaking through it violates Orion's self-detection rule
(feedback_orion-must-self-detect: announce degraded state, don't fake it).

This runs a small golden suite against a fuel and scores whether it still
acts as Orion: identity, instruction-following, and coherent (non-error,
non-empty) output. Below the floor => degraded => the brain should ANNOUNCE
it ("running on a reduced model — reasoning may be limited"), not pretend.

This is an honest floor, not a deep eval. It catches "this fuel is too weak
to be Orion right now," which is exactly what the local/offline path needs.

CLI:
    python orion_coherence_probe.py            # probe every available fuel
    python orion_coherence_probe.py ollama     # probe one fuel by name
"""

import sys

# A minimal Orion preamble — the brain always wraps fuel with identity, so
# the probe must too. We're testing "given identity, does this model behave
# as Orion?", not "does a bare model magically know it's Orion?".
PREAMBLE = ("You are Orion, a personal AI brain. The model is fuel; you are "
            "Orion. Answer accordingly.")

# (prompt, predicate) — predicate returns True if the answer is Orion-coherent.
PROBES = [
    ("What is your name? Answer in one word.",
     lambda r: "orion" in r.lower()),
    ("Reply with exactly one word: READY",
     lambda r: "ready" in r.lower()),
    ("In one short sentence, what are you?",
     lambda r: bool(r.strip()) and len(r.strip()) < 600),
]

DEFAULT_FLOOR = 0.66  # must pass 2 of 3


def _is_error(text):
    try:
        from orion_fuel import _is_error_response
        return _is_error_response(text)
    except Exception:
        return not (text and text.strip())


def probe_fuel(adapter, floor=DEFAULT_FLOOR):
    """Probe one fuel adapter. Returns a result dict with score + degraded."""
    passed, details = 0, []
    for prompt, check in PROBES:
        try:
            resp = adapter.query(PREAMBLE + "\n\n" + prompt) or ""
        except Exception as e:
            resp = "error: %s" % e
        ok = bool(resp.strip()) and not _is_error(resp) and check(resp)
        passed += 1 if ok else 0
        details.append({"prompt": prompt, "ok": bool(ok), "reply": resp.strip()[:80]})
    score = passed / len(PROBES)
    return {"fuel": getattr(adapter, "name", "?"), "score": round(score, 2),
            "floor": floor, "degraded": score < floor, "details": details}


def coherence_note(result):
    """A user-facing line to prepend when a fuel is below the floor — so Orion
    announces the degradation instead of silently speaking as a lesser self."""
    if result and result.get("degraded"):
        return ("(heads up: I'm running on a reduced model right now — my "
                "reasoning may be limited until a stronger fuel is back.)")
    return ""


def probe_available(floor=DEFAULT_FLOOR):
    """Probe every fuel the router currently sees."""
    import orion_fuel
    system = orion_fuel.init()
    return [probe_fuel(a, floor) for a in system.available]


def main(argv):
    import orion_fuel
    system = orion_fuel.init()
    targets = system.available
    if argv:
        targets = [a for a in targets if getattr(a, "name", "") == argv[0]]
        if not targets:
            print("no available fuel named %r" % argv[0])
            return 1
    for a in targets:
        r = probe_fuel(a)
        flag = "DEGRADED" if r["degraded"] else "ok"
        print("%-18s score=%.2f  [%s]" % (r["fuel"], r["score"], flag))
        for d in r["details"]:
            print("   %s %s -> %s" % ("PASS" if d["ok"] else "FAIL",
                                      d["prompt"][:32], d["reply"][:60]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
