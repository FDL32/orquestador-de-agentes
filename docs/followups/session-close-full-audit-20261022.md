# Auditoria de cierre full-audit -- 2026-10-22 (RETOMADA Y CERRADA)

> **Retomada 2026-10-22, misma tarde.** La sesion hermana termino su implementacion
> (`bba39d70`, WOT-2026-114j) y el arbol de esta worktree volvio a estar bajo control
> exclusivo de una sola sesion. Continua desde la interrupcion documentada abajo. Todo lo de
> la Seccion "Lo verificado ANTES de la interrupcion" sigue vigente (no se reproduce); lo nuevo
> va en "## RETOMA" al final.

> Ejecutada per `prompts/orchestrator_session_close_full_audit.md`, con Bloque 3 y paso 8.ter
> omitidos por autorizacion explicita del usuario (el ticket activo en
> `orquestador_de_agentes_workspace` -- `WOT-2026-026x`, `STATUS: COMPLETED` -- no tiene relacion
> con el trabajo de esta sesion). repo_motor = esta worktree (HEAD `e35803ab` al iniciar).
> repo_destino = `C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_workspace`.

## INTERRUPCION (leer primero)

A mitad del Bloque 2, `git status --porcelain` paso de limpio a:
```
 M AGENTS.md
 M docs/registry/reference_keys.md
?? .agent/rules/common/wot_026t_orden_trabajo_forense.md
```
Contenido verificado: es **exactamente** el texto de implementacion T1+T2+T3 preparado en
`docs/followups/session-hop-arranque-frio-20261022.md` para la sesion hermana. Mtimes de los
3 ficheros: `16:43:54` - `16:44:14` (minutos antes de detectarlo) -- otra sesion esta
escribiendo en este MISMO working tree, en este MISMO momento.

`origin/main` del motor tambien avanzo 1 commit (`5329a994`, de otra sesion, no relacionado con
este flight) desde que este cierre empezo -- divergencia normal en una rama de feature, no
alarmante por si sola.

**Por que esto detiene la auditoria (5.ter del propio prompt que se esta siguiendo):** ninguna
corrida de auditoria o de suite es valida mientras otra superficie muta el arbol
concurrentemente. Se DETIENE aqui, se documenta el hallazgo, y NO se continua Bloque 2 completo
ni se intenta Bloque 4/5 contra un arbol que no es exclusivamente de esta sesion ahora mismo.

**Recomendacion:** coordinar con la sesion hermana (via SendMessage o similar) antes de retomar
este cierre -- probablemente conviene que termine su implementacion y la commitee primero, y
este cierre se re-ejecute despues sobre un HEAD mas reciente y un arbol limpio.

## Lo verificado ANTES de la interrupcion (VERIFICADO, con evidencia)

### Bloque 1 -- auditorias estructurales (parcial)

- **3.4 Cableado de hooks:** `check_guard_wiring.py` -> `exit 0`, "OK: cada guard sin cablear
  esta declarado". `check_hook_interpreter.py --hooks-dir <common-git-dir>/hooks` -> `exit 0`,
  "PASS: hook interpreters ok (pre-commit, pre-push)".
- **3.5 Portabilidad:** `check_distribution_agnostic.py` -> `exit 0`, "62 entradas -> 171
  ficheros versionados auditados", 0 hits en las 3 agujas aplicables (username `fdl` SKIPPED por
  longitud <4, documentado como comportamiento esperado del propio script). `git ls-files
  destinos/ .agent/runtime/reviews/ .agent/runtime/audit/` -> 0 lineas. Topologia: `git worktree
  list` -> 34 entradas; `git remote get-url origin` ->
  `https://github.com/FDL32/orquestador-de-agentes.git`.
- **3.6 Trigger de suite:** `.agent/runtime/pytest-safe/run_history.jsonl` **AUSENTE** en la raiz
  de repo_motor (solo hay ficheros `heartbeat-*.jsonl`, sin `run_history.jsonl` ni
  `last-run.json`). `disparador NO VERIFICABLE: run_history.jsonl AUSENTE en <repo_motor>`. Esto
  es coherente con la politica del vuelo ("la suite va la ULTIMA, justo antes del push"): el
  push de este vuelo esta diferido a la sesion hermana / cierre del vuelo completo, asi que
  todavia no ha corrido `--level all` en esta worktree. **No es un defecto de este cierre, es el
  orden esperado** -- pero lo tiene que correr quien finalmente pushee, antes de publicar.
- **Collector determinista** (`collect_system_health.py --mode auto`): `ruff_motor` exit 0,
  `validate_motor` exit 0, `discover_skills_contract` exit 0, `guard_wiring` exit 0,
  `motor_pristine_snapshot` exit 0, `ruff_destino` exit 0, `validate_destino` exit 0. Hallazgo
  AUTOMATICO marcado `blocking: true` por el propio collector:
  `authoritative_health.repo=motor, verdict=unknown, findings=["pytest_safe_last_run_missing"]`
  -- mismo hallazgo que el punto anterior, confirmado por dos vias independientes (el collector
  y la lectura directa del directorio). `non_authoritative_health.repo=destino` reporta
  `verdict=stale, exit_code=4` -- **no bloqueante para este cierre** (es el estado de un repo
  que esta sesion nunca toco; declarado `is_delivery=false` por el propio collector).
  Reporte completo del collector:
  `orquestador_de_agentes_workspace/.agent/audits/system_health/general_audit_20261022_1442/`.
