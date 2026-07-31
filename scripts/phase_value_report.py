#!/usr/bin/env python3
"""Informe agregado del scorecard por fase x task_type x backend (WOT-2026-044q).

Named a *report*, not a ``check_``: NUNCA bloquea (exit 0 salvo root invalido) y
NO se cablea en ningun hook. El prefijo ``check_``/``validate_``/``guard_`` esta
reservado por `check_guard_wiring` (WOT-2026-024u) para barreras cableadas; usarlo
aqui seria una falsa promesa de barrera. Es una herramienta de consulta BAJO
DEMANDA -- cablear un informe en pre-commit seria friccion sin barrera.

Before: el destino tiene ``.agent/runtime/ensemble/scorecard.jsonl``, que
    `ensemble_dispatch` va escribiendo por append en cada ronda de fan-out.
    Requiere ``--project-root`` apuntando a ese workspace.

During: parsea el jsonl READ-ONLY y agrega por ``task_type`` x ``phase`` x
    ``backend_key``, contando rondas, rondas sustantivas y la MEDIANA de
    ``latency_ms``. Ni escribe ni reordena el fichero.

After: imprime a stdout la linea de denominador y la tabla, y devuelve 0. Devuelve
    2 si ``--project-root`` falta o no es un directorio (mismo contrato que
    `pool_permanence_metric`). No lanza ante fichero ausente, vacio o corrupto.

Por que un DENOMINADOR y no solo una tabla
------------------------------------------
Medido 2026-07-31 sobre el scorecard real: de 827 filas, **430 (52%) no tienen
``phase`` ni ``backend_key``** -- son legacy, anteriores a que esos campos
existieran. Una tabla que dijera "CONTRACT_AUDIT: 113 rondas" callando que
descarto medio fichero es indistinguible de una que no miro nada
(WOT-2026-043l). Por eso el conteo de descartes se imprime SIEMPRE, y en linea
propia antes de la tabla.

El mismo defecto, un nivel mas abajo: ``is_substantive`` es FAIL-OPEN (una fila
sin ``output_chars`` cuenta como sustantiva). Medido: 206 de 394 "sustantivas" lo
son solo por ausencia de dato. Publicar 394 a secas contaria 206 filas que nadie
midio, asi que se reportan por separado.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(MOTOR_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT / "scripts"))

# SCORECARD_REL se IMPORTA (no se duplica la ruta canonica); `is_substantive` se
# IMPORTA (no se reimplementa): dos definiciones divergentes de "sustantiva"
# harian que este informe contradiga a `check_loop_execution` sobre las MISMAS
# filas. El PARSEO, en cambio, es propio a proposito -- ver `_iter_rows`.
from check_loop_execution import is_substantive  # noqa: E402
from ensemble_dispatch import SCORECARD_REL  # noqa: E402


@dataclass
class Cell:
    """One aggregated cell: a (task_type, phase, backend_key) triple."""

    task_type: str
    phase: str
    backend_key: str
    rounds: int = 0
    substantive: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def latency_p50_ms(self) -> float | None:
        """MEDIAN latency, or None if no row of this cell carried one.

        Median, not mean, and the number is why: measured over the real eligible
        rows (n=401), mean=31762.3ms vs median=21085.0ms -- **mean/median = 1.51x**
        with a max of 118669ms. The distribution has a long tail, so the mean is
        inflated ~51% by a handful of slow runs and describes the typical case
        badly.
        """
        return statistics.median(self.latencies) if self.latencies else None


@dataclass
class Report:
    """The full aggregation plus the denominator that makes it honest."""

    total_rows: int = 0
    eligible: int = 0
    dropped_legacy: int = 0
    dropped_unparsable: int = 0
    substantive_measured: int = 0
    substantive_fail_open: int = 0
    mute: int = 0
    cells: list[Cell] = field(default_factory=list)


def _iter_rows(path: Path) -> tuple[list[dict], int]:
    """Parse the jsonl defensively; return (rows, unparsable_count).

    NOT `_read_scorecard`, and the reason is measured: that helper does
    ``json.loads`` per line with no ``try/except`` (``ensemble_dispatch.py``
    around :1015-1022) and raises ``JSONDecodeError`` on a half-written line --
    verified on a fixture. The scorecard is appended concurrently, so a truncated
    last line is a real state, not a hypothetical one. Since `ensemble_dispatch`
    is a Forbidden Surface for this ticket, the defensive parse lives here while
    the canonical PATH (``SCORECARD_REL``) is still imported rather than copied.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], 0
    rows: list[dict] = []
    unparsable = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            unparsable += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            unparsable += 1
    return rows, unparsable


