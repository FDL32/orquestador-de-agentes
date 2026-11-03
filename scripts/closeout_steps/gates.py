"""Quality-gate closeout steps extracted from scripts.session_closeout.

This module owns the prepush, audit, prose-validation, and manifest-check
steps that used to live in the session_closeout monolith.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from scripts.session_closeout import StepResult


# WOT-2026-081c: under --skip-gates the prepush CLI still runs every check and
# prints the full report; only the closing verdict is degraded to exit 0. These
# are the two stable anchors in that stdout that separate a degraded rc==0 from
# a clean one, so the closeout step never reports a faked "all passed".
_DEGRADED_PREFLIGHT_BANNER = "PREFLIGHT CON FALLOS pero --skip-gates activo"
_PREFLIGHT_FAIL_PREFIX = "[FAIL] "


def _extract_degraded_prepush_failures(
    stdout: str,
) -> list[tuple[str, list[str]]]:
    """Extract ``[FAIL] <check>`` names and their leading diagnostic lines.

    Before: ``stdout`` is the captured prepush_check.py report.
    During: reads only lines that start with ``[FAIL] `` at column zero -- the
        report (_print_preflight_report) prints exactly one such row per
        blocking failure, while a check's own diagnostic lines are indented, so
        a nested ``[FAIL]`` inside a tool's output is not mistaken for a check
        row. The diagnostic lines printed under a row are indented with six
        spaces; the first few are captured as context.
    After: returns one ``(name, context_lines)`` per blocking failure, in report
        order. Empty when no parseable row exists (caller then falls back to the
        degradation banner). Pure function: no I/O, no mutation.
    """
    failures: list[tuple[str, list[str]]] = []
    lines = stdout.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith(_PREFLIGHT_FAIL_PREFIX):
            index += 1
            continue
        name = line[len(_PREFLIGHT_FAIL_PREFIX) :].strip()
        context: list[str] = []
        probe = index + 1
        while probe < len(lines) and lines[probe].startswith("      "):
            context.append(lines[probe].strip())
            probe += 1
        failures.append((name, context[:3]))
        index = probe
    return failures


def step_prepush_check(
    project_root: Path,
    dry_run: bool,
    *,
    run_script_fn,
    process_diagnostic_fn,
    step_result_cls: type[StepResult],
    skip_gates: bool = False,
) -> StepResult:
    """Run prepush_check.py as the blocking quality gate.

    WOT-2026-020i: when skip_gates is True, forward --skip-gates so a blocking
    prepush failure no longer blocks the close (the operator chose to close over
    pre-existing debt). Default False preserves the blocking behavior.

    WOT-2026-040y: dry-run reports NOT_VERIFIED, not SKIP. SKIP is the same token
    this report uses for "deliberately not applicable", so a gate that never ran
    was indistinguishable from one that ran clean -- and since ``overall_status``
    only inspects FAIL/WARN, a dry-run that verified nothing aggregated to PASS.
    That is the invocation WOT-2026-040j consumed as closeout evidence. The
    status is the whole fix: the callers that treat this gate as blocking key off
    it (see session_closeout.overall_status and the early cut in run_closeout).

    WOT-2026-081c: a degraded ``rc==0`` (--skip-gates swallowed real blocking
    failures) must not read as PASS. The rc==0 branch parses ``result.stdout``
    for the degradation banner and/or ``[FAIL] <check>`` rows; when present it
    returns status WARN, blocking=False, with the failures in ``detail``. A
    clean rc==0 with neither anchor keeps the PASS literal.
    """
    if dry_run:
        return step_result_cls(
            name="prepush_check",
            status="NOT_VERIFIED",
            detail="Not run in dry-run mode: this gate was not verified",
            blocking=True,
        )
    try:
        prepush_args = ["--project-root", str(project_root), "--closeout-mode"]
        if skip_gates:
            prepush_args.append("--skip-gates")
        result = run_script_fn(
            "prepush_check.py",
            # WOT-2026-014a: pass --closeout-mode so check_git_tree_clean forgives
            # expected runtime artifacts (session_close_report.md, etc.) that the
            # closeout itself generates. Non-closeout callers of prepush_check do
            # NOT pass this flag, preserving the general pre-push gate unchanged.
            prepush_args,
            project_root,
            timeout=300,
        )
        if result.returncode == 0:
            stdout = result.stdout or ""
            failures = _extract_degraded_prepush_failures(stdout)
            if failures:
                rendered = "; ".join(
                    f"{name} ({' | '.join(context)})" if context else name
                    for name, context in failures
                )
                return step_result_cls(
                    name="prepush_check",
                    status="WARN",
                    detail=(
                        "PREFLIGHT degradado por --skip-gates: "
                        f"{len(failures)} check(s) bloqueante(s) fallaron: "
                        f"{rendered}"
                    ),
                    blocking=False,
                )
            if _DEGRADED_PREFLIGHT_BANNER in stdout:
                return step_result_cls(
                    name="prepush_check",
                    status="WARN",
                    detail=(
                        "PREFLIGHT degradado por --skip-gates: fallos bloqueantes "
                        "ignorados por decision del operador (banner detectado, "
                        "sin lineas [FAIL] parseables)"
                    ),
                    blocking=False,
                )
            return step_result_cls(
                name="prepush_check",
                status="PASS",
                detail="All blocking quality checks passed",
                blocking=True,
            )
        detail = process_diagnostic_fn(result)
        return step_result_cls(
            name="prepush_check",
            status="FAIL",
            detail=f"Quality gate failed (exit {result.returncode}): {detail}",
            blocking=True,
        )
    except subprocess.TimeoutExpired:
        return step_result_cls(
            name="prepush_check",
            status="FAIL",
            detail="prepush_check.py timed out after 300s",
            blocking=True,
        )
    except FileNotFoundError:
        return step_result_cls(
            name="prepush_check",
            status="FAIL",
            detail="prepush_check.py not found in scripts/",
            blocking=True,
        )


def step_roster_matches_acting_thread(
    project_root: Path,
    dry_run: bool,
    *,
    acting_thread: str,
    roster_path: str | None,
    registry_path: str | None,
    changes_log: str | None,
    run_script_fn,
    process_diagnostic_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run check_roster_matches_acting_thread.py as a blocking roster integrity gate.

    WOT-2026-136c: verifies that active_roles of the flight roster matches the
    acting thread (whoever is closing the session). Three possible outcomes
    depending on roster availability and --acting-thread:

    - No roster (neither FLIGHT_ROSTER_PATH nor --roster-path) -> SKIP, non-blocking.
    - Roster present + --acting-thread provided -> PASS or FAIL, blocking.
    - Roster present WITHOUT --acting-thread -> FAIL, blocking (fail-closed by identity).

    WOT-2026-136c: dry_run=True returns SKIP immediately without invoking the guard,
    so dry-runs never block, regardless of roster availability or --acting-thread.
    """
    if dry_run:
        return step_result_cls(
            name="roster_matches_acting_thread",
            status="SKIP",
            detail="Not run in dry-run mode: roster gate was not verified",
            blocking=False,
        )
    try:
        roster_args = []
        if roster_path:
            roster_args.extend(["--roster-path", roster_path])
        if acting_thread:
            roster_args.extend(["--acting-thread", acting_thread])
        if registry_path:
            roster_args.extend(["--registry-path", registry_path])
        if changes_log:
            roster_args.extend(["--changes-log", changes_log])
        result = run_script_fn(
            "check_roster_matches_acting_thread.py",
            roster_args,
            project_root,
            timeout=60,
        )
        if result.returncode == 0:
            return step_result_cls(
                name="roster_matches_acting_thread",
                status="PASS",
                detail="Roster and acting thread match",
                blocking=True,
            )
        if result.returncode == 3:
            return step_result_cls(
                name="roster_matches_acting_thread",
                status="SKIP",
                detail="No roster found (N/A): guard not applicable to this closeout",
                blocking=False,
            )
        # exit code 1 or any other code (including exceptions) -> FAIL, blocking
        detail = process_diagnostic_fn(result)
        return step_result_cls(
            name="roster_matches_acting_thread",
            status="FAIL",
            detail=f"Roster integrity check failed (exit {result.returncode}): {detail}",
            blocking=True,
        )
    except subprocess.TimeoutExpired:
        return step_result_cls(
            name="roster_matches_acting_thread",
            status="FAIL",
            detail="check_roster_matches_acting_thread.py timed out after 60s",
            blocking=True,
        )
    except FileNotFoundError:
        return step_result_cls(
            name="roster_matches_acting_thread",
            status="FAIL",
            detail="check_roster_matches_acting_thread.py not found in scripts/",
            blocking=True,
        )


