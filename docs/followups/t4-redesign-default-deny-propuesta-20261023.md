# Propuesta: rediseno de T4 (Gate 2) como default-deny comprimido -- 2026-10-23

> Contexto: WOT-2026-114 (flight "optimizacion-arranque-frio") ya cerro T1+T2+T3+fixes 5-8
> (commits `902bc1a4`/`89b4b5c1`) tras RONDA 4 (9 lentes). Esa misma ronda RECHAZO mover T4
> (`#### Extension: push a una rama con trafico concurrente de otras sesiones`, Gate 2
> completo) entero a un modulo forense, por 5/6 votos: es especificacion operativa VIVA que
> un agente necesita leer en el momento de decidir si aplica el Gate 2 relajado, no un caso
> forense de fondo como T1/T2. El gate Codex de cuspide quedo declarado como ITEM DE DECISION
> pendiente, con dos caminos documentados (ver `docs/followups/session-hop-arranque-frio-20261022.md`):
> (1) segunda Fase 0 sobre el resto de AGENTS.md, (2) rediseno de T4 con "default-deny
> explicito en la linea siempre cargada + checklist comprimida", propuesto por
> `kilo_deepseek_flash` en esa misma RONDA 4. Esta propuesta desarrolla el camino (2).

## ESTADO_FRESCO

    raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\optimizacion-arranque-frio-cont-20261022
    HEAD=02aba94a803a, dirty=0, verificado=2026-10-23T05:59:49Z
    gates: codex=40834/32768 (1.2462x, deficit 8066B) | claude=42763/40000 (1.0691x, deficit 2763 chars)

## Por que esta propuesta NO repite el error de T4-rechazado

El rechazo de RONDA 4 fue a mover el Gate 2 **entero** a un modulo de referencia, dejando solo
un puntero en AGENTS.md -- eso rompe la regla "**NO esta dentro de una seccion que un
consumidor extraiga por ENCABEZADO**" en su variante operativa: un agente que decide SI aplica
el Gate 2 relajado necesita leer las 5 condiciones de rechazo EN EL MOMENTO, no ir a buscarlas.

Esta propuesta no mueve la regla, **la comprime sin perder la decision binaria inline**: el
texto que se queda en AGENTS.md sigue respondiendo "¿aplica el Gate 2 relajado, si o no?" sin
salir del fichero (mismo patron que T1/T2: la "clausula de mecanismo" se queda, el desarrollo
forense/operativo largo se mueve). La diferencia con T1/T2 es que aqui lo que se mueve no es
HISTORIA de un incidente, es el DESARROLLO COMPLETO de una checklist -- por eso el texto que
queda inline declara la condicion default (fail-closed) de forma autosuficiente: un agente que
NO sigue el puntero sigue tomando la decision CORRECTA (negar el relajo) en el peor caso, solo
pierde la oportunidad de relajarlo cuando SI estaria permitido. Esto es deliberado: el coste de
omision es asimetrico (fila 2 del PASO 2 de `doc_optimization.md`, "prohibicion dura") y el
default seguro absorbe el riesgo de que el agente no siga el puntero.

## Destino: NO un modulo forense nuevo, el ya existente `flight_push_policy.md`

`flight_push_policy.md` YA tiene el encabezado `#### Extension: push a una rama con trafico
concurrente de otras sesiones (2026-10-14)` con el parrafo del Gate 1 (lineas 27-31 actuales).
El Gate 2 es la continuacion NATURAL de esa misma seccion -- no se crea fichero nuevo, se
completa uno que ya existe y que el "Push por vuelo" de AGENTS.md ya referencia.

## PASO 3 -- las cinco condiciones (verificadas sobre el bloque A MOVER: los 5 parrafos
"Gate 2 (push con la rama...)" hasta "Riesgo residual declarado...", lineas 213-254 actuales)

- **(a) CONCENTRADO:** si -- bloque contiguo, funcion unica (desarrollo operativo del Gate 2).
- **(b) DESTINO ALCANZABLE:** si -- `flight_push_policy.md` es `referencia-bajo-demanda`,
  YA enlazado desde "Push por vuelo" un parrafo arriba en el mismo AGENTS.md.
