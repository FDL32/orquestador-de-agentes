"""Tests de cobertura de la configuracion REAL para WOT-2026-161t.

Cada clausula del DoD (c-01..c-05 de la ficha) es UN test contra el agents.json
VIVO cargado con load_motor_config (patron de test_check_loop_execution.py:2846).
"""
# [NON-REVERSE-CLASSICAL: test de contrato/cobertura nueva]

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_loop_execution as cle  # noqa: E402
import ensemble_dispatch as ed  # noqa: E402


_RS_WATCHDOG_MODE = (
    "timeout: watchdog de 1500s vencido sin respuesta de la lente; "
    "arbol de procesos del hijo (pid 4242) matado"
)
_RS_INTERNAL_MODE = (
    "unexpected: RuntimeError: backend CLI sin respuesta tras 900s; arbol de "
    "procesos matado. CAUSA NO DETERMINADA -- comprueba en este orden"
)


def _emitted(nonce="N1", commit="abc", loop="L700", ts="2026-07-24T10:00:00+00:00"):
    return {
        "ts": ts,
        "issuer_role": "orchestrator",
        "issuer_backend_key": "BA01",
        "issued_before_ts": ts,
        "commit_sha": commit,
        "loop_id": loop,
        "challenge_nonce": nonce,
    }


def _rs_row(backend, *, hang=None, answered=True, nonce="N1", sec=5, commit="abc"):
    """Fila `ronda` con TODOS los campos de SCORECARD_FIELDS (formato real)."""
    row = {k: None for k in ed.SCORECARD_FIELDS}
    row.update(
        ts=f"2026-07-24T10:05:{sec:02d}+00:00",
        event="ronda",
        ticket="WOT-2026-161t",
        rol="challenger",
        task_type="code-review",
        backend="kilo",
        model="x",
        ronda=1,
        outcome=None if answered else "no-aportacion",
        evidencia="hallazgo" if answered else "(respuesta vacia)",
        input_bytes=100,
        context_kind="diff",
        failure_mode=hang,
        latency_ms=1000,
        phase="MANAGER_REVIEW",
        loop_id="UNI-X",
        backend_key=backend,
        commit_sha=commit,
        challenge_nonce=nonce,
        output_chars=50 if answered else 0,
    )
    return row


def _rs_hang(backend, *, times=2, nonce="N1", mode=_RS_WATCHDOG_MODE, start=10):
    return [
        _rs_row(backend, hang=mode, answered=False, nonce=nonce, sec=start + i)
        for i in range(times)
    ]


def audit_real(monkeypatch, rows):
    """cle.audit con scorecard/emitted parcheados y el agents.json REAL.

    Before: rows con la forma de _rs_row; monkeypatch de pytest activo.
    During: parchea _read_scorecard y read_emitted_nonces (sin disco) y fija
        phase+delivery_authority para activar la cobertura declarada.
    After: primer veredicto (un solo commit "abc") con load_motor_config().
    """
    monkeypatch.setattr(cle, "_read_scorecard", lambda root: (list(rows), "x"))
    monkeypatch.setattr(cle, "read_emitted_nonces", lambda root: [_emitted()])
    config = ed.load_motor_config()
    verdicts = cle.audit(
        Path("dummy"),
        commit_shas=["abc"],
        deliverable_type="code",
        phase="MANAGER_REVIEW",
        delivery_authority="repo_motor",
        config=config,
    )
    return verdicts[0]


