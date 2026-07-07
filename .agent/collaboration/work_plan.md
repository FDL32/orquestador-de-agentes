# Plan de Trabajo: Captura de ERROR de teardown en run_pytest_safe

## Metadata
- **ID:** WOT-2026-016k
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-07
- **Prioridad:** LOW
- **Asignado a:** Builder

## Objetivo

Que `run_pytest_safe` capture tambièn lineas `^ERROR\s+(\S+)` del stdout de pytest y las exponga en un campo SEPARADO `error_test_ids` de `last-run.json` (no mezcladas en `failed_test_ids`). Esto evita que un ERROR de teardown produzca un fallo opaco (exit 1 + `failed_test_ids=[]`) que `pre_handoff_guard.assert_canonical_suite_green` fail-cierra como "state-leak suspected".

## Contexto

`scripts/run_pytest_safe.py` linea 461: `_failed_re = re.compile(r"^FAILED\s+(\S+)")` — solo matchea lineas `FAILED`. La funcion `stream_pytest` (l.450-510) retorna `(returncode, failed_ids)` donde `failed_ids` se construye iterando lineas y aplicando `_failed_re.match()` (l.504-510).

Un test con ERROR de teardown (no FAILED) da exit 1 con `failed_ids` VACIO -> `assert_canonical_suite_green` (pre_handoff_guard.py l.504-528) fail-cierra ante conjunto-vacio + senal-de-fallo como "state-leak suspected", indistinguible de un collection crash real o state-leak verdadero.

Evidencia verificada: WOT-2026-016h (backlog.md linea 60) confirmo `run_pytest_safe.py --level all` dio `17 passed, 5 errors`, exit 1, `failed_test_ids=[]`.

## Non-goals

- NO mezclar ERROR en `failed_test_ids` (mantener semantica FAILED != ERROR de teardown).
- NO tocar los 5 tests de `tests/test_opencode_config_stability.py` (eso fue WOT-2026-016h, ya hecho).
- NO tocar `pre_handoff_guard.py` ni `assert_canonical_suite_green` (el guard no es la causa; ampliarlo seria scope creep).

## Files Likely Touched
- `scripts/run_pytest_safe.py`
- `tests/unit/test_run_pytest_safe.py`

## Read/inspect only
- `scripts/pre_handoff_guard.py` (consumidor de failed_test_ids; entender como lee last-run.json, l.431-528)
- `tests/conftest.py` (fixture `_isolate_controller_event_bus` — verificado en backlog.md que usa `pytest.fail(pytrace=False)` en teardown -> ERROR)

## Plan de Implementacion

### Fase 0: Builder — Analizar estructura actual

#### 0.1: Analizar stream_pytest y last-run.json schema
- **Tipo:** 🤖 TAREA AGENTE
- **Archivo:** `scripts/run_pytest_safe.py`
- **Descripcion:** Confirmar la estructura actual parseada:
  - `stream_pytest` (l.450-510) retorna `(returncode, failed_ids)`.
  - `write_json(LAST_RUN_JSON, summary)` (l.925) escribe `failed_test_ids` desde `summary["failed_test_ids"] = failed_ids` (l.895).
  - No existe `_error_re` ni `error_test_ids`.
- **Riesgo:** 🟢 Bajo
- **Criterio de Aceptacion:** Builder puede enumerar exactamente donde agregar el regex de ERROR y donde escribir `error_test_ids` en el schema de last-run.json.

### Fase 1: Builder — Implementacion en run_pytest_safe.py

#### 1.1: Anadir _error_re en stream_pytest
- **Tipo:** 🤖 TAREA AGENTE
- **Archivo:** `scripts/run_pytest_safe.py`
- **Descripcion:** En `stream_pytest` (l.450-510), despues de `._failed_re` (l.461), anadir:
  ```python
  _error_re = re.compile(r"^ERROR\s+(\S+)")
  ```
  La expresion captura lineas `ERROR` del stdout de pytest (formato: `ERROR tests/foo.py::test_bar -- ...`).

- **Riesgo:** 🟢 Bajo
- **Criterio de Aceptacion:** Existencia de `_error_re` como compiled regex en `stream_pytest`.

#### 1.2: Capturar error_test_ids en stream_pytest
- **Tipo:** 🤖 TAREA AGENTE
- **Archivo:** `scripts/run_pytest_safe.py`
- **Descripcion:** En el bucle de parsing despues de `process.wait()` (l.504-510), mantener el bucle de `failed_ids` tal como esta, y agregar un nuevo bucle paralelo para `error_test_ids`:
  ```python
  error_ids: list[str] = []
  for line in lines:
      m = _error_re.match(line.rstrip())
      if m:
          error_ids.append(m.group(1))
  ```
  Cambiar return a: `return returncode, failed_ids, error_ids`
  
  Verificar todos los callers de `stream_pytest` y actualizarlos. En `main()` (l.889), el llamado actual es:
  ```python
  exit_code, failed_ids = stream_pytest(command)
  ```
  Cambiar a:
  ```python
  exit_code, failed_ids, error_ids = stream_pytest(command)
  ```
  Luego, despues de `summary["failed_test_ids"] = failed_ids` (l.895), agregar:
  ```python
  summary["error_test_ids"] = error_ids
  ```

- **Riesgo:** 🟡 Medio (cambios en firma de funcion + caller en main)
- **Criterio de Aceptacion:** `stream_pytest` retorna `(exit_code, failed_ids, error_ids)`. `main()` escribe ambos campos en `summary` antes de `write_json`.

