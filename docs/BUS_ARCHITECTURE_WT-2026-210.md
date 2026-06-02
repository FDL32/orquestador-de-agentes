# BUS_ARCHITECTURE_WT-2026-210

Alias: Audit Bus V2 / Architecture Audit
Auditoria realizada: 2026-06-02 (sesion activa)
Validacion: externa al loop Manager/Builder/Supervisor
Estado: completed
Cierre documental: contrato entregado y sustituido por WT-2026-211

## Reglas de trabajo

- No usar el loop Manager/Builder/Supervisor como unica validacion del redisenio.
- No ejecutar recuperaciones ni closeout real mientras se captura evidencia.
- No escribir runtime experimental en el workspace vivo.
- Usar rama del motor y workspace sacrificial para cualquier spike que cambie eventos, locks o proyecciones.

---

## 1. Linea temporal verificada -- WT-2026-205

Fuente: `z_scripts/.agent/runtime/events/events.jsonl`.
VERIFICADO EN BUS seq=540-547.

| seq | timestamp (UTC) | actor | event_type | payload resumido | Proceso emisor real |
|-----|-----------------|-------|------------|------------------|---------------------|
| 540 | 10:26:21 | SUPERVISOR | STATE_CHANGED | READY_TO_CLOSE -> COMPLETED (WT-2026-204) | supervisor reactivo |
| 541 | 10:26:21 | SUPERVISOR | SUPERVISOR_CLOSED | source: manager-approve (WT-2026-204) | supervisor reactivo |
| 542 | 11:37:23 | SUPERVISOR | STATE_CHANGED | BOOTSTRAP -> IN_PROGRESS (source: bootstrap) | agent_controller.py --bootstrap-ticket |
| 543 | 11:46:23 | BUILDER | BUILDER_EXIT | source: mark-ready | agent_controller.py --mark-ready |
| 544 | 11:46:23 | BUILDER | STATE_CHANGED | IN_PROGRESS -> READY_FOR_REVIEW (source: mark-ready) | agent_controller.py --mark-ready |
| 545 | 11:46:23 | SUPERVISOR | STATE_CHANGED | IN_PROGRESS -> READY_FOR_REVIEW (source: mark-ready) | agent_controller.py --mark-ready (*) |
| 546 | 11:46:23 | MANAGER | REVIEW_DECISION | decision: CHANGES, stdout_tail: "[packaging: empty diff]" | manager_review_bridge.py (detached) |
| 547 | ~15:00 | SUPERVISOR | BUILDER_RELAUNCH_ATTEMPTED | outcome: builder_launch_unverified, trigger_seq: 546, verify_signal: none | supervisor reactivo (bootstrap) |

(*) seq=545: aunque actor="SUPERVISOR", source="mark-ready" revela que fue emitido por agent_controller.py
dentro de --mark-ready, no por el supervisor reactivo. El supervisor reactivo habia muerto por idle
timeout: Builder duro 540s; idle timeout = 300s.
VERIFICADO EN CODIGO agent_controller.py:_handle_mark_ready (lineas 641-664).

Fallos encadenados en esta secuencia:
1. Supervisor reactivo muerto por idle timeout (Builder > 300s sin eventos intermedios).
2. --mark-ready salio con codigo 1 (scope gate: observations.jsonl fuera de scope en working tree).
3. A pesar del codigo 1, los eventos 543-545 se emitieron igualmente (emit-before-gate).
4. Manager bridge (detached, sobrevivio al supervisor) emitio CHANGES con diff vacio (seq=546).
5. Bootstrap del supervisor (relanzado manualmente) encontro el trigger CHANGES en seq=546 pero
   TURN.md decia MANAGER/REVIEW_WORK; launcher leyo MANAGER -> no lanzo Builder -> builder_launch_unverified.

Estado actual del runtime (VERIFICADO EN ARTEFACTO 2026-06-02 16:00 UTC):
- supervisor_state.json: active_ticket=WT-2026-205, last_processed_sequence=547
- builder_lock.txt: ticket_id=WT-2026-205, role=BUILDER
- manager_bridge_state.json: last_ticket_id=WT-2026-205, last_ticket_state=READY_FOR_REVIEW
- bridge_checkpoint.json: last_processed_sequence=546
- circuit_breaker.json: last_ticket=WT-2026-205, state=CLOSED
- STATE.md: ACTIVE_TICKET=WT-2026-210 (documental ya avanzado a nuevo ticket)
- events.jsonl: ultimo evento seq=547, ticket=WT-2026-205

Drift confirmado: STATE.md (documental) en WT-2026-210; todo el runtime en WT-2026-205.

