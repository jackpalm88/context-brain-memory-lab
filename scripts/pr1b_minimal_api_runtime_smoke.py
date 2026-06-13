#!/usr/bin/env python3
"""
PR1B minimal API runtime smoke skeleton.

This script is intentionally non-executable by default.
It documents intended future flow only and requires explicit GO flag.
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-execution", action="store_true", help="Explicit human GO for later gate")
    args = parser.parse_args()

    if not args.allow_execution:
        print("REFUSED: runtime smoke execution is disabled in implementation-only gate.")
        print("Expected future DB pattern: pr1b_api_smoke_<timestamp>")
        print("Run only in PR1B_MINIMAL_API_RUNTIME_SMOKE_EXECUTION_GO gate.")
        return 2

    print("Execution flag provided, but this skeleton still does not run smoke steps in this gate.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
