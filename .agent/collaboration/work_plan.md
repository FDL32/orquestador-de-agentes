# Work Plan - WP-2026-149

## Metadata
- **ID:** WP-2026-149
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Bus-backed STATE projection sync
- **Asignado a:** Builder

## Objetivo
Make `STATE.md` a deterministic projection of the bus state so the human-readable state cannot drift behind `events.jsonl`. The ticket should reuse the existing projection probe logic as the foundation, keep the behavior idempotent, and avoid changing the review or builder flows beyond the state sync path.

## Decision Arquitectonica
- `STATE.md` will be synchronized from the bus-derived state instead of relying on handwritten markdown updates.
- The existing deterministic probe logic is the source of truth for the comparison and should be refactored or reused, not duplicated.
- The canonical `STATE.md` format will be the simple `Estado actual: VALUE` line, without bullet or bold markers, and the controller write path should be aligned to that format. The sync path must write that same plain line format.
- The sync path must be idempotent and safe to call repeatedly.
- Missing bus data must degrade gracefully without breaking the rest of the workflow.
- `TURN.md` remains controller-owned and out of scope.
- No new dependencies are allowed.
- The change is about eliminating projection drift, not redesigning the bus or the manager review flow.

## Files Likely Touched
- `.agent/agent_controller.py`
- `scripts/state_projection_sync.py`
- `scripts/state_projection_probe.py`
- `tests/unit/test_state_projection_probe.py`
- `tests/unit/test_state_projection_sync.py`

## Fases
1. Extract or reuse the bus-derived state projection logic so it can be called without mutating the probe contract.
2. Add an idempotent sync path that updates `STATE.md` from the bus-derived state when drift exists, and writes the canonical plain `Estado actual: VALUE` line.
3. Call the sync path from the main controller status route (`python .agent/agent_controller.py` with no flags) and from `--validate`, so drift is healed both in the human status path and in diagnostics.
4. Keep the no-bus and missing-state fallbacks graceful.
5. Add focused tests for matched, drifted, empty-bus, and missing-state cases.
6. Fix the markdown parser so it only trusts `Estado actual:` when the `# State - {ticket_id}` header matches the active ticket.

## Calidad
- `python scripts/run_pytest_safe.py tests/unit/test_state_projection_probe.py -q`
- `python scripts/run_pytest_safe.py tests/unit/test_state_projection_sync.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `STATE.md` can be synchronized from the bus-derived state without manual edits.
- The sync path is idempotent and safe to call more than once.
- The controller heals drift from the main status path and from `--validate`.
- Missing bus data or missing `STATE.md` falls back gracefully.
- The deterministic probe remains read-only and still reports drift when appropriate.
- `_parse_markdown_state(ticket_id)` validates the ticket header before trusting the state line.
- Canonical validation passes without new warnings or errors.
