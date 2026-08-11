"""WOT-2026-054j: el charmap del PROCESO PADRE se come la respuesta del modelo.

POR QUE UN FICHERO PROPIO Y NO `test_ensemble_dispatch.py`: aquel declara un
invariante ESTRUCTURAL (`test_no_env_or_transport_leakage_in_025z_test_section`)
que prohibe los tokens `os.environ` y `send_to_profile` en todo el texto
posterior a `_WOT_025Z_SECTION_MARKER` -- es decir, hasta el final del fichero.
Esos dos tokens son IMPRESCINDIBLES aqui: el fallo solo se reproduce lanzando el
subcomando REAL en un subproceso cuyo entorno se ha limpiado a mano. Meterlos
alli habria roto un invariante ajeno al ticket; el precedente de fichero hermano
por ticket ya existe (`test_ensemble_dispatch_027s.py`).

EL FALLO QUE FIJA
-----------------
`_cmd_loop_round` termina con `print(reply)`. En Windows el stdout heredado es
`cp1252` (medido: `sys.stdout.encoding` -> `cp1252`), asi que una respuesta con
un caracter no representable -- flecha U+2192, subconjunto U+2286 -- revienta al
imprimirse y el subcomando sale con rc=1.

LO QUE NO SE PIERDE, Y LA FICHA DECIA QUE SI: la fila del scorecard YA ESTA
ESCRITA cuando el `print` falla. `run_loop_round` llama a `_record_round` y solo
DESPUES retorna; el `print` vive en el handler. Lo que se pierde es la SALIDA
hacia el orquestador y el rc -- la fila queda, pero MUDA (`outcome: None`,
`failure_mode: None`), indistinguible de una ronda normal. Por eso el sintoma se
lee como "la lente no tenia objeciones" cuando en realidad nadie la escucho.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


_ARROW = "→"  # el caracter medido en las caidas reales
_SUBSET = "⊆"
_REPLY_NON_ASCII = f"veredicto: A {_ARROW} B, y A {_SUBSET} B"


def _config() -> dict:
    """Config minima valida; mismo molde hermetico que el fichero hermano."""
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


_DRIVER = """\
import json, sys
sys.path.insert(0, {scripts_dir!r})
import ensemble_dispatch as ed

cfg = json.loads(open({cfg_path!r}, encoding="utf-8").read())
reply = open({reply_path!r}, encoding="utf-8").read()

# Recibo ANTES de tocar nada: prueba que el stdout heredado NO era utf-8, que es
# la condicion sin la cual este test no mide lo que promete.
sys.stderr.write("RECIBO stdout.encoding=%s\\n" % sys.stdout.encoding)

ed.load_motor_config = lambda: cfg
ed.send_to_profile = lambda *a, **k: reply
if not {apply_fix!r}:
    # MUTACION: anula el fix y SOLO el fix. Todo lo demas queda identico, asi que
    # el veredicto depende exclusivamente de esta rama.
    ed._force_utf8_stdio = lambda: None

