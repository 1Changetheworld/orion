#!/usr/bin/python3
"""ORION PRESENCE BATTERY RUNNER — the Phase 0 judge, launched by JAMES.

Hard rule (2026-10-02): James runs every test that involves talking to Orion.
The builder only runs --selftest and --list, which never touch Orion or a model.

What this does:
  - asks each battery case through orion_brain.think() — the real brain path
    (recall, identity, router, fuel cascade), exactly what answers James
  - shows the RAW answer every time; raw answers are stored, never summarized
  - scores ONLY the mechanical checks (must_mention / must_not_mention /
    pass_if_mentions_any / fail_if_mentions_any / max_words); everything else
    is James's live verdict
  - NEVER writes test Q/A into Orion's memory: memorize() is disabled inside
    this process only. Daemons and real surfaces are untouched.
  - appends every result to ~/.orion/battery/run-<timestamp>.jsonl

Usage (on COMMAND, from ~/orion-code):
  python3 eval/run_battery.py               # full interactive run
  python3 eval/run_battery.py --only R1,C2  # subset
  python3 eval/run_battery.py --list        # show cases, ask nothing
  python3 eval/run_battery.py --selftest    # scorer self-test, no Orion, no fuel

Not in v1 (on purpose, one change at a time): pinning a specific fuel per case.
E1 (local_only) is skipped with a reason until fuel pinning exists.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# The battery must run on the SAME interpreter as Orion's daemons (every
# com.orion.* plist uses /usr/bin/python3; it has PyYAML and the brain's
# deps). James's interactive shell puts a bare homebrew 3.14 first on PATH,
# so a plain `python3 eval/run_battery.py` lands on the wrong Python.
# Re-exec once onto the brain's interpreter instead of failing.
BRAIN_PYTHON = "/usr/bin/python3"
if (os.path.exists(BRAIN_PYTHON)
        and not os.environ.get("ORION_BATTERY_REEXEC")):
    try:
        import yaml  # noqa: F401 — probe only
    except ImportError:
        os.environ["ORION_BATTERY_REEXEC"] = "1"
        os.execv(BRAIN_PYTHON, [BRAIN_PYTHON, os.path.abspath(__file__)] + sys.argv[1:])

BATTERY_PATH = Path(__file__).resolve().parent / "battery_v0.yaml"
RESULTS_DIR = Path.home() / ".orion" / "battery"

PASS, FAIL, OPEN = "pass", "fail", "needs_james"


def load_battery(path=BATTERY_PATH):
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _contains(answer_lc, needle):
    return needle.lower() in answer_lc


def score_mechanical(case, answer):
    """Deterministic checks only. Returns (verdict, details).

    verdict: "pass" | "fail" | "needs_james"  (needs_james = nothing mechanical
    decided it; James's verdict is the result).
    """
    details = []
    answer_lc = (answer or "").lower()
    failed = False
    decided = False

    for group in case.get("must_mention", []):
        hit = any(_contains(answer_lc, alt) for alt in group)
        decided = True
        details.append(("must_mention one of %s" % group, "ok" if hit else "MISSING"))
        if not hit:
            failed = True

    for banned in case.get("must_not_mention", []):
        hit = _contains(answer_lc, banned)
        decided = True
        details.append(("must_not_mention %r" % banned, "VIOLATED" if hit else "ok"))
        if hit:
            failed = True

    for banned in case.get("fail_if_mentions_any", []):
        if _contains(answer_lc, banned):
            decided = True
            failed = True
            details.append(("fail_if_mentions %r" % banned, "VIOLATED"))

    max_words = case.get("max_words")
    if max_words:
        n = len((answer or "").split())
        decided = True
        details.append(("max_words %d (got %d)" % (max_words, n),
                        "ok" if n <= max_words else "VIOLATED"))
        if n > max_words:
            failed = True

    if failed:
        return FAIL, details

    pass_any = case.get("pass_if_mentions_any")
    if pass_any:
        if any(_contains(answer_lc, p) for p in pass_any):
            details.append(("pass_if_mentions one of %s" % pass_any, "ok"))
            return PASS, details
        # No trap phrase and no denial phrase: the machine can't call it.
        details.append(("pass_if_mentions one of %s" % pass_any, "no match — James decides"))
        return OPEN, details

    if decided:
        return PASS, details
    return OPEN, details


def selftest():
    """Scorer self-test. States expected results up front, includes negative
    controls, touches no brain and no fuel."""
    battery = load_battery()
    by_id = {c["id"]: c for c in battery["cases"]}
    checks = [
        # (case, answer, expected) — expectations declared BEFORE running.
        ("S1", "On it, sir — maximizing profit now.", FAIL),          # banned phrases
        ("S1", "hey, what's up", PASS),                                # clean greeting
        ("S1", " ".join(["word"] * 40), FAIL),                         # over max_words
        ("R3", "Your chemistry lecture is Strickler Hall room 102.", PASS),
        ("R3", "It's in Davidson Hall.", FAIL),                        # negative control
        ("H1", "We decided on the migration plan last month, sir.", FAIL),  # trap taken
        ("H1", "I have no record of that — it never happened.", PASS),
        ("H1", "Postgres is a relational database.", OPEN),            # machine can't call it
        ("C4", "You'd miss GEN 100, CSE 120 and ENGL 101.", PASS),
        ("C4", "You'd miss GEN 100, CSE 120, ENGL 101 and CHEM 101.", FAIL),  # chem banned
        ("E3", "Fall break is Monday October 5 through Tuesday October 6.", PASS),
        ("I1", "You have a CHEM quiz closing Friday.", OPEN),          # rubric-only case
    ]
    bad = 0
    for cid, answer, expected in checks:
        verdict, _ = score_mechanical(by_id[cid], answer)
        ok = verdict == expected
        bad += 0 if ok else 1
        print("%-4s %-10s expected=%-11s got=%-11s | %s"
              % ("ok" if ok else "FAIL", cid, expected, verdict, answer[:60]))
    print("\nselftest: %d/%d checks behaved as declared" % (len(checks) - bad, len(checks)))
    return 1 if bad else 0


def ask_orion(prompt):
    """The real path: orion_brain.think(), with memory writes disabled in this
    process so test Q/A never enters the graph."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import orion_brain
    # In-process only. The graph on disk is never written by a battery run.
    orion_brain.memory.memorize = lambda *a, **k: None
    t0 = time.time()
    result = orion_brain.think(prompt, interface="battery")
    latency = round(time.time() - t0, 1)
    if isinstance(result, dict):
        return result.get("response", ""), result.get("engine", "?"), latency
    return str(result), "?", latency


def james_verdict(mechanical):
    """One line from James. Enter accepts the mechanical verdict; p/f override;
    s skips; anything else is kept as a note."""
    try:
        raw = input("  James [Enter=%s / p / f / s / note]: " % mechanical).strip()
    except EOFError:
        return mechanical, ""
    if raw == "":
        return mechanical, ""
    if raw.lower() == "p":
        return PASS, ""
    if raw.lower() == "f":
        return FAIL, ""
    if raw.lower() == "s":
        return "skipped", ""
    return mechanical, raw


def main():
    ap = argparse.ArgumentParser(description="Orion presence battery (James launches this)")
    ap.add_argument("--list", action="store_true", help="print cases, ask nothing")
    ap.add_argument("--selftest", action="store_true", help="scorer self-test, no Orion")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--no-interactive", action="store_true",
                    help="record mechanical verdicts only (for re-scoring later)")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    battery = load_battery()
    cases = battery["cases"]
    if args.only:
        wanted = {x.strip().upper() for x in args.only.split(",") if x.strip()}
        cases = [c for c in cases if c["id"].upper() in wanted]

    if args.list:
        for c in cases:
            kind = "protocol" if "protocol" in c else "prompt"
            print("%-4s %-12s %-10s %s" % (c["id"], c["category"], kind,
                                           c.get("prompt", "(manual protocol)")[:70]))
        print("\n%d cases, battery v%s (%s)" % (len(cases), battery.get("version"),
                                                battery.get("status")))
        return

    interactive = not args.no_interactive and sys.stdin.isatty()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("run-%Y%m%d-%H%M%S")
    out_path = RESULTS_DIR / ("%s.jsonl" % run_id)
    protocols, tally = [], {PASS: 0, FAIL: 0, OPEN: 0, "skipped": 0}

    print("ORION PRESENCE BATTERY v%s — %s" % (battery.get("version"), run_id))
    print("Results: %s\n" % out_path)

    for case in cases:
        if "protocol" in case:
            protocols.append(case)
            continue
        if case.get("fuel") == "local_only":
            print("%s SKIPPED — needs fuel pinning (not in v1)\n" % case["id"])
            tally["skipped"] += 1
            continue

        print("── %s [%s] " % (case["id"], case["category"]) + "─" * 40)
        print("Q: %s" % case["prompt"])
        try:
            answer, engine, latency = ask_orion(case["prompt"])
        except Exception as e:
            answer, engine, latency = "", "ERROR: %s" % e, 0.0
        print("A (%s, %ss): %s" % (engine, latency, answer or "(empty)"))

        mech, details = score_mechanical(case, answer)
        for name, outcome in details:
            print("   %-50s %s" % (name, outcome))
        for key in ("rubric", "fail_if", "scoring"):
            if case.get(key):
                print("   JAMES JUDGES: %s" % case[key])
        print("   mechanical: %s" % mech.upper())

        verdict, note = (james_verdict(mech) if interactive else (mech, ""))
        tally[verdict] = tally.get(verdict, 0) + 1
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "run": run_id, "ts": datetime.now().isoformat(timespec="seconds"),
                "id": case["id"], "category": case["category"],
                "prompt": case["prompt"], "answer": answer, "engine": engine,
                "latency_s": latency, "mechanical": mech, "verdict": verdict,
                "note": note, "battery_version": battery.get("version"),
            }) + "\n")
        print()

    print("═" * 60)
    print("TALLY: %d pass / %d fail / %d needs_james / %d skipped"
          % (tally[PASS], tally[FAIL], tally[OPEN], tally.get("skipped", 0)))
    print("Raw results: %s" % out_path)
    if protocols:
        print("\nMANUAL PROTOCOLS (run these yourself, sir):")
        for c in protocols:
            print("\n%s [%s] — pass when: %s" % (c["id"], c["category"], c.get("pass", "")))
            print(c["protocol"].rstrip())


if __name__ == "__main__":
    main()
