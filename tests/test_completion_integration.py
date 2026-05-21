"""Test funcional de integraciÃ³n para el flujo de completitud y review handoff.

Valida el escenario real `APPROVED + READY_FOR_REVIEW` sin advisory espurio,
usando un sandbox repo-local estable para no tocar el estado real del proyecto.

@marker: integration
"""

import json
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Generator

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
SANDBOX_ROOT = PROJECT_ROOT / ".tmp" / "sandbox_completion_test"
SANDBOX_AGENT = SANDBOX_ROOT / ".agent"
SANDBOX_COLLAB = SANDBOX_AGENT / "collaboration"

# Archivos a copiar en el sandbox
FILES_TO_COPY = [
    PROJECT_ROOT / ".agent" / "agent_controller.py",
    PROJECT_ROOT / ".agent" / "completion_checker.py",
    PROJECT_ROOT / ".agent" / "completion_common.py",
    PROJECT_ROOT / ".agent" / "hooks" / "stop_hook.py",
    PROJECT_ROOT / ".agent" / "hooks" / "__init__.py",
]

# Plantillas de archivos de estado
WORK_PLAN_TEMPLATE = """# Work Plan

## Ticket
- **ID:** TEST-000
- **TÃ­tulo:** Test de integraciÃ³n
- **Estado:** {status}
- **Prioridad:** MEDIUM
- **Asignado a:** Builder
"""

EXEC_LOG_TEMPLATE = """# Execution Log

## TEST-000
**Estado:** {status}
- Inicio: 23/04/2026
- Builder: test
- Alcance: test de integraciÃ³n
"""


@pytest.fixture(scope="function")
def sandbox() -> Generator[Path, None, None]:
    """Crea un sandbox repo-local limpio para el test.

    No usa %TEMP% para evitar problemas de permisos/rutas en Windows.
    El sandbox se limpia al finalizar el test.
    """
    # Limpiar si existe previamente
    if SANDBOX_ROOT.exists():
        shutil.rmtree(SANDBOX_ROOT)

    try:
        # Crear estructura
        SANDBOX_COLLAB.mkdir(parents=True, exist_ok=True)
        (SANDBOX_AGENT / "hooks").mkdir(exist_ok=True)

        # Copiar archivos del sistema real
        for src_path in FILES_TO_COPY:
            dst_path = SANDBOX_AGENT / src_path.relative_to(PROJECT_ROOT / ".agent")
            dst_path.parent.mkdir(exist_ok=True)
            shutil.copy2(src_path, dst_path)

        # Asegurar que __init__.py existe en hooks
        hooks_init = SANDBOX_AGENT / "hooks" / "__init__.py"
        if not hooks_init.exists():
            hooks_init.touch()

        # AÃ±adir __init__.py vacÃ­o en .agent para imports
        agent_init = SANDBOX_AGENT / "__init__.py"
        agent_init.touch()

        yield SANDBOX_ROOT

    finally:
        # Limpiar sandbox al finalizar
        if SANDBOX_ROOT.exists():
            shutil.rmtree(SANDBOX_ROOT)


