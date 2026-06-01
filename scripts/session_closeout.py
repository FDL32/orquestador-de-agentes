#!/usr/bin/env python3
"""Session Closeout Orchestrator - unified session close pipeline.

Before (Pre-condiciones):
    - El repositorio debe existir con la estructura .agent/ canónica.
    - `events.jsonl` debe existir en `.agent/runtime/events/` (puede estar vacío).
    - `work_plan.md` debe existir en `.agent/collaboration/` como fallback de tickets.
    - Scripts orquestados (`prepush_check.py`, `local_audit.py`, etc.) deben existir
      en `scripts/` relativo a project_root.

During (Proceso y Recursos):
    - Resuelve la ventana de sesion desde el ultimo `session_close_report.md` o desde
      el primer evento de `events.jsonl` (first-run fallback).
    - Resuelve tickets con prioridad: explicitos CLI > detectados en ventana > activo de work_plan.
    - Ejecuta en secuencia: prepush_check (bloqueante), local_audit (informativo),
      validate_ticket_prose (informativo), session_close_observations (por ticket),
      memory_consolidate (unless --skip-slow), archivadores, verificacion de portabilidad.
    - Genera `.agent/runtime/memory/session_close_report.md` con PASS/WARN/FAIL por paso.
    - En `--dry-run` genera el reporte sin ejecutar scripts destructivos.

After (Post-condiciones y Errores):
    - Exit code 0 si el cierre completo pasa (prepush_check OK + sin errores fatales).
    - Exit code 1 si prepush_check falla o hay errores fatales en pasos bloqueantes.
    - El reporte se escribe siempre, incluyendo en `--dry-run`.
    - `git status --short` debe quedar limpio salvo por el reporte.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TERMINAL_STATES = {"COMPLETED", "HUMAN_GATE"}

# Lock files (relative to project_root)
BUILDER_LOCK_REL = Path(".agent") / "runtime" / "builder_lock.txt"
SUPERVISOR_LOCK_REL = Path(".agent") / "runtime" / "supervisor_lock.txt"

# Review queue paths (relative to project_root)
REVIEW_QUEUE_REL = Path(".agent") / "collaboration" / "review_queue.md"
REVIEW_QUEUE_ARCHIVE_DIR_REL = Path(".agent") / "collaboration" / "archive"

# Manager feedback paths (relative to project_root)
MANAGER_FEEDBACK_ARCHIVE_DIR_REL = (
    Path(".agent") / "collaboration" / "archive" / "manager_feedback"
)

# Rotation constants
KEEP_ENTRIES = 10
SIZE_WARN_THRESHOLD = 50 * 1024  # 50 KB advisory threshold

# Directories to scan for absolute workspace paths (portability check)
PORTABILITY_SCAN_DIRS = ("docs", "markdowns", "skills", ".agent/rules")

# Additional specific entries to scan (files beyond the directories above)
PORTABILITY_SCAN_EXTRA = ("README.md", "PROJECT.md")

# Glob patterns to scan for hardcoded paths (combined with directories)
PORTABILITY_SCAN_GLOBS = ("*.py", "*.ps1", "*.md", "MANIFEST*")

# Report path (relative to project_root)
REPORT_REL = Path(".agent") / "runtime" / "memory" / "session_close_report.md"

# Events file (relative to project_root)
EVENTS_REL = Path(".agent") / "runtime" / "events" / "events.jsonl"

# Work plan (relative to project_root)
WORK_PLAN_REL = Path(".agent") / "collaboration" / "work_plan.md"

# Scripts directory (relative to project_root)
SCRIPTS_DIR = "scripts"

# Ticket regex pattern
TICKET_RE = re.compile(r"(?:WP|WT)-\d{4}-\d{3}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Result of a single closeout step."""

    name: str
    status: str  # PASS, WARN, FAIL, SKIP
    detail: str = ""
    blocking: bool = False


