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
        "BA03",
        "BA07",
        "BA254",
        "BA02",
        "BA04",
        "BA06",
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
    assert entry["backend_keys"][:4] == ["BA03", "BA07", "BA254", "BA02"]


def test_ba03_and_ba09_cover_without_ba07_or_ba02(monkeypatch):
    """c-04a: BA03 y BA09 respondidas cubren sin BA07 ni BA02."""
    rows = [_rs_row("BA03"), _rs_row("BA09", sec=6)]
    v = audit_real(monkeypatch, rows)
    assert all(r["backend_key"] not in {"BA07", "BA02"} for r in rows)
    assert v["ok"] is True
    assert sorted(v["distinct_backends"]) == ["BA03", "BA09"]
    assert v["min_aplicado"] == 2


def test_ba03_and_ba02_cover_without_ba07(monkeypatch):
    """c-04d: BA03 y BA02 respondidas cubren sin BA07."""
    rows = [_rs_row("BA03"), _rs_row("BA02", sec=6)]
    v = audit_real(monkeypatch, rows)
    assert all(r["backend_key"] != "BA07" for r in rows)
    assert v["ok"] is True
    assert sorted(v["distinct_backends"]) == ["BA02", "BA03"]
    assert v["min_aplicado"] == 2


def test_ba02_alone_does_not_cover(monkeypatch):
    """c-04e: BA02 sola no cubre min_distinct 2."""
    rows = [_rs_row("BA02")]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA02"]
    assert v["min_aplicado"] == 2


def test_hung_ba02_does_not_count(monkeypatch):
    """c-04f: BA02 colgada no cuenta y no activa claves de reserva."""
    rows = [
        _rs_row("BA03"),
        _rs_row("BA02", hang=_RS_WATCHDOG_MODE, answered=False, sec=12),
    ]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA03"]
    assert "BA02" not in v["distinct_backends"]
    assert "reserve_substitutions" not in v
    assert "reserve_exhausted" not in v


def test_ba03_and_ba04_cover_without_ba07_or_ba02(monkeypatch):
    """c-04g: BA03 y BA04 respondidas cubren sin BA07 ni BA02."""
    rows = [_rs_row("BA03"), _rs_row("BA04", sec=6)]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is True
    assert sorted(v["distinct_backends"]) == ["BA03", "BA04"]
    assert v["min_aplicado"] == 2


def test_ba03_and_ba08_answered_counts(monkeypatch):
    """c-04h: BA08 respondida cuenta junto a BA03."""
    rows = [_rs_row("BA03"), _rs_row("BA08", sec=6)]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is True
    assert sorted(v["distinct_backends"]) == ["BA03", "BA08"]
    assert v["min_aplicado"] == 2


def test_ba06_alone_does_not_cover(monkeypatch):
    """c-04b: BA06 sola no cubre min_distinct 2."""
    rows = [_rs_row("BA06")]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA06"]
    assert v["min_aplicado"] == 2


def test_hung_ba08_does_not_count(monkeypatch):
    """c-04c: BA08 colgada no cuenta y no activa claves de reserva."""
    rows = [
        _rs_row("BA03"),
        _rs_row("BA08", hang=_RS_WATCHDOG_MODE, answered=False, sec=12),
    ]
    v = audit_real(monkeypatch, rows)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA03"]
    assert "BA08" not in v["distinct_backends"]
    assert "reserve_substitutions" not in v
    assert "reserve_exhausted" not in v


def test_note_documents_extra_lenses_and_family_rule():
    """c-05: el note documenta las lentes extra, la regla de familias y 129r."""
    config = ed.load_motor_config()
    entry = config["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]
    note = entry["note"]
    for text in (
        "BA02",
        "2026-11-10",
        "elegible",
        "n=122",
        "84",
        "opcional",
        "BA254",
        "T1",
    ):
        assert text in note
    assert "BA04, BA06, BA08 y BA09 quedan elegibles" in note
    assert "2026-11-11" in note
    assert "La independencia por familia la aplica la coordinadora" in note
    assert "BA05/129r sigue sin tocar" in note
