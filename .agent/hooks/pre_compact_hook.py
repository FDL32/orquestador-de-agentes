#!/usr/bin/env python3
"""Pre-compact hook for preparation before compaction."""

from __future__ import annotations

import json
import sys


def main() -> None:
    """Main entry point for pre-compact hook."""
    try:
        input_data = json.loads(sys.stdin.read())
    except Exception:
        input_data = {}

    # Perform pre-compaction checks
    continue_flag = True

    # Output result
    result = {
        "continue": continue_flag,
        "input": input_data,
    }
    print(json.dumps(result))
    sys.exit(0 if continue_flag else 1)


if __name__ == "__main__":
    main()
