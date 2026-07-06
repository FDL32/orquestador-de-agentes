# Inventario de superficie: topologia worktree-dev (WOT-2026-019r Fase 1)

- Fecha: 2026-07-06
- HEAD auditado: `d7d15dbccc0d03a8cfe7d1dfb63058320f16770c`
- Ticket: WOT-2026-019r (Fase 1 -- auditoria, NO editar)
- Modo: solo lectura. Ningun prompt/skill/script fue modificado al producir
  este inventario.

## Resumen ejecutivo

Superficie clasificada: 24 prompts + 33 subdirectorios de `skills/` + 7
scripts candidatos + QUICKSTART.md + 3 puntos de superficie destino
roles/backends. 0 artefactos sin clasificar.

Conteo de veredictos:

| Superficie | OK-agnostico | DESFASADO | N/A | Total |
|---|---:|---:|---:|---:|
| Prompts (`prompts/*.md`) | 15 | 1 | 8 | 24 |
| Skills (`skills/*`) | 33 | 0 | 0 | 33 |
| Scripts candidatos | 7 | 0 | 0 | 7 |
| QUICKSTART.md (por seccion) | 1 seccion (0d, ya modelo nuevo) | 0 secciones con marcador viejo fuera de 0d | resto no aplica (no describe topologia) | ver nota |
| Superficie destino roles/backends (3 puntos) | 0 | 0 | 0 (3 puntos = GAP explicito, no aplica escala OK/DESFASADO/N/A tal cual; ver seccion dedicada) | 3 |

**Lista de artefactos DESFASADO (lo que Fase 2 editara):**

- `prompts/orchestrator_session_bootstrap.md` (l.51, l.55 y l.100; ver tabla
  de prompts para el detalle y el cambio propuesto).

Ningun otro prompt, ninguna skill, ningun script y ninguna seccion de
QUICKSTART.md (fuera de la 0d, que ya es el modelo nuevo correcto) quedo
clasificado como DESFASADO tras la busqueda exhaustiva documentada abajo.

> **Adenda Fase 2 (Review 2 fresh-context, 2026-07-06):** el barrido de Fase 1
> sobre `orchestrator_session_bootstrap.md` cito l.55 y l.100 pero OMITIO una
> tercera zona DESFASADA en el mismo archivo: la l.51 "Regla de repos: toda
> operacion git de tooling corre en `repo_motor`" que, encadenada con la l.46
> (`repo_motor` = `orquestador_de_agentes/`, el checkout principal), instruia
> correr git de tooling en el principal DETACHED -- justo lo que la topologia
> nueva prohibe. La caza Review 2 fresh-context; Fase 2 la reconcilio anadiendo
> a l.51 la aclaracion de que en dogfooding el `repo_motor` operativo es la
> worktree `orquestador_de_agentes_dev`. Leccion recurrente confirmada: el
> barrido por marcadores puede omitir una zona DENTRO del mismo archivo ya
> marcado; Review 2 fresh-context es la barrera.

## Discrepancia de conteo: skills (33 reales vs "36" citado en el plan)

El `work_plan.md` (Contexto) cita "36 directorios en `skills/` (incl.
`skills/_shared`)" como medicion en vivo del Manager. La medicion
independiente de este Builder, con dos metodos (`ls -d skills/*/` y
`Path('skills').iterdir()` en Python), da **33** subdirectorios, no 36.
Se reporta la discrepancia tal como exige el plan; no se investiga la causa
raiz de la diferencia (no es objeto de esta Fase 1) mas alla de constatar
que el conteo real y reproducible en este HEAD es 33.

Lista completa (33, orden alfabetico):

```
_shared, adopt-existing-project, audit-git-publication, audit-pipeline,
builder-implement-from-plan, builder-run-quality-gates, builder-self-audit,
builder-write-deliverable, code-audit, create-agent-skill, deep-research,
graphify, grill-work-plan, local-audit, manager-create-work-plan,
manager-resolve-escalation, manager-review-implementation,
manager-session-closeout, memory-consolidate, orchestrate-destination-batch,
orchestrate-pipeline, project-finalize, refactor-manager, repo-compare,
scaffold-python-project, secure-existing-project, session-close-full-audit,
session-close-observations, setup-agent-system, system-health-audit,
systematic-debugging, test-driven-development, version-changelog
```

