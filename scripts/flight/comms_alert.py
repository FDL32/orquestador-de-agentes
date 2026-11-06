#!/usr/bin/env python3
"""Aviso de escritorio ante una causa de parada del vuelo (estado, bloqueo, ledger, scan).

Before: Windows (o POSIX) con un directorio de operacion existente y ABSOLUTO que
    contiene (o contendra) el ledger y el estado; ``notify_user.ps1`` vive junto a
    este fichero. El directorio se da con ``--ops-dir`` o ``FLIGHT_OPS_DIR``; sin
    resolver es un error (rc 2), nunca el cwd.
During: modo manual (--what/--error), ``--event`` (causa con nivel), ``--scan`` (FAIL
    nuevos del ledger desde el ultimo escaneo), ``--ack`` y ``--resolve``. El estado
    se actualiza bajo un bloqueo del sistema operativo sobre un fichero de lock
    SEPARADO; tras 5 s sin obtenerlo se SIGUE sin bloqueo (mejor avisar que quedarse
    mudo; puede perderse una clave, gana el ultimo escritor). El directorio de
    operacion es DATOS: de el nunca se carga ni se ejecuta codigo.
After: rc 0 = aviso emitido, 10 = limitado o nada nuevo, 2 = error (incluye ops-dir
    sin resolver y aviso fallido). Un fallo del propio aviso nunca se confunde con
    "sin novedad".
    Deuda 2 (cerrada): un registro de estado que no es un dict o con ``last``/``nu``
    no numericos se trata como NUEVO (el aviso sale), nunca como traceback mudo.
    Limite declarado: ``send_with_ledger.cmd_record`` anade al ledger sin el lock de
    ``comms_ledger.oslock``; queda una carrera residual entre ese escritor y este.
"""

import argparse
import contextlib
import errno
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import time as _real_time
import uuid
from datetime import datetime
from pathlib import Path


try:
    import msvcrt
except ImportError:  # no Windows
    msvcrt = None
try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

OPS_DIR_ENV = "FLIGHT_OPS_DIR"
THROTTLE_S = 30 * 60
LOCK_WAIT_S = 5
NO_WINDOW = 0x08000000
LEVELS = ("URGENTE", "AVISO")
# URGENTE persistente: espera entre avisos (minutos), tope 4 h, hasta ack o hasta que el detector deje de verla.
BACKOFF_MIN = (30, 60, 120, 240)
_CONTENTION = (errno.EACCES, errno.EDEADLK, errno.EAGAIN)

# notify_user.ps1 y send_with_ledger.py se localizan junto a ESTE fichero (nunca en el directorio de operacion).
NOTIFY = Path(__file__).resolve().with_name("notify_user.ps1")
_HELPER_PATH = Path(__file__).resolve().with_name("send_with_ledger.py")
_HELPER = None
STATE_LOAD_STATUS = None
# Las 9 claves fijas del ledger (las mismas que send_with_ledger.FIXED_KEYS; una prueba las compara).
_ROW_KEYS = (
    "ts",
    "by",
    "a",
    "modo",
    "resultado",
    "error",
    "providerInstanceId",
    "mensaje_id",
    "nota",
)
OWN_PREFIX = "comms_alert:"  # prefijo de mensaje_id de las filas propias (mas un UUID aleatorio por fila)
POWERSHELL_APP_ID = (
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
)
ENVIRONMENT_ID_ENV = "T3_ENVIRONMENT_ID"
THREAD_ID_ENV = "T3_THREAD_ID"
TEXT_LIMIT = 160
GO_ID_RE = re.compile(r"^go-[a-z0-9](?:[a-z0-9-]{0,59}[a-z0-9])?$")
OWNER_RE = re.compile(r"^[A-Z]{2,3}-[0-9]{1,4}$")
SESSION_CODE_RE = OWNER_RE
GO_QUEUE_REL = Path("diseno") / "COLA_PARA_USUARIO.md"
GO_LINE_RE = re.compile(
    r"^- \[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] "
    r"\[(?P<owner>[A-Z]{2,3}-\d{1,4})\] ABIERTA BLOQUEA \| "
    r"(?P<id>go-[a-z0-9](?:[a-z0-9-]{0,59}[a-z0-9])?): (?P<what>.*)$"
)
GO_RESOLVED_RE = re.compile(
    r"^- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] "
    r"\[[A-Z]{2,3}-\d{1,4}\] RESUELTA(?:-SIN-EFECTO)? \| "
    r"(?P<id>go-[a-z0-9](?:[a-z0-9-]{0,59}[a-z0-9])?): .*$"
)
GO_SEPARATORS = "\n\r\u2028\u2029\u0085\u000b\u000c\u001c\u001d\u001e"
_FREE_FIELDS = ("what", "nota", "error", "note")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_RE_THREAD = re.compile(r"mcp:" + _UUID, re.IGNORECASE)
_RE_UUID = re.compile(_UUID, re.IGNORECASE)
_RE_WINPATH = re.compile(
    r"(?<![a-z0-9])(?:\\\\\?\\)?[a-z]:[\\/][^\s'\"<>|]*", re.IGNORECASE
)
_RE_UNCPATH = re.compile(
    r"(?<![A-Za-z0-9])\\\\[^\\/\s'\"<>|]+(?:[\\/][^\\/\s'\"<>|]+)+"
)
# una `{` que abre un objeto JSON plausible (no una llave suelta del texto)
_RE_OBJ_START = re.compile(r'\{\s*["}]')
_RE_OWN_FRAGMENT = re.compile(r'"(?:by|from)"\s*:\s*"comms_alert"')
_RE_HOMEPATH = re.compile(r"/(?:home|Users)/[^\s'\"<>|]*")
_RE_SECRET = re.compile(
    r"(?i)(?:token|secret|secreto|password|passwd|api[_-]?key)[=:_-][ ]*[^ ,;]+"
)
_RE_BEARER_SECRET = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:authorization:\s*)?bearer\s+[A-Za-z0-9._~+/=-]{8,}"
)
_RE_SPACED_SECRET = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])token\s+(?=[A-Za-z0-9._~+/=-]*[0-9])"
    r"[A-Za-z0-9._~+/=-]{8,}"
)
_RE_API_SECRET = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])api[-_]?key(?:\s*[=:]\s*|\s+(?=[A-Za-z0-9._~+/=-]*[0-9]))"
    r"[A-Za-z0-9._~+/=-]{8,}"
)
_RE_PREFIX_SECRET = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|sk-)[A-Za-z0-9_-]{8,}"
)
_SECRET_PATTERNS = (
    _RE_BEARER_SECRET,
    _RE_SPACED_SECRET,
    _RE_API_SECRET,
    _RE_PREFIX_SECRET,
    _RE_SECRET,
)
# Rutas del directorio de operacion: las fija configure(); None = sin configurar.
LEDGER = None
STATE = None
LOCK = None
LEDGER_LOCK = None


class OpsDirError(Exception):
    """El directorio de operacion no se pudo resolver o no es utilizable."""


