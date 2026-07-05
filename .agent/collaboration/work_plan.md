# Work Plan - WOT-2026-019i

## Metadata
- **ID:** WOT-2026-019i
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** `scripts/run_gates_dispatch.py` es NO-EJECUTABLE por
  `ModuleNotFoundError: No module named 'runtime.motor_link'` (shadowing de
  `runtime` por `.agent/runtime/` al insertar `.agent` en `sys.path` a nivel
  de modulo).
- **Prioridad:** Baja (alto valor: barrera de bus/tooling de cierre esta rota)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Reparar `scripts/run_gates_dispatch.py` para que se pueda ejecutar sin
`ModuleNotFoundError`, replicando el patron ya canonico de
`scripts/check_deliverables_exist.py` (import lazy de `scope_gate` dentro de
una funcion helper), de modo que `from runtime.motor_link import
resolve_motor_root` resuelva siempre al paquete `<motor>/runtime/` y nunca al
paquete `.agent/runtime/` que hace sombra.

## Decision Arquitectonica

**Elegida: replicar el patron lazy de `scripts/check_deliverables_exist.py`
(import de `scope_gate` dentro de `_import_scope_gate()`, `.agent` fuera del
`sys.path` a nivel de modulo).** Motivo: es el UNICO patron ya verificado en
produccion en este mismo repo que resuelve `from runtime.motor_link import
resolve_motor_root` sin shadowing, sin requerir cambios en `.agent/runtime/`
ni en `runtime/motor_link.py`. Es el cambio de menor blast-radius posible:
1 funcion nueva + 1 punto de llamada modificado, sin tocar ninguna otra
funcion ni firma publica.

**Descartada: renombrar o vaciar el paquete `.agent/runtime/__init__.py`.**
Eliminaria el shadowing de raiz, pero excede el alcance de este ticket (Tier
mas alto: tocaria un paquete compartido por el motor entero, con blast-radius
desconocido sobre otros scripts que puedan importar `.agent/runtime/`
explicitamente) y no tiene ningun precedente verificado en este repo.

**Descartada: insertar `.agent` DESPUES de `<motor>` pero con
`sys.path.append` en vez de `insert(0, ...)`.** No resuelve el problema: aun
si `.agent` queda al final de `sys.path`, `<motor>/runtime/` YA esta en
`sys.path` en indice 0 (linea 22, `_PROJECT_ROOT_BOOTSTRAP`), asi que en
teoria ganaria igual -- pero el bug real observado prueba que el orden actual
(`.agent` insertado en indice 0 en la linea 25, DESPUES del insert de
`_PROJECT_ROOT_BOOTSTRAP` en la linea 22) hace que `.agent` quede MAS
adelante en la lista que `_PROJECT_ROOT_BOOTSTRAP`, ganando la resolucion.
Cambiar el orden de insercion es fragil y no tiene un precedente verificado;
el patron lazy (que retrasa la insercion hasta que es estrictamente
necesaria) es mas robusto y ya esta probado en `check_deliverables_exist.py`.

## Contexto (Fase 0 del Orquestador, verificado en esta sesion)

- REPRO en vivo confirmado: `.venv/Scripts/python.exe
  scripts/run_gates_dispatch.py` -> exit 1,
  `ModuleNotFoundError: No module named 'runtime.motor_link'` en la linea 54
  (`from runtime.motor_link import resolve_motor_root as _resolve`, dentro de
  `resolve_motor_root_path`).
- Causa raiz confirmada por lectura directa: `run_gates_dispatch.py` lineas
  23-25 insertan `.agent` en `sys.path` A NIVEL DE MODULO
  (`_AGENT_DIR = _PROJECT_ROOT_BOOTSTRAP / ".agent"`;
  `sys.path.insert(0, str(_AGENT_DIR))`), inmediatamente antes de
  `import scope_gate` (linea 28, tambien a nivel de modulo). Como
  `.agent/runtime/__init__.py` EXISTE (paquete real, confirmado con
  `ls .agent/runtime/*.py` -> solo `__init__.py`, sin `motor_link.py`),
  cuando la linea 54 ejecuta `from runtime.motor_link import ...`, Python
  resuelve el nombre `runtime` contra `.agent/runtime/` (que no tiene
  `motor_link.py`) en vez de `<motor>/runtime/motor_link.py` (que si lo
  tiene, confirmado con `ls runtime/*.py`).
