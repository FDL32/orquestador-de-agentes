"""Tests for WOT-2026-131a: pip-audit hook interpreter alignment.

Verifies that the pip-audit pre-commit hook runs with the project
interpreter via `uv run` (language: system) and that the wrapper
fails closed when the running interpreter does not match the
requires-python floor while the uv.lock export carries python
version markers.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from scripts import pip_audit_project


# ---------------------------------------------------------------------
# Hook configuration tests
# ---------------------------------------------------------------------


@pytest.fixture()
def hook_cfg():
    """Load the .pre-commit-config.yaml and return the pip-audit hook dict."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    cfg_path = repo_root / ".pre-commit-config.yaml"
    with open(cfg_path) as fh:
        cfg = yaml.safe_load(fh)
    for repo in cfg["repos"]:
        for hook in repo.get("hooks", []):
            if hook.get("id") == "pip-audit":
                return hook
    raise ValueError("pip-audit hook not found in .pre-commit-config.yaml")


class TestHookConfig:
    """Tests 1-4: hook configuration must match the plan."""

    def test_hook_runs_in_project_interpreter_not_isolated_venv(self, hook_cfg):
        assert hook_cfg["language"] == "system"

    def test_hook_entry_goes_through_uv_run_to_the_wrapper(self, hook_cfg):
        entry_parts = shlex.split(hook_cfg["entry"])
        assert entry_parts[0:2] == ["uv", "run"]
        assert "--frozen" in entry_parts
        assert entry_parts[-2:] == ["python", "scripts/pip_audit_project.py"]

    def test_hook_declares_no_isolated_env_dependencies(self, hook_cfg):
        assert "additional_dependencies" not in hook_cfg

    def test_hook_stages_unchanged(self, hook_cfg):
        assert set(hook_cfg["stages"]) == {"pre-push", "manual"}
        assert hook_cfg["pass_filenames"] is False


# ---------------------------------------------------------------------
# Wrapper guard tests
# ---------------------------------------------------------------------


class TestGuardFunctions:
    """Tests 5-11: guard functions on _requires_python_floor,
    _export_has_python_markers, _running_version,
    and _interpreter_problem."""

    def test_floor_parsed_from_requires_python(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nrequires-python = ">=3.10,<3.14"\n',
            encoding="utf-8",
        )
        assert pip_audit_project._requires_python_floor(tmp_path) == (3, 10)

        pyproject.write_text(
            '[project]\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
        )
        assert pip_audit_project._requires_python_floor(tmp_path) == (3, 11)

        # Real repo root => (3, 10)
        repo_root = Path(__file__).resolve().parent.parent.parent
        assert pip_audit_project._requires_python_floor(repo_root) == (3, 10)

    def test_floor_none_when_requires_python_missing_or_not_a_lower_bound(
        self, tmp_path
    ):
        # No pyproject
        assert pip_audit_project._requires_python_floor(tmp_path) is None

        # pyproject without requires-python
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        assert pip_audit_project._requires_python_floor(tmp_path) is None

        # Not a lower bound
        pyproject.write_text(
            '[project]\nrequires-python = "<3.14"\n',
            encoding="utf-8",
        )
        assert pip_audit_project._requires_python_floor(tmp_path) is None

    def test_marker_detection(self):
        assert (
            pip_audit_project._export_has_python_markers(
                "pkg==1.0 ; python_full_version < '3.11'\n"
            )
            is True
        )
        assert (
            pip_audit_project._export_has_python_markers(
                'pkg==1.0 ; python_version >= "3.9"\n'
            )
            is True
        )
        assert (
            pip_audit_project._export_has_python_markers(
                "pkg==1.0 ; sys_platform == 'win32'\n"
            )
            is False
        )
        assert pip_audit_project._export_has_python_markers("pkg==1.0\n") is False
        assert (
            pip_audit_project._export_has_python_markers("# python_version\npkg==1.0\n")
            is False
        )

    def test_guard_rejects_non_floor_interpreter_when_markers_present(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nrequires-python = ">=3.10,<3.14"\n',
            encoding="utf-8",
        )
        msg = pip_audit_project._interpreter_problem(
            tmp_path, "pkg==1.0 ; python_full_version < '3.11'", (3, 12, 10)
        )
        assert msg != ""
        assert "3.12.10" in msg
        assert "3.10" in msg

    def test_guard_accepts_floor_interpreter_when_markers_present(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nrequires-python = ">=3.10,<3.14"\n',
            encoding="utf-8",
        )
        msg = pip_audit_project._interpreter_problem(
            tmp_path, "pkg==1.0 ; python_full_version < '3.11'", (3, 10, 19)
        )
        assert msg is None

    def test_guard_ignores_interpreter_when_no_markers(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nrequires-python = ">=3.10,<3.14"\n',
            encoding="utf-8",
        )
        msg = pip_audit_project._interpreter_problem(
            tmp_path, "pkg==1.0\npkg2==2.0\n", (3, 12, 10)
        )
        assert msg is None

    def test_guard_fails_closed_when_floor_unknown_and_markers_present(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nrequires-python = "<3.14"\n',
            encoding="utf-8",
        )
        floor = pip_audit_project._requires_python_floor(tmp_path)
        assert floor is None
        version = pip_audit_project._running_version()
        msg = pip_audit_project._interpreter_problem(
            tmp_path,
            "pkg==1.0 ; python_full_version < '3.11'\n",
            version,
        )
        assert msg is not None and "indeterminable" in msg

        # Without markers => None
        msg2 = pip_audit_project._interpreter_problem(tmp_path, "pkg==1.0\n", version)
        assert msg2 is None