def test_real_entry_lists_extra_lenses_as_eligible():
    """c-01: la entrada REAL declara las cuatro lentes extra como elegibles."""
    config = ed.load_motor_config()
    entry = config["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]
    assert entry["backend_keys"] == [
        "BA04",
        "BA07",
        "BA258",
        "BA259",
        "BA150",
        "BA151",
        "BA08",
        "BA09",
    ]


def test_real_entry_is_valid_and_declares_no_reserve():
    """c-02: load_eligible_coverage da la entrada sin reason y SIN campos de reserva."""
    config = ed.load_motor_config()
    entry = config["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]
    assert cle.validate_coverage_entry(entry, config) is None
    loaded, reason, key = cle.load_eligible_coverage(
        config, "MANAGER_REVIEW", "repo_motor"
    )
    assert key == "MANAGER_REVIEW:repo_motor"
    assert reason is None
    assert loaded is not None
    assert "reserve_backend_keys" not in entry
    assert "reserve_after_timeouts" not in entry


def test_real_entry_keeps_other_keys_untouched():
    """c-03: los controles existentes y las cuatro primeras claves quedan intactos."""
    config = ed.load_motor_config()
    entry = config["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]
    assert entry["min_distinct"] == 2
    assert entry["policy"] == "declared"
    assert entry["excluded_backend_keys"] == ["BA05"]
    assert entry["exempt_tickets"] == ["WOT-2026-129d"]
    assert entry["backend_keys"][:4] == ["BA04", "BA07", "BA258", "BA259"]


def test_ba04_and_ba09_cover_without_ba07_or_ba08(monkeypatch):
    """c-04a: BA04 y BA09 respondidas cubren sin BA07 ni BA08."""
    rows = [_rs_row("BA04"), _rs_row("BA09", sec=6)]
    v = audit_real(monkeypatch, rows)
    assert all(r["backend_key"] not in {"BA07", "BA08"} for r in rows)
    assert v["ok"] is True
    assert sorted(v["distinct_backends"]) == ["BA04", "BA09"]
    assert v["min_aplicado"] == 2


def test_ba04_and_ba07_cover_without_ba08(monkeypatch):
    """c-04d: BA04 y BA07 respondidas cubren sin BA08."""
    rows = [_rs_row("BA04"), _rs_row("BA07", sec=6)]
    v = audit_real(monkeypatch, rows)
    assert all(r["backend_key"] != "BA08" for r in rows)
    assert v["ok"] is True
    assert sorted(v["distinct_backends"]) == ["BA04", "BA07"]
    assert v["min_aplicado"] == 2


def test_ba07_alone_does_not_cover(monkeypatch):
    """c-04e: BA07 sola no cubre min_distinct 2."""
    rows = [_rs_row("BA07")]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA07"]
    assert v["min_aplicado"] == 2


def test_hung_ba07_does_not_count(monkeypatch):
    """c-04f: BA07 colgada no cuenta y no activa claves de reserva."""
    rows = [
        _rs_row("BA04"),
        _rs_row("BA07", hang=_RS_WATCHDOG_MODE, answered=False, sec=12),
    ]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA04"]
    assert "BA07" not in v["distinct_backends"]
    assert "reserve_substitutions" not in v
    assert "reserve_exhausted" not in v


def test_ba04_and_ba08_cover_without_ba07_or_ba09(monkeypatch):
    """c-04g: BA04 y BA08 respondidas cubren sin BA07 ni BA09."""
    rows = [_rs_row("BA04"), _rs_row("BA08", sec=6)]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is True
    assert sorted(v["distinct_backends"]) == ["BA04", "BA08"]
    assert v["min_aplicado"] == 2


def test_ba04_and_ba09_answered_counts(monkeypatch):
    """c-04h: BA09 respondida cuenta junto a BA04."""
    rows = [_rs_row("BA04"), _rs_row("BA09", sec=6)]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is True
    assert sorted(v["distinct_backends"]) == ["BA04", "BA09"]
    assert v["min_aplicado"] == 2


def test_ba08_alone_does_not_cover(monkeypatch):
    """c-04b: BA08 sola no cubre min_distinct 2."""
    rows = [_rs_row("BA08")]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA08"]
    assert v["min_aplicado"] == 2


def test_hung_ba09_does_not_count(monkeypatch):
    """c-04c: BA09 colgada no cuenta y no activa claves de reserva."""
    rows = [
        _rs_row("BA04"),
        _rs_row("BA09", hang=_RS_WATCHDOG_MODE, answered=False, sec=12),
    ]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA04"]
    assert "BA09" not in v["distinct_backends"]
    assert "reserve_substitutions" not in v
    assert "reserve_exhausted" not in v


def test_note_documents_derived_view_and_family_rule():
    """c-05: el note documenta la vista derivada, la regla de familias y 129r."""
    config = ed.load_motor_config()
    entry = config["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]
    note = entry["note"]
    for text in (
        "VISTA DERIVADA de asignaciones.lentes_p34",
        "scripts/flight/render_asignaciones.py --apply",
        "BA05 excluida por WOT-2026-129r",
        "WOT-2026-129d exento",
        "min_distinct=2",
        "NO se declara reserva",
        "WOT-2026-152t",
        "La independencia por familia la aplica la coordinadora",
    ):
        assert text in note
    for stale in ("BA02", "BA03", "BA06", "BA254"):
        assert stale not in note
