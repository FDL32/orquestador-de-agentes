# Work Plan - WOT-2026-016c

## Metadata
- **ID:** WOT-2026-016c
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Gate interno de agent_controller (uv run pytest) auto-rechaza el ticket con un
  mensaje falso de "Tests fallando" porque uv no arranca el script pytest en este entorno; no
  es un timeout de repos grandes.
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Corregir run_quality_gates (.agent/agent_controller.py, funcion en ~2014-2071) para que
invoque pytest con el interprete canonico del proyecto (sys.executable -m pytest, mismo
patron que scripts/run_pytest_safe.py) en vez de ["uv", "run", "pytest"], capture
subprocess.TimeoutExpired con un mensaje que la distinga de un fallo real de tests, y
reporte "Tests fallando" UNICAMENTE cuando pytest devolvio un returncode de fallo de
aserciones real -- nunca cuando el runner no pudo arrancar. Verificacion del objetivo
(comando literal): .venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -k
RunQualityGates -v pasa, y una corrida manual de run_quality_gates() sobre este repo (con
el uv roto tal como esta hoy en esta maquina) da passed=True con evidencia "[OK] Pytest:
Tests OK" en vez del "[FAIL] Pytest: Tests fallando" espurio actual.

## Diagnostico (causa raiz verificada, reemplaza la premisa del backlog)

La ficha de backlog dice: "el gate interno (uv run pytest -q, timeout 120s) auto-rechaza el
ticket por timeout en repos grandes (~3414 tests)". Verificado en vivo en esta sesion contra
el codigo y el entorno real: esa premisa es DOBLEMENTE FALSA.

- run_quality_gates (.agent/agent_controller.py:2014-2071) corre
  subprocess.run(["uv", "run", "pytest", "-q"], capture_output=True, timeout=120,
  cwd=PROJECT_ROOT) en el bloque 2049-2063.
