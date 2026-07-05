# Work Plan - WOT-2026-019d

## Metadata
- **ID:** WOT-2026-019d
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Inventario y correccion de los ~18 usos de str(exc)/{exc}/{e} en
  `.agent/agent_controller.py` con clasificacion PII (follow-up de WOT-2026-019b).
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

WOT-2026-019b corrigio un unico sitio (`_read_pytest_safe_verdict`, linea
2036-2049) donde un `OSError` sin capturar por separado concatenaba la ruta
absoluta local (con username) en el `detail` de un WARN. Su non-goal explicito
dejo pendiente el resto: `.agent/agent_controller.py` tiene 18 ocurrencias
totales de `str(exc)`/`{exc}`/`str(e)`/`{e}` (confirmado por grep en Fase 0 del
Orquestador). De esas 18:

- 1 es un comentario (linea 2039, no es un except real).
- 1 ya esta corregida por WOT-2026-019b (linea 2049, except json.JSONDecodeError,
  ya documentada como segura).
- 16 son excepts reales pendientes de clasificar. Este ticket clasifica las 16 y
  corrige las que sean PII-riesgo.

Este work_plan fija el subconjunto EXACTO de lineas a corregir (clasificacion
verificada leyendo cada bloque try completo en la fuente real, no la tabla
preliminar de la ficha). Los 16 excepts reales se dividen en:

- 12 PII-riesgo (el try puede producir un OSError con .filename poblado por
  I/O de filesystem bajo PROJECT_ROOT): lineas 900, 1007, 1041, 1085, 1888,
  1910, 2219, 2890, 2891 (2890 y 2891 comparten el MISMO bloque except
  Exception as exc, un solo fix cubre ambas), 5342, 5895, 5925.
- 4 seguros (no hay ruta de OSError con filename explotable): lineas 894,
  1614, 1688, 3459.

## Contexto (Fase 0 del Orquestador + clasificacion definitiva de este plan)

### Tabla de clasificacion (16 excepts reales; 2039 comentario y 2049 ya corregida excluidas)

