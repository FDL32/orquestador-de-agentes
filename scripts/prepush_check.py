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
import os
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


def run_delivery_hygiene_check(
    project_root: Path,
    expected_artifacts: list[str] | None = None,
) -> CheckResult:
    """Ejecuta el check de higiene de entrega.

    WOT-2026-014a: the optional expected_artifacts param is forwarded to
    delivery_hygiene_check.run_delivery_hygiene_check so the closeout pre-push
    gate can forgive known runtime artifacts. Default None preserves current
    behavior (no forgiveness) for all non-closeout callers.

    Args:
        project_root: Raiz del proyecto donde ejecutar el check.
        expected_artifacts: Optional allowlist forwarded to check_git_tree_clean.
            Default None preserves current behavior (any dirty file fails).

    Returns:
        CheckResult con el estado de la higiene de entrega.
    """
    try:
        import io
        from contextlib import redirect_stdout

        # Destination-local scripts must not shadow the canonical motor gate.
        from scripts.delivery_hygiene_check import run_delivery_hygiene_check

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = run_delivery_hygiene_check(
                project_root=project_root,
                expected_artifacts=expected_artifacts,
            )

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

    Resuelve el controller via motor_link (topologia repo_motor + repo_destino).
    Si no hay motor link,
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
        # workspaces that are not git repos under external-motor topology.
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
    validate_all_path = _MOTOR_ROOT / "skills" / "validate_all.py"
    try:
        from runtime.motor_link import resolve_motor_root

        resolved_motor_root = resolve_motor_root(project_root)
        if resolved_motor_root is not None:
            candidate = resolved_motor_root / "skills" / "validate_all.py"
            if candidate.exists():
                validate_all_path = candidate
    except ImportError:
        pass

    result = run_subprocess_check(
        cmd=[sys.executable, str(validate_all_path)],
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


def run_backlog_contract_check(project_root: Path) -> CheckResult:
    """Gate bloqueante de cierre: la cola viva del backlog no tiene terminales.

    WOT-2026-015g: el contrato de cola viva (backlog.md) prohibe estados
    terminales (completed/done/closed/absorbed) en la tabla Vista rapida; deben
    archivarse a _archive/backlog_done.md. `validate_backlog` (en
    check_backlog_contract.py) YA detecta esto, pero hasta ahora ningun gate de
    --session-close lo invocaba: el archivado dependia de un paso manual que se
    omitio en 4 sesiones del 27-jun, dejando 10 completed en cola viva y el
    contract en rojo solo visible al ejecutarlo a mano.

    Este gate cierra ese hueco: se ejecuta SOLO en closeout-mode (la cola viva
    solo se valida al cerrar sesion, no en cada push). Si hay violaciones, el
    cierre se BLOQUEA (is_blocking=True) hasta archivar los terminales.

    Before: project_root apunta al repo_destino con .agent/collaboration/backlog.md.
    During: importa validate_backlog y lo aplica al backlog del destino.
    After: CheckResult passed=True si no hay violaciones; False (bloqueante) si las hay.
    """
    name = "Backlog Contract Check (closeout)"
    backlog = project_root / ".agent" / "collaboration" / "backlog.md"
    if not backlog.exists():
        # Sin backlog no hay cola viva que validar; no bloquea el cierre.
        return CheckResult(
            name=name,
            passed=True,
            output=f"No backlog.md at {backlog} (skipped)",
            is_blocking=True,
        )
    try:
        from scripts.check_backlog_contract import validate_backlog
    except ImportError:
        from check_backlog_contract import validate_backlog  # type: ignore[no-redef]
    violations = validate_backlog(backlog)
    if violations:
        detail = "\n".join(f"  - {v}" for v in violations)
        output = (
            f"{len(violations)} violation(s) in {backlog}:\n{detail}\n"
            "Archive terminal tickets to _archive/backlog_done.md before closing "
            "(see WOT-2026-015i)."
        )
        return CheckResult(name=name, passed=False, output=output, is_blocking=True)
    return CheckResult(
        name=name,
        passed=True,
        output="live queue contract holds",
        is_blocking=True,
    )


def run_contract_reconcile_check(project_root: Path) -> CheckResult:
    """WOT-2026-024e: frozen contracts in ticket_contracts.md with no scheduling
    row (the batch reads only backlog.md, so it can never execute them).

    The SCRIPT is fail-closed (check_contract_backlog_reconcile.find_orphans lists
    them). The WARN/FAIL verdict lives HERE: WARN by default (is_blocking=False,
    reports but does not fail the close), FAIL when CONTRACT_RECONCILE_STRICT=1
    (is_blocking=True). The toggle is what keeps this a real barrier (it CAN block
    on demand) rather than a never-blocks reporter (WOT-2026-024e / M20).
    """
    name = "Contract-Backlog Reconcile (WOT-2026-024e)"
    strict = os.environ.get("CONTRACT_RECONCILE_STRICT", "").strip() == "1"
    try:
        from scripts.check_contract_backlog_reconcile import find_orphans
    except ImportError:
        from check_contract_backlog_reconcile import (
            find_orphans,  # type: ignore[no-redef]
        )
    orphans = find_orphans(project_root)
    if orphans:
        detail = "\n".join(f"  - {t}" for t in orphans)
        mode = (
            "BLOCKING (CONTRACT_RECONCILE_STRICT=1)."
            if strict
            else "WARN only; set CONTRACT_RECONCILE_STRICT=1 to block."
        )
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(orphans)} frozen contract(s) with no scheduling row:\n{detail}\n"
                f"Materialize a backlog row for each (human action). {mode}"
            ),
            is_blocking=strict,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="every frozen contract has a scheduling row",
        is_blocking=strict,
    )


