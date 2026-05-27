# Work Plan - WP-2026-152

## Metadata
- **ID:** WP-2026-152
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Repair request-changes requeue handoff
- **Asignado a:** Builder

## Objetivo
Fix the `--request-changes` handoff so the builder requeue does not deadlock when the bus has already advanced to `IN_PROGRESS` as a consequence of an immediate `REVIEW_DECISION=changes`. The handler must accept the pending requeue only when the latest relevant bus event proves that `changes` is the direct antecedent, and the bridge must keep logging non-zero `--request-changes` returncodes for visibility. The supervisor dedupe/trigger refinement is intentionally out of scope for this ticket.

## Decision Arquitectonica
- The bus remains the source of truth for whether a requeue is pending.
- `_handle_request_changes()` must derive `pending_requeue` from the `events` slice already read for the bus-state derivation, using `events[-1]` when present; it must not perform a second `latest_event()` read.
- The control flow must be explicit: `UNKNOWN` falls back to the existing execution_log path, `READY_FOR_REVIEW` proceeds normally, `IN_PROGRESS` is only accepted when `pending_requeue` is true, and all other states fail closed.
- Generic `IN_PROGRESS` without that antecedent must still fail closed.
- The review bridge stderr logging for failed `--request-changes` calls is observability only and must not change the transition semantics.
- Supervisor-side dedupe or relaunch policy changes are deferred to a future WP.
- No new dependencies are allowed.
- The fix should preserve the existing canonical materialization path and not redesign the review flow.

## Files Likely Touched
- `.agent/agent_controller.py`
- `bus/review_bridge.py`
- `tests/unit/test_request_changes_requeue.py`
- `tests/unit/test_review_bridge_request_changes_logging.py`

## Fases
1. Tighten `_handle_request_changes()` so it derives `pending_requeue` from the already-read bus events, uses the explicit `UNKNOWN` / `READY_FOR_REVIEW` / `IN_PROGRESS` / fallback branching above, and only accepts the `IN_PROGRESS` continuation when the direct `REVIEW_DECISION=changes` antecedent is present.
2. The bridge stderr logging for non-zero `--request-changes` returncodes is already implemented in `bus/review_bridge.py` as a prior hotfix. Do not re-implement it. The only deliverable for this phase is adding the test in `tests/unit/test_review_bridge_request_changes_logging.py` that verifies the logging behavior.
3. Add unit tests that cover the allowed requeue path, the generic `IN_PROGRESS` rejection path, the `UNKNOWN` + execution_log fallback path, and the bridge logging behavior.
4. Keep the supervisor dedupe/trigger change out of scope and document it explicitly as deferred work.
5. Refresh project metadata so the new cycle is the active ticket.

## Calidad
- `python scripts/run_pytest_safe.py tests/unit/test_request_changes_requeue.py tests/unit/test_review_bridge_request_changes_logging.py -q`
- `ruff check .agent scripts tests`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `--request-changes` no longer deadlocks when the bus has already moved to `IN_PROGRESS` because of an immediate `REVIEW_DECISION=changes`.
- A generic `IN_PROGRESS` without that immediate antecedent still fails closed.
- The handler reuses the bus events already read in the function and does not perform a redundant `latest_event()` bus read.
- The handler preserves the existing `UNKNOWN` fallback to execution_log when the bus has no usable state.
- The bridge logs the failed `--request-changes` returncode and stderr without changing the transition semantics.
- The new tests cover the allowed path, the blocked path, the `UNKNOWN` fallback path, and the logging behavior.
- No supervisor dedupe or relaunch policy changes land in this ticket.
- Canonical validation passes without new warnings or errors.