- **(c) NO es refutacion:** confirmado -- es especificacion positiva (como verificar un merge),
  no un "esto que parece verdad no lo es". Una referencia cruzada interna sigue intacta: el
  bullet "la suite completa SI debe correr... (ver regla de arriba, WOT-2026-079d)" apunta a
  la regla `-k` que YA vive en el modulo `wot_026t_orden_trabajo_forense.md` via `[T1]`, no en
  AGENTS.md -- **hallazgo de esta pasada:** "ver regla de arriba" deja de resolver si el bloque
  se muda a OTRO fichero; se reescribe como "ver [T1] en AGENTS.md / WOT-2026-079d" para que
  siga siendo correcto independientemente de donde viva el bloque.
- **(d) NINGUN CONSUMIDOR PROGRAMATICO:** verificado por grep de las frases literales mas
  especificas del bloque (`Condiciones de rechazo del Gate 2`, `Riesgo residual declarado`,
  `Gate 2 (push con la rama`, `blast radius` combinado con el contexto de superficie
  transversal) contra `tests/`, `scripts/`, `prompts/`: **0 hits reales** (los hits de "blast
  radius" son de otros contratos, sin relacion). El unico consumidor del ENCABEZADO (no del
  cuerpo) es `flight_push_policy.md:27` -- que es precisamente el destino, no un consumidor
  externo que se rompa.
- **(e) NO registrado por extraccion de encabezado:** `measure_agents_md_units.py` tiene
  patrones de encabezado especiales SOLO para "Vocabulario canonico" y "Secretos y seguridad"
  (`scripts/measure_agents_md_units.py:48,61`) -- "Extension: push..." no es uno de ellos.

**Las cinco condiciones pasan para el CUERPO del bloque (no para la regla default-deny, que se
queda).**

## Texto actual (AGENTS.md lineas 211-254, verbatim, NO reproducido aqui para no duplicar --
ver el fichero real a ese rango en HEAD `02aba94a`)

## Texto nuevo en AGENTS.md (reemplaza las lineas 211-254 completas)

```markdown
#### Extension: push a una rama con trafico concurrente de otras sesiones (2026-10-14)

**Default fail-closed: si la rama remota avanzo con commits de otras sesiones, el Gate 2
relajado NO aplica salvo que las 5 condiciones de rechazo (evidencia verificable del Gate 1
ajeno, sin superficie transversal compartida, sin import cruzado entre los lados, commit NO
merge, y menos de 2 rechazos previos sin re-suite) esten TODAS descartadas.** Checklist
completa de las 5 condiciones, criterio de merge disjunto vs mismo-fichero y riesgo residual
declarado (sin verificador CI tercero equivalente): `.agent/rules/common/flight_push_policy.md`.
```

Medido: 639 B / 639 chars (vs 3474 B del bloque actual). Ahorro neto estimado: **2835 B**.

## Texto nuevo en `flight_push_policy.md` (anade DESPUES del parrafo "Gate 1 (nunca se relaja)",
dentro de la MISMA seccion "Extension: push...", contenido VERBATIM del bloque actual de
AGENTS.md salvo el fix de la referencia "ver regla de arriba" -> "ver [T1]")

```markdown
**Gate 2 (push con la rama remota avanzada por otras sesiones):** si, al intentar publicar un
commit YA VERIFICADO por el Gate 1, la rama remota avanzo con commits de otras sesiones, el
merge de esos commits se verifica asi:
- Si el merge es disjunto en ficheros (ninguno tocado por ambos lados) **y** el auto-merge de
  Git no reporta conflicto de texto: ademas de `ast.parse`/sintaxis de los ficheros que SI
  cambiaron y confirmar que no quedan marcadores de conflicto (`<<<<<<<`), se exige ADEMAS
  (i) ausencia de dependencia de import cruzada entre los ficheros tocados por cada lado, y
  (ii) que ninguno de los ficheros tocados sea una superficie transversal de alto blast radius
  (`conftest.py`, `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `AGENTS.md`,
  `CLAUDE.md`, `bus/`, `runtime/`, `.agent/agents_config.py`). Si cualquiera de las tres
  condiciones falla, tratar como "mismo fichero compartido" (exige suite completa).
