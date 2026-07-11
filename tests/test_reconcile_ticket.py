from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    import sys

    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "reconcile_ticket.py"
    )
    spec = importlib.util.spec_from_file_location("reconcile_ticket", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__ in sys.modules.
    sys.modules["reconcile_ticket"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("reconcile_ticket", None)
        raise
    return module


def test_reconcile_ticket_closes_runtime_and_cleans_locks(tmp_path: Path) -> None:
    mod = _load_module()
    project_root = tmp_path

    runtime_dir = project_root / ".agent" / "runtime"
    events_dir = runtime_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    bus = mod.EventBus(runtime_dir=events_dir)
    bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-205",
        actor="SUPERVISOR",
        payload={
            "from_state": "BOOTSTRAP",
            "to_state": "IN_PROGRESS",
            "reason": "bootstrap",
            "source": "bootstrap",
        },
    )

    (runtime_dir / "supervisor_state.json").write_text(
        json.dumps(
            {
                "active_ticket": "WT-2026-205",
                "completed_tickets": [],
                "last_action": "RECONCILED",
                "last_processed_sequence": 1,
                "loop_current_round": 1,
                "loop_max_rounds": 0,
                "last_requeue_trigger_sequence": 0,
                "last_manager_stale_trigger_sequence": 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (runtime_dir / "manager_bridge_state.json").write_text(
        json.dumps(
            {
                "last_processed_sequence": 1,
                "last_ticket_id": "WT-2026-205",
                "last_ticket_state": "READY_FOR_REVIEW",
                "updated_at": "2026-06-02T12:08:12.730758+00:00",
                "heartbeat_at": "2026-06-02T12:08:12.730758+00:00",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (runtime_dir / "builder_session.json").write_text(
        json.dumps({"ticket_id": "WT-2026-205"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (runtime_dir / "supervisor_lock.txt").write_text(
        json.dumps({"ticket_id": "WT-2026-205"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    builder_lock = runtime_dir / "builder_lock.txt"
    builder_lock.write_text(
        json.dumps({"ticket_id": "WT-2026-205"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = mod.reconcile_ticket(
        project_root,
        "WT-2026-205",
        reason="test reconcile",
        dry_run=False,
    )

    assert result.ticket_id == "WT-2026-205"
    assert result.before_state == "IN_PROGRESS"
    assert result.after_state in {"COMPLETED", "CLOSED"}
    assert "BUILDER_EXIT" in result.events_emitted
    assert "STATE_CHANGED->COMPLETED" in result.events_emitted
    assert "SUPERVISOR_CLOSED" in result.events_emitted
    assert "builder_lock.txt" in result.cleaned_artifacts
    assert "builder_session.json" in result.cleaned_artifacts
    assert "supervisor_lock.txt" in result.cleaned_artifacts

    supervisor_state = json.loads(
        (runtime_dir / "supervisor_state.json").read_text(encoding="utf-8")
    )
    assert supervisor_state["active_ticket"] is None
    assert "WT-2026-205" in supervisor_state["completed_tickets"]
    assert supervisor_state["last_processed_sequence"] >= 3

    assert not builder_lock.exists()
    assert not (runtime_dir / "builder_session.json").exists()
    assert not (runtime_dir / "supervisor_lock.txt").exists()

    bridge_state = json.loads(
        (runtime_dir / "manager_bridge_state.json").read_text(encoding="utf-8")
    )
    assert bridge_state["last_ticket_state"] == result.after_state


def test_reconcile_ticket_dry_run_does_not_write(tmp_path: Path) -> None:
    mod = _load_module()
    project_root = tmp_path
    runtime_dir = project_root / ".agent" / "runtime"
    events_dir = runtime_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    bus = mod.EventBus(runtime_dir=events_dir)
    bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-205",
        actor="SUPERVISOR",
        payload={
            "from_state": "BOOTSTRAP",
            "to_state": "IN_PROGRESS",
            "reason": "bootstrap",
            "source": "bootstrap",
        },
    )

    supervisor_state_path = runtime_dir / "supervisor_state.json"
    supervisor_state_path.write_text(
        json.dumps(
            {
                "active_ticket": "WT-2026-205",
                "completed_tickets": [],
                "last_action": "RECONCILED",
                "last_processed_sequence": 1,
                "loop_current_round": 1,
                "loop_max_rounds": 0,
                "last_requeue_trigger_sequence": 0,
                "last_manager_stale_trigger_sequence": 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = mod.reconcile_ticket(
        project_root,
        "WT-2026-205",
        reason="dry run",
        dry_run=True,
    )

    assert result.dry_run is True
    assert supervisor_state_path.exists()
    supervisor_state = json.loads(supervisor_state_path.read_text(encoding="utf-8"))
    assert supervisor_state["active_ticket"] == "WT-2026-205"
    assert "dry-run" in " ".join(result.notes)


def test_reconcile_ticket_emits_builder_exit_for_code_only_close(
    tmp_path: Path,
) -> None:
    """A code-only ticket closed via reconcile (no prior bus events, BOOTSTRAP
    state) must get a BUILDER_EXIT event BEFORE STATE_CHANGED->COMPLETED.

    Without BUILDER_EXIT, closure_invariants.check_post_closure_built_exit
    promotes the "bus absent" warning to an ERROR ("Missing BUILDER_EXIT")
    because the bus now HAS events (STATE_CHANGED + SUPERVISOR_CLOSED) but
    lacks the required BUILDER_EXIT. This is the exact gap that broke the
    021u reconcile attempt on 2026-07-11.

    The test also verifies the ordering invariant (test_loop_hard_stop:203):
    BUILDER_EXIT sequence_number < STATE_CHANGED sequence_number.
    """
    mod = _load_module()
    project_root = tmp_path
    runtime_dir = project_root / ".agent" / "runtime"
    events_dir = runtime_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    (runtime_dir / "supervisor_state.json").write_text(
        json.dumps(
            {
                "active_ticket": "WOT-2026-021u",
                "completed_tickets": [],
                "last_action": "PROCESSED",
                "last_processed_sequence": 0,
                "loop_current_round": 0,
                "loop_max_rounds": 0,
                "last_requeue_trigger_sequence": 0,
                "last_manager_stale_trigger_sequence": 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = mod.reconcile_ticket(
        project_root,
        "WOT-2026-021u",
        reason="code-only close via commit-directo",
        dry_run=False,
    )

    assert result.before_state == "BOOTSTRAP"
    assert result.after_state == "COMPLETED"
    assert "BUILDER_EXIT" in result.events_emitted
    assert "STATE_CHANGED->COMPLETED" in result.events_emitted
    assert "SUPERVISOR_CLOSED" in result.events_emitted

    events = mod._read_events_for_ticket(project_root, "WOT-2026-021u")
    assert len(events) == 3

    builder_exit_seq = events[0]["sequence_number"]
    state_changed_seq = events[1]["sequence_number"]
    supervisor_closed_seq = events[2]["sequence_number"]
    assert events[0]["event_type"] == "BUILDER_EXIT"
    assert events[1]["event_type"] == "STATE_CHANGED"
    assert events[2]["event_type"] == "SUPERVISOR_CLOSED"
    assert builder_exit_seq < state_changed_seq < supervisor_closed_seq

    builder_exit_payload = events[0]["payload"]
    assert builder_exit_payload["exit_reason"]
    assert builder_exit_payload["completion_summary"]