- Precedente canonico que SI funciona en el mismo repo con el mismo import:
  `scripts/check_deliverables_exist.py` importa exactamente
  `from runtime.motor_link import resolve_motor_root` (dentro de
  `resolve_motor_root()`, linea 57) y no falla, porque su bootstrap a nivel
  de modulo (lineas 17-23) inserta SOLO `_PROJECT_ROOT_BOOTSTRAP` (raiz del
  motor), y el import de `scope_gate` es LAZY dentro de
  `_import_scope_gate()` (lineas 34-41), que inserta `.agent` en `sys.path`
  solo dentro de esa funcion, nunca a nivel de modulo. `run_pytest_safe.py`
  sigue el mismo patron (nunca inserta `.agent` a nivel de modulo).
- `run_gates_dispatch.py` SI necesita `scope_gate` (usado en
  `read_delivery_authority()`, linea 109, via
  `scope_gate.read_delivery_authority(...)`). El fix debe preservar que ese
  uso siga funcionando, solo cambiando CUANDO se inserta `.agent` en el path
  y CUANDO se importa `scope_gate` (de nivel-de-modulo a lazy).
- Test existente (`tests/unit/test_run_gates_dispatch.py`) carga el modulo
  completo UNA VEZ a nivel de modulo del propio archivo de test (lineas
  11-16, via `importlib.util.spec_from_file_location` +
  `spec.loader.exec_module(dispatch)`). Esto implica que el fallo real
  (`ModuleNotFoundError` en tiempo de import) YA esta ocurriendo dentro de
  ese `exec_module` en cuanto se corre CUALQUIER test del archivo hoy: no es
  posible verificar el shadowing con monkeypatch sobre un modulo ya cargado
  en memoria, porque el error ocurre ANTES de que el modulo termine de
  cargar. El test nuevo de regresion (Paso 2 de este plan) debe invocar el
  script como PROCESO independiente (`subprocess.run([sys.executable,
  str(script_path)], ...)`), no reusar el `dispatch` ya importado por el
  archivo de test.

## Files Likely Touched

### repo_motor

- `scripts/run_gates_dispatch.py` (mover la insercion de `.agent` en
  `sys.path` y el `import scope_gate` de nivel-de-modulo a una funcion lazy;
  llamar a esa funcion donde se usa `scope_gate`)
- `tests/unit/test_run_gates_dispatch.py` (anadir un test de regresion que
  invoque el script como subprocess y confirme exit 0 sin traceback, mas el
  mutation-check correspondiente)

## Read/inspect only (Manager-only / no tocar)

- `scripts/check_deliverables_exist.py` (fuente del patron canonico
  `_import_scope_gate()`; solo lectura, sirve de referencia exacta para el
  fix, no se modifica)
- `scripts/run_pytest_safe.py` (referencia de paridad: nunca inserta
  `.agent` a nivel de modulo; solo lectura)
- `.agent/scope_gate.py` (fuente de `scope_gate.read_delivery_authority`;
  solo lectura, el fix no cambia su contrato ni su firma)
- `.agent/runtime/__init__.py` (paquete que hace sombra; solo lectura, NO se
  renombra ni se elimina: el fix vive enteramente en
  `scripts/run_gates_dispatch.py`, cambiar el paquete `.agent/runtime/`
  excede el alcance y el blast-radius de este ticket)
- `runtime/motor_link.py` (fuente de `resolve_motor_root`; solo lectura, no
  se modifica)

## Plan de Implementacion

### PASO 1 (IMPLEMENT) - `scripts/run_gates_dispatch.py`, import lazy de `scope_gate`

1. Eliminar de nivel-de-modulo (lineas 23-28 actuales):
   - `_AGENT_DIR = _PROJECT_ROOT_BOOTSTRAP / ".agent"`
   - el `if str(_AGENT_DIR) not in sys.path: sys.path.insert(0, str(_AGENT_DIR))`
   - `import scope_gate  # noqa: E402`
2. Crear una funcion helper `_import_scope_gate()` (mismo nombre y forma que
   `check_deliverables_exist.py::_import_scope_gate`) que:
   - calcule `agent_dir = _PROJECT_ROOT_BOOTSTRAP / ".agent"` dentro de la
     funcion,
   - inserte `agent_dir` en `sys.path` solo si no esta ya presente,
   - haga `import scope_gate as _sg` dentro de la funcion,
   - retorne `_sg`.
