# DEC-008B-002: Modelo de Discovery de Triggers

**Ticket:** WOT-2026-008b  
**Fecha:** 2026-06-16  
**Estado:** DECIDED  
**Autor:** Builder (Claude Code, Opus 4.8)

## Contexto

El sistema actual usa `triggers: [/foo, bar]` en el frontmatter de cada
`SKILL.md` como API de activación. Este DEC evalúa si mantener ese modelo,
migrar a discovery por `description` (estilo Claude Code nativo), o adoptar
un híbrido.

## Matriz allowlist vs frontmatter real (derivada de fuentes vivas, 2026-06-16)

Fuentes: `c:/Users/***REDACTED***/Proyectos_Python/orquestador_de_agentes_workspace/.agent/config/agents.json`
(`skill_allowlists`) y `discover_skills.py --json` post-fix (29/29 skills visibles).

### BUILDER allowlist (`skill_allowlists.BUILDER`)

| Trigger | Skill FM (post-fix) | Clasificación |
|---|---|---|
| `/impl` | Ausente | `ghost-pending` — alias corto de `/implement`; no existe skill propia |
| `/implement` | `bui-implement-from-plan` ✓ | Vivo |
| `/tdd` | `test-driven-development` ✓ | Vivo |
| `/test` | Ausente | `ghost-pending` — ninguna skill tiene `/test` como trigger principal |
| `/debug` | `systematic-debugging` ✓ | Vivo |
| `/refactor` | `refactor-manager` ✓ | Vivo |
| `/fix` | Ausente | `ghost-pending` — intención obvia, skill aún no existe |

### MANAGER allowlist (`skill_allowlists.MANAGER`)

| Trigger | Skill FM (post-fix) | Clasificación |
|---|---|---|
| `/review` | `code-review` (`man-review-implementation`) ✓ | Vivo (era BOM-casualty, ahora restaurado) |
| `/audit` | `self-audit` tiene `audit` (no-slash) | `ghost-partial` — trigger slash ausente en FM |
| `/validate` | Ausente | `ghost-pending` — no existe skill con trigger `/validate` |
| `/inspect` | Ausente | `ghost-pending` — no existe skill con trigger `/inspect` |
| `/compare` | `repo-compare` tiene `/compare` ✓ | Vivo |

### SUPERVISOR allowlist (`skill_allowlists.SUPERVISOR`)

| Trigger | Skill FM (post-fix) | Clasificación |
|---|---|---|
| `/orchestrate` | Ausente en FM (orchestrate-pipeline tiene `/pipeline`) | `ghost-pending` — alias legado |
| `/schedule` | `create-work-plan` tiene `/schedule` ✓ | Vivo |
| `/archive` | Ausente | `ghost-pending` — no existe skill con trigger `/archive` |
| `/report` | Ausente | `ghost-pending` — no existe skill con trigger `/report` |

### Resumen clasificación

- **Vivo (trigger en FM):** `/implement`, `/tdd`, `/debug`, `/refactor`, `/review`, `/compare`, `/schedule` — 7 triggers.
- **BOM-casualty (restaurado por 008b):** `/review` — ahora vivo.
- **Ghost-pending (en allowlist, skill ausente):** `/impl`, `/test`, `/fix`, `/validate`, `/inspect`, `/orchestrate`, `/archive`, `/report` — 8 triggers.
- **Ghost-partial (trigger en allowlist con forma distinta en FM):** `/audit` (FM tiene `audit` sin slash) — 1 trigger.
- **Nota:** `/deepseek-v4-flash` y `/gpt-5` mencionados en contexto previo no aparecen en `skill_allowlists`; son ruido de otro contexto. No clasificados aquí.

**Consecuencia de clasificación ghost-pending:** Los 8 triggers `ghost-pending`
en la allowlist son operativamente vacíos — si el orquestador los recibe, no
hay skill que los sirva. Esto no es un error de 008b (scope STOP), pero se
documenta como deuda explícita para tickets futuros (008e/008f o nuevo ticket).

---

## Opciones de modelo de discovery

### Opción A: Mantener `triggers` en frontmatter como API propia (estado actual)

**Descripción:** El campo `triggers: [/foo, bar]` en frontmatter de `SKILL.md`
es la API de activación. `discover_skills.py` construye el `trigger_map` a
partir de estos valores.

**Ventajas:**
- Explícito: el autor de la skill controla exactamente qué activa su skill.
- Ya funciona. 29 skills ya tienen `triggers`.
- Compatible con allowlists en `agents.json` (validación cruzada posible).
- Permite múltiples triggers por skill (aliases semánticos).

