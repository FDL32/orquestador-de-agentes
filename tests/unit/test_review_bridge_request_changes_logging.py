"""Tests for WP-2026-152 Phase 2: bridge stderr logging for failed --request-changes.

Verifies that the review bridge logs non-zero --request-changes returncodes
to stderr without changing the transition semantics.
"""

import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


class TestReviewBridgeRequestChangesLogging:
    """Test that the bridge logs failed --request-changes calls to stderr."""

    @staticmethod
    def _structured_changes_output() -> str:
        return textwrap.dedent(
            """\
            ## SUMMARY
            Builder must address the blocking finding.

            ## BLOCKERS
            - bus/review_bridge.py:1 fix the failing path

            ## SUGGESTIONS
            - none

            DECISION: CHANGES
            """
        )

    @pytest.fixture
    def mock_event_bus(self):
        """Create a mock event bus."""
        bus = MagicMock()
        bus.read_events = MagicMock(return_value=[])
        bus.latest_event = MagicMock(return_value=None)
        bus.emit = MagicMock()
        return bus

    @pytest.fixture
    def mock_project_root(self, tmp_path: Path):
        """Create a mock project root with minimal structure."""
        work_plan = tmp_path / ".agent" / "collaboration" / "work_plan.md"
        work_plan.parent.mkdir(parents=True, exist_ok=True)
        work_plan.write_text(
            "# Work Plan\n\n## Metadata\n- **ID:** WP-2026-152\n- **Estado:** APPROVED\n",
            encoding="utf-8",
        )
        agents_config = tmp_path / ".agent" / "config" / "agents.json"
        agents_config.parent.mkdir(parents=True, exist_ok=True)
        agents_config.write_text(
            '{"active_profile": "engine-dev", "manager_review": {"max_attempts": 5}}',
            encoding="utf-8",
        )
        return tmp_path

    def test_bridge_logs_nonzero_request_changes_returncode(
        self, mock_event_bus: MagicMock, mock_project_root: Path, capfd
    ):
        """Bridge logs non-zero --request-changes returncode to stderr."""
        from bus import review_bridge

        bridge = review_bridge.ReviewBridge(
            event_bus=mock_event_bus,
            project_root=mock_project_root,
        )
        controller = mock_project_root / ".agent" / "agent_controller.py"
        controller.touch(exist_ok=True)

        mock_result = subprocess.CompletedProcess(
            args=[sys.executable, str(controller), "--request-changes", "WP-2026-152"],
            returncode=1,
            stdout="",
            stderr="Error: some error occurred",
        )

        with (
            patch.object(
                bridge.state_ingest, "_latest_state", return_value="READY_FOR_REVIEW"
            ),
            patch.object(
                bridge.state_ingest, "_read_deliverable_type", return_value="code"
            ),
            patch.object(bridge, "_build_review_prompt", return_value="prompt"),
            patch.object(bridge, "_get_manager_backend", return_value="opencode"),
            patch.object(
                review_bridge,
                "load_decision_artifact",
                return_value=(review_bridge.ReviewDecision.CHANGES, "artifact"),
            ),
            patch.object(
                bridge,
                "_run_opencode_review",
                return_value=(self._structured_changes_output(), "", 0),
            ),
            patch.object(bridge, "_count_prior_changes_from_bus", return_value=0),
            patch.object(review_bridge.subprocess, "run", return_value=mock_result),
        ):
            result = bridge.run_manager_review_cycle(
                ticket_id="WP-2026-152",
                supervisor=MagicMock(),
            )

        captured = capfd.readouterr()
        assert result.decision == review_bridge.ReviewDecision.CHANGES
        assert "--request-changes failed" in captured.err
        assert "rc=1" in captured.err

    def test_bridge_logging_does_not_change_semantics(
        self, mock_event_bus: MagicMock, mock_project_root: Path
    ):
        """Bridge stderr logging is observability only, does not change semantics."""
        from bus import review_bridge

        bridge = review_bridge.ReviewBridge(
            event_bus=mock_event_bus,
            project_root=mock_project_root,
        )
        controller = mock_project_root / ".agent" / "agent_controller.py"
        controller.touch(exist_ok=True)

        mock_result = subprocess.CompletedProcess(
            args=[sys.executable, str(controller), "--request-changes", "WP-2026-152"],
            returncode=1,
            stdout="",
            stderr="Error: some error occurred",
        )

        with (
            patch.object(
                bridge.state_ingest, "_latest_state", return_value="READY_FOR_REVIEW"
            ),
            patch.object(
                bridge.state_ingest, "_read_deliverable_type", return_value="code"
            ),
            patch.object(bridge, "_build_review_prompt", return_value="prompt"),
            patch.object(bridge, "_get_manager_backend", return_value="opencode"),
            patch.object(
                review_bridge,
                "load_decision_artifact",
                return_value=(review_bridge.ReviewDecision.CHANGES, "artifact"),
            ),
            patch.object(
                bridge,
                "_run_opencode_review",
                return_value=(self._structured_changes_output(), "", 0),
            ),
            patch.object(bridge, "_count_prior_changes_from_bus", return_value=0),
            patch.object(review_bridge.subprocess, "run", return_value=mock_result),
        ):
            result = bridge.run_manager_review_cycle(
                ticket_id="WP-2026-152",
                supervisor=MagicMock(),
            )

        assert result.decision == review_bridge.ReviewDecision.CHANGES
        assert result.transport_ok is True
