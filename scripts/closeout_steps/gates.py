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


def step_prepush_check(
    project_root: Path,
    dry_run: bool,
    *,
    run_script_fn,
    process_diagnostic_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run prepush_check.py as the blocking quality gate."""
    if dry_run:
        return step_result_cls(
            name="prepush_check",
            status="SKIP",
            detail="Skipped in dry-run mode",
            blocking=True,
        )
    try:
        result = run_script_fn(
            "prepush_check.py",
            ["--project-root", str(project_root)],
            project_root,
            timeout=300,
        )
        if result.returncode == 0:
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
