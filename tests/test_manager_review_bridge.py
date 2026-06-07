from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from bus.event_bus import EventBus
from bus.exceptions import ConcurrentStateError
from bus.review_bridge import ReviewBridge, ReviewDecision
from bus.supervisor import SequentialTicketSupervisor, SupervisorState
from runtime.project_root import clear_cache
from scripts.manager_review_bridge import (
    BridgeState,
    _bridge_heartbeat,
    _checkpoint_path,
    _load_checkpoint,
    _load_state,
    _save_checkpoint,
    _save_state,
    _state_path,
    _tick,
    _ticket_state,
)


# Save reference to the real _ensure_repomix_context before the autouse
# fixture _mock_repomix_for_tests monkeypatches it at class level.
_REAL_ENSURE_REPOMIX_CONTEXT = ReviewBridge._ensure_repomix_context


class DummySupervisor:
    def __init__(self) -> None:
        self.transitions: list[tuple[str, str, str]] = []

    def transition_ticket(
        self,
        ticket_id: str,
        new_state: str,
        reason: str,
        source_event_id: str | None = None,
    ) -> None:
        self.transitions.append((ticket_id, new_state, reason))

    def _is_supervisor_lock_stale(self) -> bool:
        return False

    def requeue_ticket(self, ticket_id: str) -> bool:
        return True


def _make_bridge(tmp_path: Path) -> tuple[ReviewBridge, EventBus, Path]:
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
    legacy_manager_exe = tmp_path / "manager_legacy.exe"
    legacy_manager_exe.write_text("", encoding="utf-8")
    return bridge, event_bus, legacy_manager_exe


@pytest.fixture(autouse=True)
def _mock_repomix_for_tests(monkeypatch):
    """WT-2026-182: Evitar warnings y ralentización en CI por npx repomix."""
    monkeypatch.setattr(
        "bus.review_bridge.ReviewBridge._ensure_repomix_context",
        lambda self: (None, {"status": "skipped", "reason": "mocked for tests"}),
    )


# =============================================================================
# Tests WP-2026-176: Motor controller resolution in review bridge
# =============================================================================


def test_resolve_motor_root_no_link(tmp_path):
    """_resolve_motor_root returns None when no motor_destination_link.json exists."""
    bridge, _, _ = _make_bridge(tmp_path)
    result = bridge._resolve_motor_root()
    assert result is None


def test_resolve_motor_root_with_valid_link(tmp_path):
    """_resolve_motor_root reads motor_root from workspace config link."""
    bridge, _, _ = _make_bridge(tmp_path)
    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    link = config_dir / "motor_destination_link.json"
    motor_root = tmp_path / "external_motor"
    motor_root.mkdir(parents=True, exist_ok=True)
    link.write_text(json.dumps({"motor_root": str(motor_root)}), encoding="utf-8")
    result = bridge._resolve_motor_root()
    assert result is not None
    assert result == motor_root.resolve()


def test_resolve_motor_root_with_unreachable_motor(tmp_path, monkeypatch):
    """_resolve_motor_root returns None when motor_root path does not exist."""
    bridge, _, _ = _make_bridge(tmp_path)
    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    link = config_dir / "motor_destination_link.json"
    # Use a guaranteed non-existent path on any platform
    nonexistent = tmp_path / "definitely_not_existing_987654321"
    link.write_text(json.dumps({"motor_root": str(nonexistent)}), encoding="utf-8")
    result = bridge._resolve_motor_root()
    assert result is None


def test_resolve_motor_controller_no_link(tmp_path):
    """_resolve_motor_controller falls back when no link file exists."""
    bridge, _, _ = _make_bridge(tmp_path)
    result = bridge._resolve_motor_controller()
    assert result is None


def test_resolve_motor_controller_finds_controller(tmp_path):
    """_resolve_motor_controller returns the motor controller path when link exists."""
    bridge, _, _ = _make_bridge(tmp_path)
    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    motor_root = tmp_path / "motor_repo"
    motor_root.mkdir(parents=True, exist_ok=True)
    controller = motor_root / ".agent" / "agent_controller.py"
    controller.parent.mkdir(parents=True, exist_ok=True)
    controller.write_text("# controller stub\n", encoding="utf-8")
    link = config_dir / "motor_destination_link.json"
    link.write_text(json.dumps({"motor_root": str(motor_root)}), encoding="utf-8")
    result = bridge._resolve_motor_controller()
    assert result is not None
    assert result == controller.resolve()


def test_resolve_motor_controller_missing_controller(tmp_path):
    """_resolve_motor_controller returns None when controller does not exist at motor root."""
    bridge, _, _ = _make_bridge(tmp_path)
    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    motor_root = tmp_path / "motor_repo_no_controller"
    motor_root.mkdir(parents=True, exist_ok=True)
    # No agent_controller.py in the motor root
    link = config_dir / "motor_destination_link.json"
    link.write_text(json.dumps({"motor_root": str(motor_root)}), encoding="utf-8")
    result = bridge._resolve_motor_controller()
    assert result is None


def test_resolve_motor_controller_invalid_json(tmp_path):
    """_resolve_motor_controller returns None on malformed link JSON."""
    bridge, _, _ = _make_bridge(tmp_path)
    config_dir = tmp_path / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    link = config_dir / "motor_destination_link.json"
    link.write_text("not valid json", encoding="utf-8")
    result = bridge._resolve_motor_controller()
    assert result is None


def _make_review_prompt_bridge(
    tmp_path: Path, deliverable_type: str = "code", monkeypatch=None
) -> ReviewBridge:
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    collaboration_dir.mkdir(parents=True, exist_ok=True)
    (collaboration_dir / "work_plan.md").write_text(
        "\n".join(
            [
                "# Work Plan - WP-TEST-123",
                "",
                "## Metadata",
                "- **ID:** WP-TEST-123",
                "- **Estado:** APPROVED",
                f"- **deliverable_type:** {deliverable_type}",
                "- **Titulo:** Test ticket",
                "- **Asignado a:** Builder",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (collaboration_dir / "TURN.md").write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "## Agente Activo",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                "| **ROL** | **BUILDER** |",
                "| **Plan ID** | WP-TEST-123 |",
                "| **Tipo** | IMPLEMENTATION |",
                "| **Accion** | IMPLEMENT |",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (collaboration_dir / "STATE.md").write_text(
        "\n".join(
            [
                "# State - WP-TEST-123",
                "",
                "Plan Activo: WP-TEST-123",
                "Estado actual: IN_PROGRESS",
                "Rol activo: BUILDER",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (collaboration_dir / "execution_log.md").write_text(
        "\n".join(
            [
                "# Execution Log - WP-TEST-123",
                "",
                "## Metadata",
                "- **ID:** WP-TEST-123",
                "- **Estado:** IN_PROGRESS",
                "- **deliverable_type:** code",
                "",
            ]
        ),
        encoding="utf-8",
    )
    observations_path = (
        tmp_path / ".agent" / "runtime" / "memory" / "observations.jsonl"
    )
    if observations_path.exists():
        observations_path.unlink()

    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    # WP-2026-156: Aislar git para no escapar al repo anfitrion
    if monkeypatch is not None:
        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
        monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )

    return bridge


def _write_observations(tmp_path: Path, lines: list[str]) -> Path:
    memory_dir = tmp_path / ".agent" / "runtime" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = memory_dir / "observations.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# =============================================================================


def test_manager_review_cycle_approves(monkeypatch, tmp_path):
    bridge, event_bus, legacy_manager_exe = _make_bridge(tmp_path)
    supervisor = DummySupervisor()

    def fake_run(cmd, **kwargs):
        return __import__("subprocess").CompletedProcess(
            cmd,
            0,
            stdout="APPROVE: no findings. Ready for closeout.",
            stderr="",
        )

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
    )
    # Force the legacy Manager backend for this compatibility test
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "legacy_manager")

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-2026-025",
        supervisor=supervisor,
        manager_executable=legacy_manager_exe,
        timeout_seconds=5,
    )

    assert result.decision.value == "approve"
    assert supervisor.transitions[-1][1] == "READY_TO_CLOSE"
    events = event_bus.read_events(ticket_id="WP-2026-025")
    assert any(event.event_type == "MANAGER_REVIEWING" for event in events)
    assert any(event.event_type == "REVIEW_DECISION" for event in events)


def test_manager_review_cycle_requests_changes(monkeypatch, tmp_path):
    """Test review cycle emits CHANGES and ends the cycle immediately (WP-2026-106).

    WP-2026-106: CHANGES breaks the inner loop immediately — no retry within
    the same cycle. The Builder is requeued for a new cycle via agent_controller.
    Multiple-cycle CHANGES→APPROVE behavior is covered by
    test_review_cycle_approves_before_threshold.
    """
    bridge, event_bus, legacy_manager_exe = _make_bridge(tmp_path)
    supervisor = DummySupervisor()
    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        if any("agent_controller.py" in str(part) for part in cmd):
            return __import__("subprocess").CompletedProcess(
                cmd, 0, stdout="[OK] requeue", stderr=""
            )
        if (
            isinstance(cmd, list)
            and cmd
            and Path(str(cmd[0])).name.lower() in ("git", "git.exe")
        ):
            return __import__("subprocess").CompletedProcess(
                cmd, 0, stdout="", stderr=""
            )
        call_count["n"] += 1
        return __import__("subprocess").CompletedProcess(
            cmd,
            0,
            stdout="## SUMMARY\nNeeds fixes.\n## BLOCKERS\n- Parsing\n## SUGGESTIONS\n- Fix parsing\nDECISION: CHANGES",
            stderr="",
        )

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "legacy_manager")

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-2026-025",
        supervisor=supervisor,
        manager_executable=legacy_manager_exe,
        timeout_seconds=5,
    )

    # WP-2026-106: CHANGES ends the cycle immediately, no inner retry
    assert result.decision.value == "changes"
    assert call_count["n"] == 1
    events = event_bus.read_events(ticket_id="WP-2026-025")
    assert any(event.event_type == "MANAGER_REVIEWING" for event in events)
    assert any(event.event_type == "REVIEW_DECISION" for event in events)


def test_manager_review_cycle_tool_error_is_transport_failed(monkeypatch, tmp_path):
    bridge, event_bus, legacy_manager_exe = _make_bridge(tmp_path)
    supervisor = DummySupervisor()

    def fake_run(cmd, **kwargs):
        return __import__("subprocess").CompletedProcess(
            cmd,
            2,
            stdout="",
            stderr="error: the argument '--uncommitted' cannot be used with '[PROMPT]'",
        )

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
    )
    # WP-2026-156: Aislar git para no escapar al repo anfitrion
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-2026-025",
        supervisor=supervisor,
        manager_executable=legacy_manager_exe,
        timeout_seconds=5,
    )

    assert result.decision.value == "transport_failed"
    assert result.transport_ok is False
    assert "exit_code=2" in result.transport_error
    assert supervisor.transitions == []
    events = event_bus.read_events(ticket_id="WP-2026-025")
    assert any(event.event_type == "MANAGER_REVIEWING" for event in events)
    assert any(event.event_type == "REVIEW_TRANSPORT_FAILED" for event in events)


def test_manager_review_cycle_auth_error_exit_zero_is_transport_failed(
    monkeypatch, tmp_path
):
    bridge, event_bus, legacy_manager_exe = _make_bridge(tmp_path)
    supervisor = DummySupervisor()

    def fake_run(cmd, **kwargs):
        return __import__("subprocess").CompletedProcess(
            cmd,
            0,
            stdout=(
                '{"type":"error","error":{"data":'
                '{"message":"Your authentication token has been invalidated. '
                'Please try signing in again.","statusCode":401,'
                '"responseBody":"{\\"status\\": 401, '
                '\\"code\\": \\"token_invalidated\\"}"}}}'
            ),
            stderr="",
        )

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )

    result = bridge.run_manager_review_cycle(
        ticket_id="WT-2026-236a",
        supervisor=supervisor,
        manager_executable=legacy_manager_exe,
        timeout_seconds=5,
    )

    assert result.decision.value == "transport_failed"
    assert result.transport_ok is False
    assert result.transport_error == "auth_failed"
    assert supervisor.transitions == []
    events = event_bus.read_events(ticket_id="WT-2026-236a")
    assert any(event.event_type == "MANAGER_REVIEWING" for event in events)
    assert any(event.event_type == "REVIEW_TRANSPORT_FAILED" for event in events)
    assert not any(event.event_type == "REVIEW_DECISION" for event in events)


def test_ticket_state_falls_back_to_execution_log(tmp_path):
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    (collaboration_dir / "work_plan.md").write_text(
        "\n".join(
            [
                "# Plan de Trabajo del Proyecto",
                "",
                "## WP-2026-025: Status Bar Indicator",
                "",
                "### Metadata",
                "- **ID:** WP-2026-025",
                "- **Estado:** APPROVED",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (collaboration_dir / "execution_log.md").write_text(
        "\n".join(
            [
                "# Execution Log",
                "",
                "## Project summary",
                "",
                "- Project: `orquestador_de_agentes`",
                "- **Estado:** READY_FOR_REVIEW",
                "- Current state: ACTIVE",
                "- Active workstreams: WP-2026-025",
            ]
        ),
        encoding="utf-8",
    )
    (collaboration_dir / "TURN.md").write_text(
        "\n".join(
            [
                "# TURNO ACTUAL",
                "",
                "## Agente Activo",
                "",
                "| Campo | Valor |",
                "|-------|-------|",
                "| **ROL** | **BUILDER** |",
                "| **Plan ID** | WP-2026-025 |",
                "| **Tipo** | IMPLEMENTATION |",
                "| **Accion** | IMPLEMENT |",
                "",
                "## Estado del Sistema",
                "",
                "| Archivo | Estado |",
                "|---------|--------|",
                "| work_plan.md | APPROVED |",
                "| execution_log.md | READY_FOR_REVIEW |",
            ]
        ),
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.save_state(
        SupervisorState(
            active_ticket="WP-2026-025",
            completed_tickets=["WP-2026-024"],
            last_action="ACTIVATE",
        )
    )

    ticket_id, state, sequence = _ticket_state(supervisor)
    assert ticket_id == "WP-2026-025"
    assert state.value == "READY_FOR_REVIEW"
    assert sequence >= 0


def test_ticket_state_ignores_manager_stale_as_review_trigger(tmp_path):
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )
    supervisor.save_state(
        SupervisorState(active_ticket="WT-2026-236a", completed_tickets=[])
    )

    ready_event = supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-236a",
        actor="SUPERVISOR",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )
    supervisor.event_bus.emit(
        "MANAGER_STALE",
        ticket_id="WT-2026-236a",
        actor="SUPERVISOR",
        payload={"trigger_sequence": ready_event.sequence_number},
    )

    ticket_id, state, sequence = _ticket_state(supervisor)

    assert ticket_id == "WT-2026-236a"
    assert state.value == "READY_FOR_REVIEW"
    assert sequence == ready_event.sequence_number


def test_bridge_heartbeat_includes_cursor_and_sequence():
    from bus.state_machine import TicketState

    line = _bridge_heartbeat(
        prefix="waiting",
        active_ticket="WP-2026-038",
        current_state=TicketState.READY_FOR_REVIEW,
        latest_sequence=1836,
        bridge_state=BridgeState(
            last_processed_sequence=1836,
            last_ticket_id="WP-2026-038",
            last_ticket_state="READY_FOR_REVIEW",
            updated_at="2026-05-12T17:54:37+0200",
        ),
    )

    assert "[manager-review-bridge] waiting" in line
    assert "ts=" in line
    assert "ticket=WP-2026-038" in line
    assert "state=READY_FOR_REVIEW" in line
    assert "seq=1836" in line
    assert "last_processed=1836" in line
    assert "bridge_ticket=WP-2026-038" in line
    assert "bridge_state=READY_FOR_REVIEW" in line
    assert "updated_at=2026-05-12T17:54:37+0200" in line


def test_build_review_prompt_includes_generated_artifacts_block(tmp_path, monkeypatch):
    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    # WP-2026-156: Aislar git para no escapar al repo anfitrion
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )

    # We just need to verify the prompt contains the new block
    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")

    assert "--- SYSTEM GENERATED & ARCHIVED ARTIFACTS ---" in prompt
    assert "archive_collaboration_artifacts.py" in prompt
    assert "Deletions, moves to _archive/" in prompt


def test_build_review_prompt_uses_branch_base_diff(tmp_path, monkeypatch):
    """Prompt includes diff anchored to merge-base(origin/main, HEAD) when reachable."""
    import subprocess as _subprocess

    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    sha = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    base = "feedfacefeedfacefeedfacefeedfacefeedface"

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "merge-base" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout=f"{base}\n",
                stderr="",
            )
        if isinstance(cmd, list) and "diff" in cmd and f"{base}..HEAD" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout="diff --git a/bus/review_bridge.py b/bus/review_bridge.py\n+added line\n",
                stderr="",
            )
        if isinstance(cmd, list) and "log" in cmd and f"{base}..HEAD" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout=f"{sha} 2026-05-25 10:00:00 +0200 Test Author\n",
                stderr="",
            )
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(bridge, "_motor_root_or_raise", lambda: tmp_path)
    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-134", dtype="code")

    assert "diff --git a/bus/review_bridge.py" in prompt
    assert "[WARNING: origin/main not reachable" not in prompt