- Bloques 1.2 (`audit_complete_motor_destination.md`) y 1.3 (`audit_portability_legacy_surface.md`)
  **NO EJECUTADOS** -- la interrupcion llego antes de alcanzarlos. Pendientes de una re-ejecucion.
- **2.5 (artefactos de sesion):** `init_session_scratch.py --project-root
  orquestador_de_agentes_workspace list` -> una sola sesion, `20260716-2139-4762d83-da37`
  (2026-07-16, `lock_state: stale`) -- **no pertenece a esta sesion** (3 meses de antiguedad, esta
  sesion nunca invoco `init_session_scratch.py`). Bloque 2.5 declarado **SKIP real**: sin
  sesiones propias que auditar.

### Bloque 2 -- pasada adversarial sobre el codigo generado (PARCIAL, interrumpida)

- Commits de la sesion: `a374ce09^..e35803ab` (13 commits, WOT-2026-114a a 114i), todos
  documentados en `docs/followups/session-hop-arranque-frio-20261022.md` con su resumen.
- Unico cambio de CODIGO Python real de toda la sesion: `scripts/check_reference_keys.py`
  (introducido en 114d). El resto son ediciones de prosa/markdown (`AGENTS.md`, `.agent/rules/
  common/*.md`, `docs/registry/*`, `docs/followups/*`).
- **Barrera mutation-verified, DEMOSTRADA** (COPY-RESTORE, nunca `git checkout --`):
  1. Mutacion del regex de cita (`\[([A-Z]\d+)\]` -> `\[([A-Z]\d*)\]`): **los 11 tests
     SIGUIERON EN VERDE** -- gap real de cobertura (ninguna fixture de test cubre una cita sin
     digito, p.ej. `[F]`). Restaurado por copia, confirmado `git diff --stat` vacio tras
     restaurar.
  2. Mutacion del chequeo de ancla huerfana (`if not anchors_for(letter).get(key):` -> `if
     False:`): **2 de 11 tests cayeron a ROJO** inmediatamente
     (`test_broken_anchor_in_bracket_format_is_detected` y otro). **La barrera central del
     guard (deteccion de cita sin ancla) SI esta mutation-verified.** Restaurado por copia,
     `git diff --stat scripts/check_reference_keys.py` vacio tras restaurar, suite focal verde
     de nuevo (11 passed).
  - **Hallazgo nuevo, NO bloqueante, candidato a backlog:** la mutacion (1) revela que el guard
    no tiene un test negativo para "cita de letra valida sin digito" (`[F]`). Bajo-riesgo (el
    patron de citas reales siempre lleva digito por convencion documentada en
    `docs/registry/reference_keys.md`), pero es un gap de cobertura real, no solo teorico.
- **Resto del Bloque 2 (encuadre completo `audit_agent_output.md`, triage 5.bis, 5.ter) NO
  completado** -- interrupcion llego aqui.

### Bloques 4 y 5

**NO EJECUTADOS.** La interrupcion llego durante el Bloque 2, antes de memoria o follow-ups.

## Estado declarado de este cierre

**CIERRE NO COMPLETADO.** No se corrio el Bloque 3 (por autorizacion explicita, dado el ticket
ajeno en el destino) y el resto de la auditoria (Bloque 1.2/1.3, resto del Bloque 2, Bloque 4,
Bloque 5) quedo interrumpido por mutacion CONCURRENTE del arbol de trabajo por otra sesion. El
estado git real de esta sesion sigue siendo el que ya declara
`docs/followups/session-hop-arranque-frio-20261022.md`: 13 commits locales en
`FDL32/optimizacion-arranque-frio-cont-20261022`, remoto intacto salvo el commit no relacionado
`5329a994`, push diferido con politica "Push por vuelo".

**Nada de este informe se escribio sobre codigo mutado por la otra sesion** -- todas las
verificaciones de arriba corrieron SOBRE EL CODIGO YA COMMITEADO (`e35803ab`) antes de que la
mutacion concurrente empezara, y la mutation-verify se aplico y revirtio por copia sobre un
fichero que la otra sesion no estaba tocando (`check_reference_keys.py`), confirmado limpio
despues.

## Candidatos de follow-up (preparados, NO escritos todavia -- Bloque 5 no se alcanzo)

1. `scripts/check_reference_keys.py`: falta test negativo para cita sin digito (`[F]`). Bajo
   riesgo, evidencia: mutacion (1) de arriba.
2. Re-ejecutar este cierre completo (Bloques 1.2/1.3, resto de 2, 4, 5) cuando el arbol de esta
   worktree vuelva a estar exclusivamente bajo control de una sola sesion.

## RETOMA (2026-10-22, post WOT-2026-114j, HEAD bba39d70)

### Confirmacion: arbol limpio, HEAD avanzado

`git status --short` -> solo este fichero sin trackear (el propio informe). `git rev-parse HEAD`
-> `bba39d70` (WOT-2026-114j: colapsa T1/T2/T3 de AGENTS.md a modulo de referencia + fixes 5-8,
de la sesion hermana).

