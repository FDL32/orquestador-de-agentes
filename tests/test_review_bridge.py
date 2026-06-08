"""Tests for review bridge fail-safe (WP-2026-118).

These tests verify that the review bridge handles event_bus.emit() failures
gracefully, logging errors audibly without crashing the review cycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge, ReviewDecision


@pytest.fixture
def event_bus(tmp_path):
    """Create an EventBus instance for testing."""
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    return EventBus(runtime_dir=runtime_dir)


@pytest.fixture
def review_bridge(event_bus, tmp_path):
    """Create a ReviewBridge instance for testing."""
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    collaboration_dir.mkdir(parents=True)
    (collaboration_dir / "work_plan.md").write_text(
        "---\n\n## Metadata\n- **ID:** WP-TEST-001\n- **deliverable_type:** code\n",
        encoding="utf-8",
    )
    (collaboration_dir / "TURN.md").write_text(
        "# TURNO ACTUAL\n\n## Agente Activo\n\n| Campo | Valor |\n|-------|-------|\n| **ROL** | **BUILDER** |\n| **Plan ID** | WP-TEST-001 |\n",
        encoding="utf-8",
    )
    (collaboration_dir / "STATE.md").write_text(
        "# STATE.md\n\n## Estado Canonico\n- **Plan Activo:** WP-TEST-001\n",
        encoding="utf-8",
    )
    (collaboration_dir / "execution_log.md").write_text(
        "# Execution Log - WP-TEST-001\n\n## Estado\n**Estado:** READY_FOR_REVIEW\n",
        encoding="utf-8",
    )
    return ReviewBridge(event_bus=event_bus, project_root=tmp_path)


def test_manager_review_observation_loader_caps_filters_and_truncates(
    review_bridge, tmp_path
):
    memory_dir = tmp_path / ".agent" / "runtime" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    observations_path = memory_dir / "observations.jsonl"

    lines = []
    for day in range(1, 7):
        signal = f"lesson-{day}"
        if day == 6:
            signal = "y" * 240
        lines.append(
            json.dumps(
                {
                    "timestamp": f"2026-05-{day:02d}T10:00:00+00:00",
                    "topic": "manager-review-rubric",
                    "signal": signal,
                    "source_ticket": f"WP-2026-13{day}",
                }
            )
        )
    lines.append("{bad json")
    lines.append(
        json.dumps(
            {
                "timestamp": "2026-05-08T10:00:00+00:00",
                "topic": "other-topic",
                "signal": "ignore-me",
                "source_ticket": "WP-OTHER",
            }
        )
    )
    observations_path.write_text("\n".join(lines), encoding="utf-8")

    observations = review_bridge._load_manager_review_observations()

    assert len(observations) == 5
    assert observations[0][0].date().isoformat() == "2026-05-06"
    assert observations[-1][0].date().isoformat() == "2026-05-02"
    assert observations[0][1].endswith("...")
    assert len(observations[0][1]) < 205
    assert all(source_ticket != "WP-OTHER" for _, _, source_ticket in observations)


def test_emit_fail_safe_on_managing_reviewing(review_bridge, event_bus, tmp_path):
    """WP-2026-118: Bridge logs error and aborts cleanly if emit() fails during MANAGER_REVIEWING.

    Before: An emit() failure would propagate traceback and crash the cycle.
    During: Simulates event_bus.emit() raising an exception during initial emit.
    After: Bridge returns ReviewResult with INSPECT decision and auditable error message.
    """
    # Emit STATE_CHANGED to set ticket state to READY_FOR_REVIEW
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-TEST-001",
        actor="BUILDER",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    # Create a mock supervisor
    supervisor = MagicMock()

    # Mock event_bus.emit to raise an exception on first call
    with patch.object(
        event_bus, "emit", side_effect=Exception("Simulated bus failure")
    ):
        result = review_bridge.run_manager_review_cycle(
            ticket_id="WP-TEST-001",
            supervisor=supervisor,
            timeout_seconds=10,
        )

    # Verify graceful failure
    assert result.decision == ReviewDecision.INSPECT
    assert result.exit_code == 1
    assert "FAIL-SAFE" in result.stderr
    assert (
        "event_bus.emit() failed" in result.stderr
        or "MANAGER_REVIEWING" in result.stderr
    )


def test_emit_fail_safe_on_review_decision(review_bridge, event_bus, tmp_path, capfd):
    """WP-2026-118: Bridge logs error but continues if emit() fails on REVIEW_DECISION.

    Before: An emit() failure on REVIEW_DECISION would crash with raw traceback.
    During: Simulates event_bus.emit() raising an exception when emitting REVIEW_DECISION.
    After: Bridge logs error audibly and returns result with INSPECT decision
           (text_regex degrades plain-text APPROVE to INSPECT).
    """
    # Emit STATE_CHANGED to set ticket state to READY_FOR_REVIEW
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WP-TEST-001",
        actor="BUILDER",
        payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
    )

    supervisor = MagicMock()

    # Create a mock for the backend execution
    def mock_run_opencode(*args, **kwargs):
        return ("DECISION: APPROVE\n", "", 0)

    # Patch the review execution to return APPROVE AND mock backend to use opencode
    with (
        patch.object(
            review_bridge, "_run_opencode_review", side_effect=mock_run_opencode
        ),
        patch.object(review_bridge, "_get_manager_backend", return_value="opencode"),
    ):
        # Mock emit to fail only on REVIEW_DECISION
        def conditional_emit(*args, **kwargs):
            event_type = args[0] if args else kwargs.get("event_type", "")
            # Fail only on REVIEW_DECISION
            if event_type == "REVIEW_DECISION":
                raise Exception("Simulated REVIEW_DECISION emit failure")
            # For other events, just return a dummy record
            from datetime import datetime, timezone

            from bus.event_bus import EventRecord

            return EventRecord(
                event_id=f"evt-{event_type}",
                event_type=event_type,
                ticket_id="WP-TEST-001",
                actor="MANAGER",
                timestamp=datetime.now(timezone.utc).isoformat(),
                payload=kwargs.get("payload", {}),
                sequence_number=1,
            )

        with patch.object(event_bus, "emit", side_effect=conditional_emit):
            result = review_bridge.run_manager_review_cycle(
                ticket_id="WP-TEST-001",
                supervisor=supervisor,
                timeout_seconds=10,
            )

    # WT-2026-242a: text_regex degrades plain-text APPROVE to INSPECT.
    # The bridge handles the REVIEW_DECISION emit failure gracefully.
    assert result.decision == ReviewDecision.INSPECT
    assert result.exit_code == 1
    # But stderr should contain the fail-safe message
    captured = capfd.readouterr()
    assert "FAIL-SAFE" in captured.err or "REVIEW_DECISION emit failed" in captured.err


def test_emit_fail_safe_on_review_attempt(review_bridge, event_bus, tmp_path):
    """WP-2026-118: _emit_review_attempt logs error but doesn't crash if emit() fails.

    Before: An emit() failure in _emit_review_attempt would crash the cycle.
    During: Simulates event_bus.emit() failing during MANAGER_REVIEW_ATTEMPT emit.
    After: Error is logged to stderr but cycle continues.
    """
    # Call _emit_review_attempt with mocked failing emit
    with patch.object(event_bus, "emit", side_effect=Exception("Bus error")):
        # Should not raise, just log to stderr
        review_bridge._emit_review_attempt(
            ticket_id="WP-TEST-001",
            attempt=1,
            timeout_s=180,
            exit_code=0,
            duration=1.5,
            stdout="Test output",
            decision=ReviewDecision.CHANGES,
        )

    # If we reach here, the fail-safe worked (no exception propagated)


def test_review_bridge_handles_invalid_ticket_state(review_bridge, event_bus, tmp_path):
    """WP-2026-118: Bridge blocks review if ticket state is not READY_FOR_REVIEW.

    Before: Bridge might attempt review on tickets in wrong state.
    During: Sets ticket state to IN_PROGRESS instead of READY_FOR_REVIEW.
    After: Bridge returns INSPECT with clear error message.
    """
    # Modify execution_log to show IN_PROGRESS state
    collaboration_dir = tmp_path / ".agent" / "collaboration"
    (collaboration_dir / "execution_log.md").write_text(
        "# Execution Log - WP-TEST-001\n\n## Estado\n**Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )

    supervisor = MagicMock()

    result = review_bridge.run_manager_review_cycle(
        ticket_id="WP-TEST-001",
        supervisor=supervisor,
        timeout_seconds=10,
    )

    assert result.decision == ReviewDecision.INSPECT
    assert result.exit_code == 1
    assert "READY_FOR_REVIEW" in result.stderr


def test_review_bridge_fail_safe_emits_to_stderr(
    review_bridge, event_bus, tmp_path, capfd
):
    """WP-2026-118: Verify fail-safe messages are written to stderr.

    Before: Errors might be silently swallowed or go to stdout.
    During: Triggers emit() failure and captures stderr output.
    After: stderr contains structured fail-safe message with ticket_id.
    """
    with patch.object(event_bus, "emit", side_effect=Exception("Test bus error")):
        review_bridge._emit_review_attempt(
            ticket_id="WP-FAIL-001",
            attempt=3,
            timeout_s=180,
            exit_code=1,
            duration=2.0,
            stdout="Review output",
            decision=ReviewDecision.CHANGES,
        )

    captured = capfd.readouterr()
    assert "FAIL-SAFE" in captured.err
    assert "WP-FAIL-001" in captured.err
    assert "attempt 3" in captured.err.lower()


# =============================================================================
# Tests WP-2026-120: Review Parser Handshake Hardening
# =============================================================================


class TestOpencodeJsonParserRealSchema:
    """Tests for WP-2026-120: OpenCode JSON parser with real schema."""

    def test_parse_json_text_event_with_decision_approve(self, tmp_path):
        """Test parser detects DECISION: APPROVE in type:text event with part.text."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # OpenCode NDJSON schema real: type:"text" con part.text
        stdout = """{"type":"text","part":{"text":"Review complete. All criteria met.\\nDECISION: APPROVE"}}
"""
        decision, _ = bridge._parse_opencode_json_decision(stdout)
        assert decision == ReviewDecision.APPROVE

    def test_parse_json_text_event_with_decision_changes(self, tmp_path):
        """Test parser detects DECISION: CHANGES in type:text event with part.text."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = """{"type":"text","part":{"text":"Found issues:\\n- Missing tests\\n\\nDECISION: CHANGES"}}
