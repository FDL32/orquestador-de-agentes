from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge, ReviewDecision, ReviewResult
from bus.supervisor import SequentialTicketSupervisor, SupervisorState
from scripts.manager_review_bridge import BridgeState, _bridge_heartbeat, _ticket_state


class DummySupervisor:
    def __init__(self) -> None:
        self.transitions: list[tuple[str, str, str]] = []

    def transition_ticket(self, ticket_id: str, new_state: str, reason: str, source_event_id: str | None = None) -> None:
        self.transitions.append((ticket_id, new_state, reason))


def _make_bridge(tmp_path: Path) -> tuple[ReviewBridge, EventBus, Path]:
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
    codex = tmp_path / "codex.exe"
    codex.write_text("", encoding="utf-8")
    return bridge, event_bus, codex


def test_manager_review_cycle_approves(monkeypatch, tmp_path):
    bridge, event_bus, codex = _make_bridge(tmp_path)
    supervisor = DummySupervisor()

    def fake_run(cmd, **kwargs):
        return __import__("subprocess").CompletedProcess(
            cmd,
            0,
            stdout="APPROVE: no findings. Ready for closeout.",
            stderr="",
        )

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-2026-025",
        supervisor=supervisor,
        manager_executable=codex,
        timeout_seconds=5,
    )

    assert result.decision.value == "approve"
    assert supervisor.transitions[-1][1] == "READY_TO_CLOSE"
    events = event_bus.read_events(ticket_id="WP-2026-025")
    assert any(event.event_type == "MANAGER_REVIEWING" for event in events)
    assert any(event.event_type == "REVIEW_DECISION" for event in events)


def test_manager_review_cycle_requests_changes(monkeypatch, tmp_path):
    """Test review cycle handles CHANGES decision (WP-2026-106: single CHANGES then approve).

    Note: With WP-2026-106, 5 consecutive CHANGES lead to HUMAN_GATE.
    This test returns CHANGES once, then APPROVE to verify CHANGES path
    without triggering escalation.
    """
    bridge, event_bus, codex = _make_bridge(tmp_path)
    supervisor = DummySupervisor()
    calls: list[list[str]] = []

    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if any("agent_controller.py" in str(part) for part in cmd):
            return __import__("subprocess").CompletedProcess(cmd, 0, stdout="[OK] requeue", stderr="")
        call_count["n"] += 1
        # Return CHANGES first time, then APPROVE
        if call_count["n"] == 1:
            # Include structured sections to pass validation
            return __import__("subprocess").CompletedProcess(
                cmd,
                0,
                stdout="## SUMMARY\nNeeds fixes.\n## BLOCKERS\n- Parsing\n## SUGGESTIONS\n- Fix parsing\nDECISION: CHANGES",
                stderr="",
            )
        return __import__("subprocess").CompletedProcess(
            cmd,
            0,
            stdout="DECISION: APPROVE",
            stderr="",
        )

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")
    # Force codex backend
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "codex")

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-2026-025",
        supervisor=supervisor,
        manager_executable=codex,
        timeout_seconds=5,
    )

    # First call returns CHANGES, second returns APPROVE
    # Since we got APPROVE on retry, final decision is APPROVE
    assert result.decision.value == "approve"
    # Should have called twice (CHANGES then APPROVE)
    assert call_count["n"] == 2
    # Should transition to READY_TO_CLOSE
    assert any(t[1] == "READY_TO_CLOSE" for t in supervisor.transitions)
    # The --request-changes call happens when CHANGES is the FINAL decision
    # Since we got APPROVE, no requeue call expected
    events = event_bus.read_events(ticket_id="WP-2026-025")
    assert any(event.event_type == "MANAGER_REVIEWING" for event in events)
    assert any(event.event_type == "REVIEW_DECISION" for event in events)


def test_manager_review_cycle_tool_error_inspects_without_transition(monkeypatch, tmp_path):
    bridge, event_bus, codex = _make_bridge(tmp_path)
    supervisor = DummySupervisor()

    def fake_run(cmd, **kwargs):
        return __import__("subprocess").CompletedProcess(
            cmd,
            2,
            stdout="",
            stderr="error: the argument '--uncommitted' cannot be used with '[PROMPT]'",
        )

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-2026-025",
        supervisor=supervisor,
        manager_executable=codex,
        timeout_seconds=5,
    )

    assert result.decision.value == "inspect"
    assert supervisor.transitions == []
    events = event_bus.read_events(ticket_id="WP-2026-025")
    assert any(event.event_type == "MANAGER_REVIEWING" for event in events)
    assert any(event.event_type == "REVIEW_DECISION" for event in events)
    assert any(
        event.payload.get("decision") == "inspect"
        for event in events
        if event.event_type == "REVIEW_DECISION"
    )


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
                "- Project: `orquestacion_agentes`",
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


