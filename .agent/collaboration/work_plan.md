# Work Plan - WOT-2026-016d

## Metadata
- **ID:** WOT-2026-016d
- **Estado:** APPROVED
- **deliverable_type:** analysis
- **Titulo:** Redactar PII de la historia del MOTOR con git-filter-repo (email autoria -> noreply + identidad rota + rutas username)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor
- **Type:** HISTORY (degradado de 'history' a 'analysis' por limitacion del enum del motor -- `_VALID_DELIVERABLE_TYPES = {code, documentation, research, analysis, mixed}` no incluye 'history'; naturaleza real del ticket = reescritura de historia git, no analisis de codigo)

## Objetivo

Reescribir la historia git del MOTOR (799 commits en HEAD f6eba22) con
`git-filter-repo` para redactar 3 categorias de PII de autoria y de ruta,
verificables con `git log --all` sobre el repo resultante:

1. Mailmap de autoria: mapear el email `<OWNER_EMAIL>` (aparece en 1476
   registros de metadata de commit segun `git log --all --format='%ae%n%ce'
   | grep -c <OWNER_EMAIL>`) al alias GitHub
   `128408907+FDL32@users.noreply.github.com`. Es un MAPEO (no un borrado):
   preserva la autoria via el alias publico de GitHub y protege el email
   real del dueno del repo.
2. Mailmap de identidad rota: mapear `<BROKEN_ID_EMAIL>` en METADATA de commit (104
   registros de autoria/committer, verificable con el mismo comando de
   conteo sobre `%ae`/`%ce`) al mismo noreply de GitHub.
3. Replace-text de ruta con username: reemplazar la ruta que contiene el
   username `***REDACTED***` (85 commits detectados, con 6 variantes de separador/case:
   `Users\***REDACTED***`, `Users/***REDACTED***`, `users\***REDACTED***`, `users/***REDACTED***`, y las 2 variantes
   analogas con separador mixto) por un placeholder neutro en cada blob y
   cada mensaje de commit del historial donde aparezca la ruta.

Los 135 tags existentes se reescriben por defecto (comportamiento estandar
de `git-filter-repo`, que reescribe refs/tags salvo `--no-tag-rename` o
similar).

## Decision Arquitectonica

Se usa `git-filter-repo` (no `git filter-branch`, deprecado y mas lento)
porque soporta mailmap nativo (`--mailmap`) para (1) y (2) en una sola
pasada, y `--replace-text` para (3) en la misma invocacion o en una pasada
subsiguiente sobre el resultado. Las 2 categorias de mailmap (email real +
identidad rota) se resuelven con el MISMO mecanismo (`--mailmap`) porque
ambas son sustituciones de autoria; la ruta con username es un problema de
contenido/blob distinto y usa `--replace-text`.

Divergencia consciente con WOT-2026-016g (analogo en el repo WORKSPACE
hermano, ya COMPLETED): alli se BORRO `<OWNER_EMAIL>` de la historia.
Aqui se MAPEA a un alias noreply en vez de borrar, para preservar la
autoria real del dueno del repo via el alias publico de GitHub. Ambos
enfoques son validos para su contexto; esta decision queda registrada aqui
y NO bloquea el ticket.

## Fases

### Fase 1 - Preparacion y verificacion de conteos
- Confirmar en el arbol de trabajo actual (HEAD f6eba22, `git status` limpio)
  los 3 conteos citados en el Objetivo con comandos literales sobre
  `git log --all --format='%ae|%ce|%an|%cn'` (autoria) y sobre el contenido
  versionado para la ruta con username.
- Preparar el archivo de mailmap con las 2 entradas (email real, identidad
  rota) apuntando al mismo alias noreply.
- Preparar la regla de `--replace-text` con las 6 variantes de la ruta.

### Fase 2 - Ejecucion de git-filter-repo
- Ejecutar `git-filter-repo` con `--mailmap <archivo>` y `--replace-text
  <archivo>` sobre una copia de trabajo del repo (NO sobre el remoto; sin
  push en este ticket).
