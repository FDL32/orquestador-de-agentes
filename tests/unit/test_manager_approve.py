"""Tests for --manager-approve flag in WP-2026-068."""

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from bus.event_bus import EventBus


@pytest.fixture
def temp_bus(tmp_path: Path) -> EventBus:
    """Create a temporary event bus for testing."""
    runtime_dir = tmp_path / "runtime" / "events"
    return EventBus(runtime_dir)


@pytest.fixture
def mock_files(tmp_path: Path) -> dict:
    """Create mock collaboration files."""
    collab_dir = tmp_path / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True, exist_ok=True)

    work_plan = collab_dir / "work_plan.md"
    work_plan.write_text(
        "# Plan de Trabajo: WP-TEST-001\n\n"
        "## Metadata\n"
        "- **ID:** WP-TEST-001\n"
        "- **Estado:** APPROVED\n"
    )

    exec_log = collab_dir / "execution_log.md"
    exec_log.write_text(
        "# Execution Log\n\n## WP-TEST-001\n**Estado:** READY_FOR_REVIEW\n"
    )

    turn_file = collab_dir / "TURN.md"
    turn_file.write_text("# TURNO ACTUAL\n\n## Agente Activo\n")

    state_file = collab_dir / "STATE.md"
    state_file.write_text("# STATE\n\n- **Estado actual:** READY_FOR_REVIEW\n")

    return {
        "work_plan": work_plan,
        "exec_log": exec_log,
        "turn": turn_file,
        "state": state_file,
        "collab_dir": collab_dir,
    }


