# AUDIT - WOT-2026-016c

**Ticket:** WOT-2026-016c - Gate interno de agent_controller (uv run pytest, timeout 120s)
auto-rechaza el ticket con un mensaje falso de "Tests fallando"; la causa real es que uv no
arranca pytest en este entorno (fallo instantaneo), no un timeout de repos grandes.
**Estado del plan:** APPROVED

## TP Check

- TP-01: verificado - las 3 fases son secuenciales sin contradiccion: Fase 1 re-verifica el
  diagnostico en vivo antes de tocar codigo, Fase 2 aplica el fix (runner + captura de
  TimeoutExpired) sobre el mismo bloque que Fase 1 releyo, Fase 3 anade tests con mutation
  sobre el fix de Fase 2. Ninguna fase pide crear y revertir el mismo cambio en el mismo
  paso; la unica reversion (mutation) es una barrera de verificacion explicita y transitoria,
  documentada como tal, no una contradiccion de alcance.
- TP-02: verificado - cada criterio de aceptacion tiene un verificador literal: el criterio 1
  y 2 citan el nombre de test exacto (o "nombre equivalente documentado en execution_log.md"
  como clausula de tolerancia de naming, no de contenido), el criterio 4 cita "git diff
  acotado a esas lineas", el criterio 6 cita el comando pytest completo con flags, el
  criterio 7 cita el mensaje de summary exacto esperado ("[OK] Pytest: Tests OK"), los
  criterios 8-10 citan comandos de ruff/suite/validate con su exit code esperado.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos concretos sin
  comodines (.agent/agent_controller.py, tests/test_agent_controller.py), cada uno con el
  bloque/clase exacta que se toca. El Diagnostico y la Decision Arquitectonica delimitan
  explicitamente que NO se toca (el bloque de ruff, scripts/run_pytest_safe.py,
  _check_quality_gates, determine_next_action) para que el Builder no derive scope.
- TP-04: verificado - no aparece lenguaje blando tipo "si procede" u "opcionalmente" en el
  flujo critico. La unica clausula condicional del plan ("si el Builder identifica...
  anotarlo en execution_log.md para que el Manager decida") esta en Non-goals y decide
  explicitamente NO implementar nada en este ticket bajo esa condicion -- no delega alcance,
  cierra la decision (no se hace) y solo delega la ACCION DE REGISTRO, que no es alcance de
  codigo.
- TP-05: verificado - plan y audit describen la misma secuencia (re-verificacion en vivo,
  fix de runner + TimeoutExpired, tests con mutation), los mismos 2 archivos de Files
  Likely Touched y los mismos criterios de cierre (mutation en 2 sub-cambios, regresion cero,
  evidencia end-to-end, ruff, suite canonica, validate). Los Blockers de este AUDIT usan los
  mismos verbos que las Fases del PLAN (fijar el runner, capturar TimeoutExpired, anadir los
  tests con mutation).
- TP-06: no aplica como anti-patron (este propio TP Check usa la forma canonica TP-01..TP-07,
  no criterios de diseno del entregable).
- TP-07: verificado - no hay clausulas condicionales de alcance tipo "si existe" o "si
  aplica" decidiendo que se entrega; la unica condicional de Fase 1 ("si el comportamiento
  difiere... escalar al Manager") no decide alcance de entrega, es un gate de seguridad que
  detiene el ticket si la premisa verificada deja de sostenerse, con accion explicita
  (escalar) en vez de una decision de alcance abierta al Builder.

## Blockers

- Ninguno identificado en fase de planificacion. El Manager debe verificar en review que:
  1. El diff de .agent/agent_controller.py toca UNICAMENTE el bloque de pytest dentro de
     run_quality_gates (~2049-2063): el comando cambia a [sys.executable, "-m", "pytest",
     "-q"] y el except pasa a capturar (subprocess.TimeoutExpired, FileNotFoundError). El
     bloque de ruff (~2034-2047), la firma de run_quality_gates, _check_quality_gates y
     determine_next_action no tienen diff.
  2. Los 3 tests nuevos (o los nombres equivalentes documentados) existen en
     tests/test_agent_controller.py y verifican exactamente lo que dicen los criterios 1,
     2 y 3: comando con sys.executable/-m/pytest (no uv/run/pytest), timeout NO reportado
     como "[FAIL] Pytest: Tests fallando" y NO forzando passed=False, fallo real de pytest
     (returncode != 0 sin excepcion) SI reportado como "[FAIL] Pytest: Tests fallando" con
     passed=False.
  3. La evidencia de mutation (rojo sin fix / verde con fix) aparece en execution_log.md
     con el comando literal usado, para AMBOS sub-cambios por separado (runner y captura de
     TimeoutExpired) -- no basta una unica mutation combinada si el plan pide verificar cada
     sub-cambio de forma independiente.
  4. La evidencia end-to-end (criterio 7) aparece en execution_log.md: una corrida real de
     run_quality_gates() (o del flujo de manager-approve/--validate) sobre este repo, con el
     uv roto tal como esta en la maquina de desarrollo, muestra passed=True y
     "[OK] Pytest: Tests OK" -- no solo el resultado de los tests mockeados, sino la
     confirmacion de que el sintoma original (AUTO-REJECT espurio) ya no reproduce.
  5. TODA la suite de tests/test_agent_controller.py (no solo los tests nuevos) sigue en
     100% passed tras el fix -- en particular test_run_quality_gates_returns_dict y toda la
     clase TestAutoRejectQualityGates (que mockean run_quality_gates completo o
     agent_controller.subprocess de forma generica y no deben romperse por el cambio interno
     del comando).
  6. Si el Builder detecta que la redundancia entre run_quality_gates y
     scripts/run_pytest_safe.py merece un ticket de seguimiento, NO la implementa en este
     ticket (Non-goal explicito); solo la anota en execution_log.md para que el Manager
     decida.

## Evidencia esperada al cierre

- .venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -k RunQualityGates -v
  -> passed, cubriendo los 3 escenarios nuevos (runner canonico, timeout no reportado como
  fallo, fallo real si reportado) mas el test preexistente
  test_run_quality_gates_returns_dict.
- .venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -v -> 100% passed, sin
  regresion en TestAutoRejectQualityGates ni en ningun otro test de la clase.
- Evidencia mutation (2 sub-cambios documentados por separado en execution_log.md):
  (a) revertir el comando a ["uv", "run", "pytest", "-q"] -> el test del criterio 1 falla;
  reaplicar -> verde. (b) revertir el except a solo FileNotFoundError -> el test del
  criterio 2 falla; reaplicar -> verde.
- Evidencia end-to-end en execution_log.md: salida literal (stdout/summary) de una corrida
  de run_quality_gates() sobre este repo con el uv roto, mostrando
  "[OK] Pytest: Tests OK" y passed=True -- confirmando que el AUTO-REJECT espurio original
  ya no ocurre bajo las condiciones reales de esta maquina.
- git diff .agent/agent_controller.py acotado al bloque ~2049-2063 (pytest) sin tocar el
  bloque de ruff (~2034-2047) ni ninguna otra funcion del archivo.
- ruff check y ruff format --check sobre .agent/agent_controller.py y
  tests/test_agent_controller.py -> 0 errores.
- scripts/run_pytest_safe.py --level all -> exit 0, sin state-leak sobre
  .agent/collaboration/.
- .agent/agent_controller.py --validate --json --project-root . -> exit 0, 0 errors, 0
  warnings.
- Commit(s) del ticket con ID WOT-2026-016c y autor noreply (convencion vigente de la
  sesion), sin PII en el mensaje ni en el diff.