---

## 2. Diagrama de transicion de estados

Fuente canonica: bus/state_machine.py:StateMachine.derive_state_from_events()
VERIFICADO EN CODIGO bus/state_machine.py:44-82.

NOTA CRITICA: state_machine.py ES UN DERIVADOR DE LECTURA, no un guard del write-path.
derive_state_from_events() recorre eventos en orden inverso y devuelve el estado actual.
No existe validate_transition(), can_transition() ni ninguna barrera en el camino de escritura.
Cualquier proceso puede emitir STATE_CHANGED sin que la state machine lo valide.

Transiciones canonicas observadas en el bus:

```
BOOTSTRAP -----(STATE_CHANGED: bootstrap)-----------> IN_PROGRESS
IN_PROGRESS ---(BUILDER_EXIT + STATE_CHANGED: mark-ready)--> READY_FOR_REVIEW
READY_FOR_REVIEW --(REVIEW_DECISION: approve)-------> READY_TO_CLOSE
READY_FOR_REVIEW --(REVIEW_DECISION: changes)-------> [requeue: nuevo IN_PROGRESS]
READY_FOR_REVIEW --(REVIEW_DECISION: inspect)-------> HUMAN_GATE
READY_TO_CLOSE ---(CLOSE_CONFIRMED + STATE_CHANGED)-> COMPLETED
COMPLETED -------(SUPERVISOR_CLOSED)----------------> CLOSED
```

Transiciones ambiguas o redundantes detectadas:
- IN_PROGRESS -> READY_FOR_REVIEW se emite DOS VECES en el mismo ciclo: una por actor=BUILDER
  (seq=544) y otra por actor=SUPERVISOR desde el mismo proceso --mark-ready (seq=545).
  Redundancia sin valor; confunde la lectura del actor real.
  VERIFICADO EN BUS seq=544-545 + VERIFICADO EN CODIGO agent_controller.py:641-664.
- REVIEW_DECISION=CHANGES no emite STATE_CHANGED; el estado derivado por state_machine.py
  sigue siendo READY_FOR_REVIEW hasta que el supervisor emite un nuevo IN_PROGRESS.
  Durante ese intervalo el estado logico y el estado derivado difieren.

| Evento | Tipo semantico | Emisor real | Actor declarado |
|--------|---------------|-------------|-----------------|
| STATE_CHANGED -> IN_PROGRESS (bootstrap) | Comando | agent_controller.py | SUPERVISOR |
| BUILDER_EXIT | Hecho | agent_controller.py (--mark-ready) | BUILDER |
| STATE_CHANGED -> READY_FOR_REVIEW (x1) | Hecho | agent_controller.py (--mark-ready) | BUILDER |
| STATE_CHANGED -> READY_FOR_REVIEW (x2) | Redundante | agent_controller.py (--mark-ready) | SUPERVISOR (incorrecto) |
| REVIEW_DECISION | Decision | manager_review_bridge.py | MANAGER |
| STATE_CHANGED -> READY_TO_CLOSE | Hecho | agent_controller.py (--manager-approve) | SUPERVISOR |
| SUPERVISOR_CLOSED | Hecho | supervisor.py | SUPERVISOR |
| BUILDER_RELAUNCH_ATTEMPTED | Watchdog | supervisor.py | SUPERVISOR |
| HANDOFF_BLOCKED | Guardia | supervisor.py | SUPERVISOR |
| RELAUNCH_SUPPRESSED | Guardia | supervisor.py | SUPERVISOR |

---

## 3. Autoridad de escritura por proceso

VERIFICADO EN CODIGO: agent_controller.py, supervisor.py, bus/review_bridge.py, session_tracker.py.

