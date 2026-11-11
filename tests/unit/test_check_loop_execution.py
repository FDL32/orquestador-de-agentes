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


def test_model_family_prefers_exact_pair_and_normalizes_transport_prefix():
    assert cle.model_family("codex", "gpt-5.6-luna") == "codex"
    assert cle.model_family("opencode", "nan/deepseek-v4-flash") == "deepseek"


def test_model_family_unknown_and_ambiguous_are_fail_closed():
    with pytest.raises(cle.FamilyResolutionError):
        cle.model_family("nano", "desconocido")
    with pytest.raises(cle.FamilyResolutionError):
        cle.model_family(
            "unknown",
            "transport/shared-model",
            {
                ("a", "one/shared-model"): "alpha",
                ("b", "two/shared-model"): "beta",
            },
        )


def test_counted_lenses_for_commit_uses_real_scorecard_and_emitted_nonce(tmp_path):
    ensemble = tmp_path / ".agent" / "runtime" / "ensemble"
    ensemble.mkdir(parents=True)
    rows = [
        {
            **_ronda("BA10"),
            "backend": "nan_api",
            "model": "deepseek-v4-flash",
            "output_chars": 12,
            "evidencia": "ok",
        },
        {
            **_ronda("BA10", nonce="MISSING"),
            "backend": "nan_api",
            "model": "deepseek-v4-flash",
            "output_chars": 12,
            "evidencia": "ok",
        },
        {
            **_ronda("BA11"),
            "backend": "kilo",
            "model": "nan/gemma4",
            "output_chars": 0,
            "evidencia": "",
        },
    ]
    (ensemble / "scorecard.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (ensemble / "emitted_nonces.jsonl").write_text(
        json.dumps(_emitted()) + "\n", encoding="utf-8"
    )
    assert cle.counted_lenses_for_commit(tmp_path, "abc") == [
        {"backend": "nan_api", "model": "deepseek-v4-flash", "backend_key": "BA10"}
    ]


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


# ----------------------------------------------- WOT-2026-143a: deuda historica
_DEBT_SHA = "d" * 40
_DEBT_FICHA = "WOT-2026-143b"


def _audit_sha(monkeypatch, sha, rows=(), emitted=(), dtype="mixed"):
    """`cle.audit` de UN sha con scorecard/emitted parcheados (sin disco)."""
    monkeypatch.setattr(cle, "_read_scorecard", lambda root: (list(rows), "x"))
    monkeypatch.setattr(cle, "read_emitted_nonces", lambda root: list(emitted))
    return cle.audit(Path("dummy"), commit_shas=[sha], deliverable_type=dtype)[0]


def test_declared_debt_sha_under_minimum_is_waived_and_named(monkeypatch, capsys):
    """DoD (4): SHA40 declarado + 0 rondas -> ok, con la ficha NOMBRADA."""
    monkeypatch.setitem(cle.HISTORIC_LOOP_DEBT, _DEBT_SHA, _DEBT_FICHA)
    v = _audit_sha(monkeypatch, _DEBT_SHA)
    assert v["ok"] is True
    assert v["debt"] == _DEBT_FICHA
    assert v["debt_waived"] is True
    assert cle._receipt_view(v)["debt"] == _DEBT_FICHA
    cle._print_verdict(v)
    out = capsys.readouterr().out
    assert "DEUDA HISTORICA" in out
    assert _DEBT_FICHA in out


def test_control_positive_same_sha_not_declared_fails(monkeypatch):
    """Control positivo: SIN la entrada, el mismo sha bajo el minimo FALLA."""
    assert _DEBT_SHA not in cle.HISTORIC_LOOP_DEBT
    v = _audit_sha(monkeypatch, _DEBT_SHA)
    assert v["ok"] is False
    assert v["debt"] is None
    assert v["debt_waived"] is False


def test_undeclared_sha_sharing_the_prefix_of_a_declared_one_still_fails(
    monkeypatch,
):
    """DoD (4)/M3: la deuda es por IGUALDAD de SHA40, no por prefijo ni patron."""
    monkeypatch.setitem(cle.HISTORIC_LOOP_DEBT, _DEBT_SHA, _DEBT_FICHA)
    sibling = "d" * 39 + "e"
    assert sibling.startswith(_DEBT_SHA[:39])
    v = _audit_sha(monkeypatch, sibling)
    assert v["ok"] is False
    assert v["debt"] is None
    # un sha abreviado del declarado tampoco casa
    short = _audit_sha(monkeypatch, _DEBT_SHA[:12])
    assert short["ok"] is False


def test_debt_never_changes_a_passing_verdict(monkeypatch):
    """La deuda solo levanta FALLOS: un sha declarado que YA pasa no se marca."""
    monkeypatch.setitem(cle.HISTORIC_LOOP_DEBT, _DEBT_SHA, _DEBT_FICHA)
    rows = [
        _ronda(bk, nonce="N1", commit=_DEBT_SHA)
        for bk in ("BA03", "BA07", "BA05", "BA02")
    ]
    v = _audit_sha(monkeypatch, _DEBT_SHA, rows, [_emitted(commit=_DEBT_SHA)])
    assert v["ok"] is True
    assert v["debt_waived"] is False


def test_historic_debt_table_is_exact_sha40_with_declared_exit_ficha():
    """El contenido VIGENTE: 15 SHA40 en minuscula, todos con la ficha de salida,
    sin duplicados y sin los 4 tips que ya pasan su bucle."""
    assert len(cle.HISTORIC_LOOP_DEBT) == 15
    for sha, ficha in cle.HISTORIC_LOOP_DEBT.items():
        assert len(sha) == 40 and sha == sha.lower(), sha
        int(sha, 16)
        assert ficha == "WOT-2026-143b", (sha, ficha)
    passing_tips = {
        "1236f3d72a1ac56c2550480dd1f7b0eaa66f148e",  # 136h
        "8387e9dbb515c9f72088d8ee7a505e8b275eafd7",  # 136l
        "0112ca887f560f98a294bf24fc81eeb3af80d5a4",  # 136m
        "6974d86c6d0aeedf2e32f3f99f1b1e3777c1190d",  # 142a
    }
    assert not passing_tips & set(cle.HISTORIC_LOOP_DEBT)


# --------------------------------------------------------------------------- #
# WOT-2026-152s-1: el timeout del watchdog es DISTINGUIBLE de muda y transporte
# --------------------------------------------------------------------------- #


def _timeout_round(backend, **kw):
    """Ronda con la forma EXACTA que escribe `_record_watchdog_timeout`:
    `_record_round(reply="")` => outcome no-aportacion, 0 chars, y el
    `failure_mode` propio `timeout: ...`."""
    row = _muda(backend, **kw)
    row["failure_mode"] = (
        "timeout: watchdog de 600s vencido sin respuesta de la lente; "
        "hijo (pid 4242) matado, confirmado por poll(); descendientes no verificados"
    )
    return row


def test_diagnose_silence_distinguishes_timeout_from_muda_and_transport():
    """Las TRES clases de silencio dan tres diagnosticos distintos. Mutacion M5
    (quitar la rama `timeout:`) -> el timeout cae en el texto generico de
    'respuesta descartada por la adjudicacion' y deja de nombrarse."""
    timeout = cle.diagnose_silence(_timeout_round("BA07"))
    muda = cle.diagnose_silence(_muda("BA07"))
    transporte_row = _muda("BA07")
    transporte_row["failure_mode"] = "transport_failed: rc=1; unknown"
    transporte = cle.diagnose_silence(transporte_row)

    assert len({timeout, muda, transporte}) == 3
    assert "NO respondio dentro del limite" in timeout
    assert "VACIA" not in timeout and "adjudicacion" not in timeout
    assert "VACIA" in muda
    assert "adjudicacion" in transporte
    assert "NO respondio dentro del limite" not in muda + transporte
    assert "pid 4242" in timeout, "el detalle del failure_mode debe conservarse"


def test_timeout_round_is_silent_and_reported_with_its_own_label(capsys):
    """Un `timeout:` NO cuenta como lente que aporta (no es sustantiva) y sale
    nombrado como TIMEOUT -no como MUDA- en el informe del gate."""
    emitted = [_emitted()]
    sc = [_ronda("BA10"), _timeout_round("BA07")]

    assert cle.is_substantive(_timeout_round("BA07")) is False
    v = cle.audit_commit(sc, emitted, commit_sha="abc", min_distinct=2)

    assert [s["backend_key"] for s in v["silent_rounds"]] == ["BA07"]
    assert v["silent_rounds"][0]["failure_mode"].startswith(cle.TIMEOUT_FAILURE_PREFIX)
    assert v["ok"] is False, "1 lente + 1 timeout no alcanza N=2"
    cle._print_verdict(v)
    out = capsys.readouterr().out
    assert "TIMEOUT BA07" in out
    assert "MUDA BA07" not in out


def test_muda_round_keeps_the_muda_label(capsys):
    """CONTROL: una ronda muda SIN `timeout:` sigue saliendo como MUDA."""
    emitted = [_emitted()]
    v = cle.audit_commit(
        [_ronda("BA10"), _muda("BA11")], emitted, commit_sha="abc", min_distinct=2
    )
    cle._print_verdict(v)
    out = capsys.readouterr().out
    assert "MUDA BA11" in out
    assert "TIMEOUT BA11" not in out


