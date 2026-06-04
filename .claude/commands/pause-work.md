Pausa la sesión actual de forma limpia.

1. Ejecuta `python .agent/agent_controller.py` para confirmar el turno.
2. Lee `work_plan.md`, `execution_log.md` y `STATE.md` si existe.
3. Deja un resumen breve del estado actual:
   - tarea activa
   - qué falta
   - próximo paso
   - archivos tocados
   - riesgos abiertos
4. Si la sesión es larga o hay contexto denso, recuerda al usuario que puede usar
   `python .agent/agent_controller.py --recover` al volver.
5. No cambies `work_plan.md` salvo que tu rol lo permita expresamente.
