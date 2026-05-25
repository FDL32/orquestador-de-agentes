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
