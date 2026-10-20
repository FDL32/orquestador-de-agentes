# Follow-up: coordinacion cross-worktree de la suite canonica (WOT-2026-107a)

> Draft de seguimiento (no es un ticket activo ni cerrado). Origen: implementacion
> parcial encontrada sin commitear en el checkout `FDL32-t3-dev-hub` el 2026-10-20,
> correspondiente a la propuesta de diseno ya revisada en
> `.agent/planning/agents_md_optimization/propuesta_coordinacion_suites_crossworktree.md`
> (bucle DESIGN_REVIEW de 4 lentes ya corrido, Fase C de ese documento: codex/deepseek/
> qwen3.6 = CHANGES -> diseno corregido con 7 puntos convergentes; gemma4 = APPROVE).
> Reconstruido via `git hash-object` + `git log --all --find-object` (195 checkpoints
> internos de T3 en esta misma worktree, 2026-10-18T23:31Z -> 2026-10-20T07:55Z):
> una sesion de desarrollo anterior en este mismo checkout implemento el diseno
> corregido pero nunca comito a un branch real antes de terminar.
>
> **Requiere decision del usuario para abrir como ticket formal del pipeline** (no se
> ha corrido el bucle 4 capas/MANAGER_REVIEW de cierre sobre este codigo).

## Metadata propuesta
- **ID sugerido:** `WOT-2026-107a` (siguiente libre; confirmado sin colision via
  `grep -r "WOT-2026-107"`, cero hits, al redactar este followup).
- **deliverable_type:** code (toca `scripts/run_pytest_safe.py` + tests nuevos).
- **delivery_authority:** repo_motor
- **Prioridad:** Media -- WARN no-bloqueante hoy (dos suites concurrentes en worktrees
  distintas se pisan en CPU/RAM, no hay corrupcion de datos), pero mide un incidente
  real ya ocurrido (ver propuesta, Fase A, contexto medido).

## Estado del codigo encontrado (commitear o descartar, decision pendiente)
- `scripts/run_pytest_safe.py`: +279 lineas sin commitear. Implementa
  `CrossWorktreeHolder`/`CrossWorktreeLockResult` (dataclasses), `acquire_cross_worktree_lock()`
  / `release_cross_worktree_lock()`, lock en `<git-common-dir>/agent-runtime/pytest-canonical.lock`,
  `EX_TEMPFAIL = 75`. Cubre, a primera lectura, los puntos 1 (resultado estructurado),
  3 (ownership-check en release) y 6 (subdirectorio propio, no `.git/` directo) del
  contrato corregido de la Fase C. **No verificado si cubre los puntos 2 (comportamiento
  por defecto ante lock vivo: salir con `EX_TEMPFAIL` salvo `--force-parallel`/`--wait-lock`
  explicitos), 4 (worktree como ruta absoluta normalizada + distincion "mismo worktree"
  vs cross-worktree real) y 5 (`--force-unlock` hereda la misma disciplina fail-safe) --
  requiere lectura completa + verificacion punto a punto antes de aceptarlo.**
- `tests/unit/test_run_pytest_safe.py`: +471 lineas sin commitear. **151/151 tests
  pasan en este checkout (2026-10-20, `uv run python -m pytest tests/unit/test_run_pytest_safe.py -q`)**,
  pero esto es autochequeo del mismo autor sin commitear: no ha pasado por un Revisor de
  backend distinto (regla dura, `persona_system.md` Seccion 2) ni por el ciclo 4 capas.
  Punto 7 del contrato ("tests deben combinar PIDs reales con mocks de
  `is_pid_running()` para casos stale/ambiguos") no verificado linea a linea todavia.
- Ningun fichero de este follow-up esta commiteado aun; vive solo en el disco de este
  checkout hasta que el usuario decida. T3 ya tiene 195 checkpoints internos de este
  trabajo (no se pierde si el checkout se resetea), pero esos checkpoints no son
  historia git normal ni portatil fuera de esta maquina/sesion.

## Objetivo (si se adopta)
Que `run_pytest_safe.py --level all` detecte, antes de lanzar la suite, si OTRO
worktree del mismo repo ya tiene una corrida viva (via el `.git` comun compartido por
todos los worktrees), y aplique la UX (b) ya decidida en la propuesta: avisar +
preguntar, nunca bloquear silenciosamente (a) ni competir sin avisar (c, el incidente
medido).

## Files Likely Touched
- `scripts/run_pytest_safe.py`
- `tests/unit/test_run_pytest_safe.py`

## Contrato del fix (minimo, si se adopta)
- Verificar explicitamente, punto a punto, los 7 hallazgos convergentes de la Fase C
  de `propuesta_coordinacion_suites_crossworktree.md` contra el codigo ya escrito
  (no asumir que esta completo solo porque los tests propios pasan).
- Correr el ciclo 4 capas (Manager/Builder/Revisor de backend distinto/Manager-suite)
  ya establecido en esta linea de sesiones -- este codigo nunca paso por un Revisor.
- Decidir el flag `--notify-peers` (capa T3 opcional, Fase B de la propuesta): confirmar
  si se implementa en esta pasada o se ficha aparte.

## Non-goals
- No cubre colision cross-repo (motor vs un `repo_destino`, o dos proyectos sin
  relacion) -- la propia propuesta (A.2) declara que no hay evidencia medida de ese
  caso todavia.
- No sustituye el lock intra-checkout ya existente (`acquire_lock()`/`LOCK_FILE`); lo
  complementa.

## Criterio binario de cierre (si se adopta)
- [ ] Los 7 puntos de la Fase C verificados linea a linea contra el codigo, con
  correcciones donde falten.
- [ ] Revisor de backend distinto al implementador corrio sobre el diff real.
- [ ] `ruff` + suite canonica completa del motor verdes con el codigo commiteado.
- [ ] Decision explicita (adoptar o descartar) sobre `--notify-peers`.

## Trazabilidad
- Diseno + bucle DESIGN_REVIEW de origen:
  `.agent/planning/agents_md_optimization/propuesta_coordinacion_suites_crossworktree.md`
  (loop_id `EXPLORATORY-coord-suites-crossworktree`, commit-sha `96243c48`).
- Reconstruccion forense de origen del codigo sin commitear: sesion 2026-10-20,
  `git hash-object scripts/run_pytest_safe.py` = `4b7f2efee14a79d025d33924936545f8d34ddafd`,
  encontrado en 195 checkpoints T3 (`refs/t3/orchestration-v2/checkpoints/
  OGJlMzIwMzFlM2I1NjI4NGM3MGYwNzYyMDA2MTA4NWI/ordinal/0..195`,
  2026-10-18T23:31:12+02:00 -> 2026-10-20T07:55:27+02:00). Confirmado por coordinacion
  con 2 sesiones peer (`sibling-test-20261020-71`, `pilot-104np-20261019-bd`, ambas en
  worktrees DISTINTOS a este): ninguna reclama el WIP, ninguna lo toco.
- **Continuidad explicita (decision del usuario, 2026-10-20):** continuar este ticket
  en la siguiente sesion de continuidad de optimizacion de AGENTS.md, no en esta
  sesion de cierre.