Nota: `skills/README.md`, `skills/__init__.py` y `skills/validate_all.py` son
archivos sueltos en la raiz de `skills/`, no subdirectorios; no cuentan en
el conteo de subdirectorios y no son objeto de esta clasificacion (no son
"skills" individuales con SKILL.md propio).

## 1. Prompts (`prompts/*.md`) -- 24/24 clasificados

Metodologia: para cada prompt se buscaron los 4 marcadores del modelo viejo
(cwd de arranque = checkout principal sin sufijo `_dev`; `main` vive en el
checkout principal; `git pull --ff-only` como paso de cierre; ausencia total
de mencion a la worktree cuando el prompt describe arranque/cierre de sesion
del MOTOR que la topologia nueva afecta) mediante lectura completa +
`grep -n` dirigido (`cwd`, `checkout`, `worktree`, `pull --ff-only`, `main
vive`, `repo_motor\b`) sobre cada archivo.

| # | Archivo | Veredicto | Linea/seccion exacta | Cambio propuesto |
|---|---|---|---|---|
| 1 | `audit_agent_output.md` | OK-agnostico | Prompt entero: contrato generico de auditoria de output; no fija cwd/rama del motor. Menciona `repo_motor`/`repo_destino` de forma generica en la seccion "Root y topologia antes de ejecucion" (regla 4) sin asumir ubicacion fisica concreta. | -- |
| 2 | `audit_bus.md` | OK-agnostico | Prompt entero: audita el bus del `repo_destino`; no describe arranque/cierre del checkout del motor. | -- |
| 3 | `audit_cf_plan_graph.md` | N/A | Prompt entero: auditoria de Contract Formation (`plan_graph.md`); no toca topologia de checkout del motor. | -- |
| 4 | `audit_cf_repo_charter.md` | N/A | Prompt entero: auditoria de `repo_charter.md`; no toca topologia de checkout del motor. | -- |
| 5 | `audit_cf_ticket_contract.md` | N/A | Prompt entero: auditoria de ticket contracts; no toca topologia de checkout del motor. | -- |
| 6 | `audit_complete_motor_destination.md` | OK-agnostico | l.32, l.104, l.192, l.202: usa `repo_motor` de forma generica (donde sea que viva el checkout); no fija cwd=principal ni cita `pull --ff-only`/worktree. | -- |
| 7 | `audit_git_publication.md` | N/A | Prompt entero: auditoria de publicacion Git de un `repo_destino`; l.81 "Confirmar topologia: `repo_destino`, `MOTOR_ROOT`, `AGENT_PROJECT_ROOT`" es generico, no fija checkout principal del motor. | -- |
| 8 | `audit_goal_completion.md` | N/A | Prompt entero: protocolo de checker aislado de `/goal`; no menciona topologia de checkout del motor. | -- |
| 9 | `audit_pipeline.md` | N/A | l.45 "`repo_destino`: cwd del proyecto auditado" -- es el destino, no el motor; no describe arranque/cierre del motor. | -- |
| 10 | `audit_portability_legacy_surface.md` | OK-agnostico | Prompt entero: auditoria read-only de superficie legacy/portabilidad del motor; no describe flujo de arranque/cierre de sesion ni cwd/rama especifica. | -- |
| 11 | `audit_post_change_system_health.md` | OK-agnostico | l.12, l.96, l.177-178: usa `repo_motor` genericamente; l.177-178 habla del hook `guard_paths` bloqueando escrituras cross-repo "cuando el cwd es el motor" en sentido generico (cualquier checkout del motor), no fija cwd=principal ni cita pull/worktree. | -- |
| 12 | `audit_ticket_contract.md` | OK-agnostico | l.178, l.187, l.235: usa `repo_motor` genericamente (topologia `repo_motor + repo_destino`, `repo_motor/.opencode/opencode.json`); no fija checkout principal especifico ni pull --ff-only. | -- |
| 13 | `contract_formation_pipeline.md` | N/A | Prompt entero: sin coincidencias de `cwd`/`checkout`/`worktree`/`pull --ff`/`repo_motor` en grep dirigido; no toca topologia del checkout del motor. | -- |
| 14 | `hermes_soul.md` | OK-agnostico | l.45, l.51, l.55: usa `repo_motor`/`repo_destino` genericamente como par de raices a resolver; no fija ubicacion fisica ni cita pull/worktree. | -- |
| 15 | `manager_review.md` | OK-agnostico | l.25, l.37 ("Comandos base en `repo_motor`"), l.117 ("checkout parcial" es tecnica de revert de test, no del checkout del motor); ningun marcador del modelo viejo. | -- |
| 16 | `memory_upload.md` | OK-agnostico | Tabla de topologia de repos (l.35-48): `repo_motor` = "Motor portable, fuente canonica" / "Ruta local: `orquestador_de_agentes/`" -- es una tabla de vocabulario, no describe un flujo de arranque/cierre de sesion afectado por la worktree; no cita pull --ff-only ni cwd=principal como paso operativo. | -- |
| 17 | `orchestrator_destination_batch.md` | N/A | Prompt entero: orquestador de lote sobre `repo_destino`s; el motor aparece solo como herramienta read-only (l.35-39); no describe su arranque/cierre. Ver tambien seccion "Superficie destino roles/backends" mas abajo (relevante mencion (b) del plan, sin citas de roles/backends explicitas). | -- |
| 18 | `orchestrator_destination_bootstrap.md` | N/A | Prompt entero: bootstrap de sesion en un `repo_destino`; l.43 tabla de vocabulario usa `repo_motor`/`motor_root` genericamente via `motor_destination_link.json`, sin fijar checkout especifico. Ver seccion "Superficie destino roles/backends" (mencion (b) del plan: NO cita roles/backends explicitamente pese a ser candidato declarado por la ficha). | -- |
| 19 | `orchestrator_launch_builder.md` | OK-agnostico | l.137 ("worktree temporal o checkout parcial" es tecnica de verificacion de test de regresion, no arranque/cierre del motor); l.224 ("cwd=repo_destino" es del destino, no del motor); sin marcadores del modelo viejo del motor. | -- |
| 20 | `orchestrator_pipeline.md` | N/A | Prompt entero (1342 lineas); grep dirigido (`pull --ff`, `main vive`, `checkout --detach`, `worktree`, `agents.json`, `active_profile`, `backend`) sin coincidencias; l.12, l.90 usan `repo_motor` genericamente como read-only del pipeline de destino; no describe arranque/cierre del checkout del motor. | -- |
| 21 | `orchestrator_refactor_bootstrap.md` | N/A | Prompt entero: bootstrap de sesion de refactor Python generico; no menciona `repo_motor`/topologia de checkout. | -- |
| 22 | `orchestrator_session_bootstrap.md` | **DESFASADO** | **l.51 (anadida en Fase 2 tras Review 2):** "Regla de repos: toda operacion git de tooling corre en `repo_motor`" + l.46 (`repo_motor` = `orquestador_de_agentes/`, el principal) instruye correr git de tooling en el checkout principal DETACHED -> reconciliado en Fase 2 aclarando que en dogfooding el `repo_motor` operativo es la worktree `orquestador_de_agentes_dev`. **l.55:** `` - **Runtime activo:** `orquestador_de_agentes/` (`repo_motor`, portable). `` -- fija el `repo_motor` como el checkout SIN sufijo `_dev` (el checkout principal), contradiciendo el modelo nuevo donde el trabajo de evolucion del motor ocurre en `orquestador_de_agentes_dev`. **l.100:** `2. PREFLIGHT: HEAD == origin/main, arbol limpio, ...` -- asume que el arranque del orquestador compara `HEAD == origin/main` sobre el checkout de trabajo, lo cual solo tiene sentido bajo el modelo viejo (main vive en el checkout donde se trabaja y se sincroniza con `origin/main` via pull/fast-forward); bajo el modelo nuevo, el checkout de trabajo (`orquestador_de_agentes_dev`) lleva `main` y se compara igual, pero el checkout PRINCIPAL queda DETACHED en `origin/main` (no aplica "HEAD == origin/main" de la misma forma sin distinguir cual de los dos checkouts es cual). Marcadores presentes: (1) cwd de arranque = checkout principal sin sufijo, (2) ausencia total de mencion a la worktree en el flujo de arranque/PREFLIGHT del "Modo ORQUESTADOR" (paso 0, l.92-105), pese a que ese es exactamente el flujo de arranque/cierre de sesion que la topologia nueva afecta directamente. | Reemplazar l.55 para distinguir explicitamente `repo_motor` (evolucion) = `orquestador_de_agentes_dev` (worktree que lleva `main`) del checkout principal `orquestador_de_agentes` (detached, solo-consumo), citando `QUICKSTART.md` seccion "0d". Reemplazar/ampliar l.100 (PREFLIGHT) para que el paso 0 del Modo ORQUESTADOR declare: arranque con cwd=`orquestador_de_agentes_dev`; verificar que esa worktree existe y lleva `main` (o crearla con `scripts/setup_dev_worktree.ps1` si no existe); "HEAD == origin/main" se verifica en la worktree-dev, no en el checkout principal. Anadir referencia a `scripts/setup_dev_worktree.ps1` y a la seccion "0d" en el bloque de "Ciclo canonico de un ticket" o el paso 0 del orquestador. |
| 23 | `orchestrator_session_close_chat.md` | OK-agnostico | l.158 "empieza con `git status --short` y `git log --oneline -5` en `repo_motor`" -- son comandos genericos de diagnostico que funcionan igual en la worktree-dev o en el checkout principal; no fija cual de los dos checkouts es, ni cita pull --ff-only como paso de cierre del motor (el cierre que describe es el de TICKETS/SESION del `repo_destino`, no el ciclo de push/checkout del motor). | -- |
| 24 | `orchestrator_session_close_full_audit.md` | OK-agnostico | l.73 "cwd=repo_motor" para listar commits productivos de la sesion con `git log`/`git diff --stat` -- instrumental y agnostico al checkout fisico (funciona igual en principal o worktree-dev); no describe un flujo de arranque/cierre del MOTOR que la topologia afecte (describe cierre de sesion/tickets). | -- |

