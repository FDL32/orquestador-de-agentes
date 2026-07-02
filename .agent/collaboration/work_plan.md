# Work Plan - WOT-2026-018a

## Metadata
- **ID:** WOT-2026-018a
- **Estado:** COMPLETED
- **deliverable_type:** documentation
- **Titulo:** Protocolo canonico de triage de hallazgos (finding_triage_protocol) + integracion en los 4 prompts de autonomia
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Instalar un protocolo canonico y autonomo de triage de hallazgos: cuando durante
un ticket, review, cierre o pipeline aparece un hallazgo nuevo de scope dudoso,
el agente clasifica (mismo ticket / hotfix de desbloqueo / follow-up / ticket
nuevo-Contract Formation / incidente PII-remoto / doc-memoria) ANTES de tocar
codigo, memoria o backlog, y solo pide GO humano cuando el protocolo clasifique
"hotfix urgente", "cambio irreversible/alto blast-radius" o incidente
seguridad/PII/remoto.

Motivacion: hoy existen piezas parciales (regla de no-mezclar-follow-ups en
launch_builder, scope creep en manager_review, materializacion de backlog en
pipeline, pause/resume en el controller) pero NO una matriz de decision explicita
y unica. Este ticket la crea como shared y la referencia desde los 4 prompts que
gobiernan la autonomia del agente, cubriendo las 4 fases: ejecucion (Builder),
review (Manager), cierre de sesion y pipeline.

Criterio verificable de exito: `grep -c finding_triage_protocol` devuelve 1 en cada
uno de los 4 prompts; el shared existe con 0 bytes non-ascii; `check_encoding_guard.py`,
`git diff --check` y `validate --json` cierran verdes (ver Criterios de aceptacion).

## Decision Arquitectonica

- Shared canonico nuevo en `prompts/_shared/finding_triage_protocol.md` con
  `contract_id: cid-finding-triage-v0` (sigue el patron de `loop_hard_stop.md`).
- Es PROTOCOLO DE DECISION, no barrera ejecutable: NO se anade gate automatico ni
  test de `contract_id` en esta pasada (seria scope creep; no hay consumidor que
  lo lea todavia). La matriz guia; no bloquea por si sola.
- Se referencia desde los 4 prompts en el punto donde cada rol decide que hacer
  con un hallazgo, no como bloque nuevo: launch_builder (regla de scope, Fase 0),
  manager_review (Paso 4.bis antes de la Decision), session_close (paso 5.bis del
  Bloque 2, antes del Bloque 3), pipeline (materializacion de follow-ups).

## Fases

### Fase 1 - Shared canonico
- Crear `prompts/_shared/finding_triage_protocol.md`: matriz de 7 casos +
  autonomia permitida + GO humano obligatorio + evidencia minima + nota operativa
  motor-self (`AGENT_PROJECT_ROOT` / guard `is_motor_code_only` para pause/resume).

### Fase 2 - Integracion en los 4 prompts
- `manager_review.md`: Paso 4.bis (triage antes del veredicto CHANGES/hotfix/follow-up).
- `orchestrator_session_close_full_audit.md`: paso 5.bis del Bloque 2 (triage antes
  de convertir hallazgos en memoria/backlog). Numeracion 5.bis para no colisionar
  con el "6." del Bloque 3.
- `orchestrator_launch_builder.md`: referencia en la regla de scope de Fase 0.
- `orchestrator_pipeline.md`: referencia en la materializacion de follow-ups.

### Fase 3 - Verificacion documental
- encoding guard exit 0; `git diff --check` limpio; `validate --json` 0/0;
  los 4 prompts referencian el shared (`grep -c finding_triage_protocol` == 1 cada uno).

## Criterios de aceptacion

Criterios binarios (DoD):

1. `prompts/_shared/finding_triage_protocol.md` EXISTE, ASCII limpio (0 bytes
   non-ascii, sin BOM), con la matriz de 7 casos y `contract_id: cid-finding-triage-v0`.
2. Los 4 prompts (launch_builder, manager_review, session_close, pipeline)
   referencian el shared: `grep -c finding_triage_protocol` == 1 en cada uno.
3. Sin colision de numeracion en session_close (el triage es 5.bis, el Bloque 3
   sigue en 6.).
4. `check_encoding_guard.py` exit 0 sobre los 5 archivos.
5. `git diff --check` limpio.
6. `validate --json --project-root <motor>` = 0 errors / 0 warnings.
7. Sin gate automatico nuevo ni test de contract_id (fuera de scope, evita creep).

## Files Likely Touched

### repo_motor
- `prompts/_shared/finding_triage_protocol.md` (nuevo)
- `prompts/manager_review.md`
- `prompts/orchestrator_session_close_full_audit.md`
- `prompts/orchestrator_launch_builder.md`
- `prompts/orchestrator_pipeline.md`

## Read/inspect only

- `prompts/_shared/loop_hard_stop.md` (patron de `contract_id` para shared).
- `.agent/agent_controller.py` (guard `is_motor_code_only`, flags pause/resume) para
  la nota operativa motor-self.

## Non-goals

- NO anadir gate automatico ni test que valide `contract_id` de `_shared/` (4 de 6
  shared no lo tienen; sin consumidor que lo lea = scope creep).
- NO tocar `agent_controller.py` ni codigo productivo: es solo superficie de prompts.
- NO reescribir la numeracion completa del prompt de cierre (solo 5.bis, cambio minimo).
- NO mezclar con el follow-up del test-isolation (evidence-test-leaks; ese es otro ticket).
