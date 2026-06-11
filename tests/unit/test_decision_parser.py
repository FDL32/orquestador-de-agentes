"""Tests for WT-2026-255a: bus/decision_parser standalone module.

[NON-REVERSE-CLASSICAL: seam extraction refactor — decision parser moved from
ReviewBridge instance methods to standalone functions in bus.decision_parser]

Validates parse contract (WT-2026-235a + WT-2026-242a):
- json_final_answer is authoritative for APPROVE/CHANGES
- json_last_text degrades strong decisions to INSPECT
- text_regex is diagnostic only (never APPROVE/CHANGES)
- fallback_inspect when nothing recognized
"""

from __future__ import annotations

import json

from bus.decision_parser import (
    ReviewDecision,
    extract_decision_from_single_line,
    extract_decision_from_text_events,
    parse_opencode_decision,
    parse_opencode_json_decision,
    resolve_event_phase,
)


def _make_text_event(text: str, phase: str = "") -> str:
    event: dict = {"type": "text", "part": {"text": text}}
    if phase:
        event["phase"] = phase
    return json.dumps(event)


class TestResolveEventPhase:
    def test_top_level_phase(self) -> None:
        event = {"phase": "final_answer", "type": "text"}
        assert resolve_event_phase(event) == "final_answer"

    def test_nested_openai_phase(self) -> None:
        event = {
            "type": "text",
            "part": {"metadata": {"openai": {"phase": "final_answer"}}},
        }
        assert resolve_event_phase(event) == "final_answer"

    def test_no_phase_returns_empty(self) -> None:
        event = {"type": "text"}
        assert resolve_event_phase(event) == ""


class TestExtractDecisionFromSingleLine:
    def test_approve_in_final_answer(self) -> None:
        line = _make_text_event("DECISION: APPROVE", phase="final_answer")
        result = extract_decision_from_single_line(line, require_final_answer=True)
        assert result == ReviewDecision.APPROVE

    def test_changes_without_final_answer_returns_none_when_required(self) -> None:
        line = _make_text_event("DECISION: CHANGES")
        result = extract_decision_from_single_line(line, require_final_answer=True)
        assert result is None

    def test_changes_without_final_answer_returns_decision_when_not_required(
        self,
    ) -> None:
        line = _make_text_event("DECISION: CHANGES")
        result = extract_decision_from_single_line(line, require_final_answer=False)
        assert result == ReviewDecision.CHANGES

    def test_non_json_line_returns_none(self) -> None:
        result = extract_decision_from_single_line(
            "plain text", require_final_answer=False
        )
        assert result is None

    def test_non_text_event_returns_none(self) -> None:
        line = json.dumps({"type": "step_start"})
        result = extract_decision_from_single_line(line, require_final_answer=False)
        assert result is None


class TestExtractDecisionFromTextEvents:
    def test_last_event_wins(self) -> None:
        stdout = "\n".join(
            [
                _make_text_event("DECISION: APPROVE"),
                _make_text_event("DECISION: CHANGES"),
            ]
        )
        result = extract_decision_from_text_events(stdout, require_final_answer=False)
        assert result == ReviewDecision.CHANGES

    def test_final_answer_only_filter(self) -> None:
        stdout = "\n".join(
            [
                _make_text_event("DECISION: APPROVE"),
                _make_text_event("DECISION: CHANGES", phase="final_answer"),
            ]
        )
        result = extract_decision_from_text_events(stdout, require_final_answer=True)
        assert result == ReviewDecision.CHANGES

    def test_empty_stdout_returns_none(self) -> None:
        result = extract_decision_from_text_events("", require_final_answer=False)
        assert result is None


class TestParseOpencodeJsonDecision:
    def test_final_answer_returns_json_final_answer(self) -> None:
        stdout = _make_text_event("DECISION: APPROVE", phase="final_answer")
        decision, method = parse_opencode_json_decision(stdout)
        assert decision == ReviewDecision.APPROVE
        assert method == "json_final_answer"

    def test_no_final_answer_returns_json_last_text(self) -> None:
        stdout = _make_text_event("DECISION: APPROVE")
        decision, method = parse_opencode_json_decision(stdout)
        assert decision == ReviewDecision.APPROVE
        assert method == "json_last_text"

    def test_no_decision_returns_json_no_decision(self) -> None:
        stdout = _make_text_event("nothing here")
        decision, method = parse_opencode_json_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "json_no_decision"


class TestParseOpencodeDecision:
    def test_final_answer_approve_authoritative(self) -> None:
        stdout = _make_text_event("DECISION: APPROVE", phase="final_answer")
        decision, method = parse_opencode_decision(stdout)
        assert decision == ReviewDecision.APPROVE
        assert method == "json_final_answer"

    def test_json_last_text_changes_degraded_to_inspect(self) -> None:
        stdout = _make_text_event("DECISION: CHANGES")
        decision, method = parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "json_last_text"

    def test_text_regex_approve_degraded_to_inspect(self) -> None:
        stdout = "DECISION: APPROVE"
        decision, method = parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "text_regex"

    def test_text_regex_changes_degraded_to_inspect(self) -> None:
        stdout = "DECISION: CHANGES"
        decision, method = parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "text_regex"

    def test_explicit_inspect(self) -> None:
        stdout = "DECISION: INSPECT"
        decision, method = parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "explicit_inspect"

    def test_fallback_inspect(self) -> None:
        stdout = "no decision here"
        decision, method = parse_opencode_decision(stdout)
        assert decision == ReviewDecision.INSPECT
        assert method == "fallback_inspect"
