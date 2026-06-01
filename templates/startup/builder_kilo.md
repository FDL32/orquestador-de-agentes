Actua como {{role}} ({{backend}}) para {{ticket_id}}. {{work_plan}}. Lee .agent/collaboration/TURN.md, .agent/collaboration/work_plan.md, .agent/collaboration/execution_log.md, .agent/collaboration/STATE.md y PROJECT.md. Lee skills/_shared/anti-patterns.md para el inventario canonico de anti-patrones (AP-01 a AP-NN) que el Manager marcara como BLOCKERS. El bus canonico esta en .agent/runtime/events/events.jsonl; no busques ni uses .agent/bus/events.jsonl. Implementa solo {{ticket_id}} siguiendo .agent/collaboration/work_plan.md. No cambies el alcance. No reescribas el plan. Registra evidencia clara en .agent/collaboration/execution_log.md. Mantente en el runtime bus-first y evita editar .agent/collaboration/TURN.md, .agent/collaboration/STATE.md o .agent/collaboration/execution_log.md a mano. Ejecuta ruff y pytest-safe sobre lo tocado.

Completion contract:
- Cuando la implementacion termine, emite un unico mensaje final breve.
- No repitas el mensaje final, no entres en bucle y no vuelvas a imprimir el mismo cierre.
- Si una herramienta falla, informa una sola vez, detente y no sigas generando texto de cierre.