**Desventajas:**
- Requiere que el autor actualice `triggers` al renombrar o añadir aliases.
- No hay inferencia automática: un trigger ghost-pending requiere edición manual.

**Compatibilidad:** Excelente. Ya implementado y probado.

**Coste de migración:** Cero. Estado actual.

---

### Opción B: Discovery por `description` estilo Claude Code nativo

**Descripción:** En lugar de triggers explícitos, el sistema infiere qué skill
usar a partir del campo `description` usando matching semántico o keywords.
Similar a cómo Claude Code nativo resuelve herramientas por descripción.

**Ventajas:**
- Autor no necesita listar triggers; la descripción es suficiente.
- Más natural para LLMs que razonan por semántica.

**Desventajas:**
- Requiere un resolver semántico (embedding lookup o LLM call en el hot path
  del orquestador). Introduce una dependencia nueva no stdlib.
- No determinista: el mismo input puede resolver a skills distintas según el
  modelo o la versión del resolver.
- Incompatible con el diseño actual de `agents.json` (`skill_allowlists`
  usa triggers explícitos para control de acceso por rol).
- Rompe la trazabilidad: no se puede verificar qué skill se activó sin
  inspeccionar el log del resolver.
- Las allowlists pierden su semántica exacta.

**Coste de migración:** Muy alto. Requiere reescribir el discovery, el
`orquestador.py` y adaptar `agents.json`. Rompe backwards compat.

---

### Opción C: Híbrido (triggers + description fallback)

**Descripción:** Si hay triggers en frontmatter, se usan como match exacto.
Si no hay, se hace fallback a matching por `description`.

**Ventajas:**
- Backwards compatible con skills existentes.
- Permite skills sin triggers explícitos.

**Desventajas:**
- Dos codepaths de resolución con semánticas distintas: dificulta el debug.
- El fallback semántico hereda todos los problemas de la Opción B.
- La allowlist de `agents.json` sólo cubre triggers explícitos; skills sin
  triggers quedan fuera del control de acceso por rol.
- Complejidad adicional sin beneficio claro para la escala actual.

**Coste de migración:** Alto. Requiere resolver semántico + lógica de merge.

---

## Matriz de tradeoffs

| Criterio | Opción A (triggers FM) | Opción B (description) | Opción C (híbrido) |
|---|---|---|---|
| Determinismo | Sí | No | Parcial |
| Compatibilidad allowlists | Excelente | Rota | Parcial |
| Trazabilidad | Exacta | Opaca | Mixta |
| Coste de migración | Cero | Muy alto | Alto |
| Dependencias nuevas | Ninguna | LLM/embeddings | LLM/embeddings |
| Backwards compat | Total | Rota | Parcial |
| Control de acceso por rol | Exacto | No fiable | Parcial |

## Decisión

**ADOPTED: Opción A — Mantener `triggers` en frontmatter como API propia.**

**Justificación:**

1. Los triggers explícitos son la única forma de mantener control de acceso
   por rol determinista (allowlists en `agents.json`). La Opción B rompe este
   contrato; la Opción C lo debilita.

2. La Opción B introduce dependencias no stdlib y no determinismo en el hot
   path del orquestador. Viola el principio de zero dependencies del motor
   y dificulta el testing reproducible.

3. El problema de 008b (falso verde BOM) era de encoding, no del modelo de
   triggers. El fix `utf-8-sig` restaura 29/29 skills visibles. No hay
   evidencia de que cambiar el modelo de discovery sea necesario.

4. Los 8 triggers ghost-pending son deuda documentada, no un fallo del modelo.
   Se resuelven creando skills o retirando triggers de la allowlist en tickets
   posteriores.

**Consecuencias:**

- `triggers` en frontmatter permanece como API oficial y única de activación.
- Los 8 triggers ghost-pending se documentan como deuda en `backlog.md`
  (ticket 008e o nuevo). No requieren acción en 008b.
- `/audit` ghost-partial: la skill `self-audit` debe añadir `/audit` como
  trigger en su frontmatter para alinearse con la allowlist. Esto es un fix
  menor que puede incluirse en cualquier ticket que toque `self-audit`.
  No bloquea el cierre de 008b.
- Cualquier propuesta de discovery semántico (Opción B/C) requiere un ticket
  propio con evidencia de rendimiento y plan de migración de allowlists.
