"""Tests for bus drift detection in --validate."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent_controller import _handle_validate  # noqa: E402


def _mock_read_file(path):
    if "execution_log.md" in str(path):
        return "**Estado:** READY_FOR_REVIEW"
    if "work_plan.md" in str(path):
        return "**ID:** WP-2026-063\n**Estado:** APPROVED\ndeliverable_type: code"
    return "**ID:** WP-2026-063"


def _mock_read_file_no_ticket(path):
    if "execution_log.md" in str(path):
        return "**Estado:** READY_FOR_REVIEW"
    if "work_plan.md" in str(path):
        return "**ID:** N/A"
    return "**ID:** N/A"


class TestBusDriftDetection:
    """Test detection of drift between Markdown state and bus events."""

    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus")
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_drift_detected_when_states_differ(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_bus,
        mock_deliverable,
        mock_scope,
        mock_invariants,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file

        mock_event = MagicMock()
        mock_event.payload = {"to_state": "IN_PROGRESS"}
        mock_bus.latest_event.return_value = mock_event

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")

    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus")
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_no_drift_when_states_match(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_bus,
        mock_deliverable,
        mock_scope,
        mock_invariants,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file

        mock_event = MagicMock()
        mock_event.payload = {"to_state": "READY_FOR_REVIEW"}
        mock_bus.latest_event.return_value = mock_event

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[OK] Todos los archivos de estado son validos.")

    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus")
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_warning_when_no_bus_event(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_bus,
        mock_deliverable,
        mock_scope,
        mock_invariants,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file

        mock_bus.latest_event.return_value = None

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")

    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus")
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_warning_when_no_active_ticket(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_bus,
        mock_deliverable,
        mock_scope,
        mock_invariants,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file_no_ticket

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")

    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus", None)
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_warning_when_bus_unavailable(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_deliverable,
        mock_scope,
        mock_invariants,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")
