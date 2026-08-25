# Prompt: Cierre de Sesion de DISEnO (auditoria adversarial read-only)

> **Modo:** READ-ONLY. Cierra una SESIoN DE DISEnO (planning): triar backlog, disenar planes de
> vuelo, redactar fichas de tickets. NO commitea, NO muta el motor, NO escribe backlog.md. Es la
> variante de `orchestrator_session_close_full_audit.md` para el caso read-only: reutiliza sus
> secciones aplicables y anade las propias de una sesion de diseno.

contract_id: cid-session-close-design-v1
source_of_truth: este prompt. Deriva de `prompts/orchestrator_session_close_full_audit.md`
(cierre de sesion de DESARROLLO); si algo diverge, aquel rige para desarrollo y este para diseno.
Relacionado: WOT-2026-028a (research-sessions), WOT-2026-023t (freshness gate), WOT-2026-026k
(arranque de bucle robusto), y el bootstrap hermano de arranque de sesion de diseno.

## Que es y que NO es

- ES el cierre de una sesion de DISEnO: verifica huella cero, solidez y frescura de los planes/
  fichas producidos, y que nada duplique lo existente. Revisado con bucle adversarial (8 nan +
  Codex) arrancado bajo WOT-2026-026k.
- NO es el cierre de desarrollo: no aplican las auditorias de salud, hooks, portabilidad,
  `--session-close` ni los gates de arbol (esos exigen commits; una sesion de diseno no commitea).

## Mapeo: que del cierre canonico se reutiliza y que no

| Seccion canonica | Diseno | Motivo |
|------------------|--------|--------|
| B1.1-1.3 auditoria de salud (3 auditorias) | NO | auditan el motor tras cambios; diseno no cambio el motor |
| B1.3.4-3.6 hooks/portabilidad/suite | NO | gates de codigo commiteado; diseno no commitea |
| B1.3.7 (a) umbral de evidencia | REUTILIZA | mismo gate "solo con evidencia verificable" que el inbox |
| B1.3.7 (b) registro de follow-ups del MOTOR | ADAPTA | va a ficha de inbox con delivery_authority: repo_motor (no a backlog.md; lo escribe desarrollo) |
| B2 pasada adversarial | ADAPTA | sobre los ARTEFACTOS (planes/fichas/prompts), no sobre diffs de codigo |
| B2.5 triage de hallazgos (finding_triage_protocol) | REUTILIZA | clasificar antes de fichar |
| B3 --session-close + gates de arbol | NO | muta estado/bus; diseno no cierra ticket |
| B4 promocion de memoria | MiNIMO | solo si hubo leccion de comportamiento (no infra) |
| B5 escribir backlog post-cierre | ADAPTA | diseno deja el INBOX, no escribe backlog |

---

## Prompt