def resolve_ops_dir(arg=None, environ=None):
    """Resuelve el directorio de operacion: argumento > entorno, ABSOLUTO y existente.

    Before: ``arg`` es el valor de --ops-dir (o None); ``environ`` un mapping (por
        defecto os.environ) que puede traer FLIGHT_OPS_DIR.
    During: elige argumento o entorno, rechaza vacio, relativo, UNC y ausente, y
        canoniza con resolve(strict=True). No crea nada.
    After: devuelve el Path resuelto; lanza OpsDirError con la causa nombrada.
    """
    env = os.environ if environ is None else environ
    raw = arg if arg else env.get(OPS_DIR_ENV)
    if not raw:
        raise OpsDirError(
            f"ops-dir sin resolver: pasa --ops-dir o define {OPS_DIR_ENV}"
        )
    cand = Path(raw)
    if cand.drive.startswith("\\\\") and not re.fullmatch(
        r"\\\\\?\\[A-Za-z]:", cand.drive
    ):
        raise OpsDirError(f"ops-dir en ruta de red (UNC) no admitida: {raw}")
    if not cand.is_absolute():
        raise OpsDirError(
            f"ops-dir debe ser una ruta absoluta (una relativa depende del cwd): {raw}"
        )
    try:
        real = cand.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise OpsDirError(
            f"ops-dir no existe o no se puede resolver: {raw} ({type(exc).__name__})"
        ) from exc
    if not real.is_dir():
        raise OpsDirError(f"ops-dir no es un directorio: {raw}")
    return real


def configure(arg=None, environ=None):
    """Fija LEDGER, STATE y los ficheros de lock dentro del directorio de operacion.

    Before: ver resolve_ops_dir.
    During: resuelve el directorio y asigna las rutas globales del modulo.
    After: devuelve el directorio resuelto; OpsDirError si no es utilizable.
    """
    global LEDGER, STATE, LOCK, LEDGER_LOCK
    base = resolve_ops_dir(arg, environ)
    LEDGER = base / "comms_ledger.jsonl"
    STATE = base / "comms_alert_state.json"
    LOCK = base / "comms_alert.oslock"
    LEDGER_LOCK = base / "comms_ledger.oslock"
    return base


def _require_configured():
    if STATE is None or LEDGER is None or LOCK is None:
        raise OpsDirError(
            "ops-dir sin configurar: llama a configure() antes de usar el estado"
        )


def load_state():
    """Lee el estado y distingue ausencia legitima de corrupcion.

    Before: STATE configurado.
    During: lee con utf-8-sig (tolera BOM), parsea JSON y actualiza STATE_LOAD_STATUS a
        ``missing`` para ausencia o ``corrupt`` para vacio, truncado, tipo equivocado, JSON
        anidado que desborda la recursion o error de I/O.
    After: devuelve un dict; ante corrupcion devuelve ``{}`` para que el llamante aplique
        fail-closed, mientras el marcador permite conservar el primer uso legitimo ausente.
    """
    global STATE_LOAD_STATUS
    _require_configured()
    if not STATE.exists():
        STATE_LOAD_STATUS = "missing"
        return {}
    try:
        data = json.loads(STATE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        STATE_LOAD_STATUS = "corrupt"
        return {}
    if not isinstance(data, dict):
        STATE_LOAD_STATUS = "corrupt"
        return {}
    STATE_LOAD_STATUS = None
    return data


def save_state(st):
    """Guarda el estado de forma atomica (tmp unico por proceso + replace).

    Before: STATE configurado; ``st`` serializable.
    During: escribe ``<estado>.<pid>.tmp`` y lo sustituye con os.replace.
    After: el estado viejo queda integro si algo falla; el .tmp se limpia y el OSError se propaga.
    """
    _require_configured()
    tmp = STATE.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
        )
        os.replace(tmp, STATE)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _try_lock(fh):
    """Intenta tomar el bloqueo del SO (1 byte en el offset 0) SIN esperar; OSError si no."""
    fh.seek(0)
    if msvcrt is not None:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    elif fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        raise OSError(errno.ENOSYS, "sin bloqueo del sistema operativo")


def _unlock(fh):
    """Libera el bloqueo del SO tomado por _try_lock."""
    fh.seek(0)
    if msvcrt is not None:
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    elif fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class _Lock:
    """Exclusion del fichero de estado (leer-modificar-guardar) por bloqueo del SO.

    Todos los procesos bloquean el MISMO intervalo (1 byte en el offset 0) de un fichero de
    lock SEPARADO, abierto SIN truncado y mantenido abierto hasta liberar. Si no se obtiene
    en LOCK_WAIT_S segundos se SIGUE SIN bloqueo y SOLO ese caso se declara en stderr; si falla
    la apertura del fichero de lock o el bloqueo por una causa que no es contencion tambien se
    sigue sin bloqueo pero en silencio (``held`` queda False). Sin reclamacion por mtime.
    """

    def __init__(self, path):
        self.path = path
        self.fh = None
        self.held = False

    def __enter__(self):
        end = _real_time.time() + LOCK_WAIT_S
        try:
            self.fh = open(self.path, "a+b")
        except OSError:
            return self
        while True:
            try:
                _try_lock(self.fh)
                self.held = True
                return self
            except OSError as exc:  # noqa: PERF203 - un intento de bloqueo por vuelta es el diseno
                if exc.errno not in _CONTENTION:
                    return self
                if _real_time.time() >= end:
                    print(
                        f"bloqueo no obtenido en {LOCK_WAIT_S} s: se sigue SIN bloqueo (puede perderse una clave)",
                        file=sys.stderr,
                    )
                    return self
                _real_time.sleep(0.1)

    def __exit__(self, *exc):
        if self.fh is None:
            return
        try:
            if self.held:
                _unlock(self.fh)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                self.fh.close()


def update_state(fn):
    """Relee el estado BAJO el bloqueo, aplica fn y guarda: dos procesos no se pisan.

    Before: STATE y LOCK configurados; ``fn(st)`` muta el dict.
    During: toma el bloqueo, relee, aplica fn y guarda de forma atomica.
    After: el bloqueo se libera siempre (tambien si fn lanza); la excepcion se propaga. La
        exclusion vale SOLO si el bloqueo se obtuvo de verdad; en la degradacion declarada de
        ``_Lock`` (sin bloqueo) dos escritores pueden pisarse y gana el ultimo.
    """
    _require_configured()
    with _Lock(LOCK):
        st = load_state()
        fn(st)
        save_state(st)


class HelperError(Exception):
    """send_with_ledger.py (junto a este fichero) no se pudo cargar o no define lo esperado."""