3. Sustituir el unico uso de `scope_gate` a nivel de modulo
   (`read_delivery_authority()`, linea ~105-109) para que llame primero a
   `_sg = _import_scope_gate()` y luego use
   `_sg.read_delivery_authority(content, default="repo_motor")` en vez de
   `scope_gate.read_delivery_authority(...)`.
4. No modificar ninguna otra funcion de `run_gates_dispatch.py`
   (`resolve_project_root_path`, `get_collab_dir_path`,
   `resolve_motor_root_path`, `resolve_authority_root`,
   `build_project_env`, `run_motor_script`, `has_local_tests`,
   `run_code_gates`, `run_deliverable_gates`, `main`) mas alla del cambio de
   import descrito arriba. `MOTOR_ROOT = resolve_motor_root_path(PROJECT_ROOT)`
   (linea 63, a nivel de modulo) sigue ejecutandose igual: tras el fix,
   `.agent` ya NO esta en `sys.path` en ese punto, asi que
   `from runtime.motor_link import resolve_motor_root` (dentro de
   `resolve_motor_root_path`, linea 54) resuelve al paquete
   `<motor>/runtime/` sin shadowing.
5. No cambiar la logica de dispatch por `deliverable_type` (`main()`,
   `run_code_gates`, `run_deliverable_gates` quedan con el mismo
   comportamiento observable, mismos argumentos, mismos subprocess
   invocados).

Restricciones:
- NO tocar `scripts/check_deliverables_exist.py`, `scripts/run_pytest_safe.py`,
  `.agent/scope_gate.py`, `.agent/runtime/__init__.py` ni
  `runtime/motor_link.py` (fuera de alcance, solo lectura).
- NO cambiar la firma publica de ninguna funcion existente de
  `run_gates_dispatch.py` (los tests existentes de
  `tests/unit/test_run_gates_dispatch.py` dependen de
  `dispatch.read_deliverable_type`, `dispatch.read_delivery_authority`,
  `dispatch.run_code_gates`, `dispatch.run_deliverable_gates`,
  `dispatch.main`, `dispatch.has_local_tests`,
  `dispatch.resolve_motor_root_path` con sus firmas actuales).
- NO anadir un import a nivel de modulo de `scope_gate` en ninguna forma
  (ni directo ni con alias): el import debe quedar exclusivamente dentro de
  `_import_scope_gate()`.

DoD Paso 1:
- [ ] `scripts/run_gates_dispatch.py` ya NO inserta `.agent` en `sys.path` a
      nivel de modulo, y ya NO tiene `import scope_gate` a nivel de modulo.
- [ ] Existe una funcion `_import_scope_gate()` en
      `scripts/run_gates_dispatch.py` que inserta `.agent` en `sys.path` y
      hace el import de `scope_gate` dentro de su propio cuerpo.
- [ ] `read_delivery_authority()` sigue devolviendo el valor correcto
      (verificado por el test existente
      `test_read_delivery_authority_from_work_plan`, que debe seguir
      pasando sin cambios en su codigo).
- [ ] Correr el script ya NO produce `ModuleNotFoundError` en el import
      (puede fallar mas adelante en la ejecucion por otras razones de
      entorno -- p.ej. ausencia de `work_plan.md` valido -- pero NUNCA por
      el shadowing de `runtime`).
- [ ] `ruff check scripts/run_gates_dispatch.py` y
      `ruff format --check scripts/run_gates_dispatch.py` exit 0.

### PASO 2 (IMPLEMENT) - Test de regresion como subprocess + mutation-check

Anadir a `tests/unit/test_run_gates_dispatch.py` un test nuevo,
`test_run_gates_dispatch_importable_without_module_shadowing`, que:
1. Invoca el script como proceso independiente:
   `subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" /
   "run_gates_dispatch.py")], cwd=PROJECT_ROOT, capture_output=True,
   text=True)` (usar un `cwd`/entorno donde el script pueda ejecutar sin
   depender de un `work_plan.md` real del motor; si `main()` requiere mas
   contexto para completar en exit 0, el test puede limitarse a comprobar
   que `ModuleNotFoundError` y `"runtime.motor_link"` NO aparecen en
   `result.stderr`, en vez de exigir `returncode == 0` de punta a punta --
   ambas aserciones son validas siempre que el test falle de forma
   determinista contra el codigo pre-fix).