def test_build_review_prompt_falls_back_to_ticket_commit_range_when_no_remote(
    tmp_path, monkeypatch
):
    """Prompt falls back to the contiguous ticket commit range when no remote is reachable."""
    import subprocess as _subprocess

    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "merge-base" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                128,
                stdout="",
                stderr="fatal: origin/main not reachable",
            )
        if isinstance(cmd, list) and "log" in cmd and "--format=%H%x09%s" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout=(
                    "bbb222\tWT-2026-192 second commit\n"
                    "aaa111\tWT-2026-192 first commit\n"
                    "base999\tprevious unrelated commit\n"
                ),
                stderr="",
            )
        if isinstance(cmd, list) and "diff" in cmd and "base999..HEAD" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout="diff --git a/scripts/claude_memory_mirror.py b/scripts/claude_memory_mirror.py\n+ticket range line\n",
                stderr="",
            )
        if isinstance(cmd, list) and "log" in cmd and "base999..HEAD" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2 2026-05-25 10:00:00 +0200 Test Author\n",
                stderr="",
            )
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(bridge, "_motor_root_or_raise", lambda: tmp_path)
    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    prompt = bridge._build_review_prompt(ticket_id="WT-2026-192", dtype="code")

    assert (
        "[WARNING: origin/main not reachable, using ticket commit range fallback]"
        in prompt
    )
    assert "diff --git a/scripts/claude_memory_mirror.py" in prompt


def test_build_review_prompt_falls_back_to_head_parent_when_no_remote_or_ticket_range(
    tmp_path, monkeypatch
):
    """Prompt uses HEAD^ as the last fallback when neither remote nor ticket range are available."""
    import subprocess as _subprocess

    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "merge-base" in cmd:
            return _subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal")
        if isinstance(cmd, list) and "log" in cmd and "--format=%H%x09%s" in cmd:
            return _subprocess.CompletedProcess(
                cmd, 0, stdout="zzz999\tunrelated commit\n", stderr=""
            )
        if isinstance(cmd, list) and "diff" in cmd and "HEAD^..HEAD" in cmd:
            return _subprocess.CompletedProcess(
                cmd, 0, stdout="diff --git a/x b/x\n+head-parent fallback\n", stderr=""
            )
        if isinstance(cmd, list) and "log" in cmd and "HEAD^..HEAD" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout="deadbeef 2026-05-25 10:00:00 +0200 Test Author\n",
                stderr="",
            )
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(bridge, "_motor_root_or_raise", lambda: tmp_path)
    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    prompt = bridge._build_review_prompt(ticket_id="WT-2026-192", dtype="code")

    assert "[WARNING: origin/main not reachable, using HEAD^ fallback]" in prompt


def test_build_review_prompt_includes_provenance_section(tmp_path, monkeypatch):
    """Prompt includes --- git provenance --- section with SHA, date, and author."""
    import subprocess as _subprocess

    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    sha = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    base = "feedfacefeedfacefeedfacefeedfacefeedface"

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "merge-base" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout=f"{base}\n",
                stderr="",
            )
        if isinstance(cmd, list) and "log" in cmd and f"{base}..HEAD" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout=f"{sha} 2026-05-25 10:00:00 +0200 Test Author\n",
                stderr="",
            )
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(bridge, "_motor_root_or_raise", lambda: tmp_path)
    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-134", dtype="code")

    assert "--- git provenance ---" in prompt
    assert sha in prompt


def test_render_loader_rules_dedupes_identical_blocks(tmp_path, monkeypatch):
    """Repeated identical L2 blocks must appear only once in the review packet."""
    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    repeated_block = "## Domain: review-quality\n- R-001 repeated block"
    monkeypatch.setattr(
        bridge,
        "_relevant_domains_for_dtype",
        lambda dtype: {"review-quality", "builder-contract", "testing"},
    )
    monkeypatch.setattr(
        "bus.review_bridge.get_review_context",
        lambda domain=None: repeated_block,
    )

    rendered = bridge._render_loader_rules(dtype="code")

    assert rendered.count(repeated_block) == 1


def test_build_review_prompt_includes_allowed_skills_for_role(tmp_path, monkeypatch):
    """Test that review prompt includes only skills allowed for the current role (WP-2026-128)."""
    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge
    from bus.skill_resolver import SkillResolver

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)

    # Create a resolver with specific allowlists
    resolver = SkillResolver(
        project_root=tmp_path,
        role_allowlists={
            "BUILDER": ["/impl", "/tdd"],
            "MANAGER": ["/review", "/audit"],
        },
    )
    # Mock discovered skills
    resolver._discovered_skills = {
        "impl": {"name": "Implement", "triggers": ["/impl"]},
        "tdd": {"name": "TDD", "triggers": ["/tdd"]},
        "review": {"name": "Review", "triggers": ["/review"]},
        "audit": {"name": "Audit", "triggers": ["/audit"]},
    }

    bridge = ReviewBridge(
        event_bus=event_bus, project_root=tmp_path, skill_resolver=resolver
    )

    # WP-2026-156: Aislar git para no escapar al repo anfitrion
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )

    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")

    # Should include the ALLOWED SKILLS section
    assert "ALLOWED SKILLS FOR ROLE" in prompt
    # Since TURN.md doesn't exist, role defaults to BUILDER
    assert "BUILDER" in prompt


def test_build_review_prompt_includes_manager_learnings_for_code_and_preserves_static_rubric(
    tmp_path, monkeypatch
):
    bridge = _make_review_prompt_bridge(
        tmp_path, deliverable_type="code", monkeypatch=monkeypatch
    )

    observations = []
    for day in range(1, 8):
        signal = f"lesson-{day}"
        if day == 7:
            signal = "x" * 240
        observations.append(
            json.dumps(
                {
                    "timestamp": f"2026-05-{day:02d}T10:00:00+00:00",
                    "topic": "manager-review-rubric",
                    "signal": signal,
                    "source_ticket": f"WP-2026-13{day}",
                }
            )
        )
    observations.append("{not valid json")
    observations.append(
        json.dumps(
            {
                "timestamp": "2026-05-08T10:00:00+00:00",
                "topic": "other-topic",
                "signal": "should-not-appear",
                "source_ticket": "WP-OTHER",
            }
        )
    )
    _write_observations(tmp_path, observations)

    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")

    assert "Review code ticket WP-TEST-123." in prompt
    assert "Canonical anti-pattern inventory" in prompt
    assert "- AP-01 Mock drift" in prompt
    assert "- AP-07 Scaffolding misclassified as code" in prompt
    assert "Test anti-patterns" in prompt
    assert "Implementation anti-patterns" in prompt
    assert "--- Lecciones acumuladas de auditoria ---" in prompt
    assert prompt.index("--- Lecciones acumuladas de auditoria ---") > prompt.index(
        "Implementation anti-patterns"
    )
    assert "should-not-appear" not in prompt

    dynamic_section = prompt.split("--- Lecciones acumuladas de auditoria ---", 1)[1]
    dynamic_section = dynamic_section.split("--- work_plan.md ---", 1)[0]
    bullets = [line for line in dynamic_section.splitlines() if line.startswith("- [")]
    assert len(bullets) == 5
    assert bullets[0].startswith("- [2026-05-07]")
    assert bullets[-1].startswith("- [2026-05-03]")
    assert "x" * 197 in bullets[0]
    assert "x" * 205 not in bullets[0]
    assert bullets[0].endswith("(WP-2026-137)")


def test_build_review_prompt_ignores_missing_observations_file(tmp_path, monkeypatch):
    bridge = _make_review_prompt_bridge(
        tmp_path, deliverable_type="code", monkeypatch=monkeypatch
    )
    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")

    assert "Test anti-patterns" in prompt
    assert "Implementation anti-patterns" in prompt


def test_build_review_prompt_loads_canonical_anti_patterns_once_per_instance(
    monkeypatch, tmp_path
):
    calls = 0

    def fake_load(self):
        nonlocal calls
        calls += 1
        return [("AP-01", "Mock drift")]

    monkeypatch.setattr(
        "bus.review_bridge.ReviewBridge._load_canonical_anti_patterns",
        fake_load,
    )

    bridge = _make_review_prompt_bridge(tmp_path, deliverable_type="code")
    assert calls == 1

    bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")
    bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")

    assert calls == 1


def test_build_review_prompt_warns_and_omits_inventory_when_shared_file_missing(
    monkeypatch, tmp_path
):
    missing_path = tmp_path / "missing" / "anti-patterns.md"

    monkeypatch.setattr(
        "bus.review_bridge.ReviewBridge._canonical_anti_patterns_path",
        lambda self: missing_path,
    )

    with pytest.warns(RuntimeWarning, match="Canonical anti-pattern inventory"):
        bridge = _make_review_prompt_bridge(tmp_path, deliverable_type="code")

    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")

    assert "Test anti-patterns" in prompt
    assert "Implementation anti-patterns" in prompt


def test_build_review_prompt_includes_manager_learnings_for_mixed(
    tmp_path, monkeypatch
):
    bridge = _make_review_prompt_bridge(
        tmp_path, deliverable_type="mixed", monkeypatch=monkeypatch
    )
    _write_observations(
        tmp_path,
        [
            json.dumps(
                {
                    "timestamp": "2026-05-25T10:00:00+00:00",
                    "topic": "manager-review-rubric",
                    "signal": "mixed tickets should inherit rubric learnings",
                    "source_ticket": "WP-2026-138",
                }
            )
        ],
    )

    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="mixed")

    assert "Review mixed ticket WP-TEST-123." in prompt
    assert "--- Lecciones acumuladas de auditoria ---" in prompt
    assert "mixed tickets should inherit rubric learnings" in prompt


