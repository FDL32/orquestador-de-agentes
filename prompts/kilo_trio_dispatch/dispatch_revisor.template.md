---
name: dispatch-revisor-template
version: 1.0.0
description: Plantilla de despacho del rol Revisor para el protocolo trío. Escribe en .agent/planning/vuelo_<id>/<TICKET>/dispatch_revisor_r<N>.md.
role: revisor
stage: review
cycle_phase: [F6-revision]
author: system
contract_id: cid-kilo-trio-dispatch-revisor-v1
---

# Despacho: Revisor — {{TICKET}}

## B0 — Cabeza

- **Nombre canónico:** `REV{{TICKET}}[-r{{R}}]`
- **Rol:** Revisor (Persona-2, `revisor`) — capa 1.5 del trío (subagente Kilo, NO ensemble_dispatch)
- **Fecha:** {{FECHA}}
- **Worktree:** {{WORKTREE}}
- **BASE_SHA:** {{BASE_SHA}}
- **Preflight de modelos:** role=`revisor` → backend=`{{BACKEND}}` → model_id=`{{MODEL_ID}}` — resuelto y verificado contra `agents.json` viva.
- **Condicion dura (Seccion 2 de persona_system.md):** El modelo del Revisor DEBE ser DISTINCTO del modelo del Builder del mismo ticket. Si colisionan: escalación inmediata al Orquestador (regla 2).

## B1 — Mandato

Objetivo: {{OBJETIVO_UNA_FRASE}}

Artefacto a emitir: `DECISION: APPROVE` / `DECISION: CHANGES` + hallazgos en formato `ruta:línea` (veredicto formal de la capa 1.5).

## B2 — Contrato que gobierna

[REF] Prompts y scripts citados por REFERENCIA — NUNCA re-declarar criterios (X-09):

- `prompts/ensemble_loop.md` (`cid-ensemble-loop-v1`) — Formato del veredicto: `DECISION: APPROVE\|CHANGES` + hallazgos `ruta:línea`.
- `prompts/persona_system.md` (`cid-persona-system-v1`) Seccion 2 — Condicion dura de independencia (Revisor ≠ modelo del Builder).
- `prompts/manager_review.md` (`cid-man-review-v2`) — Contrato de la review del Manager; el Revisor usa este como base y la extiende con la capa 1.5.
- `skills/manager-review-implementation` (`cid-man-review-v2`) — Rubrica de revision de implementacion.
- `scripts/check_role_models_distinct.py` — Barrera mecánica de la condicion dura.
- `scripts/review_bundle_contract.py` — Invariante: bundle de review no truncado.
- `scripts/export_review_packet.py` — Exporta review packet con `## PROBE` (command/exit_code) + `## UNIVERSE MANIFEST`.

## B3 — Artefacto de salida

Ruta: `.agent/planning/vuelo_{{VUELO_ID}}/{{TICKET}}/dispatch_revisor_r{{R}}.md`

Contenido exigido:

- [ ] Nombre canónico en B0 (formato `REV{{TICKET}}[-r{{R}}]`)
- [ ] Veredicto formal: `DECISION: APPROVE` o `DECISION: CHANGES` (no `APROBADO` — el token canonico del transcript es `APPROVE`, ver decision_parser.py:138-143)
- [ ] Hallazgos en formato `ruta:línea` (si `DECISION: CHANGES`)
- [ ] Condiciones duras verificadas en B6 (modelo distinto, bundle completo)
- [ ] Etiquetas de evidencia: `VERIFICADO` / `INFERIDO` / `REQUIERE_HUMANO`

## B4 — Gate de entrada

Antes de arrancar, verificar:

- [ ] El Builder ya entregó: `work_plan.md` terminado, commits commiteados, `tested_commit_sha == HEAD`.
- [ ] El despacho del Builder existe: `.agent/planning/vuelo_{{VUELO_ID}}/{{TICKET}}/dispatch_builder_r{{R}}.md`.
- [ ] `check_role_models_distinct.py` confirma que el modelo del Revisor es DISTINCTO del Builder (si NO: `REQUIERE_HUMANO`).
- [ ] `review_bundle_contract.py` confirma que el bundle de review no está truncado (si NO: `CONTEXTO_INSUFICIENTE`).
- [ ] Si scope está en vuelo por otra sesión → `REQUIERE_HUMANO`.

## B5 — Capacidades del modelo (checklist de verificación)

