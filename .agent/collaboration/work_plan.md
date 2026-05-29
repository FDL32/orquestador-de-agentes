# Work Plan - WP-2026-174

## Metadata
- **ID:** WP-2026-174
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Persist manager review bridge checkpoint across supervisor restarts
- **Asignado a:** Builder

## Objetivo
Evitar que el manager review bridge vuelva a procesar eventos ya consumidos cuando el supervisor se reinicia. Para ello, el bridge debe usar un checkpoint duradero propio para `last_processed_sequence` en lugar de depender solo del estado de heartbeat del bridge.

## Contexto
- El bridge ya persiste `manager_bridge_state.json`, pero ese archivo está ligado al heartbeat operativo y puede ser reparado o limpiado por los flujos de arranque.
- El incidente observado muestra que el watermark del bridge no es suficientemente estable para sobrevivir a ciertos reinicios del supervisor.
- La solucion debe separar telemetria viva de cursor duradero.
- No se va a tocar `bus/supervisor.py`; este ticket solo endurece la persistencia del bridge.
- La nueva persistencia duradera debe vivir en `.agent/runtime/bridge_checkpoint.json`, junto al resto del runtime del bridge.

## Decision Arquitectonica
- `scripts/manager_review_bridge.py` añade un checkpoint duradero separado del heartbeat, por ejemplo `bridge_checkpoint.json`, para guardar `last_processed_sequence`.
- El checkpoint se carga al iniciar el bridge y se actualiza tras procesar una review satisfactoriamente.
- La carga inicial debe combinar dos fuentes: `bridge_checkpoint.json` y el `last_processed_sequence` que ya exista en `manager_bridge_state.json`, escogiendo el mayor valor disponible para evitar reprocesar eventos cuando solo una de las dos superficies exista.
- `manager_bridge_state.json` sigue existiendo para heartbeat y metadatos de vida del bridge, pero deja de ser la fuente de verdad del watermark.
- Si `bridge_checkpoint.json` falta o esta corrupto, el bridge usa el valor que pueda rescatar de `manager_bridge_state.json`; solo si ambas superficies faltan o son inutilizables arranca en cero sin romper el flujo.
- Si el supervisor se reinicia y el checkpoint duradero sigue presente, el bridge no debe reprocesar eventos ya consumidos.
- El checkpoint duradero se escribe despues de que `_save_state()` haya completado, nunca antes, para que el cursor y el heartbeat no queden desincronizados.
- El bridge sigue escribiendo `last_processed_sequence` en `manager_bridge_state.json` como superficie viva de compatibilidad, pero esa escritura deja de ser la fuente de verdad del watermark.

## Non-goals
- No cambiar la logica de `bus/supervisor.py`.
- No cambiar el protocolo de `READY_FOR_REVIEW`.
- No alterar el flujo de aprobacion del Manager.
- No introducir nuevas dependencias.

## Fases

### Fase 1: checkpoint duradero del bridge
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/manager_review_bridge.py`
- **Accion:** Modificar
- **Descripcion:** Introducir un checkpoint duradero propio del bridge para `last_processed_sequence`, con carga al arranque y persistencia tras cada review procesada. El heartbeat del bridge puede seguir viviendo en `manager_bridge_state.json`, pero el cursor de consumo debe guardarse en `.agent/runtime/bridge_checkpoint.json`. Al arrancar, el bridge debe tomar el maximo entre el checkpoint duradero y el watermark que pudiera existir en `manager_bridge_state.json`. Si el checkpoint falta o esta corrupto, el bridge debe usar la otra fuente disponible; solo si ambas faltan o son inutilizables arranca en cero. El checkpoint duradero se escribe despues de `_save_state()`, nunca antes.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** El bridge conserva el watermark entre reinicios del supervisor y no re-procesa un `READY_FOR_REVIEW` ya consumido. Si el checkpoint duradero es mayor que `manager_bridge_state.json`, el bridge usa el valor mayor. Si el checkpoint falta, el bridge puede rescatar el valor del heartbeat si existe.
- **Si falla:** Mantener el comportamiento actual y limitar el cambio a la lectura del checkpoint duradero.

### Fase 2: cobertura mecanica
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_manager_review_bridge.py`
- **Accion:** Modificar
- **Descripcion:** Cubrir al menos cuatro casos: persistencia del checkpoint tras una review, arranque con checkpoint existente que evita reprocesar eventos viejos, arranque seguro cuando el checkpoint falta o esta corrupto, y caso defensivo donde `bridge_checkpoint.json` contiene una secuencia mayor que `manager_bridge_state.json` y el bridge debe conservar el mayor valor.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Los tests demuestran que el watermark del bridge sobreviva al reinicio del supervisor y que el flujo sigue detectando `READY_FOR_REVIEW` correctamente.
- **Si falla:** Conservar la persistencia actual del bridge y limitar la cobertura al camino feliz.

## Files Likely Touched
- `scripts/manager_review_bridge.py`
- `tests/test_manager_review_bridge.py`

## Calidad
- `python scripts/run_pytest_safe.py tests/test_manager_review_bridge.py`
- `uv run ruff check scripts/manager_review_bridge.py tests/test_manager_review_bridge.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- El checkpoint duradero del bridge se conserva tras reinicios del supervisor.
- El bridge no reprocesa eventos ya consumidos cuando vuelve a arrancar.
- El arranque sigue siendo seguro si el checkpoint falta o esta corrupto.
- Si ambas superficies existen, el bridge toma el mayor `last_processed_sequence` disponible.
- La persistencia viva del bridge sigue separada de la telemetria de heartbeat.
