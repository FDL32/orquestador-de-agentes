# PLAN - WOT-2026-016z

Ticket: WOT-2026-016z - Guard de sesion anti-contaminacion de la identidad git local
del motor (barrera preventiva, no aislamiento de fixture).
Estado: APPROVED
delivery_authority: repo_motor | deliverable_type: code

Este documento es la estrategia tecnica breve del ticket; el contrato completo
(diagnostico detallado, criterios, gates, STOP conditions) vive en work_plan.md. Si algo
difiere entre ambos, work_plan.md manda.

## Resumen del problema

La ficha original asumia que un fixture de test contamina test@test.com en la config
git LOCAL del motor. Fase 0 REFUTO esa premisa: ningun fixture activo en tests/ opera
con cwd sobre el motor real (todos usan tmp_path/repo/repo_path/repo_root); una corrida
empirica de 47 tests confirmo que la config local del motor (noreply) no cambia antes
ni despues. El dano historico de WOT-2026-016w fue manual, no de fixture, y ya esta
corregido. Aun asi, no existe barrera que impida una recontaminacion FUTURA (un test
nuevo mal escrito, o repetir el comando manual). Este ticket implementa esa barrera
preventiva.

## Estrategia (cambio minimo, clonar el patron del bus)

1. En tests/conftest.py, anadir import subprocess y 3 funciones nuevas que clonan la
   estructura exacta de _restore_motor_bus_if_changed /
   _enforce_motor_bus_isolation / motor_bus_isolation_guard (lineas 219-253), mapeando
   "leer bytes de un archivo" a "leer git config --local user.email/user.name con
   cwd=PROJECT_ROOT vía subprocess".
2. Anadir una fixture autouse _isolate_motor_git_identity(request) que replica la
   estructura de _isolate_controller_event_bus (lineas 256-293): snapshot al entrar,
   yield, enforcement (con restauracion) en el finally.
3. Scope per-test (no session): razonado en work_plan.md, seccion "Scope: per-test" --
   el criterio de aceptacion exige nombrar el nodeid del test contaminante, lo cual solo
   es posible snapshoteando/comparando alrededor de cada test, no una vez por sesion.
4. Crear tests/unit/test_motor_git_identity_barrier.py con 3 tests que clonan
   test_motor_bus_isolation_barrier.py, pero usando monkeypatch sobre la funcion lectora
   interna para simular contaminacion SIN tocar el motor real ni ningun repo real (el
   "recurso" aqui es la salida de un comando git, no un archivo en tmp_path).
5. Ejercer y documentar MUTATION en execution_log.md: caso sin-contaminacion (no
   dispara fallo) vs caso con-contaminacion (dispara fallo con el nodeid, restaura el
   valor). Cubierto por los mismos 3 tests de barrera.
6. Correr gates: pytest focal de los 2 archivos (nuevo + hermano del bus), ruff check,
   ruff format --check (o su equivalente .venv si uv esta roto en este entorno),
   suite canonica run_pytest_safe.py --level all, y verificacion final de que
   git config --local user.email/user.name del motor NO cambiaron tras la corrida
   completa.
7. Commitear en repo_motor con WOT-2026-016z en el mensaje, mark-ready, esperar review
   del Manager (validate es Manager gate).

## Archivos tocados

- tests/conftest.py (fixture nueva + 3 funciones nuevas; NO tocar
  _isolate_controller_event_bus ni sus funciones)
- tests/unit/test_motor_git_identity_barrier.py (3 tests nuevos)

## Criterios de cierre

Identicos a work_plan.md seccion "Criterios de Aceptacion (binarios)" items 1-8. No
duplicados aqui para evitar deriva; ver work_plan.md como fuente unica de los comandos
exactos.
