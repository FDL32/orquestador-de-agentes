"""scope_verification.py - Logica viva de verificacion de scope.

Extraido de scripts/orquestador.py (WOT-2026-014h).
Este modulo NO esta deprecado: contiene la logica activa de snapshot
y clasificacion de archivos usada por el pipeline de calidad.
"""

import os
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Scope Verification Functions
# ---------------------------------------------------------------------------


def snapshot_file_info(path: Path) -> dict | None:
    """
    Captura metadatos de archivo (mtime_ns y size).
    Retorna dict con keys 'mtime_ns' y 'size', o None si el archivo no existe.
    """
    try:
        stat_result = os.stat(path)
        return {
            "mtime_ns": stat_result.st_mtime_ns,
            "size": stat_result.st_size,
        }
    except FileNotFoundError:
        return None
    except OSError:
        return None


def snapshot_paths(paths: list[Path]) -> dict[str, dict]:
    """
    Captura snapshot de múltiples paths (archivos o directorios).
    Si es directorio, expande recursivamente con rglob.
    Retorna dict: {str(path): {mtime_ns, size}}
    """
    result = {}

    for p in paths:
        try:
            if not p.exists():
                continue

            if p.is_file():
                info = snapshot_file_info(p)
                if info:
                    result[str(p)] = info
            elif p.is_dir():
                for child in p.rglob("*"):
                    if child.is_file():
                        info = snapshot_file_info(child)
                        if info:
                            result[str(child)] = info
        except OSError:
            continue

    return result


def detect_changed_files(before: dict[str, dict], after: dict[str, dict]) -> list[str]:
    """
    Detecta archivos cambiados entre dos snapshots.
    Compara mtime_ns para detectar: nuevos, modificados o eliminados.
    Retorna lista de paths que cambiaron.
    """
    all_keys = set(before.keys()) | set(after.keys())
    changed = [
        path
        for path in all_keys
        if (
            path not in before
            or path not in after
            or before[path].get("mtime_ns") != after[path].get("mtime_ns")
        )
    ]
    return changed


def classify_scope(
    touched: list[str],
    allowlist: dict,
    ticket_allowed_files: list[Path] | None = None,
) -> tuple[list[str], list[str]]:
    """
    Clasifica archivos tocados según allowlist.
    Si ticket_allowed_files proveído, solo esos archivos son in_scope (modo restrictivo).
    Retorna (in_scope, out_of_scope).
    """
    write_roots = allowlist.get("write_roots", [])

    if ticket_allowed_files:
        in_scope = []
        out_of_scope = []

        ticket_set = {str(p).replace("\\", "/") for p in ticket_allowed_files}

        for path in touched:
            normalized = path.replace("\\", "/")
            if normalized in ticket_set:
                in_scope.append(path)
            else:
                out_of_scope.append(path)

        return in_scope, out_of_scope

    in_scope = []
    out_of_scope = []

    for path in touched:
        path_obj = Path(path)
        matched = False

        for root in write_roots:
            root_path = Path(root)

            if root == ".":
                matched = True
                break

            if str(root_path) == ".":
                matched = True
                break

            normalized_root = str(root_path).replace("\\", "/")
            normalized_path = str(path_obj).replace("\\", "/")

            if (
                normalized_path.startswith(normalized_root + "/")
                or normalized_path == normalized_root
            ):
                matched = True
                break

        if matched:
            in_scope.append(path)
        else:
            out_of_scope.append(path)

    return in_scope, out_of_scope


def generate_scope_report(
    in_scope: list[str],
    out_of_scope: list[str],
    indeterminate: list[str],
    stage: str,
) -> dict:
    """
    Genera reporte JSON del scope verificado.
    Incluye timestamp, stage, y summary.
    """
    return {
        "timestamp": datetime.now().isoformat(),
        "stage": stage,
        "scope_summary": {
            "in_scope_count": len(in_scope),
            "out_of_scope_count": len(out_of_scope),
            "indeterminate_count": len(indeterminate),
        },
        "in_scope": sorted(in_scope),
        "out_of_scope": sorted(out_of_scope),
        "indeterminate": sorted(indeterminate),
    }
