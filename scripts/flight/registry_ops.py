#!/usr/bin/env python3
"""Operaciones controladas sobre el registro de sesiones del vuelo.

Before: ``--registry`` apunta a un JSON legible con ``sessions`` como lista de
    diccionarios, y los subcomandos de escritura reciben ``--by`` y ``--reason``.
During: valida altas, asientos y notas en modo dry-run o, con ``--apply``, toma
    el lock del sistema, rota backups, escribe el registry atomico y anade su
    ledger propio antes de liberar el lock. Los locks usan ``msvcrt`` en
    Windows y ``fcntl`` en POSIX.
After: imprime un plan JSON o aplica una mutacion durable. Los codigos son:
    0 = exito (incluido dry-run valido); 2 = entrada invalida o esquema roto;
    3 = reservado exclusivamente para el gate operativo de reconcile --apply;
    4 = conflicto de identidad; 5 = lock no disponible tras reintentos.

El ``providerInstanceId`` se resuelve a cuenta antes del snapshot de reconcile:
``claudeAgent=brabander``, ``claudeAgent_alvarovans=alvarovans``,
``codex=plana`` y ``codex_e402540e=Gamsgo``. ``registry_changes.jsonl`` es el
ledger propio de registry_ops (Alt2 de DD), distinto de
``roster_changes.jsonl`` del rotador: separar ambos evita acoplar operaciones
de identidad con el historial de rotacion. ``asiento`` y ``nota`` nunca tocan
``threadId``, ``started``, ``brief`` ni ``launched_by``; esa separacion de
responsabilidad entre alta/asiento/nota es deliberada.
"""

import argparse
import contextlib
import errno
import json
import sys
import time
from datetime import datetime
from pathlib import Path


try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import fcntl
except ImportError:
    fcntl = None


RC_OK = 0
RC_INVALID = 2
RC_RECONCILE_GATE = 3
RC_CONFLICT = 4
RC_LOCK = 5
LOCK_ATTEMPTS = 20
LOCK_DELAY_S = 0.05
MUTABLE_FIELDS = (
    "status",
    "role",
    "slot",
    "supersedes",
    "reporta_a",
    "worktree",
    "generation",
)
OPTIONAL_FIELDS = (
    "nota",
    "started_nota",
    "supersedes",
    "reporta_a",
    "brief",
    "generation",
    "launched_by",
    "worktree",
)


class RegistryError(Exception):
    """Error operativo con un codigo de salida del contrato."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class LockUnavailableError(RegistryError):
    """El lock del registry no se obtuvo dentro del limite."""

    def __init__(self, path):
        super().__init__(f"bloqueo no disponible tras reintentos: {path}", RC_LOCK)


def _now():
    """Devuelve un timestamp local con offset.

    Before: el proceso puede consultar el reloj local.
    During: obtiene ``datetime.now().astimezone()`` y lo serializa ISO-8601.
    After: retorna una cadena con el offset local; no realiza I/O.
    """
    return datetime.now().astimezone().isoformat()


def _lock_try(handle):
    """Intenta bloquear el byte cero sin bloquear el proceso.

    Before: ``handle`` esta abierto en binario y su descriptor es valido.
    During: ancla la posicion en cero y usa la primitiva del sistema disponible.
    After: retorna al tomar el lock o propaga ``OSError`` si hay contencion/fallo.
    """
    handle.seek(0)
    if msvcrt is not None:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    elif fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        raise OSError(errno.ENOSYS, "sin backend de lock")


def _lock_release(handle):
    """Libera el byte cero tomado por ``_lock_try``.

    Before: ``handle`` conserva un lock tomado sobre el byte cero.
    During: reposiciona el descriptor y usa la primitiva de desbloqueo.
    After: el descriptor queda desbloqueado; propaga errores del sistema.
    """
    handle.seek(0)
    if msvcrt is not None:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    elif fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class _RegistryLock:
    """Lock acotado del fichero ``<registry>.lock``.

    Before: ``path`` identifica el lock separado del registry.
    During: abre/crea el lock y reintenta hasta 20 veces con backoff corto.
    After: mantiene el lock hasta salir del contexto o lanza ``LockUnavailableError``;
        no degrada a escritura sin lock: la contencion bloquea con rc 5. Siempre
        cierra el descriptor y libera el lock en ``finally``.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None
        self.held = False

    def __enter__(self):
        try:
            self.handle = self.path.open("a+b")
        except OSError as exc:
            raise LockUnavailableError(self.path) from exc
        try:
            for attempt in range(LOCK_ATTEMPTS):
                try:
                    _lock_try(self.handle)
                    self.held = True
                    return self
                except OSError:  # noqa: PERF203 - cada intento requiere una captura independiente
                    if attempt + 1 < LOCK_ATTEMPTS:
                        time.sleep(LOCK_DELAY_S)
            raise LockUnavailableError(self.path)
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.held:
                _lock_release(self.handle)
        finally:
            if self.handle is not None:
                with contextlib.suppress(OSError):
                    self.handle.close()
                self.handle = None
                self.held = False


