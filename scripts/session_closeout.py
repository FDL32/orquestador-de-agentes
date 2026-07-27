#!/usr/bin/env python3
"""Session Closeout Orchestrator - unified session close pipeline.

Before (Pre-condiciones):
    - El repositorio debe existir con la estructura .agent/ canA3nica.
    - `events.jsonl` debe existir en `.agent/runtime/events/` (puede estar vacAo).
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
    - En `--dry-run` genera el preview en `.agent/runtime/tmp/` sin tocar el
      reporte durable.

After (Post-condiciones y Errores):
    - Exit code 0 si el cierre completo pasa (prepush_check OK + sin errores fatales).
    - Exit code 1 si prepush_check falla o hay errores fatales en pasos bloqueantes.
    - El reporte durable se escribe solo en el cierre real.
    - `git status --short` queda limpio tras `--dry-run`.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# absolute path while cwd points at repo_destino.
_MOTOR_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_BOOTSTRAP))

# Constants
from bus.state_machine import terminal_state_strings  # noqa: E402
from bus.ticket_id import TICKET_ID_PATTERN  # noqa: E402
from scripts.closeout_steps.archival import (  # noqa: E402
    _can_prove_close as _archival_can_prove_close,
    step_archive_collaboration as _step_archive_collaboration_impl,
    step_archive_event_bus as _step_archive_event_bus_impl,
    step_archive_execution_log as _step_archive_execution_log_impl,
    step_archive_manager_feedback as _step_archive_manager_feedback_impl,
)
from scripts.closeout_steps.gates import (  # noqa: E402
    step_local_audit as _step_local_audit_impl,
    step_manifest_check as _step_manifest_check_impl,
    step_prepush_check as _step_prepush_check_impl,
    step_validate_ticket_prose as _step_validate_ticket_prose_impl,
)
from scripts.closeout_steps.observations import (  # noqa: E402
    step_memory_consolidate as _step_memory_consolidate_impl,
    step_session_observations as _step_session_observations_impl,
    step_upstream_learnings_ttl as _step_upstream_learnings_ttl_impl,
)
from scripts.closeout_steps.rotation import (  # noqa: E402
    is_lock_alive as _rotation_is_lock_alive,
    parse_review_queue as _rotation_parse_review_queue,
    step_cleanup_builder_session as _step_cleanup_builder_session_impl,
    step_git_clean as _step_git_clean_impl,
    step_rotate_review_queue as _step_rotate_review_queue_impl,
)
from scripts.closeout_steps.support import (  # noqa: E402
    check_portability as _check_portability_impl,
    check_versioned_filenames as _check_versioned_filenames_impl,
    find_last_report_timestamp as _find_last_report_timestamp_impl,
    generate_report as _generate_report_impl,
    get_ticket_close_timestamps as _get_ticket_close_timestamps_impl,
    parse_timestamp as _parse_timestamp_impl,
    process_diagnostic as _process_diagnostic_impl,
    read_events as _read_events_impl,
    run_script as _run_script_impl,
)
from scripts.manager_feedback_helpers import (  # noqa: E402
    extract_ticket_id_from_feedback as _canonical_extract_ticket_id_from_feedback,
    find_manager_feedback_files as _canonical_find_manager_feedback_files,
)


# WOT-2026-013n: align with shared terminality authority + HUMAN_GATE (close ts).
TERMINAL_STATES = set(terminal_state_strings()) | {"HUMAN_GATE"}

BUILDER_LOCK_REL = Path(".agent") / "runtime" / "builder_lock.txt"
SUPERVISOR_LOCK_REL = Path(".agent") / "runtime" / "supervisor_lock.txt"

REVIEW_QUEUE_REL = Path(".agent") / "collaboration" / "review_queue.md"
REVIEW_QUEUE_ARCHIVE_DIR_REL = Path(".agent") / "collaboration" / "archive"

MANAGER_FEEDBACK_ARCHIVE_DIR_REL = (
    Path(".agent") / "collaboration" / "archive" / "manager_feedback"
)

KEEP_ENTRIES = 10
SIZE_WARN_THRESHOLD = 50 * 1024  # 50 KB advisory threshold

LOCK_TTL_MINUTES = 15

PORTABILITY_SCAN_DIRS = ("docs", "markdowns", "skills", ".agent/rules")

PORTABILITY_SCAN_EXTRA = ("README.md", "PROJECT.md")

PORTABILITY_SCAN_GLOBS = ("*.py", "*.ps1", "*.md", "MANIFEST*")

REPORT_REL = Path(".agent") / "runtime" / "memory" / "session_close_report.md"
DRY_RUN_REPORT_REL = Path(".agent") / "runtime" / "tmp" / "session_close_report.md"

EVENTS_REL = Path(".agent") / "runtime" / "events" / "events.jsonl"

WORK_PLAN_REL = Path(".agent") / "collaboration" / "work_plan.md"

SCRIPTS_DIR = "scripts"

TICKET_RE = re.compile(TICKET_ID_PATTERN)

TICKET_ID_FILENAME_RE = re.compile(r"(?i)(?:[A-Z]{2,3}|PLAN)[_-]\d{4}[_-]\d{3}[a-z]?")


@dataclass
class StepResult:
    """Result of a single closeout step."""

    name: str
    # NOT_VERIFIED (WOT-2026-040y): the step did not run, so its outcome is
    # unknown. Distinct from SKIP, which means "deliberately not applicable".
    status: str  # PASS, WARN, FAIL, SKIP, NOT_VERIFIED
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
        """Overall status, honoring each step's ``blocking`` flag (WOT-2026-013m).

        FAIL only if a step that FAILED is ``blocking=True``. A FAILED step that
        is ``blocking=False`` (e.g. ``versioned_filenames``) is informative and
        degrades to WARN, not FAIL: it must not force ``--session-close`` to
        exit 1 when no genuinely blocking gate failed. Before 013m this returned
        FAIL on ANY FAIL regardless of the flag, contradicting this docstring and
        blocking sessions on non-blocking findings.

        WOT-2026-040y: a blocking step reporting ``NOT_VERIFIED`` never ran, so
        this can never return PASS -- absence of evidence is not evidence of
        health. It degrades to WARN rather than FAIL: nothing failed, we simply
        do not know, and calling that FAIL would be its own false signal.
        """
        if any(s.status == "FAIL" and s.blocking for s in self.steps):
            return "FAIL"
        statuses = [s.status for s in self.steps]
        if "FAIL" in statuses or "WARN" in statuses:
            return "WARN"
        if any(s.status == "NOT_VERIFIED" and s.blocking for s in self.steps):
            return "WARN"
        return "PASS"


def _run_script(
    script_name: str,
    args: list[str],
    project_root: Path,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run a script from the scripts/ directory relative to project_root."""
    return _run_script_impl(
        script_name,
        args,
        project_root,
        scripts_dir=SCRIPTS_DIR,
        timeout=timeout,
    )


