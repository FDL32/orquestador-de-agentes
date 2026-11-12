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

Schema JSON v2 congelado: ``QUOTA_JSON_SCHEMA``; cada cuenta lleva ``cuenta``,
``en_censo``, ``estado_operativo``, ``calidad_medida``, ``block_pct``,
``ventana_peor`` y ``ventanas``; ``codex`` lleva exactamente
``primary_pct``, ``weekly_pct``, ``resets`` y ``medido``. ``rc_info`` copia el
rc y ``fallbacks`` declara los defaults. Un registro v1 de tick_trace omite los
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
SOFT_DEFAULT = 92
HARD_DEFAULT = 97
WARN_PCT = 90
RC = {"NO_MEDIDO": 9, "HARD": 5, "FREEZE": 4, "AVISO": 3, "OK": 0}
QUOTA_JSON_SCHEMA = 2
OPERATIVE_STATES = ("NORMAL", "VIGILANCIA", "PREPARACION", "CAMBIO")
MEASUREMENT_QUALITY = ("OK", "STALE", "NO_MEDIDO", "RESERVA")


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
    try:
        roster = json.loads((flight_dir / ROSTER_NAME).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError) as exc:
        raise NoMedidoError(f"roster: {type(exc).__name__} {str(exc)[:80]}") from exc
    if not isinstance(roster, dict):
        raise NoMedidoError("roster: no es un objeto JSON")
    quota = roster.get("quota", {})
    if not isinstance(quota, dict):
        raise NoMedidoError("roster: quota no es un objeto JSON")
    policy = quota.get("account_policy", roster.get("account_policy", {}))
    if not isinstance(policy, dict):
        policy = {}
    return quota, policy


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


def _json_payload(accounts, census, quota, policy, codex_item, rc):
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
        "codex": [codex_item],
        "rc_info": rc,
        "fallbacks": list(dict.fromkeys(fallbacks)),
    }


def _tick(a):
    """Ejecuta una medicion completa de cupo y escribe su linea de resultado.

    Before: ``a`` contiene los argumentos CLI; vuelo, roster y monitor deben ser resolubles.
    During: resuelve roster y umbrales, ejecuta el monitor, anade la sonda informativa y clasifica.
    After: devuelve el rc del estado; ``NoMedidoError`` sube al ``main`` y no se modifica ningun fichero.
    """
    env = os.environ
    quota, policy = _roster_config(_flight_dir(a.flight_dir or env.get(FLIGHT_DIR_ENV)))
    soft, hard, invalid = _thresholds(quota)
    accounts = _accounts(a.monitor or env.get(MONITOR_ENV))
    census = _census(policy)
    worst, parts, bad = _measure(accounts, census)
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
                _json_payload(accounts, census, quota, policy, codex_item, process_rc),
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
