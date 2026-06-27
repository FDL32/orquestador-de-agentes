# Loop Hard-Stop Protocol

contract_id: cid-loop-hard-stop-v0
source_ticket: WOT-2026-014v
source_of_truth: prompts/_shared/loop_hard_stop.md

---

## Purpose

This prompt declares the kill-switch protocol for autonomous pipeline loops.
The OWNER of the cut decision is the guard code: scripts/loop_hard_stop.py.
The prompt establishes the OBLIGATION of the caller to invoke the guard at the
CLOSE of each iteration. Without this invocation, the guard exists but is not
called -- making the cut a suggestion, not an enforcement.

---

## Owner

Owner of the hard stop: scripts/loop_hard_stop.py

The caller (orchestrator, pipeline runner, or /goal loop) MUST invoke
check_and_stop() at the CLOSE of each pipeline iteration and act on the
returned result. The guard does NOT self-invoke; invocation is by convention.

The owner is NOT the executor being monitored. An executor cannot reliably
self-terminate (same bias that WOT-2026-014t attacks).

---

## Three Simultaneous Limits

The guard evaluates three limits at every invocation. Any single limit crossing
triggers an immediate stop (OR logic, not AND):

1. max_iterations      -- integer, tope de iteraciones
2. token_budget_estimated -- integer, tope de tokens estimados acumulados
3. timeout_seconds     -- float, tope de tiempo wall en segundos

These limits are declared in the loop budget BEFORE starting /goal. They are
NOT estimated in runtime by the guard. Reference: prompts/_shared/loop_budget.md

The caller accumulates the current counters and passes them to the guard. The
guard DOES NOT read tokens or time from the harness (not possible by design).

---

## Invocation Pattern (caller obligation)

At the CLOSE of each pipeline iteration:

    result = check_and_stop(
        ticket_id="WOT-YYYY-NNNx",
        iterations_current=n,
        tokens_estimated=total_tokens_so_far,
        elapsed_seconds=time.monotonic() - loop_start,
        budget={
            "max_iterations": 50,
            "token_budget_estimated": 200_000,
            "timeout_seconds": 3600,
        },
        project_root=Path("path/to/workspace"),
    )
    if result["stopped"]:
        # Loop terminates here. Partial state is on disk.
        break

If the caller omits this invocation, the hard-stop does not run, making the
budget declaration an empty promise.

---

## Stop Protocol (executed by the guard on limit crossing)

When any limit is crossed the guard executes the following steps IN ORDER:

1. Emits BUILDER_EXIT (actor=BUILDER, exit_reason=hard_stop) to the bus.
2. Emits STATE_CHANGED -> BLOCKED_FINAL (actor=SUPERVISOR) to the bus.
   Note: BUILDER_EXIT sequence_number MUST be strictly less than
   STATE_CHANGED sequence_number (FP-001 invariant, anti-drift).
3. Writes .agent/runtime/loop_hard_stop_state.json with:
   - ticket_id
   - tope_cruzado (iterations | tokens | timeout)
   - counters at stop
   - timestamp_utc
4. Invokes create_checkpoint.py --milestone M0 (idempotent, best-effort).
5. Invokes diagnose_builder_orphans.py --json (best-effort, informational).

The guard returns dict {stopped: True, reason: <tope_cruzado>, ...}.

---

## Bus State After Stop

The bus state for the ticket after a hard stop is BLOCKED_FINAL.

StateMachine.derive_state_from_events returns TicketState.BLOCKED_FINAL.
This is an irreversible terminal state (see IRREVERSIBLE_TERMINAL_STATES in
bus/state_machine.py).

In reports and post-mortems the status may be labeled DOCUMENTED-BLOCKED
for human readability, but the canonical bus state is BLOCKED_FINAL.

---

## Resume Predicate

Owner of the resume decision: supervisor / runtime pipeline (NOT the executor
that was stopped).

A stopped ticket is safe to resume only when ALL three conditions are met:

1. Bus terminal-coherent: the last event for the ticket in the bus represents
   a terminal state (BLOCKED_FINAL or another IRREVERSIBLE_TERMINAL_STATES).
2. Clean working tree: git status --porcelain in project_root returns empty.
3. Checkpoint exists: git tag checkpoint/base-<ticket_id> exists.

The guard provides resume_predicate(project_root, ticket_id) -> bool that
evaluates these three conditions. It is designed to be called by the
supervisor, not the executor.

---

## Idempotence Contract

Resuming twice from the same partial state must produce the same result:

- The bus deduplication guard prevents duplicate terminal events.
- create_checkpoint.py --milestone M0 is idempotent (skips if tag exists).
- loop_hard_stop_state.json is overwritten on re-invocation (same content).

A caller that calls resume_predicate twice without changing state gets the same
boolean result both times. No side effects accumulate.

---

## Priority of Limits (tope_cruzado)

When more than one limit is crossed simultaneously, the guard reports the
primary tope in priority order: iterations > tokens > timeout. All limits are
still enforced (any crossing triggers stop), but the reported reason reflects
the highest-priority crossing.

---

## References

- Budget declaration template: prompts/_shared/loop_budget.md
- Run-log for token accounting: prompts/_shared/loop_run_log.md
- Guard implementation: scripts/loop_hard_stop.py
- Bus state machine: bus/state_machine.py (BLOCKED_FINAL in TicketState enum)
- Anti-drift pattern: docs/KNOWN_FAILURE_PATTERNS.md (FP-001)
- Source origin: cobusgreyling/loop-engineering (WOT-2026-014v, CREDITS.md)
