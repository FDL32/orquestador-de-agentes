# Prompt: Auditoria del Bus y las Interacciones entre Agentes

> **Modo:** Solo lectura. No implantes nada. No reescribas archivos.
> No ejecutes comandos de recuperacion durante esta auditoria.
> Solo propones comandos; no los corres.
>
> Diagnostica el estado runtime del sistema multi-agente: bus de eventos, supervisor,
> Builder, Manager y las interacciones entre ellos. Identifica que fallo, que esta
> en drift y que se necesita para recuperar o arrancar limpiamente.

---

## Alcance obligatorio

Lee estos archivos antes de evaluar nada. No asumas estados; verifica en fuente real.

**Determina el ticket activo** desde `STATE.md` o `work_plan.md`. Si hay drift entre ambos, ese es ya un hallazgo.

### Preflight obligatorio

Antes de interpretar eventos, confirma estas tres cosas:

- `project_root` auditado: debe ser el workspace activo (`C:\Users\fdl\Proyectos_Python\z_scripts` en esta instalacion), no el motor.
- Bus leido: `.agent/runtime/events/events.jsonl` debe estar bajo el workspace activo.
- Ticket activo: extraelo de `STATE.md` y `work_plan.md`; si difieren, documenta el drift antes de seguir.

Si cualquiera de los tres puntos falla, no clasifiques patrones de fallo todavia: primero reporta que la auditoria esta mirando la raiz equivocada o un ticket ambiguo.

### Bus y estado del sistema

- `.agent/runtime/events/events.jsonl`: autoridad canonica; lee los ultimos 30-50 eventos o todos los del ticket activo
- `.agent/collaboration/STATE.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/execution_log.md`
- `.agent/collaboration/work_plan.md`

### Estado de procesos en disco

- `.agent/runtime/supervisor_lock.txt`
- `.agent/runtime/builder_lock.txt` (si existe)
- `.agent/runtime/supervisor_state.json` (si existe)
- `.agent/runtime/checkpoint/` (si existe)
- `.agent/runtime/logs/launcher_last.log` (si existe)
- `.agent/collaboration/manager_feedback_<ID>.md` (del ticket activo)

### Codigo fuente relevante

Para cada patron de fallo que identifiques, lee el codigo fuente real del modulo implicado antes de clasificar la severidad. Los nombres en los hallazgos deben estar `VERIFICADOS EN CODIGO`.

---

## Estado documental vs. estado operativo

**Esta distincion es critica. Confundirla produce falsos positivos y recuperaciones incorrectas.**

### Estado documental (plan-level)

Los archivos de colaboracion reflejan el estado del *plan*, no del bus:

| Archivo | Campo | Semantica |
|---|---|---|
| `work_plan.md` | `**Estado:** APPROVED` | El plan fue aprobado para que Builder lo ejecute. **No cambia** cuando el Builder empieza a trabajar ni cuando el Manager rechaza. |
| `STATE.md` | `STATUS: APPROVED` | Refleja la aprobacion documental del plan. **No es el estado operativo del ticket.** |
| `execution_log.md` | `**Estado:** READY_FOR_REVIEW` | Estado de progreso del log; actualizado por el controller, no por el bus. |

Estos archivos son **proyecciones documentales**. Que `STATUS: APPROVED` aparezca en `STATE.md` mientras el bus tiene `REVIEW_DECISION` con `decision: CHANGES` **no es drift**; es el comportamiento correcto. El plan sigue aprobado; lo que cambio es el estado operativo del ciclo.

### Estado operativo (bus-level)

El estado real del ticket lo define la ultima transicion `STATE_CHANGED` en `events.jsonl`. Es la autoridad canonica:

- `IN_PROGRESS`: Builder trabajando
- `READY_FOR_REVIEW`: Builder entrego, esperando Manager
- `READY_TO_CLOSE`: Manager aprobo
- `COMPLETED`: Supervisor cerro el ticket

`REVIEW_DECISION` con `decision: CHANGES` **no es un estado**: es una decision. El estado operativo sigue siendo `READY_FOR_REVIEW` mientras no haya un `STATE_CHANGED -> IN_PROGRESS` posterior (requeue). Usa siempre la formulacion "ultima decision pendiente: `REVIEW_DECISION=CHANGES` sin requeue posterior"; no lo describas como un estado del ticket.

### Que si es drift real

