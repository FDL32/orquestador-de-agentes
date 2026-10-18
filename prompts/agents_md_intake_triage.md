---
role: manager
route_kind: mantenimiento
---
# Prompt: Triaje de intake de contenido nuevo a AGENTS.md/CLAUDE.md
<!-- PROMPT-SUMMARY
what: Protocolo de admision (antes de escribir) para decidir si una regla/contenido NUEVO va a la cuspide siempre-cargada de AGENTS.md/CLAUDE.md, a un modulo de dominio o a docs/protocol/, con barrido anti-duplicado, clasificacion por funcion/clase y gate de presupuesto.
when: Cuando un agente va a anadir contenido nuevo a AGENTS.md, CLAUDE.md o un modulo de .agent/rules/common/ en el motor o en un repo_destino, ANTES de escribirlo.
not: NO decide el destino final del cierre de sesion (eso lo hace prompts/orchestrator_session_close_full_audit.md); NO es el backlog_triage general (prompts/backlog_triage.md tria TICKETS, no documentacion siempre-cargada); NO sustituye el barrido de prompts/memory_upload.md para memoria (ese es aprendizajes/memoria, dominio distinto de reglas operativas y documentacion).
-->

contract_id: cid-agents-md-intake-triage-v1
Skill canonica: skills/agents-md-intake-triage/SKILL.md
source_of_truth: este prompt. La skill es wrapper operativo; si divergen,
prevalece este prompt (X-09: skill apunta, prompt gobierna).

> **Modo:** GATE de admision ANTES de escribir. Este prompt NO escribe en
> AGENTS.md/CLAUDE.md ni en un modulo: decide SI entra, DONDE y CON QUE
> compensacion, y exige declararlo. Hereda la disciplina CEM (evidencia antes
> que relato) y la via de carga de `prompts/doc_optimization.md`.

## Alcance y no-confusion con los hermanos (leer antes de ejecutar)

Este protocolo se apoya en tres contratos ya existentes, citados por
referencia (X-09: NO se re-declaran aqui sus criterios; se nombra el prompt
dueno y se aplica su procedimiento):

1. Barrido anti-duplicado: `prompts/memory_upload.md` "Procedimiento de barrido
   anti-duplicado (obligatorio)" y `prompts/backlog_triage.md` Fase 0.ante.
2. Clasificacion por funcion y clase: `prompts/doc_optimization.md` PASO 1 y
   PASO 2.
3. Gate mecanico de presupuesto: `prompts/doc_optimization.md` PASO 1 (gates
   absolutos por-backend: bytes Codex, caracteres el cierre de
   `CLAUDE.md`+`@imports`).

Estos tres gobiernan superficies DISTINTAS y no se sustituyen entre si:
`memory_upload.md` gobierna MEMORIA (aprendizajes), `backlog_triage.md`
gobierna TICKETS, `doc_optimization.md` gobierna EXTRACCION de contenido ya
dentro de lo siempre-cargado. ESTE prompt gobierna la ADMISION de contenido
NUEVO a la documentacion operativa. Donde un paso coincide con un dueno ya
existente, este prompt REMITE al dueno, no lo copia.

## PASO 0: declara la raiz ANTES de medir

Estampa literal obligatoria (mismo contrato que `doc_optimization.md` PASO 0,
heredada de TRAMPA-1: una medicion sin raiz no es auditable):

    ESTADO_FRESCO: raiz=<ruta ABSOLUTA>, HEAD=<sha>, dirty=<n>, verificado=<hora>

Resuelve primero la topologia: si es un `repo_destino`, las superficies a barrer
viven en el destino (`.agent/rules/common/`, `.claude/rules/` del workspace); el
motor aporta los `prompts/` duenos. No asumas rutas literales.

## PASO 1: barrido anti-duplicado (obligatorio, antes de clasificar)

Aplica el procedimiento de `prompts/memory_upload.md` a la documentacion
operativa. Reglas duenas (NO las reinventes aqui): barre TODAS las superficies,
nunca una por vez; lectura COMPLETA de cada candidato proximo, NUNCA descartar
por el titulo; `find_similar_signals.py` es senal, jamas veredicto.

