"""Tests for manager_feedback archival logic.

Tests cover:
- _can_prove_close: bus events prove close/approval.
- _step_archive_manager_feedback: only archives files with proven close.
- archive_manager_feedback: standalone archival function.
"""

from __future__ import annotations

from pathlib import Path

from scripts.archive_collaboration_artifacts import (
    archive_manager_feedback,
)
from scripts.session_closeout import (
    _can_prove_close,
    _extract_ticket_id_from_feedback,
    _find_manager_feedback_files,
    _step_archive_manager_feedback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: str,
    ticket_id: str,
    payload: dict | None = None,
) -> dict:
    """Create a minimal event dict for testing."""
    return {
        "event_id": f"ev-{ticket_id}",
        "event_type": event_type,
        "ticket_id": ticket_id,
        "actor": "MANAGER",
        "timestamp": "2026-06-01T10:00:00+00:00",
        "payload": payload or {},
        "schema_version": "1.0",
        "sequence_number": 1,
    }


def _make_feedback_file(
    collab_dir: Path, ticket_id: str, content: str | None = None
) -> Path:
    """Create a manager_feedback_*.md file for testing."""
    fname = f"manager_feedback_{ticket_id}.md"
    fb_path = collab_dir / fname
    fb_path.write_text(
        content or f"# Feedback for {ticket_id}\n\nSome review notes.\n",
        encoding="utf-8",
    )
    return fb_path


