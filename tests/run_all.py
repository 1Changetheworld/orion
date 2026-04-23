"""
Run every Orion test suite. Exit non-zero if any scenario fails.

Usage:
    python -m tests.run_all
"""
from __future__ import annotations

import sys

from tests.test_extraction_resistance import SCENARIOS as EXTRACTION_SCENARIOS
from tests.test_brain_functionality import SCENARIOS as BRAIN_SCENARIOS
from tests._harness import run_suite


def main():
    failures = 0
    failures += run_suite("EXTRACTION RESISTANCE", EXTRACTION_SCENARIOS)
    failures += run_suite("BRAIN FUNCTIONALITY", BRAIN_SCENARIOS)
    print()
    if failures == 0:
        print("ALL GREEN — safe to push")
        return 0
    print(f"FAILURES: {failures} suite(s) had failing scenarios")
    return 1


if __name__ == "__main__":
    sys.exit(main())