### Re-medicion independiente de los gates (VERIFICADO, no auto-reporte)

`uv run python scripts/measure_agents_md_units.py --json` a `bba39d70`:
`codex_bytes=40576/32768=1.2383x (deficit 7808 B)`, `claude_chars=42505/40000=1.0626x (deficit
2505 chars)`. Coincide exactamente con el auto-reporte de la sesion hermana -- CONFIRMADO, no
solo citado. Ningun gate cierra; mejora real desde el inicio del flight: 1,87x/1,58x ->
1,2383x/1,0626x.

### `.gitignore` de `.loop_bundle_optimizacion.md`: VERIFICADO funcional

`git check-ignore -v .loop_bundle_optimizacion.md` -> `rc=0`, match en linea 7 del `.gitignore`
(patron para ese nombre de fichero). El fix 8 es durable: el patron que creaba el debris (un
`git add -A` de bucle) ya no puede reintroducirlo silenciosamente.

### T4 confirmado intacto (spot-check)

Lineas 226-269 de `AGENTS.md` siguen conteniendo el Gate 2 completo ("Condiciones de rechazo...",
"Riesgo residual declarado...") -- la exclusion de T4 que autorizo el bucle RONDA 4 se respeto.

### Bloque 1.1/1.2 (auditorias estrategica y de portabilidad/legacy)

DEFERIDO el censo generico repo-wide, por rigor proporcional (esta sesion es 100% prosa/markdown
mas un guard nuevo pequeno, no toco bus/supervisor/seguridad). En su lugar se aplico el metodo de
la auditoria de portabilidad de forma ACOTADA a los artefactos NUEVOS de esta sesion, que es la
superficie realmente en riesgo.

**HALLAZGO REAL, VERIFICADO (severidad Media-Alta): los 4 artefactos nuevos de
referencia-bajo-demanda de este flight NO estan en `MANIFEST.distribute`.**

`grep -n "wot_026t\|cem_v0_evidencia_forense\|reference_keys\|check_reference_keys"
MANIFEST.distribute` -> 0 hits (rc=1). `MANIFEST.distribute` lista explicitamente, archivo por
archivo (sin wildcard de directorio), una seccion "Reglas de referencia bajo demanda" con 12
ficheros de `.agent/rules/common/*.md`. Los 4 artefactos que este flight creo para el MISMO
patron estan AUSENTES de esa lista: `.agent/rules/common/cem_v0_evidencia_forense.md` (114d),
`.agent/rules/common/wot_026t_orden_trabajo_forense.md` (114j), `docs/registry/reference_keys.md`
(114d, la leyenda que ambos modulos necesitan), `scripts/check_reference_keys.py` +
`tests/unit/test_check_reference_keys.py` (114d, el guard que valida el mecanismo entero).

Impacto: un destino que instale/sincronice DESPUES de este flight recibiria `AGENTS.md` citando
`[F1]`-`[F7]` y `[T1]`-`[T2]` sin los ficheros a los que esas citas apuntan, y sin el guard que lo
detectaria. No es legacy, es un gap de portabilidad introducido por este mismo flight. Fix de 1-3
lineas, bajo riesgo, sin cambio de contrato -- pero NO bloquea ningun gate obligatorio hoy
(`check_distribution_boundary.py` valida la direccion opuesta), asi que no califica como hotfix
autonomo. Se registra como follow-up (ver Bloque 5 abajo), no se aplica aqui.

### Bloque 1.3.6/1.3.7: sin cambios desde la interrupcion (`run_history.jsonl` sigue AUSENTE en
repo_motor, esperado: la suite corre al final antes del push, que sigue diferido).

### Bloque 2 (cierre del encuadre, commits a374ce09^..bba39d70, 14 commits WOT-2026-114a-j)

`git log --oneline a374ce09^..bba39d70` -> 14 commits. `git diff --stat a374ce09^..bba39d70 --
'*.py'` -> SOLO `scripts/check_reference_keys.py` y `tests/unit/test_check_reference_keys.py`
(ya mutation-verified en la pasada previa: 2/11 tests caen en la mutacion del chequeo de ancla
huerfana, barrera central CONFIRMADA; gap de cobertura de cita-sin-digito `[F]` tambien
confirmado, sigue sin test). Resto del diff: 100% markdown/prosa. Sin mas superficie de
mutation-verify que aplicar. false-green/root-equivocado/fixture-drift/scope-creep/mock-drift/
floor-assertion: ninguno aplica a prosa pura; floor-assertion evaluado contra el guard, no
aplica (sus asserts son de presencia/ausencia de match, no umbrales numericos). Triage 5.bis: el
unico hallazgo nuevo (gap `[F]` sin digito) clasifica backlog/follow-up (deuda real, no bloquea,
bajo riesgo). 5.ter: no hay `last-run.json` huerfano, no aplica (ninguna suite completa ha
corrido en esta worktree todavia).

**PUNTO DE CONTROL:** sesion VERDE y RECONCILIADA. Ningun false-green, ninguna contradiccion
entre lo declarado por la sesion hermana y lo verificado de forma independiente.