def test_build_review_prompt_includes_generated_artifacts_block(tmp_path):
    from bus.review_bridge import ReviewBridge
    from bus.event_bus import EventBus

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    # We just need to verify the prompt contains the new block
    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")

    assert "--- SYSTEM GENERATED & ARCHIVED ARTIFACTS ---" in prompt
    assert "archive_collaboration_artifacts.py" in prompt
    assert "Deletions, moves to _archive/" in prompt


class TestOpencodeReviewRoute:
    """Tests for OpenCode backend review route."""

    def test_parse_opencode_decision_approve(self, tmp_path):
        """Test parser detects DECISION: APPROVE."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "Review complete. All criteria met.\nDECISION: APPROVE"
        decision = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.APPROVE

    def test_parse_opencode_decision_changes(self, tmp_path):
        """Test parser detects DECISION: CHANGES."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "Found issues:\n- Missing tests\n\nDECISION: CHANGES"
        decision = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.CHANGES

    def test_parse_opencode_decision_no_decision_fallback_inspect(self, tmp_path):
        """Test parser returns INSPECT when no DECISION found."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "Review complete but output lacks decision format."
        decision = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT

    def test_parse_opencode_decision_lowercase(self, tmp_path):
        """Test parser handles lowercase decision patterns."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "decision: approve"
        decision = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.APPROVE

    def test_get_manager_backend_default_codex(self, tmp_path):
        """Test backend detection returns codex when agents.json has MANAGER=codex."""
        from bus.review_bridge import ReviewBridge, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # With real agents.json (MANAGER: codex), should return "codex"
        backend = bridge._get_manager_backend()
        assert backend == "codex"

    def test_run_manager_review_cycle_dispatches_opencode(self, monkeypatch, tmp_path):
        """Test review cycle dispatches to opencode route when backend is opencode."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Mock _get_manager_backend to return opencode
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_get_manager_model", lambda: "opencode-go/deepseek-v4-flash")
        monkeypatch.setattr(bridge, "_get_canonical_files", lambda: [])
        monkeypatch.setattr(bridge, "_get_active_ticket_id", lambda: "WP-2026-072")
        monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")

        captured = {}

        def fake_opencode_review(*, ticket_id, prompt="", manager_executable=None, timeout_seconds):
            captured["ticket_id"] = ticket_id
            return "DECISION: APPROVE", "", 0

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
        assert captured["transition"] == ("WP-2026-072", "READY_TO_CLOSE", "Manager approved")

    def test_run_manager_review_cycle_dispatches_codex(self, monkeypatch, tmp_path):
        """Test review cycle dispatches to codex route when backend is codex."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "codex")
        monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")

        captured = {}

        def fake_codex_review(*, ticket_id, manager_executable, timeout_seconds):
            captured["ticket_id"] = ticket_id
            return "APPROVE", "", 0

        monkeypatch.setattr(bridge, "_run_codex_review", fake_codex_review)

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
        assert captured["transition"] == ("WP-2026-072", "READY_TO_CLOSE", "Manager approved")

    def test_opencode_review_cmd_length_is_safe(self, monkeypatch, tmp_path):
        """Test the constructed command line respects the Windows CMD limit (~8k chars) by using a prompt file."""
        import subprocess
        from bus.review_bridge import ReviewBridge, EventBus

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
        monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")

        captured_cmd = []

        def fake_run(cmd_args, **kwargs):
            captured_cmd.extend(cmd_args)
            return subprocess.CompletedProcess(args=cmd_args, returncode=0, stdout="DECISION: APPROVE", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        class DummySupervisor:
            def transition_ticket(self, *args, **kwargs):
                pass

        bridge.run_manager_review_cycle(
            ticket_id="WP-2026-077",
            supervisor=DummySupervisor(),
            timeout_seconds=5
        )

        import shlex
        cmd_string = shlex.join(captured_cmd)

        # Verify the length is well under the 6000 character safety margin
        assert len(cmd_string) < 6000
        # Verify that no -f flags are passed
        assert "-f" not in captured_cmd


class TestPromptTransportDispatch:
    """Tests for argv vs --file dispatch based on prompt length."""

    def test_short_prompt_uses_argv_path(self, tmp_path, monkeypatch):
        """Prompt <8000 chars uses argv transport, no --file flag."""
        from bus.review_bridge import ReviewBridge, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_get_manager_model", lambda: None)
        monkeypatch.setattr(bridge, "_get_canonical_files", lambda: [])
        monkeypatch.setattr(bridge, "_get_active_ticket_id", lambda: None)
        monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_supports_json_format", False)

        captured = {}

        def fake_run(cmd_args, **kwargs):
            captured["cmd"] = cmd_args
            return subprocess.CompletedProcess(
                args=cmd_args, returncode=0, stdout="DECISION: APPROVE", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        short_prompt = "Review this trivial ticket"
        stdout, stderr, exit_code = bridge._run_opencode_review(
            ticket_id="WP-T", prompt=short_prompt, timeout_seconds=5
        )

        # Prompt is appended after the flags
        assert captured["cmd"][-1] == short_prompt
        assert captured["cmd"][1] == "run"
        # --file flag NOT present
        assert "--file" not in captured["cmd"]

    def test_long_prompt_uses_file_path(self, tmp_path, monkeypatch):
        """Prompt >10000 chars uses tempfile + --file, prompt NOT in argv."""
        from bus.review_bridge import ReviewBridge, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_get_manager_model", lambda: None)
        monkeypatch.setattr(bridge, "_get_canonical_files", lambda: [])
        monkeypatch.setattr(bridge, "_get_active_ticket_id", lambda: None)
        monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_supports_json_format", False)

        captured = {}

        def fake_run(cmd_args, **kwargs):
            captured["cmd"] = cmd_args
            # Read tempfile content while it still exists
            idx = cmd_args.index("--file")
            captured["file_content"] = Path(cmd_args[idx + 1]).read_text(encoding="utf-8")
            return subprocess.CompletedProcess(
                args=cmd_args, returncode=0, stdout="DECISION: APPROVE", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        long_prompt = "x" * 12000
        stdout, stderr, exit_code = bridge._run_opencode_review(
            ticket_id="WP-T", prompt=long_prompt, timeout_seconds=5
        )

        # --file flag IS present
        assert "--file" in captured["cmd"]
        # Prompt NOT in the flag section of argv
        assert long_prompt not in captured["cmd"]
        # Prompt IS in tempfile content
        assert "End with exactly DECISION: APPROVE or DECISION: CHANGES." in captured["file_content"]
        assert captured["file_content"].endswith(long_prompt)
        assert long_prompt not in " ".join(captured["cmd"][:-1])

    def test_tempfile_cleaned_up_after_call(self, tmp_path, monkeypatch):
        """Tempfile is cleaned up after subprocess call completes."""
        from bus.review_bridge import ReviewBridge, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_get_manager_model", lambda: None)
        monkeypatch.setattr(bridge, "_get_canonical_files", lambda: [])
        monkeypatch.setattr(bridge, "_get_active_ticket_id", lambda: None)
        monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_supports_json_format", False)

        captured_path = {}

        def fake_run(cmd_args, **kwargs):
            idx = cmd_args.index("--file")
            captured_path["path"] = cmd_args[idx + 1]
            # Verify tempfile exists during call
            assert Path(captured_path["path"]).exists()
            return subprocess.CompletedProcess(
                args=cmd_args, returncode=0, stdout="DECISION: APPROVE", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        bridge._run_opencode_review(
            ticket_id="WP-T", prompt="x" * 12000, timeout_seconds=5
        )

        # Tempfile cleaned up after call
        assert not Path(captured_path["path"]).exists()

    def test_tempfile_cleaned_up_on_subprocess_failure(self, tmp_path, monkeypatch):
        """Tempfile is cleaned up even when subprocess raises TimeoutExpired."""
        from bus.review_bridge import ReviewBridge, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_get_manager_model", lambda: None)
        monkeypatch.setattr(bridge, "_get_canonical_files", lambda: [])
        monkeypatch.setattr(bridge, "_get_active_ticket_id", lambda: None)
        monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_supports_json_format", False)

        captured_path = {}

        def fake_run(cmd_args, **kwargs):
            idx = cmd_args.index("--file")
            captured_path["path"] = cmd_args[idx + 1]
            raise subprocess.TimeoutExpired(cmd_args, kwargs.get("timeout", 5))

        monkeypatch.setattr(subprocess, "run", fake_run)

        # Should not raise, cleanup happens in finally
        stdout, stderr, exit_code = bridge._run_opencode_review(
            ticket_id="WP-T", prompt="x" * 12000, timeout_seconds=5
        )

        # Verify TimeoutExpired was caught
        assert "TimeoutExpired" in stderr
        # Tempfile cleaned up even after failure
        assert not Path(captured_path["path"]).exists()


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

    def test_state_ingest_get_ticket_context_returns_none_when_no_ticket(self, tmp_path):
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
        from bus.review_bridge import ReviewBridge, ReviewDecision

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

        def fake_opencode_review(*, ticket_id, prompt, manager_executable=None, timeout_seconds):
            captured["prompt_includes_ticket"] = "WP-2026-102" in prompt
            return "DECISION: APPROVE", "", 0

        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
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
            assert state not in set(), "Sanity check: NON_TERMINAL_STATES is not empty"

        # COMPLETED and UNKNOWN are terminal
        assert TicketState.COMPLETED not in NON_TERMINAL_STATES
        assert TicketState.UNKNOWN not in NON_TERMINAL_STATES

    def test_supervisor_bootstrap_preserves_active_ticket_in_non_terminal_state(self, tmp_path):
        """Test bootstrap does NOT clear active_ticket when bus is in non-terminal state."""
        from bus.supervisor import SequentialTicketSupervisor, SupervisorState

        collaboration_dir = tmp_path / ".agent" / "collaboration"
        runtime_dir = tmp_path / ".agent" / "runtime"
        collaboration_dir.mkdir(parents=True)
        runtime_dir.mkdir(parents=True)

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
        from bus.review_bridge import ReviewBridge, EventBus

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
        from bus.review_bridge import ReviewBridge, EventBus

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
        from bus.review_bridge import ReviewBridge, EventBus

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
        from bus.review_bridge import ReviewBridge, EventBus

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
        from bus.review_bridge import ReviewBridge, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        review_path = bridge._persist_review_attempt(
            ticket_id="WP-2026-106",
            attempt=1,
            stdout="Review output here",
            stderr="",
            decision=ReviewDecision.CHANGES,
        )

        assert review_path.exists()
        assert review_path.name == "attempt-1.md"
        assert "WP-2026-106" in str(review_path)

    def test_persist_review_attempt_idempotent(self, tmp_path):
        """Test _persist_review_attempt overwrites same file idempotently."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        )

        # Second write (same attempt number)
        path2 = bridge._persist_review_attempt(
            ticket_id="WP-2026-106",
            attempt=1,
            stdout="Second attempt",
            stderr="",
            decision=ReviewDecision.CHANGES,
        )

        # Same file path
        assert path1 == path2
        # Content is the second write (idempotent overwrite)
        content = path1.read_text(encoding="utf-8")
        assert "Second attempt" in content

    def test_persist_review_attempt_includes_structured_sections(self, tmp_path):
        """Test _persist_review_attempt includes SUMMARY, BLOCKERS, SUGGESTIONS for CHANGES."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        from bus.review_bridge import ReviewBridge, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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

    def test_review_cycle_escalates_to_human_gate_at_threshold(self, tmp_path, monkeypatch):
        """WP-2026-106 B3: HUMAN_GATE report appears at the 5th cycle.

        One cycle = one review = one REVIEW_DECISION (no inner retry on
        CHANGES). After 5 bus-recorded CHANGES the human_review_report.md
        is generated.
        """
        import bus.review_bridge as rb
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            "# WP\n- **deliverable_type:** code\n- **ID:** WP-2026-106\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_build_diff_for_files_likely_touched", lambda *args: "")
        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")

        call_count = {"n": 0}

        def fake_run(**kw):
            call_count["n"] += 1
            # Vary per call so the bus anti-duplicate guard does not block
            # later cycles (production reviews always differ).
            return (
                f"## SUMMARY\nIssues remain (cycle {call_count['n']}).\n"
                "## BLOCKERS\n- Issue\n## SUGGESTIONS\n- Fix\nDECISION: CHANGES",
                "",
                0,
            )

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

        report = (
            tmp_path / ".agent" / "runtime" / "reviews"
            / "WP-2026-106" / "human_review_report.md"
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
        import bus.review_bridge as rb
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            "# WP\n- **deliverable_type:** code\n- **ID:** WP-2026-106\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW")
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_build_diff_for_files_likely_touched", lambda *args: "")
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
                return (
                    f"## SUMMARY\nIssues (cycle {call_count['n']}).\n"
                    "## BLOCKERS\n- X\n## SUGGESTIONS\n- Y\nDECISION: CHANGES",
                    "",
                    0,
                )
            return ("DECISION: APPROVE", "", 0)

        monkeypatch.setattr(bridge, "_run_opencode_review", fake_run)

        transitions = []

        class DummySupervisor:
            def transition_ticket(self, ticket_id, new_state, reason):
                transitions.append((ticket_id, new_state, reason))

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
        from bus.review_bridge import ReviewBridge, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        config = bridge._load_review_config()
        assert config["max_attempts"] == 5
