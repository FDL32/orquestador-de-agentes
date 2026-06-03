"""Functional integration tests for agent_controller.py."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from bus.event_bus import EventBus


_PROJECT_ROOT = Path(__file__).parent.parent
_REAL_CONTROLLER = _PROJECT_ROOT / ".agent" / "agent_controller.py"
_RUNTIME_DIR = _PROJECT_ROOT / "runtime"
_BUS_DIR = _PROJECT_ROOT / "bus"
_TMP_BASE = _PROJECT_ROOT / ".tmp"
_SANDBOX_ROOT = _TMP_BASE / "controller_sandbox"


@pytest.fixture()
def sandbox():
    """Create an isolated sandbox that mirrors the controller topology."""
    _TMP_BASE.mkdir(exist_ok=True)
    if _SANDBOX_ROOT.exists():
        shutil.rmtree(_SANDBOX_ROOT, ignore_errors=True)
    _SANDBOX_ROOT.mkdir(exist_ok=True)
    root = _SANDBOX_ROOT

    agent_dir = root / ".agent"
    collab_dir = agent_dir / "collaboration"
    runtime_dir = root / "runtime"
    agent_dir.mkdir()
    collab_dir.mkdir()
    (collab_dir / "archive").mkdir()
    (agent_dir / "context").mkdir()
    (agent_dir / "runtime").mkdir()
    shutil.copytree(_RUNTIME_DIR, runtime_dir)
    shutil.copytree(_BUS_DIR, root / "bus")

    controller_src = _REAL_CONTROLLER.read_text(encoding="utf-8")
    (agent_dir / "agent_controller.py").write_text(controller_src, encoding="utf-8")

    yield root, agent_dir, collab_dir
    shutil.rmtree(root, ignore_errors=True)


def _run(agent_dir: Path, root: Path, *args: str) -> dict | None:
    """Run the sandbox controller and return parsed JSON output."""
    result = subprocess.run(
        [
            sys.executable,
            str(agent_dir / "agent_controller.py"),
            "--json",
            "--force",
            *args,
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return _parse_json(result.stdout)


def _parse_json(output: str) -> dict | None:
    """Extract the first complete JSON object from controller output."""
    json_lines: list[str] = []
    in_json = False
    brace_depth = 0
    for line in output.splitlines():
        stripped = line.strip()
        if not in_json and stripped.startswith("{"):
            in_json = True
        if in_json:
            json_lines.append(stripped)
            brace_depth += stripped.count("{")
            brace_depth -= stripped.count("}")
            if brace_depth == 0:
                break
    if json_lines:
        try:
            return json.loads("\n".join(json_lines))
        except json.JSONDecodeError:
            pass
    return None


def _plan(plan_id: str, status: str) -> str:
    return (
        "# Work Ticket\n\n"
        "## Metadata\n"
        f"- **ID:** {plan_id}\n"
        "- **Title:** Test\n"
        f"- **Estado:** {status}\n"
        "- **Prioridad:** HIGH\n"
        "- **deliverable_type:** code\n"
    )


def _log(status: str) -> str:
    return (
        "# Execution Log\n\n"
        "## TEST-001\n"
        f"- **Estado:** {status}\n"
        "- Inicio: 2026-04-22\n"
    )


def _notif() -> str:
    return "# Notifications\n\nSin notificaciones.\n"


@pytest.mark.integration
def test_approved_pending_returns_builder_implement(sandbox):
    """APPROVED + PENDING -> BUILDER / IMPLEMENT."""
    root, agent_dir, collab_dir = sandbox
    (collab_dir / "work_plan.md").write_text(
        _plan("TEST-001", "APPROVED"), encoding="utf-8"
    )
    (collab_dir / "execution_log.md").write_text(_log("PENDING"), encoding="utf-8")
    (collab_dir / "notifications.md").write_text(_notif(), encoding="utf-8")

    data = _run(agent_dir, root)

    assert data is not None, "No JSON en output del controller"
    assert data.get("role") == "BUILDER"
    assert data.get("action_type") == "IMPLEMENT"


@pytest.mark.integration
def test_completed_returns_manager_create_plan(sandbox):
    """COMPLETED -> MANAGER / CREATE_PLAN."""
    root, agent_dir, collab_dir = sandbox
    (collab_dir / "work_plan.md").write_text(
        _plan("TEST-001", "COMPLETED"), encoding="utf-8"
    )
    (collab_dir / "execution_log.md").write_text(_log("COMPLETED"), encoding="utf-8")
    (collab_dir / "notifications.md").write_text(_notif(), encoding="utf-8")

    data = _run(agent_dir, root)

    assert data is not None, "No JSON en output del controller"
    assert data.get("role") == "MANAGER"
    assert data.get("action_type") == "CREATE_PLAN"


@pytest.mark.integration
def test_validate_returns_empty_arrays(sandbox):
    """Healthy state -> --validate returns empty arrays."""
    root, agent_dir, collab_dir = sandbox
    (collab_dir / "work_plan.md").write_text(
        _plan("TEST-001", "APPROVED"), encoding="utf-8"
    )
    (collab_dir / "execution_log.md").write_text(_log("IN_PROGRESS"), encoding="utf-8")
    (collab_dir / "notifications.md").write_text(_notif(), encoding="utf-8")

    event_bus = EventBus(agent_dir / "runtime" / "events")
    event_bus.emit(
        event_type="STATE_CHANGED",
        ticket_id="TEST-001",
        actor="BUILDER",
        payload={
            "from_state": "APPROVED",
            "to_state": "IN_PROGRESS",
            "reason": "Test bootstrap",
            "source": "test",
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            str(agent_dir / "agent_controller.py"),
            "--validate",
            "--json",
            "--force",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    data = _parse_json(result.stdout)

    assert data is not None, "No JSON en output del controller"
    assert data.get("errors", {}).get("work_plan.md") == []
    assert data.get("errors", {}).get("execution_log.md") == []
    assert data.get("errors", {}).get("notifications.md") == []
    assert data.get("errors", {}).get("TURN.md") == []
    assert data.get("errors", {}).get("consistency") == []
    assert data.get("warnings", {}) == {}
