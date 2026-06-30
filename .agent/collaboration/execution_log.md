# Execution Log - WOT-2026-017a

**Ticket:** WOT-2026-017a - PRE_EXISTING_SUITE_RED
**Estado:** READY_FOR_REVIEW
**HEAD al inicio:** 4f3d698
**HEAD post-commit:** fddc0ca

---

## Gates ejecutados

### G1 - Encoding
```
python scripts/check_encoding_guard.py scripts/run_pytest_safe.py scripts/pre_handoff_guard.py tests/test_pre_handoff_guard.py tests/unit/test_run_pytest_safe.py
```
Exit code: 0 (sin output = limpio)

### G2 - Suite del motor (run_pytest_safe.py --level all)
Primera ejecucion (con work_plan.md del Manager sin commitear):
- Exit code: 1
- Resultado: 3403 passed, 20 skipped, 8 failed, 5 errors
- Los 8 fallos son todos TestPreHandoff + TestBuilderBriefExclusion causados
  por work_plan.md no commiteado (entorno del Manager, no regresiones de codigo).
  Verificado con git stash: sin mis cambios de codigo y con work_plan.md modificado,
  los mismos 8 tests fallan.
- last-run.json post-run: contiene failed_test_ids (8 ids de TestPreHandoff)
  y baseline_failed_test_ids=[].

Post-commit (HEAD=fddc0ca), re-ejecucion pendiente tras Review-1 CAMBIOS_REQUERIDOS.

### G3 - T1-T5 presentes y verdes
```
python -m pytest tests/test_pre_handoff_guard.py::TestPreExistingSuiteRed -v
```
Exit code: 0
- T1 (heredado permite): PASSED
- T2 (nuevo bloquea): PASSED
- T3a (last_run_missing): PASSED
- T3b (unparseable json): PASSED
- T3c (failed_test_ids ausente con exit!=0): PASSED
- T3d (nivel incorrecto): PASSED
- T4 (mutation mismo conteo distinto id): PASSED
- T5 (regresion guard): PASSED - pre-fix bloquea T1, post-fix permite T1 y bloquea T2/T4

### G4 - failed_test_ids en last-run.json (unit tests)
```
python -m pytest tests/unit/test_run_pytest_safe.py::TestFailedTestIdsParsing tests/unit/test_run_pytest_safe.py::TestFailedTestIdsInSummary -v
```
Exit code: 0 (7 parseo + 3 integration incluyendo carry-forward = 10 tests total)

### G5 - Gates existentes preservados
```
python -m pytest tests/test_pre_handoff_guard.py::TestCanonicalSuiteGreenGate -v
```
Exit code: 0 - todos los tests de SHA, level, args_mode siguen pasando.

### G6 - Campo failed de directorios intacto
```
grep "\"failed\"" scripts/run_pytest_safe.py
```
Lineas 284, 786, 788, 906, 912 - campo failed de limpieza no tocado.

### G7 - Sin override
```
grep "force.suite|ignore.fail|bypass" scripts/pre_handoff_guard.py
```
Exit code: 0 (sin matches)

### G8 - preflight_closeout.py no modificado
Firma de assert_canonical_suite_green no cambia. tests/unit/test_preflight_closeout.py: 10 passed.

### Ruff
Exit codes: 0, 0 (check y format --check)

---

## Divergencia de diseno documentada: carry-forward vs commit-base

El PLAN D3 define B como "baseline disponible en disco" sin especificar si es el
run del commit base del ticket o el run inmediatamente anterior. La restriccion
CEM (no archivo baseline separado, no re-run en caliente) hace ambigua la
procedencia de B cuando hay multiples runs durante el ticket.

DECISION IMPLEMENTADA: carry-forward.
baseline_failed_test_ids = los failed_test_ids del last-run.json en disco ANTES
de que el run actual lo sobreescriba. Este campo se captura en main() de
run_pytest_safe.py al inicio de cada run.

JUSTIFICACION:
1. Es la unica forma coherente de tener B != A con un solo archivo last-run.json
   (sin archivo separado y sin re-run en caliente).