| Linea | Funcion contenedora | Except | Que hace el try | Clasificacion | Evidencia |
|---|---|---|---|---|---|
| 894 | _capture_builder_session | sqlite3.OperationalError | Query a la DB de OpenCode (conn.execute) | SEGURO | sqlite3.OperationalError no tiene .filename; su mensaje describe el error SQL, no una ruta de filesystem. |
| 900 | _capture_builder_session | Exception | Mismo bloque que 894, incluye session_path.write_text sobre _BUILDER_SESSION_PATH (ruta absoluta bajo PROJECT_ROOT) | RIESGO | write_text puede lanzar OSError (PermissionError, disco lleno) con .filename = ruta absoluta local. |
| 1007 | _create_human_gate_approval_request | Exception | store.create_request llama a ApprovalStore.save que llama a self._write_store(store), persiste a archivo bajo el store path | RIESGO | bus/approval.py save/_write_store hacen I/O de archivo; OSError real trae .filename absoluto. Verificado leyendo bus/approval.py lineas 304-308 (save) y 367-392 (create_request). |
| 1041 | _auto_archive_closed_artifacts | Exception | Importa y ejecuta archive_collaboration_artifacts(collaboration_dir=COLLAB_DIR) (mueve/renombra archivos bajo COLLAB_DIR) | RIESGO | Operacion de archivo real (rename/move) sobre rutas absolutas bajo PROJECT_ROOT. |
| 1085 | _check_mark_ready_archive_rename | Exception | Ejecuta check_archive_rename_complete(project_root) de scripts/delivery_hygiene_check.py (inspecciona el arbol de archivos) | RIESGO | Inspeccion de filesystem sobre project_root (ruta absoluta); un fallo de I/O real puede traer .filename. |
| 1614 | _check_declared_deliverables_exist | Exception | from scripts.check_deliverables_exist import extract_paths_from_work_plan; extract_paths_from_work_plan(plan_content) | SEGURO | extract_paths_from_work_plan(content: str) es parsing puro de texto (verificado leyendo scripts/check_deliverables_exist.py lineas 338-341); no hace I/O. El unico riesgo del try es el import (ImportError/ModuleNotFoundError), cuyo mensaje cita el nombre del modulo, no una ruta absoluta arbitraria del usuario. |
| 1688 | _check_implementation_evidence | Exception | from bus.evidence import resolve_evidence; resolve_evidence(_MOTOR_ROOT, PROJECT_ROOT, plan_id) | SEGURO | resolve_evidence (verificado leyendo bus/evidence.py completo) solo ejecuta subprocess.run(git ...) via _run_git_cmd, que ya captura (subprocess.TimeoutExpired, FileNotFoundError, OSError) internamente y devuelve set() en error. resolve_evidence no tiene ninguna llamada directa a open/read_text/write_text. |
| 1888 | _validate_contract_gap_coherence | Exception | bus.read_events(ticket_id=..., event_type=CONTRACT_GAP) llama a _read_raw_events que llama a self.events_path.read_text | RIESGO | Verificado leyendo bus/event_bus.py lineas 84-95 (_read_raw_events): read_text sobre events_path (ruta absoluta bajo el runtime dir) puede lanzar OSError con .filename. |
| 1910 | _validate_contract_gap_coherence | Exception | (contract_gaps_dir / cg_pattern).exists() | RIESGO | Path.exists() de CPython captura OSError solo si errno esta en _IGNORED_ERROS/_IGNORED_WINERRORS (ENOENT, ENOTDIR, EBADF, ELOOP y 3 winerrors); cualquier otro OSError (p. ej. EACCES/permiso denegado, o rutas UNC problematicas) se re-lanza con .filename = contract_gaps_dir / cg_pattern (ruta absoluta). Verificado leyendo el source real de pathlib.Path.exists instalado (_ignore_error). |
| 2219 | create_findings_file | Exception | template_path.read_text mas write_file(findings_path, content) que hace open(path, w) | RIESGO | Ambas operaciones son I/O directo sobre rutas absolutas bajo AGENT_DIR/COLLAB_DIR. |
| 2890 | _run_pre_handoff_guard | Exception | read_file(WORK_PLAN), subprocess.run([sys.executable, guard_script, ...]), _fallback_checkpoint_motor, _resolve_motor_checkpoint_files | RIESGO | read_file hace open(); subprocess.run con ejecutable/script ausente lanza FileNotFoundError con .filename = ruta absoluta del script. Mismo bloque except que 2891. |
| 2891 | _run_pre_handoff_guard | (mismo except que 2890) | (mismo try que 2890) | RIESGO | Mismo bloque; el fix de 2890 cubre automaticamente 2891 (dos print/return que citan el mismo exc, un solo except Exception as exc). |
| 3459 | _handle_resolve_launcher_roots | RuntimeError | _resolve_launcher_roots(PROJECT_ROOT) llama a motor_checkpoint.resolve_launcher_roots | SEGURO | Verificado leyendo .agent/motor_checkpoint.py lineas 397-421: el UNICO raise RuntimeError es f"Cannot resolve empty {key}", donde key es el nombre de una clave de dict (repo_motor_root, repo_destino_root, workspace_activo_root), nunca una ruta. RuntimeError no tiene atributo .filename. |
| 5342 | _handle_reopen_terminal_ticket | Exception | sync_state_projection(runtime_dir=..., collaboration_dir=..., ticket_id=...) llama a state_md_path.write_text | RIESGO | Verificado leyendo scripts/state_projection_sync.py lineas 25-65: write_text sobre collaboration_dir / STATE.md (ruta absoluta) puede lanzar OSError con .filename. |
| 5895 | _handle_session_close | Exception | subprocess.run(cmd) invoca script de cierre mas _sync_state_after_session_close() | RIESGO | subprocess.run con script ausente lanza FileNotFoundError con .filename = ruta absoluta del script/interprete. |
| 5925 | _handle_main_action | Exception | context_dir.mkdir(parents=True, exist_ok=True), scan_project(...), output_path.write_text(...) | RIESGO | mkdir/write_text sobre rutas absolutas bajo PROJECT_ROOT/AGENT_DIR pueden lanzar OSError con .filename. |

