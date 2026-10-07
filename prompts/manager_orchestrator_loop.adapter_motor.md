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
nucleo_sha256: 335c0854073261de747e409f75b3084bad5195cd52f63ce1310987900fe0b6eb

Este documento es el ADAPTADOR del motor `orquestador_de_agentes` al NUCLEO portable
`prompts/manager_orchestrator_loop.md` (contrato `cid-manager-orchestrator-loop-v1`,
sha256 `335c0854073261de747e409f75b3084bad5195cd52f63ce1310987900fe0b6eb`). No gobierna:
traduce. Si algo de aqui diverge del nucleo, prevalece el nucleo.

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
| LECTOR_FS | CLI Kilo directo como agente con filesystem (canal nan-FS); Codex como lente final con ficheros por `loop-round` con bundle de FICHEROS | `prompts/builder_invocation_contract.md` seccion 1; `python scripts/ensemble_dispatch.py loop-round --profile <perfil-agent> --content-file <bundle>` | sin verificador no hay bucle de GOBIERNO, solo EXPLORATORIO |
| LENTE_TEXTO | lentes de canal `api` por `loop-round` con bundle autocontenido, contrato por contenido | `python scripts/ensemble_dispatch.py loop-round --profile <perfil-api> --content-file <bundle>` | el bucle sigue con lectores; se declara |
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
nivel degradado es `prompts/manager_orchestrator_loop.profile_motor.json`; se valida
contra `SCHEMA: perfil` del nucleo antes de lanzar nada. Un perfil que no declare un
lector con ficheros hace que la revision sea EXPLORATORIA, no de GOBIERNO.
