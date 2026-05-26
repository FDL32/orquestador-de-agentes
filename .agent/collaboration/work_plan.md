# Work Plan - WP-2026-142

## Metadata
- **ID:** WP-2026-142
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Symmetric mark-ready scope gate
- **Asignado a:** Builder

## Objetivo
Endurecer `--mark-ready` para que el Builder no pueda superar el scope gate declarando archivos tocados que no aparecen en el diff real. El gate conservara el bloqueo actual por archivos fuera de scope, añadira bloqueo por cobertura cero y dejara cobertura parcial como warning.

## Decision Arquitectonica
- `check_scope_gate` comparara en ambas direcciones `Files Likely Touched` contra los archivos realmente cambiados.
- El bloqueo actual por `changed_files - whitelist` se conserva sin cambios.
- Si `whitelist ∩ changed_files = ∅`, el cierre se bloquea por fabricacion total.
- Si `whitelist - changed_files ≠ ∅`, se registrara advertencia de cobertura parcial sin bloquear.
- `changed_files is None` y whitelist vacia mantienen el comportamiento actual de paso.

## Files Likely Touched
- `.agent/agent_controller.py`
- `tests/unit/test_scope_gate.py`
- `tests/unit/test_bus_emission_on_mark_ready.py`

## Fases
1. Extender `check_scope_gate` con cobertura simetrica y resultados diferenciados por severidad.
2. Añadir pruebas unitarias para cobertura cero, cobertura parcial y preservacion de los casos base.
3. Verificar el flujo end-to-end de `--mark-ready` y el evento de bus asociado.
4. Validar con los gates locales del repositorio.

## Calidad
- `python scripts/run_pytest_safe.py tests/unit/test_scope_gate.py -q`
- `python scripts/run_pytest_safe.py tests/unit/test_bus_emission_on_mark_ready.py -q`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `check_scope_gate` bloquea cobertura cero y sigue bloqueando archivos fuera de scope.
- La cobertura parcial genera warning, pero no bloquea.
- `--mark-ready` respeta el nuevo resultado del gate sin romper la emision del bus.
- La validacion canonica pasa sin errores.
- La validacion canonica pasa sin errores.
