from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge, ReviewDecision


def _make_bridge(tmp_path):
    runtime = tmp_path / ".agent" / "runtime" / "events"
    bus = EventBus(runtime_dir=runtime)
    bridge = ReviewBridge(event_bus=bus, project_root=tmp_path)
    return bridge, bus


@pytest.fixture(autouse=True)
def _mock_repomix_for_tests(monkeypatch):
    """WT-2026-182: Evitar warnings y ralentización en CI por npx repomix."""
    monkeypatch.setattr(
        "bus.review_bridge.ReviewBridge._ensure_repomix_context",
        lambda self: (None, {"status": "skipped", "reason": "mocked for tests"}),
    )


def _write_canonical(tmp_path, name, content):
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / name).write_text(content, encoding="utf-8")


def _stub_productive_evidence(monkeypatch, bridge):
    """WOT-AUDIT-C1: simulate a real code ticket with productive changes so the
    WT-2026-221b evidence gate lets the review proceed.

    These tests exercise the retry/timeout/forensic/persistence paths, which only
    run once the review packet passes the evidence gate. Without a productive diff
    the gate (correctly) short-circuits to CHANGES before any review happens. We do
    NOT relax the gate here: we feed it a realistic productive classification, the
    same shape `classify_review_packet` returns for a genuine code ticket.
    """
    monkeypatch.setattr(
        bridge,
        "classify_review_packet",
        lambda tid: {
            "bus_active": True,
            "is_empty": False,
            "is_docs_only": False,
            "is_collaboration_only": False,
            "productive_files": ["bus/review_bridge.py"],
            "has_motor_evidence": True,
            "has_destination_productive": False,
            "deliverable_type": "code",
            "reason": "productive evidence (test stub)",
            "motor_diff_files": ["bus/review_bridge.py"],
            "destination_diff_files": [],
            "docs_only_files": [],
        },
    )


def test_single_shot_prompt_includes_canonical(tmp_path, monkeypatch):
    _write_canonical(tmp_path, "work_plan.md", "# WP-X\n- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "STATE_CONTENT")
    _write_canonical(tmp_path, "TURN.md", "TURN_CONTENT")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\nlog body\n")
    bridge, _ = _make_bridge(tmp_path)
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: "diff_content"
    )

    prompt = bridge._build_review_prompt("WP-X", "code")
    assert "STATE_CONTENT" in prompt
    assert "TURN_CONTENT" in prompt
    assert "log body" in prompt
    assert "diff_content" in prompt
    assert "DECISION: APPROVE" in prompt


def test_prompt_truncates_diff_when_canonical_exceeds_60kb(tmp_path, monkeypatch):
    big_content = "x" * (61 * 1024)
    _write_canonical(tmp_path, "work_plan.md", big_content)
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\nlog\n")
    bridge, _ = _make_bridge(tmp_path)
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "diff_stat")

    prompt = bridge._build_review_prompt("WP-X", "code")
    assert "diff omitido por budget" in prompt
    assert "diff_stat" in prompt


def test_extract_ticket_section_isolates_active(tmp_path):
    _write_canonical(
        tmp_path,
        "execution_log.md",
        "### WP-A\nA body\n\n### WP-B\nB body\n\n### WP-C\nC body\n",
    )
    bridge, _ = _make_bridge(tmp_path)
    section = bridge._extract_ticket_section("WP-B")
    assert "B body" in section
    assert "A body" not in section
    assert "C body" not in section


def test_retry_succeeds_on_second_attempt(tmp_path, monkeypatch):
    """Subprocess timeout retries the review cycle (INSPECT+fallback_inspect triggers continue)."""
    _write_canonical(tmp_path, "work_plan.md", "- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\n")
    bridge, _ = _make_bridge(tmp_path)
    _stub_productive_evidence(monkeypatch, bridge)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda tid: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
    monkeypatch.setattr(bridge, "_supports_json_format", True)

    import json as _json

    call_count = {"n": 0}

    def fake_run(**kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Timeout: triggers INSPECT+fallback_inspect → outer loop continues
            return ("", "TimeoutExpired: timed out", 1)
        return (
            _json.dumps(
                {
                    "type": "text",
                    "phase": "final_answer",
                    "part": {"type": "text", "text": "DECISION: APPROVE"},
                }
            ),
            "",
            0,
        )

    monkeypatch.setattr(bridge, "_run_opencode_review", fake_run)

    class DummySupervisor:
        def transition_ticket(self, *args, **kwargs):
            pass

        def _is_supervisor_lock_stale(self):
            return False

        def requeue_ticket(self, ticket_id):
            return True

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-X", supervisor=DummySupervisor()
    )
    assert result.decision == ReviewDecision.APPROVE
    assert call_count["n"] == 2


