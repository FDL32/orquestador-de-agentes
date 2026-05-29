# Work Plan - WP-2026-176

## Metadata
- **ID:** WP-2026-176
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Implantar Modelo B - workspace del motor en z_scripts/.agent
- **Asignado a:** Builder

## Objetivo
Implantar el Modelo B: z_scripts/.agent como workspace canonico del desarrollo del motor.

## Decision Arquitectonica
Motor code-only en orquestador_de_agentes; workspace en z_scripts/.agent via AGENT_PROJECT_ROOT.

## Non-goals
- No implementar rediseno de memoria L0-L3.
- No migrar observations.jsonl al schema nuevo.
- No crear shims duplicados de agent_controller.py.

## Fases
Fases 1-3 completadas. Fase 4 completada con backup verificado.

## Files Likely Touched
- bus/review_bridge.py
- scripts/launch_agent_terminals.ps1
- .agent/agent_controller.py
- runtime/project_root.py
- tests/test_agent_controller.py
- tests/test_launch_agent_terminals_script.py
- tests/test_manager_review_bridge.py
- MANIFEST.workspace
- .agent/collaboration/backlog.md
- .agent/config/motor_destination_link.json
- scripts/install_agent_system.py

## Criterios de aceptacion
- Bridge y launcher resuelven controller desde motor_root con --project-root.
- Guard anti-drift bloquea escrituras sin AGENT_PROJECT_ROOT.
- z_scripts/.agent queda como workspace canonico con config correcta.
- 381 tests pasan, ruff limpio.
