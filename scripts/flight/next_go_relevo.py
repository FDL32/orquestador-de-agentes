"""Selecciona la primera fila SIN USAR del registro markdown de GO de relevo.

Before: se proporciona un registro por `--registro` o `GO_RELEVO_REGISTRO`.
During: se leen las filas `bN` y se ordenan por el sufijo numérico sin escribir.
After: rc 0 imprime un GO libre, rc 3 indica que todos están usados y rc 2
    indica ausencia, ilegibilidad o falta de filas válidas.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path


REGISTRY_ENV = "GO_RELEVO_REGISTRO"
UUID36 = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
ROW_RE = re.compile(
    rf"^\|\s*(b\d+)\s*\|\s*([^|]+?)\s*\|\s*({UUID36})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$"
)


GoRow = tuple[str, str, str, str, str, str]


def _parser() -> argparse.ArgumentParser:
    """Before: no se requiere estado externo.

    During: construye el parser del argumento opcional de registro.
    After: devuelve el parser CLI.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--registro", type=Path, default=None)
    return parser


def _resolve_registry(argument: Path | None) -> Path | None:
    """Before: `argument` es el path explícito o None.

    During: aplica precedencia al argumento y luego a GO_RELEVO_REGISTRO.
    After: devuelve el path elegido o None sin inventar una ruta.
    """
    if argument is not None:
        return argument
    configured = os.environ.get(REGISTRY_ENV)
    return Path(configured) if configured else None


def _read_rows(path: Path) -> list[GoRow]:
    """Before: `path` apunta al registro markdown.

    During: lee UTF-8 y convierte solo filas con seis columnas y UUID36.
    After: devuelve las filas válidas; los errores de I/O se propagan al CLI.
    """
    text = path.read_text(encoding="utf-8")
    rows: list[GoRow] = []
    for line in text.splitlines():
        match = ROW_RE.match(line)
        if match is not None:
            rows.append(match.groups())
    rows.sort(key=lambda row: int(row[0][1:]))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    """Before: argv selecciona opcionalmente un registro de GO.

    During: lee las filas, selecciona la primera SIN USAR y emite instrucciones.
    After: devuelve rc 0, 3 o 2 según el contrato funcional.
    """
    args = _parser().parse_args(argv)
    registry = _resolve_registry(args.registro)
    if registry is None:
        print(f"ERROR: falta --registro o {REGISTRY_ENV}", file=sys.stderr)
        return 2
    try:
        rows = _read_rows(registry)
    except (OSError, UnicodeError) as exc:
        print(f"ERROR: no se pudo leer {registry}: {exc}", file=sys.stderr)
        return 2
    if not rows:
        print("ERROR: el registro no tiene filas bN legibles", file=sys.stderr)
        return 2
    for row in rows:
        if row[5].startswith("SIN USAR"):
            print(
                f"GO LIBRE: {row[0]} ({row[1]}); "
                f"mensaje del usuario {row[2]}; linea {row[3]}; creado {row[4]}"
            )
            print("NO PIDAS OTRO GO AL USUARIO: ya existe una fila SIN USAR.")
            return 0
    print("SIN GO LIBRE: todas las filas bN estan USADO; pide un GO nuevo al usuario.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