- Si el merge toca el mismo fichero en ambos lados: la suite completa SI debe correr antes de
  publicar -- nunca "suite focalizada" por `-k` (ver [T1] en AGENTS.md / WOT-2026-079d).
- El camino relajado del primer bullet NUNCA es alcanzable para el commit resultante de un
  MERGE: el `tested_commit_sha` del Gate 1 es el del commit padre, nunca el del merge commit.
  La "relajacion" ahorra la RE-suite solo cuando se demuestra ANTES de mergear que el merge es
  disjunto y seguro, nunca despues de que el merge commit ya existe.
- Si tras publicar el remoto volvio a avanzar (`non-fast-forward`), repetir el criterio arriba
  en la nueva ronda, sin acumular re-verificaciones completas solo porque ya se hizo una vez.

**Condiciones de rechazo del Gate 2 (default fail-closed):** el Gate 2 relajado NO aplica si
(1) no existe evidencia VERIFICABLE de que el lado entrante corrio su Gate 1 (`tested_commit_sha`
registrado, evento de bus, log de cierre citable -- no basta "presumiblemente"); (2) el lado
entrante toca una superficie transversal (lista arriba); (3) hay dependencia de import cruzada
entre los ficheros tocados por ambos lados; (4) el commit publicado es un merge commit cuyo
`tested_commit_sha` no coincide con el HEAD resultante; (5) han ocurrido 2+ intentos de push
rechazados consecutivos sin que ninguna ronda haya corrido la suite completa sobre el estado
integrado. El default es FAIL-CLOSED: el Gate 2 relajado es la excepcion estrecha, no el
comportamiento esperado por defecto.

**Alcance:** esta politica SOLO aplica a ramas o flujos donde exista, en algun punto del ciclo
de vida del commit, una verificacion equivalente a `assert_canonical_suite_green` (via
`--mark-ready` de un ticket formal, o via un registro explicito de `tested_commit_sha` en la
bitacora de un vuelo sin ticket). Sin esa evidencia, tratar como si el Gate 1 nunca se hubiera
verificado y exigir suite completa, sin excepcion.

