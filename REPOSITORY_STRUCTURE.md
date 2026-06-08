# Repository Structure

This document describes the public, standalone layout of `orquestador_de_agentes`.
It is written so the repository can be cloned or published without any knowledge of a parent workspace.

## Canonical layout

```text
orquestador_de_agentes/
|-- .agent/
|   |-- collaboration/
|   |-- runtime/
|   |-- project_manifest.toml
|   `-- .version_manifest.json
|-- agent_system/
|-- docs/
|-- prompts/
|-- scripts/
|-- skills/
|-- templates/
|-- tests/
|-- AGENTS.md
|-- CHANGELOG.md
|-- CLAUDE.md
|-- INTERACTION_MODES.md
|-- PROJECT.md
|-- QUICKSTART.md
|-- README.md
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

## Public boundary

When this repository is published:

- All commands in the docs should work from the repository root.
- No documentation should require a parent workspace path.
- Any local-only metadata belongs outside the public contract.
