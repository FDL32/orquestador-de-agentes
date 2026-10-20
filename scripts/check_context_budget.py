#!/usr/bin/env python3
"""Guard de presupuesto de contexto para @import (WOT-2026-071a).

Mide el cierre transitivo de @import desde ficheros raiz (default CLAUDE.md)
y emite un WARN por stderr cuando supera el 5% de la ventana de contexto
efectiva (window_tokens, default 200000).

Exit code: SIEMPRE 0 (WARN-only, nunca bloqueante).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def resolve_import_closing(root: Path, roots: list[str]) -> list[Path]:
    """Resuelve el cierre transitivo de @import desde los ficheros raiz.

    Parsea lineas literales de la forma ``@<ruta-relativa>``, resuelve la ruta
    relativa al fichero que la contiene, y recorre transitivamente acumulando
    el set de ficheros del cierre. Deteccion de ciclos: si un fichero ya
    visitado reaparece en la cadena de imports, se ignora (no se vuelve a
    leer ni a expandir) y la resolucion continua con el resto de la cola.

    Args:
        root: Raiz del repositorio donde buscar los ficheros.
        roots: Lista de nombres de ficheros raiz (default ``["CLAUDE.md"]``).

    Returns:
        Lista de rutas absolutas de los ficheros en el cierre transitivo.
    """
    visited: set[Path] = set()
    queue: list[Path] = []

    for root_name in roots:
        candidate = root / root_name
        if candidate.exists():
            queue.append(candidate)

    while queue:
        current = queue.pop(0)
        current_resolved = current.resolve()
        if current_resolved in visited:
            continue
        visited.add(current_resolved)

        try:
            lines = current_resolved.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("@") and len(stripped) > 1:
                imported_rel = stripped[1:].strip()
                imported_path = current_resolved.parent / imported_rel
                if imported_path.exists() and imported_path.resolve() not in visited:
                    queue.append(imported_path)

    return sorted(visited, key=lambda p: str(p))


def measure_chars(paths: list[Path]) -> list[dict]:
    """Mide los chars (len) de cada fichero en el cierre.

    Args:
        paths: Lista de rutas de ficheros a medir.

    Returns:
        Lista de dicts con ``path`` (str) y ``chars`` (int).
    """
    result: list[dict] = []
    for p in paths:
        try:
            chars = len(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            chars = 0
        result.append({"path": str(p), "chars": chars})
    return result


def check_budget(
    window_tokens: int = 200000,
    roots: list[str] | None = None,
    output_json: bool = False,
) -> dict:
    """Ejecuta el guard de presupuesto de contexto.

    Args:
        window_tokens: Tamano de la ventana de contexto efectiva en tokens.
        roots: Lista de ficheros raiz para medir (default ``["CLAUDE.md"]``).
        output_json: Si True, emite JSON a stdout; si False, imprime desglose a stderr.

    Returns:
        Dict con ``total_chars``, ``total_tokens_proxy``, ``window_tokens``,
        ``pct`` y ``files``.
    """
    if roots is None:
        roots = ["CLAUDE.md"]

    root = Path.cwd()
    paths = resolve_import_closing(root, roots)
    measured = measure_chars(paths)

    total_chars = sum(f["chars"] for f in measured)
    total_tokens_proxy = total_chars // 4
    pct = (total_tokens_proxy / window_tokens * 100) if window_tokens > 0 else 0

    result: dict = {
        "total_chars": total_chars,
        "total_tokens_proxy": total_tokens_proxy,
        "window_tokens": window_tokens,
        "pct": round(pct, 2),
        "files": measured,
    }

    if output_json:
        print(json.dumps(result, indent=2))
    else:
        # Desglose por fichero (orden descendente por chars)
        sorted_files = sorted(measured, key=lambda f: f["chars"], reverse=True)
        for f in sorted_files:
            print(f"{f['path']}: {f['chars']} chars", file=sys.stderr)
        if pct > 5.0:
            print(
                f"[check_context_budget] WARN: {pct:.1f}% > 5% del presupuesto",
                file=sys.stderr,
            )

    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Guard de presupuesto de contexto para @import (WARN-only)"
    )
    ap.add_argument(
        "--window-tokens",
        type=int,
        default=200000,
        help="Ventana de contexto efectiva en tokens (default: 200000)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emite resultado JSON a stdout",
    )
    ap.add_argument(
        "--roots",
        nargs="*",
        default=None,
        help="Ficheros raiz para medir (default: CLAUDE.md)",
    )
    args = ap.parse_args(argv)

    check_budget(
        window_tokens=args.window_tokens,
        roots=args.roots,
        output_json=args.output_json,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
