# Inventario 3-buckets - WOT-2026-016d (reescritura de historia del MOTOR)

> Generado 2026-07-01 (pre-filter-repo). INSUMO del checkpoint humano. Decisiones FIRMADAS por el
> humano en sesion 2026-07-01. Todos los counts VERIFICADOS sobre `--all` (git --git-dir del motor
> con export GIT_CONFIG_COUNT=1 KEY_0=safe.bareRepository VALUE_0=all).
> Base: 799 commits, 135 tags. HEAD f6eba22.
> ACTUALIZADO 2026-07-01 (RD4/RD5, ver execution_log): base OPERATIVA LIMPIA = **795 commits**, 135
> tags, HEAD f6eba22 (tras EXPORT+DROP del stash con PII y quitar refs remote-tracking locales; el
> `origin` remoto real intacto, su limpieza es 016f). PII sobre 795: info@ 1470 metadata / 0
> contenido; <BROKEN_ID_EMAIL> 104 metadata; fdl-path 147 blobs unicos. La cifra 799 queda como base HISTORICA
> pre-RD4; la reescritura opera sobre 795.
>
> DIVERGENCIA CLAVE vs 016g (workspace): 016d NO copia el protocolo de 016g. El motor requiere
> filter-repo con CALLBACKS custom (--mailmap para emails + --file-info-callback path-aware con
> allowlist EXPLICITA de 4 fixtures + redaccion coordinada del 5o, NO exclusion categorica de tests/;
> + --message-callback para 2 mensajes). NO un --replace-text global. Post-check DIFERENCIADO.

## Naturaleza distinta de la PII del motor (por que 016d != 016g)
- El motor NO tiene `<WORKSPACE_ONLY_EMAIL>` (era exclusivo del workspace).
- El motor SI tiene `<BROKEN_ID_EMAIL>` (identidad git rota, 104 metadata) que el workspace no tenia.
- `<OWNER_EMAIL>` es la AUTORIA DOMINANTE del motor (738/799 commits author), NO PII accidental.
  Decision humana: MAPEAR (no borrar) -> preserva autoria via alias GitHub, protege email real.
- El username `***REDACTED***` aparece en TESTS de la logica de redaccion -> redactarlo alli neutralizaria
  asserts de seguridad. Decision humana: excluir tests/ del replace-text de rutas.

---

## BUCKET REDACTAR (PII real; FIRMADO)

| Item | Alcance verificado | Mecanismo | Capa |
|---|---|---|---|
| `<OWNER_EMAIL>` (autoria del dueno) | 1476 hits author/committer; 0 en contenido | mailmap / --email-callback -> `128408907+FDL32@users.noreply.github.com` | METADATA |
| `<BROKEN_ID_EMAIL>` (identidad git rota) | 104 hits author/committer | mailmap / --email-callback -> mismo noreply | METADATA |
| Ruta con username `***REDACTED***` | 85 commits (regex `Users[/\\]fdl`); 16 archivos FUERA de tests/ | --blob-callback: reemplazo 6 variantes SOLO si el path NO empieza por `tests/` -> `C:\Users\<user>` | CONTENIDO (excl. tests/) |

