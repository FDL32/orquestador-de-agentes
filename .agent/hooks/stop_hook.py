"""
Stop hook for completion verification.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
# Setup sys.path for runtime/ imports
import sys
from pathlib import Path

from completion_common import (
    check_execution_summary,
    check_tasks_completed,
)


_AGENT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _AGENT_DIR.parent
# Insert project root FIRST so runtime/ is importable
for _path in (str(_PROJECT_ROOT), str(_AGENT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from runtime.project_root import get_collab_dir, resolve_project_root  # noqa: E402


COLLAB_DIR = get_collab_dir()
PROJECT_ROOT = resolve_project_root()
EXEC_LOG = COLLAB_DIR / "execution_log.md"
WORK_PLAN = COLLAB_DIR / "work_plan.md"
REVIEW_QUEUE = COLLAB_DIR / "review_queue.md"


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
