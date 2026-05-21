"""Unit tests for the conditional pip-audit policy."""

from __future__ import annotations

from pathlib import Path

from scripts.pip_audit_policy import should_run_pip_audit


def _write_work_plan(tmp_path: Path, content: str) -> None:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "work_plan.md").write_text(content, encoding="utf-8")


def test_should_run_pip_audit_no_work_plan(tmp_path):
    run_audit, reason = should_run_pip_audit(tmp_path)
    assert run_audit is True
    assert "not found" in reason


def test_should_run_pip_audit_no_files(tmp_path):
    _write_work_plan(tmp_path, "## Files Likely Touched\n\nNo files here\n---")
    run_audit, reason = should_run_pip_audit(tmp_path)
    assert run_audit is True
    assert "No files found" in reason


def test_should_run_pip_audit_no_dependency_surface(tmp_path):
    content = """
## Files Likely Touched

- `scripts/run_gates_dispatch.py`
- `tests/unit/test_run_gates_dispatch.py`
"""
    _write_work_plan(tmp_path, content)
    run_audit, reason = should_run_pip_audit(tmp_path)
    assert run_audit is False
    assert "No dependency manifests found" in reason


def test_should_run_pip_audit_with_dependency_surface(tmp_path):
    content = """
## Files Likely Touched

- `scripts/run_gates_dispatch.py`
- `pyproject.toml`
"""
    _write_work_plan(tmp_path, content)
    run_audit, reason = should_run_pip_audit(tmp_path)
    assert run_audit is True
    assert "Dependency surface matched" in reason
    assert "pyproject.toml" in reason


def test_should_run_pip_audit_with_requirements_file(tmp_path):
    content = """
## Files Likely Touched
- `requirements-dev.txt`
"""
    _write_work_plan(tmp_path, content)
    run_audit, reason = should_run_pip_audit(tmp_path)
    assert run_audit is True
    assert "requirements-dev.txt" in reason


def test_should_run_pip_audit_with_uv_lock(tmp_path):
    content = """
## Files Likely Touched
- `uv.lock`
"""
    _write_work_plan(tmp_path, content)
    run_audit, reason = should_run_pip_audit(tmp_path)
    assert run_audit is True
    assert "uv.lock" in reason
