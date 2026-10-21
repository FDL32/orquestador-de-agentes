# Follow-up: flight_manifest.json (manifiesto de que se carga siempre / por ticket / por hijo)

- **Slug:** `flight-manifest-followup`
- **Fecha:** 2026-10-21
- **Dueno:** decision de usuario para abrir WP
- **Estado:** abierto (deuda declarada, NO WP)
- **Decision:** el usuario eligio deuda declarada con dueno en vez de WP propio (2026-10-21).
- **Referencia:** `docs/followups/palanca-a-raiz-agents-md-diseno.md` (seccion 8),
  `prompts/doc_optimization.md` PASO 5 (deuda con dueno y criterio de salida).

## Problema

Hoy no existe un manifiesto machine-readable que declare que contenido se carga "siempre", "por
ticket" o "por hijo". Se infiere de la prosa de cada prompt de despacho. Es la forma concreta de
cerrar el riesgo residual que el diseno de la Palanca A declara: un agente frio que no sigue un
puntero de capa 2 no dispara ningun gate (mecanismo de carga "puntero-por-prosa").

Es una pieza NUEVA, no una migracion de contenido existente: por eso no entra en el lote de
reduccion de `AGENTS.md`.

## Por que no ahora

Ampliaria el alcance antes de que la raiz este medida (Fase 0 del diseno) y no es precondicion
de ninguna fase de reduccion.

## Criterio de salida

Un `flight_manifest.json` con esquema validado por un guard CABLEADO (hook de pre-commit o
`prepush_check`; `scripts/check_guard_wiring.py` lo exige) que falle si un prompt de despacho
declara un contenido siempre-cargado que el manifiesto no lista, o al reves. Un guard sin
cablear es una norma, no una barrera.

## Estado_FRESCO (2026-10-21)

    ESTADO_FRESCO: raiz=<worktree de la sesion sessionstart-palanca-a>, HEAD=99737636, verificado=2026-10-21

No existe ningun `flight_manifest.json` ni guard asociado en el arbol (`git ls-files | grep -i
flight_manifest` vacio en esta medicion).
