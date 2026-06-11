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
import sys
from pathlib import Path


# Bootstrap: project root must be on sys.path before importing bus modules.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

from bus.ticket_id import TICKET_ID_PATTERN, WORKPLAN_ID_PATTERN  # noqa: E402


# Patterns to match PLAN and AUDIT files — derived from canonical TICKET_ID_PATTERN
# so letter-suffix IDs (e.g. WT-2026-221a) are matched.
PLAN_RE = re.compile(r"^PLAN_(" + TICKET_ID_PATTERN + r")\.md$")
AUDIT_RE = re.compile(r"^AUDIT_(" + TICKET_ID_PATTERN + r")\.md$")

# Regex to extract ticket ID from manager_feedback filenames
MANAGER_FEEDBACK_RE = re.compile(r"^manager_feedback_(" + TICKET_ID_PATTERN + r")\.md$")

# Files that must always remain in the active collaboration surface
ACTIVE_ONLY_FILES = {
    "work_plan.md",
    "TURN.md",
    "STATE.md",
    "execution_log.md",
    "events.jsonl",
}


def parse_wp_number(filename: str) -> str | None:
    """Extract ticket ID from filename (e.g., 'PLAN_WT-2026-221a.md' -> 'WT-2026-221a')."""
    for pattern in (PLAN_RE, AUDIT_RE):
        match = pattern.match(filename)
        if match:
            return match.group(1)
    return None


def get_active_wp(collaboration_dir: Path) -> str | None:
    """Read the active WP ID from work_plan.md."""
    work_plan = collaboration_dir / "work_plan.md"
    if not work_plan.exists():
        return None

    text = work_plan.read_text(encoding="utf-8")
    # Use canonical WORKPLAN_ID_PATTERN (supports letter-suffix IDs like WT-2026-221a)
    match = WORKPLAN_ID_PATTERN.search(text)
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


def find_manager_feedback_files(collaboration_dir: Path) -> list[Path]:
    """Find all manager_feedback_*.md files in the collaboration directory.

    Before: collaboration_dir exists.
    During: Lists files matching the pattern manager_feedback_*.md.
    After: Returns sorted list of matching file paths.
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


def extract_ticket_id_from_feedback(filename: str) -> str | None:
    """Extract ticket ID from a manager_feedback filename.

    Before: filename is a string like 'manager_feedback_WP-2026-155.md'.
    During: Uses MANAGER_FEEDBACK_RE to extract the ticket ID portion.
    After: Returns ticket ID string or None if not matched.
    """
    match = MANAGER_FEEDBACK_RE.match(filename)
    if match:
        return match.group(1)
    return None


def archive_manager_feedback(
    collaboration_dir: Path,
    ticket_ids_to_archive: list[str],
    dry_run: bool = False,
) -> dict:
    """Archive manager_feedback_* files for specific ticket IDs.

    Before: collaboration_dir is the path to .agent/collaboration/.
            ticket_ids_to_archive is the list of ticket IDs whose feedback
            should be archived (close/approval already verified by caller).
    During: For each manager_feedback file matching a ticket in
            ticket_ids_to_archive, moves the file to
            archive/manager_feedback/<filename>.
            Skips files already in the archive (idempotent).
    After: Returns dict with 'archived', 'skipped', 'errors' lists.
    """
    result: dict = {"archived": [], "skipped": [], "errors": []}

    if not ticket_ids_to_archive:
        return result

    feedback_files = find_manager_feedback_files(collaboration_dir)
    if not feedback_files:
        return result

    archive_dir = collaboration_dir / "archive" / "manager_feedback"
    tid_set = set(ticket_ids_to_archive)

    for fb_path in feedback_files:
        tid = extract_ticket_id_from_feedback(fb_path.name)
        if tid is None:
            result["skipped"].append(f"{fb_path.name} (unparseable)")
            continue
        if tid not in tid_set:
            result["skipped"].append(f"{fb_path.name} (not in archive list)")
            continue

        if dry_run:
            result["archived"].append(str(fb_path))
            continue

        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            dest = archive_dir / fb_path.name
            if dest.exists():
                fb_path.unlink()
                result["archived"].append(
                    f"{fb_path.name} (live copy removed; archive exists)"
                )
                continue
            shutil.move(str(fb_path), str(dest))
            result["archived"].append(str(fb_path))
        except Exception as exc:
            result["errors"].append({"file": str(fb_path), "error": str(exc)})

    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive closed PLAN/AUDIT artifacts from .agent/collaboration/"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (overrides --collaboration-dir default)",
    )
    parser.add_argument(
        "--collaboration-dir",
        type=Path,
        default=None,
        help="Path to .agent/collaboration directory (default: <project-root>/.agent/collaboration)",
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
    parser.add_argument(
        "--archive-manager-feedback",
        type=str,
        default=None,
        help="Comma-separated ticket IDs whose manager_feedback files should be archived",
    )
    parser.add_argument(
        "--list-manager-feedback",
        action="store_true",
        help="List manager_feedback files and exit",
    )
    return parser


def main() -> int:  # noqa: C901 - CLI dispatch with multiple modes
    args = _build_parser().parse_args()

    # Resolve collaboration_dir: explicit > derived from project-root > cwd default
    if args.collaboration_dir is not None:
        collaboration_dir = args.collaboration_dir
    elif args.project_root is not None:
        collaboration_dir = args.project_root / ".agent" / "collaboration"
    else:
        collaboration_dir = Path(".agent/collaboration")
    args.collaboration_dir = collaboration_dir

    if args.list_active:
        active_files = list_active_collaboration_files(args.collaboration_dir)
        print("Active collaboration files:")
        for f in active_files:
            print(f"  {f}")
        return 0

    if args.list_manager_feedback:
        feedback_files = find_manager_feedback_files(args.collaboration_dir)
        if feedback_files:
            print("Manager feedback files:")
            for f in feedback_files:
                tid = extract_ticket_id_from_feedback(f.name)
                print(f"  {f.name}  [{tid or 'unknown'}]")
        else:
            print("No manager feedback files found")
        return 0

    if args.archive_manager_feedback:
        ticket_ids = [
            t.strip() for t in args.archive_manager_feedback.split(",") if t.strip()
        ]
        result = archive_manager_feedback(
            collaboration_dir=args.collaboration_dir,
            ticket_ids_to_archive=ticket_ids,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            if result["archived"]:
                print(f"DRY RUN: would archive {len(result['archived'])} file(s):")
                for f in result["archived"]:
                    print(f"  {f}")
            else:
                print("DRY RUN: no manager feedback files to archive")
        else:
            if result["archived"]:
                print(f"Archived {len(result['archived'])} manager feedback file(s)")
            if result["skipped"]:
                print(f"Skipped {len(result['skipped'])} file(s)")
            if result["errors"]:
                print(f"Errors: {len(result['errors'])}")
                for err in result["errors"]:
                    print(f"  {err['file']}: {err['error']}")
        return 1 if result["errors"] else 0

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
