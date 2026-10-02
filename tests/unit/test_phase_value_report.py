"""Tests for scripts/phase_value_report.py (WOT-2026-044q).

The fixtures use the REAL measured scorecard schema (827 rows, 2026-07-31):
``phase`` / ``task_type`` / ``backend_key`` / ``loop_id`` / ``latency_ms`` /
``output_chars`` / ``event`` / ``outcome`` / ``evidencia``.

The point of the ticket is that the telemetry is INERT: hundreds of rows nobody
can aggregate. The point of THESE tests is that the report publishes an honest
DENOMINATOR -- 430 of those 827 rows carry no ``phase``/``backend_key`` at all,
so a table that silently drops 52% of the file is indistinguishable from one that
looked at nothing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "phase_value_report", _ROOT / "scripts" / "phase_value_report.py"
)
pvr = importlib.util.module_from_spec(_SPEC)
# Register BEFORE exec: `@dataclass` resolves its module via
# `sys.modules[cls.__module__]`, which is None for a spec-loaded module that was
# never registered -> AttributeError at class-creation time (measured).
sys.modules[_SPEC.name] = pvr
_SPEC.loader.exec_module(pvr)


# --------------------------------------------------------------------- helpers
def _row(
    *,
    phase: str | None = "CONTRACT_AUDIT",
    task_type: str = "contract-audit",
    backend_key: str | None = "BA10",
    lens_scope: str | None = "motor",
    latency_ms: float | None = 20000.0,
    output_chars: int | None = 1500,
    outcome: str = "ok",
    evidencia: str = "raw/x.json (1500c)",
) -> dict:
    """One scorecard row in the REAL measured shape.

    WOT-2026-055o: ``lens_scope`` joins a los ejes obligatorios, con el MISMO
    tratamiento que ``phase``/``backend_key`` -- ausencia -> ``dropped_legacy``,
    nunca un valor inventado. Se declara explicito para que los fixtures sigan
    describiendo filas ACTUALES; pasar ``lens_scope=None`` reproduce una fila
    legacy sin el campo (ese es el caso que cuentan los tests de denominador).
    """
    rec: dict = {
        "event": "ronda",
        "task_type": task_type,
        "outcome": outcome,
        "evidencia": evidencia,
    }
    if phase is not None:
        rec["phase"] = phase
    if backend_key is not None:
        rec["backend_key"] = backend_key
    if lens_scope is not None:
        rec["lens_scope"] = lens_scope
    if latency_ms is not None:
        rec["latency_ms"] = latency_ms
    if output_chars is not None:
        rec["output_chars"] = output_chars
    return rec


def _write(root: Path, rows: list[dict]) -> Path:
    """Write a scorecard at the canonical relative path under ``root``."""
    path = root / pvr.SCORECARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


# ------------------------------------------------------------- the aggregation
def test_aggregates_exact_counts_across_phases_and_backends(tmp_path: Path) -> None:
    """Exact per-cell counts over >=2 phases and >=2 backends.

    One cell carries n=3 with DISTINCT latencies on purpose: a fixture where every
    cell is n=1 makes "exact counts" trivially true and exercises no aggregation
    (and a single-value median equals that value, so it proves nothing).
    """
    rows = [
        _row(phase="CONTRACT_AUDIT", backend_key="BA10", latency_ms=10000.0),
        _row(phase="CONTRACT_AUDIT", backend_key="BA10", latency_ms=20000.0),
        _row(phase="CONTRACT_AUDIT", backend_key="BA10", latency_ms=90000.0),
        _row(phase="CONTRACT_AUDIT", backend_key="BA11", latency_ms=5000.0),
        _row(phase="CLOSE", backend_key="BA10", latency_ms=7000.0),
    ]
    _write(tmp_path, rows)
    report = pvr.build_report(tmp_path)

    cells = {(c.task_type, c.phase, c.backend_key): c for c in report.cells}
    assert len(cells) == 3, cells.keys()
    assert cells[("contract-audit", "CONTRACT_AUDIT", "BA10")].rounds == 3
    assert cells[("contract-audit", "CONTRACT_AUDIT", "BA11")].rounds == 1
    assert cells[("contract-audit", "CLOSE", "BA10")].rounds == 1


def test_latency_is_the_median_not_the_mean(tmp_path: Path) -> None:
    """MEDIAN, measured choice: on the real data mean/median = 1.51x (long tail).

    10000/20000/90000 -> median 20000, mean 40000. Asserting the median pins the
    contract's decision; a mean would silently let one slow run dominate.
    """
    rows = [
        _row(phase="CONTRACT_AUDIT", backend_key="BA10", latency_ms=10000.0),
        _row(phase="CONTRACT_AUDIT", backend_key="BA10", latency_ms=20000.0),
        _row(phase="CONTRACT_AUDIT", backend_key="BA10", latency_ms=90000.0),
    ]
    _write(tmp_path, rows)
    cell = pvr.build_report(tmp_path).cells[0]
    assert cell.latency_p50_ms == 20000.0, cell


def test_missing_latency_is_excluded_never_imputed_as_zero(tmp_path: Path) -> None:
    """A row without ``latency_ms`` must not sink the median with a fake 0."""
    rows = [
        _row(phase="CLOSE", backend_key="BA12", latency_ms=30000.0),
        _row(phase="CLOSE", backend_key="BA12", latency_ms=None),
    ]
    _write(tmp_path, rows)
    cell = pvr.build_report(tmp_path).cells[0]
    assert cell.rounds == 2
    assert cell.latency_p50_ms == 30000.0, "imputed a 0 and sank the median"


# ------------------------------------------------------------- the denominator
def test_denominator_counts_legacy_rows_it_dropped(tmp_path: Path) -> None:
    """52% of the real file has no phase/backend_key; dropping it silently lies."""
    rows = [
        _row(phase="CLOSE", backend_key="BA10"),
        _row(phase=None, backend_key=None),
        _row(phase=None, backend_key=None),
        _row(phase="CLOSE", backend_key=None),
    ]
    _write(tmp_path, rows)
    report = pvr.build_report(tmp_path)
    assert report.total_rows == 4
    assert report.eligible == 1
    assert report.dropped_legacy == 3, "rows missing phase OR backend_key must drop"


def test_denominator_line_has_the_contracted_shape(tmp_path: Path) -> None:
    """The format is FIXED by contract so the count cannot be buried."""
    _write(tmp_path, [_row(), _row(phase=None, backend_key=None)])
    line = pvr.format_denominator(pvr.build_report(tmp_path))
    for token in (
        "[denominador]",
        "filas=2",
        "elegibles=1",
        "descartadas_legacy=1",
        "sustantivas_medidas=",
        "sustantivas_fail_open=",
        "mudas=",
    ):
        assert token in line, f"missing {token!r} in: {line!r}"


def test_contracted_denominator_line_is_never_extended(tmp_path: Path) -> None:
    """The contracted line stays byte-identical even when extra counts exist.

    MANAGER_REVIEW finding (lens deepseek): an earlier version spliced
    ``descartadas_ilegibles=N`` INTO the contracted line whenever a corrupt row
    appeared. Fixing a shape and then extending it defeats the point -- anything
    parsing it positionally breaks on the rare input.

    WOT-2026-079a: con la lectura unificada, la fila corrupta de un ARCHIVADO
    vive en el canal de WARN del lector y nunca llega al informe; la corrupta
    del ACTIVO lanza antes de construir linea alguna (pinned por
    ``test_corrupt_line_in_active_raises_strict``). El pin de esta prueba: la
    linea contratada no cambia de forma y la linea extra no aparece.
    """
    path = tmp_path / pvr.SCORECARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(json.dumps(_row()) + "\n", encoding="utf-8")
    clean = pvr.format_denominator(pvr.build_report(tmp_path))

    archive = path.parent / "scorecard.20261001-000000.jsonl"
    archive.write_text("{ broken\n", encoding="utf-8")
    out = pvr.format_denominator(pvr.build_report(tmp_path))

    assert out == clean, "la linea contratada cambio por una fila corrupta"
    assert "descartadas_ilegibles" not in out, out


# ---------------------------------------------------------------------- WOT-2026-079a (D7)
def test_no_local_reimplementation_of_scorecard_parsing() -> None:
    """Criterio estructural BINARIO (D7): el dashboard no reimplementa.

    `_iter_rows` (el parseo defensivo propio) ya NO existe en el modulo, y el
    modulo importa `read_scorecard_unified` desde `ensemble_dispatch` (la
    excepcion unica al Forbidden Surface de WOT-2026-055o).
    """
    source = Path(pvr.__file__).read_text(encoding="utf-8")
    assert "def _iter_rows" not in source, (
        "el parseo defensivo propio volvio: la lectura debe ser la compartida"
    )
    assert "read_scorecard_unified" in source
    assert "from ensemble_dispatch import" in source


def test_dashboard_invokes_the_shared_unified_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D7 funcional: el dashboard DEBE invocar `read_scorecard_unified`.

    El stub lanza ``AssertionError`` ante argumentos incorrectos (firma
    fijada: un solo `project_root`); si el dashboard no la invocara en
    absoluto, la asercion de la llamada cae porque el stub nunca registro el
    pase. Parchea la instancia que `build_report` resuelve (el nombre en el
    propio modulo, leccion `module-imported-under-two-names-is-two-instances`).
    """
    calls: list[Path] = []

    def stub(project_root):
        if not isinstance(project_root, Path):
            raise AssertionError(f"firma incorrecta: {project_root!r}")
        calls.append(project_root)
        return iter([_row()])

    _write(tmp_path, [])  # el fichero real existe pero el stub lo tapa
    monkeypatch.setattr(pvr, "read_scorecard_unified", stub)
    report = pvr.build_report(tmp_path)

    assert calls == [tmp_path], "el dashboard no invoco el lector compartido"
    assert report.total_rows == 1


