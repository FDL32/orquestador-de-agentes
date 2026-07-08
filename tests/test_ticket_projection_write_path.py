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

# WOT-2026-020p: reuse the already-loaded runtime.project_root if present, instead
# of exec-loading a SECOND, divergent module object. Under `pytest -n` (xdist), a
# duplicate module has its own @lru_cache; the autouse _clear_runtime_project_root_cache
# fixture (conftest.py) and the victim test's module-level `from runtime.project_root
# import clear_cache` then bind to DIFFERENT objects, so resolve_project_root()'s cache
# is never actually cleared for the victim -> stale repo-root leaks into
# tests/unit/test_project_root_resolution.py (13 flaky failures under the full suite).
# The else branch registers the newly-created module in sys.modules too, so a later
# loader reuses THIS object (not order-dependent).
_EXISTING_PR = sys.modules.get("runtime.project_root")
if _EXISTING_PR is not None:
    project_root_module = _EXISTING_PR
    runtime_pkg.project_root = project_root_module
else:
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


# WOT-2026-020p NOTE (vector B barrier): a *unit* barrier for the divergent-module
# regression was attempted and REJECTED as a no-op. The divergence only manifests
# under the specific xdist worker-split + full-suite collection order; in an isolated
# or paired run the freshly exec-loaded module IS what a subsequent import resolves,
# so any single-process assertion passes with OR without the fix (mutation-verify
# confirmed it does not catch the reverted fix). The REAL, verified barrier for
# vector B is the full-suite xdist gate (A/B confirmed: with the fix, 6/6 green; the
# reverted loader reproduces the 13 test_project_root_resolution failures). Do not
# re-add a unit test here that gives false confidence; guard this fix via the suite.


class FakeEvent:
    def __init__(
        self, event_type: str, ticket_id: str, payload: dict[str, str]
    ) -> None:
        self.event_type = event_type
        self.ticket_id = ticket_id
        self.payload = payload

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "ticket_id": self.ticket_id,
            "payload": self.payload,
        }


class FakeEventBus:
    def __init__(self, events: list[FakeEvent] | None = None) -> None:
        self.emitted: list[tuple[str, dict]] = []
        self.events = events or []

    def read_events(self, *args, **kwargs):
        ticket_id = kwargs.get("ticket_id")
        event_type = kwargs.get("event_type")
        return [
            event
            for event in self.events
            if (ticket_id is None or event.ticket_id == ticket_id)
            and (event_type is None or event.event_type == event_type)
        ]

    def latest_event(self, *args, **kwargs):
        events = self.read_events(*args, **kwargs)
        if events:
            return events[-1]
        return None

    def emit(self, event_type: str, **kwargs):
        self.emitted.append((event_type, kwargs))
        self.events.append(
            FakeEvent(
                event_type,
                kwargs.get("ticket_id", ""),
                kwargs.get("payload", {}),
            )
        )


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


def test_mark_ready_sync_materializes_projection_without_supervisor(
    monkeypatch, tmp_path
):
    """mark-ready must align bus and markdown projections without a live supervisor."""
    project_root = tmp_path
    collaboration_dir = project_root / ".agent" / "collaboration"
    runtime_dir = project_root / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    (collaboration_dir / "TURN.md").write_text(
        "# TURNO ACTUAL\n\n"
        "**Ultima actualizacion:** 2026-06-01 10:00:00\n\n"
        "---\n\n"
        "## Agente Activo\n\n"
        "| Campo | Valor |\n"
        "|-------|-------|\n"
        "| **ROL** | **BUILDER** |\n"
        "| **Plan ID** | WT-2026-999 |\n"
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
        "| execution_log.md | IN_PROGRESS |\n",
        encoding="utf-8",
    )
    (collaboration_dir / "STATE.md").write_text(
        "ACTIVE_TICKET: WT-2026-999\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )
    (collaboration_dir / "execution_log.md").write_text(
        "# Execution Log\n\n## WT-2026-999\n- **Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )

    fake_bus = FakeEventBus()
    monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
    monkeypatch.setattr(agent_controller, "event_bus", fake_bus)
    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(agent_controller, "get_collab_dir", lambda: collaboration_dir)
    monkeypatch.setattr(agent_controller, "get_runtime_dir", lambda: runtime_dir)

    agent_controller._sync_mark_ready_targets("WT-2026-999", "")

    assert [event_type for event_type, _ in fake_bus.emitted] == [
        "STATE_CHANGED",
        "STATE_CHANGED",
    ]
    assert (collaboration_dir / "STATE.md").read_text(encoding="utf-8") == (
        "ACTIVE_TICKET: WT-2026-999\nSTATUS: READY_FOR_REVIEW\n"
    )
    turn_content = (collaboration_dir / "TURN.md").read_text(encoding="utf-8")
    assert "| **ROL** | **MANAGER** |" in turn_content
    assert "| **Accion** | REVIEW_WORK |" in turn_content
    assert "- **Estado:** READY_FOR_REVIEW" in (
        collaboration_dir / "execution_log.md"
    ).read_text(encoding="utf-8")


def test_mark_ready_already_ready_reprojects_stale_markdown(monkeypatch, tmp_path):
    """already_ready is idempotent for events but must still heal projections."""
    project_root = tmp_path
    collaboration_dir = project_root / ".agent" / "collaboration"
    runtime_dir = project_root / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    (collaboration_dir / "work_plan.md").write_text(
        "# Work Plan\n\n- **ID:** WT-2026-999\n",
        encoding="utf-8",
    )
    (collaboration_dir / "TURN.md").write_text(
        "# TURNO ACTUAL\n\n"
        "**Ultima actualizacion:** 2026-06-01 10:00:00\n\n"
        "---\n\n"
        "## Agente Activo\n\n"
        "| Campo | Valor |\n"
        "|-------|-------|\n"
        "| **ROL** | **BUILDER** |\n"
        "| **Plan ID** | WT-2026-999 |\n"
        "| **Tipo** | IMPLEMENT |\n"
        "| **Accion** | IMPLEMENT |\n",
        encoding="utf-8",
    )
    (collaboration_dir / "STATE.md").write_text(
        "ACTIVE_TICKET: WT-2026-999\nSTATUS: IN_PROGRESS\n",
        encoding="utf-8",
    )
    (collaboration_dir / "execution_log.md").write_text(
        "# Execution Log\n\n## WT-2026-999\n- **Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )

    fake_bus = FakeEventBus(
        [
            FakeEvent(
                "STATE_CHANGED",
                "WT-2026-999",
                {"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
            )
        ]
    )
    monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", True)
    monkeypatch.setattr(agent_controller, "event_bus", fake_bus)
    monkeypatch.setattr(agent_controller, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(agent_controller, "get_collab_dir", lambda: collaboration_dir)
    monkeypatch.setattr(agent_controller, "get_runtime_dir", lambda: runtime_dir)
    monkeypatch.setattr(
        agent_controller,
        "_ensure_active_builder_round",
        lambda _plan_id: (True, None, "ok"),
    )

    rc = agent_controller._handle_mark_ready(None, True, True)

    assert rc == 0
    assert fake_bus.emitted == []
    assert (collaboration_dir / "STATE.md").read_text(encoding="utf-8") == (
        "ACTIVE_TICKET: WT-2026-999\nSTATUS: READY_FOR_REVIEW\n"
    )
    assert "| **ROL** | **MANAGER** |" in (collaboration_dir / "TURN.md").read_text(
        encoding="utf-8"
    )
    assert "- **Estado:** READY_FOR_REVIEW" in (
        collaboration_dir / "execution_log.md"
    ).read_text(encoding="utf-8")


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