2. El PLAN D3 dice "baseline disponible en disco" - en ausencia de otro mecanismo,
   "disponible en disco" es el contenido del archivo justo antes de ser sobreescrito.
3. Permite T1-T5 del AUDIT ser implementados y verificados.
4. El caso normal (un solo run al final del ticket) funciona correctamente:
   B = fallos del run pre-ticket, A = fallos del run del Builder.

LIMITACION (R3 actualizado, D5c no cubre este caso):
Si durante el ticket se corren multiples suites (p.ej. un run con work_plan.md sin
commitear que activa gate uncommitted_work_plan y produce fallos de entorno), el
baseline del siguiente run contiene esos fallos transitorios, no los pre-existentes
reales. D5c NO cubre este caso (D5c solo cubre cuando el campo esta ausente).
La mitigacion operativa: garantizar que el run que precede al handoff se ejecuta
con arbol limpio y todos los artefactos commiteados.

EJEMPLO CONCRETO EN ESTE TICKET:
El run de la suite durante la implementacion tuvo work_plan.md sin commitear ->
8 tests de TestPreHandoff fallaron. El last-run.json resulto con
baseline_failed_test_ids=[] y failed_test_ids=[8 ids de TestPreHandoff].
No hubo falso-verde porque el run final fue exit_code=1 y la suite del motor
para este ticket delivery_authority=repo_motor debe tener exit_code=0.

---

## Archivos modificados

- scripts/run_pytest_safe.py: stream_pytest devuelve tuple[int, list[str]];
  main() persiste failed_test_ids y baseline_failed_test_ids; # noqa: C901.
- scripts/pre_handoff_guard.py: bloqueo binario sustituido por logica subconjunto
  D3: D5c (ausente->bloquea), D7 (nivel), subset (A subset B->permite),
  regresion (A-B!={}->bloquea).
- tests/test_pre_handoff_guard.py: clase TestPreExistingSuiteRed con T1-T5 (8 tests).
- tests/unit/test_run_pytest_safe.py: TestFailedTestIdsParsing (7 tests) +
  TestFailedTestIdsInSummary (3 tests incluyendo carry-forward).
- scripts/preflight_closeout.py: NO tocado (firma no cambia).
- .agent/collaboration/AUDIT_WOT-2026-017a.md: R3 actualizado con nota de
  implementacion carry-forward y aclaracion de que D5c no cubre falsos-rojos.

---

## Cierre: doble revision adversarial (HEAD c91c976)

### Review 1 (Manager)
Primera pasada: VEREDICTO CAMBIOS_REQUERIDOS. Hallazgos: (1) carry-forward sin test
de cobertura; (2) decision arquitectonica (campo baseline_failed_test_ids) sin
documentar; (3) AUDIT R3 malcitaba D5c como mitigacion. Tambien corrigio el analisis
del orquestador: la contaminacion del baseline NO se propaga al proximo ticket (el
siguiente run lee failed_test_ids, no baseline_failed_test_ids).
Tras aplicar los 3 cambios (commit c91c976): VEREDICTO APROBADO.

### Review 2 (fresh-context, independiente)
VEREDICTO: APROBADO_PARA_HANDOFF. Sin ruta de falso-verde para regresiones de codigo
(un test VERDE->ROJO siempre emite linea FAILED -> el parser la captura -> A-B!={} ->
bloquea). Sin bypass. Mutacion (mismo conteo, distinta identidad) bloqueada. Gates
pre-existentes (level/args_mode/SHA) intactos. 92/92 tests dirigidos, exit 0.

