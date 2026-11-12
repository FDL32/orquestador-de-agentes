#!/usr/bin/env python3
"""WOT-2026-153k: barrera cableada del latido -- falla si un latido no invoca el mecanismo de avisos del motor.

Un latido es un FICHERO de texto que una sesion ejecuta a mano cada tick. Si apunta a una
copia vieja de un script (p. ej. fuera del motor), a un interprete por PATH, o le faltan las
ordenes de aviso, el vuelo se queda mudo sin que nada lo diga. Este check LEE el fichero del
latido (no la copia viva de la tarea en T3: limite declarado) y verifica que cada orden
obligatoria de su rol exista, apunte a un script TRACKED, igual a HEAD y con el indice limpio
del motor autorizado, y use el interprete fijado.

Before: ``--roster-path`` o ``FLIGHT_ROSTER_PATH`` (el MISMO roster que decide el N/A del gate
    de roster); ``--latido-file ROL=RUTA`` (repetible) o ``FLIGHT_LATIDO_FILES`` (pares
    ``ROL=RUTA`` separados por ``;``; la CLI gana, no se mezclan), con ROL en
    ``coordinadora`` | ``supervisora``. La base de las rutas relativas del CHECK es
    ``--motor-root`` (por defecto la raiz del propio check), NUNCA el cwd.
During: lee cada latido (utf-8-sig estricto), extrae las ordenes (codigo en linea o bloque
    ```; la prosa no cuenta), las tokeniza (comillas, operadores de shell) y comprueba por
    orden: interprete ABSOLUTO e igual al fijado (Python: ``--python-exe`` > ``FLIGHT_PYTHON`` >
    ``<motor-root>/.venv``; PowerShell: ``%SystemRoot%/System32/WindowsPowerShell/v1.0``), script
    ABSOLUTO que resuelve (strict, enlaces incluidos) DENTRO de ``<motor-root>/scripts/flight``,
    sin UNC, sin ``tmp_or8``, tracked, igual a HEAD y sin cambios preparados (git SIEMPRE con
    ``--``), denylist (``-SimulateToastFailure``, ``-EncodedCommand`` y sus prefijos,
    ``-Command`` antes de ``-File``), y despues del script solo parametros declarados por el productor,
    ``-ExecutionPolicy Bypass``, ``-c``/``-m`` de Python, flags internos ``--emit*``) y
    redirecciones (solo UN ``> ruta`` final, y solo en ``quota_tick.py``). Luego exige el
    inventario obligatorio del rol (cada item lo cubre UNA orden VALIDA).
After: rc 0 todo correcto; 1 violacion (rol u orden obligatoria que falta, ruta fuera del
    motor, no tracked, distinto de HEAD...); 2 ILEGIBLE (latido que no se lee, git o interprete que
    no responden, roster declarado e ilegible, error de uso); 3 N/A solo si no hay roster. Con
    roster y sin latidos = 1; una lista parcial nunca es N/A. Si hay ILEGIBLE y violacion, gana 2.
    Con ``--alert`` emite (subproceso con ``sys.executable``) ``latido-desviado`` (rc 1) o
    ``latido-check-roto`` (rc 2) URGENTE con owner ``check`` y resuelve la otra clave; rc 0
    resuelve ambas; rc 3 no emite ni resuelve. Si el aviso falla el rc final es max(diag, 2) y la
    ultima linea lleva ``diag_rc=<n> alert=ok|fallido|omitido``.

Limites declarados: (a) los roles los declara el invocador; (b) se mide el FICHERO, no la copia que
T3 ejecuta; (c) con ``core.autocrlf`` una diferencia SOLO de finales de linea no cambia el hash
que compara git (no se detecta); (d) no se exige ``--ops-dir`` en las ordenes del inventario
(``FLIGHT_OPS_DIR`` lo cubre y comms_alert falla en voz alta); (e) B1 (sonda en
``collect_system_health.py``) no existe: lo cubren el gate de cierre (A) y este check en cada tick (B2);
(f) ``_is_candidate`` descarta ordenes que no citan un script del inventario ni un interprete
conocido; (g) los valores de
retorno de latido están limitados al rango rc 0-255, por lo que los RC negativos no son representables.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple


EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_UNREADABLE = 2
EXIT_NA = 3

ROLES = ("coordinadora", "supervisora")
LATIDO_ENV = "FLIGHT_LATIDO_FILES"
ROSTER_ENV = "FLIGHT_ROSTER_PATH"
PYTHON_ENV = "FLIGHT_PYTHON"
OPS_DIR_ENV = "FLIGHT_OPS_DIR"
FLIGHT_DIR_ENV = "FLIGHT_DIR"
MAX_LATIDO_BYTES = 2 * 1024 * 1024
GIT_TIMEOUT_S = 30
EMIT_TIMEOUT_S = 30
KEY_DESVIADO = "latido-desviado"
KEY_ROTO = "latido-check-roto"
ALERT_OWNER = "check"
SELF_NAME = "check_latido_alert_wiring.py"

# Inventario de scripts del mecanismo (basename en minusculas) y de interpretes reconocibles.
_SCRIPTS = (
    "comms_alert.py",
    "flight_stall_check.py",
    "quota_tick.py",
    "tick_trace.py",
    "notify_user.ps1",
    SELF_NAME,
)
# (script, flags exigidos, flags prohibidos): lo cubre UNA orden valida con ese script.
# D2: tick_trace es OBLIGATORIO para la coordinadora, no solo permitido; sin la
# linea la traza falta en silencio y el DoD de medicion de dos ticks consecutivos
# no puede observarse ni verificarse.
_INVENTORY: dict[str, tuple[tuple[str, frozenset[str], frozenset[str]], ...]] = {
    "coordinadora": (
        ("comms_alert.py", frozenset({"--scan"}), frozenset()),
        ("comms_alert.py", frozenset({"--event"}), frozenset()),
        (
            "flight_stall_check.py",
            frozenset(),
            frozenset({"--self-check", "--heartbeat-check"}),
        ),
        (
            "flight_stall_check.py",
            frozenset({"--self-check"}),
            frozenset({"--heartbeat-check"}),
        ),
        ("quota_tick.py", frozenset(), frozenset()),
        (
            "tick_trace.py",
            frozenset(
                {
                    "--ops-dir",
                    "--coordinator",
                    "--roster-sha12",
                    "--guard-rc",
                    "--quota-rc",
                    "--quota-summary",
                }
            ),
            frozenset({"--ts"}),
        ),
        (SELF_NAME, frozenset({"--alert"}), frozenset()),
    ),
    "supervisora": (
        ("notify_user.ps1", frozenset(), frozenset()),
        ("quota_tick.py", frozenset(), frozenset()),
    ),
}
_OPERATORS = (">>", "&>", "&&", ">", "|", ";", "&", "<")
_DEV_PREFIX_RE = re.compile(r"\\\\\?\\[A-Za-z]:")
_PLACEHOLDER_RE = re.compile(r"<[^<>\s|&;\"']+>")
_INLINE_RE = re.compile(r"`([^`\n]+)`")
_PS_FLAGS = {"noprofile", "noninteractive", "nologo", "noexit"}
_PS_FLAG_MIN_PREFIX = {"noninteractive": 4}
_PS_NO_VALUE = {"sta", "mta"}
_PS_WITH_VALUE_PREFIXES = ("windowstyle",)
_PS_EXECUTION_POLICIES = frozenset({"bypass", "remotesigned", "unrestricted"})
_PS_WINDOW_STYLES = frozenset({"normal", "hidden", "minimized", "maximized"})
_PYTHON_NO_VALUE_OPTIONS = frozenset(
    {"-I", "-B", "-E", "-s", "-S", "-u", "-O", "-OO", "-q", "-v", "-b", "-d"}
)
_PYTHON_VALUE_OPTIONS = frozenset({"-W", "-X"})
_FORBIDDEN_SWITCH = "simulatetoastfailure"

# Soundness: todo lo que el check acepta debe ser ejecutable por el productor.
# Las diferencias inversas son politica deliberada, nunca igualdad accidental.
_POLICY_REJECTIONS = {
    "--dry-run": "silencia avisos y deja B2 sin cubrir",
    "-c": "ejecuta codigo inline en vez de un script del inventario",
    "-m": "ejecuta un modulo en vez de un script del inventario",
    "shell-operator": "los latidos no delegan operadores al shell",
    "powershell-denylist": "la denylist evita suprimir o desviar avisos",
}


class _OptionSpec(NamedTuple):
    arity: bool
    required: bool
    repeatable: bool
    nargs: object = None
    choices: tuple[str, ...] | None = None
    type_name: str | None = None
    mutex: int | None = None
    unsupported: tuple[str, ...] = ()
    empty_allowed: bool | None = None


def _load_tick_trace_contract() -> tuple[tuple[str, ...], object, object]:
    """Carga el esquema y validadores reales del productor tick_trace.

    Before: ``scripts/flight/tick_trace.py`` existe junto a este checker.
    During: importa el modulo real sin ejecutar su CLI y obtiene ``FIELDS``,
    ``_parse_rc`` y ``_parse_unmeasured``.
    After: devuelve el esquema y las funciones productoras. Puede lanzar ``RuntimeError``
    si falta el fichero, ocurre una excepcion durante la importacion o el contrato esta
    incompleto; ``AttributeError`` si falta un atributo del productor; o ``TypeError`` si
    ``FIELDS`` no es iterable. La defensa ``spec is None or spec.loader is None`` tambien
    produce ``RuntimeError``, pero es un limite no alcanzable por entrada de usuario y no
    se prueba. El bloque de inicializacion del modulo captura esas excepciones, las guarda
    en ``_TICK_TRACE_CONTRACT_ERROR`` y las publica mediante ``run_check`` como metadata
    ilegible con rc 2.
    """
    path = Path(__file__).resolve().with_name("tick_trace.py")
    spec = importlib.util.spec_from_file_location("tick_trace_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se puede cargar parser: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RuntimeError(f"no se puede cargar contrato: {path}") from exc
    fields = tuple(module.FIELDS)
    parse_rc = module._parse_rc
    parse_unmeasured = module._parse_unmeasured
    if not fields or not callable(parse_rc) or not callable(parse_unmeasured):
        raise RuntimeError(f"contrato incompleto: {path}")
    return fields, parse_rc, parse_unmeasured


def _unsupported_spec_details(spec: _OptionSpec) -> tuple[str, ...]:
    """Enumera metadatos del productor que el checker aun no puede ejecutar."""
    details = set(spec.unsupported)
    if spec.choices is not None:
        details.add("choices")
    if spec.type_name is not None:
        details.add("type")
    if spec.mutex is not None:
        details.add("mutex")
    if spec.nargs not in (None, 0, "?"):
        details.add("nargs")
    return tuple(sorted(details))


_SCRIPT_OPTION_META: dict[str, dict[str, _OptionSpec]] = {}
_SCRIPT_OPTIONS: dict[str, dict[str, bool]] = {}
_FORBIDDEN_DRY_RUN = "--dry-run"


class UsageError(Exception):
    """Error de uso de la CLI (rol desconocido, duplicado, formato): rc 2 con causa."""


class Unreadable(Exception):  # noqa: N818 - nombre del contrato: rc 2 = ILEGIBLE
    """No se puede VERIFICAR algo (fichero, git, interprete): rc 2, nunca un pase."""


class _Finding:
    """Un hallazgo: ``kind`` 'V' (violacion, rc 1) o 'U' (ilegible, rc 2)."""

    def __init__(self, kind: str, role: str, where: str, text: str) -> None:
        self.kind = kind
        self.role = role
        self.where = where
        self.text = text

    def render(self) -> str:
        """Linea de salida del hallazgo."""
        return f"  - [{self.kind}] {self.role}{self.where}: {self.text}"


# ----------------------------------------------------------------------------- rutas
def _norm(raw: str) -> str:
    """Barras unificadas a ``/`` (para clasificar UNC y comparar texto)."""
    return raw.replace("\\", "/")


def is_unc(raw: str) -> bool:
    """True si ``raw`` es una ruta de red o de dispositivo que NO es ``\\\\?\\X:``.

    Before: ``raw`` es texto. During: unifica barras y descarta el prefijo local
    ``//?/X:``. After: True para ``\\\\h\\s``, ``//h/s``, ``\\\\?\\UNC\\..``, ``//./..``;
    resolver una de esas rutas consulta la red, por eso se rechazan ANTES de resolver.
    """
    text = _norm(raw)
    if not text.startswith("//"):
        return False
    return re.match(r"//\?/[A-Za-z]:(/|$)", text) is None


def _canon(path: Path | str) -> str:
    """Forma comparable: sin prefijo ``\\\\?\\X:``, normalizada y en minusculas en Windows."""
    text = str(path)
    if re.match(r"\\\\\?\\[A-Za-z]:", text):
        text = text[4:]
    return os.path.normcase(os.path.normpath(text))


def _contained(child: Path, parent: Path) -> bool:
    """True si ``child`` esta en ``parent`` (o es igual) tras canonizar ambos."""
    c, p = _canon(child), _canon(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def _is_abs(raw: str) -> bool:
    """Ruta absoluta de la plataforma (con ``/`` o ``\\``) y no UNC."""
    return not is_unc(raw) and Path(raw).is_absolute()


def _resolve_strict(raw: str, what: str) -> Path:
    """Resuelve ``raw`` (absoluto, no UNC) con strict; lanza ``Unreadable`` con la causa."""
    if is_unc(raw):
        raise Unreadable(f"{what} en ruta de red/dispositivo (UNC) no admitida: {raw}")
    if not Path(raw).is_absolute():
        raise Unreadable(f"{what} debe ser una ruta absoluta: {raw}")
    try:
        return Path(raw).resolve(strict=True)
    except (OSError, ValueError, RuntimeError) as exc:
        raise Unreadable(
            f"{what} no existe o no se puede resolver: {raw} ({type(exc).__name__})"
        ) from exc


# ----------------------------------------------------------------------------- entrada
def parse_latido_specs(
    cli_specs: list[str] | None, environ: dict[str, str] | None = None
) -> dict[str, str]:
    """Convierte ``ROL=RUTA`` (CLI repetible o ``FLIGHT_LATIDO_FILES``) en ``{rol: ruta}``.

    Before: ``cli_specs`` lista (o None); ``environ`` mapping (por defecto ``os.environ``).
    During: la CLI gana (no se mezclan); el entorno se separa por ``;`` ignorando vacios.
    After: devuelve el dict; ``UsageError`` si falta ``=``, el rol no es ``coordinadora`` o
        ``supervisora``, la ruta esta vacia o un rol se repite.
    """
    env = os.environ if environ is None else environ
    raw_items = list(cli_specs or [])
    if not raw_items:
        raw_items = [s for s in env.get(LATIDO_ENV, "").split(";") if s.strip()]
    result: dict[str, str] = {}
    for item in raw_items:
        role, sep, path = item.partition("=")
        role, path = role.strip(), path.strip()
        if not sep or not path:
            raise UsageError(f"latido mal formado (esperado ROL=RUTA): {item!r}")
        if role not in ROLES:
            raise UsageError(f"rol desconocido {role!r} (validos: {', '.join(ROLES)})")
        if role in result:
            raise UsageError(f"rol repetido: {role}")
        result[role] = path
    return result


def read_latido(raw: str, motor_root: Path) -> str:
    """Lee un latido como texto.

    Before: ``raw`` ruta (relativa = contra ``motor_root``, nunca el cwd).
    During: rechaza UNC, directorios y ficheros de mas de 2 MiB; decodifica utf-8-sig ESTRICTO.
    After: devuelve el texto (un BOM se retira; vacio es valido aqui); ``Unreadable`` si no se
        puede leer (ausente, directorio, symlink roto, sin permiso, no UTF-8, demasiado grande).
    """
    if is_unc(raw):
        raise Unreadable(f"latido en ruta de red (UNC) no admitida: {raw}")
    path = Path(raw)
    if not path.is_absolute():
        path = motor_root / path
    try:
        if path.is_dir():
            raise Unreadable(f"latido es un directorio: {raw}")
        if path.stat().st_size > MAX_LATIDO_BYTES:
            raise Unreadable(f"latido de mas de {MAX_LATIDO_BYTES} bytes: {raw}")
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Unreadable(f"latido no es UTF-8: {raw}") from exc
    except OSError as exc:
        raise Unreadable(
            f"latido no se puede leer: {raw} ({type(exc).__name__})"
        ) from exc


def read_roster(raw: str, motor_root: Path) -> None:
    """Comprueba que el roster declarado existe y es un objeto JSON.

    Before: ``raw`` ruta declarada (relativa = contra ``motor_root``).
    During: lee utf-8-sig y parsea JSON; no usa los roles (solo su presencia decide el N/A).
    After: None si es un objeto JSON; ``Unreadable`` en cualquier otro caso (fail-closed: un
        roster declarado e ilegible no puede decidir el N/A).
    """
    if is_unc(raw):
        raise Unreadable(f"roster en ruta de red (UNC) no admitida: {raw}")
    path = Path(raw)
    if not path.is_absolute():
        path = motor_root / path
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError, RecursionError) as exc:
        raise Unreadable(
            f"roster declarado e ilegible: {raw} ({type(exc).__name__})"
        ) from exc
    if not isinstance(data, dict):
        raise Unreadable(f"roster declarado que no es un objeto JSON: {raw}")


# ----------------------------------------------------------------------------- ordenes
def extract_orders(text: str) -> tuple[list[tuple[int, str]], list[str]]:
    """Extrae las ordenes candidatas de un latido: codigo en linea y bloques ```.

    Before: ``text`` del latido. During: recorre por lineas; dentro de un bloque cada linea no
    vacia y que no empiece por ``#`` es una orden; fuera, cada ```` `codigo` ````. La prosa NO
    cuenta. After: ``(ordenes, problemas)``; un bloque sin cerrar es un problema (no confio en
    el parseo del resto).
    """
    orders: list[tuple[int, str]] = []
    problems: list[str] = []
    fence_start = 0
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            fence_start = 0 if fence_start else number
            continue
        if fence_start:
            if stripped and not stripped.startswith("#"):
                orders.append((number, stripped))
            continue
        orders.extend((number, m.group(1).strip()) for m in _INLINE_RE.finditer(line))
    if fence_start:
        problems.append(f"linea {fence_start}: bloque ``` sin cerrar")
    return orders, problems


