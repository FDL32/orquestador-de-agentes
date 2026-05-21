# Claude Code Rules (Modular Context)

Este directorio contiene instrucciones modulares que se cargan selectivamente según el contexto de la tarea para evitar sobrecargar la ventana de contexto principal.

## Cargas automáticas recomendadas:
- `00-startup.md`: Siempre (protocolo de inicio y bitácoras).
- `01-security-architecture.md`: Si tocas variables de entorno, hooks o cambias permisos.

## Cargas bajo demanda recomendadas:
- `02-multi-agent-system.md`: Si trabajas en el sistema orquestador `.agent/`.
- `03-skills-discovery.md`: Si estás diseñando o modificando micro-habilidades bajo `skills/`.
- `04-refactor-kit.md`: Si utilizas el refactor kit portable.
- `05-session-artifacts.md`: Si requieres entender el flujo profundo de la carpeta `.session/` y el ciclo de vida de los logs.

> **Nota para el Agente:** Usa tu comando natural para leer estos archivos únicamente cuando entres en uno de estos dominios. Ver `CLAUDE.md` (raíz) para instrucciones de Claude Code específicas.
