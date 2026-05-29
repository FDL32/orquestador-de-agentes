#!/usr/bin/env python3
# ruff: noqa: S603, S607, C901
"""
Pre-handoff guard - Verifica higiene del arbol antes de emitir READY_FOR_REVIEW.

Este script se invoca desde agent_controller.py en _handle_mark_ready() antes de
emitir STATE_CHANGED -> READY_FOR_REVIEW.

Ejecuta git status --porcelain y excluye:
- Superficies vivas del runtime (TURN.md, STATE.md, execution_log.md, events.jsonl, etc.)
- Archivos ya ignorados por .gitignore

Si el arbol esta sucio, devuelve exit 1 + JSON diagnostico.
Si falta el checkpoint M3, devuelve exit 1 + JSON diagnostico.
Si hay archivos fuera de Files Likely Touched, los reporta como scope_discrepancy
(no bloqueante, solo observacion).

Uso:
    python scripts/pre_handoff_guard.py --project-root /path --ticket-id WP-2026-XXX
"""

import json
import subprocess
import sys
from pathlib import Path


# Superficies vivas del runtime que NO deben generar falsos positivos
# Incluye archivos individuales y directorios completos
LIVE_SURFACES_REL = {
    ".agent/collaboration/TURN.md",
    ".agent/collaboration/STATE.md",
    ".agent/collaboration/execution_log.md",
    ".agent/collaboration/notifications.md",
    ".agent/collaboration/review_queue.md",
    ".agent/collaboration/work_plan.md",
    ".agent/collaboration/archive/",
    ".agent/collaboration/_archive/",
    ".agent/runtime/events/events.jsonl",
    ".agent/runtime/store.json",
    ".agent/runtime/builder_lock.txt",
    ".agent/runtime/circuit_breaker.json",
    ".agent/runtime/supervisor_lock.txt",
    ".agent/runtime/events/",
    ".agent/runtime/approvals/",
    ".agent/context/project-map.json",
}

# Directorios completos de superficies vivas (para excluir todo el arbol)
LIVE_SURFACE_DIRS = {
    ".agent/collaboration/archive",
    ".agent/collaboration/_archive",
    ".agent/runtime/events",
    ".agent/runtime/approvals",
}


def get_project_root(args_project_root: str | None) -> Path:
    """Obtener project root desde args o desde el directorio actual."""
    if args_project_root:
        return Path(args_project_root).resolve()
    # Default: subir dos niveles desde scripts/
    return Path(__file__).resolve().parent.parent


def get_gitignore_patterns(project_root: Path) -> set[str]:
    """Leer patrones de .gitignore y devolver paths ignorados."""
    ignored = set()
    gitignore = project_root / ".gitignore"
    if not gitignore.exists():
        return ignored

    try:
        content = gitignore.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                # Patrones simples: convertir a path relativo
                if line.startswith("/"):
                    line = line[1:]
                if line.endswith("/"):
                    line = line[:-1]
                if line:
                    ignored.add(line)
    except OSError:
        pass

    return ignored


