#!/usr/bin/env python3
"""Tests for prepush_check.py - delivery preflight wrapper.

Tests cover three main scenarios:
(a) Clean path - all five checks pass, exit 0, tree unchanged
(b) Dirty tree path - git status --short returns output, exit 1
(c) Mutating hook in pre-push detected by delivery_hygiene_check, exit 1

Uses monkeypatch and tmp_path to isolate subprocess calls and git operations.
No test mutates the real filesystem.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.prepush_check import (
    CheckResult,
    run_agent_controller_validate,
    run_delivery_hygiene_check,
    run_git_status_check,
    run_preflight_check,
    run_ruff_check,
    run_ruff_format_check,
    run_validate_all,
)


class TestDeliveryHygieneCheck:
    """Tests for delivery_hygiene_check integration."""

    def test_delivery_hygiene_import_error(self, tmp_path: Path) -> None:
        """Test when delivery_hygiene_check module cannot be imported."""
        # Simulate ImportError by patching the import to fail
        with patch.dict("sys.modules", {"scripts.delivery_hygiene_check": None}):
            result = run_delivery_hygiene_check(tmp_path)

        assert result.name == "Delivery Hygiene Check"
        assert result.passed is False
        assert "Error importando" in result.output
        assert result.is_blocking is True


class TestRuffCheck:
    """Tests for ruff check integration."""

    def test_ruff_check_passes(self, tmp_path: Path) -> None:
        """Test when ruff check passes."""
        mock_result = subprocess.CompletedProcess(
            args=["ruff", "check", "."],
            returncode=0,
            stdout="",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_ruff_check(tmp_path)

        assert result.name == "Ruff Check"
        assert result.passed is True
        assert result.is_blocking is True

    def test_ruff_check_fails(self, tmp_path: Path) -> None:
        """Test when ruff check fails."""
        mock_result = subprocess.CompletedProcess(
            args=["ruff", "check", "."],
            returncode=1,
            stdout="E501 Line too long\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_ruff_check(tmp_path)

        assert result.name == "Ruff Check"
        assert result.passed is False
        assert "E501" in result.output
        assert result.is_blocking is True

    def test_ruff_check_not_found(self, tmp_path: Path) -> None:
        """Test when ruff command is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError("ruff")):
            result = run_ruff_check(tmp_path)

        assert result.name == "Ruff Check"
        assert result.passed is False
        assert "no encontrado" in result.output
        assert result.is_blocking is True


