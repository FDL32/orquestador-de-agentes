# Work Plan - WP-2026-159

## Metadata
- **ID:** WP-2026-159
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Reactive Builder relaunch after CHANGES
- **Asignado a:** Builder

## Objetivo
Endurecer el ciclo reactivo del supervisor para que un `CHANGES` del Manager relance Builder de forma automatica, idempotente y terminal-safe, primero haciendo observable cada intento de relanzado y despues aplicando solo el fix que el diagnostico confirme.

## Contexto
- `bus/supervisor.py` ya dispone de `requeue_ticket()` y `_relaunch_builder()`, y `run_once()` ya detecta `CHANGES`/`IN_PROGRESS`.
- Nunca hemos conseguido verificar con claridad si el fallo esta en la deteccion del requeue, en la liveness del Builder, en el launcher o en una carrera de actualizacion de archivos; por eso primero hace falta instrumentacion.
- `scripts/ticket_supervisor.py --reactive` es la entrada canonica del loop reactivo y ya es invocada por `scripts/launch_agent_terminals.ps1`.
- El primer problema no es el fix final sino la testabilidad: hoy `_relaunch_builder()` corta demasiado pronto para que Fase 0 pueda observar `skipped_alive`, `launcher_failed`, `timeout` o `success` con evidencia real.
- El objetivo de este ticket es probar el bus end-to-end con un ciclo reactivo fiable, sin redisenar el launcher ni el bridge de review.

## Decision Arquitectonica
- Fase 0: instrumentacion primero. Extraer el spawn real del launcher a un seam injectable, por ejemplo `_run_launcher_subprocess(cmd)`, para que `tests/test_supervisor.py` pueda spy/monkeypatchar el boundary sin depender de `PYTEST_CURRENT_TEST` como bloqueo global.
- Fase 0: persistir cada intento de relanzado con un evento `BUILDER_RELAUNCH_ATTEMPTED` y payload fijo: `{"round": N, "outcome": "success|skipped_alive|launcher_failed|timeout", "exit_code": int|null, "stderr_tail": str|null}`.
- Fase 0: guardar stdout/stderr del launcher en `.agent/runtime/logs/launcher_last.log` para hacer observable el fallo sin leer la consola.
- Fase 1: fix dirigido. Una vez observada la causa real, aplicar solo la correccion necesaria en `bus/supervisor.py` y sus tests.
- `requeue_ticket()` sigue siendo la unica via que incrementa `loop_current_round` y lanza Builder.
- `run_once()` sigue siendo la autoridad para nuevos eventos del bus y debe disparar la requeue una sola vez por antecedente nuevo de `CHANGES`, usando un watermark persistido del ultimo trigger procesado para evitar doble requeue si el mismo ciclo genera mas de un `CHANGES`.
- Los estados terminales (`READY_TO_CLOSE`, `COMPLETED`, `HUMAN_GATE`) deben fallar cerrado: no relanzan Builder.
- `run_reactive()` debe seguir vivo tras la requeue y continuar el polling hasta timeout o max runtime.

## Non-goals
- No crear un watcher/daemon nuevo.
- No tocar `bus/review_bridge.py`.
- No cambiar el contrato de `launch_agent_terminals.ps1`.
- No introducir historial acumulado de feedback.
- No meter reintentos, backoff o polling extra hasta que la instrumentacion confirme que son necesarios.
- No mover la decision de requeue al launcher.

## Fases
### Fase 0: instrumentacion del relanzado
- **Tipo:** TAREA AGENTE
- **Archivos:** `bus/supervisor.py`, `tests/test_supervisor.py`
- **Accion:** Instrumentar
- **Descripcion:** Registrar cada intento de requeue y relanzado del Builder con estado observable. La implementacion debe extraer el spawn real a un seam injectable (`_run_launcher_subprocess()` o equivalente) y persistir en logs o eventos del bus el resultado de `_relaunch_builder()`, distinguiendo claramente entre `skipped_alive`, `launcher_failed`, `timeout` y `success`.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Un test de supervisor puede afirmar, sin leer stdout manualmente, si el relanzado fue omitido, fallido, timeouteado o exitoso, y puede hacerlo via monkeypatch del seam sin depender de `PYTEST_CURRENT_TEST` para saltarse la ruta.
- **Si falla:** Mantener la instrumentacion minima en bus/eventos o log persistente, aunque el resto del fix se difiera.

### Fase 1: fix dirigido segun diagnostico
- **Tipo:** TAREA AGENTE
- **Archivos:** `bus/supervisor.py`, `tests/test_supervisor.py`
- **Accion:** Endurecer
- **Descripcion:** Aplicar solo el fix que la instrumentacion confirme. La logica debe seguir en `requeue_ticket()`/`run_once()`, con estados terminales fail-closed y sin mover la autoridad a otro modulo. Si el problema resulta ser liveness, lock stale, fallo del launcher o doble requeue por `CHANGES` repetido, corregir ese punto concreto sin agregar features no diagnosticadas.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Un `CHANGES` nuevo relanza Builder automaticamente una sola vez; un segundo `CHANGES` repetido no duplica relanzado ni incrementa el round indebidamente; estados terminales no requeuean Builder; el watermark persistido evita procesar dos veces el mismo antecedente.
- **Si falla:** Mantener solo el guard minimo que deje de reactivar Builder en estados terminales y posponer el resto a un ticket posterior.

### Fase 2: smoke path reactivo estable
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_supervisor.py`
- **Accion:** Anadir cobertura
- **Descripcion:** Cubrir el flujo `ticket_supervisor.py --reactive`/`run_reactive()` con mocks y `tmp_path`, verificando que el supervisor bootstrappea, detecta actividad, relanza Builder y sigue iterando despues del relanzado hasta que vence el timeout/idle timeout, sin depender de subprocess real ni de terminales interactivas.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** El smoke test reactivo demuestra que el loop mantiene el polling despues del relanzado, que no sale inmediatamente tras el requeue, y que respeta el timeout/idle timeout.
- **Si falla:** Conservar la cobertura de `run_once()` y limitar el smoke a la deteccion de requeue.

## Files Likely Touched
- `bus/supervisor.py`
- `tests/test_supervisor.py`

## Calidad
- `python -m pytest tests/test_supervisor.py -q`
- `python scripts/ticket_supervisor.py --reactive --timeout 1`
- `python scripts/run_pytest_safe.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- La instrumentacion permite distinguir de forma verificable entre `skipped_alive`, `launcher_failed`, `timeout` y `success`.
- Un `CHANGES` nuevo en el bus relanza Builder automaticamente una sola vez.
- Un segundo `CHANGES` repetido no provoca doble relanzado ni corrompe `loop_current_round`.
- Los estados terminales siguen fallando cerrado.
- El modo `--reactive` permanece vivo despues del relanzado.
- La validacion canonica y la suite safe siguen pasando.
