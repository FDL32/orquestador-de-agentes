# Prompt: Pipeline code-only (dogfooding del motor, cierre commit-directo)

> **Modo:** MUTA codigo del motor en la worktree `_dev`. Este pipeline SI escribe
> codigo y cierra tickets, a diferencia de sus hermanas read-only (/backlog-triage,
> /audit-pipeline). Es la variante de `/orchestrate-pipeline` para el caso concreto
> **motor en CODE-ONLY MODE**: sin destino externo, el bus esta bloqueado y el
> cierre es COMMIT-DIRECTO (git es el registro; el ID del ticket va en el mensaje).

contract_id: cid-orchestrator-pipeline-codeonly-v1
Skill canonica: skills/orchestrate-pipeline-codeonly/SKILL.md
source_of_truth: este prompt. La skill es wrapper operativo; si divergen, prevalece
este prompt.

## Cuando aplica (disparador exacto)

Las TRES condiciones a la vez:
1. `delivery_authority: repo_motor` (el ticket entrega codigo del motor).
2. Se trabaja en la worktree **`_dev`** (rama `main`), NO en el checkout principal
   (detached = solo consumo) NI en el workspace (ahi vive el backlog, no el codigo).
3. **CODE-ONLY MODE**: el motor no tiene destino externo montado, asi que las ops de
   bus (`--bootstrap-ticket`/`--mark-ready`/`--session-close`) estan BLOQUEADAS
   (`[ERROR] Motor code-only mode: write operations require an external workspace`).

Si el motor SI tiene destino externo (bus vivo), usa `/orchestrate-pipeline`
canonico (`prompts/orchestrator_pipeline.md`), no este.

## Relacion con las hermanas (el ciclo del backlog)

- **/backlog-triage** (ANTES): decide QUE pipeline lanzar (read-only).
- **/orchestrate-pipeline-codeonly** (DURANTE): este prompt. Ejecuta la cadena
  elegida, ticket a ticket, cierre commit-directo.
- **/audit-pipeline** (DESPUES): meta-auditoria retrospectiva (read-only).

## Diferencias con el canonico `orchestrator_pipeline.md` (que NO aplica tal cual)

El canonico usa bus + `--session-close`. Aqui:
- Cierre = **commit-directo** por ticket (no `--bootstrap-ticket`, no `--mark-ready`).
- Los warnings `bus_drift`/`ticket_prose`/`invariants` de `--validate` son NORMALES
  (bus ausente), no errores. `--session-close` es **N/A**.
- Se sigue el ESQUELETO del canonico (por ticket: Manager plan -> Builder -> Review 1
  -> Review 2 fresh-context -> cierre) pero con cierre commit-directo.

---

## PASO 0: PREFLIGHT (obligatorio, antes de tocar nada)

Correr el recolector determinista:

```
python <MOTOR_ROOT>/scripts/preflight_codeonly_pipeline.py \
    --dev-root <_dev> --principal-root <principal> --workspace-root <workspace> \
    --ticket <WOT-ID> --retire-token "<token>"
```

Es un RECOLECTOR (testigo read-only), NO un ejecutor: reporta senales, TU juzgas.
Verifica y reporta:
- SHAs de los 3 repos (`_dev`, principal, workspace) + limpieza del arbol `_dev`.
- `--validate --json --force` = 0 errores (warnings bus_drift NORMALES).
- Guard de topologia (`check_worktree_topology.py`): worktree `_dev`/main correcta.
- **BARRERA "0 consumidores runtime"** (SOLO para tickets de RETIRADA de codigo
  deprecated; `--retire-token` es OPCIONAL, se omite en fixes/tests): `git grep -i`
  del `--retire-token` excluyendo el propio fichero -> vacio = 0 consumidores =
  seguro retirar. Interpretar por la SALIDA (vacia=OK), no por el exit code (que
  difiere entre shells con pipe). Para un ticket de FIX o de TEST (no retirada), el
  preflight se corre SIN `--retire-token`: valida SHAs/topologia/validate y basta.

Si algun SHA no coincide con lo esperado (otra sesion avanzo el motor), RECONCILIAR
y re-verificar las premisas ANTES de seguir. El recolector NO decide: surfacea las
senales; el agente decide continuar o parar.

---

## PASO 0.5: Inicializar scratch de sesion

Tras el preflight, inicializa el scratch de sesion:

```
python <MOTOR_ROOT>/scripts/init_session_scratch.py --project-root <_dev> init
```

Todo handoff/arranque especifico de sesion va a `.agent/runtime/session/` del
destino-rol, no a `C:\tmp`.

---

## FLUJO POR TICKET (el orden importa; cada paso con su barrera)

