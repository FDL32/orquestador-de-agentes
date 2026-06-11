# Arquitectura del Sistema Multi-Agente

## Relación de Carpetas
- **`agent_system/`**: Framework fuente y documentación de referencia. NO debe copiarse ni modificarse en proyectos derivados.
- **`orquestador_de_agentes/`**: Carpeta plantilla que se copia a los proyectos nuevos. Se sincroniza manualmente tras actualizar `agent_system/`. NO editar el `PROJECT.md` o `CLAUDE.md` de la plantilla directamente si es trabajo propio de un proyecto derivado.

## Reglas Modulares del Orquestador (`.agent/rules/`)
Las reglas del motor orquestador (Goose, Claw) se dividen en:
- `common/`: Obligatorias para Manager y Builder (e.g. startup, security, git).
- `builder/`: Específicas del desarrollador (e.g. identity, validaciones).
- `manager/`: Específicas del gestor (e.g. review protocol).
Los archivos monolíticos `.builder_rules` etc. son **legacy**.

## Integración de Agentes Externos [DEPRECATED - WT-2026-254a]

> **DEPRECATED:** Goose y Claw están deprecados como motores de orquestación.
> Claude Code es el agente principal. Las referencias siguientes son históricas.

- `goose.exe`: **[DEPRECATED]** Leia `.goosehints` e integraba contexto de skills.
- `claw.exe`: **[DEPRECATED]** Experimental. Leía `.clawrules`.
- Invocación oficial: `python scripts/orquestador.py --stage [etapa]` — mantener solo para compatibilidad.