def tokenize(text: str) -> list[tuple[str, str]]:  # noqa: C901 - automata de estados de una pasada
    """Tokeniza una orden en ``(tipo, texto)`` con tipo ``word`` u ``op`` (operador de shell).

    Before: ``text`` una orden. During: comillas simples o dobles agrupan (sin escapes: las
    rutas de Windows llevan ``\\``); ``<marcador>`` es una palabra; ``>``, ``>>``, ``2>``, ``&>``,
    ``|``, ``&&``, ``;``, ``&`` y ``<`` fuera de comillas son operadores. After: la lista;
    ``ValueError`` si una comilla no se cierra.
    """
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    started = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "\"'":
            end = text.find(ch, i + 1)
            if end == -1:
                raise ValueError("comilla sin cerrar")
            buf.append(text[i + 1 : end])
            started = True
            i = end + 1
        elif ch.isspace():
            if started:
                out.append(("word", "".join(buf)))
                buf, started = [], False
            i += 1
        elif ch == "<" and (m := _PLACEHOLDER_RE.match(text, i)):
            buf.append(m.group(0))
            started = True
            i = m.end()
        else:
            op = next((o for o in _OPERATORS if text.startswith(o, i)), None)
            if op is None:
                buf.append(ch)
                started = True
                i += 1
                continue
            word = "".join(buf)
            if op.startswith(">") and started and word.isdigit():
                op, buf, started = word + op, [], False
            elif started:
                out.append(("word", word))
                buf, started = [], False
            out.append(("op", op))
            i += len(op)
    if started:
        out.append(("word", "".join(buf)))
    return out


