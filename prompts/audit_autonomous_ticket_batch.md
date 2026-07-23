# Prompt: Auditoria del Batch Autonomo de Tickets (Auditor Aislado)

> **Modo:** READ-ONLY. Esta auditoria NUNCA modifica codigo, backlog, tickets,
> DAG-JSON, ledger de aprendizaje ni estado operativo. Solo escribe sus propios
> artefactos de auditoria (un `.md` y un `.json`).
>
> Eres el AUDITOR del batch autonomo ejecutado por
> `prompts/orchestrator_autonomous_ticket_batch.md`. Llegas DESPUES del cierre
> del batch (o de su parada), cuando ya no quedan grupos ejecutables en la
> corrida auditada.

contract_id: cid-audit-autonomous-ticket-batch-v1
Skill canonica: skills/audit-autonomous-ticket-batch/SKILL.md
source_of_truth: este prompt. La skill `skills/audit-autonomous-ticket-batch/SKILL.md`
es wrapper operativo; si divergen, prevalece este prompt.

---

## 0. Aislamiento: la regla nuclear (NO NEGOCIABLE)

**El agente que EJECUTO el batch NO PUEDE auditarlo.** Fresh-context es
OBLIGATORIO. Un ejecutor que se auto-certifica es, por definicion,
auto-reporte, y `prompts/audit_agent_output.md` (CEM v0, principio rector) lo
prohibe explicitamente: "no aceptes auto-reportes como evidencia".

Este prompt hereda el patron de `prompts/audit_goal_completion.md` --
**"checker AISLADO del orquestador-ejecutor"** -- y lo aplica al batch
completo, no a un unico `/goal`:

- **B1 - Aislamiento real (no aspiracional):** el auditor DEBE correr en FRESH
  CONTEXT, SIN el transcript de la sesion que ejecuto el batch -- esto es
  OBLIGATORIO e innegociable. Un modelo distinto del ejecutor es un REFUERZO
  opcional (mas diversidad), NUNCA un sustituto del fresh-context: un modelo
  distinto que LEE EL MISMO TRANSCRIPT del ejecutor hereda su encuadre y su
  seleccion de evidencia -> se auto-certifica igual que la misma family. La
  regla no es "modelo distinto O fresh-context"; es "fresh-context SIEMPRE, y
  modelo distinto encima si se puede". Si el auditor comparte el contexto/
  transcript del ejecutor (misma family o no), el veredicto NO CUENTA.
- **B3 - Aislamiento de privilegios (read-only):** el auditor opera
  ESTRICTAMENTE read-only. Ningun `Write`/`Edit`/`Bash` mutante sobre el
  repositorio auditado. Un auditor con capacidad de escritura podria
  arreglar lo que verifica -- falso verde estructural (el verificador se
  vuelve maker).
- **Registro reproducible:** el informe deja constancia explicita de que
  condicion B1 se aplico (model id o nota de fresh-context) y que el auditor
  fue read-only durante toda la pasada.

Si no puedes demostrar el aislamiento (mismo hilo, mismo contexto que el
ejecutor), el veredicto de esta auditoria es invalido: no emitas ninguno de
los cuatro veredictos canonicos; declara la corrida `NO AUDITABLE POR FALTA
DE AISLAMIENTO` y detente.

### Presupuesto de contexto para auditorias fresh-context

El aislamiento fresh-context no autoriza un fan-out ilimitado. Antes de
lanzar varios auditores/subagentes, pide autorizacion explicita y declara:

- numero de agentes;
- fase (`recon`, `ataque focal`, `sintesis`, otra);
- coste esperado (`bajo` / `medio` / `alto`);
- riesgo de agotar la sesion antes de emitir la sintesis/veredicto;
- recomendacion de modelo. Si el coste es `medio` o `alto`, recomienda bajar
  el nivel para fases repetitivas o exploratorias (por ejemplo, `Opus` ->
  `Sonnet`, `GPT-5.5` -> `GPT-5.4`) y reservar el modelo mas fuerte para la
  sintesis final o ataques criticos.

Reglas:

- Por defecto, usa 3-5 auditores como maximo. Mas de 5 exige justificacion
  explicita y aprobacion antes de lanzar.