### Bloque 2.5.j: resolucion de la clase `handoff_prompt_defect`

La premisa de la instruccion original ("propone una 6a clase") esta OBSOLETA/YA APLICADA.
Verificado por dos vias: (1) `PROPUESTA_cierre_produce_mejor_arranque.md` linea 3 declara
"Estado: APLICADA en fd3943e"; (2) `git cat-file -t fd3943e` -> `commit`; `git merge-base
--is-ancestor fd3943e HEAD` -> `rc=0` (ES ancestro del HEAD actual del prompt en repo_motor). El
prompt ya leido integro en esta sesion (lineas 312-317) efectivamente declara 8 clases
incluyendo `handoff_prompt_defect`. Conclusion: nada que aplicar, declarada OBSOLETA.

**Hallazgo NUEVO de `handoff_prompt_defect`:** `prompts/session_hop.md` no declara un modo para
topologia motor CODE-ONLY (sin `repo_destino`) -- esta misma sesion improviso un fallback a mano
(`docs/followups/session-hop-arranque-frio-20261022.md`). Dedupe verificado: 0 hits en las dos
PROPUESTA existentes sobre "CODE-ONLY"/"sin repo_destino". Registrado en
`orquestador_de_agentes_workspace/.agent/planning/
PROPUESTA_mejoras_session_hop_motor_codeonly_20261022.md`, marcado explicitamente **sin
verificar por bucle** (sin presupuesto en este cierre para correr un bucle adversarial real).
NO se aplico nada al prompt canonico.

### Bloque 4 -- candidatos de memoria (SOLO PROPUESTA, nada escrito, pendiente confirmacion humana)

1. Patron "refutacion-corta + caso-forense-largo-a-modulo" (CEM v0 + T1/T2 de WOT-2026-026t):
   mover el caso forense a un modulo referencia-bajo-demanda con anclas, dejando en la cuspide
   la regla + la clausula de mecanismo/alcance que el bucle identifico como indispensable.
2. Correccion metodologica de Fase 0: `build_llms.py` leyendo `AGENTS.md` completo no es veto
   universal de movilidad -- es proyeccion no cargada en el arranque en frio.
3. Distincion T1-T3 (evidencia historica, movible) vs T4 (politica operativa viva, NO movible) --
   5/6 lentes independientes en RONDA 4.
4. Gap de portabilidad: un modulo referencia-bajo-demanda nuevo no se distribuye solo, hay que
   anadirlo a `MANIFEST.distribute` en el MISMO commit que lo crea (hallazgo de este cierre).

### Bloque 5 (menos 8.ter) -- follow-ups PREPARADOS, NO escritos

`orquestador_de_agentes_workspace/.agent/collaboration/backlog.md` es una cola viva de gran
escala (>340 filas archivadas, decenas vivas) con dedupe obligatorio de tres superficies via
herramientas dedicadas (`backlog_db_compare.py --emit-recibo`, `find_similar_signals.py` contra
corpus >1000 entradas) que este cierre no corrio. Escribir a mano sin el recibo mecanico seria
"alta sin dedupe" (prohibido por el propio Bloque 5/8.bis). Se preparan los candidatos, la
escritura mecanica queda para una pasada `backlog-admit` dedicada:

1. `MANIFEST.distribute` no incluye los 4 artefactos nuevos de referencia-bajo-demanda (Media-Alta).
2. `check_reference_keys.py` sin test negativo para cita sin digito `[F]` (Baja).
3. Gate Codex de cuspide sigue en rojo (1,2383x) tras 114a-114j -- item de DECISION pendiente
   (segunda Fase 0, o diseno alternativo T4), no trabajo comprometido.
4. Bug `external_directory` de opencode/glm, reproducido 4 veces ya en este flight.
5. `PROPUESTA_mejoras_session_hop_motor_codeonly_20261022.md` (nueva, sin verificar por bucle) --
   su promocion a ticket formal tambien pendiente de la misma pasada de admision.

## Estado final declarado de este cierre

**AUDITORIA COMPLETADA** (Bloques 1 acotado + 2 + 2.5.j + 4-propuesta), con dos exclusiones
autorizadas por el usuario (Bloque 3, paso 8.ter) y dos diferimientos por riesgo/rigor
proporcional (censo generico 1.1/1.2 mas alla de artefactos nuevos; escritura mecanica de
Bloque 5 al backlog compartido). Ningun gate obligatorio de esta sesion esta en rojo
(ruff/guard-wiring/distribution-agnostic/reference-keys todos `exit 0`); el gate de CUSPIDE de
`AGENTS.md` (Codex 1,2383x) es un objetivo de PRODUCTO de la Palanca A, no un gate que bloquee
el cierre de esta sesion.

**Cierre git real:** 14 commits locales en `FDL32/optimizacion-arranque-frio-cont-20261022`
(`a374ce09`..`bba39d70`), mas este informe. Remoto intacto salvo el commit no relacionado
`5329a994`. Push diferido por politica "Push por vuelo" -- pendiente de autorizacion humana
explicita para publicar todo el flight de una vez.

## Pasada de verificacion independiente y propuesta consolidada (2026-10-22, pre-escritura)

