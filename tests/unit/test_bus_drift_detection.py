"""Tests for bus drift detection in --validate."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# Add the agent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".agent"))

from agent_controller import _handle_validate, get_plan_id, get_status


class TestBusDriftDetection:
    """Test detection of drift between Markdown state and bus events."""

    @patch('agent_controller.event_bus')
    @patch('agent_controller.read_file')
    @patch('agent_controller.validate_state_files')
    @patch('agent_controller.get_changed_files')
    @patch('agent_controller.check_scope_gate')
    @patch('builtins.print')
    def test_drift_detected_when_states_differ(self, mock_print, mock_gate, mock_changed, mock_validate, mock_read, mock_bus):
        """Test warning when Markdown state differs from bus state."""
        # Mock validation returns no errors
        mock_validate.return_value = {}

        # Mock scope check returns no violations
        mock_gate.return_value = {"valid": True, "out_of_scope": set(), "warnings": []}
        mock_changed.return_value = None  # No git repo

        # Mock log content with READY_FOR_REVIEW
        mock_read.side_effect = lambda path: "**Estado:** READY_FOR_REVIEW" if "execution_log.md" in str(path) else "**ID:** WP-2026-063"

        # Mock bus has different state
        mock_event = MagicMock()
        mock_event.payload = {"state": "IN_PROGRESS"}
        mock_bus.latest_event.return_value = mock_event

        # Call validate
        result = _handle_validate(json_output=False)

        # Assert warning printed
        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")

    @patch('agent_controller.event_bus')
    @patch('agent_controller.read_file')
    @patch('agent_controller.validate_state_files')
    @patch('agent_controller.get_changed_files')
    @patch('agent_controller.check_scope_gate')
    @patch('builtins.print')
    def test_no_drift_when_states_match(self, mock_print, mock_gate, mock_changed, mock_validate, mock_read, mock_bus):
        """Test no warning when Markdown state matches bus state."""
        # Mock validation returns no errors
        mock_validate.return_value = {}

        # Mock scope check returns no violations
        mock_gate.return_value = {"valid": True, "out_of_scope": set(), "warnings": []}
        mock_changed.return_value = None  # No git repo

        # Mock log content with READY_FOR_REVIEW
        mock_read.side_effect = lambda path: "**Estado:** READY_FOR_REVIEW" if "execution_log.md" in str(path) else "**ID:** WP-2026-063"

        # Mock bus has matching state
        mock_event = MagicMock()
        mock_event.payload = {"state": "READY_FOR_REVIEW"}
        mock_bus.latest_event.return_value = mock_event

        # Call validate
        result = _handle_validate(json_output=False)

        # Assert OK printed
        mock_print.assert_any_call("[OK] Todos los archivos de estado son validos.")

    @patch('agent_controller.event_bus')
    @patch('agent_controller.read_file')
    @patch('agent_controller.validate_state_files')
    @patch('agent_controller.get_changed_files')
    @patch('agent_controller.check_scope_gate')
    @patch('builtins.print')
    def test_warning_when_no_bus_event(self, mock_print, mock_gate, mock_changed, mock_validate, mock_read, mock_bus):
        """Test warning when no STATE_CHANGED event exists in bus."""
        # Mock validation returns no errors
        mock_validate.return_value = {}

        # Mock scope check returns no violations
        mock_gate.return_value = {"valid": True, "out_of_scope": set(), "warnings": []}
        mock_changed.return_value = None  # No git repo

        # Mock log content with READY_FOR_REVIEW
        mock_read.side_effect = lambda path: "**Estado:** READY_FOR_REVIEW" if "execution_log.md" in str(path) else "**ID:** WP-2026-063"

        # Mock bus has no event
        mock_bus.latest_event.return_value = None

        # Call validate
        result = _handle_validate(json_output=False)

        # Assert warning printed
        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")

    @patch('agent_controller.event_bus')
    @patch('agent_controller.read_file')
    @patch('agent_controller.validate_state_files')
    @patch('agent_controller.get_changed_files')
    @patch('agent_controller.check_scope_gate')
    @patch('builtins.print')
    def test_warning_when_no_active_ticket(self, mock_print, mock_gate, mock_changed, mock_validate, mock_read, mock_bus):
        """Test warning when no active ticket found."""
        # Mock validation returns no errors
        mock_validate.return_value = {}

        # Since status is READY_FOR_REVIEW, scope check will run, mock it
        mock_gate.return_value = {"valid": True, "out_of_scope": set(), "warnings": []}
        mock_changed.return_value = None  # No git repo

        # Mock log content with READY_FOR_REVIEW but no plan ID
        mock_read.side_effect = lambda path: "**Estado:** READY_FOR_REVIEW" if "execution_log.md" in str(path) else "**ID:** N/A"

        # Call validate
        result = _handle_validate(json_output=False)

        # Assert warning printed
        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")

    @patch('agent_controller.event_bus', None)  # Bus not available
    @patch('agent_controller.read_file')
    @patch('agent_controller.validate_state_files')
    @patch('agent_controller.get_changed_files')
    @patch('agent_controller.check_scope_gate')
    @patch('builtins.print')
    def test_warning_when_bus_unavailable(self, mock_print, mock_gate, mock_changed, mock_validate, mock_read):
        """Test warning when bus is not available."""
        # Mock validation returns no errors
        mock_validate.return_value = {}

        # Mock scope check returns no violations
        mock_gate.return_value = {"valid": True, "out_of_scope": set(), "warnings": []}
        mock_changed.return_value = None  # No git repo

        # Mock log content
        mock_read.side_effect = lambda path: "**Estado:** READY_FOR_REVIEW" if "execution_log.md" in str(path) else "**ID:** WP-2026-063"

        # Call validate
        result = _handle_validate(json_output=False)

        # Assert warning printed
        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")