**Riesgo residual declarado:** esta politica asume que cada sesion concurrente aplica su propio
Gate 1 antes de publicar. A diferencia de un equipo con CI real (que tiene un verificador
automatico TERCERO sobre el HEAD integrado), aqui no existe ningun verificador automatico
equivalente -- el riesgo es MAYOR que en un equipo con CI, no igual. `check_suite_freshness.py`
no es comparable: es local y depende de que `pre_handoff_guard` corra aguas abajo, lo cual no
ocurre en un push de vuelo sin ticket formal.
```

## Errores y puntos de mejora encontrados en esta pasada (CEM: busca errores antes de aplicar)

1. **La referencia interna "ver regla de arriba, WOT-2026-079d" se rompe al mover de fichero**
   (identificado arriba, condicion (c)): corregido a "ver [T1] en AGENTS.md / WOT-2026-079d" en
   el texto nuevo. Sin este fix, un lector de `flight_push_policy.md` no encontraria "la regla
   de arriba" (que ahora vive en OTRO fichero, `wot_026t_orden_trabajo_forense.md`).
2. **La cifra "2835 B de ahorro" NO cierra el gate Codex por si sola** (deficit actual 8066 B):
   tras aplicar, declarar explicitamente el deficit remanente (~5231 B estimado, re-medir para
   confirmar) como deuda SLO, NO como cierre silencioso. Mismo patron que exigio el bucle RONDA
   4 para T1-T3 ("declara el resultado del gate tras el ticket, no lo presentes como cierre
   parcial silencioso").
3. **No crear ticket WOT nuevo sin verificar colision de sufijo**: el siguiente libre tras
   WOT-2026-119a (ultimo visto en `git log`) es candidato, pero debe verificarse en el momento
   de commitear, no asumirse aqui.
4. **Riesgo de que el bucle adversarial repita el mismo rechazo que T4-integro**: la propuesta
   debe presentarse a las lentes dejando MUY claro que esto NO es "mover el Gate 2 entero" (lo
   que ya se rechazo 5/6), sino comprimir manteniendo la decision binaria inline -- declarar
   esta distincion explicitamente en el prompt del bucle para no gastar una ronda completa
   re-explicando el rechazo anterior.
5. **Verificar que ningun test nuevo (anadido en los pendientes heredados de esta misma sesion,
   `test_check_guard_wiring.py`/`test_flight_push_policy.py`) dependa de la posicion exacta de
   lineas 211-254 de AGENTS.md** -- grep confirmado: ningun test cita esas lineas por numero ni
   por el contenido del Gate 2 (solo citan "Push por vuelo" y los markers DECISION DE
   PROCESO/BUSQUEDA-PREVIA, que NO estan en el bloque a mover).

## Verificacion pendiente tras aplicar (PASO 4 del protocolo)

1. Re-medir `uv run python -m scripts.measure_agents_md_units` -- comparar contra el deficit
   declarado arriba (8066 B / 2763 chars) y declarar la cifra REAL (no reusar el estimado de
   2835 B).
2. `uv run python scripts/check_reference_keys.py` (no deberia afectar, el bloque no usa
   `[X#]` nuevos, solo corrige una referencia textual "ver regla de arriba" -> "[T1]").
3. `pytest tests/unit/test_flight_push_policy.py tests/unit/test_check_guard_wiring.py -v`
   (los dos tests tocados por los pendientes heredados de esta sesion).
4. `check_process_decision_search.py` (pre-commit) -- el bloque movido no tiene marcador
   `DECISION DE PROCESO`, no deberia disparar nada nuevo.
5. `check_distribution_boundary.py` / `check_cuspide_growth_and_drift.py` si aplican al tocar
   `.agent/rules/common/flight_push_policy.md`.
6. Suite canonica `--level all` -- SOLO una vez, al final de TODOS los commits de la sesion,
   nunca intermedia (regla propia de AGENTS.md).

## Bucle adversarial (RONDA 1, 2026-10-23, 5 lentes paralelas via T3 delegate_task)

Veredicto: 3 CHANGES (codex/gpt-5.6-luna, nan/deepseek-v4-flash, nan/qwen3.8-flash) vs 2 APPROVE
(mistral-large, nan/gemma4). Hallazgos BLOQUEANTES verificados independientemente:

1. **Inversion logica en la condicion (2) comprimida** (qwen3.8-flash): "sin superficie
   transversal compartida" se lee como "solo si AMBOS lados la tocan"; la regla real exige que
   NINGUN lado la toque. Fix: "ningun lado toca una superficie transversal".
2. **Falta la precondicion del Gate 1 PROPIO** (qwen3.8-flash): el resumen original solo hablaba
   del Gate 1 del lado ENTRANTE, nunca del propio -- un agente podria relajar sin que su propio
   commit hubiera pasado el Gate 1. Fix: anadir la condicion (1) "TU propio commit ya paso el
   Gate 1 con evidencia registrada".
3. **`flight_push_policy.md` NO estaba en `MANIFEST.distribute`** (codex Y deepseek,
   independientemente -- CONFIRMADO con `grep` directo: lineas 99-112 de MANIFEST.distribute no
   lo incluian). Riesgo real en topologia destino: el puntero no resolveria.
4. **Consumidor normativo omitido** (deepseek): `prompts/orchestrator_autonomous_ticket_batch.md:832`
   ("the Gate 2 criteria of AGENTS.md apply") -- CONFIRMADO con grep directo.
5. **`llms-full.txt` desincroniza** (qwen3.8-flash): `scripts/build_llms.py` embebe `AGENTS.md`
   verbatim; tocar AGENTS.md exige regenerar el corpus en el mismo commit.

Los 3 lentes CHANGES coinciden en que el DISENO es correcto (no es el T4-rechazado disfrazado:
implementa el camino 2 ya registrado en RONDA 4 de la sesion anterior), pero el TEXTO
comprimido original tenia bugs reales. qwen3.8-flash autoriza aplicar la correccion "sin
re-bucle completo de 9 lentes" si se verifican las dos frases corregidas contra los escenarios
que senala -- eso es lo que se aplico abajo.

## APLICADO (2026-10-23)

Los 5 fixes de la RONDA 1 se aplicaron:
- AGENTS.md: regla default-deny reescrita con las 5 condiciones correctas (782 B, vs 639 B del
  borrador con bug -- el fix cuesta 143 B mas, ahorro neto real 2691 B en vez de 2835 B).
- `flight_push_policy.md`: Gate 2 completo anadido verbatim tras Gate 1, con la referencia
  corregida ("regla `-k` en AGENTS.md / [T1], WOT-2026-079d" en vez de "ver regla de arriba").
- `MANIFEST.distribute`: anadida la entrada `.agent/rules/common/flight_push_policy.md`.
- `prompts/orchestrator_autonomous_ticket_batch.md`: cita actualizada para reflejar que el
  default-deny vive en AGENTS.md y el checklist completo en flight_push_policy.md.
- `llms-full.txt`: regenerado (`uv run python scripts/build_llms.py`).

**Verificacion (todo verde):**
- `check_reference_keys.py`: OK, todas las claves resuelven.
- `check_distribution_boundary.py`: OK, 174 ficheros versionados auditados (incluye el nuevo).
- `tests/unit/test_flight_push_policy.py` + `test_check_guard_wiring.py`: 29/29 passed.
- `tests/ -k "build_llms or manifest"`: 61/61 passed.
- Sin ficheros `.py` tocados -> `ruff` no aplica a este cambio.

**Gates re-medidos (HEAD `02aba94a803a`, dirty=True tras este cambio):**

| Gate | Antes de este fix | Despues |
|---|---|---|
| Codex (bytes, limite 32768) | 40834 (1,2462x, deficit 8066) | **38143 (1,164x, deficit 5375)** |
| Claude Code (chars, limite 40000, SLO interno) | 42763 (1,0691x, deficit 2763) | **40072 (1,0018x, deficit 72)** |

El gate Claude queda a 72 caracteres de cerrar (practicamente cerrado). El gate Codex mejora de
1,2462x a 1,164x pero SIGUE en rojo -- deficit 5375 B declarado como **deuda SLO explicita**
(mismo patron que WOT-2026-115a), no como cierre silencioso. Pendiente de decision del usuario:
perseguir una Fase 0 nueva sobre el resto de AGENTS.md, o detener aqui.

## Candidata adicional aplicada: #16 "No MEZCLES vias de escritura" (2026-10-23, mismo flight)

Tras cerrar T4-redesign, se identifico una segunda candidata en la misma tabla de medicion:
`#### No MEZCLES vias de escritura en el mismo fichero` (2239 B). El informe previo
(`palanca-a-fase0-medicion-informe.md`) la marcaba FAIL (d) por 2 consumidores
(`prompts/orchestrator_session_bootstrap.md:392`, `skills/test-audit/references/edit-shape.md:45`)
-- pero verificado: ambos citan SOLO el titulo/cita corta, nunca el cuerpo, y el patron
T1-T4 (encabezado se queda, solo se mueve la narrativa forense) los deja intactos. Aplicado:
- Nuevo modulo `.agent/rules/common/wot_010e_line_endings_forense.md` (letra de registro `E`,
  anadida a `docs/registry/reference_keys.md`).
- AGENTS.md: seccion comprimida a regla operativa + puntero `[E1]` (830 B, vs 2239 B --
  ahorro neto 1409 B).
- `MANIFEST.distribute`: anadida la entrada del modulo nuevo.
- `llms-full.txt` regenerado de nuevo.
- Verificado: `check_reference_keys.py` OK, `check_distribution_boundary.py` OK (tras
  `git add` del fichero nuevo -- el primer intento fallo por fichero untracked), 140 tests
  relacionados (`test_flight_push_policy`, `test_check_guard_wiring`, `build_llms`/`manifest`/
  `reference_keys`, `test_encoding_mixed_line_endings`, `test_encoding_guard_deaccent`,
  `test_check_dec_receipt`, `test_prepush_loop_execution_blocking`) pasan.

No se lanzo bucle adversarial de 5 lentes para esta candidata (rigor proporcional: patron ya
validado 2 veces por el bucle anterior, cambio mas simple que T4, auto-revision aplico el mismo
criterio de verificacion de consumidores con grep sin filtro de extension).

## Gates finales (HEAD `02aba94a803a`, dirty=True, re-medido con ambas candidatas aplicadas)

| Gate | Original (antes de este flight) | Tras T4-redesign | Tras #16 |
|---|---|---|---|
| Codex (32768 B) | 40834 (1,2462x, deficit 8066) | 38143 (1,164x, deficit 5375) | **36737 (1,1211x, deficit 3969)** |
| Claude (40000 chars, SLO) | 42763 (1,0691x, deficit 2763) | 40072 (1,0018x, deficit 72) | **38666 (0,9667x, deficit 0 -- CERRADO)** |

**El gate Claude Code queda CERRADO.** El gate Codex mejora de 1,2462x a 1,1211x pero sigue en
rojo (deficit 3969 B) -- declarado como deuda SLO explicita, pendiente de una tercera candidata
o de cerrar aqui el flight con la deuda declarada.

## Alineacion con el esquema de capsula de 5 campos (informe de investigacion 2026-10-22)

El usuario recordo que existe un informe de investigacion previo ("Contexto siempre cargado
para agentes LLM bajo presupuestos duros: practicas reales y diseno recomendado", adjuntado en
el thread `mcp:71ce2e1c-ab9f-4438-b299-2a201bd79e9b`, "Agents,md optimizacion",
worktree `vuelo-autonomo-058l-20261022`) que YA definio la estructura de dos ejes para este
mismo problema, y cuyo "consenso R3" (ratchet merge-base WOT-2026-116a, guard de rol
WOT-2026-117a, eje D de reference_keys.md WOT-2026-118a, override YAML WOT-2026-119a) **ya esta
implementado en este HEAD**. El informe prescribe textualmente para T4: "producir una
<<decision capsule>> minima que conserve trigger, accion prohibida, alternativa, precedencia y
una frase causal" con 5 campos (REGLA/CUANDO/POR QUE/SALIDA/REF). Mi rediseno de T4 de hoy
convergio de forma independiente al mismo patron, pero le faltaba el campo POR QUE explicito
(el informe lo marca como obligatorio para reglas default-deny). Corregido: anadida la frase
causal ("sin las 5, el HEAD integrado publicado queda sin verificacion real... rompiendo
`tested_commit_sha == HEAD`"), coste +142 B, gate Codex deficit sube de 3969 a 4111 B
(aceptado: alinear con el esquema ya adoptado pesa mas que 142 B marginales).

**Nota importante sobre el modelo de dos ejes (NO aplicada todavia, fuera de alcance de hoy):**
el eje D implementado en `skill_trigger_governance.md` hoy SOLO cubre colision de triggers de
skills (alcance declarado de WOT-2026-118a). El informe original imaginaba el eje D como un
esquema general para CUALQUIER capsula de decision transversal (trigger/governs/priority/why/
target) -- generalizarlo mas alla de triggers de skills (p.ej. para que T4 mismo tuviera una
entrada D con ese esquema formal) NO se ha hecho y no es parte de esta sesion.

## Estado de esta propuesta

**APLICADO** (T4-redesign con el fix de la RONDA 1 + campo POR QUE + candidata #16). Pendiente
de autorizacion humana para commitear (push sigue diferido al final del vuelo, regla "Push por
vuelo"). Coordinacion cross-account verificada en vivo con la sesion `t3-0ca66df5` (auditoria
de vocabulario orquestador/manager/builder/revisor): cero solapamiento de ficheros confirmado
salvo un ajuste de una frase en `prompts/orchestrator_autonomous_ticket_batch.md` (su lote 2b
en curso, su Builder-nan aun no llego a esa linea; ella revisara el diff a mano antes de
commitear para no pisar este cambio).
