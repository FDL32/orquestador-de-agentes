"""Pruebas de scripts/flight/flight_stall_check.py (WOT-2026-153j, caja 2A).

Cada prueba lleva el numero de fila del Anexo B del plan 153h que cierra (``fila_NN``) y la
mutacion que debe matarla (M/X/N/E; el arnes de mutacion vive fuera del repo).
El modulo se localiza por ruta (STALL_CHECK_UNDER_TEST permite apuntar a una copia mutada que
lleva comms_alert.py y notify_user.ps1 al lado). Nada avisa de verdad: ``notify`` se sustituye.
"""

import ast
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest


FSC_PATH = Path(
    os.environ.get("STALL_CHECK_UNDER_TEST")
    or Path(__file__).resolve().parents[2]
    / "scripts"
    / "flight"
    / "flight_stall_check.py"
)
WINDOWS = os.name == "nt"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
OK_QUOTA = "QUOTA | alvarovans weekly 40% | brabander weekly 30%"
ABIERTA = "- [2026-11-02 10:00] [CO-24] ABIERTA | decide X"


def _load(path=FSC_PATH, name="flight_stall_check_ut"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(path, *args):
    subprocess.run(
        ["git", "-C", str(path), *GIT_ID, *args], check=True, capture_output=True
    )


def make_repo(path):
    """Repo git con un commit y el hook de seguridad presente."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    (path / "f.txt").write_text("a\n", encoding="utf-8")
    _git(path, "add", "f.txt")
    _git(path, "commit", "-q", "-m", "x")
    hook = path / ".agent" / "hooks"
    hook.mkdir(parents=True)
    (hook / "claude_guard_entry.py").write_text("x", encoding="utf-8")
    return path


class Clock:
    """Reloj inyectable (modulo ``time`` de stall y de comms_alert)."""

    def __init__(self):
        self.now = time.time()

    def time(self):
        return self.now


class Box:
    """Un vuelo sintetico: ops-dir, flight-dir con cola, cupo fresco, motor git y comms_alert espiado."""

    def __init__(self, root, monkeypatch):
        self.root = root
        self.ops = root / "ops"
        self.flight = root / "flight"
        self.wt = root / "motor" / "wt"
        self.ops.mkdir()
        (self.flight / "diseno").mkdir(parents=True)
        self.cola = self.flight / "diseno" / "COLA_PARA_USUARIO.md"
        self.cola.write_text("# cola\n", encoding="utf-8")
        self.quota = self.ops / "quota_last.txt"
        self.quota.write_text(OK_QUOTA, encoding="utf-8")
        make_repo(self.wt)
        for var in (
            "FLIGHT_OPS_DIR",
            "FLIGHT_DIR",
            "STALL_MOTOR_WT",
            "STALL_QUOTA_FILE",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("STALL_WT_GLOB", str(root / "nada-*"))
        monkeypatch.setenv("STALL_FREE_GB_MIN", "0")
        self.monkeypatch = monkeypatch
        self.clock = Clock()
        self.m = _load()
        self.ca = self.m._load_alert()
        self.ca.configure(str(self.ops))  # para sembrar claves antes del primer tick
        self.sent = []
        self.notify_rc = 0
        self.events = []
        self.resolved = []
        self.ca.time = self.clock
        self.m.time = self.clock
        self.quota_touch(0)
        self.ca.notify = lambda t, msg, dry, **kwargs: (
            self.sent.append((t, msg)),
            self.notify_rc,
        )[1]
        self.ca.remove_toast = lambda *args, **kwargs: True
        self.clear_group_calls = []
        self.ca.clear_group = lambda dry=False: (
            self.clear_group_calls.append(dry) or True
        )
        real_event, real_mark, real_resolve = (
            self.ca.event,
            self.ca.mark_seen,
            self.ca.resolve,
        )

        def event(
            key,
            level,
            title,
            what,
            force,
            dry,
            owner=None,
            session_code=None,
            preserve_literal=False,
        ):
            self.events.append((key, level, owner))
            return real_event(
                key,
                level,
                title,
                what,
                force,
                dry,
                owner=owner,
                session_code=session_code,
                preserve_literal=preserve_literal,
            )

        def mark_seen(key, level, owner=None, dry=False):
            self.events.append(("MARK:" + key, level, owner))
            return real_mark(key, level, owner, dry)

        def resolve(key, dry=False):
            self.resolved.append(key)
            return real_resolve(key, dry)

        self.ca.event, self.ca.mark_seen, self.ca.resolve = event, mark_seen, resolve

    def quota_touch(self, age_min):
        """Fija la antiguedad del fichero de cupo respecto del reloj inyectado."""
        t = self.clock.now - age_min * 60
        os.utime(self.quota, (t, t))

    def tick(self, *argv, ops=True, flight=True, motor=True, mod=None):
        """Un tick como en produccion: ``main(argv)``; devuelve rc, salida, eventos y toasts nuevos."""
        args = []
        if ops:
            args += ["--ops-dir", str(self.ops)]
        if flight:
            args += ["--flight-dir", str(self.flight)]
        if motor:
            args += ["--motor-wt", str(self.wt)]
        n_ev, n_sent = len(self.events), len(self.sent)
        buf = []
        m = mod or self.m
        old = sys.stdout
        sys.stdout = io_buf = _Buf(buf)
        try:
            rc = m.main([*args, *argv])
        finally:
            sys.stdout = old
        return types.SimpleNamespace(
            rc=rc,
            out=io_buf.text(),
            events=self.events[n_ev:],
            sent=self.sent[n_sent:],
            keys=[e[0] for e in self.events[n_ev:]],
        )

    def stall_state(self):
        return json.loads((self.ops / "stall_state.json").read_text(encoding="utf-8"))

    def ca_state(self):
        return json.loads(
            (self.ops / "comms_alert_state.json").read_text(encoding="utf-8")
        )


class _Buf:
    def __init__(self, parts):
        self.parts = parts

    def write(self, s):
        self.parts.append(s)
        return len(s)

    def flush(self):
        return None

    def text(self):
        return "".join(self.parts)


@pytest.fixture
def box(tmp_path, monkeypatch):
    return Box(tmp_path, monkeypatch)


def _copy_script_dir(dst, with_alert=True):
    """Copia flight_stall_check.py (y, si se pide, sus vecinos) a otro directorio."""
    dst.mkdir(parents=True, exist_ok=True)
    src = FSC_PATH.parent
    names = ["flight_stall_check.py"]
    if with_alert:
        names += [
            "comms_alert.py",
            "notify_user.ps1",
            "send_with_ledger.py",
            "thread_id.py",
        ]
    for n in names:
        if (src / n).exists():
            shutil.copy(src / n, dst / n)
    return dst / "flight_stall_check.py"


# ------------------------------------------------------------------ D1/D2: rutas y configuracion
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


def test_d1_censo_sin_rutas_del_usuario():
    """D1: ninguna constante del usuario en el codigo versionado (control positivo incluido)."""
    assert _census(FSC_PATH.read_text(encoding="utf-8")) == []
    muestra = 'BASE = "C:/Users/fdl/tmp_or8"\nQ = "C:\\\\Temp\\\\co24_q.txt"\nV = "vuelo-20261026b"\nM = "orquestadora-3"'
    assert len(_census(muestra)) >= 5  # el censo SI muerde


def test_d2_ops_dir_sin_resolver_rc2_sin_cwd(box, tmp_path, monkeypatch):
    """D2: sin --ops-dir ni FLIGHT_OPS_DIR = rc 2 con causa, NUNCA el cwd."""
    monkeypatch.chdir(tmp_path)
    r = box.tick(ops=False)
    assert r.rc == 2
    assert "STALL_CHECK_BROKEN: ops-dir" in r.out and "sin resolver" in r.out
    assert r.out.count("STALL_CHECK_BROKEN") == 1  # se detiene ahi (SC4)
    assert not (tmp_path / "stall_state.json").exists()
    assert r.sent == []


@pytest.mark.parametrize("forma", ["relativa", "ausente", "fichero"])
def test_d2_ops_dir_invalido_rc2(box, tmp_path, monkeypatch, forma):
    monkeypatch.chdir(tmp_path)
    if forma == "relativa":
        (tmp_path / "ops").mkdir(exist_ok=True)
        raw = "ops"
    elif forma == "ausente":
        raw = str(tmp_path / "no-existe")
    else:
        f = tmp_path / "unfichero"
        f.write_text("x", encoding="utf-8")
        raw = str(f)
    r = box.tick("--ops-dir", raw, ops=False)
    assert r.rc == 2 and "STALL_CHECK_BROKEN: ops-dir" in r.out
    assert r.out.count("STALL_CHECK_BROKEN") == 1  # SC4
    assert not (tmp_path / "ops" / "stall_state.json").exists()
    assert not (tmp_path / "no-existe").exists()  # no se crea


def test_d2_ops_dir_por_entorno_y_argumento_gana(box, tmp_path, monkeypatch):
    otro = tmp_path / "otro"
    otro.mkdir()
    (otro / "quota_last.txt").write_text(OK_QUOTA, encoding="utf-8")
    monkeypatch.setenv("FLIGHT_OPS_DIR", str(otro))
    r = box.tick(ops=False)  # solo entorno
    assert r.rc == 0 and (otro / "stall_state.json").exists()
    r = box.tick()  # el argumento gana al entorno
    assert r.rc in (0, 1) and (box.ops / "stall_state.json").exists()


@pytest.mark.skipif(not WINDOWS, reason="UNC solo en Windows")
def test_d2_ops_dir_unc_rc2(box):
    r = box.tick("--ops-dir", r"\\servidor\recurso\ops", ops=False)
    assert r.rc == 2 and "UNC" in r.out


@pytest.mark.skipif(not WINDOWS, reason="capitalizacion de unidad solo en Windows")
def test_d2_ops_dir_unidad_en_minusculas_se_acepta(box):
    raw = str(box.ops)
    raw = raw[0].swapcase() + raw[1:]
    r = box.tick("--ops-dir", raw, ops=False)
    assert r.rc == 0


def test_d2_ops_dir_symlink_se_acepta(box, tmp_path):
    link = tmp_path / "enlace"
    try:
        link.symlink_to(box.ops, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("sin permiso para crear symlinks")
    r = box.tick("--ops-dir", str(link), ops=False)
    assert r.rc == 0 and (box.ops / "stall_state.json").exists()


def test_d2_flight_dir_sin_resolver_avisa_sin_config_y_ciega_la_cola(box):
    """flight-dir sin resolver: cola ciega + AVISO detector-sin-config (rc 1: hallazgo normal)."""
    r = box.tick(flight=False)
    assert r.rc == 1
    assert ("detector-sin-config", "AVISO", "stall") in r.events
    assert "ciego_cola" in r.out


@pytest.mark.parametrize("forma", ["relativa", "ausente", "fichero"])
def test_d2_flight_dir_invalido_avisa_sin_config(box, tmp_path, monkeypatch, forma):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel").mkdir()
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    raw = {"relativa": "rel", "ausente": str(tmp_path / "no"), "fichero": str(f)}[forma]
    r = box.tick("--flight-dir", raw, flight=False)
    assert ("detector-sin-config", "AVISO", "stall") in r.events and r.rc == 1


def test_d2_sin_config_se_resuelve_solo_al_corregir(box):
    """La clave detector-sin-config la borra el reconcile cuando la configuracion vuelve a estar bien."""
    box.tick(flight=False)
    assert "event:detector-sin-config" in box.ca_state()
    r = box.tick()
    assert "event:detector-sin-config" not in box.ca_state() and r.rc == 0


def test_d2_motor_relativo_ciega_git_y_hook_sin_urgente_falso(
    box, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    r = box.tick("--motor-wt", "relativo", motor=False)
    assert ("detector-sin-config", "AVISO", "stall") in r.events
    assert (
        "hook-seguridad" not in r.keys
        and "ciego_git" in r.out
        and "ciego_hook" in r.out
    )


def test_d2_motor_por_entorno_y_defecto_derivado_del_script(box, monkeypatch):
    monkeypatch.setenv("STALL_MOTOR_WT", str(box.wt))
    r = box.tick(motor=False)
    assert r.rc == 0 and 'hook_guard_existe": true' in r.out
    monkeypatch.delenv("STALL_MOTOR_WT")
    cfg, causes, fatal = box.m._resolve_paths(
        types.SimpleNamespace(
            flight_dir=str(box.flight), motor_wt=None, quota_file=None
        ),
        box.ops,
    )
    assert cfg.motor == FSC_PATH.resolve().parents[2] and fatal is None and causes == []


@pytest.mark.parametrize(
    "roster_body",
    [
        None,
        "{invalid",
        '{"active_roles": {"orquestador": {"session_code": "mcp:x"}}}',
        '{"active_roles": {"orquestador": {"session_code": ["CO-29"]}}}',
    ],
)
def test_a3_roster_forma_negativa_no_inyecta_codigo(box, roster_body):
    """A3: roster ausente, JSON roto, código inválido o tipo equivocado => sin título inyectado."""
    roster = box.flight / "flight_roster.json"
    if roster_body is None:
        roster.unlink(missing_ok=True)
    else:
        roster.write_text(roster_body, encoding="utf-8")
    cfg, causes, fatal = box.m._resolve_paths(
        types.SimpleNamespace(
            flight_dir=str(box.flight), motor_wt=str(box.wt), quota_file=None
        ),
        box.ops,
    )
    assert fatal is None and not causes and cfg.session_code is None


def test_a3_roster_json_suelto_no_es_canonico(box):
    """BA07: un roster.json paralelo no aporta identidad al tick."""
    (box.flight / "roster.json").write_text(
        '{"active_roles":{"orquestador":{"session_code":"CO-31"}}}',
        encoding="utf-8",
    )
    cfg, causes, fatal = box.m._resolve_paths(
        types.SimpleNamespace(
            flight_dir=str(box.flight), motor_wt=str(box.wt), quota_file=None
        ),
        box.ops,
    )
    assert fatal is None and not causes and cfg.session_code is None


def test_caja_c_7b_resolve_paths_lee_el_roster_canonico(box):
    """7b: el consumidor del tick usa la misma fixture flight_roster.json del contrato."""
    (box.flight / "flight_roster.json").write_text(
        '{"active_roles":{"orquestador":{"session_code":"CO-31"}}}',
        encoding="utf-8",
    )
    cfg, causes, fatal = box.m._resolve_paths(
        types.SimpleNamespace(
            flight_dir=str(box.flight), motor_wt=str(box.wt), quota_file=None
        ),
        box.ops,
    )
    assert causes == [] and fatal is None and cfg.session_code == "CO-31"


def test_a3_tick_real_usa_flight_roster_para_titulo(box):
    """BA07: un tick real con flight_roster.json propaga el codigo al aviso."""
    (box.flight / "flight_roster.json").write_text(
        '{"active_roles":{"orquestador":{"session_code":"CO-31"}}}',
        encoding="utf-8",
    )
    box.quota.write_text(
        "QUOTA | alvarovans weekly 97% | brabander weekly 30%", encoding="utf-8"
    )
    result = box.tick()
    assert result.sent and result.sent[0][0] == "CO-31"


def test_d2_quota_file_relativo_ciega_el_cupo(box, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "q.txt").write_text("QUOTA | alvarovans weekly 99%", encoding="utf-8")
    r = box.tick("--quota-file", "q.txt")
    assert ("detector-sin-config", "AVISO", "stall") in r.events
    assert "cupo-97" not in r.keys and "ciego_cupo" in r.out


def test_d2_quota_file_por_argumento_y_entorno(box, tmp_path, monkeypatch):
    q = tmp_path / "otro_q.txt"
    q.write_text(
        "QUOTA | alvarovans weekly 99% | brabander weekly 30%", encoding="utf-8"
    )
    assert "cupo-97" in box.tick("--quota-file", str(q)).keys
    monkeypatch.setenv("STALL_QUOTA_FILE", str(q))
    assert "cupo-97" in box.tick().keys  # el entorno tambien


@pytest.mark.parametrize("valor", ["abc", "nan", "inf", "-1", ""])
def test_d2_umbral_de_disco_invalido_rc2_con_causa(box, monkeypatch, valor):
    monkeypatch.setenv("STALL_FREE_GB_MIN", valor)
    r = box.tick()
    assert (
        r.rc == 2 and "STALL_CHECK_BROKEN: STALL_FREE_GB_MIN" in r.out and r.sent == []
    )


# ------------------------------------------------------------------ fila 78/79: comms_alert junto a __file__
def test_fila78_comms_alert_se_carga_junto_a_file_y_no_de_ops_dir(box):
    """Fila 78 (N58): una copia trampa de comms_alert.py en ops-dir se ignora."""
    marca = box.root / "trampa_ejecutada"
    trampa = box.ops / "comms_alert.py"
    trampa.write_text(
        f"open({str(marca)!r}, 'w').write('x')\nraise SystemExit(99)\n",
        encoding="utf-8",
    )
    r = box.tick()
    assert r.rc == 0 and not marca.exists()
    assert (
        Path(box.ca.__file__).resolve() == FSC_PATH.parent.resolve() / "comms_alert.py"
    )


def test_fila79_comms_alert_ilegible_rc2_y_marcador(tmp_path, monkeypatch):
    """Fila 79 (N59): sin comms_alert junto al script = rc 2 + STALL_CHECK_BROKEN, una sola vez."""
    ops = tmp_path / "ops"
    ops.mkdir()
    script = _copy_script_dir(tmp_path / "solo", with_alert=False)
    m = _load(script, "fsc_sin_alert")
    buf = []
    old = sys.stdout
    sys.stdout = io_buf = _Buf(buf)
    try:
        rc = m.main(["--ops-dir", str(ops)])
    finally:
        sys.stdout = old
    out = io_buf.text()
    assert rc == 2
    assert "STALL_CHECK_BROKEN: no se pudo cargar comms_alert.py" in out
    assert out.count("STALL_CHECK_BROKEN") == 1
    assert not (ops / "stall_state.json").exists()


# ------------------------------------------------------------------ fila 80, 114, 116, 120: estado
ESTADOS_MALOS = {
    "ausente": None,
    "vacio": b"",
    "corrupto": b"{no json",
    "lista": b"[]",
    "null": b"null",
    "anidado": b'{"a":' + b"[" * 3000 + b"]" * 3000 + b"}",
    "no_utf8": b"\xff\xfe\x00\x01",
}


@pytest.mark.parametrize("forma", sorted(ESTADOS_MALOS))
def test_fila80_estado_ausente_o_ilegible_es_vacio_y_se_reescribe(box, forma):
    """Fila 80 (N60, C1a): cualquier forma ilegible = {} y el tick se cura (rc 0, estado dict)."""
    if ESTADOS_MALOS[forma] is not None:
        (box.ops / "stall_state.json").write_bytes(ESTADOS_MALOS[forma])
    r = box.tick()
    assert r.rc == 0 and "STALL_CHECK_BROKEN" not in r.out
    st = box.stall_state()
    assert isinstance(st, dict) and "ts_latido" in st and st["motor_sucio"] == 0


def test_fila80_estado_con_bom_se_lee(box):
    """E6 (HOY perdia el estado entero): BOM + contador previo vale; el arbol sucio avisa al primer tick."""
    (box.wt / "f.txt").write_text("b\n", encoding="utf-8")
    (box.ops / "stall_state.json").write_bytes(b"\xef\xbb\xbf" + b'{"motor_sucio": 1}')
    r = box.tick()
    assert "git-motor-sucio" in r.keys


@pytest.mark.parametrize(
    "malo",
    [
        '"x"',
        "NaN",
        "true",
        "-3",
        "1e999",
        "1.5",
        "null",
        "[]",
        "{}",
        "1000000",
        "9" * 12,
    ],
)
def test_fila80_contador_motor_sucio_no_entero_cuenta_cero(box, malo):
    """E7b/E10b (HOY: cadena = detector-roto, NaN = silencio eterno): vale 0, el aviso sale al 2o tick."""
    (box.wt / "f.txt").write_text("b\n", encoding="utf-8")
    (box.ops / "stall_state.json").write_text(
        '{"motor_sucio": ' + malo + "}", encoding="utf-8"
    )
    r1 = box.tick()
    assert (
        "detector-roto" not in r1.keys
        and "git-motor-sucio" not in r1.keys
        and r1.rc == 0
    )
    assert box.stall_state()["motor_sucio"] == 1
    assert "git-motor-sucio" in box.tick().keys


def test_fila80_contador_en_el_limite_superior_si_vale(box):
    """E5: 999999 es el mayor contador valido (< 10**6); con arbol sucio avisa ya al primer tick."""
    (box.wt / "f.txt").write_text("b\n", encoding="utf-8")
    (box.ops / "stall_state.json").write_text(
        '{"motor_sucio": 999999}', encoding="utf-8"
    )
    assert "git-motor-sucio" in box.tick().keys
    assert box.stall_state()["motor_sucio"] == 1000000


def test_fila114_guardado_atomico_el_estado_viejo_queda_y_se_limpia_el_tmp(box):
    """Fila 114 (N81): un replace que falla deja el estado viejo integro, sin .tmp, rc 2."""
    box.tick()
    viejo = (box.ops / "stall_state.json").read_bytes()

    real = os.replace

    def falla(src, dst):
        if Path(src).name.startswith("stall_state"):  # solo el guardado del latido
            raise PermissionError("replace bloqueado")
        return real(src, dst)

    box.monkeypatch.setattr(box.m.os, "replace", falla)
    r = box.tick()
    assert r.rc == 2 and "STALL_CHECK_BROKEN: PermissionError" in r.out
    assert (box.ops / "stall_state.json").read_bytes() == viejo
    assert [p.name for p in box.ops.glob("*.tmp")] == []


def test_fila114_estado_es_un_directorio_rc2(box):
    (box.ops / "stall_state.json").mkdir()
    assert box.tick().rc == 2


def test_fila120_tmp_unico_por_pid(box):
    """Fila 120 (N86): el tmp lleva el PID; dos procesos no comparten tmp."""
    vistos = []
    real = os.replace
    box.monkeypatch.setattr(
        box.m.os, "replace", lambda s, d: (vistos.append(Path(s).name), real(s, d))[1]
    )
    box.monkeypatch.setattr(box.m.os, "getpid", lambda: 4242)
    box.tick()
    box.monkeypatch.setattr(box.m.os, "getpid", lambda: 4343)
    box.tick()
    stall = [n for n in vistos if n.startswith("stall_state")]
    assert stall == ["stall_state.4242.tmp", "stall_state.4343.tmp"]


def test_fila116_ts_latido_en_cada_tick_no_dry_tambien_baseline_y_sin_ts_tarea(box):
    """Fila 116 (N82): ts_latido se escribe siempre (no dry); se retira el ``ts`` legado; nunca ts_tarea."""
    (box.ops / "stall_state.json").write_text(
        '{"ts": 1.0, "cola_vistas": 3}', encoding="utf-8"
    )
    box.clock.now += 100
    box.tick()
    st = box.stall_state()
    assert (
        st["ts_latido"] == box.clock.now and "ts" not in st and "cola_vistas" not in st
    )
    assert "ts_tarea" not in st
    box.clock.now += 100
    box.tick("--baseline")
    assert box.stall_state()["ts_latido"] == box.clock.now
    assert not (box.ops / "task_state.json").exists()


def test_fila115_dry_run_no_escribe_estado_ni_ledger_ni_comms_alert(box):
    """Fila 115 (X17): --dry-run deja ops-dir byte a byte igual."""
    box.cola.write_text("# cola\n" + ABIERTA + " BLOQUEA\n", encoding="utf-8")
    antes = {p.name: p.read_bytes() for p in box.ops.iterdir()}
    r = box.tick("--dry-run")
    despues = {p.name: p.read_bytes() for p in box.ops.iterdir()}
    assert r.rc == 1 and antes == despues


# ------------------------------------------------------------------ fila 81, 93-102: git
def test_fila81_git_ausente_es_detector_roto_rc2(box):
    """Fila 81 (N61): git que no esta en el PATH = detector-roto, STALL_CHECK_BROKEN, rc 2."""
    box.monkeypatch.setattr(box.m.shutil, "which", lambda name: None)
    r = box.tick()
    assert r.rc == 2 and ("detector-roto", "AVISO", "stall") in r.events
    assert "STALL_CHECK_BROKEN: un detector fallo" in r.out


def test_fila81_git_sin_responder_timeout_es_detector_roto(box):
    def tmo(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 30)

    box.monkeypatch.setattr(box.m.subprocess, "run", tmo)
    r = box.tick()
    assert r.rc == 2 and "detector-roto" in r.keys


def test_fila93_ruta_de_hermano_ausente_se_salta(box, tmp_path):
    """Fila 93 (N69, mutante equivalente declarado): un hermano que es un symlink roto no lanza."""
    hermanos = tmp_path / "hermanos"
    hermanos.mkdir()
    try:
        (hermanos / "impl-1").symlink_to(
            tmp_path / "no-existe", target_is_directory=True
        )
    except (OSError, NotImplementedError):
        pytest.skip("sin permiso para crear symlinks")
    box.monkeypatch.setenv("STALL_WT_GLOB", str(hermanos / "impl-*"))
    r = box.tick()
    assert r.rc == 0 and "detector-roto" not in r.keys


def test_fila94_rev_parse_fallido_de_hermano_se_salta(box, tmp_path, monkeypatch):
    """Fila 94 (N70): un hermano que no es repo no produce avisos aunque el cwd tenga index.lock."""
    hermanos = tmp_path / "hermanos"
    (hermanos / "impl-2").mkdir(parents=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    for n in ("index.lock", "MERGE_HEAD"):
        (cwd / n).write_text("", encoding="utf-8")
    monkeypatch.chdir(cwd)
    box.monkeypatch.setenv("STALL_WT_GLOB", str(hermanos / "impl-*"))
    r = box.tick()
    assert r.rc == 0 and not [k for k in r.keys if k.startswith("git-")]


def test_d2_gitdir_roto_avisa_con_basename_y_sin_ruta(box, tmp_path):
    """D2: una entrada .git rota no se confunde con un directorio que no es repo."""
    roto = tmp_path / "gitdir-roto"
    roto.mkdir()
    (roto / ".git").write_text("gitdir: no-existe\n", encoding="utf-8")

    hallazgos = box.m._git_markers(roto)

    assert len(hallazgos) == 1
    clave, nivel, texto = hallazgos[0]
    assert clave == "git-gitdir-gitdir-roto" and nivel == "AVISO"
    assert str(roto) not in texto and "gitdir-roto" in texto


@pytest.mark.parametrize(
    "nombre", ["index.lock", "MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD"]
)
def test_filas95_a_98_marcador_de_git_avisa_una_vez_por_nombre(box, nombre):
    """Filas 95-98 (N71, X5, N72, N73): cada marcador da su clave AVISO propia y la clave se limpia al quitarlo."""
    gitdir = box.wt / ".git"
    (gitdir / nombre).write_text("", encoding="utf-8")
    r = box.tick()
    clave = f"git-{nombre.lower()}-wt"
    assert r.rc == 1 and (clave, "AVISO", "stall") in r.events
    assert box.tick().sent == []  # una vez por aparicion
    (gitdir / nombre).unlink()
    box.tick()
    assert "event:" + clave not in box.ca_state()


def test_fila95_worktree_hermano_con_lock_en_su_gitdir(box, tmp_path):
    hermanos = tmp_path / "hermanos"
    hermanos.mkdir()
    _git(box.wt, "worktree", "add", "-q", "-b", "sib", str(hermanos / "impl-1"))
    gd = subprocess.run(
        ["git", "-C", str(hermanos / "impl-1"), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (Path(gd) / "index.lock").write_text("", encoding="utf-8")
    box.monkeypatch.setenv("STALL_WT_GLOB", str(hermanos / "impl-*"))
    assert ("git-index.lock-impl-1", "AVISO", "stall") in box.tick().events


def test_fila95_motor_que_casa_con_su_propio_glob_no_se_duplica(box):
    """El motor derivado (implantador-*) casa con el glob de hermanos: un solo hallazgo."""
    (box.wt / ".git" / "index.lock").write_text("", encoding="utf-8")
    box.monkeypatch.setenv("STALL_WT_GLOB", str(box.wt.parent / "w*"))
    assert box.tick().keys.count("git-index.lock-wt") == 1


def test_fila99_status_fallido_es_ceguera_con_aviso_y_no_borra_claves_git(
    box, tmp_path
):
    """Fila 99 (N74, Q2): git status que falla = ciego_git + detector-ciego-git AVISO; no borra git-*."""
    box.ca.mark_seen("git-index.lock-wt", "AVISO", "stall")
    sin_repo = tmp_path / "norepo"
    sin_repo.mkdir()
    r = box.tick("--motor-wt", str(sin_repo), motor=False)
    assert r.rc == 1 and ("detector-ciego-git", "AVISO", "stall") in r.events
    assert "hook-seguridad" not in r.keys
    assert "ciego_git" in r.out and '"motor_sucio": -1' in r.out
    assert "event:git-index.lock-wt" in box.ca_state()
    assert box.stall_state()["motor_sucio"] == 0
    assert (
        box.tick("--motor-wt", str(sin_repo), motor=False).sent == []
    )  # una vez por aparicion
    r = box.tick()  # vuelve a leerse: la clave de ceguera se resuelve sola, la git-* (ya sin causa) tambien
    assert "event:detector-ciego-git" not in box.ca_state()


def test_fila100_sucio_solo_al_segundo_tick_consecutivo(box):
    """Fila 100 (X4)."""
    (box.wt / "f.txt").write_text("b\n", encoding="utf-8")
    r1 = box.tick()
    assert (
        r1.rc == 0
        and "git-motor-sucio" not in r1.keys
        and box.stall_state()["motor_sucio"] == 1
    )
    r2 = box.tick()
    assert r2.rc == 1 and ("git-motor-sucio", "AVISO", "stall") in r2.events
    assert box.stall_state()["motor_sucio"] == 2


def test_fila101_el_contador_sucio_se_reinicia_al_limpiar(box):
    """Fila 101 (N75): sucio, limpio, sucio = no avisa (el contador vuelve a 1, no a 2)."""
    f = box.wt / "f.txt"
    f.write_text("b\n", encoding="utf-8")
    box.tick()
    _git(box.wt, "checkout", "-q", "--", "f.txt")
    box.tick()
    assert box.stall_state()["motor_sucio"] == 0
    f.write_text("c\n", encoding="utf-8")
    assert "git-motor-sucio" not in box.tick().keys


def test_fila102_ficheros_sin_seguimiento_no_cuentan(box):
    """Fila 102 (N76)."""
    (box.wt / "nuevo.txt").write_text("x", encoding="utf-8")
    box.tick()
    r = box.tick()
    assert r.rc == 0 and box.stall_state()["motor_sucio"] == 0


# ------------------------------------------------------------------ fila 105, 118, 119: CLI y self-check
def test_fila105_self_check_ok_y_cuatro_fallos(box, tmp_path):
    """Fila 105 (N77): todo bien = 0; falta un fichero / sintaxis rota / cola ausente / motor ausente = 2."""
    r = box.tick("--self-check", ops=False)
    assert r.rc == 0 and "self-check: OK" in r.out
    sola = _copy_script_dir(tmp_path / "sola", with_alert=False)
    m = _load(sola, "fsc_self_falta")
    assert (
        m.main(
            ["--self-check", "--flight-dir", str(box.flight), "--motor-wt", str(box.wt)]
        )
        == 2
    )
    rota = _copy_script_dir(tmp_path / "rota")
    (rota.parent / "comms_alert.py").write_text("def x(:\n", encoding="utf-8")
    m = _load(rota, "fsc_self_rota")
    assert (
        m.main(
            ["--self-check", "--flight-dir", str(box.flight), "--motor-wt", str(box.wt)]
        )
        == 2
    )
    box.cola.unlink()
    r = box.tick("--self-check", ops=False)
    assert r.rc == 2 and "cola" in r.out
    box.cola.write_text("# cola\n", encoding="utf-8")
    r = box.tick(
        "--self-check", "--motor-wt", str(box.root / "no-hay"), ops=False, motor=False
    )
    assert r.rc == 2 and "motor" in r.out
    r = box.tick("--self-check", ops=False, flight=False)
    assert r.rc == 2 and "flight-dir" in r.out


def test_fila105_self_check_falta_cada_fichero_junto_a_file(tmp_path):
    for faltante in ("comms_alert.py", "notify_user.ps1"):
        d = tmp_path / faltante
        script = _copy_script_dir(d)
        (d / faltante).unlink()
        m = _load(script, "fsc_f_" + faltante[:4])
        assert m.main(["--self-check"]) == 2


def test_fila118_main_despacha_self_check_sin_correr_el_tick(box):
    """Fila 118 (N84): con --self-check no se toca el estado ni se exige ops-dir."""
    r = box.tick("--self-check", ops=False)
    assert "self-check:" in r.out and not (box.ops / "stall_state.json").exists()


def test_fila119_excepcion_exterior_rc2_con_marcador(box):
    """Fila 119 (N85)."""

    def boom(a):
        raise RuntimeError("no previsto")

    box.monkeypatch.setattr(box.m, "run", boom)
    r = box.tick()
    assert r.rc == 2 and "STALL_CHECK_BROKEN: RuntimeError: no previsto" in r.out


def test_argumento_desconocido_es_rc2_de_argparse(box):
    with pytest.raises(SystemExit) as exc:
        box.tick("--nada")
    assert exc.value.code == 2


# ------------------------------------------------------------------ filas 106-113: run
def test_fila106_detector_que_lanza_es_detector_roto_rc2_y_no_tapa_a_los_demas(box):
    """Fila 106 (M16): un detector roto avisa, no tapa al resto (el hook sigue siendo URGENTE) y rc 2."""
    (box.wt / ".agent" / "hooks" / "claude_guard_entry.py").unlink()

    def boom(out):
        raise RuntimeError("roto a proposito")

    box.monkeypatch.setattr(box.m, "check_quota", boom)
    r = box.tick()
    assert r.rc == 2 and ("detector-roto", "AVISO", "stall") in r.events
    assert ("hook-seguridad", "URGENTE", "stall") in r.events
    assert "STALL_CHECK_BROKEN: un detector fallo" in r.out


def test_fila107_aviso_fallido_es_rc2(box):
    """Fila 107 (M6)."""
    box.cola.write_text("# cola\n" + ABIERTA + " BLOQUEA\n", encoding="utf-8")
    box.notify_rc = 1
    r = box.tick()
    assert r.rc == 2 and "STALL_CHECK_BROKEN" not in r.out
    assert (
        "event:" + r.keys[0] not in box.ca_state()
    )  # un aviso fallido no consume el limite


def test_fila108_con_hallazgos_rc_1_es_normal(box):
    """Fila 108 (N78)."""
    box.cola.write_text("# cola\n" + ABIERTA + "\n", encoding="utf-8")
    assert box.tick().rc == 1
    assert box.tick().rc == 1  # ya avisado: sigue siendo hallazgo, sin toast
    assert box.tick("--dry-run").rc == 1


def test_fila109_y_110_baseline_marca_sin_avisar_y_el_tick_posterior_no_avisa(box):
    """Filas 109-110 (X16, N79)."""
    box.cola.write_text("# cola\n" + ABIERTA + " BLOQUEA\n", encoding="utf-8")
    r = box.tick("--baseline")
    assert r.rc == 1 and r.sent == [] and r.keys[0].startswith("MARK:cola-")
    assert "BASELINE URGENTE cola-" in r.out
    clave = "event:" + r.keys[0][5:]
    assert clave in box.ca_state() and box.ca_state()[clave]["owner"] == "stall"
    assert box.stall_state()["ts_latido"] == box.clock.now
    assert box.tick().sent == []


def test_fila111_reconcile_solo_sin_dry_ni_baseline_ni_detector_roto(box):
    """Fila 111 (N80): en esos tres modos una clave sin causa NO se borra."""
    box.ca.mark_seen("cupo-97", "URGENTE", "stall")
    box.tick("--dry-run")
    assert "event:cupo-97" in box.ca_state()
    box.tick("--baseline")
    assert "event:cupo-97" in box.ca_state()

    def boom(out):
        raise RuntimeError("roto")

    box.monkeypatch.setattr(box.m, "check_disk", boom)
    box.tick()
    assert "event:cupo-97" in box.ca_state()
    box.monkeypatch.undo()
    # el cupo queda fresco otra vez tras deshacer monkeypatch? el fichero esta intacto: se borra
    box.m.time = box.clock
    box.tick()
    assert "event:cupo-97" not in box.ca_state()


def test_fila112_reconcile_borra_las_claves_resueltas_y_la_recaida_avisa(box):
    """Fila 112 (M7): bajar el cupo borra cupo-*, quitar la cola borra cola-*, volver el hook borra hook-*."""
    box.quota.write_text(
        "QUOTA | alvarovans weekly 98% | brabander weekly 30%", encoding="utf-8"
    )
    assert "cupo-97" in box.tick().keys
    box.quota.write_text(OK_QUOTA, encoding="utf-8")
    r = box.tick()
    assert "event:cupo-97" not in box.ca_state() and "resueltas" in r.out
    box.quota.write_text(
        "QUOTA | alvarovans weekly 98% | brabander weekly 30%", encoding="utf-8"
    )
    assert len(box.tick().sent) == 1  # la recaida avisa de nuevo
    (box.wt / ".agent" / "hooks" / "claude_guard_entry.py").unlink()
    box.quota.write_text(OK_QUOTA, encoding="utf-8")
    box.tick()
    (box.wt / ".agent" / "hooks" / "claude_guard_entry.py").write_text(
        "x", encoding="utf-8"
    )
    box.tick()
    assert "event:hook-seguridad" not in box.ca_state()


def test_fila113_detector_ciego_no_borra_sus_claves(box):
    """Fila 113 (M15): cola ausente o cupo ilegible no borran cola-*/cupo-*."""
    box.cola.write_text("# cola\n" + ABIERTA + " BLOQUEA\n", encoding="utf-8")
    box.quota.write_text(
        "QUOTA | alvarovans weekly 96% | brabander weekly 30%", encoding="utf-8"
    )
    box.tick()
    claves = [k for k in box.ca_state() if k.startswith(("event:cola-", "event:cupo-"))]
    assert len(claves) == 2
    box.cola.unlink()
    box.quota.write_text("sin porcentajes", encoding="utf-8")
    box.tick()
    assert set(claves) <= set(box.ca_state())


def test_reconcile_no_toca_claves_de_otro_owner(box):
    box.ca.mark_seen("cupo-97", "URGENTE", "manual")
    box.tick()
    assert "event:cupo-97" in box.ca_state()


# ------------------------------------------------------------------ filas 117 y 121: tarea (D25)
def _tarea(box, ts=None, registrada=True):
    if registrada:
        (box.ops / "task_registered.json").write_text("{}", encoding="utf-8")
    if ts is not None:
        (box.ops / "task_state.json").write_text(
            json.dumps({"ts_tarea": ts}), encoding="utf-8"
        )


def test_fila117_sin_marca_no_hay_aviso_de_tarea(box):
    """Fila 117 (N83)."""
    r = box.tick()
    assert (
        r.rc == 0 and "tarea-muerta" not in r.keys and "tarea_registrada" not in r.out
    )


def test_fila117_con_marca_y_sin_task_state_avisa(box):
    _tarea(box)
    r = box.tick()
    assert r.rc == 1 and ("tarea-muerta", "AVISO", "stall") in r.events


@pytest.mark.parametrize(
    ("minutos", "avisa"),
    [
        (0, False),
        (24, False),
        (25, False),
        (26, True),
        (600, True),
        (-4, False),
        (-6, True),
    ],
)
def test_fila117_umbral_de_25_min_y_futuro_acotado(box, minutos, avisa):
    """El umbral es 25 min (no 2500) y un ts del futuro lejano es ilegible."""
    _tarea(box, ts=box.clock.now - minutos * 60)
    assert ("tarea-muerta" in box.tick().keys) is avisa


@pytest.mark.parametrize(
    "malo",
    ['"ayer"', "null", "true", "NaN", "Infinity", "-Infinity", "1e999", "[]", "{}"],
)
def test_fila117_ts_tarea_ilegible_avisa(box, malo):
    """Un reloj ilegible se dice ilegible (ni "lleva N min", ni detector-roto por desbordar)."""
    _tarea(box)
    (box.ops / "task_state.json").write_text(
        '{"ts_tarea": ' + malo + "}", encoding="utf-8"
    )
    r = box.tick()
    assert "tarea-muerta" in r.keys and "detector-roto" not in r.keys
    assert (
        "falta o es ilegible" in r.sent[0][1] and "min sin correr" not in r.sent[0][1]
    )


def test_fila117_ts_tarea_antiguo_dice_cuantos_minutos(box):
    _tarea(box, ts=box.clock.now - 600 * 60)
    r = box.tick()
    assert "lleva 600 min sin correr" in r.sent[0][1]


@pytest.mark.parametrize("contenido", [b"", b"{no", b"[]", b"null", b"\xff\xfe"])
def test_fila117_task_state_ilegible_avisa(box, contenido):
    _tarea(box)
    (box.ops / "task_state.json").write_bytes(contenido)
    assert "tarea-muerta" in box.tick().keys


def test_fila117_marca_como_directorio_o_symlink_roto_cuenta_como_registrada(
    box, tmp_path
):
    (box.ops / "task_registered.json").mkdir()
    assert "tarea-muerta" in box.tick().keys


def test_fila117_marca_como_symlink_roto_cuenta_como_registrada(box, tmp_path):
    """N83b: lexists, no exists: un enlace roto sigue siendo una marca puesta."""
    try:
        (box.ops / "task_registered.json").symlink_to(tmp_path / "no_existe")
    except (OSError, NotImplementedError):
        pytest.skip("sin permiso para crear symlinks")
    assert "tarea-muerta" in box.tick().keys


def test_fila121_tarea_muerta_se_resuelve_explicitamente_al_recuperarse(box):
    """Fila 121 (N87): ts_tarea fresco (o marca retirada) = resolve explicito del dueno stall."""
    _tarea(box)
    box.tick()
    assert box.ca_state()["event:tarea-muerta"]["owner"] == "stall"
    box.resolved.clear()
    _tarea(box, ts=box.clock.now)
    r = box.tick()
    assert (
        "event:tarea-muerta" not in box.ca_state()
        and box.resolved == ["tarea-muerta"]
        and r.rc == 0
    )
    _tarea(box, ts=box.clock.now - 3600)
    assert "tarea-muerta" in box.tick().keys  # la recaida avisa de nuevo
    (box.ops / "task_registered.json").unlink()
    box.tick()
    assert "event:tarea-muerta" not in box.ca_state()


def test_fila121_dry_run_no_resuelve(box):
    _tarea(box)
    box.tick()
    _tarea(box, ts=box.clock.now)
    box.tick("--dry-run")
    assert "event:tarea-muerta" in box.ca_state()


# ------------------------------------------------------------------ AST: higiene del modulo
def test_modulo_sin_cargas_desde_ops_dir_ni_bypass():
    """D17/D19: ninguna forma de cargar o ejecutar codigo de ops-dir ni Bypass en el modulo."""
    src = FSC_PATH.read_text(encoding="utf-8")
    assert "Bypass" not in src and "ExecutionPolicy" not in src
    tree = ast.parse(src)
    llamadas = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert not llamadas & {
        "exec",
        "eval",
        "import_module",
        "run_path",
        "system",
        "Popen",
    }
    assert math.isfinite(1.0)  # (math se usa en las pruebas de umbral)


# === BUILDER 2A: filas 82-92, 103, 104 (cupo, cola, disco, hook) ===


def test_fila82_cupo_ausente(box):
    """Fila 82 (N62): cupo sin medir al no existir el fichero = ciego + aviso una vez."""
    box.quota.unlink()
    r1 = box.tick()
    assert r1.rc == 1
    assert ("cupo-no-medido", "AVISO", "stall") in r1.events
    assert "ciego_cupo" in r1.out
    r2 = box.tick()
    assert r2.sent == []  # una vez por aparicion


def test_fila83_antiguedad_del_cupo(box):
    """Fila 83 (N62): mas de 40 min sin medirse = aviso cupo-no-medido."""
    # 39 min: sin aviso
    box.quota_touch(39)
    r = box.tick()
    assert r.rc == 0 and "cupo-no-medido" not in r.keys

    # 41 min: avisa
    box.quota_touch(41)
    r = box.tick()
    assert ("cupo-no-medido", "AVISO", "stall") in r.events
    assert "ciego_cupo" in r.out
    toast_text = r.sent[0][1]
    assert "min sin medirse" in toast_text

    # 600 min: también avisa (resolver la clave la vuelve a aparecer en el siguiente tick)
    box.ca.resolve("cupo-no-medido")
    box.quota_touch(600)
    r = box.tick()
    assert ("cupo-no-medido", "AVISO", "stall") in r.events
    toast_text = r.sent[0][1]
    # verifica que el numero de minutos aparece
    assert "600" in toast_text


def test_fila84_cupo_sin_porcentajes_es_ilegible(box):
    """Fila 84 (N63): sin porcentajes legibles = ciego + cupo-ilegible."""
    contenidos = [
        "",
        "sin porcentajes aqui",
        "QUOTA | alvarovans weekly nan% | brabander weekly inf%",
    ]
    for c in contenidos:
        box.quota.write_text(c, encoding="utf-8")
        box.quota_touch(0)
        r = box.tick()
        assert r.rc == 1 and ("cupo-ilegible", "AVISO", "stall") in r.events
        assert "ciego_cupo" in r.out
        assert "cupo-92" not in r.keys and "cupo-97" not in r.keys
        box.sent.clear()
        box.events.clear()

    # bytes no UTF-8 también cuenta como ilegible
    box.quota.write_bytes(b"\xff\xfeQUOTA \xff\xff")
    box.quota_touch(0)
    r = box.tick()
    assert r.rc == 1 and ("cupo-ilegible", "AVISO", "stall") in r.events
    assert "cupo-92" not in r.keys and "cupo-97" not in r.keys


def test_d3_cupo_lee_mas_alla_de_400_y_detecta_el_urgente(box):
    """D3: una cuenta alta después del prefijo histórico de 400 caracteres sigue siendo visible."""
    segmentos = ["alvarovans weekly 30%"] * 18
    segmentos.append("alvarovans weekly 98%")
    linea = "QUOTA | " + " | ".join(segmentos)
    assert len(linea) > 400
    _con_cupo(box, linea)

    r = box.tick()

    assert r.rc == 1 and ("cupo-97", "URGENTE", "stall") in r.events


def test_d3_cota_de_lectura_acepta_4096_y_ciega_4097(box):
    """D3: la cota es explícita; exactamente 4096 se procesa y 4097 se marca no medido."""
    prefijo = "QUOTA | alvarovans weekly 40% | "
    exacta = prefijo + "x" * (4096 - len(prefijo))
    assert len(exacta) == 4096
    _con_cupo(box, exacta)
    assert "cupo-no-medido" not in box.tick().keys

    sobre = exacta + "x"
    _con_cupo(box, sobre)
    r = box.tick()
    assert ("cupo-no-medido", "AVISO", "stall") in r.events
    assert "ciego_cupo" in r.out


def test_d6_sonda_codex_no_inyecta_cuenta_conocida(box):
    """D6: una mención de alvarovans dentro del segmento codex es informativa, no una cuenta."""
    _con_cupo(
        box,
        "QUOTA | codex alvarovans weekly 98% | brabander weekly 30%",
    )
    r = box.tick()
    assert r.rc == 0 and r.events == []


def test_d6_cuenta_real_alta_sigue_siendourgente(box):
    """D6: la exclusión de codex no relaja el segmento real de alvarovans."""
    _con_cupo(box, "QUOTA | alvarovans weekly 98% | brabander weekly 30%")
    assert ("cupo-97", "URGENTE", "stall") in box.tick().events


def test_d9_detector_inf_es_ilegible_y_no_urgente(box):
    """D9: el detector conserva +inf como cupo ilegible, no como cupo-97."""
    _con_cupo(box, "QUOTA HARD (soft 92/hard 97) | alvarovans weekly inf%")
    r = box.tick()
    assert ("cupo-ilegible", "AVISO", "stall") in r.events
    assert "cupo-97" not in r.keys


@pytest.mark.parametrize("p", [91, 92, 96, 97, 100])
def test_fila85_niveles_del_cupo(box, p):
    """Fila 85 (N64): niveles de cupo segun el maximo de alvarovans."""
    box.quota.write_text(
        f"QUOTA | alvarovans weekly {p}% | brabander weekly 30%", encoding="utf-8"
    )
    box.quota_touch(0)
    r = box.tick()
    if p <= 91:
        assert r.rc == 0 and r.events == []
    elif p <= 96:
        assert r.rc == 1 and ("cupo-92", "AVISO", "stall") in r.events
    else:
        assert r.rc == 1 and ("cupo-97", "URGENTE", "stall") in r.events

    # verifica que el toast lleva el porcentaje y que el resumen incluye cupo_max
    if p >= 92:
        toast_text = r.sent[0][1]
        assert f"{p}%" in toast_text
        assert f'"cupo_max": {p}' in r.out


def test_fila87_maximo_entre_cuentas(box):
    """Fila 87 (N64): el maximo es el que decide, la primera cuenta baja no tapa."""
    # (a) alvarovans 40, brabander 97 -> cupo-97 URGENTE
    box.quota.write_text(
        "QUOTA | alvarovans weekly 40% | brabander weekly 97%", encoding="utf-8"
    )
    box.quota_touch(0)
    r = box.tick()
    assert ("cupo-97", "URGENTE", "stall") in r.events

    # (b) alvarovans 97, brabander 40 -> cupo-97 URGENTE
    box.quota.write_text(
        "QUOTA | alvarovans weekly 97% | brabander weekly 40%", encoding="utf-8"
    )
    r = box.tick()
    assert ("cupo-97", "URGENTE", "stall") in r.events

    # (c) alvarovans 40, brabander 96 -> cupo-92 AVISO (la primera no tapa)
    box.quota.write_text(
        "QUOTA | alvarovans weekly 40% | brabander weekly 96%", encoding="utf-8"
    )
    r = box.tick()
    assert ("cupo-92", "AVISO", "stall") in r.events

    # (d) cuenta no listada + alvarovans 40 -> rc 0 (solo cuentan alvarovans/brabander)
    box.quota.write_text(
        "QUOTA | codex weekly 99% | alvarovans weekly 40%", encoding="utf-8"
    )
    r = box.tick()
    assert r.rc == 0 and r.events == []


def test_fila88_cola_ausente_es_ceguera_con_aviso(box):
    """Fila 88 (N65): la cola ausente ciega el detector y avisa una sola vez."""
    # Siembra una cola con ABIERTA ... BLOQUEA y tick para crear la clave
    box.cola.write_text("# cola\n" + ABIERTA + " BLOQUEA\n", encoding="utf-8")
    r1 = box.tick()
    cola_key = [k for k in r1.keys if k.startswith("cola-")]
    assert len(cola_key) == 1

    # Borra la cola
    box.cola.unlink()

    # Tick: ceguera con aviso
    r2 = box.tick()
    assert r2.rc == 1
    assert ("detector-ciego-cola", "AVISO", "stall") in r2.events
    assert "ciego_cola" in r2.out
    assert "event:" + cola_key[0] in box.ca_state()  # un ciego no borra claves

    # Un 3er tick no emite toasts (una vez por aparicion)
    r3 = box.tick()
    assert r3.sent == []

    # Recrea la cola vacia: reconcile borra las claves
    box.cola.write_text("# cola\n", encoding="utf-8")
    box.tick()
    assert "event:detector-ciego-cola" not in box.ca_state()
    assert "event:" + cola_key[0] not in box.ca_state()  # A4: con el prefijo, muerde


@pytest.mark.parametrize(
    "contenido, expected_rc, expected_key_prefix, expected_level",
    [
        ("# cola\n" + ABIERTA + "\n", 1, "cola-", "AVISO"),
        ("# cola\n" + "- [t] [CO-24] RESUELTA | decide X\n", 0, None, None),
        ("# cola\n" + ABIERTA + " | RESUELTA | decide X\n", 0, None, None),
        ("# cola\n", 0, None, None),
    ],
)
def test_fila89_abierta_avisa_y_resuelta_no(
    box, contenido, expected_rc, expected_key_prefix, expected_level
):
    """Fila 89 (N66): ABIERTA sin RESUELTA avisa; RESUELTA no."""
    box.cola.write_text(contenido, encoding="utf-8")
    r = box.tick()
    assert r.rc == expected_rc
    if expected_key_prefix:
        found = [k for k in r.keys if k.startswith(expected_key_prefix)]
        assert len(found) == 1
        assert expected_level in [e[1] for e in r.events if e[0] == found[0]]


def test_fila90_bloquea_sube_a_urgente(box):
    """Fila 90 (N67): ABIERTA sola = AVISO; ABIERTA con BLOQUEA = URGENTE."""
    box.cola.write_text("# cola\n" + ABIERTA + " BLOQUEA\n", encoding="utf-8")
    r1 = box.tick()
    assert ("cola-" + r1.keys[0].split("cola-")[1], "URGENTE", "stall") in r1.events

    box.cola.write_text("# cola\n" + ABIERTA + "\n", encoding="utf-8")
    r2 = box.tick()
    assert ("cola-" + r2.keys[0].split("cola-")[1], "AVISO", "stall") in r2.events


def test_fila91_clave_estable_por_hash_de_la_linea(box):
    """Fila 91 (N68): la clave cola-<sha1[:8]> es estable para la misma linea."""
    import hashlib

    linea = ABIERTA  # la linea tal cual en el fichero
    expected_key = (
        "cola-"
        + hashlib.sha1(linea.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    )

    box.cola.write_text("# cola\n" + linea + "\n", encoding="utf-8")

    # Primer tick: emite el hallazgo
    r1 = box.tick()
    assert r1.rc == 1 and r1.keys[0] == expected_key
    box.sent.clear()

    # Segundo tick con la misma linea: no emite toast (ya avisado)
    r2 = box.tick()
    assert r2.sent == []

    # Dos lineas ABIERTA distintas dan dos claves distintas
    box.cola.write_text(
        "# cola\n" + ABIERTA + "\n" + "- [2026-12-01 10:00] [CO-99] ABIERTA | otra\n",
        encoding="utf-8",
    )
    r3 = box.tick()
    cola_keys = [k for k in r3.keys if k.startswith("cola-")]
    assert len(cola_keys) == 2 and cola_keys[0] != cola_keys[1]

    # Cambiar la posicion de la linea ABIERTA no cambia la clave ni re-avisa
    box.cola.write_text("# otra\n" + ABIERTA + "\n", encoding="utf-8")
    box.sent.clear()
    r4 = box.tick()
    assert r4.sent == []


def test_fila92_texto_de_la_cola_redactado_y_acotado(box):
    """Fila 92 (N69): el toast no filtra rutas ni UUIDs y acota el resumen."""
    # (a) UUID + ruta Windows: redacta, conserva cola-<hash> entre corchetes
    linea_a = "- [t] [CO-24] ABIERTA | mcp:12345678-1234-1234-1234-123456789abc ver C:\\Users\\fdl\\x"
    box.cola.write_text("# cola\n" + linea_a + "\n", encoding="utf-8")
    r1 = box.tick()
    toast_a = r1.sent[0][1]
    assert "12345678-1234-1234-1234-123456789abc" not in toast_a
    assert "Users" not in toast_a
    assert "C:\\" not in toast_a
    cola_hash_a = r1.keys[0]
    assert f"[{cola_hash_a}]" in toast_a
    box.sent.clear()
    box.events.clear()

    # (b) 300 caracteres 'z' tras el |: el resumen mide max 60
    linea_b = ABIERTA + " | " + "z" * 300
    box.cola.write_text("# cola\n" + linea_b + "\n", encoding="utf-8")
    r2 = box.tick()
    toast_b = r2.sent[0][1]
    resumen_start = toast_b.index("]: ") + 3
    resumen_texto = toast_b[resumen_start:]
    assert len(resumen_texto) <= 60

    # (c) Ruta con secreto: redacta ANTES de acotar
    linea_c = "- [t] [CO-24] ABIERTA | datos C:\\Users\\fdl\\secreto\\x " + "a" * 50
    box.cola.write_text("# cola\n" + linea_c + "\n", encoding="utf-8")
    r3 = box.tick()
    toast_c = r3.sent[0][1]
    assert "Users" not in toast_c
    assert "secreto" not in toast_c
    box.sent.clear()
    box.events.clear()

    # (d) BOM al inicio del fichero: el toast no contiene el BOM
    box.cola.write_bytes(b"\xef\xbb\xbf" + ABIERTA.encode("utf-8") + b"\n")
    r4 = box.tick()
    toast_d = r4.sent[0][1]
    assert "\ufeff" not in toast_d


def test_fila92_cola_sin_salto_final_y_no_utf8(box):
    """Fila 92 (N69): linea sin salto final y bytes no UTF-8 no rompen."""
    # Sin salto final: avisa (rc 1)
    box.cola.write_bytes(ABIERTA.encode("utf-8"))
    r1 = box.tick()
    assert r1.rc == 1

    # Bytes no UTF-8: avisa sin crear evento "detector-roto"
    box.cola.write_bytes(b"\xff\xfe" + ABIERTA.encode("utf-8") + b" \xff\n")
    r2 = box.tick()
    assert r2.rc == 1
    assert ("detector-roto", "AVISO", "stall") not in r2.events


def test_cola_directorio_es_detector_roto(box, tmp_path):
    """Cola como directorio: detector-roto, rc 2."""
    box.cola.unlink()
    box.cola.mkdir()
    r = box.tick()
    assert r.rc == 2
    assert ("detector-roto", "AVISO", "stall") in r.events


def test_cupo_directorio_es_detector_roto(box, tmp_path):
    """Cupo como directorio: detector-roto, rc 2."""
    box.quota.unlink()
    box.quota.mkdir()
    r = box.tick()
    assert r.rc == 2
    assert ("detector-roto", "AVISO", "stall") in r.events


def test_fila103_disco_bajo_avisa(box, monkeypatch):
    """Fila 103 (N77): umbral de disco alto = aviso; umbral 0 = sin aviso."""
    monkeypatch.setenv("STALL_FREE_GB_MIN", "1000000")
    r1 = box.tick()
    assert r1.rc == 1
    assert ("disco", "AVISO", "stall") in r1.events
    assert "GB libres" in r1.sent[0][1]

    monkeypatch.setenv("STALL_FREE_GB_MIN", "0")
    r2 = box.tick()
    assert ("disco", "AVISO", "stall") not in r2.events


def test_fila103_umbral_de_disco_exacto(box, monkeypatch):
    """Fila 103 (N77): el umbral se compara exactamente con GB free de disk_usage."""
    anchor = Path(box.wt.anchor)

    # free=4.9 GB con umbral 5 -> avisa
    def disco_free_4_9(p):
        return types.SimpleNamespace(free=4.9e9)

    monkeypatch.setenv("STALL_FREE_GB_MIN", "5")
    monkeypatch.setattr(box.m.shutil, "disk_usage", disco_free_4_9)
    r1 = box.tick()
    assert r1.rc == 1 and ("disco", "AVISO", "stall") in r1.events

    # free=5.1 GB con umbral 5 -> no avisa
    def disco_free_5_1(p):
        return types.SimpleNamespace(free=5.1e9)

    monkeypatch.setattr(box.m.shutil, "disk_usage", disco_free_5_1)
    r2 = box.tick()
    assert ("disco", "AVISO", "stall") not in r2.events

    # Verifica que disk_usage se llama con la unidad/raiz del motor
    anchor = Path(box.wt.anchor)
    disk_usage_arg = [None]

    def disco_free_4_9_t(p):
        disk_usage_arg[0] = p
        return types.SimpleNamespace(free=4.9e9)

    monkeypatch.setattr(box.m.shutil, "disk_usage", disco_free_4_9_t)
    box.tick()
    assert disk_usage_arg[0] == anchor


def test_fila104_hook_ausente_urgente(box):
    """Fila 104 (N80): el hook de seguridad ausente = URGENTE, se reconcilia al volver."""
    hook = box.wt / ".agent" / "hooks" / "claude_guard_entry.py"
    hook.unlink()

    r1 = box.tick()
    assert r1.rc == 1
    assert ("hook-seguridad", "URGENTE", "stall") in r1.events
    assert '"hook_guard_existe": false' in r1.out

    # Con el hook presente: sin evento nuevo
    hook.write_text("x", encoding="utf-8")
    box.events.clear()
    box.tick()
    assert "hook-seguridad" not in [e[0] for e in box.events]

    # Al volver a crearlo, la clave "event:hook-seguridad" desaparece en el tick siguiente
    box.ca.mark_seen("hook-seguridad", "URGENTE", "stall")
    box.tick()
    assert "event:hook-seguridad" not in box.ca_state()


def test_q6a_motor_ciego_no_borra_la_clave_del_hook_ni_la_de_git(box, tmp_path):
    """Un motor sin resolver (relativo) deja ciego el hook y git: sus claves vivas NO se resuelven."""
    box.ca.mark_seen("hook-seguridad", "URGENTE", "stall")
    box.ca.mark_seen("git-index.lock-wt", "AVISO", "stall")
    box.monkeypatch.chdir(tmp_path)
    r = box.tick("--motor-wt", "relativo", motor=False)
    assert "ciego_hook" in r.out and "ciego_git" in r.out
    st = box.ca_state()
    assert "event:hook-seguridad" in st and "event:git-index.lock-wt" in st
    assert "hook-seguridad" not in box.resolved


def test_d1c_corchetes_en_la_ruta_del_motor_no_ciegan_a_los_hermanos(box, tmp_path):
    """glob.escape: un padre con '[1]' sigue encontrando el worktree hermano con su index.lock."""
    padre = tmp_path / "vuelo[1]"
    motor = make_repo(padre / "implantador-a")
    hermano = padre / "implantador-b"
    _git(motor, "worktree", "add", "-q", "-b", "sib2", str(hermano))
    gd = subprocess.run(
        ["git", "-C", str(hermano), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (Path(gd) / "index.lock").write_text("", encoding="utf-8")
    box.monkeypatch.delenv("STALL_WT_GLOB")
    r = box.tick("--motor-wt", str(motor), motor=False)
    assert ("git-index.lock-implantador-b", "AVISO", "stall") in r.events


# === RONDA 1 (adjudicacion 153j): A1..A7 ===
QUOTA_TICK_PATH = Path(
    os.environ.get("QUOTA_TICK_UNDER_TEST") or FSC_PATH.parent / "quota_tick.py"
)


def _cuenta(pct, stale=False, ventana="weekly"):
    return {"block_pct": pct, "stale": stale, "block_window": ventana}


def _linea_real_de_quota_tick(box, cuentas):
    """La linea que imprime quota_tick.py de VERDAD (monitor falso), para encadenarla con el detector."""
    spec = importlib.util.spec_from_file_location("quota_tick_cadena", QUOTA_TICK_PATH)
    qt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qt)
    (box.flight / "flight_roster.json").write_text('{"quota": {}}', encoding="utf-8")
    salida = json.dumps({"accounts": cuentas})
    buf = []
    old = sys.stdout
    sys.stdout = _Buf(buf)
    try:
        with (
            box.monkeypatch.context() as mp
        ):  # subprocess.run es global: solo durante la medicion
            mp.setenv("SYSTEMROOT", os.environ.get("SYSTEMROOT") or str(box.root))
            mp.setattr(
                qt.subprocess,
                "run",
                lambda cmd, **kw: types.SimpleNamespace(stdout=salida, returncode=0),
            )
            qt.main(
                ["--flight-dir", str(box.flight), "--monitor", str(box.root / "m.ps1")]
            )
    finally:
        sys.stdout = old
    return "".join(buf).strip()


def _con_cupo(box, linea, edad_min=0):
    box.quota.write_text(linea, encoding="utf-8")
    box.quota_touch(edad_min)


@pytest.mark.parametrize(
    ("pct", "clave"),
    [
        (97.0, "cupo-97"),
        (96.9, "cupo-92"),
        (97.4, "cupo-97"),
        (100.0, "cupo-97"),
        (92.5, "cupo-92"),
        (92.0, "cupo-92"),
        (91.9, None),
    ],
)
def test_a1_la_salida_real_de_quota_tick_con_fraccion_llega_al_detector(
    box, pct, clave
):
    """A1: quota_tick imprime el block_pct crudo (97.0, 92.5); el detector lo lee entero, no como 0."""
    linea = _linea_real_de_quota_tick(
        box, {"alvarovans": _cuenta(pct), "brabander": _cuenta(10)}
    )
    assert f"alvarovans weekly {pct}%" in linea
    _con_cupo(box, linea)
    r = box.tick()
    assert [k for k in r.keys if k.startswith("cupo-")] == ([clave] if clave else [])
    esperado = int(pct) if pct == int(pct) else pct
    assert f'"cupo_max": {esperado}' in r.out


def test_a1_la_cuenta_baja_no_tapa_a_la_alta_con_fraccion(box):
    _con_cupo(
        box,
        "QUOTA FREEZE (soft 92/hard 97) | alvarovans weekly 10.5% | brabander weekly 97.0%",
    )
    assert "cupo-97" in box.tick().keys


# Todas las formas en que Python imprime un float de block_pct (A8): entero exacto, decimal,
# exponente con signo (1e+20, 1e-05, 1.5e+300), negativo y cero. "nan"/"inf" se prueban aparte.
FORMAS_DE_FLOAT = [
    (97.0, "cupo-97"),
    (1e20, "cupo-97"),
    (1e16, "cupo-97"),
    (1.5e300, "cupo-97"),
    (9.7e1, "cupo-97"),
    (9.25e1, "cupo-92"),
    (1e-05, None),
    (1.5e-300, None),
    (-3.0, None),
    (-1e20, None),
    (0.0, None),
    (5e-324, None),
]


@pytest.mark.parametrize(("pct", "clave"), FORMAS_DE_FLOAT)
def test_a8_cada_forma_de_float_que_imprime_python_se_lee_entera(box, pct, clave):
    """A8: el token completo (con exponente) llega al detector; 1e+20 no se lee como su sufijo 20."""
    linea = _linea_real_de_quota_tick(
        box, {"alvarovans": _cuenta(pct), "brabander": _cuenta(30)}
    )
    assert f"alvarovans weekly {pct}%" in linea
    _con_cupo(box, linea)
    r = box.tick()
    assert [k for k in r.keys if k.startswith("cupo-")] == ([clave] if clave else [])
    peor = max(pct, 30)  # la otra cuenta esta a 30
    esperado = int(peor) if float(peor).is_integer() else peor
    assert f'"cupo_max": {esperado}' in r.out


@pytest.mark.parametrize(
    ("ventana", "pct", "clave", "cupo_max"),
    [
        ("1e+20%", 40, None, 40),  # la ventana NO es el porcentaje (falso URGENTE)
        ("1e+20%", 99, "cupo-97", 99),
        ("5h 97%", 40, None, 40),
        ("5h 97%", 97, "cupo-97", 97),
        (
            "5% x",
            97,
            "cupo-97",
            97,
        ),  # falso negativo simetrico: la ventana no tapa el pct
        ("5% x", 40, None, 40),
        ("97% 92%", 10, None, 30),
        ("weekly", 92.5, "cupo-92", 92.5),
    ],
)
def test_a9_el_porcentaje_es_el_ultimo_token_y_no_la_ventana_cruda(
    box, ventana, pct, clave, cupo_max
):
    """A9: quota_tick imprime block_window crudo; la ventana con N% no se lee como porcentaje."""
    linea = _linea_real_de_quota_tick(
        box,
        {"alvarovans": _cuenta(pct, ventana=ventana), "brabander": _cuenta(30)},
    )
    assert f"alvarovans {ventana} {pct}%" in linea
    _con_cupo(box, linea)
    r = box.tick()
    assert [k for k in r.keys if k.startswith("cupo-")] == ([clave] if clave else [])
    assert f'"cupo_max": {cupo_max}' in r.out


@pytest.mark.parametrize("pct", [None, float("nan"), float("inf"), float("-inf")])
def test_a9_ventana_con_porcentaje_y_cuenta_sin_el_suyo_sigue_siendo_ilegible(box, pct):
    """La ventana '97%' no sustituye a un pct None%/nan%/inf%: cuenta sin porcentaje, nunca cupo-97."""
    linea = _linea_real_de_quota_tick(
        box,
        {"alvarovans": _cuenta(pct, ventana="97%"), "brabander": _cuenta(30)},
    )
    _con_cupo(box, linea)
    r = box.tick()
    assert "cupo-97" not in r.keys
    # +inf: quota_tick da HARD y el detector cupo-ilegible (deliberado, diferido D9); el resto, no-medido
    assert {"cupo-no-medido", "cupo-ilegible"} & set(r.keys)


def test_a9_ventana_con_porcentaje_y_cuenta_stale_conserva_el_aviso_stale(box):
    linea = _linea_real_de_quota_tick(
        box,
        {
            "alvarovans": _cuenta(40, stale=True, ventana="5h 97%"),
            "brabander": _cuenta(30),
        },
    )
    _con_cupo(box, linea)
    r = box.tick()
    assert "cupo-no-medido" in r.keys and "cupo-97" not in r.keys


def test_a8_un_exponente_alto_no_deja_que_el_reconcile_borre_cupo_97(box):
    """1e+20 en una cuenta y 30 en otra: cupo-97 URGENTE y la clave previa sobrevive."""
    box.ca.mark_seen("cupo-97", "URGENTE", "stall")
    linea = _linea_real_de_quota_tick(
        box, {"alvarovans": _cuenta(1e20), "brabander": _cuenta(30)}
    )
    assert linea.startswith("QUOTA HARD") and "1e+20%" in linea
    _con_cupo(box, linea)
    r = box.tick()
    assert ("cupo-97", "URGENTE", "stall") in r.events
    assert "event:cupo-97" in box.ca_state() and "resueltas" not in r.out


def test_a8_un_cupo_bajo_con_exponente_negativo_si_se_reconcilia(box):
    """Control del anterior: 1e-05 es un cupo bajo legitimo y la clave vieja SI se borra."""
    box.ca.mark_seen("cupo-97", "URGENTE", "stall")
    linea = _linea_real_de_quota_tick(
        box, {"alvarovans": _cuenta(1e-05), "brabander": _cuenta(30)}
    )
    _con_cupo(box, linea)
    box.tick()
    assert "event:cupo-97" not in box.ca_state()


@pytest.mark.parametrize(
    ("segmento", "clave"),
    [
        ("alvarovans weekly 1E+20%", "cupo-97"),
        ("alvarovans weekly 9.5E+1%", "cupo-92"),
        ("alvarovans weekly +97%", "cupo-97"),
        ("alvarovans 5h 97.0%", "cupo-97"),
    ],
)
def test_a8_tokens_a_mano_con_mayuscula_signo_y_ventana_con_digitos(
    box, segmento, clave
):
    _con_cupo(box, f"QUOTA HARD (soft 92/hard 97) | {segmento} | brabander weekly 30%")
    assert clave in box.tick().keys


@pytest.mark.parametrize("crudo", ["nan", "inf", "-inf", "None"])
def test_a8_nan_e_infinito_siguen_siendo_cuenta_sin_porcentaje(box, crudo):
    _con_cupo(
        box,
        f"QUOTA NO_MEDIDO (soft 92/hard 97) | alvarovans weekly {crudo}% | brabander weekly 30%",
    )
    r = box.tick()
    assert "cupo-no-medido" in r.keys and "cupo-97" not in r.keys


def test_a2_cabecera_no_medido_con_otra_cuenta_baja_es_ciega_y_no_borra_claves(box):
    """A2: 40 % + None% (cabecera real NO_MEDIDO) no es una medicion valida."""
    box.ca.mark_seen("cupo-97", "URGENTE", "stall")
    linea = _linea_real_de_quota_tick(
        box, {"alvarovans": _cuenta(40), "brabander": _cuenta(None)}
    )
    assert linea.startswith("QUOTA NO_MEDIDO") and "None%" in linea
    _con_cupo(box, linea)
    r = box.tick()
    assert ("cupo-no-medido", "AVISO", "stall") in r.events
    assert "cupo-ilegible" not in r.keys and "ciego_cupo" in r.out
    assert "event:cupo-97" in box.ca_state() and "cupo-97" not in box.resolved


def test_a2_cuenta_stale_con_porcentaje_bajo_es_ciega_y_no_borra_claves(box):
    box.ca.mark_seen("cupo-92", "AVISO", "stall")
    _con_cupo(
        box,
        "QUOTA OK (soft 92/hard 97) | alvarovans weekly 40% STALE | brabander weekly 30%",
    )
    r = box.tick()
    assert ("cupo-no-medido", "AVISO", "stall") in r.events
    assert "STALE" in r.sent[0][1] and "ciego_cupo" in r.out
    assert "event:cupo-92" in box.ca_state()


def test_a2_stale_real_de_quota_tick_es_ciego(box):
    linea = _linea_real_de_quota_tick(
        box, {"alvarovans": _cuenta(40, stale=True), "brabander": _cuenta(30)}
    )
    _con_cupo(box, linea)
    assert ("cupo-no-medido", "AVISO", "stall") in box.tick().events


def test_a2_cuenta_sin_porcentaje_con_cabecera_ok_es_ilegible_y_no_borra_claves(box):
    box.ca.mark_seen("cupo-97", "URGENTE", "stall")
    _con_cupo(
        box,
        "QUOTA OK (soft 92/hard 97) | alvarovans weekly 40% | brabander weekly None%",
    )
    r = box.tick()
    assert ("cupo-ilegible", "AVISO", "stall") in r.events
    assert "ciego_cupo" in r.out and "event:cupo-97" in box.ca_state()


def test_a2_no_medido_sin_cuentas_avisa_una_sola_vez_como_no_medido(box):
    _con_cupo(box, "QUOTA NO_MEDIDO monitor: JSONDecodeError Expecting value")
    r = box.tick()
    claves = [k for k in r.keys if k.startswith("cupo-")]
    assert claves == ["cupo-no-medido"] and "ciego_cupo" in r.out


def test_a2_no_medido_no_oculta_un_corte_duro_visible(box):
    linea = _linea_real_de_quota_tick(
        box, {"alvarovans": _cuenta(99), "brabander": _cuenta(None)}
    )
    _con_cupo(box, linea)
    claves = {k for k in box.tick().keys if k.startswith("cupo-")}
    assert claves == {"cupo-97", "cupo-no-medido"}


def test_a2_antiguedad_y_no_medido_se_dicen_en_un_solo_aviso(box):
    _con_cupo(box, "QUOTA NO_MEDIDO monitor: x", edad_min=60)
    r = box.tick()
    assert r.keys.count("cupo-no-medido") == 1
    assert "60 min sin medirse" in r.sent[0][1] and "NO_MEDIDO" in r.sent[0][1]


def test_a5_excepcion_en_self_check_es_rc2_con_marcador(box, monkeypatch):
    def roto(a, ops):
        raise RuntimeError("a proposito")

    monkeypatch.setattr(box.m, "_resolve_paths", roto)
    r = box.tick("--self-check", ops=False)
    assert r.rc == 2
    assert r.out.startswith("STALL_CHECK_BROKEN: RuntimeError: a proposito")


def test_a5_self_check_con_umbral_de_disco_invalido_no_dice_ok(box, monkeypatch):
    monkeypatch.setenv("STALL_FREE_GB_MIN", "abc")
    r = box.tick("--self-check", ops=False)
    assert r.rc == 2 and "STALL_FREE_GB_MIN invalido" in r.out
    assert "self-check: OK" not in r.out


def _disco(box, monkeypatch, free_bytes):
    monkeypatch.setattr(
        box.m.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=free_bytes)
    )


@pytest.mark.parametrize(("libre", "avisa"), [(5.0e9, False), (4_999_999_999, True)])
def test_a6_el_umbral_exacto_de_disco_no_avisa(box, monkeypatch, libre, avisa):
    """A6: free == umbral no avisa (es `<`, no `<=`)."""
    monkeypatch.setenv("STALL_FREE_GB_MIN", "5")
    _disco(box, monkeypatch, libre)
    assert ("disco" in box.tick().keys) is avisa


@pytest.mark.parametrize(("libre", "avisa"), [(4.9e9, True), (5.1e9, False)])
def test_a6_el_umbral_de_disco_por_defecto_es_5_gb(box, monkeypatch, libre, avisa):
    """A6: sin STALL_FREE_GB_MIN manda el defecto de produccion (5 GB)."""
    monkeypatch.delenv("STALL_FREE_GB_MIN")
    _disco(box, monkeypatch, libre)
    assert ("disco" in box.tick().keys) is avisa


@pytest.mark.skipif(not WINDOWS, reason="rutas UNC solo en Windows")
@pytest.mark.parametrize("ruta", [r"\\srv\r\q.txt", r"\\?\UNC\srv\r\q.txt"])
def test_a7_quota_file_unc_se_rechaza_en_todas_sus_formas(box, ruta):
    r = box.tick("--quota-file", ruta)
    assert ("detector-sin-config", "AVISO", "stall") in r.events
    assert "quota-file en ruta de red (UNC)" in r.sent[0][1]


@pytest.mark.skipif(not WINDOWS, reason="rutas UNC solo en Windows")
def test_a7_quota_file_por_entorno_unc_tambien(box, monkeypatch):
    monkeypatch.setenv("STALL_QUOTA_FILE", r"\\?\UNC\srv\r\q.txt")
    assert "quota-file en ruta de red (UNC)" in box.tick().sent[0][1]


@pytest.mark.skipif(not WINDOWS, reason="rutas UNC solo en Windows")
def test_a7_forma_local_con_prefijo_extendido_no_es_unc(box):
    """`\\\\?\\C:\\x` es local: se acepta como quota-file, flight-dir y motor."""
    r = box.tick(
        "--quota-file",
        "\\\\?\\" + str(box.quota),
        "--flight-dir",
        "\\\\?\\" + str(box.flight),
        flight=False,
    )
    assert r.rc == 0 and "detector-sin-config" not in r.keys


@pytest.mark.skipif(not WINDOWS, reason="rutas UNC solo en Windows")
@pytest.mark.parametrize("ruta", [r"\\srv\r\x", r"\\?\UNC\srv\r\x"])
def test_a7_flight_dir_unc_en_las_dos_formas(box, ruta):
    r = box.tick("--flight-dir", ruta, flight=False)
    assert "ruta de red (UNC)" in r.sent[0][1]


# === cierre de supervivientes (Manager): texto de la causa, UNC, precedencia y recorte ===
def test_sc1_el_aviso_sin_config_nombra_la_causa(box, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel").mkdir()
    r = box.tick("--flight-dir", "rel", flight=False)
    assert "Detector sin configurar: " in r.sent[0][1]
    assert "debe ser una ruta absoluta" in r.sent[0][1]


@pytest.mark.skipif(not WINDOWS, reason="UNC solo en Windows")
@pytest.mark.parametrize("flag", ["--flight-dir", "--motor-wt"])
def test_p8_unc_en_flight_dir_o_motor_se_rechaza(box, flag):
    kw = {"flight": False} if flag == "--flight-dir" else {"motor": False}
    r = box.tick(flag, r"\\servidor\recurso\x", **kw)
    assert ("detector-sin-config", "AVISO", "stall") in r.events
    assert "ruta de red (UNC)" in r.sent[0][1]


def test_p14_flight_dir_argumento_gana_al_entorno(box, tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_DIR", str(tmp_path / "no_existe"))
    r = box.tick()
    assert r.rc == 0 and "detector-sin-config" not in r.keys


def test_n68b_el_recorte_a_60_no_parte_un_uuid_que_la_redaccion_ya_no_ve(box):
    """Se redacta ANTES de acotar: un UUID a caballo del caracter 60 no deja un trozo suelto."""
    uuid = "12345678-1234-1234-1234-123456789abc"
    linea = f"- [t] [CO-24] ABIERTA | {'a' * 50} {uuid}"
    box.cola.write_text("# cola\n" + linea + "\n", encoding="utf-8")
    toast = box.tick().sent[0][1]
    assert "12345678" not in toast and "1234-1234" not in toast


def test_n80b_dry_run_no_concilia_ni_imprime_borrados(box):
    """--dry-run no resuelve claves: ni las borra ni anuncia que lo hizo."""
    box.ca.mark_seen("cupo-92", "AVISO", "stall")
    box.ca.mark_seen("tarea-muerta", "AVISO", "stall")
    box.resolved.clear()
    r = box.tick("--dry-run")
    assert "resueltas" not in r.out and "resuelta tarea-muerta" not in r.out
    assert box.resolved == []
    assert "event:cupo-92" in box.ca_state()


def test_go_tick_reconoce_clave_go_y_titulo_go_pendiente(box):
    """E1/E6: el tick parsea go-id, no subcadenas, y usa título GO pendiente."""
    box.notify_rc = 2
    assert (
        box.ca.main(
            [
                "--ops-dir",
                str(box.ops),
                "--flight-dir",
                str(box.flight),
                "--go-id",
                "go-tick",
                "--owner",
                "IM-56",
                "--what",
                "Escribe GO 1",
            ]
        )
        == 2
    )
    resultado = box.tick()
    assert resultado.sent[0][0] == "IM-56"
    assert "Escribe GO 1" in resultado.sent[0][1]
    assert "event:go-tick" not in box.ca_state()


def test_caja1_go_real_en_cola_llega_al_tick_con_codigo_y_frase(box):
    """RED/E3: la linea real de go_request debe producir en el tick titulo y frase de la sesion."""
    box.notify_rc = 2
    box.ca.main(
        [
            "--ops-dir",
            str(box.ops),
            "--flight-dir",
            str(box.flight),
            "--go-id",
            "go-caja1-tick",
            "--owner",
            "CO-29",
            "--what",
            "PUSH C:/Users/fdl/repo mcp:12345678-1234-1234-1234-123456789012 16.",
        ]
    )
    box.notify_rc = 0
    result = box.tick("--dry-run")
    assert result.sent, result.out
    assert result.sent[0][0] == "CO-29"
    assert result.sent[0][1].startswith("PUSH C:/Users/fdl/repo")
    assert "mcp:12345678-1234-1234-1234-123456789012" in result.sent[0][1]


def test_f5_el_arranque_del_vigilante_invoca_clear_group(box):
    """F5: el tick invoca la limpieza acotada del Group propio."""
    box.tick("--dry-run")
    assert box.clear_group_calls == [True]


def test_clear_group_no_se_retira_mientras_persiste_la_causa(box):
    """Una causa activa en dos ticks conserva el Group; solo el tick vacio lo limpia."""
    box.cola.write_text(
        "# cola\n- [2026-11-04 13:30:00] [CO-29] ABIERTA BLOQUEA | go-persist: FRASE\n",
        encoding="utf-8",
    )
    assert box.tick().rc in (0, 1)
    assert box.tick().rc in (0, 1)
    assert box.clear_group_calls == []


def test_clear_group_no_retira_si_hay_causa_activa_de_otro_productor(box):
    """Una clave de check activa evita retirar el Group aunque este tick no halle causas."""
    box.ca.event(
        "latido-desviado", "URGENTE", None, "causa check", False, False, owner="check"
    )
    box.tick("--dry-run")
    assert box.clear_group_calls == []
    box.ca.resolve("latido-desviado")
    box.tick("--dry-run")
    assert box.clear_group_calls == [True]


@pytest.mark.parametrize(
    "line",
    [
        "- [2026-11-04 13:30:00] [not-a-code] ABIERTA BLOQUEA | go-bad: FRASE LITERAL primero",
        "- [2026-11-04 13:30:00] [] ABIERTA BLOQUEA | go-missing: FRASE LITERAL primero",
    ],
)
def test_caja1_go_line_owner_invalido_o_ausente_fallback_generico(box, line):
    """RED/E3: una linea GO sin codigo de emisor no inyecta identidad en el titulo."""
    box.cola.write_text("# cola\n" + line + "\n", encoding="utf-8")
    result = box.tick("--dry-run")
    assert result.sent, result.out
    assert result.sent[0][0] == "Vuelo ?"


def test_go_tick_fallo_y_exito_no_duplica_aviso(box):
    """E6: tick posterior al fallo avisa; tras éxito el tick siguiente no duplica."""
    box.notify_rc = 2
    assert (
        box.ca.main(
            [
                "--ops-dir",
                str(box.ops),
                "--flight-dir",
                str(box.flight),
                "--go-id",
                "go-fallback",
                "--owner",
                "IM-56",
                "--what",
                "Escribe GO 1",
            ]
        )
        == 2
    )
    failed_tick = box.tick()
    assert failed_tick.sent[0][0] == "IM-56"
    box.notify_rc = 0
    assert (
        box.ca.main(
            [
                "--ops-dir",
                str(box.ops),
                "--flight-dir",
                str(box.flight),
                "--go-id",
                "go-fallback",
                "--owner",
                "IM-56",
                "--what",
                "Escribe GO 1",
            ]
        )
        == 0
    )
    sent = len(box.sent)
    assert box.tick().sent == []
    assert len(box.sent) == sent
