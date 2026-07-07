# Audit - WOT-2026-019s

## Metadata
- **ID:** WOT-2026-019s
- **deliverable_type:** code
- **delivery_authority:** repo_motor
- **Fecha:** 2026-07-07

## TP Check

- TP-01: verificado - no aplica; las 4 fases son secuenciales sin
  instrucciones incompatibles sobre el mismo recurso. Fase 1 solo
  modifica el fake uv.bat/test (registro de invocaciones) y confirma el
  estado FAIL-sin-fix sin tocar el script de produccion; Fase 2 modifica
  unicamente Step-CreateVenv y la docstring del .ps1; Fase 3 solo ejecuta
  y verifica (no modifica produccion, y solo ajusta el test si hiciera
  falta un cambio de texto ya anticipado); Fase 4 solo ejecuta comandos
  de gates. Ninguna fase pide crear y borrar el mismo artefacto, ni
  operaciones opuestas sobre scripts/setup_dev_worktree.ps1 o
  tests/test_setup_dev_worktree_script.py en el mismo paso.
- TP-02: verificado - cada fase tiene un criterio de aceptacion con
  comando o assert literal: Fase 1 exige que el test nuevo falle
  exactamente en el assert de "2 lineas tras la segunda corrida" contra
  el script SIN modificar; Fase 2 exige git diff -- scripts/setup_dev_worktree.ps1
  localizado en Step-CreateVenv y en .DESCRIPTION; Fase 3 exige
  "8 passed / 0 failed" (o "8 skipped" fuera de Windows) para
  tests/test_setup_dev_worktree_script.py; Fase 4 exige exit code 0 de
  ruff check, ruff format --check, la suite completa verde con
  tested_commit_sha igual al HEAD, y --validate --json con errors: 0. No
  aparece "observable", "correcto" ni "estable" sin una prueba literal
  que lo verifique.
- TP-03: verificado - la seccion Files Likely Touched del work_plan
  enumera exactamente 2 archivos concretos (scripts/setup_dev_worktree.ps1,
  tests/test_setup_dev_worktree_script.py); no hay comodines ni "otros
  archivos si hace falta". El plan tambien enumera, dentro de la Fase 3,
  la lista cerrada de los 7 tests preexistentes por nombre exacto que
  deben seguir en verde, sin dejar la superficie de regresion implicita.
- TP-04: verificado - no aparecen expresiones "si procede",
  "opcionalmente", "preferiblemente" ni "stale" sin definir criterio. El
  plan usa formulaciones cerradas: "sacar la llamada a uv sync ... del
  bloque if", "el bloque if sigue envolviendo unicamente uv venv", y fija
  el mecanismo exacto del marcador de invocaciones (leible via
  Path.read_text() o conteo de archivos) en vez de dejarlo a
  interpretacion libre; el unico punto delegado explicitamente al Builder
  (el formato concreto del marcador: log con >>, contador, o archivo por
  invocacion) se declara como tal en la seccion "Mecanismo de la barrera",
  no como ambiguedad no reconocida.
- TP-05: verificado - este AUDIT usa los mismos archivos, mecanismo de
  barrera, fases y criterios que el work_plan.md: mismo listado de
  Files Likely Touched, mismo mecanismo de registro de invocaciones de
  uv sync via fake uv.bat, mismos 7 tests preexistentes citados por
  nombre, mismos 4 comandos de gates de la Fase 4 (ruff check, ruff
  format --check, run_pytest_safe --level all, --validate --json). No
  introduce ninguna condicion adicional no presente en el plan.

## Blockers Verificados Pre-Aprobacion

- Lectura completa de Step-CreateVenv en scripts/setup_dev_worktree.ps1
  (lineas 175-199): confirma que el bloque if (-not (Test-Path
  -LiteralPath $venvPython)) envuelve tanto uv venv como uv sync, y
  que la rama else no ejecuta ningun comando de uv, solo un Write-Host.
  Root cause confirmada por lectura directa, no por inferencia.
- Lectura completa de tests/test_setup_dev_worktree_script.py (lineas
  1-329): confirma que pytestmark = pytest.mark.skipif(sys.platform !=
  "win32", ...) ya existe a nivel de modulo (lineas 38-41), que
  _FAKE_UV_BAT (lineas 48-58) responde a "sync" con exit /b 0 sin
  registrar la invocacion, y que los 7 tests existentes
  (test_creation_detaches_principal_and_adds_worktree_with_venv,
  test_creation_fails_closed_when_principal_is_dirty,
  test_creation_is_idempotent_on_second_run,
  test_whatif_creation_mutates_nothing,
  test_remove_cleans_worktree_and_reattaches_main,
  test_remove_with_uncommitted_changes_fails_closed,
  test_regression_add_without_detach_first_fails) usan el patron
  str(worktree_path) (no el substring bare) desde la correccion de la
  leccion WOT-2026-019q (comentario en lineas 271-276).
