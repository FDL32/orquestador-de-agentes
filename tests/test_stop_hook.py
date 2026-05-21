"""Tests for stop_hook.py - Completion Verification hook."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

hooks_dir = agent_dir / "hooks"
if str(hooks_dir) not in sys.path:
    sys.path.insert(0, str(hooks_dir))

import stop_hook  # noqa: E402
from stop_hook import (  # noqa: E402
    check_all_phases_complete,
    check_execution_log_complete,
    check_tests_passing,
)


_PROJECT_ROOT = stop_hook.PROJECT_ROOT
_TESTS_DIR = _PROJECT_ROOT / "tests"
_SAFE_RUNNER = _PROJECT_ROOT / "scripts" / "run_pytest_safe.py"


class TestReadyForReviewSemantics:
    def _mock_path(self, exists=True, read_text=""):
        mock_path = MagicMock()
        mock_path.exists.return_value = exists
        mock_path.read_text.return_value = read_text
        return mock_path

    def test_all_phases_complete_passes_when_ready_for_review(self):
        mock_log = self._mock_path(
            exists=True,
            read_text="# Execution Log\n\n- **Estado:** READY_FOR_REVIEW\n",
        )
        mock_plan = self._mock_path(
            exists=True,
            read_text="# Work Plan\n\n- [ ] Criterio de cierre\n",
        )

        with (
            patch("stop_hook.EXEC_LOG", mock_log),
            patch("stop_hook.WORK_PLAN", mock_plan),
        ):
            assert check_all_phases_complete("READY_FOR_REVIEW") is True

    def test_all_phases_complete_fails_when_in_progress_with_pending_boxes(self):
        mock_log = self._mock_path(
            exists=True,
            read_text="# Execution Log\n\n- **Estado:** IN_PROGRESS\n",
        )
        mock_plan = self._mock_path(exists=True, read_text="# Work Plan\n\n- [ ] Pendiente\n")

        with (
            patch("stop_hook.EXEC_LOG", mock_log),
            patch("stop_hook.WORK_PLAN", mock_plan),
        ):
            assert check_all_phases_complete("IN_PROGRESS") is False

    def test_execution_log_complete_passes_when_completed(self):
        mock_log = self._mock_path(
            exists=True,
            read_text="# Execution Log\n\n- **Estado:** COMPLETED\n",
        )

        with patch("stop_hook.EXEC_LOG", mock_log):
            assert check_execution_log_complete("COMPLETED") is True

    def test_execution_log_complete_fails_when_in_progress_without_summary(self):
        mock_log = self._mock_path(
            exists=True,
            read_text="# Execution Log\n\n- **Estado:** IN_PROGRESS\n",
        )

        with patch("stop_hook.EXEC_LOG", mock_log):
            assert check_execution_log_complete("IN_PROGRESS") is False


class TestTestCommandSelection:
    def test_uses_safe_runner_when_available(self):
        def _exists_side_effect(self):
            return self in (_TESTS_DIR, _SAFE_RUNNER)

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            assert check_tests_passing() is True

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == sys.executable
        assert cmd[1].endswith("run_pytest_safe.py")
        assert "--level" in cmd
        assert "unit" in cmd

    def test_uses_pytest_fallback_without_uv(self):
        def _exists_side_effect(self):
            return self == _TESTS_DIR

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            assert check_tests_passing() is True

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == sys.executable
        assert cmd[1] == "-m"
        assert cmd[2] == "pytest"
        assert "uv" not in cmd