def _process_diagnostic(
    result: subprocess.CompletedProcess[str],
    *,
    limit: int = 500,
) -> str:
    """Return actionable subprocess output, preferring stdout then stderr."""
    return _process_diagnostic_impl(result, limit=limit)


def _read_events(project_root: Path) -> list[dict[str, Any]]:
    """Read all events from events.jsonl."""
    return _read_events_impl(project_root, events_rel=EVENTS_REL)


def _find_last_report_timestamp(project_root: Path) -> str | None:
    """Find the timestamp from the most recent session_close_report.md."""
    return _find_last_report_timestamp_impl(project_root, report_rel=REPORT_REL)


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Parse an ISO-ish timestamp string to datetime."""
    return _parse_timestamp_impl(ts_str)


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
    During: Searches for the canonical '- **ID:** WOT-YYYY-NNNx' pattern
            (legacy WP-/WT- still accepted).
    After: Returns ticket ID string or None.
    """
    wp_path = project_root / WORK_PLAN_REL
    if not wp_path.exists():
        return None
    try:
        content = wp_path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"-?\s*\*\*ID:\*\*\s*(" + TICKET_ID_PATTERN + r")", content)
    if m:
        return m.group(1)
    return None


def _ticket_is_terminal(events: list[dict[str, Any]], ticket_id: str) -> bool:
    """Report whether the bus already recorded ``ticket_id`` as closed.

    WOT-2026-040e. Reuses the canonical close-timestamp scan rather than
    re-deriving "what counts as terminal": that set lives in one place
    (``TERMINAL_STATES``) and a second opinion about it is how the two views
    drift apart.

    Before: ``events`` is the parsed bus (possibly empty); ``ticket_id`` is a
        ticket string.
    During: Pure scan, no I/O.
    After: True when a STATE_CHANGED event moved that ticket into a terminal
        state. Never raises.
    """
    return bool(_get_ticket_close_timestamps(events, [ticket_id]))


