import json
from pathlib import Path

import pytest
from scripts.state_projection_sync import sync_state_projection


@pytest.fixture
def sync_env(tmp_path: Path):
    runtime_dir = tmp_path / "runtime" / "events"
    runtime_dir.mkdir(parents=True)

    collab_dir = tmp_path / "collaboration"
    collab_dir.mkdir(parents=True)

    events_path = runtime_dir / "events.jsonl"
    state_md_path = collab_dir / "STATE.md"
    work_plan_path = collab_dir / "work_plan.md"

    work_plan_path.write_text("# Work Plan\n- **ID:** WP-2026-149\n", encoding="utf-8")

    def emit_event(event_type: str, state: str):
        event = {
            "event_type": event_type,
            "ticket_id": "WP-2026-149",
            "actor": "TEST",
            "payload": {"to_state": state},
        }
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    class Env:
        def __init__(self):
            self.runtime_dir = runtime_dir
            self.collab_dir = collab_dir
            self.events_path = events_path
            self.state_md_path = state_md_path
            self.emit = emit_event
            self.ticket_id = "WP-2026-149"

    return Env()


def test_sync_matched(sync_env):
    """Test when state already matches bus state."""
    sync_env.emit("STATE_CHANGED", "IN_PROGRESS")
    sync_env.state_md_path.write_text(
        f"ACTIVE_TICKET: {sync_env.ticket_id}\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )

    result = sync_state_projection(
        sync_env.runtime_dir, sync_env.collab_dir, sync_env.ticket_id
    )

    assert result is True
    # Should not have changed
    assert "STATUS: IN_PROGRESS" in sync_env.state_md_path.read_text(encoding="utf-8")


def test_sync_drifted(sync_env):
    """Test healing when state is drifted."""
    sync_env.emit("STATE_CHANGED", "READY_FOR_REVIEW")
    sync_env.state_md_path.write_text(
        f"# State - {sync_env.ticket_id}\n\nEstado actual: IN_PROGRESS\n",
        encoding="utf-8",
    )

    result = sync_state_projection(
        sync_env.runtime_dir, sync_env.collab_dir, sync_env.ticket_id
    )

    assert result is True
    # Should have healed
    synced_state = sync_env.state_md_path.read_text(encoding="utf-8")
    assert f"ACTIVE_TICKET: {sync_env.ticket_id}" in synced_state
    assert "STATUS: READY_FOR_REVIEW" in synced_state


def test_sync_empty_bus(sync_env):
    """Test graceful fallback when bus is empty."""
    sync_env.state_md_path.write_text(
        f"# State - {sync_env.ticket_id}\n\nEstado actual: IN_PROGRESS\n",
        encoding="utf-8",
    )

    result = sync_state_projection(
        sync_env.runtime_dir, sync_env.collab_dir, sync_env.ticket_id
    )

    assert result is True
    assert "Estado actual: IN_PROGRESS" in sync_env.state_md_path.read_text(
        encoding="utf-8"
    )


def test_sync_missing_state(sync_env):
    """Test healing when STATE.md is completely missing."""
    sync_env.emit("STATE_CHANGED", "COMPLETED")

    # Do not create STATE.md
    assert not sync_env.state_md_path.exists()

    result = sync_state_projection(
        sync_env.runtime_dir, sync_env.collab_dir, sync_env.ticket_id
    )

    assert result is True
    assert sync_env.state_md_path.exists()
    synced_state = sync_env.state_md_path.read_text(encoding="utf-8")
    assert f"ACTIVE_TICKET: {sync_env.ticket_id}" in synced_state
    assert "STATUS: COMPLETED" in synced_state