_LATIDO_CHECK = "flight/check_latido_alert_wiring.py"
_LATIDO_REPRO_PREFIX = "reproducir y revalidar:"


def _latido_repro_command(roster_path: str | None, latido_files: list[str]) -> str:
    """Orden exacta (reproducir y revalidar) con los mismos argumentos que recibio el paso."""
    motor_root = Path(__file__).resolve().parents[2]
    git_exe = shutil.which("git") or "git"
    parts = [
        "python",
        f"scripts/{_LATIDO_CHECK}",
        "--motor-root",
        str(motor_root),
        "--python-exe",
        sys.executable,
        "--git-exe",
        git_exe,
    ]
    if roster_path:
        parts += ["--roster-path", roster_path]
    for spec in latido_files:
        parts += ["--latido-file", spec]
    return subprocess.list2cmdline(parts)


def _latido_fail_detail(
    headline: str, stdout: str, roster_path: str | None, latido_files: list[str]
) -> str:
    """Detalle self-service de un FAIL: QUE falla, COMO reproducirlo y COMO revalidar."""
    lines = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
    findings = [ln[:160] for ln in lines if ln.startswith("- [")][:3]
    repro = next(
        (ln for ln in lines if ln.startswith(_LATIDO_REPRO_PREFIX)),
        _LATIDO_REPRO_PREFIX + " " + _latido_repro_command(roster_path, latido_files),
    )
    what = (
        " | ".join(findings)
        if findings
        else (lines[0][:200] if lines else "sin salida")
    )
    return (
        f"{headline}. QUE falla: {what}. COMO reproducirlo: {repro[len(_LATIDO_REPRO_PREFIX) :].strip()}. "
        "COMO revalidar: corrige el latido (rutas absolutas al motor, interprete fijado, ordenes "
        "obligatorias del rol) y repite esa misma orden hasta rc 0, sin escalar al humano"
    )