def _ticket_is_archived_in_backlog(project_root: Path, ticket_id: str) -> bool:
    """True si ``_archive/backlog_done.md`` ya registra ``ticket_id`` como cerrado.

    WOT-2026-042f. Segunda fuente de evidencia junto al bus, no sustituta: el bus
    puede no haber visto NUNCA un ticket (vuelo en worktree que no escribe estado,
    o eventos ya archivados), y el historico del backlog es la superficie que el
    humano cierra a mano.

    Before: `project_root` es el `repo_destino`; `ticket_id` un id de ticket.
    During: delega el parseo en `check_backlog_contract._ticket_has_row`, que es
        LAYOUT-ROBUSTO (WOT-2026-023o: el id vive en cell[0] en el archive y en
        cell[1] en el backlog vivo, y el archive tiene dos secciones distintas).
        Reimplementar el parseo aqui seria un SEGUNDO lector del mismo dato --
        exactamente el defecto que WOT-2026-042a acaba de corregir en el
        controlador.
    After: retorna bool. Si el modulo no es importable o el fichero no existe,
        retorna False (fail-OPEN: sin evidencia NO se afirma cierre, y el guard
        del bus sigue corriendo detras).
    """
    try:
        # `scripts/` no esta en sys.path bajo pytest (el modulo solo inyecta
        # _MOTOR_ROOT), asi que se importa por su paquete completo. Medido: el
        # `from check_backlog_contract import ...` a secas funciona en CLI y
        # falla en la suite -- un fail-open silencioso que dejaba el guard inerte.
        from scripts.check_backlog_contract import _ticket_has_row
    except ImportError:
        return False

    archive = project_root / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
    return _ticket_has_row(ticket_id, archive)


