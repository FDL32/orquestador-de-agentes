Usa el flujo de **planificación** del sistema.

1. Ejecuta `python .agent/agent_controller.py`.
2. Si el turno no es `MANAGER`, informa al usuario y no continúes.
3. Lee completos `.agent_common_rules.md`, `.manager_rules` y `.agent/collaboration/constitution.md`.
4. Si el requisito es ambiguo, haz como máximo 3 preguntas de clarificación.
5. Crea o completa `work_plan.md` con criterios de aceptación verificables.
6. Deja el plan en estado `APPROVED` solo cuando esté completo y coherente.
7. Explica al usuario cuál es el siguiente paso y si corresponde pasar al Builder.
