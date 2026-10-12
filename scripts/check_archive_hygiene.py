#!/usr/bin/env python3
"""Auditoria de higiene del archive de memoria portable (WOT-2026-094c).

Check de SOLO LECTURA sobre los archives trackeados
`.agent/runtime/memory/archive/observations.YYYY-MM.jsonl` de una raiz
(motor o destino). Lista por archive las entradas sin `id`, los `id`
repetidos y los pares `(topic, source_ticket)` repetidos, y falla (exit 1)
solo ante DUPLICACION NUEVA respecto de una linea base fechada.

Linea base de referencia (MEM_CM_G7, 2026-10-07, medido con script de
solo lectura sobre el corpus de ese dia):

    motor:   4 archives, 455 entradas, 78 sin id, 77 id repetidos, 87 pares repetidos
    destino: 170 entradas, 154 sin id, 1 id repetido, 16 pares repetidos

Son referencia FECHADA, no criterio de aceptacion: el total de entradas y
el numero de archives crecen legitimamente (entradas nuevas con `id`), asi
que NO participan del veredicto. El veredicto compara SOLO las metricas de
higiene (sin id / id repetidos / pares repetidos / lineas no parseables)
contra la baseline de la raiz auditada: exit 0 si ninguna crece, exit 1 si
alguna supera la baseline (duplicacion nueva).

Definiciones (calibradas contra MEM_CM_G7: reproducen 78/77/87 exactos
sobre el archive del motor en 2026-10-12):
- entrada: linea no vacia que parsea como objeto JSON. Las lineas que no
  parsean se listan como `parse_errors` y hacen fallar el check
  (corrupcion del JSONL es hallazgo, no ruido).
- sin id: entrada sin campo `id`, o con `id` vacio/no-string.
- id repetidos: numero de valores de `id` que aparecen en 2+ entradas del
  universo de archives de la raiz (entre meses incluido). En el corpus
  medido cada id duplicado aparece exactamente 2 veces, por lo que coincide
  con el conteo de ocurrencias extra.
- pares repetidos: numero de pares `(topic, source_ticket)` distintos que
  aparecen en 2+ entradas (ambos campos string no vacios).

La limpieza de los duplicados identicos queda PROPUESTA, no aplicada: este
script no escribe nada. No modifica el schema de observaciones, no toca la
consolidacion de memoria ni `--promote-id`.

Uso:
    python scripts/check_archive_hygiene.py [--root PATH]
                                            [--profile {motor,destino}]
                                            [--baseline PATH.json]

Uso:
- `--root`    raiz a auditar (default: la raiz del motor que contiene este
              script). Los archives se buscan en
              `<root>/.agent/runtime/memory/archive/`.
- `--profile` baseline embebida a comparar (default: motor). Los numeros
              del destino son la referencia fechada documentada arriba;
              si el destino quiere enforcement propio, pase `--baseline`.
- `--baseline` JSON con {"missing_id": N, "duplicate_ids": N,
              "duplicate_pairs": N, "parse_errors": N} que sustituye a la
              baseline embebida del perfil.

Salida:
- Exit 0: ninguna metrica de higiene supera la baseline (limpio o mejorado).
- Exit 1: alguna metrica supera la baseline (duplicacion nueva), o hay
  lineas JSONL no parseables, o el archive no existe siendo un directorio.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ARCHIVE_REL_DIR = Path(".agent") / "runtime" / "memory" / "archive"
ARCHIVE_GLOB = "observations.*.jsonl"

# Linea base fechada (MEM_CM_G7, 2026-10-07). `entries` y `archives` son
# CONTEXTO de la referencia, no criterio: crecen legitimamente. Solo las
# metricas de higiene participan del veredicto.
BASELINES: dict[str, dict[str, int]] = {
    "motor": {
        "archives": 4,
        "entries": 455,
        "missing_id": 78,
        "duplicate_ids": 77,
        "duplicate_pairs": 87,
        "parse_errors": 0,
    },
    "destino": {
        "archives": 0,  # no medido como archivos separados en MEM_CM_G7
        "entries": 170,
        "missing_id": 154,
        "duplicate_ids": 1,
        "duplicate_pairs": 16,
        "parse_errors": 0,
    },
}

# Metricas que DECIDEN el exit code. `entries`/`archives` quedan fuera a
# proposito (crecimiento legitimo, ver docstring).
DECIDING_METRICS = ("missing_id", "duplicate_ids", "duplicate_pairs", "parse_errors")


@dataclass
class ArchiveFileReport:
    """Metricas de higiene de UN fichero de archive.

    Before: `path` existe y es un .jsonl legible (o no existe: se reporta
    como vacio).
    During: lee el fichero en modo texto UTF-8, parsea cada linea no vacia
    como objeto JSON y clasifica: entradas sin `id` (con numero de linea),
    valores de `id` repetidos DENTRO del fichero y pares
    (topic, source_ticket) repetidos DENTRO del fichero. Solo lectura.
    After: campos poblados; `parse_errors` lista "linea N: motivo". El
    conteo ENTRE ficheros (meses) lo hace el agregador, no esta clase.
    """

    name: str
    entries: int = 0
    missing_id_lines: list[int] = field(default_factory=list)
    # Full occurrence maps (RAW counts, not filtered): cross-file duplicate
    # detection must see values that appear once here and once elsewhere.
    id_counts: dict[str, int] = field(default_factory=dict)
    pair_counts: dict[str, int] = field(default_factory=dict)
    # Filtered views for the per-file listing (count > 1 within THIS file).
    duplicate_ids: dict[str, int] = field(default_factory=dict)
    duplicate_pairs: dict[str, int] = field(default_factory=dict)
    parse_errors: list[str] = field(default_factory=list)


def _pair_key(topic: Any, source_ticket: Any) -> str | None:
    """Return the canonical "topic | source_ticket" key, or None if absent.

    Both fields must be non-empty strings to form a pair; anything else
    (missing, empty, non-string) contributes no pair.
    """
    if not isinstance(topic, str) or not isinstance(source_ticket, str):
        return None
    topic = topic.strip()
    source_ticket = source_ticket.strip()
    if not topic or not source_ticket:
        return None
    return f"{topic} | {source_ticket}"


def scan_archive_file(path: Path) -> ArchiveFileReport:
    """Scan ONE archive jsonl file (see ArchiveFileReport contract)."""
    report = ArchiveFileReport(name=path.name)
    if not path.exists():
        return report

    id_counts: dict[str, int] = {}
    pair_counts: dict[str, int] = {}

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        report.parse_errors.append(f"lectura: {e}")
        return report

    for line_num, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            report.parse_errors.append(f"linea {line_num}: {e}")
            continue
        if not isinstance(record, dict):
            report.parse_errors.append(
                f"linea {line_num}: entrada debe ser objeto JSON, "
                f"no {type(record).__name__}"
            )
            continue

        report.entries += 1
        entry_id = record.get("id")
        if isinstance(entry_id, str) and entry_id.strip():
            id_counts[entry_id.strip()] = id_counts.get(entry_id.strip(), 0) + 1
        else:
            report.missing_id_lines.append(line_num)

        pair = _pair_key(record.get("topic"), record.get("source_ticket"))
        if pair is not None:
            pair_counts[pair] = pair_counts.get(pair, 0) + 1

    report.id_counts = dict(sorted(id_counts.items()))
    report.pair_counts = dict(sorted(pair_counts.items()))
    report.duplicate_ids = {
        value: count for value, count in report.id_counts.items() if count > 1
    }
    report.duplicate_pairs = {
        pair: count for pair, count in report.pair_counts.items() if count > 1
    }
    return report


def scan_archive_root(root: Path) -> list[ArchiveFileReport]:
    """Scan every archive jsonl under `<root>/.agent/runtime/memory/archive/`.

    Returns one ArchiveFileReport per file, sorted by file name. A missing
    archive directory yields an empty list (a root without archive is clean).
    """
    archive_dir = root / ARCHIVE_REL_DIR
    if not archive_dir.is_dir():
        return []
    files = sorted(archive_dir.glob(ARCHIVE_GLOB))
    return [scan_archive_file(path) for path in files]


def _cross_file_counts(
    reports: list[ArchiveFileReport],
) -> tuple[dict[str, int], dict[str, int]]:
    """Sum id/pair occurrence counts ACROSS files of the root.

    A value that appears once in month A and once in month B is duplicated
    ENTRE meses (the baseline's own definition), so per-file max would miss
    it: the root-level count is the SUM over files, then distinct values
    with total > 1 are the duplicates.
    """
    id_counts: dict[str, int] = {}
    pair_counts: dict[str, int] = {}
    for report in reports:
        for value, count in report.id_counts.items():
            id_counts[value] = id_counts.get(value, 0) + count
        for pair, count in report.pair_counts.items():
            pair_counts[pair] = pair_counts.get(pair, 0) + count
    return id_counts, pair_counts


def aggregate(reports: list[ArchiveFileReport]) -> dict[str, int]:
    """Fold per-file reports into root-level totals for the deciding metrics.

    Duplicate ids and pairs are counted ACROSS files (see
    _cross_file_counts): the total is the number of DISTINCT values/pairs
    whose summed occurrence count over the root's whole archive universe
    exceeds 1.
    """
    missing_id = 0
    parse_errors = 0
    entries = 0
    for report in reports:
        entries += report.entries
        missing_id += len(report.missing_id_lines)
        parse_errors += len(report.parse_errors)
    id_counts, pair_counts = _cross_file_counts(reports)
    return {
        "archives": len(reports),
        "entries": entries,
        "missing_id": missing_id,
        "duplicate_ids": sum(1 for count in id_counts.values() if count > 1),
        "duplicate_pairs": sum(1 for count in pair_counts.values() if count > 1),
        "parse_errors": parse_errors,
    }


def exceeded_metrics(
    current: dict[str, int], baseline: dict[str, int]
) -> dict[str, tuple[int, int]]:
    """Return {metric: (current, baseline)} for deciding metrics that grew.

    Only DECIDING_METRICS participate; growth (current > baseline) means NEW
    duplication relative to the dated baseline. Equal or lower counts are
    clean (equal: same debt; lower: someone cleaned up).
    """
    out: dict[str, tuple[int, int]] = {}
    for metric in DECIDING_METRICS:
        base = int(baseline.get(metric, 0))
        now = int(current.get(metric, 0))
        if now > base:
            out[metric] = (now, base)
    return out


def _print_labeled_list(header: str, items: list[str]) -> None:
    """Print a labeled block: the header, or "0" when there are no items."""
    if not items:
        print(f"   {header}: 0")
        return
    print(f"   {header} ({len(items)}):")
    for item in items:
        print(f"     {item}")


def _print_file_report(report: ArchiveFileReport) -> None:
    """Print one archive file's listing (DoD a: per-archive detail)."""
    print(f"-- {report.name}: {report.entries} entradas")
    _print_labeled_list(
        "sin id",
        [f"lineas {report.missing_id_lines}"] if report.missing_id_lines else [],
    )
    _print_labeled_list(
        "id repetidos",
        [f"{value} x{count}" for value, count in report.duplicate_ids.items()],
    )
    _print_labeled_list(
        "pares (topic | source_ticket) repetidos",
        [f"{pair} x{count}" for pair, count in report.duplicate_pairs.items()],
    )
    _print_labeled_list("lineas no parseables", report.parse_errors)


def _print_cross_file_duplicates(reports: list[ArchiveFileReport]) -> None:
    """Print the root-wide duplicate values (in-file and across months)."""
    id_counts, pair_counts = _cross_file_counts(reports)
    cross_dup_ids = {
        value: count for value, count in sorted(id_counts.items()) if count > 1
    }
    cross_dup_pairs = {
        pair: count for pair, count in sorted(pair_counts.items()) if count > 1
    }
    _print_labeled_list(
        "id repetidos entre archivos", [f"{v} x{c}" for v, c in cross_dup_ids.items()]
    )
    _print_labeled_list(
        "pares repetidos entre archivos",
        [f"{p} x{c}" for p, c in cross_dup_pairs.items()],
    )


def _print_report(reports: list[ArchiveFileReport], root: Path) -> dict[str, int]:
    """Print the per-archive listing and return the root aggregate."""
    print(f"Raiz auditada: {root.resolve()}")
    archive_dir = root / ARCHIVE_REL_DIR
    if not reports:
        print(f"Sin archives en {archive_dir} (limpio: 0 entradas)")
    for report in reports:
        _print_file_report(report)

    totals = aggregate(reports)
    print(
        "TOTAL raiz: archives={archives} entradas={entries} "
        "sin_id={missing_id} id_repetidos={duplicate_ids} "
        "pares_repetidos={duplicate_pairs} no_parseables={parse_errors}".format(
            **totals
        )
    )
    _print_cross_file_duplicates(reports)
    return totals


def main(argv: list[str] | None = None) -> int:
    """CLI entry. See module docstring for the exit contract."""
    parser = argparse.ArgumentParser(
        description=(
            "Higiene del archive de memoria portable: lista sin-id, ids y "
            "pares repetidos; exit 1 solo ante duplicacion nueva vs baseline."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Raiz a auditar (default: la raiz del motor de este script)",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(BASELINES),
        default="motor",
        help="Baseline embebida a comparar (default: motor)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=(
            "JSON con {missing_id, duplicate_ids, duplicate_pairs, "
            "parse_errors} que sustituye a la baseline del perfil"
        ),
    )
    args = parser.parse_args(argv)

    baseline = dict(BASELINES[args.profile])
    if args.baseline is not None:
        try:
            override = json.loads(args.baseline.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"ERROR: --baseline ilegible: {e}", file=sys.stderr)
            return 1
        if not isinstance(override, dict):
            print("ERROR: --baseline debe ser un objeto JSON", file=sys.stderr)
            return 1
        for metric in DECIDING_METRICS:
            baseline[metric] = int(override.get(metric, 0))

    reports = scan_archive_root(args.root)
    totals = _print_report(reports, args.root)

    print(
        "Baseline ({profile}, MEM_CM_G7 2026-10-07): "
        "sin_id={missing_id} id_repetidos={duplicate_ids} "
        "pares_repetidos={duplicate_pairs} no_parseables={parse_errors}".format(
            profile=args.profile,
            missing_id=baseline["missing_id"],
            duplicate_ids=baseline["duplicate_ids"],
            duplicate_pairs=baseline["duplicate_pairs"],
            parse_errors=baseline["parse_errors"],
        )
    )

    exceeded = exceeded_metrics(totals, baseline)
    if exceeded:
        print("DUPLICACION NUEVA detectada respecto de la baseline:", file=sys.stderr)
        for metric, (now, base) in exceeded.items():
            print(f"  {metric}: {now} > {base}", file=sys.stderr)
        return 1

    print("[OK] Sin duplicacion nueva respecto de la baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
