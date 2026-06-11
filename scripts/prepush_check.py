#!/usr/bin/env python3
"""Pre-push Check - canonical delivery preflight wrapper.

Before (Pre-condiciones):
    - El repositorio Git debe existir en el directorio actual o especificado.
    - El usuario invoca este script antes de `git push` como verificacion unica.
    - Los archivos de configuracion (.pre-commit-config.yaml) deben existir.

During (Proceso y Recursos):
    - Ejecuta en secuencia fija:
      (1) delivery_hygiene_check.run_delivery_hygiene_check()
      (2) uv run ruff check .
      (3) uv run ruff format --check .
      (4) agent_controller --validate --json --force
      (5) git status --short
    - Ejecuta skills/validate_all.py de forma informacional (no bloqueante).
    - Cada check imprime estado OK/FAIL con diagnostico legible.
    - No modifica archivos; solo verifica y reporta.

After (Post-condiciones y Errores):
    - Retorna exit code 0 si los cinco checks bloqueantes pasan.
    - Retorna exit code 1 si algun check bloqueante falla.
    - git status --short no debe mostrar cambios tras la ejecucion.
    - skills/validate_all.py se ejecuta pero no afecta el exit code.
    - Excepciones: subprocess.CalledProcessError si algun comando falla,
      FileNotFoundError si falta algun archivo requerido.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple


# Bootstrap: motor root must be on sys.path so `runtime.*` imports resolve
# even when this script runs with cwd inside a destination workspace.
_MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))


# Global noqa for S603 - all subprocess calls use hardcoded command lists
# ruff: noqa: S603


class CheckResult(NamedTuple):
    """Resultado de un check individual."""

    name: str
    passed: bool
    output: str
    is_blocking: bool = True


def _configure_stdio() -> None:
    """Configura stdout/stderr para no fallar por encoding en Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")