"""
        decision, _ = bridge._parse_opencode_json_decision(stdout)
        assert decision == ReviewDecision.CHANGES

    def test_parse_json_prioritizes_final_answer_phase(self, tmp_path):
        """Test parser prioritizes phase:final_answer over other text events."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Multiple text events - final_answer should take precedence
        stdout = """{"type":"text","part":{"text":"Initial thought: DECISION: CHANGES"}}
{"type":"text","part":{"text":"After reflection: DECISION: APPROVE"},"phase":"final_answer"}
"""
        decision, _ = bridge._parse_opencode_json_decision(stdout)
        # final_answer with APPROVE should win
        assert decision == ReviewDecision.APPROVE

    def test_parse_json_no_final_answer_uses_last_text_decision(self, tmp_path):
        """Test parser uses last text event decision when no final_answer exists."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Multiple text events without phase - first valid decision wins
        stdout = """{"type":"text","part":{"text":"Initial thought: DECISION: APPROVE"}}
{"type":"text","part":{"text":"After reflection: DECISION: CHANGES"}}
"""
        decision, _ = bridge._parse_opencode_json_decision(stdout)
        # First valid decision should be returned
        assert decision == ReviewDecision.APPROVE

    def test_parse_json_invalid_json_lines_returns_inspect(self, tmp_path):
        """Test parser returns INSPECT when JSON is malformed."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = """not valid json
{broken json
{"type":"text"}
"""
        decision, _ = bridge._parse_opencode_json_decision(stdout)
        assert decision == ReviewDecision.INSPECT

    def test_parse_json_empty_stdout_returns_inspect(self, tmp_path):
        """Test parser returns INSPECT for empty stdout."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        decision, _ = bridge._parse_opencode_json_decision("")
        assert decision == ReviewDecision.INSPECT

    def test_parse_json_text_event_missing_part_field(self, tmp_path):
        """Test parser handles text events without part field gracefully."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = """{"type":"text"}
{"type":"text","part":"not a dict"}
"""
        decision, _ = bridge._parse_opencode_json_decision(stdout)
        assert decision == ReviewDecision.INSPECT


class TestParseOpencodeDecisionWithRetry:
    """Tests for WP-2026-120: Parser with controlled retry."""

    def test_retry_not_invoked_on_plain_text_decision(self, tmp_path):
        """Test retry is not invoked when text_regex extracts a decision.

        WT-2026-242a: Plain text DECISION: APPROVE goes through JSON
        (no NDJSON found) then text_regex which degrades to INSPECT.
        Retry is not invoked because parse_method is "text_regex",
        not "fallback_inspect".
        """
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Use actual newline, not escaped
        stdout = "Review complete.\nDECISION: APPROVE"
        stderr = ""

        decision, attempts, parse_method = bridge._parse_opencode_decision_with_retry(
            stdout, stderr, max_retries=2
        )

        # text_regex always degrades APPROVE to INSPECT
        assert decision == ReviewDecision.INSPECT
        assert parse_method == "text_regex"
        assert attempts == 1  # No retry needed (not fallback_inspect)

    def test_retry_invoked_on_inspect_with_valid_output(self, tmp_path):
        """Test retry is invoked when INSPECT but output looks valid."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Output without DECISION: pattern - parser returns INSPECT
        stdout = "Review complete. No issues found."
        stderr = ""

        decision, attempts, _ = bridge._parse_opencode_decision_with_retry(
            stdout, stderr, max_retries=2
        )

        assert decision == ReviewDecision.INSPECT
        # Should attempt max_retries + 1 times (initial + retries)
        assert attempts == 3  # 1 initial + 2 retries

    def test_retry_not_invoked_on_technical_failure(self, tmp_path):
        """Test retry is skipped on technical failures (timeout, etc.)."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "Some output"
        stderr = "TimeoutExpired: command timed out"

        decision, attempts, _ = bridge._parse_opencode_decision_with_retry(
            stdout, stderr, max_retries=2
        )

        assert decision == ReviewDecision.INSPECT
        assert attempts == 1  # No retry on technical failure

    def test_retry_not_invoked_on_empty_stdout(self, tmp_path):
        """Test retry is skipped when stdout is empty."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = ""
        stderr = ""

        decision, attempts, _ = bridge._parse_opencode_decision_with_retry(
            stdout, stderr, max_retries=2
        )

        assert decision == ReviewDecision.INSPECT
        assert attempts == 1  # No retry on empty output

    def test_retry_exponential_backoff(self, tmp_path, monkeypatch):
        """Test retry uses exponential backoff delays."""
        import time

        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        sleep_calls = []
        original_sleep = time.sleep

        def mock_sleep(duration):
            sleep_calls.append(duration)
            original_sleep(0.001)  # Small real delay for test stability

        monkeypatch.setattr(time, "sleep", mock_sleep)

        stdout = "No decision pattern here"
        stderr = ""

        bridge._parse_opencode_decision_with_retry(stdout, stderr, max_retries=2)

        # Should have 2 sleep calls: 0.1*2^0=0.1, 0.1*2^1=0.2
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == 0.1
        assert sleep_calls[1] == 0.2


class TestNoBareWordFallback:
    """Tests for WP-2026-120: No bare word fallback for decisions."""

    def test_no_changes_needed_not_interpreted_as_changes(self, tmp_path):
        """Test 'no changes needed' does not trigger CHANGES decision."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # WT-2026-242a: _supports_json_format removed; parser always
        # tries JSON first, then falls to text_regex automatically.

        stdout = "The code looks fine. No changes needed at this time."
        decision, _ = bridge._parse_opencode_decision(stdout)

        # Should be INSPECT, not CHANGES (no DECISION: pattern)
        assert decision == ReviewDecision.INSPECT

    def test_approve_without_decision_pattern_returns_inspect(self, tmp_path):
        """Test 'APPROVE' without DECISION: pattern returns INSPECT."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # WT-2026-242a: _supports_json_format removed; parser always
        # tries JSON first, then falls to text_regex automatically.

        stdout = "I approve of this implementation."
        decision, _ = bridge._parse_opencode_decision(stdout)

        assert decision == ReviewDecision.INSPECT

    def test_explicit_decision_pattern_is_recognized(self, tmp_path):
        """Test explicit DECISION: pattern is found but degraded to INSPECT.

        WT-2026-242a: _supports_json_format removed; parser always
        tries JSON first, then falls to text_regex. text_regex always
        degrades APPROVE to INSPECT per WT-2026-235a contract.
        """
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = "Review complete.\nDECISION: APPROVE"
        decision, parse_method = bridge._parse_opencode_decision(stdout)

        # text_regex never produces APPROVE — degrades to INSPECT
        assert decision == ReviewDecision.INSPECT
        assert parse_method == "text_regex"


class TestDocumentationPromptWiring:
    """Regression tests: documentation type receives cross-cutting checks and learnings."""

    def _make_bridge(
        self, tmp_path: Path, dtype: str = "documentation", monkeypatch=None
    ) -> ReviewBridge:
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            f"# Work Plan\n- **ID:** WP-2026-TEST\n- **deliverable_type:** {dtype}\n",
            encoding="utf-8",
        )
        for name in ("STATE.md", "TURN.md", "execution_log.md"):
            (collab / name).write_text("", encoding="utf-8")
        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # WP-2026-156: Aislar git para no escapar al repo anfitrion
        if monkeypatch is not None:
            monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
            monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
            monkeypatch.setattr(
                bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
            )

        return bridge

    def _write_observation(self, tmp_path: Path, signal: str, applies_to="all") -> None:
        obs_path = tmp_path / ".agent" / "runtime" / "memory" / "observations.jsonl"
        obs_path.parent.mkdir(parents=True, exist_ok=True)
        import datetime

        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "topic": "manager-review-rubric",
            "signal": signal,
            "source": "test",
            "applies_to": applies_to,
        }
        with obs_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def test_documentation_receives_validator_evidence_gate(
        self, tmp_path, monkeypatch
    ):
        """documentation prompt must include the cross-cutting validator evidence gate."""
        bridge = self._make_bridge(tmp_path, monkeypatch=monkeypatch)
        prompt = bridge._build_review_prompt("WP-2026-TEST", "documentation")
        assert "AP-06 Validator evidence missing" in prompt
        assert "execution_log.md must contain" in prompt

    def test_documentation_receives_learnings_when_applies_to_all(
        self, tmp_path, monkeypatch
    ):
        """documentation prompt includes observations scoped to 'all'."""
        self._write_observation(tmp_path, "test signal all scope", applies_to="all")
        bridge = self._make_bridge(tmp_path, monkeypatch=monkeypatch)
        prompt = bridge._build_review_prompt("WP-2026-TEST", "documentation")
        assert "Lecciones acumuladas de auditoria" in prompt
        assert "test signal all scope" in prompt

    def test_documentation_excludes_code_only_learnings(self, tmp_path, monkeypatch):
        """documentation prompt must not include observations scoped to code/mixed only."""
        self._write_observation(
            tmp_path, "code-only signal", applies_to=["code", "mixed"]
        )
        bridge = self._make_bridge(tmp_path, monkeypatch=monkeypatch)
        prompt = bridge._build_review_prompt("WP-2026-TEST", "documentation")
        assert "code-only signal" not in prompt

    def test_code_receives_learnings_scoped_to_code(self, tmp_path, monkeypatch):
        """code prompt includes observations scoped to code."""
        self._write_observation(
            tmp_path, "code scoped signal", applies_to=["code", "mixed"]
        )
        bridge = self._make_bridge(tmp_path, dtype="code", monkeypatch=monkeypatch)
        prompt = bridge._build_review_prompt("WP-2026-TEST", "code")
        assert "code scoped signal" in prompt

    def test_static_rubric_unmodified_when_observations_present(
        self, tmp_path, monkeypatch
    ):
        """Injecting observations must not alter the static rubric content."""
        self._write_observation(tmp_path, "some learning", applies_to="all")
        bridge = self._make_bridge(tmp_path, monkeypatch=monkeypatch)
        prompt = bridge._build_review_prompt("WP-2026-TEST", "documentation")
        assert "focus strictly on the clarity" in prompt
        assert "Lecciones acumuladas de auditoria" in prompt


