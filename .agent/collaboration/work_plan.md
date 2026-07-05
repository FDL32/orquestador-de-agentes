# Work Plan - WOT-2026-019c

## Metadata
- **ID:** WOT-2026-019c
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Aislar `_make_repo` de `tests/test_check_publication_gate.py` con
  `gc.auto=0` para eliminar la condicion de carrera de `git rev-list --all`
  que hizo fallar `test_loose_pattern_chunks_many_revs` en CI (Ubuntu) dos
  veces (2026-07-04 run 28692691463, 2026-07-05 run 28755232843).
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Eliminar el fallo intermitente `subprocess.CalledProcessError: Command
['/usr/bin/git', 'rev-list', '--all'] returned non-zero exit status 128` que
en CI (job `quality-gates (3.11)`, runs `28692691463` y `28755232843`, ambos
con traceback identico) ocurre dentro de `check_classify` ->
`build_manifest(repo, scan_history=True)` ->
`_collect_history_blob_paths(repo_root)` (`scripts/classify_publication.py`
linea 482), invocado desde `run_gate` (`scripts/check_publication_gate.py`
linea 149) sobre el repo git fixture creado por
`_make_repo(tmp_path, "repo_grande")` en
`tests/test_check_publication_gate.py::test_loose_pattern_chunks_many_revs`
(485 commits creados en bucle, `REV_CHUNK_SIZE * 2 + 5`). El `stderr` de CI
(`error: Could not read 8c5ad02d1e80a65e407934c4035d5c17b704bb0b\nfatal:
Failed to traverse parents of commit 8ed1dbf116f0ee3a361da7fedd0096fd5ded8b3f`)
demuestra corrupcion transitoria del object store del propio repo fixture
(un SHA que `rev-list --all` lista en su propio stdout resulta ilegible acto
seguido), consistente con un `git gc --auto` disparado en background
(`gc.autoDetach=true` por defecto en Linux) por alguno de los 485
`git commit -q` en bucle de `_make_repo`/el test, que compacta o poda
objetos mientras `check_classify`/`check_loose_pattern` los leen justo
despues. El fix desactiva `gc.auto` en el repo fixture (`git config gc.auto
0` inmediatamente tras `git init` dentro de `_make_repo`), cerrando la
ventana de carrera sin depender de la profundidad del checkout de CI.

## Decision Arquitectonica

(Evaluadas las 2 opciones de la ficha original mas el diagnostico de Fase 0
del Orquestador, que reproduce el escenario shallow localmente y verifica el
traceback exacto de los 2 runs de CI via `gh run view --log-failed`.)

**Descartada: Opcion (A) -- `fetch-depth: 0` en `quality-gates.yml`.**
Evidencia que la descarta: (1) reproduccion local de un clon `--depth=1`
del propio motor con un `tmp_path` de longitud normal ejecutando
`tests/test_check_publication_gate.py` completo -> `8 passed in 23.60s`,
CERO fallos, incluyendo `test_loose_pattern_chunks_many_revs`; el shallow
del checkout PADRE no afecta al repo fixture. (2) El traceback real de
ambos runs de CI (`gh run view 28755232843/28692691463 --log-failed`)
muestra que el `git rev-list --all` que falla corre con
`cwd=PosixPath('.../tests/sandbox/test_runtime/session_.../factory/
test_loose_patte_.../repo_grande')` -- el repo ANIDADO propio del test, no
el checkout del runner. `_run_git`/`_git_lines`
(`scripts/classify_publication.py` linea 216-238) invocan `git` con
`cwd=repo_root` explicito, sin heredar ningun `GIT_DIR`/working-tree del
proceso padre; `actions/checkout@v5` (log de ambos runs) solo anade
`safe.directory` para el path del checkout, no para el repo anidado. (3)
Ningun workflow del repo (`quality-gates.yml`, `security-audit.yml`) invoca
`check_publication_gate.py`/`classify_publication.py` sobre el checkout real
de CI: solo los tests los ejercitan, siempre sobre repos fixture propios en
`tmp_path`. `fetch-depth: 0` no tiene ningun camino de codigo que pueda
tocar en este bug: seria un cambio cosmetico sin relacion causal
demostrable con el fallo observado, y documentarlo como fix real
enmascararia la causa.