def _helper():
    """Carga una vez send_with_ledger.py POR RUTA, junto a este fichero (nunca del ops-dir).

    Before: ``send_with_ledger.py`` existe junto a este fichero.
    During: lo carga con importlib y comprueba que define VALID_RESULTADOS y FIXED_KEYS.
    After: devuelve el modulo (cacheado); HelperError con la causa si falla.
    """
    global _HELPER
    if _HELPER is None:
        try:
            spec = importlib.util.spec_from_file_location(
                "send_with_ledger_ca", _HELPER_PATH
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.VALID_RESULTADOS  # noqa: B018 - comprueba que el nombre existe
            mod.FIXED_KEYS  # noqa: B018
        except Exception as exc:
            raise HelperError(
                f"no se pudo cargar {_HELPER_PATH.name}: {type(exc).__name__}: {exc}"
            ) from exc
        _HELPER = mod
    return _HELPER


def _redact_secrets(text):
    """Aplica en orden todos los patrones de secretos de la lista cerrada.

    Before: ``text`` es un str y ``_SECRET_PATTERNS`` contiene regex compiladas.
    During: sustituye cada coincidencia por ``<secreto>`` en el orden declarado.
    After: devuelve el texto con los secretos reconocidos ocultos; no recorta ni normaliza.
    """
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("<secreto>", text)
    return text


def redact(text):
    """Redacta un texto libre antes de que salga por el toast o el ledger (D21), idempotente.

    Before: ``text`` es cualquier valor (se convierte con str).
    During: sustituye UUID de hilo (``mcp:<uuid>``), UUID sueltos y rutas (Windows en cualquier
        forma/capitalizacion, ``\\\\?\\``, UNC y /home, /Users), mas la lista cerrada de secretos
        Authorization/Bearer, token con espacio, api-key/api_key/apikey y prefijos ghp_/gho_/ghu_/
        ghs_/ghr_/github_pat_/sk-. En las formas separadas por espacio el valor debe contener un
        digito (solo token y api-key/apikey separados por espacio; Bearer no usa esta condicion):
        se midieron como falsos positivos ``token validation failed in step 3``, ``token
        verification pending``, ``token expiration soon`` y ``apikey rotation scheduled``; queda
        como falso negativo medido un valor solo de letras tras espacio. Las formas fuera de esta
        lista quedan como limite medido. Las rutas UNC y con unidad se redactan solo hasta el
        primer espacio: la cola visible es un limite medido; ``//server/share`` con barras
        normales tampoco se cubre. Tambien se midieron las sobre-redacciones ``Bearer
        authentication failed``, ``token 2026-11-06`` y ``Bearer 2026-11-06``. DESPUES acota a
        TEXT_LIMIT caracteres y revalida el sufijo para conservar idempotencia.
    After: devuelve un str de como mucho TEXT_LIMIT caracteres; para los SECRETOS reconocidos,
        redact(redact(x)) == redact(x). Las rutas pegadas pueden cambiar al aplicar dos veces.
    """
    out = _RE_THREAD.sub("mcp:<hilo>", str(text))
    out = _RE_UUID.sub("<uuid>", out)
    out = _RE_UNCPATH.sub("<ruta>", out)
    out = _RE_WINPATH.sub("<ruta>", out)
    out = _RE_HOMEPATH.sub("<ruta>", out)
    out = _redact_secrets(out)
    if len(out) > TEXT_LIMIT:
        out = out[: TEXT_LIMIT - 3] + "..."
        out = _redact_secrets(out)
        if len(out) > TEXT_LIMIT:
            out = out[: TEXT_LIMIT - 3] + "..."
    return out


def tag_for_toast(key):
    """Deriva un Tag estable y no colisionante para la clave cruda del aviso.

    Before: ``key`` es la clave del estado que identifica una causa.
    During: reserva ``flight-`` para Tags derivados y usa SHA-256 de la clave
        cruda cuando aparece ese prefijo o ``redact`` la transforma; las demas
        claves de hasta 64 caracteres no transformadas se conservan.
    After: la funcion aplica redact a la clave cruda SIEMPRE y su salida NO es
        idempotente, asi que publicacion y retirada deben derivar el Tag de la
        MISMA clave cruda y nunca aplicar tag_for_toast sobre un Tag ya derivado.
    """
    raw = str(key)
    clean = redact(raw)
    if not raw.startswith("flight-") and clean == raw and len(raw) <= 64:
        return raw
    return "flight-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:57]


def ledger_append(row):
    """Anade una fila JSON al ledger bajo su propio bloqueo del SO (crea el fichero).

    Before: LEDGER y LEDGER_LOCK configurados; ``row`` serializable.
    During: redacta los campos libres (what, nota, error), toma ``comms_ledger.oslock``
        (misma degradacion que el estado), repara un final sin salto de linea y escribe UNA
        linea con un solo write. LIMITE declarado: ``send_with_ledger.cmd_record`` (no se toca)
        anade al mismo ledger SIN este bloqueo, asi que entre ambos escritores sigue habiendo carrera.
    After: el ledger termina en salto de linea; con el bloqueo obtenido ninguna fila de comms_alert
        se pierde ni se parte (sin el, en la degradacion declarada de ``_Lock``, dos escritores
        pueden intercalar bytes).
    """
    _require_configured()
    clean = {
        k: (redact(v) if k in _FREE_FIELDS and isinstance(v, str) else v)
        for k, v in row.items()
    }
    data = (json.dumps(clean, ensure_ascii=False) + "\n").encode("utf-8")
    with _Lock(LEDGER_LOCK), open(LEDGER, "a+b") as fh:
        if fh.seek(0, os.SEEK_END):
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                data = b"\n" + data
        fh.write(data)


def _ledger_row(a, resultado, nota, error=""):
    """Fila propia con EXACTAMENTE las 9 claves fijas y marca ``comms_alert:<uuid>`` (D16, D20)."""
    return {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "by": "comms_alert",
        "a": a,
        "modo": "",
        "resultado": resultado,
        "error": error,
        "providerInstanceId": "",
        "mensaje_id": f"{OWN_PREFIX}{uuid.uuid4()}",
        "nota": nota,
    }


def _nota(level, why, rc, what):
    return f"nivel={level}; motivo={why}; rc={rc}; {what}"


def _powershell_exe():
    override = os.environ.get("FLIGHT_POWERSHELL_EXE")
    if override:
        return Path(override)
    root = os.environ.get("SYSTEMROOT")
    if not root:
        return None
    return Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def _valid_session_code(value):
    """Devuelve un código corto seguro para el título o None si falta/no es válido."""
    return str(value) if value and SESSION_CODE_RE.fullmatch(str(value)) else None


def session_open_uri():
    """Construye el enlace de sesión básico si el entorno aporta ambos identificadores."""
    environment_id = os.environ.get(ENVIRONMENT_ID_ENV) or os.environ.get(
        "FLIGHT_ENVIRONMENT_ID"
    )
    thread_id = os.environ.get(THREAD_ID_ENV) or os.environ.get("FLIGHT_THREAD_ID")
    if not environment_id or not thread_id:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]+", environment_id) or not re.fullmatch(
        r"[A-Za-z0-9._-]+", thread_id
    ):
        return None
    return f"t3code://threads/{environment_id}/mcp:{thread_id}"


def redact_literal_first(text, *, preserve_literal=False):
    """Redacta un texto libre o conserva el literal explicito de un emisor GO.

    Before: ``text`` puede ser cualquier valor; ``preserve_literal`` indica si el llamador conoce que el valor completo es la frase literal de un GO.
    During: con ``False`` aplica ``redact`` completo; con ``True`` conserva el texto salvo los
        secretos de la lista cerrada, normaliza CR/LF a espacios y recorta a ``TEXT_LIMIT``. El
        llamador GO no pre-redacta.
    After: devuelve texto seguro de como mucho ``TEXT_LIMIT`` caracteres.
    """
    raw = str(text)
    if not preserve_literal:
        return redact(raw)
    value = _redact_secrets(raw)
    value = value.replace("\r", " ").replace("\n", " ")
    return value if len(value) <= TEXT_LIMIT else value[: TEXT_LIMIT - 3] + "..."


