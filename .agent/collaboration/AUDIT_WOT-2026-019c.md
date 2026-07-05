# AUDIT - WOT-2026-019c

Ticket: WOT-2026-019c - test flaky en CI shallow clone
(test_loose_pattern_chunks_many_revs, exit 128 de git rev-list --all).
Estado del plan: APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin
  contradiccion: PASO 1 (anadir `gc.auto=0` en `_make_repo`) -> PASO 2
  (verificacion local + documentar el limite CI-only) -> PASO 3 (test de
  regresion determinista + mutation check). Ningun paso pide crear y
  revertir el mismo contenido de forma permanente (el comentado del
  mutation check en PASO 3 es explicitamente temporal y documentado, no
  queda en el commit final).
- TP-02: verificado - cada DoD cita un comando exacto (`pytest -v` del
  archivo completo, `ruff check`/`format --check` con ruta exacta,
  `git config --get gc.auto` con valor esperado `"0"`) o un contrato de
  codigo literal (`_git(repo, "config", "gc.auto", "0")` tras `git init`).
  El criterio CI-only tiene su propio comando verificable
  (`gh run list --workflow "Quality Gates" --limit 1`, campo
  `conclusion: success`), marcado explicitamente PENDIENTE-POST-PUSH con
  su razon (depende del runner remoto).
- TP-03: verificado - Files Likely Touched enumera exactamente 1 archivo
  concreto (`tests/test_check_publication_gate.py`), con la funcion exacta
  a modificar (`_make_repo`) y el test nuevo exacto
  (`test_make_repo_disables_autogc`). Read/inspect only enumera 4 archivos
  concretos (`scripts/check_publication_gate.py`,
  `scripts/classify_publication.py`, `tests/conftest.py`,
  `.github/workflows/quality-gates.yml`,
  `.github/workflows/security-audit.yml`) explicitamente fuera de alcance
  de edicion, sin comodines.
- TP-04: verificado - no aparece lenguaje blando tipo "si procede" en el
  flujo critico. La condicionalidad del diagnostico (por que se descarta
  Opcion A y se elige Opcion B) esta cerrada con evidencia concreta
  (reproduccion local, traceback de 2 runs de CI), no delegada como
  heuristica libre al Builder. El caracter CI-only del cierre esta
  declarado explicitamente como PENDIENTE-POST-PUSH con su razon tecnica,
  no como "si aplica" o ambiguedad sin mecanismo.
- TP-05: verificado - work_plan.md, PLAN_WOT-2026-019c.md y este AUDIT
  describen la misma secuencia (gc.auto=0 en _make_repo + test
  determinista con mutation check + verificacion local + gate CI-only
  PENDIENTE-POST-PUSH), el mismo archivo de Files Likely Touched
  (`tests/test_check_publication_gate.py`), y los mismos 8 criterios de
  aceptacion global. Los Blockers de este AUDIT usan los mismos verbos que
  las restricciones/STOP conditions del PLAN (no tocar workflows, no tocar
  scripts de produccion, no tocar conftest.py).
