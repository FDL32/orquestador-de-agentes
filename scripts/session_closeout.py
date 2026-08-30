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

LOOP_EXECUTION_TARGETS_REL = (
    Path(".agent") / "collaboration" / "loop_execution_targets.txt"
)

BACKLOG_REL = Path(".agent") / "collaboration" / "backlog.md"
BACKLOG_ARCHIVE_REL = Path(".agent") / "collaboration" / "_archive" / "backlog_done.md"

DELIVERABLE_TYPE_RE = re.compile(r"deliverable_type:\s*([^\s|]+)")

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


def _productive_commits_and_ids(
    root: Path,
    window_start: datetime | None,
) -> tuple[bool, list[str]]:
    """Productive commits of ONE repo after window_start + the ticket ids named.

    WOT-2026-040e (per-repo split wired by WOT-2026-061c): the single-root body
    of `_has_productive_commits`. Before 061c the two-repo loop and the ID
    harvest lived inline, so a per-root consumer had to duplicate the scan --
    duplication that is exactly how a harvest and the BUS-VACIO gate drift
    apart. Both now share this one.

    Before: `root` is a git working tree; window_start may be None.
    During: one read-only ``git log --oneline --since=<window_start>`` in `root`;
        ids extracted with the canonical TICKET_RE from each subject (inclusive:
        every ticket MENTIONED, per 058j).
    After: returns (found, [ids]); (False, []) on git failure or empty output.
    """
    since_args: list[str] = []
    if window_start is not None:
        since_args = [f"--since={window_start.strftime('%Y-%m-%dT%H:%M:%S')}"]

    try:
        result = subprocess.run(  # noqa: S603
            ["git", "log", "--oneline", *since_args],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False, []
    if result.returncode != 0 or not result.stdout.strip():
        return False, []
    ids: list[str] = []
    for line in result.stdout.splitlines():
        for match in TICKET_RE.findall(line):
            if match not in ids:
                ids.append(match)
    return True, ids


def _has_productive_commits(
    project_root: Path,
    motor_root: Path,
    window_start: datetime | None,
) -> tuple[bool, list[str]]:
    """Check for productive commits in either repo after window_start.

    WOT-2026-040e. Detects the 'BUS VACIO' scenario: commits exist but the
    event bus has 0 events for them. Used to distinguish a maintenance session
    (no commits, no events -> legitimate) from a session with productive work
    that failed to emit events (commits exist, 0 events -> blocking).

    WOT-2026-058j. Returns ``(has_commits, ticket_ids)`` instead of a bare
    bool: the SAME ``git log`` invocation now also harvests the ticket IDs
    named in the commit subjects. The closeout emits a bus signal for them
    (see ``_emit_session_close_recorded``); without a harvest the signal has no
    ticket_id exactly in the case that fails. The harvest is deliberately
    inclusive -- every ticket MENTIONED in a window subject, not only "closed"
    ones: an extra id certifies nothing false, a missing id reproduces the
    refusal.

    WOT-2026-061c: the per-repo scan moved to `_productive_commits_and_ids`;
    this function keeps its exact merge semantics (either repo -> found; ids
    deduplicated motor-first) and is now a thin two-root aggregation of the
    shared helper.

    Before: motor_root is resolvable, window_start may be None.
    During: Runs ``git log --oneline --since=<window_start>`` in both motor
        and destino repos, counting matching commits and extracting IDs from
        their subjects with the canonical TICKET_ID_PATTERN.
    After: Returns (True, [ids]) when at least one commit exists in either
        repo (ids possibly empty when no subject names a ticket), or
        (False, []) when neither repo produced a commit or git failed in both.
    """
    found = False
    seen: dict[str, None] = {}
    for root in (motor_root, project_root):
        root_found, root_ids = _productive_commits_and_ids(root, window_start)
        if root_found:
            found = True
        for match in root_ids:
            if match not in seen:
                seen[match] = None
    return found, list(seen.keys())


def _check_bus_vacio(project_root: Path, window_start: datetime | None) -> str:
    """Check for BUS VACIO: productive commits but 0 events.

    WOT-2026-040e. Returns 'FAIL' if commits exist but the bus has no events
    (productive work not certified), 'WARN' if no commits exist (maintenance
    session, legitimate).
    """
    try:
        from runtime.motor_link import resolve_motor_root as _rmr

        mr = _rmr(project_root)
        if mr is not None:
            has_commits, _harvested = _has_productive_commits(
                project_root, mr, window_start
            )
            if has_commits:
                return "FAIL"
    except ImportError:
        pass
    return "WARN"


def _execution_log_frozen(project_root: Path, window_start: datetime | None) -> str:
    """Segunda superficie de proyeccion congelada (WOT-2026-040e ampliado).

    El BUS VACIO no es la unica superficie que se congela: `execution_log.md`
    del destino puede quedar anclado a un vuelo anterior mientras el bus pesa
    0 bytes y la cola avanza. Medido 2026-08-07: aqui estaba congelado en
    `WOT-2026-041c` (mtime 2026-07-30) con 18 tickets archivados despues.

    Before: project_root es el destino; window_start puede ser None.
    During: lee `execution_log.md`; extrae el vuelo (`# Execution Log -- VUELO
    <X>`) y la fecha; considera congelado si el archivo existe y su mtime es
    ANTERIOR a `window_start` (un log que no registro esta sesion no puede
    sostener el cierre de esta sesion).
    After: devuelve un string de detalle (vacio si no hay congelamiento
    medible). NUNCA cambia el veredicto del BUS VACIO: amplia el diagnostico,
    no la politica.
    """
    elog = project_root / ".agent" / "collaboration" / "execution_log.md"
    if not elog.exists():
        return ""
    try:
        mtime = datetime.fromtimestamp(elog.stat().st_mtime)
        content = elog.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    vuelo = ""
    m = re.search(r"VUELO\s+([A-Za-z0-9_\-]+)", content)
    if m:
        vuelo = m.group(1)
    # Sin ventana no hay base para atribuir el log a esta sesion: un log con
    # vuelo nuevo y mtime reciente es legítimo (anti-falso-positivo). La senal
    # fiable de congelamiento es temporal (mtime anterior a la ventana), que
    # es exactamente el caso medido (mtime 2026-07-30 con 18 tickets despues).
    if window_start is None:
        return ""
    mtime_aware = mtime.astimezone()
    if mtime_aware >= window_start.astimezone():
        return ""
    detail = (
        f"execution_log.md congelado (mtime {mtime.isoformat(timespec='seconds')}"
        f" anterior a la ventana"
    )
    if vuelo:
        detail += f", vuelo '{vuelo}'"
    return detail + ")"


def _resolve_tickets_detail(
    ticket_src: str,
    ticket_ids: list[str],
    *,
    status: str,
    stale: bool,
    project_root: Path,
    window_start: datetime | None,
) -> str:
    """Detalle del paso resolve_tickets, con la ampliacion 040e.

    Before: veredicto (status/stale) y tickets ya resueltos.
    During: compone la cadena base (source + tickets) y, cuando el paso cae en
    BUS VACIO (FAIL sin rechazo stale), anexa la medicion de la SEGUNDA
    superficie de proyeccion (`execution_log.md` congelado). No cambia el
    veredicto: solo lo documenta (WOT-2026-040e ampliado).
    After: cadena de detalle final para el StepResult.
    """
    detail = f"Source: {ticket_src}. Tickets: {ticket_ids or 'none'}"
    if status == "FAIL" and not stale:
        frozen = _execution_log_frozen(project_root, window_start)
        if frozen:
            detail += f" {frozen}"
    return detail


def _step_write_decision_records(project_root: Path, ticket_ids: list[str]) -> None:
    """Write and commit decision records for tickets without commits.

    WOT-2026-040w. Wires write_decision_record (check_handoff_committed.py)
    into the closeout flow. When a flight stops without producing code, the
    closeout writes a decision record and commits it so the handoff committed
    check (prepush) finds a commit and passes.

    The commit query is PER TICKET (``git log --all --grep=<ticket_id>``, via
    ``_signal_commits``), not per repo. A repo-wide query is True in any repo
    with history, so it made this step inert: the ``continue`` always fired and
    ``write_decision_record`` was never reached. It also matches the predicate
    of the barrier this step unblocks -- ``assert_ticket_commit_visible``
    (pre_handoff_guard) looks for the ticket_id in commit subjects, so both
    sides of the contract now ask the same question.

    PROXY BIAS, MEASURED AND DECLARED: ``_signal_commits`` greps the whole
    commit MESSAGE while the barrier greps only the SUBJECT, so a commit that
    merely mentions the ticket in its body counts as landed here. Measured
    2026-08-13 over the three G1 tickets: identical verdicts by both routes;
    the only divergence was one commit naming WOT-2026-040e in its body. The
    bias therefore points at SKIP -- it can see commits that are not there,
    never miss ones that are. That is the conservative direction: a false SKIP
    omits a record, a false WRITE would commit a spurious one. The previous
    repo-wide query had this same bias at its maximum (SKIP always).

    Before: ticket_ids is non-empty, project_root is a git working tree.
    During: For each ticket, searches motor and destino for a commit naming it.
        If none exists, writes a decision record via write_decision_record and
        commits it. An unresolvable motor narrows the search to destino rather
        than skipping the check (which would write blindly).
    After: The working tree has decision records committed for stopped tickets.
    """
    try:
        from scripts.check_handoff_committed import write_decision_record
    except ImportError:
        return

    try:
        from runtime.motor_link import resolve_motor_root as _rmr

        mr = _rmr(project_root)
    except ImportError:
        mr = None

    try:
        from scripts.backlog_reconcile import _signal_commits
    except ImportError:
        return

    repos = [r for r in (mr, project_root) if r is not None]

    for ticket_id in ticket_ids:
        if any(_signal_commits(ticket_id, repo) for repo in repos):
            continue
        try:
            write_decision_record(
                worktree=project_root,
                ticket=ticket_id,
                state="STOPPED",
                cause_type="UNCLASSIFIED",
                summary="Flight stopped without code commits (session closeout)",
                evidence=["closeout: no commits found for resolved ticket"],
            )
            subprocess.run(  # noqa: S603
                ["git", "add", "--", f".flight-decision/{ticket_id}.json"],  # noqa: S607
                cwd=project_root,
                capture_output=True,
                timeout=30,
            )
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "git",
                    "commit",
                    "-m",
                    f"{ticket_id}: decision record (flight stopped)",
                ],
                cwd=project_root,
                capture_output=True,
                timeout=30,
            )
        except Exception:  # noqa: S110
            pass


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


