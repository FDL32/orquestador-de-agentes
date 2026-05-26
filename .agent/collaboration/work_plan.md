# Work Plan - WP-2026-147

## Metadata
- **ID:** WP-2026-147
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Graph context adapter
- **Asignado a:** Builder

## Objetivo
Build a lightweight graph-context adapter that reads the already-generated `graphify-out/graph.json` and `GRAPH_REPORT.md` for a destination repository, then emits a short `## Project Context` block for the active ticket. The adapter should stay in Python stdlib, avoid any new graph build pipeline, and extract only the minimum context needed to cut token usage.

## Decision Arquitectonica
- `scripts/graph_context.py` will read `graphify-out/graph.json` plus `GRAPH_REPORT.md` and turn them into a compact ticket-scoped context block.
- The adapter will stay in Python stdlib only and reuse the existing graphify output instead of creating a new graph pipeline.
- The output should focus on the active ticket's files, immediate neighbors, and a short summary of the relevant corpus.
- `agent_controller.py` will optionally surface a compact `## Project Context` summary from the graph context adapter when generating work plans for destination projects.
- The design is inspired by graph-based project understanding tools, but intentionally keeps the implementation lightweight and read-only.
- `TURN.md` stays under controller ownership and is out of scope for this ticket.
- No LLM-per-file analysis is introduced in this ticket.
- The change is about better destination understanding, not a broader runtime refactor.

## Files Likely Touched
- `scripts/graph_context.py`
- `.agent/agent_controller.py`
- `tests/unit/test_graph_context.py`

## Fases
1. Build a lightweight adapter that reads `graphify-out/graph.json` and `GRAPH_REPORT.md`.
2. Extract a ticket-scoped `## Project Context` block with the relevant files and immediate graph neighbors.
3. Add a minimal `agent_controller.py` hook to inject the context block when the graph output exists.
4. Add focused unit tests for parsing, filtering, and compact output generation.
5. Confirm the hook is optional and the ticket flow still works if no graph output exists yet.

## Calidad
- `python scripts/run_pytest_safe.py tests/unit/test_graph_context.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- The adapter produces a compact `## Project Context` summary for the destination project.
- The summary is derived from existing `graphify-out` artifacts, not a new graph build.
- The adapter is deterministic and uses Python stdlib only.
- The emitted `## Project Context` block does not exceed 30 lines.
- The optional `## Project Context` injection keeps the ticket context concise.
- The existing ticket flow still works when no project map is available.
- Canonical validation passes without new warnings or errors.
