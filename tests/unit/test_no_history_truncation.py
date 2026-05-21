#!/usr/bin/env python3
"""
Unit tests for the history truncation guard.

Tests cover:
1. Truncation without archive compensation (should fail)
2. Truncation with archive compensation (should pass)
3. Changes below threshold (should pass)
4. Add-only changes (should pass)
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts directory to path for import
scripts_dir = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from check_no_history_truncation import (
    TRUNCATION_THRESHOLD,
    check_archive_compensation,
    check_execution_log_truncation,
    get_line_diff_for_file,
    get_staged_changes,
    main,
    run_git_command,
)


class TestRunGitCommand:
    """Tests for the git command runner."""

    def test_run_git_command_success(self, tmp_path: Path) -> None:
        """Test running a valid git command."""
        # Initialize a git repo for testing
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        result = run_git_command(["rev-parse", "--show-toplevel"], cwd=tmp_path)
        # git returns POSIX-style paths on Windows; normalize both sides for comparison.
        assert Path(result).resolve() == tmp_path.resolve()

    def test_run_git_command_empty_output(self, tmp_path: Path) -> None:
        """Test git command with empty output."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        # diff on empty repo returns empty
        result = run_git_command(["diff", "--cached"], cwd=tmp_path)
        assert result == ""


class TestGetStagedChanges:
    """Tests for staged changes detection."""

    @patch("check_no_history_truncation.run_git_command")
    def test_get_staged_changes_empty(self, mock_git: pytest.MonkeyPatch) -> None:
        """Test when no files are staged."""
        mock_git.return_value = ""
        result = get_staged_changes()
        assert result == []

    @patch("check_no_history_truncation.run_git_command")
    def test_get_staged_changes_with_files(self, mock_git: pytest.MonkeyPatch) -> None:
        """Test parsing staged files."""
        mock_git.return_value = "A\tfile1.py\nM\tfile2.py\nD\tfile3.py"
        result = get_staged_changes()
        assert len(result) == 3
        assert "A\tfile1.py" in result
        assert "M\tfile2.py" in result
        assert "D\tfile3.py" in result


class TestGetLineDiffForFile:
    """Tests for line diff calculation."""

    @patch("check_no_history_truncation.run_git_command")
    def test_get_line_diff_normal(self, mock_git: pytest.MonkeyPatch) -> None:
        """Test parsing normal numstat output."""
        mock_git.return_value = "10\t5\texecution_log.md"
        added, removed = get_line_diff_for_file("execution_log.md")
        assert added == 10
        assert removed == 5

    @patch("check_no_history_truncation.run_git_command")
    def test_get_line_diff_empty(self, mock_git: pytest.MonkeyPatch) -> None:
        """Test when file has no diff."""
        mock_git.return_value = ""
        added, removed = get_line_diff_for_file("execution_log.md")
        assert added == 0
        assert removed == 0

    @patch("check_no_history_truncation.run_git_command")
    def test_get_line_diff_binary(self, mock_git: pytest.MonkeyPatch) -> None:
        """Test handling of binary file markers."""
        mock_git.return_value = "-\t-\tbinary.bin"
        added, removed = get_line_diff_for_file("binary.bin")
        assert added == 0
        assert removed == 0