2. Afirma explicitamente que `"ModuleNotFoundError"` NO esta en
   `result.stderr` y que `"No module named 'runtime.motor_link'"` NO esta en
   `result.stderr`.
3. Debe ejecutarse como proceso nuevo (no reusar el modulo `dispatch` ya
   cargado por `importlib.util` al inicio del archivo de test): el fallo
   real ocurre en tiempo de import a nivel de modulo, y el modulo ya cargado
   en el proceso pytest no vuelve a ejecutar ese import.

Mutation check (documentar en `execution_log.md` con salida literal de
pytest): reintroducir temporalmente el shadowing (volver a insertar
`.agent` en `sys.path` a nivel de modulo Y volver a poner
`import scope_gate` a nivel de modulo, exactamente como estaba antes del
Paso 1), confirmar que
`test_run_gates_dispatch_importable_without_module_shadowing` FALLA (el
subprocess vuelve a mostrar `ModuleNotFoundError: No module named
'runtime.motor_link'` en `stderr`), restaurar el fix y confirmar que el test
vuelve a pasar.

Restricciones:
- NO modificar ningun test existente de
  `tests/unit/test_run_gates_dispatch.py` (los 15 tests actuales deben
  seguir pasando sin cambios en su codigo).
- NO eliminar ni renombrar el `import scripts.pip_audit_policy as
  pip_audit_policy` de cabecera del archivo de test (usado por
  `test_run_code_gates_repo_motor_uses_motor_root_and_absolute_pytest`).

DoD Paso 2:
- [ ] `test_run_gates_dispatch_importable_without_module_shadowing` existe,
      pasa tras el fix del Paso 1, y FALLA cuando se reintroduce el
      shadowing (mutation check documentado con salida literal de pytest
      mostrando el `ModuleNotFoundError` reaparecido).
- [ ] `pytest tests/unit/test_run_gates_dispatch.py -v` exit 0 con 16 tests
      (15 existentes + 1 nuevo), 0 fallos.
- [ ] `ruff check tests/unit/test_run_gates_dispatch.py` y
      `ruff format --check tests/unit/test_run_gates_dispatch.py` exit 0.

## Quality Gates

- Builder ejecuta (interprete canonico: `.venv/Scripts/python.exe`, NO el
  `python` del PATH):
  - `pytest tests/unit/test_run_gates_dispatch.py -v` (exit 0, 16 tests
    incluyendo el nuevo).
  - `scripts/run_gates_dispatch.py` (ya no `ModuleNotFoundError` en el
    import; confirmar con salida literal).
  - `ruff check scripts/run_gates_dispatch.py tests/unit/test_run_gates_dispatch.py`
    (exit 0).
  - `ruff format --check scripts/run_gates_dispatch.py tests/unit/test_run_gates_dispatch.py`
    (exit 0).
  - `scripts/run_pytest_safe.py` (suite completa, stamp fresco sobre HEAD;
    level=all, exit_code=0).
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - `.agent/agent_controller.py --validate --json --project-root .`

## STOP conditions

- Si el fix reintroduce `import scope_gate` o la insercion de `.agent` en
  `sys.path` a NIVEL DE MODULO (fuera de `_import_scope_gate()`): DETENTE,
  esto reproduce exactamente el bug original.
- Si `test_run_gates_dispatch_importable_without_module_shadowing` NO falla
  al reintroducir el shadowing (mutation check ausente o mal ejecutado):
  DETENTE, el test es un placebo, no hay evidencia de que verifique el
  mecanismo real.
- Si algun test existente de `tests/unit/test_run_gates_dispatch.py` se
  rompe con el cambio: DETENTE, escala antes de forzar el test existente a
  pasar cambiando su asercion.
- Si el Builder intenta modificar `scripts/check_deliverables_exist.py`,
  `scripts/run_pytest_safe.py`, `.agent/scope_gate.py`,
  `.agent/runtime/__init__.py` o `runtime/motor_link.py`: DETENTE y escala
  -- fuera del alcance declarado en Files Likely Touched.
- Si el Builder cambia la logica de dispatch por `deliverable_type` (que
  gates corren para `code`/`documentation`/`research`/`analysis`/`mixed`):
  DETENTE y escala -- Non-goal explicito de este ticket.

