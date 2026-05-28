# Execution Log - WP-2026-159

## Metadata
- **ID:** WP-2026-159
**Estado:** COMPLETED
- **deliverable_type:** code

## Agente Activo
- **Rol:** BUILDER
- **Accion:** IMPLEMENT
- **Plan:** Reactive Builder relaunch after CHANGES

## Fases
- Phase 0: instrumentar cada intento de relanzado para hacer observable el motivo real de skip/fallo/success.
- Phase 1: aplicar el fix dirigido segun el diagnostico de la instrumentacion.
- Phase 2: smoke path reactivo estable.

## Registro de Implementacion
- Ticket preparado para Builder para probar el bus end-to-end en el ciclo reactivo.
- `requeue_ticket()` sigue siendo la unica autoridad para incrementar `loop_current_round` y lanzar Builder.
- Los estados terminales deben fallar cerrado.
- El modo reactivo debe permanecer vivo tras relanzar.
- Los tests deben usar `tmp_path` y mocks, sin subprocess real.

### Fase 0: Instrumentacion completada
- `_run_launcher_subprocess(cmd)` extraido como seam inyectable para testabilidad sin depender de `PYTEST_CURRENT_TEST`.
- `_persist_relaunch_log(stdout, stderr)` guarda output en `.agent/runtime/logs/launcher_last.log`.
- Evento `BUILDER_RELAUNCH_ATTEMPTED` emitido con payload: `{"round": N, "outcome": "success|skipped_alive|launcher_failed|timeout", "exit_code": int|null, "stderr_tail": str|null}`.
- Tests: `test_run_launcher_subprocess_success`, `test_run_launcher_subprocess_timeout`, `test_run_launcher_subprocess_exception`, `test_persist_relaunch_log_writes_file`, `test_relaunch_emits_event_skipped_alive`, `test_relaunch_emits_event_launcher_failed`, `test_relaunch_emits_event_success`, `test_relaunch_emits_event_timeout`, `test_relaunch_launcher_not_found_emits_event`, `test_relaunch_powershell_not_found_emits_event`, `test_relaunch_seam_allows_monkeypatch_without_pytest_check`.

### Fase 1: Fix dirigido completado
- `last_requeue_trigger_sequence` añadido a `SupervisorState` como watermark persistido.
- `run_once()` implementa logica para detectar nuevo `CHANGES` y evitar doble requeue usando watermark.
- `RELAUNCH_BLOCKED_STATES` bloquea relanzado en `HUMAN_GATE`, `READY_TO_CLOSE`, `COMPLETED`.
- Tests: `test_supervisor_preserves_loop_round_after_changes`, `test_supervisor_skips_relaunch_on_human_gate`, `test_run_once_triggers_requeue_on_review_decision_changes`, `test_run_once_watermark_prevents_double_requeue`, `test_run_once_requeue_watermark_persists_across_calls`.

### Fase 2: Smoke path reactivo estable
- `test_run_reactive_smoke_with_requeue_polling`: Verifica loop mantiene polling despues de requeue y respeta timeout/idle timeout.
- Tests existentes reforzados: `test_run_reactive_uses_idle_timeout_reset`, `test_run_reactive_releases_lock_on_exit`.

## Criterios de Aceptacion
- [x] La instrumentacion permite distinguir `skipped_alive`, `launcher_failed`, `timeout` y `success`.
- [x] Un `CHANGES` nuevo relanza Builder automaticamente una sola vez.
- [x] Un segundo `CHANGES` repetido no duplica relanzado ni incrementa el round indebidamente.
- [x] Los estados terminales siguen fallando cerrado.
- [x] El modo `--reactive` permanece vivo despues del relanzado.
- [x] La validacion canonica y la suite safe siguen pasando.

## Evidencia Esperada
- `python -m pytest tests/test_supervisor.py -q`
- `python scripts/ticket_supervisor.py --reactive --timeout 1`
- `python scripts/run_pytest_safe.py`
- `python .agent/agent_controller.py --validate --json --force`

## Quality Gates Results (2026-05-28)
- `ruff check .`: All checks passed!
- `python scripts/run_pytest_safe.py`: 319 passed in 44.72s
- `python .agent/agent_controller.py --validate --json --force`: 0 errors (validacion completada)

## Criterios de Aceptacion - Evidencia
- [x] La instrumentacion permite distinguir `skipped_alive`, `launcher_failed`, `timeout` y `success`.
  - **Evidencia:** Tests `test_relaunch_emits_event_*` en `tests/test_supervisor.py` verifican payload de `BUILDER_RELAUNCH_ATTEMPTED` con outcome distinto para cada caso.
- [x] Un `CHANGES` nuevo relanza Builder automaticamente una sola vez.
  - **Evidencia:** Test `test_run_once_triggers_requeue_on_review_decision_changes` verifica que `run_once()` llama a `requeue_ticket()` una sola vez ante nuevo `CHANGES`.
- [x] Un segundo `CHANGES` repetido no duplica relanzado ni incrementa el round indebidamente.
  - **Evidencia:** Test `test_run_once_watermark_prevents_double_requeue` verifica que watermark `last_requeue_trigger_sequence` bloquea segundo relanzado con mismo sequence.
- [x] Los estados terminales siguen fallando cerrado.
  - **Evidencia:** `RELAUNCH_BLOCKED_STATES = {HUMAN_GATE, READY_TO_CLOSE, COMPLETED}` + test `test_supervisor_skips_relaunch_on_human_gate`.
- [x] El modo `--reactive` permanece vivo despues del relanzado.
  - **Evidencia:** Test `test_run_reactive_smoke_with_requeue_polling` verifica loop continua polling tras requeue hasta timeout.
- [x] La validacion canonica y la suite safe siguen pasando.
  - **Evidencia:** `ruff check .`: All checks passed! | `pytest-safe`: 319 passed | `agent_controller --validate`: 0 errors

Marked ready by Builder (2026-05-28)

Manager requested changes (1 rejections)

Scope override: Archivos de archivado WP-2026-158 no relacionados con WP-2026-159. Files Likely Touched respetados: bus/supervisor.py, tests/test_supervisor.py. Affected files: C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\.agent\collaboration\AUDIT_WP-2026-158.md, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\.agent\collaboration\PLAN_WP-2026-158.md, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\.agent\collaboration\_archive\plan_audit\AUDIT_WP-2026-158.md, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\.agent\collaboration\_archive\plan_audit\PLAN_WP-2026-158.md

Manager requested changes (2 rejections)

Scope override: in-scope WP-2026-159 files already committed; remaining diff is excluded collaboration/runtime hotfix artifacts. Affected files: C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\bus\supervisor.py, C:\Users\fdl\Proyectos_Python\z_scripts\orquestador_de_agentes\tests\test_supervisor.py

Manager approved canonical closeout for WP-2026-159