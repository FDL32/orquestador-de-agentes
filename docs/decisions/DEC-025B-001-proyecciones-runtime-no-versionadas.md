# DEC-025B-001: Proyecciones de runtime de `.agent/collaboration/` no versionadas

**Ticket:** WOT-2026-025b
**Fecha:** 2026-09-24
**Estado:** DECIDED
**Autor:** Builder (WOT-2026-025b)

## Contexto

El motor (`repo_motor`, `orquestador_de_agentes`) trackea las 6 proyecciones de
`.agent/collaboration/` en su repositorio Git:

| Ruta | Estado original | Estado actual |
|------|----------------|---------------|
| `.agent/collaboration/STATE.md` | Trackeada | Destrackeada |
| `.agent/collaboration/TURN.md` | Trackeada | Destrackeada |
| `.agent/collaboration/work_plan.md` | Trackeada | **Mantiene trackeada** (excepcion) |
| `.agent/collaboration/execution_log.md` | Trackeada | Destrackeada |
| `.agent/collaboration/notifications.md` | Trackeada | Destrackeada |
| `.agent/collaboration/review_queue.md` | Trackeada | Destrackeada |

**Excepcion work_plan.md:** se mantiene trackeada porque el pre-handoff guard
(`scripts/pre_handoff_guard.py:1272-1298`, WOT-2026-009g) exige que
`work_plan.md` este commiteado en handoff. Destrackearla causaria
`HANDOFF_IMPOSSIBLE` (contradiccion entre el scope de este ticket y el guard).
Esta contradiccion se ficho como WOT-2026-075l (Alta).

El `agent_controller.py` del motor las reescribe en cada operacion
(`write_file(STATE_FILE, ...)`, `.agent/agent_controller.py:5079,6306,6593`),
asi que `git status --porcelain` del motor se ensucia sin que nadie lo toque
a mano.

**Premisas verificadas 2026-09-24 (no heredadas, medidas en esta sesion):**

1. Las 6 rutas originales estaban trackeadas (verificadas al inicio).
2. Ninguna de las 6 rutas exactas estaba en `.gitignore` del motor (solo habia
   exclusiones parciales como `.agent/collaboration/*_WOT-*.md`, `_archive/`,
   `archive/`).
