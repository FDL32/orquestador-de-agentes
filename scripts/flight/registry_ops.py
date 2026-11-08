#!/usr/bin/env python3
"""Operaciones controladas sobre el registro de sesiones del vuelo.

Before: ``--registry`` apunta a un JSON legible con ``sessions`` como lista de
    diccionarios, y los subcomandos de escritura reciben ``--by`` y ``--reason``.
During: valida altas, asientos y notas en modo dry-run o, con ``--apply``, toma
    el lock del sistema, abre/normaliza el ledger, lee y muta, estampa
    ``actualizado``, escribe el ledger con flush, rota backups y escribe el
    registry atomico antes de liberar el lock. Los locks usan ``msvcrt`` en
    Windows y ``fcntl`` en POSIX.
After: imprime un plan JSON o aplica una mutacion durable. Los codigos son:
    0 = exito (incluido dry-run valido); 2 = entrada invalida o esquema roto;
    3 = gate operativo compartido por todo subcomando --apply;
    4 = conflicto de identidad; 5 = lock no disponible tras reintentos.

El snapshot de reconcile trae ``cuenta`` ya resuelta por quien lo genera (una
sesion con acceso MCP); registry_ops no hace esa resolucion, solo consume el
campo. La convencion externa es ``claudeAgent=brabander``,
``claudeAgent_alvarovans=alvarovans``, ``codex=plana`` y ``codex_e402540e=Gamsgo``.
``registry_changes.jsonl`` es el ledger propio de registry_ops (Alt2 de DD), distinto de
``roster_changes.jsonl`` del rotador: separar ambos evita acoplar operaciones
de identidad con el historial de rotacion. ``asiento`` y ``nota`` nunca tocan
``threadId``, ``started``, ``brief`` ni ``launched_by``; esa separacion de
responsabilidad entre alta/asiento/nota es deliberada.
"""

import argparse
import contextlib
import errno
import json
import os
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
RC_ROSTER_GATE = 3
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
SNAPSHOT_FIELDS = ("threadId", "settled", "status", "updatedAt", "modelo", "cuenta")
RECONCILE_FIELDS = ("settled", "status", "updatedAt", "modelo", "cuenta")
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
    seen_codes = set()
    for item in data["sessions"]:
        code = item["code"]
        if code in seen_codes:
            raise RegistryError(f"registry invalido: code duplicado={code}", RC_INVALID)
        seen_codes.add(code)
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


