# Execution Log - WOT-2026-019v

Ticket: Cerrar el escape de mock en TestPreHandoff/TestBuilderBriefExclusion
que ejecuta git real cuando work_plan.md esta sucio (state-leak de
aislamiento de tests).
**Estado:** COMPLETED

## Bitacora

- Fase 0 (Orquestador): reproduccion empirica del leak. Con
  `.agent/collaboration/work_plan.md` limpio los 2 grupos de test dan
  17 passed; ensuciando work_plan.md (append no commiteado) dan 8 failed /
  9 passed con el mensaje literal `[ERROR] Pre-handoff blocked:
  .agent/collaboration/work_plan.md is not committed.`; restaurar el archivo
  vuelve a 17 passed. Premisa CONFIRMADA (no era premisa falsa).
- Plan creado y aprobado por el Manager (2026-07-07). work_plan.md creado en
  `.agent/collaboration/`. Causa raiz refinada por el Manager: el default
  `run_fn=subprocess.run` de `scope_gate.get_changed_files`
  (`.agent/scope_gate.py:443`) se congela en import-time y no vuelve a mirar
  `subprocess.run` en cada llamada, por lo que
  `monkeypatch.setattr(agent_controller.subprocess, "run", ...)` no lo
  afecta y `assert_work_plan_committed` ejecuta git REAL. Enfoque elegido:
  Opcion A (monkeypatch de `motor_checkpoint.scope_gate.get_changed_files`
  por test), consistente con
  `tests/unit/test_motor_checkpoint.py::test_delegates_to_scope_gate_not_new_git_parser`.
  Files Likely Touched: solo `tests/test_agent_controller.py` (test-only; el
  codigo de produccion queda bit-a-bit identico, el guard 009g no se relaja).
- Artefactos de WOT-2026-019u (COMPLETED) archivados:
  execution_log.md -> execution_log_WOT-2026-019u.md.
- El Orquestador ejecuto `--bootstrap-ticket` (status=bootstrapped,
  plan_id=WOT-2026-019v): STATE.md regenerado a ACTIVE_TICKET=WOT-2026-019v /
  STATUS=IN_PROGRESS y STATE_CHANGED -> IN_PROGRESS emitido al bus. Este log
  queda en IN_PROGRESS.
