from __future__ import annotations

import sys
from pathlib import Path

from bus.event_bus import EventBus
from bus.state_machine import TicketState


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "launch_agent_terminals.ps1"

sys.path.insert(0, str(PROJECT_ROOT))

from scripts.get_launcher_state import derive_launcher_state  # noqa: E402


def _write_work_plan(project_root: Path, ticket_id: str) -> None:
    collab = project_root / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "work_plan.md").write_text(
        "\n".join(
            [
                f"# Work Ticket - {ticket_id}",
                "",
                "## Metadata",
                f"- **ID:** {ticket_id}",
                "- **Estado:** APPROVED",
            ]
        ),
        encoding="utf-8",
    )


def test_derive_launcher_state_uses_bus_for_ready_for_review(tmp_path: Path) -> None:
    ticket_id = "WT-2026-216"
    _write_work_plan(tmp_path, ticket_id)
    event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    state = derive_launcher_state(tmp_path)

    assert state["ticket_id"] == ticket_id
    assert state["state"] == TicketState.READY_FOR_REVIEW.value
    assert state["role"] == "MANAGER"
    assert state["action"] == "REVIEW_WORK"
    assert state["source"] == "event_bus"


def test_derive_launcher_state_defaults_to_builder_for_unknown_bus(
    tmp_path: Path,
) -> None:
    ticket_id = "WT-2026-216"
    _write_work_plan(tmp_path, ticket_id)

    state = derive_launcher_state(tmp_path)

    assert state["ticket_id"] == ticket_id
    assert state["state"] == TicketState.UNKNOWN.value
    assert state["role"] == "BUILDER"
    assert state["action"] == "IMPLEMENT"


def test_derive_launcher_state_accepts_custom_ticket_prefix(tmp_path: Path) -> None:
    ticket_id = "ABC-2026-101"
    _write_work_plan(tmp_path, ticket_id)
    event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    state = derive_launcher_state(tmp_path)

    assert state["ticket_id"] == ticket_id
    assert state["state"] == TicketState.READY_FOR_REVIEW.value
    assert state["role"] == "MANAGER"


def test_launcher_script_uses_python_helper_before_turn_fallback() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "scripts\\get_launcher_state.py" in content
    assert "--project-root $ProjectRoot" in content
    assert "ConvertFrom-Json" in content
    assert "Recurriendo a TURN.md como fallback" in content
