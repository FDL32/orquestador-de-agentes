---
name: dispatch-builder-template
version: 1.0.0
description: Plantilla de despacho del rol Builder para el protocolo trío. Escribe en .agent/planning/vuelo_<id>/<TICKET>/dispatch_builder_r<N>.md.
role: builder
stage: implement
cycle_phase: [F5-implementacion]
author: system
contract_id: cid-kilo-trio-dispatch-builder-v1
---

# Despacho: Builder — {{TICKET}}

## B0 — Cabeza

- **Nombre canónico:** `BUI{{TICKET}}[-r{{R}}]`
- **Rol:** Builder (Persona-3, `builder`)
- **Fecha:** {{FECHA}}
- **Worktree:** {{WORKTREE}}
- **BASE_SHA:** {{BASE_SHA}}
- **Preflight de modelos:** role=`builder` → backend=`{{BACKEND}}` → model_id=`{{MODEL_ID}}` — resuelto y verificado contra `agents.json` viva. (regla 2, regla 31)
- **Requisito de modelo:** si el canal es `api` y el modelo es "mudo", el bundle DEBE incluir el CONTENIDO del repo (no solo rutas). (regla 45)

## B1 — Mandato

Objetivo: {{OBJETIVO_UNA_FRASE}}

Artefacto a emitir: diff/commit productivo + `builder_recibo_r{{R}}.md`

## B2 — Contrato que gobierna

[REF] Prompts y skills citados por REFERENCIA — NUNCA re-declarar criterios (X-09):

- `prompts/builder_invocation_contract.md` (`cid-builder-invocation-v1`) — Contrato de invocación del Builder real. Sección 3: guard bloqueante durante la ejecución => DETENTE, nunca lo parchees ni borres `events.jsonl`; un mandato ACOTADO (B1) no autoriza por iniciativa propia el ciclo de cierre completo.
- `prompts/orchestrator_launch_builder.md` (`cid-bui-implement-v1`) — Arranque del Builder con identidad y paridad.
- `skills/builder-implement-from-plan` (`cid-bui-implement-v1`) — Implementa las tareas del work_plan aprobado.
- `skills/builder-self-audit` — Salida ES el `builder_recibo_rN.md`.
- `skills/builder-run-quality-gates` → `scripts/run_gates_dispatch.py` — Gates focales por `deliverable_type`.
- `scripts/check_builder_prompt_obligations.py` — Verifica que no se omita `--mark-ready`/`BUILDER_EXIT`/`STATE_CHANGED`/`READY_FOR_REVIEW`.

## B3 — Artefacto de salida

Ruta: `.agent/planning/vuelo_{{VUELO_ID}}/{{TICKET}}/dispatch_builder_r{{R}}.md`

Contenido exigido:

- [ ] Nombre canónico en B0 (formato `BUI{{TICKET}}[-r{{R}}]`)
- [ ] Mandato (B1) con diff/commit + recibo
- [ ] Contrato citado por REFERENCIA (B2, sin re-declarar criterios)
- [ ] Micro-pasos detallados en B5 (granularidad de modelo)
- [ ] Herramientas obligatorias en B6 (lista del audit)
- [ ] Commits con `WOT-2026-<TICKET>: <accion>`

## B4 — Gate de entrada

Antes de arrancar, verificar:

- [ ] El predecesor (Manager/PLAN) dejó `work_plan.md` escrito y aprobado en `.agent/collaboration/work_plan.md`
- [ ] El despacho del Manager existe: `.agent/planning/vuelo_{{VUELO_ID}}/{{TICKET}}/dispatch_manager_r{{R}}.md`
- [ ] `AGENT_PROJECT_ROOT` resuelve al `workspace_activo` (no al motor)
- [ ] Si scope está en vuelo por otra sesión → `REQUIERE_HUMANO`

## B5 — Capacidades del modelo (micro-pasos)

El Builder opera con el modo de granularidad del modelo resuelto en B0. Las 3 granularidades posibles:

### Canal: agent + filesystem (default del trío)

El subagente lee el repo directamente y entrega como **fichero** (no por texto: mudez medida, 4/5 respuestas por texto se cortan).

Micro-pasos obligatorios:

1. **Leer work_plan.md completo** (no grep: el Builder NO muestrea el plan — norma "contrato citado => léelo entero").
2. **Dedupe antes de test/lección:** `find_similar_signals.py --text --archive --backlog` — verificar `[DEDUPE: SIN VECINOS]` en la salida.
3. **Implementar tarea por tarea** en orden del DAG. Cada tarea:
   a. Leer/crear el archivo necesario.
   b. Ejecutar `ruff check <file>` y `ruff format <file>`.
   c. Si aplica: correr tests focales (`run_pytest_safe.py -k <test_name>`).
   d. Commitear con `WOT-2026-<TICKET>: <descripcion>`.
