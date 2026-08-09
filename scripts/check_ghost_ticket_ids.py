#!/usr/bin/env python3
"""Detecta ids de ticket CITADOS en git que no tienen fila en ninguna superficie.

WOT-2026-053i. Un id que aparece en un mensaje de commit publicado pero que no
existe ni en `backlog.md` (cola viva) ni en `_archive/backlog_done.md` es un
FANTASMA: el trabajo se hizo y se publico, pero no quedo registrado en ninguna
de las dos superficies que el contrato declara como fuentes.

POR QUE UN GUARD SEPARADO Y NO UNA AMPLIACION DE `check_backlog_contract.py`:
aquel es HERMETICO por diseno -- 0 `subprocess`, 0 `git`, medido -- y esa
propiedad es la que lo hace ejecutable en cualquier entorno y rapido. Meterle una
dependencia de git lo volveria sensible al entorno (repo sin git, shallow clone,
rebase en curso) y contaminaria un contrato que hoy no puede fallar por causas
externas. Un bucle adversarial de 8 lentes voto 8/8 por la separacion.

QUE MIDE Y QUE NO (frontera declarada, no es un detalle):
- Mide la INTERSECCION: ids citados en los ultimos N commits que no tienen fila.
- NO mide el inverso (filas sin commit): una ficha `pending` legitimamente no
  tiene commit todavia, asi que ese sentido no es una senal de nada.
- La ventana de commits es finita (`--max-commits`): un id citado hace 2000
  commits y nunca fichado NO se detecta. Es un limite ASUMIDO -- el objetivo es
  cazar la fuga RECIENTE, que es cuando la correccion es barata, no auditar la
  historia entera.

MEDIDO 2026-08-09, la fuga que lo origina: `WOT-2026-053f` se cito en un commit
publicado con CI verde y no tenia fila en ninguna superficie. Esa MISMA fuga se
habia corregido HORAS ANTES para `WOT-2026-053e`, se documento por que ocurria, y
se repitio tres commits despues con el ticket mas importante de la tanda. El
censo posterior encontro 9 fantasmas, no 1: no era un descuido puntual sino un
patron que ningun mecanismo miraba.

Before / During / After
-----------------------
Before: `--project-root` apunta a un destino con `.agent/collaboration/`; el cwd
    (o `--repo-root`) es un repo git legible. Ninguno se muta.
During: lee las dos superficies de backlog y `git log --format=%s`. Sin red, sin
    escritura. Si git no esta disponible o falla, SKIP explicito (exit 0): un
    guard que no puede medir no debe inventarse un veredicto.
After: exit 0 si no hay fantasmas nuevos fuera del baseline; exit 1 nombrando
    cada fantasma y el commit que lo cita. No muta nada.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# Un id CITADO en git pero sin fila. Se ancla al patron canonico `WOT-YYYY-NNNx`.
_TICKET_RE = re.compile(r"\b(WOT-\d{4}-\d{3}[a-z]?)\b")

# Fila de tabla cuyo id vive en la celda 1 o 2: el archive tiene secciones con
# `| Prioridad | Ticket | ...` y otras con `| Ticket | Estado | ...`. Cubrir
# ambas es obligatorio -- medido: 5 filas cerradas viven en la segunda forma y un
# regex que solo mirase la primera las daria por inexistentes (falso fantasma).
_ROW_RE = re.compile(
    r"^\|[^|]*\|\s*(WOT-\d{4}-\d{3}[a-z]?)\s*\|" r"|^\|\s*(WOT-\d{4}-\d{3}[a-z]?)\s*\|",
    re.M,
)

# BASELINE DECLARADA (WOT-2026-053i): los 9 fantasmas que existian al cablear el
# guard. Se anclan como DEUDA CONOCIDA para que el guard frene la fuga NUEVA sin
# bloquear por historia que nadie va a reconstruir hoy. Es el mismo patron que
# `_ARCHIVE_ARITY_LEGACY_BASELINE` en check_backlog_contract.
#
# El censo es EVIDENCIA FECHADA, no criterio: el criterio es "cero fantasmas
# NUEVOS". Vaciar esta lista es trabajo de otro ticket, no de este guard.
GHOST_BASELINE: frozenset[str] = frozenset(
    {
        "WOT-2026-029f",
        "WOT-2026-042d",
        "WOT-2026-042p",
        "WOT-2026-044t",
        "WOT-2026-045",
        "WOT-2026-047e",
        "WOT-2026-047l",
        "WOT-2026-047n",
        "WOT-2026-047r",
    }
)


def collect_row_ids(collab: Path) -> set[str]:
    """Ids con fila en CUALQUIERA de las dos superficies del contrato."""
    ids: set[str] = set()
    for rel in ("backlog.md", "_archive/backlog_done.md"):
        path = collab / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig")
        for match in _ROW_RE.finditer(text):
            ids.add(match.group(1) or match.group(2))
    return ids


def collect_cited_ids(repo_root: Path, max_commits: int) -> dict[str, str] | None:
    """Ids citados en los asuntos de commit, mapeados a su commit mas reciente.

    Devuelve None si git no puede consultarse: el llamador debe SKIP, nunca
    asumir "no hay citas" (eso seria un verde por ausencia de medicion).
    """
    try:
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(repo_root),
                "log",
                "--format=%h %s",
                f"-n{max_commits}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    cited: dict[str, str] = {}
    for line in result.stdout.splitlines():
        sha, _, subject = line.partition(" ")
        for tid in _TICKET_RE.findall(subject):
            cited.setdefault(tid, sha)
    return cited


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Detecta ids de ticket citados en git sin fila en el backlog."
    )
    ap.add_argument("--project-root", required=True, help="raiz del repo_destino")
    ap.add_argument("--repo-root", default=".", help="repo git cuyos commits se leen")
    ap.add_argument("--max-commits", type=int, default=400)
    ap.add_argument(
        "--no-baseline",
        action="store_true",
        help="ignora GHOST_BASELINE y reporta TODOS los fantasmas (censo)",
    )
    args = ap.parse_args()

    collab = Path(args.project_root) / ".agent" / "collaboration"
    if not collab.is_dir():
        print(f"[ghost-ids] SKIP: no existe {collab}", file=sys.stderr)
        return 0

    cited = collect_cited_ids(Path(args.repo_root), args.max_commits)
    if cited is None:
        print(
            "[ghost-ids] SKIP: git no disponible o ilegible; no se puede medir.",
            file=sys.stderr,
        )
        return 0

    rows = collect_row_ids(collab)
    ghosts = {t: sha for t, sha in cited.items() if t not in rows}
    if not args.no_baseline:
        ghosts = {t: sha for t, sha in ghosts.items() if t not in GHOST_BASELINE}

    print(
        f"[ghost-ids] {len(cited)} ids citados en {args.max_commits} commits; "
        f"{len(rows)} con fila; {len(ghosts)} fantasma(s) fuera de baseline."
    )
    if not ghosts:
        print("[ghost-ids] OK: ningun id publicado se quedo sin fila.")
        return 0

    for tid, sha in sorted(ghosts.items()):
        print(
            f"[ghost-ids] FANTASMA {tid}: citado en el commit {sha} y sin fila ni en "
            f"backlog.md ni en _archive/backlog_done.md. El trabajo se publico y no "
            f"quedo registrado: anade su fila (terminal -> archive) antes de cerrar.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