def notify(
    title,
    message,
    dry,
    *,
    tag=None,
    group=None,
    open_uri=None,
    urgent=False,
    app_id=None,
    clear_group=False,
    no_flash=False,
    preserve_literal=False,
):
    """Lanza notify_user.ps1 sin ventana y devuelve su rc (2 si no pudo lanzarse).

    Before: ``notify_user.ps1`` junto a este fichero; SystemRoot definido (Windows).
    During: ejecuta PowerShell por ruta absoluta, sin Bypass, con timeout de 60 s.
    After: rc del proceso tal cual; 2 ante SystemRoot ausente, timeout u OSError. Titulo y
        mensaje se redactan completos salvo ``preserve_literal=True``, reservado a GO;
        la salida de PowerShell se redacta completa y despues se imprime recortada a 200 caracteres.
    """
    title = redact(title)
    message = redact_literal_first(message, preserve_literal=preserve_literal)
    if dry:
        print("DRY-RUN notify:", title, "|", message)
        return 0
    exe = _powershell_exe()
    if exe is None:
        print("notify FALLO: SystemRoot ausente")
        return 2
    cmd = [
        str(exe),
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(NOTIFY),
        "-Title",
        title,
        "-Message",
        message,
    ]
    if tag is not None:
        cmd += ["-Tag", tag_for_toast(tag)]
    if group is not None:
        cmd += ["-Group", redact(group)]
    if open_uri is not None:
        cmd += ["-OpenUri", open_uri]
    cmd += ["-AppId", app_id or POWERSHELL_APP_ID]
    if urgent:
        cmd.append("-Urgent")
    if clear_group:
        cmd.append("-ClearGroup")
    if no_flash:
        cmd.append("-NoFlash")
    flags = NO_WINDOW if os.name == "nt" else 0
    try:
        r = subprocess.run(  # noqa: S603 - ruta absoluta del sistema, argumentos propios
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=flags,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"notify FALLO: {type(exc).__name__}")
        return 2
    stdout = redact((r.stdout or "").strip())[:200]
    print(f"notify rc={r.returncode} {stdout}")
    return r.returncode


def remove_toast(tag, group="flight", app_id=POWERSHELL_APP_ID, dry=False):
    """Intenta limpiar solo nuestro toast; el fallo no revierte el estado canónico."""
    if dry:
        return True
    exe = _powershell_exe()
    if exe is None:
        return False
    cmd = [
        str(exe),
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(NOTIFY),
        "-Title",
        ".",
        "-Message",
        ".",
        "-Tag",
        tag_for_toast(tag),
        "-Group",
        redact(group),
        "-AppId",
        app_id,
        "-Remove",
        "-NoFlash",
    ]
    try:
        return (
            subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=NO_WINDOW if os.name == "nt" else 0,
                check=False,
            ).returncode
            == 0
        )
    except (subprocess.TimeoutExpired, OSError):
        return False


def clear_group(dry=False):
    """Limpia solo nuestro Group/AppId al arrancar el vigilante, fail-soft."""
    return (
        notify(
            ".",
            ".",
            dry,
            group="flight",
            app_id=POWERSHELL_APP_ID,
            clear_group=True,
            no_flash=True,
        )
        == 0
    )


def alert(key, what, error, force, dry):
    """Aviso manual con limite de 30 min por clave.

    Before: configurado.
    During: consulta el limite, avisa y deja una fila en el ledger. Decide FUERA del bloqueo
        (leer, avisar, registrar): dos procesos simultaneos pueden avisar los dos.
    After: rc 0 avisado, 10 limitado, 2 aviso fallido. Riesgo residual de la carrera: un doble
        toast, nunca un aviso perdido.
    """
    st = load_state()
    now = time.time()
    last = _num(st.get(key), 0)
    if not force and now - last < THROTTLE_S:
        if not dry:
            ledger_append(
                _ledger_row(
                    key, "THROTTLED", _nota("-", "limite 30 min", 10, what), error
                )
            )
        print(f"limitado: ya se aviso hace {int((now - last) / 60)} min")
        return 10
    rc = notify(
        "Vuelo: comunicacion T3 con problemas",
        f"{what}: {error}. El vuelo puede estar parado; sigo reintentando.",
        dry,
    )
    if not dry:
        if rc == 0:
            update_state(lambda s: s.__setitem__(key, now))
        ledger_append(
            _ledger_row(
                key,
                "ALERT" if rc == 0 else "ALERT_FALLIDO",
                _nota("-", "manual", rc, what),
                error,
            )
        )
    return 0 if rc == 0 else 2


def _is_num(v):
    """True solo para un numero real y razonable, con cota absoluta 1e15.

    Before: cualquier valor persistido que pueda representar un instante o contador.
    During: acepta int/float finito salvo bool y rechaza NaN, infinito y valores enormes.
        El censo de 2026-11-06 no encontro timestamps heredados en microsegundos; por eso la
        cota 1e15 se conserva como NO-DEFECTO y no se amplia por especulacion.
    After: devuelve bool sin lanzar, incluso para formas ilegibles.
    """
    return isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 1e15


def _num(v, default=0):
    """``v`` si es un numero (int o float, no bool); si no, ``default`` (un valor ilegible nunca rompe el aviso)."""
    return v if _is_num(v) else default


def _is_int(v):
    """True solo para un entero real (un bool no cuenta: ``True`` seria el offset 1)."""
    return isinstance(v, int) and not isinstance(v, bool)


def _rec(v):
    """Registro de una clave de evento, o None si no es utilizable (None = clave nueva: avisa).

    Legado: un numero era la hora del unico aviso (nivel desconocido). Un dict solo es utilizable
    con ``level`` en LEVELS, ``acked`` booleano (o ausente) y ``last`` numerico (o ausente). Cualquier
    otra forma (dict vacio, ``acked`` cadena, cadena, lista...) es ilegible: se trata como ausente
    para que el aviso SALGA en vez de callar para siempre (``{}`` con AVISO) o de silenciar por un
    ``acked`` que no es booleano (``"false"`` se evaluaba verdadero).
    """
    if isinstance(v, dict):
        usable = (
            v.get("level") in LEVELS
            and isinstance(v.get("acked", False), bool)
            and ("last" not in v or _is_num(v["last"]))
        )
        return v if usable else None
    if _is_num(v):
        return {"level": None, "first": v, "last": v, "n": 1, "acked": False}
    return None


def _nu(rec):
    """Cuantos avisos URGENTE lleva la clave (el retroceso cuenta solo esos; un registro legado sin nivel cuenta como 1)."""
    nu = rec.get("nu")
    if isinstance(nu, int) and not isinstance(nu, bool):
        return nu
    return 1 if rec.get("level") in (None, "URGENTE") else 0


