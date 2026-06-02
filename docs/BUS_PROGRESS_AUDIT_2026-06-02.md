# BUS_PROGRESS_AUDIT_2026-06-02

Tipo: Informe de progreso post-implantación (para auditoría externa)
Baseline: [BUS_ARCHITECTURE_WT-2026-210.md](BUS_ARCHITECTURE_WT-2026-210.md)
Alcance: reconstrucción del contrato del bus, tickets WT-2026-205 → 216
Validación: externa al loop Manager/Builder/Supervisor (lectura directa de código, bus y commits)
Fecha: 2026-06-02

> **Cómo leer este informe.** Cada afirmación técnica se ancla con evidencia
> reproducible: `archivo:línea` o `commit`. El objetivo no es defender que el
> sistema sea perfecto, sino que el auditor pueda distinguir con precisión qué
> se reparó, qué sigue roto y por qué las decisiones tomadas son defendibles.

---

## 1. Objetivo de la intervención

El trabajo **no** fue una colección de hotfixes. Fue una redefinición del
contrato del bus para que el estado del sistema deje de depender de
**coincidencias entre procesos, documentos y timings**.

El problema estructural de partida: varias superficies actuaban como si fueran
la verdad —`events.jsonl`, `TURN.md`, `STATE.md`, `execution_log.md`,
`supervisor_state.json`, `manager_bridge_state.json`, locks de runtime— sin una
autoridad única. La consecuencia es que el sistema no toleraba:

- caída de procesos intermedios (idle timeout del supervisor),
- reinicios y locks stale,
- drift entre el bus y sus proyecciones,
- decisiones operativas tomadas desde documentos stale.

La auditoría base ([WT-2026-210](BUS_ARCHITECTURE_WT-2026-210.md)) documentó
esto con evidencia de bus (seq 540–547 del incidente WT-2026-205) y cambió el
enfoque: de *parchear síntomas* a *redefinir el contrato de lectura, escritura
y cierre*.

---

## 2. Estado inicial: las 7 invariantes rotas

Fuente: [BUS_ARCHITECTURE_WT-2026-210.md §4](BUS_ARCHITECTURE_WT-2026-210.md).
Estas son las invariantes que la auditoría base declaró **ROTA**:

| # | Invariante | Por qué estaba rota |
|---|-----------|---------------------|
| I1 | Un solo proceso decide el estado canónico | `agent_controller`, `supervisor` y `bridge` emitían `STATE_CHANGED` de forma independiente |
| I2 | `actor=SUPERVISOR` significa supervisor reactivo | `--mark-ready` emite `actor=SUPERVISOR` desde `agent_controller.py`, no desde el supervisor |
| I3 | `REVIEW_DECISION=CHANGES` tiene consumidor durable | Si el supervisor moría antes de procesar CHANGES, nadie hacía requeue hasta bootstrap manual |
| I4 | `TURN.md` refleja el estado canónico del bus | Supervisor muerto mid-transición → TURN stale indefinidamente |
| I5 | Builder activo == lock fresco + sin `BUILDER_EXIT` posterior | Lock podía quedar stale; idle timeout mataba al supervisor antes de que el Builder terminara |
| I6 | El runtime del workspace no mezcla tickets activos | `STATE.md` en WT-210, todo el runtime en WT-205: drift confirmado |
| I7 | Cerrar un ticket limpia el runtime antes del siguiente | **No existía** protocolo de forced close |

El caso testigo fue WT-2026-205: el supervisor reactivo murió por idle timeout
(Builder duró 540s; timeout = 300s), el Manager bridge —proceso *detached* que
sobrevivió— emitió `CHANGES` con diff vacío, y el bootstrap posterior del
supervisor encontró el trigger pero `TURN.md` decía `MANAGER/REVIEW_WORK`: el
launcher leyó `MANAGER` y **no lanzó el Builder**. Resultado:
`builder_launch_unverified`. Cinco fallos encadenados, ninguno causado por un
bug aislado, todos por ambigüedad de autoridad.

