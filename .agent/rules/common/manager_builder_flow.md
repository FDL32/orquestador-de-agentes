# Flujo de Trabajo (Manager → Builder)

> Referencia bajo demanda (WOT-2026-120a corrida 6): movida literal desde
> `.claude/rules/00-startup.md` (seccion "Flujo de Trabajo") para sacarla de la autocarga de
> Claude Code; solo se ajustan los enlaces relativos a la nueva ubicacion.

> Ver detalle completo en [PROJECT.md sección "Current Cycle"](../../../PROJECT.md#current-cycle) y [prompts/orchestrator_session_bootstrap.md](../../../prompts/orchestrator_session_bootstrap.md).

1. **[Usuario]** Describe tarea al Manager.
2. **[Manager]** Crea `work_plan.md` (Tipo: IMPLEMENTATION) → Usuario aprueba.
3. **[Builder]** Implementa → Ejecuta Quality Gates (`ruff`, `pytest`, `pip-audit`).
4. **[Manager]** Revisa código real (no solo logs) → Usuario aprueba.
5. **[Manager]** Crea `work_plan.md` (Tipo: FINALIZATION) → cierre por fases.
6. **[Builder]** Ejecuta cierre fase a fase → Manager aprueba cada fase.
7. **[Usuario]** Recibe proyecto cerrado profesionalmente.
