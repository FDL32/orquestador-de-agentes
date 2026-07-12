#!/usr/bin/env python3
"""
Validador de batch_dag.json (WOT-2026-022r)

Verifica que un DAG de grupos producido por /backlog-triage (esquema
"autonomous-batch-dag/v1") sea estructuralmente valido antes de que un
ejecutor (p.ej. /orchestrate-pipeline) lo consuma.

Reglas de rechazo (exit 1):
1. Ciclo en el grafo de grupos (siguiendo depends_on_groups).
2. Inconsistencia entre depends_on_groups y blocks_groups: si G1 declara
   G2 en blocks_groups, G2 debe declarar G1 en depends_on_groups (y
   viceversa).
3. Grupo sin common_gate (falta la clave, es null, o es cadena vacia /
   solo espacios).
4. Solapamiento de shared_surfaces entre DOS GRUPOS INDEPENDIENTES (sin
   camino de dependencia entre ellos en ninguna direccion). Grupos
   conectados por un camino de dependencia (directo o transitivo) pueden
   compartir superficies: se ejecutan en serie, es seguro.
5. Basicos de esquema: "schema" == "autonomous-batch-dag/v1"; claves de
   grupo obligatorias presentes; "class" en {S, M, L}; id de grupo
   desconocido referenciado en depends_on_groups/blocks_groups; un mismo
   ticket apareciendo en dos grupos.

La regla 4 (solapamiento de superficies) es un camino de codigo
INDEPENDIENTE de las reglas 1 y 2 (ciclo / common_gate): debe poder
disparar sobre un DAG aciclico y con todos los grupos gateados (de lo
contrario la regla no tiene dientes). "Independiente" se calcula por
alcanzabilidad/ancestria en el DAG (camino transitivo), no solo por
aristas directas.

Uso:
    python scripts/validate_batch_dag.py <path-a-dag.json> [--json]

Salida:
- Exit 0: el DAG es valido.
- Exit 1: al menos un error encontrado (se listan todos, no solo el primero).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_SCHEMA = "autonomous-batch-dag/v1"
VALID_CLASSES = {"S", "M", "L"}
REQUIRED_GROUP_KEYS = {
    "id",
    "tickets",
    "depends_on_groups",
    "blocks_groups",
    "shared_surfaces",
    "class",
    "autonomy_mode",
    "common_gate",
}


def _errors_single_group(
    group: dict[str, Any], group_ids: set[str], ticket_owner: dict[str, str]
) -> list[str]:
    """Validate one group's required keys, id, class, common_gate, tickets."""
    errors: list[str] = []
    gid = group.get("id")

    missing = REQUIRED_GROUP_KEYS - group.keys()
    if missing:
        errors.append(f"grupo '{gid}': faltan claves obligatorias: {sorted(missing)}")

    if isinstance(gid, str) and gid:
        if gid in group_ids:
            errors.append(f"id de grupo duplicado: '{gid}'")
        group_ids.add(gid)
    else:
        errors.append(f"grupo con 'id' invalido: {gid!r}")

    cls = group.get("class")
    if cls not in VALID_CLASSES:
        errors.append(
            f"grupo '{gid}': class '{cls}' invalida, debe ser uno de "
            f"{sorted(VALID_CLASSES)}"
        )

    gate = group.get("common_gate")
    if not isinstance(gate, str) or not gate.strip():
        errors.append(f"grupo '{gid}': common_gate ausente o vacio")

    for ticket in group.get("tickets") or []:
        if ticket in ticket_owner:
            errors.append(
                f"ticket '{ticket}' aparece en dos grupos: "
                f"'{ticket_owner[ticket]}' y '{gid}'"
            )
        else:
            ticket_owner[ticket] = gid

    return errors


def _errors_unknown_refs(group: dict[str, Any], group_ids: set[str]) -> list[str]:
    """Validate depends_on_groups/blocks_groups reference known group ids."""
    errors: list[str] = []
    gid = group.get("id")
    for ref_field in ("depends_on_groups", "blocks_groups"):
        errors.extend(
            f"grupo '{gid}': '{ref_field}' referencia id desconocido '{ref}'"
            for ref in (group.get(ref_field) or [])
            if ref not in group_ids
        )
    return errors


def _errors_schema_basics(data: dict[str, Any]) -> list[str]:
    """Validate top-level schema tag and per-group required keys/enums."""
    errors: list[str] = []

    schema = data.get("schema")
    if schema != REQUIRED_SCHEMA:
        errors.append(f"schema '{schema}' invalido: se esperaba '{REQUIRED_SCHEMA}'")

    groups = data.get("groups")
    if not isinstance(groups, list):
        errors.append("falta 'groups' (debe ser una lista)")
        return errors

    group_ids: set[str] = set()
    ticket_owner: dict[str, str] = {}

    for group in groups:
        if not isinstance(group, dict):
            errors.append(f"grupo invalido (no es objeto): {group!r}")
            continue
        errors.extend(_errors_single_group(group, group_ids, ticket_owner))

    for group in groups:
        if not isinstance(group, dict):
            continue
        errors.extend(_errors_unknown_refs(group, group_ids))

    return errors


