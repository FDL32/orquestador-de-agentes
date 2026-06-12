"""Archival closeout steps extracted from scripts.session_closeout."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from scripts.session_closeout import StepResult


def step_archive_collaboration(
    project_root: Path,
    dry_run: bool,
    *,
    run_script_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run archive_collaboration_artifacts.py."""
    if dry_run:
        return step_result_cls(
            name="archive_collaboration",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    collab_dir = project_root / ".agent" / "collaboration"
    try:
        result = run_script_fn(
            "archive_collaboration_artifacts.py",
            ["--collaboration-dir", str(collab_dir)],
            project_root,
            timeout=60,
        )
        if result.returncode == 0:
            return step_result_cls(
                name="archive_collaboration",
                status="PASS",
                detail="Collaboration artifacts archived",
            )
        return step_result_cls(
            name="archive_collaboration",
            status="WARN",
            detail=f"Archive collaboration returned exit {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return step_result_cls(
            name="archive_collaboration",
            status="WARN",
            detail=f"Archive collaboration could not run: {exc}",
        )


def step_archive_execution_log(
    project_root: Path,
    dry_run: bool,
    *,
    run_script_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run archive_execution_log.py."""
    if dry_run:
        return step_result_cls(
            name="archive_execution_log",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = run_script_fn(
            "archive_execution_log.py",
            [],
            project_root,
            timeout=60,
        )
        if result.returncode == 0:
            return step_result_cls(
                name="archive_execution_log",
                status="PASS",
                detail="Execution log archived",
            )
        return step_result_cls(
            name="archive_execution_log",
            status="WARN",
            detail=f"Archive execution log returned exit {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return step_result_cls(
            name="archive_execution_log",
            status="WARN",
            detail=f"Archive execution log could not run: {exc}",
        )


def step_archive_event_bus(
    project_root: Path,
    dry_run: bool,
    *,
    run_script_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run archive_event_bus.py --all-terminal."""
    if dry_run:
        return step_result_cls(
            name="archive_event_bus",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = run_script_fn(
            "archive_event_bus.py",
            ["--all-terminal"],
            project_root,
            timeout=60,
        )
        if result.returncode == 0:
            return step_result_cls(
                name="archive_event_bus",
                status="PASS",
                detail="Event bus terminal tickets archived",
            )
        return step_result_cls(
            name="archive_event_bus",
            status="WARN",
            detail=f"Archive event bus returned exit {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return step_result_cls(
            name="archive_event_bus",
            status="WARN",
            detail=f"Archive event bus could not run: {exc}",
        )


def _can_prove_close(
    ticket_id: str,
    events: list[dict[str, Any]],
) -> bool:
    """Check if the bus provides unequivocal close/approval for a ticket."""
    for ev in events:
        if ev.get("ticket_id") != ticket_id:
            continue
        if ev.get("event_type") == "SUPERVISOR_CLOSED":
            return True
        if ev.get("event_type") == "STATE_CHANGED":
            payload = ev.get("payload", {})
            to_state = payload.get("to_state")
            if to_state == "COMPLETED":
                return True
            if (
                to_state == "READY_TO_CLOSE"
                and payload.get("source") == "manager-approve"
            ):
                return True
        if ev.get("event_type") == "REVIEW_DECISION":
            payload = ev.get("payload", {})
            if payload.get("decision") == "approve":
                return True
    return False


def _find_manager_feedback_files(
    collaboration_dir: Path,
) -> list[Path]:
    """Find all manager_feedback_*.md files in the collaboration directory."""
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


def _extract_ticket_id_from_feedback(
    filename: str,
    *,
    ticket_id_pattern: str,
) -> str | None:
    """Extract ticket ID from a manager_feedback filename."""
    match = re.search(r"manager_feedback_(" + ticket_id_pattern + r")\.md$", filename)
    if match:
        return match.group(1)
    return None


def step_archive_manager_feedback(  # noqa: C901 - multiple condition checks
    project_root: Path,
    dry_run: bool,
    *,
    events: list[dict[str, Any]],
    manager_feedback_archive_dir_rel: Path,
    ticket_id_pattern: str,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Archive manager_feedback_* files for tickets with proven close/approval."""
    if dry_run:
        return step_result_cls(
            name="archive_manager_feedback",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )

    collab_dir = project_root / ".agent" / "collaboration"
    feedback_files = _find_manager_feedback_files(collab_dir)

    if not feedback_files:
        return step_result_cls(
            name="archive_manager_feedback",
            status="SKIP",
            detail="No manager_feedback files found",
        )

    archive_dir = project_root / manager_feedback_archive_dir_rel
    archived: list[str] = []
    kept: list[str] = []

    for fb_path in feedback_files:
        ticket_id = _extract_ticket_id_from_feedback(
            fb_path.name,
            ticket_id_pattern=ticket_id_pattern,
        )
        if ticket_id is None:
            kept.append(f"{fb_path.name} (unparseable ticket ID)")
            continue

        if _can_prove_close(ticket_id, events):
            try:
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest = archive_dir / fb_path.name
                if dest.exists():
                    fb_path.unlink()
                    archived.append(
                        f"{fb_path.name} (live copy removed; archive exists)"
                    )
                else:
                    shutil.move(str(fb_path), str(dest))
                    archived.append(fb_path.name)
            except OSError as exc:
                kept.append(f"{fb_path.name} (move failed: {exc})")
        else:
            kept.append(f"{fb_path.name} (close not proven)")

    detail_parts: list[str] = []
    if archived:
        detail_parts.append(f"Archived {len(archived)} file(s)")
    if kept:
        detail_parts.append(f"Kept {len(kept)} file(s)")

    if not archived:
        status = "SKIP"
        detail_parts.append("No files archived")
    else:
        status = "PASS"

    return step_result_cls(
        name="archive_manager_feedback",
        status=status,
        detail="; ".join(detail_parts),
    )
