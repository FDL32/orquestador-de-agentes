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


# ---------------------------------------------------------------------------
# WOT-2026-035a: la CUARTA invariante (refutacion previa), OPT-IN.
# La norma "censo antes de tocar superficie gobernante" existia como PROSA y
# era NO EJECUTABLE. ROJO MEDIDO 2026-08-27: `grep REFUTACION` -> 0 hits y el
# flag `--requires-refutation` no existia (argparse: unrecognized arguments).
# ---------------------------------------------------------------------------

_TRES_NATALES = (
    "INVENTARIO DE EVIDENCIA: el fichero X sustenta el punto 1.\n"
    "Si algo no se puede comprobar, reporta NO VERIFICABLE en vez de abortar.\n"
    "PRESUPUESTO: no explores mas de 5 ficheros y para.\n"
)
_CON_REFUTACION = _TRES_NATALES + (
    "REFUTACION-PREVIA: censado el arbol; no hay implementacion previa.\n"
)


def _run(tmp_path, text, *argv):
    import sys

    from scripts.check_loop_bundle_protocol import main

    path = tmp_path / "bundle.md"
    path.write_text(text, encoding="utf-8")
    argv_backup = sys.argv
    sys.argv = ["check_loop_bundle_protocol.py", str(path), *argv]
    try:
        return main()
    finally:
        sys.argv = argv_backup


class TestRefutacionPrevia035a:
    def test_flag_off_sin_refutacion_avisa_pero_no_bloquea(self, tmp_path):
        """WARN-only sin el flag: un gate que nace bloqueando se desactiva."""
        assert _run(tmp_path, _TRES_NATALES) == 0

    def test_flag_on_sin_refutacion_bloquea(self, tmp_path):
        assert _run(tmp_path, _TRES_NATALES, "--requires-refutation") == 1

    def test_flag_on_con_refutacion_pasa(self, tmp_path):
        assert _run(tmp_path, _CON_REFUTACION, "--requires-refutation") == 0

    def test_flag_off_con_refutacion_pasa(self, tmp_path):
        assert _run(tmp_path, _CON_REFUTACION) == 0

    def test_la_cuarta_no_entra_en_las_tres_natales(self):
        """Las natales BLOQUEAN siempre; la cuarta NO puede colarse ahi.

        Si `refutacion_previa` entrase en INVARIANTS, todo bundle historico
        pasaria a rojo de golpe -- exactamente lo que el opt-in evita.
        """
        from scripts.check_loop_bundle_protocol import INVARIANTS, check_bundle

        assert "refutacion_previa" not in INVARIANTS
        assert len(INVARIANTS) == 3
        assert check_bundle(_TRES_NATALES) == []

    def test_variante_con_espacio_tambien_cuenta(self):
        """El guard exige la PROPIEDAD declarada, no una plantilla literal."""
        from scripts.check_loop_bundle_protocol import has_refutation_section

        assert has_refutation_section("REFUTACION PREVIA: censado")
        assert has_refutation_section("refutacion-previa: censado")
        assert not has_refutation_section("hablo de refutacion en general")
