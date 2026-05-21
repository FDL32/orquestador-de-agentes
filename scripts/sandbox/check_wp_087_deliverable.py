#!/usr/bin/env python3
"""Gate ad-hoc para WP-2026-087 Deliverable A.

Valida word count, presencia de keywords obligatorias, ausencia de código Python.
"""
from __future__ import annotations

import sys
from pathlib import Path

DELIVERABLE = Path(__file__).resolve().parent.parent.parent / ".agent" / "runtime" / "deliverables" / "WP-087-dual-mode-summary.md"
REQUIRED_KEYWORDS = ["engine-dev", "host-project", "skills layered", "gates pluggables"]
MIN_WORDS = 200
MAX_WORDS = 350


def main() -> int:
    if not DELIVERABLE.exists():
        print(f"FAIL: deliverable not found at {DELIVERABLE}")
        return 1
    text = DELIVERABLE.read_text(encoding="utf-8")
    word_count = len(text.split())
    if not (MIN_WORDS <= word_count <= MAX_WORDS):
        print(f"FAIL: word count {word_count} not in [{MIN_WORDS}, {MAX_WORDS}]")
        return 1
    missing = [kw for kw in REQUIRED_KEYWORDS if kw.lower() not in text.lower()]
    if missing:
        print(f"FAIL: missing keywords: {missing}")
        return 1
    if "```python" in text or "\ndef " in text:
        print("FAIL: deliverable contains Python code blocks")
        return 1
    print(f"OK: deliverable passes all checks ({word_count} words)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
