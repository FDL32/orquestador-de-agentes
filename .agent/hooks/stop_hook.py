from __future__ import annotations

from pathlib import Path

from completion_common import (
    check_execution_summary,
    check_tasks_completed,
)


# Constants
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXEC_LOG = PROJECT_ROOT / ".agent" / "collaboration" / "execution_log.md"
WORK_PLAN = PROJECT_ROOT / ".agent" / "collaboration" / "work_plan.md"
REVIEW_QUEUE = PROJECT_ROOT / ".agent" / "collaboration" / "review_queue.md"


def check_all_phases_complete(log_status: str) -> bool:
    """Check if all phases are complete for the given log status."""
    if log_status.upper() in {"READY_FOR_REVIEW", "COMPLETED"}:
        return True

    # For IN_PROGRESS, check if all tasks are completed
    return check_tasks_completed(WORK_PLAN, log_status)


def check_execution_log_complete(log_status: str) -> bool:
    """Check if execution log is complete."""
    return check_execution_summary(EXEC_LOG, log_status)


def check_tests_passing() -> bool:
    """Check if tests are passing."""
    from completion_common import check_quality_gates

    gates = check_quality_gates(PROJECT_ROOT)
    return gates.get("tests", False)
