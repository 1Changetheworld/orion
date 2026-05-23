"""
Run every Orion test suite. Exit non-zero if any scenario fails.

Usage:
    python -m tests.run_all
"""
from __future__ import annotations

import sys

from tests.test_extraction_resistance import SCENARIOS as EXTRACTION_SCENARIOS
from tests.test_brain_functionality import SCENARIOS as BRAIN_SCENARIOS
from tests.test_membrane_fail_closed import SCENARIOS as MEMBRANE_SCENARIOS
from tests.test_source_attribution import SCENARIOS as PROVENANCE_SCENARIOS
from tests.test_identity_continuity import SCENARIOS as IDENTITY_SCENARIOS
from tests.test_coherence_probe import SCENARIOS as COHERENCE_SCENARIOS
from tests._harness import run_suite


def main():
    failures = 0
    failures += run_suite("EXTRACTION RESISTANCE", EXTRACTION_SCENARIOS)
    failures += run_suite("BRAIN FUNCTIONALITY", BRAIN_SCENARIOS)
    failures += run_suite("MEMBRANE FAIL-CLOSED", MEMBRANE_SCENARIOS)
    failures += run_suite("SOURCE ATTRIBUTION", PROVENANCE_SCENARIOS)
    failures += run_suite("IDENTITY CONTINUITY", IDENTITY_SCENARIOS)
    failures += run_suite("COHERENCE PROBE v2", COHERENCE_SCENARIOS)
    print()
    if failures == 0:
        print("ALL GREEN — safe to push")
        return 0
    print(f"FAILURES: {failures} suite(s) had failing scenarios")
    return 1


if __name__ == "__main__":
    sys.exit(main())
