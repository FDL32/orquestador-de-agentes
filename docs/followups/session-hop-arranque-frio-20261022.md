# Puente de continuidad -- flight "optimizacion-arranque-frio" -- 2026-10-22

> **Nota de alcance:** `prompts/session_hop.md` (contract_id `cid-session-hop-v1`), leido
> ENTERO antes de escribir esto, esta diseñado para topologia `repo_motor + repo_destino`
> (escribe su salida en `<DESTINO_ROOT>/orchestrator_pipeline/arranques/`, usa
> `collect_session_state.py --project-root <DESTINO_ROOT>`, su "Restriccion dura" prohibe
> cristalizar estado en ficheros versionados DEL MOTOR). **Esta sesion es motor CODE-ONLY,
> sin `repo_destino`** -- verificado: `runtime.project_root.is_motor_code_only() == True`,
> no existe `orchestrator_pipeline/` en este checkout. El prompt NO aplica tal cual a esta
> topologia. Este documento es el fallback declarado: un brief de continuidad versionado
> en el propio motor, siguiendo la convencion ya establecida en este mismo vuelo (bloques
> `ESTADO_FRESCO` con comando + fecha, igual que los followups de Palanca A/CEM v0), no el
> output formal de `session_hop.md`.

## Estado [snapshot 2026-10-22, ACTUALIZADO tras 114g/114h]

- **HEAD:** `f093b8c4ea4563e312c932a2b0d90030d57477db` (WOT-2026-114h) -- `git rev-parse HEAD`.
- **Rama:** `FDL32/optimizacion-arranque-frio-cont-20261022` -- `git branch --show-current`.
- **Arbol:** limpio (`git status --porcelain` vacio) tras commitear este mismo update.
- **Commits locales sin publicar (12, remoto `origin/main` intacto):**
  `git log --oneline origin/main..HEAD`:
  ```
  f093b8c4 WOT-2026-114h: verificacion independiente + bucle RONDA 4 sobre split WOT-2026-026t
  3c704aca WOT-2026-114g: re-medicion Fase 0 post-114f, puente de sesion, auditoria docs raiz
  d4f730fc WOT-2026-114f: corrige comentario stale del hook check-reference-keys + documenta RONDA 3 del bucle
  264830ad WOT-2026-114e: acorta citas (ver F1) -> [F1] y anade anclas navegables
  b6cc0df2 WOT-2026-114d: claves de referencia (ver X#) + split quirurgico de CEM v0 en AGENTS.md
  1905f762 docs: resuelve 4 puntos adicionales de Codex (ronda 2) sobre el guard check_reference_keys.py
  8f520189 docs: corrige atribucion de DEC y refina spec del guard check_reference_keys.py (ronda 1 del bucle)
  426a2ef5 WOT-2026-114c: Fase 2 Palanca A -- mueve ## Vocabulario canonico a modulo
  e2bca241 WOT-2026-114b: retira Hermes (bundle de contexto para agente externo)
  8bdeb3f6 docs: propuesta de optimizacion Hermes/repo-audit + bucle adversarial (EXPLORATORY-hermes-repo-audit-20261022)
  ca8426e4 WOT-2026-114a: baseline E7 pinned e independiente de la funcion bajo prueba
  a374ce09 WOT-2026-114a: registro Hermes re-apuntable por source (Fase 1 Palanca A)
  ```
  Push diferido al final del vuelo con OK humano explicito (regla "Push por vuelo",
  `AGENTS.md`). **La sesion siguiente NO pushea sin autorizacion registrada.**

## Lo cerrado en este vuelo (WOT-2026-114a a 114h)

