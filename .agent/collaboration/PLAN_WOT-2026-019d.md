# PLAN - WOT-2026-019d

Ticket: WOT-2026-019d - Inventario y correccion de los ~18 usos de
str(exc)/{exc}/{e} en .agent/agent_controller.py con clasificacion PII
(follow-up de WOT-2026-019b).
Estado: APPROVED
delivery_authority: repo_motor | deliverable_type: code

Este documento es la estrategia tecnica breve del ticket; el contrato
completo (tabla de clasificacion, criterios, gates, STOP conditions) vive en
work_plan.md. Si algo difiere entre ambos, work_plan.md manda.

## Resumen del problema

WOT-2026-019b corrigio un unico sitio (_read_pytest_safe_verdict, lineas
2036-2049) donde un except combinado (OSError, json.JSONDecodeError) con
f"stamp ilegible: {exc}" filtraba la ruta absoluta local (con username) via
str(OSError). Su non-goal dejo pendiente el resto de usos de str(exc)/{exc}
en el mismo archivo. Grep confirma 18 lineas totales con el patron
(str(exc)|{exc}|{e}|str(e)): 1 es comentario (2039), 1 ya corregida por 019b
(2049), y 16 son excepts reales pendientes de clasificar.

## Clasificacion definitiva (leyendo cada bloque try completo)

De los 16 excepts reales:

- 12 PII-riesgo (el try puede producir OSError con .filename poblado por I/O
  de filesystem bajo PROJECT_ROOT): lineas 900 (_capture_builder_session,
  write_text de sesion), 1007 (_create_human_gate_approval_request,
  ApprovalStore.save/_write_store), 1041 (_auto_archive_closed_artifacts,
  mueve archivos), 1085 (_check_mark_ready_archive_rename, inspecciona
  arbol), 1888 (_validate_contract_gap_coherence, read_text de
  events.jsonl), 1910 (_validate_contract_gap_coherence, Path.exists puede
  re-lanzar OSError segun _ignore_error de pathlib), 2219
  (create_findings_file, read_text+write_file), 2890/2891
  (_run_pre_handoff_guard, mismo bloque except, read_file+subprocess.run),
  5342 (_handle_reopen_terminal_ticket, sync_state_projection escribe
  STATE.md), 5895 (_handle_session_close, subprocess.run del script de
  cierre), 5925 (_handle_main_action, mkdir+write_text del project-map).
- 4 seguros: 894 (sqlite3.OperationalError, sin .filename), 1614
  (extract_paths_from_work_plan es parsing puro de string, sin I/O), 1688
  (resolve_evidence solo ejecuta git via subprocess con manejo interno de
  OSError, sin I/O directo propio), 3459 (RuntimeError con mensaje fijo
  "Cannot resolve empty '<key>'", sin ruta).

## Estrategia (patron identico a 019b, replicado 12 veces)

1. Para cada uno de los 12 sitios PII-riesgo: separar except OSError as exc
   (nuevo, primero en el orden) de cualquier except Exception as exc
   existente (se mantiene despues, como red de seguridad para excepciones
   no-OSError del mismo try).
2. Dentro de except OSError as exc: componer el mensaje con exc.strerror +
   exc.errno + (si exc.filename no es None)
   scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT). Nunca
   str(exc) ni exc.filename crudo.
3. El bloque 2890/2891 comparte un unico except: un solo fix cubre ambos
   usos de exc (el print de 2890 y el warnings de 2891).
4. Los 4 sitios seguros se documentan con un comentario de una linea
   citando WOT-2026-019d, sin cambiar su logica.
5. Anadir 1 test de regresion por sitio PII-riesgo en
   tests/test_agent_controller.py, siguiendo el patron de monkeypatch de
   019b (test_read_pytest_safe_verdict_oserror_detail_has_no_absolute_path):
   forzar OSError con filename bajo tmp_path, verificar ausencia de ruta
   absoluta y presencia de <REPO_ROOT>/basename en el mensaje.
6. Mutation check por cada uno de los 12 tests: revertir el fix puntual,
   confirmar que el test falla; restaurar, confirmar que pasa. Documentar
   ambos resultados en execution_log.md.
7. Confirmar que los tests existentes de tests/test_agent_controller.py
   siguen en verde tras el cambio.
8. Correr gates: pytest completo del archivo, ruff check, ruff format
   --check, suite canonica run_pytest_safe.py (level=all, stamp fresco
   sobre HEAD).
9. Commitear en repo_motor con WOT-2026-019d en el mensaje, mark-ready,
   esperar review del Manager (validate es Manager gate).

## Archivos tocados

- .agent/agent_controller.py (12 sitios PII-riesgo + comentarios en los 4
  sitios seguros)
- tests/test_agent_controller.py (12 tests de regresion nuevos, o 11 si
  2890/2891 comparten uno solo)

## Criterios de cierre

Identicos a work_plan.md seccion "Criterios de Aceptacion Global". No
duplicados aqui para evitar deriva; ver work_plan.md como fuente unica de
los comandos exactos.