@dataclass
class CloseoutReport:
    """Aggregated closeout report."""

    session_start: str = ""
    session_end: str = ""
    tickets: list[str] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    dry_run: bool = False
    skip_slow: bool = False

    @property
    def overall_status(self) -> str:
        """Overall status: FAIL if any blocking step failed, WARN if any warn, else PASS."""
        statuses = [s.status for s in self.steps]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        return "PASS"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(
    script_name: str,
    args: list[str],
    project_root: Path,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run a script from the scripts/ directory relative to project_root.

    Before: script_name must be a filename in scripts/.
    During: Resolves script path via motor_link (Model B) first; falls back to
            local project_root/scripts/<name>. Constructs [sys.executable,
            script_path, *args] and runs it with cwd=project_root,
            capturing stdout/stderr as text.
    After: Returns CompletedProcess. Caller handles exceptions.
    """
    try:
        from runtime.motor_link import resolve_motor_script

        motor_path = resolve_motor_script(project_root, script_name)
        script_path = (
            motor_path if motor_path else project_root / SCRIPTS_DIR / script_name
        )
    except ImportError:
        script_path = project_root / SCRIPTS_DIR / script_name
    cmd = [sys.executable, str(script_path), *args]
    return subprocess.run(  # noqa: S603 - controlled script execution
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _read_events(project_root: Path) -> list[dict[str, Any]]:
    """Read all events from events.jsonl.

    Before: events.jsonl may or may not exist.
    During: Reads each line as JSON, skips malformed lines.
    After: Returns list of event dicts sorted by sequence_number.
    """
    events_path = project_root / EVENTS_REL
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
    events.sort(key=lambda e: e.get("sequence_number", 0))
    return events


def _find_last_report_timestamp(project_root: Path) -> str | None:
    """Find the timestamp from the most recent session_close_report.md.

    Before: report may or may not exist in .agent/runtime/memory/.
    During: Parses the '**Generated:**' line from the report.
    After: Returns ISO timestamp string or None if no report found.
    """
    report_path = project_root / REPORT_REL
    if not report_path.exists():
        return None
    try:
        content = report_path.read_text(encoding="utf-8")
    except OSError:
        return None
    # Match "**Generated:** 2026-05-27 00:00:00 UTC"
    m = re.search(r"\*\*Generated:\*\*\s*(.+)", content)
    if not m:
        return None
    return m.group(1).strip()


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Parse an ISO-ish timestamp string to datetime.

    Before: ts_str is a non-empty string.
    During: Tries multiple formats.
    After: Returns datetime or None if unparseable.
    """
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


def _resolve_session_window(
    project_root: Path,
) -> tuple[datetime | None, str]:
    """Resolve the session window start timestamp.

    Before: events.jsonl and session_close_report.md may or may not exist.
    During: Checks for last report timestamp; falls back to first event.
    After: Returns (start_datetime, source_description).
    """
    last_ts_str = _find_last_report_timestamp(project_root)
    if last_ts_str:
        dt = _parse_timestamp(last_ts_str)
        if dt is not None:
            return dt, f"from last report ({last_ts_str})"

    events = _read_events(project_root)
    if events:
        first_ts = events[0].get("timestamp", "")
        dt = _parse_timestamp(first_ts)
        if dt is not None:
            return dt, f"from first event ({first_ts})"

    return None, "no events or reports found"


def _detect_tickets_in_window(
    events: list[dict[str, Any]],
    window_start: datetime | None,
) -> list[str]:
    """Detect ticket IDs from events within the session window.

    Before: events is sorted by sequence_number.
    During: Filters events with timestamp >= window_start, extracts unique ticket_ids.
    After: Returns deduplicated list of ticket IDs in first-seen order.
    """
    if window_start is None:
        # No window: return all ticket IDs
        seen: dict[str, None] = {}
        for ev in events:
            tid = ev.get("ticket_id", "")
            if tid and tid not in seen:
                seen[tid] = None
        return list(seen.keys())

    seen = {}
    for ev in events:
        ts_str = ev.get("timestamp", "")
        dt = _parse_timestamp(ts_str)
        if dt is None:
            continue
        # Ensure both datetimes are comparable (both naive or both aware)
        comparable_start = window_start
        if dt.tzinfo is not None and comparable_start.tzinfo is None:
            comparable_start = comparable_start.replace(tzinfo=timezone.utc)
        elif dt.tzinfo is None and comparable_start.tzinfo is not None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= comparable_start:
            tid = ev.get("ticket_id", "")
            if tid and tid not in seen:
                seen[tid] = None
    return list(seen.keys())


def _resolve_active_ticket(project_root: Path) -> str | None:
    """Resolve the active ticket ID from work_plan.md.

    Before: work_plan.md must exist.
    During: Searches for '- **ID:** WP-YYYY-NNN' pattern.
    After: Returns ticket ID string or None.
    """
    wp_path = project_root / WORK_PLAN_REL
    if not wp_path.exists():
        return None
    try:
        content = wp_path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"-?\s*\*\*ID:\*\*\s*((?:WP|WT)-\d{4}-\d{3})", content)
    if m:
        return m.group(1)
    return None


def _resolve_tickets(
    project_root: Path,
    explicit_tickets: list[str] | None,
) -> tuple[list[str], str]:
    """Resolve tickets to audit using the priority chain.

    Before: project_root is valid, explicit_tickets may be None/empty.
    During: Priority: explicit CLI > detected in window > active from work_plan.
    After: Returns (ticket_list, source_description).
    """
    if explicit_tickets:
        return explicit_tickets, "explicit from CLI"

    events = _read_events(project_root)
    window_start, _window_src = _resolve_session_window(project_root)
    detected = _detect_tickets_in_window(events, window_start)

    if detected:
        return detected, "detected in session window"

    active = _resolve_active_ticket(project_root)
    if active:
        return [active], "fallback from work_plan.md active ticket"

    return [], "no tickets found"


def _get_ticket_close_timestamps(
    events: list[dict[str, Any]],
    ticket_ids: list[str],
) -> dict[str, str]:
    """Get the close timestamp for each ticket from STATE_CHANGED -> COMPLETED events.

    Before: events is sorted by sequence_number.
    During: Finds the latest STATE_CHANGED event with to_state=COMPLETED for each ticket.
    After: Returns dict mapping ticket_id -> timestamp string.
    """
    close_ts: dict[str, str] = {}
    for ev in events:
        if ev.get("event_type") != "STATE_CHANGED":
            continue
        payload = ev.get("payload", {})
        if payload.get("to_state") not in TERMINAL_STATES:
            continue
        tid = ev.get("ticket_id", "")
        if tid in ticket_ids:
            close_ts[tid] = ev.get("timestamp", "")
    return close_ts


# ---------------------------------------------------------------------------
# Portability check
# ---------------------------------------------------------------------------