def write_sandbox_file(sandbox: Path, rel_path: str, content: str) -> None:
    """Escribe un archivo en el sandbox con contenido dado."""
    file_path = sandbox / rel_path
    file_path.parent.mkdir(exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def run_controller(sandbox: Path, *args: str) -> subprocess.CompletedProcess:
    """Ejecuta agent_controller.py dentro del sandbox."""
    controller_path = sandbox / ".agent" / "agent_controller.py"
    cmd = [sys.executable, str(controller_path), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=sandbox,
        timeout=60,
    )


@pytest.mark.integration
def test_approved_ready_for_review_handoff(sandbox: Path) -> None:
    """Test del escenario principal: APPROVED + READY_FOR_REVIEW.

    Valida que:
    1. El controller devuelve MANAGER / REVIEW_WORK
    2. No hay advisory espurio de completitud
    3. La validaciÃ³n devuelve arrays vacÃ­os
    """
    # Preparar estado de ejemplo sano
    write_sandbox_file(
        sandbox,
        ".agent/collaboration/work_plan.md",
        WORK_PLAN_TEMPLATE.format(status="APPROVED")
    )

    write_sandbox_file(
        sandbox,
        ".agent/collaboration/execution_log.md",
        EXEC_LOG_TEMPLATE.format(status="READY_FOR_REVIEW")
    )

    write_sandbox_file(sandbox, ".agent/collaboration/notifications.md", "# Registro de Notificaciones\n")
    write_sandbox_file(sandbox, ".agent/collaboration/TURN.md", "")
    write_sandbox_file(sandbox, ".agent/collaboration/review_queue.md", "# Cola de revisiones\n")

    # 1. Ejecutar controller en modo JSON y force
    result = run_controller(sandbox, "--json", "--force")
    assert result.returncode == 0, f"Controller fallÃ³: {result.stderr}"

    # Parsear respuesta JSON: capturar todo desde el primer '{' hasta el Ãºltimo '}'
    try:
        stdout = result.stdout.strip()
        start = stdout.find("{")
        end = stdout.rfind("}") + 1
        json_content = stdout[start:end]
        output = json.loads(json_content)
    except (json.JSONDecodeError, ValueError):
        print(f"STDOUT:\n{result.stdout}")
        print(f"STDERR:\n{result.stderr}")
        raise

    # Validar que devuelve MANAGER / REVIEW_WORK
    assert output["role"] == "MANAGER"
    assert output["action_type"] == "REVIEW_WORK"
    assert output["log_status"] == "READY_FOR_REVIEW"
    assert output["plan_status"] == "APPROVED"

    # Validar que no hay advisory espurio en la salida
    assert "advisory" not in result.stdout.lower()
    assert "completitud" not in result.stdout.lower()
    assert "âš ï¸" not in result.stdout
    assert "âŒ" not in result.stdout

    # 2. Ejecutar validaciÃ³n
    validate_result = run_controller(sandbox, "--validate", "--json", "--force")
    assert validate_result.returncode == 0, f"ValidaciÃ³n fallÃ³: {validate_result.stderr}"

    try:
        validate_output = json.loads(validate_result.stdout.strip())
    except json.JSONDecodeError:
        print(f"STDOUT:\n{validate_result.stdout}")
        print(f"STDERR:\n{validate_result.stderr}")
        raise

    # Validar que todos los arrays estÃ¡n vacÃ­os (sin errores)
    assert len(validate_output["work_plan.md"]) == 0
    assert len(validate_output["execution_log.md"]) == 0
    assert len(validate_output["notifications.md"]) == 0
    assert len(validate_output["TURN.md"]) == 0
    assert len(validate_output["consistency"]) == 0
    assert len(validate_output["warnings"]) == 0


@pytest.mark.integration
def test_in_progress_does_not_pass_review(sandbox: Path) -> None:
    """Validar que IN_PROGRESS no pasa a REVIEW_WORK."""
    write_sandbox_file(
        sandbox,
        ".agent/collaboration/work_plan.md",
        WORK_PLAN_TEMPLATE.format(status="APPROVED")
    )

    write_sandbox_file(
        sandbox,
        ".agent/collaboration/execution_log.md",
        EXEC_LOG_TEMPLATE.format(status="IN_PROGRESS")
    )

    write_sandbox_file(sandbox, ".agent/collaboration/notifications.md", "# Registro de Notificaciones\n")
    write_sandbox_file(sandbox, ".agent/collaboration/TURN.md", "")
    write_sandbox_file(sandbox, ".agent/collaboration/review_queue.md", "# Cola de revisiones\n")

    result = run_controller(sandbox, "--json", "--force")
    assert result.returncode == 0

    stdout = result.stdout.strip()
    start = stdout.find("{")
    end = stdout.rfind("}") + 1
    json_content = stdout[start:end]
    output = json.loads(json_content)
    assert output["role"] == "BUILDER"
    assert output["action_type"] == "IMPLEMENT"
