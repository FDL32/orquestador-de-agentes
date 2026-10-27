# work_plan - WOT-2026-129y

## Metadata

- **ID:** WOT-2026-129y
- **Estado:** APPROVED
- ticket: WOT-2026-129y
- flight: vuelo-20261026b (sesion implantacion IM-2, threadId
  mcp:b1ba6927-036e-447a-8e26-8d3fad9f4e55, host `opencode/nan/mimo-v2.6-flash`)
- branch: `flight/WOT-2026-129y` (base `f7604ead` = punta REAL de
  `flight/vuelo-20261026b` verificada con `git rev-parse` en el AUTORIZA;
  NO se uso el HEAD de 129d)
- **deliverable_type:** code
- delivery_authority: repo_motor
- status: APPROVED (AUTORIZA de OR-3 en este hilo, 2026-10-27, cadena
  129d->129y; ficha backlog.md:2557-2567)
- fecha: 2026-10-27

## Premisa (verificada en vivo, PASO 1)

- `check_loop_execution.py:110-131`: `DEFAULT_MIN_DISTINCT_BACKENDS` con
  `code=4` y `FALLBACK_MIN_DISTINCT=4` (fail-closed); `--min-distinct`
  CLI en `:974` y `audit(..., min_distinct=...)` en `:758-771` "gana sobre
  deliverable_type" SIN piso -> bypass silencioso actual (premisa del DoD).
- El gate YA esta CABLEADO: `prepush_check.py:2491` importa
  `check_loop_execution.audit` (import ESTATICO para check_guard_wiring,
  WOT-2026-059b) y lo corre por commit en `run_loop_execution_check`
  (`:2507`). La firma `audit()` debe mantenerse retrocompatible (kwargs
  nuevos con default), o el cableado rompe.
- `agents.json::ensemble_registry` = {backend_keys (51; BA51, BA06, BA10
  y BA150 figuran con `status: active`, es decir el registry NO refleja
  exclusiones del vuelo), loop_shapes, statuses (enum activo/deprecated/
  archived)}. `_validate_config` NO valida subclaves de `ensemble_registry`
  (agents_config.py:471-528 solo valida profiles/pipelines/private_roots)
  -> anadir una clave es retrocompatible. La proyeccion
  `discover_loops.py:70-85` es WHITELIST (loop_ids/backend_keys/details/
  statuses) -> una clave nueva NO rompe la paridad de
  `docs/registry/loop_registry.md` (test_loop_registry).
- El roster del vuelo es EXTERNO no versionado (`Proyectos_Python/.../
  flight_roster.json`), con 0 consumidores en `scripts/` (medido en 129c)
  y editable solo por la orquestadora. La verdad de elegibilidad por fase
  vive hoy ahi: `session_types.implantacion.lenses.MANAGER_REVIEW=[BA03]`
  + `revisor_repo_motor_interino.backend_key=BA07` -> maximo alcanzable 2
  (medido en vivo: MR-A de 129d -> FAIL 2/4, nonce b3a9eee3).
- Evidencia previa: MR-A 129d sobre `9f18e5d1` con 2/2 `DECISION: APPROVE`
  (BA07 chars=292034, BA03 chars=245823, bundle_sha 199f7368) y aun asi
  `check_loop_execution` FAIL 2/4 -> decision C de OR-3 (journal 11:05).
- Tests existentes: `tests/unit/test_check_loop_execution.py` (1663 lineas)
  llama `cle.audit_commit(sc, emitted, commit_sha=..., min_distinct=N)` a
  nivel unidad (firma intocable) y `test_prepush_loop_execution_blocking.py`.

## DoD de mecanismo (ficha backlog.md:2564, literal)

1. Una unica fuente declarada determina, para cada fase y
   delivery_authority, el conjunto de `backend_key` elegibles y el minimo
   alcanzable.
2. El gate falla de forma explicita si el contrato exige mas claves que las
   elegibles, nombrando fase, tipo, roster y minimo, sin contar union de
   nonces ni reutilizar precedentes.
3. Cuando la politica permita derivar el minimo de la cobertura declarada,
   el derivado conserva independencia, misma instancia/nonce y no puede
   convertir un deliverable `code` en `documentation`.
4. Tests negativos y positivos con cobertura realista: 2 claves frente a
   minimo 4, 4 claves elegibles en una instancia, claves excluidas/
   retiradas, y rondas repartidas entre nonces.
