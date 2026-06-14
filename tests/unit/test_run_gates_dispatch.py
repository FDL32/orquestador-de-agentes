from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location(
    "run_gates_dispatch",
    PROJECT_ROOT / "scripts" / "run_gates_dispatch.py",
)
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)


def test_read_deliverable_type_present(tmp_path, monkeypatch):
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text("- **deliverable_type:** documentation\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "WORK_PLAN", fake_plan)
    assert dispatch.read_deliverable_type() == "documentation"


def test_read_deliverable_type_missing_fallback(tmp_path, monkeypatch, capsys):
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text("# Plan without type\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "WORK_PLAN", fake_plan)
    assert dispatch.read_deliverable_type() == "code"
    err = capsys.readouterr().err
    assert "no deliverable_type" in err


def test_read_deliverable_type_compound_treated_as_mixed(tmp_path, monkeypatch):
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text(
        "- **deliverable_type:** code+documentation\n", encoding="utf-8"
    )
    monkeypatch.setattr(dispatch, "WORK_PLAN", fake_plan)
    assert dispatch.read_deliverable_type() == "mixed"


def test_read_deliverable_type_unknown_fallback(tmp_path, monkeypatch, capsys):
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text("- **deliverable_type:** nonsense\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "WORK_PLAN", fake_plan)
    assert dispatch.read_deliverable_type() == "code"
    err = capsys.readouterr().err
    assert "unknown type" in err


def test_run_code_gates_uses_project_pip_audit_wrapper():
    """The dispatcher must share the same dependency-audit surface as pre-commit."""
    source = (PROJECT_ROOT / "scripts" / "run_gates_dispatch.py").read_text(
        encoding="utf-8"
    )
    assert "scripts/pip_audit_project.py" in source
    assert '"uv", "run", "pip-audit", "."' not in source
    assert "uv run pip-audit ." not in source


# WOT-2026-003e: has_local_tests — destino without a local suite must not fail gates


def test_has_local_tests_false_when_no_tests_dir(tmp_path):
    assert dispatch.has_local_tests(tmp_path) is False


def test_has_local_tests_false_when_tests_dir_empty(tmp_path):
    (tmp_path / "tests").mkdir()
    assert dispatch.has_local_tests(tmp_path) is False


def test_has_local_tests_false_when_tests_dir_has_no_test_files(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "helper.py").write_text("x = 1\n", encoding="utf-8")
    (tests / "conftest.py").write_text("", encoding="utf-8")
    assert dispatch.has_local_tests(tmp_path) is False


def test_has_local_tests_true_with_test_prefix(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_thing.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    assert dispatch.has_local_tests(tmp_path) is True


def test_has_local_tests_true_with_test_suffix_nested(tmp_path):
    nested = tmp_path / "tests" / "unit"
    nested.mkdir(parents=True)
    (nested / "thing_test.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    assert dispatch.has_local_tests(tmp_path) is True
