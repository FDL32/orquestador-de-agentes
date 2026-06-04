"""WT-2026-221b: Manager evidence gate tests.

Tests the binary evidence barrier that rejects docs-only/collaboration-only
review packets before they reach the Manager.

Reproduces the failure family seq 602/606/617 where the Manager rejected
reviews with no productive evidence visible from the motor repository.
"""

# ruff: noqa: ERA001

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge, ReviewDecision


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus(tmp_path):
    """Create an EventBus instance for testing."""
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    return EventBus(runtime_dir=runtime_dir)


@pytest.fixture
def review_bridge(event_bus, tmp_path):
    """Create a ReviewBridge instance for testing.

    Sets up minimal collaboration files and a work_plan with ticket ID.
    """
    collab_dir = tmp_path / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True)
    (collab_dir / "work_plan.md").write_text(
        "# Work Plan\n\n## Metadata\n- **ID:** WT-2026-221b\n"
        "- **deliverable_type:** code\n",
        encoding="utf-8",
    )
    (collab_dir / "TURN.md").write_text(
        "# TURNO ACTUAL\n\n## Agente Activo\n\n"
        "| Campo | Valor |\n"
        "|-------|-------|\n"
        "| **ROL** | **BUILDER** |\n"
        "| **Plan ID** | WT-2026-221b |\n",
        encoding="utf-8",
    )
    (collab_dir / "STATE.md").write_text(
        "# STATE.md\n\nACTIVE_TICKET: WT-2026-221b\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )
    (collab_dir / "execution_log.md").write_text(
        "# Execution Log\n\n**Estado:** IN_PROGRESS\n\n"
        "- WT-2026-221b: implementation started\n",
        encoding="utf-8",
    )
    # Emit a STATE_CHANGED event so the bus has ticket state
    event_bus.emit(
        "STATE_CHANGED",
        ticket_id="WT-2026-221b",
        actor="BUILDER",
        payload={"from_state": "BOOTSTRAP", "to_state": "IN_PROGRESS"},
    )
    return ReviewBridge(event_bus=event_bus, project_root=tmp_path)


# ---------------------------------------------------------------------------
# Helper: mock git subprocess.run to return controlled file lists
# ---------------------------------------------------------------------------


def _mock_git_diff(files: list[str], returncode: int = 0) -> MagicMock:
    """Create a subprocess.run mock returning a git diff --name-only output."""
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = "\n".join(files) + ("\n" if files else "")
    mock.stderr = ""
    return mock


def _make_diff_side_effect(
    motor_files: list[str],
    destination_files: list[str],
) -> callable:
    """Create a side_effect for subprocess.run that returns different results
    based on the cwd kwarg.

    Motor repo queries use cwd=<tmp_path>/motor (controlled path).
    Destination repo queries use any other cwd.
    """

    def side_effect(cmd, *args, **kwargs):
        cwd = kwargs.get("cwd", "")
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "diff --name-only" in cmd_str and str(cwd).endswith("motor"):
            if motor_files:
                return _mock_git_diff(motor_files)
            # Fallback to log when diff is empty
            return _mock_git_diff([])
        if "diff --name-only" in cmd_str:
            if destination_files:
                return _mock_git_diff(destination_files)
            # Fallback to log when diff is empty
            return _mock_git_diff([])
        if "log -5 --name-only" in cmd_str and str(cwd).endswith("motor"):
            if motor_files and not any("diff" in c for c in [cmd_str]):
                pass
            return _mock_git_diff(motor_files)
        if "log -5 --name-only" in cmd_str:
            return _mock_git_diff(destination_files)
        return _mock_git_diff([])

    return side_effect


# ---------------------------------------------------------------------------
# Tests: classify_review_packet
# ---------------------------------------------------------------------------


class TestClassifyReviewPacket:
    """Tests for ReviewBridge.classify_review_packet()."""

    def test_classify_docs_only_diff(self, review_bridge, monkeypatch):
        """TP-03 / seq-602/606/617: docs-only diff is classified as docs_only."""
        monkeypatch.setattr(
            review_bridge,
            "_resolve_motor_root",
            lambda: None,  # No motor root → no motor evidence
        )
        monkeypatch.setattr(
            review_bridge,
            "_get_motor_diff_files",
            lambda: [],
        )

        # Mock project_root git diff to return docs-only files
        git_mock = _mock_git_diff(
            [
                ".agent/collaboration/work_plan.md",
                ".agent/collaboration/execution_log.md",
                "PROJECT.md",
            ]
        )

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "diff --name-only" in cmd_str or "log -5 --name-only" in cmd_str:
                return git_mock
            return _mock_git_diff([])

        monkeypatch.setattr(review_bridge, "_resolve_motor_root", lambda: None)
        monkeypatch.setattr("bus.review_bridge.subprocess.run", mock_run)

        result = review_bridge.classify_review_packet("WT-2026-221b")

        assert result["is_docs_only"] is True, f"Expected docs_only=True, got: {result}"
        assert result["reason"], "Expected non-empty rejection reason"
        assert "no productive" in result["reason"].lower(), (
            f"Reason should mention no productive evidence: {result['reason']}"
        )
        # Note: PROJECT.md is docs-only but not collaboration-only pattern,
        # so is_collaboration_only is False for this mixed docs set.
        # A pure collaboration-only test covers the collab classification.

    def test_classify_collaboration_only_diff(self, review_bridge, monkeypatch):
        """TP-03: collaboration-only files → is_collaboration_only=True."""
        monkeypatch.setattr(
            review_bridge,
            "_resolve_motor_root",
            lambda: None,
        )
        monkeypatch.setattr(
            review_bridge,
            "_get_motor_diff_files",
            lambda: [],
        )

        # Mock git to return only collaboration files
        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "diff --name-only" in cmd_str or "log -5 --name-only" in cmd_str:
                return _mock_git_diff(
                    [
                        ".agent/collaboration/TURN.md",
                        ".agent/collaboration/STATE.md",
                        ".agent/runtime/events/events.jsonl",
                    ]
                )
            return _mock_git_diff([])

        monkeypatch.setattr("bus.review_bridge.subprocess.run", mock_run)

        result = review_bridge.classify_review_packet("WT-2026-221b")

        assert result["is_collaboration_only"] is True
        assert result["is_docs_only"] is True
        assert result["has_motor_evidence"] is False

    def test_accepts_motor_evidence(self, review_bridge, monkeypatch):
        """TP-04: review with motor productive evidence passes the gate."""
        monkeypatch.setattr(
            review_bridge,
            "_resolve_motor_root",
            lambda: Path("/fake/motor"),
        )
        monkeypatch.setattr(
            review_bridge,
            "_get_motor_diff_files",
            lambda: [
                "bus/review_bridge.py",
                "tests/test_wt_2026_221b_evidence_gate.py",
            ],
        )

        # Mock git diff for destination (may also have collaboration changes)
        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "diff --name-only" in cmd_str or "log -5 --name-only" in cmd_str:
                return _mock_git_diff(
                    [
                        ".agent/collaboration/execution_log.md",
                    ]
                )
            return _mock_git_diff([])

        monkeypatch.setattr("bus.review_bridge.subprocess.run", mock_run)

        result = review_bridge.classify_review_packet("WT-2026-221b")

        assert result["is_docs_only"] is False, f"Expected not docs_only, got: {result}"
        assert result["has_motor_evidence"] is True, (
            f"Expected motor evidence, got: {result}"
        )
        assert result["productive_files"], f"Expected productive files, got: {result}"
        assert "bus/review_bridge.py" in result["productive_files"]

    def test_empty_diff_returns_is_empty(self, review_bridge, monkeypatch):
        """TP-01: Empty diff (no files in either repo) → is_empty=True."""
        monkeypatch.setattr(
            review_bridge,
            "_resolve_motor_root",
            lambda: None,
        )
        monkeypatch.setattr(
            review_bridge,
            "_get_motor_diff_files",
            lambda: [],
        )

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "diff --name-only" in cmd_str:
                return _mock_git_diff([])
            if "log -5 --name-only" in cmd_str:
                return _mock_git_diff([])
            return _mock_git_diff([])

        monkeypatch.setattr("bus.review_bridge.subprocess.run", mock_run)

        result = review_bridge.classify_review_packet("WT-2026-221b")

        assert result["is_empty"] is True
        assert result["reason"], "Expected rejection reason for empty diff"
        assert "no diff" in result["reason"].lower()

    def test_classify_returns_structured_reason(self, review_bridge, monkeypatch):
        """TP-06: classification returns structured, actionable reason."""
        monkeypatch.setattr(
            review_bridge,
            "_resolve_motor_root",
            lambda: None,
        )
        monkeypatch.setattr(
            review_bridge,
            "_get_motor_diff_files",
            lambda: [],
        )

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "diff --name-only" in cmd_str or "log -5 --name-only" in cmd_str:
                return _mock_git_diff(
                    [
                        ".agent/collaboration/execution_log.md",
                    ]
                )
            return _mock_git_diff([])

        monkeypatch.setattr("bus.review_bridge.subprocess.run", mock_run)

        result = review_bridge.classify_review_packet("WT-2026-221b")

        assert "reason" in result
        reason = result["reason"]
        assert len(reason) > 20, f"Reason too short: {reason}"
        # Reason should mention ticket ID
        assert "WT-2026-221b" in reason

    def test_bus_inactive_returns_no_bus(self, review_bridge, monkeypatch):
        """TP-02: No bus/state activity returns bus_active=False."""
        monkeypatch.setattr(
            review_bridge.state_ingest,
            "get_ticket_context",
            lambda tid: None,
        )

        result = review_bridge.classify_review_packet("WT-2026-221b")

        assert result["bus_active"] is False
        assert result["reason"], "Expected reason for missing bus context"

    def test_path_matches_any_utility(self):
        """_path_matches_any correctly matches patterns."""
        assert (
            ReviewBridge._path_matches_any(
                ".agent/collaboration/work_plan.md",
                (".agent/collaboration/", ".agent/runtime/"),
            )
            is True
        )
        assert (
            ReviewBridge._path_matches_any(
                "foo.py",
                (".agent/collaboration/", ".agent/runtime/"),
            )
            is False
        )
        assert (
            ReviewBridge._path_matches_any(
                ".agent/runtime/events/events.jsonl",
                (".agent/collaboration/", ".agent/runtime/"),
            )
            is True
        )


# ---------------------------------------------------------------------------
# Tests: run_manager_review_cycle evidence gate
# ---------------------------------------------------------------------------


class TestRunManagerReviewCycleEvidenceGate:
    """The evidence gate in run_manager_review_cycle rejects docs-only packets."""

    def test_evidence_gate_rejects_docs_only(self, review_bridge, monkeypatch):
        """TP-03: run_manager_review_cycle returns CHANGES for docs-only."""
        # Emit READY_FOR_REVIEW so the initial state check passes
        review_bridge.event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WT-2026-221b",
            actor="BUILDER",
            payload={
                "from_state": "IN_PROGRESS",
                "to_state": "READY_FOR_REVIEW",
                "reason": "Test setup",
                "source": "test",
            },
        )

        # Mock the evidence gate to return docs_only
        monkeypatch.setattr(
            review_bridge,
            "classify_review_packet",
            lambda tid: {
                "is_docs_only": True,
                "is_collaboration_only": True,
                "has_motor_evidence": False,
                "reason": "WT-2026-221b: all changes are collaboration-only artifacts (3 files). No productive evidence from motor or destination repository.",
                "docs_only_files": [".agent/collaboration/TURN.md"],
                "motor_diff_files": [],
                "destination_diff_files": [],
                "productive_files": [],
                "bus_active": True,
            },
        )

        # Mock the supervisor object for _ensure_durable_changes_consumer
        supervisor = MagicMock()
        supervisor._is_supervisor_lock_stale.return_value = False

        result = review_bridge.run_manager_review_cycle(
            ticket_id="WT-2026-221b",
            supervisor=supervisor,
        )

        assert result.decision == ReviewDecision.CHANGES, (
            f"Expected CHANGES for docs-only, got: {result.decision}"
        )
        assert result.exit_code == 1
        assert (
            "collaboration-only" in result.feedback.lower()
            or "productive" in result.feedback.lower()
        ), (
            f"Feedback should mention collaboration-only or productive: {result.feedback}"
        )

    def test_evidence_gate_passes_with_motor_evidence(self, review_bridge, monkeypatch):
        """TP-04: review proceeds when motor evidence exists."""
        # Mock the evidence gate to return productive motor evidence
        monkeypatch.setattr(
            review_bridge,
            "classify_review_packet",
            lambda tid: {
                "is_docs_only": False,
                "is_collaboration_only": False,
                "has_motor_evidence": True,
                "has_destination_productive": False,
                "reason": "WT-2026-221b: has motor evidence (2 productive files).",
                "docs_only_files": [],
                "motor_diff_files": ["bus/review_bridge.py", "tests/test_evidence.py"],
                "destination_diff_files": [],
                "productive_files": ["bus/review_bridge.py", "tests/test_evidence.py"],
                "bus_active": True,
            },
        )

        # Mock the rest of the review cycle to avoid actual subprocess calls
        monkeypatch.setattr(
            review_bridge,
            "_get_current_role",
            lambda: "MANAGER",
        )
        monkeypatch.setattr(
            review_bridge.state_ingest,
            "_read_deliverable_type",
            lambda: "code",
        )
        monkeypatch.setattr(
            review_bridge,
            "_get_manager_backend",
            lambda: "opencode",
        )
        monkeypatch.setattr(
            review_bridge,
            "_run_opencode_review",
            lambda **kw: ("DECISION: APPROVE\n", "", 0),
        )
        monkeypatch.setattr(
            review_bridge,
            "_detect_json_format_support",
            lambda: False,
        )
        monkeypatch.setattr(
            review_bridge,
            "_get_manager_model",
            lambda: None,
        )
        monkeypatch.setattr(
            review_bridge,
            "_ensure_repomix_context",
            lambda timeout=15: None,
        )
        monkeypatch.setattr(
            review_bridge,
            "_load_review_config",
            lambda: {
                "timeout_seconds": 30,
                "max_attempts": 2,
                "retry_backoff_multiplier": 1.0,
            },
        )
        monkeypatch.setattr(
            review_bridge,
            "_count_prior_changes_from_bus",
            lambda tid: 0,
        )

        supervisor = MagicMock()
        supervisor._is_supervisor_lock_stale.return_value = False
        supervisor.transition_ticket = MagicMock()

        result = review_bridge.run_manager_review_cycle(
            ticket_id="WT-2026-221b",
            supervisor=supervisor,
        )

        # Should proceed past the gate and try the review
        assert result.decision in (ReviewDecision.APPROVE, ReviewDecision.INSPECT), (
            f"Expected review to proceed, got: {result.decision}"
        )


