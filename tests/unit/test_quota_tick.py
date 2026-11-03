"""Pruebas de scripts/flight/quota_tick.py (WOT-2026-153j, caja 2B).

Cada prueba lleva el numero de fila del Anexo B del plan 153h (``fila_NN``) y la mutacion que debe matarla
(N/E/Q; el arnes de mutacion vive fuera del repo). El modulo se localiza por ruta (QUOTA_TICK_UNDER_TEST
permite apuntar a una copia mutada). Nada ejecuta PowerShell ni la sonda reales salvo la prueba de integracion.
"""

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest


QT_PATH = Path(
    os.environ.get("QUOTA_TICK_UNDER_TEST")
    or Path(__file__).resolve().parents[2] / "scripts" / "flight" / "quota_tick.py"
)
WINDOWS = os.name == "nt"


def _load(name="quota_tick_ut"):
    spec = importlib.util.spec_from_file_location(name, QT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def acct(pct, stale=False, window="weekly"):
    """Una cuenta como la devuelve el monitor."""
    return {"block_pct": pct, "stale": stale, "block_window": window}


def accounts(**cuentas):
    return {"accounts": cuentas}


class Rig:
    """Un vuelo sintetico: flight-dir con roster, monitor y sonda FALSOS (subprocess.run sustituido)."""

    def __init__(self, tmp_path, monkeypatch, capsys):
        self.dir = tmp_path / "flight"
        self.dir.mkdir()
        self.monitor_path = str(tmp_path / "monitor.ps1")
        self.probe_path = str(tmp_path / "probe.py")
        self.monkeypatch = monkeypatch
        self.capsys = capsys
        for var in (
            "FLIGHT_DIR",
            "CC_USAGE_MONITOR_PS1",
            "CODEX_USAGE_PROBE",
            "CODEX_HOME",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "sysroot"))
        self.m = _load()
        self.roster({})
        self.monitor_out = json.dumps(accounts(a=acct(40), b=acct(30)))
        self.monitor_exc = None
        self.monitor_rc = 0
        self.probe_out = "PROBE-OK"
        self.probe_exc = None
        self.calls = []
        monkeypatch.setattr(self.m.subprocess, "run", self._run)

    def roster(self, quota=None, raw=None):
        """Escribe el roster (``raw`` pisa el contenido; bytes o str)."""
        p = self.dir / "flight_roster.json"
        if raw is not None:
            if isinstance(raw, bytes):
                p.write_bytes(raw)
            else:
                p.write_text(raw, encoding="utf-8")
        else:
            p.write_text(json.dumps({"quota": quota}), encoding="utf-8")

    def _run(self, cmd, **kw):
        self.calls.append((list(cmd), kw))
        if str(cmd[0]).endswith("powershell.exe"):
            if self.monitor_exc:
                raise self.monitor_exc
            return types.SimpleNamespace(
                stdout=self.monitor_out, returncode=self.monitor_rc
            )
        if self.probe_exc:
            raise self.probe_exc
        return types.SimpleNamespace(stdout=self.probe_out, returncode=0)

    def tick(self, *argv, with_tools=True, with_flight=True):
        args = []
        if with_flight:
            args += ["--flight-dir", str(self.dir)]
        if with_tools:
            args += ["--monitor", self.monitor_path, "--probe", self.probe_path]
        rc = self.m.main([*args, *argv])
        return rc, self.capsys.readouterr().out.strip()


@pytest.fixture
def rig(tmp_path, monkeypatch, capsys):
    return Rig(tmp_path, monkeypatch, capsys)


def _pct(rig, p):
    rig.monitor_out = json.dumps(accounts(a=acct(p)))
    return rig.tick()


# ------------------------------------------------------------------ D1: censo de rutas del usuario
def test_d1_censo_sin_rutas_del_usuario():
    """D1: ninguna constante del usuario en el codigo versionado."""
    import re

    src = QT_PATH.read_text(encoding="utf-8")
    prohibidas = [
        r"tmp_or8",
        r"c:[/\\]+users",
        r"\bfdl\b",
        r"co24_q",
        r"vuelo-2026",
        r"claude_tooling",
        r"\bc:[/\\]",
    ]
    assert [p for p in prohibidas if re.search(p, src, re.IGNORECASE)] == []