def test_dashboard_includes_archived_rows_after_rotation(tmp_path: Path) -> None:
    """D7 no-regresion: mismo resultado sin rotacion; con rotacion simulada
    (activo vacio + archivado), el informe INCLUYE las filas archivadas."""
    rows = [
        _row(phase="CLOSE", backend_key="BA10"),
        _row(phase="CLOSE", backend_key="BA11"),
    ]
    _write(tmp_path, rows)
    clean = pvr.build_report(tmp_path)

    active = tmp_path / pvr.SCORECARD_REL
    archive = active.parent / "scorecard.20261001-000000.jsonl"
    archive.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    active.write_text("", encoding="utf-8")  # el tramo vivo se vacio al rotar
    rotated = pvr.build_report(tmp_path)

    assert rotated.total_rows == clean.total_rows == 2
    assert {(c.phase, c.backend_key): c.rounds for c in rotated.cells} == {
        (c.phase, c.backend_key): c.rounds for c in clean.cells
    }, "una fila archivada se perdio para el dashboard"


def test_substantive_splits_measured_from_fail_open(tmp_path: Path) -> None:
    """``is_substantive`` is FAIL-OPEN: no ``output_chars`` still counts as YES.

    Measured on the real scorecard: 206 of 394 "substantive" rows are substantive
    only because the field is absent. Publishing 394 would count 206 rows nobody
    measured -- the same denominator defect this ticket exists to close, one level
    down. The two must be reported separately.
    """
    rows = [
        _row(output_chars=1500),  # measured -> substantive
        _row(output_chars=None),  # no data  -> substantive by FAIL-OPEN
        _row(output_chars=0),  # measured -> mute
    ]
    _write(tmp_path, rows)
    report = pvr.build_report(tmp_path)
    assert report.substantive_measured == 1, report
    assert report.substantive_fail_open == 1, report
    assert report.mute == 1, report