- 114a: baseline E7 + registro Hermes re-apuntable.
- 114b: retiro de Hermes (bundle de contexto para agente externo).
- 114c: Fase 2 Palanca A -- mueve `## Vocabulario canonico` fuera de `AGENTS.md`.
- 114d: split quirurgico de `## CEM v0` + convencion de claves de referencia (`docs/registry/reference_keys.md`, guard `scripts/check_reference_keys.py`).
- 114e: acorta citas `(ver F1)` -> `[F1]` + anclas navegables (`<a id="f1">`) en el fichero de referencia y la leyenda.
- 114f: corrige comentario stale del hook `check-reference-keys` + RONDA 3 del bucle adversarial (8/9 lentes convergen, 0 defectos reales; opencode/glm bloqueado 3ra vez consecutiva por su bug conocido de `external_directory`).
- 114g: re-medicion Fase 0 fresca (encuentra candidato `WOT-2026-026t`), puente de sesion (este
  documento), auditoria qwen3.6+gemma4 de la documentacion raiz (`docs/followups/root-docs-audit-qwen36-gemma4-20261022.md`).
- 114h: verificacion independiente del candidato + 3 hallazgos nuevos + bucle adversarial RONDA 4
  (9 lentes, 6 independientes) -- veredicto: proceder con T1+T2+T3+fixes 5-8, **rechazar mover T4
  integro** (mayoria 5/6). Texto completo de implementacion en la seccion "ACTUALIZACION
  2026-10-22" mas abajo.

Cada uno paso sus propios quality gates (ruff/tests focales/pre-commit completo). Ver
commits arriba para detalle; no se repite aqui.

## Estado de los gates de cuspide [snapshot 2026-10-22, comando: `uv run python scripts/measure_agents_md_units.py --json` a HEAD `d4f730fc`]

| Gate | Baseline Fase 0R (HEAD `279d2705`, 2026-10-21) | Ahora (HEAD `d4f730fc`) |
|---|---|---|
| AGENTS.md (Codex, bytes, limite 32768) | 61370 B = 1,87x | 42557 B = 1,30x |
| CLAUDE.md+@AGENTS.md (Claude, chars, limite 40000) | 63292 = 1,58x | 44486 = 1,11x |

**Ningun gate esta cerrado todavia.** Deficit restante: 9789 B (Codex) / 4486 chars (Claude).

## Decision abierta para la sesion siguiente [SUPERSEDIDA -- ver "ACTUALIZACION 2026-10-22" mas abajo]

> Esta seccion queda como historial de como se llego a la decision. La decision YA ESTA
> TOMADA (alcance reducido T1+T2+T3+fixes, sin T4) tras 114g/114h -- ve directo a la seccion
> "ACTUALIZACION 2026-10-22 (post-RONDA 4)" mas abajo para el texto de implementacion.

Ver `docs/followups/palanca-a-fase0-post-114f-remedicion-20261022.md` (medicion fresca de
este mismo dia, commiteado junto a este brief). Resumen del veredicto: **CANDIDATO
ENCONTRADO** -- la subseccion `### Orden de trabajo: AGRUPA los commits... (WOT-2026-026t)`
dentro de `## Convenciones` tiene ~6400 B movibles estimados (4 piezas: incidente del
trio Manager/Builder/Revisor, incidente del filtro `-k`, "Push por vuelo" ya duplicado en
`.agent/rules/common/flight_push_policy.md`, y "Extension: push" con el Gate 2 completo
sin duplicar todavia). Ese movimiento cerraria el gate Claude y dejaria el gate Codex en
~1,10x (de 1,30x), no cerrado del todo.

Ese mismo documento tambien declara una **correccion metodologica** al informe Fase 0R
anterior: su veredicto "SIN CANDIDATO MOVIBLE" se baso en que PASO 3(d) consideraba
`build_llms.py` (que lee `AGENTS.md` completo para `llms-full.txt`) como un veto universal
-- pero `llms-full.txt` es una proyeccion NO cargada en el arranque en frio del agente, asi
que ese veto no debia aplicar a los dos gates reales. La practica (CEM v0 se movio de
todas formas y el gate SI mejoro la cantidad medida) confirma la correccion.

**Lo que la sesion siguiente debia decidir, ya decidido en 114h tras bucle adversarial RONDA 4
(9 lentes, 6 independientes): proceder con T1+T2+T3+fixes 5-8, NO mover T4.** Ver texto
completo abajo.

## Deuda declarada (no se arregla en este vuelo)

