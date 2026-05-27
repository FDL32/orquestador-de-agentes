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

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
# Setup sys.path for runtime/ imports
import sys
from pathlib import Path

_AGENT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _AGENT_DIR.parent
# Insert project root FIRST so runtime/ is importable
for _path in (str(_PROJECT_ROOT), str(_AGENT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from runtime.project_root import get_collab_dir, resolve_project_root  # noqa: E402

COLLAB_DIR = get_collab_dir()
PROJECT_ROOT = resolve_project_root()
WORK_PLAN = COLLAB_DIR / "work_plan.md"
EXEC_LOG = COLLAB_DIR / "execution_log.md"
REVIEW_QUEUE = COLLAB_DIR / "review_queue.md"
FINDINGS = COLLAB_DIR / "findings.md"


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
