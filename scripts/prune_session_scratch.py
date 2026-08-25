#!/usr/bin/env python3
"""Poda por ANTIGUEDAD el scratch de sesiones del harness (uso MANUAL en cierres).

QUE PODA Y QUE NO -- la distincion importa y se ha confundido antes:

- **SI**: el scratch que el HARNESS (Claude Code) crea por sesion bajo
  ``<TEMP>/claude/<proyecto>/<session-uuid>/`` (``scratchpad/`` + ``tasks/``).
  No lo crea el motor: medido 2026-08-25, ``grep`` de esa ruta sobre ``scripts/``
  da 0 hits. Es acumulacion normal de un directorio efimero que nadie poda.
- **NO**: la fuga de ``WOT-2026-059d``, que vive en la RAIZ del TEMP y la crean
  los tests del motor (``_make_repo`` + ``git init``). Esa NO se arregla podando
  -- se arregla limpiando en el propio test -- y este script no la toca.

POR QUE ES MANUAL Y NO UN HOOK: borrar es irreversible y el criterio de "sesion
muerta" es del operador, no del repo. Va como paso OPCIONAL de los prompts de
cierre, con ``--dry-run`` por defecto.

SEGURIDAD (las tres, deliberadas):
1. ``--dry-run`` ES EL DEFECTO. Borrar exige ``--apply`` explicito.
2. Exclusion por ``mtime``: una sesion tocada dentro de la ventana NO se poda.
   Es lo que protege a la sesion VIVA que ejecuta el cierre -- sin necesidad de
   conocer su id.
3. Frontera dura: solo se borra bajo ``<TEMP>/claude/``, y solo directorios de
   profundidad 2 (``<proyecto>/<uuid>``). Cualquier ruta fuera de esa raiz aborta.

Before: ``--root`` apunta al scratch del harness (o se deriva de ``TEMP``).
During: lista los directorios de sesion, filtra por ``mtime`` y, solo con
    ``--apply``, los borra con ``shutil.rmtree``. Sin ``--apply`` no escribe nada.
After: imprime el censo (total / candidatos / conservados) y, con ``--apply``,
    cuantos borro. Exit 0 aunque no haya nada que podar: no encontrar basura no
    es un fallo.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path


DEFAULT_DAYS = 14
_HARNESS_DIRNAME = "claude"


def default_root() -> Path:
    """Raiz del scratch del harness, derivada del TEMP del sistema.

    NUNCA hardcodea una ruta de usuario: la deriva de ``tempfile.gettempdir()``,
    que respeta ``TEMP``/``TMP``. Si el harness cambiara de sitio, se pasa
    ``--root`` explicito.
    """
    return Path(tempfile.gettempdir()) / _HARNESS_DIRNAME


def session_dirs(root: Path) -> list[Path]:
    """Directorios de sesion: profundidad EXACTA 2 bajo ``root``.

    ``<root>/<proyecto>/<session-uuid>``. No desciende mas: el contenido de una
    sesion (``scratchpad/``, ``tasks/``) no se enumera aqui.
    """
    if not root.is_dir():
        return []
    out: list[Path] = []
    for proj in sorted(root.iterdir()):
        if not proj.is_dir():
            continue
        out.extend(sess for sess in sorted(proj.iterdir()) if sess.is_dir())
    return out


def is_stale(path: Path, cutoff_ts: float) -> bool:
    """True si ``path`` no se ha tocado desde ``cutoff_ts``.

    Usa el mtime MAS RECIENTE entre el propio directorio y sus hijos directos:
    un `scratchpad/` escrito hace un minuto mantiene VIVA la sesion aunque el
    directorio padre conserve un mtime viejo. Sin esto, la sesion que ejecuta el
    cierre podria auto-podarse.
    """
    try:
        newest = path.stat().st_mtime
        for child in path.iterdir():
            newest = max(newest, child.stat().st_mtime)
    except OSError:
        # No se pudo leer -> se CONSERVA. Un desconocido no es basura.
        return False
    return newest < cutoff_ts


def _guard_inside_root(target: Path, root: Path) -> None:
    """Aborta si ``target`` no cuelga de ``root``. Frontera dura, no confianza."""
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SystemExit(
            f"ABORTA: {target} esta FUERA de {root}; no se borra nada"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prune_session_scratch",
        description=(
            "Poda por antiguedad el scratch de sesiones del harness. "
            "DRY-RUN por defecto: borrar exige --apply."
        ),
    )
    parser.add_argument(
        "--root",
        default=None,
        help="raiz del scratch (default: <TEMP>/claude, derivado de TEMP/TMP)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"conserva lo tocado en los ultimos N dias (default: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="BORRA de verdad. Sin este flag solo informa (dry-run).",
    )
    args = parser.parse_args(argv)

    if args.days < 1:
        print(
            "error: --days debe ser >= 1 (una ventana de 0 podaria lo vivo)",
            file=sys.stderr,
        )
        return 2

    root = Path(args.root) if args.root else default_root()
    if not root.is_dir():
        print(f"[prune-scratch] raiz inexistente: {root} (nada que podar)")
        return 0

    cutoff = time.time() - args.days * 86400
    sessions = session_dirs(root)
    stale = [p for p in sessions if is_stale(p, cutoff)]

    print(f"[prune-scratch] raiz: {root}")
    print(
        f"[prune-scratch] sesiones={len(sessions)} "
        f"candidatas(>{args.days}d)={len(stale)} conservadas={len(sessions) - len(stale)}"
    )

    if not args.apply:
        print(
            "[prune-scratch] DRY-RUN: no se ha borrado nada. Anade --apply para ejecutar."
        )
        return 0

    removed = 0
    failed = 0
    for path in stale:
        _guard_inside_root(path, root)
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as exc:
            failed += 1
            print(f"[prune-scratch] NO borrado {path}: {exc}", file=sys.stderr)

    print(f"[prune-scratch] borradas={removed} fallidas={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
