"""Contrato v2 del registro de niveles y acceso de los modelos."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from scripts import check_ensemble_registry_classification as cec


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / ".agent" / "config" / "agents.json"
V2_FIELDS = (
    "nivel",
    "esfuerzo",
    "acceso",
    "presupuesto",
    "limite",
    "uso_maximo",
    "nivel_decidido_por",
)


def _config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _entry(config: dict, model: str, backend: str | None = None) -> dict:
    for entry in config["ensemble_registry"]["backend_keys"].values():
        if entry.get("model") == model and (
            backend is None or entry.get("backend") == backend
        ):
            return entry
    raise AssertionError(f"no existe la clave para {model!r}")


def test_schema_v2_has_complete_active_classification_and_flat_usage_table():
    config = _config()
    registry = config["ensemble_registry"]
    classification = registry["classification"]
    assert classification["schema_version"] == "2"
    assert isinstance(classification["schema_version"], str)
    assert classification["required_fields"][-7:] == list(V2_FIELDS)
    assert set(registry["uso_maximo_por_tipo"]) == {"base", "medio", "alto", "premium"}
    assert all(
        isinstance(value, (int, float)) and value >= 0
        for value in registry["uso_maximo_por_tipo"].values()
    )
    active = [
        entry
        for entry in registry["backend_keys"].values()
        if entry.get("status") == "active"
    ]
    assert active
    assert all(all(field in entry for field in V2_FIELDS) for entry in active)


@pytest.mark.parametrize(
    ("model", "backend", "nivel", "acceso"),
    [
        ("nan/glm5.3", None, "premium", "cuenta_propia"),
        ("nan/glm5.3-flash", None, "alto", "cuenta_propia"),
        ("claude-haiku-5-5", "anthropic_api", "medio", "externo_pago"),
        ("claude-sonnet-5-5", "anthropic_api", "alto", "externo_pago"),
        ("claude-sonnet-5", "claude", "medio", "cuenta_propia"),
    ],
)
def test_sonnet5_and_user_decisions_are_recorded(model, backend, nivel, acceso):
    entry = _entry(_config(), model, backend)
    assert entry["nivel"] == nivel
    assert entry["acceso"] == acceso
    assert entry["nivel_decidido_por"]


def test_luna_and_roles_are_explicit_without_manager_model():
    config = _config()
    luna = _entry(config, "gpt-5.6-luna", "codex")
    assert luna["niveles"] == ["medio", "alto"]
    assert luna["nivel_max"] == "alto"
    assert config["role_models"]["BUILDER"] == "gpt-5.6-luna"
    assert config["role_models"]["REVISOR"] == "nan/mimo-v2.6-flash"
    assert config["role_models"]["MANAGER"] is None


def _roles_table_findings(roles: dict) -> list[str]:
    """Niveles esperados por rol y regla de esfuerzo s.9 sobre cada fila."""
    findings: list[str] = []
    expected = {"BUILDER": "alto", "MANAGER": "alto", "REVISOR": "medio"}
    for role, nivel in expected.items():
        row = roles.get(role)
        if not isinstance(row, dict):
            findings.append(f"roles.{role} ausente")
            continue
        if row.get("nivel") != nivel:
            findings.append(f"roles.{role}.nivel={row.get('nivel')!r} != {nivel!r}")
        if row.get("esfuerzo") != "alto":
            findings.append(f"roles.{role}.esfuerzo={row.get('esfuerzo')!r} != 'alto'")
    for name, row in roles.items():
        if not isinstance(row, dict):
            findings.append(f"roles.{name} no es un objeto")
            continue
        if row.get("nivel") != "base" and row.get("esfuerzo") != "alto":
            findings.append(f"roles.{name}: esfuerzo no-base debe ser alto (s.9)")
        if row.get("nivel") == "base" and row.get("esfuerzo") != "maximo":
            findings.append(f"roles.{name}: esfuerzo base debe ser maximo (s.9)")
    return findings


def _role_models_findings(role_models: dict) -> list[str]:
    """Los tres roles de role_models con sus valores decididos (t2-d04)."""
    findings: list[str] = []
    if role_models.get("MANAGER") is not None:
        findings.append(
            "role_models.MANAGER debe ser null (contrato vivo WOT-2026-098b)"
        )
    if role_models.get("REVISOR") != "nan/mimo-v2.6-flash":
        findings.append("role_models.REVISOR debe ser nan/mimo-v2.6-flash")
    if role_models.get("BUILDER") != "gpt-5.6-luna":
        findings.append("role_models.BUILDER debe ser gpt-5.6-luna (U5, alto)")
    return findings


def role_findings(config: dict) -> list[str]:
    """Incoherencias de la tabla de roles/efuerzo y de role_models (t2-d04).

    Before: `config` es el agents.json (vivo o copia mutada).
    During: delega en `_roles_table_findings` (tabla + regla s.9) y en
        `_role_models_findings` (tres roles, MANAGER null).
    After: lista de hallazgos; vacia = coherente. Solo lectura.
    """
    registry = config.get("ensemble_registry", {})
    return _roles_table_findings(registry.get("roles", {})) + _role_models_findings(
        config.get("role_models", {})
    )


def test_roles_table_is_explicit_and_effort_rule_holds():
    assert role_findings(_config()) == []


def test_roles_table_mutation_is_red():
    config = _config()
    mutated = copy.deepcopy(config)
    mutated["ensemble_registry"]["roles"]["REVISOR"]["nivel"] = "alto"
    assert role_findings(mutated)


def test_manager_non_null_mutation_is_red():
    config = _config()
    mutated = copy.deepcopy(config)
    mutated["role_models"]["MANAGER"] = "gpt-5.6-luna"
    assert any("WOT-2026-098b" in finding for finding in role_findings(mutated)), (
        role_findings(mutated)
    )


def test_precios_mutation_does_not_rewrite_level_without_decision():
    config = _config()
    mutated = copy.deepcopy(config)
    entry_before = copy.deepcopy(mutated["ensemble_registry"]["backend_keys"]["BA255"])
    precio = mutated["ensemble_registry"]["precios"]["BA255"]["precio_por_m_creditos"]
    precio["salida"] = precio["salida"] + 1
    # El lint no lee la tabla de precios: mismos hallazgos con precio mutado.
    assert cec.lint_registry(mutated) == cec.lint_registry(config)
    # Y el nivel/registro de la clave no se reescribe al cambiar el precio.
    assert mutated["ensemble_registry"]["backend_keys"]["BA255"] == entry_before


def test_precios_table_carries_measured_procedure_and_date():
    precios = _config()["ensemble_registry"]["precios"]
    assert precios, "ensemble_registry.precios debe existir"
    for key, entry in precios.items():
        assert entry.get("procedencia"), key
        assert entry.get("fecha"), key
        assert entry.get("nivel_decidido_por"), key
    medido = precios["BA255"]["precio_por_m_creditos"]
    assert medido == {"entrada_sin_cache": 49, "cache": 1.05, "salida": 154}


def test_classification_lint_rejects_invalid_access_and_missing_usage_cross_reference():
    config = _config()
    mutated = copy.deepcopy(config)
    active_key = next(
        key
        for key, entry in mutated["ensemble_registry"]["backend_keys"].items()
        if entry.get("status") == "active"
    )
    mutated["ensemble_registry"]["backend_keys"][active_key]["acceso"] = "api_magica"
    errors = cec.lint_registry(mutated)
    assert any("acceso" in error and active_key in error for error in errors)

    mutated = copy.deepcopy(config)
    del mutated["ensemble_registry"]["uso_maximo_por_tipo"]["premium"]
    errors = cec.lint_registry(mutated)
    assert any("uso_maximo_por_tipo" in error for error in errors)