4. **Verificar `tested_commit_sha == HEAD`** antes de handoff. El Builder NO corre
   `run_pytest_safe.py --level all` como cierre propio (WOT-2026-104k): esa suite
   completa es responsabilidad EXCLUSIVA del Manager en el gate de cierre del trio
   (ver `dispatch_manager.template.md`), para evitar corridas que el Revisor pueda
   invalidar con un commit posterior.
5. **Escribir `builder_recibo_rN.md`** en `.agent/collaboration/`.
6. **Emitir `BUILDER_EXIT`** + `READY_FOR_REVIEW` en el log.

### Canal: agent sin filesystem-propio (api)

El bundle DEBE llevar el CONTENIDO completo del repo (no solo rutas). Declarar `ROL DE LA LENTE: BUILDER` en el bundle.

Micro-pasos: idénticos arriba, pero:
- Leer archivos: el bundle ya los incluye, no se lee del disco.
- Escribir archivos: devolver el contenido completo en el mensaje (fichero por fichero).
- Tests: no se pueden correr; el Manager re-corrá la suite.

### Modelo razonador / bundle grande

Preflight de mudez (`preflight --content-sample-file`), limite ~15 KB. Micro-pasos idénticos pero acotar el bundle al diff + archivos modificados.

## B6 — Herramientas obligatorias

**BUI — Herramientas de implementación (del audit §1.2):**

```
# Dedupe (ANTES de test/lección)
scripts/find_similar_signals.py --text --archive --backlog
# Mutación segura (probar sin perder fix)
scripts/mutation_cycle.py
# Barreras de guard (si se crean guards)
scripts/check_guard_wiring.py
# Frescura de suite (antes de commitear)
scripts/check_suite_freshness.py
# Encoding guard
scripts/check_encoding_guard.py
# Pre-verify deliverables al cierre
scripts/check_deliverables_exist.py
# Nomenclatura de tickets
scripts/check_ticket_nomenclature.py
# Obligaciones del prompt de Builder
scripts/check_builder_prompt_obligations.py
# DoD no caduco (compartida con MAN)
scripts/check_dod_metric_freshness.py
# Gates canonicos
scripts/run_gates_dispatch.py
scripts/run_pytest_safe.py
ruff check / ruff format
```

## B7 — Puntos de sondeo

[REF] Reglas 47, 50 del protocolo trío.

- **Arranque:** `board_post` a coordinator con `type: INFO`, cuerpo = "Builder arranca {{TICKET}}".
- **Antes de cada fase de implementación:** `board_post` con lista de tareas completadas.
- **Antes del informe:** `board_post` con checklist de cierre (tests verdes, gates OK, recibo escrito).

Mailbox: `mailbox/<session_id>/` en cada punto de sondeo.

## B8 — Identidad de bus + bitácora

[REF] Reglas 49-52, 57, 59 del protocolo trío.

- `register_pending` → `register` al arrancar.
- Heartbeat cada 2 fases de implementación.
- **Línea de bitácora por evento:** `ts | BUI (builder@{{MODEL_ID}}) | evento | detalle`

## B9 — Presupuesto y cierre

[REF] Reglas 1, 10, 16, 53, 54 del protocolo trío; `backlog_triage.md:425-431` (checklist binario); `backlog_triage.md:432-437` (EXTERNAL_WRITE_DETECTED).

- **Presupuesto:** MAX 3 rondas.
- **Escalación:** si se exceden, enviar paquete de resurrección al Manager.
- **Guard bloqueante:** si un guard (`HANDOFF_BLOCKED`, `pre_handoff_guard_failed`, etc.) impide
  avanzar, DETENTE y reporta — ver `builder_invocation_contract.md` Sección 3 (WOT-2026-104n:
  prohibido parchear/monkeypatchear el guard o borrar `.agent/runtime/events/events.jsonl`).
- **Cierre:** `builder_recibo_rN.md` escrito + `BUILDER_EXIT` emitido + `READY_FOR_REVIEW` en log.
- **Snapshot:** inicial y final + `EXTERNAL_WRITE_DETECTED` (si HEAD movido / dirty flip / backlog.md tocado ⇒ declararlo literal y re-analizar).
- **Terminal:** `BUILDER_EXIT` (nunca texto abierto sin cierre).
