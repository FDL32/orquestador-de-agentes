#!/usr/bin/env python3
"""Guard: prompts canonicos deben respetar su line_budget declarado en frontmatter (WOT-2026-090d).

Before: recibe una ruta a un fichero markdown cuyo frontmatter YAML (entre las dos
    primeras lineas `---`) declara un campo `line_budget: <N>`. No requiere red,
    backend vivo ni LLM: es una verificacion sintactica pura sobre el fichero.
During: parsea manualmente el frontmatter (busca `line_budget` como `clave: valor`
    entre las dos primeras lineas `---`, sin PyYAML), extrae el presupuesto como
    entero, cuenta las lineas reales del fichero y compara. Si el fichero no
    declara `line_budget`, falla CERRADO (no asume "sin budget = aprobado").
After: retorna un `AuditResult` con el veredicto y detalle. `main()` imprime
    lineas reales / presupuesto / veredicto por fichero y sale con exit 1 si
    alguno esta fuera de presupuesto o sin budget declarado, exit 0 si todos
    cumplen.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


# Universo cerrado: los prompts canonicos que deben cumplir line_budget.
# Misma tupla que check_prompt_parity.py para los dos ficheros principales,
# mas el modo --check-all que los audita relativos a la raiz del repo.
NORMATIVE_PROMPTS = (
    "prompts/orchestrator_launch_builder.md",
    "prompts/manager_review.md",
)


@dataclass
class AuditResult:
    """Resultado de auditar el presupuesto de lineas de un prompt."""

    path: str
    line_budget: int | None
    actual_lines: int
    within_budget: bool
    motivo: str


def _parse_frontmatter_line_budget(text: str) -> int | None:
    """Extrae `line_budget` del frontmatter YAML (entre las dos primeras lineas `---`).

    Before: `text` es el contenido raw del fichero.
    During: busca lineas `---` para delimitar el frontmatter, luego busca el patron
        `line_budget: <entero>` dentro de ese bloque. No usa PyYAML: parsing manual.
    After: entero si se encontro, None si no hay frontmatter ni campo.
    """
    lines = text.split("\n")
    # Frontmatter esta entre las dos primeras lineas `---`
    first_dash = None
    second_dash = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if first_dash is None:
                first_dash = i
            else:
                second_dash = i
                break

    if first_dash is None or second_dash is None:
        return None

    frontmatter = "\n".join(lines[first_dash + 1 : second_dash])
    match = re.search(r"^line_budget:\s*(\d+)$", frontmatter, re.MULTILINE)
    if match:
        return int(match.group(1))
    return None


def audit(path: Path) -> AuditResult:
    """Audita el line_budget de un fichero prompt.

    Before: `path` debe ser una ruta existente a un fichero readable.
    During: parsea el frontmatter para extraer `line_budget`, cuenta las lineas
        reales del fichero, compara ambos valores.
    After: `AuditResult` con veredicto. Si no hay `line_budget` en el frontmatter,
        `within_budget=False` y `motivo="NO_BUDGET_DECLARED"` (fail-closed).
    """
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    # Cuenta lineas reales: todo lo dividido por \n cuenta como lineas.
    # Si el fichero termina en newline, el ultimo elemento es vacio y no cuenta.
    actual_lines = len(lines) - (1 if lines and lines[-1] == "" else 0)

    budget = _parse_frontmatter_line_budget(raw)

    if budget is None:
        return AuditResult(
            path=str(path),
            line_budget=None,
            actual_lines=actual_lines,
            within_budget=False,
            motivo="NO_BUDGET_DECLARED",
        )

    within_budget = actual_lines <= budget
    if within_budget:
        motivo = f"{actual_lines} lineas <= presupuesto {budget}"
    else:
        motivo = f"{actual_lines} lineas > presupuesto {budget} (exceso: {actual_lines - budget})"

    return AuditResult(
        path=str(path),
        line_budget=budget,
        actual_lines=actual_lines,
        within_budget=within_budget,
        motivo=motivo,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: audita line_budget de uno o mas prompts.

    Before: `argv` es la lista de argumentos (sin argv[0]).
    During: resuelve rutas absolutas, invoca `audit()` en cada una, imprime
        el resultado (lineas reales / presupuesto / veredicto).
    After: exit 1 si algun fichero no cumple, exit 0 si todos pasan.
    """
    parser = argparse.ArgumentParser(
        description="Verifica que los prompts canonicos respetan su line_budget."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Rutas a prompts a auditar. Se resuelven como estan o relativas a CWD.",
    )
    parser.add_argument(
        "--check-all",
        action="store_true",
        help="Audita los prompts de NORMATIVE_PROMPTS relativos a la raiz del repo.",
    )
    args = parser.parse_args(argv)

    if args.check_all:
        repo_root = Path(__file__).resolve().parent.parent
        paths = [repo_root / rel for rel in NORMATIVE_PROMPTS]
    elif args.paths:
        paths = [Path(p).resolve() for p in args.paths]
    else:
        parser.print_help()
        return 2

    any_failed = False
    for p in paths:
        result = audit(p)
        status = "OK" if result.within_budget else "FAIL"
        budget_str = (
            str(result.line_budget)
            if result.line_budget is not None
            else "no declarado"
        )
        print(
            f"[line-budget] {result.path} [{status}] "
            f"lineas:{result.actual_lines} budget:{budget_str} - {result.motivo}"
        )
        if not result.within_budget:
            any_failed = True

    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