- **Bug de infraestructura `external_directory` en opencode/glm:** reproducido 3 veces
  consecutivas en este mismo vuelo (RONDA 1, 2, 3 del bucle adversarial de CEM v0).
  Bloquea sistematicamente esa lente con `NO VERIFICABLE`, honesto pero inutil para
  cobertura. Candidato a ticket propio, prioridad baja-media (no bloquea nada, solo resta
  una lente de 9 en cada bucle).

## ACTUALIZACION 2026-10-22 (post-RONDA 4): decision tomada, texto completo listo para implementar

> Esta seccion SUPERSEDE la "Decision abierta" de arriba (que quedaba pendiente). Tras 114g
> (re-medicion + auditoria docs raiz) y 114h (verificacion independiente + bucle adversarial
> RONDA 4, 9 lentes, `EXPLORATORY-wot-026t-split-y-fixes-20261022`), la decision esta tomada:
> **alcance reducido (T1+T2+T3+fixes 5-8), SIN T4.** Ver veredicto completo en
> `docs/followups/palanca-a-fase0-post-114f-remedicion-20261022.md` seccion "Bucle adversarial
> RONDA 4". HEAD de referencia para este texto: `f093b8c4` (WOT-2026-114h).
>
> **Por que T4 queda fuera:** 5 de 6 lentes independientes rechazaron mover el Gate 2 completo
> (`#### Extension: push...`, lineas 226-269 de `AGENTS.md`) a un modulo de referencia -- es
> especificacion operativa VIVA que un agente necesita leer EN EL MOMENTO de decidir si aplica
> el Gate 2 relajado, no un caso forense de fondo como CEM v0. Ademas, incluso en el escenario
> OPTIMISTA de moverlo entero, el gate Codex se queda en rojo (~1,10x) -- este ticket no lo
> cierra de todas formas. **NO toques las lineas 226-269 de AGENTS.md en este ticket.**

### Paso 0 -- precondiciones (verificar antes de tocar nada)

1. `git status --porcelain` debe estar limpio antes de empezar.
2. Re-mide en fresco: `uv run python scripts/measure_agents_md_units.py --json` -- compara los
   gates contra `codex_bytes=42557/32768 (1,2987x)`, `claude_chars=44486/40000 (1,1121x)` de
   este brief. Si difieren, alguien movio algo entre medias -- investiga antes de seguir.
3. `grep -n "AGENTS.md:2[0-7][0-9]" -r . --include="*.py" --include="*.md"` (ya ejecutado en
   114h: el unico hit es `manifest_contracts.md:5`, el fix 5 de abajo). Repite por si acaso.
4. Confirma que las lineas de AGENTS.md citadas abajo siguen en el mismo sitio:
   `sed -n '161,224p' AGENTS.md` debe coincidir con el bloque "Texto actual" de cada pieza. Si
   no coincide, las lineas se movieron -- localiza el bloque por su encabezado, no por numero.

### Pieza T1 -- regla `-k` (WOT-2026-079d)

**Texto actual (AGENTS.md, dentro de `### Orden de trabajo...`, ~lineas 186-193):**
```
**No uses `-k` como evidencia de cobertura de una funcion compartida.** El filtro selecciona por
nombre de clase/fichero, no por grafo de call-sites: una funcion ejercitada desde clases con
nombres distintos al filtro puede quedar sin cubrir aunque `-k` de verde. La evidencia final de
cobertura de una funcion compartida debe venir de la suite canonica completa (`--level all`),
nunca de un `-k` por nombre. Rationale completo (por que la comprobacion previa no bastaba, caso
medido WOT-2026-079d con 3 regresiones reales que `-k` dejo pasar): memoria de
`repo_motor`, `obs-canonical-suite-k-filter-insufficient-for-shared-function-coverage`
(2026-09-27).
```

**Texto nuevo (reemplaza el bloque de arriba, conserva la clausula de MECANISMO inline --
exigencia del bucle, NO delegarla al modulo):**
```
**No uses `-k` como evidencia de cobertura de una funcion compartida: selecciona por nombre de
clase/fichero, no por grafo de call-sites, asi que una funcion ejercitada desde otra clase puede
quedar sin cubrir aunque `-k` de verde.** La evidencia final debe venir de la suite canonica
completa (`--level all`), nunca de un `-k` por nombre. Caso forense completo (incidente medido
WOT-2026-079d, 3 regresiones reales que `-k` dejo pasar, memoria
`obs-canonical-suite-k-filter-insufficient-for-shared-function-coverage`): [T1].
```