def test_timeout_prefix_in_the_middle_of_a_transport_failure_is_not_a_timeout(capsys):
    """Solo el PREFIJO `timeout:` marca el timeout del watchdog. Un fallo de
    TRANSPORTE cuyo texto (escrito por el proveedor) contiene `timeout:` en
    MEDIO no es un timeout del watchdog: ni se diagnostica ni se etiqueta como
    tal. Mutaciones M19 (`in` en vez de `startswith` en diagnose_silence) y M19b
    (lo mismo en la etiqueta del informe) -> rojo."""
    row = _muda("BA11")
    row["failure_mode"] = "transport_failed: rc=1; el proveedor dijo timeout: reintenta"

    diagnosis = cle.diagnose_silence(row)

    assert "NO respondio dentro del limite" not in diagnosis
    assert "adjudicacion" in diagnosis
    v = cle.audit_commit(
        [_ronda("BA10"), row], [_emitted()], commit_sha="abc", min_distinct=2
    )
    cle._print_verdict(v)
    out = capsys.readouterr().out
    assert "MUDA BA11" in out
    assert "TIMEOUT BA11" not in out


def test_timeout_diagnosis_does_not_assert_the_kill_it_cannot_know(capsys):
    """El diagnostico de un `timeout:` NO afirma por su cuenta que el arbol fue
    matado: la fila puede decir `kill NO confirmado; ... puede seguir vivo` y el
    informe no puede decir lo contrario. La confirmacion viaja en el `Detalle`
    (copiado del failure_mode). Mutacion M22 (reponer 'fue matado' fijo) -> rojo."""
    sin_confirmar = _timeout_round("BA07")
    sin_confirmar["failure_mode"] = (
        "timeout: watchdog de 600s vencido sin respuesta de la lente; "
        "kill NO confirmado; el hijo (pid 4242) puede seguir vivo"
    )
    diagnosis = cle.diagnose_silence(sin_confirmar)
    assert "fue matado" not in diagnosis
    assert "kill NO confirmado" in diagnosis, "el Detalle debe conservar la salvedad"
    assert "NO respondio dentro del limite" in diagnosis

    v = cle.audit_commit(
        [_ronda("BA10"), sin_confirmar], [_emitted()], commit_sha="abc", min_distinct=2
    )
    cle._print_verdict(v)
    out = capsys.readouterr().out
    assert "TIMEOUT BA07" in out
    assert "fue matado" not in out
    assert "kill NO confirmado" in out


def test_timeout_diagnosis_shows_a_confirmed_kill_only_through_the_row_detail():
    """CONTROL POSITIVO: con una fila `timeout: ... matado` el `Detalle` sigue
    mostrando 'matado' (viene de la fila, que SI lo confirmo), pero el texto fijo
    del diagnostico no lo afirma."""
    confirmada = _timeout_round("BA07")  # failure_mode: "... (pid 4242) matado"
    diagnosis = cle.diagnose_silence(confirmada)

    assert "(pid 4242) matado" in diagnosis
    assert "fue matado" not in diagnosis
    assert "kill NO confirmado" not in diagnosis


# =========================================================== WOT-2026-152t
# Politica de RESERVA de lentes (H131): cuando una lente se cuelga N veces en una
# instancia, la siguiente reserva declarada ocupa su sitio, con registro derivado
# (veredicto + linea + recibo) y fail-closed sin reserva libre. Fixtures con filas
# del formato REAL del scorecard (`SCORECARD_FIELDS`, los `failure_mode` que
# escriben el watchdog de 152s-1 y el timeout interno de 900 s). Snapshot fechado
# 2026-11-01: N=2 es una propuesta con n pequeno, no una tasa medida.

_RS_WATCHDOG_MODE = (
    "timeout: watchdog de 1500s vencido sin respuesta de la lente; "
    "arbol de procesos del hijo (pid 4242) matado"
)
# Forma del timeout INTERNO tal como la dejo el scorecard real (30 filas el
# 2026-11-01; recortada tras la primera frase).
_RS_INTERNAL_MODE = (
    "unexpected: RuntimeError: backend CLI sin respuesta tras 900s; arbol de "
    "procesos matado. CAUSA NO DETERMINADA -- comprueba en este orden"
)
# COPIA LITERAL de la entrada real de agents.json (2026-11-01): fija la
# aditividad sin leer el agents.json vivo.
_RS_REAL_ENTRY = {
    "backend_keys": ["BA03", "BA07", "BA254"],
    "min_distinct": 2,
    "policy": "declared",
    "excluded_backend_keys": ["BA05"],
    "exempt_tickets": ["WOT-2026-129d"],
    "note": "WOT-2026-129y: cobertura elegible copiada de la verdad del roster del vuelo (session_types.implantacion.lenses.MANAGER_REVIEW=[BA03] + revisor_repo_motor_interino=BA07). BA05 excluida por WOT-2026-129r (no puede revisar repo_motor via loop-round). WOT-2026-129d exento: esta entrada NO re-adjudica su evidencia (DoD 5). 2026-11-01 CO-17 (orden del usuario, H130/H131): BA254 (Codex gpt-6.1-sol, challenger_codex_sol_cli) se anade como TERCERA elegible por sustitucion de facto de BA07, que da timeouts/colgados repetidos; min_distinct sigue en 2, asi que BA07 pasa a ser opcional. Si el roster del vuelo declara nuevas claves para esta fase, este campo se actualiza por ticket (D1 del work_plan: fuente unica versionada; la deriva es fail-safe).",
}


