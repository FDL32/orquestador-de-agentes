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


class TestLoadDecisionArtifact:
    """WT-2026-252a follow-up: structured decision artifact as primary channel.

    The Manager writes .agent/runtime/reviews/decision_<ticket>.json during
    review; the bridge consumes it before falling back to transcript parsing.
    """

    def _write_artifact(self, reviews_dir, ticket_id, payload) -> None:
        reviews_dir.mkdir(parents=True, exist_ok=True)
        path = reviews_dir / f"decision_{ticket_id}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_valid_artifact_approve(self, tmp_path) -> None:
        from bus.decision_parser import load_decision_artifact

        self._write_artifact(
            tmp_path,
            "WOT-2026-001a",
            {"ticket_id": "WOT-2026-001a", "decision": "APROBADO"},
        )
        result = load_decision_artifact(tmp_path, "WOT-2026-001a")
        assert result is not None
        decision, method = result
        assert decision == ReviewDecision.APPROVE
        assert method == "decision_artifact"

    def test_valid_artifact_changes(self, tmp_path) -> None:
        from bus.decision_parser import load_decision_artifact

        self._write_artifact(
            tmp_path, "WT-2026-100", {"ticket_id": "WT-2026-100", "decision": "CHANGES"}
        )
        result = load_decision_artifact(tmp_path, "WT-2026-100")
        assert result is not None
        assert result[0] == ReviewDecision.CHANGES

    def test_missing_artifact_returns_none(self, tmp_path) -> None:
        from bus.decision_parser import load_decision_artifact

        assert load_decision_artifact(tmp_path, "WT-2026-100") is None

    def test_corrupt_artifact_returns_none(self, tmp_path) -> None:
        from bus.decision_parser import load_decision_artifact

        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "decision_WT-2026-100.json").write_text(
            "{not json", encoding="utf-8"
        )
        assert load_decision_artifact(tmp_path, "WT-2026-100") is None

    def test_ticket_mismatch_returns_none(self, tmp_path) -> None:
        from bus.decision_parser import load_decision_artifact

        self._write_artifact(
            tmp_path,
            "WT-2026-100",
            {"ticket_id": "WT-2026-999", "decision": "APROBADO"},
        )
        assert load_decision_artifact(tmp_path, "WT-2026-100") is None

    def test_invalid_decision_returns_none(self, tmp_path) -> None:
        from bus.decision_parser import load_decision_artifact

        self._write_artifact(
            tmp_path, "WT-2026-100", {"ticket_id": "WT-2026-100", "decision": "MAYBE"}
        )
        assert load_decision_artifact(tmp_path, "WT-2026-100") is None

    def test_stale_artifact_returns_none(self, tmp_path) -> None:
        import time as time_mod

        from bus.decision_parser import load_decision_artifact

        self._write_artifact(
            tmp_path,
            "WT-2026-100",
            {"ticket_id": "WT-2026-100", "decision": "APROBADO"},
        )
        # Artifact written before the review session started -> stale
        future = time_mod.time() + 60
        assert (
            load_decision_artifact(tmp_path, "WT-2026-100", not_before=future) is None
        )

    def test_fresh_artifact_passes_not_before(self, tmp_path) -> None:
        import time as time_mod

        from bus.decision_parser import load_decision_artifact

        past = time_mod.time() - 60
        self._write_artifact(
            tmp_path,
            "WT-2026-100",
            {"ticket_id": "WT-2026-100", "decision": "APROBADO"},
        )
        result = load_decision_artifact(tmp_path, "WT-2026-100", not_before=past)
        assert result is not None
        assert result[0] == ReviewDecision.APPROVE
