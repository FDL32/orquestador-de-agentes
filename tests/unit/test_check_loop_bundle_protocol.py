"""Tests for scripts/check_loop_bundle_protocol.py.

Que protege
-----------
El protocolo de suficiencia de un bundle de bucle. Su valor NO es teorico: se
derivo por CONTRASTE medido el 2026-08-05 con la misma lente (`BA06`,
opencode/glm), el mismo cwd y ficheros del mismo repo:

    bundle SIN protocolo  ->    106 bytes, sin veredicto (aborto silencioso)
    bundle CON protocolo  ->  4.708 bytes, informe completo

Los fixtures de abajo son ESOS DOS CASOS, no ejemplos inventados.

Before / During / After
-----------------------
Before: no requiere estado externo; los fixtures son literales en el test.
During: llama a `check_bundle` sobre textos en memoria. Sin red, sin I/O.
After: exit 0 sii el guard distingue bundle conforme de no conforme y nombra
    exactamente los invariantes ausentes.
"""

from __future__ import annotations

from scripts.check_loop_bundle_protocol import INVARIANTS, check_bundle


# Reproduce la FORMA del bundle que dejo muda a la lente (106 bytes de vuelta).
BUNDLE_SIN_PROTOCOLO = """# BUNDLE DE GOBIERNO
Eres una LENTE ADVERSARIAL. Audita el informe de abajo.
Todo lo que necesitas esta DENTRO de tu cwd.

## TU TAREA
1. Verifica que el hallazgo M-4 es un falso positivo.
2. Emite VEREDICTO.
"""

# Reproduce la FORMA del bundle que produjo el informe completo (4708 bytes).
BUNDLE_CON_PROTOCOLO = """# BUNDLE DE GOBIERNO

## INVENTARIO DE EVIDENCIA (leelo antes de nada)
Cada afirmacion se sustenta en un fichero, todos bajo tu cwd:
  - scripts/validate_contract_formation.py
  - tests/unit/test_validate_contract_formation.py

**SALIDA DECLARADA:** si necesitas un fichero que no puedas leer, NO abortes:
escribe `NO VERIFICABLE desde el cwd: <fichero>` y sigue. No explores mas de
~6 ficheros: si necesitas mas, dilo y para.

## TU TAREA
1. Audita el fix.
"""


def test_conforming_bundle_passes() -> None:
    """El bundle que SI funciono no reporta ausencias."""
    assert check_bundle(BUNDLE_CON_PROTOCOLO) == []


def test_bundle_without_protocol_reports_all_three() -> None:
    """El bundle que dejo muda a la lente falla los tres invariantes."""
    missing = check_bundle(BUNDLE_SIN_PROTOCOLO)
    assert set(missing) == set(INVARIANTS), (
        f"deberia nombrar los 3 invariantes ausentes, nombro {missing}"
    )


def test_missing_only_the_exit_clause_is_isolated() -> None:
    """Aislamiento: falta SOLO la salida declarada -> se nombra SOLO esa.

    Sin este caso, el guard podria estar respondiendo a cualquier bundle largo
    en vez de a cada invariante por separado.
    """
    text = (
        "## INVENTARIO DE EVIDENCIA\n- scripts/x.py\n"
        "No explores mas de 6 ficheros: si necesitas mas, dilo y para.\n"
    )
    assert check_bundle(text) == ["salida_declarada"]


def test_missing_only_the_budget_is_isolated() -> None:
    """Aislamiento: falta SOLO el presupuesto de exploracion."""
    text = (
        "## INVENTARIO DE EVIDENCIA\n- scripts/x.py\n"
        "Si no puedes leerlo, reporta NO VERIFICABLE y sigue.\n"
    )
    assert check_bundle(text) == ["presupuesto_exploracion"]


def test_guard_accepts_wording_variants_not_a_literal_template() -> None:
    """El guard exige la PROPIEDAD, no una plantilla literal.

    Si solo aceptara una redaccion exacta, el protocolo degeneraria en cargo
    cult: se copiarian las palabras magicas sin el contenido.
    """
    text = (
        "## INVENTARIO DE LA EVIDENCIA\n- a.py\n"
        "Reporta NO VERIFICABLE si no lo alcanzas.\n"
        "PRESUPUESTO: maximo 4 ficheros.\n"
    )
    assert check_bundle(text) == []
