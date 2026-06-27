# Loop-readiness gate (cid-loop-readiness-v0)

> Fuente unica de verdad sobre si una tarea es apta para /goal autonomo.
> Adoptada en WOT-2026-014s (loop-engineering, 2026-06-27).
> Origen externo: cobusgreyling/loop-engineering, pasos 2 y 12 del roadmap Medium.
> Gobierno: skill apunta, prompt gobierna (AGENTS.md). Las skills que referencien
> este gate son punteros operativos; los criterios normativos viven aqui.

---

## Evaluacion pre-loop

Las 4 condiciones siguientes deben ser TRUE de forma CONJUNTA para habilitar
/goal autonomo. Si UNA sola es FALSE, la tarea NO es loop-ready.

### (a) Recurrente

La tarea se repite o se ejecuta en lote. Ejemplos validos: ejecutar la suite de
tests sobre cada commit, procesar un backlog de tickets con criterios uniformes,
validar encoding en todos los archivos de un directorio.

Criterio: el work_plan o el input del gate declara explicitamente que la tarea
es recurrente, periodica o de lote. Si la tarea es un cambio unico de
arquitectura, feature nueva de diseno abierto o investigacion exploratoria,
(a) es FALSE.

### (b) Verificacion automatizable

Existe un gate objetivo con resultado pass/fail deterministico: un comando, test
o script cuyo exit code 0 = OK y != 0 = fallo, sin ambiguedad.

Criterio: el work_plan nombra el comando exacto o el test especifico que decide
el resultado. El gate no puede ser una inspeccion visual, un juicio cualitativo
ni un criterio de exito subjetivo. Si el exito no es expresable como gate
objetivo, (b) es FALSE.

### (c) Presupuesto de tokens definido

El work_plan declara un ENTERO como tope de iteraciones o tokens (p.ej.
"max_iterations: 50" o "presupuesto: 100 iteraciones").

Criterio CRITICO: el ENTERO debe estar declarado en el INPUT del gate (en el
work_plan o en el campo explicitamente asignado antes de arrancar /goal). El
evaluador NO estima ni calcula el presupuesto en runtime; si el campo no existe
en el input, (c) es FALSE. Esta condicion elimina la auto-asignacion de
presupuesto por el agente ejecutor.

### (d) Acceso a tooling/runtime real nombrado

El work_plan NOMBRA el artefacto concreto que provee el gate de verificacion:
binario exacto, ruta de fixture real, endpoint o ruta .agent/runtime/... El
nombre debe aparecer literalmente en el input del gate.

Criterio: campo nombrado, no checkbox. Solo TRUE si el nombre concreto del
artefacto figura en el input. Decir "tengo acceso al runtime" o "dispongo de
herramientas" sin citar el nombre exacto NO satisface (d). Esta condicion
elimina la auto-attestation del agente sobre sus capacidades.

---

## Denylist no-loopeable

Cualquier condicion de la denylist activa -> tarea rechazada, independientemente
de las 4 condiciones anteriores.

### Arquitectura amplia (umbral contable N=3)

La tarea toca MAS DE 1 superficie de estado compartido entre:
- `.agent/runtime/` (eventos, memoria, tmp, reviews)
- `.agent/collaboration/` (work_plan, execution_log, TURN, STATE, backlog)
- `bus/` (supervisor, memory_loader, review_bridge, esquemas de eventos)

O bien:
- Modifica la maquina de estados del bus o el esquema de eventos.
- El FLT del work_plan declara mas de N=3 modulos distintos.

Cualquiera de estas condiciones verdadera -> arquitectura amplia -> NO_LOOPEABLE.

Umbral N=3 es el default calibrado para este motor. La regla de escalado (ver
seccion siguiente) cubre el limite exacto (exactamente N=3 modulos o duda sobre
si una ruta cuenta como superficie de estado compartido).

### Auth/pagos/seguridad de credenciales

La tarea toca autenticacion, flujos de pago, gestion de credenciales, permisos
de acceso o tokens. No loopeable sin supervision humana explicita.

### Feature subjetiva

