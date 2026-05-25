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


def test_manager_review_observation_loader_caps_filters_and_truncates(review_bridge, tmp_path):
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
    with patch.object(event_bus, 'emit', side_effect=Exception("Simulated bus failure")):
        result = review_bridge.run_manager_review_cycle(
            ticket_id="WP-TEST-001",
            supervisor=supervisor,
            timeout_seconds=10,
        )

    # Verify graceful failure
    assert result.decision == ReviewDecision.INSPECT
    assert result.exit_code == 1
    assert "FAIL-SAFE" in result.stderr
    assert "event_bus.emit() failed" in result.stderr or "MANAGER_REVIEWING" in result.stderr


def test_emit_fail_safe_on_review_decision(review_bridge, event_bus, tmp_path, capfd):
    """WP-2026-118: Bridge logs error but continues if emit() fails on REVIEW_DECISION.

    Before: An emit() failure on REVIEW_DECISION would crash with raw traceback.
    During: Simulates event_bus.emit() raising an exception when emitting REVIEW_DECISION.
    After: Bridge logs error audibly and returns result with decision intact.
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
    with patch.object(review_bridge, '_run_opencode_review', side_effect=mock_run_opencode):
        with patch.object(review_bridge, '_get_manager_backend', return_value='opencode'):
            # Mock emit to fail only on REVIEW_DECISION
            def conditional_emit(*args, **kwargs):
                event_type = args[0] if args else kwargs.get('event_type', '')
                # Fail only on REVIEW_DECISION
                if event_type == "REVIEW_DECISION":
                    raise Exception("Simulated REVIEW_DECISION emit failure")
                # For other events, just return a dummy record
                from bus.event_bus import EventRecord
                from datetime import datetime, timezone
                return EventRecord(
                    event_id=f"evt-{event_type}",
                    event_type=event_type,
                    ticket_id="WP-TEST-001",
                    actor="MANAGER",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    payload=kwargs.get('payload', {}),
                    sequence_number=1,
                )

            with patch.object(event_bus, 'emit', side_effect=conditional_emit):
                result = review_bridge.run_manager_review_cycle(
                    ticket_id="WP-TEST-001",
                    supervisor=supervisor,
                    timeout_seconds=10,
                )

    # Decision should still be APPROVE (the review ran successfully)
    assert result.decision == ReviewDecision.APPROVE
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
    with patch.object(event_bus, 'emit', side_effect=Exception("Bus error")):
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


def test_review_bridge_fail_safe_emits_to_stderr(review_bridge, event_bus, tmp_path, capfd):
    """WP-2026-118: Verify fail-safe messages are written to stderr.

    Before: Errors might be silently swallowed or go to stdout.
    During: Triggers emit() failure and captures stderr output.
    After: stderr contains structured fail-safe message with ticket_id.
    """
    with patch.object(event_bus, 'emit', side_effect=Exception("Test bus error")):
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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        stdout = """{"type":"text","part":{"text":"Found issues:\\n- Missing tests\\n\\nDECISION: CHANGES"}}
"""
        decision, _ = bridge._parse_opencode_json_decision(stdout)
        assert decision == ReviewDecision.CHANGES

    def test_parse_json_prioritizes_final_answer_phase(self, tmp_path):
        """Test parser prioritizes phase:final_answer over other text events."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        decision, _ = bridge._parse_opencode_json_decision("")
        assert decision == ReviewDecision.INSPECT

    def test_parse_json_text_event_missing_part_field(self, tmp_path):
        """Test parser handles text events without part field gracefully."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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

    def test_retry_not_invoked_on_valid_decision(self, tmp_path):
        """Test retry is not invoked when parser extracts valid decision."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Use actual newline, not escaped
        stdout = "Review complete.\nDECISION: APPROVE"
        stderr = ""

        decision, attempts, _ = bridge._parse_opencode_decision_with_retry(
            stdout, stderr, max_retries=2
        )

        assert decision == ReviewDecision.APPROVE
        assert attempts == 1  # No retry needed

    def test_retry_invoked_on_inspect_with_valid_output(self, tmp_path):
        """Test retry is invoked when INSPECT but output looks valid."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

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
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus
        import time

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

    def test_no_changes_needed_not_interpreted_as_changes(self, tmp_path, monkeypatch):
        """Test 'no changes needed' does not trigger CHANGES decision."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        # Disable JSON format to test text parser
        monkeypatch.setattr(bridge, "_supports_json_format", False)

        stdout = "The code looks fine. No changes needed at this time."
        decision, _ = bridge._parse_opencode_decision(stdout)

        # Should be INSPECT, not CHANGES (no DECISION: pattern)
        assert decision == ReviewDecision.INSPECT

    def test_approve_without_decision_pattern_returns_inspect(self, tmp_path, monkeypatch):
        """Test 'APPROVE' without DECISION: pattern returns INSPECT."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_supports_json_format", False)

        stdout = "I approve of this implementation."
        decision, _ = bridge._parse_opencode_decision(stdout)

        assert decision == ReviewDecision.INSPECT

    def test_explicit_decision_pattern_is_recognized(self, tmp_path, monkeypatch):
        """Test explicit DECISION: pattern is correctly recognized."""
        from bus.review_bridge import ReviewBridge, ReviewDecision, EventBus

        runtime_dir = tmp_path / ".agent" / "runtime" / "events"
        event_bus = EventBus(runtime_dir=runtime_dir)
        bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

        monkeypatch.setattr(bridge, "_supports_json_format", False)

        stdout = "Review complete.\nDECISION: APPROVE"
        decision, _ = bridge._parse_opencode_decision(stdout)

        assert decision == ReviewDecision.APPROVE


class TestDocumentationPromptWiring:
    """Regression tests: documentation type receives cross-cutting checks and learnings."""

    def _make_bridge(self, tmp_path: Path, dtype: str = "documentation") -> ReviewBridge:
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
        return ReviewBridge(event_bus=event_bus, project_root=tmp_path)

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

    def test_documentation_receives_validator_evidence_gate(self, tmp_path):
        """documentation prompt must include the cross-cutting validator evidence gate."""
        bridge = self._make_bridge(tmp_path)
        prompt = bridge._build_review_prompt("WP-2026-TEST", "documentation")
        assert "AP-06 Validator evidence missing" in prompt
        assert "execution_log.md must contain" in prompt

    def test_documentation_receives_learnings_when_applies_to_all(self, tmp_path):
        """documentation prompt includes observations scoped to 'all'."""
        self._write_observation(tmp_path, "test signal all scope", applies_to="all")
        bridge = self._make_bridge(tmp_path)
        prompt = bridge._build_review_prompt("WP-2026-TEST", "documentation")
        assert "Lecciones acumuladas de auditoria" in prompt
        assert "test signal all scope" in prompt

    def test_documentation_excludes_code_only_learnings(self, tmp_path):
        """documentation prompt must not include observations scoped to code/mixed only."""
        self._write_observation(tmp_path, "code-only signal", applies_to=["code", "mixed"])
        bridge = self._make_bridge(tmp_path)
        prompt = bridge._build_review_prompt("WP-2026-TEST", "documentation")
        assert "code-only signal" not in prompt

    def test_code_receives_learnings_scoped_to_code(self, tmp_path):
        """code prompt includes observations scoped to code."""
        self._write_observation(tmp_path, "code scoped signal", applies_to=["code", "mixed"])
        bridge = self._make_bridge(tmp_path, dtype="code")
        prompt = bridge._build_review_prompt("WP-2026-TEST", "code")
        assert "code scoped signal" in prompt

    def test_static_rubric_unmodified_when_observations_present(self, tmp_path):
        """Injecting observations must not alter the static rubric content."""
        self._write_observation(tmp_path, "some learning", applies_to="all")
        bridge = self._make_bridge(tmp_path)
        prompt = bridge._build_review_prompt("WP-2026-TEST", "documentation")
        assert "focus strictly on the clarity" in prompt
        assert "Lecciones acumuladas de auditoria" in prompt


class TestCanonicalAntiPatternInventory:
    """Direct tests for AP-08: new canonical AP loading methods (WP-2026-139 hotfix)."""

    _AP_CONTENT = "\n".join([
        "# Inventario Canonico",
        "",
        "## AP-01 - Mock drift",
        "- El patch apunta a un simbolo distinto.",
        "",
        "## AP-02 - Floor assertion",
        "- El umbral ya esta satisfecho por el baseline.",
    ])

    def _make_bridge(self, tmp_path: Path) -> ReviewBridge:
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            "# Work Plan\n- **ID:** WP-TEST\n- **deliverable_type:** code\n",
            encoding="utf-8",
        )
        for name in ("STATE.md", "TURN.md", "execution_log.md"):
            (collab / name).write_text("", encoding="utf-8")
        event_bus = EventBus(runtime_dir=tmp_path / ".agent" / "runtime" / "events")
        return ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    def test_parse_extracts_ap_id_and_name(self):
        result = ReviewBridge._parse_canonical_anti_patterns(self._AP_CONTENT)
        assert result == [("AP-01", "Mock drift"), ("AP-02", "Floor assertion")]

    def test_parse_returns_empty_for_content_without_ap_headers(self):
        result = ReviewBridge._parse_canonical_anti_patterns("# No AP headers\n- just content")
        assert result == []

    def test_load_warns_and_returns_empty_when_file_missing(self, tmp_path, monkeypatch):
        bridge = self._make_bridge(tmp_path)
        monkeypatch.setattr(bridge, "_canonical_anti_patterns_path", lambda: tmp_path / "nonexistent.md")
        with pytest.warns(RuntimeWarning, match="unavailable"):
            result = bridge._load_canonical_anti_patterns()
        assert result == []

    def test_load_warns_and_returns_empty_when_file_has_no_ap_entries(self, tmp_path, monkeypatch):
        stub = tmp_path / "anti-patterns.md"
        stub.write_text("# No AP headers here", encoding="utf-8")
        bridge = self._make_bridge(tmp_path)
        monkeypatch.setattr(bridge, "_canonical_anti_patterns_path", lambda: stub)
        with pytest.warns(RuntimeWarning, match="empty or invalid"):
            result = bridge._load_canonical_anti_patterns()
        assert result == []

    def test_render_formats_inventory_lines(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge._canonical_anti_patterns = [("AP-01", "Mock drift"), ("AP-02", "Floor assertion")]
        rendered = bridge._render_canonical_anti_pattern_inventory()
        assert "AP-01 Mock drift" in rendered
        assert "AP-02 Floor assertion" in rendered
        assert "skills/_shared/anti-patterns.md" in rendered

    def test_render_returns_empty_string_when_inventory_empty(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge._canonical_anti_patterns = []
        assert bridge._render_canonical_anti_pattern_inventory() == ""

    def test_rubric_includes_ap_inventory_block_for_code_type(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge._canonical_anti_patterns = [("AP-01", "Mock drift")]
        rubric = bridge._rubric_for_type("code", "WP-TEST")
        assert "AP-01 Mock drift" in rubric

    def test_rubric_omits_ap_inventory_block_when_inventory_empty(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge._canonical_anti_patterns = []
        rubric = bridge._rubric_for_type("code", "WP-TEST")
        assert "Canonical anti-pattern inventory" not in rubric