STALE_WORK_PLAN_MARKER = "stale work_plan.md"
"""Prefijo del `source` cuando `_resolve_tickets` RECHAZO certificar.

WOT-2026-040e. Existe para que productor y consumidor compartan UN token en
vez de que el llamante re-escriba la prosa: una lista vacia tiene DOS
significados y solo uno debe bloquear el cierre.

  - `no tickets found`  -> sesion de mantenimiento legitima: no habia nada que
    certificar. NO bloquea (DoD (d), anti-falso-positivo).
  - `stale work_plan.md: ...` -> el guard se NEGO a certificar un ticket ajeno.
    Bloquea: un rechazo degradado a WARN sale con exit 0 y certifica CERO
    mientras la sesion entrega commits (medido 2026-08-06, cierre de
    WOT-2026-049c: `CLOSE_EXIT=0` con 7 commits sin certificar).
"""

CERTIFIED_BY_ARCHIVED_COMMIT_SRC = "certified by archived landed commit"
"""Source del paso `resolve_tickets` cuando certify_tickets_by_landed_commits
resolvio por la via de commits-de-la-ventana respaldados por fila archivada
aterrizada (WOT-2026-061c, modo dogfooding de commit directo: bus vacio por
diseno, H-C1)."""

_CERTIFIABLE_VERDICTS = ("OK", "OK_BY_SUBJECT")
"""Unicamente estos veredictos del guard de aterrizaje certifican cierre.
PENDING_GROUPED_PUSH / WARN / ERROR NO: son las mismas reglas canonicas que
aplica `agent_controller._ticket_landed_by_archived_commit` (WOT-2026-024q);
una segunda opinion sobre "que cuenta como aterrizado" es como dos lectores
driftian."""