El exito no es expresable como gate objetivo. Equivale a (b) FALSE pero se
lista en la denylist para que el rechazo sea explicito incluso si el evaluador
no llego a aplicar la condicion (b).

### Sin gate objetivo

No existe comando, test ni script que decida pass/fail deterministico. Equivale
a (b) FALSE; se lista aqui por simetria con el razonamiento anterior.

---

## Regla de escalado de ambiguedad

Cuando la heuristica contable esta en el limite exacto (exactamente N=3 modulos
en FLT, o duda razonable sobre si una ruta concreta cuenta como superficie de
estado compartido), el BUILDER reporta el conteo objetivo y escala al MANAGER.

El Builder NO auto-clasifica en el limite. El Manager emite el veredicto con el
conteo como evidencia. Esta regla elimina el self-attestation del agente
ejecutor, que tiene incentivo implicito de que su tarea sea loop-ready.

Procedimiento:
1. Builder cuenta modulos distintos en FLT y superficies de estado compartido
   tocadas.
2. Builder reporta: "Conteo: N modulos en FLT, M superficies de estado compartido."
3. Si N == 3 exactamente, o si hay duda sobre una ruta, Builder escala al Manager
   antes de emitir veredicto.
4. Manager emite LOOP_READY o NO_LOOPEABLE con justificacion.

---

## Fixtures de verificacion

Los siguientes casos son la barrera critica del ticket WOT-2026-014s. Un
evaluador puede aplicar la rubrica y obtener el mismo resultado sin ambiguedad.

### Caso A: NO_LOOPEABLE por arquitectura amplia

**Descripcion de la tarea:**
Tarea que toca .agent/runtime/events/ (bus de eventos) Y .agent/collaboration/
(work_plan, execution_log). Ambas son superficies de estado compartido segun
la denylist.

**Input del gate:**

```
Tarea: sincronizar estado del ticket entre bus y proyecciones.
FLT: .agent/runtime/events/events.jsonl, .agent/collaboration/work_plan.md
Recurrente: si (se ejecuta en cada handoff)
Gate objetivo: python .agent/agent_controller.py --validate --json
Presupuesto: max_iterations: 10
Artefacto nombrado: python .agent/agent_controller.py --validate --json
```

**Aplicacion de la rubrica:**

Condiciones (a)(b)(c)(d):
- (a) Recurrente: TRUE (se ejecuta en cada handoff)
- (b) Gate objetivo: TRUE (python .agent/agent_controller.py --validate --json, exit 0 = OK)
- (c) Presupuesto declarado: TRUE (max_iterations: 10, entero en el input)
- (d) Artefacto nombrado: TRUE (python .agent/agent_controller.py --validate --json citado literalmente)

Las 4 condiciones son TRUE. Sin embargo, se aplica la denylist antes de emitir LOOP_READY.

Denylist - arquitectura amplia:

Conteo de superficies de estado compartido:
1. `.agent/runtime/events/` -> superficie de estado compartido (bus de eventos)
2. `.agent/collaboration/` -> superficie de estado compartido (proyecciones del ticket)

CONTEO OBJETIVO: 2 superficies de estado compartido (> 1 umbral de denylist).

Resultado: denylist arquitectura amplia ACTIVADA.

**Veredicto: NO_LOOPEABLE**
Causa: 2 superficies de estado compartido tocadas (.agent/runtime/events/ +
.agent/collaboration/). Umbral denylist: > 1 superficie de estado compartido.
El conteo objetivo (2) supera el umbral. No activar /goal autonomo.

---

### Caso B: NO_LOOPEABLE por (d) FALSE

**Descripcion de la tarea:**
Tarea con (a)(b)(c) aparentemente TRUE pero el campo (d) usa lenguaje de
checkbox en lugar de nombrar el artefacto concreto.

**Input del gate:**

```
Tarea: ejecutar suite de tests de regresion sobre los ultimos 5 commits.
FLT: tests/unit/test_controller.py
Recurrente: si (en cada batch de commits)
Gate objetivo: pytest con exit 0 = OK
Presupuesto: max_iterations: 5
Acceso a tooling: tengo acceso al runtime y puedo ejecutar tests
```

**Aplicacion de la rubrica:**

