#!/usr/bin/env python3
"""Comprueba en solo lectura la conformidad de celdas del vuelo.

Before: ``--registry`` identifica un JSON de registro y, para los modos que
    miden T3, ``--store`` identifica una base SQLite legible en modo read-only.
During: carga sesiones y consulta solamente hilos concretos por ``thread_id``;
    aplica las reglas de celda, corte, emparejamiento, vivos y cuentas sin
    modificar ningun fichero.
After: devuelve 0 si todo lo medible es conforme, 2 si hay violacion y 3 si
    falta cualquier dato necesario para medir; el agregado da prioridad a 2,
    despues a 3 y nunca convierte NO MEDIDO en verde.
"""

import argparse
import importlib.util
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


RC_OK = 0
RC_VIOLATION = 2
RC_NOT_MEASURED = 3
CUTOFF_DATE = "2026-11-10"
CELLS_CUTOFF = datetime.fromisoformat("2026-11-24T00:00:00+01:00")
REGISTRY_ENV = "FLIGHT_DIR"
STORE_ENV = "T3_STATE_DB"
THREADS_TABLE = "orchestration_v2_projection_threads"


class MeasurementError(Exception):
    """Indica que una comprobacion no pudo medir su dato de entrada.

    Before: una lectura o validacion encuentra un dato ausente o ilegible.
    During: conserva la causa para que el modo CLI la traduzca a rc 3.
    After: no modifica estado y permite distinguir NO MEDIDO de violacion.
    """


class CellDeclarationError(ValueError):
    """Indica que la declaracion de celdas no es verificable.

    Before: una sesion posterior al corte exige una declaracion de agents.json.
    During: conserva el fallo de estructura o coherencia sin degradar a regex legacy.
    After: el llamador lo traduce a ``RC_VIOLATION`` y no a ``NO MEDIDO``.
    """


RE_ACTIVA_PREFIX = re.compile(r"^ACTIVA(\s|$)")
# Par legacy del canon P35; registry_ops._validate_cell_requirements los lee como
# atributos de modulo (checker.RE_TRIADOR y checker.RE_REVISOR_TR) para validar
# cada alta de triaje.
RE_TRIADOR = re.compile(r"(?<![a-z0-9])gemma4(?![a-z0-9])")
RE_REVISOR_TR = re.compile(r"(?<![a-z0-9])mimo-v2\.6-flash(?![a-z0-9])")


def _model_pattern(model):
    """Construye el patron de modelo a partir de una declaracion canonica.

    Before: ``model`` es el modelo textual resuelto desde ``agents.json``.
    During: elimina el prefijo de proveedor y exige fronteras de identidad.
    After: devuelve un regex que tolera separadores equivalentes sin aceptar
        prefijos, sufijos de version ni subcadenas de otro modelo.
    """
    if not isinstance(model, str) or not model.strip():
        raise CellDeclarationError("modelo de celda no textual")
    core = model.split("/", 1)[-1].casefold().strip()
    escaped = "".join("[-._ ]" if char in "-._ " else re.escape(char) for char in core)
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![\s\-._]?[a-z0-9])")