def _harvest_window_commits_by_root(
    project_root: Path,
    motor_root: Path | None,
    window_start: datetime | None,
) -> tuple[dict[str, list[str]], dict[str, str], list[str]]:
    """Harvest productive commits PER ROOT: ids per root, origin map, order.

    WOT-2026-061c. `_has_productive_commits` merges both repos into one verdict;
    certification needs the origin of each candidate to resolve the audit root
    POR ORIGEN DE LA FILA (same defect class that WOT-2026-054e fixes in
    agent_controller: auditing a motor sha against the destino repo answers with
    the wrong tree). This delegates the whole per-repo scan to
    `_productive_commits_and_ids`, which `_has_productive_commits` itself now
    calls -- harvest and BUS-VACIO gate run the SAME code path, so they cannot
    drift.

    Before: project_root is the destino; motor_root may be None; window may be
        None (then every reachable commit counts, same semantics as the bool).
    During: read-only `git log` per root through the shared helper.
    After: returns ({root_label: [ticket_id]}, {ticket_id: root_label},
        [ticket_id in first-seen motor-first order]). When the motor is
        unresolvable only the destino is scanned, so the harvest never shrinks
        silently. Never raises.
    """
    roots: dict[str, Path] = {"destino": project_root}
    if motor_root is not None:
        roots = {"motor": motor_root, "destino": project_root}

    per_root: dict[str, list[str]] = {}
    origin_of: dict[str, str] = {}
    order: list[str] = []
    for label, root in roots.items():
        found, ids = _productive_commits_and_ids(root, window_start)
        per_root[label] = ids if found else []
        for tid in per_root[label]:
            if tid not in origin_of:
                origin_of[tid] = label
                order.append(tid)
    return per_root, origin_of, order


def _read_root_archive_content(root: Path) -> str:
    """Content of `<root>/.agent/collaboration/_archive/backlog_done.md` or ''."""
    archive = root / BACKLOG_ARCHIVE_REL
    try:
        return archive.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""


def _candidate_archived_pairs(
    cand: str,
    roots: dict[str, Path],
    skip_motor: bool,
) -> list[tuple[str, str]]:
    """(id, sha) pairs citing candidate `cand` in any root's archived backlog.

    Queried PER CANDIDATE only: the archive is never swept to invent
    candidates (WOT-2026-061c direction of inference).
    """
    try:
        from scripts.check_backlog_commits_landed import parse_archived_commits
    except ImportError:
        return []
    pairs: list[tuple[str, str]] = []
    for label, root in roots.items():
        if skip_motor and label == "motor":
            # placeholder slot: the destino root is scanned under its own
            # label; do not parse the same archive twice.
            continue
        content = _read_root_archive_content(root)
        if not content:
            continue
        pairs.extend(
            (tid, sha) for tid, sha in parse_archived_commits(content) if tid == cand
        )
    return pairs


