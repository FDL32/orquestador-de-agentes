# Execution Log - WOT-2026-016z

Ticket: WOT-2026-016z - Guard de sesion anti-contaminacion de la identidad git local
del motor (barrera preventiva, no aislamiento de fixture).
**Estado:** COMPLETED

## Bitacora

- Plan creado y aprobado por el Manager. Fase 0 (Orquestador) REFUTO la premisa
  original de la ficha (un fixture de test contamina test@test.com en la config git
  LOCAL del motor): grep exhaustivo confirmo que ningun fixture activo en tests/ opera
  con cwd sobre el motor real, y una corrida empirica de 47 tests confirmo que la
  config local del motor no cambio antes/despues. El dano historico de WOT-2026-016w
  fue manual, ya corregido. Este ticket implementa una barrera PREVENTIVA (decision del
  humano), clonando 1:1 el patron ya aprobado del bus de eventos
  (_isolate_controller_event_bus / _enforce_motor_bus_isolation /
  motor_bus_isolation_guard, tests/conftest.py:250-293, WOT-2026-007f/016h).
- Verificacion independiente del Manager antes de aprobar: git config --local
  user.email / user.name del motor real = 128408907+FDL32@users.noreply.github.com /
  FDL32 (limpios). git status --short del arbol: vacio. grep de "git config --local
  user"/"git config user" en tests/: solo tests/conftest.py (a modificar por este
  ticket) y tests/unit/test_motor_bus_isolation_barrier.py (no usa git config, solo
  opera sobre archivos en tmp_path via motor_bus_isolation_guard). Confirmado: 0
  fixtures activos mutan la identidad git del motor hoy.
- Handoff al Builder: work_plan.md, PLAN_WOT-2026-016z.md y AUDIT_WOT-2026-016z.md
  creados en .agent/collaboration/. execution_log.md previo (WOT-2026-016y, COMPLETED)
  preservado como execution_log_WOT-2026-016y.md antes de este bootstrap. TURN.md
  regenerado a BUILDER via --reset-turn --force.

## Fase 0 (Builder): diagnostico del patron a clonar

- Preflight: `--validate --json` = 0 errors / 0 warnings. STATE.md =
  `WOT-2026-016z / IN_PROGRESS`, TURN.md = BUILDER/IMPLEMENT. Confirmado antes de tocar
  codigo: `git config --local user.email` = 128408907+FDL32@users.noreply.github.com,
  `git config --local user.name` = FDL32, HEAD = 4fa8bd6 (commit del plan por el
  Manager), autor `FDL32 <128408907+FDL32@users.noreply.github.com>`.
- Modelo leido completo (tests/conftest.py:215-293): `_MOTOR_EVENTS_FILE` (constante de
  ruta bajo AGENT_DIR), `_restore_motor_bus_if_changed(events_file, before) -> bool`,
  `_enforce_motor_bus_isolation(events_file, before, nodeid) -> None` (pytest.fail
  pytrace=False si hubo cambio), fixture `motor_bus_isolation_guard` (expone el
  enforcement) y fixture autouse `_isolate_controller_event_bus` (snapshot en apertura
  del yield, enforcement en el finally).
- Constante de root reusada: `PROJECT_ROOT` (tests/conftest.py:17), tal como exige el
  plan (no crear `_MOTOR_ROOT` duplicado).
- `import subprocess` confirmado AUSENTE en tests/conftest.py antes del cambio (grep sin
  resultados). Anadido en la seccion de imports.
- `git config --local --get user.doesnotexist` (clave ausente) confirmado empiricamente:
  returncode=1, stdout vacio -> el lector interno trata returncode!=0 como None, sin
  lanzar excepcion, tal como especifica el plan.
- Modelo de test de barrera leido completo
  (tests/unit/test_motor_bus_isolation_barrier.py, 3 tests: cambia-archivo-existente /
  crea-archivo-nuevo / no-cambia-nada, cada uno usando `motor_bus_isolation_guard` +
  `pytest.raises(pytest.fail.Exception, match=...)`).
- Patron de acceso a conftest.py como modulo importable (para monkeypatchear sus
  simbolos internos sin duplicar logica) tomado de
  tests/unit/test_windows_safe_temp_runtime.py::_load_conftest (busca en sys.modules
  por `__file__`, si no esta lo carga via `importlib.util.spec_from_file_location`).

## Fase 1: implementacion (tests/conftest.py)