def _read_registry(path):
    """Lee y valida la estructura comun del registry.

    Before: ``path`` debe ser un fichero JSON candidato.
    During: lee UTF-8, parsea JSON y comprueba que ``sessions`` sea lista y que
        cada entrada sea diccionario con ``code``.
    After: retorna el diccionario validado; cualquier fallo se convierte en rc 2.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError(
            f"registry ilegible o JSON invalido: {path}", RC_INVALID
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        raise RegistryError(
            "registry invalido: sessions debe ser una lista", RC_INVALID
        )
    if any(
        not isinstance(item, dict) or not item.get("code") for item in data["sessions"]
    ):
        raise RegistryError("registry invalido: cada sesion requiere code", RC_INVALID)
    return data


def _find_session(data, code):
    """Busca una sesion por codigo.

    Before: ``data`` ha pasado ``_read_registry`` y ``code`` es texto.
    During: recorre la lista de sesiones una vez.
    After: retorna la sesion encontrada o ``None`` sin mutar datos.
    """
    return next((item for item in data["sessions"] if item["code"] == code), None)


def _require_session(data, code):
    """Obtiene una sesion existente o eleva el conflicto de identidad.

    Before: ``data`` es un registry validado.
    During: delega la busqueda por ``code``.
    After: retorna el diccionario existente o lanza rc 4 con diagnostico claro.
    """
    item = _find_session(data, code)
    if item is None:
        raise RegistryError(f"sesion no encontrada: code={code}", RC_CONFLICT)
    return item


def _rotate_backups(path, current):
    """Rota tres generaciones y guarda el contenido previo en bak1.

    Before: ``path`` existe y ``current`` son sus bytes pre-escritura.
    During: mueve bak2 a bak3, bak1 a bak2 y escribe bak1.
    After: bak1 contiene exactamente ``current`` y las generaciones anteriores
        han avanzado una posicion; los errores de I/O se propagan.
    """
    bak1 = path.with_name(path.name + ".bak1")
    bak2 = path.with_name(path.name + ".bak2")
    bak3 = path.with_name(path.name + ".bak3")
    if bak2.exists():
        bak3.unlink(missing_ok=True)
        bak2.replace(bak3)
    if bak1.exists():
        bak2.unlink(missing_ok=True)
        bak1.replace(bak2)
    bak1.write_bytes(current)


def _write_registry(path, data):
    """Escribe el registry mediante temporal y reemplazo atomico.

    Before: ``data`` es un diccionario serializable y ``path`` es el destino.
    During: escribe ``<suffix>.tmp`` con JSON UTF-8 y newline LF, y lo reemplaza.
    After: ``path`` contiene el JSON nuevo; limpia el temporal si falla I/O.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        tmp.replace(path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _append_ledger(path, by, change, detail, reason):
    """Anade una fila propia al ledger con guardia de newline.

    Before: ``path`` puede no existir o terminar sin newline.
    During: abre append-binary, inserta newline si falta y anade una fila JSON
        con el esquema exacto del contrato.
    After: la nueva fila queda al final y ninguna fila previa se reescribe.
    """
    row = {"ts": _now(), "by": by, "change": change, "detail": detail, "reason": reason}
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() and (handle.seek(-1, 2) or True) and handle.read(1) != b"\n":
            handle.seek(0, 2)
            handle.write(b"\n")
        handle.seek(0, 2)
        handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))