def is_ignored_by_gitignore(file_path: Path, project_root: Path) -> bool:
    """Verificar si un archivo es ignorado por .gitignore usando git check-ignore."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", str(file_path.relative_to(project_root))],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        return result.returncode == 0
    except (FileNotFoundError, ValueError):
        return False


def get_live_surfaces_absolute(project_root: Path) -> tuple[set[str], set[str]]:
    """
    Devolver paths absolutos de superficies vivas.

    Returns:
        tuple[set[str], set[str]]: (archivos individuales, directorios completos)
    """
    live_files = set()
    live_dirs = set()

    for rel_path in LIVE_SURFACES_REL:
        full_path = project_root / rel_path
        if rel_path.endswith("/"):
            # Es un directorio
            live_dirs.add(str(full_path.resolve()))
        else:
            live_files.add(str(full_path.resolve()))

    # Tambien incluir cualquier archivo en .agent/collaboration/archive/
    archive_dir = project_root / ".agent" / "collaboration" / "archive"
    if archive_dir.exists():
        for f in archive_dir.glob("*"):
            live_files.add(str(f.resolve()))

    # Incluir _archive/plan_audit/
    plan_audit_dir = (
        project_root / ".agent" / "collaboration" / "_archive" / "plan_audit"
    )
    if plan_audit_dir.exists():
        for f in plan_audit_dir.glob("*"):
            live_files.add(str(f.resolve()))

    # Añadir directorios de LIVE_SURFACE_DIRS
    for rel_dir in LIVE_SURFACE_DIRS:
        full_path = project_root / rel_dir
        live_dirs.add(str(full_path.resolve()))

    return live_files, live_dirs


def is_in_live_surface_dir(file_path: str, live_dirs: set[str]) -> bool:
    """Verificar si un archivo esta dentro de un directorio de superficie viva."""
    file_path_obj = Path(file_path)
    for live_dir in live_dirs:
        live_dir_obj = Path(live_dir)
        try:
            file_path_obj.relative_to(live_dir_obj)
            return True
        except ValueError:
            continue
    return False


def get_changed_files(project_root: Path) -> set[str]:
    """Obtener archivos cambiados (staged, unstaged, untracked) usando git status."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        changed = set()
        entries = result.stdout.split("\0")
        i = 0
        while i < len(entries):
            entry = entries[i]
            if not entry:
                i += 1
                continue
            if len(entry) >= 3:
                status = entry[:2]
                path = entry[3:] if entry[2] == " " else entry[2:]
                # Manejar renames
                if status[0] == "R" and i + 1 < len(entries):
                    new_path = entries[i + 1]
                    if new_path:
                        changed.add(new_path)
                    i += 2
                    continue
                else:
                    changed.add(path)
            i += 1

        # Resolver a paths absolutos
        resolved = set()
        for f in changed:
            path = (project_root / f).resolve()
            resolved.add(str(path))
        return resolved
    except FileNotFoundError:
        return set()