Condiciones:
- (a) Recurrente: TRUE (batch de commits)
- (b) Gate objetivo: TRUE (pytest, exit 0 = OK)
- (c) Presupuesto declarado: TRUE (max_iterations: 5, entero en el input)
- (d) Artefacto nombrado: EVALUAR

Evaluacion de (d):
El campo dice "tengo acceso al runtime y puedo ejecutar tests". Esto es un
CHECKBOX de capacidad declarada por el agente, no el nombre concreto del
artefacto. La condicion (d) exige que el nombre especifico figure en el input:
el binario exacto (p.ej. python scripts/run_pytest_safe.py), la ruta de fixture
real o el endpoint. "puedo ejecutar tests" es self-attestation sin artefacto.

(d) FALSE: artefacto concreto ausente del input.

**Veredicto: NO_LOOPEABLE**
Causa: condicion (d) FALSE. El campo de tooling/runtime usa lenguaje de
checkbox ("tengo acceso al runtime") sin nombrar el artefacto concreto. Un
checkbox no es evidencia de acceso real; solo un nombre especifico lo es.

---

### Caso C: LOOP_READY

**Descripcion de la tarea:**
Tarea recurrente de verificacion de suite, con gate objetivo, presupuesto
entero declarado y artefacto nombrado. FLT declara 1 modulo.

**Input del gate:**

```
Tarea: ejecutar suite de tests unitarios en modo safe tras cada commit de la
       rama de integracion.
FLT: tests/unit/test_controller.py
Recurrente: si (tras cada commit de la rama)
Gate objetivo: python scripts/run_pytest_safe.py, exit 0 = OK
Presupuesto: max_iterations: 50
Artefacto nombrado: scripts/run_pytest_safe.py
```

**Aplicacion de la rubrica:**

Condiciones:
- (a) Recurrente: TRUE (tras cada commit de la rama)
- (b) Gate objetivo: TRUE (python scripts/run_pytest_safe.py, exit 0 = OK, deterministico)
- (c) Presupuesto declarado: TRUE (max_iterations: 50, entero declarado en el input)
- (d) Artefacto nombrado: TRUE (scripts/run_pytest_safe.py citado literalmente)

Las 4 condiciones son TRUE.

Denylist:
- Arquitectura amplia: FLT declara 1 modulo (tests/unit/test_controller.py).
  Superficies de estado compartido tocadas: 0 (tests/unit/ no es .agent/runtime/,
  .agent/collaboration/ ni bus/).
  Conteo: 0 superficies de estado compartido. Umbral no superado.
- Auth/pagos/seguridad: no aplica.
- Feature subjetiva: no aplica (gate objetivo presente).
- Sin gate objetivo: no aplica.

Denylist: vacia. Ninguna condicion activada.

**Veredicto: LOOP_READY**
Las 4 condiciones son TRUE y la denylist esta vacia. La tarea es apta para
/goal autonomo con el presupuesto declarado (max_iterations: 50).

---

## Protocolo de output

El evaluador (Manager o agente con rol de gate) emite uno de dos veredictos:

### LOOP_READY

```
Veredicto: LOOP_READY
Condiciones: (a) TRUE, (b) TRUE, (c) TRUE, (d) TRUE
Denylist: ninguna condicion activada
FLT modulos: <N>
Superficies de estado compartido: <M>
Presupuesto declarado: <entero del input>
Artefacto nombrado: <nombre literal del input>
```

### NO_LOOPEABLE

```
Veredicto: NO_LOOPEABLE
Condicion fallida: <(a)|(b)|(c)|(d)|denylist-arquitectura|denylist-auth|denylist-subjetiva|denylist-sin-gate>
Conteo objetivo: <evidencia contable que produjo el rechazo>
Causa: <descripcion concisa de la condicion fallida>
Proxima accion: <escalar al Manager | corregir el input | redefinir el scope>
```

El evaluador NO emite narrativa adicional que pueda ser interpretada como
aprobacion parcial. El veredicto es binario. Si hay ambiguedad en el conteo,
el evaluador reporta el conteo y escala al Manager (regla de escalado de
ambiguedad).
