"""Tests for completion_common.py - LÃ³gica compartida de completitud.

Suite sin acceso a filesystem: usa mocks puros sobre Path.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

import completion_common as cc  # noqa: E402


class TestGetLogStatus:
    def test_returns_empty_when_file_missing(self):
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        assert cc.get_log_status(mock_path) == ""

    def test_extracts_status_from_log(self):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "# Log\n\n- **Estado:** READY_FOR_REVIEW\n"
        assert cc.get_log_status(mock_path) == "READY_FOR_REVIEW"

    def test_uppercases_status(self):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "- **Estado:** in_progress\n"
        assert cc.get_log_status(mock_path) == "IN_PROGRESS"

    def test_returns_empty_on_read_error(self):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = PermissionError
        assert cc.get_log_status(mock_path) == ""


class TestIsRelaxedCompletionStatus:
    def test_ready_for_review_is_relaxed(self):
        assert cc.is_relaxed_completion_status("READY_FOR_REVIEW") is True

    def test_completed_is_relaxed(self):
        assert cc.is_relaxed_completion_status("COMPLETED") is True

    def test_in_progress_is_not_relaxed(self):
        assert cc.is_relaxed_completion_status("IN_PROGRESS") is False

    def test_empty_is_not_relaxed(self):
        assert cc.is_relaxed_completion_status("") is False


class TestCheckTasksCompleted:
    def test_relaxed_when_ready_for_review(self):
        mock_plan = MagicMock()
        assert cc.check_tasks_completed(mock_plan, "READY_FOR_REVIEW") is True
        mock_plan.exists.assert_not_called()

    def test_relaxed_when_completed(self):
        mock_plan = MagicMock()
        assert cc.check_tasks_completed(mock_plan, "COMPLETED") is True

    def test_false_when_plan_missing(self):
        mock_plan = MagicMock()
        mock_plan.exists.return_value = False
        assert cc.check_tasks_completed(mock_plan, "IN_PROGRESS") is False

    def test_true_when_all_tasks_done(self):
        mock_plan = MagicMock()
        mock_plan.exists.return_value = True
        mock_plan.read_text.return_value = "- [x] T1\n- [x] T2\n"
        assert cc.check_tasks_completed(mock_plan, "IN_PROGRESS") is True

    def test_false_when_pending_tasks(self):
        mock_plan = MagicMock()
        mock_plan.exists.return_value = True
        mock_plan.read_text.return_value = "- [x] T1\n- [ ] T2\n"
        assert cc.check_tasks_completed(mock_plan, "IN_PROGRESS") is False


class TestCheckExecutionSummary:
    def test_false_when_log_missing(self):
        mock_log = MagicMock()
        mock_log.exists.return_value = False
        assert cc.check_execution_summary(mock_log, "IN_PROGRESS") is False

    def test_relaxed_when_ready_for_review(self):
        mock_log = MagicMock()
        mock_log.exists.return_value = True
        assert cc.check_execution_summary(mock_log, "READY_FOR_REVIEW") is True
        mock_log.read_text.assert_not_called()

    def test_relaxed_when_completed(self):
        mock_log = MagicMock()
        mock_log.exists.return_value = True
        assert cc.check_execution_summary(mock_log, "COMPLETED") is True

    def test_true_when_has_summary_and_not_in_progress(self):
        mock_log = MagicMock()
        mock_log.exists.return_value = True
        mock_log.read_text.return_value = "## Resumen Final\n"
        assert cc.check_execution_summary(mock_log, "PENDING") is True

    def test_false_when_in_progress_present(self):
        mock_log = MagicMock()
        mock_log.exists.return_value = True
        mock_log.read_text.return_value = "## Resumen\n- **Estado:** IN_PROGRESS\n"
        assert cc.check_execution_summary(mock_log, "PENDING") is False

    def test_false_when_no_summary(self):
        mock_log = MagicMock()
        mock_log.exists.return_value = True
        mock_log.read_text.return_value = "# Log\n"
        assert cc.check_execution_summary(mock_log, "PENDING") is False


class TestCheckNoEscalations:
    def test_true_when_queue_missing(self):
        mock_queue = MagicMock()
        mock_queue.exists.return_value = False
        assert cc.check_no_escalations(mock_queue) is True

    def test_true_when_no_markers(self):
        mock_queue = MagicMock()
        mock_queue.exists.return_value = True
        mock_queue.read_text.return_value = "# Queue\nTodo resuelto\n"
        assert cc.check_no_escalations(mock_queue) is True

    def test_false_when_pending(self):
        mock_queue = MagicMock()
        mock_queue.exists.return_value = True
        mock_queue.read_text.return_value = "### ESC-001\n**Estado:** PENDING\n"
        assert cc.check_no_escalations(mock_queue) is False

    def test_false_when_blocked(self):
        mock_queue = MagicMock()
        mock_queue.exists.return_value = True
        mock_queue.read_text.return_value = "### ESC-002\n**Estado:** BLOCKED\n"
        assert cc.check_no_escalations(mock_queue) is False


class TestResolveTestCommand:
    def test_empty_when_no_tests_dir(self):
        with patch.object(Path, "exists", return_value=False):
            result = cc.resolve_test_command(Path("/fake"))
        assert result == []

    def test_uses_safe_runner_when_exists(self):
        fake_root = Path("/fake")
        tests_dir = fake_root / "tests"
        runner = fake_root / "scripts" / "run_pytest_safe.py"

        def _exists_side_effect(self):
            return self in (tests_dir, runner)

        with patch.object(Path, "exists", _exists_side_effect):
            cmd = cc.resolve_test_command(fake_root)

        assert cmd[0] == sys.executable
        assert cmd[1].endswith("run_pytest_safe.py")
        assert "--level" in cmd
        assert "unit" in cmd

    def test_fallback_to_pytest(self):
        fake_root = Path("/fake")
        tests_dir = fake_root / "tests"

        def _exists_side_effect(self):
            return self == tests_dir

        with patch.object(Path, "exists", _exists_side_effect):
            cmd = cc.resolve_test_command(fake_root)

        assert cmd[0] == sys.executable
        assert cmd[1] == "-m"
        assert cmd[2] == "pytest"


class TestRunTests:
    def test_true_when_no_tests(self):
        with patch.object(Path, "exists", return_value=False):
            assert cc.run_tests(Path("/fake")) is True

    def test_true_when_tests_pass(self):
        fake_root = Path("/fake")
        tests_dir = fake_root / "tests"

        def _exists_side_effect(self):
            return self == tests_dir

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            assert cc.run_tests(fake_root) is True

    def test_false_when_tests_fail(self):
        fake_root = Path("/fake")
        tests_dir = fake_root / "tests"

        def _exists_side_effect(self):
            return self == tests_dir

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1)
            assert cc.run_tests(fake_root) is False

    def test_true_on_tool_unavailable(self):
        fake_root = Path("/fake")
        tests_dir = fake_root / "tests"

        def _exists_side_effect(self):
            return self == tests_dir

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run", side_effect=FileNotFoundError),
        ):
            assert cc.run_tests(fake_root) is True
