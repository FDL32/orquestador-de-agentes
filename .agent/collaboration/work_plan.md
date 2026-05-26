# Work Plan - WP-2026-145

## Metadata
- **ID:** WP-2026-145
- **Estado:** COMPLETED
- **deliverable_type:** research
- **Titulo:** Deterministic STATE projection probe
- **Asignado a:** Builder

## Objetivo
Build a standalone read-only probe that reconstructs the active ticket state deterministically from `events.jsonl`, compares it against `STATE.md`, and reports any drift. The goal is to validate whether the bus can serve as single source of truth for state projection, before deciding whether to promote this into the runtime controller.

## Decision Arquitectonica
- `scripts/state_projection_probe.py` will read the active ticket's events from the bus and materialize the projected state.
- The probe will compare the derived state against `STATE.md` and report drift explicitly.
- The probe will not mutate canonical files; it is a read-only experiment.
- `TURN.md` stays under `agent_controller.py` ownership and is out of scope for this ticket.
- The state machine in `bus/state_machine.py` remains the transition authority; the probe consumes it rather than reimplementing transitions.
- Events that produce invalid transitions are logged as warnings, not exceptions; the probe continues and reports the anomaly.
- This ticket is about validating the feasibility of bus-first state reconstruction, not integrating it into the runtime controller yet.

## Files Likely Touched
- `scripts/state_projection_probe.py`
- `tests/unit/test_state_projection_probe.py`

## Fases
1. Implement a small read-only probe that derives the active ticket state from `events.jsonl`.
2. Add unit tests for matching state, drift detection, and missing/empty bus cases.
3. Validate the probe against the current canonical ticket history.
4. Confirm the probe does not alter `TURN.md`, `STATE.md`, or `execution_log.md`.

## Calidad
- `python scripts/run_pytest_safe.py tests/unit/test_state_projection_probe.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- The probe reconstructs the same state as `STATE.md` for the current active ticket history.
- Drift is reported clearly when the bus-derived state and markdown state differ.
- The probe is read-only and does not mutate canonical collaboration files.
- Canonical validation passes without new warnings or errors.
- The probe emits a structured summary (`matched` / `drifted` / `bus_empty`) suitable for the Manager to decide whether to open a follow-up integration WP.
