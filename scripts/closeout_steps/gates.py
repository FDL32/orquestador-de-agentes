"""Quality-gate closeout steps extracted from scripts.session_closeout.

This module owns the prepush, audit, prose-validation, and manifest-check
steps that used to live in the session_closeout monolith.
"""

from __future__ import annotations

import json
import subprocess
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