---

## 3. La intervención, fase a fase (con evidencia)

### Fase 0 — Reconciliación de runtime huérfano (WT-2026-210 / commit `29b332e`)

Antes de rediseñar nada hubo que poder cerrar tickets colgados sin depender del
loop vivo. Se introdujo [scripts/reconcile_ticket.py](../scripts/reconcile_ticket.py):

- emite eventos terminales canónicos si faltan,
- limpia artefactos stale del runtime,
- alinea `supervisor_state.json`, `manager_bridge_state.json`, `bridge_checkpoint.json`.

**Principio operativo nuevo:** si el loop falla, existe una vía canónica de
reconciliación. El sistema deja de quedar bloqueado sin salida. No resuelve la
arquitectura, pero elimina el deadlock terminal.

### Fase 1 — Centralización del write-path de proyecciones (WT-2026-211 / commit `0125638`)

El cambio más importante. Evidencia del diffstat:

```
.agent/agent_controller.py   | 131 +++----------------- (−122 neto)
bus/supervisor.py            | 133 +++++++++++++++++++++++ (+133)
tests/test_wt_2026_211_write_path.py | 146 ++++++++++++++ (nuevo)
```

La lógica de materialización de transiciones (`TURN.md`, `STATE.md`,
`execution_log.md`) se **movió** del controller al supervisor. El controller
queda más cerca de *emisor de hechos al bus*; el supervisor pasa a ser el
*materializador principal* de proyecciones operativas.

**Efecto:** reduce el drift bus↔proyecciones y hace el orden de transición más
determinista. La auditoría ya no tiene que perseguir tres procesos para
entender por qué `TURN.md` y el bus discrepan.

### Fase 2 — Consumidor durable de CHANGES (WT-2026-212 / commit `007875e`)

Hueco restante tras la Fase 1: `REVIEW_DECISION=CHANGES` podía existir en el bus
sin consumidor si el supervisor reactivo ya no estaba vivo.

