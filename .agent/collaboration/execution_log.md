# Execution Log - WOT-2026-016d

**Ticket:** WOT-2026-016d - redactar PII de la historia del MOTOR con git-filter-repo
**Estado:** IN_PROGRESS
**HEAD al inicio:** f6eba22

---

## Bootstrap

- Ticket materializado por el Manager (bootstrap de runtime): work_plan.md
  creado con Estado=APPROVED, deliverable_type=analysis (degradado de
  'history' por limitacion del enum del motor).
- `--bootstrap-ticket` emite el STATE_CHANGED inicial BOOTSTRAP -> IN_PROGRESS
  para WOT-2026-016d en el bus.

## Fase 0: Diagnostico + inventario (COMPLETADO 2026-07-01)

Inventario de PII del motor VERIFICADO sobre --all (evidencia dura, no sondeo):
- EMAILS: <OWNER_EMAIL> 1476 metadata / 0 contenido (autoria DOMINANTE del dueno,
  738/799 author -> MAPEAR a noreply, no borrar); <BROKEN_ID_EMAIL> 104 metadata / 3 contenido
  (identidad git rota en metadata -> mapear; en contenido es git config de tests ->
  MANTENER); lilliehernanders53 = 0 (no existe en el motor).
- RUTAS username: Users\***REDACTED*** 85 commits (16 archivos fuera de tests/ -> REDACTAR;
  4 archivos EN tests/ de la logica de redaccion -> MANTENER, fixture sensible-controlado).
- FIXTURES a MANTENER (no PII, romperian tests): Users\name (1), Users\x (1),
  <BROKEN_ID_EMAIL>-en-contenido (3), C:\Users\***REDACTED*** dentro de 4 tests de redaccion.
- 135 tags (reescribir por defecto).

Decisiones DECIDIR firmadas por el humano: ver
`.agent/collaboration/INVENTARIO_3BUCKETS_016d_20260701.md` (D1-D6 + post-check diferenciado).

## PAUSA 2026-07-01 (fin de sesion)

016d PAUSADO en IN_PROGRESS tras completar Fase 0 (inventario + decisiones firmadas).
La EJECUCION (backlog: escribir email-callback + blob-callback con exclusion de tests/,
backup mirror, dry-run, filter-repo real, post-check diferenciado, Rev1/Rev2, cierre bus)
se retoma en SESION FRESCA DEDICADA. Motivo del corte: 016d requiere filter-repo con
callbacks custom (mas delicado que 016g), no conviene ejecutarlo al final de sesion larga.
HEAD del motor SIN CAMBIOS (f6eba22): NO se ha reescrito nada, NO backup aun, NO push.
Handoff de arranque: C:\tmp\PROMPT_ARRANQUE_016d_016f_MOTOR_20260701.md
Insumo firmado: INVENTARIO_3BUCKETS_016d_20260701.md (bucket DECIDIR D1-D6 firmado).

## Fase 0 REVALIDADA + RE-FIRMA del bucket (2026-07-01, sesion fresca de ejecucion)

Re-medido contra la historia real (NO se copiaron cifras a ciegas; leccion 016g). Evidencia dura:
- HEAD f6eba22 (== inventario). 799 commits, 135 tags. Emails distintos (author+committer)
  en `--all`: SOLO noreply-FDL32, github-actions[bot]-noreply, info@ (metadata), <BROKEN_ID_EMAIL> (metadata).
- Metadata: info@ 1476, <BROKEN_ID_EMAIL> 104 (== inventario). Contenido: info@ 0 global (== inventario).
- Ruta username en CONTENIDO (regex `Users[/\\]<user>`): 85 commits. Archivos DISTINTOS que la
  contienen EN ALGUN MOMENTO de la historia: 26 (5 bajo tests/, 21 fuera de tests/). El inventario
  citaba "16 fuera de tests/" contando SOLO los presentes en HEAD (14 en HEAD + 7 borrados = 21 en
  toda la historia). El callback opera sobre TODOS los blobs de TODA la historia, no solo HEAD ->
  cubre los 7 borrados que un conteo HEAD-only omitiria.

