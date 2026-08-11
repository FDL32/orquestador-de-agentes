"""WOT-2026-048x: la ronda que muere por TRANSPORTE debe dejar fila auditable.

EL FALLO QUE FIJA
-----------------
`run_loop_round` registra la fila DESPUES de que el backend responda. Si el
transporte lanza -- `TransportError` por HTTP 524, por ejemplo -- la excepcion
sube por encima de `_record_round` y la ronda NO deja NINGUNA fila. En el
scorecard, "nadie consulto a esta lente" y "la lente no llego a responder" son
entonces indistinguibles, y el silencio se lee como acuerdo.

MEDIDO 2026-08-11 en los bucles L1100/L1102 de la sesion que implanto esto: 12
rondas lanzadas, 8 registradas. Las 4 caidas (HTTP 524) no dejaron rastro, asi
que la cobertura efectiva del bucle era INCOMPUTABLE desde su propio artefacto.

POR QUE `_record_round` NO BASTABA
----------------------------------
Ya clasifica `transport_failed`, pero SOLO cuando el transporte DEVUELVE texto
marcado con `_TRANSPORT_FAILED_PREFIX` -- la ruta del canal `agent`. El canal
`api` LANZA la excepcion, que nunca llega al registrador. Ese es el hueco.

POR QUE EL EXIT CODE NO PUEDE DECIDIR ESTOS TESTS
-------------------------------------------------
El rc ya era 2 antes del fix y sigue siendo 2 despues: el fix es ADITIVO (la
fila) y no toca el contrato de salida. Un test que aseverara el rc pasaria en
verde con y sin el fix. Por eso TODAS las aserciones de abajo son sobre la FILA.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ensemble_dispatch as ed  # noqa: E402


def _config() -> dict:
    return {
        "schema_version": "1.3",
        "backends": {
            "fake": {"executable": "", "args": [], "discovery": {"method": "path_only"}}
        },
        "ensemble_profiles": {
            "p_chal": {
                "backend": "fake",
                "channel": "api",
                "model": "m2",
                "api_base_url": "https://fake.example/v1/chat/completions",
                "api_key_env": "FAKE_API_KEY",
                "data_sensitivity": "public",
                "write": False,
            }
        },
        "ensemble_pipelines": {},
        "ensemble_private_roots": [],
    }


def _rows(project_root: Path) -> list[dict]:
    path = project_root / ed.SCORECARD_REL
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _argv(tmp_path: Path, payload: Path) -> list[str]:
    return [
        "loop-round",
        "--profile",
        "p_chal",
        "--content-file",
        str(payload),
        "--ticket",
        "WOT-2026-048x",
        "--task-type",
        "contract-audit",
        "--rol",
        "challenger",
        "--phase",
        "CONTRACT_AUDIT",
        "--loop-id",
        "L048X",
        "--backend-key",
        "BKA",
        "--data-sensitivity",
        "public",
        "--project-root",
        str(tmp_path),
    ]


def _payload(tmp_path: Path) -> Path:
    p = tmp_path / "payload.txt"
    p.write_text("material publico", encoding="utf-8")
    return p


def test_transport_error_leaves_auditable_row(tmp_path, monkeypatch):
    """Una `TransportError` (HTTP 524) deja UNA fila con `failure_mode`.

    MUTATION que aisla la rama: quitar el `try/except` alrededor de
    `run_loop_round` en `_cmd_loop_round` -> la excepcion sube sin registrar y
    `len(rows) == 0`, con el rc SIN cambiar (sigue siendo 2). Es decir: este
    test NO puede pasar por el exit code, solo por la fila.
    """

    def _boom(*_a, **_k):
        raise ed.TransportError(
            "HTTPError | HTTP 524 | HTTP Error 524: <none>",
            status=524,
            body="error code: 524",
        )

    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", _boom)

    rc = ed.main(_argv(tmp_path, _payload(tmp_path)))

    rows = _rows(tmp_path)
    assert len(rows) == 1, (
        "la ronda caida por transporte DEBE dejar exactamente una fila; sin ella "
        "'nadie consulto' y 'no llego a responder' son indistinguibles"
    )
    row = rows[0]
    assert row["failure_mode"], "la fila debe declarar POR QUE murio la ronda"
    assert "TransportError" in row["failure_mode"]
    assert "524" in row["failure_mode"], (
        "el failure_mode debe conservar la causa concreta, no un generico"
    )
    assert row["outcome"] == "no-aportacion", (
        "una ronda que no respondio no es una aportacion vacia: es no-aportacion"
    )
    assert row["output_chars"] == 0
    # Atribuible: sin estos campos la fila no se puede cruzar con el bucle.
    assert row["loop_id"] == "L048X"
    assert row["backend_key"] == "BKA"
    assert row["ticket"] == "WOT-2026-048x"
    assert rc == 2, "el contrato de salida NO cambia: la fila es aditiva"


def test_privacy_block_leaves_no_row_at_all(tmp_path, monkeypatch):
    """CONTROL NEGATIVO: un bloqueo del preflight NO debe dejar fila.

    `run_loop_round` declara en su docstring que ante `DispatchBlockedError`
    "NO hay fila, porque no hubo ronda" -- el payload nunca salio. Registrarla
    inventaria una ronda inexistente e inflaria la cobertura del bucle con una
    lente que jamas se consulto.

    Mutation: capturar `DispatchBlockedError` en el mismo `except` generico que
    las de transporte -> aparece una fila y este test cae.
    """
    cfg = _config()
    cfg["ensemble_profiles"]["p_chal"]["data_sensitivity"] = "private"
    monkeypatch.setattr(ed, "load_motor_config", lambda: cfg)

    payload = _payload(tmp_path)
    argv = _argv(tmp_path, payload)
    argv[argv.index("--data-sensitivity") + 1] = "private"

    rc = ed.main(argv)

    assert rc == 1, "un bloqueo del preflight sale por la rama [BLOCKED] (exit 1)"
    assert _rows(tmp_path) == [], (
        "un payload que NUNCA salio no puede dejar fila: seria inventar una ronda"
    )


def test_successful_round_is_unaffected(tmp_path, monkeypatch):
    """CONTROL POSITIVO: la ronda que SI responde no cambia de comportamiento.

    Sin este control, un fix que marcara toda ronda como fallida pasaria el
    primer test sin que nadie lo notara.
    """
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", lambda *a, **k: "veredicto: APPROVE")

    rc = ed.main(_argv(tmp_path, _payload(tmp_path)))

    rows = _rows(tmp_path)
    assert rc == 0 and len(rows) == 1
    assert rows[0]["failure_mode"] is None, (
        "una ronda sana NO lleva failure_mode; si lo llevara, el campo dejaria "
        "de discriminar y volveriamos al problema que este ticket cierra"
    )
    assert rows[0]["output_chars"] == len("veredicto: APPROVE")


@pytest.mark.parametrize(
    ("exc", "clase_esperada"),
    [
        (
            ed.TransportError("HTTP 524", status=524, body="error code: 524"),
            "transport_failed",
        ),
        (
            OSError("[WinError 206] El nombre del archivo es demasiado largo"),
            "transport_failed",
        ),
        (KeyError("perfil_inexistente"), "unexpected"),
        (TypeError("argumento de tipo equivocado"), "unexpected"),
    ],
)
def test_row_survives_any_failure_but_the_label_is_precise(
    tmp_path, monkeypatch, exc, clase_esperada
):
    """La fila sobrevive a CUALQUIER fallo, pero la ETIQUETA no miente.

    Dos propiedades distintas, y hacen falta las dos:

    - ANCHURA: ninguna excepcion puede dejar la ronda sin rastro. La ficha nacio
      del `WinError 206` y la evidencia que la cerro fue un `HTTP 524`: causas
      distintas del MISMO defecto, asi que el rastro no puede depender de
      acertar el tipo.
    - PRECISION: un `KeyError` NO es un fallo de transporte. Etiquetarlo asi
      manda a buscar una caida de red donde hay un bug de programacion, y en un
      ticket cuyo proposito es hacer FIABLE el registro, clasificar mal es peor
      que no registrar.

    Adjudicado por el bucle L1104: el lector-FS defendio la anchura y BA14 ataco
    la etiqueta. Ambos tenian razon; este test fija las dos a la vez.

    Mutation: volver a `failure_mode=f"transport_failed: ..."` fijo -> los dos
    casos `unexpected` caen. Estrechar el `except` a `TransportError` -> los
    casos `KeyError`/`TypeError` pierden la fila y caen por `len(rows) == 1`.
    """

    def _boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", _boom)

    ed.main(_argv(tmp_path, _payload(tmp_path)))

    rows = _rows(tmp_path)
    assert len(rows) == 1, f"{type(exc).__name__} debe dejar fila igualmente"
    failure_mode = rows[0]["failure_mode"]
    assert type(exc).__name__ in failure_mode
    assert failure_mode.startswith(clase_esperada), (
        f"{type(exc).__name__} debe clasificarse como '{clase_esperada}', no como "
        f"'{failure_mode.split(':')[0]}': una fila de auditoria mal clasificada "
        "manda a investigar la causa equivocada"
    )
