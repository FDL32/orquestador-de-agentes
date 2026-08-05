"""Contract tests for the DEDUPE clause of step 8 (own follow-ups) in
`prompts/orchestrator_session_close_full_audit.md` (WOT-2026-047w).

Que protege
-----------
El paso 8 -- el alta de los follow-ups que genera la PROPIA sesion -- tenia gate
de evidencia pero NINGUNA clausula de deduplicacion, mientras su hermano 8.bis
(fusion del `backlog_inbox/`) SI hacia un barrido de tres superficies con lectura
completa. Es decir: la via mas frecuente para fichar hallazgos era exactamente la
que no comprobaba si el hallazgo ya estaba fichado.

Medido 2026-08-03 (lector-FS del bucle L700, nonce 9fd7ad51) y re-verificado el
2026-08-05: un grep de `dedup|duplic|find_similar` sobre la linea del paso 8
devolvia 0 hits; sobre la de 8.bis, >=1.

Por que un test de PROSA y no un guard ejecutable
--------------------------------------------------
NON-GOAL explicito de la ficha: no se construye un guard de duplicado semantico
automatico. El bucle establecio que el dedupe es NORMA asistida por
`find_similar_signals.py` (generador de SENAL, nunca veredicto). Ningun guard del
arbol caza un duplicado semantico: `check_backlog_contract.py` solo detecta ids
EXACTOS, asi que dos ids distintos con el mismo contenido pasan. Lo unico
fijable de forma barata y con dientes es que la NORMA este escrita y remita a un
unico criterio.

Fixture CONCRETO (exigido por el DoD (b), no "equivalente a juicio")
--------------------------------------------------------------------
El test no juzga similitud: ancla nombres literales que deben aparecer en el
prompt -- la ficha existente `memory_upload.md:18-52` (donde se escribio la
leccion del incidente fundacional) y las tres superficies del barrido -- y exige
las TRES marcas de salida EXACTAS del vocabulario cerrado
(`YA CUBIERTO` / `AMPLIAR` / `SIN VECINOS`).

Mutacion que lo pone en ROJO (DoD: "retirar el barrido del paso 8")
-------------------------------------------------------------------
  borrar la clausula DEDUPE del paso 8   -> ROJO en
    test_step8_requires_dedupe_over_three_surfaces
  borrar las marcas de salida exactas    -> ROJO en
    test_step8_declares_exact_dedupe_verdicts
  duplicar el criterio en vez de remitir -> ROJO en
    test_step8_points_to_single_criterion_instead_of_redeclaring

Before / During / After
-----------------------
Before: el prompt existe en `<motor>/prompts/`.
During: se lee en UTF-8 y se aisla el bloque del paso 8 (desde la linea que
    empieza por "8. Con `--session-close`" hasta "8.bis"). Sin red, sin
    subprocess, sin escritura.
After: exit 0 sii el paso 8 declara el dedupe de tres superficies, remite al
    criterio unico de 8.bis y fija las tres marcas de salida. No muta nada.
"""

from pathlib import Path

import pytest


MOTOR_ROOT = Path(__file__).resolve().parents[2]
PROMPT = MOTOR_ROOT / "prompts" / "orchestrator_session_close_full_audit.md"

# Fixture CONCRETO: las tres superficies que el barrido de 8.bis cubre.
THREE_SURFACES = (
    "backlog.md",
    "_archive/backlog_done.md",
    "observations.YYYY-MM.jsonl",
)

# Vocabulario CERRADO de salida del dedupe (DoD (b): salida EXACTA).
EXACT_VERDICTS = ("YA CUBIERTO", "AMPLIAR", "SIN VECINOS")


def _read_prompt() -> str:
    assert PROMPT.is_file(), f"prompt canonico ausente: {PROMPT}"
    return PROMPT.read_text(encoding="utf-8")


