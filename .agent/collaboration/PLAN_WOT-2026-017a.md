# PLAN WOT-2026-017a - PRE_EXISTING_SUITE_RED

**Ticket:** WOT-2026-017a
**Tipo:** code
**delivery_authority:** repo_motor
**Estado:** IN_PLANNING

---

## Contexto

El assert_canonical_suite_green en pre_handoff_guard.py bloquea el handoff si
exit_code != 0, sin distinguir entre fallos pre-existentes (heredados del baseline)
y regresiones nuevas. Esto produce falsos positivos: un ticket que no introdujo
nuevos fallos queda bloqueado por fallos heredados.

La solucion requiere dos cambios coordinados:
1. run_pytest_safe.py: persistir los node-ids de tests fallidos en last-run.json.
2. pre_handoff_guard.py: leer esos ids y compararlos contra el baseline por IDENTIDAD.

---

## Decisiones de diseno (7 - todas cerradas)

### D1 - Definicion de suite roja heredada

Un test es heredado si y solo si su node-id completo (file::Class::test o
file::test para tests sin clase) aparece en el campo failed_test_ids del
last-run.json en disco al momento del handoff.

La comparacion es por IDENTIDAD de string exacto del node-id, no por conteo ni
por patron parcial. Esto cierra el vector de mutacion: un test que pasa de verde
a rojo simultaneamente con otro que pasa de rojo a verde produce el mismo conteo
pero distinta identidad, y debe BLOQUEAR.

### D2 - Fuente del baseline y metodo de captura de node-ids

Fuente: el campo failed_test_ids: list[str] en
.agent/runtime/pytest-safe/last-run.json, anadido por run_pytest_safe.py.

METODO DE CAPTURA ELEGIDO: parseo de lineas FAILED del stream de pytest.

Justificacion: stream_pytest() ya acumula TODAS las lineas en lines (l.451,
l.481). El formato de salida de pytest incluye lineas con patron:
    FAILED tests/foo/test_bar.py::TestClass::test_method
Parsear con regex simple (^FAILED\s+(\S+)) es determinista, stdlib-only, no
modifica la invocacion de pytest y opera sobre el stream que YA existe.
Alternativa rechazada: --json-report (requiere plugin externo no incluido).

Cambio de firma: stream_pytest retorna tuple[int, list[str]]
(returncode, failed_ids). El caller en main() desempaqueta la tupla.

### D3 - Regla de decision

Sea B = set(last_run_base[failed_test_ids]) (baseline disponible en disco).
Sea A = set(last_run_actual[failed_test_ids]) (ultimo run del ticket actual).

- Si exit_code_actual == 0: PERMITIDO (A vacio, trivialmente subconjunto de B).
- Si exit_code_actual != 0 y A.issubset(B): PERMITIDO con diag auditado
  (lista inherited_test_ids y baseline_run_sha).
- Si exit_code_actual != 0 y A - B != {}: BLOQUEADO con lista A - B.

El guard EXIGE que failed_test_ids este presente en last-run.json para permitir
un handoff con exit_code != 0; si el campo esta ausente, BLOQUEA (fail-closed).

### D4 - Sin override opaco

Ningun flag --force-suite, --ignore-failures, ni equivalente.
La auditabilidad es estructural: el diag incluye inherited_test_ids y
baseline_run_sha (tested_commit_sha del last-run.json base).

### D5 - Fail-closed

Las siguientes condiciones BLOQUEAN incondicionalmente:
a. last-run.json ausente.
b. last-run.json no parseable.
c. exit_code != 0 y campo failed_test_ids AUSENTE en last-run.json.
d. Git falla al resolver HEAD.
e. status != finished.
f. level != all o args_mode != default_discovery (gates existentes preservados).

### D6 - Politica de flaky tests

SIN VENTANA DE GRACIA. Un test que falla en el run actual y NO estaba en el
baseline BLOQUEA, aunque sea flaky conocido.

Resolucion correcta si un flaky bloquea sistematicamente:
a. Marcar con @pytest.mark.xfail(strict=False).
b. Corregir para hacerlo determinista.
c. Skipear con razon documentada.
Ninguna es trabajo de este ticket.

SIN HERENCIA PERPETUA. La herencia solo aplica al ticket actual. En el proximo
ticket, el test debe estar en el NUEVO baseline del siguiente run pre-ticket.

### D7 - Paridad de nivel

El baseline es valido solo si fue producido con level=all y
args_mode=default_discovery. El guard verifica los campos level y args_mode
del last-run.json antes de usar failed_test_ids. Si el run base tenia nivel
focal o args explicitos, BLOQUEA.

---

## Seams verificados (HEAD=4f3d698)

scripts/pre_handoff_guard.py:
- _SUITE_REQUIRED_TYPES = {code, mixed} (l.426)
- assert_canonical_suite_green(motor_root, deliverable_type) (l.429)
- Bloqueo binario if exit_code != 0: (l.502) - PUNTO A SUSTITUIR
- Gates a PRESERVAR: tested_commit_sha==HEAD (l.512-529),
  level=all (l.531-541), args_mode=default_discovery (l.543-555)

scripts/run_pytest_safe.py:
- stream_pytest(command: list[str]) -> int (l.450) - FIRMA A CAMBIAR
- Acumulacion de lineas: lines: list[str] = [] (l.451), lines.append(line) (l.481)
- returncode = process.wait() + return returncode (l.482/l.493)
- Construccion del summary: l.804-833; write_json(LAST_RUN_JSON, summary) (l.834)
- Campo failed existente (l.275-284): limpieza de DIRECTORIOS, NO tocar

Consumidor: scripts/preflight_closeout.py importa assert_canonical_suite_green
pero no reimplementa; si la firma de la funcion no cambia, no requiere edicion.
Builder debe verificar en Fase 2.

---

## Archivos que el Builder DEBE tocar

1. scripts/run_pytest_safe.py - parseo FAILED + cambio firma stream_pytest +
   campo failed_test_ids en summary.
2. scripts/pre_handoff_guard.py - sustituir bloqueo binario por logica subconjunto.
3. tests/test_pre_handoff_guard.py - anadir T1-T5 con repos git reales.
4. tests/unit/test_run_pytest_safe.py - cobertura de failed_test_ids.

Condicional:
5. scripts/preflight_closeout.py - solo si firma assert_canonical_suite_green cambia.
6. tests/unit/test_preflight_closeout.py - solo si consumidor cambia.

---

## NON-GOALS (literales, no reabrir)

- Ningun destino (ADU u otros).
- Gates existentes del guard se PRESERVAN.
- Ningun flag de bypass/override/--force-suite.
- Ningun cambio de run_pytest_safe mas alla de ANADIR failed_test_ids.
- ADU-004 o cualquier ticket de destino.
- Archivo baseline separado (decision CEM vinculante, rechazada).
- Re-run de la suite base en caliente.