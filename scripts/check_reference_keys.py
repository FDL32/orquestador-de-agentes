#!/usr/bin/env python3
"""Guard: toda clave de referencia `[X#]` resuelve a exactamente un ancla `**X#.**`.

Que protege
-----------
`prompts/doc_optimization.md` mueve narrativa forense fuera de ficheros
siempre-cargados (`AGENTS.md`) a modulos de referencia bajo
`.agent/rules/common/`. Para no repetir una etiqueta generica `<referencia>`
en cada puntero, el motor adopta una clave corta letra+numero (p.ej. `F3`):
la letra selecciona el FICHERO (via `docs/registry/reference_keys.md`), el
numero selecciona el ANCLA dentro de ese fichero (`**F3.** <texto>`).

Precedente evaluado y descartado: `DEC-008B-001` rechazo un `registry.json`
rico mantenido aparte de sus fuentes, porque "un registry incorrecto es peor
que no tener" -- un indice que nadie regenera automaticamente diverge en
silencio. Este esquema es mas delgado (una leyenda de pocas filas +
numeracion INLINE de listas que de todos modos iban a existir), pero hereda
una version pequena del mismo riesgo: una cita puede sobrevivir a una
renumeracion del fichero de referencia sin que nadie la actualice. Este
guard cierra ese riesgo activamente, en vez de confiar en que alguien se
acuerde (CEM: "barrera cableada" sobre "norma").

Formato (literal, sin variantes -- ver prosa de diseno en
`docs/followups/propuesta-optimizacion-cem-v0-y-claves-referencia-20261022.md`
Seccion 6/6.1 para el porque de esta estrictez; el formato de cita paso de `(ver X#)` a
`[X#]` en WOT-2026-114e, a peticion del usuario, para no repetir la palabra "ver" en cada
puntero):

    cita:  [F3]                  regex: \\[([A-Z]\\d+)\\]
    ancla: **F3.** <texto>       regex: ^\\s*\\*\\*([A-Z])(\\d+)\\.\\*\\*  (al inicio de linea)

La leyenda (`docs/registry/reference_keys.md`) declara el fichero de cada letra como un
enlace markdown real `[texto](ruta)` (navegable en GitHub/VS Code); el guard extrae la ruta
del parentesis del enlace, no de backticks sueltos.

Antes de buscar citas o anclas, el guard excluye bloques de codigo fenced
(` ``` ` o `~~~`, longitud >= 3, se empareja por el mismo caracter y una
longitud de cierre >= la de apertura -- parser de fences estandar, no ad
hoc) para que una clave mencionada dentro de un ejemplo de codigo no cuente.

Non-goals declarados (deriva semantica, falso-positivo de negrita usado
como enfasis): un guard mecanico verifica SINTAXIS, nunca SEMANTICA. Ver
Seccion 6.1 del documento de diseno citado arriba.

Before: lee `docs/registry/reference_keys.md` (leyenda) + `AGENTS.md` +
    `.agent/rules/common/*.md` (superficie de citas, primera adopcion).
During: censa citas y anclas tras excluir bloques fenced; resuelve cada
    cita contra la leyenda y el fichero mapeado.
After: exit 0 si toda cita resuelve a exactamente un ancla y toda letra de
    la leyenda apunta a un fichero existente. exit 1, nombrando cada
    violacion, en cualquier otro caso. No muta nada.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGEND_PATH = PROJECT_ROOT / "docs" / "registry" / "reference_keys.md"

_LEGEND_ROW_RE = re.compile(r"^\|\s*([A-Z])\s*\|\s*\[[^\]]*\]\(([^)]+)\)\s*\|\s*$")
_CITATION_RE = re.compile(r"\[([A-Z]\d+)\]")
_ANCHOR_RE = re.compile(r"^\s*\*\*([A-Z]\d+)\.\*\*")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


def strip_fenced_code(text: str) -> str:
    """Return *text* with fenced code blocks (``` or ~~~) blanked line-by-line.

    Before: raw markdown text, possibly containing fenced code blocks.
    During: walks lines; a fence-opening line toggles "inside fence" using
        the matched delimiter char and length; a closing fence must use the
        SAME char and a length >= the opening length (standard Markdown
        fence semantics).
    After: returns text with the SAME number of lines (fenced lines become
        empty), so line numbers reported by callers stay accurate.
    """
    out_lines: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in text.splitlines():
        m = _FENCE_RE.match(line.strip())
        if fence_char is None:
            if m:
                token = m.group(1)
                fence_char = token[0]
                fence_len = len(token)
                out_lines.append("")
            else:
                out_lines.append(line)
        else:
            out_lines.append("")
            if m:
                token = m.group(1)
                if token[0] == fence_char and len(token) >= fence_len:
                    fence_char = None
                    fence_len = 0
    return "\n".join(out_lines)


def parse_legend(legend_path: Path, project_root: Path) -> dict[str, Path]:
    r"""Parse the letter -> file table of *legend_path*.

    Before: a markdown file with a `| letra | fichero |` table, rows of the
        form `| X | [texto](ruta/relativa/al/propio/legend.md) |` -- un
        enlace markdown real, navegable, no un backtick suelto.
    During: matches each row with `_LEGEND_ROW_RE`; resolves the link target
        relative to *legend_path's own directory* (estandar markdown: un
        enlace relativo se resuelve contra el fichero que lo contiene, NO
        contra *project_root* -- aunque en la practica ambos coinciden
        cuando la leyenda vive bajo `docs/registry/` y el enlace usa `../..`).
    After: dict mapping each letter to its resolved absolute Path. Raises
        no exception on a missing target file -- callers check existence
        explicitly so every violation is reported, not just the first.
    """
    legend: dict[str, Path] = {}
    if not legend_path.exists():
        return legend
    for line in legend_path.read_text(encoding="utf-8").splitlines():
        m = _LEGEND_ROW_RE.match(line.strip())
        if m:
            letter, rel_link = m.group(1), m.group(2)
            legend[letter] = (legend_path.parent / rel_link).resolve()
    return legend


def find_citations(text: str) -> list[tuple[str, int]]:
    """Return (key, 1-indexed line number) for every `[X#]` citation.

    Before: raw text (caller is responsible for stripping fenced code
        first, via `strip_fenced_code`).
    During: scans line by line with `_CITATION_RE`.
    After: one entry per citation found, in source order.
    """
    results: list[tuple[str, int]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        results.extend((m.group(1), lineno) for m in _CITATION_RE.finditer(line))
    return results


def find_anchors(text: str) -> dict[str, list[int]]:
    """Return key -> list of 1-indexed line numbers for every `**X#.**` anchor.

    Before: raw text of a reference file (caller strips fenced code first).
    During: scans line by line with `_ANCHOR_RE`, anchored to line start.
    After: a key with more than one line number is a DUPLICATE anchor.
    """
    results: dict[str, list[int]] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _ANCHOR_RE.match(line)
        if m:
            results.setdefault(m.group(1), []).append(lineno)
    return results


def discover_citation_files(project_root: Path) -> list[Path]:
    """Return the files scanned for citations (first adoption scope).

    Before: nothing. During: resolves `AGENTS.md` (if present) plus every
    `.agent/rules/common/*.md`. After: sorted list for determinism.
    """
    files: list[Path] = []
    agents_md = project_root / "AGENTS.md"
    if agents_md.exists():
        files.append(agents_md)
    rules_dir = project_root / ".agent" / "rules" / "common"
    if rules_dir.exists():
        files.extend(sorted(rules_dir.glob("*.md")))
    return files


def _check_legend_targets_exist(legend: dict[str, Path]) -> list[str]:
    return [
        f"leyenda: la letra '{letter}' apunta a '{path}', que no existe"
        for letter, path in legend.items()
        if not path.exists()
    ]


def _check_citations_resolve(
    project_root: Path, legend_path: Path, legend: dict[str, Path]
) -> list[str]:
    violations: list[str] = []
    anchor_cache: dict[str, dict[str, list[int]]] = {}

    def anchors_for(letter: str) -> dict[str, list[int]]:
        if letter not in anchor_cache:
            path = legend.get(letter)
            if path is None or not path.exists():
                anchor_cache[letter] = {}
            else:
                stripped = strip_fenced_code(path.read_text(encoding="utf-8"))
                anchor_cache[letter] = find_anchors(stripped)
        return anchor_cache[letter]

    for citation_file in discover_citation_files(project_root):
        rel = citation_file.relative_to(project_root)
        stripped = strip_fenced_code(citation_file.read_text(encoding="utf-8"))
        for key, lineno in find_citations(stripped):
            letter = key[0]
            if letter not in legend:
                violations.append(
                    f"{rel}:{lineno}: cita '[{key}]' usa la letra '{letter}', "
                    f"ausente de la leyenda ({legend_path.relative_to(project_root)})"
                )
                continue
            if not anchors_for(letter).get(key):
                violations.append(
                    f"{rel}:{lineno}: cita '[{key}]' no tiene ningun ancla "
                    f"'**{key}.**' en {legend[letter].relative_to(project_root)}"
                )
    return violations


def _check_no_duplicate_anchors(
    project_root: Path, legend: dict[str, Path]
) -> list[str]:
    violations: list[str] = []
    for path in legend.values():
        if not path.exists():
            continue
        stripped = strip_fenced_code(path.read_text(encoding="utf-8"))
        for key, linenos in find_anchors(stripped).items():
            if len(linenos) > 1:
                violations.append(
                    f"{path.relative_to(project_root)}: ancla '**{key}.**' duplicada "
                    f"en lineas {linenos}"
                )
    return violations


def check(project_root: Path, legend_path: Path) -> list[str]:
    """Run the full check. Returns a list of violation messages (empty = OK)."""
    legend = parse_legend(legend_path, project_root)
    return (
        _check_legend_targets_exist(legend)
        + _check_citations_resolve(project_root, legend_path, legend)
        + _check_no_duplicate_anchors(project_root, legend)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valida que toda cita '[X#]' resuelva a exactamente un ancla."
    )
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--legend", default=str(LEGEND_PATH))
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    legend_path = Path(args.legend).resolve()

    violations = check(project_root, legend_path)
    if violations:
        print("[check-reference-keys] FAIL:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("[check-reference-keys] OK: todas las claves de referencia resuelven.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
