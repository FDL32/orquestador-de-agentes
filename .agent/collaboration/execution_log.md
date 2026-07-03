# Execution Log - WOT-2026-016c

**Ticket:** WOT-2026-016c - gate interno run_quality_gates usa `uv run pytest` (roto en este
entorno) y reporta timeout/error de runner como "Tests fallando" (AUTO-REJECTED espurio).
**Estado:** IN_PROGRESS
**HEAD al inicio:** 7af63b4
**delivery_authority:** repo_motor | **deliverable_type:** code

> execution_log de WOT-2026-016t (COMPLETED) preservado en
> `execution_log_WOT-2026-016t.md` antes de este bootstrap.

## Fase 0 - Diagnostico (Orquestador + Manager, EJECUTADO, reproducido EN VIVO)

- Premisa del backlog ("timeout 120s en repos grandes") DOBLEMENTE FALSA.
- Causa raiz real: `run_quality_gates` (.agent/agent_controller.py ~2049-2063) corre
  `subprocess.run(["uv","run","pytest","-q"], timeout=120)`. En este entorno `uv run pytest`
  FALLA EN ~0.06s con returncode 1 ("Failed to canonicalize script path"; VIRTUAL_ENV=miniconda3
  desalineado del .venv). NO es timeout. `.venv/Scripts/python.exe -m pytest` da returncode 0
  (suite 3467+ passed). El resto del repo usa `sys.executable` como runner (run_pytest_safe.py:166).
- El mensaje `[FAIL] Pytest: Tests fallando` es ENGAÑOSO: los tests no fallan, el runner uv no
  arranca. Marca passed=False -> AUTO-REJECTED.
- El bloque pytest solo captura `except FileNotFoundError`, NO `subprocess.TimeoutExpired`
  (el patron correcto ya existe en 3 sitios del archivo: ~1437, ~1521, ~3457).
- Reproducido 2x EN VIVO esta sesion: bloqueo el manager-approve de 016s (revirtio el
  **Estado:** del execution_log a IN_PROGRESS) e intermitente en 016t.
- Decision del usuario: runner canonico (sys.executable) + capturar TimeoutExpired + mensaje
  honesto (distinguir timeout/runner-error de test-failure real).

## Fase 1 - Re-verificacion del diagnostico (Builder, EJECUTADO)

- Localizado por CONTENIDO (no solo numero de linea) en `.agent/agent_controller.py`:
  - `def run_quality_gates(...)` en linea 2014 (coincide con el plan).
  - Bloque ruff: lineas 2034-2047 (`["uv", "run", "ruff", "check", *dirs_to_check]`,
    `except FileNotFoundError:`). Coincide con el plan, NO se toca.
  - Bloque pytest: lineas 2049-2063, dentro de `if tests_dir.exists():` (linea 2049),
    `subprocess.run(["uv", "run", "pytest", "-q"], capture_output=True, timeout=120,
    cwd=PROJECT_ROOT)` (linea 2051-2056), `except FileNotFoundError:` unico (linea 2062).
    Coincide EXACTO con el diagnostico del plan.
  - `import sys` confirmado en linea 30 del archivo (`import subprocess` en linea 29).
    Ambos ya importados a nivel de modulo -- no hace falta anadir imports.
  - Patron existente `except (subprocess.TimeoutExpired, FileNotFoundError):` ya presente
    en 3 sitios: lineas 1437, 1521 (con `# noqa: PERF203`), 3457. Confirma que el bloque
    pytest (unico con `except FileNotFoundError:` solo) es la excepcion inconsistente.
- Reproducido EN VIVO (comandos literales, cwd = repo root):
  - `uv run pytest -q --co` -> returncode 1, `real 0m0.055s` (medido con `time`), stderr:
    `warning: VIRTUAL_ENV=C:\Users\fdl\miniconda3 does not match the project environment
    path .venv...` + `Failed to canonicalize script path`. Confirma: NO es timeout (120s),
    es fallo instantaneo del runner uv.
  - `.venv/Scripts/python.exe -m pytest --co -q` -> returncode 0, `real 0m1.464s`,
    salida final: `3487 tests collected in 0.90s`. Confirma: el interprete canonico
    recolecta la suite sin problema.
