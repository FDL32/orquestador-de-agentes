"""Test funcional de integraciÃƒÂ³n para el flujo de completitud y review handoff.

Valida el escenario real `APPROVED + READY_FOR_REVIEW` sin advisory espurio,
usando un sandbox repo-local estable para no tocar el estado real del proyecto.

@marker: integration
"""

import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest


def _rmtree_robust(path: Path) -> None:
    """rmtree que tolera archivos read-only de Windows (p.ej. packs de .git)."""

    def _handler(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if not path.exists():
        return
    try:
        shutil.rmtree(path, onexc=_handler)  # Python 3.12+
    except TypeError:
        shutil.rmtree(path, onerror=_handler)  # Python 3.10-3.11


PROJECT_ROOT = Path(__file__).parent.parent
SANDBOX_ROOT = PROJECT_ROOT / ".tmp" / "sandbox_completion_test"
SANDBOX_AGENT = SANDBOX_ROOT / ".agent"
SANDBOX_COLLAB = SANDBOX_AGENT / "collaboration"

# Archivos a copiar en el sandbox
# Incluye los modulos hermanos que agent_controller importa al cargar
# (closure_invariants, motor_checkpoint, state_validation): tras la
# descomposicion del monolito el sandbox dejo de copiarlos y los tests
# integration (deseleccionados por defecto) fallaban con ModuleNotFoundError.
FILES_TO_COPY = [
    PROJECT_ROOT / ".agent" / "agent_controller.py",
    PROJECT_ROOT / ".agent" / "closure_invariants.py",
    PROJECT_ROOT / ".agent" / "motor_checkpoint.py",
    PROJECT_ROOT / ".agent" / "scope_gate.py",
    PROJECT_ROOT / ".agent" / "state_validation.py",
    PROJECT_ROOT / ".agent" / "completion_checker.py",
    PROJECT_ROOT / ".agent" / "completion_common.py",
    PROJECT_ROOT / ".agent" / "hooks" / "stop_hook.py",
    PROJECT_ROOT / ".agent" / "hooks" / "__init__.py",
]

# Plantillas de archivos de estado
WORK_PLAN_TEMPLATE = """# Work Plan

## Ticket
- **ID:** TEST-000
- **TÃƒÂ­tulo:** Test de integraciÃƒÂ³n
- **Estado:** {status}
- **Prioridad:** MEDIUM
- **Asignado a:** Builder
"""

EXEC_LOG_TEMPLATE = """# Execution Log

## TEST-000
**Estado:** {status}
- Inicio: 23/04/2026
- Builder: test
- Alcance: test de integraciÃƒÂ³n
"""


@pytest.fixture(scope="function")
def sandbox() -> Generator[Path, None, None]:
    """Crea un sandbox repo-local limpio para el test.

    No usa %TEMP% para evitar problemas de permisos/rutas en Windows.
    El sandbox se limpia al finalizar el test.
    """
    # Limpiar si existe previamente
    _rmtree_robust(SANDBOX_ROOT)

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

        # AÃƒÂ±adir __init__.py vacÃƒÂ­o en .agent para imports
        agent_init = SANDBOX_AGENT / "__init__.py"
        agent_init.touch()

        # Runtime module is resolved via PYTHONPATH pointing to motor root

        # WOT-2026-003a: git-init the sandbox so it reflects a real checkout
        # (the destination CI checks out a git repo). The runtime bus
        # (events.jsonl) stays absent on purpose -- that is the scenario under
        # test: validate must not fail just because the gitignored bus is not
        # present in the checkout.
        _git = ["git", "-c", "user.email=test@example.com", "-c", "user.name=test"]
        subprocess.run([*_git, "init", "-q"], cwd=SANDBOX_ROOT, check=True)
        subprocess.run(
            [*_git, "add", "-A"], cwd=SANDBOX_ROOT, check=True, capture_output=True
        )
        subprocess.run(
            [*_git, "commit", "-q", "-m", "sandbox init"],
            cwd=SANDBOX_ROOT,
            check=True,
            capture_output=True,
        )

        yield SANDBOX_ROOT

    finally:
        # Limpiar sandbox al finalizar
        _rmtree_robust(SANDBOX_ROOT)


def write_sandbox_file(sandbox: Path, rel_path: str, content: str) -> None:
    """Escribe un archivo en el sandbox con contenido dado."""
    file_path = sandbox / rel_path
    file_path.parent.mkdir(exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def run_controller(sandbox: Path, *args: str) -> subprocess.CompletedProcess:
    """Ejecuta agent_controller.py dentro del sandbox."""
    controller_path = sandbox / ".agent" / "agent_controller.py"
    cmd = [sys.executable, str(controller_path), *args]
    env = dict(
        os.environ,
        PYTHONPATH=str(PROJECT_ROOT),
        AGENT_PROJECT_ROOT=str(sandbox.resolve()),
    )
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=sandbox,
        env=env,
        timeout=60,
    )


@pytest.mark.integration
def test_approved_ready_for_review_handoff(sandbox: Path) -> None:
    """Test del escenario principal: APPROVED + READY_FOR_REVIEW.

    Valida que:
    1. El controller devuelve MANAGER / REVIEW_WORK
    2. No hay advisory espurio de completitud
    3. WOT-2026-003a: con el bus runtime ausente (checkout/CI), validate NO
       falla; las invariantes del bus se reportan como warnings no verificables.
    """
    # Preparar estado de ejemplo sano
    write_sandbox_file(
        sandbox,
        ".agent/collaboration/work_plan.md",
        WORK_PLAN_TEMPLATE.format(status="APPROVED"),
    )

    write_sandbox_file(
        sandbox,
        ".agent/collaboration/execution_log.md",
        EXEC_LOG_TEMPLATE.format(status="READY_FOR_REVIEW"),
    )

    write_sandbox_file(
        sandbox,
        ".agent/collaboration/notifications.md",
        "# Registro de Notificaciones\n",
    )
    write_sandbox_file(sandbox, ".agent/collaboration/TURN.md", "")
    write_sandbox_file(
        sandbox, ".agent/collaboration/review_queue.md", "# Cola de revisiones\n"
    )

    # 1. Ejecutar controller en modo JSON y force
    result = run_controller(sandbox, "--json", "--force", "--skip-gates")
    assert result.returncode == 0, f"Controller fallÃƒÂ³: {result.stderr}"

    # Parsear respuesta JSON: capturar todo desde el primer '{' hasta el ÃƒÂºltimo '}'
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
    assert "\u26a0\ufe0f" not in result.stdout
    assert "\u274c" not in result.stdout

    # 2. Ejecutar validacion
    validate_result = run_controller(sandbox, "--validate", "--json", "--force")
    # WOT-2026-003a: el sandbox no siembra el bus runtime (events.jsonl es
    # gitignored), igual que un checkout fresco / CI. Las invariantes que
    # dependen del bus son NO VERIFICABLES en ese contexto, no violadas: deben
    # reportarse como warnings, no como errores. Por tanto validate NO falla.
    assert validate_result.returncode == 0, (
        f"validate no debe fallar por bus ausente: {validate_result.stderr}\n{validate_result.stdout}"
    )

    try:
        validate_output = json.loads(validate_result.stdout.strip())
    except json.JSONDecodeError:
        print(f"STDOUT:\n{validate_result.stdout}")
        print(f"STDERR:\n{validate_result.stderr}")
        raise

    # Sin errores de ninguna categoria: la invariante del bus es no verificable
    # (bus ausente en el checkout), no violada -> no debe contribuir errores.
    total_errors = sum(len(v) for v in validate_output["errors"].values())
    assert total_errors == 0, (
        f"validate no debe tener errores: {validate_output['errors']}"
    )
    assert "invariants" not in validate_output["errors"], validate_output["errors"]
    # Las invariantes del bus quedan como warnings 'no verificable'.
    assert any(
        "Cannot verify BUILDER_EXIT" in w
        for w in validate_output["warnings"].get("invariants", [])
    ), validate_output["warnings"]
    assert validate_output["warnings"]["bus_drift"] == [
        "No STATE_CHANGED event found in bus for ticket TEST-000"
    ]


@pytest.mark.integration
def test_in_progress_does_not_pass_review(sandbox: Path) -> None:
    """Validar que IN_PROGRESS no pasa a REVIEW_WORK."""
    write_sandbox_file(
        sandbox,
        ".agent/collaboration/work_plan.md",
        WORK_PLAN_TEMPLATE.format(status="APPROVED"),
    )

    write_sandbox_file(
        sandbox,
        ".agent/collaboration/execution_log.md",
        EXEC_LOG_TEMPLATE.format(status="IN_PROGRESS"),
    )

    write_sandbox_file(
        sandbox,
        ".agent/collaboration/notifications.md",
        "# Registro de Notificaciones\n",
    )
    write_sandbox_file(sandbox, ".agent/collaboration/TURN.md", "")
    write_sandbox_file(
        sandbox, ".agent/collaboration/review_queue.md", "# Cola de revisiones\n"
    )

    result = run_controller(sandbox, "--json", "--force", "--skip-gates")
    assert result.returncode == 0

    stdout = result.stdout.strip()
    start = stdout.find("{")
    end = stdout.rfind("}") + 1
    json_content = stdout[start:end]
    output = json.loads(json_content)
    assert output["role"] == "BUILDER"
    assert output["action_type"] == "IMPLEMENT"