### Pieza T2 -- asignacion de rol en despacho trio (WOT-2026-104k/104j)

**Texto actual (~lineas 195-215):**
```
**Asignacion de rol en despacho trio (Manager/Builder/Revisor, WOT-2026-104k):** cuando el
despacho de un ticket se reparte entre tres roles (protocolo `prompts/kilo_trio_dispatch/`),
SOLO el Manager corre la suite completa `--level all`, como gate de cierre, UNA vez,
inmediatamente antes del push -- tras TODOS los commits del ticket, nunca "antes del commit
final" (la regla de arriba ya fija que la suite es el ULTIMO paso, no uno intermedio). El
Builder se limita a tests focales del area tocada durante la implementacion (nunca `--level all`
como su propio cierre); el Revisor ejecuta de forma independiente sus propios tests focales
sobre el area modificada -- NUNCA cita ni espera una corrida del Manager, porque en el orden
canonico del trio (Manager -> Builder -> Revisor -> Manager-cierre) esa corrida todavia no
existe cuando el Revisor actua. Medido en vivo (2026-10-18, WOT-2026-104j, sesion hija 4 capas):
sin esta asignacion explicita, Builder y el Orquestador corrieron `--level all` CADA UNO por su
cuenta, ambas veces antes de que el Revisor tuviera turno -- exactamente el patron de
desperdicio que la regla de arriba ya advertia, mas una corrida redundante que la regla de
arriba no cubria (quien tiene PERMISO de correrla, no solo cuando). Verificado por bucle de
gobierno DESIGN_REVIEW (`UNI-5`, 4 lentes independientes: codex, opencode/glm, gemini, mistral;
3/4 `APROBAR_CON_CAMBIOS` tras corregir una redaccion anacronica del primer borrador). **Alcance
declarado, no se extiende por si solo:** esta regla cubre el protocolo trio
`prompts/kilo_trio_dispatch/`. NO toca `scripts/run_gates_dispatch.py` ni
`skills/builder-run-quality-gates` (hallazgo de la lente codex en el mismo bucle): esos
mecanismos sirven tambien a tickets de un solo Builder sin Revisor/Manager separados, donde el
Builder SI es el unico verificador legitimo de `--level all`.
```

**Texto nuevo (conserva la clausula de ALCANCE NEGATIVO inline -- exigencia del bucle):**
```
**Asignacion de rol en despacho trio (Manager/Builder/Revisor, WOT-2026-104k):** en el protocolo
`prompts/kilo_trio_dispatch/`, SOLO el Manager corre la suite completa `--level all`, UNA vez,
tras TODOS los commits del ticket, nunca antes. El Builder se limita a tests focales; el Revisor
corre sus propios focales de forma independiente, sin esperar al Manager. **Alcance: cubre SOLO
el protocolo trio -- NO toca `scripts/run_gates_dispatch.py` ni `skills/builder-run-quality-gates`**,
donde el Builder SI es el unico verificador legitimo de `--level all` (tickets de un solo
Builder sin Revisor/Manager separados). Caso forense completo (incidente medido WOT-2026-104j,
bucle de gobierno `UNI-5`): [T2].
```

### Pieza T3 -- colapsa "Push por vuelo" (duplicado confirmado, SIN modulo nuevo)

**Texto actual (~lineas 217-224, bloque completo `#### Push por vuelo...`):**
```
#### Push por vuelo: UN solo push al final de TODOS los tickets (2026-10-19)

- DECISION DE PROCESO: la publicacion se difiere al final del vuelo, nunca por ticket (2026-10-19).
  BUSQUEDA-PREVIA: PROTOCOLO ENCONTRADO: `prompts/orchestrator_session_bootstrap.md:314` ("UN solo push al final de la cola, con OK humano explicito"), `prompts/orchestrator_pipeline_codeonly.md:199` ("Push AGRUPADO al final de sesion ... NO push por ticket") y `prompts/manager_orchestrator_loop_backlog.md:455` (informe antes del push). Esta seccion EXTIENDE esa regla a todo vuelo multi-ticket; no la inventa.

**La publicacion es una accion del VUELO, no del ticket.** Ver detalles, fallos medidos y contract en `.agent/rules/common/flight_push_policy.md`.
- **NO se pushea entre tickets** (mismo logico que `batch-agrupar-preguntas-antes-de-arrancar`).
- **Sin autorizacion registrada no hay push.** Un vuelo que termina sin decision de publicacion queda en estado declarado `PUBLICACION_PENDIENTE_AUTORIZACION`: todo commiteado y verde en local, remoto intacto.
```