**Nota sobre cobertura de la busqueda:** ademas de la lectura completa de
cada prompt, se ejecutaron las siguientes busquedas globales sobre
`prompts/*.md` para confirmar negativos:

- `grep -rn "pull --ff-only" prompts/*.md` -> 0 coincidencias en ningun prompt
  (el unico lugar del repo que cita `pull --ff-only` es `QUICKSTART.md`,
  seccion 0d, y ahi es para decir explicitamente que NO se usa).
- `grep -rln "orquestador_de_agentes_dev\|worktree" prompts/*.md` -> 3
  archivos: `manager_review.md`, `orchestrator_launch_builder.md`,
  `orchestrator_session_bootstrap.md`. De los tres, solo
  `orchestrator_session_bootstrap.md` lo hace en un contexto DESFASADO (fija
  `repo_motor` = checkout principal); los otros dos usan "worktree"/"checkout"
  en sentido generico de tecnica de test o de destino, no del ciclo de
  arranque/cierre del motor.
- `grep -rln "cwd" prompts/*.md` -> 5 archivos (`audit_pipeline.md`,
  `audit_post_change_system_health.md`, `orchestrator_launch_builder.md`,
  `orchestrator_pipeline.md`, `orchestrator_session_close_full_audit.md`);
  todos revisados individualmente arriba, ninguno fija cwd=checkout-principal-
  del-motor de forma que contradiga el modelo nuevo.

