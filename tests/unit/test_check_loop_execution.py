"""Barrera de ejecucion del bucle 1->9->2 (WOT-2026-040b).

Cada rama del guard con su mutation EJECUTADA que prueba que muerde. El vector
que MUERDE de verdad (adjudicado por Codex) es el bucle DEGRADADO: N llamadas al
mismo modelo. El nonce es la ceremonia previa auditable.

Fixtures REALISTAS: filas con la forma exacta que escribe `_record_round`
(event="ronda", challenge_nonce copiado del emitido) y de `emit_nonce`.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_loop_execution as cle  # noqa: E402
import ensemble_dispatch as ed  # noqa: E402


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


def _ronda(backend, nonce="N1", commit="abc", ts="2026-07-24T10:05:00+00:00"):
    return {
        "event": "ronda",
        "commit_sha": commit,
        "backend_key": backend,
        "challenge_nonce": nonce,
        "ts": ts,
    }


# --------------------------------------------------------------- fixture positivo
def test_real_flight_with_emitted_receipts_passes():
    """(e) DoD: un vuelo real con 4 backends distintos y nonce emitido antes PASA."""
    emitted = [_emitted()]
    sc = [_ronda(bk) for bk in ("BA10", "BA11", "BA12", "BA13")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is True
    assert set(v["distinct_backends"]) == {"BA10", "BA11", "BA12", "BA13"}


# --------------------------------------------------------------------- ataques
def test_degraded_loop_same_backend_fails():
    """VECTOR PRINCIPAL: 4 rondas del MISMO backend (8 instancias del mismo modelo,
    la 2a ocurrencia medida 2026-07-24) NO alcanza N lentes distintas -> RED."""
    emitted = [_emitted()]
    sc = [_ronda("BA10") for _ in range(4)]  # mismo modelo x4
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA10"]


def test_fabricated_nonce_rejected():
    """(d) DoD: un receipt cuyo nonce NO fue emitido fuera se descarta -> RED."""
    emitted = [_emitted(nonce="N1")]
    sc = [_ronda(bk, nonce="FABRICADO") for bk in ("BA10", "BA11", "BA12", "BA13")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False
    assert v["distinct_backends"] == []


def test_adjudicate_rows_are_not_execution():
    """(c) DoD: filas event=adjudicate (campos pasables por CLI) NO prueban
    ejecucion, aunque lleven backend_key y nonce validos -> RED."""
    emitted = [_emitted()]
    sc = [
        {**_ronda(bk), "event": "adjudicate"} for bk in ("BA10", "BA11", "BA12", "BA13")
    ]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False


def test_nonce_emitted_after_round_rejected():
    """La emision debe ser ANTERIOR a la ronda (ceremonia previa). Un nonce emitido
    DESPUES no autoriza los receipts -> RED."""
    emitted = [_emitted(ts="2026-07-24T11:00:00+00:00")]  # despues de las rondas
    sc = [_ronda(bk) for bk in ("BA10", "BA11", "BA12", "BA13")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False


def test_nonce_for_other_commit_does_not_authorize():
    """Un nonce emitido para OTRO commit no autoriza este -> RED."""
    emitted = [_emitted(commit="otro")]
    sc = [_ronda(bk) for bk in ("BA10", "BA11", "BA12", "BA13")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False


def test_wrong_commit_rounds_ignored():
    """Rondas de OTRO commit no cuentan para este -> RED (0 lentes)."""
    emitted = [_emitted()]
    sc = [_ronda(bk, commit="otro") for bk in ("BA10", "BA11", "BA12", "BA13")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["distinct_backends"] == []


# ------------------------------------------------------------- N por deliverable
def test_min_distinct_proportional_to_deliverable_type():
    """(b) DoD: N proporcional. code exige mas lentes que documentation."""
    assert cle.min_distinct_for("code") == 4
    assert cle.min_distinct_for("documentation") == 2
    assert cle.min_distinct_for("research") == 2


def test_unknown_deliverable_type_is_strict_fallback():
    """Fail-closed: un tipo desconocido cae al fallback ESTRICTO, no al laxo."""
    assert cle.min_distinct_for("weird") == cle.FALLBACK_MIN_DISTINCT
    assert cle.min_distinct_for(None) == cle.FALLBACK_MIN_DISTINCT
    assert cle.FALLBACK_MIN_DISTINCT == 4


def test_doc_deliverable_passes_with_two_distinct():
    """Rigor proporcional: un doc con 2 lentes distintas basta (no exige 4)."""
    emitted = [_emitted()]
    sc = [_ronda(bk) for bk in ("BA01", "BA10")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=2)
    assert v["ok"] is True


# ----------------------------------------------------- integracion end-to-end
def test_emit_nonce_then_record_round_join_passes(tmp_path):
    """END-TO-END en la ruta REAL: emit_nonce escribe la emision, y una fila de
    scorecard que copia ese nonce con backend_key distinto pasa el join dual."""
    nonce, _p = ed.emit_nonce(
        tmp_path,
        commit_sha="abc123",
        loop_id="L700",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="FIXED_NONCE",
    )
    assert nonce == "FIXED_NONCE"
    # 4 rondas reales via append_scorecard con el nonce emitido
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        ed.append_scorecard(
            tmp_path,
            {
                "event": "ronda",
                "commit_sha": "abc123",
                "backend_key": bk,
                "challenge_nonce": "FIXED_NONCE",
                "ts": "2099-01-01T00:00:00+00:00",
            },
        )
    verdicts = cle.audit(tmp_path, commit_shas=["abc123"], deliverable_type="code")
    assert verdicts[0]["ok"] is True
    assert len(verdicts[0]["distinct_backends"]) == 4


def test_end_to_end_degraded_fails(tmp_path):
    """END-TO-END: emit + 4 rondas del MISMO backend -> el gate falla en la ruta real."""
    ed.emit_nonce(
        tmp_path,
        commit_sha="abc123",
        loop_id="L700",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="FIXED_NONCE",
    )
    for _ in range(4):
        ed.append_scorecard(
            tmp_path,
            {
                "event": "ronda",
                "commit_sha": "abc123",
                "backend_key": "BA10",
                "challenge_nonce": "FIXED_NONCE",
                "ts": "2099-01-01T00:00:00+00:00",
            },
        )
    verdicts = cle.audit(tmp_path, commit_shas=["abc123"], deliverable_type="code")
    assert verdicts[0]["ok"] is False


def test_read_emitted_nonces_missing_file_is_empty(tmp_path):
    """Un destino sin emisiones aun devuelve lista vacia (no crashea)."""
    assert ed.read_emitted_nonces(tmp_path) == []
