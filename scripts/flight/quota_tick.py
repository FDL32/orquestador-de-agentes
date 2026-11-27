#!/usr/bin/env python3
"""Medidor de cupo del tick. Solo lectura. Fail-closed: lectura stale, nula o ilegible => NO_MEDIDO.

Before: un directorio del vuelo (``--flight-dir`` o ``FLIGHT_DIR``, absoluto y existente) con
    ``flight_roster.json``; el monitor de uso de cuentas (``--monitor`` o ``CC_USAGE_MONITOR_PS1``,
    un .ps1 que acepta ``-Json``) y, opcional, la sonda de codex (``--probe`` o ``CODEX_USAGE_PROBE``,
    con ``--codex-home`` o ``CODEX_HOME``). Las herramientas son del usuario y NO se versionan.
During: lee los umbrales del roster (``quota.soft_freeze_block_pct``, ``quota.hard_stop_block_pct``;
    por defecto 92 y 97), ejecuta el monitor con PowerShell por ruta absoluta de SystemRoot y toma
    el peor ``block_pct`` de las cuentas. Un umbral invalido cae al defecto con la marca
    ``umbrales-roster-invalidos``; en particular, un ``hard_stop_block_pct`` invalido cae a 97
    y puede resultar menos severo que el umbral pretendido por el roster. La sonda de codex es
    informativa. Un ``+inf`` del monitor se conserva como HARD rc 5 deliberadamente.
After: UNA linea ``QUOTA <ESTADO> (soft S/hard H) | <cuenta> <ventana> <pct>% | codex ...`` y rc 0 OK,
    3 AVISO (>= 90), 4 FREEZE (>= soft), 5 HARD (>= hard), 9 NO_MEDIDO. Cualquier fallo interno
    (roster o monitor ausentes o ilegibles, cuentas vacias, porcentaje NaN, booleano o cadena)
    es rc 9 con la causa; nunca un traceback con rc 1 ni un OK sin haber medido nada.
    Las cuentas con ``consume_to_exhaustion`` literal ``true`` se excluyen del worst global y
    reciben la marca textual ``AGOTAR``. Cuando el roster declara ``sessions``, el fichero fijo
    ``session_registry.json`` del mismo directorio aporta el censo de sesiones y la celda de
    asignacion de subagentes; cada identidad reutiliza la medida de cuenta que entrega el monitor.
    Una nota sin ``_CUENTA_<nombre>``, un registro extra o un lanzamiento sin proveedor presente
    en ``provider_map`` queda como ``NO_MEDIDO`` con causa.

Schema JSON v2 congelado: ``QUOTA_JSON_SCHEMA``; cada cuenta lleva ``cuenta``,
``en_censo``, ``estado_operativo``, ``calidad_medida``, ``block_pct``,
``ventana_peor`` y ``ventanas``; ``codex`` lleva exactamente
``primary_pct``, ``weekly_pct``, ``resets`` y ``medido``. ``rc_info`` copia el
rc y ``fallbacks`` declara los defaults. ``sesiones`` y ``subagentes`` anaden el detalle de
atribucion y ``dimensions`` declara su estado y causas. Un registro v1 de tick_trace omite los
campos de cola y por tanto ``cola_despachable`` se interpreta como no declarado.
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path


FLIGHT_DIR_ENV = "FLIGHT_DIR"
MONITOR_ENV = "CC_USAGE_MONITOR_PS1"
PROBE_ENV = "CODEX_USAGE_PROBE"
CODEX_HOME_ENV = "CODEX_HOME"
ROSTER_NAME = "flight_roster.json"
SESSION_REGISTRY_NAME = "session_registry.json"
SOFT_DEFAULT = 92
HARD_DEFAULT = 97
WARN_PCT = 90
RC = {"NO_MEDIDO": 9, "HARD": 5, "FREEZE": 4, "AVISO": 3, "OK": 0}
QUOTA_JSON_SCHEMA = 2
OPERATIVE_STATES = ("NORMAL", "VIGILANCIA", "PREPARACION", "CAMBIO")
MEASUREMENT_QUALITY = ("OK", "STALE", "NO_MEDIDO", "RESERVA")
ACCOUNT_RE = re.compile(r"_CUENTA_([A-Za-z0-9][A-Za-z0-9_.-]*)\s*$")


class NoMedidoError(Exception):
    """Señala una medicion no realizada y conserva su causa.

    Before: el llamador detecta una entrada ausente, invalida o no medible.
    During: la excepcion transporta el mensaje de causa sin ejecutar logica adicional.
    After: ``main`` puede convertirla en ``QUOTA NO_MEDIDO`` con rc 9.
    """


def _is_real(value):
    """Comprueba si un valor es real admisible para la medicion.

    Before: ``value`` puede proceder del roster o del monitor.
    During: acepta ``int`` o ``float`` salvo ``bool`` y rechaza ``NaN`` mediante
        ``math.isnan`` dentro de una guarda contra el desborde de conversion a ``float``.
    After: devuelve ``True`` para numeros no booleanos no-NaN, incluidos ``+inf`` y
        ``-inf``; devuelve ``False`` para el resto y para enteros cuyo ``float()``
        desborda, sin propagar ``OverflowError``.
    """
    if not (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return False
    try:
        return not math.isnan(value)
    except OverflowError:
        return False


def _is_unc(cand):
    """Comprueba si una ruta es UNC y no la forma extendida local.

    Before: ``cand`` es un ``Path`` construido desde el argumento del vuelo.
    During: inspecciona ``cand.drive`` y excluye el patron ``\\?\\C:``.
    After: devuelve ``True`` para rutas UNC de red y ``False`` para rutas locales.
    """
    return cand.drive.startswith("\\\\") and not re.fullmatch(
        r"\\\\\?\\[A-Za-z]:", cand.drive
    )


def _flight_dir(raw):
    """Valida y devuelve el directorio absoluto del vuelo.

    Before: ``raw`` es el argumento opcional de vuelo o su valor de entorno.
    During: rechaza ausencia, UNC, rutas relativas y rutas que no sean directorios existentes.
    After: devuelve el ``Path`` valido o lanza ``NoMedidoError`` con la causa concreta.
    """
    if not raw:
        raise NoMedidoError(
            f"roster: flight-dir sin resolver (pasa --flight-dir o define {FLIGHT_DIR_ENV})"
        )
    cand = Path(raw)
    if _is_unc(cand):
        raise NoMedidoError("roster: flight-dir en ruta de red (UNC) no admitida")
    if not cand.is_absolute():
        raise NoMedidoError("roster: flight-dir debe ser una ruta absoluta")
    if not cand.is_dir():
        raise NoMedidoError("roster: flight-dir no existe o no es un directorio")
    return cand


def _roster_config(flight_dir):
    """Bloque ``quota`` del roster (un dict, vacio si falta la clave).

    Before: ``flight_dir`` existe.
    During: lee ``flight_roster.json`` con utf-8-sig (tolera BOM) y parsea.
    After: dict; NoMedidoError si el fichero falta, no es JSON, no es un objeto o ``quota`` no lo es.
    """
    roster = _roster_document(flight_dir)
    quota = roster.get("quota", {})
    if not isinstance(quota, dict):
        raise NoMedidoError("roster: quota no es un objeto JSON")
    policy = quota.get("account_policy", roster.get("account_policy", {}))
    if not isinstance(policy, dict):
        policy = {}
    return quota, policy


def _roster_document(flight_dir):
    """Read the complete roster for the session/subagent census.

    Before: ``flight_dir`` is an existing flight directory.
    During: read the same UTF-8-sig roster used by ``_roster_config``.
    After: return the parsed roster object or raise ``NoMedidoError`` with its cause.
    """
    try:
        roster = json.loads((flight_dir / ROSTER_NAME).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError) as exc:
        raise NoMedidoError(f"roster: {type(exc).__name__} {str(exc)[:80]}") from exc
    if not isinstance(roster, dict):
        raise NoMedidoError("roster: no es un objeto JSON")
    return roster


def _session_registry(flight_dir):
    """Read the fixed-name session store and classify malformed input.

    Before: the roster declares sessions and ``flight_dir`` is already validated.
    During: load ``session_registry.json`` as a JSON object and distinguish absence from corruption.
    After: return ``(registry, None)`` or ``(None, cause)`` for fail-closed reporting.
    """
    try:
        registry = json.loads(
            (flight_dir / SESSION_REGISTRY_NAME).read_text(encoding="utf-8-sig")
        )
    except FileNotFoundError:
        return None, "session_registry_ausente"
    except (OSError, ValueError) as exc:
        return None, f"session_registry_ilegible:{type(exc).__name__}"
    except RecursionError:
        return None, "session_registry_ilegible:RecursionError"
    if not isinstance(registry, dict) or not isinstance(registry.get("sessions"), list):
        return None, "session_registry_ilegible:formato_sessions"
    return registry, None


def _roster_quota(flight_dir):
    """Return only the quota block for legacy callers."""
    return _roster_config(flight_dir)[0]


def _thresholds(quota):
    """Obtiene los umbrales soft y hard del bloque quota.

    Before: ``quota`` es un diccionario del roster y puede contener tipos arbitrarios.
    During: valida cada valor como real finito y positivo, sustituyendo invalidos por el
        defecto; los enteros JSON fuera del rango convertible a ``float`` son invalidos.
    After: devuelve ``(soft, hard, invalid)`` y marca si algun valor fue sustituido;
        nunca propaga el ``OverflowError`` de un entero JSON enorme.
    """
    out, invalid = [], False
    for key, default in (
        ("soft_freeze_block_pct", SOFT_DEFAULT),
        ("hard_stop_block_pct", HARD_DEFAULT),
    ):
        value = quota.get(key, default)
        if _is_real(value) and math.isfinite(value) and value > 0:
            out.append(value)
        else:
            out.append(default)
            invalid = True
    return out[0], out[1], invalid


def _powershell():
    """Construye la ruta absoluta del PowerShell del sistema.

    Before: ``SYSTEMROOT`` identifica la instalacion Windows del proceso.
    During: toma esa variable y anade la ruta fija sin buscar ejecutables mediante ``PATH``.
    After: devuelve un ``Path`` al ejecutable o lanza ``NoMedidoError`` si falta la variable.
    """
    root = os.environ.get("SYSTEMROOT")
    if not root:
        raise NoMedidoError("monitor: SystemRoot ausente")
    return Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def _accounts(monitor):
    """Ejecuta el monitor y valida su mapa de cuentas.

    Before: ``monitor`` identifica el script o es un valor vacio no resoluble.
    During: ejecuta PowerShell con ``-NoProfile -File monitor -Json``, parsea stdout y valida la forma.
    After: devuelve el mapa valido o lanza ``NoMedidoError`` con la causa del fallo.
    """
    if not monitor:
        raise NoMedidoError(
            f"monitor: sin resolver (pasa --monitor o define {MONITOR_ENV})"
        )
    try:
        r = subprocess.run(  # noqa: S603 - PowerShell por ruta absoluta del sistema, argumentos propios
            [str(_powershell()), "-NoProfile", "-File", monitor, "-Json"],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if r.returncode != 0:
            raise NoMedidoError(f"monitor: salio con rc {r.returncode}")
        accounts = json.loads(r.stdout)["accounts"]
    except NoMedidoError:
        raise
    except Exception as exc:
        raise NoMedidoError(f"monitor: {type(exc).__name__} {str(exc)[:80]}") from exc
    if not isinstance(accounts, dict) or not accounts:
        raise NoMedidoError("monitor: accounts vacio o no es un objeto")
    if not all(isinstance(v, dict) for v in accounts.values()):
        raise NoMedidoError("monitor: una cuenta no es un objeto")
    return accounts


def _measure(accounts, census):
    """Resume porcentajes and stale states for the measured accounts.

    Before: ``accounts`` is the validated monitor map and ``census`` is the roster census.
    During: retain every account in text while calculating severity only from the census
        when it is non-empty; an empty census preserves the legacy all-account behavior.
    After: return ``(worst, parts, bad)`` without allowing an extra account to raise rc.
    """
    worst, parts, bad = 0, [], False
    measured_names = set(census) if census else set(accounts)
    for name, v in accounts.items():
        pct, stale = v.get("block_pct"), v.get("stale")
        ok = _is_real(pct) and pct != -math.inf
        if not ok or stale:  # noqa: SIM102 - preserves the mutation anchor
            if name in measured_names:
                bad = True
        parts.append(
            f"{name} {v.get('block_window')} {pct}%{' STALE' if stale else ''}"
        )
        if name in measured_names and ok:
            worst = max(worst, pct)
    return worst, parts, bad


def _codex(probe, home):
    """Parte informativa de la sonda de codex; su fallo NUNCA cambia el rc.

    Before: ``probe`` es una ruta opcional y ``home`` el directorio de la sonda.
    During: ejecuta la sonda, aplana saltos de línea, sanea ``|`` como ``/`` y acota la salida
        para que la información no cree segmentos adicionales en la línea ``QUOTA``.
    After: devuelve un fragmento informativo estable; cualquier excepción produce ``NO_MEDIDO``
        sin alterar el rc de la medición.
    """
    account = Path(home).name.lstrip(".") or "codex"
    empty = {
        "primary_pct": None,
        "weekly_pct": None,
        "resets": {"primary": None, "weekly": None},
        "medido": False,
    }
    if not probe:
        return f"codex NO_MEDIDO sin {PROBE_ENV}", empty
    try:
        c = subprocess.run(  # noqa: S603 - interprete actual y sonda del usuario
            [sys.executable, probe, home],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        raw = c.stdout.strip().replace("\r", " ").replace("\n", " ").replace("|", "/")
        match = re.search(r"RATELIMITS:\s*(\{.*\})", raw)
        if match:
            payload = json.loads(match.group(1))
            data = (
                payload["result"]
                if isinstance(payload.get("result"), dict)
                else payload
            )
            limits = data["rateLimits"]
            primary = limits["primary"]["usedPercent"]
            weekly = limits["secondary"]["usedPercent"]
            item = {
                "primary_pct": primary,
                "weekly_pct": weekly,
                "resets": {
                    "primary": limits["primary"].get("resetsAt"),
                    "weekly": limits["secondary"].get("resetsAt"),
                },
                "medido": True,
            }
            return f"codex {account} primary {primary}% weekly {weekly}%", item
        return f"codex {raw or 'sin salida'}", empty
    except Exception as exc:
        return f"codex NO_MEDIDO {type(exc).__name__}", empty


def _state(worst, bad, soft, hard):
    """Clasifica la medicion por severidad y umbrales configurados.

    Before: ``worst`` es el maximo, ``bad`` indica dato no medible y los umbrales son positivos.
    During: aplica el orden NO_MEDIDO, HARD, FREEZE, AVISO y OK.
    After: devuelve exactamente uno de los estados presentes en ``RC``.
    """
    if bad:
        return "NO_MEDIDO"
    if worst >= hard:
        return "HARD"
    if worst >= soft:
        return "FREEZE"
    return "AVISO" if worst >= WARN_PCT else "OK"


def _census(policy):
    """Build the declared account census without treating an absent census as an error.

    Before: ``policy`` is the roster account_policy object.
    During: collect provider-map values and preferred/harbor identities.
    After: return an ordered unique list, or an empty list for legacy rosters.
    """
    values = []
    provider_map = policy.get("provider_map", {})
    if isinstance(provider_map, dict):
        values.extend(
            value for value in provider_map.values() if isinstance(value, str)
        )
    for key in ("preferred_account", "harbor_account"):
        value = policy.get(key)
        if isinstance(value, str):
            values.append(value)
    return list(dict.fromkeys(values))


def _session_active(entry):
    """Return whether a registry entry can represent a live session.

    Before: ``entry`` is a candidate from the real ``session_registry.sessions`` list.
    During: accept only the explicit active markers and ignore historical free-form statuses.
    After: return ``True`` only for a live ``ACTIVE``/``ACTIVA`` string status.
    """
    status = entry.get("status") if isinstance(entry, dict) else None
    if not isinstance(status, str) or not status.strip():
        return False
    folded = status.strip().upper()
    return (
        folded == "ACTIVE"
        or folded.startswith("ACTIVE ")
        or folded == "ACTIVA"
        or folded.startswith("ACTIVA ")
        or folded == "ACTIVO"
        or folded.startswith("ACTIVO ")
    )


def _session_account(entry):
    """Resolve the account marker used by the live session registry.

    Before: ``entry`` is a registry session with its free-form ``nota`` field.
    During: search only the declared ``_CUENTA_<nombre>`` suffix convention.
    After: return the account string or ``None`` when the relation is not attributable.
    """
    nota = entry.get("nota") if isinstance(entry, dict) else None
    if not isinstance(nota, str):
        return None
    match = ACCOUNT_RE.search(nota)
    return match.group(1) if match else None


def _dimension_quality(account, accounts, census):
    """Reuse an account monitor result for a session or subagent identity.

    Before: ``account`` is a candidate account and ``accounts`` is monitor output.
    During: require both roster declaration and a valid monitor entry.
    After: return ``(quality, block_pct, cause)`` without inventing a measurement.
    """
    if not isinstance(account, str):
        return "NO_MEDIDO", None, "cuenta_no_atribuida"
    if account not in census:
        return "NO_MEDIDO", None, "cuenta_no_declarada"
    measured = accounts.get(account)
    if not isinstance(measured, dict):
        return "NO_MEDIDO", None, "cuenta_no_medida"
    pct = measured.get("block_pct")
    if measured.get("stale"):
        return "STALE", pct, "cuenta_stale"
    if not _is_real(pct) or pct == -math.inf:
        return "NO_MEDIDO", None, "cuenta_dato_ilegible"
    return "OK", pct, None


def _dimension_entry(identity, session, puesto, account, accounts, census, cause=None):
    """Build one schema-v2 detail entry for a session or subagent.

    Before: identity metadata and the account monitor map are available.
    During: resolve quality through ``_dimension_quality`` unless a relation is already broken.
    After: return a compact entry with an explicit ``causa`` only for non-measurements.
    """
    if cause:
        quality, pct = "NO_MEDIDO", None
    else:
        quality, pct, cause = _dimension_quality(account, accounts, census)
    entry = {
        "sesion": session,
        "cuenta": account,
        "calidad_medida": quality,
        "block_pct": pct,
    }
    if identity is not None:
        entry["subagente"] = identity
    if puesto is not None:
        entry["puesto"] = puesto
    if cause:
        entry["causa"] = cause
    return entry


def _dimension_status(entries):
    """Summarize detail entries without allowing an empty or bad dimension to be green.

    Before: ``entries`` contains the complete declared dimension census.
    During: collect visible causes and accept only ``OK``/``RESERVA`` entries.
    After: return ``(estado, causas)`` where any missing-quality entry is ``NO_MEDIDO``.
    """
    causes = [entry["causa"] for entry in entries if entry.get("causa")]
    if not entries:
        return "NO_MEDIDO", ["censo_vacio"]
    if any(entry.get("calidad_medida") not in ("OK", "RESERVA") for entry in entries):
        return "NO_MEDIDO", list(dict.fromkeys(causes or ["dato_no_medido"]))
    return "OK", []


def _dimensions(accounts, flight_dir, policy):  # noqa: C901
    """Measure session and subagent identities using the account monitor result.

    Before: ``accounts`` came from the existing monitor; ``policy`` came from the roster.
    During: use roster session types, the fixed session registry, and provider-map attribution.
    After: return ``(sessions, subagents, dimensions, text_parts, bad)``; malformed relations are
        visible as ``NO_MEDIDO`` and never become an aggregate green measurement.
    """
    roster = _roster_document(flight_dir)
    declared = roster.get("sessions")
    if not declared:
        dimensions = {
            "sesiones": {"estado": "NO_APLICA", "causas": []},
            "subagentes": {"estado": "NO_APLICA", "causas": []},
        }
        return [], [], dimensions, [], False
    if not isinstance(declared, dict):
        reason = "sesiones_censo_ilegible"
        dimensions = {
            "sesiones": {"estado": "NO_MEDIDO", "causas": [reason]},
            "subagentes": {"estado": "NO_MEDIDO", "causas": [reason]},
        }
        return [], [], dimensions, ["sesiones NO_MEDIDO", "subagentes NO_MEDIDO"], True

    registry, registry_error = _session_registry(flight_dir)
    census = set(_census(policy))
    sessions, subagents = [], []
    if registry_error:
        sessions.extend(
            _dimension_entry(
                None,
                slot,
                None,
                None,
                accounts,
                census,
                registry_error,
            )
            for slot in declared
        )
        session_status = ("NO_MEDIDO", [registry_error])
        subagent_status = ("NO_MEDIDO", [registry_error])
        dimensions = {
            "sesiones": {"estado": session_status[0], "causas": session_status[1]},
            "subagentes": {"estado": subagent_status[0], "causas": subagent_status[1]},
        }
        return (
            sessions,
            subagents,
            dimensions,
            ["sesiones NO_MEDIDO", "subagentes NO_MEDIDO"],
            True,
        )

    declared_types = {
        value.get("type")
        for value in declared.values()
        if isinstance(value, dict) and isinstance(value.get("type"), str)
    }
    if not declared_types:
        reason = "sesiones_censo_sin_tipo"
        dimensions = {
            "sesiones": {"estado": "NO_MEDIDO", "causas": [reason]},
            "subagentes": {"estado": "NO_MEDIDO", "causas": [reason]},
        }
        return [], [], dimensions, ["sesiones NO_MEDIDO", "subagentes NO_MEDIDO"], True

    entries = [entry for entry in registry["sessions"] if isinstance(entry, dict)]
    active = [entry for entry in entries if _session_active(entry)]
    declared_entries = [
        entry
        for entry in active
        if entry.get("role") in declared_types or entry.get("slot") in declared
    ]
    present_types = {
        entry.get("role")
        for entry in declared_entries
        if isinstance(entry.get("role"), str)
    }
    sessions.extend(
        _dimension_entry(
            None,
            missing_type,
            None,
            None,
            accounts,
            census,
            "sesion_no_medida",
        )
        for missing_type in sorted(declared_types - present_types)
    )
    for entry in declared_entries:
        code = entry.get("code")
        session_id = code if isinstance(code, str) and code else entry.get("slot")
        if not isinstance(session_id, str) or not session_id:
            session_id = entry.get("role", "sesion_desconocida")
        account = _session_account(entry)
        session_entry = _dimension_entry(
            None,
            session_id,
            None,
            account,
            accounts,
            census,
            "sesion_sin_cuenta" if account is None else None,
        )
        sessions.append(session_entry)

        cell = entry.get("celda_asignacion")
        resolution = cell.get("resolucion") if isinstance(cell, dict) else None
        puestos = resolution.get("puestos") if isinstance(resolution, dict) else None
        if not isinstance(puestos, dict) or not puestos:
            subagents.append(
                _dimension_entry(
                    f"{session_id}:NO_MEDIDO",
                    session_id,
                    None,
                    account,
                    accounts,
                    census,
                    "subagente_relacion_ilegible",
                )
            )
            continue
        for puesto, assignment in puestos.items():
            launch = (
                assignment.get("lanzamiento") if isinstance(assignment, dict) else None
            )
            provider_key = None
            if isinstance(launch, dict):
                if isinstance(launch.get("instanceId"), str):
                    provider_key = launch["instanceId"]
                elif isinstance(launch.get("backend_key"), str):
                    provider_key = launch["backend_key"]
            subagent_account = (
                policy.get("provider_map", {}).get(provider_key)
                if isinstance(policy.get("provider_map"), dict) and provider_key
                else None
            )
            cause = None
            if (
                not isinstance(puesto, str)
                or not isinstance(launch, dict)
                or not provider_key
            ):
                cause = "subagente_relacion_ilegible"
            elif not isinstance(subagent_account, str):
                cause = "subagente_cuenta_no_resoluble"
            elif session_entry.get("calidad_medida") not in ("OK", "RESERVA"):
                cause = "sesion_no_medida"
            subagents.append(
                _dimension_entry(
                    f"{session_id}:{puesto}",
                    session_id,
                    puesto,
                    subagent_account,
                    accounts,
                    census,
                    cause,
                )
            )

    declared_slots = set(declared)
    for entry in active:
        if entry in declared_entries:
            continue
        role = entry.get("role")
        slot = entry.get("slot")
        if role not in declared_types and slot not in declared_slots:
            code = entry.get("code")
            session_id = code if isinstance(code, str) and code else slot
            if not isinstance(session_id, str) or not session_id:
                session_id = role if isinstance(role, str) else "sesion_desconocida"
            sessions.append(
                _dimension_entry(
                    None,
                    session_id,
                    None,
                    _session_account(entry),
                    accounts,
                    census,
                    "sesion_no_declarada",
                )
            )
            subagents.append(
                _dimension_entry(
                    f"{session_id}:NO_MEDIDO",
                    session_id,
                    None,
                    None,
                    accounts,
                    census,
                    "sesion_no_declarada",
                )
            )

    session_state, session_causes = _dimension_status(sessions)
    subagent_state, subagent_causes = _dimension_status(subagents)
    dimensions = {
        "sesiones": {"estado": session_state, "causas": session_causes},
        "subagentes": {"estado": subagent_state, "causas": subagent_causes},
    }
    bad = session_state != "OK" or subagent_state != "OK"
    text_parts = [
        f"sesiones {len(sessions)} {session_state}",
        f"subagentes {len(subagents)} {subagent_state}",
    ]
    return sessions, subagents, dimensions, text_parts, bad


def _account_cuts(name, quota, policy):
    """Resolve per-account soft and hard cuts and report visible fallback reasons.

    Before: quota and policy are JSON dictionaries.
    During: prefer account_policy[name], then quota, then 92/97.
    After: return ``(soft, hard, reasons)`` with no silent fallback.
    """
    account = policy.get(name, {})
    if not isinstance(account, dict):
        account = {}
    reasons = []
    values = []
    for key, default in (
        ("soft_freeze_block_pct", SOFT_DEFAULT),
        ("hard_stop_block_pct", HARD_DEFAULT),
    ):
        if key in account:
            values.append(account[key])
            continue
        if key in quota:
            values.append(quota[key])
            reasons.append(f"{name}:{key}=quota")
            continue
        values.append(default)
        reasons.append(f"{name}:{key}=default")
    soft, hard, invalid = _thresholds(
        dict(zip(("soft_freeze_block_pct", "hard_stop_block_pct"), values, strict=True))
    )
    if invalid:
        reasons.append(f"{name}:umbrales-invalidos")
    return soft, hard, reasons


def _operative_state(value, window, quality, soft, hard):
    """Classify an account's measured operational window.

    Before: value/window/quality are normalized monitor data.
    During: apply account cuts for weekly data and the fixed 5h/session boundaries.
    After: return a closed operational enum or null for non-measurements.
    """
    if quality not in ("OK", "RESERVA") or not _is_real(value):
        return None
    if str(window).lower() in {"5h", "session", "5_hours"}:
        return "CAMBIO" if value >= 95 else "VIGILANCIA" if value >= 85 else "NORMAL"
    return "CAMBIO" if value >= hard else "PREPARACION" if value >= 95 else "NORMAL"


def _account_json(name, measured, census, quota, policy):
    """Create one frozen schema-v2 account entry from monitor data."""
    windows = []
    if measured is None:
        quality = "NO_MEDIDO"
        block_pct = None
        worst_window = None
        state = None
    else:
        pct = measured.get("block_pct")
        stale = bool(measured.get("stale"))
        quality = (
            "STALE"
            if stale
            else "OK"
            if _is_real(pct) and pct != -math.inf
            else "NO_MEDIDO"
        )
        block_pct = pct if quality != "NO_MEDIDO" else None
        window = measured.get("block_window")
        windows.append({"ventana": window, "block_pct": pct, "calidad_medida": quality})
        worst_window = window
        soft, hard, _ = _account_cuts(name, quota, policy)
        state = _operative_state(pct, window, quality, soft, hard)
    return {
        "cuenta": name,
        "en_censo": name in census,
        "estado_operativo": state,
        "calidad_medida": quality,
        "block_pct": block_pct,
        "ventana_peor": worst_window,
        "ventanas": windows,
    }


def _json_payload(
    accounts,
    census,
    quota,
    policy,
    codex_item,
    rc,
    sessions=None,
    subagents=None,
    dimensions=None,
):
    """Build the single stdout JSON object for an opt-in quota tick."""
    entries = []
    fallbacks = []
    for name in [*census, *[key for key in accounts if key not in census]]:
        entry = _account_json(name, accounts.get(name), census, quota, policy)
        entries.append(entry)
        if name in census:
            _, _, reasons = _account_cuts(name, quota, policy)
            fallbacks.extend(reasons)
    return {
        "QUOTA_JSON_SCHEMA": QUOTA_JSON_SCHEMA,
        "accounts": entries,
        "sesiones": sessions or [],
        "subagentes": subagents or [],
        "dimensions": dimensions
        or {
            "sesiones": {"estado": "NO_APLICA", "causas": []},
            "subagentes": {"estado": "NO_APLICA", "causas": []},
        },
        "codex": [codex_item],
        "rc_info": rc,
        "fallbacks": list(dict.fromkeys(fallbacks)),
    }


def _tick(a):
    """Ejecuta una medicion completa de cupo y escribe su linea de resultado.

    Before: ``a`` contiene los argumentos CLI; vuelo, roster y monitor deben ser resolubles.
    During: resuelve roster y umbrales, excluye por cuenta las politicas de agotamiento del worst,
        anade ``AGOTAR`` solo al segmento textual de cada cuenta y clasifica.
    After: devuelve el rc del estado; ``NoMedidoError`` sube al ``main`` y no se modifica ningun fichero.
    """
    env = os.environ
    flight_dir = _flight_dir(a.flight_dir or env.get(FLIGHT_DIR_ENV))
    quota, policy = _roster_config(flight_dir)
    soft, hard, invalid = _thresholds(quota)
    accounts = _accounts(a.monitor or env.get(MONITOR_ENV))
    census = _census(policy)
    worst, parts, bad = _measure(accounts, census)
    sessions, subagents, dimensions, dimension_parts, dimensions_bad = _dimensions(
        accounts,
        flight_dir,
        policy,
    )
    parts.extend(dimension_parts)
    bad = bad or dimensions_bad
    agotar = {
        nombre
        for nombre, valor in policy.items()
        if isinstance(valor, dict) and valor.get("consume_to_exhaustion") is True
    }
    if agotar:
        worst = _measure(
            {key: value for key, value in accounts.items() if key not in agotar}, census
        )[0]
        parts = [
            f"{part} AGOTAR" if part.split(maxsplit=1)[0] in agotar else part
            for part in parts
        ]
    home = a.codex_home or env.get(CODEX_HOME_ENV) or (Path.home() / ".codex")
    codex_text, codex_item = _codex(
        a.probe or env.get(PROBE_ENV), Path(home).as_posix()
    )
    parts.append(codex_text)
    state = _state(worst, bad, soft, hard)
    mark = " umbrales-roster-invalidos" if invalid else ""
    missing = [name for name in census if name not in accounts]
    process_rc = 9 if missing else RC[state]
    text = f"QUOTA {state} (soft {soft}/hard {hard}){mark} | " + " | ".join(parts)
    if a.json:
        print(
            json.dumps(
                _json_payload(
                    accounts,
                    census,
                    quota,
                    policy,
                    codex_item,
                    process_rc,
                    sessions,
                    subagents,
                    dimensions,
                ),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    else:
        print(text)
    return process_rc


def main(argv=None):
    """CLI del medidor de cupo.

    Before: argumentos de linea de comandos (o ``argv``); ver el docstring del modulo.
    During: un tick de medicion (``_tick``).
    After: rc 0/3/4/5/9; cualquier fallo interno es ``QUOTA NO_MEDIDO <causa>`` con rc 9. Un
        error de uso de argparse sale con rc 2 (es del llamador, no de la medicion).
    """
    ap = argparse.ArgumentParser(description="Medidor de cupo del tick (solo lectura)")
    ap.add_argument(
        "--flight-dir", help=f"directorio del vuelo; por defecto ${FLIGHT_DIR_ENV}"
    )
    ap.add_argument(
        "--monitor", help=f"monitor de uso (.ps1); por defecto ${MONITOR_ENV}"
    )
    ap.add_argument("--probe", help=f"sonda de codex (.py); por defecto ${PROBE_ENV}")
    ap.add_argument(
        "--codex-home",
        help=f"directorio de codex; por defecto ${CODEX_HOME_ENV} o ~/.codex",
    )
    ap.add_argument("--json", action="store_true", help="emit frozen schema-v2 JSON")
    a = ap.parse_args(argv)
    try:
        return _tick(a)
    except NoMedidoError as exc:
        print(f"QUOTA NO_MEDIDO {exc}")
    except Exception as exc:
        print(f"QUOTA NO_MEDIDO interno: {type(exc).__name__} {str(exc)[:80]}")
    return RC["NO_MEDIDO"]


if __name__ == "__main__":
    sys.exit(main())
