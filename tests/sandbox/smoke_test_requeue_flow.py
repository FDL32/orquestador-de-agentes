#!/usr/bin/env python3
"""
Smoke test E2E for WP-2026-080:
Validates APPROVE cascade, CHANGES requeue (IN_PROGRESS), and 3x CHANGES escalation to HUMAN_GATE.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bus.supervisor import SequentialTicketSupervisor, SupervisorState

def setup_dummy_project(tmp_path: Path):
    collab = tmp_path / ".agent" / "collaboration"
    runtime = tmp_path / ".agent" / "runtime"
    collab.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "events").mkdir(parents=True, exist_ok=True)

    # work_plan.md
    (collab / "work_plan.md").write_text("""# Plan de Trabajo del Proyecto

## WP-2026-001: Primer Ticket
### Metadata
- **ID:** WP-2026-001
- **Estado:** PENDING
### Objetivo
Implementar algo.

## WP-2026-002: Segundo Ticket
### Metadata
- **ID:** WP-2026-002
- **Estado:** PENDING
### Objetivo
Implementar otra cosa.
""", encoding="utf-8")

    # execution_log.md
    (collab / "execution_log.md").write_text("""# Execution Log - orquestacion_agentes

**Estado:** IN_PROGRESS
- Current state: WP-2026-001 IN_PROGRESS

### WP-2026-001 - Primer Ticket
**Estado:** IN_PROGRESS
""", encoding="utf-8")

    # TURN.md
    (collab / "TURN.md").write_text("""# Control de Turno
| **Atributo** | **Valor** |
| :--- | :--- |
| **Rol Activo** | BUILDER |
| **Plan ID** | WP-2026-001 |
| **Estado del Plan** | APPROVED |
| **Estado del Log** | IN_PROGRESS |
""", encoding="utf-8")

    # STATE.md
    (collab / "STATE.md").write_text("""# Estado Operacional
- **Plan Activo:** WP-2026-001
- **Estado actual:** IN_PROGRESS
""", encoding="utf-8")

    # Copy agent_controller.py and other needed modules
    (tmp_path / ".agent").mkdir(exist_ok=True)
    shutil.copy(PROJECT_ROOT / ".agent" / "agent_controller.py", tmp_path / ".agent" / "agent_controller.py")
    if (PROJECT_ROOT / ".agent" / "workflows").exists():
        shutil.copytree(PROJECT_ROOT / ".agent" / "workflows", tmp_path / ".agent" / "workflows", dirs_exist_ok=True)
    # Copy bus
    if (PROJECT_ROOT / "bus").exists():
        shutil.copytree(PROJECT_ROOT / "bus", tmp_path / "bus", dirs_exist_ok=True)

    # Create dummy rule files
    (tmp_path / ".builder_rules").write_text("builder rules", encoding="utf-8")
    (tmp_path / ".supervisor_rules").write_text("supervisor rules", encoding="utf-8")

def run_controller(tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)
    # Set PYTEST_CURRENT_TEST so supervisor doesn't spawn real pwsh windows during smoke test
    env["PYTEST_CURRENT_TEST"] = "smoke_test"
    controller = tmp_path / ".agent" / "agent_controller.py"
    return subprocess.run(
        [sys.executable, str(controller)] + args,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

def test_flow_1_approve():
    print("\n--- FLOW 1: APPROVE CASCADE ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        setup_dummy_project(tmp_path)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        supervisor.bootstrap()

        # Builder finishes
        run_controller(tmp_path, ["--mark-ready", "--force"])

        # Manager approves
        supervisor.event_bus.emit(
            "REVIEW_DECISION",
            ticket_id="WP-2026-001",
            actor="MANAGER",
            payload={"decision": "approve", "feedback": "LGTM"},
        )
        supervisor.transition_ticket("WP-2026-001", "READY_TO_CLOSE", "Manager approved")

        # User confirms close
        supervisor.event_bus.emit(
            "CLOSE_CONFIRMED",
            ticket_id="WP-2026-001",
            actor="USER",
            payload={"action": "closeout_confirmed"},
        )

        supervisor.run_once()
        state = supervisor.load_state()
        print(f"Active ticket after closeout: {state.active_ticket}")
        assert state.active_ticket == "WP-2026-002", f"Expected WP-2026-002, got {state.active_ticket}"
        print("[PASS] Flow 1: APPROVE cascade verified successfully.")

def test_flow_2_changes_requeue():
    print("\n--- FLOW 2: CHANGES -> REQUEUE -> RE-IMPLEMENT -> APPROVE ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        setup_dummy_project(tmp_path)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        supervisor.bootstrap()

        # Builder finishes
        run_controller(tmp_path, ["--mark-ready", "--force"])

        # Manager requests changes (1st rejection)
        res = run_controller(tmp_path, ["--request-changes", "WP-2026-001", "--force"])
        print(f"Controller output (--request-changes): {res.stdout.strip()}")

        # Supervisor processes event
        supervisor.run_once()
        state = supervisor.load_state()
        print(f"Supervisor loop round: {state.loop_current_round}")
        assert state.loop_current_round == 1, f"Expected round 1, got {state.loop_current_round}"

        # Verify state is IN_PROGRESS
        turn_content = (tmp_path / ".agent" / "collaboration" / "TURN.md").read_text(encoding="utf-8")
        assert "IN_PROGRESS" in turn_content, "TURN.md not transitioned to IN_PROGRESS"
        assert "BUILDER" in turn_content, "TURN.md active role not BUILDER"

        print("[PASS] Flow 2: CHANGES requeue verified successfully.")

def test_flow_3_three_rejections_human_gate():
    print("\n--- FLOW 3: 3x CHANGES -> HUMAN_GATE ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        setup_dummy_project(tmp_path)
        supervisor = SequentialTicketSupervisor(project_root=tmp_path)
        supervisor.bootstrap()

        # 1st rejection
        run_controller(tmp_path, ["--mark-ready", "--force"])
        run_controller(tmp_path, ["--request-changes", "WP-2026-001", "--force"])
        supervisor.run_once()

        # 2nd rejection
        run_controller(tmp_path, ["--mark-ready", "--force"])
        run_controller(tmp_path, ["--request-changes", "WP-2026-001", "--force"])
        supervisor.run_once()

        # 3rd rejection
        run_controller(tmp_path, ["--mark-ready", "--force"])
        res = run_controller(tmp_path, ["--request-changes", "WP-2026-001", "--force"])
        print(f"Controller output (3rd --request-changes): {res.stdout.strip()}")
        supervisor.run_once()

        # Verify state is HUMAN_GATE
        turn_content = (tmp_path / ".agent" / "collaboration" / "TURN.md").read_text(encoding="utf-8")
        print(f"TURN.md after 3 rejections:\n{turn_content.strip()}")
        assert "HUMAN_GATE" in turn_content, "TURN.md not transitioned to HUMAN_GATE"
        assert "SUPERVISOR" in turn_content, "TURN.md active role not SUPERVISOR"

        exec_log = (tmp_path / ".agent" / "collaboration" / "execution_log.md").read_text(encoding="utf-8")
        assert "HUMAN_GATE" in exec_log, "execution_log.md not transitioned to HUMAN_GATE"

        print("[PASS] Flow 3: 3x CHANGES escalation to HUMAN_GATE verified successfully.")

if __name__ == "__main__":
    test_flow_1_approve()
    test_flow_2_changes_requeue()
    test_flow_3_three_rejections_human_gate()
    print("\n[ALL PASS] Smoke tests completed successfully.")
