"""Shared closeout helpers extracted from scripts.session_closeout."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from scripts.session_closeout import CloseoutReport, StepResult


def run_script(
    script_name: str,
    args: list[str],
    project_root: Path,
    *,
    scripts_dir: str,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run a script from the scripts/ directory relative to project_root."""
    try:
        from runtime.motor_link import resolve_motor_script

        motor_path = resolve_motor_script(project_root, script_name)
        script_path = (
            motor_path if motor_path else project_root / scripts_dir / script_name
        )
    except ImportError:
        script_path = project_root / scripts_dir / script_name
    cmd = [sys.executable, str(script_path), *args]
    env = os.environ.copy()
    env["AGENT_PROJECT_ROOT"] = str(project_root.resolve())
    return subprocess.run(  # noqa: S603 - controlled script execution
        cmd,
        cwd=str(project_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def process_diagnostic(
    result: subprocess.CompletedProcess[str],
    *,
    limit: int = 500,
) -> str:
    """Return actionable subprocess output, preferring stdout then stderr."""
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return output[-limit:] if output else "No output"


def read_events(project_root: Path, *, events_rel: Path) -> list[dict[str, Any]]:
    """Read all events from events.jsonl."""
    events_path = project_root / events_rel
    if not events_path.exists():
        return []
    events: list[dict[str, Any]] = []
    with open(events_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    events.sort(key=lambda event: event.get("sequence_number", 0))
    return events


def find_last_report_timestamp(
    project_root: Path,
    *,
    report_rel: Path,
) -> str | None:
    """Find the timestamp from the most recent session_close_report.md."""
    report_path = project_root / report_rel
    if not report_path.exists():
        return None
    try:
        content = report_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"\*\*Generated:\*\*\s*(.+)", content)
    if not match:
        return None
    return match.group(1).strip()


def parse_timestamp(ts_str: str) -> datetime | None:
    """Parse an ISO-ish timestamp string to datetime."""
    for fmt in (
        "%Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:  # noqa: PERF203 - small fixed loop, no overhead concern
            continue
    return None


def get_ticket_close_timestamps(
    events: list[dict[str, Any]],
    ticket_ids: list[str],
    *,
    terminal_states: set[str],
) -> dict[str, str]:
    """Get the close timestamp for each ticket from terminal state changes."""
    close_ts: dict[str, str] = {}
    for event in events:
        if event.get("event_type") != "STATE_CHANGED":
            continue
        payload = event.get("payload", {})
        if payload.get("to_state") not in terminal_states:
            continue
        ticket_id = event.get("ticket_id", "")
        if ticket_id in ticket_ids:
            close_ts[ticket_id] = event.get("timestamp", "")
    return close_ts


def _scan_file_for_absolute_paths(
    file_path: Path,
    project_root: Path,
    home_str: str,
    root_str: str,
) -> list[str]:
    matches: list[str] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return matches
    for line_no, line in enumerate(content.splitlines(), 1):
        line_lower = line.replace("\\", "/").lower()
        if home_str in line_lower or root_str in line_lower:
            rel_path = file_path.relative_to(project_root)
            matches.append(f"{rel_path}:{line_no}")
    return matches


def _scan_scan_dir_for_markdown(
    project_root: Path,
    dir_name: str,
    home_str: str,
    root_str: str,
) -> list[str]:
    scan_dir = project_root / dir_name
    if not scan_dir.exists():
        return []
    matches: list[str] = []
    for md_file in scan_dir.rglob("*.md"):
        matches.extend(
            _scan_file_for_absolute_paths(md_file, project_root, home_str, root_str)
        )
    return matches


def _scan_extra_files(
    project_root: Path,
    extra_names: tuple[str, ...],
    home_str: str,
    root_str: str,
) -> list[str]:
    matches: list[str] = []
    for extra_name in extra_names:
        extra_path = project_root / extra_name
        if extra_path.exists() and extra_path.is_file():
            matches.extend(
                _scan_file_for_absolute_paths(
                    extra_path,
                    project_root,
                    home_str,
                    root_str,
                )
            )
    return matches


def _scan_globs_in_dirs(
    project_root: Path,
    dir_names: tuple[str, ...],
    globs: tuple[str, ...],
    home_str: str,
    root_str: str,
) -> list[str]:
    matches: list[str] = []
    for scan_dir_name in dir_names:
        scan_dir = project_root / scan_dir_name
        if not scan_dir.exists():
            continue
        for pattern in globs:
            for matched_file in scan_dir.rglob(pattern):
                if matched_file.is_file():
                    matches.extend(
                        _scan_file_for_absolute_paths(
                            matched_file,
                            project_root,
                            home_str,
                            root_str,
                        )
                    )
    return matches


def check_portability(
    project_root: Path,
    *,
    portability_scan_dirs: tuple[str, ...],
    portability_scan_extra: tuple[str, ...],
    portability_scan_globs: tuple[str, ...],
    step_result_cls: type[StepResult],
) -> StepResult:
    """Check for absolute workspace paths in portable files."""
    home_str = str(Path.home()).replace("\\", "/").lower()
    root_str = str(project_root.resolve()).replace("\\", "/").lower()
    matches: list[str] = []

    for dir_name in portability_scan_dirs:
        matches.extend(
            _scan_scan_dir_for_markdown(project_root, dir_name, home_str, root_str)
        )

    matches.extend(
        _scan_extra_files(project_root, portability_scan_extra, home_str, root_str)
    )

    matches.extend(
        _scan_globs_in_dirs(
            project_root,
            ("scripts", "bus"),
            portability_scan_globs,
            home_str,
            root_str,
        )
    )

    for manifest_file in project_root.glob("MANIFEST*"):
        if manifest_file.is_file():
            matches.extend(
                _scan_file_for_absolute_paths(
                    manifest_file,
                    project_root,
                    home_str,
                    root_str,
                )
            )

    if matches:
        detail = f"Absolute paths found in {len(matches)} file(s): " + ", ".join(
            matches[:5]
        )
        if len(matches) > 5:
            detail += f" (+{len(matches) - 5} more)"
        return step_result_cls(name="portability_paths", status="WARN", detail=detail)

    return step_result_cls(
        name="portability_paths",
        status="PASS",
        detail="No absolute workspace paths found",
    )


def check_versioned_filenames(
    motor_root: Path,
    *,
    subprocess_run,
    step_result_cls: type[StepResult],
    ticket_id_filename_re,
) -> StepResult:
    """Check versioned filenames for embedded ticket IDs."""
    try:
        result = subprocess_run(
            ["git", "ls-files"],
            cwd=str(motor_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return step_result_cls(
            name="versioned_filenames",
            status="WARN",
            detail=f"git ls-files could not run: {exc}",
        )

    if result.returncode != 0:
        return step_result_cls(
            name="versioned_filenames",
            status="WARN",
            detail=f"git ls-files returned exit {result.returncode}: {result.stderr}",
        )

    matches: list[str] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        normalized = line.strip().replace("\\", "/")
        basename = normalized.rsplit("/", 1)[-1]
        if ticket_id_filename_re.search(basename):
            matches.append(normalized)

    if matches:
        detail = (
            f"Ticket IDs found in versioned filenames ({len(matches)}): "
            + ", ".join(matches)
        )
        return step_result_cls(
            name="versioned_filenames",
            status="FAIL",
            detail=detail,
            blocking=False,
        )

    return step_result_cls(
        name="versioned_filenames",
        status="PASS",
        detail="No ticket IDs found in versioned filenames",
    )


def generate_report(
    report: CloseoutReport,
    project_root: Path,
    *,
    dry_run_report_rel: Path,
    report_rel: Path,
) -> Path:
    """Generate the session close report markdown file."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report.session_end = now

    lines = [
        "# Session Close Report",
        "",
        f"**Generated:** {now}",
        f"**Dry Run:** {'Yes' if report.dry_run else 'No'}",
        f"**Skip Slow:** {'Yes' if report.skip_slow else 'No'}",
        "",
        "## Session Window",
        "",
        f"- **Start:** {report.session_start or 'N/A'}",
        f"- **End:** {now}",
        "",
        "## Tickets",
        "",
    ]
    if report.tickets:
        lines.extend(f"- {ticket_id}" for ticket_id in report.tickets)
    else:
        lines.append("- No tickets resolved")

    lines.extend(
        [
            "",
            "## Steps",
            "",
            "| # | Step | Status | Blocking | Detail |",
            "|---|------|--------|----------|--------|",
        ]
    )
    for idx, step in enumerate(report.steps, 1):
        blocking_str = "Yes" if step.blocking else "No"
        detail_escaped = step.detail.replace("|", "\\|")
        lines.append(
            f"| {idx} | {step.name} | {step.status} | {blocking_str} | {detail_escaped} |"
        )

    lines.extend(
        [
            "",
            f"## Overall: {report.overall_status}",
            "",
            "## Manual Recommendations",
            "",
            "The following checks are recommended but not automated in this pipeline:",
            "",
            "- `code-audit` - Deep code quality analysis (run manually if significant Python changes)",
            "- `bui-self-audit` - Self-audit of builder output (run manually for complex tickets)",
            "",
        ]
    )

    target_rel = dry_run_report_rel if report.dry_run else report_rel
    report_path = project_root / target_rel
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
