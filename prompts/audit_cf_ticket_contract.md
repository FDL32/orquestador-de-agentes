# Prompt: Auditoria del Ticket Contract (Contract Formation)

> **Modo:** Solo lectura. No implantes nada. No reescribas archivos.
> Auditoria adversarial de un `ticket_contract` ANTES de congelarlo (`status: frozen`)
> y convertirlo en `work_plan.md`. El objetivo es que el Builder barato implante sin
> preguntar: `Builder clarification rate = 0`.
>
> **No dupliques `audit_agent_output.md`.** El `Intent Audit` (2.b) y la
> `Impact Simulation` (2.c) son la fuente canonica. Aqui los **enrutas y especializas**
> para un ticket concreto; no redefinas el procedimiento.

---

## Entradas obligatorias

Lee antes de evaluar:

- `.agent/planning/ticket_contracts.md` (el bloque del ticket auditado).
- `repo_charter.md` (`Non-Goals`, `Quality Bar`, `Security Constraints`).
  **Resolucion de ruta POR DUEÑO DEL TICKET, no por orden fijo (DEC-motor-charter-001).**
  El charter que gobierna a un contrato es el de SU repo, y lo determina el
  `delivery_authority` del propio contrato (o, si no lo declara, el prefijo del ticket):
  - `delivery_authority: repo_motor` -> `<motor>/repo_charter.md` (RAIZ; el motor no es un
    `repo_destino`, por eso no vive en `.agent/planning/`).
  - `delivery_authority: repo_destino` (o ticket de un destino) ->
    `<destino>/.agent/planning/repo_charter.md`.

  **NO uses "la raiz primero" como regla ciega:** en un `entorno_multi_root` ambos charters
  existen a la vez, y buscar por orden fijo hace que un contrato de destino se audite contra
  los `Non-Goals` del MOTOR -- dueño equivocado, veredicto invalido. Declara SIEMPRE que
  charter resolviste y por que.
- `plan_graph.md` (el `PLAN-*` y las `Forbidden Surfaces` derivadas). Misma resolucion por
  dueño que `repo_charter.md`.
- `prompts/contract_formation_pipeline.md` (campos obligatorios y maquina de estados).
- `prompts/audit_agent_output.md` secciones 2.b y 2.c (marco general).
- Para validacion mecanica de campos: `scripts/validate_contract_formation.py`
  (WOT-2026-007c). La auditoria humana/adversarial NO sustituye al validador ni
  viceversa: el script cubre estructura; este prompt cubre intencion y suficiencia.

### Si una entrada obligatoria NO EXISTE: "repo sin CF materializado" != "contrato mal formado"

**Distincion obligatoria (WOT-2026-023m(d)).** Antes de emitir un hallazgo por una entrada
ausente, resuelve su ruta por la regla de arriba (raiz del motor, luego planning del
destino). Si tras esa resolucion el artefacto **sigue sin existir**, estas ante un
**repo sin CF materializado**, que es un estado del REPO, no un defecto del CONTRATO:

- **NO es BLOCKER del ticket auditado.** Bloquearlo seria *scope hijack*: le cobras al
  contrato una carencia de infraestructura que no le pertenece ni puede arreglar.
- El punto 8 (**Intent Audit**) queda **INEJECUTABLE, no "debil"**: sin `Non-Goals` /
  `Quality Bar` / `Security Constraints` no hay nada contra lo que contrastar. Declaralo
  como tal, con la ruta que buscaste, en vez de inventar un veredicto.
- Emite el estado **`CF_NOT_MATERIALIZED`** nombrando el artefacto y las rutas probadas, y
  **escala con ARTEFACTO, no de palabra**: escribe el gap en el sink que ya existe,
  `.agent/planning/contract_gaps/CG-<TICKET_ID>.md` (plantilla `templates/contract_gap.md`,
  el mismo canal que usa el Builder). Una escalada sin fichero es NORMA, no mecanismo: nadie
  la recibe y la carencia vuelve silenciosa. El gap declara el artefacto ausente, el dueño
  del charter que se resolvio y la ruta probada.
- Un contrato **mal formado** es cosa distinta: sus campos existen pero estan incompletos,
  no son binarios o no son reproducibles. Eso SI es hallazgo del contrato y mantiene su
  severidad normal.

