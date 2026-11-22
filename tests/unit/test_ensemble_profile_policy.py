"""Tests for enforce_profile_policy + su cableado en send_to_profile.

WOT-2026-222a FASE 1 (v4): el alcance del guard es DELIBERADAMENTE estrecho
-- ver docstring de `enforce_profile_policy` en scripts/ensemble_dispatch.py.
Cada test lee el `agents.json` REAL del motor via `ed.load_motor_config()`,
nunca un perfil sintetico con campos inventados: la regresion medida en P34
ronda 3 (ds H-02, sonnet H-01) existia precisamente porque la sonda anterior
probaba contra perfiles "api"/"agent" que no existian en agents.json.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ensemble_dispatch as ed  # noqa: E402


REAL_NON_KILO_LENS_PROFILES = [
    "proposer_claude",
    "challenger_codex",
    "challenger_claude_sonnet_cli",
    "challenger_claude_opus_cli",
    "challenger_codex_sol_cli",
    "challenger_opencode_glm_flash_nan",
]

REAL_KILO_LEGACY_PROFILES = [
    "challenger_kilo_deepseek_flash",
    "challenger_kilo_qwen",
    "challenger_kilo_gemma",
    "challenger_kilo_qwen_flash",
    "challenger_kilo_glm_flash",
    "challenger_kilo_glm",
    "challenger_kilo_mimo_flash",
]


def _real_config():
    return ed.load_motor_config()


@pytest.mark.parametrize("profile_name", REAL_NON_KILO_LENS_PROFILES)
def test_enforce_profile_policy_accepts_real_non_kilo_lenses(profile_name):
    config = _real_config()
    profile = config["ensemble_profiles"][profile_name]
    backend_cfg = config["backends"][profile["backend"]]
    ed.enforce_profile_policy(profile, caller="lens", backend_cfg=backend_cfg)


@pytest.mark.parametrize("profile_name", REAL_KILO_LEGACY_PROFILES)
def test_enforce_profile_policy_rejects_real_kilo_profiles_as_lens(profile_name):
    config = _real_config()
    profile = config["ensemble_profiles"][profile_name]
    backend_cfg = config["backends"][profile["backend"]]
    with pytest.raises(ed.DispatchBlockedError, match="Kilo"):
        ed.enforce_profile_policy(profile, caller="lens", backend_cfg=backend_cfg)


def test_enforce_profile_policy_rejects_kilo_even_if_edited_to_write_false():
    config = _real_config()
    profile = dict(config["ensemble_profiles"]["challenger_kilo_glm_flash"])
    profile["write"] = False
    profile.pop("status", None)
    with pytest.raises(ed.DispatchBlockedError, match="Kilo"):
        ed.enforce_profile_policy(profile, caller="lens", backend_cfg={})


def test_enforce_profile_policy_rejects_explicit_write_true_as_lens():
    profile = {"backend": "fake", "channel": "api", "write": True}
    with pytest.raises(ed.DispatchBlockedError, match="write"):
        ed.enforce_profile_policy(profile, caller="lens")


def test_enforce_profile_policy_accepts_lens_with_write_absent():
    profile = {"backend": "fake", "channel": "agent"}
    ed.enforce_profile_policy(profile, caller="lens")


def test_enforce_profile_policy_builder_requires_write_true():
    ed.enforce_profile_policy({"write": True}, caller="builder")
    with pytest.raises(ed.DispatchBlockedError, match="Builder"):
        ed.enforce_profile_policy({"write": False}, caller="builder")
    with pytest.raises(ed.DispatchBlockedError, match="Builder"):
        ed.enforce_profile_policy({}, caller="builder")


def test_enforce_profile_policy_rejects_unknown_caller():
    with pytest.raises(ValueError, match="caller"):
        ed.enforce_profile_policy({"write": False}, caller="orchestrator")


def test_send_to_profile_dispatches_real_lens_and_blocks_real_kilo_legacy():
    config = _real_config()
    transport_calls = []

    def fake_transport(profile, backend_cfg, messages, timeout):
        transport_calls.append(profile.get("backend"))
        return "ok"

    reply = ed.send_to_profile(
        "challenger_codex",
        [{"role": "user", "content": "hola"}],
        config=config,
        sensitivity="public",
        transport=fake_transport,
    )
    assert reply == "ok"
    assert transport_calls == ["codex"]

    with pytest.raises(ed.DispatchBlockedError, match="Kilo"):
        ed.send_to_profile(
            "challenger_kilo_glm_flash",
            [{"role": "user", "content": "hola"}],
            config=config,
            sensitivity="public",
            transport=fake_transport,
        )
    assert transport_calls == ["codex"]


def test_send_to_profile_builder_caller_rejects_the_same_real_lens():
    config = _real_config()

    def fake_transport(profile, backend_cfg, messages, timeout):
        return "ok"

    with pytest.raises(ed.DispatchBlockedError, match="Builder"):
        ed.send_to_profile(
            "challenger_codex",
            [{"role": "user", "content": "hola"}],
            config=config,
            sensitivity="public",
            transport=fake_transport,
            caller="builder",
        )


def test_seven_kilo_profiles_are_legacy_with_live_replaced_by():
    config = _real_config()
    profiles = config["ensemble_profiles"]
    kilo_legacy = sorted(
        name for name, p in profiles.items() if p.get("backend") == "kilo"
    )
    assert kilo_legacy == sorted(REAL_KILO_LEGACY_PROFILES)
    for name in kilo_legacy:
        profile = profiles[name]
        assert profile.get("status") == "legacy", name
        replaced_by = profile.get("replaced_by")
        assert replaced_by, f"{name} sin replaced_by declarado"
        assert replaced_by in profiles, f"{name}.replaced_by={replaced_by!r} no existe"
        assert not ed.is_legacy_profile(profiles[replaced_by]), (
            f"{name}.replaced_by={replaced_by!r} tambien es legacy"
        )


def test_selectable_profiles_excludes_all_seven_kilo_legacy():
    config = _real_config()
    selectable = ed.selectable_profiles(config)
    for name in REAL_KILO_LEGACY_PROFILES:
        assert name not in selectable, f"{name} sigue seleccionable"


def test_selectable_profiles_excludes_premium_glm_full_via_auto_select():
    config = _real_config()
    selectable = ed.selectable_profiles(config)
    assert "challenger_opencode_glm_nan" not in selectable
    assert "challenger_opencode_glm_flash_nan" in selectable
    assert config["ensemble_profiles"]["challenger_opencode_glm_nan"]["write"] is False


def test_nan_route_sibling_candidates_excludes_kilo_glm_legacy():
    config = _real_config()
    failed = config["ensemble_profiles"]["challenger_opencode_glm_flash"]
    same_family_candidates = [
        name
        for name, p in ed.selectable_profiles(config).items()
        if ed.MODEL_FAMILY_MAP.get((p.get("backend"), p.get("model"))) == "glm"
    ]
    siblings = ed._nan_route_sibling_candidates(failed, same_family_candidates, config)
    assert "challenger_kilo_glm_flash" not in same_family_candidates
    assert "challenger_kilo_glm" not in same_family_candidates
    assert siblings == [] or all("kilo" not in s for s in siblings)


def test_model_family_map_has_opencode_glm_nan_pairs():
    assert ed.MODEL_FAMILY_MAP[("opencode", "nan/glm5.3-flash")] == "glm"
    assert ed.MODEL_FAMILY_MAP[("opencode", "nan/glm5.3")] == "glm"
