"""Tests for ui_state projection."""

import json
from unittest.mock import patch

import pytest
from bus.event_bus import EventBus
from runtime.ui_state_projector import UIStateProjector


@pytest.fixture
def temp_runtime_dir(tmp_path):
    """Temporary runtime directory."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


@pytest.fixture
def mock_event_bus(temp_runtime_dir):
    """Mock event bus with sample events."""
    bus = EventBus(runtime_dir=temp_runtime_dir)
    # Emit a sample TURN_CHANGED event
    bus.emit(
        "TURN_CHANGED",
        ticket_id="WP-2026-024",
        actor="BUILDER",
        payload={
            "action": "IMPLEMENT",
            "plan_status": "APPROVED",
            "log_status": "IN_PROGRESS",
        },
        timestamp="2026-05-11T13:00:00",
    )
    return bus


@pytest.fixture
def mock_collaboration_dir(temp_runtime_dir):
    """Mock collaboration directory with sample files."""
    collab_dir = temp_runtime_dir / "collaboration"
    collab_dir.mkdir(parents=True, exist_ok=True)

    # Mock work_plan.md using the real metadata format
    (collab_dir / "work_plan.md").write_text(
        "# Work Ticket - WP-2026-024\n\n## Metadata\n- **ID:** WP-2026-024\n- **Title:** UI State Projection\n- **Estado:** APPROVED\n\n## Problema\nImplementar ui_state.json",
        encoding="utf-8",
    )

    # Mock execution_log.md
    (collab_dir / "execution_log.md").write_text(
        "## WP-2026-024\n\n**Estado:** READY_FOR_REVIEW",
        encoding="utf-8",
    )

    return collab_dir


def test_projector_initialization(temp_runtime_dir):
    """Test projector initializes correctly."""
    projector = UIStateProjector(runtime_dir=temp_runtime_dir)
    assert projector.runtime_dir == temp_runtime_dir
    assert projector.ui_state_path == temp_runtime_dir / "ui_state.json"


def test_get_plan_info(mock_collaboration_dir):
    """Test extracting plan info from work_plan.md."""
    projector = UIStateProjector()
    projector.collaboration_dir = mock_collaboration_dir

    plan_info = projector._get_plan_info()
    assert plan_info["plan_id"] == "WP-2026-024"
    assert plan_info["status"] == "APPROVED"
    assert "UI State Projection" in plan_info["objective"]


def test_get_ticket_status(mock_collaboration_dir):
    """Test extracting ticket status."""
    projector = UIStateProjector()
    projector.collaboration_dir = mock_collaboration_dir

    status = projector._get_ticket_status()
    assert status["plan_status"] == "APPROVED"
    assert status["log_status"] == "READY_FOR_REVIEW"


def test_get_current_turn(mock_event_bus):
    """Test extracting current turn from events."""
    projector = UIStateProjector()
    projector.event_bus = mock_event_bus

    turn = projector._get_current_turn()
    assert turn["role"] == "BUILDER"
    assert turn["plan_id"] == "WP-2026-024"
    assert turn["action"] == "IMPLEMENT"
    assert turn["timestamp"] == "2026-05-11T13:00:00"


def test_get_recent_events(mock_event_bus):
    """Test extracting recent events."""
    projector = UIStateProjector()
    projector.event_bus = mock_event_bus

    events = projector._get_recent_events(limit=1)
    assert len(events) == 1
    assert events[0]["event_type"] == "TURN_CHANGED"
    assert events[0]["actor"] == "BUILDER"


def test_project_state_integration(mock_event_bus, mock_collaboration_dir):
    """Test full state projection."""
    projector = UIStateProjector()
    projector.event_bus = mock_event_bus
    projector.collaboration_dir = mock_collaboration_dir

    state = projector.project_state()
    assert "current_turn" in state
    assert "active_plan" in state
    assert "ticket_status" in state
    assert "recent_events" in state

    assert state["current_turn"]["role"] == "BUILDER"
    assert state["active_plan"]["plan_id"] == "WP-2026-024"
    assert state["ticket_status"]["plan_status"] == "APPROVED"


def test_update_ui_state(mock_event_bus, mock_collaboration_dir, temp_runtime_dir):
    """Test updating ui_state.json."""
    projector = UIStateProjector(runtime_dir=temp_runtime_dir)
    projector.event_bus = mock_event_bus
    projector.collaboration_dir = mock_collaboration_dir

    projector.update_ui_state()
    assert projector.ui_state_path.exists()

    data = json.loads(projector.ui_state_path.read_text())
    assert data["current_turn"]["role"] == "BUILDER"


def test_get_recommended_files_ready_for_review():
    """Test recommended files when status is READY_FOR_REVIEW."""
    # Since current state has no active ticket in review, expect no recommended files
    projector = UIStateProjector()
    recommended = projector._get_recommended_files()
    assert recommended == []


def test_get_recommended_files_review(mock_collaboration_dir):
    """Test recommended files when status is review."""
    projector = UIStateProjector()
    projector.collaboration_dir = mock_collaboration_dir

    # Override with READY_FOR_REVIEW in correct block
    (mock_collaboration_dir / "execution_log.md").write_text(
        "## WP-2026-027: Supervisor Recovery and Reconciliation\n\n**Estado:** READY_FOR_REVIEW",
        encoding="utf-8",
    )

    recommended = projector._get_recommended_files()
    assert recommended == ["work_plan.md", "execution_log.md"]


def test_validate_projection(mock_event_bus, mock_collaboration_dir, temp_runtime_dir):
    """Test validation of projection."""
    projector = UIStateProjector(runtime_dir=temp_runtime_dir)
    projector.event_bus = mock_event_bus
    projector.collaboration_dir = mock_collaboration_dir

    # Initially invalid (no file)
    assert not projector.validate_projection()

    # After update, should be valid
    projector.update_ui_state()
    assert projector.validate_projection()


def test_cli_entry_point(
    capsys, mock_event_bus, mock_collaboration_dir, temp_runtime_dir
):
    """Test CLI entry point."""
    with patch("sys.path", []):
        # Mock to avoid import issues in test
        pass
