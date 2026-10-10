#!/usr/bin/env python3
"""Backfill: anota `promoted_via: "legacy_backfill"` a entradas sin procedencia (WOT-2026-041g).

Before (Pre-condiciones):
    - `--root` (opcional): raiz del workspace donde vive el archive.
      Por defecto: raiz del motor resuelta desde `Path(__file__)`.
    - `--apply`: escribir los cambios (por defecto: dry-run).

During (Proceso y Recursos):
    - Glob de `.agent/runtime/memory/archive/observations.*.jsonl` bajo `--root`.
    - Para CADA entrada que NO lleve `promoted_via` o tenga un valor no aceptado:
        * anota `record["promoted_via"] = "legacy_backfill"`.
        * NO recomputa el `id` (ya existe o no debe tocarse).
        * PRESERVA todos los demas campos byte a byte.
    - Escribe cada fichero de vuelta solo si hubo cambios.
    - Segunda corrida = no-op (todas las entradas ya tienen `promoted_via`).

After (Post-condiciones y Errores):
    - Dry-run: imprime el conteo de entradas que SERIAN migradas, sin escribir.
    - Con --apply: imprime el conteo de entradas MIGRADAS, escribe solo ficheros
      con cambios. Retorna 0 siempre (el backfill es idempotente y no falla por
      hallazgos individuales).
    - El script queda commiteado tras la corrida exitosa.

Uso:
    python scripts/backfill_promoted_via.py [--root <dir>] [--apply]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


MOTOR_ROOT = Path(__file__).resolve().parent.parent

# Bootstrap: motor root on sys.path so imports from scripts/ resolve both when
# this script runs directly and when imported from elsewhere.
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

from scripts.reconcile_portable_memory import PROMOTED_VIA_ACCEPTED  # noqa: E402


ARCHIVE_DIR_REL = Path(".agent/runtime/memory/archive")


def find_archive_files(root: Path) -> list[Path]:
    """Archive files trackeados (glob del arbol vivo, no del argv)."""
    archive_dir = root / ARCHIVE_DIR_REL
    if not archive_dir.is_dir():
        return []
    return sorted(archive_dir.glob("observations.*.jsonl"))


def _needs_backfill(entry: dict[str, Any]) -> bool:
    """Return True if the entry lacks an accepted promoted_via."""
    pv = entry.get("promoted_via")
    return pv is None or pv not in PROMOTED_VIA_ACCEPTED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "--root",
        default=str(MOTOR_ROOT),
        help="raiz del workspace donde vive el archive (default: raiz del motor)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="escribir los cambios (por defecto: dry-run)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    archive_files = find_archive_files(root)

    if not archive_files:
        print(
            f"[backfill] OK: 0 archive file(s) en {root} "
            f"({ARCHIVE_DIR_REL.as_posix()}/observations.*.jsonl) -- "
            "nada que migrar."
        )
        return 0

    total_migrated = 0
    total_skipped = 0

    for path in archive_files:
        lines = path.read_text(encoding="utf-8").splitlines()
        entries = []
        migrated_in_file = 0

        for line in lines:
            if not line.strip():
                entries.append(line)
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                # No podemos modificar JSON corrupto; lo dejamos tal cual.
                entries.append(line)
                continue

            if _needs_backfill(entry):
                entry["promoted_via"] = "legacy_backfill"
                migrated_in_file += 1
            entries.append(json.dumps(entry, ensure_ascii=False))

        if migrated_in_file > 0:
            if args.apply:
                path.write_text(
                    "\n".join(entries) + "\n" if entries else "",
                    encoding="utf-8",
                )
                print(
                    f"[backfill] MIGRADAS: {migrated_in_file} entradas en "
                    f"{path.relative_to(root)}"
                )
            else:
                print(
                    f"[backfill] DRY-RUN: migraria {migrated_in_file} entradas en "
                    f"{path.relative_to(root)}"
                )

        total_migrated += migrated_in_file
        total_skipped += len(entries) - migrated_in_file

    action = "MIGRADAS" if args.apply else "DRY-RUN: migraria"
    print(
        f"[backfill] {action}: {total_migrated} de {total_migrated + total_skipped} "
        f"entradas en {len(archive_files)} archivo(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