### Nota sobre el patron de fix (identico a WOT-2026-019b, NO reinventar)

Para cada uno de los 12 sitios PII-riesgo, el patron probado en 019b
(agent_controller.py funcion _read_pytest_safe_verdict, commit b0d8d7b) es el
UNICO patron autorizado:

1. Si el try puede lanzar tanto OSError como otras excepciones (p. ej.
   Exception generico que en la practica solo captura OSError en el path de
   I/O), separar el except en dos ramas: una especifica except OSError as exc
   y otra que preserva el comportamiento actual para el resto de excepciones
   NO relacionadas con filesystem (mantener except Exception as exc para el
   resto, con su str(exc) intacto si no toca filesystem).
2. Dentro de except OSError as exc, componer el detail/mensaje a mano:
   exc.strerror + exc.errno + (solo si exc.filename no es None) el resultado
   de scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT). NUNCA
   usar str(exc) ni exc.filename crudo dentro de la rama OSError.
3. Guard obligatorio para exc.filename is None (algunos OSError no lo
   traen): en ese caso el detail usa solo strerror+errno, sin intentar
   relativizar None.
4. scope_gate._relativize_scope_path NO se modifica (ya existe, firma
   _relativize_scope_path(path: str, repo_root: Path | None) -> str,
   .agent/scope_gate.py lineas 539-557). Se llama tal cual, mismo patron ya
   usado 15 veces en el archivo (14 previas + el uso de 019b).
5. Si el except Exception original tambien debe seguir capturando
   excepciones no-OSError del mismo try (p. ej. ImportError,
   sqlite3.OperationalError en un try mixto), preservar una segunda rama
   except Exception as exc DESPUES de except OSError as exc para no perder
   cobertura de esas otras excepciones (Python evalua los except en orden;
   OSError debe ir primero para interceptar el caso de filesystem antes de
   que caiga al generico).

### Casos con matiz especifico (leer antes de implementar)

- 900 (_capture_builder_session): el bloque ya tiene DOS excepts separados:
  except sqlite3.OperationalError as exc (894, SEGURO, no tocar) y except
  Exception as exc (900, RIESGO). El fix debe insertar except OSError as exc
  ANTES del except Exception as exc existente (el orden importa: OSError mas
  especifico primero), y dejar except Exception as exc como ultimo recurso
  para cualquier otra excepcion no-OSError del mismo try (p. ej. errores de
  la libreria sqlite3 que no sean OperationalError). NO tocar el except
  sqlite3.OperationalError existente.
- 2890/2891 (_run_pre_handoff_guard): un UNICO except Exception as exc
  produce DOS mensajes que citan exc (el print en 2890 y el warnings en 2891,
  ambos parte del mismo return). El fix es UNA sola insercion de except
  OSError as exc antes del except Exception as exc existente; el detail
  compuesto (sin ruta cruda) se usa en AMBOS lugares donde antes se usaba exc
  (el print y el warnings list).
- 1910 (_validate_contract_gap_coherence, segundo except del par 1888/1910):
  el try de 1910 SOLO contiene (contract_gaps_dir / cg_pattern).exists(), una
  sola expresion. El fix aqui es directo: separar en except OSError as exc
  (compone detail seguro) sin rama adicional except Exception (no hay otro
  tipo de excepcion esperada de .exists() segun el source de pathlib
  verificado).
- 1041 (_auto_archive_closed_artifacts) y 1085
  (_check_mark_ready_archive_rename): ambos try mezclan importlib (que puede
  lanzar excepciones de import, no relacionadas con filesystem directo) con
  la ejecucion de la funcion importada (que SI toca filesystem). Mantener
  except Exception as exc como red de seguridad DESPUES de except OSError as
  exc para no perder cobertura de errores de import.

