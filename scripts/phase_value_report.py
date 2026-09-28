#!/usr/bin/env python3
"""Informe agregado del scorecard por fase x task_type x backend x lens_scope.

(WOT-2026-044q; ejes ampliados por WOT-2026-055o).

Named a *report*, not a ``check_``: NUNCA bloquea (exit 0 salvo root invalido) y
NO se cablea en ningun hook. El prefijo ``check_``/``validate_``/``guard_`` esta
reservado por `check_guard_wiring` (WOT-2026-024u) para barreras cableadas; usarlo
aqui seria una falsa promesa de barrera. Es una herramienta de consulta BAJO
DEMANDA -- cablear un informe en pre-commit seria friccion sin barrera.

Before: el destino tiene ``.agent/runtime/ensemble/scorecard.jsonl``, que
    `ensemble_dispatch` va escribiendo por append en cada ronda de fan-out.
    Requiere ``--project-root`` apuntando a ese workspace.

During: parsea el jsonl READ-ONLY y agrega por ``task_type`` x ``phase`` x
    ``backend_key`` x ``lens_scope``, contando rondas, rondas sustantivas y la
    MEDIANA de ``latency_ms``. Cruza ademas cada adjudicacion con su ronda via
    la CLAVE HACIA ADELANTE que `adjudicate()` escribe desde WOT-2026-055o
    (``phase``+``loop_id``+``backend_key``+``lens_scope`` copiados de la
    fuente). Ni escribe ni reordena el fichero.

After: imprime a stdout la linea de denominador, la tabla, y devuelve 0.
    Devuelve 2 si ``--project-root`` falta o no es un directorio (mismo
    contrato que `pool_permanence_metric`). No lanza ante fichero ausente,
    vacio o corrupto.

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

Un tercer eje, misma regla (WOT-2026-055o): ``lens_scope``. Una ronda con ojos y
otra ciega del MISMO modelo caian en la misma celda y el informe mezclaba dos
poblaciones con tasas de acierto distintas. La ausencia del campo se trata como
la de ``phase``/``backend_key``: fila DESCARTADA y CONTADA, nunca un valor
``"desconocido"`` inventado (fabricar una categoria para datos ausentes
deformaria el denominador que este informe existe para proteger).

Y un cuarto conteo, el de las COHORTES: la eficacia (adoptadas/falsos) solo se
publica sobre cohortes COMPLETOS -- una adjudicacion cuya ronda fuente no
existe no mide nada --, con el denominador de intentados vs completos en linea
propia. Las adjudicaciones ANTERIORES a WOT-2026-055o no llevan la clave
hacia adelante y se declaran NO-UNIBLES; emparejarlas por heuristica de etiqueta
libre esta PROHIBIDO por decision del operador 2026-09-23 (el join aproximado
daba 144/257 sin match unico).
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
from ensemble_dispatch import (  # noqa: E402
    ADJUDICATED_OUTCOMES,
    SCORECARD_REL,
)


# Los 4 ejes de la CELDA y de la clave de cohorte (WOT-2026-055o).
_COHORT_FIELDS = ("phase", "loop_id", "backend_key", "lens_scope")

# Outcomes que cuentan como "falso" en la columna adm/fals. MISMO criterio que
# `regenerate_leaders`/`regenerate_family_leaders` (no se reinventa): un
# `error-factual` adoptado como hallazgo es un falso, igual que un
# `falso-positivo`.
_FALSE_OUTCOMES = frozenset({"falso-positivo", "error-factual"})


@dataclass
class Cell:
    """One aggregated cell: a (task_type, phase, backend_key, lens_scope) tuple."""

    task_type: str
    phase: str
    backend_key: str
    lens_scope: str
    rounds: int = 0
    substantive: int = 0
    latencies: list[float] = field(default_factory=list)
    # Eficacia SOLO sobre cohortes completos (adjudicacion unida a su ronda);
    # 0/0 es el estado sano de una celda sin adjudicacion, no un dato perdido.
    adoptadas: int = 0
    falsos: int = 0

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

    @property
    def efficacy(self) -> str:
        """``adoptadas/falsos``, or ``-`` when this cell has no complete cohort."""
        if not (self.adoptadas or self.falsos):
            return "-"
        return f"{self.adoptadas}/{self.falsos}"


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
    # Contadores de adjudicacion (WOT-2026-055o). Filas vs cohortes: dos
    # poblaciones distintas y ambas se publican para que no se confundan.
    adjudications_total: int = 0
    adjudications_joinable: int = 0
    adjudications_unjoinable_legacy: int = 0
    cohortes_intentadas: int = 0
    cohortes_completas: int = 0
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


def _cell_key(row: dict) -> tuple[str, str, str, str] | None:
    """The 4-eje key of a row, or None if ANY eje falta.

    Mismo criterio de fail-closed que el resto del modulo: sin el eje completo
    no hay celda, porque inventar un valor ausente fabricaria una poblacion que
    nadie midio.
    """
    phase = row.get("phase")
    backend = row.get("backend_key")
    lens_scope = row.get("lens_scope")
    if not phase or not backend or not lens_scope:
        return None
    return (
        str(row.get("task_type") or "?"),
        str(phase),
        str(backend),
        str(lens_scope),
    )


def _cohort_key(row: dict) -> tuple[str, str, str, str] | None:
    """Las 4 claves hacia adelante de una adjudicacion, o None si falta ALGUNA.

    Un valor ausente (None o vacio) deja la fila NO-UNIBLE: no se empareja por
    aproximacion jamas (decision del operador 2026-09-23).
    """
    vals = tuple(row.get(f) for f in _COHORT_FIELDS)
    if not all(vals):
        return None
    return (str(vals[0]), str(vals[1]), str(vals[2]), str(vals[3]))


def _join_adjudications(rows: list[dict]) -> dict:
    """Cruza adjudicaciones <-> rondas por la clave hacia adelante.

    Before: `rows` es el scorecard ya parseado (orden de aparicion preservado).
    During: (1) indexa las rondas por su tupla de 4 ejes -- la ULTIMA ronda con
        esa tupla gana, mismo "por orden de aparicion" que `_adjudicated_cells`
        en `ensemble_dispatch`; (2) separa las adjudicaciones/supersede en
        unibles (las 4 claves pobladas) y NO-UNIBLES legacy; (3) deduplica las
        unibles por su clave de cohorte -- un `supersede` posterior PISA a la
        adjudicacion anterior de esa misma ronda, sin mutar filas; (4) resuelve
        cada cohorte contra su ronda fuente.
    After: dict con
        `total` / `joinable` / `unjoinable_legacy` (contadores de FILAS),
        `intentadas` / `completas` (contadores de COHORTES, ya deduplicadas),
        `sin_ronda` (= intentadas - completas) y `joined`: lista de
        `(adjudicacion_efectiva, ronda_fuente)` lista para agregar por celda.
        Nunca lanza y nunca empareja "casi": o la tupla casa exacta, o la
        cohorte queda sin ronda y se PUBLICA.
    """
    rounds: dict[tuple, dict] = {}
    for row in rows:
        if row.get("event") != "ronda":
            continue
        key = _cohort_key(row)
        if key is not None:
            rounds[key] = row

    result = {
        "total": 0,
        "joinable": 0,
        "unjoinable_legacy": 0,
        "intentadas": 0,
        "completas": 0,
        "sin_ronda": 0,
        "joined": [],
    }
    # Deduplicacion por cohorte: la ULTIMA adjudicacion de esa cohorte gana
    # (supersede pisa por orden de aparicion).
    effective: dict[tuple, dict] = {}
    for row in rows:
        if row.get("event") not in ("adjudicacion", "supersede"):
            continue
        result["total"] += 1
        key = _cohort_key(row)
        if key is None:
            result["unjoinable_legacy"] += 1
            continue
        result["joinable"] += 1
        if row.get("outcome") in ADJUDICATED_OUTCOMES:
            effective[key] = row

    result["intentadas"] = len(effective)
    for key, adj in effective.items():
        source = rounds.get(key)
        if source is None:
            continue
        result["completas"] += 1
        result["joined"].append((adj, source))
    result["sin_ronda"] = result["intentadas"] - result["completas"]
    return result


def _aggregate_rounds(rows: list[dict], report: Report) -> dict[tuple, Cell]:
    """Rellena los contadores de filas y devuelve las celdas de RONDA.

    Separado de `build_report` por COMPLEJIDAD (C901: el JOIN de cohorte hizo
    que la funcion combinara dos responsabilidades distintas); la semantica es
    exactamente la del bucle original de WOT-2026-044q, con el tercer eje
    (``lens_scope``, WOT-2026-055o) anadido a la tupla de celda.
    """
    buckets: dict[tuple[str, str, str, str], Cell] = {}
    for row in rows:
        # WOT-2026-055o: las adjudicaciones NO son rondas. Antes de este
        # ticket no hacia falta filtrarlas: no portaban `phase` ni
        # `backend_key` y caian solas en `dropped_legacy`. Desde el commit de
        # 055o `adjudicate()` copia la clave hacia adelante, con lo que una
        # adjudicacion ya reuniria los 4 ejes y se contaria como RONDA --
        # inflando la columna literalmente llamada `rondas` con filas de
        # adjudicacion. Se excluyen aqui y se cuentan en el denominador de
        # cohortes (mismo aviso que el docstring de `regenerate_leaders`:
        # "al medir adjudicaciones, filtra SIEMPRE por `event`").
        if row.get("event") in ("adjudicacion", "supersede"):
            continue
        key4 = _cell_key(row)
        # A legacy row misses an eje; it is DROPPED and COUNTED, never folded
        # into an "unknown" bucket -- inventing a category for missing data
        # would let the table look complete while describing nothing. Same rule
        # for the three axes: phase/backend_key (WOT-2026-044q) and
        # lens_scope (WOT-2026-055o).
        if key4 is None:
            report.dropped_legacy += 1
            continue
        report.eligible += 1

        substantive = is_substantive(row)
        if substantive:
            # FAIL-OPEN split: a row with no `output_chars` is substantive only
            # because the field is absent. Merging both would republish, one level
            # down, the denominator defect this report exists to expose.
            if row.get("output_chars") is None:
                report.substantive_fail_open += 1
            else:
                report.substantive_measured += 1
        else:
            report.mute += 1

        cell = buckets.get(key4)
        if cell is None:
            cell = Cell(
                task_type=key4[0],
                phase=key4[1],
                backend_key=key4[2],
                lens_scope=key4[3],
            )
            buckets[key4] = cell
        cell.rounds += 1
        if substantive:
            cell.substantive += 1
        latency = row.get("latency_ms")
        # A missing latency is EXCLUDED, never imputed as 0: a fake zero would
        # drag the median down and understate the real cost of the cell.
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            cell.latencies.append(float(latency))
    return buckets


def _apply_cohorts(buckets: dict[tuple, Cell], join: dict, report: Report) -> None:
    """Agrega adoptadas/falsos por celda SOLO sobre cohortes completas.

    El resultado del JOIN se publica entero en `report` (completas y
    pendientes); lo que NO se hace aqui es imputar: una adjudicacion sin ronda
    fuente no cuenta en ninguna celda, se queda en el denominador.
    """
    report.adjudications_total = join["total"]
    report.adjudications_joinable = join["joinable"]
    report.adjudications_unjoinable_legacy = join["unjoinable_legacy"]
    report.cohortes_intentadas = join["intentadas"]
    report.cohortes_completas = join["completas"]
    for adj, source in join["joined"]:
        source_key = _cell_key(source)
        cell = buckets.get(source_key) if source_key else None
        if cell is None:  # defensivo: la ronda cumplia las 4 claves
            continue
        if adj.get("outcome") == "adoptada":
            cell.adoptadas += 1
        elif adj.get("outcome") in _FALSE_OUTCOMES:
            cell.falsos += 1


def build_report(project_root: Path) -> Report:
    """Aggregate the scorecard READ-ONLY. Never raises on bad input."""
    rows, unparsable = _iter_rows(project_root / SCORECARD_REL)
    report = Report(total_rows=len(rows), dropped_unparsable=unparsable)

    buckets = _aggregate_rounds(rows, report)
    # JOIN ronda<->adjudicacion (WOT-2026-055o): la eficacia se agrega SOLO
    # sobre cohortes completas; el denominador de las demas se publica igual.
    _apply_cohorts(buckets, _join_adjudications(rows), report)

    # Only cells with data: the cartesian product is ~343 combinations over ~397
    # eligible rows, so a full grid would be mostly zeros and would bury the few
    # cells that carry signal.
    report.cells = sorted(buckets.values(), key=lambda c: (-c.rounds, c.phase))
    return report


def format_denominator(report: Report) -> str:
    """The denominator line, in the shape the contract fixes.

    Fixed format on purpose: "publish the denominator" without a shape lets it be
    buried in a comment or a debug log the reader never sees.

    The contracted line is emitted VERBATIM, with no extra fields spliced into it
    (MANAGER_REVIEW finding, lens deepseek): an earlier version inserted
    ``descartadas_ilegibles=N`` in the middle of it whenever a corrupt line showed
    up. Fixing a shape and then extending it is the same defect as not fixing one
    -- a consumer that parses this line positionally breaks. Unparsable lines are
    still reported (the contract requires counting them), but on their OWN line,
    where they cannot deform the contracted one.

    WOT-2026-055o: los contadores de cohorte van TAMBIEN en su propia linea, y
    SOLO cuando hay adjudicaciones que contar -- con cero adjudicaciones la
    linea no aparece, igual que la de ``descartadas_ilegibles`` solo aparece
    cuando hay lineas ilegibles.
    """
    line = (
        f"[denominador] filas={report.total_rows} elegibles={report.eligible} "
        f"descartadas_legacy={report.dropped_legacy} "
        f"(sin phase, sin backend_key o sin lens_scope) | "
        f"sustantivas_medidas={report.substantive_measured} "
        f"sustantivas_fail_open={report.substantive_fail_open} "
        f"mudas={report.mute}"
    )
    if report.dropped_unparsable:
        line += (
            f"\n[denominador] descartadas_ilegibles={report.dropped_unparsable} "
            f"(lineas que no parsean como JSON)"
        )
    if report.adjudications_total:
        line += (
            f"\n[denominador] adjudicaciones_excluidas_de_rondas="
            f"{report.adjudications_total} "
            f"cohortes_intentadas={report.cohortes_intentadas} "
            f"cohortes_completas={report.cohortes_completas} "
            f"(unibles_clave={report.adjudications_joinable} "
            f"no_unibles_legacy={report.adjudications_unjoinable_legacy} "
            f"sin_ronda={report.cohortes_intentadas - report.cohortes_completas})"
        )
    return line


def format_table(report: Report) -> str:
    """Render the sparse table, or say plainly that there is nothing to show."""
    if not report.cells:
        if report.total_rows:
            return (
                "sin datos agregables: hay filas, pero ninguna trae phase, "
                "backend_key y lens_scope (ver denominador)"
            )
        return "sin datos (0 filas en scorecard)"
    header = (
        f"{'task_type':<16} | {'phase':<16} | {'backend':<8} | {'scope':<12} | "
        f"{'rondas':>6} | {'sustant':>7} | {'adm/fals':>9} | {'p50_ms':>9}"
    )
    lines = [header, "-" * len(header)]
    for c in report.cells:
        p50 = f"{c.latency_p50_ms:.0f}" if c.latency_p50_ms is not None else "-"
        lines.append(
            f"{c.task_type:<16} | {c.phase:<16} | {c.backend_key:<8} | "
            f"{c.lens_scope:<12} | {c.rounds:>6} | {c.substantive:>7} | "
            f"{c.efficacy:>9} | {p50:>9}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns 0 (informative) or 2 on an invalid root."""
    parser = argparse.ArgumentParser(
        description=(
            "Informe agregado del scorecard por fase x task_type x backend x "
            "lens_scope (read-only, informativo). No es un gate y no se cablea."
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
