"""Barrier (WOT-2026-090v DoD-d): no test may rewrite files via git.

A test that mutates a tracked file and restores it with ``git checkout --`` /
``git restore`` destroys any uncommitted work in that file and, when aimed at
the real working tree, corrupts the repository under test. The sanctioned
technique is COPY-RESTORE (copy the file, mutate the copy, restore from the
copy), never git (see observation
``obs-mutation-verify-copy-restore-not-git-checkout``).

This module scans every test file under ``tests/**/*.py`` for the destructive
git forms of checkout/restore:

- ``["git", "restore", ...]`` (restore is file-level by nature), and
- ``["git", "checkout", ..., "--", ...]`` (the explicit path form).

Branch operations are intentionally NOT flagged: ``git checkout --detach main``
and ``git checkout -b lateral`` do not rewrite working-tree files and are used
legitimately against repositories created inside ``tmp_path``.

Limitations (declared, not hidden): the scan is textual and argv-shaped, so a
dynamically built git command or a checkout split across helper indirection
would not be caught. It is a guardrail against the concrete regression this
ticket fixes, not a proof of absence.
"""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = PROJECT_ROOT / "tests"
_SELF = Path(__file__).resolve()

# Matches the argv list of a git checkout/restore call, capturing the subcommand
# and everything up to the closing bracket (may span multiple lines).
_GIT_CHECKOUT_ARGV = re.compile(
    r"""\[\s*["']git["']\s*,\s*["'](?P<sub>checkout|restore)["'](?P<rest>.*?)\]""",
    re.DOTALL | re.IGNORECASE,
)
_PATH_SEPARATOR = re.compile(r"""["']--["']""")


def _is_offender(subcommand: str, rest: str) -> bool:
    """True when the captured git argv rewrites working-tree files."""
    if subcommand.lower() == "restore":
        return True
    # checkout: only the explicit path form ("--") is destructive.
    return bool(_PATH_SEPARATOR.search(rest))


def find_git_restore_offenders(files: list[Path]) -> list[tuple[Path, int, str]]:
    """Return ``(path, lineno, matched_text)`` for each destructive git call.

    Before: *files* is an explicit list of Python files (the caller can pass any
        set, e.g. a ``git show`` export of an older revision, for mutation
        verification).
    During: reads each file as text and searches for the destructive argv forms
        described in the module docstring.
    After: returns one tuple per offender (empty when none). Never raises on
        unreadable input (a binary or deleted fixture is skipped).
    """
    offenders: list[tuple[Path, int, str]] = []
    for raw_path in files:
        path = Path(raw_path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _GIT_CHECKOUT_ARGV.finditer(text):
            if not _is_offender(match.group("sub"), match.group("rest")):
                continue
            lineno = text.count("\n", 0, match.start()) + 1
            offenders.append((path, lineno, match.group(0)))
    return offenders


def _discover_test_files() -> list[Path]:
    """Every ``tests/**/*.py`` file except this barrier itself."""
    return sorted(p for p in TESTS_DIR.rglob("*.py") if p.resolve() != _SELF)


def test_no_test_rewrites_files_with_git() -> None:
    """No test file may invoke destructive ``git checkout``/``git restore``."""
    offenders = find_git_restore_offenders(_discover_test_files())
    assert offenders == [], (
        "Destructive git checkout/restore found in tests: use COPY-RESTORE "
        "instead (never aim git checkout/restore at a tracked file). "
        + "; ".join(
            f"{p.relative_to(PROJECT_ROOT)}:{n} -> {txt.strip()}"
            for p, n, txt in offenders
        )
    )


def test_barrier_flags_path_checkout(tmp_path: Path) -> None:
    """Positive control: the barrier has teeth on the exact regression shape."""
    fixture = tmp_path / "test_offender.py"
    fixture.write_text(
        'subprocess.run(["git", "checkout", "--", str(RUNNER_PATH)])\n',
        encoding="utf-8",
    )
    offenders = find_git_restore_offenders([fixture])
    assert offenders, "barrier must flag git checkout -- <path>"


def test_barrier_flags_any_restore(tmp_path: Path) -> None:
    """Positive control: ``git restore`` is file-level by nature -> flagged."""
    fixture = tmp_path / "test_offender_restore.py"
    fixture.write_text(
        'subprocess.run(["git", "restore", "--", str(RUNNER_PATH)])\n',
        encoding="utf-8",
    )
    offenders = find_git_restore_offenders([fixture])
    assert offenders, "barrier must flag git restore"


def test_barrier_allows_branch_checkout(tmp_path: Path) -> None:
    """Negative control: branch operations in a tmp repo are legitimate."""
    fixture = tmp_path / "test_branch_ops.py"
    fixture.write_text(
        'subprocess.run(["git", "checkout", "--detach", "main"])\n'
        'subprocess.run(["git", "checkout", "-b", "lateral"])\n'
        'subprocess.run(["git", "checkout", "main"])\n',
        encoding="utf-8",
    )
    offenders = find_git_restore_offenders([fixture])
    assert offenders == [], (
        f"branch operations must not be flagged as destructive restores: {offenders}"
    )