## Files Likely Touched

### repo_motor

- .agent/agent_controller.py (los 12 sitios PII-riesgo: lineas 900, 1007,
  1041, 1085, 1888, 1910, 2219, 2890, 2891, 5342, 5895, 5925 -- separar
  except OSError con detail seguro via scope_gate._relativize_scope_path)
- tests/test_agent_controller.py (1 test de regresion nuevo por cada uno de
  los 12 sitios PII-riesgo, mas su mutation check documentado; total 12
  tests nuevos como minimo)

## Read/inspect only (Manager-only / no tocar)

- .agent/scope_gate.py (fuente de _relativize_scope_path, linea 539-557; se
  llama, no se edita)
- bus/approval.py (fuente de ApprovalStore.save/_write_store; solo lectura
  para confirmar el patron de I/O, no se edita)
- bus/event_bus.py (fuente de _read_raw_events; solo lectura, no se edita)
- bus/evidence.py (fuente de resolve_evidence; solo lectura para confirmar
  que el sitio 1688 es SEGURO, no se edita)
- scripts/check_deliverables_exist.py (fuente de
  extract_paths_from_work_plan; solo lectura para confirmar que el sitio
  1614 es SEGURO, no se edita)
- scripts/state_projection_sync.py (fuente de sync_state_projection; solo
  lectura, no se edita)
- .agent/motor_checkpoint.py (fuente de resolve_launcher_roots; solo lectura
  para confirmar que el sitio 3459 es SEGURO, no se edita)

## Plan de Implementacion

### PASO 1 (IMPLEMENT) - .agent/agent_controller.py, sitios PII-riesgo

Para cada uno de los 12 sitios (900, 1007, 1041, 1085, 1888, 1910, 2219,
2890, 2891 [mismo bloque que 2890], 5342, 5895, 5925), aplicar el patron
fijado en "Nota sobre el patron de fix" arriba:

1. Insertar except OSError as exc ANTES de cualquier except Exception
   existente del mismo try (Python evalua los excepts en orden de
   aparicion; OSError debe interceptar antes que el generico).
2. Componer el detail/mensaje sin exponer str(exc) ni exc.filename crudo:
   exc.strerror + exc.errno + (si exc.filename no es None)
   scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT).