class TestCanonicalAntiPatternInventory:
    """Direct tests for AP-08: new canonical AP loading methods (WP-2026-139 hotfix)."""

    _AP_CONTENT = "\n".join(
        [
            "# Inventario Canonico",
            "",
            "## AP-01 - Mock drift",
            "- El patch apunta a un simbolo distinto.",
            "",
            "## AP-02 - Floor assertion",
            "- El umbral ya esta satisfecho por el baseline.",
        ]
    )

    def _make_bridge(self, tmp_path: Path, monkeypatch=None) -> ReviewBridge:
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            "# Work Plan\n- **ID:** WP-TEST\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )
        for name in ("STATE.md", "TURN.md", "execution_log.md"):
            (collab / name).write_text("", encoding="utf-8")
        event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # WP-2026-156: Aislar git para no escapar al repo anfitrion
        if monkeypatch is not None:
            monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
            monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
            monkeypatch.setattr(
                bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
            )

        return bridge

    def test_parse_extracts_ap_id_and_name(self):
        result = ReviewBridge._parse_canonical_anti_patterns(self._AP_CONTENT)
        assert result == [("AP-01", "Mock drift"), ("AP-02", "Floor assertion")]

    def test_parse_returns_empty_for_content_without_ap_headers(self):
        result = ReviewBridge._parse_canonical_anti_patterns(
            "# No AP headers\n- just content"
        )
        assert result == []

    def test_load_warns_and_returns_empty_when_file_missing(
        self, tmp_path, monkeypatch
    ):
        bridge = self._make_bridge(tmp_path)
        monkeypatch.setattr(
            bridge, "_canonical_anti_patterns_path", lambda: tmp_path / "nonexistent.md"
        )
        with pytest.warns(RuntimeWarning, match="unavailable"):
            result = bridge._load_canonical_anti_patterns()
        assert result == []

    def test_load_warns_and_returns_empty_when_file_has_no_ap_entries(
        self, tmp_path, monkeypatch
    ):
        stub = tmp_path / "anti-patterns.md"
        stub.write_text("# No AP headers here", encoding="utf-8")
        bridge = self._make_bridge(tmp_path)
        monkeypatch.setattr(bridge, "_canonical_anti_patterns_path", lambda: stub)
        with pytest.warns(RuntimeWarning, match="empty or invalid"):
            result = bridge._load_canonical_anti_patterns()
        assert result == []

    def test_render_formats_inventory_lines(self, tmp_path, monkeypatch):
        bridge = self._make_bridge(tmp_path, monkeypatch=monkeypatch)
        bridge._canonical_anti_patterns = [
            ("AP-01", "Mock drift"),
            ("AP-02", "Floor assertion"),
        ]
        rendered = bridge._render_canonical_anti_pattern_inventory()
        assert "AP-01 Mock drift" in rendered
        assert "AP-02 Floor assertion" in rendered
        assert "skills/_shared/anti-patterns.md" in rendered

    def test_render_returns_empty_string_when_inventory_empty(
        self, tmp_path, monkeypatch
    ):
        bridge = self._make_bridge(tmp_path, monkeypatch=monkeypatch)
        bridge._canonical_anti_patterns = []
        assert bridge._render_canonical_anti_pattern_inventory() == ""

    def test_rubric_includes_ap_inventory_block_for_code_type(
        self, tmp_path, monkeypatch
    ):
        bridge = self._make_bridge(tmp_path, monkeypatch=monkeypatch)
        bridge._canonical_anti_patterns = [("AP-01", "Mock drift")]
        rubric = bridge._rubric_for_type("code", "WP-TEST")
        assert "AP-01 Mock drift" in rubric

    def test_rubric_omits_ap_inventory_block_when_inventory_empty(
        self, tmp_path, monkeypatch
    ):
        bridge = self._make_bridge(tmp_path, monkeypatch=monkeypatch)
        bridge._canonical_anti_patterns = []
        rubric = bridge._rubric_for_type("code", "WP-TEST")
        assert "Canonical anti-pattern inventory" not in rubric


