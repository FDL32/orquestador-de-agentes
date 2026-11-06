"""Pruebas de scripts/flight/comms_alert.py (WOT-2026-153i).

Caja 1A: rutas (D1, D2, D17), estado (D10), bloqueo del SO (D18) y claves (D3, D5).
Cada prueba lleva el numero de fila del Anexo B del plan 153h que cierra y, cuando existe,
la mutacion que debe matarla (M/X/N/P/E; el arnes de mutacion vive fuera del repo).
El modulo se localiza por ruta (COMMS_ALERT_UNDER_TEST permite apuntar a una copia mutada).
"""

import ast
import errno
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time as _time
import types
from pathlib import Path

import pytest


CA_PATH = Path(
    os.environ.get("COMMS_ALERT_UNDER_TEST")
    or Path(__file__).resolve().parents[2] / "scripts" / "flight" / "comms_alert.py"
)
FS_PATH = CA_PATH.with_name("flight_stall_check.py")
WINDOWS = os.name == "nt"
M = 60  # segundos por minuto del reloj inyectado


def _load(name="comms_alert_ut"):
    spec = importlib.util.spec_from_file_location(name, CA_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _consumer_findings(cola):
    spec = importlib.util.spec_from_file_location("flight_stall_check_ut", FS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.CFG = types.SimpleNamespace(cola=cola)
    return mod.check_cola({}, {})


class FakeClock:
    """Sustituye al ``_real_time`` del bloqueo: avanza solo al dormir y corta un bucle sin limite."""

    def __init__(self):
        self.t = _time.time()
        self.sleeps = 0

    def time(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps += 1
        self.t += seconds
        assert self.sleeps < 500, "bucle de espera sin limite"


@pytest.fixture
def ca(tmp_path):
    """Modulo fresco configurado sobre un ops-dir temporal, reloj inyectado y notify falso."""
    mod = _load()
    mod.configure(str(tmp_path))
    clock = types.SimpleNamespace(now=1_000_000.0)
    mod.time = types.SimpleNamespace(time=lambda: clock.now)
    sent = []
    cleanup = []
    mode = {"rc": 0}
    mod.notify = lambda title, message, dry, **kwargs: (
        sent.append((title, message)),
        mode["rc"],
    )[1]

    def remove_toast(tag, group="flight", app_id=None, dry=False):
        cleanup.append((tag, group, app_id, dry))
        return True

    mod.remove_toast = remove_toast
    real_main = mod.main

    def test_main(argv=None):
        # Los tests heredados de Caja 1 no incluían el owner; el contrato D3 sí.
        args = list(argv or [])
        if (
            "--go-id" in args or ("--resolve" in args and "--flight-dir" in args)
        ) and "--owner" not in args:
            marker = (
                args.index("--go-id") if "--go-id" in args else args.index("--resolve")
            )
            args[marker:marker] = ["--owner", "IM-56"]
        return real_main(args)

    mod.main = test_main
    mod._raw_main = real_main
    return types.SimpleNamespace(
        m=mod, clock=clock, sent=sent, cleanup=cleanup, mode=mode, dir=tmp_path
    )


def _contend(code=errno.EACCES):
    def fake(fh):
        raise OSError(code, "contencion simulada")

    return fake


# ------------------------------------------------------------------ D1: censo de rutas del usuario
_FORBIDDEN = [
    r"tmp_or8",
    r"c:[/\\]+users",
    r"\bfdl\b",
    r"co24_q",
    r"vuelo-2026",
    r"orquestadora-3",
    r"\bc:[/\\]",
]


def _census(text):
    return [p for p in _FORBIDDEN if re.search(p, text, re.IGNORECASE)]


def test_d1_censo_produccion_sin_rutas_del_usuario():
    assert _census(CA_PATH.read_text(encoding="utf-8")) == []


def test_d1_censo_control_positivo_detecta_cada_tipo():
    sample = "\n".join(
        [
            "C:/Users/x",
            "tmp_OR8",
            "FDL",
            "co24_q",
            "vuelo-2026",
            "orquestadora-3",
            "c:\\ sueltos",
        ]
    )
    assert len(_census(sample)) == len(_FORBIDDEN)


# ------------------------------------------------------------------ D2: resolucion del ops-dir
def test_d2_argumento_gana_al_entorno(ca, tmp_path):
    otro = tmp_path / "otro"
    otro.mkdir()
    assert ca.m.resolve_ops_dir(str(tmp_path), {ca.m.OPS_DIR_ENV: str(otro)}).samefile(
        tmp_path
    )


def test_d2_entorno_si_no_hay_argumento(ca, tmp_path):
    assert ca.m.resolve_ops_dir(None, {ca.m.OPS_DIR_ENV: str(tmp_path)}).samefile(
        tmp_path
    )


def test_d2_sin_resolver_error_con_causa(ca):
    with pytest.raises(ca.m.OpsDirError, match="sin resolver"):
        ca.m.resolve_ops_dir(None, {})


def test_d2_main_sin_ops_dir_rc2_nunca_cwd(ca, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(ca.m.OPS_DIR_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    assert ca.m.main(["--scan"]) == 2
    assert "sin resolver" in capsys.readouterr().err


def test_d2_relativa_rechazada(ca):
    with pytest.raises(ca.m.OpsDirError, match="absoluta"):
        ca.m.resolve_ops_dir("ops", {})


@pytest.mark.skipif(not WINDOWS, reason="unidad-relativa solo existe en Windows")
def test_d2_unidad_relativa_rechazada(ca):
    with pytest.raises(ca.m.OpsDirError, match="absoluta"):
        ca.m.resolve_ops_dir("C:ops", {})


def test_d2_ausente_rechazada_y_no_se_crea(ca, tmp_path):
    ausente = tmp_path / "no_existe"
    with pytest.raises(ca.m.OpsDirError, match="no existe"):
        ca.m.resolve_ops_dir(str(ausente), {})
    assert not ausente.exists()


def test_d2_fichero_no_es_directorio(ca, tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ca.m.OpsDirError, match="no es un directorio"):
        ca.m.resolve_ops_dir(str(f), {})


@pytest.mark.skipif(not WINDOWS, reason="UNC solo en Windows")
def test_d2_unc_rechazada(ca):
    with pytest.raises(ca.m.OpsDirError, match="UNC"):
        ca.m.resolve_ops_dir("\\\\servidor\\recurso\\ops", {})


@pytest.mark.skipif(
    not WINDOWS, reason="capitalizacion de unidad y prefijo extendido solo en Windows"
)
def test_d2_unidad_en_minusculas_y_prefijo_extendido_aceptados(ca, tmp_path):
    s = str(tmp_path)
    assert ca.m.resolve_ops_dir(s[0].lower() + s[1:], {}).samefile(tmp_path)
    assert ca.m.resolve_ops_dir("\\\\?\\" + s, {}).samefile(tmp_path)


def test_d2_symlink_aceptado_y_resuelto(ca, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "enlace"
    try:
        os.symlink(real, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("este equipo no permite crear symlinks")
    assert ca.m.resolve_ops_dir(str(link), {}) == real.resolve()


def test_d2_configure_fija_rutas_dentro_del_ops_dir(ca, tmp_path):
    base = ca.m.configure(str(tmp_path))
    for p in (ca.m.LEDGER, ca.m.STATE, ca.m.LOCK, ca.m.LEDGER_LOCK):
        assert p.parent == base


# ------------------------------------------------------------------ D17: nada se carga de ops-dir
def test_d17_notify_se_localiza_junto_al_modulo_aunque_ops_dir_tenga_trampa(
    ca, tmp_path
):
    (tmp_path / "notify_user.ps1").write_text("trampa", encoding="utf-8")
    (tmp_path / "comms_alert.py").write_text(
        "raise SystemExit('trampa')", encoding="utf-8"
    )
    ca.m.configure(str(tmp_path))
    assert ca.m.NOTIFY.parent == CA_PATH.resolve().parent
    assert ca.m.NOTIFY.name == "notify_user.ps1"


def test_d17_la_orden_real_usa_el_ps1_junto_al_modulo(tmp_path, monkeypatch):
    mod = _load("comms_alert_cmd")
    mod.configure(str(tmp_path))
    (tmp_path / "notify_user.ps1").write_text("trampa", encoding="utf-8")
    cap = {}

    def fake_run(cmd, **kw):
        cap["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(
        mod,
        "subprocess",
        types.SimpleNamespace(run=fake_run, TimeoutExpired=TimeoutError),
    )
    monkeypatch.setenv("SYSTEMROOT", os.environ.get("SYSTEMROOT") or "C:\\WINDOWS")
    assert mod.notify("t", "m", False) == 0
    script = Path(cap["cmd"][cap["cmd"].index("-File") + 1])
    assert script.parent == CA_PATH.resolve().parent
    assert tmp_path not in script.parents


def test_d17_censo_ast_sin_cargadores_dinamicos():
    src = CA_PATH.read_text(encoding="utf-8")
    prohibidos = {"runpy", "exec", "eval", "import_module", "__import__"}
    vistos = set()
    cargas = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name) and node.id in prohibidos:
            vistos.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in prohibidos:
            vistos.add(node.attr)
        elif isinstance(node, ast.Import):
            vistos |= {a.name for a in node.names if a.name in prohibidos}
        if isinstance(node, ast.Attribute) and node.attr == "spec_from_file_location":
            cargas += 1
    assert vistos == set()
    # la UNICA carga por ruta permitida es send_with_ledger.py, localizado junto a este fichero
    assert cargas == 1
    assert (
        '_HELPER_PATH = Path(__file__).resolve().with_name("send_with_ledger.py")'
        in src
    )
    assert "Invoke-Expression" not in src
    assert "Start-Process" not in src


def test_d17_el_helper_se_localiza_junto_al_modulo_y_no_en_ops_dir(ca, tmp_path):
    (tmp_path / "send_with_ledger.py").write_text(
        "VALID_RESULTADOS = {'trampa'}\nFIXED_KEYS = {'x'}", encoding="utf-8"
    )
    ca.m.configure(str(tmp_path))
    assert ca.m._HELPER_PATH.parent == CA_PATH.resolve().parent
    assert "trampa" not in ca.m._helper().VALID_RESULTADOS


# ------------------------------------------------------------------ Filas 1-4: load_state y save_state
def test_fila01_load_state_ausente_es_vacio(ca):
    assert not ca.m.STATE.exists()
    assert ca.m.load_state() == {}


def test_fila02_load_state_truncado_es_vacio_y_el_aviso_sale(ca):
    ca.m.STATE.write_text('{"event:k": {"level": "AVI', encoding="utf-8")
    assert ca.m.load_state() == {}
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 0
    assert len(ca.sent) == 1


def test_fila02b_load_state_bom_se_lee(ca):
    ca.m.event("k", "AVISO", None, "x", False, False)
    ca.m.STATE.write_bytes(b"\xef\xbb\xbf" + ca.m.STATE.read_bytes())
    assert "event:k" in ca.m.load_state()
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 10


@pytest.mark.parametrize("raw", [b"[]", b"null", b'"x"', b"7"])
def test_fila02c_load_state_no_diccionario_es_vacio(ca, raw):
    ca.m.STATE.write_bytes(raw)
    assert ca.m.load_state() == {}
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 0


def test_fila03_save_state_atomico_si_replace_falla(ca, monkeypatch):
    ca.m.save_state({"a": 1})
    antes = ca.m.STATE.read_bytes()

    def boom(src, dst):
        raise OSError(errno.EIO, "fallo forzado")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="fallo forzado"):
        ca.m.save_state({"a": 2, "b": 3})
    monkeypatch.undo()
    assert ca.m.STATE.read_bytes() == antes
    assert list(ca.dir.glob("*.tmp")) == []


def test_fila04_tmp_unico_por_proceso(ca, monkeypatch):
    vistos = []
    real = os.replace
    monkeypatch.setattr(
        os, "replace", lambda s, d: (vistos.append(Path(s).name), real(s, d))[1]
    )
    for pid in (111, 222):
        monkeypatch.setattr(os, "getpid", lambda pid=pid: pid)
        ca.m.save_state({"a": pid})
    assert len(set(vistos)) == 2
    assert "111" in vistos[0]
    assert "222" in vistos[1]


# ------------------------------------------------------------------ Filas 5-21: bloqueo del SO (D18, mecanismo A)
def test_fila05_cuatro_hilos_no_pierden_claves(ca):
    def worker(tag):
        for i in range(25):
            ca.m.update_state(lambda s, k=f"event:{tag}{i}": s.__setitem__(k, 1))

    hilos = [threading.Thread(target=worker, args=(c,)) for c in "abcd"]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert len([k for k in ca.m.load_state() if k.startswith("event:")]) == 100


def test_fila06_fichero_de_lock_separado_del_estado(ca):
    assert ca.m.LOCK != ca.m.STATE
    with ca.m._Lock(ca.m.LOCK) as lk:
        ca.m.save_state({"con": "lock"})
    assert ca.m.load_state() == {"con": "lock"}
    assert lk is not None


class FakeMsvcrt:
    LK_UNLCK = 0
    LK_LOCK = 1
    LK_NBLCK = 2

    def __init__(self):
        self.calls = []

    def locking(self, fd, mode, nbytes):
        self.calls.append((mode, nbytes, os.lseek(fd, 0, os.SEEK_CUR)))


def test_fila07_bloqueo_no_bloqueante_lk_nblck(ca, monkeypatch):
    fake = FakeMsvcrt()
    monkeypatch.setattr(ca.m, "msvcrt", fake)
    with ca.m._Lock(ca.m.LOCK):
        pass
    assert [c[0] for c in fake.calls] == [fake.LK_NBLCK, fake.LK_UNLCK]


def test_fila08_intervalo_comun_un_byte_en_offset_0(ca, monkeypatch):
    fake = FakeMsvcrt()
    monkeypatch.setattr(ca.m, "msvcrt", fake)
    for _ in range(2):
        with ca.m._Lock(ca.m.LOCK):
            pass
    assert {(c[1], c[2]) for c in fake.calls} == {(1, 0)}
    assert len(fake.calls) == 4


def test_fila09_apertura_sin_truncado(ca):
    ca.m.LOCK.write_bytes(b"conservar")
    with ca.m._Lock(ca.m.LOCK):
        pass
    assert ca.m.LOCK.read_bytes() == b"conservar"


def test_fila10_descriptor_abierto_hasta_liberar(ca):
    with ca.m._Lock(ca.m.LOCK) as lk:
        assert lk.fh is not None
        assert not lk.fh.closed
    assert lk.fh.closed


_WORKER = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('ca_w', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
    "m.configure(sys.argv[2])\n"
    "tag = sys.argv[3]\n"
    "for i in range(int(sys.argv[4])):\n"
    "    m.update_state(lambda s, k='event:%s%d' % (tag, i): s.__setitem__(k, 1))\n"
)


def test_fila11_cuatro_procesos_con_replace_concurrente_no_pierden_claves(ca):
    procs = [
        subprocess.Popen(
            [sys.executable, "-I", "-c", _WORKER, str(CA_PATH), str(ca.dir), tag, "25"]
        )
        for tag in "abcd"
    ]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]
    assert len([k for k in ca.m.load_state() if k.startswith("event:")]) == 100


def test_fila12_agotados_5s_se_sigue_sin_bloqueo_y_se_declara(ca, monkeypatch, capsys):
    clk = FakeClock()
    monkeypatch.setattr(ca.m, "_real_time", clk)
    monkeypatch.setattr(ca.m, "_try_lock", _contend())

    def fn(s):
        ca.m.STATE.write_text(
            json.dumps({"event:otro": 1}), encoding="utf-8"
        )  # otro escritor, sin bloqueo
        s["event:mio"] = 1

    ca.m.update_state(fn)
    assert "SIN bloqueo" in capsys.readouterr().err
    assert "event:mio" in ca.m.load_state()
    assert (
        "event:otro" not in ca.m.load_state()
    )  # degradacion declarada: gana el ultimo escritor


def test_fila13_un_lock_viejo_ajeno_no_se_reclama_por_mtime(ca, monkeypatch):
    clk = FakeClock()
    monkeypatch.setattr(ca.m, "_real_time", clk)
    monkeypatch.setattr(ca.m, "_try_lock", _contend())
    ca.m.LOCK.write_bytes(b"")
    viejo = clk.t - 120
    os.utime(ca.m.LOCK, (viejo, viejo))
    ca.m.update_state(lambda s: s.__setitem__("event:z", 1))
    assert ca.m.LOCK.exists()
    assert os.path.getmtime(ca.m.LOCK) == pytest.approx(viejo, abs=1)


def test_fila14_oserror_al_abrir_el_lock_sigue_sin_bloqueo(ca, monkeypatch):
    def boom(*a, **k):
        raise PermissionError(errno.EACCES, "no abre")

    monkeypatch.setattr(ca.m, "open", boom, raising=False)
    ca.m.update_state(lambda s: s.__setitem__("event:z", 1))
    assert "event:z" in ca.m.load_state()


def test_fila15_bloqueo_ajeno_fresco_agotado_a_5s_sigue_sin_bloqueo(ca, monkeypatch):
    clk = FakeClock()
    inicio = clk.t
    monkeypatch.setattr(ca.m, "_real_time", clk)
    monkeypatch.setattr(ca.m, "_try_lock", _contend())
    ca.m.update_state(lambda s: s.__setitem__("event:z", 1))
    assert 5 <= clk.t - inicio < 6
    assert "event:z" in ca.m.load_state()


def test_fila16_error_que_no_es_contencion_sigue_sin_bloqueo_sin_esperar(
    ca, monkeypatch
):
    clk = FakeClock()
    monkeypatch.setattr(ca.m, "_real_time", clk)
    monkeypatch.setattr(ca.m, "_try_lock", _contend(errno.EIO))
    ca.m.update_state(lambda s: s.__setitem__("event:z", 1))
    assert clk.sleeps == 0
    assert "event:z" in ca.m.load_state()


def test_fila17_liberacion_normal_permite_a_otro_adquirir(ca):
    ajeno = open(ca.m.LOCK, "a+b")
    try:
        with ca.m._Lock(ca.m.LOCK) as lk:
            assert lk.held
            with pytest.raises(OSError) as info:
                ca.m._try_lock(ajeno)
            assert info.value.errno in ca.m._CONTENTION
        ca.m._try_lock(ajeno)  # liberado: ahora si
    finally:
        ajeno.close()


def test_fila18_oserror_al_liberar_se_ignora(ca, monkeypatch):
    def boom(fh):
        raise OSError(errno.EIO, "no libera")

    monkeypatch.setattr(ca.m, "_unlock", boom)
    with ca.m._Lock(ca.m.LOCK) as lk:
        pass
    assert lk.fh.closed


def test_fila21b_si_el_cuerpo_lanza_el_bloqueo_se_libera_aunque_siga_referenciado(ca):
    lk = ca.m._Lock(ca.m.LOCK)
    with pytest.raises(RuntimeError, match="cuerpo falla"), lk:
        raise RuntimeError("cuerpo falla")
    assert lk.fh.closed
    ajeno = open(ca.m.LOCK, "a+b")
    try:
        ca.m._try_lock(ajeno)
    finally:
        ajeno.close()


def test_fila21_si_fn_lanza_el_bloqueo_se_libera(ca):
    def fn(s):
        raise RuntimeError("fn falla")

    with pytest.raises(RuntimeError, match="fn falla"):
        ca.m.update_state(fn)
    ajeno = open(ca.m.LOCK, "a+b")
    try:
        ca.m._try_lock(ajeno)
    finally:
        ajeno.close()


# === FILAS 22-43 (Builder): claves y semantica (_rec, _due, _record, event, mark_seen, ack, resolve, reconcile) ===


def test_fila22_registro_legado_float_no_reavisa(ca):
    """fila 22: un registro legado (float antiguo) no reavisa, rc 10."""
    ca.m.save_state({"event:old": ca.clock.now - 100})
    assert ca.m.event("old", "AVISO", None, "x", False, False) == 10


def test_fila22b_legado_urgente_respeta_retroceso_y_cuenta_uno(ca):
    """fila 22b: legado URGENTE respeta retroceso 30 min y cuenta avisos."""
    ca.m.save_state({"event:old": ca.clock.now - 100})
    assert ca.m.event("old", "URGENTE", None, "x", False, False) == 10
    ca.clock.now += 31 * M
    assert ca.m.event("old", "URGENTE", None, "x", False, False) == 0
    ca.clock.now += 31 * M
    assert ca.m.event("old", "URGENTE", None, "x", False, False) == 10
    ca.clock.now += 30 * M
    assert ca.m.event("old", "URGENTE", None, "x", False, False) == 0


def test_fila23_clave_nueva_avisa(ca):
    """fila 23: clave nueva produce un aviso (rc 0, 1 entrada en sent)."""
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 0
    assert len(ca.sent) == 1


def test_fila24_ack_silencia(ca):
    """fila 24: ack sienta la clave - retroceso no la reavisa."""
    ca.m.event("k", "URGENTE", None, "x", False, False)
    assert ca.m.ack("k") == 0
    assert ca.cleanup[-1][0:2] == ("k", "flight")
    ca.clock.now += 600 * M
    assert ca.m.event("k", "URGENTE", None, "x", False, False) == 10


def test_fila25_aviso_sube_a_urgente(ca):
    """fila 25: AVISO -> URGENTE cuenta como sube de nivel y avisa."""
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 0
    assert ca.m.event("k", "URGENTE", None, "x", False, False) == 0
    assert len(ca.sent) == 2


def test_fila26_urgente_retroceso_30_60_120_240_y_tope(ca):
    """fila 26: URGENTE persistente sigue 30, 60, 120, 240 min y tope 4 h."""
    ca.m.event("u", "URGENTE", None, "x", False, False)
    pairs = [
        (29, 10),
        (2, 0),
        (59, 10),
        (2, 0),
        (119, 10),
        (2, 0),
        (239, 10),
        (2, 0),
        (239, 10),
        (2, 0),
    ]
    for espera, rc_esperado in pairs:
        ca.clock.now += espera * M
        result = ca.m.event("u", "URGENTE", None, "x", False, False)
        assert result == rc_esperado, (
            f"espera={espera * M}s rc={result} rc_exp={rc_esperado}"
        )


def test_fila27_aviso_se_avisa_una_sola_vez(ca):
    """fila 27: AVISO se notifica solo una vez, nunca se repite."""
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 0
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 10
    ca.clock.now += 400 * M
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 10
    assert len(ca.sent) == 1


def test_fila28_record_conserva_first_n_nu_y_owner(ca):
    """fila 28: _record conserva first, cuenta n/nu y respeta owner."""
    t0 = ca.clock.now
    ca.m.event("k", "URGENTE", None, "x", False, False, owner="stall")
    ca.clock.now += 31 * M
    ca.m.event("k", "URGENTE", None, "x", False, False, owner="stall")
    ca.clock.now += 61 * M
    ca.m.event("k", "URGENTE", None, "x", False, False, owner=None)
    rec = ca.m.load_state()["event:k"]
    assert rec["first"] == t0
    assert rec["n"] == 3
    assert rec["nu"] == 3
    assert rec["owner"] == "stall"
    assert rec["level"] == "URGENTE"
    assert rec["acked"] is False


def test_fila29_nivel_desconocido_rc2_sin_aviso(ca):
    """fila 29: nivel desconocido devuelve rc 2 y no produce aviso ni registro."""
    assert ca.m.event("k", "foo", None, "x", False, False) == 2
    assert ca.sent == []
    assert "event:k" not in ca.m.load_state()


def test_fila30_force_avisa_aunque_limitado(ca):
    """fila 30: force salta el limite y obliga a avisar."""
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 0
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 10
    assert ca.m.event("k", "AVISO", None, "x", True, False) == 0
    assert len(ca.sent) == 2


def test_fila31_aviso_fallido_no_consume(ca):
    """fila 31: aviso fallido (rc!=0) no consume el registro."""
    ca.mode["rc"] = 1
    assert ca.m.event("f", "AVISO", None, "x", False, False) == 2
    assert "event:f" not in ca.m.load_state()
    ca.mode["rc"] = 0
    assert ca.m.event("f", "AVISO", None, "x", False, False) == 0
    assert "event:f" in ca.m.load_state()


def test_fila32_mark_seen_marca_sin_avisar(ca):
    """fila 32: mark_seen crea registro base sin notificar."""
    ca.m.mark_seen("k", "urgente", "stall")
    assert ca.sent == []
    rec = ca.m.load_state()["event:k"]
    assert rec["level"] == "URGENTE"
    assert rec["owner"] == "stall"
    assert rec["nu"] == 1
    assert rec["n"] == 1
    assert rec["acked"] is False
    assert ca.m.event("k", "URGENTE", None, "x", False, False) == 10


def test_fila33_mark_seen_dry_no_escribe(ca):
    """fila 33: mark_seen con dry=True no escribe nada."""
    ca.m.mark_seen("k", "AVISO", None, True)
    assert not ca.m.STATE.exists()
    assert "event:k" not in ca.m.load_state()


def test_fila34_ack_clave_inexistente_devuelve_10(ca):
    """fila 34: ack de clave que no existe devuelve rc 10."""
    assert ca.m.ack("nada") == 10
    assert ca.m.load_state() == {}


def test_fila35_ack_marca_acked_y_dry_no_escribe(ca):
    """fila 35: ack marca acked=True; dry no escribe."""
    ca.m.event("k", "URGENTE", None, "x", False, False)
    assert ca.m.ack("k", True) == 0
    assert ca.m.load_state()["event:k"]["acked"] is False
    assert ca.m.ack("k") == 0
    assert ca.m.load_state()["event:k"]["acked"] is True


def test_ack_resolve_sin_toast_previo_no_registra_fallo_de_remove(ca, monkeypatch):
    """Limpieza fail-soft: una marca sin toast no genera un fallo espurio de History.Remove."""
    ca.m.save_state(
        {
            "event:ghost": {
                "level": "AVISO",
                "first": 1,
                "last": 1,
                "n": 1,
                "nu": 0,
                "acked": False,
                "owner": "manual",
                "toast": False,
            }
        }
    )

    def impossible_remove(*args, **kwargs):
        raise AssertionError("History.Remove no debe invocarse sin toast publicado")

    monkeypatch.setattr(ca.m, "remove_toast", impossible_remove)
    assert ca.m.ack("ghost") == 0
    assert not ca.m.LEDGER.exists()
    assert ca.m.resolve("ghost") == 0
    assert not ca.m.LEDGER.exists()


def test_fila36_resolve_borra_y_la_recaida_avisa(ca):
    """fila 36: resolve borra la clave y una recaida vuelve a avisar."""
    ca.m.event("r1", "URGENTE", None, "x", False, False)
    n0 = len(ca.sent)
    assert ca.m.resolve("r1") == 0
    assert ca.cleanup[-1][0:2] == ("r1", "flight")
    assert "event:r1" not in ca.m.load_state()
    assert ca.m.event("r1", "URGENTE", None, "x", False, False) == 0
    assert len(ca.sent) == n0 + 1


def test_fila37_resolve_clave_inexistente_devuelve_10(ca):
    """fila 37: resolve de clave inexistente devuelve rc 10."""
    assert ca.m.resolve("no-existe") == 10


def test_fila38_resolve_dry_no_borra(ca):
    """fila 38: resolve con dry=True no borra el registro."""
    ca.m.event("k", "AVISO", None, "x", False, False)
    assert ca.m.resolve("k", True) == 0
    assert "event:k" in ca.m.load_state()


def test_fila39_reconcile_prefijos_y_activas(ca):
    """fila 39: reconcile borra claves no activas (la recaida avisa) y respeta activas."""
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 0
    assert ca.m.reconcile(("k",), set()) == ["k"]
    assert ca.cleanup[-1][0:2] == ("k", "flight")
    assert "event:k" not in ca.m.load_state()
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 0
    assert len(ca.sent) == 2
    ca.m.event("otra", "AVISO", None, "x", False, False)
    assert ca.m.reconcile(("zzz",), set()) == []
    assert "event:otra" in ca.m.load_state()
    assert ca.m.reconcile(("otra",), {"otra"}) == []
    assert "event:otra" in ca.m.load_state()


def test_fila40_reconcile_respeta_dueno(ca):
    """fila 40: reconcile con owner solo borra las suyas y las heredadas sin dueno."""
    ca.m.event("cola-a", "AVISO", None, "x", False, False, owner="stall")
    ca.m.event("cola-b", "AVISO", None, "x", False, False, owner="manual")
    st = ca.m.load_state()
    st["event:cola-c"] = ca.clock.now - 5
    ca.m.save_state(st)
    gone = sorted(ca.m.reconcile(("cola-",), set(), False, "stall"))
    assert gone == ["cola-a", "cola-c"]
    assert "event:cola-b" in ca.m.load_state()


def test_fila41_reconcile_dry_no_borra(ca):
    """fila 41: reconcile con dry=True no borra ningun registro."""
    ca.m.event("k", "AVISO", None, "x", False, False)
    assert ca.m.reconcile(("k",), set(), True) == ["k"]
    assert "event:k" in ca.m.load_state()


def test_fila42_reconcile_no_toca_claves_que_no_son_de_evento(ca):
    """fila 42: reconcile solo toca claves event: y no altera metadatos."""
    ca.m.event("k", "AVISO", None, "x", False, False)
    st = ca.m.load_state()
    st["_last_scan_offset"] = 5
    ca.m.save_state(st)
    assert ca.m.reconcile(("",), set()) == ["k"]
    st2 = ca.m.load_state()
    assert st2.get("_last_scan_offset") == 5
    assert "event:k" not in st2


def test_fila43_reconcile_borra_solo_las_claves_de_su_owner_con_tres_owners(ca):
    """fila 43: reconcile con owner filtra por dueno exacto (tres owners)."""
    ca.m.event("latido-desviado", "AVISO", None, "x", False, False, owner="check")
    ca.m.event("latido-muerto", "AVISO", None, "x", False, False, owner="task")
    ca.m.event("tarea-muerta", "AVISO", None, "x", False, False, owner="stall")
    ca.m.event("cupo-92", "AVISO", None, "x", False, False, owner="stall")
    prefixes = ("latido-", "tarea-", "cupo-")
    assert ca.m.reconcile(prefixes, set(), False, "check") == ["latido-desviado"]
    assert ca.m.reconcile(prefixes, set(), False, "task") == ["latido-muerto"]
    assert sorted(ca.m.reconcile(prefixes, set(), False, "stall")) == [
        "cupo-92",
        "tarea-muerta",
    ]
    assert ca.m.load_state() == {}


def test_fila44_ninguna_clave_nueva_con_owner_none_la_borra_otro_owner(ca):
    """fila 44: owner None => borrable por cualquier owner (comportamiento heredado: owner None es borrable)."""
    ca.m.event("sin-dueno", "AVISO", None, "x", False, False)
    ca.m.event("de-check", "AVISO", None, "x", False, False, owner="check")
    assert sorted(ca.m.reconcile(("de-", "sin-"), set(), False, "check")) == sorted(
        ["de-check", "sin-dueno"]
    )


# ====================================================================== CAJA 1B (Manager): ledger, notify, alert, scan, main, redact
FLIGHT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "flight"


def _load_sibling(name):
    spec = importlib.util.spec_from_file_location(
        name.replace(".py", "_ut"), FLIGHT_DIR / name
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(ca):
    return [
        json.loads(ln)
        for ln in ca.m.LEDGER.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def _write_ledger(ca, raw, offset=0):
    """Escribe ``raw`` (bytes) como ledger y fija el offset del scan."""
    ca.m.LEDGER.write_bytes(raw)
    ca.m.save_state({"_last_scan_offset": offset})


def _fail_row(**extra):
    return (
        json.dumps(
            {"ts": "t", "from": "CO-24", "a": "mcp:x", "resultado": "FAIL", **extra}
        )
        + "\n"
    ).encode()


def _real_notify_module(tmp_path, monkeypatch, rc=0, raises=None):
    """Modulo con el notify REAL y un subprocess falso que captura la orden."""
    mod = _load("comms_alert_real")
    mod.configure(str(tmp_path))
    cap = {}

    def fake_run(cmd, **kw):
        cap["cmd"], cap["kw"] = cmd, kw
        if raises is not None:
            raise raises
        return types.SimpleNamespace(returncode=rc, stdout="salida")

    monkeypatch.setattr(
        mod,
        "subprocess",
        types.SimpleNamespace(run=fake_run, TimeoutExpired=subprocess.TimeoutExpired),
    )
    monkeypatch.setenv("SYSTEMROOT", os.environ.get("SYSTEMROOT") or "C:\\WINDOWS")
    return mod, cap


# ---- filas 44-45: ledger_append
def test_fila44_ledger_append_crea_el_fichero_y_escribe_una_linea(ca):
    assert not ca.m.LEDGER.exists()
    ca.m.ledger_append({"a": 1})
    assert ca.m.LEDGER.read_bytes() == b'{"a": 1}\n'


def test_fila45_ledger_append_repara_final_sin_salto_de_linea(ca):
    ca.m.LEDGER.write_bytes(b'{"previa": 1}')
    ca.m.ledger_append({"nueva": 2})
    assert ca.m.LEDGER.read_bytes() == b'{"previa": 1}\n{"nueva": 2}\n'


# ---- filas 47, 48, 50: notify
def test_fila47_forma_de_la_orden_absoluta_sin_bypass_sin_ventana(
    tmp_path, monkeypatch
):
    mod, cap = _real_notify_module(tmp_path, monkeypatch)
    assert mod.notify("t", "m", False) == 0
    cmd = cap["cmd"]
    exe = (
        Path(os.environ.get("SYSTEMROOT") or "C:\\WINDOWS")
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    assert Path(cmd[0]) == exe
    assert Path(cmd[0]).is_absolute()
    assert "Bypass" not in cmd
    assert cmd[1:7] == [
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(mod.NOTIFY),
    ]
    assert cap["kw"]["timeout"] == 60
    assert cap["kw"]["creationflags"] == (mod.NO_WINDOW if os.name == "nt" else 0)


def test_fila48_el_rc_del_proceso_se_devuelve_tal_cual(tmp_path, monkeypatch):
    mod, _ = _real_notify_module(tmp_path, monkeypatch, rc=3)
    assert mod.notify("t", "m", False) == 3


def test_fila50_systemroot_ausente_rc2_con_causa_y_sin_lanzar(
    tmp_path, monkeypatch, capsys
):
    mod, cap = _real_notify_module(tmp_path, monkeypatch)
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    assert mod.notify("t", "m", False) == 2
    assert "SystemRoot ausente" in capsys.readouterr().out
    assert "cmd" not in cap


# ---- filas 54, 57: filas propias de 9 claves y marca
def test_fila54_alert_escribe_alert_alert_fallido_y_throttled_con_9_claves(ca):
    helper = _load_sibling("send_with_ledger.py")
    ca.m.alert("k1", "w", "e", False, False)
    ca.m.alert("k1", "w", "e", False, False)  # THROTTLED
    ca.mode["rc"] = 1
    ca.m.alert("k2", "w", "e", False, False)  # ALERT_FALLIDO
    rows = _rows(ca)
    assert [r["resultado"] for r in rows] == ["ALERT", "THROTTLED", "ALERT_FALLIDO"]
    for r in rows:
        assert set(r) == set(helper.FIXED_KEYS)
        assert r["by"] == "comms_alert"
        assert r["mensaje_id"].startswith("comms_alert:")
    assert rows[2]["error"] == "e"
    validate = _load_sibling("validate_ledger.py")
    rc, report = validate.cmd_validate(ca.m.LEDGER)
    assert rc == 0
    assert "legacy" not in report


def test_fila54b_control_positivo_una_clave_extra_si_es_legacy(ca):
    validate = _load_sibling("validate_ledger.py")
    ca.m.alert("k1", "w", "e", False, False)
    ca.m.ledger_append({**_rows(ca)[0], "extra": 1})
    rc, report = validate.cmd_validate(ca.m.LEDGER)
    assert rc == 0
    assert "legacy: 1 linea" in report


def test_row_keys_coinciden_con_las_fijas_del_helper(ca):
    assert set(ca.m._ROW_KEYS) == set(_load_sibling("send_with_ledger.py").FIXED_KEYS)


def test_fila57_event_escribe_fila_de_9_claves_con_marca_unica_y_nota(ca):
    ca.m.event("cupo-92", "URGENTE", None, "x", False, False, owner="stall")
    ca.m.event("otra", "AVISO", None, "y", False, False)
    r1, r2 = _rows(ca)
    assert set(r1) == set(ca.m._ROW_KEYS)
    assert r1["a"] == "cupo-92"
    assert r1["resultado"] == "ALERT"
    assert r1["nota"].startswith("nivel=URGENTE; motivo=nueva; rc=0;")
    assert r1["mensaje_id"] != r2["mensaje_id"]
    assert re.fullmatch(r"comms_alert:[0-9a-f-]{36}", r1["mensaje_id"])


# ---- fila 56: dry-run
def test_fila56_event_dry_run_no_guarda_estado_ni_ledger(ca):
    assert ca.m.event("k", "AVISO", None, "x", False, True) == 0
    assert not ca.m.STATE.exists()
    assert not ca.m.LEDGER.exists()


# ---- filas 61, 63, 65, 66, 67: scan
def test_fila61_linea_fusionada_se_detecta_por_ultimo_recurso(ca):
    _write_ledger(ca, b'{"a":1}{"from":"CO-24","resultado":"FAIL"}\n')
    assert ca.m.scan(True, False) == 0
    assert len(ca.sent) == 1


def test_q8_fusionada_con_resultado_del_vocabulario_si_pero_la_palabra_suelta_no(ca):
    _write_ledger(ca, b'{"a":1}{"by":"CO-24","resultado": "thread_not_found"}\n')
    assert ca.m.scan(True, False) == 0
    _write_ledger(ca, b'{"a":1}{"by":"CO-24","error":"nada","nota":"error leve"}\n')
    assert ca.m.scan(True, False) == 10


def test_fila63_filas_propias_no_cuentan_antiguas_y_con_marca(ca):
    helper = _load_sibling("send_with_ledger.py")
    assert helper is not None
    propias = [
        {"ts": "t", "from": "comms_alert", "status": "FAIL parent_not_active"},
        {
            "ts": "t",
            "by": "comms_alert",
            "mensaje_id": "comms_alert:abc",
            "resultado": "ALERT",
            "nota": "FAIL parent_not_active error",
        },
        {
            "ts": "t",
            "by": "comms_alert",
            "mensaje_id": "comms_alert:def",
            "resultado": "error",
        },
    ]
    _write_ledger(ca, "".join(json.dumps(r) + "\n" for r in propias).encode())
    assert ca.m.scan(False, False) == 10
    assert ca.sent == []


def test_d20_fila_ajena_con_by_comms_alert_sin_marca_se_examina(ca):
    _write_ledger(ca, b'{"by":"comms_alert","mensaje_id":"otra","resultado":"error"}\n')
    assert ca.m.scan(True, False) == 0


def test_q7_linea_propia_rota_con_subcadena_de_fallo_no_redispara(ca):
    _write_ledger(
        ca,
        b'{"by":"comms_alert","mensaje_id":"comms_alert:x","resultado":"ALERT","nota":"FAIL parent_not_active"\n',
    )
    assert ca.m.scan(True, False) == 10
    assert ca.sent == []


def test_fila65_d15_cada_resultado_del_helper_real_menos_enviado(ca):
    helper = _load_sibling("send_with_ledger.py")
    for res in sorted(helper.VALID_RESULTADOS):
        ca.sent.clear()
        _write_ledger(ca, b"")
        rc, _ = helper.cmd_record(
            ca.m.LEDGER, "CO-24", f"m-{res}", "mcp:abc", "queue", res, error=res
        )
        assert rc == 0
        expected = 10 if res == "enviado" else 0
        assert ca.m.scan(True, False) == expected, res
        assert len(ca.sent) == (0 if res == "enviado" else 1), res


def test_d15_el_conjunto_se_deriva_del_helper_y_un_valor_nuevo_no_pasa_en_silencio(
    ca, monkeypatch
):
    fake = types.SimpleNamespace(
        VALID_RESULTADOS={"enviado", "valor_nuevo"}, FIXED_KEYS=set(ca.m._ROW_KEYS)
    )
    monkeypatch.setattr(ca.m, "_HELPER", fake)
    _write_ledger(ca, b'{"by":"CO-24","a":"mcp:x","resultado":"valor_nuevo"}\n')
    assert ca.m.scan(True, False) == 0


def test_d15_forma_result_del_ledger_antiguo_se_detecta(ca):
    _write_ledger(
        ca,
        b'{"delivery":"d","from":"CO-24","mode":"q","result":"FAIL","tag":"t","to":"x","ts":"t"}\n',
    )
    assert ca.m.scan(True, False) == 0


def test_fila66_el_motivo_parent_not_active_sale_en_el_aviso(ca):
    _write_ledger(
        ca,
        b'{"by":"CO-24","a":"mcp:x","resultado":"error","error":"parent_not_active"}\n',
    )
    assert ca.m.scan(True, False) == 0
    assert "FAIL parent_not_active" in ca.sent[-1][1]
    _write_ledger(
        ca, b'{"by":"CO-24","a":"mcp:x","resultado":"error","error":"otro"}\n'
    )
    assert ca.m.scan(True, False) == 0
    assert "parent_not_active" not in ca.sent[-1][1]


def test_fila67_aviso_fallido_no_avanza_el_offset_y_agrupado_lo_consume(ca):
    _write_ledger(ca, _fail_row())
    ca.mode["rc"] = 1
    assert ca.m.scan(True, False) == 2
    assert ca.m.load_state()["_last_scan_offset"] == 0
    ca.mode["rc"] = 0
    assert ca.m.scan(True, False) == 0
    off = ca.m.load_state()["_last_scan_offset"]
    assert off > 0
    ca.m.LEDGER.write_bytes(ca.m.LEDGER.read_bytes() + _fail_row())
    assert ca.m.scan(False, False) == 10  # agrupado en la ventana de 30 min
    assert ca.m.load_state()["_last_scan_offset"] > off
    assert len(ca.sent) == 2  # el intento fallido y el bueno; el agrupado no avisa


def test_q4_ledger_ausente_rc2_con_causa(ca, capsys):
    assert not ca.m.LEDGER.exists()
    assert ca.m.scan(False, False) == 2
    assert "scan FALLO" in capsys.readouterr().out


def test_q4_helper_no_cargable_rc2_con_causa(ca, monkeypatch, capsys):
    ca.m.LEDGER.write_bytes(b"")
    monkeypatch.setattr(ca.m, "_HELPER", None)
    monkeypatch.setattr(ca.m, "_HELPER_PATH", ca.dir / "no_existe.py")
    assert ca.m.scan(False, False) == 2
    assert "scan FALLO" in capsys.readouterr().out


def test_q2_bom_en_el_offset_0_se_ignora_y_la_fila_se_detecta(ca):
    _write_ledger(
        ca, b"\xef\xbb\xbf" + b'{"by":"CO-24","a":"IM-7","resultado":"error"}\n'
    )
    assert ca.m.scan(True, False) == 0
    # la fila se PARSEA (destino real). Desde la resincronizacion (B1) un BOM delante del objeto ya queda
    # como fragmento vacio, asi que el removeprefix es defensa explicita y no se puede mutar (Q2a retirado)
    assert "IM-7" in ca.sent[-1][1]


# ---- filas 69-70: main
def test_fila69_main_despacha_a_cada_subcomando_y_valida_el_uso(ca, monkeypatch):
    llamadas = []
    for nombre in ("resolve", "ack", "scan", "event", "alert"):
        monkeypatch.setattr(
            ca.m, nombre, lambda *a, _n=nombre, **k: llamadas.append((_n, a)) or 7
        )
    monkeypatch.setenv(ca.m.OPS_DIR_ENV, str(ca.dir))
    assert ca.m.main(["--resolve", "K1", "--dry-run"]) == 7
    assert ca.m.main(["--ack", "K2"]) == 7
    assert ca.m.main(["--scan", "--force"]) == 7
    assert ca.m.main(["--event", "K3", "--what", "w", "--level", "URGENTE"]) == 7
    assert ca.m.main(["--what", "w", "--error", "e"]) == 7
    assert [c[0] for c in llamadas] == ["resolve", "ack", "scan", "event", "alert"]
    assert llamadas[0][1] == ("K1", True)
    assert llamadas[1][1] == ("K2", False)
    assert llamadas[2][1] == (True, False)
    assert llamadas[4][1] == ("e", "w", "e", False, False)
    for argv in (["--event", "k"], []):
        with pytest.raises(SystemExit) as info:
            ca.m.main(argv)
        assert info.value.code == 2


def test_fila70_main_event_usa_owner_manual(ca, monkeypatch):
    vistos = []
    monkeypatch.setattr(ca.m, "event", lambda *a, **k: vistos.append((a, k)) or 0)
    monkeypatch.setenv(ca.m.OPS_DIR_ENV, str(ca.dir))
    assert ca.m.main(["--event", "K", "--what", "w"]) == 0
    assert vistos[0][1] == {"owner": "manual", "session_code": None}


def test_caja_c_main_event_inyecta_owner_como_session_code(ca, monkeypatch):
    """Caja C 7c: el CLI real conserva --owner como session_code del evento."""
    vistos = []
    monkeypatch.setattr(ca.m, "event", lambda *a, **k: vistos.append((a, k)) or 0)
    monkeypatch.setenv(ca.m.OPS_DIR_ENV, str(ca.dir))
    assert (
        ca.m.main(["--event", "K", "--what", "w", "--owner", "CO-31", "--dry-run"]) == 0
    )
    assert vistos == [
        (
            ("K", "AVISO", None, "w", False, True),
            {"owner": "manual", "session_code": "CO-31"},
        )
    ]


def test_caja_c_main_event_owner_invalido_conserva_fallback_real(ca):
    """El CLI real no convierte un owner inválido en identidad visible."""
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--event",
                "K",
                "--what",
                "w",
                "--owner",
                "not-a-code",
                "--dry-run",
            ]
        )
        == 0
    )
    assert ca.sent == [("Vuelo ?", "w")]


def test_caja1_evento_sin_codigo_conserva_aviso_y_marca_titulo_generico(ca):
    """Caja 1 RED/E2: la falta de codigo no puede silenciar el aviso."""
    assert (
        ca.m.event("sin-codigo", "AVISO", None, "FRASE LITERAL primero", False, False)
        == 0
    )
    assert ca.sent[0][0] == "Vuelo ?"


@pytest.mark.parametrize(
    "invalid", ["", "bad id", "bad/slash", "bad;semi", 'bad"quote', "bad-ñ"]
)
def test_caja_b_session_open_uri_rechaza_ids_invalidos(ca, monkeypatch, invalid):
    """Cada forma inválida de entorno no produce un URI de sesión."""
    for name in (
        "T3_ENVIRONMENT_ID",
        "T3_THREAD_ID",
        "FLIGHT_ENVIRONMENT_ID",
        "FLIGHT_THREAD_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("T3_ENVIRONMENT_ID", invalid)
    monkeypatch.setenv("T3_THREAD_ID", "THREAD_ID")
    assert ca.m.session_open_uri() is None


@pytest.mark.parametrize(
    "invalid", ["bad id", "bad/slash", "bad;semi", 'bad"quote', "bad-ñ"]
)
def test_caja_b_session_open_uri_rechaza_thread_ids_invalidos(ca, monkeypatch, invalid):
    """El control negativo también cubre el segundo identificador de entorno."""
    for name in (
        "T3_ENVIRONMENT_ID",
        "T3_THREAD_ID",
        "FLIGHT_ENVIRONMENT_ID",
        "FLIGHT_THREAD_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("T3_ENVIRONMENT_ID", "ENVIRONMENT_ID")
    monkeypatch.setenv("T3_THREAD_ID", invalid)
    assert ca.m.session_open_uri() is None


def test_caja_b_event_cablea_urgent_segun_nivel_con_notificador_stub(tmp_path):
    """La ruta real de event entrega urgent=True solo para URGENTE."""
    real = _load("urgent_wiring_real")
    real.configure(str(tmp_path))
    captured = []

    def notify(title, message, dry, **kwargs):
        captured.append((title, message, dry, kwargs))
        return 0

    real.notify = notify
    assert real.event("urgent-wire", "URGENTE", None, "urgent", True, True) == 0
    assert real.event("notice-wire", "AVISO", None, "notice", True, True) == 0
    assert [item[3]["urgent"] for item in captured] == [True, False]


def test_caja_b_redact_ancla_la_frontera_exacta_de_text_limit(ca):
    """160 caracteres caben; 161 se recortan al límite y conservan el sufijo."""
    assert len(ca.m.redact("x" * 160)) == 160
    recortado = ca.m.redact("x" * 161)
    assert len(recortado) == ca.m.TEXT_LIMIT == 160
    assert recortado.endswith("...")


def test_caja_b_main_fija_what_y_titulo_con_owner_invalido_y_ausente(ca):
    """El fallback real conserva el what literal tanto con owner inválido como ausente."""
    literal = "FRASE LITERAL primero"
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--event",
                "fallback-invalid-owner",
                "--what",
                literal,
                "--owner",
                "not-a-code",
                "--dry-run",
            ]
        )
        == 0
    )
    assert len(ca.sent) == 1
    assert ca.sent[0] == ("Vuelo ?", literal)
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--event",
                "fallback-missing-owner",
                "--what",
                literal,
                "--dry-run",
            ]
        )
        == 0
    )
    assert len(ca.sent) == 2
    assert ca.sent[1] == ("Vuelo ?", literal)


