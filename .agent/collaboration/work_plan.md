# Plan de Trabajo: fixture de basetemp usa el TEMP real del sistema, no el secuestrado por conftest

## Metadata
- **ID:** WOT-2026-021b
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-09
- **delivery_authority:** repo_motor
- **Prioridad:** MEDIA
- **Asignado a:** Builder

## Objetivo
Cerrar un false-green de barrera detectado en la auditoria adversarial de cierre de
WOT-2026-020f: la clase `TestBasetempOutsideRepo` en `tests/unit/test_run_pytest_safe.py`
verifica el invariante "basetemp fuera del repo motor" contra un `tempfile.gettempdir()`
que sigue secuestrado dentro del repo por el conftest de sesion, por lo que el assert pasa
incluso si `make_run_dir` regresara a colocar el basetemp dentro del repo. Este ticket NO
reabre 020f: la produccion (`scripts/run_pytest_safe.py`) es correcta y no se toca. El fix
es exclusivamente de la barrera de test (fixture + assert).

## Contexto
`tests/conftest.py` tiene un fixture de sesion autouse (`_project_temp_environment`,
l.191-217) que redirige `tempfile.tempdir` y `os.environ["TEMP"/"TMP"/"TMPDIR"]` a
`SESSION_RUNTIME_ROOT` (l.21: `PROJECT_ROOT/tests/sandbox/test_runtime/session_<pid>`),
que esta DENTRO del repo. Esto es correcto para aislar la suite del temp real del sistema.

El fixture `_restore_real_tempdir` (`tests/unit/test_run_pytest_safe.py:929-940`) declara en
su docstring de clase (l.924-926) "these tests restore the REAL system temp to validate
production behavior", pero calcula:
```
real_temp = Path(os.environ.get("TEMP", os.environ.get("TMP", tempfile.gettempdir())))
```
(l.933-934). Como el fixture de sesion YA secuestro `os.environ["TEMP"]` antes de que este
fixture corra, `real_temp` resuelve a `SESSION_RUNTIME_ROOT` (dentro del repo), NO al TEMP
real del sistema (`C:\Users\<user>\AppData\Local\Temp` en Windows, verificado en vivo:
`SESSION_RUNTIME_ROOT.is_relative_to(PROJECT_ROOT) == True`). El fixture "restaura" el
basetemp a un valor que sigue dentro del repo.

`test_make_run_dir_in_tempdir` (l.956-964) asserta
`run_dir.is_relative_to(Path(tempfile.gettempdir()).resolve())` (l.962). Con
`tempfile.gettempdir()` apuntando dentro del repo (por el defecto anterior), este assert
PASA aunque `run_dir` este dentro del repo motor -- exactamente lo que el DoD de 020f
prohibia. La barrera es tautologica: compara `make_run_dir()` contra la misma base
secuestrada que usa internamente, en vez de contra el invariante real "fuera del repo".

## Root Cause
1. **Fixture-drift** (`tests/unit/test_run_pytest_safe.py:929-940`): el fixture lee
   `os.environ.get("TEMP", ...)` DESPUES de que `tests/conftest.py:196-207` ya sobreescribio
   esa variable de entorno con `SESSION_RUNTIME_ROOT` (dentro del repo). El docstring de la
   clase (l.925-926) afirma que se restaura "the REAL system temp", pero el mecanismo lee un
   valor ya mutado, no el original pre-secuestro.
2. **Floor-assertion tautologica** (`tests/unit/test_run_pytest_safe.py:956-964`): el assert
   compara `run_dir` contra `tempfile.gettempdir()`, la MISMA fuente que (tras el defecto 1)
   puede estar dentro del repo. El assert no puede fallar contra el invariante real
   ("fuera de `PROJECT_ROOT`"), solo contra si mismo.

## Files Likely Touched
- `tests/conftest.py` (expone `REAL_SYSTEM_TEMP` capturado a nivel de modulo, antes del secuestro del fixture de sesion)
- `tests/unit/test_run_pytest_safe.py` (fixture usa `REAL_SYSTEM_TEMP`; assert reforzado; docstring corregido)

## Forbidden Surfaces
- NO tocar `scripts/run_pytest_safe.py` (produccion ya correcta; el defecto es solo de test)
- NO alterar el secuestro existente de `os.environ`/`tempfile.tempdir` en `_project_temp_environment` (l.191-217 de `tests/conftest.py`)
- NO reordenar ni renombrar fixtures existentes de `tests/conftest.py`