def _check_roster_gate(roster_path):
    """Comprueba el estado operativo de todos los roles activos.

    Before: ``roster_path`` apunta al JSON del roster y el gate solo se invoca
        para una escritura real.
    During: lee ``active_roles`` y examina ``estado`` (con fallback ``ACTIVO``),
        ignorando claves cuyo nombre empieza por ``_``.
    After: retorna ``None`` si todos estan activos; lanza rc 2 ante roster
        ilegible/esquema invalido y rc 3 ante cualquier estado no ACTIVO.
        ``rotate_coordinator.py:426`` lee ``current_orchestrator.get("estado")``
        y ``rotate_coordinator.py:441`` escribe literalmente ``estado`` con
        ``PENDIENTE_ACK``; este gate consume ese mismo disyunto del rotador.
    """
    try:
        roster = json.loads(Path(roster_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"roster ilegible: {roster_path}", RC_INVALID) from exc
    if not isinstance(roster, dict) or not isinstance(roster.get("active_roles"), dict):
        raise RegistryError(f"roster ilegible: {roster_path}", RC_INVALID)
    for role, entry in roster["active_roles"].items():
        if role.startswith("_"):
            continue
        if not isinstance(entry, dict):
            raise RegistryError(f"roster ilegible: active_roles.{role}", RC_INVALID)
        state = entry.get("estado", "ACTIVO")
        if state != "ACTIVO":
            raise RegistryError(f"active_roles.{role}.estado={state}", RC_ROSTER_GATE)


def _open_ledger(path):
    """Abre el ledger y corrige inmediatamente una newline final ausente.

    Before: ``path`` es el destino del ledger propio de registry_ops.
    During: abre en append-binary, inspecciona el ultimo byte y deja el handle
        posicionado al final para la fila que se escribe antes del reemplazo
        del registry.
    After: retorna un handle abierto; cualquier error de apertura se propaga sin
        tocar el registry, backups ni su contenido.
    """
    handle = path.open("a+b")
    try:
        handle.seek(0, 2)
        if handle.tell():
            handle.seek(-1, 2)
            if handle.read(1) != b"\n":
                handle.seek(0, 2)
                handle.write(b"\n")
        handle.seek(0, 2)
        return handle
    except Exception:
        handle.close()
        raise


def _append_ledger_handle(handle, by, change, detail, reason):
    """Escribe una fila en un handle de ledger ya abierto bajo el lock.

    Before: ``handle`` procede de ``_open_ledger`` y esta al final del fichero.
    During: serializa el esquema exacto con timestamp local y escribe una fila.
    After: la fila queda append-only y el handle permanece abierto para el cierre
        de la seccion critica.
    """
    row = {"ts": _now(), "by": by, "change": change, "detail": detail, "reason": reason}
    handle.seek(0, 2)
    handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    handle.flush()


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
    During: escribe ``<suffix>.tmp`` con JSON UTF-8 y newline LF, hace flush y
        fsync del fichero temporal, y despues lo reemplaza.
    After: ``path`` contiene el JSON nuevo; limpia el temporal si falla I/O.
        El fsync cubre solo el fichero, no el directorio contenedor.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _apply_change(path, ledger, roster, by, reason, change, detail, mutate):
    """Ejecuta una mutacion bajo lock, backup, escritura y ledger.

    Before: ``path`` existe, ``roster`` pasa el gate y ``mutate`` puede modificar
        un registry validado; ``change/detail`` describen la fila de ledger.
    During: aplica el gate antes del lock, abre/normaliza el ledger dentro del
        lock, lee+valida+muta, estampa ``actualizado``, escribe la fila real del
        ledger con flush, rota backups y despues escribe atomicamente el registry,
        manteniendo el mismo handle hasta liberar el lock.
    After: registry y ledger quedan escritos antes de liberar el lock. Si falla
        el append, no se toca registry ni backups (ningun bak nuevo); el ledger
        puede crearse o normalizar su newline antes de que falle la validacion.
        Si falla _write_registry despues del append y la rotacion, queda la fila
        y la rotacion sin escritura final correspondiente (sobre-auditoria doble,
        direccion segura, preferible a escribir sin rastro).
        Los errores de lock retornan rc 5 al llamador.
    """
    _check_roster_gate(roster)
    lock_path = path.with_name(path.name + ".lock")
    with _RegistryLock(lock_path):
        ledger_handle = _open_ledger(ledger)
        try:
            data = _read_registry(path)
            current = path.read_bytes()
            mutate(data)
            data["actualizado"] = _now()
            actual_detail = detail(data) if callable(detail) else detail
            _append_ledger_handle(ledger_handle, by, change, actual_detail, reason)
            _rotate_backups(path, current)
            _write_registry(path, data)
        finally:
            ledger_handle.close()


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
        ``cadena_consulta``, ``protocolo`` y ``autoridad`` son top-level del
        registry y no se crean por sesion desde alta; asiento y reconcile los
        preservan (nunca los tocan) y close_relief.py (WOT-2026-160f, fuera de
        alcance) es quien los escribira.
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
        Path(args.roster),
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
        path,
        Path(args.ledger),
        Path(args.roster),
        args.by,
        args.reason,
        "asiento",
        detail,
        mutate,
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
    _apply_change(
        path,
        Path(args.ledger),
        Path(args.roster),
        args.by,
        args.reason,
        "nota",
        detail,
        mutate,
    )
    return RC_OK


def _read_snapshot(path):
    """Lee y valida el snapshot T3 de reconcile.

    Before: ``path`` apunta a un JSON candidato a snapshot.
    During: exige una lista de diccionarios con los seis campos obligatorios y
        rechaza ``threadId`` duplicados dentro del propio snapshot.
    After: retorna la lista validada; JSON ilegible, forma incorrecta, campo
        ausente o duplicado producen rc 2. El rechazo de duplicados es una
        decision de ambiguedad del snapshot, no un requisito literal del DoD.
    """
    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"snapshot ilegible: {path}", RC_INVALID) from exc
    if not isinstance(snapshot, list):
        raise RegistryError("snapshot invalido: debe ser una lista", RC_INVALID)
    seen = []
    for entry in snapshot:
        if not isinstance(entry, dict) or any(
            field not in entry for field in SNAPSHOT_FIELDS
        ):
            raise RegistryError(
                "snapshot invalido: faltan campos obligatorios", RC_INVALID
            )
        if entry["threadId"] is None or entry["threadId"] == "":
            raise RegistryError("snapshot invalido: threadId nulo o vacio", RC_INVALID)
        if entry["threadId"] in seen:
            raise RegistryError(
                f"snapshot invalido: threadId duplicado={entry['threadId']}", RC_INVALID
            )
        seen.append(entry["threadId"])
    return snapshot


