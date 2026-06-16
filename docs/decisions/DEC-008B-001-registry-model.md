# DEC-008B-001: Modelo de Registry de Skills

**Ticket:** WOT-2026-008b  
**Fecha:** 2026-06-16  
**Estado:** DECIDED  
**Autor:** Builder (Claude Code, Opus 4.8)

## Contexto

El sistema actual descubre skills mediante `discover_skills.py` que escanea
`skills/**/SKILL.md` y extrae frontmatter. No existe un archivo de registry
central. Este DEC decide si se adopta uno y de qué tipo.

## Opciones comparadas

### Opción 1: Registry central (`registry.json` en raíz del motor)

**Descripción:** Archivo único que lista todas las skills con sus triggers,
versiones y metadatos. El discovery lee el registry en vez de escanear el FS.

**Ventajas:**
- O(1) lookup vs O(n) scan del FS.
- Permite marcar skills deprecadas sin borrar carpetas.
- Facilita validación offline (sin FS) y generación de índices.

**Desventajas:**
- Fuente manual: puede desincronizarse con el FS real si el Builder olvida actualizar.
- Host-first precedence necesita merge lógico (bundle registry + host registry).
- Introduce una fuente de verdad nueva sin validación automática —
  un registry incorrecto es peor que no tener registry.
- Bloquea el añadir skills sin tocar el registry (fricción intencional, pero
  dificulta onboarding rápido).

**Compatibilidad host-first:** Media. Requiere que hosts tengan su propio
`registry.json` y que el motor merge ambos con precedencia host.

**Coste de migración:** Alto. Hay 29 skills; hay que generar el registry,
añadir validación en CI, y documentar el contrato de actualización.

**Relación con INDEX.md (008c):** Si se adopta, `registry.json` sería
autoridad lógica de API activa e `INDEX.md` sería una proyección generada
automáticamente (nunca fuente manual). Separación clara autoridad/proyección.

---

### Opción 2: Manifest por skill (`manifest.json` local en cada `skills/<name>/`)

**Descripción:** Cada skill tiene un `manifest.json` con sus metadatos,
además del `SKILL.md` existente.

**Ventajas:**
- Co-locación: la skill y su contrato viven juntos.
- El motor puede validar cada skill en aislamiento.
- Elimina la dependencia de frontmatter YAML ad-hoc.

**Desventajas:**
- Duplica información ya presente en el frontmatter de `SKILL.md`.
- 29 archivos nuevos. Alto coste de migración.
- No resuelve el problema de discovery global (sigue necesitando scan del FS).
- Host-first: misma complejidad que Opción 1.

**Coste de migración:** Muy alto. 29 manifests + actualizar parser +
potencial desincronización frontmatter ↔ manifest.

---

### Opción 3: `.claude-plugin/plugin.json` compatible con ecosystem Claude Code

**Descripción:** Adoptar el formato de plugin de Claude Code (si existiera un
estándar oficial) para declarar skills y triggers.

**Ventajas:**
- Potencial interoperabilidad futura con el ecosistema Claude.
- Estandarización externa.

**Desventajas:**
- No existe un estándar oficial documentado para plugins de skills en Claude Code
  a fecha 2026-06-16. Adoptar un formato especulativo introduce deuda.
- Requeriría adaptar el motor a un contrato externo que puede cambiar sin aviso.
- Coste de migración: desconocido y alto.

**Coste de migración:** Indeterminado. Bloqueado por ausencia de estándar.

---

### Opción 4: Discovery recursivo sin manifest (estado actual)

**Descripción:** `discover_skills.py` escanea `skills/**/SKILL.md`, extrae
frontmatter, construye trigger_map en memoria. No hay archivo de registry en disco.

**Ventajas:**
- Zero overhead adicional: añadir una skill = crear carpeta + `SKILL.md`.
- No hay desincronización fuente-manual posible: el FS es la única autoridad.
- Host-first precedence ya funciona: merge por scan del host skills dir.
- Sin fricción para onboarding: no hay registry que actualizar.

**Desventajas:**
- O(n) scan por invocación (29 skills: negligible; 300 skills: tolerable).
- No permite marcar skills deprecadas sin borrar carpetas (necesita workaround,
  p.ej. campo `status: deprecated` en frontmatter).
- INDEX.md (008c) tiene que ser proyección generada, no fuente manual.

**Compatibilidad host-first:** Excelente. Ya implementada y funcionando.

**Coste de migración:** Cero. Es el estado actual.

---

## Matriz de tradeoffs

| Criterio | Opción 1 (registry.json) | Opción 2 (manifest/skill) | Opción 3 (plugin.json) | Opción 4 (discovery actual) |
|---|---|---|---|---|
| Riesgo desincronización | Alto | Alto | Indeterminado | Ninguno |
| Host-first compat. | Media | Media | Desconocida | Excelente |
| Coste migración | Alto | Muy alto | Indeterminado | Cero |
| O(1) lookup | Sí | No | Depende | No (O(n), tolerable) |
| Deprecación sin borrar | Sí | Sí | Depende | Vía campo FM |
| Fricción onboarding | Alta | Muy alta | Alta | Baja |
| Validación automática | Requiere CI gate | Requiere CI gate | Desconocida | Implícita (parse_frontmatter) |

## Decisión

**ADOPTED: Opción 4 — Discovery recursivo sin manifest.**

**Justificación:**

1. El problema real de 008b era un BOM en el frontmatter que silenciaba una
   skill, no la ausencia de un registry. El fix (`utf-8-sig`) ya resuelve el
   falso verde sin necesidad de cambiar el modelo de autoridad.

2. A escala actual (29 skills), el coste de un registry central supera con
   creces el beneficio. La opción 4 tiene coste de migración cero y riesgo
   de desincronización cero.

3. El modelo de discovery recursivo ya soporta host-first precedence
   correctamente. Introducir un registry añadiría una fuente de verdad
   adicional que puede desincronizarse: esto viola el principio CEM v0
   "evidencia antes que relato" — un registry incorrecto es peor que no tener.

4. INDEX.md (008c) deberá generarse como proyección automática del discovery,
   nunca como fuente manual. Este contrato está implícito en esta decisión.

**Consecuencias:**

- `registry.json` no se crea en este ticket ni en 008c.
- Si en el futuro la escala supera ~200 skills y el scan se vuelve lento,
  revisar esta decisión con evidencia de tiempo real. Abrir ticket en ese punto.
- Las skills deprecadas se marcan con `status: deprecated` en frontmatter
  (no requiere mover/borrar carpeta). El discovery puede filtrar por `status`.
- INDEX.md (008c) es una proyección generada por `discover_skills --json`,
  no una fuente editada manualmente.
