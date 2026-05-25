"""Test funcional de integración para agent_controller.py.

Sandbox bajo .tmp/ con nombres de directorio no ocultos:
  - Parchea la copia del controller: AGENT_DIR = SCRIPT_DIR (no .agent/).
  - Archivos de colaboración en agent/collaboration/ (no oculto).
  - Sin backup/restore. Sin acceso a .agent/collaboration real.
  - Compatible con Windows donde mkdir de directorios ocultos falla.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


_REAL_CONTROLLER = Path(__file__).parent.parent / ".agent" / "agent_controller.py"
_TMP_BASE = Path(__file__).parent.parent / ".tmp"
_SANDBOX_ROOT = _TMP_BASE / "controller_sandbox"

# Parche quirúrgico: hace que el controller copiado use SCRIPT_DIR como AGENT_DIR
# en lugar de PROJECT_ROOT / ".agent". Así toda la estructura queda en
# sandbox/agent/ (no oculto) y Windows no bloquea la creación de directorios.
_PATCH_FROM = 'AGENT_DIR = PROJECT_ROOT / ".agent"'
_PATCH_TO = "AGENT_DIR = SCRIPT_DIR"


# ---------------------------------------------------------------------------
# Fixture de sandbox
# ---------------------------------------------------------------------------


@pytest.fixture()
def sandbox():
    """Árbol temporal aislado bajo una raíz fija y segura en .tmp/.

    Estructura creada:
        .tmp/controller_sandbox/
        ├── agent/                  <- reemplaza a .agent/
        │   ├── agent_controller.py <- copia parcheada
        │   ├── collaboration/
        │   │   └── archive/
        │   └── context/
        └── (sin .git)
    """
    _TMP_BASE.mkdir(exist_ok=True)
    if _SANDBOX_ROOT.exists():
        shutil.rmtree(_SANDBOX_ROOT, ignore_errors=True)
    _SANDBOX_ROOT.mkdir(exist_ok=True)
    root = _SANDBOX_ROOT

    agent_dir = root / "agent"
    collab_dir = agent_dir / "collaboration"
    agent_dir.mkdir()
    collab_dir.mkdir()
    (collab_dir / "archive").mkdir()
    (agent_dir / "context").mkdir()

    patched_src = _REAL_CONTROLLER.read_text(encoding="utf-8").replace(
        _PATCH_FROM, _PATCH_TO
    )
    (agent_dir / "agent_controller.py").write_text(patched_src, encoding="utf-8")

    yield root, agent_dir, collab_dir
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(agent_dir: Path, root: Path, *args: str) -> dict | None:
    """Ejecuta el controller en el sandbox y devuelve el JSON parseado."""
    result = subprocess.run(
        [
            sys.executable,
            str(agent_dir / "agent_controller.py"),
            "--json",
            "--force",
            *args,
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return _parse_json(result.stdout)


def _parse_json(output: str) -> dict | None:
    """Extrae el primer objeto JSON del output del controller."""
    json_lines: list[str] = []
    in_json = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            in_json = True
            json_lines = [stripped]
        elif in_json:
            json_lines.append(stripped)
            if stripped.startswith("}"):
                break
    if json_lines:
        try:
            return json.loads("\n".join(json_lines))
        except json.JSONDecodeError:
            pass
    return None


def _plan(plan_id: str, status: str) -> str:
    return (
        "# Work Plan\n\n"
        "## Ticket\n"
        f"- **ID:** {plan_id}\n"
        "- **Titulo:** Test\n"
        f"- **Estado:** {status}\n"
        "- **Prioridad:** HIGH\n"
    )


def _log(status: str) -> str:
    return (
        "# Execution Log\n\n"
        "## TEST-001\n"
        f"- **Estado:** {status}\n"
        "- Inicio: 2026-04-22\n"
    )


def _notif() -> str:
    return "# Notifications\n\nSin notificaciones.\n"


# ---------------------------------------------------------------------------
# Tests de integración
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_approved_pending_returns_builder_implement(sandbox):
    """APPROVED + PENDING -> BUILDER / IMPLEMENT."""
    root, agent_dir, collab_dir = sandbox
    (collab_dir / "work_plan.md").write_text(
        _plan("TEST-001", "APPROVED"), encoding="utf-8"
    )
    (collab_dir / "execution_log.md").write_text(_log("PENDING"), encoding="utf-8")
    (collab_dir / "notifications.md").write_text(_notif(), encoding="utf-8")

    data = _run(agent_dir, root)

    assert data is not None, "No JSON en output del controller"
    assert data.get("role") == "BUILDER"
    assert data.get("action_type") == "IMPLEMENT"


@pytest.mark.integration
def test_completed_returns_manager_create_plan(sandbox):
    """COMPLETED -> MANAGER / CREATE_PLAN."""
    root, agent_dir, collab_dir = sandbox
    (collab_dir / "work_plan.md").write_text(
        _plan("TEST-001", "COMPLETED"), encoding="utf-8"
    )
    (collab_dir / "execution_log.md").write_text(_log("COMPLETED"), encoding="utf-8")
    (collab_dir / "notifications.md").write_text(_notif(), encoding="utf-8")

    data = _run(agent_dir, root)

    assert data is not None, "No JSON en output del controller"
    assert data.get("role") == "MANAGER"
    assert data.get("action_type") == "CREATE_PLAN"


@pytest.mark.integration
def test_validate_returns_empty_arrays(sandbox):
    """Estado sano -> --validate devuelve todos los arrays vacíos."""
    root, agent_dir, collab_dir = sandbox
    (collab_dir / "work_plan.md").write_text(
        _plan("TEST-001", "APPROVED"), encoding="utf-8"
    )
    (collab_dir / "execution_log.md").write_text(_log("PENDING"), encoding="utf-8")
    (collab_dir / "notifications.md").write_text(_notif(), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(agent_dir / "agent_controller.py"),
            "--validate",
            "--json",
            "--force",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    data = _parse_json(result.stdout)

    assert data is not None, "No JSON en output del controller"
    assert data.get("work_plan.md") == []
    assert data.get("execution_log.md") == []
    assert data.get("notifications.md") == []
    assert data.get("TURN.md") == []
    assert data.get("consistency") == []
    assert data.get("warnings") == []
