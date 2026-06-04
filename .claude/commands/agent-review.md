Usa el flujo de **review formal** del sistema.

1. Ejecuta `python .agent/agent_controller.py`.
2. Si el turno no es `MANAGER`, informa al usuario y no continúes.
3. Lee completos `.agent_common_rules.md`, `.manager_rules`, `.agent/collaboration/constitution.md`, `work_plan.md` y `execution_log.md`.
4. Empieza por `execution_log.md` y, si hay git, revisa `git diff HEAD` para orientarte.
5. Lee el código real y aplica el protocolo de validación de hallazgos.
6. Re-ejecuta tú mismo las validaciones necesarias antes de aprobar.
7. Si no hay issues válidos, dilo explícitamente: `Revisión sin issues`.
