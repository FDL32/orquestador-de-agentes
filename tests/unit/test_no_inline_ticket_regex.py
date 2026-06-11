"""Test-barrier: no inline ticket-ID regex outside bus/ticket_id.py.

WT-2026-251a: after centralizing all ticket-ID parsing to bus/ticket_id.py,
no Python file under scripts/, bus/, or runtime/ may contain the legacy
inline pattern ``(?:WP|WT)-``.

Exemption: a file may contain a line with the comment
``# ticket-id-exemption: <reason>`` immediately inline to suppress the check
for that specific line.

[NON-REVERSE-CLASSICAL: test-barrier guarding a repo-wide structural contract]
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ── Configuration ─────────────────────────────────────────────────────────────
_MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent

# Directories to scan (relative to motor root)
_SCAN_DIRS = ["scripts", "bus", "runtime"]

# The canonical source of truth — excluded from the scan
_EXEMPT_FILE = _MOTOR_ROOT / "bus" / "ticket_id.py"

# The forbidden inline pattern (literal string to search for)
_FORBIDDEN_PATTERN = "(?:WP|WT)-"

# Inline exemption comment marker
_EXEMPTION_MARKER = "# ticket-id-exemption:"


def _collect_violations() -> list[tuple[str, int, str]]:
    """Scan .py files and collect lines containing the forbidden pattern.

    Returns a list of (relative_path, line_number, line_content) tuples.
    """
    violations: list[tuple[str, int, str]] = []
    for scan_dir in _SCAN_DIRS:
        directory = _MOTOR_ROOT / scan_dir
        if not directory.is_dir():
            continue
        for py_file in sorted(directory.rglob("*.py")):
            if py_file.resolve() == _EXEMPT_FILE.resolve():
                continue
            try:
                lines = py_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                if _FORBIDDEN_PATTERN in line and _EXEMPTION_MARKER not in line:
                    rel = str(py_file.relative_to(_MOTOR_ROOT))
                    violations.append((rel, lineno, line.rstrip()))
    return violations


def test_no_inline_ticket_regex():
    """Fail if any .py file outside bus/ticket_id.py contains ``(?:WP|WT)-``."""
    violations = _collect_violations()
    if not violations:
        return

    lines = ["Inline ticket-ID regex found outside bus/ticket_id.py:"]
    for path, lineno, line in violations:
        lines.append(f"  {path}:{lineno}: {line}")
    lines.append(
        "\nFix: import TICKET_ID_PATTERN from bus.ticket_id instead, or add"
        " '# ticket-id-exemption: <reason>' to the offending line."
    )
    pytest.fail("\n".join(lines))