def _apply_change(path, ledger, by, reason, change, detail, mutate):
    """Ejecuta una mutacion bajo lock, backup, escritura y ledger.

    Before: ``path`` existe, ``mutate`` puede modificar un registry validado y
        ``change/detail`` describen la fila de ledger.
    During: adquiere lock antes de leer, valida mediante ``mutate``, rota backup,
        actualiza ``actualizado``, escribe atomicamente y anade el ledger bajo lock.
    After: registry y ledger quedan escritos antes de liberar el lock; errores de
        validacion no escriben y errores de lock retornan rc 5 al llamador.
    """
    lock_path = path.with_name(path.name + ".lock")
    with _RegistryLock(lock_path):
        data = _read_registry(path)
        current = path.read_bytes()
        mutate(data)
        _rotate_backups(path, current)
        data["actualizado"] = _now()
        _write_registry(path, data)
        _append_ledger(ledger, by, change, detail, reason)


def _session_for_alta(args, data):
    """Construye y valida la nueva sesion de alta.

    Before: ``args`` contiene los seis campos obligatorios y ``data`` es valido.
    During: rechaza code duplicado y conserva solo opcionales explicitamente dados.
    After: retorna el diccionario listo para anadir o lanza rc 4.
    """
    if _find_session(data, args.code) is not None:
        raise RegistryError(
            f"sesion duplicada: code={args.code} ya existe", RC_CONFLICT
        )
    item = {
        "code": args.code,
        "role": args.role,
        "slot": args.slot,
        "threadId": args.thread_id,
        "started": args.started,
        "status": args.status,
    }
    for field in OPTIONAL_FIELDS:
        value = getattr(args, field)
        if value is not None:
            item[field] = value
    return item