| Senal | Por que es drift |
|---|---|
| `TURN.md` dice `MANAGER / REVIEW_WORK` pero bus tiene `REVIEW_DECISION=CHANGES` sin requeue | TURN.md no fue actualizado tras la decision del Manager; el launcher leera el rol equivocado |
| `execution_log.md` dice `READY_FOR_REVIEW` pero bus tiene `IN_PROGRESS` | El log esta por delante del bus; indica un estado que el bus no reconoce |
| `STATE.md` `ACTIVE_TICKET` apunta a un ticket diferente al del ultimo `STATE_CHANGED` activo | El tracker documental y el bus estan desincronizados sobre que ticket es el activo |

**Regla practica:** antes de clasificar un campo de `STATE.md` o `work_plan.md` como drift, verifica si ese campo es documental (plan-level) u operativo (bus-level). Solo los campos operativos deben alinearse con `events.jsonl`.

---

## Checklist de salud del bus

Recorre item por item para el ticket activo.

### 1. Integridad de secuencia

Los `sequence_number` en `events.jsonl` son **globales** y compartidos por todos los tickets. No esperes contiguidad dentro de un ticket: los saltos entre eventos del mismo ticket son normales porque otros tickets intercalan sus propios eventos.

Lo que debes verificar:
- La secuencia global (todos los eventos) no tiene huecos numericos (si despues de seq=N aparece seq=N+2 sin N+1, un evento no se escribio).
- Los eventos del ticket activo estan **ordenados** (timestamps y sequence_number crecientes), aunque no contiguos.
- No hay eventos del ticket activo con `sequence_number` inferior al del ticket anterior (escritura en bus equivocado: motor root vs. workspace).

Formula rapida: `global_seq_gap = any(next.sequence_number != current.sequence_number + 1)` al recorrer todos los eventos en orden. En eventos filtrados por ticket, comprueba orden, no contiguedad.

### 2. Estado canonico vs. proyeccion documental

El ultimo `STATE_CHANGED` en `events.jsonl` es la autoridad. Comprueba que `TURN.md` y `execution_log.md` no contradicen ese estado operativo (ver tabla de drift real en la seccion anterior).

### 3. Ciclo del ticket completo

Verifica que los eventos del ticket activo siguen una secuencia coherente:
`IN_PROGRESS -> BUILDER_EXIT -> READY_FOR_REVIEW -> REVIEW_DECISION -> [requeue o cierre]`

Detecta:
- Ticket con `IN_PROGRESS` pero sin `BUILDER_EXIT` posterior (Builder crasheo o fue interrumpido)
- `READY_FOR_REVIEW` emitido pero `REVIEW_DECISION` ausente (Manager bridge no corrio o murio)
- `REVIEW_DECISION=CHANGES` sin `IN_PROGRESS` posterior ni `HANDOFF_BLOCKED` (supervisor murio antes de procesar el trigger)
- `SUPERVISOR_CLOSED` sin `STATE_CHANGED -> COMPLETED` previo (cierre incompleto)

### 4. Actor real de cada evento

`actor="SUPERVISOR"` en el bus puede provenir de dos procesos distintos:
- El supervisor reactivo (`ticket_supervisor.py --reactive`): proceso de larga vida
- `agent_controller.py --mark-ready`: proceso de corta vida que emite un `STATE_CHANGED` con `actor="SUPERVISOR"` durante el handoff (VERIFICADO EN CODIGO `agent_controller.py:_handle_mark_ready`)

Si el `STATE_CHANGED -> READY_FOR_REVIEW` con `actor=SUPERVISOR` tiene `source: mark-ready` en el payload, fue emitido por el controller, **no por el supervisor reactivo**. El supervisor puede haber muerto antes de que ese evento se emitiera.

Regla de atribucion: cuando existan ambos, prioriza `payload.source` sobre `actor` para inferir que proceso emitio el evento. `actor` describe el rol semantico; `payload.source` suele describir el camino de ejecucion real.

Para distinguirlos: compara el timestamp del evento con el `started_at` del `supervisor_lock.txt`. Si el lock no existe o su PID esta muerto, el supervisor ya no estaba vivo en ese momento.

### 5. Supervisor: idle timeout vs. duracion del Builder

