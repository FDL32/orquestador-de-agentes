# Known Failure Patterns Registry

Registro canonico de patrones de fallo observados en el motor y reutilizables
en auditorias, cierre de tickets y diseno de barreras.

## Uso

- Cita los patrones como `FP-XXX`.
- Separa siempre hechos verificados de inferencias y fixes candidatos.
- Un patron puede registrar workarounds operativos sin fijar todavia la
  solucion estructural.

---

## FP-001: Drift bus -> STATE.md / TURN.md

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- El bus contiene un `STATE_CHANGED` mas reciente que `STATE.md`.
- `TURN.md` sigue apuntando a un rol anterior.
- `supervisor_state.json.last_processed_sequence` queda por detras del maximo
  `seq` del bus.

### Contrato / realidad verificada

- El bus es la autoridad canonica de hechos y transiciones.
- `STATE.md` y `TURN.md` son proyecciones derivadas.
- Un ticket puede quedar con `bus=READY_FOR_REVIEW` y
  `STATE.md=IN_PROGRESS` si la proyeccion no se materializa a tiempo.

### Causa raiz probable

El supervisor emite o deja pasar eventos canonicos, pero muere o sale por idle
antes de proyectarlos completamente a `STATE.md` y `TURN.md`.

### Mitigacion temporal

- Reconciliar el ticket desde el bus antes de relanzar agentes.
- Tratar el bus como fuente de verdad si `STATE.md` y `TURN.md` divergen.

### Fix estructural candidato

- Hacer durable la proyeccion de estado.
- O forzar reconciliacion automatica cuando `last_processed_sequence` quede por
  detras del bus.

### Tickets relacionados

- `WT-2026-224a`
- `WT-2026-216`
- `WT-2026-214`

---

## FP-002: builder_launch_unverified con ejecucion real

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- El bus emite `BUILDER_RELAUNCH_ATTEMPTED` con
  `outcome=builder_launch_unverified`.
- Poco despues aparece `BUILDER_EXIT` o `STATE_CHANGED -> READY_FOR_REVIEW`.

### Contrato / realidad verificada

- El launcher puede no verificar el arranque del Builder aunque la ventana si
  ejecute trabajo real.
- La ausencia de verificacion no implica necesariamente ausencia de ejecucion.

### Causa raiz probable

La verificacion post-spawn depende de una senal de identidad o lock mas fragil
que la ejecucion real del proceso lanzado.

### Mitigacion temporal

- Revisar si hay `BUILDER_EXIT` posterior antes de asumir relaunch fallido.
- Evitar relanzar automaticamente solo por `builder_launch_unverified`.

### Fix estructural candidato

- Hacer mas robusta la verificacion de arranque.
- O introducir reconciliacion retrospectiva cuando el bus confirma actividad del
  Builder tras el launch no verificado.

### Escalada conocida

Este patron puede aparecer como inicio de una cascada:

- `FP-002`: el launcher no verifica el arranque;
- `FP-001`: el supervisor o la proyeccion quedan por detras del bus;
- `FP-003`: el cierre o handoff posterior detecta round explicito sin lock
  durable.

Observado en la secuencia `WT-2026-224a` `seq=691..696`.

### Tickets relacionados

- `WT-2026-224a`
- `WT-2026-221a`

---

## FP-003: stale_builder_round por lock ausente

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- `HANDOFF_BLOCKED` con `reason=stale_builder_round`.
- El Builder tiene identidad de round explicita, pero `builder_lock.txt` falta
  o no es legible.

### Contrato / realidad verificada

- La proteccion por round puede bloquear closeout o handoff cuando no existe el
  lock esperado para ese round.
- El problema puede aparecer incluso despues de trabajo real del Builder.

### Causa raiz probable

Hay una discrepancia entre la identidad de round entregada al proceso y el
artefacto durable que debe respaldarla.

### Mitigacion temporal

- Contrastar el bloqueo con los ultimos eventos del bus antes de relanzar.
- Verificar si el Builder ya emitio `BUILDER_EXIT` o `READY_FOR_REVIEW`.

### Fix estructural candidato

- Endurecer el contrato de creacion y lectura del lock.
- Reducir la dependencia de artefactos transitorios no confirmados.

### Tickets relacionados

- `WT-2026-221b`
- `WT-2026-224a`

---

## FP-004: Composicion PowerShell multi-linea rota

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- En una ventana hija aparece `= : El termino '=' no se reconoce...`.
- O aparece `Token 'try' inesperado`.
- Observado durante `WT-2026-224a` en una ventana real del Builder.

### Contrato / realidad verificada

- La composicion por concatenacion de bloques PowerShell puede romperse si las
  variables de entorno se expanden antes de tiempo o si falta el salto de linea
  entre bloques.
- El proceso puede abrirse con una linea sintacticamente invalida sin que el
  launcher principal detecte bien la causa.

### Causa raiz probable

Interpolacion prematura de `$env:` o union incorrecta entre prefijos de entorno
y bloques `try { ... }` en el comando compuesto.

