"""Tests para circuit breaker y checkout atómico del Builder."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Add the agent directory to path for imports (same pattern as test_agents_config.py)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".agent"))

from agent_controller import (
    _acquire_builder_lock,
    _check_circuit_breaker,
    _check_invariants,
    _emit_builder_exit,
    _read_builder_lock,
    _read_circuit_breaker,
    _record_error_for_breaker,
    _record_no_progress_for_breaker,
    _release_builder_lock,
    _reset_circuit_breaker,
    _trigger_circuit_breaker,
    _write_circuit_breaker,
)


@pytest.fixture
def temp_runtime_dir(tmp_path):
    """Crear directorio temporal para runtime."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    return runtime_dir


@pytest.fixture
def mock_event_bus(temp_runtime_dir):
    """Crear un mock del event bus."""
    bus = MagicMock()
    bus.emit = MagicMock()
    bus.latest_event = MagicMock(return_value=None)
    return bus


class TestCircuitBreaker:
    """Tests para circuit breaker."""

    def test_read_circuit_breaker_default(self, temp_runtime_dir):
        """Leer circuit breaker cuando no existe debe devolver estado CLOSED."""
        with patch(
            "agent_controller.CIRCUIT_BREAKER_PATH",
            temp_runtime_dir / "circuit_breaker.json",
        ):
            state = _read_circuit_breaker()
            assert state["state"] == "CLOSED"
            assert state["failures"] == 0
            assert state["no_progress_count"] == 0

    def test_write_and_read_circuit_breaker(self, temp_runtime_dir):
        """Escribir y leer circuit breaker debe persistir el estado."""
        breaker_path = temp_runtime_dir / "circuit_breaker.json"
        with patch("agent_controller.CIRCUIT_BREAKER_PATH", breaker_path):
            _write_circuit_breaker({"state": "OPEN", "failures": 5, "reason": "test"})
            state = _read_circuit_breaker()
            assert state["state"] == "OPEN"
            assert state["failures"] == 5
            assert state["reason"] == "test"

    def test_check_circuit_breaker_closed(self, temp_runtime_dir):
        """Verificar circuit breaker CLOSED debe retornar open=False."""
        breaker_path = temp_runtime_dir / "circuit_breaker.json"
        with patch("agent_controller.CIRCUIT_BREAKER_PATH", breaker_path):
            _write_circuit_breaker({"state": "CLOSED", "failures": 0})
            result = _check_circuit_breaker("WP-2026-065")
            assert result["open"] is False
            assert result["reason"] is None

    def test_check_circuit_breaker_open(self, temp_runtime_dir):
        """Verificar circuit breaker OPEN debe retornar open=True con razon."""
        breaker_path = temp_runtime_dir / "circuit_breaker.json"
        with patch("agent_controller.CIRCUIT_BREAKER_PATH", breaker_path):
            _write_circuit_breaker(
                {"state": "OPEN", "reason": "Repeated errors", "failures": 3}
            )
            result = _check_circuit_breaker("WP-2026-065")
            assert result["open"] is True
            assert "Repeated errors" in result["reason"]

    def test_trigger_circuit_breaker(self, temp_runtime_dir):
        """Trigger debe cambiar estado a OPEN."""
        breaker_path = temp_runtime_dir / "circuit_breaker.json"
        with patch("agent_controller.CIRCUIT_BREAKER_PATH", breaker_path):
            _trigger_circuit_breaker("Test reason", "WP-2026-065")
            state = _read_circuit_breaker()
            assert state["state"] == "OPEN"
            assert state["reason"] == "Test reason"
            assert state["ticket_id"] == "WP-2026-065"

    def test_reset_circuit_breaker(self, temp_runtime_dir):
        """Reset debe cambiar estado a CLOSED y limpiar contadores."""
        breaker_path = temp_runtime_dir / "circuit_breaker.json"
        with patch("agent_controller.CIRCUIT_BREAKER_PATH", breaker_path):
            _write_circuit_breaker(
                {"state": "OPEN", "failures": 5, "no_progress_count": 3}
            )
            _reset_circuit_breaker("WP-2026-065")
            state = _read_circuit_breaker()
            assert state["state"] == "CLOSED"
            assert state["failures"] == 0
            assert state["no_progress_count"] == 0

    def test_record_error_triggers_after_three(self, temp_runtime_dir):
        """Tres errores deben disparar el circuit breaker."""
        breaker_path = temp_runtime_dir / "circuit_breaker.json"
        with patch("agent_controller.CIRCUIT_BREAKER_PATH", breaker_path):
            _record_error_for_breaker("WP-2026-065", "Error 1")
            _record_error_for_breaker("WP-2026-065", "Error 2")
            _record_error_for_breaker("WP-2026-065", "Error 3")
            result = _check_circuit_breaker("WP-2026-065")
            assert result["open"] is True

    def test_record_no_progress_triggers_after_three(self, temp_runtime_dir):
        """Tres no-progresos deben disparar el circuit breaker."""
        breaker_path = temp_runtime_dir / "circuit_breaker.json"
        with patch("agent_controller.CIRCUIT_BREAKER_PATH", breaker_path):
            _record_no_progress_for_breaker("WP-2026-065")
            _record_no_progress_for_breaker("WP-2026-065")
            _record_no_progress_for_breaker("WP-2026-065")
            result = _check_circuit_breaker("WP-2026-065")
            assert result["open"] is True


