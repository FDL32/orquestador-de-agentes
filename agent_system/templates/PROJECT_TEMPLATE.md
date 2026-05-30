# PROJECT.md — Project Manifest

Rellena los placeholders `{{...}}`. Este archivo es la fuente de verdad
canónica para el motor del agente.

## Identidad del Proyecto

- **Nombre:** {{project_name}}
- **Propósito:** {{project_purpose}}
Ticket prefix: XXX

> **ATENCIÓN:** Reemplaza `XXX` por el prefijo real (ej. `MI_PROY`).
> El motor necesita esta línea exacta para validar tickets.

## Stack Tecnológico

- **Runtime:** {{runtime}}
- **Package manager:** {{package_manager}}
- **Testing:** {{test_framework}}
- **Linter:** {{linter}}

## Rutas Críticas

- `{{path_source}}/` — código fuente principal
- `{{path_tests}}/` — tests
- `{{path_config}}/` — configuración

## Reglas y Non‑Goals

- {{rule_1}}
- {{non_goal_1}}

## CHANGELOG.md

Compañero de este manifiesto. Registra decisiones arquitectónicas y cambios
notables. Mantenlo actualizado junto con PROJECT.md.

---
*Generado por orquestador_de_agentes — completa los placeholders.*
