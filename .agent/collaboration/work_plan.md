# work_plan - WOT-2026-129l

## Metadata

- ticket: WOT-2026-129l
- flight: vuelo-20261026b (S1 implantacion-1, Manager `nan/mimo-v2.6-flash`)
- branch: `flight/WOT-2026-129l` (base `cef840cb` = punta `flight/vuelo-20261026b` verificada)
- deliverable_type: code
- delivery_authority: repo_motor
- status: APPROVED (CONTRACT_AUDIT hecha: BA03 APROBAR sin BLOCKER; BA110 503
  -> sin cuenta; OR-1 autoriza Builder con BA03 unica lente y eleva R-A/R-B a
  REQUISITOS de este plan)
- fecha: 2026-10-26

## Premisa (verificada en vivo, PASO 1)

- `git log --grep 129l/129p` = 0 hits; grep de mecanismo de aviso de drift
  (`settings_canonical|canonical_drift|resync.*aviso`) en `scripts/` = 0 hits.
- No existe hoy NINGUN aviso en motor (cierre ni prepush) cuando cambia un comando
  canonico de hooks; el gate solo corre en la CI de cada destino, DESPUES del push
  (fallo medido: WOT-2026-058a dejo el workspace rojo en main hasta 10ccc0cb).
- Simbolos del DoD existentes: `canonical_command_for` (`claude_guard_entry.py:255`),
  `canonical_hook_command` (`:297`), `canonical_session_start_command` (`:321`).
- NO arregla aqui el gap del generador (eso es WOT-2026-129p, ya fichada).

## DoD (binario; de la ficha 129l del backlog del workspace)

1. Deteccion en el motor: un diff que toca `canonical_hook_command`/
   `canonical_session_start_command` de `.agent/hooks/claude_guard_entry.py` o
   `scripts/check_claude_settings_portability.py` produce un aviso NOMBRADO
   (punto de cableado: DECISION D1 abajo).
2. El aviso lista los destinos conocidos (los `motor_destination_link.json`
   resolubles, mismo universo que WOT-2026-129k) cuyo `.claude/settings.json` NO
   pasa el gate con el motor NUEVO, con el comando de re-sincronizacion.
3. WARN, no BLOCK (no puede depender de repos ajenos al motor), y fail-visible:
   universo vacio o link ilegible se DECLARA, nunca OK silencioso.
4. Tests: (a) cambio canonico + destino fixture desfasado -> aviso con ese
   destino; (b) cambio ajeno -> sin aviso; (c) destino al dia -> no aparece.
5. Cableado visible para `scripts/check_guard_wiring.py`.

## Decisiones del contrato (con motivo)

- **D1 - punto de cableado = `scripts/prepush_check.py`**, no el cierre.
  Motivo: (i) `prepush_check` corre en TODO push, justo ANTES de que el motor
  publique, que es exactamente la ventana del fallo medido (la CI del destino
  recien se enteraria despues); (ii) el cierre (`--session-close`) no corre en
  todos los flujos que publican (code-only / cierre manual) y en este vuelo es
  N/A; (iii) existe patron WARN previo ahi mismo (`run_arranque_budget_check`,
  5-bis: `is_blocking=False`, corre en todo push). Forma: nuevo
  `run_settings_canonical_drift_check(project_root)` con
  `CheckResult(..., is_blocking=False)` (DoD 3: WARN, jamas bloquea).
- **D2 - universo de destinos**: barredo `<raiz>/*/.agent/config/motor_destination_link.json`
  resolubles (parseo OK), mismo barrido que el censo 129k. Raices: flag CLI
  `--destino-root` (repetible) > env `AGENT_DESTINOS_ROOT` (separada por
  `os.pathsep`) > default = directorio padre del checkout del motor
  (`Path(__file__).resolve().parents[1].parent`). Motivo: portabilidad (NADA de
  rutas de usuario hardcodeadas - grep `Proyectos_Python` en scripts = 0
  precedentes) + el default por herencia de topologia sigue funcionando en la
  instalacion actual, y el vacio se declara (DoD 3).
- **D3 - comando de resync citado en el aviso**: `python
  scripts/install_agent_system.py --sync --dest <destino>` ejecutado desde el
  CHECKOUT CANONICO del motor. Motivo: es la forma medida como correcta en
  FASE 2 de WOT-2026-129k (flag real `--dest`; el generador estampa el
  motor_root de su propio checkout, por eso "desde el canonico").
- **D4 - diff de trigger**: `git diff --name-only origin/main...HEAD` (rango del
  push). Sin `origin/main` -> el aviso DECLARA el diff indeterminado y aun asi
  evalua el universo (fail-visible, nunca silencio).

## Files Likely Touched

- scripts/check_settings_canonical_drift.py
- scripts/prepush_check.py
- tests/unit/test_settings_canonical_drift.py
- CHANGELOG.md

## Fases y tareas