**Texto nuevo (verificado caracter a caracter contra `.agent/rules/common/flight_push_policy.md`:
el parrafo DECISION DE PROCESO/BUSQUEDA-PREVIA, "NO se pushea entre tickets" y el bullet de
autorizacion YA estan completos alli -- esto es recorte de duplicado, no migracion):**
```
#### Push por vuelo: UN solo push al final de TODOS los tickets (2026-10-19)

**La publicacion es una accion del VUELO, no del ticket: NO se pushea entre tickets, solo al
final con autorizacion registrada.** Detalle completo (decision de proceso, busqueda previa,
motivo y estado `PUBLICACION_PENDIENTE_AUTORIZACION`): `.agent/rules/common/flight_push_policy.md`.
```

**Nota de verificacion para el `check_process_decision_search.py` hook:** el marcador `DECISION
DE PROCESO` desaparece de `AGENTS.md` con este cambio, pero sigue intacto y completo (con su
`BUSQUEDA-PREVIA`) en `.agent/rules/common/flight_push_policy.md`. El hook escanea
`prompts/**/*.md`, `.claude/rules/**/*.md`, `AGENTS.md`, `CLAUDE.md` -- `.agent/rules/common/`
NO esta en ese alcance, asi que no hay regresion de cobertura del hook por este movimiento.
Verifica de todas formas corriendo el hook tras el cambio (pre-commit lo hace solo).

### Modulo nuevo: `.agent/rules/common/wot_026t_orden_trabajo_forense.md`

Mismo patron que `cem_v0_evidencia_forense.md` (cabecera + anclas `<a id="t1"></a>`/`<a
id="t2"></a>` + marcadores `**T1.**`/`**T2.**`). Contenido COMPLETO VERBATIM de los dos bloques
"Texto actual" de arriba (T1 y T2), sin resumir. Crea el fichero con este contenido exacto:

```markdown
# WOT-2026-026t — Evidencia forense (casos completos)

> Modulo de referencia (`referencia-bajo-demanda`). Cada item es el caso forense COMPLETO y
> VERBATIM de la regla de `AGENTS.md` seccion "Orden de trabajo: AGRUPA los commits..." que lo
> cita con `[T<n>]`. La cuspide en `AGENTS.md` retiene solo la frase de refutacion corta con su
> clausula de mecanismo/alcance; este fichero conserva la narrativa completa del incidente.
> Citado desde `docs/registry/reference_keys.md` (letra `T`). Validado por
> `scripts/check_reference_keys.py`. Cada item lleva un ancla HTML (`<a id="t1"></a>`...)
> navegable por enlace (`#t1`) en GitHub/VS Code, ademas del ancla `**T1.**` que valida el guard.

<a id="t1"></a>
**T1.** [pegar aqui el bloque "Texto actual" COMPLETO de T1 de arriba, verbatim]

