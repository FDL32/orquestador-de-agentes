#!/usr/bin/env python3
"""Builder agent for the active ticket - implements work plan.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import resolve_project_root  # noqa: E402


_PROJECT_ROOT = resolve_project_root()
PROJECT_ROOT = _PROJECT_ROOT  # Alias for backward compatibility with subprocess calls
AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from agent_controller import (  # noqa: E402
    BUS_AVAILABLE,
    WORK_PLAN,
    event_bus,
    get_plan_id,
    read_file,
    update_log_status,
)

# WOT-2026-058v: the launch-precondition logic is REUSED from the WOT-2026-058t
# detective path (prepush imports it from here too). prepush_check.py and
# check_batch_run_accounting.py are IMPORT-ONLY surfaces for this ticket: they
# are never modified here. Reimplementing the PREDICATE-vs-flight_plans
# matching would create a second variant of the same invariant.
from scripts.check_batch_run_accounting import (  # noqa: E402
    _flight_name,
    _predicate_claims_dag,
    _resolve_flight_plans_root,
    check_flight_plan_persisted,
)


def check_flight_launch_prerequisites(
    launch_context: Path, flight_plans_root: Path | None = None
) -> list[str]:
    """WOT-2026-058v: preventive launch gate - a flight does not launch
    without a persisted DAG.

    Before: ``launch_context`` is a batch_run-shaped JSON (top-level ``flight``
    plus ``PREDICATE``) prepared at flight takeoff; ``flight_plans_root`` may
    override the ``orchestrator_pipeline/flight_plans/`` tree (resolved from
    the context's own ancestor chain when None, same convention as
    WOT-2026-058t).
    During: reads the context and fails closed on (a0) a launch that cites no
    DAG at all (no ``flight``, no ``PREDICATE``, or a PREDICATE whose
    conditions 1/2 do not claim ``exit_code: 0``) and on a launch context with
    no reachable ``flight_plans/`` tree (nothing to resolve the claim against
    is not a pass); the claimed-DAG-vs-disk resolution itself is delegated to
    ``check_flight_plan_persisted`` (the WOT-2026-058t detective, reused by
    import, never reimplemented).
    After: returns finding strings (empty list = launch may proceed); every
    finding names the flight it blocks. Unreadable or malformed context input
    is surfaced as a finding, never raised past the launch.
    """
    path = Path(launch_context)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"launch context ilegible ({path}): {exc}"]
    if not isinstance(payload, dict):
        return [f"launch context invalido ({path}): se esperaba un objeto JSON"]

    flight = _flight_name(payload)
    if not flight:
        return [
            "arranque sin 'flight' citado: un vuelo no arranca sin identificar "
            "el plan que ejecuta (WOT-2026-058v)"
        ]
    if not _predicate_claims_dag(payload):
        return [
            f"el arranque del vuelo '{flight}' no cita ningun DAG validado: su "
            "PREDICATE no declara exit_code 0 en las condiciones 1/2 "
            "(schema_valido/dag_aciclico); un vuelo no arranca sin DAG "
            "persistido bajo orchestrator_pipeline/flight_plans/ "
            "(WOT-2026-058v)"
        ]
    if flight_plans_root is None:
        flight_plans_root = _resolve_flight_plans_root(path)
    if flight_plans_root is None:
        return [
            f"el arranque del vuelo '{flight}' cita un DAG validado pero no hay "
            "arbol orchestrator_pipeline/flight_plans/ alcanzable desde el "
            "contexto de arranque: el DAG citado no resuelve a ningun fichero "
            "(WOT-2026-058v)"
        ]
    try:
        return check_flight_plan_persisted(path, Path(flight_plans_root))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"launch context ilegible ({path}): {exc}"]


def _launch_precondition_exit(args: argparse.Namespace) -> int | None:
    """WOT-2026-058v: run the launch precondition as step 0 of main().

    Before: ``args`` carries the optional ``--flight-launch-context`` value
    (or None when the launch is not a flight launch).
    During: with a context given, runs the launch guard and prints its output;
    a guard with findings stops the launch (exit != 0) before any work runs.
    After: returns 1 when the launch must stop, None when it may proceed.
    """
    if not args.flight_launch_context:
        return None
    findings = check_flight_launch_prerequisites(Path(args.flight_launch_context))
    if findings:
        for finding in findings:
            print(f"[LAUNCH-GUARD] ERROR: {finding}")
        return 1
    print("[OK] Launch guard: el DAG citado por el vuelo esta persistido")
    return None


def main(argv: list[str] | None = None) -> int:  # noqa: C901 - CLI: parser + pasos + precondicion de arranque (WOT-2026-058v); main ya estaba en el umbral (10)
    """Main builder flow."""
    parser = argparse.ArgumentParser(description="Builder agent for the active ticket")
    parser.add_argument(
        "--ticket-id",
        default=None,
        help="Ticket ID to implement (defaults to the active plan_id from work_plan.md)",
    )
    parser.add_argument(
        "--flight-launch-context",
        dest="flight_launch_context",
        default=None,
        help=(
            "WOT-2026-058v: JSON del contexto de arranque del vuelo (forma "
            "batch_run: flight + PREDICATE). El arranque falla cerrado si el "
            "vuelo no cita un DAG validado o si el DAG citado no esta "
            "persistido bajo orchestrator_pipeline/flight_plans/."
        ),
    )
    args = parser.parse_args(argv)

    # WOT-2026-058v: launch precondition runs BEFORE any work. A flight whose
    # PREDICATE cites no DAG, or whose cited DAG does not resolve to a file
    # under flight_plans/**, fails closed here (exit != 0), naming the plan.
    stop = _launch_precondition_exit(args)
    if stop is not None:
        return stop

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
    # WOT-2026-058v (repair, Fase 0 finding): this flow imported
    # `publish_state_changed_event`, a symbol that no longer exists in
    # agent_controller - the module has been unimportable since that removal.
    # The canonical emission (same shape the controller itself uses) replaces
    # the stale call; the mark-ready subprocess below remains the authority.
    if BUS_AVAILABLE and event_bus:
        event_bus.emit(
            event_type="STATE_CHANGED",
            ticket_id=plan_id,
            actor="BUILDER",
            payload={
                "from_state": "IN_PROGRESS",
                "to_state": "READY_FOR_REVIEW",
                "reason": "Builder completed implementation",
                "source": "builder_agent",
            },
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