def _scan_file_for_absolute_paths(
    file_path: Path, project_root: Path, home_str: str, root_str: str
) -> list[str]:
    """Scan a single file for absolute path references.

    Before: file_path exists and is readable.
    During: Reads file content, checks each line for home or project root paths.
    After: Returns list of "rel_path:line_number" matches.
    """
    matches: list[str] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return matches
    for i, line in enumerate(content.splitlines(), 1):
        line_lower = line.replace("\\", "/").lower()
        if home_str in line_lower or root_str in line_lower:
            rel = file_path.relative_to(project_root)
            matches.append(f"{rel}:{i}")
    return matches


def _scan_scan_dir_for_markdown(
    project_root: Path, dir_name: str, home_str: str, root_str: str
) -> list[str]:
    """Scan a single directory recursively for *.md files with absolute paths."""
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
    project_root: Path, extra_names: tuple[str, ...], home_str: str, root_str: str
) -> list[str]:
    """Scan explicit file names at project root for absolute paths."""
    matches: list[str] = []
    for extra_name in extra_names:
        extra_path = project_root / extra_name
        if extra_path.exists() and extra_path.is_file():
            matches.extend(
                _scan_file_for_absolute_paths(
                    extra_path, project_root, home_str, root_str
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
    """Scan directories with glob patterns for absolute paths."""
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
                            matched_file, project_root, home_str, root_str
                        )
                    )
    return matches


