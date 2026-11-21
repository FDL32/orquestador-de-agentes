#!/usr/bin/env python3
"""Pure guard for the mother/daughter account cycle.

Before: the caller has a validated account reading and an optional persisted state.
During: apply external events, record the reading, project quota burn, and choose one action.
After: return a new state and one action; the CLI only persists after ``--guardar``.
"""

import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path


PREFERIDA = "alvarovans"
REFUGIO = "brabander"
ESTADO_INICIAL = {
    "version": 1,
    "madre_en_refugio": False,
    "hija_en_refugio": False,
    "agotada": None,
    "despertar_en": None,
    "reintentos": 0,
    "secuencia_retorno": 0,
    "lecturas": [],
    "roster_sha12": None,
    "cycle_id": None,
    "tasa_razon": None,
    "motivo": None,
}
ACCIONES_VALIDAS = {
    "NONE",
    "MOVE_MADRE_REFUGE",
    "MOVE_HIJA_REFUGE_Y_PROGRAMAR_DESPERTAR",
    "ESPERAR",
    "REINTENTAR_DESPERTAR",
    "AVISAR_RESET_NO_OBSERVADO",
    "MOVE_HIJA_PREFERIDA",
    "MOVE_MADRE_PREFERIDA",
    "MADRE_AGOTADA_EN_REFUGIO",
    "AMBAS_AGOTADAS",
    "DESPERTAR_NO_EJECUTADO",
    "ABORTAR_CICLO_Y_AVISAR",
}


def _action(tipo="NONE", ejecutor=None, wake_at=None):
    """Build the closed action shape.

    Before: a decision type and optional executor/wake time are available.
    During: normalize the three action fields.
    After: return an action dictionary accepted by the CLI contract.
    """
    return {"tipo": tipo, "ejecutor": ejecutor, "wake_at": wake_at}


def _numeric(value):
    """Return whether a value is a finite non-boolean number.

    Before: value may come from JSON or a caller.
    During: reject booleans, strings, null, NaN, and infinities.
    After: return a strict boolean without raising.
    """
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _reset_for(state, readings):
    """Resolve the reset belonging to the exhausted quota.

    Before: state has an exhaustion label and readings contain reset fields.
    During: choose weekly reset only for weekly exhaustion.
    After: return an epoch or None when it was not observed.
    """
    return (
        readings.get("weekly_resets")
        if state.get("agotada") == "semanal"
        else readings.get("resets")
    )


def _tasa(historial, lecturas):
    """Calculate the latest valid adjacent quota rate and its reason.

    Before: history is ordered reading data and ``lecturas`` is the current reading.
    During: accept only increasing finite pairs at least sixty seconds apart and on the
        same observed reset when both resets are present; otherwise apply the one-point floor.
    After: return ``(rate, reason)`` with a persisted explanation for every valid reading.
    """
    candidates = [
        *historial,
        {
            "ts": lecturas["checked_at"],
            "pct": lecturas["pct"],
            "reset": lecturas.get("resets"),
        },
    ]
    latest = None
    for index in range(len(candidates) - 1):
        older, newer = candidates[index : index + 2]
        if not (
            older.get("ts") is not None
            and newer.get("ts") is not None
            and newer["ts"] > older["ts"]
            and newer["ts"] - older["ts"] >= 60
            and _numeric(older.get("pct"))
            and _numeric(newer.get("pct"))
            and not (
                older.get("reset") is not None
                and newer.get("reset") is not None
                and older.get("reset") != newer.get("reset")
            )
        ):
            continue
        latest = (older, newer)
    if latest is None:
        return 1.0, "suelo-1pt-min"
    older, newer = latest
    rate = (newer["pct"] - older["pct"]) / ((newer["ts"] - older["ts"]) / 60)
    if rate <= 0:
        return 0, "pareja-valida-tasa-no-positiva"
    return rate, "pareja-valida"


def _remember(state, readings):
    """Append and bound the current reading history.

    Before: state contains zero or more historical reading pairs.
    During: deduplicate by timestamp and retain the latest five entries.
    After: return state with the current reading represented at most once.
    """
    items = [
        item
        for item in state.get("lecturas", [])
        if item.get("ts") != readings["checked_at"]
    ]
    items.append(
        {
            "ts": readings["checked_at"],
            "pct": readings["pct"],
            "reset": readings.get("resets"),
        }
    )
    state["lecturas"] = items[-5:]
    return state


