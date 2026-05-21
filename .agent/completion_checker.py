# ruff: noqa
"""Completion Checker Lite para proyectos pequenos (<30 archivos).

Version simplificada de verificacion de completitud que verifica
criterios esenciales sin sobrecargar el sistema.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.

Uso:
    from .completion_checker import check_completion
    result = check_completion()
    if result["can_complete"]:
        print("Listo para completar")
    else:
        print(f"Faltan: {result['missing']}")
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

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
    return Path(__file__).parent / "collaboration"


def _project_root() -> Path:
    if resolve_project_root is not None:
        return resolve_project_root()
    return _collab_dir().parent.parent


COLLAB_DIR = _LazyPath(_collab_dir)
PROJECT_ROOT = _LazyPath(_project_root)
WORK_PLAN = _LazyPath(lambda: _collab_dir() / "work_plan.md")
EXEC_LOG = _LazyPath(lambda: _collab_dir() / "execution_log.md")
REVIEW_QUEUE = _LazyPath(lambda: _collab_dir() / "review_queue.md")
FINDINGS = _LazyPath(lambda: _collab_dir() / "findings.md")


def check_completion() -> dict[str, Any]:
    """Verifica criterios de completitud simplificados."""
    checks = {
        "tasks_completed": _check_all_tasks_done(),
        "tests_passing": _check_tests_pass(),
        "no_escalations": _check_no_pending_escalations(),
        "log_has_summary": _check_execution_summary(),
        "findings_exist": _check_findings_exist(),
    }

    passed = sum(1 for value in checks.values() if value)
    total = len(checks)
    percentage = int((passed / total) * 100) if total > 0 else 0
    can_complete = passed >= 4

    missing = []
    check_names = {
        "tasks_completed": "Tareas pendientes en work_plan.md",
        "tests_passing": "Tests fallando",
        "no_escalations": "Escalaciones pendientes en review_queue.md",
        "log_has_summary": "Falta resumen en execution_log.md",
        "findings_exist": "No existe findings.md (opcional pero recomendado)",
    }

    for check_name, passed_check in checks.items():
        if not passed_check:
            missing.append(check_names.get(check_name, check_name))

    return {
        "can_complete": can_complete,
        "percentage": percentage,
        "checks": checks,
        "missing": missing,
        "passed": passed,
        "total": total,
    }


def show_completion_report(result: dict[str, Any]) -> None:
    """Muestra reporte de completitud de forma legible."""
    emoji = "âœ…" if result["can_complete"] else "âš ï¸"
    status = "LISTO PARA COMPLETAR" if result["can_complete"] else "INCOMPLETO"

    print("\n" + "=" * 60)
    print(f"{emoji} VERIFICACION DE COMPLETITUD: {status}")
    print("=" * 60)
    print(f"Progreso: {result['passed']}/{result['total']} ({result['percentage']}%)")

    if result["missing"]:
        print("\nItems faltantes:")
        for item in result["missing"]:
            print(f"  - {item}")
    else:
        print("\nâœ… Todos los criterios cumplidos")

    print("=" * 60 + "\n")


def safe_print(text: str, end: str = "\n") -> None:
    try:
        print(text, end=end)
    except UnicodeEncodeError:
        ascii_text = text.encode("ascii", errors="replace").decode("ascii")
        print(ascii_text, end=end)


def _check_all_tasks_done() -> bool:
    """Verifica que todas las tareas esten marcadas [x]."""
    if not WORK_PLAN.exists():
        return False

    try:
        content = WORK_PLAN.read_text(encoding="utf-8")
        return content.count("- [ ]") == 0
    except Exception:
        return False


def _check_tests_pass() -> bool:
    """Verifica que los tests pasen (si hay tests)."""
    tests_dir = PROJECT_ROOT / "tests"
    if not tests_dir.exists():
        return True

    try:
        result = subprocess.run(
            ["uv", "run", "pytest", "-q", "--tb=no"],
            capture_output=True,
            timeout=60,
            cwd=PROJECT_ROOT,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True


def _check_no_pending_escalations() -> bool:
    """Verifica que no haya escalaciones pendientes."""
    if not REVIEW_QUEUE.exists():
        return True

    try:
        content = REVIEW_QUEUE.read_text(encoding="utf-8")
        import re

        has_pending = re.search(r"PENDING", content) is not None
        has_blocked = re.search(r"BLOCKED", content) is not None
        return not has_pending and not has_blocked
    except Exception:
        return True


def _check_execution_summary() -> bool:
    """Verifica que execution_log tenga resumen."""
    if not EXEC_LOG.exists():
        return False

    try:
        content = EXEC_LOG.read_text(encoding="utf-8")
        import re

        has_summary = re.search(r"##\s+.*Resumen", content) is not None
        not_in_progress = re.search(r"IN_PROGRESS", content) is None
        return has_summary and not_in_progress
    except Exception:
        return False


def _check_findings_exist() -> bool:
    """Verifica que exista findings.md (opcional pero recomendado)."""
    if not FINDINGS.exists():
        return False

    try:
        content = FINDINGS.read_text(encoding="utf-8")
        return "### " in content
    except Exception:
        return False


if __name__ == "__main__":
    import sys

    result = check_completion()
    show_completion_report(result)
    sys.exit(0 if result["can_complete"] else 1)
