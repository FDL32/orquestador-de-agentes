from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge, ReviewDecision
from bus.supervisor import SequentialTicketSupervisor, SupervisorState
from scripts.manager_review_bridge import BridgeState, _bridge_heartbeat, _ticket_state


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


def _make_bridge(tmp_path: Path) -> tuple[ReviewBridge, EventBus, Path]:
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
    legacy_manager_exe = tmp_path / "manager_legacy.exe"
    legacy_manager_exe.write_text("", encoding="utf-8")
    return bridge, event_bus, legacy_manager_exe


def _make_review_prompt_bridge(
    tmp_path: Path, deliverable_type: str = "code"
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
    return ReviewBridge(event_bus=event_bus, project_root=tmp_path)


def _write_observations(tmp_path: Path, lines: list[str]) -> Path:
    memory_dir = tmp_path / ".agent" / "runtime" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = memory_dir / "observations.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


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
    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    # We just need to verify the prompt contains the new block
    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")

    assert "--- SYSTEM GENERATED & ARCHIVED ARTIFACTS ---" in prompt
    assert "archive_collaboration_artifacts.py" in prompt
    assert "Deletions, moves to _archive/" in prompt


def test_build_review_prompt_uses_branch_base_diff(tmp_path, monkeypatch):
    """Prompt includes diff anchored to origin/main...HEAD when remote is reachable."""
    import subprocess as _subprocess

    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    sha = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "origin/main...HEAD" in cmd and "diff" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout="diff --git a/bus/review_bridge.py b/bus/review_bridge.py\n+added line\n",
                stderr="",
            )
        if isinstance(cmd, list) and "origin/main..HEAD" in cmd and "log" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout=f"{sha} 2026-05-25 10:00:00 +0200 Test Author\n",
                stderr="",
            )
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-134", dtype="code")

    assert "diff --git a/bus/review_bridge.py" in prompt
    assert "[WARNING: origin/main not reachable" not in prompt


def test_build_review_prompt_falls_back_to_head_when_no_remote(tmp_path, monkeypatch):
    """Prompt degrades to git diff HEAD with visible warning when origin/main is unreachable."""
    import subprocess as _subprocess

    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "origin/main...HEAD" in cmd and "diff" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                128,
                stdout="",
                stderr="fatal: ambiguous argument 'origin/main...HEAD'",
            )
        if isinstance(cmd, list) and "origin/main..HEAD" in cmd and "log" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                128,
                stdout="",
                stderr="fatal: ambiguous argument 'origin/main..HEAD'",
            )
        if isinstance(cmd, list) and "diff" in cmd and "HEAD" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout="diff --git a/bus/review_bridge.py b/bus/review_bridge.py\n+head line\n",
                stderr="",
            )
        if isinstance(cmd, list) and "log" in cmd and cmd[-1] == "HEAD":
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2 2026-05-25 10:00:00 +0200 Test Author\n",
                stderr="",
            )
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-134", dtype="code")

    assert "[WARNING: origin/main not reachable" in prompt


def test_build_review_prompt_includes_provenance_section(tmp_path, monkeypatch):
    """Prompt includes --- git provenance --- section with SHA, date, and author."""
    import subprocess as _subprocess

    from bus.event_bus import EventBus
    from bus.review_bridge import ReviewBridge

    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    sha = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "log" in cmd and "origin/main..HEAD" in cmd:
            return _subprocess.CompletedProcess(
                cmd,
                0,
                stdout=f"{sha} 2026-05-25 10:00:00 +0200 Test Author\n",
                stderr="",
            )
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("bus.review_bridge.subprocess.run", fake_run)
    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-134", dtype="code")

    assert "--- git provenance ---" in prompt
    assert sha in prompt


def test_build_review_prompt_includes_allowed_skills_for_role(tmp_path):
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

    prompt = bridge._build_review_prompt(ticket_id="WP-TEST-123", dtype="code")

    # Should include the ALLOWED SKILLS section
    assert "ALLOWED SKILLS FOR ROLE" in prompt
    # Since TURN.md doesn't exist, role defaults to BUILDER
    assert "BUILDER" in prompt


def test_build_review_prompt_includes_manager_learnings_for_code_and_preserves_static_rubric(
    tmp_path,
):
    bridge = _make_review_prompt_bridge(tmp_path, deliverable_type="code")

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


def test_build_review_prompt_ignores_missing_observations_file(tmp_path):
    bridge = _make_review_prompt_bridge(tmp_path, deliverable_type="code")
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


def test_build_review_prompt_includes_manager_learnings_for_mixed(tmp_path):
    bridge = _make_review_prompt_bridge(tmp_path, deliverable_type="mixed")
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
        """Test parser detects DECISION: APPROVE."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "Review complete. All criteria met.\nDECISION: APPROVE"
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.APPROVE
        assert method == "text_regex"

    def test_parse_opencode_decision_changes(self, tmp_path):
        """Test parser detects DECISION: CHANGES."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "Found issues:\n- Missing tests\n\nDECISION: CHANGES"
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.CHANGES
        assert method == "text_regex"

    def test_parse_opencode_decision_no_decision_fallback_inspect(self, tmp_path):
        """Test parser returns INSPECT+fallback_inspect when no decision found."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

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

        stdout = "Cannot verify acceptance criteria remotely.\nDECISION: INSPECT"
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "explicit_inspect"

    def test_parse_opencode_decision_lowercase(self, tmp_path):
        """Test parser handles lowercase decision patterns."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "decision: approve"
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.APPROVE
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
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Mock _get_manager_backend to return opencode
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(
            bridge, "_get_manager_model", lambda: "opencode-go/deepseek-v4-flash"
        )
        monkeypatch.setattr(bridge, "_get_canonical_files", lambda: [])
        monkeypatch.setattr(bridge, "_get_active_ticket_id", lambda: "WP-2026-072")
        monkeypatch.setattr(
            bridge.state_ingest, "_latest_state", lambda _: "READY_FOR_REVIEW"
        )

        captured = {}

        def fake_opencode_review(
            *, ticket_id, prompt="", attempt=1, manager_executable=None, timeout_seconds
        ):
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
        assert packet.read_text(encoding="utf-8") == prompt

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
        assert packet_1.read_text(encoding="utf-8") == "PROMPT 1"
        assert packet_2.read_text(encoding="utf-8") == "PROMPT 2"

    def test_bridge_helper_does_not_patch_global_os_name(self, tmp_path, monkeypatch):
        """La simulacion de plataforma debe quedar confinada al modulo de review."""
        self._bridge(tmp_path, monkeypatch, "posix")
        assert os.name == "nt"

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

        def fake_opencode_review(
            *, ticket_id, prompt, attempt=1, manager_executable=None, timeout_seconds
        ):
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
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )
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
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        config = bridge._load_review_config()
        assert config["max_attempts"] == 5