5. La solucion no autoriza retrospectivamente WOT-2026-129d ni cambia su
   evidencia.
6. Cableado visible del gate y recibo reproducible con `commit_sha`,
   `loop_id`, `nonce`, claves elegibles y minimo aplicado.

## Decision Arquitectonica

Motivo de cada decision, con su por que:

- **D1 - FUENTE UNICA = campo declarado
  `agents.json::ensemble_registry.eligible_coverage` (NO el roster
  leido).** Motivo: (a) los llamadores REALES (`prepush_check.audit`,
  cierre, CLI) lo consumen sin ningun plumbing nuevo - el roster es un
  fichero EXTERNO no versionado que exigiria `--roster` en prepush/cierre
  y romperia el cableado existente; (b) `agents.json` ya es la config
  versionada de claves (`ensemble_registry.backend_keys`, 51 claves) y su
  validador acepta claves nuevas retrocompatiblemente; (c) cumple el
  no-goal "no editar flight_roster.json" por construccion; (d) la deriva
  roster->campo es FAIL-SAFE: si el roster gana claves y el campo no, el
  gate SUBESTIMA la cobertura (nunca sobre-aprueba). El roster sigue siendo
  la expectativa de sesion (independencia) - este gate no lo lee ni lo
  sustituye. La palabra "roster" del DoD 2 se materializa aqui como
  `coverage_source: agents.json::ensemble_registry.eligible_coverage`,
  nombrado en el fallo explicito y en el recibo.
- **D2 - Formato de la entrada**: clave `"<PHASE>:<DELIVERY_AUTHORITY>"`
  (p. ej. `"MANAGER_REVIEW:repo_motor"`); valor:
  `{"backend_keys": [...], "min_distinct": <int>, "policy":
  "declared"|"strict", "excluded_backend_keys": [opcional],
  "exempt_tickets": [opcional]}`. Validacion fail-closed de la
  DECLARACION (motivo invalido -> veredicto fail con reason
  `invalid_coverage`): keys no vacias sin duplicados y con cada una
  presente en `ensemble_registry.backend_keys`; `min_distinct` entero >=2 y
  <= len(backend_keys); `policy` en el enum; sin claves que esten a la vez
  en `backend_keys` y `excluded_backend_keys`.
- **D3 - Elegibilidad FILTRA el conteo**: con cobertura presente, solo
  cuentan hacia N las backend_key de las rondas que esten en
  `backend_keys` MINUS `excluded_backend_keys` MINUS claves con
  `ensemble_registry.backend_keys.<k>.status != "active"` (retiradas/
  archivadas -> la declaracion vencida NO cuenta; receipt las lista en
  `no_contadas` con reason). Sin entrada de cobertura -> comportamiento
  LEGACY intacto (cualquer clave distinta cuenta, min=policy). Filtro solo
  dentro de entradas declaradas: cero cambio para flujos sin cobertura.
- **D4 - Politica por entrada**: `policy: "declared"` ->
  `min_aplicado = min_distinct` declarado (DoD 3: conserva >=2 claves
  distintas = piso de independencia; misma instancia/nonce SIN cambios;
  el receipt imprime `deliverable_type` y `policy_min` junto a
  `min_aplicado`, la transparencia reemplaza a la reclasificacion -
  NUNCA se cambia el tipo). `policy: "strict"` (o entrada ausente) ->
  `min_aplicado = min_distinct_for(deliverable_type)` (4 para code); si
  ademas hay entrada y len(elegibles) < min -> FALLA EXPLICITA ANTES de
  mirar rondas (DoD 2) nombrando fase, tipo, coverage_source, elegibles y
  minimo - "sin union de nonces ni reutilizar precedentes" = el conteo
  sigue POR nonce/instancia (logica existente intacta) y la unica exencion
  es la lista declarada `exempt_tickets`, no un precedente narrativo.