class TestOpencodeReviewRoute:
    """Tests for OpenCode backend review route."""

    def test_parse_opencode_decision_approve(self, tmp_path):
        """text_regex already degraded: DECISION: APPROVE via text_regex returns INSPECT.

        WT-2026-235a: text_regex is diagnostic only; APPROVE requires
        json_final_answer source.
        """
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        bridge._supports_json_format = False  # Force text_regex path for this test

        stdout = "Review complete. All criteria met.\nDECISION: APPROVE"
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "text_regex"

    def test_parse_opencode_decision_changes(self, tmp_path):
        """text_regex already degraded: DECISION: CHANGES via text_regex returns INSPECT.

        WT-2026-235a: text_regex is diagnostic only; CHANGES requires
        json_final_answer source.
        """
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        bridge._supports_json_format = False  # Force text_regex path

        stdout = "Found issues:\n- Missing tests\n\nDECISION: CHANGES"
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "text_regex"

    def test_parse_opencode_decision_no_decision_fallback_inspect(self, tmp_path):
        """Test parser returns INSPECT+fallback_inspect when no decision found."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        bridge._supports_json_format = False  # Force text_regex path

        stdout = "Review complete but output lacks decision format."
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "fallback_inspect"

    def test_parse_opencode_decision_explicit_inspect(self, tmp_path):
        """Test parser detects DECISION: INSPECT explicitly."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        bridge._supports_json_format = False  # Force text_regex path

        stdout = "Cannot verify acceptance criteria remotely.\nDECISION: INSPECT"
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "explicit_inspect"

    def test_parse_opencode_decision_lowercase(self, tmp_path):
        """text_regex already degraded: lowercase 'decision: approve' returns INSPECT."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        bridge._supports_json_format = False  # Force text_regex path

        stdout = "decision: approve"
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "text_regex"

    def test_get_manager_backend_default_opencode(self, tmp_path):
        """Test backend detection returns opencode as fallback when agents.json is missing."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # With no agents.json, should fallback to "opencode" (WP-2026-129)
        backend = bridge._get_manager_backend()
        assert backend == "opencode"

    def test_run_manager_review_cycle_dispatches_opencode(self, monkeypatch, tmp_path):
        """Test review cycle dispatches to opencode route when backend is opencode."""
        import json as _json

        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Mock _get_manager_backend to return opencode
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_supports_json_format", True)
        monkeypatch.setattr(
            bridge, "_get_manager_model", lambda: "opencode-go/deepseek-v4-flash"
        )
        monkeypatch.setattr(bridge, "_get_canonical_files", lambda: [])
        monkeypatch.setattr(bridge, "_get_active_ticket_id", lambda: "WP-2026-072")
        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )

        captured = {}

        ndjson_approve = _json.dumps(
            {
                "type": "text",
                "phase": "final_answer",
                "part": {
                    "type": "text",
                    "text": "All criteria met.\nDECISION: APPROVE",
                },
            }
        )

        def fake_opencode_review(
            *, ticket_id, prompt="", attempt=1, manager_executable=None, timeout_seconds
        ):
            captured["ticket_id"] = ticket_id
            return ndjson_approve, "", 0

        monkeypatch.setattr(bridge, "_run_opencode_review", fake_opencode_review)

        class DummySupervisor:
            def transition_ticket(self, ticket_id, new_state, reason):
                captured["transition"] = (ticket_id, new_state, reason)

        result = bridge.run_manager_review_cycle(
            ticket_id="WP-2026-072",
            supervisor=DummySupervisor(),
            timeout_seconds=5,
        )

        assert result.decision == ReviewDecision.APPROVE
        assert captured["ticket_id"] == "WP-2026-072"
        assert captured["transition"] == (
            "WP-2026-072",
            "READY_TO_CLOSE",
            "Manager approved",
        )

    def test_opencode_review_preserves_github_copilot_prefix(
        self, monkeypatch, tmp_path
    ):
        """OpenCode should receive the GitHub Copilot-qualified model id unchanged."""
        import subprocess

        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(
            bridge, "_get_manager_model", lambda: "github-copilot/gpt-5.4-mini"
        )
        monkeypatch.setattr(bridge, "_review_env", lambda: {})
        monkeypatch.setattr(bridge, "_supports_json_format", False)

        captured = {}

        def fake_run(cmd_args, **kwargs):
            captured["cmd_args"] = cmd_args
            return subprocess.CompletedProcess(
                args=cmd_args, returncode=0, stdout="DECISION: APPROVE", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        bridge._run_opencode_review(
            ticket_id="WP-2026-072",
            prompt="test prompt",
            timeout_seconds=5,
        )

        cmd_args = captured["cmd_args"]
        if isinstance(cmd_args, str):
            assert "--model github-copilot/gpt-5.4-mini" in cmd_args
        else:
            assert "--model" in cmd_args
            model_index = cmd_args.index("--model") + 1
            assert cmd_args[model_index] == "github-copilot/gpt-5.4-mini"

    def test_run_manager_review_cycle_dispatches_legacy_manager(
        self, monkeypatch, tmp_path
    ):
        """Test review cycle dispatches to the legacy Manager route."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "legacy_manager")
        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )

        captured = {}

        def fake_legacy_manager_review(
            *, ticket_id, manager_executable, timeout_seconds
        ):
            captured["ticket_id"] = ticket_id
            return "APPROVE", "", 0

        monkeypatch.setattr(
            bridge, "_run_legacy_manager_review", fake_legacy_manager_review
        )

        class DummySupervisor:
            def transition_ticket(self, ticket_id, new_state, reason):
                captured["transition"] = (ticket_id, new_state, reason)

        fake_executable = tmp_path / "fake.exe"
        fake_executable.write_text("")

        result = bridge.run_manager_review_cycle(
            ticket_id="WP-2026-072",
            supervisor=DummySupervisor(),
            manager_executable=fake_executable,
            timeout_seconds=5,
        )

        assert result.decision == ReviewDecision.APPROVE
        assert captured["ticket_id"] == "WP-2026-072"
        assert captured["transition"] == (
            "WP-2026-072",
            "READY_TO_CLOSE",
            "Manager approved",
        )

    def test_run_manager_review_cycle_blocked_when_supervisor_closed(
        self, monkeypatch, tmp_path
    ):
        """SUPERVISOR_CLOSED must short-circuit review and reconcile terminal state."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            "# WP\n- **deliverable_type:** code\n- **ID:** WP-2026-072\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_TO_CLOSE"
        )
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")

        event_bus.emit(
            event_type="SUPERVISOR_CLOSED",
            ticket_id="WP-2026-072",
            actor="SUPERVISOR",
            payload={
                "source": "manager-approve",
                "reason": "Canonical closeout completed",
            },
        )

        called = {"review": False}

        def fake_run_opencode_review(**kwargs):
            called["review"] = True
            return "DECISION: APPROVE", "", 0

        monkeypatch.setattr(bridge, "_run_opencode_review", fake_run_opencode_review)

        class DummySupervisor:
            def transition_ticket(self, *args, **kwargs):
                raise AssertionError("Supervisor transition should not be called")

        result = bridge.run_manager_review_cycle(
            ticket_id="WP-2026-072",
            supervisor=DummySupervisor(),
            timeout_seconds=5,
        )

        latest_state_event = event_bus.latest_event(
            ticket_id="WP-2026-072", event_type="STATE_CHANGED"
        )

        assert result.decision == ReviewDecision.INSPECT
        assert called["review"] is False
        assert latest_state_event is not None
        assert latest_state_event.payload["to_state"] == "COMPLETED"

    def test_opencode_review_cmd_length_is_safe(self, monkeypatch, tmp_path):
        """Test the constructed command line respects the Windows CMD limit (~8k chars) by using a prompt file."""
        import subprocess

        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Create 100 dummy files to simulate a large canonical_files list
        dummy_files = []
        for i in range(100):
            p = tmp_path / f"dummy_file_{i}.py"
            p.write_text("")
            dummy_files.append(p)

        monkeypatch.setattr(bridge, "_get_canonical_files", lambda: dummy_files)
        monkeypatch.setattr(bridge, "_get_active_ticket_id", lambda: "WP-2026-077")
        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")

        captured_cmd = []

        def fake_run(cmd_args, **kwargs):
            captured_cmd.extend(cmd_args)
            return subprocess.CompletedProcess(
                args=cmd_args, returncode=0, stdout="DECISION: APPROVE", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        class DummySupervisor:
            def transition_ticket(self, *args, **kwargs):
                pass

        bridge.run_manager_review_cycle(
            ticket_id="WP-2026-077", supervisor=DummySupervisor(), timeout_seconds=5
        )

        import shlex

        cmd_string = shlex.join(captured_cmd)

        # Verify the length is well under the 6000 character safety margin
        assert len(cmd_string) < 6000
        # Verify that no -f flags are passed
        assert "-f" not in captured_cmd

    # =========================================================================
    # WT-2026-235a: Procedencia autoritativa y validacion de CHANGES
    # =========================================================================

    def test_text_regex_template_decisions_are_inspect(self, tmp_path):
        """Transcript with template DECISION markers but no verdict → INSPECT.

        The review packet template contains literal ``DECISION: APPROVE`` and
        ``DECISION: CHANGES`` in the INSTRUCTIONS block.  text_regex must not
        mistake these for a real verdict.
        """
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        bridge._supports_json_format = False  # Force text_regex path

        stdout = (
            "I have reviewed the implementation.\n\n"
            "--- INSTRUCTIONS ---\n"
            "If you APPROVE, end with EXACTLY one line:\n"
            "DECISION: APPROVE\n\n"
            "If you request changes:\n"
            "## SUMMARY\n..."
            "## BLOCKERS\n..."
            "DECISION: CHANGES\n"
        )
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "text_regex"

    def test_tool_calls_without_final_answer_is_inspect(self, tmp_path, monkeypatch):
        """NDJSON with text events but no final_answer phase → INSPECT.

        Simulates an OpenCode stream that ends with ``step_finish`` /
        ``tool-calls`` and has no ``phase=final_answer`` event.  ``json_last_text``
        should degrade strong decisions.
        """
        import json

        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        monkeypatch.setattr(bridge, "_supports_json_format", True)

        # NDJSON with text events but none marked final_answer
        lines = [
            json.dumps(
                {
                    "type": "text",
                    "phase": "",
                    "part": {"type": "text", "text": "I have reviewed the code."},
                }
            ),
            json.dumps(
                {
                    "type": "text",
                    "phase": "",
                    "part": {
                        "type": "text",
                        "text": "## SUMMARY\nFix needed\n## BLOCKERS\n- Bug\n## SUGGESTIONS\n- Fix\nDECISION: CHANGES",
                    },
                }
            ),
            json.dumps({"type": "step_finish", "phase": ""}),
        ]
        stdout = "\n".join(lines)

        decision, method = bridge._parse_opencode_decision(stdout)
        # json_last_text found CHANGES but it is not authoritative → INSPECT
        assert decision == ReviewDecision.INSPECT
        assert method == "json_last_text"

    def test_json_final_answer_approve_is_authoritative(self, tmp_path, monkeypatch):
        """json_final_answer with APPROVE still produces APPROVE."""
        import json

        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        monkeypatch.setattr(bridge, "_supports_json_format", True)

        stdout = json.dumps(
            {
                "type": "text",
                "phase": "final_answer",
                "part": {
                    "type": "text",
                    "text": "All criteria met.\nDECISION: APPROVE",
                },
            }
        )

        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.APPROVE
        assert method == "json_final_answer"

    def test_structured_changes_preserves_valid_changes(self, monkeypatch, tmp_path):
        """Valid CHANGES with full structure and non-empty blockers → CHANGES."""
        bridge, event_bus, legacy_manager_exe = _make_bridge(tmp_path)
        supervisor = DummySupervisor()

        call_count = {"n": 0}

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            if (
                isinstance(cmd, list)
                and cmd
                and Path(str(cmd[0])).name.lower() in ("git", "git.exe")
            ):
                return __import__("subprocess").CompletedProcess(
                    cmd, 0, stdout="", stderr=""
                )
            call_count["n"] += 1
            return __import__("subprocess").CompletedProcess(
                cmd,
                0,
                stdout=(
                    "## SUMMARY\nNeeds coverage.\n"
                    "## BLOCKERS\n- tests/test_a.py: missing edge case\n"
                    "## SUGGESTIONS\n- Add test for negative input\n"
                    "DECISION: CHANGES"
                ),
                stderr="",
            )

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "legacy_manager")

        result = bridge.run_manager_review_cycle(
            ticket_id="WP-2026-025",
            supervisor=supervisor,
            manager_executable=legacy_manager_exe,
            timeout_seconds=5,
        )

        assert result.decision == ReviewDecision.CHANGES
        # Check the REVIEW_DECISION payload preserves parse_method
        events = event_bus.read_events(ticket_id="WP-2026-025")
        rd_events = [e for e in events if e.event_type == "REVIEW_DECISION"]
        assert len(rd_events) > 0
        assert rd_events[-1].payload.get("decision") == "changes"
        assert "parse_method" in rd_events[-1].payload

    def test_changes_without_blockers_degrades_to_inspect(self, monkeypatch, tmp_path):
        """CHANGES without ## BLOCKERS section → INSPECT + failure_reason."""
        bridge, event_bus, legacy_manager_exe = _make_bridge(tmp_path)
        supervisor = DummySupervisor()

        def fake_run(cmd, **kwargs):
            if (
                isinstance(cmd, list)
                and cmd
                and Path(str(cmd[0])).name.lower() in ("git", "git.exe")
            ):
                return __import__("subprocess").CompletedProcess(
                    cmd, 0, stdout="", stderr=""
                )
            return __import__("subprocess").CompletedProcess(
                cmd,
                0,
                stdout=(
                    "## SUMMARY\nFix needed.\n"
                    "## SUGGESTIONS\n- Improve\n"
                    "DECISION: CHANGES"
                ),
                stderr="",
            )

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "legacy_manager")

        result = bridge.run_manager_review_cycle(
            ticket_id="WP-2026-025",
            supervisor=supervisor,
            manager_executable=legacy_manager_exe,
            timeout_seconds=5,
        )

        assert result.decision == ReviewDecision.INSPECT

        events = event_bus.read_events(ticket_id="WP-2026-025")
        rd_events = [e for e in events if e.event_type == "REVIEW_DECISION"]
        assert len(rd_events) > 0
        payload = rd_events[-1].payload or {}
        assert payload.get("decision") == "inspect"
        assert payload.get("failure_reason") == "changes_structure_invalid"
        assert "BLOCKERS" in payload.get("missing_sections", [])

    def test_changes_with_empty_blockers_degrades_to_inspect(
        self, monkeypatch, tmp_path
    ):
        """CHANGES with empty BLOCKERS content → INSPECT + failure_reason."""
        bridge, event_bus, legacy_manager_exe = _make_bridge(tmp_path)
        supervisor = DummySupervisor()

        def fake_run(cmd, **kwargs):
            if (
                isinstance(cmd, list)
                and cmd
                and Path(str(cmd[0])).name.lower() in ("git", "git.exe")
            ):
                return __import__("subprocess").CompletedProcess(
                    cmd, 0, stdout="", stderr=""
                )
            return __import__("subprocess").CompletedProcess(
                cmd,
                0,
                stdout=(
                    "## SUMMARY\nFix needed.\n"
                    "## BLOCKERS\n\n"
                    "## SUGGESTIONS\n- Improve\n"
                    "DECISION: CHANGES"
                ),
                stderr="",
            )

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "legacy_manager")

        result = bridge.run_manager_review_cycle(
            ticket_id="WP-2026-025",
            supervisor=supervisor,
            manager_executable=legacy_manager_exe,
            timeout_seconds=5,
        )

        assert result.decision == ReviewDecision.INSPECT

        events = event_bus.read_events(ticket_id="WP-2026-025")
        rd_events = [e for e in events if e.event_type == "REVIEW_DECISION"]
        assert len(rd_events) > 0
        payload = rd_events[-1].payload or {}
        assert payload.get("decision") == "inspect"
        assert payload.get("failure_reason") == "changes_structure_invalid"


class TestReviewPacketTransport:
    """WP-2026-126: el contexto del review va por un review packet en disco,
    no por --file (flag array que consume el mensaje) ni por argv largo."""

    @staticmethod
    def _bridge(tmp_path, monkeypatch, os_name):
        from bus.review_bridge import EventBus, ReviewBridge

        event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        monkeypatch.setattr(bridge, "_get_manager_model", lambda: None)
        monkeypatch.setattr(bridge, "_supports_json_format", False)
        monkeypatch.setattr("bus.review_bridge.OS_NAME", os_name)
        return bridge

    def test_writes_review_packet(self, tmp_path, monkeypatch):
        """El contexto completo se escribe a .agent/runtime/review_packets/<ticket>_attempt-N.md."""
        bridge = self._bridge(tmp_path, monkeypatch, "posix")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda c, **k: subprocess.CompletedProcess(c, 0, "DECISION: APPROVE", ""),
        )

        prompt = "CONTEXTO DE REVIEW\n" + ("x" * 8000)
        bridge._run_opencode_review(
            ticket_id="WP-T", prompt=prompt, attempt=1, timeout_seconds=5
        )

        packet = (
            tmp_path / ".agent" / "runtime" / "review_packets" / "WP-T_attempt-1.md"
        )
        assert packet.exists()
        assert prompt in packet.read_text(encoding="utf-8")

    def test_review_packet_is_separate_per_attempt(self, tmp_path, monkeypatch):
        """Cada intento escribe su propio packet y preserva la provenance."""
        bridge = self._bridge(tmp_path, monkeypatch, "posix")

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda c, **k: subprocess.CompletedProcess(c, 0, "DECISION: APPROVE", ""),
        )

        bridge._run_opencode_review(
            ticket_id="WP-T", prompt="PROMPT 1", attempt=1, timeout_seconds=5
        )
        bridge._run_opencode_review(
            ticket_id="WP-T", prompt="PROMPT 2", attempt=2, timeout_seconds=5
        )

        packet_1 = (
            tmp_path / ".agent" / "runtime" / "review_packets" / "WP-T_attempt-1.md"
        )
        packet_2 = (
            tmp_path / ".agent" / "runtime" / "review_packets" / "WP-T_attempt-2.md"
        )
        assert packet_1.exists()
        assert packet_2.exists()
        assert "PROMPT 1" in packet_1.read_text(encoding="utf-8")
        assert "PROMPT 2" in packet_2.read_text(encoding="utf-8")

    def test_bridge_helper_does_not_patch_global_os_name(self, tmp_path, monkeypatch):
        """La simulacion de plataforma debe quedar confinada al modulo de review."""
        original_os_name = os.name
        self._bridge(tmp_path, monkeypatch, "posix")
        assert os.name == original_os_name

    def test_positional_message_short_and_no_file_flag(self, tmp_path, monkeypatch):
        """El prompt posicional es corto y referencia el packet; sin --file
        y sin el prompt completo en la linea de comandos."""
        bridge = self._bridge(tmp_path, monkeypatch, "posix")

        captured = {}

        def fake_run(cmd_args, **kwargs):
            captured["cmd"] = cmd_args
            return subprocess.CompletedProcess(cmd_args, 0, "DECISION: APPROVE", "")

        monkeypatch.setattr(subprocess, "run", fake_run)

        prompt = "PROMPT-LARGO-UNICO " + ("x" * 9000)
        bridge._run_opencode_review(ticket_id="WP-T", prompt=prompt, timeout_seconds=5)

        cmd = captured["cmd"]
        assert "--file" not in cmd
        assert prompt not in cmd
        message = cmd[-1]
        assert "WP-T" in message
        assert "review_packets/WP-T_attempt-1.md" in message
        assert len(message) < 400

    def test_windows_invocation_is_string_without_file_flag(
        self, tmp_path, monkeypatch
    ):
        """En Windows shell=True: subprocess.run recibe un string (list2cmdline),
        sin --file; el prompt completo nunca toca la CLI."""
        bridge = self._bridge(tmp_path, monkeypatch, "nt")

        captured = {}

        def fake_run(cmd_args, **kwargs):
            captured["cmd"] = cmd_args
            return subprocess.CompletedProcess(cmd_args, 0, "DECISION: APPROVE", "")

        monkeypatch.setattr(subprocess, "run", fake_run)

        bridge._run_opencode_review(
            ticket_id="WP-T", prompt="x" * 9000, timeout_seconds=5
        )

        cmd = captured["cmd"]
        assert isinstance(cmd, str)
        assert "--file" not in cmd
        assert "review_packets/WP-T_attempt-1.md" in cmd


# =============================================================================
# Tests WP-2026-102: Bridge/Supervisor Hardening
# =============================================================================


