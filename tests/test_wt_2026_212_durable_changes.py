from __future__ import annotations

import subprocess
from pathlib import Path

from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge


def _make_bridge(tmp_path: Path) -> tuple[ReviewBridge, EventBus, Path]:
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
    legacy_manager_exe = tmp_path / "manager_legacy.exe"
    legacy_manager_exe.write_text("", encoding="utf-8")
    return bridge, event_bus, legacy_manager_exe


def _prepare_changes_bridge(tmp_path: Path, monkeypatch):
    bridge, event_bus, legacy_exe = _make_bridge(tmp_path)

    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "work_plan.md").write_text(
        "# Work Ticket - WT-2026-212\n\n## Metadata\n- **ID:** WT-2026-212\n"
        "- **Estado:** APPROVED\n- **deliverable_type:** code\n",
        encoding="utf-8",
    )

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "--request-changes" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                "## SUMMARY\nNeeds fixes.\n## BLOCKERS\n- Missing test\n"
                "## SUGGESTIONS\n- Add test\nDECISION: CHANGES"
            ),
            stderr="",
        )

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "legacy_manager")
    monkeypatch.setattr(bridge, "_resolve_motor_controller", lambda: None)
    monkeypatch.setattr(
        "bus.review_bridge.ReviewBridge._ensure_repomix_context", lambda self: None
    )
    return bridge, event_bus, legacy_exe


def test_changes_runs_real_supervisor_tick_when_lock_is_stale(tmp_path, monkeypatch):
    bridge, _, legacy_exe = _prepare_changes_bridge(tmp_path, monkeypatch)

    class DurableSupervisor:
        def __init__(self) -> None:
            self.bootstrap_calls = 0
            self.run_once_calls = 0
            self.release_calls = 0
            self.requeue_calls: list[tuple[str, int]] = []

        def transition_ticket(self, **kwargs):
            return None

        def _is_supervisor_lock_stale(self):
            return True

        def bootstrap(self):
            self.bootstrap_calls += 1
            return True

        def run_once(self):
            self.run_once_calls += 1
            return True

        def _release_supervisor_lock(self):
            self.release_calls += 1

        def requeue_ticket(self, ticket_id: str, trigger_seq: int):
            self.requeue_calls.append((ticket_id, trigger_seq))
            return True

    supervisor = DurableSupervisor()
    result = bridge.run_manager_review_cycle(
        ticket_id="WT-2026-212",
        supervisor=supervisor,
        manager_executable=legacy_exe,
        timeout_seconds=5,
    )

    assert result.decision.value == "changes"
    assert supervisor.bootstrap_calls == 1
    assert supervisor.run_once_calls == 1
    assert supervisor.release_calls == 1
    assert supervisor.requeue_calls == []


def test_changes_skips_rescue_tick_if_relaunch_already_exists(tmp_path, monkeypatch):
    bridge, event_bus, legacy_exe = _prepare_changes_bridge(tmp_path, monkeypatch)
    ticket_id = "WT-2026-212"

    class SupervisorThatLostRace:
        def __init__(self) -> None:
            self.bootstrap_calls = 0
            self.run_once_calls = 0
            self.release_calls = 0

        def transition_ticket(self, **kwargs):
            return None

        def _is_supervisor_lock_stale(self):
            event_bus.emit(
                "BUILDER_RELAUNCH_ATTEMPTED",
                ticket_id=ticket_id,
                actor="SUPERVISOR",
                payload={"success": True},
            )
            return True

        def bootstrap(self):
            self.bootstrap_calls += 1
            return True

        def run_once(self):
            self.run_once_calls += 1
            return True

        def _release_supervisor_lock(self):
            self.release_calls += 1

    supervisor = SupervisorThatLostRace()
    result = bridge.run_manager_review_cycle(
        ticket_id=ticket_id,
        supervisor=supervisor,
        manager_executable=legacy_exe,
        timeout_seconds=5,
    )

    assert result.decision.value == "changes"
    assert supervisor.bootstrap_calls == 0
    assert supervisor.run_once_calls == 0
    assert supervisor.release_calls == 0
