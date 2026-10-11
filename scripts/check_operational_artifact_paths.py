#!/usr/bin/env python3
r"""Guard: un artefacto OPERATIVO del destino no puede llevar un rol sin resolver
(WOT-2026-054g).

Norma ya escrita (``prompts/orchestrator_autonomous_ticket_batch.md``, seccion
"PORTABLE artifacts keep roles; OPERATIONAL artifacts resolve them"): un
artefacto PORTABLE (prompt/skill/script del motor) debe llevar los roles
``<MOTOR_ROOT>``/``<DESTINO_ROOT>`` sin resolver -- eso es lo correcto, viaja a
cada destino. Un artefacto OPERATIVO (informe, arranque, plan de vuelo) lo
consume un agente FRIO contra UN destino concreto; ahi un rol sin resolver es
una pregunta que ese agente no puede responder.

Censo que lo origina (2026-08-10, re-medido 2026-10-11): 29/345 informes de
``orchestrator_pipeline/reports/`` llevaban el rol crudo. La cifra de hoy es
evidencia FECHADA (crece el denominador, no el invariante); el gate mide la
PROPIEDAD, nunca el numero.

Ambito deliberado -- SOLO rutas operativas del DESTINO, nunca el motor
-----------------------------------------------------------------------
``check_distribution_agnostic.py`` (el guard hermano) mira la direccion
OPUESTA: lo que viaja (motor) no puede nombrar ESTA maquina. Este guard mira
el destino: ``orchestrator_pipeline/reports/``, ``orchestrator_pipeline/
arranques/`` y ``orchestrator_pipeline/flight_plans/`` -- las tres rutas que
el contrato nombra explicitamente como OPERATIVAS. El motor (``prompts/``,
``skills/``, ``scripts/``) queda FUERA por diseno: ahi el rol sin resolver es
lo correcto, y mezclar ambas direcciones en un solo guard confundiria la
Forbidden Surface de ``check_distribution_agnostic.py``.

FAIL-CLOSED (mismo patron que el guard hermano)
------------------------------------------------
Si ``--project-root`` no resuelve a un destino con al menos uno de los tres
directorios, o si los tres estan ausentes/vacios, el guard EMITE WARN (no
ERROR): un destino recien instalado sin ningun informe todavia no es un
defecto, pero el aviso evita que un "0 hits sobre 0 ficheros" se confunda con
un "0 hits sobre 345 ficheros" en un reporte.

Baseline por FICHERO con conteo, anclado por PAR (ruta, ausencia) -- DoD(d)
-----------------------------------------------------------------------------
Re-medido 2026-10-11: 121 ficheros / 918 hits bajo las 3 rutas operativas (la
cifra "29/345" del contrato solo cubria `reports/*.md`+`*.json`; `arranques/`
multiplica la deuda). Eximir linea a linea (patron del guard hermano) seria
una allowlist de ~900 entradas, fragil y sin valor real -- la propiedad que
importa no es "esta linea exacta", es "este FICHERO ya tenia N hits conocidos
al nacer el guard, y no puede tener MAS sin que alguien se entere".

El baseline es un JSON ``{ruta: n_hits_conocidos}``. Un fichero AUSENTE del
baseline con >=1 hit es NUEVO -> FALLA (DoD b). Un fichero PRESENTE en el
baseline cuyo recuento de hits ACTUAL es <= el declarado, pasa (deuda
heredada, Non-goal explicito: "NO reescribir los informes historicos"). Si
su recuento SUBE por encima del baseline, FALLA -- alguien anadio un rol
nuevo a un fichero ya contaminado, y eso si es un defecto nuevo evitable.
Un fichero del baseline que BAJA a 0 queda STALE (su entrada ya no protege
nada) -> se reporta para poda, nunca bloqueante por si solo (limpiar deuda no
puede ser lo que rompe el gate).

Dos mutaciones independientes (DoD e):
  (1) un informe NUEVO (fuera del baseline) con rol sin resolver -> ROJO;
      resuelto -> VERDE.
  (2) un fichero YA en el baseline, sin cambios -> VERDE; con un rol NUEVO
      ANADIDO (su conteo sube sobre lo declarado) -> ROJO.

Before: ``--project-root`` resuelve al destino (``runtime.project_root`` en el
    caller); los tres directorios pueden existir o no.
During: ``git``-independiente (lee el arbol de trabajo, no el indice) -- un
    informe generado en esta misma sesion y aun sin `git add` debe auditarse
    igual que uno ya trackeado (mismo argumento que el guard hermano: el
    consumidor del artefacto no distingue tracked de untracked).
After: exit 0 si ningun hit sobrevive sin eximir y la allowlist no esta
    stale; exit 1 listando (fichero, linea, texto) de los hits y las
    entradas stale. Nunca escribe nada.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_ROLE_RE = re.compile(r"<MOTOR_ROOT>|<DESTINO_ROOT>")

# Las tres rutas OPERATIVAS declaradas por el contrato (relativas al destino).
# Deliberadamente NO incluye `.agent/planning/` ni `.agent/collaboration/`:
# el contrato ancla el censo a `orchestrator_pipeline/`, y ampliar el ambito
# sin re-medir el baseline seria una expansion de alcance no declarada.
OPERATIONAL_DIRS = (
    "orchestrator_pipeline/reports",
    "orchestrator_pipeline/arranques",
    "orchestrator_pipeline/flight_plans",
)

_SKIP_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".ico", ".woff", ".woff2"}
)


def _iter_files(root: Path) -> list[Path]:
    """Ficheros de texto bajo las 3 rutas operativas, arbol de trabajo (no git index)."""
    out: list[Path] = []
    for rel in OPERATIONAL_DIRS:
        d = root / rel
        if not d.is_dir():
            continue
        out.extend(
            p
            for p in sorted(d.rglob("*"))
            if p.is_file() and p.suffix.lower() not in _SKIP_SUFFIXES
        )
    return out


def scan(root: Path) -> tuple[list[Path], dict[str, int]]:
    """(ficheros auditados, {ruta relativa '/': n_hits}). Solo cuenta, DoD mide
    conteo-por-fichero, no linea individual (ver docstring del modulo)."""
    files = _iter_files(root)
    counts: dict[str, int] = {}
    for f in files:
        rel = f.relative_to(root).as_posix()
        try:
            txt = f.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            counts[rel] = counts.get(rel, 0) + 1
            continue
        n = sum(1 for line in txt.splitlines() if _ROLE_RE.search(line))
        if n:
            counts[rel] = n
    return files, counts


DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parent / "operational_artifact_paths_baseline.json"
)


def load_baseline(path: Path | None = None) -> dict[str, int]:
    path = path or DEFAULT_BASELINE_PATH
    if not path.exists():
        return {}
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in data.items()}


# --------------------------------------------------------------------- audit
def audit(root: Path, baseline: dict[str, int] | None = None) -> tuple[int, list[str]]:
    """(exit_code, lineas). Publica siempre cuantos ficheros audito.

    Fichero NUEVO (fuera del baseline) con >=1 hit -> no_exempt (DoD b).
    Fichero del baseline con conteo ACTUAL <= declarado -> deuda heredada,
    pasa (Non-goal: no se reescriben los informes historicos).
    Fichero del baseline con conteo ACTUAL > declarado -> no_exempt (se
    anadio un rol nuevo a un fichero ya contaminado).
    Entrada del baseline cuyo conteo actual es 0 -> STALE (reportado, nunca
    bloqueante por si solo: limpiar deuda no puede romper el gate).
    """
    baseline = baseline if baseline is not None else load_baseline()
    out: list[str] = []

    present_dirs = [d for d in OPERATIONAL_DIRS if (root / d).is_dir()]
    if not present_dirs:
        out.append(
            "[operational-artifact-paths] WARN: ninguna de las 3 rutas operativas "
            f"existe bajo {root} ({', '.join(OPERATIONAL_DIRS)}) -- destino sin "
            "informes todavia, o project-root no resuelve al destino."
        )
        return 0, out

    files, counts = scan(root)
    out.append(
        f"[operational-artifact-paths] {len(present_dirs)}/3 rutas presentes -> "
        f"{len(files)} ficheros auditados, {len(counts)} con hits"
    )

    not_exempt: list[tuple[str, int, int]] = []  # (fichero, actual, declarado)
    for f, actual in counts.items():
        declared = baseline.get(f)
        if declared is None:
            not_exempt.append((f, actual, 0))
        elif actual > declared:
            not_exempt.append((f, actual, declared))

    stale = sorted(
        f for f, declared in baseline.items() if declared > 0 and counts.get(f, 0) == 0
    )

    out.append(f"[operational-artifact-paths] {len(not_exempt)} ficheros sin eximir")
    for f, actual, declared in sorted(not_exempt):
        out.append(f"      {f}: {actual} hits (baseline declara {declared})")

    if stale:
        out.append("")
        out.append(
            "[operational-artifact-paths] AVISO: entradas de baseline STALE (el "
            "fichero ya no tiene hits -- se puede retirar del baseline):"
        )
        out.extend(f"      {f}" for f in stale)

    if not_exempt:
        out.append("")
        out.append(
            "[operational-artifact-paths] ERROR: un artefacto OPERATIVO del "
            "destino no puede llevar un rol <MOTOR_ROOT>/<DESTINO_ROOT> sin "
            "resolver -- resuelvelo a la ruta absoluta real. Si es un informe "
            "NUEVO legitimamente generado con el rol (p.ej. plantilla que un "
            "proceso posterior resuelve), anadelo al baseline en "
            f"{DEFAULT_BASELINE_PATH.name} declarando su conteo."
        )
        return 1, out

    out.append("[operational-artifact-paths] OK: ningun fichero excede su baseline.")
    return 0, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--project-root", default=str(Path.cwd()))
    ap.add_argument(
        "--baseline", default=None, help="Ruta a baseline JSON alternativo."
    )
    args = ap.parse_args(argv)
    root = Path(args.project_root).resolve()
    baseline = load_baseline(Path(args.baseline)) if args.baseline else None
    code, lines = audit(root, baseline)
    stream = sys.stderr if code else sys.stdout
    for ln in lines:
        print(ln, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