def build_report(project_root: Path) -> Report:
    """Aggregate the scorecard READ-ONLY. Never raises on bad input."""
    rows, unparsable = _iter_rows(project_root / SCORECARD_REL)
    report = Report(total_rows=len(rows), dropped_unparsable=unparsable)
    buckets: dict[tuple[str, str, str], Cell] = {}

    for row in rows:
        phase = row.get("phase")
        backend = row.get("backend_key")
        # A legacy row carries neither field; it is DROPPED and COUNTED, never
        # folded into an "unknown" bucket -- inventing a category for missing data
        # would let the table look complete while describing nothing.
        if not phase or not backend:
            report.dropped_legacy += 1
            continue
        report.eligible += 1

        if is_substantive(row):
            # FAIL-OPEN split: a row with no `output_chars` is substantive only
            # because the field is absent. Merging both would republish, one level
            # down, the denominator defect this report exists to expose.
            if row.get("output_chars") is None:
                report.substantive_fail_open += 1
            else:
                report.substantive_measured += 1
        else:
            report.mute += 1

        key = (str(row.get("task_type") or "?"), str(phase), str(backend))
        cell = buckets.get(key)
        if cell is None:
            cell = Cell(task_type=key[0], phase=key[1], backend_key=key[2])
            buckets[key] = cell
        cell.rounds += 1
        if is_substantive(row):
            cell.substantive += 1
        latency = row.get("latency_ms")
        # A missing latency is EXCLUDED, never imputed as 0: a fake zero would
        # drag the median down and understate the real cost of the cell.
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            cell.latencies.append(float(latency))

    # Only cells with data: the cartesian product is ~343 combinations over ~397
    # eligible rows, so a full grid would be mostly zeros and would bury the few
    # cells that carry signal.
    report.cells = sorted(buckets.values(), key=lambda c: (-c.rounds, c.phase))
    return report


def format_denominator(report: Report) -> str:
    """The denominator line, in the shape the contract fixes.

    Fixed format on purpose: "publish the denominator" without a shape lets it be
    buried in a comment or a debug log the reader never sees.
    """
    extra = ""
    if report.dropped_unparsable:
        extra = f" descartadas_ilegibles={report.dropped_unparsable}"
    return (
        f"[denominador] filas={report.total_rows} elegibles={report.eligible} "
        f"descartadas_legacy={report.dropped_legacy} "
        f"(sin phase o sin backend_key){extra} | "
        f"sustantivas_medidas={report.substantive_measured} "
        f"sustantivas_fail_open={report.substantive_fail_open} "
        f"mudas={report.mute}"
    )


def format_table(report: Report) -> str:
    """Render the sparse table, or say plainly that there is nothing to show."""
    if not report.cells:
        if report.total_rows:
            return (
                "sin datos agregables: hay filas, pero ninguna trae phase y "
                "backend_key (ver denominador)"
            )
        return "sin datos (0 filas en scorecard)"
    header = (
        f"{'task_type':<16} | {'phase':<16} | {'backend':<8} | "
        f"{'rondas':>6} | {'sustant':>7} | {'p50_ms':>9}"
    )
    lines = [header, "-" * len(header)]
    for c in report.cells:
        p50 = f"{c.latency_p50_ms:.0f}" if c.latency_p50_ms is not None else "-"
        lines.append(
            f"{c.task_type:<16} | {c.phase:<16} | {c.backend_key:<8} | "
            f"{c.rounds:>6} | {c.substantive:>7} | {p50:>9}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns 0 (informative) or 2 on an invalid root."""
    parser = argparse.ArgumentParser(
        description=(
            "Informe agregado del scorecard por fase x task_type x backend "
            "(read-only, informativo). No es un gate y no se cablea."
        )
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="Workspace que contiene .agent/runtime/ensemble/scorecard.jsonl",
    )
    args = parser.parse_args(argv)
    project_root = Path(args.project_root)
    if not project_root.is_dir():
        print(f"[ERROR] project-root no existe: {project_root}", file=sys.stderr)
        return 2
    report = build_report(project_root)
    print(format_denominator(report))
    print(format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
