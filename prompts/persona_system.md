---
role: orchestrator
route_kind: modulo
---
# Prompt: vocabulario de "personas" sobre el patron de 4 capas
<!-- PROMPT-SUMMARY
what: Define "Persona-Orquestador/Manager/Revisor/Builder" (numeracion ENTERA 0/1/2/3) como la traduccion de vocabulario de una UNICA sesion Claude Code que encarna en turnos sucesivos las capas del patron de 4 capas, y fija la condicion dura de independencia que ese vocabulario no puede relajar.
when: Cuando una sola sesion Claude Code (sin Manager/Builder como procesos separados) va a ejecutar un vuelo de 4 capas, y se quiere nombrar sus turnos sucesivos sin perder la trazabilidad de quien hizo que.
not: NO redefine los modos de ejecucion (Tradicional/4capas/Intermedio, eso es agent_execution_modes.md) ni el mecanismo operativo de las 4 capas (comandos de Kilo, convencion de directorios, eso es el documento canonico de 4 capas); NO es una quinta capa ni un modo nuevo.
-->

contract_id: cid-persona-system-v1
nucleo_referenciado: prompts/agent_execution_modes.md (contract_id cid-agent-execution-modes-v1, status frozen)
documento_canonico_referenciado: PROMPT_ARRANQUE_vuelo_limpieza_backlog_4capas_20261010.md
  (vive en el repo_destino, no en este motor -- ver Nota de ubicacion abajo)
source_of_truth: este prompt SOLO para la numeracion entera de personas (Seccion 1) y la
condicion dura de independencia (Seccion 2). Los modos de ejecucion, sus señales de
seleccion y la allowlist de blast-radius-alto siguen gobernados integramente por
`agent_execution_modes.md`; el mecanismo operativo de cada capa (comandos Kilo, convencion
de `staged/WOT-<ID>/`, cadencia S/M/L) sigue gobernado integramente por el documento
canonico de 4 capas. Si algo de aqui parece contradecir cualquiera de los dos, prevalece
el documento referenciado, nunca este.

## Numeracion: ENTERA aqui, SIN TOCAR la del nucleo/documento de 4 capas

Decision explicita del usuario (2026-10-12): este documento usa numeracion ENTERA
(0/1/2/3) para las 4 personas, nunca decimales. **NO se renumera `agent_execution_modes.md`
ni el documento canonico de 4 capas** -- ambos conservan su numeracion original ("Capa 1.5"
para Revisor, "Capa 2" para Builder), exactamente igual que la decision ya tomada para
`PROPUESTA_vocabulario_roles_capas_20261011.md` v6 Seccion 9 sobre el mismo nucleo. La
Seccion 1 de aqui es la UNICA tabla de correlacion entre ambas numeraciones; no se duplica
en ningun otro documento.

## Nota de ubicacion (deuda declarada, NO resuelta por este documento)

El documento canonico de 4 capas que `agent_execution_modes.md` ya cita como fuente de la
allowlist (Seccion 3 de ese nucleo) vive HOY solo como documento de vuelo en el
`repo_destino`, nunca se promovio a prompt versionado del motor. Este documento NO resuelve
esa deuda (fuera de alcance, decision explicita 2026-10-12): solo remite a el por el nombre
de fichero, y quien lo use debe localizarlo en su `repo_destino` activo (vive tipicamente en
`.agent/planning/PROMPT_ARRANQUE_vuelo_limpieza_backlog_4capas_20261010.md` o equivalente del
vuelo en curso -- la ruta exacta varia por destino/vuelo, verificala en vivo).

## 0. Por que existe este vocabulario

El patron de 4 capas asume, por defecto, 3 actores DELEGADOS a `nan` via Kilo CLI
(Manager-nan, Revisor-nan, Builder-nan) mas Claude Code como orquestador. Cuando Claude
Code, ademas, ejecuta una o mas de esas capas EL MISMO (Persona-Manager por decision de
producto, Intermedio sobre un ticket de la allowlist, o cualquier otra razon declarada en
`agent_execution_modes.md`), necesita nombrar en que capa esta actuando en cada turno, para
que su propio registro de progreso sea legible por una sesion futura o por un auditor.
"Persona-X" es ese nombre -- nada mas.

Medido 2026-10-12 (retrospectiva de WOT-2026-098b, bucle adversarial de 4 lentes: codex,
opencode/glm, 2 nan-con-filesystem): 3 de 4 lentes independientes coincidieron en que, sin la
Seccion 2 de aqui declarada explicitamente, "persona" se lee como una conveniencia
conversacional sin consecuencias, y una sesion puede terminar revisando (Persona-Revisor) el
mismo diseño que ella misma fijo (Persona-Orquestador/Manager), sin independencia real.

