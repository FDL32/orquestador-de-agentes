# Topology & artifact locations (cid-topology-artifact-locations-v0)

> Fuente unica de verdad sobre DONDE vive cada artefacto operativo en la topologia
> motor<->destino. Adoptada en WOT-2026-029b (M22, flight_20260718) para corregir el
> patron "root equivocado" (auditor o Builder leyendo estado operativo en `repo_motor`
> en vez de `repo_destino`, o viceversa).

## Regla de topologia

- `repo_motor` (`<MOTOR_ROOT>`) es CODIGO SOLAMENTE. Su propio `.agent/` es una
  **semilla neutra** (molde para destinos nuevos), NO estado operativo. Nunca
  leas ni escribas estado operativo ahi.
- `repo_destino` (`<DESTINO_ROOT>`) es donde vive el estado operativo y los
  artefactos: tickets, memoria, eventos, reportes.

## Mapa de artefactos

Expresado siempre en terminos de rol (`<MOTOR_ROOT>` / `<DESTINO_ROOT>`), nunca
como ruta absoluta de una maquina concreta ni con el nombre de una instancia de
dogfooding especifica.

| Artefacto | Vive en |
|---|---|
| Backlog | `<DESTINO_ROOT>/.agent/collaboration/backlog.md` |
| Estado de colaboracion (work_plan, execution_log, STATE, TURN) | `<DESTINO_ROOT>/.agent/collaboration/` |
| Eventos del bus | `<DESTINO_ROOT>/.agent/runtime/events/events.jsonl` |
| Memoria por proyecto | `<DESTINO_ROOT>/.agent/runtime/memory/` |
| Reportes de pipeline | `<DESTINO_ROOT>/orchestrator_pipeline/reports/` |
| Superficies de codigo del motor | `<MOTOR_ROOT>/scripts/`, `<MOTOR_ROOT>/prompts/`, `<MOTOR_ROOT>/bus/` |

## Mecanismo de resolucion

El root activo se resuelve via `AGENT_PROJECT_ROOT` / `--project-root`; el
enlace motor<->destino via `resolve_motor_link(project_root)`
(`from scripts.destination_context import resolve_motor_link`); y el modo via
`is_motor_code_only()` (`from runtime.project_root import is_motor_code_only`).
`is_motor_code_only()` es un **write-guard** sobre el `.agent/` del motor, no un
detector de bus en vivo: distingue "estoy en modo codigo-solo" de "hay o no
actividad operativa real".
