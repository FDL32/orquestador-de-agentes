"""Canonical helpers for manager_feedback file discovery and ticket ID parsing.

WOT-2026-014f: Single source of truth for the two helpers that were previously
duplicated across archive_collaboration_artifacts.py (public API, signature
without pattern) and closeout_steps/archival.py (internal, signature with
ticket_id_pattern). This module holds the ONE real implementation of each;
the three consumers (archive_collaboration_artifacts, closeout_steps/archival,
session_closeout) import from here.

Before: collaboration_dir and filename strings are provided by callers.
During: Discovery iterates the filesystem; parsing applies a regex built from
        ticket_id_pattern.
After:  Pure read-only functions -- no file mutation, no side effects.
"""

from __future__ import annotations

import re
from pathlib import Path


def find_manager_feedback_files(collaboration_dir: Path) -> list[Path]:
    """Find all manager_feedback_*.md files in the collaboration directory.

    Before: collaboration_dir is the path to .agent/collaboration/.
    During: Iterates collaboration_dir (non-recursive); selects regular files
            whose name starts with "manager_feedback_" and ends with ".md".
    After:  Returns a sorted list of matching Path objects, or [] if the
            directory does not exist.
    """
    if not collaboration_dir.exists():
        return []
    return sorted(
        entry
        for entry in collaboration_dir.iterdir()
        if (
            entry.is_file()
            and entry.name.startswith("manager_feedback_")
            and entry.name.endswith(".md")
        )
    )


def extract_ticket_id_from_feedback(
    filename: str,
    *,
    ticket_id_pattern: str,
) -> str | None:
    """Extract ticket ID from a manager_feedback filename.

    Before: filename is a string (e.g. "manager_feedback_WP-2026-155.md").
            ticket_id_pattern is a raw regex string (e.g. from bus.ticket_id).
    During: Builds and applies a regex that anchors the pattern inside the
            manager_feedback_<ID>.md envelope.
    After:  Returns the ticket ID string if matched, None otherwise.
    """
    match = re.search(
        r"manager_feedback_(" + ticket_id_pattern + r")\.md$",
        filename,
    )
    if match:
        return match.group(1)
    return None
