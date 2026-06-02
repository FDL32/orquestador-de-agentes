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