def test_caja_c_tag_for_toast_docstring_fija_la_clave_cruda(ca):
    """Caja C 7d: la especificación exige derivar siempre desde la clave cruda."""
    doc = ca.m.tag_for_toast.__doc__ or ""
    assert "aplica redact a la clave cruda SIEMPRE" in doc
    assert "NO aplica redact a la clave cruda SIEMPRE" not in doc
    assert "salida NO es" in doc and "idempotente" in doc
    assert "MISMA clave cruda" in doc
    assert "nunca aplicar tag_for_toast sobre un Tag ya derivado" in doc


def test_caja_c_redact_aplica_text_limit_despues_de_transformar_contenido(ca):
    """La frontera se mide sobre el contenido ya redactado, no sobre la entrada cruda."""
    raw = "x" * 150 + "mcp:12345678-1234-1234-1234-123456789012"
    assert len(raw) > ca.m.TEXT_LIMIT
    assert ca.m.redact(raw) == "x" * 150 + "mcp:<hilo>"
    assert len(ca.m.redact(raw)) == ca.m.TEXT_LIMIT
    near = "x" * 149 + "mcp:12345678-1234-1234-1234-123456789012"
    assert ca.m.redact(near) == "x" * 149 + "mcp:<hilo>"
    assert len(ca.m.redact(near)) == ca.m.TEXT_LIMIT - 1


