# Orchestrator Destination Batch Prompt

> Meta-prompt para un orquestador EXTERNO que prepara varios `repo_destino`
> para publicacion remota usando el motor `orquestador_de_agentes` como
> herramienta portable. Procesa los destinos uno a uno: clasifica estado,
> forma contrato, ejecuta el pipeline por ticket, audita y deja cada repo en un
> estado de publicacion explicito antes de pasar al siguiente.
>
> Skill canonica: `skills/orchestrate-destination-batch/SKILL.md`
> contract_id: `cid-orchestrator-destination-batch-v1`
> source_of_truth: este prompt. La skill es wrapper operativo; si divergen,
> prevalece `prompts/orchestrator_destination_batch.md`.
>
> Herramienta determinista del lote:
> `scripts/batch_destination_controller.py` (read-only; emite un manifest por
> destino, nunca un verde agregado).

---

## Frontera y herencia

Este prompt NO reimplanta tickets ni reescribe el pipeline por destino. Es el
orquestador superior que decide QUE destino va despues y conserva un indice
global. La implantacion real de cada destino vive en
`prompts/orchestrator_pipeline.md`; la formacion de contrato en
`prompts/contract_formation_pipeline.md`; la auditoria de publicacion en
`prompts/audit_git_publication.md`.

Hereda la filosofia de `prompts/audit_agent_output.md`: evidencia antes que
relato, verificacion topologica propia, etiquetas de evidencia y barrera antes
que memoria. Un manifest agregado NO sustituye los artefactos canonicos del
destino (`.agent/`, bus, backlog, git, closeouts): cada fila del manifest cita
su propia evidencia (`path:`, `command:` + `exit_code:`).

El motor es read-only salvo que un destino declare explicitamente un ticket con
`delivery_authority: repo_motor` (por ejemplo, la propia instalacion del motor
en el destino via `install_agent_system.py`). Una escritura autorizada al motor
NO es drift; el orquestador debe declararla antes para no disparar un falso
bloqueo sistemico.

---

## Modelo de estados por destino

El batch NO colapsa estados. Cada destino avanza por una cadena observable:

| Estado | Quien lo decide | Evidencia |
|---|---|---|
| `adopted` | existe `.agent/config/motor_destination_link.json` | `path:` |
| `contract_ready` | planning frozen + `audit_cf_ticket_contract.md` APPROVE | `path:` + decision |
| `agent_project_root_verified` | `memory_context.py --status` refleja el repo | `command:` + `exit_code:` |
| `integrated_local` | `check_destino_publish_ready.py` / validate 0/0 | `command:` + `exit_code:` |
| `publication_classified` | `classify_publication.py` (historia completa) = LISTO | `path:` (**[RELATO]**) |
| `publication_audit_passed` | `audit_git_publication.md` Pasada B (agente) | `path:` closeout |
| `publishable` | Local + Classified + Audited, los tres | derivado |

Regla dura: `publishable` es `true` SOLO si `integrated_local`,
`publication_classified` y `publication_audit_passed` son los tres `true`. El
verdict de `classify_publication.py` es `[RELATO]`, no evidencia final. El
orquestador NUNCA declara un destino publicable a partir del script
determinista solo.

---

## Adopcion =/= primer ticket ejecutable

Un destino recien adoptado (`adopted=true`) pero sin
`repo_charter.md` / `plan_graph.md` / `ticket_contracts.md` frozen NO esta listo
para Builder. Es `RUN_CONTRACT_FORMATION`. La integracion completa motor-destino
toca mas de una superficie de estado compartido: por
`prompts/orchestrator_pipeline.md` (seccion 2.a) dispara
`CONTRACT_FORMATION_REQUIRED` y por el gate de loop-readiness
(`prompts/_shared/loop_readiness.md`) es por defecto NO_LOOPEABLE. Va
supervisada por Manager; solo sub-tareas estrechas que pasen el gate usan /goal
autonomo, y siempre con `max_iterations` declarado segun
`prompts/_shared/loop_budget.md`.

---