def certify_tickets_by_landed_commits(
    project_root: Path,
    motor_root: Path | None,
    window_start: datetime | None,
) -> list[str]:
    """Second certification path: this session's window commits backed by an
    archived row whose cited shas LANDED.

    WOT-2026-061c (H-C1). In direct-commit dogfooding the bus stays empty by
    design, `resolve_tickets` finds nothing and `_check_bus_vacio` blocks the
    close even though the backlog rows were already archived with
    `commit:<sha>` evidence. This path certifies EXACTLY those tickets, with the
    inference direction load-bearing:

        CORRECTO:  commits productivos en VENTANA -> buscar su respaldo archivado
        PROHIBIDO: barrer _archive/backlog_done.md -> tomar shas ancestros -> certificar

    The candidate ids come ONLY from `_harvest_window_commits_by_root`, which
    shares its scan with `_has_productive_commits` -- the very window scan
    `_check_bus_vacio` relies on; the archive is queried about those candidates,
    never swept to invent them. Inverting it would certify another session's
    last archived row over hand-editable plaintext -- the exact false green
    WOT-2026-040e / WOT-2026-042f exist to close.

    The root is resolved POR ORIGEN: a candidate harvested from motor commits is
    audited with the motor repo as home; one from destino commits, with the
    destino. Only `_CERTIFIABLE_VERDICTS` certify (canonical rules of
    WOT-2026-024q). Fail-closed at every seam: any error yields no
    certification for that ticket.

    Before: project_root is the destino; motor_root may be None.
    During: read-only git (merge-base/cat-file/log inside the landed-guard
        module) and reads of each root's archive. Mutates nothing.
    After: returns certifying ticket ids in harvest order (deduplicated). Empty
        list when there are no candidates, no archived rows, or no landing.
    """
    _per_root, origin_of, candidates = _harvest_window_commits_by_root(
        project_root, motor_root, window_start
    )
    if not candidates:
        return []

    try:
        from scripts.check_backlog_commits_landed import audit
    except ImportError:
        return []

    roots: dict[str, Path] = {"motor": project_root, "destino": project_root}
    if motor_root is not None:
        roots["motor"] = motor_root
    skip_motor = motor_root is None

    certified: list[str] = []
    for cand in candidates:
        home_label = origin_of[cand]
        home = roots[home_label]
        other = roots["destino" if home_label == "motor" else "motor"]
        pairs = _candidate_archived_pairs(cand, roots, skip_motor)
        if not pairs:
            continue
        try:
            results = audit(pairs, "origin/main", home, other_repo=other)
        except OSError:
            # fail-closed: an unrunnable git/object read certifies nothing.
            continue
        if results and all(r["verdict"] in _CERTIFIABLE_VERDICTS for r in results):
            certified.append(cand)
    return certified


