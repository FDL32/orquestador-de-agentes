"""WOT-2026-152x (H148): una lente MUDA no puede contar como sustantiva.

EL DEFECTO QUE FIJA (medido 2026-11-01, HEAD b7a71cdb, fila real de BA03,
nonce eb8b902d)
--------------------------------------------------------------------------
`kilo --format json` devuelve la respuesta como stream NDJSON de eventos
(step_start / text / step_finish). `_record_round` medio ese stream CRUDO: una
ronda que solo emitio step_start + step_finish (778 B, ninguna parte `text` del
modelo) quedaba con output_chars 778, outcome None y `is_substantive` True; el
gate la contaba como lente que aporta.

QUE HACE EL ARREGLO
-------------------
`_event_stream_has_no_model_text` (puro) decide si el reply es un stream de
eventos de CICLO DE VIDA de kilo/opencode (conjunto cerrado
`_LIFECYCLE_EVENT_TYPES`) SIN texto del modelo; `_record_round` lo registra
entonces muda (output_chars 0 + no-aportacion, failure_mode y evidencia
intactos). Es FAIL-OPEN y CONSERVADOR: un falso "muda" bloquea el gate, un falso
"sustantiva" es el defecto de hoy; una respuesta JSON legitima de cualquier
canal (`{"type":"review",...}`) NO se silencia.

LIMITES DECLARADOS
------------------
- Las filas HISTORICAS ya registradas (output_chars 778 con stream sin texto)
  NO se reclasifican: siguen contando `ok` (ver test_check_loop_execution.py).
- Un stream de solo error/tool_use/reasoning (tipo fuera del conjunto cerrado)
  NO se detecta mudo; y uno con un `text` no vacio cuenta como CON texto.
- Solo se mira el reply de `_record_round`; otros consumidores del reply crudo
  no cambian.

Los ids de los fixtures estan ACORTADOS (ses_x1, prt_x1...) para no disparar el
detector de entropia de privacy_preflight; la FORMA de los eventos es la real.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_loop_execution as cle  # noqa: E402
import ensemble_dispatch as ed  # noqa: E402


_SHA = "c6a46a6177ab26ab8a7a7d24389b79b84c3e5714"
_NONCE = "N152X"


def _ev(**fields) -> str:
    return json.dumps(fields, separators=(",", ":"))


_STEP_START = _ev(
    type="step_start",
    timestamp=1,
    sessionID="ses_x1",
    part={"id": "prt_x1", "sessionID": "ses_x1", "type": "step-start"},
)
_STEP_FINISH = _ev(
    type="step_finish",
    timestamp=2,
    sessionID="ses_x1",
    part={
        "id": "prt_x2",
        "type": "step-finish",
        "reason": "stop",
        "cost": 0,
        "tokens": {"input": 10, "output": 0, "reasoning": 0},
    },
)
_TEXT = _ev(
    type="text",
    timestamp=3,
    sessionID="ses_x1",
    part={"id": "prt_x3", "type": "text", "text": "Hallazgo: falta el guard."},
)
_ERROR = _ev(type="error", timestamp=3, error={"name": "ApiError", "data": {"m": "x"}})
_TOOL_USE = _ev(
    type="tool_use",
    timestamp=3,
    part={"id": "prt_x4", "type": "tool", "tool": "read", "state": {"status": "ok"}},
)
_REASONING = _ev(
    type="reasoning", timestamp=3, part={"id": "prt_x5", "type": "reasoning"}
)


def _stream(*events: str) -> str:
    return "\n".join(events)


# --------------------------------------------------------------------- el helper
_STEP_START_H = _ev(type="step-start", part={"type": "step-start"})
_STEP_FINISH_H = _ev(type="step-finish", part={"type": "step-finish"})
_LIFECYCLE_BLANK_TEXT = _ev(
    type="step_start", part={"type": "step-start", "text": "  \t "}
)


@pytest.mark.parametrize(
    "events",
    [
        (_STEP_START, _STEP_FINISH),  # la forma exacta de H148
        (_STEP_START,),  # un solo evento de ciclo de vida
        (_STEP_START_H, _STEP_FINISH_H),  # variante con guion
        (_STEP_START, _LIFECYCLE_BLANK_TEXT, _STEP_FINISH),  # `text` en blanco
    ],
)
def test_lifecycle_only_stream_without_model_text_is_mute(events):
    assert ed._event_stream_has_no_model_text(_stream(*events) + "\n\n") is True


@pytest.mark.parametrize(
    "events",
    [
        (_STEP_START, _TEXT, _STEP_FINISH),  # control negativo: forma real CON texto
        (
            _STEP_START,
            _ev(
                type="step_finish",
                part={"state": {"output": {"text": "salida de la herramienta"}}},
            ),
        ),  # `text` ANIDADO a cualquier profundidad (no solo part.type == text)
        (
            _STEP_START,
            _ev(type="step_finish", parts=[{"k": [{"text": "en una lista"}]}]),
        ),
        (_STEP_START, _ev(type="step_finish", part={"type": "reasoning", "text": "x"})),
    ],
)
def test_event_stream_with_any_nonempty_text_is_not_mute(events):
    assert ed._event_stream_has_no_model_text(_stream(*events)) is False


@pytest.mark.parametrize(
    "events",
    [
        (_STEP_START, _ERROR, _STEP_FINISH),
        (_STEP_START, _TOOL_USE, _STEP_FINISH),
        (_STEP_START, _REASONING, _STEP_FINISH),
        (_STEP_START, _ev(type="text", part={"type": "text", "text": " "})),
        (_STEP_START, _ev(type="evento_nuevo", part={"id": "prt_x9"})),
        (_ERROR,),  # solo error
        (_TOOL_USE,),  # solo tool_use
    ],
)
def test_a_line_outside_the_closed_lifecycle_set_is_never_mute(events):
    """LIMITE declarado: ciclo de vida MAS un tipo fuera del conjunto cerrado =>
    False (fail-open), aunque no traiga texto."""
    assert ed._event_stream_has_no_model_text(_stream(*events)) is False


@pytest.mark.parametrize(
    "reply",
    [
        '{"type":"review","findings":[],"verdict":"APPROVE"}',
        '{"type":"error","error":{"name":"ApiError","data":{"m":"x"}}}',
        '{"type":["step_start"]}',  # `type` no-str: no se hashea ni lanza
        '{"type":{"k":"step_start"}}',
        '{"type":null}',
    ],
)
def test_a_json_answer_with_another_top_level_type_is_not_mute(reply):
    """CONTROL NEGATIVO (BA254 MAJOR): una respuesta JSON sustantiva de cualquier
    canal con clave `type` NO es un stream mudo."""
    assert ed._event_stream_has_no_model_text(reply) is False


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   \n  ",
        "Hallazgo: todo bien",  # texto libre
        _STEP_START + "\nruido no JSON\n" + _STEP_FINISH,  # una linea no JSON
        'ruido\n{"type":"step_start"}',
        '["type","step_start"]',  # JSON valido pero no objeto
        '{"sin_type": 1}',  # objeto sin clave `type`
        _STEP_START + '\n{"type":"step_fini',  # stream truncado a medias
        None,
        123,
    ],
)
def test_anything_that_is_not_a_pure_event_stream_is_fail_open(raw):
    """Texto libre, ruido, truncado, vacio o no-str: NO es 'stream mudo'."""
    assert ed._event_stream_has_no_model_text(raw) is False


def test_absurdly_nested_json_is_fail_open_and_never_raises():
    """Anidamiento absurdo (RecursionError/ValueError del parser): no lanza.
    Se construye en el cuerpo: un parametro gigante rompe PYTEST_CURRENT_TEST."""
    raw = '{"type":' + "[" * 200000 + "]" * 200000 + "}"
    assert ed._event_stream_has_no_model_text(raw) is False


# --------------------------------------------------------- el registrador real
_PROFILE = {"backend": "kilo", "model": "glm-x", "channel": "agent"}


def _record(tmp_path: Path, reply: str, **kw) -> dict:
    ed._record_round(
        tmp_path,
        ticket="WOT-2026-152x",
        task_type="code-review",
        rol="challenger",
        profile=dict(_PROFILE),
        backend_version=None,
        ronda=1,
        reply=reply,
        input_bytes=100,
        context_kind="diff",
        phase="MANAGER_REVIEW",
        loop_id="UNI-4",
        backend_key="BA03",
        commit_sha=_SHA,
        challenge_nonce=_NONCE,
        **kw,
    )
    path = tmp_path / ".agent" / "runtime" / "ensemble" / "scorecard.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    assert len(rows) == 1
    return rows[0]


def test_h148_stream_without_text_is_recorded_mute_by_the_real_recorder(tmp_path):
    """POSITIVO (DoD): el stream de H148 por la ruta de produccion => fila NUEVA muda."""
    raw = _stream(_STEP_START, _STEP_FINISH)
    row = _record(tmp_path, raw)
    assert row["output_chars"] == 0
    assert row["outcome"] == "no-aportacion"
    assert row["failure_mode"] is None  # no se inventa una causa
    assert row["evidencia"] == raw[:500]  # el diagnostico (stream crudo) no se pierde
    assert cle.is_substantive(row) is False
    assert cle._reliability_category(row) == "mudas"
    report = cle.lens_reliability([row])
    assert (
        report["by_backend"]["BA03"]["ok"],
        report["by_backend"]["BA03"]["mudas"],
    ) == (0, 1)
    # y el gate la ve silenciosa, no como lente que cuenta
    emitted = [
        {
            "ts": "2026-07-24T10:00:00+00:00",
            "issuer_role": "orchestrator",
            "issuer_backend_key": "BA01",
            "issued_before_ts": "2026-07-24T10:00:00+00:00",
            "commit_sha": _SHA,
            "loop_id": "UNI-4",
            "challenge_nonce": _NONCE,
        }
    ]
    row = dict(row, ts="2026-07-24T10:05:00+00:00")
    verdict = cle.audit_commit([row], emitted, commit_sha=_SHA, min_distinct=1)
    assert verdict["distinct_backends"] == []
    assert [s["backend_key"] for s in verdict["silent_rounds"]] == ["BA03"]
    assert verdict["ok"] is False


def test_stream_with_a_text_part_stays_substantive(tmp_path):
    """NEGATIVO: el mismo stream CON parte text conserva medida y sustancia."""
    raw = _stream(_STEP_START, _TEXT, _STEP_FINISH)
    row = _record(tmp_path, raw)
    assert row["output_chars"] == len(raw)
    assert row["outcome"] is None
    assert row["failure_mode"] is None
    assert cle.is_substantive(row) is True


def test_real_shaped_stream_with_model_text_stays_substantive(tmp_path):
    """CONTROL NEGATIVO REAL (BA03 ronda 2 de 152t-2, stream OK): la FORMA literal
    de sus tres eventos (step_start, text, step_finish) con los ids ACORTADOS y el
    texto recortado a unos caracteres. Debe quedar sustantivo."""
    start = (
        '{"type":"step_start","timestamp":1,"sessionID":"ses_x1","part":{"id":"prt_x1",'
        '"sessionID":"ses_x1","messageID":"msg_x1","type":"step-start","snapshot":"snap_x1"}}'
    )
    text = (
        '{"type":"text","timestamp":2,"sessionID":"ses_x1","part":{"id":"prt_x2",'
        '"sessionID":"ses_x1","messageID":"msg_x1","type":"text",'
        '"text":"# REVISION ronda 2","time":{"start":1,"end":2}}}'
    )
    finish = (
        '{"type":"step_finish","timestamp":3,"sessionID":"ses_x1","part":{"id":"prt_x3",'
        '"sessionID":"ses_x1","messageID":"msg_x1","type":"step-finish","reason":"stop",'
        '"snapshot":"snap_x2","metrics":{"generation":46.9,"source":"computed"},'
        '"time":{"start":1,"end":3,"elapsed":2},"cost":0,'
        '"tokens":{"total":10,"input":5,"output":3,"reasoning":2,'
        '"cache":{"read":0,"write":0}}}}'
    )
    raw = "\n".join((start, text, finish))
    assert ed._event_stream_has_no_model_text(raw) is False
    row = _record(tmp_path, raw)
    assert row["output_chars"] == len(raw)
    assert row["outcome"] is None
    assert cle.is_substantive(row) is True
    assert cle._reliability_category(row) == "ok"


def test_free_text_reply_is_recorded_exactly_as_before(tmp_path):
    """ADITIVO: una respuesta que no es un stream puro no cambia (fail-open)."""
    raw = 'Revision {"type": "x"} sin hallazgos'
    row = _record(tmp_path, raw)
    assert row["output_chars"] == len(raw)
    assert row["outcome"] is None


def test_mute_stream_keeps_an_explicit_outcome_override(tmp_path):
    """Un `outcome_override` explicito del caller sigue mandando; solo se mide 0."""
    row = _record(
        tmp_path, _stream(_STEP_START, _STEP_FINISH), outcome_override="falso-positivo"
    )
    assert row["outcome"] == "falso-positivo"
    assert row["output_chars"] == 0


@pytest.mark.parametrize(
    "reply",
    [
        '{"type":"review","findings":[],"verdict":"APPROVE"}',
        '{"type":"error","error":{"name":"ApiError","data":{"m":"x"}}}',
        _stream(_STEP_START, _ERROR, _STEP_FINISH),  # ciclo de vida + otro tipo
    ],
)
def test_json_replies_outside_the_lifecycle_set_are_recorded_as_before(tmp_path, reply):
    """CONTROL NEGATIVO del registrador (BA254 MAJOR): output_chars = len, sin outcome."""
    row = _record(tmp_path, reply)
    assert row["output_chars"] == len(reply)
    assert row["outcome"] is None
    assert row["failure_mode"] is None
    assert cle.is_substantive(row) is True


@pytest.mark.parametrize("override", [None, "falso-positivo"])
@pytest.mark.parametrize(
    "reply",
    [
        ed._TRANSPORT_FAILED_PREFIX + "rc=1\n" + _stream(_STEP_START, _STEP_FINISH),
        _stream(_STEP_START, _STEP_FINISH)
        + "\n"
        + ed._TRANSPORT_FAILED_PREFIX
        + "rc=1",
    ],
)
def test_a_failed_transport_next_to_a_lifecycle_stream_keeps_its_classification(
    tmp_path, reply, override
):
    """ORDEN (BA254 MINOR): el silenciado de streams no pisa al transporte fallido:
    sigue clasificando `transport_failed` y la medida cruda; un override previo manda."""
    row = _record(tmp_path, reply, outcome_override=override)
    if reply.startswith(ed._TRANSPORT_FAILED_PREFIX):
        assert row["failure_mode"].startswith("transport_failed: rc=1")
        assert row["outcome"] == (override or "no-aportacion")
    else:  # linea no JSON a continuacion: fail-open, comportamiento anterior
        assert row["failure_mode"] is None
        assert row["outcome"] == override
    assert row["output_chars"] == len(reply)
