# Work Plan - WOT-2026-016e

## Metadata
- **ID:** WOT-2026-016e
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Scope-override deja de escribir rutas ABSOLUTAS locales en execution_log.md
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Que el registro de scope-override deje de escribir RUTAS ABSOLUTAS locales
(C:\Users\***REDACTED***\...) en execution_log.md. Es la FUENTE que re-ensucia la historia
de git de AMBOS repos (motor y workspace): cada vez que el gate registra un
override, embebe el username local en un archivo versionado. Cerrar esta fuente
ANTES de limpiar la historia (016d/016g).

## Decision Arquitectonica

El fix vive en `.agent/scope_gate.py:record_scope_override`, no en el controller.
Motivo: hay DOS call sites en el controller (`_record_scope_override` en l.430 -
usado por el injected fn del scope gate en l.443 - y la llamada directa del
checkpoint en l.3179), y ambos delegan en `scope_gate.record_scope_override`.
Relativizar dentro de esa unica funcion cubre los dos caminos con un solo cambio y
mantiene la funcion pura (root inyectada por parametro keyword-only, testeable sin
globals). NO se toca la logica de DECISION del scope gate: que archivos estan fuera
de scope no cambia; solo COMO se registran sus rutas.

Render elegido: paths dentro del repo -> `<REPO_ROOT>/rel/path` (forward slashes,
marcador literal auto-documentado que classify_publication.py no marca como
redaction_risk). Paths fuera del repo o no relativizables -> basename, NUNCA la
ruta absoluta con username.

## Fases

### Fase 0 - Confirmar seams (VERIFICADO EN CODIGO)
- scope_gate.py:537 formatea `f"Affected files: {', '.join(sorted(problem_files))}"`.
- problem_files = out_of_scope | missing_from_diff (l.584-586), paths absolutos
  resueltos (str((root / name).resolve())).
- 2 call sites en el controller (l.430 injected, l.3179 checkpoint) -> ambos via
  `_record_scope_override` -> `scope_gate.record_scope_override`.
- Test existente: tests/unit/test_scope_gate.py.

### Fase 1 - Fix minimo en scope_gate.py
- Anadir helper `_relativize_scope_path(path, repo_root)` (repo -> <REPO_ROOT>/rel;
  fuera/no relativizable -> basename).
- `record_scope_override`: parametro keyword-only `repo_root: Path | str | None`;
  relativizar cada problem_file antes de formatear la nota.
- Controller: `_record_scope_override` (l.430) pasa `repo_root=PROJECT_ROOT.resolve()`
  (choke point unico -> cubre ambas call sites).

### Fase 2 - Test de regresion + mutation-verify
- tests/unit/test_scope_gate.py: clase TestRecordScopeOverrideNoAbsolutePaths con
  4 casos (dentro del repo -> <REPO_ROOT>/rel; username nunca sobrevive; fuera del
  repo -> basename; sin repo_root -> basename).
- Mutation-verify: revertir scope_gate.py -> tests fallan (nota con ruta absoluta);
  restaurar -> pasan. Registrado en execution_log.md.

### Fase 3 - Verificacion final (DoD)
- classify_publication.py sobre un log generado por el nuevo codigo -> NO
  PUBLISH_WITH_REDACTIONS, verdict LISTO_PARA_PUBLICAR (repo tmp, prueba real).
- suite canonica run_pytest_safe.py --level all verde + validate 0/0 + ruff
  check/format + encoding guard.

## Criterios de aceptacion (DoD binario)

1. Un `record_scope_override` con rutas absolutas de entrada escribe rutas
   RELATIVAS/placeholder en el log (test con repo tmp + rutas absolutas).
2. classify_publication.py sobre un log generado por el nuevo codigo NO marca
   PUBLISH_WITH_REDACTIONS por ruta local.
3. Suite canonica verde + validate 0/0 + ruff check/format + encoding limpios.

## Files Likely Touched

- .agent/scope_gate.py
- .agent/agent_controller.py
- tests/unit/test_scope_gate.py

## Non-goals

- NO tocar la logica de DECISION del scope gate (que archivos estan fuera de scope
  no cambia; solo COMO se registran sus rutas).
- NO tocar el controller mas alla de pasar repo_root al choke point.
- NO tocar ningun otro gate.
- NO anadir flags de override o bypass.