def check_checkpoint_m3_exists(project_root: Path, ticket_id: str) -> bool:
    """Verificar si el checkpoint M3 (review-<ticket>) existe como tag."""
    tag_name = f"checkpoint/review-{ticket_id}"
    try:
        result = subprocess.run(
            ["git", "rev-parse", tag_name],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def parse_files_likely_touched(project_root: Path) -> set[str]:
    """Parsear Files Likely Touched desde work_plan.md."""
    work_plan = project_root / ".agent" / "collaboration" / "work_plan.md"
    if not work_plan.exists():
        return set()

    try:
        content = work_plan.read_text(encoding="utf-8")
    except OSError:
        return set()

    lines = content.split("\n")
    in_section = False
    files = set()

    def _looks_like_path_token(token: str) -> bool:
        if not token or " " in token:
            return False
        if token.startswith("."):
            return True
        if "/" in token or "\\" in token:
            return True
        basename = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return "." in basename

    for line in lines:
        line = line.strip()
        if "## Files Likely Touched" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line and not line.startswith("---"):
            normalized = (
                line.lstrip("*- ")
                .replace("`", "")
                .replace('"', "")
                .replace("'", "")
                .strip()
            )
            if normalized and _looks_like_path_token(normalized):
                path = (project_root / normalized).resolve()
                files.add(str(path))

    return files


def get_scope_discrepancy(
    changed_files: set[str], files_likely_touched: set[str], live_surfaces: set[str]
) -> set[str]:
    """Detectar archivos fuera de Files Likely Touched (excluyendo superficies vivas)."""
    relevant_changed = changed_files - live_surfaces
    discrepancy = relevant_changed - files_likely_touched
    return discrepancy


def run_guard(project_root: Path, ticket_id: str) -> dict:
    """
    Ejecutar el guard de handoff.

    Returns:
        dict con:
            - valid: bool (True si handoff permitido)
            - dirty_tree: bool (True si arbol sucio)
            - missing_checkpoint: bool (True si falta M3)
            - dirty_files: list[str] (archivos que ensucian el arbol)
            - scope_discrepancy: list[str] (archivos fuera de scope, no bloqueante)
            - checkpoint_tag: str | None (tag del checkpoint M3 si existe)
    """
    result = {
        "valid": True,
        "dirty_tree": False,
        "missing_checkpoint": False,
        "dirty_files": [],
        "scope_discrepancy": [],
        "checkpoint_tag": None,
        "ticket_id": ticket_id,
    }

    # 1. Verificar checkpoint M3
    m3_exists = check_checkpoint_m3_exists(project_root, ticket_id)
    if not m3_exists:
        result["valid"] = False
        result["missing_checkpoint"] = True
    else:
        result["checkpoint_tag"] = f"checkpoint/review-{ticket_id}"

    # 2. Obtener superficies vivas (archivos y directorios)
    live_files, live_dirs = get_live_surfaces_absolute(project_root)

    # 3. Obtener archivos cambiados
    changed_files = get_changed_files(project_root)

    # 4. Filtrar archivos ignorados por gitignore
    non_ignored_changed = set()
    for f in changed_files:
        f_path = Path(f)
        if not is_ignored_by_gitignore(f_path, project_root):
            non_ignored_changed.add(f)

    # 5. Determinar dirty_files y scope_discrepancy
    # - dirty_files: cualquier archivo no vivo y no ignorado por gitignore.
    #   Si existe, el arbol esta sucio y el handoff debe bloquear.
    # - scope_discrepancy: subconjunto informativo de dirty_files que queda fuera
    #   de Files Likely Touched.
    #
    # Regla:
    # - Todo cambio no vivo ensucia el arbol.
    # - Los cambios fuera de scope se reportan adicionalmente como observacion.

    files_likely_touched = parse_files_likely_touched(project_root)

    dirty_files = set()
    scope_discrepancy = set()

    for f in non_ignored_changed:
        # Es superficie viva? → ignorar
        if f in live_files or is_in_live_surface_dir(f, live_dirs):
            continue

        dirty_files.add(f)

        # Fuera de scope: reportar como scope_discrepancy (observacion)
        if files_likely_touched and f not in files_likely_touched:
            scope_discrepancy.add(f)

    if dirty_files:
        result["valid"] = False
        result["dirty_tree"] = True
        result["dirty_files"] = sorted(
            str(Path(f).relative_to(project_root)) for f in dirty_files
        )

    # Reportar scope_discrepancy (no bloqueante)
    if scope_discrepancy:
        result["scope_discrepancy"] = sorted(
            str(Path(f).relative_to(project_root)) for f in scope_discrepancy
        )

    return result


def main() -> int:
    """Punto de entrada principal."""
    import argparse

    parser = argparse.ArgumentParser(description="Pre-handoff guard")
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Project root directory",
    )
    parser.add_argument(
        "--ticket-id",
        type=str,
        required=True,
        help="Ticket ID (e.g., WP-2026-167)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    args = parser.parse_args()

    project_root = get_project_root(args.project_root)
    ticket_id = args.ticket_id

    # Verificar que estamos en un repo git
    if not (project_root / ".git").exists():
        result = {
            "valid": True,
            "dirty_tree": False,
            "missing_checkpoint": False,
            "dirty_files": [],
            "scope_discrepancy": [],
            "checkpoint_tag": None,
            "ticket_id": ticket_id,
            "warnings": ["Repository is not git-managed"],
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("[WARN] Repository is not git-managed. Skipping guard checks.")
        return 0

    result = run_guard(project_root, ticket_id)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["valid"]:
            print(f"[OK] Handoff guard passed for {ticket_id}")
            if result["scope_discrepancy"]:
                print(
                    f"[WARN] Scope discrepancy (non-blocking): {', '.join(result['scope_discrepancy'])}"
                )
        else:
            print(f"[ERROR] Handoff guard failed for {ticket_id}")
            if result["missing_checkpoint"]:
                print(f"  - Missing checkpoint M3: checkpoint/review-{ticket_id}")
            if result["dirty_tree"]:
                print(f"  - Dirty tree: {', '.join(result['dirty_files'])}")
            if result["scope_discrepancy"]:
                print(
                    f"  - Scope discrepancy (non-blocking): {', '.join(result['scope_discrepancy'])}"
                )

    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