def _due(rec, level, now):
    """Motivo por el que toca avisar, o None: nueva; sube de nivel; URGENTE persistente tras su retroceso. AVISO: una sola vez."""
    if rec is None:
        return "nueva"
    if rec.get("acked"):
        return None
    if level == "URGENTE" and rec.get("level") == "AVISO":
        return "sube de nivel"
    if level == "URGENTE":
        wait = BACKOFF_MIN[min(max(_nu(rec), 1) - 1, len(BACKOFF_MIN) - 1)] * 60
        return "persiste" if now - rec.get("last", 0) >= wait else None
    return None


def _record(st, key, level, now, owner):
    rec = _rec(st.get("event:" + key))
    st["event:" + key] = {
        "level": level,
        "first": (rec or {}).get("first", now),
        "last": now,
        "n": _num((rec or {}).get("n"), 0) + 1,
        "nu": (_nu(rec) if rec else 0) + (1 if level == "URGENTE" else 0),
        "acked": False,
        "owner": owner or (rec or {}).get("owner"),
        "toast": True,
    }


def event(
    key,
    level,
    title,
    what,
    force,
    dry,
    owner=None,
    session_code=None,
    open_uri=None,
    preserve_literal=False,
):
    """Aviso de escritorio por una causa de parada, UNA vez por aparicion; URGENTE se repite con retroceso hasta ack o hasta que deje de verse.

    Before: configurado; ``level`` URGENTE o AVISO.
    During: decide con _due FUERA del bloqueo, avisa y, solo si el aviso salio, registra la clave.
    After: rc 0 avisado, 10 limitado, 2 nivel desconocido o aviso fallido (no consume el limite).
        Riesgo residual de la carrera entre dos procesos: un doble toast, nunca un aviso perdido.
    """
    level = level.upper()
    if level not in LEVELS:
        print(f"nivel desconocido: {level} (URGENTE o AVISO)")
        return 2
    st = load_state()
    now = time.time()
    rec = _rec(st.get("event:" + key))
    why = "forzado" if force else _due(rec, level, now)
    if why is None:
        mins = int((now - rec.get("last", now)) / 60)
        print(
            f"limitado ({key}, {level}): ya avisado hace {mins} min (n={_num(rec.get('n'), 1)}{', ack' if rec.get('acked') else ''})"
        )
        return 10
    safe_code = _valid_session_code(session_code)
    effective_title = safe_code or "Vuelo ?"
    if not safe_code:
        print("titulo de sesion ausente o invalido: se usa Vuelo ?")
    rc = notify(
        effective_title,
        what,
        dry,
        tag=key,
        group="flight",
        urgent=level == "URGENTE",
        open_uri=open_uri if open_uri is not None else session_open_uri(),
        preserve_literal=preserve_literal,
    )
    if not dry:
        if rc == 0:
            update_state(lambda s: _record(s, key, level, now, owner))
        ledger_append(
            _ledger_row(
                key,
                "ALERT" if rc == 0 else "ALERT_FALLIDO",
                _nota(level, why, rc, what)
                + ("; titulo_sesion=ok" if safe_code else "; titulo_sesion=fallback"),
                "" if rc == 0 else f"notify rc={rc}",
            )
        )
    return 0 if rc == 0 else 2


def mark_seen(key, level, owner=None, dry=False):
    """Linea base: da la clave por avisada SIN notificar."""
    if dry:
        return
    now = time.time()
    update_state(
        lambda s: s.__setitem__(
            "event:" + key,
            {
                "level": level.upper(),
                "first": now,
                "last": now,
                "n": 1,
                "nu": 1 if level.upper() == "URGENTE" else 0,
                "acked": False,
                "owner": owner,
                "toast": False,
            },
        )
    )


def ack(key, dry=False):
    """Reconocida la causa: no se repite mientras el detector la siga viendo."""
    state = load_state()
    if "event:" + key not in state:
        print(f"sin registro de {key}")
        return 10
    if _rec(state["event:" + key]) is None:
        print(f"ack FALLO: registro ilegible para {key}", file=sys.stderr)
        return 2
    if not dry:

        def f(s):
            if "event:" + key in s:
                r = _rec(s["event:" + key]) or _rec(0)
                r["acked"] = True
                s["event:" + key] = r

        update_state(f)
        rec = _rec(load_state().get("event:" + key))
        if (
            rec is not None
            and rec.get("toast") is True
            and not remove_toast(key, dry=False)
        ):
            ledger_append(
                _ledger_row(key, "TOAST_REMOVE_FALLIDO", "ack: limpieza fail-soft", "")
            )
    print(f"ack {key}")
    return 0


def resolve(key, dry=False):
    """La causa ya no existe: borra la clave (una recaida vuelve a avisar). Para las claves que NO mide un detector."""
    if "event:" + key not in load_state():
        print(f"sin registro de {key}")
        return 10
    if not dry:
        rec = _rec(load_state().get("event:" + key))
        update_state(lambda s: s.pop("event:" + key, None))
        if (
            rec is not None
            and rec.get("toast") is True
            and not remove_toast(key, dry=False)
        ):
            ledger_append(
                _ledger_row(
                    key, "TOAST_REMOVE_FALLIDO", "resolve: limpieza fail-soft", ""
                )
            )
    print(f"resuelta {key}")
    return 0


def _validate_go_value(value, *, identifier=False):
    """Valida un identificador o frase GO antes de cualquier I/O de la cola.

    Before: ``value`` es texto recibido por el CLI.
    During: aplica la gramática ASCII del identificador o la política monolínea de la frase.
    After: devuelve ``None`` si es válido; imprime la causa y devuelve 2 si no lo es.
    """
    text = str(value)
    if identifier:
        if not GO_ID_RE.fullmatch(text):
            print(
                "go-id invalido: se espera go-[a-z0-9]([a-z0-9-]{0,59}[a-z0-9])?",
                file=sys.stderr,
            )
            return 2
        return None
    if not text or len(text) > TEXT_LIMIT or any(ch in text for ch in GO_SEPARATORS):
        print("--what invalido: debe ser una frase UTF-8 de una linea", file=sys.stderr)
        return 2
    upper = text.upper()
    reserved_scan = upper.replace("DESBLOQUEAR", "")
    if " | " in text or any(
        token in reserved_scan for token in ("ABIERTA", "RESUELTA", "BLOQUEA")
    ):
        print(
            "--what invalido: contiene un separador o palabra reservada",
            file=sys.stderr,
        )
        return 2
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        print("--what invalido: contiene un caracter de control", file=sys.stderr)
        return 2
    if "\ufeff" in text:
        print("--what invalido: contiene BOM intermedio", file=sys.stderr)
        return 2
    return None


def _validate_owner(value):
    if value is None or not OWNER_RE.fullmatch(value):
        print("--owner invalido: se espera ^[A-Z]{2,3}-[0-9]{1,4}$", file=sys.stderr)
        return 2
    return None


