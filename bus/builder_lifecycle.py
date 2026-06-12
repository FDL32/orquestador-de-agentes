"""Builder lifecycle facade extracted from ``bus.supervisor``.

This facade keeps the historical import surface stable while delegating lock,
relaunch, and capsule responsibilities to focused modules extracted from the
original ``builder_lifecycle`` monolith.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from .approval import ApprovalReason
from .builder_capsule import (  # noqa: F401
    _build_relaunch_capsule,
    _capsule_blockers_from_turn,
    _capsule_hechos_from_bus,
    _capsule_hechos_from_log_tail,
    _capsule_hechos_from_state,
    _capsule_hechos_from_work_plan,
    _capsule_hipotesis_from_log,
)
from .builder_locks import (  # noqa: F401
    MANAGER_STALE_TIMEOUT,
    RELAUNCH_BLOCKED_STATES,
    REQUEUE_CLAIMS_DIRNAME,
    _REQUEUE_CLAIM_TTL_ENV,
    _claim_requeue,
    _cleanup_terminal_requeue_claims,
    _emit_supervisor_restarted_if_requested,
    _get_claim_ttl,
    _has_builder_exited_after,
    _has_handoff_blocked_after_sequence,
    _has_relaunched_for_trigger,
    _is_manager_bridge_stale,
    _is_pid_alive,
    _latest_changes_trigger_sequence,
    _load_manager_bridge_state,
    _parse_iso_datetime,
    _should_stop_run_reactive,
    _timeout_from_env,
    builder_alive,
    bus_cleanup_builder_session,
)
from .builder_relaunch import (  # noqa: F401
    _BUILDER_START_VERIFY_TIMEOUT_DEFAULT,
    _BUILDER_START_VERIFY_TIMEOUT_ENV,
    _check_artifact,
    _get_verify_timeout,
    _materialize_turn_blockers,
    _persist_relaunch_log,
    _relaunch_builder,
    _resolve_launcher_path,
    _run_launcher_subprocess,
    _verify_builder_start,
    _verify_relaunch_topology,
)
from .event_bus import EventBus
from .state_machine import TicketState


def requeue_ticket(
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    ticket_id: str,
    trigger_seq: int = 0,
    load_state_fn=None,
    save_state_fn=None,
    current_state_fn=None,
    relaunch_builder_fn=None,
    builder_alive_fn=None,
    run_launcher_fn=None,
    claim_requeue_fn=None,
) -> bool:
    if not isinstance(trigger_seq, int) or trigger_seq <= 0:
        print(
            f"[ticket-supervisor] requeue_ticket: invalid trigger_seq={trigger_seq} "
            f"for {ticket_id}. Failing closed.",
            flush=True,
        )
        return False

    claim_requeue = claim_requeue_fn or (
        lambda tid, seq: _claim_requeue(runtime_dir, event_bus, tid, seq)
    )
    if not claim_requeue(ticket_id, trigger_seq):
        print(
            f"[ticket-supervisor] requeue_ticket: claim denied for "
            f"{ticket_id} seq={trigger_seq}. Skipping relaunch.",
            flush=True,
        )
        return False

    if load_state_fn:
        state = load_state_fn()
    else:
        return False
    if state.active_ticket != ticket_id:
        return False

    if current_state_fn:
        current_state = current_state_fn(ticket_id)
    else:
        return False
    if current_state in RELAUNCH_BLOCKED_STATES:
        print(
            f"[ticket-supervisor] Skipping Builder relaunch for {ticket_id}: "
            f"ticket is {current_state.value}",
            flush=True,
        )
        return False

    state.last_requeue_trigger_sequence = trigger_seq
    state.loop_current_round += 1
    if save_state_fn:
        save_state_fn(state)
    print(
        f"[ticket-supervisor] Detected requeue for {ticket_id} "
        f"(round {state.loop_current_round}). Relaunching Builder...",
        flush=True,
    )
    if relaunch_builder_fn:
        return relaunch_builder_fn(ticket_id, trigger_seq)
    return _relaunch_builder(
        project_root=project_root,
        runtime_dir=runtime_dir,
        collaboration_dir=collaboration_dir,
        event_bus=event_bus,
        state_path_file=state_path_file,
        turn_path=turn_path,
        work_plan_path=work_plan_path,
        execution_log_path=execution_log_path,
        ticket_id=ticket_id,
        trigger_seq=trigger_seq,
        load_state_fn=load_state_fn,
        save_state_fn=save_state_fn,
        builder_alive_fn=builder_alive_fn,
        run_launcher_fn=run_launcher_fn,
    )


def _bootstrap_requeue_if_needed(  # noqa: C901
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    ticket_id: str,
    load_state_fn=None,
    save_state_fn=None,
    current_state_fn=None,
    requeue_ticket_fn=None,
    relaunch_builder_fn=None,
    builder_alive_fn=None,
    run_launcher_fn=None,
    cleanup_session_fn=None,
    materialize_turn_blockers_fn=None,
) -> bool:
    if load_state_fn is None:
        return False
    state = load_state_fn()

    requeue_trigger_seq = _latest_changes_trigger_sequence(
        event_bus.read_events(ticket_id=ticket_id), ticket_id=ticket_id
    )

    if not (
        requeue_trigger_seq > 0
        and requeue_trigger_seq > state.last_requeue_trigger_sequence
    ):
        return False

    current_ticket_state = current_state_fn(ticket_id) if current_state_fn else None
    if current_ticket_state is None:
        return False
    state_ok = current_ticket_state == TicketState.IN_PROGRESS or (
        current_ticket_state == TicketState.READY_FOR_REVIEW
        and requeue_trigger_seq > 0
        and requeue_trigger_seq > state.last_processed_sequence
    )
    if not state_ok:
        return False
    if current_ticket_state == TicketState.READY_FOR_REVIEW:
        print(
            f"[supervisor] bootstrap: spurious READY_FOR_REVIEW detected for {ticket_id} "
            f"after CHANGES at seq={requeue_trigger_seq} - crash during relaunch suspected. "
            "Forcing Builder requeue.",
            flush=True,
        )

    alive_check = (
        builder_alive_fn
        if builder_alive_fn
        else (lambda: builder_alive(runtime_dir, event_bus))
    )
    if alive_check():
        print(
            f"[supervisor] bootstrap: Builder lock is fresh for {ticket_id}, "
            "deferring requeue until lock expires.",
            flush=True,
        )
        event_bus.emit(
            "SUPERVISOR_REQUEUE_DEFERRED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "trigger_sequence": requeue_trigger_seq,
                "reason": "builder_lock_fresh",
                "watermark": state.last_requeue_trigger_sequence,
            },
        )
        return False

    blocking_seq = _has_handoff_blocked_after_sequence(
        event_bus, ticket_id, requeue_trigger_seq
    )
    if blocking_seq > 0:
        print(
            f"[supervisor] bootstrap: HANDOFF_BLOCKED at seq={blocking_seq} after "
            f"trigger seq={requeue_trigger_seq} for {ticket_id}. "
            "Suppressing relaunch.",
            flush=True,
        )
        event_bus.emit(
            "RELAUNCH_SUPPRESSED",
            ticket_id=ticket_id,
            actor="SUPERVISOR",
            payload={
                "reason": "handoff_blocked",
                "trigger_sequence": requeue_trigger_seq,
                "blocking_sequence": blocking_seq,
            },
        )
        return False

    print(
        f"[supervisor] bootstrap: unprocessed CHANGES trigger at seq={requeue_trigger_seq} "
        f"for {ticket_id}. Firing requeue.",
        flush=True,
    )
    if cleanup_session_fn:
        cleanup_session_fn()
    else:
        bus_cleanup_builder_session(runtime_dir)

    if materialize_turn_blockers_fn:
        materialize_turn_blockers_fn(ticket_id)
    else:
        _materialize_turn_blockers(collaboration_dir, event_bus, ticket_id)

    impl = requeue_ticket_fn if requeue_ticket_fn else requeue_ticket
    if requeue_ticket_fn:
        return requeue_ticket_fn(ticket_id, requeue_trigger_seq)
    return impl(
        runtime_dir=runtime_dir,
        event_bus=event_bus,
        project_root=project_root,
        collaboration_dir=collaboration_dir,
        state_path_file=state_path_file,
        turn_path=turn_path,
        work_plan_path=work_plan_path,
        execution_log_path=execution_log_path,
        ticket_id=ticket_id,
        trigger_seq=requeue_trigger_seq,
        load_state_fn=load_state_fn,
        save_state_fn=save_state_fn,
        current_state_fn=current_state_fn,
        relaunch_builder_fn=relaunch_builder_fn,
        builder_alive_fn=builder_alive_fn,
        run_launcher_fn=run_launcher_fn,
    )


def run_once(  # noqa: C901
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    load_state_fn=None,
    save_state_fn=None,
    transition_ticket_fn=None,
    get_approval_store_fn=None,
    advance_if_review_ready_fn=None,
    current_state_fn=None,
    materialize_ticket_projection_fn=None,
    relaunch_builder_fn=None,
    builder_alive_fn=None,
    run_launcher_fn=None,
    process_new_events_fn=None,
    requeue_ticket_fn=None,
) -> tuple[bool, bool]:
    if load_state_fn is None:
        return False, False
    state = load_state_fn()

    if get_approval_store_fn:
        try:
            store = get_approval_store_fn()
            expired = store.check_and_expire_all()
            for req in expired:
                target_state = "BLOCKED"
                if req.reason == ApprovalReason.TIMEOUT_EXPIRED:
                    target_state = "BLOCKED"
                    if transition_ticket_fn:
                        transition_ticket_fn(
                            ticket_id=req.ticket_id,
                            new_state=target_state,
                            reason=f"Approval {req.approval_id} expired after {req.timeout_seconds}s",
                        )
                event_bus.emit(
                    "APPROVAL_RESOLVED",
                    ticket_id=req.ticket_id,
                    actor="SUPERVISOR",
                    payload={
                        "approval_id": req.approval_id,
                        "status": req.status.value,
                        "reason": req.reason.value if req.reason else "TIMEOUT_EXPIRED",
                        "to_state": target_state,
                        "message": "Approval expired automatically by supervisor timeout policy",
                    },
                )
                print(
                    f"[ticket-supervisor] Auto-expired approval {req.approval_id}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[ticket-supervisor] Error checking approval timeouts: {exc}",
                file=sys.stderr,
                flush=True,
            )

    previous_sequence = state.last_processed_sequence
    events = event_bus.read_events()
    new_events = [
        event
        for event in events
        if event.sequence_number > state.last_processed_sequence
    ]

    changed = process_new_events_fn() if process_new_events_fn else False
    state = load_state_fn()
    event_activity = state.last_processed_sequence > previous_sequence

    if (
        state.active_ticket
        and materialize_ticket_projection_fn
        and materialize_ticket_projection_fn(
            state.active_ticket,
            current_state_fn(state.active_ticket)
            if current_state_fn
            else TicketState.UNKNOWN,
        )
    ):
        changed = True

    requeue_trigger_sequence = _latest_changes_trigger_sequence(
        new_events, ticket_id=state.active_ticket
    )

    requeue_triggered = (
        requeue_trigger_sequence > 0
        and requeue_trigger_sequence > state.last_requeue_trigger_sequence
    )

    requeue_success = False
    if requeue_triggered and state.active_ticket:
        blocking_seq = _has_handoff_blocked_after_sequence(
            event_bus, state.active_ticket, requeue_trigger_sequence
        )
        if blocking_seq > 0:
            print(
                f"[supervisor] run_once: HANDOFF_BLOCKED at seq={blocking_seq} after "
                f"trigger seq={requeue_trigger_sequence} for {state.active_ticket}. "
                "Suppressing relaunch.",
                flush=True,
            )
            event_bus.emit(
                "RELAUNCH_SUPPRESSED",
                ticket_id=state.active_ticket,
                actor="SUPERVISOR",
                payload={
                    "reason": "handoff_blocked",
                    "trigger_sequence": requeue_trigger_sequence,
                    "blocking_sequence": blocking_seq,
                },
            )
        else:
            _materialize_turn_blockers(
                collaboration_dir, event_bus, state.active_ticket
            )
            requeue_succeeded = (
                requeue_ticket_fn(state.active_ticket, requeue_trigger_sequence)
                if requeue_ticket_fn
                else requeue_ticket(
                    runtime_dir=runtime_dir,
                    event_bus=event_bus,
                    project_root=project_root,
                    collaboration_dir=collaboration_dir,
                    state_path_file=state_path_file,
                    turn_path=turn_path,
                    work_plan_path=work_plan_path,
                    execution_log_path=execution_log_path,
                    ticket_id=state.active_ticket,
                    trigger_seq=requeue_trigger_sequence,
                    load_state_fn=load_state_fn,
                    save_state_fn=save_state_fn,
                    current_state_fn=current_state_fn,
                    relaunch_builder_fn=relaunch_builder_fn,
                    builder_alive_fn=builder_alive_fn,
                    run_launcher_fn=run_launcher_fn,
                )
            )
            if requeue_succeeded:
                changed = True
                requeue_success = True

    if advance_if_review_ready_fn and advance_if_review_ready_fn():
        changed = True
    return changed or event_activity, requeue_success


def run_reactive(
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    bootstrap_fn=None,
    load_state_fn=None,
    save_state_fn=None,
    transition_ticket_fn=None,
    get_approval_store_fn=None,
    advance_if_review_ready_fn=None,
    current_state_fn=None,
    materialize_ticket_projection_fn=None,
    release_supervisor_lock_fn=None,
    relaunch_builder_fn=None,
    run_once_fn=None,
    builder_alive_fn=None,
    get_requeue_triggered_fn=None,
    clear_requeue_triggered_fn=None,
    timeout_seconds: float = 300.0,
):
    if bootstrap_fn is None or bootstrap_fn() is False:
        return False

    _emit_supervisor_restarted_if_requested(runtime_dir, event_bus, load_state_fn)

    state_after_bootstrap = load_state_fn() if load_state_fn else None
    if not state_after_bootstrap or not state_after_bootstrap.active_ticket:
        print(
            "[supervisor] idle: no active ticket. Waiting for Manager to create a new plan.",
            flush=True,
        )
        event_bus.emit(
            "SUPERVISOR_IDLE",
            ticket_id="__bootstrap__",
            actor="SUPERVISOR",
            payload={"reason": "no active ticket after bootstrap"},
        )

    idle_timeout = _timeout_from_env(
        "TICKET_SUPERVISOR_IDLE_TIMEOUT_SECONDS", timeout_seconds
    )
    max_runtime = _timeout_from_env("TICKET_SUPERVISOR_MAX_RUNTIME_SECONDS", 3600.0)
    start_time = time.time()
    last_activity = start_time
    changed = False
    try:
        while True:
            if _should_stop_run_reactive(
                start_time=start_time,
                last_activity=last_activity,
                idle_timeout=idle_timeout,
                max_runtime=max_runtime,
                now=time.time(),
                runtime_dir=runtime_dir,
                event_bus=event_bus,
                builder_alive_fn=builder_alive_fn,
            ):
                break
            run_changed = (
                run_once_fn()
                if run_once_fn
                else run_once(
                    runtime_dir=runtime_dir,
                    event_bus=event_bus,
                    project_root=project_root,
                    collaboration_dir=collaboration_dir,
                    state_path_file=state_path_file,
                    turn_path=turn_path,
                    work_plan_path=work_plan_path,
                    execution_log_path=execution_log_path,
                    load_state_fn=load_state_fn,
                    save_state_fn=save_state_fn,
                    transition_ticket_fn=transition_ticket_fn,
                    get_approval_store_fn=get_approval_store_fn,
                    advance_if_review_ready_fn=advance_if_review_ready_fn,
                    current_state_fn=current_state_fn,
                    materialize_ticket_projection_fn=materialize_ticket_projection_fn,
                    relaunch_builder_fn=relaunch_builder_fn,
                )[0]
            )
            if run_changed:
                changed = True
                last_activity = time.time()
            if get_requeue_triggered_fn and get_requeue_triggered_fn():
                if clear_requeue_triggered_fn:
                    clear_requeue_triggered_fn()
                print(
                    "[supervisor] Builder-only requeue: staying alive as watcher",
                    flush=True,
                )
            time.sleep(1.0)
    finally:
        if release_supervisor_lock_fn:
            release_supervisor_lock_fn()
    return changed


def run_loop(
    runtime_dir: Path,
    event_bus: EventBus,
    project_root: Path,
    collaboration_dir: Path,
    state_path_file: Path,
    turn_path: Path,
    work_plan_path: Path,
    execution_log_path: Path,
    bootstrap_fn=None,
    load_state_fn=None,
    save_state_fn=None,
    transition_ticket_fn=None,
    get_approval_store_fn=None,
    advance_if_review_ready_fn=None,
    current_state_fn=None,
    materialize_ticket_projection_fn=None,
    release_supervisor_lock_fn=None,
    relaunch_builder_fn=None,
    run_once_fn=None,
    poll_interval: float = 1.0,
):
    if bootstrap_fn is None or bootstrap_fn() is False:
        return
    try:
        while True:
            if run_once_fn:
                run_once_fn()
            else:
                run_once(
                    runtime_dir=runtime_dir,
                    event_bus=event_bus,
                    project_root=project_root,
                    collaboration_dir=collaboration_dir,
                    state_path_file=state_path_file,
                    turn_path=turn_path,
                    work_plan_path=work_plan_path,
                    execution_log_path=execution_log_path,
                    load_state_fn=load_state_fn,
                    save_state_fn=save_state_fn,
                    transition_ticket_fn=transition_ticket_fn,
                    get_approval_store_fn=get_approval_store_fn,
                    advance_if_review_ready_fn=advance_if_review_ready_fn,
                    current_state_fn=current_state_fn,
                    materialize_ticket_projection_fn=materialize_ticket_projection_fn,
                    relaunch_builder_fn=relaunch_builder_fn,
                )
            time.sleep(poll_interval)
    finally:
        if release_supervisor_lock_fn:
            release_supervisor_lock_fn()
