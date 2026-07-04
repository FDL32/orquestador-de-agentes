# AUDIT - WOT-2026-019b

Ticket: WOT-2026-019b - Fuga PII en el detail de "stamp ilegible" de
_read_pytest_safe_verdict (OSError vuelca ruta absoluta con username).
Estado del plan: APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin contradiccion: PASO 1
  (separar except OSError/json.JSONDecodeError en agent_controller.py) -> PASO 2
  (test de regresion en tests/test_agent_controller.py) -> PASO 3 (verificacion
  combinada: pytest focal + ruff + suite canonica). Ningun paso pide crear y
  revertir el mismo contenido de forma permanente (el revert del mutation check en
  PASO 2 es explicitamente temporal y documentado, no queda en el commit final).
- TP-02: verificado - cada DoD por paso cita un comando exacto (ruff check/format
  --check con ruta exacta, pytest -k TestRunQualityGates) o un contrato de codigo
  literal (scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT), el except
  json.JSONDecodeError sin cambios). No hay criterio narrado como "se mejoro el
  mensaje" sin verificacion concreta.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos concretos
  (.agent/agent_controller.py, tests/test_agent_controller.py), cada bullet con
  ruta parseable. La seccion "Read/inspect only" delimita explicitamente que
  scope_gate.py se LLAMA pero no se edita, para que el Builder no derive scope
  hacia ese archivo.

- TP-04: verificado - no aparece lenguaje blando tipo "si procede" en el flujo
  critico. El punto de monkeypatch exacto para el test (PASO 2) tiene una STOP
  condition explicita que exige documentar con prefijo hipotesis: si no esta
  100% verificado, en vez de dejarlo ambiguo.
- TP-05: verificado - work_plan.md, PLAN_WOT-2026-019b.md y este AUDIT describen la
  misma secuencia (fix de 2 excepts separados + 1 test de regresion + verificacion
  combinada), los mismos 2 archivos de Files Likely Touched, y los mismos 7
  criterios de aceptacion global. Los Blockers de este AUDIT usan los mismos verbos
  que las restricciones del PLAN (no tocar la rama verde/roja, no barrer los
  demas str(exc), no modificar scope_gate.py).
