# Work Plan - WOT-2026-019b

## Metadata
- **ID:** WOT-2026-019b
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Fuga PII en el detail de "stamp ilegible" de `_read_pytest_safe_verdict`
  (OSError vuelca ruta absoluta con username).
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

`.agent/agent_controller.py`, funcion `_read_pytest_safe_verdict` (linea 2014 y ss.),
lineas 2038-2039:

except (OSError, json.JSONDecodeError) as exc:
    return {"verdict": "inconclusive", "detail": f"stamp ilegible: {exc}"}

Si la lectura del stamp (`.agent/runtime/pytest-safe/last-run.json`) falla con un
`OSError` (permiso denegado, carpeta borrada a mitad de carrera, etc.), `str(exc)`
concatena `strerror` + `errno` + la ruta absoluta (`exc.filename`), que bajo
Windows incluye C:\Users\<username>\... . Ese `detail` se propaga a
`run_quality_gates()` -> `results["warnings"]`/`summary` -> stdout y potencialmente a
logs persistidos (execution_log.md, notifications.md) segun quien consuma el detail.
Es una fuga de PII (username local) por la rama de error, analoga en espiritu a
WOT-2026-016e (que ya resolvio el mismo problema para `record_scope_override` con
`scope_gate._relativize_scope_path`).

`json.JSONDecodeError` no tiene este problema: hereda de `ValueError`, no de
`OSError`, y su `str(exc)` describe posicion/contenido del JSON invalido (linea,
columna, caracter), nunca una ruta del filesystem. Confirmar esto es parte del DoD
(no aplicar el mismo tratamiento a JSONDecodeError seria sobre-ingenieria; aplicar
distinto tratamiento a OSError es el fix correcto).

Verificacion del objetivo (comando literal, tras el fix): el test de regresion nuevo
(ver seccion Tests) fuerza un `OSError` con `exc.filename` = ruta absoluta bajo
`PROJECT_ROOT` y verifica que el `detail` devuelto por `_read_pytest_safe_verdict` NO
contiene el username del usuario (`os.environ` o `Path.home()`) ni la ruta absoluta
completa, y SI contiene `<REPO_ROOT>` o el basename del archivo. Ademas, revertir el
fix debe hacer FALLAR ese mismo test (mutation check), confirmando que el test es
gobernante y no un placebo.

## Contexto (Fase 0 del Orquestador, verificado en vivo -- fuente de verdad de este
plan; corrige la premisa original de la ficha)

- Confirmado leyendo `.agent/agent_controller.py` lineas 2036-2039: el except
  combinado `(OSError, json.JSONDecodeError)` esta exactamente donde dice la ficha, y
  el f-string `f"stamp ilegible: {exc}"` es literal.
- Demostrado en vivo que `str(OSError(...))` con `filename` seteado concatena
  `strerror` + `errno` + la ruta: p. ej. para una ruta inexistente bajo el HOME del
  usuario, el mensaje es "[Errno 2] No such file or directory: '<ruta-absoluta>'".
  `PROJECT_ROOT` (usado para construir `stamp_path`) vive bajo el home del usuario en
  esta maquina, por lo que cualquier `OSError` real al leer ese stamp arrastra el
  username.
- CORRECCION CLAVE a la premisa de la ficha original: la ficha proponia
  "relativizar con el patron 016e/`_relativize_scope_path`" asumiendo que ese helper
  vive en `agent_controller.py`. Verificado que NO es asi:
  - `_relativize_scope_path` vive en `.agent/scope_gate.py` linea 539, firma
    `_relativize_scope_path(path: str, repo_root: Path | None) -> str`. Renderiza
    "<REPO_ROOT>/" + rel.as_posix() para paths dentro de `repo_root`, y cae a
    `Path(path).name` (basename, nunca ruta absoluta) si el path no es relativizable
    o si `repo_root` es `None`.
  - `agent_controller.py` ya importa el modulo completo en la linea 52
    (`import scope_gate  # noqa: E402 - sibling module in .agent/`) y ya lo llama
    como `scope_gate.<funcion>(...)` en multiples sitios (lineas 306, 310, 326, 341,
    356, 361, 369, 373, 400, 405, 415, 431, 440, 1195). Usar
    `scope_gate._relativize_scope_path(...)` es el patron identico y NO introduce
    dependencia nueva ni import nuevo.
  - El helper toma un path (`str`), no una excepcion. NO se puede pasar `exc`
    directamente al helper. El fix correcto compone el `detail` a mano para el caso
    `OSError`: usar `exc.strerror`, `exc.errno`, y (solo si `exc.filename` no es
    `None`) el resultado de `scope_gate._relativize_scope_path(exc.filename,
    PROJECT_ROOT)`; para `json.JSONDecodeError` mantener `str(exc)` sin cambios (no
    tiene el problema, y cambiarlo perderia informacion de diagnostico util --
    linea/columna del JSON invalido).
