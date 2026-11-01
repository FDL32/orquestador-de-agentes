"""WOT-2026-089h-1: lint de clasificacion de endpoints de ensemble (fase F0).

Cubre el DoD (a)-(e) de la ficha sobre el registro REAL del motor
(`.agent/config/agents.json`) y sobre copias mutadas: cada rama del DoD tiene
una mutacion que la pone en rojo. Los numeros (44 active, 6 pares historicos)
son evidencia fechada; el criterio es el invariante (todo active clasificado,
mapa derivado == MODEL_FAMILY_MAP salvo un delta declarado y exacto).
"""

from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import pytest


MOTOR_ROOT = Path(__file__).resolve().parents[2]
for _p in (MOTOR_ROOT / "scripts", MOTOR_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import check_ensemble_registry_classification as cec  # noqa: E402
import ensemble_dispatch as ed  # noqa: E402
import validate_agent_config as vac  # noqa: E402


REAL_PATH = MOTOR_ROOT / ".agent" / "config" / "agents.json"
FIELDS = ("lab", "family", "tier", "generation")

# DoD (c): pares (backend, model) que MODEL_FAMILY_MAP conoce y el registro no
# clasifica. Delta EXPLICITO y exacto (snapshot 2026-11-01): un par nuevo en el
# mapa sin endpoint clasificado FALLA hasta que se declare aqui o se clasifique.
HISTORIC_MAP_ONLY = {
    ("opencode", "opencode-go/glm-5.2"),  # 384 filas de scorecard (decision 2026-09-29)
    ("codex", None),
    ("codex", "gpt-5.4"),
    ("codex", "gpt-5.4-mini"),
    ("codex", "gpt-5.5"),
    ("codex", "gpt-6-astra"),
}
# Par con endpoint en el registro pero SIN clasificar: lab desconocido (stealth).
REGISTRY_UNCLASSIFIED_PAIRS = {("openrouter_api", "stealth/space-bunny-alpha")}


def _real() -> dict:
    return json.loads(REAL_PATH.read_text(encoding="utf-8"))


def _good() -> dict:
    """Registro sintetico minimo y coherente (control positivo de las mutaciones)."""
    block = {
        "schema_version": "1",
        "required_fields": list(cec.FROZEN["1"]["required_fields"]),
        "tiers": list(cec.FROZEN["1"]["tiers"]),
        "labs": list(cec.FROZEN["1"]["labs_floor"]),
        "required_for_status": ["active"],
    }
    keys = {
        "BA01": {
            "backend": "p_api",
            "model": "zhi-x-flash",
            "status": "active",
            "lab": "Zhipu",
            "family": "glm",
            "tier": "flash",
            "generation": 1,
        },
        "BA02": {
            "backend": "q_api",
            "model": "zhi-x-flash",
            "status": "deprecated",
            "lab": "Zhipu",
            "family": "glm",
            "tier": "flash",
            "generation": 1,
        },
        "BA03": {"backend": "r_api", "model": "old", "status": "archived"},
    }
    return {"ensemble_registry": {"classification": block, "backend_keys": keys}}


def _active_keys(cfg: dict) -> list[str]:
    return [
        k
        for k, v in cfg["ensemble_registry"]["backend_keys"].items()
        if v.get("status") == "active"
    ]


def derived_family_map(cfg: dict) -> dict[tuple, str]:
    """Mapa (backend, model) -> family derivado de los endpoints clasificados."""
    out: dict[tuple, str] = {}
    for ent in cfg["ensemble_registry"]["backend_keys"].values():
        if all(f in ent for f in FIELDS):
            out[(ent["backend"], ent["model"])] = ent["family"]
    return out


def family_map_findings(cfg: dict, mapping: dict) -> list[str]:
    """Discrepancias entre el mapa derivado del registro y `mapping` (DoD c)."""
    derived = derived_family_map(cfg)
    findings = [
        f"{pair}: registro={fam!r} mapa={mapping.get(pair)!r}"
        for pair, fam in sorted(derived.items(), key=str)
        if mapping.get(pair) != fam
    ]
    map_only = set(mapping) - set(derived)
    expected = HISTORIC_MAP_ONLY | REGISTRY_UNCLASSIFIED_PAIRS
    findings += [
        f"solo-mapa no declarado: {p}" for p in sorted(map_only - expected, key=str)
    ]
    findings += [
        f"delta declarado ya no existe en el mapa: {p}"
        for p in sorted(expected - map_only, key=str)
    ]
    return findings


# --- (a) todo endpoint active clasificado, sobre el registro REAL ----------


def test_real_registry_is_clean_and_every_active_endpoint_is_classified():
    cfg = _real()
    assert cec.lint_registry(cfg) == []
    active = _active_keys(cfg)
    assert active, "denominador 0: el registro real no tiene endpoints active"
    for key in active:
        ent = cfg["ensemble_registry"]["backend_keys"][key]
        missing = [f for f in FIELDS if f not in ent]
        assert not missing, f"{key} sin {missing}"


@pytest.mark.parametrize("field", FIELDS)
def test_a_real_active_endpoint_missing_a_field_names_endpoint_and_field(field):
    cfg = _real()
    key = _active_keys(cfg)[0]
    del cfg["ensemble_registry"]["backend_keys"][key][field]
    errors = cec.lint_registry(cfg)
    assert any(f"{key}: campo '{field}' ausente" in e for e in errors), errors


def test_a_paso0_new_active_endpoint_without_fields_is_red():
    """El ROJO de la ficha: BA999 active sin clasificar pasaba todos los gates."""
    cfg = _real()
    cfg["ensemble_registry"]["backend_keys"]["BA999"] = {
        "backend": "zz_api",
        "model": "zz/modelo-sin-clasificar",
        "backend_version": None,
        "status": "active",
    }
    errors = cec.lint_registry(cfg)
    assert sum(1 for e in errors if e.startswith("BA999:")) == 4, errors


def test_a_non_active_may_be_unclassified_but_not_partially_classified():
    cfg = _good()
    assert cec.lint_registry(cfg) == []  # BA03 archived sin campos: valido
    cfg["ensemble_registry"]["backend_keys"]["BA03"]["lab"] = "Zhipu"
    errors = cec.lint_registry(cfg)
    assert any(
        "BA03: campo 'family' ausente (clasificacion parcial)" in e for e in errors
    )


# --- (b) lab de tabla cerrada y valores de campo ----------------------------


def test_b_lab_outside_closed_table_is_red_on_real_and_synthetic():
    for cfg in (_real(), _good()):
        key = _active_keys(cfg)[0]
        cfg["ensemble_registry"]["backend_keys"][key]["lab"] = "Meta"
        errors = cec.lint_registry(cfg)
        assert any(
            f"{key}: campo 'lab' = 'Meta' fuera de la tabla cerrada" in e
            for e in errors
        )


def test_b_lab_in_table_but_wrong_case_is_red():
    cfg = _good()
    cfg["ensemble_registry"]["backend_keys"]["BA01"]["lab"] = "zhipu"
    assert any("fuera de la tabla cerrada" in e for e in cec.lint_registry(cfg))


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("family", "GLM", "debe ser una palabra en minusculas"),
        ("family", "glm-5", "debe ser una palabra en minusculas"),
        ("family", "", "debe ser una palabra en minusculas"),
        ("family", None, "debe ser una palabra en minusculas"),
        ("tier", "pro", "fuera de ['full', 'flash']"),
        ("generation", 0, "debe ser un entero >= 1"),
        ("generation", True, "debe ser un entero >= 1"),
        ("generation", "1", "debe ser un entero >= 1"),
        ("generation", 1.5, "debe ser un entero >= 1"),
        ("variant", "", "debe ser una cadena no vacia"),
        ("variant", 3, "debe ser una cadena no vacia"),
    ],
)
def test_b_invalid_field_values_are_red(field, value, fragment):
    cfg = _good()
    cfg["ensemble_registry"]["backend_keys"]["BA01"][field] = value
    errors = cec.lint_registry(cfg)
    assert any(e.startswith("BA01:") and fragment in e for e in errors), errors