3. `WOT-2026-020r` (el ticket que esta ficha citaba como bloqueante "ORDEN
   OBLIGATORIO: WOT-2026-020r PRIMERO") esta CERRADO desde 2026-07-16
   (`commit:5201482`, guard `_own_git_root` en `bus/evidence.py:48-116`).
   La ficha `backlog.md` NO refleja este cierre -- sigue citandolo como
   dependiente; este DEC corrige esa ficha como parte del cierre de `025b`.
4. Correccion al precedente citado por la ficha original: `.agent/runtime/`
   NO fue "destrackeado todo", sino que tiene una mezcla real de patrones
   parciales gitignorados (`*.json`, `*.txt`, `tmp/`, `session/`, `pytest-safe/`,
   etc.) MIENTRAS otros ficheros centrales siguen trackeados hoy
   (`events.jsonl`, `observations.jsonl`, `MEMORY.md`, `memory_profile.md`,
   `memory_rules.md`, `closeout_lessons.md`, `UPSTREAM_LEARNINGS.md`). No fue
   destrackear todo runtime: fue una migracion selectiva ficha a ficha.
   Este DEC nombra explicitamente que el precedente es PARCIAL, no total.

**Referencia de distribucion:** `MANIFEST.distribute` linea 93-99 lista las 6
rutas bajo el comentario `# Collaboration - solo superficies vivas (NO historial)`.
`scripts/check_distribution_boundary.py` falla con exit 1 si una entrada del
manifiesto resuelve a 0 ficheros trackeados. El precedente `WOT-2026-015c`
(commit `f220c7c`) retiro sus 3 lineas equivalentes de runtime en el MISMO
commit que el `git rm --cached` -- este DEC replica ese patron.

## Decision

### Rama (A): Destrackear + gitignorar -- ELEGIDA

Se ejecuta `git rm --cached` sobre las **5** rutas (excluyendo `work_plan.md`)
y se anaden al `.gitignore` del motor con las rutas exactas:

```
.agent/collaboration/STATE.md
.agent/collaboration/TURN.md
.agent/collaboration/execution_log.md
.agent/collaboration/notifications.md
.agent/collaboration/review_queue.md
```

Ademas se retiran las 5 lineas de `MANIFEST.distribute` (lineas 94-98).
`work_plan.md` se mantiene trackeado y en `MANIFEST.distribute`.

**Por que esta rama:**

1. **Es la unica rama que hace `git status --porcelain` reproducible vacio**
   tras una operacion normal del controller, que es la propiedad que la ficha
   original persigue ("el arbol del motor se ensucia solo sin que nadie lo
   toque a mano").
2. **Es consistente con el precedente YA aplicado (parcial) en
   `.agent/runtime/`:** el motor ya trata el estado operativo como no
   versionable por defecto: extenderlo a las 5 rutas de
   `.agent/collaboration/` cierra la mitad del mismo problema que quedo
   abierta.
3. **La rama (B) exigiria diseno nuevo:** mantener trackeadas las 5 rutas y
   inventar un mecanismo de "proteccion anti-suciedad" viola la regla de
   `AGENTS.md` "STOP de degeneracion" (WOT-2026-024u: de 3 lineas a "disenar
   un analizador estatico" en 5 parches).

**Excepcion work_plan.md (desviacion del plan original):**

El plan original de este ticket destrackeaba las 6 rutas. Se excluyo
`work_plan.md` porque `assert_work_plan_committed()` (`motor_checkpoint.py:76`)
exige que este fichero este commiteado en handoff. Destrackearlo provocaria
`HANDOFF_IMPOSSIBLE`. Esta contradiccion (scope del ticket vs pre-handoff
guard) se ficho como WOT-2026-075l (Alta) con recibo de admision valido.
Se mantiene `work_plan.md` trackeada con su contenido original (WOT-2026-022c,
de `commit:4e15446`).

**Riesgo declarado de la rama (A), y por que no bloquea:**

Perder `git log` futuro de esas 5 rutas. Mitigacion: decisiones significativas
ya viven en `CHANGELOG.md`/`PROJECT.md`/`docs/decisions/` por convencion
explicita de `AGENTS.md`; las proyecciones de `.agent/collaboration/` son
estado EFIMERO por diseno (se sobrescriben en cada ciclo), no un archivo
historico.

### Rama (B): Mantener trackeadas + mecanismo anti-suciedad -- DESCARTADA

Conservaria historial completo de las rutas pero exigiria diseno de un
mecanismo nuevo (p.ej. un hook que revierta o excluya la escritura del
evidence-gate) que no existe hoy. Se descarta por el patron "STOP de degeneracion"
de `AGENTS.md` (WOT-2026-024u).

### Rama (C): No decidir -- descartada

Es exactamente el estado actual que la ficha lleva desde julio: el arbol se
ensucia solo en cada operacion del controller.

## Consecuencias

- **El motor ya no trackea las 5 proyecciones de `.agent/collaboration/`**
  (STATE, TURN, execution_log, notifications, review_queue).
  `git ls-files` devuelve vacio para las 5 rutas. El contenido sigue existiendo
  en disco pero no se incluye en commits futuros.
- **`.gitignore` incluye las 5 rutas exactas.** `work_plan.md` NO se incluye
  (mantiene trackeado).
- **`MANIFEST.distribute` ya NO declara las 5 rutas destrackeadas.**
  `work_plan.md` SI se mantiene en el manifiesto.
  `check_distribution_boundary.py` pasa a exit 0.
- **El historico git de las 5 rutas se preserva** (el commit actual las incluye,
  `git log` anterior funciona). El historico post-commit no las incluira.
- **`backlog.md` del workspace destino se corrige:** `WOT-2026-020r` se retira
  como bloqueante activo (esta cerrado desde 2026-07-16) y se anade nota
  fechada confirmando que la dependencia esta satisfecha.
- **`repo_destino` NO se ve afectado:** el destino conserva su propio tracking
  operativo de estas 6 rutas; el motor es solo el producto portable y estas rutas
  son superficie operativa del destino, no del motor.

## Deuda declarada

- **WOT-2026-075l (Alta):** contradiccion entre el scope de este ticket
  (destrackear `work_plan.md`) y `assert_work_plan_committed()` que lo exige
  commiteado. Se resolvió a medio plazo manteniendo `work_plan.md` trackeada.
  Ticket dueno: por asignar; criterio de salida: `assert_work_plan_committed()`
  o bien acepta una exencion explicita (p.ej. `--no-wp-check` para este tipo
  de tickets), o bien se documenta que este ticket es la unica excepcion.
- El precedente de `.agent/runtime/` sigue siendo selectivo: varias ficheros
  de runtime siguen trackeados (`events.jsonl`, `observations.jsonl`, `MEMORY.md`,
  etc.). Unificar el patron seria un ticket propio si se decide.

## Criterios de aceptacion

- [x] Las 5 rutas aparecen en `.gitignore` del motor (NO work_plan.md).
- [x] `git ls-files` devuelve vacio para las 5 rutas.
- [x] Las 5 rutas siguen existiendo en disco (solo se destrackean del indice).
- [x] `.gitignore` del motor incluye las 5 rutas exactas.
- [x] `MANIFEST.distribute` ya no declara las 5 rutas (work_plan.md si).
- [x] `check_distribution_boundary.py` -> exit 0.
- [x] Mutation-verify: con el `.gitignore` corregido, `git status --porcelain`
      tras `--validate` es vacio; sin la correccion (gitignore revertido) es
      sucio.