def test_retry_exhausted_timeout_becomes_transport_failed(tmp_path, monkeypatch):
    _write_canonical(tmp_path, "work_plan.md", "- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\n")
    bridge, _ = _make_bridge(tmp_path)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda tid: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
    _stub_productive_evidence(monkeypatch, bridge)

    monkeypatch.setattr(
        bridge,
        "_run_opencode_review",
        lambda **kw: ("", "TimeoutExpired: timed out", 1),
    )

    class DummySupervisor:
        def transition_ticket(self, *args, **kwargs):
            pass

        def _is_supervisor_lock_stale(self):
            return False

        def requeue_ticket(self, ticket_id):
            return True

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-X", supervisor=DummySupervisor()
    )
    # WP-2026-144 hotfix: timeout-exhausted retries must not reach the bus as
    # inspect (→ HUMAN_GATE). They are reclassified as transport_failed.
    assert result.decision == ReviewDecision.TRANSPORT_FAILED
    assert result.transport_ok is False


def test_decision_changes_does_not_retry_for_timeout(tmp_path, monkeypatch):
    """WP-2026-106 B3: CHANGES ends the cycle immediately, no inner retry.

    A CHANGES decision performs exactly one review per cycle. Escalation to
    HUMAN_GATE happens across cycles (counted from the bus), not by an inner
    loop re-reviewing unchanged code.
    """
    _write_canonical(tmp_path, "work_plan.md", "- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\n")
    bridge, _ = _make_bridge(tmp_path)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda tid: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
    monkeypatch.setattr(bridge, "_supports_json_format", True)
    monkeypatch.setattr(
        "bus.review_bridge.subprocess.run", lambda *a, **kw: MagicMock(returncode=0)
    )

    import json as _json

    call_count = {"n": 0}

    def fake_run(**kw):
        call_count["n"] += 1
        return (
            _json.dumps(
                {
                    "type": "text",
                    "phase": "final_answer",
                    "part": {
                        "type": "text",
                        "text": "## SUMMARY\nIssues\n## BLOCKERS\n- X\n## SUGGESTIONS\n- Y\nDECISION: CHANGES",
                    },
                }
            ),
            "",
            0,
        )

    monkeypatch.setattr(bridge, "_run_opencode_review", fake_run)

    transitions = []

    class DummySupervisor:
        def transition_ticket(self, ticket_id, new_state, reason):
            transitions.append((ticket_id, new_state, reason))

        def _is_supervisor_lock_stale(self):
            return False

        def requeue_ticket(self, ticket_id):
            return True

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-X", supervisor=DummySupervisor()
    )
    assert result.decision == ReviewDecision.CHANGES
    # WP-2026-106 B3: exactly one review per cycle, no inner retry on CHANGES.
    assert call_count["n"] == 1


def test_forensic_event_emitted_per_attempt(tmp_path, monkeypatch):
    _write_canonical(tmp_path, "work_plan.md", "- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\n")
    bridge, bus = _make_bridge(tmp_path)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda tid: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
    _stub_productive_evidence(monkeypatch, bridge)

    monkeypatch.setattr(
        bridge, "_run_opencode_review", lambda **kw: ("DECISION: APPROVE\n", "", 0)
    )

    class DummySupervisor:
        def transition_ticket(self, *args, **kwargs):
            pass

        def _is_supervisor_lock_stale(self):
            return False

        def requeue_ticket(self, ticket_id):
            return True

    bridge.run_manager_review_cycle(ticket_id="WP-X", supervisor=DummySupervisor())
    events = bus.read_events(ticket_id="WP-X", event_type="MANAGER_REVIEW_ATTEMPT")
    assert len(events) == 1
    assert events[0].payload["attempt"] == 1
    assert events[0].payload["exit_code"] == 0


def test_parse_opencode_json_decision_approve(tmp_path):
    """WP-2026-120: parser consumes the real OpenCode NDJSON schema
    (type:"text" with part.text, phase:"final_answer")."""
    bridge, _ = _make_bridge(tmp_path)
    stdout = (
        '{"type": "text", "phase": "final_answer", '
        '"part": {"type": "text", '
        '"text": "The implementation is great. DECISION: APPROVE"}}\n'
    )
    decision, method = bridge._parse_opencode_json_decision(stdout)
    assert decision == ReviewDecision.APPROVE
    assert method == "json_final_answer"