## 2. Skills (`skills/*`) -- 33/33 subdirectorios clasificados

**Veredicto agrupado: los 33 subdirectorios son OK-agnostico.**

Justificacion explicita (no es un veredicto global sin desglose; es el
resultado de dos barridos deterministas sobre TODOS los subdirectorios):

1. `grep -rln "pull --ff-only\|worktree\|checkout principal\|checkout --detach" skills/`
   -> **0 coincidencias en cualquier subdirectorio de `skills/`.** Ninguna
   skill menciona la worktree, `pull --ff-only` ni un checkout-principal
   explicito.
2. `grep -rln "repo_motor\b" skills/*/SKILL.md` -> 7 skills lo mencionan
   (`audit-git-publication`, `builder-implement-from-plan`,
   `orchestrate-pipeline`, `repo-compare`, `session-close-full-audit`,
   `setup-agent-system`, `system-health-audit`); las 7 se revisaron
   individualmente (grep de linea exacta) y en las 7 el uso es generico
   ("`repo_motor` = motor portable, donde sea que viva el checkout"), sin
   fijar cwd=principal ni citar pull --ff-only. Ejemplo puntual:
   `skills/session-close-full-audit/SKILL.md:74` dice "cwd=repo_motor" para
   listar commits de la sesion con `git log`/`git diff --stat`, igual que su
   prompt hermano (`orchestrator_session_close_full_audit.md` l.73):
   instrumental, agnostico al checkout fisico.

