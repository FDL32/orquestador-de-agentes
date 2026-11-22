"""Tests de contrato para las seis altas nan_api de WOT-2026-161s."""
# [NON-REVERSE-CLASSICAL: test de contrato/cobertura nueva]

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import discover_loops as dl  # noqa: E402
import ensemble_dispatch as ed  # noqa: E402


BASELINE_KEYS = {
    "BA10",
    "BA11",
    "BA12",
    "BA13",
    "BA14",
    "BA15",
    "BA16",
    "BA25",
}
EXPECTED_NEW = {
    "BA26": ("glm5.3", "Zhipu", "glm", 1),
    "BA27": ("deepseek-v4-pro", "DeepSeek", "deepseek", 1),
    "BA28": ("hy4", "Tencent", "hy", 1),
    "BA29": ("qwen3.8-max", "Alibaba", "qwen", 2),
    "BA32": ("kimi-k3.1-pro", "Moonshot", "kimi", 2),
    "BA33": ("minimax-h3", "MiniMax", "minimax", 1),
}


def _real_config() -> dict:
    """Carga el agents.json real del motor y comprueba su cardinalidad."""
    config = ed.load_motor_config()
    # 73 = 65 previas + BA261..BA266 (lote opencode/*-free WOT-2026-204a)
    # + BA267..BA268 (WOT-2026-222a).
    assert len(config["ensemble_registry"]["backend_keys"]) == 73
    return config


def test_c01_new_nan_keys_have_expected_contract():
    """c-01: las seis claves nuevas tienen sus campos nan_api exactos."""
    config = _real_config()
    registry = config["ensemble_registry"]
    backend_keys = registry["backend_keys"]
    labs = registry["classification"]["labs"]
    new_keys = {
        key
        for key, entry in backend_keys.items()
        if key not in BASELINE_KEYS and entry["backend"] == "nan_api"
    }

    assert new_keys == set(EXPECTED_NEW)
    for key, (model, lab, family, generation) in EXPECTED_NEW.items():
        entry = backend_keys[key]
        assert entry["model"] == model
        assert entry["backend"] == "nan_api"
        assert entry["tier"] == "full"
        assert entry["backend_version"] is None
        # 13bb1c45 (orden directa del usuario, 2026-11-16) paso las claves
        # nan_api del registro a deprecated: los modelos nan solo se sirven via
        # kilo/opencode, y esas altas son BA255/BA256..BA260.
        assert entry["status"] == "deprecated"
        assert entry["lab"] in labs
        assert entry["lab"] == lab
        assert entry["family"] == family
        assert isinstance(entry["generation"], int)
        assert entry["generation"] == generation
        assert entry["generation"] >= 1