### Fase 2: Builder — Test focal

#### 2.1: Test unitario para parsing de ERROR lines
- **Tipo:** 🤖 TAREA AGENTE
- **Archivo:** `tests/unit/test_run_pytest_safe.py`
- **Descripcion:** Anadir test dentro de la clase `TestFailedTestIdsParsing` (o nueva clase `TestErrorTestIdsParsing`) que verifique:
  1. Una linea `ERROR tests/foo.py::TestFoo::test_err -- AttributeError\n` se parsea correctamente a `["tests/foo.py::TestFoo::test_err"]`.
  2. Mixed stream con FAILED, ERROR, PASSED: FAILED va a `failed_ids`, ERROR va a `error_test_ids`, ambos separados.
  3. Stream vacio con ERROR -> `error_test_ids = []`.

#### 2.2: Test de integracion para error_test_ids en last-run.json
- **Tipo:** 🤖 TAREA AGENTE
- **Archivo:** `tests/unit/test_run_pytest_safe.py`
- **Descripcion:** Anadir test en la clase `TestFailedTestIdsInSummary` (o nueva `TestErrorTestIdsInSummary`) que use `_stub_main` con mock de `stream_pytest` retornando `(1, [], ["tests/fake.py::test_teardown_error"])` y verifique que `last-run.json` contiene `"error_test_ids": ["tests/fake.py::test_teardown_error"]` y `"failed_test_ids": []`.

- **Riesgo:** 🟢 Bajo
- **Criterio de Aceptacion:** Tests focales pasan con exit 0.

### Fase 3: Cierre y Validacion

#### 3.1: Quality gates
- **Tipo:** 🤖 TAREA AGENTE
- **Descripcion:**
  - `ruff check scripts/run_pytest_safe.py`
  - `ruff format scripts/run_pytest_safe.py`
  - `ruff check tests/unit/test_run_pytest_safe.py`
  - `ruff format tests/unit/test_run_pytest_safe.py`
  - Tests focales: `pytest tests/unit/test_run_pytest_safe.py -v`

- **Riesgo:** 🟢 Bajo

#### 3.2: Mutation-verify
- **Tipo:** 🤖 TAREA AGENTE
- **Descripcion:** Secuencia exacta:
  1. `git stash push -- scripts/run_pytest_safe.py` (revertir fix)
  2. Correr test focal de ERROR -> debe FALLAR (error_test_ids vacio con exit 1)
  3. `git stash pop` (restaurar fix)
  4. Correr test focal -> debe PASS (error_test_ids poblado)
  
  Esto verifica que la captura de ERROR es la causa real del comportamiento y no un falso positivo.

- **Riesgo:** 🟢 Bajo

## Criterios de Aceptacion Global (DoD)

- [ ] Un test que produce ERROR de teardown aparece enumerado en `error_test_ids` de `last-run.json`.
- [ ] `error_test_ids` es un campo SEPARADO de `failed_test_ids` (no mezclados).
- [ ] MUTATION: quitar la captura de ERROR -> vuelve el fallo opaco (failed_test_ids y error_test_ids vacios con exit 1).
- [ ] ruff check no reporta warnings en los archivos modificados.
- [ ] Tests focales pasan con exit 0.
- [ ] La suite canonica sigue pasando (no regression).

## Decision Arquitectonica

El fix anade un campo SEPARADO `error_test_ids` en `last-run.json` en lugar de
mezclar ERROR en `failed_test_ids`. Razon: pytest distingue semanticamente
`FAILED` (asercion del test falla) de `ERROR` (fallo de setup/teardown o
collection crash). Mezclarlos en un solo campo haria que el guard
`assert_canonical_suite_green` no pueda distinguir un state-leak opaco (exit 1
+ conjunto vacio) de un ERROR de teardown legitimo. Con `error_test_ids`
separado, el guard futuro puede decidir como tratar los ERROR sin perder la
senal de fallo. El cambio es backward-compatible: `error_test_ids` es un
campo opcional nuevo; los consumidores existentes que solo leen
`failed_test_ids` no se ven afectados.

## STOP conditions

- Si un cambio rompe tests existents en `test_run_pytest_safe.py` no relacionados con esta feature -> escalado al Manager.
- Si `stream_pytest` callers en otros archivos no encontrados -> escalado al Manager.
- Si `ruff` exige cambios de estilo que alteren la logica -> verificar con Manager antes de aplicar.

## TP Check

- TP-01: Premisa verificada contra codigo real (`scripts/run_pytest_safe.py:461`, `stream_pytest` l.450-510, `main()` l.889/895)
- TP-02: Fix mecanico: anadir `_error_re`, capturar `error_test_ids`, exponer en last-run.json
- TP-03: Tests: unit para parsing de ERROR lines + integration para campo en last-run.json
- TP-04: Mutation: revertir fix -> test ERROR falla (exit 1); restaurar -> pasa (exit 0)
- TP-05: Non-goal verificado: pre_handoff_guard NO se modifica (solo lectura)

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Campo separado `error_test_ids` | Separa semantica FAILED vs ERROR teardown, mantiene compatibilidad backward | Requiere que el guard futuro decida como tratar los ERROR | ✅ Elegida |
| Mezclar ERROR en `failed_test_ids` | Mas simple, menor impacto | Pierde semantica FAILED != ERROR teardown | Descartada (explicit non-goal) |
| Ampliar `pre_handoff_guard` para leer `error_test_ids` | El guard podria tomar decisiones basadas en ERROR | Scope creep, no es la causa raiz | Descartada (non-goal) |
