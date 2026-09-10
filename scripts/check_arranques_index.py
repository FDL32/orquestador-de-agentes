"""WOT-2026-067m: barrera del INDICE de `arranques/_archive/` (cuadre en AMBAS direcciones).

CONTRATO (DEC-067L-002). El historico NO CITADO de `orchestrator_pipeline/arranques/`
se MUEVE a `arranques/_archive/` con una fila por fichero en `_archive/INDEX.md`.
Ese indice es lo que hace el historico CONSULTABLE y no un vertedero; y para que sea
BARRERA y no norma, algo tiene que INVOCARLO solo. Este modulo es la barrera: el
invocador es `run_arranques_index_check` en `scripts/prepush_check.py` (cierre),
patron del precedente `run_flight_plan_collision_check` (guard del motor que corre
sobre el `project_root` del destino).

EL INVARIANTE ES DE CUADRE, en las DOS direcciones:
  (1) un fichero que vive en `_archive/` SIN fila en `INDEX.md` FALLA; y
  (2) una fila que nombra un fichero AUSENTE de `_archive/` FALLA.
Una sola direccion dejaria pasar la mitad de la familia: el fichero movido y no
indexado (la traza perdida) o la fila huerfana que promete un fichero que ya no esta.

NON-GOAL: NO mueve, NO escribe, NO repara. Es READ-ONLY; el que mueve es
`scripts/archive_arranques.py` y el que repara un desajuste es el operador.

Docstring-as-spec:
  Before: `arranques_dir` es la carpeta `orchestrator_pipeline/arranques/` resoluble.
      `_archive/` puede no existir (antes del primer archivado): entonces SKIP.
  During: lee el NOMBRE de cada fichero de `_archive/` (excluido `INDEX.md`) y la
      PRIMERA celda de cada fila de tabla de `INDEX.md`. Sin I/O de escritura.
  After: devuelve la lista de hallazgos (vacia si cuadra); `main()` imprime el
      DENOMINADOR (ficheros y filas) y devuelve exit 1 si hay >=1 hallazgo, 0 si no,
      0 con SKIP nombrado si `_archive/` no existe. Nunca un verde mudo.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ARCHIVE_DIRNAME = "_archive"
INDEX_FILENAME = "INDEX.md"
_HEADER_FIRST_CELL = "archivo"


def _table_cells(line: str) -> list[str] | None:
    """Celda de una fila de tabla markdown, o None si la linea no es una fila."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def parse_index_filenames(index_path: Path) -> list[str]:
    """Nombres de fichero declarados en la PRIMERA columna de `INDEX.md`.

    Before: `index_path` puede no existir (indice aun no creado).
    During: lee el fichero en UTF-8 y descarta cabecera (`Archivo`) y separador
        (`---`). Solo cuenta filas de tabla con primera celda no vacia.
    After: lista de nombres en el orden del fichero. AUSENTE -> [] ("sin filas
        todavia"), que es fail-closed mientras haya ficheros en disco: cada uno
        saldra como "sin fila". PRESENTE PERO ILEGIBLE -> OSError propagado
        (WOT-2026-067n): degradarlo a [] seria fail-OPEN con `_archive/` vacio,
        porque `rows=[]` y `disco=vacio` no producen ningun hallazgo y el guard
        daria verde sin haber podido leer nada. Un INDEX corrupto ya reventaba
        via UnicodeDecodeError (no es OSError); esto cierra la via de permisos.
    """
    if not index_path.exists():
        return []
    text = index_path.read_text(encoding="utf-8")
    names: list[str] = []
    for line in text.splitlines():
        cells = _table_cells(line)
        if not cells:
            continue
        first = cells[0]
        if not first or first.lower() == _HEADER_FIRST_CELL:
            continue
        if set(first) <= {"-", ":", " "}:
            continue
        names.append(first)
    return names


def check_index_consistency(arranques_dir: Path) -> list[str]:
    """Hallazgos de cuadre entre `_archive/` y su `INDEX.md` (AMBAS direcciones).

    Before: `arranques_dir` es `orchestrator_pipeline/arranques/`.
    During: si `_archive/` no existe, no hay nada que cuadrar -> []. Si existe, lee
        los ficheros de disco (excluido INDEX.md) y las filas del indice; cruza los
        dos conjuntos.
    After: lista ordenada de hallazgos, uno por desajuste, en las dos direcciones.
        Vacia = cuadra. Read-only.
    """
    archive = arranques_dir / ARCHIVE_DIRNAME
    if not archive.is_dir():
        return []
    on_disk = sorted(
        p.name for p in archive.iterdir() if p.is_file() and p.name != INDEX_FILENAME
    )
    rows = parse_index_filenames(archive / INDEX_FILENAME)
    row_set = set(rows)
    disk_set = set(on_disk)

    findings = [
        f"{ARCHIVE_DIRNAME}/{name} vive en disco SIN fila en "
        f"{ARCHIVE_DIRNAME}/{INDEX_FILENAME}"
        for name in on_disk
        if name not in row_set
    ]
    findings.extend(
        f"{ARCHIVE_DIRNAME}/{INDEX_FILENAME} nombra {name!r}, ausente de "
        f"{ARCHIVE_DIRNAME}/"
        for name in dict.fromkeys(rows)
        if name not in disk_set
    )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "FALLA si un fichero de arranques/_archive/ no tiene fila en INDEX.md, "
            "o si una fila nombra un fichero ausente (WOT-2026-067m, DEC-067L-002)."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="repo_destino cuyo orchestrator_pipeline/arranques/_archive/ se audita.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emitir el resultado en formato JSON (machine-readable).",
    )
    args = parser.parse_args(argv)

    arranques = Path(args.project_root) / "orchestrator_pipeline" / "arranques"
    archive = arranques / ARCHIVE_DIRNAME
    if not archive.is_dir():
        message = f"SKIP: no existe {archive} (sin historico archivado)."
        if args.json:
            print(json.dumps({"ok": True, "skip": message}))
        else:
            print(message)
        return 0

    findings = check_index_consistency(arranques)
    denominador = (
        f"{len([p for p in archive.iterdir() if p.is_file() and p.name != INDEX_FILENAME])} "
        f"fichero(s) en {ARCHIVE_DIRNAME}/, "
        f"{len(parse_index_filenames(archive / INDEX_FILENAME))} fila(s) en {INDEX_FILENAME}"
    )

    if args.json:
        print(
            json.dumps(
                {"ok": not findings, "denominator": denominador, "findings": findings}
            )
        )
    else:
        print(f"[arranques-index] denominador: {denominador}")
        if findings:
            print(f"[FAIL] {len(findings)} desajuste(s) INDEX <-> {ARCHIVE_DIRNAME}/:")
            for finding in findings:
                print(f"  - {finding}")
        else:
            print(f"[OK] {INDEX_FILENAME} cuadra con {ARCHIVE_DIRNAME}/")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
