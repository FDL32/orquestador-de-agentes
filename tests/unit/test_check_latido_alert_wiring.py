"""WOT-2026-153k: pruebas del check de latidos (scripts/flight/check_latido_alert_wiring.py).

Cada prueba lleva en su docstring la FILA del Anexo B del plan 153h que cubre (130-165) y la
mutacion N que debe matarla. Los fixtures son SINTETICOS: un repo git temporal con los cinco
scripts del inventario como stubs, un roster `{}` y latidos de texto escritos por el fixture.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
from scripts.closeout_steps.gates import step_latido_alert_wiring
from scripts.session_closeout import StepResult


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "flight" / "check_latido_alert_wiring.py"
_spec = importlib.util.spec_from_file_location("check_latido_alert_wiring_t", _SCRIPT)
chk = importlib.util.module_from_spec(_spec)
sys.modules["check_latido_alert_wiring_t"] = chk
_spec.loader.exec_module(chk)

windows_only = pytest.mark.skipif(os.name != "nt", reason="PowerShell de Windows")

_STUBS = (
    "comms_alert.py",
    "flight_stall_check.py",
    "quota_tick.py",
    "tick_trace.py",
    "notify_user.ps1",
    "check_latido_alert_wiring.py",
)

# Copia literal del parrafo GO AL USUARIO del latido real de CO-28 (linea 19,
# 2026-11-04). El test no lee el workspace del vuelo.
LATIDO_REAL_GO_MANUAL = r"""GO AL USUARIO (seccion 8 del ARRANQUE_CO-27, b7861d02fbf8): toda solicitud de GO sale como notificacion en pantalla en la MISMA accion: (1) linea ABIERTA BLOQUEA en diseno\COLA_PARA_USUARIO.md con la frase literal esperada (la ruta absoluta de la cola es esa; no crees otra); (2) FLIGHT_OPS_DIR=C:/Users/fdl/tmp_or8 python scripts/flight/comms_alert.py --event go-<id> --level URGENTE --title "GO pendiente: <ticket>" --what "<frase literal>" (--what se redacta y se recorta a 160 caracteres: la frase LITERAL esta en la cola); al recibir el GO: comms_alert.py --resolve go-<id> y marca la linea RESUELTA. LIMITE CONOCIDO (bucle de avisos, tickets 153s y 153h): el tick avisa ademas la linea de cola con la clave cola-<sha1>, asi que un GO genera DOS avisos hasta que 153s unifique la clave; no resuelvas a mano la clave cola-<sha1>: se limpia sola cuando la linea pasa a RESUELTA."""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )


class Box:
    """Motor sintetico (repo git con los 5 scripts del inventario) + roster + latidos."""

    def __init__(self, root: Path) -> None:
        self._bind(root)
        self.flight.mkdir(parents=True)
        for name in _STUBS:
            (self.flight / name).write_text(f"# stub {name}\n", encoding="utf-8")
        _git(self.motor, "init", "-q")
        _git(self.motor, "config", "user.email", "t@example.invalid")
        _git(self.motor, "config", "user.name", "t")
        _git(self.motor, "add", "-A")
        _git(self.motor, "commit", "-q", "-m", "stubs")
        self.roster.write_text("{}", encoding="utf-8")
        self.ops.mkdir()

    @classmethod
    def _bound(cls, root: Path) -> Box:
        """Before: recibe una copia ya construida. During: liga sus rutas. After: devuelve la caja ligada."""
        obj = cls.__new__(cls)
        obj._bind(root)
        return obj

    def _bind(self, root: Path) -> None:
        """Before: recibe la raiz de una caja. During: calcula todas sus rutas. After: no escribe nada."""
        self.root = root
        self.motor = root / "motor"
        self.flight = self.motor / "scripts" / "flight"
        self.py = sys.executable
        self.ps = str(
            Path(os.environ.get("SYSTEMROOT", ""))
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        self.roster = root / "roster.json"
        self.ops = root / "ops"

    def s(self, name: str) -> str:
        """Ruta absoluta del script del inventario dentro del motor sintetico."""
        return str(self.flight / name)

    def coord_orders(self) -> list[str]:
        """Las 7 ordenes obligatorias de la coordinadora (todas validas)."""
        py = self.py
        return [
            f"{py} {self.s('comms_alert.py')} --scan --ops-dir {self.ops}",
            f'{py} {self.s("comms_alert.py")} --event clave --level URGENTE --what "x"',
            f"{py} {self.s('flight_stall_check.py')} --ops-dir {self.ops}",
            f"{py} {self.s('flight_stall_check.py')} --self-check",
            f"{py} {self.s('quota_tick.py')} > {self.root / 'quota.txt'}",
            f"{py} {self.s('check_latido_alert_wiring.py')} --alert",
            self.trace_order(),
        ]

    def trace_order(self, *, markers: bool = False) -> str:
        """Construye la orden completa de tick_trace para los fixtures."""
        values = {
            "ops": "<ops-dir>" if markers else str(self.ops),
            "coordinator": "<coordinator>" if markers else "CO-48",
            "roster": "<roster-sha12>" if markers else "0123456789ab",
            "guard": "<guard-rc>" if markers else "0",
            "quota": "<quota-rc>" if markers else "0",
            "summary": "<quota-summary>" if markers else "ok",
        }
        return (
            f"{self.py} {self.s('tick_trace.py')} --ops-dir {values['ops']} "
            f"--coordinator {values['coordinator']} --roster-sha12 {values['roster']} "
            f"--guard-rc {values['guard']} --quota-rc {values['quota']} "
            f"--quota-summary {values['summary']}"
        )

    def sup_orders(self) -> list[str]:
        """Las 2 ordenes obligatorias de la supervisora (todas validas; PowerShell = Windows)."""
        return [
            f"{self.ps} -NoProfile -NonInteractive -File {self.s('notify_user.ps1')}"
            " -Title t -Message m",
            f"{self.py} {self.s('quota_tick.py')}",
        ]

    def latido(self, name: str, orders: list[str], prose: str = "") -> Path:
        """Escribe un latido: una linea `- `orden`` por orden (codigo en linea) y prosa."""
        body = "\n".join(f"- `{o}`" for o in orders)
        path = self.root / name
        path.write_text(f"Latido sintetico.\n{prose}\n{body}\n", encoding="utf-8")
        return path

    def argv(
        self,
        coord: Path | str | None = None,
        sup: Path | str | None = None,
        extra: tuple[str, ...] = (),
        roster: bool = True,
    ) -> list[str]:
        """Argumentos de la CLI (python fijado = el interprete de la prueba)."""
        args = ["--motor-root", str(self.motor), "--python-exe", self.py]
        if roster:
            args += ["--roster-path", str(self.roster)]
        if coord is not None:
            args += ["--latido-file", f"coordinadora={coord}"]
        if sup is not None:
            args += ["--latido-file", f"supervisora={sup}"]
        return args + list(extra)

    def good(self) -> tuple[Path, Path]:
        """(latido de coordinadora, latido de supervisora) correctos."""
        return self.latido("c.md", self.coord_orders()), self.latido(
            "s.md", self.sup_orders()
        )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        chk.ROSTER_ENV,
        chk.LATIDO_ENV,
        chk.PYTHON_ENV,
        chk.OPS_DIR_ENV,
        chk.FLIGHT_DIR_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _hermetic_alert_subprocesses(monkeypatch, tmp_path, request):
    """Hermetiza ``--alert`` por run/check_output, cadenas y Popen directo.

    Before: cualquier prueba puede lanzar el script del check en subproceso.
    During: intercepta la orden y el Popen subyacente, registra ambos y el hijo recibe un stub;
        los demás subprocess (git y sondas PowerShell) conservan su comportamiento.
    After: el log prueba la barrera; nunca se abre PowerShell real y no se fuerza dry-run.
    """
    real_run = subprocess.run
    real_popen = subprocess.Popen
    log = tmp_path / "alert_subprocess_guard.log"
    request.node._alert_subprocess_guard_log = log
    stub_dir = tmp_path / "alert_stub"
    stub_dir.mkdir()
    stub_log = str(log).replace("\\", "\\\\")
    (stub_dir / "sitecustomize.py").write_text(
        "import subprocess\n"
        "_real_run = subprocess.run\n"
        "def _stub_run(cmd, *args, **kwargs):\n"
        "    words = [str(x) for x in cmd] if isinstance(cmd, (list, tuple)) else [str(cmd)]\n"
        "    if any('notify_user.ps1' in x.lower() for x in words) and '-file' in [x.lower() for x in words]:\n"
        f"        open(r'{stub_log}', 'a', encoding='utf-8').write('POWERSHELL_STUB\\n' + ' '.join(words) + '\\n')\n"
        "        return subprocess.CompletedProcess(cmd, 0, '', '')\n"
        "    return _real_run(cmd, *args, **kwargs)\n"
        "subprocess.run = _stub_run\n",
        encoding="utf-8",
    )

    def is_alert(cmd):
        text = (
            " ".join(str(item) for item in cmd)
            if isinstance(cmd, (list, tuple))
            else str(cmd)
        )
        return "check_latido_alert_wiring.py" in text and "--alert" in text

    def child_env(kwargs):
        env = dict(kwargs.get("env") or os.environ)
        env["PYTHONPATH"] = str(stub_dir) + os.pathsep + env.get("PYTHONPATH", "")
        kwargs["env"] = env
        return kwargs

    def record(kind, cmd):
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"INTERCEPTED {kind} check --alert\n{cmd}\n")

    def guarded_run(cmd, *args, **kwargs):
        if is_alert(cmd):
            record("run", cmd)
            kwargs = child_env(kwargs)
        return real_run(cmd, *args, **kwargs)

    def guarded_popen(cmd, *args, **kwargs):
        if is_alert(cmd):
            record("Popen", cmd)
            kwargs = child_env(kwargs)
        return real_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(subprocess, "Popen", guarded_popen)


@pytest.fixture(scope="session")
def _box_template(tmp_path_factory) -> Path:
    """Before: recibe el factory aislado del worker. During: construye una plantilla. After: devuelve su raiz."""
    template = tmp_path_factory.mktemp("box_template")
    Box(template)
    return template


@pytest.fixture
def box(tmp_path, _box_template) -> Box:
    """Before: recibe la plantilla y el tmp del test. During: copia el arbol. After: devuelve una caja propia."""
    dest = tmp_path / "box"
    shutil.copytree(_box_template, dest)
    return Box._bound(dest)


def run(argv: list[str], capsys) -> tuple[int, str]:
    """main(argv) en proceso: (rc, stdout)."""
    rc = chk.main(argv)
    return rc, capsys.readouterr().out


# ------------------------------------------------------------------ ejemplos resueltos
@windows_only
def test_fila_131_latidos_correctos_dan_rc_0(box, capsys):
    """Control positivo de TODAS las filas: los fixtures correctos dan rc 0 (el rojo esperado
    de los latidos reales, rc 1, lo mide el informe de la caja)."""
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0, out
    assert out.startswith("latido-check: OK")


def test_tick_trace_valido_es_obligatorio_una_vez_y_acepta_marcadores(box, capsys):
    """WOT-2026-158a D1-D5: una traza completa valida el latido con marcadores."""
    orders = box.coord_orders()
    orders[-1] = box.trace_order(markers=True)
    coord = box.latido("tick-markers.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 0, out
    assert "latido-check: OK" in out


def test_tick_trace_duplicado_es_violacion(box, capsys):
    """WOT-2026-158a D2/D5: dos trazas validas no satisfacen exactamente una."""
    orders = [*box.coord_orders(), box.trace_order()]
    coord = box.latido("tick-duplicate.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "exactamente una" in out


def test_tick_trace_ausente_es_violacion(box, capsys):
    """WOT-2026-158a D2: omitir la traza obligatoria invalida el latido."""
    orders = box.coord_orders()
    orders.pop()
    coord = box.latido("tick-missing-order.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "falta una orden VALIDA de tick_trace.py" in out


def test_tick_trace_sin_ops_dir_se_rechaza_por_la_ruta_cli(box, capsys):
    """WOT-2026-158a D6: la CLI rechaza tick_trace sin --ops-dir con rc 1."""
    orders = box.coord_orders()
    orders[-1] = box.trace_order().replace("--ops-dir " + str(box.ops), "")
    coord = box.latido("tick-no-ops.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "falta el parametro obligatorio de tick_trace.py: --ops-dir" in out


@pytest.mark.parametrize(
    "flag",
    [
        "--ops-dir",
        "--coordinator",
        "--roster-sha12",
        "--guard-rc",
        "--quota-rc",
        "--quota-summary",
    ],
)
def test_tick_trace_cada_flag_exigido_es_necesario(box, capsys, flag):
    """WOT-2026-158a D3: quitar cualquier flag exigido invalida el tick."""
    orders = box.coord_orders()
    trace = box.trace_order()
    tokens = trace.split()
    index = tokens.index(flag)
    del tokens[index : index + 2]
    orders[-1] = " ".join(tokens)
    coord = box.latido(f"tick-missing-{flag[2:]}.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert flag in out


@pytest.mark.parametrize("flag", ["--ops-dir"])
def test_tick_trace_metadata_required_fija_mensaje_completo(flag, box):
    """WOT-2026-160a P4: metadata real required fija el mensaje exacto para ops-dir."""
    assert chk._SCRIPT_OPTION_META["tick_trace.py"][flag].required is True
    args = box.trace_order().split()
    script_index = next(
        i for i, token in enumerate(args) if token.endswith("tick_trace.py")
    )
    script_args = args[script_index + 1 :]
    index = script_args.index(flag)
    del script_args[index : index + 2]
    order = chk._Order(1, "tick_trace.py " + " ".join(script_args))
    checker = chk._Checker(box.motor, box.py, None, {})

    checker._check_script_arguments(order, script_args, "tick_trace.py")

    assert order.problems == [
        ("V", f"falta el parametro obligatorio de tick_trace.py: {flag}")
    ]


def _finding_messages(output):
    """Normaliza ubicacion y receta, conservando la lista completa de mensajes."""
    return [
        line.split(": ", 1)[1].split(" | ", 1)[0]
        for line in output.splitlines()
        if line.startswith("  - [")
    ]


@pytest.mark.parametrize(
    "flag",
    [
        "--coordinator",
        "--roster-sha12",
        "--guard-rc",
        "--quota-rc",
        "--quota-summary",
    ],
)
def test_tick_trace_inventory_required_flags_fijan_hallazgos_reales(flag, box, capsys):
    """WOT-2026-160a P4: cinco flags vienen de _INVENTORY (l.109-120), no de metadata required."""
    assert chk._SCRIPT_OPTION_META["tick_trace.py"][flag].required is False
    orders = box.coord_orders()
    tokens = box.trace_order().split()
    index = tokens.index(flag)
    del tokens[index : index + 2]
    orders[-1] = " ".join(tokens)
    coord = box.latido(f"tick-inventory-missing-{flag[2:]}.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert _finding_messages(out) == [
        "falta una orden VALIDA de tick_trace.py --coordinator --guard-rc "
        "--ops-dir --quota-rc --quota-summary --roster-sha12 sin --ts"
    ]


def _tick_trace_argument_problems(box, flag, value, form):
    """Devuelve hallazgos y rc agregado de una orden completa de tick_trace."""
    args = box.trace_order().split()
    script_index = next(
        i for i, token in enumerate(args) if token.endswith("tick_trace.py")
    )
    script_args = args[script_index + 1 :]
    index = script_args.index(flag)
    if form == "inline":
        script_args[index] = f"{flag}={value}"
        del script_args[index + 1]
    else:
        script_args[index + 1] = value
    order = chk._Order(1, "tick_trace.py " + " ".join(script_args))
    checker = chk._Checker(box.motor, box.py, None, {})
    checker._check_script_arguments(order, script_args, "tick_trace.py")
    findings = [
        chk._Finding(kind, "coordinadora", "", text) for kind, text in order.problems
    ]
    return order.problems, chk.aggregate(findings)


_RC_INLINE_CASES = [
    (
        "--guard-rc",
        "abc",
        "valor no aceptado por tick_trace.py: --guard-rc=abc (guard-rc must be an integer)",
    ),
    (
        "--quota-rc",
        "abc",
        "valor no aceptado por tick_trace.py: --quota-rc=abc (quota-rc must be an integer)",
    ),
    ("--guard-rc", "0", None),
    ("--quota-rc", "0", None),
    ("--guard-rc", "", "--guard-rc: valor ausente o con apariencia de flag"),
    ("--quota-rc", "", "--quota-rc: valor ausente o con apariencia de flag"),
    ("--guard-rc", "-5", "--guard-rc: valor ausente o con apariencia de flag"),
    ("--quota-rc", "-5", "--quota-rc: valor ausente o con apariencia de flag"),
    ("--guard-rc", "<guard-rc>", None),
    ("--quota-rc", "<quota-rc>", None),
]


def _space_expected(flag, value, inline_expected):
    if value == "":
        return (
            f"valor no aceptado por tick_trace.py: {flag}= ({flag[2:]} "
            "must be an integer)"
        )
    if value == "-5":
        return f"{flag}: falta el valor o parece otra opcion"
    return inline_expected


def _expected_problems(flag, value, expected, form):
    if expected is None:
        return []
    problems = [("V", expected)]
    if form == "space" and value == "-5":
        problems.append(("V", "opcion desconocida para tick_trace.py: -5"))
    return problems


_RC_EQUIVALENCE_CASES = [
    (*case, _space_expected(case[0], case[1], case[2])) for case in _RC_INLINE_CASES
]


@pytest.mark.parametrize(
    ("flag", "value", "expected"),
    _RC_INLINE_CASES,
    ids=[f"{flag[2:]}-{value or 'empty'}" for flag, value, _ in _RC_INLINE_CASES],
)
def test_tick_trace_rc_inline_matrix(box, flag, value, expected):
    """WOT-2026-160a DA: ambos flags cubren todas las formas inline."""
    problems, rc = _tick_trace_argument_problems(box, flag, value, "inline")
    expected_problems = _expected_problems(flag, value, expected, "inline")
    assert problems == expected_problems
    assert rc == (0 if expected is None else 1)


@pytest.mark.parametrize(
    ("flag", "value", "inline_expected", "space_expected"),
    _RC_EQUIVALENCE_CASES,
    ids=[
        f"{flag[2:]}-{value or 'empty'}" for flag, value, _, _ in _RC_EQUIVALENCE_CASES
    ],
)
def test_tick_trace_rc_inline_y_espacio_compara_hallazgos_completos(
    box, flag, value, inline_expected, space_expected
):
    """WOT-2026-160a DA: ambas representaciones fijan listas completas y el mismo rc."""
    inline, inline_rc = _tick_trace_argument_problems(box, flag, value, "inline")
    space, space_rc = _tick_trace_argument_problems(box, flag, value, "space")
    expected_inline = _expected_problems(flag, value, inline_expected, "inline")
    expected_space = _expected_problems(flag, value, space_expected, "space")
    assert inline == expected_inline
    assert space == expected_space
    assert inline_rc == space_rc


def test_tick_trace_opcion_no_derivada_se_rechaza_por_la_ruta_cli(box, capsys):
    """WOT-2026-158a D6: una opcion ajena al productor se rechaza con rc 1."""
    orders = box.coord_orders()
    orders[-1] = box.trace_order().replace(
        "--quota-summary ok", "--not-a-real-option x"
    )
    coord = box.latido("tick-unknown-option.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "opcion desconocida para tick_trace.py: --not-a-real-option" in out


def test_tick_trace_ts_esta_prohibido(box, capsys):
    """WOT-2026-158a D4: el reloj del productor no se fija desde el latido."""
    orders = box.coord_orders()
    orders[-1] += " --ts <fixed-ts>"
    coord = box.latido("tick-fixed-ts.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "--ts" in out and "prohibid" in out


def test_tick_trace_ts_inline_esta_prohibido(box, capsys):
    """T2: la forma inline --ts=... tambien queda prohibida."""
    orders = box.coord_orders()
    orders[-1] += " --ts=<fixed-ts>"
    coord = box.latido("tick-fixed-ts-inline.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "--ts" in out and "prohibid" in out


def test_tick_trace_prefijo_t_es_desconocido(box, capsys):
    """T2: --t no puede adquirir semantica por prefijo de --ts."""
    orders = box.coord_orders()
    orders[-1] += " --t <fixed-ts>"
    coord = box.latido("tick-short-ts.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "opcion desconocida para tick_trace.py: --t" in out


def test_tick_trace_valida_mas_otra_con_ts_falla_por_prohibicion_y_duplicado(
    box, capsys
):
    """T2: una orden valida y otra con --ts disparan ambas barreras."""
    orders = [*box.coord_orders(), box.trace_order() + " --ts <fixed-ts>"]
    coord = box.latido("tick-valid-and-ts.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "opcion prohibida para tick_trace.py" in out
    assert "exactamente una" in out


def test_tick_trace_duplicado_con_marcadores_es_violacion(box, capsys):
    """T2: dos órdenes válidas con marcadores siguen siendo dos ticks."""
    orders = [*box.coord_orders(), box.trace_order(markers=True)]
    coord = box.latido("tick-marker-duplicate.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "exactamente una" in out


@pytest.mark.parametrize("flag", ["--guard-rc", "--quota-rc"])
def test_tick_trace_rc_literal_no_entero_es_rechazado(box, capsys, flag):
    """T2: los RC literales respetan int(raw, 10) del productor real."""
    orders = box.coord_orders()
    orders[-1] = box.trace_order().replace(f"{flag} 0", f"{flag} abc")
    coord = box.latido(f"tick-bad-{flag[2:]}.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert f"valor no aceptado por tick_trace.py: {flag}=abc" in out


@pytest.mark.parametrize("flag", ["--guard-rc", "--quota-rc"])
def test_tick_trace_rc_marcador_es_aceptado(box, capsys, flag):
    """T2: cada RC admite un marcador posicional del latido."""
    orders = box.coord_orders()
    orders[-1] = box.trace_order().replace(f"{flag} 0", f"{flag} <{flag[2:]}>")
    coord = box.latido(f"tick-marker-{flag[2:]}.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 0, out


def test_tick_trace_unmeasured_deriva_esquema_y_rechaza_campo_ajeno(box, capsys):
    """T2: --unmeasured usa el FIELD=REASON del productor, no una tabla local."""
    orders = box.coord_orders()
    orders[-1] += " --unmeasured not_a_field=reason"
    coord = box.latido("tick-bad-unmeasured.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "valor no aceptado por tick_trace.py: --unmeasured=not_a_field=reason" in out


def test_tick_trace_unmeasured_field_real_es_aceptado(box, capsys):
    """T2: un FIELD real del productor mantiene la orden ejecutable."""
    orders = box.coord_orders()
    orders[-1] += " --unmeasured guard_rc=not_measured"
    coord = box.latido("tick-good-unmeasured.md", orders)
    sup = box.latido("s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 0, out


def test_go_productor_nuevo_en_latido_es_valido(box, capsys):
    """E7 positivo: una solicitud GO usa el subcomando productor y pasa el wiring."""
    orders = box.coord_orders()
    orders.insert(
        2,
        f'{box.py} {box.s("comms_alert.py")} --go-id go-e7 --what "Escribe GO 1" '
        f"--flight-dir {box.root / 'flight'} --owner CO-28 --ops-dir {box.ops}",
    )
    coord = box.latido("go-good.md", orders)
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0
    assert "latido-check: OK" in out


def test_flight_heartbeat_extra_no_rompe_latido_normal(box, capsys):
    """Control positivo: heartbeat adicional no sustituye la orden detectora normal."""
    orders = box.coord_orders()
    orders.insert(
        3,
        f"{box.py} {box.s('flight_stall_check.py')} --heartbeat-check "
        f"--ops-dir {box.ops} --flight-dir {box.flight}",
    )
    coord = box.latido("heartbeat-extra.md", orders)
    sup = box.latido("heartbeat-extra-s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 0, out
    assert "latido-check: OK" in out


def test_flight_heartbeat_no_sustituye_orden_normal(box, capsys):
    """Control negativo: solo heartbeat no cubre la orden normal de la coordinadora."""
    orders = box.coord_orders()
    orders[2] = (
        f"{box.py} {box.s('flight_stall_check.py')} --heartbeat-check "
        f"--ops-dir {box.ops} --flight-dir {box.flight}"
    )
    coord = box.latido("heartbeat-only.md", orders)
    sup = box.latido("heartbeat-only-s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 1
    assert "falta una orden VALIDA de flight_stall_check.py (orden normal)" in out


def test_go_receta_manual_en_latido_es_violation_nombrada(box, capsys):
    """E7 negativo: la receta manual de GO debe fallar con causa reparable."""
    orders = box.coord_orders()
    orders.insert(
        2,
        f"{box.py} {box.s('comms_alert.py')} --event go-e7 --level URGENTE "
        '--what "Escribe GO 1 y anade ABIERTA BLOQUEA a mano"',
    )
    coord = box.latido("go-manual.md", orders)
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1
    assert "GO" in out and ("manual" in out.lower() or "--go-id" in out)


def test_d14_go_id_en_what_no_convierte_evento_legitimo_en_receta(box, capsys):
    orders = box.coord_orders()
    orders.insert(
        2,
        f"{box.py} {box.s('comms_alert.py')} --event clave --level URGENTE "
        '--what "go-123 listo"',
    )
    coord = box.latido("go-what.md", orders)
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0
    assert "receta GO manual" not in out


def test_d14_clave_event_go_si_es_receta_manual(box, capsys):
    orders = box.coord_orders()
    orders.insert(
        2,
        f"{box.py} {box.s('comms_alert.py')} --event go-x --level URGENTE "
        '--what "solicita decision"',
    )
    coord = box.latido("go-event.md", orders)
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1
    assert "receta GO manual" in out


def test_d9_latido_real_go_manual_exige_productor_valido(box, capsys):
    """D9a: el parrafo real marca receta manual y ausencia de orden GO valida."""
    coord = box.latido("go-real.md", box.coord_orders(), LATIDO_REAL_GO_MANUAL)
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1
    assert "receta GO manual" in out
    assert "falta una orden GO valida" in out


@pytest.mark.parametrize(
    ("missing", "order"),
    [
        ("owner", '--go-id go-missing --what "Escribe GO" --flight-dir F'),
        ("flight-dir", '--go-id go-missing --what "Escribe GO" --owner CO-28'),
        ("what", "--go-id go-missing --flight-dir F --owner CO-28"),
    ],
)
def test_d9_orden_go_incompleta_no_cubre_seccion(box, capsys, missing, order):
    """D9b: cada omision deja la orden invalida y nombra la barrera GO."""
    orders = box.coord_orders()
    orders.insert(2, f"{box.py} {box.s('comms_alert.py')} {order}")
    coord = box.latido(f"go-missing-{missing}.md", orders, "GO AL USUARIO")
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1
    assert "falta una orden GO valida" in out


def test_d9_seccion_go_sin_go_id_se_marca_y_latido_normal_no(box, capsys):
    """D9c: la seccion GO exige productor; un latido sin seccion no hereda el hallazgo."""
    coord = box.latido("go-sin-orden.md", box.coord_orders(), "ABIERTA BLOQUEA")
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1
    assert "falta una orden GO valida" in out

    coord = box.latido("sin-go.md", box.coord_orders(), "progreso normal")
    rc, out = run(box.argv(coord, sup), capsys)
    assert "falta una orden GO valida" not in out
    assert "receta GO manual" not in out


def test_d20_go_dry_run_no_cubre_seccion(box, capsys):
    orders = box.coord_orders()
    orders.insert(
        2,
        f'{box.py} {box.s("comms_alert.py")} --go-id go-dry --what "Escribe GO" '
        f"--flight-dir {box.root / 'flight'} --owner CO-28 --dry-run",
    )
    coord = box.latido("go-dry-run.md", orders, "GO AL USUARIO")
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1
    assert "falta una orden GO valida" in out


def test_d9_go_id_en_prosa_manual_tambien_es_violation(box, capsys):
    """D9d: go-<id> en prosa, junto a la receta manual, tambien muerde."""
    prose = "GO AL USUARIO: usa --event go-<id> y escribe ABIERTA BLOQUEA a mano."
    coord = box.latido("go-prosa.md", box.coord_orders(), prose)
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1
    assert "receta GO manual" in out
    assert "falta una orden GO valida" in out


@windows_only
def test_fila_131_orden_obligatoria_faltante_es_rc_1_y_se_nombra(box, capsys):
    """Fila 131 (N97: faltante devuelve 2): quitar `--self-check` de la coordinadora -> rc 1 que
    NOMBRA lo que falta (no rc 2)."""
    orders = [o for o in box.coord_orders() if "--self-check" not in o]
    coord = box.latido("c.md", orders)
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1
    assert "flight_stall_check.py --self-check" in out


def test_fila_132_sin_roster_es_rc_3_aunque_los_latidos_esten_mal(box, capsys):
    """Fila 132 (N98: sin latidos devuelve 3): sin roster -> rc 3 N/A; con roster y SIN latidos
    -> rc 1 (una lista parcial nunca es N/A)."""
    rc, out = run(box.argv(roster=False), capsys)
    assert rc == 3
    assert "N/A" in out
    rc, out = run(box.argv(), capsys)  # roster presente, ningun latido
    assert rc == 1
    assert "sin latido" in out


@pytest.mark.parametrize(
    ("roster_body", "expected"),
    [
        ('{"active_roles":{"orquestador":{"session_code":"CO-31"}}}', "CO-31"),
        ('{"active_roles":{"orquestador":{}}}', None),
        ('{"active_roles":{"orquestador":{"session_code":""}}}', None),
        ('{"active_roles":{"orquestador":{"session_code":null}}}', None),
        ('{"active_roles":{"orquestador":{"session_code":"co-31"}}}', None),
        ('{"active_roles":{"orquestador":{"session_code":"CO31"}}}', None),
        ('{"active_roles":{"orquestador":{"session_code":"123"}}}', None),
        ("{", None),
    ],
)
def test_caja_c_7b_ambos_consumidores_usan_el_mismo_roster_real(
    box, monkeypatch, roster_body, expected
):
    """7b: ambos consumidores resuelven None ante cualquier roster no canónico."""
    roster = box.motor / "flight_roster.json"
    roster.write_text(roster_body, encoding="utf-8")
    captured = {}
    monkeypatch.setattr(
        chk,
        "emit_alert",
        lambda *args, **kwargs: captured.update(kwargs) or True,
    )
    args = argparse.Namespace(
        roster_path=str(roster),
        ops_dir=str(box.ops),
        flight_dir=str(box.motor),
        dry_run=True,
    )
    assert chk._alert_and_report(1, ["diagnostico", "hallazgo"], args, {}) == 1

    stall_path = _ROOT / "scripts" / "flight" / "flight_stall_check.py"
    spec = importlib.util.spec_from_file_location(
        "flight_stall_check_caja_c_7b", stall_path
    )
    stall = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stall)
    cfg, causes, fatal = stall._resolve_paths(
        types.SimpleNamespace(
            flight_dir=str(box.motor),
            motor_wt=str(box.motor),
            quota_file=None,
        ),
        box.ops,
    )
    assert causes == [] and fatal is None
    assert captured["session_code"] == cfg.session_code == expected


# ================================================================== FILA 130 -- ILEGIBLE rc 2
# El OTRO latido siempre es correcto; se verifica rc 2 y que la salida nombra la causa.


def test_fila_130_latido_ausente_rc_2(box, capsys):
    """Fila 130 (mutacion 130.1): latido de coordinadora ausente (solo supervisora buena) -> rc 2
    con 'latido no se puede leer'."""
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord="c_missing.md", sup=sup), capsys)
    assert rc == 2, out
    assert "latido no se puede leer" in out


def test_fila_130_latido_es_directorio_rc_2(box, capsys):
    """Fila 130 (mutacion 130.2): latido que es un directorio -> rc 2 con 'es un directorio'."""
    bad_dir = box.root / "bad_dir"
    bad_dir.mkdir()
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord=bad_dir, sup=sup), capsys)
    assert rc == 2, out
    assert "es un directorio" in out


def test_fila_130_no_utf8_rc_2(box, capsys):
    """Fila 130 (mutacion 130.3): no UTF-8 (bytes invalidos) -> rc 2 con 'no es UTF-8'."""
    bad = box.root / "bad_utf8.md"
    bad.write_bytes(b"\xff\xfe\x00\x00")
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord=bad, sup=sup), capsys)
    assert rc == 2, out
    assert "no es UTF-8" in out


def test_fila_130_mayor_2mib_rc_2(box, capsys):
    """Fila 130 (mutacion 130.4): latido mayor de 2 MiB -> rc 2 con 'mas de'."""
    big = box.root / "big.md"
    big.write_bytes(b"x" * (chk.MAX_LATIDO_BYTES + 1))
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord=big, sup=sup), capsys)
    assert rc == 2, out
    assert "mas de" in out


def test_fila_130_symlink_roto_rc_2(box, capsys):
    """Fila 130 (mutacion 130.5): symlink roto -> rc 2 con 'no se puede leer'."""
    link = box.root / "broken_link.md"
    target = box.root / "no_existe_aqui.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("no se pueden crear symlinks")
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord=link, sup=sup), capsys)
    assert rc == 2, out
    assert "no se puede leer" in out


def test_fila_130_roster_ausente_rc_2(box, capsys):
    """Fila 130 (mutacion 130.6): roster declarado ausente -> rc 2 con 'roster'."""
    coord, sup = box.good()
    rc, out = run(
        box.argv(coord, sup, extra=["--roster-path", "/no/existe.json"]), capsys
    )
    assert rc == 2, out
    assert "roster" in out


def test_fila_130_roster_no_json_rc_2(box, capsys):
    """Fila 130 (mutacion 130.7): roster no JSON -> rc 2 con 'roster'."""
    bad_r = box.root / "bad_roster.json"
    bad_r.write_text("esto no es json", encoding="utf-8")
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup, extra=["--roster-path", str(bad_r)]), capsys)
    assert rc == 2, out
    assert "roster" in out


def test_fila_130_roster_no_objeto_rc_2(box, capsys):
    """Fila 130 (mutacion 130.8): roster es JSON lista (no objeto) -> rc 2 con 'objeto JSON'."""
    arr_r = box.root / "arr_roster.json"
    arr_r.write_text("[]", encoding="utf-8")
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup, extra=["--roster-path", str(arr_r)]), capsys)
    assert rc == 2, out
    assert "objeto JSON" in out


def test_fila_130_git_exe_inexistente_rc_2(box, capsys):
    """Fila 130 (mutacion 130.9): --git-exe a ruta inexistente -> rc 2 con 'git'."""
    coord, sup = box.good()
    rc, out = run(
        box.argv(coord, sup, extra=["--git-exe", "/no/existe/git.exe"]), capsys
    )
    assert rc == 2, out
    assert "git" in out


# ================================================================== FILA 131 -- FALTANTE rc 1
# Partiendo siempre de latidos buenos, se cambia UNA cosa.


def test_fila_131_latido_vacio_rc_1(box, capsys):
    """Fila 131 (mutacion 131.1): latido vacio (0 bytes) -> rc 1 con 'sin latido'."""
    empty = box.root / "empty.md"
    empty.write_text("", encoding="utf-8")
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord=empty, sup=sup), capsys)
    assert rc == 1, out
    assert "coordinadora: falta una orden VALIDA" in out


@windows_only
def test_fila_131_un_solo_rol_rc_1(box, capsys):
    """Fila 131 (mutacion 131.2): solo un rol dado -> rc 1 con 'sin latido' del otro."""
    coord, _ = box.good()
    rc, out = run(box.argv(coord=coord), capsys)
    assert rc == 1, out
    assert "sin latido" in out


@pytest.mark.parametrize(
    "order_name,order_idx",
    [
        ("comms_alert.py --scan", 0),
        ("comms_alert.py --event", 1),
        ("flight_stall_check.py --ops-dir", 2),
        ("flight_stall_check.py --self-check", 3),
        ("quota_tick.py >", 4),
        ("check_latido_alert_wiring.py --alert", 5),
    ],
)
def test_fila_131_ord_coord_retirada_rc_1(box, capsys, order_name, order_idx):
    """Fila 131 (mutacion 131.N): cada orden de la coordinadora retirada -> rc 1 con nombre.
    Fila {131} (mutacion 131.{order_idx + 10})."""
    all_orders = box.coord_orders()
    removed = all_orders[order_idx]
    orders = [o for o in all_orders if o != removed]
    coord = box.latido("c.md", orders)
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "falta una orden VALIDA" in out


@windows_only
def test_fila_131_bom_inicio_rc_0(box, capsys):
    """Fila 131 (mutacion 131.16): BOM al inicio del latido bueno -> rc 0."""
    coord, sup = box.good()
    c_text = coord.read_bytes()
    c_bom = box.root / "c_bom.md"
    c_bom.write_bytes(b"\xef\xbb\xbf" + c_text)
    # Use absolute paths in the argv call
    rc, out = run(box.argv(coord=str(c_bom), sup=str(sup)), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


@windows_only
def test_fila_131_sin_salto_final_rc_0(box, capsys):
    """Fila 131 (mutacion 131.17): latido bueno sin salto de linea final -> rc 0."""
    coord, sup = box.good()
    c_text = coord.read_text(encoding="utf-8").rstrip("\n")
    c_noeol = box.root / "c_noeol.md"
    c_noeol.write_text(c_text, encoding="utf-8")
    rc, out = run(box.argv(coord=str(c_noeol), sup=str(sup)), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


# ================================================================== FILA 132 -- ENTORNO (monkeypatch.setenv)


def test_fila_132_flight_roster_path(box, capsys, monkeypatch):
    """Fila 132 (mutacion 132.1): FLIGHT_ROSTER_PATH por entorno (latidos por CLI) -> rc 0."""
    coord, sup = box.good()
    monkeypatch.setenv(chk.ROSTER_ENV, str(box.roster))
    rc, out = run(box.argv(coord, sup, roster=False), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


def test_fila_132_latido_mal_formado_env_rc_3(box, capsys, monkeypatch):
    """Fila 132 (mutacion 132.2): sin roster + `x` en FLIGHT_LATIDO_FILES -> rc 3."""
    monkeypatch.setenv(chk.LATIDO_ENV, "x")
    rc, out = run(box.argv(roster=False), capsys)
    assert rc == 3, out
    assert "N/A" in out


def test_fila_132_flight_latido_files_env_rc_0(box, capsys, monkeypatch):
    """Fila 132 (mutacion 132.3): FLIGHT_LATIDO_FILES por entorno -> rc 0."""
    coord, sup = box.good()
    monkeypatch.setenv(chk.ROSTER_ENV, str(box.roster))
    monkeypatch.setenv(chk.LATIDO_ENV, f"coordinadora={coord!s};supervisora={sup!s}")
    rc, out = run(box.argv(roster=False), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


def test_fila_132_cli_gana_al_entorno(box, capsys, monkeypatch):
    """Fila 132 (mutacion 132.4): entorno con ruta mala + CLI buena -> rc 0."""
    coord, sup = box.good()
    monkeypatch.setenv(chk.ROSTER_ENV, str(box.roster))
    monkeypatch.setenv(chk.LATIDO_ENV, "coordinadora=/no/existe.md")
    rc, out = run(box.argv(coord, sup, roster=False), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


# ================================================================== FILA 133 -- RUTAS RELATIVAS


def test_fila_133_latido_rel_dentro_motor_rc_0(box, capsys):
    """Fila 133 (mutacion 133.1): latido bueno dentro de motor/ como lat/c.md, pasado relativo
    -> rc 0."""
    lat_dir = box.motor / "lat"
    lat_dir.mkdir()
    c_path = lat_dir / "c.md"
    s_path = lat_dir / "s.md"
    c_orders = box.coord_orders()
    old_s = box.s("comms_alert.py")
    for i, o in enumerate(c_orders):
        if old_s in o:
            c_orders[i] = o.replace(old_s, str(box.flight / "comms_alert.py"))
    c_path.write_text(
        "\n".join(f"- `{o}`" for o in c_orders),
        encoding="utf-8",
    )
    s_orders = box.sup_orders()
    s_path.write_text(
        "\n".join(f"- `{o}`" for o in s_orders),
        encoding="utf-8",
    )
    rc, out = run(box.argv("lat/c.md", "lat/s.md"), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


def test_fila_133_cambio_cwd_mal_rc_0(box, capsys, monkeypatch):
    """Fila 133 (mutacion 133.2): monkeypatch.chdir a carpeta con lat/malo -> rc 0 (motor-root
    define las bases, no el cwd)."""
    other = box.root / "other_dir"
    other.mkdir()
    bad_lat = other / "malo.md"
    bad_lat.write_text("- `python /no/existe.py --scan`\n", encoding="utf-8")
    coord, sup = box.good()
    monkeypatch.chdir(other)
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


# ================================================================== FILA 134 -- GRAMATICA
# Positivos y negativos de sintaxis de interprete/script.


def test_fila_134_python_absoluto_rc_0(box, capsys):
    """Fila 134 (mutacion 134.1): python con ruta absoluta -> rc 0."""
    c_orders = box.coord_orders()
    c_path = box.latido("c.md", c_orders)
    s_orders = box.sup_orders()
    s_path = box.latido("s.md", s_orders)
    rc, out = run(box.argv(c_path, s_path), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


@pytest.mark.parametrize("placement", ["argumento", "directorio", "nombre"])
@pytest.mark.parametrize(
    "script",
    ["comms_alert.py", "flight_stall_check.py", "check_latido_alert_wiring.py"],
)
def test_fila_134_quota_en_texto_de_script_no_permite_redireccion(
    box, capsys, script, placement
):
    """BA03: ``quota_tick.py`` en un argumento no convierte otro script en quota."""
    if placement == "argumento":
        suffix = "--what quota_tick.py"
    elif placement == "directorio":
        suffix = f"--ops-dir {box.root / 'quota_tick.py' / 'ops'}"
    else:
        suffix = "--event nombre-quota_tick.py"
    order = f"{box.py} {box.s(script)} {suffix} > {box.root / 'out.txt'}"
    coord = box.latido("c.md", [order])
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "operador de shell no permitido" in out


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("--what {script}", "opcion de Python no permitida: --what"),
        ("--ops-dir {script}", "opcion de Python no permitida: --ops-dir"),
        ("-W {script}", "valor de opcion Python no puede ser un script"),
        ("-X {script}", "valor de opcion Python no puede ser un script"),
    ],
)
@pytest.mark.parametrize("style", ["normal", "mayusculas_y_barras_mixtas"])
def test_r2_valor_de_opcion_python_no_es_el_script_ejecutable(
    box, capsys, prefix, expected, style
):
    """R2 MAJOR-1: un script en valor de opcion de Python nunca da un falso PASS."""
    script = box.s("comms_alert.py")
    if style == "mayusculas_y_barras_mixtas":
        script = script.upper().replace("\\", "/")
    order = f"{box.py} {prefix.format(script=script)} --scan"
    coord = box.latido("c-r2.md", [order])
    sup = box.latido("s-r2.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert expected in out


@pytest.mark.parametrize("option", ["-W", "-X"])
def test_r2_script_repetido_como_valor_de_python_sigue_siendo_violacion(
    box, capsys, option
):
    """R2 censo: ni repetir el script convierte su primer uso como valor en ejecutable."""
    script = box.s("comms_alert.py")
    order = f"{box.py} {option} {script} {script} --scan"
    coord = box.latido("c-r2-repeat.md", [order])
    sup = box.latido("s-r2-repeat.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "valor de opcion Python no puede ser un script" in out


@pytest.mark.parametrize("option", ["-W", "-X"])
def test_r5_valor_de_opcion_python_con_aspecto_de_flag_se_rechaza(box, capsys, option):
    """BA03 H2: un valor pre-script que empieza por '-' no puede ocultar otra opcion."""
    order = f"{box.py} {option} -alert {box.s('comms_alert.py')} --scan"
    coord = box.latido("r5-python-value.md", [order, *box.coord_orders()[1:]])
    sup = box.latido("r5-python-value-s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "parece otra opcion Python" in out


def test_r2_valor_title_de_powershell_no_es_el_script_ejecutable(box, capsys):
    """R2 censo: el valor de -Title no puede satisfacer el inventario de PowerShell."""
    script = box.s("notify_user.ps1")
    order = f'{box.ps} -Title {script} -File {script} -Message "x"'
    coord = box.latido("c-r2-ps.md", box.coord_orders())
    sup = box.latido("s-r2-ps.md", [order, box.sup_orders()[1]])
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "opcion de PowerShell no permitida: -Title" in out


def test_fila_134_una_orden_no_cubre_dos_items_del_inventario(box, capsys):
    """MINOR-2: ``--scan --event`` requiere dos ordenes distintas del inventario."""
    orders = box.coord_orders()
    orders[0] += " --event clave --level URGENTE --what x"
    orders.pop(1)
    coord = box.latido("c.md", orders)
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "falta una orden VALIDA de comms_alert.py --event" in out


def test_fila_134_slash_abajo_rc_0(box, capsys):
    """Fila 134 (mutacion 134.2): rutas con `/` -> rc 0."""
    py = box.py
    flight_str = str(box.flight).replace(os.sep, "/")
    orders = [
        f"{py} {flight_str}/comms_alert.py --scan --ops-dir {box.ops}",
        f"{py} {flight_str}/comms_alert.py --event clave --level URGENTE --what x",
        f"{py} {flight_str}/flight_stall_check.py --ops-dir {box.ops}",
        f"{py} {flight_str}/flight_stall_check.py --self-check",
        f"{py} {flight_str}/quota_tick.py > {box.root / 'quota.txt'}",
        f"{py} {flight_str}/check_latido_alert_wiring.py --alert",
        box.trace_order(),
    ]
    # Fix powershell path in sup orders
    sysroot = os.environ.get("SYSTEMROOT", "")
    ps_path = str(
        Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    sup_orders = [
        f"{ps_path} -NoProfile -NonInteractive -File {flight_str}/notify_user.ps1 -Title t -Message m",
        f"{py} {flight_str}/quota_tick.py",
    ]
    c_path = box.latido("c.md", orders)
    s_path = box.latido("s.md", sup_orders)
    rc, out = run(box.argv(c_path, s_path), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


def test_fila_134_comillas_dobles_rc_0(box, capsys):
    """Fila 134 (mutacion 134.3): comillas dobles alrededor de ruta del script -> rc 0."""
    py = box.py
    s_ca = f'"{box.s("comms_alert.py")}"'
    orders = [
        f"{py} {s_ca} --scan --ops-dir {box.ops}",
        f'{py} {s_ca} --event clave --level URGENTE --what "x"',
        f"{py} {s_ca.replace('comms_alert.py', 'flight_stall_check.py')} --ops-dir {box.ops}",
        f"{py} {s_ca.replace('comms_alert.py', 'flight_stall_check.py')} --self-check",
        f"{py} {s_ca.replace('comms_alert.py', 'quota_tick.py')} > {box.root / 'quota.txt'}",
        f"{py} {s_ca.replace('comms_alert.py', 'check_latido_alert_wiring.py')} --alert",
        box.trace_order(),
    ]
    ps = box.ps
    sup_orders = [
        f'{ps} -NoProfile -NonInteractive -File "{box.s("notify_user.ps1")}" -Title t -Message m',
        f"{py} {s_ca.replace('comms_alert.py', 'quota_tick.py')}",
    ]
    c_path = box.latido("c.md", orders)
    s_path = box.latido("s.md", sup_orders)
    rc, out = run(box.argv(c_path, s_path), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


def test_fila_134_bloque_backticks_rc_0(box, capsys):
    """Fila 134 (mutacion 134.4): ordenes dentro de un bloque ``` -> rc 0."""
    body_lines = [
        "Latido sintetico.",
        "```",
    ]
    body_lines.extend(box.coord_orders())
    body_lines.append("```")
    body_lines.extend(f"- `{o}`" for o in box.sup_orders())
    c_path = box.latido("c.md", [])
    c_path.write_text("\n".join(body_lines) + "\n", encoding="utf-8")
    s_path = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c_path, s_path), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