Anadido, clonando el patron 1:1, tras `motor_bus_isolation_guard` y antes de
`_isolate_controller_event_bus` (no se toco ninguna linea del bus):

- `import subprocess` en el bloque de imports.
- `_read_motor_git_identity() -> tuple[str | None, str | None]`: helper interno
  `_read_one(key)` que corre `subprocess.run(["git","config","--local",key],
  cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)`; returncode!=0 o
  stdout vacio -> None.
- `_write_motor_git_identity_key(key, value)`: si value es None, `git config --local
  --unset key` (returncode!=0 ignorado, ya cubierto por check=False); si no, `git
  config --local key value`.
- `_restore_motor_git_identity_if_changed(before) -> bool`: lee `after` con
  `_read_motor_git_identity()`, compara con `before`; si iguales retorna False; si
  difieren, restaura cada clave independientemente via `_write_motor_git_identity_key`
  y retorna True.
- `_enforce_motor_git_identity_isolation(before, nodeid) -> None`: si
  `_restore_motor_git_identity_if_changed(before)` retorna True, `pytest.fail(...,
  pytrace=False)` con el mensaje literal exacto pedido por el plan (interpolando
  nodeid).
- Fixture `motor_git_identity_guard` (no autouse): retorna
  `_enforce_motor_git_identity_isolation`.
- Fixture autouse `_isolate_motor_git_identity(request)`: `before =
  _read_motor_git_identity()` al abrir, `yield`, en el finally llama a
  `_enforce_motor_git_identity_isolation(before, request.node.nodeid)`. Docstring cita
  WOT-2026-016z y el hallazgo de Fase 0 (ningun fixture activo contamina hoy).

No se toco `_isolate_controller_event_bus`, `_restore_motor_bus_if_changed`,
`_enforce_motor_bus_isolation` ni `motor_bus_isolation_guard` (confirmado por
`git diff` final: unico bloque anadido es el nuevo, sin modificaciones al bloque del
bus).

## Fase 2: tests/unit/test_motor_git_identity_barrier.py (nuevo, 115 lineas)

3 tests paralelos a test_motor_bus_isolation_barrier.py, ninguno invoca `git config`
real ni toca PROJECT_ROOT: usan `_load_conftest()` (mismo patron que
test_windows_safe_temp_runtime.py) para obtener el modulo conftest ya cargado por
pytest, y `monkeypatch.setattr(conftest, "_read_motor_git_identity", ...)` /
`monkeypatch.setattr(conftest, "_write_motor_git_identity_key", ...)` para interceptar
lectura y escritura. Se llama directamente a
`motor_git_identity_guard(before_simulado, nodeid)` (antes = tupla en memoria pasada
por el test; "after" = lo que retorna el lector monkeypatcheado).

