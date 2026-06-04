Usa el flujo de **implementación formal** del sistema.

1. Ejecuta `python .agent/agent_controller.py`.
2. Si el turno no es `BUILDER`, informa al usuario y no continúes.
3. Lee completos `.agent_common_rules.md`, `.builder_rules`, `work_plan.md` y `execution_log.md`.
4. Implementa la fase activa siguiendo el plan aprobado.
5. Lee completos los archivos antes de editarlos y usa rutas absolutas en tool calls.
6. Documenta evidencia real en `execution_log.md`.
7. Ejecuta validaciones relevantes y `bui-self-audit` antes de dejar `READY_FOR_REVIEW`.