# ------------------------------------------------------------------ fila 129: importable
def test_fila129_importar_no_ejecuta_ni_sale(capsys):
    """Fila 129 (N95): importar el modulo no corre el tick ni lanza SystemExit."""
    mod = _load("quota_tick_import")
    assert callable(mod.main) and capsys.readouterr().out == ""


# ------------------------------------------------------------------ fila 128: roster ausente o ilegible
ROSTERS_ILEGIBLES = {
    "ausente": None,
    "vacio": b"",
    "corrupto": b"{no json",
    "lista": b"[]",
    "null": b"null",
    "quota_lista": b'{"quota": []}',
    "quota_cadena": b'{"quota": "x"}',
    "anidado": b"[" * 3000 + b"]" * 3000,
    "no_utf8": b"\xff\xfe\x00\x01",
}


@pytest.mark.parametrize("forma", sorted(ROSTERS_ILEGIBLES))
def test_fila128_roster_ausente_o_ilegible_es_no_medido_rc9(rig, forma):
    """Fila 128 (N94, E1): cualquier forma ilegible del roster = rc 9 con causa; nunca traceback."""
    if ROSTERS_ILEGIBLES[forma] is None:
        (rig.dir / "flight_roster.json").unlink()
    else:
        rig.roster(raw=ROSTERS_ILEGIBLES[forma])
    rc, out = rig.tick()
    assert (
        rc == 9 and out.startswith("QUOTA NO_MEDIDO roster:") and "Traceback" not in out
    )
    assert rig.calls == []  # sin roster no se llama al monitor


def test_fila128_roster_con_bom_se_lee(rig):
    rig.roster(
        raw=b"\xef\xbb\xbf"
        + json.dumps({"quota": {"soft_freeze_block_pct": 50}}).encode()
    )
    rc, out = _pct(rig, 55)
    assert rc == 4 and "(soft 50/hard 97)" in out


@pytest.mark.parametrize("forma", ["sin_resolver", "relativo", "ausente", "fichero"])
def test_fila128_flight_dir_invalido_es_rc9(rig, tmp_path, monkeypatch, forma):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel").mkdir()
    f = tmp_path / "unfichero"
    f.write_text("x", encoding="utf-8")
    if forma == "sin_resolver":
        rc, out = rig.tick(with_flight=False)
    else:
        raw = {"relativo": "rel", "ausente": str(tmp_path / "no"), "fichero": str(f)}[
            forma
        ]
        rc, out = rig.tick("--flight-dir", raw, with_flight=False)
    assert rc == 9 and out.startswith("QUOTA NO_MEDIDO roster: flight-dir")


@pytest.mark.skipif(not WINDOWS, reason="UNC solo existe en Windows")
def test_fila128_flight_dir_unc_es_rc9_y_no_se_consulta_la_red(rig):
    rc, out = rig.tick("--flight-dir", r"\\servidor\recurso\vuelo", with_flight=False)
    assert rc == 9 and "ruta de red (UNC)" in out and rig.calls == []


def test_fallo_interno_inesperado_es_rc9_con_causa_y_sin_traceback(rig, monkeypatch):
    def roto(_accounts):
        raise ZeroDivisionError("a proposito")

    monkeypatch.setattr(rig.m, "_measure", roto)
    rc, out = rig.tick()
    assert rc == 9
    assert out == "QUOTA NO_MEDIDO interno: ZeroDivisionError a proposito"


@pytest.mark.skipif(not WINDOWS, reason="UNC solo existe en Windows")
@pytest.mark.parametrize("ruta", [r"\\srv\r", r"\\?\UNC\srv\r\vuelo"])
def test_a7_flight_dir_unc_en_las_dos_formas_es_rc9_sin_consultar_la_red(rig, ruta):
    rc, out = rig.tick("--flight-dir", ruta, with_flight=False)
    assert rc == 9 and "ruta de red (UNC)" in out and rig.calls == []