Re-verificacion propia de las afirmaciones clave del informe de arriba, antes de escribir nada en
memoria o backlog (mismo patron de las 4 rondas previas de este flight).

### Confirmaciones (re-derivadas, no re-citadas)

- **Gap `MANIFEST.distribute` CONFIRMADO**, a `HEAD=3ba8adb7`: `grep -n "wot_026t\|cem_v0_evidencia_forense\|reference_keys\|check_reference_keys" MANIFEST.distribute` -> `rc=1`, 0 hits. La seccion `# Reglas de referencia bajo demanda (piramide, pasada 1)` (linea 98) lista 12 ficheros `.agent/rules/common/*.md`, uno por linea, SIN wildcard de directorio -- confirma el patron de edicion exacto para el fix: anadir 5 lineas (4 artefactos + su test), rutas bare, sin comentario inline (misma regla FLT que el resto del repo).
- **`check_distribution_boundary.py` confirma la direccion del hueco**: su propio docstring dice literalmente que valida "every manifest entry resolves to >=1 tracked file" (entrada->fichero), **la direccion CONTRARIA** a "todo fichero relevante esta en el manifest". Ningun gate existente cazaria este hueco -- el hallazgo del cierre es real y no esta cubierto.
- **Gates re-medidos de nuevo, mismo HEAD de contenido** (`3ba8adb7` solo anadio el propio informe, no toco `AGENTS.md`): `codex_bytes=40576/32768=1,2383x`, `claude_chars=42505/40000=1,0626x` -- identico al numero ya citado. CONFIRMADO por tercera vez independiente (hermana -> cierre-retomado -> esta pasada).
- `tests/unit/test_check_reference_keys.py` existe y es el fichero correcto (ruta verificada).

### Correccion 1: candidatos de memoria 1 y 3 describen la MISMA tecnica, no dos -- fusionar

