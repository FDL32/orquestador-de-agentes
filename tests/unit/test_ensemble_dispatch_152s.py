"""WOT-2026-152s-1: watchdog POR INVOCACION de `loop-round` (`--watchdog-s`).

EL DEFECTO QUE FIJA (medido 2026-11-01, HEAD 73c78f96, backend sintetico que no
termina y lanza un nieto)
------------------------------------------------------------------------------
1. `loop-round` no tenia NINGUN limite por invocacion: solo el `timeout_s` del
   backend en agents.json (900 s kilo/opencode). Una lente colgada vivia hasta
   ese techo, con su arbol de procesos, sin que el lanzador pudiera acotarla.
2. Cuando ese timeout interno disparaba, la fila quedaba como
   `unexpected: RuntimeError...` y el rc era 2: la misma clase que cualquier
   excepcion inesperada, indistinguible de una lente muda o de un fallo de
   transporte.

QUE HACE `--watchdog-s N` (aditivo: sin la bandera no cambia ni un byte)
------------------------------------------------------------------------
El proceso que recibe la bandera NO ejecuta la ronda: relanza el mismo comando
como HIJO y espera N s. Si el hijo termina antes, su stdout/stderr/rc pasan tal
cual. Si vence, mata el ARBOL del hijo (taskkill /T /F; el supervisor y su padre
quedan fuera por construccion), escribe UNA fila `timeout:` y sale con
`EXIT_WATCHDOG_TIMEOUT` (5).

LIMITES DECLARADOS (no los absorbe este fichero)
-----------------------------------------------
- Si muere el SUPERVISOR, el hijo queda huerfano (lo cierra un Job Object: 152s-3).
- Un nieto DESACOPLADO (el hijo muere y el nieto se reparenta) sobrevive a
  `taskkill /T`: ver `test_probe_detached_grandchild_survives_taskkill_tree`.
- El timeout INTERNO (`timeout_s`) sigue registrandose como `unexpected:` (152s-2).

Los tests del arbol usan procesos REALES y son solo-Windows (taskkill). Son
hermeticos: watchdog de 3 s, limpieza en `finally` por PID registrado (nunca por
patron), y comprobacion de vida con `tasklist` (lectura independiente del codigo
bajo prueba).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ensemble_dispatch as ed  # noqa: E402


_ONLY_WINDOWS = pytest.mark.skipif(
    os.name != "nt", reason="taskkill /T /F: el arbol real solo se prueba en Windows"
)

# Hijo de prueba: lanza un NIETO que duerme, anota "pid_hijo pid_nieto", opcionalmente
# escribe UNA fila de ronda en el scorecard (como haria el hijo real) y duerme.
_SLEEPER = """\
import json, os, subprocess, sys, time
pidfile, scorecard, write_row = sys.argv[1], sys.argv[2], sys.argv[3]
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])
with open(pidfile, "w") as fh:
    fh.write(f"{os.getpid()} {grandchild.pid}")
