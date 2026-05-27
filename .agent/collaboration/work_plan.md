# Work Plan - WP-2026-155

## Metadata
- **ID:** WP-2026-155
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Runtime project_root contract hardening
- **Asignado a:** Builder

## Objetivo
Eliminar las derivaciones directas de `project_root` basadas en `__file__` en la capa runtime [A] y consolidar la precedencia canonica `CLI --project-root > env AGENT_PROJECT_ROOT > derivado`.
El hardening de feedback del Manager y la reinyeccion de contexto al relanzar Builder se separan en WP-2026-156 para no mezclar hotfix de transporte con el contrato de `project_root`.

## Fases
0. Verificar que `tests/unit/test_project_root_resolution.py` colecciona limpio.
1. Confirmar el contrato existente de `runtime.project_root.py` y el bootstrap temprano de `AGENT_PROJECT_ROOT`.
2. Desacoplar los call-sites de `scripts/` hacia resolucion lazy compartida.
3. Ajustar entry points y hooks de `.agent/`.
4. Validar con `tests/unit/test_project_root_resolution.py`, `pytest --collect-only` y `agent_controller --validate`.

## Files Likely Touched
- `.agent/agent_controller.py`
- `.agent/agents_config.py`
- `.agent/completion_checker.py`
- `.agent/completion_common.py`
- `.agent/session_tracker.py`
- `.agent/hooks/stop_hook.py`
- `.agent/runtime/memory/memory_helpers.py`
- `runtime/ui_state_projector.py`
- `scripts/manager_review_bridge.py`
- `scripts/local_audit.py`
- `scripts/ticket_supervisor.py`
- `scripts/ticket_activity_monitor.py`
- `scripts/run_gates_dispatch.py`
- `scripts/builder_agent.py`
- `scripts/archive_event_bus.py`
- `scripts/check_deliverables_exist.py`
- `scripts/memory_consolidate.py`
- `scripts/update_project_map.py`
- `scripts/validate_authority.py`
- `scripts/run_pytest_safe.py`
- `tests/unit/test_project_root_resolution.py`
- `tests/conftest.py`