Las 26 skills restantes (todas las de la lista de la seccion de discrepancia
arriba excepto las 7 nombradas en el punto 2: `audit-git-publication`,
`builder-implement-from-plan`, `orchestrate-pipeline`, `repo-compare`,
`session-close-full-audit`, `setup-agent-system`, `system-health-audit`) no
mencionan `repo_motor` en absoluto, por lo que no son candidatas a DESFASADO
por definicion (los 4 marcadores
del modelo viejo requieren, como minimo, alguna referencia al checkout del
motor).

Conclusion: 33/33 OK-agnostico, agrupados por evidencia de grep global
(marcadores 1 y 2), con desglose individual de las 7 excepciones que
mencionan `repo_motor`.

## 3. Scripts candidatos -- 7/7 clasificados

| Script | Veredicto | Linea/seccion exacta | Cambio propuesto |
|---|---|---|---|
| `scripts/install_agent_system.py` | OK-agnostico | `grep -n "pull --ff-only\|checkout principal\|worktree\|cwd.*motor\|main vive"` -> 0 coincidencias en 1533 lineas. No asume ruta/rama del checkout que rompa bajo la worktree nueva. | -- |
| `scripts/destination_context.py` | OK-agnostico | `grep -n` de los mismos marcadores -> 0 coincidencias en 700 lineas. | -- |
| `scripts/validate_authority.py` | OK-agnostico | `grep -n` de los mismos marcadores -> 0 coincidencias en 135 lineas. | -- |
| `scripts/update_project_map.py` | OK-agnostico | `grep -n` de los mismos marcadores -> 0 coincidencias en 358 lineas. | -- |
| `.agent/session_tracker.py` | OK-agnostico | `grep -n` de los mismos marcadores -> 0 coincidencias en 212 lineas. | -- |
| `.agent/agent_controller.py` | OK-agnostico | `grep -n "pull --ff-only\|checkout principal\|worktree\|main vive"` -> 0 coincidencias en 6458 lineas. | -- |
| `scripts/setup_dev_worktree.ps1` | OK-agnostico (es el script CANONICO del modelo nuevo) | Todo el script (245 lineas) implementa exactamente el procedimiento de `QUICKSTART.md` seccion "0d": detach del principal antes de `worktree add`, `main` en la worktree-dev, fail-closed si el principal tiene cambios sin commitear (l.122-131, l.138-145), `-Remove` re-ata `main` al principal (l.209-235). Es la fuente de verdad del modelo nuevo, no un artefacto a corregir. | -- |

