# Work Plan - WOT-2026-016t

## Metadata
- **ID:** WOT-2026-016t
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** manager-approve: el mensaje del WARN por commit invalido no es accionable
  (no muestra el commit encontrado ni distingue el camino limpio de --force)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Reescribir el TEXTO del mensaje [WARN] (criterio de aceptacion 3 fija el contenido exacto) que _handle_manager_approve emite cuando
_check_last_commit rechaza el ultimo commit (.agent/agent_controller.py, bloque
~4520-4529), sin tocar cuando se dispara ni la logica de validacion. Verificacion del
objetivo (comando literal):
.venv/Scripts/python.exe -m pytest tests/unit/test_manager_approve.py -k warn_message -v
pasa, y el mensaje capturado en stderr incluye (a) el texto del ultimo commit encontrado
(el %s real via commit_reason/_check_last_commit), (b) una instruccion explicita del
camino limpio (commitear referenciando el ticket y reintentar), y (c) una mencion de
--force como alternativa consciente (no la unica salida ofrecida).

## Diagnostico (causa raiz verificada, reemplaza la premisa del backlog)

La ficha de backlog dice: "el PRIMER intento tras mark-ready SIEMPRE devuelve WARN sin
cerrar, y el SEGUNDO intento identico cierra canonicamente". Verificado en el codigo y
releido contra los cierres reales de esta sesion (015l, 016s): esa premisa es IMPRECISA.

- El WARN se emite en _handle_manager_approve (.agent/agent_controller.py:4517-4529),
  solo cuando force_mode es False, el deliverable_type no es
  documentation/research/analysis, y _check_last_commit(commit_root, ticket_id)
  (linea 4519, definida en linea ~1320) devuelve commit_valid=False.
- _check_last_commit corre "git log -1 --format=%s" sobre commit_root (resuelto por
  _resolve_closeout_commit_root) y delega en _validate_closeout_commit_message
  (linea ~1267), que rechaza el mensaje si: (1) contiene alguna keyword de
  _CHECKPOINT_KEYWORDS = {checkpoint, pre-handoff, wip, interim}; (2) no
  referencia ningun ticket ID (extract_all_ticket_ids); (3) referencia un ticket ID
  DISTINTO al active_id. Si el ultimo commit incluye el active_id con contenido
  significativo, _validate_closeout_commit_message devuelve (True, "") y el WARN no se
  dispara.
- Es decir: el gate ES correcto por diseno -- exige que el ultimo commit del repo, en el
  momento del approve, referencie el ticket activo con un mensaje no generico. NO es un bug
  de "primer intento vs segundo intento": se dispara siempre y solo cuando el ultimo commit
  no cumple esa regla, sin importar si es el primer o el enesimo intento de approve.
- El sintoma "el primer intento falla, el segundo (identico) cierra" que motivo la ficha
  ocurria porque, entre ambos intentos, el ULTIMO COMMIT del repo cambiaba: un commit
  intermedio invalido para closeout (churn de mark-ready, mensajes tipo checkpoint o sin el
  ticket ID) quedaba como el mas reciente en el primer intento; luego, sin que el operador
  lo notara explicitamente en el mensaje del WARN (que no muestra el commit encontrado), se
  hacia un commit adicional que si referenciaba el ticket, y el SEGUNDO approve entonces
  encontraba un commit valido y cerraba. El bug real no es de logica sino de UX: el mensaje
  actual no le dice al operador CUAL fue el commit que disparo el rechazo, asi que la causa
  parece aleatoria/temporal en vez de deterministica.
- Mensaje actual (.agent/agent_controller.py:4521-4525):
  [WARN] Last commit validation failed: {commit_reason}
  [WARN] The last commit should reference ticket {ticket_id}
  [WARN] with a meaningful message (not a generic checkpoint).
  [WARN] Use --force to approve anyway.
  commit_reason ya trae la razon estructurada (ej. "Commit references [X] but active
  ticket is Y", o "Commit message does not reference any ticket ID"), pero en ningun punto
  se imprime el TEXTO LITERAL del ultimo commit (%s real), obligando al operador a correr
  git log -1 por su cuenta para diagnosticar. Tampoco distingue explicitamente "esto es lo
  que deberias hacer en el 99% de los casos" (commitear referenciando el ticket y
  reintentar) de "esto es un escape consciente para el caso legitimo minoritario" (--force).

## Decision Arquitectonica

- Se toca EXCLUSIVAMENTE el bloque de construccion del mensaje WARN en
  _handle_manager_approve (.agent/agent_controller.py, lineas ~4520-4529). No se
  modifica _validate_closeout_commit_message, _CHECKPOINT_KEYWORDS,
  _check_last_commit, ni la condicion que decide SI se dispara el WARN (linea 4517: sigue
  siendo "not force_mode and _dt_ma not in {...}" seguido de "if not commit_valid").