Superficies a barrer (las tres, siempre, por el contenido de la regla nueva):

- (a) la cuspide siempre-cargada: `AGENTS.md` y `CLAUDE.md` (+ su cierre
  transitivo de `@imports`, ver `doc_optimization.md` TRAMPA-2: contar el
  fichero suelto miente).
- (b) TODOS los modulos de dominio: `.agent/rules/common/*.md` y
  `.claude/rules/*.md`.
- (c) la base: `docs/protocol/*.md`.

Un grep por keyword NO basta para el veredicto: hay que LEER ENTERO el
candidato mas proximo (misma leccion que `memory_upload.md`: una regla
abstracta y un caso concreto pueden ser el mismo contenido con titulos
distintos). Ayuda mecanica opcional (no sustituye la lectura):

    python <MOTOR_ROOT>/scripts/find_similar_signals.py --text-file <candidato.txt> \
        --archive <...>   # solo si quieres vecinos semanticos; senal, no veredicto

Veredicto del PASO 1, obligatorio y con evidencia (`commit:`/`path:` o
"leido entero, no existe"):

- DUPLICADO: la regla YA EXISTE en una de las superficies -> este prompt NO la
  duplica. Se actualiza/fusiona en su ubicacion existente (re-aplicar el PASO 2
  a esa ubicacion) y se cierra el intake aqui.
- SIN DUPLICADO: no existe (declarado con la lectura completa hecha) -> sigue.

## PASO 2: clasifica por FUNCION y por CLASE (decide el destino por defecto)

Remite a `prompts/doc_optimization.md` por los criterios (no los copies):

