# Execution Log - WOT-2026-019s

Ticket: Idempotencia de venv en scripts/setup_dev_worktree.ps1
(Step-CreateVenv salta uv sync cuando .venv\Scripts\python.exe ya existe,
aunque las deps esten incompletas o desincronizadas).
**Estado:** COMPLETED

## Bitacora

- Fase 0 (Orquestador): premisa CONFIRMADA por lectura de codigo real.
  `Step-CreateVenv` (setup_dev_worktree.ps1:175-199) mira SOLO si existe
  `.venv\Scripts\python.exe`; si existe entra en la rama else e imprime
  "idempotente, sin cambios" saltando `uv sync` por completo. Un venv con
  python.exe pero deps faltantes queda incompleto y el script reporta exito.
  Test scaffold existente `tests/test_setup_dev_worktree_script.py` con
  pytestmark skipif(win32) a nivel de modulo (leccion 019m) y un
  `_FAKE_UV_BAT` que fakea uv venv/uv sync.
- Plan creado y aprobado por el Manager (2026-07-07). Enfoque elegido:
  Opcion A -- correr `uv sync` INCONDICIONALMENTE (fuera del `if -not
  Test-Path`), preservando el `uv venv` condicional. `uv sync` es
  idempotente por diseno. Opcion B (deteccion heuristica de deps
  faltantes) descartada por superficie extra y fragilidad con el fake
  uv.bat. Files Likely Touched: scripts/setup_dev_worktree.ps1 +
  tests/test_setup_dev_worktree_script.py.
- Mecanismo de la barrera: extender el fake uv.bat para que la rama sync
  registre cada invocacion en un marcador legible desde Python; test nuevo
  que afirma 1 registro tras la 1a corrida y 2 tras la 2a (venv ya existe).
  Sin fix la 2a corrida no invoca sync (queda en 1 = FAIL); con fix sube a
  2 (PASS). Hereda skipif(win32) de modulo; usa str(worktree_path).
- Artefactos de WOT-2026-019v (COMPLETED) archivados:
  execution_log.md -> execution_log_WOT-2026-019v.md.
- El Orquestador ejecuto `--bootstrap-ticket` (plan_id=WOT-2026-019s):
  STATE.md a ACTIVE_TICKET=WOT-2026-019s / STATUS=IN_PROGRESS y
  STATE_CHANGED -> IN_PROGRESS emitido al bus. Este log queda en IN_PROGRESS.

## Fase 1 (Builder): FAIL-sin-fix confirmado

- Extendido `tests/test_setup_dev_worktree_script.py`: nueva constante
  `_FAKE_UV_BAT_WITH_SYNC_LOG` (variante local, NO se toco el
  `_FAKE_UV_BAT` compartido por los 7 tests preexistentes) cuya rama
  `"%1"=="sync"` hace `echo sync >> "%CD%\.uv_sync_calls.log"` antes de
  `exit /b 0`. `_fake_uv_dir` gano un parametro opcional `script=_FAKE_UV_BAT`
  (default identico al comportamiento previo) para poder inyectar la
  variante sin afectar las llamadas existentes.
- Test nuevo `test_second_run_resyncs_existing_venv` (fixture propio con
  `tmp_path`, no reutiliza el fixture `fixture_repo` compartido): corre el
  script 2 veces sobre el mismo repo fixture y lee
  `<worktree>/.uv_sync_calls.log`.
- Corrida contra el script SIN modificar (estado pre-Fase-2, HEAD actual):

  Comando:
  `PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest tests/test_setup_dev_worktree_script.py::test_second_run_resyncs_existing_venv -p no:cacheprovider -v`

  Resultado literal (FAIL esperado, en el assert de la 2a corrida, no en
  fixture/sintaxis):
  ```
  >           assert len(second_lines) == 2, (
                  "uv sync must be invoked again on the second run even though "
                  "python.exe already exists (Step-CreateVenv must not skip "
                  f"dependency sync); log contents={second_lines!r}"
              )
  E           AssertionError: uv sync must be invoked again on the second run even though python.exe already exists (Step-CreateVenv must not skip dependency sync); log contents=['sync ']
  E           assert 1 == 2
  E            +  where 1 = len(['sync '])

  tests\test_setup_dev_worktree_script.py:402: AssertionError
  =========================== short test summary info ===========================
  FAILED tests/test_setup_dev_worktree_script.py::test_second_run_resyncs_existing_venv
  ============================== 1 failed in 1.19s ==============================
  ```
  Confirma: 1a corrida deja el log en 1 linea (correcto, esperado por el
  test); 2a corrida NO invoca `uv sync` (Step-CreateVenv entra en la rama
  `else` y se salta `uv`), log se queda en 1 -> falla exactamente en el
  assert de "2 lineas tras la segunda corrida", criterio de aceptacion de
  la Fase 1 cumplido.