3. Preservar el resto del mensaje original (prefijos como "[WARN]
   Auto-archive failed: ", "[ERROR] Failed to create HUMAN_GATE approval
   request: ", etc.) intactos; solo cambia la parte que antes era
   {exc}/str(exc).
4. Si el try original solo capturaba Exception (sin otra rama previa),
   mantener una rama except Exception as exc DESPUES de la nueva except
   OSError as exc para no perder cobertura de excepciones no-OSError del
   mismo bloque (import errors, etc.) -- ESA rama sigue usando {exc} tal
   cual (no tiene el problema de PII).
5. NO fusionar los 12 sitios en un helper compartido nuevo: cada sitio
   mantiene su propio bloque except en su funcion, replicando el patron
   inline (igual que 019b hizo para _read_pytest_safe_verdict). Un helper
   compartido esta fuera de scope (ver Non-goals).

Restricciones:
- NO modificar el except sqlite3.OperationalError de la linea 894 (SEGURO,
  no tocar).
- NO modificar los 4 sitios SEGURO (894, 1614, 1688, 3459): en su lugar,
  anadir un comentario breve de una linea en cada uno citando WOT-2026-019d
  y la razon de por que NO se toca (ver PASO 2, documentacion).
- NO modificar la logica de negocio de ninguna de las 10 funciones tocadas
  (_capture_builder_session, _create_human_gate_approval_request,
  _auto_archive_closed_artifacts, _check_mark_ready_archive_rename,
  _validate_contract_gap_coherence, create_findings_file,
  _run_pre_handoff_guard, _handle_reopen_terminal_ticket,
  _handle_session_close, _handle_main_action): solo el manejo del except y
  la composicion del detail/mensaje de error cambian.
- NO tocar .agent/scope_gate.py (_relativize_scope_path se usa tal cual
  existe).
- NO barrer str(exc)/{exc} fuera de .agent/agent_controller.py (non-goal
  explicito de la ficha).

DoD Paso 1:
- [ ] Los 12 sitios PII-riesgo (900, 1007, 1041, 1085, 1888, 1910, 2219,
      2890, 2891, 5342, 5895, 5925) ya NO pueden emitir una ruta absoluta
      local en su mensaje cuando el try lanza un OSError con .filename
      poblado.
- [ ] Cada sitio usa scope_gate._relativize_scope_path(exc.filename,
      PROJECT_ROOT) cuando exc.filename existe, y cae a
      solo-strerror-mas-errno cuando exc.filename es None.
- [ ] El bloque 2890/2891 se corrige con UNA sola insercion de except
      OSError (no duplicar el fix en dos sitios distintos del codigo).
- [ ] Los 4 sitios SEGURO (894, 1614, 1688, 3459) llevan un comentario de
      una linea citando WOT-2026-019d y la razon (sin cambiar su logica).
- [ ] Ninguna otra rama de las 10 funciones tocadas cambia de
      comportamiento (diff no debe tocar logica fuera del except).
- [ ] ruff check .agent/agent_controller.py y ruff format --check
      .agent/agent_controller.py exit 0.

### PASO 2 (IMPLEMENT) - tests/test_agent_controller.py, 12 tests de regresion

Para cada uno de los 12 sitios PII-riesgo, anadir un test de regresion nuevo
siguiendo el MISMO patron de monkeypatch usado en 019b
(test_read_pytest_safe_verdict_oserror_detail_has_no_absolute_path,
tests/test_agent_controller.py lineas 511-554):

1. Localizar (o crear, si no existe una clase de test dedicada a la funcion
   en cuestion) la clase de test correspondiente a cada funcion tocada.
2. Forzar el OSError real en el punto de I/O especifico de cada sitio
   (monkeypatch.setattr sobre el metodo puntual: Path.write_text,
   Path.read_text, Path.exists, Path.mkdir, o subprocess.run/
   FileNotFoundError segun corresponda a cada try), con exc.filename = ruta
   absoluta DENTRO de tmp_path/PROJECT_ROOT simulado.
3. Aserciones minimas por test (identicas en espiritu a las de 019b):
   - El mensaje/detail resultante NO contiene la ruta absoluta simulada
     completa (str(tmp_path) o el path exacto usado en el monkeypatch no
     debe aparecer).
   - El mensaje/detail NO contiene str(Path.home()) (el username real de la
     maquina que ejecuta el test).
   - El mensaje/detail SI contiene <REPO_ROOT> o el basename del archivo
     (segun si el path simulado cae dentro o fuera de PROJECT_ROOT).
   - La informacion de diagnostico util (strerror, errno) se conserva en el
     mensaje.
4. Mutation check por cada uno de los 12 tests (documentar en
   execution_log.md, NO dejar el codigo revertido en el commit final):
   revertir temporalmente el fix del sitio correspondiente (volver a except
   Exception as exc con {exc}/str(exc) directo) y confirmar que el test
   nuevo FALLA (la ruta absoluta reaparece); restaurar el fix y confirmar
   que vuelve a pasar. Citar el resultado de pytest de cada mutation (al
   menos el nombre del test + PASS/FAIL) en execution_log.md.

Restricciones:
- Los 12 tests deben ser deterministicos: construir la ruta absoluta
  simulada dentro de tmp_path, no depender del username real de la maquina
  de CI.
- NO borrar ni modificar ningun test existente de
  tests/test_agent_controller.py.
- Si una funcion de las 10 tocadas no tiene aun una clase de test dedicada
  (verificar con grep antes de asumir), el Builder puede crear una clase
  nueva siguiendo el estilo de las existentes (class Test<Funcion>:), pero
  documentar en execution_log.md cual eligio y por que.

DoD Paso 2:
- [ ] 12 tests de regresion nuevos anadidos (uno por sitio PII-riesgo,
      2890/2891 pueden compartir un unico test si el mismo monkeypatch
      cubre ambos usos de exc dentro del mismo bloque -- documentar la
      eleccion).
- [ ] Los 12 (u 11 si 2890/2891 se cubren con un solo test) pasan en verde
      tras el fix.
- [ ] Mutation check documentado en execution_log.md para cada uno:
      revertir el fix puntual hace FALLAR su test correspondiente.
- [ ] Ningun test existente de tests/test_agent_controller.py se rompe
      (correr el archivo completo, no solo los tests nuevos).
- [ ] ruff check tests/test_agent_controller.py y ruff format --check
      tests/test_agent_controller.py exit 0.

### PASO 3 (VERIFY) - Verificacion final combinada

Comandos (Builder ejecuta, cita salida literal en execution_log.md):

.venv\Scripts\python.exe -m pytest tests/test_agent_controller.py -v

ruff check .agent/agent_controller.py tests/test_agent_controller.py

ruff format --check .agent/agent_controller.py tests/test_agent_controller.py

Y la suite canonica completa antes de mark-ready (obligatoria: el propio
gate de pre-handoff lee el stamp que corrige 019b, dogfooding continuo):

.venv\Scripts\python.exe scripts/run_pytest_safe.py

## Quality Gates

- Builder ejecuta:
  - .venv\Scripts\python.exe -m pytest tests/test_agent_controller.py -v
    (exit 0, incluyendo los 12 tests de regresion nuevos).
  - ruff check .agent/agent_controller.py tests/test_agent_controller.py
    (exit 0).
  - ruff format --check .agent/agent_controller.py
    tests/test_agent_controller.py (exit 0).
  - .venv\Scripts\python.exe scripts/run_pytest_safe.py (suite completa,
    stamp fresco sobre HEAD; level=all, exit_code=0).
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - .venv\Scripts\python.exe .agent\agent_controller.py --validate --json
    --project-root .

## STOP conditions

- Si algun sitio de la tabla de clasificacion NO se comporta como describe
  este plan al leer el codigo en el momento de implementar (p. ej. el try
  cambio de forma desde que se escribio este plan): documentar en
  execution_log.md con prefijo hipotesis: si no esta 100% verificado, y
  escalar antes de aplicar un fix distinto al patron fijado.
- Si scope_gate._relativize_scope_path no esta accesible como
  scope_gate._relativize_scope_path en algun sitio (p. ej. import faltante
  en el scope de esa funcion): DETENTE y escala, no inventes un helper
  propio duplicado.
- Si el fix de cualquiera de los 12 sitios rompe un test YA existente de
  tests/test_agent_controller.py: DETENTE, escala antes de seguir; no
  fuerces el test existente a pasar cambiando su asercion.
- Si durante la implementacion el Builder identifica un 17mo sitio no
  contemplado en el grep de Fase 0 (p. ej. una variante no cubierta por el
  patron de busqueda usado): documentar en execution_log.md como hallazgo,
  NO corregirlo en este ticket (fuera del subconjunto exacto fijado), y
  sugerir un ticket de seguimiento.

## Non-goals

- NO reescribir la logica de las 10 funciones tocadas: solo el manejo del
  except y la composicion del detail/mensaje.
- NO barrer str(exc)/{exc} fuera de .agent/agent_controller.py.
- NO crear un helper compartido nuevo para componer el detail (el patron se
  replica inline en cada sitio, igual que 019b).
- NO modificar .agent/scope_gate.py ni la firma de _relativize_scope_path.
- NO tocar los 4 sitios SEGURO (894, 1614, 1688, 3459) mas alla de anadir
  un comentario de una linea documentando por que no se tocan.
- NO modificar bus/approval.py, bus/event_bus.py, bus/evidence.py,
  scripts/check_deliverables_exist.py, scripts/state_projection_sync.py ni
  .agent/motor_checkpoint.py (solo lectura para confirmar clasificacion).

## Riesgos

- Bajo-medio: 12 sitios distintos en 10 funciones distintas del mismo
  archivo incrementan el blast radius respecto a 019b (que toco 1 sitio),
  pero cada fix individual es identico en forma al patron ya probado y
  revisado en 019b; el riesgo se mitiga con un test + mutation check por
  sitio.
- Bajo: el bloque compartido 2890/2891 podria inducir al Builder a
  duplicar el fix en dos lugares en vez de reconocer que es un unico
  except; mitigado con la nota explicita en "Casos con matiz especifico".
- Bajo: Path.exists() (sitio 1910) re-lanzando OSError es un caso poco
  frecuente en la practica (solo con errores de permiso o rutas UNC
  problematicas), pero el fix es identico al resto y no anade complejidad
  extra.
- Bajo: encontrar el punto de monkeypatch quirurgico correcto para cada
  uno de los 12 sitios puede requerir iteracion (distintos metodos:
  write_text, read_text, exists, mkdir, subprocess.run) -- mitigado con la
  STOP condition explicita de documentar hipotesis si no esta verificado.

## Decision Arquitectonica

Replicar el patron de 019b sitio por sitio (sin abstraer un helper
compartido nuevo) porque: (a) cada sitio ya tiene su propio prefijo de
mensaje ("[WARN] Auto-archive failed: ", "[ERROR] Failed to create
HUMAN_GATE..." etc.) que un helper generico tendria que parametrizar sin
ganancia real de mantenibilidad; (b) 019b establecio precedente de fix
inline revisado y aprobado; introducir abstraccion nueva en un ticket de
"solo mensajes de error" es sobre-ingenieria fuera del non-goal declarado
("no reescribir la logica de las funciones tocadas").

## Decision sobre REVIEW

Single-review basta (no se exige Review 2 adversarial). Justificacion:
- Blast radius por sitio identico al de 019b (ya aprobado con
  single-review): cambia solo el manejo de un except y la composicion de
  un mensaje de diagnostico, sin tocar logica de negocio de ninguna
  funcion.
- El fix reusa integramente un helper ya existente y probado
  (scope_gate._relativize_scope_path, con su propia cobertura de tests de
  WOT-2026-016e), no introduce logica nueva de relativizacion.
- Los 12 sitios son independientes entre si (no hay interaccion cruzada:
  cada uno vive en su propia funcion), por lo que el riesgo de romper un
  sitio al corregir otro es bajo, y cada uno queda cubierto por su propio
  test + mutation check.
- Prioridad Baja de la ficha original, deliverable_type=code, mismo patron
  ya validado en el ciclo anterior.

## Criterios de Aceptacion Global (1:1 con el DoD de la ficha)

- [ ] Tabla de los 16 excepts reales (18 grep hits menos 1 comentario menos
      1 ya corregida por 019b) con clasificacion PII-riesgo/seguro y
      justificacion, presente en execution_log.md (replicando o citando la
      tabla de este work_plan).
- [ ] Cada uno de los 12 usos PII-riesgo corregido: la ruta absoluta con
      username NUNCA llega al mensaje/detail final cuando el try lanza
      OSError con .filename poblado.
- [ ] Test de regresion + mutation check documentado para cada uno de los
      12 sitios (o 11 tests si 2890/2891 comparten uno solo, documentado
      explicitamente por que).
- [ ] Los 4 usos SEGURO (894, 1614, 1688, 3459) documentados con un
      comentario de una linea en el codigo y una entrada en
      execution_log.md explicando por que no se tocan.
- [ ] Ningun test existente de tests/test_agent_controller.py se rompe.
- [ ] ruff check y ruff format --check exit 0 sobre ambos archivos
      tocados.
- [ ] .venv\Scripts\python.exe scripts/run_pytest_safe.py verde (stamp
      fresco sobre HEAD, level=all, exit_code=0).
- [ ] .venv\Scripts\python.exe .agent\agent_controller.py --validate
      --json --project-root . exit 0/0 tras el cierre.