def _cuenta_agotada(pct, weekly):
    """Identify exhaustion from a quota reading without intermediate thresholds.

    Before: preferred or refuge percentages may be numeric or absent.
    During: compare each observed window to the terminal 100 percent boundary.
    After: return true only when an observed window is at least 100 percent.
    """
    return (pct is not None and pct >= 100) or (weekly is not None and weekly >= 100)


def decide(lecturas, estado, ahora, eventos):  # noqa: C901
    """Choose one account-cycle action from readings, state, time, and events.

    Before: ``lecturas`` is a validated reading map and ``estado`` is a state snapshot.
    During: apply events first, retain the reading, then evaluate refuge, exhaustion, wake,
        retries, and return sequencing in contract order.
    After: return an independent ``(estado_nuevo, accion)`` pair; the input state is untouched.
    """
    nuevo = copy.deepcopy(estado)
    for evento in eventos:
        if evento == "limite":
            nuevo["agotada"] = "5h"
        elif evento == "limite_semanal":
            nuevo["agotada"] = "semanal"
        elif evento == "madre_en_refugio":
            nuevo["madre_en_refugio"] = True
        elif evento == "hija_en_refugio":
            nuevo["hija_en_refugio"] = True
            if nuevo.get("agotada") and nuevo.get("despertar_en") is None:
                reset = _reset_for(nuevo, lecturas)
                if reset is not None:
                    nuevo["despertar_en"] = reset + 60
        elif evento == "madre_en_preferida":
            nuevo.update(
                {
                    "madre_en_refugio": False,
                    "hija_en_refugio": False,
                    "agotada": None,
                    "despertar_en": None,
                    "reintentos": 0,
                    "secuencia_retorno": 0,
                    "motivo": None,
                }
            )
        else:
            raise ValueError(f"evento desconocido: {evento}")

    if not (_numeric(lecturas.get("pct")) and _numeric(lecturas.get("weekly_pct"))):
        return nuevo, _action()
    if nuevo.get("roster_sha12") is not None and nuevo.get(
        "roster_sha12"
    ) != lecturas.get("roster_sha12"):
        return nuevo, _action("ABORTAR_CICLO_Y_AVISAR", "madre")
    _remember(nuevo, lecturas)
    tasa, tasa_razon = _tasa(nuevo["lecturas"][:-1], lecturas)
    nuevo["tasa_razon"] = tasa_razon
    rem5 = 100 - lecturas["pct"]
    weekly_rem = 100 - lecturas["weekly_pct"]
    latch = weekly_rem < 5 and (
        lecturas.get("weekly_resets") is None or ahora < lecturas["weekly_resets"]
    )
    reset_ausente = weekly_rem < 5 and lecturas.get("weekly_resets") is None
    projection = rem5 - tasa * 15
    preferida_agotada = bool(nuevo.get("agotada")) or _cuenta_agotada(
        lecturas["pct"], lecturas["weekly_pct"]
    )
    refugio_agotado = _cuenta_agotada(
        lecturas.get("refugio_pct"), lecturas.get("refugio_weekly_pct")
    )
    if preferida_agotada and refugio_agotado:
        return nuevo, _action("AMBAS_AGOTADAS", "madre")
    if nuevo.get("madre_en_refugio") and refugio_agotado:
        return nuevo, _action("MADRE_AGOTADA_EN_REFUGIO", "madre")
    if not nuevo["madre_en_refugio"] and (
        rem5 < 10 or projection < 10 or weekly_rem < 5
    ):
        return nuevo, _action("MOVE_MADRE_REFUGE", "hija")
    if not nuevo["hija_en_refugio"] and (
        nuevo.get("agotada") or lecturas["pct"] >= 100 or lecturas["weekly_pct"] >= 100
    ):
        cuota = (
            "semanal"
            if lecturas["weekly_pct"] >= 100 or nuevo.get("agotada") == "semanal"
            else "5h"
        )
        nuevo["agotada"] = cuota
        reset = (
            lecturas.get("weekly_resets")
            if cuota == "semanal"
            else lecturas.get("resets")
        )
        if reset is None:
            return nuevo, _action("AVISAR_RESET_NO_OBSERVADO", "madre")
        nuevo["despertar_en"] = reset + 60
        return nuevo, _action(
            "MOVE_HIJA_REFUGE_Y_PROGRAMAR_DESPERTAR", "madre", reset + 60
        )
    if nuevo.get("despertar_en") is not None:
        wake = nuevo["despertar_en"]
        if ahora < wake:
            return nuevo, _action("ESPERAR")
        quota = (
            lecturas["weekly_pct"]
            if nuevo.get("agotada") == "semanal"
            else lecturas["pct"]
        )
        if nuevo.get("secuencia_retorno") == 0:
            if quota >= 85:
                if nuevo.get("hija_en_refugio") and ahora > wake + 600:
                    return nuevo, _action("DESPERTAR_NO_EJECUTADO", "madre")
                if nuevo.get("reintentos", 0) < 5:
                    nuevo["reintentos"] += 1
                    nuevo["despertar_en"] = wake + 120
                    return nuevo, _action("REINTENTAR_DESPERTAR", "madre", wake + 120)
                return nuevo, _action("AVISAR_RESET_NO_OBSERVADO", "madre")
            if latch:
                if reset_ausente and nuevo.get("agotada") == "semanal":
                    return nuevo, _action("AVISAR_RESET_NO_OBSERVADO", "madre")
                if latch and nuevo.get("agotada") == "semanal":
                    return nuevo, _action("ESPERAR")
            if nuevo.get("hija_en_refugio") and ahora > wake + 600 and latch:
                return nuevo, _action(
                    "DESPERTAR_NO_EJECUTADO" if reset_ausente else "ESPERAR",
                    "madre" if reset_ausente else None,
                )
            if nuevo.get("hija_en_refugio") and ahora > wake + 600:
                nuevo["motivo"] = "retorno-tardio"
            nuevo["secuencia_retorno"] = 1
            return nuevo, _action("MOVE_HIJA_PREFERIDA", "madre")
        if nuevo["secuencia_retorno"] == 1:
            if latch:
                if reset_ausente:
                    return nuevo, _action("AVISAR_RESET_NO_OBSERVADO", "madre")
                return nuevo, _action("ESPERAR")
            nuevo["secuencia_retorno"] = 2
            return nuevo, _action("MOVE_MADRE_PREFERIDA", "hija")
        return nuevo, _action("ESPERAR")
    if (
        nuevo.get("madre_en_refugio")
        and not nuevo.get("hija_en_refugio")
        and nuevo.get("agotada") is None
        and nuevo.get("despertar_en") is None
        and not latch
        and lecturas["pct"] < 85
        and not (rem5 < 10 or projection < 10 or weekly_rem < 5)
    ):
        return nuevo, _action("MOVE_MADRE_PREFERIDA", "hija")
    return nuevo, _action()