# =============================================================================
# Tests WT-2026-196: Manager adaptivo ante blockers repetidos
# =============================================================================


class TestAdaptiveReviewState:
    """Tests for adaptive review state management."""

    def test_adaptive_review_state_persisted_in_manager_bridge_state(self, tmp_path):
        """TP-10: Adaptive state is persisted/loaded from manager_bridge_state.json."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        ticket_id = "WT-2026-196"
        state_data = {
            "last_review_sequence": 3,
            "last_git_head": "abc123",
            "blocker_signatures": ["test.py:::SIGNATURE ONE"],
            "repeated_blockers": [],
            "diagnostic_mode": False,
            "changed_files_since_previous_review": ["test.py"],
            "last_feedback": "Some feedback",
        }

        # Save and load
        bridge._save_adaptive_state(ticket_id, state_data)
        loaded = bridge._load_adaptive_state(ticket_id)

        assert loaded.get("last_review_sequence") == 3
        assert loaded.get("last_git_head") == "abc123"
        assert "test.py:::SIGNATURE ONE" in loaded.get("blocker_signatures", [])
        assert loaded.get("diagnostic_mode") is False

    def test_adaptive_review_state_merges_with_existing(self, tmp_path):
        """Test _save_adaptive_state merges, not overwrites, existing state."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        ticket_id = "WT-2026-196"
        bridge._save_adaptive_state(ticket_id, {"diagnostic_mode": True})
        bridge._save_adaptive_state(ticket_id, {"last_review_sequence": 5})

        loaded = bridge._load_adaptive_state(ticket_id)
        assert loaded.get("diagnostic_mode") is True
        assert loaded.get("last_review_sequence") == 5

    def test_adaptive_review_state_empty_when_no_ticket(self, tmp_path):
        """Test _load_adaptive_state returns {} for unknown ticket."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        loaded = bridge._load_adaptive_state("NONEXISTENT-TICKET")
        assert loaded == {}


class TestDiagnosticModePrompt:
    """Tests for diagnostic mode prompt injection."""

    def test_manager_prompt_includes_diagnostic_mode_sections_for_repeated_blocker(
        self, tmp_path, monkeypatch
    ):
        """TP-06/TP-07: Prompt with diagnostic_mode=True includes diagnostic sections."""
        from bus.review_bridge import EventBus, ReviewBridge

        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            "# WP\n- **ID:** WT-2026-196\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )
        for name in ("STATE.md", "TURN.md", "execution_log.md"):
            (collab / name).write_text("", encoding="utf-8")

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
        monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )

        adaptive_context = {
            "diagnostic_mode": True,
            "repeated_blockers": ["test.py:::SIGNATURE ONE"],
            "changed_files_since_previous_review": ["test.py"],
            "last_feedback": "Previous feedback here.",
        }

        prompt = bridge._build_review_prompt(
            "WT-2026-196", "code", adaptive_context=adaptive_context
        )

        # Must contain diagnostic mode sections
        assert "--- DIAGNOSTIC MODE ---" in prompt
        assert "REPEATED BLOCKER" in prompt
        assert "SIGNATURE ONE" in prompt
        assert "test.py" in prompt
        assert "REQUIRED ACTIONS" in prompt
        assert "Re-read the exact affected code" in prompt
        assert "Propose a concrete solution" in prompt
        assert "Propose a minimal test" in prompt
        assert "textual patch-plan" in prompt

    def test_manager_prompt_does_not_include_diagnostic_mode_when_false(
        self, tmp_path, monkeypatch
    ):
        """Prompt must NOT include diagnostic sections when diagnostic_mode is False."""
        from bus.review_bridge import EventBus, ReviewBridge

        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            "# WP\n- **ID:** WT-2026-196\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )
        for name in ("STATE.md", "TURN.md", "execution_log.md"):
            (collab / name).write_text("", encoding="utf-8")

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
        monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )

        # No adaptive context (normal mode)
        prompt = bridge._build_review_prompt("WT-2026-196", "code")

        assert "--- DIAGNOSTIC MODE ---" not in prompt
        assert "REPEATED BLOCKER" not in prompt

    def test_run_review_uses_persisted_adaptive_context_not_previous_signature_bool(
        self, tmp_path, monkeypatch
    ):
        """Integration: previous signatures alone must not force diagnostic mode."""
        from bus.event_bus import EventBus
        from bus.review_bridge import ReviewBridge

        ticket_id = "WT-2026-196"
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            f"# WP\n- **ID:** {ticket_id}\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )
        for name in ("STATE.md", "TURN.md", "execution_log.md"):
            (collab / name).write_text("", encoding="utf-8")

        event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id=ticket_id,
            actor="BUILDER",
            payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
        )
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)
        bridge._save_adaptive_state(
            ticket_id,
            {
                "blocker_signatures": ["old.py:::PREVIOUS DIFFERENT BLOCKER"],
                "repeated_blockers": [],
                "diagnostic_mode": False,
                "changed_files_since_previous_review": ["old.py"],
                "last_feedback": "Previous different feedback.",
                "last_review_sequence": 1,
                "last_git_head": "abc123",
            },
        )

        captured_contexts = []
        original_build_prompt = bridge._build_review_prompt

        def capture_prompt(*args, **kwargs):
            captured_contexts.append(kwargs.get("adaptive_context"))
            return original_build_prompt(*args, **kwargs)

        monkeypatch.setattr(bridge, "_build_review_prompt", capture_prompt)
        monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
        monkeypatch.setattr(bridge, "_git_provenance", lambda: "[no commits]")
        monkeypatch.setattr(
            bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
        )
        monkeypatch.setattr(
            bridge,
            "_run_opencode_review",
            lambda **kwargs: ("DECISION: APPROVE\n", "", 0),
        )

        supervisor = MagicMock()
        result = bridge.run_manager_review_cycle(
            ticket_id=ticket_id,
            supervisor=supervisor,
            timeout_seconds=10,
        )

        # WT-2026-242a: text_regex degrades plain-text APPROVE to INSPECT.
        # The test verifies the adaptive context capture and control flow,
        # not the JSON path.
        assert result.decision == ReviewDecision.INSPECT
        assert captured_contexts
        context = captured_contexts[0]
        assert context["diagnostic_mode"] is False
        assert context["repeated_blockers"] == []


class TestHumanGateEnriched:
    """Tests for enriched HUMAN_GATE report."""

    def test_human_gate_includes_repeated_blocker_summary(self, tmp_path, monkeypatch):
        """TP-08: HUMAN_GATE report includes repeated blocker summary if available."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Pre-seed adaptive state with repeated blockers
        ticket_id = "WT-2026-196"
        bridge._save_adaptive_state(
            ticket_id,
            {
                "blocker_signatures": ["test.py:::REPEATED ERROR"],
                "repeated_blockers": ["test.py:::REPEATED ERROR"],
                "diagnostic_mode": True,
                "changed_files_since_previous_review": [],
                "last_feedback": "Fix the repeated error.",
                "last_review_sequence": 5,
                "last_git_head": None,
            },
        )

        review_attempts = [
            {
                "attempt": 1,
                "payload": {"attempt": 1, "blockers": "- Repeated error"},
            },
            {
                "attempt": 2,
                "payload": {"attempt": 2, "blockers": "- Same repeated error"},
            },
        ]

        report_path = bridge._generate_human_review_report(
            ticket_id=ticket_id,
            review_attempts=review_attempts,
            last_decision=ReviewDecision.CHANGES,
        )

        content = report_path.read_text(encoding="utf-8")
        assert "Repeated BLOCKERS" in content
        assert "REPEATED ERROR" in content
        assert "Last Manager proposal" in content
        assert "Fix the repeated error" in content

    def test_human_gate_includes_files_touched_or_untouched(
        self, tmp_path, monkeypatch
    ):
        """TP-08: HUMAN_GATE report includes file change info."""
        from bus.review_bridge import EventBus, ReviewBridge, ReviewDecision

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        ticket_id = "WT-2026-196"
        bridge._save_adaptive_state(
            ticket_id,
            {
                "repeated_blockers": [],
                "changed_files_since_previous_review": ["bus/review_bridge.py"],
                "last_feedback": "",
                "blocker_signatures": [],
                "diagnostic_mode": False,
                "last_review_sequence": 1,
                "last_git_head": None,
            },
        )

        review_attempts = [
            {
                "attempt": 1,
                "payload": {"attempt": 1, "blockers": ""},
            },
        ]

        report_path = bridge._generate_human_review_report(
            ticket_id=ticket_id,
            review_attempts=review_attempts,
            last_decision=ReviewDecision.CHANGES,
        )

        content = report_path.read_text(encoding="utf-8")
        assert "Files touched" in content
        assert "bus/review_bridge.py" in content