**Elegida: Opcion (B) -- aislar `_make_repo` con `gc.auto=0`.** El fix vive
enteramente en `tests/test_check_publication_gate.py::_make_repo`: anadir
`_git(repo, "config", "gc.auto", "0")` inmediatamente despues de
`_git(repo, "init")` y antes de la primera escritura. Esto desactiva el
disparo automatico de `git gc` (que por defecto se activa a partir de 6700
objetos loose o 50 packs, `gc.auto`/`gc.autoPackLimit`) dentro del repo
fixture, cerrando la ventana de carrera entre los 485 `git commit -q` en
bucle y las 2 lecturas de historial completo que corren justo despues
(`check_classify` y `check_loose_pattern`, ambos via `git rev-list --all`
sobre el mismo repo). Es hermetico (no depende de la profundidad ni de la
ubicacion del checkout padre), ataca el mecanismo real documentado por el
traceback de CI, y no requiere tocar ningun workflow.

## Contexto (Fase 0 del Orquestador, verificado en esta sesion)

- Traceback identico en 2 runs de CI reales (`28692691463` 2026-07-04,
  `28755232843` 2026-07-05), obtenido con
  `gh run view <id> --log-failed`: ambos fallan en
  `scripts/classify_publication.py:482` (`_collect_history_blob_paths`,
  dentro de `_git_lines(repo_root, "rev-list", "--all")`) llamado desde
  `scripts/check_publication_gate.py:89` (`check_classify`), NO en
  `scripts/check_publication_gate.py:115` (`check_loose_pattern`, que la
  ficha original senalaba como sospechoso). `check_classify` corre antes en
  la secuencia de `run_gate` (linea 146-153: `check_name`,
  `check_tree_clean`, `check_classify`, `check_loose_pattern`, ...).
- `cwd` exacto del `git rev-list --all` que falla, tomado del log de CI:
  `/home/runner/work/orquestador-de-agentes/orquestador-de-agentes/tests/sandbox/test_runtime/session_<pid>/factory/test_loose_patte_<hash>/repo_grande`
  -- el repo fixture ANIDADO creado por `_make_repo`, no el checkout del
  runner. `stdout` del proceso fallido SI incluye el SHA que luego resulta
  ilegible (aparece listado, `rev-list` ya lo habia encontrado), y `stderr`
  es exactamente `error: Could not read
  8c5ad02d1e80a65e407934c4035d5c17b704bb0b\nfatal: Failed to traverse
  parents of commit 8ed1dbf116f0ee3a361da7fedd0096fd5ded8b3f`.
- Reproduccion local (Windows) de un clon `--depth=1` del propio motor
  (`git clone --depth=1 file:///<motor> <tmp>`) ejecutando
  `tests/test_check_publication_gate.py` completo desde dentro del clon:
  `8 passed in 23.60s`, incluyendo `test_loose_pattern_chunks_many_revs`.
  CERO reproduccion del fallo en 3 corridas adicionales del mismo escenario.
  Confirma que el shallow del padre, por si solo, no es la causa.
- `tests/conftest.py` (`ProjectTmpPathFactory`, linea 34-57, y fixture
  `tmp_path`, linea 182-187) reemplaza el `tmp_path` estandar de pytest: en
  vez de un directorio temporal del sistema, resuelve a
  `<PROJECT_ROOT>/tests/sandbox/test_runtime/session_<pid>/factory/<hash>`,
  es decir, DENTRO del propio repo (motor o checkout de CI). Este dato
  explica por que el path de CI cae dentro del checkout, pero NO es la
  causa del fallo: la reproduccion local con el mismo mecanismo de
  `tmp_path` (mismo `conftest.py`, mismo clon shallow) no reprodujo el
  error.
- `scripts/check_publication_gate.py` linea 105-124 (`REV_CHUNK_SIZE`,
  `check_loose_pattern`) y `scripts/classify_publication.py` linea 478-494
  (`_collect_history_blob_paths`) confirmados por lectura directa: ambos
  llaman `git rev-list --all` sobre `repo_root` (el argumento recibido, el
  repo fixture), sin ninguna opcion de `git` relacionada con gc o
  concurrencia.
- `_make_repo` (`tests/test_check_publication_gate.py` linea 13-24) hace
  `git init` seguido de `config user.email/user.name` y UN commit baseline;
  `test_loose_pattern_chunks_many_revs` (linea 110-124) anade 485 commits
  mas (`REV_CHUNK_SIZE * 2 + 5` con `REV_CHUNK_SIZE = 100`) en un bucle de
  `git add` + `git commit -q`. Es el UNICO test del archivo que genera un
  volumen de commits capaz de acercarse a un umbral de `gc.auto` (los demas
  tests de `_make_repo` hacen 1-2 commits).