Calcula el intervalo entre `STATE_CHANGED -> IN_PROGRESS` (arranque del Builder) y `BUILDER_EXIT`. Si supera **300 segundos** (idle timeout por defecto), el supervisor probablemente murio durante la ejecucion del Builder.

El supervisor no actualiza `last_activity` mientras el Builder trabaja en silencio (sin emitir eventos). Tras 300 s sin eventos nuevos, `_should_stop_run_reactive()` devuelve `True` y el proceso sale limpiamente.

**Bug estructural conocido:** `_should_stop_run_reactive()` no consulta `_builder_alive()` antes de aplicar el idle timeout. Un Builder activo no impide la salida del supervisor. Hasta que se corrija, usa `--timeout 900` (o superior) en el supervisor para mitigarlo.

Senales confirmatorias de idle timeout:
- `supervisor_lock.txt` ausente en el workspace (supervisor salio limpiamente)
- No hay `SUPERVISOR_RESTARTED` entre `IN_PROGRESS` y `BUILDER_EXIT`
- El `STATE_CHANGED -> READY_FOR_REVIEW` con `actor=SUPERVISOR` tiene `source: mark-ready`

Formula rapida: idle timeout probable si `timestamp(BUILDER_EXIT) - timestamp(STATE_CHANGED -> IN_PROGRESS) > 300s`, no hay supervisor vivo y no existe `SUPERVISOR_RESTARTED` entre ambos eventos.

### 6. CHANGES: payload de blockers

Si el bus tiene un `REVIEW_DECISION` con `decision: CHANGES`, verifica el payload:
- Tiene clave `blockers` con contenido no vacio? Si no, `_materialize_turn_blockers` emitira `HANDOFF_BLOCKED` en el proximo arranque del supervisor, suprimiendo el requeue del Builder.
- `TURN.md` refleja los blockers accionables? Si solo dice "Manager requested changes" sin detalle, el Builder queda ciego en el ciclo de CHANGES.
- Hay un `HANDOFF_BLOCKED` en el bus despues del CHANGES trigger? Ese evento suprime el relaunch del Builder en `run_once` y en `_bootstrap_requeue_if_needed`.

Formula rapida: requeue perdido si existe `REVIEW_DECISION=CHANGES` y no existe `STATE_CHANGED -> IN_PROGRESS`, `BUILDER_RELAUNCH_ATTEMPTED`, `HANDOFF_BLOCKED` ni `RELAUNCH_SUPPRESSED` posterior para el mismo ticket.

### 7. RELAUNCH_SUPPRESSED

Busca eventos `RELAUNCH_SUPPRESSED` en el bus. Cada uno indica un requeue que el supervisor decidio no ejecutar. Verifica el `payload.reason`:
- `handoff_blocked`: hay un `HANDOFF_BLOCKED` previo que bloquea (puede ser legitimo o un falso positivo por payload vacio)
- Otros: documenta el motivo exacto

### 8. Packaging del review packet

Si el ticket llego a `READY_FOR_REVIEW` pero el Manager rechazo con `REVIEW_DECISION=CHANGES` y `manager_feedback_*.md` dice "empty review diff detected":
- El review packet estaba ausente o vacio antes de que el Manager bridge lo procesara
- Causa posible: el scope gate o el evidence gate dispararon y `--mark-ready` salio con codigo 1 sin crear el packet; sin embargo los eventos de estado se emitieron igualmente
- Causa posible alternativa: el working tree estaba limpio porque el commit se hizo antes de `--mark-ready` y no habia diff en staging

No asumas la causa. Verifica: existe el review packet en `.agent/runtime/review_packets/`? Tiene diff verificable? Que indica el `manager_feedback_*.md` exactamente?

El commit puede ser correcto. El problema puede ser exclusivamente de packaging.

### 9. Estado del lock del supervisor

| Condicion | Interpretacion |
|---|---|
| `supervisor_lock.txt` existe, PID vivo | Supervisor activo; no relanzar |
| `supervisor_lock.txt` existe, PID muerto | Lock huerfano; supervisor crasheo; el launcher lo eliminara en el proximo arranque |
| `supervisor_lock.txt` ausente | Supervisor salio limpiamente (timeout o ciclo completado) |

Comprueba que el `supervisor_lock.txt` este en el workspace (`.agent/runtime/` de z_scripts), no en el motor root. Si esta en el motor, el supervisor arranko con `project_root` incorrecto porque `AGENT_PROJECT_ROOT` no estaba seteado al importar `ticket_supervisor.py`.