@windows_only
def test_fila_134_python_desnudo_rc_1(box, capsys):
    """Fila 134 (mutacion 134.5): `python` desnudo (sin script) -> rc 1."""
    orders = box.coord_orders()
    orders[0] = "python"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "falta una orden VALIDA de comms_alert.py --scan" in out


@windows_only
def test_fila_134_cmd_c_rc_1(box, capsys):
    """Fila 134 (mutacion 134.6): `cmd /c <python> <script>` -> rc 1."""
    orders = box.coord_orders()
    orders[0] = f"cmd /c {box.py} {box.s('comms_alert.py')} --scan --ops-dir {box.ops}"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "falta una orden VALIDA de comms_alert.py --scan" in out


@windows_only
def test_fila_134_python_c_rc_1(box, capsys):
    """Fila 134 (mutacion 134.7): `<python> -c "..."` -> rc 1."""
    orders = box.coord_orders()
    orders[0] = f'{box.py} -c "import comms_alert"'
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "falta una orden VALIDA de comms_alert.py --scan" in out


@windows_only
def test_fila_134_python_m_rc_1(box, capsys):
    """Fila 134 (mutacion 134.8): `<python> -m x` -> rc 1."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} -m comms_alert"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "falta una orden VALIDA de comms_alert.py --scan" in out


def test_fila_134_script_sin_interprete_rc_1(box, capsys):
    """Fila 134 (mutacion 134.9): solo el script sin interprete -> rc 1."""
    orders = box.coord_orders()
    orders[0] = box.s("comms_alert.py") + " --scan"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "falta una orden VALIDA de comms_alert.py --scan" in out


@windows_only
def test_fila_134_interprete_unc_rc_1(box, capsys):
    """Fila 134 (mutacion 134.10): interprete UNC -> rc 1 con 'red (UNC)'."""
    orders = box.coord_orders()
    orders[0] = f"\\\\\\\\server\\share\\python.exe {box.s('comms_alert.py')} --scan"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "falta una orden VALIDA de comms_alert.py --scan" in out


def test_fila_134_script_relativo_rc_1(box, capsys):
    """Fila 134 (mutacion 134.11): script con ruta relativa -> rc 1."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} scripts/flight/comms_alert.py --scan"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "ruta relativa" in out