def test_caja_c_docstring_tag_no_promete_idempotencia():
    """La comprobación lee el docstring real del módulo, no una copia del test."""
    tree = ast.parse(CA_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "tag_for_toast"
    )
    doc = ast.get_docstring(function) or ""
    assert "aplica redact a la clave cruda SIEMPRE" in doc
    assert "MISMA clave cruda" in doc


def test_caja1_evento_largo_cadena_real_protege_frase_y_recorta(ca, monkeypatch):
    """A4: notify real recibe la frase protegida y aplica el recorte de 160."""
    real_mod = _load("comms_alert_chain_real")
    real_mod.configure(str(ca.dir))
    captured = []

    def run(argv, **kwargs):
        captured.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(real_mod.subprocess, "run", run)
    monkeypatch.setattr(real_mod, "_powershell_exe", lambda: Path("powershell.exe"))
    ca.m.notify = real_mod.notify
    what = (
        "PUSH C:/Users/fdl/repo mcp:12345678-1234-1234-1234-123456789012 16. Detalle: "
        + ("x" * 400)
    )
    assert (
        ca.m.event(
            "frase-larga",
            "AVISO",
            "CO-29",
            what,
            False,
            False,
            preserve_literal=True,
        )
        == 0
    )
    message = captured[0][captured[0].index("-Message") + 1]
    assert message.startswith(
        "PUSH C:/Users/fdl/repo mcp:12345678-1234-1234-1234-123456789012 16."
    )
    assert len(message) <= ca.m.TEXT_LIMIT


