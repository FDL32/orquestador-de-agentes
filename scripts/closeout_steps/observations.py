"""Observation closeout steps extracted from scripts.session_closeout.

This module owns the per-ticket observation pass and the memory consolidation
step that used to live in the session_closeout monolith.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from scripts.session_closeout import StepResult


def step_session_observations(
    project_root: Path,
    dry_run: bool,
    *,
    ticket_ids: list[str],
    close_timestamps: dict[str, str],
    run_script_fn,
    process_diagnostic_fn,
    step_result_cls: type[StepResult],
) -> list[StepResult]:
    """Run session_close_observations.py once per resolved ticket."""
    results: list[StepResult] = []
    if dry_run:
        results.extend(
            step_result_cls(
                name=f"observations:{tid}",
                status="SKIP",
                detail="Skipped in dry-run mode",
            )
            for tid in ticket_ids
        )
        return results

    sorted_tickets = sorted(
        ticket_ids, key=lambda ticket: close_timestamps.get(ticket, "")
    )

    for tid in sorted_tickets:
        try:
            result = run_script_fn(
                "session_close_observations.py",
                ["--ticket", tid],
                project_root,
                timeout=120,
            )
            if result.returncode == 0:
                results.append(
                    step_result_cls(
                        name=f"observations:{tid}",
                        status="PASS",
                        detail=f"Observations processed for {tid}",
                    )
                )
            else:
                detail = process_diagnostic_fn(result, limit=300)
                results.append(
                    step_result_cls(
                        name=f"observations:{tid}",
                        status="WARN",
                        detail=(
                            f"Observations script returned exit "
                            f"{result.returncode} for {tid}: {detail}"
                        ),
                    )
                )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:  # noqa: PERF203
            results.append(
                step_result_cls(
                    name=f"observations:{tid}",
                    status="WARN",
                    detail=f"Observations could not run for {tid}: {exc}",
                )
            )
    return results


def step_memory_consolidate(
    project_root: Path,
    dry_run: bool,
    *,
    run_script_fn,
    process_diagnostic_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Run memory_consolidate.py --verbose --apply."""
    if dry_run:
        return step_result_cls(
            name="memory_consolidate",
            status="SKIP",
            detail="Skipped in dry-run mode",
        )
    try:
        result = run_script_fn(
            "memory_consolidate.py",
            ["--verbose", "--apply"],
            project_root,
            timeout=120,
        )
        if result.returncode == 0:
            return step_result_cls(
                name="memory_consolidate",
                status="PASS",
                detail="Memory consolidated successfully",
            )
        return step_result_cls(
            name="memory_consolidate",
            status="WARN",
            detail=(
                f"Memory consolidate returned exit {result.returncode}: "
                f"{process_diagnostic_fn(result)}"
            ),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return step_result_cls(
            name="memory_consolidate",
            status="WARN",
            detail=f"Memory consolidate could not run: {exc}",
        )
