# STRATEGY - WOT-2026-019i

Ticket: `scripts/run_gates_dispatch.py` es NO-EJECUTABLE por
`ModuleNotFoundError: No module named 'runtime.motor_link'` (shadowing de
`runtime` por `.agent/runtime/`).

## Diagnostico (heredado de Fase 0, no se re-deriva)

`run_gates_dispatch.py` inserta `.agent` en `sys.path` a nivel de modulo
(lineas 23-25) antes de `import scope_gate` (linea 28, tambien a nivel de
modulo). `.agent/runtime/__init__.py` existe como paquete real (sin
`motor_link.py`). Cuando `resolve_motor_root_path()` ejecuta
`from runtime.motor_link import resolve_motor_root` (linea 54), Python
resuelve `runtime` contra `.agent/runtime/` (el primero en `sys.path` que
provee ese nombre) en vez de `<motor>/runtime/motor_link.py`. Resultado:
`ModuleNotFoundError`.

`scripts/check_deliverables_exist.py` resuelve exactamente el mismo import
(`from runtime.motor_link import resolve_motor_root`, dentro de
`resolve_motor_root()`) sin fallar, porque nunca inserta `.agent` a nivel de
modulo: su unico uso de `scope_gate` esta detras de una funcion lazy,
`_import_scope_gate()`, que inserta `.agent` en `sys.path` SOLO dentro de su
propio cuerpo, ejecutada unicamente cuando se necesita.

## Estrategia

Replicar el patron de `check_deliverables_exist.py` en
`run_gates_dispatch.py`:

1. Sacar de nivel-de-modulo: la insercion de `.agent` en `sys.path` y el
   `import scope_gate`.
2. Envolver ambas operaciones en una funcion `_import_scope_gate()` que
   retorna el modulo `scope_gate` importado.
3. En el unico punto que usa `scope_gate` (`read_delivery_authority()`),
   llamar `_import_scope_gate()` primero y usar el modulo devuelto.
4. No tocar ninguna otra funcion, firma o comportamiento observable de
   `run_gates_dispatch.py`.

Esto es un cambio quirurgico: no cambia CUANDO se necesita `scope_gate`
(sigue siendo solo dentro de `read_delivery_authority`), solo CUANDO se
inserta `.agent` en `sys.path` (de "siempre, al importar el script" a
"solo cuando de verdad se necesita `scope_gate`"). Como `MOTOR_ROOT =
resolve_motor_root_path(PROJECT_ROOT)` (linea 63, a nivel de modulo) corre
ANTES de que `read_delivery_authority()` se invoque en `main()`, tras el fix
esa resolucion de `runtime.motor_link` ocurre siempre con `.agent` ausente
de `sys.path`, eliminando el shadowing en el unico punto donde puede
importar.

## Test de regresion

El test existente carga el modulo completo con `importlib.util` a nivel de
modulo del propio archivo de test: el error de import (si reaparece) ocurre
ANTES de que cualquier test pueda ejecutar, y no es observable con
monkeypatch sobre un modulo ya cargado en memoria del proceso pytest. Por
eso el test de regresion nuevo debe invocar el script como subprocess
(`subprocess.run([sys.executable, str(script_path)], ...)`), capturando
`stderr`, y afirmando que `ModuleNotFoundError` y el nombre del modulo roto
(`runtime.motor_link`) no aparecen ahi. Esto ejercita el import real, en un
interprete fresco, exactamente como lo hace un humano al ejecutar el script
desde la terminal.

## Mutation-check

Reintroducir temporalmente el shadowing (insercion de `.agent` a nivel de
modulo + `import scope_gate` a nivel de modulo, como antes del fix) debe
hacer que el test de regresion FALLE mostrando de nuevo el
`ModuleNotFoundError` en `stderr` del subprocess. Esto confirma que el test
mide el mecanismo real (el shadowing en tiempo de import), no un sintoma
cosmetico.

## Non-goals

- No se cambia la logica de dispatch por `deliverable_type`.
- No se toca `check_deliverables_exist.py`, `run_pytest_safe.py`,
  `scope_gate.py`, `.agent/runtime/__init__.py` ni `runtime/motor_link.py`.
- No se renombra ni se vacia el paquete `.agent/runtime/` (fuente del
  shadowing, pero fuera de alcance: el fix vive enteramente en
  `run_gates_dispatch.py`).