## Non-goals

- NO cambiar la logica de dispatch por `deliverable_type` (que gates corren
  para cada tipo).
- NO tocar `scripts/check_deliverables_exist.py`, `scripts/run_pytest_safe.py`
  ni ningun otro script del motor mas alla de
  `scripts/run_gates_dispatch.py`.
- NO renombrar, mover ni vaciar el paquete `.agent/runtime/__init__.py`
  (fuente del shadowing, pero fuera de alcance: el fix vive enteramente en
  `scripts/run_gates_dispatch.py`).
- NO modificar `.agent/scope_gate.py` ni su contrato publico
  (`read_delivery_authority`).
- NO anadir tests nuevos a ningun otro archivo de `tests/` distinto de
  `tests/unit/test_run_gates_dispatch.py`.

## Riesgos

- Bajo: mover el import de `scope_gate` a lazy podria, en teoria, ocultar un
  error de import de `scope_gate` hasta que se llame
  `read_delivery_authority()` -- mitigado porque ese es exactamente el
  patron ya probado en produccion por `check_deliverables_exist.py` (mismo
  repo, mismo modulo importado, sin incidentes conocidos).
- Bajo: el test nuevo depende de invocar el script como subprocess real, lo
  que puede ser mas lento o fragil ante el entorno (p.ej. si
  `AGENT_PROJECT_ROOT` esta seteado en el entorno del test) -- mitigado
  fijando `cwd=PROJECT_ROOT` explicito y limitando la asercion al mensaje de
  `stderr` relacionado con el shadowing, no al `returncode` completo de
  `main()`.
- Bajo: si algun otro punto futuro del script vuelve a necesitar
  `scope_gate` a nivel de modulo, el patron lazy exige recordar llamar a
  `_import_scope_gate()` explicitamente -- mitigado porque el precedente
  (`check_deliverables_exist.py`) ya documenta este patron y el mutation
  check de este ticket deja una barrera viva contra la regresion mas
  probable (reinsertar el import a nivel de modulo).

## Decision sobre REVIEW

Review 2 adversarial fresh-context NO obligatoria por regla generica de
blast-radius (el cambio es un script de tooling de cierre, no CI/workflow),
pero SI recomendada dado que `run_gates_dispatch.py` es invocado por el
propio flujo de quality gates del motor (bus/tooling de cierre, Tier 3 segun
CEM). El Manager en review debe, como minimo, re-ejecutar
`scripts/run_gates_dispatch.py` el mismo (con el interprete canonico) y
confirmar con sus propios ojos que el traceback de `ModuleNotFoundError` ya
no aparece, ademas de revisar el diff literal de
`scripts/run_gates_dispatch.py` para confirmar que no quedo ningun import de
`scope_gate` a nivel de modulo.

## Criterios de Aceptacion Global (1:1 con el DoD binario de la ficha)

- [ ] `run_gates_dispatch.py` corre y dispatcha por `deliverable_type` SIN
      `ModuleNotFoundError` (verificado ejecutando el script directamente,
      sin traceback de import).
- [ ] MUTATION: reintroducir el import roto (insertar `.agent` a nivel de
      modulo antes del import de `motor_link`, y `import scope_gate` a nivel
      de modulo) hace que
      `test_run_gates_dispatch_importable_without_module_shadowing` FALLE
      (vuelve el `ModuleNotFoundError`), documentado con salida literal de
      pytest. Restaurar el fix hace que el test vuelva a pasar.
- [ ] `tests/unit/test_run_gates_dispatch.py` pasa completo (16 tests: 15
      existentes + 1 nuevo), sin cambios en las aserciones de los tests
      existentes.
- [ ] `ruff check` y `ruff format --check` exit 0 sobre
      `scripts/run_gates_dispatch.py` y
      `tests/unit/test_run_gates_dispatch.py`.
- [ ] `scripts/run_pytest_safe.py` verde (stamp fresco sobre HEAD, level=all,
      exit_code=0).
- [ ] `agent_controller.py --validate --json --project-root .` exit 0/0
      tras el cierre.
- [ ] `scripts/check_deliverables_exist.py`, `scripts/run_pytest_safe.py`,
      `.agent/scope_gate.py`, `.agent/runtime/__init__.py` y
      `runtime/motor_link.py` NO aparecen modificados en el diff final.
