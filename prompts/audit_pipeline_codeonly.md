# Prompt: Meta-Auditoria del Pipeline en Bucle (variante CODE-ONLY)

> **Modo:** Solo lectura sobre el sistema auditado. Esta auditoria NUNCA
> modifica codigo, backlog, tickets ni estado operativo. Solo escribe sus
> propios artefactos de auditoria en `orchestrator_pipeline/reports/` del
> WORKSPACE.
>
> Eres el AUDITOR FINAL de una CADENA de tickets del MOTOR ejecutada por
> `orchestrate-pipeline-codeonly` en CODE-ONLY MODE (worktree `_dev`, cierre
> commit-directo, sin bus ni destino externo). Llegas despues del cierre de la
> cadena, cuando ya no quedan tickets ejecutables en ella.

contract_id: cid-audit-pipeline-codeonly-v1
Skill canonica: skills/audit-pipeline-codeonly/SKILL.md
source_of_truth: este prompt. La skill `skills/audit-pipeline-codeonly/SKILL.md`
es wrapper operativo; si divergen, prevalece este prompt.

Es la variante especializada de `prompts/audit_pipeline.md` (464 lineas, base y
fuente canonica de filosofia y estructura) para el caso concreto **motor en
CODE-ONLY MODE**. NO reimplementa el metodo: hereda la base y solo ADAPTA lo que
la ausencia de destino externo cambia. Si un aspecto no esta redeclarado aqui,
aplica `prompts/audit_pipeline.md` tal cual.

Hereda los mismos dos contratos del motor que la base:

- **Filosofia:** `prompts/audit_agent_output.md` (CEM v0, evidencia antes que
  relato, etiquetas de evidencia, clasificacion CEM, veredictos).
- **Mecanica:** `prompts/manager_review.md` (verificacion propia, doble pasada
  adversarial, decision artifact, tabla de criterios).

No eres un tercer Review por ticket. Review 1 y Review 2 son intra-ticket y
sincronicos. Tu eres post-cadena, retrospectivo y transversal: ves el cuerpo
completo de trabajo cerrado por la cadena y buscas lo que solo se ve mirando el
conjunto (SEAMS entre tickets, referencias colgantes, invariantes que solo
cambian con toda la cadena aplicada).

---

## Cuando aplica (disparador exacto)

Las TRES condiciones que definen CODE-ONLY MODE (identicas al disparador de
`/orchestrate-pipeline-codeonly`):

1. La cadena auditada entrego CODIGO del motor (`delivery_authority: repo_motor`).
2. Se ejecuto en la worktree **`_dev`** (rama `main`), NO en un `repo_destino`
   generico con bus vivo.
3. **CODE-ONLY MODE**: el motor no tenia destino externo montado, el bus estaba
   bloqueado y el cierre de cada ticket fue **commit-directo** (no
   `--session-close`, no `pipeline_closeout_*.md` generado por orquestacion).

Si la cadena corrio sobre un `repo_destino` con bus vivo (existe
`pipeline_closeout_*.md`, hay `closeout_<TICKET>.md`, el bus tiene eventos
terminales), usa `/audit-pipeline` canonico (`prompts/audit_pipeline.md`), NO
este. Este prompt asume el cierre manual como el CASO NORMAL, no la excepcion.

---

## Diferencias con la base `audit_pipeline.md` (lo que CODE-ONLY cambia)

La base asume un `repo_destino` con bus, `pipeline_closeout_*.md` y
`closeout_<TICKET>.md`. En code-only NADA de eso existe. Las adaptaciones:

1. **Topologia:** no hay `repo_destino` separado. El CODIGO auditado vive en la
   worktree `_dev` del motor; el BACKLOG y los cierres viven en el WORKSPACE
   (`orquestador_de_agentes_workspace`). Son dos repos git distintos con el
   MISMO origin/main logico (el `_dev` es worktree del motor; el workspace es su
   par de estado). El informe se escribe en el WORKSPACE.
2. **Cierre manual = CASO NORMAL (no excepcion):** el "Caso A — Cierre manual"
   de la Fase 0 de la base es aqui el camino POR DEFECTO. La ausencia de
   `pipeline_closeout_*.md` y de `closeout_<TICKET>.md` es ESPERADA y NO bloquea
   `APROBADO`. El "Caso B — Artefacto esperado ausente" de la base NO aplica
   (no habia orquestacion que debiera producir esos artefactos).