def _base(raw: str) -> str:
    """Basename de una ruta con cualquier tipo de barra."""
    return _norm(raw).rstrip("/").rsplit("/", 1)[-1]


def _interpreter_kind(exe: str) -> str:
    """'python', 'powershell' o 'other' segun el basename del primer token."""
    base = _base(exe).lower()
    if re.fullmatch(r"pythonw?[0-9.]*(\.exe)?", base):
        return "python"
    if base in ("powershell", "powershell.exe"):
        return "powershell"
    return "other"


def _is_candidate(order: str) -> bool:
    """True si la orden cita un script del inventario o empieza por un interprete conocido."""
    try:
        words = [value for kind, value in tokenize(order) if kind == "word"]
    except ValueError:
        return False
    if any(_base(word).lower() in _SCRIPTS for word in words):
        return True
    first = order.strip().split(None, 1)[0].strip("\"'") if order.strip() else ""
    base = _base(first).lower()
    return bool(re.fullmatch(r"(pythonw?[0-9.]*|powershell|pwsh|cmd)(\.exe)?", base))


def _prefix_of(name: str, full: str, minlen: int = 1) -> bool:
    """True si ``name`` es un prefijo (de al menos ``minlen``) de ``full``."""
    return len(name) >= minlen and full.startswith(name)


class _Order:
    """Resultado de evaluar UNA orden: script citado, flags y hallazgos."""

    def __init__(self, line: int, text: str) -> None:
        self.line = line
        self.text = text
        self.script: str | None = None
        self.flags: set[str] = set()
        self.problems: list[tuple[str, str]] = []

    def bad(self, text: str) -> None:
        self.problems.append(("V", text))

    def unreadable(self, text: str) -> None:
        self.problems.append(("U", text))

    @property
    def valid(self) -> bool:
        """True si la orden cita un script y no tiene hallazgos."""
        return self.script is not None and not self.problems