def _validate_reconcile_registry(data):
    """Rechaza threadId no nulos duplicados antes del emparejamiento.

    Before: ``data`` es un registry validado por ``_read_registry``.
    During: recorre las sesiones y cuenta solo ``threadId`` presentes; un
        duplicado vuelve ambiguo el emparejamiento por diccionario.
    After: retorna ``None`` si es univoco o lanza rc 2 con el ``threadId``
        repetido.
    """
    seen_threads = set()
    for item in data["sessions"]:
        thread_id = item.get("threadId")
        if thread_id is None:
            continue
        if thread_id in seen_threads:
            raise RegistryError(
                f"registry invalido: threadId duplicado={thread_id}", RC_INVALID
            )
        seen_threads.add(thread_id)


def _reconcile_plan(data, snapshot):
    """Calcula el plan de reconcile sin mutar el registry.

    Before: ``data`` y ``snapshot`` han pasado sus validadores respectivos.
    During: empareja por ``threadId`` y compara exclusivamente cinco campos.
    After: retorna actualizaciones y las dos listas de no-emparejados, sin crear
        sesiones ni descartar campos desconocidos.
    """
    sessions_by_thread = {
        item.get("threadId"): item for item in data["sessions"] if item.get("threadId")
    }
    snapshot_by_thread = {entry["threadId"]: entry for entry in snapshot}
    updates = []
    for entry in snapshot:
        item = sessions_by_thread.get(entry["threadId"])
        if item is None:
            continue
        changes = {
            field: [item.get(field), entry[field]]
            for field in RECONCILE_FIELDS
            if item.get(field) != entry[field]
        }
        updates.append(
            {
                "code": item["code"],
                "threadId": entry["threadId"],
                "cambios": changes,
            }
        )
    return {
        "actualizaciones": updates,
        "snapshot_sin_match": [
            entry["threadId"]
            for entry in snapshot
            if entry["threadId"] not in sessions_by_thread
        ],
        "registry_sin_actualizar": [
            item["code"]
            for item in data["sessions"]
            if item.get("threadId") not in snapshot_by_thread
        ],
    }


def _handle_reconcile(args):
    """Valida o aplica reconcile contra un snapshot T3.

    Before: ``args`` contiene registry, snapshot, metadatos y, para apply,
        roster. Dry-run no lee ni valida el roster.
    During: construye un plan por ``threadId`` o aplica solo settled/status/
        updatedAt/modelo/cuenta bajo el pipeline comun de gate, ledger, lock,
        backups y escritura atomica.
        Un snapshot invalido se valida antes del gate de roster, por lo que
        snapshot invalido + roster bloqueado devuelve rc 2.
    After: imprime el plan en dry-run o persiste el resultado con rc 0; los
        errores de snapshot, roster, lock o I/O usan el contrato global.
        ``actualizadas`` cuenta todas las sesiones emparejadas, incluso cuando
        sus cinco valores ya coinciden y ``cambios`` queda vacio.
    """
    path = Path(args.registry)
    if not args.apply:
        data = _read_registry(path)
        _validate_reconcile_registry(data)
        snapshot = _read_snapshot(args.snapshot)
        print(json.dumps(_reconcile_plan(data, snapshot), ensure_ascii=False, indent=2))
        return RC_OK

    snapshot = _read_snapshot(args.snapshot)
    counts = {"actualizadas": 0, "sin_match": 0, "sin_actualizar": 0}

    def mutate(data):
        _validate_reconcile_registry(data)
        plan = _reconcile_plan(data, snapshot)
        counts["actualizadas"] = len(plan["actualizaciones"])
        counts["sin_match"] = len(plan["snapshot_sin_match"])
        counts["sin_actualizar"] = len(plan["registry_sin_actualizar"])
        by_thread = {entry["threadId"]: entry for entry in snapshot}
        for update in plan["actualizaciones"]:
            item = _find_session(data, update["code"])
            entry = by_thread[update["threadId"]]
            for field in RECONCILE_FIELDS:
                item[field] = entry[field]

    def detail(_data):
        return (
            f"actualizadas={counts['actualizadas']} snapshot={args.snapshot} "
            f"sin_match={counts['sin_match']} sin_actualizar={counts['sin_actualizar']}"
        )

    _apply_change(
        path,
        Path(args.ledger),
        Path(args.roster),
        args.by,
        args.reason,
        "reconcile",
        detail,
        mutate,
    )
    return RC_OK