- Sin overrides de `gc.auto`/`gc.autopacklimit`/`gc.autodetach` en la
  config git de este entorno (`git config --get gc.auto` vacio): aplican
  los defaults documentados de git (`gc.auto=6700` objetos loose,
  `gc.autoDetach=true` en POSIX -- dispara `git gc --auto` como proceso
  hijo desacoplado cuyo termino NO se espera por el `git commit`
  invocante), consistente con una carrera que solo se manifiesta bajo el
  timing/IO especifico del runner Ubuntu y no en Windows local.
- Unico archivo de test con el patron de "muchos commits en bucle" (grep
  de `range(` + `REV_CHUNK_SIZE` en `tests/`): confirma que el fix de
  `_make_repo` no necesita replicarse en otro archivo del repo.

## Files Likely Touched

### repo_motor

- `tests/test_check_publication_gate.py` (`_make_repo`: anadir
  `_git(repo, "config", "gc.auto", "0")` tras `_git(repo, "init")`)

## Read/inspect only (Manager-only / no tocar)

- `scripts/check_publication_gate.py` (fuente de `run_gate`/
  `check_classify`/`check_loose_pattern`; solo lectura, el fix no cambia
  produccion)
- `scripts/classify_publication.py` (fuente de `_collect_history_blob_paths`/
  `_run_git`; solo lectura, el fix no cambia produccion)
- `tests/conftest.py` (fuente de `ProjectTmpPathFactory`/`tmp_path`; solo
  lectura, confirma el path anidado pero NO se modifica: cambiar el
  comportamiento global de `tmp_path` excede el blast-radius de este
  ticket y afectaria a toda la suite)
- `.github/workflows/quality-gates.yml` (Opcion A descartada; NO se anade
  `fetch-depth: 0`, ver Decision Arquitectonica)
- `.github/workflows/security-audit.yml` (referencia de paridad citada en
  la ficha original; solo lectura, no se modifica)

## Plan de Implementacion

### PASO 1 (IMPLEMENT) - `tests/test_check_publication_gate.py`, `_make_repo` hermetico

1. En `_make_repo` (linea 13-24), anadir una linea
   `_git(repo, "config", "gc.auto", "0")` inmediatamente despues de
   `_git(repo, "init")` y antes de `_git(repo, "config", "user.email",
   email)`. Esta config se escribe en `<repo>/.git/config` (local al repo
   fixture, nunca afecta al repo motor real ni a otros repos fixture
   creados por otros tests).
2. No modificar la firma de `_make_repo` ni el resto de su cuerpo
   (`user.email`, `user.name`, `README.md`, `add`, `commit -m baseline`
   quedan identicos).
3. No modificar ningun otro test del archivo: los 7 tests existentes que
   usan `_make_repo` (`test_clean_repo_is_listo`,
   `test_copia_folder_blocks`, `test_dirty_tree_blocks`,
   `test_personal_metadata_email_blocks_and_mutation`,
   `test_dirty_sibling_blocks_unidad`,
   `test_loose_pattern_catches_slug_variant`,
   `test_loose_pattern_chunks_many_revs`) heredan el fix automaticamente al
   compartir el mismo helper, sin que su codigo cambie.

Restricciones:
- NO tocar `scripts/check_publication_gate.py` ni
  `scripts/classify_publication.py` (produccion, fuera de alcance: el fix
  es exclusivamente del fixture de test).
- NO tocar `tests/conftest.py` ni el mecanismo de `tmp_path` (blast-radius
  de toda la suite, fuera de alcance de este ticket).
- NO anadir `fetch-depth: 0` a ningun workflow (Opcion A descartada por
  evidencia, ver Decision Arquitectonica).

DoD Paso 1:
- [ ] `_make_repo` invoca `git config gc.auto 0` tras `git init`, antes de
      la primera escritura de contenido.
- [ ] Los 7 tests existentes de `tests/test_check_publication_gate.py`
      que usan `_make_repo` siguen pasando localmente sin cambio de
      aserciones.
- [ ] `ruff check tests/test_check_publication_gate.py` y
      `ruff format --check tests/test_check_publication_gate.py` exit 0.

### PASO 2 (VERIFY) - Verificacion local + documentar el limite de reproduccion

El fallo real (carrera de `git gc --auto` bajo el timing de CI Ubuntu) NO
reprodujo en 3 corridas locales (Windows) ni en el escenario shallow
clonado localmente (ver Contexto): esta barrera es CI-only,
PENDIENTE-POST-PUSH. Razon: la condicion de carrera depende del
scheduler/IO del runner Ubuntu de GitHub Actions, no reproducible de forma
determinista en Windows local con las herramientas disponibles en este
repo (no hay inyeccion de fallos de git ni control del scheduler del SO).

Verificacion local disponible (determinista, no depende de la carrera):

