# Plan Graph - <repo/proyecto> (PLANTILLA)

> Copia a `DESTINO_ROOT/.agent/planning/plan_graph.md` y rellena.
> Descompone el charter en `PLAN-*`. **La independencia entre planes se verifica,
> no se declara por buena fe.** Endurecimiento de paralelismo: `WOT-2026-007e`.

## PLAN-001 - <titulo>
- objetivo: <que logra; enlaza a OBJ-00x del charter>
- tickets: [<TICKET_ID>]
- depends_on: [PLAN-00x] | -
- superficies_archivo: [<rutas/globs que este plan crea o modifica>]
- interfaces: [<APIs, contratos, eventos de bus, schemas que expone o consume>]
- shared_dependencies: [<DB, API, config global, schema, installer, lock-file
  (pyproject.toml/uv.lock), variables de entorno, runtime compartido...>]

<!-- repetir PLAN-00x segun haga falta -->

## Impact Simulation

Tabla obligatoria, salida auditable (no relato). Una fila por plan:

| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |
|------|-------------|-------------|--------------------|------------|---------------|
| PLAN-001 | <archivos/interfaces> | <deps compartidas> | <colision concreta> | <como se evita> | yes |

Reglas mecanicas:

- **Paralelizable** solo admite tres valores: `yes` | `no` | `after PLAN-00x`.
- Solo `yes` si las superficies **e** interfaces son disjuntas, **o** las
  `shared_dependencies` estan estabilizadas por contrato (congeladas, versionadas
  o con owner unico declarado).
- Si la independencia **no puede probarse**, degradar a `requires_serialization`
  (equivale a `after`); nunca asumir `yes` por defecto.
- Superficies de archivo distintas NO implican independencia si comparten estado
  (misma DB, mismo lock-file, misma config global, mismo schema).

## Forbidden Surfaces por plan

Cada plan deriva las superficies prohibidas para los tickets que genere (insumo
directo del scope-gate y del anti-scope por ticket):

- PLAN-001: <superficies que sus tickets NO pueden tocar, derivadas de los
  otros planes y de las shared_dependencies>

## Merge Regression Audit

Antes de **integrar** el resultado de dos planes que tocaron superficies vecinas
o `shared_dependencies` compartidas, ejecutar una auditoria transversal de
regresion sobre la **union**, no plan por plan:

- Invariantes cross-plan a revalidar: <p.ej. el schema sigue coherente; la API
  que un plan consume no cambio bajo el otro; el lock-file resuelve sin conflicto>.
- Gates sobre la union: <suite completa, no solo los tests de cada plan; validate
  del destino 0/0; linters sobre el merge>.
- Si la auditoria de merge falla, el paralelismo era ilegitimo: re-clasificar los
  planes implicados a `requires_serialization` y abrir `CONTRACT_GAP` si el
  contrato afirmaba independencia.