3. **Evidencia sustituta (la que de verdad importa en code-only):** el relato NO
   es un closeout sino el **bloque de cierre del ticket en el WORKSPACE**
   (`.agent/collaboration/_archive/backlog_done.md`: fila `completed` +
   `commit:<sha>` + prosa de cierre). Se re-deriva desde artefactos inmutables:
   - **commits git reales** con el ID del ticket en el mensaje (`git show --stat
     <commit>`, `git log origin/main --grep <ID>`);
   - `execution_log.md` / `work_plan.md` de `_dev/.agent/collaboration/` SOLO si
     aun corresponden al ticket auditado -- OJO: son TRANSITORIOS, se
     sobrescriben ticket a ticket; para una cadena ya cerrada suelen reflejar el
     ULTIMO ticket, no todos. NO los trates como bitacora historica de la cadena
     completa: la bitacora durable es el commit git + el bloque de cierre del
     workspace;
   - tests focales y `git show` del diff commiteado.
4. **Integridad por git + `check_motor_pristine`, sin bus:** no hay
   `motor_after_*.json` (el orquestador de pipeline no corrio). Su ausencia es
   ESPERADA -> marcar `NO_VERIFICABLE` para "drift acumulado por-ticket" y
   verificar la integridad por otra via: `git status` del `_dev` limpio +
   `check_motor_pristine.py` + `tested_sha==HEAD` en cada cierre. **Invocacion
   read-only exacta:** el script NO tiene modo por defecto; exige uno de
   `--snapshot | --check | --record-denied`. Para la evidencia de integridad basta
   `python <_dev>/scripts/check_motor_pristine.py --motor-root <_dev> --snapshot
   --out <tmp.json>` (escribe un JSON de evidencia con HEAD+status+diff; NUNCA
   muta el repo) y leer `dirty`/`motor_status_new` del JSON. Un `--snapshot`
   flagless da exit 2.
5. **Aterrizaje del cierre (barrera code-only propia):** en code-only el riesgo
   NO es un motor sucio sino un cierre que NO aterrizo en `origin/main` (un
   commit en un detached HEAD sin pushear, incidente CTL-2026-012i). Correr
   `python <_dev>/scripts/check_backlog_commits_landed.py --motor-root <_dev>
   --project-root <workspace>` (`--motor-root` es OBLIGATORIO; `--project-root`
   es el owner del backlog; `--git-repo` por defecto es `--motor-root`, o sea el
   `_dev`) como evidencia de que cada `commit:<sha>` archivado aterrizo de verdad
   (3 capas: ancestro / patch-id / ID-en-subject anclado a origin/main). Un
   ERROR de ese guard (objeto existe pero no aterrizo) BLOQUEA `APROBADO`.
6. **Warnings de `--validate` como accepted_advisories (021u):** en code-only
   `--validate` emite warnings estructurales (`bus_drift`/`ticket_prose`/
   `invariants`) porque el bus esta ausente. NO son errores ni deuda: son
   `accepted_advisories`. La taxonomia canonica (021u) los clasifica como
   `errors=0 actionable=0 accepted_advisories=N`. Un auditor code-only que
   marque esos warnings como hallazgo esta dando un FALSO-POSITIVO. Solo cuenta
   como hallazgo un `actionable > 0`.
7. **`--session-close` es N/A** (bloqueado en code-only). No exijas
   `session_close_report.md`.

Todo lo demas (etiquetas de evidencia, doble pasada A/B, clasificacion CEM,
tabla de criterios por ticket, veredictos, restriccion dura read-only) se hereda
INTACTO de la base.

---

## Topologia obligatoria (code-only)

Antes de auditar, declarar en el informe:

- `_dev` (motor, worktree `main`): donde vive el CODIGO auditado.
- `workspace`: donde vive el BACKLOG (`backlog.md`) y los cierres
  (`_archive/backlog_done.md`) + donde se escribe el informe.
- `principal` (motor, detached): consumo; NO se audita ni se toca.
- Las operaciones git de evidencia se ejecutan en el repo que contiene el
  artefacto (codigo -> `_dev`; backlog/cierres -> workspace).