def _add_common(parser, writes=True):
    """Anade opciones comunes del CLI.

    Before: ``parser`` es un subparser de argparse.
    During: registra rutas y metadatos de mutacion.
    After: retorna ``parser`` para facilitar la construccion del parser.
    """
    parser.add_argument("--registry", required=True)
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--roster", default=None)
    if writes:
        parser.add_argument("--by", required=True)
        parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser


def _parser():
    """Construye el parser de los cuatro subcomandos del CLI.

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
    reconcile = _add_common(commands.add_parser("reconcile"))
    reconcile.add_argument("--snapshot", required=True)
    return parser


def _check_path_collisions(args):
    """Rechaza rutas efectivas que apuntan al mismo fichero.

    Before: ``args`` contiene las rutas ya resueltas por ``main`` y el
        subcomando seleccionado.
    During: compara rutas normalizadas y, cuando ambas existen, confirma la
        identidad física con ``samefile``.
    After: retorna ``None`` si no hay colisiones o lanza ``RegistryError``
        con ``RC_INVALID`` nombrando ambos flags y sus rutas.
    """
    paths = [("--registry", args.registry), ("--ledger", args.ledger)]
    if args.apply:
        paths.append(("--roster", args.roster))
    if args.command == "reconcile":
        paths.append(("--snapshot", args.snapshot))

    def collides(left, right):
        left_path = Path(left)
        right_path = Path(right)
        if os.path.normcase(str(left_path.resolve())) == os.path.normcase(
            str(right_path.resolve())
        ):
            return True
        if left_path.exists() and right_path.exists():
            try:
                return os.path.samefile(left_path, right_path)
            except OSError:
                return False
        return False

    for index, (left_flag, left_path) in enumerate(paths):
        for right_flag, right_path in paths[index + 1 :]:
            if collides(left_path, right_path):
                raise RegistryError(
                    f"rutas en colision: {left_flag}={left_path} y "
                    f"{right_flag}={right_path}",
                    RC_INVALID,
                )


def main(argv=None):
    """Parsea y ejecuta una operacion de registry_ops.

    Before: ``argv`` contiene un subcomando y ``--registry`` explicito.
    During: exige roster para apply, resuelve el ledger por defecto y despacha
        alta, asiento, nota o reconcile.
    After: retorna exactamente uno de los cinco codigos documentados; imprime
        los errores operativos en stderr. Args malformados para argparse terminan
        en SystemExit(2) emitido por argparse mismo, antes de este contrato; no
        es uno de los cinco codigos de arriba.
    """
    args = _parser().parse_args(argv)
    if args.apply and not args.roster:
        print("registry_ops: --apply requiere --roster", file=sys.stderr)
        return RC_INVALID
    args.ledger = args.ledger or str(
        Path(args.registry).parent / "registry_changes.jsonl"
    )
    try:
        _check_path_collisions(args)
        if args.command == "alta":
            return _handle_alta(args)
        if args.command == "asiento":
            return _handle_asiento(args)
        if args.command == "nota":
            return _handle_nota(args)
        return _handle_reconcile(args)
    except RegistryError as exc:
        print(f"registry_ops: {exc}", file=sys.stderr)
        return exc.code
    except (OSError, TypeError, ValueError) as exc:
        print(f"registry_ops: I/O: {exc}", file=sys.stderr)
        return RC_INVALID


if __name__ == "__main__":
    sys.exit(main())