<a id="t2"></a>
**T2.** [pegar aqui el bloque "Texto actual" COMPLETO de T2 de arriba, verbatim]
```

**No crees `T3`/`T4` en este modulo** -- T3 se colapsa a puntero hacia `flight_push_policy.md`
(ya tiene el contenido), T4 no se mueve en este ticket (veredicto del bucle).

### Leyenda: anade la fila `T` a `docs/registry/reference_keys.md`

Anade esta fila a la tabla (mantener orden alfabetico, tras la fila `F`):
```
| T | [`.agent/rules/common/wot_026t_orden_trabajo_forense.md`](../../.agent/rules/common/wot_026t_orden_trabajo_forense.md) |
```

### Fix 5 -- `manifest_contracts.md:5` cita stale

**Texto actual (linea 4-5):**
```
> **Procedencia:** piramide pasada 2 + lote R1, HEAD base
> `8e956837`, 2026-10-19. Secciones origen (verbatim abajo):
> - `## MANIFEST.distribute y MANIFEST.workspace (WP-2026-111)` -- `AGENTS.md:214-230`
```

**Texto nuevo (rango de linea ACTUAL + encabezado -- doble anclaje, exigencia del bucle: "no
solo heading, tambien rango, para que siga siendo machine-checkable"):**
```
> **Procedencia:** piramide pasada 2 + lote R1, HEAD base
> `8e956837`, 2026-10-19. Secciones origen (verbatim abajo):
> - `## MANIFEST.distribute y MANIFEST.workspace (WP-2026-111)` -- `AGENTS.md:95-97`
>   (rango valido a `f093b8c4`; si vuelve a desplazarse, localiza por el encabezado exacto
>   de arriba, no asumas que el rango sigue vigente)
```
Verifica el rango actual tu mismo antes de aplicar (`grep -n "^## MANIFEST.distribute" AGENTS.md`
seguido de `sed -n` para confirmar donde termina la seccion) -- puede haber cambiado si algo
mas se movio entre el `f093b8c4` de este brief y tu HEAD actual.

### Fix 6 -- `CLOSURE_MODEL.md:46` afirmacion falsa

**Texto actual (linea 46):**
```
- Note: the standalone `scripts/session_closeout.py` utility referenced in earlier revisions was removed in `WP-2026-061` cleanup. Closeout is currently a manual canonical handoff (edit `work_plan.md` and `execution_log.md` to `COMPLETED`, regenerate `TURN.md` with `--reset-turn`, then validate). An integrated replacement is pending design.
```

**Texto nuevo (afirma la verdad, no solo borra la falsedad -- exigencia del bucle; declara
MOTOR explicitamente, no "el proyecto" generico -- otra exigencia del bucle sobre ambiguedad
motor-vs-destino):**
```
- Note: `scripts/session_closeout.py` exists in `repo_motor` and is the live delegate of `--session-close` (`agent_controller.py` handles the flag by calling it directly — see its docstring for the before/during/after contract). This note previously claimed it was removed in `WP-2026-061`; that was false as of `f093b8c4` (2026-10-22) — verify it still exists before trusting this note, since it describes `repo_motor` state, not `repo_destino`.
```
Verifica tu mismo antes de aplicar: `ls scripts/session_closeout.py` (debe existir) y
`grep -n "session_closeout" .agent/agent_controller.py` (debe mostrar la delegacion).

### Fix 7 -- `MANUAL_PUBLICATION_CHECKLIST.md` nota de documento historico

**Anade al inicio del fichero, ANTES del `# Checklist...` actual (no reescribas el resto --
fuera de alcance de este ticket; nombra el sucesor explicitamente -- exigencia del bucle, sin
esto el riesgo que se queria mitigar sigue vivo para quien llega por enlace):**
```
> **Documento historico de `WP-2026-058`.** Pre-fecha el flujo actual: hoy el agente SI
> ejecuta `git commit`/`git add`/`git status` directamente via herramienta (ver `AGENTS.md`
> seccion "Orden de trabajo: AGRUPA los commits..." para el flujo vigente, y
> `.agent/rules/common/flight_push_policy.md` para la politica de push). La premisa de la
> primera linea de abajo ("el agente no ejecuta comandos de git") ya NO es cierta. Se conserva
> como referencia historica, no como procedimiento vigente.

```
No cambies el resto del documento (la version `v9.6.0` de ejemplo en el paso 3 queda como
ilustracion historica, ya contextualizada por la nota de arriba -- reescribirla es scope creep
para este ticket).

### Fix 8 -- `.loop_bundle_optimizacion.md` (debris recurrente, WOT-2026-104n)

```
git rm .loop_bundle_optimizacion.md
```
Verificado (114h): trackeado desde `8756e927` cuyo mensaje no menciona bundles; mismo nombre de
fichero ya documentado como precedente en `prompts/orchestrator_launch_builder.md:303-310`
(WOT-2026-104n). Cero consumidores vivos (ya grepeado).