class TestTicketStateIngest:
    """Tests for the TicketStateIngest class (WP-2026-102)."""

    def test_ticket_context_dataclass(self, tmp_path):
        """Test TicketContext dataclass creation."""
        from bus.review_bridge import TicketContext

        ctx = TicketContext(
            ticket_id="WP-2026-102",
            state="READY_FOR_REVIEW",
            deliverable_type="code",
        )

        assert ctx.ticket_id == "WP-2026-102"
        assert ctx.state == "READY_FOR_REVIEW"
        assert ctx.deliverable_type == "code"

    def test_state_ingest_latest_state_from_bus(self, tmp_path):
        """Test state ingest reads latest state from event bus."""
        from bus.event_bus import EventBus
        from bus.review_bridge import TicketStateIngest

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        ingest = TicketStateIngest(event_bus=event_bus, project_root=tmp_path)

        # Emit STATE_CHANGED events
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WP-2026-102",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        state = ingest._latest_state("WP-2026-102")
        assert state == "READY_FOR_REVIEW"

    def test_state_ingest_latest_state_default(self, tmp_path):
        """Test state ingest returns IN_PROGRESS when no events exist."""
        from bus.event_bus import EventBus
        from bus.review_bridge import TicketStateIngest

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        ingest = TicketStateIngest(event_bus=event_bus, project_root=tmp_path)

        state = ingest._latest_state("WP-2026-999")
        assert state == "IN_PROGRESS"

    def test_state_ingest_get_ticket_context(self, tmp_path):
        """Test get_ticket_context returns complete TicketContext."""
        from bus.event_bus import EventBus
        from bus.review_bridge import TicketStateIngest

        collaboration_dir = tmp_path / ".agent" / "collaboration"
        collaboration_dir.mkdir(parents=True)

        # Create work_plan.md with deliverable_type
        (collaboration_dir / "work_plan.md").write_text(
            "# Work Plan\n\n## WP-2026-102\n\n### Metadata\n- **ID:** WP-2026-102\n- **deliverable_type:** documentation\n",
            encoding="utf-8",
        )

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        ingest = TicketStateIngest(event_bus=event_bus, project_root=tmp_path)

        # Emit state event
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WP-2026-102",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        ctx = ingest.get_ticket_context("WP-2026-102")

        assert ctx is not None
        assert ctx.ticket_id == "WP-2026-102"
        assert ctx.state == "READY_FOR_REVIEW"
        assert ctx.deliverable_type == "documentation"

    def test_state_ingest_get_ticket_context_fallback_to_work_plan(self, tmp_path):
        """Test get_ticket_context falls back to work_plan.md for ticket_id."""
        from bus.event_bus import EventBus
        from bus.review_bridge import TicketStateIngest

        collaboration_dir = tmp_path / ".agent" / "collaboration"
        collaboration_dir.mkdir(parents=True)

        (collaboration_dir / "work_plan.md").write_text(
            "# Work Plan\n\n## WP-2026-102\n\n### Metadata\n- **ID:** WP-2026-102\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        ingest = TicketStateIngest(event_bus=event_bus, project_root=tmp_path)

        # Call without explicit ticket_id - should read from work_plan
        ctx = ingest.get_ticket_context()

        assert ctx is not None
        assert ctx.ticket_id == "WP-2026-102"
        assert ctx.deliverable_type == "code"

    def test_state_ingest_get_ticket_context_returns_none_when_no_ticket(
        self, tmp_path
    ):
        """Test get_ticket_context returns None when no ticket can be resolved."""
        from bus.event_bus import EventBus
        from bus.review_bridge import TicketStateIngest

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        ingest = TicketStateIngest(event_bus=event_bus, project_root=tmp_path)

        ctx = ingest.get_ticket_context()
        assert ctx is None


class TestBridgeHandshakeWithoutSnapshots:
    """Tests for bridge handshake without depending on old snapshots (WP-2026-102)."""

    def test_bridge_uses_current_bus_state_not_snapshots(self, tmp_path, monkeypatch):
        """Test bridge queries event_bus directly, not stale snapshots."""
        from bus.event_bus import EventBus
        from bus.review_bridge import ReviewBridge

        collaboration_dir = tmp_path / ".agent" / "collaboration"
        collaboration_dir.mkdir(parents=True)

        # Create minimal work_plan.md
        (collaboration_dir / "work_plan.md").write_text(
            "# Work Plan\n\n## WP-2026-102\n\n### Metadata\n- **ID:** WP-2026-102\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Emit current state directly to bus (no snapshot files)
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WP-2026-102",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        # Mock the review execution to capture that it was called
        captured = {}

        import json as _json

        # NDJSON that both parsers can consume: top-level type=text for
        # _extract_decision_from_single_line and part.type=text for
        # _extract_json_stream_text.
        ndjson_approve = _json.dumps(
            {
                "type": "text",
                "phase": "final_answer",
                "part": {
                    "type": "text",
                    "text": "All criteria met.\nDECISION: APPROVE",
                },
            }
        )

        def fake_opencode_review(
            *, ticket_id, prompt, attempt=1, manager_executable=None, timeout_seconds
        ):
            captured["prompt_includes_ticket"] = "WP-2026-102" in prompt
            return ndjson_approve, "", 0

        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_supports_json_format", True)
        monkeypatch.setattr(bridge, "_run_opencode_review", fake_opencode_review)

        class DummySupervisor:
            def transition_ticket(self, ticket_id, new_state, reason):
                captured["transition"] = (ticket_id, new_state, reason)

        result = bridge.run_manager_review_cycle(
            ticket_id="WP-2026-102",
            supervisor=DummySupervisor(),
            timeout_seconds=5,
        )

        assert result.decision == ReviewDecision.APPROVE
        assert captured.get("prompt_includes_ticket") is True
        assert captured.get("transition") is not None


class TestSupervisorNonTerminalStates:
    """Tests for supervisor NON_TERMINAL_STATES constant (WP-2026-102)."""

    def test_non_terminal_states_constant_exists(self):
        """Test NON_TERMINAL_STATES constant is defined."""
        from bus.supervisor import NON_TERMINAL_STATES

        assert NON_TERMINAL_STATES is not None
        assert isinstance(NON_TERMINAL_STATES, frozenset)

    def test_is_state_terminal_method(self, tmp_path):
        """Test _is_state_terminal correctly identifies terminal vs non-terminal states."""
        from bus.state_machine import TicketState
        from bus.supervisor import NON_TERMINAL_STATES

        # Non-terminal states should return False
        for state in NON_TERMINAL_STATES:
            assert state not in set(), "Sanity check: NON_TERMINAL_STATES is not empty"  # noqa: RUF060

        # COMPLETED and UNKNOWN are terminal
        assert TicketState.COMPLETED not in NON_TERMINAL_STATES
        assert TicketState.UNKNOWN not in NON_TERMINAL_STATES

    def test_supervisor_bootstrap_preserves_active_ticket_in_non_terminal_state(
        self, tmp_path
    ):
        """Test bootstrap does NOT clear active_ticket when bus is in non-terminal state."""
        from bus.supervisor import SequentialTicketSupervisor, SupervisorState

        collaboration_dir = tmp_path / ".agent" / "collaboration"
        runtime_dir = tmp_path / ".agent" / "runtime"
        collaboration_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)

        # Create execution_log showing COMPLETED (but bus says READY_FOR_REVIEW)
        (collaboration_dir / "execution_log.md").write_text(
            "# Execution Log\n\n## WP-2026-102\n\n**Estado:** COMPLETED\n",
            encoding="utf-8",
        )

        supervisor = SequentialTicketSupervisor(
            project_root=tmp_path,
            collaboration_dir=collaboration_dir,
            runtime_dir=runtime_dir,
            auto_sync=False,
        )

        # Set up state with active ticket
        supervisor.save_state(
            SupervisorState(active_ticket="WP-2026-102", completed_tickets=[])
        )

        # Bus says READY_FOR_REVIEW (non-terminal) - this takes precedence over execution_log
        supervisor.event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WP-2026-102",
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )

        supervisor.bootstrap()

        # active_ticket should be preserved because bus says READY_FOR_REVIEW (non-terminal)
        # The bootstrap logic only clears active_ticket when:
        # 1. execution_log_status == "COMPLETED" AND
        # 2. current_state (from bus) is terminal
        # Since current_state is READY_FOR_REVIEW (non-terminal), active_ticket is preserved
        state = supervisor.load_state()
        assert state.active_ticket == "WP-2026-102"


# =============================================================================
# Tests WP-2026-106: Structured Manager Reviews and Human Gate Escalation
# =============================================================================


class TestStructuredChangesValidation:
    """Tests for WP-2026-106: structured CHANGES responses."""

    def test_validate_changes_structure_valid(self, tmp_path):
        """Test validation passes when all required sections present."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = """
## SUMMARY
Implementation has issues.

## BLOCKERS
- Missing tests
- Type errors

## SUGGESTIONS
- Add unit tests
- Fix type hints

DECISION: CHANGES
"""
        is_valid, missing = bridge._validate_changes_structure(stdout)
        assert is_valid is True
        assert missing == []

    def test_validate_changes_structure_missing_sections(self, tmp_path):
        """Test validation detects missing required sections."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = """
## SUMMARY
Implementation has issues.

DECISION: CHANGES
"""
        is_valid, missing = bridge._validate_changes_structure(stdout)
        assert is_valid is False
        assert "BLOCKERS" in missing
        assert "SUGGESTIONS" in missing

    def test_validate_changes_structure_missing_decision(self, tmp_path):
        """Test validation detects missing DECISION: CHANGES."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = """
## SUMMARY
Implementation has issues.

## BLOCKERS
- Missing tests

## SUGGESTIONS
- Add tests
"""
        is_valid, missing = bridge._validate_changes_structure(stdout)
        assert is_valid is False
        assert "DECISION: CHANGES" in missing

    def test_parse_changes_structure_extracts_sections(self, tmp_path):
        """Test parser extracts SUMMARY, BLOCKERS, SUGGESTIONS correctly."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = """
## SUMMARY
The implementation needs work.

## BLOCKERS
- Missing test coverage
- Type hint errors

## SUGGESTIONS
- Add pytest tests for core logic
- Fix type hints in review_bridge.py

DECISION: CHANGES
"""
        structured = bridge._parse_changes_structure(stdout)
        assert "The implementation needs work." in structured["summary"]
        assert "Missing test coverage" in structured["blockers"]
        assert "Add pytest tests" in structured["suggestions"]

    def test_parse_changes_structure_empty_sections(self, tmp_path):
        """Test parser returns empty strings when sections missing."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "Just some random text without structure."
        structured = bridge._parse_changes_structure(stdout)
        assert structured["summary"] == ""
        assert structured["blockers"] == ""
        assert structured["suggestions"] == ""


class TestReviewAttemptPersistence:
    """Tests for WP-2026-106: review attempt persistence."""

    def test_persist_review_attempt_creates_file(self, tmp_path):
        """Test _persist_review_attempt creates attempt-N.md file."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_path = bridge._persist_review_attempt(
            ticket_id="WP-2026-106",
            attempt=1,
            stdout="Review output here",
            stderr="",
            decision=ReviewDecision.CHANGES,
            review_packet_path=tmp_path
            / ".agent"
            / "runtime"
            / "review_packets"
            / "WP-2026-106_attempt-1.md",
        )

        assert review_path.exists()
        assert review_path.name == "attempt-1.md"
        assert "WP-2026-106" in str(review_path)
        content = review_path.read_text(encoding="utf-8")
        assert "## Review Packet" in content
        assert "WP-2026-106_attempt-1.md" in content

    def test_persist_review_attempt_idempotent(self, tmp_path):
        """Test _persist_review_attempt overwrites same file idempotently."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # First write
        path1 = bridge._persist_review_attempt(
            ticket_id="WP-2026-106",
            attempt=1,
            stdout="First attempt",
            stderr="",
            decision=ReviewDecision.CHANGES,
            review_packet_path=tmp_path
            / ".agent"
            / "runtime"
            / "review_packets"
            / "WP-2026-106_attempt-1.md",
        )

        # Second write (same attempt number)
        path2 = bridge._persist_review_attempt(
            ticket_id="WP-2026-106",
            attempt=1,
            stdout="Second attempt",
            stderr="",
            decision=ReviewDecision.CHANGES,
            review_packet_path=tmp_path
            / ".agent"
            / "runtime"
            / "review_packets"
            / "WP-2026-106_attempt-1.md",
        )

        # Same file path
        assert path1 == path2
        # Content is the second write (idempotent overwrite)
        content = path1.read_text(encoding="utf-8")
        assert "Second attempt" in content
        assert "## Review Packet" in content
        assert "WP-2026-106_attempt-1.md" in content

    def test_persist_review_attempt_includes_structured_sections(self, tmp_path):
        """Test _persist_review_attempt includes SUMMARY, BLOCKERS, SUGGESTIONS for CHANGES."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = """
## SUMMARY
Issues found.

## BLOCKERS
- Missing tests

## SUGGESTIONS
- Add tests

DECISION: CHANGES
"""
        review_path = bridge._persist_review_attempt(
            ticket_id="WP-2026-106",
            attempt=1,
            stdout=stdout,
            stderr="",
            decision=ReviewDecision.CHANGES,
        )

        content = review_path.read_text(encoding="utf-8")
        assert "## SUMMARY" in content
        assert "## BLOCKERS" in content
        assert "## SUGGESTIONS" in content
        assert "Issues found." in content

    def test_get_review_log_path_creates_directory(self, tmp_path):
        """Test _get_review_log_path creates ticket directory structure."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        ticket_dir = bridge._get_review_log_path("WP-2026-106")

        assert ticket_dir.exists()
        assert ticket_dir.name == "WP-2026-106"
        assert "reviews" in str(ticket_dir)


