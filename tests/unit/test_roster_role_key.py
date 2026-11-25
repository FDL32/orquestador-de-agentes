"""Focused FLT regressions for the shared coordinator-key contract."""

import importlib.util
import json
from pathlib import Path

import pytest
from scripts import check_roster_matches_acting_thread as guard
from scripts.flight import render_latido
from scripts.flight.roster_role_key import (
    RosterRoleKeyError,
    resolve_orchestrator_role,
    set_orchestrator_entry,
)


def test_resolver_is_symmetric_and_fail_closed():
    assert resolve_orchestrator_role({"orquestador": {}}) == "orquestador"
    assert resolve_orchestrator_role({"coordinadora": {}}) == "coordinadora"
    assert resolve_orchestrator_role({}) is None
    with pytest.raises(RosterRoleKeyError):
        resolve_orchestrator_role({"orquestador": {}, "coordinadora": {}})


def test_writer_set_updates_alias_without_creating_second_key():
    roles = {"coordinadora": {"old": 1}}
    set_orchestrator_entry(roles, {"new": 2})
    assert roles == {"coordinadora": {"new": 2}}
    roles = {}
    set_orchestrator_entry(roles, {"new": 2})
    assert set(roles) == {"orquestador"}


def test_writer_set_rejects_invalid_and_ambiguous_without_mutation():
    for roles in (None, {"orquestador": {}, "coordinadora": {}}):
        before = repr(roles)
        with pytest.raises((TypeError, RosterRoleKeyError)):
            set_orchestrator_entry(roles, {})
        assert repr(roles) == before


def test_find_violations_reports_one_ambiguity_and_not_missing_key(tmp_path: Path):
    roster = tmp_path / "roster.json"
    registry = tmp_path / "registry.json"
    changes = tmp_path / "changes.jsonl"
    roles = {
        "orquestador": {"estado": "ACTIVO"},
        "coordinadora": {"estado": "ACTIVO"},
    }
    roster.write_text(json.dumps({"active_roles": roles}), encoding="utf-8")
    registry.write_text(json.dumps({"sessions": []}), encoding="utf-8")
    violations, _ = guard.find_violations(
        roster, "mcp:x", registry, changes, "orquestador"
    )
    assert len([item for item in violations if "ambigua" in item]) == 1


def test_check_pendiente_ack_preserves_missing_helper_diagnostic(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(guard, "_role_key_load_error", ImportError("missing"))
    monkeypatch.setattr(
        guard,
        "resolve_orchestrator_role",
        lambda _roles: (_ for _ in ()).throw(guard.RosterRoleKeyError("both")),
    )
    result = guard.check_pendiente_ack(
        {"coordinadora": {}}, "coordinadora", tmp_path / "x"
    )
    assert "no se pudo cargar roster_role_key.py" in result[0]
    assert "ambigua" not in result[0]


def test_reduce_roster_alias_and_double_diagnostic():
    base = {
        "active_roles": {"coordinadora": {}, "supervisor": {}},
        "cadena_contexto": [{}],
    }
    reduced, errors = render_latido.reduce_roster(base)
    assert reduced is not None
    assert not any("ausente" in error for error in errors)
    double = {
        "active_roles": {"orquestador": {}, "coordinadora": {}},
        "cadena_contexto": [{}],
    }
    _, errors = render_latido.reduce_roster(double)
    assert sum("ambas claves" in error for error in errors) == 1
    assert not any(
        "debe contener orquestador o coordinadora" in error for error in errors
    )


def _load_hook(path: Path):
    spec = importlib.util.spec_from_file_location("isolated_native_stop_hook", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p9_coord_only_without_role_and_double_are_fail_closed(tmp_path: Path):
    hook_path = (
        Path(__file__).resolve().parents[2] / ".agent" / "hooks" / "native_stop_hook.py"
    )
    hook = _load_hook(hook_path)
    flight = tmp_path / "flight"
    flight.mkdir()
    roster = flight / "flight_roster.json"
    roster.write_text(
        json.dumps({"active_roles": {"coordinadora": {"session_code": "CO-1"}}}),
        encoding="utf-8",
    )
    assert hook._p9_resolve_co_activa(flight) == "CO-1"
    roster.write_text(
        json.dumps(
            {
                "active_roles": {
                    "orquestador": {"session_code": "CO-1"},
                    "coordinadora": {"session_code": "CO-2"},
                }
            }
        ),
        encoding="utf-8",
    )
    assert hook._p9_resolve_co_activa(flight) is None


def test_p9_production_binding_is_mandatory():
    hook_path = (
        Path(__file__).resolve().parents[2] / ".agent" / "hooks" / "native_stop_hook.py"
    )
    hook = _load_hook(hook_path)
    assert hook.RosterRoleKeyError is not ValueError
    assert hook.RosterRoleKeyError.__name__ == "RosterRoleKeyError"


def test_p9_mutant_removing_binding_fails(tmp_path: Path):
    source = (
        Path(__file__).resolve().parents[2] / ".agent" / "hooks" / "native_stop_hook.py"
    )
    mutant = tmp_path / "native_stop_hook.py"
    text = source.read_text(encoding="utf-8")
    binding = "    RosterRoleKeyError = _role_key_module.RosterRoleKeyError\n"
    assert binding in text
    mutant.write_text(text.replace(binding, "", 1), encoding="utf-8")
    hook = _load_hook(mutant)
    flight = tmp_path / "flight"
    flight.mkdir()
    (flight / "flight_roster.json").write_text(
        json.dumps({"active_roles": {"coordinadora": {"session_code": "CO-1"}}}),
        encoding="utf-8",
    )
    assert hook._p9_resolve_co_activa(flight) is None