@pytest.mark.skipif(not WINDOWS, reason="el prefijo extendido solo existe en Windows")
def test_a7_forma_local_con_prefijo_extendido_no_es_unc(rig):
    rc, out = rig.tick("--flight-dir", "\\\\?\\" + str(rig.dir), with_flight=False)
    assert rc == 0 and out.startswith("QUOTA OK")


@pytest.mark.parametrize("rc_monitor", [1, 2, 255])
def test_a3_monitor_con_json_valido_pero_rc_distinto_de_cero_es_no_medido(
    rig, rc_monitor
):
    """A3: el JSON es VALIDO (40/30 %): lo que lo invalida es el rc, no un error de parseo."""
    rig.monitor_rc = rc_monitor
    rc, out = rig.tick()
    assert rc == 9
    assert out == f"QUOTA NO_MEDIDO monitor: salio con rc {rc_monitor}"


def test_a3_el_rc_cero_sigue_midiendo(rig):
    assert rig.tick()[0] == 0


def test_la_linea_imprime_el_porcentaje_crudo_que_lee_el_detector_de_paradas(rig):
    """Contrato con flight_stall_check: un float entero se imprime 97.0 (el detector lo acepta)."""
    rc, out = _pct(rig, 97.0)
    assert rc == 5 and "a weekly 97.0%" in out


def test_fila128_flight_dir_por_entorno(rig, monkeypatch):
    monkeypatch.setenv("FLIGHT_DIR", str(rig.dir))
    rc, out = rig.tick(with_flight=False)
    assert rc == 0 and out.startswith("QUOTA OK")


def test_fila128_flight_dir_argumento_gana_al_entorno(rig, monkeypatch, tmp_path):
    """D2: argumento > entorno; un entorno invalido no tumba un argumento valido."""
    monkeypatch.setenv("FLIGHT_DIR", str(tmp_path / "no_existe"))
    rc, out = rig.tick()
    assert rc == 0 and out.startswith("QUOTA OK")


@pytest.mark.parametrize(
    "pct, estado, rc_esperado",
    [
        (89.9, "OK", 0),
        (90, "AVISO", 3),
        (91.9, "AVISO", 3),
        (92, "FREEZE", 4),
        (96.9, "FREEZE", 4),
        (97, "HARD", 5),
    ],
)
def test_fronteras_exactas_de_los_umbrales_por_defecto(rig, pct, estado, rc_esperado):
    """Cada umbral es >= (el valor justo en la frontera ya cuenta); un escalon por debajo no."""
    rc, out = _pct(rig, pct)
    assert (rc, out.split()[1]) == (rc_esperado, estado)


# ------------------------------------------------------------------ umbrales del roster (formas)
@pytest.mark.parametrize(
    "malo", ['"92"', "NaN", "Infinity", "-Infinity", "true", "0", "-5", "null", "[]"]
)
def test_umbral_invalido_cae_al_defecto_con_marca_y_nunca_baja_un_hard(rig, malo):
    """Q-O4: un umbral invalido usa 92/97 con la marca; con 99 % sigue siendo HARD (rc 5)."""
    rig.roster(
        raw='{"quota": {"soft_freeze_block_pct": '
        + malo
        + ', "hard_stop_block_pct": '
        + malo
        + "}}"
    )
    rc, out = _pct(rig, 99)
    assert rc == 5 and out.startswith(
        "QUOTA HARD (soft 92/hard 97) umbrales-roster-invalidos"
    )
    rc, out = _pct(rig, 93)
    assert rc == 4 and "umbrales-roster-invalidos" in out


def test_umbral_valido_no_lleva_marca(rig):
    rc, out = _pct(rig, 40)
    assert rc == 0 and "umbrales-roster-invalidos" not in out


def test_umbrales_invertidos_conservan_la_precedencia_hard(rig):
    """R13: soft 97 > hard 92 con 95 % = HARD (como HOY)."""
    rig.roster({"soft_freeze_block_pct": 97, "hard_stop_block_pct": 92})
    rc, out = _pct(rig, 95)
    assert rc == 5 and "(soft 97/hard 92)" in out


