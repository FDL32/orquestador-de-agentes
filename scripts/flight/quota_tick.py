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


def _roster_quota(flight_dir):
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
    return quota


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


def _measure(accounts):
    """Resume porcentajes y estados stale de las cuentas medidas.

    Before: ``accounts`` es el diccionario validado por ``_accounts``.
    During: lee porcentaje, stale y ventana, conserva cada cuenta como texto y calcula
        el peor porcentaje mediante ``_is_real``.
    After: devuelve ``(worst, parts, bad)`` con el maximo, fragmentos y marca de dato
        malo; un entero JSON fuera del rango convertible a ``float`` marca la cuenta
        como mala y no propaga ``OverflowError``.
    """
    worst, parts, bad = 0, [], False
    for name, v in accounts.items():
        pct, stale = v.get("block_pct"), v.get("stale")
        ok = _is_real(pct) and pct != -math.inf
        if not ok or stale:
            bad = True
        parts.append(
            f"{name} {v.get('block_window')} {pct}%{' STALE' if stale else ''}"
        )
        if ok:
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
    if not probe:
        return f"codex NO_MEDIDO sin {PROBE_ENV}"
    try:
        c = subprocess.run(  # noqa: S603 - interprete actual y sonda del usuario
            [sys.executable, probe, home],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return "codex " + (
            c.stdout.strip().replace("\n", " ").replace("|", "/")[:110] or "sin salida"
        )
    except Exception as exc:
        return f"codex NO_MEDIDO {type(exc).__name__}"


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


def _tick(a):
    """Ejecuta una medicion completa de cupo y escribe su linea de resultado.

    Before: ``a`` contiene los argumentos CLI; vuelo, roster y monitor deben ser resolubles.
    During: resuelve roster y umbrales, ejecuta el monitor, anade la sonda informativa y clasifica.
    After: devuelve el rc del estado; ``NoMedidoError`` sube al ``main`` y no se modifica ningun fichero.
    """
    env = os.environ
    quota = _roster_quota(_flight_dir(a.flight_dir or env.get(FLIGHT_DIR_ENV)))
    soft, hard, invalid = _thresholds(quota)
    accounts = _accounts(a.monitor or env.get(MONITOR_ENV))
    worst, parts, bad = _measure(accounts)
    home = a.codex_home or env.get(CODEX_HOME_ENV) or (Path.home() / ".codex")
    parts.append(_codex(a.probe or env.get(PROBE_ENV), Path(home).as_posix()))
    state = _state(worst, bad, soft, hard)
    mark = " umbrales-roster-invalidos" if invalid else ""
    print(f"QUOTA {state} (soft {soft}/hard {hard}){mark} | " + " | ".join(parts))
    return RC[state]


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