## 1. Las 4 personas (numeracion entera) y su correlacion con el nucleo/documento de 4 capas

| # | Persona | Quien la ejecuta por defecto | Cuando Claude Code la hace directamente | Capa equivalente en `agent_execution_modes.md` / documento de 4 capas (NO renumerados) |
|---|---|---|---|---|
| 0 | Persona-Orquestador | Claude Code, SIEMPRE | Siempre -- no es delegable, decide y lanza las demas | Capa 0 Orquestador |
| 1 | Persona-Manager | Manager-nan (via Kilo) | Decisiones de producto/CONTRACT_GAP que Manager-nan no puede resolver por si solo; o cuando el propio vuelo decide Capa 1 no delegada | Capa 1 Manager |
| 2 | Persona-Revisor | Revisor-nan (via Kilo, modelo DISTINTO al Builder del mismo ticket) | Ticket de la allowlist de blast-radius-alto (modo Intermedio, `agent_execution_modes.md` Seccion 1); o colision de modelo sin sustituto disponible (ver Seccion 2) | Capa 1.5 Revisor |
| 3 | Persona-Builder | Builder-nan (via Kilo) | Ticket de la allowlist de blast-radius-alto (modo Intermedio) | Capa 2 Builder |

Una "persona" NO es un agente externo ni una sesion distinta: sigue siendo la MISMA sesion
Claude Code, mismo contexto, misma memoria. La independencia real para el DoD/revision la
aporta SIEMPRE el modelo `nan` delegado cuando la capa SI se delega -- nunca el cambio de
persona en si mismo. Cuando Claude Code hace de Persona-Revisor (2) sobre un ticket que ella
misma implemento como Persona-Builder (3) (Intermedio), NO hay independencia de modelo --
solo aplica cuando el propio modo Intermedio lo exige asi por diseño (`agent_execution_modes.md`
Seccion 1, regla dura de seguridad para la allowlist).

## 2. Condicion dura, no negociable

> **NUNCA el mismo agente implementa y revisa.** Si la Persona-Builder (3) y la
> Persona-Revisor (2) de un ticket resuelven al mismo modelo/backend (ambas delegadas al
> mismo `nan/<modelo>`, o ambas Claude Code sin que el modo Intermedio lo exija), sustituye
> uno de los dos ANTES de lanzar esa capa -- nunca despues de recibir el veredicto.

Esta condicion NO es nueva. Dos precedentes distintos, cada uno cubre una mitad:
`agent_execution_modes.md` Seccion 1 fija, para Intermedio, que Claude Code NUNCA delega a
Kilo ni la implementacion NI la revision de un ticket de la allowlist en la MISMA sesion
(prohibicion de delegar ambas, no una regla de "modelo distinto" entre ellas). La regla de
"modelo distinto entre quien implementa y quien revisa" vive en el documento canonico de 4
capas Seccion 1 ("Regla dura") y en `prompts/ensemble_loop.md` Seccion 3.2 "Elegir lentes"
("el mismo `backend_key` repetido NO son dos lentes") -- no en su Seccion 2 ("Una sola
puerta: loop-round"). Este documento no amplia ni relaja ninguna de las dos -- las hace
explicitas juntas en el vocabulario de "persona" para que una sesion que use ese vocabulario
no las pierda de vista.

## 3. Traza obligatoria de transicion

Cada vez que la sesion cambia de persona, añade una linea al fichero de progreso del vuelo
en curso (el que cada vuelo ya mantiene, p.ej. `PROGRESO_<vuelo>.md`) declarando la
transicion: `"Persona-X (#N) -> Persona-Y (#M) para <ticket>, delega a <backend/modelo o
'Claude Code directamente'>"`. Esto NO es ceremonia: sin esta traza, el estado real de un
ticket puede quedar invisible para una sesion futura tras un CONTRACT_GAP o una
interrupcion (medido 2026-10-12, WOT-2026-098b: la ausencia de esta traza dejo el canon de
un ticket -- `STATE.md`, `work_plan.md`, `backlog.md`, `execution_log.md` -- contradiciendo
el commit real durante horas).

## 4. Que NO decide este documento

- Si un vuelo debe usar 4 capas, Intermedio o Tradicional -- eso es `agent_execution_modes.md`
  Seccion 2 (señales de seleccion).
- Que ficheros tocar, que comandos de Kilo lanzar, en que directorio escribir el informe de
  cada capa -- eso es el documento canonico de 4 capas (mecanismo operativo).
- Si un ticket toca la allowlist de blast-radius-alto -- eso es `agent_execution_modes.md`
  Seccion 3 (fuente unica, no se re-declara aqui).
- La numeracion interna de `agent_execution_modes.md` ni del documento canonico de 4 capas --
  ambos quedan SIN renumerar (ver seccion dedicada arriba).