def test_umbral_flotante_se_imprime_tal_cual(rig):
    rig.roster({"soft_freeze_block_pct": 92.5})
    rc, out = _pct(rig, 92)
    assert rc == 3 and "(soft 92.5/hard 97)" in out


# ------------------------------------------------------------------ monitor: formas de su salida
@pytest.mark.parametrize(
    "salida",
    [
        "",
        "esto no es json",
        "[]",
        "null",
        json.dumps({"x": 1}),
        json.dumps({"accounts": {}}),
        json.dumps({"accounts": []}),
        json.dumps({"accounts": "x"}),
        json.dumps({"accounts": {"a": "x"}}),
        json.dumps({"accounts": {"a": None}}),
        "[" * 3000 + "]" * 3000,
    ],
)
def test_monitor_ilegible_o_sin_cuentas_es_no_medido(rig, salida):
    """Falsos verdes de HOY (accounts vacio daba OK) y tracebacks: todo rc 9 con causa."""
    rig.monitor_out = salida
    rc, out = rig.tick()
    assert (
        rc == 9
        and out.startswith("QUOTA NO_MEDIDO monitor:")
        and "Traceback" not in out
    )


@pytest.mark.parametrize(
    "pct",
    [None, "50", "nan", True, False, [], {}],
)
def test_porcentaje_no_numerico_es_no_medido(rig, pct):
    rc, out = _pct(rig, pct)
    assert rc == 9 and out.startswith("QUOTA NO_MEDIDO (soft")


def test_porcentaje_nan_json_es_no_medido(rig):
    """HOY: NaN daba QUOTA OK rc 0 (nan no supera ningun umbral)."""
    rig.monitor_out = '{"accounts": {"a": {"block_pct": NaN, "stale": false}}}'
    rc, out = rig.tick()
    assert rc == 9 and "nan%" in out


@pytest.mark.parametrize("crudo", ["Infinity", "1e309"])
def test_porcentaje_infinito_positivo_es_hard(rig, crudo):
    """Se conserva HOY: +inf supera el umbral duro (no se baja un HARD a NO_MEDIDO)."""
    rig.monitor_out = (
        '{"accounts": {"a": {"block_pct": ' + crudo + ', "stale": false}}}'
    )
    assert rig.tick()[0] == 5


def test_porcentaje_menos_infinito_es_no_medido(rig):
    rig.monitor_out = '{"accounts": {"a": {"block_pct": -Infinity, "stale": false}}}'
    assert rig.tick()[0] == 9


def test_porcentaje_negativo_finito_se_conserva_como_hoy(rig):
    assert _pct(rig, -5)[0] == 0


def test_stale_cualquier_valor_verdadero_es_no_medido(rig):
    for stale in (True, "false", 1, "x"):
        rig.monitor_out = json.dumps(accounts(a=acct(40, stale=stale)))
        rc, out = rig.tick()
        assert rc == 9 and " STALE" in out


def test_una_cuenta_mala_entre_buenas_es_no_medido_y_se_listan_todas(rig):
    rig.monitor_out = json.dumps(accounts(a=acct(40), b=acct(None), c=acct(30)))
    rc, out = rig.tick()
    assert (
        rc == 9
        and "a weekly 40%" in out
        and "b weekly None%" in out
        and "c weekly 30%" in out
    )


def test_el_peor_porcentaje_manda_aunque_haya_otra_cuenta_mala(rig):
    """Una cuenta mala no oculta un HARD: NO_MEDIDO prima en el estado pero la linea muestra los porcentajes."""
    rig.monitor_out = json.dumps(accounts(a=acct(99), b=acct(None)))
    rc, out = rig.tick()
    assert rc == 9 and "a weekly 99%" in out


@pytest.mark.parametrize(
    "exc",
    [
        subprocess.TimeoutExpired("monitor", 90),
        OSError("sin powershell"),
        FileNotFoundError("x"),
    ],
)
def test_monitor_que_falla_o_se_cuelga_es_no_medido(rig, exc):
    rig.monitor_exc = exc
    rc, out = rig.tick()
    assert rc == 9 and out.startswith(f"QUOTA NO_MEDIDO monitor: {type(exc).__name__}")