Regla practica: **ausencia de infra -> `CF_NOT_MATERIALIZED` + escalar; defecto de campo ->
BLOCKER/MAJOR segun severidad.** Confundirlos produce falsos BLOCKER que congelan tickets
sanos, y es la razon por la que `WOT-2026-021k` necesito un waiver explicito del usuario.

## Checklist especifica del ticket contract

1. **Campos completos:** `status`, `Objective-Link`, `Plan-Link`, `Premise`,
   `Premise Re-check`, `Files Likely Touched`, `Forbidden Surfaces`, DoD, STOP,
   `CONTRACT_GAP behavior`, `Builder clarification budget`. Un campo ausente bloquea.
2. **Premise verificable read-only:** el `Premise Re-check` es un comando read-only
   reproducible, no una afirmacion de fe. Si no se puede reproducir, no es premisa.
3. **DoD binario:** cada criterio de cierre es un comando con exit code o un test
   pass/fail, no "verificar que funcione".
4. **Forbidden Surfaces coherentes con el plan:** las superficies prohibidas derivan del
   `PLAN-*` y de sus `shared_dependencies`; protegen el anti-scope real del ticket.
5. **Suficiencia para clarification = 0:** simula ser el Builder. Hay alguna decision de
   intencion de producto que tendrias que preguntar? Si si, es fallo de contrato, no del
   Builder: marca el hueco para que vuelva a genesis, no para que el Builder improvise.
6. **deliverable_type honesto:** un ticket que dice `documentation` pero cuyo DoD exige
   ejecutar Builder/codigo/tests debe ser `mixed` o abrir ticket separado.
7. **CONTRACT_GAP como unica valvula:** el contrato deja claro que ante premisa falsa,
   ambiguedad, superficie prohibida necesaria o criterio incompleto, el Builder emite
   `CG-<TICKET_ID>.md` y bloquea; no muta el contrato en silencio.
8. **Intent Audit (rutado a 2.b):** contrasta el ticket contra `Non-Goals`,
   `Quality Bar` y `Security Constraints` del charter **de su dueño** (resolucion de ruta
   arriba). Un ticket que cumple su DoD pero contradice un Non-Goal debe marcarse riesgo,
   no aprobarse.
   **GATE PREVIO (WOT-2026-023m(d)):** si el charter de su dueño NO existe, este punto es
   `CF_NOT_MATERIALIZED` -> **INEJECUTABLE, y NO BLOCKER del ticket**. Emite el estado con
   la ruta probada y escala; no lo apruebes en silencio ni lo bloquees por la carencia.
9. **Evidencia minima para frozen:** cada claim central del contrato necesita
   artefacto concreto (`path:`, `command:` + `exit_code:`, `commit:` cuando
   aplique). Una etiqueta sin artefacto es relato y no habilita `frozen`.
   Para verificar que un `path:` declarado corresponde al repo correcto
   (`repo_motor` vs `repo_destino`), usa `prompts/_shared/topology_artifact_locations.md`.

## Severidad de hallazgos

- **BLOCKER:** campo obligatorio ausente; DoD no binario; `Premise Re-check` no
  reproducible; el ticket exige una decision de producto no resuelta; contradice un
  `Non-Goal`/`Security Constraint`.
- **MAJOR:** `Forbidden Surfaces` no derivadas del plan; `deliverable_type` mal
  clasificado; `CONTRACT_GAP behavior` ausente o vago; evidencia central sin
  artefacto concreto.
- **MINOR:** redaccion que no bloquea implantacion.
- **NIT:** estilo u orden.

## STOP conditions

- Si el ticket solo es elegible para `frozen` cuando el Builder "asuma" algo: no esta
  listo; devuelvelo a `draft`.
- Si el ticket exige que el usuario escriba codigo o edite contratos: redisenalo como
  `DEC-*`; no apruebes.
- Si auditando descubres que el `plan_graph` o el charter estan mal: escala hacia
  arriba (audit_cf_plan_graph / audit_cf_repo_charter), no parchees el ticket aislado.

## Salida (apta para bucle de mejora)

Entrega:
- `DECISION: APPROVE (frozen-ready) | CHANGES`.
- Hallazgos por severidad, cada uno con el campo del contrato afectado y la correccion.
- Estimacion explicita del `Builder clarification rate` esperado y por que.
- Tabla minima `Claim | Evidencia | Estado` para los claims centrales del contrato.
- Si `CHANGES`, la lista de campos que el Manager debe completar antes de `frozen`.
