# Execution Log - WOT-2026-019c

Ticket: WOT-2026-019c - test flaky en CI shallow clone
(test_loose_pattern_chunks_many_revs, exit 128 de git rev-list --all).
**Estado:** IN_PROGRESS

## Bitacora

- Plan creado y aprobado por el Manager (2026-07-05). Fase 0 (Orquestador)
  diagnostico la premisa de la ficha ANTES de bootstrapear, y la REFUTO
  parcialmente:
  - La ficha suponia que el fallo estaba en `check_loose_pattern`
    (`scripts/check_publication_gate.py` linea 115) y potencialmente
    relacionado con la profundidad del checkout (shallow del padre).
  - `gh run view 28755232843 --log-failed` y
    `gh run view 28692691463 --log-failed` (2 runs de CI reales con el
    mismo fallo, 2026-07-05 y 2026-07-04) muestran el traceback exacto: el
    `git rev-list --all` que falla corre DENTRO de
    `check_classify` -> `build_manifest(scan_history=True)` ->
    `_collect_history_blob_paths` (`scripts/classify_publication.py:482`),
    que corre ANTES que `check_loose_pattern` en la secuencia de
    `run_gate`. El `cwd` del proceso fallido es el repo fixture ANIDADO de
    `_make_repo(tmp_path, "repo_grande")`, no el checkout del runner.
  - Reproduccion local: `git clone --depth=1 file:///<motor> <tmp>` +
    `pytest tests/test_check_publication_gate.py` completo desde dentro
    del clon -> `8 passed in 23.60s`, 0 fallos en 3 corridas. El shallow
    del padre, por si solo, NO reproduce el fallo real de CI.
  - `_run_git`/`_git_lines` corren con `cwd=repo_root` explicito (repo
    fixture), sin heredar working-tree del padre; ningun workflow invoca
    estos scripts sobre el checkout real de CI (grep 0 matches). Por
    tanto Opcion A (`fetch-depth: 0`) queda descartada: no tiene ningun
    camino de codigo que pueda tocar el bug real.
  - El `stderr` de CI (`error: Could not read <sha>`, sobre un SHA que el
    propio `rev-list --all` acaba de listar en su stdout) es la firma de
    corrupcion transitoria de objetos, consistente con una carrera de
    `git gc --auto` en background (default POSIX `gc.autoDetach=true`)
    disparado por alguno de los 485 `git commit -q` en bucle del test.
  - Decision de diseno: Opcion (B) -- anadir
    `_git(repo, "config", "gc.auto", "0")` en `_make_repo`
    (`tests/test_check_publication_gate.py`) inmediatamente tras
    `git init`. Justificacion completa en work_plan.md seccion "Decision
    Arquitectonica".
  - work_plan.md, PLAN_WOT-2026-019c.md y AUDIT_WOT-2026-019c.md creados y
    pendientes de commit. execution_log.md de WOT-2026-019a archivado a
    execution_log_WOT-2026-019a.md (commit 7d36c7f) antes de este
    bootstrap.
- Turno a resetear a BUILDER (`--reset-turn --force`), ticket a
  bootstrapear en el bus (`--bootstrap-ticket --json`).

El cierre real de este ticket requiere ademas observar un run verde de
`Quality Gates` en CI tras el push (criterio PENDIENTE-POST-PUSH, ver
work_plan.md).

## Implementacion (Orquestador toma el fix de 1 linea directamente)

El fix es 1 linea; el Orquestador lo aplico directamente en vez de lanzar Builder
(mismo patron que otros fixes triviales de la sesion). Verificacion del diagnostico
causal del Manager ANTES de aplicar:
- `[VERIFICADO EN CODIGO]` el `git rev-list --all` que falla vive en
  `scripts/classify_publication.py:482` (`_collect_history_blob_paths`), dentro de
  `check_classify`, no en `check_loose_pattern` (refuta la premisa de la ficha).
  Hace `rev-list --all` + `ls-tree -r <commit>` por cada uno de los 485 commits ->
  rafaga de lecturas de objetos justo tras crear 485 commits -> ventana de carrera
  con `git gc --auto` en background (gc.autoDetach=true default POSIX).
- `[VERIFICADO EN CODIGO]` `_make_repo` hacia `git init` sin desactivar gc -> el fix
  (`git config gc.auto 0` tras init) aplica exactamente ahi.

Fix aplicado: `tests/test_check_publication_gate.py::_make_repo` +
`_git(repo, "config", "gc.auto", "0")` tras `git init` (+ comentario WOT-2026-019c).
Test nuevo `test_make_repo_disables_autogc` (verifica `git config --get gc.auto == 0`).

### Gates (verificados por el Orquestador)
- `pytest tests/test_check_publication_gate.py::test_make_repo_disables_autogc` -> 1 passed.
- MUTATION: comentar `gc.auto=0` -> el test nuevo FALLA (1 failed); restaurar -> pasa. Barrera valida.
- `pytest tests/test_check_publication_gate.py` -> 9 passed in 22.30s (8 previos + 1 nuevo).
- `ruff check` -> All checks passed. `ruff format --check` -> already formatted.
- Encoding: 0 caracteres no-ASCII en lineas nuevas. Diff: solo tests/test_check_publication_gate.py (+24).

### Barrera del sintoma real (CI-only, PENDIENTE-POST-PUSH)
La carrera de gc NO reproduce de forma determinista en Windows local. El criterio de cierre
real es observar un run verde de `Quality Gates` en CI tras el push. barrier: run verde de
Quality Gates post-push; reason: la carrera git-gc solo se manifiesta en el runner Linux de CI
bajo carga, no reproducible en local. Estado de pipeline: CLOSED_PENDING_CI.

Pendiente: Review 2 fresh-context + cierre canonico local + push + verificar CI verde.