def test_caja1_go_usa_owner_como_codigo_de_sesion_y_redacta_la_frase(ca, tmp_path):
    """Caja 1 RED/E3: GO explicito identifica la sesion; el llamador ya da la frase primera."""
    queue = tmp_path / "diseno" / "COLA_PARA_USUARIO.md"
    queue.parent.mkdir()
    queue.write_text("", encoding="utf-8")
    assert (
        ca.m.go_request(
            "go-caja1",
            "FRASE LITERAL primero",
            str(tmp_path),
            "CO-29",
            dry=False,
            now_fn=lambda: "2026-11-04 13:24:00",
        )
        == 0
    )
    assert ca.sent[0][0] == "CO-29"
    assert ca.sent[0][1] == "FRASE LITERAL primero"


def test_f1_appid_efectivo_es_igual_al_publicar_y_retirar(ca, monkeypatch):
    real = _load("f1_real")
    real.configure(str(ca.dir))
    """F1: publicación y retirada deben usar exactamente la misma identidad."""
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(real.subprocess, "run", run)
    monkeypatch.setattr(real, "_powershell_exe", lambda: Path("powershell.exe"))
    key = "hilo-failed-6bb68939-6779-41de-be05-88e711bb7d03"
    real.notify("CO-29", "FRASE", False, tag=key, group="flight")
    real.remove_toast(key)

    def appid(argv):
        return argv[argv.index("-AppId") + 1]

    assert len(calls) == 2
    assert appid(calls[0]) == appid(calls[1]) == real.POWERSHELL_APP_ID
    expected_tag = real.tag_for_toast(key)
    assert calls[0][calls[0].index("-Tag") + 1] == expected_tag
    assert calls[1][calls[1].index("-Tag") + 1] == expected_tag
    assert "-Remove" in calls[1] and "-NoFlash" in calls[1]


def test_clear_group_real_no_flash_y_appid_unico(ca, monkeypatch):
    real = _load("clear_group_real")
    real.configure(str(ca.dir))
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(real.subprocess, "run", run)
    monkeypatch.setattr(real, "_powershell_exe", lambda: Path("powershell.exe"))
    assert real.clear_group(False) is True
    assert "-ClearGroup" in calls[0]
    assert "-NoFlash" in calls[0]
    assert calls[0][calls[0].index("-AppId") + 1] == real.POWERSHELL_APP_ID


def test_f2_enlace_basico_t3code_se_pasa_y_fallback_no_anade_uri(ca, monkeypatch):
    """F2: el enlace depende de ambos ids del entorno; si falta uno solo queda dismiss."""
    captured = []
    ca.m.notify = lambda *args, **kwargs: captured.append(kwargs) or 0
    monkeypatch.setenv("T3_ENVIRONMENT_ID", "ENVIRONMENT_ID")
    monkeypatch.setenv("T3_THREAD_ID", "THREAD_ID")
    assert (
        ca.m.event(
            "f2", "URGENTE", "ignorado", "FRASE", True, False, session_code="CO-29"
        )
        == 0
    )
    assert captured[-1]["open_uri"] == "t3code://threads/ENVIRONMENT_ID/mcp:THREAD_ID"
    monkeypatch.delenv("T3_THREAD_ID")
    assert (
        ca.m.event(
            "f2b", "URGENTE", "ignorado", "FRASE", True, False, session_code="CO-29"
        )
        == 0
    )
    assert captured[-1]["open_uri"] is None


