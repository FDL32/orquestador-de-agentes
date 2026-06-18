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


# Bootstrap: motor root must be on sys.path so `runtime.*` imports resolve
# even when this script runs with cwd inside a destination workspace.
_MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))


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
        # Motor/destino topology: the pre-commit config lives in repo_motor,
        # not in the destination workspace. Resolve it via motor_link.
        try:
            from runtime.motor_link import resolve_motor_root

            motor_root = resolve_motor_root(project_root)
            if motor_root is not None:
                motor_config = motor_root / ".pre-commit-config.yaml"
                if motor_config.exists():
                    config_path = motor_config
        except ImportError:
            pass
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


# WOT-2026-010u: plan/audit artifact name prefixes that the archiver moves into
# _archive/plan_audit/. A deletion of one of these with a matching untracked copy
# under _archive/plan_audit/ is an UNCOMMITTED RENAME, not a normal dirty file.
_ARCHIVABLE_PREFIXES = ("STRATEGY_", "AUDIT_", "PLAN_")
_ARCHIVE_REL_DIR = ".agent/collaboration/_archive/plan_audit"


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _is_archivable_collab_artifact(rel_path: str) -> bool:
    p = rel_path.replace("\\", "/")
    name = _basename(p)
    return p.startswith(".agent/collaboration/") and name.startswith(
        _ARCHIVABLE_PREFIXES
    )


def check_archive_rename_complete(project_root: Path) -> HygieneResult:
    """Detect an uncommitted archival rename (WOT-2026-010u).

    Before: ``archive_collaboration_artifacts.py`` moves a closed STRATEGY_/AUDIT_/
    PLAN_ artifact into ``_archive/plan_audit/`` with ``shutil.move`` and does NOT
    ``git add``/commit. Git then shows the original as deleted and the archived copy
    as untracked -- a rename that was never recorded.

    During: parse ``git status --porcelain``. A deleted collaboration artifact whose
    basename also appears as an untracked file under ``_archive/plan_audit/`` is the
    limbo state. A bare deletion WITHOUT an archived copy is a normal dirty file and
    is NOT reported here (no false positive). Unrelated files are ignored.

    After: returns ``passed=False`` with a stable reason ``archive_rename_uncommitted``
    and a self-service remediation naming the exact ``git add``/``commit`` command.
    Never auto-commits and never deletes anything.
    """
    try:
        # --untracked-files=all so an untracked archived copy is listed as an
        # individual file (git otherwise collapses a new dir like _archive/ to its
        # top level, hiding the renamed artifact).
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],  # noqa: S607
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

    deleted_artifacts: dict[str, str] = {}
    archived_untracked: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip().strip('"')
        rel = path.replace("\\", "/")
        # Deleted collaboration artifact (staged or unstaged delete).
        if "D" in code and _is_archivable_collab_artifact(rel):
            deleted_artifacts[_basename(rel)] = rel
        # Untracked copy already sitting in the archive dir.
        elif code == "??" and rel.startswith(_ARCHIVE_REL_DIR + "/"):
            archived_untracked[_basename(rel)] = rel

    pairs = [
        (deleted_artifacts[name], archived_untracked[name])
        for name in sorted(deleted_artifacts)
        if name in archived_untracked
    ]
    if not pairs:
        return HygieneResult(
            passed=True,
            message="Sin renames de archivado pendientes",
        )

    details = [
        "archive_rename_uncommitted: el archivador movio artefactos cerrados a "
        "_archive/plan_audit/ pero el rename no quedo commiteado (delete+untracked).",
    ]
    for old, new in pairs:
        details.append(f"  origen: {old}")
        details.append(f"  destino: {new}")
    remediation_paths = " ".join(f"{old} {new}" for old, new in pairs)
    details.append(
        f"Remediacion (registra el rename, no borra): "
        f'git add -- {remediation_paths} && git commit -m "chore: reconcile archival rename"'
    )
    return HygieneResult(
        passed=False,
        message="ARCHIVE_RENAME_UNCOMMITTED",
        details=details,
    )


