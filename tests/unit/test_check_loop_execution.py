"""Barrera de ejecucion del bucle 1->9->2 (WOT-2026-040b).

Cada rama del guard con su mutation EJECUTADA que prueba que muerde. El vector
que MUERDE de verdad (adjudicado por Codex) es el bucle DEGRADADO: N llamadas al
mismo modelo. El nonce es la ceremonia previa auditable.

Fixtures REALISTAS: filas con la forma exacta que escribe `_record_round`
(event="ronda", challenge_nonce copiado del emitido) y de `emit_nonce`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_loop_execution as cle  # noqa: E402
import ensemble_dispatch as ed  # noqa: E402
import remap_evidence_shas as remap  # noqa: E402


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


def _ronda(
    backend, nonce="N1", commit="abc", ts="2026-07-24T10:05:00+00:00", loop_id=None
):
    row = {
        "event": "ronda",
        "commit_sha": commit,
        "backend_key": backend,
        "challenge_nonce": nonce,
        "ts": ts,
    }
    if loop_id is not None:
        row["loop_id"] = loop_id
    return row


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


def test_output_chars_alone_decides_silence():
    """Hallazgo de la AUDITORIA HERMANA (contexto fresco, 2026-07-29): el fixture
    `_muda` pone las TRES senales de silencio a la vez, asi que ninguna rama queda
    discriminada -- se podia BORRAR `output_chars == 0` (el mecanismo estrella de
    este ticket) y las 26 pruebas seguian verdes. Medido: MUT-A/B/C/D -> 26 passed;
    solo neutralizando las tres a la vez mordia.

    Este test aisla la rama: `output_chars=0` con `evidencia` SUSTANTIVA y sin
    `outcome`. Si alguien quita esa condicion del criterio, esto se pone rojo."""
    emitted = [_emitted()]
    sc = []
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        row = _ronda(bk)
        # solo la senal nueva: la evidencia parece sustantiva y no hay outcome
        row.update({"output_chars": 0, "evidencia": "un hallazgo largo y citado"})
        sc.append(row)
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False, "output_chars==0 debe bastar por si solo para MUDA"
    assert v["distinct_backends"] == []


def test_outcome_no_aportacion_alone_decides_silence():
    """Misma cura para la segunda rama: `outcome` solo, sin las otras dos senales.
    Cubre la fila que marca el FILTRO DE LENTE (no el texto vacio)."""
    emitted = [_emitted()]
    sc = []
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        row = _ronda(bk)
        row.update({"output_chars": 1500, "outcome": "no-aportacion", "evidencia": "x"})
        sc.append(row)
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False
    assert v["distinct_backends"] == []


def test_empty_evidencia_marker_alone_decides_silence():
    """Tercera rama aislada: el marcador historico solo. Es la unica senal que
    tienen las filas ANTERIORES a `output_chars`, asi que su rama debe morder sin
    ayuda de las otras dos."""
    emitted = [_emitted()]
    sc = []
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        row = _ronda(bk)
        row["evidencia"] = "(respuesta vacia)"  # sin output_chars, sin outcome
        sc.append(row)
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False
    assert v["distinct_backends"] == []


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
    """(e) DoD, ACTUALIZADO tras WOT-2026-046h (2026-09-27): una ronda muda
    CON FILA y SIN `failure_mode` sigue siendo siempre "hubo llamada y
    respondio vacio" -- eso no cambio. Lo que SI cambio es el otro lado: un
    fallo de TRANSPORTE ahora SI llega a escribir fila (con `failure_mode`
    poblado, cubierto por la rama `if failure_mode:` de la funcion), asi que
    ya no es observable SOLO como lente ausente del recuento. Lo que sigue
    sin dejar fila es un rechazo del preflight de privacidad
    (`DispatchBlockedError`, la ronda nunca se ejecuto).

    Pinea que el diagnostico de una ronda muda SIN failure_mode NO culpe al
    transporte, y que remita al caso que SI queda ausente
    (`DispatchBlockedError`). Una version previa infería el transporte desde
    `latency_ms is None`: era codigo muerto que habría mandado a revisar
    credenciales ante un fallo de backend."""
    con_latencia = _muda("BA11")
    con_latencia["latency_ms"] = 4210
    sin_latencia = _muda("BA10")  # no ocurre en produccion, pero no debe mentir
    for row in (con_latencia, sin_latencia):
        msg = cle.diagnose_silence(row)
        assert "BACKEND" in msg
        assert "DispatchBlockedError" in msg  # remite a donde SI se observa
        assert "no deja fila" in msg

    descartada = _muda("BA12")
    descartada["failure_mode"] = "no_contribution: missing_cite_block"
    assert "adjudicacion" in cle.diagnose_silence(descartada)


def test_transport_failure_writes_a_row_then_reraises(tmp_path, monkeypatch):
    """ACTUALIZADO (WOT-2026-046h, 2026-09-27): la PREMISA de este test era la
    inversa hasta hoy ("un fallo de transporte NO debe dejar receipt"), y se
    invirtio a proposito -- medido en vivo 2026-09-26, 4 fallos HTTP 402
    reales no dejaron NINGUNA fila, indistinguible de "nadie lo intento".
    Ahora `send_to_profile` levantando SI escribe fila (con `failure_mode`
    clasificado) ANTES de re-lanzar -- verificado en la ruta productiva, no
    asumido."""
    cfg = {
        "ensemble_profiles": {"p0": {"backend": "nan", "model": "m0"}},
        "backends": {"nan": {}},
    }
    monkeypatch.setattr(ed, "_backend_version", lambda _b: "v0")

    def _boom(*a, **k):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(ed, "send_to_profile", _boom)
    # WOT-2026-066t: `code-review` es task_type de gobierno y la barrera de
    # `run_loop_round` exige el par VALIDO antes de gastar la ronda. Se siembra
    # el dominio real (motor git + link + emision), no un helper mockeado:
    # la resolucion del sha corre por la via productiva.
    motor, sha40 = _make_git_repo_with_commit(tmp_path / "motor")
    _link_motor(tmp_path, motor)
    ed.emit_nonce(
        tmp_path,
        commit_sha=sha40,
        loop_id="L700",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="N1",
    )
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
            commit_sha=sha40,
            challenge_nonce="N1",
        )
    rows, _sha = ed._read_scorecard(tmp_path)
    assert len(rows) == 1, "un fallo de transporte debe dejar UNA fila (WOT-2026-046h)"
    # TimeoutError ES OSError (stdlib: TimeoutError.__mro__ incluye OSError),
    # asi que la regla adjudicada en L1104 (transport_failed para
    # TransportError/OSError) lo clasifica como transport_failed, no
    # unexpected -- verificado, no asumido por el nombre de la excepcion.
    assert rows[0]["failure_mode"].startswith("transport_failed"), (
        f"TimeoutError es OSError: debe clasificar como 'transport_failed'; "
        f"got {rows[0]['failure_mode']!r}"
    )


def test_end_to_end_silent_fanout_fails_through_run_loop_round(tmp_path, monkeypatch):
    """END-TO-END en la ruta PRODUCTIVA: `run_loop_round` es quien escribe los
    receipts del bucle de gobierno. Con un transporte que devuelve cadena vacia,
    4 backends distintos dejan 4 filas y el gate las rechaza por MUDAS."""
    # WOT-2026-066t: dominio de gobierno REAL (motor git + link + emision),
    # el par debe casar por la via productiva antes de gastar cada ronda.
    motor, sha40 = _make_git_repo_with_commit(tmp_path / "motor")
    _link_motor(tmp_path, motor)
    ed.emit_nonce(
        tmp_path,
        commit_sha=sha40,
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
    monkeypatch.setattr(ed, "_backend_version", lambda *a, **k: "v0")
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
            commit_sha=sha40,
            challenge_nonce="FIXED_NONCE",
        )
    rows, _sha = ed._read_scorecard(tmp_path)
    assert len(rows) == 4
    assert all(r["output_chars"] == 0 for r in rows)

    verdicts = cle.audit(tmp_path, commit_shas=[sha40], deliverable_type="code")
    assert verdicts[0]["ok"] is False
    assert len(verdicts[0]["silent_rounds"]) == 4


def test_end_to_end_substantive_fanout_passes_through_run_loop_round(
    tmp_path, monkeypatch
):
    """CONTROL POSITIVO de la ruta productiva: identico al anterior salvo que el
    transporte responde. Si este tambien fallara, el test de arriba no probaria
    nada sobre el silencio."""
    # WOT-2026-066t: igual que el par de arriba, dominio REAL de emision.
    motor, sha40 = _make_git_repo_with_commit(tmp_path / "motor")
    _link_motor(tmp_path, motor)
    ed.emit_nonce(
        tmp_path,
        commit_sha=sha40,
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
    monkeypatch.setattr(ed, "_backend_version", lambda *a, **k: "v0")
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
            commit_sha=sha40,
            challenge_nonce="FIXED_NONCE",
        )
    rows, _sha = ed._read_scorecard(tmp_path)
    # el tamano REAL se mide antes de truncar: evidencia va a 500, output_chars no
    assert all(r["output_chars"] == 908 for r in rows)
    assert all(len(r["evidencia"]) == 500 for r in rows)

    verdicts = cle.audit(tmp_path, commit_shas=[sha40], deliverable_type="code")
    assert verdicts[0]["ok"] is True
    assert verdicts[0]["silent_rounds"] == []


# ---------------------------------------------------------------------------
# WOT-2026-044p: orphan nonces (nonce emitted without rounds)
# ---------------------------------------------------------------------------


def test_orphan_nonces_detected_when_no_rounds():
    """WOT-2026-044p (b): a nonce emitted for a commit but with no corresponding
    scorecard rounds is an orphan -- the loop was DECLARED but never ACCREDITED."""
    emitted = [_emitted(nonce="ORPHAN1", commit="abc")]
    scorecard = []  # no rounds at all
    orphans = cle.orphan_nonces(scorecard, emitted, commit_sha="abc")
    assert len(orphans) == 1
    assert orphans[0]["nonce"] == "ORPHAN1"
    assert "DECLARADO" in orphans[0]["diagnosis"]
    assert "ACREDITADO" in orphans[0]["diagnosis"]


def test_orphan_nonces_empty_when_rounds_exist():
    """A nonce with corresponding rounds is NOT an orphan."""
    emitted = [_emitted(nonce="N1", commit="abc")]
    scorecard = [
        {
            "event": "ronda",
            "backend_key": "BA11",
            "challenge_nonce": "N1",
            "commit_sha": "abc",
            "ts": "2026-07-24T10:00:01+00:00",
            "output_chars": 100,
            "evidencia": "some response",
        }
    ]
    orphans = cle.orphan_nonces(scorecard, emitted, commit_sha="abc")
    assert orphans == []


def test_orphan_nonces_only_for_this_commit():
    """Nonces for OTHER commits are not orphans of this commit."""
    emitted = [_emitted(nonce="N1", commit="other_commit")]
    scorecard = []  # no rounds for "abc"
    orphans = cle.orphan_nonces(scorecard, emitted, commit_sha="abc")
    assert orphans == []


def test_audit_commit_includes_orphan_nonces():
    """audit_commit returns orphan_nonces in its verdict dict."""
    emitted = [_emitted(nonce="ORPHAN1", commit="abc")]
    scorecard = []
    verdict = cle.audit_commit(scorecard, emitted, commit_sha="abc", min_distinct=4)
    assert "orphan_nonces" in verdict
    assert len(verdict["orphan_nonces"]) == 1
    assert verdict["orphan_nonces"][0]["nonce"] == "ORPHAN1"


# ---------------------------------------------------------------------------
# S1B item 1: normalizar el sha en la ENTRADA CLI (el join exacto queda intacto)
# ---------------------------------------------------------------------------


def _make_git_repo_with_commit(root: Path, *, seed: str = "seed") -> tuple[Path, str]:
    """Repo git REAL en `root` con un commit; devuelve (repo, sha40 de HEAD).

    Hermetico: `.git` propio para que el walk-up de git no alcance el repo REAL
    y el probe conteste sobre el arbol de la maquina (vector documentado en
    AGENTS.md).
    """
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "seed.txt").write_text(seed, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", seed], check=True)
    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return root, out.stdout.strip()


def _build_accredited_ensemble(dest: Path, sha40: str) -> None:
    """Ensemble anclado al sha40: un nonce y 4 lentes sustantivas (verde para code)."""
    ed.emit_nonce(
        dest,
        commit_sha=sha40,
        loop_id="L-SHATEST",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="N-SHATEST",
    )
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        ed.append_scorecard(
            dest,
            {
                "event": "ronda",
                "commit_sha": sha40,
                "backend_key": bk,
                "challenge_nonce": "N-SHATEST",
                "ts": "2099-01-01T00:00:00+00:00",
            },
        )


def test_cli_short_sha_and_sha40_give_the_same_verdict(tmp_path, capsys):
    """S1B item 1 (MUTACION): sha corto y sha40 dan el MISMO veredicto.

    Defecto medido 2026-09-07 sobre el destino real: `--commit-sha c54b9de`
    (corto) -> `FAIL 0/4 lentes []` rc=1 (ROJO FALSO); el sha40 -> `OK 4/4`
    rc=0. Con el fix, las DOS formas del MISMO commit resuelven al sha40 y el
    veredicto es identico. Revertir la normalizacion vuelve a diferirlos (lo
    pinea el test siguiente)."""
    repo, sha40 = _make_git_repo_with_commit(tmp_path / "repo")
    _build_accredited_ensemble(repo, sha40)
    rc = cle.main(
        [
            "--project-root",
            str(repo),
            "--commit-sha",
            sha40[:7],
            "--commit-sha",
            sha40,
            "--deliverable-type",
            "code",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    # dos veredictos por-commit identicos (la linea final de resumen tambien
    # dice "OK", por eso se cuenta el detalle y no el marcador a secas)
    assert out.count("4/4 lentes distintas") == 2, out
    assert out.count("[loop-exec] FAIL") == 0, out
    assert "0/4" not in out, out


def test_cli_short_sha_without_normalization_is_a_false_red(
    tmp_path, monkeypatch, capsys
):
    """El estado PRE-fix (mutacion revertida a identidad): el sha corto llega
    crudo al join EXACTO y produce el ROJO FALSO medido 2026-09-07. Si la
    normalizacion desaparece del CLI, este test y el de arriba ya no pueden ser
    verdes a la vez: el veredicto difiere por la FORMA del sha."""
    repo, sha40 = _make_git_repo_with_commit(tmp_path / "repo")
    _build_accredited_ensemble(repo, sha40)
    monkeypatch.setattr(cle, "resolve_input_commit_sha", lambda _root, sha: sha)
    rc = cle.main(
        [
            "--project-root",
            str(repo),
            "--commit-sha",
            sha40[:7],
            "--deliverable-type",
            "code",
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "[loop-exec] FAIL" in out and "0/4" in out, out


def test_cli_unresolvable_sha_is_rejected_with_a_message(tmp_path, capsys):
    """Fail-closed NOMBRADO: un sha que no resuelve ni en el motor ni en el
    destino no produce un veredicto `0/4` ambiguo: se rechaza con la razon y el
    sha nombrado. El veredicto no se inventa."""
    rc = cle.main(
        [
            "--project-root",
            str(tmp_path),
            "--commit-sha",
            "deadbeef" * 5,
            "--deliverable-type",
            "code",
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "no resuelve a un commit" in out, out
    assert "deadbeef" in out, out


# ---------------------------------------------------------------------------
# S1B item 3 (C', DEC-bucle-doc-001): contar lentes POR INSTANCIA (nonce)
# ---------------------------------------------------------------------------


def test_two_nonces_two_lenses_each_no_longer_reach_n():
    """MUTACION C' (la del DEC): dos nonces con 2 lentes cada uno -> ANTES la
    union daba 4/4 OK; AHORA el veredicto es POR INSTANCIA (2/4 y 2/4 -> FAIL).

    'N lentes distintas' significa N lentes en la MISMA corrida: la union de
    dos corridas distintas no prueba independencia. La union sigue
    informandose en `distinct_backends`, pero ya no decide."""
    emitted = [_emitted(nonce="NA"), _emitted(nonce="NB")]
    sc = [
        _ronda("BA10", nonce="NA"),
        _ronda("BA11", nonce="NA"),
        _ronda("BA12", nonce="NB"),
        _ronda("BA13", nonce="NB"),
    ]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False, (
        "ninguna instancia llega a N; la suma de corridas no acredita: "
        f"{v['per_nonce']}"
    )
    assert v["distinct_backends"] == ["BA10", "BA11", "BA12", "BA13"]
    assert sorted(e["distinct"] for e in v["per_nonce"]) == [2, 2]
    assert all(not e["ok"] for e in v["per_nonce"])


def test_one_instance_reaching_minimum_still_passes():
    """CONTROL POSITIVO: la misma forma de fixture con UNA instancia que SI
    alcanza N sigue en verde. Sin este control, endurecer el veredicto seria
    indistinguible de romper la rama verde."""
    emitted = [_emitted(nonce="NA"), _emitted(nonce="NB")]
    sc = [
        _ronda("BA10", nonce="NA"),
        _ronda("BA11", nonce="NA"),
        _ronda("BA12", nonce="NA"),
        _ronda("BA13", nonce="NA"),
        _ronda("BA12", nonce="NB"),
    ]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is True
    assert v["silent_rounds"] == []


def test_instances_below_minimum_are_named_in_the_verdict():
    """Las instancias que no llegan a N se NOMBRAN (criterio ya aplicado a las
    mudas): cada entrada de `per_nonce` lleva su nonce y sus backends."""
    emitted = [_emitted(nonce="NA"), _emitted(nonce="NB")]
    sc = [
        _ronda("BA10", nonce="NA"),
        _ronda("BA11", nonce="NA"),
        _ronda("BA12", nonce="NB"),
    ]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    by_nonce = {e["nonce"]: e for e in v["per_nonce"]}
    assert by_nonce["NA"]["backends"] == ["BA10", "BA11"]
    assert by_nonce["NA"]["ok"] is False
    assert by_nonce["NB"]["backends"] == ["BA12"]
    assert by_nonce["NB"]["ok"] is False


def test_fabricated_nonce_round_is_named_not_silently_dropped():
    """C': el receipt con nonce no emitido ya NO desaparece en un `continue`
    mudo: se reporta en `fabricated_rounds` con backend, nonce y razon."""
    emitted = [_emitted(nonce="N1")]
    sc = [_ronda(bk, nonce="FABRICADO") for bk in ("BA10", "BA11", "BA12", "BA13")]
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert v["ok"] is False
    assert {f["backend_key"] for f in v["fabricated_rounds"]} == {
        "BA10",
        "BA11",
        "BA12",
        "BA13",
    }
    assert "fabricado" in v["fabricated_rounds"][0]["reason"]
    # el emisor con nonce fabricado se excluye por EMISOR, no por el nonce:
    # no se reporta aqui (misma condicion que structurally_valid_rounds)
    sc2 = [_ronda("BA01", nonce="FABRICADO")]
    v2 = cle.audit_commit(sc2, [_emitted()], commit_sha="abc", min_distinct=4)
    assert v2["fabricated_rounds"] == []


# ------------------------------------------------- S1B item 3c: nonce reutilizado


SHA_A = "a" * 40
SHA_B = "b" * 40


def test_reject_nonce_reuse_names_the_collision(tmp_path):
    """S1B item 3c: un nonce ya usado con OTRO sha o con OTRO loop_id se
    rechaza nombrando la colision; el MISMO par (sha, loop_id) es un reintento
    legitimo y NO rechaza; un nonce sin uso previo pasa."""
    ed.append_scorecard(
        tmp_path,
        {
            "event": "ronda",
            "commit_sha": SHA_A,
            "backend_key": "BA10",
            "challenge_nonce": "N1",
            "ts": "2026-09-07T10:00:00+00:00",
            "loop_id": "L-A",
        },
    )
    with pytest.raises(ValueError, match="YA fue usado"):
        ed.reject_nonce_reuse(
            tmp_path, challenge_nonce="N1", commit_sha=SHA_B, loop_id="L-B"
        )
    with pytest.raises(ValueError, match="loop_id='L-B'"):
        ed.reject_nonce_reuse(
            tmp_path, challenge_nonce="N1", commit_sha=SHA_A, loop_id="L-B"
        )
    # reintento legitimo del MISMO par: no rechaza
    ed.reject_nonce_reuse(
        tmp_path, challenge_nonce="N1", commit_sha=SHA_A, loop_id="L-A"
    )
    # nonce sin uso previo: pasa
    ed.reject_nonce_reuse(
        tmp_path, challenge_nonce="N2", commit_sha=SHA_B, loop_id="L-B"
    )


def _link_motor(dest: Path, motor: Path) -> Path:
    """Escribe el motor_destination_link.json que `resolve_motor_root` lee."""
    cfg = dest / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(motor)}), encoding="utf-8"
    )
    return dest


def _loop_round_args(dest: Path, **overrides):
    """Namespace con la forma que exige el CLI `loop-round`."""
    defaults = dict(
        profile="p0",
        content_file=str(dest / "bundle.md"),
        ticket="WOT-2026-000x",
        task_type="weird",  # invalido a proposito: el error de uso debe quedar
        rol="challenger",
        phase="fanout",
        loop_id="L-B",
        backend_key="BA10",
        data_sensitivity="public",
        ronda=1,
        context_kind="diff",
        commit_sha=None,
        challenge_nonce=None,
        session_id=None,
        project_root=str(dest),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_loop_round_call_site_blocks_nonce_reuse_before_any_row(tmp_path):
    """El CALL-SITE (una barrera tras una clausula guard nunca corre):
    `loop-round` rechaza el nonce reutilizado ANTES de escribir fila y sin
    rastro nuevo en el scorecard.

    PRECEDENCIA = mutacion in-suite: el task_type es invalido a proposito, asi
    que si alguien RETIRA la llamada a `reject_nonce_reuse`, el error que sube
    es el de task_type ('invalido') y este test cae por mensaje."""
    motor = tmp_path / "motor"
    _repo, sha = _make_git_repo_with_commit(motor)
    dest = tmp_path / "dest"
    _link_motor(dest, motor)
    prev = {
        "event": "ronda",
        "commit_sha": sha,
        "backend_key": "BA10",
        "challenge_nonce": "N1",
        "ts": "2026-09-07T10:00:00+00:00",
        "loop_id": "L-A",
    }
    ed.append_scorecard(dest, prev)
    stored_before, _ = ed._read_scorecard(dest)

    args = _loop_round_args(
        dest, task_type="weird", commit_sha=sha, challenge_nonce="N1", loop_id="L-B"
    )
    with pytest.raises(ValueError, match="YA fue usado"):
        ed._cmd_loop_round(args, {})
    rows, _sha = ed._read_scorecard(dest)
    assert rows == stored_before, "el rechazo NO debe escribir fila ninguna"

    # y el MISMO par (sha, loop_id) es un reintento legitimo: pasa de la
    # barrera y cae despues por el task_type invalido (evidencia de orden)
    args_retry = _loop_round_args(
        dest, task_type="weird", commit_sha=sha, challenge_nonce="N1", loop_id="L-A"
    )
    with pytest.raises(ValueError, match="task_type"):
        ed._cmd_loop_round(args_retry, {})
    rows_after, _ = ed._read_scorecard(dest)
    assert rows_after == stored_before, "sin perfil resoluble no debe quedar fila"


def test_loop_round_handler_defaults_session_id_for_usage_error_row(tmp_path):
    """WOT-2026-040g: el default del `session_id` en el BORDE del handler cubre
    tambien las filas que NO pasan por `run_loop_round` (aqui, un fallo de USO
    que se registra en `_cmd_loop_round`). Sin el, esa fila quedaria
    NO-ATRIBUIBLE aunque la ronda si lo estuviera."""
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "bundle.md").write_text("bundle", encoding="utf-8")
    sid = "20260101-0001-nogit-" + "a" * 32
    (dest / ".agent" / "runtime" / "session" / sid).mkdir(parents=True)

    cfg = {
        "ensemble_profiles": {"p0": {"backend": "nan", "model": "m0"}},
        "backends": {"nan": {}},
    }
    args = _loop_round_args(dest, task_type="weird", phase="fanout")
    with pytest.raises(ValueError, match="task_type"):
        ed._cmd_loop_round(args, cfg)
    rows, _sha = ed._read_scorecard(dest)
    assert rows, "el fallo de uso debe dejar fila (WOT-2026-048i)"
    assert rows[-1]["failure_mode"] == "usage-error"
    assert rows[-1]["session_id"] == sid, rows[-1]


# ---------------------------------------------------------------------------
# WOT-2026-059n: el LECTOR resuelve shas del DESTINO via resolve_governed_commit_sha
# ---------------------------------------------------------------------------


def _two_repos(tmp_path):
    """Motor y destino INDEPENDIENTES, cada uno con su commit propio.

    Devuelve (motor, sha_motor, destino, sha_destino). Los dos son repos git
    REALES con .git propio (hermetico contra el repo real de la maquina).
    Los SHAs son DISTINTOS y NO compartidos: genesis con contenido diferente
    garantiza que sha_m no existe en destino y viceversa.
    """
    motor, sha_m = _make_git_repo_with_commit(tmp_path / "motor", seed="motor-seed")
    destino, _sha_d_initial = _make_git_repo_with_commit(
        tmp_path / "destino", seed="destino-seed"
    )
    _link_motor(destino, motor)
    # Anadir contenido al destino para crear un segundo commit.
    (destino / "extra.txt").write_text("extra", encoding="utf-8")
    subprocess.run(["git", "-C", str(destino), "add", "extra.txt"], check=True)
    subprocess.run(["git", "-C", str(destino), "commit", "-qm", "extra"], check=True)
    out = subprocess.run(
        ["git", "-C", str(destino), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    sha_d = out.stdout.strip()
    assert sha_d != sha_m, "motor y destino deben tener SHAs distintos"
    # Verificar que sha_m NO existe como commit en destino.
    probe = subprocess.run(
        ["git", "-C", str(destino), "cat-file", "-e", f"{sha_m}^{{commit}}"],
        capture_output=True,
    )
    assert probe.returncode != 0, (
        f"sha_m ({sha_m[:12]}...) no debe existir en destino; "
        "el test de mutation no seria discriminante"
    )
    return motor, sha_m, destino, sha_d


def _build_accredited_ensemble_dest(tmp_path, destino, sha, *, loop_id="L-TEST"):
    """Ensemble anclado al sha: emite nonce + 4 lentes, con timestamps
    coherentes (ronda DESPUES del nonce)."""
    from datetime import datetime, timezone

    ed.emit_nonce(
        destino,
        commit_sha=sha,
        loop_id=loop_id,
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce=f"N-{loop_id}",
    )
    # Usar un timestamp DESPUES de la emision real para que el guard no
    # rechace la ronda por "nonce emitido despues de la ronda".
    now = datetime.now(timezone.utc).isoformat()
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        ed.append_scorecard(
            destino,
            {
                "event": "ronda",
                "commit_sha": sha,
                "backend_key": bk,
                "challenge_nonce": f"N-{loop_id}",
                "ts": now,
                "loop_id": loop_id,
            },
        )


def test_destination_sha_resolves_through_audit(tmp_path, capsys):
    """WOT-2026-059n DoD (a): un sha que SOLO vive en el destino se resuelve
    a traves de check_loop_execution.audit, no produce ERROR de resolucion.

    El lector usa resolve_governed_commit_sha (ensemble_dispatch) que prueba
    contra el motor Y el destino. Un sha del destino no puede contar como
    'no-resoluble'."""
    _motor, _sha_m, destino, sha_d = _two_repos(tmp_path)
    _build_accredited_ensemble_dest(tmp_path, destino, sha_d, loop_id="L-DEST")
    verdicts = cle.audit(
        destino,
        commit_shas=[sha_d],
        deliverable_type="code",
        loop_id="L-DEST",
    )
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v["commit_sha"] == sha_d
    assert v["ok"] is True, (
        f"sha del destino debe resolver y pasar: {v['distinct_backends']}"
    )
    assert len(v["distinct_backends"]) >= 4


def test_motor_sha_no_regression(tmp_path):
    """WOT-2026-059n DoD (b): un sha del motor sigue resolviendo igual
    (sin regresion del writer ni del lector)."""
    _motor, sha_m, destino, _sha_d = _two_repos(tmp_path)
    _build_accredited_ensemble_dest(tmp_path, destino, sha_m, loop_id="L-MOTOR")
    verdicts = cle.audit(
        destino,
        commit_shas=[sha_m],
        deliverable_type="code",
        loop_id="L-MOTOR",
    )
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v["commit_sha"] == sha_m
    assert v["ok"] is True


def test_destination_sha_resolution_mutation_motor_only(tmp_path, capsys):
    """WOT-2026-059n mutation-verify: si resolve_input_commit_sha SOLO resuelve
    contra el motor (mutacion a identidad), un sha del destino FALLA con
    'no resuelve a un commit' -- evidencia de que la resolucion dual es lo
    UNICO que decide el veredicto.

    Rojo previo: sin resolve_governed_commit_sha (o con una que solo mira
    el motor), el sha del destino produce ERROR."""
    _motor, _sha_m, destino, sha_d = _two_repos(tmp_path)
    _build_accredited_ensemble_dest(tmp_path, destino, sha_d, loop_id="L-DEST")

    original = cle.resolve_input_commit_sha

    def motor_only(project_root, sha):
        return original(_motor, sha)

    import unittest.mock as mock

    with mock.patch.object(cle, "resolve_input_commit_sha", motor_only):
        rc = cle.main(
            [
                "--project-root",
                str(destino),
                "--commit-sha",
                sha_d,
                "--deliverable-type",
                "code",
                "--loop-id",
                "L-DEST",
            ]
        )
    assert rc == 1, "sin resolucion dual, sha del destino debe fallar"
    out = capsys.readouterr().out
    assert "no resuelve" in out or "FAIL" in out, out


def test_destination_sha_resolution_mutation_dest_only(tmp_path, capsys):
    """WOT-2026-059n mutation-verify: si resolve_governed_commit_sha SOLO
    resuelve contra el destino (mutacion), un sha del motor FALLA --
    evidencia de que la resolucion AMBAS raices es lo que protege la
    regresion.

    La mutacion reemplaza resolve_governed_commit_sha en check_loop_execution
    para que SOLO pruebe contra project_root (destino), nunca contra
    motor_root. Un sha que solo existe en el motor no resuelve -> ValueError
    -> rc=1."""
    _motor, sha_m, destino, _sha_d = _two_repos(tmp_path)
    _build_accredited_ensemble_dest(tmp_path, destino, sha_m, loop_id="L-MOTOR")

    def _dest_only_res(_motor_root, project_root, sha):
        ok, resolved = ed._canonical_motor_commit_sha(project_root, sha)
        if ok:
            return resolved, "repo_destino"
        raise ValueError(
            f"'{sha}' no resuelve a un commit del destino ({project_root})"
        )

    import unittest.mock as mock

    with mock.patch.object(cle, "resolve_governed_commit_sha", _dest_only_res):
        rc = cle.main(
            [
                "--project-root",
                str(destino),
                "--commit-sha",
                sha_m,
                "--deliverable-type",
                "code",
                "--loop-id",
                "L-MOTOR",
            ]
        )
    assert rc == 1, "sin resolucion contra motor, sha del motor debe fallar"
    out = capsys.readouterr().out
    assert "no resuelve" in out or "FAIL" in out, out


# --------------------------------------------------- WOT-2026-055o: exploracion
def test_structurally_valid_rounds_excludes_exploracion_task_type():
    """DEFENSA EN PROFUNDIDAD: una fila de trafico EXPLORATORIO que POR ERROR
    llevara un `commit_sha` + `challenge_nonce` validos de un bucle de gobierno
    real NO cuenta para la barrera de independencia.

    Por que hace falta si el filtro de nonce ya la deja fuera: antes de
    WOT-2026-055o el trafico exploratorio no dejaba fila, y despues de el SI
    la deja (con `event="ronda"`); un caller exploratorio que reutilizara un
    nonce real colaria. MUTATION: quitar el filtro explicito de `task_type` ->
    la fila exploratoria cuenta y este test cae.

    CONTROL POSITIVO: la MISMA fixture con un `task_type` de gobierno sigue
    contando exactamente igual que antes.
    """
    emitted = [_emitted()]
    exploratoria = {**_ronda("BA10"), "task_type": "exploracion"}
    gobierno = [_ronda(bk) for bk in ("BA11", "BA12", "BA13")]
    sc = [exploratoria, *gobierno]

    valid = cle.structurally_valid_rounds(sc, emitted, commit_sha="abc")
    assert [r["backend_key"] for r in valid] == ["BA11", "BA12", "BA13"], (
        "la fila exploratoria NO puede colar en la barrera aunque su "
        "commit_sha+nonce sean los de un bucle de gobierno real"
    )
    assert "BA10" not in {r["backend_key"] for r in valid}

    # Efecto en el veredicto: con 4 min, 3 lentes reales NO alcanzan N.
    verdict = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=4)
    assert verdict["distinct_backends"] == ["BA11", "BA12", "BA13"]
    assert verdict["ok"] is False

    # CONTROL POSITIVO: misma fila, task_type de gobierno -> SI cuenta.
    misma = [{**_ronda("BA10"), "task_type": "contract-audit"}, *gobierno]
    valid_gov = cle.structurally_valid_rounds(misma, emitted, commit_sha="abc")
    assert {r["backend_key"] for r in valid_gov} == {
        "BA10",
        "BA11",
        "BA12",
        "BA13",
    }
    verdict_gov = cle.audit_commit(misma, emitted, commit_sha="abc", min_distinct=4)
    assert verdict_gov["ok"] is True


# ------------------------------------------------- WOT-2026-044l: bundle_sha256
def test_bundle_sha256_groups_separates_foreign_citations():
    """El caso real medido (17 citas de un commit, 0 legitimas): tres bucles
    sobre OTRA cosa citaron el mismo commit por inercia. Agrupar por
    bundle_sha256 separa el grupo legitimo (3 filas, mismo hash) de las 2
    citas foraneas (hashes distintos entre si)."""
    emitted = [_emitted()]
    legitimo = [
        {**_ronda(bk), "bundle_sha256": "hashA"} for bk in ("BA10", "BA11", "BA12")
    ]
    foraneas = [
        {**_ronda("BA13"), "bundle_sha256": "hashB"},
        {**_ronda("BA14"), "bundle_sha256": "hashC"},
    ]
    sc = [*legitimo, *foraneas]

    groups = cle.bundle_sha256_groups(sc, emitted, commit_sha="abc")

    assert {h: len(rows) for h, rows in groups.items()} == {
        "hashA": 3,
        "hashB": 1,
        "hashC": 1,
    }


def test_foreign_bundle_rounds_reports_the_minority_hashes():
    emitted = [_emitted()]
    legitimo = [
        {**_ronda(bk), "bundle_sha256": "hashA"} for bk in ("BA10", "BA11", "BA12")
    ]
    foraneas = [
        {**_ronda("BA13"), "bundle_sha256": "hashB"},
        {**_ronda("BA14"), "bundle_sha256": "hashC"},
    ]
    sc = [*legitimo, *foraneas]

    foreign = cle.foreign_bundle_rounds(sc, emitted, commit_sha="abc")

    assert {r["backend_key"] for r in foreign} == {"BA13", "BA14"}


def test_foreign_bundle_rounds_empty_when_all_rounds_share_one_hash():
    """ANTI-FALSO-POSITIVO: un bucle legitimo donde TODAS las lentes recibieron
    el mismo bundle no reporta ninguna fila foranea."""
    emitted = [_emitted()]
    sc = [{**_ronda(bk), "bundle_sha256": "hashA"} for bk in ("BA10", "BA11", "BA12")]

    assert cle.foreign_bundle_rounds(sc, emitted, commit_sha="abc") == []


def test_foreign_bundle_rounds_ignores_rows_without_bundle_hash():
    """Filas sin bundle_sha256 (legacy, o fallo antes de leer el bundle) NUNCA
    se acusan de ser foraneas: ausencia de dato no es evidencia de contenido
    distinto."""
    emitted = [_emitted()]
    sc = [
        {**_ronda("BA10"), "bundle_sha256": "hashA"},
        {**_ronda("BA11"), "bundle_sha256": "hashA"},
        _ronda("BA12"),  # sin bundle_sha256 -> None
    ]

    assert cle.foreign_bundle_rounds(sc, emitted, commit_sha="abc") == []


def test_mutation_altering_one_rounds_bundle_hash_flags_it_as_foreign():
    """MUTATION (DoD d): alterar el bundle_sha256 de UNA fila (simulando que su
    bundle fue distinto del resto) hace que `foreign_bundle_rounds` la detecte;
    restaurar el hash original la vuelve a dejar fuera."""
    emitted = [_emitted()]
    sc = [{**_ronda(bk), "bundle_sha256": "hashA"} for bk in ("BA10", "BA11", "BA12")]

    assert cle.foreign_bundle_rounds(sc, emitted, commit_sha="abc") == []

    sc[0]["bundle_sha256"] = "hashA-tampered"
    foreign = cle.foreign_bundle_rounds(sc, emitted, commit_sha="abc")
    assert {r["backend_key"] for r in foreign} == {"BA10"}

    sc[0]["bundle_sha256"] = "hashA"
    assert cle.foreign_bundle_rounds(sc, emitted, commit_sha="abc") == []


# ---------------------------------------- WOT-2026-044l DoD (f): "auditar" un commit
def test_auditing_rounds_for_commit_matches_the_declared_criterion():
    rounds = [
        {
            "event": "ronda",
            "commit_sha": "abc",
            "ticket": "WOT-TEST-044l",
            "phase": "CONTRACT_AUDIT",
            "output_chars": 500,
        },
        {
            # fase de gobierno pero NO es MANAGER_REVIEW/CONTRACT_AUDIT
            "event": "ronda",
            "commit_sha": "abc",
            "ticket": "WOT-TEST-044l",
            "phase": "CLOSE",
            "output_chars": 500,
        },
        {
            # ticket distinto del dueno del commit -> no cuenta
            "event": "ronda",
            "commit_sha": "abc",
            "ticket": "WOT-TEST-OTRO",
            "phase": "manager-review",
            "output_chars": 500,
        },
        {
            # muda: output_chars == 0 -> no cuenta
            "event": "ronda",
            "commit_sha": "abc",
            "ticket": "WOT-TEST-044l",
            "phase": "manager-review",
            "output_chars": 0,
        },
    ]

    auditing = cle.auditing_rounds_for_commit(
        rounds, commit_sha="abc", commit_owner_ticket="WOT-TEST-044l"
    )

    assert len(auditing) == 1
    assert auditing[0]["phase"] == "CONTRACT_AUDIT"


def test_auditing_rounds_for_commit_normalizes_phase_case_and_hyphens():
    rounds = [
        {
            "event": "ronda",
            "commit_sha": "abc",
            "ticket": "WOT-TEST-044l",
            "phase": "manager-review",
            "output_chars": 10,
        },
    ]

    auditing = cle.auditing_rounds_for_commit(
        rounds, commit_sha="abc", commit_owner_ticket="WOT-TEST-044l"
    )

    assert len(auditing) == 1


# ---------------------------------------------------------------------------
# WOT-2026-086f: fabricated_nonce_rounds filtra scorecard por loop_id
# ---------------------------------------------------------------------------


def test_fabricated_nonce_rounds_filters_scorecard_by_loop_id():
    """WOT-2026-086f DoD D5(b): fabricado filtra scorecard por loop_id.

    Mutation: revertir el fix (dejar de filtrar por loop_id en scorecard) ->
    ROJO.

    Escenario: dos nonces del mismo sha pero loop_id distinto. La ronda del
    loop_id X no debe marcarse fabricada si tiene su propio nonce emitido,
    aunque comparta commit_sha con otro bucle.
    """
    emitted_ab = [
        _emitted(nonce="N_A", commit=SHA_A, loop="X"),
        _emitted(nonce="N_B", commit=SHA_A, loop="Y"),
    ]
    sc = [
        _ronda("BA10", commit=SHA_A, nonce="N_A", loop_id="X"),
        _ronda("BA11", commit=SHA_A, nonce="N_A", loop_id="X"),
        _ronda("BA12", commit=SHA_A, nonce="N_B", loop_id="Y"),
        _ronda("BA13", commit=SHA_A, nonce="N_B", loop_id="Y"),
    ]

    # Con loop_id="X": N_A es valido, N_B no es de X pero las filas de Y
    # se filtran FUERA (tienen loop_id="Y" != "X"), asi que no se marcan
    # fabricadas (son de otro bucle, no fabricadas para X).
    v = cle.fabricated_nonce_rounds(sc, emitted_ab, commit_sha=SHA_A, loop_id="X")
    assert v == [], (
        "con loop_id='X', solo las filas con loop_id='X' se chequean; "
        "N_A es valido para X, las de Y se filtran fuera"
    )

    # Sin filtrar por loop_id explicito: se filtran TODAS las filas del
    # scorecard por su propio loop_id implicito (que es None si no se da
    # loop_id a la funcion, asi que se chequean TODAS, no solo las de X).
    v_all = cle.fabricated_nonce_rounds(sc, emitted_ab, commit_sha=SHA_A)
    assert len(v_all) == 0, (
        "sin loop_id explicito, todas las filas del scorecard se chequean "
        "y N_A/N_B existen en el ledger"
    )


# ---------------------------------------------------------------------------
# WOT-2026-088b: pista de remapeo en la ruta de fallo (0 rondas + huerfanos)
# ---------------------------------------------------------------------------


def _round_for(repo: Path, sha: str, *, backend: str = "BA10") -> None:
    """Ronda con un nonce NO emitido: fabrica, asi `per_nonce` queda vacio."""
    ed.append_scorecard(
        repo,
        {
            "event": "ronda",
            "commit_sha": sha,
            "backend_key": backend,
            "challenge_nonce": "N-FAB",
            "ts": "2099-01-01T00:00:00+00:00",
        },
    )


def test_088b_cero_rondas_con_sha_huerfano_nombra_la_herramienta(tmp_path, capsys):
    """D9: veredicto con 0 rondas + SHA no resoluble -> la salida de fallo
    nombra `scripts/remap_evidence_shas.py`, la regla (arbol Y patch-id) y el
    SHA no resoluble."""
    repo, sha = _make_git_repo_with_commit(tmp_path / "repo")
    orphan = "deadbeef" * 5
    _round_for(repo, sha)
    _round_for(repo, orphan, backend="BA11")
    rc = cle.main(
        [
            "--project-root",
            str(repo),
            "--commit-sha",
            sha,
            "--deliverable-type",
            "code",
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "remap_evidence_shas" in out
    assert "no resolubles" in out
    assert "patch-id" in out
    assert orphan in out


def test_088b_sin_huerfanos_no_hay_pista(tmp_path, capsys):
    """MUTACION (e): sin SHAs no resolubles la pista NO aparece (el rojo del
    veredicto se mantiene: la pista no sustituye al fallo)."""
    repo, sha = _make_git_repo_with_commit(tmp_path / "repo")
    _round_for(repo, sha)
    rc = cle.main(
        [
            "--project-root",
            str(repo),
            "--commit-sha",
            sha,
            "--deliverable-type",
            "code",
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "remap_evidence_shas" not in out
    assert "[loop-exec] FAIL" in out


def test_088b_la_pista_no_cambia_veredicto_ni_exit_code(tmp_path, capsys, monkeypatch):
    """D9: la pista es DIAGNOSTICA; el mismo escenario con y sin huerfanos da
    el MISMO exit code y el mismo veredicto por commit."""
    repo, sha = _make_git_repo_with_commit(tmp_path / "repo")
    _round_for(repo, sha)
    _round_for(repo, "deadbeef" * 5, backend="BA11")
    args = [
        "--project-root",
        str(repo),
        "--commit-sha",
        sha,
        "--deliverable-type",
        "code",
    ]
    rc_con = cle.main(args)
    out_con = capsys.readouterr().out
    assert rc_con == 1 and "PISTA" in out_con

    monkeypatch.setattr(cle, "_unresolvable_evidence_shas", lambda _root: [])
    rc_sin = cle.main(args)
    out_sin = capsys.readouterr().out
    assert rc_sin == 1
    assert "PISTA" not in out_sin
    assert "[loop-exec] FAIL" in out_sin and "0/4" in out_sin
    assert "[loop-exec] FAIL" in out_con and "0/4" in out_con


def test_088b_cli_de_produccion_bloquea_y_tras_remapear_pasa(tmp_path):
    """D9/D10 end-to-end por la RUTA DE PRODUCCION (`sys.executable script`).

    Repo temporal CON su propio `.git` (hermetico). Se reescribe el mensaje del
    commit (mismo arbol y patch-id, SHA nuevo) y la evidencia queda citando el
    viejo: el CLI falla para el commit nuevo. Tras remapear (`--apply`), pasa.
    """
    repo, old = _make_git_repo_with_commit(tmp_path / "repo")
    tree = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{old}^{{tree}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    new = subprocess.run(
        ["git", "-C", str(repo), "commit-tree", tree, "-m", "reworded"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert new != old

    ed.emit_nonce(
        repo,
        commit_sha=old,
        loop_id="L-088B",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="N-REMAP",
    )
    for bk in ("BA10", "BA11", "BA12", "BA13"):
        ed.append_scorecard(
            repo,
            {
                "event": "ronda",
                "commit_sha": old,
                "backend_key": bk,
                "challenge_nonce": "N-REMAP",
                "ts": "2099-01-01T00:00:00+00:00",
                "loop_id": "L-088B",
            },
        )

    script = SCRIPTS_DIR / "check_loop_execution.py"

    def _cli(commit: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(script),
                "--project-root",
                str(repo),
                "--commit-sha",
                commit,
                "--deliverable-type",
                "code",
            ],
            capture_output=True,
            text=True,
        )

    blocked = _cli(new)
    assert blocked.returncode == 1, blocked.stdout + blocked.stderr
    assert "0/4" in blocked.stdout

    rc = remap.main(
        [
            "--project-root",
            str(repo),
            "--git-root",
            str(repo),
            "--map",
            f"{old}={new}",
            "--apply",
        ]
    )
    assert rc == 0

    passed = _cli(new)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert "4/4" in passed.stdout


# --------------------------------------------------------------------- WOT-2026-055p
class TestSummarizeLoopGroups:
    """`summarize_loop_groups` agrupa commits de targets por loop_id compartido,
    PARA REPORTAR -- nunca decide acreditacion (ver docstring del modulo)."""

    def test_groups_by_shared_loop_id_in_order(self):
        shas = ["a", "b", "c"]
        per_commit_loop = {"a": "L800", "b": "L800", "c": "L900"}
        groups = cle.summarize_loop_groups(shas, per_commit_loop)
        assert groups == {"L800": ["a", "b"], "L900": ["c"]}

    def test_commits_without_loop_id_group_under_empty_key(self):
        shas = ["a", "b"]
        groups = cle.summarize_loop_groups(shas, {})
        assert groups == {"": ["a", "b"]}

    def test_mixed_grouped_and_ungrouped(self):
        shas = ["a", "b", "c"]
        per_commit_loop = {"a": "L800"}
        groups = cle.summarize_loop_groups(shas, per_commit_loop)
        assert groups == {"L800": ["a"], "": ["b", "c"]}

    def test_preserves_first_appearance_order_of_groups(self):
        shas = ["z", "a", "y"]
        per_commit_loop = {"z": "L900", "a": "L800", "y": "L900"}
        groups = cle.summarize_loop_groups(shas, per_commit_loop)
        assert list(groups.keys()) == ["L900", "L800"]
        assert groups["L900"] == ["z", "y"]

    def test_mutation_breaking_grouping_never_changes_accreditation_verdict(
        self, tmp_path: Path, monkeypatch
    ):
        """DoD (3): mutar el agrupador (reportar TODO bajo una sola clave falsa)
        no debe cambiar NINGUN veredicto ok/not-ok -- solo el TEXTO del reporte.
        Lo que decide acreditacion es `_loop_accreditation_failures`
        (prepush_check.py), que nunca llama a esta funcion."""
        shas = ["a", "b", "c"]
        per_commit_loop = {"a": "L800", "b": "L800", "c": "L900"}

        real = cle.summarize_loop_groups(shas, per_commit_loop)
        assert real != {"MUTATED": shas}  # el agrupador real no colapsa en 1

        def _mutated(_shas, _loop):
            return {"MUTATED": list(_shas)}

        monkeypatch.setattr(cle, "summarize_loop_groups", _mutated)
        mutated = cle.summarize_loop_groups(shas, per_commit_loop)
        assert mutated == {"MUTATED": shas}
        # la mutacion cambia el agrupamiento (rojo esperado para ESTA funcion)...
        assert mutated != real
        # ...pero `audit_commit`/`audit` (los que SI deciden) no importan ni
        # llaman a `summarize_loop_groups` en absoluto -- verificado por grep,
        # no por ejecucion (no hay fixture de scorecard aqui): la funcion de
        # acreditacion real vive en otro modulo y no referencia este nombre.
        import inspect

        audit_src = inspect.getsource(cle.audit)
        audit_commit_src = inspect.getsource(cle.audit_commit)
        assert "summarize_loop_groups" not in audit_src
        assert "summarize_loop_groups" not in audit_commit_src


# =========================================================== WOT-2026-129y
# Cobertura elegible declarada (agents.json::ensemble_registry.eligible_coverage),
# politica declared/strict, override --min-distinct sin bypass, exencion de
# 129d (DoD 5) y receipt reproducible (DoD 6). Nivel `audit()`: los fixtures
# inyectan config y parchean la lectura del scorecard; `audit_commit` queda
# intocado (los 82 tests previos siguen siendo la red de seguridad legacy).


def _cov_config(
    *,
    keys=("BA03", "BA07"),
    entry=None,
    statuses=None,
):
    """Config-minima con ensemble_registry: backend_keys + eligible_coverage.

    Before: claves BAxx; `entry` opcional sobreescribe la entrada por defecto
        (declared min 2, excluded BA05, exempt WOT-2026-129d).
    During: `statuses` permite marcar una clave como archivada (retirada).
    After: dict config apto para `audit(config=...)` sin tocar el agents.json real.
    """
    statuses = statuses or {}
    registry_keys = {
        k: {
            "backend": "kilo",
            "model": f"model-{k}",
            "backend_version": None,
            "status": statuses.get(k, "active"),
        }
        for k in (*keys, "BA05", "BA02", "BA15")
    }
    default_entry = {
        "backend_keys": list(keys),
        "min_distinct": 2,
        "policy": "declared",
        "excluded_backend_keys": ["BA05"],
        "exempt_tickets": ["WOT-2026-129d"],
    }
    return {
        "ensemble_registry": {
            "backend_keys": registry_keys,
            "eligible_coverage": {
                "MANAGER_REVIEW:repo_motor": (default_entry if entry is None else entry)
            },
        }
    }


def _audit_cov(monkeypatch, rows, emitted, **kwargs):
    """`cle.audit` con scorecard/emitted parcheados y config inyectada.

    Before: rows/emitted con la forma de `_ronda`/`_emitted`; kwargs llevan
        dtype/phase/authority/config/min_distinct segun el caso.
    During: parchea `_read_scorecard` y `read_emitted_nonces` (sin disco) y
        fija phase+delivery_authority por DEFECTO para activar cobertura.
    After: primer veredicto (un solo commit "abc").
    """
    monkeypatch.setattr(cle, "_read_scorecard", lambda root: (list(rows), "x"))
    monkeypatch.setattr(cle, "read_emitted_nonces", lambda root: list(emitted))
    kwargs.setdefault("phase", "MANAGER_REVIEW")
    kwargs.setdefault("delivery_authority", "repo_motor")
    verdicts = cle.audit(Path("dummy"), commit_shas=["abc"], **kwargs)
    return verdicts[0]


def _cov_rows(*backends, ticket="WOT-2026-129y", nonce="N1"):
    """Rondas (una por backend) con ticket+phase del flujo real."""
    return [
        {**_ronda(bk, nonce=nonce), "ticket": ticket, "phase": "MANAGER_REVIEW"}
        for bk in backends
    ]


# ------------------------------------------------------------------- CA1/CA2
def test_coverage_declared_two_keys_pass_same_instance(monkeypatch):
    """CA1: entrada declared min 2 + 2 claves elegibles en UNA instancia -> ok;
    receipt con min_aplicado=2, origen=eligible_coverage y policy_min=4 visible."""
    rows = _cov_rows("BA03", "BA07")
    emitted = [_emitted()]
    v = _audit_cov(
        monkeypatch,
        rows,
        emitted,
        deliverable_type="code",
        config=_cov_config(),
    )
    assert v["ok"] is True
    assert v["min_distinct"] == 2
    assert v["min_aplicado"] == 2
    assert v["min_origen"] == "eligible_coverage"
    assert v["policy_min"] == 4
    assert v["deliverable_type"] == "code"
    assert v["eligible_declared"] == ["BA03", "BA07"]
    assert v["eligible_effective"] == ["BA03", "BA07"]
    assert v["coverage_key"] == "MANAGER_REVIEW:repo_motor"
    receipt = cle._receipt_view(v)
    assert receipt["nonces"] == ["N1"]
    assert receipt["min_origen"] == "eligible_coverage"


def test_coverage_strict_policy_unreachable_fails_explicitly(monkeypatch):
    """CA2/DoD 2: policy=strict con 2 elegibles < policy 4 -> fallo EXPLICITO
    nombrando fase, tipo, cobertura, elegibles y minimo, aunque las rondas
    existan y pasen a nivel nonce."""
    entry = {
        "backend_keys": ["BA03", "BA07"],
        "min_distinct": 2,
        "policy": "strict",
    }
    rows = _cov_rows("BA03", "BA07")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        config=_cov_config(entry=entry),
    )
    assert v["ok"] is False
    err = v["coverage_error"]
    assert err.startswith("contrato_inalcanzable")
    for token in ("MANAGER_REVIEW", "code", "eligible_coverage", "4", "elegibles"):
        assert token in err, f"falta {token!r} en el fallo explicito: {err}"
    assert v["min_aplicado"] == 4
    assert v["min_origen"] == "policy"


# ------------------------------------------------------------------- CA3
def test_four_eligible_keys_in_one_instance_pass(monkeypatch):
    """CA3a: 4 claves elegibles en la MISMA instancia/nonce -> ok con distinct 4."""
    entry = {
        "backend_keys": ["BA03", "BA07", "BA02", "BA15"],
        "min_distinct": 4,
        "policy": "declared",
    }
    rows = _cov_rows("BA03", "BA07", "BA02", "BA15")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        config=_cov_config(entry=entry),
    )
    assert v["ok"] is True
    assert v["distinct_backends"] == ["BA02", "BA03", "BA07", "BA15"]
    assert v["min_aplicado"] == 4


def test_rounds_split_across_nonces_never_unioned(monkeypatch):
    """CA3b/DoD 2: 4 elegibles repartidos 2+2 en DOS nonces con min 4 -> cada
    instancia se evalua sola (ok=False), la union NO cuenta."""
    entry = {
        "backend_keys": ["BA03", "BA07", "BA02", "BA15"],
        "min_distinct": 4,
        "policy": "declared",
    }
    rows = [
        *_cov_rows("BA03", "BA07", nonce="N1"),
        *_cov_rows("BA02", "BA15", nonce="N2"),
    ]
    emitted = [_emitted(nonce="N1"), _emitted(nonce="N2")]
    v = _audit_cov(
        monkeypatch,
        rows,
        emitted,
        deliverable_type="code",
        config=_cov_config(entry=entry),
    )
    assert v["ok"] is False
    assert sorted(v["distinct_backends"]) == ["BA02", "BA03", "BA07", "BA15"]
    assert all(not e["ok"] for e in v["per_nonce"])
    assert [e["distinct"] for e in v["per_nonce"]] == [2, 2]


# ------------------------------------------------------------------- CA4
def test_excluded_key_round_not_counted(monkeypatch):
    """CA4a: ronda de una clave en excluded_backend_keys -> no cuenta; 1<2 -> rojo."""
    entry = {
        # D2: excluded_backend_keys debe ser disjunto de backend_keys. BA07
        # puede haber ejecutado una ronda, pero no forma parte de la cobertura.
        "backend_keys": ["BA03", "BA02"],
        "min_distinct": 2,
        "policy": "declared",
        "excluded_backend_keys": ["BA07"],
    }
    rows = _cov_rows("BA03", "BA07")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        config=_cov_config(entry=entry),
    )
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA03"]
    assert v["eligible_effective"] == ["BA02", "BA03"]
    reasons = {n["backend_key"]: n["reason"] for n in v["not_eligible_backends"]}
    assert reasons.get("BA07") == "excluded"
    receipt = cle._receipt_view(v)
    assert any(item["backend_key"] == "BA07" for item in receipt["no_contadas"]), (
        "el recibo debe nombrar la clave no contada (DoD 6)"
    )


def test_retired_key_not_counted(monkeypatch):
    """CA4b: clave declarada con registry status != active (retirada) -> no cuenta."""
    rows = _cov_rows("BA03", "BA07")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        config=_cov_config(statuses={"BA07": "archived"}),
    )
    assert v["ok"] is False
    assert v["eligible_effective"] == ["BA03"]
    removed = {r["backend_key"]: r["reason"] for r in v["declared_removed"]}
    assert removed.get("BA07") == "retired(status=archived)"


# ------------------------------------------------------------------- CA5
def test_exempt_ticket_129d_falls_back_to_strict_policy(monkeypatch):
    """CA5/DoD 5: filas con ticket WOT-2026-129d -> la cobertura NO aplica
    (exenta): min vuelve a policy 4 y 2 rondas quedan ok=False (sin
    retro-autorizacion de 129d)."""
    rows = _cov_rows("BA03", "BA07", ticket="WOT-2026-129d")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        config=_cov_config(),
    )
    assert v["exempt"] is True
    assert v["ok"] is False
    assert v["min_aplicado"] == 4
    assert v["min_origen"] == "policy"
    assert v["eligible_effective"] is None


# ------------------------------------------------------------------- CA6
def test_override_below_declared_min_rejected(monkeypatch):
    """CA6i/D5: --min-distinct por debajo del minimo declarado -> RECHAZADO
    (ok=False, reason override_below_declared_min); nunca invalida el derivado."""
    rows = _cov_rows("BA03", "BA07")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        min_distinct=1,
        config=_cov_config(),
    )
    assert v["ok"] is False
    assert v["coverage_error"].startswith("override_below_declared_min")
    assert v["min_aplicado"] == 2
    assert v["override"] == 1


def test_override_above_declared_applied_and_recorded(monkeypatch):
    """CA6ii/D5: override >= declarado se aplica (mas estricto) y queda en el
    recibo con min_origen=cli-override (no silencioso)."""
    rows = _cov_rows("BA03", "BA07")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        min_distinct=3,
        config=_cov_config(),
    )
    assert v["min_aplicado"] == 3
    assert v["min_origen"] == "cli-override"
    assert v["ok"] is False  # 2 claves reales < 3 exigidas por el override
    assert cle._receipt_view(v)["override"] == 3


def test_override_below_policy_without_coverage_flags_not_silent(monkeypatch):
    """CA6iii/D5: SIN cobertura, override por debajo de policy -> se aplica pero
    con override_below_policy=True en el receipt (el WARN de stderr es del CLI)."""
    rows = _cov_rows("BA03", "BA07")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        min_distinct=2,
        config={"ensemble_registry": {"backend_keys": {}}},
        phase=None,
        delivery_authority=None,
    )
    assert v["min_aplicado"] == 2
    assert v["min_origen"] == "cli-override"
    assert v["override_below_policy"] is True
    assert v["coverage_key"] is None


def test_invalid_coverage_declaration_fails_closed(monkeypatch):
    """D2: declaracion invalida (min_distinct fuera de rango) -> bloqueo
    explicito invalid_coverage, jamas degradacion silenciosa a legacy."""
    entry = {
        "backend_keys": ["BA03", "BA07"],
        "min_distinct": 99,
        "policy": "declared",
    }
    rows = _cov_rows("BA03", "BA07")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        config=_cov_config(entry=entry),
    )
    assert v["ok"] is False
    assert v["coverage_error"].startswith("invalid_coverage")


# ------------------------------------------------------------------- CA7/CA8
def test_legacy_path_without_phase_authority_unchanged(monkeypatch):
    """CA7: sin phase+authority el camino es legacy: policy 4 para code, sin
    filtro de elegibilidad, coverage_key None."""
    rows = _cov_rows("BA03", "BA07")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        config=_cov_config(),
        phase=None,
        delivery_authority=None,
    )
    assert v["ok"] is False
    assert v["min_distinct"] == 4
    assert v["min_origen"] == "policy"
    assert v["coverage_key"] is None
    assert v["distinct_backends"] == ["BA03", "BA07"]


def test_receipt_is_deterministic(monkeypatch):
    """CA8/DoD 6: dos corridas identicas -> mismo recibo (JSON estable)."""
    rows = _cov_rows("BA03", "BA07")
    emitted = [_emitted()]
    kwargs = {"deliverable_type": "code", "config": _cov_config()}
    first = cle._receipt_view(_audit_cov(monkeypatch, rows, emitted, **kwargs))
    second = cle._receipt_view(_audit_cov(monkeypatch, rows, emitted, **kwargs))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    for field in (
        "ticket",
        "commit_sha",
        "loop_id",
        "nonces",
        "distinct_backends",
        "eligible_declared",
        "eligible_effective",
        "no_contadas",
        "deliverable_type",
        "policy_min",
        "min_aplicado",
        "min_origen",
        "coverage_key",
        "override",
        "ok",
    ):
        assert field in first, f"el recibo DoD 6 carece de {field!r}"


def test_coverage_rejects_unknown_backend_key(monkeypatch):
    """D2: clave elegible que NO existe en ensemble_registry.backend_keys ->
    invalid_coverage (declaracion rota, fail-closed)."""
    entry = {
        "backend_keys": ["BA03", "BA999"],
        "min_distinct": 2,
        "policy": "declared",
    }
    rows = _cov_rows("BA03", "BA07")
    v = _audit_cov(
        monkeypatch,
        rows,
        [_emitted()],
        deliverable_type="code",
        config=_cov_config(entry=entry),
    )
    assert v["ok"] is False
    assert v["coverage_error"].startswith("invalid_coverage")
    assert "BA999" in v["coverage_error"]
