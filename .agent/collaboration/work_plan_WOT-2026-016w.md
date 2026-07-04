# Work Plan - WOT-2026-016w

## Metadata
- **ID:** WOT-2026-016w
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** check_deliverables_exist.py descarta bullets FLT con anotacion (bug gemelo de 016s).
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Corregir _resolve_flt_bullet_tokens en scripts/check_deliverables_exist.py (~linea 232-263)
para que un bullet de Files Likely Touched con anotacion descriptiva tras el path (por ejemplo
scripts/x.py (nuevo, el gate)) se resuelva al path scripts/x.py y sea verificado en disco,
en vez de descartarse silenciosamente por contener un espacio. El fix debe alcanzar paridad
semantica con .agent/scope_gate.py::_normalize_flt_line (corregido en WOT-2026-016s), sin
reintroducir el falso positivo que ese mismo filtro de espacio existe para evitar: bullets
narrativos que mencionan paths entre backticks dentro de prosa (ej. "Notas: los scripts
inspeccionados (foo.py, bar.py) son read-only").

Verificacion del objetivo (comando literal): `.venv/Scripts/python.exe -m pytest tests/unit/test_check_deliverables_exist.py -v` da 11 passed (9 preexistentes + 2 nuevos de paridad), incluyendo el test que prueba que un bullet anotado con `scripts/annotated_thing.py` ausente en disco produce `code == 1`.

## Diagnostico (causa raiz verificada en codigo, sesion 2026-07-03)

- scripts/check_deliverables_exist.py:244-252, dentro de _resolve_flt_bullet_tokens:

```python
normalized = (
    stripped.lstrip("*- ")
    .replace("`", "")
    .replace('"', "")
    .replace("'", "")
    .strip()
)
if not normalized or " " in normalized:
    return
