#!/usr/bin/env python3
"""Gate: ticket nomenclature — WOT-2026-010a.

Classifies every legacy-prefix (WP-/WT-) hit in prompts/, skills/ and
scripts/ as one of:

- generator      : template/placeholder/example/--help/schema that teaches or
                   creates new nomenclature. MUST use WOT-. A legacy prefix
                   here is a BUG -> the gate fails.
- history        : a commit-history comment/docstring of the form
                   ``# <TICKET>: <what was done>`` or a historical reference.
                   Rewriting it would falsify traceability -> permitted as
                   implicit legacy-compat.
- legacy-tagged  : a line near an explicit ``legacy-compat`` marker -> permitted.

The gate exits 0 when no generator hit uses a legacy prefix, 1 otherwise.

Before: run from the motor root (repo with prompts/, skills/, scripts/).
During: scans tracked text files line by line, classifies each legacy hit.
After: prints a per-category report; exit 1 if any unclassified generator hit
       remains, else exit 0.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Legacy ticket-id prefixes this gate watches for in active surfaces.
LEGACY_HIT_RE = re.compile(r"\b(?:WP|WT)-(?:\d{4}|YYYY|XXXX)\b")

# A line is treated as commit-history when it starts with one or more legacy
# ticket IDs followed by ":" or ")" and then explanatory prose about the change.
HISTORY_RE = re.compile(
    r"^\s*#?\s*(?:WP|WT)-(?:\d{4})-[A-Za-z0-9]+"
    r"(?:\s*/\s*(?:WP|WT)-\d{4}-[A-Za-z0-9]+)*\s*[:)]"
)

# Markers that explicitly opt a line/region into legacy-compat.
LEGACY_TAG_RE = re.compile(r"legacy-compat|ticket historico|legacy \(retro", re.I)

# Generator signals: if a legacy hit shares a line with any of these, the line
# is teaching/creating nomenclature and must use WOT-.
GENERATOR_SIGNAL_RE = re.compile(
    r"--ticket(?:-id)?\s+(?:WP|WT)-"
    r"|Plan ID:?\**\s*(?:WP|WT)-"
    r"|\*\*ID:\*\*\s*(?:WP|WT)-"
    r"|Ticket relacionado:.*(?:WP|WT)-"
    r"|source_ticket\"?\s*:\s*\"?(?:WP|WT)-"
    r"|source\"?\s*:\s*\"?human_audit_(?:WP|WT)-"
    r"|e\.g\.,?\s*(?:WP|WT)-"
    r"|(?:WP|WT)-(?:YYYY|XXXX)"
    r"|--milestone\s+\S+\s+--ticket-id\s+(?:WP|WT)-",
    re.I,
)

SCAN_DIRS = ("prompts", "skills", "scripts")
SCAN_SUFFIXES = {".md", ".py", ".ps1", ".txt"}
SKIP_PARTS = {"__pycache__", "sandbox", ".ruff_cache"}


def iter_files(root: Path) -> list[Path]:
    """Yield text files under the scan dirs, skipping caches/sandbox."""
    files: list[Path] = []
    for d in SCAN_DIRS:
        base = root / d
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix not in SCAN_SUFFIXES:
                continue
            if any(part in SKIP_PARTS for part in f.parts):
                continue
            files.append(f)
    return files


def classify_line(line: str, region_legacy: bool) -> str | None:
    """Classify a single line that contains a legacy hit.

    Returns one of "generator", "history", "legacy-tagged", or None when the
    line contains no legacy hit at all.
    """
    if not LEGACY_HIT_RE.search(line):
        return None
    if region_legacy or LEGACY_TAG_RE.search(line):
        return "legacy-tagged"
    if GENERATOR_SIGNAL_RE.search(line):
        return "generator"
    if HISTORY_RE.match(line):
        return "history"
    # A bare legacy id with no generator signal and no history form: treat as
    # history reference (e.g. prose "...corregido en WP-2026-120..."). These
    # are historical mentions, not generators.
    return "history"


def scan_file(path: Path) -> dict[str, list[tuple[int, str]]]:
    """Classify every legacy hit in a file.

    A region is considered legacy-tagged for the following few lines after a
    legacy-compat marker (covers a tagged example block).
    """
    buckets: dict[str, list[tuple[int, str]]] = {
        "generator": [],
        "history": [],
        "legacy-tagged": [],
    }
    legacy_region_ttl = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return buckets
    for n, line in enumerate(lines, start=1):
        if LEGACY_TAG_RE.search(line):
            legacy_region_ttl = 18  # cover the tagged note + example block
        region_legacy = legacy_region_ttl > 0
        if legacy_region_ttl > 0:
            legacy_region_ttl -= 1
        kind = classify_line(line, region_legacy)
        if kind is not None:
            buckets[kind].append((n, line.strip()))
    return buckets


def main() -> int:
    parser = argparse.ArgumentParser(description="Ticket nomenclature gate")
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help="Motor root (defaults to this script's parent's parent).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    root = (
        Path(args.root).resolve()
        if args.root
        else Path(__file__).resolve().parent.parent
    )

    generators: list[str] = []
    history_count = 0
    tagged_count = 0
    for f in iter_files(root):
        buckets = scan_file(f)
        history_count += len(buckets["history"])
        tagged_count += len(buckets["legacy-tagged"])
        for n, text in buckets["generator"]:
            rel = f.relative_to(root).as_posix()
            generators.append(f"{rel}:{n}: {text}")

    print("[ticket-nomenclature] classification:")
    print(f"  generator (must be WOT-, legacy = BUG): {len(generators)}")
    print(f"  history (legacy-compat implicit):       {history_count}")
    print(f"  legacy-tagged (legacy-compat explicit): {tagged_count}")

    if generators:
        print("\n[FAIL] Active generators still using a legacy prefix:")
        for g in generators:
            print(f"  - {g}")
        print(
            "\nFix: convert each to WOT-, or move it under an explicit "
            "legacy-compat marker if it is a deliberate retro example."
        )
        return 1

    if args.verbose and history_count:
        print("\n[OK] history hits are permitted legacy-compat (not rewritten).")
    print("\n[OK] No active generator uses a legacy prefix.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
