---
name: run-quality-gates
version: 2.0.0
description: Ejecutar gates apropiados según deliverable_type del WP activo
triggers: [/gates, quality-gates, /check]
author: agent
role: builder
stage: quality
writes_memory: false
quality_gate: true
tags: [core, system]
---

# bui-run-quality-gates

Skill para ejecutar la batería de gates correspondiente al tipo de deliverable del WP activo. Dispatchea automáticamente — el agente solo invoca el wrapper.

## Cuándo usar
- Antes de declarar READY_FOR_REVIEW.
- Tras cada cambio sustancial durante implementación.

## Workflow

1. Ejecuta `python scripts/run_gates_dispatch.py`.
2. Si exit code != 0: lee el output, corrige, vuelve a ejecutar.
3. Si exit code == 0: prosigue con BUILDER_EXIT.

## Dispatch table (informativo)

| deliverable_type | Gates ejecutados |
|---|---|
| code | ruff + pytest-safe + pip-audit wrapper (condicional, invocado directo por el dispatcher) |
| mixed | code gates + deliverable existence check |
| documentation | deliverable existence check |
| research | deliverable existence check |
| analysis | deliverable existence check |
| (missing) | fallback a code + warning |

## Constraints

- NO saltar el dispatcher invocando ruff/pytest manualmente.
- NO modificar el dispatcher por WP — usa el wrapper.