```

  Tras quitar el prefijo de bullet y los backticks/comillas, si la linea completa (path +
  anotacion) contiene CUALQUIER espacio, la funcion descarta el bullet entero y retorna sin
  anadir nada a paths. Un bullet "- `scripts/x.py` (nuevo, el gate)" normaliza a
  "scripts/x.py (nuevo, el gate)", que contiene espacios y se descarta. El deliverable nunca
  se verifica en disco: falso-verde en check_deliverables_exist para tickets documentation
  o mixed cuyo FLT usa bullets anotados.
- .agent/scope_gate.py:63-89 tiene el MISMO problema originalmente, corregido en
  WOT-2026-016s (_normalize_flt_line, lineas 77-89): tras la misma limpieza de
  backticks/comillas/bullet-prefix, la funcion se queda SOLO con el primer token separado por
  espacio (cleaned.split(" ", 1)[0]) antes de que el caller aplique _looks_like_path_token
  (linea 67-74: rechaza si hay espacio en el token, exige que empiece por punto, contenga
  slash o backslash, o que el basename tenga un punto). El commit 4c79e8e (WOT-2026-016s) es
  la fuente de este patron; no toco scripts/check_deliverables_exist.py (confirmado con
  "git log --oneline -- scripts/check_deliverables_exist.py": solo muestra commits de
  WOT-2026-010n, ninguno de WOT-2026-016s). El bug en check_deliverables_exist.py es real, no
  corregido, y es el gemelo exacto del que 016s arreglo en scope_gate.py.
- Matiz de diseno CONFIRMADO (no romper): el docstring de _resolve_flt_bullet_tokens
  (lineas 235-243) documenta que el filtro de espacio existe para rechazar bullets
  narrativos como "Notas: los scripts inspeccionados (foo.py, bar.py) son read-only". Ese
  caso real esta cubierto por el test existente
  tests/unit/test_check_deliverables_exist.py::test_wot_010j_real_case_narrative_note_not_treated_as_deliverable
  (linea 139-170), que usa el bullet narrativo real de WOT-2026-010j y exige code == 0
  (no tratarlo como deliverable faltante). El fix NO debe tocar ese comportamiento: tomar
  solo el PRIMER TOKEN (patron 016s) preserva el rechazo porque el primer token de una
  linea narrativa tipica ("Los", "Notas:", etc.) no pasa looks_like_path (no tiene punto ni
  slash, o es una palabra corriente sin extension), mientras que el primer token de un
  bullet anotado (scripts/x.py) SI pasa looks_like_path.
- looks_like_path (mismo archivo, lineas 63-71) es el equivalente local de
  _looks_like_path_token de scope_gate.py (lineas 66-74): ambas rechazan tokens con
  espacio y exigen punto, slash o backslash. looks_like_path anade un filtro extra (rechaza
  tokens UPPER_CASE con guion bajo, p.ej. constantes tipo YYYY_NNN) que no interfiere con el
  fix: un path real como scripts/x.py nunca es upper-case-con-guion-bajo.

## Alcance (cambio minimo, paridad con 016s)

Modificar UNICAMENTE _resolve_flt_bullet_tokens en scripts/check_deliverables_exist.py
para que, tras la limpieza actual de backticks/comillas/bullet-prefix, tome solo el primer
token separado por espacio (normalized.split(" ", 1)[0] o equivalente) ANTES de aplicar el
resto de las validaciones ya existentes (los caracteres <, >, {, }, YYYY, NNN, trailing
slash, looks_like_path). El resto de la funcion (resolucion de Path, current_root,
paths.add) no cambia. No se toca .agent/scope_gate.py (ya corregido en 016s) ni ningun otro
archivo.

### Non-goals

- NO modificar .agent/scope_gate.py ni _normalize_flt_line (ya corregidos en WOT-2026-016s).
- NO cambiar el filtro anti-narrativa mas alla de tomar el primer token: seguir rechazando
  bullets cuyo primer token no sea un path (looks_like_path sigue siendo la gate final).
- NO tocar _extract_paths_from_generic_sections, _process_backtick_tokens,
  resolve_with_fallbacks ni ningun otro extractor del mismo archivo: el bug y el fix son
  especificos de la seccion FLT namespaced (_resolve_flt_bullet_tokens / _extract_flt_paths).
- NO anadir un nuevo modo de deteccion de anotaciones (parentesis, comas, etc.): el patron
  "primer token" es identico al de 016s, no una heuristica nueva.

## Files Likely Touched

### repo_motor

- scripts/check_deliverables_exist.py
- tests/unit/test_check_deliverables_exist.py

## Tests Esperados

1. Nuevo test_wot_016w_flt_bullet_with_trailing_annotation_resolves_and_checked
   (tests/unit/test_check_deliverables_exist.py): un work_plan.md con
   "## Files Likely Touched" -> "### repo_motor" -> bullet
   "- `scripts/annotated_thing.py` (nuevo, el gate)" donde scripts/annotated_thing.py
   NO existe en disco debe dar code == 1 y el output debe mencionar annotated_thing.py
   (paridad con test_namespaced_repo_motor_missing_deliverable_fails_closed, pero con
   bullet anotado). Confirma criterio de aceptacion 1 del ticket (el deliverable se
   resuelve y se comprueba su existencia) usando el caso "falta en disco" como prueba
   directa: si la funcion siguiera descartando el bullet, el script no reportaria el
   archivo faltante y daria code == 0 (falso-verde), que es exactamente el bug.
2. Nuevo test_wot_016w_flt_bullet_with_trailing_annotation_passes_when_exists
   (mismo archivo): mismo bullet anotado pero con scripts/annotated_thing.py SI presente en
   disco (bajo motor_root) debe dar code == 0. Confirma que el path resuelto es el correcto
   (scripts/annotated_thing.py, no la linea completa con anotacion, que nunca existiria
   como archivo).
3. No-regresion (ya existente, no se toca):
   test_wot_010j_real_case_narrative_note_not_treated_as_deliverable debe seguir dando
   code == 0 tras el fix (confirma que el filtro anti-narrativa sigue vivo). Ejecutar junto
   al resto de la suite del archivo, no como test nuevo.
4. MUTATION (documentado en execution_log.md, no como test pytest nuevo separado):
   revertir temporalmente el fix (quitar el split en el primer token / volver a la
   condicion original de "si hay espacio, return") y confirmar que
   test_wot_016w_flt_bullet_with_trailing_annotation_resolves_and_checked (test 1) FALLA
   (el script da code == 0 en vez de 1 porque el bullet se descarta silenciosamente);
   restaurar el fix y confirmar que el mismo test PASA. Este es el criterio de aceptacion 3
   del ticket. Usar el patron ya establecido en el repo (worktree/checkout parcial con
   git status --short limpio antes y despues, o edicion temporal + git diff para confirmar
   revertido 100% al estado post-fix); ver prompts/orchestrator_launch_builder.md, seccion
   "Verificacion del test de regresion".

## Criterios de Aceptacion (binarios)

1. Un bullet FLT "scripts/x.py (anotacion)" se resuelve a scripts/x.py y
   check_deliverables_exist comprueba su existencia. Verificado por los tests 1 y 2 de
   "Tests Esperados": .venv/Scripts/python.exe -m pytest
   tests/unit/test_check_deliverables_exist.py -k wot_016w_flt_bullet_with_trailing_annotation -v
   pasa con 2 passed.
2. Un bullet narrativo con espacios pero sin path como primer token sigue rechazado (no
   reintroducir el falso positivo). Verificado por:
   .venv/Scripts/python.exe -m pytest tests/unit/test_check_deliverables_exist.py -k
   wot_010j_real_case_narrative_note_not_treated_as_deliverable -v pasa (1 passed).
3. MUTATION: revertir el fix hace que
   test_wot_016w_flt_bullet_with_trailing_annotation_resolves_and_checked FALLE; con el fix
   restaurado, el mismo test PASA. Ambos resultados (FAIL-sin-fix, PASS-con-fix) quedan
   registrados literalmente en execution_log.md con el comando exacto y el output relevante
   (no basta con narrar "se verifico").
4. Suite completa del archivo sigue verde: .venv/Scripts/python.exe -m pytest
   tests/unit/test_check_deliverables_exist.py -v -> todos los tests pasan (9 preexistentes
   + 2 nuevos = 11 passed), 0 failed.
5. ruff check scripts/check_deliverables_exist.py tests/unit/test_check_deliverables_exist.py
   -> exit code 0.
6. uv run ruff format --check scripts/check_deliverables_exist.py
   tests/unit/test_check_deliverables_exist.py -> exit code 0 (si uv no arranca en este
   entorno segun el diagnostico de WOT-2026-016c, usar el formatter equivalente ya instalado
   en .venv y documentar la sustitucion en execution_log.md; no declarar el gate como
   "no aplica" sin evidencia).
7. Suite canonica: python scripts/run_pytest_safe.py --level all con last-run.json en
   status=finished, exit_code=0, level=all, args_mode=default_discovery y
   tested_commit_sha == HEAD del commit que se entrega.
8. validate (Manager gate, ver abajo) en 0 errors / 0 warnings.

## Quality Gates

- Builder ejecuta:
  - .venv/Scripts/python.exe -m pytest tests/unit/test_check_deliverables_exist.py -v
  - ruff check scripts/check_deliverables_exist.py tests/unit/test_check_deliverables_exist.py
  - uv run ruff format --check scripts/check_deliverables_exist.py tests/unit/test_check_deliverables_exist.py
  - .venv/Scripts/python.exe scripts/run_pytest_safe.py --level all
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - .venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .

## STOP conditions

- Si el fix requiere tocar .agent/scope_gate.py para que el test pase: DETENTE, es fuera de
  scope (ya corregido en 016s); reporta el hallazgo en execution_log.md y no amplies el
  ticket.
- Si el test anti-narrativa existente
  (test_wot_010j_real_case_narrative_note_not_treated_as_deliverable) empieza a fallar tras
  el fix: DETENTE, el fix esta reintroduciendo el falso positivo que el ticket prohibe
  explicitamente; no relajes ni borres ese test para forzar verde.
- Si "uv run ruff format --check" no arranca en este entorno (mismo sintoma documentado en
  WOT-2026-016c: uv desalineado del .venv), no lo declares "no aplica": usa
  .venv/Scripts/python.exe -m ruff format --check <paths> como equivalente y documenta la
  sustitucion con el output literal en execution_log.md.
- Si run_pytest_safe.py --level all no cierra con tested_commit_sha == HEAD del commit
  final: no reportes cierre canonico; re-corre tras el commit final antes de --mark-ready.

## Riesgos

- Bajo: cambio de una linea logica dentro de una funcion ya cubierta por 9 tests
  existentes, con paridad exacta a un fix ya verificado (016s) en el mismo repo.
- Medio: el filtro anti-narrativa es el unico invariante fragil; mitigado con test de
  no-regresion explicito en Tests Esperados item 3 y STOP condition dedicada.

## Decision Arquitectonica

Por que tomar el primer token en vez de otra heuristica: WOT-2026-016s ya resolvio exactamente este problema en `.agent/scope_gate.py::_normalize_flt_line` con el mismo patron (`cleaned.split(" ", 1)[0]`), revisado y aprobado por el Manager en esa ronda. Replicar el patron exacto en `check_deliverables_exist.py` da paridad semantica entre los dos consumidores del mismo formato de bullet FLT, minimiza el diff (una linea logica) y reutiliza el razonamiento ya verificado de por que el primer token no rompe el filtro anti-narrativa (el primer token de una linea narrativa no pasa `looks_like_path`). Alternativas descartadas: ver Trade-offs Considerados abajo.

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Tomar el primer token, igual que 016s | Paridad exacta con el fix ya revisado y aprobado en scope_gate; cambio minimo de una linea | Trunca paths con espacios literales (edge case ya documentado como inerte en 016s) | Elegida |
| Detectar anotacion por parentesis / heuristica nueva | Mas "inteligente" para casos no cubiertos | Heuristica nueva sin precedente revisado; mayor superficie de bug; diverge del patron gemelo | Descartada |

## Criterios de Aceptacion Global
- [ ] Bullet FLT anotado se resuelve y se verifica en disco (tests 1 y 2)
- [ ] Bullet narrativo sigue rechazado (test 3, no-regresion)
- [ ] Mutation FAIL-sin-fix / PASS-con-fix documentado en execution_log.md
- [ ] Suite del archivo 11 passed, 0 failed
- [ ] ruff check + ruff format --check en verde
- [ ] Suite canonica run_pytest_safe.py --level all verde con tested_commit_sha == HEAD
- [ ] validate --json 0 errors / 0 warnings (Manager gate)
