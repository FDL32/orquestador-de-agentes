"""Tests for scripts/check_document_self_contradiction.py.

Que protege
-----------
El caso REAL medido 2026-10-07 (vuelo memoria v3): `arranque_borrador_v1.md`
afirmaba "52 commits POR DELANTE" en una seccion y "51 commits POR DELANTE" en
otra, sobre el MISMO estado git. Lo caza un lector con filesystem real
re-ejecutando `git rev-list --count`; este guard lo caza sin filesystem,
comparando el documento consigo mismo.

Before / During / After
-----------------------
Before: no requiere estado externo; los fixtures son literales en el test.
During: llama a `find_contradictions` sobre textos en memoria. Sin red, sin I/O.
After: exit 0 sii el guard distingue documento consistente de contradictorio,
    y no dispara con las exclusiones declaradas (proyeccion, cita).
"""

from __future__ import annotations

from scripts.check_document_self_contradiction import find_contradictions


def test_real_case_52_vs_51_is_caught() -> None:
    """Reproduce el defecto REAL medido en arranque_borrador_v1.md."""
    text = (
        "## Seccion 1: Estado\n"
        "Este workspace tiene 52 commits por delante del origin.\n\n"
        "## Seccion 3: Verificacion\n"
        "git rev-list --count origin/main..HEAD -> 51 commits por delante.\n"
    )
    found = find_contradictions(text)
    assert len(found) == 1
    assert found[0]["predicate"] == "commits por delante"
    values = {n for n, _, _ in found[0]["values"]}
    assert values == {"52", "51"}


def test_consistent_document_passes() -> None:
    """El mismo numero repetido no es contradiccion."""
    text = (
        "Este workspace tiene 51 commits por delante.\n"
        "Confirmado: 51 commits por delante tras re-medir.\n"
    )
    assert find_contradictions(text) == []


def test_temporal_projection_is_excluded() -> None:
    """'tras el proximo commit seran 52' es TRANSICION, no contradiccion.

    Sin esta exclusion, el guard daria falso positivo en cualquier documento
    que describa legitimamente un cambio de estado futuro.
    """
    text = (
        "Estado actual: 51 commits por delante.\n"
        "Nota: tras el proximo commit seran 52 commits por delante.\n"
    )
    assert find_contradictions(text) == []


def test_historical_qualifier_is_excluded() -> None:
    """'historicamente eran 52' no contradice el estado actual de 51."""
    text = (
        "Estado actual: 51 commits por delante.\n"
        "Historicamente eran 52 commits por delante, antes del rebase.\n"
    )
    assert find_contradictions(text) == []


def test_quoted_attribution_is_excluded() -> None:
    """Una cita atribuida a otra fuente no es afirmacion propia del documento."""
    text = (
        "Estado actual: 51 commits por delante.\n"
        "> El informe anterior decia: 52 commits por delante.\n"
    )
    assert find_contradictions(text) == []


def test_different_predicates_do_not_cross_contaminate() -> None:
    """332 lineas y 834 lineas son predicados DISTINTOS (ficheros distintos).

    No deben compararse entre si solo por compartir la palabra 'lineas'.
    """
    text = (
        "session_hop.md tiene 332 lineas.\n"
        "orchestrator_launch_builder.md tiene 834 lineas.\n"
    )
    # Mismo PREDICADO normalizado ("lineas"), pero referidos a sujetos
    # distintos -- el guard de forma no distingue sujeto, asi que esto es un
    # LIMITE DECLARADO: un censo de falsos positivos de este tipo exigiria
    # atar el numero a su sustantivo propio (nombre de fichero), fuera del
    # alcance de este guard de primera barrera.
    found = find_contradictions(text)
    assert len(found) == 1
    assert found[0]["predicate"] == "lineas"


def test_reports_line_numbers_for_each_occurrence() -> None:
    """El guard debe nombrar donde aparece cada valor, no solo que difieren."""
    text = "linea con 52 commits por delante\nlinea con 51 commits por delante\n"
    found = find_contradictions(text)
    linenos = sorted(lineno for _, lineno, _ in found[0]["values"])
    assert linenos == [1, 2]


def test_step_number_is_not_a_line_count() -> None:
    """FALSO POSITIVO REAL (2026-10-07, arranque_borrador_v1.md): 'Paso 0
    lineas 54-92' capturaba el '0' del numero de Paso como si fuera una
    cantidad de lineas, y contradecia a '4 lineas' en otro punto del mismo
    documento -- ninguno de los dos era un CONTEO real.
    """
    text = (
        "YA incorporada (Paso 0 lineas 54-92 de session_hop.md).\n"
        "4 lineas con applies_to fuera de enum.\n"
    )
    assert find_contradictions(text) == []
