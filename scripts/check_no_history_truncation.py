#!/usr/bin/env python3
"""
Guard script to detect dangerous truncation of execution_log.md.

This script checks if the current commit removes more than 50 lines from
execution_log.md without a compensating archive file being added in the same commit.

Usage:
    python scripts/check_no_history_truncation.py

Exit codes:
    0 - No dangerous truncation detected (or not a relevant commit)
    1 - Dangerous truncation detected without archive compensation
"""

import subprocess
import sys
from pathlib import Path


# Threshold for dangerous truncation (lines removed)
TRUNCATION_THRESHOLD = 50

# Files to monitor
EXECUTION_LOG = "execution_log.md"
# Canonical archive directory for execution_log rotations (see scripts/archive_execution_log.py)
ARCHIVE_DIR = ".agent/collaboration/archive/"


def run_git_command(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command and return stdout."""
    # Note: args are controlled by this script, not user input (S603/S607 safe)
    # git is a trusted system command, and args are constructed internally
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def get_staged_changes() -> list[str]:
    """Get list of staged files with their change status."""
    output = run_git_command(["diff", "--cached", "--name-status"])
    if not output:
        return []
    return output.split("\n")


def get_line_diff_for_file(filepath: str) -> tuple[int, int]:
    """
    Get the number of lines added and removed for a file in staged changes.

    Returns:
        (lines_added, lines_removed) tuple
    """
    output = run_git_command(["diff", "--cached", "--numstat", "--", filepath])
    if not output:
        return (0, 0)

    parts = output.split()
    if len(parts) < 2:
        return (0, 0)

    # Numstat shows "-" for binary files or when count is unavailable
    try:
        added = int(parts[0]) if parts[0] != "-" else 0
        removed = int(parts[1]) if parts[1] != "-" else 0
        return (added, removed)
    except ValueError:
        return (0, 0)


def check_archive_compensation() -> bool:
    """
    Check if any archive files are being added in this commit.

    Returns:
        True if archive files are being added, False otherwise
    """
    staged = get_staged_changes()
    for line in staged:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        status = parts[0]
        # For renames (R<score>), the new path is the LAST part. For adds, parts[1].
        filepath = parts[-1] if status.startswith("R") else parts[1]

        # Check if this is an archive file being added (added or renamed-into)
        if (status == "A" or status.startswith("R")) and ARCHIVE_DIR in filepath:
            return True

    return False


def check_execution_log_truncation() -> tuple[bool, int, int]:
    """
    Check if execution_log.md is being truncated beyond threshold.

    Returns:
        (is_truncated, lines_added, lines_removed) tuple
    """
    # Check if execution_log.md is in staged changes
    staged = get_staged_changes()
    log_found = False
    for line in staged:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        filepath = parts[1] if len(parts) >= 2 else ""
        if filepath.endswith(EXECUTION_LOG) or filepath == EXECUTION_LOG:
            log_found = True
            break

    if not log_found:
        return (False, 0, 0)

    lines_added, lines_removed = get_line_diff_for_file(EXECUTION_LOG)

    # Truncation is dangerous if we remove more than threshold lines
    # and we're not adding at least as many (i.e., net loss > threshold)
    is_truncated = lines_removed > TRUNCATION_THRESHOLD and lines_removed > lines_added

    return (is_truncated, lines_added, lines_removed)


def main() -> int:
    """Main entry point."""
    # Check for execution_log.md truncation
    is_truncated, lines_added, lines_removed = check_execution_log_truncation()

    if not is_truncated:
        # No dangerous truncation, pass silently
        return 0

    # Truncation detected - check for archive compensation
    has_archive_compensation = check_archive_compensation()

    if has_archive_compensation:
        # Archive compensation present, this is acceptable
        print(
            f"[check-no-history-truncation] INFO: "
            f"execution_log.md truncated by {lines_removed} lines, "
            f"but archive compensation detected. Allowing commit."
        )
        return 0

    # Dangerous truncation without compensation - FAIL
    print(
        f"[check-no-history-truncation] ERROR: "
        f"Dangerous truncation detected in {EXECUTION_LOG}!",
        file=sys.stderr,
    )
    print(f"  Lines removed: {lines_removed}", file=sys.stderr)
    print(f"  Lines added: {lines_added}", file=sys.stderr)
    print(f"  Threshold: {TRUNCATION_THRESHOLD} lines", file=sys.stderr)
    print("  Archive compensation: NONE", file=sys.stderr)
    print("\nTo fix this:", file=sys.stderr)
    print("  1. Run: python scripts/archive_execution_log.py", file=sys.stderr)
    print(
        "  2. Stage the archive file: git add .agent/collaboration/archive/",
        file=sys.stderr,
    )
    print("  3. Try commit again", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