```text
Cierras una SESIoN DE DISEnO (planning, read-only) como AUDITOR adversarial de tus propios
artefactos, no como narrador. No hubo commits ni cambios en el motor: no aplican las auditorias de
salud, hooks, portabilidad ni --session-close del cierre de desarrollo. Lo que Si auditas: que tu
huella sea cero, que tus planes/fichas sean solidos y frescos, y que nada duplique lo existente.

CONTRATO: rige prompts/audit_agent_output.md (CEM v0): evidencia antes que relato (solo
diff/exit-code/probe/SHA/hash), etiqueta cada hallazgo VERIFICADO/INFERIDO/NO VERIFICADO.

REGLA DE PARADA: si un artefacto falla su gate (plan no valida, premisa no se reproduce, ficha sin
evidencia, huella no-cero inesperada), DETENTE y surfacealo; no lo tapes ni promociones nada.

Ejecuta en orden:

== BLOQUE H - HUELLA CERO (propio del diseno; la garantia de no-choque) ==
H1. git -C <motor> status --porcelain: NINGuN fichero del motor tocado por ti (solo lo que la sesion
    de desarrollo tenga sucio, que NO es tuyo). Si tu tocaste el motor -> ROJO.
H2. git -C <workspace> status --porcelain: solo tu zona propia sucia (flight_plans/queued/,
    flight_plans/INDEX.md, backlog_inbox/, reports/). backlog.md, STATE.md, work_plan.md y .gitignore
    NO tocados por ti (el diseno NO edita .gitignore: si falta una regla, fichala como follow-up al
    inbox para desarrollo). Si algo fuera de tu zona esta sucio por ti -> ROJO (si por desarrollo, es
    legitimo: distinguelo).
H3. NO hay commits tuyos en ningun repo (git log no muestra commits de esta sesion de diseno).

== BLOQUE I - INVENTARIO DE LO PRODUCIDO ==
I1. Lista los planes en flight_plans/queued/ (id, tickets, tamano) y las fichas en backlog_inbox/.
I2. Por cada uno, cita su evidencia de origen (SHA/probe/bundle). Sin evidencia -> no cuenta (se retira).

== BLOQUE F - FRESHNESS DE LOS PLANES (anti-staleness, WOT-2026-023t + design_premises) ==
F1. Por cada plan en queued/, corre el freshness gate:
    validate_batch_dag.py <plan>.json --live-backlog <workspace>/.agent/collaboration/backlog.md \
      --head-sha $(git -C <motor> rev-parse HEAD)
    - exit != 0 (ticket muerto) -> el plan esta DEAD: marcalo o retiralo de queued/.
    - WARN de HEAD distinto -> re-ejecuta los probes de design_premises cuyos `touches` intersectan
      git diff <state_at_triage.motor>..HEAD. Premisa que ya no se reproduce -> ese ticket del plan
      esta STALE: anotalo (el vuelo debe congelarlo en su Paso 0).
F2. Reporta por plan: FRESCO / STALE(tickets afectados) / DEAD.

== BLOQUE A - PASADA ADVERSARIAL SOBRE LOS ARTEFACTOS (adaptado de B2) ==
A1. Aplica prompts/audit_agent_output.md (checklist esceptico) SOBRE tus artefactos de esta sesion
    (planes, fichas, prompts), no sobre codigo. Mira: conclusion sembrada en tus prompts, contexto
    recortado en tus bundles, premisa sin probe binario, colision de superficie entre planes, ficha
    que duplica un ticket vivo.
A2. ARRANQUE DEL BUCLE bajo WOT-2026-026k (si esta pasada usa fan-out). SEPARA por tipo de artefacto:
    - CoDIGO: universo del bundle derivado MECaNICAMENTE (git ls-tree/AST/lista de ficheros), regla de
      construccion declarada + hash de integridad; tu AnADES, nunca RECORTAS bajo el universo.
    - NO-CoDIGO (prompts, planes, fichas .md): 026k DECLARA que el universo mecanico para no-codigo es
      SUB-PROBLEMA ABIERTO (NON-GOAL). NO finjas el hash como cobertura completa: declara
      `NO-CODIGO_UNIVERSO_ABIERTO`; usa inventario/lista de artefactos + hash como TRAZABILIDAD minima
      (no como prueba de completitud). El objeto bajo review lo FIJA el flujo (el artefacto que ya
      existe), no tu ad-hoc.
    - En ambos: prompt NEUTRAL (traza/refuta, no confirma); GATE DE PROMPT por Codex ANTES del fan-out;
      FS obligatorio nivel-0; fallback de CLASE distinta si Codex cae (no degradar a misma clase).

== BLOQUE T - TRIAGE DE HALLAZGOS (finding_triage_protocol, B2.5) ==
T1. Cada hallazgo de A -> aplica prompts/_shared/finding_triage_protocol.md (sus categorias:
    mismo-ticket si bloquea aceptacion/regresion; hotfix autonomo 1-3 lineas bajo riesgo;
    backlog/follow-up si deuda con evidencia; Contract Formation/ticket nuevo si cambia
    contrato/FLT/arquitectura; checkpoint humano si seguridad/PII/irreversible). MAPEO a la sesion
    de diseno (read-only, no implementa): "mismo-ticket/hotfix" -> corrige el artefacto ahora;
    "backlog/follow-up" -> ficha al inbox; "CF/ticket nuevo" -> ficha DISENO_PRIMERO al inbox;
    "checkpoint humano" -> REQUIERE_HUMANO; "deuda que NO bloquea el deliverable" ->
    sugerencia/observacion con evidencia (no infla el inbox). Reporta la categoria del protocolo +
    su mapeo. Sin triage no se ficha nada.

== BLOQUE D - DEDUPE + REGISTRO (umbral de evidencia de B1.3.7 + via follow-up del motor) ==
D1. Por cada ficha en backlog_inbox/: comprueba que NO exista ya una fila equivalente en backlog.md
    (evita el duplicado). Si existe -> vincula/absorbe, no dupliques.
D2. Gate de evidencia (umbral de B1.3.7): una ficha SOLO queda en el inbox si tiene evidencia
    verificable (al menos un hallazgo VERIFICADO por audit_agent_output.md; INFERIDO no basta para
    fichar). Sin evidencia -> se retira o degrada a observacion.
D3. FOLLOW-UP DEL MOTOR (parte (b) de B1.3.7): si en el cierre descubres un defecto/deuda del MOTOR
    (no de tus artefactos) -> ficha al inbox con `delivery_authority: repo_motor` + evidencia +
    dedupe contra backlog.md. Su destino final (backlog.md) lo escribe DESARROLLO en su Bloque 5.
    NUNCA se escribe un follow-up en repo_motor ni en memoria (AGENTS.md).
D4. NO escribes backlog.md (lo hace desarrollo al fusionar el inbox). NO commiteas ningun repo.
D5. RECIBO DE DECISIONES (obligatorio -- WOT-2026-042w). Antes de dar por buena una ficha o un plan,
    CONSULTA el registro de decisiones y verifica que su recibo esta escrito y es resoluble. Son DOS
    registros y NO se mezclan: `<motor>/docs/decisions/*.md` -> scope (motor);
    `<workspace>/.agent/planning/decisions.md` -> scope (destino). LECTURA ONLY: no anadas, edites ni
    reordenes ninguna DEC (crear o cambiar una DEC es decision humana aparte).
    Cada artefacto lleva su recibo en UNA de estas TRES formas exactas y parseables:
      DEC-<id> (motor)
      DEC-<id> (destino)
      DEC-no-aplica: <motivo>
    El scope entre parentesis dice contra QUE registro se resuelve el id. Un `DEC-<id>` que NO EXISTE
    en el registro que su propio scope declara es recibo INVALIDO -> el artefacto no cierra (ROJO), no
    se le concede el beneficio de la duda. `DEC-no-aplica` exige motivo escrito; vacio o "n/a" no vale.
    Si la adjudicacion del artefacto CONTRADICE una DEC aceptada, el recibo declara ademas
    `supersedes: DEC-<id>` o `invalidates: DEC-<id>` sobre la DEC CONCRETA, con motivo. El override
    queda ESCRITO y NO existe flag para saltarselo: contradecir en silencio una DEC aceptada es
    justamente el fallo que este recibo previene.

== BLOQUE L - LIMPIEZA DE RESIDUOS DE RUNTIME (propio; hueco cazado por el bucle) ==
L1. La sesion genero residuos gitignored que git status NO ve pero ensucian semanticamente el
    workspace: bundles/jobs de fan-out (reports/gov_*/, job_*.json, out_*.json), borradores.
    Decide por cada uno: CONSERVAR (evidencia citada por una ficha/plan -> se queda) o RETIRAR
    (transitorio sin consumidor). No borres a ciegas: un gov_* citado como evidencia es load-bearing.
