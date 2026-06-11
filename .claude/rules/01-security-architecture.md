# Arquitectura de Seguridad y Controles Automáticos

> Reglas operativas básicas (no tocar `privada/`, no commitear secretos, no desactivar `guard_paths`): ver [AGENTS.md sección "Secretos y seguridad"](../../AGENTS.md#secretos-y-seguridad). Este archivo añade detalles técnicos específicos de Claude Code (hooks, pip-audit, allowlist).

## Política de Secretos
1. **`privada/`**: FUERA del workspace del agente. Contiene `.env` y configuración sensible. NUNCA leer ni escribir aquí.
2. **Workspace del agente**: usa `.env.example` con variables vacías; nunca un `.env` real.
3. **Carga de secretos**: siempre vía variables de entorno desde `privada/`, nunca hardcodeadas en código del repo.
- **PROHIBIDO** hardcodear tokens/passwords. Usar siempre variables de entorno y `***REDACTED***` en logs.

## Controles Activos
### Hook `guard_paths` (Claude Code)
Registrado en `.claude/settings.json`. Bloquea escrituras en:
- `privada/` y archivos `.env`
- `.agent/collaboration/TURN.md`
- Si el hook bloquea, informa al usuario y detente.

### `pip-audit` (Supply Chain)
Ejecuta `python scripts/pip_audit_project.py` localmente (pre-push) para detectar CVEs en dependencias del proyecto. No se aceptan vulnerabilidades sin mitigación explícita o documentación en `PROJECT.md`.

### State Drift Detection
`agent_controller.py --validate` previene estados imposibles entre `work_plan.md` y `execution_log.md` (e.g. plan en IN_PLANNING pero log en READY_FOR_REVIEW). Corrige el log activo si se detecta un drift.

### Allowlist de Lectura Remota
Si operas como agente remoto, limita la lectura a: `scripts/`, `bus/`, `runtime/`, `tests/unit/`, `pyproject.toml`, `.md` de raíz, y `agent_system/docs/reference/`.
