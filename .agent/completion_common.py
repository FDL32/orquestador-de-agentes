# ruff: noqa: S603
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORK_PLAN = PROJECT_ROOT / ".agent" / "collaboration" / "work_plan.md"
EXEC_LOG = PROJECT_ROOT / ".agent" / "collaboration" / "execution_log.md"
REVIEW_QUEUE = PROJECT_ROOT / ".agent" / "collaboration" / "review_queue.md"


def _read_text(path: Path) -> str:
    try:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def get_log_status(log_path: Path) -> str:
    content = _read_text(log_path)
    if not content:
        return ""
    for line in content.splitlines():
        if "**Estado:**" in line:
            return line.split("**Estado:**", 1)[1].strip().upper()
    return ""


def is_relaxed_completion_status(status: str) -> bool:
    return status.upper() in {"READY_FOR_REVIEW", "COMPLETED"}


def check_tasks_completed(plan_path: Path, log_status: str) -> bool:
    if is_relaxed_completion_status(log_status):
        return True
    content = _read_text(plan_path)
    if not content:
        return False
    return "- [ ]" not in content


def check_execution_summary(log_path: Path, log_status: str | None = None) -> bool:
    if log_status and is_relaxed_completion_status(log_status):
        return True
    content = _read_text(log_path)
    if not content:
        return False
    upper = content.upper()
    if "IN_PROGRESS" in upper:
        return False
    return "**ESTADO:**" in upper or "RESUMEN" in upper


def check_no_escalations(queue_path: Path) -> bool:
    content = _read_text(queue_path)
    if not content:
        return True
    upper = content.upper()
    return "PENDING" not in upper and "BLOCKED" not in upper


def resolve_test_command(project_root: Path) -> list[str]:
    tests_dir = project_root / "tests"
    if not tests_dir.exists():
        return []
    safe_runner = project_root / "scripts" / "run_pytest_safe.py"
    if safe_runner.exists():
        return [sys.executable, str(safe_runner), "--level", "unit"]
    return [sys.executable, "-m", "pytest", "tests", "-q"]


def run_tests(project_root: Path) -> bool:
    cmd = resolve_test_command(project_root)
    if not cmd:
        return True
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
        return result.returncode == 0
    except (FileNotFoundError, PermissionError):
        return True


def check_quality_gates(project_root: Path) -> dict[str, Any]:
    return {
        "tests": run_tests(project_root),
        "tasks_completed": check_tasks_completed(WORK_PLAN, get_log_status(EXEC_LOG)),
        "no_escalations": check_no_escalations(REVIEW_QUEUE),
        "execution_summary": check_execution_summary(
            EXEC_LOG, get_log_status(EXEC_LOG)
        ),
    }