### Hallazgo no bloqueante de Review 2 -> FOLLOW-UP (fuera de scope de 017a)
CASO BORDE: exit_code=1 + failed_test_ids=[] + baseline cualquiera -> PERMITE handoff
(porque {} es subconjunto de todo). Ocurre cuando la suite falla SIN que ningun test
individual falle: state-leak (run_pytest_safe fuerza exit_code=1, l.908-913), errores
de coleccion que pytest reporta como ERROR (no FAILED), o XPASS strict. NO es
falso-verde para regresiones del codigo entregado (esas siempre emiten FAILED), pero
SI deja pasar un state-leak activo. Riesgo medio, documentado.
FOLLOW-UP a abrir (ticket nuevo, p.ej. WOT-2026-017b): el guard debe leer el campo
state_leak del last-run.json (y/o tratar exit_code!=0 con failed_test_ids=[] como
fail-closed) y BLOQUEAR ese caso. No se incluye en 017a porque excede su contrato
(distinguir rojo heredado de regresion por identidad de test-id), ya aprobado.


Scope override: deuda tickets 015x previos sin pushear (commits pre-base 4f3d698); diff de codigo 017a acotado a guard/runner/tests; override evidenciado y auditable. Affected files: C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes\prompts\audit_agent_output.md, C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes\tests\integration\test_memory_integration.py, C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes\tests\test_manager_review_bridge.py

---

## Fix reapertura (state-leak falso-verde) - WOT-2026-017b sobre WOT-2026-017a

**HEAD al inicio del fix:** 327d6a3 (motor verde, 3412 passed segun memoria previa al fix).

### El bug (hallazgo de review esceptica, confirmado en codigo antes de tocar nada)

En `assert_canonical_suite_green` (scripts/pre_handoff_guard.py), rama
`if exit_code != 0:` (L502 antes del fix), el D5c original solo cubria
`"failed_test_ids" not in data` (campo AUSENTE). Si el campo estaba PRESENTE
pero VACIO (`[]`) con `exit_code != 0` -- caso real: pytest crashea en
coleccion, recibe OOM/SIGKILL, o cualquier state-leak que fuerza exit_code=1
sin que pytest llegue a emitir una sola linea `FAILED <node-id>` -- entonces:
- `a_set = set([])` (vacio).
- `new_failures = a_set - b_set` siempre vacio (un set vacio es subconjunto
  de cualquier otro set).
- El guard devolvia `(True, {"reason": "inherited_failures_subset"})`:
  HANDOFF PERMITIDO sobre una suite que en realidad fallo de forma OPACA
  (sin enumerar ningun test). El reason "inherited_failures_subset" ademas
  mentia: no hubo herencia ni exito, hubo silencio del runner.

Este hallazgo fue documentado como follow-up no bloqueante en el cierre de
WOT-2026-017a (ver seccion "Hallazgo no bloqueante de Review 2" arriba) y
es el motivo de la reapertura.

### El fix aplicado

Un (1) discriminante nuevo en scripts/pre_handoff_guard.py, JUSTO DESPUES de
`exit_code = data.get("exit_code"); if exit_code != 0:`, ANTES de cualquier
otro gate (D7 level/args_mode, comparacion de subconjunto, SHA freshness):

```python
if not (data.get("failed_test_ids") or []):
    return False, {
        **base_diag,
        "reason": "nonzero_exit_but_no_failed_ids (state-leak suspected)",
        "canonical_suite_error": (
            f"Canonical suite exit_code={exit_code!r} but "
            "failed_test_ids is empty: the suite failed without "
            "enumerating any test (collection crash, OOM/SIGKILL, or a "
            "state-leak). This is an opaque failure, not an "
            "inherited-subset pass. Investigate the run log "
            "(.agent/runtime/pytest-safe/last-run.log), then re-run: "
            "python scripts/run_pytest_safe.py --level all"
        ),
    }
```

`data.get("failed_test_ids") or []` normaliza AMBAS formas (campo ausente
-> `.get()` devuelve `None` -> `or []` da `[]`; campo presente vacio ->
ya es `[]`) a la misma decision: `not []` es `True` -> bloquea. Esto cubre
el caso original de la reapertura (presente-vacio) Y el caso D5c viejo
(ausente) con UN solo guard.

### Decision: REEMPLAZAR el D5c viejo (Opcion A), no mantenerlo en paralelo