def test_formato_de_la_linea_es_el_que_parsean_los_latidos(rig):
    rig.monitor_out = json.dumps(
        accounts(brabander=acct(40, window="session"), alvarovans=acct(30))
    )
    rc, out = rig.tick()
    assert rc == 0
    assert (
        out
        == "QUOTA OK (soft 92/hard 97) | brabander session 40% | alvarovans weekly 30% | codex PROBE-OK"
    )


# ------------------------------------------------------------------ herramientas por entorno o argumento
def test_monitor_sin_resolver_es_rc9_con_causa(rig):
    rc, out = rig.tick(with_tools=False)
    assert (
        rc == 9
        and out.startswith("QUOTA NO_MEDIDO monitor: sin resolver")
        and rig.calls == []
    )


def test_monitor_y_sonda_por_entorno_y_argumento_gana(rig, monkeypatch):
    monkeypatch.setenv("CC_USAGE_MONITOR_PS1", "ENV_MON.ps1")
    monkeypatch.setenv("CODEX_USAGE_PROBE", "ENV_PROBE.py")
    rig.tick(with_tools=False)
    assert "ENV_MON.ps1" in rig.calls[0][0] and "ENV_PROBE.py" in rig.calls[1][0]
    rig.calls.clear()
    rig.tick()  # argumentos
    assert rig.monitor_path in rig.calls[0][0] and rig.probe_path in rig.calls[1][0]


def test_powershell_por_ruta_absoluta_de_systemroot_sin_bypass(rig, tmp_path):
    rig.tick()
    cmd, kw = rig.calls[0]
    esperado = (
        tmp_path
        / "sysroot"
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    assert cmd == [str(esperado), "-NoProfile", "-File", rig.monitor_path, "-Json"]
    assert (
        kw["timeout"] == 90 and "Bypass" not in " ".join(cmd) and cmd[0] != "powershell"
    )


def test_systemroot_ausente_es_rc9(rig, monkeypatch):
    monkeypatch.delenv("SYSTEMROOT")
    rc, out = rig.tick()
    assert rc == 9 and out.startswith("QUOTA NO_MEDIDO monitor: SystemRoot ausente")
    assert out == "QUOTA NO_MEDIDO monitor: SystemRoot ausente" and rig.calls == []


def test_sonda_sin_resolver_es_informativa_y_no_cambia_el_rc(rig):
    rc = rig.m.main(["--flight-dir", str(rig.dir), "--monitor", rig.monitor_path])
    out = rig.capsys.readouterr().out.strip()
    assert rc == 0 and out.endswith("codex NO_MEDIDO sin CODEX_USAGE_PROBE")
    assert len(rig.calls) == 1  # solo el monitor


@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired("probe", 60), OSError("x")])
def test_sonda_que_falla_no_cambia_el_rc(rig, exc):
    """Fila 127 (N93): un fallo de la sonda de codex es informativo."""
    rig.probe_exc = exc
    rc, out = rig.tick()
    assert rc == 0 and out.endswith(f"codex NO_MEDIDO {type(exc).__name__}")


def test_sonda_sin_salida_y_salida_larga_acotada(rig):
    rig.probe_out = "  \n"
    assert rig.tick()[1].endswith("codex sin salida")
    rig.probe_out = "x\ny" + "z" * 300
    out = rig.tick()[1]
    assert out.endswith("codex " + ("x y" + "z" * 300)[:110]) and "\n" not in out


def test_codex_home_defecto_entorno_y_argumento(rig, monkeypatch):
    rig.tick()
    assert rig.calls[1][0][2] == (Path.home() / ".codex").as_posix()
    monkeypatch.setenv("CODEX_HOME", "ENV_HOME")
    rig.calls.clear()
    rig.tick()
    assert rig.calls[1][0][2] == "ENV_HOME"
    rig.calls.clear()
    rig.tick("--codex-home", "ARG_HOME")
    assert rig.calls[1][0][2] == "ARG_HOME"
    assert rig.calls[1][0][0] == sys.executable


