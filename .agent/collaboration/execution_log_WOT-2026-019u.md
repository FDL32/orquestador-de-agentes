# Execution Log - WOT-2026-019u

Ticket: Eliminar rama muerta de print_motor_checkpoint_guidance en
.agent/motor_checkpoint.py, inalcanzable desde el cierre de WOT-2026-019q.
**Estado:** COMPLETED

## Bitacora

- Plan creado y aprobado por el Manager (2026-07-06). work_plan.md y
  AUDIT_WOT-2026-019u.md creados en `.agent/collaboration/`. Alcance: un
  unico archivo (.agent/motor_checkpoint.py), borrado de 11 lineas en la
  funcion print_motor_checkpoint_guidance, sin adaptacion de tests (grep
  confirma que ninguno depende de la rama muerta).
- Artefactos de WOT-2026-019r (COMPLETED) archivados: execution_log.md ->
  execution_log_WOT-2026-019r.md; STRATEGY_WOT-2026-019r.md y
  AUDIT_WOT-2026-019r.md -> `.agent/collaboration/_archive/plan_audit/`.
- El Orquestador ejecuto `--reset-turn --force` y `--bootstrap-ticket --json`
  (status=bootstrapped, plan_id=WOT-2026-019u): TURN.md/STATE.md regenerados
  y STATE_CHANGED -> IN_PROGRESS emitido al bus. Este log queda en IN_PROGRESS.

### Builder - ejecucion (2026-07-06/07)

- Turno confirmado con `./.venv/Scripts/python.exe .agent/agent_controller.py
  --force` (arbol tenia artefactos de colaboracion heredados del handoff
  019r->019u, no relacionados con el ticket): TURNO ACTUAL: BUILDER, Plan
  WOT-2026-019u, Estado APPROVED, Progreso IN_PROGRESS.

**Fase 1 (verificacion previa):**
- `grep -rn "stale; expected HEAD" .agent scripts bus tests` (sin filtro):
  13 lineas totales, pero filtrando solo codigo fuente
  (`grep -rn "stale; expected HEAD" --include="*.py" .agent scripts bus
  tests`) da EXACTAMENTE 1 hit: `.agent/motor_checkpoint.py:388`. El resto
  de hits sin filtrar son: 1 mencion historica en
  `execution_log_WOT-2026-019q.md:42`, 8 menciones en prosa dentro del
  propio `work_plan.md` de este ticket (citan la cadena como texto, no
  como codigo — patron conocido de falso-positivo por substring, ver
  leccion 019j/019l), 1 mencion en
  `_archive/plan_audit/STRATEGY_WOT-2026-019q.md:13` (documento archivado),
  y 1 match binario en `.agent/__pycache__/motor_checkpoint.cpython-310.pyc`
  (artefacto compilado derivado del propio .py, no fuente independiente).
  0 emisores de codigo vivo distintos al conocido. Criterio de Fase 1
  satisfecho.
- `grep -rln "print_motor_checkpoint_guidance" tests/`: 0 archivos (exit
  code 1 = sin matches). Criterio de Fase 1 satisfecho.

**Fase 2 (borrado):**
- Edicion aplicada en `.agent/motor_checkpoint.py`: eliminado el bloque
  completo `if "stale; expected HEAD" in cp_error: ... return` (el `if`,
  sus dos `print(...)` multi-linea, y el `return`), mas la linea en blanco
  separadora entre esa rama y la siguiente (`if "refusing empty
  closeout"`). Preservado bit-a-bit: la linea inicial de error, el bloque
  `refusing empty closeout` completo (2 prints + return), y el print
  generico final.
- `git diff --stat -- .agent/motor_checkpoint.py`: `1 file changed, 12
  deletions(-)` (11 lineas del bloque logico + 1 linea en blanco
  separadora; 0 lineas anadidas). Ningun otro archivo tocado por esta
  edicion.
- `grep -c "stale; expected HEAD" .agent/motor_checkpoint.py` -> `0`
  (exit code 1 = sin matches). Criterio de Fase 2 satisfecho.
- Funcion resultante verificada por lectura directa (lineas 383-397):
  queda con la linea de error inicial, 1 rama condicional
  (`refusing empty closeout`, intacta) y el print de fallback final —
  exactamente el contrato del DoD.

**Fase 3 (gates):**
1. `./.venv/Scripts/python.exe -m ruff check .agent/motor_checkpoint.py`
   -> `All checks passed!`, **exit code 0**.
