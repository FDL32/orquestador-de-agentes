"""Test-barrier: no inline ticket-ID regex outside bus/ticket_id.py.

WT-2026-251a: after centralizing all ticket-ID parsing to bus/ticket_id.py,
no Python file under scripts/, bus/, runtime/, or tests/ may contain the
legacy inline pattern ``(?:WP|WT)-``. Tests must exercise production parsers
(or import patterns from bus.ticket_id) instead of duplicating the regex.

Exemption: a file may contain a line with the comment
``# ticket-id-exemption: <reason>`` immediately inline to suppress the check
for that specific line.

[NON-REVERSE-CLASSICAL: test-barrier guarding a repo-wide structural contract]
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# ── Configuration ─────────────────────────────────────────────────────────────
_MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent

# Directories to scan (relative to motor root)
_SCAN_DIRS = ["scripts", "bus", "runtime", "tests"]

# Files excluded from the scan: the canonical source of truth, and this
# barrier itself (it must name the forbidden literal to search for it).
_EXEMPT_FILES = {
    _MOTOR_ROOT / "bus" / "ticket_id.py",
    Path(__file__).resolve(),
}

# The forbidden inline pattern (literal string to search for)
_FORBIDDEN_PATTERN = "(?:WP|WT)-"

# Inline exemption comment marker
_EXEMPTION_MARKER = "# ticket-id-exemption:"


# WOT-2026-013d: directories pruned before descending, so this test's own scan
# never enters the volatile pytest sandbox (tests/sandbox/test_runtime/session_*)
# that concurrent xdist workers delete mid-traversal.
_PRUNE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "build",
    "dist",
}


def _safe_scan_py(directory: Path) -> list[Path]:
    """WOT-2026-013d: robustly collect *.py under ``directory``, sorted.

    Replaces ``directory.rglob("*.py")`` (which raised FileNotFoundError when a
    sandbox subtree vanished mid-scan under xdist). Prunes the volatile pytest
    sandbox and other non-product dirs before descending, and tolerates entries
    that disappear during the walk. Sorted output preserves deterministic order.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(
        str(directory), onerror=lambda _e: None
    ):
        current = Path(dirpath)
        kept = []
        for d in dirnames:
            if d in _PRUNE_DIRS:
                continue
            try:
                rel = (current / d).relative_to(_MOTOR_ROOT).as_posix()
            except ValueError:
                rel = ""
            if rel.startswith("tests/sandbox/test_runtime"):
                continue
            kept.append(d)
        dirnames[:] = kept
        found.extend(current / fname for fname in filenames if fname.endswith(".py"))
    return sorted(found)


def _collect_violations() -> list[tuple[str, int, str]]:
    """Scan .py files and collect lines containing the forbidden pattern.

    Returns a list of (relative_path, line_number, line_content) tuples.
    """
    violations: list[tuple[str, int, str]] = []
    for scan_dir in _SCAN_DIRS:
        directory = _MOTOR_ROOT / scan_dir
        if not directory.is_dir():
            continue
        for py_file in _safe_scan_py(directory):
            if py_file.resolve() in _EXEMPT_FILES:
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
