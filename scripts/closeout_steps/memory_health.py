"""Memory-health closeout step (WOT-2026-089e, P0).

Runs `scripts/check_memory_health.py` on the destination AND the motor roots at every
`--session-close`, so the optimization triggers of the close prompt (Block 4.0) are
computed by a path that runs on its own instead of by an agent remembering to do it.
Before this step the 4.0 was optional prose with no declared root: it measured the
destination and the motor L1 reached 97 % noise unseen.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from scripts.session_closeout import StepResult


STEP_NAME = "memory_health"


def step_memory_health(
    project_root: Path,
    motor_root: Path | None,
    *,
    run_script_fn,
    step_result_cls: type[StepResult],
) -> StepResult:
    """Measure memory health on both roots; WARN (never FAIL) when a trigger fires.

    Before: `project_root` is the destination; `motor_root` is the resolved motor or
        None (then only the destination is measured).
    During: read-only (the script only reads); it also runs in dry-run mode.
    After: PASS with the denominators when nothing fires; WARN naming each fired
        trigger, its root and the exact command when something does. Never blocking:
        the thresholds are knobs, not calibrated values.
    """
    args = ["--project-root", str(project_root), "--json"]
    if motor_root is not None:
        args += ["--motor-root", str(motor_root)]
    command = "python scripts/check_memory_health.py " + " ".join(
        a for a in args if a != "--json"
    )
    try:
        result = run_script_fn(
            "check_memory_health.py", args, project_root, timeout=120
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return step_result_cls(
            name=STEP_NAME,
            status="WARN",
            detail=f"Memory health could not run: {exc}",
        )
    if result.returncode != 0:
        return step_result_cls(
            name=STEP_NAME,
            status="WARN",
            detail=f"Memory health exited {result.returncode}: {result.stderr[:300]}",
        )
    try:
        measures = json.loads(result.stdout)
    except json.JSONDecodeError:
        return step_result_cls(
            name=STEP_NAME,
            status="WARN",
            detail="Memory health output is not valid JSON; trigger state unknown",
        )

    fired = [
        f"{label} ({trig['id']}) {trig['detail']}"
        for label, measure in measures.items()
        for trig in measure["triggers"]
        if trig["fired"]
    ]
    if fired:
        return step_result_cls(
            name=STEP_NAME,
            status="WARN",
            detail=(
                "; ".join(fired)
                + f". Apply prompts/memory_optimization.md. Re-measure: {command}"
            ),
        )
    summary = "; ".join(
        f"{label}: L1 {m['l1']['parsed']} entries (noise {m['l1']['noise']}), "
        f"L2 {m['l2']['rules']}/{m['l2']['max_rules']}"
        for label, m in measures.items()
    )
    return step_result_cls(name=STEP_NAME, status="PASS", detail=summary)
