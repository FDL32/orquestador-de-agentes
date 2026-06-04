# Claude Project Guide

## Inicio de sesion

Ejecutar siempre:

```bash
python .agent/agent_controller.py
```

Si el controller indica otro rol, no actues sobre el ticket.

## Primer arranque tras copiar

Si esta carpeta acaba de copiarse a un proyecto nuevo, Manager debe ejecutar primero:

```bash
python .agent/agent_controller.py --validate --json --force
python .agent/agent_controller.py --json --force
python -m pytest tests/ -q -p no:cacheprovider
```

Si falla algun comando, corregir la instalacion antes de crear el primer plan.

## Roles y Reglas Modulares

Las reglas están fragmentadas en **29 archivos modulares** dentro de `.agent/rules/`:

### Manager
Lee primero:
1. `.agent/rules/common/` — 7 archivos con reglas compartidas
2. `.agent/rules/manager/` — 9 archivos específicos del Manager

Crea planes, revisa implementaciones y cierra tickets.

### Builder
Lee primero:
1. `.agent/rules/common/` — 7 archivos con reglas compartidas
2. `.agent/rules/builder/` — 13 archivos específicos del Builder

Implementa el plan aprobado y documenta evidencia.

**Nota histórica:** Las reglas antiguas (`.agent_common_rules.md`, `.manager_rules`, `.builder_rules`) están archivadas en `.agent/legacy/` y no deben usarse.

## Comandos

```bash
python .agent/agent_controller.py --json --force
python .agent/agent_controller.py --validate --json --force
python scripts/run_pytest_safe.py
python scripts/run_pytest_safe.py --level all
```

## Seguridad

- No acceder a `privada/`.
- No tocar `.env` ni secretos.
- No ejecutar acciones destructivas sin aprobacion.
- Revisar `.agent/logs/security.log` si hay bloqueos.

## Archivos clave

- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/execution_log.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/notifications.md`
- `.agent/agent_controller.py`
- `.agent/hooks/guard_paths.py`
- `.agent/rules/**/*.md` — Reglas modulares (ver arriba)

## Copia a nuevos proyectos

No copiar caches ni temporales:

- `.tmp/`
- `.pytest_cache/`
- `.ruff_cache/`
- `tmp_pytest_*`
- `__pycache__/`
- `.agent/test_logs/`
- `.agent/logs/*.log`