El candidato 1 (patron refutacion-corta + caso-forense-a-modulo) y el candidato 3 (T1-T3 movible
vs T4 no-movible) no son dos lecciones independientes: el candidato 3 es la CONDICION DE
APLICABILIDAD del candidato 1 (cuando el patron aplica y cuando no). Escribirlos como dos entradas
de memoria separadas duplica contexto y arriesga que diverjan con el tiempo (la misma leccion que
este mismo flight ya aprendio sobre duplicados de ficha, WOT-2026-114's regla DEDUPE). Se fusionan
en UNA entrada de memoria.

### Correccion 2: ningun duplicado real entre los 5 follow-ups

Verificado leyendo las 5 evidencias citadas: ninguna pareja comparte causa raiz (gap de manifest,
gap de test, gate de producto pendiente de decision, bug de infraestructura ajeno, prompt sin modo
CODE-ONLY). Se mantienen las 5, sin fusion.

### Correccion 3: el gap de `MANIFEST.distribute` merece arreglo YA, no diferido -- recomendacion, no decision tomada

Es un fix de 5 lineas, mecanico, sin ambiguedad de diseno, que CIERRA un hueco de portabilidad que
este MISMO flight introdujo (no es deuda preexistente). Dejarlo en backlog significa que, si
alguien sincroniza un destino ANTES de que el ticket de backlog se atienda, hereda `AGENTS.md`
citando ficheros que no existen ahi. Recomendacion: aplicarlo como commit propio ANTES de declarar
el flight cerrado, no como ticket de backlog disperso. (Decision final: del usuario/bucle, no
autoaplicada aqui.)

### Texto final de los 2 candidatos de memoria (fusionados de 4 a 3, listos para escribir tal cual)

**Memoria 1 -- `wot-026t-split-forense-aplicabilidad.md`** (type: project)
```markdown
---
name: wot-026t-split-forense-aplicabilidad
description: Patron de split AGENTS.md (refutacion corta + caso forense a modulo) y su condicion de aplicabilidad (evidencia historica si, politica operativa viva no)
metadata:
  type: project
---

Para reducir el tamano de AGENTS.md sin perder contenido: separar cada regla en (a) la
frase de refutacion corta + su clausula de MECANISMO/ALCANCE indispensable, que se queda en
la cuspide, y (b) el caso forense extenso (fechas, cifras, incidente), que se muda a un
modulo `referencia-bajo-demanda` con anclas `<a id="x#">`/`**X#.**` citado `[X#]`, validado
por `scripts/check_reference_keys.py`. Aplicado con exito en CEM v0 (WOT-2026-114d/e) y en
T1/T2 de WOT-2026-026t (WOT-2026-114j).

**Condicion de aplicabilidad (NO todo es movible):** el patron solo aplica a EVIDENCIA
HISTORICA (contexto opcional que explica por que existe una regla ya completa por si sola).
NO aplica a POLITICA OPERATIVA VIVA que un agente necesita leer EN EL MOMENTO de decidir (p.
ej. los criterios de rechazo de un gate de push con trafico concurrente) -- moverla sin que
el puntero declare la condicion de disparo explicita convierte una regla accionable en una
que un agente puede ignorar sin saber que necesitaba consultarla. Confirmado por bucle
adversarial RONDA 4 de WOT-2026-026t (5 de 6 lentes independientes rechazaron mover esa
pieza, [[wot-026t-portability-manifest-gap]] documenta el follow-up relacionado).

**Why:** medido en 2 iteraciones reales de este mismo proyecto (CEM v0 y WOT-2026-026t);
la distincion T1-T3-vs-T4 evito aplicar el patron fuera de su alcance correcto.
**How to apply:** antes de proponer mover un bloque de AGENTS.md a un modulo de referencia,
clasificalo primero como evidencia-historica o politica-operativa-viva.
```

**Memoria 2 -- `fase0-build-llms-no-es-veto-universal.md`** (type: project)
```markdown
---
name: fase0-build-llms-no-es-veto-universal
description: build_llms.py leyendo AGENTS.md completo para llms-full.txt NO veta el movimiento de contenido fuera de AGENTS.md -- es proyeccion derivada, no carga de arranque en frio
metadata:
  type: project
---

La medicion Fase 0 de reduccion de `AGENTS.md` (Palanca A) tenia un criterio PASO 3(d) que
trataba `build_llms.py` (lee `AGENTS.md` completo para `llms-full.txt`) como veto universal
de movilidad para TODAS las unidades nivel-2. Eso es incorrecto: `llms-full.txt` es una
PROYECCION derivada (consumida por crawlers/docs externos), nunca cargada en el arranque en
frio del agente. Mover contenido fuera de `AGENTS.md` reduce igual los dos gates reales
(`codex_bytes` sobre `AGENTS.md`, `claude_chars` sobre `CLAUDE.md+@AGENTS.md`) aunque
`llms-full.txt` siga reflejando el fichero via su propia sincronizacion.

**Why:** confirmado en la practica -- CEM v0 (bloqueado por este criterio en el informe
Fase 0R original) se movio igualmente en WOT-2026-114d/e y el gate SI mejoro la cantidad
medida.
**How to apply:** al clasificar unidades de `AGENTS.md` por movilidad (PASO 3 de
`doc_optimization.md`), distingue "consumidor que carga en el arranque en frio" (veto real)
de "consumidor que genera una proyeccion derivada no cargada en frio" (no es veto).
```

### Fichas de backlog (5, listas para `backlog-admit`, IDs por asignar en el momento real de alta)

1. **Titulo:** `MANIFEST.distribute` no incluye 4 artefactos referencia-bajo-demanda del flight 114
   **Estado:** pending | **delivery_authority:** repo_motor | **Prioridad:** Alta (recomendado
   atender YA, ver Correccion 3) | **Origen:** session-20261022-optimizacion-arranque-frio-114
   **Evidencia:** `grep` 0 hits citado arriba; rutas exactas: `.agent/rules/common/
   cem_v0_evidencia_forense.md`, `.agent/rules/common/wot_026t_orden_trabajo_forense.md`,
   `docs/registry/reference_keys.md`, `scripts/check_reference_keys.py`,
   `tests/unit/test_check_reference_keys.py`. **Criterio de aceptacion:** las 5 rutas aparecen en
   `MANIFEST.distribute` bajo la seccion de referencia bajo demanda; `check_distribution_boundary.py`
   sigue en verde.
2. **Titulo:** `check_reference_keys.py` sin test negativo para cita sin digito (`[F]`)
   **Estado:** pending | **delivery_authority:** repo_motor | **Prioridad:** Baja | **Origen:**
   session-20261022-optimizacion-arranque-frio-114 | **Evidencia:** mutacion `\[([A-Z]\d+)\]` ->
   `\[([A-Z]\d*)\]` deja los 11 tests en verde. **Criterio de aceptacion:** nuevo test que falla
   contra esa mutacion.
3. **Titulo:** Gate Codex de cuspide AGENTS.md sigue en rojo (1,2383x) tras flight 114 -- decision
   de continuacion pendiente
   **Estado:** pending | **delivery_authority:** repo_motor | **Prioridad:** Media | **Origen:**
   session-20261022-optimizacion-arranque-frio-114 | **Evidencia:** medicion de este informe.
   **Criterio de aceptacion:** NO es trabajo comprometido -- es un item de DECISION (segunda
   Fase 0, o diseno alternativo T4 default-deny) que el usuario debe resolver antes de convertirse
   en ticket de implementacion.
4. **Titulo:** Bug `external_directory` de opencode/glm -- 3 fallos consecutivos (RONDA 1/2/3),
   streak ROTO en RONDA 4 -- no reabrir con una cifra inflada
   **Estado:** pending | **delivery_authority:** repo_motor | **Prioridad:** Baja |
   **Origen:** session-20261022-optimizacion-arranque-frio-114 | **Evidencia:** CORREGIDO contra
   el informe real de RONDA 4 (WOT-2026-114h, ya citado en esta misma conversacion): "y esta vez SI
   respondio, rompiendo la racha de 3 fallos consecutivos" -- NO son 4 fallos, son 3 seguidos
   (RONDA 1/2/3) y un 4o intento exitoso. Prioridad bajada de Baja-Media a Baja: el bug sigue
   siendo real (reproducido 3 veces) pero la ficha original de este informe exageraba su
   recurrencia. **Criterio de aceptacion:** reproducir el fallo bajo demanda con un caso minimo
   antes de declarar arreglo; mientras tanto no bloquea ningun bucle (la racha ya se rompio una
   vez).
5. **Titulo:** Promover `PROPUESTA_mejoras_session_hop_motor_codeonly_20261022.md` a ticket formal
   **Estado:** pending | **delivery_authority:** repo_motor | **Prioridad:** Media | **Origen:**
   session-20261022-optimizacion-arranque-frio-114 | **Evidencia:** `session_hop.md` no declara
   modo CODE-ONLY, esta misma sesion improviso el fallback. **Criterio de aceptacion:** la
   propuesta pasa por bucle adversarial real (pendiente, marcada "sin verificar por bucle") antes
   de aplicarse al prompt canonico.

Nada de esto se escribe todavia -- es el objeto de revision del bucle adversarial de la seccion
siguiente.

## Bucle adversarial (`EXPLORATORY-close-audit-memory-backlog-20261022`, DESIGN_REVIEW, resultado real)

Roster pedido (9, mismo que las 4 rondas previas del flight). **7/9 respondieron con contenido
sustantivo propio** (independientes): `challenger_codex` (BA05), `challenger_opencode_glm_5_2`
(BA06 -- respondio en su propio backend esta vez, NO cayo en fallback), `challenger_nan_qwen_flash`
(BA15), `challenger_gemini_gemini` (BA110), `challenger_mistral` (BA150), `challenger_llm7_minimax`
(BA172), `challenger_cohere_command` (BA130). **2/9 no cuentan como independientes:**
`challenger_nan_deepseek_flash` fallo tras DOS fallbacks (`tokenharbor_deepseek_flash` ->
`kilo_deepseek_flash`) con `RuntimeError: backend CLI sin respuesta tras 900s` -- sin respuesta
alguna, dispatch failure puro; `challenger_nvidia_kimi` cayo en fallback a `proposer_claude`
(BA01), que por el contrato de `ensemble_loop.md` NO cuenta como lente independiente (aunque su
contenido es util como senal: se nego honestamente a verificar sin acceso a `repo_motor`,
disciplina CEM aplicada correctamente por la propia sustitucion). 7 independientes esta MUY por
encima del minimo exigido.

### Veredicto por item (consolidado de las 7 lentes independientes)

**1. Gap `MANIFEST.distribute`: consenso UNANIME y el mas fuerte de toda la ronda -- FIX YA, commit
propio, ANTES de cerrar el flight.** Las 7 lentes independientes lo dicen sin excepcion (codex:
"ejecutar el fix... antes de declarar el flight cerrado"; opencode/glm: "debe resolverse en commit
propio antes del cierre, no en cola"; qwen: "ARREGLAR YA"; gemini: aplica el commit y DESCARTA la
ficha 1 del backlog por resolucion inmediata; mistral: "Recomendacion fuerte"; minimax: ficha 1
debe alinear titulo con "5 rutas"; cohere: ficha 1 "Critica"/"FIX NOW"). **No implementado por este
fork** -- fuera del alcance autorizado de este directive (solo propone, no aplica codigo fuera de
este informe); queda como recomendacion fuerte para que el coordinador/usuario lo autorice.

**2. Candidatos de memoria (2, fusionados): APROBADOS para escritura, con una aclaracion de alcance
necesaria, no un rechazo de contenido.** `opencode_glm_5_2` senalo que el formato frontmatter-YAML
"no existe en ninguna superficie" del repo y propuso convertirlo a filas L1/`CL-XX` -- **esto es
una confusion de sistema de memoria, no un defecto real**: los 2 candidatos de este informe son
para la memoria PERSISTENTE PROPIA del agente Claude Code (fuera del repo, en
`C:\Users\fdl\.claude\projects\...\memory\`, formato `name`/`description`/`metadata.type`/cuerpo
con **Why:**/**How to apply:**), NUNCA para `.agent/runtime/memory/` (L1 `observations.jsonl`, L2
`memory_rules.md` con prefijo `R-`) del propio repo -- son dos sistemas de memoria DISTINTOS y el
formato usado SI es el correcto para el sistema al que apuntan. El resto de lentes (mistral,
minimax, cohere) aprobaron el contenido "tal cual" o con ajustes de estilo menores (anclar T4 como
ejemplo negativo explicito en Memoria 1; corregir una frase incompleta en Memoria 2; destacar el
ejemplo de "politica operativa viva" con enfasis). **Hallazgo real que SI se corrige:** el enlace
`[[wot-026t-portability-manifest-gap]]` en Memoria 1 es colgante -- no corresponde a ninguna entrada
real planeada (fue una referencia suelta de este fork, no un candidato formal). Se retira, sustituido
por prosa directa citando el hallazgo del Bloque 1.1/1.2 sin enlace.

**3. Fichas de backlog (5): APROBADAS con evidencia solida, SIN solapamiento real entre ellas**
(confirmado independientemente por qwen: "NO SE SOLAPAN -- causas distintas"), pero **ninguna esta
"lista para escribir tal cual" en el formato de cola viva real** -- correccion importante de
`opencode_glm_5_2`, la unica lente que de verdad peino el `backlog.md` vivo del destino:
   - Ficha 1 (MANIFEST.distribute): si el fix se aplica ya (punto 1), la ficha debe registrarse
     como `done` con `commit:<sha>` en `Reactivation`, NUNCA como `pending` -- consenso de codex,
     qwen y gemini.
   - Ficha 3 (gate Codex en rojo): debe marcarse explicitamente como ITEM DE DECISION, no ticket de
     implementacion -- formato `DEC-no-aplica: <motivo>` sugerido por opencode/glm, eco en qwen
     ("decision-pendiente") y cohere ("item de decision"). Confirma el diseño ya declarado en el
     informe original (no era trabajo comprometido), solo pide formalizar la etiqueta.
   - Ficha 4 (bug opencode/glm `external_directory`): **la correccion de este fork ("3 fallos, no
     4") queda INCOMPLETA, no al reves** -- `opencode_glm_5_2` reporto en ESTE MISMO despacho
     ("la denegacion `external_directory` que sufri en este despacho") una reproduccion ADICIONAL
     del mismo modo de fallo (aunque parcial: esta vez SI dio contenido sustantivo, solo se quedo
     sin poder leer `repo_motor`). El patron real no es "3 fallos y racha rota en RONDA 4": es
     "3 fallos totales (RONDA 1/2/3), 1 exito total (RONDA 4), 1 fallo PARCIAL nuevo (este bucle)"
     -- mas inestable de lo que la correccion original declaraba, no mas estable. Texto de la ficha
     se actualiza abajo.
   - Fichas 1-5, TODAS: faltan las columnas de formato de cola viva real (`Prioridad | Ticket |
     Titulo | Scope | Estado | Depende de | Origen | Reactivation`), el dedupe de 3 superficies
     contra la cola VIVA (opencode/glm cito un vecino candidato real, `WOT-2026-043m`, sin
     verificar si es vecino genuino o falso positivo -- **ninguna de las 7 lentes tuvo acceso para
     confirmarlo**, queda como verificacion obligatoria de la propia pasada `backlog-admit`, no de
     este bucle) y un recibo DEC por ficha. **Esto confirma, no contradice, la decision original de
     este informe de diferir la escritura mecanica a una pasada `backlog-admit` dedicada** -- el
     bucle encontro exactamente los gaps de formato que esa herramienta esta disenada para cerrar.

### Texto corregido de Memoria 1 (retira el enlace colgante, resto sin cambios)

Sustituir, en el bloque `wot-026t-split-forense-aplicabilidad.md` de arriba, la frase final:
`...Confirmado por bucle adversarial RONDA 4 de WOT-2026-026t (5 de 6 lentes independientes
rechazaron mover esa pieza, [[wot-026t-portability-manifest-gap]] documenta el follow-up
relacionado).` por: `...Confirmado por bucle adversarial RONDA 4 de WOT-2026-026t (5 de 6 lentes
independientes rechazaron mover esa pieza; el gap de portabilidad de MANIFEST.distribute que este
mismo cierre encontro es un follow-up relacionado pero distinto, ver ficha de backlog 1).`

### Texto corregido de Ficha 4 (reemplaza la version de arriba)

**Titulo:** Bug `external_directory` de opencode/glm -- patron inestable (3 fallos totales, 1 exito,
1 fallo parcial nuevo en el bucle de este mismo cierre) -- NO declarar "racha rota"
**Estado:** pending | **delivery_authority:** repo_motor | **Prioridad:** Baja-Media (subida de
Baja: la recurrencia en el bucle de ESTE cierre, post-RONDA-4, muestra que el bug no esta resuelto
ni es raro) | **Origen:** session-20261022-optimizacion-arranque-frio-114 | **Evidencia:** RONDA
1/2/3 (3 fallos totales, bloqueo completo), RONDA 4 (1 exito total, "rompiendo la racha"), bucle
`EXPLORATORY-close-audit-memory-backlog-20261022` de este mismo informe (1 fallo PARCIAL: el lente
respondio con contenido real pero reporto denegacion de `external_directory` al intentar leer
`repo_motor` durante el despacho). **Criterio de aceptacion:** reproducir el fallo bajo demanda con
un caso minimo; el patron de 5 corridas (3 fallo / 1 exito / 1 parcial) sugiere intermitencia, no
un bug binario resuelto-o-no -- investigar la condicion que distingue exito de fallo antes de cerrar.

## Estado final declarado (post-bucle, 2026-10-22)

Recomendacion consolidada para el coordinador/usuario, nada escrito por este fork:
1. **Aplicar el fix de `MANIFEST.distribute` (5 rutas) en commit propio ANTES de declarar el flight
   cerrado** -- consenso unanime de 7/7 lentes independientes, el item de mayor prioridad de toda
   esta pasada.
2. **Escribir las 2 entradas de memoria** (con el enlace colgante retirado) en la memoria persistente
   propia de Claude Code -- aprobadas sin objecion de contenido real.
3. **Lanzar una pasada `backlog-admit` dedicada** para las 5 fichas (con ficha 1 pasada a `done` si
   el punto 1 ya aterrizo, ficha 3 con formato de decision, ficha 4 con el texto corregido de
   arriba) -- el bucle confirma que escribir a mano sin esa herramienta habria sido "alta sin
   dedupe", exactamente lo que el informe original ya evitaba.
