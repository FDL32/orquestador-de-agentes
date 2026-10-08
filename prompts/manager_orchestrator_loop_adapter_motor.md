---
role: orchestrator
route_kind: modulo
---
# Adaptador del motor para el nucleo del proceso Manager-Builder
<!-- PROMPT-SUMMARY
what: Adaptador del MOTOR al nucleo portable manager_orchestrator_loop.md: traduce cada capacidad del nucleo a los comandos y ficheros REALES de este repositorio, fija los minimos por tipo de entrega y declara la diferencia de identidad (D2).
when: Cuando un Manager orquesta bucles de revision adversarial sobre este motor (backlog, prompts, scripts, agentes) y necesita saber con que comando y fichero reales se cubre cada capacidad del nucleo.
not: NO redefine roles, estados, reglas de validez ni esquemas: eso vive en prompts/manager_orchestrator_loop.md y, si divergen, prevalece el nucleo. NO es el procedimiento de despacho de una lente (prompts/ensemble_loop.md) ni el contrato de invocacion de un Builder real (prompts/builder_invocation_contract.md).
-->

contract_id: cid-manager-orchestrator-loop-adapter-motor-v1
implements: cid-manager-orchestrator-loop-v1
nucleo: prompts/manager_orchestrator_loop.md
nucleo_sha256: 909543817393de016021657c85fa298fd1db768c5702f2aff86bde93df1bd19b

Este documento es el ADAPTADOR del motor `orquestador_de_agentes` al NUCLEO portable
`prompts/manager_orchestrator_loop.md` (contrato `cid-manager-orchestrator-loop-v1`,
sha256 `909543817393de016021657c85fa298fd1db768c5702f2aff86bde93df1bd19b`). No gobierna:
traduce. Si algo de aqui diverge del nucleo, prevalece el nucleo.

## 0. Como arrancar (recibiste este documento y no sabes por donde empezar)

Este adaptador es una TABLA DE CAPACIDADES, no un prompt de tarea. Si te lo han pegado
sin un objetivo adjunto, el documento no te dice que hacer -- te dice con que comando
real se cubre cada pieza una vez que ya sabes que vas a montar un bucle. Dos sintomas
medidos (2026-10-08, sesion fria + prompt pegado sin tarea; sesion con tarea que gasto
~350k tokens explorando antes de lanzar nada):

1. **Declara el objetivo con esta forma estandar ANTES de cualquier otra cosa** (el
   humano la rellena, o el agente se la pide con estas tres lineas exactas si faltan):

       OBJETIVO: <una frase: que decision o documento debe producir/auditar el bucle>
       ALCANCE: <fichero(s) o ruta(s) concreta(s) sobre los que corre, o "nuevo documento">
       ENTREGABLE: <que archivo/fila/commit debe existir al cerrar el bucle>

   Sin estas tres lineas, la seccion 2 de este adaptador no se puede instanciar: cada
   fila de la tabla necesita saber QUE se esta revisando. **No empieces a explorar el
   repo** (censar perfiles, localizar `kilo.exe`, leer memoria completa) mientras falte
   cualquiera de las tres -- pidelas primero.