Elegi que el nuevo discriminante REEMPLACE el `if "failed_test_ids" not in
data:` original en vez de coexistir con el (Opcion B del aviso del
coordinador). Justificacion:
1. Ausente y presente-vacio son el MISMO modo de fallo conceptual: "no hay
   ids enumerados, no hay forma de saber si los fallos son heredados o
   nuevos". Mantener dos reasons distintos para el mismo modo de fallo es
   ruido, no informacion.
2. Un solo guard reduce superficie de mantenimiento: cualquier futuro modo
   de fallo "sin ids" (p.ej. timeout del runner, lista corrupta) cae bajo
   el mismo discriminante sin anadir una tercera rama.
3. El test T3c (que verificaba el caso ausente bajo el reason viejo
   `failed_test_ids_missing_with_nonzero_exit`) se actualizo para esperar
   el reason nuevo `nonzero_exit_but_no_failed_ids (state-leak suspected)`.
   Su INTENCION (campo ausente bloquea) no cambio, solo el string del
   reason. Esto fue confirmado con el coordinador antes de tocar el test
   (aviso recibido durante la tarea: T3c en L1674 esperaba el reason viejo;
   se opto explicitamente por la Opcion A y se actualizo T3c en
   consecuencia, en vez de mantener D5c en paralelo).
4. El AUDIT_WOT-2026-017a.md (T3c, L44-45) se actualizo para citar el
   reason nuevo y documentar la subsuncion, con referencia a T6a/T6b.

### Naming honesto: "inherited_failures_subset" nunca se emite con a_set vacio

Verificado por construccion: el nuevo guard retorna ANTES de llegar a
`a_set = set(data.get("failed_test_ids") or [])` (linea posterior, D1/D3)
cuando `failed_test_ids` esta vacio o ausente. Por tanto, en el momento en
que el codigo alcanza `return True, {"reason": "inherited_failures_subset",
...}` (la unica linea que emite ese reason), `a_set` SIEMPRE tiene al menos
un elemento. No se necesito cambiar el string porque la garantia ya se
cumple estructuralmente tras el fix.

### Tests T6 (adversariales, clase TestPreExistingSuiteRed)

Siguiendo el patron exacto de T1-T5 (repo git real en tmp_path via
`init_git_repo`, `commit_ticket_marker`, `_base_payload`, `_write_last_run`):

- **T6a** (`test_t6a_present_empty_failed_ids_blocks_state_leak`):
  `exit_code=1`, `failed_test_ids=[]` (presente, vacio), probado con DOS
  baselines (uno no-vacio, uno vacio) para demostrar que el bloqueo NO
  depende del contenido de B (el bug viejo fallaba en ambos casos por
  igual: `set() - cualquier_set = set()`). Resultado esperado y obtenido:
  `(False, reason="nonzero_exit_but_no_failed_ids (state-leak suspected)")`
  en ambas variantes. PASSED.
- **T6b** (`test_t6b_absent_failed_ids_still_blocks_after_refactor`):
  confirma que el caso original D5c (campo AUSENTE del dict, no solo vacio)
  sigue bloqueando tras el refactor que subsumio D5c bajo el discriminante
  unico. Mismo reason esperado. PASSED.

Resultado: T6a y T6b PASSED. Sin ellos (es decir, revirtiendo el fix a
`if "failed_test_ids" not in data:`), T6a fallaria: el guard viejo
devolveria `(True, reason="inherited_failures_subset")` para
`failed_test_ids=[]` presente, exactamente el bug reportado.

### T3c actualizado (no roto, no borrado)

`test_t3c_failed_test_ids_absent_with_nonzero_blocks` se mantiene, con el
mismo escenario (campo ausente) y el mismo assert de bloqueo (`ok is
False`), unicamente actualizando el string de reason esperado de
`failed_test_ids_missing_with_nonzero_exit` a
`nonzero_exit_but_no_failed_ids (state-leak suspected)`. Docstring
actualizado para explicar el cambio y referenciar T6a/T6b. PASSED.

### Resultado de gates de calidad