## Flujo por destino (secuencial)

Para cada destino del lote, en orden:

### 0. Topologia propia (gate)

Antes de tocar el destino, fija y verifica el root operativo:

```powershell
$env:AGENT_PROJECT_ROOT = (Resolve-Path <REPO_DESTINO>).Path
python <MOTOR_ROOT>/scripts/memory_context.py --status
```

Si `--status` muestra rutas del `repo_motor` en vez del destino, la env var no
quedo fijada en esa shell. El harness no persiste shell state entre destinos:
re-fija `AGENT_PROJECT_ROOT` por destino y vuelve a verificar. Si no se puede
verificar, marca `FIX_AGENT_PROJECT_ROOT_FOR_REPO` y NO sigas con ese destino
(no detiene el lote: pasa al siguiente).

### 1. Clasificacion read-only

```powershell
python <MOTOR_ROOT>/scripts/batch_destination_controller.py --repos <REPOS_JSON> --motor-root <MOTOR_ROOT> --out-dir <OUT_DIR> --run-readonly-gates
```

Lee el manifest y usa `next_action` por destino como guia. El manifest es el
indice global reanudable; vive fuera de `.agent/`, no es fuente de verdad.

### 2. Adopcion o reparacion

Si `adopted=false`: instala el destino con `skills/setup-agent-system` /
`skills/adopt-existing-project`. Declara el ticket de instalacion con
`delivery_authority: repo_motor` si toca el motor.

### 3. Contract Formation

Si `contract_ready=false`: `prompts/contract_formation_pipeline.md`. Audita cada
ticket con `prompts/audit_cf_ticket_contract.md` antes de `frozen`
(clarification rate = 0, DoD binario, CONTRACT_GAP behavior, evidencia
concreta). Si el Builder tendria que preguntar, vuelve a Contract Formation o
crea `DEC-*`; no improvises en ejecucion.

### 4. Pipeline por ticket

`prompts/orchestrator_pipeline.md` gobierna. Snapshot/check del motor por ticket
ya es canon ahi; el batch lo obedece y lo evidencia, no lo reimplanta. El
contador de 3 bloqueos consecutivos es LOCAL al destino: agota un destino, no el
lote, salvo patron sistemico (misma herramienta del motor fallando en varios
destinos, confusion de topologia, escritura fuera del destino).

### 5. Auditorias de cierre

`prompts/audit_post_change_system_health.md`,
`prompts/audit_complete_motor_destination.md`,
`prompts/audit_portability_legacy_surface.md`, `prompts/audit_pipeline.md`,
`prompts/orchestrator_session_close_full_audit.md`.

### 6. Publicacion (dos capas, no se sustituyen)

Primero el gate de estado vivo y la clasificacion determinista con historia
completa:

```powershell
python <MOTOR_ROOT>/scripts/check_destino_publish_ready.py --project-root <REPO_DESTINO> --motor-root <MOTOR_ROOT>
python <MOTOR_ROOT>/scripts/classify_publication.py --repo-root <REPO_DESTINO> --out <REPO_DESTINO>/orchestrator_pipeline/reports/publication_manifest.json
```

No uses `--quick` ni `--no-history` para aprobar: no pueden emitir
`LISTO_PARA_PUBLICAR`. Despues, la Pasada B adversarial de
`prompts/audit_git_publication.md`: un agente abre cada archivo `PUBLISH`,
`PUBLISH_WITH_REDACTIONS` y `DECIDE` y re-deriva por contenido. Solo cuando esa
auditoria emite `LISTO_PARA_PUBLICAR` y deja closeout, el destino pasa a
`publication_audit_passed=true`. La creacion del repo privado y el push quedan
FUERA del batch autonomo: requieren permiso humano explicito.

### 7. Recheck inter-repo

Antes de pasar al siguiente destino, si el destino cerrado comparte superficies
(credenciales, servicios, contratos de datos, artefactos generados) con otros
destinos del lote, re-verifica la premisa de esos destinos. El manifest expone
`inter_repo_recheck.overlaps`. Este nivel es NUEVO del batch: el
`pending-contract recheck` de `orchestrator_pipeline.md` es intra-repo; el batch
anade el cruce entre repos.