def test_substantive_uses_the_canonical_definition(tmp_path: Path) -> None:
    """The mute signals come from ``is_substantive``, not a local re-invention.

    Two definitions of "substantive" drifting apart would make this report
    contradict ``check_loop_execution`` on the same rows.
    """
    rows = [
        _row(output_chars=None, outcome="no-aportacion"),
        _row(output_chars=None, evidencia="(respuesta vacia)"),
    ]
    _write(tmp_path, rows)
    report = pvr.build_report(tmp_path)
    assert report.mute == 2, "canonical mute signals were not honoured"
    assert report.substantive_fail_open == 0


# ------------------------------------------------------------ robustness edges
def test_sparse_table_emits_only_cells_with_data(tmp_path: Path) -> None:
    """~343 cartesian cells vs 397 eligible rows: a grid of zeros hides the signal."""
    rows = [
        _row(phase="CLOSE", backend_key="BA10"),
        _row(phase="CONTRACT_AUDIT", backend_key="BA11"),
    ]
    _write(tmp_path, rows)
    report = pvr.build_report(tmp_path)
    assert len(report.cells) == 2
    assert all(c.rounds > 0 for c in report.cells)


def test_corrupt_line_in_active_raises_strict(tmp_path: Path) -> None:
    """WOT-2026-079a (D5 / DEC-079A-001 Decision 2.2): el ACTIVO es ESTRICTO.

    La semantica del ledger vivo se PRESERVA: una linea truncada (estado real
    de crash del append concurrente) no se calla. El parseo defensivo propio
    fue RETIRADO por el contrato y la lectura pasa por
    `read_scorecard_unified`, que lanza igual que `_read_scorecard` lanzaba
    siempre sobre el activo.
    """
    path = tmp_path / pvr.SCORECARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_row()) + "\n{ this is not json\n" + json.dumps(_row()) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(json.JSONDecodeError):
        pvr.build_report(tmp_path)