La tentación fácil era que el bridge relanzara el Builder directamente. Se
**rechazó** por arquitectura: habría creado una segunda autoridad de requeue y
riesgo de doble relaunch, justo cuando el objetivo era centralizar. La solución
implantada en [bus/review_bridge.py:238](../bus/review_bridge.py#L238)
`_ensure_durable_changes_consumer`:

1. solo actúa si el lock del supervisor está stale (`_is_supervisor_lock_stale()`),
2. **guard anti-doble-relaunch**: si ya existe un `BUILDER_RELAUNCH_ATTEMPTED`
   posterior al `REVIEW_DECISION`, no hace nada
   ([review_bridge.py:251-261](../bus/review_bridge.py#L251)),
3. si no, dispara **un tick real del supervisor**: `bootstrap()` + `run_once()`
   + `_release_supervisor_lock()` ([review_bridge.py:272-284](../bus/review_bridge.py#L272)).

**Resultado arquitectónico limpio:** el bridge *garantiza que exista* un
consumidor, pero el consumo real lo ejecuta el supervisor con su lógica
canónica. El bridge no se convierte en writer paralelo.

### Fase 3 — Lectura canónica del launcher (WT-2026-216 / commit `07991cd`)

Se cerró la deuda de lectura más estructural. Antes,
`launch_agent_terminals.ps1` usaba `TURN.md` como autoridad para decidir qué
agente lanzar; con TURN stale tomaba la decisión equivocada aunque el bus fuera
correcto (causa directa del incidente WT-205).

Ahora [scripts/get_launcher_state.py:55](../scripts/get_launcher_state.py#L55):

- lee el ticket activo de `work_plan.md`,
- deriva el estado con `StateMachine.derive_state_from_events()`
  ([get_launcher_state.py:59](../scripts/get_launcher_state.py#L59)),
- devuelve JSON estable (`ticket_id, state, role, action, source`),
- `Get-ActiveRole` lo intenta primero; `TURN.md` queda como **fallback explícito**.

**Efecto:** la autoridad de lectura crítica pasa de proyección documental a
estado derivado del bus. Con esto, el rescate de la Fase 2 deja de ser el camino
normal y vuelve a ser lo que debe ser: una excepción.

---

## 4. Invariantes: reparadas vs. aún rotas (lectura honesta)

Esta es la tabla que el auditor debe mirar con más atención. No todo se cerró.

| # | Invariante | Estado tras la intervención | Evidencia / matiz |
|---|-----------|------------------------------|-------------------|
| I1 | Autoridad única de estado | **PARCIAL** | Se centralizó la *materialización de proyecciones* en el supervisor (WT-211). **Pero el write-path del bus en sí sigue sin guard**: cualquier proceso puede emitir `STATE_CHANGED`. Ver §5. |
| I2 | `actor=SUPERVISOR` fiable | **ABIERTA** | `--mark-ready` sigue emitiendo doble `STATE_CHANGED`, uno con `actor=SUPERVISOR` falso. Es WT-2026-213, no implementado. |
| I3 | Consumidor durable de CHANGES | **REPARADA** | WT-212 garantiza el consumidor vía tick del supervisor, con guard anti-doble-relaunch. |
| I4 | `TURN.md` refleja el bus | **MITIGADA** | El launcher ya no *depende* de TURN.md (WT-216). TURN puede seguir stale, pero ya no es autoridad para la decisión crítica. |
| I5 | Liveness del Builder fiable | **PARCIAL** | Persiste el riesgo de idle timeout; mitigado por liveness check (WT-084) pero no eliminado. |
| I6 | Runtime no mezcla tickets | **MITIGADA** | El reconciler permite converger runtime+doc, pero no hay prevención automática en preflight (ver I7). |
| I7 | Forced close al abrir ticket | **PARCIAL** | El reconciler existe (cierre manual). La integración al **preflight automático sigue siendo non-goal** (WT-2026-214 pendiente). |

**Conclusión de la tabla:** el sistema pasó de *frágil por ambigüedad de
autoridad* a *mucho más robusto por separación de responsabilidades*, en tres
ejes —escritura de proyecciones, consumo durable y lectura operativa—. Pero
**no es un sistema cerrado en todos sus bordes**, y este informe no lo pretende.

---

## 5. Por qué el bus es más fiable ahora (y el límite exacto de esa afirmación)

**Es más fiable porque:**

1. La materialización de proyecciones está concentrada en el supervisor, no
   repartida entre procesos (WT-211).
2. La lectura crítica del launcher se deriva del bus, no de markdown stale (WT-216).
3. CHANGES ya no depende de que el supervisor anterior siga vivo (WT-212).
4. El cierre canónico ya no exige que todo el loop esté vivo (reconciler).
5. Cada transición importante deja evidencia trazable en `events.jsonl`: los
   rescates y relanzamientos dejaron de ser "magia del proceso".

**El límite preciso —y esto es crítico para el auditor:**

> `bus/state_machine.py` es un **derivador de lectura, NO un guard de escritura**.
> No existe `validate_transition()` ni `can_transition()`. Cualquier proceso
> puede emitir un `STATE_CHANGED` que la state machine no valida.
> (Verificado: [BUS_ARCHITECTURE_WT-2026-210.md §2, línea 65](BUS_ARCHITECTURE_WT-2026-210.md)).

Lo que se reparó es **dónde se materializan las proyecciones** y **quién las
lee**. Lo que **no** se reparó es la ausencia de una barrera de validación en el
camino de escritura al bus. La sección 6 de la auditoría base proponía convertir
`state_machine.py` en guard de escritura; ese cambio **no se ha implementado**.
Decir "el bus es robusto" sin este matiz sería sobre-vender el entregable.

---

## 6. Deuda viva (tickets abiertos)

| Ticket | Scope | Impacto | Prioridad sugerida |
|--------|-------|---------|--------------------|
| WT-2026-213 | Eliminar doble `STATE_CHANGED` en `--mark-ready` (un solo evento `actor=BUILDER`) | Ruido semántico en el bus; mantiene I2 rota | Media |
| WT-2026-214 | Forced close en preflight: cerrar runtime del ticket anterior al abrir el siguiente | Cierra la clase de drift que originó WT-205 (I7) | **Alta** |
| WT-2026-215 | Gates Modelo B: `prepush_check.py` para workspace no-repo + motor portable | Bloquea `session_closeout` en Modelo B | Media |
| — | Consolidación documental: WT-211/212/216 **no están en `CHANGELOG.md` ni `PROJECT.md`** | La doc canónica va por detrás del código; incumple criterio de cierre #3 | **Alta** |

> El último punto es un hallazgo de este informe: los tres tickets de la
> reconstrucción están commiteados en git pero ausentes de la documentación
> canónica (entrada más reciente de [CHANGELOG.md](../CHANGELOG.md): WT-205).
> Un auditor que lea solo la doc oficial no sabría que esta reconstrucción
> ocurrió.

---

## 7. Mejoras propuestas

Ordenadas por relación valor/coste. Las tres primeras son de bajo coste y alto
valor; las siguientes son estructurales.

### 7.1 — Cerrar I7: integrar el reconciler al preflight (coste bajo, valor alto)

El reconciler ya existe; falta **invocarlo automáticamente** al arrancar un
ticket nuevo cuando el runtime del anterior quedó sin cierre. Es la deuda que
causó el incidente original (WT-205). No requiere arquitectura nueva, solo
cablear `reconcile_ticket.py` en el preflight del launcher/controller con una
detección de "ticket anterior sin terminal en el bus". **Es la mejora de mayor
retorno pendiente.**

### 7.2 — Extraer un módulo único de proyección operativa (coste bajo, valor medio)

Hoy existe un mapeo `TicketState → (role, action)` duplicado: uno en
[get_launcher_state.py:43](../scripts/get_launcher_state.py#L43)
(`_role_action_for_state`) y otro equivalente en el supervisor. Es deuda de
drift semántico latente: si una superficie cambia el mapeo y la otra no, el
launcher y el supervisor discreparán silenciosamente.

Propuesta: un único `bus/ticket_projection.py` (o `runtime/ticket_projection.py`)
que sea la **fuente única** de:

```
TicketState -> role
TicketState -> action
TicketState -> consumidor operativo esperado
```

Tanto el helper del launcher como el supervisor lo importan. Elimina la
duplicación y el riesgo de drift de un plumazo.

### 7.3 — Formalizar el contrato de lectura del launcher con schema explícito (coste bajo, valor medio)

`get_launcher_state.py` ya devuelve JSON estable, pero sin schema declarado.
Propuesta: definir explícitamente el contrato —`ticket_id`, `state`, `role`,
`action`, `source`, y añadir `fallback_used: bool`— y testear ambos caminos
(bus disponible vs. fallback a TURN.md). Hace auditable *cuándo* el launcher
cayó al fallback, dato hoy invisible.

### 7.4 — Convertir `state_machine.py` en guard de escritura (coste medio, valor alto)

Es la mejora que cierra I1 de verdad. Hoy el bus no valida transiciones. Añadir
una barrera `validate_transition(from, to, event)` que **rechace** escrituras
incoherentes (p.ej. `READY_TO_CLOSE → IN_PROGRESS` sin requeue) convertiría el
bus de "append-only observable" en "append-only **coherente**". El diseño base
ya está descrito en [BUS_ARCHITECTURE_WT-2026-210.md §6](BUS_ARCHITECTURE_WT-2026-210.md);
solo falta implementarlo. Riesgo: hay que auditar todos los call-sites de emisión
para no introducir rechazos espurios.

### 7.5 — Supervisor durable real (coste medio-alto, valor alto, largo plazo)

WT-212 es elegante pero sigue siendo un *kick* del bridge al supervisor. La
solución de fondo a la clase entera de bugs "supervisor murió entre dos
escrituras" (I5) es un daemon persistente que no muera por idle timeout y sea el
único writer de proyecciones. Tradeoff explícito: **más robustez a cambio de
gestión de ciclo de vida del daemon** (restart, healthcheck, supervisión del
supervisor). Es la Opción B de la auditoría base; recomendada como visión, no
como urgencia.

### 7.6 — Adelgazar la lógica crítica en PowerShell (coste bajo por incremento, valor alto acumulado)

Ver §8. No es una reescritura: es continuar el patrón que WT-216 ya demostró.

---

## 8. Sobre el uso de otros lenguajes

**Recomendación: mantener Python como lenguaje del motor.** El bus, supervisor,
bridge, reconciler y la suite de tests ya viven ahí; la testabilidad es muy
superior a PowerShell y la inversión existente es alta. Reescribir en Go o Rust
sería caro, rompería contexto y aumentaría el mantenimiento sin necesidad
inmediata. **No se recomienda otro lenguaje a corto ni medio plazo.**

El único punto donde el lenguaje actual sí genera fricción es el **launcher en
PowerShell**: no porque PowerShell sea malo como glue del SO, sino porque la
lógica *semántica* embebida en `.ps1` no se puede testear con la misma fidelidad
que Python.

La buena noticia: **WT-2026-216 ya es la prueba del patrón correcto.** No hizo
falta migrar el launcher; bastó extraer la decisión a un helper Python
(`get_launcher_state.py`) testeable y dejar que PowerShell lo invoque. La regla
de evolución, por tanto, no es "reescribir" sino:

> **Toda decisión semántica nueva va a un helper Python con test focal.
> PowerShell queda como borde de integración con Windows (arranque de
> terminales, procesos hijo, UX de consola).**

Coste casi nulo por incremento, y con el tiempo vacía el `.ps1` de contrato
crítico sin un proyecto de migración dedicado. Las alternativas de migración
total del launcher a Python, o de runtime duro a Go/Rust, quedan documentadas
como posibles pero **no recomendadas ahora** por coste/beneficio.

---

## 9. Veredicto para el auditor

El sistema cambió de **tipo**: antes dependía de coincidencias correctas entre
procesos y documentos; ahora depende de contratos explícitos en tres ejes
—escritura de proyecciones (WT-211), consumo durable de triggers (WT-212) y
lectura operativa (WT-216)— con una vía de reconciliación cuando el loop falla.

Eso es precisamente lo que empieza a hacer fiable a un bus: una sola verdad
canónica de lectura, menos writers paralelos de proyecciones, y un consumidor
durable de los triggers críticos.

**Pero quedan tres bordes abiertos que el auditor debe ponderar:** el write-path
del bus sigue sin barrera de validación (I1 parcial), el forced-close automático
no existe (I7, WT-214), y la documentación canónica va por detrás del código.
Las dos primeras son las que recomiendo priorizar; la tercera es de cierre
inmediato.

---

### Apéndice — Trazabilidad de evidencia

| Afirmación | Evidencia |
|-----------|-----------|
| Auditoría base con invariantes verificadas | [BUS_ARCHITECTURE_WT-2026-210.md](BUS_ARCHITECTURE_WT-2026-210.md) |
| Reconciler de runtime huérfano | commit `29b332e` · [reconcile_ticket.py](../scripts/reconcile_ticket.py) |
| Write-path centralizado en supervisor | commit `0125638` (controller −122 / supervisor +133) |
| Consumidor durable de CHANGES + guard anti-doble-relaunch | commit `007875e` · [review_bridge.py:238](../bus/review_bridge.py#L238) |
| Launcher lee el bus | commit `07991cd` · [get_launcher_state.py:55](../scripts/get_launcher_state.py#L55) |
| state_machine es derivador, no guard | [BUS_ARCHITECTURE_WT-2026-210.md §2 (línea 65)](BUS_ARCHITECTURE_WT-2026-210.md) |
| WT-211/212/216 ausentes de CHANGELOG/PROJECT | [CHANGELOG.md](../CHANGELOG.md) (entrada más reciente: WT-205) |
