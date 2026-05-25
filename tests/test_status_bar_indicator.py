"""Tests for status bar indicator."""

import json

import pytest
from runtime.status_bar_indicator import StatusBarIndicator


@pytest.fixture
def temp_runtime_dir(tmp_path):
    """Temporary runtime directory."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


@pytest.fixture
def mock_ui_state(temp_runtime_dir):
    """Mock ui_state.json."""
    ui_state = {
        "current_turn": {
            "role": "BUILDER",
            "plan_id": "WP-2026-025",
            "action": "IMPLEMENT",
            "timestamp": "2026-05-11 15:00:00",
        },
        "active_plan": {
            "plan_id": "WP-2026-025",
            "status": "APPROVED",
            "objective": "Mostrar estado en status bar",
        },
    }
    ui_state_path = temp_runtime_dir / "ui_state.json"
    ui_state_path.write_text(json.dumps(ui_state))
    return ui_state_path


def test_indicator_initialization(temp_runtime_dir):
    """Test indicator initializes correctly."""
    indicator = StatusBarIndicator(runtime_dir=temp_runtime_dir)
    assert indicator.runtime_dir == temp_runtime_dir
    assert indicator.ui_state_path == temp_runtime_dir / "ui_state.json"
    assert indicator.status_bar_path == temp_runtime_dir / "status_bar.json"


def test_read_ui_state(mock_ui_state, temp_runtime_dir):
    """Test reading ui_state.json."""
    indicator = StatusBarIndicator(runtime_dir=temp_runtime_dir)
    ui_state = indicator._read_ui_state()
    assert ui_state is not None
    assert ui_state["current_turn"]["role"] == "BUILDER"


def test_extract_status_info(mock_ui_state, temp_runtime_dir):
    """Test extracting status info."""
    indicator = StatusBarIndicator(runtime_dir=temp_runtime_dir)
    ui_state = indicator._read_ui_state()
    status_info = indicator._extract_status_info(ui_state)
    assert status_info["role"] == "BUILDER"
    assert status_info["plan_id"] == "WP-2026-025"
    assert status_info["action"] == "IMPLEMENT"
    assert status_info["plan_status"] == "APPROVED"
    assert status_info["timestamp"] == "2026-05-11 15:00:00"


def test_update_status_bar(mock_ui_state, temp_runtime_dir):
    """Test updating status_bar.json."""
    indicator = StatusBarIndicator(runtime_dir=temp_runtime_dir)
    indicator.update_status_bar()
    assert indicator.status_bar_path.exists()

    data = json.loads(indicator.status_bar_path.read_text())
    assert data["role"] == "BUILDER"
    assert data["plan_id"] == "WP-2026-025"


def test_validate_status_bar(mock_ui_state, temp_runtime_dir):
    """Test validation of status bar."""
    indicator = StatusBarIndicator(runtime_dir=temp_runtime_dir)

    # Initially invalid (no file)
    assert not indicator.validate_status_bar()

    # After update, should be valid
    indicator.update_status_bar()
    assert indicator.validate_status_bar()


def test_no_ui_state(temp_runtime_dir):
    """Test behavior when ui_state.json doesn't exist."""
    indicator = StatusBarIndicator(runtime_dir=temp_runtime_dir)
    indicator.update_status_bar()
    assert indicator.status_bar_path.exists()

    data = json.loads(indicator.status_bar_path.read_text())
    assert data["role"] == "UNKNOWN"
    assert data["plan_id"] == "NINGUNO"
