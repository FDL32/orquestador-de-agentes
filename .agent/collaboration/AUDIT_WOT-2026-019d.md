# AUDIT - WOT-2026-019d

Ticket: WOT-2026-019d - Inventario y correccion de los ~18 usos de
str(exc)/{exc}/{e} en .agent/agent_controller.py con clasificacion PII
(follow-up de WOT-2026-019b).
Estado del plan: APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin contradiccion:
  PASO 1 (separar except OSError en los 12 sitios PII-riesgo de
  agent_controller.py) -> PASO 2 (12 tests de regresion + mutation check en
  tests/test_agent_controller.py) -> PASO 3 (verificacion combinada: pytest
  completo + ruff + suite canonica). Ningun paso pide crear y revertir el
  mismo contenido de forma permanente (el revert del mutation check en PASO
  2 es explicitamente temporal y documentado, no queda en el commit final).
- TP-02: verificado - cada DoD por paso cita un comando exacto (ruff
  check/format --check con rutas exactas, pytest -m del archivo completo)
  o un contrato de codigo literal (scope_gate._relativize_scope_path con
  exc.filename y PROJECT_ROOT para cada uno de los 12 sitios, con su linea
  exacta). No hay criterio narrado como mejora de mensajes sin verificacion
  concreta.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos
  concretos (.agent/agent_controller.py, tests/test_agent_controller.py),
  cada bullet con ruta parseable, sin comodines. La tabla de clasificacion
  fija el subconjunto EXACTO de 12 lineas a corregir y 4 a documentar como
  seguras, sin dejar los demas casos como alcance abierto.
- TP-04: verificado - no aparece lenguaje blando tipo si procede en el
  flujo critico. Los casos con matiz especifico (900, 2890/2891, 1910,
  1041/1085) tienen instrucciones concretas de orden de excepts y de
  cobertura, no heuristicas libradas al Builder.
- TP-05: verificado - work_plan.md, PLAN_WOT-2026-019d.md y este AUDIT
  describen la misma secuencia (fix de 12 sitios PII-riesgo + 12 tests de
  regresion + mutation check + verificacion combinada), los mismos 2
  archivos de Files Likely Touched, y los mismos 8 criterios de aceptacion
  global. Los Blockers de este AUDIT usan los mismos verbos que las
  restricciones del PLAN (no reescribir logica, no barrer str(exc) fuera
  del archivo, no tocar scope_gate.py).
