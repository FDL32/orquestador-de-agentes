# Impact analysis: mattpocock/skills v1.0.0 vs local skills/prompts — WOT-2026-010r

> **Tipo:** analysis (decision + evidencia). NO adopta ni porta codigo.
> **delivery_authority:** repo_motor. **Fecha:** 2026-06-18.
> **Base local:** inventario de `WOT-2026-010g`
> (`.agent/docs/prompts_skills_inventory_WOT-2026-010g.md`, 178 lineas).

Cada claim lleva etiqueta `[VERIFICADO ...]` o `[INFERENCIA]`. El relato del
release no es evidencia: se contrasta con `gh` y con el codigo local.

---

## 1. Fuente externa y licencia

| Campo | Valor | Evidencia |
|---|---|---|
| Repo | `mattpocock/skills` | [VERIFICADO GH] `gh api repos/mattpocock/skills` |
| Licencia | **MIT** | [VERIFICADO GH] `gh api .../license --jq .license.spdx_id` -> `MIT` |
| Tag analizado | `v1.0.0` (SHA `dcfc232`) | [VERIFICADO GH] `gh api .../git/refs/tags/v1.0.0` -> `dcfc2322...` |

### Discrepancia de metadata (limitacion de evidencia, NO ignorar)

El packet de arranque cito `tag mattpocock-skills@1.0.0`, `release commit
00ff03c`, `change commit 47bde84`. Verificacion real con `gh`:

- `v1.0.0` -> SHA `dcfc2322f2f978113b1ec2dbbf50c00eda824519` [VERIFICADO GH].
- `mattpocock-skills@1.0.0` -> SHA `ad9690ac...` (distinto de `00ff03c`
  declarado) [VERIFICADO GH].
- `47bde84` aparece como commit de cambios en las release notes de `v1.0.0`
  [VERIFICADO GH, en el cuerpo del release].
- **Existe un release MAS NUEVO: `v1.0.1`** (Latest, publicado 2026-06-17
  22:07 UTC, posterior al v1.0.0 de las 14:46) [VERIFICADO GH] `gh release list`.

**Conclusion:** este analisis se ancla a `v1.0.0 / dcfc232` (el tag con notas de
cambio mayores y el que se reviso en sesion). Los IDs `00ff03c` del packet no se
pudieron confirmar como SHA de tag; se conserva el dato declarado pero se marca
`[NO VERIFICADO]`. Antes de cualquier adopcion (010s/010t), re-anclar al SHA
vigente y decidir si `v1.0.1` cambia algo.

---

## 2. Piezas externas y decision por pieza

Decision: **adoptar** (portar idea con fila CREDITS), **adaptar** (idea ajustada
a nuestro stack), **rechazar** (no aporta o choca), **diferir** (fuera de 010r).

| Pieza externa | Que es | Solape local | Decision | Ticket destino |
|---|---|---|---|---|
| `docs/invocation.md` (taxonomia user/model-invoked) | user-invoked (`disable-model-invocation: true`, description humana) vs model-invoked (description con triggers) | Nuestra dicotomia Commands/Skills en `.claude/rules/03-skills-discovery.md` (modelo Goose-era "triggers YAML max 3") | **adaptar** | decide aqui; migra en **010s** |
| `codebase-design` (deep module/interface/seam/adapter, deletion test) | Vocabulario de diseno de modulos profundos | Anti-patrones vivos: zero-logic wrapper (CLAUDE.md), index/inline R-006, "Test Util vs Basura" | **adaptar** | **010t** (review del Manager) |
| `diagnosing-bugs` (rename de `diagnose`) | Loop de diagnostico de bugs | `skills/systematic-debugging/SKILL.md` (limite 3 intentos) | **adaptar** (como guia; CONSERVAR limite 3) | **010t** |
| `writing-great-skills` (+ GLOSSARY) | Como escribir skills predecibles | `skills/create-agent-skill/SKILL.md` (parcial) | **diferir** | 008d/008e (taxonomia/naming) |
| `domain-modeling` (CONTEXT.md, ADRs) | Construir/afilar modelo de dominio | Contract Formation (familia 007: repo_charter, decisions) | **diferir** | familia 007 si se reabre |
| `ask-matt` (router user-invoked) | Router sobre otras skills user-invoked | `scripts/discover_skills.py` (trigger_map) | **rechazar** | — (asume bundle instalado; Breaking dep) |
| `resolving-merge-conflicts` | Loop standalone de conflictos merge/rebase | Ninguno directo | **diferir** | follow-up baja prioridad |

Notas:
- `ask-matt` se **rechaza**: `docs/invocation.md` dice que enruta sobre las demas
  skills user-invoked del bundle y "expects them to be installed" [VERIFICADO GH].
  Importarlo arrastra el grafo de dependencias Breaking; no encaja en un motor que
  adopta ideas, no bundles.
- Removidas en v1.0.0: `caveman`, `zoom-out` [VERIFICADO GH, release notes]. Sin
  impacto local (no las teniamos).

---

## 3. Inventario reproducible de consumidores locales de `triggers`/discovery

Comando reproducible (re-ejecutable por cualquier revisor):

```bash
grep -rEl 'fm.get\(.triggers|trigger_map|"triggers"' scripts/ bus/
```

Resultado [VERIFICADO CODIGO, 2026-06-18]:

| Consumidor | Que hace con `triggers` | Hits |
|---|---|---|
| `scripts/discover_skills.py` | construye `trigger_map` + `aliases` (L109,123); genera dispatch | 13 |
| `scripts/orquestador.py` | dispatch por trigger (motor de orquestacion) | 13 |
| `bus/skill_resolver.py` | filtro/resolucion de skill por trigger | 9 |
| `scripts/validate_agent_config.py` | valida triggers en config | 7 |
| `scripts/local_audit.py` | audita presencia/consistencia de triggers | 2 |
| `scripts/check_skill_collisions.py` | unicidad de triggers entre skills | 1 |

