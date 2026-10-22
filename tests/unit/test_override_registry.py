"""Tests de libreria para scripts/override_registry.py (WOT-2026-119a).

Cubre las 4 salvaguardas a nivel de datos (sin subprocess git, sin
pre-commit): (c) scope estricto y (d) fail-closed se prueban aqui de forma
directa sobre `parse_override`/`scope_matches`; (a) y (b) se prueban sobre
`self_approval_violation`/`is_expired` con datos sinteticos. El contrato
end-to-end (fases pre-commit/commit-msg sobre un repo git real) vive en
`tests/unit/test_check_override_registry.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _ROOT / "scripts" / "override_registry.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reg = _load("override_registry", _MODULE_PATH)


VALID_YAML = """\
id: OVERRIDE-TEST-001
scope:
  - scripts/example_guarded.py
expiry: 2099-01-01
aprobador: tester
justificacion: motivo de prueba no vacio
"""


def _parse(text: str, name: str = "fixture.yaml"):
    return reg.parse_override(text, Path(name))


# --- Salvaguarda (d): fail-closed ------------------------------------------


def test_valid_yaml_parses_to_override():
    o = _parse(VALID_YAML)
    assert o.id == "OVERRIDE-TEST-001"
    assert o.scope == ("scripts/example_guarded.py",)
    assert o.expiry == date(2099, 1, 1)
    assert o.aprobador == "tester"


def test_illegible_yaml_raises_fail_closed():
    with pytest.raises(reg.OverrideRegistryError):
        _parse("id: [unterminated\n  - broken\n:::")


def test_missing_required_field_raises():
    for field in reg.REQUIRED_FIELDS:
        lines = VALID_YAML.splitlines()
        filtered = [line for line in lines if not line.startswith(f"{field}:")]
        broken = "\n".join(filtered)
        with pytest.raises(reg.OverrideRegistryError, match=field):
            _parse(broken)


def test_non_mapping_yaml_raises():
    with pytest.raises(reg.OverrideRegistryError):
        _parse("- just\n- a\n- list\n")


def test_bad_expiry_format_raises():
    broken = VALID_YAML.replace("expiry: 2099-01-01", "expiry: not-a-date")
    with pytest.raises(reg.OverrideRegistryError, match="expiry"):
        _parse(broken)


def test_empty_justificacion_raises():
    broken = VALID_YAML.replace(
        "justificacion: motivo de prueba no vacio", "justificacion: ''"
    )
    with pytest.raises(reg.OverrideRegistryError, match="justificacion"):
        _parse(broken)


# --- Salvaguarda (c): scope estricto, sin comodines -------------------------


def test_wildcard_in_scope_raises_malformed():
    broken = VALID_YAML.replace("scripts/example_guarded.py", "scripts/*.py")
    with pytest.raises(reg.OverrideRegistryError, match="comodines"):
        _parse(broken)


@pytest.mark.parametrize(
    "candidate,expected",
    [
        ("scripts/example_guarded.py", True),
        ("scripts/example_guarded_extra.py", False),
        ("scripts/sub/example_guarded.py", False),
        ("scripts/example_guarded.py.bak", False),
        ("other/scripts/example_guarded.py", False),
    ],
)
def test_scope_matches_is_exact_equality_not_prefix_or_substring(candidate, expected):
    o = _parse(VALID_YAML)
    assert reg.scope_matches(o, candidate) is expected


def test_scope_matches_normalizes_windows_separators():
    o = _parse(VALID_YAML)
    assert reg.scope_matches(o, "scripts\\example_guarded.py") is True


# --- Salvaguarda (b): expiry -----------------------------------------------


def test_is_expired_boundary():
    o = _parse(VALID_YAML)  # expiry 2099-01-01
    assert reg.is_expired(o, date(2099, 1, 2)) is True
    assert reg.is_expired(o, date(2099, 1, 1)) is False
    assert reg.is_expired(o, date(2098, 12, 31)) is False


# --- Salvaguarda (a): anti-auto-aprobacion ----------------------------------


def test_self_approval_violation_true_when_both_staged_together():
    o = _parse(VALID_YAML)
    changed = ["fixture.yaml", "scripts/example_guarded.py"]
    assert reg.self_approval_violation(o, "fixture.yaml", changed) is True


def test_no_violation_when_override_file_not_staged():
    o = _parse(VALID_YAML)
    changed = ["scripts/example_guarded.py"]
    assert reg.self_approval_violation(o, "fixture.yaml", changed) is False


def test_no_violation_when_scope_file_not_staged():
    o = _parse(VALID_YAML)
    changed = ["fixture.yaml", "scripts/unrelated.py"]
    assert reg.self_approval_violation(o, "fixture.yaml", changed) is False


def test_load_overrides_is_not_recursive_into_archive(tmp_path: Path):
    directory = tmp_path / "overrides"
    directory.mkdir()
    (directory / "active.yaml").write_text(VALID_YAML, encoding="utf-8")
    archive = directory / "_archive"
    archive.mkdir()
    (archive / "expired.yaml").write_text(
        VALID_YAML.replace("OVERRIDE-TEST-001", "OVERRIDE-TEST-ARCHIVED"),
        encoding="utf-8",
    )
    overrides = reg.load_overrides(directory)
    assert [o.id for o in overrides] == ["OVERRIDE-TEST-001"]


def test_load_overrides_fail_closed_on_any_bad_file(tmp_path: Path):
    directory = tmp_path / "overrides"
    directory.mkdir()
    (directory / "good.yaml").write_text(VALID_YAML, encoding="utf-8")
    (directory / "bad.yaml").write_text("id: only-id\n", encoding="utf-8")
    with pytest.raises(reg.OverrideRegistryError):
        reg.load_overrides(directory)


def test_load_overrides_on_missing_directory_returns_empty(tmp_path: Path):
    assert reg.load_overrides(tmp_path / "nonexistent") == []
