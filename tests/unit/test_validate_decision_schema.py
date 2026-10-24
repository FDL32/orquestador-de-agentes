"""Tests for scripts/validate_decision_schema.py (WOT-2026-050b).

DoD binario de la ficha:
(a) el esquema de decision_*.json exige un campo que enlace la review.
(b) sin el campo -> FALLA; con el -> pasa.
(c) ROJO EN VIVO: la forma actual {ticket_id, decision, blockers} debe
    fallar con el fix (hoy validaria sin el).
(d) fixture anti-falso-positivo: una decision legitima CON su enlace
    sigue validando.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_decision_schema import (
    REQUIRED_EVIDENCE_FIELD,
    main,
    validate_decision_file,
    validate_paths,
)


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_legacy_shape_fails_dod_c(tmp_path: Path) -> None:
    """DoD(c), ROJO EN VIVO: la forma historica {ticket_id, decision,
    blockers}, identica a los decision_*.json reales hoy en el destino
    (ej. decision_WOT-2026-068z.json), no lleva evidencia de review y debe
    fallar.
    """
    path = _write(
        tmp_path,
        "decision_WOT-2026-068z.json",
        {"ticket_id": "WOT-2026-068z", "decision": "APROBADO", "blockers": []},
    )
    errors = validate_decision_file(path)
    assert errors, "la forma historica sin evidencia debe fallar (DoD-c)"
    assert REQUIRED_EVIDENCE_FIELD in errors[0]


def test_with_evidence_ref_passes_dod_d(tmp_path: Path) -> None:
    """DoD(d), fixture anti-falso-positivo: una decision legitima CON su
    enlace de evidencia sigue validando.
    """
    path = _write(
        tmp_path,
        "decision_WOT-2026-999z.json",
        {
            "ticket_id": "WOT-2026-999z",
            "decision": "APROBADO",
            "blockers": [],
            "review_evidence_ref": ".agent/runtime/reviews/transcript_999z.md",
        },
    )
    errors = validate_decision_file(path)
    assert errors == [], f"una decision con evidencia enlazada debe validar: {errors}"


def test_empty_string_evidence_ref_fails() -> None:
    """Un campo presente pero vacio NO cuenta como enlazado (anti-trivializacion)."""
    payload = {
        "ticket_id": "WOT-2026-999y",
        "decision": "APROBADO",
        "blockers": [],
        "review_evidence_ref": "   ",
    }
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decision_WOT-2026-999y.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        errors = validate_decision_file(path)
    assert errors, "un review_evidence_ref vacio no debe contar como enlazado"


def test_non_string_evidence_ref_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "decision_WOT-2026-999x.json",
        {
            "ticket_id": "WOT-2026-999x",
            "decision": "APROBADO",
            "blockers": [],
            "review_evidence_ref": 12345,
        },
    )
    errors = validate_decision_file(path)
    assert errors, "un review_evidence_ref no-string no debe contar como enlazado"


def test_malformed_json_degrades_to_error_not_exception(tmp_path: Path) -> None:
    path = tmp_path / "decision_WOT-2026-999w.json"
    path.write_text("{not valid json", encoding="utf-8")
    errors = validate_decision_file(path)
    assert errors
    assert "JSON invalido" in errors[0]


def test_unreadable_file_degrades_to_error_not_exception(tmp_path: Path) -> None:
    path = tmp_path / "decision_WOT-2026-999v.json"
    # Never created -- read_text raises OSError (FileNotFoundError).
    errors = validate_decision_file(path)
    assert errors
    assert "no se pudo leer" in errors[0]


def test_validate_paths_aggregates_across_multiple_files(tmp_path: Path) -> None:
    good = _write(
        tmp_path,
        "decision_WOT-2026-999u.json",
        {
            "ticket_id": "WOT-2026-999u",
            "decision": "APROBADO",
            "blockers": [],
            "review_evidence_ref": "sha:abc123",
        },
    )
    bad = _write(
        tmp_path,
        "decision_WOT-2026-999t.json",
        {"ticket_id": "WOT-2026-999t", "decision": "APROBADO", "blockers": []},
    )
    errors = validate_paths([good, bad])
    assert len(errors) == 1
    assert "999t" in errors[0]


def test_main_exit_code_1_on_legacy_shape(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "decision_WOT-2026-999s.json",
        {"ticket_id": "WOT-2026-999s", "decision": "APROBADO", "blockers": []},
    )
    assert main([str(path)]) == 1


def test_main_exit_code_0_with_evidence_ref(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "decision_WOT-2026-999r.json",
        {
            "ticket_id": "WOT-2026-999r",
            "decision": "APROBADO",
            "blockers": [],
            "review_evidence_ref": "sha:def456",
        },
    )
    assert main([str(path)]) == 0


def test_main_reviews_dir_discovers_decision_files(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "decision_WOT-2026-999q.json",
        {"ticket_id": "WOT-2026-999q", "decision": "APROBADO", "blockers": []},
    )
    _write(tmp_path, "not_a_decision.json", {"foo": "bar"})
    assert main(["--reviews-dir", str(tmp_path)]) == 1


def test_main_no_targets_passes_trivially() -> None:
    assert main([]) == 0