- Para mostrar el commit encontrado sin cambiar la firma publica de _check_last_commit
  (que hoy devuelve (bool, str) y ya se usa en 2 tests con return_value/side_effect
  fijos), la opcion mas simple y de menor blast radius es que _handle_manager_approve (que
  ya tiene commit_root disponible en el scope, linea 4518) corra su propia consulta ligera
  del commit para mostrarlo. Se elige: NO tocar _validate_closeout_commit_message
  (mantiene su contrato con mensajes de razon estructurados, reusados en otros sitios) y en
  su lugar, en _handle_manager_approve, obtener el texto del ultimo commit con una llamada
  directa (subprocess.run con git log -1 --format=%s, cwd=commit_root, mismo
  patron que usa _check_last_commit internamente) SOLO para fines de mensaje, envuelta en
  try/except silencioso (si git falla aqui, se omite esa linea del mensaje en vez de romper
  el flujo -- el gate ya fallo por otra razon mas arriba). Alternativa descartada: cambiar
  _check_last_commit/_validate_closeout_commit_message para que devuelvan tambien el
  commit crudo -- se descarta por tocar una firma consumida por multiples tests existentes
  sin necesidad (mayor blast radius para el mismo resultado).
- El nuevo mensaje sigue siendo multi-linea con prefijo [WARN] (consistente con el resto
  del archivo) e incluye, en este orden: (1) la razon estructurada existente (sin cambios);
  (2) el texto literal del ultimo commit encontrado, cuando se pudo obtener; (3) el camino
  limpio recomendado, explicito (ej. Recommended: commit the closeout referencing
  ticket_id then retry manager-approve, o equivalente en el idioma ya usado por el
  resto de los mensajes del archivo -- inspeccionar convencion de idioma antes de escribir
  el texto final); (4) --force presentado como alternativa consciente para el caso en que
  el ultimo commit legitimamente no pueda referenciar el ticket, no como unica salida.
- El valor de retorno (return 1) y el destino (sys.stderr, flush=True) del bloque NO
  cambian: solo cambia el contenido de warn_parts/warn_msg.

## Fases

### Fase 1 - Re-verificacion del diagnostico (obligatoria antes de tocar codigo)
- Releer .agent/agent_controller.py funciones _handle_manager_approve (~4370-4550),
  _check_last_commit (~1320), _validate_closeout_commit_message (~1267) y la constante
  _CHECKPOINT_KEYWORDS (~1264). Confirmar que el bloque WARN sigue en las lineas citadas
  (pueden haber corrido +/- unas lineas por commits intermedios; localizar por contenido,
  no solo por numero de linea).
- Confirmar que ningun test existente en tests/unit/test_manager_approve.py cubre HOY el
  contenido exacto del mensaje WARN (los tests actuales solo mockean
  _check_last_commit con return_value=(True, ""), camino feliz). Documentar el hallazgo
  en execution_log.md antes de escribir el fix (evidencia de que la Fase 2 anade
  cobertura nueva, no duplicada).

### Fase 2 - Fix del mensaje
- En _handle_manager_approve, dentro del bloque "if not commit_valid:" (~4520-4529),
  anadir la obtencion del texto del ultimo commit (best-effort, try/except silencioso,
  usando commit_root ya resuelto en la linea anterior) y reconstruir warn_parts segun la
  Decision Arquitectonica: razon estructurada + commit encontrado (si se pudo obtener) +
  camino limpio explicito + --force como alternativa consciente.
- No modificar la condicion "if not force_mode and _dt_ma not in {...}:" (linea 4517) ni la
  llamada a _check_last_commit (linea 4519): el fix es estrictamente el contenido de
  warn_parts/warn_msg y la obtencion best-effort del commit para mostrarlo.
- Revisar el idioma/tono de los demas mensajes [WARN]/[ERROR]/[OK] del archivo para
  que el texto nuevo sea consistente (el archivo usa ingles en los mensajes de consola;
  mantener esa convencion).