1. **F1 - nucleo del check (scripts/check_settings_canonical_drift.py)**
   - T1.1: `TRIGGER_PATHS` = (`.agent/hooks/claude_guard_entry.py`,
     `scripts/check_claude_settings_portability.py`) + deteccion de si el diff
     toca `canonical_hook_command`/`canonical_session_start_command` (diff de
     nombres de fichero; D4).
   - T1.2: resolucion de universo (D2) con resultado por link: resoluble /
     ilegible (declarado) / settings ausente (declarado).
   - T1.3: por destino resoluble, gate con el motor ACTUAL
     (`check_claude_settings_portability.py <destino>/.claude/settings.json`)
     -> falla = candidato a listar con su D3.
   - T1.4: emision del aviso NOMBRADO (`[settings-canonical-drift] WARN ...`):
     lista de destinos en rojo + comando resync + conteo de al-dia + declara
     universo vacio/ilegible/diff indeterminado cuando aplique. Nunca silencio.
   - T1.4-bis (**REQUISITO R-A/R-B, elevado por OR-1**): R-B - el aviso o su
     docstring DECLARA que en topologia de worktrees el default
     (`parents[1].parent`) puede no alcanzar el destino activo y que el remedio
     es `--destino-root` / env `AGENT_DESTINOS_ROOT`.
   - T1.5: CLI propio (`--destino-root` repetible, `--project-root`, rc 0
     siempre: es WARN; rc != 0 solo para ERROR interno del script).
2. **F2 - cableado (scripts/prepush_check.py)**
   - T2.1: `run_settings_canonical_drift_check(project_root)` con import
     ESTATICO del modulo (patron que `check_guard_wiring` cuenta como WIRED) y
     `is_blocking=False`; registrado en `run_preflight_check` en la cadena de
     TODO push (tras 5-ter, closeout_mode=False).
   - T2.1-bis (**REQUISITO R-A, elevado por OR-1**): el run_ envuelve TODO su
     cuerpo en try/except amplio y convierte CUALQUIER excepcion en
     `CheckResult(..., is_blocking=False, ...)` con mensaje nombrando la causa
     (forma exacta 5-bis, `prepush_check.py:958-975`); NUNCA propaga: un raise
     abortaria el prepush entero y violaria el DoD 3.
   - T2.2: ejecutar `scripts/check_guard_wiring.py` y verificar que el guard
     nuevo aparece cableado (DoD 5); si NO lo detecta, PARAR y escalar al
     Manager (posible cambio fuera de FLT).
3. **F3 - tests (tests/unit/test_settings_canonical_drift.py)**
   - T3.1: (a) trigger canonico + fixture destino desfasado -> aviso NOMBRANDO
     ese destino; (b) diff de fichero ajeno -> sin aviso; (c) fixture destino
     al dia (pasa el gate) -> no aparece en la lista.
   - T3.2: (D2/DoD 3) universo vacio -> declara vacio (nunca "OK" silencioso);
     link malformado -> declarado ilegible, no rompe.
   - T3.3: wiring: el modulo invocado desde `run_settings_canonical_drift_check`
     (o assertion de presencia en `run_preflight_check`, segun lo que
     `check_guard_wiring` realmente mire - sin inventar el mecanismo).
4. **F4 - CHANGELOG.md** entrada del ticket.
5. **F5 - gates focales (Manager, rc real sin pipe)**: `ruff check` sobre los
   ficheros, `pytest tests/unit/test_settings_canonical_drift.py` leyendo
   "N passed", `py_compile`, `check_guard_wiring.py`. SIN suite canonica (la
   ordena la orquestadora al final del vuelo).

## Riesgos

- R1 (alto): falso-verde del trigger - un diff que toca el fichero pero NO la
  funcion canonica debe o no disparar? Ficha dice "un diff que toca
  canonical_hook_command/canonical_session_start_command de claude_guard_entry.py
  O check_claude_settings_portability.py" -> trigger por FICHERO (no por
  simbolo) para los dos primeros; el gate completo solo para el tercero.
  Se implementa por fichero (mas simple, coincide con la letra del DoD) y se
  cubre con test (b).
- R2: coste de prepush - cada push barre destinos y corre el gate N veces.
  Acotado: solo se evalua el universo SI el diff toca trigger; trigger negativo
  = coste cero (test (b) lo fija).
- R3: avisar con destinos ajenos no resolubles -> DoD 3 lo resuelve declarando.
- R4: 129l NO toca el generador (129p). Si un lente propone "arreglar
  propagate_*" = scope creep -> PARAR y avisar (instruccion explicita de la
  orquestadora).

## Criterios de aceptacion (invariantes)

- CA1: con diff tocando `.agent/hooks/claude_guard_entry.py` y fixture de
  destino desfasado, la salida contiene el nombre del destino y el comando
  `--sync --dest`; con fixture al dia, ese destino NO aparece.
- CA2: con diff de fichero ajeno, NINGUN aviso de drift (linea ausente).
- CA3: universo vacio y link ilegible producen declaraciones explicitas.
- CA4: `check_guard_wiring.py` reconoce el guard como cableado; el check en
  prepush es `is_blocking=False` (nunca puede rojo-ear un push); y la MUTACION
  de la via raise (nucleo que lanza excepcion) devuelve CheckResult WARN sin
  romper el prepush (REQUISITO R-A).
- CA5: ruff verde en los ficheros tocados; tests verdes leidos por "N passed".