### 10. TURN.md autosuficiente para el proximo ciclo

Si hay una decision `REVIEW_DECISION=CHANGES` pendiente de requeue:
- `TURN.md` tiene los blockers concretos del Manager materializados?
- El rol en `TURN.md` es `BUILDER` y la accion es `IMPLEMENT`?
- Si `TURN.md` dice `MANAGER / REVIEW_WORK` y el bus tiene `REVIEW_DECISION=CHANGES` -> drift confirmado; el launcher leera TURN y no lanzara Builder

---

## Verificaciones adicionales

### Requeue claims

Comprueba `.agent/runtime/requeue_claims/` si existe. Un claim stale (archivo viejo) puede hacer que el supervisor descarte un requeue legitimo por creer que otro proceso ya lo reclamo.

### Bridge checkpoint

Lee `.agent/runtime/bridge_checkpoint.json`. Si apunta a un ticket diferente al activo o a una secuencia anterior al ultimo `REVIEW_DECISION`, el Manager bridge puede estar desfasado.

### Escrituras legacy al motor root

Si `orquestador_de_agentes/.agent/collaboration/.session_state.json` tiene mtime reciente (mismo dia que la sesion activa), hay un proceso escribiendo en el motor en lugar del workspace. Ver `session_tracker.py:_collab_dir()`.

---

## Patrones de fallo conocidos

Identifica si el estado actual encaja en alguno de estos patrones documentados.

| Patron | Senal en el bus | Causa raiz | Recuperacion propuesta |
|---|---|---|---|
| **Idle timeout silencioso** | Builder > 5 min, `supervisor_lock` ausente, `REVIEW_DECISION=CHANGES` sin requeue | `_should_stop_run_reactive()` no consulta `_builder_alive()` antes de aplicar idle timeout | Relaunch con `-LaunchBuilder 0` y `--timeout 900` |
| **Empty diff CHANGES** | `manager_feedback_*.md`: "empty review diff detected"; review packet ausente o vacio | `--mark-ready` salio antes de empaquetar (scope/evidence gate) o working tree limpio antes de `--mark-ready` | Verificar causa exacta; si el commit es correcto, commitear artefactos pendientes y relanzar |
| **TURN drift en CHANGES** | Bus: `REVIEW_DECISION=CHANGES`; `TURN.md`: MANAGER/REVIEW_WORK | Supervisor murio mid-transition antes de actualizar TURN | Corregir TURN.md manualmente (ver comandos en recuperacion) o relanzar con supervisor fresco |
| **HANDOFF_BLOCKED falso positivo** | `HANDOFF_BLOCKED` + `reason: empty_blockers` | `REVIEW_DECISION` sin clave `blockers` en payload; `_materialize_turn_blockers` emite HANDOFF_BLOCKED | Relaunch; bootstrap omite HANDOFF_BLOCKED si no hay requeue posterior |
| **Supervisor en motor root** | `supervisor_lock.txt` en `orquestador_de_agentes/.agent/runtime/` | `AGENT_PROJECT_ROOT` no estaba seteado al importar `ticket_supervisor.py` | Relaunch con `$env:AGENT_PROJECT_ROOT` correcto |
| **Triple Builder race** | 2-3 ventanas de Builder abiertas simultaneamente | Launcher + supervisor detectan el mismo CHANGES trigger en paralelo | Cerrar extras manualmente; usar `-LaunchBuilder 0` en CHANGES |

---

## Modo de revision

Revision esceptica y orientada a recuperacion. Busca:

- Divergencias entre el bus y los archivos de colaboracion que haran que el proximo arranque falle silenciosamente
- Eventos que parecen del supervisor reactivo pero son del controller (`source: mark-ready`)
- Triggers de requeue no procesados (sin `IN_PROGRESS` posterior ni `HANDOFF_BLOCKED` explicativo)
- Locks huerfanos que bloquearan el `Wait-SupervisorExit` del launcher
- Archivos de colaboracion que reflejan un ciclo anterior al estado real del bus

Si un patron ya ocurrio en sesiones anteriores y hay una leccion en memoria o en el backlog, citala. No dupliques la critica; solo confirma que aplica aqui.

---

## Formato de salida obligatorio

### 1. Resumen del bus

