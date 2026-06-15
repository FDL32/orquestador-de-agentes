# Prompt: Auditoria del Plan Graph (Contract Formation)

> **Modo:** Solo lectura. No implantes nada. No reescribas archivos.
> Auditoria adversarial de la descomposicion en `PLAN-*` y, sobre todo, del claim
> mas fragil: **que dos planes pueden correr en paralelo sin colisionar.**
>
> **No dupliques `audit_agent_output.md`.** La `Impact Simulation` (seccion 2.c) es la
> fuente canonica del razonamiento de impacto. Aqui la **enrutas y especializas** para
> el `plan_graph.md`; no redefinas el procedimiento en paralelo.

---

## Entradas obligatorias

Lee antes de evaluar:

- `.agent/planning/plan_graph.md` (objeto de la auditoria).
- `.agent/planning/repo_charter.md` (los `OBJ-*` que los planes dicen cubrir).
- `.agent/planning/ticket_contracts.md` (si ya existen, para cruzar superficies).
- `prompts/contract_formation_pipeline.md` seccion 7 (schema e Impact Simulation).
- `prompts/audit_agent_output.md` seccion 2.c (marco general de impacto).

## Checklist especifica del plan graph

1. **Cobertura de objetivos:** cada `OBJ-*` del charter esta cubierto por al menos un
   `PLAN-*`, y cada `PLAN-*` enlaza a un objetivo real (no planes huerfanos).
2. **Superficies declaradas:** cada plan declara superficies de archivo, interfaces y
   `shared_dependencies` (DB, API, config global, schema, installer). Un plan sin
   `shared_dependencies` declaradas es no auditable para paralelismo.
3. **Impact Simulation como tabla, no relato:** existe la tabla obligatoria con columnas
   `Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable`.
   Cada fila afirmativa debe justificar por que las superficies son realmente disjuntas.
4. **Independencia probada, no declarada:** desconfia de un "paralelizable: yes" cuando
   dos planes comparten `pyproject.toml`, schema, config global, installer o un mismo
   modulo. Superficies de archivo distintas NO implican independencia si comparten estado.
5. **Degradacion segura:** si la independencia no puede probarse, el plan debe quedar
   como `requires_serialization` (after PLAN-00x), no como paralelo por defecto.
6. **Forbidden Surfaces calculables:** cada plan deja superficies prohibidas derivables
   para los tickets que genere (insumo del scope-gate y del anti-scope por ticket).
7. **Impact Simulation (rutada a 2.c):** aplica el procedimiento de
   `audit_agent_output.md` 2.c sobre ESTE grafo; marca riesgos como `NO VERIFICADO`
   cuando falte backlog o evidencia, no los presentes como aprobados.

## Severidad de hallazgos

- **BLOCKER:** plan paraleliza superficies que comparten estado/config/schema/installer
  sin estabilizar el contrato; falta la tabla Impact Simulation; `OBJ-*` sin plan.
- **MAJOR:** `shared_dependencies` ausentes en un plan; un "paralelizable: yes" sin
  justificacion de disjuncion; Forbidden Surfaces no derivables.
- **MINOR:** tabla presente pero con celdas vagas.
- **NIT:** estilo u orden.

## STOP conditions

- Si no puedes probar independencia entre dos planes marcados paralelos: exige
  `requires_serialization`; no asumas paralelo.
- Si el grafo toca runtime, bus, CI, installer o seguridad y no hay `context_baseline`:
  marca el impacto como `NO VERIFICADO` y bloquea el paralelismo.
- Si un plan invalida la premisa de un ticket pendiente: marca CONTRACT conflict.

## Salida (apta para bucle de mejora)

Entrega:
- `DECISION: APPROVE | CHANGES`.
- Hallazgos por severidad, cada uno con `PLAN-*` afectado y correccion exacta.
- Si `CHANGES`, las filas de Impact Simulation que deben corregirse y que planes
  deben degradarse a serializacion antes de emitir tickets.