# ---------------------------------------------------------------------------
# Tests: get_motor_diff_files
# ---------------------------------------------------------------------------


class TestGetMotorDiffFiles:
    """Tests for ReviewBridge._get_motor_diff_files()."""

    def test_no_motor_root_returns_empty(self, review_bridge, monkeypatch):
        """When motor root is None, returns empty list."""
        monkeypatch.setattr(
            review_bridge,
            "_resolve_motor_root",
            lambda: None,
        )
        result = review_bridge._get_motor_diff_files()
        assert result == []

    def test_no_diff_in_motor_returns_empty(self, review_bridge, monkeypatch):
        """When motor has no diff, returns empty list."""
        motor_root = Path("/fake/motor")
        monkeypatch.setattr(
            review_bridge,
            "_resolve_motor_root",
            lambda: motor_root,
        )

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "diff --name-only" in cmd_str:
                return _mock_git_diff([])
            if "diff --cached --name-only" in cmd_str:
                return _mock_git_diff([])
            if "log -5 --name-only" in cmd_str:
                return _mock_git_diff([])
            return _mock_git_diff([])

        monkeypatch.setattr("bus.review_bridge.subprocess.run", mock_run)
        result = review_bridge._get_motor_diff_files()
        assert result == []

    def test_unstaged_motor_diff_returns_files(self, review_bridge, monkeypatch):
        """Unstaged diff in motor returns file list."""
        motor_root = Path("/fake/motor")
        monkeypatch.setattr(
            review_bridge,
            "_resolve_motor_root",
            lambda: motor_root,
        )

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "diff --name-only" in cmd_str and "cached" not in cmd_str:
                return _mock_git_diff(
                    ["bus/review_bridge.py", "tests/test_evidence.py"]
                )
            return _mock_git_diff([])

        monkeypatch.setattr("bus.review_bridge.subprocess.run", mock_run)
        result = review_bridge._get_motor_diff_files()
        assert "bus/review_bridge.py" in result
        assert "tests/test_evidence.py" in result