**Hallazgo de ruta/rama hardcodeada rota:** ninguno. Los 7 scripts fueron
revisados con grep dirigido a los 4 marcadores del modelo viejo y ninguno
presenta una ruta o rama hardcodeada que rompa bajo la topologia nueva (ni
siquiera en comentarios/docstrings). No se abre sub-ticket para esta
categoria en esta Fase 1.

## 4. QUICKSTART.md

QUICKSTART.md es el unico documento donde el modelo nuevo YA esta descrito
correctamente (seccion "0d. Motor dev worktree", l.140-235), y donde se
verifico exhaustivamente si OTRAS secciones seguian citando el modelo viejo.

| Seccion | Rango de lineas | Veredicto | Evidencia | Cambio propuesto |
|---|---|---|---|---|
| Cabecera / "Motor vs Workspace" | l.1-44 | OK-agnostico | Describe la separacion motor-codigo vs workspace-`.agent/` de forma generica; no fija cwd/rama del checkout del motor. | -- |
| "0. Reproducible launcher" | l.46-103 | OK-agnostico | Describe el launcher de terminales del `repo_destino`/ticket; no cita pull --ff-only ni checkout-principal del motor. | -- |
| "0b. Role-to-backend mapping" | l.105-119 | OK-agnostico | Tabla backend/rol; no topologia de checkout. | -- |
| "0c. Startup Templates" | l.121-138 | OK-agnostico | Historial de WP-2026-0xx y arranque del supervisor; no cita pull --ff-only ni checkout-principal. | -- |
| **"0d. Motor dev worktree"** | **l.140-235** | **OK-agnostico (ya es el modelo nuevo, fuente canonica)** | Detach-antes-de-worktree-add (l.161-170), cierre con `git fetch` + `git checkout --detach origin/main` (l.192-199) citando explicitamente "(no `git pull --ff-only`: no aplica sobre un HEAD sin rama)" (l.201), desmontaje (l.204-218), referencia a `scripts/setup_dev_worktree.ps1` (l.232-235). Esta seccion es la REFERENCIA que Fase 2 usara para corregir los artefactos DESFASADO, no un artefacto a corregir. | -- |
| "1. Preflight" | l.237-243 | OK-agnostico | `--validate --json --force` generico, sin fijar checkout. | -- |
| "2. Terminal-driven startup" | l.245-311 | OK-agnostico | Arranque de terminales del ciclo de ticket (destino); no describe arranque/cierre del checkout del motor. | -- |
| "3"-"5" (terminales, flujo builder, reconciliacion) | l.312-381 | OK-agnostico | Mismo alcance que la seccion anterior (ciclo de ticket/destino). | -- |
| "6. Comandos diarios" | l.382-451 | OK-agnostico | `git status --short`/gates diarios genericos; no fija checkout del motor. | -- |
| "7. Multi-Ticket Integration Smoke" | l.452-465 | OK-agnostico | Smoke test generico. | -- |
| "8. Cierre de sesion" | l.467-526 | OK-agnostico | `git status --short` (l.508) generico; el "criterio de sesion cerrada" es sobre el ciclo de TICKETS del `repo_destino`, no el ciclo push/checkout del motor. No cita `pull --ff-only` como paso de cierre del motor en ningun punto de esta seccion. | -- |

**Conclusion QUICKSTART.md:** tras `grep -n "checkout principal\|main vive
en\|cwd.*principal"` sobre el archivo completo, las 10 coincidencias caen
TODAS dentro del rango l.140-230 (seccion 0d), y las 3 apariciones de
`pull --ff-only` (l.201 mas dos menciones en el resumen ejecutivo de este
mismo inventario) tambien estan dentro de esa seccion, usada para decir
explicitamente que el modelo nuevo NO lo usa. No se encontro ninguna otra
seccion de QUICKSTART.md que cite el modelo viejo del checkout del motor.
**QUICKSTART.md queda clasificado en su totalidad como OK-agnostico/ya
corregido: no hay ninguna seccion DESFASADA que Fase 2 deba tocar.**

