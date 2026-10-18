# Follow-up: disparador 3.6 (suite-optimization) activo por nodeid recurrente

> Draft de seguimiento (no es un ticket activo). Origen: cierre de sesion motor-only
> 2026-10-18 bajo `prompts/orchestrator_session_close_full_audit.md`, Bloque 1.3.6. Hallazgo de
> la lente adversarial Codex (`codex exec -m gpt-6-luna`, ronda real,
> `.agent/planning/research_context_budget/review_close_codex.md`), verificado de forma
> independiente leyendo `run_history.jsonl` directamente.
> Materializado como follow-up versionable (misma via que
> `docs/followups/agents-md-over-quota-followup.md`) porque este cierre es motor-only: no hay
> `destination_root` resoluble para registrar via Bloque 5 del prompt de cierre.
> **Requiere decision del usuario para abrir WP** (no se lanza el piloto de
> `prompts/suite_optimization.md` sin esa decision -- es gasto de tiempo/CI, no gratis).

## Metadata propuesta
- **ID sugerido:** siguiente `WOT-2026-NNN` libre.
- **deliverable_type:** code (toca tests/fixtures, nunca asserts ni barreras git reales).
- **delivery_authority:** repo_motor
- **Prioridad:** Media (no bloqueante; la suite sigue dando verde, es una oportunidad de
  reducir tiempo de corrida).

## Premisa verificada (read-only)

    ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\FDL32-t3-dev-hub, HEAD=bf74cd33, dirty=8, verificado=2026-10-18T (sesion de cierre motor-only)

- `run_history.jsonl` (raiz motor, `.agent/runtime/pytest-safe/run_history.jsonl`): 6 filas
  totales, 3 con `level=all`, `status=finished`, `args_mode=default_discovery` (las unicas
  computables por la regla WOT-2026-044o).
- Criterio 3.6(c) del prompt de cierre: "el mismo `nodeid` aparece en `top_slowest` en >=3 de
  las 5 ultimas corridas COMPLETAS". El criterio NO exige que existan 5 corridas para evaluarse
  -- con las 3 disponibles, `>=3 de las 5` se satisface igual si las 3 que hay ya cumplen.
- Verificado por comando (`.venv/Scripts/python.exe` leyendo el jsonl): las TRES corridas
  completas (`finished_at` 2026-10-18T00:18:38Z, 00:48:18Z, 08:27:55Z; `duration_s` 1023.29,
  1041.32, 1036.47) tienen, cada una, el mismo nodeid en `top_slowest`:
  `tests/integration/test_run_pytest_safe_process_isolation.py::TestProcessIsolationReal::test_runner_survives_parent_kill`.
- Criterio 3.6(a) (duracion de ESTA sesion >600s) NO aplica literalmente: esta sesion de cierre
  no corrio la suite ni una vez (deliverable_type=documentation, 0 cambios Python). Las 3
  corridas citadas son de sesiones/tickets anteriores. Criterio 3.6(b) (tendencia 5-vs-5) sigue
  NO VERIFICABLE (faltan corridas para el segundo quinteto).
- **Conclusion correcta (corrige el borrador inicial del cierre, que declaro "no dispara" por
  mirar solo (a)/(b) y pasar por alto que (c) no exige 5 corridas):** el disparador 3.6 SI
  dispara, por (c) exclusivamente.

## Objetivo
Decidir si lanzar el piloto de `prompts/suite_optimization.md` (contract_id
cid-suite-optimization-v1, RECOLECTOR->JUEZ) sobre
`tests/integration/test_run_pytest_safe_process_isolation.py::TestProcessIsolationReal::test_runner_survives_parent_kill`,
que ya aparece como el test mas lento en las 3 ultimas corridas completas de la suite canonica
(~1020-1040s de duracion total de suite en las 3 corridas; este test es candidato pero el
prompt exige leer la tabla de `durations` real antes de culpar a un nodeid por su posicion en
`top_slowest` -- la atribucion de pytest puede mentir por teardown session-scoped, TRAMPA-1 del
propio prompt).

## Contrato del fix (minimo, SI se abre WP)
- Leer `prompts/suite_optimization.md` ENTERO antes de tocar nada (regla de "prompt citado =>
  leelo entero").
- Aplicar su PASO 1 (recoleccion desde `run_history.jsonl` + tabla de durations real, no solo
  `top_slowest`) y PASO 2 (las DOS condiciones duras: before/after medido + guard, antes de
  aplicar cualquier piloto).
- Non-goals que el piloto debe respetar: NUNCA mock-drift, NUNCA relajar asserts, NUNCA tocar
  barreras git reales.

## Non-goals
- No lanzar el piloto sin decision explicita del usuario (coste de tiempo/CI no es gratis).
- No asumir que el nodeid citado es la causa real sin leer la tabla de `durations` completa
  (la atribucion de `top_slowest` puede ser session-scoped teardown, no el test en si).

## Criterio binario de cierre
- [ ] `prompts/suite_optimization.md` leido entero.
- [ ] Recoleccion con tabla de `durations` real (no solo `top_slowest`) citada.
- [ ] Decision: aplicar piloto (con before/after medido + guard) o declarar "no vale la pena"
  con evidencia, y marcar este follow-up como cerrado en cualquiera de los dos casos.

## Trazabilidad
- Cierre de sesion motor-only 2026-10-18, Bloque 1.3.6 de
  `prompts/orchestrator_session_close_full_audit.md`.
- Hallazgo original: `.agent/planning/research_context_budget/review_close_codex.md` (Codex,
  `codex exec -m gpt-6-luna`, ronda real DECISION: CHANGES).
- Verificacion independiente: lectura directa de
  `.agent/runtime/pytest-safe/run_history.jsonl` por el agente de cierre (comando citado
  arriba), confirmando el hallazgo antes de aceptarlo.
