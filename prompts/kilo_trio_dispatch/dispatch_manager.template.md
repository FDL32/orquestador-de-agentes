---
name: dispatch-manager-template
version: 1.0.0
description: Plantilla de despacho del rol Manager para el protocolo trío. Escribe en .agent/planning/vuelo_<id>/<TICKET>/dispatch_manager_r<N>.md.
role: manager
stage: plan,closed
cycle_phase: [F1-backlog,F6-revision,F8-cierre]
author: system
contract_id: cid-kilo-trio-dispatch-manager-v1
---

# Despacho: Manager — {{TICKET}}

## B0 — Cabeza

- **Nombre canónico:** `MAN{{TICKET}}[-r{{R}}]`
- **Rol:** Manager (Persona-1, `manager`)
- **Fecha:** {{FECHA}}
- **Worktree:** {{WORKTREE}}
- **BASE_SHA:** {{BASE_SHA}}
- **Preflight de modelos:** role=`manager` → backend=`{{BACKEND}}` → model_id=`{{MODEL_ID}}` — resuelto y verificado contra `agents.json` viva. (regla 2, regla 31)

## B1 — Mandato

Objetivo: {{OBJETIVO_UNA_FRASE}}

Artefacto a emitir: {{ARTEFACTO_EXACTO}}

## B2 — Contrato que gobierna

[REF] Prompts y skills citados por REFERENCIA — NUNCA re-declarar criterios (X-09):

- `skills/manager-create-work-plan` (`manager-create-work-plan/SKILL.md`) — Produce el `work_plan.md`.
- `prompts/contract_formation_pipeline.md` — Contrato de formación de contract para tickets de Contract Formation.
- `prompts/_shared/memory_bootstrap.md` — Paso 0 de la skill manager-create-work-plan: consulta corpus antes de clasificar.
- **Cuando el despacho sea de PLAN/triaje:** `prompts/backlog_triage.md` (`cid-backlog-triage-v1`, Fases 0-3). La plantilla REMITE a las fases del contrato de triaje; no las copia. Regla de gobierno: §2.5 y §2.6 del audit.
- **Cuando el despacho sea de cierre/review (p2):** `prompts/manager_review.md` (`cid-man-review-v2`) + `skills/manager-review-implementation` (`cid-man-review-v2`). Ver regla 62: suite sellada `--level all` como gate de cierre.
- `scripts/run_gates_dispatch.py` — Dispatcher de quality gates focal por `deliverable_type`.

## B3 — Artefacto de salida

Ruta: `.agent/planning/vuelo_{{VUELO_ID}}/{{TICKET}}/dispatch_manager_r{{R}}.md`

Contenido exigido:

- [ ] Nombre canónico en B0 (formato `MAN{{TICKET}}[-r{{R}}]`)
- [ ] Mandato (B1) con artefacto exacto
- [ ] Contrato citado por REFERENCIA (B2, sin re-declarar criterios)
- [ ] Herramientas obligatorias en B6 (lista del audit)
- [ ] Etiquetas de evidencia: `VERIFICADO` / `INFERIDO` / `REQUIERE_HUMANO` (heredado de `backlog_triage.md` §2.6)

## B4 — Gate de entrada

Antes de arrancar, verificar:

- [ ] El predecesor (Orquestador/PLAN) dejó su despacho en `.agent/planning/vuelo_{{VUELO_ID}}/{{TICKET}}/dispatch_orc_r{{R}}.md` (regla 28)
- [ ] `check_backlog_contract.py` devolvió exit 0 sobre el backlog (Fase 0.pre del contrato de triaje)
- [ ] Si scope está en vuelo por otra sesión → `REQUIERE_HUMANO`, NUNCA `APTO_AUTONOMO` (regla PREVIA)
- [ ] `memory_context.py --recall` corrió (Fase 0.ante) y `find_similar_signals.py` dedupéo (3 superficies)

## B5 — Capacidades del modelo

| Cap. | Valor |
|---|---|
| Canal | `{{CANAL}}` (agent = FS propio / api = bundle) |
| ¿Filesystem? | {{SI_NO_FS}} |
| Presupuesto bundle | {{PRESUPUESTO_KB}} KB |
| Mudez conocida | {{MUDEZ}} |
| Entrega | {{ENTREGA}} (fichero vs veredicto corto) |

[REF] `builder_invocation_contract.md:33-78` (mudez por modelo), `ensemble_loop.md:197-208` (mudez por modelo).

## B6 — Herramientas obligatorias

**MAN — Herramientas de triaje y planificación (del audit §1.1 y §1.1bis):**

```
# FASE 0.pre — Contrato del backlog
scripts/check_backlog_contract.py
# FASE 0.ante — Corpus y dedupe
scripts/memory_context.py --recall --query "<termino>"
scripts/find_similar_signals.py --text --archive --backlog
# FASE 0.1 — Reconciliación (recolector obligatorio)
scripts/backlog_reconcile.py
# FASE 1-2 — Clasificación y agrupación (remite a backlog_triage.md Fases 1-2)
# FASE 3 — Síntesis y DAG
scripts/backlog_triage_writer.py      # Escritor único del DAG (Barrera WOT-2026-049c)
scripts/validate_batch_dag.py         # Valida DAG JSON (binding EXCLUSIVO)
scripts/backlog_priority_score.py     # Desempate por TDS (Fase 3, NUNCA en clasificación)
# Herramientas complementarias del Manager
scripts/check_dod_metric_freshness.py   # DoD no caduco (m3)
scripts/validate_ticket_prose.py        # Prosa del ticket (m4)
scripts/check_flight_plan_collision.py  # Colisión inter-plan (m5)
scripts/scope_verification.py           # Scope sin creep (m6)
scripts/work_plan_authority.py          # delivery_authority (m6)
```

## B7 — Puntos de sondeo

[REF] Reglas 47, 50 del protocolo trío.

- **Arranque:** `board_post` a coordinator con `type: INFO`, cuerpo = "Manager arranca {{TICKET}}".
- **Antes de cada fase:** `board_post` con resumen de avance.
- **Antes del informe:** `board_post` con checklist de cierre.

Mailbox: `mailbox/<session_id>/` en cada punto de sondeo.

## B8 — Identidad de bus + bitácora

[REF] Reglas 49-52, 57, 59 del protocolo trío.

- `register_pending` → `register` al arrancar.
- Heartbeat cada 2 fases.
- **Línea de bitácora por evento:** `ts | MAN (manager@{{MODEL_ID}}) | evento | detalle`

## B9 — Presupuesto y cierre

[REF] Reglas 1, 10, 16, 53, 54 del protocolo trío; `backlog_triage.md:425-431` (checklist binario); `backlog_triage.md:432-437` (EXTERNAL_WRITE_DETECTED).

- **Presupuesto:** MAX 3 rondas.
- **Escalación:** si se exceden, enviar paquete de resurrección al Orquestador.
- **Cierre:** `agent_controller.py --validate --json` en el cierre.
- **Snapshot:** inicial y final + `EXTERNAL_WRITE_DETECTED` (si HEAD movido / dirty flip / backlog.md tocado ⇒ declararlo literal y re-analizar sobre snapshot fresco).
- **Terminal:** `exit` o `escalated` (nunca texto abierto sin cierre).