def test_b_variant_is_optional_and_accepted_when_valid():
    cfg = _good()
    cfg["ensemble_registry"]["backend_keys"]["BA01"]["variant"] = "27b"
    cfg["ensemble_registry"]["backend_keys"]["BA02"]["variant"] = "27b"
    assert cec.lint_registry(cfg) == []


# --- regla de tier (mecanica, por tokens) -----------------------------------


@pytest.mark.parametrize(
    ("model", "tier"),
    [
        ("nan/qwen3.8-flash", "flash"),
        ("GLM-5.3-Flash", "flash"),
        ("cohere/north-mini-code:free", "flash"),
        ("claude-haiku-5-5", "flash"),
        ("minimax-m2.7", "full"),  # `minimax` no es el token `mini`
        ("gemini-3.8-flash", "flash"),
        ("gpt-5.6-luna", "full"),
        ("qwen/qwen3.8-27b", "full"),
        ("sonnet", "full"),
        (None, "full"),
    ],
)
def test_tier_rule_is_token_based(model, tier):
    assert cec.tier_by_rule(model) == tier


def test_tier_rule_violation_is_red_and_tokens_not_substrings():
    cfg = _good()
    cfg["ensemble_registry"]["backend_keys"]["BA01"]["tier"] = "full"  # *-flash
    cfg["ensemble_registry"]["backend_keys"]["BA02"]["tier"] = "full"
    errors = cec.lint_registry(cfg)
    assert any(
        "BA01: campo 'tier' = 'full' contradice la regla de tier" in e for e in errors
    )
    cfg = _good()
    for key in ("BA01", "BA02"):
        cfg["ensemble_registry"]["backend_keys"][key].update(
            model="minimax-m2.7", tier="full"
        )
    assert cec.lint_registry(cfg) == []