| Proceso | Escribe bus | Escribe proyecciones | Escribe locks/cache | Observaciones |
|---------|-------------|---------------------|---------------------|---------------|
| agent_controller --bootstrap-ticket | SI: STATE_CHANGED -> IN_PROGRESS | SI: TURN.md, STATE.md, execution_log.md | NO | Unica ruta de arranque |
| agent_controller --mark-ready | SI: BUILDER_EXIT, STATE_CHANGED(x2) | SI: TURN.md, execution_log.md | NO | Emite actor=SUPERVISOR en segundo STATE_CHANGED; origen confuso |
| agent_controller --manager-approve | SI: STATE_CHANGED -> READY_TO_CLOSE | SI: TURN.md, STATE.md, execution_log.md | NO | Usa _materialize_state_transition |
| agent_controller --validate | NO directo | SI: regenera TURN.md si stale | NO | should_overwrite_turn() puede sobreescribir |
| supervisor run_reactive/run_once | SI: STATE_CHANGED, SUPERVISOR_CLOSED, BUILDER_RELAUNCH_ATTEMPTED, HANDOFF_BLOCKED, RELAUNCH_SUPPRESSED | SI: TURN.md (via _materialize_turn_blockers) | SI: supervisor_lock.txt | _materialize_turn_blockers solo anade seccion Blockers; no flipea ROL de MANAGER a BUILDER |
| supervisor _bootstrap_requeue_if_needed | SI: via requeue_ticket | SI: TURN.md (via _materialize_turn_blockers) | NO | Mismo gap: no flipea ROL en TURN.md; launcher lee MANAGER -> no lanza Builder |
| manager_review_bridge | SI: REVIEW_DECISION | SI: manager_feedback_*.md | SI: manager_bridge_state.json, bridge_checkpoint.json | Proceso detached; sobrevive al supervisor |
| launch_agent_terminals.ps1 | NO directo | NO escribe; SI lee TURN.md para decidir | SI: elimina supervisor_lock.txt en arranque | Lee TURN.md como autoridad; si TURN stale -> decision equivocada |
| session_tracker.py save_session | NO | NO directo | SI: .session_state.json | Fix en WT-2026-205: lazy collab_dir. Antes escribia al motor root. |
| hooks (.agent/hooks/) | NO | NO | NO | Verificado por grep: no importan session_tracker ni emiten al bus |
| session_closeout.py | NO | SI: archiva collaboration, execution_log, event_bus | SI: session_close_report.md | Bloqueado en Modelo B: prepush_check sale con exit 1 (TP-01 roto en WT-2026-205) |

---

## 4. Contrato de invariantes duras

| Invariante | Estado | Evidencia |
|------------|--------|-----------|
| Un solo proceso decide el estado canonico del ticket | ROTA | agent_controller, supervisor y bridge escriben STATE_CHANGED de forma independiente |
| actor=SUPERVISOR en el bus significa supervisor reactivo | ROTA | --mark-ready emite actor=SUPERVISOR desde agent_controller.py |
| REVIEW_DECISION=CHANGES tiene consumidor durable | ROTA | Si supervisor muere antes de procesar CHANGES, nadie requeue hasta bootstrap manual |
| TURN.md siempre refleja el estado canonico del bus | ROTA | Supervisor muere mid-transition -> TURN stale indefinidamente (TURN drift) |
| Builder activo == builder_lock.txt fresco + sin BUILDER_EXIT posterior | DEBIL | Lock puede quedar stale; idle timeout mata supervisor antes de que Builder termine |
| session_closeout.py puede cerrar un ticket en Modelo B | ROTA | prepush_check falla estructuralmente; exit 1 antes de archivar |
| El runtime del workspace no mezcla tickets activos | ROTA | STATE.md en WT-2026-210, todo el runtime en WT-2026-205; drift confirmado 2026-06-02 |
| Cerrar un ticket limpia el runtime antes de abrir el siguiente | NO EXISTE | No hay protocolo de forced close; gap arquitectonico confirmado |

Invariantes que si se sostienen:
- events.jsonl es append-only y la secuencia global es monotona.
- state_machine.py deriva el estado correcto si recibe los eventos completos del ticket.
- supervisor_lock.txt se elimina en preflight del launcher (previene deadlock).
- circuit_breaker.json limita reintento infinito en loops rotos.

---

## 5. Write-paths actuales sin orquestador unico

state_machine.py debe tratarse como derivador de lectura, no como guard del write-path.
VERIFICADO EN CODIGO bus/state_machine.py:44-82.

| Ruta | Superficie afectada | Riesgo confirmado | Evidencia |
|------|---------------------|-------------------|-----------|
| agent_controller.py:641-664 (_handle_mark_ready) | bus STATE_CHANGED (actor=SUPERVISOR), TURN.md | actor confuso; supervisor parece vivo cuando puede estar muerto | VERIFICADO EN CODIGO |
| agent_controller.py:3668-3700 (_materialize_state_transition) | bus STATE_CHANGED, execution_log.md, TURN.md, STATE.md | Correcto en intension; problema es que no es la UNICA ruta | VERIFICADO EN CODIGO |
| supervisor.py:2241-2246 (run_once) | TURN.md via _materialize_turn_blockers | Solo anade seccion Blockers; no flipea ROL de MANAGER a BUILDER antes del launcher | VERIFICADO EN CODIGO + BUS seq=547 |
| supervisor.py:932-937 (_bootstrap_requeue_if_needed) | TURN.md via _materialize_turn_blockers, bus via requeue_ticket | Mismo gap: launcher lee MANAGER en TURN.md y no lanza Builder | VERIFICADO EN BUS seq=547 + launcher_last.log |
| launch_agent_terminals.ps1 | Decision de lanzar o no Builder | Lee TURN.md stale -> no lanza Builder aunque bus diga CHANGES | VERIFICADO EN ARTEFACTO launcher_last.log |
| agent_controller.py:2267 (should_overwrite_turn) | TURN.md | Puede sobreescribir TURN.md en cualquier --validate con force_reset | VERIFICADO EN CODIGO |

