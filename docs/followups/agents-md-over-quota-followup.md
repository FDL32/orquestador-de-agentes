# Follow-up: AGENTS.md supera los dos gates de siempre-cargado (PASO 1)

> Draft de seguimiento (no es un ticket activo). Origen: bucle DESIGN_REVIEW
> `EXPLORATORY-doc-optimization-gates` (2026-10-18), hallazgo H3 de la lente
> deepseek y confirmado de forma independiente por Codex -- ambas lentes
> rechazaron declarar esta deuda como prosa sin owner dentro de
> `prompts/doc_optimization.md` y señalaron este formato (`docs/followups/`,
> ya usado en `anti-mangling-guard-followup.md`) como el artefacto correcto
> para una deuda sin ticket en `repo_motor` code-only.
> Materializado en ruta versionable del motor para que el Manager pueda
> convertirlo en `work_plan` cuando proceda. NO bootstrapped en el bus.
> **Requiere decision del usuario para abrir WP** (clausula literal exigida por PASO 5.2 de
> `prompts/doc_optimization.md` para esta via).

## Metadata propuesta
- **ID sugerido:** siguiente `WOT-2026-NNN` libre (el motor usa prefijo `WOT-`).
- **deliverable_type:** mixed (codigo si se reestructura `AGENTS.md`; documentacion si solo se
  mueven secciones a referencia).
- **delivery_authority:** repo_motor
- **Prioridad:** Media (WARN no-bloqueante, ningun backend trunca con perdida de datos salvo
  Codex, y ese truncado ya es conocido y documentado).

## Objetivo
`AGENTS.md` de este motor debe caber DENTRO de los dos gates absolutos declarados en
`prompts/doc_optimization.md` PASO 1: el gate Codex (bytes) y el gate Claude Code (caracteres
del cierre `CLAUDE.md` + `@imports`). Se considera cumplido cuando ambos ratios son <= 1,0x.

## Premisa verificada (read-only)

    ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\FDL32-t3-dev-hub, HEAD=bf74cd33, dirty=7, verificado=2026-10-18T10:59:29Z

(TRAMPA-1 de `doc_optimization.md` advierte que la misma medicion difiere en otro
checkout/worktree -- revalidar si se retoma desde otra raiz.)

- `wc -c AGENTS.md` = **77228 bytes** en esa medicion (2026-10-18); re-medido
  2026-10-19 en `FDL32-t3-dev-hub` tras el Lote 0+R1 (`96243c48`): **74321
  bytes**. Gate Codex = 32768 B (`PROJECT_DOC_MAX_BYTES`). **Evidencia
  actualizada 2026-10-19 (sesion `propuesta_continuidad_agentes_frios_
  20261019.md`): verificado contra el CODIGO FUENTE real de `openai/codex`
  via `gh api` (ya no "issues de comunidad, no verificado"):
  `codex-rs/config/src/config_toml.rs` declara
  `DEFAULT_PROJECT_DOC_MAX_BYTES: usize = 32 * 1024`; `codex-rs/core/src/
  agents_md.rs` confirma presupuesto COMPARTIDO (un unico contador
  `remaining` decrementado a traves de TODOS los `AGENTS.md` root-to-leaf Y
  de multiples entornos) con truncado SILENCIOSO (`data.truncate()` + solo
  `tracing::warn!`, nunca a UI/TUI); `codex-rs/codex-home/src/instructions/
  mod.rs` confirma que `~/.codex/AGENTS.md` usa un camino de codigo
  DISTINTO sin ese cap, exento.** Ratio con la cifra actual: **74321 / 32768
  = 2,27x** (bajo de 2,36x tras el Lote 0+R1, sigue sin cumplir el gate).
- Cierre Claude Code = `CLAUDE.md` (1983 chars) + `@AGENTS.md` (77092 chars, unico `@import`
  real de `CLAUDE.md:3`, confirmado con `grep '^@' CLAUDE.md AGENTS.md` -> un solo hit) =
  **79075 chars**. Gate Claude Code = 40000 chars (WARN no-bloqueante). Ratio:
  **79075 / 40000 = 1,98x**.