class TestManagerApprove:
    """Test suite for --manager-approve flag."""

    def test_complete_cascade_emitted(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should emit complete closeout cascade."""
        from agent_controller import _handle_manager_approve

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=False, force_mode=False
            )

        assert result == 0

        # Verify cascade events were emitted
        events = temp_bus.read_events(ticket_id="WP-TEST-001")
        event_types = [e.event_type for e in events]

        assert "REVIEW_DECISION" in event_types
        assert "STATE_CHANGED" in event_types
        assert "CLOSE_CONFIRMED" in event_types
        assert "SUPERVISOR_CLOSED" in event_types

        # Verify REVIEW_DECISION payload
        review_events = [e for e in events if e.event_type == "REVIEW_DECISION"]
        assert len(review_events) == 1
        assert review_events[0].payload["decision"] == "approve"
        assert review_events[0].payload["note"] == "Canonical closeout approved"

        # Verify STATE_CHANGED events
        state_events = [e for e in events if e.event_type == "STATE_CHANGED"]
        assert len(state_events) >= 2  # At least READY_TO_CLOSE and COMPLETED

        to_states = [e.payload.get("to_state") for e in state_events]
        assert "READY_TO_CLOSE" in to_states
        assert "COMPLETED" in to_states

    def test_backfills_closeout_when_markdown_completed_but_bus_empty(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """Markdown COMPLETED without SUPERVISOR_CLOSED in bus must backfill.

        Chat-driven closeouts can leave the log in COMPLETED while the bus
        (canonical authority) has no closeout events, making --validate fail
        permanently with no CLI repair path. manager-approve must reconcile
        toward the bus instead of returning a passive already_completed.
        """
        from agent_controller import _handle_manager_approve

        # Set state to COMPLETED with an empty bus (chat-driven drift)
        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-001\n**Estado:** COMPLETED\n"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            import io
            import sys

            captured = io.StringIO()
            sys.stdout = captured
            try:
                result = _handle_manager_approve(
                    "WP-TEST-001", json_output=True, force_mode=False
                )
            finally:
                sys.stdout = sys.__stdout__

        assert result == 0
        output = json.loads(captured.getvalue())
        assert output["status"] == "backfilled_closeout"

        # The canonical cascade must now exist in the bus, including a
        # synthetic BUILDER_EXIT (chat closeouts never ran --mark-ready)
        events = temp_bus.read_events(ticket_id="WP-TEST-001")
        event_types = [event.event_type for event in events]
        assert "SUPERVISOR_CLOSED" in event_types
        assert "STATE_CHANGED" in event_types
        assert "BUILDER_EXIT" in event_types
        builder_exit = next(e for e in events if e.event_type == "BUILDER_EXIT")
        assert builder_exit.payload["exit_reason"] == "backfilled_closeout"

    def test_idempotency_already_completed_without_bus(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """Without bus available, COMPLETED markdown returns already_completed."""
        from agent_controller import _handle_manager_approve

        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-001\n**Estado:** COMPLETED\n"
        )

        with (
            patch("agent_controller.event_bus", None),
            patch("agent_controller.BUS_AVAILABLE", False),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            import io
            import sys

            captured = io.StringIO()
            sys.stdout = captured
            try:
                result = _handle_manager_approve(
                    "WP-TEST-001", json_output=True, force_mode=False
                )
            finally:
                sys.stdout = sys.__stdout__

        assert result == 0
        output = json.loads(captured.getvalue())
        assert output["status"] == "already_completed"

    def test_blocks_if_not_ready_for_review(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should block if ticket not in READY_FOR_REVIEW."""
        from agent_controller import _handle_manager_approve

        # Set state to IN_PROGRESS
        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-001\n**Estado:** IN_PROGRESS\n"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=False, force_mode=False
            )

        assert result != 0

        # No events should be emitted
        events = temp_bus.read_events(ticket_id="WP-TEST-001")
        assert len(events) == 0

    def test_requires_ticket_id(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should fail without ticket_id."""
        from agent_controller import _handle_manager_approve

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
        ):
            result = _handle_manager_approve(None, json_output=False, force_mode=False)

        assert result != 0

    def test_json_output_on_completed(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve returns JSON when backfilling a markdown-only COMPLETED."""
        from agent_controller import _handle_manager_approve

        # Set state to COMPLETED with an empty bus (chat-driven drift)
        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-001\n**Estado:** COMPLETED\n"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            # Capture stdout
            captured = io.StringIO()
            sys.stdout = captured
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=True, force_mode=False
            )
            sys.stdout = sys.__stdout__

        assert result == 0
        output = json.loads(captured.getvalue())
        assert output["status"] == "backfilled_closeout"
        assert output["ticket_id"] == "WP-TEST-001"

    def test_circuit_breaker_reset(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should reset circuit breaker on success."""
        from agent_controller import _handle_manager_approve, _read_circuit_breaker

        # Pre-set circuit breaker to OPEN
        breaker_path = tmp_path / ".agent" / "runtime" / "circuit_breaker.json"
        breaker_path.parent.mkdir(parents=True, exist_ok=True)
        breaker_path.write_text(
            '{"state": "OPEN", "failures": 3, "reason": "test failure"}'
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller.CIRCUIT_BREAKER_PATH", breaker_path),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=False, force_mode=False
            )

        assert result == 0

        # Verify circuit breaker was reset
        breaker = _read_circuit_breaker()
        assert breaker["state"] == "CLOSED"

    def test_idempotency_via_bus_supervisor_closed(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """--manager-approve should be idempotent if SUPERVISOR_CLOSED exists in bus."""
        from agent_controller import _handle_manager_approve

        # Pre-populate bus with SUPERVISOR_CLOSED event for this ticket
        temp_bus.emit(
            event_type="SUPERVISOR_CLOSED",
            ticket_id="WP-TEST-001",
            actor="SUPERVISOR",
            payload={"source": "manager-approve", "reason": "Already closed"},
        )

        # Set markdown state to READY_FOR_REVIEW (simulating drift)
        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-001\n**Estado:** READY_FOR_REVIEW\n"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=True, force_mode=False
            )

        assert result == 0

        # Returns already_completed without re-emitting the cascade, but it
        # repairs the missing BUILDER_EXIT (chat closeouts skip --mark-ready)
        events = temp_bus.read_events(ticket_id="WP-TEST-001")
        event_types = [event.event_type for event in events]
        assert event_types.count("SUPERVISOR_CLOSED") == 1
        assert event_types.count("BUILDER_EXIT") == 1

        # Verify JSON output
        import io
        import sys

        captured = io.StringIO()
        sys.stdout = captured
        # Re-run to capture output
        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller._check_last_commit", return_value=(True, "")),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=True, force_mode=False
            )
        sys.stdout = sys.__stdout__

        output = json.loads(captured.getvalue())
        assert output["status"] == "already_completed"
        assert output["ticket_id"] == "WP-TEST-001"

    def test_documentation_ticket_bypasses_commit_check(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """Documentation ticket: manager-approve must skip _check_last_commit()."""
        from agent_controller import _handle_manager_approve

        # Override work_plan to documentation deliverable_type
        mock_files["work_plan"].write_text(
            "# Plan de Trabajo: WP-TEST-DOC\n\n"
            "## Metadata\n"
            "- **ID:** WP-TEST-DOC\n"
            "- **Estado:** APPROVED\n"
            "- **deliverable_type:** documentation\n"
        )

        # Set state to READY_FOR_REVIEW
        mock_files["exec_log"].write_text(
            "# Execution Log\n\n## WP-TEST-DOC\n**Estado:** READY_FOR_REVIEW\n"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            # _check_last_commit must NOT be called for documentation tickets.
            # A side_effect that raises proves the bypass works.
            patch(
                "agent_controller._check_last_commit",
                side_effect=RuntimeError("must not be called for docs"),
            ),
        ):
            result = _handle_manager_approve(
                "WP-TEST-DOC", json_output=False, force_mode=False
            )

        assert result == 0, (
            f"Expected 0 (closed for docs without commit check), got {result}"
        )

        # Verify cascade events were emitted (full closeout)
        events = temp_bus.read_events(ticket_id="WP-TEST-DOC")
        event_types = [e.event_type for e in events]
        assert "REVIEW_DECISION" in event_types
        assert "STATE_CHANGED" in event_types
        assert "CLOSE_CONFIRMED" in event_types
        assert "SUPERVISOR_CLOSED" in event_types

    def test_code_ticket_validates_last_commit_in_motor_root_for_external_motor_topology(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """Code tickets in motor/destino topology must validate against repo_motor."""
        from agent_controller import _handle_manager_approve

        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        (workspace_root / ".git").mkdir()

        motor_root = tmp_path / "motor"
        motor_root.mkdir()
        (motor_root / ".git").mkdir()

        captured_roots: list[Path] = []

        def _capture_commit_root(root: Path, ticket_id: str) -> tuple[bool, str]:
            captured_roots.append(root)
            return True, ""

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch("agent_controller.PROJECT_ROOT", workspace_root),
            patch("agent_controller._MOTOR_ROOT", motor_root),
            patch(
                "agent_controller._check_last_commit",
                side_effect=_capture_commit_root,
            ),
        ):
            result = _handle_manager_approve(
                "WP-TEST-001", json_output=False, force_mode=False
            )

        assert result == 0
        assert captured_roots == [motor_root.resolve()]

    def test_warn_message_is_actionable_and_shows_last_commit(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """WOT-2026-016t: the WARN emitted when the last commit fails closeout
        validation must be actionable, not just diagnostic.

        Before the fix, the WARN never showed the offending commit's literal
        text and did not distinguish the clean recommended path (commit +
        retry) from --force (presented as if it were the only way out). This
        barrier locks in all three: the structured reason, a stable clean-path
        substring, and --force as a conscious alternative.
        """
        from agent_controller import _handle_manager_approve

        structured_reason = (
            "Commit references [WOT-2026-999] but active ticket is WP-TEST-001"
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch(
                "agent_controller._check_last_commit",
                return_value=(False, structured_reason),
            ),
        ):
            captured_stderr = io.StringIO()
            sys.stderr = captured_stderr
            try:
                result = _handle_manager_approve(
                    "WP-TEST-001", json_output=False, force_mode=False
                )
            finally:
                sys.stderr = sys.__stderr__

        # Blocking behavior does NOT change: still a hard fail without --force.
        assert result == 1

        stderr_text = captured_stderr.getvalue()

        # (a) the structured reason from _check_last_commit is still present.
        assert structured_reason in stderr_text

        # (b) a stable, literal clean-path substring is present. This fixes
        # the exact wording Fase 2 produces (not a paraphrase), so reverting
        # the message text is what the MUTATION barrier below detects.
        assert "Recommended: commit your closeout referencing ticket" in stderr_text
        assert "then retry --manager-approve" in stderr_text

        # (c) --force is mentioned as a conscious alternative, not the only
        # path offered.
        assert "--force" in stderr_text
        assert "Alternatively" in stderr_text

    def test_warn_message_shows_real_last_commit_text_from_git(
        self, temp_bus: EventBus, mock_files: dict, tmp_path: Path
    ) -> None:
        """Integration-style barrier: with a REAL git repo (not a mocked
        _check_last_commit), the WARN must display the actual %s of the last
        commit, proving the best-effort lookup is not a complacent mock.

        Uses a generic 'checkpoint' commit message so the real
        _check_last_commit / _validate_closeout_commit_message reject it
        exactly like production would (keyword rule), without needing to
        also fake ticket-ID extraction.
        """
        from agent_controller import _handle_manager_approve

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        subprocess.run(
            ["git", "init"], cwd=repo_root, capture_output=True, text=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        (repo_root / "file.txt").write_text("content")
        subprocess.run(
            ["git", "add", "."],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        real_commit_message = "checkpoint: intermediate churn, not a real closeout"
        subprocess.run(
            ["git", "commit", "-m", real_commit_message],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )

        with (
            patch("agent_controller.event_bus", temp_bus),
            patch("agent_controller.BUS_AVAILABLE", True),
            patch("agent_controller.WORK_PLAN", mock_files["work_plan"]),
            patch("agent_controller.EXEC_LOG", mock_files["exec_log"]),
            patch("agent_controller.TURN_FILE", mock_files["turn"]),
            patch("agent_controller.STATE_FILE", mock_files["state"]),
            patch("agent_controller.AGENT_DIR", tmp_path / ".agent"),
            patch(
                "agent_controller._resolve_closeout_commit_root",
                return_value=repo_root,
            ),
        ):
            captured_stderr = io.StringIO()
            sys.stderr = captured_stderr
            try:
                result = _handle_manager_approve(
                    "WP-TEST-001", json_output=False, force_mode=False
                )
            finally:
                sys.stderr = sys.__stderr__

        assert result == 1
        stderr_text = captured_stderr.getvalue()
        # The literal %s of the real commit must appear verbatim: proves the
        # best-effort subprocess lookup in _handle_manager_approve returns the
        # actual last commit, not a placeholder.
        assert real_commit_message in stderr_text
        assert "Recommended: commit your closeout referencing ticket" in stderr_text
        assert "--force" in stderr_text


# WOT-2026-013u: CLI-contract barrier exercising the REAL --ticket parser via
# subprocess dispatch (not _handle_manager_approve with a hardcoded string), so
# it covers the parser branch the ticket fixes.
#
# Hermetic: builds its OWN throwaway project-root with a no-ticket work_plan, so
# the barrier does NOT depend on the live dogfooding workspace. The robust signal
# is "No ticket_id provided": present only when the parser fails to capture the
# ticket (the pre-fix symptom, emitted before any work_plan lookup); absent once
# the ticket is parsed (the flow then emits a different, downstream error).
_MA_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MA_NOT_PARSED = "No ticket_id provided"
_MA_FAKE_TICKET = "WOT-TEST-013U-MA"


def _ma_run_controller(*args: str) -> subprocess.CompletedProcess:
    controller = _MA_PROJECT_ROOT / ".agent" / "agent_controller.py"
    with tempfile.TemporaryDirectory() as tmp:
        collab = Path(tmp) / ".agent" / "collaboration"
        collab.mkdir(parents=True, exist_ok=True)
        (collab / "work_plan.md").write_text(
            "# Plan de Trabajo\n\nNo active ticket here.\n", encoding="utf-8"
        )
        return subprocess.run(
            [
                sys.executable,
                str(controller),
                *args,
                "--json",
                "--force",
                "--project-root",
                tmp,
            ],
            cwd=_MA_PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


class TestManagerApproveCLIContract:
    """WOT-2026-013u: --manager-approve must honor BOTH --ticket and positional."""

    def test_manager_approve_accepts_ticket_flag(self) -> None:
        """--manager-approve --ticket <id> captures the id via the --ticket parser.

        Mutation barrier: reintroducing the inverted condition
        `idx + 1 >= len(sys.argv)` leaves ticket_id None -> "No ticket_id provided"
        reappears and this test FAILS. Hermetic project-root, no live-state dep.
        """
        result = _ma_run_controller("--manager-approve", "--ticket", _MA_FAKE_TICKET)
        combined = result.stdout + result.stderr
        assert _MA_NOT_PARSED not in combined, combined

    def test_manager_approve_positional_ticket_still_supported(self) -> None:
        """Backward-compat: --manager-approve <id> (positional) keeps working."""
        result = _ma_run_controller("--manager-approve", _MA_FAKE_TICKET)
        combined = result.stdout + result.stderr
        assert _MA_NOT_PARSED not in combined, combined

    def test_manager_approve_without_ticket_reports_missing(self) -> None:
        """Negative control: with no ticket, "No ticket_id provided" appears,
        proving the marker is real and the positive tests are not vacuous."""
        result = _ma_run_controller("--manager-approve")
        combined = result.stdout + result.stderr
        assert _MA_NOT_PARSED in combined, combined


class TestBackfillIgnoresReconciledEvents:
    """WOT-2026-058z: el backfill y el invariante aplicaban criterios OPUESTOS.

    `WOT-2026-050a` (commit 3eaaac2, 2026-08-07) endurecio `validate` para que
    dejara de aceptar un `BUILDER_EXIT` sintetico: `_latest_real_builder_exit`
    DESCARTA los de `source == "reconcile_ticket"`. Correcto y deseado.

    Pero `_backfill_builder_exit` -- la funcion que REPARA justo ese hueco -- es
    de `7407e84` (2026-06-11), ANTERIOR, y su guarda seguia usando
    `latest_event(...)` SIN filtrar `source`. Resultado medido: un ticket
    reconciliado quedaba en un estado que `--manager-approve` NO reparaba, con
    `validate` en 1 error PERMANENTE tras cualquier cierre por chat.

    Escalado desde el repo_destino Crear_Texto_LLM; premisa RE-VERIFICADA aqui
    con probe ejecutado sobre las dos funciones del motor antes de tocar codigo.
    """

    def test_backfill_emits_when_only_event_is_reconciled(
        self, temp_bus: EventBus, tmp_path: Path
    ) -> None:
        """ROJO sin el fix: con SOLO un BUILDER_EXIT sintetico de
        reconcile_ticket, el backfill debe EMITIR uno real. Antes veia el
        sintetico y devolvia False sin emitir, dejando el invariante roto."""
        from agent_controller import _backfill_builder_exit

        ticket = "WOT-2026-058z-a"
        temp_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id=ticket,
            actor="BUILDER",
            payload={
                "source": "reconcile_ticket",
                "exit_reason": "reconcile_ticket: forced close",
            },
        )

        emitted = _backfill_builder_exit(temp_bus, ticket)

        assert emitted is True, (
            "un BUILDER_EXIT de reconcile_ticket es SINTETICO: el invariante lo "
            "descarta, luego el backfill debe emitir uno real o el ticket queda "
            "sin reparacion barata posible"
        )
        # Y el hueco queda REALMENTE cerrado: el invariante ya encuentra uno real.
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".agent"))
        from closure_invariants import _latest_real_builder_exit

        assert _latest_real_builder_exit(temp_bus, ticket) is not None, (
            "tras el backfill el invariante debe converger: si sigue en None, "
            "el fix no cierra el hueco que dice cerrar"
        )

    def test_backfill_still_noops_on_a_real_builder_exit(
        self, temp_bus: EventBus, tmp_path: Path
    ) -> None:
        """CONTROL NEGATIVO: la idempotencia NO se relaja. Un BUILDER_EXIT REAL
        (p.ej. de mark-ready) sigue impidiendo el backfill -- si esto cambiara,
        el bus ganaria una fila duplicada en CADA aprobacion normal."""
        from agent_controller import _backfill_builder_exit

        ticket = "WOT-2026-058z-b"
        temp_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id=ticket,
            actor="BUILDER",
            payload={"source": "mark-ready", "exit_reason": "handoff"},
        )

        assert _backfill_builder_exit(temp_bus, ticket) is False, (
            "con un BUILDER_EXIT real ya presente, el backfill es no-op"
        )

    def test_backfill_noops_on_its_own_previous_backfill(
        self, temp_bus: EventBus, tmp_path: Path
    ) -> None:
        """CONTROL NEGATIVO 2 (anti-bucle): el evento que el propio backfill
        emite NO es reconciliado, asi que una segunda pasada es no-op. Sin esto
        el fix anadiria una fila por cada invocacion de --manager-approve."""
        from agent_controller import _backfill_builder_exit

        ticket = "WOT-2026-058z-c"
        temp_bus.emit(
            event_type="BUILDER_EXIT",
            ticket_id=ticket,
            actor="BUILDER",
            payload={"source": "reconcile_ticket", "exit_reason": "forced"},
        )

        assert _backfill_builder_exit(temp_bus, ticket) is True
        assert _backfill_builder_exit(temp_bus, ticket) is False, (
            "segunda pasada debe ser no-op: el backfill no puede acumular filas"
        )

    def test_backfill_emits_when_bus_has_no_builder_exit_at_all(
        self, temp_bus: EventBus, tmp_path: Path
    ) -> None:
        """CONTROL POSITIVO heredado (7407e84): el caso original -- cierre por
        chat sin ningun BUILDER_EXIT -- sigue reparandose igual que antes."""
        from agent_controller import _backfill_builder_exit

        assert _backfill_builder_exit(temp_bus, "WOT-2026-058z-d") is True
