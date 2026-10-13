# Despacho del Trío (MAN / BUI / REV) — plantillas Kilo

Contiene las plantillas de despacho canonicas para el protocolo trío v2.14.
Cada vuelo copia la plantilla correspondiente a `.agent/planning/vuelo_<id>/<TICKET>/dispatch_<rol>_r<N>.md` (regla 28 del protocolo).

## Estructura común

Las 3 plantillas comparten un esqueleto de bloques B0-B9 (§2.2 del audit):

| Bloque | Contenido |
|---|---|
| B0 | Cabeza: nombre canónico, rol, fecha, worktree, BASE_SHA, recibo preflight |
| B1 | Mandato: objetivo + artefacto a emitir |
| B2 | Contrato que gobierna: prompts/skills citados por REFERENCIA (X-09) |
| B3 | Artefacto de salida: ruta exacta + marcadores |
| B4 | Gate de entrada: artefacto del predecesor obligatorio |
| B5 | Capacidades del modelo: canal, filesystem, bundle, mudez |
| B6 | Herramientas obligatorias del rol: lista §1 del audit por persona |
| B7 | Puntos de sondeo: tablero + mailbox |
| B8 | Identidad de bus + bitácora: registro, heartbeat, línea de bitácora |
| B9 | Presupuesto y cierre: rondas, escalación, validate cierre |

## Especialización por persona

Cada plantilla ESPECIALIZA el contrato `backlog_triage.md` (`cid-backlog-triage-v1`) POR REFERENCIA — NUNCA re-declarando criterios normativos (norma X-09, regla 34). El contrato de triaje gobierna las fases de PLAN que preceden al dispatch por ticket.

## Matriz persona × herramientas (de AUDIT_herramientas_personas_20261013.md, §1)

### MAN (Persona-1) — bloque B6 de la plantilla

| Herramienta | Rol | Evidencia |
|---|---|---|
| `scripts/memory_context.py --recall` | Fases 0.ante — consulta corpus antes de clasificar | m1 |
| `scripts/find_similar_signals.py` | Dedupe ANTES de escribir ficha/STRATEGY/AUDIT (3 superficies) | m2 / b1 |
| `scripts/check_dod_metric_freshness.py` | Valida que los criterios numéricos del DoD no caduquen | m3 / b9 |
| `scripts/validate_ticket_prose.py` | Valida prosa del ticket/work_plan antes del handoff | m4 |
| `scripts/check_flight_plan_collision.py` | Colisión inter-plan en queued/ | m5 |
| `scripts/scope_verification.py` + `work_plan_authority.py` | diff sin scope-creep + delivery_authority | m6 |
| `scripts/backlog_priority_score.py` | Triaje objetivo por valor/riesgo | m7 |
| `scripts/backlog_reconcile.py` | Recolector obligatorio (Fase 0.1 del contrato de triaje) | §1.1bis |
| `scripts/backlog_triage_writer.py` | Escritor único del DAG (Barrera WOT-2026-049c) | §1.1bis |
| `scripts/validate_batch_dag.py` | Valida DAG JSON del Manager (binding EXCLUSIVO) | §1.1bis |

### BUI (Persona-3) — bloque B6 de la plantilla

| Herramienta | Rol | Evidencia |
|---|---|---|
| `scripts/find_similar_signals.py` | Dedupe ANTES de test/lección (3 superficies) | b1 |
| `scripts/mutation_cycle.py` | Snapshot+restore para mutación sin perder fix sin commitear | b2 |
| `scripts/check_guard_wiring.py` | Valida que los guards creados estén cableados | b3 |
| `scripts/check_suite_freshness.py` | Avisa si commitear invalida suite verde del HEAD | b4 |
| `scripts/check_encoding_guard.py` | Mojibake/BOM antes de entregar | b5 |
| `scripts/check_deliverables_exist.py` | Pre-verifica que los artefactos existan al cierre | b6 |
| `scripts/check_ticket_nomenclature.py` | Gate de nomenclatura al crear ficheros | b7 |
| `scripts/check_builder_prompt_obligations.py` | Verifica que no se omita BUILDER_EXIT/READY para REVIEW | b8 |
| `scripts/check_dod_metric_freshness.py` | No satisface un número caduco (compartida con MAN) | b9 |

### REV (Persona-2) — bloque B6 de la plantilla

| Herramienta | Rol | Evidencia |
|---|---|---|
| `scripts/ensemble_dispatch.py loop-round` | 2ª lente independiente sobre diff de alto riesgo | r1 |
| `scripts/check_role_models_distinct.py` | Barrera mecánica de la condición dura (Persona-Revisor ≠ modelo del Builder) | r2 |
| `scripts/review_bundle_contract.py` | Invariante: bundle de review no truncado | r3 |
| `scripts/export_review_packet.py` | Exporta review packet con ## PROBE + ## UNIVERSE MANIFEST | r4 |
| `scripts/mutation_cycle.py` | mutation-verify seguro para el Revisor | r5 |
| `scripts/check_suite_running.py` | Detecta suite ya en vuelo antes de re-correr | r6 |
| `scripts/check_seal_staleness.py` | Frescura del recibo de contexto (suite sellada) | r7 |
| `scripts/check_document_self_contradiction.py` | Detecta auto-contradicción en prompts/docs revisados | r8 |
| `scripts/check_prompt_parity.py` / `check_prompt_bias.py` | Revisión de paridad y sesgo de prompts | r9 |

### Herramientas compartidas entre personas

| Herramienta | MAN | BUI | REV |
|---|---|---|---|
| `find_similar_signals.py` | Fase 0.ante | antes de test/lección | verifica dedupe corrió |
| `check_dod_metric_freshness.py` | DoD no caduco | No satisface número caduco | — |
| `mutation_cycle.py` | — | mutación de prueba | mutation-verify |
| `check_seal_staleness.py` | suite sellada fresca (p2) | — | frescura del recibo |

## Reglas de gobierno heredadas del contrato de triaje (§2.6 del audit)

Cada plantilla hereda POR REFERENCIA (`backlog_triage.md`, `cid-backlog-triage-v1`) las siguientes reglas:

- Superficie en vuelo por otra sesión → `REQUIERE_HUMANO` (regla PREVIA a cualquier otra)
- Dedupe antes de dar de alta (3 superficies)
- "El script RECOLECTA; el AGENTE juzga" — `exit 0` ≠ reconciliado
- Snapshot inicial/final + `EXTERNAL_WRITE_DETECTED`
- Etiquetas `VERIFICADO` / `INFERIDO` / `REQUIERE_HUMANO`
- Universo cerrado por serie (4 estados; fila fuera = ANOMALÍA)
- Dependencia REAL vs preferencia de orden (arista falsa → cascada)
- `class`/`autonomy_mode` los asigna el TRIAGE, no el ejecutor
- El triage es solo-lectura: propone, no muta el backlog