- Conclusion: el comportamiento coincide 100% con lo descrito en el work_plan. No hay
  divergencia que escalar al Manager. Se procede a Fase 2 (fix).

## Fase 2 - Fix del runner y captura de TimeoutExpired (Builder, EJECUTADO)

- Cambiado el comando del bloque pytest (linea ~2051-2052) de
  `["uv", "run", "pytest", "-q"]` a `[sys.executable, "-m", "pytest", "-q"]`.
- Cambiado `except FileNotFoundError:` (linea ~2062) a
  `except (subprocess.TimeoutExpired, FileNotFoundError) as exc:`, distinguiendo con
  `isinstance(exc, subprocess.TimeoutExpired)`:
  - TimeoutExpired: `results["warnings"].append(f"[WARN] Pytest: timeout tras {exc.timeout}s
    (no es fallo de tests)")`. NO se toca `results["passed"]` en esta rama (queda True si
    nada mas lo puso en False), replicando la semantica actual de FileNotFoundError.
  - FileNotFoundError: mensaje sin cambios, `results["summary"].append("[WARN] Pytest: No
    instalado")`.
- El bloque de ruff (2034-2047) queda sin diff (verificado con `git diff` acotado, ver
  gates mas abajo).
- `results["passed"]` solo se fuerza a False en la rama `if pytest_result.returncode != 0:`
  del try (pytest SI corrio y devolvio fallo real), confirmado por inspeccion del diff.

## Fase 3 - Tests + mutation-verify (Builder, EJECUTADO)

Ver seccion "Tests nuevos" y "MUTATION-VERIFY" mas abajo para el detalle completo con
comandos literales y exit codes.

## Tests nuevos (TestRunQualityGates, tests/test_agent_controller.py)

Anadidos 3 tests nuevos junto a `test_run_quality_gates_returns_dict` (linea 327,
existente, sin modificar):
1. `test_run_quality_gates_uses_canonical_python_interpreter_for_pytest`: mockea
   `agent_controller.subprocess.run` (MagicMock returncode=0 para ambas llamadas),
   captura `call_args_list`, filtra la llamada cuyo comando contiene "pytest" y afirma
   que `cmd[0] == sys.executable`, `cmd[1] == "-m"`, `cmd[2] == "pytest"` y que
   `cmd[:3] != ["uv", "run", "pytest"]`. Tambien afirma `passed is True` y
   `"[OK] Pytest"` en el summary.
2. `test_run_quality_gates_pytest_timeout_is_not_reported_as_test_failure`: side_effect
   que devuelve returncode=0 para ruff y lanza `subprocess.TimeoutExpired(cmd=cmd,
   timeout=120)` para pytest. Afirma `passed is True` (ruff paso, timeout no fuerza
   False), que algun mensaje en summary+warnings contiene "timeout" (case-insensitive)
   y que NINGUNO contiene el texto exacto "[FAIL] Pytest: Tests fallando".
3. `test_run_quality_gates_pytest_real_failure_reports_tests_fallando`: side_effect que
   devuelve returncode=0 para ruff y returncode=1 (SIN excepcion) para pytest. Afirma
   `passed is False` y que el summary SI contiene "[FAIL] Pytest: Tests fallando".

Gate: `.venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -k
RunQualityGates -v` -> **4 passed** (los 3 nuevos + el preexistente), exit 0.

## Regresion completa + hallazgo de state-leak preexistente (NO introducido por este ticket)

`.venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -v` con el arbol
actual (work_plan.md/execution_log.md/STATE.md/TURN.md modificados, proyecciones vivas
del propio ticket en curso) da **8 failed, 115 passed**. Los 8 fallos son EXCLUSIVAMENTE
en `TestPreHandoff` (7) y `TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff`
(1), todos con el mismo sintoma: `[ERROR] Pre-handoff blocked:
.agent/collaboration/work_plan.md is not committed`.