def test_parse_opencode_json_decision_changes(tmp_path):
    """WP-2026-120: parser consumes the real OpenCode NDJSON schema."""
    bridge, _ = _make_bridge(tmp_path)
    stdout = (
        '{"type": "text", "phase": "final_answer", '
        '"part": {"type": "text", '
        '"text": "Please add tests. DECISION: CHANGES"}}\n'
    )
    decision, method = bridge._parse_opencode_json_decision(stdout)
    assert decision == ReviewDecision.CHANGES
    assert method == "json_final_answer"


# =============================================================================
# Tests WP-2026-106: Structured Reviews and Human Gate Escalation
# =============================================================================


def test_review_attempt_persistence_creates_file(tmp_path, monkeypatch):
    """Test review attempts are persisted to attempt-N.md."""

    _write_canonical(tmp_path, "work_plan.md", "- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\n")
    bridge, _ = _make_bridge(tmp_path)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda tid: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
    _stub_productive_evidence(monkeypatch, bridge)

    monkeypatch.setattr(
        bridge,
        "_run_opencode_review",
        lambda **kw: ("DECISION: APPROVE\n", "", 0),
    )

    class DummySupervisor:
        def transition_ticket(self, *args, **kwargs):
            pass

        def _is_supervisor_lock_stale(self):
            return False

        def requeue_ticket(self, ticket_id):
            return True

    bridge.run_manager_review_cycle(ticket_id="WP-X", supervisor=DummySupervisor())

    # Check attempt file was created
    review_dir = tmp_path / ".agent" / "runtime" / "reviews" / "WP-X"
    assert review_dir.exists()
    attempt_file = review_dir / "attempt-1.md"
    assert attempt_file.exists()
    content = attempt_file.read_text(encoding="utf-8")
    assert "Attempt 1" in content
    assert "DECISION: APPROVE" in content


def test_review_emits_lightweight_event_with_log_path(tmp_path, monkeypatch):
    """Test bus event contains review_log_path and stdout_tail, not full review."""

    _write_canonical(tmp_path, "work_plan.md", "- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\n")
    bridge, bus = _make_bridge(tmp_path)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda tid: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
    _stub_productive_evidence(monkeypatch, bridge)

    long_stdout = "x" * 2000 + "DECISION: APPROVE"

    monkeypatch.setattr(
        bridge,
        "_run_opencode_review",
        lambda **kw: (long_stdout, "", 0),
    )

    class DummySupervisor:
        def transition_ticket(self, *args, **kwargs):
            pass

        def _is_supervisor_lock_stale(self):
            return False

        def requeue_ticket(self, ticket_id):
            return True

    bridge.run_manager_review_cycle(ticket_id="WP-X", supervisor=DummySupervisor())

    events = bus.read_events(ticket_id="WP-X", event_type="MANAGER_REVIEW_ATTEMPT")
    assert len(events) == 1
    payload = events[0].payload

    # Should have review_log_path
    assert "review_log_path" in payload
    assert payload["review_log_path"] is not None

    # Should have stdout_tail (short), not full stdout
    assert "stdout_tail" in payload
    assert len(payload["stdout_tail"]) <= 500
    assert len(payload["stdout_tail"]) < len(long_stdout)


