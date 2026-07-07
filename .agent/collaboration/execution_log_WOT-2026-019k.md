# Execution Log - WOT-2026-019k

Ticket: Acotar el test de regresion de 019i
(test_run_gates_dispatch_importable_without_module_shadowing) para que
verifique la ausencia de shadowing de runtime.motor_link en <5s (de ~165s)
sin perder la barrera del ModuleNotFoundError.
**Estado:** COMPLETED

## Bitacora

- Fase 0 (Orquestador): premisa CONFIRMADA vs codigo real. El test
  (tests/unit/test_run_gates_dispatch.py:359-382) invoca
  scripts/run_gates_dispatch.py como SUBPROCESO COMPLETO -> arranca main()
  (l.229) que corre ruff + pytest-safe + todos los gates -> ~165s
  (Review 2 de 019i: "1 passed in 164.48s"). Pero lo unico que verifica es
  que el import de nivel-modulo no de ModuleNotFoundError: el fallo de 019i
  ocurria en MOTOR_ROOT = resolve_motor_root_path(PROJECT_ROOT)
  (run_gates_dispatch.py:67 -> import runtime.motor_link l.58), todo a nivel
  de modulo ANTES de main(). El subprocess completo es un desperdicio para
  verificar un import.
- Plan + AUDIT creados y aprobados por el Manager (2026-07-07). Enfoque:
  Opcion (A) test-only -- reemplazar el subprocess completo por un
  `python -c` con importlib.util.spec_from_file_location + module_from_spec
  + exec_module del script, que ejecuta el codigo top-level (incluida la
  l.67 con el import problematico) SIN invocar main() (porque __name__ no es
  "__main__"). Coste medido por el Manager: ~0.115s. Se preservan las 2
  aserciones de stderr + una 3a: "[dispatch]" not in stdout (confirma que
  main/gates no corren). Files Likely Touched: tests/unit/test_run_gates_dispatch.py
  (test-only; run_gates_dispatch.py en Non-goals). Cross-platform (el import
  no es Windows-especifico).
- Mutation verificado por el Manager: revertir en el working tree el diff del
  commit 5a7d973 de 019i (que inserta .agent en sys.path[0] antes del import)
  reproduce el ModuleNotFoundError -> el test acotado sigue cazandolo. Insertar
  .agent en indice posterior NO lo reproduce (el fix de 019i ya prioriza la
  raiz); documentado para que el Builder no yerre la mutation.
- Artefactos de WOT-2026-019p (COMPLETED) archivados:
  execution_log.md -> execution_log_WOT-2026-019p.md.
- El Orquestador ejecuto `--bootstrap-ticket` (plan_id=WOT-2026-019k):
  STATE.md a ACTIVE_TICKET=WOT-2026-019k / STATUS=IN_PROGRESS y
  STATE_CHANGED -> IN_PROGRESS emitido al bus. Este log queda en IN_PROGRESS.

## Builder: implementacion (Fase 1, 2, 3)

### Fase 1.1 + 1.2: subprocess acotado a exec_module + assert estructural

Unico archivo tocado: `tests/unit/test_run_gates_dispatch.py`, exclusivamente
dentro de `test_run_gates_dispatch_importable_without_module_shadowing`
(git diff --stat: 1 file changed, 27 insertions(+), 2 deletions(-)).

Se reemplazo `subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" /
"run_gates_dispatch.py")], ...)` por un subprocess `python -c` que ejecuta el
script via `spec_from_file_location` + `module_from_spec` +
`spec.loader.exec_module` (mismo patron ya usado en el propio archivo,
lineas 13-18), de modo que el codigo a nivel de modulo (incluida la l.67
`MOTOR_ROOT = resolve_motor_root_path(PROJECT_ROOT)` y el import de la l.58
`from runtime.motor_link import resolve_motor_root`) se ejecuta integramente,
pero `__name__` del modulo cargado es `'run_gates_dispatch_module_probe'`
(no `'__main__'`), por lo que el guard `if __name__ == "__main__": main()`
al final del script no se dispara y main()/gates jamas corren.

Snippet exacto usado (variable renombrada a `exec_module_only_snippet`,
minusculas, por N806 de ruff -- ver nota mas abajo; el mecanismo es identico
al del work_plan):

```python
exec_module_only_snippet = (
    "import importlib.util, sys\n"
    "from pathlib import Path\n"
    "project_root = Path(sys.argv[1]).resolve()\n"
    "spec = importlib.util.spec_from_file_location(\n"
    "    'run_gates_dispatch_module_probe',\n"
    "    project_root / 'scripts' / 'run_gates_dispatch.py',\n"
    ")\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
)

result = subprocess.run(
    [sys.executable, "-c", exec_module_only_snippet, str(PROJECT_ROOT)],
    cwd=PROJECT_ROOT,
    capture_output=True,
    text=True,
)

assert "ModuleNotFoundError" not in result.stderr
assert "No module named 'runtime.motor_link'" not in result.stderr
assert "[dispatch]" not in result.stdout
```