@windows_only
def test_fila_134_pipe_rc_1(box, capsys):
    """Fila 134 (mutacion 134.12): operador `|` -> rc 1 con 'operador de shell'."""
    orders = box.coord_orders()
    orders[0] += " | cat"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


@windows_only
def test_fila_134_ampamp_rc_1(box, capsys):
    """Fila 134 (mutacion 134.13): operador `&&` -> rc 1 con 'operador de shell'."""
    orders = box.coord_orders()
    orders[0] += " && echo ok"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


@windows_only
def test_fila_134_semicolon_rc_1(box, capsys):
    """Fila 134 (mutacion 134.14): operador `;` -> rc 1 con 'operador de shell'."""
    orders = box.coord_orders()
    orders[0] += "; echo ok"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


@windows_only
def test_fila_134_comilla_sin_cerrar_rc_1(box, capsys):
    """Fila 134 (mutacion 134.15): comilla sin cerrar -> rc 1."""
    bad = box.root / "bad_quote.md"
    bad.write_text('- `python C:\\x\\comms_alert.py --scan "x\n', encoding="utf-8")
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord=bad, sup=sup), capsys)
    assert rc == 1, out
    assert "VIOLACION" in out


# ================================================================== FILA 135 -- PROSA


def test_fila_135_prosa_solamente_rc_1(box, capsys):
    """Fila 135 (mutacion 135.1): ordenes SOLO en prosa (sin backticks) -> rc 1."""
    bad = box.root / "prosa.md"
    bad.write_text("Ejecutar python C:\\x\\comms_alert.py --scan\n", encoding="utf-8")
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord=bad, sup=sup), capsys)
    assert rc == 1, out
    assert "VIOLACION" in out


def test_fila_135_prosa_con_backticks_rc_0(box, capsys):
    """Fila 135 (mutacion 135.2): latido bueno con prosa que cita comms_alert.py sin backticks
    -> rc 0 (solo se cuentan las ordenes con backticks)."""
    coord, sup = box.good()
    coord.write_text(
        coord.read_text() + "Nota: ver comms_alert.py para detalles.\n",
        encoding="utf-8",
    )
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


def test_fila_135_bloque_sin_cerrar_rc_1(box, capsys):
    """Fila 135 (mutacion 135.3): bloque ``` sin cerrar -> rc 1 con 'sin cerrar'."""
    bad = box.root / "unclosed.md"
    bad.write_text("```\npython C:\\x\\comms_alert.py --scan\n", encoding="utf-8")
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(coord=bad, sup=sup), capsys)
    assert rc == 1, out
    assert "sin cerrar" in out


# ================================================================== FILA 136 -- ENLACES HACIA FUERA


def test_fila_136_symlink_fuera_skip(box, capsys):
    """Fila 136 (mutacion 136.1): symlink a fichero FUERA del motor (sin commitear) -> rc 1
    'fuera de'. Skip si no se puede crear symlink."""
    try:
        box.root.joinpath("outside.txt").write_text("# outside\n", encoding="utf-8")
        link = box.flight / "comms_alert.py"
        link.unlink()
        link.symlink_to(box.root / "outside.txt")
    except OSError:
        pytest.skip("no se pueden crear symlinks")
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "fuera de" in out.lower()


@windows_only
def test_fila_136_junction_fuera_rc_1(box, capsys):
    """Fila 136 (mutacion 136.2): junction a carpeta externa con comms_alert.py -> rc 1 'fuera'.
    Skip si no se puede crear."""
    try:
        ext_dir = box.root / "external_dir"
        ext_dir.mkdir()
        (ext_dir / "comms_alert.py").write_text("# external\n", encoding="utf-8")
        link = box.motor / "scripts" / "flight2"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(ext_dir)],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no se puede crear junction")
    # Build latido orders that reference the junctioned path, not the normal one
    py = box.py
    ext_ca = str(link / "comms_alert.py")
    c_orders = [
        f"{py} {ext_ca} --scan --ops-dir {box.ops}",
        f"{py} {ext_ca} --event clave --level URGENTE --what x",
        f"{py} {box.s('flight_stall_check.py')} --ops-dir {box.ops}",
        f"{py} {box.s('flight_stall_check.py')} --self-check",
        f"{py} {box.s('quota_tick.py')} > {box.root / 'quota.txt'}",
        f"{py} {box.s('check_latido_alert_wiring.py')} --alert",
        box.trace_order(),
    ]
    sysroot = os.environ.get("SYSTEMROOT", "")
    ps = str(
        Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    sup_orders = [
        f"{ps} -NoProfile -NonInteractive -File {box.s('notify_user.ps1')} -Title t -Message m",
        f"{py} {box.s('quota_tick.py')}",
    ]
    c = box.latido("c.md", c_orders)
    s = box.latido("s.md", sup_orders)
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "fuera de" in out.lower()

    # Control positivo: un junction que apunta DENTRO del flight es valido.
    inside = box.motor / "scripts" / "flight3"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(inside), str(box.flight)],
        check=True,
        capture_output=True,
    )
    c_orders[0] = f"{py} {inside / 'comms_alert.py'} --scan --ops-dir {box.ops}"
    c_orders[1] = (
        f"{py} {inside / 'comms_alert.py'} --event clave --level URGENTE --what x"
    )
    c = box.latido("c-in.md", c_orders)
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 0, out


def test_r5_soundness_metadata_se_deriva_de_los_parsers_reales():
    """R5 BA03: soundness es check-acepta => parser-acepta, no igualdad inversa."""
    for script in (
        "comms_alert.py",
        "flight_stall_check.py",
        "quota_tick.py",
        "tick_trace.py",
        "check_latido_alert_wiring.py",
    ):
        actual = chk._python_parser_actions(
            _ROOT / "scripts" / "flight" / script,
            own=script == "check_latido_alert_wiring.py",
        )
        assert {name: spec[0] for name, spec in actual.items()} == chk._SCRIPT_OPTIONS[
            script
        ], script
        assert actual == chk._SCRIPT_OPTION_META[script], script
    ps_meta = chk._powershell_parser_actions(
        _ROOT / "scripts" / "flight" / "notify_user.ps1"
    )
    assert {name: spec[0] for name, spec in ps_meta.items()} == chk._SCRIPT_OPTIONS[
        "notify_user.ps1"
    ]
    assert ps_meta["-Title"][1] and ps_meta["-Message"][1]
    assert all(not spec[2] for spec in ps_meta.values())


def test_r5_rechazos_de_politica_estan_declarados():
    """R5: parser-acepta/check-rechaza solo vale para excepciones de politica explicitas."""
    assert chk._POLICY_REJECTIONS == {
        "--dry-run": "silencia avisos y deja B2 sin cubrir",
        "-c": "ejecuta codigo inline en vez de un script del inventario",
        "-m": "ejecuta un modulo en vez de un script del inventario",
        "shell-operator": "los latidos no delegan operadores al shell",
        "powershell-denylist": "la denylist evita suprimir o desviar avisos",
    }


@pytest.mark.parametrize(
    "spec",
    [
        chk._OptionSpec(True, False, False, None, ("x", "y"), None, None),
        chk._OptionSpec(True, False, False, None, None, "int", None),
        chk._OptionSpec(True, False, False, None, None, None, 0),
        chk._OptionSpec(True, False, False, "+", None, None, None),
    ],
)
def test_r5_metadata_argparse_no_modelada_falla_cerrado(spec):
    """R5 BA03: choices/type/mutex/nargs no modelados nunca pueden dar PASS."""
    checker = chk._Checker(Path.cwd(), None, None, {})
    # Inyectamos el contrato del productor en vez de simular una constante manual.
    original = chk._SCRIPT_OPTION_META["comms_alert.py"]
    try:
        chk._SCRIPT_OPTION_META["comms_alert.py"] = {"--x": spec}
        order = chk._Order(1, "orden")
        checker._check_script_arguments(order, ["--x", "valor"], "comms_alert.py")
        assert any("metadata no modelada" in text for _, text in order.problems)
    finally:
        chk._SCRIPT_OPTION_META["comms_alert.py"] = original


def test_r5_metadata_powershell_validatex_falla_cerrado():
    """R5 BA03: ValidateX/atributos PS no derivados no pueden dar PASS."""
    checker = chk._Checker(Path.cwd(), None, None, {})
    original = chk._SCRIPT_OPTION_META["notify_user.ps1"]
    try:
        chk._SCRIPT_OPTION_META["notify_user.ps1"] = {
            "-Title": chk._OptionSpec(
                True, True, False, None, None, None, None, ("ValidateSet",)
            ),
            "-Message": chk._OptionSpec(True, True, False),
        }
        order = chk._Order(1, "orden")
        checker._check_script_arguments(
            order, ["-Title", "a", "-Message", "b"], "notify_user.ps1"
        )
        assert any("metadata no modelada" in text for _, text in order.problems)
    finally:
        chk._SCRIPT_OPTION_META["notify_user.ps1"] = original