sys.exit(ed.main([
    "loop-round",
    "--profile", "p_chal",
    "--content-file", {payload_path!r},
    "--ticket", "WOT-2026-054j",
    "--task-type", "contract-audit",
    "--rol", "challenger",
    "--phase", "CONTRACT_AUDIT",
    "--loop-id", "L054J",
    "--backend-key", "BKA",
    "--data-sensitivity", "public",
    "--project-root", {project_root!r},
]))
"""


def _run_dispatcher_subprocess(tmp_path: Path, *, apply_fix: bool):
    """Ejecuta `loop-round` en un SUBPROCESO REAL, sin `PYTHONIOENCODING`.

    Before: `tmp_path` es un directorio vacio; `apply_fix` decide si
        `_force_utf8_stdio` conserva su cuerpo o se anula.
    During: materializa config, respuesta y driver; lanza el subcomando con el
        entorno heredado MENOS `PYTHONIOENCODING`. Sin red: `send_to_profile`
        queda stubeado dentro del driver.
    After: devuelve el `CompletedProcess`. El rc se lee de `returncode`, nunca
        de `$?` tras un pipe.

    POR QUE SUBPROCESO Y NO `ed.main()` EN-PROCESO: bajo pytest `sys.stdout` es
    un objeto de captura sin `reconfigure`, asi que el fix seria un no-op y el
    test daria VERDE SIN PROBAR NADA. El fallo real vive en un proceso cuyo
    stdout lo fija el sistema.

    POR QUE SE LIMPIA `PYTHONIOENCODING`: si el runner de la suite la lleva
    puesta, el hijo la hereda, el stdout nace en utf-8 y la mitad ROJA del par
    pasaria en verde. Es un falso verde perfecto, y esta linea es lo unico que
    lo impide.
    """
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(_config()), encoding="utf-8")
    reply_path = tmp_path / "reply.txt"
    reply_path.write_text(_REPLY_NON_ASCII, encoding="utf-8")
    payload_path = tmp_path / "payload.txt"
    payload_path.write_text("material publico", encoding="utf-8")
    driver = tmp_path / "driver.py"
    driver.write_text(
        _DRIVER.format(
            scripts_dir=str(_SCRIPTS_DIR),
            cfg_path=str(cfg_path),
            reply_path=str(reply_path),
            payload_path=str(payload_path),
            project_root=str(tmp_path),
            apply_fix=apply_fix,
        ),
        encoding="utf-8",
    )

    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    return subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _inherited_encoding(proc) -> str:
    """Lee el encoding heredado del RECIBO del driver, no de una suposicion."""
    recibo = [ln for ln in proc.stderr.splitlines() if ln.startswith("RECIBO ")]
    assert recibo, f"el driver no dejo recibo; stderr={proc.stderr[-400:]}"
    return recibo[0].split("=", 1)[1].strip().lower()


def test_non_ascii_reply_survives_the_dispatcher_stdout(tmp_path):
    """CON el fix: una respuesta con U+2192 se imprime ENTERA y rc=0.

    Mitad VERDE del par de mutacion del DoD (b).

    La asercion sobre el contenido no es decorativa: el NON-GOAL del ticket
    prohibe sanear la respuesta a ASCII, asi que un fix que "arreglara" el rc
    imprimiendo `?` cumpliria el exit code y ROMPERIA el contrato. Por eso se
    exige el caracter original, no solo el rc.
    """
    proc = _run_dispatcher_subprocess(tmp_path, apply_fix=True)

    _inherited_encoding(proc)  # falla si no hay recibo
    assert proc.returncode == 0, (
        f"con el fix el subcomando debe salir 0; stderr={proc.stderr[-400:]}"
    )
    assert _ARROW in proc.stdout and _SUBSET in proc.stdout, (
        "la respuesta debe llegar INTACTA (el non-goal prohibe sanear a ASCII); "
        f"stdout={proc.stdout[:200]!r}"
    )


def test_non_ascii_reply_dies_without_the_fix(tmp_path):
    """SIN el fix: la MISMA respuesta mata la ronda con rc != 0.

    Mitad ROJA del par. La mutacion anula UNICAMENTE `_force_utf8_stdio`: si
    este test pasara a verde, significaria que el fix dejo de ser lo que decide
    el veredicto -- exactamente el falso verde que la barrera existe para
    impedir.

    SKIP cuando el stdout heredado ya es utf-8 (Linux/macOS, o Windows con
    UTF-8 mode): alli el bug no es reproducible y un fallo no diria nada sobre
    el fix. La condicion se lee del RECIBO del driver, no de `sys.platform`.
    """
    proc = _run_dispatcher_subprocess(tmp_path, apply_fix=False)

    encoding = _inherited_encoding(proc)
    if encoding.replace("-", "") in {"utf8", "utf8mb4"}:
        pytest.skip(
            f"stdout heredado ya es {encoding}: el charmap no es reproducible "
            "aqui, asi que la mitad roja del par no aplica"
        )

    assert proc.returncode != 0, (
        "SIN el fix la ronda DEBE morir: si sale 0, el fix ya no es lo que "
        f"decide el veredicto. stdout={proc.stdout[:200]!r}"
    )
    assert "UnicodeEncodeError" in proc.stderr or "charmap" in proc.stderr, (
        "debe morir por el charmap concreto que ficha el ticket, no por otra "
        f"causa. stderr={proc.stderr[-400:]}"
    )


def test_ascii_reply_unaffected_by_the_fix(tmp_path):
    """CONTROL NEGATIVO del DoD (c): el camino ASCII no cambia.

    Sin este control, un fix que rompiera las respuestas normales pasaria los
    dos tests de arriba sin que nadie lo notara.
    """
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(_config()), encoding="utf-8")
    reply_path = tmp_path / "reply.txt"
    reply_path.write_text("veredicto ASCII sin adornos", encoding="utf-8")
    payload_path = tmp_path / "payload.txt"
    payload_path.write_text("material publico", encoding="utf-8")
    driver = tmp_path / "driver.py"
    driver.write_text(
        _DRIVER.format(
            scripts_dir=str(_SCRIPTS_DIR),
            cfg_path=str(cfg_path),
            reply_path=str(reply_path),
            payload_path=str(payload_path),
            project_root=str(tmp_path),
            apply_fix=True,
        ),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    proc = subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    assert proc.returncode == 0, f"ASCII debe seguir saliendo 0; {proc.stderr[-300:]}"
    assert "veredicto ASCII sin adornos" in proc.stdout


def test_force_utf8_stdio_is_idempotent_and_guards_streams_without_reconfigure():
    """`_force_utf8_stdio` no explota cuando el stream no es reconfigurable.

    La guarda `hasattr` NO es decorativa: bajo captura de pytest `sys.stdout` es
    un objeto tipo `io.StringIO`, que carece de `reconfigure`. Mutation: quitar
    la guarda y llamar a esta funcion bajo captura -> AttributeError.

    Se ejerce dos veces para fijar la idempotencia declarada en el docstring.
    """
    import io

    import ensemble_dispatch as ed

    original_out, original_err = sys.stdout, sys.stderr
    try:
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        assert not hasattr(sys.stdout, "reconfigure"), (
            "premisa del test: StringIO no expone reconfigure; si lo hiciera, "
            "este test dejaria de cubrir la rama de la guarda"
        )
        ed._force_utf8_stdio()
        ed._force_utf8_stdio()
    finally:
        sys.stdout, sys.stderr = original_out, original_err