- Confirmar que los 135 tags fueron reescritos (no eliminados) via
  `git tag | wc -l` antes/despues.

### Fase 3 - Verificacion post-reescritura
- `git log --all --format='%ae%n%ce'` no debe devolver ninguna coincidencia
  de `<OWNER_EMAIL>` ni de `<BROKEN_ID_EMAIL>` en METADATA de commit.
- El contenido con la ruta `***REDACTED***` (6 variantes) no debe aparecer en ningun
  blob versionado ni mensaje de commit tras la reescritura
  (`git grep` sobre `git rev-list --all`).
- Las fixtures de test declaradas como Non-goals permanecen intactas y
  verificables por conteo exacto (ver Non-goals).

## Criterios de aceptacion

Criterios binarios (DoD):

1. `git log --all --format='%ae%n%ce' | grep -c <OWNER_EMAIL>` devuelve
   `0` sobre el repo reescrito.
2. `git log --all --format='%ae%n%ce' | grep -c <BROKEN_ID_EMAIL>` devuelve `0` sobre
   el repo reescrito (identidad rota en METADATA).
3. POST-CHECK DIFERENCIADO (RE-FIRMA 2026-07-01, RD1 supersede el criterio
   original "0 global"): la ruta con el username aparece 0 veces FUERA de la
   allowlist de 4 fixtures de redaccion, y PRESENTE (byte-identica al backup)
   DENTRO de esos 4 fixtures. Detalle:
   - Allowlist de 4 (el blob-callback NUNCA toca): `tests/test_persistence_redaction.py`,
     `tests/test_redact.py`, `tests/unit/test_collect_system_health.py`,
     `tests/unit/test_project_root_resolution.py` -> ruta username PRESENTE.
   - Todo lo demas (incl. `tests/test_claude_memory_mirror.py`, redactado con
     redaccion coordinada ruta+slug por RD3) -> ruta username y slug `Users-<user>-` = 0.
   Motivo del cambio: aplicar "0 global incl. tests/" volveria tautologicos los
   asserts `assert '...<user>...' not in output` de los 4 fixtures y degradaria
   silenciosamente la logica de seguridad testeada.
4. `git tag | wc -l` en el repo reescrito reporta 135 (mismos tags,
   reescritos, no eliminados).
5. Las fixtures de test (`Users\name`, `Users\x`, `<BROKEN_ID_EMAIL>` en CONTENIDO
   de `tests/`, y la ruta username en los 4 fixtures allowlisted de RD2)
   permanecen intactas: mismo conteo antes y despues de la reescritura,
   byte-identicas al backup.

## Files Likely Touched

- N/A -- este ticket no produce codigo de aplicacion ni modifica archivos
  del arbol de trabajo actual. El "entregable" es la historia git
  reescrita (commits, blobs, tags) del propio repositorio MOTOR, no un
  diff de archivos de contenido. Los comandos de `git-filter-repo` operan
  sobre el `.git/` del repo, fuera del ambito de `Files Likely Touched`
  tradicional.

## Read/inspect only

- `.git/` (historia completa, 799 commits, para auditoria de conteos antes
  y despues de la reescritura).
- `git log --all` (fuente de verdad para los 3 conteos del Objetivo).

## Non-goals

- NO ejecutar `git-filter-repo` sobre el repo WORKSPACE hermano (ese es
  WOT-2026-016g, YA COMPLETED, con su propia decision de borrar en vez de
  mapear).
- NO hacer `git push` en ningun momento de este ticket; la reescritura
  ocurre en un repo de trabajo local, sin publicar el resultado.
- NO tocar backups existentes (`.agent/backups/` u otros) ni crear uno
  nuevo como parte de este ticket.
- NO redactar las fixtures de test que NO son PII real: `Users\name`,
  `Users\x`, y las 3 apariciones de `<BROKEN_ID_EMAIL>` EN CONTENIDO de `tests/`
  (configuraciones de `git config user.email` usadas como fixture, no
  identidad real).
- NO mezclar esta reescritura con ningun ticket de codigo/mixed pendiente
  del motor; este ticket es exclusivamente de reescritura de historia.