- `git ls-files | grep 'AGENTS.md$'` confirma un unico `AGENTS.md` tracked en el repo; no hay
  ambiguedad de raiz dentro de este checkout.

## Files Likely Touched (repo_motor)
- `AGENTS.md`
- Ficheros de destino en `docs/protocol/` para las secciones que se extraigan (via
  `prompts/doc_optimization.md` PASO 2-4, una seccion por corrida).

## Contrato del fix (minimo)
- Aplicar el protocolo de `prompts/doc_optimization.md` (PASO 0-4) sobre `AGENTS.md`,
  UNA seccion movible por corrida, hasta que ambos ratios bajen a <= 1,0x o se agoten los
  candidatos movibles (`SIN CANDIDATO MOVIBLE` es un estado terminal legitimo, no un fallo).
- Preferir el flujo orquestado de `prompts/agents_md_optimization_4layer_loop.md` si el modo
  de ejecucion activo es "4 capas"; aplicar directo si es "Tradicional".
- Cada traslado debe respetar las CINCO condiciones del PASO 3 (concentrado, destino
  alcanzable, no es refutacion, ningun consumidor programatico lo consume, no esta bajo un
  encabezado que un consumidor extraiga) y el guard de no-degradacion (before/after de la
  salida de cada consumidor censado).

## Barrera de regresion (obligatoria, fail-sin-fix)
- Antes del fix: `wc -c AGENTS.md` > 32768 y el cierre Claude Code > 40000 chars (ambos
  confirmados arriba).
- Despues del fix: ambas mediciones deben re-ejecutarse con la misma receta y quedar <= su
  gate. Si solo uno de los dos baja, la deuda sigue abierta para el gate restante (PASO 5.2:
  "una deuda que solo cubre uno de los gates deja al otro en silencio").

## Non-goals
- No reescribir `AGENTS.md` de una sola vez ni en un solo commit (es una familia de cambios,
  no un bloque -- PASO 5 lo descarta explicitamente para este caso por blast radius).
- No implementar un guard WARN automatico de tamano como parte de este follow-up: es una
  decision de producto distinta (si el motor quiere un guard cableado en
  `.pre-commit-config.yaml` analogo a `ROUTER_MAX_LINES_WARN` de `scripts/discover_skills.py`),
  que requiere decision explicita del usuario, no de quien cierra este follow-up.
- No tocar la gobernanza X-09 (skill apunta, prompt gobierna) como parte de este trabajo.

## Criterio binario de cierre
- [ ] `wc -c AGENTS.md` <= 32768.
- [ ] cierre `CLAUDE.md` + `@imports` <= 40000 chars (misma receta que arriba, resolviendo
  `@imports` reales, no solo `AGENTS.md` hardcodeado).
- [ ] cada traslado aplicado paso PASO 3 (cinco condiciones) y el guard de no-degradacion de
  PASO 4.
- [ ] `ruff` + suite canonica del motor verdes.

## Trazabilidad
- Bucle DESIGN_REVIEW `EXPLORATORY-doc-optimization-gates` (2026-10-18):
  `.agent/planning/research_context_budget/review_deepseek.md` (hallazgo H3, ALTA),
  `.agent/planning/research_context_budget/review_glmpay.md` (hallazgo 3, ALTA, confirma),
  `.agent/planning/research_context_budget/review_h3_codex.md` y
  `.agent/planning/research_context_budget/review_h3_deepseek.md` (ronda de validacion de
  este propio artefacto como forma correcta de declarar la deuda).
- **Pasada 3 (2026-10-18), hallazgo nuevo que no cierra esta deuda pero la reencuadra:**
  `.agent/planning/agents_md_optimization/pasada_3_manager.md` -- censo real (Manager
  `nan/qwen3.8-flash`) de contenido legitimamente movible via `doc_optimization.md`: suma
  confirmada 5512 B, escenario optimista no verificado 17277 B, frente a un deficit de
  46457 B para el gate Codex. **La extraccion incremental por si sola no puede cerrar esta
  deuda** (cubre a lo sumo el 37.2% del deficit, incluso en el escenario mas favorable).
  Via de salida propuesta (requiere decision humana, no mecanica):
  `.agent/planning/agents_md_optimization/propuesta_restructuracion_arquitectonica.md`
  (tres palancas: AGENTS.md anidados por directorio, desacoplar el `@import` de Claude Code,
  o condensar la narrativa forense adyacente a reglas que se quedan). El usuario eligio
