# Arquitectura del Sistema Multi-Agente

## Relación de Carpetas
- **`agent_system/`**: Framework fuente y documentación de referencia. NO debe copiarse ni modificarse en proyectos derivados.
- **`orquestador_de_agentes/`**: Carpeta plantilla que se copia a los proyectos nuevos. Se sincroniza manualmente tras actualizar `agent_system/`. NO editar el `PROJECT.md` o `CLAUDE.md` de la plantilla directamente si es trabajo propio de un proyecto derivado.

## Reglas Modulares del Orquestador (`.agent/rules/`)
Las reglas del orquestador se dividen en:
- `common/`: Obligatorias para Manager y Builder (e.g. startup, security, git).
- `builder/`: Específicas del desarrollador (e.g. identity, validaciones).
- `manager/`: Específicas del gestor (e.g. review protocol).
Los archivos monolíticos `.builder_rules` etc. son **legacy**.

## Backend de IA

Claude Code es el agente principal y el único backend soportado. Los motores de
orquestación externos que existieron en versiones previas fueron retirados
(WT-2026-254a; ver CHANGELOG e historial de tickets). La ejecución de skills se
hace vía `python scripts/orquestador.py --skill /<trigger>`.