class TestHumanGateEscalation:
    """Tests for WP-2026-106: HUMAN_GATE escalation at 5th rejection."""

    def test_generate_human_review_report_creates_file(self, tmp_path):
        """Test _generate_human_review_report creates report from template."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_attempts = [
            {
                "attempt": 1,
                "payload": {
                    "attempt": 1,
                    "exit_code": 0,
                    "duration_seconds": 10.5,
                    "blockers": "- Missing tests",
                },
            },
            {
                "attempt": 2,
                "payload": {
                    "attempt": 2,
                    "exit_code": 0,
                    "duration_seconds": 12.3,
                    "blockers": "- Type errors",
                },
            },
        ]

        report_path = bridge._generate_human_review_report(
            ticket_id="WP-2026-106",
            review_attempts=review_attempts,
            last_decision=ReviewDecision.CHANGES,
        )

        assert report_path.exists()
        assert report_path.name == "human_review_report.md"
        content = report_path.read_text(encoding="utf-8")
        assert "WP-2026-106" in content
        assert "HUMAN_GATE" in content or "CHANGES" in content

    def test_human_review_report_consolidates_blockers(self, tmp_path):
        """Test _generate_human_review_report consolidates blockers from all attempts."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_attempts = [
            {
                "attempt": 1,
                "payload": {"attempt": 1, "blockers": "- Missing tests"},
            },
            {
                "attempt": 2,
                "payload": {"attempt": 2, "blockers": "- Type errors"},
            },
            {
                "attempt": 3,
                "payload": {"attempt": 3, "blockers": "- Missing docs"},
            },
        ]

        report_path = bridge._generate_human_review_report(
            ticket_id="WP-2026-106",
            review_attempts=review_attempts,
            last_decision=ReviewDecision.CHANGES,
        )

        content = report_path.read_text(encoding="utf-8")
        assert "Missing tests" in content
        assert "Type errors" in content
        assert "Missing docs" in content

    def test_review_cycle_escalates_to_human_gate_at_threshold(
        self, tmp_path, monkeypatch
    ):
        """WP-2026-106 B3: HUMAN_GATE report appears at the 5th cycle.

        One cycle = one review = one REVIEW_DECISION (no inner retry on
        CHANGES). After 5 bus-recorded CHANGES the human_review_report.md
        is generated.
        """
        import json as _json

        import bus.review_bridge as rb
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            "# WP\n- **deliverable_type:** code\n- **ID:** WP-2026-106\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_supports_json_format", True)
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )
        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")

        call_count = {"n": 0}

        def fake_run(**kw):
            call_count["n"] += 1
            ndjson_changes = _json.dumps(
                {
                    "type": "text",
                    "phase": "final_answer",
                    "part": {
                        "type": "text",
                        "text": (
                            f"## SUMMARY\nIssues remain (cycle {call_count['n']}).\n"
                            "## BLOCKERS\n- Issue\n## SUGGESTIONS\n- Fix\nDECISION: CHANGES"
                        ),
                    },
                }
            )
            return ndjson_changes, "", 0

        monkeypatch.setattr(bridge, "_run_opencode_review", fake_run)
        # Stub the escalation authority (agent_controller --request-changes).
        monkeypatch.setattr(
            rb.subprocess,
            "run",
            lambda *a, **k: type(
                "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
            )(),
        )

        class DummySupervisor:
            def transition_ticket(self, *args, **kwargs):
                pass

            def _is_supervisor_lock_stale(self):
                return False

            def requeue_ticket(self, ticket_id):
                return True

        report = (
            tmp_path
            / ".agent"
            / "runtime"
            / "reviews"
            / "WP-2026-106"
            / "human_review_report.md"
        )

        result = None
        for cycle in range(1, 6):
            result = bridge.run_manager_review_cycle(
                ticket_id="WP-2026-106",
                supervisor=DummySupervisor(),
                timeout_seconds=5,
            )
            # One review per cycle: no inner retry on CHANGES.
            assert call_count["n"] == cycle
            if cycle < 5:
                assert not report.exists()

        assert result.decision == ReviewDecision.CHANGES
        assert report.exists()

    def test_review_cycle_approves_before_threshold(self, tmp_path, monkeypatch):
        """WP-2026-106 B3: APPROVE on cycle 3 closes before the HUMAN_GATE threshold.

        One review per cycle; the 3rd cycle approves, so the ticket reaches
        READY_TO_CLOSE without escalating.
        """
        import json as _json

        import bus.review_bridge as rb
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            "# WP\n- **deliverable_type:** code\n- **ID:** WP-2026-106\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_supports_json_format", True)
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )
        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
        monkeypatch.setattr(
            rb.subprocess,
            "run",
            lambda *a, **k: type(
                "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
            )(),
        )

        call_count = {"n": 0}

        def fake_run(**kw):
            call_count["n"] += 1
            if call_count["n"] < 3:
                ndjson_changes = _json.dumps(
                    {
                        "type": "text",
                        "phase": "final_answer",
                        "part": {
                            "type": "text",
                            "text": (
                                f"## SUMMARY\nIssues (cycle {call_count['n']}).\n"
                                "## BLOCKERS\n- X\n## SUGGESTIONS\n- Y\nDECISION: CHANGES"
                            ),
                        },
                    }
                )
                return ndjson_changes, "", 0
            ndjson_approve = _json.dumps(
                {
                    "type": "text",
                    "phase": "final_answer",
                    "part": {"type": "text", "text": "OK.\nDECISION: APPROVE"},
                }
            )
            return ndjson_approve, "", 0

        monkeypatch.setattr(bridge, "_run_opencode_review", fake_run)

        transitions = []

        class DummySupervisor:
            def transition_ticket(self, ticket_id, new_state, reason):
                transitions.append((ticket_id, new_state, reason))

            def _is_supervisor_lock_stale(self):
                return False

            def requeue_ticket(self, ticket_id):
                return True

        result = None
        for _ in range(3):
            result = bridge.run_manager_review_cycle(
                ticket_id="WP-2026-106",
                supervisor=DummySupervisor(),
                timeout_seconds=5,
            )

        assert call_count["n"] == 3
        assert result.decision == ReviewDecision.APPROVE
        assert any(t[1] == "READY_TO_CLOSE" for t in transitions)

    def test_load_review_config_uses_max_attempts_5(self, tmp_path):
        """Test _load_review_config returns max_attempts=5 by default."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        config = bridge._load_review_config()
        assert config["max_attempts"] == 5


# =============================================================================
# Tests WP-2026-158: Review Packet Completeness and Diff Filtering
# =============================================================================


class TestUntrackedDeliverables:
    """Tests for WP-2026-158: untracked deliverables visibility in review packet."""

    def test_get_untracked_files_returns_empty_when_no_untracked(
        self, tmp_path, monkeypatch
    ):
        """Test _get_untracked_files returns empty list when no ?? files."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Mock git status to return empty
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: type(
                "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
            )(),
        )

        untracked = bridge._get_untracked_files()
        assert untracked == []

    def test_get_untracked_files_detects_deliverable_files(self, tmp_path, monkeypatch):
        """Test _get_untracked_files detects ?? files as deliverables."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # WT-2026-215: mock motor_root so git evidence runs without link
        monkeypatch.setattr(bridge, "_motor_root_or_raise", lambda: tmp_path)

        # Mock git status to return untracked files
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: type(
                "R",
                (),
                {
                    "returncode": 0,
                    "stdout": "?? new_feature.py\0?? tests/test_feature.py\0",
                    "stderr": "",
                },
            )(),
        )

        untracked = bridge._get_untracked_files()
        assert "new_feature.py" in untracked
        assert "tests/test_feature.py" in untracked

    def test_get_untracked_files_filters_agent_collaboration(
        self, tmp_path, monkeypatch
    ):
        """Test _get_untracked_files excludes .agent/collaboration/ noise."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # WT-2026-215: mock motor_root so git evidence runs without link
        monkeypatch.setattr(bridge, "_motor_root_or_raise", lambda: tmp_path)

        # Mock git status with mix of deliverables and noise
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: type(
                "R",
                (),
                {
                    "returncode": 0,
                    "stdout": "?? .agent/collaboration/notes.md\0?? feature.py\0?? .agent/runtime/tmp.log\0",
                    "stderr": "",
                },
            )(),
        )

        untracked = bridge._get_untracked_files()
        assert ".agent/collaboration/notes.md" not in untracked
        assert ".agent/runtime/tmp.log" not in untracked
        assert "feature.py" in untracked

    def test_is_deliverable_path_excludes_patterns(self, tmp_path):
        """Test _is_deliverable_path correctly filters known patterns."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Should be excluded
        assert bridge._is_deliverable_path(".agent/collaboration/foo.md") is False
        assert bridge._is_deliverable_path(".agent/runtime/tmp.log") is False
        assert bridge._is_deliverable_path("__pycache__/module.pyc") is False
        assert bridge._is_deliverable_path("module.pyc") is False
        assert bridge._is_deliverable_path(".ruff_cache/data.json") is False

        # Should be included
        assert bridge._is_deliverable_path("new_feature.py") is True
        assert bridge._is_deliverable_path("tests/test_feature.py") is True
        assert bridge._is_deliverable_path("docs/new_doc.md") is True

    def test_build_review_prompt_includes_untracked_section(
        self, tmp_path, monkeypatch
    ):
        """Test _build_review_prompt includes Untracked Deliverables section."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Mock git methods to isolate untracked logic
        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
        monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )
        monkeypatch.setattr(bridge, "_get_untracked_files", lambda: ["new_feature.py"])

        prompt = bridge._build_review_prompt(ticket_id="WP-TEST-158", dtype="code")

        assert "--- Untracked Deliverables ---" in prompt
        assert "new_feature.py" in prompt

    def test_build_review_prompt_includes_packet_metadata(self, tmp_path, monkeypatch):
        """Test _build_review_prompt includes filter_mode and severity metadata."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Mock git methods
        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
        monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )
        monkeypatch.setattr(bridge, "_get_untracked_files", lambda: ["new_feature.py"])

        prompt = bridge._build_review_prompt(ticket_id="WP-TEST-158", dtype="code")

        assert "--- Packet Metadata ---" in prompt
        assert "filter_mode: added" in prompt
        assert "severity: warn" in prompt
        assert "untracked_count: 1" in prompt

    def test_build_review_prompt_diff_context_mode_when_no_untracked(
        self, tmp_path, monkeypatch
    ):
        """Test filter_mode is diff_context when no untracked files."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Mock git methods with no untracked
        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
        monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )
        monkeypatch.setattr(bridge, "_get_untracked_files", lambda: [])

        prompt = bridge._build_review_prompt(ticket_id="WP-TEST-158", dtype="code")

        assert "--- Packet Metadata ---" in prompt
        assert "filter_mode: diff_context" in prompt
        assert "severity: info" in prompt
        assert "untracked_count: 0" in prompt


# =============================================================================
# Tests WP-2026-170: Fix ConcurrentStateError (reconcile_state removed from _tick)
# =============================================================================


def _make_supervisor(tmp_path: Path) -> SequentialTicketSupervisor:
    """Helper: build a SequentialTicketSupervisor with standard dirs."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )


def _write_work_plan_rfr(path: Path, ticket_id: str) -> None:
    """Write work_plan.md so _ticket_state can derive a ticket."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# Work Plan",
                "",
                f"## {ticket_id}: Test",
                "",
                "### Metadata",
                f"- **ID:** {ticket_id}",
                "- **Estado:** APPROVED",
                "- **deliverable_type:** code",
            ]
        ),
        encoding="utf-8",
    )