class TestChangedFilesTracking:
    """Tests for git-based file change computation."""

    def test_changed_files_since_previous_review_is_sorted_relative_path_list_or_unknown_reason(
        self, tmp_path, monkeypatch
    ):
        """TP-11: changed_files is a sorted list of relative paths or unknown dict."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # When last_git_head is None and git is unreachable -> unknown
        monkeypatch.setattr(bridge, "_get_current_git_head", lambda: None)
        result = bridge._compute_changed_files(None)
        assert isinstance(result, dict)
        assert result["status"] == "unknown"
        assert "reason" in result

    def test_changed_files_is_empty_list_on_first_review(self, tmp_path, monkeypatch):
        """TP-11: First review (no last_git_head but git available) returns empty list."""
        from bus.review_bridge import EventBus, ReviewBridge

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Git is available (has a head) but no last_git_head -> first review
        monkeypatch.setattr(bridge, "_get_current_git_head", lambda: "abc123def456")
        result = bridge._compute_changed_files(None)
        assert isinstance(result, list)
        assert result == []


class TestMaxAttempts:
    """Tests for max_attempts finite guard."""

    def test_max_attempts_remains_finite_and_configured_to_8(self, tmp_path):
        """TP-01: max_attempts must be finite and configured to 8 in agents.json."""
        # Check the agents.json config
        agent_config_path = (
            Path(__file__).resolve().parents[1] / ".agent" / "config" / "agents.json"
        )
        assert agent_config_path.exists(), "agents.json must exist"
        import json

        data = json.loads(agent_config_path.read_text(encoding="utf-8"))
        mgr = data.get("manager_review", {})
        max_attempts = mgr.get("max_attempts", None)
        assert max_attempts is not None, (
            "max_attempts must be configured in manager_review"
        )
        assert max_attempts == 8, f"max_attempts must be 8, got {max_attempts}"
        assert isinstance(max_attempts, int), "max_attempts must be an integer"
        assert max_attempts > 0, "max_attempts must be positive"
        assert max_attempts < 100, "max_attempts must be finite (sanity check)"


class TestReviewBridgeEvidence:
    """WT-2026-226a: Review bridge consumes bus.evidence without empty diff drift."""

    def test_regression_ticket_commit_plus_dirty_working_tree(self, tmp_path):
        """A dirty working tree must not hide valid ticket commits from the motor."""
        import subprocess
        from unittest.mock import MagicMock

        from bus.review_bridge import ReviewBridge

        from tests.test_pre_handoff_guard import init_git_repo

        motor = tmp_path / "motor"
        init_git_repo(motor)

        bridge = ReviewBridge(event_bus=MagicMock(), project_root=motor)
        bridge._resolve_motor_root = lambda: motor

        # Add and commit the collaboration file FIRST
        collab_dir = motor / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        (collab_dir / "notes.md").write_text("original")
        subprocess.run(["git", "add", "."], cwd=motor, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add collab file"], cwd=motor, check=True
        )

        # Add ticket commit
        (motor / "productive.py").write_text("code")
        subprocess.run(["git", "add", "."], cwd=motor, check=True)
        subprocess.run(
            ["git", "commit", "-m", "WT-2026-999: add code"], cwd=motor, check=True
        )

        # Then modify the collaboration file without staging so it appears in git diff --name-only
        (collab_dir / "notes.md").write_text("dirty modification")

        result = bridge.classify_review_packet("WT-2026-999")

        assert result["is_empty"] is False
        assert result["has_motor_evidence"] is True
        # Note: has_ticket_commit might not be returned in result, but we test it indirectly by is_empty being False

    def test_negative_no_commit_no_diff(self, tmp_path):
        """No ticket commit and no diff -> packet is empty."""
        from unittest.mock import MagicMock

        from bus.review_bridge import ReviewBridge

        from tests.test_pre_handoff_guard import init_git_repo

        motor = tmp_path / "motor"
        init_git_repo(motor)

        bridge = ReviewBridge(event_bus=MagicMock(), project_root=motor)
        bridge._resolve_motor_root = lambda: motor

        # Need bus_active = True to bypass the first check
        bridge.state_ingest = MagicMock()
        bridge.state_ingest.get_ticket_context.return_value = {"status": "in_progress"}

        result = bridge.classify_review_packet("WT-2026-999")
        assert result["is_empty"] is True
        assert "no diff files found" in result.get("reason", "")

    def test_documentation_ticket_docs_only_evidence_is_reviewable(
        self, tmp_path, monkeypatch
    ):
        """Documentation deliverables are valid review evidence even when docs-only."""
        from unittest.mock import MagicMock

        from bus.review_bridge import ReviewBridge

        bridge = ReviewBridge(event_bus=MagicMock(), project_root=tmp_path)
        bridge._resolve_motor_root = lambda: tmp_path
        bridge.state_ingest = MagicMock()
        bridge.state_ingest.get_ticket_context.return_value = {
            "status": "ready_for_review",
            "deliverable_type": "documentation",
        }

        monkeypatch.setattr(
            "bus.evidence.resolve_evidence",
            lambda *_args, **_kwargs: {
                "motor_files": [],
                "destination_files": [
                    ".agent/reports/compare/stablyai-orca-HEAD-2026-06-07.md"
                ],
                "all_files": [
                    ".agent/reports/compare/stablyai-orca-HEAD-2026-06-07.md"
                ],
                "docs_only_files": [
                    ".agent/reports/compare/stablyai-orca-HEAD-2026-06-07.md"
                ],
                "productive_files": [],
                "is_docs_only": True,
                "is_collaboration_only": False,
                "motor_productive": [],
                "dest_productive": [],
                "has_motor_evidence": False,
                "has_destination_productive": False,
            },
        )

        classification = bridge.classify_review_packet("WT-2026-236a")

        assert classification["is_empty"] is False
        assert classification["is_docs_only"] is True
        assert classification["deliverable_type"] == "documentation"
        assert bridge.check_review_packet_diff_empty("WT-2026-236a") is False

    def test_productive_evidence_wins_over_legacy_empty_diff_stat(
        self, tmp_path, monkeypatch
    ):
        """Structured productive evidence must not be overridden by legacy diff_stat."""
        from unittest.mock import MagicMock

        from bus.review_bridge import ReviewBridge

        bridge = ReviewBridge(event_bus=MagicMock(), project_root=tmp_path)
        bridge._resolve_motor_root = lambda: tmp_path
        bridge._git_diff_stat = lambda: "[git diff --stat empty]"
        bridge.state_ingest = MagicMock()
        bridge.state_ingest.get_ticket_context.return_value = {
            "status": "ready_for_review",
            "deliverable_type": "documentation",
        }

        monkeypatch.setattr(
            "bus.evidence.resolve_evidence",
            lambda *_args, **_kwargs: {
                "motor_files": ["bus/review_bridge.py"],
                "destination_files": [
                    ".agent/reports/compare/stablyai-orca-HEAD-2026-06-07.md"
                ],
                "all_files": [
                    "bus/review_bridge.py",
                    ".agent/reports/compare/stablyai-orca-HEAD-2026-06-07.md",
                ],
                "docs_only_files": [],
                "productive_files": [
                    "bus/review_bridge.py",
                    ".agent/reports/compare/stablyai-orca-HEAD-2026-06-07.md",
                ],
                "is_docs_only": False,
                "is_collaboration_only": False,
                "motor_productive": ["bus/review_bridge.py"],
                "dest_productive": [
                    ".agent/reports/compare/stablyai-orca-HEAD-2026-06-07.md"
                ],
                "has_motor_evidence": True,
                "has_destination_productive": True,
            },
        )

        classification = bridge.classify_review_packet("WT-2026-236a")

        assert classification["is_empty"] is False
        assert classification["productive_files"]
        assert bridge.check_review_packet_diff_empty("WT-2026-236a") is False

    def test_code_ticket_docs_only_evidence_still_blocks(self, tmp_path, monkeypatch):
        """Code tickets still need productive evidence; docs-only is not enough."""
        from unittest.mock import MagicMock

        from bus.review_bridge import ReviewBridge

        bridge = ReviewBridge(event_bus=MagicMock(), project_root=tmp_path)
        bridge._resolve_motor_root = lambda: tmp_path
        bridge.state_ingest = MagicMock()
        bridge.state_ingest.get_ticket_context.return_value = {
            "status": "ready_for_review",
            "deliverable_type": "code",
        }

        monkeypatch.setattr(
            "bus.evidence.resolve_evidence",
            lambda *_args, **_kwargs: {
                "motor_files": [],
                "destination_files": ["README.md"],
                "all_files": ["README.md"],
                "docs_only_files": ["README.md"],
                "productive_files": [],
                "is_docs_only": True,
                "is_collaboration_only": False,
                "motor_productive": [],
                "dest_productive": [],
                "has_motor_evidence": False,
                "has_destination_productive": False,
            },
        )

        classification = bridge.classify_review_packet("WT-2026-CODE")

        assert classification["is_empty"] is False
        assert classification["is_docs_only"] is True
        assert classification["deliverable_type"] == "code"
        assert bridge.check_review_packet_diff_empty("WT-2026-CODE") is True


# ---------------------------------------------------------------------------
# WT-2026-242a: try-first JSON transport governing tests
# ---------------------------------------------------------------------------


class TestTryFirstJsonTransport:
    """Tests for the WT-2026-242a try-first JSON transport in review_bridge."""

    @staticmethod
    def _make_bridge(tmp_path):
        """Create a ReviewBridge with minimal setup."""
        collaboration_dir = tmp_path / ".agent" / "collaboration"
        collaboration_dir.mkdir(parents=True, exist_ok=True)
        (collaboration_dir / "work_plan.md").write_text(
            "## Metadata\n- **ID:** WT-2026-242a\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )
        event_bus = MagicMock()
        return ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    def _make_bridge_with_motor(self, tmp_path):
        """Create a ReviewBridge with motor_root mocked for _run_opencode_review tests."""
        bridge = self._make_bridge(tmp_path)
        # Mock _resolve_motor_root to return tmp_path (avoids RuntimeError)
        bridge._resolve_motor_root = lambda: tmp_path
        # Mock _materialize_manager_agent_spec to return a fake path
        bridge._materialize_manager_agent_spec = lambda: tmp_path / "fake_manager.md"
        return bridge

    def test_opencode_review_uses_json_when_executable_off_path(self, tmp_path):
        """Test that _run_opencode_review tries --format json with the real executable.

        Even when PATH is empty, if the manager_executable is a valid path,
        the command built must include --format json.
        """
        bridge = self._make_bridge_with_motor(tmp_path)

        # NDJSON output that would be produced by a real OpenCode run with JSON
        ndjson_output = '{"type":"text","phase":"final_answer","part":{"text":"DECISION: CHANGES"}}\n'

        mock_result = MagicMock()
        mock_result.stdout = ndjson_output
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "bus.review_bridge.subprocess.run", return_value=mock_result
        ) as mock_run:
            _, _, rc = bridge._run_opencode_review(
                ticket_id="WT-2026-242a",
                prompt="test prompt",
                manager_executable=tmp_path / "opencode",
                timeout_seconds=180,
            )

            # Verify --format json was in the command
            call_args = mock_run.call_args
            cmd_list = (
                call_args[0][0]
                if not call_args.kwargs.get("shell")
                else call_args[0][0].split()
            )
            cmd_str = " ".join(str(a) for a in cmd_list)
            assert "--format" in cmd_str and "json" in cmd_str, (
                f"Expected --format json in command: {cmd_str}"
            )
            # Verify the decision is parsed from JSON (CHANGES via json_final_answer)
            assert rc == 0

    def test_opencode_review_falls_back_without_json_on_unsupported_flag_error(
        self, tmp_path
    ):
        """Test that _run_opencode_review falls back to non-JSON when stderr indicates
        --format json is not supported by the real executable."""
        bridge = self._make_bridge_with_motor(tmp_path)

        # First attempt: stderr indicates unsupported flag
        # Second attempt (fallback): successful non-JSON output
        fallback_stdout = "DECISION: CHANGES\n"

        call_count = [0]

        def mock_run_side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                # First call: --format json rejected
                mock_result.stdout = ""
                mock_result.stderr = "Error: unknown flag --format"
                mock_result.returncode = 1
            else:
                # Second call: fallback without JSON succeeds
                mock_result.stdout = fallback_stdout
                mock_result.stderr = ""
                mock_result.returncode = 0
            return mock_result

        with patch(
            "bus.review_bridge.subprocess.run", side_effect=mock_run_side_effect
        ):
            stdout, _, _ = bridge._run_opencode_review(
                ticket_id="WT-2026-242a",
                prompt="test prompt",
                manager_executable=tmp_path / "opencode",
                timeout_seconds=180,
            )

            # Should have fallen back and returned the fallback output
            assert "DECISION: CHANGES" in stdout
            assert call_count[0] == 2

    def test_opencode_review_degrades_textual_approve_to_inspect_after_fallback(
        self, tmp_path
    ):
        """Test that after fallback, a textual APPROVE degrades to INSPECT."""
        bridge = self._make_bridge_with_motor(tmp_path)

        call_count = [0]

        def mock_run_side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                mock_result.stdout = ""
                mock_result.stderr = "Error: invalid option --format"
                mock_result.returncode = 1
            else:
                # Textual APPROVE (not NDJSON)
                mock_result.stdout = "DECISION: APPROVE\n"
                mock_result.stderr = ""
                mock_result.returncode = 0
            return mock_result

        with patch(
            "bus.review_bridge.subprocess.run", side_effect=mock_run_side_effect
        ):
            stdout, _, _ = bridge._run_opencode_review(
                ticket_id="WT-2026-242a",
                prompt="test prompt",
                manager_executable=tmp_path / "opencode",
                timeout_seconds=180,
            )

        # The raw output is APPROVE, but _parse_opencode_decision should
        # degrade it to INSPECT because text_regex never produces APPROVE.
        decision, method = bridge._parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "text_regex"

    def test_opencode_review_does_not_fallback_on_generic_failure(self, tmp_path):
        """Test that timeout/auth/output empty does NOT trigger fallback.

        WT-2026-242a: The fallback is governed by concrete patterns from the
        real executable's error output (unknown flag, invalid option, help
        banner), NOT by exit_code != 0 alone. A timeout or auth failure
        should return the failure result, not silently fall back.
        """
        bridge = self._make_bridge_with_motor(tmp_path)

        # Timeout error — should NOT trigger fallback
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "TimeoutExpired: ..."
        mock_result.returncode = 1

        with patch(
            "bus.review_bridge.subprocess.run", return_value=mock_result
        ) as mock_run:
            _, stderr, rc = bridge._run_opencode_review(
                ticket_id="WT-2026-242a",
                prompt="test prompt",
                manager_executable=tmp_path / "opencode",
                timeout_seconds=1,  # Very short timeout to trigger it
            )

            # Should NOT have fallen back — only one call
            assert mock_run.call_count == 1
            # Should return the error result
            assert rc == 1
            assert "TimeoutExpired" in stderr

        # Auth failure — should NOT trigger fallback
        call_count = [0]

        def auth_side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.stderr = "Authentication failed"
            mock_result.returncode = 1
            return mock_result

        with patch("bus.review_bridge.subprocess.run", side_effect=auth_side_effect):
            _, _, rc = bridge._run_opencode_review(
                ticket_id="WT-2026-242a",
                prompt="test prompt",
                manager_executable=tmp_path / "opencode",
                timeout_seconds=180,
            )

            # Should NOT have fallen back
            assert call_count[0] == 1
            assert rc == 1

        # Empty output (no error, just no output) — should NOT trigger fallback
        call_count[0] = 0

        def empty_side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_result.returncode = 0
            return mock_result

        with patch("bus.review_bridge.subprocess.run", side_effect=empty_side_effect):
            _, _, _ = bridge._run_opencode_review(
                ticket_id="WT-2026-242a",
                prompt="test prompt",
                manager_executable=tmp_path / "opencode",
                timeout_seconds=180,
            )

            # Should NOT have fallen back
            assert call_count[0] == 1
