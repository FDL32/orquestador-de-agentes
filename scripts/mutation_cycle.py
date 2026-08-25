#!/usr/bin/env python3
"""WOT-2026-040d: ciclo de mutation seguro que restaura el arbol PRE-mutacion.

El ciclo historico ``aplicar mutante -> test cae -> revertir`` usaba
``git checkout <fichero>`` para revertir, que restaura a HEAD: si el FIX del
ticket aun no esta commiteado, ese checkout lo borra entero y el test sigue
cayendo por la razon equivocada (medido 2026-07-23, dos veces en el mismo
vuelo: FP-20260723b, tickets 039g y 039d -- hubo que re-aplicar los edits a
mano).

Este helper reemplaza ese revert por SNAPSHOT + RESTORE del working tree: hace
una copia byte a byte de los ficheros antes de la mutacion y los restaura
SIEMPRE al terminar el ciclo (en `finally`), de modo que el fix sin commitear y
cualquier otro cambio del working tree sobreviven intactos.

CLI:

    python scripts/mutation_cycle.py -- ruta1 ruta2 -- comando con args

- Las rutas a proteger van ANTES del doble guion ``--``.
- El comando a ejecutar (la parada del ciclo donde el test debe caer) va
  DESPUES del doble guion ``--``.
- El helper: 1) fotografia las rutas, 2) ejecuta el comando con el rc real,
  3) en `finally` restaura las rutas, 4) propaga el rc del comando.

Exit codes:

- 0  -> el comando corrio y los ficheros quedaron restaurados.
- rc del comando si el comando fallo (>=1), propagado tal cual.
- 125+ -> el helper no pudo completar la ceremonia (snapshot o restore
  fallidos), independiente del rc del comando.

Contract core exportable (testable sin CLI):
    snapshot(paths) -> dict[Path, bytes]
    restore(snapshot) -> None
    run_cycle(snapshot, command) -> int   (propaga rc real, restaura en finally)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def snapshot(paths: Sequence[str | Path]) -> dict[Path, bytes]:
    """Copia byte a byte del working tree de `paths` ANTES de la mutacion.

    Before: cada ruta existe y es un fichero legible (o se lanza el error).
    During: lee los bytes crudos de cada ruta; sin escribir nada. No toca git.
    After: devuelve {path: bytes}. La copia es la unica fuente de verdad de que
        el FIX sin commitear sobreviva al ciclo.
    """
    snap: dict[Path, bytes] = {}
    for raw in paths:
        p = Path(raw)
        snap[p] = p.read_bytes()
    return snap


def restore(snapshot_set: dict[Path, bytes]) -> list[Path]:
    """Restaura el working tree a la copia pre-mutacion.

    Before: snapshot_set dictado por `snapshot`.
    During: reescribe los bytes originales en cada ruta (crea el padre si falta).
    After: devuelve la lista de rutas restauradas. Sin tocar git.
    """
    restored: list[Path] = []
    for path, data in snapshot_set.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        restored.append(path)
    return restored


def run_cycle(
    snapshot_set: dict[Path, bytes],
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
) -> int:
    """Ejecuta la parada del ciclo y RESTAURA SIEMPRE el snapshot (en finally).

    Before: snapshot_set capturado pre-mutacion; command no vacio.
    During: ejecuta `command` con `subprocess.run` (cwd opcional); despues, en
        `finally`, restaura el snapshot. Sin tuberias: el rc que se lee es el
        del comando real, no el de un pipe.
    After: devuelve el rc del comando (>=0). Incluso si el comando falla o
        lanza, el working tree queda restaurado al estado pre-mutacion.
    """
    try:
        proc = subprocess.run(list(command), cwd=str(cwd) if cwd else None)  # noqa: S603
        return proc.returncode
    finally:
        restore(snapshot_set)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mutation_cycle",
        description=(
            "Ejecuta un ciclo de mutation y restaura SIEMPRE el working tree "
            "pre-mutacion (protege el fix sin commitear de un revert destructivo)."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # El primer `--` suele ser el marcador "fin de opciones" del CLI (argparse);
    # se descarta para que el separador real vuelo--comando sea el siguiente.
    if argv and argv[0] == "--":
        argv = argv[1:]
    try:
        sep = argv.index("--")
    except ValueError:
        print(
            "uso: mutation_cycle.py -- ruta1 ruta2 ... -- comando [args...]",
            file=sys.stderr,
        )
        return 125
    protected = argv[:sep]
    command = argv[sep + 1 :]
    if not protected:
        print("error: no hay rutas a proteger antes de '--'", file=sys.stderr)
        return 125
    if not command:
        print("error: no hay comando despues de '--'", file=sys.stderr)
        return 125
    try:
        snap = snapshot(protected)
    except OSError as exc:
        print(f"error: no se pudo fotografiar el working tree: {exc}", file=sys.stderr)
        return 125
    try:
        return run_cycle(snap, command)
    except OSError as exc:
        print(f"error: no se pudo restaurar el snapshot: {exc}", file=sys.stderr)
        return 126


if __name__ == "__main__":
    raise SystemExit(main())