# ---------------------------------------------------------------------
# main() end-to-end tests with mocked subprocess
# ---------------------------------------------------------------------


class TestMainMocked:
    """Tests 12-13: main() respects the interpreter guard."""

    def test_main_blocks_before_auditing_on_simulated_python_312(
        self, tmp_path, monkeypatch, capsys
    ):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nrequires-python = ">=3.10,<3.14"\n',
            encoding="utf-8",
        )

        def mock_which(name):
            return "uv"

        def mock_run(cmd, **kwargs):
            if "export" in cmd:
                output_file_idx = cmd.index("--output-file")
                output_file = Path(cmd[output_file_idx + 1])
                output_file.write_text(
                    "pkg==1.0 ; python_full_version < '3.11'\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(
                    cmd, returncode=0, stdout="", stderr=""
                )
            raise AssertionError(
                "pip-audit command must NOT be executed after guard blocks"
            )

        with (
            patch.object(pip_audit_project.shutil, "which", mock_which),
            patch.object(pip_audit_project.subprocess, "run", mock_run),
            patch.object(
                pip_audit_project,
                "_running_version",
                return_value=(3, 12, 10),
            ),
        ):
            rc = pip_audit_project.main()

        assert rc != 0
        stderr = capsys.readouterr().err
        assert "3.12.10" in stderr

    def test_main_audits_on_floor_interpreter_and_reports_version(
        self, tmp_path, monkeypatch, capsys
    ):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nrequires-python = ">=3.10,<3.14"\n',
            encoding="utf-8",
        )

        audit_cmd_received = []

        def mock_which(name):
            return "uv"

        def mock_run(cmd, **kwargs):
            if "export" in cmd:
                return subprocess.CompletedProcess(
                    cmd, returncode=0, stdout="", stderr=""
                )
            audit_cmd_received.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        with (
            patch.object(pip_audit_project.shutil, "which", mock_which),
            patch.object(pip_audit_project.subprocess, "run", mock_run),
            patch.object(
                pip_audit_project,
                "_running_version",
                return_value=(3, 10, 19),
            ),
        ):
            rc = pip_audit_project.main()

        assert rc == 0
        stdout = capsys.readouterr().out
        assert "3.10.19" in stdout
        assert any("-m" in c and "pip_audit" in c for c in audit_cmd_received)