Una tabla con los eventos del ticket activo (todos, o los ultimos 20 si el ticket tiene historial largo):

```
seq | actor      | event_type      | timestamp   | payload resumido
----|------------|-----------------|-------------|------------------
542 | SUPERVISOR | STATE_CHANGED   | 11:37:23    | BOOTSTRAP -> IN_PROGRESS (source: bootstrap)
543 | BUILDER    | BUILDER_EXIT    | 11:46:23    | exit_reason: "..."
...
```

### 2. Hallazgos

Ordenados por severidad: `CRITICO` / `ALTO` / `MEDIO` / `BAJO`

Cada hallazgo incluye:

- Que archivo o evento evidencia el problema
- Por que es un problema
- Como fallaria: supervisor / Builder / Manager / launcher / packaging
- Correccion exacta o comando de recuperacion propuesto (no ejecutar)
- **Etiqueta de evidencia** (obligatoria):
  - `VERIFICADO EN BUS seq=N`: confirmado directamente en events.jsonl
  - `VERIFICADO EN CODIGO <archivo:simbolo>`: comprobado en el archivo fuente real
  - `VERIFICADO EN ARTEFACTO <archivo>`: comprobado en lock, log u otro artefacto
  - `INFERENCIA RAZONABLE`: deducido sin verificacion directa

Regla de evidencia: todo hallazgo `CRITICO` o `ALTO` necesita al menos una evidencia primaria (`VERIFICADO EN BUS`, `VERIFICADO EN CODIGO` o `VERIFICADO EN ARTEFACTO`). `INFERENCIA RAZONABLE` puede apoyar, pero no debe ser la unica base de un hallazgo bloqueante.

### 3. Patron de fallo identificado

Si el estado encaja en uno de los patrones de la tabla anterior, nombralo explicitamente. Si es un patron nuevo, describelo con precision suficiente para anadirlo a la tabla.

### 4. Veredicto final

Uno de:

- **SISTEMA SANO**: bus coherente, sin drift, listo para arrancar
- **RECUPERABLE**: hay drift o trigger no procesado; pasos exactos a continuacion
- **REQUIERE INTERVENCION MANUAL**: no puede recuperarse con relaunch estandar; razon principal y que fichero editar

Incluye tambien la confianza del diagnostico, atada a las etiquetas de evidencia:

- `ALTA`: la causa raiz tiene al menos dos evidencias primarias independientes (`VERIFICADO EN BUS` + `VERIFICADO EN CODIGO` o `VERIFICADO EN ARTEFACTO`). Los pasos de recuperacion son deterministas.
- `MEDIA`: la causa raiz tiene una evidencia primaria y el resto son inferencias que la apoyan. Los pasos son probables pero pueden necesitar ajuste segun el estado real del proceso.
- `BAJA`: la causa raiz descansa en `INFERENCIA RAZONABLE` sin verificacion primaria. **Obligatorio:** indica que aspecto especifico no pudo verificarse y que riesgo concreto implica ejecutar los pasos propuestos sin esa verificacion. No uses `BAJA` como comodin; si puedes leer el bus o el codigo, hazlo antes de clasificar aqui.

Independientemente del veredicto, cierra con dos bloques:

**Pasos de recuperacion propuestos (en orden, no ejecutar):**

Incluye comandos exactos con flags y rutas absolutas. Ejemplo para relaunch tras idle timeout:

```powershell
# 1. Setear project root antes de lanzar el supervisor
$env:AGENT_PROJECT_ROOT = 'C:\Users\fdl\Proyectos_Python\z_scripts'

# 2. Relanzar sin Builder; el supervisor detectara el trigger CHANGES en bootstrap
powershell -ExecutionPolicy Bypass -File `
  orquestador_de_agentes\scripts\launch_agent_terminals.ps1 `
  -ProjectRoot 'C:\Users\fdl\Proyectos_Python\z_scripts' `
  -LaunchBuilder 0

# Alternativa: lanzar supervisor directamente con timeout ampliado
$env:AGENT_PROJECT_ROOT = 'C:\Users\fdl\Proyectos_Python\z_scripts'
python orquestador_de_agentes\scripts\ticket_supervisor.py --reactive --timeout 900
```

**Deuda tecnica detectada (no bloquea recuperacion):**
- [patron de fallo estructural o gap en el sistema que conviene documentar o corregir en un ticket futuro]
