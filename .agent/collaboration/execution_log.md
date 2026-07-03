# Execution Log - WOT-2026-016w

**Ticket:** WOT-2026-016w - check_deliverables_exist.py descarta bullets FLT con anotacion
(bug gemelo de 016s).
**Estado:** IN_PROGRESS
**delivery_authority:** repo_motor | **deliverable_type:** code

> execution_log de WOT-2026-016c (COMPLETED) preservado en
> execution_log_WOT-2026-016c.md antes de este bootstrap.

## Fase 0 - Diagnostico (Orquestador + Manager, EJECUTADO, verificado en codigo)

- Sintoma confirmado en scripts/check_deliverables_exist.py:244-252
  (_resolve_flt_bullet_tokens): tras limpiar backticks/comillas/bullet-prefix, si la linea
  completa contiene un espacio, la funcion descarta el bullet entero sin comprobar
  existencia en disco.
- Confirmado que .agent/scope_gate.py::_normalize_flt_line (lineas 77-89) ya corrige el
  mismo problema desde WOT-2026-016s (commit 4c79e8e): toma solo el primer token separado
  por espacio antes de que _looks_like_path_token valide el resultado.
- Confirmado con git log --oneline -- scripts/check_deliverables_exist.py que este archivo
  NO fue tocado por WOT-2026-016s (ultimo commit es de WOT-2026-010n): el bug es real y
  sigue sin corregir.
- Matiz de diseno anti-narrativa confirmado: docstring lineas 235-243 y test existente
  test_wot_010j_real_case_narrative_note_not_treated_as_deliverable (lineas 139-170 de
  tests/unit/test_check_deliverables_exist.py) cubren el caso que el filtro de espacio
  protege; el fix de "primer token" no lo rompe porque el primer token de una linea
  narrativa no pasa looks_like_path.
- Baseline: .venv/Scripts/python.exe -m pytest tests/unit/test_check_deliverables_exist.py -q
  -> 9 passed in 1.00s (verificado antes de cualquier cambio).

## Fase 0 - Diagnostico (Builder, re-confirmado en codigo)

- Preflight: `.venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .`
  -> `total_errors: 0, total_warnings: 0`. STATE.md = `WOT-2026-016w / IN_PROGRESS`. TURN.md =
  `ROL: BUILDER, Plan ID: WOT-2026-016w, Accion: IMPLEMENT`. work_plan.md ID activo =
  WOT-2026-016w. Preflight OK, runtime bootstrapped correctamente.
- Seam confirmado: `scripts/check_deliverables_exist.py:232-263`
  (`_resolve_flt_bullet_tokens`), caller `_extract_flt_paths` (linea 266-325, llama al
  resolver en la linea 323 para cada bullet `-`/`*` dentro de `## Files Likely Touched`).
- Linea exacta a cambiar: linea 251 `if not normalized or " " in normalized:` — se sustituye
  la condicion de descarte por espacio por "quedarse con el primer token" (paridad con
  `.agent/scope_gate.py::_normalize_flt_line` linea 89: `cleaned.split(" ", 1)[0]`), ANTES
  del resto de validaciones ya existentes (linea 253 `rstrip(",")`, linea 256 caracteres
  prohibidos, linea 258 `looks_like_path`).
- `_normalize_flt_line` (scope_gate.py:77-89) y `_looks_like_path_token` (scope_gate.py:66-74)
  confirmados como el patron gemelo ya revisado: limpia backticks/comillas/bullet-prefix,
  toma `cleaned.split(" ", 1)[0]` como el path candidato, y el caller valida ese token con
  `_looks_like_path_token` (rechaza si aun tiene espacio, exige que empiece por punto,
  contenga slash/backslash, o el basename tenga un punto). `looks_like_path` en
  check_deliverables_exist.py (lineas 63-71) es equivalente local con un filtro extra
  (rechaza UPPER_CASE con guion bajo) que no interfiere con el fix.
- Test de referencia para el patron de test nuevo:
  `test_namespaced_repo_motor_missing_deliverable_fails_closed` (tests/unit/
  test_check_deliverables_exist.py:107-116). Test de no-regresion a preservar:
  `test_wot_010j_real_case_narrative_note_not_treated_as_deliverable` (lineas 139-170).

## Fase 1 - Implementacion

- Cambio unico en `scripts/check_deliverables_exist.py::_resolve_flt_bullet_tokens`
  (linea ~251-259): reemplazada la condicion `if not normalized or " " in normalized: return`
  por `if not normalized: return` seguido de `normalized = normalized.split(" ", 1)[0]`
  (paridad exacta con `scope_gate._normalize_flt_line`), ANTES del resto de validaciones
  ya existentes (rstrip coma, caracteres prohibidos, looks_like_path). Docstring de la
  funcion actualizado para reflejar el comportamiento real (ya no rechaza por espacio, sino
  que toma el primer token y ese token es el que se valida contra looks_like_path).
  No se toco `.agent/scope_gate.py` ni ningun otro archivo (non-goal respetado).

## Fase 2 - Tests nuevos

