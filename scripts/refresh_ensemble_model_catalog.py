"""Regenera un snapshot de catalogo desde las dos fuentes declaradas.

WOT-2026-222a s.4: `opencode models` y `kilo models` se capturan POR
SEPARADO, SIN suponer que comparten formato. Cada fuente conserva su comando
exacto, fecha de captura, hash SHA-256 de la salida cruda y la version del
generador (este modulo); el PARSEO linea-a-linea de cada CLI sigue siendo
una aproximacion NO VERIFICADA (no se ha ejecutado `opencode models` ni
`kilo models` reales en esta ronda, igual que declaran las tres fichas
previas y los dos informes de lente P34 r3) -- el Builder debe confirmar la
forma real de cada CLI antes de confiar en el PARSEO; la METADATA de
procedencia (comando, hash, fecha, generador) si es real y esta probada con
`monkeypatch` sobre `subprocess.run` (ver tests/unit/test_ensemble_profile_catalog.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


GENERATOR_VERSION = "1"


def _parse_opencode_models_line(line: str) -> tuple[str, str] | None:
    """Heuristica NO VERIFICADA para UNA linea de `opencode models`.

    codex H-02 (ronda P34 posterior a esta misma ficha): esta funcion es
    INDEPENDIENTE de `_parse_kilo_models_line` -- hoy ambas asumen el mismo
    patron "<backend> <modelo>" separado por el PRIMER espacio porque
    ninguno de los dos CLIs reales se ha ejecutado todavia (misma deuda
    declarada que el modulo), pero son dos funciones, dos puntos de cambio:
    confirmar el formato real de opencode y editar esta NO toca kilo.
    """
    backend, separator, model = line.partition(" ")
    if separator and backend == "opencode" and model.strip():
        return backend, model.strip()
    return None


def _parse_kilo_models_line(line: str) -> tuple[str, str] | None:
    """Heuristica NO VERIFICADA para UNA linea de `kilo models`.

    Ver docstring de `_parse_opencode_models_line`: funcion INDEPENDIENTE,
    no un parser compartido parametrizado por nombre de ejecutable.
    """
    backend, separator, model = line.partition(" ")
    if separator and backend == "kilo" and model.strip():
        return backend, model.strip()
    return None


def _capture_source(executable: str) -> tuple[dict, list[dict]]:
    """Captura UNA fuente; no asume que su formato coincide con la otra.

    Before: `executable` es `opencode` o `kilo`.
    During: ejecuta `<executable> models`, hashea la salida cruda COMPLETA
        (antes de parsear nada) y delega el parseo linea a linea en
        `_parse_opencode_models_line` o `_parse_kilo_models_line` segun
        `executable`, DOS funciones independientes (codex
        H-02), no un unico parser compartido. Ambas formas siguen siendo
        NO VERIFICADAS contra un CLI real; el Builder debe confirmar el
        formato de CADA UNA por separado antes de depender del parseo (el
        hash de la salida cruda queda intacto aunque el parseo este mal).
    After: `(source_metadata, entries)`. `source_metadata` lleva `command`,
        `backend`, `captured_at`, `sha256` y `generator_version`. `entries`
        es la lista de pares `{backend, model}` detectados (puede ser vacia
        si el formato real no coincide con la suposicion -- eso lo nombra la
        barrera de catalogo huerfano, no este capturador).
    """
    command = [executable, "models"]
    completed = subprocess.run(  # noqa: S603 - command viene de un literal fijo (opencode|kilo), no de input externo
        command, check=True, capture_output=True, text=True
    )
    raw = completed.stdout
    captured_at = datetime.now(timezone.utc).isoformat()
    source_metadata = {
        "command": " ".join(command),
        "backend": executable,
        "captured_at": captured_at,
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "generator_version": GENERATOR_VERSION,
    }
    if executable == "opencode":
        parse_line = _parse_opencode_models_line
    elif executable == "kilo":
        parse_line = _parse_kilo_models_line
    else:
        raise ValueError(f"unknown executable: {executable}")
    entries = []
    for line in raw.splitlines():
        parsed = parse_line(line)
        if parsed is not None:
            backend, model = parsed
            entries.append({"backend": backend, "model": model})
    return source_metadata, entries


def refresh_snapshot(output: Path, ttl_hours: int = 24) -> dict:
    """Captura las dos fuentes POR SEPARADO y escribe el snapshot completo."""
    sources: list[dict] = []
    entries: list[dict] = []
    for executable in ("opencode", "kilo"):
        source_metadata, source_entries = _capture_source(executable)
        sources.append(source_metadata)
        entries.extend(source_entries)
    captured = datetime.now(timezone.utc)
    catalog = {
        "captured_at": captured.isoformat(),
        "expires_at": (captured + timedelta(hours=ttl_hours)).isoformat(),
        "sources": sources,
        "entries": entries,
    }
    output.write_text(json.dumps(catalog, indent=2) + chr(10), encoding="utf-8")
    return catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ttl-hours", type=int, default=24)
    args = parser.parse_args(argv)
    refresh_snapshot(args.output, ttl_hours=args.ttl_hours)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
