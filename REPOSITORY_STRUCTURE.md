# Repository Structure

This document describes the public, standalone layout of `orquestador_de_agentes`.
It is written so the repository can be cloned or published without any knowledge of a parent workspace.

## Canonical layout

```text
orquestador_de_agentes/
|-- .agent/
|   |-- collaboration/
|   |-- config/
|   |-- context/
|   |-- hooks/
|   |-- planning/
|   |-- rules/
|   |-- runtime/
|   |-- templates/
|   |-- agent_controller.py
|   |-- agents_config.py
|   |-- project_manifest.toml
|   `-- .version_manifest.json
|-- agent_system/
|-- bus/
|-- docs/
|-- prompts/
|-- scripts/
|-- skills/
|-- templates/
|-- tests/
|-- AGENTS.md
|-- CHANGELOG.md
|-- CLAUDE.md
|-- CREDITS.md
|-- CLOSURE_MODEL.md
|-- CONSTITUTION.md
|-- DISTRIBUTION_GUIDE.md
|-- INTERACTION_MODES.md
|-- MANUAL_PUBLICATION_CHECKLIST.md
|-- PROJECT.md
|-- QUICKSTART.md
|-- README.md
|-- REPOSITORY_STRUCTURE.md
|-- RELEASE_CHECKLIST.md
|-- UPGRADE_CLEANUP_GUIDE.md
|-- UPGRADE_GUIDE.md
|-- plan_graph.md
|-- repo_charter.md
`-- pyproject.toml
```

## What is public

- `.agent/` holds the canonical runtime state and manifests.
- `scripts/` contains reproducible utilities and launcher commands.
- `skills/` contains reusable skill instructions.
- `docs/` contains durable architectural reference documents (known failure patterns, bus audit reports). Read on demand when a ticket touches bus, state projections, or topology-aware code.
- `prompts/` contains operator-facing prompts used during planning, launch, review and audits; not part of the default runtime context unless explicitly referenced.
- `templates/` contains reusable startup templates.
- `tests/` contains the validation suite for the repo.
- The top-level Markdown files document how the repo works as a standalone project.

## What is internal

- `tests/sandbox/` is disposable test runtime and fixture space.
- `tests/.../.agent.__pytest_hidden__/` is a testing mirror used by specific test scenarios.
- Local editor settings, caches and runtime artifacts are intentionally excluded from the public contract.

## Design vs. development sessions (destination projects)

The motor ships `.agent/collaboration/` as a neutral seed. A destination project populates it at
runtime with two parallel, non-colliding session types: a read-only `sesion_diseno` (triages the
backlog, drafts flight plans into a queue, never touches code or `backlog.md`) and a
`sesion_desarrollo` (implements, commits, and advances queued flight plans through execution).
Neither this document nor the motor hardcodes the destination's queue paths, since the motor must
remain publishable without any knowledge of a parent workspace (see "Public boundary" below). The
full contract -- who writes which surface, and the no-collision guarantee between the two session
types -- is canonical in `.agent/rules/common/vocabulario_canonico.md`; this section only points to
it (no redeclaration, per the skill/prompt governance convention).

## Public boundary

When this repository is published:

- All commands in the docs should work from the repository root.
- No documentation should require a parent workspace path.
- Any local-only metadata belongs outside the public contract.
