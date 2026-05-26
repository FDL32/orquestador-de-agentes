"""Tests para HUMAN_GATE timeout y expiracion canonica.

WP-2026-146: Human gate approval timeout wiring.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


# Add the agent directory to path for imports (same pattern as test_builder_exit_and_breaker.py)
_agent_dir = Path(__file__).parent.parent.parent / ".agent"
sys.path.insert(0, str(_agent_dir))
# Also add project root for runtime/ imports
sys.path.insert(0, str(_agent_dir.parent))

import pytest  # noqa: E402


@pytest.fixture
def temp_runtime_dir(tmp_path):
    """Crear directorio temporal para runtime."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    return runtime_dir


@pytest.fixture
def temp_agents_config(tmp_path):
    """Crear un archivo agents.json temporal con configuracion de timeout."""
    config = {
        "active_profile": "engine-dev",
        "manager_review": {
            "timeout_seconds": 180,
            "max_attempts": 5,
            "human_gate_timeout_seconds": 7200,
        },
    }
    config_path = tmp_path / "agents.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


class TestHumanGateTimeoutConfig:
    """Tests para configuracion de timeout de HUMAN_GATE."""

    def test_get_human_gate_timeout_from_config(self, temp_agents_config):
        """Leer timeout desde agents.json debe devolver el valor configurado."""
        from agent_controller import get_human_gate_timeout

        with patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config):
            timeout = get_human_gate_timeout()
            assert timeout == 7200

    def test_get_human_gate_timeout_fallback_on_missing_config(self, tmp_path):
        """Configuracion ausente debe devolver fallback de 86400 segundos (24h)."""
        from agent_controller import get_human_gate_timeout

        config_path = tmp_path / "nonexistent.json"
        with patch("agent_controller.AGENTS_CONFIG_PATH", config_path):
            timeout = get_human_gate_timeout()
            assert timeout == 86400  # HUMAN_GATE_TIMEOUT_FALLBACK

    def test_get_human_gate_timeout_fallback_on_invalid_value(self, tmp_path):
        """Valor invalido (negativo) debe devolver fallback."""
        from agent_controller import get_human_gate_timeout

        config = {"manager_review": {"human_gate_timeout_seconds": -10}}
        config_path = tmp_path / "agents.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with patch("agent_controller.AGENTS_CONFIG_PATH", config_path):
            timeout = get_human_gate_timeout()
            assert timeout == 86400  # Fallback

    def test_get_human_gate_timeout_fallback_on_zero(self, tmp_path):
        """Valor cero debe devolver fallback."""
        from agent_controller import get_human_gate_timeout

        config = {"manager_review": {"human_gate_timeout_seconds": 0}}
        config_path = tmp_path / "agents.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with patch("agent_controller.AGENTS_CONFIG_PATH", config_path):
            timeout = get_human_gate_timeout()
            assert timeout == 86400  # Fallback


class TestApprovalStoreCreation:
    """Tests para creacion de ApprovalStore."""

    def test_get_approval_store_creates_store(
        self, temp_runtime_dir, temp_agents_config
    ):
        """Obtener ApprovalStore debe crearlo con politica correcta."""
        from agent_controller import _get_approval_store

        with (
            patch(
                "agent_controller.get_agent_dir", return_value=temp_runtime_dir.parent
            ),
            patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config),
        ):
            store = _get_approval_store()
            assert store is not None
            assert store.policy.policy_name == "human_gate"
            assert store.policy.timeout_seconds == 7200
            assert store.policy.auto_resolve is True

    def test_get_approval_store_returns_none_if_unavailable(self, temp_agents_config):
        """Si el sistema de approval no esta disponible, retorna None."""
        from agent_controller import _get_approval_store

        with (
            patch("agent_controller.APPROVAL_SYSTEM_AVAILABLE", False),
            patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config),
        ):
            store = _get_approval_store()
            assert store is None


