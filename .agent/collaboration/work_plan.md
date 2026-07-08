# Plan de Trabajo: --manager-approve --dry-run respeta semantica preview

## Metadata
- **ID:** WOT-2026-020h
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-08
- **delivery_authority:** repo_motor
- **Prioridad:** MEDIA
- **Asignado a:** Builder

## Objetivo
`--manager-approve --dry-run` aplicaba la transicion canonica completa (STATE/TURN/
work_plan/execution_log -> COMPLETED) en lugar de solo previsualizar. El flag `--dry-run`
se parseaba global (l.6467) pero el dispatch (l.6485) no lo pasaba al handler
`_handle_manager_approve(ticket_id, json_output, force_mode)` — sin param `dry_run`.

## Premisa (verificada read-only)
- VERIFICADO EN CODIGO (`agent_controller.py:6485-6486`): dispatch llama
  `handler(ticket_id, json_output, force_mode)` sin dry_run.
- VERIFICADO EN CODIGO (`agent_controller.py:4624-4625`): handler signature
  `(ticket_id, json_output, force_mode)` — no recibe dry_run.
- VERIFICADO EN CODIGO (`agent_controller.py:6467`): `--dry-run` solo se parsea para
  `--session-close`, no para `--manager-approve`.
- CONFIRMADA: bug real, 3 puntos de mutacion (already-completed bus l.4700,
  already-completed markdown l.4721, main READY_FOR_REVIEW->COMPLETED l.4813).

## Files Likely Touched
- `.agent/agent_controller.py` (handler + dispatch)
- `tests/test_agent_controller.py` (regression test)

## Forbidden Surfaces
- NO cambiar la logica de --manager-approve sin --dry-run (real-run debe seguir aplicando)
- NO tocar --session-close --dry-run (comportamiento separado)

## Non-goals
- No cambiar la logica de --manager-approve sin --dry-run
- No tocar --session-close --dry-run (verificar por separado)
- No tocar --request-changes (sin dry_run en su contrato)

## Decision Arquitectonica
Anadir `dry_run: bool = False` al handler en lugar de leer `sys.argv` dentro del handler.
Motivo: el handler ya recibe todos sus parametros del dispatch (ticket_id, json_output,
force_mode); leer sys.argv dentro romperia el aislamiento y dificultaria el testeo
(los tests llaman `_handle_manager_approve` directamente, sin pasar por main/argv).
El dispatch (l.6485) es el unico punto que ve `sys.argv` y puede pasar `dry_run`
explicitamente. Los 3 guards cubren los 3 caminos de mutacion: (1) already-completed
en bus (backfill idempotente), (2) already-completed en markdown (backfill closeout),
(3) main READY_FOR_REVIEW->COMPLETED (cascade + sync). Cada guard reporta que haria
(json: `would_apply`; text: `[DRY-RUN]`) y retorna 0 sin mutar.

## Criterios de Aceptacion
- [x] `--manager-approve --dry-run` deja STATE.md sin cambios (test_dry_run_does_not_mutate_state)
- [x] mutation: quitar el guard de dry-run -> vuelve a mutar (mutation-verify: sync llamado)
- [x] la ejecucion real (sin --dry-run) sigue aplicando la transicion (test_real_run_still_applies_transition)
- [ ] `run_pytest_safe.py --level all` exit 0 (suite final pendiente)