def test_human_gate_escalation_at_5_changes(tmp_path, monkeypatch):
    """WP-2026-106 B3: escalation derives from bus history, not a local counter.

    Each review cycle emits one REVIEW_DECISION. After the 5th consecutive
    CHANGES the bridge must generate human_review_report.md. The actual
    HUMAN_GATE state transition is owned by agent_controller --request-changes
    (single escalation authority), which is stubbed here.
    """
    _write_canonical(tmp_path, "work_plan.md", "- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\n")
    bridge, bus = _make_bridge(tmp_path)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda tid: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
    monkeypatch.setattr(bridge, "_supports_json_format", True)

    import json as _json

    # Vary the response per call so the bus anti-duplicate guard (identical
    # payloads) does not block later cycles -- production reviews always differ.
    cycle_n = {"n": 0}

    def fake_run(**kw):
        cycle_n["n"] += 1
        return (
            _json.dumps(
                {
                    "type": "text",
                    "phase": "final_answer",
                    "part": {
                        "type": "text",
                        "text": (
                            f"## SUMMARY\nIssues remain (cycle {cycle_n['n']}).\n"
                            "## BLOCKERS\n- Missing tests\n"
                            "## SUGGESTIONS\n- Add tests\n"
                            "DECISION: CHANGES"
                        ),
                    },
                }
            ),
            "",
            0,
        )

    monkeypatch.setattr(bridge, "_run_opencode_review", fake_run)
    # Stub the escalation authority: the bridge shells out to agent_controller
    # --request-changes; we only need it to be a no-op for this unit test.
    monkeypatch.setattr(
        "bus.review_bridge.subprocess.run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    class DummySupervisor:
        def transition_ticket(self, *args, **kwargs):
            pass

        def _is_supervisor_lock_stale(self):
            return False

        def requeue_ticket(self, ticket_id):
            return True

    review_dir = tmp_path / ".agent" / "runtime" / "reviews" / "WP-X"
    report_file = review_dir / "human_review_report.md"

    # Run 5 cycles; each emits one REVIEW_DECISION -> changes onto the bus.
    last_result = None
    for cycle in range(1, 6):
        last_result = bridge.run_manager_review_cycle(
            ticket_id="WP-X",
            supervisor=DummySupervisor(),
            timeout_seconds=5,
        )
        changes = bus.read_events(ticket_id="WP-X", event_type="REVIEW_DECISION")
        assert len(changes) == cycle
        # Counter is bus-derived, so it equals the number of cycles so far.
        assert bridge._count_prior_changes_from_bus("WP-X") == cycle
        # Report only appears once the bus shows >= 5 CHANGES.
        if cycle < 5:
            assert not report_file.exists()

    assert last_result.decision == ReviewDecision.CHANGES
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "WP-X" in content
    assert "HUMAN_GATE" in content or "5" in content


def test_changes_structure_validation(tmp_path):
    """Test CHANGES structure validation detects missing sections."""
    bridge, _ = _make_bridge(tmp_path)

    # Valid structure
    valid_stdout = (
        "## SUMMARY\nSummary here.\n"
        "## BLOCKERS\n- Blocker 1\n"
        "## SUGGESTIONS\n- Suggestion 1\n"
        "DECISION: CHANGES"
    )
    is_valid, missing = bridge._validate_changes_structure(valid_stdout)
    assert is_valid is True
    assert missing == []

    # Missing sections
    invalid_stdout = "## SUMMARY\nSummary here.\nDECISION: CHANGES"
    is_valid, missing = bridge._validate_changes_structure(invalid_stdout)
    assert is_valid is False
    assert "BLOCKERS" in missing
    assert "SUGGESTIONS" in missing


def test_review_attempt_bus_payload_is_lightweight(tmp_path, monkeypatch):
    """WP-2026-106 B1/B2: the bus stays lightweight.

    MANAGER_REVIEW_ATTEMPT must carry only review_log_path + a short
    stdout_tail. Heavy fields (blockers, stderr_tail, full stdout/stderr)
    must NOT be on the bus; they live in attempt-N.md on disk.
    """
    _write_canonical(tmp_path, "work_plan.md", "- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\n")
    bridge, bus = _make_bridge(tmp_path)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda tid: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")
    monkeypatch.setattr(bridge, "_get_manager_backend", lambda: "opencode")
    monkeypatch.setattr(bridge, "_supports_json_format", True)
    monkeypatch.setattr(
        "bus.review_bridge.subprocess.run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    import json as _json

    changes_with_blockers = _json.dumps(
        {
            "type": "text",
            "phase": "final_answer",
            "part": {
                "type": "text",
                "text": (
                    "## SUMMARY\nIssues.\n"
                    "## BLOCKERS\n- Critical bug in parser\n"
                    "## SUGGESTIONS\n- Fix parser\n"
                    "DECISION: CHANGES"
                ),
            },
        }
    )

    monkeypatch.setattr(
        bridge,
        "_run_opencode_review",
        lambda **kw: (changes_with_blockers, "", 0),
    )

    class DummySupervisor:
        def transition_ticket(self, *args, **kwargs):
            pass

        def _is_supervisor_lock_stale(self):
            return False

        def requeue_ticket(self, ticket_id):
            return True

    # Run 5 times to trigger HUMAN_GATE
    for _ in range(5):
        bridge.run_manager_review_cycle(
            ticket_id="WP-X",
            supervisor=DummySupervisor(),
            timeout_seconds=5,
        )

    events = bus.read_events(ticket_id="WP-X", event_type="MANAGER_REVIEW_ATTEMPT")
    assert len(events) >= 1

    changes_events = [e for e in events if e.payload.get("decision") == "changes"]
    assert changes_events, "expected at least one CHANGES attempt"

    for event in changes_events:
        payload = event.payload
        # B1/B2: heavy fields must NOT be on the bus.
        assert "blockers" not in payload
        assert "stderr_tail" not in payload
        assert "stdout" not in payload
        assert "stderr" not in payload
        # The bus keeps only a pointer + a short tail.
        assert "review_log_path" in payload
        assert len(payload.get("stdout_tail", "")) <= 500

    # The blockers content must instead be recoverable from disk.
    attempt_file = tmp_path / ".agent" / "runtime" / "reviews" / "WP-X" / "attempt-1.md"
    assert attempt_file.exists()
    assert "Critical bug" in attempt_file.read_text(encoding="utf-8")


def test_changes_counter_is_derived_from_bus(tmp_path):
    """WP-2026-106 B3: the escalation counter resumes from bus history.

    A fresh bridge must count prior REVIEW_DECISION->changes events for the
    ticket, so a mid-cycle restart does not reset progress toward HUMAN_GATE.
    """
    bridge, bus = _make_bridge(tmp_path)

    # No history yet -> 0.
    assert bridge._count_prior_changes_from_bus("WP-X") == 0

    # Two prior CHANGES decisions.
    for _ in range(2):
        bus.emit(
            "REVIEW_DECISION",
            ticket_id="WP-X",
            actor="MANAGER",
            payload={"decision": "changes"},
        )
    assert bridge._count_prior_changes_from_bus("WP-X") == 2

    # An APPROVE breaks the trailing CHANGES run.
    bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-X",
        actor="MANAGER",
        payload={"decision": "approve"},
    )
    assert bridge._count_prior_changes_from_bus("WP-X") == 0

    # New CHANGES after the reset count again from there.
    bus.emit(
        "REVIEW_DECISION",
        ticket_id="WP-X",
        actor="MANAGER",
        payload={"decision": "changes"},
    )
    assert bridge._count_prior_changes_from_bus("WP-X") == 1


def test_evidence_gate_blocks_docs_only_review(tmp_path, monkeypatch):
    """WOT-AUDIT-C1 / WT-2026-221b: a docs-only review packet is blocked.

    Positive barrier for the evidence gate: when classify_review_packet reports a
    docs-only packet, run_manager_review_cycle must return CHANGES, emit
    REVIEW_EVIDENCE_BLOCKED, and never invoke the backend review. This locks the
    contract so the inverse regression (docs-only silently APPROVED) cannot return.
    """
    _write_canonical(tmp_path, "work_plan.md", "- **deliverable_type:** code\n")
    _write_canonical(tmp_path, "STATE.md", "s")
    _write_canonical(tmp_path, "TURN.md", "t")
    _write_canonical(tmp_path, "execution_log.md", "### WP-X\n")
    bridge, bus = _make_bridge(tmp_path)
    monkeypatch.setattr(
        bridge.state_ingest, "_latest_state", lambda tid: "READY_FOR_REVIEW"
    )
    monkeypatch.setattr(
        bridge,
        "classify_review_packet",
        lambda tid: {
            "bus_active": True,
            "is_empty": False,
            "is_docs_only": True,
            "is_collaboration_only": False,
            "productive_files": [],
            "has_motor_evidence": False,
            "has_destination_productive": False,
            "deliverable_type": "code",
            "reason": "Ticket WP-X: all changes are docs-only (1 files).",
            "docs_only_files": ["README.md"],
            "motor_diff_files": [],
            "destination_diff_files": ["README.md"],
        },
    )

    called = {"review": 0}

    def fail_if_called(**kw):
        called["review"] += 1
        return ("DECISION: APPROVE\n", "", 0)

    monkeypatch.setattr(bridge, "_run_opencode_review", fail_if_called)

    class DummySupervisor:
        def transition_ticket(self, *args, **kwargs):
            pass

        def _is_supervisor_lock_stale(self):
            return False

        def requeue_ticket(self, ticket_id):
            return True

    result = bridge.run_manager_review_cycle(
        ticket_id="WP-X", supervisor=DummySupervisor()
    )

    assert result.decision == ReviewDecision.CHANGES
    # The gate must short-circuit BEFORE invoking the backend review.
    assert called["review"] == 0
    blocked = bus.read_events(ticket_id="WP-X", event_type="REVIEW_EVIDENCE_BLOCKED")
    assert len(blocked) == 1
    assert blocked[0].payload["classification"] == "docs_only"
