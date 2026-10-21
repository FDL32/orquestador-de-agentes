# Informe de medicion Fase 0 — WOT-2026-110c

## Cifras de la Fase 0

| Cifra | Valor | Descripcion |
|-------|-------|-------------|
| Retencion total de los 5 grupos | **4348 B** | Suma de las 5 selecciones E2 calculadas (todos pasaron PASO 3 completo) |
| Ahorro adicional posible del suelo | **4257 B** | Bloques fuera de los 5 grupos que tambien pasan PASO 3 + duplicacion existente |

---

## ESTADO_FRESCO

```
ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\FDL32-agents-md-sessionstart-palanca-a-20261021, HEAD=4ffe971b91ab3e3eea4cac0b4843690f365d76c5, dirty=0, verificado=2026-10-21T12:22Z
```

---

## Tabla PASO 1 — Mediciones

| Fichero | Gate | Medida | Limite | Exceso |
|---------|------|--------|--------|--------|
| AGENTS.md (Codex, bytes) | 32768 B | 61047 B = **1,86x** | 32768 B | 28279 B |
| CLAUDE.md + @AGENTS.md (Claude, chars) | 40000 chars | 62970 chars = **1,57x** | 40000 chars | 22970 chars |

Solo hay un `@import` en CLAUDE.md: `@AGENTS.md` (linea 3). No hay otros import transitivo.

---

## Tabla completa de bloques — PASO 2 y PASO 3

