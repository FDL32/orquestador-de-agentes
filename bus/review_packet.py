"""Diff collection and classification for the review evidence gate.

Extracted from bus/review_bridge.py (monolith decomposition). This module
owns the WT-2026-221b evidence-gate primitives:

- Best-effort diff-file collection from the motor repo (unstaged, staged,
  recent commits) and the destination repo (unstaged, recent commits).
- ``path_matches_any`` and ``DOCS_ONLY_PATTERNS``, the canonical pattern
  tuple that classification call sites build on.

``ReviewBridge.classify_review_packet`` orchestrates these primitives (via
``bus.evidence.resolve_evidence``) with bus/state context; the primitives
themselves never raise.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


DOCS_ONLY_PATTERNS: tuple[str, ...] = (
    ".agent/collaboration/",
    ".agent/runtime/",
    ".session/",
    "PROJECT.md",
    "AGENTS.md",
    "README.md",
    "CHANGELOG.md",
    "CREDITS.md",
    "REPOSITORY_STRUCTURE.md",
    "repomix.config.json",
)


def path_matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    """Check if a normalized path matches any of the given patterns."""
    normalized = path.replace("\\", "/")
    return any(pattern in normalized for pattern in patterns)


def _run_git_name_only(git_root: Path, args: list[str]) -> list[str] | None:
    """Run a git command at git_root and return non-empty stdout lines.

    Returns None when the command failed or produced no output (so callers
    can chain fallbacks). Lines starting with ``commit `` are filtered out
    (for ``git log --name-only`` fallbacks). Never raises.
    """
    git_bin = shutil.which("git") or "git"
    result = subprocess.run(  # noqa: S603
        [git_bin, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=git_root,
        timeout=10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return [
        f.strip()
        for f in result.stdout.splitlines()
        if f.strip() and not f.strip().startswith("commit ")
    ]


def get_motor_diff_files(motor_root: Path) -> list[str]:
    """Get diff file names from the motor repository (best-effort).

    Tries unstaged diff, then staged diff, then the last 5 commits.
    Returns [] on any error; never raises.
    """
    try:
        for args in (
            ["diff", "--name-only"],
            ["diff", "--cached", "--name-only"],
            ["log", "-5", "--name-only", "--format="],
        ):
            files = _run_git_name_only(motor_root, args)
            if files is not None:
                return files
    except Exception:  # noqa: S110 - best-effort
        pass
    return []


def get_destination_diff_files(project_root: Path) -> list[str]:
    """Get diff file names from the destination repository (best-effort).

    Tries unstaged diff, then the last 5 commits.
    Returns [] on any error; never raises.
    """
    try:
        for args in (
            ["diff", "--name-only"],
            ["log", "-5", "--name-only", "--format="],
        ):
            files = _run_git_name_only(project_root, args)
            if files is not None:
                return files
    except Exception:  # noqa: S110 - best-effort
        pass
    return []