HALLAZGO ADVERSARIAL (no cubierto por la firma D1-D6 original): bajo tests/ hay 5 archivos con la
ruta username, NO 4. El 5o (tests/test_claude_memory_mirror.py) NO es fixture de logica-de-redaccion:
usa la ruta como raiz de test y esta ACOPLADA a 2 asserts de slug (lineas 118 y 612):
`assert slug == "c--Users-<user>-Proyectos-Python-z-scripts"` derivado del input
`Path("C:/Users/<user>/Proyectos_Python/z_scripts")`. Redactar solo la ruta (6 variantes con
separador `/` o `\`) cambiaria el input pero dejaria el slug esperado con el username (forma con
GUION `Users-<user>-`, 7a variante) -> assert falso -> SUITE ROJA SILENCIOSA. Es exactamente el
fallo que el nit de verificacion de blobs del launch prompt advierte.

RE-DECISIONES HUMANAS FIRMADAS 2026-07-01 (checkpoint, 2 rondas de AskUser; CEM: bucket DECIDIR es
del humano, el Builder recomienda y el humano aprueba):
- RD1 (gobierna sobre work_plan#3): el criterio "ruta username = 0 GLOBAL incl. tests/" del work_plan
  quedo OBSOLETO. Gobierna el INVENTARIO firmado: post-check DIFERENCIADO -> ruta username = 0 FUERA
  de la allowlist; PRESENTE dentro de los fixtures de redaccion allowlisted. Se reescribe el criterio
  de aceptacion #3 del work_plan como post-check diferenciado (abajo).
- RD2: tests/ NO es exclusion categorica. Allowlist EXPLICITA de EXACTAMENTE 4 archivos (los fixtures
  de la logica de redaccion) que el blob-callback NUNCA toca:
    tests/test_persistence_redaction.py, tests/test_redact.py,
    tests/unit/test_collect_system_health.py, tests/unit/test_project_root_resolution.py
- RD3: tests/test_claude_memory_mirror.py se REDACTA (no es fixture de redaccion; deja username real).
  Redaccion COORDINADA especial para ese archivo: reemplazar tanto la ruta (`Users/<user>`,
  `Users\<user>`) como el slug esperado (`Users-<user>-`) por el placeholder, de modo que input y
  asserts queden consistentes y el test siga verde. Verificacion byte/diff en dry-run OBLIGATORIA.
- Allowlist FINAL que sobrevive con username: solo los 4 tests de RD2. El 5o NO sobrevive con username.

HEAD del motor AUN SIN CAMBIOS (f6eba22): re-firma es solo de artefactos de colaboracion; NO se ha
reescrito historia, NO backup aun, NO push.

## FASE 1 PREPARADA + PAUSA FAIL-CLOSED por hallazgo de base (2026-07-01)

Artefactos de reescritura ESCRITOS y VALIDADOS (fuera del repo, en scratchpad; NO commiteados):
- `motor.mailmap`: 2 entradas -> `FDL32 <128408907+FDL32@users.noreply.github.com>` para
  `<<OWNER_EMAIL>>` (name actual `***REDACTED***`, 738 author) y `<<BROKEN_ID_EMAIL>>` (name actual `T`, 52). El
  `--mailmap` de filter-repo reescribe author + committer + TAGGER (verificado en --help) -> cubre
  las etiquetas anotadas cuyo tagger lleva PII.
- `file_info_cb.py` (--file-info-callback, path-aware; --blob-callback NO recibe el path, por eso se
  usa file-info): allowlist EXACTA de 4 fixtures (RD2) -> sin tocar; `test_claude_memory_mirror.py`
  (RD3) -> redaccion COORDINADA ruta + slug; resto -> regex username-path IGUAL a bus/redact.py
  (`(?i)([a-z]:[/\\]users[/\\])([A-Za-z0-9_-]+)` -> `\1***REDACTED***`). Instrumentado con
  ADU016D_SAMPLE_LOG para samplear decisiones por path en el dry-run.
- `message_cb.py` (--message-callback): misma regex username-path para los 2 commits cuyo MENSAJE
  cita la ruta (5a0faae, f3db5e9). Emails en mensajes = 0 (verificado), no requieren redaccion.
- Placeholder canonico CONFIRMADO empiricamente: `derive_project_slug(Path("C:/Users/***REDACTED***/
  Proyectos_Python/z_scripts"))` == `c--Users-***REDACTED***-Proyectos-Python-z-scripts`. Es decir,
  input redactado + slug redactado quedan CONSISTENTES -> el test de RD3 sigue verde. `.resolve()` no
  rompe con `***REDACTED***` (los `*` sobreviven la slugificacion).

Backup mirror creado (scratchpad, fuera del arbol): 799 commits / 135 tags / HEAD f6eba22 (== fuente).
NOTA (nit ALTO, review 2026-07-01): este backup 799 queda **STALE** en cuanto se resuelva el stash
(RD4) y se quiten los remote-tracking (RD5). La base 799 NO es base operativa limpia. El backup que
cuenta como GATE FINAL se rehace DESPUES de RD4/RD5, sobre la base recalculada. No usar el backup 799
como vigente para el filter-repo real.

HALLAZGO DE BASE (no previsto por el inventario; PARA fail-closed): los "799 commits" NO son todos
locales-alcanzables. Desglose real medido:
- 795 alcanzables desde refs LOCALES (refs/heads/{main,backup/wt-2026-242a-pre-squash,
  regression-test-003d} + 135 tags).
- 4 restantes = remote-only / stash:
  * refs/stash@{0} = 3 commits (41329ec WIP + 7e84390 index + f4b38ac untracked), "WIP on main ...
    evidence seam", AUTORADOS POR <OWNER_EMAIL> -> PII en metadata. filter-repo DESCARTA
    refs/stash por defecto. ES TRABAJO WIP VIVO DEL DUENO.
  * d7ab0b1 = commit de bot CI en refs/remotes/origin/chore/deps-bump-2026-06-01 (ya anonimo).

DECISIONES HUMANAS FIRMADAS 2026-07-01 (3a ronda de checkpoint):
- RD4 (STASH): PARAR. El dueno revisa stash@{0} y decide (convertir a rama/commit real, exportar
  fuera del repo, o dropear) ANTES de cualquier filter-repo. Fail-closed: no se descarta ni se
  reescribe WIP vivo dentro de una operacion irreversible sin revision humana. Tras resolverlo,
  RECALCULAR base (`rev-list --count --all`) y RE-FIRMAR inventario + rehacer backup.
- RD5 (REMOTE-TRACKING): base de 016d = SOLO refs locales reescritas (795 + lo que quede del stash
  segun RD4). Quitar refs/remotes/origin/* del working copy antes de filter-repo para no mezclar
  016d con 016f. NO borrar el `origin` remoto real (solo refs remote-tracking locales). El remoto
  real SIGUE SUCIO hasta 016f + force-push humano. Revalidar conteos tras quitar remote-tracking.
- RD6 (PLACEHOLDER, nit BAJO review 2026-07-01): la redaccion de HISTORIA usa `***REDACTED***`, el
  MISMO placeholder que bus/redact.py (runtime) -> UNA sola convencion en todo el repo (runtime +
  historia + 5o test coordinado). Se descarto `<user>` (mas legible) para no crear dos convenciones
  para la misma operacion irreversible (confundiria auditorias/post-checks futuros). Confirmado
  empiricamente: input y slug redactados a `***REDACTED***` quedan consistentes; los `*` sobreviven
  la slugificacion. Los callbacks ya escritos (file_info_cb.py, message_cb.py) ya usan este valor:
  NO requieren cambio. Cambiar la convencion runtime seria un ticket separado.

ESTADO: 016d IN_PROGRESS, PAUSADO fail-closed en pre-dry-run. HEAD f6eba22 SIN CAMBIOS. NADA
reescrito, NADA commiteado en el motor, NADA pusheado. El stash sigue intacto. Artefactos de
reescritura listos en scratchpad para el resume.

PRECONDICIONES DE RESUME (cuando el dueno resuelva RD4):
1. Resolver stash@{0} (rama/export/drop) -> `git stash list` refleja la decision.
2. Recalcular base: `rev-list --count --all` y desglose local vs remote-only.
3. Rehacer backup mirror verificado sobre la base nueva.
4. Quitar refs/remotes/origin/* del working copy (RD5); revalidar conteos.
5. Re-firmar inventario si la base cambio.
6. Reanudar en: DRY-RUN sobre clon del backup (sampleo de paths + verificacion byte-identica de los
   4 allowlisted + suite verde en el clon) ANTES del filter-repo real.

## RD4/RD5 EJECUTADAS + BASE RECALCULADA (2026-07-01)

STASH resuelto (RD4, decision humana: EXPORT + DROP, decidido por DIFF no por nombre):
- Inspeccion read-only en 2 pasos (--stat acotado -> patch completo). Contenido: UN cambio de
  DOCSTRING puro en `scripts/install_agent_system.py` (+6/-5), 0 untracked, sin secretos/PII.
  OBSOLETO: el archivo fue tocado por 7+ commits desde la base del stash (74bc96d), incl.
  50beca6/ff05b8d que rehicieron la MISMA logica de residuos; el HEAD actual ya describe el punto
  con mas precision que el docstring stasheado. Sin trabajo util que rescatar.
- Export de respaldo (barato, fuera de la historia): `C:\tmp\stash_evidence_seam_20260701.patch`
  (1348 bytes, verificado > 0 ANTES del drop).
- `git stash drop stash@{0}` -> Dropped (41329ec). `git stash list` VACIO. No convertido a rama
  (obsoleto = solo ruido); no conservado dentro del repo.

REMOTE-TRACKING resuelto (RD5):
- `git update-ref -d` sobre refs/remotes/origin/{HEAD,chore/deps-bump-2026-06-01,main} -> 0 refs
  remote-tracking. El `origin` remoto real (config) INTACTO:
  https://github.com/FDL32/orquestador-de-agentes.git (fetch+push). El remoto real SIGUE SUCIO,
  limpieza en 016f (push coordinado humano). El commit de bot d7ab0b1 queda sin referenciar.

BASE OPERATIVA LIMPIA (revalidada; SUPERSEDE la base 799):
- 795 commits (== `--all` == local heads+tags), 135 tags, HEAD f6eba22. Sin stash, sin remote-tracking.
- PII recontada sobre 795: info@ metadata 1470 (era 1476; -6 del stash), <BROKEN_ID_EMAIL> metadata 104,
  info@ contenido 0. Emails distintos: 3 (noreply-FDL32, info@, <BROKEN_ID_EMAIL>) -> el bot email desaparecio
  (solo estaba en el commit remote-only). Tras el mailmap deberian quedar SOLO noreply (1 email).
- fdl-path en blobs unicos de toda la historia: 147 (era 150 en 799). Baseline del post-check:
  post-rewrite -> 0 fuera de la allowlist de 4; presente solo en los 4 fixtures.

BACKUP re-hecho sobre 795 (GATE FINAL vigente): scratchpad/motor_backup_795.git = 795/135/f6eba22,
0 remote-tracking, 0 stash. El backup 799 anterior renombrado a *_STALE_799.git (no vigente).

ESTADO: 016d IN_PROGRESS. RD4/RD5 completas. Base limpia 795 lista. Motor SIN reescribir (HEAD
f6eba22), SIN commits, SIN push. SIGUIENTE PASO: DRY-RUN sobre clon del backup 795 (sampleo de
paths del callback + byte-identico de los 4 allowlisted + suite verde) ANTES del filter-repo real.

## DRY-RUN (3 iteraciones; el gate CAZO 2 bugs reales antes del repo real) - 2026-07-01

Todos los dry-runs sobre clon fresco del backup 795 (filter-repo, exit 0). El gate hizo su trabajo:

- DRY-RUN #1: post-checks metadata OK, PERO el scan de contenido revelo `CHANGELOG.md` con la ruta
  username SIN redactar. CAUSA (bug #1): la regex copiada de bus/redact.py tiene lookahead
  `(?=[/\\]|$)` que EXIGE separador o fin de linea tras el username -> FALLA cuando el username va
  seguido de terminador no-separador (backtick/comilla/parentesis/espacio), p.ej. `` `c:\Users\***REDACTED***` ``
  en prosa. FIX: eliminar el lookahead en file_info_cb.py y message_cb.py (el `[a-zA-Z0-9_-]+` ya es
  greedy y auto-terminante; superset estricto, sin sobre-redaccion). NOTA: este bug tambien existe en
  bus/redact.py (runtime) -> candidato a ticket separado del codebase.
- DRY-RUN #2 (regex sin lookahead): CHANGELOG limpio, PERO byte-check revelo `test_compress_canonical.py`
  MODIFICADO: el callback sobre-redacto `Users\name` -> `Users\***REDACTED***`. CAUSA (bug #2): la
  allowlist RD2 solo cubria los 4 fixtures de logica-de-redaccion, pero D4 tambien exige MANTENER el
  fixture generico `Users\name` (username de ejemplo, NO PII) que vive en test_compress_canonical.py.
  FIX: anadir tests/unit/test_compress_canonical.py a la allowlist (ahora 5 archivos). (El fixture
  `Users\x` vive en test_project_root_resolution.py, ya allowlisted en RD2.) Esto es cumplir D4, no
  una decision humana nueva.
- DRY-RUN #3 (allowlist=5, regex sin lookahead): TODO VERDE.
  * tests/ modificados a HEAD: SOLO tests/test_claude_memory_mirror.py (redaccion coordinada
    intencional). Ningun otro fixture tocado.
  * metadata: info@ 0, <BROKEN_ID_EMAIL> 0; emails distintos = SOLO 128408907+FDL32@users.noreply.github.com.
  * taggers de tags anotadas: 0 PII (mailmap cubre tagger). mensajes de commit con ruta: 0.
  * fdl-path en contenido (con-drive y bare `Users\***REDACTED***`): presente SOLO en los 4 fixtures de redaccion
    (test_persistence_redaction, test_redact, test_collect_system_health, test_project_root_resolution);
    0 en todo lo demas (CHANGELOG, 5o file, no-tests).
  * allowlist de 5: BYTE-IDENTICA al backup (sha256). <BROKEN_ID_EMAIL>-contenido presente en sus 4 test-config
    (metadata=0 pero contenido>0: NO es 0-global, no se borro el fixture). Users\name, Users\x presentes.
  * sample-log: SKIP_ALLOWLIST 10, REDACT_COORD_CHANGED 4, REDACT_PATH_CHANGED 201, SKIP_NOMATCH 3493.
  * SUITE (gate de redaccion, targeted): los 6 archivos de test afectados por redaccion en el clon ->
    **106 passed, 0 failed** (1.04s). Verificado por nombre: TestRealPathSlug::test_workspace_slug
    PASSED (el assert de slug coordinado line 612), test_windows_path_preserved PASSED (fixture name).

Callbacks FINALES (en scratchpad, listos para el repo real): mailmap (2 emails->noreply),
file_info_cb.py (allowlist=5, regex sin lookahead, redaccion coordinada del 5o), message_cb.py
(regex sin lookahead).

GITLEAKS sobre dry-run #3: 3 findings, PERO IDENTICOS al backup (mismo set exacto; 016d no introdujo
ni elimino ninguno). Son dummies/ejemplos pre-existentes, FUERA de scope de 016d (PII):
  #1 sk_live_0123456789abcdefXYZ en agent_system/templates/gitleaks.config.toml (ejemplo del template)
  #2 TOKEN=valorsincomillas0123456789abcd en tests/test_classify_publication.py (fixture)
  #3 sk_live_0123456789abcdefXYZ en tests/test_classify_publication.py (fixture)
Ninguno es email/username; son valores de ejemplo (0123456789abcdef) para TESTear deteccion de
secretos. Candidatos a limpieza en ticket separado (no 016d). Para 016d = limpio (0 fugas de PII).

CHECKPOINT HUMANO PRE-REPO-REAL: el dry-run #3 esta 100% verde (2 bugs cazados y corregidos +
suite 106/0 + post-checks diferenciados + gitleaks sin regresion). El SIGUIENTE paso es IRREVERSIBLE
(filter-repo sobre el motor real). Barrera: NO filter-repo sin los 3 puntos del checkpoint humano.

## GO PACKET (4 anclajes con evidencia literal) - 2026-07-01

ANCLA 1 - CALLBACKS CONGELADOS (sha256; el repo real DEBE usar exactamente estos):
  congelados en scratchpad/FROZEN_callbacks_016d/ (+ SHA256SUMS.txt; verify -c = OK):
  - motor.mailmap    sha256=573129b8478e2d83a8101527cbf7f94f31283f8ef3147d4de24e66c489b5225d (128B)
  - file_info_cb.py  sha256=db8f6c83372f03d4fe5f95558e0ea3e24517655f5a24de2c6d54b9b400d05ae3 (4537B)
  - message_cb.py    sha256=5ad53423e6cfe5f7031c7f3617ce4c6429850bfd97406544f39a9a923a1e4c60 (905B)

ANCLA 2 - BACKUP VIGENTE (comando + resultado literal):
  path: scratchpad/motor_backup_795.git
  `git -C <backup> rev-list --count --all` = 795 ; `git tag | wc -l` = 135
  `git -C <backup> rev-parse HEAD` = f6eba2265e461ce37ad5a155709056237935c28f
  `git -C <backup> fsck --full` -> exit 0, SOLO objetos dangling (tags/trees/blobs sin ref, benigno
  tras mirror de repo con refs podadas); NINGUN missing/corrupt object.

ANCLA 3 - DRY-RUN #3 (el clon que paso todos los gates):
  HEAD 19cf69105afa33233e2d1d08c22d8cc18f7bf5dd ; --all 795 ; tags 135 ;
  emails distintos = SOLO 128408907+FDL32@users.noreply.github.com.
  Post-check resumen: metadata info@/<BROKEN_ID_EMAIL>=0; fdl-path solo en 4 fixtures; allowlist(5) byte-identica;
  suite redaccion 106 passed/0 failed.

ANCLA 4 - ESTADO REAL DEL MOTOR JUSTO ANTES (literal):
  HEAD f6eba2265e461ce37ad5a155709056237935c28f ; --all 795 ; tags 135.
  stash list = 0 (vacio). refs/remotes/* = 0 (RD5 aplicado). status = solo artefactos 016d
  (M STATE/TURN/execution_log/work_plan, ?? AUDIT/INVENTARIO).
  origin remoto CONFIGURADO E INTACTO: https://github.com/FDL32/orquestador-de-agentes.git (fetch+push).
  ATENCION: filter-repo por defecto ELIMINA el remote `origin` LOCAL tras reescribir (mecanismo de
  seguridad anti-push de refs viejas). Es cambio LOCAL de config; el remoto GitHub NO se toca. Se
  re-anade origin despues si 016f lo necesita (URL guardada arriba). El checkout de filter-repo
  DESCARTA los artefactos 016d sin commitear -> YA PRE-SALVADOS en scratchpad/016d_artifacts_presave/,
  se restauran post-reescritura.

GITLEAKS - EXCEPCION ACEPTADA (no "verde"): 3 findings PREEXISTENTES, IDENTICOS backup vs dry-run
(mismo set exacto; 016d no introdujo ni elimino ninguno), FUERA de scope de 016d (PII, no secretos):
  - agent_system/templates/gitleaks.config.toml : sk_live_0123456789abcdefXYZ (ejemplo del template)
  - tests/test_classify_publication.py L591 : sk_live_0123456789abcdefXYZ (fixture)
  - tests/test_classify_publication.py L619 : TOKEN=valorsincomillas0123456789abcd (fixture)

COMANDO REAL EXACTO A EJECUTAR (sobre el motor real, tras export safe.bareRepository=all):
  cd C:/Users/***REDACTED***/Proyectos_Python/orquestador_de_agentes
  <FR> --mailmap  scratchpad/FROZEN_callbacks_016d/motor.mailmap \
       --file-info-callback scratchpad/FROZEN_callbacks_016d/file_info_cb.py \
       --message-callback   scratchpad/FROZEN_callbacks_016d/message_cb.py \
       --force
  (FR = C:/Users/***REDACTED***/AppData/Local/Programs/Python/Python312/Scripts/git-filter-repo.exe)

## FILTER-REPO REAL EJECUTADO + POST-OP (2026-07-01, GO local humano)

GO local humano tras GO packet + 3 nits (origin URL persistida en scratchpad/ORIGIN_URL_016d.txt;
presave confirmado FUERA del repo; repetir TODOS los post-checks en el repo real).

filter-repo REAL (callbacks congelados, hashes reverificados == GO packet):
- HEAD_BEFORE f6eba2265e461ce37ad5a155709056237935c28f -> HEAD_AFTER 19cf69105afa33233e2d1d08c22d8cc18f7bf5dd
  (== dry-run #3, determinista). commits --all 795, tags 135. exit 0.
- sample-log REAL IDENTICO al dry-run #3: SKIP_NOMATCH 3493, REDACT_PATH_CHANGED 201,
  SKIP_ALLOWLIST 10, REDACT_COORD_CHANGED 4.

POST-OP:
- origin: filter-repo lo ELIMINO (esperado). RE-ANADIDO local:
  https://github.com/FDL32/orquestador-de-agentes.git (el remoto GitHub sigue con historia VIEJA
  sin redactar -> 016f hace el force-push coordinado).
- artefactos 016d restaurados desde presave (execution_log, work_plan, AUDIT, INVENTARIO, STATE, TURN).
  STATE.md = WOT-2026-016d / IN_PROGRESS (el checkout lo habia revertido a 016h; restaurado).

HALLAZGO POST-OP CRITICO (el dry-run NO podia verlo): tras la reescritura, el scan del repo REAL
mostro PII residual (ruta username sin redactar, p.ej. CHANGELOG L1387 `c:\Users\***REDACTED***`, +docs/prompts/
.opencode/5o-file) alcanzable SOLO via 2 refs `refs/codex/turn-diffs/captures/<ts>/<uuid>/base`.
- Son snapshots de turn-diff del IDE Codex, apuntan a un TREE PRE-reescritura (no commit, no en
  heads/tags). filter-repo reescribe solo refs/heads/* + refs/tags/* -> NO toco estos refs.
- El dry-run (via git clone) NO copia refs/codex/* -> estructuralmente no podia detectarlos. Es la
  MISMA clase de hallazgo que RD5 (namespace de refs extra fuera de la base operativa), pero el
  namespace codex solo existe en el repo real. LECCION: antes de un filter-repo real, enumerar TODOS
  los refs (for-each-ref sin filtro), no solo heads/tags/remotes; el dry-run por clone no los replica.
- DECISION HUMANA (checkpoint): BORRAR los 2 refs codex. Ejecutado: git update-ref -d sobre ambos
  + reflog expire --all + gc --prune=now. Solo quedan heads (3) + tags (135). main history intacto
  (795/135, HEAD 19cf691).

POST-CHECKS DIFERENCIADOS en el repo REAL (no se confio en el dry-run; re-corridos tras el gc):
- METADATA: info@ 0, <BROKEN_ID_EMAIL> 0; emails distintos = SOLO 128408907+FDL32@users.noreply.github.com.
- Taggers de tags anotadas: 0 PII. Mensajes de commit con ruta: 0.
- CONTENIDO: fdl-path (bare `Users\***REDACTED***`) presente SOLO en los 4 fixtures de redaccion
  (test_persistence_redaction, test_redact, test_collect_system_health, test_project_root_resolution);
  0 en CHANGELOG, 5o file, docs, prompts, .opencode y todo lo demas.
- ALLOWLIST de 5: BYTE-IDENTICA al backup (sha256, incl. test_compress_canonical.py).
- <BROKEN_ID_EMAIL>-contenido: metadata=0 PERO presente (x1) en sus 4 test-config -> NO 0-global, fixture vivo.
- GITLEAKS (real, all history): 3 findings, IDENTICOS al backup (dummies preexistentes fuera de scope).
- VALIDATE --json --project-root .: 0 errors / 0 warnings.

SUITE CANONICA (gate history-redaction) - analisis de no-regresion:
- run_pytest_safe --level all @ HEAD 19cf691: 15 failed, 3403 passed, 20 skipped. exit 1.
  + WARNING state-leak: la suite muto work_plan.md/execution_log.md (hazard conocido
    motor-suite-level-all-state-leak) -> restaurados desde presave tras la corrida.
- NO-REGRESION PROBADA: los 15 fallos NO los causa 016d. Evidencia:
  * Los 3 ficheros de test que fallan (test_agent_controller.py, test_manager_review_bridge.py,
    test_review_bridge.py) son BYTE-IDENTICOS al backup (sha256): la redaccion NO los toco.
  * Causa real de TestPreHandoff+TestBuilderBriefExclusion: error literal "Pre-handoff blocked:
    work_plan.md is not committed / uncommitted_work_plan: true". Es el hazard documentado
    motor-testprehandoff-lee-workplan-real: leen el work_plan REAL y fallan si esta sucio
    (mis artefactos 016d aun sin commitear). El COMMIT del work_plan los limpia (patron
    handoff-requiere-commit-colaboracion). NO es la redaccion.
  * TestOpencodeReviewRoute/review_bridge: dependen de estado vivo de bus/decision (assert
    APPROVE vs CHANGES), sensibles a subproceso/bus; pre-existentes, ajenos a la redaccion.
  * Gate REAL de la redaccion (los 6 tests que la redaccion pudo romper): 106 passed / 0 failed
    en el repo real -> la reescritura NO degrado ni fixtures ni el 5o test coordinado.
- CONCLUSION: la suite roja es estado-heredado/no-commit, no regresion de 016d. El commit de
  colaboracion (siguiente paso) debe limpiar TestPreHandoff/BuilderBrief; los review-bridge son
  pre-existentes fuera de scope (candidatos a ticket aparte, como los teardown de 016h/016e).

ARTEFACTOS REDACTADOS (placeholders, antes de git add): el grep estricto de PII (email del dueno,
identidad rota, ruta username en sus 6 variantes + forma slug con guion) da 0 en work_plan/
execution_log/AUDIT/INVENTARIO/STATE/TURN. Placeholders: <OWNER_EMAIL>, <BROKEN_ID_EMAIL>, `***REDACTED***`.
El noreply alias (128408907+FDL32@...) PRESERVADO (no es PII). Los 2 archivos _archive/*016e*.md
con `Users\***REDACTED***` residual estan GITIGNORED (.gitignore:87 _archive/) -> nunca se commitean.

COMMIT DE COLABORACION: 043e17b "WOT-2026-016d: reescritura de historia del motor (redaccion PII)
+ cierre". 6 archivos (STATE/TURN/execution_log/work_plan/AUDIT/INVENTARIO). Hooks de portabilidad
PASARON (encoding guard, history-truncation, claude-settings-portability) tras arreglar el
motor-precommit-hook-ruta-obsoleta (el `python` resolvia a un shim conda roto nsight-compute\
python.bat; se limpio miniconda3/Scripts del PATH y se antepuso Python312 real; guards corridos
directos = exit 0 los 3). Mensaje de commit tambien redactado (amend: quitada una referencia literal
a la identidad rota -> 0 PII en el mensaje). AUTOR/COMMITTER del commit = FDL32 <128408907+FDL32@users.noreply.github.com>
(noreply, NO re-introduce PII). Historia tras el commit: 0 emails PII, distinct = solo noreply.

VERIFICACION post-commit: committear el work_plan LIMPIO los TestPreHandoff+TestBuilderBriefExclusion
(14 passed / 0 failed) -> confirma que su rojez era el hazard work_plan-dirty, no la redaccion.
validate 0/0, tree limpio.

REV1 (Manager mecanico): commit scope LIMPIO (los 2 commits de cierre tocan SOLO
.agent/collaboration/*; sin codigo de produccion). pre-handoff = success. APROBADO.

REV2 FRESH-CONTEXT (G3, subagente sin transcript): **RECHAZADO** (veredicto ACEPTADO por el Builder).
Verifico independiente (pickaxe `git log -S` + git grep en HEAD:main). Casi todo pasa (metadata 0,
taggers 0, mensajes 0, 4 fixtures byte-identicos, 5o test coordinado 6/6, gitleaks solo dummies,
validate 0/0), PERO encontro PII RESIDUAL real fuera de la allowlist -> viola el criterio firmado
"ruta username FUERA de la allowlist = 0". CONFIRMADO por el Builder con evidencia dura (git grep HEAD):

GAP ESTRUCTURAL del callback (el regex de ruta-username NO cubre 3 formas; probado en el artefacto
DURABLE .agent/collaboration/CALLBACK_GAP_016d_test_forms.py -- ejecutable, PII-free con username
generico 'usr', que muestra REDACTED en single-`\`/`/` y MISSED en las 3 formas de abajo):
- DOUBLE-backslash `Users\\<user>` (literales de string Python) -> MISSED (el regex matchea UN `\`).
- no-separator slug `Users<user>...` (ruta con separadores eliminados) -> MISSED.
- dash-slug `--Users-<user>-...` en FUENTE (no solo en el 5o test) -> MISSED (solo se cubrio ese slug
  en test_claude_memory_mirror.py, no en el resto).

Archivos de PRODUCCION/DOC con el username residual (presentes ya en el backup -> el callback los
MISSED, no los introdujo):
- runtime/project_root.py L36 (`Users\\<user>\\proj`, docstring ejemplo), L41 (slug sin separadores).
- scripts/claude_memory_mirror.py L68 (docstring con el slug dash del proyecto).
- prompts/orchestrator_launch_builder.md L229 (doc ejemplo del mangle CTL-2026-007b, slug sin sep).
Son el username real como EJEMPLO ilustrativo en docstrings/docs -> PII segun el criterio 0-fuera-allowlist.

HALLAZGO SECUNDARIO (Rev2, valido): tests/test_classify_publication.py (L312/678/728/976/1015, ruta
`Users\\<user>\\private\\note.txt` en `\\`) es un 6o FIXTURE de logica-de-clasificacion-PII no
documentado. DEBE preservarse (como los otros fixtures) pero NO estaba en ninguna allowlist -> a lo
sumo omision de doc; ademas el `\\` no lo tocaba el regex de todos modos.

DECISION: 016d NO cierra. La correccion exige OTRA reescritura de historia (irreversible, alto
blast-radius) con callback ampliado (cubrir `\\`, no-separator, dash-slug en FUENTE) + allowlist
explicita de test_classify_publication.py (6o fixture) -> debe hacerse en SESION DEDICADA NUEVA, no
como parche incremental sobre este HEAD. El HEAD actual (5a054c8) YA esta parcialmente redactado
(metadata 100% limpia, la mayoria del contenido); la 2a pasada solo debe cubrir las 3 formas faltantes.

NO se ejecuta --mark-ready (no hay entrega aprobada). NO se pushea (016f sigue bloqueado: el motor
sigue sucio por estas 3 formas). Backups intactos (795 @ f6eba22 + stale 799). 016d permanece
IN_PROGRESS con este RECHAZO documentado para el resume.

## TRIPLE REVIEW CONVERGENTE + DECISION DE BASE (2026-07-01)

Tres revisiones INDEPENDIENTES coinciden en CHANGES/RECHAZO:
- Rev1 (Manager mecanico): APROBADO en scope/commit, pero el blocker aparece antes de gates.
- Rev2 (fresh-context G3, subagente sin transcript): RECHAZADO (hallazgo original).
- Manager review (canonico): CHANGES. Escribio .agent/runtime/reviews/decision_WOT-2026-016d.json
  = {"decision":"CHANGES", blockers:[gap de formas de ruta/slug fuera de allowlist; allowlist
  incompleta -> test_classify_publication.py 6o fixture]}. (artefacto gitignored, su BOM no entra
  en historia.) NO ejecuto mark-ready/commit/push.

DECISION DE BASE PARA LA CORRECCION (firmada por el humano 2026-07-01): opcion (a) = partir del
BACKUP 795 @ f6eba22 (scratchpad/motor_backup_795.git). Motivo: una UNICA reescritura limpia con el
callback corregido, sin encadenar una 2a historia sobre el HEAD ya parcialmente redactado.
CONDICION: conservar este execution_log/artefactos de RECHAZO como referencia, y re-aplicar despues
solo los artefactos de colaboracion necesarios (ya PII-free).

RESUME (sesion dedicada nueva, IRREVERSIBLE - mismos gates que esta: backup+dry-run+3 checkpoints):
1. Base = clon del backup 795 @ f6eba22 (NO el HEAD actual e196bae, ya parcialmente redactado).
2. Callback ampliado: cubrir las 3 formas faltantes en TODA la fuente (no solo el 5o test):
   - double-backslash `Users\\<user>`; no-separator `Users<user>`; dash-slug `--Users-<user>-`.
   (El regex actual ya cubre single-`\` y `/`; ver .agent/collaboration/CALLBACK_GAP_016d_test_forms.py
   -- artefacto durable y commiteado con el gap probado.)
3. Allowlist ampliada a 6: los 5 actuales + tests/test_classify_publication.py (fixture de
   clasificacion PII; preservar byte-identico; DOCUMENTARLO en el inventario).
4. Post-check REFORZADO: escanear el username en TODAS sus formas (word-level `grep -i`, no solo
   `Users[/\\]<user>`), y enumerar TODOS los refs (for-each-ref sin filtro; el dry-run por clone no
   replica refs/codex/*/refs/stash -> revisarlos en el repo real tras la reescritura).
5. Rev1 + Rev2 (G3) + Manager review de nuevo antes de cualquier mark-ready. Push sigue en 016f.

## 2a PASADA CORRECTIVA EJECUTADA (2026-07-02)

BASE: backup 795 @ f6eba22 (decision humana firmada opcion a). Callback v2 ampliado con regex
anclada `(?i)(users[/\\+-]*)(<user>)` en file_info_cb.py (ramas _COORD Y else) + message_cb.py;
allowlist=6 (aniadido tests/test_classify_publication.py). Gate de formas (CALLBACK_GAP_016d_test_forms.py
--gate) VERDE: 5/5 REDACTED (single/fwd/`\\`/no-sep/dash-slug) + negativos INTACT (alias publico FDL32,
`users.noreply`, `docs/users/readme` preservados). Anti-sobre-redaccion verificada.

CHECKPOINT HUMANO: 2 Manager reviews independientes -> APROBADO PARA GO (tras resolver B1 arbol sucio,
B2 manifest stale, B3 dry-run no auditable). Evidencia durable del dry-run en C:/tmp (no versionada,
tiene rutas locales -> NO copiar a artefactos).

DECISION DE GRAFT (humano): re-aplicar SOLO los artefactos de colaboracion PII-free como UN commit
fresco sobre la base limpia (no cherry-pick de los 11 commits de la 1a-pasada contaminada).

EJECUCION: filter-repo v2 sobre clon staging del backup (exit 0, 13.4s) -> HEAD 4580889, 795 commits,
135 tags. Post-checks staging VERDES. Reemplazo del motor real via fetch+update-ref atomico (138 refs:
3 heads + 135 tags) + reset --hard + reflog expire + gc --prune=now. NO se uso filter-repo in-place
sobre el real (por eso 0 refs/original, origin PRESERVADO).

POST-CHECKS EN EL REAL (post-gc):
- Metadata: unico email 128408907+FDL32@users.noreply.github.com. Counts 795/135.
- Username ANCLADO (todas las formas), ALL refs Y branches+tags: SOLO los 5 fixtures allowlisted
  (test_classify_publication, test_persistence_redaction, test_redact, test_collect_system_health,
  test_project_root_resolution). 0 fuera de la allowlist. _COORD (test_claude_memory_mirror) = 0 residual.
- 6 fixtures allowlisted BYTE-IDENTICOS al backup (mismo blob sha).
- Refs no-estandar (codex/stash/original) = 0 (el real ya los tenia limpios de la 1a pasada; el
  vector codex del dry-run vivia en el mirror fuente, no en el real).
- gitleaks (config consistente): 3 findings = IDENTICOS a backup/staging (0 delta). Dummies
  pre-existentes (stripe/generic-api-key en gitleaks.config.toml + test_classify_publication.py),
  fuera del scope PII de 016d.
- validate --json: 0/0.

ESTADO: motor real reescrito y limpio. Artefactos de colaboracion PII-free re-aplicados. NO mark-ready
(pendiente NUEVA triple review: Rev1 + Rev2 fresh-context G3 + Manager). NO push (016f gobierna el
force-push coordinado; el remoto GitHub sigue con historia VIEJA).
