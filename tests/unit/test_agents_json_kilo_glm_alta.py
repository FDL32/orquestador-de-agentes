"""Tests de contrato para el alta kilo de GLM-5.3 completo."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ensemble_dispatch as ed  # noqa: E402


EXPECTED_KILO_GLM = {"BA255": ("nan/glm5.3", "Zhipu", "glm", 1)}


def _real_config() -> dict:
    """Before: identify the motor config; During: load it; After: return it."""
    return ed.load_motor_config()


def test_perfil_challenger_kilo_glm_has_complete_contract():
    """Before: load profiles; During: inspect the new signature; After: verify every field."""
    config = _real_config()
    profile = config["ensemble_profiles"]["challenger_kilo_glm"]
    flash = config["ensemble_profiles"]["challenger_kilo_glm_flash"]

    assert profile["backend"] == "kilo"
    assert profile["channel"] == "agent"
    assert profile["model"] == "nan/glm5.3"
    assert profile["context"] == "diff-o-artefacto-publico"
    assert profile["write"] is True
    assert (
        profile["write_enforcement_note"]
        == "Ver nota identica en challenger_kilo_deepseek_flash."
    )
    assert profile["data_sensitivity"] == "public"
    assert profile["backend_key"] == "BA255"
    assert profile["repo_scope"] == "destino"

    assert flash["backend"] == "kilo"
    assert flash["channel"] == "agent"
    assert flash["model"] == "nan/glm5.3-flash"
    assert flash["context"] == "diff-o-artefacto-publico"
    assert flash["write"] is True
    assert (
        flash["write_enforcement_note"]
        == "Ver nota identica en challenger_kilo_deepseek_flash."
    )
    assert flash["data_sensitivity"] == "public"
    assert flash["backend_key"] == "BA03"
    assert flash["repo_scope"] == "destino"


def test_BA255_has_expected_registry_contract():  # noqa: N802
    """Before: load the registry; During: inspect BA255; After: verify its classification."""
    config = _real_config()
    registry = config["ensemble_registry"]
    entry = registry["backend_keys"]["BA255"]
    model, lab, family, generation = EXPECTED_KILO_GLM["BA255"]

    assert "BA255" in registry["backend_keys"]
    assert entry["model"] == model
    assert entry["backend"] == "kilo"
    assert entry["tier"] == "full"
    assert entry["backend_version"] is None
    assert entry["status"] == "active"
    assert entry["lab"] in registry["classification"]["labs"]
    assert entry["lab"] == lab
    assert entry["family"] == family
    assert isinstance(entry["generation"], int)
    assert entry["generation"] == generation


def test_challenger_kilo_glm_and_flash_signatures_are_independent():
    """Before: load both profiles; During: compare immutable signatures; After: reject copy loss."""
    config = _real_config()
    profile = config["ensemble_profiles"]["challenger_kilo_glm"]
    flash = config["ensemble_profiles"]["challenger_kilo_glm_flash"]

    assert profile != flash
    assert profile["model"] != flash["model"]
    assert profile["backend_key"] != flash["backend_key"]
    assert flash == {
        "backend": "kilo",
        "channel": "agent",
        "model": "nan/glm5.3-flash",
        "context": "diff-o-artefacto-publico",
        "write": True,
        "write_enforcement_note": "Ver nota identica en challenger_kilo_deepseek_flash.",
        "data_sensitivity": "public",
        "backend_key": "BA03",
        "repo_scope": "destino",
    }
