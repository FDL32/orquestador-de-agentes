# AUDIT - WOT-2026-019i

Ticket: `scripts/run_gates_dispatch.py` es NO-EJECUTABLE por
`ModuleNotFoundError: No module named 'runtime.motor_link'` (shadowing de
`runtime` por `.agent/runtime/`).
Estado del plan: APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin contradiccion:
  PASO 1 (mover la insercion de `.agent` y el import de `scope_gate` a una
  funcion lazy `_import_scope_gate()`) -> PASO 2 (test de regresion por
  subprocess + mutation check). Ningun paso pide insertar y retirar `.agent`
  del `sys.path` de forma permanente en el mismo punto; el mutation check
  del PASO 2 es explicitamente temporal y documentado, no queda en el
  commit final.
- TP-02: verificado - cada DoD cita un comando o asercion literal: exit code
  del subprocess/`stderr` sin `ModuleNotFoundError` ni
  `"runtime.motor_link"`, `pytest tests/unit/test_run_gates_dispatch.py -v`
  con conteo exacto de tests (16 = 15 existentes + 1 nuevo), `ruff check`/
  `ruff format --check` con rutas exactas, y el mutation-check con salida
  literal de pytest documentada en `execution_log.md`.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos
  concretos (`scripts/run_gates_dispatch.py`,
  `tests/unit/test_run_gates_dispatch.py`), sin comodines. Read/inspect only
  enumera 4 archivos concretos
  (`scripts/check_deliverables_exist.py`, `scripts/run_pytest_safe.py`,
  `.agent/scope_gate.py`, `.agent/runtime/__init__.py`,
  `runtime/motor_link.py`) explicitamente fuera de alcance de edicion.
- TP-04: verificado - no aparece lenguaje blando tipo "si procede" en el
  flujo critico. La condicionalidad del diagnostico (por que el fix debe
  ser lazy y no eliminar `.agent` del path por completo) esta cerrada con
  evidencia concreta (precedente de `check_deliverables_exist.py`, repro en
  vivo del traceback), no delegada como heuristica libre al Builder.
- TP-05: verificado - work_plan.md, STRATEGY_WOT-2026-019i.md y este AUDIT
  describen la misma secuencia (import lazy de `scope_gate` via
  `_import_scope_gate()` + test de regresion por subprocess + mutation
  check), los mismos 2 archivos de Files Likely Touched, y los mismos 7
  criterios de aceptacion global. Los Blockers de este AUDIT usan los
  mismos verbos que las STOP conditions del PLAN (no tocar los 5 archivos
  read-only, no cambiar la logica de dispatch, no reintroducir el import a
  nivel de modulo).