def test_corrupt_line_in_archive_is_skipped_with_warn(tmp_path: Path) -> None:
    """WOT-2026-079a (D5): los ARCHIVADOS son SIEMPRE tolerantes.

    Una linea ilegible en un archivado (inmutable: no tiene arreglo) se salta
    con WARN nombrando fichero y linea, el informe se construye con las filas
    validas (del activo Y del archivado) y NUNCA lanza.
    """
    path = tmp_path / pvr.SCORECARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_row()) + "\n", encoding="utf-8")
    archive = path.parent / "scorecard.20261001-000000.jsonl"
    archive.write_text(
        json.dumps(_row(phase="CLOSE", backend_key="BA11")) + "\n{ broken\n",
        encoding="utf-8",
    )
    report = pvr.build_report(tmp_path)
    assert report.total_rows == 2  # activo + la fila valida del archivado
    assert report.dropped_unparsable == 0  # el conteo vive en el WARN del lector


def test_empty_scorecard_says_no_data_rc_zero(tmp_path: Path) -> None:
    """NEGATIVE CONTROL: no rows -> "sin datos", rc=0, no misleading empty table."""
    _write(tmp_path, [])
    assert pvr.main(["--project-root", str(tmp_path)]) == 0
    assert "sin datos" in pvr.format_table(pvr.build_report(tmp_path)).lower()


def test_all_legacy_is_not_the_same_as_empty(tmp_path: Path) -> None:
    """NEGATIVE CONTROL 3: rows present but NONE eligible is its own case.

    This is the likely state of a freshly installed destino, and conflating it
    with "empty" would hide that the file has data the report cannot use.
    """
    _write(tmp_path, [_row(phase=None, backend_key=None) for _ in range(3)])
    report = pvr.build_report(tmp_path)
    assert report.total_rows == 3
    assert report.eligible == 0
    assert not report.cells
    assert pvr.main(["--project-root", str(tmp_path)]) == 0
    assert "elegibles=0" in pvr.format_denominator(report)