---

## 6. Propuesta de simplificacion

### Problema raiz

Cinco procesos pueden cambiar estado o proyecciones de forma independiente: agent_controller,
supervisor, bridge, launcher y session_closeout. Cada uno tiene su logica de "cuando escribo que".
El resultado es drift estructural en cualquier escenario donde un proceso muere entre escrituras.

### Principio

Un solo proceso debe ser la autoridad del write-path. Los demas emiten peticiones o hechos al bus.
Solo el orquestador materializa proyecciones (TURN.md, STATE.md, execution_log.md).

No hace falta reescribir el bus. Hace falta una barrera: ninguna proyeccion se escribe fuera del
orquestador. state_machine.py ya tiene la logica de derivacion; convertirlo en guard de escritura
es el cambio minimo.

### Arquitectura objetivo minima

```
Proceso emisor              Emite al bus               Orquestador durable         Proyecciones
--------------------        ------------------         ---------------------       -------------------
Builder (via controller)    BUILDER_EXIT           -->                        --> TURN.md (ROL=MANAGER)
agent_controller            READY_FOR_REVIEW       --> Supervisor durable     --> STATE.md
Manager bridge              REVIEW_DECISION        --> (unico writer)         --> execution_log.md
Cualquier proceso           peticion STATE_CHANGED --> valida + materializa   --> locks/cache
```

---

## 7. Opciones de arquitectura

### Opcion A: Orquestador unico sobre flujo actual

Centralizar write de proyecciones en supervisor.py.
agent_controller.py solo emite eventos al bus; no escribe TURN.md, STATE.md ni execution_log.md directamente.
Supervisor lee el bus y materializa proyecciones tras cada evento relevante.

Ventaja: sin migracion de esquema de eventos. Cambio localizado.
Riesgo: supervisor sigue sujeto a ciclo de vida finito; idle timeout sigue siendo un riesgo parcial.

### Opcion B: Supervisor Durable

Proceso persistente que nunca muere por idle timeout.
Procesa REVIEW_DECISION=CHANGES aunque el Builder tarde horas.
Es el unico writer de proyecciones.

Ventaja: elimina la clase de bugs "supervisor murio entre dos escrituras".
Complejidad: requiere gestion de ciclo de vida del daemon (restart, healthcheck).

### Opcion C: Proyecciones derivadas del bus

TURN.md, STATE.md y execution_log.md no se persisten; se regeneran desde events.jsonl bajo demanda.
La unica fuente de verdad es el bus.

Ventaja: elimina el drift entre bus y proyecciones de forma estructural.
Complejidad: todos los lectores (launcher, controller) deben leer el bus en vez de markdown.
Migracion considerable; vision de largo plazo.

### Comparativa

| Criterio | Opcion A | Opcion B (Supervisor Durable) | Opcion C (Proyecciones derivadas) |
|----------|----------|-------------------------------|-----------------------------------|
| Migracion | Minima | Media (daemon lifecycle) | Alta (cambio de contrato de lectura) |
| Elimina drift TURN/bus | Parcial (si supervisor vive) | SI | SI |
| Elimina idle timeout death | NO | SI | N/A |
| Elimina actor=SUPERVISOR falso | SI (con refactor) | SI | SI |
| Requiere cambio de esquema eventos | NO | NO | NO |
| Ticket hijo recomendado | Primero | Segundo | Vision largo plazo |

---

## 8. Estrategia de validacion externa al loop

Cualquier cambio derivado de esta auditoria debe validarse mediante:

1. Tests unitarios directos: `uv run pytest tests/test_supervisor.py tests/test_agent_controller.py -q`
2. Lectura manual del bus tras cada spike.
3. Revision humana del artefacto antes de abrir tickets hijos.
4. No usar "Manager aprobo" ni "Builder completo con exito" como criterio de verdad para cambios
   que afectan al propio Manager, Builder o Supervisor.

---

## 9. Workspace sacrificial

El workspace vivo (`z_scripts/`) tiene el bus y runtime del ticket activo.