def _load_account_cycle_module():
    """Carga account_cycle.py solo cuando una declaracion nueva lo necesita.

    Before: el comprobador puede ejecutarse para sesiones legacy sin config nueva.
    During: importa el modulo por ruta, sin convertirlo en dependencia de import.
    After: devuelve sus constantes de cuenta o eleva ``CellDeclarationError``.
    """
    path = Path(__file__).resolve().with_name("account_cycle.py")
    try:
        spec = importlib.util.spec_from_file_location("cell_account_cycle", path)
        if spec is None or spec.loader is None:
            raise CellDeclarationError(f"no se pudo cargar ciclo: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except (OSError, ImportError, AttributeError, CellDeclarationError) as exc:
        if isinstance(exc, CellDeclarationError):
            raise
        raise CellDeclarationError(f"ciclo de cuentas ilegible: {exc}") from exc


def _load_cell_declaration(path, needed=("im", "tr")):  # noqa: C901
    """Lee y valida ``celdas`` y resuelve sus modelos por ``backend_key``.

    Before: ``path`` identifica agents.json y ``needed`` nombra las celdas que
        exige el modo que va a medir (``--check-im`` no lee ``celdas.tr`` ni al
        reves: una declaracion rota en la otra celda no puede marcar de rojo un
        comprobador cuyo ambito no la incluye).
    During: valida tipos, claves, niveles, cuentas, fases y la bandera de FASE B
        unicamente de las celdas pedidas.
    After: devuelve una declaracion normalizada para esas celdas o eleva
        declaracion no verificable, siempre fail-closed.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CellDeclarationError(f"agents.json ilegible: {exc}") from exc
    if not isinstance(document, dict):
        raise CellDeclarationError("agents.json no es objeto")
    registry = document.get("ensemble_registry")
    backends = registry.get("backend_keys") if isinstance(registry, dict) else None
    cells = document.get("celdas")
    if not isinstance(backends, dict) or not isinstance(cells, dict):
        raise CellDeclarationError("declaracion celdas ausente o malformada")

    def resolve(cell_name, role_name):
        cell = cells.get(cell_name)
        entry = cell.get(role_name) if isinstance(cell, dict) else None
        key = entry.get("backend_key") if isinstance(entry, dict) else None
        backend = backends.get(key) if isinstance(key, str) else None
        model = backend.get("model") if isinstance(backend, dict) else None
        if not isinstance(model, str) or not model.strip():
            raise CellDeclarationError(f"backend_key invalido: {cell_name}.{role_name}")
        return model.strip(), backend

    declaration = {}
    if "im" in needed:
        im = cells.get("im")
        if not isinstance(im, dict):
            raise CellDeclarationError("celdas.im ausente")
        builder_model, _ = resolve("im", "builder")
        revisor_model, revisor_backend = resolve("im", "revisor")
        v1_model, _ = resolve("im", "v1")
        if not isinstance(im.get("nivel"), str) or not isinstance(
            im.get("esfuerzo"), str
        ):
            raise CellDeclarationError("nivel/esfuerzo IM no textuales")
        if im["nivel"] != revisor_backend.get("nivel") or im[
            "esfuerzo"
        ] != revisor_backend.get("esfuerzo"):
            raise CellDeclarationError("nivel/esfuerzo IM divergen del revisor")
        account_cycle = _load_account_cycle_module()
        expected_account = {
            "preferente": account_cycle.PREFERIDA,
            "refugio": account_cycle.REFUGIO,
        }
        if im.get("cuenta") != expected_account:
            raise CellDeclarationError("cuenta IM diverge del ciclo")
        phases = im.get("fase_aplicable")
        if (
            not isinstance(phases, list)
            or not phases
            or not all(isinstance(phase, str) for phase in phases)
            or len(phases) != len(set(phases))
            or any(phase not in {"A", "B", "C", "D"} for phase in phases)
        ):
            raise CellDeclarationError("fase_aplicable IM malformada")
        if im.get("fase_B_subagentes_largos_claude") is not False:
            raise CellDeclarationError("restriccion FASE B ausente o activa")
        declaration["im"] = {
            "builder": _model_pattern(builder_model),
            "revisor": _model_pattern(revisor_model),
            "v1": _model_pattern(v1_model),
            "nivel": im["nivel"],
            "esfuerzo": im["esfuerzo"],
            "cuenta": expected_account,
            "fase": phases,
        }
    if "tr" in needed:
        tr = cells.get("tr")
        if not isinstance(tr, dict):
            raise CellDeclarationError("celdas.tr ausente")
        triador_model, _ = resolve("tr", "triador")
        tr_revisor_model, _ = resolve("tr", "revisor")
        declaration["tr"] = {
            "triador": _model_pattern(triador_model),
            "revisor": _model_pattern(tr_revisor_model),
        }
    return declaration


def _started_datetime(session):
    """Parsea ``started`` con zona para clasificar la frontera de celdas.

    Before: una sesion puede omitir ``started`` o contener una fecha invalida.
    During: parsea ISO y rechaza timestamps naive como ilegibles.
    After: devuelve datetime aware o ``None`` para aplicar reglas nuevas.
    """
    started = session.get("started")
    if not isinstance(started, str) or not started.strip():
        return None
    try:
        parsed = datetime.fromisoformat(started.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _uses_new_cell_rules(session):
    """Indica si una sesion IM/TR cruza la frontera de celdas.

    Before: ``session`` es una sesion gobernada por una celda.
    During: compara timestamps aware contra ``CELLS_CUTOFF``.
    After: devuelve ``True`` para ausencia/ilegalidad o fecha inclusiva nueva.
    """
    started = _started_datetime(session)
    return started is None or started >= CELLS_CUTOFF


def _default_agents_json_path():
    """Ruta por defecto de la declaracion de celdas, sin leerla.

    Before: el CLI y los llamadores directos deben compartir la misma fuente.
    During: parte de la raiz del repo del propio modulo, no del cwd.
    After: devuelve ``<raiz>/.agent/config/agents.json``.
    """
    return Path(__file__).resolve().parents[2] / ".agent" / "config" / "agents.json"


def _resolve_declaration(sessions, role, declaration):
    """Resuelve la declaracion que exigen las sesiones medidas de ``role``.

    Before: ``declaration`` viene del CLI o es ``None`` cuando el llamador es
        directo (``flight_stall_check`` llama ``check_tr`` sin tercer argumento
        y no puede recibir una excepcion).
    During: solo si alguna sesion de ese rol cruza ``CELLS_CUTOFF`` y todavia no
        hay declaracion, la carga perezosamente de la ruta por defecto; cualquier
        fallo de lectura se convierte en ``None``, que el modo traduce a rc 2.
    After: la declaracion normalizada pedida o ``None``; nunca una excepcion.
    """
    if declaration is not None:
        return declaration
    if not any(
        session.get("role") == role and _uses_new_cell_rules(session)
        for session in sessions
    ):
        return None
    # El rol de sesion y el nombre de celda no son el mismo identificador:
    # ``_load_cell_declaration`` valida por celda ("im"/"tr").
    cell_name = "im" if role == "implantacion" else "tr"
    try:
        return _load_cell_declaration(_default_agents_json_path(), (cell_name,))
    except CellDeclarationError:
        return None


def is_activa(status):
    """Comprueba el predicado canonico de estado activo.

    Before: ``status`` procede del registro y puede ser cualquier valor.
    During: aplica literalmente ``^ACTIVA(\\s|$)`` sin lista blanca adicional.
    After: devuelve ``True`` solo para ``ACTIVA`` y sus estados con sufijo.
    """
    return bool(RE_ACTIVA_PREFIX.match(str(status or "")))


def _load_store_module():
    """Carga el abridor oficial de statev2 por ruta.

    Before: este modulo esta junto a ``verify_user_authorization.py``.
    During: importa con importlib sin alterar ``sys.path``.
    After: devuelve el modulo que expone ``open_store_ro`` o eleva medicion.
    """
    path = Path(__file__).resolve().with_name("verify_user_authorization.py")
    try:
        spec = importlib.util.spec_from_file_location("verify_user_authorization", path)
        if spec is None or spec.loader is None:
            raise MeasurementError(f"no se pudo cargar abridor: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    except (OSError, ImportError, AttributeError, MeasurementError) as exc:
        if isinstance(exc, MeasurementError):
            raise
        raise MeasurementError(f"abridor T3 ilegible: {exc}") from exc


def _open_store(path):
    """Abre statev2 mediante el helper canonico y valida la tabla consultada.

    Before: ``path`` es la ruta candidata al almacen.
    During: abre en read-only y comprueba la tabla sin recorrer sus filas.
    After: devuelve una conexion SQLite o eleva ``MeasurementError``.
    """
    try:
        connection = _load_store_module().open_store_ro(path)
        columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({THREADS_TABLE})")
        }
        required = {"thread_id", "deleted_at", "payload_json", "provider_instance_id"}
        if not required <= columns:
            connection.close()
            raise MeasurementError("tabla T3 sin columnas requeridas")
        return connection
    except (OSError, RuntimeError, sqlite3.Error, ValueError, TypeError) as exc:
        raise MeasurementError(f"almacen T3 ilegible: {exc}") from exc


def _thread_row(connection, thread_id):
    """Lee una fila de hilo concreta por su clave primaria.

    Before: ``connection`` apunta al almacen read-only y ``thread_id`` no esta vacio.
    During: ejecuta una consulta parametrizada con ``WHERE thread_id = ?``.
    After: devuelve un dict de fila o ``None`` si el hilo no existe.
    """
    if not thread_id:
        return None
    row = connection.execute(
        "SELECT thread_id, deleted_at, payload_json, provider_instance_id "
        "FROM orchestration_v2_projection_threads WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _payload(row):
    """Parsea el payload de una fila de hilo.

    Before: ``row`` contiene ``payload_json``.
    During: decodifica JSON y exige un objeto.
    After: devuelve el objeto o eleva ``MeasurementError``.
    """
    try:
        value = json.loads(row["payload_json"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MeasurementError(f"payload de hilo ilegible: {exc}") from exc
    if not isinstance(value, dict):
        raise MeasurementError("payload de hilo no es objeto")
    return value


def is_im_vivo(session, settled_lookup):
    """Determina si una sesion de implantacion sigue viva.

    Before: ``session`` es un registro de sesion y ``settled_lookup`` consulta T3.
    During: combina rol, estado del registry y asentamiento externo.
    After: devuelve booleano; propaga fallos de ``settled_lookup`` para fail-closed.

    Decision explicita (c-01, CO-69 ronda 6): un hilo AUSENTE del almacen no se
    puede probar asentado, asi que cuenta como VIVO. Para el tope de 2 eso
    sobre-cuenta (puede dar falso rojo) y nunca sub-cuenta (no puede dar falso
    verde); es la direccion fail-closed que se quiere. El comportamiento lo
    fijan ``test_im_vivos_tres_rc_no_cero`` (tabla vacia + 3 ACTIVA -> rc 2) y
    ``test_im_vivos_dos_rc0`` (tabla vacia + 2 -> rc 0).
    """
    return (
        session.get("role") == "implantacion"
        and is_activa(session.get("status"))
        and not settled_lookup(session.get("threadId"))
    )


def live_ims(sessions, settled_lookup):
    """Devuelve las sesiones IM vivas usando el predicado canonico.

    Before: ``sessions`` es una lista de diccionarios y el lookup es callable.
    During: filtra sin cambiar los registros de entrada.
    After: retorna una lista nueva de IM vivos.
    """
    return [session for session in sessions if is_im_vivo(session, settled_lookup)]


def _registry(path):
    """Carga y valida el registro de sesiones.

    Before: ``path`` apunta a un JSON accesible.
    During: lee el fichero y valida ``sessions`` como lista de objetos.
    After: retorna la lista de sesiones o eleva ``MeasurementError``.
    """
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise MeasurementError(f"registry ilegible: {exc}") from exc
    sessions = value.get("sessions") if isinstance(value, dict) else None
    if not isinstance(sessions, list) or not all(
        isinstance(item, dict) for item in sessions
    ):
        raise MeasurementError("registry sin sessions valida")
    return sessions


def _default_registry():
    """Resuelve el registry desde ``FLIGHT_DIR``.

    Before: el entorno puede contener un directorio de vuelo.
    During: anade ``session_registry.json`` solo si existe.
    After: retorna una ruta existente o ``None``.
    """
    raw = os.environ.get(REGISTRY_ENV)
    if not raw:
        return None
    path = Path(raw) / "session_registry.json"
    return path if path.is_file() else None


def _sessions_for_measure(sessions, cutoff):
    """Filtra primero IM/TR y excluye sesiones anteriores al corte.

    Before: ``sessions`` contiene sesiones de cualquier rol y fechas ISO o
        valores ausentes.
    During: descarta primero roles no gobernados; compara fechas datables con
        ``cutoff`` y conserva fechas ausentes o ilegibles para medirlas.
    After: devuelve solo IM/TR medibles, fail-closed hacia medicion y nunca
        eleva por un ``started`` ausente o ilegible.
    """
    result = []
    for session in sessions:
        if session.get("role") not in {"implantacion", "triaje"}:
            continue
        started = session.get("started")
        # CO-69 ronda 8: solo un texto puede conceder la exencion de fecha. Un
        # entero JSON como 20261109 stringifica a "20261109" (ISO basico, que
        # fromisoformat acepta desde Python 3.11) y quedaria "antes del corte":
        # se trata como medible, igual que None o ilegible (fail-closed hacia
        # medicion).
        if not isinstance(started, str) or not started.strip():
            result.append(session)
            continue
        try:
            if (
                datetime.fromisoformat(started.strip().replace("Z", "+00:00"))
                .date()
                .isoformat()
                >= cutoff
            ):
                result.append(session)
        except ValueError as exc:
            del exc
            result.append(session)
    return result


def _cell(session):
    """Obtiene una declaracion de celda como diccionario no vacio."""
    value = session.get("celda")
    return value if isinstance(value, dict) else None


def _builder_name(builder):
    """Devuelve el nombre del builder declarado por la celda.

    Before: ``builder`` es la celda declarada, en la forma string historica o
        en el dict que el resto del comprobador acepta (``name`` y ``threadId``,
        ver ``_child_id``).
    During: acepta solo texto: un dict cuenta si ``name`` es ``str`` con
        contenido tras ``strip``; un builder string cuenta tal cual; cualquier
        otro tipo (``None``, numeros, objetos) NO declara nombre.
    After: devuelve el nombre o ``""``; nunca el repr de un dict ni el texto de
        un numero, que es lo que permitia colar valores no identificables como
        builder (c-02 ronda 5 y barrido de la clase, CO-69 ronda 7).
    """
    if isinstance(builder, dict):
        name = builder.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return ""
    if isinstance(builder, str):
        return builder.strip()
    return ""


def check_im(sessions, cutoff, declaration=None):
    """Comprueba IM legacy o los siete datos de la declaracion nueva.

    Before: ``sessions`` contiene IM medibles y ``declaration`` solo llega del
        CLI; un llamador directo (sin tercer argumento) tambien debe medir.
    During: resuelve perezosamente la declaracion por defecto si alguna sesion
        cruza ``CELLS_CUTOFF`` y aplica regex legacy a rondas anteriores, o
        valida builder, revisor, V1, nivel, esfuerzo, cuenta y fase en rondas
        nuevas.
    After: ``RC_OK``, o ``RC_VIOLATION`` ante omision, discrepancia o
        declaracion ilegible; nunca acepta omision como conformidad.
    """
    measured = [
        s
        for s in _sessions_for_measure(sessions, cutoff)
        if s.get("role") == "implantacion"
    ]
    if not measured:
        return RC_NOT_MEASURED
    resolved = _resolve_declaration(measured, "implantacion", declaration)
    for session in measured:
        cell = _cell(session)
        revisor, builder = (cell or {}).get("revisor"), (cell or {}).get("builder")
        builder_text = _builder_name(builder)
        if _uses_new_cell_rules(session):
            if resolved is None:
                return RC_VIOLATION
            required = resolved["im"]
            v1 = (cell or {}).get("v1")
            nivel = (cell or {}).get("nivel")
            esfuerzo = (cell or {}).get("esfuerzo")
            cuenta = (cell or {}).get("cuenta")
            fase = (cell or {}).get("fase")
            if (
                not builder_text
                or not required["builder"].search(builder_text.casefold())
                or not isinstance(revisor, str)
                or not revisor.strip()
                or revisor.strip().casefold() == builder_text.casefold()
                or not required["revisor"].search(revisor.strip().casefold())
                or not isinstance(v1, str)
                or not v1.strip()
                or not required["v1"].search(v1.strip().casefold())
                or not isinstance(nivel, str)
                or nivel != required["nivel"]
                or not isinstance(esfuerzo, str)
                or esfuerzo != required["esfuerzo"]
                or not isinstance(cuenta, dict)
                or cuenta != required["cuenta"]
                or not isinstance(fase, list)
                or fase != required["fase"]
                or any(item not in {"A", "B", "C", "D"} for item in fase)
            ):
                return RC_VIOLATION
            continue
        if (
            not isinstance(revisor, str)
            or not revisor.strip()
            or not builder_text
            or revisor.strip().casefold() == builder_text.casefold()
        ):
            return RC_VIOLATION
        lowered = builder_text.casefold()
        # MINOR-2 (BA03 ronda 7): "codex" exige frontera, igual que "sol"; por
        # subcadena un builder "anticodex" se colaba como codex valido.
        if not re.search(r"(?<![a-z0-9])codex(?![a-z0-9])", lowered) or re.search(
            r"(?<![a-z0-9])sol(?![a-z0-9])", lowered
        ):
            return RC_VIOLATION
    return RC_OK


def check_tr(sessions, cutoff, declaration=None):
    """Comprueba TR legacy o los modelos de la declaracion nueva.

    Before: cada celda TR declara ``triador`` y ``revisor`` sin validar y el
        llamador directo (``flight_stall_check``) no aporta ``declaration``.
    During: resuelve perezosamente la declaracion por defecto cuando alguna
        sesion cruza ``CELLS_CUTOFF``; acepta el triador historico como
        diccionario via ``_builder_name`` y lee ``supervisor`` solo si falta
        ``revisor``; las rondas nuevas comparan contra los modelos declarados y
        las anteriores contra el par legacy con frontera de palabra.
    After: 2 si alguna celda TR incumple el par o la declaracion no es
        verificable, 0 si todas lo cumplen y 3 si no hay celdas medibles.
    """
    measured = [
        s for s in _sessions_for_measure(sessions, cutoff) if s.get("role") == "triaje"
    ]
    if not measured:
        return RC_NOT_MEASURED
    resolved = _resolve_declaration(measured, "triaje", declaration)
    for session in measured:
        cell = _cell(session) or {}
        triador = cell.get("triador")
        revisor = cell["revisor"] if "revisor" in cell else cell.get("supervisor")
        triador_text = _builder_name(triador)
        if not triador_text or not isinstance(revisor, str) or not revisor.strip():
            return RC_VIOLATION
        if _uses_new_cell_rules(session):
            if resolved is None:
                return RC_VIOLATION
            required = resolved["tr"]
            if not required["triador"].search(triador_text.casefold()) or not required[
                "revisor"
            ].search(revisor.strip().casefold()):
                return RC_VIOLATION
        elif not RE_TRIADOR.search(triador_text.casefold()) or not RE_REVISOR_TR.search(
            revisor.casefold()
        ):
            return RC_VIOLATION
    return RC_OK


def check_lenses(sessions, cutoff):
    """Exige al menos dos modelos distintos en cada celda TR e IM.

    Before: cada celda puede declarar ``lentes`` como lista de cualquier cosa
        (texto, nulos, numeros u objetos) o no declararlo.
    During: uses a non-empty ``session.lentes`` list first, normalizing its
        string entries or dictionary ``modelo``/``lente`` values; otherwise it
        falls back to the cell list and compares casefolded names.
    After: 2 si alguna celda medible no tiene dos lentes distintas, 0 si todas
        las tienen y 3 si no hay celdas medibles.
    """
    measured = [
        s
        for s in _sessions_for_measure(sessions, cutoff)
        if s.get("role") in {"triaje", "implantacion"}
    ]
    if not measured:
        return RC_NOT_MEASURED
    for session in measured:
        session_lenses = session.get("lentes")
        if isinstance(session_lenses, list) and session_lenses:
            lenses = session_lenses
        else:
            lenses = (_cell(session) or {}).get("lentes")
        if not isinstance(lenses, list):
            return RC_VIOLATION
        named = set()
        for item in lenses:
            if isinstance(item, str):
                name = item.strip()
            elif isinstance(item, dict):
                candidate = item.get("modelo", item.get("lente"))
                name = candidate.strip() if isinstance(candidate, str) else ""
            else:
                name = ""
            if name:
                named.add(name.casefold())
        if len(named) < 2:
            return RC_VIOLATION
    return RC_OK


def check_cutoff(sessions, cutoff):
    """Valida que exista una sesion exenta y que ninguna previa se mida.

    Before: ``sessions`` contiene sesiones con ``started`` y ``cutoff`` es una
        fecha ISO inclusiva.
    During: identifica sesiones anteriores y contrasta ese conjunto con el
        conjunto medido por ``_sessions_for_measure``.
    After: devuelve 3 si no hay previas, 2 si una previa entra en medicion y 0
        cuando las previas quedan exentas. La rama rc 2 es un guard de
        regresion: el filtro canonico mantiene ambos conjuntos disjuntos.
    """
    if not sessions:
        return RC_NOT_MEASURED
    previous = []
    governed = [
        session
        for session in sessions
        if session.get("role") in {"implantacion", "triaje"}
    ]
    for session in governed:
        started = session.get("started")
        # CO-69 ronda 8: un `started` no textual (p.ej. el entero 20261109) no
        # cuenta como sesion previa al corte; solo el texto puede eximir.
        if not isinstance(started, str) or not started.strip():
            continue
        try:
            date = datetime.fromisoformat(started.strip().replace("Z", "+00:00")).date()
        except ValueError as exc:
            del exc
            continue
        if date.isoformat() < cutoff:
            previous.append(session)
    if not previous:
        return RC_NOT_MEASURED
    measured = _sessions_for_measure(sessions, cutoff)
    if any(any(candidate is session for candidate in measured) for session in previous):
        return RC_VIOLATION
    return RC_OK


def _child_id(builder):
    """Extrae un id de hilo hijo declarado por la celda.

    Before: ``builder`` es la celda declarada (dict con ``threadId`` o la forma
        string historica).
    During: acepta solo ids textuales no vacios; cualquier otro tipo
        (``None``, numeros, objetos) no declara hijo medible.
    After: devuelve el id o ``None``; nunca un objeto que haga fallar
        ``startswith`` en los llamadores (barrido de la clase, CO-69 ronda 7).
    """
    if isinstance(builder, dict):
        for key in ("threadId", "thread_id", "id"):
            value = builder.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    if not isinstance(builder, str):
        return None
    return builder if builder.startswith("thread:delegated-task:") else None


def _settlement(settled_at, unsettled_at):
    """Valida y parsea las fechas de asentamiento del payload.

    Before: ``settled_at`` y ``unsettled_at`` vienen del payload sin validar.
    During: exige texto con contenido (``unsettled_at`` puede ser ``None``) y
        parsea ISO; un valor no textual no puede decidir asentamiento.
    After: devuelve ``(settled_date, unsettled_date|None)`` o eleva
        ``MeasurementError`` (NO MEDIDO).
    """
    if not isinstance(settled_at, str) or not settled_at.strip():
        raise MeasurementError("settledAt no textual")
    if unsettled_at is not None and (
        not isinstance(unsettled_at, str) or not unsettled_at.strip()
    ):
        raise MeasurementError("unsettledAt no textual")
    try:
        settled_date = datetime.fromisoformat(settled_at.strip().replace("Z", "+00:00"))
        unsettled_date = (
            None
            if unsettled_at is None
            else datetime.fromisoformat(unsettled_at.strip().replace("Z", "+00:00"))
        )
    except (TypeError, ValueError) as exc:
        raise MeasurementError("fecha de asentamiento ilegible") from exc
    return settled_date, unsettled_date


def _store_lookup(path):
    """Construye lookups de asentamiento, pairing y cuenta sobre un almacen."""
    connection = _open_store(path)

    def row(thread_id):
        return _thread_row(connection, thread_id)

    def settled(thread_id):
        """Indica si el hilo esta asentado en el almacen T3.

        Before: ``thread_id`` identifica un hilo del registro de vuelo.
        During: lee la fila y resuelve ``deleted_at``, ``settledAt`` y
            ``unsettledAt`` del payload, con la rama legacy ``status``.
        After: True si esta asentado; False si no, o si el hilo NO EXISTE.

        Decision explicita (c-01, CO-69 ronda 6): hilo ausente -> False (no
        asentado). Un hilo que no se puede leer no se puede probar asentado, de
        modo que cuenta como VIVO en ``is_im_vivo``: sobre-cuenta el tope
        (falso rojo posible) y nunca lo sub-cuenta (falso verde imposible).
        """
        value = row(thread_id)
        if value is None:
            return False
        payload = _payload(value)
        status = payload.get("status") or payload.get("threadStatus")
        if value.get("deleted_at") or str(status or "").casefold() == "settled":
            return True
        settled_at = payload.get("settledAt")
        if settled_at is None:
            return False
        # CO-69 ronda 9: las fechas de asentamiento solo se interpretan si son
        # texto; un valor no textual (p.ej. el entero 20261110, que stringifica
        # a ISO basico desde 3.11) no puede decidir que un IM esta asentado: es
        # NO MEDIDO, no un veredicto.
        settled_date, unsettled_date = _settlement(
            settled_at, payload.get("unsettledAt")
        )
        if unsettled_date is None:
            return True
        try:
            return unsettled_date < settled_date
        except TypeError as exc:
            raise MeasurementError("fechas de asentamiento incompatibles") from exc

    return connection, row, settled


def check_pairing(sessions, cutoff, store):
    """Comprueba que cada IM tenga su hijo delegated-task bien emparentado.

    Before: ``store`` es el almacen T3 real o un fixture con la tabla
        ``orchestration_v2_projection_threads``; ``sessions`` son las sesiones
        del registro de vuelo.
    During: por cada IM medible lee el hilo hijo declarado en la celda y exige
        ``lineage.parentThreadId`` igual al ``threadId`` del IM y
        ``lineage.relationshipToParent`` igual a ``subagent``.
    After: 0 si todos los hijos emparentan, 2 si el hijo falta o su
        ``parentThreadId`` es ajeno, y 3 (NO MEDIDO) si el almacen no guarda el
        linaje necesario.

    c-12 (CO-69): medido en el almacen REAL en solo lectura (conexion
    ``sqlite3`` abierta con ``mode=ro`` sobre ``~/.t3/userdata/statev2.sqlite``):
    las 586 filas con prefijo ``thread:delegated-task:`` guardan ``lineage`` con
    ``parentThreadId``, ``rootThreadId`` y ``relationshipToParent``, y el valor
    es ``subagent`` en el 100 % de los hijos delegados. La clave esta en TODAS
    las filas del almacen: snapshot 2026-11-10 de 1431 filas, 773 con
    ``subagent`` y 658 con ``None`` por no ser hijas. Por eso la ausencia del
    campo o un valor distinto NO se juzga como violacion: es NO MEDIDO, porque
    el emparejamiento deja de estar declarado por el almacen.
    """
    measured = [
        s
        for s in _sessions_for_measure(sessions, cutoff)
        if s.get("role") == "implantacion"
    ]
    if not measured:
        return RC_NOT_MEASURED
    connection, row, _ = _store_lookup(store)
    try:
        for session in measured:
            child_id = _child_id((_cell(session) or {}).get("builder"))
            if not child_id or not child_id.startswith("thread:delegated-task:"):
                return RC_NOT_MEASURED
            child = row(child_id)
            if child is None:
                return RC_VIOLATION
            payload = _payload(child)
            lineage = payload.get("lineage")
            if not isinstance(lineage, dict) or not lineage.get("parentThreadId"):
                return RC_NOT_MEASURED
            # c-12 (CO-69): el almacen real guarda relationshipToParent en el
            # 100 % de los hijos delegados (ver docstring: 583/583). Sin ese
            # dato el emparejamiento no esta declarado: NO MEDIDO, no veredicto.
            if lineage.get("relationshipToParent") != "subagent":
                return RC_NOT_MEASURED
            if lineage.get("parentThreadId") != session.get("threadId"):
                return RC_VIOLATION
    finally:
        connection.close()
    return RC_OK


def check_im_vivos(sessions, cutoff, store):
    """Exige como maximo dos IM vivos."""
    measured = _sessions_for_measure(sessions, cutoff)
    if not measured:
        return RC_NOT_MEASURED
    connection, _, settled = _store_lookup(store)
    try:
        vivos = live_ims(measured, settled)
    finally:
        connection.close()
    return RC_VIOLATION if len(vivos) > 2 else RC_OK


def check_im_cuentas(sessions, cutoff, store):
    """Exige cuentas provider distintas para IM vivos."""
    measured = _sessions_for_measure(sessions, cutoff)
    if not measured:
        return RC_NOT_MEASURED
    connection, row, settled = _store_lookup(store)
    try:
        vivos = live_ims(measured, settled)
        accounts = []
        for session in vivos:
            child_id = _child_id((_cell(session) or {}).get("builder"))
            # c-17 (CO-69 ronda 7): las cuentas solo se pueden leer de un hijo
            # delegated-task; sin el prefijo no hay dato medible (NO MEDIDO),
            # no un verde por omision.
            if not child_id or not child_id.startswith("thread:delegated-task:"):
                return RC_NOT_MEASURED
            child = row(child_id)
            if child is None:
                return RC_NOT_MEASURED
            account = child.get("provider_instance_id") or _payload(child).get(
                "providerInstanceId"
            )
            if not account:
                return RC_NOT_MEASURED
            accounts.append(account)
    finally:
        connection.close()
    return RC_VIOLATION if len(accounts) != len(set(accounts)) else RC_OK


def _paths(args):
    """Resuelve defaults CLI sin crear ningun fichero."""
    registry = Path(args.registry) if args.registry else _default_registry()
    store = Path(
        args.store
        or os.environ.get(
            STORE_ENV, Path.home() / ".t3" / "userdata" / "statev2.sqlite"
        )
    )
    return registry, store, args.cutoff or CUTOFF_DATE


def _run_mode(name, sessions, cutoff, store, agents_json):
    """Ejecuta un modo individual con carga perezosa de la declaracion.

    Before: ``sessions`` ya esta validado y ``agents_json`` identifica la fuente
        declarativa candidata.
    During: lee la fuente solo si el modo IM/TR tiene una sesion nueva; un fallo
        declarativo se traduce a violacion cerrada.
    After: devuelve el codigo del modo sin tocar ningun artefacto.
    """
    try:
        declaration = None
        if name in {"im", "tr"} and any(
            session.get("role") == ("implantacion" if name == "im" else "triaje")
            and _uses_new_cell_rules(session)
            for session in sessions
        ):
            declaration = _load_cell_declaration(agents_json, (name,))
        if name == "im":
            return check_im(sessions, cutoff, declaration)
        if name == "tr":
            return check_tr(sessions, cutoff, declaration)
        if name == "lenses":
            return check_lenses(sessions, cutoff)
        if name == "cutoff":
            return check_cutoff(sessions, cutoff)
        if name == "pairing":
            return check_pairing(sessions, cutoff, store)
        if name == "im-vivos":
            return check_im_vivos(sessions, cutoff, store)
        return check_im_cuentas(sessions, cutoff, store)
    except (CellDeclarationError, MeasurementError, sqlite3.Error, RuntimeError) as exc:
        if isinstance(exc, CellDeclarationError):
            print(f"VIOLACION {name}: {exc}", file=sys.stderr)
            return RC_VIOLATION
        print(f"NO MEDIDO {name}: {exc}", file=sys.stderr)
        return RC_NOT_MEASURED


def main(argv=None):
    """Ejecuta el modo solicitado y conserva precedencia violation > not measured.

    Before: argumentos CLI validos.
    During: carga registry y ejecuta un modo o todos en read-only.
    After: retorna 0, 2 o 3 y solo imprime diagnostico; nunca escribe estado.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry")
    parser.add_argument("--store")
    parser.add_argument("--cutoff", default=CUTOFF_DATE)
    parser.add_argument("--agents-json")
    parser.add_argument("--read-only", action="store_true")
    for mode in ("im", "tr", "lenses", "cutoff", "pairing", "im-vivos", "im-cuentas"):
        parser.add_argument(f"--check-{mode}", action="store_true")
    args = parser.parse_args(argv)
    selected = [
        name
        for name in (
            "im",
            "tr",
            "lenses",
            "cutoff",
            "pairing",
            "im-vivos",
            "im-cuentas",
        )
        if getattr(args, f"check_{name.replace('-', '_')}")
    ]
    if not selected or args.read_only:
        selected = ("im", "tr", "lenses", "cutoff", "pairing", "im-vivos", "im-cuentas")
    registry, store, cutoff = _paths(args)
    agents_json = (
        Path(args.agents_json) if args.agents_json else _default_agents_json_path()
    )
    if registry is None:
        print("NO MEDIDO: registry irresoluble", file=sys.stderr)
        return RC_NOT_MEASURED
    try:
        sessions = _registry(registry)
    except MeasurementError as exc:
        print(f"NO MEDIDO: {exc}", file=sys.stderr)
        return RC_NOT_MEASURED
    codes = [_run_mode(name, sessions, cutoff, store, agents_json) for name in selected]
    result = (
        RC_VIOLATION
        if RC_VIOLATION in codes
        else RC_NOT_MEASURED
        if RC_NOT_MEASURED in codes
        else RC_OK
    )
    details = ", ".join(
        f"{name}={code}" for name, code in zip(selected, codes, strict=True)
    )
    print("check_cell_conformance:", details, f"rc={result}")
    return result


if __name__ == "__main__":
    sys.exit(main())