def test_tier_rule_holds_on_every_real_classified_endpoint():
    cfg = _real()
    for key, ent in cfg["ensemble_registry"]["backend_keys"].items():
        if "tier" in ent:
            assert ent["tier"] == cec.tier_by_rule(ent["model"]), key


# --- consistencia entre endpoints -------------------------------------------


def test_same_backend_model_pair_must_share_classification():
    cfg = _real()
    bk = cfg["ensemble_registry"]["backend_keys"]
    assert bk["BA17"]["model"] == bk["BA20"]["model"]  # control: par duplicado real
    bk["BA20"]["generation"] = bk["BA17"]["generation"] + 1
    errors = cec.lint_registry(cfg)
    assert any(e.startswith("BA20: clasificacion distinta de BA17") for e in errors), (
        errors
    )


def test_a_family_belongs_to_a_single_lab():
    cfg = _good()
    bk = cfg["ensemble_registry"]["backend_keys"]
    bk["BA02"].update(model="otro", lab="Alibaba")
    errors = cec.lint_registry(cfg)
    assert any(
        "BA02: la family 'glm' ya pertenece a lab 'Zhipu'" in e for e in errors
    ), errors


# --- (c) mapa derivado del registro == MODEL_FAMILY_MAP ---------------------


def test_c_derived_family_map_equals_model_family_map_with_declared_delta():
    cfg = _real()
    assert family_map_findings(cfg, ed.MODEL_FAMILY_MAP) == []
    assert len(derived_family_map(cfg)) >= len(_active_keys(cfg)) - 6  # denominador


def test_c_changing_a_registry_family_is_red():
    cfg = _real()
    bk = cfg["ensemble_registry"]["backend_keys"]
    key = _active_keys(cfg)[0]
    bk[key]["family"] = "otrafamilia"
    assert any(
        key in f or "registro=" in f
        for f in family_map_findings(cfg, ed.MODEL_FAMILY_MAP)
    )


def test_c_new_map_entry_without_classified_endpoint_is_red():
    mapping = dict(ed.MODEL_FAMILY_MAP)
    mapping[("nuevo_api", "modelo-sin-endpoint")] = "glm"
    findings = family_map_findings(_real(), mapping)
    assert findings == ["solo-mapa no declarado: ('nuevo_api', 'modelo-sin-endpoint')"]


def test_c_delta_entry_removed_from_map_is_red():
    mapping = dict(ed.MODEL_FAMILY_MAP)
    del mapping[("codex", "gpt-5.5")]
    findings = family_map_findings(_real(), mapping)
    assert findings == ["delta declarado ya no existe en el mapa: ('codex', 'gpt-5.5')"]


# --- (d)/(e) esquema congelado y versionado ---------------------------------


def test_schema_v1_is_frozen_literal():
    assert cec.FROZEN["1"]["required_fields"] == ("lab", "family", "tier", "generation")
    assert cec.FROZEN["1"]["tiers"] == ("full", "flash")
    assert set(cec.FROZEN["1"]["labs_floor"]) == {
        "Alibaba", "Anthropic", "Cohere", "DeepSeek", "Google", "MiniMax",
        "Mistral AI", "Moonshot", "NVIDIA", "OpenAI", "Xiaomi", "Zhipu",
    }  # fmt: skip
    assert cec.OPTIONAL_FIELDS == ("variant",)
    assert {"flash", "mini", "haiku", "lite", "nano"} == cec.TIER_FLASH_MARKERS
    assert _real()["ensemble_registry"]["classification"]["schema_version"] == "1"


def test_changing_required_fields_without_bumping_schema_version_is_red():
    cfg = _real()
    cfg["ensemble_registry"]["classification"]["required_fields"].append("data_policy")
    errors = cec.lint_registry(cfg)
    assert any(
        "required_fields" in e and "subir schema_version" in e for e in errors
    ), errors


def test_changing_tiers_or_dropping_a_floor_lab_is_red():
    cfg = _real()
    cfg["ensemble_registry"]["classification"]["tiers"] = ["full", "flash", "pro"]
    assert any("classification.tiers" in e for e in cec.lint_registry(cfg))
    cfg = _real()
    cfg["ensemble_registry"]["classification"]["labs"].remove("Zhipu")
    errors = cec.lint_registry(cfg)
    assert any("perdio laboratorios del suelo v1: ['Zhipu']" in e for e in errors), (
        errors
    )