def test_c02_tencent_is_classified_and_validator_passes():
    """c-02: Tencent esta clasificado y el validador real termina en OK."""
    config = _real_config()
    assert "Tencent" in config["ensemble_registry"]["classification"]["labs"]
    result = subprocess.run(
        [sys.executable, "scripts/check_ensemble_registry_classification.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_c03_new_nan_keys_are_not_eligible():
    """c-03: ninguna alta nan_api aparece en la cobertura elegible."""
    config = _real_config()
    registry = config["ensemble_registry"]
    eligible = registry["eligible_coverage"]["MANAGER_REVIEW:repo_motor"]
    assert not set(EXPECTED_NEW).intersection(eligible["backend_keys"])


def test_c04_ba254_is_restricted_and_remains_eligible():
    """c-04: BA254 queda restringida y conserva su elegibilidad."""
    config = _real_config()
    registry = config["ensemble_registry"]
    ba254 = registry["backend_keys"]["BA254"]
    eligible = registry["eligible_coverage"]["MANAGER_REVIEW:repo_motor"]
    assert ba254["uso_restringido"] is True
    assert "BA254" in eligible["backend_keys"]


def test_c05_existing_backend_entries_are_unchanged():
    """c-05: las claves del baseline mantienen sus campos de registro."""
    config = _real_config()
    current = config["ensemble_registry"]["backend_keys"]
    baseline = json.loads(
        subprocess.check_output(
            ["git", "show", "8c74f577:.agent/config/agents.json"],
            cwd=PROJECT_ROOT,
            text=True,
        )
    )["ensemble_registry"]["backend_keys"]
    # Solo seis claves cambiaron de status de forma legitima: la migracion
    # nan_api -> opencode (5b2bb7ae/30134f53/13bb1c45, orden directa del usuario
    # 2026-11-16) las paso a deprecated. Para ellas el status va en el mapa
    # explicito de abajo; para TODAS las demas el asiento completo (status
    # incluido) sigue anclado al baseline pre-161s 8c74f577.
    #
    # WOT-2026-210a: lens_class es obligatorio desde este ticket y el baseline
    # historico (8c74f577) no lo lleva. Se anade al lado de la EXPECTATIVA el
    # valor que exige la misma regla de migracion (backend == opencode ->
    # verificadora; BA06 es la unica entrada opencode del baseline, el resto
    # texto). Las comparaciones de abajo siguen siendo EXACTAS: cualquier
    # lens_class incoherente con la regla o ausente en el actual sigue rojo.
    for base_entry in baseline.values():
        base_entry["lens_class"] = (
            "verificadora" if base_entry["backend"] == "opencode" else "texto"
        )
    migrated_status = {
        "BA10": "deprecated",
        "BA11": "deprecated",
        "BA13": "deprecated",
        "BA15": "deprecated",
        "BA16": "deprecated",
        "BA25": "deprecated",
    }
    for key, entry in baseline.items():
        if key == "BA254":
            continue
        if key in migrated_status:
            assert {
                field: value
                for field, value in current[key].items()
                if field != "status"
            } == {
                field: value for field, value in entry.items() if field != "status"
            }, key
        else:
            assert current[key] == entry, key
    assert {key: current[key]["status"] for key in migrated_status} == migrated_status
    ba254_expected = {
        key: value
        for key, value in baseline["BA254"].items()
        if not key.startswith("uso_")
    }
    assert {
        key: value
        for key, value in current["BA254"].items()
        if not key.startswith("uso_")
    } == ba254_expected


def test_c09_new_pairs_have_family_map_entry():
    """c-09: las seis parejas nuevas tienen entrada en MODEL_FAMILY_MAP."""
    config = _real_config()
    backend_keys = config["ensemble_registry"]["backend_keys"]
    expected_families = {
        "BA26": "glm",
        "BA27": "deepseek",
        "BA28": "hy",
        "BA29": "qwen",
        "BA32": "kimi",
        "BA33": "minimax",
    }

    for key, family in expected_families.items():
        entry = backend_keys[key]
        pair = (entry["backend"], entry["model"])
        assert ed.MODEL_FAMILY_MAP[pair] == entry["family"]
        assert ed.MODEL_FAMILY_MAP[pair] == family


def test_c10_loop_registry_md_lists_new_keys_and_is_not_stale():
    """c-10: loop_registry.md esta actualizado y lista las seis altas."""
    config_path = PROJECT_ROOT / ".agent" / "config" / "agents.json"
    registry_md_path = PROJECT_ROOT / "docs" / "registry" / "loop_registry.md"
    is_stale, diagnostic = dl.check_registry_md_stale(
        config_path=config_path, bundle_root=PROJECT_ROOT
    )
    assert not is_stale, diagnostic
    text = registry_md_path.read_text(encoding="utf-8")
    expected_rows = {
        # deprecated desde 13bb1c45: mismas claves, ahora servidas via kilo/opencode.
        "BA26": "| BA26 | nan_api | glm5.3 | deprecated |",
        "BA27": "| BA27 | nan_api | deepseek-v4-pro | deprecated |",
        "BA28": "| BA28 | nan_api | hy4 | deprecated |",
        "BA29": "| BA29 | nan_api | qwen3.8-max | deprecated |",
        "BA32": "| BA32 | nan_api | kimi-k3.1-pro | deprecated |",
        "BA33": "| BA33 | nan_api | minimax-h3 | deprecated |",
    }
    for row in expected_rows.values():
        assert row in text