| Verificacion | Comando | Resultado |
|---|---|---|
| T1-T6 dirigidos | `pytest tests/test_pre_handoff_guard.py -v` | 60 passed (incluye T1-T6b) |
| py_compile | `python -m py_compile scripts/pre_handoff_guard.py tests/test_pre_handoff_guard.py` | exit 0, sin output |
| ruff check (archivo) | `ruff check scripts/pre_handoff_guard.py` | All checks passed (exit 0) |
| ruff format --check (archivo) | `ruff format --check scripts/pre_handoff_guard.py` | 1 file already formatted (exit 0) |
| ruff check (proyecto) | `ruff check . --exclude .agent` | All checks passed (exit 0) |
| ruff format (test file) | `ruff format tests/test_pre_handoff_guard.py` | 1 file reformatted (solo line-wrapping, sin cambio semantico; re-verificado con pytest tras reformatear) |
| Suite completa del motor | `python scripts/run_pytest_safe.py --level all` | 3414 passed, 20 skipped, exit_code=0 (vs 3412 passed previos al fix: +2 por T6a+T6b) |
| last-run.json | inspeccion manual | status=finished, exit_code=0, tested_commit_sha=327d6a3 (==HEAD), failed_test_ids=[], baseline_failed_test_ids=[] |

### Archivos modificados en este fix

- `scripts/pre_handoff_guard.py`: discriminante unico
  `nonzero_exit_but_no_failed_ids (state-leak suspected)` reemplaza el D5c
  binario `"failed_test_ids" not in data`. +22/-10 lineas. Ningun otro gate
  (D7 level/args_mode, comparacion de subconjunto a_set/b_set, SHA
  freshness) tocado.
- `tests/test_pre_handoff_guard.py`: T3c actualizado (reason nuevo, mismo
  comportamiento); T6a y T6b anadidos al final de `TestPreExistingSuiteRed`.
  Reformateado por `ruff format` (solo wrapping de lineas largas).
- `.agent/collaboration/AUDIT_WOT-2026-017a.md`: nota T3c actualizada con
  el reason nuevo y referencia a T6a/T6b, explicando la subsuncion de D5c.

### Lo que NO se toco (confirmado)

- La logica de subconjunto por identidad (`a_set`/`b_set`/`new_failures`,
  D1/D3) -- intacta, T1/T2/T4/T5 siguen verdes sin modificacion de esa
  logica.
- Los gates D7 (level/args_mode) y SHA freshness -- intactos, T3d y los
  tests de `TestCanonicalSuiteGreenGate` siguen verdes.
- `scripts/run_pytest_safe.py` -- no tocado (el fix es solo en el guard,
  como pedia el ticket).
- Ningun flag de bypass anadido (`grep -i "force.suite|ignore.fail|bypass"
  scripts/pre_handoff_guard.py` sigue sin matches, no re-verificado por
  separado porque el diff no introduce ningun token nuevo de ese tipo).
- `work_plan.md` no se modifico (permanece APPROVED, el plan no cambio:
  este es un fix quirurgico sobre un hallazgo de review, no una nueva
  fase). Los estados de TURN.md/STATE.md (bus) tampoco se tocaron a mano:
  STATE.md ya decia IN_PROGRESS al leerlo (cambio hecho por el
  orquestador al reabrir el ticket, anterior a esta sesion); se deja como
  esta para que el orquestador gestione la transicion de cierre.

### Divergencia o duda a reportar

Ninguna. El fix calzo exactamente con el diagnostico del ticket: un solo
`if`, un solo reason, sin necesidad de tocar `run_pytest_safe.py` ni los
gates D7/SHA. La unica decision con dos caminos validos (Opcion A vs B
sobre T3c) fue resuelta explicitamente por aviso del coordinador en mitad
de la tarea, antes de tocar el test, y documentada arriba con la
justificacion completa.

Scope override: reapertura 017a por falso-verde state-leak; fix d8dd16c aprobado por Review 1 + Review 2 fresh-context; deuda 015x previa sin pushear sigue out-of-scope. Affected files: C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes\prompts\audit_agent_output.md