class TestRuffFormatCheck:
    """Tests for ruff format --check integration."""

    def test_ruff_format_passes(self, tmp_path: Path) -> None:
        """Test when ruff format --check passes."""
        mock_result = subprocess.CompletedProcess(
            args=["ruff", "format", "--check", "."],
            returncode=0,
            stdout="",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_ruff_format_check(tmp_path)

        assert result.name == "Ruff Format Check"
        assert result.passed is True
        assert result.is_blocking is True

    def test_ruff_format_fails(self, tmp_path: Path) -> None:
        """Test when ruff format --check fails."""
        mock_result = subprocess.CompletedProcess(
            args=["ruff", "format", "--check", "."],
            returncode=1,
            stdout="Would reformat: file.py\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_ruff_format_check(tmp_path)

        assert result.name == "Ruff Format Check"
        assert result.passed is False
        assert "Would reformat" in result.output
        assert result.is_blocking is True


class TestAgentControllerValidate:
    """Tests for agent_controller --validate integration."""

    def test_controller_validate_passes(self, tmp_path: Path) -> None:
        """Test when agent_controller --validate passes."""
        mock_result = subprocess.CompletedProcess(
            args=[
                "python",
                ".agent/agent_controller.py",
                "--validate",
                "--json",
                "--force",
            ],
            returncode=0,
            stdout='{"status": "valid"}\n',
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_agent_controller_validate(tmp_path)

        assert result.name == "Agent Controller Validate"
        assert result.passed is True
        assert result.is_blocking is True

    def test_controller_validate_fails(self, tmp_path: Path) -> None:
        """Test when agent_controller --validate fails."""
        mock_result = subprocess.CompletedProcess(
            args=[
                "python",
                ".agent/agent_controller.py",
                "--validate",
                "--json",
                "--force",
            ],
            returncode=1,
            stdout="",
            stderr="Validation error: work_plan.md missing\n",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_agent_controller_validate(tmp_path)

        assert result.name == "Agent Controller Validate"
        assert result.passed is False
        assert "Validation error" in result.output
        assert result.is_blocking is True


class TestGitStatusCheck:
    """Tests for git status --short integration."""

    def test_git_status_clean(self, tmp_path: Path) -> None:
        """Test when git status shows clean tree."""
        mock_result = subprocess.CompletedProcess(
            args=["git", "status", "--short"],
            returncode=0,
            stdout="",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_git_status_check(tmp_path)

        assert result.name == "Git Status Check"
        assert result.passed is True
        assert "limpio" in result.output
        assert result.is_blocking is True

    def test_git_status_dirty(self, tmp_path: Path) -> None:
        """Test when git status shows dirty tree."""
        mock_result = subprocess.CompletedProcess(
            args=["git", "status", "--short"],
            returncode=0,
            stdout="M scripts/prepush_check.py\n?? tests/test_prepush_check.py\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_git_status_check(tmp_path)

        assert result.name == "Git Status Check"
        assert result.passed is False
        assert "sucio" in result.output
        assert "scripts/prepush_check.py" in result.output
        assert result.is_blocking is True

    def test_git_status_command_not_found(self, tmp_path: Path) -> None:
        """Test when git command is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError("git")):
            result = run_git_status_check(tmp_path)

        assert result.name == "Git Status Check"
        assert result.passed is False
        assert "no encontrado" in result.output
        assert result.is_blocking is True

    def test_git_status_command_error(self, tmp_path: Path) -> None:
        """Test when git status returns non-zero exit code."""
        mock_result = subprocess.CompletedProcess(
            args=["git", "status", "--short"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_git_status_check(tmp_path)

        assert result.name == "Git Status Check"
        assert result.passed is False
        assert "Error ejecutando git status" in result.output
        assert "exit 128" in result.output
        assert result.is_blocking is True


class TestValidateAll:
    """Tests for skills/validate_all.py integration."""

    def test_validate_all_passes(self, tmp_path: Path) -> None:
        """Test when validate_all passes."""
        mock_result = subprocess.CompletedProcess(
            args=["python", "skills/validate_all.py"],
            returncode=0,
            stdout="All validations passed\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_validate_all(tmp_path)

        assert result.name == "Validate All (informacional)"
        assert result.passed is True
        assert result.is_blocking is False  # Non-blocking

    def test_validate_all_fails(self, tmp_path: Path) -> None:
        """Test when validate_all fails - still non-blocking."""
        mock_result = subprocess.CompletedProcess(
            args=["python", "skills/validate_all.py"],
            returncode=1,
            stdout="",
            stderr="Validation failed\n",
        )

        with patch("subprocess.run", return_value=mock_result):
            result = run_validate_all(tmp_path)

        assert result.name == "Validate All (informacional)"
        assert result.passed is False
        assert result.is_blocking is False  # Still non-blocking


class TestPreflightCheckIntegration:
    """Integration tests for the full preflight check."""

    def test_clean_path_all_checks_pass(self, tmp_path: Path) -> None:
        """Test clean path: all five blocking checks pass, exit 0."""
        # Mock all the individual check functions to return passing CheckResults
        mock_result = CheckResult(name="Mock", passed=True, output="OK")

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_result,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_result),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_result
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_result,
            ),
            patch(
                "scripts.prepush_check.run_git_status_check", return_value=mock_result
            ),
            patch("scripts.prepush_check.run_validate_all", return_value=mock_result),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 0

    def test_dirty_tree_path(self, tmp_path: Path) -> None:
        """Test dirty tree path: git status returns output, exit 1."""
        mock_pass = CheckResult(name="Mock", passed=True, output="OK")
        mock_fail = CheckResult(
            name="Git Status", passed=False, output="Dirty", is_blocking=True
        )

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_pass),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_pass
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_git_status_check", return_value=mock_fail),
            patch("scripts.prepush_check.run_validate_all", return_value=mock_pass),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 1

    def test_mutating_hook_in_prepush(self, tmp_path: Path) -> None:
        """Test mutating hook in pre-push detected by delivery_hygiene_check, exit 1."""
        mock_pass = CheckResult(name="Mock", passed=True, output="OK")
        mock_fail = CheckResult(
            name="Delivery Hygiene",
            passed=False,
            output="Mutator detected",
            is_blocking=True,
        )

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_fail,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_pass),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_pass
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_git_status_check", return_value=mock_pass),
            patch("scripts.prepush_check.run_validate_all", return_value=mock_pass),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 1

    def test_ruff_check_failure_blocks(self, tmp_path: Path) -> None:
        """Test that ruff check failure blocks the preflight."""
        mock_pass = CheckResult(name="Mock", passed=True, output="OK")
        mock_fail = CheckResult(
            name="Ruff", passed=False, output="E501", is_blocking=True
        )

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_fail),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_pass
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_git_status_check", return_value=mock_pass),
            patch("scripts.prepush_check.run_validate_all", return_value=mock_pass),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 1

    def test_validate_all_failure_does_not_block(self, tmp_path: Path) -> None:
        """Test that validate_all failure does not block the preflight."""
        mock_pass = CheckResult(name="Mock", passed=True, output="OK")
        mock_fail_nonblocking = CheckResult(
            name="Validate All", passed=False, output="Failed", is_blocking=False
        )

        with (
            patch(
                "scripts.prepush_check.run_delivery_hygiene_check",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_ruff_check", return_value=mock_pass),
            patch(
                "scripts.prepush_check.run_ruff_format_check", return_value=mock_pass
            ),
            patch(
                "scripts.prepush_check.run_agent_controller_validate",
                return_value=mock_pass,
            ),
            patch("scripts.prepush_check.run_git_status_check", return_value=mock_pass),
            patch(
                "scripts.prepush_check.run_validate_all",
                return_value=mock_fail_nonblocking,
            ),
        ):
            exit_code = run_preflight_check(tmp_path)

        assert exit_code == 0  # validate_all is non-blocking


class TestCheckResult:
    """Tests for CheckResult named tuple."""

    def test_check_result_creation(self) -> None:
        """Test CheckResult can be created with default values."""
        result = CheckResult(
            name="Test Check",
            passed=True,
            output="All good",
        )

        assert result.name == "Test Check"
        assert result.passed is True
        assert result.output == "All good"
        assert result.is_blocking is True

    def test_check_result_non_blocking(self) -> None:
        """Test CheckResult can be created as non-blocking."""
        result = CheckResult(
            name="Informacional",
            passed=False,
            output="Failed but ok",
            is_blocking=False,
        )

        assert result.is_blocking is False