2. `PYTHONDONTWRITEBYTECODE=1 ./.venv/Scripts/python.exe
   scripts/run_pytest_safe.py --level all` -> **8 failed, 3489 passed, 47
   skipped** en 226.85s, **exit code != 0**. `last-run.json`: `status:
   "finished"`, `exit_code: 1`, `tested_commit_sha:
   f8541f826ee7fce57334d8e3497ad70bc1e76161` (== HEAD actual, confirmado
   con `git rev-parse HEAD`). Los 8 tests que fallan son todos de
   `tests/test_agent_controller.py`, clases `TestPreHandoff` (7 tests:
   `test_happy_path_commit_tag_clean`,
   `test_happy_path_resets_circuit_breaker`,
   `test_idempotent_no_changes_tag_aligned`,
   `test_no_changes_tag_missing_create_only`,
   `test_no_changes_tag_misaligned_delete_then_recreate`,
   `test_hook_failure_propagates_stderr`, `test_dirty_tree_after_ops`) y
   `TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff`.
   Todos fallan con el mismo mensaje: `[ERROR] Pre-handoff blocked:
   .agent/collaboration/work_plan.md is not committed. uncommitted_work_plan:
   true`.
   - **Diagnostico de causa (sin tocar codigo fuera de scope):** los tests
     mockean unicamente `agent_controller.subprocess.run`
     (`monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)`),
     pero `_handle_pre_handoff` invoca
     `motor_checkpoint.assert_work_plan_committed(...)`, que a su vez
     llama a `scope_gate.get_changed_files(...)`. `scope_gate.py` hace
     `import subprocess` en su PROPIO namespace (linea 12), distinto de
     `agent_controller.subprocess`. Ningun test de los 8 mockea
     `scope_gate.subprocess.run` ni `scope_gate.get_changed_files`
     directamente, por lo que `assert_work_plan_committed` ejecuta una
     llamada git REAL sobre el arbol real del working directory. Ese
     arbol real tiene `.agent/collaboration/work_plan.md` modificado sin
     commit (estado heredado del handoff 019r->019u, visible en
     `git status --porcelain` desde el inicio de este turno, antes de
     tocar ningun codigo), por lo que el guard real detecta
     correctamente "work_plan.md no comiteado" y bloquea con exit 1 --
     resultado esperable del guard real, pero contrario a lo que cada
     test simulaba (arbol limpio via mock parcial).
   - **Prueba de que es preexistente e independiente de este ticket:**
     ejecute `git stash push -- .agent/motor_checkpoint.py` (revirtiendo
     temporalmente SOLO mi edicion, dejando el resto del arbol intacto),
     corri `pytest tests/test_agent_controller.py::TestPreHandoff -x -q`
     sobre ese estado (HEAD limpio `f8541f8`, mi cambio fuera): el primer
     test (`test_happy_path_commit_tag_clean`) fallo con el MISMO mensaje
     exacto (`work_plan.md is not committed`). Confirmado con
     `git stash pop` inmediato despues (recuper mi cambio; verificado con
     `git diff --stat -- .agent/motor_checkpoint.py` -> igual `12
     deletions(-)`, sin perdida). Esto demuestra que el fallo NO depende
     de las 12 lineas borradas en `print_motor_checkpoint_guidance`; es
     una fuga de aislamiento preexistente (Clase B) en los tests de
     `TestPreHandoff`/`TestBuilderBriefExclusion` combinada con el estado
     real (legitimo) del arbol de colaboracion en este momento del
     pipeline.
   - **Decision:** conforme al work_plan ("Si falla: No proceder a
     handoff ni pre-handoff; escalar al Manager con el output literal del
     gate que fallo"), NO se intenta arreglar `assert_work_plan_committed`
     ni el aislamiento de mocks de estos tests -- esta fuera del scope
     autorizado de WOT-2026-019u (unico archivo tocable:
     `.agent/motor_checkpoint.py`, sin tests nuevos ni cambios en
     `agent_controller.py`/`scope_gate.py`). Se escala al Manager.
3. `./.venv/Scripts/python.exe .agent/agent_controller.py --validate --json
   --project-root .` (ejecutado como diagnostico de solo lectura, no como
   cierre): `{"errors": {...todas las claves vacias...}, "warnings": {},
   "total_errors": 0, "total_warnings": 0}`. Gate 3 en verde de forma
   aislada.

**Resultado:** Fases 1 y 2 completas y verificadas (criterios de
aceptacion cumplidos al pie de la letra). Fase 3, gate 1 y gate 3 verdes;
gate 2 (suite completa) rojo por 8 tests preexistentes NO relacionados con
el cambio de este ticket (evidencia de aislamiento arriba). NO se ejecuto
`--pre-handoff` ni `--mark-ready`. NO se hizo commit. El cambio queda en el
working tree para revision del Orquestador/Manager, junto con esta
bitacora.

hipotesis: el bloqueo de estos 8 tests podria desaparecer si el arbol de
colaboracion (work_plan.md) estuviera comiteado en el momento de correr la
suite -- pendiente de confirmar por el Manager si se considera deuda
tecnica aceptable (mock incompleto de `scope_gate.subprocess`) o si se abre
un ticket de barrera (mockear `scope_gate.get_changed_files` directamente
en `TestPreHandoff`/`TestBuilderBriefExclusion` en vez de mocks parciales
de `subprocess`).

### Verificacion del ORQUESTADOR (2026-07-07) -- hipotesis del Builder CONFIRMADA por metodo limpio

La prueba del Builder uso `git stash push` sobre el arbol COMPARTIDO (metodo
contaminado: trampa del poisoned-pyc / mtime del handoff). La re-corri con un
metodo aislado que no toca el arbol de trabajo:

- Cree una worktree efimera `git worktree add --detach <scratchpad>/wt_019u_clean
  f8541f8` (arbol GARANTIZADO limpio, `status --porcelain` vacio).
- Corri los 8 tests (14 metodos) ahi con `-B -p no:cacheprovider`:
  `TestPreHandoff` + `TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff`
  -> **14 passed in 1.09s** (arbol limpio, SIN mi cambio).
- Apliqu mi diff de 019u (`git apply 019u.patch`) sobre esa worktree limpia
  (unico modificado: `.agent/motor_checkpoint.py`) y re-corri los 8:
  -> **14 passed in 0.83s** (arbol limpio, CON mi cambio).
- Elimine la worktree (`git worktree remove --force`); arbol de la dev intacto.

CONCLUSION (verificada por el Orquestador, no heredada del reporte del Builder):
1. Los 8 rojos NO los causa el cambio de 019u: con el fix aplicado sobre arbol
   limpio, los 14 metodos pasan.
2. Los 8 rojos NO son "preexistentes en HEAD f8541f8": en f8541f8 con arbol
   limpio pasan (14 passed). El CI de f8541f8 tampoco muestra TestPreHandoff
   fallando.
3. Los 8 rojos los dispara EL ESTADO DEL PIPELINE: el arbol de la dev tiene
   `work_plan.md`/`execution_log.md` modificados SIN commit (bootstrap del
   ticket). `assert_work_plan_committed` (motor_checkpoint.py:76 -> 
   scope_gate.get_changed_files) hace una llamada git REAL que escapa el mock
   parcial de `TestPreHandoff` (mockea `agent_controller.subprocess`, NO
   `scope_gate.subprocess` -- import propio en scope_gate.py:12) y ve el arbol
   sucio -> guard legitimo bloquea.
4. IMPLICACION PARA EL CIERRE: al commitear el cierre (work_plan.md pasa a
   committed), el arbol quedara limpio y la RE-SUITE sobre el HEAD final de
   cierre volvera verde en estos 8. Esa re-suite (no la corrida con arbol
   sucio) es el criterio de DoD. Patron "re-suite sobre HEAD final".

Follow-up SEPARADO (state-leak de test, NO de este ticket): mockear
`scope_gate.get_changed_files` directamente en `TestPreHandoff`/
`TestBuilderBriefExclusion`, o aislar su cwd, para que no dependan del estado
git real del working directory. Candidato a ficha de backlog del workspace.


Scope override: Falso-positivo de over-captura sobre arbol LIMPIO (patron confirmado x3, handoff 019q/019r). Evidencia: git show --name-only 43a43d2 = solo 9 archivos de 019u (motor_checkpoint.py + artefactos pipeline), 0 de los listados (scope_gate.py/agent_controller.py/AUDIT_019i-r/QUICKSTART/tests son de tickets YA cerrados); git status --porcelain vacio; origin/main..HEAD = 1 solo commit (43a43d2). El gate diffea contra base amplia, no contra mi commit.. Affected files: <REPO_ROOT>/.agent/agent_controller.py, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019i.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019j.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019m.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019q.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019r.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019i.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019j.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019m.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019q.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019r.md, <REPO_ROOT>/.agent/scope_gate.py, <REPO_ROOT>/QUICKSTART.md, <REPO_ROOT>/docs/audit/worktree_topology_surface_inventory.md, <REPO_ROOT>/prompts/orchestrator_session_bootstrap.md, <REPO_ROOT>/scripts/pre_handoff_guard.py, <REPO_ROOT>/scripts/setup_dev_worktree.ps1, <REPO_ROOT>/tests/test_agent_controller.py, <REPO_ROOT>/tests/test_mark_ready_motor_scope.py, <REPO_ROOT>/tests/test_setup_dev_worktree_script.py, <REPO_ROOT>/tests/unit/test_motor_checkpoint.py, <REPO_ROOT>/tests/unit/test_scope_gate_deliverable_aware.py, <REPO_ROOT>/tests/unit/test_scope_gate_topology.py

Manager approved canonical closeout for WOT-2026-019u