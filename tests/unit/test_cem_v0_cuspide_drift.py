"""E8 guard (WOT-2026-114d): la cuspide de CEM v0 en AGENTS.md no diverge del modulo movido.

Before: AGENTS.md tiene una seccion "## CEM v0 - Contrato, Evidencia y Memoria" con una
    mezcla de bullets Grupo A (principios cortos de una linea, se quedan integros) y
    Grupo B (casos forenses truncados a su frase-refutacion-nucleo + puntero inline
    `[F<n>]` (formato migrado desde `(ver F<n>)` en WOT-2026-114e), cuyo caso COMPLETO
    vive en .agent/rules/common/cem_v0_evidencia_forense.md).
During: lee el contenido REAL de la cuspide en AGENTS.md (no una copia hardcodeada). Para
    cada bullet Grupo B (identificado por el puntero `[F<n>]` al final de la linea),
    quita el puntero y verifica que el texto RESTANTE sigue siendo subcadena del modulo
    (E8 de docs/followups/palanca-a-raiz-agents-md-diseno.md Seccion 6, extendido a
    cortes de PREFIJO puro en vez de parrafo-completo-movido). Los bullets Grupo A (sin
    puntero) se excluyen deliberadamente: nunca se movieron, así que no tienen con qué
    compararse en el modulo.
After: si alguien edita SOLO la cuspide (o SOLO el modulo) de forma que el prefijo deja
    de coincidir, el test falla. Nunca escribe en disco: la mutacion se aplica sobre el
    STRING leido de AGENTS.md, no sobre el fichero.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD = REPO_ROOT / "AGENTS.md"
MODULE_MD = REPO_ROOT / ".agent" / "rules" / "common" / "cem_v0_evidencia_forense.md"
POINTER_RE = re.compile(r"\s*\[(F\d+)\]\s*$")


def _normalized(text: str) -> str:
    """Collapse markdown line-wrap whitespace to single spaces for substring checks."""
    return re.sub(r"\s+", " ", text).strip()


def _cuspide_body(agents_md_text: str) -> str:
    start = agents_md_text.index("## CEM v0 - Contrato, Evidencia y Memoria")
    end = agents_md_text.index("## Hacer ahora vs aplazar", start)
    return agents_md_text[start:end]


def _group_b_lines(agents_md_text: str) -> list[tuple[str, str]]:
    """Return (ticket_key, prefix_text_without_pointer) for every Grupo B bullet line.

    Strips the leading markdown list marker ("- ") too: it is structural syntax of
    the cuspide's bullet-list rendering, not part of the forensic text itself -- the
    module uses a numbered-anchor marker ("**F1.**") instead of a list marker for the
    exact same reason the heading/pointer paragraphs were excluded in the
    vocabulario_canonico precedent.
    """
    body = _cuspide_body(agents_md_text)
    pairs: list[tuple[str, str]] = []
    for line in body.splitlines():
        m = POINTER_RE.search(line)
        if m:
            key = m.group(1)
            prefix = POINTER_RE.sub("", line).strip()
            prefix = re.sub(r"^-\s+", "", prefix)
            pairs.append((key, prefix))
    return pairs


def test_cuspide_has_group_b_lines_to_verify() -> None:
    agents_md_text = AGENTS_MD.read_text(encoding="utf-8")
    pairs = _group_b_lines(agents_md_text)
    assert pairs, (
        "la cuspide no tiene bullets Grupo B con puntero '[F<n>]' (precondicion rota)"
    )
    assert {k for k, _ in pairs} == {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}


def test_cuspide_group_b_prefixes_are_substrings_of_module() -> None:
    """Lee AGENTS.md DE DISCO (no una copia) y contrasta cada prefijo contra el modulo real."""
    agents_md_text = AGENTS_MD.read_text(encoding="utf-8")
    module_text = _normalized(MODULE_MD.read_text(encoding="utf-8"))
    for key, prefix in _group_b_lines(agents_md_text):
        assert _normalized(prefix) in module_text, (
            f"Prefijo de la cuspide de AGENTS.md para {key} ya no esta en el modulo "
            f"(deriva E8): {prefix!r}"
        )


def test_cuspide_pointer_references_the_real_module() -> None:
    body = _cuspide_body(AGENTS_MD.read_text(encoding="utf-8"))
    assert "cem_v0_evidencia_forense.md" in body
    assert MODULE_MD.is_file()


def test_mutation_of_real_agents_md_text_is_detected() -> None:
    """Mutation-verify: parte del texto REAL de AGENTS.md (no una constante del test).

    Replica el patron de test_vocabulario_canonico_cuspide_drift.py: muta el string en
    memoria leido del fichero real, nunca escribe en disco.
    """
    real_text = AGENTS_MD.read_text(encoding="utf-8")
    target = "El exit code tras una tuberia MIENTE"
    assert target in real_text, (
        "precondicion: la frase debe existir en el fichero real hoy"
    )

    mutated_text = real_text.replace(
        target,
        "El exit code tras una tuberia DICE LA VERDAD SIEMPRE",
    )
    assert mutated_text != real_text

    module_text = _normalized(MODULE_MD.read_text(encoding="utf-8"))
    pairs = _group_b_lines(mutated_text)
    offending = [
        (key, prefix) for key, prefix in pairs if _normalized(prefix) not in module_text
    ]
    assert offending, (
        "la mutacion del texto real de AGENTS.md debio romper al menos un prefijo Grupo B "
        "contra el modulo; si esto no cae, el guard E8 no mira el contenido real"
    )