@pytest.mark.parametrize(
    ("environment", "thread"),
    [
        ("T3_ENVIRONMENT_ID", "T3_THREAD_ID"),
        ("FLIGHT_ENVIRONMENT_ID", "FLIGHT_THREAD_ID"),
    ],
)
def test_session_open_uri_acepta_los_dos_pares_de_entorno(
    ca, monkeypatch, environment, thread
):
    for name in (
        "T3_ENVIRONMENT_ID",
        "T3_THREAD_ID",
        "FLIGHT_ENVIRONMENT_ID",
        "FLIGHT_THREAD_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(environment, "ENVIRONMENT_ID")
    monkeypatch.setenv(thread, "THREAD_ID")
    assert ca.m.session_open_uri() == "t3code://threads/ENVIRONMENT_ID/mcp:THREAD_ID"


def test_f3_codigo_ausente_ignora_title_del_llamador(ca):
    """F3: sin código válido el título visible siempre es Vuelo ?."""
    ca.sent.clear()
    assert ca.m.event("f3", "AVISO", "CO-29", "FRASE", True, False) == 0
    assert ca.sent[-1][0] == "Vuelo ?"


def test_f4_protege_la_frase_literal_antes_de_redactar_la_cola(ca, monkeypatch):
    """F4: ruta y mcp:id dentro de la primera frase permanecen literales."""
    phrase = "PUSH C:/Users/fdl/repo mcp:12345678-1234-1234-1234-123456789012 16. Detalle: reintento"
    real = _load("f4_real")
    real.configure(str(ca.dir))
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(real.subprocess, "run", run)
    monkeypatch.setattr(real, "_powershell_exe", lambda: Path("powershell.exe"))
    assert real.notify("CO-29", phrase, False, preserve_literal=True) == 0
    message = calls[0][calls[0].index("-Message") + 1]
    assert message.startswith(
        "PUSH C:/Users/fdl/repo mcp:12345678-1234-1234-1234-123456789012 16."
    )
    assert len(message) <= real.TEXT_LIMIT


def test_evento_manual_redacta_completo_sin_heuristica(ca, monkeypatch):
    real = _load("manual_redact_real")
    real.configure(str(ca.dir))
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(real.subprocess, "run", run)
    monkeypatch.setattr(real, "_powershell_exe", lambda: Path("powershell.exe"))
    assert (
        real.event(
            "manual-redact",
            "AVISO",
            None,
            "Detalle C:/Users/fdl/privada. Escribe GO 1 token-secreto",
            False,
            False,
            session_code="CO-29",
        )
        == 0
    )
    message = calls[0][calls[0].index("-Message") + 1]
    assert "<ruta>" in message
    assert "token-secreto" not in message
    assert "Escribe GO 1" in message


def test_tag_for_toast_distingue_uuid_y_reutiliza_tag_en_publicar_y_retirar(
    ca, monkeypatch
):
    real = _load("tag_identity_real")
    real.configure(str(ca.dir))
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(real.subprocess, "run", run)
    monkeypatch.setattr(real, "_powershell_exe", lambda: Path("powershell.exe"))
    keys = [
        "hilo-failed-6bb68939-6779-41de-be05-88e711bb7d03",
        "hilo-failed-2083aab7-ec8d-45a6-ad03-ac2e9ba6782c",
    ]
    for key in keys:
        assert real.notify("CO-31", "aviso", False, tag=key) == 0
        assert real.remove_toast(key, dry=False)
    published = [calls[i][calls[i].index("-Tag") + 1] for i in (0, 2)]
    removed = [calls[i][calls[i].index("-Tag") + 1] for i in (1, 3)]
    assert published[0] != published[1]
    assert published == removed


def test_caja_a_tag_reserva_prefijo_y_conserva_tags_de_productores_reales(ca):
    """Caja A: ``flight-`` es prefijo reservado; los productores actuales no cambian."""
    real = _load("tag_reserved_prefix_real")
    source_key = "hilo-failed-6bb68939-6779-41de-be05-88e711bb7d03"
    hashed_tag = real.tag_for_toast(source_key)
    assert real.tag_for_toast(hashed_tag) != hashed_tag
    assert real.tag_for_toast(hashed_tag) == (
        "flight-" + hashlib.sha256(hashed_tag.encode("utf-8")).hexdigest()[:57]
    )

    golden = {
        "latido-muerto": "latido-muerto",
        "cupo-alvarovans-95": "cupo-alvarovans-95",
        "cola-66c72ced": "cola-66c72ced",
        source_key: "flight-c3ff50acd48e5c186aa7d834d948a64065abb7982e3ced7b951628ca4",
        "go-153y-1": "go-153y-1",
    }
    assert {key: real.tag_for_toast(key) for key in golden} == golden


def test_caja_a_tag_fija_fronteras_de_longitud_y_prefijo_reservado(ca):
    """La reserva solo aplica al prefijo exacto y la frontera de 64 es inclusiva."""
    real = _load("tag_reserved_boundaries_real")
    assert real.tag_for_toast("x" * 64) == "x" * 64
    assert real.tag_for_toast("x" * 65) == (
        "flight-" + hashlib.sha256(("x" * 65).encode("utf-8")).hexdigest()[:57]
    )
    assert real.tag_for_toast("flightplan") == "flightplan"
    assert real.tag_for_toast("flight") == "flight"
    assert real.tag_for_toast("flight-anything") == (
        "flight-" + hashlib.sha256(b"flight-anything").hexdigest()[:57]
    )


@pytest.mark.parametrize(
    "value",
    ["mi-token=abc123", "my_token=abc", "x-api-key: abc", "mypassword=abc"],
)
def test_redact_reconoce_secretos_pegados_a_prefijos(ca, value):
    real = _load("secret_prefixes_real")
    assert "abc" not in real.redact(value)


def test_redact_literal_first_docstring_real_del_fuente():
    """La especificacion se lee del docstring AST, no de una reasignacion posterior."""
    tree = ast.parse(CA_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "redact_literal_first"
    )
    doc = ast.get_docstring(function) or ""
    assert "96 caracteres" not in doc
    assert "debe aplicar" not in doc
    assert "preserve_literal" in doc
    assert "no pre-redacta" in doc


def test_go_cola_tick_literal_conserva_ruta_mcp_y_redacta_secreto(ca, monkeypatch):
    real = _load("go_chain_real")
    real.configure(str(ca.dir))
    flight = ca.dir / "flight"
    queue = flight / "diseno" / "COLA_PARA_USUARIO.md"
    queue.parent.mkdir(parents=True)
    queue.write_text("", encoding="utf-8")
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(real.subprocess, "run", run)
    monkeypatch.setattr(real, "_powershell_exe", lambda: Path("powershell.exe"))
    phrase = (
        "PUSH C:/Users/fdl/repo mcp:12345678-1234-1234-1234-123456789012 "
        "16. token-secreto"
    )
    assert real.go_request("go-chain", phrase, str(flight), "CO-29") == 0
    fs = _load_sibling("flight_stall_check.py")
    fs.CFG = types.SimpleNamespace(cola=queue)
    out = {}
    found = fs.check_cola(out, {})
    key, level, what = found[0]
    assert key == "go-chain" and level == "URGENTE"
    assert "C:/Users/fdl/repo" in what
    assert "mcp:12345678-1234-1234-1234-123456789012" in what
    assert "token-secreto" not in what
    assert (
        real.event(
            key,
            level,
            None,
            what,
            True,
            False,
            owner="stall",
            session_code="CO-29",
            preserve_literal=True,
        )
        == 0
    )
    message = calls[-1][calls[-1].index("-Message") + 1]
    assert "C:/Users/fdl/repo" in message
    assert "mcp:12345678-1234-1234-1234-123456789012" in message
    assert "token-secreto" not in message


def test_caja1_event_owner_codigo_valido_titulo_y_codigo_invalido_fallback(ca):
    """RED/E3: session_code identifica; owner sigue siendo la clase interna del estado."""
    ca.m.event(
        "owner-ok",
        "AVISO",
        None,
        "FRASE LITERAL primero",
        False,
        False,
        owner="manual",
        session_code="CO-29",
    )
    assert ca.sent[-1][0] == "CO-29"
    for invalid in (
        "mcp:12345678-1234-1234-1234-123456789012",
        r"C:\secret",
        "<CO-29>",
        "TOOLONG-1",
    ):
        ca.m.event(
            "owner-" + str(len(ca.sent)),
            "AVISO",
            None,
            "FRASE LITERAL primero",
            False,
            False,
            owner="manual",
            session_code=invalid,
        )
        assert ca.sent[-1][0].startswith("Vuelo ?")


def test_caja1_setting_disabled_doble_no_marca_evento_y_devuelve_rc2(ca):
    """RED/E2: si el notificador devuelve rc 3 por Setting Disabled, comms devuelve rc 2."""
    ca.mode["rc"] = 3
    assert (
        ca.m.event(
            "setting-disabled", "AVISO", "CO-29", "FRASE LITERAL primero", False, False
        )
        == 2
    )
    assert ca.sent
    assert "event:setting-disabled" not in ca.m.load_state()


# ---- filas 71-73: redact (D21)
_UUID_TXT = "mcp:3921a7b1-8f23-4016-898c-8abc7e58c8a9"


def test_fila71_redact_cubre_el_title_y_el_mensaje_del_toast(tmp_path, monkeypatch):
    mod, cap = _real_notify_module(tmp_path, monkeypatch)
    mod.notify(
        f"hilo {_UUID_TXT}", "en C:\\Users\\fdl\\tmp_or8\\x y c:/users/FDL/y", False
    )
    title = cap["cmd"][cap["cmd"].index("-Title") + 1]
    message = cap["cmd"][cap["cmd"].index("-Message") + 1]
    assert "3921a7b1" not in title
    assert "mcp:<hilo>" in title
    assert "fdl" not in message.lower()
    assert message.count("<ruta>") == 2


def test_fila71b_redact_cubre_el_ledger_y_el_destino_del_scan(ca):
    ca.m.ledger_append(
        {
            "a": "k",
            "nota": f"destino {_UUID_TXT}",
            "error": "C:\\Users\\x",
            "what": "ok",
            "mensaje_id": "comms_alert:" + "7" * 8,
        }
    )
    row = _rows(ca)[0]
    assert "3921a7b1" not in row["nota"]
    assert row["error"] == "<ruta>"
    assert (
        row["mensaje_id"] == "comms_alert:77777777"
    )  # las 9 claves y el id se preservan sin tocar
    _write_ledger(
        ca, b'{"by":"CO-24","a":"' + _UUID_TXT.encode() + b'","resultado":"error"}\n'
    )
    assert ca.m.scan(True, False) == 0
    ca.m.ledger_append({"a": "scan", "nota": ca.sent[-1][1]})
    assert "3921a7b1" not in _rows(ca)[-1]["nota"]


def test_fila72_el_tope_de_160_se_aplica_despues_de_redactar(ca):
    assert ca.m.redact("x" * 140 + _UUID_TXT) == "x" * 140 + "mcp:<hilo>"
    largo = ca.m.redact("y" * 400)
    assert len(largo) == ca.m.TEXT_LIMIT
    assert largo.endswith("...")


@pytest.mark.parametrize(
    "texto",
    [
        "x" * 140 + _UUID_TXT,
        "y" * 400,
        "C:\\Users\\fdl\\a b",
        "plano",
        "\\\\?\\C:\\Users\\fdl\\z " + "w" * 200,
    ],
)
def test_fila73_redact_es_idempotente(ca, texto):
    una = ca.m.redact(texto)
    assert ca.m.redact(una) == una


@pytest.mark.parametrize("texto", ["https://ejemplo.org/x", "ftp://host:21/dir"])
def test_redact_no_toca_urls(ca, texto):
    assert ca.m.redact(texto) == texto


# ---- fila 74 (F1): ledger entre procesos
_LEDGER_WORKER = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('ca_w', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
    "m.configure(sys.argv[2])\n"
    "for i in range(int(sys.argv[4])):\n"
    "    m.ledger_append(m._ledger_row(sys.argv[3] + str(i), 'ALERT', 'z' * 300))\n"
)


def test_fila74_cuatro_procesos_anaden_filas_sin_perder_ni_partir_ninguna(ca):
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                _LEDGER_WORKER,
                str(CA_PATH),
                str(ca.dir),
                tag,
                "50",
            ]
        )
        for tag in "abcd"
    ]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]
    filas = _rows(ca)
    assert len(filas) == 200
    assert len({f["mensaje_id"] for f in filas}) == 200
    assert len({f["a"] for f in filas}) == 200


# ---- deuda 2 de 1A: valores ilegibles en el estado no impiden que el aviso salga
@pytest.mark.parametrize(
    ("raw", "nivel", "esperado"),
    [
        ('"ayer"', "AVISO", 0),
        ('"ayer"', "URGENTE", 0),
        ("[1]", "AVISO", 0),
        ("[1]", "URGENTE", 0),
        (
            # A2 (ronda 1): `last` no numerico = registro ilegible = ausente, asi que el AVISO SALE
            '{"level":"URGENTE","last":"x","first":1,"n":1,"nu":1,"acked":false}',
            "AVISO",
            0,
        ),
        (
            '{"level":"URGENTE","last":"x","first":1,"n":1,"nu":1,"acked":false}',
            "URGENTE",
            0,
        ),
        (
            '{"level":"URGENTE","last":1,"first":1,"n":"x","nu":"x","acked":false}',
            "AVISO",
            10,
        ),
        (
            '{"level":"URGENTE","last":1,"first":1,"n":"x","nu":"x","acked":false}',
            "URGENTE",
            0,
        ),
    ],
)
def test_deuda2_event_con_registro_ilegible_no_rompe_y_el_urgente_sale(
    ca, raw, nivel, esperado
):
    ca.m.STATE.write_text('{"event:k": ' + raw + "}", encoding="utf-8")
    assert ca.m.event("k", nivel, None, "x", False, False) == esperado
    assert len(ca.sent) == (1 if esperado == 0 else 0)


def test_deuda2_ack_y_reconcile_con_registro_ilegible(ca):
    ca.m.STATE.write_text('{"event:k": "ayer", "event:j": [1]}', encoding="utf-8")
    assert ca.m.ack("k") == 0
    assert ca.m.load_state()["event:k"]["acked"] is True
    assert ca.m.reconcile(("j",), set(), False, "stall") == ["j"]


def test_q3_alert_con_valor_no_numerico_en_el_estado_avisa(ca):
    ca.m.STATE.write_text('{"k": "ayer"}', encoding="utf-8")
    assert ca.m.alert("k", "w", "e", False, False) == 0
    assert len(ca.sent) == 1


# === FILAS 1B simples (Builder) ===


def test_fila46_notify_dry_run_no_ejecuta_nada(tmp_path, monkeypatch, capsys):
    """fila 46: dry run no ejecuta subprocess ni escribe nada."""
    mod, cap = _real_notify_module(tmp_path, monkeypatch)
    assert mod.notify("t", "m", True) == 0
    assert "cmd" not in cap
    assert "DRY-RUN notify:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "excepcion",
    [subprocess.TimeoutExpired("powershell", 60), OSError("no arranca")],
)
def test_fila49_notify_timeout_u_oserror_devuelve_2_sin_lanzar(
    tmp_path, monkeypatch, capsys, excepcion
):
    """fila 49: TimeoutExpired / OSError devuelve rc 2 sin re-lanzar."""
    mod, _cap = _real_notify_module(tmp_path, monkeypatch, raises=excepcion)
    assert mod.notify("t", "m", False) == 2
    assert "notify FALLO" in capsys.readouterr().out


def test_fila51_alert_limita_a_una_vez_cada_30_min_por_clave(ca):
    """fila 51: misma clave limitada a una vez cada 30 minutos."""
    assert ca.m.alert("k", "w", "e", False, False) == 0
    assert ca.m.alert("k", "w", "e", False, False) == 10
    assert len(ca.sent) == 1
    ca.clock.now += 31 * M
    assert ca.m.alert("k", "w", "e", False, False) == 0
    assert len(ca.sent) == 2


def test_fila52_alert_una_clave_distinta_no_se_limita(ca):
    """fila 52: claves distintas tienen ventanas de throttle independientes."""
    assert ca.m.alert("k1", "w", "e", False, False) == 0
    assert ca.m.alert("k2", "w", "e", False, False) == 0
    assert len(ca.sent) == 2


def test_fila53_alert_aviso_fallido_no_consume_el_limite(ca):
    """fila 53: fallo del notify no consume la ventana de throttle."""
    ca.mode["rc"] = 1
    assert ca.m.alert("k", "w", "e", False, False) == 2
    assert "k" not in ca.m.load_state()
    ca.mode["rc"] = 0
    assert ca.m.alert("k", "w", "e", False, False) == 0
    assert "k" in ca.m.load_state()


def test_fila55_alert_rc_0_2_y_10(ca):
    """fila 55: alerta devuelve rc 0 cuando se envia, 2 si falla, 10 si esta limitado."""
    ca.mode["rc"] = 1
    r1 = ca.m.alert("a", "w", "e", False, False)
    ca.mode["rc"] = 0
    r2 = ca.m.alert("b", "w", "e", False, False)
    r3 = ca.m.alert("b", "w", "e", False, False)
    assert (r1, r2, r3) == (2, 0, 10)


def test_fila58_scan_primer_uso_sin_offset_no_reavisa_la_historia(ca):
    """fila 58: primer scan sin offset detecta fila FAIL pero no reavisa la historia."""
    ca.m.LEDGER.write_bytes(_fail_row())
    assert ca.m.scan(False, False) == 10
    assert ca.sent == []
    assert ca.m.load_state()["_last_scan_offset"] == ca.m.LEDGER.stat().st_size


def test_fila59_scan_offset_mayor_que_el_fichero_relee_desde_0_fail_closed(ca):
    """fila 59 (A3, ronda 1): ledger encogido o sustituido (offset > tamano) = se RELEE desde 0.

    Antes saltaba al final y descartaba en silencio las filas FAIL no escaneadas (parada sin aviso);
    es una diferencia autorizada frente a la version vigente. Control negativo: con el offset
    exactamente en el final no se reavisa la historia.
    """
    fila = _fail_row(a="IM-7")
    _write_ledger(ca, fila, offset=len(fila) + 1)
    assert ca.m.scan(False, False) == 0
    assert "IM-7" in ca.sent[-1][1]
    assert ca.m.load_state()["_last_scan_offset"] == len(fila)
    ca.sent.clear()
    _write_ledger(ca, fila, offset=len(fila))
    assert ca.m.scan(False, False) == 10
    assert ca.sent == []