- **D5 - `--min-distinct` sin bypass (mandato OR-3)**: con cobertura
  `policy: declared`, un `--min-distinct M` con M < min_distinct declarado
  -> RECHAZADO (veredicto fail, reason `override_below_declared_min`,
  rc!=0): no puede invalidar el minimo derivado. M >= declarado -> se
  aplica (mas estricto) y SIEMPRE se registra en el recibo
  (`min_origen: cli-override`, valor, base declarada): no silencioso.
  Sin cobertura: M < min_distinct_for(dtype) -> se aplica pero con WARN
  explicito por stderr y registro en recibo (`override_below_policy`):
  ruidoso, no bloqueante (compatibilidad con usos existentes); M >= ->
  normal + recibo. El override NUNCA baja del piso absoluto 2.
- **D6 - DoD 5 (no retro-autorizar 129d)**: `exempt_tickets:
  ["WOT-2026-129d"]` en la entrada. Si las rondas de un commit llevan
  ticket eximido, la cobertura NO se aplica: se evalua con politica
  estricta (code=4) -> 129d sigue FAIL 2/4 con la evidencia intacta.
  Mecanismo declarado en el campo (no un precedente en prosa).
- **D7 - Cableado (DoD 6)**: NO se mueve el import estatico de
  `prepush_check.py:2491` ni su `audit()`-llamada; los cambios entran por
  kwargs opcionales con default legacy. `check_guard_wiring.py` se ejecuta
  en gates para probar que el guard sigue CABLEADO. La propagacion de
  `delivery_authority` desde `loop_execution_targets.txt` al `audit()` de
  prepush queda como DEUDA DECLARADA (fuera de FLT: tocaría
  session_closeout/targets), con la consecuencia explicita: prepush corre
  hoy en modo legacy (min policy) hasta que esa deuda se cierre.
- **D8 - Recibo reproducible (DoD 6)**: `audit()`/CLI emiten un bloque
  JSON `{"loop_exec_receipt": {...}}` determinista con `ticket`,
  `commit_sha`, `loop_id`, nonces, `distinct_backends` contados,
  `eligible_declared`, `eligible_effective`, `no_contadas` [{key,
  reason}], `deliverable_type`, `policy_min`, `min_aplicado`,
  `min_origen` (policy|eligible_coverage|cli-override),
  `coverage_key`, `override`, `ok`. Salida por stdout; dos corridas
  identicas -> mismo receipt (test).

## Files Likely Touched

- scripts/check_loop_execution.py
- .agent/config/agents.json
- tests/unit/test_check_loop_execution.py
- CHANGELOG.md
- .agent/collaboration/work_plan.md
- .agent/collaboration/execution_log.md
- .agent/collaboration/STATE.md

## Fases y tareas

1. **F1 - cobertura declarada (agents.json) + resolucion (gate)**
   - T1.1: anadir `ensemble_registry.eligible_coverage` con la entrada
     `MANAGER_REVIEW:repo_motor` = backend_keys [`BA03`,`BA07`],
     min_distinct 2, policy declared, excluded [`BA05`] (129r: no
     elegible en repo_motor hasta su decision), exempt
     [`WOT-2026-129d`] (D6). Claves escogidas COPIANDO la verdad del
     roster (no inventadas); el ticket NO edita el roster.
   - T1.2: en `check_loop_execution.py`: `load_coverage(config, phase,
     delivery_authority)` + `validate_coverage_entry()` (D2) +
     `effective_eligible()` (D3: minus excluidas minus status != active).
   - T1.3: `audit(..., phase=None, delivery_authority=None, config=None)`
     retrocompatible; resolucion de minimo D4; override D5; exemption D6.
2. **F2 - fallos explicitos + receipt (DoD 2/6)**
   - T2.1: mensaje de contrato inalcanzable nombrando fase, tipo,
     coverage_source, elegibles, minimo (rc!=0).
   - T2.2: bloque `loop_exec_receipt` (D8) en `audit()` y CLI; WARN
     stderr para override-below-policy (D5).
   - T2.3: flags CLI `--phase` (default MANAGER_REVIEW) y
     `--delivery-authority` (default None -> sin cobertura -> legacy).
3. **F3 - tests (DoD 4 + CAs)**: ver Criterios. Anadir al fichero
   existente; NO tocar la firma `audit_commit`.
4. **F4 - CHANGELOG** entrada del ticket.
5. **F5 - gates focales**: ruff check/format sobre FLT, pytest del fichero
   de tests con ancla de resumen, py_compile, `check_guard_wiring.py`
   (cableado), `check_encoding_guard` sobre FLT. SIN suite canonica, SIN
   push. Despues: MR-A por OR-3 (bundle con foco: checker modificado,
   override, 2-vs-4, 4 elegibles, excluidas/retiradas, nonces separados).

