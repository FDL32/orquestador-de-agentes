"""WT-2026-221b: Manager evidence gate tests.

Tests the binary evidence barrier that rejects docs-only/collaboration-only
review packets before they reach the Manager.

Reproduces the failure family seq 602/606/617 where the Manager rejected
reviews with no productive evidence visible from the motor repository.
"""

# ruff: noqa: ERA001

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bus.event_bus import EventBus
from bus.evidence import (
    _own_git_root,
    motor_uncommitted_productive,
    resolve_evidence,
)
from bus.review_bridge import ReviewBridge, ReviewDecision

from tests.test_pre_handoff_guard import init_git_repo


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

    WOT-2026-020r: project_root must be a REAL repo root, because that is what the
    production call site passes. Without its own .git it is not a repo at all, and
    resolve_evidence now drops it rather than let git walk UP and answer for the
    enclosing motor repo. The tests below mock git's OUTPUT; the .git makes the
    fixture faithful to the shape git is asked about.
    """
    init_git_repo(tmp_path)
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
        """TP-04: review with motor productive evidence passes the gate.

        Clase C fix (WT-2026-227a): classify_review_packet delegates to
        bus.evidence.resolve_evidence, not _get_motor_diff_files. The original
        mock had no effect, allowing the real working tree to leak into the
        classification. Fix: mock resolve_evidence directly with a realistic
        productive result to keep the fixture honest without escaping to the
        real tree.
        """
        motor_files = [
            "bus/review_bridge.py",
            "tests/test_review_packet_evidence_gate.py",
        ]
        monkeypatch.setattr(
            "bus.evidence.resolve_evidence",
            lambda motor_root, project_root, ticket_id=None: {
                "motor_files": motor_files,
                "destination_files": [],
                "all_files": motor_files,
                "docs_only_files": [],
                "productive_files": motor_files,
                "is_docs_only": False,
                "is_collaboration_only": False,
                "motor_productive": motor_files,
                "dest_productive": [],
                "has_motor_evidence": True,
                "has_destination_productive": False,
                "has_productive_evidence": True,
                "has_ticket_commit": True,
                "sources_used": ["working_tree"],
            },
        )

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
# Tests: run_manager_review_cycle evidence gate (unit)
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
            "_get_manager_model",
            lambda: None,
        )
        monkeypatch.setattr(
            review_bridge,
            "_ensure_repomix_context",
            lambda timeout=15: (
                None,
                {"status": "skipped", "reason": "mocked for tests"},
            ),
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


# ---------------------------------------------------------------------------
# Integration tests: run_manager_review_cycle with real classify_review_packet
# ---------------------------------------------------------------------------


class TestReviewCycleEvidenceGateIntegration:
    """End-to-end evidence gate tests using real classify_review_packet().

    These tests do NOT mock classify_review_packet(). Instead, they mock
    subprocess.run at the git level to control what files appear in diffs,
    exercising the full classification -> gate rejection pipeline.
    """

    def _handle_name_only_query(self, files: list[str]) -> MagicMock | None:
        """Handle git diff --name-only queries for a repo."""
        if files is None:
            return None
        m = MagicMock()
        m.returncode = 0
        m.stdout = "\n".join(files) + ("\n" if files else "")
        m.stderr = ""
        return m

    def _mock_result(self, stdout: str = "") -> MagicMock:
        """Create a MagicMock subprocess result with given stdout."""
        m = MagicMock()
        m.returncode = 0
        m.stdout = stdout
        m.stderr = ""
        return m

    def _make_side_effect(self, destination_files, motor_files):  # noqa: C901
        """Create subprocess.run side_effect returning controlled git output."""

        def side_effect(cmd, *args, **kwargs):  # noqa: C901
            cwd = kwargs.get("cwd", "")
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            is_motor = motor_files is not None and str(cwd).endswith("motor")
            is_dest = destination_files is not None and not str(cwd).endswith("motor")

            if is_motor:
                if "diff --name-only" in cmd_str and "cached" not in cmd_str:
                    return self._handle_name_only_query(motor_files)
                if (
                    "diff --cached --name-only" in cmd_str
                    or "log -5 --name-only" in cmd_str
                ):
                    return self._mock_result()

            if is_dest:
                if "diff --name-only" in cmd_str and "cached" not in cmd_str:
                    return self._handle_name_only_query(destination_files)
                if (
                    "diff --cached --name-only" in cmd_str
                    or "log -5 --name-only" in cmd_str
                ):
                    return self._mock_result()
                # diff --stat
                if "diff --stat" in cmd_str:
                    return self._mock_result(
                        " 10 files changed, 200 insertions(+)\n"
                        if destination_files
                        else ""
                    )
                # diff (content)
                if (
                    "--name-only" not in cmd_str
                    and "--stat" not in cmd_str
                    and "diff " in cmd_str
                ):
                    return self._mock_result(
                        "\n".join(
                            f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n-test\n+change"
                            for f in (destination_files or [])
                        )
                    )
                # git rev-parse / merge-base
                if "rev-parse" in cmd_str:
                    return self._mock_result("HEAD")
                if "merge-base" in cmd_str:
                    return self._mock_result("BASE")
                # git log --oneline
                if "git log" in cmd_str and "--oneline" in cmd_str:
                    return self._mock_result()

            return self._mock_result()

        return side_effect

    def test_integration_gate_rejects_collaboration_only(
        self, review_bridge, monkeypatch
    ):
        """TP-03/TP-05: Real classify_review_packet rejects collaboration-only.

        Reproduces seq 602/606/617 where only .agent/collaboration/ files
        were changed. The evidence gate in run_manager_review_cycle must
        return CHANGES before building the review prompt.
        """
        # Emit READY_FOR_REVIEW state
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

        # No motor root
        monkeypatch.setattr(review_bridge, "_resolve_motor_root", lambda: None)

        # Mock subprocess.run to return only collaboration files from destination
        monkeypatch.setattr(
            "bus.review_bridge.subprocess.run",
            self._make_side_effect(
                destination_files=[
                    ".agent/collaboration/work_plan.md",
                    ".agent/collaboration/execution_log.md",
                    ".agent/collaboration/TURN.md",
                ],
                motor_files=[],
            ),
        )

        supervisor = MagicMock()
        supervisor._is_supervisor_lock_stale.return_value = False

        result = review_bridge.run_manager_review_cycle(
            ticket_id="WT-2026-221b",
            supervisor=supervisor,
        )

        assert result.decision == ReviewDecision.CHANGES, (
            f"Expected CHANGES for collaboration-only, got: {result.decision}"
        )
        assert result.exit_code == 1
        assert (
            "collaboration-only" in result.feedback.lower()
            or "productive" in result.feedback.lower()
        ), (
            f"Feedback should mention collaboration-only or productive: {result.feedback}"
        )

    def test_integration_gate_passes_with_motor_evidence(
        self, review_bridge, monkeypatch, tmp_path
    ):
        """TP-04: Real classify_review_packet passes when motor has productive files."""
        # Emit READY_FOR_REVIEW state
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

        # Mock motor root to exist.
        # WOT-2026-020r: it must be a REAL repo root. resolve_evidence now drops any
        # root without its own .git (such a root makes git walk UP and answer for the
        # enclosing repo). Path("/fake/motor") is not a repo, so the motor block would
        # be skipped and this test would assert the gate's rejection path by accident.
        # The dir name still ends in "motor" -- _make_side_effect routes on that.
        fake_motor = tmp_path / "motor"
        init_git_repo(fake_motor)
        monkeypatch.setattr(
            review_bridge,
            "_resolve_motor_root",
            lambda: fake_motor,
        )

        # Mock subprocess.run: motor has productive files, destination has collab files
        monkeypatch.setattr(
            "bus.review_bridge.subprocess.run",
            self._make_side_effect(
                destination_files=[
                    ".agent/collaboration/execution_log.md",
                ],
                motor_files=[
                    "bus/review_bridge.py",
                    "tests/test_review_packet_evidence_gate.py",
                ],
            ),
        )

        # Mock downstream review calls to avoid actual execution
        monkeypatch.setattr(review_bridge, "_get_current_role", lambda: "MANAGER")
        monkeypatch.setattr(
            review_bridge.state_ingest, "_read_deliverable_type", lambda: "code"
        )
        monkeypatch.setattr(review_bridge, "_get_manager_backend", lambda: "opencode")
        monkeypatch.setattr(
            review_bridge,
            "_run_opencode_review",
            lambda **kw: ("DECISION: APPROVE\n", "", 0),
        )
        monkeypatch.setattr(review_bridge, "_get_manager_model", lambda: None)
        monkeypatch.setattr(
            review_bridge,
            "_ensure_repomix_context",
            lambda timeout=15: (
                None,
                {"status": "skipped", "reason": "mocked for tests"},
            ),
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
            review_bridge, "_count_prior_changes_from_bus", lambda tid: 0
        )

        supervisor = MagicMock()
        supervisor._is_supervisor_lock_stale.return_value = False
        supervisor.transition_ticket = MagicMock()

        result = review_bridge.run_manager_review_cycle(
            ticket_id="WT-2026-221b",
            supervisor=supervisor,
        )

        # Should proceed past the evidence gate to the actual review
        assert result.decision in (
            ReviewDecision.APPROVE,
            ReviewDecision.INSPECT,
        ), f"Expected review to proceed, got: {result.decision}"

    def test_integration_gate_rejects_no_bus(self, review_bridge, monkeypatch):
        """TP-02: classify_review_packet returns bus_active=False when no state."""
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

        # Mock get_ticket_context to return None (simulates no bus/state context)
        monkeypatch.setattr(
            review_bridge.state_ingest,
            "get_ticket_context",
            lambda tid: None,
        )

        # Mock subprocess to avoid any real execution
        monkeypatch.setattr(
            "bus.review_bridge.subprocess.run",
            self._make_side_effect(
                destination_files=[".agent/collaboration/work_plan.md"],
                motor_files=[],
            ),
        )

        # Even with files, the bus context check should fail first
        result = review_bridge.run_manager_review_cycle(
            ticket_id="WT-2026-221b",
            supervisor=MagicMock(),
        )

        assert result.decision == ReviewDecision.CHANGES, (
            f"Expected CHANGES when bus inactive, got: {result.decision}"
        )
        assert result.exit_code == 1


class TestClassifyReviewPacketRealRepos:
    """Sentinel tests with real git repos and no subprocess.run mock.

    These cover the residual risk from broad subprocess mocking by exercising
    classify_review_packet() against actual git state in motor + destination.
    """

    @staticmethod
    def _build_real_bridge(tmp_path: Path) -> tuple[ReviewBridge, Path, Path]:
        motor = tmp_path / "motor"
        dest = tmp_path / "dest"
        init_git_repo(motor)
        init_git_repo(dest)

        collab_dir = dest / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
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

        event_bus = EventBus(runtime_dir=dest / ".agent" / "runtime" / "events")
        event_bus.emit(
            "STATE_CHANGED",
            ticket_id="WT-2026-221b",
            actor="BUILDER",
            payload={"from_state": "BOOTSTRAP", "to_state": "IN_PROGRESS"},
        )

        bridge = ReviewBridge(event_bus=event_bus, project_root=dest)
        bridge._resolve_motor_root = lambda: motor
        return bridge, motor, dest

    def test_classify_docs_only_real_repos(self, tmp_path: Path) -> None:
        """Docs-only destination changes are rejected using real git repos."""
        bridge, _motor, dest = self._build_real_bridge(tmp_path)

        project_md = dest / "PROJECT.md"
        project_md.write_text("# Project\nbaseline\n", encoding="utf-8")
        subprocess.run(["git", "add", "PROJECT.md"], cwd=dest, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Add PROJECT.md"],
            cwd=dest,
            check=True,
        )
        project_md.write_text("# Project\nupdated\n", encoding="utf-8")

        result = bridge.classify_review_packet("WT-2026-221b")

        assert result["bus_active"] is True
        assert result["is_empty"] is False
        assert result["is_docs_only"] is True
        assert result["has_motor_evidence"] is False
        assert "PROJECT.md" in result["docs_only_files"]

    def test_classify_motor_evidence_real_repos(self, tmp_path: Path) -> None:
        """Motor productive commit is accepted using real git repos."""
        bridge, motor, _dest = self._build_real_bridge(tmp_path)

        productive = motor / "bus" / "review_bridge.py"
        productive.parent.mkdir(parents=True, exist_ok=True)
        productive.write_text("def sentinel():\n    return 'ok'\n", encoding="utf-8")
        subprocess.run(["git", "add", "bus/review_bridge.py"], cwd=motor, check=True)
        subprocess.run(
            ["git", "commit", "-m", "WT-2026-221b: add productive evidence"],
            cwd=motor,
            check=True,
        )

        result = bridge.classify_review_packet("WT-2026-221b")

        assert result["bus_active"] is True
        assert result["is_empty"] is False
        assert result["is_docs_only"] is False
        assert result["has_motor_evidence"] is True
        assert "bus/review_bridge.py" in result["motor_diff_files"]


# ---------------------------------------------------------------------------
# Tests: check_review_packet_diff_empty (updated with classify_review_packet)
# ---------------------------------------------------------------------------


class TestCheckReviewPacketDiffEmpty:
    """Tests for the updated check_review_packet_diff_empty with classify_review_packet."""

    def test_empty_diff_returns_true(self, review_bridge, monkeypatch):
        """Empty diff returns True from check_review_packet_diff_empty."""
        monkeypatch.setattr(review_bridge, "_resolve_motor_root", lambda: None)

        def mock_run(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        monkeypatch.setattr("bus.review_bridge.subprocess.run", mock_run)

        result = review_bridge.check_review_packet_diff_empty("WT-2026-221b")
        assert result is True, "Expected True for empty diff"

    def test_docs_only_returns_true(self, review_bridge, monkeypatch):
        """Docs-only diff returns True because classify_review_packet detects it."""
        monkeypatch.setattr(review_bridge, "_resolve_motor_root", lambda: None)

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            m = MagicMock()
            m.returncode = 0
            if "diff --stat" in cmd_str:
                m.stdout = " 1 file changed\n"
            elif "diff --name-only" in cmd_str or "log -5 --name-only" in cmd_str:
                m.stdout = ".agent/collaboration/work_plan.md\n"
            else:
                m.stdout = ""
            m.stderr = ""
            return m

        monkeypatch.setattr("bus.review_bridge.subprocess.run", mock_run)

        result = review_bridge.check_review_packet_diff_empty("WT-2026-221b")
        assert result is True, "Expected True for docs-only diff"


# ---------------------------------------------------------------------------
# WOT-2026-020r: the evidence gate must not read the REAL git tree
# ---------------------------------------------------------------------------


class TestEvidenceHermeticity020r:
    """resolve_evidence() must ignore roots that carry no .git of their own.

    Git resolves a repo by walking UP from cwd. `tmp_path` lands INSIDE this repo
    (tests/sandbox/test_runtime/), so a root without its own .git answers for the
    REAL repo: the gate reports whatever the developer's tree happens to contain.
    A single dirty file in .agent/collaboration/ turned 6 bridge tests red while
    the code under test was untouched.

    These tests bite on a CLEAN tree: `git log -10 --name-only` walks up whether or
    not anything is dirty, so they do not depend on -- and never create -- tree dirt.
    """

    def test_resolve_evidence_ignores_roots_without_own_git(self, tmp_path):
        """Both roots. project_root is the one that actually carried the dirt:
        _resolve_motor_root() returns None under tmp_path, so the motor block never
        ran and the real tree entered through project_root."""
        ev = resolve_evidence(tmp_path, tmp_path)

        assert ev["motor_files"] == [], (
            "motor_root without .git leaked the real repo's files: "
            f"{ev['motor_files'][:5]}"
        )
        assert ev["destination_files"] == [], (
            "project_root without .git leaked the real repo's files: "
            f"{ev['destination_files'][:5]}"
        )
        assert ev["all_files"] == []

    def test_resolve_evidence_finds_no_ticket_commit_from_rootless_dir(self, tmp_path):
        """The `git log --oneline -20` probe walks up too, and it runs BEFORE the
        diffs -- guarding only the diff calls would leave this one lying.

        This must NOT lean on the enclosing repo's history: an id that happens to be
        absent from the last 20 real commits yields has_ticket_commit=False with or
        without the guard, and the test passes for the wrong reason (it did, until a
        mutation exposed it). So build the walk-up ourselves: a real repo whose commit
        message carries TICKET, queried from a subdirectory with no .git of its own.
        Unguarded, git walks up and FINDS it -- which is precisely the leak.
        """
        ticket = "WOT-2026-020r"
        repo = tmp_path / "enclosing_repo"
        init_git_repo(repo)
        (repo / "impl.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"{ticket}: landed"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        nested = repo / "sandbox" / "run"
        nested.mkdir(parents=True)
        assert not (nested / ".git").exists()

        ev = resolve_evidence(nested, nested, ticket)

        assert ev["has_ticket_commit"] is False, (
            "has_ticket_commit walked UP into the enclosing repo's history"
        )
        assert ev["all_files"] == []

    def test_resolve_evidence_still_reads_a_genuine_repo(self, tmp_path):
        """Positive control: the guard must not degrade into 'always empty'.

        Without this, `return []` would satisfy the two tests above.
        """
        repo = tmp_path / "real_repo"
        init_git_repo(repo)
        (repo / "module.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)

        ev = resolve_evidence(repo, repo)

        assert "module.py" in ev["motor_files"], (
            f"a real repo must still be read; got {ev['motor_files']}"
        )
        assert ev["has_productive_evidence"] is True

    def test_own_git_root_accepts_a_worktree_dotgit_file(self, tmp_path):
        """In a linked worktree `.git` is a FILE, not a directory -- and `_dev`, where
        this suite runs, is one. An is_dir() predicate would reject the real motor."""
        worktree = tmp_path / "linked_worktree"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: /somewhere/.git/worktrees/wt\n")

        assert _own_git_root(worktree) == worktree

    def test_own_git_root_rejects_dir_without_git(self, tmp_path):
        assert _own_git_root(tmp_path) is None
        assert _own_git_root(None) is None

    def test_own_git_root_tolerates_a_falsy_root(self):
        """The code this replaced read `if not motor_root or not (...).exists()`, so a
        falsy root returned [] rather than raising. Guarding on `root is None` dropped
        that branch: `"" / ".git"` raises TypeError. Unreachable via today's callers
        (all pass Path|None), but it is behaviour that was removed by accident.

        Caught by an adversarial audit of the 020r commit, not by this suite.
        """
        assert _own_git_root("") is None
        assert motor_uncommitted_productive("") == []
