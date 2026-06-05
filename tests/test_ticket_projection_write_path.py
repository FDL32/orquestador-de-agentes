"""Tests for WT-2026-211 write-path centralization."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parents[1]

_ORIGINAL_RUNTIME_MODULE = sys.modules.get("runtime")
_ORIGINAL_RUNTIME_PROJECT_ROOT = sys.modules.get("runtime.project_root")

sys.path.insert(0, str(MOTOR_ROOT))
sys.path.insert(0, str(MOTOR_ROOT / ".agent"))

runtime_pkg = types.ModuleType("runtime")
runtime_pkg.__path__ = [str(MOTOR_ROOT / "runtime")]
sys.modules.setdefault("runtime", runtime_pkg)

project_root_spec = importlib.util.spec_from_file_location(
    "runtime.project_root", MOTOR_ROOT / "runtime" / "project_root.py"
)
assert project_root_spec and project_root_spec.loader
project_root_module = importlib.util.module_from_spec(project_root_spec)
project_root_spec.loader.exec_module(project_root_module)
sys.modules["runtime.project_root"] = project_root_module
runtime_pkg.project_root = project_root_module

import agent_controller  # type: ignore  # noqa: E402
from bus.state_machine import TicketState  # type: ignore  # noqa: E402
from bus.supervisor import SequentialTicketSupervisor  # type: ignore  # noqa: E402


class FakeEventBus:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def read_events(self, *args, **kwargs):
        return []

    def latest_event(self, *args, **kwargs):
        return None

    def emit(self, event_type: str, **kwargs):
        self.emitted.append((event_type, kwargs))


def test_materialize_state_transition_only_emits_bus(monkeypatch):
    fake_bus = FakeEventBus()

    monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
    monkeypatch.setattr(agent_controller, "event_bus", fake_bus)
    monkeypatch.setattr(
        agent_controller,
        "read_file",
        lambda path: "**Estado:** IN_PROGRESS\n",
    )

    def fail_write(*_args, **_kwargs):
        raise AssertionError(
            "_materialize_state_transition must not write projections directly"
        )

    monkeypatch.setattr(agent_controller, "update_turn_file", fail_write)
    monkeypatch.setattr(agent_controller, "write_file", fail_write)
    monkeypatch.setattr(
        agent_controller, "_create_human_gate_approval_request", lambda *_args: None
    )

    agent_controller._materialize_state_transition(
        "WT-2026-211",
        "READY_FOR_REVIEW",
        "Builder completed implementation",
        actor="SUPERVISOR",
        source="canonical",
    )

    assert len(fake_bus.emitted) == 1
    event_type, payload = fake_bus.emitted[0]
    assert event_type == "STATE_CHANGED"
    assert payload["ticket_id"] == "WT-2026-211"
    assert payload["payload"]["to_state"] == "READY_FOR_REVIEW"


def test_supervisor_materializes_ready_for_review_projection(tmp_path):
    project_root = tmp_path
    collaboration_dir = project_root / ".agent" / "collaboration"
    runtime_dir = project_root / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    turn_path = collaboration_dir / "TURN.md"
    state_path = collaboration_dir / "STATE.md"
    log_path = collaboration_dir / "execution_log.md"

    turn_path.write_text(
        "# TURNO ACTUAL\n\n"
        "**Ultima actualizacion:** 2026-06-01 10:00:00\n\n"
        "---\n\n"
        "## Agente Activo\n\n"
        "| Campo | Valor |\n"
        "|-------|-------|\n"
        "| **ROL** | **BUILDER** |\n"
        "| **Plan ID** | WT-2026-211 |\n"
        "| **Tipo** | IMPLEMENT |\n"
        "| **Accion** | IMPLEMENT |\n"
        "\n---\n\n"
        "## Instruccion\n\n"
        "> Trabajo en progreso.\n\n"
        "---\n\n"
        "## Estado del Sistema\n\n"
        "| Archivo | Estado |\n"
        "|---------|--------|\n"
        "| work_plan.md | APPROVED |\n"
        "| execution_log.md | READY_TO_START |\n",
        encoding="utf-8",
    )
    state_path.write_text(
        "ACTIVE_TICKET: WT-2026-211\nSTATUS: APPROVED\n",
        encoding="utf-8",
    )
    log_path.write_text(
        "# Execution Log\n\n"
        "## WT-2026-211\n"
        "- Inicio documental: 2026-06-02.\n"
        "- Estado documental: READY_TO_START.\n",
        encoding="utf-8",
    )

    supervisor = SequentialTicketSupervisor(
        project_root=project_root,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
    )

    changed = supervisor._materialize_ticket_projection(
        "WT-2026-211", TicketState.READY_FOR_REVIEW
    )

    assert changed is True
    assert "| **ROL** | **MANAGER** |" in turn_path.read_text(encoding="utf-8")
    assert "| **Accion** | REVIEW_WORK |" in turn_path.read_text(encoding="utf-8")
    assert state_path.read_text(encoding="utf-8") == (
        "ACTIVE_TICKET: WT-2026-211\nSTATUS: READY_FOR_REVIEW\n"
    )
    assert "Estado documental: READY_FOR_REVIEW" in log_path.read_text(encoding="utf-8")


def teardown_module(module) -> None:
    runtime_module = sys.modules.get("runtime")
    if _ORIGINAL_RUNTIME_PROJECT_ROOT is None:
        sys.modules.pop("runtime.project_root", None)
        if runtime_module is not None and hasattr(runtime_module, "project_root"):
            delattr(runtime_module, "project_root")
    else:
        sys.modules["runtime.project_root"] = _ORIGINAL_RUNTIME_PROJECT_ROOT
        if runtime_module is not None:
            runtime_module.project_root = _ORIGINAL_RUNTIME_PROJECT_ROOT

    if _ORIGINAL_RUNTIME_MODULE is None:
        sys.modules.pop("runtime", None)
    else:
        sys.modules["runtime"] = _ORIGINAL_RUNTIME_MODULE