class TestBuilderLock:
    """Tests para checkout atómico con builder_lock.txt."""

    def test_acquire_lock_fresh(self, temp_runtime_dir):
        """Adquirir lock sin lock existente debe tener exito."""
        lock_path = temp_runtime_dir / "builder_lock.txt"
        with patch("agent_controller.BUILDER_LOCK_PATH", lock_path):
            result = _acquire_builder_lock("WP-2026-065", 12345)
            assert result is True
            lock_data = _read_builder_lock()
            assert lock_data["ticket_id"] == "WP-2026-065"
            assert lock_data["pid"] == 12345
            assert lock_data["round"] == 1

    def test_acquire_lock_same_ticket(self, temp_runtime_dir):
        """Adquirir lock para mismo ticket debe actualizar round."""
        lock_path = temp_runtime_dir / "builder_lock.txt"
        with patch("agent_controller.BUILDER_LOCK_PATH", lock_path):
            _acquire_builder_lock("WP-2026-065", 12345)
            result = _acquire_builder_lock("WP-2026-065", 12345)
            assert result is True
            lock_data = _read_builder_lock()
            assert lock_data["round"] == 2

    def test_acquire_lock_different_ticket(self, temp_runtime_dir):
        """Adquirir lock para ticket diferente debe override stale lock."""
        lock_path = temp_runtime_dir / "builder_lock.txt"
        with patch("agent_controller.BUILDER_LOCK_PATH", lock_path):
            _acquire_builder_lock("WP-2026-064", 12345)
            result = _acquire_builder_lock("WP-2026-065", 54321)
            assert result is True
            lock_data = _read_builder_lock()
            assert lock_data["ticket_id"] == "WP-2026-065"
            assert lock_data["round"] == 1

    def test_release_lock(self, temp_runtime_dir):
        """Liberar lock debe eliminar el archivo."""
        lock_path = temp_runtime_dir / "builder_lock.txt"
        with patch("agent_controller.BUILDER_LOCK_PATH", lock_path):
            _acquire_builder_lock("WP-2026-065", 12345)
            _release_builder_lock("WP-2026-065")
            assert not lock_path.exists()

    def test_read_lock_nonexistent(self, temp_runtime_dir):
        """Leer lock inexistente debe retornar None."""
        lock_path = temp_runtime_dir / "builder_lock.txt"
        with patch("agent_controller.BUILDER_LOCK_PATH", lock_path):
            result = _read_builder_lock()
            assert result is None