1. `test_motor_git_identity_barrier_restores_existing_value`: before=("original@...",
   "Original Name"), lector monkeypatcheado retorna after=("leaked@...", "Leaked
   Name") distinto. `pytest.raises(pytest.fail.Exception,
   match=r"test_existing_identity")` envuelve la llamada al guard; se verifica ademas
   que `_write_motor_git_identity_key` fue invocado exactamente con
   [("user.email","original@..."), ("user.name","Original Name")] (prueba que
   restaura el valor original, no el simulado).
2. `test_motor_git_identity_barrier_handles_previously_unset_value`: before=(None,
   None), after=("leaked@...","Leaked Name"). Guard falla (mismo pytest.raises) y se
   verifica que las llamadas de restauracion fueron [("user.email", None),
   ("user.name", None)] -- confirma el camino de --unset (valor None), no que se
   invente un valor.
3. `test_motor_git_identity_barrier_allows_unchanged_value`: before == after (mismo
   valor). Se llama al guard SIN pytest.raises (no debe lanzar) y se verifica que
   `_write_motor_git_identity_key` NO fue invocado (restore_calls == []).

Ningun subprocess real toco PROJECT_ROOT durante estos 3 tests (verificado leyendo el
codigo: el unico punto de entrada a git real, `_read_motor_git_identity` y
`_write_motor_git_identity_key`, esta monkeypatcheado en los 3 tests).

## Quality gates (salida real)

```
$ .venv/Scripts/python.exe -m pytest tests/unit/test_motor_git_identity_barrier.py -v
tests/unit/test_motor_git_identity_barrier.py::test_motor_git_identity_barrier_restores_existing_value PASSED [ 33%]
tests/unit/test_motor_git_identity_barrier.py::test_motor_git_identity_barrier_handles_previously_unset_value PASSED [ 66%]
tests/unit/test_motor_git_identity_barrier.py::test_motor_git_identity_barrier_allows_unchanged_value PASSED [100%]
3 passed in 0.27s
```
`git config --local user.email`/`user.name` leidos inmediatamente despues: sin cambio
(128408907+FDL32@users.noreply.github.com / FDL32).

```
$ .venv/Scripts/python.exe -m pytest tests/unit/test_motor_bus_isolation_barrier.py -v
tests/unit/test_motor_bus_isolation_barrier.py::test_motor_bus_barrier_restores_existing_file PASSED [ 33%]
tests/unit/test_motor_bus_isolation_barrier.py::test_motor_bus_barrier_removes_new_file PASSED [ 66%]
tests/unit/test_motor_bus_isolation_barrier.py::test_motor_bus_barrier_allows_unchanged_file PASSED [100%]
3 passed in 0.28s
```
No-regresion del hermano confirmada (el fixture nuevo coexiste con el del bus sin
interferencia).

```
$ .venv/Scripts/python.exe -m ruff check tests/conftest.py tests/unit/test_motor_git_identity_barrier.py
All checks passed!
```

```
$ uv run ruff format --check tests/conftest.py tests/unit/test_motor_git_identity_barrier.py
```
`uv` SI arranco en este entorno (solo warning de VIRTUAL_ENV apuntando a miniconda3,
ignorado por uv). Primera corrida: exit 1, "Would reformat:
tests\unit\test_motor_git_identity_barrier.py" (1 file would be reformatted, 1 file
already formatted). Se aplico `uv run ruff format` (sin --check) sobre ambos archivos;
reformateo real: 1 file reformatted (el test nuevo), 1 file left unchanged (conftest.py
ya estaba formateado). Re-verificacion:
```
$ uv run ruff format --check tests/conftest.py tests/unit/test_motor_git_identity_barrier.py
2 files already formatted
```
No hizo falta la sustitucion documentada en WOT-2026-016c (`.venv/Scripts/python.exe -m
ruff format --check`) porque uv SI funciono en esta sesion; se deja constancia igual
por si difiere de una corrida a otra.

Tras el reformateo se re-corrieron los 6 tests (3 barrera nuevos + 3 del bus): 6 passed
en 0.46s, sin cambios de comportamiento.

## MUTATION-VERIFY (obligatorio, tests/unit/test_motor_git_identity_barrier.py)

Procedimiento: se comento temporalmente el CUERPO de `pytest.fail(...)` dentro de
`_enforce_motor_git_identity_isolation` en tests/conftest.py (reemplazado por `pass  #
MUTATION-VERIFY WOT-2026-016z...` con el bloque `pytest.fail` comentado linea a linea),
dejando intacta la logica de deteccion/restauracion (`_restore_motor_git_identity_if_changed`
seguia ejecutandose y llamando a `_write_motor_git_identity_key`, solo el fallo se
suprimio). Ningun git real fue tocado en este paso (los tests siguen usando monkeypatch
sobre PROJECT_ROOT simulado en memoria).

(a) Con el guard revertido (`pass` en vez de `pytest.fail`), se corrio:
```
$ .venv/Scripts/python.exe -m pytest tests/unit/test_motor_git_identity_barrier.py -v
tests/unit/test_motor_git_identity_barrier.py::test_motor_git_identity_barrier_restores_existing_value FAILED
tests/unit/test_motor_git_identity_barrier.py::test_motor_git_identity_barrier_handles_previously_unset_value FAILED
tests/unit/test_motor_git_identity_barrier.py::test_motor_git_identity_barrier_allows_unchanged_value PASSED
2 failed, 1 passed in 0.29s
```
Ambos tests fallaron con `Failed: DID NOT RAISE <class 'Failed'>` en la linea del
`with pytest.raises(pytest.fail.Exception, ...)`, confirmando que sin el `pytest.fail`
real el guard deja pasar la contaminacion simulada sin protestar (la barrera es
efectivamente la pieza que produce el fallo esperado, no un artefacto casual del test).

(b) exit code de (a): **1** (capturado por separado, redirigiendo a archivo, para
evitar que un pipe intermedio enmascarara el codigo real:
`.venv/Scripts/python.exe -m pytest tests/unit/test_motor_git_identity_barrier.py -v >
mutation_a.log 2>&1; echo EXITCODE_A=$?` -> `EXITCODE_A=1`).

(c) Se restauro el bloque `pytest.fail(...)` original (se deshizo exactamente el cambio
del paso (a); `git diff -- tests/conftest.py` tras la restauracion no muestra ningun
residuo del bloque comentado, solo el diff legitimo del guard nuevo). Se re-corrio:
```
$ .venv/Scripts/python.exe -m pytest tests/unit/test_motor_git_identity_barrier.py -v
tests/unit/test_motor_git_identity_barrier.py::test_motor_git_identity_barrier_restores_existing_value PASSED
tests/unit/test_motor_git_identity_barrier.py::test_motor_git_identity_barrier_handles_previously_unset_value PASSED
tests/unit/test_motor_git_identity_barrier.py::test_motor_git_identity_barrier_allows_unchanged_value PASSED
3 passed in 0.25s
```

(d) exit code de (c): **0** (`EXITCODE_C=0`, misma tecnica de redireccion a archivo).

Identidad git del motor verificada intacta antes/durante/despues de todo el
mutation-verify: 128408907+FDL32@users.noreply.github.com / FDL32 (el mutation-verify
completo NUNCA invoco git real contra PROJECT_ROOT, solo monkeypatch en memoria).

## Suite canonica (2 corridas: pre-commit y post-commit sobre HEAD final)

Identidad ANTES de la 1a corrida (pre-commit, sobre working tree con los cambios sin
commitear): 128408907+FDL32@users.noreply.github.com / FDL32.

```
$ .venv/Scripts/python.exe scripts/run_pytest_safe.py --level all
3481 passed, 20 skipped in 355.51s (0:05:55)
```
Identidad DESPUES (misma corrida): 128408907+FDL32@users.noreply.github.com / FDL32
(sin cambio). last-run.json de esta corrida: status=finished, exit_code=0, level=all,
args_mode=default_discovery, tested_commit_sha=4fa8bd63... (HEAD del plan, antes del
commit del Builder).

Side-effect conocido (WOT-2026-016d, "suite --level all: state-leak de artefactos"): la
corrida dejo `.agent/collaboration/AUDIT_WOT-2026-016y.md` y
`.agent/collaboration/PLAN_WOT-2026-016y.md` (artefactos de un ticket YA CERRADO,
05bc284) marcados como staged-deleted (`D ` en `git status --short`). Restaurados con
`git restore --staged --worktree <ambos paths>` antes de commitear (no son parte del
diff de este ticket).

Commit del Builder: `393bc4f211a3dd19da07d1d59d3db120a3ad4190`, mensaje con
"WOT-2026-016z" (ver seccion Cierre). Autor: `FDL32
<128408907+FDL32@users.noreply.github.com>` (verificado con
`git log -1 --format="%H %an <%ae>"`). Config local tras commitear:
`git config --local user.email` = 128408907+FDL32@users.noreply.github.com,
`git config --local user.name` = FDL32 (sin cambio).

2a corrida (post-commit, sobre HEAD=393bc4f):
```
$ .venv/Scripts/python.exe scripts/run_pytest_safe.py --level all
3481 passed, 20 skipped in 378.61s (0:06:18)
```
Identidad ANTES de esta 2a corrida: 128408907+FDL32@users.noreply.github.com / FDL32.
Identidad DESPUES: 128408907+FDL32@users.noreply.github.com / FDL32 (sin cambio;
**criterio de aceptacion 4 cumplido**). last-run.json de esta corrida: status=finished,
exit_code=0, level=all, args_mode=default_discovery,
tested_commit_sha=393bc4f211a3dd19da07d1d59d3db120a3ad4190 -- **igual al HEAD del
commit final** (criterio de aceptacion 5 cumplido).

El mismo state-leak conocido (016y AUDIT/PLAN) reaparecio tras esta 2a corrida y fue
restaurado de nuevo con `git restore --staged --worktree` antes de proceder al
handoff; `git status --short` final: arbol limpio, HEAD sin cambios (393bc4f).

## Encoding

Verificado con `open(path, "rb").read().decode("utf-8")` (sin excepcion) para
`tests/conftest.py` (13749 bytes) y `tests/unit/test_motor_git_identity_barrier.py`
(4170 bytes): ambos UTF-8 valido (contenido ASCII puro, subconjunto valido de UTF-8).

## Diff final

- `tests/conftest.py`: +94 insertions (bloque nuevo de identidad git; ninguna linea
  del bloque del bus tocada). `git diff --stat`: `1 file changed, 94 insertions(+)`.
- `tests/unit/test_motor_git_identity_barrier.py`: nuevo, 115 lineas (3 tests +
  helper `_load_conftest` + docstring de modulo).

## Cierre

Commit `393bc4f` con "WOT-2026-016z" en el mensaje. Suite canonica re-corrida sobre
ese HEAD (2a corrida arriba) con tested_commit_sha coincidente. Identidad git del
motor confirmada sin cambio real en ningun punto de la sesion. Procediendo a
pre-handoff + mark-ready.


Scope override: La entrega productiva de 016z (tests/conftest.py + tests/unit/test_motor_git_identity_barrier.py, ambos en el FLT) ya esta COMMITEADA en 393bc4f (verificado con 'git show --name-only 393bc4f'), por eso no aparece en el diff no-committeado que inspecciona el scope gate. El guard de identidad git + sus 3 tests de barrera estan entregados y verdes; suite canonica verde a HEAD, config del motor intacta (noreply) tras la suite.. Affected files: <REPO_ROOT>/tests/conftest.py, <REPO_ROOT>/tests/unit/test_motor_git_identity_barrier.py
## REVIEW 2 ADVERSARIAL -> CHANGES (2026-07-04)
Blockers accionables de Review 2 (fresh-context), a corregir en re-Builder:
1. COSTE DESPROPORCIONADO (blocker principal): el fixture autouse per-test hace 4 subprocess
   git/test x 3501 tests. Medicion empirica de Rev2: tests/unit 112s CON vs 32s SIN el fixture
   (~186s de overhead en la suite completa; DUPLICA el tiempo de ~165s a ~355-378s, para siempre).
   El work_plan subestimo el coste ("2 subprocess" cuando el codigo real hace 4). FIX: migrar a
   SESSION-scope (1 snapshot al inicio + 1 verificacion en pytest_sessionfinish, ~4 subprocess
   totales), aceptando perder la atribucion del nodeid exacto (evento con 0 ocurrencias hoy).
2. ROBUSTEZ: _read_motor_git_identity no captura FileNotFoundError/OSError -> si git no esta en
   PATH, rompe los 3501 tests con error de fixture (el patron del bus no tenia esta fragilidad
   porque usa Path.read_bytes). FIX: try/except que degrade a "no verificable" en vez de romper.
3. GAP DOCUMENTAL (menor): el vector 'git -c user.email=X commit' / '--author=' produce commit
   contaminado SIN tocar la config --local -> el guard NO lo detecta. Ese patron ya se usa en el
   repo (test_completion_integration.py:116, test_agent_controller.py:471, con cwd seguro). FIX:
   documentar el gap conocido en el work_plan/AUDIT (no se cierra en este ticket).
Nota: el vector HISTORICO real de 016w (commit ordinario con --local contaminada, d4787c3->e6460b1)
SI lo cubre el guard (confirmado por reflog en Rev2). El session-scope lo sigue cubriendo.

## RE-BUILDER: correccion de los 3 blockers de Review 2 (session-scope)
- Blocker 1 (coste) RESUELTO: fixture migrado de per-test a SESSION-scope
  (_isolate_motor_git_identity_session, scope="session"). 1 snapshot al inicio + 1
  verificacion en teardown de sesion (~4 subprocess totales vs ~14000 per-test).
  Docstring documenta el trade-off con mediciones (355-378s per-test vs ~165-190s
  session) y la eleccion de fixture-teardown (no pytest_sessionfinish, que no puede
  fallar la sesion). Trade-off aceptado: se pierde la atribucion del nodeid exacto.
- Blocker 2 (robustez) RESUELTO: _read_motor_git_identity y _write_motor_git_identity_key
  envuelven subprocess en try/except (FileNotFoundError, OSError) -> degradan a
  (None,None)/no-op si git no esta en PATH, en vez de romper los 3501 tests.
- Blocker 3 (gap -c inline) DOCUMENTADO: el mensaje de pytest.fail cita el vector
  'git -c user.email=... inline' como alternativa segura; gap conocido (el guard cubre
  --local persistente, vector historico real de 016w; NO cubre -c/--author inline).
- Tests de barrera ajustados al API session-scope: 4 passed. Ruff: All checks passed.
- Config motor: noreply intacta antes y despues. Autor del re-commit: noreply.
- Note: el Builder subagente fallo por error de API (ConnectionRefused) tras aplicar los
  cambios en el working tree sin commitear; el Orquestador cierra el ciclo (verificado el
  repo real: los 3 blockers resueltos en conftest.py + test_...barrier.py).


Manager approved canonical closeout for WOT-2026-016z