L2. GARBAGE-COLLECTION de queued/: un plan marcado DEAD/STALE en el Bloque F que ya no se va a
    ejecutar NO se queda en queued/ (el siguiente diseno lo re-intentaria). NO lo muevas a done/:
    done/ lo mueve DESARROLLO (esta en tu zona prohibida). Si el plan es artefacto tuyo y no debe
    ejecutarse, RETiRALO de queued/ y deja la razon en reports/; si requiere trazabilidad operativa,
    deja una nota/ficha para que desarrollo lo archive en done/. Un plan a medias/abortado se anota,
    no se deja como cadaver en queued/.

L3. PODA OPCIONAL DEL SCRATCH DEL HARNESS (misma familia que L1: residuo que
    `git status` no ve). El harness crea un directorio por SESION bajo
    `<TEMP>/claude/<proyecto>/<session-uuid>/`; no lo crea el motor ni tu sesion
    de diseno, pero se acumula igual. NO es la fuga de `WOT-2026-059d` (esa vive
    en la RAIZ del TEMP y la crean los tests del motor: se arregla limpiando en
    el test, no podando).
    - EVIDENCIA FECHADA (2026-08-25, NO criterio): 1.769 sesiones, 1.502 sin
      tocar en >14 dias. El coste son INODOS y latencia, no espacio.
    - `python <repo_motor>/scripts/prune_session_scratch.py --days 14`
      DRY-RUN por defecto; `--apply` BORRA y es IRREVERSIBLE. La exclusion por
      `mtime` protege a la sesion VIVA sin conocer su id; solo toca bajo
      `<TEMP>/claude/`.
    - **Read-only manda**: en una sesion de DISENO corre SOLO el dry-run y CITA
      el censo. `--apply` borra, y borrar NO es read-only: si procede, deja la
      recomendacion en `reports/` para que la ejecute el operador o el cierre de
      desarrollo. Reporta `[SCRATCH: <n> candidatas -- dry-run, no podado]`.