@pytest.mark.skipif(not WINDOWS, reason="PowerShell real solo en Windows")
def test_integracion_powershell_real_con_monitor_ps1_local(
    tmp_path, monkeypatch, capsys
):
    """Un .ps1 local se ejecuta por la ruta absoluta sin -ExecutionPolicy Bypass (politica CurrentUser)."""
    mon = tmp_path / "mon.ps1"
    mon.write_text(
        'param([switch]$Json)\n[Console]::Out.Write(\'{"accounts": {"a": {"block_pct": 95, "stale": false, "block_window": "weekly"}}}\')\n',
        encoding="utf-8",
    )
    flight = tmp_path / "flight"
    flight.mkdir()
    (flight / "flight_roster.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("CODEX_USAGE_PROBE", raising=False)
    rc = _load("quota_tick_real").main(
        ["--flight-dir", str(flight), "--monitor", str(mon)]
    )
    out = capsys.readouterr().out
    assert rc == 4 and "a weekly 95%" in out


# ------------------------------------------------------------------ filas 122-127 (Builder, ver abajo)
# === BUILDER 2B: filas 122-127 ===


# ---------- fila 124: borde 100 % ----------
def test_frontera_100_por_ciento_es_hard(rig):
    """Fila 124: 100 % >= 97 => HARD rc 5."""
    rc, out = _pct(rig, 100)
    assert (rc, out.split()[1]) == (5, "HARD")


# ---------- fila 126: umbrales personalizados ----------
@pytest.mark.parametrize(
    "pct, estado, rc_esperado, etiqueta",
    [
        (49, "OK", 0, "por debajo de soft"),
        (50, "FREEZE", 4, "justo en soft"),
        (55, "FREEZE", 4, "entre soft y hard"),
        (60, "HARD", 5, "justo en hard"),
        (70, "HARD", 5, "por encima de hard"),
    ],
)
def test_umbral_roster_personalizado_soft50_hard60(
    rig, pct, estado, rc_esperado, etiqueta
):
    """Fila 126 (N98): umbrales del roster (soft 50 / hard 60) cambian las fronteras; la linea imprime (soft 50/hard 60)."""
    rig.roster({"soft_freeze_block_pct": 50, "hard_stop_block_pct": 60})
    rc, out = _pct(rig, pct)
    assert (rc, out.split()[1]) == (rc_esperado, estado)
    assert "(soft 50/hard 60)" in out


# ---------- fila 127: varias cuentas, el mayor manda ----------
@pytest.mark.parametrize(
    "cuentas",
    [
        {"a": acct(30), "b": acct(55), "c": acct(70)},
        {"c": acct(70), "b": acct(55), "a": acct(30)},
        {"b": acct(55), "a": acct(30), "c": acct(70)},
    ],
)
def test_varias_cuentas_mayor_porcentaje_manda_any_order(rig, cuentas):
    """Fila 127 (N99): con varias cuentas se usa el peor porcentaje sin importar el orden de insercion; la linea lista todas separadas por ' | '."""
    # Umbrales bajos para que 70 % genere FREEZE; sin ellos 70 < 90 => OK.
    rig.roster({"soft_freeze_block_pct": 50, "hard_stop_block_pct": 60})
    rig.monitor_out = json.dumps(accounts(**cuentas))
    rc, out = rig.tick()
    # El mayor (70) da HARD rc 5 independientemente del orden
    assert rc == 5 and out.split()[1] == "HARD"
    # Todas las cuentas aparecen en la linea separadas por ' | '
    assert "a weekly 30%" in out and "b weekly 55%" in out and "c weekly 70%" in out


def test_varias_cuentas_hay_mayor_que_umbrales_y_se_muestra_ninguna_mala(rig):
    """Una cuenta mala entre buenas => NO_MEDIDO, pero worst sigue siendo el mayor de las validas."""
    rig.monitor_out = json.dumps(accounts(c=acct(80), a=acct(None), b=acct(40)))
    rc, out = rig.tick()
    assert rc == 9  # bad=True => NO_MEDIDO
    assert "c weekly 80%" in out  # worst=80 aparece