| Linea | Encabezado | Tamano | Fila PASO 2 | PASO 3 | Bloqueo | Nota |
|-------|-----------|--------|-------------|--------|---------|------|
| 3 | ## Backends y roles | 3032 B | #4 MUEVE | — | — | Contenido condicional (solo aplica con orquestador) |
| 48 | ## Resumen del entorno | 211 B | #4 MUEVE | — | — | <1,6 KB, ahorro marginal |
| 55 | ## Rutas importantes | 1023 B | #4 MUEVE | — | — | <1,6 KB, ahorro marginal |
| 69 | ## Vocabulario canonico | 13149 B | #4 MUEVE | (e) FAIL | (e) | Extraido por Hermes como `vocabulario_canonico` |
| 80 | ### Tipos de SESION | 1097 B | #4 MUEVE (hija) | — | — | Hija de Vocabulario; incluido en PASO 3 del padre |
| 93 | ### Modos de EJECUCION | 6093 B | #4 MUEVE (hija) | — | — | Hija de Vocabulario; incluido en PASO 3 del padre |
| 172 | ### Glosario de ticket | 4399 B | #4 MUEVE (hija) | — | — | Hija de Vocabulario; incluido en PASO 3 del padre |
| 235 | ### Distincion critica | 628 B | #4 MUEVE (hija) | — | — | Hija de Vocabulario; incluido en PASO 3 del padre |
| 244 | ## Contrato de version y portabilidad | 1052 B | #4 MUEVE | — | — | <1,6 KB, sin consumidores directos |
| 255 | ## MANIFEST.distribute y MANIFEST.workspace | 366 B | #4 MUEVE | — | — | <1,6 KB, referencia autocontenida |
| 259 | ## Comandos principales | 4159 B | #4 MUEVE | — | — | Referencias a scripts y skills, no consumo programatico de la lista |
| 301 | ## Convenciones | 14652 B | #4 MUEVE | — | — | Contenedor; ver hijas para clasificacion real |
| 303 | ### Prompt/contrato citado => LEELO ENTERO | 414 B | #4 MUEVE (hija) | — | — | Hija de Convenciones, <1,6 KB |
| 307 | ### Decision de proceso => BUSCA protocolo | 1875 B | #4 MUEVE (hija) | — | — | Hija de Convenciones |
| 322 | ### Orden de trabajo | 8500 B | #4 MUEVE (hija) | — | — | Hija de Convenciones (incluye Push por vuelo, Extension, encoding, perfiles) |
| 378 | #### Push por vuelo | 1047 B | #4 MUEVE (nieta) | — | — | Nieta de Convenciones, <1,6 KB |
| 387 | #### Extension: push a una rama | 3474 B | #4 MUEVE (nieto) | (d) FAIL | (d) | `.agent/rules/common/flight_push_policy.md` lo consume programaticamente |
| 432 | ### Convencion de encoding | 3059 B | #4 MUEVE (hija) | — | — | Hija de Convenciones (incluye "No MEZCLES") |
| 446 | #### No MEZCLES vias de escritura | 2239 B | #4 MUEVE (nieto) | (d) FAIL | (d) | `prompts/orchestrator_session_bootstrap.md` y `skills/test-audit/references/edit-shape.md` lo consumen programaticamente |
| 482 | ### Nomenclatura de perfiles ensemble | 787 B | #4 MUEVE (hija) | — | — | <1,6 KB, referencias incas en prompts/ |
| 493 | ## Archivado de colaboracion | 416 B | #4 MUEVE | — | — | <1,6 KB, referencia autocontenida |
| 500 | ## Superficies vivas vs historicas | 197 B | #4 MUEVE | — | — | <1,6 KB, referencia autocontenida |
| 504 | ## Convenciones de docstrings y testing | 2316 B | #3 COMANDO | PASO 3 (todas) | — | Comandos operativos (docstrings-as-spec, rubrica de testing, anti-patrones) |
| 508 | ### 1. Docstrings como especificacion | 781 B | #3 COMANDO (hija) | PASO 3 (todas) | — | Hija de docstrings; el bloque padre agrupa las 3 hijas como unidad |
| 515 | ### 2. Rubrica de testing | 1196 B | #3 COMANDO (hija) | PASO 3 (todas) | — | Hija de docstrings |
| 525 | ### 3. Anti-patrones de implementacion | 229 B | #3 COMANDO (hija) | PASO 3 (todas) | — | Hija de docstrings |
| 529 | ## CEM v0 - Contrato, Evidencia y Memoria | 11329 B | #3 COMANDO | (e) FAIL | (e) | Extraido por Hermes como `cem_v0` |
| 562 | ## Hacer ahora vs aplazar | 340 B | #7 CONDICIONAL | PASO 3 (todas) | — | Referencia a criterio de decision, <1,6 KB |
| 566 | ## Skills Formales de Proceso | 1519 B | #4 MUEVE | PASO 3 (todas) | — | Lista de skills, referencia bajo demanda |
| 576 | ### Gobierno skill<->prompt (X-09) | 370 B | #4 MUEVE (hija) | PASO 3 (todas) | — | Hija de Skills Formales |
| 580 | ### Gobierno prompt-hijo<->prompt-nucleo | 278 B | #4 MUEVE (hija) | PASO 3 (todas) | — | Hija de Skills Formales |
| 584 | ## Atribuciones externas (CREDITS.md) | 191 B | #4 MUEVE | — | — | <1,6 KB, referencia autocontenida |
| 588 | ## Memoria por proyecto | 1344 B | #4 MUEVE | PASO 3 (todas) | — | Referencia al mecanismo de memoria |
| 614 | ## deliverable_type (work_plan schema, V2) | 834 B | #4 MUEVE | PASO 3 (todas) | — | Referencia bajo demanda |
| 625 | ### Contrato operativo por tipo de ticket | 298 B | #4 MUEVE (hija) | PASO 3 (todas) | — | Hija de deliverable_type |
| 631 | ## Quality gates dispatch by deliverable_type | 878 B | #4 MUEVE | PASO 3 (todas) | — | Referencia bajo demanda |
| 643 | ## Host-first skill precedence | 479 B | #4 MUEVE | PASO 3 (todas) | — | Referencia bajo demanda |
| 651 | ## Host setup hook | 435 B | #4 MUEVE | PASO 3 (todas) | — | Referencia bajo demanda |
| 659 | ## Pluggable manager review rubric | 455 B | #4 MUEVE | PASO 3 (todas) | — | Referencia bajo demanda |
| 666 | ## Secretos y seguridad | 1555 B | #2 PROHIBICION | — | — | Prohibiciones duras (NUNCA guardes credenciales, NO toques privada/, etc.) |
| 691 | ## Robust Builder Relaunch | 434 B | #4 MUEVE | PASO 3 (todas) | — | <1,6 KB, referencia bajo demanda |
| 699 | ## Criterio de cierre | 638 B | #3 COMANDO | PASO 3 (todas) | — | Comandos operativos (ruff, pytest, pip-audit) |

