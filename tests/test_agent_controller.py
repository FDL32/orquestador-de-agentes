"""Minimal tests for agent_controller.py canonical functions.

Only tests functions that exist in the canonical controller:
- read_file
- write_file
- validate_state_files
- determine_next_action
- should_overwrite_turn
- update_log_status
- run_quality_gates

Full test suite for removed functions (normalize_*, mark_*, perform_*,
request_*, get_rejection_*, publish_*) can be restored when those
functions are implemented.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# Add .agent to path for imports
agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

import agent_controller  # noqa: E402
from agent_controller import (  # noqa: E402
    determine_next_action,
    read_file,
    run_quality_gates,
    should_overwrite_turn,
    update_log_status,
    validate_state_files,
    write_file,
)


class TestReadFile:
    """Test read_file handles filesystem correctly."""

    def test_read_file_existing_path(self, tmp_path):
        """read_file returns content from existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = read_file(test_file)
        assert result == "test content"

    def test_read_file_missing_path(self, tmp_path):
        """read_file returns empty string for missing file."""
        missing_file = tmp_path / "missing.txt"

        result = read_file(missing_file)
        assert result == ""


class TestWriteFile:
    """Test write_file creates and updates files."""

    def test_write_file_creates_new(self, tmp_path):
        """write_file creates new file with content."""
        test_file = tmp_path / "new.txt"
        write_file(test_file, "new content")

        assert test_file.exists()
        assert test_file.read_text() == "new content"

    def test_write_file_overwrites_existing(self, tmp_path):
        """write_file overwrites existing file."""
        test_file = tmp_path / "existing.txt"
        test_file.write_text("old content")

        write_file(test_file, "new content")

        assert test_file.read_text() == "new content"

    def test_write_file_creates_parent_dirs(self, tmp_path):
        """write_file creates parent directories if needed."""
        test_file = tmp_path / "subdir" / "nested" / "file.txt"
        write_file(test_file, "nested content")

        assert test_file.exists()
        assert test_file.read_text() == "nested content"


class TestValidateStateFiles:
    """Test validate_state_files checks state consistency."""

    def test_validate_returns_dict_with_keys(self):
        """validate_state_files returns proper error dict structure."""
        with patch("agent_controller.read_file", return_value=""):
            errors = validate_state_files()

        # Should have these keys
        assert "work_plan.md" in errors
        assert "execution_log.md" in errors
        assert "TURN.md" in errors
        assert "consistency" in errors

    def test_validate_detects_missing_section(self):
        """validate_state_files detects missing required sections."""
        with (
            patch("agent_controller.read_file", return_value="# Empty file\n"),
            patch(
                "agent_controller.TURN_FILE",
                MagicMock(exists=MagicMock(return_value=True)),
            ),
        ):
            errors = validate_state_files()

        # Should detect missing sections
        assert len(errors["TURN.md"]) > 0 or len(errors["consistency"]) > 0


class TestDetermineNextAction:
    """Test determine_next_action analyzes state and returns action."""

    def test_determine_next_action_returns_dict(self):
        """determine_next_action returns proper action dict."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch("agent_controller.HOOKS_AVAILABLE", False),
        ):
            action = determine_next_action(skip_gates=True)

        # Should return dict with role and action_type
        assert isinstance(action, dict)
        assert "role" in action


class TestShouldOverwriteTurn:
    """Test should_overwrite_turn determines if TURN.md needs reset."""

    def test_should_overwrite_turn_returns_bool(self):
        """should_overwrite_turn returns boolean."""
        with patch.object(Path, "exists", return_value=False):
            result = should_overwrite_turn(Path("/fake/TURN.md"))

        assert isinstance(result, bool)


class TestUpdateLogStatus:
    """Test update_log_status modifies execution log."""

    def test_update_log_status_returns_bool(self):
        """update_log_status returns success boolean."""
        with (
            patch("agent_controller.read_file", return_value="# Execution Log\n"),
            patch("agent_controller.write_file"),
        ):
            result = update_log_status("IN_PROGRESS", "test note")

        assert isinstance(result, bool)


class TestRunQualityGates:
    """Test run_quality_gates executes validation checks."""

    def test_run_quality_gates_returns_dict(self):
        """run_quality_gates returns result dict with expected keys."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch("agent_controller.subprocess"),
        ):
            result = run_quality_gates()

        assert isinstance(result, dict)
        # Should have standard result keys: errors, passed, summary, warnings
        assert "passed" in result
        assert "summary" in result


class TestHumanGateThreshold:
    """WP-2026-106 B-fix: HUMAN_GATE threshold is a single source of truth."""

    def test_threshold_reads_from_agents_config(self, tmp_path, monkeypatch):
        """get_human_gate_threshold reads manager_review.max_attempts."""
        import json

        cfg = tmp_path / "agents.json"
        cfg.write_text(
            json.dumps({"manager_review": {"max_attempts": 5}}), encoding="utf-8"
        )
        monkeypatch.setattr(agent_controller, "AGENTS_CONFIG_PATH", cfg)
        assert agent_controller.get_human_gate_threshold() == 5

    def test_threshold_falls_back_when_config_missing(self, tmp_path, monkeypatch):
        """Missing config -> safe fallback, never the legacy hardcoded 3."""
        monkeypatch.setattr(
            agent_controller, "AGENTS_CONFIG_PATH", tmp_path / "absent.json"
        )
        result = agent_controller.get_human_gate_threshold()
        assert result == agent_controller.HUMAN_GATE_REJECTION_FALLBACK
        assert result != 3

    def test_threshold_falls_back_on_malformed_config(self, tmp_path, monkeypatch):
        """Malformed JSON -> fallback, no exception."""
        bad = tmp_path / "agents.json"
        bad.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(agent_controller, "AGENTS_CONFIG_PATH", bad)
        assert (
            agent_controller.get_human_gate_threshold()
            == agent_controller.HUMAN_GATE_REJECTION_FALLBACK
        )
