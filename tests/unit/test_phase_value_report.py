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
    latency_ms: float | None = 20000.0,
    output_chars: int | None = 1500,
    outcome: str = "ok",
    evidencia: str = "raw/x.json (1500c)",
) -> dict:
    """One scorecard row in the REAL measured shape."""
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


def test_corrupt_line_is_skipped_and_counted_not_crash(tmp_path: Path) -> None:
    """The scorecard is appended concurrently: a half-written last line is real.

    ``_read_scorecard`` raises JSONDecodeError here (measured), so this report
    parses defensively on its own.
    """
    path = tmp_path / pvr.SCORECARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_row()) + "\n{ this is not json\n" + json.dumps(_row()) + "\n",
        encoding="utf-8",
    )
    report = pvr.build_report(tmp_path)
    assert report.eligible == 2
    assert report.dropped_unparsable == 1


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