def test_extending_the_lab_table_is_allowed_without_bumping_the_version():
    cfg = _real()
    cfg["ensemble_registry"]["classification"]["labs"].append("Meta")
    assert cec.lint_registry(cfg) == []


def test_unknown_or_missing_schema_version_is_red():
    cfg = _real()
    cfg["ensemble_registry"]["classification"]["schema_version"] = "2"
    assert any("schema_version '2' desconocida" in e for e in cec.lint_registry(cfg))
    del cfg["ensemble_registry"]["classification"]
    assert any("classification ausente" in e for e in cec.lint_registry(cfg))


def test_malformed_block_does_not_crash_and_is_reported():
    cfg = _good()
    cfg["ensemble_registry"]["classification"]["required_for_status"] = "active"
    cfg["ensemble_registry"]["classification"]["labs"] = "x"
    errors = cec.lint_registry(cfg)
    assert any("required_for_status" in e for e in errors)
    assert any("classification.labs" in e for e in errors)


def test_non_dict_registry_entry_and_missing_registry_are_reported():
    cfg = _good()
    cfg["ensemble_registry"]["backend_keys"]["BA09"] = "texto"
    assert any(e.startswith("BA09:") for e in cec.lint_registry(cfg))
    assert cec.lint_registry({}) == [
        "ensemble_registry.backend_keys ausente o no es un objeto"
    ]


# --- CLI y cableado ----------------------------------------------------------


def _write(tmp_path: Path, cfg: dict) -> Path:
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def test_cli_exit_codes_and_no_vacuous_ok(tmp_path, capsys):
    assert cec.main(["--config", str(_write(tmp_path, _good()))]) == 0
    assert "OK: 3 endpoints revisados (1 active)" in capsys.readouterr().out
    bad = _good()
    bad["ensemble_registry"]["backend_keys"]["BA01"].pop("lab")
    assert cec.main(["--config", str(_write(tmp_path, bad))]) == 1
    assert "BA01: campo 'lab' ausente" in capsys.readouterr().out
    empty = {"ensemble_registry": {"backend_keys": {}}}
    assert cec.main(["--config", str(_write(tmp_path, empty))]) == 2
    assert cec.main(["--config", str(tmp_path / "no_existe.json")]) == 2
    assert "OK" not in capsys.readouterr().out


def test_lint_config_file_reports_unreadable_and_empty_as_findings(tmp_path):
    assert cec.lint_config_file(tmp_path / "no_existe.json")[0].startswith(
        "no verificable"
    )
    empty = _write(tmp_path, {"ensemble_registry": {"backend_keys": {}}})
    assert cec.lint_config_file(empty)[0].startswith("no verificable")


def _isolate_main(monkeypatch, vac_module):
    monkeypatch.setattr(vac_module, "validate_trigger_uniqueness", lambda: [])
    monkeypatch.setattr(vac_module, "validate_skill_frontmatter", lambda: [])
    monkeypatch.setattr(vac_module, "validate_motor_agents_config", lambda: None)


def test_wiring_validate_agent_config_fails_on_unclassified_active_endpoint(
    tmp_path, monkeypatch, capsys
):
    """El cableado: validate_agent_config (hook pre-commit always_run) corre el lint."""
    _isolate_main(monkeypatch, vac)
    (tmp_path / ".agent" / "config").mkdir(parents=True)
    bad = _real()
    bad["ensemble_registry"]["backend_keys"]["BA999"] = {
        "backend": "zz_api",
        "model": "zz/x",
        "status": "active",
    }
    cfg_path = tmp_path / ".agent" / "config" / "agents.json"
    cfg_path.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(vac, "MOTOR_ROOT", tmp_path)
    assert vac.main() == 1
    out = capsys.readouterr().out
    assert "BA999: campo 'lab' ausente" in out
    # control positivo: el mismo motor sin BA999 pasa
    del bad["ensemble_registry"]["backend_keys"]["BA999"]
    cfg_path.write_text(json.dumps(bad), encoding="utf-8")
    assert vac.main() == 0


def test_wiring_main_calls_the_classification_gate(monkeypatch):
    _isolate_main(monkeypatch, vac)
    monkeypatch.setattr(vac, "validate_ensemble_registry_classification", lambda: ["x"])
    assert vac.main() == 1


def test_real_motor_passes_validate_agent_config_gate():
    assert vac.validate_ensemble_registry_classification() == []


def test_lint_is_fast_enough_for_an_always_run_hook():
    cfg = _real()
    start = time.perf_counter()
    for _ in range(20):
        cec.lint_registry(cfg)
    assert (time.perf_counter() - start) / 20 < 0.1


def test_lint_does_not_mutate_its_input():
    cfg = _real()
    snapshot = copy.deepcopy(cfg)
    cec.lint_registry(cfg)
    assert cfg == snapshot