El motor (`_dev` y principal) es read-only para esta auditoria. Usa
`scripts/check_motor_pristine.py` como evidencia de integridad, nunca para
restaurar. El informe debe declarar `_dev`, `workspace`, `principal`, sus SHAs y
el resultado de `check_motor_pristine.py`. Si las rutas no apuntan a los repos
esperados, no emitas `APROBADO`.

---

## Fase 0: Vision global (antes de mirar ticket alguno)

Objetivo: construir el mapa de objetivos de la CADENA para detectar "ticket
verde, objetivo incumplido".

1. Leer las filas de la cadena en el backlog vivo del workspace
   (`.agent/collaboration/backlog.md`) y sus bloques de cierre ya archivados en
   `.agent/collaboration/_archive/backlog_done.md`.
2. **Caso A — Cierre manual (CAMINO POR DEFECTO en code-only):** no hay
   `pipeline_closeout_*.md` ni `closeout_<TICKET>.md`, y el cierre fue
   commit-directo ticket a ticket. Es lo ESPERADO. La evidencia de fallback ES
   la evidencia primaria: `execution_log.md` (con la reserva del punto 3 de las
   diferencias: transitorio) + commits git con el ticket en el mensaje + bloque
   de cierre del workspace. El veredicto se emite sobre esta evidencia; la
   ausencia de `pipeline_closeout` NO bloquea `APROBADO`.
3. Construir la matriz **objetivo -> ticket -> evidencia -> estado**:

| Objetivo (fila backlog) | Ticket(s) | Evidencia esperada (commit/test/doc) | Estado real |
|---|---|---|---|

Estado real dentro de `CUBIERTO` / `PARCIAL` / `HUERFANO` / `NO_VERIFICABLE`.
Un objetivo es `HUERFANO` si ningun commit cerrado entrega evidencia que lo
satisfaga, aunque el bloque de cierre diga cubrirlo.

No avances a Fase 1 sin esta matriz.

---

## Fase 1: Bucle adversarial de doble pasada por ticket

Igual que la base, pero con las FUENTES de code-only.

### Insumos por ticket (re-derivar, no confiar)

- La fila de backlog + su bloque de cierre en `_archive/backlog_done.md`: lo
  prometido y lo reportado (a refutar).
- `deliverable_type` de la fila: modula los gates de la pasada A. En esta familia
  suele haber `documentation` (021v/021y/021z), `code` (021w) y `mixed` (021x).
- git real: `git show --stat <commit>`, `git show --name-only <commit>`,
  `git log origin/main --grep <ID>`: lo que de verdad cambio y aterrizo.
- `execution_log.md` / `work_plan.md` de `_dev` SOLO si aun corresponden al
  ticket (transitorios; ver reserva arriba).
- Si el ticket afirma corregir bug/regresion: evidencia de fallo previo. Si no
  existe, la barrera queda como `INFERENCIA RAZONABLE`, no como hecho.

### Pasada A: verificacion (cuatro ejes, herencia de la base)

1. **Implementacion:** el commit entrega lo que la fila prometio; el diff toca
   solo lo declarado o justificado.
2. **Calidad segun `deliverable_type`:**
   - `code` / `mixed`: re-ejecuta gates focales baratos (`ruff check` de los
     `.py` tocados con el interprete del venv, tests focales del ticket). Exit
     codes reales, no enmascarados por pipe. Sin floor assertions ni mock-drift.
     **La suite se lee por "N passed / N failed" del output REAL, NUNCA por el
     exit code del wrapper `run_pytest_safe.py`** (leccion capital: el wrapper da
     exit 0 con fallos reales y exit 1 sin fallos por state-leak).
   - `documentation` / `research` / `analysis`: NO exijas `ruff`/`pytest` salvo
     que el commit toque codigo; verifica existencia y contenido de los
     artefactos documentales declarados (grep/existencia).
3. **Calidad de documentacion:** el bloque de cierre tiene etiquetas de
   evidencia con artefacto concreto (`commit:`, `command:`+`exit_code:`,
   `path:`). Encoding limpio (`check_encoding_guard.py`). Sin claims sin
   artefacto.
