"""Tests for completion_checker.py - Verificacion de completitud.

Suite sin acceso a filesystem: usa mocks puros sobre subprocess.run y Path.exists.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Add .agent to path for imports
agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

import completion_checker  # noqa: E402
from completion_checker import (  # noqa: E402
    _check_all_tasks_done,
    _check_execution_summary,
    _check_tests_pass,
    check_completion,
    safe_print,
)


_PROJECT_ROOT = completion_checker.PROJECT_ROOT
_TESTS_DIR = _PROJECT_ROOT / "tests"
_SAFE_RUNNER = _PROJECT_ROOT / "scripts" / "run_pytest_safe.py"
_WORK_PLAN = completion_checker.WORK_PLAN
_EXEC_LOG = completion_checker.EXEC_LOG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_log_status(status: str):
    """Devuelve un mock de read_text que simula un log con el estado dado."""

    def _read_text(*args, **kwargs):
        return f"# Execution Log\n\n## TEST-001\n- **Estado:** {status}\n"

    return _read_text


# ---------------------------------------------------------------------------
# TestCheckTestsPass -- seleccion de comando y errores de herramienta
# ---------------------------------------------------------------------------


class TestCheckTestsPass:
    def test_returns_true_when_no_tests_dir(self):
        """Sin directorio tests/ debe considerar OK."""
        with patch.object(Path, "exists", return_value=False):
            assert _check_tests_pass() is True

    def test_uses_safe_runner_when_exists(self):
        """Si run_pytest_safe.py existe, debe usarlo con --level unit."""

        def _exists_side_effect(self):
            return self in (_TESTS_DIR, _SAFE_RUNNER)

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = _check_tests_pass()

        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[1].endswith("run_pytest_safe.py")
        assert "--level" in cmd
        assert "unit" in cmd

    def test_uses_pytest_fallback_when_safe_runner_missing(self):
        """Si no existe safe runner, fallback a python -m pytest tests/ -q."""

        def _exists_side_effect(self):
            return self == _TESTS_DIR

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = _check_tests_pass()

        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == sys.executable
        assert cmd[1] == "-m"
        assert cmd[2] == "pytest"
        assert "tests" in cmd[3]

    def test_returns_false_when_tests_fail(self):
        """Si pytest retorna returncode != 0, debe retornar False."""

        def _exists_side_effect(self):
            return self == _TESTS_DIR

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1)
            result = _check_tests_pass()

        assert result is False

    def test_returns_true_when_tool_unavailable(self):
        """Si la herramienta no estÃ¡ disponible, no bloquear completitud."""

        def _exists_side_effect(self):
            return self == _TESTS_DIR

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run", side_effect=FileNotFoundError),
        ):
            result = _check_tests_pass()

        assert result is True

    def test_returns_true_on_permission_error(self):
        """PermissionError no debe bloquear completitud."""

        def _exists_side_effect(self):
            return self == _TESTS_DIR

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run", side_effect=PermissionError),
        ):
            result = _check_tests_pass()

        assert result is True

    def test_never_uses_uv_run(self):
        """El comando nunca debe contener 'uv run'."""

        def _exists_side_effect(self):
            return self == _TESTS_DIR

        with (
            patch.object(Path, "exists", _exists_side_effect),
            patch("completion_common.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            _check_tests_pass()
            cmd = mock_run.call_args[0][0]
            assert "uv" not in cmd


# ---------------------------------------------------------------------------
# TestReadyForReviewSemantics -- falsos negativos de WP-2026-009
# ---------------------------------------------------------------------------


class TestReadyForReviewSemantics:
    def _mock_path(self, exists=True, read_text=""):
        m = MagicMock()
        m.exists.return_value = exists
        m.read_text.return_value = read_text
        return m

    def test_tasks_done_passes_when_ready_for_review_despite_checkboxes(self):
        """READY_FOR_REVIEW no debe penalizar checkboxes de cierre."""
        plan_content = (
            "# Work Plan\n\n- [ ] Criterio de aceptacion\n- [x] Tarea hecha\n"
        )
        mock_plan = self._mock_path(exists=True, read_text=plan_content)
        mock_log = self._mock_path(
            exists=True, read_text=_mock_log_status("READY_FOR_REVIEW")()
        )

        with (
            patch("completion_checker.EXEC_LOG", mock_log),
            patch("completion_checker.WORK_PLAN", mock_plan),
        ):
            assert _check_all_tasks_done() is True

    def test_tasks_done_fails_when_in_progress_with_checkboxes(self):
        """IN_PROGRESS debe seguir penalizando checkboxes pendientes."""
        plan_content = "# Work Plan\n\n- [ ] Tarea pendiente\n"
        mock_plan = self._mock_path(exists=True, read_text=plan_content)
        mock_log = self._mock_path(
            exists=True, read_text=_mock_log_status("IN_PROGRESS")()
        )

        with (
            patch("completion_checker.EXEC_LOG", mock_log),
            patch("completion_checker.WORK_PLAN", mock_plan),
        ):
            assert _check_all_tasks_done() is False

    def test_execution_summary_passes_when_ready_for_review(self):
        """READY_FOR_REVIEW no debe exigir 'Resumen' generico."""
        log_content = "# Execution Log\n\n## WP-009\n- **Estado:** READY_FOR_REVIEW\n"
        mock_log = self._mock_path(exists=True, read_text=log_content)

        with patch("completion_checker.EXEC_LOG", mock_log):
            assert _check_execution_summary() is True

    def test_execution_summary_fails_when_in_progress_without_summary(self):
        """IN_PROGRESS sin 'Resumen' debe seguir fallando."""
        log_content = "# Execution Log\n\n## WP-009\n- **Estado:** IN_PROGRESS\n"
        mock_log = self._mock_path(exists=True, read_text=log_content)

        with patch("completion_checker.EXEC_LOG", mock_log):
            assert _check_execution_summary() is False

    def test_execution_summary_passes_when_completed(self):
        """COMPLETED debe relajar el criterio de resumen."""
        log_content = "# Execution Log\n\n## WP-009\n- **Estado:** COMPLETED\n"
        mock_log = self._mock_path(exists=True, read_text=log_content)

        with patch("completion_checker.EXEC_LOG", mock_log):
            assert _check_execution_summary() is True

    def test_check_completion_ready_for_review_vs_in_progress(self):
        """check_completion distingue READY_FOR_REVIEW de IN_PROGRESS."""
        plan_content = "# Work Plan\n\n- [ ] Criterio final\n- [x] Hecho\n"
        log_ready = "# Execution Log\n\n## WP-009\n- **Estado:** READY_FOR_REVIEW\n"
        log_progress = "# Execution Log\n\n## WP-009\n- **Estado:** IN_PROGRESS\n"

        # Mockear tests_passing para que no dependa de subprocess
        with (
            patch("completion_checker._check_tests_pass", return_value=True),
            patch(
                "completion_checker._check_no_pending_escalations", return_value=True
            ),
            patch("completion_checker._check_findings_exist", return_value=False),
        ):
            # Con READY_FOR_REVIEW: tasks y summary pasan => 4/5 => can_complete=True
            mock_plan = self._mock_path(exists=True, read_text=plan_content)
            mock_log = self._mock_path(exists=True, read_text=log_ready)
            with (
                patch("completion_checker.WORK_PLAN", mock_plan),
                patch("completion_checker.EXEC_LOG", mock_log),
            ):
                result = check_completion()
                assert result["checks"]["tasks_completed"] is True
                assert result["checks"]["log_has_summary"] is True
                assert result["can_complete"] is True

            # Con IN_PROGRESS: tasks y summary fallan => 2/5 => can_complete=False
            mock_plan = self._mock_path(exists=True, read_text=plan_content)
            mock_log = self._mock_path(exists=True, read_text=log_progress)
            with (
                patch("completion_checker.WORK_PLAN", mock_plan),
                patch("completion_checker.EXEC_LOG", mock_log),
            ):
                result = check_completion()
                assert result["checks"]["tasks_completed"] is False
                assert result["checks"]["log_has_summary"] is False
                assert result["can_complete"] is False


# ---------------------------------------------------------------------------
# TestSafePrint -- edge cases de encoding
# ---------------------------------------------------------------------------


class TestSafePrint:
    def test_safe_print_ascii(self):
        """safe_print maneja texto ASCII normalmente."""
        with patch("builtins.print") as mock_print:
            safe_print("Hello World")
            mock_print.assert_called_once_with("Hello World", end="\n")

    def test_safe_print_unicode_supported(self):
        """safe_print maneja Unicode soportado por la consola."""
        with patch("builtins.print") as mock_print:
            safe_print("CafÃ© rÃ©sumÃ© naÃ¯ve")
            mock_print.assert_called_once_with("CafÃ© rÃ©sumÃ© naÃ¯ve", end="\n")

    def test_safe_print_encoding_error_fallback(self):
        """safe_print maneja errores de encoding de forma segura."""
        # Esta funcion ya maneja UnicodeEncodeError internamente
        # Solo verificamos que no lanza excepciones con caracteres especiales
        try:
            safe_print("CafÃ© rÃ©sumÃ© naÃ¯ve")
        except Exception as e:
            pytest.fail(f"safe_print raised unexpected exception: {e}")

    def test_safe_print_emojis_fallback(self):
        """safe_print maneja emojis y simbolos especiales."""
        # Verificar que no lanza excepciones con emojis
        try:
            safe_print("âœ… Task completed ðŸŽ‰")
        except Exception as e:
            pytest.fail(f"safe_print raised unexpected exception: {e}")

    def test_safe_print_bom_handling(self):
        """safe_print maneja entrada con BOM o marcas de encoding."""
        # Texto con BOM (Byte Order Mark)
        bom_text = "\ufeffHello World"
        with patch("builtins.print") as mock_print:
            safe_print(bom_text)
            mock_print.assert_called_once_with(bom_text, end="\n")

    def test_safe_print_empty_string(self):
        """safe_print maneja string vacio."""
        with patch("builtins.print") as mock_print:
            safe_print("")
            mock_print.assert_called_once_with("", end="\n")

    def test_safe_print_custom_end(self):
        """safe_print respeta parametro end."""
        with patch("builtins.print") as mock_print:
            safe_print("Test", end="")
            mock_print.assert_called_once_with("Test", end="")