- FUNCION (filas #1-#7 de PASO 2): decide si el contenido nuevo es una
  directiva-que-se-queda (refutacion / prohibicion dura / comando operativo:
  filas #1-#3) o contenido-que-se-mueve (flags condicionales, justificacion
  forense, contenido condicional: filas #4, #5, #7; #6 evalua).
- CLASE (las 5 de PASO 1: `siempre-cargado` / `router-condicional` /
  `referencia-bajo-demanda` / `citado-obligatorio` / `generado`): decide DONDE
  aterriza por defecto. El destino natural de lo nuevo es `referencia-bajo-
  demanda` (base) o un modulo de dominio (capa intermedia), NO la cuspide.

## PASO 3: regla de aterrizaje por defecto (normativa propia de este protocolo)

Contenido NUEVO de este prompt (Seccion 4 de
`propuesta_restructuracion_arquitectonica.md`), no re-declaracion de un
hermano. Copiar/adaptar, no contradecir:

- Ninguna adicion nueva entra directa a la cuspide de `AGENTS.md`. El destino
  por defecto de cualquier regla/contenido nuevo es un modulo de dominio (capa
  intermedia) o `docs/protocol/` (base), SALVO que sea una directiva
  verdaderamente universal (NUNCA/SIEMPRE con blast radius para TODA sesion,
  sin excepcion de dominio) Y quepa en una linea.
- Crecimiento presupuesto-neutral de la cuspide: si una directiva nueva es
  genuinamente universal y debe entrar en la cuspide, su coste en bytes debe
  compensarse moviendo o condensando otra directiva existente de la cuspide;
  nunca se permite que la cuspide crezca sin una compensacion EXPLICITA. Evita
  que la piramide reproduzca, con una sesion de retraso, el problema que la
  motivo.

## PASO 4: mide el gate ANTES y DESPUES de decidir el destino

Reutiliza los comandos de `prompts/doc_optimization.md` PASO 1 (los numeros de
gate duenos viven alli: bytes para Codex, caracteres para el cierre Claude
Code; no se re-declaran aqui). Medir ANTES y DESPUES para que el agente vea el
impacto real de la adicion/compensacion:

- Cuspide Codex (bytes): `wc -c AGENTS.md` (y en un destino, la jerarquia
  root-to-leaf que Codex suma -- ver "El invariante" del prompt dueno).
- Cuspide Claude Code (caracteres): longitud de texto decodificado del cierre
  transitivo `CLAUDE.md` + sus `@imports` (lineas `^@`), no del fichero suelto.
- Modulo de dominio / `docs/protocol/`: sin gate de presupuesto siempre-cargado
  (no entran en cada sesion); su medida es de cordura, no de gate.

Regla de decision: si el destino es la cuspide, la adicion MAS su compensacion
DEBE dejar ambos gates en <=1.0x respecto de su estado actual (no puede
empeorar el ratio). Si el destino es modulo o base, registra el gate de la
cuspide SIN variacion (intake presupuesto-neutral por construccion).

## PASO 5: DECLARACION EXPLICITA obligatoria (el triaje se declara, nunca se asume)

Mismo patron que "declara el destino antes de escribir" de
`prompts/memory_upload.md`. Toda PR/commit que toque `AGENTS.md`, `CLAUDE.md` o
un modulo de `.agent/rules/common/` (o `.claude/rules/`) debe declarar, en el
propio mensaje de commit o en `execution_log.md`:

1. El resultado del barrido (PASO 1): DUPLICADO (con la `path:` del hit leido
   entero) o SIN-DUPLICADO (con la superficie barrida y que se leyo completo).
2. La clasificacion aplicada (PASO 2): fila de FUNCION (#1-#7) y CLASE
   destino.
3. El veredicto de aterrizaje (PASO 3): cuspide (con su compensacion explicita)
   o modulo/base.
4. La medida del gate antes/despues (PASO 4), si el destino fue la cuspide.

Sin esta declaracion, el intake NO esta completado: es gobierno declarativo y
queda como el hueco de ENFORCEMENT que las lentes senalaron (Seccion 5 hallazgo
#3). Este prompt convierte ese hueco en un recibo obligatorio en el commit, no
en un gate automatico nuevo.

## Fuera de alcance declarado (no implementar aqui)

- El gate MECANICO de crecimiento de cuspide (hook pre-commit que mide el delta
  de bytes y bloquea sin compensacion declarada) es WARN-vs-BLOCK decision PENDIENTE
  del usuario (Seccion 9 punto 3 de la propuesta; Seccion 8 hallazgo #4). Este
  prompt lo MENCIONA como deuda pendiente con dueno, pero NO implementa ningun
  gate automatico nuevo.
- La piramide en si (reordenar AGENTS.md en cuspide+modulos+base) tampoco se
  ejecuta aqui: este prompt gobierna SOLO la ADMISION de contenido nuevo, no la
  reestructuracion del contenido existente (eso es `doc_optimization.md` y la
  decision de piramide).

## Salida

Un informe corto con:

1. La estampa `ESTADO_FRESCO`.
2. Veredicto del PASO 1 (DUPLICADO / SIN-DUPLICADO) con la evidencia de lectura
   completa de cada superficie barrida.
3. Clasificacion del PASO 2 (fila de funcion + clase destino), citando las
   filas/clases por nombre, no re-declarando la tabla.
4. Veredicto de aterrizaje del PASO 3 (cuspide con compensacion / modulo / base).
5. Medida del gate antes/despues del PASO 4 si aplica a cuspide.
6. La declaracion explicita del PASO 5 tal como quedara en el commit.

**Estados terminales validos:**
- `NO_ENTRA` -- es duplicado de una regla existente (PASO 1 DUPLICADO).
- `A_MODULO` / `A_REFERENCIA` -- destino capa intermedia o base.
- `A_CUSPIDE_COMPENSADO` -- entra a la cuspide con su compensacion explicita y
  gate <=1.0x.
- `BLOQUEADO` -- no se puede medir el gate aplicable o no se resuelve la
  topologia del destino.

## Restriccion dura

- NO escribe `AGENTS.md`/`CLAUDE.md`/modulos: propone el destino y exige la
  declaracion. Quien escribe es el Builder tras este triaje.
- NO re-declara cifras de gate ni tablas de los prompts duenos: remite a ellos
  (X-09).
- NO implementa el gate automatico WARN-vs-BLOCK (decision del usuario pendiente).
- Un barrido que no leyo completo el candidato mas proximo NO es barrido: es el
  falso-verde que `memory_upload.md` documenta (4 duplicados declarando "busque
  duplicados").