Se preservaron las 2 aserciones originales sin debilitarlas y se anadio la
3a (`"[dispatch]" not in result.stdout`), que confirma estructuralmente que
ningun gate/print de main() se ejecuto. Docstring actualizado para explicar
el nuevo mecanismo acotado.

**Desviacion menor del work_plan (documentada):** el snippet ejemplo del plan
usaba el nombre `_EXEC_MODULE_ONLY_SNIPPET` (mayusculas) como si fuera
constante de modulo; al vivir como variable LOCAL dentro de la funcion de
test, `ruff check` la marca con `N806 Variable ... in function should be
lowercase`. Se renombro a `exec_module_only_snippet` (mismo contenido,
mismo mecanismo, solo cambia el nombre de la variable) para que `ruff check`
pase limpio. No afecta ninguna asercion ni el comportamiento.

Gate 1.1/1.2 (comando pedido por el Orquestador, PYTHONDONTWRITEBYTECODE=1,
-p no:cacheprovider):

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest "tests/unit/test_run_gates_dispatch.py::test_run_gates_dispatch_importable_without_module_shadowing" -p no:cacheprovider -v --durations=1
============================= test session starts =============================
platform win32 -- Python 3.10.19, pytest-9.0.3, pluggy-1.6.0
collecting ... collected 1 item

tests/unit/test_run_gates_dispatch.py::test_run_gates_dispatch_importable_without_module_shadowing PASSED [100%]

============================= slowest 1 durations =============================
0.10s call     tests/unit/test_run_gates_dispatch.py::test_run_gates_dispatch_importable_without_module_shadowing
============================== 1 passed in 0.26s ==============================
```

Duracion del test: **0.10s** (0.26s de sesion pytest completa). Muy por
debajo del umbral de 5s exigido, en linea con el ~0.115-0.119s medido por el
Manager. Mejora frente a los ~165s (164.48s confirmados en Review 2 de 019i)
del mecanismo anterior: **de ~165s a 0.10s**.

No-regresion del archivo completo:

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest tests/unit/test_run_gates_dispatch.py -p no:cacheprovider -q
...................                                                      [100%]
19 passed in 0.30s
```

19/19 tests del archivo pasan en 0.30s total (antes, solo el test objetivo
tardaba ~165s).

### Fase 2.1: mutation-verify (shadowing reintroducido, temporal, sin commit)

Confirmado que `5a7d973` es el commit exacto de 019i que toca
`scripts/run_gates_dispatch.py`:
`git log --oneline -- scripts/run_gates_dispatch.py` -> primera entrada:
`5a7d973 WOT-2026-019i: fix run_gates_dispatch shadowing runtime.motor_link
(import lazy scope_gate)`.

git status ANTES de mutar (run_gates_dispatch.py limpio, sin cambios
pendientes):
```
 M .agent/collaboration/STATE.md
R  .agent/collaboration/execution_log.md -> .agent/collaboration/execution_log_WOT-2026-019p.md
 M .agent/collaboration/work_plan.md
 M tests/unit/test_run_gates_dispatch.py
?? .agent/collaboration/AUDIT_WOT-2026-019k.md
?? .agent/collaboration/execution_log.md
```
(scripts/run_gates_dispatch.py NO aparece: limpio.)

Mutation aplicada: `git checkout 5a7d973^ -- scripts/run_gates_dispatch.py`
(revierte SOLO ese archivo a la version PRE-fix, commit padre de 5a7d973).
Diff confirmado (`git diff HEAD -- scripts/run_gates_dispatch.py`) es
exactamente el inverso del diff mostrado por `git show 5a7d973 -- ...`:
reintroduce `_AGENT_DIR = _PROJECT_ROOT_BOOTSTRAP / ".agent"` +
`sys.path.insert(0, str(_AGENT_DIR))` a nivel de modulo (ANTES del import de
`runtime.motor_link` en `resolve_motor_root_path`) y el `import scope_gate`
global de nivel de modulo, eliminando `_import_scope_gate()` lazy.