# Literales CAPTURADOS de la version 87f79a85 (pre-152t) con la entrada real
# copiada arriba: veredicto, recibo y salida impresa de dos escenarios.
_LEGACY_GOLDEN = {
    "hung_one_below_min": {
        "printed": "[loop-exec] FAIL abc: 1/2 lentes distintas ['BA03']\n"
        "[loop-exec]   TIMEOUT BA07: la lente NO respondio dentro "
        "del limite del watchdog de la invocacion; se intento matar "
        "su arbol de procesos y la fila dice si el kill se "
        "confirmo: no es una respuesta vacia ni un fallo de "
        "transporte. Detalle: timeout: watchdog de 1500s vencido "
        "sin respuesta de la lente; arbol de procesos del hijo (pid "
        "4242) matado (output_chars=0)\n"
        "[loop-exec]   NONCE N1...: 1/2 lentes distintas ['BA03'] "
        "(esa corrida no llega a N)\n",
        "receipt": {
            "commit_sha": "abc",
            "coverage_key": "MANAGER_REVIEW:repo_motor",
            "debt": None,
            "deliverable_type": "code",
            "distinct_backends": ["BA03"],
            "eligible_declared": ["BA03", "BA07", "BA254"],
            "eligible_effective": ["BA03", "BA07", "BA254"],
            "exempt": False,
            "loop_id": None,
            "min_aplicado": 2,
            "min_origen": "eligible_coverage",
            "no_contadas": [],
            "nonces": ["N1"],
            "ok": False,
            "override": None,
            "policy_min": 4,
            "ticket": ["WOT-2026-152t"],
        },
        "verdict": {
            "commit_sha": "abc",
            "coverage_key": "MANAGER_REVIEW:repo_motor",
            "coverage_source": "agents.json::ensemble_registry.eligible_coverage",
            "debt": None,
            "debt_waived": False,
            "declared_removed": [],
            "deliverable_type": "code",
            "delivery_authority": "repo_motor",
            "distinct_backends": ["BA03"],
            "eligible_declared": ["BA03", "BA07", "BA254"],
            "eligible_effective": ["BA03", "BA07", "BA254"],
            "exempt": False,
            "fabricated_rounds": [],
            "loop_id": None,
            "min_aplicado": 2,
            "min_distinct": 2,
            "min_origen": "eligible_coverage",
            "not_eligible_backends": [],
            "ok": False,
            "orphan_nonces": [],
            "override": None,
            "override_below_policy": False,
            "per_nonce": [
                {
                    "backends": ["BA03"],
                    "distinct": 1,
                    "ineligible": [],
                    "nonce": "N1",
                    "ok": False,
                }
            ],
            "phase": "MANAGER_REVIEW",
            "policy_min": 4,
            "silent_rounds": [
                {
                    "backend_key": "BA07",
                    "diagnosis": "la lente NO respondio "
                    "dentro del limite del "
                    "watchdog de la "
                    "invocacion; se intento "
                    "matar su arbol de "
                    "procesos y la fila dice "
                    "si el kill se confirmo: "
                    "no es una respuesta vacia "
                    "ni un fallo de "
                    "transporte. Detalle: "
                    "timeout: watchdog de "
                    "1500s vencido sin "
                    "respuesta de la lente; "
                    "arbol de procesos del "
                    "hijo (pid 4242) matado",
                    "failure_mode": "timeout: watchdog de "
                    "1500s vencido sin "
                    "respuesta de la lente; "
                    "arbol de procesos del "
                    "hijo (pid 4242) matado",
                    "outcome": "no-aportacion",
                    "output_chars": 0,
                }
            ],
            "tickets": ["WOT-2026-152t"],
        },
    },
    "hung_two_and_reserve_answers": {
        "printed": "[loop-exec] OK abc: 2/2 lentes distintas "
        "['BA03', 'BA254']\n"
        "[loop-exec]   TIMEOUT BA07: la lente NO "
        "respondio dentro del limite del watchdog de la "
        "invocacion; se intento matar su arbol de "
        "procesos y la fila dice si el kill se confirmo: "
        "no es una respuesta vacia ni un fallo de "
        "transporte. Detalle: timeout: watchdog de 1500s "
        "vencido sin respuesta de la lente; arbol de "
        "procesos del hijo (pid 4242) matado "
        "(output_chars=0)\n"
        "[loop-exec]   TIMEOUT BA07: la lente NO "
        "respondio dentro del limite del watchdog de la "
        "invocacion; se intento matar su arbol de "
        "procesos y la fila dice si el kill se confirmo: "
        "no es una respuesta vacia ni un fallo de "
        "transporte. Detalle: timeout: watchdog de 1500s "
        "vencido sin respuesta de la lente; arbol de "
        "procesos del hijo (pid 4242) matado "
        "(output_chars=0)\n",
        "receipt": {
            "commit_sha": "abc",
            "coverage_key": "MANAGER_REVIEW:repo_motor",
            "debt": None,
            "deliverable_type": "code",
            "distinct_backends": ["BA03", "BA254"],
            "eligible_declared": ["BA03", "BA07", "BA254"],
            "eligible_effective": ["BA03", "BA07", "BA254"],
            "exempt": False,
            "loop_id": None,
            "min_aplicado": 2,
            "min_origen": "eligible_coverage",
            "no_contadas": [],
            "nonces": ["N1"],
            "ok": True,
            "override": None,
            "policy_min": 4,
            "ticket": ["WOT-2026-152t"],
        },
        "verdict": {
            "commit_sha": "abc",
            "coverage_key": "MANAGER_REVIEW:repo_motor",
            "coverage_source": "agents.json::ensemble_registry.eligible_coverage",
            "debt": None,
            "debt_waived": False,
            "declared_removed": [],
            "deliverable_type": "code",
            "delivery_authority": "repo_motor",
            "distinct_backends": ["BA03", "BA254"],
            "eligible_declared": ["BA03", "BA07", "BA254"],
            "eligible_effective": ["BA03", "BA07", "BA254"],
            "exempt": False,
            "fabricated_rounds": [],
            "loop_id": None,
            "min_aplicado": 2,
            "min_distinct": 2,
            "min_origen": "eligible_coverage",
            "not_eligible_backends": [],
            "ok": True,
            "orphan_nonces": [],
            "override": None,
            "override_below_policy": False,
            "per_nonce": [
                {
                    "backends": ["BA03", "BA254"],
                    "distinct": 2,
                    "ineligible": [],
                    "nonce": "N1",
                    "ok": True,
                }
            ],
            "phase": "MANAGER_REVIEW",
            "policy_min": 4,
            "silent_rounds": [
                {
                    "backend_key": "BA07",
                    "diagnosis": "la lente NO "
                    "respondio "
                    "dentro del "
                    "limite del "
                    "watchdog de la "
                    "invocacion; se "
                    "intento matar "
                    "su arbol de "
                    "procesos y la "
                    "fila dice si el "
                    "kill se "
                    "confirmo: no es "
                    "una respuesta "
                    "vacia ni un "
                    "fallo de "
                    "transporte. "
                    "Detalle: "
                    "timeout: "
                    "watchdog de "
                    "1500s vencido "
                    "sin respuesta "
                    "de la lente; "
                    "arbol de "
                    "procesos del "
                    "hijo (pid 4242) "
                    "matado",
                    "failure_mode": "timeout: "
                    "watchdog de "
                    "1500s "
                    "vencido sin "
                    "respuesta de "
                    "la lente; "
                    "arbol de "
                    "procesos del "
                    "hijo (pid "
                    "4242) matado",
                    "outcome": "no-aportacion",
                    "output_chars": 0,
                },
                {
                    "backend_key": "BA07",
                    "diagnosis": "la lente NO "
                    "respondio "
                    "dentro del "
                    "limite del "
                    "watchdog de la "
                    "invocacion; se "
                    "intento matar "
                    "su arbol de "
                    "procesos y la "
                    "fila dice si el "
                    "kill se "
                    "confirmo: no es "
                    "una respuesta "
                    "vacia ni un "
                    "fallo de "
                    "transporte. "
                    "Detalle: "
                    "timeout: "
                    "watchdog de "
                    "1500s vencido "
                    "sin respuesta "
                    "de la lente; "
                    "arbol de "
                    "procesos del "
                    "hijo (pid 4242) "
                    "matado",
                    "failure_mode": "timeout: "
                    "watchdog de "
                    "1500s "
                    "vencido sin "
                    "respuesta de "
                    "la lente; "
                    "arbol de "
                    "procesos del "
                    "hijo (pid "
                    "4242) matado",
                    "outcome": "no-aportacion",
                    "output_chars": 0,
                },
            ],
            "tickets": ["WOT-2026-152t"],
        },
    },
}