class TestBuilderExit:
    """Tests para emision de BUILDER_EXIT."""

    def test_emit_builder_exit(self, temp_runtime_dir, mock_event_bus):
        """Emitir BUILDER_EXIT debe llamar al bus con payload correcto."""
        with patch("agent_controller.event_bus", mock_event_bus):
            _emit_builder_exit("WP-2026-065", "Test reason", "Test summary")
            mock_event_bus.emit.assert_called_once()
            call_args = mock_event_bus.emit.call_args
            assert call_args.kwargs["event_type"] == "BUILDER_EXIT"
            assert call_args.kwargs["ticket_id"] == "WP-2026-065"
            assert call_args.kwargs["actor"] == "BUILDER"
            payload = call_args.kwargs["payload"]
            assert payload["exit_reason"] == "Test reason"
            assert payload["completion_summary"] == "Test summary"


class TestInvariants:
    """Tests para invariantes pre y post cierre."""

    def test_invariants_no_plan(self):
        """Sin plan activo debe retornar warning."""
        result = _check_invariants("", "", "IN_PROGRESS")
        assert "No active plan for invariant check" in result["warnings"]

    def test_invariants_pre_closure_no_builder_exit(self):
        """Pre-cierre sin BUILDER_EXIT debe estar OK."""
        plan_content = "# Work Plan\n\n**ID:** WP-2026-065\n\n**Estado:** APPROVED"
        log_content = "# Execution Log\n\n**Estado:** IN_PROGRESS"
        with patch("agent_controller.event_bus", None):
            result = _check_invariants(plan_content, log_content, "IN_PROGRESS")
            assert len(result["errors"]) == 0

    def test_invariants_post_closure_missing_builder_exit(self):
        """Post-cierre sin BUILDER_EXIT debe generar error."""
        plan_content = "# Work Plan\n\n**ID:** WP-2026-065\n\n**Estado:** APPROVED"
        log_content = "# Execution Log\n\n**Estado:** READY_FOR_REVIEW"
        mock_bus = MagicMock()
        mock_bus.latest_event = MagicMock(return_value=None)
        with patch("agent_controller.event_bus", mock_bus):
            result = _check_invariants(plan_content, log_content, "READY_FOR_REVIEW")
            assert any("Missing BUILDER_EXIT" in err for err in result["errors"])

    def test_invariants_post_closure_with_builder_exit(self):
        """Post-cierre con BUILDER_EXIT valido debe estar OK."""
        plan_content = "# Work Plan\n\n**ID:** WP-2026-065\n\n**Estado:** APPROVED"
        log_content = "# Execution Log\n\n**Estado:** READY_FOR_REVIEW"
        mock_event = MagicMock()
        mock_event.payload = {
            "ticket_id": "WP-2026-065",
            "exit_reason": "Completed",
            "completion_summary": "Done",
        }
        mock_bus = MagicMock()
        mock_bus.latest_event = MagicMock(return_value=mock_event)
        with (
            patch("agent_controller.event_bus", mock_bus),
            patch(
                "agent_controller._read_circuit_breaker",
                return_value={"state": "CLOSED"},
            ),
            patch("agent_controller._read_builder_lock", return_value=None),
        ):
            result = _check_invariants(plan_content, log_content, "READY_FOR_REVIEW")
            assert len(result["errors"]) == 0

    def test_invariants_open_breaker_with_ready_for_review(self):
        """Circuit breaker OPEN con READY_FOR_REVIEW debe generar error."""
        plan_content = "# Work Plan\n\n**ID:** WP-2026-065\n\n**Estado:** APPROVED"
        log_content = "# Execution Log\n\n**Estado:** READY_FOR_REVIEW"
        mock_event = MagicMock()
        mock_event.payload = {
            "ticket_id": "WP-2026-065",
            "exit_reason": "Done",
            "completion_summary": "Summary",
        }
        mock_bus = MagicMock()
        mock_bus.latest_event = MagicMock(return_value=mock_event)
        with (
            patch("agent_controller.event_bus", mock_bus),
            patch(
                "agent_controller._read_circuit_breaker", return_value={"state": "OPEN"}
            ),
            patch("agent_controller._read_builder_lock", return_value=None),
        ):
            result = _check_invariants(plan_content, log_content, "READY_FOR_REVIEW")
            assert any("Circuit breaker OPEN" in err for err in result["errors"])
