# Protocolo de Inicio y Flujo Principal

> **Carga de memoria:** ejecuta el mecanismo en `prompts/_shared/memory_bootstrap.md`
> al arrancar **solo si el indice de memoria NO esta ya en tu contexto**. En Claude Code el
> hook SessionStart lo inyecta en cada arranque (startup/resume/compact; indice acotado
> ~9k chars, `SESSION_CONTEXT_MAX_CHARS`): no lo repitas;
> si ves el indice inyectado, usa `--recall` para expandir. Motivo: sin carga, el agente
> opera con 0 lecciones y repite errores ya documentados en la memoria del proyecto.

## Flujo y Quality Gates
- Flujo Manager → Builder (7 pasos): `.agent/rules/common/manager_builder_flow.md`.
- Quality Gates (obligatorios antes de cada review): `AGENTS.md` "Comandos principales" (pip-audit, ruff, pytest-safe).

## Error y Debug
- Registrar errores persistentes en `PROJECT.md` (sin datos sensibles, usar `***REDACTED***`).
- Scripts de un solo uso o depuración deben ir a `tests/sandbox/debug_*.py`. Nunca en la raíz.
