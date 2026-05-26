# Work Plan - WP-2026-146

## Metadata
- **ID:** WP-2026-146
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Human gate approval timeout wiring
- **Asignado a:** Builder

## Objetivo
Wire `HUMAN_GATE` escalation into the existing `ApprovalStore` so timeout handling is persistent and survives restarts instead of being recreated ad hoc in the supervisor loop. The implementation should reuse the approval-resolution contract already present in `bus/approval.py`, keep the current state machine semantics intact, and stay small enough to close in one cycle.

## Decision Arquitectonica
- `agent_controller.py` will include timeout metadata when a ticket is escalated to `HUMAN_GATE`.
- `bus/approval.py` already provides the persistent approval model; the ticket escalation must create an `ApprovalRequest` there instead of inventing a new timeout store.
- `bus/supervisor.py` already calls `check_and_expire_all()` and will consume the persisted approval request on its normal loop.
- `agents.json` should provide the timeout value alongside `manager_review.max_attempts`, with a documented fallback if the setting is absent.
- The existing `APPROVAL_RESOLVED` -> `BLOCKED` path remains the canonical expiry contract.
- `TURN.md` stays under controller ownership and is out of scope for this ticket.
- No new terminal state is introduced; the timeout uses the approval resolution contract already understood by the bus.
- The change is about bounded waiting and explicit expiry, not a broader runtime refactor.

## Files Likely Touched
- `.agent/agent_controller.py`
- `bus/approval.py`
- `bus/supervisor.py`
- `tests/unit/test_human_gate_timeout.py`

## Fases
1. Add timeout metadata to the `STATE_CHANGED -> HUMAN_GATE` handoff.
2. Create and persist an `ApprovalRequest` when the ticket is escalated to `HUMAN_GATE`.
3. Let the supervisor expire the stored request via its existing approval timeout loop.
4. Add unit tests for expired, non-expired, and restart-survivability cases.
5. Confirm the timeout flow does not change the existing `resume-human-gate` behavior.

## Calidad
- `python scripts/run_pytest_safe.py tests/unit/test_human_gate_timeout.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `HUMAN_GATE` carries explicit timeout metadata at handoff.
- The escalation persists an `ApprovalRequest` so the gate survives restarts.
- An expired `HUMAN_GATE` resolves automatically through the canonical approval-resolution path.
- A fresh `HUMAN_GATE` does not expire early.
- The timeout value is sourced from configuration with a documented fallback.
- The existing `resume-human-gate` path remains valid after the timeout change.
- Canonical validation passes without new warnings or errors.
