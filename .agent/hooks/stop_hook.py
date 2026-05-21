"""
Stop hook for completion verification.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""
from __future__ import annotations

from pathlib import Path

from completion_common import (
    check_execution_summary,
    check_tasks_completed,
)


# WP-2026-122: Deferred path resolution via runtime.project_root
try:
    from runtime.project_root import get_collab_dir, resolve_project_root
except ImportError:
    # Fallback if runtime.project_root not available
    get_collab_dir = None
    resolve_project_root = None

class _LazyPath:
    def __init__(self, resolver):
        self._resolver = resolver

    def resolve(self) -> Path:
        return self._resolver()

    def __truediv__(self, other):
        return self.resolve() / other

    def __getattr__(self, name: str):
        return getattr(self.resolve(), name)

    def __fspath__(self) -> str:
        return str(self.resolve())

    def __str__(self) -> str:
        return str(self.resolve())


def _collab_dir() -> Path:
    if get_collab_dir is not None:
        return get_collab_dir()
    return Path(__file__).resolve().parent.parent / "collaboration"


def _project_root() -> Path:
    if resolve_project_root is not None:
        return resolve_project_root()
    return Path(__file__).resolve().parent.parent

# Deferred path resolution for collaboration files
COLLAB_DIR = _LazyPath(_collab_dir)
PROJECT_ROOT = _LazyPath(_project_root)
EXEC_LOG = _LazyPath(lambda: _collab_dir() / "execution_log.md")
WORK_PLAN = _LazyPath(lambda: _collab_dir() / "work_plan.md")
REVIEW_QUEUE = _LazyPath(lambda: _collab_dir() / "review_queue.md")


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
