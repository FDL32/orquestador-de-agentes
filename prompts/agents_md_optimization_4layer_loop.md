---
role: orchestrator
route_kind: mantenimiento
---
# Prompt: Optimizacion de AGENTS.md en pasadas consecutivas, protocolo trio (MAN/BUI/REV)

<!-- PROMPT-SUMMARY
what: Gobierna pasadas repetidas de prompts/doc_optimization.md sobre un fichero
      siempre-cargado (por defecto AGENTS.md), despachando cada turno con las plantillas
      ya existentes prompts/kilo_trio_dispatch/dispatch_{manager,builder,revisor}.template.md
      (esqueleto B0-B9), especializando su B2 con este prompt en vez de backlog_triage.md.
when: Cuando el cierre transitivo de lo siempre-cargado supera el presupuesto (~5% de la
      ventana efectiva) y se quiere reducirlo con varias pasadas delegadas al trio en vez
      de una sesion manual por pasada.
not: NO redefine QUE mover (prompts/doc_optimization.md, citado por referencia, nunca
      redeclarado) ni el esqueleto de despacho B0-B9 (prompts/kilo_trio_dispatch/*.template.md,
      reusado tal cual). NO sustituye el bucle adversarial de ensemble_dispatch.py cuando el
      usuario lo pida explicitamente para una propuesta concreta (Seccion 5).
-->

contract_id: cid-agents-md-optimization-trio-v1
source_of_truth: este prompt, para la fase de PLAN/triaje de una pasada de doc-optimization
(mismo rol que `prompts/backlog_triage.md` juega para el backlog). El esqueleto de despacho
de cada turno sigue viviendo, sin redeclarar, en `prompts/kilo_trio_dispatch/*.template.md`
(X-09: skill/plantilla apunta, prompt gobierna).

## 0. Que es "basarse en el triaje" aqui

`prompts/backlog_triage.md` es PLAN de solo lectura sobre el backlog: clasifica, propone un
DAG, nunca muta. Este prompt juega el MISMO papel para UN fichero siempre-cargado en vez de
para el backlog: el Turno 1 (Manager) es solo-lectura (mide, clasifica el candidato contra
las cinco condiciones de `doc_optimization.md` PASO 3), nunca mueve nada el mismo; el DAG de
`backlog_triage.md` aqui es, trivialmente, una lista de UN candidato por pasada (restriccion
dura de `doc_optimization.md`: "SOLO se propone y aplica UN fichero/bloque por corrida").

Las plantillas `prompts/kilo_trio_dispatch/dispatch_manager.template.md`,
`dispatch_builder.template.md` y `dispatch_revisor.template.md` se reusan SIN modificar su
esqueleto B0-B9. Cambio principal por pasada: su bloque **B2 — Contrato que gobierna** cita,
en vez de (o ademas de) `backlog_triage.md`:

- `prompts/doc_optimization.md` (`cid-doc-optimization-v1`) — que mover y las cinco
  condiciones del PASO 3.
- este prompt (`cid-agents-md-optimization-trio-v1`) — el bucle de pasadas y los estados
  terminales.

**Adaptaciones DECLARADAS adicionales (no solo B2; verificado contra las tres plantillas
reales, no asumido):** este protocolo NO opera sobre un `TICKET`/`VUELO_ID` de la cola de
backlog -- opera sobre un fichero siempre-cargado y un numero de pasada. Donde las
plantillas asumen esa identidad de ticket, este prompt la sustituye explicitamente:

- **B3 (ruta del artefacto):** las tres plantillas declaran
  `.agent/planning/vuelo_{{VUELO_ID}}/{{TICKET}}/dispatch_<rol>_r{{R}}.md`. Aqui no hay
  `TICKET` ni `VUELO_ID`: la ruta real es
  `.agent/planning/agents_md_optimization/pasada_<N>_<rol>.md` (Seccion 2 y Seccion 6). El
  `builder_recibo_r{{R}}.md` que `dispatch_builder.template.md` B1/B9 exige como artefacto
  de cierre del Builder se funde en ese mismo `pasada_<N>_builder.md`: no hay un fichero
  `builder_recibo_*` adicional bajo este prompt.
- **B4 (gate de entrada):** donde `dispatch_manager.template.md` B4 exige el despacho del
  Orquestador en `dispatch_orc_r{{R}}.md`, aqui NO EXISTE ese artefacto -- el Orquestador es
  la sesion T3 que invoca `kilo run` directamente (Seccion 1), sin dejar fichero de despacho
  propio; esa condicion de la plantilla se declara N/A para este prompt. Donde
  `dispatch_builder.template.md` B4 exige "el despacho del Manager existe en
  `dispatch_manager_r{{R}}.md`" ademas de "work_plan.md aprobado", la Seccion 2 (Turno 2) de
  aqui sustituye AMBAS condiciones por una sola: el informe del Manager de ESTA pasada
  (`pasada_<N>_manager.md`) debe existir y declarar un candidato (no un estado terminal).
  Donde `dispatch_revisor.template.md` B4 exige el despacho del Builder en
  `dispatch_builder_r{{R}}.md`, aqui se sustituye por `pasada_<N>_builder.md` de la misma
  pasada. El resto de condiciones de B4 de cada plantilla (scope en vuelo por otra sesion ->
  `REQUIERE_HUMANO`; condicion dura de modelo distinto Revisor/Builder) SI aplican sin
  cambio y no se redeclaran aqui.
- **B4 del Manager, condiciones especificas de triaje de backlog (verificado contra
  `dispatch_manager.template.md` B4 completo, no solo su primera condicion):** la plantilla
  exige ademas `check_backlog_contract.py` con exit 0 sobre el backlog, y que
  `memory_context.py --recall` + `find_similar_signals.py` hayan corrido y dedupeado. Este
  protocolo NO opera sobre el backlog de tickets -- no hay `backlog.md` ni cola que auditar
  en una pasada de `doc_optimization.md` -- asi que `check_backlog_contract.py` se declara
  N/A explicitamente, igual que `dispatch_orc_r{{R}}.md`. `memory_context.py --recall` SI
  conserva utilidad aqui (puede existir ya una leccion sobre este mismo bloque/fichero) y el
  Turno 1 de la Seccion 2 lo hereda como practica recomendada, sin que sea gate duro de
  entrada: su ausencia no bloquea el turno, a diferencia de en `backlog_triage.md`.

## 1. Adaptacion declarada de B7/B8 (board_post/mailbox/bus)

Las plantillas del trio asumen, en B7-B8, primitivas de coordinacion de workers supervisados
(`board_post`, `mailbox/<session_id>/`, `register_pending`/`register` de bus) que no estan
implementadas en `bus/` de este motor para una invocacion DIRECTA de Kilo CLI. Esa via de
invocacion (`prompts/builder_invocation_contract.md` Seccion 1) es explicita: "Sin bus de
eventos: Kilo no emite `BUILDER_EXIT` ni ningun otro evento al bus del orquestador."

Por tanto, bajo este prompt, B7/B8 de cada plantilla se leen asi:
- **B7 (puntos de sondeo):** sustituido por el Orquestador (Capa 0, esta sesion T3) leyendo
  el fichero de salida de cada turno (B3 de la plantilla) tras cada invocacion `kilo run`
  (comando canonico de `builder_invocation_contract.md` Seccion 1). No hay `board_post`; el
  "sondeo" es la lectura sincrona del fichero al terminar el proceso.
- **B8 (bus + bitacora):** sustituido por el Orquestador anotando a mano inicio/fin de cada
  turno en `.agent/planning/agents_md_optimization/pasada_<N>_bitacora.md` -- mismo patron
  que `builder_invocation_contract.md` exige para cualquier Builder sin bus.

Si una sesion futura invoca este prompt DENTRO de un entorno Orca con board/mailbox reales
disponibles, puede usar B7/B8 tal cual las declaran las plantillas -- declararlo
explicitamente al arrancar la pasada, no asumirlo en silencio.

## 2. Los cuatro turnos de UNA pasada

Cada pasada es UN ciclo completo, nunca menos. El Orquestador invoca cada turno por separado
via `kilo run` (`builder_invocation_contract.md` Seccion 1), espera su fichero de salida
(B3 de la plantilla correspondiente), y no avanza sin haberlo leido completo.

**Condicion dura de independencia** (misma condicion de independencia que
`prompts/persona_system.md` Seccion 2 -- "NUNCA el mismo agente implementa y revisa",
usando la colision de modelo/backend como senal de violacion, no al reves -- y verificada
mecanicamente por `check_role_models_distinct.py` segun `dispatch_revisor.template.md` B0 y
B4): el modelo `nan/<modelo>` del Turno 1.5 (Revisor) NUNCA es el mismo que el del Turno 2
(Builder) de la MISMA pasada. El Orquestador declara los dos modelos elegidos antes de
lanzar el Turno 2.

### Turno 1 -- Manager: busca oportunidad

Despacho: `dispatch_manager.template.md`, B2 especializado segun Seccion 0 de este prompt.
B1 (mandato): "Aplicar PASO 0-3 de `prompts/doc_optimization.md` sobre {{FICHERO_OBJETIVO}}
(default `AGENTS.md`) y proponer UN candidato, o declarar un estado terminal."
B3 (artefacto): `.agent/planning/agents_md_optimization/pasada_<N>_manager.md`, con:
1. Estampa `ESTADO_FRESCO` (PASO 0 de `doc_optimization.md`).
2. Tabla de medicion del cierre transitivo: chars, proxy de tokens, % sobre la ventana
   (PASO 1).
3. El candidato elegido (seccion/lineas exactas) con su fila del PASO 2 y el veredicto letra
   por letra de las CINCO condiciones del PASO 3 -- o uno de los estados terminales
   (`SIN CANDIDATO MOVIBLE`, `NO APLICA`, `BLOQUEADO`) si no hay nada que mover esta pasada.
4. Si hay candidato: el bloque EXACTO a mover (verbatim, delimitado) y el nombre propuesto
   del fichero destino en `docs/protocol/`, con la convencion ya usada (`x09_*_case.md` u
   homologa: blockquote de procedencia citando seccion origen + este prompt + fecha).

Si el Manager declara `SIN CANDIDATO MOVIBLE`, `NO APLICA` o `BLOQUEADO`: la pasada TERMINA
aqui (Seccion 3). El Orquestador no lanza el Turno 2.

### Turno 2 -- Builder: aplica

Despacho: `dispatch_builder.template.md`, B2 especializado igual. B4 (gate de entrada) pasa
a exigir el informe del Manager de ESTA pasada en vez de `work_plan.md`. B1: "Aplicar el
traslado minimo del bloque que el Manager identifico (PASO 4 de `doc_optimization.md`), sin
resumir, con guard de no-degradacion verificado."

Obligaciones heredadas de `doc_optimization.md` PASO 4 (citadas, no redeclaradas en el
despacho): medir ANTES (fichero + cada consumidor censado por el Manager), aplicar el
traslado minimo, regenerar (nunca editar a mano) ficheros `generado` dependientes
(`llms.txt`/`llms-full.txt` via `scripts/build_llms.py` si existen), medir DESPUES con los
mismos consumidores, correr la suite canonica completa UNA vez al final, commit LOCAL
(`git push` PROHIBIDO en este turno) citando este prompt y el numero de pasada.

B3: `.agent/planning/agents_md_optimization/pasada_<N>_builder.md` con el SHA del commit,
el before/after de cada consumidor, y la salida de la suite.

### Turno 1.5 -- Revisor: revisa la aplicacion

Despacho: `dispatch_revisor.template.md`, B2 especializado igual, mas
`prompts/doc_optimization.md` PASO 4 como criterio de guard. El Revisor NO confia en lo que
el Builder declaro -- lo reverifica contra el commit real:
- Releer el bloque movido en el fichero destino: ¿es VERBATIM del original, o se resumio?
  (non-goal duro de `doc_optimization.md`; cualquier resumen es `DECISION: CHANGES`
  automatico).
- Releer el puntero que queda en el origen: ¿sigue siendo localizable desde donde "muerde"
  el fallo (condicion (b) del PASO 3)?
- Re-ejecutar (no releer el log ajeno) al menos UN consumidor censado y comparar su salida
  real contra el before/after declarado por el Builder.
- Confirmar que el commit es LOCAL (sin push) y que la suite reportada coincide con lo que
  el propio Revisor puede verificar (`git log`, `git show --stat`).

Veredicto en el formato de `dispatch_revisor.template.md` B1/B3 (`DECISION: APPROVE` o
`DECISION: CHANGES` con hallazgos `ruta:linea`). B3:
`.agent/planning/agents_md_optimization/pasada_<N>_revisor.md`.

Si `DECISION: CHANGES`: la pasada NO se da por cerrada. El Orquestador decide con el usuario
si se relanza el Turno 2 (mismo Builder, con los hallazgos) o se descarta el candidato y se
repite el Turno 1 con ese bloque marcado "intentado, revertido".

### Turno 1 (segunda vez) -- Manager: analiza y decide la pasada siguiente

Mismo despacho que el Turno 1, B1 distinto: "Medir el cierre transitivo FRESCO tras el
commit del Builder (nunca reusar la medicion de la primera vez: el fichero cambio) y decidir
si hay pasada siguiente." Output anadido al MISMO fichero del Turno 1 (no uno nuevo):
1. % actual sobre la ventana, y cuanto bajo respecto a la pasada anterior.
2. Si `% < 5%`: declara **SUELO** (`doc_optimization.md`, Restriccion dura) -- no se abre
   pasada siguiente aunque queden bloques teoricamente movibles.
3. Si `% >= 5%`: identifica el SIGUIENTE candidato (repite PASO 1-3), o declara
   `SIN CANDIDATO MOVIBLE` -- tambien se para, como deuda declarada (PASO 5 de
   `doc_optimization.md`, opcion 2: ticket dueno + criterio de salida, nunca silencio).

## 3. Cierre de cada pasada (Orquestador, Capa 0)

Tras el Turno 1 (segunda vez), el Orquestador reporta al usuario un resumen corto
(<500 palabras, mismo limite que el resto de 4 capas, `agent_execution_modes.md` Seccion 1,
tabla de modos -- celda "4 capas"):
candidato movido, veredicto del Revisor, SHA del commit, nueva medicion %, y el estado
terminal declarado por el Manager.

El Orquestador NUNCA encadena la pasada siguiente sin confirmacion del usuario, salvo que el
usuario haya pedido explicitamente ejecutar N pasadas seguidas sin pausa -- en ese caso el
Orquestador lo declara al arrancar y se detiene igual de inmediato si cualquier turno
devuelve `BLOQUEADO` o `DECISION: CHANGES` sin resolver en el mismo ciclo.

Push: nunca automatico. Cada pasada deja como maximo un commit LOCAL adicional. El
Orquestador pregunta por el push solo al cerrar la sesion de optimizacion (una pregunta, no
una por pasada).

## 4. Estados terminales validos de UNA pasada

**Nota de ortogonalidad:** `SUELO` (Seccion 2, Turno 1 segunda vez) NO es un estado de esta
lista -- no describe si ESTA pasada aplico o no un candidato, sino si existe o no una
PASADA SIGUIENTE. `SUELO` coexiste con `APLICADO`: la pasada actual puede cerrar
`APLICADO` y, en el mismo turno, el Manager declarar `SUELO` para la secuencia completa
(ningun candidato nuevo se busca despues de esta). La Seccion 6 trata `SUELO` como el
disparador del `RESUMEN.md` final precisamente porque marca el fin de la SECUENCIA, no el
de una pasada individual.

Los mismos cuatro de `doc_optimization.md` Seccion "Salida", mas uno propio:

- `APLICADO` -- con guard de no-degradacion verificado de forma independiente por el
  Revisor (no solo declarado por el Builder).
- `SIN CANDIDATO MOVIBLE` -- ningun bloque pasa las cinco condiciones esta pasada.
- `NO APLICA` -- el fichero ya cumple su presupuesto al medir.
- `BLOQUEADO` -- un consumidor no es ejecutable, o un turno devolvio transporte fallido sin
  sustituto vivo (declarar el perfil, nunca silencio).
- `RECHAZADO_POR_REVISOR` (propio de este prompt) -- el Builder aplico algo que el Revisor
  marco `DECISION: CHANGES` y no se resolvio en el mismo ciclo; el commit local se revierte
  (`git reset --hard` al SHA previo al Turno 2, SOLO si no hay trabajo humano intercalado) o
  se deja marcado explicitamente como pendiente, nunca se publica ni se cuenta como pasada
  aplicada.

## 5. Relacion con el bucle adversarial de ensemble_dispatch.py

Este protocolo trio (Manager/Builder/Revisor via Kilo) es DISTINTO del bucle adversarial
`ensemble_dispatch.py loop-round` usado en pasadas previas de `AGENTS.md` (commits que citan
`loop_id EXPLORATORY-dos-reglas-durables`, precedente `abceda5d`). Ambos son validos; no se
mezclan dentro del mismo turno:

- **Trio (este prompt):** rapido, un Revisor independiente por pasada, pensado para iterar
  varias pasadas seguidas sin gastar el bundle de un bucle de gobierno completo.
- **Ensemble adversarial (`ensemble_loop.md`):** mas lento, 4+ lentes independientes en
  paralelo, pensado para UNA propuesta de alto riesgo donde el Orquestador o el usuario
  tengan duda real sobre si una seccion es refutacion o narrativa forense.

Si el usuario pide explicitamente "bucle adversarial" para una pasada concreta, el
Orquestador AÑADE una ronda de `ensemble_dispatch.py loop-round` (fase `DESIGN_REVIEW`, sin
nonce) sobre el commit del Turno 2 ANTES del Turno 1.5, en vez de sustituirlo -- el Revisor
de este protocolo sigue corriendo igual.

## 6. Registro vivo

`.agent/planning/agents_md_optimization/` acumula un fichero por turno y pasada
(`pasada_<N>_manager.md`, `pasada_<N>_builder.md`, `pasada_<N>_revisor.md`,
`pasada_<N>_bitacora.md` de la Seccion 1). El Orquestador crea el directorio si no existe la
primera vez. Al declarar `SUELO`, el Orquestador anade un `RESUMEN.md` en ese mismo
directorio con la tabla completa de pasadas (candidato, SHA, % antes/despues).