## Riesgos

- R1 (alto): cambiar el conteo solo DENTRO de entradas declaradas; sin
  entrada el camino legacy es byte-identico -> la suite de 1663 lineas
  existente debe quedar VERDE sin ediciones de firma.
- R2: auto-aplicacion - el MR de 129y correria con el checker nuevo y la
  entrada declarada (min 2) en su propia rama; OR-3 lo sabe y exige al
  Revisor auditarlo explicitamente (foco del bundle). El DoD 5 protege
  129d; 129y se revisa bajo la politica que propia y declaradamente
  introduce - el receipt lo hace transparente (D4/D8).
- R3: edicion de agents.json -> hooks de pre-commit (json validos,
  encoding); la proyeccion del registry y el validador de config se
  verifican en F5 (premisa medida arriba).
- R4: scope creep hacia prepush/targets/session_closeout -> DEUDA
  DECLARADA en D7, fuera de FLT; si una lente lo propone como blocker,
  escalar (es ampliacion de alcance, no del DoD).

## Criterios de aceptacion (invariantes)

- CA1 (DoD 1/3): con entrada `MANAGER_REVIEW:repo_motor`
  (declared, min 2, [BA03,BA07]) y UNA instancia/nonce con 2 rondas
  sustantivas de BA03+BA07 -> ok=True, receipt con
  min_aplicado=2 y min_origen=eligible_coverage, deliverable_type=code y
  policy_min=4 visibles (no reclasificado).
- CA2 (DoD 2): misma entrada con policy strict (fixture) y min policy 4
  > 2 elegibles -> fallo EXPLICITO nombrando fase, tipo, coverage_source,
  elegibles y minimo; rc!=0; el mensaje NO depende de las rondas (falla
  aunque las 2 rondas existan).
- CA3 (DoD 4): 4 claves elegibles declaradas (fixture) con 4 rondas en la
  MISMA instancia/nonce -> ok=True con distinct=4; y con 2+2 rondas
  REPARTIDAS en dos nonces -> cada nonce se evalua por separado (sin
  union), ok=False y receipt lista los nonces.
- CA4 (DoD 4): ronda de clave en `excluded_backend_keys` -> no cuenta
  (receipt no_contadas con reason); clave con registry status != active
  (config fixture) -> no cuenta; en ambos casos si el resto no llega al
  minimo -> ok=False.
- CA5 (DoD 5): filas con ticket `WOT-2026-129d` bajo la entrada
  declarada -> la cobertura NO aplica (exenta), min vuelve a 4 y el
  veredicto de 2 rondas queda ok=False (evidencia de 129d intacta).
- CA6 (DoD 6/OR-3): `--min-distinct 1` con entrada declared min 2 ->
  fail `override_below_declared_min` (rc!=0, no bypass); `--min-distinct
  3` -> aplica 3 y el recibo lo registra; sin cobertura con dtype=code y
  override 2 -> WARN por stderr + override en recibo (nada silencioso).
- CA7: legacy - sin `eligible_coverage` en la config, `audit()` produce
  exactamente el comportamiento de min policy actual (suite existente
  verde sin cambios de firma) y `check_guard_wiring.py` sigue contando el
  guard cableado (rc 0, 0 UNDECLARED).
- CA8: ruff check/format verdes en los ficheros FLT; pytest del fichero
  con linea de resumen anclada "N passed"; receipt determinista (dos
  corridas -> mismos campos).
- CA9: el gate NUNCA convierte el tipo: cada salida con cobertura lleva
  deliverable_type original + policy_min + min_aplicado separados.

## Non-goals

- NO editar `flight_roster.json` (ni ningun fichero de la carpeta del
  vuelo); NO readmitir BA110/BA150 ni habilitar BA05 para repo_motor
  (BA05 solo figura como EXCLUIDO declarado en la entrada, coherente con
  129r); NO bajar el umbral reclasificando `code` a `documentation`.
- NO tocar `prepush_check.py`/`session_closeout.py`/targets (deuda D7).
- NO cambiar la firma `audit_commit` ni la logica de nonce/sustantividad
  existente; NO tocar prompts; NO fusionar, pushear ni correr suite
  canonica en este ticket.