@pytest.mark.parametrize(
    "basura",
    ["abc", 1.5, -5, True, [1], {"a": 1}, "", float("nan"), float("inf"), 10**400],
)
def test_q3b_scan_con_offset_no_entero_relee_desde_0_y_avisa(ca, basura):
    """Q3b: un offset que no es un entero >= 0 (antes TypeError sin aviso) vale 0: el aviso sale una vez."""
    _write_ledger(ca, _fail_row(a="IM-7"), offset=basura)
    assert ca.m.scan(True, False) == 0
    assert len(ca.sent) == 1
    # la fila se PARSEA desde el byte 0 (con True como 1 se cortaria el primer caracter y el destino seria "?")
    assert "IM-7" in ca.sent[-1][1]
    # el offset avanza hasta el final de la fila leida (el ALERT que el propio aviso anade queda detras)
    assert ca.m.load_state()["_last_scan_offset"] == len(_fail_row(a="IM-7"))


# ---- ronda 1 de lentes (A1-A4) ----
_PROPIA = (
    b'{"by":"comms_alert","mensaje_id":"comms_alert:x","resultado":"ALERT","nota":"n"}'
)
_AJENA_FAIL = b'{"from":"CO-24","a":"IM-9","resultado":"FAIL"}'


def test_a1_fila_propia_fusionada_con_fail_ajeno_cuenta_el_ajeno(ca):
    """A1 (i): `{propia}{ajena FAIL}` en una linea: el FAIL ajeno cuenta (antes: se perdia)."""
    linea = _PROPIA + _AJENA_FAIL + b"\n"
    assert ca.m._scan_chunk(linea.decode(), ca.m._failure_resultados()) == [
        {"to": "IM-9", "status": "FAIL"}
    ]
    _write_ledger(ca, linea)
    assert ca.m.scan(True, False) == 0
    assert "IM-9" in ca.sent[-1][1]


def test_a1_objetos_separados_por_espacios_y_espacios_al_final_se_evaluan(ca):
    """A1: espacios entre los objetos fusionados y tras el ultimo no esconden ni inventan filas."""
    linea = "  " + _PROPIA.decode() + "   " + _AJENA_FAIL.decode() + "  \t "
    assert ca.m._scan_chunk(linea, ca.m._failure_resultados()) == [
        {"to": "IM-9", "status": "FAIL"}
    ]
    solo_propia = "  " + _PROPIA.decode() + "   "
    assert ca.m._scan_chunk(solo_propia, ca.m._failure_resultados()) == []


def test_a1_fila_ajena_rota_que_solo_menciona_comms_alert_cuenta(ca):
    """A1 (ii): ajena rota que solo MENCIONA comms_alert (no es suya) sigue contando por el ultimo recurso."""
    linea = '{"by":"CO-24","resultado":"FAIL","nota":"revisar comms_alert"\n'
    assert ca.m._scan_chunk(linea, ca.m._failure_resultados()) == [
        {"to": "?", "status": "FAIL (linea no parseable)"}
    ]
    _write_ledger(ca, linea.encode())
    assert ca.m.scan(True, False) == 0


@pytest.mark.parametrize(
    "linea",
    [
        _PROPIA + _PROPIA,
        _PROPIA + b'{"from":"comms_alert","status":"ALERT_FALLIDO","what":"FAIL"}',
        b'{"by":"comms_alert","mensaje_id":"comms_alert:x","resultado":"ALERT","nota":"FAIL parent_not_active"',
        b'{"from":"comms_alert","status":"ALERT_FALLIDO","what":"x","note":"FAIL"',
        _PROPIA + b'{"by":"comms_alert","nota":"FAIL parent_not_active"',
    ],
)
def test_a1_control_negativo_lo_que_es_solo_propio_no_cuenta(ca, linea):
    """A1, control negativo: una linea compuesta SOLO de filas propias (completas, fusionadas o rotas) no cuenta."""
    assert ca.m._scan_chunk(linea.decode() + "\n", ca.m._failure_resultados()) == []


@pytest.mark.parametrize(
    "registro",
    [
        {},
        {"level": "AVISO", "acked": "false"},
        {"level": "URGENTE", "acked": "false", "last": 1},
        {"level": "ROJO", "acked": False, "last": 1},
        {"level": "URGENTE", "last": "x"},
        {"level": "AVISO", "acked": 1},
        {"level": None, "acked": False},
    ],
)
def test_a2_registro_con_forma_inutilizable_es_ausente_y_el_aviso_sale(ca, registro):
    """A2: sin level valido, con `acked` no booleano o `last` no numerico el registro no silencia nada."""
    ca.m.save_state({"event:k": registro})
    assert ca.m.event("k", "AVISO", None, "x", False, False) == 0
    assert len(ca.sent) == 1


@pytest.mark.parametrize(
    "registro",
    [
        {"level": "AVISO", "acked": False},
        {"level": "AVISO", "acked": True, "last": 1},
        {"level": "URGENTE", "acked": True, "last": 1},
    ],
)
def test_a2_control_negativo_un_registro_valido_si_silencia(ca, registro):
    """A2, control negativo: la forma valida (AVISO ya avisado o URGENTE acked) sigue limitando."""
    registro = {**registro, "last": ca.clock.now - 60}
    ca.m.save_state({"event:k": registro})
    assert ca.m.event("k", registro["level"], None, "x", False, False) == 10
    assert ca.sent == []


# ---- ronda 2 (B1): ENUMERACION de formas de linea con piezas propias/ajenas, completas/rotas, en los dos ordenes
_FORMAS_B1 = [
    # (a) propia rota + ajena completa que la sigue
    (
        '{"by":"comms_alert","nota":"rota {"from":"CO-24","a":"IM-9","resultado":"FAIL"}',
        ["IM-9"],
    ),
    # (b) ajena rota con FAIL + propia completa
    (
        '{"from":"CO-24","resultado":"FAIL","nota":"rota {"by":"comms_alert","mensaje_id":"comms_alert:x","resultado":"ALERT"}',
        ["?"],
    ),
    # (c) propia rota (sin cerrar) + ajena completa pegada
    (
        '{"by":"comms_alert","mensaje_id":"comms_alert:x","resultado":"ALERT"{"from":"CO-24","a":"IM-9","resultado":"FAIL"}',
        ["IM-9"],
    ),
    # propia completa + ajena rota con FAIL
    (_PROPIA.decode() + '{"from":"CO-24","resultado":"FAIL","nota":"x"', ["?"]),
    # ajena completa + propia rota con FAIL en su texto: cuenta SOLO la ajena
    (
        _AJENA_FAIL.decode() + '{"by":"comms_alert","nota":"FAIL parent_not_active"',
        ["IM-9"],
    ),
    # ajena completa + propia completa (orden inverso al de A1)
    (_AJENA_FAIL.decode() + _PROPIA.decode(), ["IM-9"]),
    # ajena rota + ajena completa: son dos fallos reales
    (
        '{"from":"CO-24","resultado":"FAIL"{"from":"CO-25","a":"IM-3","resultado":"FAIL"}',
        ["?", "IM-3"],
    ),
    # basura delante de un objeto ajeno completo
    ('basura {"from":"CO-24","a":"IM-9","resultado":"FAIL"}', ["IM-9"]),
    # anidado: el objeto propio dentro de uno ajeno no lo hace propio (decide la clave de primer nivel)
    (
        '{"from":"CO-24","a":"IM-9","resultado":"FAIL","x":{"by":"comms_alert","mensaje_id":"comms_alert:y"}}',
        ["IM-9"],
    ),
    # sin ninguna `{` decodificable: el ultimo recurso por subcadena
    ("texto FAIL sin llaves", ["?"]),
]


@pytest.mark.parametrize(("linea", "esperado"), _FORMAS_B1)
def test_b1_formas_de_linea_mixta_cuentan_el_fail_ajeno(ca, linea, esperado):
    """B1: cada forma hermana de A1 cuenta exactamente los fallos AJENOS (el resto de la linea se resincroniza)."""
    got = ca.m._scan_chunk(linea + "\n", ca.m._failure_resultados())
    assert [g["to"] for g in got] == esperado


@pytest.mark.parametrize(
    "linea",
    [
        '{"by":"comms_alert","nota":"a {"by":"comms_alert","nota":"FAIL parent_not_active"',
        _PROPIA.decode() + '{"by":"comms_alert","nota":"FAIL"',
        '{"from":"CO-24","resultado":"enviado","nota":"x {"',
        "texto sin llaves ni fallo",
        "[" * 100000,
    ],
    ids=[
        "propio_roto_x2",
        "propio_completo_y_roto",
        "ajena_sin_fallo",
        "sin_llaves",
        "anidado_profundo",
    ],
)
def test_b1_control_negativo_lo_que_no_es_un_fallo_ajeno_no_cuenta(ca, linea):
    """B1, control negativo: solo-propio roto (en varios trozos), ajena sin fallo, sin llaves o anidado profundo: 0, sin excepcion."""
    assert ca.m._scan_chunk(linea + "\n", ca.m._failure_resultados()) == []


# ---- ronda 2 (B2): valores numericos no finitos o enormes en el estado = registro ilegible, el aviso sale
_NUM_MALOS = [
    "1e309",
    "-1e309",
    "NaN",
    "Infinity",
    "-Infinity",
    "1" + "0" * 400,
    "true",
]
_NUM_IDS = ["inf", "-inf", "nan", "Infinity", "-Infinity", "int_enorme", "bool"]


@pytest.mark.parametrize("malo", _NUM_MALOS, ids=_NUM_IDS)
def test_b2_last_no_finito_o_enorme_es_ilegible_y_el_aviso_sale(ca, malo):
    ca.m.STATE.write_text(
        f'{{"event:k": {{"level": "URGENTE", "last": {malo}, "nu": 1, "acked": false}}}}',
        encoding="utf-8",
    )
    assert ca.m.event("k", "URGENTE", "t", "w", False, False) == 0
    assert len(ca.sent) == 1


@pytest.mark.parametrize("malo", _NUM_MALOS, ids=_NUM_IDS)
def test_b2_alert_manual_con_marca_no_finita_o_enorme_avisa(ca, malo):
    ca.m.STATE.write_text(f'{{"k": {malo}}}', encoding="utf-8")
    assert ca.m.alert("k", "w", "e", False, False) == 0
    assert len(ca.sent) == 1


@pytest.mark.parametrize("malo", _NUM_MALOS, ids=_NUM_IDS)
def test_b2_n_nu_y_first_malos_no_rompen_el_aviso_ni_el_guardado(ca, malo):
    """B2: `n`, `nu` y `first` con basura numerica no lanzan; el registro se reescribe y sigue legible."""
    vieja = ca.clock.now - 5 * 3600  # mas que el tope de 4 h del backoff
    ca.m.STATE.write_text(
        f'{{"event:k": {{"level": "URGENTE", "last": {vieja}, "first": {malo}, "n": {malo}, "nu": {malo}, "acked": false}}}}',
        encoding="utf-8",
    )
    assert ca.m.event("k", "URGENTE", "t", "w", False, False) == 0
    assert isinstance(ca.m.load_state()["event:k"]["last"], float)
    reciente = ca.clock.now - 60
    ca.m.STATE.write_text(
        f'{{"event:k": {{"level": "AVISO", "last": {reciente}, "n": {malo}, "acked": false}}}}',
        encoding="utf-8",
    )
    assert ca.m.event("k", "AVISO", "t", "w", False, False) == 10


def test_b2_control_negativo_numeros_normales_siguen_limitando(ca):
    reciente = ca.clock.now - 60
    ca.m.STATE.write_text(
        f'{{"event:k": {{"level": "AVISO", "last": {reciente}, "n": 3, "acked": false}}}}',
        encoding="utf-8",
    )
    assert ca.m.event("k", "AVISO", "t", "w", False, False) == 10
    assert ca.sent == []


# ---- ronda 2 (B4): transicion AVISO -> URGENTE y su contador `nu`
def test_b4_aviso_no_cuenta_en_nu_y_la_transicion_a_urgente_empieza_el_backoff_en_30_min(
    ca,
):
    assert ca.m.event("k", "AVISO", "t", "w", False, False) == 0
    assert ca.m.load_state()["event:k"]["nu"] == 0
    ca.clock.now += 1 * M
    assert ca.m.event("k", "URGENTE", "t", "w", False, False) == 0  # sube de nivel
    assert ca.m.load_state()["event:k"]["nu"] == 1
    ca.clock.now += 29 * M
    assert (
        ca.m.event("k", "URGENTE", "t", "w", False, False) == 10
    )  # dentro de los 30 min
    ca.clock.now += 2 * M
    assert (
        ca.m.event("k", "URGENTE", "t", "w", False, False) == 0
    )  # nu=1 => espera 30 min
    assert ca.m.load_state()["event:k"]["nu"] == 2


# ---- ronda 3 (C1): JSON de estado muy anidado
def test_c1_estado_muy_anidado_se_trata_como_vacio_y_el_aviso_sale(ca):
    """C1: un RecursionError del parser no escapa de load_state; el estado cuenta como vacio y el aviso sale."""
    ca.m.STATE.write_text('{"a":' + "[" * 3000 + "]" * 3000 + "}", encoding="utf-8")
    assert ca.m.load_state() == {}
    assert ca.m.event("k", "URGENTE", "t", "w", False, False) == 0
    assert len(ca.sent) == 1


def test_c1_control_negativo_un_anidado_moderado_sigue_leyendose(ca):
    ca.m.STATE.write_text('{"x": ' + "[" * 50 + "]" * 50 + "}", encoding="utf-8")
    assert "x" in ca.m.load_state()


# ---- ronda 3 (C2): la resincronizacion solo corta en una `{` que abre un objeto plausible
@pytest.mark.parametrize(
    "linea",
    [
        '{"by":"comms_alert","mensaje_id":"comms_alert:x","resultado":"ALERT","nota":"detalle {FAIL"',
        '{"by":"comms_alert","mensaje_id":"comms_alert:x","resultado":"ALERT","nota":"a { FAIL parent_not_active"',
        '{"by":"comms_alert","mensaje_id":"comms_alert:x","resultado":"ALERT","nota":"x {FAIL y {FAIL"',
    ],
    ids=["llave_pegada", "llave_con_espacio", "dos_llaves"],
)
def test_c2_llave_suelta_en_el_texto_de_una_fila_propia_rota_no_es_un_fallo_ajeno(
    ca, linea
):
    assert ca.m._scan_chunk(linea + "\n", ca.m._failure_resultados()) == []