def check_cross_root_isolation(
    project_root: Path,
    motor_root: Path,
    delivery_authority: str,
) -> HygieneResult:
    """Verify no productive files exist in the non-authority root.

    WOT-2026-009c: reciprocal isolation guard for delivery hygiene.

    Before: both project_root and motor_root must be valid directories.
    During: imports scope_gate from motor .agent/; runs check_cross_root_contamination
        on the non-authority root; filters with that root's operational exclude set.
    After: returns HygieneResult.passed=False if productive (non-operational)
        files found in non-authority root. Operational files are reported but
        do not cause failure.
    """
    try:
        agent_dir = motor_root / ".agent"
        if str(agent_dir) not in sys.path:
            sys.path.insert(0, str(agent_dir))
        import scope_gate as sg
    except ImportError:
        return HygieneResult(
            passed=True,
            message="Aislamiento reciproco: scope_gate no importable (skip)",
        )

    if delivery_authority == "repo_motor":
        other_root = project_root.resolve()
    else:
        other_root = motor_root.resolve()

    collab = other_root / ".agent" / "collaboration"
    agent_d = other_root / ".agent"
    context_d = agent_d / "context"
    try:
        other_exclude = sg.exclude_files(
            collab_dir=collab,
            agent_dir=agent_d,
            context_dir=context_d,
        )
    except Exception:
        other_exclude = set()

    cross = sg.check_cross_root_contamination(
        other_root=other_root,
        other_exclude=other_exclude,
    )

    other_name = "repo_destino" if delivery_authority == "repo_motor" else "repo_motor"

    if cross["productive"]:
        return HygieneResult(
            passed=False,
            message=f"CONTAMINACION PRODUCTIVA EN {other_name.upper()}",
            details=[
                f"contaminacion_productiva: {f}" for f in sorted(cross["productive"])
            ],
        )

    details = None
    if cross["operational"]:
        details = [
            f"excluded_operational (OK): {f}" for f in sorted(cross["operational"])
        ]
    return HygieneResult(
        passed=True,
        message=f"Aislamiento reciproco OK (sin contaminacion en {other_name})",
        details=details,
    )


def _read_delivery_authority(project_root: Path) -> str:
    """Read delivery_authority from work_plan.md in project_root."""
    import re

    wp = project_root / ".agent" / "collaboration" / "work_plan.md"
    if not wp.exists():
        return "repo_motor"
    try:
        content = wp.read_text(encoding="utf-8")
    except OSError:
        return "repo_motor"
    if re.search(
        r"delivery_authority\s*:?\**\s*(?:repo_destino|destino)",
        content,
        re.IGNORECASE,
    ):
        return "repo_destino"
    return "repo_motor"


def run_delivery_hygiene_check(  # noqa: C901
    project_root: Path | None = None,
    *,
    check_tree: bool = True,
    motor_root: Path | None = None,
) -> int:
    """Ejecuta todas las verificaciones de higiene de entrega.

    Args:
        project_root: Raiz del proyecto. Si None, usa el directorio actual.
        check_tree: Si True, verifica que el arbol Git este limpio.
        motor_root: Motor root para check de aislamiento reciproco (WOT-2026-009c).
            Si None, omite el check de contaminacion cruzada.

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

    # Verificacion 4: aislamiento reciproco motor/destino (WOT-2026-009c)
    if motor_root is not None and motor_root.resolve() != project_root.resolve():
        da = _read_delivery_authority(project_root)
        result = check_cross_root_isolation(project_root, motor_root, da)
        results.append(result)
        if not result.passed:
            all_passed = False

    # Verificacion 5: rename de archivado pendiente (WOT-2026-010u). Independiente
    # de check_tree: detecta el limbo delete+untracked que check_git_tree_clean
    # solo reporta como dirty generico, nombrando la remediacion exacta del rename.
    result = check_archive_rename_complete(project_root)
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
    parser.add_argument(
        "--motor-root",
        type=Path,
        default=None,
        help="Motor root para check de aislamiento reciproco (WOT-2026-009c)",
    )

    args = parser.parse_args()

    return run_delivery_hygiene_check(
        project_root=args.project_root,
        check_tree=not args.no_tree_check,
        motor_root=args.motor_root,
    )


if __name__ == "__main__":
    sys.exit(main())
