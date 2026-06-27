"""Loop hard-stop guard for autonomous pipeline loops.

Receives the current iteration counters from the caller and compares them
against the declared budget limits. When any single limit is crossed the
guard emits BUILDER_EXIT + STATE_CHANGED -> BLOCKED_FINAL to the bus in the
correct order (FP-001), writes a state artifact, and returns STOP.

Owner: this script is the enforcement owner. It is invoked by convention at
the CLOSE of each pipeline iteration. The caller accumulates the counters and
passes them here; the guard does NOT read tokens from the harness (not
possible by design).

Invocation pattern (caller side):
    result = check_and_stop(
        ticket_id="WOT-2026-XYZ",
        iterations_current=n,
        tokens_estimated=t,
        elapsed_seconds=s,
        budget={
            "max_iterations": 50,
            "token_budget_estimated": 200_000,
            "timeout_seconds": 3600,
        },
        project_root=Path("..."),
    )
    if result["stopped"]:
        # exit the loop; partial state is on disk
        break

Source: WOT-2026-014v. Origin: cobusgreyling/loop-engineering (hard stop /
tokens-timeout-iterations limits).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Sentinel values returned by check_and_stop
# ---------------------------------------------------------------------------
STOP = "STOP"
CONTINUE = "CONTINUE"


def _get_engine_root() -> Path:
    """Return the motor repo root (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def _ensure_bus_importable() -> None:
    """Insert engine root into sys.path so bus.event_bus is importable.

    Before: sys.path may not include the engine root.
    During: inserts engine root at position 0 if not already present.
    After:  bus.event_bus is importable; sys.path unchanged if already ok.
    """
    engine_root = str(_get_engine_root())
    if engine_root not in sys.path:
        sys.path.insert(0, engine_root)


def _emit_events(
    ticket_id: str,
    project_root: Path,
    tope_cruzado: str,
    iterations_current: int,
    tokens_estimated: int,
    elapsed_seconds: float,
) -> None:
    """Emit BUILDER_EXIT then STATE_CHANGED -> BLOCKED_FINAL to the bus.

    Before:
        - bus.event_bus is importable (caller ensures _ensure_bus_importable()).
        - project_root exists and is writable.
        - ticket_id is a valid ticket id string.

    During:
        - Emits BUILDER_EXIT (actor=BUILDER) with exit_reason=hard_stop and
          tope_cruzado in payload.
        - Emits STATE_CHANGED -> BLOCKED_FINAL (actor=SUPERVISOR) with reason
          hard_stop in payload.
        - The sequence_number of BUILDER_EXIT is strictly less than that of
          STATE_CHANGED, satisfying the FP-001 invariant.
        - Both events are written to
          <project_root>/.agent/runtime/events/events.jsonl.

    After:
        - Bus has BUILDER_EXIT event with lower seq than STATE_CHANGED.
        - StateMachine.derive_state_from_events for the ticket returns
          TicketState.BLOCKED_FINAL.
        - If either emit returns None (bus guard blocked), continues silently;
          the state artifact (loop_hard_stop_state.json) is still written.
    """
    from bus.event_bus import EventBus

    events_dir = project_root / ".agent" / "runtime" / "events"
    bus = EventBus(runtime_dir=events_dir)

    bus.emit(
        "BUILDER_EXIT",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "exit_reason": "hard_stop",
            "tope_cruzado": tope_cruzado,
            "iterations_at_stop": iterations_current,
            "tokens_at_stop": tokens_estimated,
            "elapsed_seconds_at_stop": elapsed_seconds,
        },
    )

    bus.emit(
        "STATE_CHANGED",
        ticket_id=ticket_id,
        actor="SUPERVISOR",
        payload={
            "to_state": "BLOCKED_FINAL",
            "reason": "hard_stop",
            "tope_cruzado": tope_cruzado,
        },
    )