def step_latido_alert_wiring(
    project_root: Path,
    dry_run: bool,
    *,
    roster_path: str | None,
    latido_files: list[str] | None,
    run_script_fn,
    process_diagnostic_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run flight/check_latido_alert_wiring.py as a blocking, self-service closeout gate.

    WOT-2026-153k (A, obligatorio en el cierre FINAL): verifica que los latidos del vuelo
    invocan el mecanismo de avisos del motor (ruta absoluta, tracked e igual a HEAD,
    interprete fijado, ordenes obligatorias por rol). Contrato de rc del check:

    - dry_run=True -> SKIP, non-blocking (nada se verifico).
    - roster declarado cuyo fichero no existe -> FAIL, blocking: un roster declarado pero
      ausente deja el cierre sin verificar y no puede degradarse a SKIP fail-open.
    - rc 3 (N/A: sin roster) -> SKIP, non-blocking: un cierre ordinario NO cambia.
    - rc 0 -> PASS, blocking.
    - rc 1 (violacion), rc 2 (ilegible), otro rc, timeout de 60 s o script ausente ->
      FAIL, blocking. El detail dice QUE falla, COMO reproducirlo (la orden exacta) y COMO
      revalidar, sin escalar al humano.

    The roster is passed with --roster-path only when the closeout received one; the latidos
    with one --latido-file ROL=RUTA each (the child also inherits FLIGHT_ROSTER_PATH and
    FLIGHT_LATIDO_FILES from the environment).
    """
    name = "latido_alert_wiring"
    if dry_run:
        return step_result_cls(
            name=name,
            status="SKIP",
            detail="Not run in dry-run mode: latido wiring was not verified",
            blocking=False,
        )
    if roster_path and not (
        Path(roster_path).is_file() or (project_root / roster_path).is_file()
    ):
        return step_result_cls(
            name=name,
            status="FAIL",
            detail=_latido_fail_detail(
                f"Roster file not found ({roster_path}): latido wiring not verified",
                "",
                roster_path,
                list(latido_files or []),
            ),
            blocking=True,
        )
    specs = list(latido_files or [])
    args: list[str] = ["--roster-path", roster_path] if roster_path else []
    for spec in specs:
        args += ["--latido-file", spec]
    try:
        result = run_script_fn(_LATIDO_CHECK, args, project_root, timeout=60)
    except subprocess.TimeoutExpired:
        return step_result_cls(
            name=name,
            status="FAIL",
            detail=_latido_fail_detail(
                "check_latido_alert_wiring.py agoto 60s", "", roster_path, specs
            ),
            blocking=True,
        )
    except FileNotFoundError:
        return step_result_cls(
            name=name,
            status="FAIL",
            detail=_latido_fail_detail(
                "flight/check_latido_alert_wiring.py no existe en scripts/",
                "",
                roster_path,
                specs,
            ),
            blocking=True,
        )
    except OSError as exc:
        return step_result_cls(
            name=name,
            status="FAIL",
            detail=_latido_fail_detail(
                f"no se pudo ejecutar flight/check_latido_alert_wiring.py "
                f"({type(exc).__name__}: {exc})",
                "",
                roster_path,
                specs,
            ),
            blocking=True,
        )
    if result.returncode == 0:
        return step_result_cls(
            name=name,
            status="PASS",
            detail="Latidos invocan el mecanismo de avisos del motor",
            blocking=True,
        )
    if result.returncode == 3:
        return step_result_cls(
            name=name,
            status="SKIP",
            detail="No roster found (N/A): latido wiring not applicable to this closeout",
            blocking=False,
        )
    return step_result_cls(
        name=name,
        status="FAIL",
        detail=_latido_fail_detail(
            f"Latidos sin cablear o ilegibles (exit {result.returncode})",
            result.stdout or process_diagnostic_fn(result),
            roster_path,
            specs,
        ),
        blocking=True,
    )


def step_quota_index_drift(
    project_root: Path,
    dry_run: bool,
    *,
    roster_path: str | None,
    run_script_fn,
    process_diagnostic_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run flight/check_quota_index_drift.py as a read-only, NEVER blocking check.

    WOT-2026-136m: compares the `quota` field index of the supervision protocol with
    the `quota` block of the live flight roster. The first stdout line of the script is
    the contract; this step never maps anything to FAIL and is never blocking, because
    a stale documentation index (or a defect of the check itself) is not a closeout
    failure:

    - dry_run=True -> SKIP, declaring the drift was not verified.
    - rc 0 and first line `OK ...` -> PASS.
    - rc 0 and first line `AVISO ...` -> WARN with the drifted keys in the detail.
    - rc 2 (`NO VERIFICABLE ...`), timeout, script missing, rc 1/3/other -> NOT_VERIFIED
      with the reason in the detail (the script never emits rc 3 by contract).

    The roster is passed with --roster-path only when the closeout received one;
    otherwise the child inherits FLIGHT_ROSTER_PATH from the environment.
    """
    name = "quota_index_drift"
    if dry_run:
        return step_result_cls(
            name=name,
            status="SKIP",
            detail="Not run in dry-run mode: quota index drift was not verified",
            blocking=False,
        )
    roster_args = ["--roster-path", roster_path] if roster_path else []
    try:
        result = run_script_fn(
            "flight/check_quota_index_drift.py",
            roster_args,
            project_root,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return step_result_cls(
            name=name,
            status="NOT_VERIFIED",
            detail="check_quota_index_drift.py timed out after 30s",
            blocking=False,
        )
    except FileNotFoundError:
        return step_result_cls(
            name=name,
            status="NOT_VERIFIED",
            detail="flight/check_quota_index_drift.py not found in scripts/",
            blocking=False,
        )
    first_line = (result.stdout or "").strip().split("\n", 1)[0]
    if result.returncode == 0 and first_line.startswith("OK"):
        return step_result_cls(
            name=name, status="PASS", detail=first_line, blocking=False
        )
    if result.returncode == 0 and first_line.startswith("AVISO"):
        return step_result_cls(
            name=name,
            status="WARN",
            detail=(result.stdout or "").strip(),
            blocking=False,
        )
    return step_result_cls(
        name=name,
        status="NOT_VERIFIED",
        detail=f"quota index drift not verified (exit {result.returncode}): "
        f"{process_diagnostic_fn(result)}",
        blocking=False,
    )


def step_integration_receipts(
    project_root: Path,
    dry_run: bool,
    *,
    targets_path: Path,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Require an integration receipt for every loop target that is not declared debt.

    WOT-2026-143a: the loop is demanded per TICKET on its last commit, and a ``git merge
    --ff-only`` fires no hook that could authorize it, so the only integration path is
    ``scripts/flight/integrate_ticket.py`` (audit, ff, receipt). This step is the barrier by
    ABSENCE: skipping the wrapper leaves a target without receipt and the closeout fails here.
    The receipt is operational, not cryptographic.

    - dry_run=True -> SKIP (the targets file may be stale, nothing was verified).
    - no targets file, or no target line -> SKIP, non-blocking (nothing to demand).
    - targets file unreadable -> FAIL, blocking (never read as "no targets").
    - every target in ``HISTORIC_LOOP_DEBT`` is exempt (named in the detail); every other
      target needs a valid receipt and its tip still an ancestor of the motor HEAD.
    - a missing/invalid receipt -> FAIL, blocking, naming each sha and the command.
    """
    name = "integration_receipts"
    if dry_run:
        return step_result_cls(
            name=name,
            status="SKIP",
            detail="Not run in dry-run mode: integration receipts were not verified",
            blocking=False,
        )
    if not targets_path.exists():
        return step_result_cls(
            name=name,
            status="SKIP",
            detail=f"No {targets_path.name}: no loop target to demand a receipt for",
            blocking=False,
        )
    try:
        text = targets_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return step_result_cls(
            name=name,
            status="FAIL",
            detail=f"{targets_path} exists but cannot be read ({exc})",
            blocking=True,
        )
    try:
        from scripts.flight.integrate_ticket import verify_receipts
    except ImportError:
        from flight.integrate_ticket import verify_receipts  # type: ignore[no-redef]
    try:
        from runtime.motor_link import resolve_motor_root

        motor_root = resolve_motor_root(project_root)
    except ImportError:
        motor_root = None
    problems, notes = verify_receipts(project_root, text, motor_root)
    if problems:
        return step_result_cls(
            name=name,
            status="FAIL",
            detail=(
                f"{len(problems)} target(s) sin recibo de integracion valido: "
                + "; ".join(problems)
                + ". Integra con python scripts/flight/integrate_ticket.py --ticket <ID> "
                "--candidate <ref> --project-root <destino> (o --attest si ya esta integrado)"
            ),
            blocking=True,
        )
    return step_result_cls(
        name=name,
        status="PASS",
        detail="Every non-debt loop target has an integration receipt"
        + (f" ({'; '.join(notes)})" if notes else ""),
        blocking=True,
    )


def step_local_audit(
    project_root: Path,
    dry_run: bool,
    *,
    run_script_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run local_audit.py as an informational snapshot."""
    if dry_run:
        return step_result_cls(
            name="local_audit",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = run_script_fn(
            "local_audit.py",
            ["--json", "--quick"],
            project_root,
            timeout=120,
        )
        if result.returncode == 0:
            return step_result_cls(
                name="local_audit",
                status="PASS",
                detail="Local audit snapshot captured",
            )
        return step_result_cls(
            name="local_audit",
            status="WARN",
            detail=f"Local audit returned exit {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return step_result_cls(
            name="local_audit",
            status="WARN",
            detail=f"Local audit could not run: {exc}",
        )


def step_validate_ticket_prose(
    project_root: Path,
    dry_run: bool,
    *,
    run_script_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run validate_ticket_prose.py --json as an informational check."""
    if dry_run:
        return step_result_cls(
            name="validate_ticket_prose",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = run_script_fn(
            "validate_ticket_prose.py",
            ["--json"],
            project_root,
            timeout=60,
        )
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
        return step_result_cls(
            name="validate_ticket_prose",
            status="PASS" if warnings == 0 else "WARN",
            detail=detail,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return step_result_cls(
            name="validate_ticket_prose",
            status="WARN",
            detail=f"Ticket prose validation could not run: {exc}",
        )


def step_manifest_check(
    project_root: Path,
    dry_run: bool,
    *,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Verify MANIFEST.distribute exists."""
    _ = dry_run
    manifest_root = project_root
    try:
        from runtime.motor_link import resolve_motor_root

        motor_root = resolve_motor_root(project_root)
        if motor_root is not None:
            manifest_root = motor_root
    except ImportError:
        pass

    manifest_path = manifest_root / "MANIFEST.distribute"
    if manifest_path.exists():
        location = "repo_motor" if manifest_root != project_root else "project root"
        return step_result_cls(
            name="manifest_check",
            status="PASS",
            detail=f"MANIFEST.distribute exists in {location}",
        )
    return step_result_cls(
        name="manifest_check",
        status="WARN",
        detail="MANIFEST.distribute not found at project root",
    )