## 5. Superficie destino: roles/backends (alimenta WOT-2026-019t)

Los 3 puntos exigidos por el plan, cada uno con evidencia literal.

### (a) Mecanismo de sync de `install_agent_system.py --sync` sobre `agents.json`/config de roles del destino

**Veredicto: DESFASADO/GAP respecto a lo que WOT-2026-019t necesitara (no es
un DESFASADO de topologia worktree; es un gap de config-por-destino).**

Evidencia literal (`scripts/install_agent_system.py`):

- `LOCAL_DIRS = {"collaboration", "runtime", "audits"}` (l.46): estos 3
  directorios NUNCA se sincronizan desde el motor. **`config/` NO esta en
  `LOCAL_DIRS`.**
- `INSTALLER_MANAGED_PATHS: frozenset[str] = frozenset({"glossary.md",
  "microagents"})` (l.52): depositados una vez, luego propiedad del destino;
  `--sync` no los pisa ni los poda. `agents.json` NO esta en este set.
- `INSTALLER_BOOTSTRAP_PATHS: frozenset[str] = frozenset({"config/
  destination_context.json", "context/destination_map.md"})` (l.60-68):
  sobreviven la deteccion de residuos durante sync (match de ruta completa).
  `agents.json` NO esta en este set.
- `MANIFEST.workspace` l.68 lista explicitamente `.agent/config/agents.json`
  en la allowlist de `copy_tree` -- es decir, **`agents.json` SI se copia/
  sobrescribe en cada `--install`/`--sync`** (via `copy_tree(template_agent,
  project_agent, ..., allowlist=allowlist)`, invocado en
  `install_agent_system.py:1201-1202` para install y `:1315-1316` para sync).
- `flip_profile_in_destination()` (definida en l.611-638; invocada en
  l.1204 tras `--install` y en l.1318 tras `--sync`): tras la copia
  completa del arbol, esta funcion abre `config/agents.json` en el destino
  y, SOLO SI `active_profile == "engine-dev"`, lo flipa a
  `"host-project"`. Es decir: el motor primero SOBRESCRIBE `agents.json`
  completo via `copy_tree`, y despues aplica un parche puntual de un solo
  campo (`active_profile`). Ningun otro campo de `agents.json` (mapeo
  backend por rol, modelos, etc.) se preserva de una version local del
  destino: la copia de `copy_tree` ya lo sobreescribio antes del flip.

Conclusion (a): el sync actual SOBRESCRIBE `agents.json` en cada
install/sync (no lo preserva como config local del destino); solo el campo
`active_profile` recibe tratamiento especial post-copia, y unicamente para
forzarlo a `"host-project"`, no para preservar una eleccion del destino.

### (b) Prompts de destino que citan roles/backends explicitamente

**Veredicto: N/A / gap de cobertura -- ninguno de los prompts de destino
candidatos cita roles/backends explicitamente**, pese a que la ficha los
declara como candidatos naturales.

Evidencia: `grep -n "agents\.json\|active_profile\|backend\|role"` sobre
`prompts/orchestrator_destination_bootstrap.md` y
`prompts/orchestrator_destination_batch.md` -> **0 coincidencias en
ambos.** Ninguno de los dos prompts menciona `agents.json`, `active_profile`,
ni un mapeo de rol->backend por destino. La busqueda de 1.1 tampoco
encontro un tercer prompt de destino que lo haga (`orchestrator_pipeline.md`
tampoco cita `agents.json`/`active_profile`/`backend` -- 0 coincidencias
verificado en la seccion de prompts).