== BLOQUE M - MEMORIA (minimo) ==
M1. Hubo alguna LECCIoN de comportamiento (no infraestructura)? Infra -> documentacion/ficha, NO
    memoria (AGENTS.md). Solo si hay leccion real de comportamiento, proponla (no la escribas: el
    canal de memoria lo gobierna otra pasada).

SALIDA: reporte por bloque (H/I/F/A/T/D/L/M), con VEREDICTO por artefacto (FRESCO/STALE/DEAD, solido/
CHANGES) y el estado de huella (cero / no-cero con explicacion). La sesion de diseno cierra LIMPIA
solo si: huella cero verificada, todo plan FRESCO o su staleness anotada, toda ficha con evidencia y
sin duplicado, TODO artefacto con su recibo de decisiones escrito y resoluble (D5), todo hallazgo
triado, y los residuos de runtime resueltos (conservados con dueno o retirados).
```

---

## Diferencias con el cierre canonico (resumen)

- **Quita** lo que asume commits (salud, hooks, portabilidad, --session-close, gates de arbol).
- **Reutiliza** el umbral de evidencia (B1.3.7a), la pasada adversarial (B2->A) y el triage
  (B2.5->T, mapeado a las categorias de finding_triage_protocol).
- **Anade** 5 bloques propios: Huella cero (H), Inventario (I), Freshness de planes (F),
  Dedupe+follow-up-del-motor (D), Limpieza de residuos (L).
- **Integra** el arranque de bucle bajo WOT-2026-026k (A2, separando codigo de NO-codigo: el
  universo mecanico para no-codigo queda declarado ABIERTO, no fingido) y el anti-staleness
  (F, WOT-2026-023t).

## Cuando usarlo

Al terminar una sesion de DISEnO (planning) read-only que produjo planes de vuelo (flight_plans/)
y/o fichas de tickets (backlog_inbox/). Su hermano de arranque es el bootstrap de sesion de diseno.

## Cuando NO usarlo

- En una sesion de DESARROLLO que commiteo codigo: usa `orchestrator_session_close_full_audit.md`.
- En consultas exploratorias que no produjeron planes ni fichas: no hay nada que cerrar.