- TP-06: no aplica como anti-patron (este TP Check usa la forma canonica
  TP-01 a TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional tipo "si
  existe" o "si aplica" en Objetivo, Fases o Criterios de Aceptacion Global
  del work_plan.md decidiendo cuando se activa el fix: la decision (mover
  siempre el import a lazy, en `run_gates_dispatch.py`) esta cerrada
  explicitamente, sin condicionalidad de alcance delegada al Builder.

## Premisa de Fase 0 (verificacion independiente del Manager antes de aprobar)

Confirmado en esta sesion (2026-07-06):
- REPRO en vivo: `.venv/Scripts/python.exe scripts/run_gates_dispatch.py`
  produce exit 1 con `ModuleNotFoundError: No module named
  'runtime.motor_link'` en la linea 54 de `resolve_motor_root_path`.
- Lectura directa de `scripts/run_gates_dispatch.py` lineas 20-28: confirma
  que `_AGENT_DIR = _PROJECT_ROOT_BOOTSTRAP / ".agent"` y
  `sys.path.insert(0, str(_AGENT_DIR))` corren a nivel de modulo,
  inmediatamente antes de `import scope_gate` (tambien a nivel de modulo).
- `ls .agent/runtime/*.py` -> solo `__init__.py` (sin `motor_link.py`);
  `ls runtime/*.py` -> `__init__.py`, `motor_link.py`, `project_root.py`,
  `status_bar_indicator.py`, `ui_state_projector.py`. Confirma que el
  paquete `.agent/runtime/` hace sombra al paquete `<motor>/runtime/` en
  cuanto `.agent` esta en `sys.path`.
- Lectura directa de `scripts/check_deliverables_exist.py` lineas 17-41 y
  57: confirma el precedente canonico -- bootstrap a nivel de modulo
  inserta SOLO la raiz del proyecto, `scope_gate` se importa dentro de
  `_import_scope_gate()` (lineas 34-41), y
  `from runtime.motor_link import resolve_motor_root` (linea 57) no falla
  porque `.agent` nunca esta en `sys.path` en ese punto salvo que
  `_import_scope_gate()` ya haya corrido antes.
- Lectura directa de `tests/unit/test_run_gates_dispatch.py` lineas 1-16:
  confirma que el modulo se carga una sola vez, a nivel de modulo del
  propio archivo de test, via `importlib.util.spec_from_file_location` +
  `spec.loader.exec_module(dispatch)`. Confirma que el test de regresion
  nuevo debe invocar el script como subprocess independiente (no reusar
  `dispatch` ya cargado) para poder observar el fallo de import real.
- Busqueda de "subprocess" y de invocaciones con sys.executable sobre
  run_gates_dispatch.py en tests/unit/test_run_gates_dispatch.py (0 matches
  fuera de los usos de monkeypatch.setattr(dispatch.subprocess, "run", ...)):
  confirma que ningun test existente invoca el script como proceso real hoy.
- `git status --short`: arbol limpio antes del bootstrap.

## Blockers (para el Manager en review)

- Si `scripts/run_gates_dispatch.py` conserva `import scope_gate` o la
  insercion de `.agent` a NIVEL DE MODULO fuera de `_import_scope_gate()`
  en el diff final: BLOCKER critico, reproduce exactamente el bug original.
- Si `scripts/check_deliverables_exist.py`, `scripts/run_pytest_safe.py`,
  `.agent/scope_gate.py`, `.agent/runtime/__init__.py` o
  `runtime/motor_link.py` aparecen modificados en el diff final: BLOCKER,
  fuera del alcance declarado (el fix es exclusivamente de
  `run_gates_dispatch.py` + su test).
- Si `test_run_gates_dispatch_importable_without_module_shadowing` NO falla
  contra el codigo pre-fix (mutation check ausente o mal ejecutado,
  reintroduciendo el shadowing): BLOCKER, no hay evidencia de que el test
  verifique el mecanismo real en vez de ser un placebo.
- Si algun test existente de `tests/unit/test_run_gates_dispatch.py` se
  rompe con el cambio (deben seguir pasando los 15 tests actuales sin
  cambios en su codigo): BLOCKER.
- Si `ruff check` o `ruff format --check` fallan sobre
  `scripts/run_gates_dispatch.py` o `tests/unit/test_run_gates_dispatch.py`:
  BLOCKER, gate de calidad no satisfecho.
- Si la suite canonica (`run_pytest_safe.py`) no queda verde con stamp
  fresco sobre HEAD antes de mark-ready: BLOCKER, el gate de pre-handoff no
  confiara en el resultado.
- Si `execution_log.md` no documenta el mutation check (reintroducir el
  shadowing + fallo del test nuevo + restauracion + exito) con salida
  literal de pytest/stderr: BLOCKER, evidencia insuficiente.
- Si el diff cambia la firma publica de cualquier funcion existente de
  `run_gates_dispatch.py` (`read_deliverable_type`,
  `read_delivery_authority`, `run_code_gates`, `run_deliverable_gates`,
  `main`, `has_local_tests`, `resolve_motor_root_path`): BLOCKER, rompe el
  contrato que usan los 15 tests existentes.

## Evidencia esperada en execution_log.md

- Diff final (o cita literal) de `scripts/run_gates_dispatch.py` mostrando
  la funcion `_import_scope_gate()` y el punto donde
  `read_delivery_authority()` la invoca.
- Confirmacion de que la insercion de `.agent` en `sys.path` y el
  `import scope_gate` ya NO existen a nivel de modulo del script.
- Cita literal del test nuevo con su asercion sobre `stderr` del subprocess.
- Salida literal (stdout/stderr relevante) de ejecutar
  `scripts/run_gates_dispatch.py` directamente, confirmando ausencia de
  `ModuleNotFoundError`.
- Salida literal de pytest del mutation check: ANTES de reintroducir el
  shadowing (verde, incluyendo el test nuevo), DESPUES de reintroducirlo (el
  test nuevo FALLA mostrando `ModuleNotFoundError` en el subprocess), y tras
  restaurar el fix (verde de nuevo).
- Salida literal de `pytest tests/unit/test_run_gates_dispatch.py -v`
  completo (16 tests, no solo el nuevo), confirmando 0 fallos.
- Salida literal de `ruff check`/`ruff format --check` sobre
  `scripts/run_gates_dispatch.py` y `tests/unit/test_run_gates_dispatch.py`,
  exit code 0.
- Salida literal (o resumen con exit_code/level/tested_commit_sha) de
  `scripts/run_pytest_safe.py` confirmando level=all, exit_code=0 y
  tested_commit_sha == HEAD tras el commit del fix.
- Commit sha del repo_motor que contiene el fix, citado con
  WOT-2026-019i en el mensaje.
- Confirmacion explicita (diff vacio o "sin cambios") de que
  `scripts/check_deliverables_exist.py`, `scripts/run_pytest_safe.py`,
  `.agent/scope_gate.py`, `.agent/runtime/__init__.py` y
  `runtime/motor_link.py` no aparecen modificados.
