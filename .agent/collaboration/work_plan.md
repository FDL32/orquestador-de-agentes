# Work Plan - WP-2026-150

## Metadata
- **ID:** WP-2026-150
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Project scanner with import map
- **Asignado a:** Builder

## Objetivo
Build a deterministic project scanner that turns a destination repository into a compact, token-efficient `project-map.json` with a real Python `importMap`, file inventory, fingerprinting, and framework hints so the Builder can consume destination context without reading the whole tree.

## Decision Arquitectonica
- The scanner must be stdlib-only and deterministic.
- Python import relationships must come from `ast.parse()` rather than heuristics or LLM output.
- The scanner should bucket files into useful categories, not dump the whole repository.
- The output should be compact enough to seed `## Project Context` in the ticket flow.
- The scanner writes a structured artifact at `.agent/context/project-map.json`; the controller reads that artifact and does not re-scan inline in the hot path.
- The controller hook may consume the scanner output to enrich work-plan context, but the scanner remains the source of truth.
- For local imports that resolve to files inside the repository, preserve the full module path in `importMap`; for stdlib and external imports, collapse to the top-level package name.
- Record `SyntaxError` parse failures explicitly in the output instead of swallowing them silently.
- No new dependencies are allowed.
- Noise-heavy directories must be excluded so the output stays portable and relevant.

## Files Likely Touched
- `scripts/project_scanner.py`
- `.agent/agent_controller.py`
- `tests/unit/test_project_scanner.py`
- `.agent/context/project-map.json` (generated artifact)

## Fases
1. Implement a deterministic scanner over the destination repository that collects the file inventory, fingerprints, and category buckets with exclusion filters for non-product noise.
2. Add Python AST import extraction so the scanner emits a real `importMap` for source files, preserving local module depth and collapsing only stdlib/external imports.
3. Detect framework hints from common manifests such as `pyproject.toml`, `requirements.txt`, and `package.json`.
4. Emit a compact `project-map.json` under `.agent/context/` that can be reused by the controller to populate `## Project Context` for work plans.
5. Wire the controller to consume the scanner artifact when preparing destination context, complementing the existing project-map flow instead of re-scanning inline.
6. Cover the scanner with focused tests for exclusions, fingerprints, import discovery, framework hints, parse failures, and deterministic output.

## Calidad
- `python scripts/run_pytest_safe.py tests/unit/test_project_scanner.py -q`
- `ruff check scripts tests`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- The scanner emits a compact `project-map.json` for the destination repository.
- Python imports are captured via AST, not by string search.
- Noise directories are excluded so the resulting map stays token-efficient.
- The controller can use the scanner summary to enrich `## Project Context` without duplicating logic.
- The scanner is deterministic and stdlib-only.
- The tests cover the main scan paths and the exclusion behavior.
- Canonical validation passes without new warnings or errors.
