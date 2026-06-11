"""Tests for WT-2026-252a: structured decision artifact in manager_feedback_*.md.

[NON-REVERSE-CLASSICAL: new feature — adds machine-readable Decision Artifact
section to manager_feedback digest; no prior bug to reproduce]

Validates that _record_review writes a parseable ## Decision Artifact block
so downstream tools can extract decision without regex-scraping narrative text.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts.manager_review_bridge import _record_review  # noqa: E402


@pytest.fixture()
def fake_supervisor(tmp_path: Path) -> MagicMock:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "review_queue.md").write_text("# review_queue\n", encoding="utf-8")
    notifications = collab / "notifications.md"
    notifications.write_text("", encoding="utf-8")

    sup = MagicMock()
    sup.collaboration_dir = collab
    sup.project_root = tmp_path
    sup.notifications_path = notifications
    return sup


class TestDecisionArtifactSection:
    """manager_feedback_*.md must contain a structured Decision Artifact block."""

    def test_artifact_section_present(self, fake_supervisor: MagicMock) -> None:
        _record_review(
            supervisor=fake_supervisor,
            ticket_id="WT-2026-252a",
            decision="APPROVE",
            feedback="All gates passed.",
            source="test",
            parse_method="json_final_answer",
        )
        content = (
            fake_supervisor.collaboration_dir / "manager_feedback_WT-2026-252a.md"
        ).read_text(encoding="utf-8")
        assert "## Decision Artifact" in content, (
            "Digest must have ## Decision Artifact section"
        )

    def test_artifact_contains_decision_field(self, fake_supervisor: MagicMock) -> None:
        _record_review(
            supervisor=fake_supervisor,
            ticket_id="WT-2026-252a",
            decision="CHANGES",
            feedback="Missing tests.",
            source="test",
            parse_method="regex_keyword",
        )
        content = (
            fake_supervisor.collaboration_dir / "manager_feedback_WT-2026-252a.md"
        ).read_text(encoding="utf-8")
        assert "decision: CHANGES" in content, (
            "Artifact block must contain machine-readable decision field"
        )

    def test_artifact_contains_parse_method(self, fake_supervisor: MagicMock) -> None:
        _record_review(
            supervisor=fake_supervisor,
            ticket_id="WT-2026-252a",
            decision="APPROVE",
            feedback="Ok.",
            source="test",
            parse_method="json_final_answer",
        )
        content = (
            fake_supervisor.collaboration_dir / "manager_feedback_WT-2026-252a.md"
        ).read_text(encoding="utf-8")
        assert "parse_method: json_final_answer" in content, (
            "Artifact block must include parse_method for auditability"
        )

    def test_artifact_does_not_include_streaming_ndjson(
        self, fake_supervisor: MagicMock
    ) -> None:
        _record_review(
            supervisor=fake_supervisor,
            ticket_id="WT-2026-252a",
            decision="APPROVE",
            feedback="Ok.",
            source="test",
            raw_stdout='{"type":"text","text":"DECISION: APPROVE"}',
        )
        content = (
            fake_supervisor.collaboration_dir / "manager_feedback_WT-2026-252a.md"
        ).read_text(encoding="utf-8")
        assert '{"type"' not in content, (
            "Artifact block must not contain raw streaming NDJSON"
        )

    def test_artifact_contains_ticket_id(self, fake_supervisor: MagicMock) -> None:
        _record_review(
            supervisor=fake_supervisor,
            ticket_id="WT-2026-252a",
            decision="APPROVE",
            feedback="Ok.",
            source="test",
        )
        content = (
            fake_supervisor.collaboration_dir / "manager_feedback_WT-2026-252a.md"
        ).read_text(encoding="utf-8")
        assert "ticket_id: WT-2026-252a" in content, (
            "Artifact block must include ticket_id"
        )