- TP-06: no aplica como anti-patron (este TP Check usa la forma canonica
  TP-01..TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional tipo "si existe"
  / "si aplica" en Objetivo, Pasos o Criterios de Aceptacion Global del work_plan.md.
  La unica condicionalidad real (si exc.filename es None) esta resuelta
  explicitamente en el propio contrato del fix (Paso 1: solo si exc.filename no es
  None), no como decision abierta al Builder.

## Premisa de Fase 0 (verificacion independiente del Manager antes de aprobar)

Confirmado en esta sesion (2026-07-05), leyendo el codigo real ademas del
diagnostico ya citado en work_plan.md:

- .agent/agent_controller.py lineas 2036-2039 leidas directamente: el except
  combinado (OSError, json.JSONDecodeError) con f-string "stamp ilegible: {exc}" es
  exactamente como describe la ficha y el work_plan.md.
- .agent/scope_gate.py lineas 539-557 leidas completas: _relativize_scope_path(path:
  str, repo_root: Path | None) -> str existe con esa firma exacta, renderiza
  "<REPO_ROOT>/" + rel.as_posix() para paths bajo repo_root y cae a Path(path).name
  (basename) en cualquier otro caso -- confirmado que NUNCA devuelve una ruta
  absoluta cruda. Docstring del helper cita explicitamente WOT-2026-016e y el mismo
  problema de raiz (username embebido via la ruta local de Windows).

- .agent/agent_controller.py linea 52: import scope_gate confirmado presente (con
  comentario noqa E402 explicando que es modulo hermano en .agent/). Grep de
  "scope_gate." en agent_controller.py: 14 llamadas ya existentes al patron
  scope_gate.<funcion>(...) (lineas 306, 310, 326, 341, 356, 361, 369, 373, 400,
  405, 415, 431, 440, 1195) -- confirma que scope_gate._relativize_scope_path(...)
  no introduce ninguna dependencia nueva, solo replica un patron establecido.
- grep -rln de "_read_pytest_safe_verdict" y "stamp ilegible" en tests/: un unico
  archivo, tests/test_agent_controller.py. Leida la clase TestRunQualityGates
  completa (lineas 324-509): 0 tests existentes ejercitan la rama
  except (OSError, json.JSONDecodeError) -- todos los tests existentes mockean el
  return value de _read_pytest_safe_verdict directamente (verdict green/red/
  inconclusive) o escriben un last-run.json valido para probar la degradacion por
  cobertura parcial. El test nuevo de este ticket es net-new, sin riesgo de
  duplicar cobertura ya existente.
- json.JSONDecodeError hereda de ValueError (no de OSError) -- confirmado via MRO
  de Python estandar, no requiere verificacion adicional en este repo; el except
  OSError nuevo no puede capturar accidentalmente un JSONDecodeError.
- git status --short del arbol de trabajo del motor: vacio (arbol limpio antes del
  bootstrap). HEAD = 94f0fb4 == origin/main (confirmado por el contexto de cierre de
  WOT-2026-015p que precede a este ticket).

## Blockers (para el Manager en review)

- Si el except de OSError sigue permitiendo que exc.filename crudo o str(exc)
  lleguen al detail final (sin pasar por scope_gate._relativize_scope_path):
  BLOCKER critico, el objetivo de PII del ticket no se cumple.
- Si el except de json.JSONDecodeError cambia de comportamiento (deja de usar
  str(exc) directo, o pierde informacion de linea/columna del JSON): BLOCKER, fuera
  de scope y regresion de diagnostico.
- Si el diff toca cualquier otra rama de _read_pytest_safe_verdict (head_sha,
  tested_sha, level/args_mode, exit_code) o cualquier otro except/f-string del
  archivo (los ~16 restantes fuera de esta funcion): BLOCKER, scope creep explicito
  (ese barrido es 019d, no este ticket).
- Si .agent/scope_gate.py aparece modificado en el diff: BLOCKER critico, el
  contrato es "se llama, no se edita".
- Si no existe un test de regresion nuevo que fuerce el OSError real (monkeypatch)
  y verifique ausencia de ruta absoluta en detail: BLOCKER, criterio de aceptacion
  central no verificado.
- Si el mutation check (revertir el fix hace fallar el test nuevo) no esta
  documentado con salida literal en execution_log.md: BLOCKER, evidencia
  insuficiente (el test podria ser un placebo que pasa siempre).
- Si algun test YA existente de TestRunQualityGates se rompe con el cambio:
  BLOCKER, el cambio no es tan minimo como se penso.
- Si ruff check o ruff format --check fallan sobre cualquiera de los 2 archivos
  tocados: BLOCKER, gate de calidad no satisfecho.
- Si la suite canonica (run_pytest_safe.py) no queda verde con stamp fresco sobre
  HEAD antes de mark-ready: BLOCKER, el propio gate de pre-handoff no confiara en
  el resultado (dogfooding: este ticket arregla justamente el helper que lee ese
  stamp).

## Evidencia esperada en execution_log.md

- Diff final (o cita literal) del bloque except de _read_pytest_safe_verdict,
  mostrando los dos excepts separados y la llamada exacta a
  scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT).
- Cita literal del test nuevo en tests/test_agent_controller.py, con el
  monkeypatch usado para forzar el OSError y las aserciones sobre detail.
- Salida literal de pytest -k TestRunQualityGates ANTES del mutation revert
  (verde, incluyendo el test nuevo) y DESPUES del revert temporal (el test nuevo
  falla), y de nuevo tras restaurar (verde) -- las 2-3 corridas documentadas, no
  solo la final.
- Salida literal de ruff check y ruff format --check sobre
  .agent/agent_controller.py y tests/test_agent_controller.py, con exit code 0 en
  ambos.
- Salida literal (o resumen con exit_code/level/tested_commit_sha) de
  scripts/run_pytest_safe.py confirmando level=all, exit_code=0 y
  tested_commit_sha == HEAD tras el commit del fix.
- Commit sha del repo_motor que contiene el fix, citado con WOT-2026-019b en el
  mensaje.