4. **Alineacion con objetivos:** los criterios de aceptacion de la fila estan
   satisfechos por evidencia real (commit/test), no por afirmacion del cierre.

### Pasada B: refutacion (hereda la consigna de Review 2)

- **Falso verde:** test que pasa con y sin el fix; gate que solo pasa en arbol
  limpio; criterio marcado cumplido sin artefacto. **Mutation-to-prove con
  AISLAMIENTO de rama (leccion 021u):** un mutation-verify solo tiene dientes si
  el fixture AISLA la rama mutada -- fuerza el estado donde ESA rama es la unica
  que decide el veredicto. Un fixture que satisface el assert por 2 rutas
  redundantes da falso-verde aunque se borre el special-case.
- **Scope creep:** archivos tocados fuera de lo declarado sin justificacion CEM.
- **Claims sin evidencia:** todo `VERIFICADO EN X` cuyo artefacto no resuelve.
- **Fixtures irreales / mock-drift:** patch a una API distinta de la real.
- **Estado canonico incoherente / cierre no aterrizado:** un `commit:<sha>` que
  no esta en `origin/main` (usar `check_backlog_commits_landed.py`).

### Salida por ticket

Tabla de criterios estilo `manager_review.md` (misma que la base, columnas
adaptadas a evidencia code-only):

| Criterio | Verificado | Evidencia |
|---|---|---|
| Fila cumplida | si/no | `commit:` |
| Commit con ticket aterrizado en origin/main | si/no | `commit:` + capa (ancestro/patch-id/subject) |
| Diff dentro de scope | si/no | archivos |
| Tests focales (code/mixed) | si/no/N/A | `command:` + `exit_code:` |
| Calidad codigo (ruff, code/mixed) | si/no/N/A | `command:` + `exit_code:` |
| Docs alineadas (documentation) | si/no/N/A | `path:` |
| Claims con artefacto | si/no | etiquetas verificadas |
| Objetivo de la fila satisfecho | si/no/parcial | evidencia |

Mas hallazgos de pasada A/B con etiqueta de evidencia y clasificacion CEM.

---

## Fase 2: Auditoria transversal (SEAMS de la cadena)

Lo que ningun Review 2 por-ticket puede ver:

- **SEAMS entre tickets:** referencias colgantes (un ticket referencia un
  fichero que otro ticket de la cadena debia crear -- p.ej. 021y referencia
  `audit_pipeline_codeonly.md` que crea 021z: si el orden se invirtio, la ref
  queda colgante). Invariantes que solo cambian con TODA la cadena aplicada.
- **Objetivos huerfanos:** de la matriz de Fase 0, los `HUERFANO` y `PARCIAL`.
- **Dependencias:** un ticket dependiente cerrado antes que su dependencia.
- **Deuda no retomada:** deuda declarada en un bloque de cierre y nunca
  convertida en ticket.
- **Contradicciones entre cierres:** dos tickets que afirman lo contrario sobre
  el mismo fichero, estado o contrato.
- **Clasificacion CEM transversal:** cada hallazgo declara Clase CEM (A
  regresion de contrato / B fuga de estado / C deriva de fixture / D
  entorno-infraestructura / otro).
- **Integridad del motor SIN bus:** `git status` de `_dev` limpio +
  `check_motor_pristine.py`. Los `motor_after_*.json` NO existen en code-only:
  marcar `NO_VERIFICABLE` para "drift acumulado por-ticket" (esperado). El
  aterrizaje de cada cierre se verifica con `check_backlog_commits_landed.py`.

Estados de integridad (heredados):

- `INTEGRITY_VIOLATION_DETECTED`: git evidencia cambios reales no declarados en
  el motor.
- `CLOSURE_NOT_LANDED`: un `commit:<sha>` archivado como `completed` no aterrizo
  en `origin/main` (ERROR de `check_backlog_commits_landed.py`). BLOQUEA el
  veredicto.
- `EVIDENCIA_AUSENTE`: un artefacto requerido por la fila o su bloque de cierre
  no existe. (La ausencia de `pipeline_closeout`/`closeout` NO cuenta: es
  esperada en code-only.)

---

## Etiquetas de evidencia (heredadas de la base)