def _parse_iso(value):
    """Parse an ISO timestamp with seven fractional digits or Z.

    Before: value is a string from the usage cache.
    During: normalize Z and truncate fractional seconds to Python 3.10 precision.
    After: return an aware epoch or raise ValueError.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp no es texto")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    if "." in text:
        head, tail = text.split(".", 1)
        offset = ""
        for marker in ("+", "-"):
            position = tail.find(marker)
            if position > 0:
                tail, offset = tail[:position], tail[position:]
                break
        text = f"{head}.{tail[:6]}{offset}"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp sin zona horaria")
    return parsed.timestamp()


def _read_cache(path, estado=None, ahora=None):  # noqa: C901
    """Read and validate the account cache, with a bounded phase-C exception.

    Before: path identifies a JSON usage cache and estado may identify complete phase C.
    During: validate preferred data normally, or in complete phase C (both refuge flags,
        weekly exhaustion, and a future numeric state wake) tolerate preferred resets that
        are non-numeric or out of range plus a preferred checked_at that is stale or at
        most 1200 seconds in the future; brabander freshness and data stay mandatory there.
    After: return validated readings or raise ValueError with a fail-closed cause.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        entry = data[PREFERIDA]
        checked = entry.get("checked_at")
        checked_at = checked if _numeric(checked) else _parse_iso(checked)
        ahora = time.time() if ahora is None else ahora
        phase_c_tolerance = (
            isinstance(estado, dict)
            and estado.get("madre_en_refugio") is True
            and estado.get("hija_en_refugio") is True
            and estado.get("agotada") == "semanal"
            and _numeric(estado.get("despertar_en"))
            and ahora < estado["despertar_en"]
        )
        readings = {
            key: entry.get(key)
            for key in ("pct", "weekly_pct", "resets", "weekly_resets")
        }
        readings["checked_at"] = checked_at
        for key in ("pct", "weekly_pct"):
            if not _numeric(readings[key]):
                raise ValueError(f"{key} no numerico")
            if readings[key] < 0:
                raise ValueError(f"{key} negativo")
        for key in ("resets", "weekly_resets"):
            if isinstance(readings[key], str):
                readings[key] = _parse_iso(readings[key])
            if not _numeric(readings[key]):
                if not phase_c_tolerance:
                    raise ValueError(f"{key} no numerico")
                continue
            if not phase_c_tolerance and not (
                checked_at - 86400 <= readings[key] <= checked_at + 8 * 86400
            ):
                raise ValueError(f"{key} fuera de rango")
        refuge = data.get(REFUGIO)
        if phase_c_tolerance:
            if not isinstance(refuge, dict):
                raise ValueError("cuenta refugio ausente")
            refuge_checked = refuge.get("checked_at")
            refuge_checked_at = (
                refuge_checked
                if _numeric(refuge_checked)
                else _parse_iso(refuge_checked)
            )
            for key in ("pct", "weekly_pct"):
                if not _numeric(refuge.get(key)):
                    raise ValueError(f"refugio_{key} no numerico")
                if refuge[key] < 0:
                    raise ValueError(f"refugio_{key} negativo")
            for key in ("resets", "weekly_resets"):
                refuge_reset = refuge.get(key)
                if isinstance(refuge_reset, str):
                    refuge_reset = _parse_iso(refuge_reset)
                if not _numeric(refuge_reset):
                    raise ValueError(f"refugio_{key} no numerico")
                if (
                    not refuge_checked_at - 86400
                    <= refuge_reset
                    <= refuge_checked_at + 8 * 86400
                ):
                    raise ValueError(f"refugio_{key} fuera de rango")
            if abs(ahora - refuge_checked_at) > 1200:
                raise ValueError("cache refugio vieja o futura")
        if isinstance(refuge, dict):
            refuge_pct = refuge.get("pct")
            refuge_weekly = refuge.get("weekly_pct")
            readings["refugio_pct"] = refuge_pct if _numeric(refuge_pct) else None
            readings["refugio_weekly_pct"] = (
                refuge_weekly if _numeric(refuge_weekly) else None
            )
            if readings["refugio_pct"] is not None and readings["refugio_pct"] < 0:
                raise ValueError("refugio_pct negativo")
            if (
                readings["refugio_weekly_pct"] is not None
                and readings["refugio_weekly_pct"] < 0
            ):
                raise ValueError("refugio_weekly_pct negativo")
        else:
            readings["refugio_pct"] = None
            readings["refugio_weekly_pct"] = None
        if (checked_at - ahora > 1200) or (
            not phase_c_tolerance and abs(ahora - checked_at) > 1200
        ):
            raise ValueError("cache vieja o futura")
        return readings
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cache no medible: {type(exc).__name__} {exc}") from exc


