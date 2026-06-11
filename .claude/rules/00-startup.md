# Protocolo de Inicio y Flujo Principal

## Flujo de Trabajo (Manager → Builder)

> Ver detalle completo en [PROJECT.md sección "Current Cycle"](../PROJECT.md#current-cycle) y [prompts/session_bootstrap.md](../prompts/session_bootstrap.md).

1. **[Usuario]** Describe tarea al Manager.
2. **[Manager]** Crea `work_plan.md` (Tipo: IMPLEMENTATION) → Usuario aprueba.
3. **[Builder]** Implementa → Ejecuta Quality Gates (`ruff`, `pytest`, `pip-audit`).
4. **[Manager]** Revisa código real (no solo logs) → Usuario aprueba.
5. **[Manager]** Crea `work_plan.md` (Tipo: FINALIZATION) → cierre por fases.
6. **[Builder]** Ejecuta cierre fase a fase → Manager aprueba cada fase.
7. **[Usuario]** Recibe proyecto cerrado profesionalmente.

## Quality Gates (obligatorios antes de cada review)

> Ver detalle en [QUICKSTART.md sección "6. Comandos diarios"](../QUICKSTART.md#6-comandos-diarios).

- **Auditoría de dependencias:** `python scripts/pip_audit_project.py`
- **Linter y Formatter:** `ruff check .` y `ruff format .`
- **Tests:** `python scripts/run_pytest_safe.py`

## Error y Debug
- Registrar errores persistentes en `PROJECT.md` (sin datos sensibles, usar `***REDACTED***`).
- Scripts de un solo uso o depuración deben ir a `tests/sandbox/debug_*.py`. Nunca en la raíz.