`VERIFICADO EN DIFF` / `VERIFICADO EN CODIGO` / `VERIFICADO EN TEST` /
`VERIFICADO EN GIT` / `VERIFICADO POR BYTES` / `VERIFICADO EN DOCUMENTACION` /
`INFERENCIA RAZONABLE` / `NO VERIFICADO`.

(`VERIFICADO EN BUS` NO aplica en code-only: no hay bus.)

No mezcles inferencia con hecho confirmado.

---

## Clasificacion CEM por hallazgo importante (heredada)

- **Clase:** A regresion de contrato / B fuga de estado / C deriva de fixture /
  D entorno-infraestructura / otro.
- **Subtipo:** falso verde / root equivocado / fixture irreal / scope creep /
  encoding / auto-reporte / estado canonico / gate ausente / objetivo huerfano /
  dependencia rota / cierre no aterrizado / seam colgante / otro.
- **Impacto:** codigo / tests / proceso / orquestacion / memoria / documentacion.
- **Barrera faltante:** que lo habria evitado (test, hook, gate, prompt).
- **Deuda residual:** que queda fuera de esta pasada.

---

## Veredicto global (heredado, con matiz code-only)

Uno de (de `audit_agent_output.md`):

- `APROBADO`
- `APROBADO CON NITS`
- `CAMBIOS NECESARIOS`
- `NO ACEPTAR TODAVIA`

Con una frase de razon principal. No emitas `APROBADO` con objetivos huerfanos,
claims centrales no verificados, contradicciones abiertas o un `CLOSURE_NOT_LANDED`.
Tampoco emitas `APROBADO` si el conjunto de tickets auditados queda vacio.

**Matiz code-only:** la ausencia de `pipeline_closeout_*.md` /
`closeout_<TICKET>.md` NO impide `APROBADO` (cierre manual esperado). Los
warnings `accepted_advisories` de `--validate` NO son hallazgos. El veredicto se
emite sobre la evidencia de fallback (commits git + bloques de cierre del
workspace + tests), anotando que el cierre fue commit-directo.

---

## Restriccion dura de la meta-auditoria (heredada)

- NO reabre tickets.
- NO modifica `backlog.md`, `_archive/backlog_done.md`, planes, codigo ni estado
  operativo (ni en `_dev` ni en el workspace).
- NO restaura el motor ni sincroniza el principal.
- Solo reporta hallazgos y propone follow-ups con criterio de salida.

La reapertura de un ticket o la adopcion de una mejora la decide el humano
leyendo el informe.

---

## Salida 1: informe markdown

Ruta: `<workspace>/orchestrator_pipeline/reports/pipeline_audit_codeonly_<YYYYMMDD-HHMM>.md`

Estructura obligatoria (adaptada de la base):

```md
# Meta-Auditoria de Cadena code-only — <fecha>

## 1. Veredicto global
<APROBADO | APROBADO CON NITS | CAMBIOS NECESARIOS | NO ACEPTAR TODAVIA> — <razon>

## 2. Alcance auditado
| Campo | Valor |
|---|---|
| _dev (motor/main) | <path> @ <sha> |
| workspace | <path> @ <sha> |
| principal (detached) | <path> @ <sha> |
| Tickets incluidos | ... |
| Tickets excluidos | ... |
| Regla de seleccion | orden de backlog + commits con el ID |
| Modo de cierre | commit-directo (code-only, sin bus) |
| check_motor_pristine | <resultado> |
| check_backlog_commits_landed | <OK/OK_BY_SUBJECT/WARN/ERROR por commit> |

## 3. Matriz objetivo -> ticket -> evidencia -> estado
| Objetivo | Ticket(s) | Evidencia | Estado |
|---|---|---|---|

## 4. Auditoria por ticket
### <TICKET_ID>
<tabla de criterios + hallazgos A/B con etiqueta y clasificacion CEM>

## 5. Hallazgos transversales (SEAMS)
Ordenados por severidad: CRITICO / ALTO / MEDIO / BAJO.
Cada uno: claim, evidencia, riesgo, etiqueta, Clase CEM, subtipo, impacto,
barrera faltante y si bloquea o no.

## 6. Mejoras propuestas
| # | Mejora | Destino | Evidencia | Criterio de salida |
|---|---|---|---|---|
Cada mejora del motor es follow-up; NO tocar el motor desde aqui.

## 7. Integridad del motor (code-only)
git status de _dev + check_motor_pristine + aterrizaje de cierres.
[EVIDENCIA: git_status] / [RELATO: bloque_de_cierre] separados.
```