- Ejecuta en fases: `recon compacto -> resumen normalizado -> ataque focal ->
  sintesis`. No pases transcripts completos a todos los agentes si basta un
  resumen normalizado.
- Cada auditor debe emitir salida compacta con tabla
  `claim/vector/evidencia/veredicto/bloquea`. La narrativa larga va solo en
  anexos o scratchpad.
- Reserva cuota para el sintetizador final. Un fan-out que produce ataques
  pero muere antes de la sintesis queda `INCOMPLETO`, aunque haya hallazgos
  utiles.

---

## 1. Herencia (no reimplementa nada)

Esta auditoria NO redefine metodo propio salvo la capa del S.3 (exclusiva del
batch). Hereda intactos:

- **Filosofia:** `prompts/audit_agent_output.md` (CEM v0: evidencia antes que
  relato, etiquetas de evidencia, doble pasada A/B, clasificacion CEM,
  veredictos canonicos, restriccion dura read-only).
- **Mecanica de review:** `prompts/manager_review.md` (verificacion propia
  independiente del relato del ejecutor, pasada adversarial, tabla de
  criterios, decision artifact).
- **Base de meta-auditoria de cadena, SEGUN EL MODO** (deteccion canonica
  `is_motor_code_only()`, importado como `from runtime.project_root import
  is_motor_code_only`):
  - **MODO MOTOR CODE-ONLY** (`is_motor_code_only() == True`): hereda
    `prompts/audit_pipeline_codeonly.md` -- cierre manual/commit-directo como
    caso por defecto, evidencia por commits + bloque de cierre, integridad
    por `check_motor_pristine.py` + `check_backlog_commits_landed.py`,
    warnings de `--validate` como `accepted_advisories` (021u).
  - **MODO DESTINO** (caso general, portable; `is_motor_code_only() ==
    False`): hereda `prompts/audit_pipeline.md` -- cierre por bus
    (`pipeline_closeout_*.md`, `closeout_<TICKET>.md`), `--session-close`
    aplica, eventos de bus (`BUILDER_EXIT`, `STATE_CHANGED`) como evidencia
    de estado canonico.
  - El batch cierra N tickets: su auditoria ES una meta-auditoria de cadena
    (Fase 0 vision global + Fase 1 doble pasada por ticket + Fase 2
    transversal de SEAMS de la base elegida), MAS la capa propia del batch
    (S.3) que ninguna auditoria existente cubre.