def _resolve_tickets(
    project_root: Path,
    explicit_tickets: list[str] | None,
) -> tuple[list[str], str]:
    """Resolve tickets to audit using the priority chain.

    Before: project_root is valid, explicit_tickets may be None/empty.
    During: Priority: explicit CLI > detected in window > active from work_plan
        > certified by archived landed commit (WOT-2026-061c).
        The work_plan fallback is guarded (WOT-2026-040e): if the bus already
        recorded that ticket in a terminal state, work_plan.md is stale and the
        ticket belongs to an earlier session, so it is refused rather than
        certified. A refusal is marked with `STALE_WORK_PLAN_MARKER` so the
        caller can tell it apart from an empty-but-legitimate resolution.
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
                f"{STALE_WORK_PLAN_MARKER}: it points at {active}, which "
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
                f"{STALE_WORK_PLAN_MARKER}: it points at {active}, which the event bus "
                "already recorded as closed. This session produced no events of "
                "its own, so there is nothing to certify. Pass --ticket "
                "explicitly if you know what this session closed."
            )
        return [active], "fallback from work_plan.md active ticket"

    # WOT-2026-061c (H-C1): fourth, NON-contradicting source. With no events and
    # no active ticket, a direct-commit session certifies the tickets whose
    # WINDOW commits are backed by an archived row whose shas landed. The
    # direction of inference is load-bearing: candidates come from
    # `_has_productive_commits`-style window harvest (via the shared per-root
    # scan), never from a sweep of the archive (that would certify another
    # session's last archived row). A ticket with productive commits and no
    # archived backing still lands in `_check_bus_vacio` -> FAIL: the
    # fail-closed is untouched.
    try:
        from runtime.motor_link import resolve_motor_root as _rmr

        motor_root = _rmr(project_root)
    except ImportError:
        motor_root = None
    _has_any, _window_ids = _has_productive_commits(
        project_root, motor_root or project_root, window_start
    )
    if not _has_any:
        # Nothing productive in the window: nothing this path could certify,
        # and a maintenance session must keep resolving [] WITHOUT the
        # stale marker so `_check_bus_vacio` answers WARN, not FAIL.
        return [], "no tickets found"
    certified = certify_tickets_by_landed_commits(
        project_root, motor_root, window_start
    )
    if certified:
        return certified, f"{CERTIFIED_BY_ARCHIVED_COMMIT_SRC} (window harvest)"

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


def _emit_session_close_recorded(
    project_root: Path,
    window_start: datetime | None,
    overall_status: str,
) -> StepResult:
    """Emit one SESSION_CLOSE_RECORDED event per ticket found in window commits.

    WOT-2026-058j. Today the closeout writes NO bus events (0 hits of ``.emit``
    in this module), so a session that delivered commits via direct commit but
    emitted nothing leaves the NEXT session's detection window empty: the
    fallback resolves the stale work_plan and the guard refuses to certify.
    This step closes the producer gap by harvesting ticket IDs from the commit
    subjects the window already searches -- the SAME ``git log --since`` source
    the BUS VACIO check uses -- and emitting one non-transitional event per ID.

    Fire-and-forget by design: if the bus raises, the failure is recorded as a
    non-blocking WARN and the close continues. Emission is observability, not a
    gate -- making it fail-fast would let a bus failure block a close that
    already passed all its real gates.

    Before: the close report was already generated; ``overall_status != "FAIL"``
        (a red close leaves no closure signal); ``window_start`` is the session
        window from ``_resolve_session_window``.
    During: resolves the motor, runs ``git log`` in motor and destino (same
        source as ``_has_productive_commits``), extracts ticket IDs from commit
        subjects, and appends one SESSION_CLOSE_RECORDED event per unique ID
        to ``events.jsonl`` with actor SUPERVISOR and payload
        ``{"ticket_id", "source": "direct_commit", "closeout_status"}``.
    After: returns a StepResult; PASS when at least one event was written,
        WARN when nothing could be emitted (unresolvable motor or bus error),
        SKIP when there is no window. Never raises. Nothing is written when
        ``window_start`` is None: without a window there is nothing to
        describe, and harvesting the whole history would flood the bus with
        signals for every past ticket.
    """
    if window_start is None:
        return StepResult(
            name="session_close_recorded",
            status="SKIP",
            detail="no session window; nothing to signal",
        )

    try:
        from runtime.motor_link import resolve_motor_root as _rmr

        motor_root = _rmr(project_root)
    except ImportError:
        motor_root = None
    if motor_root is None:
        return StepResult(
            name="session_close_recorded",
            status="WARN",
            detail="motor_root not resolvable; no close signal emitted",
        )

    _has_commits, ticket_ids = _has_productive_commits(
        project_root, motor_root, window_start
    )
    if not ticket_ids:
        return StepResult(
            name="session_close_recorded",
            status="PASS",
            detail="no ticket IDs harvested from window commits",
        )

    try:
        from bus.event_bus import SESSION_CLOSE_RECORDED, EventBus

        events_dir = project_root / EVENTS_REL.parent
        bus = EventBus(events_dir)
        for ticket_id in ticket_ids:
            bus.emit(
                event_type=SESSION_CLOSE_RECORDED,
                ticket_id=ticket_id,
                actor="SUPERVISOR",
                payload={
                    "ticket_id": ticket_id,
                    "source": "direct_commit",
                    "closeout_status": overall_status,
                },
            )
    except Exception as exc:
        return StepResult(
            name="session_close_recorded",
            status="WARN",
            detail=f"close signal emission failed: {exc}",
        )

    return StepResult(
        name="session_close_recorded",
        status="PASS",
        detail=f"emitted SESSION_CLOSE_RECORDED for {ticket_ids}",
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


def _step_verification_mode_off(motor_root: Path, dry_run: bool) -> StepResult:
    """Apaga el modo verificacion del Stop hook al cerrar la sesion (WOT-2026-044u).

    Por que existe: el centinela `.agent/runtime/verification_mode` vive en el MOTOR
    y hace que el Stop hook exija `[EVIDENCIA]`/`[HIPOTESIS]` en cierres que mutaron
    el repo. Si una sesion lo enciende y nadie lo apaga, la SIGUIENTE sesion hereda
    la barrera sin haberla pedido.

    NO ES BLOQUEANTE por diseno: es higiene de estado, no un gate. Un fallo aqui
    jamas debe tumbar un cierre; se reporta como WARN visible (no SKIP generico,
    que seria silencio) para que quede en el informe.

    Idempotente: si el centinela no existe, devuelve OK con detail explicito.
    """
    sentinel = motor_root / ".agent" / "runtime" / "verification_mode.json"
    if dry_run:
        estado = "presente" if sentinel.is_file() else "ausente"
        return StepResult(
            name="verification_mode_off",
            status="SKIP",
            detail=f"dry-run; centinela {estado}",
        )
    try:
        if not sentinel.is_file():
            return StepResult(
                name="verification_mode_off",
                status="PASS",
                detail="already off",
            )
        sentinel.unlink()
        return StepResult(
            name="verification_mode_off",
            status="PASS",
            detail=f"sentinel removed: {sentinel}",
        )
    except OSError as exc:
        return StepResult(
            name="verification_mode_off",
            status="WARN",
            detail=f"no se pudo apagar el modo verificacion: {exc}",
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


def _resolve_deliverable_type_for_ticket(project_root: Path, ticket_id: str) -> str:
    """Resolve the ``deliverable_type`` declared for ``ticket_id`` in the backlog.

    WOT-2026-045a. `_resolve_tickets` only returns ticket IDs, not their
    metadata, so the writer must go look the type up itself.

    Before: ``project_root`` is the repo_destino; ``ticket_id`` is a resolved
        ticket string.
    During: Searches for a row containing ``ticket_id`` first in the live
        backlog (`.agent/collaboration/backlog.md`), then in the archive
        (`_archive/backlog_done.md`). Within the matching row, extracts the
        literal ``deliverable_type: <value>`` cell text with
        ``DELIVERABLE_TYPE_RE``. Values are NEVER normalized (e.g. `doc` or
        `process` are emitted verbatim): deciding taxonomy is a DEC, not
        Builder work.
    After: Returns the raw string value found. Falls back to `"code"` (the
        ticket's own declared type and the strictest alongside `mixed`) when
        the ticket has no row in either file, the row has no
        `deliverable_type:` cell, or the file cannot be read. Never raises.
    """
    for rel in (BACKLOG_REL, BACKLOG_ARCHIVE_REL):
        path = project_root / rel
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in content.splitlines():
            if ticket_id not in line:
                continue
            m = DELIVERABLE_TYPE_RE.search(line)
            if m:
                return m.group(1)
    # No row found in either surface, or the row lacked the cell: fall back
    # to "code" (documented default per contract WOT-2026-045a).
    return "code"


def _git_log_shas_for_ticket(
    motor_root: Path, ticket_id: str, since_args: list[str]
) -> tuple[list[str] | None, str]:
    """Run `git log --grep=<ticket_id>` and return matching shas.

    WOT-2026-045a. Extracted so the caller stays under complexity budget.

    Before: ``motor_root`` is a resolvable git repo root; ``since_args`` is
        `["--since=<ISO>"]` or `[]` (open window).
    During: `subprocess.run(["git", "log", "--format=%H",
        f"--grep={ticket_id}", "--fixed-strings", *since_args],
        cwd=motor_root)`, never reading `$?` after a pipe.
    After: Returns `(shas, "")` on success (possibly an empty list when no
        commit matches). Returns `(None, detail)` on any git failure (OSError
        or non-zero returncode), where `detail` explains the failure.
    """
    cmd = [
        "git",
        "log",
        "--format=%H",
        f"--grep={ticket_id}",
        "--fixed-strings",
        *since_args,
    ]
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=motor_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        return None, f"git log failed for {ticket_id}: {exc}"
    if result.returncode != 0:
        return None, (
            f"git log rc={result.returncode} for {ticket_id}: {result.stderr.strip()}"
        )
    return [s for s in result.stdout.splitlines() if s.strip()], ""


def _resolve_authoritative_repo(
    ticket_id: str,
    motor_root: Path,
    extract_prefix_fn,
    resolve_prefix_fn,
) -> tuple[Path, Path | None, bool, str]:
    """Resolve the authoritative repo for a ticket by its prefix.

    WOT-2026-048b. WOT- tickets always resolve to motor_root (special case:
    their commits live in the motor even though resolve_prefix('WOT') returns
    the workspace destination). Non-WOT prefixes resolve via prefix_resolver.

    Returns (authoritative_root, other_root_for_control, skip, warn_detail).
    """
    if extract_prefix_fn is None or resolve_prefix_fn is None:
        return motor_root, None, False, ""
    prefix = extract_prefix_fn(ticket_id)
    if prefix is None or prefix == "WOT":
        return motor_root, None, False, ""
    try:
        resolved_dest = resolve_prefix_fn(prefix, motor_root)
    except Exception:
        resolved_dest = None
    if resolved_dest is None:
        return (
            motor_root,
            None,
            True,
            (f"WARN_PREFIX_UNRESOLVABLE: {ticket_id} (prefix={prefix}); skipping"),
        )
    other = motor_root if resolved_dest != motor_root else None
    return resolved_dest, other, False, ""


@dataclass
class _TicketTargetResult:
    lines: list[str]
    status: str  # "PASS", "WARN", "FAIL"
    detail: str = ""
    blocking: bool = False


def _process_ticket_targets(
    ticket_id: str,
    project_root: Path,
    motor_root: Path,
    extract_prefix_fn,
    resolve_prefix_fn,
    since_args: list[str],
) -> _TicketTargetResult:
    """Process a single ticket for loop execution targets.

    WOT-2026-048b. Resolves the authoritative repo by prefix, searches for
    commits, and runs a control query when the authoritative repo is empty.
    """
    authoritative_root, other_root, skip, warn = _resolve_authoritative_repo(
        ticket_id, motor_root, extract_prefix_fn, resolve_prefix_fn
    )
    if skip:
        return _TicketTargetResult([], "WARN", warn)

    shas, error_detail = _git_log_shas_for_ticket(
        authoritative_root, ticket_id, since_args
    )
    if shas is None:
        return _TicketTargetResult([], "SKIP", error_detail)

    if not shas and other_root is not None:
        ctrl_shas, _ = _git_log_shas_for_ticket(other_root, ticket_id, since_args)
        if ctrl_shas:
            return _TicketTargetResult(
                [],
                "FAIL",
                f"FAIL_TARGETS_MISSING: {ticket_id} not in authoritative "
                f"repo ({authoritative_root}) but found in {other_root}",
                blocking=True,
            )

    if not shas:
        return _TicketTargetResult([], "PASS")

    dtype = _resolve_deliverable_type_for_ticket(project_root, ticket_id)
    return _TicketTargetResult([f"{sha} {dtype}" for sha in shas], "PASS")


@dataclass
class _WriterSetup:
    motor_root: Path
    extract_prefix_fn: Any
    resolve_prefix_fn: Any
    since_args: list[str]
    window_detail: str


def _resolve_writer_setup(
    project_root: Path, window_start: datetime | None
) -> _WriterSetup | StepResult:
    """Resolve motor_root, prefix resolvers, and window args for the writer.

    Returns _WriterSetup on success, or a SKIP StepResult on failure.
    """
    try:
        from runtime.motor_link import resolve_motor_root
    except ImportError:
        return StepResult(
            name="write_loop_execution_targets",
            status="SKIP",
            detail="runtime.motor_link not available; writer skipped",
        )

    motor_root = resolve_motor_root(project_root)
    if motor_root is None:
        return StepResult(
            name="write_loop_execution_targets",
            status="SKIP",
            detail="motor_root not resolvable; writer skipped",
        )

    try:
        from scripts.prefix_resolver import extract_prefix, resolve_prefix
    except ImportError:
        extract_prefix = None  # type: ignore[assignment]
        resolve_prefix = None  # type: ignore[assignment]

    since_args: list[str] = []
    window_detail = "no window filter (None: this flight's window is open)"
    if window_start is not None:
        since_iso = window_start.strftime("%Y-%m-%dT%H:%M:%S")
        since_args = [f"--since={since_iso}"]
        window_detail = f"--since={since_iso}"

    return _WriterSetup(
        motor_root, extract_prefix, resolve_prefix, since_args, window_detail
    )


def _finalize_targets_result(
    name: str,
    lines: list[str],
    ticket_ids: list[str],
    worst_status: str,
    detail_parts: list[str],
    targets_path: Path,
    window_detail: str,
) -> StepResult:
    """Build the final StepResult for the writer step."""
    if worst_status == "FAIL":
        return StepResult(
            name=name,
            status="FAIL",
            detail="; ".join(detail_parts) if detail_parts else "targets missing",
            blocking=True,
        )

    if not lines:
        if targets_path.exists():
            targets_path.unlink()
        detail = (
            f"nothing to declare (tickets={ticket_ids or 'none'}, "
            f"window={window_detail}); file removed if present"
        )
        if detail_parts:
            detail += "; " + "; ".join(detail_parts)
        return StepResult(name=name, status=worst_status, detail=detail)

    targets_path.parent.mkdir(parents=True, exist_ok=True)
    targets_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    detail = (
        f"wrote {len(lines)} commit line(s) for {len(ticket_ids)} "
        f"ticket(s); window={window_detail}"
    )
    if detail_parts:
        detail += "; " + "; ".join(detail_parts)
    return StepResult(name=name, status=worst_status, detail=detail)


def _step_write_loop_execution_targets(
    project_root: Path,
    ticket_ids: list[str],
    window_start: datetime | None,
    dry_run: bool,
) -> StepResult:
    """Write `.agent/collaboration/loop_execution_targets.txt` self-running.

    WOT-2026-045a. Closes the productor gap: today nobody writes this file by
    code, so `check_loop_execution` (via `prepush_check.py:848`) always sees
    either a hand-maintained file or none, and a flight that ran and one that
    did not produce the identical SKIP observable. This writer derives the
    file from the SAME ticket resolution the closeout already trusts
    (`_resolve_tickets`), so the scope is never self-declared by a human.

    Before: ``project_root`` is the repo_destino; ``ticket_ids`` is the
        resolved list from `_resolve_tickets` (called immediately before this
        step in `run_closeout`); ``window_start`` is the flight window from
        `_resolve_session_window` (called one line earlier still); ``dry_run``
        mirrors the flag every other mutating step in this module receives
        (`_step_cleanup_builder_session`, `_step_git_clean`, the `_step_archive_*`
        family, ...).
    During: WOT-2026-045a review (defecto 2): when ``dry_run`` is True, this
        step performs NO filesystem I/O at all -- it does not run `git log`
        and does not touch the targets file, matching the module's unanimous
        pattern (every other mutating step short-circuits to SKIP before any
        write) and the module docstring's promise (`:26`) that `git status
        --short` stays clean after `--dry-run`. Otherwise, for each ticket,
        runs `git log --format=%H --grep=<ticket_id> --fixed-strings` (plus
        `--since=<window_start ISO>` when the window is known) with
        `cwd=<motor_root>` via `subprocess.run` (never `$?` after a pipe).
        Every matching commit produces one line, unbounded, in git's own
        order. Resolves `deliverable_type` per ticket via
        `_resolve_deliverable_type_for_ticket`. If `motor_root` cannot be
        resolved (`runtime.motor_link` unavailable or no link), the step is a
        no-op SKIP: git log has no root to run against.
    After: In dry-run, always returns SKIP with detail "Skipped in dry-run
        mode" and the file is left untouched (created, deleted, or absent --
        whatever state it was already in). Otherwise: if at least one commit
        line was produced, writes the whole file (never appends) with one
        `<sha> <deliverable_type>` line per commit and returns PASS. If zero
        tickets or zero matching commits exist, deletes the file if present
        (so the consumer's `if not targets_file.exists()` branch fires) and
        returns PASS with a "nothing to declare" detail. Never raises: git
        failures degrade to SKIP with the stderr detail recorded.
    """
    name = "write_loop_execution_targets"
    if dry_run:
        return StepResult(name=name, status="SKIP", detail="Skipped in dry-run mode")

    setup = _resolve_writer_setup(project_root, window_start)
    if isinstance(setup, StepResult):
        return setup

    targets_path = project_root / LOOP_EXECUTION_TARGETS_REL
    lines: list[str] = []
    worst_status = "PASS"
    detail_parts: list[str] = []

    for ticket_id in ticket_ids:
        res = _process_ticket_targets(
            ticket_id,
            project_root,
            setup.motor_root,
            setup.extract_prefix_fn,
            setup.resolve_prefix_fn,
            setup.since_args,
        )
        if res.status == "SKIP":
            return StepResult(name=name, status="SKIP", detail=res.detail)
        if res.status == "FAIL":
            worst_status = "FAIL"
            detail_parts.append(res.detail)
            continue
        if res.status == "WARN":
            if worst_status != "FAIL":
                worst_status = "WARN"
            detail_parts.append(res.detail)
            continue
        lines.extend(res.lines)

    return _finalize_targets_result(
        name,
        lines,
        ticket_ids,
        worst_status,
        detail_parts,
        targets_path,
        setup.window_detail,
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
    # WOT-2026-040e: una lista vacia tiene DOS significados y solo uno debe
    # bloquear. Antes se degradaban ambos a WARN, y como el exit code solo es 1
    # cuando el overall es FAIL (:1002-1003), un cierre que RECHAZO un
    # work_plan stale salia con exit 0 igual. Medido dos veces (2026-07-23 y
    # 2026-08-06): la segunda certifico CERO tickets mientras la sesion
    # entregaba 7 commits, y el WARN no lo detuvo.
    _resolved_stale = STALE_WORK_PLAN_MARKER in ticket_src
    if ticket_ids:
        _resolve_status = "PASS"
    elif _resolved_stale:
        _resolve_status = "FAIL"
    else:
        _resolve_status = _check_bus_vacio(project_root, _window_start)
    # WOT-2026-040e (ampliacion): cuando el cierre cae en BUS VACIO (commits
    # productivos + 0 eventos), medir TAMBIEN la segunda superficie de
    # proyeccion (execution_log.md) y anexarla al diagnostico. No cambia el
    # veredicto: lo documenta.
    _detail = _resolve_tickets_detail(
        ticket_src,
        ticket_ids,
        status=_resolve_status,
        stale=_resolved_stale,
        project_root=project_root,
        window_start=_window_start,
    )
    report.steps.append(
        StepResult(
            name="resolve_tickets",
            status=_resolve_status,
            detail=_detail,
            # `blocking` cuando hubo RECHAZO o BUS VACIO: `overall_status` escala
            # a FAIL unicamente si el paso que falla es blocking (WOT-2026-013m).
            # Un cierre de mantenimiento (WARN) no es blocking y sigue saliendo 0.
            blocking=_resolved_stale or (_resolve_status == "FAIL" and not ticket_ids),
        )
    )
    report.steps.append(
        _step_write_loop_execution_targets(
            project_root, ticket_ids, _window_start, dry_run
        )
    )
    # WOT-2026-040w: wire write_decision_record for flights that stopped without
    # commits. Without this, the handoff committed check (prepush) rejects the
    # closeout because the working tree is dirty (decision files written but not
    # committed) or there is no commit to audit (F7: work in limbo).
    if ticket_ids and not dry_run:
        _step_write_decision_records(project_root, ticket_ids)
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
            report.steps.append(_step_verification_mode_off(motor_root, dry_run))
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
    # Capture overall BEFORE emission: the signal must land strictly after the
    # report snapshot so its timestamp sits inside the NEXT session's window
    # (filter `dt >= window_start`), and a bus hiccup must never change the
    # exit code of a close that already passed its real gates.
    overall_status = report.overall_status
    report_path = _generate_report(report, project_root)
    # Dry-run writes to runtime/tmp/ (non-mutating, 7d28d2e); print the path
    # so operators and reviewers do not look at the stale canonical report.
    print(f"[closeout] Report ({overall_status}): {report_path}")

    # WOT-2026-058j: the closeout itself must leave a bus trace when it
    # resolved tickets from commits. A session delivered by direct commit
    # writes no events today, so the NEXT session's detection window comes up
    # empty, the fallback resolves the stale work_plan, and the guard refuses
    # to certify. Emit one non-transitional SESSION_CLOSE_RECORDED event per
    # ticket found in the window's commits, strictly AFTER report generation.
    # A red close emits nothing: a failed close leaves no closure signal. In
    # dry-run, nothing is emitted (the run must not mutate the tree).
    if overall_status != "FAIL" and not dry_run:
        report.steps.append(
            _emit_session_close_recorded(project_root, _window_start, overall_status)
        )

    # Return code: 0 if overall is PASS or WARN, 1 if FAIL
    return 1 if overall_status == "FAIL" else 0


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
