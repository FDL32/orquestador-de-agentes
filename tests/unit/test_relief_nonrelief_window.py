"""Verify that the relief no-go window stays aligned with canon P23.

Before: the relief prompt and the flight pillars must describe the same
        declarative conditions.
During: extract and normalize both sources, then compare their condition keys.
After: a prompt/canon drift raises an assertion naming the missing or extra
       condition.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "prompts" / "t3_role_session_relief.md"
CANON_PATH = ROOT / ".agent" / "rules" / "common" / "vuelo_pilares.md"
CONDITION_KEYS = (
    ("builder", "vivo"),
    ("contract_audit", "abierto"),
    ("listo", "integrar"),
    ("nonce", "lente"),
)


def extraer_ventana(texto: str) -> str:
    """Extract the no-relief subsection from the complete relief prompt.

    Before: ``texto`` contains the markdown prompt.
    During: collect lines after the target heading up to the next level-three
            heading.
    After: return the subsection body, or raise a clear assertion if absent.
    """
    lines = texto.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith("### Ventana de no-relevo")
        ),
        None,
    )
    if start is None:
        raise AssertionError("No se encontró la subsección 'Ventana de no-relevo'")

    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("### ")
        ),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end])


def normalizar(texto: str) -> str:
    """Normalize accents, line breaks, spacing, and case for phrase checks.

    Before: ``texto`` may contain accented characters and wrapped phrases.
    During: apply NFKD, remove combining marks, and collapse whitespace.
    After: return a lowercase single-space representation.
    """
    decomposed = unicodedata.normalize("NFKD", texto)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(without_marks.lower().split())


def condiciones_del_prompt(ventana: str) -> list[str]:
    """Return one entry for each bold markdown condition bullet.

    Before: ``ventana`` is the extracted no-relief subsection.
    During: select lines whose markdown bullet begins with ``- **``.
    After: return the condition bullet text in source order.
    """
    return [
        line[2:].strip() for line in ventana.splitlines() if line.startswith("- **")
    ]


def terminos_p23(canon_texto: str) -> list[str]:
    """Extract the four no-relief terms from the P23 rule cell.

    Before: ``canon_texto`` contains the flight pillars markdown table.
    During: locate P23, isolate text after ``solo se releva``, and split each
            declarative ``sin`` condition.
    After: return the condition terms without their leading ``sin``.
    """
    row = next(
        (line for line in canon_texto.splitlines() if line.startswith("| P23 |")),
        None,
    )
    if row is None:
        raise AssertionError("No se encontró la fila P23 del canon")

    cells = row.split("|")
    if len(cells) < 3:
        raise AssertionError("La fila P23 no contiene la segunda celda esperada")
    marker = "solo se releva "
    rule = cells[2].strip()
    if marker not in normalizar(rule):
        raise AssertionError("P23 no contiene la frase 'solo se releva'")
    start = rule.lower().index(marker)
    remainder = rule[start + len(marker) :]
    terms = re.split(r",\s*sin\s+|\s+y\s+sin\s+", remainder)
    return [re.sub(r"^sin\s+", "", term.strip(), flags=re.IGNORECASE) for term in terms]


def _matching_keys(text: str) -> list[tuple[str, str]]:
    """Return condition keys whose tokens all occur in normalized ``text``.

    Before: ``text`` is one bullet or one P23 term.
    During: compare every canonical token pair against normalized text.
    After: return all matching keys for one-to-one validation.
    """
    normalized = normalizar(text)
    return [key for key in CONDITION_KEYS if all(token in normalized for token in key)]


def _assert_condition_mapping(items: list[str], source: str) -> None:
    """Assert exact four-item, one-key-per-item coverage for a source.

    Before: ``items`` contains prompt bullets or P23 terms.
    During: map each item to exactly one canonical condition key.
    After: raise ``AssertionError`` for a missing, ambiguous, extra, or absent
           condition; otherwise return normally.
    """
    if len(items) != len(CONDITION_KEYS):
        raise AssertionError(
            f"{source} debe tener exactamente 4 condiciones; tiene {len(items)}"
        )

    matched = []
    for item in items:
        keys = _matching_keys(item)
        if len(keys) != 1:
            raise AssertionError(
                f"{source} no mapea exactamente una condición: {item!r}; coincidencias={keys}"
            )
        matched.append(keys[0])

    for key in CONDITION_KEYS:
        if matched.count(key) != 1:
            raise AssertionError(
                f"{source} no cubre exactamente la condición {key!r}; coincidencias={matched}"
            )


def _prompt_and_canon() -> tuple[str, list[str], list[str]]:
    """Load the live prompt and canon and derive their condition lists.

    Before: the repository contains the two authoritative markdown sources.
    During: read UTF-8 text and run the extraction helpers.
    After: return the window, prompt bullets, and P23 terms.
    """
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    canon = CANON_PATH.read_text(encoding="utf-8")
    window = extraer_ventana(prompt)
    return window, condiciones_del_prompt(window), terminos_p23(canon)


def test_ventana_lista_cuatro_condiciones() -> None:
    """m-01: the prompt window must list all four canonical conditions.

    Before: load the current relief prompt subsection.
    During: validate its exact bullet count and condition-key coverage.
    After: the four expected conditions are represented exactly once.
    """
    window, bullets, _ = _prompt_and_canon()
    _assert_condition_mapping(bullets, "La ventana del prompt")
    normalized = normalizar(window)
    for key in CONDITION_KEYS:
        assert all(token in normalized for token in key), (
            f"La ventana no contiene la condición {key!r}"
        )


def test_prompt_sin_tres_condiciones() -> None:
    """m-02: the prompt must not preserve the obsolete three-condition phrase.

    Before: extract and normalize the live no-relief subsection.
    During: check the wrapped phrase in its whitespace-insensitive form.
    After: the obsolete phrase is absent.
    """
    window, _, _ = _prompt_and_canon()
    assert "tres condiciones" not in normalizar(window), (
        "La ventana conserva la frase prohibida 'tres condiciones'"
    )


def test_condiciones_coinciden_con_p23() -> None:
    """m-03: prompt bullets and P23 terms must have identical condition keys.

    Before: derive both condition lists from their live sources.
    During: validate each side and verify every key is covered by both sides.
    After: the prompt and canon express the same four-condition contract.
    """
    window, bullets, terms = _prompt_and_canon()
    _assert_condition_mapping(terms, "La fila P23")
    _assert_condition_mapping(bullets, "La ventana del prompt")
    for key in CONDITION_KEYS:
        assert any(all(token in normalizar(term) for token in key) for term in terms), (
            f"P23 no cubre la condición {key!r}"
        )
        assert any(
            all(token in normalizar(bullet) for token in key) for bullet in bullets
        ), f"El prompt no cubre la condición {key!r}"
    assert "tres condiciones" not in normalizar(window), (
        "La ventana conserva la frase prohibida 'tres condiciones'"
    )


def test_fixture_ventana_sin_condicion_nonce_falla() -> None:
    """m-01 control: a three-condition fixture must fail the mapping.

    Before: construct the historical prompt window without nonce/lens.
    During: validate its condition bullets with the production assertion helper.
    After: an ``AssertionError`` identifies the missing fourth condition.
    """
    fixture = """\n- **Builder vivo:** sí.\n- **CONTRACT_AUDIT abierto:** sí.\n- **Aviso de listo para integrar sin merge:** sí.\n"""
    with pytest.raises(AssertionError, match="exactamente 4 condiciones"):
        _assert_condition_mapping(condiciones_del_prompt(fixture), "Fixture de ventana")


def test_fixture_texto_tres_condiciones_falla() -> None:
    """m-02 control: a fixture containing the obsolete phrase must fail.

    Before: construct a normalized subsection containing ``tres condiciones``.
    During: apply the same forbidden-phrase assertion as the live check.
    After: an ``AssertionError`` identifies the obsolete wording.
    """
    fixture = "La ventana enumera estas tres\ncondiciones."
    with pytest.raises(AssertionError, match="tres condiciones"):
        assert "tres condiciones" not in normalizar(fixture), (
            "La ventana conserva la frase prohibida 'tres condiciones'"
        )


def test_fixture_p23_quinta_condicion_falla() -> None:
    """m-03 control: a P23 fixture with five conditions must fail.

    Before: construct a synthetic P23 row with an extra fifth condition.
    During: extract its terms and validate the exact canonical count.
    After: an ``AssertionError`` identifies the extra condition.
    """
    fixture = (
        "| P23 | Ventana: solo se releva sin Builder vivo, sin CONTRACT_AUDIT abierto, "
        "sin LISTO_PARA_INTEGRAR sin fusionar y sin nonce ni lente de revision en vuelo, "
        "sin condicion quinta | RATIFICADA |\n"
    )
    with pytest.raises(AssertionError, match="exactamente 4 condiciones"):
        _assert_condition_mapping(terminos_p23(fixture), "Fixture de P23")