def _go_queue_path(raw):
    """Resuelve el directorio de vuelo y exige una cola existente."""
    if not raw:
        print("flight-dir sin resolver", file=sys.stderr)
        return None
    path = Path(raw)
    if not path.is_absolute() or not path.is_dir():
        print(f"flight-dir no existe o no es absoluto: {raw}", file=sys.stderr)
        return None
    queue = path.resolve() / GO_QUEUE_REL
    if not queue.is_file():
        print(f"cola ausente: {queue}", file=sys.stderr)
        return None
    return queue


def _go_lines(data):
    """Devuelve los GO ABIERTOS de bytes UTF-8, tolerando BOM inicial y EOL mixto."""
    text = data.decode("utf-8-sig")
    return [GO_LINE_RE.fullmatch(line.rstrip("\r\n")) for line in text.splitlines()]


def _go_resolved_ids(data):
    text = data.decode("utf-8-sig")
    return {
        match.group("id")
        for line in text.splitlines()
        if (match := GO_RESOLVED_RE.fullmatch(line.rstrip("\r\n")))
    }


def _go_eol(data):
    """Elige el EOL dominante, con LF como desempate y fallback."""
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    return b"\r\n" if crlf > lf else b"\n"


def local_timestamp():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def go_request(  # noqa: C901
    go_id, what, flight_dir, owner, dry=False, now_fn=local_timestamp
):
    """Añade un GO idempotente y avisa sólo después del append.

    Before: ops configurado, flight-dir absoluto existente y cola existente.
    During: valida texto, bloquea la cola entre procesos, detecta repetición/conflicto, añade una
        línea con el EOL dominante y delega el aviso URGENTE a ``event``.
    After: rc 0 tras aviso, 10 si ya avisado con la misma frase, 2 ante entrada/I/O/notificador;
        un fallo del notificador conserva la línea pero no registra evento de éxito.
    """
    if (
        _validate_go_value(go_id, identifier=True)
        or _validate_go_value(what)
        or _validate_owner(owner)
    ):
        return 2
    queue = _go_queue_path(flight_dir)
    if queue is None:
        return 2
    lock_path = queue.with_name(queue.name + ".go.lock")
    line = f"- [{now_fn()}] [{owner}] ABIERTA BLOQUEA | {go_id}: {what}".encode()
    already_present = False
    with _Lock(lock_path):
        data = queue.read_bytes()
        try:
            resolved_ids = _go_resolved_ids(data)
            matches = _go_lines(data)
        except UnicodeDecodeError:
            print("cola invalida: no es UTF-8", file=sys.stderr)
            return 2
        if go_id in resolved_ids:
            print(f"go-id ya resuelto: usa otra clave: {go_id}", file=sys.stderr)
            return 2
        for match in matches:
            if match and match.group("id") == go_id:
                if match.group("what") == what:
                    if "event:" + go_id in load_state():
                        return 10
                    already_present = True
                else:
                    print(f"go-id en conflicto: {go_id}", file=sys.stderr)
                    return 2
        eol = _go_eol(data)
        prefix = b"" if not data or data.endswith((b"\n", b"\r")) else eol
        if not dry and not already_present:
            with queue.open("ab") as handle:
                handle.write(prefix + line + eol)
    if dry:
        return 0
    literal = redact_literal_first(what, preserve_literal=True)
    rc = event(
        go_id,
        "URGENTE",
        None,
        literal,
        False,
        False,
        owner="go",
        session_code=owner,
        preserve_literal=True,
    )
    # La cola puede haberse resuelto mientras el notificador estaba bloqueado.
    with _Lock(lock_path):
        try:
            resolved_after = _go_resolved_ids(queue.read_bytes())
        except UnicodeDecodeError:
            return rc
        if go_id in resolved_after:
            resolve(go_id, dry=False)
    return rc


def go_resolve(  # noqa: C901 - contrato de cola, estado y reconciliacion en un unico lock
    go_id, flight_dir, owner, dry=False, without_effect=False, now_fn=local_timestamp
):
    """Marca un GO como recibido o cancelado y resuelve su evento.

    Before: ``go_id`` válido y un flight-dir absoluto.
    During: bloquea la cola, añade una marca RESUELTA asociada si hay ABIERTA y elimina el
        evento de estado si existe; una cola ausente se trata como no registrada.
    After: rc 0 al resolver una ABIERTA o evento, rc 10 si no hay ninguno o si ya estaba
        RESUELTA; dry-run no muta cola ni estado.
    """
    if _validate_go_value(go_id, identifier=True) or _validate_owner(owner):
        return 2
    raw_path = Path(flight_dir) if flight_dir is not None else None
    if raw_path is None or not raw_path.is_absolute() or not raw_path.is_dir():
        print(f"flight-dir no existe o no es absoluto: {flight_dir}", file=sys.stderr)
        return 2
    queue = _go_queue_path(flight_dir)
    if queue is None:
        return 10
    lock_path = queue.with_name(queue.name + ".go.lock")
    with _Lock(lock_path):
        data = queue.read_bytes()
        try:
            resolved_ids = _go_resolved_ids(data)
            open_ids = {
                match.group("id") for match in _go_lines(data) if match is not None
            }
        except UnicodeDecodeError:
            print("cola invalida: no es UTF-8", file=sys.stderr)
            return 2
        has_event = "event:" + go_id in load_state()
        if go_id in resolved_ids:
            if has_event:
                # A crash may leave the marker committed before event cleanup.
                # Reconcile that active event while keeping the queue immutable.
                return resolve(go_id, dry)
            print(f"go ya resuelto: {go_id}")
            return 10
        if go_id in open_ids:
            marker = "RESUELTA-SIN-EFECTO" if without_effect else "RESUELTA"
            eol = _go_eol(data)
            if not dry:
                with queue.open("ab") as handle:
                    if data and not data.endswith((b"\n", b"\r")):
                        handle.write(eol)
                    handle.write(
                        f"- [{now_fn()}] [{owner}] {marker} | {go_id}: {marker}".encode()
                        + eol
                    )
            if not has_event:
                return 0
        elif not has_event:
            print(f"sin registro de {go_id}")
            return 10
        else:
            return resolve(go_id, dry)
    return resolve(go_id, dry)


def reconcile(prefixes, active, dry=False, owner=None):  # noqa: C901 - filtros de estado y limpieza fail-soft
    """Borra las claves de evento con esos prefijos que el detector ya NO ve (una recaida vuelve a avisar). Con owner, solo las suyas o las heredadas sin dueno."""
    gone = []
    toast_keys = set()

    def f(s):
        for k in list(s):
            if not (
                k.startswith("event:")
                and k[6:].startswith(tuple(prefixes))
                and k[6:] not in active
            ):
                continue
            dueno = (_rec(s[k]) or {}).get("owner")
            if owner is not None and dueno not in (owner, None):
                continue
            gone.append(k[6:])
            if (_rec(s[k]) or {}).get("toast") is True:
                toast_keys.add(k[6:])
            if not dry:
                del s[k]

    if dry:
        f(load_state())
    else:
        update_state(f)
        for key in gone:
            if key not in toast_keys:
                continue
            if not remove_toast(key, dry=False):
                ledger_append(
                    _ledger_row(
                        key, "TOAST_REMOVE_FALLIDO", "reconcile: limpieza fail-soft", ""
                    )
                )
    return gone