- TP-06: no aplica como anti-patron (este TP Check usa la forma canonica
  TP-01 a TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional tipo si
  existe o si aplica en Objetivo, Pasos o Criterios de Aceptacion Global
  del work_plan.md decidiendo que sitios se corrigen (la clasificacion de
  los 16 sitios esta cerrada en la tabla, no delegada al Builder). La unica
  condicionalidad real (si exc.filename es None) esta resuelta
  explicitamente en el propio contrato del fix (guard documentado en el
  patron), no como decision abierta.

## Premisa de Fase 0 (verificacion independiente del Manager antes de aprobar)

Confirmado en esta sesion (2026-07-05), leyendo el codigo real de cada uno
de los 18 sitios (no solo la tabla preliminar de la ficha):

- grep -nE del patron str(exc)/{exc}/{e}/str(e) en .agent/agent_controller.py
  confirma exactamente 18 lineas: 894, 900, 1007, 1041, 1085, 1614, 1688,
  1888, 1910, 2039 (comentario, no except real), 2049 (ya corregida por
  019b), 2219, 2890, 2891, 3459, 5342, 5895, 5925.
- Leidos los 16 bloques try/except reales completos (no solo la linea del
  except): confirmado que 12 tienen una operacion de filesystem real en su
  try (write_text, read_text, mkdir, Path.exists via pathlib con
  re-lanzamiento condicional, o subprocess.run con FileNotFoundError sobre
  un script/ejecutable local) y 4 no tienen ninguna ruta de OSError
  explotable.
- Correccion a la clasificacion preliminar de la ficha del Orquestador: la
  linea 1614 (_check_declared_deliverables_exist) estaba marcada como
  RIESGO citado por la ficha en el diagnostico inicial; verificado leyendo
  scripts/check_deliverables_exist.py lineas 338-341 que
  extract_paths_from_work_plan(content: str) es parsing puro de texto sin
  ninguna llamada a open/read_text/write_text -- reclasificada a SEGURO.
- La linea 1688 (_check_implementation_evidence) estaba marcada como
  SEGURO (git, no path repo) en el diagnostico preliminar; verificado
  leyendo bus/evidence.py completo (resolve_evidence + _run_git_cmd) que en
  efecto solo ejecuta subprocess de git con manejo interno de
  subprocess.TimeoutExpired, FileNotFoundError y OSError que devuelve set()
  vacio en error -- confirmado SEGURO, sin cambios a la clasificacion
  preliminar.
- La linea 1910 (segundo except de _validate_contract_gap_coherence) NO
  tenia clasificacion explicita en la ficha original (solo cubria 1888).
  Verificado leyendo el source real instalado de pathlib Path.exists (via
  inspect.getsource): captura OSError solo si el errno esta en la lista de
  errores ignorados (ENOENT, ENOTDIR, EBADF, ELOOP) o en los winerrors
  ignorados (3 codigos especificos de Windows); cualquier otro errno (p.
  ej. EACCES) se re-lanza con filename poblado -- clasificada RIESGO, no un
  caso trivial de exists() que nunca falla.
- La linea 3459 (except RuntimeError) confirmada SEGURO leyendo
  .agent/motor_checkpoint.py lineas 397-421: el unico raise RuntimeError
  usa un mensaje fijo tipo Cannot resolve empty seguido del nombre de una
  clave de dict (repo_motor_root, repo_destino_root,
  workspace_activo_root), nunca una ruta variable.
- git status --short del arbol de trabajo del motor: vacio (arbol limpio
  antes del bootstrap). execution_log.md de WOT-2026-019b archivado a
  execution_log_WOT-2026-019b.md antes de este bootstrap (evita
  contaminar el scope gate del nuevo ticket).

## Blockers (para el Manager en review)

- Si algun sitio de los 12 PII-riesgo sigue permitiendo que exc.filename
  crudo o str(exc) lleguen al mensaje final (sin pasar por
  scope_gate._relativize_scope_path cuando exc.filename existe): BLOCKER
  critico, el objetivo de PII del ticket no se cumple para ese sitio.
- Si el bloque 2890/2891 termina con DOS inserciones distintas de except
  OSError en vez de una sola que cubra ambos usos de exc: BLOCKER, deriva
  de la instruccion explicita del PLAN (un unico bloque except).
- Si cualquiera de los 4 sitios seguros (894, 1614, 1688, 3459) aparece
  modificado en su LOGICA (no solo un comentario de una linea): BLOCKER,
  scope creep sobre sitios ya clasificados como fuera del fix.
- Si el diff toca la logica de negocio de cualquiera de las 10 funciones
  mas alla del manejo del except y la composicion del mensaje: BLOCKER,
  fuera del non-goal explicito de no reescribir la logica de las funciones
  tocadas.
- Si .agent/scope_gate.py, bus/approval.py, bus/event_bus.py,
  bus/evidence.py, scripts/check_deliverables_exist.py,
  scripts/state_projection_sync.py o .agent/motor_checkpoint.py aparecen
  modificados en el diff: BLOCKER critico, son Read/inspect only.
- Si no existe un test de regresion nuevo (con mutation check documentado)
  por cada uno de los 12 sitios PII-riesgo (o 11 si 2890/2891 comparten
  uno solo, con esa eleccion documentada explicitamente): BLOCKER, criterio
  de aceptacion central no verificado para ese sitio.
- Si algun test YA existente de tests/test_agent_controller.py se rompe
  con el cambio: BLOCKER, el cambio no es tan quirurgico como se penso.
- Si ruff check o ruff format --check fallan sobre cualquiera de los 2
  archivos tocados: BLOCKER, gate de calidad no satisfecho.
- Si la suite canonica (run_pytest_safe.py) no queda verde con stamp
  fresco sobre HEAD antes de mark-ready: BLOCKER, el gate de pre-handoff no
  confiara en el resultado.
- Si execution_log.md no documenta la tabla de clasificacion completa (16
  sitios) con su justificacion, o no documenta el mutation check de cada
  uno de los 12 sitios PII-riesgo con la salida literal de pytest: BLOCKER,
  evidencia insuficiente (los tests podrian ser placebos).

## Evidencia esperada en execution_log.md

- Tabla de los 16 excepts reales (clasificacion PII-riesgo/seguro y
  justificacion), citando o replicando la tabla de work_plan.md.
- Diff final (o cita literal) de cada uno de los 12 bloques except
  corregidos, mostrando la rama except OSError nueva y la llamada exacta a
  scope_gate._relativize_scope_path con exc.filename y PROJECT_ROOT.
- Cita literal de cada uno de los 12 tests nuevos (o 11) en
  tests/test_agent_controller.py, con el monkeypatch usado para forzar el
  OSError y las aserciones sobre el mensaje resultante.
- Salida literal de pytest para cada uno de los 12 mutation checks: ANTES
  del revert (verde, incluyendo el test nuevo), DESPUES del revert temporal
  (el test nuevo falla), y tras restaurar (verde de nuevo).
- Salida literal de pytest tests/test_agent_controller.py -v completo
  (todos los tests, no solo los nuevos), confirmando 0 fallos.
- Salida literal de ruff check y ruff format --check sobre
  .agent/agent_controller.py y tests/test_agent_controller.py, con exit
  code 0 en ambos.
- Salida literal (o resumen con exit_code/level/tested_commit_sha) de
  scripts/run_pytest_safe.py confirmando level=all, exit_code=0 y
  tested_commit_sha == HEAD tras el commit del fix.
- Commit sha del repo_motor que contiene el fix, citado con WOT-2026-019d
  en el mensaje.