def _write_state_artifact(
    project_root: Path,
    ticket_id: str,
    tope_cruzado: str,
    iterations_current: int,
    tokens_estimated: int,
    elapsed_seconds: float,
) -> Path:
    """Write loop_hard_stop_state.json with current counters and stop reason.

    Before:
        - project_root/.agent/runtime/ may or may not exist.

    During:
        - Creates directories as needed.
        - Writes JSON artifact with ticket_id, tope_cruzado, counts at stop,
          and timestamp_utc.

    After:
        - File exists at project_root/.agent/runtime/loop_hard_stop_state.json.
        - Contains all required fields: ticket_id, tope_cruzado, timestamp_utc.
    """
    runtime_dir = project_root / ".agent" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = runtime_dir / "loop_hard_stop_state.json"
    state = {
        "ticket_id": ticket_id,
        "tope_cruzado": tope_cruzado,
        "iterations_at_stop": iterations_current,
        "tokens_at_stop": tokens_estimated,
        "elapsed_seconds_at_stop": elapsed_seconds,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    artifact_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return artifact_path


def _try_create_checkpoint(project_root: Path, ticket_id: str) -> None:
    """Invoke create_checkpoint.py --milestone M0 idempotently via subprocess.

    Before:
        - scripts/create_checkpoint.py must exist in the engine root.

    During:
        - Runs create_checkpoint.py with --milestone M0 --ticket-id <ticket_id>.
        - Passes --project-root <project_root> so the checkpoint is associated
          with the correct workspace.
        - Swallows all errors: checkpoint creation is best-effort during stop.

    After:
        - If successful, M0 tag exists in repo; a BUILDER_MILESTONE event was
          emitted by the checkpoint script (idempotent: skip if already exists).
        - On error, logs to stderr and continues.
    """
    engine_root = _get_engine_root()
    checkpoint_script = engine_root / "scripts" / "create_checkpoint.py"
    if not checkpoint_script.exists():
        print(
            f"[loop_hard_stop] WARN: create_checkpoint.py not found at {checkpoint_script}",
            file=sys.stderr,
        )
        return
    try:
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(checkpoint_script),
                "--milestone",
                "M0",
                "--ticket-id",
                ticket_id,
                "--project-root",
                str(project_root),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(
                f"[loop_hard_stop] WARN: create_checkpoint M0 exited {result.returncode}: "
                + result.stderr.strip(),
                file=sys.stderr,
            )
    except Exception as exc:
        print(
            f"[loop_hard_stop] WARN: create_checkpoint failed: {exc}", file=sys.stderr
        )


def _try_diagnose_orphans(project_root: Path) -> None:
    """Invoke diagnose_builder_orphans.py --json via subprocess, best-effort.

    Before:
        - scripts/diagnose_builder_orphans.py must exist in the engine root.

    During:
        - Runs the script with --project-root <project_root> --json.
        - Swallows all errors: diagnosis is informational during stop.

    After:
        - If successful, orphan diagnostic is emitted to the bus by the script.
        - On error, logs a warning and continues.
    """
    engine_root = _get_engine_root()
    orphan_script = engine_root / "scripts" / "diagnose_builder_orphans.py"
    if not orphan_script.exists():
        print(
            f"[loop_hard_stop] WARN: diagnose_builder_orphans.py not found at {orphan_script}",
            file=sys.stderr,
        )
        return
    try:
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(orphan_script),
                "--project-root",
                str(project_root),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(
                f"[loop_hard_stop] WARN: diagnose_orphans exited {result.returncode}",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"[loop_hard_stop] WARN: diagnose_orphans failed: {exc}", file=sys.stderr)


def check_and_stop(
    ticket_id: str,
    iterations_current: int,
    tokens_estimated: int,
    elapsed_seconds: float,
    budget: dict,
    project_root: Path,
) -> dict:
    """Evaluate current counters against declared budget limits and stop if needed.

    Before:
        - ticket_id: non-empty string identifying the active ticket.
        - iterations_current: integer count of loop iterations completed.
        - tokens_estimated: integer count of tokens used (estimated by caller).
        - elapsed_seconds: float wall-clock seconds since the loop started.
        - budget: dict with keys:
            max_iterations (int): tope de iteraciones.
            token_budget_estimated (int): tope de tokens.
            timeout_seconds (float): tope de tiempo wall.
          Missing keys are treated as unlimited (no stop on that dimension).
        - project_root: Path to the workspace root containing .agent/runtime/.
          Must be writable.

    During:
        - Evaluates three conditions simultaneously:
            iterations_current >= budget["max_iterations"]
            tokens_estimated   >= budget["token_budget_estimated"]
            elapsed_seconds    >= budget["timeout_seconds"]
        - If ANY condition is True:
            1. Determines the first tope_cruzado (priority: iterations > tokens > timeout).
            2. Calls _ensure_bus_importable() to prepare import path.
            3. Emits BUILDER_EXIT (actor=BUILDER) to bus with tope_cruzado in payload.
            4. Emits STATE_CHANGED -> BLOCKED_FINAL (actor=SUPERVISOR) to bus.
            5. Writes loop_hard_stop_state.json under project_root/.agent/runtime/.
            6. Invokes create_checkpoint.py --milestone M0 (idempotent, best-effort).
            7. Invokes diagnose_builder_orphans.py --json (best-effort).
        - If NO condition is True:
            - Returns immediately with stopped=False.

    After (stop case):
        - Returns dict: {stopped: True, reason: <tope_cruzado>, ...<counters>}.
        - BUILDER_EXIT sequence_number < STATE_CHANGED sequence_number in bus.
        - StateMachine.derive_state_from_events for ticket returns BLOCKED_FINAL.
        - loop_hard_stop_state.json contains ticket_id, tope_cruzado, timestamp_utc.

    After (continue case):
        - Returns dict: {stopped: False, reason: None, ...<counters>}.
        - Bus is unmodified.
        - loop_hard_stop_state.json is NOT written.
    """
    max_iterations = budget.get("max_iterations")
    token_budget = budget.get("token_budget_estimated")
    timeout_seconds_limit = budget.get("timeout_seconds")

    iterations_exceeded = (
        max_iterations is not None and iterations_current >= max_iterations
    )
    tokens_exceeded = token_budget is not None and tokens_estimated >= token_budget
    timeout_exceeded = (
        timeout_seconds_limit is not None and elapsed_seconds >= timeout_seconds_limit
    )

    if not (iterations_exceeded or tokens_exceeded or timeout_exceeded):
        return {
            "stopped": False,
            "reason": None,
            "iterations_current": iterations_current,
            "tokens_estimated": tokens_estimated,
            "elapsed_seconds": elapsed_seconds,
        }

    # Determine primary tope (priority: iterations > tokens > timeout)
    if iterations_exceeded:
        tope_cruzado = "iterations"
    elif tokens_exceeded:
        tope_cruzado = "tokens"
    else:
        tope_cruzado = "timeout"

    _ensure_bus_importable()
    _emit_events(
        ticket_id=ticket_id,
        project_root=project_root,
        tope_cruzado=tope_cruzado,
        iterations_current=iterations_current,
        tokens_estimated=tokens_estimated,
        elapsed_seconds=elapsed_seconds,
    )
    _write_state_artifact(
        project_root=project_root,
        ticket_id=ticket_id,
        tope_cruzado=tope_cruzado,
        iterations_current=iterations_current,
        tokens_estimated=tokens_estimated,
        elapsed_seconds=elapsed_seconds,
    )
    _try_create_checkpoint(project_root=project_root, ticket_id=ticket_id)
    _try_diagnose_orphans(project_root=project_root)

    return {
        "stopped": True,
        "reason": tope_cruzado,
        "iterations_current": iterations_current,
        "tokens_estimated": tokens_estimated,
        "elapsed_seconds": elapsed_seconds,
    }


def resume_predicate(project_root: Path, ticket_id: str) -> bool:
    """Return True if the ticket is safe to resume after a hard stop.

    Owner: supervisor/runtime (not the executor that was stopped).

    The predicate checks three conditions simultaneously:
    1. The last event in the bus for ticket_id is a terminal-coherent event
       (BLOCKED_FINAL or another terminal state from IRREVERSIBLE_TERMINAL_STATES).
    2. The git working tree of project_root is clean (no uncommitted changes).
    3. A checkpoint M0 tag exists for the ticket (checkpoint/base-<ticket_id>).

    If all three are True, the ticket can be re-submitted to the pipeline from
    the last known state. Resuming twice from the same state is safe
    (idempotent): the bus de-duplication guard prevents duplicate terminal
    events, and the checkpoint is idempotent (skip if already exists).

    Before:
        - project_root: must be a valid path; .agent/runtime/events/events.jsonl
          may not exist (no events = cannot resume).
        - ticket_id: must be a non-empty string.

    During:
        - Reads bus events for ticket_id via EventBus.read_events().
        - Calls StateMachine.derive_state_from_events() to get last state.
        - Runs git status --porcelain in project_root to check clean tree.
        - Checks existence of git tag checkpoint/base-<ticket_id>.

    After:
        - Returns True only if ALL three conditions are met.
        - Returns False if any condition fails, including import errors or
          subprocess failures (fail-closed).
    """
    _ensure_bus_importable()
    try:
        from bus.event_bus import EventBus
        from bus.state_machine import (
            IRREVERSIBLE_TERMINAL_STATES,
            StateMachine,
        )
    except Exception as exc:
        print(
            f"[loop_hard_stop] resume_predicate: import failed: {exc}", file=sys.stderr
        )
        return False

    # Condition 1: terminal-coherent bus state
    events_dir = project_root / ".agent" / "runtime" / "events"
    bus = EventBus(runtime_dir=events_dir)
    events = [e.to_dict() for e in bus.read_events(ticket_id=ticket_id)]
    if not events:
        return False
    state = StateMachine.derive_state_from_events(events)
    if state not in IRREVERSIBLE_TERMINAL_STATES:
        return False

    # Condition 2: clean git working tree
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=10,
        )
        if result.returncode != 0 or result.stdout.strip():
            return False
    except Exception:
        return False

    # Condition 3: M0 checkpoint tag exists
    tag_name = f"checkpoint/base-{ticket_id}"
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", tag_name],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=10,
        )
        if result.returncode != 0:
            return False
    except Exception:
        return False

    return True
