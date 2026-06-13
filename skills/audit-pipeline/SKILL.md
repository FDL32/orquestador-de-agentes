---
name: audit-pipeline
version: 1.0.0
description: Meta-auditoria post-pipeline read-only sobre el sistema auditado en un repo_destino, con doble pasada adversarial e informe consolidado
triggers: [/audit-pipeline, audit-pipeline, auditar-pipeline]
author: agent
role: manager
stage: review
writes_memory: false
quality_gate: false
tags: [core, system, audit]
source_prompt: prompts/audit_pipeline.md
contract_id: cid-audit-pipeline-v1
---

# audit-pipeline

Skill para conducir la meta-auditoria final de un pipeline ya ejecutado por
`orchestrate-pipeline` sobre un `repo_destino`.

No es un tercer Review por ticket. Review 1 y Review 2 son intra-ticket y
sincronicos. Esta skill es post-pipeline, retrospectiva y transversal: audita el
cuerpo completo de trabajo cerrado y produce un informe consolidado.

Es **read-only sobre el sistema auditado**: no reabre tickets, no toca backlog,
codigo ni estado operativo. Solo escribe sus propios artefactos de auditoria y
propone follow-ups.

## Cuando usarla

Usar cuando el usuario pida:

- auditar un pipeline ya cerrado de tickets en `repo_destino`;
- una revision final transversal de implementacion, codigo, docs y alineacion
  con objetivos del backlog;
- detectar objetivos huerfanos, deuda no retomada o contradicciones entre
  tickets cerrados.

No usar para:

- revisar un unico ticket en curso (usar `man-review-implementation`);
- conducir el bucle de implantacion (usar `orchestrate-pipeline`);
- corregir o reabrir trabajo (esta skill no escribe estado operativo).

## Prompt canonico

Leer y aplicar:

- `prompts/audit_pipeline.md`

Ese prompt es la fuente de verdad. Hereda filosofia de
`prompts/audit_agent_output.md` y mecanica de `prompts/review_manager.md`. Si
algo diverge, prevalece `prompts/audit_pipeline.md`.

## Topologia obligatoria

Igual que `orchestrate-pipeline`:

- `repo_destino`: cwd del proyecto auditado.
- `MOTOR_ROOT`: desde `.agent/config/motor_destination_link.json`.
- `AGENT_PROJECT_ROOT`: apunta al `repo_destino`.
- El motor es read-only; `scripts/check_motor_pristine.py` es evidencia de
  integridad, nunca restauracion.

## Flujo

1. **Fase 0 - Vision global:** leer `backlog.md` completo, seleccionar el
   `pipeline_closeout_*.md` mas reciente de forma deterministica y leer todos
   los `closeout_*.md`. Construir la matriz objetivo -> ticket -> evidencia ->
   estado. Si falta un closeout, marcar `NO_VERIFICABLE` salvo evidencia de
   fallo. Si no hay cierre global, no emitir `APROBADO`.
2. **Fase 1 - Doble pasada por ticket:**
   - Pasada A (verificacion): plan, implementacion, logs, tests, docs, closeout
     en cuatro ejes (implementacion, calidad codigo, calidad docs, alineacion).
   - Pasada B (refutacion): falso verde, scope creep, claims sin evidencia,
     fixtures irreales, estado canonico incoherente.
3. **Fase 2 - Transversal:** dependencias, objetivos huerfanos, deuda no
   retomada, contradicciones, drift de motor acumulado.
4. **Veredicto global:** `APROBADO` / `APROBADO CON NITS` /
   `CAMBIOS NECESARIOS` / `NO ACEPTAR TODAVIA`.
5. **Emitir informe + JSON** en el mismo turno.

## Herramientas por fase

| Fase | Rol | Prompts | Scripts / comandos |
|---|---|---|---|
| Vision global | Auditor | `<MOTOR_ROOT>/prompts/audit_pipeline.md` | leer `backlog.md`, `orchestrator_pipeline/reports/*.md` |
| Por ticket A/B | Auditor | `<MOTOR_ROOT>/prompts/audit_agent_output.md`, `<MOTOR_ROOT>/prompts/review_manager.md` | `git show --stat`, `git log --oneline`, `ruff check`, tests focales, `<MOTOR_ROOT>/scripts/check_encoding_guard.py` |
| Transversal | Auditor | `<MOTOR_ROOT>/prompts/audit_pipeline.md` | `<MOTOR_ROOT>/scripts/check_motor_pristine.py --check`, leer `motor_after_*.json` |
| Informe | Auditor | `<MOTOR_ROOT>/prompts/audit_pipeline.md` | `<MOTOR_ROOT>/scripts/check_encoding_guard.py` sobre el informe |

## Contrato de evidencia

- Cada claim relevante lleva etiqueta de evidencia con artefacto concreto
  (`path:`, `commit:`, `command:`+`exit_code:`, `event_seq:` o `bytes:`).
- Separar siempre `[EVIDENCIA: <fuente>]` de `[RELATO: agente_explicacion]`.
- Etiqueta sin artefacto = relato, no permite afirmar cumplimiento.
- Los closeouts son relato del pipeline: re-derivar desde git, plan y logs.

## Salidas

- `repo_destino/orchestrator_pipeline/reports/pipeline_audit_<timestamp>.md`
- `repo_destino/orchestrator_pipeline/reports/pipeline_audit_<timestamp>.json`

Estructura detallada de ambos en `prompts/audit_pipeline.md`. El Markdown debe
incluir el alcance auditado y el JSON debe incluir `audit_scope` y
`source_reports` con `path`, `exists` y `role`.

## Restriccion dura

- No reabre tickets ni modifica `backlog.md`.
- No escribe codigo ni estado operativo.
- No restaura motor ni destino.
- Mejoras del motor van como follow-up, nunca como edicion del motor.

La reapertura de tickets o adopcion de mejoras la decide el humano leyendo el
informe.