**Total: 6 consumidores reales.** [VERIFICADO CODIGO]

`bus/review_bridge.py` = **0 hits del campo** [VERIFICADO CODIGO]. NO es
consumidor: un grep ingenuo cuenta la palabra inglesa "triggers requeue"
(falso positivo que en sesion produjo el conteo erroneo 7; el real es 6).

`disable-model-invocation` = **no existe** en `skills/` ni `prompts/`
[VERIFICADO CODIGO] (`grep -rln disable-model-invocation` -> vacio).

**Implicacion clave:** matar el campo `triggers:` NO es migracion de nomenclatura
documental: reescribe el grafo de resolucion del bus (6 consumidores). Por eso
010r decide y 010s migra con barrera.

---

## 4. Decision arquitectonica: hibrido vs break-glass

Ver tambien la seccion `Decision Arquitectonica` del `work_plan.md`.

Dos rutas para introducir la taxonomia user/model-invoked:

- **break-glass:** retirar `triggers:` de golpe e introducir
  `disable-model-invocation`. Menor codigo transitorio, mayor riesgo: rompe los
  6 consumidores a la vez; cualquier fallo de paridad deja el bus sin resolver
  skills.
- **hibrido (RECOMENDADO):** `triggers:` y `disable-model-invocation` coexisten
  durante una ventana de transicion. `skill_resolver`/`discover_skills` respetan
  ambos; se migra consumidor a consumidor con test de paridad de `trigger_map`;
  `triggers:` se retira solo cuando los 6 consumidores ya no lo leen.

**Recomendacion [INFERENCIA, fundada en el conteo verificado]:** hibrido. El bus
es estado compartido de alto blast radius; la coexistencia permite barrera de
regresion incremental (`discover_skills.py --json` antes/despues equivalente) en
vez de un big-bang. La decision final de ruta la ratifica 010s con su test de
paridad.

---

## 5. Impacto sobre tickets posteriores

| Ticket | Estado | Impacto de este analisis | Accion propuesta |
|---|---|---|---|
| **010s** | candidate | Ejecuta la migracion de los 6 consumidores segun ruta decidida (hibrido). Debe mantener verde la gate `discover_skills.py --check-contract` (`scripts/run_gates_dispatch.py:158`, prompt<->skill, INDEP. de deliverable_type) [VERIFICADO CODIGO]. Efecto secundario: limpiar docstring Goose/Claw en `discover_skills.py:5` [VERIFICADO CODIGO] y decidir flag `--goose`. | Serializar 010r->010s. Barrera: test de paridad trigger_map. |
| **010t** | candidate | Porta vocabulario `codebase-design` al review del Manager + contrasta `diagnosing-bugs`. Gate anti-over-engineering: describir lo que existe, no exigir seams nuevos. | Ejemplo de referencia sobre un decision_artifact existente (p.ej. scope_gate 009b). |
| **008c** | pending | `writing-great-skills` y la taxonomia user/model-invoked refuerzan el Registry/INDEX generado. La taxonomia debe quedar fijada (010s) antes de que 008c genere el INDEX, para no indexar un modelo que va a cambiar. | Diferir 008c hasta cerrar 010s, o documentar que el INDEX se regenera tras 010s. |
| **008d** | pending | Migracion de naming con shims: la taxonomia user/model-invoked es la nomenclatura objetivo. 010r/010s la fijan; 008d aplica shims sobre ella. | 008d depende conceptualmente de 010s; revalidar premisa de 008d tras 010s. |

`008e` (retirada de shims) no se ve afectado por este analisis salvo por la
cadena 008d.

---

## 6. Politica CREDITS

`CREDITS.md` **no se toca en 010r** (es Forbidden Surface del ticket)
[VERIFICADO DIFF: 010r no modifica CREDITS.md]. Las filas candidatas ya estan
preparadas en `backlog.md` del destino y se mueven a `CREDITS.md` cuando el
ticket que ADOPTA la idea (010s para la taxonomia, 010t para el vocabulario)
se abra. Regla `AGENTS.md`: una fila por ticket que adopta idea externa.

---

## 7. Separacion VERIFICADO / INFERENCIA (resumen)

- **VERIFICADO (gh):** licencia MIT; SHA v1.0.0=dcfc232; existencia de v1.0.1;
  piezas del release y removidos (caveman/zoom-out); `ask-matt` espera bundle.
- **VERIFICADO (codigo):** 6 consumidores reales de `triggers`; review_bridge=0;
  `disable-model-invocation` ausente; `--check-contract` indep. de
  deliverable_type; docstring Goose en discover_skills:5.
- **INFERENCIA:** recomendacion hibrido-sobre-break-glass (fundada en blast
  radius del bus, no en medicion); que 008c deba diferirse a 010s.
- **NO VERIFICADO:** `release commit 00ff03c` del packet (no confirmado como SHA
  de tag; el real de mattpocock-skills@1.0.0 es ad9690a).

---

## 8. Conclusion

`mattpocock/skills v1.0.0` aporta dos ideas de alto valor adaptables (taxonomia
user/model-invoked -> 010s; vocabulario codebase-design -> 010t) y varias
diferibles. Ninguna se adopta en 010r. La ruta segura es **hibrida y
serializada** (010r decide -> 010s migra con paridad -> 010t vocabulario), con
re-anclaje al SHA vigente y chequeo de si `v1.0.1` altera el analisis antes de
ejecutar 010s. Cero codigo tocado en este ticket.
