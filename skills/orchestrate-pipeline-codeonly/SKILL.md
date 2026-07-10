---
name: orchestrate-pipeline-codeonly
version: 1.0.0
description: Ejecuta un pipeline de tickets del motor en CODE-ONLY MODE (worktree _dev, cierre commit-directo sin bus) con premisa-en-vivo, plan-audit adversarial, Review 2 fresh-context y las barreras de verificacion aprendidas
triggers: [/orchestrate-pipeline-codeonly, orchestrate-pipeline-codeonly, pipeline-codeonly]
author: agent
role: manager
stage: implement
writes_memory: false
quality_gate: true
tags: [core, system, pipeline, codeonly, dogfooding]
source_prompt: prompts/orchestrator_pipeline_codeonly.md
contract_id: cid-orchestrator-pipeline-codeonly-v1
---

# orchestrate-pipeline-codeonly

Skill para conducir un pipeline de tickets del MOTOR cuando este esta en
**CODE-ONLY MODE**: se trabaja en la worktree `_dev`, no hay destino externo
montado, el bus esta bloqueado y el cierre de cada ticket es **commit-directo**
(git es el registro; el ID va en el mensaje del commit).

Es la variante especializada de `orchestrate-pipeline` para el dogfooding del
propio motor. NO reimplementa el metodo: el flujo completo (preflight, flujo por
ticket, cierre de cadena, riesgos codificados) vive en
`prompts/orchestrator_pipeline_codeonly.md`. **El prompt es la fuente de verdad;
si algo diverge, prevalece el prompt.**

## Cuando usarla

Las TRES condiciones a la vez (si falta una, NO es este pipeline):

- `delivery_authority: repo_motor` (el ticket entrega codigo del motor);
- se trabaja en la worktree **`_dev`** (rama `main`), no en el principal (detached)
  ni en el workspace (backlog);
- **CODE-ONLY MODE**: sin destino externo -> el bus esta bloqueado
  (`--session-close`/`--bootstrap-ticket`/`--mark-ready` dan
  `[ERROR] Motor code-only mode`).

## Cuando NO usarla

- Si el motor SI tiene destino externo montado (bus vivo): usar
  `orchestrate-pipeline` canonico (`prompts/orchestrator_pipeline.md`).
- Para decidir QUE pipeline lanzar (usar `backlog-triage`, read-only).
- Para auditar un pipeline ya cerrado (usar `audit-pipeline`, read-only).
- Para un `repo_destino` generico (ese es el flujo canonico con bus).

## Preflight (recolector, obligatorio)

Antes de tocar nada, correr el recolector determinista
`scripts/preflight_codeonly_pipeline.py` (SHAs de los 3 repos + validate + guard de
topologia + barrera "0 consumidores runtime" del token a retirar). Es un TESTIGO
read-only: reporta senales, el agente juzga. Detalle en el prompt (Paso 0).

## Workflow

El metodo completo esta en `prompts/orchestrator_pipeline_codeonly.md`. En resumen,
por ticket: (1) verificar premisa EN VIVO; (2) Manager plan + auditar el PLAN
adversarialmente; (3) Builder persistiendo a disco; (4) correr los gates YO MISMO
(grep `-i`, ruff, py_compile, encoding, suite leyendo "N passed/failed" NO el exit
code); (5) Review 2 fresh-context que MUTA para probar barreras; (6) cierre
commit-directo (PATH del venv para hooks, Co-Authored-By dinamico, push); (7)
verificar cada claim con evidencia. Al final: auditoria adversarial de la CADENA +
cierre canonico adaptado (Bloque 3 N/A) + archivar backlog + memoria.

## Restriccion dura

- SOLO `repo_motor` + `_dev` + code-only. Cierre commit-directo, sin bus.
- La skill es puntero: no redeclara el metodo. Remite al prompt.