@pytest.mark.parametrize(
    "linea",
    [
        '{"by":"comms_alert","nota":"rota {  "from":"CO-24","a":"IM-9","resultado":"FAIL"}',
        '{"by":"comms_alert","nota":"x {}{"from":"CO-24","a":"IM-9","resultado":"FAIL"}',
        '{"by":"comms_alert","nota":"x {\t"from":"CO-24","a":"IM-9","resultado":"FAIL"}',
    ],
    ids=["espacios", "llaves_vacias", "tabulador"],
)
def test_c2_la_resincronizacion_sigue_viendo_un_objeto_plausible(ca, linea):
    """C2, positivos de B1: `{` + espacios (o `{}`) + `"` sigue siendo un objeto ajeno completo."""
    got = ca.m._scan_chunk(linea + "\n", ca.m._failure_resultados())
    assert [g["to"] for g in got] == ["IM-9"]


# ---- ronda 3 (C3): cota y tipo de los numeros del estado, con un epoch realista
def test_c3_la_cota_de_numeros_respeta_un_epoch_real_y_rechaza_un_valor_absurdo(ca):
    ca.clock.now = 1.77e9
    ca.m.STATE.write_text(
        '{"event:k": {"level": "AVISO", "last": %r, "acked": false}}' % (1.77e9 - 60),
        encoding="utf-8",
    )
    assert ca.m.event("k", "AVISO", "t", "w", False, False) == 10  # limita
    assert ca.sent == []
    ca.m.STATE.write_text(
        '{"event:k": {"level": "AVISO", "last": 1e15, "acked": false}}',
        encoding="utf-8",
    )
    assert ca.m.event("k", "AVISO", "t", "w", False, False) == 0  # ilegible: avisa
    assert len(ca.sent) == 1


def test_c3_un_booleano_en_last_no_es_un_numero_y_el_aviso_sale(ca):
    ca.m.STATE.write_text(
        '{"event:k": {"level": "AVISO", "last": true, "acked": false}}',
        encoding="utf-8",
    )
    assert ca.m.event("k", "AVISO", "t", "w", False, False) == 0
    assert len(ca.sent) == 1


def test_a4_redact_cubre_el_uuid_suelto_sin_prefijo_mcp(ca):
    """A4: un UUID sin `mcp:` (cualquier capitalizacion) tambien se oculta; uno que no lo es, no."""
    suelto = "3921a7b1-8f23-4016-898c-8abc7e58c8a9"
    assert ca.m.redact(f"hilo {suelto} ok") == "hilo <uuid> ok"
    assert ca.m.redact(f"hilo {suelto.upper()} ok") == "hilo <uuid> ok"
    assert ca.m.redact("hilo 3921a7b1-8f23 ok") == "hilo 3921a7b1-8f23 ok"


def test_fila60_scan_linea_parcial_no_se_consume(ca):
    """fila 60: linea JSON incompleta no se consume hasta completarse."""
    _write_ledger(ca, b'{"from":"CO-24","a":"x","resultado":"FA')
    assert ca.m.scan(False, False) == 10
    assert ca.m.load_state()["_last_scan_offset"] == 0
    ca.m.LEDGER.write_bytes(
        ca.m.LEDGER.read_bytes() + b'IL","error":"parent_not_active"}\n'
    )
    assert ca.m.scan(True, False) == 0
    assert len(ca.sent) == 1


def test_fila62_scan_ignora_filas_en_blanco_y_no_diccionario(ca):
    """fila 62: el scan ignora lineas en blanco y valores que no son diccionario."""
    _write_ledger(ca, b'\n\n[1, 2]\n"x"\nnull\n123\n')
    assert ca.m.scan(True, False) == 10
    assert ca.sent == []


def test_fila64_scan_detecta_el_prefijo_fail_de_filas_antiguas(ca):
    """fila 64: el scan detecta el prefijo FAIL en el campo status de filas antiguas."""
    _write_ledger(
        ca,
        b'{"from":"CO-24","to":"IM-9","status":"FAIL parent_not_active"}\n',
    )
    assert ca.m.scan(True, False) == 0
    assert "IM-9" in ca.sent[-1][1]
    assert "parent_not_active" in ca.sent[-1][1]


def test_fila68_scan_dry_run_no_escribe_el_offset_ni_el_ledger(ca):
    """fila 68: dry-run no escribe el offset ni modifica el ledger."""
    _write_ledger(ca, _fail_row(), offset=0)
    antes = ca.m.LEDGER.read_bytes()
    assert ca.m.scan(True, True) == 0
    assert ca.m.load_state()["_last_scan_offset"] == 0
    assert ca.m.LEDGER.read_bytes() == antes


def test_fila68b_scan_dry_run_sin_novedad_tampoco_escribe_el_offset(ca):
    """fila 68b: dry-run sin novedad tampoco escribe el offset."""
    _write_ledger(ca, b'{"x":1}\n', offset=0)
    assert ca.m.scan(False, True) == 10
    assert ca.m.load_state()["_last_scan_offset"] == 0


def test_fila55b_alert_dry_run_no_escribe_estado_ni_ledger(ca):
    """fila 55b: alert con dry-run no escribe el estado ni el ledger."""
    assert ca.m.alert("k", "w", "e", False, True) == 0
    assert not ca.m.STATE.exists()
    assert not ca.m.LEDGER.exists()


@pytest.mark.parametrize(
    "value",
    [
        "Escribe GO 1\nforjada",
        "Escribe GO 1\rforjada",
        "Escribe GO 1\u2028forjada",
        "Escribe GO 1\u2029forjada",
        "Escribe GO 1\u0085forjada",
        "Escribe GO 1\u000bforjada",
        "Escribe GO 1\u000cforjada",
        "Escribe GO 1\u001cforjada",
        "Escribe GO 1\u001dforjada",
        "Escribe GO 1\u001eforjada",
        "Escribe RESUELTA ahora",
        "Escribe ABIERTA ahora",
        "Escribe BLOQUEA ahora",
        "Escribe | GO 1",
        "\ufeffEscribe GO 1",
    ],
)
def test_go_rechaza_inyeccion_de_cola_sin_escribir_ni_notificar(ca, value):
    """E1: texto no monolineal o reservado devuelve 2 sin efectos observables."""
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"# cola existente\n")
    antes = cola.read_bytes()
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--go-id",
                "go-e1",
                "--what",
                value,
            ]
        )
        == 2
    )
    assert cola.read_bytes() == antes
    assert ca.sent == []


@pytest.mark.parametrize(
    "go_id",
    [
        "go-a",
        "go-" + "a" * 61,
        "go",
        "go-",
        "go--",
        "go-a-",
        "go-A",
        "go_a",
        "go-" + "a" * 62,
    ],
)
def test_go_id_gramatica_cerrada_y_fronteras(ca, go_id):
    """E1: go-id sólo admite la gramática cerrada y rechaza sus fronteras inválidas."""
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"# cola existente\n")
    antes = cola.read_bytes()
    assert ca.m.main(
        [
            "--ops-dir",
            str(ca.dir),
            "--flight-dir",
            str(flight),
            "--go-id",
            go_id,
            "--what",
            "Escribe GO 1",
        ]
    ) == (0 if go_id in {"go-a", "go-" + "a" * 61} else 2)
    if go_id not in {"go-a", "go-" + "a" * 61}:
        assert cola.read_bytes() == antes
        assert ca.sent == []


def test_go_sin_owner_rechaza_rc2_sin_mutar(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"# cola\n")
    antes = cola.read_bytes()
    assert (
        ca.m._raw_main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--go-id",
                "go-owner",
                "--what",
                "Escribe GO",
            ]
        )
        == 2
    )
    assert cola.read_bytes() == antes


def test_go_acepta_cola_vacia_y_append_especifico(ca):
    """E2/E3: cola vacía es válida y el primer GO se añade sin reescribirla."""
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--go-id",
                "go-e2",
                "--what",
                "Escribe GO 1",
            ]
        )
        == 0
    )
    assert cola.read_bytes().endswith(
        b"] [IM-56] ABIERTA BLOQUEA | go-e2: Escribe GO 1\n"
    )
    assert ca.sent == [("IM-56", "Escribe GO 1")]


@pytest.mark.parametrize(
    "original",
    [
        b"# cola\n- [old] [CO-1] ABIERTA | vieja\n",
        b"# cola\r\n- [old] [CO-1] ABIERTA | vieja\r\n",
        b"\xef\xbb\xbf# cola\n- [old] [CO-1] ABIERTA | vieja\n",
        b"# cola\n- [old] [CO-1] ABIERTA | vieja",
    ],
)
def test_go_append_conserva_bytes_y_formato_de_eol(ca, original):
    """E3: append no reescribe el prefijo y produce una línea exacta consumible."""
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(original)
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--go-id",
                "go-e3",
                "--what",
                "Escribe GO 1",
            ]
        )
        == 0
    )
    producido = b"] [IM-56] ABIERTA BLOQUEA | go-e3: Escribe GO 1"
    datos = cola.read_bytes()
    eol = b"\r\n" if b"\r\n" in original else b"\n"
    assert datos.endswith(producido + eol)


def test_go_misma_clave_idempotente_y_conflicto_no_silencioso(ca):
    """E4: misma clave/frase da 10; misma clave/frase distinta da 2."""
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    args = [
        "--ops-dir",
        str(ca.dir),
        "--flight-dir",
        str(flight),
        "--go-id",
        "go-e4",
        "--what",
        "Escribe GO 1",
    ]
    assert ca.m.main(args) == 0
    antes = cola.read_bytes()
    assert ca.m.main(args) == 10
    assert cola.read_bytes() == antes
    assert ca.sent == [("IM-56", "Escribe GO 1")]
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--go-id",
                "go-e4",
                "--what",
                "Escribe GO 2",
            ]
        )
        == 2
    )
    assert cola.read_bytes() == antes


def test_go_fallo_de_notificador_conserva_linea_y_devuelve_2(ca):
    """E6: append precede al aviso; un fallo queda reintentable y fail-closed."""
    ca.mode["rc"] = 2
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--go-id",
                "go-e6",
                "--what",
                "Escribe GO 1",
            ]
        )
        == 2
    )
    assert cola.read_bytes().endswith(
        b"] [IM-56] ABIERTA BLOQUEA | go-e6: Escribe GO 1\n"
    )
    assert ca.m.load_state() == {}


def test_go_reintento_tras_fallo_reavisa_sin_duplicar_linea(ca):
    """E6: sin evento registrado, la misma petición reintenta y luego queda idempotente."""
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    ca.mode["rc"] = 2
    args = [
        "--ops-dir",
        str(ca.dir),
        "--flight-dir",
        str(flight),
        "--go-id",
        "go-r",
        "--what",
        "Escribe GO 1",
    ]
    assert ca.m.main(args) == 2
    ca.mode["rc"] = 0
    assert ca.m.main(args) == 0
    assert ca.m.main(args) == 10
    assert cola.read_bytes().endswith(
        b"] [IM-56] ABIERTA BLOQUEA | go-r: Escribe GO 1\n"
    )
    assert ca.sent == [
        ("IM-56", "Escribe GO 1"),
        ("IM-56", "Escribe GO 1"),
    ]


def _go_args(ca, flight, go_id, what="Escribe GO 1"):
    return [
        "--ops-dir",
        str(ca.dir),
        "--flight-dir",
        str(flight),
        "--go-id",
        go_id,
        "--what",
        what,
    ]


def test_go_resolve_dry_run_no_muta_cola_y_consumidor_real(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"# cola\n")
    assert ca.m.main(_go_args(ca, flight, "go-r4a")) == 0
    antes = cola.read_bytes()
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4a",
                "--dry-run",
            ]
        )
        == 0
    )
    assert cola.read_bytes() == antes
    assert _consumer_findings(cola)[0][0] == "go-r4a"


def test_go_sin_efecto_end_to_end_resuelve_consumidor_real(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    assert ca.m.main(_go_args(ca, flight, "go-r4b")) == 0
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4b",
                "--sin-efecto",
            ]
        )
        == 0
    )
    assert b"RESUELTA-SIN-EFECTO | go-r4b:" in cola.read_bytes()
    assert _consumer_findings(cola) == []


def test_go_sin_efecto_mezclado_con_request_rechaza_sin_mutar(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"# cola\n")
    antes = cola.read_bytes()
    assert ca.m.main([*_go_args(ca, flight, "go-r4c"), "--sin-efecto"]) == 2
    assert cola.read_bytes() == antes


def test_go_resolve_owner_sin_flight_y_event_mezclado_rechazan_sin_mutar(ca, capsys):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    antes = cola.read_bytes()
    assert (
        ca.m.main(
            ["--ops-dir", str(ca.dir), "--resolve", "go-r4c1", "--owner", "CO-28"]
        )
        == 2
    )
    assert "--flight-dir" in capsys.readouterr().err
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4c1",
                "--owner",
                "CO-28",
                "--event",
                "otra",
            ]
        )
        == 2
    )
    assert cola.read_bytes() == antes


def test_go_notify_fallido_resolve_y_tick_real_no_avisa(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    ca.mode["rc"] = 2
    assert ca.m.main(_go_args(ca, flight, "go-r4d")) == 2
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4d",
            ]
        )
        == 0
    )
    assert "event:go-r4d" not in ca.m.load_state()
    assert _consumer_findings(cola) == []


def test_go_reabrir_resuelto_rechaza_incluso_notify_fallido(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    assert ca.m.main(_go_args(ca, flight, "go-r4e")) == 0
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4e",
            ]
        )
        == 0
    )
    antes = cola.read_bytes()
    ca.mode["rc"] = 2
    assert ca.m.main(_go_args(ca, flight, "go-r4e")) == 2
    assert cola.read_bytes() == antes


def test_go_resolve_inexistente_rc10_sin_mutar(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"# cola\n")
    antes = cola.read_bytes()
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4f",
            ]
        )
        == 10
    )
    assert cola.read_bytes() == antes


def test_go_cola_no_utf8_rc2_sin_mutar(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"# invalida \xff\n")
    antes = cola.read_bytes()
    assert ca.m.main(_go_args(ca, flight, "go-r4g")) == 2
    assert cola.read_bytes() == antes
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4g",
            ]
        )
        == 2
    )
    assert cola.read_bytes() == antes


def test_go_cola_ausente_request_rc2_resolve_rc10(ca):
    flight = ca.dir / "flight"
    (flight / "diseno").mkdir(parents=True)
    assert ca.m.main(_go_args(ca, flight, "go-r4h")) == 2
    assert not (flight / "diseno" / "COLA_PARA_USUARIO.md").exists()
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4h",
            ]
        )
        == 10
    )


def test_go_resolve_elimina_evento_y_segundo_resolve_es_idempotente(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    assert ca.m.main(_go_args(ca, flight, "go-r4i")) == 0
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4i",
            ]
        )
        == 0
    )
    assert "event:go-r4i" not in ca.m.load_state()
    antes = cola.read_bytes()
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4i",
            ]
        )
        == 10
    )
    assert cola.read_bytes() == antes