- TP-06: no aplica como anti-patron (este TP Check usa la forma canonica
  TP-01 a TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional tipo
  "si existe" o "si aplica" en Objetivo, Fases o Criterios de Aceptacion
  Global del work_plan.md decidiendo cuando se activa el fix: la decision
  (Opcion B, siempre, en `_make_repo`) esta cerrada explicitamente para
  todos los tests que usan el helper, sin condicionalidad de alcance
  delegada al Builder.

## Premisa de Fase 0 (verificacion independiente del Manager antes de aprobar)

Confirmado en esta sesion (2026-07-05), la ficha original supone que el
fallo esta en `check_loose_pattern`/depende de la profundidad del checkout
(shallow del padre). Esa premisa queda REFUTADA por evidencia directa:

- `gh run view 28755232843 --log-failed` y
  `gh run view 28692691463 --log-failed`: ambos runs de CI muestran el
  mismo traceback exacto, con el fallo en
  `scripts/classify_publication.py:482` (`_collect_history_blob_paths`,
  dentro de `_git_lines(repo_root, "rev-list", "--all")`), llamado desde
  `check_classify` (`scripts/check_publication_gate.py:89`), que corre
  ANTES que `check_loose_pattern` en la secuencia de `run_gate`
  (linea 146-153). El `cwd` del proceso (visible en el frame de
  `_run_git`) es
  `.../tests/sandbox/test_runtime/session_<pid>/factory/test_loose_patte_<hash>/repo_grande`
  -- el repo fixture ANIDADO propio del test, NO el checkout del runner.
- Reproduccion local: `git clone --depth=1 file:///<motor> <tmp>` +
  `pytest tests/test_check_publication_gate.py` completo desde dentro del
  clon -> `8 passed in 23.60s`, 0 fallos, en 3 corridas. El shallow del
  checkout padre, por si solo, NO reproduce el fallo.
- `_run_git`/`_git_lines` (`scripts/classify_publication.py` linea
  216-238) invocan `git` con `cwd=repo_root` explicito (el repo fixture),
  sin heredar `GIT_DIR`/working-tree del proceso padre;
  `actions/checkout@v5` (log de ambos runs) solo anade `safe.directory`
  para el path del checkout padre, nunca para el repo anidado.
- Ningun workflow (`quality-gates.yml`, `security-audit.yml`) invoca
  `check_publication_gate.py`/`classify_publication.py` sobre el checkout
  real de CI (grep confirmado: 0 matches). `fetch-depth: 0` no tiene
  ningun camino de codigo que pueda tocar el bug real.
- El `stderr` de CI (`error: Could not read <sha>`, `fatal: Failed to
  traverse parents of commit <sha>`) sobre un SHA que el propio
  `rev-list --all` acaba de listar en su stdout es la firma de corrupcion
  transitoria de objetos, consistente con `git gc --auto` en background
  (`gc.autoDetach=true` por defecto en POSIX) disparado por alguno de los
  485 `git commit -q` en bucle, solapandose con las lecturas de historial
  completo inmediatamente posteriores. Sin overrides de `gc.auto` en el
  entorno (`git config --get gc.auto` vacio): aplican los defaults de git
  (umbral 6700 objetos loose).
- `tests/conftest.py::ProjectTmpPathFactory`/fixture `tmp_path` (linea
  34-57, 182-187) confirmado: `tmp_path` cae DENTRO del repo (motor o
  checkout de CI, bajo `tests/sandbox/test_runtime/`), explicando el path
  observado en el log de CI, pero esto no es la causa del fallo (la
  reproduccion local con el mismo mecanismo no reprodujo el error).
- Unico archivo de test con el patron "muchos commits en bucle" (grep de
  `REV_CHUNK_SIZE` + bucle `range(...)` en `tests/`): confirma que el fix
  no necesita replicarse en otro archivo.
- git status --short del arbol de trabajo del motor: vacio (arbol limpio
  antes del bootstrap, tras commitear el archivado de
  execution_log_WOT-2026-019a.md).

## Blockers (para el Manager en review)

- Si `.github/workflows/quality-gates.yml` o
  `.github/workflows/security-audit.yml` aparecen modificados en el diff
  final: BLOCKER critico, invalida la Decision Arquitectonica (Opcion A
  descartada explicitamente por evidencia).
- Si `scripts/check_publication_gate.py`, `scripts/classify_publication.py`
  o `tests/conftest.py` aparecen modificados en el diff final: BLOCKER,
  fuera del alcance declarado (el fix es exclusivamente del fixture de
  test).
- Si `test_make_repo_disables_autogc` NO falla contra el codigo pre-fix
  (mutation check ausente o mal ejecutado, comentando la linea del fix):
  BLOCKER, no hay evidencia de que el test verifique el mecanismo real del
  fix en vez de ser un placebo.
- Si algun test existente de `tests/test_check_publication_gate.py` se
  rompe con el cambio: BLOCKER, el cambio no es tan quirurgico como se
  penso.
- Si `ruff check` o `ruff format --check` fallan sobre
  `tests/test_check_publication_gate.py`: BLOCKER, gate de calidad no
  satisfecho.
- Si la suite canonica (`run_pytest_safe.py`) no queda verde con stamp
  fresco sobre HEAD antes de mark-ready: BLOCKER, el gate de pre-handoff
  no confiara en el resultado.
- Si `execution_log.md` no documenta el mutation check (comentar la linea
  del fix + fallo del test nuevo + restauracion + exito) con salida
  literal de pytest: BLOCKER, evidencia insuficiente.
- Si el ticket se cierra como COMPLETED sin que exista evidencia de un run
  de CI posterior al push (`gh run list --workflow "Quality Gates"
  --limit 1` con `conclusion: success`, o el propio Manager verificandolo
  en la review): BLOCKER -- el criterio PENDIENTE-POST-PUSH es el cierre
  real de este ticket, no un extra opcional.

## Evidencia esperada en execution_log.md

- Diff final (o cita literal) de `_make_repo` en
  `tests/test_check_publication_gate.py` mostrando la linea
  `_git(repo, "config", "gc.auto", "0")` anadida tras `git init`.
- Cita literal de `test_make_repo_disables_autogc` con su asercion sobre
  `git config --get gc.auto`.
- Salida literal de pytest del mutation check: ANTES de comentar el fix
  (verde, incluyendo el test nuevo), DESPUES de comentar la linea (el test
  nuevo FALLA, el resto sigue verde), y tras restaurar (verde de nuevo).
- Salida literal de `pytest tests/test_check_publication_gate.py -v`
  completo (9 tests, no solo el nuevo), confirmando 0 fallos.
- Salida literal de `ruff check`/`ruff format --check` sobre
  `tests/test_check_publication_gate.py`, exit code 0.
- Salida literal (o resumen con exit_code/level/tested_commit_sha) de
  `scripts/run_pytest_safe.py` confirmando level=all, exit_code=0 y
  tested_commit_sha == HEAD tras el commit del fix.
- Commit sha del repo_motor que contiene el fix, citado con
  WOT-2026-019c en el mensaje.
- Confirmacion explicita (diff vacio o "sin cambios") de que ningun
  workflow ni `scripts/check_publication_gate.py`/
  `scripts/classify_publication.py`/`tests/conftest.py` aparece
  modificado.
- Tras el push: salida de `gh run list --workflow "Quality Gates" --limit 1`
  (o equivalente) mostrando el run del commit del fix con
  `conclusion: success`, citada en execution_log.md como evidencia de
  cierre del criterio PENDIENTE-POST-PUSH.