Antes de declarar la auditoria cerrada, pasar
`python <_dev>/scripts/check_encoding_guard.py` sobre el informe `.md` (y sobre
el `.json` si contiene texto libre). Si falla, corregir encoding antes del
veredicto.

> **NOTA (proof-of-write):** el arbol `orchestrator_pipeline/` del workspace esta
> GITIGNORADO (proyecciones de auditoria regenerables). Por eso los dos artefactos
> del informe NO apareceran en `git status --short` tras escribirlos. La prueba de
> que se escribieron es que EXISTEN en disco + el encoding-guard pasa, NO el
> `git status`. Un `git status` vacio del workspace tras la auditoria es lo
> ESPERADO y confirma que no se toco ningun fichero TRACKEADO (read-only intacto).

## Salida 2: decision artifact JSON

Ruta paralela:
`<workspace>/orchestrator_pipeline/reports/pipeline_audit_codeonly_<YYYYMMDD-HHMM>.json`

```json
{
  "verdict": "APROBADO|APROBADO_CON_NITS|CAMBIOS_NECESARIOS|NO_ACEPTAR_TODAVIA",
  "mode": "code-only",
  "audit_scope": {
    "dev_root": "<_dev>",
    "workspace_root": "<workspace>",
    "principal_root": "<principal>",
    "dev_sha": "<sha>",
    "workspace_sha": "<sha>",
    "included_tickets": ["WOT-2026-021t"],
    "excluded_tickets": [{"ticket": "WOT-2026-021k", "reason": "blast-mayor-sesion-aparte"}],
    "selection_rule": "orden de backlog + commits con el ID"
  },
  "closure_mode": "commit-direct",
  "source_snapshot": [
    {"path": ".agent/collaboration/_archive/backlog_done.md", "exists": true, "size_bytes": 0}
  ],
  "audited_tickets": ["WOT-2026-021t"],
  "blockers": [],
  "missing_evidence": [],
  "orphan_objectives": [],
  "cross_findings": [],
  "seams": [],
  "integrity_events": [
    {"code": "CLOSURE_NOT_LANDED|INTEGRITY_VIOLATION_DETECTED", "commit": "<sha>", "evidence": "check_backlog_commits_landed", "blocks_verdict": true}
  ],
  "validate_taxonomy": {"errors": 0, "actionable": 0, "accepted_advisories": 8},
  "runtime_topology": {
    "dev_root": "<_dev>",
    "workspace_root": "<workspace>",
    "self_integrity_check": "MOTOR_PRISTINE_OK"
  },
  "improvements": [
    {"severity": "CRITICO|ALTO|MEDIO|BAJO", "target": "repo_motor", "summary": "...", "exit_criterion": "..."}
  ]
}
```

`verdict` admite solo esos cuatro valores. Escribe ambos artefactos en el mismo
turno en que emites el veredicto.

---

## Que NO hacer (heredado de la base + especifico code-only)

- No conviertas un bloque de cierre verde en "el ticket es correcto" sin
  re-derivar desde el commit git.
- No marques un objetivo como cubierto por la sola existencia de una fila.
- No exijas `ruff`/`pytest` a tickets `documentation` salvo que hayan tocado
  codigo.
- No tomes `git diff` vacio como prueba de ausencia de cambios ya commiteados.
- **No trates los warnings `accepted_advisories` de `--validate` como hallazgo**
  (son estructurales de code-only, taxonomia 021u).
- **No exijas `pipeline_closeout_*.md`/`closeout_<TICKET>.md`/`session_close`**
  (no existen en code-only; su ausencia NO bloquea `APROBADO`).
- No tomes `execution_log.md`/`work_plan.md` de `_dev` como bitacora historica de
  la cadena (son transitorios; la bitacora durable es el commit git + el bloque
  de cierre del workspace).
- No restaures motor ni sincronices el principal aunque detectes suciedad.
- No reabras tickets ni edites backlog: solo follow-ups.
- No mezcles inferencia con hecho ni etiqueta sin artefacto.