Verificado que es un state-leak PREEXISTENTE, no causado por el fix de este ticket:
- `git stash push -u` (guarda TODOS los cambios, incl. `.agent/agent_controller.py` y
  `tests/test_agent_controller.py`) -> arbol queda IDENTICO a HEAD (limpio).
- `.venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -k "TestPreHandoff
  or TestBuilderBriefExclusion" -v` sobre el arbol limpio -> **17 passed, 0 failed**,
  exit 0.
- `git stash pop` -> cambios restaurados byte a byte (confirmado con `git status
  --porcelain`, mismos 6 modified + 2 untracked que antes del stash).
- Conclusion: estas clases leen el estado REAL de `git status`/`git diff` del repo (no
  usan un `tmp_path` git-aislado), por lo que solo pasan con arbol limpio. Esto coincide
  con el patron ya documentado en memoria de sesion ("test-isolation evidence bug",
  WOT-2026-018b) de tests que quedan clavados rojos por leer estado real en vez de un
  fixture aislado. NO es responsabilidad de este ticket (Non-goal: no se toca
  TestPreHandoff ni el guard de pre-handoff); se anota como deuda para que el Manager
  decida si abre seguimiento.
- Verificacion aislada equivalente sin state-leak:
  `.venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -k "not
  TestPreHandoff and not TestBuilderBriefExclusion" -v` -> **106 passed, 0 failed**,
  exit 0 (arbol sucio con el fix aplicado, excluyendo solo las 2 clases con la
  dependencia conocida de arbol-limpio). Esto confirma regresion cero del fix de
  016c sobre el resto de la suite del archivo.

DEUDA ANOTADA (no implementada en este ticket, Non-goal respetado): considerar que
`TestPreHandoff`/`TestBuilderBriefExclusion` usen un `tmp_path`/repo git aislado en vez
de depender de `git status` del arbol de trabajo real, para no quedar rojos cuando hay
un ticket legitimo en curso con proyecciones sin commitear.

## MUTATION-VERIFY (Blocker 3 del AUDIT: los 2 sub-cambios verificados POR SEPARADO)

Comando usado en los 3 pasos (mismo en cada uno):
`.venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -k RunQualityGates -v`

**Baseline (fix completo aplicado, antes de mutar):** 4 passed, exit 0.

### Sub-cambio 1: runner (`["uv","run","pytest","-q"]` -> `[sys.executable,"-m","pytest","-q"]`)

1. Revertido SOLO el comando (linea ~2052) a `["uv", "run", "pytest", "-q"]`, dejando la
   captura `except (subprocess.TimeoutExpired, FileNotFoundError) as exc:` intacta.
2. Comando -> **1 failed, 3 passed**, exit 1. Fallo exacto:
   `test_run_quality_gates_uses_canonical_python_interpreter_for_pytest` ->
   `AssertionError: assert 'uv' == 'C:\\...\\python.exe'` (linea 364). Los otros 3
   (incl. el de timeout y el de fallo real) siguen en verde -- el mutante SOLO rompe el
   test que blinda el sub-cambio 1, como exige el plan.
3. Restaurado el comando a `[sys.executable, "-m", "pytest", "-q"]`.
4. Comando -> **4 passed**, exit 0 (verde restaurado).

### Sub-cambio 2: captura de TimeoutExpired (`except FileNotFoundError:` ->
`except (subprocess.TimeoutExpired, FileNotFoundError) as exc:` con distincion de mensaje)

1. Revertido SOLO el except (lineas ~2062-2067) a `except FileNotFoundError:` +
   `results["summary"].append("[WARN] Pytest: No instalado")`, dejando el runner
   `[sys.executable, "-m", "pytest", "-q"]` intacto.