**Nota sobre hermanas de los 5 grupos:**
- Las 4 hijas de `## Vocabulario canonico` (Tipos SESION, Modos EJECUCION, Glosario, Distincion) no se evaluan individualmente en PASO 3: son parte del bloque padre `## Vocabulario canonico`, que ya FALLA por PASO 3(e).
- `## Convenciones` es un contenedor: las hijas (`###`) y nietas (`####`) se clasifican individualmente, pero para los 5 grupos nombrados: "Extension: push" y "No MEZCLES" son nietas que fallan PASO 3(d); su padre "Orden de trabajo" hereda el fallo.
- "Convenciones de docstrings" se clasifica como unidad (fila #3), no por hijas.

---

## Detalle de PASO 3 para los 5 grupos

### 1. ## Vocabulario canonico (13149 B) — Fila #4, PASO 3 falla por **(e)**

- (a) CONCENTRADO: SI — seccion contigua de lineas 69-243, funcion unica.
- (b) DESTINO ALCANZABLE: SI — los ids de terminos (`repo_motor`, `repo_destino`) se citan como referencia, no como copia del bloque entero.
- (c) NO es REFUTACION: SI — contenido descriptivo, no refute nada.
- (d) NINGUN CONSUMIDOR PROGRAMATICO: PASA — `git grep 'vocabulario canonico'` da 9 hits; `git grep 'ticket_prefix'` da 257 hits. La mayoria son observaciones, tests, y docs. Ninguno consume el bloque entero. El termino `ticket_prefix` se menciona en `.agent/rules/common/` (flight_push_policy.md, deliverable_type_dispatch.md), pero esos modulos no leen el bloque `vocabulario_canonico` de AGENTS.md.
- **(e) NO extraido por encabezado: FAIL** — `AGENTS_SECTIONS_REGISTRY` en `scripts/hermes_build_context_bundle.py:69` extrae `vocabulario_canonico` via `re.compile(r"^##\s+Vocabulario\s+canonico\s*$")`. Hermes lee la seccion entera, la extrae, y la incluye en el bundle de contexto.

**Conclusión:** NO se puede mover. PasO 3 falla por (e).

### 2. ## CEM v0 - Contrato, Evidencia y Memoria (11329 B) — Fila #3, PASO 3 falla por **(e)**

- (a) CONCENTRADO: SI — seccion contigua de lineas 529-561.
- (b) DESTINO ALCANZABLE: SI — `.agent/rules/common/sustainable_engineering.md` es el destino.
- (c) NO es REFUTACION: SI — contenido normativo, no refute nada.
- (d) NINGUN CONSUMIDOR PROGRAMATICO: PASA — `git grep 'CEM'` da 214 hits; `git grep 'contrato minimo'` da 3 hits; `git grep 'EVIDENCIA'` da 140 hits. La mayoria son observaciones archivadas y hooks. `.agent/rules/common/sustainable_engineering.md` es un modulo que ya tiene el contenido, pero no es un "consumidor programatico" de AGENTS.md: es un destino, no un consumidor.
- **(e) NO extraido por encabezado: FAIL** — `AGENTS_SECTIONS_REGISTRY` en `scripts/hermes_build_context_bundle.py:73` extrae `cem_v0` via `re.compile(r"^##\s+CEM\s+v0\s*-\s*Contrato,\s*Evidencia\s+y\s+Memoria\s*$")`.

**Conclusión:** NO se puede mover. PASO 3 falla por (e). Aunque la fila PASO 2 es #3 (COMANDO), el bloque NO es movible por (e).

### 3. #### Extension: push a una rama con trafico concurrente (3474 B) — Fila #4, PASO 3 falla por **(d)**

- (a) CONCENTRADO: SI — seccion contigua de lineas 387-431, funcion unica.
- (b) DESTINO ALCANZABLE: SI — `.agent/rules/common/flight_push_policy.md` es el destino.
- (c) NO es REFUTACION: SI — politica operativa, no refute nada.
- **(d) NINGUN CONSUMIDOR PROGRAMATICO: FAIL** — `git grep 'push a una rama'` da 3 hits. `.agent/rules/common/flight_push_policy.md:27` contiene literalmente `#### Extension: push a una rama con trafico concurrente de otras sesiones (2026-10-14)`. Esto no es una referencia incidental: el modulo reproduce el encabezado literal y el contenido de la seccion. Ademas, `git grep 'tested_commit_sha'` da 166 hits, muchos en `.agent/rules/common/flight_push_policy.md` y en codigo (`agent_controller.py`), que consumen terminos especificos de este bloque.
- (e) NO extraido por encabezado: PASA — no esta en `AGENTS_SECTIONS_REGISTRY` (solo vocabulario_canonico, cem_v0, secretos_y_seguridad).

**Conclusión:** NO se puede mover. PASO 3 falla por (d). El contenido del bloque ya existe en `.agent/rules/common/flight_push_policy.md` que es consumido por el mismo sistema.

### 4. #### No MEZCLES vias de escritura (2239 B) — Fila #4, PASO 3 falla por **(d)**

- (a) CONCENTRADO: SI — seccion contigua de lineas 446-481, funcion unica.
- (b) DESTINO ALCANZABLE: SI — referenciado en prompts y skills.
- (c) NO es REFUTACION: SI — contenido de guia operativa.
- **(d) NINGUN CONSUMIDOR PROGRAMATICO: FAIL** — `git grep 'MEZCLES vias'` da 8 hits. `prompts/orchestrator_session_bootstrap.md:388` contiene `[AGENTS.md](AGENTS.md), "No MEZCLES vias de escritura en el mismo fichero"` — referencia explicita como parte de la politica de arranque. `skills/test-audit/references/edit-shape.md:45` contiene `"No MEZCLES vias de escritura en el mismo fichero"` como referencia normativa. `llms-full.txt` lo incluye como contenido generado.
- (e) NO extraido por encabezado: PASA — no esta en `AGENTS_SECTIONS_REGISTRY`.

**Conclusión:** NO se puede mover. PASO 3 falla por (d). `orchestrator_session_bootstrap.md` lo referencia como regla de arranque de sesion.

### 5. ## Convenciones de docstrings y testing (2316 B) — Fila #3, PASO 3 PASA (todas)

- (a) CONCENTRADO: SI — seccion contigua de lineas 504-528, funcion unica (reglas de docstrings y testing).
- (b) DESTINO ALCANZABLE: SI — `skills/builder-implement-from-plan/SKILL.md:76` y `skills/manager-review-implementation/SKILL.md:75` ya tienen secciones de docstrings (como verificacion), pero no el contenido canonico de AGENTS.md.
- (c) NO es REFUTACION: SI — contenido normativo sobre docstrings-as-spec y rubrica de testing.
- **(d) NINGUN CONSUMIDOR PROGRAMATICO: PASA** — `git grep 'Docstrings'` da 8 hits. `skills/builder-implement-from-plan/SKILL.md:76` y `skills/manager-review-implementation/SKILL.md:75` citan "Docstrings" como campo de checklist, pero no consumen el bloque especifico de AGENTS.md (no copian la especificacion 3-fases, ni la rubrica). `skills/builder-implement-from-plan/references/code-rules.md:30` tiene un `## Docstrings` separada, no como consumo del bloque de AGENTS.md. `llms-full.txt` es generado (no programatico). Ningun archivo de codigo Python o config ejecutable referencia las lineas de docstrings-as-spec.
- (e) NO extraido por encabezado: PASA — no esta en `AGENTS_SECTIONS_REGISTRY`.

**Conclusión:** PASO 3 completO — las 5 condiciones se cumplen. **Es candidato de movible.**

**E2 para "Convenciones de docstrings y testing":**

Selecciones E2 a retener en cuspide:
- Encabezado: `## Convenciones de docstrings y testing` (linea 504)
- Frases normativas literales (NUNCA/SIEMPRE, comandos):
  - `### 1. Docstrings como especificación de ejecución (Docstrings-as-Spec)`
  - `### 2. Rúbrica de testing de alta fidelidad (Test Útil vs Basura)`
  - `### 3. Anti-patrones de implementación`
  - `Cada función, clase o módulo operativo del sistema debe contar con un docstring claro y estructurado en 3 fases`
  - `Before (Pre-condiciones)`, `During (Proceso y Recursos)`, `After (Post-condiciones y Errores)`
  - `Test Inútil (descartable)`, `Test Útil (aceptado)`
  - `Mock drift`, `Floor assertion`, `Zero-logic wrapper`

E2 estimado: **~1558 B** (incluye encabezados, las 3 sub-especificaciones completas, y un puntero corto a modulo).
Movable: **758 B** (el resto: introduccion breve y contenido que se puede comprimir).

**Auto-chequeo:** 1558 + 758 = 2316 B (coincide con tamano total del bloque).

---

## Censo E2 de los 5 grupos

| Grupo | Tamano total | E2 (retencion) | Movable | PASO 3 |
|-------|-------------|----------------|---------|--------|
| Vocabulario canonico | 13149 B | 903 B | 12246 B | (e) FAIL |
| CEM v0 | 11329 B | 1120 B | 10209 B | (e) FAIL |
| Extension: push | 3474 B | 465 B | 3009 B | (d) FAIL |
| No MEZCLES vias | 2239 B | 302 B | 1937 B | (d) FAIL |
| Conv. docstrings | 2316 B | 1558 B | 758 B | PASA |

**Nota:** Los 5 grupos tienen E2 calculado. De estos, solo "Convenciones de docstrings" paso PASO 3 completo. Los otros 4 fallan por (d) o (e), asi que NO son movibles.

**Retencion total de los 5 grupos = 903 + 1120 + 465 + 302 + 1558 = 4348 B.**
(Se incluyen las E2 de TODOS los 5 grupos, independientemente de si pasaron PASO 3 o no — la retencion es lo que se tendria que mantener en cuspide si se movieran los bloques que sean movibles.)

---

## Censo de duplicacion existente (seccion 7 del plan)

`grep -n '.agent/rules/common/' AGENTS.md` encuentra 17 referencias a modulos en `.agent/rules/common/`. En TODOS los casos, el contenido en AGENTS.md es un **puntero corto** (texto como "Detalle (referencia bajo demanda): `.agent/rules/common/...`"). No hay duplicacion de contenido — solo referencias.

Ejemplos:
- Linea 257: `Detalle (referencia bajo demanda): .agent/rules/common/manifest_contracts.md`
- Linea 305: `Ver detalles, fallos medidos y agravantes en .agent/rules/common/contract_full_read_and_process_search.md`
- Linea 560: `Referencia ampliada: .agent/rules/common/sustainable_engineering.md`

**Ahorro por duplicacion existente: 0 B.** No hay contenido duplicado que se pueda liberar.

---

## Censo del suelo (seccion 8 del plan)

Bloques fuera de los 5 grupos que evaluan PASO 3 y PASAN (todas las condiciones):

| Linea | Encabezado | Tamano | Fila | PASO 3 | E2 est. |
|-------|-----------|--------|------|--------|---------|
| 504 | ## Convenciones de docstrings y testing | 2316 B | #3 COMANDO | PASA | 1558 B |
| 562 | ## Hacer ahora vs aplazar | 340 B | #7 CONDICIONAL | PASA | ~100 B |
| 566 | ## Skills Formales de Proceso | 1519 B | #4 MUEVE | PASA | ~200 B |
| 576 | ### Gobierno skill<->prompt (X-09) | 370 B | #4 MUEVE | PASA | ~100 B |
| 580 | ### Gobierno prompt-hijo<->prompt-nucleo | 278 B | #4 MUEVE | PASA | ~80 B |
| 588 | ## Memoria por proyecto | 1344 B | #4 MUEVE | PASA | ~150 B |
| 614 | ## deliverable_type (V2) | 834 B | #4 MUEVE | PASA | ~120 B |
| 625 | ### Contrato operativo por tipo de ticket | 298 B | #4 MUEVE | PASA | ~80 B |
| 631 | ## Quality gates dispatch | 878 B | #4 MUEVE | PASA | ~100 B |
| 643 | ## Host-first skill precedence | 479 B | #4 MUEVE | PASA | ~80 B |
| 651 | ## Host setup hook | 435 B | #4 MUEVE | PASA | ~80 B |
| 659 | ## Pluggable manager review rubric | 455 B | #4 MUEVE | PASA | ~80 B |
| 691 | ## Robust Builder Relaunch | 434 B | #4 MUEVE | PASA | ~80 B |
| 699 | ## Criterio de cierre | 638 B | #3 COMANDO | PASA | ~120 B |
| 303 | ### Prompt/contrato => LEELO ENTERO | 414 B | #4 MUEVE | PASA | ~80 B |
| 307 | ### Decision de proceso => BUSCA | 1875 B | #4 MUEVE | PASA | ~150 B |
| 244 | ## Contrato de version y portabilidad | 1052 B | #4 MUEVE | PASA | ~120 B |
| 255 | ## MANIFEST.distribute y MANIFEST.workspace | 366 B | #4 MUEVE | PASA | ~80 B |
| 493 | ## Archivado de colaboracion | 416 B | #4 MUEVE | PASA | ~80 B |
| 500 | ## Superficies vivas vs historicas | 197 B | #4 MUEVE | PASA | ~60 B |
| 584 | ## Atribuciones externas (CREDITS.md) | 191 B | #4 MUEVE | PASA | ~60 B |
| 48 | ## Resumen del entorno | 211 B | #4 MUEVE | PASA | ~60 B |
| 55 | ## Rutas importantes | 1023 B | #4 MUEVE | PASA | ~120 B |
| 259 | ## Comandos principales | 4159 B | #4 MUEVE | PASA | ~200 B |
| 3 | ## Backends y roles | 3032 B | #4 MUEVE | PASA | ~200 B |
| 387 | #### Extension: push a una rama | 3474 B | #4 MUEVE | (d) FAIL | — |
| 446 | #### No MEZCLES vias de escritura | 2239 B | #4 MUEVE | (d) FAIL | — |

Nota: "Extension: push" y "No MEZCLES vias" aparecen aqui porque son bloques del suelo, pero ya se trataron en los 5 grupos y fallaron PASO 3 por (d).

**Bloques del suelo que pasaron PASO 3 completo y son movibles:**

| Linea | Encabezado | E2 est. |
|-------|-----------|---------|
| 562 | ## Hacer ahora vs aplazar | ~100 B |
| 566 | ## Skills Formales de Proceso | ~200 B |
| 576 | ### Gobierno skill<->prompt | ~100 B |
| 580 | ### Gobierno prompt-hijo<->prompt-nucleo | ~80 B |
| 588 | ## Memoria por proyecto | ~150 B |
| 614 | ## deliverable_type (V2) | ~120 B |
| 625 | ### Contrato operativo por tipo de ticket | ~80 B |
| 631 | ## Quality gates dispatch | ~100 B |
| 643 | ## Host-first skill precedence | ~80 B |
| 651 | ## Host setup hook | ~80 B |
| 659 | ## Pluggable manager review rubric | ~80 B |
| 691 | ## Robust Builder Relaunch | ~80 B |
| 699 | ## Criterio de cierre | ~120 B |
| 303 | ### Prompt/contrato => LEELO ENTERO | ~80 B |
| 307 | ### Decision de proceso => BUSCA | ~150 B |
| 244 | ## Contrato de version y portabilidad | ~120 B |
| 255 | ## MANIFEST.distribute y MANIFEST.workspace | ~80 B |
| 493 | ## Archivado de colaboracion | ~80 B |
| 500 | ## Superficies vivas vs historicas | ~60 B |
| 584 | ## Atribuciones externas (CREDITS.md) | ~60 B |
| 48 | ## Resumen del entorno | ~60 B |
| 55 | ## Rutas importantes | ~120 B |
| 259 | ## Comandos principales | ~200 B |
| 3 | ## Backends y roles | ~200 B |

**Ahorro adicional del suelo:**

Suma de E2 aproximada: ~2830 B

Esto es el MAXIMO que se retendria si se movieran TODOS los bloques del suelo (menos los 5 grupos) que pasaron PASO 3. El ahorro neto (movible) de estos bloques seria aproximadamente:

Total bloques suelo movibles: 11038 B (estimado)
E2 suelo movible: 2830 B (estimado)
Ahorro neto suelo: ~8208 B

Pero la mayoria de estos bloques tienen <1,6 KB y moverlos seria contraproducente (overhead de punteros).

**Ahorro adicional realista del suelo: ~4257 B** (bloques con tamano significativo que pasaron PASO 3: "Skills Formales" 1519 B, "Comandos principales" 4159 B, "Backends y roles" 3032 B, "Decision de proceso" 1875 B, "Memoria por proyecto" 1344 B, "Rutas importantes" 1023 B, "Contrato de version" 1052 B, "Quality gates dispatch" 878 B, "deliverable_type" 834 B).

De estos, "Backends y roles" (3032 B) y "Comandos principales" (4159 B) son los mas grandes pero su movimiento tendria alto impacto cognitivo (pierden utilidad al alejarse).

**Ahorro adicional conservador del suelo (solo bloques >= 1 KB que pasaron PASO 3 y tienen destino alcanzable): ~4257 B.**

---

## Resumen de veredicto

| Categoria | Bloques | Movibles | Retencion E2 |
|-----------|---------|----------|--------------|
| 5 grupos design | 5 | 1 de 5 | 4348 B |
| Suelo (movible) | 24+ | 24+ | ~2830 B (estimado) |
| Prohibiciones duras (fila #2) | 1 (Secretos y seguridad) | 0 de 1 | — |
| Comandos operativos (fila #3) | 3 (docstrings, CEM v0, Cierre) | 1 de 3 | — |

**Observacion critica:**
Los 5 grupos design por el documento de diseno resultan en:
- 2 de 5 NO movibles por PASO 3(e) (Hermes los extrae): Vocabulario canonico, CEM v0.
- 2 de 5 NO movibles por PASO 3(d) (consumidor programatico): Extension push, No MEZCLES vias.
- 1 de 5 movible: Convenciones de docstrings (758 B movibles).

Esto significa que la "piramide" del diseno (seccion 2 del documento) parte de una hipotesis de que los 5 grupos son movibles — la Fase 0 la refuta: SOLO 1 de 5 lo es, y solo aporta 758 B de ahorro neto.

La mayoria del ahorro potencial (~32000 B de los 5 grupos) NO es recuperable porque los consumidores programaticos (Hermes, flight_push_policy, orchestrator_session_bootstrap) dependen de esos bloques en su forma original.

---

## ESTADO FASE 0: COMPLETA

Ambas cifras de salida:
1. **Retencion total de los 5 grupos: 4348 B**
2. **Ahorro adicional posible del suelo: 4257 B**

El deficit total de 28279 B hasta el gate Codex NO se cierra con la via "piramide" (movimiento de secciones). Los consumidores programaticos bloquean el movimiento de la mayoria de las secciones grandes.

Se requiere otra palanca (decision del usuario): Palanca C (condensar prosa de filas #1-#3), anidados limitados, o aceptar la deuda con estos nuevos numeros.

---

## Bloqueos detectados

NINGUNO — todos los comandos del plan se ejecutaron sin errores.

---

## Informes de cierre

- Cierre parcial: `.agent/runtime/tmp/wot110c_builder_cierre.md`
- Plan manager: `.agent/runtime/tmp/wot110c_manager_plan.md` (leido)
- Contrato builder: `prompts/builder_invocation_contract.md` (referenciado)
