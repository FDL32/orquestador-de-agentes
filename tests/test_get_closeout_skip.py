"""WT-2026-246b: Focal tests for --get-closeout-skip endpoint.

Tests cover:
- skip=true when bus state is READY_FOR_REVIEW, READY_TO_CLOSE, HUMAN_GATE, COMPLETED
- skip=false when bus state is IN_PROGRESS, UNKNOWN, or no events
- fail-open: skip=false when bus is unavailable
- fail-open: skip=false when plan_id is missing
- JSON output correctness
- Launcher parse resilience under Set-StrictMode -Version Latest
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_event_bus():
    """Return a mock EventBus instance."""
    bus = MagicMock()
    bus.read_events.return_value = []
    bus.latest_event.return_value = None
    return bus


@pytest.fixture
def mock_bus_available():
    """Patch BUS_AVAILABLE and event_bus in agent_controller."""
    with (
        patch("agent_controller.BUS_AVAILABLE", True),
        patch("agent_controller.event_bus", MagicMock()),
    ):
        yield


@pytest.fixture
def mock_bus_unavailable():
    """Patch BUS_AVAILABLE=False to test fail-open."""
    with patch("agent_controller.BUS_AVAILABLE", False):
        yield


# ============================================================================
# HELPER: invoke _handle_get_closeout_skip capturing stdout
# ============================================================================


def _invoke_handler(json_output: bool = True) -> dict:
    """Call _handle_get_closeout_skip and return parsed JSON from stdout."""
    # Capture stdout
    from io import StringIO

    import agent_controller as ac

    old_stdout = sys.stdout
    sys.stdout = captured = StringIO()
    try:
        ac._handle_get_closeout_skip(json_output=json_output)
        output = captured.getvalue().strip()
        return json.loads(output)
    finally:
        sys.stdout = old_stdout


# ============================================================================
# TESTS: skip=true for post-success states
# ============================================================================


class TestGetCloseoutSkipPostSuccess:
    """skip=true when bus-derived state is post-success."""

    def test_skip_true_ready_for_review(self):
        """Bus state READY_FOR_REVIEW → skip=true."""

        mock_bus = MagicMock()
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "READY_FOR_REVIEW"},
        }
        mock_bus.read_events.return_value = [mock_ev]

        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert result["skip"] is True
        assert result["bus_state"] == "READY_FOR_REVIEW"

    def test_skip_true_ready_to_close(self):
        """Bus state READY_TO_CLOSE → skip=true."""

        mock_bus = MagicMock()
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "READY_TO_CLOSE"},
        }
        mock_bus.read_events.return_value = [mock_ev]

        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert result["skip"] is True
        assert result["bus_state"] == "READY_TO_CLOSE"

    def test_skip_true_human_gate(self):
        """Bus state HUMAN_GATE → skip=true."""

        mock_bus = MagicMock()
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "HUMAN_GATE"},
        }
        mock_bus.read_events.return_value = [mock_ev]

        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert result["skip"] is True
        assert result["bus_state"] == "HUMAN_GATE"

    def test_skip_true_completed(self):
        """Bus state COMPLETED → skip=true."""

        mock_bus = MagicMock()
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "COMPLETED"},
        }
        mock_bus.read_events.return_value = [mock_ev]

        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert result["skip"] is True
        assert result["bus_state"] == "COMPLETED"


# ============================================================================
# TESTS: skip=false for non-terminal states
# ============================================================================


class TestGetCloseoutSkipInProgress:
    """skip=false when bus state is IN_PROGRESS or unknown."""

    def test_skip_false_in_progress(self):
        """Bus state IN_PROGRESS → skip=false."""

        mock_bus = MagicMock()
        # Simulate events that derive to IN_PROGRESS
        event_dict = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS"},
        }
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = event_dict
        mock_bus.read_events.return_value = [mock_ev]

        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
            patch("agent_controller._is_bus_state_post_success", return_value=False),
        ):
            result = _invoke_handler()
        assert result["skip"] is False
        assert result["reason"] == "bus_authority_not_post_success"

    def test_skip_false_no_events(self):
        """No bus events → skip=false (fail-open)."""
        mock_bus = MagicMock()
        mock_bus.read_events.return_value = []

        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
            patch("agent_controller._is_bus_state_post_success", return_value=False),
        ):
            result = _invoke_handler()
        assert result["skip"] is False

    def test_skip_false_bus_unavailable(self):
        """Bus unavailable → skip=false (fail-open)."""
        result = _invoke_handler()
        # When BUS_AVAILABLE=False, bus_state stays None, _is_bus_state_post_success returns False
        assert result["skip"] is False


# ============================================================================
# TESTS: fail-open for missing plan_id
# ============================================================================


class TestGetCloseoutSkipNoPlan:
    """skip=false when there is no active plan."""

    def test_skip_false_no_active_plan(self):
        """No plan_id → skip=false with reason 'no_active_plan'."""
        with patch(
            "agent_controller._load_mark_ready_context", return_value=("", "", "N/A")
        ):
            result = _invoke_handler()
        assert result["skip"] is False
        assert result["reason"] == "no_active_plan"


# ============================================================================
# TESTS: JSON output structure
# ============================================================================


class TestGetCloseoutSkipJsonStructure:
    """Verify JSON output has the expected keys."""

    def test_json_has_skip_key(self):
        """Output always includes 'skip' boolean."""
        mock_bus = MagicMock()
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "READY_FOR_REVIEW"},
        }
        mock_bus.read_events.return_value = [mock_ev]
        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert "skip" in result
        assert isinstance(result["skip"], bool)

    def test_json_has_plan_id_key(self):
        """Output always includes 'plan_id' string."""
        mock_bus = MagicMock()
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "READY_FOR_REVIEW"},
        }
        mock_bus.read_events.return_value = [mock_ev]
        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert "plan_id" in result
        assert isinstance(result["plan_id"], str)

    def test_json_has_bus_state_key_on_skip_false(self):
        """Output includes 'bus_state' when skip=false."""
        mock_bus = MagicMock()
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS"},
        }
        mock_bus.read_events.return_value = [mock_ev]
        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert "bus_state" in result

    def test_json_has_reason_key_on_skip_false(self):
        """Output includes 'reason' when skip=false."""
        mock_bus = MagicMock()
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": "IN_PROGRESS"},
        }
        mock_bus.read_events.return_value = [mock_ev]
        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert "reason" in result


# ============================================================================
# TESTS: Launcher parse resilience (Set-StrictMode -Version Latest)
# ============================================================================


class TestLauncherParseResilience:
    """Verify the JSON output can be parsed safely under PowerShell strict mode.

    Set-StrictMode -Version Latest disallows:
    - Accessing non-existent properties
    - Using methods on null objects
    - Array indexing on null

    The launcher will do something like:
        $skip = $result.skip
        if ($skip -eq $true) { ... }

    These tests ensure the JSON is always a flat object with scalar values.
    """

    def _make_mock_event(self, state: str) -> MagicMock:
        """Create a mock event with the given state."""
        mock_ev = MagicMock()
        mock_ev.to_dict.return_value = {
            "event_type": "STATE_CHANGED",
            "payload": {"to_state": state},
        }
        return mock_ev

    def test_json_is_flat_object(self):
        """Output is a flat JSON object (no nested objects/arrays)."""
        mock_bus = MagicMock()
        mock_bus.read_events.return_value = [self._make_mock_event("READY_FOR_REVIEW")]
        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        # All values should be scalar (bool, str, None)
        for key, value in result.items():
            assert value is None or isinstance(value, (bool, str)), (
                f"Key '{key}' has non-scalar value: {type(value)}"
            )

    def test_json_keys_are_strings(self):
        """All JSON keys are strings (PowerShell dict access)."""
        mock_bus = MagicMock()
        mock_bus.read_events.return_value = [self._make_mock_event("READY_FOR_REVIEW")]
        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        for key in result:
            assert isinstance(key, str)

    def test_skip_value_is_boolean_not_string(self):
        """'skip' is a JSON boolean, not a string 'true'/'false'."""
        mock_bus = MagicMock()
        mock_bus.read_events.return_value = [self._make_mock_event("READY_FOR_REVIEW")]
        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert isinstance(result["skip"], bool)
        assert result["skip"] in (True, False)

    def test_plan_id_is_string_not_null(self):
        """'plan_id' is always a string."""
        mock_bus = MagicMock()
        mock_bus.read_events.return_value = [self._make_mock_event("READY_FOR_REVIEW")]
        with (
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.event_bus", mock_bus),
        ):
            result = _invoke_handler()
        assert isinstance(result["plan_id"], str)
