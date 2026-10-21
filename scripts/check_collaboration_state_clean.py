#!/usr/bin/env python3
"""WOT-2026-026x (c): el estado OPERATIVO de ``.agent/collaboration/`` no puede
volver a ser trackeado por el motor ni re-declarado como distribuible.

Contexto (medido, no relatado): DEC-025B-001 (commit ``b4379a93``) ya ejecuto la
sustancia de la Opcion 1 -- el motor dejo de trackear las 6 proyecciones de
``.agent/collaboration/`` (``git rm --cached`` + ``.gitignore``) y `MANIFEST.distribute`
retiro esas entradas (ahora son comentarios, lineas 99-111). Lo que NO existia era la
BARRERA de reintroduccion (DoD punto c): un guard que cace que alguien vuelva a meter
estado operativo por una de las DOS puertas. Este fichero es esa barrera.

Dos superficies, dos preguntas DISTINTAS (leaccion de WOT-2026-024x: un guard que
muerde pero mira donde el fallo NO ocurre):

- (i)  "¿VIAJA a un destino?" -> la oracle correcta es la DECLARACION de
       ``MANIFEST.distribute``, no el tracking. El instalador copia del filesystem lo
       que el manifiesto DECLARA (mismo motivo por el que 024h NO usa ``git ls-files``).
       Un fichero UNTRACKED pero declarado VIAJA igual. Si ninguna ruta bajo
       ``.agent/collaboration/`` esta declarada activa, nada operativo viaja.
- (ii) "¿El motor lo TRACKEA?" -> DoD (a)/(b): el repo motor debe tener 0 ficheros
       bajo ``.agent/collaboration/`` en su indice. Es una propiedad de higiene del repo,
       no la pregunta de "viaja". El guard NOMBRA el repo que mide (leaccion
       ``same-file-two-repos-two-tracking-contracts``): mide ``--motor-root``, jamas el
       destino.

Before: ``--motor-root`` apunta al repo del motor (por defecto, el repo de este script)
        y existe ``MANIFEST.distribute`` en esa raiz.
During: corre ``git ls-files -- .agent/collaboration/`` con ``-C motor_root`` (solo
        lectura del indice) y lee las lineas no-comentario de ``MANIFEST.distribute``
        que empiezan por ``.agent/collaboration/``. No muta nada.
After:  exit 0 y ``[collab-state-clean] OK`` si ambas superficies estan limpias;
        exit 1 con ``VIOLATION`` nombrando ficheros trackeados y/o lineas de manifiesto
        si alguna reintroduce estado operativo. ``git`` no ejecutable o raiz que no es
        repo => VIOLATION fail-closed (no puede certificar).
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DISTRIBUTE = "MANIFEST.distribute"
COLLAB_PREFIX = ".agent/collaboration/"


def tracked_collaboration(motor_root: Path) -> list[str]:
    """Ficheros del INDICE del motor bajo ``.agent/collaboration/`` (posix-relativos).

    Fail-closed: si ``motor_root`` no es un repo o ``git`` no corre, devuelve una
    entrada centinela en ``tracked`` para que el guard reporte VIOLACION en vez de un
    verde vacuo (un probe que puede devolver vacio porque el binario no esta es
    indistinguible de "limpio": fail-open por construccion).
    """
    try:
        proc = subprocess.run(  # noqa: S603 - argv constante, sin input externo
            ["git", "-C", str(motor_root), "ls-files", "--", COLLAB_PREFIX],  # noqa: S607 - git del PATH
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ["<git-no-disponible-o-raiz-no-repo>"]
    if proc.returncode != 0:
        return ["<no-es-un-repo-git>"]
    return [line for line in proc.stdout.splitlines() if line.strip()]


def distributable_collaboration_lines(motor_root: Path) -> list[str]:
    """Lineas ACTIVAS (no comentario) de MANIFEST.distribute bajo COLLAB_PREFIX."""
    manifest = motor_root / MANIFEST_DISTRIBUTE
    if not manifest.exists():
        return []
    hits: list[str] = []
    for raw in manifest.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(COLLAB_PREFIX):
            hits.append(line)
    return hits


def find_violations(motor_root: Path) -> dict[str, list[str]]:
    """Superficies con estado operativo reintroducido: {tracked:[...], declared:[...]}.

    Diccionario VACIO = coherente (invariante del motor, hoy MEDIDO verde en 5bed0948).
    """
    violations: dict[str, list[str]] = {}
    tracked = tracked_collaboration(motor_root)
    if tracked:
        violations["tracked"] = tracked
    declared = distributable_collaboration_lines(motor_root)
    if declared:
        violations["declared"] = declared
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed: el motor no trackea ni declara distribuible estado "
            "operativo de .agent/collaboration/ (WOT-2026-026x c)."
        )
    )
    parser.add_argument(
        "--motor-root",
        default=str(MOTOR_ROOT),
        help="Raiz del repo MOTOR a medir (por defecto: el repo de este script).",
    )
    args = parser.parse_args(argv)
    motor_root = Path(args.motor_root).resolve()

    violations = find_violations(motor_root)
    if not violations:
        print(
            f"[collab-state-clean] OK: {motor_root.as_posix()} no trackea ni declara "
            "estado operativo bajo .agent/collaboration/"
        )
        return 0

    print(
        f"[collab-state-clean] VIOLATION en repo={motor_root.as_posix()}: estado "
        "operativo reintroducido (DEC-025B-001 lo retiró deliberadamente):"
    )
    for rel in violations.get("tracked", []):
        print(f"  - TRACKeado en el indice del motor: {rel}")
    for line in violations.get("declared", []):
        print(f"  - DECLARADO distribuible en MANIFEST.distribute: {line}")
    print(
        "\nRemedio: el motor NO versiona ni distribuye estado operativo del dogfooding "
        "(superficie viva del DESTINO). Para el tracking:\n"
        "  git rm --cached <fichero>   # y dejarlo en .gitignore\n"
        "Y para la declaracion, RETIRAR la linea de MANIFEST.distribute (no comentarla "
        "con un valor que el instalador aun pueda copiar del filesystem -- 024h).\n"
        "NO silencies este guard ni amplíes una allowlist: cualquier excepcion exige "
        "decision/ADR explicita."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
