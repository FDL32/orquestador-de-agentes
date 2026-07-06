# STRATEGY - WOT-2026-019j

Ticket: El scope gate no reconoce el heading `## Builder` para tickets
`deliverable_type=mixed`.

## Diagnostico (heredado de Fase 0 del Orquestador, verificado por el Manager)

`_DOC_DELIVERABLE_TYPES = frozenset({"analysis", "documentation", "research"})`
(`.agent/scope_gate.py:58`) no incluye `mixed`. Tres superficies dependen de
este conjunto (o de la cadena de parseo que termina en el mismo mecanismo)
como guard para caer a `## Builder` cuando no hay `## Files Likely Touched`:

1. `scope_gate.parse_files_likely_touched` (linea 331-349): resuelve el
   whitelist real que usa `--validate` / `check_scope_gate`. Sin `mixed` en
   el guard, el whitelist queda vacio y se emite el warning "No Files Likely
   Touched section in work_plan.md".
2. `scope_gate.files_likely_touched_tokens` (linea 131-145): mismo guard,
   usado para los tokens crudos del check de congruencia de extension
   (`agent_controller._check_deliverable_type_file_congruence`). Ese check
   nunca invoca con `value="mixed"` hoy (su propio guard,
   `_DOC_DELIVERABLE_TYPES_CONGRUENCE`, tampoco incluye `mixed`, y no debe
   incluirlo: es un chequeo inverso), pero la funcion en si debe alinearse
   por coherencia de contrato.
3. El checkpoint del mark-ready (`agent_controller.py:3352`, dentro de
   `_handle_mark_ready`) llama una cadena que termina en
   `scope_gate._parse_flt_section` (linea 169-209), la cual SOLO reconoce
   `## Files Likely Touched` y no recibe `deliverable_type` en ningun punto.
   Los doc-types no sufren esto porque `_handle_mark_ready` los trata como
   `_non_code_ticket` (linea 3340) y salta el checkpoint entero. `mixed` no
   esta en ese set, asi que cae al checkpoint, que reporta cada
   archivo como "outside Files Likely Touched" y exige `--scope-override`.

Verificacion adicional del Manager (no en la ficha original, misma cadena de
codigo): los otros 2 call-sites de la misma `_parse_raw_flt_paths` dentro de
`_handle_pre_handoff` (`agent_controller.py:3636` y `:3914`) comparten el
mismo problema si no reciben `deliverable_type`. Se corrigen en el mismo
ticket por ser la misma funcion publica y el mismo mecanismo de bug, aunque
el sintoma verificado en vivo por la ficha original es especificamente el
checkpoint del mark-ready (linea 3352).

`_VALID_DELIVERABLE_TYPES` en `agent_controller.py:1200` confirma que `mixed`
es un `deliverable_type` valido de primera clase, no secundario.

## Estrategia

Dos cambios independientes pero coordinados:

**A. Superficies 1 y 2 (guard simple).** Crear
`_FLT_BUILDER_FALLBACK_TYPES = _DOC_DELIVERABLE_TYPES | {"mixed"}` junto a
`_DOC_DELIVERABLE_TYPES` en `scope_gate.py`, y sustituir el conjunto usado en
el guard de `parse_files_likely_touched` y `files_likely_touched_tokens` por
el nuevo. Un solo punto de verdad, en vez de repetir
`or deliverable_type == "mixed"` en cada sitio.

**B. Superficie 3 (cadena FLT raw, hoy ciega a `deliverable_type`).** Pasar
`deliverable_type` explicitamente por toda la cadena:
`motor_checkpoint.parse_raw_flt_paths` -> `scope_gate.parse_flt_raw_paths` ->
`scope_gate.parse_flt_raw_buckets` -> `scope_gate._parse_flt_section`. Cada
nivel anade el parametro con default `"code"` (preserva el comportamiento
actual de cualquier caller que no lo pase). `_parse_flt_section` hace el
fallback real: si el escaneo de `## Files Likely Touched` no produce ninguna
entrada Y `deliverable_type in _FLT_BUILDER_FALLBACK_TYPES`, re-escanea
buscando `## Builder` con la misma logica de deteccion de seccion, devolviendo
namespace `None` (`## Builder` no usa namespaces `### repo_motor`/
`### repo_destino`).