## Fase 2 (Builder): fix aplicado a Step-CreateVenv

- `scripts/setup_dev_worktree.ps1`, funcion `Step-CreateVenv` (antes
  lineas 175-199): se saco la invocacion de `uv sync` (y su chequeo de
  `$LASTEXITCODE`) del bloque `if (-not (Test-Path -LiteralPath
  $venvPython))`. Ese bloque ahora envuelve UNICAMENTE `uv venv` y su
  chequeo de exit code (creacion del venv sigue condicional). `uv sync`
  pasa a un segundo bloque `if ($PSCmdlet.ShouldProcess(...))`
  incondicional a la rama del venv, con su propio `Push-Location
  $script:WorktreePath` / `finally { Pop-Location }`, de modo que corre
  siempre (venv recien creado o preexistente) y respeta `-WhatIf` (bajo
  `-WhatIf` ningun `ShouldProcess` devuelve true, ni `uv venv` ni `uv
  sync` se invocan; consistente con `test_whatif_creation_mutates_nothing`).
- Mensajes `Write-Host` ajustados para no mentir: la rama "ya existe" ya
  no dice "idempotente, sin cambios" (ahora dice "se resincronizan
  dependencias"); tras `uv sync` en la rama de venv preexistente se anade
  un `Write-Host` "Dependencias del venv resincronizadas con uv sync."
  (solo cuando `$venvJustCreated` es false, para no duplicar el mensaje
  cuando el venv se acaba de crear).
- Docstring `.DESCRIPTION` (paso 3, antes lineas 21-23) actualizada: ahora
  describe que la creacion del venv sigue condicional pero `uv sync` corre
  siempre a continuacion, con la justificacion de idempotencia por diseno.
- `git diff --stat -- scripts/setup_dev_worktree.ps1`: ver seccion de
  Gates mas abajo para el resumen literal de lineas. Ningun otro Step
  (Step-DetachPrincipal, Step-CreateWorktree,
  Test-WorktreeHasUncommittedChanges, Invoke-RemoveWorktree) fue tocado.

## Fase 3 (Builder): PASS-con-fix y suite completa del script

- Re-ejecucion de `test_second_run_resyncs_existing_venv` contra el
  script ya corregido:

  Comando:
  `PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest tests/test_setup_dev_worktree_script.py::test_second_run_resyncs_existing_venv -p no:cacheprovider -v`

  Resultado literal (PASS):
  ```
  tests/test_setup_dev_worktree_script.py::test_second_run_resyncs_existing_venv PASSED [100%]

  ============================== 1 passed in 1.18s ==============================
  ```
  Confirma: 1a corrida deja el log de sync en 1 linea, 2a corrida (venv y
  python.exe ya existentes) lo sube a 2 -> Step-CreateVenv invoca `uv
  sync` en ambas corridas tras el fix.

- Suite completa del modulo:

  Comando:
  `PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest tests/test_setup_dev_worktree_script.py -p no:cacheprovider -v`

  Resultado literal:
  ```
  tests/test_setup_dev_worktree_script.py::test_creation_detaches_principal_and_adds_worktree_with_venv PASSED [ 12%]
  tests/test_setup_dev_worktree_script.py::test_creation_fails_closed_when_principal_is_dirty PASSED [ 25%]
  tests/test_setup_dev_worktree_script.py::test_creation_is_idempotent_on_second_run PASSED [ 37%]
  tests/test_setup_dev_worktree_script.py::test_whatif_creation_mutates_nothing PASSED [ 50%]
  tests/test_setup_dev_worktree_script.py::test_remove_cleans_worktree_and_reattaches_main PASSED [ 62%]
  tests/test_setup_dev_worktree_script.py::test_remove_with_uncommitted_changes_fails_closed PASSED [ 75%]
  tests/test_setup_dev_worktree_script.py::test_regression_add_without_detach_first_fails PASSED [ 87%]
  tests/test_setup_dev_worktree_script.py::test_second_run_resyncs_existing_venv PASSED [100%]

  ============================== 8 passed in 6.26s ==============================
  ```
  8 passed / 0 failed: los 7 tests preexistentes (ninguno cambio de texto
  esperado; `test_creation_is_idempotent_on_second_run` sigue pasando
  porque su assert de "idempotente" en stdout+stderr se refiere a los
  pasos de detach/worktree, que el fix no toco) + el nuevo, todos verdes.

## Fase 4 (Builder): gates de calidad

- `git diff --stat -- scripts/setup_dev_worktree.ps1 tests/test_setup_dev_worktree_script.py`:
  ```
   scripts/setup_dev_worktree.ps1          | 42 +++++++++++++----
   tests/test_setup_dev_worktree_script.py | 84 ++++++++++++++++++++++++++++++++-
   2 files changed, 116 insertions(+), 10 deletions(-)
  ```
  (el conteo de tests/test_setup_dev_worktree_script.py incluye el ajuste
  de `ruff format`, ver abajo).

- `.venv/Scripts/python.exe -m ruff check tests/test_setup_dev_worktree_script.py`:
  ```
  All checks passed!
  ```

- `.venv/Scripts/python.exe -m ruff format --check tests/test_setup_dev_worktree_script.py`
  (1a corrida, ANTES de aplicar el formato): fallo con
  `Would reformat: tests\test_setup_dev_worktree_script.py` / `1 file would be reformatted`.
  Siguiendo el "Si falla" de la Fase 4 del plan (no editar el formato a
  mano), se corrio `.venv/Scripts/python.exe -m ruff format
  tests/test_setup_dev_worktree_script.py` (`1 file reformatted`) y se
  re-verifico:
  ```
  1 file already formatted
  ```
  Tras el reformateo se re-corrio la suite completa del modulo para
  confirmar que el auto-format no rompio nada: 8 passed / 0 failed (mismo
  resultado que en Fase 3).

- Gate de sintaxis PowerShell: no existe un gate/test generico de
  sintaxis AST que cubra `scripts/setup_dev_worktree.ps1`
  (`tests/test_launcher_ps1_syntax.py` y
  `tests/unit/test_launcher_powershell_syntax.py` son especificos de
  `scripts/launch_agent_terminals.ps1`, no lo mencionan). Consistente con
  el work_plan/AUDIT: "el gate funcional del .ps1 es su propia suite de
  tests (tests/test_setup_dev_worktree_script.py), no ruff ni un linter
  de PowerShell". Como verificacion adicional (no exigida por el plan) se
  parseo el script con el mismo parser AST real de PowerShell que usan
  esos tests:
  ```
  {"errors":[],"error_count":0}
  ```
  0 errores de sintaxis.

- `.venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .`:
  ```
  {
    "errors": {
      "work_plan.md": [],
      "execution_log.md": [],
      "notifications.md": [],
      "consistency": [],
      "TURN.md": [],
      "host_project_prefix": [],
      "git_presence": []
    },
    "warnings": {},
    "total_errors": 0,
    "total_warnings": 0
  }
  ```
  0 errores / 0 warnings.

- Encoding: ambos archivos verificados como UTF-8 valido. 0 caracteres
  no-ASCII en `scripts/setup_dev_worktree.ps1`. En
  `tests/test_setup_dev_worktree_script.py` hay exactamente 1 caracter
  no-ASCII (`—`, U+2014) en el docstring de modulo preexistente (fuera de
  mi diff, confirmado con `git diff | grep` -- no aparece en las lineas
  anadidas); ninguna linea `+` del diff combinado de ambos archivos
  contiene comillas curvas ni guiones em/en (verificado
  programaticamente sobre el diff completo).

- No se ejecuto `scripts/run_pytest_safe.py --level all` (el Builder no
  corre la suite canonica completa; la corre el Orquestador sobre el HEAD
  final tras el commit, segun instruccion explicita del ticket).

- `git status --porcelain` final confirma que solo se tocaron los 2
  archivos de scope (`scripts/setup_dev_worktree.ps1`,
  `tests/test_setup_dev_worktree_script.py`) mas los artefactos de
  colaboracion ya modificados por el bootstrap del Orquestador
  (STATE.md, work_plan.md, execution_log.md/AUDIT_WOT-2026-019s.md,
  renombre de execution_log_WOT-2026-019v.md); `.agent/motor_checkpoint.py`,
  `.agent/scope_gate.py` y `.agent/agent_controller.py` no aparecen
  modificados (bit-a-bit identicos a HEAD).

**Estado:** READY_FOR_REVIEW (pendiente builder-self-audit).


Scope override: Falso scope-violation por over-captura de arbol limpio (patron confirmado x3): origin/main..HEAD = commits 019v + 019s de esta sesion batch; el HEAD 5dcca44 SI contiene el FLT scripts/setup_dev_worktree.ps1 + tests/test_setup_dev_worktree_script.py y no contiene archivos ajenos fuera del batch. git status --porcelain vacio.. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019j.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019m.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019q.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019r.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019u.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019j.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019m.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019q.md, <REPO_ROOT>/.agent/collaboration/STRATEGY_WOT-2026-019r.md, <REPO_ROOT>/.agent/motor_checkpoint.py, <REPO_ROOT>/QUICKSTART.md, <REPO_ROOT>/docs/audit/worktree_topology_surface_inventory.md, <REPO_ROOT>/prompts/orchestrator_session_bootstrap.md, <REPO_ROOT>/tests/test_agent_controller.py, <REPO_ROOT>/tests/test_mark_ready_motor_scope.py, <REPO_ROOT>/tests/unit/test_motor_checkpoint.py

Manager approved canonical closeout for WOT-2026-019s