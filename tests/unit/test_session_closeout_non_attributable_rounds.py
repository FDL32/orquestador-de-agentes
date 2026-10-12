"""WOT-2026-040g, DoD (d): el cierre REPORTA las rondas de gobierno NO
ATRIBUIBLES (sin `session_id`), en vez de esconderlas tras un SKIP agregado.

Cierra la mitad "consumidor" del ticket: `ensemble_dispatch.py` POBLA el
`session_id` por defecto (heredado del scratch) y este paso del cierre es quien
rompe el silencio cuando ese default no hubo (scratch ausente/vacio).

Mutation-verified: `find_non_attributable_government_rounds` es PURA; el paso
se prueba contra un scorecard REAL escrito por `append_scorecard`. Un control
negativo (todas atribuidas -> PASS) y un positivo (una huerfana -> WARN)
discriminan que el reporte depende del estado real del scorecard, no de una
aserción decorativa.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts import (  # noqa: E402
    ensemble_dispatch as ed,
    session_closeout as sc,
)


def _round_row(
    *,
    session_id: str | None,
    ts: str = "2026-09-07T10:00:00+00:00",
    phase: str | None = "MANAGER_REVIEW",
    loop_id: str | None = "L040g",
) -> dict:
    return {
        "ts": ts,
        "event": "ronda",
        "ticket": "WOT-2026-040g",
        "rol": "challenger",
        "task_type": "code-review",
        "backend": "fake",
        "model": "m1",
        "ronda": 1,
        "outcome": None,
        "evidencia": "e",
        "input_bytes": 10,
        "context_kind": "diff",
        "session_id": session_id,
        "phase": phase,
        "loop_id": loop_id,
    }


# ---------------------------------------------------------------------------
# Pure filter: find_non_attributable_government_rounds
# ---------------------------------------------------------------------------


def test_filter_selects_only_government_rounds_without_session_id():
    sid = "20260101-0001-nogit-" + "a" * 32
    rows = [
        _round_row(session_id=sid),  # gobierno, atribuida -> fuera
        _round_row(session_id=None),  # gobierno, huerfana -> DENTRO
        _round_row(session_id=None, phase=None, loop_id=None),  # exploratoria -> fuera
        {"event": "adjudicacion", "session_id": None, "phase": "CLOSE"},  # no-ronda
    ]
    orphans = sc.find_non_attributable_government_rounds(rows)
    assert len(orphans) == 1
    assert orphans[0]["event"] == "ronda"
    assert orphans[0]["loop_id"] == "L040g"


def test_filter_window_excludes_rounds_before_window_start():
    """Una huerfana ANTERIOR a la ventana no ensucia el cierre de hoy."""
    old = _round_row(session_id=None, ts="2026-07-23T00:00:00+00:00")
    fresh = _round_row(session_id=None, ts="2026-09-07T10:00:00+00:00")
    window = datetime(2026, 9, 1, tzinfo=timezone.utc)
    orphans = sc.find_non_attributable_government_rounds([old, fresh], window)
    assert orphans == [fresh]


def test_filter_tolerates_naive_vs_aware_timestamps():
    """`ts` aware + `window_start` naive NO debe lanzar TypeError."""
    row = _round_row(session_id=None, ts="2026-09-07T10:00:00+00:00")
    naive_window = datetime(2026, 9, 1)  # sin tzinfo
    orphans = sc.find_non_attributable_government_rounds([row], naive_window)
    assert orphans == [row]


# ---------------------------------------------------------------------------
# Reporte por paso (no solo el filtro puro)
# ---------------------------------------------------------------------------


def test_step_pass_when_no_government_round(tmp_path):
    ed.append_scorecard(tmp_path, _round_row(session_id="sid-x"))
    result = sc._step_report_non_attributable_rounds(tmp_path, None)
    assert result.status == "PASS"
    assert result.blocking is False


def test_step_warn_reports_orphan_round_not_hidden(tmp_path):
    """MUTATION PIN: con una ronda de gobierno SIN session_id el paso la
    REPORTA (WARN con recuento), no la esconde. Sin la fila huerfana el paso es
    PASS (control negativo en el test de arriba)."""
    ed.append_scorecard(tmp_path, _round_row(session_id=None, loop_id="L-huerfano"))
    result = sc._step_report_non_attributable_rounds(tmp_path, None)
    assert result.status == "WARN", result
    assert "1 ronda(s)" in result.detail
    assert "L-huerfano" in result.detail
    # No bloquea el cierre: es informativo (misma regla que el Bloque 2.5.i).
    assert result.blocking is False


def test_step_skips_cleanly_on_empty_missing_scorecard(tmp_path):
    """Sin scorecard no hay ronda que reportar: PASS (0 huerfanas), nunca FAIL."""
    result = sc._step_report_non_attributable_rounds(tmp_path, None)
    assert result.status == "PASS"


def test_warn_is_non_blocking_in_report_aggregate(tmp_path):
    """El WARN del paso NO escala `overall_status` a FAIL (no bloquea el cierre)."""
    ed.append_scorecard(tmp_path, _round_row(session_id=None))
    report = sc.CloseoutReport()
    report.steps.append(sc._step_report_non_attributable_rounds(tmp_path, None))
    assert report.overall_status == "WARN", report.overall_status