@pytest.mark.parametrize(
    "mandatory", ["Mandatory", "Mandatory=$true", "Mandatory:$true", "Mandatory=$false"]
)
@windows_only
def test_r7_powershell_mandatory_real_se_deriva_y_concuerda_con_runtime(
    tmp_path, mandatory
):
    """R7 M1: las cuatro sintaxis reales de Mandatory no se pierden en el AST."""
    script = tmp_path / "bare.ps1"
    script.write_text(
        f"param([Parameter({mandatory})][string]$Title, "
        f"[Parameter({mandatory})][string]$Message)\nexit 0\n",
        encoding="utf-8",
    )
    expected = mandatory != "Mandatory=$false"
    if mandatory in {"Mandatory", "Mandatory:$true"}:
        try:
            meta = chk._powershell_parser_actions(script)
        except RuntimeError:
            meta = {}
        if meta:
            assert meta["-Title"].required or "mandatory" in meta["-Title"].unsupported
            assert (
                meta["-Message"].required or "mandatory" in meta["-Message"].unsupported
            )
    else:
        meta = chk._powershell_parser_actions(script)
        assert meta["-Title"].required is expected
        assert meta["-Message"].required is expected
    ps = (
        Path(os.environ["SYSTEMROOT"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    done = subprocess.run(
        [str(ps), "-NoProfile", "-NonInteractive", "-File", str(script), "-Title", "a"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == (1 if expected else 0), done.stderr


@windows_only
def test_r7_fuzz_mandatory_soundness_contra_powershell_real(tmp_path):
    """R7 BA254: ninguna forma que el check ve opcional puede ser obligatoria en PS."""
    forms = [
        "Mandatory",
        "Mandatory=$true",
        "Mandatory=$false",
        "Mandatory=$null",
        "Mandatory=0",
        "Mandatory=1",
        'Mandatory="false"',
        'Mandatory="true"',
        "Mandatory='false'",
        "Mandatory='true'",
        "Mandatory=$(1)",
        "Mandatory=$x",
        "Mandatory:$true",
    ]
    ps = (
        Path(os.environ["SYSTEMROOT"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    for index, form in enumerate(forms):
        script = tmp_path / f"fuzz_{index}.ps1"
        script.write_text(
            f"param([Parameter({form})][string]$Title, "
            f"[Parameter({form})][string]$Message)\nexit 0\n",
            encoding="utf-8",
        )
        try:
            meta = chk._powershell_parser_actions(script)
            check_optional = (
                not meta["-Message"].required and not meta["-Message"].unsupported
            )
        except RuntimeError:
            check_optional = False
        real = subprocess.run(
            [
                str(ps),
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(script),
                "-Title",
                "a",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        real_optional = real.returncode == 0
        assert not check_optional or real_optional, (
            form,
            real.returncode,
            real.stderr,
        )


def test_r7_positional_argparse_falla_cerrado():
    """R7 M2: una accion argparse posicional no puede desaparecer del contrato."""
    parser = argparse.ArgumentParser()
    parser.add_argument("destino", choices=["x"])
    parser.add_argument("--x")
    with pytest.raises(RuntimeError, match="posicional"):
        chk._actions_from_parser(parser)


@pytest.mark.parametrize(
    "content, message",
    [
        ("param([string]$Title,", "errores de parseo"),
        ("Write-Output 'hello'", "ParamBlock ausente"),
    ],
)
def test_r7_powershell_parse_error_o_paramblock_ausente_falla_cerrado(
    tmp_path, content, message
):
    """R7 BA03: AST roto o sin param() no produce contrato vacio/parcial."""
    script = tmp_path / "producer.ps1"
    script.write_text(content, encoding="utf-8")
    with pytest.raises(RuntimeError, match=message):
        chk._powershell_parser_actions(script)


def test_r7_argparse_subparsers_falla_cerrado():
    """R7 BA07: add_subparsers no modelado es ILEGIBLE, nunca contrato parcial."""
    parser = argparse.ArgumentParser()
    parser.add_subparsers(dest="command").add_parser("run")
    with pytest.raises(RuntimeError, match="subparsers"):
        chk._actions_from_parser(parser)


@pytest.mark.parametrize("valor", [None, "todos"])
def test_wot_2026_161u_latido_normal_acepta_test_detector_opcional(box, capsys, valor):
    """WOT-2026-161u mutantes M1/M2: la orden normal acepta --test-detector con y sin valor."""
    orders = box.coord_orders()
    detector = "--test-detector" if valor is None else f"--test-detector {valor}"
    orders[2] = (
        f"{box.py} {box.s('flight_stall_check.py')} {detector} --ops-dir {box.ops}"
    )
    coord = box.latido("test-detector.md", orders)
    sup = box.latido("test-detector-s.md", box.sup_orders())

    rc, out = run(box.argv(coord, sup), capsys)

    assert rc == 0, out
    assert out.startswith("latido-check: OK")


def test_wot_2026_161u_metadata_desconocida_sigue_ilegible(box, capsys, monkeypatch):
    """WOT-2026-161u mutante M3: metadata desconocida mantiene rc 2 y cierre fail-closed."""
    original = chk._SCRIPT_OPTION_META["flight_stall_check.py"]
    try:
        chk._SCRIPT_OPTION_META["flight_stall_check.py"] = {
            "--test-detector": chk._OptionSpec(True, False, False, "+")
        }
        coord, sup = box.good()
        rc = chk.main(box.argv(coord, sup))
        out = capsys.readouterr().out
    finally:
        chk._SCRIPT_OPTION_META["flight_stall_check.py"] = original

    assert rc == 2
    assert "metadata no modelada" in out


@pytest.mark.parametrize(
    "nargs, esperado",
    [("?", ()), ("+", ("nargs",))],
)
def test_wot_2026_161u_unsupported_nargs_solo_opcional_modelado(nargs, esperado):
    """WOT-2026-161u mutante M4: solo nargs=? queda modelado en el detalle de spec."""
    assert (
        chk._unsupported_spec_details(chk._OptionSpec(True, False, False, nargs))
        == esperado
    )


@pytest.mark.parametrize("nargs, modelado", [("?", True), ("+", False)])
def test_wot_2026_161u_actions_parser_modela_nargs_opcional(nargs, modelado):
    """WOT-2026-161u mutante M5: actions_from_parser refleja el soporte de nargs=? sin drift."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--opt", nargs=nargs)

    spec = chk._actions_from_parser(parser)["--opt"]

    assert ("nargs" not in spec.unsupported) is modelado


@pytest.mark.parametrize(
    "attribute, marker",
    [
        ("ValidateSet('x','y')", "ValidateSet"),
        ("ValidatePattern('x')", "ValidatePattern"),
        ("ValidateRange(1,2)", "ValidateRange"),
        ("Alias('T')", "Alias"),
        ("Parameter(Position=0)", "Parameter.Position"),
    ],
)
@windows_only
def test_r8_metadata_powershell_se_deriva_de_ps_real(attribute, marker, tmp_path):
    """R8 BA07/BA254: atributos reales no modelados quedan en metadata.unsupported."""
    script = tmp_path / "producer.ps1"
    prefix = "[" + attribute + "]"
    script.write_text(
        f"param([Parameter(Mandatory=$true)]{prefix}[string]$Title)\nexit 0\n",
        encoding="utf-8",
    )
    meta = chk._powershell_parser_actions(script)
    assert marker in meta["-Title"].unsupported


@pytest.mark.parametrize(
    "parameter_text",
    [
        "Parameter(ParameterSetName='A', Mandatory=$false)",
        "Parameter(Mandatory=$false, ParameterSetName='A')",
    ],
)
@windows_only
def test_r9_parameter_named_arguments_se_acumulan_en_ps_real(parameter_text, tmp_path):
    """R9 BA254: ParameterSetName no desaparece segun el orden del AST."""
    script = tmp_path / "parameter-set.ps1"
    script.write_text(
        f"param([{parameter_text}][string]$Title)\nexit 0\n", encoding="utf-8"
    )
    meta = chk._powershell_parser_actions(script)
    assert any(
        item == "Parameter.ParameterSetName" for item in meta["-Title"].unsupported
    )


def test_r9_metadata_ruta_alternativa_interna_es_rechazo_explicito(box, capsys):
    """R9 BA254: copia commiteada dentro de flight no cae en un retorno silencioso."""
    alternate = box.flight / "alternativa"
    alternate.mkdir()
    copied = alternate / "comms_alert.py"
    copied.write_text("# bogus copy\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(box.motor), "add", str(copied)], check=True)
    subprocess.run(
        ["git", "-C", str(box.motor), "commit", "-q", "-m", "alternate"],
        check=True,
    )
    orders = box.coord_orders()
    orders[0] = f"{box.py} {copied} --bogus"
    _coord, sup = box.good()
    rc, out = run(box.argv(box.latido("r9-alt.md", orders), sup), capsys)
    assert rc == 1
    assert "ruta de productor no autorizada" in out


def test_r8_metadata_argparse_se_deriva_de_parser_real(tmp_path):
    """R8 BA07: choices/type/mutex/nargs se detectan desde un parser productor real."""
    script = tmp_path / "producer.py"
    script.write_text(
        "import argparse\n"
        "def main(argv=None):\n"
        "    p=argparse.ArgumentParser()\n"
        "    g=p.add_mutually_exclusive_group()\n"
        "    g.add_argument('--choice', choices=['x'])\n"
        "    p.add_argument('--typed', type=int)\n"
        "    p.add_argument('--many', nargs='+')\n"
        "    p.parse_args(argv)\n",
        encoding="utf-8",
    )
    meta = chk._python_parser_actions(script)
    assert {"choices", "mutex"}.issubset(meta["--choice"].unsupported)
    assert "type" in meta["--typed"].unsupported
    assert "nargs" in meta["--many"].unsupported


@pytest.mark.parametrize(
    ("label", "producer", "detail"),
    [
        ("absent", None, "no se puede cargar contrato"),
        ("syntax", "def (:", "no se puede cargar contrato"),
        (
            "import-error",
            "raise RuntimeError('import boom')\n",
            "no se puede cargar contrato",
        ),
        (
            "missing-attribute",
            "FIELDS=('a',)\ndef _parse_unmeasured(value): pass\n",
            "module 'tick_trace_contract' has no attribute '_parse_rc'",
        ),
        (
            "missing-fields",
            "def _parse_rc(value, name): pass\ndef _parse_unmeasured(value): pass\n",
            "module 'tick_trace_contract' has no attribute 'FIELDS'",
        ),
        (
            "missing-parse-unmeasured",
            "FIELDS=('a',)\ndef _parse_rc(value, name): pass\n",
            "module 'tick_trace_contract' has no attribute '_parse_unmeasured'",
        ),
        (
            "non-callable-parse-rc",
            "FIELDS=('a',)\n_parse_rc=42\ndef _parse_unmeasured(value): pass\n",
            "contrato incompleto",
        ),
        (
            "non-callable-parse-unmeasured",
            "FIELDS=('a',)\ndef _parse_rc(value, name): pass\n_parse_unmeasured=42\n",
            "contrato incompleto",
        ),
        (
            "empty-fields",
            "FIELDS=()\ndef _parse_rc(value, name): pass\ndef _parse_unmeasured(value): pass\n",
            "contrato incompleto",
        ),
        (
            "non-iterable-fields",
            "FIELDS=42\ndef _parse_rc(value, name): pass\ndef _parse_unmeasured(value): pass\n",
            "'int' object is not iterable",
        ),
    ],
)
def test_r7_loader_roto_se_importa_y_publica_error_real(
    tmp_path, label, producer, detail
):
    """WOT-2026-160a DA/M3/M4: cada fallo real del loader llega a run_check como rc2."""
    flight = tmp_path / "scripts" / "flight"
    flight.mkdir(parents=True)
    for source in (_ROOT / "scripts" / "flight").iterdir():
        if source.is_file() and source.name != "tick_trace.py":
            shutil.copy2(source, flight / source.name)
    fake = flight / "tick_trace.py"
    if producer is not None:
        fake.write_text(producer, encoding="utf-8")
    module_name = f"check_latido_alert_wiring_probe_{label}_{id(tmp_path)}"
    spec = importlib.util.spec_from_file_location(
        module_name, flight / "check_latido_alert_wiring.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        roster = tmp_path / "roster.json"
        roster.write_text("{}", encoding="utf-8")
        rc, lines = module.run_check(
            roster=str(roster), specs={}, motor_root=tmp_path, environ={}
        )
        assert rc == 2
        assert module._TICK_TRACE_CONTRACT_ERROR is not None
        expected = f"no se pudo derivar contrato de tick_trace.py: {detail}"
        if detail in {"no se puede cargar contrato", "contrato incompleto"}:
            expected += f": {fake}"
        assert lines == [
            "latido-check: ILEGIBLE",
            f"  - [U] metadata de parsers: {expected}",
        ]
    finally:
        sys.modules.pop(module_name, None)


def test_r7_loader_real_es_control_positivo(tmp_path):
    """WOT-2026-160a DA: el productor real conserva contrato cargable."""
    assert chk._TICK_TRACE_CONTRACT_ERROR is None
    roster = tmp_path / "roster.json"
    roster.write_text("{}", encoding="utf-8")
    rc, lines = chk.run_check(
        roster=str(roster), specs={}, motor_root=tmp_path, environ={}
    )
    assert rc == 1
    assert lines == [
        "latido-check: VIOLACION",
        "  - [V] coordinadora: sin latido (pasa --latido-file ROL=RUTA)",
        "  - [V] supervisora: sin latido (pasa --latido-file ROL=RUTA)",
    ]


def test_r7_loader_docstring_declara_excepciones_y_captura():
    """WOT-2026-160a DC: el contrato documental refleja las excepciones observables."""
    doc = chk._load_tick_trace_contract.__doc__ or ""
    assert "RuntimeError" in doc
    assert "AttributeError" in doc
    assert "TypeError" in doc
    assert "modulo" in doc and "captura" in doc


def test_check_docstring_declara_limites_de_candidatura_y_rc():
    """WOT-2026-160a DD: los límites P5/P6 quedan declarados sin alterar código."""
    doc = chk.__doc__ or ""
    assert "Limites declarados" in doc
    assert "_is_candidate" in doc
    assert "rc 0-255" in doc
    assert chk._is_candidate("echo hello") is False
    assert chk._is_candidate("unknown.py --x") is False
    assert chk._is_candidate("python unknown.py --x") is True
    assert chk._is_candidate("tick_trace.py --guard-rc 0") is True


def test_r7_fallo_de_introspeccion_no_rompe_import_y_da_ilegible_con_alert(
    tmp_path, monkeypatch
):
    """R7 M3: un fallo de derivacion se vuelve rc 2 y pasa por el diagnostico/alerta."""
    monkeypatch.setattr(chk, "_SCRIPT_OPTION_META_ERROR", "powershell inexistente")
    monkeypatch.setattr(chk, "emit_alert", lambda *a, **k: True)
    roster = tmp_path / "roster.json"
    roster.write_text("{}", encoding="utf-8")
    rc, lines = chk.run_check(
        roster=str(roster),
        specs={},
        motor_root=tmp_path,
        environ={},
    )
    assert rc == 2
    assert "metadata de parsers" in lines[1]


def test_r7_subprocess_sin_systemroot_da_ilegible_y_diag_alert(tmp_path, request):
    """R7 original: PowerShell inexistente conserva rc2/metadata/diag_rc=2, hermético."""
    roster = tmp_path / "roster.json"
    roster.write_text("{}", encoding="utf-8")
    env = dict(os.environ)
    env["FLIGHT_POWERSHELL_EXE"] = str(tmp_path / "missing-powershell.exe")
    done = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--alert",
            "--roster-path",
            str(roster),
            "--ops-dir",
            str(tmp_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert "Traceback" not in done.stdout
    assert "metadata de parsers" in done.stdout
    assert "diag_rc=2" in done.stdout
    assert "POWERSHELL_STUB" in request.node._alert_subprocess_guard_log.read_text(
        encoding="utf-8"
    )


def test_alert_subprocess_barrier_logs_and_neutralizes_real_notifier(tmp_path, request):
    """D15: la barrera autouse intercepta una orden alert antes de que toque pantalla."""
    roster = tmp_path / "roster.json"
    roster.write_text("{}", encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--alert",
            "--roster-path",
            str(roster),
            "--ops-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1
    log = request.node._alert_subprocess_guard_log
    assert "INTERCEPTED run check --alert" in log.read_text(encoding="utf-8")


def test_alert_subprocess_barrier_intercepts_string_and_direct_popen(tmp_path, request):
    """D17: cadena y Popen directo no pueden esquivar la barrera."""
    command = f'"{sys.executable}" "{_SCRIPT}" --alert --ops-dir "{tmp_path}"'
    subprocess.run(  # noqa: S602 - la cadena es precisamente la superficie bajo prueba
        command, shell=True, capture_output=True, text=True, check=False
    )
    proc = subprocess.Popen(
        [sys.executable, str(_SCRIPT), "--alert", "--ops-dir", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    proc.communicate()
    log = request.node._alert_subprocess_guard_log.read_text(encoding="utf-8")
    assert "INTERCEPTED run check --alert" in log
    assert "INTERCEPTED Popen check --alert" in log


@pytest.mark.parametrize(
    "tail",
    [
        ("-Title a", "falta el parametro obligatorio"),
        ("-Message b", "falta el parametro obligatorio"),
        ("-Title a -Title c -Message b", "parametro repetido"),
        ("-Title a -Message b -NoFlash -NoFlash", "parametro repetido"),
    ],
)
@windows_only
def test_r4_ps_obligatoriedad_y_repeticion_son_del_ast_real(box, capsys, tail):
    """R4 N1/N2: obligatoriedad y unicidad del .ps1 no son una lista manual."""
    orders = box.sup_orders()
    orders[0] = orders[0].split(" -Title", 1)[0] + " " + tail[0]
    coord, _ = box.good()
    rc, out = run(box.argv(coord, box.latido("r4-ps-meta.md", orders)), capsys)
    assert rc == 1, out
    assert tail[1] in out


@pytest.mark.parametrize(
    ("argv_tail", "expected_rc"),
    [
        (["--alert", "--latido-file"], 2),
        (["--alert", "extra"], 2),
    ],
)
def test_r4_error_de_parseo_con_alert_emite_diagnostico_roto(
    box, capsys, monkeypatch, argv_tail, expected_rc
):
    """R4 M3: argparse rc 2 con --alert transita por el aviso latido-check-roto."""
    llamadas = []
    monkeypatch.setattr(
        chk,
        "emit_alert",
        lambda diag, line, **kwargs: llamadas.append((diag, line, kwargs)) or True,
    )
    rc, out = run(box.argv(extra=tuple(argv_tail)), capsys)
    assert rc == expected_rc
    assert "latido-check: ILEGIBLE (uso)" in out
    assert "diag_rc=2 alert=ok" in out
    assert llamadas and llamadas[0][0] == 2


@pytest.mark.parametrize(
    ("order_index", "suffix", "cause"),
    [
        (0, " --scan=x", "no admite valor inline"),
        (0, " --what --alert", "parece otra opcion"),
        (2, " --bogus", "opcion desconocida"),
        (4, " --flight-dir --alert", "parece otra opcion"),
        (5, " --alert=false", "no admite valor inline"),
        (0, " --dry-run", "silencia el aviso"),
    ],
)
def test_r3_flags_post_script_tienen_gramatica_cerrada(
    box, capsys, order_index, suffix, cause
):
    """R3: cada flag posterior al script tiene aridad cerrada y dry-run siempre falla."""
    orders = box.coord_orders()
    orders[order_index] += suffix
    c = box.latido("r3-flags.md", orders)
    s = box.latido("r3-flags-s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert cause in out, out


@pytest.mark.parametrize("flag", ["-S", "-s", "-E"])
def test_r3_opciones_python_validas_no_heredan_denylist_powershell(box, capsys, flag):
    """R3 BA03: -S/-s/-E son opciones Python validas, no la denylist de PowerShell."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} {flag} {box.s('comms_alert.py')} --scan --ops-dir {box.ops}"
    c = box.latido("r3-python-option.md", orders)
    s = box.latido("r3-python-option-s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 0, out


@windows_only
@pytest.mark.parametrize("flag", ["-S", "-s", "-E"])
def test_r3_opciones_equivalentes_powershell_son_rechazadas(box, capsys, flag):
    """R3 BA03: opciones no declaradas de PowerShell no pasan por parecerse a Python."""
    orders = box.sup_orders()
    orders[0] += f" {flag}"
    coord, _ = box.good()
    rc, out = run(box.argv(coord, box.latido("r3-ps-option.md", orders)), capsys)
    assert rc == 1, out
    assert "opcion desconocida" in out


def test_fila_136_symlink_mismo_flight_rc_1(box, capsys):
    """Fila 136 (mutacion 136.3): enlace en flight que apunta a otro fichero de flight -> rc 1
    con 'enlace apunta a otro fichero'."""
    try:
        link = box.flight / "comms_alert.py"
        link.unlink()
        link.symlink_to(box.flight / "quota_tick.py")
    except OSError:
        pytest.skip("no se pueden crear symlinks")
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "enlace apunta a otro fichero" in out


# ================================================================== FILA 137 -- INEXISTENTE


def test_fila_137_script_no_existe_rc_1(box, capsys):
    """Fila 137 (mutacion 137.1): script que no existe en disco -> rc 1 con 'falta'."""
    # Use a script path that still matches _SCRIPTS but doesn't exist on disk
    orders = [
        f"{box.py} /no/existe.py --scan --ops-dir {box.ops}",
        f"{box.py} {box.s('comms_alert.py')} --event clave --level URGENTE --what x",
        f"{box.py} {box.s('flight_stall_check.py')} --ops-dir {box.ops}",
        f"{box.py} {box.s('flight_stall_check.py')} --self-check",
        f"{box.py} {box.s('quota_tick.py')} > {box.root / 'quota.txt'}",
        f"{box.py} {box.s('check_latido_alert_wiring.py')} --alert",
    ]
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "VIOLACION" in out


@windows_only
def test_fila_137_unc_script_rc_1_rechaza_antes_de_resolver(box, capsys, monkeypatch):
    """Fila 137: una ruta UNC se rechaza antes de tocar ``Path.resolve`` para esa ruta."""
    original_resolve = Path.resolve
    resolved: list[str] = []

    def spy(path, *args, **kwargs):
        resolved.append(str(path))
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", spy)
    orders = box.coord_orders()
    orders[0] = f"{box.py} \\\\srv\\sh\\comms_alert.py --scan"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "VIOLACION" in out  # script UNC causes a violation
    assert not any(chk.is_unc(path) for path in resolved)

    resolved.clear()
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0, out
    assert any(not chk.is_unc(path) for path in resolved)


@windows_only
def test_fila_137_unc_script_slash_rc_1(box, capsys):
    """Fila 137 (mutacion 137.3): script UNC con `/` (`//srv/sh/comms_alert.py`) -> rc 1 'UNC'."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} //srv/sh/comms_alert.py --scan"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "VIOLACION" in out  # script UNC causes a violation


# ================================================================== FILA 138 -- NO TRACKED / DISTINTO DE HEAD


def test_fila_138_distinto_de_head_rc_1(box, capsys):
    """Fila 138 (mutacion 138.1): modifica comms_alert.py sin commit -> rc 1 'distinto de HEAD'."""
    (box.flight / "comms_alert.py").write_text("# MODIFIED\n", encoding="utf-8")
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "distinto de HEAD" in out


def test_fila_138_no_tracked_rm_cached_rc_1(box, capsys):
    """Fila 138 (mutacion 138.2): git rm --cached de quota_tick.py (sigue en disco) -> rc 1
    'no tracked'."""
    _git(box.motor, "rm", "--cached", "scripts/flight/quota_tick.py")
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "no tracked" in out


def test_fila_138_tras_commit_rc_0(box, capsys):
    """Fila 138 (mutacion 138.3): tras commitear lo modificado -> rc 0 (control positivo)."""
    (box.flight / "comms_alert.py").write_text("# MODIFIED\n", encoding="utf-8")
    _git(box.motor, "add", "scripts/flight/comms_alert.py")
    _git(box.motor, "commit", "-q", "-m", "modify comms")
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


# ================================================================== FILA 139 -- INDICE PREPARADO


def test_fila_139_indice_distinto_rc_1(box, capsys):
    """Fila 139 (mutacion 139.1): modifica, git add, RESTAURA trabajo a HEAD -> rc 1 'indice'
    (hash trabajo == HEAD, pero indice distinto)."""
    (box.flight / "comms_alert.py").write_text("# STAGED\n", encoding="utf-8")
    _git(box.motor, "add", "scripts/flight/comms_alert.py")
    _git(box.motor, "checkout", "--", "scripts/flight/comms_alert.py")
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "indice" in out


# ================================================================== FILA 140 -- GIT CON -- Y RUTA RELATIVIZADA


@windows_only
def test_fila_140_git_wrapper_cmd(box, capsys):
    """Fila 140 (mutacion 140.1): git-wrapper.cmd que loga argumentos, comprueba `--` y
    rev-parse HEAD:./scripts/flight/<script>."""
    git_real = shutil.which("git")
    wrapper = box.root / "git-wrapper.cmd"
    wrapper.write_text(
        f'@echo off\r\necho %* >> {box.root / "git.log"}\r\ncall "{git_real}" %*\r\n',
        encoding="utf-8",
    )
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup, extra=["--git-exe", str(wrapper)]), capsys)
    assert rc == 0, out
    log = (box.root / "git.log").read_text(encoding="utf-8")
    assert "--" in log, "git-wrapper no recibio `--` antes de rutas"
    assert "HEAD:./scripts/flight/" in log, "rev-parse sin path relativizado"


# ================================================================== FILA 141 -- UNIDAD Y BARRAS


def test_fila_141_minuscula_slash_rc_0(box, capsys):
    """Fila 141 (mutacion 141.1): ordenes con letra de unidad en minuscula y `/` en vez de `\\`
    -> rc 0."""
    py_lower = box.py.lower()
    flight_lower = str(box.flight).replace("\\", "/").lower()
    c_orders = [
        f"{py_lower} {flight_lower}/comms_alert.py --scan --ops-dir {box.ops}",
        f'{py_lower} {flight_lower}/comms_alert.py --event clave --level URGENTE --what "x"',
        f"{py_lower} {flight_lower}/flight_stall_check.py --ops-dir {box.ops}",
        f"{py_lower} {flight_lower}/flight_stall_check.py --self-check",
        f"{py_lower} {flight_lower}/quota_tick.py > {box.root / 'quota.txt'}",
        f"{py_lower} {flight_lower}/check_latido_alert_wiring.py --alert",
        box.trace_order(),
    ]
    sysroot = os.environ.get("SYSTEMROOT", "")
    ps_lower = str(
        Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    ).lower()
    sup_orders = [
        f"{ps_lower} -NoProfile -NonInteractive -File {flight_lower}/notify_user.ps1 -Title t -Message m",
        f"{py_lower} {flight_lower}/quota_tick.py",
    ]
    c = box.latido("c.md", c_orders)
    s = box.latido("s.md", sup_orders)
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


@windows_only
def test_fila_141_prefijo_dispositivo_rc_0(box, capsys):
    """Fila 141 (mutacion 141.2): prefijo de dispositivo `\\\\?\\C:\\...` en el script -> rc 0."""
    py = box.py
    dev_prefix = f"\\\\?\\{box.s('comms_alert.py')}"
    orders = [
        f"{py} {dev_prefix} --scan --ops-dir {box.ops}",
        f'{py} {dev_prefix} --event clave --level URGENTE --what "x"',
        f"{py} {box.s('flight_stall_check.py')} --ops-dir {box.ops}",
        f"{py} {box.s('flight_stall_check.py')} --self-check",
        f"{py} {box.s('quota_tick.py')} > {box.root / 'quota.txt'}",
        f"{py} {box.s('check_latido_alert_wiring.py')} --alert",
        box.trace_order(),
    ]
    sup = box.latido("s.md", box.sup_orders())
    c = box.latido("c.md", orders)
    rc, out = run(box.argv(c, sup), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


def test_fila_141_otra_unidad_rc_1(box, capsys):
    """Fila 141 (mutacion 141.3): letra de otro disco inexistente (Z:\\...) -> rc 1."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} Z:\\x\\comms_alert.py --scan"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "VIOLACION" in out


# ================================================================== FILA 142 -- TMP_OR8


def test_fila_142_copia_tmp_or8_fuera_rc_1(box, capsys):
    """Fila 142 (mutacion 142.1): copia comms_alert.py a `tmp_or8` fuera del motor -> rc 1
    'tmp_or8'."""
    tmp_or8 = box.root / "tmp_or8"
    tmp_or8.mkdir()
    (tmp_or8 / "comms_alert.py").write_text("# copy\n", encoding="utf-8")
    orders = box.coord_orders()
    orders[0] = f"{box.py} {tmp_or8 / 'comms_alert.py'} --scan --ops-dir {box.ops}"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "tmp_or8" in out


def test_fila_142_ops_dir_arg_rc_0(box, capsys):
    """Fila 142 (mutacion 142.2): `--ops-dir C:/algo/tmp_or8` como argumento de orden buena
    -> rc 0 (solo se chequea la ruta del script, no los flags)."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} {box.s('comms_alert.py')} --scan --ops-dir C:/algo/tmp_or8"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


# ================================================================== FILA 143 -- FLAG EN ORDEN DISTINTA


def test_fila_143_scan_en_otra_rc_1(box, capsys):
    """Fila 143 (mutacion 143.1): orden de comms_alert sin `--scan`, con `--scan` en quota_tick
    -> rc 1."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} {box.s('comms_alert.py')} --event clave --ops-dir {box.ops}"
    orders[4] = f"{box.py} {box.s('quota_tick.py')} --scan"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "falta una orden VALIDA" in out


def test_fila_143_self_check_quota_rc_1(box, capsys):
    """Fila 143 (mutacion 143.2): `--self-check` solo en quota_tick -> rc 1."""
    orders = box.coord_orders()
    orders[3] = f"{box.py} {box.s('quota_tick.py')} --self-check"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "flight_stall_check.py --self-check" in out


@windows_only
def test_fila_143_solamente_flight_stall_self_rc_1(box, capsys):
    """Fila 143 (mutacion 143.3): solo flight_stall_check con --self-check -> rc 1 (falta normal)."""
    orders = [f"{box.py} {box.s('flight_stall_check.py')} --self-check"]
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "comms_alert.py --scan" in out


# ================================================================== FILA 144 -- DOS LATIDOS (@windows_only)


@windows_only
def test_fila_144_coord_buen_sup_mala_rc_1(box, capsys):
    """Fila 144 (mutacion 144.1): coordinadora buena + supervisora mala -> rc 1 'supervisora'."""
    coord, _ = box.good()
    sup = box.root / "bad_s.md"
    sup.write_text("", encoding="utf-8")
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "supervisora" in out


@windows_only
def test_fila_144_coord_mala_sup_buen_rc_1(box, capsys):
    """Fila 144 (mutacion 144.2): coordinadora mala + supervisora buena -> rc 1 'coordinadora'."""
    _, sup = box.good()
    coord = box.root / "bad_c.md"
    coord.write_text("", encoding="utf-8")
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "coordinadora" in out


# ================================================================== FILA 145 -- COORDINadora CONTIENE ORDEN PROPIA


def test_fila_145_sin_ord_propia_rc_1(box, capsys):
    """Fila 145 (mutacion 145.1): sin la orden del propio check -> rc 1."""
    orders = box.coord_orders()
    orders.remove(
        next(
            order for order in orders if "check_latido_alert_wiring.py --alert" in order
        )
    )
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "check_latido_alert_wiring.py --alert" in out


def test_fila_145_sin_alert_rc_1(box, capsys):
    """Fila 145 (mutacion 145.2): con la orden del check pero sin `--alert` -> rc 1."""
    orders = box.coord_orders()
    orders[5] = f"{box.py} {box.s('check_latido_alert_wiring.py')}"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "check_latido_alert_wiring.py --alert" in out


# ================================================================== FILA 146 -- DENYLIST -SimulateToastFailure (@windows_only)


@windows_only
def test_fila_146_simulatetoastfailure_rc_1(box, capsys):
    """Fila 146 (mutacion 146.1): -SimulateToastFailure en la orden notify_user de supervisora
    -> rc 1."""
    orders = box.sup_orders()
    orders[0] += " -SimulateToastFailure"
    coord, _ = box.good()
    s = box.latido("s.md", orders)
    rc, out = run(box.argv(coord, s), capsys)
    assert rc == 1, out
    assert "suprime el aviso" in out


@windows_only
def test_fila_146_prefijo_sim_rc_1(box, capsys):
    """Fila 146 (mutacion 146.2): prefijo `-Sim` -> rc 1."""
    orders = box.sup_orders()
    orders[0] += " -Simulate"
    coord, _ = box.good()
    s = box.latido("s.md", orders)
    rc, out = run(box.argv(coord, s), capsys)
    assert rc == 1, out
    assert "suprime el aviso" in out


@windows_only
def test_caja1_simulate_notifier_setting_denylist_rc_1(box, capsys):
    """RED/R7: el gancho de Setting Disabled también suprime avisos y queda prohibido."""
    orders = box.sup_orders()
    orders[0] += " -SimulateNotifierSetting Disabled"
    coord, _ = box.good()
    s = box.latido("s-caja1.md", orders)
    rc, out = run(box.argv(coord, s), capsys)
    assert rc == 1, out
    assert "suprime el aviso" in out


# ================================================================== FILA 147 -- DENYLIST POWERSHELL (@windows_only)


@pytest.mark.parametrize(
    "flag",
    [
        "-EncodedCommand",
        "-enc",
        "-e",
        "-ec",
        "-Command",
        "-c",
        "-ExecutionPolicy Bypass",
        "-ep bypass",
    ],
)
@windows_only
def test_fila_147_ps_denylist_rc_1(box, capsys, flag):
    """Fila 147 (mutacion 147.N): cada flag prohibido, ANTES de -File, da rc 1."""
    orders = box.sup_orders()
    orders[0] = orders[0].replace(" -File ", f" {flag} -File ")
    assert flag in orders[0]
    coord, _ = box.good()
    s = box.latido("s.md", orders)
    rc, out = run(box.argv(coord, s), capsys)
    assert rc == 1, out
    assert "VIOLACION" in out


@windows_only
def test_fila_147_command_tras_file_es_una_opcion_desconocida_rc_1(box, capsys):
    """R4 M1: tras `-File <script>` solo los parametros declarados por el .ps1 pasan."""
    orders = box.sup_orders()
    orders[0] += " -Command"
    coord, _ = box.good()
    rc, out = run(box.argv(coord, box.latido("s.md", orders)), capsys)
    assert rc == 1, out
    assert "opcion desconocida" in out


def test_fila_147_executionpolicy_tras_script_rc_1(box, capsys):
    """R4 M1: `-ExecutionPolicy` no es parametro de notify_user.ps1 despues del script."""
    orders = box.sup_orders()
    orders[0] += " -ExecutionPolicy RemoteSigned"
    coord, _ = box.good()
    s = box.latido("s.md", orders)
    rc, out = run(box.argv(coord, s), capsys)
    assert rc == 1, out
    assert "opcion desconocida" in out


@windows_only
def test_fila_147_windowstyle_tras_script_rc_1(box, capsys):
    """R4 M1: `-WindowStyle` no es parametro de notify_user.ps1 despues del script."""
    orders = box.sup_orders()
    orders[0] += " -WindowStyle Hidden"
    coord, _ = box.good()
    s = box.latido("s.md", orders)
    rc, out = run(box.argv(coord, s), capsys)
    assert rc == 1, out
    assert "opcion desconocida" in out


@pytest.mark.parametrize(
    "launcher, value, expected",
    [
        ("-ExecutionPolicy", "RemoteSigned", 0),
        ("-ExecutionPolicy", "Bogus", 1),
        ("-WindowStyle", "Hidden", 0),
        ("-WindowStyle", "Bogus", 1),
    ],
)
@windows_only
def test_r8_powershell_launcher_values_have_closed_domains(
    box, capsys, launcher, value, expected
):
    """R8 BA07: valores de opciones del launcher siguen los dominios de PowerShell."""
    orders = box.sup_orders()
    orders[0] = orders[0].replace(" -File ", f" {launcher} {value} -File ")
    coord, _ = box.good()
    rc, out = run(box.argv(coord, box.latido("r8-launcher.md", orders)), capsys)
    assert rc == expected, out


@pytest.mark.parametrize("empty_arg", ['-Title ""', '-Message ""', "-Title ''"])
@windows_only
def test_r12_powershell_mandatory_string_vacio_es_rechazado(box, capsys, empty_arg):
    """R12 MAJOR: PowerShell no enlaza cadena vacia a Mandatory string."""
    orders = box.sup_orders()
    replacement = (
        f"{empty_arg} -Message m"
        if empty_arg.startswith("-Title")
        else f"-Title t {empty_arg}"
    )
    orders[0] = orders[0].replace("-Title t -Message m", replacement)
    coord, _ = box.good()
    rc, out = run(box.argv(coord, box.latido("r12-empty.md", orders)), capsys)
    assert rc == 1, out
    assert "valor vacio" in out


@pytest.mark.parametrize(
    "value, real_success",
    [
        ("Bypass", True),
        ("RemoteSigned", True),
        ("Unrestricted", True),
        ("Default", False),
        ("Undefined", False),
        ("Restricted", False),
        ("AllSigned", False),
    ],
)
@windows_only
def test_r12_executionpolicy_soundness_contra_powershell_real(
    tmp_path, box, value, real_success
):
    """R12 MAJOR: solo politicas ejecutables por PowerShell real pueden pasar el dominio."""
    script = tmp_path / "notify_user.ps1"
    script.write_text("param([string]$Title,[string]$Message)\n", encoding="utf-8")
    real = subprocess.run(
        [
            box.ps,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            value,
            "-File",
            str(script),
            "-Title",
            "t",
            "-Message",
            "m",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (real.returncode == 0) is real_success
    order = chk._Order(1, "order")
    checker = chk._Checker(box.motor, box.py, None, dict(os.environ))
    checker._powershell_script_position(
        order, [box.ps, "-ExecutionPolicy", value, "-File", box.s("notify_user.ps1")]
    )
    accepted = not order.problems
    assert accepted == (value.lower() in {"bypass", "remotesigned", "unrestricted"})


@windows_only
def test_r13_prefijos_powershell_soundness_contra_productor_real(box):
    """R13: ningun prefijo aceptado por el check falla en powershell.exe real."""
    options = [
        ("NoProfile", None),
        ("NonInteractive", None),
        ("NoLogo", None),
        ("NoExit", None),
        ("Sta", None),
        ("Mta", None),
        ("WindowStyle", "Normal"),
        ("ExecutionPolicy", "RemoteSigned"),
    ]
    checker = chk._Checker(box.motor, box.py, None, dict(os.environ))
    for option, value in options:
        for size in range(1, len(option) + 1):
            prefix = "-" + option[:size]
            order = chk._Order(1, "order")
            words = [box.ps, prefix]
            if value is not None:
                words.append(value)
            words += ["-File", box.s("notify_user.ps1")]
            checker._powershell_script_position(order, words)
            check_accepts = not order.problems
            command = [box.ps, prefix]
            if value is not None:
                command.append(value)
            command += ["-File", box.s("notify_user.ps1")]
            try:
                real = subprocess.run(
                    command,
                    input="",
                    capture_output=True,
                    text=True,
                    timeout=25,
                    check=False,
                )
                real_accepts = real.returncode == 0
                real_rc = real.returncode
            except subprocess.TimeoutExpired:
                real_accepts = False
                real_rc = "timeout"
            assert not check_accepts or real_accepts, (prefix, real_rc)


@windows_only
def test_r2_powershell_script_posicional_sin_file_rc_1_por_mandatorios(box, capsys):
    """R4 N1: el script posicional sin Title/Message viola los Mandatory reales."""
    orders = box.sup_orders()
    orders[0] = f"{box.ps} -NoProfile {box.s('notify_user.ps1')}"
    coord, _ = box.good()
    s = box.latido("s.md", orders)
    rc, out = run(box.argv(coord, s), capsys)
    assert rc == 1, out
    assert "falta el parametro obligatorio" in out


# ================================================================== FILA 148 -- POWERSHELL (@windows_only)


@windows_only
def test_fila_148_no_es_powershell_fijado_rc_1(box, capsys):
    """Fila 148 (mutacion 148.1): copia sys.executable a tmp/powershell.exe, usar como interprete
    de notify_user -> rc 1 'no es el fijado'."""
    tmp = box.root / "tmp"
    tmp.mkdir()
    fake_ps = tmp / "powershell.exe"
    shutil.copy2(sys.executable, str(fake_ps))
    orders = box.sup_orders()
    orders[0] = (
        f"{fake_ps} -NoProfile -NonInteractive -File {box.s('notify_user.ps1')} -Title t -Message m"
    )
    coord, _ = box.good()
    s = box.latido("s.md", orders)
    rc, out = run(box.argv(coord, s), capsys)
    assert rc == 1, out
    assert "no es el fijado" in out


@windows_only
def test_fila_148_real_powershell_rc_0(box, capsys):
    """Fila 148 (mutacion 148.2): el PowerShell real -> rc 0."""
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


@windows_only
def test_fila_148_sin_systemroot_rc_2(box, capsys):
    """Fila 148 (mutacion 148.3): chk.run_check(..., environ={}) sin SystemRoot con latido
    PowerShell -> rc 2 'SystemRoot'."""
    coord, sup = box.good()
    rc, lines = chk.run_check(
        roster=str(box.roster),
        specs={"coordinadora": str(coord), "supervisora": str(sup)},
        motor_root=box.motor,
        python_exe=box.py,
        environ={},  # sin SystemRoot
    )
    assert rc == 2, str(lines)
    assert "SystemRoot" in "\n".join(lines)


# ================================================================== FILA 149 -- PYTHON FIJADO


def test_fila_149_no_es_python_fijado_rc_1(box, capsys):
    """Fila 149 (mutacion 149.1): copia sys.executable a carpeta como python.exe y usarla
    -> rc 1 'no es el fijado'."""
    fake = box.root / "fake_python"
    fake.mkdir()
    fake_py = fake / "python.exe"
    shutil.copy2(sys.executable, str(fake_py))
    orders = box.coord_orders()
    orders[0] = f"{fake_py} {box.s('comms_alert.py')} --scan --ops-dir {box.ops}"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s, extra=["--python-exe", str(fake_py)]), capsys)
    assert rc == 1, out
    assert "no es el fijado" in out


def test_fila_149_sin_python_exe_rc_2(box, capsys):
    """Fila 149 (mutacion 149.2): sin --python-exe, sin FLIGHT_PYTHON, sin .venv -> rc 2."""
    coord, sup = box.good()
    args = box.argv(coord, sup)
    del args[args.index("--python-exe") : args.index("--python-exe") + 2]
    rc, out = run(args, capsys)
    assert rc == 2, out
    assert "interprete Python fijado" in out


def test_fila_149_flight_python_env_rc_0(box, capsys, monkeypatch):
    """Fila 149 (mutacion 149.3): FLIGHT_PYTHON por entorno basta -> rc 0."""
    coord, sup = box.good()
    monkeypatch.setenv(chk.PYTHON_ENV, box.py)
    args = box.argv(coord, sup)
    del args[args.index("--python-exe") : args.index("--python-exe") + 2]
    rc, out = run(args, capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


def test_fila_149_python_exe_gana_rc_0(box, capsys):
    """Fila 149 (mutacion 149.4): `--python-exe` gana al entorno -> rc 0."""
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup, extra=["--python-exe", box.py]), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


# ================================================================== FILA 150 -- GIT


def test_fila_150_git_fake_version_rc_2(box, capsys):
    """Fila 150 (mutacion 150.1): --git-exe a exe que imprime otra cosa en --version -> rc 2."""
    fake_git = box.root / "fake_git.cmd"
    fake_git.write_text(
        "@echo off\r\necho not git version 1.0\r\nexit /b 0\r\n", encoding="utf-8"
    )
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup, extra=["--git-exe", str(fake_git)]), capsys)
    assert rc == 2, out
    assert "git" in out


def test_fila_150_git_timeout_rc_2(box, monkeypatch):
    """Fila 150 (mutacion 150.2): git que no responde (TimeoutExpired) -> rc 2 'no responde'."""

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0] if args else [], 0)

    coord, sup = box.good()
    monkeypatch.setattr(chk.subprocess, "run", fake_run)
    rc, lines = chk.run_check(
        roster=str(box.roster),
        specs={"coordinadora": str(coord), "supervisora": str(sup)},
        motor_root=box.motor,
        python_exe=box.py,
    )
    assert rc == 2, str(lines)
    texto = "\n".join(lines)
    assert "no responde" in texto, texto


def test_fila_150_motor_root_no_git_rc_2(box, capsys, monkeypatch):
    """Fila 150 (mutacion 150.3): motor-root que no es repo git -> rc 2 (no 1)."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(box.root))
    fake_motor = box.root / "fake_motor"
    fake_flight = fake_motor / "scripts" / "flight"
    fake_flight.mkdir(parents=True)
    for name in _STUBS:
        (fake_flight / name).write_text(f"# stub {name}\n", encoding="utf-8")
    orders = [o.replace(str(box.flight), str(fake_flight)) for o in box.coord_orders()]
    coord = box.latido("c.md", orders)
    sup = box.latido("s.md", box.sup_orders())
    args = box.argv(coord, sup)
    args[args.index("--motor-root") + 1] = str(fake_motor)
    rc, out = run(args, capsys)
    assert rc == 2, out
    assert "ILEGIBLE" in out


# ================================================================== EXTRAS: REDIRECCIONES (Q5)


def test_fila_q5_redir_existent_dir_rc_0(box, capsys):
    """Q5: `> ruta` de quota_tick con directorio existente -> rc 0 (ya en coord_orders)."""
    # The existing coord_orders has `> {box.root / 'quota.txt'}` - rc 0 is default.
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0, out
    assert "latido-check: OK" in out


def test_fila_q5_append_rc_1(box, capsys):
    """Q5: `>>` en CUALQUIER orden -> rc 1."""
    orders = box.coord_orders()
    orders[0] += " >> /dev/null"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


def test_fila_q5_2rc_1(box, capsys):
    """Q5: `2>` en CUALQUIER orden -> rc 1."""
    orders = box.coord_orders()
    orders[0] += " 2>/dev/null"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


def test_fila_q5_andrc_1(box, capsys):
    """Q5: `&>` en CUALQUIER orden -> rc 1."""
    orders = box.coord_orders()
    orders[0] += " &>/dev/null"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


def test_fila_q5_pipe_redir_rc_1(box, capsys):
    """Q5: `|` en CUALQUIER orden -> rc 1."""
    orders = box.coord_orders()
    orders[0] += " | cat"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


def test_fila_q5_ampamp_rc_1(box, capsys):
    """Q5: `&&` en CUALQUIER orden -> rc 1."""
    orders = box.coord_orders()
    orders[0] += " && true"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


def test_fila_q5_semicolon_rc_1(box, capsys):
    """Q5: `;` en CUALQUIER orden -> rc 1."""
    orders = box.coord_orders()
    orders[0] += "; echo ok"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


def test_fila_q5_rc_on_comms_alert_rc_1(box, capsys):
    """Q5: `>` en la orden de comms_alert -> rc 1."""
    orders = box.coord_orders()
    orders[0] += " > /tmp/out.txt"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


def test_fila_q5_dos_rc_1(box, capsys):
    """Q5: dos `>` en quota_tick -> rc 1."""
    orders = box.coord_orders()
    orders[4] += " >> /tmp/app.txt"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


def test_fila_q5_rc_dir_inexistente_rc_1(box, capsys):
    """Q5: `>` a directorio inexistente -> rc 1."""
    orders = box.coord_orders()
    orders[4] = (
        f"{box.py} {box.s('quota_tick.py')} > {box.root / 'nonexistent_dir' / 'out.txt'}"
    )
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "directorio" in out


def test_fila_q5_rc_relativo_rc_1(box, capsys):
    """Q5: `>` a ruta relativa -> rc 1."""
    orders = box.coord_orders()
    orders[4] = f"{box.py} {box.s('quota_tick.py')} > out.txt"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "ruta no absoluta" in out


def test_fila_q5_rc_unc_rc_1(box, capsys):
    """Q5: `>` UNC -> rc 1."""
    orders = box.coord_orders()
    orders[4] = f"{box.py} {box.s('quota_tick.py')} > \\\\srv\\sh\\out.txt"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "no absoluta" in out or "UNC" in out


def test_fila_q5_marca_posicional_rc_1(box, capsys):
    """R4 M2: un marcador suelto no es argumento posicional declarado por argparse."""
    orders = box.coord_orders()
    orders[0] += " <clave>"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "opcion desconocida" in out


# ================================================================== EXTRAS: UNIDAD DE FUNCIONES


def test_fila_q5_tokenize_comillas(box):
    """Q5: `chk.tokenize` con comillas, `2>` y `<marcador>`."""
    toks = chk.tokenize('python "C:\\x" 2> out.txt <marcador> --flag')
    words = [t for k, t in toks if k == "word"]
    assert "python" in words
    assert "C:\\x" in words
    assert "2>" in [t for k, t in toks if k == "op"]
    assert "<marcador>" in words


def test_fila_q5_tokenize_comilla_sin_cerrar(box):
    """Q5: `chk.tokenize` comilla sin cerrar -> ValueError."""
    with pytest.raises(ValueError, match="comilla sin cerrar"):
        chk.tokenize('python "x')


def test_fila_q5_parse_latido_specs_unknown_role(box):
    """Q5: `chk.parse_latido_specs` rol desconocido -> UsageError."""
    with pytest.raises(chk.UsageError, match="rol desconocido"):
        chk.parse_latido_specs(["badrole=file.md"])


def test_fila_q5_parse_latido_specs_no_equals(box):
    """Q5: `chk.parse_latido_specs` sin `=` -> UsageError."""
    with pytest.raises(chk.UsageError, match="ROL=RUTA"):
        chk.parse_latido_specs(["badformat"])


def test_fila_q5_parse_latido_specs_repetido(box):
    """Q5: `chk.parse_latido_specs` rol repetido -> UsageError."""
    with pytest.raises(chk.UsageError, match="repetido"):
        chk.parse_latido_specs(["coordinadora=a.md", "coordinadora=b.md"])


def test_fila_q5_parse_latido_specs_ruta_vacia(box):
    """Q5: `chk.parse_latido_specs` ruta vacia -> UsageError."""
    with pytest.raises(chk.UsageError, match="ROL=RUTA"):
        chk.parse_latido_specs(["coordinadora="])


def test_fila_q5_parse_latido_specs_cli_gana_entorno(box, monkeypatch):
    """Q5: CLI gana al entorno en parse_latido_specs."""
    monkeypatch.setenv(chk.LATIDO_ENV, "coordinadora=/env.md")
    specs = chk.parse_latido_specs(["coordinadora=/cli.md"], dict(os.environ))
    assert specs["coordinadora"] == "/cli.md"


def test_fila_q5_is_unc_true(box):
    """Q5: `chk.is_unc` True para `\\\\h\\s`, `//h/s`, `\\\\?\\UNC\\h\\s`, `//?/UNC/h/s`."""
    assert chk.is_unc("\\\\h\\s")
    assert chk.is_unc("//h/s")
    assert chk.is_unc("\\\\?\\UNC\\h\\s")
    assert chk.is_unc("//?/UNC/h/s")


def test_fila_q5_is_unc_false(box):
    """Q5: `chk.is_unc` False para `C:\\x`, `\\\\?\\C:\\x`, `//?/C:/x`, `x`."""
    assert not chk.is_unc("C:\\x")
    assert not chk.is_unc("\\\\?\\C:\\x")
    assert not chk.is_unc("//?/C:/x")
    assert not chk.is_unc("x")


def test_fila_q5_aggregate_violacion_ilegible(box):
    """Q5: `chk.aggregate` violacion + ilegible -> 2 (EXIT_UNREADABLE)."""
    findings = [
        chk._Finding("V", "coordinadora", "", "falta una orden"),
        chk._Finding("U", "supervisora", "", "ilegible"),
    ]
    assert chk.aggregate(findings) == chk.EXIT_UNREADABLE


# ================================================================== EXTRAS: SALIDA FINAL


def test_fila_q5_ultima_linea_reproducir(box, capsys):
    """Q5: la salida termina en la linea `reproducir y revalidar:`."""
    coord, sup = box.good()
    _, out = run(box.argv(coord, sup), capsys)
    last_line = out.strip().split("\n")[-1]
    assert last_line.startswith("reproducir y revalidar:")


def test_fila_q5_reproducir_mismo_rc(box, capsys):
    """Q5: ejecutar la orden `reproducir y revalidar:` por subprocess da el mismo rc."""
    coord, sup = box.good()
    rc1, out = run(box.argv(coord, sup), capsys)
    assert rc1 == 0, out
    last_line = out.strip().split("\n")[-1]
    cmd = last_line.split("reproducir y revalidar:")[1].strip()
    assert "--python-exe" in cmd
    result = subprocess.run(  # noqa: S602 - la orden es la que imprime el propio check
        cmd, shell=True, check=False, capture_output=True, text=True
    )
    assert result.returncode == rc1, (
        f"Expected rc {rc1}, got {result.returncode}: {result.stderr[:200]}"
    )


# ====================================================================== 3A: PRUEBAS QUE MATAN SUPERVIVIENTES
# Cada una discrimina por la CAUSA (mensaje) o por la forma exacta, no solo por el rc.
def test_fila_133_roster_relativo_contra_motor_root_no_el_cwd(box, capsys, monkeypatch):
    """Fila 133 / N99b: `--roster-path` relativo se resuelve contra --motor-root."""
    (box.motor / "rosters").mkdir()
    (box.motor / "rosters" / "r.json").write_text("{}", encoding="utf-8")
    otro = box.root / "otro_cwd"
    otro.mkdir()
    monkeypatch.chdir(otro)
    coord, sup = box.good()
    args = box.argv(coord, sup)
    args[args.index("--roster-path") + 1] = "rosters/r.json"
    rc, out = run(args, capsys)
    assert rc == 0, out


def test_fila_133_roster_relativo_ausente_en_motor_es_rc_2(box, capsys, monkeypatch):
    """Control negativo de la anterior: el mismo relativo que NO existe en el motor da rc 2."""
    otro = box.root / "otro_cwd"
    otro.mkdir()
    (otro / "rosters").mkdir()
    (otro / "rosters" / "r.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(otro)
    coord, sup = box.good()
    args = box.argv(coord, sup)
    args[args.index("--roster-path") + 1] = "rosters/r.json"
    rc, out = run(args, capsys)
    assert rc == 2 and "roster" in out, out


@windows_only
def test_fila_133_canon_ignora_mayusculas_de_ruta_en_windows():
    """Control N107: la contencion de rutas es insensible a mayusculas en Windows."""
    upper = chk._canon(r"C:\\Motor\\Scripts\\Flight\\check.py")
    lower = chk._canon(r"c:\\motor\\scripts\\flight\\check.py")
    assert upper == lower


@windows_only
def test_fila_140_git_recibe_dos_guiones_antes_de_cada_ruta(box, capsys):
    """Fila 140 / N106a-c: ls-files, hash-object y diff --cached llevan `--` justo antes de la
    ruta relativa; rev-parse recibe `HEAD:./ruta`."""
    git_real = shutil.which("git")
    log = box.root / "git2.log"
    wrapper = box.root / "git-wrapper2.cmd"
    wrapper.write_text(
        f'@echo off\r\necho %* >> {log}\r\ncall "{git_real}" %*\r\n', encoding="utf-8"
    )
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup, extra=("--git-exe", str(wrapper))), capsys)
    assert rc == 0, out
    filas = [
        ln.split() for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    con_ruta = [t for t in filas if any(w.startswith("scripts/flight/") for w in t)]
    assert {t[t.index("--") - 1] if "--" in t else "" for t in con_ruta} >= {
        "--error-unmatch",
        "hash-object",
        "--quiet",
    }
    for toks in con_ruta:
        i = next(i for i, w in enumerate(toks) if w.startswith("scripts/flight/"))
        assert toks[i - 1] == "--", toks
    assert any(w.startswith("HEAD:./scripts/flight/") for t in filas for w in t)


def test_fila_142_la_causa_de_tmp_or8_es_la_copia_no_otra(box, capsys):
    """Fila 142 / N108: el motivo del rechazo es tmp_or8 (no solo estar fuera del motor)."""
    tmp_or8 = box.root / "tmp_or8"
    tmp_or8.mkdir()
    (tmp_or8 / "comms_alert.py").write_text("# copy\n", encoding="utf-8")
    orders = box.coord_orders()
    orders[0] = f"{box.py} {tmp_or8 / 'comms_alert.py'} --scan --ops-dir {box.ops}"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "el script vive en tmp_or8" in out


@windows_only
@pytest.mark.parametrize("flag", ["-EncodedCommand", "-enc", "-ec", "-e"])
def test_fila_147_encoded_command_tras_file_tambien_es_violacion(box, capsys, flag):
    """Fila 147 / N113: -EncodedCommand y sus prefijos se prohiben en CUALQUIER posicion."""
    orders = box.sup_orders()
    orders[0] += f" {flag}"
    coord, _ = box.good()
    rc, out = run(box.argv(coord, box.latido("s.md", orders)), capsys)
    assert rc == 1, out
    assert "EncodedCommand" in out


@windows_only
@pytest.mark.parametrize("flag", ["-Command", "-c", "-Comm"])
def test_fila_147_command_antes_de_file_se_nombra_por_su_causa(box, capsys, flag):
    """Fila 147 / X-pscmd: la causa es `-Command no ejecuta un script con -File`."""
    orders = box.sup_orders()
    orders[0] = orders[0].replace(" -File ", f" {flag} -File ")
    coord, _ = box.good()
    rc, out = run(box.argv(coord, box.latido("s.md", orders)), capsys)
    assert rc == 1, out
    assert "no ejecuta un script con -File" in out


def test_fila_134_interprete_relativo_se_nombra_por_su_causa(box, capsys):
    """Fila 134 / N115: `python <script>` (sin ruta absoluta) -> causa 'ABSOLUTA'."""
    orders = box.coord_orders()
    orders[0] = f"python {box.s('comms_alert.py')} --scan --ops-dir {box.ops}"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "no es una ruta ABSOLUTA" in out


@pytest.mark.parametrize(
    ("opt", "cause"),
    [
        ("-c", "python -c / -m no es la invocacion de un script"),
        ("-m", "python -c / -m no es la invocacion de un script"),
        ("-Ic", "opcion de Python no permitida: -Ic"),
        ("-Bm", "opcion de Python no permitida: -Bm"),
    ],
)
def test_fila_134_python_c_o_m_sin_carga_util_se_nombra_por_su_causa(
    box, capsys, opt, cause
):
    """Fila 134 / X-pyc: `python -c <script>` ejecutaria el NOMBRE como codigo: violacion."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} {opt} {box.s('comms_alert.py')} --scan --ops-dir {box.ops}"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert cause in out


def test_r2_opcion_python_de_aridad_cero_y_script_estructural_siguen_validos(
    box, capsys
):
    """R2 control: la tabla cerrada admite opciones sin valor antes del script real."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} -I -B {box.s('comms_alert.py')} --scan"
    coord = box.latido("c-r2-control.md", orders)
    sup = box.latido("s-r2-control.md", box.sup_orders())
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0, out


def test_fila_q5_dos_redirecciones_simples_rc_1(box, capsys):
    """Q5 / X-redir-two: dos `>` seguidos (no `>>`) en quota_tick -> rc 1."""
    orders = box.coord_orders()
    orders[4] += f" > {box.root / 'otra.txt'}"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "operador de shell" in out


def test_fila_131_bloque_de_codigo_desde_el_primer_byte_con_y_sin_bom(box, capsys):
    """Fila 131 / X-bom: el latido es SOLO un bloque ``` desde el byte 0; el BOM no lo rompe."""
    cuerpo = "```\n" + "\n".join(box.coord_orders()) + "\n```\n"
    sup = box.latido("s.md", box.sup_orders())
    sin = box.root / "sin_bom.md"
    sin.write_text(cuerpo, encoding="utf-8")
    con = box.root / "con_bom.md"
    con.write_bytes(b"\xef\xbb\xbf" + cuerpo.encode("utf-8"))
    for ruta in (sin, con):
        rc, out = run(box.argv(ruta, sup), capsys)
        assert rc == 0, (ruta.name, out)


def test_fila_146_flag_interno_emit_en_una_orden_es_violacion(box, capsys):
    """Fila 146 / X-emit: `--emit-child` / `--emit` son internos del check: prohibidos."""
    for flag in ("--emit-child", "--emit"):
        orders = box.coord_orders()
        orders[0] += f" {flag}"
        c = box.latido("c.md", orders)
        s = box.latido("s.md", box.sup_orders())
        rc, out = run(box.argv(c, s), capsys)
        assert rc == 1, (flag, out)
        assert "flag interno prohibido" in out


@windows_only
def test_fila_147_opcion_desconocida_de_powershell_antes_de_file_es_violacion(
    box, capsys
):
    """Fila 147 / X-psopt: una opcion de PowerShell fuera de la lista permitida -> rc 1."""
    orders = box.sup_orders()
    orders[0] = orders[0].replace(" -File ", " -Bogus -File ")
    coord, _ = box.good()
    rc, out = run(box.argv(coord, box.latido("s.md", orders)), capsys)
    assert rc == 1, out
    assert "opcion de PowerShell no permitida: -Bogus" in out


def test_fila_134_argumento_suelto_de_python_antes_del_script_es_violacion(box, capsys):
    """Fila 134 / X-pyarg: `python extra <script>` -> rc 1 'argumento de python'."""
    orders = box.coord_orders()
    orders[0] = f"{box.py} extra {box.s('comms_alert.py')} --scan --ops-dir {box.ops}"
    c = box.latido("c.md", orders)
    s = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(c, s), capsys)
    assert rc == 1, out
    assert "primer operando tras las opciones no es un script" in out


def test_fila_149_python_exe_gana_a_flight_python_aunque_el_entorno_sea_otro(
    box, capsys, monkeypatch
):
    """Fila 149 / X-pycli: con FLIGHT_PYTHON apuntando a OTRO python, `--python-exe` manda."""
    otro = box.root / "otro_py"
    otro.mkdir()
    copia = otro / "python.exe"
    shutil.copy2(box.py, copia)
    monkeypatch.setenv(chk.PYTHON_ENV, str(copia))
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 0, out


def test_fila_138_script_staged_nuevo_sin_estar_en_head_es_violacion(box, capsys):
    """Fila 138 / X-head: tracked (indice) pero ausente de HEAD -> rc 1 'no existe en HEAD'."""
    _git(box.motor, "rm", "-q", "--cached", "scripts/flight/quota_tick.py")
    _git(box.motor, "commit", "-q", "-m", "sin quota")
    _git(box.motor, "add", "scripts/flight/quota_tick.py")
    coord, sup = box.good()
    rc, out = run(box.argv(coord, sup), capsys)
    assert rc == 1, out
    assert "el script no existe en HEAD" in out


# ====================================================================== CAJA 3B
# --alert (filas 151-160) y gate de cierre (filas 161-165). Cadena REAL: la orden que arma
# `emit_alert` se parsea con el parser del propio check y se ejecuta con `emit_child_main`
# contra el `comms_alert` REAL en un ops-dir temporal; solo `notify` (el toast) se sustituye.
class _Aviso:
    """Directorio de operacion temporal + `comms_alert` real con el toast simulado."""

    def __init__(self, ops: Path) -> None:
        self.ops = ops
        self.sent: list[tuple[str, str]] = []
        self.cmds: list[list[str]] = []
        self.timeouts: list[object] = []

    def loader(self):
        ca = chk._load_comms_alert()
        assert ca is not None

        def notify(title, message, dry, **kwargs):
            if not dry:
                self.sent.append((title, message))
            return 0

        ca.notify = notify
        return ca

    def runner(self, cmd, **kwargs):
        """Sustituye subprocess.run: ejecuta EN PROCESO el modo --emit-child del check."""
        self.cmds.append(list(cmd))
        self.timeouts.append(kwargs.get("timeout"))
        ns = chk._build_parser().parse_args(cmd[2:])
        rc = chk.emit_child_main(ns, loader=self.loader)
        return subprocess.CompletedProcess(cmd, rc, "", "")

    def emit(self, diag: int, finding: str = "- [x] algo", dry: bool = False) -> bool:
        return chk.emit_alert(
            diag,
            finding,
            ops_dir=str(self.ops),
            flight_dir=str(self.ops),
            dry_run=dry,
            runner=self.runner,
        )

    def state(self) -> dict:
        path = self.ops / "comms_alert_state.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def keys(self) -> set[str]:
        return {k for k in self.state() if k.startswith("event:latido-")}


@pytest.fixture
def aviso(tmp_path) -> _Aviso:
    ops = tmp_path / "opsreal"
    ops.mkdir()
    return _Aviso(ops)


def test_fila_151_comms_alert_se_carga_de_junto_al_check_no_de_ops_dir(aviso):
    """Fila 151 / N117: una copia trampa de comms_alert.py en ops-dir se IGNORA."""
    marca = aviso.ops / "trampa_cargada.txt"
    (aviso.ops / "comms_alert.py").write_text(
        f"from pathlib import Path\nPath({str(marca)!r}).write_text('x')\n",
        encoding="utf-8",
    )
    ca = chk._load_comms_alert()
    assert Path(ca.__file__).resolve() == _SCRIPT.with_name("comms_alert.py").resolve()
    assert aviso.emit(1) is True
    assert not marca.exists()
    assert aviso.keys() == {"event:latido-desviado"}


def test_fila_152_comms_alert_ausente_es_rc_2_con_causa(tmp_path):
    """Fila 152 / N118: sin comms_alert.py junto al check, el hijo sale 2 y nombra la causa."""
    solo = tmp_path / "solo"
    solo.mkdir()
    shutil.copy2(_SCRIPT, solo / _SCRIPT.name)
    ops = tmp_path / "ops2"
    ops.mkdir()
    done = subprocess.run(
        [
            sys.executable,
            str(solo / _SCRIPT.name),
            "--emit-child",
            "--ops-dir",
            str(ops),
            "--emit",
            "latido-desviado",
            "--what",
            "x",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2
    assert "comms_alert.py no se pudo cargar" in done.stderr


def test_fila_152_hijo_roto_sube_el_rc_final_a_2_y_lo_declara(box, capsys, monkeypatch):
    """Fila 152 / N118: diagnostico 1 + aviso imposible -> rc 2 (no el rc 1 del diagnostico)."""
    malo = box.latido("malo.md", ["nada"])
    sup = box.latido("s.md", box.sup_orders())
    original = chk.emit_alert

    def hijo_roto(cmd, **kwargs):
        ns = chk._build_parser().parse_args(cmd[2:])
        rc = chk.emit_child_main(ns, loader=lambda: None)
        return subprocess.CompletedProcess(cmd, rc, "", "")

    monkeypatch.setattr(
        chk, "emit_alert", lambda *a, **k: original(*a, **{**k, "runner": hijo_roto})
    )
    rc, out = run(box.argv(malo, sup, ("--alert", "--ops-dir", str(box.ops))), capsys)
    assert rc == 2
    assert "diag_rc=1 alert=fallido" in out


def test_fila_152_ops_dir_inutilizable_en_el_hijo_es_rc_2(tmp_path, capsys):
    """Fila 152: ops-dir ausente -> OpsDirError del comms_alert real -> rc 2 con causa."""
    ns = chk._build_parser().parse_args(
        ["--emit-child", "--ops-dir", str(tmp_path / "no_existe"), "--emit", "k"]
    )
    assert chk.emit_child_main(ns) == 2
    assert "ops-dir" in capsys.readouterr().err


def test_fila_153_owner_fijo_check_y_nivel_urgente():
    """Fila 153 / N119: el hijo pasa owner='check' y URGENTE a event, nunca None."""
    llamadas: list[tuple] = []

    class Falso:
        class OpsDirError(Exception):
            pass

        @staticmethod
        def configure(ops):
            llamadas.append(("configure", ops))

        @staticmethod
        def event(key, level, title, what, force, dry, owner=None, session_code=None):
            llamadas.append(("event", key, level, title, what, force, dry, owner))
            return 0

        @staticmethod
        def resolve(key, dry=False):
            llamadas.append(("resolve", key, dry))
            return 10

    ns = chk._build_parser().parse_args(
        [
            "--emit-child",
            "--ops-dir",
            "/x",
            "--emit",
            "latido-desviado",
            "--what",
            "w",
            "--resolve",
            "latido-check-roto",
        ]
    )
    assert chk.emit_child_main(ns, loader=lambda: Falso) == 0
    assert llamadas[1] == (
        "event",
        "latido-desviado",
        "URGENTE",
        "Vuelo: latido-desviado",
        "w",
        False,
        False,
        "check",
    )
    assert llamadas[2] == ("resolve", "latido-check-roto", False)


def test_fila_153_el_aviso_real_queda_con_owner_check(aviso):
    """Fila 153 / N119 contra el comms_alert REAL: el registro de estado dice owner 'check'."""
    assert aviso.emit(1) is True
    registro = aviso.state()["event:latido-desviado"]
    assert registro["owner"] == "check" and registro["level"] == "URGENTE"


def test_fila_154_subproceso_con_ejecutable_y_directorios_explicitos():
    """Fila 154 / N120: sys.executable, el fichero del check y --ops-dir/--flight-dir."""
    vistos: list[tuple[list[str], dict]] = []

    def runner(cmd, **kwargs):
        vistos.append((list(cmd), kwargs))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert chk.emit_alert(
        1, "- [c] f", ops_dir="/o", flight_dir="/v", dry_run=False, runner=runner
    )
    cmd, kwargs = vistos[0]
    assert cmd[0] == sys.executable
    assert Path(cmd[1]).resolve() == _SCRIPT.resolve()
    assert cmd[2] == "--emit-child"
    assert cmd[cmd.index("--ops-dir") + 1] == "/o"
    assert cmd[cmd.index("--flight-dir") + 1] == "/v"
    assert cmd[cmd.index("--emit") + 1] == "latido-desviado"
    assert "--dry-run" not in cmd
    assert kwargs["capture_output"] is True and kwargs["check"] is False


def test_fila_154_session_code_llega_al_hijo():
    """BA07 L1/L2: emit_alert propaga --session-code al productor hijo."""
    vistos: list[list[str]] = []

    def runner(cmd, **kwargs):
        vistos.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert chk.emit_alert(
        1,
        "- [c] f",
        ops_dir="/o",
        flight_dir="/v",
        session_code="CO-31",
        dry_run=False,
        runner=runner,
    )
    cmd = vistos[0]
    assert cmd[cmd.index("--session-code") + 1] == "CO-31"


def test_alert_real_pasa_session_code_del_roster_al_hijo(box, capsys, monkeypatch):
    """BA07 L2: el camino --alert lee el roster y lo reenvia al hijo real."""
    box.roster.write_text(
        '{"active_roles":{"orquestador":{"session_code":"CO-31"}}}',
        encoding="utf-8",
    )
    malo = box.latido("malo-session.md", ["nada"])
    sup = box.latido("s.md", box.sup_orders())
    vistos: list[list[str]] = []

    def runner(cmd, **kwargs):
        vistos.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    original = chk.emit_alert
    monkeypatch.setattr(
        chk,
        "emit_alert",
        lambda *args, **kwargs: original(*args, **{**kwargs, "runner": runner}),
    )
    rc, out = run(box.argv(malo, sup, ("--alert", "--ops-dir", str(box.ops))), capsys)
    assert rc == 1 and "alert=ok" in out
    assert vistos[0][vistos[0].index("--session-code") + 1] == "CO-31"


def test_fila_154_sin_ops_dir_no_lanza_nada_y_falla():
    """Fila 154: sin ops-dir el aviso es imposible (False) y no se lanza ningun hijo."""
    llamadas: list = []
    assert (
        chk.emit_alert(
            2,
            "",
            ops_dir=None,
            flight_dir=None,
            dry_run=False,
            runner=lambda *a, **k: llamadas.append(a),
        )
        is False
    )
    assert llamadas == []


def test_fila_154_sin_flight_dir_no_pasa_el_argumento():
    vistos: list[list[str]] = []
    chk.emit_alert(
        1,
        "",
        ops_dir="/o",
        flight_dir=None,
        dry_run=True,
        runner=lambda cmd, **k: (
            vistos.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0)
        ),
    )
    assert "--flight-dir" not in vistos[0] and "--dry-run" in vistos[0]


@windows_only
def test_fila_155_timeout_del_subproceso_es_fallo_del_aviso(box, capsys, monkeypatch):
    """Fila 155 / N121: el hijo recibe un timeout positivo; si vence, rc final 2."""
    recibidos: list[object] = []

    def vence(cmd, **kwargs):
        recibidos.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout") or 0)

    coord, sup = box.good()
    original = chk.emit_alert
    monkeypatch.setattr(
        chk, "emit_alert", lambda *a, **k: original(*a, **{**k, "runner": vence})
    )
    rc, out = run(box.argv(coord, sup, ("--alert", "--ops-dir", str(box.ops))), capsys)
    assert rc == 2 and "diag_rc=0 alert=fallido" in out
    assert isinstance(recibidos[0], (int, float)) and recibidos[0] > 0


def test_fila_155_oserror_al_lanzar_el_hijo_es_fallo_del_aviso():
    def roto(cmd, **kwargs):
        raise OSError("no arranca")

    assert (
        chk.emit_alert(1, "", ops_dir="/o", flight_dir=None, dry_run=False, runner=roto)
        is False
    )


def test_fila_156_rc_1_emite_latido_desviado_urgente_y_no_el_roto(aviso):
    """Fila 156 / N122: el aviso real lleva la clave latido-desviado, no latido-check-roto."""
    assert aviso.emit(1, "- [coordinadora] falta la orden") is True
    assert aviso.keys() == {"event:latido-desviado"}
    assert len(aviso.sent) == 1
    titulo, texto = aviso.sent[0]
    assert titulo == "Vuelo ?"
    assert "latido-desviado" not in titulo
    assert "falta la orden" in texto


def test_fila_157_rc_2_emite_latido_check_roto_y_no_el_desviado(aviso):
    """Fila 157 / N123: el aviso real lleva la clave latido-check-roto."""
    assert aviso.emit(2, "latido ilegible") is True
    assert aviso.keys() == {"event:latido-check-roto"}
    assert aviso.sent[0][0] == "Vuelo ?"
    assert "latido-check-roto" not in aviso.sent[0][0]


def test_fila_158_rc_0_resuelve_ambas_claves(aviso):
    """Fila 158 / N124: tras un rc 0 no queda NINGUNA de las dos claves y no se avisa."""
    ca = aviso.loader()
    ca.configure(str(aviso.ops))
    ca.mark_seen("latido-desviado", "URGENTE", owner="check")
    ca.mark_seen("latido-check-roto", "URGENTE", owner="check")
    assert aviso.keys() == {"event:latido-desviado", "event:latido-check-roto"}
    assert aviso.emit(0) is True
    assert aviso.keys() == set()
    assert aviso.sent == []


def test_fila_159_transiciones_resuelven_la_otra_y_la_recaida_vuelve_a_avisar(aviso):
    """Fila 159 / N125: 1 -> 2 -> 1; cada cambio retira la clave anterior y el regreso avisa."""
    aviso.emit(1)
    assert aviso.keys() == {"event:latido-desviado"}
    aviso.emit(2)
    assert aviso.keys() == {"event:latido-check-roto"}
    aviso.emit(1)
    assert aviso.keys() == {"event:latido-desviado"}
    titles = [t for t, _ in aviso.sent]
    assert titles == ["Vuelo ?", "Vuelo ?", "Vuelo ?"]
    assert all("latido-" not in title for title in titles)


def test_fila_159_mismo_rc_dos_veces_no_repite_el_aviso_inmediato(aviso):
    """El estado real limita la repeticion: dos ticks seguidos con rc 1 dan UN toast."""
    aviso.emit(1)
    aviso.emit(1)
    assert len(aviso.sent) == 1


def test_fila_159_dry_run_no_avisa_ni_guarda_estado(aviso):
    assert aviso.emit(1, dry=True) is True
    assert aviso.sent == [] and aviso.state() == {}


def test_fila_160_aviso_correcto_conserva_el_rc_y_dice_alert_ok(
    box, capsys, monkeypatch
):
    """Fila 160 / N126: con el aviso bien, el rc es el del diagnostico y la salida lo dice."""
    malo = box.latido("malo.md", ["nada"])
    sup = box.latido("s.md", box.sup_orders())
    original = chk.emit_alert
    monkeypatch.setattr(
        chk,
        "emit_alert",
        lambda *a, **k: original(
            *a, **{**k, "runner": lambda c, **kw: subprocess.CompletedProcess(c, 0)}
        ),
    )
    rc, out = run(box.argv(malo, sup, ("--alert", "--ops-dir", str(box.ops))), capsys)
    assert rc == 1
    assert out.rstrip().splitlines()[-1] == "diag_rc=1 alert=ok"


def test_fila_160_fallo_del_aviso_da_max_diag_2_y_alert_fallido(box, capsys):
    """Fila 160 / N126: sin ops-dir el aviso es imposible: rc 2 y 'alert=fallido'."""
    malo = box.latido("malo.md", ["nada"])
    sup = box.latido("s.md", box.sup_orders())
    rc, out = run(box.argv(malo, sup, ("--alert",)), capsys)
    assert rc == 2
    assert out.rstrip().splitlines()[-1] == "diag_rc=1 alert=fallido"


def test_fila_160_na_sin_roster_no_emite_y_dice_omitido(box, capsys, monkeypatch):
    """rc 3 (sin roster): ni emite ni resuelve; salida 'alert=omitido'."""
    llamadas: list = []
    monkeypatch.setattr(chk, "emit_alert", lambda *a, **k: llamadas.append(a))
    rc, out = run(box.argv(roster=False, extra=("--alert",)), capsys)
    assert rc == 3 and llamadas == []
    assert "diag_rc=3 alert=omitido" in out


@pytest.mark.parametrize(
    ("roster_text", "expected"),
    [
        ('{"active_roles":{"orquestador":{"session_code":"CO-31"}}}', "CO-31"),
        ("{", None),
        ('{"active_roles":[]}', None),
        ('{"active_roles":{"orquestador":null}}', None),
        ('{"active_roles":{"orquestador":{"session_code":7}}}', None),
        ('{"active_roles":{"orquestador":{"session_code":"mcp:bad"}}}', None),
    ],
)
def test_alert_roster_session_code_real_y_formas_invalidas(
    box, capsys, monkeypatch, roster_text, expected
):
    """El --alert real lee cada forma de roster y nunca inyecta codigo invalido."""
    box.roster.write_text(roster_text, encoding="utf-8")
    malo = box.latido("malo-roster.md", ["nada"])
    sup = box.latido("s.md", box.sup_orders())
    vistos = {}

    def captura(diag, first, **kwargs):
        vistos.update(kwargs)
        return True

    monkeypatch.setattr(chk, "emit_alert", captura)
    rc, out = run(box.argv(malo, sup, ("--alert", "--ops-dir", str(box.ops))), capsys)
    assert rc in {1, 2}
    assert "alert=ok" in out
    assert vistos["session_code"] == expected


def test_alert_roster_ausente_no_inyecta_session_code(box, capsys, monkeypatch):
    """El --alert real conserva el aviso aunque el roster declarado no exista."""
    box.roster.unlink()
    malo = box.latido("malo-roster-ausente.md", ["nada"])
    sup = box.latido("s.md", box.sup_orders())
    vistos = {}
    monkeypatch.setattr(
        chk, "emit_alert", lambda diag, first, **kwargs: vistos.update(kwargs) or True
    )
    rc, out = run(box.argv(malo, sup, ("--alert", "--ops-dir", str(box.ops))), capsys)
    assert rc == 2 and "alert=ok" in out
    assert vistos["session_code"] is None


@windows_only
def test_fila_160_el_ops_dir_y_flight_dir_pueden_venir_del_entorno(
    box, capsys, monkeypatch
):
    """--alert toma FLIGHT_OPS_DIR / FLIGHT_DIR del entorno si no hay argumento."""
    vistos: dict = {}

    def espia(diag, first, **kwargs):
        vistos.update(kwargs)
        return True

    monkeypatch.setattr(chk, "emit_alert", espia)
    monkeypatch.setenv(chk.OPS_DIR_ENV, "/env/ops")
    monkeypatch.setenv(chk.FLIGHT_DIR_ENV, "/env/vuelo")
    coord, sup = box.good()
    rc, _ = run(box.argv(coord, sup, ("--alert",)), capsys)
    assert rc == 0
    assert vistos["ops_dir"] == "/env/ops" and vistos["flight_dir"] == "/env/vuelo"


def test_fila_160_real_subproceso_dry_run_de_extremo_a_extremo(box, tmp_path):
    """Subproceso REAL del check con --alert --dry-run: rc 1, 'alert=ok', sin estado escrito."""
    malo = box.latido("malo.md", ["nada"])
    sup = box.latido("s.md", box.sup_orders())
    done = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            *box.argv(malo, sup, ("--alert", "--dry-run", "--ops-dir", str(box.ops))),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.rstrip().splitlines()[-1] == "diag_rc=1 alert=ok"
    assert not (box.ops / "comms_alert_state.json").exists()


# ------------------------------------------------------------------ gate de cierre (161-165)
@pytest.fixture
def rosterf(tmp_path) -> str:
    """Un roster que EXISTE (el paso se salta con un roster declarado y ausente)."""
    path = tmp_path / "flight_roster.json"
    path.write_text("{}", encoding="utf-8")
    return str(path)


class _Res:
    def __init__(self, rc: int, out: str = "", err: str = "") -> None:
        self.returncode, self.stdout, self.stderr = rc, out, err


def _gate(fn, roster, dry_run=False, latidos=None):
    llamadas: list = []

    def run_script(nombre, args, cwd, timeout=None):
        llamadas.append((nombre, args, timeout))
        return fn()

    r = step_latido_alert_wiring(
        Path("."),
        dry_run,
        roster_path=roster,
        latido_files=latidos,
        run_script_fn=run_script,
        process_diagnostic_fn=lambda res: f"diag:{res.stdout}{res.stderr}",
        step_result_cls=StepResult,
    )
    return r, llamadas


def test_fila_161_dry_run_es_skip_no_bloqueante_y_no_ejecuta(rosterf):
    """Fila 161 / N127: en dry-run el check NO se lanza y el paso lo declara."""
    r, llamadas = _gate(lambda: _Res(0), rosterf, dry_run=True)
    assert llamadas == []
    assert (r.status, r.blocking) == ("SKIP", False)
    assert "dry-run" in r.detail and "not verified" in r.detail


def test_fila_162_rc_0_pass_bloqueante(rosterf):
    """Fila 162 / N128."""
    r, _ = _gate(lambda: _Res(0, "latido-check: OK"), rosterf)
    assert (r.name, r.status, r.blocking) == ("latido_alert_wiring", "PASS", True)


def test_fila_162_rc_3_es_skip_no_bloqueante(rosterf):
    r, _ = _gate(lambda: _Res(3, "N/A"), rosterf)
    assert (r.status, r.blocking) == ("SKIP", False)


def test_r7_roster_ausente_incluye_reproduccion_y_revalidacion(tmp_path):
    """R7 minor: el roster declarado ausente mantiene el contrato self-service."""
    r, llamadas = _gate(
        lambda: _Res(0),
        str(tmp_path / "missing.json"),
        latidos=["coordinadora=/l/c.md"],
    )
    assert llamadas == []
    assert r.status == "FAIL" and r.blocking is True
    assert "COMO reproducirlo:" in r.detail
    assert "COMO revalidar:" in r.detail


@pytest.mark.parametrize("rc", [1, 2, 4, 127])
def test_fila_162_cualquier_otro_rc_es_fail_bloqueante(rc, rosterf):
    """Fila 162 / N128: rc 1 (violacion), 2 (ilegible) y desconocidos NUNCA pasan."""
    r, _ = _gate(
        lambda: _Res(rc, "latido-check: VIOLACION\n- [coordinadora] falta"), rosterf
    )
    assert (r.status, r.blocking) == ("FAIL", True)
    assert f"exit {rc}" in r.detail


def test_fila_162_fail_dice_que_falla_como_reproducirlo_y_como_revalidar(rosterf):
    """O1-O5: el FAIL es self-service (QUE / COMO reproducirlo / COMO revalidar)."""
    salida = (
        "latido-check: VIOLACION\n- [coordinadora] falta la orden --scan\n"
        "reproducir y revalidar: python scripts/flight/check_latido_alert_wiring.py --x"
    )
    r, _ = _gate(lambda: _Res(1, salida), rosterf, latidos=["coordinadora=/l/c.md"])
    assert "QUE falla: - [coordinadora] falta la orden --scan" in r.detail
    assert (
        "COMO reproducirlo: python scripts/flight/check_latido_alert_wiring.py --x"
        in r.detail
    )
    assert "COMO revalidar" in r.detail


def test_fila_162_fail_sin_linea_de_reproduccion_la_reconstruye_con_los_mismos_argumentos(
    rosterf,
):
    r, _ = _gate(
        lambda: _Res(2, "", "boom"),
        rosterf,
        latidos=["coordinadora=/l/c.md", "supervisora=/l/s.md"],
    )
    assert "QUE falla: diag:boom" in r.detail
    assert "scripts/flight/check_latido_alert_wiring.py" in r.detail
    assert "--motor-root" in r.detail
    assert "--python-exe" in r.detail
    assert "--git-exe" in r.detail
    assert subprocess.list2cmdline(["--roster-path", rosterf]) in r.detail
    assert (
        subprocess.list2cmdline(["--latido-file", "coordinadora=/l/c.md"]) in r.detail
    )
    assert subprocess.list2cmdline(["--latido-file", "supervisora=/l/s.md"]) in r.detail


def test_r2_repro_del_gate_fija_motor_python_y_git_y_escapa_argumentos(rosterf):
    """R2 MINOR-2: la reproduccion no depende de PATH ni pierde rutas con espacios."""
    import scripts.closeout_steps.gates as gates

    command = gates._latido_repro_command(
        str(rosterf), ["coordinadora=C:/latidos/con espacio/c.md"]
    )
    assert "--motor-root" in command
    assert "--python-exe" in command
    assert "--git-exe" in command
    assert '"coordinadora=C:/latidos/con espacio/c.md"' in command


def test_fila_162_roster_declarado_inexistente_es_skip_y_no_lanza_el_check(tmp_path):
    """BA03 H1: roster declarado ausente es FAIL bloqueante, nunca SKIP fail-open."""
    r, llamadas = _gate(lambda: _Res(1), str(tmp_path / "no_existe.json"))
    assert llamadas == []
    assert (r.status, r.blocking) == ("FAIL", True)
    assert "not verified" in r.detail and "no_existe.json" in r.detail


def test_fila_163_timeout_de_60s_es_fail_bloqueante_con_detalle(rosterf):
    """Fila 163 / N129: el paso pide timeout=60 y, si vence, FAIL bloqueante."""

    def vence():
        raise subprocess.TimeoutExpired("x", 60)

    r, llamadas = _gate(vence, rosterf)
    assert llamadas[0][2] == 60
    assert (r.status, r.blocking) == ("FAIL", True)
    assert "agoto 60s" in r.detail and "COMO reproducirlo" in r.detail


def test_fila_163_script_ausente_es_fail_bloqueante_con_detalle(rosterf):
    def falta():
        raise FileNotFoundError("x")

    r, _ = _gate(falta, rosterf)
    assert (r.status, r.blocking) == ("FAIL", True)
    assert "no existe en scripts/" in r.detail and "COMO revalidar" in r.detail


def test_fila_163_oserror_es_fail_bloqueante_con_detalle(rosterf):
    """MINOR-4: un OSError de ejecucion queda diagnosticado y es bloqueante."""

    def falla():
        raise OSError("permiso denegado")

    r, _ = _gate(falla, rosterf, latidos=["coordinadora=/l/c.md"])
    assert (r.status, r.blocking) == ("FAIL", True)
    assert "OSError" in r.detail and "permiso denegado" in r.detail
    assert "COMO reproducirlo" in r.detail and "COMO revalidar" in r.detail


def test_fila_164_con_roster_y_sin_latidos_el_check_real_da_fail_en_el_gate(box):
    """Fila 164 / N130: el check REAL con roster y sin latidos sale 1 y el gate lo hace FAIL."""
    done = subprocess.run(
        [sys.executable, str(_SCRIPT), *box.argv()],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 1, done.stdout + done.stderr
    r, _ = _gate(lambda: _Res(done.returncode, done.stdout), str(box.roster))
    assert (r.status, r.blocking) == ("FAIL", True)


def test_fila_164_sin_roster_el_check_real_da_rc_3_y_el_gate_skip(box):
    done = subprocess.run(
        [sys.executable, str(_SCRIPT), "--motor-root", str(box.motor)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={
            k: v
            for k, v in os.environ.items()
            if k not in (chk.ROSTER_ENV, chk.LATIDO_ENV)
        },
    )
    assert done.returncode == 3, done.stdout + done.stderr
    r, _ = _gate(lambda: _Res(done.returncode, done.stdout), None)
    assert (r.status, r.blocking) == ("SKIP", False)


def test_fila_165_el_gate_pasa_roster_y_cada_latido_al_script(rosterf):
    """Fila 165 / N131: --roster-path y un --latido-file por especificacion llegan al check."""
    _, llamadas = _gate(
        lambda: _Res(0),
        rosterf,
        latidos=["coordinadora=/l/c.md", "supervisora=/l/s.md"],
    )
    assert llamadas == [
        (
            "flight/check_latido_alert_wiring.py",
            [
                "--roster-path",
                rosterf,
                "--latido-file",
                "coordinadora=/l/c.md",
                "--latido-file",
                "supervisora=/l/s.md",
            ],
            60,
        )
    ]


def test_fila_165_sin_roster_ni_latidos_no_pasa_argumentos():
    _, llamadas = _gate(lambda: _Res(3), None, latidos=None)
    assert llamadas[0][1] == []


def _closeout_aislado(tmp_path, monkeypatch, **kwargs):
    """run_closeout con los pasos previos sustituidos; devuelve (rc, lo que vio el paso)."""
    import scripts.session_closeout as sc

    wp_dir = tmp_path / ".agent" / "collaboration"
    wp_dir.mkdir(parents=True)
    (wp_dir / "work_plan.md").write_text(
        "# Work Plan\n\n## Metadata\n- **ID:** WOT-2026-0001\n", encoding="utf-8"
    )
    visto: dict = {"n": 0}

    def falso(project_root, dry_run, *, roster_path=None, latido_files=None):
        visto.update(
            n=visto["n"] + 1,
            dry_run=dry_run,
            roster_path=roster_path,
            latido_files=latido_files,
        )
        return StepResult(
            name="latido_alert_wiring",
            status=visto.get("status", "PASS"),
            blocking=True,
        )

    visto["status"] = kwargs.pop("status", "PASS")
    roster_status = kwargs.pop("roster_status", "PASS")
    monkeypatch.setattr(sc, "_step_latido_alert_wiring", falso)
    monkeypatch.setattr(
        sc,
        "_step_quota_index_drift",
        lambda *a, **k: StepResult(name="quota", status="SKIP"),
    )
    monkeypatch.setattr(
        sc,
        "_step_roster_matches_acting_thread",
        lambda *a, **k: StepResult(name="roster", status=roster_status, blocking=True),
    )
    monkeypatch.setattr(
        sc,
        "_step_prepush_check",
        lambda *a, **k: StepResult(name="prepush_check", status="PASS", blocking=True),
    )
    visto.update(siguiente=0, report=None)

    def siguiente(*a, **k):
        visto["siguiente"] += 1
        return StepResult(name="integration_receipts", status="SKIP")

    original_report = sc._generate_report

    def captura(report, project_root):
        visto["report"] = report
        return original_report(report, project_root)

    monkeypatch.setattr(sc, "_step_integration_receipts", siguiente)
    monkeypatch.setattr(sc, "_generate_report", captura)
    rc = sc.run_closeout(tmp_path, dry_run=False, acting_thread="mcp:t", **kwargs)
    return rc, visto


def test_fila_165_run_closeout_entrega_roster_y_latidos_al_paso(tmp_path, monkeypatch):
    """Fila 165 / N131: la plomeria de run_closeout al paso conserva ambos argumentos."""
    rc, visto = _closeout_aislado(
        tmp_path,
        monkeypatch,
        roster_path="/fake/roster.json",
        latido_files=["coordinadora=/l/c.md"],
    )
    assert visto["n"] == 1 and rc == 0
    assert visto["roster_path"] == "/fake/roster.json"
    assert visto["latido_files"] == ["coordinadora=/l/c.md"]
    assert visto["dry_run"] is False


def test_fila_165_un_fail_del_paso_corta_el_cierre_con_rc_1(tmp_path, monkeypatch):
    """El paso es BLOQUEANTE: un FAIL aborta el cierre (rc 1) antes de los pasos siguientes."""
    rc, visto = _closeout_aislado(tmp_path, monkeypatch, status="FAIL")
    assert visto["n"] == 1 and rc == 1


def test_fila_165_cli_latido_file_repetible_llega_a_run_closeout(tmp_path, monkeypatch):
    """Fila 165 / N131: `--latido-file` (repetible) del CLI llega como lista a run_closeout."""
    import scripts.session_closeout as sc

    capturado: dict = {}

    def falso_run(**kwargs):
        capturado.update(kwargs)
        return 0

    monkeypatch.setattr(sc, "run_closeout", falso_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "session_closeout.py",
            "--project-root",
            str(tmp_path),
            "--roster-path",
            "/r.json",
            "--latido-file",
            "coordinadora=/l/c.md",
            "--latido-file",
            "supervisora=/l/s.md",
        ],
    )
    assert sc.main() == 0
    assert capturado["latido_files"] == ["coordinadora=/l/c.md", "supervisora=/l/s.md"]
    assert capturado["roster_path"] == "/r.json"


def test_fila_165_cli_sin_latido_file_pasa_none(tmp_path, monkeypatch):
    import scripts.session_closeout as sc

    capturado: dict = {}
    monkeypatch.setattr(sc, "run_closeout", lambda **kw: capturado.update(kw) or 0)
    monkeypatch.setattr(
        sys, "argv", ["session_closeout.py", "--project-root", str(tmp_path)]
    )
    assert sc.main() == 0
    assert capturado["latido_files"] is None


@windows_only
def test_fila_165_flight_latido_files_del_entorno_llega_al_check_real(box, monkeypatch):
    """La variable FLIGHT_LATIDO_FILES que hereda el hijo del cierre alimenta al check REAL."""
    coord, sup = box.good()
    env = dict(os.environ)
    env[chk.LATIDO_ENV] = f"coordinadora={coord};supervisora={sup}"
    done = subprocess.run(
        [sys.executable, str(_SCRIPT), *box.argv()],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )
    assert done.returncode == 0, done.stdout + done.stderr


# ---------------------------------------------------------------- 3B: supervivientes de la 1a pasada
def _ca_falso(event_rc: int = 0, resolve_rc: int = 10):
    """`comms_alert` falso con los rc que se le pidan (para ramas que el real no produce)."""

    class Falso:
        class OpsDirError(Exception):
            pass

        @staticmethod
        def configure(ops):
            return ops

        @staticmethod
        def event(key, level, title, what, force, dry, owner=None, session_code=None):
            return event_rc

        @staticmethod
        def resolve(key, dry=False):
            return resolve_rc

    return Falso


@pytest.mark.parametrize(
    "diag,esperado",
    [
        (0, (None, ["latido-desviado", "latido-check-roto"])),
        (1, ("latido-desviado", ["latido-check-roto"])),
        (2, ("latido-check-roto", ["latido-desviado"])),
        (3, (None, [])),
        (4, (None, [])),
    ],
)
def test_fila_159_tabla_de_transicion_exacta(diag, esperado):
    """Fila 159 / X-na-alert: la tabla emite/resuelve solo para 0, 1 y 2; el resto no hace nada."""
    assert chk._alert_plan(diag) == esperado


def test_fila_160_diagnostico_sin_tabla_no_lanza_ningun_hijo():
    """Fila 160 / X-na-alert: un rc que no es de la tabla no avisa ni lanza un subproceso."""
    llamadas: list = []
    ok = chk.emit_alert(
        3,
        "",
        ops_dir="/o",
        flight_dir=None,
        dry_run=False,
        runner=lambda *a, **k: llamadas.append(a),
    )
    assert ok is True and llamadas == []


@pytest.mark.parametrize("event_rc,esperado", [(0, 0), (10, 0), (2, 2), (1, 2)])
def test_fila_153_rc_del_hijo_segun_el_rc_de_event(event_rc, esperado):
    """Fila 153 / X-child-rc: un aviso que falla (rc 2/1) hace salir 2 al hijo; 0/10 salen 0."""
    ns = chk._build_parser().parse_args(
        ["--emit-child", "--ops-dir", "/x", "--emit", "latido-desviado"]
    )
    assert (
        chk.emit_child_main(ns, loader=lambda: _ca_falso(event_rc=event_rc)) == esperado
    )


@pytest.mark.parametrize("resolve_rc,esperado", [(0, 0), (10, 0), (2, 2), (1, 2)])
def test_fila_158_rc_del_hijo_segun_el_rc_de_resolve(resolve_rc, esperado):
    """Fila 158 / X-child-resolve: un resolve que devuelve 2/1 hace salir 2 al hijo."""
    ns = chk._build_parser().parse_args(
        ["--emit-child", "--ops-dir", "/x", "--resolve", "latido-desviado"]
    )
    assert (
        chk.emit_child_main(ns, loader=lambda: _ca_falso(resolve_rc=resolve_rc))
        == esperado
    )


def test_fila_151_la_variable_flight_ops_dir_tampoco_cambia_de_donde_se_carga(
    aviso, monkeypatch
):
    """Fila 151 / N117: con FLIGHT_OPS_DIR apuntando a un ops-dir con copia trampa, se ignora."""
    marca = aviso.ops / "trampa_env.txt"
    (aviso.ops / "comms_alert.py").write_text(
        f"from pathlib import Path\nPath({str(marca)!r}).write_text('x')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(chk.OPS_DIR_ENV, str(aviso.ops))
    ca = chk._load_comms_alert()
    assert Path(ca.__file__).resolve() == _SCRIPT.with_name("comms_alert.py").resolve()
    assert not marca.exists()


def test_fila_165_un_fail_no_deja_correr_los_pasos_siguientes(tmp_path, monkeypatch):
    """Fila 165 / X-sc-earlyret: tras un FAIL del paso NO corre el siguiente; con PASS si."""
    rc, visto = _closeout_aislado(tmp_path, monkeypatch, status="FAIL")
    assert rc == 1 and visto["siguiente"] == 0


def test_r2_roster_precede_y_bloquea_el_paso_de_latidos(tmp_path, monkeypatch):
    """R2 MINOR-1: el roster FAIL corta antes de invocar el gate de latidos."""
    rc, visto = _closeout_aislado(tmp_path, monkeypatch, roster_status="FAIL")
    assert rc == 1
    assert visto["n"] == 0


def test_fila_165_con_pass_corre_el_paso_siguiente(tmp_path, monkeypatch):
    rc, visto = _closeout_aislado(tmp_path / "ok", monkeypatch)
    assert rc == 0 and visto["siguiente"] == 1


def test_fila_165_el_paso_queda_en_el_informe_del_cierre(tmp_path, monkeypatch):
    """Fila 165 / X-sc-append: el StepResult del paso figura en report.steps (FAIL y PASS)."""
    _, visto = _closeout_aislado(tmp_path / "f", monkeypatch, status="FAIL")
    nombres = [st.name for st in visto["report"].steps]
    assert "latido_alert_wiring" in nombres


def test_fila_165_el_envoltorio_reenvia_roster_y_latidos_al_paso(tmp_path, monkeypatch):
    """Fila 165 / N131d / X-sc-wrap: `_step_latido_alert_wiring` de session_closeout reenvia
    --roster-path y cada --latido-file al check (verifica el SUBPROCESO, no un doble)."""
    import scripts.session_closeout as sc

    roster = tmp_path / "roster.json"
    roster.write_text("{}", encoding="utf-8")
    vistos: list = []

    def run_script(nombre, args, cwd, timeout=None):
        vistos.append((nombre, args, timeout))
        return subprocess.CompletedProcess([nombre], 0, "ok", "")

    monkeypatch.setattr(sc, "_run_script", run_script)
    res = sc._step_latido_alert_wiring(
        tmp_path,
        False,
        roster_path=str(roster),
        latido_files=["coordinadora=/l/c.md"],
    )
    assert res.status == "PASS" and res.blocking is True
    assert vistos == [
        (
            "flight/check_latido_alert_wiring.py",
            ["--roster-path", str(roster), "--latido-file", "coordinadora=/l/c.md"],
            60,
        )
    ]
