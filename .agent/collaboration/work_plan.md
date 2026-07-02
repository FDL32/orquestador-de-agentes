# Work Plan - WOT-2026-016f

## Metadata
- **ID:** WOT-2026-016f
- **Estado:** COMPLETED
- **deliverable_type:** analysis
- **Titulo:** Publicar la redaccion del MOTOR al remoto GitHub (force-push coordinado + sync ref-a-ref: reemplazar historia vieja con PII por la historia limpia de 016d)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor
- **Type:** HISTORY/publicacion (degradado de 'history' a 'analysis' por el enum del motor -- `_VALID_DELIVERABLE_TYPES = {code, documentation, research, analysis, mixed}` no incluye 'history'; naturaleza real = publicacion de una reescritura de historia git, no analisis de codigo). Operacion IRREVERSIBLE, PUBLICA, de alto blast-radius: requiere checkpoint humano con GO explicito antes del force-push.

## Objetivo

Publicar en el remoto GitHub `https://github.com/FDL32/orquestador-de-agentes.git`
la historia local LIMPIA que 016d dejo `READY_FOR_REVIEW` (main @ `26958b7`,
solo metadata noreply, username solo en 6 fixtures allowlisted), reemplazando la
historia VIEJA sin redactar que el remoto aun expone. Es el ULTIMO paso vivo del
motor: 016d redacto en local; 016f PUBLICA esa limpieza. 016f NO redacta.

Alcance confirmado por checkpoint READ-ONLY (2026-07-02) + decision humana:
la PII vieja (`<OWNER_EMAIL>`, `<BROKEN_ID_EMAIL>`, rutas username) vive en el remoto
NO solo en `main`, sino tambien en 2 ramas remotas huerfanas
(`chore/deps-bump-2026-06-01`, `chore/deps-bump-2026-07-01`) y en los 66 tags
remotos (cada tag cuelga de la historia vieja). Un force-push de solo `main` NO
limpia el remoto. Decision humana: SYNC COMPLETO CONTROLADO ref-a-ref con lease
(no `--mirror` ciego).

## Decision Arquitectonica

- El remoto se alinea al local via operaciones ref-a-ref, NO `--mirror` a ciegas
  (`--mirror` queda prohibido sin el inventario ref-a-ref, que ya existe:
  `C:/tmp/016f_ref_inventory_<ts>.txt`). Cada ref divergente se decide
  explicitamente.
- `main`: force-replace con `--force-with-lease=refs/heads/main:<SHA_REMOTO>`
  (aborta si el remoto cambio desde el snapshot).
- 2 ramas remotas con PII (`chore/deps-bump-*`): se BORRAN del remoto (no existen
  en local; contienen historia vieja con PII). Borrado explicito por ref.
- Tags: los 66 tags remotos apuntan a la historia vieja; se reemplazan por los
  135 tags locales limpios. Sin `--force` ciego a `--tags`; comparacion tag-a-tag
  o lease por ref (ver Fase 3).
- Ramas locales `backup/wt-2026-242a-pre-squash` y `regression-test-003d`: son
  local-only y PII-free; se decide con el humano si se publican o se dejan solo
  en local (por defecto NO se publican salvo GO explicito).
- Repo privatizado (`private=true`, confirmado 2026-07-02) ANTES del push para
  cortar la exposicion publica viva detectada en el checkpoint. El force-push
  MITIGA hacia adelante; NO borra copias externas/cache/indexes ya filtradas
  mientras el repo fue publico.

## Fases

### Fase 0 - Preflight y checkpoint READ-ONLY (COMPLETADO 2026-07-02)
- Preflight FAIL-CLOSED sobre `26958b7`: validate 0/0, arbol limpio, fsck exit 0,
  metadata solo noreply en `main`, gh 2.92 autenticado. VERDE.
- Checkpoint duro READ-ONLY: fetch aislado a `refs/remote-snapshot/*` (main NUNCA
  tocado), snapshot `C:/tmp/016f_remote_snapshot_<ts>.txt`, inventario ref-a-ref
  `C:/tmp/016f_ref_inventory_<ts>.txt`, branch protection (main NO protegida, 404),
  re-scan username anclado (0 fuera de allowlist). VERDE.
- Divergencia confirmada: LOCAL `26958b7` vs REMOTO `60baa66`, sin merge-base =
  REEMPLAZO, no fast-forward.

### Fase 1 - GO packet + checkpoint humano
- Presentar al humano: SHA local vs remoto, confirmacion de divergencia, snapshot,
  inventario ref-a-ref, plan de push exacto (comandos literales por ref), estado
  de proteccion, re-verificacion de limpieza. NO ejecutar sin GO explicito.