def _resolve_tickets(
    project_root: Path,
    explicit_tickets: list[str] | None,
) -> tuple[list[str], str]:
    """Resolve tickets to audit using the priority chain.

    Before: project_root is valid, explicit_tickets may be None/empty.
    During: Priority: explicit CLI > detected in window > active from work_plan.
        The work_plan fallback is guarded (WOT-2026-040e): if the bus already
        recorded that ticket in a terminal state, work_plan.md is stale and the
        ticket belongs to an earlier session, so it is refused rather than
        certified.
    After: Returns (ticket_list, source_description). An empty list with a
        "stale" source means the caller must not treat the close as scoped.
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
        # WOT-2026-042f: el BACKLOG tambien es evidencia. El guard de abajo
        # (040e) solo pregunta al BUS, y en la TERCERA ocurrencia del mismo
        # incidente (medida 2026-07-27) el bus no tenia UN SOLO evento de
        # WOT-2026-026k -- ni vivo ni archivado -- asi que respondia "no
        # terminal" y el fallback certificaba un ticket cerrado el 21-jul.
        # Reconciliar el bus NO lo arreglo: la fuente que SI lo sabia era
        # `_archive/backlog_done.md`. Se consulta ANTES del bus porque es la
        # superficie que el humano cierra a mano y la que sobrevive al
        # archivado de eventos.
        if _ticket_is_archived_in_backlog(project_root, active):
            return [], (
                f"stale work_plan.md: it points at {active}, which "
                "_archive/backlog_done.md already records as closed. This "
                "session produced no events of its own, so there is nothing to "
                "certify. Pass --ticket explicitly if you know what this "
                "session closed."
            )
        # WOT-2026-040e: measured twice (2026-07-23, 2026-07-25), both times
        # resolving to the same already-closed WOT-2026-026k. A flight ran in a
        # worktree without writing state, the window came up empty, and the
        # closeout certified seventeen green steps for another session's ticket.
        # Trusting work_plan.md is the bug; the bus is the evidence.
        if _ticket_is_terminal(events, active):
            return [], (
                f"stale work_plan.md: it points at {active}, which the event bus "
                "already recorded as closed. This session produced no events of "
                "its own, so there is nothing to certify. Pass --ticket "
                "explicitly if you know what this session closed."
            )
        return [active], "fallback from work_plan.md active ticket"

    return [], "no tickets found"


def _get_ticket_close_timestamps(
    events: list[dict[str, Any]],
    ticket_ids: list[str],
) -> dict[str, str]:
    """Get the close timestamp for each ticket from terminal state changes."""
    return _get_ticket_close_timestamps_impl(
        events,
        ticket_ids,
        terminal_states=TERMINAL_STATES,
    )


def _check_portability(project_root: Path) -> StepResult:
    """Check for absolute workspace paths in portable files."""
    return _check_portability_impl(
        project_root,
        portability_scan_dirs=PORTABILITY_SCAN_DIRS,
        portability_scan_extra=PORTABILITY_SCAN_EXTRA,
        portability_scan_globs=PORTABILITY_SCAN_GLOBS,
        step_result_cls=StepResult,
    )


def _check_versioned_filenames(motor_root: Path) -> StepResult:
    """Check versioned filenames for embedded ticket IDs."""
    return _check_versioned_filenames_impl(
        motor_root,
        subprocess_run=subprocess.run,
        step_result_cls=StepResult,
        ticket_id_filename_re=TICKET_ID_FILENAME_RE,
    )


def _generate_report(report: CloseoutReport, project_root: Path) -> Path:
    """Generate the session close report markdown file."""
    return _generate_report_impl(
        report,
        project_root,
        dry_run_report_rel=DRY_RUN_REPORT_REL,
        report_rel=REPORT_REL,
    )


def _step_prepush_check(
    project_root: Path, dry_run: bool, skip_gates: bool = False
) -> StepResult:
    """Run prepush_check.py as the blocking quality gate."""
    return _step_prepush_check_impl(
        project_root,
        dry_run,
        run_script_fn=_run_script,
        process_diagnostic_fn=_process_diagnostic,
        step_result_cls=StepResult,
        skip_gates=skip_gates,
    )


def _step_local_audit(project_root: Path, dry_run: bool) -> StepResult:
    """Run local_audit.py as an informational snapshot."""
    return _step_local_audit_impl(
        project_root,
        dry_run,
        run_script_fn=_run_script,
        step_result_cls=StepResult,
    )


def _step_validate_ticket_prose(project_root: Path, dry_run: bool) -> StepResult:
    """Run validate_ticket_prose.py --json as an informational check."""
    return _step_validate_ticket_prose_impl(
        project_root,
        dry_run,
        run_script_fn=_run_script,
        step_result_cls=StepResult,
    )


def _step_session_observations(
    ticket_ids: list[str],
    project_root: Path,
    dry_run: bool,
    close_timestamps: dict[str, str],
) -> list[StepResult]:
    """Run session_close_observations.py once per resolved ticket."""
    return _step_session_observations_impl(
        project_root,
        dry_run,
        ticket_ids=ticket_ids,
        close_timestamps=close_timestamps,
        run_script_fn=_run_script,
        process_diagnostic_fn=_process_diagnostic,
        step_result_cls=StepResult,
    )


def _step_memory_consolidate(project_root: Path, dry_run: bool) -> StepResult:
    """Run memory_consolidate.py --verbose --apply."""
    return _step_memory_consolidate_impl(
        project_root,
        dry_run,
        run_script_fn=_run_script,
        process_diagnostic_fn=_process_diagnostic,
        step_result_cls=StepResult,
    )


def _step_archive_collaboration(project_root: Path, dry_run: bool) -> StepResult:
    """Run archive_collaboration_artifacts.py."""
    return _step_archive_collaboration_impl(
        project_root,
        dry_run,
        run_script_fn=_run_script,
        step_result_cls=StepResult,
    )


def _step_archive_execution_log(project_root: Path, dry_run: bool) -> StepResult:
    """Run archive_execution_log.py."""
    return _step_archive_execution_log_impl(
        project_root,
        dry_run,
        run_script_fn=_run_script,
        step_result_cls=StepResult,
    )


def _step_archive_event_bus(project_root: Path, dry_run: bool) -> StepResult:
    """Run archive_event_bus.py --all-terminal."""
    return _step_archive_event_bus_impl(
        project_root,
        dry_run,
        run_script_fn=_run_script,
        step_result_cls=StepResult,
    )


def _is_lock_alive(lock_path: Path) -> bool:
    """Check if a lock file is alive based on TTL and mtime."""
    return _rotation_is_lock_alive(
        lock_path,
        lock_ttl_minutes=LOCK_TTL_MINUTES,
    )


def _parse_review_queue(content: str) -> tuple[str, list[str], str | None]:
    """Parse review_queue.md into header, entries, and active ticket entry."""
    return _rotation_parse_review_queue(content)


def _step_rotate_review_queue(project_root: Path, dry_run: bool) -> StepResult:
    """Rotate review_queue.md: archive old entries, keep header + active + recent."""
    return _step_rotate_review_queue_impl(
        project_root,
        dry_run,
        builder_lock_rel=BUILDER_LOCK_REL,
        keep_entries=KEEP_ENTRIES,
        lock_ttl_minutes=LOCK_TTL_MINUTES,
        resolve_active_ticket_fn=_resolve_active_ticket,
        review_queue_archive_dir_rel=REVIEW_QUEUE_ARCHIVE_DIR_REL,
        review_queue_rel=REVIEW_QUEUE_REL,
        size_warn_threshold=SIZE_WARN_THRESHOLD,
        step_result_cls=StepResult,
        supervisor_lock_rel=SUPERVISOR_LOCK_REL,
    )


def _can_prove_close(
    ticket_id: str,
    events: list[dict[str, Any]],
) -> bool:
    """Compatibility wrapper for manager feedback archival tests/helpers."""
    return _archival_can_prove_close(ticket_id, events)


def _find_manager_feedback_files(collaboration_dir: Path) -> list[Path]:
    """Compatibility wrapper for manager feedback file discovery."""
    return _canonical_find_manager_feedback_files(collaboration_dir)


def _extract_ticket_id_from_feedback(filename: str) -> str | None:
    """Compatibility wrapper for manager feedback ticket parsing."""
    return _canonical_extract_ticket_id_from_feedback(
        filename,
        ticket_id_pattern=TICKET_ID_PATTERN,
    )


def _step_archive_manager_feedback(
    project_root: Path,
    dry_run: bool,
    events: list[dict[str, Any]],
) -> StepResult:
    """Archive manager_feedback_* files for tickets with proven close/approval."""
    return _step_archive_manager_feedback_impl(
        project_root,
        dry_run,
        events=events,
        manager_feedback_archive_dir_rel=MANAGER_FEEDBACK_ARCHIVE_DIR_REL,
        ticket_id_pattern=TICKET_ID_PATTERN,
        step_result_cls=StepResult,
    )


def _step_manifest_check(project_root: Path) -> StepResult:
    """Verify MANIFEST.distribute exists."""
    return _step_manifest_check_impl(
        project_root,
        False,
        step_result_cls=StepResult,
    )


def _step_cleanup_builder_session(project_root: Path, dry_run: bool) -> StepResult:
    """Remove builder_session.json if it exists."""
    return _step_cleanup_builder_session_impl(
        project_root,
        dry_run,
        step_result_cls=StepResult,
    )


def _step_git_clean(project_root: Path, dry_run: bool) -> StepResult:
    """Verify git status --short is clean (except expected runtime files)."""
    return _step_git_clean_impl(
        project_root,
        dry_run,
        subprocess_run=subprocess.run,
        step_result_cls=StepResult,
    )


def run_closeout(
    project_root: Path,
    dry_run: bool = False,
    skip_slow: bool = False,
    explicit_tickets: list[str] | None = None,
    skip_gates: bool = False,
) -> int:
    """Run the full session closeout pipeline.

    Before: project_root is the repository root.
    During: Executes all closeout steps in order, collecting results.
    After: Returns exit code (0=success, 1=blocking failure).

    WOT-2026-020i: skip_gates forwards --skip-gates to prepush_check so a
    blocking prepush failure no longer aborts the close (operator chose to close
    over pre-existing debt). Default False preserves blocking behavior.
    """
    report = CloseoutReport(dry_run=dry_run, skip_slow=skip_slow)
    _window_start, window_src = _resolve_session_window(project_root)
    report.session_start = window_src
    ticket_ids, ticket_src = _resolve_tickets(project_root, explicit_tickets)
    report.tickets = ticket_ids
    report.steps.append(
        StepResult(
            name="resolve_tickets",
            status="PASS" if ticket_ids else "WARN",
            detail=f"Source: {ticket_src}. Tickets: {ticket_ids or 'none'}",
        )
    )
    prepush = _step_prepush_check(project_root, dry_run, skip_gates=skip_gates)
    report.steps.append(prepush)
    if prepush.status == "FAIL":
        # Write report and exit early. Announce the report path to stderr (the
        # success path below prints the same to stdout): without this, a caller
        # like `agent_controller.py --session-close` sees exit 1 with NO console
        # output and cannot find where the failure detail was written.
        report_path = _generate_report(report, project_root)
        print(f"[closeout] Report (FAIL): {report_path}", file=sys.stderr)
        return 1
    report.steps.append(_step_local_audit(project_root, dry_run))
    report.steps.append(_step_validate_ticket_prose(project_root, dry_run))
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
    report.steps.append(
        _step_upstream_learnings_ttl_impl(project_root, step_result_cls=StepResult)
    )
    report.steps.append(_step_cleanup_builder_session(project_root, dry_run))
    report.steps.append(_step_archive_collaboration(project_root, dry_run))
    report.steps.append(_step_rotate_review_queue(project_root, dry_run))
    report.steps.append(_step_archive_manager_feedback(project_root, dry_run, events))

    report.steps.append(_step_archive_execution_log(project_root, dry_run))
    report.steps.append(_step_archive_event_bus(project_root, dry_run))
    report.steps.append(_step_manifest_check(project_root))
    report.steps.append(_check_portability(project_root))
    try:
        from runtime.motor_link import resolve_motor_root

        motor_root = resolve_motor_root(project_root)
        if motor_root is not None:
            report.steps.append(_check_versioned_filenames(motor_root))
        else:
            report.steps.append(
                StepResult(
                    name="versioned_filenames",
                    status="SKIP",
                    detail="motor_root not resolvable; check skipped",
                )
            )
    except ImportError:
        report.steps.append(
            StepResult(
                name="versioned_filenames",
                status="SKIP",
                detail="runtime.motor_link not available; check skipped",
            )
        )
    report.steps.append(_step_git_clean(project_root, dry_run))

    # --- Generate report ---
    report_path = _generate_report(report, project_root)
    # Dry-run writes to runtime/tmp/ (non-mutating, 7d28d2e); print the path
    # so operators and reviewers do not look at the stale canonical report.
    print(f"[closeout] Report ({report.overall_status}): {report_path}")

    # Return code: 0 if overall is PASS or WARN, 1 if FAIL
    return 1 if report.overall_status == "FAIL" else 0


def main() -> int:
    """CLI entry point for session_closeout.py.

    Before: Parses command-line arguments.
    During: Validates project_root exists, then runs closeout pipeline.
    After: Returns exit code from run_closeout().
    """
    parser = argparse.ArgumentParser(
        description="Session Closeout Orchestrator - unified session close pipeline",
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
        help="Explicit ticket ID to audit (e.g., WOT-2026-010a)",
    )
    parser.add_argument(
        "--tickets",
        type=str,
        default=None,
        help="Comma-separated ticket IDs to audit (e.g., WOT-2026-010a,WOT-2026-009g)",
    )
    parser.add_argument(
        "--skip-gates",
        action="store_true",
        default=False,
        help=(
            "WOT-2026-020i: forward --skip-gates to prepush_check so a blocking "
            "prepush failure does not abort the close (close over pre-existing debt)."
        ),
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
        skip_gates=args.skip_gates,
    )


if __name__ == "__main__":
    sys.exit(main())
