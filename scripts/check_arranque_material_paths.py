#!/usr/bin/env python3
"""WOT-2026-055s: material de arranque MAL COLOCADO en la raiz del destino.

Contexto (medido, no relatado): hasta este guard, un
``ARRANQUE_MUTACION_PRUEBA.md`` en la RAIZ del destino y otro en
``orchestrator_pipeline/arranques/`` salian IGUAL por ``git status`` (``??`` los
dos) -- el ``.gitignore`` de la cadena declarada gobierna QUE SE VERSIONA, pero
nada detectaba ni enrutaba un fichero de material de arranque fuera de ella.
Premise Re-check 2026-10-11: probe en la raiz del destino -> ``??`` sin protesta
de ningun guard. O sea: CONVENCION, no barrera (AGENTS.md: una norma sin
mecanismo depende de que alguien se acuerde).

Ambito deliberado -- SOLO el nivel RAIZ del destino, NO recursivo
-----------------------------------------------------------------
* Un fichero gobernado en ``orchestrator_pipeline/arranques/`` (la ruta
  declarada) nunca puede estar "mal colocado" por definicion: no se mira ahi.
* Un fichero gobernado en cualquier OTRO subdirectorio (ni raiz ni la ruta
  declarada) tampoco cuenta: fuera de la raiz no es el fallo que este guard
  mide. Ambito del contrato T-055S-001; NO amplitudir a recursivo.
* ``orchestrator_pipeline/reports/*`` tiene su PROPIA allowlist de prefijos
  (``backlog_triage_*``, ``batch_run_*``, ``MUTATION_WOT-*``, ...) completamente
  distinta: un fichero con prefijo gobernado ahi NUNCA debe disparar este guard
  (Forbidden Surface / DoD (d) -- control negativo).

Los 4 prefijos gobernados (README de ``arranques/`` + ``.gitignore`` del
destino, re-confirmados 2026-10-11): ``ARRANQUE_``, ``ENCARGO_``,
``PROPUESTA_`` e ``INCIDENT_`` -- el cuarto tipo se anadio 2026-08-24; el texto
fechado del contrato original solo cita los 3 primeros porque es prosa anterior.

Censo al nacer (2026-10-11): 0 ficheros gobernados en la raiz del destino, asi
que la barrera nace BLOQUEANTE sin deuda historica que amnistiar a WARN (mismo
argumento que ``run_arranques_index_check`` / ``run_operational_artifact_paths_
check`` en ``prepush_check.py``).

El guard SOLO detecta y reporta: no mueve ni borra nada (decidir el destino de
ficheros historicos es decision humana, Forbidden Surface del ticket).

Before: ``--destino-root`` (o el ``destino_root`` de ``find_misplaced``/``audit``)
    resuelve a la raiz del repo_destino; la raiz puede existir o no.
During: lee SOLO el nivel raiz (``iterdir``, sin recursion) y clasifica FICHEROS
    por prefijo literal. Git-independiente: mide el arbol de trabajo, asi que un
    fichero aun sin ``git add`` es igual de mal colocado.
After:  exit 1 si la raiz no existe / no es directorio (fail-closed: un verde
    sobre 0 ficheros medidos es el falso-verde "no hice nada" de CEM) o si hay
        >=1 fichero gobernado en la raiz, listandolos y remitiendo a la ruta
        declarada; exit 0 con el DENOMINADOR publicado SIEMPRE (N ficheros en la
        raiz, M gobernados). Nunca escribe nada.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


GOVERNED_PREFIXES = ("ARRANQUE_", "ENCARGO_", "PROPUESTA_", "INCIDENT_")

# Ruta de aterrizaje declarada (README + .gitignore del destino, 2026-08-13).
DECLARED_ROUTE = "orchestrator_pipeline/arranques"


def find_misplaced(destino_root: Path) -> list[str]:
    """Nombres de fichero gobernados en la RAIZ, orden alfabetico.

    Before: ``destino_root`` resoluble a un directorio (si no lo es, devuelve
        [] -- la decision de severidad es de ``audit``, que es el que publica).
    During: un SOLO nivel (``iterdir``), solo ``is_file()``, match de prefijo
        literal sobre los 4 gobernados. Sin recursion deliberada (ver docstring
        del modulo: ambito del contrato T-055S-001).
    After: lista de nombres ordenada alfabeticamente; [] si la raiz no existe o
        no contiene ficheros gobernados en su nivel raiz.
    """
    if not destino_root.is_dir():
        return []
    return sorted(
        p.name
        for p in destino_root.iterdir()
        if p.is_file() and p.name.startswith(GOVERNED_PREFIXES)
    )


def audit(destino_root: Path) -> tuple[int, list[str]]:
    """(exit_code, lineas). Publica SIEMPRE el denominador.

    Before: ``destino_root`` resoluble o no (cada caso tiene veredicto propio).
    During: cuenta los ficheros del nivel raiz, filtra por prefijo gobernado y
        redacta el informe. Read-only, sin tocar git.
    After: (1, lineas) si la raiz no existe (fail-closed, sin verde mudo) o si
        hay >=1 fichero gobernado mal colocado, listandolos; (0, lineas) con el
        denominador ``N ficheros en la raiz, M gobernados`` publicado en TODOS
        los caminos (un "OK" sin numeros es indistinguible de "no medi nada").
    """
    root = Path(destino_root)
    if not root.is_dir():
        return 1, [
            f"[arranque-material-paths] ERROR: raiz inexistente o no-directorio "
            f"({root}) -- no se pudo medir la raiz del destino; fail-closed, "
            "sin verde mudo (0 ficheros medidos no es un OK)."
        ]

    root_files = sorted(p.name for p in root.iterdir() if p.is_file())
    misplaced = [name for name in root_files if name.startswith(GOVERNED_PREFIXES)]

    out = [
        f"[arranque-material-paths] {len(root_files)} fichero(s) en la raiz de "
        f"{root}, {len(misplaced)} con prefijo gobernado "
        f"({', '.join(GOVERNED_PREFIXES)})"
    ]
    if misplaced:
        out.extend(f"      - {name}" for name in misplaced)
        out.append(
            "[arranque-material-paths] ERROR: material de arranque MAL COLOCADO "
            f"en la raiz. Ruta de aterrizaje declarada: {DECLARED_ROUTE}/ (ahi el "
            ".gitignore de la cadena ya lo versiona). Muevelo ahi -- este guard "
            "solo DETECTA: no mueve ni borra nada."
        )
        return 1, out

    out.append(
        "[arranque-material-paths] OK: ningun fichero gobernado en la raiz del destino."
    )
    return 0, out


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--destino-root`` (default: cwd). rc 0 limpio, 1 con hallazgos."""
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed: detecta material de arranque (ARRANQUE_/ENCARGO_/"
            "PROPUESTA_/INCIDENT_) mal colocado en la RAIZ del destino "
            "(WOT-2026-055s). Solo detecta; no mueve ni borra."
        )
    )
    parser.add_argument(
        "--destino-root",
        default=str(Path.cwd()),
        help="Raiz del repo_destino (por defecto: directorio actual).",
    )
    args = parser.parse_args(argv)
    code, lines = audit(Path(args.destino_root))
    stream = sys.stderr if code else sys.stdout
    for ln in lines:
        print(ln, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