def test_go_resolve_reconcilia_marcador_previo_con_evento_activo(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    assert ca.m.main(_go_args(ca, flight, "go-r5-crash")) == 0
    cola.write_bytes(
        cola.read_bytes()
        + b"- [2026-11-04 10:00:00] [CO-28] RESUELTA | go-r5-crash: RESUELTA\n"
    )
    assert "event:go-r5-crash" in ca.m.load_state()
    antes = cola.read_bytes()
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r5-crash",
            ]
        )
        == 0
    )
    assert cola.read_bytes() == antes
    assert "event:go-r5-crash" not in ca.m.load_state()


def test_go_redacta_ruta_y_secreto_en_aviso_inmediato_y_tick(ca, capsys):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    real_notify = _load("comms_alert_notify_real").notify
    recibido = []

    def captura_notify(title, message, dry, **kwargs):
        recibido.append((title, message, dry))
        return real_notify(title, message, True)

    ca.m.notify = captura_notify
    phrase = r"usa C:\Users\fdl\privada\token-secreto"
    assert ca.m.main(_go_args(ca, flight, "go-redact", phrase)) == 0
    assert recibido[-1][1] == r"usa C:\Users\fdl\privada\<secreto>"
    salida = capsys.readouterr().out
    assert phrase not in salida
    assert "<ruta>" in salida
    findings = _consumer_findings(cola)
    rendered = " ".join(str(item) for item in findings)
    assert "token-secreto" not in rendered
    assert "<ruta>" in rendered or "<secreto>" in rendered


def test_go_resolve_destino_invalido_rc2_sin_mutar_estado(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    assert ca.m.main(_go_args(ca, flight, "go-destino")) == 0
    antes_estado = ca.m.load_state()
    antes_cola = cola.read_bytes()
    for destino in ("flight-relativo", str(ca.dir / "no-existe")):
        assert (
            ca.m.main(
                [
                    "--ops-dir",
                    str(ca.dir),
                    "--flight-dir",
                    destino,
                    "--resolve",
                    "go-destino",
                    "--owner",
                    "CO-28",
                ]
            )
            == 2
        )
        assert cola.read_bytes() == antes_cola
        assert ca.m.load_state() == antes_estado


@pytest.mark.parametrize(
    "extra",
    [
        ["--what", ""],
        ["--what", "x" * 161],
        ["--owner", "bad-owner"],
    ],
)
def test_go_request_argumentos_invalidos_rc2_sin_mutar_cola(ca, extra):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"# cola\n")
    antes = cola.read_bytes()
    args = [
        "--ops-dir",
        str(ca.dir),
        "--flight-dir",
        str(flight),
        "--go-id",
        "go-invalid-args",
        "--what",
        "Escribe GO 1",
    ]
    if extra[0] == "--what":
        args[args.index("--what") + 1] = extra[1]
    else:
        args.extend(extra)
    assert ca.m.main(args) == 2
    assert cola.read_bytes() == antes


def test_go_ack_y_resolve_control(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    assert ca.m.main(_go_args(ca, flight, "go-ack-control")) == 0
    assert ca.m.main(["--ops-dir", str(ca.dir), "--ack", "go-ack-control"]) == 0
    assert ca.m.load_state()["event:go-ack-control"]["acked"] is True
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-ack-control",
            ]
        )
        == 0
    )
    assert "event:go-ack-control" not in ca.m.load_state()


def test_go_request_resolve_entrelazado_no_deja_evento(ca):
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    entered = threading.Event()
    release = threading.Event()
    real_event = ca.m.event

    def paused_event(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return real_event(*args, **kwargs)

    ca.m.event = paused_event
    result = []

    def request():
        result.append(ca.m.main(_go_args(ca, flight, "go-r4j")))

    thread = threading.Thread(target=request)
    thread.start()
    assert entered.wait(timeout=5)
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--resolve",
                "go-r4j",
            ]
        )
        == 0
    )
    release.set()
    thread.join(timeout=5)
    assert result == [0]
    assert "event:go-r4j" not in ca.m.load_state()
    assert b"RESUELTA | go-r4j:" in cola.read_bytes()


def test_go_resolve_concurrent_no_pierde_lineas(ca):
    """E5: dos productores concurrentes conservan ambos GO y su resolución es explícita."""
    cola = ca.dir / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    resultados = []
    errores = []

    def emitir(go_id):
        try:
            resultados.append(
                ca.m.main(
                    [
                        "--ops-dir",
                        str(ca.dir),
                        "--flight-dir",
                        str(ca.dir),
                        "--go-id",
                        go_id,
                        "--owner",
                        "IM-56",
                        "--what",
                        f"Escribe {go_id}",
                    ]
                )
            )
        except (
            BaseException
        ) as exc:  # argparse/SystemExit también es evidencia RED del CLI ausente.
            errores.append(exc)

    hilos = [
        threading.Thread(target=emitir, args=(go_id,)) for go_id in ("go-a", "go-b")
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    contenido = cola.read_text(encoding="utf-8")
    assert errores == []
    assert sorted(resultados) == [0, 0]
    assert "go-a" in contenido and "go-b" in contenido
    assert (
        ca.m.main(
            [
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(ca.dir),
                "--resolve",
                "go-a",
                "--owner",
                "IM-56",
            ]
        )
        == 0
    )
    assert "RESUELTA | go-a:" in cola.read_text(encoding="utf-8")


def test_go_dos_procesos_y_escritor_crudo_no_funden_ni_pierden_lineas(ca):
    """E5: dos procesos y un tercero crudo conservan líneas completas bajo contención."""
    flight = ca.dir / "flight"
    cola = flight / "diseno" / "COLA_PARA_USUARIO.md"
    cola.parent.mkdir(parents=True)
    cola.write_bytes(b"")
    worker = (
        "import importlib.util, sys; "
        "spec=importlib.util.spec_from_file_location('ca', sys.argv[1]); "
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
        "m.notify=lambda title,message,dry,**kwargs: 0; "
        "raise SystemExit(m.main(sys.argv[2:]))"
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                worker,
                str(CA_PATH),
                "--ops-dir",
                str(ca.dir),
                "--flight-dir",
                str(flight),
                "--go-id",
                go_id,
                "--owner",
                "IM-56",
                "--what",
                f"Escribe {go_id}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for go_id in ("go-proc-a", "go-proc-b")
    ]
    with cola.open("ab") as handle:
        handle.write(b"- [go-raw] [IM-57] ABIERTA BLOQUEA | Escribe GO raw\n")
    assert [process.wait(timeout=10) for process in processes] == [0, 0]
    lines = cola.read_bytes().splitlines(keepends=True)
    assert len(lines) == 3
    assert all(line.endswith(b"\n") for line in lines)
    assert all(
        token in b"".join(lines) for token in (b"go-proc-a", b"go-proc-b", b"go-raw")
    )


def test_153n_redacta_unc_y_conserva_control_negativo(ca):
    assert ca.m.redact(r"UNC \\server\share\secret.txt") == "UNC <ruta>"
    assert (
        ca.m.redact("https://server/share/secret.txt")
        == "https://server/share/secret.txt"
    )


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer SYNTHETIC_BEARER_123",
        "Bearer SYNTHETIC_BEARER_123",
        "token SYNTHETIC_TOKEN_123",
        "api-key=SYNTHETIC_API_123",
        "api_key: SYNTHETIC_API_123",
        "apikey SYNTHETIC_API_123",
        "ghp_SYNTHETIC_123",
        "gho_SYNTHETIC_123",
        "ghu_SYNTHETIC_123",
        "ghs_SYNTHETIC_123",
        "ghr_SYNTHETIC_123",
        "github_pat_SYNTHETIC_123",
        "sk-SYNTHETIC_123",
    ],
)
def test_153n_redacta_patrones_cerrados_de_secretos(ca, value):
    assert "SYNTHETIC" not in ca.m.redact(value)


@pytest.mark.parametrize(
    "value",
    [
        "api_key = abcdEFGH1234",
        "api_key  =  secretvalueXYZ",
        "API_KEY   =   abc12345678",
        "apikey = rotation12",
        "api_key\t=\tabcdEFGH1234",
    ],
)
def test_153n_api_key_con_espacios_alrededor_del_separador_se_redacta(ca, value):
    assert "key" not in ca.m.redact(value).lower()
    assert "abcd" not in ca.m.redact(value).lower()


@pytest.mark.parametrize(
    "value",
    [
        "risk-assessment",
        "disk-1234abcdefgh",
        "task-force",
        "el token expira mañana",
        "token validation failed in step 3",
        "token verification pending",
        "token expiration soon",
        "apikey rotation scheduled",
        "Bearer es un apellido sin valor",
        "sk- es un prefijo citado sin valor",
    ],
)
def test_153n_redacta_sin_falsos_positivos_legitimos(ca, value):
    assert ca.m.redact(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "token abcDEF1234567890",
        "api-key SYNTH12345678",
        "api_key: SYNTH12345678",
        "apikey SYNTH12345678",
    ],
)
def test_153n_exige_digito_en_secretos_separados_por_espacio(ca, value):
    assert "SYNTH" not in ca.m.redact(value)


@pytest.mark.parametrize(
    ("prefix", "short_value", "long_value"),
    [
        ("ghp_", "ghp_1234567", "ghp_12345678"),
        ("sk-", "sk-1234567", "sk-12345678"),
    ],
)
def test_153n_prefijos_respetan_frontera_de_ocho_caracteres(
    ca, prefix, short_value, long_value
):
    assert ca.m.redact(short_value) == short_value
    assert ca.m.redact(long_value) == "<secreto>"


def test_153n_unc_respeta_limite_izquierdo(ca):
    assert ca.m.redact(r"abc\\srv\share\x") == r"abc\\srv\share\x"
    assert ca.m.redact(r"\\srv\share\x") == "<ruta>"


@pytest.mark.parametrize(
    "value",
    [
        r"\\server\shared folder\private.txt",
        r"C:\shared folder\private.txt",
    ],
)
def test_153n_caracteriza_ruta_con_espacio_y_cola_visible(ca, value):
    assert ca.m.redact(value).endswith(" folder\\private.txt")
    assert ca.m.redact(value).startswith("<ruta>")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Bearer authentication failed", "<secreto> failed"),
        ("token 2026-11-06", "<secreto>"),
        ("Bearer 2026-11-06", "<secreto>"),
        ("//server/share", "//server/share"),
    ],
)
def test_153n_caracteriza_limites_y_sobre_redacciones_mediadas(ca, value, expected):
    assert ca.m.redact(value) == expected


@pytest.mark.parametrize(
    "template",
    [
        "Authorization: Bearer {value}",
        "Bearer {value}",
        "token {value}",
        "api-key={value}",
        "api_key = {value}",
        "apikey {value}",
        "ghp_{value}",
        "sk-{value}",
        "token={value}",
        "secret:{value}",
    ],
)
@pytest.mark.parametrize("length", range(1, 13))
def test_153n_redact_idempotente_si_el_corte_cae_en_cualquier_secreto(
    ca, template, length
):
    value = "a" * max(0, length - 1) + "1"
    body = template.format(value=value)
    fixed_length = len(body) - length
    prefix_length = ca.m.TEXT_LIMIT - 3 - fixed_length - length
    raw = "!" * max(0, prefix_length) + body + " fin!"
    assert len(raw) > ca.m.TEXT_LIMIT
    once = ca.m.redact(raw)
    assert ca.m.redact(once) == once


def test_153n_redacta_stdout_antes_de_truncar(ca, monkeypatch, capsys):
    real = _load("notify_153n_real")
    real.configure(str(ca.dir))

    class Result:
        returncode = 0
        stdout = ""

    seen = []
    full_bearer_value = "Bearer abcdefgh12345678"

    def fake_redact(value):
        seen.append(value)
        return value.replace(full_bearer_value, "<secreto>")

    monkeypatch.setattr(real, "_powershell_exe", lambda: Path("powershell.exe"))
    monkeypatch.setattr(real.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(real, "redact", fake_redact)

    Result.stdout = ("a" * 195) + " " + full_bearer_value + "\n"
    assert real.notify("title", "message", False) == 0
    output = capsys.readouterr().out
    assert seen[-1].endswith(full_bearer_value)
    assert " Bear" not in output

    Result.stdout = "a" * 250
    assert real.notify("title", "message", False) == 0
    control = capsys.readouterr().out
    assert len(control.split("notify rc=0 ", 1)[1].rstrip("\n")) == 200


def test_153n_preserve_literal_redacta_secretos_nuevos_y_conserva_ruta(ca):
    value = "PUSH C:/Users/example/repo Authorization: Bearer SYNTHETIC_GO_123"
    result = ca.m.redact_literal_first(value, preserve_literal=True)
    assert "C:/Users/example/repo" in result
    assert "SYNTHETIC_GO_123" not in result


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("--scan", "--event"),
        ("--scan", "--resolve"),
        ("--scan", "--ack"),
        ("--event", "--resolve"),
        ("--event", "--ack"),
        ("--resolve", "--ack"),
    ],
)
def test_153n_cli_rechaza_dos_modos_de_aviso_con_mensaje_estable(
    ca, capsys, left, right
):
    values = {
        "--event": ["event-key", "--what", "texto"],
        "--resolve": ["resolve-key"],
        "--ack": ["ack-key"],
    }
    args = ["--ops-dir", str(ca.dir), "--dry-run", left]
    args.extend(values.get(left, []))
    args.append(right)
    args.extend(values.get(right, []))

    assert ca.m.main(args) == 2
    error = capsys.readouterr().err
    assert "opciones incompatibles" in error
    assert left in error and right in error


@pytest.mark.parametrize(
    "args",
    [
        ["--event", "event-key", "--level", "AVISO", "--what", "texto"],
        ["--ack", "ack-key"],
        ["--resolve", "resolve-key"],
        ["--resolve", "go-key", "--owner", "CO-48", "--flight-dir", "{flight}"],
        [
            "--go-id",
            "go-key",
            "--what",
            "Escribe GO 1",
            "--owner",
            "CO-48",
            "--flight-dir",
            "{flight}",
        ],
        ["--scan"],
    ],
)
def test_153n_conserva_invocaciones_documentadas_del_latido(ca, args):
    flight = ca.dir / "flight"
    (flight / "diseno").mkdir(parents=True)
    (flight / "diseno" / "COLA_PARA_USUARIO.md").write_text("", encoding="utf-8")
    (ca.dir / "comms_ledger.jsonl").write_text("", encoding="utf-8")
    argv = [part.format(flight=str(flight)) for part in args]
    argv.extend(["--ops-dir", str(ca.dir), "--dry-run"])

    assert ca.m.main(argv) != 2


def test_153n_caracteriza_paridad_de_throttle_por_error(ca, monkeypatch):
    monkeypatch.setattr(
        ca.m,
        "load_state",
        lambda: {"same-error": ca.clock.now - 1, "other-error": 0},
    )

    assert ca.m.alert("same-error", "incidencia-uno", "same-error", False, True) == 10
    assert ca.m.alert("same-error", "incidencia-dos", "same-error", False, True) == 10
    assert (
        ca.m.alert("different-error", "incidencia-tres", "different-error", False, True)
        == 0
    )