def _is_own(d):
    """Fila propia: ``from``=comms_alert (antiguas) o ``by``=comms_alert con marca ``comms_alert:<uuid>`` (D20)."""
    if d.get("from") == "comms_alert":
        return True
    return d.get("by") == "comms_alert" and str(d.get("mensaje_id", "")).startswith(
        OWN_PREFIX
    )


def _failure_resultados():
    """Resultados del vocabulario cerrado de send_with_ledger que son fallo: todos menos ``enviado``."""
    return frozenset(_helper().VALID_RESULTADOS) - {"enviado"}


def _scan_failure(d, failures):
    """Convierte una fila ajena del ledger en un fallo ``{to, status}`` o None (D15)."""
    verdict = str(d.get("resultado") or d.get("status") or d.get("result") or "")
    folded = verdict.casefold()
    if not (
        folded.startswith("fail") or folded in {item.casefold() for item in failures}
    ):
        return None
    pna = "parent_not_active" in (str(d.get("error")) + verdict)
    return {
        "to": str(d.get("a") or d.get("to") or "?"),
        "status": "FAIL parent_not_active" if pna else "FAIL",
    }


def _split_line(line):
    """Parte una linea en sus piezas, en orden: ``("obj", valor)`` o ``("frag", texto)``.

    Una linea fusionada (``{..}{..}``) trae varios objetos JSON completos. Si un objeto esta roto, se
    RESINCRONIZA en la siguiente ``{`` que abre un objeto plausible (``{`` + espacios + ``"`` o ``}``; una
    llave suelta dentro del texto no corta) y el texto roto es un ``frag``: asi una fila propia rota no
    esconde una ajena completa que la sigue, ni al reves. Sin ninguna ``{`` decodificable la linea
    entera es un ``frag``.
    """
    dec = json.JSONDecoder()
    plausible_starts = [match.start() for match in _RE_OBJ_START.finditer(line)]
    start_index = 0
    out, pos, n = [], 0, len(line)
    while pos < n:
        if line[pos].isspace():
            pos += 1
            continue
        try:
            obj, pos = dec.raw_decode(line, pos)
        except (ValueError, RecursionError):
            while (
                start_index < len(plausible_starts)
                and plausible_starts[start_index] <= pos
            ):
                start_index += 1
            nxt = (
                plausible_starts[start_index]
                if start_index < len(plausible_starts)
                else None
            )
            end = n if nxt is None else nxt
            out.append(("frag", line[pos:end]))
            pos = end
            continue
        out.append(("obj", obj))
    return out


def _ledger_identity():
    """Calcula la identidad estable del ledger para detectar sustituciones silenciosas.

    Before: LEDGER configurado y accesible.
    During: obtiene tamaño y mtime_ns del fichero y hashea como máximo sus primeros 4096 bytes.
    After: devuelve un dict serializable; propaga OSError para que scan devuelva rc 2.
    """
    stat = LEDGER.stat()
    with open(LEDGER, "rb") as fh:
        prefix = fh.read(min(stat.st_size, 4096))
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
        "prefix_n": len(prefix),
    }


def _scan_chunk(chunk, failures):
    """Lista los fallos de las lineas completas de ``chunk``; las filas propias NO cuentan.

    Cada objeto JSON completo se evalua por separado (una fila propia fusionada con una ajena no
    esconde el fallo ajeno). El ultimo recurso por subcadena se aplica a cada FRAGMENTO no parseable
    por separado, y se omite cuando ese fragmento es propio por su clave ``by``/``from`` = comms_alert
    (no por la palabra suelta: una fila ajena rota que solo MENCIONA comms_alert sigue contando).
    LIMITE DECLARADO: un UNICO fragmento que mezcla una cabecera propia y una cola ajena sin una segunda
    llave de objeto (``{"by":"comms_alert",...FAIL``) se descarta entero como propio, y el FAIL ajeno
    queda oculto; exige la carrera de escritura ya declarada en ledger_append. Como compromiso D18/D19,
    las anclas plausibles priorizan no perder la cola ajena, y se acepta/declarara el falso positivo
    residual cuando una llave seguida de comillas aparece dentro de una nota propia rota.
    """
    fused = re.compile(
        r'"resultado"\s*:\s*"(?:'
        + "|".join(re.escape(v) for v in sorted(failures))
        + r')"'
    )
    new = []
    for line in chunk.splitlines():
        if not line.strip():
            continue
        for kind, val in _split_line(line):
            if kind == "obj":
                found = None
                if isinstance(val, dict) and not _is_own(val):
                    found = _scan_failure(val, failures)
                if found:
                    new.append(found)
            elif not _RE_OWN_FRAGMENT.search(val) and (
                "FAIL" in val or "parent_not_active" in val or fused.search(val)
            ):
                new.append({"to": "?", "status": "FAIL (linea no parseable)"})
    return new


def scan(force, dry):  # noqa: C901 - scan keeps the fail-closed cursor transitions together.
    """Mira solo los bytes COMPLETOS (hasta el ultimo salto de linea) del ledger posteriores al ultimo escaneo.

    Before: configurado; ``send_with_ledger.py`` junto a este fichero.
    During: lee desde el offset guardado (primer uso = final del fichero), quita un BOM en el
        offset 0, y avisa de los fallos ajenos: prefijo FAIL de las filas antiguas y todo
        ``resultado`` del vocabulario cerrado salvo ``enviado``. Un offset no entero, negativo o MAYOR
        que el fichero (ledger encogido o sustituido) se trata como 0: relee todo y avisa una vez
        agrupado (el limite de 30 min acota el coste). DIFERENCIA AUTORIZADA frente a la version
        vigente, que saltaba al final y descartaba en silencio las filas FAIL no escaneadas (falso
        negativo = parada sin aviso); antes un offset no entero daba TypeError sin aviso.
        La identidad persistida es tamaño + mtime_ns + SHA-256 de los primeros 4096 bytes; una
        sustitucion con tamaño >= offset y distinta identidad relee desde 0 y agrupa un unico aviso.
        Un estado viejo sin identidad adopta la actual conservando el offset si sigue dentro del
        fichero; un estado corrupto relee desde 0, avisa ``estado ilegible`` y se reescribe.
    After: rc 0 avisado, 10 nada nuevo o agrupado, 2 aviso fallido, ledger ausente/ilegible o helper
        no cargable (con la causa en la salida; nunca "sin novedad").
    """
    try:
        failures = _failure_resultados()
        identity = _ledger_identity()
        size = identity["size"]
    except (HelperError, OSError) as exc:
        print(f"scan FALLO: {exc}")
        return 2
    state = load_state()
    state_corrupt = STATE_LOAD_STATUS == "corrupt"
    stored_identity = {
        "size": state.get("_ledger_size"),
        "mtime_ns": state.get("_ledger_mtime_ns"),
        "prefix_sha256": state.get("_ledger_prefix_sha256"),
        "prefix_n": state.get("_ledger_prefix_n"),
    }
    has_identity = all(value is not None for value in stored_identity.values())
    replaced = has_identity and stored_identity != identity
    offset = state.get("_last_scan_offset")
    if state_corrupt or replaced:
        offset = 0
    elif offset is None:
        offset = size
    elif not _is_int(offset) or offset < 0 or offset > size:
        offset = 0  # estado basura o ledger encogido/sustituido: se relee desde el principio (un aviso agrupado), nunca traceback ni filas FAIL descartadas
    try:
        with open(LEDGER, "rb") as fh:
            fh.seek(offset)
            raw = fh.read()
    except OSError as exc:
        print(f"scan FALLO: {exc}")
        return 2
    cut = raw.rfind(b"\n")
    consumed = cut + 1 if cut >= 0 else 0
    new_off = offset + consumed
    chunk = raw[:consumed].decode("utf-8", errors="replace")
    if offset == 0:
        chunk = chunk.removeprefix("\ufeff")
    new = _scan_chunk(chunk, failures)

    def setoff(s):
        current_identity = _ledger_identity()
        s["_last_scan_offset"] = new_off
        s["_ledger_size"] = current_identity["size"]
        s["_ledger_mtime_ns"] = current_identity["mtime_ns"]
        s["_ledger_prefix_sha256"] = current_identity["prefix_sha256"]
        s["_ledger_prefix_n"] = current_identity["prefix_n"]
        s.pop("_last_scan_ts", None)

    if state_corrupt and not new:
        rc = alert(
            "scan", "estado ilegible; 0 envios fallidos", "estado ilegible", force, dry
        )
        if rc != 2 and not dry:
            update_state(setoff)
        return rc
    if not new:
        if not dry:
            update_state(setoff)
        print(f"sin FAIL nuevos en el ledger (desde la posicion {offset})")
        return 10
    prefix = "estado ilegible; " if state_corrupt else ""
    what = f"{prefix}{len(new)} envio(s) fallido(s), ultimo hacia {new[-1]['to']}"
    error = (
        "estado ilegible; " + new[-1]["status"] if state_corrupt else new[-1]["status"]
    )
    rc = alert("scan", what, error, force, dry)
    # rc 10 = agrupado con el aviso de hace menos de 30 min: se consume; solo un aviso FALLIDO (rc 2) deja el offset donde estaba
    if rc != 2 and not dry:
        update_state(setoff)
    return rc