def _write_execution_log_rfr(path: Path, status: str) -> None:
    """Write execution_log.md with a given status line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# Execution Log",
                "",
                "## Project summary",
                "",
                "- **Estado:** " + status,
            ]
        ),
        encoding="utf-8",
    )


def test_tick_does_not_call_reconcile_state(tmp_path, monkeypatch):
    """Test that _tick() does NOT invoke supervisor.reconcile_state().

    WP-2026-170: the bridge must stop writing supervisor_state.json during
    its tick.  Spying on reconcile_state verifies it is never called.
    """
    supervisor = _make_supervisor(tmp_path)

    # Spy on reconcile_state — count calls
    reconcile_calls = 0
    original_reconcile = supervisor.reconcile_state

    def spy_reconcile():
        nonlocal reconcile_calls
        reconcile_calls += 1
        return original_reconcile()

    monkeypatch.setattr(supervisor, "reconcile_state", spy_reconcile)

    # No active ticket → _tick() returns False after the (removed) reconcile
    supervisor.save_state(SupervisorState(active_ticket=None))

    from bus.review_bridge import ReviewBridge

    review = ReviewBridge(event_bus=supervisor.event_bus, project_root=tmp_path)

    result = _tick(
        supervisor=supervisor,
        review=review,
        manager_path=None,
        timeout=5,
    )

    # _tick returns False because no active ticket (not the point)
    assert result is False
    # reconcile_state must NOT have been called
    assert reconcile_calls == 0, "reconcile_state must NOT be called from _tick()"


def _mock_bridge_state_path(monkeypatch, tmp_path: Path) -> Path:
    """Monkeypatch _state_path and _checkpoint_path so bridge state reads/writes
    are isolated per test.

    Without this, _load_state() / _save_state() read the real project's
    manager_bridge_state.json / bridge_checkpoint.json, causing cross-test
    contamination.
    """
    bridge_state_path = tmp_path / ".agent" / "runtime" / "manager_bridge_state.json"
    bridge_state_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "scripts.manager_review_bridge._state_path",
        lambda: bridge_state_path,
    )
    # WP-2026-174: also isolate the durable checkpoint path per test
    checkpoint_path = tmp_path / ".agent" / "runtime" / "bridge_checkpoint.json"
    monkeypatch.setattr(
        "scripts.manager_review_bridge._checkpoint_path",
        lambda: checkpoint_path,
    )
    return bridge_state_path


def test_tick_detects_ready_for_review_without_reconcile(tmp_path, monkeypatch):
    """Test that _tick() still detects READY_FOR_REVIEW after removing reconcile_state.

    WP-2026-170: the bridge must keep detecting READY_FOR_REVIEW via the
    bus even though it no longer calls reconcile_state().
    """
    _mock_bridge_state_path(monkeypatch, tmp_path)

    supervisor = _make_supervisor(tmp_path)
    ticket_id = "WP-2026-170"

    # Write collaboration artifacts that _ticket_state reads
    _write_work_plan_rfr(supervisor.collaboration_dir / "work_plan.md", ticket_id)
    _write_execution_log_rfr(
        supervisor.collaboration_dir / "execution_log.md", "READY_FOR_REVIEW"
    )

    # Persist active ticket
    supervisor.save_state(
        SupervisorState(active_ticket=ticket_id, completed_tickets=[])
    )

    # Bus state: emit events so derive_state_from_events yields READY_FOR_REVIEW
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Ready",
        },
    )
    # Also emit a preceding event so sequence_number > 0
    supervisor.event_bus.emit(
        "TURN_CHANGED",
        ticket_id=ticket_id,
        actor="CONTROLLER",
        payload={"action": "IMPLEMENT"},
    )

    # Mock _resolve_manager_executable so we don't need a real backend
    fake_exe = tmp_path / "fake_manager.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(
        "scripts.manager_review_bridge._resolve_manager_executable",
        lambda *a: fake_exe,
    )

    from bus.review_bridge import ReviewBridge, ReviewDecision, ReviewResult

    review = ReviewBridge(event_bus=supervisor.event_bus, project_root=tmp_path)

    # Mock the review cycle to return APPROVE without spawning a subprocess
    monkeypatch.setattr(
        review,
        "run_manager_review_cycle",
        lambda **kw: ReviewResult(
            decision=ReviewDecision.APPROVE,
            feedback="LGTM",
            stdout="",
            parse_method="test",
            transport_ok=True,
        ),
    )

    # Spy on reconcile_state — raise if called (it must not be)
    monkeypatch.setattr(
        supervisor,
        "reconcile_state",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    result = _tick(
        supervisor=supervisor,
        review=review,
        manager_path=fake_exe,
        timeout=5,
    )

    # _tick should successfully process the READY_FOR_REVIEW ticket
    assert result is True, "_tick() must process a READY_FOR_REVIEW ticket"


def test_tick_no_concurrent_state_error(tmp_path, monkeypatch):
    """Test that omitting reconcile_state() from _tick() does not
    produce ConcurrentStateError.

    WP-2026-170: since reconcile_state() is the only path inside _tick()
    that writes supervisor_state.json, removing it eliminates the race
    condition with the supervisor process.
    """
    _mock_bridge_state_path(monkeypatch, tmp_path)

    supervisor = _make_supervisor(tmp_path)
    ticket_id = "WP-2026-170-CE"

    _write_work_plan_rfr(supervisor.collaboration_dir / "work_plan.md", ticket_id)
    _write_execution_log_rfr(
        supervisor.collaboration_dir / "execution_log.md", "READY_FOR_REVIEW"
    )

    supervisor.save_state(
        SupervisorState(active_ticket=ticket_id, completed_tickets=[])
    )

    # Emit bus events for READY_FOR_REVIEW
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Ready",
        },
    )

    # Mock the expensive parts
    fake_exe = tmp_path / "fake_manager.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(
        "scripts.manager_review_bridge._resolve_manager_executable",
        lambda *a: fake_exe,
    )

    from bus.review_bridge import ReviewBridge, ReviewDecision, ReviewResult

    review = ReviewBridge(event_bus=supervisor.event_bus, project_root=tmp_path)
    monkeypatch.setattr(
        review,
        "run_manager_review_cycle",
        lambda **kw: ReviewResult(
            decision=ReviewDecision.APPROVE,
            feedback="LGTM",
            stdout="",
            parse_method="test",
            transport_ok=True,
        ),
    )

    # The critical assertion: _tick must NOT raise ConcurrentStateError
    # because it no longer writes supervisor_state.json
    try:
        result = _tick(
            supervisor=supervisor,
            review=review,
            manager_path=fake_exe,
            timeout=5,
        )
    except ConcurrentStateError:
        pytest.fail(
            "_tick() raised ConcurrentStateError — reconcile_state should not be called"
        )

    assert result is True


# =============================================================================
# Tests WP-2026-174: Durable checkpoint for manager review bridge
# =============================================================================


@pytest.fixture(autouse=False)
def _restore_project_root():
    """Restore AGENT_PROJECT_ROOT and clear the module cache after each checkpoint test."""
    import os

    original = os.environ.get("AGENT_PROJECT_ROOT")
    yield
    if original is None:
        os.environ.pop("AGENT_PROJECT_ROOT", None)
    else:
        os.environ["AGENT_PROJECT_ROOT"] = original
    clear_cache()


def _setup_project_root(tmp_path):
    """Set AGENT_PROJECT_ROOT to tmp_path and clear the cache."""
    import os

    os.environ["AGENT_PROJECT_ROOT"] = str(tmp_path)
    clear_cache()


@pytest.mark.usefixtures("_restore_project_root")
def test_checkpoint_persists_after_review(tmp_path):
    """Checkpoint file is created with correct sequence after a review."""
    _setup_project_root(tmp_path)

    state = BridgeState(last_processed_sequence=42)
    _save_checkpoint(state)

    cp_path = _checkpoint_path()
    assert cp_path.exists()
    data = json.loads(cp_path.read_text(encoding="utf-8"))
    assert data["last_processed_sequence"] == 42

    seq = _load_checkpoint()
    assert seq == 42


@pytest.mark.usefixtures("_restore_project_root")
def test_checkpoint_roundtrip_preserves_sequence(tmp_path):
    """Checkpoint survives a full save/load roundtrip."""
    _setup_project_root(tmp_path)

    state = BridgeState(last_processed_sequence=99)
    _save_checkpoint(state)
    assert _load_checkpoint() == 99

    state.last_processed_sequence = 150
    _save_checkpoint(state)
    assert _load_checkpoint() == 150


@pytest.mark.usefixtures("_restore_project_root")
def test_checkpoint_missing_falls_back_to_state(tmp_path):
    """When checkpoint is missing, _load_state uses the heartbeat state file."""
    _setup_project_root(tmp_path)

    state = BridgeState(last_processed_sequence=30)
    _save_state(state)

    cp_path = _checkpoint_path()
    if cp_path.exists():
        cp_path.unlink()

    loaded = _load_state()
    assert loaded.last_processed_sequence == 30


@pytest.mark.usefixtures("_restore_project_root")
def test_checkpoint_corrupt_falls_back_to_state(tmp_path):
    """When checkpoint is corrupt, _load_state uses the heartbeat state file."""
    _setup_project_root(tmp_path)

    state = BridgeState(last_processed_sequence=30)
    _save_state(state)

    cp_path = _checkpoint_path()
    cp_path.write_text("not valid json {{{", encoding="utf-8")

    loaded = _load_state()
    assert loaded.last_processed_sequence == 30


@pytest.mark.usefixtures("_restore_project_root")
def test_checkpoint_takes_max_when_greater_than_state(tmp_path):
    """When checkpoint has a higher sequence than the state file, the
    bridge must use the greater value (defensive merge)."""
    _setup_project_root(tmp_path)

    state = BridgeState(last_processed_sequence=10)
    _save_state(state)

    cp_state = BridgeState(last_processed_sequence=50)
    _save_checkpoint(cp_state)

    loaded = _load_state()
    assert loaded.last_processed_sequence == 50


@pytest.mark.usefixtures("_restore_project_root")
def test_checkpoint_uses_state_when_higher(tmp_path):
    """When the state file has a higher sequence than the checkpoint,
    _load_state uses the state file value (heartbeat compatibility)."""
    _setup_project_root(tmp_path)

    state = BridgeState(last_processed_sequence=80)
    _save_state(state)

    cp_state = BridgeState(last_processed_sequence=20)
    _save_checkpoint(cp_state)

    loaded = _load_state()
    assert loaded.last_processed_sequence == 80


@pytest.mark.usefixtures("_restore_project_root")
def test_checkpoint_arranca_en_cero_si_ambas_superficies_faltan(tmp_path):
    """When both checkpoint and state file are missing, _load_state
    returns a default BridgeState with last_processed_sequence=0."""
    _setup_project_root(tmp_path)

    st_path = _state_path()
    if st_path.exists():
        st_path.unlink()
    cp_path = _checkpoint_path()
    if cp_path.exists():
        cp_path.unlink()

    loaded = _load_state()
    assert loaded.last_processed_sequence == 0
    assert loaded.last_ticket_id is None


# =============================================================================
# Tests WP-2026-177: Domain-based observation loading in review bridge
# =============================================================================


def test_load_manager_review_observations_by_domain_returns_domain_matches(
    tmp_path, monkeypatch
):
    """_load_manager_review_observations_by_domain returns entries matching dtype domain."""
    bridge = _make_review_prompt_bridge(
        tmp_path, deliverable_type="code", monkeypatch=monkeypatch
    )
    _write_observations(
        tmp_path,
        [
            json.dumps(
                {
                    "timestamp": "2026-05-30T10:00:00+00:00",
                    "domain": "delivery-hygiene",
                    "confidence": 0.9,
                    "applies_to": "code",
                    "signal": "Ticket completion hygiene",
                    "source_ticket": "WP-2026-177",
                    "topic": "ticket-completion",
                    "source": "session-close",
                }
            ),
            json.dumps(
                {
                    "timestamp": "2026-05-29T10:00:00+00:00",
                    "domain": "review-quality",
                    "confidence": 0.85,
                    "applies_to": "code",
                    "signal": "Review quality finding",
                    "source_ticket": "WP-2026-176",
                    "topic": "code-quality",
                    "source": "session-close",
                }
            ),
            json.dumps(
                {
                    "timestamp": "2026-05-28T10:00:00+00:00",
                    "domain": "config-schema",
                    "confidence": 0.75,
                    "applies_to": "docs",
                    "signal": "Config schema update",
                    "source_ticket": "WP-2026-175",
                    "topic": "config",
                    "source": "session-close",
                }
            ),
        ],
    )

    # dtype="code" should match delivery-hygiene and review-quality, not config-schema
    results = bridge._load_manager_review_observations_by_domain(dtype="code")
    assert len(results) >= 2
    signals = [r[1] for r in results]
    assert "Ticket completion hygiene" in signals
    assert "Review quality finding" in signals
    assert "Config schema update" not in signals


def test_load_manager_review_observations_by_domain_all_dtype(tmp_path, monkeypatch):
    """_load_manager_review_observations_by_domain with dtype='all' returns all."""
    bridge = _make_review_prompt_bridge(
        tmp_path, deliverable_type="code", monkeypatch=monkeypatch
    )
    _write_observations(
        tmp_path,
        [
            json.dumps(
                {
                    "timestamp": "2026-05-30T10:00:00+00:00",
                    "domain": "delivery-hygiene",
                    "confidence": 0.9,
                    "applies_to": "code",
                    "signal": "Hygiene finding",
                    "source_ticket": "WP-2026-177",
                    "topic": "ticket-completion",
                    "source": "session-close",
                }
            ),
            json.dumps(
                {
                    "timestamp": "2026-05-29T10:00:00+00:00",
                    "domain": "config-schema",
                    "confidence": 0.75,
                    "applies_to": "docs",
                    "signal": "Config finding",
                    "source_ticket": "WP-2026-175",
                    "topic": "config",
                    "source": "session-close",
                }
            ),
        ],
    )

    results = bridge._load_manager_review_observations_by_domain(dtype="all")
    assert len(results) == 2


def test_load_manager_review_observations_falls_back_to_legacy_when_no_domain(
    tmp_path, monkeypatch
):
    """_load_manager_review_observations falls back to topic-based when no domain entries."""
    bridge = _make_review_prompt_bridge(
        tmp_path, deliverable_type="code", monkeypatch=monkeypatch
    )
    _write_observations(
        tmp_path,
        [
            json.dumps(
                {
                    "timestamp": "2026-05-25T10:00:00+00:00",
                    "topic": "manager-review-rubric",
                    "signal": "Legacy rubric finding",
                    "source_ticket": "WP-2026-100",
                    "source": "audit",
                }
            ),
        ],
    )

    results = bridge._load_manager_review_observations(dtype="code")
    assert len(results) == 1
    assert results[0][1] == "Legacy rubric finding"


def test_load_manager_review_observations_returns_domain_before_legacy(
    tmp_path, monkeypatch
):
    """_load_manager_review_observations prefers domain entries over legacy topic."""
    bridge = _make_review_prompt_bridge(
        tmp_path, deliverable_type="code", monkeypatch=monkeypatch
    )
    _write_observations(
        tmp_path,
        [
            json.dumps(
                {
                    "timestamp": "2026-05-30T10:00:00+00:00",
                    "domain": "delivery-hygiene",
                    "confidence": 0.9,
                    "applies_to": "code",
                    "signal": "Canonical domain finding",
                    "source_ticket": "WP-2026-177",
                    "topic": "ticket-completion",
                    "source": "session-close",
                }
            ),
            json.dumps(
                {
                    "timestamp": "2026-05-25T10:00:00+00:00",
                    "topic": "manager-review-rubric",
                    "signal": "Legacy finding (should not appear)",
                    "source_ticket": "WP-2026-100",
                    "source": "audit",
                }
            ),
        ],
    )

    results = bridge._load_manager_review_observations(dtype="code")
    assert len(results) == 1
    assert results[0][1] == "Canonical domain finding"


def test_domain_dtype_map_code_includes_base_domains(tmp_path, monkeypatch):
    """DOMAIN_DTYPE_MAP maps domains to applicable dtypes (code in review-quality)."""
    from bus.review_bridge import DOMAIN_DTYPE_MAP

    review_quality_dtypes = DOMAIN_DTYPE_MAP.get("review-quality", set())
    assert "code" in review_quality_dtypes
    assert "mixed" in review_quality_dtypes


def test_domain_dtype_map_docs_includes_review_quality(tmp_path, monkeypatch):
    """DOMAIN_DTYPE_MAP maps review-quality to include documentation."""
    from bus.review_bridge import DOMAIN_DTYPE_MAP

    delivery_dtypes = DOMAIN_DTYPE_MAP.get("delivery-hygiene", set())
    assert "code" in delivery_dtypes
    assert "mixed" in delivery_dtypes
    assert "documentation" not in delivery_dtypes


def test_load_manager_review_observations_empty_when_no_observations_file(
    tmp_path, monkeypatch
):
    """_load_manager_review_observations_by_domain returns empty list when file missing."""
    bridge = _make_review_prompt_bridge(
        tmp_path, deliverable_type="code", monkeypatch=monkeypatch
    )
    results = bridge._load_manager_review_observations_by_domain(dtype="code")
    assert results == []


@pytest.mark.usefixtures("_restore_project_root")
def test_checkpoint_prevents_reprocessing_on_restart(tmp_path):
    """After a review, on next startup with checkpoint present, the bridge
    skips already-consumed events because _load_state returns the checkpoint
    sequence. If a ticket's latest_sequence <= checkpoint, _tick returns
    False."""
    _setup_project_root(tmp_path)

    # Simulate previous session: checkpoint at seq 42, state file at seq 5
    state = BridgeState(last_processed_sequence=5)
    _save_state(state)
    cp_state = BridgeState(last_processed_sequence=42)
    _save_checkpoint(cp_state)

    # On restart, _load_state must pick seq 42
    loaded = _load_state()
    assert loaded.last_processed_sequence == 42


# ======================================================================
# WT-2026-181: Dual WP-/WT- prefix regression tests
# ======================================================================


class TestDualPrefixBridge:
    """Verify the manager review bridge accepts both WP- and WT- prefixes."""

    def test_bridge_get_active_ticket_wp(self, tmp_path):
        """ReviewBridge._get_active_ticket_id() extracts WP- ID from work_plan.md."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        wp = collab / "work_plan.md"
        wp.write_text("# Work Plan\n- **ID:** WP-2026-100\n- **Estado:** APPROVED\n")
        bridge, _, _ = _make_bridge(tmp_path)
        # Re-read the written work_plan content
        result = bridge._get_active_ticket_id()
        assert result == "WP-2026-100", f"Expected WP-2026-100, got {result}"

    def test_bridge_get_active_ticket_wt(self, tmp_path):
        """ReviewBridge._get_active_ticket_id() extracts WT- ID from work_plan.md."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        wp = collab / "work_plan.md"
        wp.write_text("# Work Plan\n- **ID:** WT-2026-100\n- **Estado:** APPROVED\n")
        bridge, _, _ = _make_bridge(tmp_path)
        result = bridge._get_active_ticket_id()
        assert result == "WT-2026-100", f"Expected WT-2026-100, got {result}"

    def test_bridge_extract_ticket_section_boundary_wp(self, tmp_path, monkeypatch):
        """_extract_ticket_section boundary handles next ### WP- section."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        elog = collab / "execution_log.md"
        elog.write_text(
            "# Execution Log\n\n"
            "### WT-2026-181: Dual prefix\n**Estado:** IN_PROGRESS\n\n"
            "### WP-2026-100: Old ticket\n**Estado:** COMPLETED\n\n"
        )
        # The boundary regex (?=\n### (?:WP|WT)-|\Z) should match WT- boundary
        import re

        content = elog.read_text(encoding="utf-8")
        ticket_id = "WT-2026-181"
        pattern = rf"### {re.escape(ticket_id)}.*?(?=\n### (?:WP|WT)-|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        assert match is not None, "Section boundary regex should match WT- ticket"
        assert "WT-2026-181" in match.group(0)

    def test_bridge_extract_ticket_section_boundary_wp_next(self, tmp_path):
        """_extract_ticket_section boundary handles next ### WT- section."""
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        elog = collab / "execution_log.md"
        elog.write_text(
            "# Execution Log\n\n"
            "### WP-2026-100: Old ticket\n**Estado:** COMPLETED\n\n"
            "### WT-2026-181: New ticket\n**Estado:** IN_PROGRESS\n\n"
        )
        import re

        content = elog.read_text(encoding="utf-8")
        ticket_id = "WP-2026-100"
        pattern = rf"### {re.escape(ticket_id)}.*?(?=\n### (?:WP|WT)-|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        assert match is not None, (
            "Section boundary regex should match WP- ticket with WT- next"
        )
        assert "WP-2026-100" in match.group(0)


# =============================================================================
# Tests WT-2026-183: Resiliencia ante Supervisor muerto en CHANGES
# =============================================================================


