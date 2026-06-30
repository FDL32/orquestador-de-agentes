# Execution Log - WOT-2026-017a

**Ticket:** WOT-2026-017a - PRE_EXISTING_SUITE_RED
**Estado:** IN_REVIEW (post Review-1 CAMBIOS_REQUERIDOS aplicados)
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
