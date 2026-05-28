# Work Plan - WP-2026-160

## Metadata
- **ID:** WP-2026-160
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Restart supervisor on Builder relaunch
- **Asignado a:** Builder

## Objetivo
Hacer que el camino `-ResumeBuilder` del launcher garantice que el supervisor en memoria sea reemplazado por uno fresco antes de abrir el nuevo Builder, para cerrar el anti-patron de procesos de larga vida con codigo viejo en disco.

## Contexto
- AP-13 ya documenta el problema: un proceso supervisor de larga vida puede seguir ejecutando codigo viejo despues de un hot-patch si no se reinicia.
- Hoy `scripts/launch_agent_terminals.ps1 -ResumeBuilder` se usa en el camino de requeue, pero no deja explicitado ni verificado que el supervisor que queda activo sea uno fresco.
- El objetivo de este ticket es arreglar la orquestacion de arranque sin inventar un daemon nuevo: el launcher coordina el reemplazo y el supervisor viejo sale limpiamente para liberar el lock.
- El fix debe mantener el flujo bus-first: el launcher coordina, el supervisor sigue siendo un consumidor reactivo, y Builder no intenta repararse a si mismo.

## Decision Arquitectonica
- Opcion elegida: el launcher reinicia o reemplaza el supervisor al relanzar Builder, y el supervisor viejo coopera saliendo limpiamente tras completar el handoff.
- La comprobacion de frescura vive en `scripts/launch_agent_terminals.ps1`; `bus/supervisor.py` solo aporta la salida cooperativa para no dejar un proceso viejo con autoridad activa.
- `-ResumeBuilder` debe tratar `supervisor_lock.txt` como artefacto del ciclo previo: se elimina de forma incondicional antes de relanzar el supervisor fresco.
- El launcher debe dejar trazabilidad observable del reinicio del supervisor para que el Manager pueda decidir sin inferir; si no puede garantizar frescura, debe fallar cerrado con stderr + exit code no cero.
- El reinicio del supervisor debe usar el mismo patron de arranque normal del launcher, no un camino ad hoc distinto.

## Non-goals
- No crear un daemon nuevo.
- No mover la responsabilidad de requeue al supervisor.
- No introducir polling continuo ni backoff de reintentos.
- No cambiar el contrato de `--mark-ready`.

## Fases

### Fase 0: instrumentacion del reinicio
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/launch_agent_terminals.ps1`, `bus/supervisor.py`, `tests/test_launch_agent_terminals_script.py`, `tests/test_supervisor.py`
- **Accion:** Instrumentar
- **Descripcion:** Aislar el camino de refresco del supervisor con un helper observable, por ejemplo `Restart-ProjectSupervisor` o `Ensure-FreshSupervisor`, y completar la pieza cooperativa en `bus/supervisor.py` para que el proceso viejo pueda salir limpiamente tras el handoff. Ese camino debe dejar claro si el supervisor se limpio, si ya estaba fresco o si el reinicio fallo. La salida del launcher debe permitir distinguir el estado sin leer la ventana manualmente.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Un test de contenido puede afirmar que `-ResumeBuilder` tiene una rama explicita para dejar el supervisor fresco antes de abrir Builder y que el supervisor viejo emite/sigue la salida cooperativa tras el handoff.
- **Si falla:** Mantener la instrumentacion minima como mensaje/log visible y posponer la automatizacion total.

### Fase 1: fix dirigido de reinicio
- **Tipo:** TAREA AGENTE
- **Archivos:** `scripts/launch_agent_terminals.ps1`, `bus/supervisor.py`, `tests/test_launch_agent_terminals_script.py`, `tests/test_supervisor.py`
- **Accion:** Endurecer
- **Descripcion:** Implementar el camino de `-ResumeBuilder` para que elimine `supervisor_lock.txt` de forma incondicional, arranque un supervisor fresco usando el mismo patron normal del launcher y espere a que el supervisor viejo haya salido limpiamente antes de abrir Builder. Si no puede garantizar frescura, el launcher debe fallar cerrado, escribir un mensaje especifico a stderr y no abrir Builder sobre un proceso viejo.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** En el flujo `ResumeBuilder`, el supervisor viejo no sobrevive como autoridad activa cuando Builder vuelve a entrar; el camino de relanzado deja trazabilidad observable del reinicio, usa el mismo patron de arranque normal del launcher y no abre Builder si el supervisor no pudo renovarse.
- **Si falla:** Mantener el guard minimo de no abrir Builder si el supervisor no puede verificarse como fresco, con stderr explicito y exit code no cero.

### Fase 2: smoke path de requeue con supervisor fresco
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_launch_agent_terminals_script.py`, `tests/test_supervisor.py`
- **Accion:** Anadir cobertura
- **Descripcion:** Cubrir el flujo de requeue que usa `-ResumeBuilder` con tests de contenido para el launcher y tests de unidad para el supervisor: el launcher debe mostrar la rama explicita de reinicio y el supervisor debe exponer la salida cooperativa tras el handoff. La cobertura debe demostrar que el camino de requeue no depende de un supervisor viejo persistiendo en memoria.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** La prueba deja claro que `-ResumeBuilder` prepara un supervisor fresco antes del Builder nuevo, que el supervisor viejo sale limpiamente y que el camino de cierre no se apoya en un proceso viejo.
- **Si falla:** Conservar la cobertura de la instrumentacion y limitar el smoke al orden supervisor->builder con fail-closed observable.

## Files Likely Touched
- `scripts/launch_agent_terminals.ps1`
- `bus/supervisor.py`
- `tests/test_launch_agent_terminals_script.py`
- `tests/test_supervisor.py`

## Calidad
- `python -m pytest tests/test_launch_agent_terminals_script.py -q`
- `python scripts/run_pytest_safe.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `-ResumeBuilder` deja explicitamente un supervisor fresco antes de abrir Builder.
- Un supervisor viejo no queda como autoridad activa despues del relanzado.
- El camino de reinicio es observable y falla cerrado si no puede garantizar frescura, con stderr explicito y exit code no cero.
- El supervisor viejo sale limpiamente tras el handoff y no mantiene el lock viejo como autoridad.
- La validacion canonica y la suite safe siguen pasando.
