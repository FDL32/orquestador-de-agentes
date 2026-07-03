# Work Plan - WOT-2026-016s

## Metadata
- **ID:** WOT-2026-016s
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** mark-ready: el parser de Files Likely Touched descarta el path cuando el bullet lleva anotacion descriptiva tras la ruta
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Corregir `scope_gate.py` para que un bullet de la seccion Files Likely Touched con anotacion
descriptiva tras el path (ej. `scripts/x.py` (nuevo, el gate)) siga resolviendo a un
path valido, en vez de ser descartado por completo. Verificacion del objetivo (comando
literal): `pytest tests/unit/test_scope_gate.py -k trailing_annotation` pasa, y sobre un
`work_plan.md` cuyo FLT usa la subseccion `repo_motor` con bullets anotados,
`parse_files_likely_touched` y `parse_flt_raw_buckets` devuelven un whitelist NO vacio con
exactamente los paths esperados, dejando de emitir el warning de ausencia de seccion FLT.

## Diagnostico (causa raiz verificada, reemplaza la premisa del backlog)

La ficha de backlog atribuye el WARN a que el parser "no reconoce subsecciones
(repo_motor)". Eso es impreciso. Verificado en vivo (evidencia literal):

- La llamada scope_gate._looks_like_path_token con el argumento "scripts/x.py (nuevo)"
  devuelve False (.agent/scope_gate.py, checkea: si hay un espacio en el token, devuelve False).
- Sobre el work_plan.md real de WOT-2026-015l (que SI usa la subseccion repo_motor y bullets
  del tipo: scripts/check_closeout_reconciliation.py (nuevo, el gate)), tanto
  parse_files_likely_touched(content, project_root=...) como
  parse_flt_raw_buckets(content) devuelven whitelist/buckets VACIOS.
- La subseccion repo_motor SI se reconoce (_parse_flt_section la detecta y le asigna
  namespace "motor" correctamente) -- el problema ocurre DESPUES, cuando esa misma funcion
  (y las otras dos rutas de parseo) normalizan la linea con _normalize_flt_line y validan
  con _looks_like_path_token, que rechaza cualquier token con espacio. La anotacion
  descriptiva ("(nuevo)", "(el gate)", "(fix del parser)") queda pegada al path tras la
  normalizacion, asi que el bullet completo se descarta.
- Las TRES rutas de parseo del modulo comparten exactamente _normalize_flt_line +
  _looks_like_path_token: _extract_section_paths (usada por parse_files_likely_touched
  y parse_forbidden_surfaces), _section_path_tokens (usada por files_likely_touched_tokens),
  y _parse_flt_section (usada por parse_flt_namespaced/parse_flt_raw_buckets/
  parse_flt_raw_paths). Arreglar la fuente compartida arregla las tres de una vez (patron
  AP-D04: una sola fuente de verdad).

## Decision Arquitectonica

- Fix en _normalize_flt_line (.agent/scope_gate.py): tras la limpieza actual de
  bullets/backticks/comillas, quedarse SOLO con el primer token separado por espacio (el
  path), descartando cualquier anotacion posterior. No se toca _looks_like_path_token (ya
  es correcta como validador de "esto es un solo token sin espacios"): el fix ocurre antes,
  en la normalizacion, para que el token que le llega ya venga sin anotacion.
- Un bullet sin anotacion (bullet simple tipo "file1.py") sigue normalizando exactamente
  igual que hoy (no hay segundo token que recortar) -- el fix es aditivo, no cambia el
  comportamiento actual para el caso ya cubierto por test_parse_simple_files /
  test_parse_with_bullets_and_quotes.
- No se modifica _looks_like_path_token, _parse_flt_section (deteccion de namespace), ni
  la resolucion de motor_root/project_root: el fix es estrictamente en la extraccion del
  token de path, sin tocar la semantica de namespaces ya correcta.
- Non-goal explicito de esta decision: scripts/check_deliverables_exist.py tiene una
  funcion paralela _resolve_flt_bullet_tokens que reimplementa el mismo criterio (rechaza
  el bullet si el texto normalizado contiene un espacio) y comparte el mismo bug (su propio
  docstring dice que reproduce el comportamiento de scope_gate._normalize_flt_line /
  _looks_like_path_token). NO se toca en este ticket: ese script solo corre para
  deliverable_type documental/mixed (no es la ruta que emite el WARN de mark-ready
  reportado), y tocarlo amplia el blast radius sin evidencia de que este ticket lo
  requiera. Se deja como deuda explicita para un ticket futuro (mismo patron, mismo fix,
  otro archivo).

## Fases

### Fase 1 - Fix del parser compartido
- Modificar _normalize_flt_line en .agent/scope_gate.py: despues de aplicar el
  lstrip/replace/strip actual, partir el resultado por el primer espacio y devolver solo
  esa primera porcion (si el resultado limpio no es vacio).
- No modificar la firma de la funcion (sigue recibiendo line: str y devolviendo str).
- No modificar ningun call-site: los tres consumidores (_extract_section_paths,
  _section_path_tokens, _parse_flt_section) siguen llamando _normalize_flt_line igual
  que hoy; heredan el fix automaticamente.

### Fase 2 - Tests (barrera + mutation)
- En tests/unit/test_scope_gate.py, dentro de TestParseFilesLikelyTouched, anadir
  test_parse_flt_with_trailing_annotation_after_path: contenido con un bullet del tipo
  scripts/foo.py (nuevo, el gate) bajo la seccion FLT (sin subseccion, para probar la ruta
  plana parse_files_likely_touched/_extract_section_paths) debe hacer que
  parse_files_likely_touched(content, project_root=_MOTOR_ROOT) devuelva un set con
  exactamente la ruta resuelta de scripts/foo.py (no vacio, no incluye la anotacion).