**Los 3 call-sites de `agent_controller.py` pasan el `deliverable_type` ya
disponible o recien leido:**
- Linea 3352 (`_handle_mark_ready`): usa `_dt_mr`, ya definida antes en la
  misma funcion (linea 3339).
- Linea 3636 (`_handle_pre_handoff`, guard BOM): NO existe todavia ninguna
  variable de `deliverable_type` en ese punto de la funcion (se define mas
  adelante, linea 3726, como `_dt_ph`). Se anade una lectura local
  (`_read_deliverable_type(plan_content)`) justo antes de la llamada. Es
  segura de duplicar: la funcion es pura (regex sobre el string), sin
  I/O ni estado.
- Linea 3914 (`_handle_pre_handoff`, commit-or-block): usa `_dt_ph`, ya
  definida antes en el flujo de ejecucion de la misma funcion (linea 3726).

Se opto explicitamente por la opcion quirurgica (pasar `deliverable_type`) en
vez de hacer que `_parse_flt_section` caiga siempre a `## Builder` cuando
falta FLT (opcion descartada): esa alternativa ampliaria el fallback a
cualquier ticket `code` con una seccion `## Builder` usada para otro
proposito (p.ej. notas), rompiendo el bloqueo esperado cuando un ticket code
omite FLT por error.

## Test de regresion

`tests/unit/test_scope_gate_deliverable_aware.py` ya tiene el test
`test_mixed_does_not_parse_builder_section` que hoy AFIRMA el comportamiento
contrario al DoD de este ticket (`mixed` NO debe parsear `## Builder`). Este
test se invierte (renombrado y reescrito) como parte del fix, no como
regresion accidental: es el contrato ANTERIOR quedando obsoleto por diseno.
Se anaden tests nuevos que replican la cobertura ya existente para
`analysis`/`documentation`/`research` (parseo, ausencia de warning cuando el
diff cubre el whitelist, prioridad de FLT sobre Builder cuando ambos existen)
pero para `mixed`, en los 3 archivos de test tocados
(`test_scope_gate_deliverable_aware.py`, `test_scope_gate_topology.py`,
`test_motor_checkpoint.py`).

## Mutation-check

Revertir el guard de PASO 1 (quitar `mixed` de `_FLT_BUILDER_FALLBACK_TYPES`)
Y el parametro de PASO 2/3 (quitar `deliverable_type` de la cadena o forzar
que el fallback nunca se active) debe hacer que los tests nuevos FALLEN
mostrando de nuevo el whitelist vacio / warning "No Files Likely Touched" /
bloqueo del checkpoint exigiendo `--scope-override`. Restaurar el fix debe
hacer que vuelvan a pasar. Documentar ambas corridas (roja y verde) con
salida literal de pytest en `execution_log.md`.

## Non-goals

- No se anade `mixed` a `_DOC_DELIVERABLE_TYPES_CONGRUENCE` ni se modifica
  `_check_deliverable_type_file_congruence` (conjunto hermano de proposito
  inverso: advertir cuando un doc-type declara codigo; `mixed` con codigo es
  legitimo).
- No se cambia el contrato de namespaces (`### repo_motor`/`### repo_destino`)
  de `## Files Likely Touched`.
- No se cambia el comportamiento de `--validate`/`--mark-ready` para
  `deliverable_type="code"` sin `## Builder` (sigue emitiendo el mismo
  warning/bloqueo que antes).
- No se anade un fallback incondicional a `## Builder` para cualquier
  `deliverable_type` (opcion de diseno evaluada y descartada explicitamente).
- No se toca ningun archivo fuera de los 6 listados en Files Likely Touched
  del `work_plan.md`.