**Opcional, para que el fix sea DURABLE (el bucle senalo que sin esto el patron que lo creo --
un `git add -A` de un bucle -- puede reintroducirlo):** evalua anadir `.loop_bundle_*.md` a
`.gitignore`, O un check en `scripts/delivery_hygiene_check.py` que avise si aparece un fichero
asi en el staging. Esto es una mejora separada, no bloqueante para cerrar el ticket -- decidelo
tu si lo incluyes en el mismo commit o lo declaras como deuda con ticket propio.

### Paso final -- verificacion y cierre

1. `uv run python scripts/check_reference_keys.py` -- debe dar OK con la nueva clave `T`
   resuelta (2 citas `[T1]`/`[T2]`, 2 anclas en el modulo nuevo).
2. Re-mide: `uv run python scripts/measure_agents_md_units.py --json` -- compara contra el
   deficit declarado (9789 B Codex / 4486 chars Claude a HEAD `f093b8c4`). El ahorro esperado
   de T1+T2+T3 es menor que el ~6400 B optimista de la medicion original (esa cifra incluia T4,
   que aqui NO se mueve) -- **declara la cifra real medida, no reuses la estimacion de 6400 B**.
3. `ruff check . && ruff format .` sobre los ficheros `.py` tocados (si tocaste alguno --
   probablemente ninguno en este ticket, es todo markdown).
4. Pre-commit completo (se dispara solo al commitear) -- presta atencion a `check-reference-keys`,
   `check process decision search`, `check suite freshness`, `check cuspide growth gate`.
5. Suite canonica (`--level all`) como ULTIMO paso antes de cualquier push -- pero el push sigue
   diferido al final del vuelo, no lo hagas en este ticket salvo autorizacion humana explicita.
6. Commit unico con todos los cambios (modulo nuevo + reference_keys.md + AGENTS.md T1/T2/T3 +
   manifest_contracts.md + CLOSURE_MODEL.md + MANUAL_PUBLICATION_CHECKLIST.md +
   `git rm .loop_bundle_optimizacion.md`), mensaje `WOT-2026-114i` (o el siguiente sufijo libre
   -- verifica que no colisione), trailer `Co-Authored-By: Claude <noreply@anthropic.com>` (el
   hook `check-model-id-crystallization` rechaza trailers con version de modelo).
7. Declara explicitamente el resultado del gate Codex tras este ticket (NO lo presentes como
   cierre parcial silencioso si sigue en rojo -- exigencia del bucle, punto 5 de su
   recomendacion final). Si sigue en rojo, abre una segunda medicion Fase 0 sobre el resto de
   `AGENTS.md` para la siguiente candidata, o declara el diseno alternativo de T4
   (default-deny + checklist comprimida en `flight_push_policy.md`, propuesto por
   `kilo_deepseek_flash` en la RONDA 4) como siguiente ticket si se quiere perseguir el cierre
   completo.

## Que invocar primero en la sesion siguiente

1. Lee `prompts/orchestrator_session_bootstrap.md` para fijar rol y metodo (este brief NO
   lo sustituye, solo transporta continuidad -- por diseño de `session_hop.md`).
2. Lee este documento + `docs/followups/palanca-a-fase0-post-114f-remedicion-20261022.md`
   enteros para el ESTADO y la decision abierta de arriba.
3. Re-mide antes de actuar: no confies en las cifras de este brief mas alla de su fecha
   `[snapshot 2026-10-22]` -- vuelve a correr `measure_agents_md_units.py --json` y
   `git log --oneline origin/main..HEAD` al arrancar.

## Lo que NO hacer

- No pushear sin autorizacion humana explicita (10 commits locales, remoto intacto).
- No asumir que el veredicto "CANDIDATO ENCONTRADO" de la remedicion es una orden de
  implementar: es un informe de analisis, la decision de abrir el ticket es del usuario.
- No reintentar indefinidamente la lente opencode/glm por el mismo bug conocido -- es un
  resultado honesto (`NO VERIFICABLE`), no un fallo de despacho a corregir reintentando.