- En tests/unit/test_scope_gate_topology.py, anadir
  test_namespaced_motor_annotated_path_resolves (o nombre equivalente en el estilo del
  archivo): contenido con la subseccion repo_motor y un bullet scripts/bar.py (nuevo) debe
  hacer que parse_flt_raw_buckets(content) devuelva bucket motor con exactamente
  "scripts/bar.py" y bucket destino vacio (namespace correcto Y path limpio, no vacio).
- Barrera mutation-verify (obligatoria, CEM): revertir manualmente el fix (restaurar
  _normalize_flt_line a su forma actual sin el split) y confirmar que AMBOS tests nuevos
  fallan (whitelist/bucket vacio en vez del path esperado). Documentar el comando y el
  resultado (rojo sin fix / verde con fix) en execution_log.md.
- Confirmar que los tests preexistentes de la familia (test_scope_gate.py,
  test_scope_gate_topology.py, test_scope_gate_deliverable_aware.py,
  test_scope_gate_isolation.py) siguen en verde tras el fix (regresion cero sobre el
  comportamiento de bullets sin anotacion).

### Fase 3 - Verificacion end-to-end contra el sintoma original
- Reproducir el WARN original: parse_files_likely_touched y parse_flt_raw_buckets sobre
  el work_plan.md HISTORICO de WOT-2026-015l (contiene la subseccion repo_motor con bullets
  anotados) deben devolver ahora un whitelist/bucket NO vacio con los 2 paths declarados
  (scripts/check_closeout_reconciliation.py,
  tests/unit/test_check_closeout_reconciliation.py). Usar el archivo real via
  AUDIT_WOT-2026-015l.md o historial git si work_plan.md ya fue sobrescrito por este mismo
  ticket (ver checklist de handoff del Manager); si no esta accesible en disco, reconstruir
  el fragmento FLT exacto citado en el Diagnostico como fixture de regresion en el test de
  Fase 2 en su lugar.

## Criterios de aceptacion

1. La llamada scope_gate._normalize_flt_line con el argumento de bullet
   "- scripts/x.py (nuevo, el gate)" (con backticks reales alrededor de scripts/x.py en el
   input, tal como aparece en un work_plan.md real) devuelve exactamente "scripts/x.py" sin
   la anotacion. Verificable ejecutando:
   .venv/Scripts/python.exe -m pytest tests/unit/test_scope_gate.py -k trailing_annotation -v
2. test_parse_flt_with_trailing_annotation_after_path (Fase 2) verde: whitelist no vacio,
   path exacto sin anotacion.
3. test_namespaced_motor_annotated_path_resolves (Fase 2) verde: bucket motor no vacio,
   bucket destino vacio, path exacto sin anotacion.
4. MUTATION: revertir el fix en _normalize_flt_line hace que ambos tests de Fase 2 fallen
   (whitelist/bucket vuelve a vacio). Evidencia rojo-sin-fix / verde-con-fix documentada en
   execution_log.md.
5. Regresion cero: pytest sobre tests/unit/test_scope_gate.py,
   tests/unit/test_scope_gate_topology.py, tests/unit/test_scope_gate_deliverable_aware.py
   y tests/unit/test_scope_gate_isolation.py da 100% passed (ni un test preexistente se
   rompe).
6. ruff check y ruff format --check sobre .agent/scope_gate.py,
   tests/unit/test_scope_gate.py y tests/unit/test_scope_gate_topology.py: 0 errores.
7. Suite canonica: scripts/run_pytest_safe.py --level all termina en exit 0, sin
   state-leak (.agent/collaboration/ intacto tras la corrida salvo lo que este propio
   ticket declare).
8. .agent/agent_controller.py --validate --json --project-root . termina en exit 0, 0
   errors, 0 warnings al cierre.

## Files Likely Touched

### repo_motor
- `.agent/scope_gate.py` (fix del parser: extrae solo el primer token de cada bullet)
- `tests/unit/test_scope_gate.py` (test nuevo: anotacion tras el path, ruta plana)
- `tests/unit/test_scope_gate_topology.py` (test nuevo: anotacion tras el path, con namespace)

## Non-goals

- NO tocar _looks_like_path_token (el validador de token-sin-espacios sigue siendo
  correcto; el fix ocurre antes, en la normalizacion).
- NO tocar la semantica de deteccion de namespaces (subsecciones repo_motor/repo_destino) en
  _parse_flt_section: ya funciona, el bug estaba en el paso posterior compartido.
- NO tocar scripts/check_deliverables_exist.py / _resolve_flt_bullet_tokens (misma
  familia de bug, pero fuera de scope de este ticket; ver Decision Arquitectonica). No
  crear ticket de seguimiento formal en este plan: queda anotado en el diagnostico para
  que el Manager lo capture en backlog si lo considera necesario.
- NO cambiar el flujo de mark-ready mas alla del parser (el flag de scope-override sigue
  disponible como via de escape; este ticket reduce cuando hace falta usarlo, no lo
  elimina).
- NO relajar _looks_like_path_token para aceptar tokens con espacios en el path en si
  (rutas con espacios reales en el nombre de archivo no son un caso soportado ni antes ni
  despues de este fix).