- Busqueda en `tests/` (grep -rln "_read_pytest_safe_verdict\|stamp ilegible"
  tests/): un unico archivo, `tests/test_agent_controller.py`. Leidas las 9
  referencias a `_read_pytest_safe_verdict` en ese archivo (clase `TestRunQualityGates`,
  lineas 324-509): existen tests que mockean el valor de retorno de
  `_read_pytest_safe_verdict` (verdict green/red/inconclusive) para probar
  `run_quality_gates()`, y un test que escribe un `last-run.json` real para probar la
  degradacion por cobertura parcial
  (`test_read_pytest_safe_verdict_partial_coverage_is_inconclusive`, lineas 455-509).
  Ninguno de los tests existentes cubre la rama except (OSError,
  json.JSONDecodeError) ni el caso "stamp ilegible" -- confirmado con grep, 0
  ocurrencias de "ilegible" salvo el propio codigo de produccion. El test de
  regresion de este ticket es net-new, no hay riesgo de duplicar cobertura.
- `PROJECT_ROOT` es una constante ya definida en `agent_controller.py` (usada en la
  linea 2033 para construir `stamp_path`); el fix y el test deben reusarla, no
  hardcodear otra ruta.

## Files Likely Touched

### repo_motor

- `.agent/agent_controller.py` (fix: separar el manejo de `OSError` de
  `json.JSONDecodeError` en `_read_pytest_safe_verdict`, lineas 2036-2039)
- `tests/test_agent_controller.py` (test de regresion nuevo en la clase
  `TestRunQualityGates`, junto a
  `test_read_pytest_safe_verdict_partial_coverage_is_inconclusive`)

## Read/inspect only (Manager-only / no tocar)

- `.agent/scope_gate.py` (fuente de `_relativize_scope_path`, linea 539-557; se
  llama, no se edita)

## Plan de Implementacion

### PASO 1 (IMPLEMENT) - `.agent/agent_controller.py`

Que cambia: reescribir el bloque try/except de las lineas ~2036-2039 de
`_read_pytest_safe_verdict` para que `OSError` y `json.JSONDecodeError` se manejen en
excepts separados:

- `except json.JSONDecodeError as exc:` -> mantener el comportamiento actual
  (detail = f"stamp ilegible: {exc}"), sin cambios de fondo.
- `except OSError as exc:` -> construir un `detail` que NO contenga la ruta absoluta:
  usar `exc.strerror` y `exc.errno`, y si `exc.filename` esta poblado, adjuntar
  `scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)` (nunca
  `exc.filename` crudo ni `str(exc)`).

Cambio MINIMO: no tocar el resto de la funcion (las ramas de `head_sha`, `tested_sha`,
`level`/`args_mode`, `exit_code` permanecen intactas byte a byte). No tocar ningun
otro except/f-string en el archivo (los ~16 restantes son follow-up 019d explicito,
fuera de scope de este ticket).

Restricciones:
- NO modificar la firma ni el docstring de `_read_pytest_safe_verdict` mas alla de lo
  estrictamente necesario para documentar el nuevo comportamiento del except (si el
  Builder anade una linea al docstring explicando el fix, debe ser breve y no alterar
  el contrato documentado de verdict/detail ya descrito).
- NO tocar `.agent/scope_gate.py` (`_relativize_scope_path` se usa tal cual existe,
  no se modifica su firma ni su comportamiento).
- NO barrer otros usos de {exc}/str(exc) en `agent_controller.py` fuera de estas
  dos lineas (ese es el scope explicito de 019d, un ticket futuro, NO este).
- NO cambiar la visibilidad de los warnings de WOT-2026-016x (siguen imprimiendose a
  stdout tal cual).
- NO tocar la rama verde/roja del verdict (green/red), solo la rama
  inconclusive que nace del except de lectura del stamp.

DoD Paso 1:
- [ ] El except de OSError ya NO puede emitir una ruta absoluta local (ni via
      str(exc) ni via exc.filename crudo): usa
      scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT) cuando
      exc.filename existe.
- [ ] El except de json.JSONDecodeError sigue devolviendo f"stamp ilegible:
      {exc}" sin cambios de fondo.
- [ ] El resto de _read_pytest_safe_verdict (ramas head_sha, tested_sha,
      level/args_mode, exit_code) no cambia (diff no debe tocarlas).
- [ ] ruff check .agent/agent_controller.py y
      ruff format --check .agent/agent_controller.py exit 0.

### PASO 2 (IMPLEMENT) - `tests/test_agent_controller.py`

