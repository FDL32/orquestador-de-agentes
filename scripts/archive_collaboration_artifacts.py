#!/usr/bin/env python3
"""Archive closed PLAN/AUDIT artifacts from .agent/collaboration/.

This script moves historical PLAN_WP-*.md and AUDIT_WP-*.md files
from the active collaboration surface to an internal archive directory,
keeping only the current ticket's support files in place.

Goals:
- Keep the portable bundle copyable without dragging old ticket forensics.
- Preserve closed ticket artifacts in `.agent/collaboration/_archive/plan_audit/`.
- Leave live operational surfaces untouched: work_plan.md, TURN.md, STATE.md, execution_log.md.
- Be idempotent: re-running does not duplicate or corrupt files.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


# Patterns to match PLAN and AUDIT files
PLAN_RE = re.compile(r"^PLAN_WP-(\d{4})-(\d{3})\.md$")
AUDIT_RE = re.compile(r"^AUDIT_WP-(\d{4})-(\d{3})\.md$")

# Files that must always remain in the active collaboration surface
ACTIVE_ONLY_FILES = {
    "work_plan.md",
    "TURN.md",
    "STATE.md",
    "execution_log.md",
    "events.jsonl",
}


def parse_wp_number(filename: str) -> str | None:
    """Extract WP number from filename (e.g., 'PLAN_WP-2026-100.md' -> 'WP-2026-100')."""
    for pattern in (PLAN_RE, AUDIT_RE):
        match = pattern.match(filename)
        if match:
            year, num = match.groups()
            return f"WP-{year}-{num}"
    return None


def get_active_wp(collaboration_dir: Path) -> str | None:
    """Read the active WP ID from work_plan.md."""
    work_plan = collaboration_dir / "work_plan.md"
    if not work_plan.exists():
        return None

    text = work_plan.read_text(encoding="utf-8")
    # Look for "- **ID:** WP-YYYY-NNN" or "**ID:** WP-YYYY-NNN" patterns
    match = re.search(r"(?m)-?\s*\*\*ID:\*\*\s*(WP-\d{4}-\d{3})", text)
    if match:
        return match.group(1)
    return None


def find_closed_plan_audit_files(
    collaboration_dir: Path, active_wp: str | None
) -> list[Path]:
    """Find all PLAN/AUDIT files that belong to closed tickets."""
    closed_files: list[Path] = []

    if not collaboration_dir.exists():
        return closed_files

    for entry in collaboration_dir.iterdir():
        if not entry.is_file():
            continue

        wp_id = parse_wp_number(entry.name)
        if wp_id is None:
            continue

        # Skip if this is the active ticket
        if wp_id == active_wp:
            continue

        closed_files.append(entry)

    return closed_files


def get_archive_dir(collaboration_dir: Path) -> Path:
    """Get the archive directory path for plan_audit artifacts."""
    return collaboration_dir / "_archive" / "plan_audit"


def archive_collaboration_artifacts(
    collaboration_dir: Path,
    dry_run: bool = False,
    active_wp_override: str | None = None,
) -> dict:
    """Archive closed PLAN/AUDIT artifacts to the internal archive.

    Args:
        collaboration_dir: Path to .agent/collaboration directory.
        dry_run: If True, only report what would be archived without moving files.
        active_wp_override: Override the active WP ID (for testing).

    Returns:
        Dictionary with 'archived' (list of archived files) and 'skipped' (list of skipped files).
    """
    result: dict = {"archived": [], "skipped": [], "errors": []}

    active_wp = active_wp_override or get_active_wp(collaboration_dir)
    closed_files = find_closed_plan_audit_files(collaboration_dir, active_wp)

    if not closed_files:
        return result

    archive_dir = get_archive_dir(collaboration_dir)

    for file_path in sorted(closed_files):
        if dry_run:
            result["archived"].append(str(file_path))
            continue

        try:
            # Create archive directory if needed
            archive_dir.mkdir(parents=True, exist_ok=True)

            # Move file to archive
            dest = archive_dir / file_path.name
            shutil.move(str(file_path), str(dest))
            result["archived"].append(str(file_path))
        except Exception as exc:
            result["errors"].append({"file": str(file_path), "error": str(exc)})

    return result


def list_active_collaboration_files(collaboration_dir: Path) -> list[str]:
    """List files that remain in the active collaboration surface."""
    active_files: list[str] = []

    if not collaboration_dir.exists():
        return active_files

    for entry in collaboration_dir.iterdir():
        if not entry.is_file():
            continue

        # Skip archive directory
        if entry.name.startswith("_"):
            continue

        # Check if it's a PLAN/AUDIT file
        wp_id = parse_wp_number(entry.name)
        if wp_id is not None:
            # Only include if it's the active WP
            active_wp = get_active_wp(collaboration_dir)
            if wp_id == active_wp:
                active_files.append(entry.name)
        elif entry.name in ACTIVE_ONLY_FILES:
            active_files.append(entry.name)

    return sorted(active_files)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive closed PLAN/AUDIT artifacts from .agent/collaboration/"
    )
    parser.add_argument(
        "--collaboration-dir",
        type=Path,
        default=Path(".agent/collaboration"),
        help="Path to .agent/collaboration directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be archived without moving files",
    )
    parser.add_argument(
        "--active-wp",
        type=str,
        default=None,
        help="Override active WP ID (for testing)",
    )
    parser.add_argument(
        "--list-active",
        action="store_true",
        help="List active collaboration files and exit",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    if args.list_active:
        active_files = list_active_collaboration_files(args.collaboration_dir)
        print("Active collaboration files:")
        for f in active_files:
            print(f"  {f}")
        return 0

    result = archive_collaboration_artifacts(
        collaboration_dir=args.collaboration_dir,
        dry_run=args.dry_run,
        active_wp_override=args.active_wp,
    )

    if args.dry_run:
        if result["archived"]:
            print(f"DRY RUN: would archive {len(result['archived'])} file(s):")
            for f in result["archived"]:
                print(f"  {f}")
        else:
            print("DRY RUN: no files to archive")
    else:
        if result["archived"]:
            print(f"Archived {len(result['archived'])} file(s)")
        if result["errors"]:
            print(f"Errors: {len(result['errors'])}")
            for err in result["errors"]:
                print(f"  {err['file']}: {err['error']}")

    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