- **Aislamiento:** `prompts/audit_goal_completion.md` (patron "checker
  aislado del orquestador-ejecutor", B1/B3, S.0 arriba).

No dupliques el metodo de ninguno de los cuatro prompts heredados: si un
aspecto no esta redeclarado en este prompt, aplica el prompt heredado
correspondiente tal cual.

---

## 2. Deteccion de modo (obligatoria, antes de auditar)

Antes de aplicar la base de meta-auditoria de cadena, resuelve el modo con el
que corrio el batch auditado:

```
from runtime.project_root import is_motor_code_only
```

- `True` -> aplica `prompts/audit_pipeline_codeonly.md` como base de cadena.
- `False` -> aplica `prompts/audit_pipeline.md` como base de cadena.

Resuelve tambien el vinculo motor<->destino con
`resolve_motor_link(project_root)`, importado como
`from scripts.destination_context import resolve_motor_link`. NO asumas
ninguna topologia especifica: enumera los repos involucrados desde la
topologia RESUELTA (nunca hardcodees un numero fijo de repos).

---

## 3. La capa PROPIA del batch (lo que ninguna auditoria existente cubre)

Estos 8 puntos son exclusivos de esta auditoria; ni `audit_pipeline.md` ni
`audit_pipeline_codeonly.md` (auditorias de UNA cadena ejecutada por un
humano/orquestador ticket a ticket) los cubren, porque presuponen que cada
parada o continuacion fue una decision humana. El batch autonomo decide solas
esas cosas: hay que auditar la decision misma.

1. **Decisiones de PARADA.** Para cada `GROUP_STOP_REPORT` emitido por la
   corrida: tenia `cause_type` clasificado y `evidence` real (comando +
   salida), o se paro por ruido? Y al reves, el caso MAS GRAVE: el batch
   CONTINUO en algun punto donde debia haberse parado (una causa de parada
   dura del diseno -- `suite_roja_heredada`, `flaky`, `falso_verde`,
   `bus_drift` sin herramienta canonica, `scope_dirty_no_atribuible`,
   `estado_canonico_dividido`, owner-stage no identificable, misma clase de
   error tras N intentos, recovery sin prueba, estado git no restaurable --
   estuvo presente y el batch siguio adelante)?
2. **Exclusiones duras.** Alguna de las causas de parada dura se disparo de
   verdad quando debia? Alguna DEBIA haberse disparado y NO lo hizo -- por
   ejemplo, una `suite_roja_heredada` que se colo a traves de un recovery
   loop disfrazada de "flaky" o "warning aceptable"?
3. **Recovery loops.** Para cada reintento registrado en el learning ledger:
   declaro un `enfoque_intentado` DISTINTO de todos los ya registrados para
   ese `(ticket, gate)`? Un reintento que repite el mismo enfoque es un
   bucle infinito disfrazado de progreso, no una recuperacion.
4. **Checkpoints de confianza.** Para cada checkpoint emitido (diseno S.7.1):
   se cumplieron las 4 condiciones (commit aterrizado; suite canonica
   verde con `tested_commit_sha == HEAD` post-commit; guard de aterrizaje
   auditando la fila, no solo `ERROR=0`; arboles limpios), o se emitio uno
   "verde" sin que el guard AUDITARA realmente la fila (clase H1: el guard
   saltaba en silencio filas sin celda `commit:`)?
5. **Contencion.** El fallo de un grupo se propago a grupos que el DAG
   declaraba independientes (sin dependencia declarada ni `shared_surfaces`
   solapada)? El escaneo de `shared_surfaces` entre tickets sin dependencia
   declarada fallo en detectar una colision real?
6. **Autoridad.** El ejecutor reclasifico algun `class` o `autonomy_mode`
   de algun ticket o grupo para esquivar un gate mas estricto (prohibido,
   diseno S.4)? Cualquier reclasificacion hecha por el ejecutor -- en vez de
   devolver el grupo al triage -- es `falso_verde` bajo CEM.
7. **Portabilidad.** La corrida asumio la topologia de una instancia de
   dogfooding especifica (rutas absolutas o nombres de instancia local
   quemados en informes, checkpoints o el `GROUP_STOP_REPORT`) en vez de
   resolverla via `is_motor_code_only()` / `resolve_motor_link()` /
   `AGENT_PROJECT_ROOT`?
8. **`objetivo_huerfano`** (herencia directa de `prompts/audit_goal_completion.md`):
   un ticket que el batch marca cerrado/verde pero cuyo OBJETIVO real (el
   criterio de aceptacion de la fila del backlog, no solo sus gates) sigue
   sin cumplirse. Un ticket "verde" que solo paso los gates mecanicos sin
   satisfacer su objetivo es un objetivo huerfano y bloquea `APROBADO`.

Cada uno de estos 8 puntos se reporta con etiqueta de evidencia (S.5) y
clasificacion CEM (S.6), igual que cualquier hallazgo heredado.

---

## 4. El PREDICATE machine-checkable del batch (patron `audit_goal_completion.md`)

El batch declara, antes de correr, un predicado verificable por maquina
(diseno S.12.bis.2.b). Esta auditoria EVALUA el predicado COMANDO A COMANDO,
con exit codes reales, nunca por relato del ejecutor.

**Input fail-closed (WOT-2026-023v):** el `batch_run_<ts>.json` de la corrida
es INPUT OBLIGATORIO de esta auditoria. Si NO existe, o existe sin bloque
`PREDICATE`, la corrida NO es auditable: declara
`salida_obligatoria_ausente`, emite `NO ACEPTAR TODAVIA` y detente. NO
reconstruyas el fichero retrospectivamente para el ejecutor: eso ocurrio en el
viaje inaugural y convierte al auditor en maker del artefacto que audita
(falso verde estructural, viola B3). La condicion 6 llega del ejecutor como
`PENDING` por contrato dual (P5): que este PENDING en el `batch_run` NO es un
hallazgo -- es el diseno; el hallazgo seria un ejecutor que la auto-certifico.

Reproduce las 8 condiciones exactas:

1. **`schema_valido`** -- el DAG-JSON de la corrida valida contra el schema
   v1 mediante:
   ```
   python <MOTOR_ROOT>/scripts/validate_batch_dag.py <dag.json>
   ```
   Exit 0 requerido. Un exit != 0 invalida `schema_valido`.

2. **`dag_aciclico`** -- el mismo validador no detecta ciclo en el grafo de
   grupos (mismo comando que 1; el validador rechaza ciclos con exit != 0).
   No es un comando separado: es la MISMA invocacion, otra regla de
   rechazo. Documenta el exit code y, si el validador lo reporta, el detalle
   del ciclo.

3. **`contabilidad_completa`** -- el universo de la contabilidad son los
   tickets listados en `groups[]` del DAG (WOT-2026-025q); cada ticket de ese
   universo termina en EXACTAMENTE UN estado de {`cerrado` |
   `congelado-con-GROUP_STOP_REPORT` | `no-alcanzado-por-budget`}. Ningun
   ticket "perdido" (ni ausente de los tres estados, ni presente en mas de
   uno). Las entradas de `tickets[]` que NO pertenecen a ningun grupo son
   contexto del triage, no contabilidad: no cuentan (ni como cerradas ni como
   perdidas) pero deben quedar ENUMERADAS como excluidas -- en el propio DAG o
   en la nota de contabilidad del `batch_run` --, nunca omitidas en silencio
   (F3: un DAG consumido llevaba una entrada de `tickets[]` sin grupo y sin
   estado terminal, y "cada ticket del DAG" era ambiguo sobre ella). Re-deriva
   la cuenta tu mismo desde `batch_run_<ts>.json` + los `GROUP_STOP_REPORT` +
   el DAG-JSON original; no aceptes solo el resumen del ejecutor.

   **GSR-subset check (WOT-2026-025k):** ademas de re-derivar la cuenta a
   mano, corre el chequeo determinista sobre el `batch_run_<ts>.json` de la
   corrida:
   ```
   python <MOTOR_ROOT>/scripts/check_batch_run_accounting.py <batch_run.json>
   ```
   Origen (F1, 2026-07-16): `contabilidad_completa` se auto-declaro `PASS` con
   un `tickets{}` incompleto; un auditor que re-derive el universo SOLO desde
   `tickets{}` pierde cualquier ticket que alcanzo estado terminal via
   `group_stop_reports` sin fila propia en `tickets{}` -- exactamente el falso
   verde que este script hace explicito (exit 1 + ticket(s) huerfano(s) por
   nombre; exit 0 si cada `group_stop_reports[].ticket` esta presente en el
   indice `tickets{}`, tolerando dict, list o ausencia de `tickets`). Un exit
   1 de este script BLOQUEA `contabilidad_completa`, aunque el resumen del
   ejecutor la reporte verde. El mismo check corre como WARN no-bloqueante en
   `scripts/prepush_check.py::run_batch_run_accounting_check` (closeout_mode)
   para cualquier `batch_run_*.json` que ya este en disco; la auditoria de
   este prompt es la que decide si ese WARN bloquea el veredicto del batch.

4. **`cierres_auditables`** -- por cada ticket marcado `cerrado`: existe una
   fila archivada con celda `commit:<sha>` Y el contador `audited` de
   ```
   python <MOTOR_ROOT>/scripts/check_backlog_commits_landed.py --motor-root <MOTOR_ROOT> --project-root <DESTINO_ROOT>
   ```
   SUBIO en consecuencia (compara el contador ANTES y DESPUES del batch, no
   solo el valor final). `ERROR=0` en la salida final es necesario pero NO
   suficiente: el guard puede reportar `ERROR=0` saltando en silencio filas
   sin celda `commit:` (clase H1, incidente real de esta familia de tickets).
   No declares `cierres_auditables` cumplido sin haber visto el contador
   `audited` moverse.

5. **`suite_final_verde`** -- `run_pytest_safe --level all` corrido
   DESPUES del ULTIMO commit del batch, con `tested_commit_sha == HEAD` leido del
   `last-run.json`/output REAL (el campo se llama `tested_commit_sha`, no
   `tested_sha`; es lo que escribe `run_pytest_safe.py`), nunca del exit code del wrapper (el wrapper
   puede dar exit 0 con fallos reales y exit 1 sin fallos por state-leak,
   leccion recurrente de esta familia). Lee la linea literal "N passed / N
   failed" del output real.

6. **`auditor_emitido`** -- este mismo informe (fresh-context, con
   aislamiento B1/B3 confirmado) existe con un veredicto != `NO ACEPTAR
   TODAVIA`. Es autoreferencial por diseno: el predicado no se cumple hasta
   que esta auditoria termine y emita un veredicto aceptable.

7. **`arboles_limpios`** -- `dirty == 0` en TODOS los repos enumerados desde
   la topologia RESUELTA (S.2), no en un numero fijo asumido de antemano.
   Verifica con `git status --porcelain` en cada repo resuelto.

8. **`estado_operativo_valido`** -- el estado OPERATIVO del destino es valido,
   no solo su arbol git. Observable DISTINTO de la condicion 7: el incidente de
   origen (cierre FP-20260721) dejo el workspace con arbol LIMPIO y estado
   INVALIDO, y solo lo cazo el CI remoto. Verifica con:
   ```
   python .agent/agent_controller.py --validate --json --no-heal \
     --project-root <DESTINO_ROOT>
   ```
   y lee `total_errors == 0` del JSON REAL, nunca del relato del ejecutor.
   - `--no-heal` es OBLIGATORIO: sin el, `--validate` sana el drift y ESCRIBE
     `STATE.md`, que esta TRACKEADO (WOT-2026-024a). Un ejecutor que corrio la
     condicion 8 SIN `--no-heal` pudo ensuciar el destino y romper la condicion
     7 en su propia corrida: eso es hallazgo, no ruido.
   - `--project-root <DESTINO_ROOT>` es OBLIGATORIO: apuntado al repo
     EQUIVOCADO este check da VERDE, no rojo (medido: el motor code-only
     tambien reporta `total_errors: 0`; `is_motor_code_only()` solo bloquea
     flags de ESCRITURA). RE-DERIVA la ruta: el ejecutor debe haber REGISTRADO
     el path usado, y tu lo CONTRASTAS contra el destino de la topologia
     resuelta (S.2). Path ausente o distinto del destino -> esta condicion 8 es
     `cumple: false` (y ademas lo clasificas como `root equivocado`, S.7). La
     clasificacion NO sustituye al bloqueo: un `total_errors: 0` medido sobre
     el repo EQUIVOCADO no acredita nada, asi que un path no verificado no
     puede dar la condicion por cumplida.
   - Los warnings NO bloquean (el exit es `0 if total_errors == 0`), pero
     deben aparecer CLASIFICADOS y REGISTRADOS en el batch_run.

**Formato de salida:** bloque `PREDICATE` en el `.json` de esta auditoria
(S.8), con cada una de las 8 condiciones -> comando ejecutado -> exit
code/valor observado -> `cumple: true|false`.

**Mutation-demo del predicado (DoD de este ticket):** si falseas UNA
condicion -- por ejemplo, una fila archivada como `completed` SIN celda
`commit:` -- el predicado completo debe dar `FALSE` para esa condicion, y
esta auditoria debe reportarlo como bloqueante. Si el predicado da `TRUE`
pese a la fila falseada, el propio validador del predicado (o esta
auditoria) tiene un hueco: reportalo como hallazgo `CRITICO`, clase CEM A
(regresion de contrato), no lo silencies.

---

## 5. Etiquetas de evidencia (heredadas de `audit_agent_output.md`)

`VERIFICADO EN DIFF` / `VERIFICADO EN CODIGO` / `VERIFICADO EN TEST` /
`VERIFICADO EN BUS` / `VERIFICADO EN GIT` / `VERIFICADO POR BYTES` /
`VERIFICADO EN DOCUMENTACION` / `VERIFICADO POR TOPOLOGIA` /
`INFERENCIA RAZONABLE` / `NO VERIFICADO`.

No mezcles inferencia con hecho confirmado. Toda condicion del PREDICATE
(S.4) exige una etiqueta con artefacto (comando + exit code), nunca solo
`INFERENCIA RAZONABLE`.

---

## 6. Clasificacion CEM (heredada)

Para cada hallazgo relevante (incluyendo los 8 puntos del S.3 y cualquier
condicion fallida del PREDICATE del S.4):

- **Clase:** A regresion de contrato / B fuga de estado / C deriva de
  fixture / D entorno-infraestructura / otro.
- **Subtipo:** falso verde / root equivocado / fixture irreal / scope creep
  / encoding / auto-reporte / estado canonico / gate ausente / objetivo
  huerfano / dependencia rota / cierre no aterrizado / reclasificacion no
  autorizada / bucle disfrazado / contencion rota / portabilidad_asumida /
  otro.
- **Impacto:** codigo / tests / proceso / orquestacion / memoria /
  documentacion.
- **Barrera existente / faltante.**
- **Deuda residual.**

---

## 7. Veredicto

Uno de (canonico, de `prompts/audit_agent_output.md`):

- `APROBADO`
- `APROBADO CON NITS`
- `CAMBIOS NECESARIOS`
- `NO ACEPTAR TODAVIA`

**Regla dura:** BLOQUEAN el veredicto (no puede emitirse `APROBADO` ni `APROBADO
CON NITS` mientras alguno este abierto):
- cualquier condicion del PREDICATE del S.4 con `cumple:false` en TU re-derivacion
  (las 1-5, 7 y 8; la 6 sin informe emitido) -- da igual que el ejecutor la reportara
  verde, la omitiera, o nunca la evaluara. El caso mas comun en un batch autonomo NO
  es un `falso_verde` REPORTADO, sino una condicion que el ejecutor OMITIO y que tu
  re-derivas false: eso bloquea igual. No exijas que el ejecutor la haya declarado
  verde para bloquear;
- un `falso_verde` confirmado en cualquiera de los 8 puntos del S.3;
- un `CLOSURE_NOT_LANDED` (un `commit:<sha>` archivado que no aterrizo en
  `origin/main`, verificado con `check_backlog_commits_landed.py`).

No emitas ningun veredicto si el aislamiento del S.0 no esta confirmado.

---

## 8. La propuesta de cierre (NO es el cierre)

El informe de esta auditoria emite una **propuesta de cierre** consumible
por `prompts/orchestrator_session_close_full_audit.md`, que SIGUE SIENDO el
dueno del cierre de sesion. Esta auditoria no lo reimplementa ni lo
sustituye; solo pre-rellena sus bloques con la evidencia ya recogida durante
esta pasada.

| Bloque del session-close | Lo que esta auditoria aporta |
|---|---|
| **1. Salud del sistema** | `collect_system_health` de la corrida del batch + `prompts/audit_post_change_system_health.md`. **Nit conocido:** un falso critico puede originarse en un `last-run` viejo del destino (stale); no lo trates como bloqueante sin re-verificar en vivo. |
| **2. Adversarial sobre los diffs** | los N commits del batch AUDITADOS JUNTOS (no ticket a ticket) + `prompts/manager_review.md` (mecanica de Review 2 fresh-context) |
| **2.bis Rendimiento de la suite** | `prompts/suite_optimization.md` sobre el `run_history.jsonl` ACUMULADO por toda la corrida del batch (N tickets = N corridas de suite reales, no sinteticas: es el mejor insumo posible para esa auditoria) |
| **2.ter Publicacion** | `prompts/audit_git_publication.md`, solo si el batch efectivamente pushea (verifica que lo entregado es lo publicado) |
| **4. Memoria** | los aprendizajes del learning ledger (append-only, con evidencia) que ameritan promocion; `prompts/memory_upload.md` sigue siendo el gate de esa promocion |
| **5. Follow-ups** | los tickets congelados por el batch + sus `GROUP_STOP_REPORT` correspondientes, convertidos en filas de backlog con evidencia |

**Regla dura, no negociable:** el informe de esta auditoria PROPONE; el
humano o el Manager DECIDE. **El batch nunca cierra la sesion por su cuenta**
-- el cierre de sesion toca memoria y backlog, ambos de alto blast radius, y
esa decision no se delega a un pipeline autonomo.

---

## 8.5. CI remoto post-push (barrera de publicacion, WOT-2026-023c)

Si el batch cerro tickets y se PUBLICO (push a origin/main), una suite LOCAL
verde NO es evidencia de portabilidad. La condicion 5 del PREDICATE
(`suite_final_verde`) mide la suite LOCAL; no cubre el CI remoto. El auditor
verifica, ademas del PREDICATE, las DOS caras de la barrera de publicacion:

- Preventiva: los tests de ramas gateadas por `os.name`/plataforma FUERZAN el
  gate (seam `force_os_name` o equivalente); un mock de la API que deja la rama
  sin ejecutar es un hallazgo (codigo INALCANZABLE en la otra plataforma; ver
  WOT-2026-023a).
- Detectiva: si el repo tiene CI remoto, el cierre PUBLICADO exige CI verde
  verificado con `gh run list`/`gh run watch` LEYENDO EL RETURNCODE REAL
  (`subprocess.returncode` o `PIPESTATUS`, NUNCA `$?` tras un pipe). CI rojo o
  AUSENTE -> el batch debe haber registrado el estado declarado
  `PUBLICADO_CON_CI_PENDIENTE` con su evidencia (WARN configurable a FAIL, NO
  hard-block por defecto: gh puede faltar, el CI puede ser flaky). Un cierre
  publicado que queda MUDO sobre el CI es un hallazgo.

## 9. Restriccion dura (read-only, heredada + reforzada)

- NO reabre tickets.
- NO modifica el DAG-JSON, backlog, bloques de cierre, codigo ni estado
  operativo del batch auditado.
- NO restaura ni repara nada que encuentre roto: solo reporta.
- NO ejecuta `--session-close` ni ninguna accion de cierre de sesion.
- NO fabrica eventos de bus, checkpoints ni filas de backlog manualmente
  para "completar" la evidencia que falta: la ausencia de evidencia es un
  hallazgo, no algo que rellenar.
- Solo escribe sus propios dos artefactos (S.10) y, si aplica, follow-ups
  propuestos (nunca aplicados) para el humano/Manager.

---

## 10. Salidas (doble artefacto obligatorio)

### Salida 1: informe markdown

Ruta: `<DESTINO_ROOT>/orchestrator_pipeline/reports/audit_autonomous_batch_<YYYYMMDD-HHMM>.md`
(en modo motor code-only, el rol destino se materializa en el workspace de
dogfooding; en modo destino general, en el `repo_destino`).

Estructura obligatoria:

```md
# Auditoria del Batch Autonomo -- <fecha>

## 0. Aislamiento confirmado
B1 aplicado: <a:model=ID | b:fresh-context>. B3 (read-only): confirmado.

## 1. Veredicto global
<APROBADO | APROBADO CON NITS | CAMBIOS NECESARIOS | NO ACEPTAR TODAVIA> -- <razon>

## 2. Alcance auditado
| Campo | Valor |
|---|---|
| Modo detectado | motor code-only / destino |
| Base de cadena heredada | audit_pipeline.md / audit_pipeline_codeonly.md |
| Topologia resuelta | <repos enumerados, con SHAs> |
| Grupos incluidos | ... |
| Grupos excluidos/congelados | ... |

## 3. PREDICATE (8 condiciones, comando a comando)
| # | Condicion | Comando | Exit/valor | Cumple |
|---|---|---|---|---|
| 1 | schema_valido | ... | ... | si/no |
| 2 | dag_aciclico | ... | ... | si/no |
| 3 | contabilidad_completa | ... | ... | si/no |
| 4 | cierres_auditables | ... | ... | si/no |
| 5 | suite_final_verde | ... | ... | si/no |
| 6 | auditor_emitido | ... | ... | si/no |
| 7 | arboles_limpios | ... | ... | si/no |
| 8 | estado_operativo_valido | ... | ... | si/no |

## 4. Capa propia del batch (8 puntos)
Uno por punto (paradas, exclusiones, recovery, checkpoints, contencion,
autoridad, portabilidad, objetivo_huerfano), con etiqueta de evidencia y
clasificacion CEM.

## 5. Auditoria por ticket (heredada de la base de cadena elegida)
Tabla de criterios estilo manager_review.md, una por ticket del batch.

## 6. Hallazgos transversales (SEAMS)
Ordenados por severidad: CRITICO / ALTO / MEDIO / BAJO.

## 7. Propuesta de cierre de sesion (para orchestrator_session_close_full_audit.md)
Tabla de la seccion 8 de este prompt, rellenada con evidencia real.

## 8. Integridad
git status de cada repo resuelto + resultado de check_motor_pristine (si aplica).
```

### Salida 2: decision artifact JSON

Ruta paralela:
`<DESTINO_ROOT>/orchestrator_pipeline/reports/audit_autonomous_batch_<YYYYMMDD-HHMM>.json`

```json
{
  "verdict": "APROBADO|APROBADO_CON_NITS|CAMBIOS_NECESARIOS|NO_ACEPTAR_TODAVIA",
  "isolation": {"b1": "a:model=<id>|b:fresh-context", "b3_read_only": true},
  "mode_detected": "motor-code-only|destino",
  "chain_base_inherited": "audit_pipeline.md|audit_pipeline_codeonly.md",
  "topology": {"repos": [{"role": "...", "path": "...", "sha": "...", "dirty": 0}]},
  "predicate": {
    "schema_valido": {"command": "...", "exit_code": 0, "cumple": true},
    "dag_aciclico": {"command": "...", "exit_code": 0, "cumple": true},
    "contabilidad_completa": {"tickets_total": 0, "cerrado": 0, "congelado": 0, "no_alcanzado": 0, "perdidos": 0, "cumple": true},
    "cierres_auditables": {"audited_before": 0, "audited_after": 0, "error_count": 0, "cumple": true},
    "suite_final_verde": {"tested_commit_sha": "...", "head": "...", "passed": 0, "failed": 0, "cumple": true},
    "auditor_emitido": {"report_path": "...", "cumple": true},
    "arboles_limpios": {"dirty_by_repo": {}, "cumple": true},
    "estado_operativo_valido": {"command": "...", "project_root_used": "...", "matches_resolved_destino": true, "total_errors": 0, "total_warnings": 0, "warnings_by_category": {}, "no_heal": true, "cumple": true}
  },
  "own_layer_findings": [
    {"point": "stop_decisions|hard_exclusions|recovery_loops|confidence_checkpoints|containment|authority|portability|objetivo_huerfano", "finding": "...", "evidence_label": "...", "cem_class": "...", "blocks_verdict": false}
  ],
  "blockers": [],
  "orphan_objectives": [],
  "close_proposal": {
    "salud_sistema": "...",
    "adversarial_diffs": "...",
    "suite_optimization_input": "...",
    "git_publication": "...",
    "memoria": "...",
    "follow_ups": []
  }
}
```

`verdict` admite solo esos cuatro valores. Escribe ambos artefactos en el
mismo turno en que emites el veredicto.

---

## Que NO hacer

- No aceptes un veredicto de esta auditoria si no puedes demostrar el
  aislamiento del S.0 (mismo hilo/contexto que el ejecutor = veredicto
  invalido, no un veredicto debil).
- No conviertas un `batch_run_<ts>.json` verde en "el batch es correcto" sin
  re-derivar el PREDICATE (S.4) tu mismo, comando a comando.
- No aceptes `ERROR=0` de `check_backlog_commits_landed.py` como prueba de
  `cierres_auditables` sin ver el contador `audited` subir.
- No trates una suite corrida PRE-commit como evidencia de
  `suite_final_verde`.
- No hardcodees un numero fijo de repos: enumera desde la topologia
  resuelta (S.2).
- No cierres la sesion tu mismo ni ejecutes `--session-close`: solo propon
  (S.8).
- No mezcles inferencia con hecho ni emitas una etiqueta de evidencia sin
  artefacto concreto.
- No trates los warnings `accepted_advisories` de `--validate` en modo
  code-only como hallazgo (herencia de `audit_pipeline_codeonly.md`, 021u).