**FAIL-con-shadowing** (comando y salida literal, `-vv` para el mensaje
completo):

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest "tests/unit/test_run_gates_dispatch.py::test_run_gates_dispatch_importable_without_module_shadowing" -p no:cacheprovider -vv
...
>       assert "ModuleNotFoundError" not in result.stderr
E       assert 'ModuleNotFoundError' not in 'Traceback (most recent call last):\n  File "<string>", line 9, in <module>\n  File "<frozen importlib._bootstrap_external>", line 883, in exec_module\n  File "<frozen importlib._bootstrap>", line 241, in _call_with_frames_removed\n  File "C:\\Users\\fdl\\Proyectos_Python\\orquestador_de_agentes_dev\\scripts\\run_gates_dispatch.py", line 63, in <module>\n    MOTOR_ROOT = resolve_motor_root_path(PROJECT_ROOT)\n  File "C:\\Users\\fdl\\Proyectos_Python\\orquestador_de_agentes_dev\\scripts\\run_gates_dispatch.py", line 54, in resolve_motor_root_path\n    from runtime.motor_link import resolve_motor_root as _resolve\nModuleNotFoundError: No module named \'runtime.motor_link\'\n'
...
============================== 1 failed in 0.26s ==============================
```

Tiempo total del comando (incluye overhead de shell/proceso, medido con
`time`): **real 0m0.607s** (pytest: 0.26s / 1 failed). Contiene literalmente
`ModuleNotFoundError` y `No module named 'runtime.motor_link'` -- la barrera
sigue cazando el shadowing exactamente como antes, en fraccion de segundo en
vez de ~165s.

Restauracion: `git checkout HEAD -- scripts/run_gates_dispatch.py`. Verificado
`git status --porcelain scripts/run_gates_dispatch.py` -> sin salida (limpio)
y `git diff HEAD -- scripts/run_gates_dispatch.py` -> sin salida (identico al
HEAD).

**PASS-sin** (tras restaurar, mismo comando):

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest "tests/unit/test_run_gates_dispatch.py::test_run_gates_dispatch_importable_without_module_shadowing" -p no:cacheprovider -v --durations=1
tests/unit/test_run_gates_dispatch.py::test_run_gates_dispatch_importable_without_module_shadowing PASSED [100%]
0.10s call     tests/unit/test_run_gates_dispatch.py::test_run_gates_dispatch_importable_without_module_shadowing
============================== 1 passed in 0.26s ==============================
```

Tiempo total (con `time`): **real 0m0.617s** (pytest: 0.26s / 1 passed).

Barrera confirmada real (no placebo): FALLA con el shadowing reintroducido,
PASA sin el, ambos en fraccion de segundo.

### Fase 3.1: gates de calidad

Ruff check (tras el rename de variable por N806, ver nota arriba):
```
$ .venv/Scripts/python.exe -m ruff check tests/unit/test_run_gates_dispatch.py
All checks passed!
```

Ruff format --check:
```
$ .venv/Scripts/python.exe -m ruff format --check tests/unit/test_run_gates_dispatch.py
1 file already formatted
```

Validate:
```
$ .venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .
{
  "errors": {"work_plan.md": [], "execution_log.md": [], "notifications.md": [], "consistency": [], "TURN.md": [], "host_project_prefix": [], "git_presence": []},
  "warnings": {},
  "total_errors": 0,
  "total_warnings": 0
}
```

Encoding: `git diff -- tests/unit/test_run_gates_dispatch.py` verificado
programaticamente (decode utf-8 + scan de caracteres > 127) -> **0 caracteres
no-ASCII en el diff introducido**. El archivo completo conserva 3 em-dashes
(U+2014) PRE-EXISTENTES en lineas 72, 286, 355 (comentarios de tickets
anteriores, WOT-2026-003e/014e/019i), ninguno de ellos tocado por este
ticket; no forman parte del diff de entrega.

**Suite completa (`run_pytest_safe.py --level all`): NO ejecutada por el
Builder.** El prompt del Orquestador para este ticket especifica
explicitamente "NO corras `scripts/run_pytest_safe.py --level all` tu: la
suite canonica la corre el Orquestador sobre el HEAD final tras el commit."
Se sigue esa instruccion (tiene prioridad sobre la Fase 3.1 generica del
work_plan, que asume que el Builder corre la suite); el Orquestador la
correra sobre el commit final con `tested_commit_sha == HEAD`.

### Estado final de git

`git status --porcelain` (tras completar Fases 1-3):
```
 M .agent/collaboration/STATE.md
R  .agent/collaboration/execution_log.md -> .agent/collaboration/execution_log_WOT-2026-019p.md
 M .agent/collaboration/work_plan.md
 M tests/unit/test_run_gates_dispatch.py
?? .agent/collaboration/AUDIT_WOT-2026-019k.md
?? .agent/collaboration/execution_log.md
```

`scripts/run_gates_dispatch.py` NO aparece: confirmado sin cambios (mutation
de la Fase 2 completamente revertida antes de este punto). Ningun archivo de
produccion fue modificado; unico archivo de codigo tocado:
`tests/unit/test_run_gates_dispatch.py`.

**Entrega: staged/modificada en disco, SIN COMMIT** (segun instruccion del
Orquestador). El commit lo decide el Orquestador.


Scope override: Falso scope-violation por over-captura de arbol limpio (patron confirmado x4): origin/main..HEAD = commits 019v+019s+019p+019k del batch; HEAD c471b8e SI contiene el FLT tests/unit/test_run_gates_dispatch.py y no ajenos fuera del batch. git status vacio.. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019p.md, <REPO_ROOT>/tests/unit/test_run_gates_dispatch.py

Manager approved canonical closeout for WOT-2026-019k