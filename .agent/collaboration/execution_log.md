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

Pendiente: Builder implementa PASO 1/2/3 de work_plan.md y documenta aqui
la evidencia (diff, tests, mutation check, salidas de pytest/ruff/suite).
El cierre real de este ticket requiere ademas observar un run verde de
`Quality Gates` en CI tras el push (criterio PENDIENTE-POST-PUSH, ver
work_plan.md).