def _rs_row(backend, *, hang=None, answered=True, nonce="N1", sec=5, commit="abc"):
    """Fila `ronda` con TODOS los campos de `SCORECARD_FIELDS` (formato real).

    Before: `hang` es el `failure_mode` de colgado o None; `answered` decide si la
        ronda aporto contenido.
    After: dict listo para `audit()`; ts posterior a la emision del nonce.
    """
    row = {k: None for k in ed.SCORECARD_FIELDS}
    row.update(
        ts=f"2026-07-24T10:05:{sec:02d}+00:00",
        event="ronda",
        ticket="WOT-2026-152t",
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


def _rs_entry(**over):
    entry = {
        "backend_keys": ["BA03", "BA07"],
        "min_distinct": 2,
        "policy": "declared",
        "excluded_backend_keys": ["BA05"],
        "reserve_backend_keys": ["BA254"],
        "reserve_after_timeouts": 2,
    }
    entry.update(over)
    return entry


def _rs_audit(monkeypatch, rows, *, entry=None, statuses=None, emitted=None, keys=None):
    config = _cov_config(
        keys=keys or ("BA03", "BA07", "BA254", "BA11"),
        entry=entry or _rs_entry(),
        statuses=statuses,
    )
    return _audit_cov(
        monkeypatch,
        rows,
        emitted or [_emitted()],
        deliverable_type="code",
        config=config,
    )


def _rs_not_eligible(v):
    return {x["backend_key"]: x["reason"] for x in v["not_eligible_backends"]}


def test_hung_lens_is_replaced_by_reserve_and_the_swap_is_recorded(monkeypatch):
    """ROJO->VERDE del Paso 0: BA07 se cuelga N=2 veces, BA254 (reserva) responde.
    Antes el campo de reserva se ignoraba y el veredicto era FAIL sin registro."""
    rows = [_rs_row("BA03"), *_rs_hang("BA07"), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows)
    assert v["ok"] is True
    assert v["distinct_backends"] == ["BA03", "BA254"]
    assert v["not_eligible_backends"] == []
    assert v["reserve_policy"] == {
        "reserve_backend_keys": ["BA254"],
        "reserve_after_timeouts": 2,
        "window": "nonce",
    }
    assert v["reserve_substitutions"] == [
        {
            "nonce": "N1",
            "replaced_backend_key": "BA07",
            "reserve_backend_key": "BA254",
            "timeouts": 2,
            "n": 2,
            "window": "nonce",
            "evidence_ts": [
                "2026-07-24T10:05:10+00:00",
                "2026-07-24T10:05:11+00:00",
            ],
        }
    ]
    assert v["reserve_exhausted"] == []


def test_reserve_does_not_count_below_n_timeouts(monkeypatch):
    """N-1 timeouts NO activan la reserva: la ronda de BA254 no cuenta y el
    bucle no llega a N (una lente lenta no es una lente sustituida)."""
    rows = [_rs_row("BA03"), *_rs_hang("BA07", times=1), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows)
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA03"]
    assert _rs_not_eligible(v) == {"BA254": "reserve_not_activated"}
    assert v["reserve_substitutions"] == []
    assert v["reserve_exhausted"] == []


def test_n_is_declared_per_entry_not_hardcoded(monkeypatch):
    """N=3: dos timeouts no bastan; tres si. Mata un N cableado a 2."""
    rows = [_rs_row("BA03"), *_rs_hang("BA07", times=2), _rs_row("BA254", sec=30)]
    entry = _rs_entry(reserve_after_timeouts=3)
    assert _rs_audit(monkeypatch, rows, entry=entry)["ok"] is False
    rows = [_rs_row("BA03"), *_rs_hang("BA07", times=3), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows, entry=entry)
    assert v["ok"] is True
    assert v["reserve_substitutions"][0]["timeouts"] == 3


def test_window_is_the_instance_not_the_commit(monkeypatch):
    """Un timeout en cada de DOS instancias (nonces) NO suma N=2: la ventana es
    la instancia. Mata contar por commit."""
    emitted = [_emitted("N1"), _emitted("N2", ts="2026-07-24T10:01:00+00:00")]
    rows = [
        _rs_row("BA03", nonce="N1"),
        *_rs_hang("BA07", times=1, nonce="N1"),
        *_rs_hang("BA07", times=1, nonce="N2"),
        _rs_row("BA254", nonce="N1", sec=30),
    ]
    v = _rs_audit(monkeypatch, rows, emitted=emitted)
    assert v["ok"] is False
    assert v["reserve_substitutions"] == []


def test_internal_900s_timeout_form_counts_too(monkeypatch):
    """La forma que HOY deja el scorecard (timeout interno) activa la reserva."""
    rows = [
        _rs_row("BA03"),
        *_rs_hang("BA07", mode=_RS_INTERNAL_MODE),
        _rs_row("BA254", sec=30),
    ]
    v = _rs_audit(monkeypatch, rows)
    assert v["ok"] is True
    assert v["reserve_substitutions"][0]["replaced_backend_key"] == "BA07"


def test_fabricated_timeouts_do_not_activate_a_reserve(monkeypatch):
    """Dos filas `timeout:` con un nonce NO emitido no son evidencia: no activan."""
    rows = [
        _rs_row("BA03"),
        *_rs_hang("BA07", nonce="NX"),
        _rs_row("BA254", sec=30),
    ]
    v = _rs_audit(monkeypatch, rows)
    assert v["ok"] is False
    assert v["reserve_substitutions"] == []
    assert _rs_not_eligible(v) == {"BA254": "reserve_not_activated"}


def test_one_hung_lens_activates_only_one_reserve_in_order(monkeypatch):
    """Dos reservas, UNA colgada: entra solo la primera declarada; la segunda
    queda `reserve_not_activated`. Mata activar todas a la vez."""
    entry = _rs_entry(reserve_backend_keys=["BA254", "BA11"])
    rows = [
        _rs_row("BA03"),
        *_rs_hang("BA07"),
        _rs_row("BA254", sec=30),
        _rs_row("BA11", sec=31),
    ]
    v = _rs_audit(monkeypatch, rows, entry=entry)
    assert v["ok"] is True
    assert v["distinct_backends"] == ["BA03", "BA254"]
    assert _rs_not_eligible(v) == {"BA11": "reserve_not_activated"}
    assert [s["reserve_backend_key"] for s in v["reserve_substitutions"]] == ["BA254"]


def test_a_hung_reserve_pulls_the_next_one(monkeypatch):
    """La reserva activada tambien puede colgarse: pide la siguiente (cadena)."""
    entry = _rs_entry(reserve_backend_keys=["BA254", "BA11"])
    rows = [
        _rs_row("BA03"),
        *_rs_hang("BA07"),
        *_rs_hang("BA254", start=20),
        _rs_row("BA11", sec=40),
    ]
    v = _rs_audit(monkeypatch, rows, entry=entry)
    assert v["ok"] is True
    assert [
        (s["replaced_backend_key"], s["reserve_backend_key"])
        for s in v["reserve_substitutions"]
    ] == [("BA07", "BA254"), ("BA254", "BA11")]
    assert v["reserve_exhausted"] == []


def test_swap_is_registered_in_printed_line_and_receipt(monkeypatch, capsys):
    """Registro DERIVADO: veredicto + linea impresa + recibo, y el recibo es
    determinista (dos corridas, mismo JSON)."""
    rows = [_rs_row("BA03"), *_rs_hang("BA07"), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows)
    cle._print_verdict(v)
    out = capsys.readouterr().out
    assert "RESERVA BA07 -> BA254: 2 timeouts (N=2, ventana=nonce" in out
    receipt = cle._receipt_view(v)
    assert receipt["reserve_substitutions"] == v["reserve_substitutions"]
    assert receipt["reserve_policy"]["reserve_after_timeouts"] == 2
    assert receipt["reserve_exhausted"] == []
    again = cle._receipt_view(_rs_audit(monkeypatch, rows))
    assert json.dumps(receipt, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_no_reserve_left_is_named_and_does_not_cover(monkeypatch, capsys):
    """FAIL-CLOSED: la reserva esta retirada, BA07 colgado -> NO cubierto,
    `reserve_exhausted` lo nombra y la ronda de la reserva retirada no cuenta."""
    rows = [_rs_row("BA03"), *_rs_hang("BA07"), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows, statuses={"BA254": "deprecated"})
    assert v["ok"] is False
    assert v["reserve_substitutions"] == []
    assert [(x["backend_key"], x["timeouts"]) for x in v["reserve_exhausted"]] == [
        ("BA07", 2)
    ]
    assert _rs_not_eligible(v) == {"BA254": "retired(status=deprecated)"}
    cle._print_verdict(v)
    assert "RESERVA-AGOTADA BA07" in capsys.readouterr().out


def test_exhausted_reserve_does_not_invent_a_failure_when_n_is_reached(monkeypatch):
    """Q6: colgar no debe BLOQUEAR (es el punto de H131). Con tres primarias,
    una colgada sin reserva y las otras dos respondiendo, `ok` sigue True y el
    agotamiento queda NOMBRADO."""
    entry = _rs_entry(backend_keys=["BA03", "BA07", "BA11"])
    rows = [_rs_row("BA03"), _rs_row("BA11", sec=6), *_rs_hang("BA07")]
    v = _rs_audit(monkeypatch, rows, entry=entry, statuses={"BA254": "deprecated"})
    assert v["ok"] is True
    assert [x["backend_key"] for x in v["reserve_exhausted"]] == ["BA07"]


def test_hung_lens_that_later_answers_still_counts(monkeypatch):
    """La sustitucion solo AMPLIA: BA03 se cuelga 2 veces y a la 3a responde
    (caso real 140a). Sigue contando junto a BA07 aunque BA254 no corriera."""
    rows = [
        *_rs_hang("BA03"),
        _rs_row("BA03", sec=40),
        _rs_row("BA07", sec=41),
    ]
    v = _rs_audit(monkeypatch, rows)
    assert v["ok"] is True
    assert v["distinct_backends"] == ["BA03", "BA07"]
    assert [s["replaced_backend_key"] for s in v["reserve_substitutions"]] == ["BA03"]


def test_retired_reserve_never_counts_even_if_a_primary_hangs(monkeypatch):
    rows = [_rs_row("BA03"), *_rs_hang("BA07"), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows, statuses={"BA254": "archived"})
    assert v["ok"] is False
    assert "BA254" not in v["distinct_backends"]


def test_an_excluded_lens_hanging_does_not_activate_a_reserve(monkeypatch):
    """BA05 (excluida) colgada NO es una primaria: no activa reserva."""
    rows = [_rs_row("BA03"), *_rs_hang("BA05"), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows)
    assert v["reserve_substitutions"] == []
    assert v["ok"] is False


@pytest.mark.parametrize(
    "patch",
    [
        {"reserve_after_timeouts": None},
        {"reserve_after_timeouts": 0},
        {"reserve_after_timeouts": True},
        {"reserve_after_timeouts": "2"},
        {"reserve_backend_keys": None},
        {"reserve_backend_keys": []},
        {"reserve_backend_keys": ["BA254", "BA254"]},
        {"reserve_backend_keys": ["BA254", ""]},
        {"reserve_backend_keys": ["BA999"]},
        {"reserve_backend_keys": ["BA03"]},
        {"reserve_backend_keys": ["BA05"]},
    ],
)
def test_invalid_reserve_declaration_fails_closed(monkeypatch, patch):
    """Una reserva mal declarada BLOQUEA con `invalid_coverage`, nunca se ignora
    ni se degrada a la lista estatica. Aqui None = clave AUSENTE (la otra queda
    presente); el valor null PRESENTE se prueba aparte."""
    entry = _rs_entry(**patch)
    entry = {k: v for k, v in entry.items() if v is not None}
    rows = [_rs_row("BA03"), _rs_row("BA07", sec=6)]
    v = _rs_audit(monkeypatch, rows, entry=entry)
    assert v["ok"] is False
    assert v["coverage_error"].startswith("invalid_coverage")


def test_live_agents_json_coverage_validates_with_the_new_validator():
    """El agents.json VIVO sigue siendo valido con el validador nuevo (los campos
    de reserva son opcionales). Separado de la copia literal de arriba."""
    config = ed.load_motor_config()
    coverage = config["ensemble_registry"]["eligible_coverage"]
    assert coverage, "agents.json sin eligible_coverage"
    for key, entry in coverage.items():
        assert cle.validate_coverage_entry(entry, config) is None, key


def test_exempt_ticket_never_gets_reserve_fields(monkeypatch):
    """Un ticket EXENTO se evalua con la politica estricta legacy: sin filtro de
    elegibilidad, y por tanto sin registro de reserva."""
    entry = _rs_entry(exempt_tickets=["WOT-2026-152t"])
    rows = [_rs_row("BA03"), *_rs_hang("BA07"), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows, entry=entry)
    assert v["exempt"] is True
    assert "reserve_substitutions" not in v


def test_is_hang_row_counts_only_the_two_timeout_forms():
    assert cle.is_hang_row(_rs_row("BA07", hang=_RS_WATCHDOG_MODE, answered=False))
    assert cle.is_hang_row(_rs_row("BA07", hang=_RS_INTERNAL_MODE, answered=False))
    for mode in (
        None,
        "",
        "transport_failed: TransportError",
        "privacy_preflight_blocked: privacy_preflight BLOQUEA el envio",
        "missing-nonce",
    ):
        assert not cle.is_hang_row(_rs_row("BA07", hang=mode, answered=False)), mode


def test_timeout_markers_match_the_literals_the_emitters_write():
    """Contrato con el EMISOR (lectura del texto fuente, sin importar su valor):
    si `ensemble_dispatch.py` cambia el mensaje del timeout interno o el prefijo
    del watchdog, la cuenta de colgados dejaria de ver las filas reales."""
    source = (SCRIPTS_DIR / "ensemble_dispatch.py").read_text(encoding="utf-8")
    assert f'f"{cle.INTERNAL_TIMEOUT_MARKER} {{timeout}}s' in source
    assert f'f"{cle.TIMEOUT_FAILURE_PREFIX} watchdog de' in source


def test_timeouts_logged_before_the_nonce_was_issued_do_not_activate(monkeypatch):
    """Una fila de colgado ANTERIOR a la emision del nonce no es una ronda de esa
    instancia (sin ceremonia previa): no activa la reserva, aunque BA03 y BA254
    si sean validas en el mismo nonce."""
    emitted = [_emitted(ts="2026-07-24T10:05:20+00:00")]
    rows = [
        *_rs_hang("BA07", start=10),
        _rs_row("BA03", sec=25),
        _rs_row("BA254", sec=30),
    ]
    v = _rs_audit(monkeypatch, rows, emitted=emitted)
    assert v["ok"] is False
    assert v["reserve_substitutions"] == []
    assert _rs_not_eligible(v) == {"BA254": "reserve_not_activated"}


# ---------------------------------------------------------------- ronda 2 (152t)
def _rs_pairs(v):
    return [
        (s["replaced_backend_key"], s["reserve_backend_key"])
        for s in v["reserve_substitutions"]
    ]


def test_reserve_hanging_earlier_than_the_primary_keeps_the_causal_pairing(
    monkeypatch,
):
    """MAJOR de BA254: la reserva BA254 se cuelga ANTES (ts 10-11) que la
    primaria BA07 (ts 20-21). El emparejamiento se fija al activar: BA07 -> BA254
    y despues BA254 -> BA11, no BA254 -> BA254 ni BA07 -> BA11."""
    entry = _rs_entry(reserve_backend_keys=["BA254", "BA11"])
    rows = [
        _rs_row("BA03"),
        *_rs_hang("BA254", start=10),
        *_rs_hang("BA07", start=20),
        _rs_row("BA11", sec=40),
    ]
    v = _rs_audit(monkeypatch, rows, entry=entry)
    assert _rs_pairs(v) == [("BA07", "BA254"), ("BA254", "BA11")]
    assert v["reserve_exhausted"] == []
    assert v["ok"] is True


def test_reserve_hanging_earlier_with_a_single_reserve_exhausts_the_reserve(
    monkeypatch,
):
    """Misma situacion con UNA reserva: BA07 -> BA254 y lo agotado es BA254 (la
    reserva colgada), no la primaria BA07."""
    rows = [
        _rs_row("BA03"),
        *_rs_hang("BA254", start=10),
        *_rs_hang("BA07", start=20),
    ]
    v = _rs_audit(monkeypatch, rows)
    assert _rs_pairs(v) == [("BA07", "BA254")]
    assert [x["backend_key"] for x in v["reserve_exhausted"]] == ["BA254"]
    assert v["ok"] is False


def test_two_hung_primaries_with_fewer_reserves_are_served_by_first_timestamp(
    monkeypatch,
):
    """Dos primarias colgadas y UNA reserva: la reserva ocupa el sitio de la que
    se colgo antes (BA07, ts 10), aunque BA03 sea menor por clave; BA03 queda
    agotada. Mata ordenar por clave en vez de (primer ts, clave)."""
    rows = [
        *_rs_hang("BA03", start=20),
        *_rs_hang("BA07", start=10),
        _rs_row("BA254", sec=40),
    ]
    v = _rs_audit(monkeypatch, rows)
    assert _rs_pairs(v) == [("BA07", "BA254")]
    assert [x["backend_key"] for x in v["reserve_exhausted"]] == ["BA03"]


def test_a_transport_failure_that_mentions_timeout_is_not_a_hang(monkeypatch):
    """Un fallo de TRANSPORTE cuyo texto contiene la palabra `timeout` NO es una
    lente colgada: no activa reserva. Mata `'timeout' in mode`."""
    mode = "transport_failed: HTTP 408 request timeout (TPM 8000)"
    assert not cle.is_hang_row(_rs_row("BA07", hang=mode, answered=False))
    rows = [
        _rs_row("BA03"),
        *_rs_hang("BA07", mode=mode),
        _rs_row("BA254", sec=30),
    ]
    v = _rs_audit(monkeypatch, rows)
    assert v["reserve_substitutions"] == []
    assert v["ok"] is False
    assert _rs_not_eligible(v) == {"BA254": "reserve_not_activated"}


def test_a_reserve_activated_in_one_instance_stays_ineligible_in_another(
    monkeypatch,
):
    """BA254 se activa en N1 (BA07 colgado alli) pero en N2 nadie se colgo: su
    ronda de N2 NO cuenta y N2 no llega a N. Mata filtrar reservas entre nonces."""
    emitted = [_emitted("N1"), _emitted("N2", ts="2026-07-24T10:01:00+00:00")]
    rows = [
        _rs_row("BA03", nonce="N1"),
        *_rs_hang("BA07", nonce="N1"),
        _rs_row("BA254", nonce="N1", sec=30),
        _rs_row("BA03", nonce="N2", sec=31),
        _rs_row("BA254", nonce="N2", sec=32),
    ]
    v = _rs_audit(monkeypatch, rows, emitted=emitted)
    by_nonce = {e["nonce"]: e for e in v["per_nonce"]}
    assert by_nonce["N1"]["ok"] is True
    assert by_nonce["N2"]["ok"] is False
    assert by_nonce["N2"]["backends"] == ["BA03"]
    assert by_nonce["N2"]["ineligible"] == ["BA254"]
    assert [s["nonce"] for s in v["reserve_substitutions"]] == ["N1"]


@pytest.mark.parametrize(
    "patch",
    [
        {"reserve_after_timeouts": None},
        {"reserve_backend_keys": None},
        {"reserve_backend_keys": None, "reserve_after_timeouts": None},
        {"reserve_after_timeouts": cle},
        {"reserve_backend_keys": cle},
    ],
)
def test_reserve_fields_present_but_null_or_absent_are_declared_and_invalid(
    monkeypatch, patch
):
    """Un campo PRESENTE con valor null es DECLARADO e invalido (no se descarta
    como si faltara): bloquea con `invalid_coverage`. `cle` marca AUSENTE (se
    borra la clave): con la otra presente tambien es invalido. Ambos null NO
    apaga el mecanismo."""
    entry = _rs_entry()
    for key, value in patch.items():
        if value is cle:
            del entry[key]
        else:
            entry[key] = value
    v = _rs_audit(monkeypatch, [_rs_row("BA03"), _rs_row("BA07", sec=6)], entry=entry)
    assert v["ok"] is False
    assert v["coverage_error"].startswith("invalid_coverage")


def test_declares_reserve_by_key_presence():
    assert cle._declares_reserve({"reserve_backend_keys": None}) is True
    assert cle._declares_reserve({"reserve_backend_keys": ["BA254"]}) is True
    assert cle._declares_reserve({"backend_keys": ["BA03"]}) is False
    assert cle._declares_reserve(None) is False


def _rs_legacy_capture(monkeypatch, name, capsys):
    entry = json.loads(json.dumps(_RS_REAL_ENTRY))
    rows = {
        "hung_two_and_reserve_answers": [
            _rs_row("BA03"),
            *_rs_hang("BA07", times=2),
            _rs_row("BA254", sec=30),
        ],
        "hung_one_below_min": [_rs_row("BA03"), *_rs_hang("BA07", times=1)],
    }[name]
    v = _rs_audit(monkeypatch, rows, entry=entry, keys=tuple(entry["backend_keys"]))
    capsys.readouterr()
    cle._print_verdict(v)
    return v, cle._receipt_view(v), capsys.readouterr().out


@pytest.mark.parametrize("name", sorted(_LEGACY_GOLDEN))
def test_entry_without_reserve_matches_the_pre_152t_verdict_receipt_and_output(
    monkeypatch, capsys, name
):
    """ADITIVIDAD COMPLETA: veredicto + recibo + salida impresa con la entrada
    real (copia literal) son IGUALES a los literales capturados de la version
    87f79a85 (`git show 87f79a85:scripts/check_loop_execution.py` en una copia
    temporal, fuera del repo)."""
    v, receipt, printed = _rs_legacy_capture(monkeypatch, name, capsys)
    golden = _LEGACY_GOLDEN[name]
    assert v == golden["verdict"]
    assert receipt == golden["receipt"]
    assert printed == golden["printed"]


# ---------------------------------------------------------------- ronda 3 (152t)
def test_retired_primary_hanging_does_not_activate_a_reserve(monkeypatch):
    """MAJOR de BA254: BA07 RETIRADA (status deprecated) con N timeouts NO
    sustituye ni agota nada: sin entrada en `by_nonce`, sin sustitucion, y la
    reserva que respondio SIGUE inelegible."""
    rows = [_rs_row("BA03"), *_rs_hang("BA07"), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows, statuses={"BA07": "deprecated"})
    assert v["reserve_substitutions"] == []
    assert v["reserve_exhausted"] == []
    assert v["ok"] is False
    assert v["distinct_backends"] == ["BA03"]
    assert _rs_not_eligible(v) == {"BA254": "reserve_not_activated"}
    assert v["declared_removed"] == [
        {"backend_key": "BA07", "reason": "retired(status=deprecated)"}
    ]
    config = _cov_config(
        keys=("BA03", "BA07", "BA254", "BA11"),
        entry=_rs_entry(),
        statuses={"BA07": "deprecated"},
    )
    activation = cle.reserve_activation(
        rows, [_emitted()], _rs_entry(), config, commit_sha="abc"
    )
    assert activation["by_nonce"] == {}
    assert activation["substitutions"] == []
    assert activation["exhausted"] == []


def test_timeouts_field_reports_the_real_count_above_n(monkeypatch):
    """Con 3 filas y N=2 el registro dice `timeouts == 3` (no N) tanto en la
    sustitucion como en el agotamiento."""
    rows = [_rs_row("BA03"), *_rs_hang("BA07", times=3), _rs_row("BA254", sec=30)]
    v = _rs_audit(monkeypatch, rows)
    assert [s["timeouts"] for s in v["reserve_substitutions"]] == [3]
    assert len(v["reserve_substitutions"][0]["evidence_ts"]) == 3
    rows = [_rs_row("BA03"), *_rs_hang("BA07", times=3)]
    v = _rs_audit(monkeypatch, rows, statuses={"BA254": "deprecated"})
    assert [(x["backend_key"], x["timeouts"]) for x in v["reserve_exhausted"]] == [
        ("BA07", 3)
    ]


def test_timestamp_tie_between_hung_primaries_is_broken_by_key(monkeypatch):
    """Empate de primer ts: desempata la CLAVE, no el orden declarado. Con
    backend_keys [BA07, BA03] y una reserva, la sustituida es BA03."""
    entry = _rs_entry(backend_keys=["BA07", "BA03"])
    rows = [*_rs_hang("BA07", start=10), *_rs_hang("BA03", start=10)]
    rows.append(_rs_row("BA254", sec=40))
    v = _rs_audit(monkeypatch, rows, entry=entry)
    assert _rs_pairs(v) == [("BA03", "BA254")]
    assert [x["backend_key"] for x in v["reserve_exhausted"]] == ["BA07"]


def test_retired_reserve_between_two_active_ones_is_skipped(monkeypatch):
    """Reservas [BA254, BA11, BA02] con BA11 retirada: dos primarias colgadas se
    sirven con BA254 y BA02 (la tercera ocupa el sitio) y BA11 cae con motivo
    `retired(...)`."""
    entry = _rs_entry(reserve_backend_keys=["BA254", "BA11", "BA02"])
    rows = [
        *_rs_hang("BA03", start=10),
        *_rs_hang("BA07", start=20),
        _rs_row("BA254", sec=40),
        _rs_row("BA11", sec=41),
        _rs_row("BA02", sec=42),
    ]
    v = _rs_audit(monkeypatch, rows, entry=entry, statuses={"BA11": "deprecated"})
    assert _rs_pairs(v) == [("BA03", "BA254"), ("BA07", "BA02")]
    assert v["reserve_exhausted"] == []
    assert _rs_not_eligible(v) == {"BA11": "retired(status=deprecated)"}
    assert v["ok"] is True


# ---------------------------------------------------------------- 152t-2 (M3)
# `lens_reliability`: fiabilidad DESCRIPTIVA de cada lente sobre sus ultimas rondas
# (lanzamientos sin fin incluidos cuando dejan fila). Nunca decide el gate.


def _m3_row(backend, kind, idx, **over):
    """Fila `ronda` del formato real; `kind` fija la categoria esperada."""
    spec = {
        "ok": {},
        "muda": {"answered": False},
        "wd": {"hang": _RS_WATCHDOG_MODE, "answered": False},
        "int": {"hang": _RS_INTERNAL_MODE, "answered": False},
        "transport": {
            "hang": "transport_failed: TransportError: HTTP 402",
            "answered": False,
        },
        "otra": {"hang": "usage-error", "answered": False},
    }[kind]
    row = _rs_row(backend, **spec)
    row["ts"] = f"2026-07-24T11:{idx // 60:02d}:{idx % 60:02d}+00:00"
    row.update(over)
    return row


def _m3_by(report, backend):
    return report["by_backend"][backend]


def test_lens_reliability_splits_each_round_into_exactly_one_category():
    """ok / mudas / timeouts (las DOS formas) / transporte / otras, excluyentes."""
    rows = [
        _m3_row("BA07", k, i)
        for i, k in enumerate(["ok", "muda", "wd", "int", "transport", "otra"])
    ]
    entry = _m3_by(cle.lens_reliability(rows, window=6), "BA07")
    assert entry == {
        "ok": 1,
        "mudas": 1,
        "timeouts": 2,
        "transporte": 1,
        "otras": 1,
        "rondas": 6,
        "rondas_totales": 6,
    }
    assert sum(entry[c] for c in cle.LENS_RELIABILITY_CATEGORIES) == entry["rondas"]


def test_lens_reliability_window_keeps_the_latest_rounds_by_timestamp():
    """Ventana = las ULTIMAS `window` rondas por `ts`, aunque las filas lleguen
    desordenadas; `rondas_totales` conserva el denominador previo a la ventana."""
    rows = [_m3_row("BA07", "wd", i) for i in range(3)]
    rows += [_m3_row("BA07", "ok", i) for i in range(3, 8)]
    shuffled = [rows[i] for i in (7, 0, 5, 2, 6, 1, 4, 3)]
    report = cle.lens_reliability(shuffled, window=5)
    assert _m3_by(report, "BA07") == {
        "ok": 5,
        "mudas": 0,
        "timeouts": 0,
        "transporte": 0,
        "otras": 0,
        "rondas": 5,
        "rondas_totales": 8,
    }
    wide = cle.lens_reliability(shuffled, window=8)
    assert _m3_by(wide, "BA07")["timeouts"] == 3


def test_lens_reliability_window_is_per_backend_not_global():
    """Una lente muy activa no expulsa a otra: BA07 con 2 rondas sigue viendo las
    2 aunque BA03 tenga 10 posteriores."""
    rows = [_m3_row("BA07", "wd", i) for i in range(2)]
    rows += [_m3_row("BA03", "ok", i) for i in range(10, 20)]
    report = cle.lens_reliability(rows, window=5)
    assert _m3_by(report, "BA07")["rondas"] == 2
    assert _m3_by(report, "BA07")["timeouts"] == 2
    assert _m3_by(report, "BA03")["rondas"] == 5
    assert _m3_by(report, "BA03")["rondas_totales"] == 10


def test_lens_reliability_declares_the_denominator():
    """El denominador cuenta lo leido y lo EXCLUIDO (exploracion, sin backend_key,
    eventos que no son `ronda`)."""
    rows = [
        _m3_row("BA07", "ok", 0),
        _m3_row("BA07", "wd", 1),
        _m3_row("BA03", "ok", 2, task_type="exploracion"),
        _m3_row(None, "ok", 3),
        {"event": "adjudicacion", "ts": "2026-07-24T11:00:04+00:00"},
        {"event": "supersede", "ts": "2026-07-24T11:00:05+00:00"},
    ]
    report = cle.lens_reliability(rows)
    assert report["denominator"] == {
        "rows_read": 6,
        "ronda_rows": 4,
        "excluded_exploracion": 1,
        "excluded_without_backend_key": 1,
        "counted": 2,
        "backend_keys": 1,
    }
    assert sorted(report["by_backend"]) == ["BA07"]


def test_a_hang_is_a_timeout_and_never_a_mute_round():
    """Una ronda colgada tampoco es `muda` ni `ok`: una sola categoria."""
    report = cle.lens_reliability([_m3_row("BA07", "wd", 0)])
    entry = _m3_by(report, "BA07")
    assert (entry["timeouts"], entry["mudas"], entry["ok"]) == (1, 0, 0)
    mute = _m3_by(cle.lens_reliability([_m3_row("BA07", "muda", 0)]), "BA07")
    assert (mute["mudas"], mute["timeouts"], mute["ok"]) == (1, 0, 0)


def test_lens_reliability_declares_its_blind_spots():
    blind = cle.lens_reliability([])["blind_spots"]
    assert blind == list(cle.LENS_RELIABILITY_BLIND_SPOTS)
    joined = " ".join(blind)
    for needle in ("H145", "--watchdog-s", "NUNCA decide el gate", "exploracion"):
        assert needle in joined, needle
    assert cle.lens_reliability([])["by_backend"] == {}


@pytest.mark.parametrize("window", [0, -1, True, "5", 2.5, None])
def test_lens_reliability_rejects_an_invalid_window(window):
    with pytest.raises(ValueError, match="window"):
        cle.lens_reliability([], window=window)


def test_lens_reliability_is_pure():
    rows = [_m3_row("BA07", k, i) for i, k in enumerate(["wd", "ok", "muda"])]
    before = json.dumps(rows, sort_keys=True)
    first = cle.lens_reliability(rows)
    assert json.dumps(rows, sort_keys=True) == before
    assert first == cle.lens_reliability(rows)
    json.dumps(first)


def test_lens_reliability_is_not_wired_into_the_gate():
    """ADITIVIDAD: ni `audit` ni `audit_commit` ni el recibo ni la impresion del
    veredicto consultan M3: no puede cambiar `ok`."""
    import inspect

    for fn in (cle.audit, cle.audit_commit, cle._receipt_view, cle._print_verdict):
        assert "lens_reliability" not in inspect.getsource(fn), fn.__name__


def _m3_root(tmp_path, rows):
    ens = tmp_path / ".agent" / "runtime" / "ensemble"
    ens.mkdir(parents=True)
    lines = [json.dumps(r, ensure_ascii=True) for r in rows]
    (ens / "scorecard.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def test_cli_lens_reliability_prints_json_and_never_decides_the_gate(tmp_path, capsys):
    """Con TODAS las lentes colgadas el flag sigue saliendo 0 y no imprime ningun
    veredicto OK/FAIL, aunque se le pase un --commit-sha (solo lectura)."""
    rows = [_m3_row("BA07", "wd", i) for i in range(3)]
    root = _m3_root(tmp_path, rows)
    rc = cle.main(
        ["--project-root", str(root), "--lens-reliability", "--commit-sha", "abc"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "[loop-exec] OK" not in out and "[loop-exec] FAIL" not in out
    assert "loop_exec_receipt" not in out
    payload = json.loads(out.strip().splitlines()[-1])["lens_reliability"]
    assert payload["window"] == 5
    assert payload["by_backend"]["BA07"]["timeouts"] == 3


def test_cli_lens_window_is_honoured_and_validated(tmp_path, capsys):
    rows = [_m3_row("BA07", "ok", i) for i in range(4)]
    root = _m3_root(tmp_path, rows)
    assert (
        cle.main(
            ["--project-root", str(root), "--lens-reliability", "--lens-window", "2"]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out.strip())["lens_reliability"]
    assert payload["by_backend"]["BA07"]["rondas"] == 2
    assert payload["by_backend"]["BA07"]["rondas_totales"] == 4
    rc = cle.main(
        ["--project-root", str(root), "--lens-reliability", "--lens-window", "0"]
    )
    assert rc == 1
    assert "ERROR" in capsys.readouterr().out


@pytest.mark.parametrize(
    "statuses",
    [
        {},
        {"BA07": "deprecated"},
        {"BA03": "archived"},
        {"BA03": "archived", "BA07": "deprecated"},
    ],
)
def test_effective_primaries_equal_effective_eligible_in_declared_order(statuses):
    """ANCLA (MINOR 1 de BA03, ronda 3): las primarias que activan reserva SON las
    que `effective_eligible` deja elegibles, en el orden declarado de
    `backend_keys` (aqui deliberadamente [BA07, BA03])."""
    entry = _rs_entry(backend_keys=["BA07", "BA03"])
    config = _cov_config(
        keys=("BA03", "BA07", "BA254", "BA11"), entry=entry, statuses=statuses
    )
    eligible, _removed = cle.effective_eligible(entry, config)
    primaries = cle._effective_primaries(entry, config)
    assert set(primaries) == eligible
    assert primaries == [k for k in entry["backend_keys"] if k in eligible]


_H148_EVENT_STREAM = (
    '{"type":"step_start","timestamp":1793486759170,"part":{"type":"step-start"}}\n'
    '{"type":"step_finish","timestamp":1793486759900,"part":{"type":"step-finish"}}'
)


def test_lens_reliability_does_not_reclassify_the_h148_event_stream(monkeypatch):
    """H148 (WOT-2026-152x): el registrador ya escribe NUEVAS rondas sin texto como
    mudas, pero una fila HISTORICA con el stream sin parte `text` (fila real de
    BA03, nonce eb8b902d, output_chars 778) NO se reclasifica: `is_substantive`
    no parsea la evidencia y M3 sigue a `is_substantive`, que es lo que
    `blind_spots` declara."""
    row = _m3_row("BA03", "ok", 0, output_chars=778)
    row["evidencia"] = _H148_EVENT_STREAM
    assert cle.is_substantive(row) is True  # historica: sigue contando `ok`
    entry = _m3_by(cle.lens_reliability([row]), "BA03")
    assert (entry["ok"], entry["mudas"]) == (1, 0)
    spots = cle.lens_reliability([row])["blind_spots"]
    assert [b for b in spots if b.startswith("H148:")], "falta el blind_spot H148"
    blind = " ".join(spots)
    for needle in (
        "H148",
        "arreglada hacia adelante",
        "SOBRESTIMA",
        "SUBESTIMA",
        "NO las reclasifica",
    ):
        assert needle in blind, needle
    # delega en is_substantive: lo que is_substantive decida, M3 lo hereda sin tocarse
    monkeypatch.setattr(cle, "is_substantive", lambda _row: False)
    entry = _m3_by(cle.lens_reliability([row]), "BA03")
    assert (entry["ok"], entry["mudas"]) == (0, 1)


# Fila REAL de BA03 (scorecard de sandbox co15_sbx_140a, ts 2026-11-01T17:49:10Z,
# nonce eb8b902d): `evidencia` es el stream crudo step_start/step_finish SIN parte
# `text` del modelo y aun asi `output_chars` es 778. Copia literal de los campos
# relevantes (sin secretos). Documenta H148 tal como esta HOY.
_H148_REAL_ROW = {
    "ts": "2026-11-01T17:49:10.087636+00:00",
    "event": "ronda",
    "ticket": "WOT-2026-152t",
    "rol": "challenger",
    "task_type": "code-review",
    "outcome": None,
    "evidencia": '{"type":"step_start","timestamp":1793555145501,"sessionID":"ses_e67c89b51ffeyMqesa0Ce6l4Nu","part":{"id":"prt_19837a315001dI6Yai2sv30MlC","sessionID":"ses_e67c89b51ffeyMqesa0Ce6l4Nu","messageID":"msg_198377a21001vWjnRz6ejdJZhe","type":"step-start","snapshot":"e5467425f906f1f92acf1e4b31ba0ef9f88fac8d"}}\n{"type":"step_finish","timestamp":1793555345139,"sessionID":"ses_e67c89b51ffeyMqesa0Ce6l4Nu","part":{"id":"prt_1983aaeea001FlyT5KuCNd996A","sessionID":"ses_e67c89b51ffeyMqesa0Ce6l4Nu","messageID":',
    "failure_mode": None,
    "phase": "MANAGER_REVIEW",
    "loop_id": "UNI-4",
    "backend_key": "BA03",
    "commit_sha": "c6a46a6177ab26ab8a7a7d24389b79b84c3e5714",
    "challenge_nonce": "eb8b902d0bff6e4a38e95ba5d06076e8",
    "output_chars": 778,
    "channel": "agent",
}


def test_h148_real_row_historical_stays_ok_and_blind_spots_say_so():
    """H148 arreglada HACIA ADELANTE (WOT-2026-152x): la FILA HISTORICA real sigue
    contando `ok` (NON-GOAL: no se reclasifica el historico) y `blind_spots` lo
    declara. Las filas NUEVAS sin texto nacen mudas del registrador (ver
    `test_ensemble_dispatch_152x.py`)."""
    row = dict(_H148_REAL_ROW)
    assert '"type":"text"' not in row["evidencia"]
    assert row["output_chars"] == 778
    assert cle.is_substantive(row) is True
    assert cle._reliability_category(row) == "ok"
    report = cle.lens_reliability([row])
    entry = _m3_by(report, "BA03")
    assert (entry["ok"], entry["mudas"], entry["rondas"]) == (1, 0, 1)
    assert [b for b in report["blind_spots"] if b.startswith("H148:")]


@pytest.mark.parametrize("bad", [7, 3.5, True, ["x"], {"a": 1}])
def test_is_substantive_never_raises_on_a_non_string_evidencia(bad):
    """Fila corrupta (WOT-2026-152x): `evidencia` no-str se trata como ausente
    (fail-OPEN, igual que una fila legacy) y no lanza; las otras senales de
    silencio siguen mordiendo."""
    row = {"event": "ronda", "evidencia": bad}
    assert cle.is_substantive(row) is True
    assert cle.is_substantive({**row, "output_chars": 0}) is False
    assert cle.is_substantive({**row, "outcome": "no-aportacion"}) is False
    assert cle._reliability_category({**row, "backend_key": "BA03"}) == "ok"


@pytest.mark.parametrize("bad", [1, 3.5, True, ["x"], {"a": 1}])
def test_a_non_string_failure_mode_is_other_and_never_raises(bad):
    """Fila corrupta: `failure_mode` no-str y no vacio => `otras`, sin lanzar."""
    row = _m3_row("BA07", "ok", 0, failure_mode=bad)
    assert cle._reliability_category(row) == "otras"
    entry = _m3_by(cle.lens_reliability([row, _m3_row("BA07", "ok", 1)]), "BA07")
    assert (entry["otras"], entry["ok"], entry["rondas"]) == (1, 1, 2)


@pytest.mark.parametrize("empty", [0, "", [], None])
def test_a_falsy_failure_mode_counts_as_absent(empty):
    """Un `failure_mode` vacio/falsy equivale a ausente: la ronda sigue su regla."""
    row = _m3_row("BA07", "ok", 0, failure_mode=empty)
    assert cle._reliability_category(row) == "ok"


_M3_BAD_KEYS = [["BA07"], {"k": "BA07"}, 7, True, 3.5, "", "   "]


@pytest.mark.parametrize("bad", _M3_BAD_KEYS, ids=repr)
def test_a_non_string_or_empty_backend_key_is_excluded_and_never_raises(bad):
    """Fila corrupta (backend_key lista/dict/int/bool/float/vacio): se EXCLUYE del
    conteo por lente y se cuenta en `excluded_without_backend_key`; las demas
    lentes siguen contando."""
    rows = [
        _m3_row("BA07", "ok", 0),
        _m3_row("BA03", "wd", 1),
        _m3_row(bad, "ok", 2),
    ]
    report = cle.lens_reliability(rows)
    assert sorted(report["by_backend"]) == ["BA03", "BA07"]
    assert report["denominator"]["excluded_without_backend_key"] == 1
    assert report["denominator"]["counted"] == 2
    assert report["denominator"]["ronda_rows"] == 3
    assert _m3_by(report, "BA03")["timeouts"] == 1


def test_mixed_str_and_int_backend_keys_do_not_break_the_ordering():
    """str e int mezclados en el mismo scorecard: `sorted` no lanza y el resto de
    lentes sigue contando."""
    rows = [
        _m3_row("BA07", "ok", 0),
        _m3_row(5, "ok", 1),
        _m3_row("BA03", "ok", 2),
        _m3_row(None, "ok", 3),
        _m3_row(["BA03"], "ok", 4),
    ]
    report = cle.lens_reliability(rows)
    assert list(report["by_backend"]) == ["BA03", "BA07"]
    assert report["denominator"]["excluded_without_backend_key"] == 3
    assert report["denominator"]["counted"] == 2


def test_cli_lens_reliability_survives_corrupt_backend_keys(tmp_path, capsys):
    rows = [
        _m3_row("BA07", "wd", 0),
        _m3_row(["BA07"], "ok", 1),
        _m3_row({"k": 1}, "ok", 2),
        _m3_row(9, "ok", 3),
        _m3_row(True, "ok", 4),
    ]
    root = _m3_root(tmp_path, rows)
    assert cle.main(["--project-root", str(root), "--lens-reliability"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())["lens_reliability"]
    assert list(payload["by_backend"]) == ["BA07"]
    assert payload["denominator"]["excluded_without_backend_key"] == 4
    assert payload["by_backend"]["BA07"]["timeouts"] == 1


def test_ts_ordering_is_textual_and_blind_spots_declare_it():
    """LIMITE fijado: el orden por `ts` compara el TEXTO ISO. Con offsets mezclados
    la ventana puede invertirse: 11:00+02:00 (= 09:00Z, ANTERIOR) gana a
    10:00+00:00 por ser mayor como texto. No se parsean fechas; `blind_spots` lo
    declara con etiqueta propia (ORDEN-TS)."""
    earlier_real = _m3_row("BA07", "wd", 0, ts="2026-11-01T11:00:00+02:00")
    later_real = _m3_row("BA07", "ok", 1, ts="2026-11-01T10:00:00+00:00")
    report = cle.lens_reliability([later_real, earlier_real], window=1)
    entry = _m3_by(report, "BA07")
    assert (entry["timeouts"], entry["ok"]) == (1, 0), "conserva la mayor como texto"
    spots = [b for b in report["blind_spots"] if b.startswith("ORDEN-TS:")]
    assert len(spots) == 1
    for needle in ("TEXTO ISO", "UTC", "+00:00", "invertirse"):
        assert needle in spots[0], needle
    # con ts normalizados UTC el orden textual coincide con el real
    utc_a = _m3_row("BA07", "wd", 0, ts="2026-11-01T09:00:00+00:00")
    utc_b = _m3_row("BA07", "ok", 1, ts="2026-11-01T10:00:00+00:00")
    entry = _m3_by(cle.lens_reliability([utc_b, utc_a], window=1), "BA07")
    assert (entry["timeouts"], entry["ok"]) == (0, 1)


# =========================================================== WOT-2026-152s-2
# `failure_mode` se lee UNA vez (strip + no-str), el texto fijo del diagnostico de un
# `timeout:` no afirma ninguna muerte, y la forma nueva del timeout interno cuenta
# UNA vez como colgado. Filas con la redaccion REAL de cada emisor.

_S2_CONFIRMED = (
    "timeout: watchdog de 600s vencido sin respuesta de la lente; "
    "hijo (pid 4242) matado, confirmado por poll(); descendientes no verificados"
)
_S2_UNCONFIRMED = (
    "timeout: watchdog de 600s vencido sin respuesta de la lente; "
    "kill NO confirmado; el hijo (pid 4242) puede seguir vivo"
)
# Forma NUEVA del timeout interno (la que escribe `run_loop_round` desde 152s-2).
_S2_INTERNAL_NEW = (
    "timeout: RuntimeError: backend CLI sin respuesta tras 900s; se intento matar "
    "el arbol de procesos (taskkill /T /F), muerte NO verificada. CAUSA NO DETERMINADA"
)


def test_padded_timeout_mode_gets_one_reading_in_diagnosis_and_label(capsys):
    """La MISMA fila no puede leerse de dos formas: con espacios alrededor del
    prefijo `timeout:` el diagnostico, `is_hang_row` y la etiqueta del informe
    coinciden con los de la fila limpia. Mutaciones: quitar el strip de la
    etiqueta de `_print_verdict` (sale MUDA) o el de `diagnose_silence` (cae al
    texto de adjudicacion) -> rojo."""
    clean = _timeout_round("BA07")
    padded = _timeout_round("BA07")
    padded["failure_mode"] = "  " + clean["failure_mode"] + " \t"

    assert cle.diagnose_silence(padded) == cle.diagnose_silence(clean)
    assert "NO respondio dentro del limite" in cle.diagnose_silence(padded)
    assert cle.is_hang_row(padded) and cle.is_hang_row(clean)
    v = cle.audit_commit(
        [_ronda("BA10"), padded], [_emitted()], commit_sha="abc", min_distinct=2
    )
    cle._print_verdict(v)
    out = capsys.readouterr().out
    assert "TIMEOUT BA07" in out
    assert "MUDA BA07" not in out


@pytest.mark.parametrize("bad", [123, ["timeout:"], {"a": 1}, 4.5])
def test_corrupt_failure_mode_rows_never_raise_in_the_gate_path(bad, capsys):
    """Una fila CORRUPTA (`failure_mode` entero, lista, dict, float) no tumba el
    gate: `diagnose_silence`, `is_hang_row`, el recuento, el informe y M3 la leen
    como no-textual. Antes `diagnose_silence` e `is_hang_row` lanzaban
    AttributeError. Mutacion: el helper deja de tolerar no-str -> rojo."""
    row = _muda("BA11")
    row["failure_mode"] = bad

    assert "no textual" in cle.diagnose_silence(row)
    assert cle.is_hang_row(row) is False
    assert cle._reliability_category(row) == "otras"
    v = cle.audit_commit(
        [_ronda("BA10"), row], [_emitted()], commit_sha="abc", min_distinct=2
    )
    assert [s["backend_key"] for s in v["silent_rounds"]] == ["BA11"]
    cle._print_verdict(v)
    assert "MUDA BA11" in capsys.readouterr().out
    report = cle.lens_reliability([row])
    assert report["by_backend"]["BA11"]["otras"] == 1


@pytest.mark.parametrize("mode", [_S2_CONFIRMED, _S2_UNCONFIRMED])
def test_timeout_fixed_text_never_asserts_a_kill_for_any_failure_mode(mode, capsys):
    """BA254 (ronda 3 de 152s-1): el test anterior solo excluia `fue matado`, asi
    que `arbol matado` en el texto FIJO pasaba. Aqui el texto fijo (lo anterior a
    `Detalle:`) no contiene NINGUNA forma de `matad...`, ni en el diagnostico ni en
    la linea impresa, con la fila confirmada y con la no confirmada; la
    confirmacion solo viaja en el Detalle copiado de la fila. Mutacion: anadir
    `arbol matado` al texto fijo -> rojo."""
    row = _timeout_round("BA07")
    row["failure_mode"] = mode

    diagnosis = cle.diagnose_silence(row)
    fixed, sep, detail = diagnosis.partition("Detalle:")
    assert sep == "Detalle:" and detail.strip() == mode
    assert "NO respondio dentro del limite" in fixed
    assert "matad" not in fixed.lower()

    v = cle.audit_commit(
        [_ronda("BA10"), row], [_emitted()], commit_sha="abc", min_distinct=2
    )
    cle._print_verdict(v)
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "TIMEOUT BA07" in ln)
    printed_fixed, _sep, printed_detail = line.partition("Detalle:")
    assert "matad" not in printed_fixed.lower()
    assert mode in printed_detail


def test_new_internal_timeout_form_counts_once_and_the_old_form_still_counts(
    monkeypatch,
):
    """Sin DOBLE conteo: la fila `timeout: RuntimeError: backend CLI sin respuesta
    tras ...` casa a la vez el prefijo `timeout:` y el marcador interno, y cuenta
    UNA vez (un colgado solo no alcanza N=2 y no activa la reserva). La forma
    historica `unexpected: RuntimeError: ...` sigue contando como hoy, y una de cada
    forma suman 2. Mutacion: sumar prefijo y marcador por separado -> rojo."""
    for mode in (_S2_INTERNAL_NEW, _RS_INTERNAL_MODE):
        rows = [
            _rs_row("BA03"),
            *_rs_hang("BA07", times=1, mode=mode),
            _rs_row("BA254", sec=30),
        ]
        v = _rs_audit(monkeypatch, rows)
        assert v["ok"] is False, mode
        assert v["reserve_substitutions"] == [], mode
        assert _rs_not_eligible(v) == {"BA254": "reserve_not_activated"}, mode

    mixed = [
        _rs_row("BA03"),
        _rs_row("BA07", hang=_S2_INTERNAL_NEW, answered=False, sec=10),
        _rs_row("BA07", hang=_RS_INTERNAL_MODE, answered=False, sec=11),
        _rs_row("BA254", sec=30),
    ]
    v = _rs_audit(monkeypatch, mixed)
    assert v["ok"] is True
    assert v["reserve_substitutions"][0]["timeouts"] == 2

    solo = [_rs_row("BA07", hang=_S2_INTERNAL_NEW, answered=False)]
    entry = cle.lens_reliability(solo)["by_backend"]["BA07"]
    assert (entry["timeouts"], entry["mudas"], entry["otras"], entry["ok"]) == (
        1,
        0,
        0,
        0,
    )
    assert cle.diagnose_silence(solo[0]).startswith("la lente NO respondio")