def _setup_collab(tmp_path: Path, ticket_ids: list[str]) -> Path:
    """Set up a collaboration dir with manager_feedback files and work_plan."""
    collab_dir = tmp_path / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True, exist_ok=True)
    for tid in ticket_ids:
        _make_feedback_file(collab_dir, tid)

    # Create work_plan.md
    wp = collab_dir / "work_plan.md"
    wp.write_text(
        "# Work Plan\n\n**ID:** WP-2026-999\n**Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )
    return collab_dir


# Tests: _can_prove_close  # noqa: ERA001


class TestCanProveClose:
    """Tests for bus-based close/approval detection."""

    def test_state_changed_to_completed(self) -> None:
        """STATE_CHANGED to COMPLETED proves close."""
        events = [
            _make_event(
                "STATE_CHANGED",
                "WP-2026-155",
                {"from_state": "READY_TO_CLOSE", "to_state": "COMPLETED"},
            ),
        ]
        assert _can_prove_close("WP-2026-155", events) is True

    def test_state_changed_to_human_gate_does_not_prove_close(self) -> None:
        """STATE_CHANGED to HUMAN_GATE does NOT prove close.

        HUMAN_GATE is an escalation state, not final closure.
        Archiving manager_feedback_* on HUMAN_GATE would violate the contract:
        feedback must be preserved when close cannot be proven.
        """
        events = [
            _make_event(
                "STATE_CHANGED",
                "WP-2026-155",
                {"from_state": "READY_TO_CLOSE", "to_state": "HUMAN_GATE"},
            ),
        ]
        assert _can_prove_close("WP-2026-155", events) is False

    def test_state_changed_to_ready_to_close(self) -> None:
        """STATE_CHANGED to READY_TO_CLOSE (manager-approve) proves close."""
        events = [
            _make_event(
                "STATE_CHANGED",
                "WP-2026-155",
                {
                    "from_state": "READY_FOR_REVIEW",
                    "to_state": "READY_TO_CLOSE",
                    "source": "manager-approve",
                },
            ),
        ]
        assert _can_prove_close("WP-2026-155", events) is True

    def test_review_decision_approve(self) -> None:
        """REVIEW_DECISION with approve proves close."""
        events = [
            _make_event(
                "REVIEW_DECISION",
                "WP-2026-155",
                {"decision": "approve"},
            ),
        ]
        assert _can_prove_close("WP-2026-155", events) is True

    def test_non_terminal_state_does_not_prove_close(self) -> None:
        """STATE_CHANGED to IN_PROGRESS does NOT prove close."""
        events = [
            _make_event(
                "STATE_CHANGED",
                "WP-2026-155",
                {"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
            ),
        ]
        assert _can_prove_close("WP-2026-155", events) is False

    def test_empty_events_does_not_prove_close(self) -> None:
        """Empty event list does not prove close."""
        assert _can_prove_close("WP-2026-155", []) is False

    def test_other_ticket_does_not_prove_close(self) -> None:
        """Events for a different ticket don't prove this ticket's close."""
        events = [
            _make_event(
                "STATE_CHANGED",
                "WP-2026-999",
                {"from_state": "READY_TO_CLOSE", "to_state": "COMPLETED"},
            ),
        ]
        assert _can_prove_close("WP-2026-155", events) is False


# Tests: _find_manager_feedback_files and _extract_ticket_id_from_feedback  # noqa: ERA001


class TestManagerFeedbackFileHelpers:
    """Tests for finding and parsing manager_feedback files."""

    def test_finds_feedback_files(self, tmp_path: Path) -> None:
        """Finds all manager_feedback_*.md files in the collaboration dir."""
        collab_dir = _setup_collab(tmp_path, ["WP-2026-155", "WP-2026-156"])
        files = _find_manager_feedback_files(collab_dir)
        assert len(files) == 2
        assert any("WP-2026-155" in f.name for f in files)
        assert any("WP-2026-156" in f.name for f in files)

    def test_ignores_other_files(self, tmp_path: Path) -> None:
        """Non-feedback files are ignored."""
        collab_dir = _setup_collab(tmp_path, ["WP-2026-155"])
        (collab_dir / "work_plan.md").write_text("# Work Plan\n", encoding="utf-8")
        (collab_dir / "TURN.md").write_text("# TURN\n", encoding="utf-8")
        files = _find_manager_feedback_files(collab_dir)
        assert len(files) == 1
        assert "work_plan.md" not in [f.name for f in files]

    def test_extracts_ticket_id(self) -> None:
        """Correctly extracts ticket ID from filename."""
        assert (
            _extract_ticket_id_from_feedback("manager_feedback_WP-2026-155.md")
            == "WP-2026-155"
        )
        assert (
            _extract_ticket_id_from_feedback("manager_feedback_WT-2026-001.md")
            == "WT-2026-001"
        )

    def test_extract_returns_none_for_mismatch(self) -> None:
        """Returns None for filenames that don't match the pattern."""
        assert _extract_ticket_id_from_feedback("work_plan.md") is None
        assert _extract_ticket_id_from_feedback("review_queue.md") is None


# Tests: _step_archive_manager_feedback  # noqa: ERA001


class TestStepArchiveManagerFeedback:
    """Tests for the manager_feedback archival step in session_closeout."""

    def test_archives_when_bus_has_close(self, tmp_path: Path) -> None:
        """Feedback file is archived when close is proven by bus."""
        project_root = tmp_path
        collab_dir = _setup_collab(project_root, ["WP-2026-155", "WP-2026-156"])
        _make_feedback_file(collab_dir, "WP-2026-155")
        _make_feedback_file(collab_dir, "WP-2026-156")

        events = [
            _make_event(
                "STATE_CHANGED",
                "WP-2026-155",
                {"from_state": "READY_TO_CLOSE", "to_state": "COMPLETED"},
            ),
        ]

        result = _step_archive_manager_feedback(
            project_root, dry_run=False, events=events
        )
        assert result.status == "PASS"
        assert "Archived" in result.detail

        # WP-2026-155 should be archived
        archive_dir = (
            project_root / ".agent" / "collaboration" / "archive" / "manager_feedback"
        )
        assert (archive_dir / "manager_feedback_WP-2026-155.md").exists()
        # WP-2026-156 should remain alive
        assert (collab_dir / "manager_feedback_WP-2026-156.md").exists()

    def test_keeps_file_when_close_cannot_be_proven(self, tmp_path: Path) -> None:
        """Feedback file remains alive when close cannot be proven."""
        project_root = tmp_path
        collab_dir = _setup_collab(project_root, ["WP-2026-155"])
        _make_feedback_file(collab_dir, "WP-2026-155")

        events: list[dict] = []  # No events = no close

        result = _step_archive_manager_feedback(
            project_root, dry_run=False, events=events
        )
        # Either SKIP (no files to archive) or PASS (with kept files)
        assert result.status in ("SKIP", "PASS")
        assert (
            "close not proven" in result.detail or "No files archived" in result.detail
        )

        # File should still be in collaboration dir
        assert (collab_dir / "manager_feedback_WP-2026-155.md").exists()

    def test_dry_run_skips_archival(self, tmp_path: Path) -> None:
        """Dry run skips manager feedback archival."""
        project_root = tmp_path
        collab_dir = _setup_collab(project_root, ["WP-2026-155"])
        _make_feedback_file(collab_dir, "WP-2026-155")

        result = _step_archive_manager_feedback(project_root, dry_run=True, events=[])
        assert result.status == "SKIP"

    def test_no_feedback_files_skips(self, tmp_path: Path) -> None:
        """When no feedback files exist, returns SKIP."""
        project_root = tmp_path
        result = _step_archive_manager_feedback(project_root, dry_run=False, events=[])
        assert result.status == "SKIP"
        assert "No manager_feedback files" in result.detail


# ---------------------------------------------------------------------------
# Tests: archive_manager_feedback (standalone function in archive_collaboration_artifacts)
# ---------------------------------------------------------------------------


class TestArchiveManagerFeedbackStandalone:
    """Tests for the standalone archive_manager_feedback function."""

    def test_archives_specific_tickets(self, tmp_path: Path) -> None:
        """Only the specified ticket IDs are archived."""
        collab_dir = _setup_collab(tmp_path, ["WP-2026-155", "WP-2026-156"])

        result = archive_manager_feedback(
            collaboration_dir=collab_dir,
            ticket_ids_to_archive=["WP-2026-155"],
            dry_run=False,
        )
        assert len(result["archived"]) == 1
        assert len(result["errors"]) == 0

        archive_dir = collab_dir / "archive" / "manager_feedback"
        assert (archive_dir / "manager_feedback_WP-2026-155.md").exists()
        # WP-2026-156 should remain in collaboration dir
        assert (collab_dir / "manager_feedback_WP-2026-156.md").exists()

    def test_idempotent_second_run(self, tmp_path: Path) -> None:
        """Second run has nothing to archive (already moved)."""
        collab_dir = _setup_collab(tmp_path, ["WP-2026-155"])

        first = archive_manager_feedback(
            collaboration_dir=collab_dir,
            ticket_ids_to_archive=["WP-2026-155"],
            dry_run=False,
        )
        assert len(first["archived"]) == 1

        # File was moved out of collaboration dir into archive subdirectory.
        # Second run finds no feedback files -> returns empty archived list.
        second = archive_manager_feedback(
            collaboration_dir=collab_dir,
            ticket_ids_to_archive=["WP-2026-155"],
            dry_run=False,
        )
        assert len(second["archived"]) == 0
        assert len(second["errors"]) == 0

    def test_idempotent_removes_live_copy_when_archive_exists(
        self, tmp_path: Path
    ) -> None:
        """If archive already has the file, remove duplicate live feedback."""
        collab_dir = _setup_collab(tmp_path, ["WP-2026-155"])
        archive_dir = collab_dir / "archive" / "manager_feedback"
        archive_dir.mkdir(parents=True)
        archived_file = archive_dir / "manager_feedback_WP-2026-155.md"
        archived_file.write_text("# Already archived\n", encoding="utf-8")

        live_file = collab_dir / "manager_feedback_WP-2026-155.md"
        assert live_file.exists()

        result = archive_manager_feedback(
            collaboration_dir=collab_dir,
            ticket_ids_to_archive=["WP-2026-155"],
            dry_run=False,
        )

        assert len(result["archived"]) == 1
        assert len(result["errors"]) == 0
        assert archived_file.exists()
        assert not live_file.exists()

    def test_dry_run_does_not_move_files(self, tmp_path: Path) -> None:
        """Dry run reports without moving files."""
        collab_dir = _setup_collab(tmp_path, ["WP-2026-155"])

        result = archive_manager_feedback(
            collaboration_dir=collab_dir,
            ticket_ids_to_archive=["WP-2026-155"],
            dry_run=True,
        )
        assert len(result["archived"]) == 1
        assert len(result["errors"]) == 0

        # File should still be in place
        assert (collab_dir / "manager_feedback_WP-2026-155.md").exists()

    def test_no_ticket_ids_returns_empty(self, tmp_path: Path) -> None:
        """Empty ticket list returns early with no action."""
        collab_dir = _setup_collab(tmp_path, ["WP-2026-155"])
        result = archive_manager_feedback(
            collaboration_dir=collab_dir,
            ticket_ids_to_archive=[],
            dry_run=False,
        )
        assert len(result["archived"]) == 0

    def test_unparseable_filename_skipped(self, tmp_path: Path) -> None:
        """Files with unparseable ticket IDs are skipped."""
        collab_dir = _setup_collab(tmp_path, ["WP-2026-155"])
        # Create a malformed feedback file
        bad_file = collab_dir / "manager_feedback_bad-file.md"
        bad_file.write_text("# Bad\n", encoding="utf-8")

        result = archive_manager_feedback(
            collaboration_dir=collab_dir,
            ticket_ids_to_archive=["WP-2026-155"],
            dry_run=False,
        )
        assert len(result["archived"]) == 1  # Only the valid one
        assert len(result["skipped"]) >= 1
        assert any("unparseable" in s for s in result["skipped"])
