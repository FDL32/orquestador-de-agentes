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

- `wc -c AGENTS.md` = **77228 bytes**. Gate Codex = 32768 B (`PROJECT_DOC_MAX_BYTES`, fuente:
  issues de comunidad #13386/#7138/#6038, no verificado contra el codigo fuente de Codex).
  Ratio: **77228 / 32768 = 2,36x**.
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