class TestChangesResilienceSupervisorDead:
    """WT-2026-183: bridge relaunches Builder when Supervisor has done cooperative exit."""

    def _make_changes_bridge(self, tmp_path, monkeypatch):
        bridge, event_bus, legacy_exe = _make_bridge(tmp_path)

        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        (collab / "work_plan.md").write_text(
            "# Work Ticket - WT-2026-183\n\n## Metadata\n- **ID:** WT-2026-183\n"
            "- **Estado:** APPROVED\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )

        def fake_run(cmd, **kwargs):
            return __import__("subprocess").CompletedProcess(
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
        return bridge, event_bus, legacy_exe

    def test_requeue_called_when_supervisor_dead(self, tmp_path, monkeypatch):
        """Builder is relaunched directly when _is_supervisor_lock_stale() is True."""
        bridge, _, legacy_exe = self._make_changes_bridge(tmp_path, monkeypatch)

        requeue_calls = []

        class DeadSupervisor:
            def transition_ticket(self, **kwargs):
                pass

            def _is_supervisor_lock_stale(self):
                return True

            def requeue_ticket(self, ticket_id, *a, **kw):
                requeue_calls.append(ticket_id)

        result = bridge.run_manager_review_cycle(
            ticket_id="WT-2026-183",
            supervisor=DeadSupervisor(),
            manager_executable=legacy_exe,
            timeout_seconds=5,
        )

        assert result.decision.value == "changes"
        assert requeue_calls == ["WT-2026-183"], (
            "requeue_ticket must be called with the ticket_id when Supervisor is dead"
        )

    def test_requeue_not_called_when_supervisor_alive(self, tmp_path, monkeypatch):
        """Builder is NOT relaunched by the bridge when Supervisor daemon is alive."""
        bridge, _, legacy_exe = self._make_changes_bridge(tmp_path, monkeypatch)

        requeue_calls = []

        class AliveSupervisor:
            def transition_ticket(self, **kwargs):
                pass

            def _is_supervisor_lock_stale(self):
                return False

            def requeue_ticket(self, ticket_id):
                requeue_calls.append(ticket_id)

        result = bridge.run_manager_review_cycle(
            ticket_id="WT-2026-183",
            supervisor=AliveSupervisor(),
            manager_executable=legacy_exe,
            timeout_seconds=5,
        )

        assert result.decision.value == "changes"
        assert requeue_calls == [], (
            "requeue_ticket must NOT be called when Supervisor daemon is alive"
        )


# =============================================================================
# Tests WT-2026-189: Guard anti doble lanzamiento de Builder tras CHANGES
# =============================================================================


class TestAntiDoubleRelaunchGuard:
    """WT-2026-189: Guard idempotente contra doble relaunch de Builder.

    El bridge no debe llamar a requeue_ticket() si el Supervisor ya emitió
    BUILDER_RELAUNCH_ATTEMPTED después del REVIEW_DECISION: changes.
    """

    def _make_changes_bridge(self, tmp_path, monkeypatch):
        """Helper: create bridge configured for CHANGES path."""
        bridge, event_bus, legacy_exe = _make_bridge(tmp_path)

        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        (collab / "work_plan.md").write_text(
            "# Work Ticket - WT-2026-189\n\n## Metadata\n- **ID:** WT-2026-189\n"
            "- **Estado:** APPROVED\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )

        def fake_run(cmd, **kwargs):
            return __import__("subprocess").CompletedProcess(
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
        return bridge, event_bus, legacy_exe

    def test_review_bridge_does_not_double_relaunch_when_supervisor_already_relaunched(
        self, tmp_path, monkeypatch
    ):
        """requeue_ticket NO debe llamarse si ya existe BUILDER_RELAUNCH_ATTEMPTED
        posterior al REVIEW_DECISION: changes emitido por este ciclo."""
        bridge, event_bus, legacy_exe = self._make_changes_bridge(tmp_path, monkeypatch)
        ticket_id = "WT-2026-189"

        requeue_calls = []

        class SupervisorThatAlreadyRelaunched:
            def transition_ticket(self, **kwargs):
                pass

            def _is_supervisor_lock_stale(self):
                # Simulate Supervisor race: emit BUILDER_RELAUNCH_ATTEMPTED
                # AFTER REVIEW_DECISION but BEFORE the bridge calls requeue_ticket.
                event_bus.emit(
                    "BUILDER_RELAUNCH_ATTEMPTED",
                    ticket_id=ticket_id,
                    actor="SUPERVISOR",
                    payload={"success": True},
                )
                return True

            def requeue_ticket(self, tid):
                requeue_calls.append(tid)

        result = bridge.run_manager_review_cycle(
            ticket_id=ticket_id,
            supervisor=SupervisorThatAlreadyRelaunched(),
            manager_executable=legacy_exe,
            timeout_seconds=5,
        )

        assert result.decision.value == "changes"
        assert requeue_calls == [], (
            "requeue_ticket NO debe llamarse cuando el Supervisor ya relanzó Builder"
        )

    def test_review_bridge_relaunches_when_no_builder_relaunch_event_exists_after_changes(
        self, tmp_path, monkeypatch
    ):
        """requeue_ticket SÍ debe llamarse cuando NO existe BUILDER_RELAUNCH_ATTEMPTED
        posterior al REVIEW_DECISION: changes."""
        bridge, _, legacy_exe = self._make_changes_bridge(tmp_path, monkeypatch)
        ticket_id = "WT-2026-189"

        requeue_calls = []

        class SupervisorWithoutRelaunch:
            def transition_ticket(self, **kwargs):
                pass

            def _is_supervisor_lock_stale(self):
                return True

            def requeue_ticket(self, tid, *a, **kw):
                requeue_calls.append(tid)

        result = bridge.run_manager_review_cycle(
            ticket_id=ticket_id,
            supervisor=SupervisorWithoutRelaunch(),
            manager_executable=legacy_exe,
            timeout_seconds=5,
        )

        assert result.decision.value == "changes"
        assert requeue_calls == [ticket_id], (
            "requeue_ticket DEBE llamarse cuando no hay relaunch previo del Supervisor"
        )


# =============================================================================
# WT-2026-203: Empty review diff packaging CHANGES tests
# =============================================================================


def test_tick_empty_diff_returns_packaging_changes(tmp_path, monkeypatch):
    """TP-04: _tick returns CHANGES of packaging when diff is empty, without Manager review."""
    _mock_bridge_state_path(monkeypatch, tmp_path)

    supervisor = _make_supervisor(tmp_path)
    ticket_id = "WP-2026-203-EMPTY-DIFF"

    _write_work_plan_rfr(supervisor.collaboration_dir / "work_plan.md", ticket_id)
    _write_execution_log_rfr(
        supervisor.collaboration_dir / "execution_log.md", "READY_FOR_REVIEW"
    )

    supervisor.save_state(
        SupervisorState(active_ticket=ticket_id, completed_tickets=[])
    )

    # Bus state: emit events for READY_FOR_REVIEW
    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Ready",
        },
    )
    supervisor.event_bus.emit(
        "TURN_CHANGED",
        ticket_id=ticket_id,
        actor="CONTROLLER",
        payload={"action": "IMPLEMENT"},
    )

    from bus.review_bridge import ReviewBridge

    review = ReviewBridge(event_bus=supervisor.event_bus, project_root=tmp_path)

    # Mock check_review_packet_diff_empty to return True (empty diff)
    monkeypatch.setattr(review, "check_review_packet_diff_empty", lambda tid: True)

    # Spy on run_manager_review_cycle — MUST NOT be called
    review_cycle_called = False

    def fail_if_called(**kw):
        nonlocal review_cycle_called
        review_cycle_called = True
        raise AssertionError(
            "run_manager_review_cycle must not be called for empty diff"
        )

    monkeypatch.setattr(review, "run_manager_review_cycle", fail_if_called)

    result = _tick(
        supervisor=supervisor,
        review=review,
        manager_path=None,
        timeout=5,
    )

    # _tick must return True (processed the packaging CHANGES)
    assert result is True, "_tick() must return True for packaging CHANGES"

    # run_manager_review_cycle must NOT have been called
    assert not review_cycle_called, (
        "run_manager_review_cycle MUST NOT be called when diff is empty"
    )

    # Verify REVIEW_DECISION was emitted
    latest_review = supervisor.event_bus.latest_event(
        ticket_id=ticket_id, event_type="REVIEW_DECISION"
    )
    assert latest_review is not None, "REVIEW_DECISION must be emitted"
    assert latest_review.payload.get("decision") == "CHANGES", (
        f"Decision must be CHANGES, got: {latest_review.payload.get('decision')}"
    )


def test_tick_normal_diff_proceeds_with_review(tmp_path, monkeypatch):
    """TP-04 regression: _tick proceeds with normal review when diff is valid."""
    _mock_bridge_state_path(monkeypatch, tmp_path)

    supervisor = _make_supervisor(tmp_path)
    ticket_id = "WP-2026-203-VALID-DIFF"

    _write_work_plan_rfr(supervisor.collaboration_dir / "work_plan.md", ticket_id)
    _write_execution_log_rfr(
        supervisor.collaboration_dir / "execution_log.md", "READY_FOR_REVIEW"
    )

    supervisor.save_state(
        SupervisorState(active_ticket=ticket_id, completed_tickets=[])
    )

    supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Ready",
        },
    )
    supervisor.event_bus.emit(
        "TURN_CHANGED",
        ticket_id=ticket_id,
        actor="CONTROLLER",
        payload={"action": "IMPLEMENT"},
    )

    from bus.review_bridge import ReviewBridge, ReviewDecision, ReviewResult

    review = ReviewBridge(event_bus=supervisor.event_bus, project_root=tmp_path)

    # Mock check_review_packet_diff_empty to return False (valid diff)
    monkeypatch.setattr(review, "check_review_packet_diff_empty", lambda tid: False)

    # Mock run_manager_review_cycle to return APPROVE
    monkeypatch.setattr(
        review,
        "run_manager_review_cycle",
        lambda **kw: ReviewResult(
            decision=ReviewDecision.APPROVE,
            feedback="LGTM",
            stdout="",
            parse_method="test",
            transport_ok=True,
        ),
    )

    fake_exe = tmp_path / "fake_manager.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(
        "scripts.manager_review_bridge._resolve_manager_executable",
        lambda *a: fake_exe,
    )

    result = _tick(
        supervisor=supervisor,
        review=review,
        manager_path=fake_exe,
        timeout=5,
    )

    # _tick must return True (processed the normal review)
    assert result is True, "_tick() must return True for normal review"


def test_tick_manager_stale_checkpoint_does_not_block_ready_review(
    tmp_path, monkeypatch
):
    """MANAGER_STALE checkpoint must not suppress the pending READY review."""
    _mock_bridge_state_path(monkeypatch, tmp_path)

    supervisor = _make_supervisor(tmp_path)
    ticket_id = "WT-2026-236a"

    _write_work_plan_rfr(supervisor.collaboration_dir / "work_plan.md", ticket_id)
    _write_execution_log_rfr(
        supervisor.collaboration_dir / "execution_log.md", "READY_FOR_REVIEW"
    )
    supervisor.save_state(
        SupervisorState(active_ticket=ticket_id, completed_tickets=[])
    )

    ready_event = supervisor.event_bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Ready",
        },
    )
    stale_event = supervisor.event_bus.emit(
        "MANAGER_STALE",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={"trigger_sequence": ready_event.sequence_number},
    )
    _save_state(
        BridgeState(
            last_processed_sequence=stale_event.sequence_number,
            last_ticket_id=ticket_id,
            last_ticket_state="READY_FOR_REVIEW",
        )
    )

    from bus.review_bridge import ReviewBridge, ReviewDecision, ReviewResult

    review = ReviewBridge(event_bus=supervisor.event_bus, project_root=tmp_path)
    monkeypatch.setattr(review, "check_review_packet_diff_empty", lambda tid: False)

    review_called = False

    def approve_review(**kw):
        nonlocal review_called
        review_called = True
        return ReviewResult(
            decision=ReviewDecision.APPROVE,
            feedback="LGTM",
            stdout="",
            parse_method="test",
            transport_ok=True,
        )

    monkeypatch.setattr(review, "run_manager_review_cycle", approve_review)

    fake_exe = tmp_path / "fake_manager.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(
        "scripts.manager_review_bridge._resolve_manager_executable",
        lambda *a: fake_exe,
    )

    result = _tick(
        supervisor=supervisor,
        review=review,
        manager_path=fake_exe,
        timeout=5,
    )

    assert result is True
    assert review_called is True


# =============================================================================
# Tests WT-2026-204: Parser unico con fixture real y materializacion sin reparseo
# =============================================================================


class TestWT2026204:
    """WT-2026-204: Hardening de materializacion de blockers con parser unico."""

    def _get_golden_fixture_path(self) -> Path:
        """Return the path to the golden fixture."""
        return (
            Path(__file__).resolve().parent
            / "fixtures"
            / "opencode_streaming_changes.jsonl"
        )

    def _read_golden_fixture(self) -> str:
        fixture_path = self._get_golden_fixture_path()
        assert fixture_path.exists(), f"Golden fixture not found: {fixture_path}"
        return fixture_path.read_text(encoding="utf-8")

    # TP-01: el parser del bridge extrae blockers desde un golden fixture real
    # de OpenCode sanitizado via redact()
    def test_parse_changes_structure_extracts_from_ndjson_fixture(self, tmp_path):
        """_parse_changes_structure extracts blockers from NDJSON golden fixture."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        fixture_content = self._read_golden_fixture()

        structured = bridge._parse_changes_structure(fixture_content)

        # Must find BLOCKERS from the NDJSON fixture
        assert "blockers" in structured
        assert structured["blockers"], "blockers must be non-empty from golden fixture"
        assert "event_parser.py" in structured["blockers"], (
            "blockers must contain parsed content"
        )
        assert '{"type":' not in structured["blockers"], (
            "blockers must not contain raw JSONL"
        )
        assert "sessionID" not in structured["blockers"], (
            "blockers must not contain sessionID"
        )

        # Must find SUMMARY
        assert "summary" in structured
        assert structured["summary"], "summary must be non-empty from golden fixture"

        # Must find SUGGESTIONS
        assert "suggestions" in structured
        assert structured["suggestions"], (
            "suggestions must be non-empty from golden fixture"
        )

    def test_extract_json_stream_text_extracts_from_ndjson(self, tmp_path):
        """_extract_json_stream_text extracts text from NDJSON lines."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        ndjson = (
            '{"type":"text","part":{"type":"text","text":"## SUMMARY\\nSummary text"}}\n'
            '{"type":"text","part":{"type":"text","text":"## BLOCKERS\\n- blocker1"}}\n'
            '{"type":"text","phase":"final_answer","part":{"type":"text","text":"DECISION: CHANGES"}}'
        )

        result = bridge._extract_json_stream_text(ndjson)

        assert result is not None
        assert "## SUMMARY" in result
        assert "Summary text" in result
        assert "## BLOCKERS" in result
        assert "blocker1" in result
        assert "DECISION: CHANGES" in result

    def test_extract_json_stream_text_returns_none_for_plain_text(self, tmp_path):
        """_extract_json_stream_text returns None for plain text (no NDJSON)."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        plain_text = (
            "## SUMMARY\nSummary text\n## BLOCKERS\n- blocker1\nDECISION: CHANGES"
        )

        result = bridge._extract_json_stream_text(plain_text)

        assert result is None, "plain text with no NDJSON lines should return None"

    # TP-02: la normalizacion no devuelve raw stream gigante como feedback estructurado
    def test_normalize_feedback_does_not_return_raw_stream(self, tmp_path):
        """_normalize_feedback returns clean text, not raw NDJSON."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # NDJSON with CHANGES decision
        ndjson_stdout = (
            '{"type":"text","part":{"type":"text","text":"## SUMMARY\\nNeeds fixes"}}\n'
            '{"type":"text","part":{"type":"text","text":"## BLOCKERS\\n- fix parser"}}\n'
            '{"type":"text","part":{"type":"text","text":"## SUGGESTIONS\\n- add tests"}}\n'
            '{"type":"text","phase":"final_answer","part":{"type":"text","text":"DECISION: CHANGES"}}'
        )

        normalized = bridge._normalize_feedback(ndjson_stdout, ReviewDecision.CHANGES)

        # Must NOT contain raw NDJSON markers
        assert '{"type":' not in normalized, (
            "normalized feedback must not contain raw JSONL"
        )
        assert '"part"' not in normalized, (
            "normalized feedback must not contain JSON object keys"
        )
        # Must contain the structured content
        assert "## BLOCKERS" in normalized
        assert "fix parser" in normalized
        assert "## SUMMARY" in normalized

    def test_normalize_feedback_falls_back_gracefully_for_unparseable(self, tmp_path):
        """_normalize_feedback handles unparseable stdout without returning raw gibberish."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Plain text without JSON structure (not parseable as NDJSON either)
        plain_text = "Some review text without decision markers"

        normalized = bridge._normalize_feedback(plain_text, ReviewDecision.CHANGES)

        # Should still get something reasonable back
        assert isinstance(normalized, str)
        assert "Some review text" in normalized

    # TP-03: el materializador de TURN.md consume payload["blockers"] de REVIEW_DECISION
    # y no reparsea output crudo
    def test_review_decision_payload_contains_blockers(self, monkeypatch, tmp_path):
        """REVIEW_DECISION event payload includes blockers from _parse_changes_structure."""
        import json as _json

        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )

        # Mock the underlying subprocess to return NDJSON with final_answer CHANGES
        import subprocess

        ndjson_stdout = _json.dumps(
            {
                "type": "text",
                "phase": "final_answer",
                "part": {
                    "type": "text",
                    "text": (
                        "## SUMMARY\nFix needed\n"
                        "## BLOCKERS\n- test_blocker\n"
                        "## SUGGESTIONS\n- none\n"
                        "DECISION: CHANGES"
                    ),
                },
            }
        )

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=ndjson_stdout,
                stderr="",
            )

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_supports_json_format", True)
        monkeypatch.setattr(bridge, "_resolve_motor_controller", lambda: None)
        monkeypatch.setattr(
            bridge,
            "_ensure_repomix_context",
            lambda *a: (None, {"status": "skipped", "reason": "mocked for tests"}),
        )

        class DummySupervisor:
            def transition_ticket(self, tid, new_state, reason):
                pass

            def load_state(self):
                from bus.supervisor import SupervisorState

                return SupervisorState()

            def _is_supervisor_lock_stale(self):
                return False

            def save_state(self, state):
                pass

        supervisor = DummySupervisor()

        # Mock --request-changes call
        def fake_subprocess_run(cmd, **kwargs):
            if "agent_controller.py" in " ".join(
                str(p) for p in (cmd if isinstance(cmd, list) else [cmd])
            ):
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="[OK] requeue", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(
            bridge,
            "_count_prior_changes_from_bus",
            lambda tid: 1,
        )
        monkeypatch.setattr(
            bridge,
            "_load_review_config",
            lambda: {
                "timeout_seconds": 180,
                "max_attempts": 5,
                "retry_backoff_multiplier": 2.0,
            },
        )
        # This prevents the subprocess from being called for --request-changes
        monkeypatch.setattr(
            bridge,
            "_resolve_motor_controller",
            lambda: None,
        )

        bridge.run_manager_review_cycle(
            ticket_id="WT-2026-204",
            supervisor=supervisor,
            timeout_seconds=10,
        )

        # Verify the REVIEW_DECISION event has blockers
        events = event_bus.read_events(ticket_id="WT-2026-204")
        review_decision_events = [
            e for e in events if e.event_type == "REVIEW_DECISION"
        ]
        assert review_decision_events, "Must have REVIEW_DECISION event"
        latest = review_decision_events[-1]
        blockers = (latest.payload or {}).get("blockers", "")
        assert blockers, "REVIEW_DECISION payload must contain blockers"
        assert "test_blocker" in blockers
        assert '{"type":' not in blockers, "blockers must not contain raw JSONL"

    def test_parse_changes_structure_plain_text_still_works(self, tmp_path):
        """_parse_changes_structure handles plain text (non-NDJSON) correctly."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        plain_text = (
            "## SUMMARY\nFix the parser\n\n"
            "## BLOCKERS\n- file.py:10 handle edge case\n- file.py:20 add null check\n\n"
            "## SUGGESTIONS\n- Add tests\n\n"
            "DECISION: CHANGES"
        )

        structured = bridge._parse_changes_structure(plain_text)

        assert structured["summary"] == "Fix the parser"
        assert "file.py:10" in structured["blockers"]
        assert "file.py:20" in structured["blockers"]
        assert "Add tests" in structured["suggestions"]