### 1. Verificar la premisa EN VIVO antes de gastar Builder
Leccion 020s/020j (premisas refutadas): la ficha describe una parte, el sistema real
puede ser mayor O YA PUEDE ESTAR HECHO. `git grep` del token/simbolo por TODO el
scope (scripts/ agent_system/ bus/ prompts/ skills/ .agent/ .claude/) excluyendo
historia (CHANGELOG/DEC), + `git log --grep <ID>` y busqueda de commits/tests que ya
satisfagan el DoD. Confirmar el alcance REAL antes de planificar.

**Salidas validas del PASO 1** (no solo "seguir al PASO 2"):
- **Premisa CONFIRMADA** -> PASO 2 (planificar el trabajo real).
- **Premisa REFUTADA-por-ampliacion** (el scope real es mayor) -> reencuadrar el
  ticket, actualizar el plan, PASO 2 con el alcance corregido.
- **Premisa REFUTADA-por-ya-hecho** (otro commit/sesion ya cerro el DoD; verificar
  con mutation-to-prove que el fix/test tiene dientes) -> NO gastar Builder;
  reconciliar el ticket como LIKELY_DONE y archivarlo en el WORKSPACE con evidencia
  (commit/test/mutation). Esto es un EXITO del pipeline, no un fallo: el maiden
  voyage de 2026-07-10 cazo 021e+021j ya-hechos aqui y evito trabajo redundante.

### 2. Manager: crear los artefactos de plan + auditar el PLAN adversarialmente
- work_plan.md APPROVED + STRATEGY_<ID>.md + AUDIT_<ID>.md (con TP Check).
- execution_log.md IN_PROGRESS, STATE.md ACTIVE_TICKET/IN_PROGRESS.
- **execution_log usa `**Estado:** X` INLINE (dobles asteriscos), NO `## Estado`
  heading** (el validador lee por el marcador; heading -> UNKNOWN -> error).
- **AUDITAR EL PLAN ADVERSARIALMENTE ANTES del Builder** (leccion 021g: un auditor
  fresh-context cazo 2 BLOCKER que el Manager + 2 pasadas no vieron). Verificar cada
  claim del plan contra codigo vivo: call-graph, imports a retirar, survivor set,
  0 importadores externos, 0 tests que ejerzan lo retirado, 0 launchers con el flag.
- **Review 1 (mecanica canonica):** la verificacion sincronica intra-ticket sigue
  `prompts/manager_review.md` + `prompts/audit_agent_output.md` (filosofia CEM),
  MODULADA por el `deliverable_type` del plan (`code`/`mixed` corren gates focales;
  `documentation`/`research` verifican existencia+contenido, no `ruff`/`pytest`).
  Este prompt NO reimplementa esa mecanica: la referencia. Si diverge, prevalece
  `manager_review.md` para el metodo de Review y este prompt para el modo code-only.

