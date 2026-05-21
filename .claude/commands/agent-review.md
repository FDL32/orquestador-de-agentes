Usa el flujo de **review formal** del sistema.

1. Ejecuta `python .agent/agent_controller.py`.
2. Si el turno no es `MANAGER`, informa al usuario y no continÃºes.
3. Lee completos `.agent_common_rules.md`, `.manager_rules`, `.agent/collaboration/constitution.md`, `work_plan.md` y `execution_log.md`.
4. Empieza por `execution_log.md` y, si hay git, revisa `git diff HEAD` para orientarte.
5. Lee el cÃ³digo real y aplica el protocolo de validaciÃ³n de hallazgos.
6. Re-ejecuta tÃº mismo las validaciones necesarias antes de aprobar.
7. Si no hay issues vÃ¡lidos, dilo explÃ­citamente: `RevisiÃ³n sin issues`.