Que cambia: anadir un test de regresion nuevo en la clase TestRunQualityGates
(mismo bloque que test_read_pytest_safe_verdict_partial_coverage_is_inconclusive,
siguiendo su mismo patron de tmp_path/monkeypatch sobre
agent_controller.PROJECT_ROOT y agent_controller reimportado localmente):

1. Forzar que la lectura del stamp (Path.read_text o la ruta completa de
   stamp_path.read_text(...)) lance un OSError con filename seteado a una ruta
   absoluta DENTRO de PROJECT_ROOT (monkeypatch de pathlib.Path.read_text, o
   del metodo puntual que usa _read_pytest_safe_verdict, verificar en el codigo
   real cual es el punto exacto de monkeypatch mas quirurgico: la llamada es
   stamp_path.read_text(encoding="utf-8") en la linea 2037).
2. Llamar ac._read_pytest_safe_verdict() y capturar detail.
3. Aserciones:
   - detail NO contiene ningun componente de la ruta absoluta completa que
     exc.filename traia (ni el nombre del usuario/HOME, verificable comparando
     contra str(Path.home()) o el segmento de usuario si la maquina de CI lo
     expone; como minimo, detail no debe contener la cadena literal de la ruta
     absoluta simulada).
   - detail SI contiene "<REPO_ROOT>" (o el basename del archivo si el path
     simulado cae fuera de PROJECT_ROOT -- pero el caso principal del test debe
     estar DENTRO de PROJECT_ROOT para ejercer la rama de relativizacion).
4. Verificacion mutation (documentar en execution_log.md, NO dejar el codigo
   revertido en el commit final): revertir temporalmente el fix del Paso 1 (volver al
   except (OSError, json.JSONDecodeError) as exc combinado con f"stamp ilegible:
   {exc}") y confirmar que el test nuevo FALLA (la ruta absoluta reaparece en
   detail); restaurar el fix y confirmar que vuelve a pasar. Citar literalmente el
   resultado de ambas corridas (pytest -k del test nuevo) en execution_log.md.

Restricciones:
- Seguir el estilo/patron de fixtures ya usado por
  test_read_pytest_safe_verdict_partial_coverage_is_inconclusive (mismo
  tmp_path, mismo monkeypatch.setattr(ac, "PROJECT_ROOT", tmp_path) o equivalente
  si ese es el patron real -- confirmar leyendo el test existente completo antes de
  escribir el nuevo, para no reinventar un fixture distinto sin necesidad).
- NO borrar ni modificar ningun test existente de TestRunQualityGates.
- El test nuevo debe ser deterministico (no depender del username real de la
  maquina que ejecuta CI) -- construir la ruta absoluta simulada dentro de
  tmp_path, no asumir un valor fijo de C:\Users\<algo>.

DoD Paso 2:
- [ ] Test nuevo anadido en TestRunQualityGates, pasa en verde tras el fix.
- [ ] Revertir el fix del Paso 1 hace FALLAR el test nuevo (mutation check
      documentado en execution_log.md con la salida literal de pytest).
- [ ] Ningun test existente de tests/test_agent_controller.py se rompe (correr la
      clase completa TestRunQualityGates, no solo el test nuevo).
- [ ] ruff check tests/test_agent_controller.py y
      ruff format --check tests/test_agent_controller.py exit 0.

### PASO 3 (VERIFY) - Verificacion final combinada

Comandos (Builder ejecuta, cita salida literal en execution_log.md):

.venv\Scripts\python.exe -m pytest tests/test_agent_controller.py -k "TestRunQualityGates" -v
ruff check .agent/agent_controller.py tests/test_agent_controller.py
ruff format --check .agent/agent_controller.py tests/test_agent_controller.py

Y la suite canonica completa antes de mark-ready (obligatoria para el stamp que lee
_read_pytest_safe_verdict en el propio gate -- dogfooding):

.venv\Scripts\python.exe scripts/run_pytest_safe.py

## Quality Gates

- Builder ejecuta:
  - .venv\Scripts\python.exe -m pytest tests/test_agent_controller.py -k
    "TestRunQualityGates" -v (exit 0, incluyendo el test de regresion nuevo).
  - ruff check .agent/agent_controller.py tests/test_agent_controller.py (exit 0).
  - ruff format --check .agent/agent_controller.py tests/test_agent_controller.py
    (exit 0).
  - .venv\Scripts\python.exe scripts/run_pytest_safe.py (suite completa, stamp
    fresco sobre HEAD; requisito para que el propio gate de pre-handoff/manager vea
    verdict: green).
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - .venv\Scripts\python.exe .agent\agent_controller.py --validate --json
    --project-root .

## STOP conditions

