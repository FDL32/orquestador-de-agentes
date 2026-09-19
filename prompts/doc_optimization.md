# Prompt: Optimizacion de documentacion basada en evidencia (medir -> mover -> verificar)

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
`<DESTINO>/.agent/planning/PROPUESTA_doc_optimization.md`. **No hace falta leerlo para
ejecutar este protocolo.**

## El invariante (lo unico portable)

> El cierre transitivo de `siempre-cargado` cabe en **<5 % de la ventana efectiva**.

Relativo a proposito: un destino pequeno y uno grande no comparten techo de LINEAS, pero si
ese porcentaje. El numero de lineas es una proyeccion local, nunca un umbral importado.

---

## PASO 0: declara la raiz ANTES de medir

Estampa literal, obligatoria:

    ESTADO_FRESCO: raiz=<ruta ABSOLUTA>, HEAD=<sha>, dirty=<n>, verificado=<hora>

Sin raiz declarada toda medicion posterior es inauditable, y el error lo comete el AUDITOR
(ver TRAMPA-1).

---

## PASO 1: mide, no estimes

1. Resolver el cierre transitivo de `@imports` (lineas `^@`) desde el fichero de entrada del
   agente. **Contar el fichero suelto MIENTE** (TRAMPA-2).
2. Sumar chars del cierre; tokens por proxy de ~4 chars/token, declarado COMO PROXY.
3. Calcular el % sobre la ventana efectiva y compararlo con el 5 %.

**Si el resultado cae entre ~4 % y ~6 %, el proxy NO decide:** mide con tokenizador real antes
de actuar.

Clasificar cada fichero por **VIA DE CARGA**. La unidad es el FICHERO, nunca el directorio; un
directorio con ficheros de clases distintas se clasifica uno a uno y su total no se agrega.

| Clase | Que es | Presupuesto |
|---|---|---|
| `siempre-cargado` | entra en CADA sesion (fichero de entrada + cierre de sus `@imports` + los marcados "Siempre" en un indice de reglas) | **<5 % de la ventana** |
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
es **699** -- 15.402 tokens, **7,70 %** de 200K, 1,54x su presupuesto. Un protocolo que mida el
fichero raiz da verde a ese caso. **Cuenta los `@import` reales (`^@`), no toda mencion de un
fichero: una referencia en prosa ("if X exists, use it as a map") es otra via de carga.**
`[EVIDENCIA: 2026-09-19, grep '^@' + wc -l]`

### TRAMPA-3: "0 lineas perdidas" es un CONTEO, no un guard
Sustituir el cuerpo de una seccion registrada por un puntero deja el fichero mas corto, el
enlace funcionando y **los tests verdes** -- mientras el consumidor recibe un 95 % menos.
Medido contra el parser real: seccion intacta **1553 chars** -> con puntero **73 chars**, y
**NO lanza excepcion** (el fail-closed solo cubre "encabezado ausente", no "seccion vacia").
Ese bloque pasaba (a), (b), (c) y (d). **Verifica la SALIDA del consumidor, no el conteo.**
`[EVIDENCIA: 2026-09-19, probe contra hermes_build_context_bundle.py con copia mutada]`

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

1. **Guard de clase en WARN**, que reporte el % consumido sin bloquear.
2. **Deuda declarada** con ticket dueno y criterio de salida. Nunca silencio.
3. **Tope duro**: SOLO para ficheros `generado`, aplicado **en el script generador** (editar el
   fichero lo prohibe el non-goal), y nunca sin procedimiento de subida: quien lo sube (el
   operador, jamas el agente), con que evidencia (el cierre transitivo re-medido, con su %) y
   donde queda el rastro (fecha y motivo).

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
2. Tabla de ficheros medidos: clase, cierre transitivo, % sobre la ventana.
3. Por cada bloque candidato: su fila del PASO 2 y el veredicto de las CINCO condiciones,
   nombrando la letra que falla si no procede.
4. Si se aplico: before/after + la salida de cada consumidor antes y despues.
5. La barrera del PASO 5, o la deuda con su ticket dueno.

**Estados terminales validos, todos legitimos:**

- `APLICADO` -- con su guard de no-degradacion.
- `SIN CANDIDATO MOVIBLE` -- ningun bloque pasa las cinco condiciones.
- `NO APLICA` -- el fichero ya cumple su presupuesto.
- `BLOQUEADO` -- un consumidor no es ejecutable, o falta la ventana efectiva para calcular el %.

**Concluir "aqui no hay nada que recortar" es un RESULTADO, no una corrida fallida.** Sin esta
clausula, un agente queda sesgado a recortar algo para justificar la corrida.

## Restriccion dura

- SOLO se propone y aplica UN fichero por corrida. No un sweep.
- **SUELO:** alcanzado el presupuesto, el protocolo NO SE APLICA MAS a ese fichero. El objetivo
  es el invariante, no el minimo. Sin suelo, diez corridas legitimas erosionan un fichero por
  mil cortes, cada corte auditable.
- Ante duda entre "movible" y "adyacente al error": es adyacente -> **NO mover**.
- La evidencia manda sobre la intuicion y sobre la apariencia de longitud.