def _step8_block(text: str) -> str:
    """Aisla el bloque del paso 8, excluyendo el bloque de 8.bis.

    Ancla al inicio literal del paso 8 y corta en el ENCABEZADO de 8.bis, para
    que un test del paso 8 NUNCA pase por lo que declara su hermano -- que es
    justamente el hueco que este ticket cierra.

    El corte usa el encabezado real de la seccion (`8.bis FUSIoN`) y NO la
    subcadena "8.bis" a secas: el propio paso 8 REMITE a 8.bis por nombre (DoD
    (c)), asi que cortar en la primera aparicion truncaba el bloque en la
    remision y dejaba fuera las clausulas que este test debe leer.
    """
    start = text.find("8. Con `--session-close`")
    assert start != -1, "no se encontro el inicio del paso 8 en el prompt"
    end = text.find("\n8.bis FUSIoN", start)
    assert end != -1, "no se encontro el encabezado de la seccion 8.bis"
    block = text[start:end]
    assert block.strip(), "el bloque del paso 8 quedo vacio"
    return block


def test_step8_requires_dedupe_over_three_surfaces() -> None:
    """El paso 8 exige el barrido, y sobre las TRES superficies nombradas."""
    block = _step8_block(_read_prompt())

    assert "DEDUPE" in block, (
        "el paso 8 no menciona DEDUPE: es el agujero de WOT-2026-047w "
        "(la via mas frecuente de alta era la que no deduplicaba)"
    )

    missing = [s for s in THREE_SURFACES if s not in block]
    assert not missing, (
        f"el dedupe del paso 8 no nombra estas superficies: {missing}. "
        "El barrido debe cubrir las MISMAS tres que 8.bis; medido 2026-07-22, "
        "deduplicar solo contra el archive de memoria dejo pasar un duplicado."
    )


def test_step8_declares_exact_dedupe_verdicts() -> None:
    """Las tres marcas de salida son EXACTAS, no 'equivalentes a juicio'."""
    block = _step8_block(_read_prompt())

    missing = [v for v in EXACT_VERDICTS if v not in block]
    assert not missing, (
        f"faltan marcas de salida exactas del dedupe: {missing}. "
        "Sin vocabulario cerrado, 'he deduplicado' no es verificable: en el "
        "incidente fundacional (2026-07-22) TRES de los cuatro duplicados "
        "declaraban haber buscado duplicados."
    )


def test_step8_points_to_single_criterion_instead_of_redeclaring() -> None:
    """El criterio vive en UN solo sitio (8.bis) y el paso 8 REMITE a el.

    DoD (c). Si el paso 8 redeclarase el criterio, tendriamos dos copias que
    pueden divergir -- el defecto que este repo persigue como
    'skill apunta, prompt gobierna' aplicado dentro del mismo prompt.
    """
    block = _step8_block(_read_prompt())

    assert "8.bis" in block, (
        "el paso 8 no remite a 8.bis: el criterio debe vivir UNA vez y "
        "el paso 8 apuntar a el, no redeclararlo"
    )
    assert "prevalece 8.bis" in block, (
        "falta la regla de precedencia explicita ('prevalece 8.bis'): sin ella, "
        "una divergencia futura entre ambos no tiene arbitro"
    )


def test_step8_records_that_no_guard_catches_semantic_duplicates() -> None:
    """La norma declara su propio limite: ningun guard caza esto.

    NON-GOAL de la ficha. Que quede escrito evita que una sesion futura asuma
    que `check_backlog_contract.py` la cubre -- solo detecta ids EXACTOS.
    """
    block = _step8_block(_read_prompt())
    assert "check_backlog_contract.py" in block and "id EXACTO" in block, (
        "el paso 8 debe declarar que ningun guard caza el duplicado SEMANTICO "
        "(check_backlog_contract solo mira ids exactos); si no, la norma se "
        "confunde con una barrera"
    )


@pytest.mark.parametrize("surface", THREE_SURFACES)
def test_8bis_still_declares_the_same_surfaces(surface: str) -> None:
    """Control: 8.bis conserva el criterio original.

    Si este test cae, el paso 8 no gano dedupe: es 8.bis quien lo PERDIO, y el
    remite del paso 8 apuntaria a un criterio inexistente.
    """
    text = _read_prompt()
    start = text.find("8.bis")
    end = text.find("8.ter", start)
    assert start != -1 and end != -1, "no se pudo aislar el bloque 8.bis"
    assert surface in text[start:end], (
        f"8.bis dejo de nombrar la superficie {surface!r}: el paso 8 remite a "
        "un criterio que ya no declara lo que promete"
    )