### Estado actual

El patron fue identificado y mitigado. El codigo actual ya contiene el separador
explicito entre el prefijo de entorno y el bloque de ejecucion; este registro
documenta la familia del fallo, no afirma que el launcher siga roto hoy.

### Mitigacion temporal

- Inspeccionar el comando generado antes de asumir un fallo semantico del
  Builder.
- Repetir el arranque solo con una version verificada del launcher.

### Fix estructural candidato

- Centralizar la construccion de comandos multi-linea.
- Anadir tests que validen el comando compuesto real, no solo fragmentos.

### Tickets relacionados

- `WT-2026-224a`

---

## FP-005: REVIEW_DECISION con blockers vacios

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- `REVIEW_DECISION` con `decision=CHANGES`.
- Poco despues aparece `HANDOFF_BLOCKED` con `reason=empty_blockers`.

### Contrato / realidad verificada

- Un `CHANGES` sin blockers estructurados deja al supervisor o al Builder sin
  instruccion accionable.
- La barrera puede dispararse aunque el review conceptualmente exista.

### Causa raiz probable

El bridge o el camino de review no siempre serializa blockers de forma
estructurada en el payload canonico.

### Mitigacion temporal

- Tratar el feedback del Manager como fuente operativa si el payload no trae
  blockers estructurados.
- Evitar cerrar el analisis solo en base al `HANDOFF_BLOCKED`.

### Fix estructural candidato

- Garantizar blockers estructurados en todo `REVIEW_DECISION=CHANGES`.
- O degradar el bloqueo a warning cuando falte estructura pero exista feedback
  legible por otra via.

### Tickets relacionados

- `WT-2026-221b`
- `WT-2026-224a`

---

## FP-006: Rearranque desde fuente equivocada de verdad

**Estado de evidencia:** INFERENCIA RAZONABLE

### Sintoma observable

- El launcher o el operador relanza el agente equivocado porque `TURN.md` o
  `STATE.md` no reflejan el ultimo estado del bus.

### Contrato / realidad verificada

- La decision operativa correcta debe derivarse del bus cuando este es legible.
- Las proyecciones documentales son fallback o vistas derivadas, no autoridad
  primaria.

### Verificacion parcial

- La arquitectura bus-first del launcher esta verificada.
- La aplicacion de este patron como causa concreta en una instancia futura debe
  confirmarse caso por caso contra el bus y el launcher.

### Causa raiz probable

Se usa una proyeccion stale para decidir rol o accion en vez de consultar el
estado derivado del bus.

### Mitigacion temporal

- Confirmar el ultimo `STATE_CHANGED` del bus antes de relanzar.
- Si hay drift, reconciliar primero y solo despues lanzar.

### Fix estructural candidato

- Mantener el launcher y los flujos manuales alineados con el estado derivado
  del bus.
- Explicitar mas claramente en tooling y prompts cual es la fuente de verdad.

### Tickets relacionados

- `WT-2026-216`
- `WT-2026-224a`

---

## FP-007: Stub fail-open en codigo topologia-aware elevado a blocker arquitectonico

**Estado de evidencia:** VERIFICADO EN CODIGO Y REVIEW

### Sintoma observable

- Un metodo de `repo_motor` que depende de `motor_root` (resolucion de agente,
  discovery de paths, inyeccion de config) captura `RuntimeError` cuando
  `_motor_root_or_raise()` falla y crea un stub o fallback silencioso.
- El stub permite avanzar en pruebas aisladas o en rondas tacticas, pero
  Manager review para un ticket de codigo que formaliza la topologia lo
  identifica como blocker arquitectonico.

### Contrato / realidad verificada

- En la topologia `repo_motor + repo_destino`, cualquier codigo que degrada
  su comportamiento silenciosamente cuando `motor_root` no es resoluble viola
  el contrato topologico.
- Un fail-open en una ruta de decision (agent spec, cwd de subprocess, path
  discovery) no es un fallback defensivo; es una ruta de ejecucion incorrecta
  disfrazada de resiliencia.

### Causa raiz probable

Se acepta el stub como solucion tactica para desbloquear una ronda
Builder/Manager, sin extraerlo a un ticket de compatibilidad con scope y
aprobacion explicita.

### Mitigacion temporal

- Si el stub es inevitable para avanzar, abrirlo como ticket separado de
  compatibilidad antes de cerrar el ticket principal.

### Fix estructural candidato

- En codigo topologia-aware: llamar a `_motor_root_or_raise()` directamente
  y dejar que `RuntimeError` propague. No capturar la excepcion salvo en el
  perimetro de tests con topologia explicita.
- En tests: usar `_configure_motor_topology(project_root, motor_root)` o
  patron equivalente que construya un `motor_destination_link.json` real y
  un `manager.md` en la ruta esperada. No depender de mocks de
  `_motor_root_or_raise()` como setup principal; preferir topologia explicita
  con fixture real.

### Tickets relacionados

- `WT-2026-237a`
