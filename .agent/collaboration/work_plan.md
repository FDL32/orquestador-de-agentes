# Work Plan - WP-2026-137

## Metadata
- **ID:** WP-2026-137
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Supervisor startup lock and reconciliation dedupe
- **Asignado a:** Builder

## Objetivo
Eliminar la repeticion de `SUPERVISOR_RECONCILED` cuando el supervisor se arranca varias veces sobre el mismo ticket, reforzando el arranque con lock atómico, verificacion de liveness e idempotencia de reconciliacion.

## Decision Arquitectonica
- El supervisor debe comportarse como una instancia unica por ticket activo.
- El lock debe adquirirse de forma atomica (`O_CREAT | O_EXCL`) para evitar TOCTOU.
- La reconciliacion debe ser idempotente para el mismo par `previous_ticket` / `recovered_ticket`.
- El launcher no debe bloquear el arranque por presencia del lock; como mucho puede informar y dejar que Python decida por liveness.
- Si el PID check no esta disponible, el fallback de mtime debe ser corto y conservador.
- La semantica de `run_reactive()` debe distinguir claramente entre "no hubo cambios" y "no se pudo adquirir lock".
- El fix se limita a supervisor, launcher y tests; no toca la memoria persistente ni el flujo de auditoria.

## Files Likely Touched
- `bus/supervisor.py`
- `scripts/launch_agent_terminals.ps1`
- `scripts/ticket_supervisor.py`
- `tests/test_supervisor.py`
- `tests/test_launch_agent_terminals_script.py`

## Fases
1. Añadir el lock de arranque atomico del supervisor y definir la semantica de liberacion/liveness.
2. Hacer idempotente la emision de `SUPERVISOR_RECONCILED` para el mismo ticket recuperado.
3. Revisar el launcher para que no sea el mecanismo de seguridad y solo actue como capa informativa/operativa.
4. Cubrir el comportamiento con tests de arranque repetido, contencion de lock y dedupe.

## Calidad
- `python scripts/run_pytest_safe.py tests/test_supervisor.py tests/test_launch_agent_terminals_script.py -q`
- `ruff check bus scripts tests`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `SUPERVISOR_RECONCILED` no se emite mas de una vez para el mismo `previous_ticket` / `recovered_ticket`.
- El lock se adquiere de forma atomica y no hay ventana TOCTOU.
- El launcher no bloquea el sistema si el lock queda huérfano; Python resuelve la liveness.
- El estado del ticket recuperado sigue siendo correcto tras arranques repetidos.
- Los tests cubren el camino feliz y el path de contencion del lock.
- La validacion canonica pasa sin errores.