### 3. Builder: implementar, PERSISTIENDO incrementalmente a disco
Leccion 021g: el Builder iteraba en memoria y agotaba tanda sin guardar. Instruccion
explicita: persiste cada fase a disco. Para una retirada limpia y bien acotada de un
solo fichero, el orquestador puede implementar directo (evita el fallo de "iterar en
memoria"); para cambios mayores, delegar al Builder con la instruccion de persistir.

### 4. Correr los gates YO MISMO (el Builder suele dejar la fase de gates incompleta)
- `git grep -i` del token retirado en el scope = 0 (CASE-INSENSITIVE; leccion 021d:
  un grep sin `-i` dejo escapar "Goose"/"Claw" con mayuscula que Review 2 cazo).
- `py_compile` + `ruff check` verdes.
- Encoding-guard: si el fichero esta en CORE_SCOPE_REGRESSION, dejarlo ASCII limpio.
  **NO reproducir bytes de mojibake en el work_plan/execution_log** (son tracked y
  estan en el scope del encoding-guard; describir el mojibake de forma abstracta).
- El test-pin de comportamiento (la ruta que SOBREVIVE sigue viva).
- Suite: `run_pytest_safe.py --level all` SIN `--` (con `-- --level` el wrapper da
  exit 0 aunque pytest aborte = false-green). **LEER "N passed / N failed" del output
  REAL, NUNCA el exit code del wrapper** (leccion capital, confirmada varias veces:
  el wrapper da exit 0 con "1 failed" Y da exit 1 sin ningun failed cuando hay
  state-leak de proyecciones gitignored). **NO correr suites CONCURRENTES ni una
  suite CONCURRENTE con un Review 2 que muta** (false-fail por solapamiento).

### 5. Review 2 fresh-context OBLIGATORIO (toca superficie del motor = alto blast)
Un auditor fresh-context que VERIFICA cada claim y **MUTA produccion para probar que
las barreras/retiradas son genuinas** (mutation-to-prove: romper el fix debe romper
el test; quitar un import "conservado" debe romper el fichero). Un test verde +
docstring plausible != barrera. **Secuenciar** el Review 2 respecto a la suite (no
solapar mutaciones con una corrida). Restaurar toda mutacion (verificar md5/diff).
La consigna adversarial de Review 2 (intentar tumbar la conclusion, buscar
falso-verde/scope-creep/mock-drift) es la de `prompts/manager_review.md` (Review 2);
este prompt la aplica al modo code-only, no la reimplementa. **Aislamiento de rama
(leccion 021u):** el mutation-verify solo tiene dientes si el fixture AISLA la rama
mutada (fuerza el estado donde ESA rama es la unica que decide el veredicto); un
fixture que satisface el assert por 2 rutas redundantes da falso-verde.

### 6. Cierre commit-directo
- Marcar work_plan/execution_log/STATE COMPLETED (inline).
- Commit con el ID en el mensaje. **PATH del venv prependido para los hooks
  `language:system`**: `PATH="<_dev>/.venv/Scripts:$PATH" git commit -F -`.
  (Trampa CRLF: reescribir una linea via Python puede meter CRLF -> el hook
  mixed-line-ending lo auto-arregla y ABORTA el commit; re-stage + re-commit.
  Editar via Edit tool no lo provoca.)
- **Co-Authored-By DINAMICO**: firmar con la identidad REAL del modelo ejecutor de
  ESA sesion, no un valor hardcoded. Si no puedes determinar tu modelo con certeza,
  OMITE el trailer (mejor sin co-autoria que con una falsa).
- **Push AGRUPADO al final de sesion, con autorizacion explicita del usuario** (NO push
  por ticket: el usuario controla cuando el trabajo sale a remoto; incidente 2026-07-11).
  Verificar HEAD == origin/main + arbol limpio tras el push autorizado.

### 7. Verificar YO cada claim del Builder/Manager
No fiarse del reporte; verificar con evidencia (diff/exit-code/test/grep), no con el
auto-reporte. Leccion repetida toda la serie.

---

## CIERRE DE LA CADENA (tras el ultimo ticket)

1. **Auditoria adversarial de cierre de la CADENA** (no solo por-ticket): un auditor
   fresh-context sobre los N commits JUNTOS caza problemas de SEAM (referencias
   colgantes entre tickets, invariantes que solo cambian con toda la cadena aplicada,
   coherencia de la frontera "preservar historia"). Los Review 2 por-ticket no ven
   los seams. **Metodo canonico:** usar `prompts/audit_pipeline_codeonly.md` (la
   variante CODE-ONLY, que hereda de la base `prompts/audit_pipeline.md`): cierre
   manual = caso por defecto, evidencia por commits git + bloque de cierre del
   workspace, integridad por `check_motor_pristine` + aterrizaje en origin/main, y
   los warnings `accepted_advisories` de `--validate` NO cuentan como hallazgo. Este
   prompt referencia ese metodo, no lo reimplementa.
2. **Cierre canonico adaptado** (`prompts/orchestrator_session_close_full_audit.md`):
   Bloques 1 (salud) / 2 (adversarial sobre diffs) / 4 (memoria) / 5 (follow-ups)
   aplican; **Bloque 3 (`--session-close`) es N/A code-only**.
3. **Backlog**: archivar los tickets cerrados a `_archive/backlog_done.md` en el
   WORKSPACE (fila con `completed` + `commit:<sha>` + bloque de cierre). Registrar
   follow-ups con evidencia. `check_backlog_contract.py` OK.
4. **Memoria**: promocionar solo aprendizajes con evidencia verificable.

---

## Los riesgos codificados (barreras de este pipeline)

1. **El exit code del wrapper NO es un veredicto de suite**: leer "N passed/failed".
   El wrapper da exit 0 con fallos reales Y exit 1 sin fallos (state-leak). Vector
   registrado como WOT-2026-021m (falso-positivo del recolector de salud).
2. **El grep de DoD/retirada DEBE ser case-insensitive** (`-i`).
3. **Auditar el PLAN adversarialmente ANTES del Builder** (caza BLOCKER que el Manager
   no ve). **Review 2 fresh-context que MUTA** (unica prueba de barrera genuina).
4. **No solapar suite + mutador** (Review 2 concurrente = false-fail).
5. **La skill es puntero, no fuente**: `skills/orchestrate-pipeline-codeonly/SKILL.md`
   remite aqui. Si diverge, prevalece este prompt.
6. **Barrera pre-Builder "0 consumidores runtime"** en el preflight: lo que hace
   segura una retirada de codigo deprecated. No basta topologia + SHAs.

---

## Restriccion dura

- SOLO para `delivery_authority: repo_motor` + `_dev` + code-only. Fuera de eso,
  usar `/orchestrate-pipeline` canonico.
- NO usar bus (`--session-close`/`--bootstrap-ticket`/`--mark-ready`): estan
  bloqueados en code-only. Cierre = commit-directo.
- El backlog vive en el WORKSPACE, no en `_dev`; archivar alli.