class _Git:
    """Consultas de solo lectura a git sobre el motor autorizado (siempre con ``--``)."""

    def __init__(self, git_exe: str | None, motor_root: Path) -> None:
        self._arg = git_exe
        self._motor = motor_root
        self._exe: str | None = None
        self._cache: dict[str, list[str]] = {}

    def _git_exe(self) -> str:
        if self._exe is not None:
            return self._exe
        raw = self._arg or shutil.which("git")
        if not raw:
            raise Unreadable("git no encontrado (ni --git-exe ni PATH)")
        try:
            exe = str(Path(raw).resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise Unreadable(f"git no se puede resolver: {raw}") from exc
        done = self._call(exe, ["--version"], cwd=False)
        if done.returncode != 0 or not done.stdout.startswith("git version"):
            raise Unreadable(
                f"git --version no responde como git (rc {done.returncode})"
            )
        self._exe = exe
        return exe

    def _call(
        self, exe: str, args: list[str], cwd: bool = True
    ) -> subprocess.CompletedProcess[str]:
        cmd = [exe, *(["-C", str(self._motor)] if cwd else []), *args]
        try:
            return subprocess.run(  # noqa: S603 - ruta absoluta verificada, sin shell
                cmd,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_S,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise Unreadable(
                f"git no responde ({type(exc).__name__}): {' '.join(args[:2])}"
            ) from exc

    def check_file(self, rel: str) -> list[str]:
        """Violaciones de ``rel`` (relativa al motor): no tracked, ausente de HEAD, distinta, preparada.

        Before: ``rel`` en posix relativa a ``motor_root``. During: ``ls-files --error-unmatch``,
        ``rev-parse HEAD:./rel``, ``hash-object`` y ``diff --cached --quiet``, todos con ``--``.
        After: lista de violaciones (vacia = limpio); ``Unreadable`` si git responde otra cosa.
        """
        if rel in self._cache:
            return self._cache[rel]
        exe = self._git_exe()
        found: list[str] = []
        ls = self._call(exe, ["ls-files", "--error-unmatch", "--", rel])
        if ls.returncode == 1:
            found.append("el script no esta seguido por git (no tracked)")
        elif ls.returncode != 0:
            raise Unreadable(
                f"git ls-files rc {ls.returncode}: {ls.stderr.strip()[:120]}"
            )
        else:
            found.extend(self._compare_head(exe, rel))
        self._cache[rel] = found
        return found

    def _compare_head(self, exe: str, rel: str) -> list[str]:
        found: list[str] = []
        head = self._call(exe, ["rev-parse", f"HEAD:./{rel}"])
        if head.returncode != 0:
            found.append("el script no existe en HEAD")
        else:
            work = self._call(exe, ["hash-object", "--", rel])
            if work.returncode != 0:
                raise Unreadable(f"git hash-object rc {work.returncode}")
            if work.stdout.strip() != head.stdout.strip():
                found.append("el script es distinto de HEAD (modificado sin commit)")
        staged = self._call(exe, ["diff", "--cached", "--quiet", "--", rel])
        if staged.returncode == 1:
            found.append("el script tiene cambios preparados en el indice sin commit")
        elif staged.returncode != 0:
            raise Unreadable(f"git diff --cached rc {staged.returncode}")
        return found


class _Checker:
    """Evalua ordenes de un latido contra el motor autorizado."""

    def __init__(
        self,
        motor_root: Path,
        python_exe: str | None,
        git_exe: str | None,
        environ: dict[str, str],
    ) -> None:
        self.motor = motor_root
        self.env = environ
        self._python_arg = python_exe
        self._git = _Git(git_exe, motor_root)
        self._pinned: Path | None = None

    # -- interpretes fijados
    def pinned_python(self) -> Path:
        """Interprete Python fijado (arg > FLIGHT_PYTHON > .venv del motor)."""
        if self._pinned is None:
            raw = self._python_arg or self.env.get(PYTHON_ENV)
            if not raw:
                sub = (
                    ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
                )
                raw = str(self.motor.joinpath(".venv", *sub))
            self._pinned = _resolve_strict(raw, "interprete Python fijado")
        return self._pinned

    def powershell_expected(self) -> Path:
        """PowerShell de ``%SystemRoot%/System32/WindowsPowerShell/v1.0``."""
        override = next(
            (v for k, v in self.env.items() if k.lower() == "flight_powershell_exe"),
            None,
        )
        if override:
            return _resolve_strict(override, "PowerShell fijado de prueba")
        # os.environ ignora mayusculas en Windows, un dict(os.environ) no: busca sin distinguirlas
        root = next((v for k, v in self.env.items() if k.lower() == "systemroot"), None)
        if not root:
            raise Unreadable(
                "SystemRoot ausente: no puedo fijar el PowerShell del sistema"
            )
        raw = str(
            Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        return _resolve_strict(raw, "PowerShell del sistema")

    # -- orden completa
    def evaluate(self, line: int, text: str) -> _Order:
        """Evalua UNA orden candidata. After: ``_Order`` con script, flags y hallazgos."""
        order = _Order(line, text)
        try:
            toks = tokenize(text)
        except ValueError as exc:
            order.bad(f"orden no tokenizable ({exc})")
            return order
        words = [t for k, t in toks if k == "word"]
        parsed = self._script_position(order, words)
        script = parsed[1] if parsed is not None else None
        toks = self._apply_redirect_rule(order, toks, script)
        words = [t for k, t in toks if k == "word"]
        self._denylist(order, words, _interpreter_kind(words[0]) if words else "other")
        if parsed is None:
            return order
        idx, script_word = parsed
        if _base(script_word).lower() not in _SCRIPTS:
            order.bad(
                "el primer operando tras las opciones no es un script del inventario: "
                f"{script_word}"
            )
            return order
        order.script = _base(script_word).lower()
        kind = _interpreter_kind(words[0])
        wanted = "powershell" if script_word.lower().endswith(".ps1") else "python"
        if kind != wanted:
            order.bad(f"el interprete {kind} no ejecuta un script {wanted}")
        order.flags = {
            w.split("=", 1)[0] for w in words[idx + 1 :] if w.startswith("-")
        }
        self._check_script(order, script_word)
        self._check_script_arguments(order, words[idx + 1 :], script_word)
        return order

    def _script_position(
        self, order: _Order, words: list[str]
    ) -> tuple[int, str] | None:
        """Ubica el unico operando-script estructural, sin inferir por coincidencia posterior.

        Before: ``words`` conserva el orden de tokens de una orden tokenizada. During: clasifica
        el primer token como Python o PowerShell, verifica el interprete fijado y delega la
        aridad de sus opciones. After: devuelve ``(indice, script)`` o ``None`` y deja una causa
        concreta en ``order``; nunca escanea basenames de valores de opciones.
        """
        if not words:
            order.bad("orden vacia")
            return None
        exe = words[0]
        kind = _interpreter_kind(exe)
        if kind == "other":
            order.bad(f"interprete no permitido (cmd, pwsh u otro): {exe}")
            return None
        if kind == "python":
            self._check_exe(order, exe, kind)
            return self._python_script_position(order, words)
        self._check_exe(order, exe, kind)
        return self._powershell_script_position(order, words)

    def _python_script_position(
        self, order: _Order, words: list[str]
    ) -> tuple[int, str] | None:
        """Aplica la tabla cerrada de opciones de Python antes del script.

        Before: ``words[0]`` ya es Python fijado. During: consume exactamente las opciones sin
        valor y con un valor admitidas; rechaza ``-c``, ``-m`` y cualquier opcion desconocida.
        After: devuelve el primer operando no opcion como script, o ``None`` con una causa que
        impide aceptar un valor de opcion como orden ejecutable.
        """
        index = 1
        while index < len(words):
            token = words[index]
            if not token.startswith("-"):
                return index, token
            if token in _PYTHON_NO_VALUE_OPTIONS:
                index += 1
                continue
            if token in _PYTHON_VALUE_OPTIONS:
                if index + 1 >= len(words):
                    order.bad(f"{token}: falta el valor de la opcion Python")
                    return None
                value = words[index + 1]
                if value.startswith("-"):
                    order.bad(f"{token}: el valor parece otra opcion Python: {value}")
                    return None
                if _base(value).lower() in _SCRIPTS:
                    order.bad(
                        "valor de opcion Python no puede ser un script del inventario: "
                        f"{value}"
                    )
                index += 2
                continue
            if token in {"-c", "-m"}:
                order.bad(f"{token}: python -c / -m no es la invocacion de un script")
            else:
                order.bad(f"opcion de Python no permitida: {token}")
            return None
        order.bad("falta el script despues de las opciones de Python")
        return None

    def _powershell_script_position(  # noqa: C901
        self, order: _Order, words: list[str]
    ) -> tuple[int, str] | None:
        """Resuelve script posicional o el operando inmediato de ``-File``.

        Before: ``words[0]`` ya es el PowerShell fijado. During: consume cada opcion previa con
        su aridad y toma solo el siguiente token de ``-File`` o el primer posicional como script.
        After: devuelve ``(indice, script)`` o ``None`` con causa; los valores de ``-Title``,
        ``-Message`` u otra opcion no pueden adquirir el rol de script.
        """
        index = 1
        while index < len(words):
            token = words[index]
            if not token.startswith("-"):
                return index, token
            name = token.lower().lstrip("-")
            if _prefix_of(name, "file"):
                if index + 1 >= len(words):
                    order.bad("-File de PowerShell sin script")
                    return None
                return index + 1, words[index + 1]
            if _is_command_switch(name):
                order.bad(f"{token}: -Command no ejecuta un script con -File")
                return None
            if name in _PS_NO_VALUE or any(
                _prefix_of(name, flag, _PS_FLAG_MIN_PREFIX.get(flag, 3))
                for flag in _PS_FLAGS
            ):
                index += 1
                continue
            if (
                name == "ep"
                or _prefix_of(name, "executionpolicy", 2)
                or any(_prefix_of(name, flag, 1) for flag in _PS_WITH_VALUE_PREFIXES)
            ):
                if index + 1 >= len(words):
                    order.bad(f"{token}: falta el valor de la opcion PowerShell")
                    return None
                value = words[index + 1].lower()
                if name == "ep" or _prefix_of(name, "executionpolicy", 2):
                    if value not in _PS_EXECUTION_POLICIES:
                        order.bad(
                            f"{token}: valor ExecutionPolicy no reconocido: {words[index + 1]}"
                        )
                        return None
                elif value not in _PS_WINDOW_STYLES:
                    order.bad(
                        f"{token}: valor WindowStyle no reconocido: {words[index + 1]}"
                    )
                    return None
                index += 2
                continue
            order.bad(f"opcion de PowerShell no permitida: {token}")
            return None
        order.bad("falta el script de PowerShell")
        return None

    def _apply_redirect_rule(
        self, order: _Order, toks: list[tuple[str, str]], script: str | None
    ) -> list[tuple[str, str]]:
        ops = [t for k, t in toks if k == "op"]
        if not ops:
            return toks
        is_quota = script is not None and _base(script).lower() == "quota_tick.py"
        final = (
            len(ops) == 1
            and ops[0] == ">"
            and len(toks) >= 2
            and toks[-2] == ("op", ">")
            and toks[-1][0] == "word"
            and is_quota
        )
        if not final:
            for op in ops:
                order.bad(f"operador de shell no permitido: {op!r}")
            return [t for t in toks if t[0] == "word"]
        target = toks[-1][1]
        if is_unc(target) or not Path(target).is_absolute():
            order.bad("redireccion a una ruta no absoluta o UNC")
        elif not Path(target).parent.is_dir():
            order.bad("redireccion a un directorio que no existe")
        return toks[:-2]

    def _check_script_arguments(
        self, order: _Order, args: list[str], script: str
    ) -> None:
        """Valida toda la cola de argumentos con una tabla cerrada por script."""
        script_key = _base(script).lower()
        if Path(script).is_absolute():
            if is_unc(script) or _DEV_PREFIX_RE.match(_norm(script)):
                return
            expected = (self.motor / "scripts" / "flight" / script_key).resolve()
            try:
                actual = Path(script).resolve(strict=True)
            except (OSError, ValueError, RuntimeError):
                actual = None
            if actual is not None and _strip_dev(actual) != _strip_dev(expected):
                order.bad(
                    f"ruta de productor no autorizada para metadata: {script}; "
                    f"se esperaba {expected}"
                )
                return
        script = script_key
        options = _SCRIPT_OPTION_META.get(script)
        if options is None:
            order.unreadable(f"parser real ausente para {script}")
            return
        unsupported = sorted(
            {
                detail
                for spec in options.values()
                for detail in _unsupported_spec_details(spec)
            }
        )
        if unsupported:
            order.unreadable(
                f"metadata no modelada para {script}: {', '.join(unsupported)}"
            )
            return
        index = 0
        seen: set[str] = set()
        while index < len(args):
            index = self._check_script_argument(
                order, args, index, script, options, seen
            )
        for name, spec in options.items():
            if spec.required and name not in seen:
                order.bad(f"falta el parametro obligatorio de {script}: {name}")

    def _check_script_argument(  # noqa: C901
        self,
        order: _Order,
        args: list[str],
        index: int,
        script: str,
        options: dict[str, tuple[bool, bool, bool]],
        seen: set[str],
    ) -> int:
        token = args[index]
        name, inline = token.split("=", 1) if "=" in token else (token, None)
        spec = options.get(name)
        if spec is None:
            order.bad(f"opcion desconocida para {script}: {token}")
            return index + 1
        arity, _required, repeatable = spec[:3]
        if script == "notify_user.ps1" and name in seen and not repeatable:
            order.bad(f"parametro repetido para {script}: {name}")
        seen.add(name)
        if name == _FORBIDDEN_DRY_RUN:
            order.bad(f"{name} silencia el aviso y esta prohibido en un latido")
        if not arity:
            if inline is not None:
                order.bad(f"{name} no admite valor inline: {token}")
            return index + 1
        if inline is not None:
            if not inline or inline.startswith("-"):
                order.bad(f"{name}: valor ausente o con apariencia de flag")
            else:
                self._check_tick_trace_value(order, script, name, inline)
            return index + 1
        if spec.nargs == "?" and (
            index + 1 >= len(args) or args[index + 1].startswith("-")
        ):
            return index + 1
        if index + 1 >= len(args) or args[index + 1].startswith("-"):
            order.bad(f"{name}: falta el valor o parece otra opcion")
            return index + 1
        if args[index + 1] == "" and spec.empty_allowed is False:
            order.bad(f"{name}: valor vacio no permitido para un string obligatorio")
        self._check_tick_trace_value(order, script, name, args[index + 1])
        return index + 2

    def _check_tick_trace_value(
        self, order: _Order, script: str, name: str, value: str
    ) -> None:
        """Comprueba valores literales de tick_trace con sus validadores reales.

        Before: ``script`` es el productor ya identificado y ``value`` es el
        valor de una opción con aridad.
        During: conserva marcadores ``<...>`` como posiciones del latido y, en
        otro caso, delega en ``tick_trace.py`` para enteros y ``FIELD=REASON``.
        After: añade una violación concreta si el productor rechaza el literal.
        """
        if script != "tick_trace.py" or _PLACEHOLDER_RE.fullmatch(value):
            return
        try:
            if name in {"--guard-rc", "--quota-rc"}:
                _TICK_TRACE_PARSE_RC(value, name[2:])
            elif name == "--unmeasured":
                _TICK_TRACE_PARSE_UNMEASURED([value])
        except (TypeError, ValueError) as exc:
            order.bad(f"valor no aceptado por tick_trace.py: {name}={value} ({exc})")

    def _denylist(self, order: _Order, words: list[str], kind: str) -> None:
        for i, w in enumerate(words):
            low = w.lower()
            if low.startswith("--emit"):
                order.bad(f"flag interno prohibido en un latido: {w}")
            if (
                kind == "powershell"
                and low.startswith("-")
                and (
                    _prefix_of(low.lstrip("-"), _FORBIDDEN_SWITCH)
                    or _prefix_of(low.lstrip("-"), "simulatenotifiersetting")
                )
            ):
                order.bad(f"{w} suprime el aviso (prohibido)")
            name = low.lstrip("-")
            if (
                kind == "powershell"
                and low.startswith("-")
                and (
                    name == "ec"
                    or (name.startswith("e") and _prefix_of(name, "encodedcommand"))
                )
            ):
                order.bad(f"{w}: -EncodedCommand (o un prefijo) prohibido")
            if (
                kind == "powershell"
                and low.startswith("-")
                and (name == "ep" or _prefix_of(name, "executionpolicy", 2))
                and i + 1 < len(words)
                and words[i + 1].lower() == "bypass"
            ):
                order.bad("-ExecutionPolicy Bypass prohibido")

    def _check_exe(self, order: _Order, exe: str, kind: str) -> None:
        if is_unc(exe):
            order.bad(f"interprete en ruta de red (UNC): {exe}")
            return
        if not Path(exe).is_absolute():
            order.bad(
                f"el primer token no es una ruta ABSOLUTA (se resolveria por PATH): {exe}"
            )
            return
        try:
            real = Path(exe).resolve(strict=True)
        except (OSError, ValueError, RuntimeError):
            order.bad(f"el interprete no existe: {exe}")
            return
        try:
            expected = (
                self.pinned_python() if kind == "python" else self.powershell_expected()
            )
        except Unreadable as exc:
            order.unreadable(str(exc))
            return
        if not _same(real, expected):
            order.bad(f"el interprete no es el fijado ({expected}): {exe}")

    def _check_script(self, order: _Order, raw: str) -> None:
        text = _norm(raw).lower()
        if "tmp_or8" in text:
            order.bad("el script vive en tmp_or8 (copia fuera del motor)")
            return
        if is_unc(raw):
            order.bad(f"script en ruta de red (UNC), no se resuelve: {raw}")
            return
        if not Path(raw).is_absolute():
            order.bad(f"script con ruta relativa (depende del cwd del latido): {raw}")
            return
        try:
            real = Path(raw).resolve(strict=True)
        except (OSError, ValueError, RuntimeError):
            order.bad(f"el script no existe o es un enlace roto: {raw}")
            return
        try:
            flight = self.motor.joinpath("scripts", "flight").resolve(strict=True)
            motor = self.motor.resolve(strict=True)
        except OSError as exc:
            order.unreadable(
                f"motor-root sin scripts/flight resoluble ({type(exc).__name__})"
            )
            return
        if not _contained(real, flight):
            order.bad(f"el script resuelve fuera de {flight}: {real}")
            return
        if real.name.lower() != _base(raw).lower():
            order.bad(f"el enlace apunta a otro fichero ({real.name}): {raw}")
            return
        rel = Path(os.path.relpath(_strip_dev(real), _strip_dev(motor))).as_posix()
        try:
            for problem in self._git.check_file(rel):
                order.bad(problem)
        except Unreadable as exc:
            order.unreadable(str(exc))


def _is_command_switch(name: str) -> bool:
    """-Command / -c y prefijos de PowerShell (no abarca -ConfigurationName)."""
    return bool(name) and name[0] == "c" and "command".startswith(name)


def _strip_dev(path: Path) -> Path:
    """Quita el prefijo de dispositivo local de una ruta resuelta (para relativizar)."""
    text = str(path)
    return Path(text[4:]) if _DEV_PREFIX_RE.match(text) else path


def _same(a: Path, b: Path) -> bool:
    """samefile tolerante: False si alguno no se puede comparar."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


# ----------------------------------------------------------------------------- informe
def evaluate_latido(role: str, text: str, checker: _Checker) -> list[_Finding]:
    """Evalua un latido contra el inventario de su rol.

    Before: ``text`` ya leido, ``role`` valido, ``checker`` con el motor autorizado. During:
    extrae y evalua cada orden candidata y exige el inventario del rol (cada item lo cubre UNA
    orden valida; las invalidas se informan por si mismas). After: lista de hallazgos (vacia =
    el latido cumple).
    """
    findings: list[_Finding] = []
    go_section = bool(re.search(r"GO AL USUARIO|ABIERTA BLOQUEA", text, re.IGNORECASE))
    if go_section and re.search(
        r"--event\s+go-\S+|ABIERTA BLOQUEA", text, re.IGNORECASE
    ):
        findings.append(
            _Finding(
                "V",
                role,
                "",
                "receta GO manual: usa una orden valida --go-id --what --flight-dir --owner; "
                "no escribas ABIERTA BLOQUEA ni uses --event go-<id>",
            )
        )
    orders, problems = extract_orders(text)
    findings.extend(_Finding("V", role, "", problem) for problem in problems)
    evaluated: list[_Order] = []
    for line, order_text in orders:
        if not _is_candidate(order_text):
            continue
        result = checker.evaluate(line, order_text)
        evaluated.append(result)
        findings.extend(
            _Finding(kind, role, f" linea {line}", f"{msg} | {order_text[:90]}")
            for kind, msg in result.problems
        )
        upper = order_text.upper()
        if (
            result.valid
            and result.script == "comms_alert.py"
            and "--EVENT" in upper
            and re.search(
                r"(?:^|\s)--event\s+go-[a-z0-9-]+(?:\s|$)",
                order_text,
                re.IGNORECASE,
            )
        ):
            findings.append(
                _Finding(
                    "V",
                    role,
                    f" linea {line}",
                    "receta GO manual: usa --go-id ... --what ... --flight-dir; "
                    "no escribas ABIERTA ni uses --event go-<id>",
                )
            )
    if go_section and not any(
        o.valid
        and o.script == "comms_alert.py"
        and {"--go-id", "--what", "--flight-dir", "--owner"} <= o.flags
        for o in evaluated
    ):
        findings.append(
            _Finding(
                "V",
                role,
                "",
                "falta una orden GO valida con --go-id --what --flight-dir --owner",
            )
        )
    used: set[int] = set()
    for script, required, forbidden in _INVENTORY[role]:
        forbidden_orders = [
            o for o in evaluated if o.script == script and forbidden & o.flags
        ]
        if script == "tick_trace.py" and forbidden_orders:
            findings.append(
                _Finding(
                    "V",
                    role,
                    "",
                    f"opcion prohibida para {script}: "
                    f"{' '.join(sorted(forbidden & forbidden_orders[0].flags))}",
                )
            )
        if not any(
            i not in used
            and o.valid
            and o.script == script
            and required <= o.flags
            and not (forbidden & o.flags)
            for i, o in enumerate(evaluated)
        ):
            need = " ".join(sorted(required)) or "(orden normal)"
            nope = f" sin {' '.join(sorted(forbidden))}" if forbidden else ""
            findings.append(
                _Finding(
                    "V", role, "", f"falta una orden VALIDA de {script} {need}{nope}"
                )
            )
        else:
            used.add(
                next(
                    i
                    for i, o in enumerate(evaluated)
                    if i not in used
                    and o.valid
                    and o.script == script
                    and required <= o.flags
                    and not (forbidden & o.flags)
                )
            )
    trace_count = sum(o.valid and o.script == "tick_trace.py" for o in evaluated)
    if role == "coordinadora" and trace_count > 1:
        findings.append(
            _Finding(
                "V",
                role,
                "",
                "tick_trace.py debe aparecer exactamente una vez en el latido",
            )
        )
    return findings


def aggregate(findings: list[_Finding]) -> int:
    """rc agregado: 2 si hay algo no verificable, 1 si hay violaciones, 0 si no hay nada."""
    if any(f.kind == "U" for f in findings):
        return EXIT_UNREADABLE
    return EXIT_VIOLATION if findings else EXIT_OK


def _quote(arg: str) -> str:
    return f'"{arg}"' if re.search(r"\s", arg) else arg


def reproduce_command(
    roster: str, specs: dict[str, str], motor: Path, extra: list[str]
) -> str:
    """Orden exacta para reproducir y revalidar (la usa el detalle del FAIL del gate)."""
    me = Path(__file__).resolve()
    parts = ["python", _quote(str(me)), "--roster-path", _quote(roster)]
    for role, raw in specs.items():
        parts += ["--latido-file", _quote(f"{role}={raw}")]
    parts += ["--motor-root", _quote(str(motor)), *extra]
    return " ".join(parts)


def run_check(
    *,
    roster: str | None,
    specs: dict[str, str],
    motor_root: Path,
    python_exe: str | None = None,
    git_exe: str | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[int, list[str]]:
    """Ejecuta el diagnostico completo.

    Before: argumentos ya resueltos (sin I/O de CLI). During: N/A sin roster; lee el roster;
    para cada rol lee y evalua su latido (los que faltan son violacion). After: ``(rc, lineas)``
    con la primera linea ``latido-check: OK|VIOLACION|ILEGIBLE|N/A``.
    """
    env = dict(os.environ if environ is None else environ)
    if not roster:
        return EXIT_NA, [
            "latido-check: N/A (sin roster: ni --roster-path ni " + ROSTER_ENV + ")"
        ]
    if _SCRIPT_OPTION_META_ERROR:
        return EXIT_UNREADABLE, [
            "latido-check: ILEGIBLE",
            f"  - [U] metadata de parsers: {_SCRIPT_OPTION_META_ERROR}",
        ]
    findings: list[_Finding] = []
    try:
        read_roster(roster, motor_root)
    except Unreadable as exc:
        return EXIT_UNREADABLE, ["latido-check: ILEGIBLE", f"  - [U] roster: {exc}"]
    checker = _Checker(motor_root, python_exe, git_exe, env)
    for role in ROLES:
        if role not in specs:
            findings.append(
                _Finding("V", role, "", "sin latido (pasa --latido-file ROL=RUTA)")
            )
            continue
        try:
            text = read_latido(specs[role], motor_root)
        except Unreadable as exc:
            findings.append(_Finding("U", role, "", str(exc)))
            continue
        findings.extend(evaluate_latido(role, text, checker))
    rc = aggregate(findings)
    label = {EXIT_OK: "OK", EXIT_VIOLATION: "VIOLACION", EXIT_UNREADABLE: "ILEGIBLE"}[
        rc
    ]
    lines = [f"latido-check: {label}", *[f.render() for f in findings]]
    return rc, lines


# ----------------------------------------------------------------------------- --alert
def _alert_plan(diag: int) -> tuple[str | None, list[str]]:
    """Tabla de transicion: ``(clave a emitir, claves a resolver)`` segun el rc diagnostico."""
    if diag == EXIT_VIOLATION:
        return KEY_DESVIADO, [KEY_ROTO]
    if diag == EXIT_UNREADABLE:
        return KEY_ROTO, [KEY_DESVIADO]
    if diag == EXIT_OK:
        return None, [KEY_DESVIADO, KEY_ROTO]
    return None, []


def _alert_what(diag: int, first_line: str) -> str:
    """Frase para el usuario (ASCII, corta; comms_alert la redacta)."""
    if diag == EXIT_VIOLATION:
        return (
            "Un latido del vuelo apunta fuera del motor o le faltan ordenes de aviso: revisalo. "
            + first_line
        )
    return (
        "El check de latidos no pudo verificar un latido (git, interprete o fichero ilegible): revisalo. "
        + first_line
    )


def emit_alert(
    diag: int,
    first_finding: str,
    *,
    ops_dir: str | None,
    flight_dir: str | None,
    session_code: str | None = None,
    dry_run: bool,
    runner=subprocess.run,
) -> bool:
    """Emite/resuelve las claves segun el rc diagnostico, en un SUBPROCESO del propio check.

    Before: ``diag`` rc diagnostico; ``ops_dir`` resuelto (o None). During: lanza
    ``sys.executable <este fichero> --emit-child ...`` con ``--ops-dir`` (y ``--flight-dir``)
    EXPLICITOS y timeout; el hijo carga comms_alert de junto a ``__file__`` y llama
    ``event(owner='check')`` / ``resolve``. After: True si el hijo salio 0 (o no habia nada que
    hacer); False si no hay ops-dir, hay timeout o el hijo falla (el llamador sube el rc a >= 2).
    """
    emit_key, resolve_keys = _alert_plan(diag)
    if emit_key is None and not resolve_keys:
        return True
    if not ops_dir:
        return False
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--emit-child",
        "--ops-dir",
        ops_dir,
    ]
    if flight_dir:
        cmd += ["--flight-dir", flight_dir]
    if session_code:
        cmd += ["--session-code", session_code]
    if emit_key:
        cmd += ["--emit", emit_key, "--what", _alert_what(diag, first_finding)[:300]]
    for key in resolve_keys:
        cmd += ["--resolve", key]
    if dry_run:
        cmd.append("--dry-run")
    try:
        done = runner(
            cmd, capture_output=True, text=True, timeout=EMIT_TIMEOUT_S, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return done.returncode == 0


def _load_comms_alert():
    """Carga comms_alert.py de junto a ESTE fichero (nunca de ops-dir); None si no se puede."""
    path = Path(__file__).resolve().with_name("comms_alert.py")
    spec = importlib.util.spec_from_file_location("comms_alert_153k", path)
    if spec is None or spec.loader is None or not path.is_file():
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["comms_alert_153k"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # cualquier fallo de carga es un fallo del aviso
        return None
    finally:
        sys.modules.pop("comms_alert_153k", None)
    return module


def emit_child_main(args: argparse.Namespace, loader=_load_comms_alert) -> int:
    """Modo INTERNO ``--emit-child``: emite una clave y resuelve otras con owner ``check``.

    Before: ``args.ops_dir`` resuelto por el padre; ``args.emit``/``args.resolve`` claves.
    During: carga comms_alert de junto a ``__file__``, ``configure(ops_dir)``, ``event(...,
    owner='check')`` (URGENTE) y ``resolve(clave)`` por cada clave. After: 0 si todo salio 0 o 10
    (limitado / sin registro: normal); 2 si comms_alert no carga, ops-dir no es utilizable o un
    paso devolvio 2. Los latidos NO pueden usar este modo (la denylist lo prohibe).
    """
    ca = loader()
    if ca is None:
        print(
            "check_latido_alert_wiring: comms_alert.py no se pudo cargar",
            file=sys.stderr,
        )
        return EXIT_UNREADABLE
    try:
        ca.configure(args.ops_dir)
    except ca.OpsDirError as exc:
        print(f"check_latido_alert_wiring: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE
    rc = 0
    if args.emit:
        title = f"Vuelo: {args.emit}"
        sent = ca.event(
            args.emit,
            "URGENTE",
            title,
            args.what or "",
            False,
            args.dry_run,
            owner=ALERT_OWNER,
            session_code=args.session_code,
        )
        if sent not in (0, 10):
            rc = 2
    for key in args.resolve or []:
        if ca.resolve(key, args.dry_run) not in (0, 10):
            rc = 2
    return rc


# ----------------------------------------------------------------------------- CLI
def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Check de latidos: invocan el mecanismo de avisos del motor"
    )
    ap.add_argument(
        "--latido-file",
        action="append",
        metavar="ROL=RUTA",
        help=f"latido de un rol (repetible); o ${LATIDO_ENV}",
    )
    ap.add_argument(
        "--roster-path", help=f"roster del vuelo; o ${ROSTER_ENV} (sin roster: rc 3)"
    )
    ap.add_argument(
        "--motor-root", help="worktree autorizado (por defecto la raiz de este check)"
    )
    ap.add_argument(
        "--python-exe", help=f"interprete fijado; o ${PYTHON_ENV}; o <motor>/.venv"
    )
    ap.add_argument(
        "--git-exe", help="git por ruta absoluta (por defecto PATH, verificado)"
    )
    ap.add_argument(
        "--alert",
        action="store_true",
        help="avisa URGENTE por latido-desviado/latido-check-roto",
    )
    ap.add_argument(
        "--ops-dir", help=f"directorio de operacion de comms_alert; o ${OPS_DIR_ENV}"
    )
    ap.add_argument("--flight-dir", help=f"directorio del vuelo; o ${FLIGHT_DIR_ENV}")
    ap.add_argument(
        "--dry-run", action="store_true", help="con --alert: no avisa ni guarda estado"
    )
    ap.add_argument("--emit-child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--emit", help=argparse.SUPPRESS)
    ap.add_argument("--what", help=argparse.SUPPRESS)
    ap.add_argument("--session-code", help=argparse.SUPPRESS)
    ap.add_argument("--resolve", action="append", help=argparse.SUPPRESS)
    return ap


class _ParserCaptured(BaseException):
    """Interrumpe un productor Python despues de construir su parser real."""


def _actions_from_parser(
    parser: argparse.ArgumentParser,
) -> dict[str, _OptionSpec]:
    """Convierte acciones y grupos reales en el contrato completo de opciones."""
    mutex_by_action: dict[object, int] = {}
    for group_index, group in enumerate(parser._mutually_exclusive_groups):
        for action in group._group_actions:
            mutex_by_action[action] = group_index
    result: dict[str, _OptionSpec] = {}
    for action in parser._actions:
        if action.__class__.__name__ == "_SubParsersAction":
            raise RuntimeError("subparsers de argparse no modelados")
        if not action.option_strings and action.dest != "help":
            raise RuntimeError(
                f"accion posicional no modelada en argparse: {action.dest}"
            )
        for option in action.option_strings:
            if option not in {"-h", "--help"}:
                result[option] = _OptionSpec(
                    action.nargs != 0,
                    bool(getattr(action, "required", False)),
                    action.__class__.__name__ in {"_AppendAction", "_CountAction"},
                    action.nargs,
                    tuple(str(choice) for choice in action.choices)
                    if action.choices is not None
                    else None,
                    getattr(action.type, "__name__", None)
                    if action.type is not None
                    else None,
                    mutex_by_action.get(action),
                    tuple(
                        detail
                        for detail, present in (
                            ("choices", action.choices is not None),
                            ("type", action.type is not None),
                            (
                                "mutex",
                                mutex_by_action.get(action) is not None,
                            ),
                            (
                                "nargs",
                                action.nargs not in (None, 0, "?"),
                            ),
                        )
                        if present
                    ),
                )
    return result


def _python_parser_actions(
    path: Path, own: bool = False
) -> dict[str, tuple[bool, bool, bool]]:
    """Obtiene acciones del parser real, sin duplicar su lista de opciones."""
    if own:
        return _actions_from_parser(_build_parser())
    original = argparse.ArgumentParser

    def factory(*args, **kwargs):
        parser = original(*args, **kwargs)

        def capture(*parse_args, **parse_kwargs):
            raise _ParserCaptured(parser)

        parser.parse_args = capture
        return parser

    try:
        spec = importlib.util.spec_from_file_location("latido_producer_probe", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"no se puede cargar parser: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class _ArgparseProxy:
            ArgumentParser = staticmethod(factory)

            def __getattr__(self, name):
                return getattr(argparse, name)

        module.argparse = _ArgparseProxy()
        module.main([])
    except _ParserCaptured as captured:
        return _actions_from_parser(captured.args[0])
    finally:
        pass
    raise RuntimeError(f"el productor no construyo parser: {path}")


def _powershell_parser_actions(path: Path) -> dict[str, _OptionSpec]:  # noqa: C901
    """Introspecciona ``param()`` mediante el AST de PowerShell real."""
    override = next(
        (v for k, v in os.environ.items() if k.lower() == "flight_powershell_exe"),
        None,
    )
    if override:
        executable = Path(override)
    elif os.name == "nt":
        root = next(
            (v for k, v in os.environ.items() if k.lower() == "systemroot"), None
        )
        if not root:
            raise RuntimeError("SystemRoot ausente para introspeccion PowerShell")
        executable = (
            Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
    else:
        found = shutil.which("pwsh")
        if not found:
            raise RuntimeError("SystemRoot ausente para introspeccion PowerShell")
        executable = Path(found)
    ps_path = "'" + str(path).replace("'", "''") + "'"
    command = (
        "$t=$null;$e=$null;"
        f"$a=[System.Management.Automation.Language.Parser]::ParseFile({ps_path},[ref]$t,[ref]$e);"
        "if ($e -and $e.Count -gt 0) { Write-Output '__PARSE_ERROR__' } "
        "elseif ($null -eq $a.ParamBlock) { Write-Output '__PARAMBLOCK_MISSING__' } "
        "else { $a.ParamBlock.Parameters | ForEach-Object { "
        "$m='none';$paramargs=@();$parampos=@();$_.Attributes | Where-Object {$_.TypeName.Name -eq 'Parameter'} | ForEach-Object { "
        "$_.NamedArguments | ForEach-Object { "
        "$paramargs += $_.ArgumentName; if ($_.ArgumentName -eq 'Mandatory') {$m=$_.Argument.Extent.Text} }; "
        "$_.PositionalArguments | ForEach-Object { $parampos += $_.Extent.Text; $m=$_.Extent.Text } };"
        "$attrs=( $_.Attributes | ForEach-Object { $_.TypeName.Name } ) -join ',';"
        "Write-Output (($_.Name.VariablePath.UserPath)+'|||'+$m+'|||'+$attrs+'|||'+$_.StaticType.Name+'|||'+($paramargs -join ',')+'|||'+($parampos -join ',')) } }"
    )
    result = subprocess.run(  # noqa: S603 - PowerShell absoluto y script AST fijo del motor
        [str(executable), "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "AST PowerShell no disponible")
    output_lines = result.stdout.splitlines()
    if "__PARSE_ERROR__" in output_lines:
        raise RuntimeError("errores de parseo PowerShell")
    if "__PARAMBLOCK_MISSING__" in output_lines:
        raise RuntimeError("ParamBlock ausente en PowerShell")
    actions: dict[str, _OptionSpec] = {}
    for line in output_lines:
        name, _, rest = line.partition("|||")
        mandatory, _, rest = rest.partition("|||")
        attrs, _, rest = rest.partition("|||")
        typename, _, rest = rest.partition("|||")
        paramargs, _, parampos = rest.partition("|||")
        if name == "__error__":
            raise RuntimeError("AST PowerShell no parseable")
        if name:
            unsupported = tuple(
                attr
                for attr in attrs.split(",")
                if attr
                and attr.lower()
                not in {"parameter", "string", "switch", "switchparameter"}
            )
            parameter_args = {
                arg for arg in paramargs.split(",") if arg and arg != "Mandatory"
            }
            positional_args = {
                arg for arg in parampos.split(",") if arg and arg != "Mandatory"
            }
            if parameter_args:
                unsupported = tuple(
                    sorted(
                        {*unsupported, *(f"Parameter.{arg}" for arg in parameter_args)}
                    )
                )
            if positional_args:
                unsupported = tuple(
                    sorted(
                        {
                            *unsupported,
                            *(f"Parameter.positional={arg}" for arg in positional_args),
                        }
                    )
                )
            mandatory_raw = mandatory.strip()
            mandatory_text = mandatory_raw.lower().replace(" ", "")
            if mandatory_text == "none":
                required = False
            elif mandatory_text == "mandatory" or mandatory_text in {
                "$true",
                "$false",
                "$null",
                "0",
                "1",
            }:
                required = mandatory_text in {"mandatory", "$true", "1"}
            else:
                unsupported = tuple(
                    sorted({*unsupported, f"mandatory={mandatory_raw}"})
                )
                required = False
            actions[f"-{name}"] = _OptionSpec(
                typename != "SwitchParameter",
                required,
                False,
                unsupported=unsupported,
                empty_allowed=not (required and typename.lower() == "string"),
            )
    return actions


def _derive_script_options() -> dict[str, dict[str, tuple[bool, bool, bool]]]:
    """Construye la gramática desde los productores, no desde una lista manual."""
    flight = Path(__file__).resolve().parent
    result = {SELF_NAME: _python_parser_actions(Path(__file__), own=True)}
    for name in (
        "comms_alert.py",
        "flight_stall_check.py",
        "quota_tick.py",
        "tick_trace.py",
    ):
        path = flight / name
        if path.exists():
            result[name] = _python_parser_actions(path)
    ps = flight / "notify_user.ps1"
    if ps.exists():
        result["notify_user.ps1"] = _powershell_parser_actions(ps)
    return result


def _alert_and_report(
    diag: int, lines: list[str], args: argparse.Namespace, env: dict[str, str]
) -> int:
    """Aplica ``--alert`` y devuelve el rc final (max(diag, 2) si el aviso falla)."""
    if diag == EXIT_NA:
        print(f"diag_rc={diag} alert=omitido")
        return diag
    first = next((ln.strip() for ln in lines[1:2]), "")
    ops = args.ops_dir or env.get(OPS_DIR_ENV)
    flight = args.flight_dir or env.get(FLIGHT_DIR_ENV)
    roster = getattr(args, "roster_path", None) or env.get(ROSTER_ENV) or None
    session_code = None
    if roster:
        try:
            roster_data = json.loads(Path(roster).read_text(encoding="utf-8"))
            candidate = (
                roster_data.get("active_roles", {})
                .get("orquestador", {})
                .get("session_code")
            )
            if re.fullmatch(r"[A-Z]{2,3}-[0-9]{1,4}", str(candidate or "")):
                session_code = candidate
        except (OSError, ValueError, AttributeError):
            pass
    ok = emit_alert(
        diag,
        first,
        ops_dir=ops,
        flight_dir=flight,
        session_code=session_code,
        dry_run=args.dry_run,
    )
    print(f"diag_rc={diag} alert={'ok' if ok else 'fallido'}")
    return diag if ok else max(diag, EXIT_UNREADABLE)


def _diagnose(args: argparse.Namespace, env: dict[str, str]) -> tuple[int, list[str]]:
    """Resuelve motor, roster y latidos y diagnostica; los errores de uso son rc 2."""
    roster = args.roster_path or env.get(ROSTER_ENV) or None
    if not roster:
        return EXIT_NA, [
            "latido-check: N/A (sin roster: ni --roster-path ni " + ROSTER_ENV + ")"
        ]
    try:
        specs = parse_latido_specs(args.latido_file, env)
        motor = (
            Path(args.motor_root)
            if args.motor_root
            else Path(__file__).resolve().parents[2]
        )
        motor = motor.resolve(strict=True)
    except (UsageError, OSError) as exc:
        return EXIT_UNREADABLE, [f"latido-check: ILEGIBLE (uso): {exc}"]
    rc, lines = run_check(
        roster=roster,
        specs=specs,
        motor_root=motor,
        python_exe=args.python_exe,
        git_exe=args.git_exe,
        environ=env,
    )
    extra = ["--alert"] if args.alert else []
    if args.python_exe:
        extra += ["--python-exe", _quote(args.python_exe)]
    if args.git_exe:
        extra += ["--git-exe", _quote(args.git_exe)]
    lines.append(
        "reproducir y revalidar: " + reproduce_command(roster, specs, motor, extra)
    )
    return rc, lines


def main(argv: list[str] | None = None) -> int:
    """CLI del check.

    Before: argumentos de linea de comandos (o ``argv``) y el entorno. During: resuelve motor,
    roster y latidos; N/A (rc 3) sin roster; diagnostica; con ``--alert`` emite en un subproceso
    (tambien ante un error de uso o un latido ilegible: ``latido-check-roto``). After: rc 0/1/2/3
    del contrato; salida con la primera linea ``latido-check: ...``, al final la orden exacta
    para reproducir y revalidar y, con ``--alert``, ``diag_rc=<n> alert=ok|fallido|omitido``.
    """
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _build_parser().parse_args(raw_argv)
    except SystemExit as exc:
        if exc.code == 0 or "--alert" not in raw_argv:
            raise
        env = dict(os.environ)
        usage = argparse.Namespace(
            alert=True,
            dry_run="--dry-run" in raw_argv,
            ops_dir=_argv_value(raw_argv, "--ops-dir"),
            flight_dir=_argv_value(raw_argv, "--flight-dir"),
        )
        lines = ["latido-check: ILEGIBLE (uso): argumentos invalidos"]
        print("\n".join(lines))
        return _alert_and_report(EXIT_UNREADABLE, lines, usage, env)
    env = dict(os.environ)
    if args.emit_child:
        return emit_child_main(args)
    rc, lines = _diagnose(args, env)
    print("\n".join(lines))
    if not args.alert:
        return rc
    return _alert_and_report(rc, lines, args, env)


def _argv_value(argv: list[str], option: str) -> str | None:
    """Extrae solo el valor literal de una opcion para el camino de error con ``--alert``."""
    try:
        index = argv.index(option)
    except ValueError:
        return None
    return (
        argv[index + 1]
        if index + 1 < len(argv) and not argv[index + 1].startswith("-")
        else None
    )


_TICK_TRACE_FIELDS: tuple[str, ...] = ()
_TICK_TRACE_PARSE_RC = None
_TICK_TRACE_PARSE_UNMEASURED = None
_TICK_TRACE_CONTRACT_ERROR: str | None = None
try:
    (
        _TICK_TRACE_FIELDS,
        _TICK_TRACE_PARSE_RC,
        _TICK_TRACE_PARSE_UNMEASURED,
    ) = _load_tick_trace_contract()
except Exception as exc:
    _TICK_TRACE_CONTRACT_ERROR = f"no se pudo derivar contrato de tick_trace.py: {exc}"

_SCRIPT_OPTION_META_ERROR: str | None = None
try:
    _SCRIPT_OPTION_META = _derive_script_options()
except Exception as exc:
    _SCRIPT_OPTION_META = {}
    _SCRIPT_OPTION_META_ERROR = f"no se pudo derivar metadata de parsers: {exc}"
if _TICK_TRACE_CONTRACT_ERROR:
    _SCRIPT_OPTION_META_ERROR = _TICK_TRACE_CONTRACT_ERROR
_SCRIPT_OPTIONS = {
    script: {option: spec[0] for option, spec in options.items()}
    for script, options in _SCRIPT_OPTION_META.items()
}
_SCRIPT_OPTION_CANONICAL_PATHS = {
    name: (Path(__file__).resolve().parent / name).resolve() for name in _SCRIPTS
}


if __name__ == "__main__":
    with contextlib.suppress(BrokenPipeError):
        sys.exit(main())
