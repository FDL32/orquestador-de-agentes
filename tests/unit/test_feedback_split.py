"""Tests for WT-2026-250b: manager_feedback digest/raw split.

Validates that _record_review writes a compact digest to collaboration/ and
routes raw stdout to .agent/runtime/reviews/ (already gitignored).
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


RAW_NDJSON = '{"type":"text","text":"hello"}\n{"type":"text","text":"world"}\n'


def test_tracked_digest_excludes_raw_ndjson(
    fake_supervisor: MagicMock, tmp_path: Path
) -> None:
    """manager_feedback_*.md must not contain the raw NDJSON block."""
    _record_review(
        supervisor=fake_supervisor,
        ticket_id="WT-2026-250b",
        decision="APPROVED",
        feedback="Everything looks good.",
        source="test",
        raw_stdout=RAW_NDJSON,
    )

    feedback_file = (
        fake_supervisor.collaboration_dir / "manager_feedback_WT-2026-250b.md"
    )
    assert feedback_file.exists(), "Digest file must be created"
    content = feedback_file.read_text(encoding="utf-8")
    assert '{"type"' not in content, "Tracked digest must not contain raw NDJSON"
    assert "Raw Review" not in content, (
        "Tracked digest must not have ## Raw Review section"
    )


def test_raw_file_written_to_runtime_reviews(
    fake_supervisor: MagicMock, tmp_path: Path
) -> None:
    """Raw stdout must be written to .agent/runtime/reviews/."""
    _record_review(
        supervisor=fake_supervisor,
        ticket_id="WT-2026-250b",
        decision="APPROVED",
        feedback="Everything looks good.",
        source="test",
        raw_stdout=RAW_NDJSON,
    )

    raw_dir = tmp_path / ".agent" / "runtime" / "reviews"
    assert raw_dir.exists(), ".agent/runtime/reviews/ must be created"
    raw_files = list(raw_dir.glob("manager_review_raw_*.txt"))
    assert len(raw_files) == 1, f"Expected 1 raw file, found {len(raw_files)}"
    raw_content = raw_files[0].read_text(encoding="utf-8")
    assert RAW_NDJSON in raw_content, "Raw NDJSON must be in the raw file"


def test_digest_contains_decision_and_feedback(
    fake_supervisor: MagicMock, tmp_path: Path
) -> None:
    """Digest must still contain decision and parsed feedback text."""
    _record_review(
        supervisor=fake_supervisor,
        ticket_id="WT-2026-250b",
        decision="CHANGES",
        feedback="Missing test coverage.",
        source="test",
        raw_stdout=RAW_NDJSON,
    )

    feedback_file = (
        fake_supervisor.collaboration_dir / "manager_feedback_WT-2026-250b.md"
    )
    content = feedback_file.read_text(encoding="utf-8")
    assert "CHANGES" in content
    assert "Missing test coverage." in content


def test_digest_points_to_raw_file(fake_supervisor: MagicMock, tmp_path: Path) -> None:
    """Digest must reference the raw file location."""
    _record_review(
        supervisor=fake_supervisor,
        ticket_id="WT-2026-250b",
        decision="APPROVED",
        feedback="Ok",
        source="test",
        raw_stdout=RAW_NDJSON,
    )

    feedback_file = (
        fake_supervisor.collaboration_dir / "manager_feedback_WT-2026-250b.md"
    )
    content = feedback_file.read_text(encoding="utf-8")
    assert "runtime/reviews" in content, "Digest must reference the raw file path"


def test_empty_raw_stdout_writes_placeholder(
    fake_supervisor: MagicMock, tmp_path: Path
) -> None:
    """Empty raw_stdout must write a placeholder to the raw file."""
    _record_review(
        supervisor=fake_supervisor,
        ticket_id="WT-2026-250b",
        decision="APPROVED",
        feedback="Ok",
        source="test",
        raw_stdout="",
    )

    raw_dir = tmp_path / ".agent" / "runtime" / "reviews"
    raw_files = list(raw_dir.glob("manager_review_raw_*.txt"))
    assert len(raw_files) == 1
    assert "[empty stdout]" in raw_files[0].read_text(encoding="utf-8")
