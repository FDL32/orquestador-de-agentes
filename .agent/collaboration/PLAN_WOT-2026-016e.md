# PLAN - WOT-2026-016e

**Ticket:** WOT-2026-016e
**deliverable_type:** code
**delivery_authority:** repo_motor
**Estado del plan:** APPROVED

## Problema (root cause, VERIFICADO EN CODIGO)

El registro de scope-override escribe rutas ABSOLUTAS locales en execution_log.md,
un archivo versionado en git. Cada override embebe `C:\Users\***REDACTED***\...` (username) en
la historia. Es la FUENTE que re-ensucia la historia de motor y workspace: hay que
cerrarla ANTES de reescribir la historia (016d/016g), o la limpieza se vuelve a
contaminar en el siguiente override.

Root cause exacto: `.agent/scope_gate.py:record_scope_override` formatea los
`problem_files` (absolutos) sin relativizar. Ese formateo lo alimentan DOS call
sites del controller (l.430 injected fn y l.3179 checkpoint), ambos via
`scope_gate.record_scope_override`.

## Estrategia

Fix minimo en la unica funcion compartida (`record_scope_override`), inyectando la
raiz del repo por parametro keyword-only y relativizando cada path antes de
escribir la nota. El controller pasa `PROJECT_ROOT.resolve()` en el choke point
(l.430), que cubre ambos call sites. No se toca la logica de DECISION del gate.

Render: dentro del repo -> `<REPO_ROOT>/rel/path` (posix); fuera/no relativizable
-> basename. Nunca la ruta absoluta con username.

## Barreras

1. Doble revision adversarial (Review 2 en fresh-context: 016e toca un gate de
   seguridad de scope).
2. Mutation-verify obligatorio: revertir el fix debe hacer FALLAR el test nuevo.
3. DoD (2) con prueba REAL (repo tmp) de classify_publication.py, no relato.

## Files Likely Touched

- .agent/scope_gate.py
- .agent/agent_controller.py
- tests/unit/test_scope_gate.py

## Criterios de aceptacion

Ver work_plan.md (DoD binario 1-3). Cierre canonico via --bootstrap-ticket +
--pre-handoff + --mark-ready con BUILDER_EXIT + STATE_CHANGED reales.
