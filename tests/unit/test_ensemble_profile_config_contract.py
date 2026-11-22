"""Tests for the cross-registry contract of the 2 new OpenCode nan profiles.

WOT-2026-222a v4. Corrige el defecto medido en P34 ronda 3 (ds H-04, sonnet
H-02): la version anterior de este test fabricaba un dict sintetico de DOS
entradas y se autoafirmaba -- nunca leia .agent/config/agents.json, asi que
quedaba verde con los dos perfiles AUSENTES y con claves DUPLICADAS (usaba un
set, que no detecta duplicados). Este modulo lee el agents.json REAL y
compara contra TODOS los perfiles activos, no un subconjunto fabricado.
"""

from __future__ import annotations

import json
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_AGENTS_JSON = _MOTOR_ROOT / ".agent" / "config" / "agents.json"


def _load_real_config() -> dict:
    return json.loads(_AGENTS_JSON.read_text(encoding="utf-8"))


def registry_keys_without_profile(profiles: dict, registry: dict) -> list[str]:
    """Direccion INVERSA registro -> perfil: claves del registro que ningun
    perfil referencia por `backend_key`. Es el UNICO codigo del cruce inverso;
    lo usan el test sobre el agents.json REAL y el test del mutante sintetico,
    asi el sintetico no re-implementa la logica en su propio cuerpo."""
    used = {p["backend_key"] for p in profiles.values() if p.get("backend_key")}
    return sorted(set(registry) - used)


def test_two_new_profiles_exist_active_verifier_readonly():
    config = _load_real_config()
    profiles = config["ensemble_profiles"]
    for name, model, backend_key, tier in (
        ("challenger_opencode_glm_flash_nan", "nan/glm5.3-flash", "BA267", "flash"),
        ("challenger_opencode_glm_nan", "nan/glm5.3", "BA268", "full"),
    ):
        assert name in profiles, f"{name} no existe en agents.json"
        profile = profiles[name]
        assert profile["backend"] == "opencode"
        assert profile["model"] == model
        assert profile["backend_key"] == backend_key
        assert profile["tier"] == tier
        assert profile["status"] == "active"
        assert profile["write"] is False
        assert profile["channel"] == "agent"
        assert profile["lens_class"] == "verificadora"
        assert profile.get("readonly_agent") == "verificador"


def test_backend_keys_are_unique_across_all_active_profiles_real_config():
    """Cuenta por LISTA, no por set: dos perfiles ACTIVOS con la MISMA clave
    deben hacer fallar este test (sonnet H-02 / ds H-04: el set anterior no
    podia). Un perfil LEGACY puede compartir backend_key con su sustituto
    activo a proposito (continuidad de scorecard, p.ej. BA06 entre
    challenger_opencode_glm_5_2 legacy y challenger_opencode_glm_flash
    activo, WOT-2026-082a) -- el invariante real es "sin duplicados entre
    perfiles ACTIVOS", no "sin duplicados en todo el fichero"."""
    config = _load_real_config()
    profiles = config["ensemble_profiles"]
    active_keys = [
        p["backend_key"]
        for p in profiles.values()
        if p.get("backend_key") and p.get("status") != "legacy"
    ]
    duplicated = {k for k in active_keys if active_keys.count(k) > 1}
    assert not duplicated, f"backend_key duplicada entre perfiles ACTIVOS: {duplicated}"
    assert active_keys.count("BA267") == 1
    assert active_keys.count("BA268") == 1


def test_two_new_backend_keys_are_mirrored_in_registry_with_full_fields():
    config = _load_real_config()
    registry = config["ensemble_registry"]["backend_keys"]
    for key, model, tier in (
        ("BA267", "nan/glm5.3-flash", "flash"),
        ("BA268", "nan/glm5.3", "full"),
    ):
        assert key in registry, f"{key} ausente de ensemble_registry.backend_keys"
        entry = registry[key]
        for field in (
            "backend",
            "model",
            "lens_class",
            "status",
            "lab",
            "family",
            "tier",
            "generation",
        ):
            assert field in entry, f"{key}.{field} ausente"
        assert entry["backend"] == "opencode"
        assert entry["model"] == model
        assert entry["tier"] == tier
        assert entry["lab"] == "Zhipu"
        assert entry["family"] == "glm"


def test_every_active_profile_has_a_registry_entry_forward_direction():
    """Direccion perfil -> registro, contra el agents.json real: todo perfil
    ACTIVO con backend_key tiene entrada en el registro."""
    config = _load_real_config()
    profiles = config["ensemble_profiles"]
    registry = config["ensemble_registry"]["backend_keys"]
    missing = sorted(
        name
        for name, p in profiles.items()
        if p.get("backend_key") and p["backend_key"] not in registry
    )
    assert not missing, f"perfiles activos sin espejo de registro: {missing}"


def test_ba267_and_ba268_registry_entries_map_back_to_exactly_their_profiles():
    """codex H-05: direccion INVERSA (registro -> perfil) para los 2 keys
    NUEVOS de esta ficha. Alcance DECLARADO: no se generaliza a TODAS las
    73 entradas del registro real -- medido que 15 keys historicas
    (BA12/BA14/BA17-19/BA26-29/BA32-33/BA52/BA70-72) no tienen NINGUN
    perfil que las referencie hoy (nan_api legado, credito historico sin
    dispatch activo), asi que un assert generico "todo key activo tiene
    perfil" rompería contra datos reales preexistentes NO relacionados con
    esta ficha. La direccion inversa se prueba, con PRECISION, solo para
    las 2 claves que ESTA ficha da de alta."""
    config = _load_real_config()
    profiles = config["ensemble_profiles"]
    expected = {
        "BA267": "challenger_opencode_glm_flash_nan",
        "BA268": "challenger_opencode_glm_nan",
    }
    registry = config["ensemble_registry"]["backend_keys"]
    orphans = registry_keys_without_profile(profiles, registry)
    for key in expected:
        assert key not in orphans, f"{key} esta en el registro sin ningun perfil"
    for key, expected_profile in expected.items():
        owners = sorted(
            name for name, p in profiles.items() if p.get("backend_key") == key
        )
        assert owners == [expected_profile], (
            f"{key} deberia mapear de vuelta a exactamente [{expected_profile}], "
            f"mapea a {owners}"
        )


def test_reverse_cross_registry_check_catches_a_synthetic_orphan_key():
    """codex H-05: mutante PROVOCADO sobre un config SINTETICO pequeno (no el
    agents.json real, por la deuda historica declarada arriba) que demuestra
    que `registry_keys_without_profile` -- el MISMO helper que usa el test
    real -- detecta una clave de registro sin ningun perfil, y que no marca
    como huerfana una clave que si tiene perfil."""
    synthetic_profiles = {"p_with_key": {"backend_key": "BAX1"}}
    synthetic_registry = {"BAX1": {}, "BAX2_ORFANO": {}}
    assert registry_keys_without_profile(synthetic_profiles, synthetic_registry) == [
        "BAX2_ORFANO"
    ]
    assert registry_keys_without_profile(synthetic_profiles, {"BAX1": {}}) == []


def test_new_profiles_absent_from_default_challenger_roster():
    """f1-d10 (v4): ninguno de los 2 perfiles nuevos esta en el roster
    default; el premium queda ademas excluido del fallback (ver
    test_ensemble_profile_policy.py::test_selectable_profiles_excludes_premium_glm_full_via_auto_select)."""
    config = _load_real_config()
    roster = config["role_mapping"]["challenger"].get("ensemble_profiles_ref", [])
    assert "challenger_opencode_glm_flash_nan" not in roster
    assert "challenger_opencode_glm_nan" not in roster