- Anadidos 2 tests en `tests/unit/test_check_deliverables_exist.py` (antes de
  `test_wot_010j_real_case_narrative_note_not_treated_as_deliverable`, siguiendo el patron
  de `test_namespaced_repo_motor_missing_deliverable_fails_closed`):
  - `test_wot_016w_flt_bullet_with_trailing_annotation_resolves_and_checked`: bullet
    `` - `scripts/annotated_thing.py` (nuevo, el gate)`` bajo `### repo_motor`, archivo
    AUSENTE en `motor_root` -> exige `code == 1` y `"annotated_thing.py" in output`.
  - `test_wot_016w_flt_bullet_with_trailing_annotation_passes_when_exists`: mismo bullet,
    archivo PRESENTE en `motor_root/scripts/annotated_thing.py` -> exige `code == 0`.

## Mutation-verify (criterio de aceptacion 3, OBLIGATORIO)

Backup previo: `scripts/check_deliverables_exist.py` copiado a
`.../scratchpad/check_deliverables_exist.py.bak_016w` (fuera del repo) antes de mutar.

1. **(a) Test de paridad SIN el fix** (revertido solo el cambio central: condicion vuelta a
   `if not normalized or " " in normalized: return`, sin el `split(" ", 1)[0]`):
   ```
   .venv/Scripts/python.exe -m pytest tests/unit/test_check_deliverables_exist.py -k wot_016w_flt_bullet_with_trailing_annotation_resolves_and_checked -v
   ```
   Resultado: **FAILED**. `assert code == 1` -> `AssertionError: assert 0 == 1` (el bullet
   anotado se descarta silenciosamente, el script no detecta el archivo faltante: exactamente
   el falso-verde que describe el bug).
2. **(b) Codigo de salida observado (pytest):** `1` (`1 failed, 10 deselected in 0.22s`,
   `EXIT_CODE=1` capturado tras el comando).
3. **(c) Test CON el fix restaurado** (archivo restaurado byte-a-byte desde el backup;
   `git diff scripts/check_deliverables_exist.py` confirmado identico al fix original: 14
   insertions(+), 4 deletions(-) sobre HEAD, mismo diff que tras la Fase 1):
   ```
   .venv/Scripts/python.exe -m pytest tests/unit/test_check_deliverables_exist.py -k wot_016w_flt_bullet_with_trailing_annotation_resolves_and_checked -v
   ```
   Resultado: **PASSED** (`1 passed, 10 deselected in 0.17s`).
4. **(d) Codigo de salida observado (pytest):** `0` (`EXIT_CODE=0` capturado tras el comando).

Arbol confirmado limpio tras la restauracion (`git status --short` sobre
`scripts/check_deliverables_exist.py` muestra unicamente el diff del fix, ningun rastro de
la mutacion temporal).

## Quality gates (Builder)

1. `.venv/Scripts/python.exe -m pytest tests/unit/test_check_deliverables_exist.py -v`
   -> **11 passed in 1.14s** (9 preexistentes + 2 nuevos, 0 failed). Incluye
   `test_wot_010j_real_case_narrative_note_not_treated_as_deliverable` en verde (no-regresion
   confirmada, STOP condition no disparada).
2. `.venv/Scripts/python.exe -m ruff check scripts/check_deliverables_exist.py tests/unit/test_check_deliverables_exist.py`
   -> `All checks passed!` (exit 0).
3. `uv run ruff format --check scripts/check_deliverables_exist.py tests/unit/test_check_deliverables_exist.py`
   -> funciono en este entorno (con warning benigno de `VIRTUAL_ENV` no coincide con
   `.venv`, ignorado por uv): `2 files already formatted` (exit 0). No hizo falta el
   fallback a `.venv/Scripts/python.exe -m ruff format --check` documentado en el plan como
   contingencia (a diferencia de 016c, aqui `uv run` si arranco).
4. `.venv/Scripts/python.exe scripts/run_pytest_safe.py --level all` (PRIMERA corrida, antes
   del commit de cierre): **8 failed, 3466 passed, 20 skipped**. Los 8 fallos son TODOS en
   `tests/test_agent_controller.py::TestPreHandoff` y
   `TestBuilderBriefExclusion::test_builder_brief_does_not_block_pre_handoff`, no relacionados
   con `check_deliverables_exist.py` (confirmado corriendo solo esas clases:
   `-k "TestPreHandoff or TestBuilderBriefExclusion"` -> mismos 8 failed). Causa raiz: estos
   tests invocan `_handle_pre_handoff` real, que lee el estado git actual del arbol de
   trabajo; en este punto del ciclo `.agent/collaboration/work_plan.md` (y STATE/TURN/
   execution_log) estan modificados sin commitear (bootstrap del Orquestador para 016w aun
   no commiteado), por lo que el guard real reporta
   `uncommitted_work_plan: true` y bloquea con exit 1 en vez del exit 0 que los tests esperan
   para sus escenarios mockeados. Coincide con la leccion de memoria "Suite --level all:
   state-leak de artefactos / tests-que-leen-arbol fallan con arbol sucio -> commitear antes
   de suite". Plan de accion: commitear (fix + tests + artefactos de colaboracion) y
   RE-CORRER la suite canonica sobre el HEAD final antes de mark-ready (exigido por el
   propio work_plan.md, seccion STOP conditions y Criterios de Aceptacion 7).