1. `.venv\Scripts\python.exe -m pytest tests/test_check_publication_gate.py -v`
   -> exit 0, los 8 tests pasan (incluye
   `test_loose_pattern_chunks_many_revs`).
2. Inspeccion directa de que el fix aplica: el test nuevo del Paso 3
   (`test_make_repo_disables_autogc`) confirma con una asercion literal
   que el repo creado tiene `gc.auto=0` en su config local.
3. `ruff check tests/test_check_publication_gate.py` y
   `ruff format --check tests/test_check_publication_gate.py` -> exit 0.
4. `.venv\Scripts\python.exe scripts/run_pytest_safe.py` (suite completa,
   stamp fresco sobre HEAD, level=all, exit_code=0) antes de mark-ready.
5. Tras el push: el criterio de cierre real de este ticket es que el
   siguiente run de `Quality Gates` en CI (matrix 3.10 y 3.11) termine en
   verde, confirmado con
   `gh run list --workflow "Quality Gates" --limit 1` mostrando
   `conclusion: success` para el commit del fix. Este check es
   PENDIENTE-POST-PUSH: no puede satisfacerse antes del push porque
   depende del runner remoto.

### PASO 3 (IMPLEMENT) - Test de regresion determinista del propio fix

Anadir a `tests/test_check_publication_gate.py` un test nuevo,
`test_make_repo_disables_autogc`, que:
1. Llama `_make_repo(tmp_path, "repo_gc_check")`.
2. Ejecuta `git config --get gc.auto` con `cwd=repo` (usar
   `subprocess.run` directo capturando stdout, con `check=True`) y afirma
   que el valor devuelto (stripped) es exactamente `"0"`.
3. Es un test determinista (no depende de la carrera de CI): verifica el
   MECANISMO del fix (la config queda escrita), no el sintoma
   (`rev-list --all` fallando), que es CI-only e irreproducible localmente
   segun el Paso 2.

Mutation check (documentar en `execution_log.md`): comentar temporalmente
la linea `_git(repo, "config", "gc.auto", "0")` anadida en el Paso 1,
confirmar que `test_make_repo_disables_autogc` FALLA (la config no esta
seteada, `git config --get gc.auto` devuelve cadena vacia o exit distinto
de 0), restaurar la linea y confirmar que el test vuelve a pasar.

DoD Paso 3:
- [ ] `test_make_repo_disables_autogc` existe, pasa tras el fix, y FALLA
      cuando se comenta la linea del fix (mutation check documentado con
      salida literal de pytest).
- [ ] `.venv\Scripts\python.exe -m pytest tests/test_check_publication_gate.py -v`
      exit 0 con los 9 tests (8 existentes + 1 nuevo).

## Quality Gates

- Builder ejecuta:
  - `.venv\Scripts\python.exe -m pytest tests/test_check_publication_gate.py -v`
    (exit 0, 9 tests incluyendo el nuevo).
  - `ruff check tests/test_check_publication_gate.py` (exit 0).
  - `ruff format --check tests/test_check_publication_gate.py` (exit 0).
  - `.venv\Scripts\python.exe scripts/run_pytest_safe.py` (suite completa,
    stamp fresco sobre HEAD; level=all, exit_code=0).
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - `.venv\Scripts\python.exe .agent\agent_controller.py --validate --json
    --project-root .`
- Gate CI-only, PENDIENTE-POST-PUSH (razon: depende del runner remoto de
  GitHub Actions, no reproducible localmente segun Paso 2):
  - `gh run list --workflow "Quality Gates" --limit 1` tras el push del
    commit del fix debe mostrar `conclusion: success` para ambos legs del
    matrix (3.10 y 3.11).

## STOP conditions

- Si `test_make_repo_disables_autogc` NO falla al comentar la linea del
  fix (mutation check ausente o mal ejecutado): DETENTE, el test es un
  placebo, no hay evidencia de que verifique el mecanismo real.
- Si algun test existente de `tests/test_check_publication_gate.py` se
  rompe con el cambio: DETENTE, escala antes de forzar el test existente a
  pasar cambiando su asercion.
- Si el Builder intenta anadir `fetch-depth: 0` a `quality-gates.yml` o
  cualquier otro cambio de workflow: DETENTE y escala al Manager -- esto
  contradice la Decision Arquitectonica de este plan (Opcion A descartada
  por evidencia).
- Si el Builder intenta modificar `scripts/check_publication_gate.py`,
  `scripts/classify_publication.py` o `tests/conftest.py`: DETENTE y
  escala -- fuera del alcance declarado en Files Likely Touched.

## Non-goals

