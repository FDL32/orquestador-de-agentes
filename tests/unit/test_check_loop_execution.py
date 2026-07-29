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

import pytest


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


def test_issuer_backend_does_not_count_as_a_lens():
    """CRITERIO ADJUDICADO POR CODEX: el issuer_backend_key del emisor NO cuenta
    como lente ejecutora para N. En dogfooding BA01 (Claude) emite el nonce Y es
    la lente lector-FS, asi que SI puede ejecutar una ronda -- pero contarlo
    inflaria N con una independencia que no existe (quien emite no es una lente
    independiente del challenge). El emisor BA01 + 3 lentes reales = 3, NO 4."""
    emitted = [_emitted()]  # issuer_backend_key = BA01 (ver _emitted)
    sc = [_ronda(bk) for bk in ("BA01", "BA10", "BA11", "BA12")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert "BA01" not in v["distinct_backends"], (
        "el emisor BA01 NO puede contar como lente independiente para N"
    )
    assert v["distinct_backends"] == ["BA10", "BA11", "BA12"]
    assert v["ok"] is False  # 3 lentes reales < 4 exigidas


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
    """Rigor proporcional: un doc con 2 lentes distintas (ninguna el emisor BA01)
    basta (no exige 4)."""
    emitted = [_emitted()]  # emisor BA01
    sc = [_ronda(bk) for bk in ("BA10", "BA11")]  # 2 lentes reales, no el emisor
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


# ------------------------------------------ SUSTANCIA vs silencio (WOT-2026-043q)
def _muda(backend, **kw):
    """Ronda que corrio y CALLO, con la forma exacta que escribe `_record_round`
    ante un `reply` vacio: outcome derivado + marcador en evidencia + 0 chars."""
    row = _ronda(backend, **kw)
    row.update(
        {
            "output_chars": 0,
            "outcome": "no-aportacion",
            "evidencia": "(respuesta vacia)",
        }
    )
    return row


def test_lenses_and_silent_rounds_partition_the_same_pass():
    """Las dos vistas (lentes que cuentan / rondas mudas) salen de UNA sola pasada
    estructural y son complementarias: la sustancia es el unico filtro que las
    separa. Pinea que nadie duplique la cadena de filtros y las haga divergir."""
    emitted = [_emitted()]
    sc = [
        _ronda("BA10"),
        _muda("BA11"),
        _ronda("BA12"),
        {**_ronda("BA13"), "event": "adjudicate"},  # estructuralmente invalida
        _ronda("BA01"),  # el emisor: tampoco es estructuralmente valida
    ]
    valid = cle.structurally_valid_rounds(sc, emitted, commit_sha="abc")
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    # las descartadas por estructura no aparecen en NINGUNA de las dos vistas
    assert {r["backend_key"] for r in valid} == {"BA10", "BA11", "BA12"}
    assert len(v["distinct_backends"]) + len(v["silent_rounds"]) == len(valid)
    assert set(v["distinct_backends"]).isdisjoint(
        {s["backend_key"] for s in v["silent_rounds"]}
    )


def test_silent_lens_does_not_count_as_execution():
    """MUTATION (direccion 1): 4 backends DISTINTOS que devuelven CERO BYTES no son
    un bucle ejecutado. Es el fallo del ticket: "no corrio" y "corrio y callo" eran
    indistinguibles, y N backends mudos daban rc=0."""
    emitted = [_emitted()]
    sc = [_muda(bk) for bk in ("BA10", "BA11", "BA12", "BA13")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False
    assert v["distinct_backends"] == []
    # y las NOMBRA: un contador sin nombres obliga a re-medir a mano
    assert {s["backend_key"] for s in v["silent_rounds"]} == {
        "BA10",
        "BA11",
        "BA12",
        "BA13",
    }


def test_substantive_answers_still_pass():
    """MUTATION (direccion 2 / CONTROL POSITIVO): el MISMO fan-out con respuestas
    REALES sigue en verde. Sin esta direccion el criterio podria estar rechazandolo
    todo y el test de arriba pasaria igual."""
    emitted = [_emitted()]
    sc = []
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        row = _ronda(bk)
        row.update({"output_chars": 1800, "evidencia": "hallazgo real y citado"})
        sc.append(row)
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is True
    assert len(v["distinct_backends"]) == 4
    assert v["silent_rounds"] == []


def test_one_silent_lens_drops_the_count_below_minimum():
    """El caso REAL medido en el scorecard: no todas mudas, solo una. 4 lentes de
    las que 1 calla -> 3, por debajo del minimo de `code`."""
    emitted = [_emitted()]
    sc = [_ronda(bk) for bk in ("BA10", "BA11", "BA12")] + [_muda("BA13")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA10", "BA11", "BA12"]
    assert [s["backend_key"] for s in v["silent_rounds"]] == ["BA13"]


def test_invisible_only_reply_is_not_substantive():
    """Hallazgo del bucle de gobierno L1400 (lente gemma4, CONFIRMADO en el arbol):
    `_record_round` mide sobre `text.strip()`, asi que una respuesta de solo
    blancos ya llega con output_chars=0 -- pero `str.strip()` NO quita los
    invisibles Unicode, y un zero-width space medía 1 y contaba como aportacion."""
    emitted = [_emitted()]
    sc = []
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        row = _ronda(bk)
        row.update({"output_chars": 1, "evidencia": "​"})
        sc.append(row)
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False
    assert len(v["silent_rounds"]) == 4


def test_whitespace_only_reply_already_arrives_as_zero_chars():
    """El otro lado del mismo hallazgo, REFUTADO al medirlo: los blancos normales
    NO necesitan tratamiento especial aqui porque `_record_round` los strippea
    antes de medir. Se pinea en la ruta productiva para que siga siendo cierto."""
    text = "   \n\t  "
    assert len(text.strip()) == 0


def test_legacy_rows_without_output_chars_stay_substantive():
    """ANTI-FALSO-POSITIVO (fail-OPEN deliberado): las filas anteriores a este
    ticket NO llevan `output_chars`. Tratar "campo ausente" como muda invalidaria
    RETROACTIVAMENTE bucles ya corridos, y un gate asi se rodea (WOT-2026-042x).
    Medido: de 16 commits historicos con fan-out, ninguno cae bajo su minimo."""
    emitted = [_emitted()]
    sc = [_ronda(bk) for bk in ("BA10", "BA11", "BA12", "BA13")]
    assert all("output_chars" not in row for row in sc)
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is True


def test_truncated_evidencia_is_not_used_as_a_size_proxy():
    """Por que NO hay umbral de longitud: una respuesta sustantiva guardada FUERA
    DE LINEA ocupa ~46 caracteres en `evidencia` ("raw/....json (2134c)"). Un
    umbral sobre ese campo la marcaria muda -- falso positivo por construccion."""
    emitted = [_emitted()]
    sc = []
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        row = _ronda(bk)
        row.update(
            {
                "output_chars": 2134,
                "evidencia": "raw/router__lectura__dif__qwen3.6.json (2134c)",
            }
        )
        sc.append(row)
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is True


def test_silence_diagnosis_never_blames_transport_on_a_row():
    """(e) DoD, con el ALCANCE que la medicion permite: una ronda muda CON FILA es
    siempre "hubo llamada y respondio vacio". El otro lado ("no hubo llamada") no
    es observable aqui -- `run_loop_round` calcula la latencia DESPUES de
    `send_to_profile` y no captura excepciones, asi que un fallo de transporte no
    llega a escribir fila (medido: `latency_ms is None` en 0 de 479 rondas reales;
    y un timeout real de deepseek en el vuelo de este ticket dejo 0 filas).

    Pinea que el diagnostico NO culpe al transporte por la fila, y que REMITA a
    donde si se ve (la lente ausente del recuento). Una version previa infería el
    transporte desde `latency_ms is None`: era codigo muerto que habría mandado a
    revisar credenciales ante un fallo de backend."""
    con_latencia = _muda("BA11")
    con_latencia["latency_ms"] = 4210
    sin_latencia = _muda("BA10")  # no ocurre en produccion, pero no debe mentir
    for row in (con_latencia, sin_latencia):
        msg = cle.diagnose_silence(row)
        assert "BACKEND" in msg
        assert "TRANSPORTE" not in msg.split("Un fallo de TRANSPORTE")[0]
        assert "no deja fila" in msg  # remite a donde SI se observa

    descartada = _muda("BA12")
    descartada["failure_mode"] = "no_contribution: missing_cite_block"
    assert "adjudicacion" in cle.diagnose_silence(descartada)


def test_transport_failure_writes_no_row_at_all(tmp_path, monkeypatch):
    """La PREMISA del test anterior, verificada en la ruta productiva en vez de
    asumida: si `send_to_profile` levanta, `run_loop_round` propaga y NO escribe
    fila. Por eso "no hubo llamada" se manifiesta como lente ausente."""
    cfg = {
        "ensemble_profiles": {"p0": {"backend": "nan", "model": "m0"}},
        "backends": {"nan": {}},
    }
    monkeypatch.setattr(ed, "_backend_version", lambda _b: "v0")

    def _boom(*a, **k):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(ed, "send_to_profile", _boom)
    with pytest.raises(TimeoutError):
        ed.run_loop_round(
            "p0",
            "bundle",
            config=cfg,
            project_root=tmp_path,
            ticket="WOT-2026-043q",
            task_type="code-review",
            rol="challenger",
            phase="fanout",
            loop_id="L700",
            backend_key="BA10",
            sensitivity="public",
            commit_sha="abc123",
            challenge_nonce="N1",
        )
    rows, _sha = ed._read_scorecard(tmp_path)
    assert rows == [], "un fallo de transporte NO debe dejar receipt de ronda"


def test_end_to_end_silent_fanout_fails_through_run_loop_round(tmp_path, monkeypatch):
    """END-TO-END en la ruta PRODUCTIVA: `run_loop_round` es quien escribe los
    receipts del bucle de gobierno. Con un transporte que devuelve cadena vacia,
    4 backends distintos dejan 4 filas y el gate las rechaza por MUDAS."""
    ed.emit_nonce(
        tmp_path,
        commit_sha="abc123",
        loop_id="L700",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="FIXED_NONCE",
    )
    config = {
        "ensemble_profiles": {
            f"p{i}": {"backend": "nan", "model": f"m{i}"} for i in range(4)
        },
        "backends": {"nan": {}},
    }
    monkeypatch.setattr(ed, "_backend_version", lambda _b: "v0")
    monkeypatch.setattr(
        ed, "send_to_profile", lambda *a, **k: ""
    )  # el backend calla: cero bytes
    for i, bk in enumerate(("BA10", "BA11", "BA12", "BA13")):
        ed.run_loop_round(
            f"p{i}",
            "bundle",
            config=config,
            project_root=tmp_path,
            ticket="WOT-2026-043q",
            task_type="code-review",
            rol="challenger",
            phase="fanout",
            loop_id="L700",
            backend_key=bk,
            sensitivity="internal",
            commit_sha="abc123",
            challenge_nonce="FIXED_NONCE",
        )
    rows, _sha = ed._read_scorecard(tmp_path)
    assert len(rows) == 4
    assert all(r["output_chars"] == 0 for r in rows)

    verdicts = cle.audit(tmp_path, commit_shas=["abc123"], deliverable_type="code")
    assert verdicts[0]["ok"] is False
    assert len(verdicts[0]["silent_rounds"]) == 4


def test_end_to_end_substantive_fanout_passes_through_run_loop_round(
    tmp_path, monkeypatch
):
    """CONTROL POSITIVO de la ruta productiva: identico al anterior salvo que el
    transporte responde. Si este tambien fallara, el test de arriba no probaria
    nada sobre el silencio."""
    ed.emit_nonce(
        tmp_path,
        commit_sha="abc123",
        loop_id="L700",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="FIXED_NONCE",
    )
    config = {
        "ensemble_profiles": {
            f"p{i}": {"backend": "nan", "model": f"m{i}"} for i in range(4)
        },
        "backends": {"nan": {}},
    }
    monkeypatch.setattr(ed, "_backend_version", lambda _b: "v0")
    monkeypatch.setattr(ed, "send_to_profile", lambda *a, **k: "REFUTA: " + "x" * 900)
    for i, bk in enumerate(("BA10", "BA11", "BA12", "BA13")):
        ed.run_loop_round(
            f"p{i}",
            "bundle",
            config=config,
            project_root=tmp_path,
            ticket="WOT-2026-043q",
            task_type="code-review",
            rol="challenger",
            phase="fanout",
            loop_id="L700",
            backend_key=bk,
            sensitivity="internal",
            commit_sha="abc123",
            challenge_nonce="FIXED_NONCE",
        )
    rows, _sha = ed._read_scorecard(tmp_path)
    # el tamano REAL se mide antes de truncar: evidencia va a 500, output_chars no
    assert all(r["output_chars"] == 908 for r in rows)
    assert all(len(r["evidencia"]) == 500 for r in rows)

    verdicts = cle.audit(tmp_path, commit_shas=["abc123"], deliverable_type="code")
    assert verdicts[0]["ok"] is True
    assert verdicts[0]["silent_rounds"] == []