## Non-goals
- No reabrir ni modificar el alcance de WOT-2026-020f
- No anadir nuevas fixtures de aislamiento de temp mas alla de `REAL_SYSTEM_TEMP`
- No cambiar `test_make_run_dir_outside_runtime_dir` (l.942-954); ese test ya verifica correctamente contra `RUNTIME_DIR`, un invariante distinto y no tautologico

## Decision Arquitectonica
`REAL_SYSTEM_TEMP` se define como constante de modulo en `tests/conftest.py`, junto a las
constantes existentes (`PROJECT_ROOT`, `AGENT_DIR`, `TEST_RUNTIME_ROOT`, `SESSION_RUNTIME_ROOT`,
l.18-21), usando exactamente el mismo calculo que hoy hace erroneamente el fixture de test:
`Path(os.environ.get("TEMP", os.environ.get("TMP", tempfile.gettempdir()))).resolve()`.

Motivo de resolverlo a nivel de modulo (import-time) y no dentro de un fixture: pytest importa
`conftest.py` completo (ejecutando su codigo de nivel de modulo) ANTES de coleccionar y
ejecutar cualquier fixture, incluido el fixture de sesion autouse `_project_temp_environment`
que hace el secuestro (l.191-217). En el momento en que Python evalua la linea de asignacion
de `REAL_SYSTEM_TEMP`, `os.environ["TEMP"]` todavia contiene el valor real del sistema
operativo (verificado en vivo por el orquestador: TEMP real fuera del repo,
`is_relative_to(PROJECT_ROOT) == False`). Es aditivo puro: una constante nueva, sin tocar el
fixture de sesion existente ni su orden.

Alternativa descartada: capturar el valor real dentro del propio fixture de sesion
(`_project_temp_environment`) en una variable de modulo poblada en su primera linea, antes de
mutar `os.environ`. Se descarta porque acopla la exposicion del valor al ciclo de vida de un
fixture (no disponible hasta que el fixture arranca, y en xdist cada worker collector ya
importa conftest antes de que el fixture corra en ese worker, por lo que el resultado es
identico pero con una dependencia de orden mas fragil). La constante de modulo es mas simple
y no tiene dependencia de fixture.

En `tests/unit/test_run_pytest_safe.py`, el fixture `_restore_real_tempdir` (l.929-940) pasa
a usar `conftest.REAL_SYSTEM_TEMP` en vez de recalcular desde `os.environ` (que esta
secuestrado en el momento en que el fixture corre). El docstring de la clase (l.924-926) se
corrige para no afirmar un mecanismo que no cumplia.

