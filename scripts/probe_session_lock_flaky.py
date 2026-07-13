#!/usr/bin/env python3
"""Reproductor del flaky de sesion bajo contencion xdist (WOT-2026-023l).

EL PROBLEMA QUE REPRODUCE
-------------------------
``tests/test_init_session_scratch.py::TestMaidenVoyage::
test_takeover_competition_exactly_one_wins`` falla de forma INTERMITENTE bajo la
suite completa concurrente, y **solo ahi**:

    aislado, 300 repeticiones sin carga -> wins=1 las 300 veces (correcto)
    modulo solo con -n 4, 3 corridas    -> 0 fallos
    SUITE COMPLETA con -n auto          -> ~3 de cada 6 corridas en rojo

Necesita la contencion REAL de los workers de xdist: no se reproduce sin ella. Por
eso este probe corre la suite entera, no el test suelto -- correrlo aislado da un
falso "ya no pasa".

HISTORIA DEL SINTOMA (importante: NO confundir los dos fallos)
-------------------------------------------------------------
    ANTES de WOT-2026-023n:  "Exactly 1 should win, got 2"  -> DOS ganadores
    DESPUES de 023n:         "Exactly 1 should win, got 0"  -> NINGUNO

023n arreglo un bug REAL (la propiedad del lock es (pid, session_id), no solo el
pid) y eso **cambio el modo de fallo**, lo que prueba que tocaba una rama viva.
Pero **NO mato el flaky**, y no podia: bajo xdist los workers son PROCESOS
DISTINTOS, asi que la rama ``pid == os.getpid()`` que 023n corrige NO SE EJERCE.

MECANISMO: NO DETERMINADO. No lo inventes.
------------------------------------------
``got 0`` significa que NINGUN hilo adquiere. Apunta al marker ``.takeover``: los
dos hilos compiten por el con O_EXCL y el perdedor ve ``age < TAKEOVER_TTL`` y
**se rinde** (``return False``) en vez de esperar o reintentar. El marker esta
disenado para excluir PROCESOS, y el test lanza HILOS del mismo proceso.

Hipotesis ABIERTAS, ninguna verificada:
  (a) el perdedor del marker deberia reintentar/esperar en vez de rendirse;
  (b) O_EXCL sobre NTFS bajo contencion real;
  (c) el timeout de ``tasklist`` en ``_is_pid_alive_best_effort`` (5s) expirando
      bajo carga.

Uso:
    python scripts/probe_session_lock_flaky.py [--runs N]

Sale con 1 si REPRODUCE el fallo (y vuelca el traceback), 0 si no lo reproduce en
N corridas -- lo cual NO significa "arreglado": el flaky es intermitente.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = (
    "tests/test_init_session_scratch.py::TestMaidenVoyage::"
    "test_takeover_competition_exactly_one_wins"
)


def _run_suite() -> tuple[str, str]:
    """Run the FULL suite under xdist. Returns (summary_line, full_output)."""
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "-n",
            "auto",
            "-p",
            "no:cacheprovider",
            "-q",
            "--no-header",
            "--tb=long",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    summary = [
        line
        for line in output.splitlines()
        if re.search(r"\d+ (passed|failed|error)", line)
    ]
    return (summary[-1].strip() if summary else "NO SUMMARY"), output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce the session-lock flaky under real xdist contention."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=6,
        help="Full-suite runs before giving up (default: 6; it reproduced ~3/6).",
    )
    args = parser.parse_args()

    print(
        "Probe WOT-2026-023l: suite COMPLETA bajo xdist (la contencion es el vector)."
    )
    print("Correr el test aislado NO reproduce: da un falso 'ya no pasa'.\n")

    for attempt in range(1, args.runs + 1):
        summary, output = _run_suite()
        hit = any(
            line.startswith(("FAILED", "ERROR")) and "init_session_scratch" in line
            for line in output.splitlines()
        )
        print(f"  corrida {attempt}/{args.runs}: {summary}")
        if not hit:
            continue

        print("\n  *** REPRODUCIDO. Traceback: ***\n")
        capture = False
        for line in output.splitlines():
            if re.match(r"_{3,}.*(TestMaidenVoyage|TestInit|TestArchive)", line):
                capture = True
            if capture:
                print(f"  {line[:118]}")
                if line.startswith("===") and "short" in line:
                    break
        print("\n  Lee el modo de fallo: 'got 2' (dos ganadores) es el bug que")
        print("  WOT-2026-023n YA arreglo. 'got 0' (ninguno) es el flaky VIVO.")
        return 1

    print(f"\n  NO reproducido en {args.runs} corridas.")
    print("  Esto NO significa 'arreglado': el flaky es INTERMITENTE (~3/6 medido).")
    print("  Sube --runs antes de concluir nada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