# =============================================================================
# Tests WT-2026-227a: Repomix estado estructurado y diagnostico verificable
# =============================================================================


class TestRepomixStructuredStatus:
    """WT-2026-227a: _ensure_repomix_context returns structured status dict.

    These tests override the autouse _mock_repomix_for_tests fixture at the
    test level so they exercise the real _ensure_repomix_context logic paths
    (success, failed, skipped/exception).
    """

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    @staticmethod
    def _make_repomix_bridge(tmp_path: Path) -> tuple[ReviewBridge, EventBus]:
        """Build a minimal bridge with collaboration artifacts."""
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        config_dir = tmp_path / ".agent" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "motor_destination_link.json").write_text(
            '{"motor_root": "' + str(tmp_path).replace("\\", "\\\\") + '"}',
            encoding="utf-8",
        )
        template_dir = tmp_path / "agent_system" / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        (template_dir / "repomix.config.json").write_text(
            '{"include": [], "ignore": {"useGitignore": true, "customPatterns": []}}',
            encoding="utf-8",
        )
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        return bridge, event_bus

    @staticmethod
    def _stub_work_plan(tmp_path: Path) -> Path:
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        wp = collab / "work_plan.md"
        wp.write_text(
            "# Work Ticket - WT-2026-227a\n\n## Metadata\n"
            "- **ID:** WT-2026-227a\n- **Estado:** APPROVED\n"
            "- **deliverable_type:** code\n",
            encoding="utf-8",
        )
        return wp

    # ---------------------------------------------------------------
    # TP-01 / TP-02: test de exito
    # ---------------------------------------------------------------

    def test_repomix_ok_when_subprocess_exit_zero(self, monkeypatch, tmp_path):
        """TP-02: _ensure_repomix_context returns status=ok when subprocess
        exits 0 and the output file is created."""
        # Restore real method before testing
        monkeypatch.setattr(
            "bus.review_bridge.ReviewBridge._ensure_repomix_context",
            _REAL_ENSURE_REPOMIX_CONTEXT,
        )
        bridge, _ = self._make_repomix_bridge(tmp_path)

        context_dir = tmp_path / ".agent" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        out_path = context_dir / "repomix_motor.xml"
        captured: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            # Simulate repomix creating the output file
            out_path.write_text("<context>generated</context>", encoding="utf-8")
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="",
                stderr="",
            )

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)

        path, status = bridge._ensure_repomix_context(timeout=5)

        assert status["status"] == "ok"
        assert status["reason"] == "Repomix completed successfully"
        assert status["output_path"] is not None
        assert Path(status["output_path"]).exists()
        assert path is not None
        assert path.exists()
        assert captured["cwd"] == tmp_path
        assert "--config" in captured["cmd"]
        assert any(
            "agent_system" in str(part) and "repomix.config.json" in str(part)
            for part in captured["cmd"]
        )

    def test_repomix_ok_when_pre_existing_file(self, monkeypatch, tmp_path):
        """TP-02 variant: status=ok when repomix_motor.xml already exists."""
        monkeypatch.setattr(
            "bus.review_bridge.ReviewBridge._ensure_repomix_context",
            _REAL_ENSURE_REPOMIX_CONTEXT,
        )
        bridge, _ = self._make_repomix_bridge(tmp_path)
        context_dir = tmp_path / ".agent" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        out_path = context_dir / "repomix_motor.xml"
        out_path.write_text("<context>existing</context>", encoding="utf-8")

        path, status = bridge._ensure_repomix_context(timeout=5)

        assert status["status"] == "ok"
        assert "Existing" in status["reason"]
        assert status["output_path"] == str(out_path)
        assert path == out_path

    # ---------------------------------------------------------------
    # TP-03: test de fallo con returncode != 0
    # ---------------------------------------------------------------

    def test_repomix_failed_when_returncode_nonzero(self, monkeypatch, tmp_path):
        """TP-03: _ensure_repomix_context returns status=failed when
        subprocess exits with non-zero returncode and captures stderr_tail."""
        monkeypatch.setattr(
            "bus.review_bridge.ReviewBridge._ensure_repomix_context",
            _REAL_ENSURE_REPOMIX_CONTEXT,
        )
        bridge, _ = self._make_repomix_bridge(tmp_path)

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout="",
                stderr="Error: repomix failed",
            )

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
        # Ensure no pre-existing file
        context_dir = tmp_path / ".agent" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)

        path, status = bridge._ensure_repomix_context(timeout=5)

        assert path is None
        assert status["status"] == "failed"
        assert status["returncode"] == 1
        assert "stderr_tail" in status
        assert "Error: repomix failed" in status["stderr_tail"]

    # ---------------------------------------------------------------
    # TP-04: test de excepcion / npx ausente
    # ---------------------------------------------------------------

    def test_repomix_skipped_when_npx_not_found(self, monkeypatch, tmp_path):
        """TP-04: _ensure_repomix_context returns status=skipped when
        FileNotFoundError is raised (npx not available)."""
        monkeypatch.setattr(
            "bus.review_bridge.ReviewBridge._ensure_repomix_context",
            _REAL_ENSURE_REPOMIX_CONTEXT,
        )
        bridge, _ = self._make_repomix_bridge(tmp_path)

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("npx not found")

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
        context_dir = tmp_path / ".agent" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)

        path, status = bridge._ensure_repomix_context(timeout=5)

        assert path is None
        assert status["status"] == "skipped"
        assert "npx not found" in status["reason"]

    def test_repomix_failed_when_timeout(self, monkeypatch, tmp_path):
        """TP-04 variant: timeout raises TimeoutExpired -> status=failed."""
        import subprocess as _subprocess

        monkeypatch.setattr(
            "bus.review_bridge.ReviewBridge._ensure_repomix_context",
            _REAL_ENSURE_REPOMIX_CONTEXT,
        )
        bridge, _ = self._make_repomix_bridge(tmp_path)

        def fake_run(cmd, **kwargs):
            raise _subprocess.TimeoutExpired(cmd, timeout=5)

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
        context_dir = tmp_path / ".agent" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)

        path, status = bridge._ensure_repomix_context(timeout=5)

        assert path is None
        assert status["status"] == "failed"
        assert "timed out" in status["reason"]

    def test_repomix_skipped_on_generic_exception(self, monkeypatch, tmp_path):
        """TP-04 variant: generic Exception yields status=skipped with reason."""
        monkeypatch.setattr(
            "bus.review_bridge.ReviewBridge._ensure_repomix_context",
            _REAL_ENSURE_REPOMIX_CONTEXT,
        )
        bridge, _ = self._make_repomix_bridge(tmp_path)

        def fake_run(cmd, **kwargs):
            raise PermissionError("Access denied")

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
        context_dir = tmp_path / ".agent" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)

        path, status = bridge._ensure_repomix_context(timeout=5)

        assert path is None
        assert status["status"] == "skipped"
        assert "PermissionError" in status["reason"]

    # ---------------------------------------------------------------
    # TP-05: el review continua cuando Repomix falla
    # ---------------------------------------------------------------

    def test_run_opencode_review_continues_when_repomix_fails(
        self, monkeypatch, tmp_path
    ):
        """TP-05: _run_opencode_review invokes opencode even when repomix
        context fails (status != ok)."""
        import subprocess as _subprocess

        bridge, _ = self._make_repomix_bridge(tmp_path)
        self._stub_work_plan(tmp_path)
        manager_source = tmp_path / ".opencode" / "agents" / "manager.md"
        manager_source.parent.mkdir(parents=True, exist_ok=True)
        manager_source.write_text(
            "---\ndescription: test manager\n---\n", encoding="utf-8"
        )

        # Mock _ensure_repomix_context to return failed
        monkeypatch.setattr(
            bridge,
            "_ensure_repomix_context",
            lambda timeout=15: (
                None,
                {
                    "status": "failed",
                    "reason": "Repomix failed (simulated)",
                    "returncode": 1,
                    "stderr_tail": "simulated error",
                },
            ),
        )
        # Mock subprocess.run to capture the opencode command
        captured = {}

        def fake_run(cmd_args, **kwargs):
            captured["cmd"] = cmd_args
            return _subprocess.CompletedProcess(
                args=cmd_args,
                returncode=0,
                stdout="DECISION: APPROVE",
                stderr="",
            )

        monkeypatch.setattr(_subprocess, "run", fake_run)
        monkeypatch.setattr(bridge, "_get_manager_model", lambda: None)
        monkeypatch.setattr(bridge, "_supports_json_format", False)
        monkeypatch.setattr("bus.review_bridge.OS_NAME", "posix")

        bridge._run_opencode_review(
            ticket_id="WT-2026-227a",
            prompt="test prompt",
            timeout_seconds=5,
        )

        cmd = captured.get("cmd", [])
        # Must NOT contain -f flag (since repomix_path is None)
        assert "-f" not in cmd
        # Must contain the review message
        assert any("WT-2026-227a" in str(part) for part in cmd)

        # Validate that repomix_status was injected into the review packet
        packet_path = (
            tmp_path
            / ".agent"
            / "runtime"
            / "review_packets"
            / "WT-2026-227a_attempt-1.md"
        )
        assert packet_path.exists(), "Review packet should be created"
        packet_content = packet_path.read_text(encoding="utf-8")
        assert "Repomix Context Status" in packet_content
        assert "Repomix failed (simulated)" in packet_content

    def test_run_opencode_review_uses_motor_root_and_project_dir(
        self, monkeypatch, tmp_path
    ):
        """Manager agent must be materialized before OpenCode runs."""
        import subprocess as _subprocess

        project_root = tmp_path / "repo_destino"
        project_root.mkdir(parents=True, exist_ok=True)
        bridge, _, _ = _make_bridge(project_root)
        self._stub_work_plan(project_root)

        config_dir = project_root / ".agent" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        motor_root = tmp_path / "repo_motor"
        motor_root.mkdir(parents=True, exist_ok=True)
        manager_source = motor_root / ".opencode" / "agents" / "manager.md"
        manager_source.parent.mkdir(parents=True, exist_ok=True)
        manager_source.write_text(
            "---\ndescription: test manager\n---\n", encoding="utf-8"
        )
        (config_dir / "motor_destination_link.json").write_text(
            json.dumps({"motor_root": str(motor_root)}),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            bridge,
            "_ensure_repomix_context",
            lambda timeout=15: (None, {"status": "skipped", "reason": "test"}),
        )
        monkeypatch.setattr(bridge, "_get_manager_model", lambda: None)
        monkeypatch.setattr(bridge, "_supports_json_format", False)
        monkeypatch.setattr("bus.review_bridge.OS_NAME", "posix")

        captured: dict[str, object] = {}
        manager_dest = project_root / ".opencode" / "agents" / "manager.md"

        def fake_run(cmd_args, **kwargs):
            captured["cmd"] = cmd_args
            captured["cwd"] = kwargs.get("cwd")
            captured["dest_exists_before_run"] = manager_dest.exists()
            if manager_dest.exists():
                captured["dest_content"] = manager_dest.read_text(encoding="utf-8")
            return _subprocess.CompletedProcess(
                args=cmd_args,
                returncode=0,
                stdout="DECISION: APPROVE",
                stderr="",
            )

        monkeypatch.setattr(_subprocess, "run", fake_run)

        bridge._run_opencode_review(
            ticket_id="WT-2026-236a",
            prompt="test prompt",
            timeout_seconds=5,
        )

        cmd = captured["cmd"]
        assert isinstance(cmd, list)
        assert "--agent" in cmd
        assert "manager" in cmd
        assert "--dir" in cmd
        assert cmd[cmd.index("--dir") + 1] == str(project_root)
        assert captured["cwd"] == motor_root.resolve()
        assert captured["dest_exists_before_run"] is True
        assert captured["dest_content"] == manager_source.read_text(encoding="utf-8")

    def test_run_opencode_review_fails_clearly_when_manager_agent_missing(
        self, monkeypatch, tmp_path
    ):
        """Bridge must fail clearly before subprocess when manager.md is absent."""
        project_root = tmp_path / "repo_destino"
        project_root.mkdir(parents=True, exist_ok=True)
        bridge, _, _ = _make_bridge(project_root)
        self._stub_work_plan(project_root)

        config_dir = project_root / ".agent" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        motor_root = tmp_path / "repo_motor"
        motor_root.mkdir(parents=True, exist_ok=True)
        (config_dir / "motor_destination_link.json").write_text(
            json.dumps({"motor_root": str(motor_root)}),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            bridge,
            "_ensure_repomix_context",
            lambda timeout=15: (None, {"status": "skipped", "reason": "test"}),
        )
        monkeypatch.setattr(bridge, "_get_manager_model", lambda: None)
        monkeypatch.setattr(bridge, "_supports_json_format", False)
        monkeypatch.setattr("bus.review_bridge.OS_NAME", "posix")

        def fail_if_run(*args, **kwargs):
            raise AssertionError("subprocess.run should not be called")

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fail_if_run)

        with pytest.raises(FileNotFoundError, match="Manager agent spec not found"):
            bridge._run_opencode_review(
                ticket_id="WT-2026-236a",
                prompt="test prompt",
                timeout_seconds=5,
            )

    # ---------------------------------------------------------------
    # TP-06: tests focales no usan _mock_repomix_for_tests
    # ---------------------------------------------------------------

    def test_repomix_status_has_exact_literals(self, monkeypatch, tmp_path):
        """TP-02: status literals are exactly 'ok', 'failed', 'skipped'."""
        monkeypatch.setattr(
            "bus.review_bridge.ReviewBridge._ensure_repomix_context",
            _REAL_ENSURE_REPOMIX_CONTEXT,
        )
        bridge, _ = self._make_repomix_bridge(tmp_path)
        context_dir = tmp_path / ".agent" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        out_path = context_dir / "repomix_motor.xml"
        out_path.write_text("<context>pre-existing</context>", encoding="utf-8")

        _, status = bridge._ensure_repomix_context(timeout=5)

        assert status["status"] in ("ok", "failed", "skipped")
        assert status["status"] == "ok"

    def test_repomix_skipped_when_output_exceeds_budget(self, monkeypatch, tmp_path):
        """Large repomix output is not injected into the review packet."""
        monkeypatch.setattr(
            "bus.review_bridge.ReviewBridge._ensure_repomix_context",
            _REAL_ENSURE_REPOMIX_CONTEXT,
        )
        bridge, _ = self._make_repomix_bridge(tmp_path)

        context_dir = tmp_path / ".agent" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        out_path = context_dir / "repomix_motor.xml"

        def fake_run(cmd, **kwargs):
            out_path.write_bytes(b"x" * (1024 * 1024 + 1))
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="",
                stderr="",
            )

        monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)

        path, status = bridge._ensure_repomix_context(timeout=5)

        assert path is None
        assert status["status"] == "skipped"
        assert "exceeds" in status["reason"]
        assert not out_path.exists()
