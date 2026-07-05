# Work Plan - WOT-2026-019a

## Metadata
- **ID:** WOT-2026-019a
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** guard_paths acepta un segundo root explicito (AGENT_PROJECT_ROOT /
  destination_root del link) para no bloquear Writes legitimos al repo_destino
  cuando el cwd del proceso harness apunta al repo_motor.
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

El hook PreToolUse (`claude_guard_entry.py` -> `guard_paths.py`) resuelve
`repo_root` buscando el ancestro `.claude` mas cercano al cwd del proceso
harness (`resolve_repo_root`, `claude_guard_entry.py` linea 37-43) y ejecuta
`guard_paths.py` con `cwd=repo_root` (linea 102-104). Dentro de
`guard_paths.py`, `_is_protected_path` (linea 121-160) usa ese `repo_root` (o,
si es `None`, cae a `Path(os.getcwd()).resolve()`, linea 133-137) como UNICO
root valido: `_is_within_repo` (linea 100-105) hace
`path_obj.relative_to(repo_root)` y devuelve `False` (bloqueo, "fuera del
repo") por `ValueError` en cuanto el path no cuelga de ese unico root.
Cuando el cwd del proceso apunta al repo_motor (tras cualquier Bash, o en
subagentes que no heredan el cwd aparcado del repo_destino), `repo_root`
resuelve al motor. Un Write/Edit legitimo a un archivo del repo_destino
(otro repo git, con su propio `.claude`) NO cuelga del motor: `relative_to`
lanza `ValueError` y el guard bloquea con "fuera del repo", aunque
`AGENT_PROJECT_ROOT` (env var ya establecida como fuente canonica de
resolucion del project root del orquestador, `runtime/project_root.py` linea
9, 92, 106) apunte correctamente al destino, o aunque
`.agent/config/motor_destination_link.json` del motor declare ese destino en
su campo `destination_root` (patron ya usado por
`.agent/motor_checkpoint.py::resolve_destino_root`, linea 424-436).
Este ticket fija el fix MINIMO: `guard_paths.py` acepta un SEGUNDO root
valido derivado de fuentes ya oficiales del sistema (env var
`AGENT_PROJECT_ROOT`, o si no esta seteada, `destination_root` del
`motor_destination_link.json` situado en el `repo_root` resuelto por el
entry). Un Write cuenta como legitimo si cuelga de CUALQUIERA de los dos
roots (motor O destino); sigue bloqueado si no cuelga de NINGUNO
(fail-closed preservado). El resto de checks (`PROTECTED_PATH_PATTERNS`,
`PROTECTED_FILENAMES`, `write_roots`) se siguen aplicando sin cambios, y se
aplican al root efectivo bajo el que cae el path (no se relajan ni se
saltan).

## Decision Arquitectonica

(Evaluadas las 3 opciones del diagnostico de Fase 0.)

**Elegida: Opcion (a)** -- `guard_paths.py` resuelve el segundo root
internamente (dentro de `_is_protected_path`, sin cambiar su firma publica
mas alla de anadir logica interna) y lo trata como repo valido ADEMAS del
`repo_root` recibido. `claude_guard_entry.py` (el entry) y
`canonical_hook_command()` (el bootstrap hardcodeado) NO se tocan: siguen
resolviendo `repo_root` por ancestro `.claude` exactamente igual que hoy, y
lo pasan a `guard_paths.py` con `cwd=repo_root` exactamente igual que hoy.
Por que (a) y no (b) o (c):
- **(b) descartada:** pasar el destino como root explicito desde
  `claude_guard_entry.py` obligaria a anadir un argumento nuevo al comando
  que invoca `guard_paths.py` (linea 102-104) y probablemente a
  `canonical_hook_command()` (linea 69-90, el bootstrap hardcodeado que
  tambien resuelve por `.claude` y que el gate de portabilidad
  `check claude settings portability` valida ESTATICAMENTE, segun el
  docstring de linea 6-8). Cambiar el bootstrap amplia el blast-radius al
  gate de portabilidad sin necesidad: el entry NO necesita saber nada del
  destino porque `guard_paths.py` ya puede resolverlo el mismo leyendo el
  `motor_destination_link.json` bajo el `repo_root` recibido (exactamente
  igual patron que `resolve_guard_paths` ya usa para localizar el propio
  script via link, linea 46-66).
- **(c) descartada:** no aplica. El fix cabe dentro del contrato actual
  del hook (mismo comando canonico, mismo bootstrap, misma firma de
  `_is_protected_path` salvo logica interna) sin requerir una decision de
  producto o arquitectura nueva. No hay tercer root arbitrario: el segundo
  root SOLO puede ser `AGENT_PROJECT_ROOT` (env var ya oficial, propagada
  por los entry points del orquestador tras parsear `--project-root`) o el
  `destination_root` de un `motor_destination_link.json` YA presente en el
  `repo_root` resuelto (no se lee ningun archivo fuera de ese arbol, no se
  acepta ningun valor de un tercer origen).
- **(a) elegida, minimo blast-radius:** no toca `claude_guard_entry.py` (el
  entry sigue siendo exactamente el mismo binario testeado por
  `tests/unit/test_claude_guard_entry.py`), no toca
  `canonical_hook_command()` (el gate de portabilidad no necesita
  re-validarse), y el cambio vive enteramente en `guard_paths.py`
  (`_is_protected_path`/`_is_within_repo`), que ya reciben `repo_root` como
  parametro explicito (linea 125) y ya tienen su propia suite de tests
  aislada (`tests/test_guard_paths.py`).
## Contexto (Fase 0 del Orquestador, verificado leyendo el codigo real)

- `claude_guard_entry.py::resolve_repo_root` (linea 37-43): ancestro `.claude`
  mas cercano al cwd. Con cwd=motor, `repo_root`=motor. NO se toca.
- `claude_guard_entry.py::main` (linea 93-104): corre `guard_paths.py` con
  `cwd=repo_root`. NO se toca.
- `guard_paths.py::_is_protected_path` (linea 121-160): hoy usa
  UNICAMENTE el `repo_root` recibido (o `os.getcwd()` si es `None`) para
  `_is_within_repo`. El fix anade un segundo root candidato, resuelto de
  `AGENT_PROJECT_ROOT` (si esta seteada y no vacia tras `.strip()`) o, si no
  esta seteada, de `destination_root` en
  `<repo_root>/.agent/config/motor_destination_link.json` (mismo patron de
  lectura fail-safe -- `except (json.JSONDecodeError, OSError, KeyError,
  TypeError)` -- ya usado en `resolve_guard_paths`, linea 56-66, y en
  `motor_checkpoint.py::resolve_destino_root`, linea 424-436).
- `_is_within_repo` (linea 100-105): hoy comprueba un unico root. El fix
  generaliza a "esta dentro de repo_root O dentro de destino_root" sin
  cambiar el resto del pipeline de checks.
- `guard_paths.py` NO importa nada de `runtime/project_root.py` hoy (el hook
  es standalone, solo usa `os.environ.get(...)` directamente para
  `GUARD_PATHS_CONFIG`, linea 236). El fix mantiene ese mismo estilo
  autocontenido: lee `os.environ.get("AGENT_PROJECT_ROOT", "")` directamente,
  sin importar el paquete `runtime` (evita acoplar el hook standalone a
  modulos del orquestador que pueden no estar en `sys.path` cuando el hook
  se invoca desde un repo_destino externo).
- `motor_destination_link.json` de ESTE motor (`.agent/config/`) ya declara
  `destination_root` (`orquestador_de_agentes_workspace`) ademas de
  `motor_root`: confirma que el campo ya existe en produccion y no es una
  invencion del plan.
## Files Likely Touched

### repo_motor

- `.agent/hooks/guard_paths.py` (anadir resolucion del segundo root dentro
  de `_is_protected_path`/nueva funcion helper privada, y generalizar
  `_is_within_repo` o el punto de llamada para aceptar 1 o 2 roots)
- `tests/test_guard_paths.py` (tests de regresion: cwd=motor + Write al
  destino via `AGENT_PROJECT_ROOT` -> pasa; cwd=motor + Write al destino via
  `destination_root` del link -> pasa; cwd=motor + Write a un TERCER path
  fuera de ambos -> sigue bloqueado; sin `AGENT_PROJECT_ROOT` ni link ->
  comportamiento identico al actual, un unico root)

## Read/inspect only (Manager-only / no tocar)

- `.agent/hooks/claude_guard_entry.py` (entry + bootstrap; NO se modifica --
  decision de diseno explicita de esta ficha)
- `.agent/agents.json` (config de allowlist; solo se lee, `write_roots` y
  `blocked_command_patterns` no cambian de semantica)
- `.agent/motor_checkpoint.py` (fuente del patron `resolve_destino_root`;
  solo lectura para replicar el mismo estilo de lectura fail-safe del link,
  no se edita ni se importa)
- `runtime/project_root.py` (fuente de la semantica de `AGENT_PROJECT_ROOT`;
  solo lectura para confirmar el contrato del env var, NO se importa desde
  el hook)
- `tests/unit/test_claude_guard_entry.py` (cubre el entry, que no cambia;
  debe seguir en verde sin modificacion)

## Plan de Implementacion

### PASO 1 (IMPLEMENT) - `.agent/hooks/guard_paths.py`, segundo root

1. Anadir una funcion privada `_resolve_extra_root(repo_root: Path) ->
   Path | None` que:
   - Si `os.environ.get("AGENT_PROJECT_ROOT", "").strip()` es no vacio,
     devuelve `Path(esa_variable).resolve()` (fail-safe: si `Path(...)`
     lanza `OSError`/`ValueError`, devuelve `None`, NO propaga la
     excepcion).
   - Si no esta seteada, intenta leer
     `repo_root / ".agent" / "config" / "motor_destination_link.json"`
     igual que `resolve_guard_paths` (linea 56-66 de
     `claude_guard_entry.py`): si existe y es JSON valido con clave
     `destination_root` no vacia, devuelve `Path(ese_valor).resolve()`.
     Cualquier `(json.JSONDecodeError, OSError, KeyError, TypeError)` ->
     devuelve `None` (no hay segundo root, comportamiento actual sin
     cambios).
   - Si ninguna fuente resuelve, devuelve `None`.
2. Modificar `_is_within_repo` (o el punto de llamada en
   `_is_protected_path`) para aceptar el resultado de `_resolve_extra_root`
   como root ADICIONAL: el path esta "dentro del repo" si
   `path_obj.relative_to(repo_root)` funciona O (si `extra_root` no es
   `None`) `path_obj.relative_to(extra_root)` funciona. Si NINGUNO de los
   dos aplica -> sigue bloqueado con "fuera del repo" (mismo mensaje,
   mismo exit code).
3. El resto de `_is_protected_path` (filename protegido,
   `PROTECTED_PATH_PATTERNS`, `write_roots`) sigue evaluandose exactamente
   igual DESPUES de superar el check de "dentro de algun repo": no se
   relaja ningun otro check, y `write_roots` (si esta configurado) se
   evalua contra `repo_root` en el caso motor y contra `extra_root` en el
   caso destino (usar el root bajo el que el path SI cayo, no
   arbitrariamente el primero).
4. `_resolve_extra_root` se llama UNA vez por invocacion de
   `_is_protected_path` (no cambia la firma publica de
   `evaluate_tool_request` ni de `_is_protected_path`: sigue aceptando
   `repo_root: Path | None = None`).

Restricciones:
- NO modificar `claude_guard_entry.py` ni `canonical_hook_command()`.
- NO anadir un tercer origen de root ademas de `AGENT_PROJECT_ROOT` y
  `destination_root` del link (evita abrir un root arbitrario que rompa
  fail-closed).
- NO relajar `PROTECTED_PATH_PATTERNS`, `PROTECTED_FILENAMES` ni
  `write_roots` para NINGUNO de los dos roots: ambos quedan sujetos a los
  mismos checks que hoy aplica el unico root.
- NO importar `runtime.project_root` desde el hook (mantener el hook
  standalone, mismo estilo que el uso existente de
  `os.environ.get("GUARD_PATHS_CONFIG")`).
- Si `AGENT_PROJECT_ROOT` resuelve a una ruta que NO existe en disco (env
  var mal seteada), tratarla igual que "no hay segundo root" (fail-closed:
  no se crea un root fantasma que nunca bloquea nada -- ver STOP
  conditions).

DoD Paso 1:
- [ ] `_resolve_extra_root` existe, lee `AGENT_PROJECT_ROOT` primero y
      `destination_root` del link como fallback, y devuelve `None` (no
      excepciona) ante cualquier fuente ausente o malformada.
- [ ] Un Write dentro del `repo_root` (motor) sigue permitido exactamente
      igual que hoy cuando NO hay segundo root (paridad de comportamiento
      sin regresion).
- [ ] Un Write dentro del segundo root (destino, via `AGENT_PROJECT_ROOT` O
      via `destination_root` del link) deja de bloquearse con "fuera del
      repo".
- [ ] Un Write fuera de AMBOS roots sigue bloqueado con "fuera del repo"
      (mismo mensaje, exit 2).
- [ ] `PROTECTED_PATH_PATTERNS`/`PROTECTED_FILENAMES`/`write_roots` se
      siguen aplicando sobre paths que caen en CUALQUIERA de los dos roots
      (no hay bypass de esos checks para el segundo root).
- [ ] `ruff check .agent/hooks/guard_paths.py` y
      `ruff format --check .agent/hooks/guard_paths.py` exit 0.

### PASO 2 (IMPLEMENT) - `tests/test_guard_paths.py`, tests de regresion + fail-closed

Usar el patron de repos git reales (`init_git_repo`, ver
`tests/test_motor_root_gates.py` linea 23-46, y el estilo con `tmp_path` de
`tests/unit/test_claude_guard_entry.py::_make_repo`, linea 17-27): montar un
"motor" (con `.claude`) y un "destino" (con `.claude` +
`.agent/config/motor_destination_link.json` declarando
`destination_root=<destino>`), fijar cwd al motor, y ejercitar
`_is_protected_path`/`evaluate_tool_request` con `repo_root=<motor>`.

Anadir como minimo:

1. `test_write_to_destination_via_agent_project_root_allowed`: cwd/repo_root
   = motor; `monkeypatch.setenv("AGENT_PROJECT_ROOT", str(destino))`; path =
   archivo dentro de destino. HOY (antes del fix) da `blocked=True,
   "fuera del repo"`; TRAS el fix da `blocked=False`.
2. `test_write_to_destination_via_link_destination_root_allowed`: cwd/repo_root
   = motor; SIN `AGENT_PROJECT_ROOT` seteada (monkeypatch.delenv si estuviera
   presente); motor tiene `.agent/config/motor_destination_link.json` con
   `destination_root=str(destino)`; path = archivo dentro de destino. Mismo
   antes/despues que el test 1.
3. `test_write_outside_both_roots_still_blocked` (fail-closed): cwd/repo_root
   = motor; `AGENT_PROJECT_ROOT` seteada al destino; path = archivo en un
   TERCER directorio (ni motor ni destino). Debe seguir bloqueado con
   "fuera del repo" tanto ANTES como DESPUES del fix (no debe cambiar).
4. `test_no_extra_root_behaves_like_today`: cwd/repo_root = motor; SIN
   `AGENT_PROJECT_ROOT` y SIN link (o link sin `destination_root`); path
   fuera del motor. Sigue bloqueado (paridad exacta con el comportamiento
   pre-fix, ausencia de regresion cuando no hay destino declarado).
5. `test_malformed_agent_project_root_value_falls_back_closed`: `AGENT_PROJECT_ROOT`
   seteada a un valor que no resuelve a un directorio existente; path fuera
   del motor. Sigue bloqueado (no se crea un root fantasma permisivo).
6. Al menos 1 test que confirme que `PROTECTED_PATH_PATTERNS` (p. ej. un
   archivo `.env` dentro del destino) SIGUE bloqueado aunque el destino sea
   un root valido (no bypass de los demas checks para el segundo root).

Mutation check (documentar en `execution_log.md`, no dejar reverts en el
commit final): revertir temporalmente `_resolve_extra_root` a devolver
siempre `None` (o eliminar la rama del segundo root en
`_is_within_repo`), confirmar que los tests 1 y 2 FALLAN (siguen bloqueados
hoy), confirmar que 3/4/5/6 siguen en verde (fail-closed y paridad no
dependen del fix); restaurar el fix y confirmar que los 6 (o mas) tests
pasan.

Restricciones:
- Los tests deben usar repos git reales (`init_git_repo`) o, como minimo,
  directorios reales con `.claude` marker (no mockear `Path.relative_to` ni
  `Path.resolve`).
- NO borrar ni modificar ningun test existente de `tests/test_guard_paths.py`.
- Los tests nuevos deben limpiar `AGENT_PROJECT_ROOT` del entorno tras cada
  test (usar `monkeypatch.setenv`/`monkeypatch.delenv`, nunca mutar
  `os.environ` directamente sin cleanup) para no filtrar estado entre tests.

DoD Paso 2:
- [ ] Los 6 tests (o mas) descritos arriba existen y pasan tras el fix.
- [ ] El test de regresion principal (`..._agent_project_root_allowed`)
      FALLA contra el codigo pre-fix (mutation check documentado con
      salida literal de pytest) y PASA tras el fix.
- [ ] El test fail-closed (`..._outside_both_roots_still_blocked`) pasa
      tanto ANTES como DESPUES del fix (no debe cambiar de comportamiento).
- [ ] Ningun test existente de `tests/test_guard_paths.py` se rompe
      (correr el archivo completo).
- [ ] `ruff check tests/test_guard_paths.py` y
      `ruff format --check tests/test_guard_paths.py` exit 0.

### PASO 3 (VERIFY) - Verificacion final combinada

Comandos (Builder ejecuta, cita salida literal en `execution_log.md`):

`.venv\Scripts\python.exe -m pytest tests/test_guard_paths.py -v`

`.venv\Scripts\python.exe -m pytest tests/unit/test_claude_guard_entry.py -v`
(debe seguir en verde SIN cambios: confirma que el entry no se toco).

`ruff check .agent/hooks/guard_paths.py tests/test_guard_paths.py`

`ruff format --check .agent/hooks/guard_paths.py tests/test_guard_paths.py`

Y la suite canonica completa antes de mark-ready:

`.venv\Scripts\python.exe scripts/run_pytest_safe.py`

## Quality Gates

- Builder ejecuta:
  - `.venv\Scripts\python.exe -m pytest tests/test_guard_paths.py -v` (exit
    0, incluyendo los 6+ tests nuevos).
  - `.venv\Scripts\python.exe -m pytest tests/unit/test_claude_guard_entry.py
    -v` (exit 0, SIN modificaciones -- confirma que el entry no cambio de
    comportamiento).
  - `ruff check .agent/hooks/guard_paths.py tests/test_guard_paths.py`
    (exit 0).
  - `ruff format --check .agent/hooks/guard_paths.py
    tests/test_guard_paths.py` (exit 0).
  - `.venv\Scripts\python.exe scripts/run_pytest_safe.py` (suite completa,
    stamp fresco sobre HEAD; level=all, exit_code=0).
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - `.venv\Scripts\python.exe .agent\agent_controller.py --validate --json
    --project-root .`

## STOP conditions

- Si `_resolve_extra_root` termina propagando CUALQUIER excepcion (en vez
  de devolver `None` fail-safe) ante un `AGENT_PROJECT_ROOT` malformado o un
  `motor_destination_link.json` corrupto: DETENTE, es una regresion de
  disponibilidad del hook (el guard debe seguir funcionando con un unico
  root si el segundo root no resuelve).
- Si el fix requiere tocar `claude_guard_entry.py` o
  `canonical_hook_command()` para funcionar (p. ej. porque `guard_paths.py`
  no puede acceder a `AGENT_PROJECT_ROOT` o al link con la informacion que
  ya recibe): DETENTE y escala al Manager -- esto invalidaria la premisa de
  la Opcion (a) elegida en este plan.
- Si algun test existente de `tests/test_guard_paths.py` o
  `tests/unit/test_claude_guard_entry.py` se rompe con el cambio: DETENTE,
  escala antes de forzar el test existente a pasar cambiando su asercion.
- Si el test fail-closed (path fuera de ambos roots) empieza a pasar
  (`blocked=False`) en algun escenario: DETENTE inmediatamente, es una
  regresion de seguridad critica (el guard dejaria de bloquear escrituras
  arbitrarias fuera de los repos conocidos).

## Non-goals

- NO modificar `claude_guard_entry.py` ni `canonical_hook_command()` (el
  bootstrap del hook y el gate de portabilidad que lo valida quedan
  intactos).
- NO anadir un tercer origen de root (solo `AGENT_PROJECT_ROOT` y
  `destination_root` del link).
- NO relajar `PROTECTED_PATH_PATTERNS`, `PROTECTED_FILENAMES` ni
  `write_roots` para ninguno de los dos roots.
- NO importar `runtime.project_root` desde el hook standalone.
- NO cambiar el `agents.json` de configuracion del guard (perfiles,
  `write_roots` por perfil quedan iguales).

## Riesgos

- Bajo: `_resolve_extra_root` mal implementado podria abrir un bypass de
  seguridad si no se aplican `PROTECTED_PATH_PATTERNS`/`write_roots` al
  segundo root -- mitigado con DoD explicito y un test dedicado (test 6
  del Paso 2) que verifica que el segundo root SIGUE sujeto a esos checks.
- Bajo: un `AGENT_PROJECT_ROOT` heredado de una sesion anterior (variable de
  entorno que sobrevive entre invocaciones del hook en el mismo proceso
  harness) podria ampliar el alcance del guard mas alla de lo esperado si
  apunta a un destino ya no vigente -- mitigado porque el hook siempre
  re-lee la env var en cada invocacion (no hay cache), y el test 5 cubre el
  caso de un valor que no resuelve a un directorio existente.
- Bajo: el patron de lectura del link ya existe y esta probado
  (`resolve_guard_paths`, `resolve_destino_root`); el unico codigo
  genuinamente nuevo es la generalizacion de `_is_within_repo` a 2 roots,
  cambio pequeno y cubierto por el test fail-closed.

## Decision sobre REVIEW

Single-review basta (no se exige Review 2 adversarial), condicionado a que
el test fail-closed (Paso 2, test 3) este presente y en verde. Justificacion:
- Blast-radius minimo y localizado: un unico archivo de produccion tocado
  (`.agent/hooks/guard_paths.py`), sin cambios al entry ni al bootstrap ni
  al gate de portabilidad.
- El patron de lectura fail-safe del link ya existe y esta probado en 2
  sitios del codigo (`resolve_guard_paths`, `resolve_destino_root`); no se
  introduce un mecanismo de resolucion nuevo, solo se reutiliza el mismo
  patron dentro de `guard_paths.py`.
- El criterio de aceptacion mas critico (fail-closed sobre un tercer path)
  es un test explicito y obligatorio con su propia DoD y STOP condition
  dedicada, verificable de forma binaria sin necesidad de una segunda
  pasada adversarial completa.
- Prioridad Media de la ficha original, deliverable_type=code, mismo estilo
  de fix quirurgico que 019b/019d (single-review, ya validado en el ciclo
  anterior para cambios de blast-radius comparable).

## Criterios de Aceptacion Global (1:1 con el criterio de aceptacion de la ficha)

- [ ] Existe un test que reproduce el bloqueo actual: cwd=repo_motor + Write
      a una ruta del repo_destino declarado via `AGENT_PROJECT_ROOT` (o via
      `destination_root` del link) -- ese test FALLA contra el codigo
      pre-fix (mutation check documentado) y PASA tras el fix.
- [ ] Existe un test fail-closed: Write a un tercer path fuera de AMBOS
      repos sigue bloqueado con "fuera del repo" tanto antes como despues
      del fix.
- [ ] `claude_guard_entry.py` y `canonical_hook_command()` no aparecen
      modificados en el diff final.
- [ ] `PROTECTED_PATH_PATTERNS`/`PROTECTED_FILENAMES`/`write_roots` se
      siguen aplicando sobre paths que caen en el segundo root (destino),
      no solo sobre el primero (motor).
- [ ] Ningun test existente de `tests/test_guard_paths.py` ni de
      `tests/unit/test_claude_guard_entry.py` se rompe.
- [ ] `ruff check` y `ruff format --check` exit 0 sobre ambos archivos
      tocados.
- [ ] `.venv\Scripts\python.exe scripts/run_pytest_safe.py` verde (stamp
      fresco sobre HEAD, level=all, exit_code=0).
- [ ] `.venv\Scripts\python.exe .agent\agent_controller.py --validate
      --json --project-root .` exit 0/0 tras el cierre.
