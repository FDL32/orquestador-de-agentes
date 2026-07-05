# Execution Log - WOT-2026-019a

Ticket: WOT-2026-019a - guard_paths resuelve repo-root por cwd, bloquea
Writes legitimos al repo_destino.
**Estado:** COMPLETED

## Bitacora

- Plan creado y aprobado por el Manager (2026-07-05). Fase 0 (Orquestador)
  verifico la premisa del ticket leyendo el codigo real antes de
  bootstrapear:
  - claude_guard_entry.py::resolve_repo_root (linea 37-43) resuelve
    repo_root por ancestro .claude mas cercano al cwd; con cwd=motor,
    repo_root=motor.
  - guard_paths.py::_is_protected_path/_is_within_repo (linea 100-160)
    usan UNICAMENTE ese repo_root para decidir si un path esta dentro del
    repo; un Write al repo_destino produce ValueError en relative_to ->
    bloqueado con "fuera del repo".
  - grep de AGENT_PROJECT_ROOT en 60 archivos del repo confirma que
    guard_paths.py y claude_guard_entry.py nunca la consultan hoy.
  - motor_destination_link.json de este motor ya declara
    destination_root, confirmando que el campo existe en produccion
    (patron ya usado por motor_checkpoint.py::resolve_destino_root).
- Decision de diseno: Opcion (a) -- guard_paths.py resuelve un segundo
  root (AGENT_PROJECT_ROOT o destination_root del link) internamente, sin
  tocar claude_guard_entry.py ni el bootstrap canonico. Justificacion
  completa en work_plan.md seccion "Decision Arquitectonica".
- work_plan.md, PLAN_WOT-2026-019a.md y AUDIT_WOT-2026-019a.md creados y
  commiteados (commit feebeab). execution_log.md de WOT-2026-019d
  archivado a execution_log_WOT-2026-019d.md antes del bootstrap.
- Turno reseteado a BUILDER (--reset-turn --force), ticket bootstrapeado
  en el bus (--bootstrap-ticket --json).

Pendiente: Builder implementa PASO 1/2/3 de work_plan.md y documenta aqui
la evidencia (diff, tests, mutation check, salidas de pytest/ruff/suite).

## Implementacion (Builder)

### PASO 1 -- `.agent/hooks/guard_paths.py`

- Anadida `_resolve_extra_root(repo_root: Path) -> Path | None`: lee
  `AGENT_PROJECT_ROOT` (`.strip()`, `Path(...).resolve()`, `OSError`/
  `ValueError` -> `None`); si vacia, lee
  `repo_root/.agent/config/motor_destination_link.json` (mismo patron
  fail-safe que `resolve_guard_paths`: `except (json.JSONDecodeError,
  OSError, KeyError, TypeError)` -> `None`). En ambos casos, si la ruta
  resuelta no existe en disco (`.exists()` False) -> `None` (no root
  fantasma).
- `_is_protected_path`: si el path no cuelga de `repo_root`, se intenta
  `_resolve_extra_root(repo_root)`; si resuelve y el path cuelga de ese
  extra_root, se continua (no bloqueado por "fuera del repo") con
  `effective_root = extra_root`. Si ninguno de los dos aplica, sigue
  bloqueado con el mismo mensaje "fuera del repo" (exit 2, sin cambios).
  `write_roots` se evalua contra `effective_root` (el root bajo el que
  cayo el path), no arbitrariamente contra `repo_root`.
- NO se toco `claude_guard_entry.py` ni `canonical_hook_command()` (Non-goal
  respetado). Firma publica de `_is_protected_path`/`evaluate_tool_request`
  sin cambios.

### PASO 2 -- `tests/test_guard_paths.py`

Anadida clase `TestExtraRootDestination` con los 6 tests exigidos por el
plan (nombres exactos):
1. `test_write_to_destination_via_agent_project_root_allowed`
2. `test_write_to_destination_via_link_destination_root_allowed`
3. `test_write_outside_both_roots_still_blocked` (fail-closed)
4. `test_no_extra_root_behaves_like_today` (paridad)
5. `test_malformed_agent_project_root_value_falls_back_closed`
6. `test_protected_pattern_still_blocked_in_destination` (`.env` en destino
   sigue bloqueado)

Usan directorios reales con marker `.claude` (motor/destino/outside bajo
`TEST_WORKSPACE`), `monkeypatch.setenv`/`delenv` con cleanup en
`teardown_method` (`os.environ.pop("AGENT_PROJECT_ROOT", None)`), sin
mockear `relative_to`/`resolve`. Ningun test existente fue borrado ni
modificado.