---

## Criterios de parada (no detienen la implantacion global)

Los posibles criterios de parada NO detienen el lote por sospecha temprana. Se
tratan como stop-candidates: se someten a intentos adversariales documentados,
se clasifican, se evidencian y se presentan en el informe final. Solo un fallo
sistemico externo detiene el lote completo.

Taxonomia:

- `HARD_STOP`: limite mecanico del loop (`prompts/_shared/loop_hard_stop.md`):
  max_iterations, tokens, timeout. Para solo el loop/ticket actual.
- `LOOP_NOT_READY`: el gate loop-readiness da NO_LOOPEABLE. No activa /goal; pasa
  a modo supervisado. No detiene el destino.
- `LOCAL_REPO_BLOCKER`: tras N intentos adversariales documentados con evidencia,
  el destino no puede avanzar en scope seguro. Bloquea ese destino, NO el lote.
  Se documenta y el batch pasa al siguiente.
- `ENVIRONMENT_ISSUE`: error de entorno del destino (`ModuleNotFoundError`,
  `PermissionError`) aislado por captura de `stderr`. Bloquea el destino, no el
  lote. Si el MISMO error del motor se repite en 2+ destinos, se reclasifica
  como sistemico.
- `GLOBAL_PIPELINE_BLOCKER`: fallo sistemico externo. Detiene el lote. Ejemplos:
  motor deja de estar pristine sin ticket que lo declare; instalador falla igual
  en 2-3 destinos por el mismo bug; validate del motor falla por bug interno;
  el batch escribe fuera del destino; no puede distinguir motor/destino.

Un stop-candidate solo se convierte en `LOCAL_REPO_BLOCKER` tras: (1) >= N
intentos adversariales documentados; (2) evidencia por comando/diff/log/auditoria;
(3) diagnostico de por que no se resuelve en scope seguro; (4) propuesta de
accion humana o follow-up; (5) registro en el informe del destino y en el
manifest. `N` se declara en el input (`adversarial_attempts_required`, default 3).

Una clasificacion de stop-candidate es PROVISIONAL hasta cumplir esos cinco
pasos: no puede cristalizar como CONFIRMADO solo por repeticion
(`audit_agent_output.md`, regla anti-cristalizacion).

---

## Informe final por destino + manifest global

Cada destino genera su seccion con:

```md
## <destino>
| Estado | Valor | Evidencia |
|---|---|---|
| adopted | si/no | `path:` |
| contract_ready | si/no | `path:` + decision |
| integrated_local | si/no | `command:` + `exit_code:` |
| publication_classified | si/no | `path:` ([RELATO]) |
| publication_audit_passed | si/no | `path:` closeout |
| publishable | si/no | derivado |

### Stop-candidates evaluados
| Candidate | Intentos | Evidencia | Resultado | Accion |
|---|---:|---|---|---|
```

El manifest global (`batch_manifest.json` + `.md`) materializa esas decisiones
con `path:` por destino. Estados terminales del lote:
`ALL_COMPLETED` / `PARTIAL_COMPLETED` / `LOCAL_BLOCKED` / `DECISION_REQUIRED` /
`GLOBAL_PIPELINE_BLOCKER`.

---

## Que NO hacer

- No declarar un destino `publishable` desde el verdict del script
  (`[RELATO]`) sin Pasada B de `audit_git_publication.md`.
- No detener el lote por un bloqueo local; solo por fallo sistemico externo.
- No imponer `--strict` global del motor sobre todos los destinos: cada
  ticket declara si el drift es bloqueante (`orchestrator_pipeline.md`).
- No tratar el manifest como fuente de verdad: el estado real vive en `.agent/`,
  bus, backlog, git y closeouts.
- No crear el repo remoto ni hacer push desde el batch autonomo: requiere
  permiso humano explicito.
- No mezclar inferencia con hecho ni etiqueta sin artefacto concreto.
