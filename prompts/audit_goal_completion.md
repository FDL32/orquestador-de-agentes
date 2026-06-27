# Audit Goal Completion (Isolated Goal-Checker)

> Prompt canonico para verificar el cumplimiento de un /goal autonomo con un
> checker AISLADO del orquestador-ejecutor.
>
> contract_id: cid-audit-goal-completion-v0
> source_of_truth: este prompt.
> Adopcion: WOT-2026-014t (2026-06-27). Origen externo: cobusgreyling/loop-engineering
> (Medium paso 9 Isolating Maker from Checker).

---

## Proposito

El maker/checker de IMPLEMENTACION (Builder hace, Manager revisa) es maduro. Pero
la CONDICION del /goal -- el objetivo del pipeline esta cumplido -- la suele
evaluar el MISMO orquestador que ejecuto el pipeline. Eso es self-validation bias
en la capa mas externa: el actor que hizo el trabajo declara que el trabajo esta hecho.

Este prompt define un CHECKER AISLADO del ejecutor que verifica el cumplimiento del
/goal contra EVIDENCIA DURA (git, exit codes, bus, validate), nunca contra el
relato ni el transcript del ejecutor.

## 1. Pre-requisito: el goal debe traer un predicado machine-checkable

Antes de evaluar cumplimiento, el goal DEBE declarar su condicion de exito como un
PREDICADO VERIFICABLE POR MAQUINA: un exit code (0 o 1), un hash esperado, una
validacion de schema, o un comando que retorna PASS/FAIL deterministico.

Si el goal solo describe el objetivo en prosa, sin predicado machine-checkable, el
checker emite NO-APTO ANTES de evaluar: ese goal no es loopeable y cae bajo la
denylist de prompts/_shared/loop_readiness.md (cid-loop-readiness-v0). Operar por
turnos supervisados, no en /goal autonomo.

Regla dura: un goal cuya UNICA verificacion sea el juicio conversacional de un LLM
es self-validation re-empaquetada -> NO-APTO. El predicado debe existir antes de
que el LLM-checker entre en juego.

## 2. Bundle de evidencia dura (el unico input del checker)

El checker recibe EXCLUSIVAMENTE la condicion del goal + este bundle. NUNCA recibe
el transcript ni el historial de sesion del ejecutor (eso propagaria sus sesgos).

El bundle declara, campo a campo:

| Campo | Descripcion |
|---|---|
| goal_condition | La condicion del goal, en una linea. |
| predicate | El predicado machine-checkable declarado (comando/hash/schema). |
| predicate_result | El resultado real del predicado: exit code 0 o 1, o PASS/FAIL. |
| commit_sha | SHA(s) del commit que materializa el goal. |
| validate_output | Salida de agent_controller --validate (errors/warnings). |
| isolation_field | Que condicion B1 se aplico: B1a:model=ID o B1b:fresh-context, con evidencia de registro. |

Una etiqueta de evidencia sin artefacto concreto (path/commit/exit/event) cuenta
como RELATO, no como evidencia dura, y no permite CUMPLIDO.

## 3. Protocolo de evaluacion (4 pasos del checker)

El LLM-checker SOLO interpreta el CONTEXTO alrededor del predicado: si la evidencia
dura corresponde al goal declarado y si hubo cierre-en-falso. NO sustituye al
predicado ni decide el exito por inferencia conversacional.

1. Predicado presente. Existe predicate en el bundle. Si no -> NO-APTO (seccion 1).
2. Resultado PASS. predicate_result es PASS (exit 0 o equivalente). Si es FAIL -> NO-CUMPLIDO.
3. Evidencia corresponde al goal. El commit_sha y validate_output existen y son
   coherentes con goal_condition. Falta de commit_sha o validate_output con un
   resultado declarado PASS = evidencia insuficiente -> NO-CUMPLIDO.
4. Sin cierre-en-falso. No hay senal de que el resultado PASS se haya fabricado
   (predicado trivial que siempre pasa, o evidencia que no liga al goal). Si hay
   sospecha fundada -> NO-CUMPLIDO con causa.

Veredictos: CUMPLIDO (los 4 pasos pasan), NO-CUMPLIDO (algun paso falla con
evidencia), NO-APTO (el goal no trae predicado machine-checkable).

## 4. Protocolo de invocacion del checker aislado (los 3 bloqueantes)

### B1 - Aislamiento real (no aspiracional)