### Gates (salida literal)

`.venv\Scripts\python.exe -m pytest tests/test_guard_paths.py -v`
-> `43 passed in 0.67s` (37 existentes + 6 nuevos, todos verdes).

`.venv\Scripts\python.exe -m pytest tests/unit/test_claude_guard_entry.py -v`
-> `8 passed in 0.22s` (entry SIN modificar, confirma que no cambio de
comportamiento).

`.venv\Scripts\python.exe -m ruff check .agent/hooks/guard_paths.py tests/test_guard_paths.py`
-> `All checks passed!`

`.venv\Scripts\python.exe -m ruff format --check .agent/hooks/guard_paths.py tests/test_guard_paths.py`
-> primera pasada: `Would reformat: tests\test_guard_paths.py` (1 file
would be reformatted) -> se aplico `ruff format` (reformateo de wrapping,
sin cambio de logica) -> segunda pasada: `2 files already formatted`.
Re-corrida de `pytest tests/test_guard_paths.py -q` tras el reformat:
`43 passed in 0.70s`.

### Mutation check

Se forzo `_resolve_extra_root` a devolver siempre `None` dentro de
`_is_protected_path` (linea `extra_root = None  # MUTATION: force
_resolve_extra_root() -> None`), sustituyendo la llamada real. Resultado
de `pytest tests/test_guard_paths.py::TestExtraRootDestination -v`:

```
FAILED tests/test_guard_paths.py::TestExtraRootDestination::test_write_to_destination_via_agent_project_root_allowed
FAILED tests/test_guard_paths.py::TestExtraRootDestination::test_write_to_destination_via_link_destination_root_allowed
FAILED tests/test_guard_paths.py::TestExtraRootDestination::test_protected_pattern_still_blocked_in_destination
3 failed, 3 passed in 0.21s
```

Los 3 tests que dependen del segundo root (1, 2, y el de patron protegido
en destino -- este ultimo falla porque bajo la mutacion el destino ya ni
siquiera se reconoce como root valido, por lo que el mensaje es "fuera del
repo" en vez de "archivo protegido") FALLAN como se esperaba. Los tests
fail-closed/paridad (3 `test_write_outside_both_roots_still_blocked`, 4
`test_no_extra_root_behaves_like_today`, 5
`test_malformed_agent_project_root_value_falls_back_closed`) siguen VERDES
bajo la mutacion, confirmando que no dependen del fix.

Restaurado el codigo original (`extra_root = _resolve_extra_root(repo_root)`).
Verificado con `diff` contra copia de respaldo pre-mutacion: exit 0 (byte-
identico al fix real, sin residuo de mutacion en el archivo final). Re-corrida
completa `pytest tests/test_guard_paths.py -v` tras restaurar: `43 passed in
0.67s`.

### Criterios de Aceptacion Global -- verificacion

- [x] Test que reproduce el bloqueo actual y pasa tras el fix: tests 1 y 2,
      mutation check documentado arriba.
- [x] Test fail-closed (tercer path fuera de ambos roots): test 3, verde
      antes y despues del fix (mutation check).
- [x] `claude_guard_entry.py`/`canonical_hook_command()` no aparecen en el
      diff (confirmado con `git show --name-only` en el commit, ver reporte
      final).
- [x] `PROTECTED_PATH_PATTERNS`/`write_roots` se siguen aplicando en el
      segundo root: test 6 (`.env` en destino sigue bloqueado).
- [x] Ningun test existente roto: 43/43 en test_guard_paths.py, 8/8 en
      test_claude_guard_entry.py.
- [x] `ruff check`/`ruff format --check` exit 0 (tras aplicar reformat).
- [ ] Suite canonica `run_pytest_safe.py` -- pendiente de ejecutar tras el
      commit (ver siguiente entrada de este log / reporte final).


Scope override: Over-captura de artefactos de tickets YA CERRADOS (015p/019b/019d AUDIT/PLAN, y agent_controller.py+test_agent_controller.py que son la ENTREGA de 019d ya commiteada). Verificado con git show --name-only dfdebee f3ac1f5: 019a solo toco guard_paths.py + tests/test_guard_paths.py + execution_log + archivado de PLAN/AUDIT de 019d (churn de cierre). 0 hits de los archivos ajenos en mis commits.. Affected files: <REPO_ROOT>/.agent/agent_controller.py, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-015p.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019b.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019d.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-015p.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-019b.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-019d.md, <REPO_ROOT>/tests/test_agent_controller.py

Manager approved canonical closeout for WOT-2026-019a