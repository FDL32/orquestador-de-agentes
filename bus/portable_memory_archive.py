#!/usr/bin/env python3
"""Lectura del archive de memoria PORTABLE (`archive/observations.YYYY-MM.jsonl`).

WOT-2026-024r (A1): hasta hoy la memoria portable se escribia, se versionaba y se
pusheaba -- y **nadie la leia de vuelta**. Los cuatro consumidores medidos del
archive (`check_portable_memory_archive_schema`, `check_portable_memory_promotion`,
`prepush_check`, `reconcile_portable_memory`) son guards y reconciliadores: validan,
comparan y promueven, pero ninguno CONSUME. No faltaba un enlace: faltaba el ROL de
lector. Este modulo es ese rol.

Por que un modulo y no un import de `scripts/reconcile_portable_memory.py`:
importar el script desde `bus/` invertiria la dependencia (`bus -> scripts`) y
arrastraria `--apply` y la semantica "promovido == esta en un commit", que pertenece
a reconcile y no al lector. Y reimplementar el parseo crearia **dos definiciones de
identidad de observacion que divergirian en silencio**. Asi que la convencion vive
aqui una sola vez y ambos la consumen.

Que encapsula (lo que lo salva de ser un `json.loads` 1:1):
  1. La CONVENCION de nombres: un fichero por mes UTC, `observations.YYYY-MM.jsonl`,
     y el hecho de que hay que recorrerlos TODOS -- una leccion promovida un mes
     anterior ya viajo, y tratarla como nueva la duplicaria.
  2. La CLAVE DE DEDUP: `(topic, source_ticket)`, la misma que usa reconcile.
  3. El fail-closed ante JSONL corrupto, distinguiendo "no existe" (memoria vacia,
     legitima) de "roto" (error explicito, no un traceback opaco).

Before: ``root`` es la raiz de un repo con `.agent/runtime/memory/archive/`.
During: lee y parsea los ficheros de archive; no escribe NUNCA.
After: devuelve dicts de observacion; lanza ``CorruptArchiveError`` si un JSONL
esta roto -- fail-closed explicito, nunca un verde silencioso.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


#: Ruta del archive relativa a la raiz del repo. Misma que
#: ``reconcile_portable_memory.ARCHIVE_DIR_REL``: si divergen, el lector y el
#: reconciliador mirarian sitios distintos.
ARCHIVE_DIR_REL = Path(".agent/runtime/memory/archive")

#: Patron de la convencion mes-a-mes (UTC).
ARCHIVE_GLOB = "observations.*.jsonl"


class CorruptArchiveError(RuntimeError):
    """Un fichero de archive no es JSONL valido.

    Se distingue de "no existe" (memoria vacia, legitima) y de "invalido segun el
    schema" (eso lo caza ``validate_observations --strict``). Un JSON roto ni
    siquiera llega al validador: revienta al parsear. Sin esta excepcion el fallo
    saldria como TRACEBACK -- fail-closed de facto pero por CRASH, y "el script
    peto" es indistinguible de un bug del propio lector.
    """


def iter_archive_months(root: Path) -> list[Path]:
    """TODOS los ficheros de archive de ``root``, ordenados, no solo el del mes.

    Before: ``root`` es la raiz de un repo (puede no tener archive todavia).
    During: hace glob de la convencion mes-a-mes bajo ``ARCHIVE_DIR_REL``.
    After: lista ordenada de rutas; ``[]`` si el directorio no existe -- un repo
    sin memoria portable es legitimo, no un error.
    """
    archive_dir = root / ARCHIVE_DIR_REL
    if not archive_dir.is_dir():
        return []
    return sorted(archive_dir.glob(ARCHIVE_GLOB))


def read_archive_observations(root: Path) -> list[dict[str, Any]]:
    """Todas las observaciones del archive portable de ``root``.

    Before: ``root`` es la raiz de un repo.
    During: recorre TODOS los meses (no solo el actual) y parsea cada linea.
    After: lista de dicts en orden de fichero y linea. Lanza
    ``CorruptArchiveError`` con fichero y numero de linea si el JSONL esta roto.
    """
    records: list[dict[str, Any]] = []
    for path in iter_archive_months(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CorruptArchiveError(f"{path}: no legible ({exc})") from exc
        for lineno, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CorruptArchiveError(
                    f"{path}:{lineno}: JSON invalido ({exc})"
                ) from exc
            if isinstance(record, dict):
                records.append(record)
    return records


def record_key(record: dict[str, Any]) -> tuple[str, str | None]:
    """Clave de dedup de una observacion.

    Identica a ``reconcile_portable_memory.record_key``: si divergieran, el lector
    y el reconciliador tendrian dos nociones distintas de "la misma leccion".
    """
    return (record.get("topic", ""), record.get("source_ticket"))


def dedup_key(record: dict[str, Any]) -> tuple[Any, ...]:
    """Identidad ESTABLE de una entrada, para unir archive con la copia viva.

    Before: ``record`` es una observacion ya parseada.
    During: prefiere el ``id`` estable cuando existe (143 de 153 entradas medidas
    el 2026-07-28 lo tienen); para las que no, cae a ``record_key`` mas el
    ``timestamp``, que es lo unico que las distingue sin inventar schema.
    After: tupla hashable utilizable como clave de un dict.
    """
    stable = record.get("id")
    if isinstance(stable, str) and stable:
        return ("id", stable)
    topic, ticket = record_key(record)
    return ("fallback", topic, ticket, record.get("timestamp"))