class TestHumanGateApprovalRequest:
    """Tests para creacion de ApprovalRequest en HUMAN_GATE."""

    def test_create_approval_request_success(
        self, temp_runtime_dir, temp_agents_config
    ):
        """Crear ApprovalRequest debe persistir el request con timeout."""
        from agent_controller import _create_human_gate_approval_request

        with (
            patch(
                "agent_controller.get_agent_dir", return_value=temp_runtime_dir.parent
            ),
            patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config),
        ):
            result = _create_human_gate_approval_request("WP-2026-146")
            assert result is True

            # Verify the store file was created
            store_path = temp_runtime_dir / "approvals" / "store.json"
            assert store_path.exists()

            # Verify the request was persisted
            store_data = json.loads(store_path.read_text(encoding="utf-8"))
            assert len(store_data) == 1
            approval_id = next(iter(store_data.keys()))
            request_data = store_data[approval_id]
            assert request_data["ticket_id"] == "WP-2026-146"
            assert request_data["status"] == "pending"
            assert request_data["timeout_seconds"] == 7200
            assert request_data["metadata"]["escalation_type"] == "human_gate"

    def test_create_approval_request_with_custom_timeout(
        self, temp_runtime_dir, temp_agents_config
    ):
        """Crear ApprovalRequest con timeout personalizado debe usar ese valor."""
        from agent_controller import _create_human_gate_approval_request

        with (
            patch(
                "agent_controller.get_agent_dir", return_value=temp_runtime_dir.parent
            ),
            patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config),
        ):
            result = _create_human_gate_approval_request(
                "WP-2026-146", timeout_seconds=600
            )
            assert result is True

            store_path = temp_runtime_dir / "approvals" / "store.json"
            store_data = json.loads(store_path.read_text(encoding="utf-8"))
            approval_id = next(iter(store_data.keys()))
            request_data = store_data[approval_id]
            assert request_data["timeout_seconds"] == 600

    def test_create_approval_request_returns_false_if_unavailable(
        self, temp_agents_config
    ):
        """Si el sistema de approval no esta disponible, retorna False."""
        from agent_controller import _create_human_gate_approval_request

        with (
            patch("agent_controller.APPROVAL_SYSTEM_AVAILABLE", False),
            patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config),
        ):
            result = _create_human_gate_approval_request("WP-2026-146")
            assert result is False

    def test_create_approval_request_generates_unique_id(
        self, temp_runtime_dir, temp_agents_config
    ):
        """Cada ApprovalRequest debe tener un ID unico."""
        from agent_controller import _create_human_gate_approval_request

        with (
            patch(
                "agent_controller.get_agent_dir", return_value=temp_runtime_dir.parent
            ),
            patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config),
        ):
            result1 = _create_human_gate_approval_request("WP-2026-146")
            result2 = _create_human_gate_approval_request("WP-2026-146")

            assert result1 is True
            assert result2 is True

            store_path = temp_runtime_dir / "approvals" / "store.json"
            store_data = json.loads(store_path.read_text(encoding="utf-8"))
            # Should have 2 different approval IDs
            assert len(store_data) == 2
            approval_ids = list(store_data.keys())
            assert approval_ids[0] != approval_ids[1]


class TestHumanGateExpiryIntegration:
    """Tests de integracion para expiracion de HUMAN_GATE via supervisor."""

    def test_expired_approval_resolves_to_blocked(
        self, temp_runtime_dir, temp_agents_config
    ):
        """Un ApprovalRequest expirado debe resolverse a EXPIRED via supervisor."""
        from agent_controller import (
            _create_human_gate_approval_request,
            _get_approval_store,
        )
        from bus.approval import ApprovalReason, ApprovalStatus

        with (
            patch(
                "agent_controller.get_agent_dir", return_value=temp_runtime_dir.parent
            ),
            patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config),
        ):
            # Create an approval request
            _create_human_gate_approval_request("WP-2026-146")

            # Get the store and manually set created_at to past
            store = _get_approval_store()
            store_path = temp_runtime_dir / "approvals" / "store.json"
            store_data = json.loads(store_path.read_text(encoding="utf-8"))
            approval_id = next(iter(store_data.keys()))

            # Set created_at to 3 hours ago (past the 7200s timeout)
            past_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
            store_data[approval_id]["created_at"] = past_time
            store_path.write_text(json.dumps(store_data), encoding="utf-8")

            # Run check_and_expire_all (simulating supervisor loop)
            expired = store.check_and_expire_all()

            # Verify the request was expired
            assert len(expired) == 1
            expired_request = expired[0]
            assert expired_request.status == ApprovalStatus.EXPIRED
            assert expired_request.reason == ApprovalReason.TIMEOUT_EXPIRED

    def test_non_expired_approval_remains_pending(
        self, temp_runtime_dir, temp_agents_config
    ):
        """Un ApprovalRequest no expirado debe permanecer PENDING."""
        from agent_controller import (
            _create_human_gate_approval_request,
            _get_approval_store,
        )

        with (
            patch(
                "agent_controller.get_agent_dir", return_value=temp_runtime_dir.parent
            ),
            patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config),
        ):
            # Create an approval request
            _create_human_gate_approval_request("WP-2026-146")

            # Get the store
            store = _get_approval_store()

            # Run check_and_expire_all immediately (should not expire)
            expired = store.check_and_expire_all()

            # Verify no requests were expired
            assert len(expired) == 0

            # Verify the request is still pending
            store_path = temp_runtime_dir / "approvals" / "store.json"
            store_data = json.loads(store_path.read_text(encoding="utf-8"))
            approval_id = next(iter(store_data.keys()))
            assert store_data[approval_id]["status"] == "pending"

    def test_approval_survives_restart(self, temp_runtime_dir, temp_agents_config):
        """Un ApprovalRequest debe sobrevivir a un restart (persistencia)."""
        from agent_controller import _create_human_gate_approval_request
        from bus.approval import ApprovalStatus, ApprovalStore

        with (
            patch(
                "agent_controller.get_agent_dir", return_value=temp_runtime_dir.parent
            ),
            patch("agent_controller.AGENTS_CONFIG_PATH", temp_agents_config),
        ):
            # Create an approval request
            _create_human_gate_approval_request("WP-2026-146")

            # Read the store data before "restart"
            store_path = temp_runtime_dir / "approvals" / "store.json"
            original_data = json.loads(store_path.read_text(encoding="utf-8"))
            approval_id = next(iter(original_data.keys()))

            # Simulate restart: create new store instance
            new_store = ApprovalStore(
                store_path=store_path,
                policy=MagicMock(timeout_seconds=7200),
            )

            # Load the request from the persisted store
            request = new_store.load(approval_id)

            # Verify the request was loaded correctly
            assert request is not None
            assert request.ticket_id == "WP-2026-146"
            assert request.status == ApprovalStatus.PENDING
            assert request.timeout_seconds == 7200