- NO anadir `fetch-depth: 0` a `.github/workflows/quality-gates.yml`
  (Opcion A descartada por evidencia; ver Decision Arquitectonica).
- NO modificar `scripts/check_publication_gate.py` ni
  `scripts/classify_publication.py` (produccion, fuera de alcance).
- NO modificar `tests/conftest.py` ni el mecanismo de `tmp_path` del
  proyecto (blast-radius de toda la suite).
- NO intentar reproducir de forma determinista la carrera de `git gc
  --auto` en el entorno local de este ticket (confirmado irreproducible en
  Windows tras 3 intentos; el criterio de cierre real es CI-only,
  PENDIENTE-POST-PUSH).
- NO anadir tests nuevos a ningun otro archivo de `tests/` (el patron de
  "muchos commits en bucle" es exclusivo de
  `tests/test_check_publication_gate.py`).

## Riesgos

- Bajo: `gc.auto=0` en el repo fixture podria, en teoria, dejar de
  ejercitar codigo de produccion que dependiera de que `git gc` corriera
  durante el test -- mitigado porque ningun check de
  `check_publication_gate.py`/`classify_publication.py` invoca ni depende
  de `git gc` en ningun punto (confirmado por lectura completa de ambos
  archivos: solo usan `rev-list`, `ls-tree`, `show`, `log`, `status`,
  `grep`).
- Bajo: el fix corrige el MECANISMO documentado (carrera de gc en
  background) pero, al ser CI-only, el cierre depende de observar un run
  verde de CI tras el push -- mitigado con el gate PENDIENTE-POST-PUSH
  explicito en Quality Gates y con el Paso 2 documentando por que no puede
  verificarse antes.
- Bajo: si el fallo real de CI tuviera una causa adicional no cubierta por
  `gc.auto=0` (por ejemplo un limite de recursos del runner en vez de gc),
  el siguiente run de CI seguiria fallando -- mitigado porque el gate
  PENDIENTE-POST-PUSH exige observar el resultado real antes de dar el
  ticket por cerrado; si CI sigue en rojo con el mismo traceback, el
  Manager debe reabrir el diagnostico en vez de asumir cierre.

## Decision sobre REVIEW

Review 2 adversarial fresh-context OBLIGATORIA (la ficha original la exige
por tocar CI/workflow con alto blast-radius). Aunque el diagnostico final
de Fase 0 concluye que el fix NO toca ningun workflow (solo un archivo de
test), se mantiene la Review 2 obligatoria por dos razones: (1) la
naturaleza CI-only del criterio de cierre (el gate real depende de un run
remoto de GitHub Actions, no de un test local) requiere una segunda mirada
fresh-context que confirme que el traceback de CI post-push coincide con
el mecanismo documentado aqui antes de dar el ticket por cerrado; (2) el
propio diagnostico de Fase 0 revirtio la premisa inicial de la ficha (el
fallo no esta en `check_loose_pattern` ni depende de `fetch-depth`), y un
cambio de diagnostico de esta magnitud debe re-verificarse por un segundo
agente sin el contexto de la sesion que lo produjo.

## Criterios de Aceptacion Global (1:1 con el criterio de aceptacion de la ficha)

- [ ] `_make_repo` invoca `git config gc.auto 0` tras `git init`, verificado
      por un test determinista (`test_make_repo_disables_autogc`) que FALLA
      contra el codigo pre-fix (mutation check documentado con salida
      literal de pytest) y PASA tras el fix.
- [ ] Los 8 tests existentes de `tests/test_check_publication_gate.py`
      siguen pasando localmente sin cambio de aserciones.
- [ ] `.github/workflows/quality-gates.yml` y
      `.github/workflows/security-audit.yml` NO aparecen modificados en el
      diff final (Opcion A descartada explicitamente).
- [ ] `scripts/check_publication_gate.py`, `scripts/classify_publication.py`
      y `tests/conftest.py` NO aparecen modificados en el diff final.
- [ ] `ruff check` y `ruff format --check` exit 0 sobre
      `tests/test_check_publication_gate.py`.
- [ ] `.venv\Scripts\python.exe scripts/run_pytest_safe.py` verde (stamp
      fresco sobre HEAD, level=all, exit_code=0).
- [ ] `.venv\Scripts\python.exe .agent\agent_controller.py --validate
      --json --project-root .` exit 0/0 tras el cierre.
- [ ] PENDIENTE-POST-PUSH: el siguiente run de `Quality Gates` en CI tras
      el push del commit del fix termina en `conclusion: success` para
      ambos legs del matrix (3.10, 3.11), confirmado con
      `gh run list --workflow "Quality Gates" --limit 1`.