def main(argv=None):  # noqa: C901 - CLI dispatch keeps legacy and GO paths explicit.
    """CLI de comms_alert.

    Before: argumentos de linea de comandos (o ``argv``).
    During: resuelve el directorio de operacion y despacha resolve, ack, scan, event o alert.
    After: rc 0/10/2 del subcomando; 2 si el directorio de operacion no se resuelve.
    """
    ap = argparse.ArgumentParser(
        description="Aviso de escritorio por problema de comunicacion T3"
    )
    ap.add_argument(
        "--ops-dir",
        help=f"directorio de operacion (ledger y estado); por defecto ${OPS_DIR_ENV}",
    )
    ap.add_argument(
        "--flight-dir",
        help="directorio del vuelo que contiene diseno/COLA_PARA_USUARIO.md",
    )
    ap.add_argument("--what", help="llamada y destino que fallo")
    ap.add_argument("--error", default="parent_not_active")
    ap.add_argument(
        "--scan", action="store_true", help="avisa si hay FAIL nuevos en el ledger"
    )
    ap.add_argument(
        "--event",
        help="clave de la causa de parada (p. ej. decision-usuario, cupo-97, hilo-failed)",
    )
    ap.add_argument("--level", default="AVISO", help="URGENTE o AVISO")
    ap.add_argument("--title", default=None)
    ap.add_argument(
        "--force", action="store_true", help="salta el limite de repeticion"
    )
    ap.add_argument(
        "--ack", help="reconoce una clave de evento: no se repite mientras siga activa"
    )
    ap.add_argument(
        "--resolve",
        help="la causa ya no existe: borra la clave (una recaida avisa de nuevo)",
    )
    ap.add_argument("--go-id", help="clave estable de una solicitud GO")
    ap.add_argument("--owner", help="propietario: AA-1..AAA-9999")
    ap.add_argument(
        "--sin-efecto", action="store_true", help="marca un GO cancelado sin efecto"
    )
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        configure(a.ops_dir)
    except OpsDirError as exc:
        print(f"comms_alert: {exc}", file=sys.stderr)
        return 2
    mode_options = [
        ("--scan", a.scan),
        ("--event", a.event is not None),
        ("--resolve", a.resolve is not None),
        ("--ack", a.ack is not None),
    ]
    selected_modes = [name for name, selected in mode_options if selected]
    if len(selected_modes) >= 2:
        print(
            "opciones incompatibles: " + ", ".join(selected_modes),
            file=sys.stderr,
        )
        return 2
    if a.resolve and a.what:
        print("--resolve no se combina con --what", file=sys.stderr)
        return 2
    if a.resolve and a.owner is not None and a.flight_dir is None:
        print("--owner con --resolve exige --flight-dir", file=sys.stderr)
        return 2
    if a.sin_efecto and (not a.resolve or not a.flight_dir):
        print(
            "--sin-efecto solo es valido con --resolve y --flight-dir", file=sys.stderr
        )
        return 2
    go_mode = (
        a.go_id is not None
        or a.flight_dir is not None
        or (a.owner is not None and a.event is None)
        or a.sin_efecto
    )
    try:
        if go_mode:
            mixed = (
                a.event
                or a.ack
                or a.scan
                or (a.resolve and a.go_id is not None)
                or a.sin_efecto
                or a.error != "parent_not_active"
            )
            if a.resolve and (a.event or a.ack or a.scan or a.go_id is not None):
                print(
                    "--resolve no se combina con --event/--ack/--scan/--go-id",
                    file=sys.stderr,
                )
                return 2
            if a.go_id is None and not a.resolve:
                print(
                    "modo GO incompleto: --flight-dir/--owner/--sin-efecto exige --go-id o --resolve",
                    file=sys.stderr,
                )
                return 2
            if a.go_id is not None and (not a.what or not a.flight_dir or mixed):
                print(
                    "modo GO incompleto o mezclado: --go-id exige --what, --flight-dir y --owner",
                    file=sys.stderr,
                )
                return 2
            if a.resolve and not a.flight_dir:
                return resolve(a.resolve, a.dry_run)
            if a.resolve:
                return go_resolve(
                    a.resolve, a.flight_dir, a.owner, a.dry_run, a.sin_efecto
                )
            return go_request(a.go_id, a.what, a.flight_dir, a.owner, a.dry_run)
        if a.resolve:
            return resolve(a.resolve, a.dry_run)
        if a.ack:
            return ack(a.ack, a.dry_run)
        if a.scan:
            return scan(a.force, a.dry_run)
        if a.event:
            if not a.what:
                ap.error(
                    "--event exige --what (una frase con lo que hace falta del usuario)"
                )
            return event(
                a.event,
                a.level,
                a.title,
                a.what,
                a.force,
                a.dry_run,
                owner="manual",
                session_code=a.owner,
            )
        if not a.what:
            ap.error("falta --what o --scan")
        return alert(a.error, a.what, a.error, a.force, a.dry_run)
    except OSError as exc:
        print(f"comms_alert: I/O: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
