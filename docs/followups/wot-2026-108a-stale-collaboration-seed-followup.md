# Follow-up: `.agent/collaboration/work_plan.md` del motor en estado invalido (WOT-2026-108a)

> Draft de seguimiento (no es un ticket activo). Origen: hallazgo del
> `--validate` durante el cierre de sesion 2026-10-20 (`orchestrator_session_close_full_audit.md`,
> VALIDACION FINAL). Preexistente, NO causado por esta sesion.

## Metadata propuesta
- **ID sugerido:** `WOT-2026-108a`.
- **deliverable_type:** code (o documentation, si el remedio es solo resetear el fichero).
- **delivery_authority:** repo_motor
- **Prioridad:** Baja -- WARN no bloqueante hoy (solo 2 `total_errors` en `--validate`,
  sin bus/ticket activo que dependa de este estado), pero contradice la norma propia
  del repo: "Nunca usar `repo_motor/.agent/collaboration/` como operativo" (AGENTS.md,
  seccion "Distincion critica").

## Evidencia (VERIFICADO)
- `python .agent/agent_controller.py --validate --json --project-root <este-checkout>`
  -> `exit_code=1`, `total_errors: 2`:
  - `work_plan.md: "Estado invalido: 'UNKNOWN'"`
  - `work_plan.md: "Falta campo **ID:**"`
- `git log -1 --format="%H %ad %s" -- .agent/collaboration/work_plan.md` ->
  `ea48e827 2026-09-24T20:17:53+02:00 Revert "WIP: stage work_plan for pre-handoff (WOT-2026-025b)"`.
  **Casi un mes antes de esta sesion** -- confirmado NO causado por el trabajo de
  2026-10-20 (WOT-2026-058b/105a/107a y los 2 fixes de test).
- El contenido actual del fichero corresponde al ticket YA CERRADO `WOT-2026-106a`
  (commit `3c8f7cc6`), cerrado por commit directo (modo code-only) sin pasar por
  `agent_controller.py --session-close` -- consistente con que este motor NO tiene
  ningun `AGENT_PROJECT_ROOT`/`z_scripts/` montado en este checkout
  (confirmado: `python .agent/agent_controller.py --session-close --project-root <self>`
  rechaza con `"Motor code-only mode: write operations require an external workspace"`).

## Hipotesis de causa raiz (NO VERIFICADO, requiere mas investigacion)
El flujo `orchestrate-pipeline-codeonly` cierra tickets por commit directo y NUNCA
toca `.agent/collaboration/`, asi que el `work_plan.md` queda congelado en el estado
del ULTIMO ticket que si lo escribio (quiza una sesion anterior que SI tuvo un
workspace externo montado, o una escritura manual). El propio AGENTS.md declara esta
carpeta como "seed neutro... No contienen tickets activos" para `repo_motor` -- este
fichero viola esa invariante desde hace un mes sin que ningun gate lo capturara como
bloqueante (solo como WARN/error no-bloqueante de `--validate`).

## Contrato del fix (si se adopta)
- Investigar como llego `work_plan.md` a reflejar el contenido de WOT-2026-106a sin
  pasar por el bus (¿escritura manual? ¿un `--session-close` contra un workspace que
  ya no existe?).
- Resetear `.agent/collaboration/work_plan.md` (y verificar `execution_log.md`,
  `TURN.md`, `STATE.md`) al seed neutro canonico.
- Considerar una barrera: un check que detecte `work_plan.md` con `Estado: UNKNOWN`
  o sin `**ID:**` en `repo_motor` especificamente (no en un destino, donde eso puede
  ser legitimo transitorio) y lo marque como drift de seed.

## Non-goals
- No decide aqui si el motor DEBERIA tener un `z_scripts/` dogfooding workspace
  montado permanentemente -- esa es una decision de topologia separada.

## Criterio binario de cierre (si se adopta)
- [ ] `python .agent/agent_controller.py --validate --json --project-root <este-checkout>`
  -> `total_errors: 0`.
- [ ] Causa raiz de como llego a este estado, documentada.

## Trazabilidad
- Hallado durante: cierre de sesion 2026-10-20 (WOT-2026-058b + WOT-2026-105a +
  WOT-2026-107a + 2 fixes de test), Bloque "VALIDACION FINAL" de
  `orchestrator_session_close_full_audit.md`.
