"""Lista los mensajes `createdBy=user` de un hilo del almacen de T3.

Before: el almacen existe y `verify_user_authorization.py` esta junto a este script.
During: se abre en solo lectura, se valida el esquema y se recorre el hilo desde
    `DESDE_ISO` usando las primitivas canonicas del verificador.
After: se imprime una linea por mensaje de usuario y `user msgs: N`; rc 0 es una
    lectura correcta y rc 2 nombra un fallo de apertura o lectura.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType


DB_ENV = "T3_STATE_DB"


def _load_verifier() -> ModuleType:
    """Before: el verificador vive junto a user_msgs.py.

    During: lo carga dinámicamente por ruta, sin depender del cwd ni importar un módulo ajeno.
    After: devuelve el módulo con las primitivas de lectura requeridas.
    """
    path = Path(__file__).resolve().with_name("verify_user_authorization.py")
    spec = importlib.util.spec_from_file_location("flight_user_authorization", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"no se pudo cargar {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parser() -> argparse.ArgumentParser:
    """Before: no se requiere estado externo.

    During: construye el parser con hilo, timestamp opcional y almacen opcional.
    After: devuelve el parser del contrato CLI.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("thread_id")
    parser.add_argument(
        "since",
        nargs="?",
        default="0000-00-00T00:00:00.000Z",
        metavar="DESDE_ISO",
    )
    parser.add_argument("--db", type=Path, default=None)
    return parser


def _database_path(argument: Path | None) -> Path:
    """Before: `argument` es el path explícito o None.

    During: aplica la precedencia argumento, entorno y home del usuario.
    After: devuelve un path portable sin fijar una cuenta o vuelo.
    """
    if argument is not None:
        return argument
    configured = os.environ.get(DB_ENV)
    if configured:
        return Path(configured)
    return Path.home() / ".t3" / "userdata" / "statev2.sqlite"


def main(argv: Sequence[str] | None = None) -> int:
    """Before: argv contiene THREAD_ID, DESDE_ISO opcional y --db opcional.

    During: abre, valida y recorre el almacen read-only, filtrando `created_by=user`.
    After: devuelve rc 0 si la lectura termina o rc 2 con causa en stderr.
    """
    args = _parser().parse_args(argv)
    verifier: ModuleType | None = None
    connection: sqlite3.Connection | None = None
    try:
        verifier = _load_verifier()
        database = _database_path(args.db)
        connection = verifier.open_store_ro(database)
        verifier.check_schema(connection)
        count = 0
        for row in verifier._iter_thread_messages(
            connection, args.thread_id, args.since, ""
        ):
            record = verifier._row_to_record(row)
            if record.created_by == "user":
                count += 1
                print(
                    f"{record.created_at} {record.creation_source} "
                    f"{record.message_id} {record.normalized_text!r}"
                )
        print(f"user msgs: {count}")
        return 0
    except (
        AttributeError,
        ImportError,
        OSError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ) as exc:
        print(f"ERROR: no se pudo abrir o leer el almacen: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        if verifier is not None and isinstance(exc, verifier.InfraError):
            print(f"ERROR: no se pudo abrir o leer el almacen: {exc}", file=sys.stderr)
            return 2
        raise
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
