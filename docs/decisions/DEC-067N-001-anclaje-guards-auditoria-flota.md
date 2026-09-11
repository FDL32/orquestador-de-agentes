# DEC-067N-001: Donde cuelgan en el plan_graph los defectos de un guard ya entregado

**Ticket:** WOT-2026-067n (origen, completed)
**Fecha:** 2026-09-12
**Estado:** DECIDED
**Autor:** Usuario (decision T1c; el agente propone, no decide)

## Contexto

Tres fichas (`ESPEJO-MOTOR-067n-a/b/c`) declaran `delivery_authority: repo_motor` y
documentan defectos de `scripts/check_launch_prompt_paths.py`, un guard YA entregado.
Para pasar de `review` a `frozen` necesitan un `Plan-Link`, porque el salto exige
Impact Simulation y esa se valida en el `plan_graph`, no en el ticket
(`validate_contract_formation.py`).

**El hueco, medido:** `repo_charter.md:90-96` (`OBJ-002`) cubre la INTENCION con
precision literal -- *"el instrumento que audita la proteccion de la flota conoce su
denominador y falla honestamente cuando no puede enumerar"*, con `failure_mode` *"un
destino se salta en silencio y el censo sale verde"*. **Pero ningun PLAN declara la
superficie:**

| PLAN | tickets | declara `check_launch_prompt_paths.py`? |
|---|---|---|
| PLAN-001 | WOT-2026-024z, 025e, 025h, 025i | no |
| PLAN-002 | WOT-2026-024f-A | no |
| PLAN-003 | WOT-2026-024d, 024h, 020t | no |
| PLAN-004 | WOT-2026-024f-B | no |

Verificado: `grep -rln check_launch_prompt_paths .agent/planning/ prompts/` -> 0 hits.

## Por que exige DEC y no la decide un ejecutor

`NG-RAIZ` del charter es explicito: *"cuando falta un contrato el motor falla explicito o
pide DEC. No inventa destino, ni superficie distribuible, ni reglas de adopcion. Es la raiz
[...] y el antipatron que mas ha costado: inventar una premisa en vez de medirla o pedir la
decision."* Elegir un PLAN por parecido tematico ES inventar la premisa, y la
`Negative Audit Checklist` lo lista como invalidante.

## Opciones comparadas

### [A] Ampliar `superficies_archivo` de PLAN-002

Barato y sin entradas nuevas. **Descartada:** PLAN-002 esta acotado a
`check_claude_settings_portability.py` con `tickets: [WOT-2026-024f-A]`. Ampliarlo para
cubrir "guards de auditoria de la flota" lo convierte en un cajon de sastre, y deja las
`Forbidden Surfaces` de las tres fichas sin derivar de un plan coherente.

### [B] Abrir PLAN-005 colgado de OBJ-002  -- **ELEGIDA**

Plan propio para "guards de auditoria de prompts de arranque", con sus `Forbidden
Surfaces` e `Impact Simulation`. Mantiene la trazabilidad `OBJ-002 -> PLAN-005 -> ticket`
que el pipeline exige. Coste: una entrada nueva en el grafo y su fila de simulacion.

### [C] Declarar que un guard ya entregado no necesita PLAN-*

Su `Plan-Link` seria el ticket de origen (`WOT-2026-067n`, completed). **Descartada:**
exige decidir si el `TICKET_REQUIRED` del validador lo admite, y abre una via por la que
cualquier defecto futuro elude el grafo. Cambia una regla general para resolver un caso.

## Decision

**[B].** Se abre `PLAN-005` en `plan_graph.md`, colgado de `OBJ-002`, con
`superficies_archivo` que incluyan `scripts/check_launch_prompt_paths.py` y su test, y
`tickets: [ESPEJO-MOTOR-067n-a, -b, -c]`.

**Motivo:** es la unica opcion que no degrada una estructura existente. [A] ensancha un
plan acotado hasta vaciarlo de significado; [C] cambia una regla general para resolver un
caso particular. [B] cuesta una entrada y deja el grafo mas preciso que antes.

## Consecuencias

- Las tres fichas `ESPEJO-MOTOR-067n-a/b/c` quedan desbloqueadas para `review -> frozen`
  UNA VEZ exista PLAN-005 con su Impact Simulation. **La DEC no las promueve por si sola.**
- `PLAN-002` no se toca: sigue acotado a `check_claude_settings_portability.py`.
- **Reversibilidad alta:** si PLAN-005 resulta redundante, se fusiona con otro plan sin
  tocar codigo -- es una entrada de grafo, no una superficie.

## Limites declarados

- **NO reabre `WOT-2026-067n`** (completed, `commit:9c72250`), cuya fila de archive declara
  *"NO re-audita la implementacion"*.
- **NO decide el contenido tecnico** de las tres fichas: solo donde cuelgan en el grafo.
- **NO aplica al destino.** La segunda cola de la propuesta (fichas `RDS-2026-004m/004n`)
  fue RETIRADA por su propio bucle: la cuarta entrada de `superficies_archivo` de PLAN-002
  es `README`/docs de raiz, una CATEGORIA que ya las cubre. No habia hueco.