if write_row == "1":
    os.makedirs(os.path.dirname(scorecard), exist_ok=True)
    row = {"event": "ronda", "ticket": "WOT-2026-152s", "ronda": 1,
           "backend_key": "BKA", "failure_mode": "fila-del-hijo"}
    with open(scorecard, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\\n")
time.sleep(3600)
"""


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


def _payload(tmp_path: Path) -> Path:
    p = tmp_path / "payload.txt"
    p.write_text("material publico", encoding="utf-8")
    return p


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "loop-round",
        "--profile",
        "p_chal",
        "--content-file",
        str(_payload(tmp_path)),
        "--ticket",
        "WOT-2026-152s",
        "--task-type",
        "prose",
        "--rol",
        "challenger",
        "--phase",
        "DESIGN_REVIEW",
        "--loop-id",
        "L152S",
        "--backend-key",
        "BKA",
        "--data-sensitivity",
        "public",
        "--project-root",
        str(tmp_path),
        *extra,
    ]


def _rows(project_root: Path) -> list[dict]:
    path = project_root / ed.SCORECARD_REL
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _alive(pid: int) -> bool:
    """Lectura INDEPENDIENTE de vida (tasklist), no el estado interno del codigo."""
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return f'"{pid}"' in out


def _read_pids(pidfile: Path, *, wait_s: float = 10.0) -> list[int]:
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if pidfile.exists():
            parts = pidfile.read_text().split()
            if len(parts) == 2:
                return [int(p) for p in parts]
        time.sleep(0.05)
    return []


def _patch_sleeper_child(monkeypatch, tmp_path: Path, *, write_row: bool) -> Path:
    script = tmp_path / "sleeper.py"
    script.write_text(_SLEEPER, encoding="utf-8")
    pidfile = tmp_path / "pids.txt"
    scorecard = tmp_path / ed.SCORECARD_REL
    monkeypatch.setattr(
        ed,
        "_watchdog_child_argv",
        lambda _args: [
            sys.executable,
            str(script),
            str(pidfile),
            str(scorecard),
            "1" if write_row else "0",
        ],
    )
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    return pidfile


def _cleanup(pids: list[int]) -> None:
    for pid in pids:
        ed._kill_process_tree(pid)


# --------------------------------------------------------------------------- #
# Rama 1-4: el watchdog mata el ARBOL, deja rc propio y una fila `timeout:`
# --------------------------------------------------------------------------- #


@_ONLY_WINDOWS
def test_watchdog_kills_child_and_grandchild_and_leaves_rc_and_timeout_row(
    tmp_path, monkeypatch, capsys
):
    """Hijo + nieto REALES que no terminan: a los 3 s ambos mueren, el rc es 5,
    queda UNA fila `timeout:` y el PID propio y el del padre siguen vivos.

    Mutaciones: M1 (no llamar al kill) -> procesos vivos; M2 (kill sin /T) ->
    nieto vivo; M3 (rc del hijo en vez de 5) -> rc incorrecto; M4 (failure_mode
    sin prefijo `timeout:`) -> la fila no se distingue de `unexpected:`.
    """
    pidfile = _patch_sleeper_child(monkeypatch, tmp_path, write_row=False)
    pids: list[int] = []
    try:
        t0 = time.monotonic()
        rc = ed.main(_argv(tmp_path, "--watchdog-s", "3"))
        elapsed = time.monotonic() - t0
        pids = _read_pids(pidfile)
        assert len(pids) == 2, "el hijo de prueba no llego a anotar sus PID"

        assert rc == ed.EXIT_WATCHDOG_TIMEOUT == 5
        assert rc not in (0, 1, 2, ed.EXIT_NO_CONTRIBUTION, ed.EXIT_INVALID_INPUT)
        assert 2.5 <= elapsed < 30, (
            f"el watchdog debe vencer a ~3 s, no a {elapsed:.1f}"
        )
        assert not _alive(pids[0]), "el HIJO sigue vivo tras el watchdog"
        assert not _alive(pids[1]), "el NIETO sigue vivo: kill sin arbol (/T)"
        # exclusion: el supervisor (este proceso) y su padre siguen vivos
        assert _alive(os.getpid())
        assert _alive(os.getppid())

        rows = _rows(tmp_path)
        assert len(rows) == 1, f"UNA fila `timeout:`, hay {len(rows)}"
        row = rows[0]
        assert row["event"] == "ronda"
        assert row["outcome"] == "no-aportacion"
        assert row["ticket"] == "WOT-2026-152s"
        assert row["backend_key"] == "BKA"
        assert row["ronda"] == 1
        assert row["failure_mode"].startswith("timeout:"), row["failure_mode"]
        assert "3" in row["failure_mode"], "la fila debe decir el limite que vencio"
        # kill CONFIRMADO: la fila puede afirmar `matado` y no lleva la salvedad
        assert "matado" in row["failure_mode"]
        assert "NO confirmado" not in row["failure_mode"]
        assert "NO confirmado" not in capsys.readouterr().err
    finally:
        _cleanup(pids)


@_ONLY_WINDOWS
def test_watchdog_does_not_duplicate_a_row_the_child_already_wrote(
    tmp_path, monkeypatch
):
    """Si el hijo YA escribio su fila (ticket/ronda/backend_key) desde su
    arranque, el supervisor NO escribe la `timeout:`: dos filas de la misma
    ronda inflarian el recuento de lentes. Mutacion M9 (sin dedupe) -> 2 filas."""
    pidfile = _patch_sleeper_child(monkeypatch, tmp_path, write_row=True)
    pids: list[int] = []
    try:
        rc = ed.main(_argv(tmp_path, "--watchdog-s", "3"))
        pids = _read_pids(pidfile)
        assert rc == ed.EXIT_WATCHDOG_TIMEOUT
        rows = _rows(tmp_path)
        assert [r["failure_mode"] for r in rows] == ["fila-del-hijo"], rows
        assert all(not _alive(p) for p in pids), "el arbol debe morir igualmente"
    finally:
        _cleanup(pids)


@_ONLY_WINDOWS
def test_watchdog_ignores_a_child_row_of_another_backend_key(tmp_path, monkeypatch):
    """CONTROL del dedupe: una fila de OTRA lente (otro backend_key, misma
    ticket/ronda) escrita durante la ventana NO exime: la lente colgada es esta,
    y su `timeout:` debe quedar registrada. Mutacion: dedupe por ticket+ronda
    solamente -> falta la fila `timeout:`."""
    pidfile = _patch_sleeper_child(monkeypatch, tmp_path, write_row=False)
    pids: list[int] = []
    other = tmp_path / ed.SCORECARD_REL
    other.parent.mkdir(parents=True, exist_ok=True)
    original = ed._watchdog_child_argv

    def _with_foreign_row(args):
        # la fila ajena aparece DESPUES de que el supervisor tomo su linea base
        other.write_text(
            json.dumps(
                {
                    "event": "ronda",
                    "ticket": "WOT-2026-152s",
                    "ronda": 1,
                    "backend_key": "OTRA",
                    "failure_mode": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return original(args)

    monkeypatch.setattr(ed, "_watchdog_child_argv", _with_foreign_row)
    try:
        rc = ed.main(_argv(tmp_path, "--watchdog-s", "3"))
        pids = _read_pids(pidfile)
        assert rc == ed.EXIT_WATCHDOG_TIMEOUT
        keys = [r["backend_key"] for r in _rows(tmp_path)]
        assert keys.count("BKA") == 1 and "OTRA" in keys, keys
    finally:
        _cleanup(pids)


def test_watchdog_kill_refuses_own_pid_and_parent_pid(monkeypatch):
    """Exclusion explicita: el watchdog JAMAS mata su propio PID ni el de su
    padre (el patron de un `pkill` sin partir ya mato dos shells de
    coordinadora). Mutacion M6 (la guarda deja pasar getppid) -> rojo."""
    killed: list[int] = []
    monkeypatch.setattr(ed, "_kill_process_tree", lambda pid: killed.append(pid))

    assert ed._watchdog_kill(os.getpid()) is False
    assert ed._watchdog_kill(os.getppid()) is False
    assert ed._watchdog_kill(0) is False
    assert killed == []

    assert ed._watchdog_kill(424242) is True  # CONTROL POSITIVO: un hijo ajeno SI
    assert killed == [424242]


# --------------------------------------------------------------------------- #
# Aditividad: sin bandera no cambia nada; con hijo que termina, passthrough
# --------------------------------------------------------------------------- #


def test_without_flag_no_supervisor_and_output_is_unchanged(
    tmp_path, monkeypatch, capsys
):
    """Sin `--watchdog-s` NO se crea hijo y la salida es la de siempre.
    Mutacion M7 (supervisor activo siempre) -> el supervisor se invoca y revienta."""

    def _must_not_run(*_a, **_k):
        raise AssertionError("el supervisor NO debe correr sin --watchdog-s")

    monkeypatch.setattr(ed, "_supervise_loop_round", _must_not_run)
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", lambda *a, **k: "respuesta real")

    rc = ed.main(_argv(tmp_path))

    assert rc == 0
    assert capsys.readouterr().out == "respuesta real\n"
    assert len(_rows(tmp_path)) == 1


def test_env_marker_stops_recursion_even_with_the_flag(tmp_path, monkeypatch):
    """El hijo recibe `ENSEMBLE_LOOP_ROUND_WATCHDOG_CHILD`: con ella, aunque la
    bandera siga presente, NO se vuelve a supervisar (un watchdog que relanza un
    watchdog es una fork-bomb). Mutacion M8 (sin guarda) -> el supervisor corre."""

    def _must_not_run(*_a, **_k):
        raise AssertionError("recursion: el hijo no debe supervisar otra vez")

    monkeypatch.setattr(ed, "_supervise_loop_round", _must_not_run)
    monkeypatch.setenv(ed.WATCHDOG_CHILD_ENV, "1")
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", lambda *a, **k: "respuesta real")

    assert ed.WATCHDOG_CHILD_ENV == "ENSEMBLE_LOOP_ROUND_WATCHDOG_CHILD"
    assert ed.main(_argv(tmp_path, "--watchdog-s", "3")) == 0
    assert len(_rows(tmp_path)) == 1


@pytest.mark.parametrize("child_rc", [0, 3, 4])
def test_child_that_finishes_in_time_passes_through_rc_and_streams(
    tmp_path, monkeypatch, capfd, child_rc
):
    """El hijo termina antes del limite: stdout, stderr y rc pasan TAL CUAL, el
    hijo recibe el marcador anti-recursion y el supervisor NO escribe fila."""
    code = (
        "import os, sys;"
        f"print('SALIDA-HIJO env=' + os.environ.get('{ed.WATCHDOG_CHILD_ENV}', 'AUSENTE'));"
        "print('ERROR-HIJO', file=sys.stderr);"
        f"sys.exit({child_rc})"
    )
    monkeypatch.setattr(
        ed, "_watchdog_child_argv", lambda _a: [sys.executable, "-c", code]
    )
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())

    rc = ed.main(_argv(tmp_path, "--watchdog-s", "30"))

    captured = capfd.readouterr()
    assert rc == child_rc
    assert "SALIDA-HIJO env=1" in captured.out
    assert "ERROR-HIJO" in captured.err
    assert _rows(tmp_path) == [], "el supervisor no escribe fila si el hijo termino"


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "nan", "inf", "-inf"])
def test_invalid_watchdog_value_is_rejected_by_argparse_before_any_child(
    tmp_path, monkeypatch, capsys, bad
):
    """`--watchdog-s` <= 0 o no numerico lo rechaza el PARSER (SystemExit 2 con el
    mensaje del argumento), nunca un limite de 0 s que mata la ronda al nacer.
    Mutacion M11 (aceptar <= 0) -> `main` ya no lanza SystemExit."""

    def _must_not_spawn(_a):
        raise AssertionError("no debe lanzarse ningun hijo con un limite invalido")

    monkeypatch.setattr(ed, "_watchdog_child_argv", _must_not_spawn)
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())

    with pytest.raises(SystemExit) as exc_info:
        ed.main(_argv(tmp_path, "--watchdog-s", bad))

    assert exc_info.value.code == 2
    assert "--watchdog-s" in capsys.readouterr().err
    assert _rows(tmp_path) == []


def test_child_argv_reproduces_every_option_and_drops_only_the_watchdog(
    tmp_path, monkeypatch
):
    """El comando del hijo conserva TODAS las opciones del padre (incluidas las
    opcionales presentes) y solo omite `--watchdog-s`; arranca con el mismo
    interprete y este mismo script."""
    captured: dict = {}

    def _spy(args, config):
        captured["args"] = args
        return 0

    monkeypatch.setattr(ed, "_supervise_loop_round", _spy)
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    extra = [
        "--watchdog-s",
        "7",
        "--ronda",
        "2",
        "--context-kind",
        "diff",
        "--session-id",
        "S152",
    ]
    argv = _argv(tmp_path, *extra)
    assert ed.main(argv) == 0

    cmd = ed._watchdog_child_argv(captured["args"])

    assert cmd[0] == sys.executable
    assert Path(cmd[1]).resolve() == Path(ed.__file__).resolve()
    assert cmd[2] == "loop-round"
    assert "--watchdog-s" not in cmd and "7" not in cmd
    flags = {cmd[i]: cmd[i + 1] for i in range(3, len(cmd), 2)}
    expected = {argv[i]: argv[i + 1] for i in range(1, len(argv), 2)}
    expected.pop("--watchdog-s")
    assert flags == expected


# --------------------------------------------------------------------------- #
# SONDA MEDIDA (no se corrige): el limite del taskkill /T
# --------------------------------------------------------------------------- #

_DETACHER = """\
import os, subprocess, sys, time
pidfile = sys.argv[1]
# nieto DESACOPLADO: lo lanza un intermedio que muere enseguida -> el nieto queda
# reparentado y ya no cuelga del arbol que taskkill /T recorre desde la raiz.
launcher = (
    "import subprocess, sys;"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)']);"
    "open(sys.argv[1], 'w').write(str(p.pid))"
)
subprocess.Popen([sys.executable, "-c", launcher, pidfile]).wait()
time.sleep(3600)
"""


@_ONLY_WINDOWS
def test_probe_detached_grandchild_survives_taskkill_tree(tmp_path):
    """SONDA (H143, LIMITE DECLARADO de 152s-1, no se corrige aqui): un nieto
    cuyo padre intermedio YA murio escapa a `taskkill /T /F` sobre la raiz. Este
    test FIJA el comportamiento medido para que nadie lo de por resuelto: si
    algun dia falla porque el nieto muere, el LIMITE de ALCANCE DECLARADO ha
    caducado y hay que reescribirlo (el cierre real es un Job Object, 152s-3)."""
    script = tmp_path / "detacher.py"
    script.write_text(_DETACHER, encoding="utf-8")
    pidfile = tmp_path / "orphan_pid.txt"
    root = subprocess.Popen([sys.executable, str(script), str(pidfile)])
    orphan_pid = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (
            pidfile.exists() and pidfile.read_text().strip()
        ):
            time.sleep(0.05)
        orphan_pid = int(pidfile.read_text().strip())
        assert _alive(orphan_pid), "control positivo: el nieto esta vivo antes del kill"

        ed._kill_process_tree(root.pid)
        root.wait(timeout=10)

        assert not _alive(root.pid), "la raiz debe morir"
        assert _alive(orphan_pid), (
            "SONDA: el nieto desacoplado SOBREVIVE a taskkill /T (limite medido)"
        )
    finally:
        if orphan_pid is not None:
            ed._kill_process_tree(orphan_pid)
        ed._kill_process_tree(root.pid)


def test_child_marker_does_not_skip_privacy_preflight(tmp_path, monkeypatch, capsys):
    """EVIDENCIA de la exencion 046c de `_supervise_loop_round`: el HIJO (con
    `ENSEMBLE_LOOP_ROUND_WATCHDOG_CHILD`) sigue pasando por `privacy_preflight`
    ANTES de cualquier salida. El marcador solo se lee en el gate de
    `_cmd_loop_round` (ensemble_dispatch.py: `_watchdog_requested(args) and not
    os.environ.get(WATCHDOG_CHILD_ENV)`); la salida a backend es
    `send_to_profile` -> `privacy_preflight(...)` -> `transport(...)`.

    Un payload `private` hacia un backend sin `trusted: true` debe quedar
    BLOQUEADO (rc 1, fila `privacy_preflight_blocked`) sin llamar al transporte.
    CONTROL POSITIVO: con `public` el MISMO camino SI llega al transporte (el
    espia esta cableado), y sin el marcador el resultado es identico.
    """
    sent: list[str] = []

    def _spy(_profile, _backend_cfg, _messages, _timeout):
        sent.append("salio-a-backend")
        return "respuesta real"

    monkeypatch.setattr(ed, "_transport_api", _spy)
    monkeypatch.setattr(ed, "_transport_agent", _spy)
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setenv(ed.WATCHDOG_CHILD_ENV, "1")

    argv = _argv(tmp_path, "--watchdog-s", "30")
    private_argv = [("private" if a == "public" else a) for a in argv]
    assert ed.main(private_argv) == 1
    assert "[BLOCKED]" in capsys.readouterr().err
    assert sent == [], "el marcador de hijo NO puede saltarse el preflight"
    assert _rows(tmp_path)[-1]["failure_mode"].startswith("privacy_preflight_blocked")

    assert ed.main(argv) == 0  # control positivo: public si sale
    assert sent == ["salio-a-backend"]


# --------------------------------------------------------------------------- #
# Ronda 2 (WOT-2026-152s): la fila y el stderr NO afirman `matado` sin confirmarlo
# --------------------------------------------------------------------------- #


def _raises_oserror(_pid):
    raise OSError("taskkill no disponible")


@_ONLY_WINDOWS
@pytest.mark.parametrize(
    "fake_kill",
    [lambda _pid: None, _raises_oserror],
    ids=["kill_no_op", "kill_lanza_oserror"],
)
def test_unconfirmed_kill_is_not_reported_as_killed(
    tmp_path, monkeypatch, capsys, fake_kill
):
    """Si el kill NO se confirma (el hijo REAL sigue vivo tras la espera), la fila
    `timeout:` y el stderr lo dicen: `kill NO confirmado; el hijo (pid N) puede
    seguir vivo`. Una fila que afirma `matado` con el hijo vivo es una fila falsa
    en una ficha cuyo defecto es 'un proceso sobrevive'. Mantiene el prefijo
    `timeout:` y el rc 5. Mutacion M16 (afirmar siempre `matado`) -> rojo."""
    pidfile = _patch_sleeper_child(monkeypatch, tmp_path, write_row=False)
    real_kill = ed._kill_process_tree
    monkeypatch.setattr(ed, "_kill_process_tree", fake_kill)
    monkeypatch.setattr(ed, "WATCHDOG_KILL_CONFIRM_S", 0.5)
    pids: list[int] = []
    try:
        rc = ed.main(_argv(tmp_path, "--watchdog-s", "2"))
        pids = _read_pids(pidfile)
        assert rc == ed.EXIT_WATCHDOG_TIMEOUT
        assert pids and _alive(pids[0]), "premisa: el hijo REAL sigue vivo"

        failure_mode = _rows(tmp_path)[-1]["failure_mode"]
        assert failure_mode.startswith("timeout:")
        assert "kill NO confirmado" in failure_mode
        # el pid de la fila es el del Popen del supervisor (en un venv de Windows el
        # `python.exe` es un lanzador: no coincide con el pid que anota el script)
        assert re.search(r"\(pid \d+\) puede seguir vivo", failure_mode)
        assert "puede seguir vivo" in failure_mode
        assert "matado" not in failure_mode
        err = capsys.readouterr().err
        assert "kill NO confirmado" in err and "puede seguir vivo" in err
        assert "matado;" not in err
    finally:
        for pid in pids:
            real_kill(pid)


# --------------------------------------------------------------------------- #
# Ronda 2: el dedupe es FAIL-OPEN hacia registrar (decision medida, no accidente)
# --------------------------------------------------------------------------- #


@_ONLY_WINDOWS
@pytest.mark.parametrize(
    ("before", "after"),
    [(None, None), (0, None), (None, 1)],
    ids=["ambos_ilegibles", "despues_ilegible", "antes_ilegible"],
)
def test_dedupe_fails_open_to_recording_when_the_scorecard_is_unreadable(
    tmp_path, monkeypatch, before, after
):
    """Si el recuento de filas no se puede leer (rotacion concurrente, linea
    ilegible) el supervisor ESCRIBE la fila `timeout:` igualmente: un duplicado es
    un defecto menor y una ronda sin rastro es el que este ticket cierra. Decision
    deliberada y documentada en `_count_round_rows`; este test la fija.
    Mutacion M17 (fail-closed: no escribir si no se puede comparar) -> rojo."""
    pidfile = _patch_sleeper_child(monkeypatch, tmp_path, write_row=False)
    counts = iter([before, after])
    monkeypatch.setattr(ed, "_count_round_rows", lambda *_a, **_k: next(counts))
    pids: list[int] = []
    try:
        assert ed.main(_argv(tmp_path, "--watchdog-s", "2")) == ed.EXIT_WATCHDOG_TIMEOUT
        pids = _read_pids(pidfile)
        rows = _rows(tmp_path)
        assert len(rows) == 1 and rows[0]["failure_mode"].startswith("timeout:")
    finally:
        _cleanup(pids)


@_ONLY_WINDOWS
def test_dedupe_still_skips_when_both_counts_are_readable_and_grew(
    tmp_path, monkeypatch
):
    """CONTROL POSITIVO del fail-open: con AMBOS recuentos legibles y mas filas
    despues (0 -> 1) el supervisor NO escribe: el hijo ya registro su ronda."""
    pidfile = _patch_sleeper_child(monkeypatch, tmp_path, write_row=False)
    counts = iter([0, 1])
    monkeypatch.setattr(ed, "_count_round_rows", lambda *_a, **_k: next(counts))
    pids: list[int] = []
    try:
        assert ed.main(_argv(tmp_path, "--watchdog-s", "2")) == ed.EXIT_WATCHDOG_TIMEOUT
        pids = _read_pids(pidfile)
        assert _rows(tmp_path) == []
    finally:
        _cleanup(pids)


# --------------------------------------------------------------------------- #
# Ronda 2 (adenda CO-19): huecos de test cerrados, cada uno con su mutacion
# --------------------------------------------------------------------------- #


def test_child_argv_forwards_commit_sha_and_challenge_nonce(tmp_path, monkeypatch):
    """El hijo recibe `--commit-sha` y `--challenge-nonce` CON sus valores. Sin
    ellos la ronda supervisada pierde su traza de cierre y `check_loop_execution`
    no la acredita, y nadie lo veria. Mutacion M17 (el argv los pierde) -> rojo."""
    captured: dict = {}

    def _spy(args, config):
        captured["args"] = args
        return 0

    monkeypatch.setattr(ed, "_supervise_loop_round", _spy)
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    sha = "0123456789abcdef0123456789abcdef01234567"
    nonce = "NONCE-152S-A"
    argv = _argv(
        tmp_path,
        "--watchdog-s",
        "7",
        "--commit-sha",
        sha,
        "--challenge-nonce",
        nonce,
    )
    assert ed.main(argv) == 0

    cmd = ed._watchdog_child_argv(captured["args"])

    flags = {cmd[i]: cmd[i + 1] for i in range(3, len(cmd), 2)}
    assert flags["--commit-sha"] == sha
    assert flags["--challenge-nonce"] == nonce


@_ONLY_WINDOWS
def test_stale_row_of_the_same_key_does_not_suppress_the_timeout_row(
    tmp_path, monkeypatch
):
    """El dedupe mira filas NUEVAS desde el arranque del hijo, no cualquier fila de
    la misma clave: una fila ANTIGUA (ticket/ronda/backend_key) no puede suprimir la
    fila `timeout:` de esta ejecucion. Mutacion M18 (`rows_after > 0` en vez de
    `rows_after > rows_before`) -> la fila `timeout:` desaparece."""
    pidfile = _patch_sleeper_child(monkeypatch, tmp_path, write_row=False)
    scorecard = tmp_path / ed.SCORECARD_REL
    scorecard.parent.mkdir(parents=True, exist_ok=True)
    scorecard.write_text(
        json.dumps(
            {
                "event": "ronda",
                "ticket": "WOT-2026-152s",
                "ronda": 1,
                "backend_key": "BKA",
                "failure_mode": "fila-antigua",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    pids: list[int] = []
    try:
        assert ed.main(_argv(tmp_path, "--watchdog-s", "2")) == ed.EXIT_WATCHDOG_TIMEOUT
        pids = _read_pids(pidfile)
        modes = [r["failure_mode"] for r in _rows(tmp_path)]
        assert len(modes) == 2 and modes[0] == "fila-antigua", modes
        assert modes[1].startswith("timeout:"), modes
    finally:
        _cleanup(pids)


def test_namespace_without_watchdog_attribute_is_treated_as_off():
    """Los callers Python (tests, bucles por import) que arman un Namespace SIN
    `watchdog_s` no deben romperse: ausente == apagado."""
    assert ed._watchdog_requested(SimpleNamespace()) is False
    assert ed._watchdog_requested(SimpleNamespace(watchdog_s=None)) is False
    assert ed._watchdog_requested(SimpleNamespace(watchdog_s=3.0)) is True