- Reproducido en vivo: "uv run pytest -q --co" en este repo termina con returncode 1 en
  0.06 segundos (no en 120s), con el mensaje de uv "Failed to canonicalize script path"
  (mas el warning previo "VIRTUAL_ENV=...miniconda3 does not match the project environment
  path .venv"). NO es un timeout: uv no logra arrancar el script pytest como comando de
  consola en este entorno (el VIRTUAL_ENV global apunta a un miniconda desalineado del
  .venv del proyecto) y falla instantaneo.
- El runner canonico ".venv/Scripts/python.exe -m pytest --co -q" da returncode 0 y
  recolecta 3487 tests en ~1 segundo. Es el patron ya usado en el resto del repo:
  scripts/run_pytest_safe.py:141-166 (resolve_test_interpreter) resuelve el interprete
  del .venv (con fallback a sys.executable) y NUNCA usa uv run pytest; el propio
  agent_controller.py ya usa sys.executable para invocar otros scripts del repo sobre
  PROJECT_ROOT (ver linea ~2696, invocacion de pre_handoff_guard.py).
- Consecuencia real: cuando el ticket esta en READY_FOR_REVIEW, _check_quality_gates
  (linea ~2144, llamada desde determine_next_action ~2414) corre run_quality_gates, que
  marca passed=False con el mensaje enganoso "[FAIL] Pytest: Tests fallando", y
  _check_quality_gates emite AUTO-REJECTED (revierte execution_log.md a IN_PROGRESS)
  aunque los 3487 tests de la suite real pasan al 100% bajo el interprete correcto. El
  mensaje no distingue "el runner no arranco" de "un test fallo una asercion": ambos casos
  hoy producen el mismo "[FAIL] Pytest: Tests fallando".
- Gap adicional confirmado: el bloque de pytest en run_quality_gates solo captura
  except FileNotFoundError (linea 2062); NO captura subprocess.TimeoutExpired. Si el
  proceso SI llegase a colgarse hasta el timeout de 120s (escenario que la ficha original
  asumia como causa, pero que no es lo que ocurre hoy), run_quality_gates lanzaria una
  excepcion no controlada en vez de degradar a un resultado de gate con mensaje claro. El
  resto del archivo ya tiene el patron de captura correcto en otros 3 sitios
  (except (subprocess.TimeoutExpired, FileNotFoundError): en lineas ~1437, ~1521, ~3457),
  asi que el bloque de pytest es la excepcion inconsistente, no la norma.
- El bloque de ruff (linea 2035-2036, ["uv", "run", "ruff", "check", *dirs_to_check]) SI
  funciona en este entorno: verificado en vivo, "uv run ruff check tests --exit-zero" da
  returncode 0 y "All checks passed!". La diferencia es que uv run ruff invoca un binario
  Rust instalado como entry point de consola (uv lo resuelve sin pasar por "canonicalizar
  script path"), mientras que uv run pytest intenta resolver el script pytest de un modo
  que falla con el VIRTUAL_ENV desalineado de esta maquina. No hay evidencia de que ruff
  este roto; no se toca por consistencia especulativa.

## Decision Arquitectonica

- Se toca EXCLUSIVAMENTE el bloque de pytest dentro de run_quality_gates
  (.agent/agent_controller.py, lineas ~2049-2063 hoy; localizar por contenido, pueden variar
  +/- lineas). El bloque de ruff (~2034-2047) NO se modifica: reproducido en vivo que
  funciona en este entorno, y cambiarlo no tiene evidencia de bug que lo justifique dentro de
  este ticket (alcance minimo, ver Non-goals).
- El comando pytest pasa de ["uv", "run", "pytest", "-q"] a
  [sys.executable, "-m", "pytest", "-q"]. Se usa sys.executable directamente (NO se
  importa resolve_test_interpreter de scripts/run_pytest_safe.py): run_quality_gates
  ya opera sobre PROJECT_ROOT con el interprete que lanzo el propio agent_controller.py
  (mismo patron que la invocacion existente de pre_handoff_guard.py en linea ~2696), y
  acoplar agent_controller.py a un import de scripts/ para este gate interno seria mayor
  blast radius sin beneficio adicional -- run_quality_gates no tiene el escenario
  multi-repo (motor vs destino con su propio .venv) que motivo resolve_test_interpreter
  en primer lugar; corre siempre sobre el workspace activo del controller.
- El try/except del bloque pasa de except FileNotFoundError a
  except (subprocess.TimeoutExpired, FileNotFoundError) as exc:, replicando el patron ya
  usado en el resto del archivo. Dentro de cada rama se distingue el mensaje:
  - subprocess.TimeoutExpired: agrega a results["warnings"] (NO a results["errors"] ni
    fuerza passed=False solo por esto) un mensaje del tipo
    "[WARN] Pytest: timeout tras {N}s (no es fallo de tests)" (con {N} = exc.timeout), y
    dado que un timeout es una senal de "no se pudo verificar", el gate lo trata igual que
    hoy trata FileNotFoundError (no bloquea el plan, queda como warning informativo) --
    consistente con que el mensaje actual de FileNotFoundError ("[WARN] Pytest: No
    instalado") tampoco fuerza passed=False. Esto preserva la semantica existente: el gate
    solo bloquea (passed=False) cuando pytest SI corrio y devolvio evidencia real de fallo.
  - returncode != 0 (el runner SI arranco): se mantiene results["passed"] = False y el
    mensaje pasa a "[FAIL] Pytest: Tests fallando" SOLO en este camino -- sigue siendo el
    texto correcto porque aqui SI hubo una ejecucion real de pytest con fallo.
  - returncode == 0: sin cambio, "[OK] Pytest: Tests OK".
- No se cambia la firma de run_quality_gates, su valor de retorno (dict con las mismas
  claves passed/errors/summary/warnings), ni el contrato consumido por
  _check_quality_gates (linea ~2156) o determine_next_action. El AUTO-REJECT sigue
  disparandose exactamente cuando passed=False; con el fix, passed=False ya no ocurre por
  un uv roto, solo por un fallo real de pytest o de ruff.

## Fases

### Fase 1 - Re-verificacion del diagnostico (obligatoria antes de tocar codigo)
- Releer .agent/agent_controller.py: run_quality_gates (~2014), el bloque de pytest
  (~2049-2063), _check_quality_gates (~2144) y su propagacion a AUTO-REJECTED (~2156-2171).
  Confirmar que las lineas citadas siguen describiendo el mismo codigo (pueden variar +/-
  lineas por commits intermedios; localizar por contenido, no solo por numero de linea).
- Re-ejecutar en vivo y documentar el resultado en execution_log.md antes de tocar codigo:
  "uv run pytest -q --co" (esperar returncode != 0, fallo casi instantaneo, mensaje
  "Failed to canonicalize script path") y ".venv/Scripts/python.exe -m pytest --co -q"
  (esperar returncode 0). Si el comportamiento difiere de lo aqui descrito (p.ej. uv ya no
  esta roto en la maquina del Builder), documentarlo explicitamente en execution_log.md y
  escalar al Manager antes de continuar -- el fix asume que el problema es el runner, no un
  timeout real.

### Fase 2 - Fix del runner y captura de TimeoutExpired
- En run_quality_gates, dentro del bloque de pytest (~2049-2063):
  1. Cambiar el comando de ["uv", "run", "pytest", "-q"] a
     [sys.executable, "-m", "pytest", "-q"].
  2. Cambiar except FileNotFoundError: a
     except (subprocess.TimeoutExpired, FileNotFoundError) as exc: y, dentro del except,
     distinguir con isinstance(exc, subprocess.TimeoutExpired): si es timeout, agregar a
     results["warnings"] el mensaje "[WARN] Pytest: timeout tras {N}s (no es fallo de
     tests)" (N = exc.timeout); si es FileNotFoundError, mantener el mensaje existente
     "[WARN] Pytest: No instalado" sin cambios.
  3. NO modificar el bloque de ruff (~2034-2047): queda con ["uv", "run", "ruff", "check",
     *dirs_to_check] sin cambios (Decision Arquitectonica).
  4. NO modificar la condicion "if tests_dir.exists():" que envuelve el bloque, ni el
     timeout=120 (el valor del timeout no es el bug; se mantiene igual).
- Confirmar por inspeccion de diff que results["passed"] solo se fuerza a False en la
  rama de returncode != 0 del try (pytest SI corrio y fallo), nunca en la rama de
  TimeoutExpired ni en la de FileNotFoundError.

### Fase 3 - Tests (barrera + mutation)
- En tests/test_agent_controller.py, dentro o junto a la clase TestRunQualityGates
  (linea ~324, que ya contiene test_run_quality_gates_returns_dict), anadir tests nuevos
  que mockeen agent_controller.subprocess.run con un side_effect/return_value por
  escenario (patron patch("agent_controller.subprocess") ya usado en
  test_run_quality_gates_returns_dict; para fijar el comando exacto invocado, capturar los
  argumentos posicionales del mock, ej. mock_subprocess.run.call_args_list):
  1. test_run_quality_gates_uses_canonical_python_interpreter_for_pytest (o nombre
     equivalente): con subprocess.run mockeado devolviendo returncode=0 para ambas
     llamadas (ruff y pytest), verificar que la llamada correspondiente a pytest usa
     sys.executable y "-m" y "pytest" como primeros elementos del comando -- NO
     "uv"/"run"/"pytest" como lista literal.
  2. test_run_quality_gates_pytest_timeout_is_not_reported_as_test_failure (o nombre
     equivalente): mockear subprocess.run con side_effect tal que la llamada de ruff
     devuelva returncode=0 y la llamada de pytest levante
     subprocess.TimeoutExpired(cmd=[...], timeout=120). Verificar: (a) el resultado NO
     tiene results["passed"] == False causado por esta rama (si ruff paso y el unico
     evento es el timeout de pytest, passed debe ser True, replicando la semantica actual
     de FileNotFoundError que tampoco fuerza passed=False); (b) el summary/warnings
     contiene un mensaje que incluye la palabra "timeout" y NO el texto exacto
     "[FAIL] Pytest: Tests fallando".
  3. test_run_quality_gates_pytest_real_failure_reports_tests_fallando (o nombre
     equivalente): mockear subprocess.run con returncode=0 para ruff y returncode=1
     (sin excepcion) para pytest. Verificar que results["passed"] is False y que el
     summary SI contiene "[FAIL] Pytest: Tests fallando" -- este es el unico camino donde
     ese texto debe seguir apareciendo.
  4. Confirmar que test_run_quality_gates_returns_dict (ya existente, linea ~327) sigue
     pasando sin modificacion (usa patch("agent_controller.subprocess") generico, un
     MagicMock() sin side_effect especifico; su contrato -- dict con passed/summary --
     no cambia).
- Barrera MUTATION (obligatoria, CEM): revertir manualmente el cambio de comando (volver a
  ["uv", "run", "pytest", "-q"]) y confirmar que el test del punto 1 FALLA (detecta que ya
  no se usa sys.executable). Revertir por separado la captura de TimeoutExpired (volver a
  except FileNotFoundError: solo) y confirmar que el test del punto 2 FALLA (la excepcion
  no controlada se propaga o el mensaje cambia). Reaplicar ambos fixes y confirmar verde.
  Documentar el comando exacto y el resultado (rojo sin fix / verde con fix) en
  execution_log.md para cada uno de los dos sub-cambios por separado.
- Confirmar que TODA la clase TestRunQualityGates y TestAutoRejectQualityGates (linea
  ~2197, que mockea run_quality_gates a nivel de funcion completa) siguen en 100% passed
  tras el fix -- estas ultimas no deben verse afectadas porque mockean run_quality_gates
  entero, no subprocess.

## Criterios de aceptacion

1. El comando de pytest dentro de run_quality_gates usa [sys.executable, "-m", "pytest",
   "-q"] en vez de ["uv", "run", "pytest", "-q"]. Verificable por inspeccion de diff y por
   el test test_run_quality_gates_uses_canonical_python_interpreter_for_pytest (o nombre
   equivalente documentado en execution_log.md).
2. El bloque de pytest captura subprocess.TimeoutExpired ademas de FileNotFoundError, con
   un mensaje que contiene la palabra "timeout" y que NO es igual a
   "[FAIL] Pytest: Tests fallando". Un timeout NO fuerza results["passed"] = False por si
   solo (misma semantica que FileNotFoundError hoy). Verificable con
   test_run_quality_gates_pytest_timeout_is_not_reported_as_test_failure (o nombre
   equivalente).
3. Un returncode != 0 de pytest SIN excepcion (fallo real de tests) sigue produciendo
   results["passed"] is False y el mensaje "[FAIL] Pytest: Tests fallando". Verificable
   con test_run_quality_gates_pytest_real_failure_reports_tests_fallando (o nombre
   equivalente).
4. El bloque de ruff (["uv", "run", "ruff", "check", *dirs_to_check]) no tiene diff (0
   lineas modificadas) -- verificable por git diff acotado a esas lineas.
5. MUTATION: revertir el cambio de runner hace fallar el test del criterio 1; revertir por
   separado la captura de TimeoutExpired hace fallar el test del criterio 2. Evidencia
   rojo-sin-fix / verde-con-fix documentada en execution_log.md con el comando literal
   para cada sub-cambio.
6. Regresion cero: .venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -v da
   100% passed (ningun test preexistente se rompe, incluidos
   test_run_quality_gates_returns_dict y toda TestAutoRejectQualityGates).
7. Evidencia end-to-end en execution_log.md: una corrida manual de run_quality_gates()
   (o del flujo completo via --validate/manager-approve) sobre este repo, con el uv tal
   como esta hoy (roto para pytest), da passed=True con "[OK] Pytest: Tests OK" en el
   summary -- confirmando que el sintoma original (AUTO-REJECT espurio) ya no ocurre.
8. ruff check y ruff format --check sobre .agent/agent_controller.py y
   tests/test_agent_controller.py: 0 errores.
9. Suite canonica: scripts/run_pytest_safe.py --level all termina en exit 0, sin
   state-leak (.agent/collaboration/ intacto tras la corrida salvo lo que este propio
   ticket declare).
10. .agent/agent_controller.py --validate --json --project-root . termina en exit 0, 0
    errors, 0 warnings al cierre.

## Files Likely Touched

### repo_motor
- .agent/agent_controller.py (fix del runner de pytest dentro de run_quality_gates,
  bloque ~2049-2063: sys.executable -m pytest en vez de uv run pytest, captura de
  subprocess.TimeoutExpired con mensaje distinguible; no toca el bloque de ruff ni la
  firma publica de run_quality_gates ni _check_quality_gates)
- tests/test_agent_controller.py (3 tests nuevos en/junto a TestRunQualityGates: runner
  canonico, timeout no reportado como fallo, fallo real si reportado; con evidencia
  mutation)

## Non-goals

- NO reescribir run_quality_gates entero: el bloque de ruff, el bloque de
  validate_state_files, run_finalization_checks y la firma/valor de retorno de la funcion
  quedan identicos.
- NO cambiar la logica de AUTO-REJECT ni el flujo de determine_next_action:
  _check_quality_gates sigue disparando AUTO-REJECTED bajo exactamente la misma condicion
  (gate_result["passed"] is False); el fix cambia CUANDO passed es False (ya no por un uv
  roto), no la mecanica de rechazo.
- NO tocar scripts/run_pytest_safe.py: su patron (resolve_test_interpreter,
  select_test_runner) es correcto y ya funciona; run_quality_gates usa sys.executable
  directamente por las razones dadas en Decision Arquitectonica, sin importar ese modulo.
- NO cambiar el bloque de ruff (["uv", "run", "ruff", ...]): funciona en este entorno
  (verificado en vivo), no hay evidencia de bug que lo justifique dentro de este ticket.
- NO cambiar el valor de timeout=120 del subprocess de pytest: el problema no era el
  valor del timeout, era el comando que uv no podia arrancar.
- NO abrir en este ticket el follow-up de unificar run_quality_gates con
  scripts/run_pytest_safe.py (posible redundancia entre ambos runners): si el Builder lo
  identifica como deuda real durante la implementacion, anotarlo en execution_log.md para
  que el Manager decida si abre un ticket de seguimiento; no se implementa aqui.
