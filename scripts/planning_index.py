#!/usr/bin/env python3
"""WOT-2026-090h: indice ON-DEMAND y navegable de `.agent/planning/`.

El planning acumula cientos de .md sin indice verificable. La ficha fija un
STOP explicito: si el indice se vuelve otro artefacto que crece sin cota,
priorizar GENERACION ON-DEMAND sobre fichero persistido -- medido en HEAD
(1074 .md en el destino), un fichero indice persistido seria enorme y caducaria
en cada sesion, asi que este generador NO persiste nada por defecto.

Uso:
    python scripts/planning_index.py --project-root <raiz>          # tabla md
    python scripts/planning_index.py --project-root <raiz> --json   # maquina
    ... --out <fichero>                                             # persiste
        SOLO si el operador lo pide explicitamente (nunca por defecto).

El indice lista TODOS los .md de planning (recursivo) con su TIPO (clasificacion
por prefijo de nombre: AUDIT, STRATEGY, work_plan, builder_prompt, revisor,
PROPUESTA, DISENO, decision, plan_graph, otro) y enlace relativo navegable.

Before: raiz con .agent/planning (si no existe: exit 2, nunca un indice vacuo
    que parezca verdadero). During: walk recursivo read-only + clasificacion
    por prefijo + orden tipo/nombre. After: imprime o escribe el indice; exit 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Clasificacion por prefijo de nombre (orden = prioridad del match).
_TIPO_PATTERNS: tuple[tuple[str, str], ...] = (
    ("AUDIT", "AUDIT"),
    ("STRATEGY", "STRATEGY"),
    ("work_plan", "work_plan"),
    ("builder_prompt", "builder_prompt"),
    ("revisor", "revisor_veredicto"),
    ("PROPUESTA", "propuesta"),
    ("propuesta", "propuesta"),
    ("diseno", "diseno"),
    ("DISENO", "diseno"),
    ("decision", "decision"),
    ("plan_graph", "plan_graph"),
)


def classify(name: str) -> str:
    """Tipo de un artefacto de planning por prefijo de su nombre.

    Before: nombre de fichero .md. During: primer patron que casa (case-
        sensitive en los prefijos que son convencion del repo). After: tipo,
        o "otro".
    """
    for prefix, tipo in _TIPO_PATTERNS:
        if name.startswith(prefix):
            return tipo
    return "otro"


def build_index(planning_dir: Path) -> list[dict[str, str]]:
    """Inventario recursivo de .md de planning, clasificado y ordenado.

    Before: planning_dir existente. During: rglob("*.md") read-only; tipo por
        classify(); ruta relativa al planning para el enlace navegable; dedupe
        estable. After: lista ordenada por (tipo, ruta relativa).
    """
    entries: list[dict[str, str]] = []
    for path in sorted(planning_dir.rglob("*.md")):
        rel = path.relative_to(planning_dir).as_posix()
        entries.append(
            {
                "file": rel,
                "tipo": classify(path.name),
                "dir": rel.rsplit("/", 1)[0] if "/" in rel else ".",
            }
        )
    entries.sort(key=lambda e: (e["tipo"], e["file"]))
    return entries


def render_markdown(planning_dir: Path, entries: list[dict[str, str]]) -> str:
    """Render navegable del indice en markdown.

    Before: planning_dir raiz para las rutas relativas de los enlaces; entries
        de build_index. During: resumen por tipo + tabla con enlaces. After:
        texto markdown; sin escritura.
    """
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["tipo"]] = counts.get(entry["tipo"], 0) + 1
    lines = [
        "# Indice de .agent/planning/ (generado on-demand, WOT-2026-090h)",
        "",
        f"Total: {len(entries)} fichero(s) .md",
        "",
        "| Tipo | Count |",
        "|------|-------|",
    ]
    lines.extend(f"| {tipo} | {counts[tipo]} |" for tipo in sorted(counts))
    lines.extend(["", "| Tipo | Fichero |", "|------|---------|"])
    lines.extend(
        f"| {entry['tipo']} | [{entry['file']}]({entry['file']}) |" for entry in entries
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--out", type=Path, help="Persiste el indice SOLO aqui (opt-in explicito)."
    )
    args = parser.parse_args(argv)

    planning_dir = args.project_root / ".agent" / "planning"
    if not planning_dir.is_dir():
        print(
            f"[planning-index] ERROR: no existe {planning_dir} "
            "(nunca un indice vacuo que parezca verdadero)",
            file=sys.stderr,
        )
        return 2

    entries = build_index(planning_dir)
    # WOT-2026-090h ronda 2 (hallazgo Codex): el formato PERSISTIDO respeta el
    # formato de salida (--json persiste JSON, no una mezcla).
    if args.json:
        content = json.dumps(entries, indent=1, ensure_ascii=True)
        print(content)
    else:
        content = render_markdown(planning_dir, entries)
        print(content, end="")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(content, encoding="utf-8")
        print(
            f"[planning-index] indice persistido en {args.out} "
            f"({len(entries)} ficheros, formato "
            f"{'json' if args.json else 'markdown'}) -- opt-in explicito del operador",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