def _roster_sha12(path):
    """Hash a resolved roster using the first twelve hexadecimal characters.

    Before: path identifies an optional roster file supplied by the caller.
    During: read its bytes and calculate a deterministic SHA-256 prefix.
    After: return the roster identity or raise a fail-closed ValueError.
    """
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return hashlib.sha256(raw).hexdigest()[:12]
    except OSError as exc:
        raise ValueError(f"roster ilegible: {type(exc).__name__} {exc}") from exc


def _read_state(path):
    """Read an existing state or return the initial state.

    Before: path may be absent or contain a JSON state.
    During: parse the object and validate its required version key.
    After: return a state snapshot, or the initial state when absent.
    """
    if path is None or not path.exists():
        return copy.deepcopy(ESTADO_INICIAL)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("estado sin version")
        defaults = copy.deepcopy(ESTADO_INICIAL)
        defaults.update(value)
        value = defaults
        return value
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"estado ilegible: {type(exc).__name__} {exc}") from exc


def _save_state(path, state):
    """Atomically replace a state file in its destination directory.

    Before: path is a resolvable state destination and state is JSON serializable.
    During: create a same-directory temporary file and replace the destination.
    After: the destination contains the new state and the temporary file is removed on error.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(
                state, stream, ensure_ascii=True, allow_nan=False, separators=(",", ":")
            )
            stream.write("\n")
        os.replace(temp, path)
    except (OSError, TypeError, ValueError):
        with contextlib.suppress(OSError):
            temp.unlink()
        raise


def main(argv=None):
    """Run the account-cycle CLI and emit exactly one JSON line.

    Before: CLI paths/events identify the cache, state, and external observations.
    During: validate cache freshness, decide, and optionally atomically save the new state.
    After: return rc 0, 10, or 9 with one JSON line; rc 2 is argparse usage on stderr without JSON.
    """
    parser = argparse.ArgumentParser(
        description="Guard del ciclo de cuentas madre/hija"
    )
    parser.add_argument("--cache", default=os.environ.get("CC_USAGE_CACHE"))
    parser.add_argument("--estado", default=os.environ.get("ACCOUNT_CYCLE_STATE"))
    parser.add_argument(
        "--roster-path",
        dest="roster_path",
        default=os.environ.get("FLIGHT_ROSTER_PATH") or os.environ.get("FLIGHT_ROSTER"),
    )
    parser.add_argument("--evento", action="append", default=[])
    parser.add_argument("--guardar", action="store_true")
    args = parser.parse_args(argv)
    unknown = [
        event
        for event in args.evento
        if event
        not in {
            "limite",
            "limite_semanal",
            "madre_en_refugio",
            "hija_en_refugio",
            "madre_en_preferida",
        }
    ]
    if unknown:
        parser.error(f"evento desconocido: {unknown[0]}")
    state_path = Path(args.estado) if args.estado else None
    try:
        ahora = time.time()
        current = _read_state(state_path)
        readings = (
            _read_cache(Path(args.cache), current, ahora)
            if args.cache
            else (_ for _ in ()).throw(ValueError("cache no medible: ruta ausente"))
        )
        readings["roster_sha12"] = (
            _roster_sha12(Path(args.roster_path)) if args.roster_path else None
        )
        if current.get("roster_sha12") is None and readings["roster_sha12"] is not None:
            current["roster_sha12"] = readings["roster_sha12"]
            current["cycle_id"] = uuid.uuid4().hex
        if args.guardar and state_path is None:
            raise ValueError("estado no resoluble para guardar")
        updated, action = decide(readings, current, ahora, args.evento)
        if action["tipo"] not in ACCIONES_VALIDAS:
            raise ValueError(f"accion desconocida: {action['tipo']}")
        code = 0 if action["tipo"] in {"NONE", "ESPERAR"} else 10
        if args.guardar:
            _save_state(state_path, updated)
        payload = {
            "accion": action["tipo"],
            "ejecutor": action["ejecutor"],
            "wake_at": action["wake_at"],
            "rc": code,
            "motivo": "",
            "estado": updated,
        }
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        payload = {
            "accion": "NONE",
            "ejecutor": None,
            "wake_at": None,
            "rc": 9,
            "motivo": reason,
            "estado": copy.deepcopy(ESTADO_INICIAL),
        }
        if state_path is not None and state_path.exists():
            with contextlib.suppress(ValueError):
                payload["estado"] = _read_state(state_path)
        code = 9
    try:
        encoded = json.dumps(
            payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        encoded = json.dumps(
            {
                "accion": "NONE",
                "ejecutor": None,
                "wake_at": None,
                "rc": 9,
                "motivo": str(exc) or type(exc).__name__,
                "estado": copy.deepcopy(ESTADO_INICIAL),
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        code = 9
    print(encoded)
    return code


if __name__ == "__main__":
    sys.exit(main())