def test_read_only_leaves_content_and_mtime_untouched(tmp_path: Path) -> None:
    """MUTATION: any write to the scorecard fails this test.

    Content AND mtime, not just content: an ``open(..., "a")`` that writes nothing,
    or a "last read" touch, leaves the bytes identical and moves the timestamp.
    """
    path = _write(tmp_path, [_row(), _row(phase="CLOSE", backend_key="BA11")])
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    pvr.main(["--project-root", str(tmp_path)])

    assert path.read_bytes() == before_bytes, "the report rewrote the scorecard"
    assert path.stat().st_mtime_ns == before_mtime, "the report touched the scorecard"


def test_missing_project_root_exits_two(tmp_path: Path) -> None:
    """Same contract as pool_permanence_metric: invalid root -> rc 2, not a crash."""
    assert pvr.main(["--project-root", str(tmp_path / "nope")]) == 2


# ------------------------------------------------------- WOT-2026-055o: ejes y JOIN
def test_phase_value_report_separates_cells_by_lens_scope(tmp_path: Path) -> None:
    """Dos filas con el MISMO task_type+phase+backend_key pero `lens_scope`
    distinto -> DOS celdas, no una.

    MUTATION: revertir la tupla `key` de `build_report` a
    `(task_type, phase, backend_key)` -> una sola celda con rounds=2 y este
    test cae. Sin el eje, una lente CON ojos y otra CIEGA del mismo modelo se
    agregaban juntas y el informe mezclaba dos poblaciones con tasas de acierto
    distintas.
    """
    rows = [
        _row(phase="CONTRACT_AUDIT", backend_key="BA10", lens_scope="motor"),
        _row(phase="CONTRACT_AUDIT", backend_key="BA10", lens_scope="destino"),
    ]
    _write(tmp_path, rows)
    report = pvr.build_report(tmp_path)
    cells = {
        (c.task_type, c.phase, c.backend_key, c.lens_scope): c for c in report.cells
    }
    assert len(cells) == 2, f"el lens_scope debe partir la celda: {cells.keys()}"
    assert cells[("contract-audit", "CONTRACT_AUDIT", "BA10", "motor")].rounds == 1
    assert cells[("contract-audit", "CONTRACT_AUDIT", "BA10", "destino")].rounds == 1
    header = pvr.format_table(report).splitlines()[0]
    assert "scope" in header, "la tabla debe publicar el eje lens_scope"