El checker satisface AL MENOS UNA condicion, registrada en isolation_field:

- B1(a) Modelo distinto: el checker corre en una family/modelo distinto del
  ejecutor (model id ejecutor != model id checker). Via Agent tool con parametro model distinto.
- B1(b) Sub-agente sin contexto compartido: el checker arranca en FRESH CONTEXT,
  sin el transcript del ejecutor. Su unico input es la condicion del goal + el
  bundle. Via Agent tool (spawnea un sub-agente sin el historial de la sesion).

Criterio de rechazo: si el checker es la MISMA family leyendo el MISMO contexto del
ejecutor (mismo transcript), comparte sesgos -> NO es aislado -> el veredicto no
cuenta. Aplicar audit_agent_output.md con el mismo modelo y el mismo contexto NO satisface B1.

### B3 - Aislamiento de privilegios (read-only)

El checker opera ESTRICTAMENTE read-only sobre el workspace. Se spawnea con
tools = Read/Grep/Glob/Bash-read, SIN Write/Edit/Bash-mutante (o con un
subagent_type read-only por diseno, p.ej. Explore).

Criterio de rechazo: un checker con capacidad de escritura podria arreglar los
tests/artefactos que verifica = falso verde estructural (el verificador se vuelve
maker). Un checker con Write/Edit NO cuenta como aislado, aunque cumpla B1.

### Registro reproducible

El protocolo de invocacion deja en el log del goal: que condicion B1 (a o b) se
aplico, el model id o la nota de fresh-context, y que el checker fue read-only.

## 5. Umbral de activacion (coste proporcional)

El checker aislado NO se aplica a cada ticket. Se activa EXCLUSIVAMENTE cuando se
cumple UNA de estas dos condiciones:

- Goal multi-ticket: el /goal procesa un pipeline de varios tickets (P1, P2, P3).
- Accion externa irreversible: el /goal termina en push, publicacion o deploy.

Para tickets de un solo paso, el maker/checker de implementacion existente
(Builder/Manager) es suficiente; instanciar un checker de goal dedicado seria coste desproporcionado.

## 6. Fixtures de verificacion (barrera)

### Fixture A - cierre-en-falso RECHAZADO

Input (bundle campo a campo):

    goal_condition: Los tickets del lote estan COMPLETED y validate 0/0
    predicate: agent_controller --validate --json -> errors=0 warnings=0
    predicate_result: PASS
    commit_sha: (ausente)
    validate_output: (ausente)
    isolation_field: B1b:fresh-context

Rubrica paso a paso:
1. Predicado presente: SI (validate).
2. Resultado PASS: declarado PASS.
3. Evidencia corresponde al goal: FALLA -- commit_sha ausente Y validate_output
   ausente. El resultado dice PASS pero no hay artefacto duro que lo respalde.
4. (no se alcanza)

Veredicto: NO-CUMPLIDO.
Causa: evidencia insuficiente -- resultado PASS sin commit SHA ni salida de
validate. Un PASS declarado sin artefacto que lo soporte es RELATO, no evidencia.

### Fixture B - goal-sin-predicado RECHAZADO

Input (bundle campo a campo):

    goal_condition: Mejorar la calidad general del codigo del motor
    predicate: (ausente -- el goal esta en prosa)
    predicate_result: (no aplica)
    commit_sha: abc1234
    validate_output: errors=0 warnings=0
    isolation_field: B1a:model=claude-haiku-4-5

Rubrica paso a paso:
1. Predicado presente: FALLA -- no hay predicado machine-checkable; el goal es
   prosa subjetiva (calidad general) sin condicion verificable por maquina.

Veredicto: NO-APTO.
Causa: goal sin predicado machine-checkable -> cae bajo la denylist de
loop_readiness.md (cid-loop-readiness-v0). No es apto para /goal autonomo.

> Un auditor externo que aplique esta rubrica a los dos fixtures obtiene los mismos
> veredictos (NO-CUMPLIDO para A, NO-APTO para B) de forma deterministica, sin
> ejecutar codigo: la barrera es la rubrica + los fixtures, verificable por inspeccion.

## Protocolo de salida

El checker emite UNA linea de veredicto + causa:

    Veredicto: CUMPLIDO | NO-CUMPLIDO | NO-APTO
    Causa: una linea, que paso fallo o por que no es apto
    Aislamiento aplicado: B1a:model=ID o B1b:fresh-context, + read-only confirmado