def run_preflight_check(
    project_root: Path | None = None,
    expected_artifacts: list[str] | None = None,
    closeout_mode: bool = False,
    skip_gates: bool = False,
) -> int:
    """Ejecuta todos los checks de preflight de entrega.

    WOT-2026-014a: the optional expected_artifacts param is forwarded to
    run_delivery_hygiene_check so the closeout pre-push gate can forgive known
    runtime artifacts. Default None preserves current behavior (no forgiveness).

    WOT-2026-015g: closeout_mode=True adds run_backlog_contract_check as a
    blocking gate so --session-close fails if the live backlog still holds
    terminal tickets. Default False preserves the general pre-push behavior
    (the live-queue contract is only enforced at session close).

    Args:
        project_root: Raiz del proyecto. Si None, usa el directorio actual.
        expected_artifacts: Optional allowlist forwarded to check_git_tree_clean.
            Default None preserves current behavior (any dirty file fails).
        closeout_mode: When True, enforce the live backlog contract as a blocking
            gate (session-close only). Default False leaves it off.
        skip_gates: WOT-2026-020i. When True, the checks STILL RUN and their
            results are printed, but a blocking failure no longer forces exit 1:
            the operator explicitly chose to close over pre-existing debt
            (--session-close --skip-gates --force). Default False preserves the
            blocking behavior. Never silences the report -- only its verdict.

    Returns:
        Exit code: 0 si todos los checks bloqueantes pasan, 1 si alguno falla
        (o siempre 0 con skip_gates, que degrada el veredicto a no-bloqueante).
    """
    _configure_stdio()

    if project_root is None:
        project_root = Path.cwd()

    results: list[CheckResult] = []

    # Secuencia fija de checks bloqueantes
    # 1. Delivery Hygiene Check
    results.append(run_delivery_hygiene_check(project_root, expected_artifacts))

    # 2. Ruff Check
    results.append(run_ruff_check(project_root))

    # 3. Ruff Format Check
    results.append(run_ruff_format_check(project_root))

    # 4. Agent Controller Validate
    results.append(run_agent_controller_validate(project_root))

    # 5. Git Status Check
    results.append(run_git_status_check(project_root))

    # 6. Backlog Contract Check (solo en cierre de sesion; bloqueante)
    if closeout_mode:
        results.append(run_backlog_contract_check(project_root))
        # 6b. Contract-Backlog Reconcile (WOT-2026-024e; WARN default, FAIL opt-in)
        results.append(run_contract_reconcile_check(project_root))

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

    _print_preflight_verdict(blocking_failed, skip_gates)

    if skip_gates:
        return 0
    return 0 if not blocking_failed else 1


def _print_preflight_verdict(blocking_failed: bool, skip_gates: bool) -> None:
    """Print the closing verdict banner (WOT-2026-020i extracted this to keep
    run_preflight_check under the complexity cap)."""
    print("=" * 60)
    if blocking_failed and skip_gates:
        # The operator asked to skip the gate verdict. Show the failures (never
        # silent) but degrade to non-blocking.
        print("PREFLIGHT CON FALLOS pero --skip-gates activo: cierre NO bloqueado")
        print("  (los fallos de arriba se ignoran por decision explicita del operador)")
    elif blocking_failed:
        print("PREFLIGHT BLOQUEADO: corrija los problemas antes de push")
        print("Ejecute la pasada mutadora manualmente si hace falta:")
        print("  uv run pre-commit run --all-files --hook-stage pre-commit")
        print("Luego vuelva a ejecutar este preflight")
    else:
        print("PREFLIGHT EXITOSO: arbol listo para push")
    print("=" * 60)


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
    parser.add_argument(
        "--closeout-mode",
        action="store_true",
        default=False,
        help=(
            "WOT-2026-014a: pass EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS allowlist to "
            "check_git_tree_clean. Only the closeout path should pass this flag; "
            "the general pre-push gate MUST NOT pass it (default behavior unchanged)."
        ),
    )
    parser.add_argument(
        "--skip-gates",
        action="store_true",
        default=False,
        help=(
            "WOT-2026-020i: run the checks and print the report, but degrade a "
            "blocking failure to non-blocking (exit 0). For an operator who "
            "explicitly chooses to close over pre-existing debt."
        ),
    )

    args = parser.parse_args()

    artifacts: list[str] | None = None
    if args.closeout_mode:
        from scripts.delivery_hygiene_check import EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS

        artifacts = EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS
    return run_preflight_check(
        project_root=args.project_root,
        expected_artifacts=artifacts,
        closeout_mode=args.closeout_mode,
        skip_gates=args.skip_gates,
    )


if __name__ == "__main__":
    sys.exit(main())
