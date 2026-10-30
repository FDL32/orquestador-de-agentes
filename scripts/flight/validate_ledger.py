#!/usr/bin/env python3
"""Ledger validator: reads a ledger, classifies legacy lines, never blocks.

Before: the ledger path is provided via --ledger.
During: reads the ledger file, parses each line, counts total lines,
    non-JSON lines, and key sets. A line is legacy if its set of keys
    differs from the fixed schema (N3). Reports legacy lines without
    blocking.
After: exit code 0 (even with legacy); exit code 2 only if the file
    cannot be read. Never fixes a count as a criterion.

The fixed schema keys (N3) are: ts, by, a, modo, resultado, error,
    providerInstanceId, mensaje_id, nota.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Fixed schema keys for the ledger.
FIXED_KEYS: frozenset[str] = frozenset(
    {
        "ts",
        "by",
        "a",
        "modo",
        "resultado",
        "error",
        "providerInstanceId",
        "mensaje_id",
        "nota",
    }
)


def _process_line(line_raw: str, key_sets: set) -> tuple[int, list[str]]:
    """Parse one ledger line and update key_sets / legacy_lines.

    Before: line_raw is a stripped, non-empty string from the ledger.
    During: tries json.loads, records the key set, appends to legacy_lines
        if keys differ from FIXED_KEYS.
    After: returns (1 if non-json, 0 otherwise), legacy_lines_mutated.
    """
    non_json: int = 0
    legacy: list[str] = []
    try:
        obj = json.loads(line_raw)
        if not isinstance(obj, dict):
            non_json = 1
            return (non_json, legacy)
        keys = frozenset(obj.keys())
        key_sets.add(keys)
        if keys != FIXED_KEYS:
            legacy.append(line_raw[:200])
    except (json.JSONDecodeError, ValueError):
        non_json = 1
    return (non_json, legacy)


def cmd_validate(ledger_path: Path) -> tuple[int, str]:
    """Validate and report on the ledger content.

    Before: ledger_path points to a ledger file that may or may not exist.
    During: reads the file, parses each line as JSON, counts total lines,
        non-JSON lines, and unique key sets. Lines whose key set differs
        from FIXED_KEYS are classified as legacy and reported.
    After: returns (rc, report). rc is 0 on success (even with legacy),
        2 if the file cannot be read. The report contains counts and
        legacy line details.
    """
    if not ledger_path.exists():
        return (2, "ilegible: el fichero no existe")

    try:
        raw = ledger_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return (2, "ilegible: el fichero no es UTF-8 valido: " + str(exc))
    except OSError as exc:
        return (2, "ilegible: no se pudo leer el fichero: " + str(exc))

    total_lines: int = 0
    non_json_lines: int = 0
    legacy_lines: list[str] = []
    key_sets: set[frozenset[str]] = set()

    for line_raw in raw.splitlines():
        line_raw = line_raw.strip()
        if not line_raw:
            continue

        total_lines += 1
        nj, leg = _process_line(line_raw, key_sets)
        non_json_lines += nj
        legacy_lines.extend(leg)

    report_lines: list[str] = []
    report_lines.append(
        f"ledger: {total_lines} linea(s) total, {non_json_lines} no-JSON, {len(key_sets)} conjunto(s) de claves"
    )

    if legacy_lines:
        report_lines.append(
            f"legacy: {len(legacy_lines)} linea(s) cuyo conjunto de claves difiere del fijo:"
        )
        for idx, ll in enumerate(legacy_lines[:10]):  # Limit report to first 10
            report_lines.append(f"  [{idx + 1}]: {ll}")
        if len(legacy_lines) > 10:
            report_lines.append(f"  ... y {len(legacy_lines) - 10} mas")

    return (0, "\n".join(report_lines))


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run validation.

    Before: CLI arguments are parsed from argv (or sys.argv).
    During: runs cmd_validate on the provided ledger path.
    After: returns exit code 0 (even with legacy) or 2 if unreadable.
    """
    parser = argparse.ArgumentParser(
        description="Ledger validator: reports legacy lines without blocking."
    )
    parser.add_argument("--ledger", required=True, help="Path to the ledger JSONL file")
    args = parser.parse_args(argv)

    rc, report = cmd_validate(Path(args.ledger))
    print(report)
    return rc


if __name__ == "__main__":
    sys.exit(main())
