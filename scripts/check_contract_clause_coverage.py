#!/usr/bin/env python
"""Guard: un bucle que solo ve la RUTA de un contrato citado no ve lo que el
artefacto OMITE de el (WOT-2026-042y).

Que protege
-----------
MEDIDO 2026-07-29: un prompt de arranque de vuelo trabajo el contrato de su
ejecutor (`orchestrator_autonomous_ticket_batch.md`, 571 lineas) por grep
dirigido y diff contra una copia stale, sin abrirlo entero. Faltaron tres
secciones normativas enteras (`MANAGER_REVIEW` por ticket y la forma exacta
`1->9->2`, `GROUP_STOP_REPORT`, el cierre bloqueante con
`batch_run_<ts>.json`). Ese mismo prompt paso un bucle de 4 lentes sin que
ninguna lo detectara, porque a las lentes se les paso el prompt y sus
contratos por REFERENCIA (rutas), no por CONTENIDO -- auditaron coherencia
interna del artefacto, nunca pudieron ver lo que el artefacto OMITIA de un
contrato que no estaba EN el bundle. Lo caso el usuario preguntando.

Que hace este guard
--------------------
Dado un artefacto que CITA uno o mas contratos (rutas bajo `prompts/` o
`.agent/rules/`), extrae de cada contrato citado sus identificadores
normativos mediante marcadores ESTRUCTURALES, nunca analisis de prosa (el
muro WOT-2026-025c ya midio 8 intentos fallidos de esa via):

  - identificadores en mayusculas con guion bajo o guion
    (`MANAGER_REVIEW`, `GROUP_STOP_REPORT`, `NON-NEGOTIABLE`);
  - lineas con enfasis fuerte de convencion del repo
    (`**OBLIGATORIO**`, `**NUNCA**`, `**SIEMPRE**`, `**PROHIBIDO**`,
    `**BLOQUEANTE**`, `**NON-NEGOTIABLE**`);
  - un encabezado markdown inmediatamente seguido de una tabla (tablas de
    fases);
  - un campo declarado en negrita dentro de una lista (`- **Nonce:**`).

Y verifica que cada identificador aparezca, LITERALMENTE (sin distinguir
mayusculas/minusculas), en algun lugar del artefacto auditado. No exige que
el artefacto REPRODUZCA el texto del contrato: un artefacto que legitimamente
ENRUTA sin re-declarar ("skill apunta, prompt gobierna", AGENTS.md) pasa
igual, porque NOMBRAR el identificador -- aunque sea en una linea de
remision breve a su fuente -- ya lo deja presente en el texto.

ALCANCE DECLARADO (lo que este guard NO hace)
----------------------------------------------
No analiza si el artefacto CUMPLE la clausula, solo si la NOMBRA. Es una
barrera de FORMA -- detecta omision ESTRUCTURAL, no incumplimiento
semantico. Un artefacto puede nombrar `MANAGER_REVIEW` y seguir sin
implementarlo bien; eso lo audita una lente con lectura real del repo, no
este guard.

Before / During / After
------------------------
Before: recibe la ruta de un artefacto legible en UTF-8 y la raiz del
    proyecto para resolver los contratos citados por ruta relativa.
During: sin red, sin subprocess, sin escritura. Solo lectura y regex.
After: exit 0 si el artefacto no cita ningun contrato, o si cada contrato
    citado tiene sus identificadores cubiertos; exit 1 enumerando, por
    contrato, los identificadores ausentes. No muta nada.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_CONTRACT_PATH_PATTERN = re.compile(
    r"(?:prompts|\.agent/rules(?:/common)?)/[\w\-./]+\.md"
)

_KEYWORD_ANCHOR_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)+\b")

_STRONG_MARKERS = (
    "OBLIGATORIO",
    "NUNCA",
    "SIEMPRE",
    "PROHIBIDO",
    "BLOQUEANTE",
    "NON-NEGOTIABLE",
)
_STRONG_MARKER_PATTERN = re.compile(
    r"\*\*(" + "|".join(re.escape(m) for m in _STRONG_MARKERS) + r")\*\*"
)

_FIELD_PATTERN = re.compile(r"^\s*[-*]\s+\*\*([^*:]+):\*\*", re.MULTILINE)

_HEADING_LINE_PATTERN = re.compile(r"^(#{1,4})\s+(.+)$")


def extract_cited_contracts(text: str, project_root: Path) -> list[Path]:
    """Rutas de contrato citadas LITERALMENTE en `text` que existen bajo `project_root`."""
    contracts: list[Path] = []
    seen: set[str] = set()
    for match in _CONTRACT_PATH_PATTERN.finditer(text):
        candidate = (project_root / match.group(0)).resolve()
        key = str(candidate)
        if key in seen:
            continue
        if candidate.is_file():
            contracts.append(candidate)
            seen.add(key)
    return contracts


def _table_heading_anchors(text: str) -> list[str]:
    """Encabezado mas reciente antes de una tabla markdown real (puede haber prosa entre medias).

    Una tabla real tiene al menos 2 lineas consecutivas que empiezan por
    '|' (fila de cabecera + separador o segunda fila); una sola linea con
    '|' suelta (p.ej. prosa citando un pipe) no cuenta.
    """
    lines = text.splitlines()
    anchors: list[str] = []
    last_heading: str | None = None
    for i, line in enumerate(lines):
        heading_match = _HEADING_LINE_PATTERN.match(line)
        if heading_match:
            last_heading = heading_match.group(2).strip()
            continue
        if line.strip().startswith("|") and last_heading is not None:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt.startswith("|"):
                if last_heading not in anchors:
                    anchors.append(last_heading)
                last_heading = None
    return anchors


def extract_clause_anchors(contract_text: str) -> list[str]:
    """Identificadores normativos ESTRUCTURALES de un contrato (sin analisis de prosa)."""
    anchors: list[str] = []

    for match in _KEYWORD_ANCHOR_PATTERN.finditer(contract_text):
        token = match.group(0)
        if token not in anchors:
            anchors.append(token)

    for match in _STRONG_MARKER_PATTERN.finditer(contract_text):
        token = match.group(1)
        if token not in anchors:
            anchors.append(token)

    for match in _FIELD_PATTERN.finditer(contract_text):
        field = match.group(1).strip()
        if field and field not in anchors:
            anchors.append(field)

    for heading in _table_heading_anchors(contract_text):
        if heading not in anchors:
            anchors.append(heading)

    return anchors


def _anchor_is_present(anchor: str, artifact_text: str) -> bool:
    """True si `anchor` aparece en `artifact_text` con bordes de palabra.

    Revisor independiente (WOT-2026-042y, nan/glm5.3-flash modo 3): un
    substring sin bordes deja que un casi-token (`BUILDER_EXITS`) enmascare la
    ausencia del anchor real (`BUILDER_EXIT`). `\\b` basta porque todo
    separador de los cuatro tipos de anchor (`_`, `-`, espacio, `:`) es un
    caracter no-palabra.
    """
    pattern = re.compile(rf"\b{re.escape(anchor)}\b", re.IGNORECASE)
    return pattern.search(artifact_text) is not None


def check_clause_coverage(artifact_text: str, contract_text: str) -> list[str]:
    """Identificadores del contrato AUSENTES (ni literales ni por remision) del artefacto."""
    return [
        anchor
        for anchor in extract_clause_anchors(contract_text)
        if not _anchor_is_present(anchor, artifact_text)
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Verifica que un artefacto que CITA un contrato cubra sus "
            "identificadores normativos estructurales (WOT-2026-042y)."
        )
    )
    ap.add_argument("--artifact", required=True, help="ruta del artefacto auditado")
    ap.add_argument(
        "--project-root",
        required=True,
        help="raiz del proyecto para resolver rutas de contrato citadas",
    )
    ap.add_argument(
        "--contract",
        action="append",
        default=None,
        help=(
            "ruta de contrato a verificar (repetible). Sin esta flag, se "
            "auto-detectan los contratos citados LITERALMENTE en el artefacto."
        ),
    )
    args = ap.parse_args(argv)

    artifact_path = Path(args.artifact)
    project_root = Path(args.project_root)
    if not artifact_path.is_file():
        print(
            f"[contract-clause-coverage] ERROR: artefacto no encontrado: {artifact_path}",
            file=sys.stderr,
        )
        return 2

    artifact_text = artifact_path.read_text(encoding="utf-8", errors="replace")

    if args.contract:
        contracts = [Path(c) for c in args.contract]
    else:
        contracts = extract_cited_contracts(artifact_text, project_root)

    if not contracts:
        print(
            f"[contract-clause-coverage] OK: {artifact_path.name} no cita ningun "
            "contrato bajo prompts/ o .agent/rules/; nada que verificar."
        )
        return 0

    any_missing = False
    for contract_path in contracts:
        if not contract_path.is_file():
            print(
                f"[contract-clause-coverage] ERROR: contrato citado no existe: {contract_path}",
                file=sys.stderr,
            )
            any_missing = True
            continue
        contract_text = contract_path.read_text(encoding="utf-8", errors="replace")
        anchors = extract_clause_anchors(contract_text)
        if not anchors:
            print(
                f"[contract-clause-coverage] AVISO: {contract_path.name} no tiene "
                "ningun identificador normativo estructural extraible; cobertura "
                "NO verificable por marcadores (no es un OK de cobertura real)."
            )
            continue
        missing = [a for a in anchors if not _anchor_is_present(a, artifact_text)]
        if missing:
            any_missing = True
            print(
                f"[contract-clause-coverage] BLOQUEA: {artifact_path.name} cita "
                f"{contract_path.name} pero omite {len(missing)} identificador(es) "
                "normativo(s):",
                file=sys.stderr,
            )
            for anchor in missing:
                print(f"  - {anchor}", file=sys.stderr)

    if any_missing:
        print(
            "\n  Un bucle que audita coherencia interna sobre un artefacto cuyo\n"
            "  contrato no va EN el bundle no puede ver lo que el artefacto OMITE\n"
            "  (WOT-2026-042y, medido 2026-07-29). Incluye el contrato en el bundle\n"
            "  o nombra explicitamente el identificador y su fuente.",
            file=sys.stderr,
        )
        return 1

    print(
        f"[contract-clause-coverage] OK: {artifact_path.name} cubre los "
        f"identificadores de {len(contracts)} contrato(s) citado(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