def test_phase_value_report_joins_ronda_with_adjudicacion_by_cohort_key(
    tmp_path: Path,
) -> None:
    """Una ronda + su adjudicacion con las 4 claves coincidentes -> el JOIN las
    une y la celda refleja el outcome.

    NEGATIVO (y es la parte que mata la aproximacion): cambiando UNA clave de
    la adjudicacion el JOIN NO las une -- la cohorte queda `sin_ronda`, con
    `cohortes_completas=0` y cero adopciones en la celda, en vez de fundirse
    por vocabulario libre en `ticket`/`ronda`/`rol`.
    """
    ronda = _row(
        phase="CONTRACT_AUDIT",
        backend_key="BA10",
        lens_scope="motor",
        task_type="contract-audit",
    )
    ronda.update(
        {
            "loop_id": "L700",
            "challenge_nonce": "N1",
            "ticket": "WOT-TEST-055o",
            "rol": "challenger",
            "ronda": 1,
            "backend": "fake",
            "model": "m2",
        }
    )
    adj = dict(ronda)
    adj.update({"event": "adjudicacion", "outcome": "adoptada"})
    _write(tmp_path, [ronda, adj])

    report = pvr.build_report(tmp_path)
    assert report.adjudications_total == 1
    assert report.adjudications_joinable == 1
    assert report.adjudications_unjoinable_legacy == 0
    assert (report.cohortes_intentadas, report.cohortes_completas) == (1, 1)
    assert report.eligible == 1, "la adjudicacion no cuenta como ronda"
    cell = report.cells[0]
    assert (cell.adoptadas, cell.falsos) == (1, 0)
    assert cell.efficacy == "1/0"
    denom = pvr.format_denominator(report)
    assert "cohortes_intentadas=1" in denom and "cohortes_completas=1" in denom
    assert "adjudicaciones_excluidas_de_rondas=1" in denom

    # ---- negativo: UNA clave cambiada -> sin union, jamas por aproximacion ----
    ronda2 = _row(
        phase="CONTRACT_AUDIT",
        backend_key="BA10",
        lens_scope="motor",
        task_type="contract-audit",
        latency_ms=5000.0,
    )
    ronda2.update(
        {
            "loop_id": "L700",
            "ticket": "WOT-TEST-055o",
            "rol": "challenger",
            "ronda": 2,
            "backend": "fake",
            "model": "m2",
        }
    )
    adj2 = dict(ronda2)
    adj2.update({"event": "adjudicacion", "outcome": "adoptada", "backend_key": "BA99"})
    path = tmp_path / pvr.SCORECARD_REL
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in [ronda2, adj2]), encoding="utf-8"
    )
    report2 = pvr.build_report(tmp_path)
    assert report2.adjudications_joinable == 1, "la clave esta completa"
    assert (report2.cohortes_intentadas, report2.cohortes_completas) == (1, 0), (
        "una adjudicacion cuya ronda no existe NO puede unirse: el contador "
        "'sin ronda' la declara en vez de emparejarla por aproximacion"
    )
    assert report2.cells[0].adoptadas == 0, "fusion aproximada detectada"
    assert "sin_ronda=1" in pvr.format_denominator(report2), (
        "el denominador debe publicar la cohorte incompleta"
    )


def test_phase_value_report_declares_unjoinable_legacy_denominator(
    tmp_path: Path,
) -> None:
    """Una adjudicacion SIN las 4 claves (anterior a WOT-2026-055o) cuenta en
    `adjudications_unjoinable_legacy` y NUNCA se empareja.

    CONTROL NEGATIVO duro: la fila legacy lleva `ticket`+`ronda`+`rol`
    IDENTICOS a una ronda real presente en el fichero -- el vocabulario libre
    casaria al 100% --, pero sin la clave hacia adelante no hay union.
    """
    ronda = _row(
        phase="CONTRACT_AUDIT",
        backend_key="BA10",
        lens_scope="motor",
        task_type="contract-audit",
    )
    ronda.update(
        {
            "loop_id": "L700",
            "ticket": "WOT-TEST-055o",
            "rol": "challenger",
            "ronda": 1,
            "backend": "fake",
            "model": "m2",
        }
    )
    legacy_adj = {
        "event": "adjudicacion",
        "task_type": "contract-audit",
        "backend": "fake",
        "model": "m2",
        "ticket": "WOT-TEST-055o",
        "ronda": 1,
        "rol": "challenger",
        "outcome": "adoptada",
        "phase": "CONTRACT_AUDIT",
        "backend_key": "BA10",
        "lens_scope": "motor",
        # SIN loop_id -> sin clave completa -> NO unible, por muy identico que
        # este todo lo demas.
    }
    _write(tmp_path, [ronda, legacy_adj])

    report = pvr.build_report(tmp_path)
    assert report.adjudications_total == 1
    assert report.adjudications_joinable == 0
    assert report.adjudications_unjoinable_legacy == 1
    assert (report.cohortes_intentadas, report.cohortes_completas) == (0, 0)
    assert report.cells[0].adoptadas == 0, (
        "la adjudicacion legacy NO debe unirse: emparejarla por etiqueta es "
        "exactamente lo prohibido por la decision del operador 2026-09-23"
    )
    denom = pvr.format_denominator(report)
    assert "no_unibles_legacy=1" in denom, denom
    assert "cohortes_completas=0" in denom, denom
