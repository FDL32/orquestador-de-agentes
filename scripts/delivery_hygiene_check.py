#!/usr/bin/env python3
"""Delivery Hygiene Check - pre-push no mutating preflight.

Before (Pre-condiciones):
    - El repositorio Git debe existir con un archivo `.pre-commit-config.yaml`.
    - El arbol de trabajo debe estar limpio o con cambios trackeados.
    - El usuario invoca este script antes de `git push` como preflight de entrega.

During (Proceso y Recursos):
    - Lee `.pre-commit-config.yaml` para detectar hooks mutadores en `pre-push`.
    - Verifica que los artefactos generados (.agent/context/, .agent/runtime/events/)
      esten excluidos de los hooks de formato/whitespace.
    - Ejecuta una pasada correctiva simulada (git status) para detectar arbol sucio.
    - No modifica archivos; solo verifica y reporta.

After (Post-condiciones y Errores):
    - Retorna exit code 0 si el arbol pasa todas las verificaciones de higiene.
    - Retorna exit code 1 si detecta mutadores en pre-push o arbol sucio.
    - Imprime diagnostico accionable antes del `git push`.
    - Excepciones: FileNotFoundError si falta .pre-commit-config.yaml,
      subprocess.CalledProcessError si git falla.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple


class HygieneResult(NamedTuple):
    """Resultado de una verificacion de higiene."""

    passed: bool
    message: str
    details: list[str] | None = None


MUTATING_HOOKS = frozenset(
    [
        "end-of-file-fixer",
        "mixed-line-ending",
        "trailing-whitespace",
        "ruff-format",
        "black",
        "isort",
        "yamlfmt",
        "uv-lock",
    ]
)

GENERATED_ARTIFACT_PATHS = [
    r"\.agent/context/",
    r"\.agent/runtime/events/",
]


def _parse_hook_property(stripped: str, hook: dict) -> bool:
    """Parse a single hook property line into the hook dict. Returns True if parsed."""
    stages_match = re.match(r"^\s*stages:\s*\[(.+)\]$", stripped)
    if stages_match:
        hook["stages"] = [s.strip() for s in stages_match.group(1).split(",")]
        return True
    exclude_match = re.match(r"^\s*exclude:\s*['\"]?(.+?)['\"]?$", stripped)
    if exclude_match:
        hook["exclude"] = exclude_match.group(1)
        return True
    args_match = re.match(r"^\s*args:\s*\[(.+)\]$", stripped)
    if args_match:
        hook["args"] = [a.strip() for a in args_match.group(1).split(",")]
        return True
    types_match = re.match(r"^\s*types:\s*\[(.+)\]$", stripped)
    if types_match:
        hook["types"] = [t.strip() for t in types_match.group(1).split(",")]
        return True
    return False


def _parse_config_lines(content: str) -> list[dict]:
    """Parsea el contenido YAML linea a linea y retorna lista de repos con hooks."""
    repos: list[dict] = []
    current_repo: dict | None = None
    current_hook: dict | None = None
    in_hooks = False

    for line in content.split("\n"):
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue

        repo_match = re.match(r"^\s*-\s*repo:\s*(.+)$", stripped)
        if repo_match:
            if current_repo is not None:
                repos.append(current_repo)
            current_repo = {"repo": repo_match.group(1).strip(), "hooks": []}
            in_hooks = False
            current_hook = None
            continue

        if re.match(r"^\s*hooks:\s*$", stripped):
            in_hooks = True
            continue

        if in_hooks and current_repo is not None:
            hook_match = re.match(r"^\s*-\s*id:\s*(.+)$", stripped)
            if hook_match:
                current_hook = {"id": hook_match.group(1).strip()}
                current_repo["hooks"].append(current_hook)
                continue

            if current_hook is not None:
                _parse_hook_property(stripped, current_hook)

    if current_repo is not None:
        repos.append(current_repo)

    return repos


def load_pre_commit_config(project_root: Path) -> dict[str, list[dict]] | None:
    """Carga .pre-commit-config.yaml y retorna estructura de repos/hooks.

    Args:
        project_root: Raiz del proyecto donde buscar el archivo.

    Returns:
        Dict con clave 'repos' y lista de hooks, o None si falla el parseo.
    """
    config_path = project_root / ".pre-commit-config.yaml"
    if not config_path.exists():
        return None

    try:
        content = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    repos = _parse_config_lines(content)
    return {"repos": repos} if repos else None


def check_mutating_hooks_in_pre_push(config: dict[str, list[dict]]) -> HygieneResult:
    """Verifica que no haya hooks mutadores en la etapa pre-push.

    Args:
        config: Configuracion cargada de .pre-commit-config.yaml.

    Returns:
        HygieneResult con passed=True si no hay mutadores en pre-push.
    """
    violations: list[str] = []

    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            hook_id = hook.get("id", "")
            stages = hook.get("stages", None)  # None = todos los stages

            # Si el hook es mutador y esta en pre-push (explicito o implicito)
            if hook_id in MUTATING_HOOKS:
                if stages is None:
                    # Sin stages explicitos = aplica a todos, incluyendo pre-push
                    violations.append(
                        f"Hook mutador '{hook_id}' sin stages explicitos "
                        "(aplica a pre-push por defecto)"
                    )
                elif "pre-push" in stages:
                    violations.append(
                        f"Hook mutador '{hook_id}' explicitamente en pre-push"
                    )

    if violations:
        return HygieneResult(
            passed=False,
            message="MUTADORES EN PRE-PUSH DETECTADOS",
            details=violations,
        )

    return HygieneResult(
        passed=True,
        message="No hay hooks mutadores en pre-push",
    )


def check_generated_artifacts_excluded(config: dict[str, list[dict]]) -> HygieneResult:
    """Verifica que los artefactos generados esten excluidos de hooks de formato.

    Args:
        config: Configuracion cargada de .pre-commit-config.yaml.

    Returns:
        HygieneResult con passed=True si los artefactos estan excluidos.
    """
    formatting_hooks = frozenset(
        [
            "end-of-file-fixer",
            "mixed-line-ending",
            "trailing-whitespace",
            "ruff-format",
        ]
    )

    missing_exclusions: list[str] = []

    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            hook_id = hook.get("id", "")
            if hook_id not in formatting_hooks:
                continue

            # Hooks with a type restriction (e.g. types: [python]) only run on
            # matching files, so they cannot touch .json/.md generated artifacts.
            if hook.get("types"):
                continue

            exclude_pattern = hook.get("exclude", "")

            # Verificar que cada ruta generada este cubierta por el exclude
            missing_exclusions.extend(
                f"Hook '{hook_id}' no excluye '{artifact_path}'"
                for artifact_path in GENERATED_ARTIFACT_PATHS
                if artifact_path not in exclude_pattern
            )

    if missing_exclusions:
        return HygieneResult(
            passed=False,
            message="ARTEFACTOS GENERADOS NO EXCLUIDOS",
            details=missing_exclusions,
        )

    return HygieneResult(
        passed=True,
        message="Artefactos generados correctamente excluidos",
    )


def check_git_tree_clean(project_root: Path) -> HygieneResult:
    """Verifica que el arbol Git este limpio (sin cambios staged o unstaged).

    Args:
        project_root: Raiz del proyecto donde ejecutar git status.

    Returns:
        HygieneResult con passed=True si el arbol esta limpio.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],  # noqa: S607
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return HygieneResult(
            passed=False,
            message="GIT NO DISPONIBLE",
            details=["El comando 'git' no esta disponible en PATH"],
        )

    if result.returncode != 0:
        return HygieneResult(
            passed=False,
            message="ERROR AL EJECUTAR GIT STATUS",
            details=[result.stderr.strip() or f"Exit code: {result.returncode}"],
        )

    output_lines = [line for line in result.stdout.strip().split("\n") if line]
    if output_lines:
        return HygieneResult(
            passed=False,
            message="ARBOL SUCIO DETECTADO",
            details=[
                f"{len(output_lines)} archivo(s) con cambios:",
                *output_lines[:10],  # Mostrar solo primeros 10
            ]
            + (
                [f"... y {len(output_lines) - 10} mas"]
                if len(output_lines) > 10
                else []
            ),
        )

    return HygieneResult(
        passed=True,
        message="Arbol Git limpio",
    )


