# Work Plan - WP-2026-148

## Metadata
- **ID:** WP-2026-148
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Graph report summary enrichment
- **Asignado a:** Builder

## Objetivo
Build a small follow-up for the graph context adapter that reads the existing `graphify-out/GRAPH_REPORT.md`, extracts only the compact `## Estadísticas` block, and folds that summary into the emitted `## Project Context` block without exceeding 30 lines. The goal is to make the report file useful, remove the current dead-code shape, and keep the adapter lightweight and read-only.

## Decision Arquitectonica
- `scripts/graph_context.py` will parse only the `## Estadísticas` section from `GRAPH_REPORT.md` and surface a brief report-backed summary inside the compact context block.
- The adapter will stay in Python stdlib only and remain read-only.
- The output should focus on the active ticket's files, immediate neighbors, and one concise report summary line.
- Missing or malformed graph reports must degrade gracefully.
- The context budget is declarative: fixed line slots are allocated by section before emitting lines, instead of trimming from the end.
- `TURN.md` stays under controller ownership and is out of scope for this ticket.
- No new graph build pipeline is introduced.
- No controller changes are required for this ticket.
- The change is about better destination understanding, not a broader runtime refactor.

## Files Likely Touched
- `scripts/graph_context.py`
- `tests/unit/test_graph_context.py`

## Fases
1. Parse `GRAPH_REPORT.md` into a compact, deterministic summary from the statistics section only.
2. Include the report summary in the emitted `## Project Context` block while respecting the 30-line cap via pre-allocated section budgets.
3. Keep graceful fallback behavior when the report is absent or malformed.
4. Add focused unit tests for report-present, report-absent, and line-limit cases.

## Calidad
- `python scripts/run_pytest_safe.py tests/unit/test_graph_context.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- The adapter consumes `GRAPH_REPORT.md` when available.
- The adapter only consumes the `## Estadísticas` section and ignores the file inventory.
- The emitted `## Project Context` block does not exceed 30 lines.
- Missing or malformed report data falls back gracefully.
- The adapter remains deterministic and uses Python stdlib only.
- The output stays concise and ticket-scoped.
- Canonical validation passes without new warnings or errors.