2. **Si el humano NO tiene nada concreto que encomendar** ("por donde empiezo", "mira a
   ver que hace falta"): no te quedes parado pidiendo mas detalle indefinidamente. Cae a
   **sesion generica**: usa `skills/backlog-triage/SKILL.md` (modo lectura, propone
   candidatos del backlog vivo) o, si el objetivo es revisar la salud del propio sistema
   de bucles, `prompts/audit_complete_motor_destination.md`. El resultado de cualquiera de
   las dos rellena las tres lineas de OBJETIVO/ALCANCE/ENTREGABLE de arriba antes de
   lanzar ninguna ronda -- la sesion generica PRODUCE el objetivo, no lo sustituye.
3. **Con objetivo ya declarado:** NO releas `builder_invocation_contract.md` ni
   `ensemble_loop.md` enteros para recordar el comando -- ya estan resueltos ahi.
   - Para lanzar un **Builder real con filesystem** (leer/escribir/implementar, no dar
     veredicto): el comando canonico completo (Kilo CLI, flags, orden exacto) vive en
     `prompts/builder_invocation_contract.md` seccion 1. Los perfiles `nan` ya validados
     (`challenger_nan_deepseek_flash`, `challenger_nan_qwen`, `challenger_nan_qwen_flash`,
     `challenger_nan_glm_flash`, `challenger_nan_gemma`, `challenger_nan_mimo_flash`) estan
     en `.agent/config/agents.json` -> `ensemble_profiles`; no hace falta localizar el
     ejecutable a mano, la config ya declara `backends.kilo.executable`.
   - Para lanzar una **ronda de revision adversarial** (veredicto corto, no implementacion):
     el comando completo vive en `prompts/ensemble_loop.md` seccion 3.4.
   - La distincion entre ambos (cuando usar cada uno) es la tabla de
     `prompts/builder_invocation_contract.md` seccion 0 -- leela si dudas cual aplica,
     no inventes un tercer mecanismo.
4. **Si el humano da un objetivo pero es ambiguo** ("optimiza el motor", "mejora la
   velocidad", "revisa los tests"): no lo tomes por concreto (rellenando
   OBJETIVO/ALCANCE/ENTREGABLE al azar) ni lo descartes como vacio (cayendo al
   fallback del punto 2). Pide aclaracion con UNA pregunta especifica que
   desambigue la incognita mas critica. Si tras dos intentos de aclaracion sigue
   sin concretarse, cae al fallback de sesion generica del punto 2.
5. **No localices rutas que ya estan declaradas.** Antes de un `find`/`grep` recursivo
   para localizar un ejecutable o un fichero de config, comprueba si `agents.json` o este
   adaptador ya lo nombran. La exploracion cuesta contexto que el bucle necesita para las
   rondas reales.

## 1. Que cubre este adaptador y que no

El nucleo define, en terminos GENERALES, capacidades, roles, validez de un bucle,
estados, plantillas y esquemas. Este adaptador hace UNA cosa: decir, para cada
capacidad de su seccion 3, con que comando o fichero REAL de este repositorio se
cubre hoy, y cual es su nivel degradado. Las rutas relativas sin `<destino>` son del
MOTOR (`<motor>/...`); pasa `--project-root <destino>` a los comandos que operan
sobre el estado del destino.

## 2. Tabla de capacidades (una fila por capacidad del nucleo, seccion 3)

| Capacidad | Como la cubre este motor | Comando o fichero | Nivel degradado |
|---|---|---|---|
| LECTOR_FS | CLI Kilo directo como agente con filesystem (canal nan-FS); Codex como lente final con ficheros por `loop-round` con bundle de FICHEROS | `prompts/builder_invocation_contract.md` seccion 1; comando completo en `prompts/ensemble_loop.md` seccion 3.4 | sin verificador no hay bucle de GOBIERNO, solo EXPLORATORIO |
| LENTE_TEXTO | lentes de canal `api` por `loop-round` con bundle autocontenido, contrato por contenido | comando completo en `prompts/ensemble_loop.md` seccion 3.4 | el bucle sigue con lectores; se declara |
| EJECUTOR | CLI Kilo directo como Builder real; o el propio Manager en modo implementador=manager del nucleo (seccion 9) | `prompts/builder_invocation_contract.md`; nucleo seccion 9 | modo implementador=manager (nucleo, seccion 9) |
| EVIDENCIA | git: foto antes/despues del arbol, commit o revert | `git -C <destino> status --porcelain`; `git -C <destino> diff` | sin VCS: sha256 por fichero de las rutas declaradas |
| REGISTRO_TRABAJO | backlog vivo del destino, validado por el gate de contrato | `<destino>/.agent/collaboration/backlog.md`; `python scripts/check_backlog_contract.py --project-root <destino>` | una tabla versionada |
| REGISTRO_RONDAS | scorecard JSONL del destino, una fila por ronda | `<destino>/.agent/runtime/ensemble/scorecard.jsonl`; `python scripts/ensemble_dispatch.py leaders --project-root <destino>` | un JSONL local |
| BARRERAS | gates obligatorios por tipo de entrega | `python scripts/check_loop_execution.py` (minimos: su funcion `min_distinct_for`); `python scripts/prepush_check.py` | se declaran los que faltan; ningun cierre los da por pasados |
| CANAL_SESIONES | buzon de tareas del destino con la norma de reclamo | `<destino>/.agent/collaboration/backlog_inbox/` | el USUARIO hace de bus (riesgo declarado) |
| DECISIONES | registro de decisiones del USUARIO | `docs/decisions/` | un fichero por ciclo |
| IDENTIDAD | registro de identidad de lentes en la config del motor | `.agent/config/agents.json` -> `ensemble_registry.backend_keys` | el lanzador anota proveedor y modelo de cada respuesta |
| ESCALADO | chat con el USUARIO para llevar las dos posturas cuando el bucle no converge | canal humano, sin comando | se para el ciclo y se declara |

## 3. Identidad: la diferencia D2

El nucleo (seccion 4, regla 1) cuenta IDENTIDADES (proveedor, modelo) distintas, no
claves. La barrera de este motor, `python scripts/check_loop_execution.py`, cuenta
`backend_key` DISTINTOS. El registro de identidad (`WOT-2026-088c`) aun NO garantiza
que una clave apunte a un unico modelo: la clave `BA22` aparece asociada a modelos
distintos entre el `agents.json` del motor y el del destino. Hasta que ese registro
cierre la diferencia, el Manager coteja clave -> modelo A MANO al adjudicar.

## 4. Minimos por tipo de entrega (parametros del adaptador)

Los fija el codigo, no el nucleo: `min_distinct_for` de `scripts/check_loop_execution.py`
devuelve `code` 4, `mixed` 4, `analysis` 3, `research` 2, `documentation` 2, y un tipo
desconocido cae al fallback estricto 4 (fail-closed). El numero de verificadores
independientes de gobierno es 1. Un bucle de gobierno que no alcance su minimo es
INSUFICIENTE; nunca se simula.

## 5. Perfil del motor

El perfil que declara, por capacidad, su comando, su version, una prueba de vida y su
nivel degradado es `prompts/manager_orchestrator_loop_profile_motor.json`; se valida
contra `SCHEMA: perfil` del nucleo antes de lanzar nada. Un perfil que no declare un
lector con ficheros hace que la revision sea EXPLORATORIA, no de GOBIERNO.

## 6. Cierre de bucle: un commit, un bucle anclado (N8)

La regla 7 del nucleo (un commit, un bucle anclado) se traduce asi en este motor: todos
los hallazgos ADOPTADOS de un mismo bucle se aplican en UN solo commit, y ese commit es
el ANCLA del bucle de verificacion. El nonce se emite POR COMMIT, antes del fan-out:

    python scripts/ensemble_dispatch.py emit-nonce --commit-sha <sha> --loop-id <shape> --issuer-backend-key <BA> --project-root <destino>

Las rondas se lanzan contra ese sha y la barrera `scripts/check_loop_execution.py`
acredita el commit por sus lentes. No se abre un commit por hallazgo, y un bucle cuyos
cambios quedaron repartidos en varios commits sin su ancla no se da por cerrado: la
barrera reporta 0/4. La suite canonica va al final, tras el ultimo commit.
