"""WOT-2026-027h: colision INTER-plan en el directorio queued/ de planes de vuelo.

CONTRATO (check HERMANO, no ampliacion de validate_batch_dag).
validate_batch_dag recibe UN dag_path posicional y emite UN veredicto: es CIEGO
al CONJUNTO. Solo detecta colisiones ENTRE GRUPOS del MISMO dag. Este check mira el
DIRECTORIO queued/ entero y FALLA si:
  (i)  un ticket.id aparece en >=2 planes distintos, o
  (ii) dos planes distintos declaran la misma shared_surface (normalizada).

NON-GOALS (hard-stop, criterio adjudicado 2026-07-24):
  - NO fusiona ni coordina planes. Solo DETECTA la colision; no la resuelve.
  - NO tiene allowlist de colisiones declaradas. Un ticket en 2 planes o una
    shared_surface compartida SIEMPRE FALLA, sin excepcion. El caso legitimo de dos
    planes que se coordinan a proposito se resuelve NO teniendolos ambos en queued/
    a la vez (el que espera va a otra carpeta), no relajando el check. Un allowlist
    convertiria el check en coordinador y esconderia justo el fallo que debe cazar
    (defecto cazado por Codex 2026-07-24).
  - NO reescribe el contrato un-DAG-un-veredicto de validate_batch_dag.

REUSO: _normalize_surface se IMPORTA de validate_batch_dag (una sola fuente de la
forma canonica de una ruta), no se reescribe.

CABLEADO: run_flight_plan_collision_check en prepush_check.py closeout (WARN inicial,
is_blocking=False; el queued/ real ya esta sucio antes de introducir la barrera y
bloquear con esa deuda historica seria un falso-rojo heredado -- precedente
run_guard_wiring_orphan_check). Criterio de salida a bloqueante: WOT-2026-040r.

Docstring-as-spec:
  Before: queued_dir es un directorio existente con planes *.json (o vacio).
  During: lee cada *.json (read-only), extrae ticket-ids (fullmatch, robusto a
          placeholders de grupo y a tickets polimorfico) y shared_surfaces
          normalizadas; cruza los conjuntos entre planes. Sin I/O de escritura.
  After:  find_collisions() devuelve la lista de colisiones (vacia si ninguna);
          main() imprime el reporte y devuelve exit 1 si hay >=1 colision, 0 si no,
          2 si el directorio no existe. Un JSON ilegible es una colision-error
          reportada (fail-closed), nunca un verde mudo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from validate_batch_dag import _normalize_surface  # noqa: E402


_TICKET_ID_RE = re.compile(r"^(?:WOT|WP|WT|CTL)-\d{4}-[0-9a-z]+$", re.IGNORECASE)


@dataclass(frozen=True)
class Collision:
    kind: str
    key: str
    plans: tuple[str, ...]

    def render(self) -> str:
        planos = ", ".join(sorted(self.plans))
        if self.kind == "ticket":
            return f"ticket {self.key!r} aparece en >=2 planes de queued/: {planos}"
        if self.kind == "surface":
            return (
                f"shared_surface {self.key!r} declarada en >=2 planes de "
                f"queued/: {planos}"
            )
        return f"error leyendo plan: {self.key}"


def _iter_ticket_ids(value: Any) -> list[str]:
    ids: list[str] = []
    if not isinstance(value, list):
        return ids
    for item in value:
        candidate: Any = None
        if isinstance(item, str):
            candidate = item
        elif isinstance(item, dict):
            candidate = item.get("id")
        if isinstance(candidate, str) and _TICKET_ID_RE.fullmatch(candidate.strip()):
            ids.append(candidate.strip())
    return ids


def _plan_ticket_ids(data: dict[str, Any]) -> set[str]:
    ids: set[str] = set(_iter_ticket_ids(data.get("tickets")))
    for group in data.get("groups") or []:
        if isinstance(group, dict):
            ids.update(_iter_ticket_ids(group.get("tickets")))
    return ids


def _plan_surfaces(data: dict[str, Any]) -> set[str]:
    surfaces: set[str] = set()
    for group in data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for surface in group.get("shared_surfaces") or []:
            if isinstance(surface, str) and surface.strip():
                surfaces.add(_normalize_surface(surface))
    return surfaces


def _load_plans(queued_dir: Path) -> tuple[dict[str, dict[str, Any]], list[Collision]]:
    plans: dict[str, dict[str, Any]] = {}
    errors: list[Collision] = []
    for path in sorted(queued_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(Collision("error", f"{path.name}: {exc}", (path.name,)))
            continue
        if isinstance(data, dict):
            plans[path.name] = data
        else:
            errors.append(
                Collision("error", f"{path.name}: raiz no es objeto JSON", (path.name,))
            )
    return plans, errors


def build_ticket_index(queued_dir: Path) -> dict[str, list[str]]:
    plans, _ = _load_plans(queued_dir)
    index: dict[str, list[str]] = {}
    for name, data in plans.items():
        for tid in _plan_ticket_ids(data):
            index.setdefault(tid, []).append(name)
    return index


def build_surface_index(queued_dir: Path) -> dict[str, list[str]]:
    plans, _ = _load_plans(queued_dir)
    index: dict[str, list[str]] = {}
    for name, data in plans.items():
        for surface in _plan_surfaces(data):
            index.setdefault(surface, []).append(name)
    return index


def find_collisions(queued_dir: Path) -> list[Collision]:
    plans, collisions = _load_plans(queued_dir)

    ticket_index: dict[str, list[str]] = {}
    surface_index: dict[str, list[str]] = {}
    for name, data in plans.items():
        for tid in _plan_ticket_ids(data):
            ticket_index.setdefault(tid, []).append(name)
        for surface in _plan_surfaces(data):
            surface_index.setdefault(surface, []).append(name)

    for tid, names in sorted(ticket_index.items()):
        if len(set(names)) >= 2:
            collisions.append(Collision("ticket", tid, tuple(sorted(set(names)))))
    for surface, names in sorted(surface_index.items()):
        if len(set(names)) >= 2:
            collisions.append(Collision("surface", surface, tuple(sorted(set(names)))))
    return collisions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "FALLA si un ticket aparece en >=2 planes de queued/ o dos planes "
            "declaran la misma shared_surface (WOT-2026-027h). Check HERMANO de "
            "validate_batch_dag: mira el CONJUNTO, no un solo DAG. Sin allowlist."
        )
    )
    parser.add_argument(
        "--queued-dir",
        type=Path,
        required=True,
        help="Directorio de planes de vuelo *.json (queued/).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emitir el resultado en formato JSON (machine-readable).",
    )
    args = parser.parse_args(argv)

    queued_dir: Path = args.queued_dir
    if not queued_dir.is_dir():
        message = f"directorio no existe: {queued_dir}"
        if args.json:
            print(json.dumps({"ok": False, "error": message}))
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 2

    collisions = find_collisions(queued_dir)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": not collisions,
                    "collisions": [
                        {"kind": c.kind, "key": c.key, "plans": list(c.plans)}
                        for c in collisions
                    ],
                }
            )
        )
    else:
        if not collisions:
            print("[OK] queued/ sin colisiones inter-plan")
        else:
            print(f"[FAIL] {len(collisions)} colision(es) inter-plan en queued/:")
            for c in collisions:
                print(f"  - {c.render()}")

    return 1 if collisions else 0


if __name__ == "__main__":
    raise SystemExit(main())