### Fase 2 - Force-push de `main` (ULTIMA accion escritora sobre historia; solo tras GO)
- `git push --force-with-lease=refs/heads/main:<SHA_REMOTO> origin main`.

### Fase 3 - Sync del resto de refs (solo tras GO, tras Fase 2)
- Borrar ramas remotas con PII: `git push origin --delete chore/deps-bump-2026-06-01 chore/deps-bump-2026-07-01`.
- Tags: comparar tag-a-tag local vs snapshot; empujar los 135 limpios y borrar del
  remoto cualquier tag que ya no exista en local o que diverja, por ref con lease
  o comparacion previa. Registrar la opcion usada.

### Fase 4 - Verificacion post-push (el push NO es el final)
- Re-clonar el remoto LIMPIO a un dir temporal fresco (no el local) y escanear PII:
  metadata solo noreply, username anclado 0 fuera de allowlist, fsck limpio,
  gitleaks == baseline. Verificar SOBRE EL CLON.
- Confirmar que las 2 ramas PII ya no existen en el remoto y que los tags apuntan
  a la historia limpia.
- Limpiar en el LOCAL los refs `refs/remote-snapshot/*` y `refs/remotes/origin/*`
  que trajeron la PII vieja al object-store, y `gc --prune=now` para no retener PII.
- Mantener el repo privado. Decidir (separado) si se anade branch protection a main.

## Criterios de aceptacion

Criterios binarios (DoD):

1. `origin/main` (tras re-fetch limpio o re-clone) == `26958b7`; `git log` del
   clon fresco no contiene `<OWNER_EMAIL>` ni `<BROKEN_ID_EMAIL>` en metadata (solo
   noreply).
2. Las ramas remotas `chore/deps-bump-2026-06-01` y `chore/deps-bump-2026-07-01`
   ya NO existen en el remoto (`git ls-remote --heads origin` no las lista).
3. Los tags del remoto apuntan a la historia limpia (0 tags remotos reachable
   desde `60baa66` que sigan en el remoto; los tags publicados == los 135 locales
   limpios byte-identicos).
4. Sobre un RE-CLONE fresco del remoto: username anclado (5 formas) = 0 fuera de
   la allowlist de 6 fixtures; fsck exit 0; gitleaks == baseline (0 delta).
5. El repo permanece `private=true`.
6. El force-push se ejecuto con `--force-with-lease` (o borrado explicito por ref),
   NUNCA `--mirror` a ciegas; cada ref divergente decidido explicitamente.

## Files Likely Touched

- N/A -- este ticket no produce codigo de aplicacion ni modifica archivos del
  arbol de trabajo. El "entregable" es el estado del remoto GitHub (refs
  publicados: main, tags, ramas borradas), no un diff de archivos. Los comandos
  operan sobre el remoto y sobre `.git/`, fuera del ambito de `Files Likely
  Touched` tradicional. Scope-override esperado (deliverable_type=HISTORY).

## Read/inspect only

- `.git/` local (historia limpia @ `26958b7`, fuente de verdad de lo que se publica).
- `refs/remote-snapshot/*`, `refs/remotes/origin/*` (snapshot READ-ONLY del remoto
  viejo, para comparacion ref-a-ref; se limpian en Fase 4).
- `C:/tmp/016f_remote_snapshot_<ts>.txt`, `C:/tmp/016f_ref_inventory_<ts>.txt`
  (evidencia local del checkpoint; NO versionar, tienen rutas locales).

## Non-goals

- NO redactar aqui. Si el local NO estuviera limpio -> ABORTAR (eso seria 016d).
  016f solo PUBLICA lo que 016d dejo limpio.
- NO `git pull`/`merge`/fetch-into-main NUNCA (reintroduciria PII vieja en `main`).
  El fetch de comparacion va siempre a namespace aislado.
- NO `--mirror` a ciegas. NO `push --force origin --tags` masivo sin comparacion
  previa (no respeta lease).
- NO force-push sin checkpoint humano y GO explicito. El force-push es la ULTIMA
  accion escritora sobre historia.
- NO publicar las ramas locales `backup/*` ni `regression-test-003d` salvo GO
  explicito del humano.
- NO cerrar 016d a COMPLETED antes de que el push este verificado sobre un clon
  fresco (016d se mantiene READY_FOR_REVIEW como red de seguridad; su
  `--manager-approve` va DESPUES del push verificado, por decision humana).