- Builder ejecuto el Plan de Implementacion (Fases 1-4) sobre
  `tests/test_agent_controller.py` (unico archivo tocado, Opcion A del
  Manager):
  - Fase 1 (verificacion sin modificar): confirmado por lectura de codigo
    que `motor_checkpoint.assert_work_plan_committed`
    (`.agent/motor_checkpoint.py:90-93`) llama a
    `scope_gate.get_changed_files` sin pasar `run_fn`.
  - Fase 2: en `TestPreHandoff._setup_basic_mocks`, anadida la linea
    `monkeypatch.setattr(motor_checkpoint.scope_gate, "get_changed_files",
    lambda *, project_root, motor_root, run_fn=None: changed_files)`
    inmediatamente despues del monkeypatch existente de
    `agent_controller.get_changed_files`, usando el mismo `changed_files`.
  - Fase 3: en
    `TestBuilderBriefExclusion.test_builder_brief_does_not_block_pre_handoff`,
    anadido el mismo patron con `{brief_file}` inmediatamente despues del
    monkeypatch existente de `agent_controller.get_changed_files`.
  - Import: anadido `import motor_checkpoint  # noqa: E402` justo despues de
    `import agent_controller  # noqa: E402` (no existia antes; verificado
    con grep antes de anadir). Resuelve via el mismo `sys.path.insert(0,
    str(agent_dir))` que ya usa `agent_controller`.
  - `git diff --stat -- tests/test_agent_controller.py`: `1 file changed,
    22 insertions(+)` -- solo lineas anadidas, ninguna eliminada ni
    reordenada, tal como exige el criterio de aceptacion de Fase 2/3.
  - Demostracion FAIL-sin-fix (reconfirmada empiricamente con
    `git stash push --keep-index -- tests/test_agent_controller.py` para
    revertir temporalmente el archivo de test a HEAD sin perder el fix, y
    `.agent/collaboration/work_plan.md` ensuciado via backup/append, NUNCA
    `git checkout --` sobre el work_plan.md APPROVED): comando
    `PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest
    tests/test_agent_controller.py::TestPreHandoff
    tests/test_agent_controller.py::TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff
    -p no:cacheprovider -q` dio **8 failed, 6 passed**, con el mensaje
    literal `[ERROR] Pre-handoff blocked:
    .agent/collaboration/work_plan.md is not committed.` en los 8 casos
    (identico al de Fase 0). `git stash pop` reaplico el fix
    inmediatamente despues; `git diff --stat` confirmo el mismo `22
    insertions(+)` que antes del stash (fix intacto).
  - Demostracion PASS-con-fix bajo arbol sucio: mismo comando pytest con
    el fix aplicado y `.agent/collaboration/work_plan.md` ensuciado
    (append `\n# leak-repro\n` sobre una copia de respaldo del work_plan
    APPROVED) dio **14 passed, 0 failed**. Restaurado el work_plan.md
    desde el backup (`cp` + `diff` para confirmar identidad byte a byte),
    NUNCA con `git checkout --`.
  - No-regresion con el arbol en su estado modificado-esperado (work_plan
    APPROVED, sin commitear): `PYTHONDONTWRITEBYTECODE=1
    .venv/Scripts/python.exe -m pytest
    tests/test_agent_controller.py::TestPreHandoff
    tests/test_agent_controller.py::TestBuilderBriefExclusion -p
    no:cacheprovider -q` dio **17 passed** (los 14 del ticket + 3 mas de
    `TestBuilderBriefExclusion` que ya pasaban y no forman parte del
    ticket).
  - Gates: `ruff check tests/test_agent_controller.py` ->
    `All checks passed!`; `ruff format --check
    tests/test_agent_controller.py` -> `1 file already formatted`;
    `.agent/agent_controller.py --validate --json --project-root .` ->
    `total_errors: 0, total_warnings: {}` (warnings vacio).
  - Encoding: verificado que las 22 lineas anadidas por el diff son
    ASCII-limpio (0 caracteres no-ASCII en `git diff | grep '^+'`); el
    archivo ya tenia 14 caracteres no-ASCII preexistentes fuera de scope
    (flechas `→` y em-dash `—` en docstrings de otros tests, no
    tocados por este ticket).
  - Codigo de produccion: `.agent/motor_checkpoint.py`,
    `.agent/scope_gate.py` y `.agent/agent_controller.py` no aparecen en
    `git diff --name-only` (bit-a-bit identicos a HEAD, confirmado).
  - Por instruccion explicita del Orquestador para este ticket, el
    Builder NO ejecuto `scripts/run_pytest_safe.py --level all` (la
    corre el Orquestador sobre el HEAD final tras el commit); solo se
    entregan aqui los gates focal + ruff + validate.
  - Entrega: sin commit. `tests/test_agent_controller.py` queda
    modificado en disco (staged/unstaged segun decida el Orquestador);
    STATE.md/work_plan.md en su estado de runtime bootstrapped tal como
    los dejo el Orquestador en Fase 0.


Scope override: Falso scope-violation por over-captura de arbol limpio (patron confirmado x3): origin/main..HEAD = solo el commit 3a1b245 de 019v, que SI contiene el FLT tests/test_agent_controller.py y NO contiene ninguno de los archivos ajenos listados (son de tickets 019j/019m/019q/019r/019u ya en origin/main). git status --porcelain vacio.. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019j.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019m.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019q.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019r.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019u.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019j.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019m.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019q.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019r.md, <REPO_ROOT>/.agent/motor_checkpoint.py, <REPO_ROOT>/QUICKSTART.md, <REPO_ROOT>/docs/audit/worktree_topology_surface_inventory.md, <REPO_ROOT>/prompts/orchestrator_session_bootstrap.md, <REPO_ROOT>/scripts/setup_dev_worktree.ps1, <REPO_ROOT>/tests/test_mark_ready_motor_scope.py, <REPO_ROOT>/tests/test_setup_dev_worktree_script.py, <REPO_ROOT>/tests/unit/test_motor_checkpoint.py

Manager approved canonical closeout for WOT-2026-019v