def _build_depends_map(groups: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Map group id -> set of group ids it depends_on (raw, unvalidated refs kept)."""
    depends: dict[str, set[str]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id")
        if not isinstance(gid, str):
            continue
        depends[gid] = set(group.get("depends_on_groups") or [])
    return depends


def _errors_cycle(groups: list[dict[str, Any]]) -> list[str]:
    """Detect cycles in the depends_on_groups graph via DFS coloring."""
    depends = _build_depends_map(groups)
    errors: list[str] = []

    white, gray, black = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(depends, white)

    def visit(node: str, stack: list[str]) -> bool:
        color[node] = gray
        stack.append(node)
        for dep in depends.get(node, set()):
            if dep not in color:
                continue
            if color[dep] == gray:
                cycle = [*stack[stack.index(dep) :], dep]
                errors.append(
                    "ciclo detectado en depends_on_groups: " + " -> ".join(cycle)
                )
                return True
            if color[dep] == white and visit(dep, stack):
                return True
        stack.pop()
        color[node] = black
        return False

    for node in list(depends.keys()):
        if color[node] == white and visit(node, []):
            break

    return errors


def _errors_blocks_consistency(groups: list[dict[str, Any]]) -> list[str]:
    """If G1 blocks G2, then G2 must depend_on G1 (and vice versa)."""
    errors: list[str] = []
    depends = _build_depends_map(groups)

    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id")
        if not isinstance(gid, str):
            continue
        errors.extend(
            f"inconsistencia: grupo '{gid}' declara blocks_groups "
            f"'{blocked}', pero '{blocked}' no declara '{gid}' en "
            "depends_on_groups"
            for blocked in (group.get("blocks_groups") or [])
            if gid not in depends.get(blocked, set())
        )

    return errors


def _reachable(start: str, depends: dict[str, set[str]]) -> set[str]:
    """All groups reachable from start by following depends_on_groups edges."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        for dep in depends.get(node, set()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def _errors_surface_overlap(groups: list[dict[str, Any]]) -> list[str]:
    """
    Independent code path: reject shared_surfaces overlap between two
    groups with NO dependency path connecting them in either direction
    (ancestor/descendant via depends_on_groups, transitive).
    """
    errors: list[str] = []
    depends = _build_depends_map(groups)

    valid_groups = [
        g for g in groups if isinstance(g, dict) and isinstance(g.get("id"), str)
    ]

    ancestors_or_descendants: dict[str, set[str]] = {}
    for group in valid_groups:
        gid = group["id"]
        ancestors_or_descendants[gid] = _reachable(gid, depends)

    # Add reverse direction (descendants): if A reaches B, B is connected to A too.
    for gid, reached in list(ancestors_or_descendants.items()):
        for other in reached:
            ancestors_or_descendants.setdefault(other, set()).add(gid)

    n = len(valid_groups)
    for i in range(n):
        for j in range(i + 1, n):
            g1 = valid_groups[i]
            g2 = valid_groups[j]
            id1, id2 = g1["id"], g2["id"]

            connected = id2 in ancestors_or_descendants.get(
                id1, set()
            ) or id1 in ancestors_or_descendants.get(id2, set())
            if connected:
                continue

            surfaces1 = set(g1.get("shared_surfaces") or [])
            surfaces2 = set(g2.get("shared_surfaces") or [])
            overlap = surfaces1 & surfaces2
            if overlap:
                errors.append(
                    f"solapamiento de shared_surfaces entre grupos "
                    f"independientes '{id1}' y '{id2}': {sorted(overlap)}"
                )

    return errors


def validate_dag(data: dict[str, Any]) -> list[str]:
    """Run all validation rules and return the combined list of errors."""
    errors: list[str] = []
    errors.extend(_errors_schema_basics(data))

    groups = data.get("groups")
    if not isinstance(groups, list):
        return errors

    errors.extend(_errors_cycle(groups))
    errors.extend(_errors_blocks_consistency(groups))
    errors.extend(_errors_surface_overlap(groups))

    return errors


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Validar un batch_dag.json contra el esquema autonomous-batch-dag/v1"
    )
    parser.add_argument("dag_path", type=Path, help="Ruta al archivo dag.json")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emitir el resultado en formato JSON (machine-readable)",
    )

    args = parser.parse_args(argv)

    if not args.dag_path.exists():
        message = f"archivo no existe: {args.dag_path}"
        if args.json:
            print(json.dumps({"valid": False, "errors": [message]}))
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    try:
        content = args.dag_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as e:
        message = f"no se pudo leer/parsear el archivo: {e}"
        if args.json:
            print(json.dumps({"valid": False, "errors": [message]}))
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        message = "el contenido raiz debe ser un objeto JSON"
        if args.json:
            print(json.dumps({"valid": False, "errors": [message]}))
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    errors = validate_dag(data)

    if args.json:
        print(json.dumps({"valid": len(errors) == 0, "errors": errors}))
        return 0 if not errors else 1

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(
            f"\nValidacion FALLIDA: {len(errors)} error(es) encontrado(s)",
            file=sys.stderr,
        )
        return 1

    print(f"Validacion EXITOSA: {args.dag_path} es valido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
