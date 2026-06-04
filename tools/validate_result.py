#!/usr/bin/env python3
"""Validate HammerDB result artifacts under results/."""

from __future__ import annotations

import sys
from pathlib import Path

from result_validation import format_validation_failure, validate_artifacts

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_ROOT = REPO_ROOT / "results"


def main() -> int:
    result = validate_artifacts(REPO_ROOT, RESULTS_ROOT)
    if result.json_file_count == 0:
        print("No JSON files found under results/; nothing to validate.")
        return 0

    if not result.ok:
        print(format_validation_failure(result.errors))
        return 1

    print(f"Validation succeeded for {result.json_file_count} JSON file(s) under results/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
