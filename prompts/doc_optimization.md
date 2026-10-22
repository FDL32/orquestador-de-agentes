---
role: orchestrator
route_kind: mantenimiento
---
# Prompt: Optimizacion de documentacion basada en evidencia (medir -> mover -> verificar)
<!-- PROMPT-SUMMARY
what: Protocolo medir -> mover -> verificar para trasladar contenido de un fichero siempre-cargado a una referencia, con guard de no-degradacion de sus consumidores.
when: Cuando el cierre transitivo de lo siempre-cargado (CLAUDE.md, AGENTS.md y sus @imports) supera cualquiera de los DOS gates por backend declarados en PASO 1 (no un % unico arbitrario).
not: NO es para anadir contenido nuevo ni para recortar prompts por longitud; hermanos: suite_optimization.md (segundos de suite) y memory_optimization.md (memoria).
-->

> **Modo:** propone y (opcionalmente) aplica UN traslado de contenido desde un fichero
> SIEMPRE-CARGADO hacia una referencia, guiado por EVIDENCIA, con disciplina CEM: NUNCA mover
> lo que un consumidor programatico consume, NUNCA mover una refutacion, NUNCA resumir la
> evidencia al moverla.

contract_id: cid-doc-optimization-v1
Skill canonica: skills/doc-optimization/SKILL.md
source_of_truth: este prompt. La skill es wrapper operativo; si divergen,
prevalece este prompt.

Hereda la filosofia de `prompts/audit_agent_output.md` (CEM v0, evidencia antes que relato,
etiquetas de evidencia) y la forma de `prompts/suite_optimization.md`, su hermano: aquel
optimiza SEGUNDOS de suite, este optimiza TOKENS de contexto. Mismo metodo, otra superficie.

Expediente de evidencia (mediciones, bucle de 3 rondas, contraejemplos completos):
`<DESTINO>/.agent/planning/PROPUESTA_doc_optimization.md` -- ruta generica por destino, no
necesariamente existente en cada uno hasta que ese destino corra su propio ciclo. El expediente
del cambio de invariante de este mismo prompt (reescritura 2026-10-18) vive en este motor en
`.agent/planning/research_context_budget/` (bundle DESIGN_REVIEW + reviews de multiples
lentes independientes). **No hace falta leer ninguno de los dos para ejecutar este
protocolo.**

## El invariante (lo unico portable)

> El cierre transitivo de `siempre-cargado` cabe DENTRO DE CADA gate por-backend de PASO 1.

**Por que ya no es un % unico de la ventana (reescrito 2026-10-18, bucle DESIGN_REVIEW
`EXPLORATORY-doc-optimization-gates`, multiples rondas con lentes independientes de Codex,
Kilo/nan y OpenCode, todas `DECISION: CHANGES`, aplicadas abajo -- expediente completo en
`.agent/planning/research_context_budget/`):** se investigo que mecanismo usa REALMENTE cada
backend para limitar `AGENTS.md`/`CLAUDE.md`, y ninguno calcula un porcentaje de su ventana de
contexto:

- **Codex CLI:** tope de bytes FIJO, constante `PROJECT_DOC_MAX_BYTES` = **32768 bytes (32 KiB)**,
  suma de TODOS los `AGENTS.md` en la jerarquia root-to-leaf, truncado SIN aviso. No escala con
  el modelo detras. Fuente: issues del repo oficial `github.com/openai/codex` (#13386, #7138,
  #6038) -- community reports, no lectura directa del codigo fuente de Codex.
  `[EVIDENCIA: 2026-10-18]`
- **Claude Code:** aviso de ARRANQUE (no bloqueo) a un umbral de **40.000 caracteres** del cierre
  de `CLAUDE.md` + sus `@imports`. Confirmado por 3 reportes de usuario independientes con el
  string literal del aviso (`"... chars > 40.0k"`) y por el changelog oficial de Claude Code, que
  confirma que el aviso "now counts instruction files together" -- es decir, el mecanismo NATIVO
  ya suma el cierre transitivo, no solo el fichero raiz. No escala con el modelo ni con la version
  (un intento de triangular una cifra mayor, 150K/v2.1.169, no encontro NINGUNA corroboracion en
  3 busquedas independientes y se descarta como no verificado). `[EVIDENCIA: 2026-10-18]`
- **OpenCode:** sin cap de tamano documentado (confirmado-negativo, pagina oficial
  `opencode.ai/docs/rules/`). **Kilo/nan** via `-f <dispatch>.md`: no autocarga nada.

Un invariante en % era una ficcion util pero no correspondia a ningun mecanismo real -- medir
contra el gate por-backend real es mas estricto Y mas verificable que dividir por una ventana que
ninguna herramienta consulta de verdad.

Relativo a proposito, pero NO por un unico porcentaje: cada backend declara su propio gate
(bytes o chars, segun su mecanismo real), y el invariante exige cumplir TODOS los que aplican
al fichero de entrada medido. Un destino pequeno y uno grande comparten los mismos gates
absolutos (no escalan con el tamano del destino, porque tampoco escalan en la herramienta real).

---

## PASO 0: declara la raiz ANTES de medir

Estampa literal, obligatoria:

    ESTADO_FRESCO: raiz=<ruta ABSOLUTA>, HEAD=<sha>, dirty=<n>, verificado=<hora>

Sin raiz declarada toda medicion posterior es inauditable, y el error lo comete el AUDITOR
(ver TRAMPA-1).

---

## PASO 1: mide, no estimes

**Dos gates absolutos, en su unidad NATIVA. Nunca conviertas una a la otra (ni via "~4
chars/token" ni ninguna otra formula): cada backend aplica su propio mecanismo real, no un %
de ventana (ver "El invariante" arriba).**

1. Resolver el cierre transitivo de `@imports` (lineas `^@`) desde el fichero de entrada del
   agente. **Contar el fichero suelto MIENTE** (TRAMPA-2).
2. **Gate Codex (bytes):** suma en BYTES de todos los `AGENTS.md` en la jerarquia root-to-leaf
   desde el cwd del agente (un destino puede tener varios; en este repo, uno solo). Limite:
   **32768 bytes**. Mide con conteo de bytes del fichero en disco (`wc -c`), nunca caracteres:
   un acento UTF-8 cuenta 2 bytes y 1 caracter, y la diferencia es real (medido: 77228 B vs
   77092 chars en este repo, 136 B de diferencia).
3. **Gate Claude Code (caracteres):** cierre transitivo en CARACTERES de `CLAUDE.md` + sus
   `@imports`. Limite: **40000 caracteres**. Mide con longitud de texto decodificado (no bytes).
4. Backends sin autocarga confirmada (Kilo/nan via `-f <dispatch>.md`) o sin cap documentado
   (OpenCode) quedan EXCLUIDOS de ambos gates: no aplican.

No existe zona gris que requiera un tokenizador real: cada gate es una cifra absoluta en su
propia unidad, no una aproximacion de tokens. La antigua regla del "4%-6% el proxy no decide"
pertenecia al invariante en % ya retirado (TRAMPA-4).

Clasificar cada fichero por **VIA DE CARGA**. La unidad es el FICHERO, nunca el directorio; un
directorio con ficheros de clases distintas se clasifica uno a uno y su total no se agrega.

| Clase | Que es | Presupuesto |
|---|---|---|
| `siempre-cargado` | entra en CADA sesion (fichero de entrada + cierre de sus `@imports` + los marcados "Siempre" en un indice de reglas) | **gates absolutos del PASO 1** (bytes para Codex, chars para Claude Code; ningun % de ventana) |
| `citado-obligatorio` | un contrato **ORDENA** leerlo entero ("lee X entero", "antes de Y, lee X") | el de la sesion que lo cita. NO es "sin tope" |
| `router-condicional` | se lee para decidir a donde ir | tope propio; **recortarlo es lo mas peligroso** |
| `referencia-bajo-demanda` | un contrato lo **OFRECE** ("ver detalle en X") | sin tope: es el DESTINO de lo que se saca |
| `generado` | lo produce un script | su tope vive en el generador; **NO editar a mano** |

**Una orden no es un ofrecimiento.** Si bastara con ser alcanzable, todo ascenderia a
`citado-obligatorio`, la clase sin tope se vaciaria y no habria destino: el protocolo se
morderia la cola.

---

## PASO 2: clasifica cada bloque por FUNCION, no por longitud

Ante match multiple, **gana la fila superior**.

| # | Funcion del bloque | Se queda? | Criterio |
|---|---|---|---|
| 1 | **Refutacion** ("esto que parece verdad, no lo es") | **SIEMPRE** | Su valor depende de la ADYACENCIA al error |
| 2 | **Prohibicion dura** (NUNCA hagas X) | **SIEMPRE** | Coste de omision asimetrico |
| 3 | **Comando operativo** (su invocacion canonica) | **SIEMPRE** | 90 % del valor en 10 % del espacio |
| 4 | **Flags condicionales y sus excepciones** | MUEVE | Al `--help` o al prompt dueno |
| 5 | **Justificacion forense** (historia, cifras del incidente) | MUEVE | Solo se necesita al investigar -- salvo fila 1 |
| 6 | **Ejemplo canonico** | EVALUA | Uno vale mil palabras; dos del mismo patron, no |
| 7 | **Contenido condicional** | MUEVE | Viola la universalidad de lo siempre-cargado |

---

## PASO 3: las CINCO condiciones. Todas, o no se mueve

**(a) CONCENTRADO:** seccion contigua de funcion unica. Contenido repartido NO se toca.

**(b) DESTINO ALCANZABLE desde donde muerde el fallo.** Un enlace solo lo ve quien lee el
fichero origen. **El destino debe ser `referencia-bajo-demanda` o `router-condicional`**:
mover a `citado-obligatorio` no es optimizar, es cambiar de bolsillo.

**(c) NO es una REFUTACION** -- ni entera ni repartida. Si otra seccion del mismo fichero lo
CITA o depende de el (`grep` del encabezado y sus terminos en el resto), no es concentrado a
efectos de (a): o se mueven las dos partes, o ninguna.

**(d) NINGUN CONSUMIDOR PROGRAMATICO consume ESE BLOQUE.** Un parser no sigue enlaces.
Procedimiento:
1. `git grep -n '<nombre-del-fichero>'` **sin filtrar por extension** (un destino puede leerlo
   desde JS, Go, un Makefile o un workflow).
2. Clasificar cada hit por tipo: codigo ejecutable, config, workflow, test, documentacion
   normativa, referencia incidental. **No descartar un hit solo por ser prosa:** una cita en
   documentacion normativa puede ser el contrato que no debe romperse.
3. Determinar el ALCANCE de cada consumidor: .lee el fichero entero, o extrae anclas?
4. Falla solo si alguno consume el bloque que quieres mover (o lee el fichero entero).

**(e) NO esta dentro de una seccion que un consumidor extraiga por ENCABEZADO.** Censar
registries de extraccion (`git grep -n 're.compile(r"\^##'` y equivalentes). Si cae dentro de
una seccion registrada, **falla por defecto**; unica via de continuar: el PASO 4 con
before/after de la salida real (ver TRAMPA-3).

---

## TRAMPAS VERIFICADAS (aprendizajes con evidencia; no re-descubrir)

### TRAMPA-1: la medicion MIENTE si no declaras la raiz
El mismo `CLAUDE.md` mide **35** lineas en el motor, **43** en un destino y **84** en otro.
Son TRES ficheros distintos con el mismo nombre. Una cifra sin raiz no es auditable.
`[EVIDENCIA: 2026-09-19, wc -l en dos raices + reporte de una tercera]`

### TRAMPA-2: contar el fichero SUELTO miente cuando hay `@import`
`CLAUDE.md` = 35 lineas parece holgado; su `:3` es `@AGENTS.md` = 664. El siempre-cargado real
es **699** lineas. Un protocolo que mida el fichero raiz da verde a ese caso. **Cuenta los
`@import` reales (`^@`), no toda mencion de un fichero: una referencia en prosa ("if X exists,
use it as a map") es otra via de carga.**
`[EVIDENCIA: 2026-09-19, grep '^@' + wc -l]`

**Nota de vigencia:** la cifra original de esta trampa ("15.402 tokens, 7,70 % de 200K, 1,54x
su presupuesto") usaba el % de ventana ya retirado (ver "El invariante" arriba) -- no es un
criterio vigente, aunque la leccion de contar el `@import` real sigue aplicando igual contra
los gates absolutos de PASO 1 (bytes/Codex, chars/Claude Code).

### TRAMPA-3: "0 lineas perdidas" es un CONTEO, no un guard
Sustituir el cuerpo de una seccion registrada por un puntero deja el fichero mas corto, el
enlace funcionando y **los tests verdes** -- mientras el consumidor recibe un 95 % menos.
Medido contra el parser real: seccion intacta **1553 chars** -> con puntero **73 chars**, y
**NO lanza excepcion** (el fail-closed solo cubre "encabezado ausente", no "seccion vacia").
Ese bloque pasaba (a), (b), (c) y (d). **Verifica la SALIDA del consumidor, no el conteo.**
`[EVIDENCIA: 2026-09-19, probe contra hermes_build_context_bundle.py con copia mutada]`

### TRAMPA-4: dividir CHARS por una ventana declarada en TOKENS infla el % ~4x `[SUPERADA -- ver "El invariante" arriba]`
**Nota de vigencia:** el invariante en % de ventana que esta trampa discute YA NO ES el
mecanismo vigente (PASO 1 mide ahora dos gates absolutos, bytes y caracteres, sin ningun %).
La evidencia de ABAJO sigue siendo historicamente valida (el bug ocurrio, las cifras se
inflaron 4x) pero su remedio ("divide tokens_proxy por la ventana en tokens") ya no aplica: no
lo repliques en PASO 1 nuevo.

Dos pasadas reales de `agents_md_optimization_4layer_loop.md` (2026-10-17/18) calcularon el %
como `chars_totales / 200000` en vez de `tokens_proxy / 200000`, pese a que la "ventana
efectiva de 200K" esta declarada en TOKENS (el contexto real de Claude). Como ambos numeros
comparten el mismo factor de conversion (~4 chars/token), el error no rompe la COMPARACION
entre pasadas sucesivas (la tendencia es real), pero SI infla el % absoluto ~4x: pasada 1
reporto 39.92 % cuando la cifra correcta (`tokens_proxy/200000`) era **9.98 %**; pasada 2
reporto 38.55 % cuando la correcta era **9.64 %**. El invariante del 5 % se comparaba contra
una cifra 4x mas alta de la real, narrando una "crisis" ~4x peor que la medida honesta.
**Verifica la UNIDAD del denominador antes de dividir, no solo su valor.**
`[EVIDENCIA: 2026-10-18, pasada_1_manager.md mediciones pasada 1 y 2, recalculo manual]`

---

## PASO 4: aplica CON before/after y GUARD DE NO-DEGRADACION

1. **Medir ANTES:** lineas/chars del fichero y, por cada consumidor censado en (d)/(e),
   EJECUTARLO y guardar su salida.
2. **Aplicar** el traslado minimo. **NO resumir al mover:** comprimir "para que quepa" destruye
   el dato forense (clase CEM `B fuga de estado`).
3. **Medir DESPUES:** mismo conteo y mismos consumidores.
4. **GUARD (obligatorio):** la salida de cada consumidor debe ser IGUAL, o su diferencia
   justificada bloque a bloque. Si la seccion extraida encoge, el traslado esta estripando
   contexto aunque el origen conserve un puntero.
5. **Si no puedes EJECUTAR el consumidor, no puedes mover el bloque.** No hay tercera via.

---

## PASO 5: barrera o deuda declarada

En orden de preferencia:

1. **Deuda declarada** con ticket dueno y criterio de salida. Nunca silencio. Si el fichero
   supera MAS DE UN gate (p.ej. Codex Y Claude Code a la vez), la deuda declara CADA exceso por
   separado con su propio recibo de medicion -- una deuda que solo cubre uno de los gates deja
   al otro en silencio, violando este mismo paso.
   - **Via nombrada para `repo_motor` code-only (sin `AGENT_PROJECT_ROOT`, sin
     `.agent/collaboration/backlog.md` vivo, sin `motor_destination_link.json`):** no existe
     ticket real que asignar. La deuda se materializa como follow-up TRACKED en
     `docs/followups/<slug>-followup.md` (formato ya establecido, ver
     `docs/followups/anti-mangling-guard-followup.md`), con `ESTADO_FRESCO`, el recibo de
     CADA gate en exceso y "requiere decision del usuario para abrir WP". **Sin ese artefacto,
     no hay deuda: hay silencio.** Esta via NO sustituye el requisito de ticket dueno en
     sesiones con backlog operativo disponible -- ahi aplica la regla general sin excepcion.
     `[DECIDIDO: 2026-10-18, bucle DESIGN_REVIEW tras rechazar una declaracion inline sin
     owner/trigger/superficie -- ver `docs/followups/agents-md-over-quota-followup.md` como
     primera instancia.]`
2. **Tope duro**: SOLO para ficheros `generado`, aplicado **en el script generador** (editar el
   fichero lo prohibe el non-goal), y nunca sin procedimiento de subida: quien lo sube (el
   operador, jamas el agente), con que evidencia (el cierre transitivo re-medido contra CADA
   gate aplicable) y donde queda el rastro (fecha y motivo).

Un cap sobre un fichero escrito a mano solo puede FALLAR el commit, y la salida mas barata ante
un bloqueo legitimo es subir el numero: en tres meses la barrera es cosmetica. Por eso el WARN
va primero. **El guard que crees se cablea en el MISMO commit** (`pre-commit` o `prepush_check`)
o se declara como deuda: un guard huerfano rompe `scripts/check_guard_wiring.py`.

---

## Non-goals (duros)

- NO recortar `router-condicional` por longitud: su tamano es su funcion.
- NO editar a mano ficheros `generado`.
- NO resumir la evidencia al moverla. El PASO 2 decide SI se mueve; este non-goal solo
  gobierna COMO. Un bloque marcado "SIEMPRE se queda" no se resume tampoco.
- NO usar `@import` para contenido condicional ni para eludir el presupuesto: un `@import`
  SUMA al presupuesto del importador.
- NO optimizar sin declarar la raiz (PASO 0).

---

## Salida

Un informe corto con:

1. La estampa `ESTADO_FRESCO`.
2. Tabla de ficheros medidos: clase, cierre transitivo (bytes y caracteres), exceso sobre cada
   gate aplicable (p.ej. "2,36x Codex", "1,98x Claude Code").
3. Por cada bloque candidato: su fila del PASO 2 y el veredicto de las CINCO condiciones,
   nombrando la letra que falla si no procede.
4. Si se aplico: before/after + la salida de cada consumidor antes y despues.
5. La barrera del PASO 5 (guard WARN, deuda con ticket dueno, o la via nombrada de follow-up
   tracked en `repo_motor` code-only).

**Estados terminales validos, todos legitimos:**

- `APLICADO` -- con su guard de no-degradacion.
- `SIN CANDIDATO MOVIBLE` -- ningun bloque pasa las cinco condiciones.
- `NO APLICA` -- el fichero ya cumple TODOS los gates aplicables.
- `BLOQUEADO` -- un consumidor no es ejecutable, o no se puede medir el gate aplicable (bytes/caracteres del cierre transitivo).

**Concluir "aqui no hay nada que recortar" es un RESULTADO, no una corrida fallida.** Sin esta
clausula, un agente queda sesgado a recortar algo para justificar la corrida.

## Restriccion dura

- SOLO se propone y aplica UN fichero por corrida. No un sweep.
- **SUELO:** alcanzados TODOS los gates aplicables, el protocolo NO SE APLICA MAS a ese fichero.
  El objetivo es el invariante, no el minimo. Sin suelo, diez corridas legitimas erosionan un
  fichero por mil cortes, cada corte auditable.
- Ante duda entre "movible" y "adyacente al error": es adyacente -> **NO mover**.
- La evidencia manda sobre la intuicion y sobre la apariencia de longitud.
