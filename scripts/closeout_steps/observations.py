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


def _resolve_upstream_learnings_path(project_root: Path) -> Path:
    """Resolve UPSTREAM_LEARNINGS.md locally or via motor_link fallback."""
    path = project_root / ".agent" / "runtime" / "memory" / "UPSTREAM_LEARNINGS.md"
    if path.exists():
        return path
    try:
        from runtime.motor_link import resolve_motor_root

        motor_root = resolve_motor_root(project_root)
        if motor_root is not None:
            candidate = (
                motor_root / ".agent" / "runtime" / "memory" / "UPSTREAM_LEARNINGS.md"
            )
            if candidate.exists():
                return candidate
    except ImportError:
        pass
    return path


def step_upstream_learnings_ttl(
    project_root: Path,
    *,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Warn about pending upstream learnings whose TTL is about to expire.

    UPSTREAM_LEARNINGS.md entries under '## Pendientes de revision' carry a
    'ttl_wps: N' counter decremented by man-session-closeout. Without an
    automatic consumer they used to expire silently; this step surfaces
    entries with ttl_wps <= 1 (numeric) so the human can triage them
    before archival.
    """
    import re

    path = _resolve_upstream_learnings_path(project_root)
    if not path.exists():
        return step_result_cls(
            name="upstream_learnings_ttl",
            status="SKIP",
            detail="UPSTREAM_LEARNINGS.md not present",
        )
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return step_result_cls(
            name="upstream_learnings_ttl",
            status="WARN",
            detail=f"Could not read UPSTREAM_LEARNINGS.md: {exc}",
        )

    pending_section = content.split("## Pendientes de revision", 1)
    if len(pending_section) < 2:
        return step_result_cls(
            name="upstream_learnings_ttl",
            status="PASS",
            detail="No 'Pendientes de revision' section",
        )
    # Stop at the next H2 section if present
    pending = re.split(r"\n## ", pending_section[1], maxsplit=1)[0]

    expiring: list[str] = []
    for match in re.finditer(r"^### (.+?)$", pending, flags=re.MULTILINE):
        header = match.group(1)
        ttl_match = re.search(r"ttl_wps:\s*(\d+)", header)
        if ttl_match and int(ttl_match.group(1)) <= 1:
            expiring.append(header.strip()[:80])

    if expiring:
        return step_result_cls(
            name="upstream_learnings_ttl",
            status="WARN",
            detail=(
                f"{len(expiring)} pending learning(s) with ttl_wps <= 1 "
                f"(triage before they expire): {expiring[:3]}"
            ),
        )
    return step_result_cls(
        name="upstream_learnings_ttl",
        status="PASS",
        detail="No pending learnings near TTL expiry",
    )