class TestCheckExecutionLogTruncation:
    """Tests for truncation detection logic."""

    @patch("check_no_history_truncation.get_staged_changes")
    @patch("check_no_history_truncation.get_line_diff_for_file")
    def test_no_truncation_file_not_staged(
        self, mock_diff: pytest.MonkeyPatch, mock_staged: pytest.MonkeyPatch
    ) -> None:
        """Test when execution_log.md is not in staged changes."""
        mock_staged.return_value = ["A\tother_file.py"]
        mock_diff.return_value = (0, 0)
        is_truncated, added, removed = check_execution_log_truncation()
        assert is_truncated is False
        assert added == 0
        assert removed == 0

    @patch("check_no_history_truncation.get_staged_changes")
    @patch("check_no_history_truncation.get_line_diff_for_file")
    def test_truncation_detected(
        self, mock_diff: pytest.MonkeyPatch, mock_staged: pytest.MonkeyPatch
    ) -> None:
        """Test detection of dangerous truncation."""
        mock_staged.return_value = ["M\texecution_log.md"]
        # Remove 100 lines, add 5 (net loss of 95)
        mock_diff.return_value = (5, 100)
        is_truncated, added, removed = check_execution_log_truncation()
        assert is_truncated is True
        assert added == 5
        assert removed == 100

    @patch("check_no_history_truncation.get_staged_changes")
    @patch("check_no_history_truncation.get_line_diff_for_file")
    def test_below_threshold(
        self, mock_diff: pytest.MonkeyPatch, mock_staged: pytest.MonkeyPatch
    ) -> None:
        """Test that small changes pass."""
        mock_staged.return_value = ["M\texecution_log.md"]
        # Remove 30 lines (below 50 threshold)
        mock_diff.return_value = (5, 30)
        is_truncated, added, removed = check_execution_log_truncation()
        assert is_truncated is False

    @patch("check_no_history_truncation.get_staged_changes")
    @patch("check_no_history_truncation.get_line_diff_for_file")
    def test_add_only_no_truncation(
        self, mock_diff: pytest.MonkeyPatch, mock_staged: pytest.MonkeyPatch
    ) -> None:
        """Test that add-only changes pass."""
        mock_staged.return_value = ["M\texecution_log.md"]
        # Add 50 lines, remove 0
        mock_diff.return_value = (50, 0)
        is_truncated, added, removed = check_execution_log_truncation()
        assert is_truncated is False

    @patch("check_no_history_truncation.get_staged_changes")
    @patch("check_no_history_truncation.get_line_diff_for_file")
    def test_boundary_exactly_50_lines(
        self, mock_diff: pytest.MonkeyPatch, mock_staged: pytest.MonkeyPatch
    ) -> None:
        """Test boundary case: exactly 50 lines removed."""
        mock_staged.return_value = ["M\texecution_log.md"]
        # Remove exactly 50 lines (threshold), add 0
        mock_diff.return_value = (0, 50)
        is_truncated, added, removed = check_execution_log_truncation()
        # 50 > 50 is False, so should not be truncated
        assert is_truncated is False

    @patch("check_no_history_truncation.get_staged_changes")
    @patch("check_no_history_truncation.get_line_diff_for_file")
    def test_boundary_51_lines(
        self, mock_diff: pytest.MonkeyPatch, mock_staged: pytest.MonkeyPatch
    ) -> None:
        """Test boundary case: 51 lines removed."""
        mock_staged.return_value = ["M\texecution_log.md"]
        # Remove 51 lines (just above threshold), add 0
        mock_diff.return_value = (0, 51)
        is_truncated, added, removed = check_execution_log_truncation()
        # 51 > 50 is True, and 51 > 0, so should be truncated
        assert is_truncated is True


class TestCheckArchiveCompensation:
    """Tests for archive compensation detection."""

    @patch("check_no_history_truncation.get_staged_changes")
    def test_no_archive_files(self, mock_staged: pytest.MonkeyPatch) -> None:
        """Test when no archive files are staged."""
        mock_staged.return_value = ["M\texecution_log.md", "A\tother.py"]
        result = check_archive_compensation()
        assert result is False

    @patch("check_no_history_truncation.get_staged_changes")
    def test_archive_file_added(self, mock_staged: pytest.MonkeyPatch) -> None:
        """Test detection of archive file being added."""
        mock_staged.return_value = [
            "M\texecution_log.md",
            "A\t.agent/collaboration/archive/execution_log_2026-05.md",
        ]
        result = check_archive_compensation()
        assert result is True

    @patch("check_no_history_truncation.get_staged_changes")
    def test_archive_file_renamed(self, mock_staged: pytest.MonkeyPatch) -> None:
        """Test detection of an execution_log archive file being added."""
        # Canonical archive lives under .agent/collaboration/archive/ per
        # scripts/archive_execution_log.py; rename status (R) into that path
        # also counts as compensation.
        mock_staged.return_value = [
            "M\texecution_log.md",
            "R100\told_path.md\t.agent/collaboration/archive/execution_log_2026-05.md",
        ]
        result = check_archive_compensation()
        assert result is True


class TestMainFunction:
    """Tests for the main entry point."""

    @patch("check_no_history_truncation.check_execution_log_truncation")
    @patch("check_no_history_truncation.check_archive_compensation")
    def test_main_no_truncation(
        self, mock_archive: pytest.MonkeyPatch, mock_trunc: pytest.MonkeyPatch
    ) -> None:
        """Test main returns 0 when no truncation."""
        mock_trunc.return_value = (False, 0, 0)
        result = main()
        assert result == 0
        mock_archive.assert_not_called()

    @patch("check_no_history_truncation.check_execution_log_truncation")
    @patch("check_no_history_truncation.check_archive_compensation")
    def test_main_truncation_with_archive(
        self, mock_archive: pytest.MonkeyPatch, mock_trunc: pytest.MonkeyPatch
    ) -> None:
        """Test main returns 0 when truncation has archive compensation."""
        mock_trunc.return_value = (True, 5, 100)
        mock_archive.return_value = True
        result = main()
        assert result == 0
        mock_archive.assert_called_once()

    @patch("check_no_history_truncation.check_execution_log_truncation")
    @patch("check_no_history_truncation.check_archive_compensation")
    def test_main_truncation_without_archive(
        self, mock_archive: pytest.MonkeyPatch, mock_trunc: pytest.MonkeyPatch
    ) -> None:
        """Test main returns 1 when truncation lacks archive compensation."""
        mock_trunc.return_value = (True, 5, 100)
        mock_archive.return_value = False
        result = main()
        assert result == 1
        mock_archive.assert_called_once()


class TestIntegration:
    """Integration tests with actual git operations."""

    def test_threshold_constant_is_50(self) -> None:
        """Verify the truncation threshold is set to 50 lines."""
        assert TRUNCATION_THRESHOLD == 50