Para spikes que necesiten escribir eventos, locks o proyecciones:
```powershell
# Copiar workspace
cp -r "C:\Users\fdl\Proyectos_Python\z_scripts" "C:\Users\fdl\Proyectos_Python\z_scripts_spike_210"
$env:AGENT_PROJECT_ROOT = 'C:\Users\fdl\Proyectos_Python\z_scripts_spike_210'

# Rama del motor para codigo experimental
git -C orquestador_de_agentes switch -c wt-2026-210-bus-spike
```

Baseline de recuperacion documentado: `z_scripts - copia (2)` (referencia en memoria del proyecto).

---

## 10. Documentos canonicos al arrancar un ticket

Auditoria de que documentos se leen/escriben al arrancar un ticket nuevo.

### Lectura en arranque

| Superficie | Leida por | Proposito | Problema si stale |
|------------|-----------|-----------|-------------------|
| `work_plan.md` | launcher, controller | Ticket ID, Files Likely Touched, estado | Lanza agente para ticket equivocado |
| `STATE.md` | controller (--validate) | Ticket activo, estado documental | Confunde ticket activo si runtime y documental difieren |
| `TURN.md` | launcher | Decide si lanzar Builder o Manager | Si stale -> no lanza Builder aunque bus diga CHANGES |
| `supervisor_state.json` | supervisor (bootstrap) | last_processed_sequence, active_ticket | Si apunta a ticket viejo -> requeue trigger mal procesado |
| `builder_lock.txt` | supervisor (_builder_alive) | Liveness del Builder | Si stale -> supervisor cree que Builder vive y no relanza |
| `events.jsonl` | supervisor, controller, bridge | Estado canonico del ticket | Es la autoridad; mezclar motor/workspace -> analisis incorrecto |
| `bridge_checkpoint.json` | manager_review_bridge | Secuencia ya procesada | Si desincronizado -> bridge re-procesa o salta eventos |
| `manager_bridge_state.json` | supervisor (watchdog) | Detectar bridge stale | Si apunta a ticket viejo -> watchdog puede relanzar bridge innecesariamente |

### Escritura en arranque

| Superficie | Escrita por | Momento |
|------------|-------------|---------|
| `supervisor_lock.txt` | launcher (elimina) + supervisor (crea) | Preflight |
| `builder_lock.txt` | launcher (elimina en preflight) | Preflight |
| `events.jsonl` | agent_controller (--bootstrap-ticket) | Al lanzar Builder |
| `TURN.md` | agent_controller (--bootstrap-ticket) | Al lanzar Builder |
| `execution_log.md` | agent_controller (--bootstrap-ticket) | Al lanzar Builder |

### Gap critico: ticket anterior sin cierre limpio

Si el ticket anterior quedo en CHANGES sin requeue (como WT-2026-205 hoy), abrir un nuevo
ticket documental crea un drift que ningun proceso resuelve automaticamente:

- supervisor_state.json: active_ticket del anterior.
- builder_lock.txt: ticket_id del anterior.
- events.jsonl: ultimo evento del anterior sin cierre.
- work_plan.md y STATE.md: ya apuntan al nuevo.

No existe un protocolo de forced close. Este gap debe generar un ticket hijo.

---

## 11. Tickets hijos propuestos

| Ticket | Scope | Depende de | Criterio de aceptacion |
|--------|-------|------------|------------------------|
| WT-2026-211 | Centralizar write-path: --mark-ready solo emite bus events; supervisor es unico writer de TURN.md | WT-2026-210 | --mark-ready no escribe TURN.md directamente; test verifica |
| WT-2026-212 | Supervisor durable para CHANGES: consumidor que garantiza requeue aunque supervisor reactivo muera | WT-2026-211 | REVIEW_DECISION=CHANGES produce requeue dentro de N segundos sin intervencion manual |
| WT-2026-213 | Eliminar STATE_CHANGED doble en mark-ready: un solo evento con actor=BUILDER | WT-2026-211 | Un solo STATE_CHANGED -> READY_FOR_REVIEW por ciclo; tests pasan |
| WT-2026-214 | Protocolo de forced close: al arrancar nuevo ticket, cerrar runtime del anterior en el bus | WT-2026-210 | Arrancar WT-N+1 con runtime de WT-N pendiente genera cierre explicito en bus |
| WT-2026-215 | Gates Modelo B: redefinir prepush_check.py para workspace no-repo + motor portable | WT-2026-210 | prepush_check sale codigo 0 desde z_scripts; session_closeout completa |
| WT-2026-216 | Launcher lee bus en vez de TURN.md para decidir que agente lanzar | WT-2026-211 | TURN drift no impide relaunch correcto; tests de launcher con TURN stale |