def run_delivery_hygiene_check(  # noqa: C901
    project_root: Path | None = None,
    *,
    check_tree: bool = True,
) -> int:
    """Ejecuta todas las verificaciones de higiene de entrega.

    Args:
        project_root: Raiz del proyecto. Si None, usa el directorio actual.
        check_tree: Si True, verifica que el arbol Git este limpio.

    Returns:
        Exit code: 0 si todas las verificaciones pasan, 1 si alguna falla.
    """
    if project_root is None:
        project_root = Path.cwd()

    all_passed = True
    results: list[HygieneResult] = []

    # Cargar configuracion
    config = load_pre_commit_config(project_root)
    if config is None:
        print("[ERROR] No se pudo cargar .pre-commit-config.yaml", file=sys.stderr)
        return 1

    # Verificacion 1: mutadores en pre-push
    result = check_mutating_hooks_in_pre_push(config)
    results.append(result)
    if not result.passed:
        all_passed = False

    # Verificacion 2: artefactos generados excluidos
    result = check_generated_artifacts_excluded(config)
    results.append(result)
    if not result.passed:
        all_passed = False

    # Verificacion 3: arbol limpio (opcional, puede desactivarse)
    if check_tree:
        result = check_git_tree_clean(project_root)
        results.append(result)
        if not result.passed:
            all_passed = False

    # Imprimir reporte
    print("=" * 60)
    print("DELIVERY HYGIENE CHECK - Reporte")
    print("=" * 60)

    for result in results:
        status = "[OK]" if result.passed else "[FAIL]"
        print(f"{status} {result.message}")
        if result.details:
            for detail in result.details:
                print(f"      {detail}")
        print()

    print("=" * 60)
    if all_passed:
        print("ENTREGA LIMPIA: todas las verificaciones pasaron")
        print("Puede proceder con git push")
    else:
        print("ENTREGA BLOQUEADA: corrija los problemas antes de push")
    print("=" * 60)

    return 0 if all_passed else 1


def main() -> int:
    """Punto de entrada CLI."""
    parser = argparse.ArgumentParser(
        description="Delivery Hygiene Check - pre-push no mutating preflight"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Raiz del proyecto (default: directorio actual)",
    )
    parser.add_argument(
        "--no-tree-check",
        action="store_true",
        help="Omitir verificacion de arbol limpio (solo config)",
    )

    args = parser.parse_args()

    return run_delivery_hygiene_check(
        project_root=args.project_root,
        check_tree=not args.no_tree_check,
    )


if __name__ == "__main__":
    sys.exit(main())
