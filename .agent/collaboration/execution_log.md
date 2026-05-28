# Execution Log - WP-2026-160

## Metadata
- **ID:** WP-2026-160
**Estado:** IN_PROGRESS
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

## Criterios de Aceptacion
- [ ] `-ResumeBuilder` deja explicitamente un supervisor fresco antes de abrir Builder.
- [ ] Un supervisor viejo no queda como autoridad activa despues del relanzado.
- [ ] El camino de reinicio es observable y falla cerrado si no puede garantizar frescura.
- [ ] La validacion canonica y la suite safe siguen pasando.

## Evidencia Esperada
- `python -m pytest tests/test_launch_agent_terminals_script.py -q`
- `python scripts/run_pytest_safe.py`
- `python .agent/agent_controller.py --validate --json --force`