### Fase 3 - Tests (barrera + mutation)
- En tests/unit/test_manager_approve.py, anadir un test (ej.
  test_warn_message_is_actionable_and_shows_last_commit o nombre equivalente) que:
  1. Mockee _check_last_commit con return_value=(False, razon estructurada de
     ejemplo) (patron ya usado por los tests existentes de la clase, ver
     test_code_ticket_validates_last_commit_in_motor_root_for_external_motor_topology
     para el estilo de mock con side_effect/return_value).
  2. Capture stderr (redireccion manual sys.stderr = io.StringIO() con
     try/finally restaurando sys.stderr = sys.__stderr__, mismo patron ya usado en el
     archivo para stdout con json_output=True; aqui el WARN va a stderr).
  3. Llame _handle_manager_approve(ticket_id, json_output=False, force_mode=False) y
     verifique result == 1 (el comportamiento de bloqueo NO cambia).
  4. Verifique en el texto capturado de stderr: (a) que aparece la razon estructurada
     pasada al mock; (b) que aparece una mencion explicita del camino limpio (buscar una
     subcadena estable, ej. retry o commit + ticket_id segun el texto final elegido
     en Fase 2 -- el test debe fijar la subcadena literal que Fase 2 produce, no una
     parafrasis); (c) que --force sigue mencionado como alternativa.
  5. Si _check_last_commit real (no mockeado) es facil de ejercitar con un repo git de
     tmp_path con un commit generico (ej. mensaje checkpoint), anadir tambien un test
     de integracion mas fino que confirme que el commit real mostrado en el mensaje
     coincide con el %s del commit creado en el fixture (evidencia de que "se obtiene el
     commit encontrado" no es solo un mock complaciente). Si el costo de fixture de git real
     no se justifica frente al mock ya validado en el punto 1-4, documentar la decision en
     execution_log.md en vez de omitir la barrera sin explicacion.
- Barrera MUTATION (obligatoria, CEM): revertir manualmente el texto del mensaje al
  original (las 4 lineas citadas en el Diagnostico) y confirmar que el/los test(s) nuevos
  de este ticket FALLAN (no encuentran las subcadenas nuevas). Reaplicar el fix y confirmar
  verde. Documentar el comando exacto y el resultado (rojo sin fix / verde con fix) en
  execution_log.md.
- Confirmar que TODA la suite de tests/unit/test_manager_approve.py (no solo el test
  nuevo) sigue en 100% passed tras el fix -- en particular los tests que mockean
  _check_last_commit con return_value=(True, "") (camino feliz, no deben pasar por el
  bloque WARN en absoluto) y
  test_code_ticket_validates_last_commit_in_motor_root_for_external_motor_topology (que
  el commit_root capturado no cambie).

## Criterios de aceptacion

1. El bloque "if not commit_valid:" en _handle_manager_approve
   (.agent/agent_controller.py) sigue disparandose bajo EXACTAMENTE la misma condicion
   que hoy (not force_mode and _dt_ma not in documentation/research/analysis y
   commit_valid is False) -- verificable por inspeccion de diff: la linea 4517 y la
   llamada a _check_last_commit en 4519 no cambian de semantica.
2. _validate_closeout_commit_message y _check_last_commit no tienen diff (0 lineas
   modificadas) -- verificable por git diff acotado a esas funciones.
3. El mensaje WARN nuevo, cuando se dispara, incluye: (a) el texto del ultimo commit
   encontrado (cuando se pudo obtener via git), (b) una instruccion explicita del camino
   limpio (commitear referenciando el ticket y reintentar el approve), (c) --force
   mencionado como alternativa consciente (no como unica salida). Verificable ejecutando:
   .venv/Scripts/python.exe -m pytest tests/unit/test_manager_approve.py -k warn_message -v
4. MUTATION: revertir el texto del mensaje a su forma original hace fallar el/los test(s)
   nuevos de Fase 3 (no encuentran las subcadenas nuevas). Evidencia rojo-sin-fix /
   verde-con-fix documentada en execution_log.md con el comando literal.
5. Regresion cero: .venv/Scripts/python.exe -m pytest tests/unit/test_manager_approve.py -v
   da 100% passed (ningun test preexistente se rompe, incluidos los que mockean el camino
   feliz return_value=(True, "")).
6. ruff check y ruff format --check sobre .agent/agent_controller.py y
   tests/unit/test_manager_approve.py: 0 errores.
7. Suite canonica: scripts/run_pytest_safe.py --level all termina en exit 0, sin
   state-leak (.agent/collaboration/ intacto tras la corrida salvo lo que este propio
   ticket declare).
8. .agent/agent_controller.py --validate --json --project-root . termina en exit 0, 0
   errors, 0 warnings al cierre.

## Files Likely Touched

### repo_motor
- .agent/agent_controller.py (fix del texto del mensaje WARN dentro de
  _handle_manager_approve, bloque ~4520-4529; no toca _check_last_commit ni
  _validate_closeout_commit_message)
- tests/unit/test_manager_approve.py (test nuevo: mensaje WARN accionable, con mutation)

## Non-goals

- NO cambiar _validate_closeout_commit_message (las 4 reglas de rechazo -- keywords de
  checkpoint, sin ticket ID, ticket ID distinto -- son correctas y no se tocan).
- NO cambiar CUANDO se dispara el WARN (la condicion en la linea 4517 y la llamada en 4519
  quedan identicas).
- NO tocar el flujo de cierre posterior (cascada de eventos, sync de markdowns,
  _clear_auxiliary_states, _reset_circuit_breaker, _release_builder_lock): ese codigo
  vive DESPUES del bloque WARN y solo se alcanza cuando commit_valid es True o
  force_mode es True; no cambia.
- NO anadir un tercer modo/flag nuevo (ej. --dry-run-approve): el ticket es estrictamente
  UX del mensaje existente, no una superficie nueva de CLI.
- NO tocar _CHECKPOINT_KEYWORDS ni anadir/quitar keywords.
- NO relajar el return 1 del bloque (el approve sigue bloqueado sin --force cuando el
  commit no es valido).
