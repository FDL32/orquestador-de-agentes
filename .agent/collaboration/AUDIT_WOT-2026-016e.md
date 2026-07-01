# AUDIT WOT-2026-016e - SCOPE_OVERRIDE_NO_ABSOLUTE_PATHS

**Ticket:** WOT-2026-016e
**Tipo:** code
**delivery_authority:** repo_motor
**Estado:** IN_REVIEW

---

## Criterios de verificacion (tests de barrera obligatorios)

### T1 - Path dentro del repo se relativiza a <REPO_ROOT>/rel

Escenario: `record_scope_override` recibe un problem_file cuya ruta absoluta esta
DENTRO de `repo_root`.

Resultado esperado: la nota escrita contiene `<REPO_ROOT>/rel/path` (forward
slashes), NO la ruta absoluta. Test:
`TestRecordScopeOverrideNoAbsolutePaths::test_paths_inside_repo_are_relativized`.

### T2 - El prefijo de username NUNCA sobrevive

Escenario: la ruta absoluta de entrada contiene `C:\Users\<user>\...`.

Resultado esperado: la nota NO contiene el segmento de username en ningun caso
(dentro o fuera del repo). Test:
`TestRecordScopeOverrideNoAbsolutePaths::test_username_prefix_never_leaks`.

### T3 - Path fuera del repo cae a basename

Escenario: problem_file cuya ruta absoluta esta FUERA de `repo_root`.

Resultado esperado: la nota usa el basename del archivo, nunca la ruta absoluta.
Test: `TestRecordScopeOverrideNoAbsolutePaths::test_path_outside_repo_falls_back_to_basename`.

### T4 - Sin repo_root cae a basename

Escenario: `record_scope_override` llamado sin `repo_root` (None).

Resultado esperado: basename para todos los paths (nunca ruta absoluta). Test:
`TestRecordScopeOverrideNoAbsolutePaths::test_no_repo_root_falls_back_to_basename`.

## Mutation-verify (obligatorio, bug fix)

- sin_fix: revertir scope_gate.py -> los 4 tests FALLAN (exit 1); la nota generada
  contiene `C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes\x\y.py`.
- con_fix: restaurar -> 4 passed (exit 0).

## TP Check (Test-Presence / Test-Power)

- Los 4 tests aserta el CONTENIDO de la nota (no floor assertions): comprueban
  ausencia del username y presencia del marcador `<REPO_ROOT>`, y el fallback a
  basename fuera del repo / sin root. No hay assert trivial.
- El seam es la funcion pura `record_scope_override` con `repo_root` inyectado por
  parametro (testeable sin globals ni el controller).
- Cobertura de ambos call sites: el fix vive en el choke point unico
  (scope_gate.record_scope_override); el controller solo pasa repo_root en l.430.

## Forbidden Surfaces

- La logica de DECISION del scope gate (que archivos estan fuera de scope) NO cambia.
- No se anaden flags de override/bypass.
- No se toca ningun otro gate.
- No se reescriben notas historicas (eso es 016d/016g filter-repo).

## Alto blast-radius (G3)

016e toca el gate de scope (superficie de SEGURIDAD/publicacion) -> Review 2 debe
correr en fresh-context, separada de Review 1.
