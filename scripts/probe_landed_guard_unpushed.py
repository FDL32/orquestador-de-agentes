#!/usr/bin/env python3
"""Probe de WOT-2026-023q: el guard commits-landed bendecia un commit NUNCA pusheado.

QUE DEMUESTRA
-------------
``check_backlog_commits_landed.py`` clasificaba por CAPA 3 (**OK_BY_SUBJECT**: el ticket-ID
aparece en el subject de algun commit de ``origin/main``) **ANTES** de comprobar el hecho de
que el SHA registrado **existe y cuelga de la rama local pero NO esta en el remoto**
(**PENDING_GROUPED_PUSH**).

Consecuencia: si un ticket ya tenia OTRO commit aterrizado con su ID en el subject -- un
contrato, un probe, lo que sea -- entonces su commit de cierre, **aun sin pushear**, quedaba
bendecido como aterrizado, y el guard reportaba ``ERROR=0`` sobre trabajo que **no habia
salido de la maquina**. La politica de **push agrupado al final de sesion GARANTIZA** que
ese caso ocurra en cada sesion, asi que no era un caso raro: era el caso normal.

**El arreglo es de PRECEDENCIA:** un HECHO sobre el SHA (existe y es alcanzable desde mi
rama) vence a una CONVENCION sobre el ID (aparece en algun subject). CAPA 3 sigue existiendo,
pero por DEBAJO: es para SHAs cuyo objeto YA NO ESTA (reescritura de historia, 016e/016h) o
que fueron superados en otra rama (squash-merge) -- ninguno de los dos es alcanzable desde
HEAD, asi que subir PENDING por encima no los toca.

POLARIDAD (importa: este probe queda TRACKEADO y sobrevive al fix)
------------------------------------------------------------------
Es un **DETECTOR DE REGRESION**, no el reproductor de un bug vivo:

    exit 0  -> el guard dice PENDING_GROUPED_PUSH. Correcto.
    exit 1  -> el guard dice OK_BY_SUBJECT: **el bug de 023q ha VUELTO.**

HERMETICO Y PORTABLE: clona el repo del motor en un temporal y **sintetiza** su propio
backlog. No lee ni escribe el workspace real, y no lleva ninguna ruta de ninguna maquina.

Uso:
    python scripts/probe_landed_guard_unpushed.py
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "scripts" / "check_backlog_commits_landed.py"
TICKET = "WOT-2026-0QQQ"


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        args, capture_output=True, text=True, check=False
    )


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args])


def force_rm(path: Path) -> None:
    """git deja sus objetos READ-ONLY: sin este handler, rmtree falla en Windows."""

    def on_error(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=on_error)


def build_repo(work: Path) -> tuple[Path, str]:
    """Un repo con origin, un commit del ticket YA aterrizado, y otro SIN PUSHEAR."""
    origin = work / "origin.git"
    run(["git", "init", "--quiet", "--bare", str(origin)])
    repo = work / "repo"
    run(["git", "clone", "--quiet", str(origin), str(repo)])
    git(repo, "config", "user.name", "probe")
    git(repo, "config", "user.email", "probe@local")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")

    # El guard exige que el motor-root lleve MANIFEST.distribute (check_backlog_commits_landed.py:448):
    # sin el sale con rc=2 y NO audita nada.
    (repo / "MANIFEST.distribute").write_bytes(b"# probe\n")

    # (1) un commit del ticket que SI aterriza: su subject lleva el ID.
    (repo / "contract.txt").write_bytes(b"contract\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--no-verify", "-qm", f"{TICKET}: contrato (aterrizado)")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")

    # (2) el commit de CIERRE: en main local, NUNCA pusheado. Es el que se archiva.
    (repo / "fix.txt").write_bytes(b"the fix\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--no-verify", "-qm", f"{TICKET}: el fix (SIN pushear)")
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, sha


def build_backlog(work: Path, sha: str) -> Path:
    """Un destino-rol minimo con la fila archivada que cita el commit sin pushear."""
    collab = work / "dest" / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    header = (
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    )
    (collab / "backlog.md").write_text(f"# Backlog\n\n{header}", encoding="utf-8")
    row = (
        f"| Alta | {TICKET} | fila del probe: su commit NO se ha pusheado | motor/probe "
        f"| completed | commit:{sha} | probe | probe |\n"
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        f"# Archivo\n\n{header}{row}", encoding="utf-8"
    )
    return work / "dest"


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="probe023q_"))
    try:
        repo, sha = build_repo(work)
        dest = build_backlog(work, sha)

        # El fixture ASERTA SU PROPIO MONTAJE: sin esto, un probe verde no prueba nada.
        remotes = git(repo, "branch", "-r", "--contains", sha).stdout.strip()
        if remotes:
            print(f"PROBE INVALIDO: {sha[:7]} SI esta en un remoto ({remotes!r}).")
            return 2
        print(f"commit de cierre : {sha[:7]}  -- git branch -r --contains -> VACIO")
        print(f"commit hermano   : el ID {TICKET} SI aterrizo, con el ID en el subject")
        print("  -> el escenario EXACTO que CAPA 3 se tragaba\n")

        r = run(
            [
                sys.executable,
                str(GUARD),
                "--project-root",
                str(dest),
                "--motor-root",
                str(repo),
            ]
        )
        out = r.stdout + r.stderr
        for line in out.splitlines():
            if "OK=" in line or "audited" in line or sha[:7] in line:
                print("   " + line.strip())
        print(f"   rc={r.returncode}\n")

        # EL GUARD TIENE QUE HABER CORRIDO. Sin esto, un guard que revienta (rc=2, cero
        # salida) no dispara la rama de REGRESION y el probe cantaria OK: un probe que
        # aprueba porque su instrumento NO se ejecuto es el falso-verde que este probe
        # existe para cazar. Verificar el veredicto POSITIVAMENTE, nunca por ausencia.
        if "audited" not in out:
            print(
                "PROBE INVALIDO: el guard no llego a auditar nada (no hay linea 'audited')."
            )
            print(f"stderr: {r.stderr.strip()[:200]}")
            return 2

        if "PENDING_GROUPED_PUSH=1" in out:
            print(
                "OK: el guard clasifica el commit sin pushear como PENDING_GROUPED_PUSH."
            )
            print(
                "Un HECHO sobre el SHA (existe y cuelga de mi rama) vence a una CONVENCION"
            )
            print("sobre el ID (aparece en algun subject de origin/main).")
            return 0

        print("REGRESION DE WOT-2026-023q: el guard NO marco PENDING_GROUPED_PUSH.")
        print(
            "Bendijo via CAPA 3 (OK_BY_SUBJECT) un commit que no ha salido de la maquina,"
        )
        print(
            "porque un commit HERMANO del mismo ticket si aterrizo con el ID en el subject."
        )
        print("rc=0 => ERROR=0 => 'todo aterrizado' es FALSO.")
        return 1
    finally:
        force_rm(work)


if __name__ == "__main__":
    raise SystemExit(main())