6 variantes de ruta a redactar (del aprendizaje 016g): `C:\`, `C:/`, `c:\`, `c:/`, `/c/`, `/C/` + `Users\***REDACTED***`.

## BUCKET MANTENER (NO son PII; redactarlos rompe la suite del motor; FIRMADO)

| Item | Por que se mantiene | Allowlist (paths esperados) |
|---|---|---|
| `<BROKEN_ID_EMAIL>` en CONTENIDO (3 commits) | `git config user.email "<BROKEN_ID_EMAIL>"` en setup de tests (email-basura tipo test@example) | tests/test_archive_collaboration_artifacts.py, tests/test_session_closeout.py, tests/unit/test_closeout_self_dirty_allowlist.py, tests/unit/test_delivery_hygiene_check.py |
| `Users\name` (1 commit) | Fixture de test: `assert r'C:\Users\name\file.txt' in result` | tests/unit/test_compress_canonical.py |
| `Users\x` (1 commit) | Fixture de test (username generico de ejemplo) | tests/ (test de compresion/redaccion) |
| `C:\Users\***REDACTED***` DENTRO de tests/ (4 archivos) | Dato-sensible-controlado en tests de la LOGICA DE REDACCION; redactarlo vuelve tautologicos los asserts `assert 'C:\Users\***REDACTED***' not in output` | tests/test_persistence_redaction.py, tests/test_redact.py, tests/unit/test_collect_system_health.py, tests/unit/test_project_root_resolution.py |
| `128408907+FDL32@users.noreply...`, `github-actions[bot]@...noreply` | Ya anonimos (alias GitHub / bot CI) | metadata |

## BUCKET DECIDIR (FIRMADO por el humano 2026-07-01)

| # | Item | Decision humana |
|---|---|---|
| D1 | <OWNER_EMAIL> (autoria dominante) | **MAPEAR -> noreply** (no borrar; preserva autoria, protege email) |
| D2 | <BROKEN_ID_EMAIL> metadata | **MAPEAR -> noreply** (identidad git rota) |
| D3 | fdl en rutas dentro de tests/ | **SUPERSEDED por RD2/RD3** (ya NO es "excluir tests/ categorico") |
| D4 | name/x/<BROKEN_ID_EMAIL>-en-contenido | **MANTENER** (fixtures; no son PII; redactar rompe tests) |
| D5 | 135 tags | **REESCRIBIR por defecto** (filter-repo los reapunta) |
| D6 | Divergencia con 016g (alli info@ se BORRO, aqui se MAPEA) | **Anotar, NO rehacer 016g** (016g ya COMPLETED; ambas protegen el email; decidir en 016f antes del push coordinado) |

### RE-FIRMA 2026-07-01 (sesion de ejecucion) - SUPERSEDE D3

Hallazgo adversarial en Fase 0 revalidada: bajo `tests/` hay **5** archivos con la ruta username,
no 4. El 5o (`tests/test_claude_memory_mirror.py`) NO es fixture de la logica de redaccion (usa la
ruta como raiz de test, con el username ACOPLADO a 2 asserts de slug, lineas 118 y 612). El D3
original ("excluir tests/ categorico") preservaria un username REAL en ese archivo. Re-decidido con
el humano (2 rondas de checkpoint):

| # | Item | Decision humana (RE-FIRMA) |
|---|---|---|
| RD1 | Criterio work_plan#3 "ruta username = 0 GLOBAL incl. tests/" | **OBSOLETO -> post-check DIFERENCIADO** gobierna: 0 FUERA de la allowlist, PRESENTE dentro. Governa el inventario, no el literal del work_plan. |
| RD2 | Que se preserva bajo tests/ | **Allowlist EXPLICITA de 4 archivos** (NO "todo tests/"). El blob-callback NUNCA toca: `tests/test_persistence_redaction.py`, `tests/test_redact.py`, `tests/unit/test_collect_system_health.py`, `tests/unit/test_project_root_resolution.py`. |
| RD3 | `tests/test_claude_memory_mirror.py` (5o) | **REDACTAR** (no es fixture de redaccion). Redaccion COORDINADA especial: reemplazar tanto la ruta (`Users/<user>`, `Users\<user>`) como el slug esperado (`Users-<user>-`, 7a variante con guion) para que input y asserts queden consistentes -> test verde. Verificacion byte/diff en dry-run OBLIGATORIA. |

**Allowlist FINAL que sobrevive con username:** solo los 4 tests de RD2. `test_claude_memory_mirror.py`
NO sobrevive con username (queda redactado, byte-consistente input+slug).

## POST-CHECK DIFERENCIADO (NO "todo literal = 0"; FIRMADO, actualizado por RE-FIRMA)
Tras el filter-repo, verificar por capas:
- **DEBE IR A 0:**
  * metadata: `git log --all --pretty='%ae%n%ce' | grep -c '<OWNER_EMAIL>'` = 0; idem `<BROKEN_ID_EMAIL>` = 0.
  * emails distintos en la historia = SOLO noreply + github-actions bot.
  * ruta username FUERA de la allowlist de 4 fixtures = 0. Esto INCLUYE `test_claude_memory_mirror.py`
    (redactado por RD3): la ruta username Y el slug (`Users-<user>-`) deben dar 0 en ese archivo.
- **DEBE SOBREVIVIR (allowlist; NO es fuga):**
  * `<BROKEN_ID_EMAIL>` en contenido = 3 commits (solo en los 4 tests de config git esperados; ver bucket MANTENER).
  * `Users\name` = 1, `Users\x` = 1 (fixtures).
  * ruta username dentro de los **4 tests de redaccion allowlisted** (RD2) = presente y byte-identico
    al backup. (El 5o, `test_claude_memory_mirror.py`, NO esta en esta allowlist: debe quedar en 0.)
- **Prueba ortogonal:** `git grep <PII-metadata> $(git rev-list --all)` para emails = 0.
- **gitleaks** `--config .gitleaks.toml` = no leaks found.
- **Suite del motor VERDE** tras la reescritura (los fixtures intactos garantizan que no se rompio;
  correr la suite canonica confirma que ni tests de redaccion ni de compresion se degradaron).

## Mecanica de ejecucion (sesion dedicada)
1. Backup mirror verificado (rev-list --count --all sobre el clon = 799).
2. Escribir --email-callback (2 emails -> noreply) y --blob-callback (reemplazo de 6 variantes de
   ruta fdl SOLO si b'tests/' NO es prefijo del filename del blob).
3. DRY-RUN sobre clon del backup; post-checks DIFERENCIADOS a verde ANTES del repo real.
4. filter-repo sobre el motor real; post-checks diferenciados; suite verde.
5. Rev1 (Manager fresh) + Rev2 fresh-context (G3). Cierre por bus.
6. Push a GitHub = decision humana coordinada (016f), posterior. Remoto motor AUN expuesto.
