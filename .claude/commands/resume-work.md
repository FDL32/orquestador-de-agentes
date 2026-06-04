Retoma una sesión pausada de forma segura.

1. Ejecuta `python .agent/agent_controller.py --recover`.
2. Ejecuta `python .agent/agent_controller.py`.
3. Lee `TURN.md`, `work_plan.md`, `execution_log.md` y `STATE.md` si existe.
4. Resume en 3-5 líneas el estado actual y el siguiente paso recomendado.
5. Continúa solo si el turno coincide con tu rol; si no, informa al usuario.
