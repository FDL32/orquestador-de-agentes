"""Reporter de cobertura de memoria en superficies gobernantes (WOT-2026-058c).

Before:
    El script require acceso de solo lectura al arbol del motor (raiz resuelta
    desde __file__ via pathlib). No necesita ningun argumento obligatorio.

During:
    Recorre tres familias de ficheros markdown (prompts/*.md,
    skills/*/SKILL.md, .claude/rules/*.md) y aplica el predicado de cobertura:
    una superficie esta CUBIERTA si (a) su texto contiene una invocacion
    'memory_context.py --bootstrap' o 'memory_context.py --recall', O (b) su
    texto contiene 'memory_bootstrap' (referencia al shared doc). El token
    '--status' JAMAS suma.

After:
    Imprime en stdout las cifras por familia (PROMPTS, SKILLS, RULES) con
    formato cubiertas/total y la lista de superficies NO cubiertas. Exit 0
    siempre que corra (reporter, no guard); exit 1 solo por error de uso.
"""

from __future__ import annotations

import pathlib
import sys


COVERAGE_PREDICATES = [
    "memory_context.py --bootstrap",
    "memory_context.py --recall",
    "memory_bootstrap",
]


def _is_covered(text: str) -> bool:
    return any(p in text for p in COVERAGE_PREDICATES)


def _scan_family(root: pathlib.Path, glob_pattern: str) -> tuple[int, list[str]]:
    files = sorted(root.glob(glob_pattern))
    total = len(files)
    uncovered = []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            uncovered.append(str(f.relative_to(root)))
            continue
        if not _is_covered(content):
            uncovered.append(str(f.relative_to(root)))
    return total, uncovered


def main(root: pathlib.Path | None = None) -> int:
    """Ejecuta el censo y imprime resultados en stdout.

    Args:
        root: Raiz del arbol del motor. Si es None, se resuelve desde
              __file__ (scripts/../).

    Returns:
        0 siempre (reporter, no guard).
    """
    if root is None:
        root = pathlib.Path(__file__).resolve().parents[1]

    families = [
        ("PROMPTS", "prompts/*.md"),
        ("SKILLS", "skills/*/SKILL.md"),
        ("RULES", ".claude/rules/*.md"),
    ]

    totals: dict[str, int] = {}
    covered_counts: dict[str, int] = {}
    all_uncovered: list[str] = []

    for label, pattern in families:
        total, uncovered = _scan_family(root, pattern)
        totals[label] = total
        covered_counts[label] = total - len(uncovered)
        all_uncovered.extend(uncovered)

    grand_total = sum(totals.values())
    grand_covered = sum(covered_counts.values())

    for label, _pattern in families:
        print(f"{label}: {covered_counts[label]}/{totals[label]}")
    print(f"TOTAL: {grand_covered}/{grand_total}")

    if all_uncovered:
        print("NO_CUBIERTAS:")
        for name in all_uncovered:
            print(name)

    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Reporter de cobertura de memoria en superficies gobernantes."
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=None,
        help="Raiz del arbol del motor. Por defecto, se resuelve desde __file__.",
    )
    args = parser.parse_args()
    sys.exit(main(root=args.root))