def run_subprocess_check(
    cmd: list[str],
    name: str,
    project_root: Path,
    capture_output: bool = True,
) -> CheckResult:
    """Ejecuta un comando de verificacion y retorna su resultado.

    Args:
        cmd: Lista de argumentos del comando a ejecutar.
        name: Nombre descriptivo del check para el reporte.
        project_root: Raiz del proyecto donde ejecutar el comando.
        capture_output: Si True, captura stdout/stderr para diagnostico.

    Returns:
        CheckResult con nombre, estado, salida y si es bloqueante.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=capture_output,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        passed = result.returncode == 0
        output = (result.stdout or "") + (result.stderr or "") if capture_output else ""
    except FileNotFoundError as e:
        passed = False
        output = f"Comando no encontrado: {e}"
    except Exception as e:
        passed = False
        output = f"Error ejecutando comando: {e}"

    return CheckResult(name=name, passed=passed, output=output, is_blocking=True)


def run_delivery_hygiene_check(project_root: Path) -> CheckResult:
    """Ejecuta el check de higiene de entrega.

    Args:
        project_root: Raiz del proyecto donde ejecutar el check.

    Returns:
        CheckResult con el estado de la higiene de entrega.
    """
    try:
        # Add project root to sys.path to import scripts.delivery_hygiene_check
        import sys

        sys.path.insert(0, str(project_root))

        import io
        from contextlib import redirect_stdout

        # Import as package module (scripts.delivery_hygiene_check)
        from scripts.delivery_hygiene_check import run_delivery_hygiene_check

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = run_delivery_hygiene_check(project_root=project_root)

        output = f.getvalue()
        passed = exit_code == 0

        return CheckResult(
            name="Delivery Hygiene Check",
            passed=passed,
            output=output,
            is_blocking=True,
        )
    except ImportError as e:
        return CheckResult(
            name="Delivery Hygiene Check",
            passed=False,
            output=f"Error importando delivery_hygiene_check: {e}",
            is_blocking=True,
        )
    except Exception as e:
        return CheckResult(
            name="Delivery Hygiene Check",
            passed=False,
            output=f"Error ejecutando delivery_hygiene_check: {e}",
            is_blocking=True,
        )


def _ruff_exclude_args() -> list[str]:
    """Return --extend-exclude arguments for directories outside operational scope.

    _backups/ and uv-cache/ are outside the operational scope of the motor
    and should not be linted or formatted by ruff.
    """
    return [
        "--extend-exclude",
        "_backups/*,uv-cache/*,.agent/runtime/uv-cache/*",
    ]


def run_ruff_check(project_root: Path) -> CheckResult:
    """Ejecuta ruff check en el proyecto.

    Args:
        project_root: Raiz del proyecto donde ejecutar ruff.

    Returns:
        CheckResult con el estado del check de ruff.
    """
    return run_subprocess_check(
        cmd=["uv", "run", "ruff", "check", ".", *_ruff_exclude_args()],
        name="Ruff Check",
        project_root=project_root,
    )


def run_ruff_format_check(project_root: Path) -> CheckResult:
    """Ejecuta ruff format --check en el proyecto.

    Args:
        project_root: Raiz del proyecto donde ejecutar ruff.

    Returns:
        CheckResult con el estado del check de formato.
    """
    return run_subprocess_check(
        cmd=["uv", "run", "ruff", "format", "--check", "."],
        name="Ruff Format Check",
        project_root=project_root,
    )


def run_agent_controller_validate(project_root: Path) -> CheckResult:
    """Ejecuta agent_controller --validate --json --force.

    Resuelve el controller via motor_link (Model B). Si no hay motor link,
    usa .agent/agent_controller.py local como fallback.

    Args:
        project_root: Raiz del proyecto donde ejecutar el controller.

    Returns:
        CheckResult con el estado de la validacion del controller.
    """
    controller_path = None
    try:
        from runtime.motor_link import resolve_motor_controller

        resolved = resolve_motor_controller(project_root)
        if resolved:
            controller_path = str(resolved)
    except ImportError:
        pass

    if controller_path is None:
        controller_path = ".agent/agent_controller.py"

    return run_subprocess_check(
        cmd=[
            sys.executable,
            controller_path,
            "--validate",
            "--json",
            "--force",
            "--project-root",
            str(project_root),
        ],
        name="Agent Controller Validate",
        project_root=project_root,
    )


def run_git_status_check(project_root: Path) -> CheckResult:
    """Ejecuta git status --short y verifica que el arbol este limpio.

    WT-2026-215: ejecuta git sobre motor_root (repositorio del motor), no
    sobre project_root (workspace destino). Si motor_root no es resoluble,
    reporta un WARN no bloqueante en lugar de FAIL, para soportar la
    arquitectura workspace activo + motor portable.

    Args:
        project_root: Raiz del proyecto (usado para resolver motor_root).

    Returns:
        CheckResult con passed=True si no hay cambios en el arbol.
    """
    try:
        from runtime.motor_link import resolve_motor_root

        motor_root = resolve_motor_root(project_root)
        if motor_root is None:
            return CheckResult(
                name="Git Status Check",
                passed=True,
                output="motor_root no resoluble (motor_destination_link.json ausente); "
                "check de git saltado (no bloqueante)",
                is_blocking=False,
            )
        result = subprocess.run(
            ["git", "status", "--short"],  # noqa: S607
            cwd=motor_root,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        # If git command itself fails, report as non-blocking WARN for
        # workspaces that are not git repos (e.g. z_scripts/ in Model B).
        if result.returncode != 0:
            return CheckResult(
                name="Git Status Check",
                passed=True,
                output=f"Workspace no-repo (git exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}",
                is_blocking=False,
            )

        output = result.stdout.strip()
        passed = not output
        output = f"Arbol sucio detectado:\n{output}" if output else "Arbol Git limpio"

        return CheckResult(
            name="Git Status Check",
            passed=passed,
            output=output,
            is_blocking=True,
        )
    except FileNotFoundError:
        return CheckResult(
            name="Git Status Check",
            passed=True,
            output="Comando 'git' no encontrado en PATH (workspace no-repo tolerado)",
            is_blocking=False,
        )


def run_validate_all(project_root: Path) -> CheckResult:
    """Ejecuta skills/validate_all.py de forma informacional.

    Args:
        project_root: Raiz del proyecto donde ejecutar la validacion.

    Returns:
        CheckResult con el estado (siempre no-bloqueante).
    """
    result = run_subprocess_check(
        cmd=[sys.executable, "skills/validate_all.py"],
        name="Validate All (informacional)",
        project_root=project_root,
    )
    # Este check es informacional, no bloquea el exit code
    return CheckResult(
        name=result.name,
        passed=result.passed,
        output=result.output,
        is_blocking=False,
    )


def run_preflight_check(
    project_root: Path | None = None,
) -> int:
    """Ejecuta todos los checks de preflight de entrega.

    Args:
        project_root: Raiz del proyecto. Si None, usa el directorio actual.

    Returns:
        Exit code: 0 si todos los checks bloqueantes pasan, 1 si alguno falla.
    """
    _configure_stdio()

    if project_root is None:
        project_root = Path.cwd()

    results: list[CheckResult] = []

    # Secuencia fija de checks bloqueantes
    # 1. Delivery Hygiene Check
    results.append(run_delivery_hygiene_check(project_root))

    # 2. Ruff Check
    results.append(run_ruff_check(project_root))

    # 3. Ruff Format Check
    results.append(run_ruff_format_check(project_root))

    # 4. Agent Controller Validate
    results.append(run_agent_controller_validate(project_root))

    # 5. Git Status Check
    results.append(run_git_status_check(project_root))

    # Check informacional (no bloqueante)
    results.append(run_validate_all(project_root))

    # Imprimir reporte
    print("=" * 60)
    print("PREFLIGHT DE ENTREGA - Reporte")
    print("=" * 60)
    print()

    blocking_failed = False

    for result in results:
        status = "[OK]" if result.passed else "[FAIL]"
        blocking_marker = "" if result.is_blocking else " (informacional)"
        print(f"{status} {result.name}{blocking_marker}")

        if not result.passed and result.output:
            # Mostrar solo las primeras lineas del output si hay error
            lines = result.output.strip().split("\n")
            for line in lines[:10]:  # Mostrar max 10 lineas
                print(f"      {line}")
            if len(lines) > 10:
                print(f"      ... y {len(lines) - 10} lineas mas")

        if not result.passed and result.is_blocking:
            blocking_failed = True

        print()

    print("=" * 60)
    if blocking_failed:
        print("PREFLIGHT BLOQUEADO: corrija los problemas antes de push")
        print("Ejecute la pasada mutadora manualmente si hace falta:")
        print("  uv run pre-commit run --all-files --hook-stage pre-commit")
        print("Luego vuelva a ejecutar este preflight")
    else:
        print("PREFLIGHT EXITOSO: arbol listo para push")
    print("=" * 60)

    return 0 if not blocking_failed else 1


def main() -> int:
    """Punto de entrada CLI."""
    _configure_stdio()

    parser = argparse.ArgumentParser(
        description="Pre-push Check - canonical delivery preflight wrapper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/prepush_check.py
    Ejecuta todos los checks de preflight en el directorio actual

  python scripts/prepush_check.py --project-root /ruta/al/proyecto
    Ejecuta los checks en un directorio especifico

Secuencia de checks (todos bloqueantes excepto validate_all):
  1. Delivery Hygiene Check (hooks mutadores, artefactos, arbol limpio)
  2. Ruff Check via `uv run ruff` (linting de Python)
  3. Ruff Format Check via `uv run ruff` (formato de codigo)
  4. Agent Controller Validate (validacion de tickets)
  5. Git Status Check (arbol sin cambios)
  6. Validate All (skills, informacional)

Si el preflight falla:
  - Ejecute la pasada mutadora manualmente: pre-commit run --hook-stage pre-commit
  - Corrija los errores reportados
  - Vuelva a ejecutar este preflight hasta que todos los checks pasen
""",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Raiz del proyecto (default: directorio actual)",
    )

    args = parser.parse_args()

    return run_preflight_check(project_root=args.project_root)


if __name__ == "__main__":
    sys.exit(main())
