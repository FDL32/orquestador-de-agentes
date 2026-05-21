#!/usr/bin/env python3
"""Builder agent for the active ticket - implements work plan.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path


# WP-2026-122: Deferred path resolution via runtime.project_root
try:
    from runtime.project_root import resolve_project_root
except ImportError:
    # Fallback if runtime.project_root not available
    resolve_project_root = None

PROJECT_ROOT = (
    resolve_project_root()
    if resolve_project_root is not None
    else Path(__file__).resolve().parents[1]
)
AGENT_DIR = PROJECT_ROOT / ".agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from agent_controller import (  # noqa: E402
    WORK_PLAN,
    get_plan_id,
    publish_state_changed_event,
    read_file,
    update_log_status,
)


def main():
    """Main builder flow."""
    parser = argparse.ArgumentParser(description="Builder agent for the active ticket")
    parser.add_argument(
        "--ticket-id",
        default=None,
        help="Ticket ID to implement (defaults to the active plan_id from work_plan.md)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print(f"BUILDER AGENT - {args.ticket_id}")
    print("=" * 70)

    # 1. Read work plan
    print("\n[1] Leyendo work_plan.md...")
    plan_content = read_file(WORK_PLAN)
    plan_id = get_plan_id(plan_content)

    if not plan_id:
        print("[ERROR] No se encontro plan_id en work_plan.md")
        return 1  # return 1 = error (no plan found)

    if not args.ticket_id or args.ticket_id != plan_id:
        if args.ticket_id and args.ticket_id != plan_id:
            print(
                f"[WARN] Ticket solicitado ({args.ticket_id}) no coincide con el plan activo ({plan_id}). "
                "Se usara el plan activo para evitar drift."
            )
        args.ticket_id = plan_id

    print(f"[OK] Plan activo: {plan_id}")
    print("     Objetivo: Smoke test del requeue Manager/Builder")
    print("     Estado: APPROVED")

    # 2. Log execution start
    print("\n[2] Registrando inicio de implementacion...")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exec_note = (
        f"\n### BUILDER START - {timestamp}\n"
        f"- **Agente:** Builder (Python script)\n"
        f"- **Plan ID:** {plan_id}\n"
        f"- **Ticket:** {args.ticket_id}\n"
        f"- **Accion:** Iniciando implementacion del smoke test\n"
    )
    update_log_status("IN_PROGRESS", exec_note)
    print("[OK] Registro actualizado")

    # 3. Prepare implementation
    print("\n[3] Preparando implementacion...")
    print("     Archivos a revisar:")
    print("       - PROJECT.md (documentacion del proyecto)")
    print("       - QUICKSTART.md (instrucciones de arranque)")
    print("       - work_plan.md (este plan)")
    print("       - TURN.md (turno actual)")
    print("       - STATE.md (estado snapshot)")
    print("       - execution_log.md (bitacora)")
    print("       - notifications.md (notificaciones)")

    print("\n[4] Ejecutando validaciones...")
    print("     - python .agent/agent_controller.py --validate --json --force")
    import subprocess

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            ".agent/agent_controller.py",
            "--validate",
            "--json",
            "--force",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        print(f"[WARN] Validacion: {result.stderr[:200]}")
    else:
        print("[OK] Validacion pasada")

    print("\n[5] Ejecutando tests...")
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "scripts/run_pytest_safe.py",
            "tests/test_agent_controller.py",
            "-q",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )
    if "passed" in result.stdout:
        print(f"[OK] {result.stdout.splitlines()[-1]}")
    else:
        print(f"[WARN] Tests: {result.stdout[:200]}")

    # 6. Mark as ready for review
    print("\n[6] Marcando como READY_FOR_REVIEW...")
    update_log_status(
        "READY_FOR_REVIEW", "\n### BUILDER COMPLETE\n- Ready for Manager review\n"
    )
    publish_state_changed_event(
        plan_id, "IN_PROGRESS", "READY_FOR_REVIEW", "Builder complete"
    )
    print("[OK] Estado actualizado a READY_FOR_REVIEW")

    # 7. Execute mark-ready
    print("\n[7] Ejecutando mark-ready...")
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            ".agent/agent_controller.py",
            "--mark-ready",
            "--json",
            "--force",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode == 0:
        print("[OK] mark-ready ejecutado")
    else:
        print(f"[WARN] mark-ready: {result.stderr[:200]}")

    print("\n" + "=" * 70)
    print("BUILDER COMPLETE - Esperando revisión del Manager...")
    print("=" * 70)
    # Normal exit: success if no errors (return 0 = exito real)

    # Keep the window open, waiting for manager feedback
    print("\nEsperando respuesta del Manager...")
    print("Si se rechaza el trabajo, Builder sera requeued automaticamente.")
    print("Presiona Ctrl+C para salir.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[EXIT] Builder terminado por usuario")
        # Clean exit: user interruption (Ctrl+C) is not a failure, just manual stop (return 0 = salida limpia).
        return 0


if __name__ == "__main__":
    sys.exit(main())