- Confirmado que scripts/setup_dev_worktree.ps1 es el unico archivo
  PowerShell tocado y que ruff no aplica sobre el (solo sobre
  tests/test_setup_dev_worktree_script.py, que es Python); el gate
  funcional del .ps1 es su propia suite de tests, no un linter de
  PowerShell.
- Confirmado que este ticket no toca assert_work_plan_committed,
  scope_gate.get_changed_files ni _handle_pre_handoff
  (superficie exclusiva del ticket anterior, WOT-2026-019v, ya cerrado);
  0 solapamiento de archivos entre 019s y 019v.

## Criterios que el Manager verificara en el Review

1. git diff -- scripts/setup_dev_worktree.ps1 entre el commit base y el
   commit de entrega muestra el cambio localizado en Step-CreateVenv
   (uv sync sacado del bloque if, creacion del venv sigue condicional) y
   en el bloque .DESCRIPTION (paso 3 actualizado); ningun otro Step
   (Step-DetachPrincipal, Step-CreateWorktree,
   Test-WorktreeHasUncommittedChanges, Invoke-RemoveWorktree) aparece
   modificado.
2. git diff -- tests/test_setup_dev_worktree_script.py muestra el fake
   uv.bat extendido con registro de invocaciones de uv sync y un test
   nuevo que demuestra la barrera; los 7 tests preexistentes no cambian
   de comportamiento salvo, como mucho, el texto exacto de un assert que
   dependa literalmente del mensaje de Write-Host de Step-CreateVenv
   (documentado explicitamente en el plan como el unico ajuste tolerado).
3. El Builder documenta en el execution_log el resultado del test de la
   barrera en modo FAIL-sin-fix (contra el script antes del cambio de
   Fase 2) y en modo PASS-con-fix (contra el script despues del cambio),
   con el conteo literal de invocaciones registradas (1 tras la primera
   corrida, 2 tras la segunda).
4. ruff check tests/test_setup_dev_worktree_script.py y
   ruff format --check tests/test_setup_dev_worktree_script.py dan
   exit code 0.
5. La suite scripts/run_pytest_safe.py --level all reportada por el
   Builder esta verde y su tested_commit_sha coincide con el HEAD del
   commit de entrega.
6. tests/test_setup_dev_worktree_script.py completo da 8 passed / 0
   failed en Windows (7 preexistentes + 1 nuevo), o se skipea entero
   fuera de Windows via el pytestmark de modulo sin que el Builder lo
   haya modificado.
7. --validate --json --project-root . reportado por el Builder da
   errors: 0 (aceptando unicamente el warning estructural
   TP-STRUCT-01 si por algun motivo el AUDIT no fuese detectado en ese
   momento del ciclo; en condiciones normales, con este AUDIT presente,
   debe dar tambien warnings: {} u objeto equivalente sin
   audit-missing-tp-check).
8. scripts/setup_dev_worktree.ps1 no modifica Step-CreateWorktree,
   Test-WorktreeHasUncommittedChanges ni Invoke-RemoveWorktree; y
   .agent/motor_checkpoint.py, .agent/scope_gate.py,
   .agent/agent_controller.py quedan bit-a-bit identicos a HEAD (0
   solapamiento con la superficie de WOT-2026-019v).

## Evidencia esperada en execution_log_WOT-2026-019s.md

- Output literal del test de la barrera corrido en modo FAIL-sin-fix
  (contra el script antes de la Fase 2) y su mensaje de fallo exacto.
- Output literal del mismo test corrido en modo PASS-con-fix (contra el
  script despues de la Fase 2), mostrando el conteo de invocaciones
  subiendo de 1 a 2 tras la segunda corrida.
- git diff (o su resumen de lineas anadidas/eliminadas) de
  scripts/setup_dev_worktree.ps1 y de
  tests/test_setup_dev_worktree_script.py.
- Output de pytest tests/test_setup_dev_worktree_script.py -q (8
  passed / 0 failed en Windows).
- Output de ruff check y ruff format --check sobre
  tests/test_setup_dev_worktree_script.py.
- Checkpoint de la suite completa (tested_commit_sha) y de
  --validate --json.