- Si el Builder descubre que el punto de monkeypatch mas quirurgico para forzar el
  OSError NO es stamp_path.read_text(...) sino otro (p. ej. stamp_path.exists()
  ya filtra antes de llegar al try, o hace falta interceptar Path.read_text a
  nivel de clase): documentarlo en execution_log.md con prefijo hipotesis: si no
  esta 100% verificado, y ajustar el test sin cambiar el objetivo del DoD.
- Si scope_gate._relativize_scope_path no esta accesible como
  scope_gate._relativize_scope_path (p. ej. cambio de nombre/firma desde el
  diagnostico de este plan): DETENTE y escala, no inventes un helper propio
  duplicado en agent_controller.py.
- Si el fix del Paso 1 rompe cualquier test YA existente de TestRunQualityGates (no
  solo el nuevo): DETENTE, el cambio no es tan minimo como se penso, escala antes de
  seguir.

## Non-goals

- NO barrer los demas str(exc)/{exc} de .agent/agent_controller.py (~16
  ocurrencias adicionales fuera de esta funcion) -- eso es el ticket follow-up 019d,
  explicitamente NO este.
- NO cambiar la visibilidad de los warnings de WOT-2026-016x (siguen impresos a
  stdout).
- NO tocar la rama verde/roja del verdict de _read_pytest_safe_verdict.
- NO modificar .agent/scope_gate.py ni la firma de _relativize_scope_path.

## Riesgos

- Bajo: cambio quirurgico de una funcion de 2 lineas dentro de un helper de
  diagnostico (_read_pytest_safe_verdict), sin tocar la logica de decision
  green/red/inconclusive salvo el texto del detail en un unico sub-caso de error.
  Blast radius acotado a un mensaje de warning/log, reversible trivialmente con git.
- Bajo-medio: el punto exacto de monkeypatch para forzar OSError en la lectura del
  stamp puede requerir iteracion (interceptar Path.read_text vs.
  stamp_path.read_text) -- mitigado con la STOP condition explicita arriba
  (documentar hipotesis, no bloquear el ticket por esto).
- Bajo: json.JSONDecodeError no hereda de OSError (hereda de ValueError) --
  confirmado en el diagnostico; el except OSError nuevo NO debe capturar
  accidentalmente JSONDecodeError (Python los distingue correctamente por MRO, pero
  el Builder debe verificar con un test que ambos excepts siguen disparando cada uno
  para su tipo, no solo el caso OSError).

## Decision Arquitectonica

Componer el detail de OSError a mano (strerror + errno + path relativizado) en
vez de intentar pasar la excepcion completa a scope_gate._relativize_scope_path
porque el helper esta disenado para recibir un path: str, no una excepcion; forzar
la firma del helper para aceptar excepciones acoplaria scope_gate.py (modulo
generico de scope) a la forma especifica de OSError, lo cual es peor diseno que
extraer exc.filename en el sitio de uso (agent_controller.py) y pasar solo el
string al helper existente, sin tocar scope_gate.py.

## Decision sobre REVIEW

Single-review basta (no se exige Review 2 adversarial). Justificacion:
- Blast radius acotado a un unico sub-caso de error en una funcion diagnostica; no
  toca logica de negocio del verdict green/red, ni bus, ni hooks, ni CI.
- El fix reusa un helper ya existente y probado (scope_gate._relativize_scope_path,
  con su propia cobertura de tests de WOT-2026-016e), no introduce logica nueva de
  relativizacion.
- Riesgo residual (mutation check del test nuevo + no romper tests existentes de
  TestRunQualityGates) queda cubierto por DoD explicito y gates automatizados
  (pytest focal + ruff + suite canonica completa).
- Prioridad Baja de la ficha original, deliverable_type=code de blast radius minimo.

## Criterios de Aceptacion Global (1:1 con el criterio binario de la ficha)

- [ ] El except de OSError en _read_pytest_safe_verdict ya NO puede emitir una
      ruta absoluta local en detail (usa scope_gate._relativize_scope_path sobre
      exc.filename cuando existe).
- [ ] El except de json.JSONDecodeError no cambia de comportamiento (str(exc)
      sigue siendo seguro, confirmado no hereda de OSError).
- [ ] Test de regresion nuevo en tests/test_agent_controller.py (clase
      TestRunQualityGates) que fuerza el OSError y verifica ausencia de ruta
      absoluta en detail.
- [ ] Mutation check documentado: revertir el fix hace fallar el test nuevo.
- [ ] ruff check y ruff format --check exit 0 sobre ambos archivos tocados.
- [ ] .venv\Scripts\python.exe scripts/run_pytest_safe.py verde (stamp fresco sobre
      HEAD, level=all, exit_code=0).
- [ ] .venv\Scripts\python.exe .agent\agent_controller.py --validate --json
      --project-root . exit 0/0 tras el cierre.