2. Comando -> **1 failed, 3 passed**, exit 1. Fallo exacto:
   `test_run_quality_gates_pytest_timeout_is_not_reported_as_test_failure` ->
   `subprocess.TimeoutExpired` NO controlada se propaga fuera de `run_quality_gates()`
   y aborta el test (traceback: `.agent\agent_controller.py:2051: in run_quality_gates`).
   Los otros 3 (incl. el del runner canonico y el de fallo real) siguen en verde -- el
   mutante SOLO rompe el test que blinda el sub-cambio 2.
3. Restaurado el except a `except (subprocess.TimeoutExpired, FileNotFoundError) as exc:`
   con la distincion de mensaje completa.
4. Comando -> **4 passed**, exit 0 (verde restaurado).

### Verificacion de fuente identico tras ambas mutaciones

`git diff .agent/agent_controller.py` tras restaurar ambos sub-cambios es BYTE A BYTE
identico al diff del fix original (comparado visualmente linea por linea): mismo
`+                [sys.executable, "-m", "pytest", "-q"],` y mismo bloque
`+        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:` con las 4 lineas
de distincion de mensaje. Ninguna mutacion dejo residuo.

## ITERACION tras Review 2 adversarial (REFUTA -> fix de fondo)

Review 2 (fresh-context) REFUTO el primer fix (sys.executable + timeout 120 + captura
TimeoutExpired): correcto en su micro-alcance, PERO convertia el gate de pytest en un
NO-OP silencioso (la suite canonica >120s -> SIEMPRE timeout -> passed=True nunca por
pytest) y abria un FALSO VERDE (un test que falla en suite lenta se enmascara como
timeout benigno; subprocess mata el proceso a 120s con returncode=None antes de ver el
fallo). Ademas el WARN de timeout iba a results["warnings"], que _check_quality_gates
descarta -> invisible al operador.

Decision del usuario: NO cerrar con deuda (un falso verde en un gate de proceso no es
deuda aceptable). Iterar delegando en el runner canonico.

FIX DE FONDO (reemplaza el subprocess-timeout):
- Nueva funcion `_read_pytest_safe_verdict()`: lee el stamp `.agent/runtime/pytest-safe/
  last-run.json` que escribe `scripts/run_pytest_safe.py` (corre la suite completa SIN cap
  de 120s). Devuelve verdict green|red|inconclusive:
  - green: stamp de HEAD, status finished, exit_code 0 -> passed=True, [OK].
  - red: stamp de HEAD pero exit_code != 0 -> passed=False, [FAIL] con tests fallando
    nombrados. UN FALLO REAL YA NO SE ENMASCARA (falso verde CERRADO).
  - inconclusive: stamp ausente/desalineado/no-finished -> WARN accionable VISIBLE, no
    fake-pass ni fake-fail (el pre-handoff canonico exige stamp fresco por separado).
- El gate ya NO re-corre pytest via subprocess (sin timeout artificial). Refleja la salud
  real de la suite.

Verificacion 3 escenarios (stamp sintetico): green->green, exit1+fallos->red, stamp-viejo
->inconclusive, status=running->inconclusive. CLAVE confirmada: red -> passed=False.

Tests reescritos (5, TestRunQualityGates):
- does_not_rerun_pytest_with_timeout: el gate NO invoca pytest via subprocess.
- pytest_green_from_stamp: green -> passed=True.
- real_failure_is_not_masked: red -> passed=False (el anti-falso-verde de Review 2).
- inconclusive_stamp_does_not_fake_pass: inconclusive -> WARN visible, no fake-pass.
- returns_dict (preexistente).
MUTATION: neutralizar la rama red (no forzar passed=False) -> real_failure_is_not_masked
FALLA (exit 1); restaurado -> 5 passed. Barrera anti-falso-verde viva.

Gates: ruff check All passed, ruff format aplicado, encoding exit 0, regresion
test_agent_controller (sin TestPreHandoff/BuilderBriefExclusion, deuda de estado-real)
107 passed. Dogfooding: run_quality_gates lee el stamp verde de HEAD -> [OK] Pytest suite
verde, passed=True.
