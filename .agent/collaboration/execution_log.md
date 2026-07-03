# Execution Log - WOT-2026-016t

**Ticket:** WOT-2026-016t - manager-approve: el mensaje del WARN por commit invalido no es
accionable (no muestra el commit encontrado ni distingue el camino limpio de --force).
**Estado:** IN_PROGRESS
**HEAD al inicio:** 44629c8
**delivery_authority:** repo_motor | **deliverable_type:** code

> execution_log de WOT-2026-016s (COMPLETED) preservado en
> `execution_log_WOT-2026-016s.md` antes de este bootstrap.

## Fase 0 - Diagnostico (Orquestador + Manager, EJECUTADO)

- Premisa del backlog ("el PRIMER intento tras mark-ready SIEMPRE da WARN, el SEGUNDO
  cierra") verificada como IMPRECISA. El WARN NO es un bug de primer-vs-segundo intento.
- Causa raiz real: el WARN en `_handle_manager_approve` (.agent/agent_controller.py ~4520)
  se dispara cuando `_check_last_commit` rechaza el ULTIMO commit del repo. El gate ES
  correcto (exige que el ultimo commit referencie el ticket con mensaje no generico). El
  sintoma "segundo intento cierra" ocurria porque entre intentos cambiaba el ultimo commit
  (un churn intermedio invalido quedaba primero; luego un commit valido lo reemplazaba).
- En los cierres de 015l y 016s de esta sesion el WARN NUNCA se reprodujo, porque el ultimo
  commit siempre fue `WOT-2026-XXX: <mensaje significativo>` (referencia el ticket).
- Decision del usuario: el fix es de UX -- mejorar el TEXTO del mensaje (mostrar el commit
  encontrado + distinguir camino limpio de --force), sin tocar la logica del gate.

## Fase 1 - Re-verificacion (EJECUTADO, Builder)

- Localizacion por CONTENIDO (no solo numero de linea) en
  `.agent/agent_controller.py`, HEAD=44629c8:
  - `_CHECKPOINT_KEYWORDS` en linea 1264 (coincide con el plan, sin corrimiento).
  - `_validate_closeout_commit_message` en linea 1267-1317 (coincide).
  - `_check_last_commit` en linea 1320-1351: corre
    `subprocess.run(["git", "log", "-1", "--format=%s"], capture_output=True, text=True, cwd=project_root)`
    y delega en `_validate_closeout_commit_message`. Confirma el patron a reusar
    en Fase 2 (misma llamada, mismo cwd=commit_root).
  - `_handle_manager_approve` en linea 4370. El bloque WARN esta en linea
    4517-4529 (coincide con el rango ~4520-4529 citado en el plan, sin
    corrimiento real):
    - L4517: `if not force_mode and _dt_ma not in {"documentation", "research", "analysis"}:`
    - L4518: `commit_root = _resolve_closeout_commit_root(_dt_ma, plan_content)`
      (confirma que `commit_root` esta disponible en el scope, tal como dice el
      Diagnostico del plan).
    - L4519: `commit_valid, commit_reason = _check_last_commit(commit_root, ticket_id)`
    - L4520-4529: bloque `if not commit_valid:` con el mensaje original de 4
      lineas (`warn_parts` + `warn_msg` + `print(..., file=sys.stderr, flush=True)` +
      `return 1`).
  - Ninguna de estas 4 localizaciones requirio ajuste de rango: el plan fue
    escrito contra el mismo HEAD que el Builder retoma (44629c8), sin commits
    intermedios que movieran las lineas.

- Cobertura actual de `tests/unit/test_manager_approve.py` (leido completo,
  533 lineas, HEAD=44629c8) sobre el contenido del mensaje WARN: **NINGUNA**.
  Evidencia (grep de todos los usos de `_check_last_commit` en el archivo):
  - Los 9 tests de `TestManagerApprove` que parchean `_check_last_commit`
    usan `return_value=(True, "")` (camino feliz, commit_valid=True) EXCEPTO:
    - `test_documentation_ticket_bypasses_commit_check`: usa
      `side_effect=RuntimeError(...)` para probar que la funcion NO se llama
      en absoluto para tickets `documentation` (bypass del bloque completo,
      no ejercita el WARN).
    - `test_code_ticket_validates_last_commit_in_motor_root_for_external_motor_topology`:
      usa `side_effect=_capture_commit_root` que SIEMPRE retorna `(True, "")`
      (solo captura el `root` recibido para verificar topologia motor/destino;
      tampoco ejercita el WARN).
  - `test_blocks_if_not_ready_for_review` produce `result != 0` pero por una
    rama de codigo DISTINTA (el guard de `READY_FOR_REVIEW` en linea ~4494,
    antes de llegar al bloque de commit); tampoco pasa por `commit_valid=False`.
  - Conclusion: 0 tests instancian `commit_valid=False` via mock de
    `_check_last_commit`, por lo que 0 tests leen o capturan el `stderr`
    producido por el bloque WARN (linea 4520-4529). El test nuevo de Fase 3
    (mock `return_value=(False, "<razon>")` + captura de stderr) es cobertura
    genuinamente NUEVA, no duplicada. Confirma la premisa del work_plan
    (Fase 1, segundo punto).

## Fase 2 - Fix del mensaje (EJECUTADO, Builder)

- Cambio aplicado EXCLUSIVAMENTE dentro del bloque `if not commit_valid:`
  (`.agent/agent_controller.py`, linea 4520 en adelante). La condicion de
  L4517 (`if not force_mode and _dt_ma not in {...}:`) y la llamada a
  `_check_last_commit` en L4519 quedan byte-a-byte identicas (verificado por
  lectura post-edicion).
- Se agrego una consulta best-effort del texto literal del ultimo commit
  DENTRO del propio `_handle_manager_approve` (subprocess.run con
  `git log -1 --format=%s`, `cwd=commit_root` -- mismo comando y mismo cwd
  que usa internamente `_check_last_commit`, pero una llamada SEPARADA y
  desechable, solo para fines de presentacion). Envuelta en
  `try/except Exception` silencioso: si `returncode != 0`, si el stdout esta
  vacio tras strip(), o si la excepcion (ej. `FileNotFoundError` si git no
  esta disponible) se dispara, `last_commit_text` queda `None` y esa linea del
  mensaje simplemente se omite -- no se rompe el flujo ni cambia el `return 1`
  ya decidido por el gate.
- Nuevo `warn_parts` (4 lineas cuando se pudo obtener el commit, 3 si no):
  1. `[WARN] Last commit validation failed: {commit_reason}` (sin cambios,
     la razon estructurada existente).
  2. `[WARN] Last commit found: "{last_commit_text}"` (NUEVA, solo si se pudo
     obtener el commit).
  3. `[WARN] Recommended: commit your closeout referencing ticket {ticket_id}
     with a meaningful message (not a generic checkpoint), then retry
     --manager-approve.` (NUEVA -- camino limpio explicito).
  4. `[WARN] Alternatively, if the last commit legitimately cannot reference
     this ticket, use --force to approve anyway.` (NUEVA -- --force
     presentado como alternativa consciente, no como unica salida; contrasta
     con "Alternatively" vs. el texto original que lo listaba como unica
     instruccion final).
- Prefijo `[WARN]` multi-linea mantenido en las 4 lineas. Mensajes en ingles
  (convencion confirmada del archivo: se reviso el estilo de otros bloques
  WARN/ERROR de cierre, ej. linea ~3097-3099 `[ERROR] --mark-ready blocked:
  ... Complete the implementation before marking ready.`, mismo tono
  directivo "Recommended action then retry"). `return 1` y
  `print(warn_msg, file=sys.stderr, flush=True)` sin cambios.
- `_check_last_commit`, `_validate_closeout_commit_message` y
  `_CHECKPOINT_KEYWORDS` NO tocados (verificar con `git diff` acotado en
  Fase 3/gates).

## Fase 3 - Tests + mutation-verify (EJECUTADO, Builder)

- Tests nuevos anadidos a `tests/unit/test_manager_approve.py`
  (clase `TestManagerApprove`, junto a los existentes):
  1. `test_warn_message_is_actionable_and_shows_last_commit`: mockea
     `_check_last_commit` con `return_value=(False, structured_reason)`,
     captura stderr con `sys.stderr = io.StringIO()` / `try/finally`
     restaurando `sys.stderr = sys.__stderr__` (mismo patron ya usado en el
     archivo para stdout), llama `_handle_manager_approve("WP-TEST-001",
     json_output=False, force_mode=False)`, verifica `result == 1` (el
     bloqueo NO cambia) y 3 aserciones sobre `stderr_text`: (a) la razon
     estructurada literal aparece; (b) subcadena literal fija
     `"Recommended: commit your closeout referencing ticket"` +
     `"then retry --manager-approve"`; (c) `"--force"` y `"Alternatively"`
     presentes.
  2. `test_warn_message_shows_real_last_commit_text_from_git`: test de
     integracion con repo git REAL en `tmp_path` (no mock de
     `_check_last_commit`), crea un commit generico
     `"checkpoint: intermediate churn, not a real closeout"` (dispara la
     regla de `_CHECKPOINT_KEYWORDS` real, sin necesidad de fingir extraccion
     de ticket ID), parchea solo `_resolve_closeout_commit_root` para apuntar
     al repo de fixture, y confirma que el `%s` REAL del commit aparece
     verbatim en el stderr capturado -- evidencia de que la consulta
     best-effort en `_handle_manager_approve` no es un mock complaciente sino
     una llamada real a git. DECISION (punto 5 de Fase 3 / Fase 3 del plan):
     se incluyo este test de integracion (no se omitio) porque el costo del
     fixture es bajo (subprocess.run + git init de 3 comandos, ~0.3s) y da
     evidencia end-to-end genuina que el mock del test 1 no puede dar por si
     solo.

- Barrera MUTATION (obligatoria, CEM) -- comando literal y resultados:
  1. Se reverto manualmente el bloque `warn_parts` a su forma ORIGINAL de 4
     lineas (`[WARN] Last commit validation failed: {commit_reason}` /
     `[WARN] The last commit should reference ticket {ticket_id}` /
     `[WARN] with a meaningful message (not a generic checkpoint).` /
     `[WARN] Use --force to approve anyway.`), eliminando por completo el
     bloque de obtencion best-effort del commit y el `warn_parts.extend(...)`.
  2. Comando: `.venv/Scripts/python.exe -m pytest
     tests/unit/test_manager_approve.py -k warn_message -v`
     Resultado SIN FIX (rojo): `2 failed, 13 deselected in 0.32s`.
     Exit code real de pytest (capturado con redireccion a archivo, no via
     `tail`): **1**.
     Fallo observado en `test_warn_message_shows_real_last_commit_text_from_git`:
     `AssertionError: assert 'checkpoint: intermediate churn, not a real
     closeout' in "[WARN] Last commit validation failed: Commit appears to be
     a 'checkpoint' commit, not a meaningful closeout message\n[WARN] The
     last commit should reference ticket WP-TEST-001\n[WARN] with a
     meaningful message (not a generic checkpoint).\n[WARN] Use --force to
     approve anyway.\n"` -- confirma que sin el fix ni el commit literal ni
     la subcadena "Recommended" aparecen. `test_warn_message_is_actionable_and_shows_last_commit`
     tambien fallo (misma causa, subcadenas nuevas ausentes).
  3. Se reaplico el fix completo (restaurado desde copia identica verificada
     con `diff` -- 0 diferencias contra la version post-Fase-2).
  4. Mismo comando re-ejecutado. Resultado CON FIX (verde):
     `2 passed, 13 deselected in 0.30s`. Exit code real de pytest: **0**.

- Regresion cero confirmada: `.venv/Scripts/python.exe -m pytest
  tests/unit/test_manager_approve.py -v` -> **15 passed in 1.05s**, exit
  code **0**. Incluye los 9 tests preexistentes de camino feliz
  (`return_value=(True, "")`) y
  `test_code_ticket_validates_last_commit_in_motor_root_for_external_motor_topology`
  (el `commit_root` capturado no cambio: sigue siendo `motor_root.resolve()`).

## Gates de cierre (exit codes — trazabilidad, finding de Review 1)

- ruff check .agent/agent_controller.py tests/unit/test_manager_approve.py -> All checks passed! (exit 0)
- ruff format --check (mismos archivos) -> 2 files already formatted (exit 0)
- check_encoding_guard.py (archivos tocados) -> exit 0
- run_pytest_safe.py --level all -> 3467 passed, 20 skipped, exit 0, sin state-leak,
  tested_commit_sha == HEAD (275d804)
- agent_controller.py --validate --json --project-root . -> total_errors 0, total_warnings 0

## Dogfooding (verificacion end-to-end del mensaje nuevo)

- Con un commit "checkpoint: intermediate wip" (invalido para closeout) en un repo git tmp,
  el WARN nuevo muestra en vivo: razon estructurada + `[WARN] Last commit found: "checkpoint:
  intermediate wip"` + `Recommended: commit your closeout referencing ticket ... then retry` +
  `Alternatively ... use --force`. El operador ya no necesita correr `git log -1` a mano.

## Review 1 (Manager): APROBADO
- Mutation-verify re-ejecutado independientemente (2 failed sin fix / 15 passed con fix, restaurado
  byte-identico). Diff acotado verificado (gate no tocado). Edge cases del try/except confirmados
  (repo sin commits returncode 128, git ausente FileNotFoundError -> degradan sin romper).
- Finding no-bloqueante: faltaba registrar los exit codes de los gates de cierre en este log
  (esta seccion los añade).
