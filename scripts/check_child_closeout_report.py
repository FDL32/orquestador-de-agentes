"""Valida el FORMATO de un informe CIERRE_PARCIAL_<TICKET>.md (WOT-2026-104s).

Contrato fuente (no se redeclara aqui, X-09): `prompts/builder_invocation_contract.md`
Seccion 3.5 (`contract_id: cid-builder-invocation-v1`). Este guard es una verificacion
MECANICA de FORMATO (las 5 secciones CP-1..CP-5 presentes, en orden, no vacias, y el
literal HIJO_TERMINADO seguido de contenido no vacio en CP-3) -- NO verifica el CONTENIDO
semantico (SHAs reales, rc reales, que lo que sigue a HIJO_TERMINADO sea realmente un
`git status --short`): esa verificacion sigue siendo acto del Manager/auditor (el informe
es evidencia DECLARADA, no verificada, CEM).

Markup exigido (definido por este guard a falta de convencion previa -- se declara
en el propio contrato, Seccion 3.5, para que no quede como "esquema sin consumidor"):
cada campo es un encabezado markdown de nivel 2 `## CP-n` (p.ej. `## CP-1`), seguido
de su contenido hasta el siguiente encabezado `## CP-n` o el fin del fichero.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


CP_IDS: tuple[str, ...] = ("CP-1", "CP-2", "CP-3", "CP-4", "CP-5")

_CP_HEADING_RE = re.compile(r"^##\s*(CP-[1-5])\b.*$", re.MULTILINE)

HIJO_TERMINADO_LINE = (
    "HIJO TERMINADO: sin procesos propios en background ni mutaciones sin restaurar"
)


def _split_sections(text: str) -> dict[str, str]:
    """Devuelve {cp_id: contenido_crudo} para cada encabezado `## CP-n` hallado,
    en el orden en que aparecen en el texto. No valida orden ni completitud."""
    matches = list(_CP_HEADING_RE.finditer(text))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        cp_id = match.group(1)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections[cp_id] = text[start:end]
    return sections


def validate_report(text: str) -> list[str]:
    """Devuelve la lista de violaciones del FORMATO (vacia = informe valido).

    No lanza excepciones por contenido faltante: cada violacion es una cadena
    legible, lista para reportarse tal cual en el checklist de 4.bis.
    """
    violations: list[str] = []
    sections = _split_sections(text)

    found_order = [m.group(1) for m in _CP_HEADING_RE.finditer(text)]
    missing = [cp for cp in CP_IDS if cp not in sections]
    if missing:
        violations.append(f"Faltan encabezados `## CP-n`: {', '.join(missing)}")

    present_order = [cp for cp in found_order if cp in CP_IDS]
    if present_order and present_order != [cp for cp in CP_IDS if cp in present_order]:
        violations.append(
            f"Los campos CP-n no estan en el orden exigido CP-1..CP-5: "
            f"orden hallado {present_order}"
        )

    for cp in CP_IDS:
        if cp not in sections:
            continue
        if not sections[cp].strip():
            violations.append(
                f"`{cp}` esta presente pero vacio (sin contenido ni valor literal)"
            )

    if "CP-3" in sections and sections["CP-3"].strip():
        cp3_content = sections["CP-3"]
        if HIJO_TERMINADO_LINE not in cp3_content:
            violations.append(
                f'`CP-3` no contiene la linea literal exigida: "{HIJO_TERMINADO_LINE}"'
            )
        else:
            after_line = cp3_content.split(HIJO_TERMINADO_LINE, 1)[1]
            if not after_line.strip():
                violations.append(
                    "`CP-3` tiene la linea HIJO TERMINADO pero nada a continuacion: "
                    "falta contenido posterior (el contrato exige ahi la salida real "
                    "de `git status --short`, pero este guard solo verifica que algo "
                    "este escrito, no que sea esa salida)"
                )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", required=True, help="Ruta al CIERRE_PARCIAL_<TICKET>.md"
    )
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    if not report_path.is_file():
        print(f"cierre NO VERIFICABLE: informe ausente en {report_path}")
        return 1

    text = report_path.read_text(encoding="utf-8")
    violations = validate_report(text)
    if violations:
        print(f"cierre NO VERIFICABLE: {report_path}")
        for v in violations:
            print(f"  - {v}")
        return 1

    print(f"formato OK: {report_path} (las 5 secciones CP-1..CP-5 completas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