Contraste: el mapeo de roles/backends esta documentado en el propio motor
(`QUICKSTART.md` seccion "0b. Role-to-backend mapping", l.105-119) y en
`prompts/orchestrator_session_bootstrap.md` (tabla "Config de agentes:
`.agent/config/agents.json` mapea backend->ejecutable", l.61), pero NINGUNO
de esos dos es un prompt de DESTINO: describen el mapeo del propio motor/
dogfooding, no dan instrucciones al agente que arranca en un `repo_destino`
sobre como declarar o preservar su propio mapeo de roles/backends.

Conclusion (b): existe un gap de cobertura documental -- los prompts de
destino candidatos no dan al agente ninguna instruccion sobre roles/
backends del destino, ni advierten que el proximo `--sync` puede
sobrescribir su `agents.json`.

### (c) Gap de configuracion-de-roles-por-destino (alimenta WOT-2026-019t, no se resuelve aqui)

**Veredicto: GAP explicito documentado, no se resuelve en este ticket.**

Sintesis del gap concreto (evidencia de (a) + (b) arriba): un futuro
`.agent/config/agents.local.json` (o mecanismo equivalente que WOT-2026-019t
disene para permitir que cada destino declare su propio mapeo rol->backend
sin que el motor lo pise) **NO seria preservado por el `--sync` actual**:

1. `config/` no esta en `LOCAL_DIRS` (l.46) -> no se excluye del sync.
2. Un archivo nuevo como `agents.local.json` no estaria en
   `INSTALLER_MANAGED_PATHS` (l.52) ni en `INSTALLER_BOOTSTRAP_PATHS`
   (l.60-68) salvo que WOT-2026-019t lo añada explicitamente a alguno de
   esos sets (o a un nuevo `LOCAL_FILES`, actualmente inexistente).
3. Si WOT-2026-019t versiona `agents.local.json` en el destino sin extender
   esas allowlists, el proximo `install --sync` lo trataria como no-
   allowlisted: `detect_destination_residues()` (invocada en
   `install_agent_system.py` antes de `copy_tree` en el flujo `--sync`,
   l.1307) lo marcaria como residuo potencial, y el proceso de copia no
   tiene ningun mecanismo que lo preserve por defecto.

**Requisito duro para WOT-2026-019t (no implementado aqui):** extender
`INSTALLER_MANAGED_PATHS` (o crear un nuevo `LOCAL_FILES`/equivalente) para
incluir el archivo de config de roles-por-destino que ese ticket introduzca,
y actualizar los prompts de destino ((b) arriba) para que documenten su
existencia y su contrato de preservacion frente a `--sync`.

## Hallazgos para sub-ticket

Ninguno. Los 7 scripts candidatos fueron revisados explicitamente en busca
de rutas o ramas hardcodeadas ROTAS (no solo comentarios desactualizados) y
no se encontro ninguna. El unico gap real detectado (superficie destino
roles/backends, seccion 5) ya tiene ticket de destino declarado
(WOT-2026-019t) segun el propio `work_plan.md` de este ticket; no requiere
un sub-ticket nuevo en `backlog.md`.

## Superficie destino -> 019t

Gap concreto (repetido aqui de forma compacta para trazabilidad directa de
Fase 2/019t): el `--sync` de `install_agent_system.py` sobrescribe
`config/agents.json` completo en cada instalacion/sincronizacion (via la
allowlist de `MANIFEST.workspace` l.68 + `copy_tree`), preservando
selectivamente solo el campo `active_profile` mediante
`flip_profile_in_destination()` (l.611-638, invocada en l.1204 y l.1318).
Ningun prompt de destino (`orchestrator_destination_bootstrap.md`,
`orchestrator_destination_batch.md`, `orchestrator_pipeline.md`) menciona
roles/backends ni advierte de este comportamiento de sobrescritura. Un
futuro `agents.local.json` de WOT-2026-019t necesitara extender
`INSTALLER_MANAGED_PATHS` (o un nuevo `LOCAL_FILES`) para sobrevivir al
sync, y los prompts de destino necesitaran una seccion nueva que lo
documente. Este ticket (019r) NO implementa ese mecanismo; solo lo deja
inventariado con evidencia literal para que 019t lo consuma directamente.
