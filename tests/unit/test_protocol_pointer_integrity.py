"""Tests for the motor-canon pointer to the WOT-2026-222a checker.

WOT-2026-222a v4. Corrige el defecto medido en P34 ronda 3 (ds H-09, sonnet
H-03): la version anterior ESCRIBIA sus dos documentos temporales y se
autoafirmaba -- nunca leia el documento real ni implementaba deteccion
alguna. Este modulo lee el documento REAL del motor y define un detector
minimo pero real: el puntero debe citar el checker y sus dos fuentes, y el
documento NO debe copiar el texto normativo literal del rechazo del guard
(duplicacion de norma, X-09).
"""

from __future__ import annotations

from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_CANON_DOC = _MOTOR_ROOT / "docs" / "protocol" / "sistema_agnostico_celdas_y_lentes.md"

# Texto normativo LITERAL del guard (scripts/ensemble_dispatch.py,
# enforce_profile_policy): si este texto aparece en el canon, el documento
# esta DUPLICANDO la norma en vez de apuntar a ella (X-09).
_GUARD_REJECTION_TEXT = "Kilo no aporta contencion verificable"


def pointer_present(doc_text: str) -> bool:
    """True si el documento cita el checker Y sus dos fuentes por nombre."""
    return (
        "check_ensemble_profile_catalog.py" in doc_text
        and "opencode models" in doc_text
        and "kilo models" in doc_text
    )


def duplicate_norm_present(doc_text: str) -> bool:
    """True si el documento copia el texto normativo literal del guard."""
    return _GUARD_REJECTION_TEXT in doc_text


def test_canon_doc_has_the_pointer():
    doc_text = _CANON_DOC.read_text(encoding="utf-8")
    assert pointer_present(doc_text), (
        "docs/protocol/sistema_agnostico_celdas_y_lentes.md no cita "
        "check_ensemble_profile_catalog.py ni sus dos fuentes"
    )


def test_canon_doc_does_not_duplicate_the_guard_norm():
    doc_text = _CANON_DOC.read_text(encoding="utf-8")
    assert not duplicate_norm_present(doc_text), (
        "el documento copia el texto normativo literal del guard en vez de "
        "apuntar a el (X-09)"
    )


def test_detector_rejects_a_document_with_only_a_bare_mention():
    """Control negativo: mencionar el NOMBRE del script sin las dos fuentes
    NO cuenta como puntero -- evita un detector que de verde con media frase."""
    bare = "Este ticket toca scripts/check_ensemble_profile_catalog.py."
    assert not pointer_present(bare)


def test_detector_flags_a_document_that_pastes_the_guard_text():
    """Control positivo del detector de duplicado: un documento que SI pega
    el texto normativo del guard debe disparar el detector."""
    duplicated = (
        "## Norma\nUn perfil se rechaza porque Kilo no aporta contencion "
        "verificable, sin excepciones."
    )
    assert duplicate_norm_present(duplicated)
