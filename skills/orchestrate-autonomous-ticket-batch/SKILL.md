---
name: orchestrate-autonomous-ticket-batch
version: 1.0.0
description: Ejecuta un batch autonomo de tickets consumiendo el DAG de grupos que produce backlog-triage; cierra el maximo de tickets CON GARANTIAS (Tier 0-1) con hard-stop y GROUP_STOP_REPORT, congela solo el subgrafo del grupo caido y sigue con los independientes; detecta el modo (destino con bus vivo / motor code-only) y DELEGA en el pipeline por ticket que corresponda, sin duplicar la logica de cierre de ninguno
triggers: [/orchestrate-autonomous-ticket-batch, orchestrate-autonomous-ticket-batch, batch-autonomo-de-tickets]
author: agent
role: orchestrator
stage: execute
writes_memory: false
quality_gate: false
tags: [core, system, orchestration, autonomy, batch]
source_prompt: prompts/orchestrator_autonomous_ticket_batch.md
contract_id: cid-orchestrator-autonomous-ticket-batch-v1
---

# orchestrate-autonomous-ticket-batch

Skill para ejecutar el BATCH AUTONOMO de tickets: consume el DAG de grupos
emitido por `/backlog-triage` (schema `autonomous-batch-dag/v1`) y cierra el
mayor numero de tickets posible **con garantias**.

NO reimplementa el metodo. El flujo completo (deteccion de modo y delegacion,
maquina de estados con ruteo al owner-stage, causas de parada dura,
`GROUP_STOP_REPORT`, regla de contencion, las 7 barreras no negociables por
ticket y las salidas de la corrida) vive en
`prompts/orchestrator_autonomous_ticket_batch.md`. **El prompt es la fuente de
verdad; si algo diverge, prevalece el prompt.**

## La garantia no es opcional: el auditor es la pieza hermana

Un ejecutor sin su auditoria es autonomia sin garantia, es decir auto-reporte,
y `prompts/audit_agent_output.md` (CEM v0) lo prohibe. Toda corrida de esta
skill se audita despues con `/audit-autonomous-ticket-batch`
(`prompts/audit_autonomous_ticket_batch.md`), **en fresh-context y por un
agente que NO sea el que ejecuto el batch**. El ejecutor no puede auditarse a
si mismo.

## Cuando usarla

- Hay varios tickets `APTO_AUTONOMO` ya clasificados por `/backlog-triage`, y
  ese triage emitio el DAG de grupos (`autonomous-batch-dag/v1`), validado con
  `scripts/validate_batch_dag.py`.
- Se quiere cerrar una tanda sin intervencion humana por ticket, aceptando que
  las barreras PARAN la corrida cuando no dan verde (parar limpio es su
  funcion, no su fallo).

## Cuando NO usarla

- Tickets `REQUIERE_HUMANO` o `DISENO_PRIMERO`: **jamas** entran en el batch.
- Sin DAG validado: sin schema congelado, el ejecutor no tiene contrato de
  datos. Corre `/backlog-triage` primero.
- Un solo ticket: usa el pipeline por ticket directamente
  (`/orchestrate-pipeline` o `/orchestrate-pipeline-codeonly` segun el modo).

## Restriccion dura

- El ejecutor **NUNCA reclasifica** un ticket (`class` / `autonomy_mode` los
  asigna el TRIAGE). Reclasificar para esquivar un gate es `falso_verde`.
- El ejecutor **jamas escribe** backlog, informes, follow-ups ni ledger en
  `repo_motor`: van al destino-rol.
- Tier 2 y Tier 3 **no estan implementados**. No los improvises.