`test_make_run_dir_in_tempdir` (l.956-964) se refuerza anadiendo un assert adicional
`not run_dir.is_relative_to(PROJECT_ROOT)` (usando el `PROJECT_ROOT` ya definido en l.13 del
propio archivo) ADEMAS del assert existente contra `tempfile.gettempdir()`. Se mantienen
ambos asserts (no se sustituye uno por otro): el assert contra `gettempdir()` sigue
verificando que `make_run_dir` es consistente con el TEMP configurado, y el assert nuevo
contra `PROJECT_ROOT` es el que expresa el invariante real del DoD de 020f ("fuera del repo
motor") de forma no tautologica, porque `PROJECT_ROOT` es independiente del valor que el
fixture haya restaurado en `tempfile.tempdir`.

## Mecanismo de Mutation (DoD obligatorio)
Para demostrar que el assert nuevo es una barrera genuina y no otra tautologia, el Builder
debe ejecutar la siguiente secuencia y registrar los dos resultados literales en
`execution_log.md`:

1. Sin fix (basetemp forzado dentro del repo): con un monkeypatch temporal (dentro del
   propio test de mutation, NO en produccion) que sustituya `mod.make_run_dir` por una
   version que devuelva `mod.RUNTIME_DIR / "run-mutation-test"` (una ruta dentro de
   `PROJECT_ROOT`), ejecutar
   `run_pytest_safe.py -- tests/unit/test_run_pytest_safe.py::TestBasetempOutsideRepo::test_make_run_dir_in_tempdir -v`
   (o `pytest` directo equivalente). El assert nuevo contra `PROJECT_ROOT`
   DEBE fallar (exit code distinto de cero).
2. Con fix (basetemp real): sin el monkeypatch (comportamiento real de `make_run_dir`),
   la misma invocacion DEBE pasar (exit code 0).

Registrar el par en el formato canonico:
```
mutation-verify:
  sin_fix:  command: <cmd literal>   exit_code: <distinto de 0>
  con_fix:  command: <cmd literal>   exit_code: 0
```

## Plan de Implementacion

### Fase 1: Exponer `REAL_SYSTEM_TEMP` en conftest.py
- **Archivo:** `tests/conftest.py`
- **Accion:** Modificar
- **Descripcion:** Anadir, junto a las constantes de modulo existentes (l.18-21, antes de la
  clase `ProjectTmpPathFactory`), la linea
  `REAL_SYSTEM_TEMP = Path(os.environ.get("TEMP", os.environ.get("TMP", tempfile.gettempdir()))).resolve()`.
  No modificar `_project_temp_environment` (l.191-217) ni el orden de fixtures existente.
- **Riesgo:** Medio (conftest.py es infraestructura compartida por toda la suite; el cambio
  es aditivo -- una constante nueva, sin efecto en fixtures existentes -- pero un error de
  sintaxis o de import a nivel de modulo rompe la coleccion de TODA la suite)
- **Criterio de Aceptacion:** `python -c "import ast; ast.parse(open('tests/conftest.py', encoding='utf-8').read())"` no lanza excepcion; `REAL_SYSTEM_TEMP` es importable desde el modulo conftest cargado por pytest y su valor NO es relativo a `PROJECT_ROOT`
- **Si falla:** revertir el cambio y escalar al Manager con el traceback exacto

### Fase 2: Usar `REAL_SYSTEM_TEMP` en el fixture del test y corregir el docstring
- **Archivo:** `tests/unit/test_run_pytest_safe.py`
- **Accion:** Modificar
- **Descripcion:** En `_restore_real_tempdir` (l.929-940), reemplazar el calculo local
  (`os.environ.get("TEMP", os.environ.get("TMP", tempfile.gettempdir()))`) por una referencia
  a `conftest.REAL_SYSTEM_TEMP` (import explicito del modulo conftest de la suite, o
  reutilizando el mecanismo estandar de pytest para acceder a conftest; el Builder decide el
  import concreto sin cambiar el comportamiento resuelto). Corregir el docstring de la clase
  `TestBasetempOutsideRepo` (l.924-926) para describir el mecanismo real: usa el TEMP del
  sistema capturado en `tests/conftest.py` antes de que el fixture de sesion lo secuestre, en
  vez de afirmar que "restaura" un valor leido de `os.environ` en el momento del test.
- **Riesgo:** Bajo (cambio confinado a un fixture y un docstring de un solo archivo de test)
- **Criterio de Aceptacion:** `_restore_real_tempdir` ya no llama a
  `os.environ.get` para calcular `real_temp`; usa `REAL_SYSTEM_TEMP`. El docstring
  de la clase no describe el mecanismo viejo basado en `os.environ.get` en el momento del
  test; describe el mecanismo nuevo
- **Si falla:** revertir y escalar al Manager

### Fase 3: Anadir el segundo assert (`not is_relative_to(PROJECT_ROOT)`) a `test_make_run_dir_in_tempdir`
- **Archivo:** `tests/unit/test_run_pytest_safe.py`
- **Accion:** Modificar
- **Descripcion:** En `test_make_run_dir_in_tempdir` (l.956-964), anadir un segundo assert
  que verifique `not run_dir.is_relative_to(PROJECT_ROOT)`, con un mensaje que indique que el
  basetemp no debe estar dentro del repo motor. `PROJECT_ROOT` es la constante ya definida en
  l.13 del mismo archivo. El assert existente contra `tempfile.gettempdir()` NO se elimina.
- **Riesgo:** Bajo (un assert adicional en un test existente; no cambia produccion)
- **Criterio de Aceptacion:** el test contiene ambos asserts (contra `tempfile.gettempdir()`
  y contra `not run_dir.is_relative_to(PROJECT_ROOT)`)
- **Si falla:** revertir y escalar al Manager

### Fase 4: Mutation-verify de la barrera reforzada
- **Archivo:** `tests/unit/test_run_pytest_safe.py` (verificacion transitoria; sin test permanente nuevo)
- **Accion:** Verificar
- **Descripcion:** Ejecutar el mecanismo de mutation descrito en la seccion "Mecanismo de
  Mutation" de este plan: monkeypatch temporal de `make_run_dir` a una ruta dentro de
  `RUNTIME_DIR`/`PROJECT_ROOT` hace fallar el assert nuevo; sin el monkeypatch, el assert
  pasa. El monkeypatch se aplica y revierte dentro de la misma sesion de verificacion (por
  ejemplo, editando temporalmente el test para forzar `run_dir` a una ruta in-repo, correr,
  restaurar el archivo, correr de nuevo) sin dejar codigo de mutation permanente en el repo.
- **Riesgo:** Bajo (verificacion transitoria; el archivo se restaura a su version de Fase 3 antes de continuar)
- **Criterio de Aceptacion:** el par `mutation-verify` (sin_fix exit distinto de 0, con_fix exit 0) queda
  registrado literal en `execution_log.md` con el comando exacto usado
- **Si falla:** el assert de Fase 3 no es una barrera genuina; revisar el mecanismo y escalar al Manager antes de marcar READY_FOR_REVIEW

### Fase 5: Verificacion de no-regresion de produccion y suite completa
- **Archivo:** `scripts/run_pytest_safe.py` (solo lectura/verificacion, NO modificar); toda la suite
- **Accion:** Verificar
- **Descripcion:** (a) Confirmar que `scripts/run_pytest_safe.py` no tiene diff:
  `git diff --stat scripts/run_pytest_safe.py` debe estar vacio. (b) Ejecutar
  `ruff check tests/conftest.py tests/unit/test_run_pytest_safe.py` con resultado 0 errores.
  (c) Ejecutar la suite completa `python scripts/run_pytest_safe.py -- --level all` (o el
  comando canonico equivalente del runner seguro) con exit code 0, porque `tests/conftest.py`
  es infraestructura compartida por toda la suite y un error de orden de fixtures o de import
  solo se detecta corriendo todo, no solo el archivo tocado. (d) Ejecutar
  `python .agent/agent_controller.py --validate --json --force` con resultado 0 errores.
- **Riesgo:** Medio (blast radius de tocar conftest.py; un fallo aqui puede indicar que
  `REAL_SYSTEM_TEMP` interfiere con algun otro test que dependa del estado de
  `os.environ`/`tempfile` en el momento del import)
- **Criterio de Aceptacion:** los 4 comandos de la Descripcion terminan con el exit
  code/resultado indicado en cada caso
- **Si falla:** revertir Fase 1 (conftest) primero y aislar si el fallo viene de la nueva
  constante o de otra interaccion; escalar al Manager con el log de fallo exacto

## Trade-offs Considerados
| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Constante de modulo en conftest.py capturada a import-time | Fiable (import ocurre antes que cualquier fixture); aditiva; sin dependencia de orden de fixtures | Anade un nombre nuevo al namespace compartido de conftest | Aceptada |
| Capturar el valor real dentro del propio fixture de sesion y exponerlo via variable de modulo mutada en su primera linea | Co-localizado con el secuestro | Depende del ciclo de vida del fixture; mas fragil bajo xdist; menos simple | Descartada |
| Sustituir el assert tautologico por uno solo nuevo, sin mantener el assert contra `gettempdir()` | Mas corto | Pierde la verificacion de consistencia interna entre `make_run_dir` y `tempfile.gettempdir()` que el test original si aportaba | Descartada; se mantienen ambos asserts |

## Guia de Riesgos
| Nivel | Significado | Accion del Builder |
|-------|-------------|---------------------|
| Bajo | Rutinaria | Intentar 3 veces antes de escalar |
| Medio | Requiere atencion (conftest.py compartido) | Intentar 2 veces, escalar si dudas |
| Alto | Critica | Escalar al primer fallo |

## Calidad
- `ruff check tests/conftest.py tests/unit/test_run_pytest_safe.py` con resultado 0 errores (Fase 5b)
- `python scripts/run_pytest_safe.py -- --level all` con exit code 0 (Fase 5c)
- `python .agent/agent_controller.py --validate --json --force` con 0 errores (Fase 5d)
- `git diff --stat scripts/run_pytest_safe.py` vacio (Fase 5a)
- mutation-verify de Fase 4 registrado en `execution_log.md` con comando y exit codes literales

## Criterios de Aceptacion Global
- [ ] El fixture `_restore_real_tempdir` usa `REAL_SYSTEM_TEMP` (capturado a import-time de `tests/conftest.py`, antes del secuestro de `os.environ`) en vez de leer `os.environ` en el momento del test
- [ ] `test_make_run_dir_in_tempdir` falla con basetemp forzado dentro del repo y pasa con el basetemp real (mutation-verify literal en `execution_log.md`)
- [ ] `scripts/run_pytest_safe.py` queda bit a bit identico (sin diff)
- [ ] La suite completa (`--level all`) sigue verde
- [ ] `ruff check` y `--validate` en 0 errores