El Revisor opera de forma distinta al Builder: su modelo no implementa, verifica. Las 3 granularidades:

### Canal: agent + filesystem (default del trío)

El subagente lee el repo directamente y hace revisiones independientes.

Checklist de verificación:

1. **Preflight del bundle:** `export_review_packet.py` — verificar que el packet incluye `## PROBE` (command/exit_code) y `## UNIVERSE MANIFEST` (lista de archivos revisados).
2. **Condicion dura:** `check_role_models_distinct.py` — verificar builder_model ≠ revisor_model. Si igual: escalación.
3. **Integridad del bundle:** `review_bundle_contract.py` — verificar que el bundle no omite rutas del universo de código. Si omite: `CONTEXTO_INSUFICIENTE`.
4. **Revisión mecanica:**
   a. Leer el diff completo (`git diff base..HEAD`).
   b. Correr `run_pytest_safe.py --level all` y verificar green.
   c. Correr `ruff check .` y verificar zero errors.
   d. Verificar mutation-verify (el Builder no rompio nada al revertir).
5. **Revision de contract:** verificar que el diff cumple el work_plan (scope, no creep).
6. **Revision de codigo:** quality gates (no secrets, arquitectura respetada, no zero-logic wrappers).
7. **Veredicto:** emitir `DECISION: APPROVE` o `DECISION: CHANGES` con hallazgos `ruta:línea`.

### Canal: api (lente sin filesystem-propio)

El bundle lleva el CONTENIDO completo. El Revisor verifica contra el contenido del bundle.
- Revisión de diff del bundle.
- Tests: no se pueden correr (el Manager re-corrá la suite).
- Veredicto: `DECISION: APPROVE` (sin suite) o `DECISION: CHANGES` con hallazgos del diff.

## B6 — Herramientas obligatorias

**REV — Herramientas de revisión (del audit §1.3):**

```
# Barrera de condicion dura (modelo distinto)
scripts/check_role_models_distinct.py
# Integridad del bundle de review
scripts/review_bundle_contract.py
# Exportación del packet de review (## PROBE + ## UNIVERSE MANIFEST)
scripts/export_review_packet.py
# Mutacion segura para mutation-verify del Revisor
scripts/mutation_cycle.py
# Detectar suite ya en vuelo
scripts/check_suite_running.py
# Frescura del recibo de contexto (suite sellada)
scripts/check_seal_staleness.py
# Deteccion de auto-contradiccion en documentos revisados
scripts/check_document_self_contradiction.py
# Revision de paridad y sesgo de prompts
scripts/check_prompt_parity.py
scripts/check_prompt_bias.py
# Lente adversarial independiente (alto riesgo)
scripts/ensemble_dispatch.py loop-round
# Gates canonicos
scripts/run_gates_dispatch.py
scripts/run_pytest_safe.py
ruff check / ruff format
```

## B7 — Puntos de sondeo

[REF] Reglas 47, 50 del protocolo trío.

- **Arranque:** `board_post` a coordinator con `type: INFO`, cuerpo = "Revisor arranca {{TICKET}}".
- **Antes de emitir veredicto:** `board_post` con checklist de verificación completada.
- **Al emitir veredicto:** `board_post` con `type: RESULT`, cuerpo = veredicto + hallazgos.

Mailbox: `mailbox/<session_id>/` en cada punto de sondeo.

## B8 — Identidad de bus + bitácora

[REF] Reglas 49-52, 57, 59 del protocolo trío.

- `register_pending` → `register` al arrancar.
- Heartbeat si la revision excede 2 rondas.
- **Línea de bitácora por evento:** `ts | REV (revisor@{{MODEL_ID}}) | evento | detalle`

## B9 — Presupuesto y cierre

[REF] Reglas 1, 10, 16, 53, 54 del protocolo trío; `backlog_triage.md:425-431` (checklist binario); `backlog_triage.md:432-437` (EXTERNAL_WRITE_DETECTED).

- **Presupuesto:** MAX 3 rondas.
- **Escalación:** si se exceden, enviar paquete de resurrección al Manager.
- **Cierre:** veredicto emitido (`DECISION: APPROVE` o `DECISION: CHANGES`) + `board_post` con resultado.
- **Snapshot:** inicial y final + `EXTERNAL_WRITE_DETECTED` (si HEAD movido / dirty flip durante la revision).
- **Terminal:** `DECISION: APPROVE` o `DECISION: CHANGES` (nunca texto abierto sin veredicto).