explorar esta via arquitectonica en vez de aceptar la deuda tal cual o seguir con pasadas
   marginales (2026-10-18).

## Medicion post-P6 (recibo por gate, 2026-10-20)

P6 mueve la seccion `## Memoria por proyecto` (`AGENTS.md:801-856`) a
`.agent/rules/common/memory_hierarchy.md`. Secciones de gates re-medidas tras el traslado:

    AGENTS.md bytes: 76930 (Codex gate 32768 B) -> ratio 2,35x
    CLAUDE.md chars: 1983 + AGENTS.md chars: 76840 = 78823 (Claude gate 40000 chars) -> ratio 1,97x

Evolucion de ratios:
- Codex: 2,48x (antes P6) -> 2,35x (post P6). Reduccion: 4372 B (81302 -> 76930).
- Claude: 2,08x (antes P6) -> 1,97x (post P6). Reduccion: 4366 chars (83189 -> 78823).

Persiste exceso en AMBOS gates (ninguno <= 1,0x). P6 es rebanada legitima de la campana, no
cierre de la deuda. La deuda continua abierta y esta via nombrada de seguimiento aplica
segun PASO 5 de `prompts/doc_optimization.md`: **requiere decision del usuario para abrir WP**.

## Medicion post-pasada-2 (recibo por gate, 2026-10-21)

Pasada 2 mueve 7 secciones a modulos en `.agent/rules/common/`:
- S1+S2: `contract_full_read_and_process_search.md` (8502 B)
- S3: `flight_push_policy.md` (2317 B)
- S4: `do_now_vs_defer.md` (4049 B)
- S5: `x09_skill_prompt_governance.md` (3053 B)
- S6: `collaboration_live_surfaces.md` (1190 B)
- S7: `credits_external_attributions.md` (984 B)

Medicion del HEAD post-reparacion y restauracion de literales E2/E4 (`1f0dbcab`; la medicion previa de `d640dca5` daba 60586/62421, inflada por el doble-encoding y los blancos duplicados corregidos despues):

    AGENTS.md bytes: 61047 (Codex gate 32768 B) -> ratio 1,86x
    cierre CLAUDE.md (CLAUDE.md + @AGENTS.md) chars: 62970 (Claude gate 40000 chars) -> ratio 1,57x

Evolucion de ratios:
- Codex: 2,35x (post P6) -> 1,86x (post pasada 2). Reduccion: ~16325 B desde la base `d965ee45` (77372 -> 61047).
- Claude: 1,97x (post P6) -> 1,57x (post pasada 2). Reduccion: ~16318 chars desde la base `d965ee45` (79288 -> 62970).

Persiste exceso en AMBOS gates (ninguno <= 1,0x). La piramide sola, incluso consumiendo el
techo fresco (~30 KB), no cierra ambos gates: 61047 B = 1,86x del gate Codex. Confirma
hallazgo #2 del bucle Seccion 8: cerrar el gate exige Palanca A (AGENTS.md anidados).

La deuda sigue ABIERTA. Esta via nombrada de seguimiento aplica segun PASO 5 de
`prompts/doc_optimization.md`: **requiere decision del usuario para abrir WP**.

## Diseno de la Palanca A (solo raiz), 2026-10-21

El WP de DISENO esta en `docs/followups/palanca-a-raiz-agents-md-diseno.md` (revisado por
2 rondas de lentes independientes). Conclusion con numeros: el TOPE de directivas que podrian
quedarse en la raiz si se movieran enteros los grupos Vocabulario + CEM v0 + ola 2 es 4228 B para
llegar al gate (951 B con 10% de margen); que la piramide sola llegue depende de la retencion
real, que la Fase 0 del diseno mide. Esta deuda sigue ABIERTA: ratios 1,86x y 1,57x.
