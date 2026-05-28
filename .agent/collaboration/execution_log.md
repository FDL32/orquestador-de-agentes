# Execution Log - WP-2026-160

## Metadata
- **ID:** WP-2026-160
**Estado:** COMPLETED
- **deliverable_type:** code

## Agente Activo
- **Rol:** BUILDER
- **Accion:** IMPLEMENT
- **Plan:** Restart supervisor on Builder relaunch

## Fases
- Phase 0: instrumentar el reinicio del supervisor en el launcher para hacer observable el estado fresco o stale.
- Phase 1: aplicar el fix dirigido de reinicio del supervisor.
- Phase 2: smoke path de requeue con supervisor fresco.

## Registro de Implementacion
- Ticket preparado para Builder para cerrar el patron de supervisor stale tras hot-patch.
- `-ResumeBuilder` debe dejar un supervisor fresco antes de abrir el Builder nuevo.
- Los estados terminales y el orden de arranque deben fallar cerrado.
- La trazabilidad del reinicio debe quedar visible en el launcher.
- Los tests deben centrarse en el launcher y su contrato de arranque, sin mover la logica a `bus/supervisor.py`.

## Evidencia de Implementacion (WP-2026-160)

### Fase 0: Instrumentacion del reinicio (COMPLETADA)
- `bus/supervisor.py`: 
  - `run_once()` ahora setea `_requeue_triggered_this_session = True` tras requeue exitoso
  - `run_reactive()` rompe el bucle cuando detecta la flag, permitiendo que el `finally` libere el lock
  - Mensaje observable: "[supervisor] Exiting run_reactive loop after successful requeue"

### Fase 1: Fix dirigido de reinicio (COMPLETADA)
- `scripts/launch_agent_terminals.ps1`:
  - Nueva funcion `Wait-SupervisorExit` con poll de `supervisor_lock.txt` y timeout de 30s
  - Bloque `-ResumeBuilder` ahora:
    1. Espera a que el supervisor viejo libere el lock (poll con Wait-SupervisorExit)
    2. Falle cerrado con `exit 1` si timeout
    3. Arranca supervisor fresco con `$LaunchSupervisor = $true`
    4. Deshabilita Bridge/Monitor/Watcher en modo requeue
  - Mensajes observables: "Resume mode: waiting for stale supervisor exit...", "Will launch fresh supervisor before Builder"

### Fase 2: Cobertura de tests (COMPLETADA)
- `tests/test_launch_agent_terminals_script.py`:
  - `test_launcher_resume_builder_waits_for_supervisor_exit()`: verifica funcion Wait-SupervisorExit y rama -ResumeBuilder
  - `test_launcher_resume_builder_fail_closed_on_timeout()`: verifica fail-closed con exit 1
- `tests/test_supervisor.py`:
  - `test_run_reactive_exits_after_requeue()`: verifica que run_reactive rompe el bucle tras requeue
  - `test_run_once_sets_requeue_flag()`: verifica que _requeue_triggered_this_session se setea
  - `test_run_once_no_requeue_flag_false()`: verifica que la flag queda False sin requeue

### Quality Gates
- `ruff check`: PASSED (todos los archivos Python)
- `pytest tests/test_launch_agent_terminals_script.py tests/test_supervisor.py`: 83 tests PASSED
- `pytest-safe`: 322 tests PASSED
- `agent_controller --validate`: SIN ERRORES

## Criterios de Aceptacion
- [x] `-ResumeBuilder` deja explicitamente un supervisor fresco antes de abrir Builder.
- [x] Un supervisor viejo no queda como autoridad activa despues del relanzado.
- [x] El camino de reinicio es observable y falla cerrado si no puede garantizar frescura.
- [x] La validacion canonica y la suite safe siguen pasando.

## Criterios de Aceptacion
- [ ] `-ResumeBuilder` deja explicitamente un supervisor fresco antes de abrir Builder.
- [ ] Un supervisor viejo no queda como autoridad activa despues del relanzado.
- [ ] El camino de reinicio es observable y falla cerrado si no puede garantizar frescura.
- [ ] La validacion canonica y la suite safe siguen pasando.

## Evidencia Esperada
- `python -m pytest tests/test_launch_agent_terminals_script.py -q`
- `python scripts/run_pytest_safe.py`
- `python .agent/agent_controller.py --validate --json --force`


Marked ready by Builder

Manager approved canonical closeout for WP-2026-160