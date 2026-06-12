"""Rotation and cleanup closeout steps extracted from scripts.session_closeout."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from scripts.session_closeout import StepResult


def is_lock_alive(
    lock_path: Path,
    *,
    lock_ttl_minutes: int,
) -> bool:
    """Check if a lock file is alive based on TTL and mtime."""
    if not lock_path.exists():
        return False
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    now = datetime.now(timezone.utc)
    started_at_str = data.get("started_at")
    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            age_minutes = (now - started_at).total_seconds() / 60
            return age_minutes < lock_ttl_minutes
        except (ValueError, TypeError):
            pass

    try:
        mtime = datetime.fromtimestamp(lock_path.stat().st_mtime, tz=timezone.utc)
        age_minutes = (now - mtime).total_seconds() / 60
        if age_minutes < lock_ttl_minutes:
            return True
    except OSError:
        pass

    return False


def _is_entry_delimiter(line: str) -> bool:
    """Check if a line marks the start of a new logical entry."""
    stripped = line.strip()
    if stripped in ("---",) or stripped.startswith("---"):
        return True
    return bool(re.match(r"^##\s", line))


def _split_header_and_entries(lines: list[str]) -> tuple[str, list[str]]:
    """Split content lines into header and logical entries."""
    dash_indices = [
        i
        for i, line in enumerate(lines)
        if line.strip() in ("---",) or line.strip().startswith("---")
    ]

    if dash_indices:
        first_dash = dash_indices[0]
        header = "\n".join(lines[:first_dash]).strip()
        content_lines = lines[first_dash:]
        delimiter_indices: list[int] = [
            i for i, line in enumerate(content_lines) if _is_entry_delimiter(line)
        ]

        entries: list[str] = []
        for idx, start in enumerate(delimiter_indices):
            end = (
                delimiter_indices[idx + 1]
                if idx + 1 < len(delimiter_indices)
                else len(content_lines)
            )
            entry_lines = content_lines[start:end]
            stripped_line = content_lines[start].strip()
            if stripped_line in ("---",) or stripped_line.startswith("---"):
                entry_lines = entry_lines[1:]
            entry_text = "\n".join(entry_lines).strip()
            if entry_text:
                entries.append(entry_text)

        return header, entries

    hash_indices = [i for i, line in enumerate(lines) if bool(re.match(r"^##\s", line))]
    if hash_indices:
        header = "\n".join(lines[: hash_indices[0]]).strip()
    else:
        header = "\n".join(lines).strip()

    entries: list[str] = []
    for idx, start in enumerate(hash_indices):
        end = hash_indices[idx + 1] if idx + 1 < len(hash_indices) else len(lines)
        entry_text = "\n".join(lines[start:end]).strip()
        if entry_text:
            entries.append(entry_text)

    return header, entries


def parse_review_queue(content: str) -> tuple[str, list[str], str | None]:
    """Parse review_queue.md into header, entries, and active ticket entry."""
    lines = content.split("\n")
    header, entries = _split_header_and_entries(lines)
    return header, entries, None


def _find_active_ticket_entry(
    entries: list[str],
    active_ticket_id: str | None,
) -> tuple[int | None, str | None]:
    """Find the entry matching the active ticket."""
    if active_ticket_id is None:
        return None, None
    for i, entry in enumerate(entries):
        if f"**Plan ID:** {active_ticket_id}" in entry:
            return i, entry
    return None, None


def step_rotate_review_queue(  # noqa: C901 - multiple condition checks
    project_root: Path,
    dry_run: bool,
    *,
    builder_lock_rel: Path,
    keep_entries: int,
    lock_ttl_minutes: int,
    resolve_active_ticket_fn,
    review_queue_archive_dir_rel: Path,
    review_queue_rel: Path,
    size_warn_threshold: int,
    step_result_cls: type[StepResult],
    supervisor_lock_rel: Path,
) -> StepResult:
    """Rotate review_queue.md: archive old entries, keep header + active + recent."""
    if dry_run:
        return step_result_cls(
            name="rotate_review_queue",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )

    review_queue_path = project_root / review_queue_rel
    if not review_queue_path.exists():
        return step_result_cls(
            name="rotate_review_queue",
            status="SKIP",
            detail="review_queue.md does not exist; nothing to rotate",
        )

    builder_lock = project_root / builder_lock_rel
    supervisor_lock = project_root / supervisor_lock_rel
    lock_alive = False
    lock_detail_parts: list[str] = []

    if is_lock_alive(builder_lock, lock_ttl_minutes=lock_ttl_minutes):
        lock_alive = True
        lock_detail_parts.append("builder_lock.txt alive")
    if is_lock_alive(supervisor_lock, lock_ttl_minutes=lock_ttl_minutes):
        lock_alive = True
        lock_detail_parts.append("supervisor_lock.txt alive")

    if lock_alive:
        return step_result_cls(
            name="rotate_review_queue",
            status="SKIP",
            detail=f"Skipped: lock(s) alive: {', '.join(lock_detail_parts)}",
        )

    print(
        "[rotate_review_queue] Advisory: no reusable detector for Manager "
        "Bridge/Stop Hook; proceeding with best-effort rotation",
        file=sys.stderr,
    )

    try:
        content = review_queue_path.read_text(encoding="utf-8")
    except OSError as exc:
        return step_result_cls(
            name="rotate_review_queue",
            status="WARN",
            detail=f"Could not read review_queue.md: {exc}",
        )

    header, entries, _active_entry = parse_review_queue(content)
    if not entries:
        return step_result_cls(
            name="rotate_review_queue",
            status="SKIP",
            detail="review_queue.md has no parsed entries; nothing to rotate",
        )

    wpid = resolve_active_ticket_fn(project_root)
    active_idx, active_entry = _find_active_ticket_entry(entries, wpid)
    keep_start = max(0, len(entries) - keep_entries)
    kept_entries = entries[keep_start:]
    archived_entries = entries[:keep_start]

    if active_idx is not None and active_idx < keep_start:
        kept_entries.insert(0, active_entry)
        if active_idx < len(archived_entries):
            archived_entries.remove(active_entry)

    if not archived_entries:
        kept_content = header + "\n"
        for entry in kept_entries:
            kept_content += "---\n\n" + entry + "\n\n"
        kept_size_bytes = len(kept_content.encode("utf-8"))
        if kept_size_bytes > size_warn_threshold:
            return step_result_cls(
                name="rotate_review_queue",
                status="WARN",
                detail=(
                    f"Fewer entries than KEEP_ENTRIES; nothing to archive. "
                    f"WARNING: kept entries exceed {size_warn_threshold // 1024} KB"
                ),
            )
        return step_result_cls(
            name="rotate_review_queue",
            status="SKIP",
            detail="Fewer entries than KEEP_ENTRIES; nothing to archive",
        )

    archive_dir = project_root / review_queue_archive_dir_rel
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_path = archive_dir / f"review_queue_{date_str}.md"

    archive_lines = [
        f"# Archived Review Queue - {date_str}",
        "",
        f"Archived from review_queue.md on {date_str}.",
        f"Total archived entries: {len(archived_entries)}",
        "",
    ]
    for entry in archived_entries:
        archive_lines.append("---")
        archive_lines.append("")
        archive_lines.append(entry)
        archive_lines.append("")

    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        new_archive_content = "\n".join(archive_lines)
        if archive_path.exists():
            existing = archive_path.read_text(encoding="utf-8")
            archive_path.write_text(
                existing.rstrip("\n") + "\n\n" + new_archive_content,
                encoding="utf-8",
            )
        else:
            archive_path.write_text(new_archive_content, encoding="utf-8")
    except OSError as exc:
        return step_result_cls(
            name="rotate_review_queue",
            status="WARN",
            detail=f"Could not write archive file: {exc}",
        )

    truncated_lines = [header, ""]
    for entry in kept_entries:
        truncated_lines.append("---")
        truncated_lines.append("")
        truncated_lines.append(entry)
        truncated_lines.append("")

    truncated_content = "\n".join(truncated_lines)
    kept_size = len(truncated_content.encode("utf-8"))
    size_warning = kept_size > size_warn_threshold

    try:
        review_queue_path.write_text(truncated_content, encoding="utf-8")
    except OSError as exc:
        return step_result_cls(
            name="rotate_review_queue",
            status="WARN",
            detail=f"Could not write truncated review_queue.md: {exc}",
        )

    detail_parts = [
        f"Archived {len(archived_entries)} entr(es)",
        f"kept {len(kept_entries)} entr(es)",
    ]
    if size_warning:
        detail_parts.append(
            f"WARNING: kept entries exceed {size_warn_threshold // 1024} KB"
        )
    status = "WARN" if size_warning else "PASS"

    return step_result_cls(
        name="rotate_review_queue",
        status=status,
        detail="; ".join(detail_parts),
    )


def step_cleanup_builder_session(
    project_root: Path,
    dry_run: bool,
    *,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Remove builder_session.json if it exists."""
    if dry_run:
        return step_result_cls(
            name="cleanup_builder_session",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    session_path = project_root / ".agent" / "runtime" / "builder_session.json"
    if session_path.exists():
        try:
            session_path.unlink()
            return step_result_cls(
                name="cleanup_builder_session",
                status="PASS",
                detail="builder_session.json removed",
            )
        except OSError as exc:
            return step_result_cls(
                name="cleanup_builder_session",
                status="WARN",
                detail=f"Could not remove builder_session.json: {exc}",
            )
    return step_result_cls(
        name="cleanup_builder_session",
        status="SKIP",
        detail="builder_session.json already absent",
    )


def step_git_clean(
    project_root: Path,
    dry_run: bool,
    *,
    subprocess_run,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Verify git status --short is clean (except expected runtime files)."""
    if dry_run:
        return step_result_cls(
            name="git_clean",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        from runtime.motor_link import resolve_motor_root

        motor_root = resolve_motor_root(project_root)
        if motor_root is None:
            return step_result_cls(
                name="git_clean",
                status="WARN",
                detail="motor_root no resoluble (motor_destination_link.json ausente); "
                "check de git saltado (no bloqueante)",
            )
        result = subprocess_run(
            ["git", "status", "--short"],
            cwd=str(motor_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr_msg = (result.stderr or "").strip()
            if "not a git repository" in stderr_msg.lower():
                return step_result_cls(
                    name="git_clean",
                    status="WARN",
                    detail="Workspace not a git repository (tolerated for workspace+motor architecture)",
                )
            return step_result_cls(
                name="git_clean",
                status="WARN",
                detail=f"git status returned exit {result.returncode}: {stderr_msg}",
            )
        dirty_lines = [
            line for line in result.stdout.strip().splitlines() if line.strip()
        ]
        expected_patterns = [
            "session_close_report.md",
            "CONSOLIDATION_REPORT.md",
            "MEMORY.md",
            "observations.jsonl",
        ]
        unexpected = [
            line
            for line in dirty_lines
            if not any(pat in line for pat in expected_patterns)
        ]
        if not unexpected:
            return step_result_cls(
                name="git_clean",
                status="PASS",
                detail=f"Tree clean ({len(dirty_lines)} expected runtime file(s) dirty)",
            )
        return step_result_cls(
            name="git_clean",
            status="WARN",
            detail=f"Tree dirty with {len(unexpected)} unexpected file(s): {unexpected[:3]}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return step_result_cls(
            name="git_clean",
            status="WARN",
            detail=f"git status could not run: {exc} (tolerated for workspace+motor architecture)",
        )