def _handle_alta(args):
    """Valida o aplica una alta.

    Before: argparse ha validado los argumentos obligatorios.
    During: genera el plan sin escribir o ejecuta la mutacion bajo lock.
    After: imprime el dict de alta o retorna rc 0; los errores usan el contrato.
    """
    path = Path(args.registry)
    if not args.apply:
        print(
            json.dumps(
                _session_for_alta(args, _read_registry(path)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return RC_OK

    def mutate(data):
        data["sessions"].append(_session_for_alta(args, data))

    _apply_change(
        path,
        Path(args.ledger),
        args.by,
        args.reason,
        "alta",
        f"code={args.code}",
        mutate,
    )
    return RC_OK


def _handle_asiento(args):
    """Valida o aplica cambios de transicion permitidos.

    Before: ``args`` identifica un code y puede contener campos mutables.
    During: exige primero al menos un campo mutable; por tanto, si faltan ambos
        campos y el code tampoco existe, prevalece rc 2 sobre rc 4. Luego calcula
        pares viejo/nuevo o modifica solo los campos permitidos.
    After: imprime el plan o deja registry/ledger consistentes bajo lock.
    """
    changes = {
        field: getattr(args, field)
        for field in MUTABLE_FIELDS
        if getattr(args, field) is not None
    }
    if not changes:
        raise RegistryError("asiento sin campos a cambiar", RC_INVALID)
    path = Path(args.registry)
    if not args.apply:
        item = _require_session(_read_registry(path), args.code)
        plan = {
            "code": args.code,
            "cambios": {
                field: [item.get(field), value] for field, value in changes.items()
            },
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return RC_OK

    def mutate(data):
        item = _require_session(data, args.code)
        for field, value in changes.items():
            item[field] = value

    detail = f"code={args.code} campos={sorted(changes)}"
    _apply_change(
        path, Path(args.ledger), args.by, args.reason, "asiento", detail, mutate
    )
    return RC_OK


def _handle_nota(args):
    """Valida o aplica una nota reemplazando o concatenando su valor.

    Before: exactamente uno de ``nota`` y ``started_nota`` esta presente.
    During: determina el campo y calcula el valor nuevo con el separador literal.
    After: imprime el plan o persiste solo el campo de nota seleccionado.
    """
    selected = [
        (field, getattr(args, field))
        for field in ("nota", "started_nota")
        if getattr(args, field) is not None
    ]
    if len(selected) != 1:
        raise RegistryError(
            "nota exige exactamente uno de --nota o --started-nota", RC_INVALID
        )
    field, value = selected[0]
    path = Path(args.registry)
    if not args.apply:
        item = _require_session(_read_registry(path), args.code)
        old = item.get(field)
        new = value if old is None or not args.append else f"{old} | {value}"
        print(
            json.dumps(
                {
                    "code": args.code,
                    "campo": field,
                    "valor_viejo": old,
                    "valor_nuevo": new,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return RC_OK

    def mutate(data):
        item = _require_session(data, args.code)
        old = item.get(field)
        item[field] = value if old is None or not args.append else f"{old} | {value}"

    detail = (
        f"code={args.code} campo={field} modo={'append' if args.append else 'replace'}"
    )
    _apply_change(path, Path(args.ledger), args.by, args.reason, "nota", detail, mutate)
    return RC_OK


def _add_common(parser, writes=True):
    """Anade opciones comunes del CLI.

    Before: ``parser`` es un subparser de argparse.
    During: registra rutas y metadatos de mutacion.
    After: retorna ``parser`` para facilitar la construccion del parser.
    """
    parser.add_argument("--registry", required=True)
    parser.add_argument("--ledger", default=None)
    if writes:
        parser.add_argument("--by", required=True)
        parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser


def _parser():
    """Construye el parser de los tres subcomandos de Caja 1.

    Before: no requiere estado externo.
    During: registra flags obligatorios, opcionales y campos mutables.
    After: retorna un ``ArgumentParser`` listo para parsear.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    alta = _add_common(commands.add_parser("alta"))
    alta.add_argument("--code", required=True)
    alta.add_argument("--role", required=True)
    alta.add_argument("--slot", required=True)
    alta.add_argument("--thread-id", dest="thread_id", required=True)
    alta.add_argument("--started", required=True)
    alta.add_argument("--status", required=True)
    for flag in OPTIONAL_FIELDS:
        alta.add_argument("--" + flag.replace("_", "-"), dest=flag, default=None)
    asiento = _add_common(commands.add_parser("asiento"))
    asiento.add_argument("--code", required=True)
    for field in MUTABLE_FIELDS:
        asiento.add_argument("--" + field.replace("_", "-"), dest=field, default=None)
    nota = _add_common(commands.add_parser("nota"))
    nota.add_argument("--code", required=True)
    nota.add_argument("--nota", default=None)
    nota.add_argument("--started-nota", dest="started_nota", default=None)
    nota.add_argument("--append", action="store_true")
    return parser


def main(argv=None):
    """Parsea y ejecuta una operacion de registry_ops.

    Before: ``argv`` contiene un subcomando y ``--registry`` explicito.
    During: resuelve el ledger por defecto y despacha alta, asiento o nota.
    After: retorna exactamente uno de los cinco codigos documentados; imprime
        los errores operativos en stderr.
    """
    args = _parser().parse_args(argv)
    args.ledger = args.ledger or str(
        Path(args.registry).parent / "registry_changes.jsonl"
    )
    try:
        if args.command == "alta":
            return _handle_alta(args)
        if args.command == "asiento":
            return _handle_asiento(args)
        return _handle_nota(args)
    except RegistryError as exc:
        print(f"registry_ops: {exc}", file=sys.stderr)
        return exc.code
    except (OSError, TypeError, ValueError) as exc:
        print(f"registry_ops: I/O: {exc}", file=sys.stderr)
        return RC_INVALID


if __name__ == "__main__":
    sys.exit(main())