def _check_portability(project_root: Path) -> StepResult:
    """Check for absolute workspace paths in portable files.

    Before: project_root is valid.
    During: Scans docs/, markdowns/, skills/, scripts/, bus/, .agent/rules/
            for absolute paths derived from Path.home() or project_root.resolve().
            Also scans *.py, *.ps1, *.md, MANIFEST* globs and explicit files
            like README.md, PROJECT.md.
    After: Returns StepResult with WARN if matches found, PASS otherwise.
    """
    home_str = str(Path.home()).replace("\\", "/").lower()
    root_str = str(project_root.resolve()).replace("\\", "/").lower()

    matches: list[str] = []

    # Scan directories recursively for markdown
    for dir_name in PORTABILITY_SCAN_DIRS:
        matches.extend(
            _scan_scan_dir_for_markdown(project_root, dir_name, home_str, root_str)
        )

    # Scan extra explicit files
    matches.extend(
        _scan_extra_files(project_root, PORTABILITY_SCAN_EXTRA, home_str, root_str)
    )

    # Scan scripts/ and bus/ directories with glob patterns
    matches.extend(
        _scan_globs_in_dirs(
            project_root,
            ("scripts", "bus"),
            PORTABILITY_SCAN_GLOBS,
            home_str,
            root_str,
        )
    )

    # Scan MANIFEST* files at root
    for manifest_file in project_root.glob("MANIFEST*"):
        if manifest_file.is_file():
            matches.extend(
                _scan_file_for_absolute_paths(
                    manifest_file, project_root, home_str, root_str
                )
            )

    if matches:
        detail = f"Absolute paths found in {len(matches)} file(s): " + ", ".join(
            matches[:5]
        )
        if len(matches) > 5:
            detail += f" (+{len(matches) - 5} more)"
        return StepResult(name="portability_paths", status="WARN", detail=detail)

    return StepResult(
        name="portability_paths",
        status="PASS",
        detail="No absolute workspace paths found",
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _generate_report(report: CloseoutReport, project_root: Path) -> Path:
    """Generate the session close report markdown file.

    Before: report has all steps populated.
    During: Formats steps as a table and writes to session_close_report.md.
    After: Returns the path to the written report.
    """
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
        lines.extend(f"- {tid}" for tid in report.tickets)
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
    for i, step in enumerate(report.steps, 1):
        blocking_str = "Yes" if step.blocking else "No"
        detail_escaped = step.detail.replace("|", "\\|")
        lines.append(
            f"| {i} | {step.name} | {step.status} | {blocking_str} | {detail_escaped} |"
        )

    lines.extend(
        [
            "",
            f"## Overall: {report.overall_status}",
            "",
        ]
    )

    # Add manual recommendations section
    lines.extend(
        [
            "## Manual Recommendations",
            "",
            "The following checks are recommended but not automated in this pipeline:",
            "",
            "- `code-audit` — Deep code quality analysis (run manually if significant Python changes)",
            "- `bui-self-audit` — Self-audit of builder output (run manually for complex tickets)",
            "",
        ]
    )

    report_path = project_root / REPORT_REL
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# Step executors
# ---------------------------------------------------------------------------


def _step_prepush_check(project_root: Path, dry_run: bool) -> StepResult:
    """Run prepush_check.py as the blocking quality gate.

    Before: prepush_check.py must exist in scripts/.
    During: Runs the script with --project-root. Expects exit 0 for pass.
    After: Returns PASS if exit 0, FAIL otherwise.
    """
    if dry_run:
        return StepResult(
            name="prepush_check",
            status="SKIP",
            detail="Skipped in dry-run mode",
            blocking=True,
        )
    try:
        result = _run_script(
            "prepush_check.py",
            ["--project-root", str(project_root)],
            project_root,
            timeout=300,
        )
        if result.returncode == 0:
            return StepResult(
                name="prepush_check",
                status="PASS",
                detail="All blocking quality checks passed",
                blocking=True,
            )
        detail = result.stdout[-500:] if result.stdout else "No output"
        return StepResult(
            name="prepush_check",
            status="FAIL",
            detail=f"Quality gate failed (exit {result.returncode}): {detail}",
            blocking=True,
        )
    except subprocess.TimeoutExpired:
        return StepResult(
            name="prepush_check",
            status="FAIL",
            detail="prepush_check.py timed out after 300s",
            blocking=True,
        )
    except FileNotFoundError:
        return StepResult(
            name="prepush_check",
            status="FAIL",
            detail="prepush_check.py not found in scripts/",
            blocking=True,
        )


def _step_local_audit(project_root: Path, dry_run: bool) -> StepResult:
    """Run local_audit.py as an informational snapshot.

    Before: local_audit.py must exist in scripts/.
    During: Runs with --json --quick. Always returns PASS (informational).
    After: Returns PASS with summary or WARN on error.
    """
    if dry_run:
        return StepResult(
            name="local_audit",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = _run_script(
            "local_audit.py",
            ["--json", "--quick"],
            project_root,
            timeout=120,
        )
        if result.returncode == 0:
            return StepResult(
                name="local_audit",
                status="PASS",
                detail="Local audit snapshot captured",
            )
        return StepResult(
            name="local_audit",
            status="WARN",
            detail=f"Local audit returned exit {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return StepResult(
            name="local_audit",
            status="WARN",
            detail=f"Local audit could not run: {exc}",
        )


def _step_validate_ticket_prose(project_root: Path, dry_run: bool) -> StepResult:
    """Run validate_ticket_prose.py --json as informational check.

    Before: validate_ticket_prose.py must exist in scripts/.
    During: Runs with --json. Always returns PASS (informational, exit 0 always).
    After: Returns PASS with summary.
    """
    if dry_run:
        return StepResult(
            name="validate_ticket_prose",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = _run_script(
            "validate_ticket_prose.py",
            ["--json"],
            project_root,
            timeout=60,
        )
        # validate_ticket_prose always exits 0; parse JSON for warnings
        warnings = 0
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                warnings = len(data.get("warnings", []))
            except (json.JSONDecodeError, AttributeError):
                pass
        detail = (
            f"Ticket prose validated, {warnings} warning(s)"
            if warnings
            else "Ticket prose validated, clean"
        )
        return StepResult(
            name="validate_ticket_prose",
            status="PASS" if warnings == 0 else "WARN",
            detail=detail,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return StepResult(
            name="validate_ticket_prose",
            status="WARN",
            detail=f"Ticket prose validation could not run: {exc}",
        )


def _step_session_observations(
    ticket_ids: list[str],
    project_root: Path,
    dry_run: bool,
    close_timestamps: dict[str, str],
) -> list[StepResult]:
    """Run session_close_observations.py once per resolved ticket.

    Before: session_close_observations.py must exist in scripts/.
    During: Runs --ticket <id> for each ticket, in chronological close order.
    After: Returns one StepResult per ticket.
    """
    results: list[StepResult] = []
    if dry_run:
        results.extend(
            StepResult(
                name=f"observations:{tid}",
                status="SKIP",
                detail="Skipped in dry-run mode",
            )
            for tid in ticket_ids
        )
        return results

    # Sort tickets by close timestamp (earliest first)
    sorted_tickets = sorted(
        ticket_ids,
        key=lambda t: close_timestamps.get(t, ""),
    )

    for tid in sorted_tickets:
        try:
            result = _run_script(
                "session_close_observations.py",
                ["--ticket", tid],
                project_root,
                timeout=120,
            )
            if result.returncode == 0:
                results.append(
                    StepResult(
                        name=f"observations:{tid}",
                        status="PASS",
                        detail=f"Observations processed for {tid}",
                    )
                )
            else:
                detail = result.stdout[-300:] if result.stdout else "No output"
                results.append(
                    StepResult(
                        name=f"observations:{tid}",
                        status="WARN",
                        detail=f"Observations script returned exit {result.returncode} for {tid}: {detail}",
                    )
                )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:  # noqa: PERF203 - small fixed loop
            results.append(
                StepResult(
                    name=f"observations:{tid}",
                    status="WARN",
                    detail=f"Observations could not run for {tid}: {exc}",
                )
            )
    return results


def _step_memory_consolidate(project_root: Path, dry_run: bool) -> StepResult:
    """Run memory_consolidate.py --verbose --apply.

    Before: memory_consolidate.py must exist in scripts/.
    During: Runs with --verbose --apply to consolidate observations.
    After: Returns PASS or WARN.
    """
    if dry_run:
        return StepResult(
            name="memory_consolidate",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = _run_script(
            "memory_consolidate.py",
            ["--verbose", "--apply"],
            project_root,
            timeout=120,
        )
        if result.returncode == 0:
            return StepResult(
                name="memory_consolidate",
                status="PASS",
                detail="Memory consolidated successfully",
            )
        return StepResult(
            name="memory_consolidate",
            status="WARN",
            detail=f"Memory consolidate returned exit {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return StepResult(
            name="memory_consolidate",
            status="WARN",
            detail=f"Memory consolidate could not run: {exc}",
        )


def _step_archive_collaboration(project_root: Path, dry_run: bool) -> StepResult:
    """Run archive_collaboration_artifacts.py.

    Before: archive_collaboration_artifacts.py must exist in scripts/.
    During: Runs with --collaboration-dir pointing to .agent/collaboration.
    After: Returns PASS or WARN.
    """
    if dry_run:
        return StepResult(
            name="archive_collaboration",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    collab_dir = project_root / ".agent" / "collaboration"
    try:
        result = _run_script(
            "archive_collaboration_artifacts.py",
            ["--collaboration-dir", str(collab_dir)],
            project_root,
            timeout=60,
        )
        if result.returncode == 0:
            return StepResult(
                name="archive_collaboration",
                status="PASS",
                detail="Collaboration artifacts archived",
            )
        return StepResult(
            name="archive_collaboration",
            status="WARN",
            detail=f"Archive collaboration returned exit {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return StepResult(
            name="archive_collaboration",
            status="WARN",
            detail=f"Archive collaboration could not run: {exc}",
        )


def _step_archive_execution_log(project_root: Path, dry_run: bool) -> StepResult:
    """Run archive_execution_log.py.

    Before: archive_execution_log.py must exist in scripts/.
    During: Runs with default args.
    After: Returns PASS or WARN.
    """
    if dry_run:
        return StepResult(
            name="archive_execution_log",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = _run_script(
            "archive_execution_log.py",
            [],
            project_root,
            timeout=60,
        )
        if result.returncode == 0:
            return StepResult(
                name="archive_execution_log",
                status="PASS",
                detail="Execution log archived",
            )
        return StepResult(
            name="archive_execution_log",
            status="WARN",
            detail=f"Archive execution log returned exit {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return StepResult(
            name="archive_execution_log",
            status="WARN",
            detail=f"Archive execution log could not run: {exc}",
        )


def _step_archive_event_bus(project_root: Path, dry_run: bool) -> StepResult:
    """Run archive_event_bus.py --all-terminal.

    Before: archive_event_bus.py must exist in scripts/.
    During: Runs with --all-terminal to archive completed/human_gate tickets.
    After: Returns PASS or WARN.
    """
    if dry_run:
        return StepResult(
            name="archive_event_bus",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = _run_script(
            "archive_event_bus.py",
            ["--all-terminal"],
            project_root,
            timeout=60,
        )
        if result.returncode == 0:
            return StepResult(
                name="archive_event_bus",
                status="PASS",
                detail="Event bus terminal tickets archived",
            )
        return StepResult(
            name="archive_event_bus",
            status="WARN",
            detail=f"Archive event bus returned exit {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return StepResult(
            name="archive_event_bus",
            status="WARN",
            detail=f"Archive event bus could not run: {exc}",
        )


# ---------------------------------------------------------------------------
# Review queue rotation
# ---------------------------------------------------------------------------


def _is_lock_alive(lock_path: Path) -> bool:
    """Check if a lock file has an alive PID on Windows.

    Before: lock_path may or may not exist.
    During: Reads the lock file as JSON. If it contains a 'pid' field,
            attempts to check if the process is running via tasklist.
    After: Returns True if the PID is alive, False if the lock is stale
           or does not exist.
    """
    if not lock_path.exists():
        return False
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    pid = data.get("pid")
    if pid is None:
        return False
    if not isinstance(pid, int) or pid <= 0:
        return False
    # On Windows, use tasklist to check if the process exists
    try:
        result = subprocess.run(  # noqa: S603 - controlled PID from lock file
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False
        # tasklist returns "INFO: No tasks are running..." if not found
        return str(pid) in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        # If we can't check, conservatively return True (lock assumed alive)
        return True


def _parse_review_queue(content: str) -> tuple[str, list[str], str | None]:
    """Parse review_queue.md into header, entries, and active ticket entry.

    Before: content is the full text of review_queue.md.
    During: Splits by '---' separator. Everything before the first '---' is the
            header. Each block between separators is an entry. Also detects
            '## ' prefix as an alternative delimiter, but the primary format
            uses '---'.
    After: Returns (header_text, list_of_entries, active_ticket_entry_or_None).
    """
    # Split by separator lines
    lines = content.split("\n")
    header_lines: list[str] = []
    entries: list[str] = []
    current_entry: list[str] = []
    in_header = True
    found_first_sep = False

    for line in lines:
        stripped = line.strip()
        # Detect separator: line is exactly "---" or starts with "---"
        if stripped in ("---",) or stripped.startswith("---"):
            if not found_first_sep:
                # First separator: header ends
                found_first_sep = True
                in_header = False
                if current_entry:
                    entries.append("\n".join(current_entry))
                    current_entry = []
                continue
            # Subsequent separators: current entry ends
            if current_entry:
                entries.append("\n".join(current_entry))
                current_entry = []
            continue
        # Detect '## ' prefix as alternative entry start (at top level)
        if not in_header and re.match(r"^##\s", line) and current_entry:
            # Complete previous entry and start new one (include the ## line)
            entries.append("\n".join(current_entry))
            current_entry = [line]
            continue

        if in_header:
            header_lines.append(line)
        else:
            current_entry.append(line)

    # Flush last entry
    if current_entry:
        entries.append("\n".join(current_entry))

    header = "\n".join(header_lines).strip()

    # Detect active ticket entry: look for "- **Plan ID:**" in each entry
    # The active ticket is the one in work_plan.md
    active_entry: str | None = None
    # We detect by reading work_plan.md to find the active ticket ID
    # This will be done at the call site; here we just return entries as-is.
    # The caller will identify the active ticket entry.

    return header, entries, active_entry


def _find_active_ticket_entry(
    entries: list[str], active_ticket_id: str | None
) -> tuple[int | None, str | None]:
    """Find the entry matching the active ticket.

    Before: entries is a list of entry strings; active_ticket_id may be None.
    During: Searches each entry for a '- **Plan ID:** <active_ticket_id>' line.
    After: Returns (index, entry_text) or (None, None).
    """
    if active_ticket_id is None:
        return None, None
    for i, entry in enumerate(entries):
        if f"**Plan ID:** {active_ticket_id}" in entry:
            return i, entry
    return None, None


def _step_rotate_review_queue(project_root: Path, dry_run: bool) -> StepResult:  # noqa: C901 - multiple condition checks
    """Rotate review_queue.md: archive old entries, keep header + active + 10 recent.

    Before: project_root is the repository root. review_queue.md may or may not exist.
    During:
        1. Check builder_lock.txt and supervisor_lock.txt for alive locks.
        2. If any lock is alive, skip rotation and return advisory warning.
        3. Read review_queue.md, parse header and entries by '---' delimiter.
        4. Identify active ticket from work_plan.md.
        5. Keep header, active ticket entry (if found and not already in top 10),
           and up to 10 most recent logical entries.
        6. Archive old entries to archive/review_queue_YYYY-MM-DD.md.
        7. Write truncated content back.
        8. If kept entries exceed 50 KB, emit warning advisory.
    After: Returns StepResult with PASS, SKIP, or WARN.
    """
    if dry_run:
        return StepResult(
            name="rotate_review_queue",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )

    review_queue_path = project_root / REVIEW_QUEUE_REL
    if not review_queue_path.exists():
        return StepResult(
            name="rotate_review_queue",
            status="SKIP",
            detail="review_queue.md does not exist; nothing to rotate",
        )

    # --- Lock checks ---
    builder_lock = project_root / BUILDER_LOCK_REL
    supervisor_lock = project_root / SUPERVISOR_LOCK_REL

    lock_alive = False
    lock_detail_parts: list[str] = []

    if _is_lock_alive(builder_lock):
        lock_alive = True
        lock_detail_parts.append("builder_lock.txt alive")
    if _is_lock_alive(supervisor_lock):
        lock_alive = True
        lock_detail_parts.append("supervisor_lock.txt alive")

    if lock_alive:
        return StepResult(
            name="rotate_review_queue",
            status="SKIP",
            detail=f"Skipped: lock(s) alive: {', '.join(lock_detail_parts)}",
        )

    # --- Parse review queue ---
    try:
        content = review_queue_path.read_text(encoding="utf-8")
    except OSError as exc:
        return StepResult(
            name="rotate_review_queue",
            status="WARN",
            detail=f"Could not read review_queue.md: {exc}",
        )

    header, entries, _active_entry = _parse_review_queue(content)

    if not entries:
        return StepResult(
            name="rotate_review_queue",
            status="SKIP",
            detail="review_queue.md has no parsed entries; nothing to rotate",
        )

    # --- Identify active ticket entry ---
    wpid = _resolve_active_ticket(project_root)
    active_idx, active_entry = _find_active_ticket_entry(entries, wpid)

    # --- Determine kept and archived ---
    # Keep up to KEEP_ENTRIES most recent (last in list)
    keep_start = max(0, len(entries) - KEEP_ENTRIES)
    keep_entries = entries[keep_start:]
    archived_entries = entries[:keep_start]

    # If active entry is outside the keep window, prepend it
    if active_idx is not None and active_idx < keep_start:
        keep_entries.insert(0, active_entry)
        # Also remove from archived if it was there
        if active_idx < len(archived_entries):
            archived_entries.remove(active_entry)

    if not archived_entries:
        return StepResult(
            name="rotate_review_queue",
            status="SKIP",
            detail="Fewer entries than KEEP_ENTRIES; nothing to archive",
        )

    # --- Build archive file ---
    archive_dir = project_root / REVIEW_QUEUE_ARCHIVE_DIR_REL
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
        archive_path.write_text("\n".join(archive_lines), encoding="utf-8")
    except OSError as exc:
        return StepResult(
            name="rotate_review_queue",
            status="WARN",
            detail=f"Could not write archive file: {exc}",
        )

    # --- Build truncated review queue ---
    truncated_lines = [header, ""]
    for entry in keep_entries:
        truncated_lines.append("---")
        truncated_lines.append("")
        truncated_lines.append(entry)
        truncated_lines.append("")

    truncated_content = "\n".join(truncated_lines)

    # Check size advisory
    kept_size = len(truncated_content.encode("utf-8"))
    size_warning = kept_size > SIZE_WARN_THRESHOLD

    try:
        review_queue_path.write_text(truncated_content, encoding="utf-8")
    except OSError as exc:
        return StepResult(
            name="rotate_review_queue",
            status="WARN",
            detail=f"Could not write truncated review_queue.md: {exc}",
        )

    detail_parts = [
        f"Archived {len(archived_entries)} entr(es)",
        f"kept {len(keep_entries)} entr(es)",
    ]
    if size_warning:
        detail_parts.append(
            f"WARNING: kept entries exceed {SIZE_WARN_THRESHOLD // 1024} KB"
        )
    status = "WARN" if size_warning else "PASS"

    return StepResult(
        name="rotate_review_queue",
        status=status,
        detail="; ".join(detail_parts),
    )


# ---------------------------------------------------------------------------
# Manager feedback archival
# ---------------------------------------------------------------------------


def _can_prove_close(
    ticket_id: str,
    events: list[dict[str, Any]],
) -> bool:
    """Check if the bus provides unequivocal close/approval for a ticket.

    Before: events is a sorted list of event dicts.
    During: Looks for STATE_CHANGED with to_state in TERMINAL_STATES
            or REVIEW_DECISION with decision=approve for the given ticket.
    After: Returns True if close/approval is proven.
    """
    for ev in events:
        if ev.get("event_type") == "STATE_CHANGED":
            payload = ev.get("payload", {})
            to_state = payload.get("to_state")
            if (to_state in TERMINAL_STATES or to_state == "READY_TO_CLOSE") and ev.get(
                "ticket_id"
            ) == ticket_id:
                return True
        if ev.get("event_type") == "REVIEW_DECISION":
            payload = ev.get("payload", {})
            if (
                payload.get("decision") == "approve"
                and ev.get("ticket_id") == ticket_id
            ):
                return True
    return False


def _find_manager_feedback_files(
    collaboration_dir: Path,
) -> list[Path]:
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


def _extract_ticket_id_from_feedback(filename: str) -> str | None:
    """Extract ticket ID from a manager_feedback filename.

    Before: filename is a string like 'manager_feedback_WP-2026-155.md'.
    During: Uses regex to extract the ticket ID portion.
    After: Returns ticket ID string or None if not matched.
    """
    m = re.search(r"manager_feedback_((?:WP|WT)-\d{4}-\d{3})\.md$", filename)
    if m:
        return m.group(1)
    return None


def _step_archive_manager_feedback(  # noqa: C901 - multiple condition checks
    project_root: Path,
    dry_run: bool,
    events: list[dict[str, Any]],
) -> StepResult:
    """Archive manager_feedback_* files for tickets with proven close/approval.

    Before: events is a sorted list of event dicts from the bus.
    During:
        1. Find all manager_feedback_*.md files in collaboration dir.
        2. For each, extract ticket ID and check bus for close/approval.
        3. If proven, move to archive/manager_feedback/.
        4. If not proven, keep in place.
        5. Skip files that are already in the archive (idempotent).
    After: Returns StepResult with PASS, SKIP, or WARN.
    """
    if dry_run:
        return StepResult(
            name="archive_manager_feedback",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )

    collab_dir = project_root / ".agent" / "collaboration"
    feedback_files = _find_manager_feedback_files(collab_dir)

    if not feedback_files:
        return StepResult(
            name="archive_manager_feedback",
            status="SKIP",
            detail="No manager_feedback files found",
        )

    archive_dir = project_root / MANAGER_FEEDBACK_ARCHIVE_DIR_REL
    archived: list[str] = []
    kept: list[str] = []

    for fb_path in feedback_files:
        ticket_id = _extract_ticket_id_from_feedback(fb_path.name)
        if ticket_id is None:
            kept.append(f"{fb_path.name} (unparseable ticket ID)")
            continue

        if _can_prove_close(ticket_id, events):
            # Archive the file
            try:
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest = archive_dir / fb_path.name
                # Skip if already archived
                if dest.exists():
                    archived.append(f"{fb_path.name} (already archived)")
                    continue
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

    return StepResult(
        name="archive_manager_feedback",
        status=status,
        detail="; ".join(detail_parts),
    )


def _step_manifest_check(project_root: Path) -> StepResult:
    """Verify MANIFEST.distribute exists.

    Before: MANIFEST.distribute may or may not exist at project root.
    During: Checks file existence.
    After: Returns PASS or FAIL.
    """
    manifest_path = project_root / "MANIFEST.distribute"
    if manifest_path.exists():
        return StepResult(
            name="manifest_check",
            status="PASS",
            detail="MANIFEST.distribute exists",
        )
    return StepResult(
        name="manifest_check",
        status="WARN",
        detail="MANIFEST.distribute not found at project root",
    )


def _step_cleanup_builder_session(project_root: Path, dry_run: bool) -> StepResult:
    """Remove builder_session.json if it exists.

    Before: builder_session.json may exist in .agent/runtime/.
    During: Unconditionally removes the file.
    After: builder_session.json no longer exists; ticket context is clean.
    """
    if dry_run:
        return StepResult(
            name="cleanup_builder_session",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    session_path = project_root / ".agent" / "runtime" / "builder_session.json"
    if session_path.exists():
        try:
            session_path.unlink()
            return StepResult(
                name="cleanup_builder_session",
                status="PASS",
                detail="builder_session.json removed",
            )
        except OSError as exc:
            return StepResult(
                name="cleanup_builder_session",
                status="WARN",
                detail=f"Could not remove builder_session.json: {exc}",
            )
    return StepResult(
        name="cleanup_builder_session",
        status="SKIP",
        detail="builder_session.json already absent",
    )


def _step_git_clean(project_root: Path, dry_run: bool) -> StepResult:
    """Verify git status --short is clean (except expected runtime files).

    Before: project_root must be a git repo.
    During: Runs git status --short, filters out expected runtime files.
    After: Returns PASS if clean, WARN if dirty (non-blocking).
    """
    if dry_run:
        return StepResult(
            name="git_clean",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = subprocess.run(
            ["git", "status", "--short"],  # noqa: S607 - git is always on PATH
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return StepResult(
                name="git_clean",
                status="WARN",
                detail=f"git status returned exit {result.returncode}",
            )
        dirty_lines = [
            line for line in result.stdout.strip().splitlines() if line.strip()
        ]
        # Filter out expected runtime files
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
            return StepResult(
                name="git_clean",
                status="PASS",
                detail=f"Tree clean ({len(dirty_lines)} expected runtime file(s) dirty)",
            )
        return StepResult(
            name="git_clean",
            status="WARN",
            detail=f"Tree dirty with {len(unexpected)} unexpected file(s): {unexpected[:3]}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return StepResult(
            name="git_clean",
            status="WARN",
            detail=f"git status could not run: {exc}",
        )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_closeout(
    project_root: Path,
    dry_run: bool = False,
    skip_slow: bool = False,
    explicit_tickets: list[str] | None = None,
) -> int:
    """Run the full session closeout pipeline.

    Before: project_root is the repository root.
    During: Executes all closeout steps in order, collecting results.
    After: Returns exit code (0=success, 1=blocking failure).
    """
    report = CloseoutReport(dry_run=dry_run, skip_slow=skip_slow)

    # --- Step 1: Resolve session window ---
    _window_start, window_src = _resolve_session_window(project_root)
    report.session_start = window_src

    # --- Step 2: Resolve tickets ---
    ticket_ids, ticket_src = _resolve_tickets(project_root, explicit_tickets)
    report.tickets = ticket_ids
    report.steps.append(
        StepResult(
            name="resolve_tickets",
            status="PASS" if ticket_ids else "WARN",
            detail=f"Source: {ticket_src}. Tickets: {ticket_ids or 'none'}",
        )
    )

    # --- Step 3: Prepush check (blocking) ---
    prepush = _step_prepush_check(project_root, dry_run)
    report.steps.append(prepush)
    if prepush.status == "FAIL":
        # Write report and exit early
        _generate_report(report, project_root)
        return 1

    # --- Step 4: Local audit (informational) ---
    report.steps.append(_step_local_audit(project_root, dry_run))

    # --- Step 5: Validate ticket prose (informational) ---
    report.steps.append(_step_validate_ticket_prose(project_root, dry_run))

    # --- Step 6: Session observations (per ticket) ---
    events = _read_events(project_root)
    close_ts = _get_ticket_close_timestamps(events, ticket_ids)

    if not skip_slow:
        obs_results = _step_session_observations(
            ticket_ids, project_root, dry_run, close_ts
        )
        report.steps.extend(obs_results)
    else:
        report.steps.append(
            StepResult(
                name="observations_all",
                status="SKIP",
                detail="Skipped by --skip-slow",
            )
        )

    # --- Step 7: Memory consolidation ---
    if not skip_slow:
        report.steps.append(_step_memory_consolidate(project_root, dry_run))
    else:
        report.steps.append(
            StepResult(
                name="memory_consolidate",
                status="SKIP",
                detail="Skipped by --skip-slow",
            )
        )

    # --- Step 8: Clean up builder session ---
    report.steps.append(_step_cleanup_builder_session(project_root, dry_run))

    # --- Step 9: Archival ---
    report.steps.append(_step_archive_collaboration(project_root, dry_run))

    # --- Step 9b: Review queue rotation (between archive_collaboration and archive_execution_log) ---
    report.steps.append(_step_rotate_review_queue(project_root, dry_run))

    # --- Step 9c: Manager feedback archival ---
    report.steps.append(_step_archive_manager_feedback(project_root, dry_run, events))

    report.steps.append(_step_archive_execution_log(project_root, dry_run))
    report.steps.append(_step_archive_event_bus(project_root, dry_run))

    # --- Step 10: Portability checks ---
    report.steps.append(_step_manifest_check(project_root))
    report.steps.append(_check_portability(project_root))
    report.steps.append(_step_git_clean(project_root, dry_run))

    # --- Generate report ---
    _generate_report(report, project_root)

    # Return code: 0 if overall is PASS or WARN, 1 if FAIL
    return 1 if report.overall_status == "FAIL" else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entry point for session_closeout.py.

    Before: Parses command-line arguments.
    During: Validates project_root exists, then runs closeout pipeline.
    After: Returns exit code from run_closeout().
    """
    parser = argparse.ArgumentParser(
        description="Session Closeout Orchestrator — unified session close pipeline",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (default: cwd)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Generate report without executing destructive steps",
    )
    parser.add_argument(
        "--skip-slow",
        action="store_true",
        default=False,
        help="Skip memory consolidation and observation generation",
    )
    parser.add_argument(
        "--ticket",
        type=str,
        default=None,
        help="Explicit ticket ID to audit (e.g., WT-2026-168)",
    )
    parser.add_argument(
        "--tickets",
        type=str,
        default=None,
        help="Comma-separated ticket IDs to audit (e.g., WT-2026-168,WT-2026-167)",
    )

    args = parser.parse_args()

    project_root = args.project_root or Path.cwd()
    project_root = project_root.resolve()

    if not project_root.exists():
        print(f"ERROR: project root does not exist: {project_root}", file=sys.stderr)
        return 1

    # Build explicit tickets list
    explicit_tickets: list[str] | None = None
    if args.ticket:
        explicit_tickets = [args.ticket]
    elif args.tickets:
        explicit_tickets = [t.strip() for t in args.tickets.split(",") if t.strip()]

    return run_closeout(
        project_root=project_root,
        dry_run=args.dry_run,
        skip_slow=args.skip_slow,
        explicit_tickets=explicit_tickets,
    )


if __name__ == "__main__":
    sys.exit(main())
