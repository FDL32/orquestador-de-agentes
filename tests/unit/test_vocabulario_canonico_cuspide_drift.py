"""E8 guard (WOT-2026-114c): la cuspide de AGENTS.md no diverge del modulo movido.

Before: AGENTS.md tiene una seccion "## Vocabulario canonico" condensada (cuspide) que
    apunta a .agent/rules/common/vocabulario_canonico.md (modulo, cuerpo completo).
During: lee el contenido REAL de la cuspide en AGENTS.md (no una copia hardcodeada),
    descarta el encabezado "##" y la linea final de puntero, y verifica que cada LINEA
    no vacia retenida sigue siendo subcadena del modulo (E8 de
    docs/followups/palanca-a-raiz-agents-md-diseno.md Seccion 6), normalizando saltos
    de linea a espacios (el markdown reenvuelve texto sin cambiar su significado).
After: si alguien edita SOLO la cuspide (o SOLO el modulo) de forma que dejan de
    coincidir, el test falla. Nunca escribe en disco: la mutacion se aplica sobre el
    STRING leido de AGENTS.md, no sobre el fichero -- evita el round-trip LF/CRLF de
    Windows (leccion ya documentada: write_text() sin newline="\n" reescribe LF como
    CRLF y ensucia el arbol) y el riesgo de dejar el working tree sucio si el test
    muere a mitad.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD = REPO_ROOT / "AGENTS.md"
MODULE_MD = REPO_ROOT / ".agent" / "rules" / "common" / "vocabulario_canonico.md"
POINTER_MARKER = (
    "[vocabulario_canonico.md](.agent/rules/common/vocabulario_canonico.md)"
)


def _normalized(text: str) -> str:
    """Collapse markdown line-wrap whitespace to single spaces for substring checks."""
    return re.sub(r"\s+", " ", text).strip()


def _cuspide_body(agents_md_text: str) -> str:
    start = agents_md_text.index("## Vocabulario canonico")
    end = agents_md_text.index("## Contrato de version y portabilidad", start)
    return agents_md_text[start:end]


def _retained_lines(agents_md_text: str) -> list[str]:
    """Non-empty lines of the cuspide that must survive in the module (E8).

    Excludes the heading paragraph and the ENTIRE pointer paragraph (a markdown
    paragraph can wrap across several lines; only its first line contains the
    marker text, so paragraph-level exclusion is required, not per-line matching).
    """
    body = _cuspide_body(agents_md_text)
    paragraphs = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    retained_lines: list[str] = []
    for paragraph in paragraphs:
        if paragraph.strip().startswith("## Vocabulario canonico"):
            continue
        if POINTER_MARKER in paragraph or "Ver vocabulario completo" in paragraph:
            continue
        retained_lines.extend(ln.strip() for ln in paragraph.splitlines() if ln.strip())
    return retained_lines


def test_cuspide_real_lines_are_substrings_of_module() -> None:
    """Lee AGENTS.md DE DISCO (no una copia) y contrasta cada linea contra el modulo real."""
    agents_md_text = AGENTS_MD.read_text(encoding="utf-8")
    module_text = _normalized(MODULE_MD.read_text(encoding="utf-8"))
    retained = _retained_lines(agents_md_text)
    assert retained, (
        "la cuspide no tiene lineas retenidas que verificar (precondicion rota)"
    )
    for line in retained:
        assert _normalized(line) in module_text, (
            f"Linea de la cuspide de AGENTS.md ya no esta en el modulo (deriva E8): {line!r}"
        )


def test_cuspide_pointer_references_the_real_module() -> None:
    body = _cuspide_body(AGENTS_MD.read_text(encoding="utf-8"))
    assert POINTER_MARKER in body
    assert MODULE_MD.is_file()


def test_mutation_of_real_agents_md_text_is_detected() -> None:
    """Mutation-verify: parte del texto REAL de AGENTS.md (no una constante del test).

    El Revisor (Codex) encontro que una version previa de este test validaba una
    constante Python copiada a mano, no el contenido real de AGENTS.md -- un mutador
    sobre el fichero real no la hacia caer. Esta version arranca leyendo el fichero
    real y muta ESE string en memoria (nunca escribe en disco), reproduciendo la
    ruta de verificacion productiva sin el riesgo de un round-trip de escritura.
    """
    real_text = AGENTS_MD.read_text(encoding="utf-8")
    target = "**Nunca usar `repo_motor/.agent/collaboration/` como operativo.**"
    assert target in real_text, (
        "precondicion: la frase debe existir en el fichero real hoy"
    )

    mutated_text = real_text.replace(
        target,
        "**Nunca usar `repo_motor/.agent/collaboration/` como algo distinto.**",
    )
    assert mutated_text != real_text

    module_text = _normalized(MODULE_MD.read_text(encoding="utf-8"))
    retained = _retained_lines(mutated_text)
    offending = [ln for ln in retained if _normalized(ln) not in module_text]
    assert offending, (
        "la mutacion del texto real de AGENTS.md debio romper al menos una linea "
        "contra el modulo; si esto no cae, el guard E8 no mira el contenido real"
    )
