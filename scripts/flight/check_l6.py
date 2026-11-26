"""Read-only L-6 reconciliation for the flight archive index.

Before: ``archive_index`` is the sole input and points to a JSONL archive index.
During: read the index and reconcile each family through ``p7_common`` without
    creating, changing, or deleting any file.
After: return ``(rc, findings)`` for the CLI face or only findings for heartbeat.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_p7_common():
    """Load the shared reconciler from the sibling source file by path."""
    path = Path(__file__).resolve().with_name("p7_common.py")
    spec = importlib.util.spec_from_file_location("_l6_p7_common", path)
    if spec is None or spec.loader is None:
        raise ImportError("no se pudo cargar p7_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p7_common = _load_p7_common()


def _finding(key: str, text: str) -> tuple[str, str, str]:
    """Create the fixed L-6 finding shape and severity."""
    return key, "AVISO", text


def _read_rows(index: Path) -> list[dict[str, Any]]:
    """Read JSONL rows without opening the index in a write-capable mode."""
    rows = []
    for line_number, line in enumerate(
        index.read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"fila {line_number} no es un objeto")
        rows.append(value)
    return rows


def _families(root: Path, rows: list[dict[str, Any]]) -> set[str]:
    """Return index families plus existing archive family directories."""
    result = {
        str(row.get("family"))
        for row in rows
        if isinstance(row.get("family"), str) and row.get("family")
    }
    if root.is_dir():
        result.update(path.name for path in root.iterdir() if path.is_dir())
    return result


def _retired_names(root: Path, family: str, rows: list[dict[str, Any]]) -> set[str]:
    """Return family-relative paths belonging to RETIRADO_LOCAL rows."""
    family_root = (root / family).resolve()
    names = set()
    for row in rows:
        if row.get("status") != "RETIRADO_LOCAL" or row.get("family") != family:
            continue
        for field in ("zip", "manifest"):
            value = row.get(field)
            if not value:
                continue
            candidate = Path(str(value))
            candidate = candidate if candidate.is_absolute() else root / candidate
            try:
                names.add(candidate.resolve().relative_to(family_root).as_posix())
            except ValueError:
                continue
    return names


def run_check_l6(archive_index) -> tuple[int, list[tuple[str, str, str]]]:
    """Reconcile an archive index and return an rc plus fixed-shape findings.

    Before: ``archive_index`` is a path-like JSONL index, or a missing path.
    During: inspect the index and archive family trees using the shared reconciler.
    After: return rc 0 iff there are no findings, otherwise rc 1; never mutate input.
    """
    index = Path(archive_index)
    if not index.is_file() or not index.parent.is_dir():
        return 1, [
            _finding("l6-archivo-no-montado", f"No existe el indice o archivo: {index}")
        ]
    root = index.parent
    try:
        rows = _read_rows(index)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return 1, [
            _finding(
                "l6-indice-ilegible", f"No se puede leer el indice: {str(exc)[:120]}"
            )
        ]

    findings: list[tuple[str, str, str]] = []
    findings.extend(
        _finding(
            "l6-indice-retirado-local",
            f"Fila RETIRADO_LOCAL: {row.get('family', '<sin-familia>')}",
        )
        for row in rows
        if row.get("status") == "RETIRADO_LOCAL"
    )
    for family in sorted(_families(root, rows)):
        retired = _retired_names(root, family, rows)
        try:
            reconciled = p7_common.reconcile_index(root, rows, family)
        except (OSError, ValueError, p7_common.ArchiveError) as exc:
            findings.append(
                _finding(
                    "l6-indice-ilegible",
                    f"No se puede reconciliar {family}: {str(exc)[:120]}",
                )
            )
            continue
        for item in reconciled:
            kind, _, name = item.partition(": ")
            if kind == "fichero_sin_fila" and name in retired:
                continue
            if kind == "fila_sin_fichero":
                findings.append(_finding("l6-fila-sin-fichero", f"{family}: {name}"))
            elif kind == "fichero_sin_fila":
                findings.append(_finding("l6-fichero-sin-fila", f"{family}: {name}"))
    return (1 if findings else 0), findings


def check_l6(out, archive_index) -> list[tuple[str, str, str]]:
    """Heartbeat face: stay inert without an explicitly supplied index.

    Before: ``archive_index`` is optional configuration from the heartbeat.
    During: run the read-only checker only when configuration is present.
    After: return only the list of three-tuples expected by ``_detect``.
    """
    del out
    if archive_index is None:
        return []
    return run_check_l6(archive_index)[1]
