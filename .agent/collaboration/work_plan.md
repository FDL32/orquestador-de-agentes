# Work Plan - WOT-2026-019r

## Metadata
- **ID:** WOT-2026-019r
- **Estado:** COMPLETED
- **deliverable_type:** documentation
- **Titulo:** Auditoria + inventario + actualizacion de prompts/skills/scripts
  segun la topologia worktree-dev (WOT-2026-019m)
- **Creado:** 2026-07-06
- **Prioridad:** Media
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Producir el archivo `docs/audit/worktree_topology_surface_inventory.md`
clasificando cada artefacto de la superficie del pipeline (24 prompts,
skills, scripts candidatos, superficie destino roles/backends) como
OK-agnostico, DESFASADO o N/A frente al modelo de topologia worktree-dev
activado por WOT-2026-019m, y actualizar UNICAMENTE los artefactos marcados
DESFASADO para que un lector nuevo pueda arrancar en la worktree-dev
siguiendo solo la documentacion.

## Contexto

WOT-2026-019m activo el modelo de ramas INVERTIDO: la worktree
`..\orquestador_de_agentes_dev` lleva `main` y es donde se EVOLUCIONA el
motor; el checkout principal `orquestador_de_agentes` queda DETACHED en
`origin/main` y es la fuente ESTABLE que consumen los destinos en runtime
via `motor_destination_link.json` (sin cambios en ese consumo). La doc
canonica del pipeline en gran parte aun asume el modelo VIEJO: cwd de
arranque = el checkout principal, `main` vive en el principal, cierre via
`git pull --ff-only`, worktree ausente.

Premisa YA VERIFICADA por el Orquestador en Fase 0 (no se re-verifica en
este plan, se hereda como hecho): `git pull --ff-only` aparece en
`QUICKSTART.md`; la seccion "0d. Motor dev worktree" de `QUICKSTART.md`
(l.140-211 aprox.) YA documenta el modelo nuevo correctamente (worktree
add, checkout `--detach origin/main` en el principal al cerrar, sin
`pull --ff-only` porque no aplica sobre un HEAD sin rama); la awareness del
modelo nuevo esta DESIGUAL entre prompts: `manager_review.md`,
`orchestrator_launch_builder.md` y `orchestrator_session_bootstrap.md` ya
mencionan la worktree; la mayoria de los 24 prompts NO la mencionan en
absoluto. Hay drift real entre lo que el motor hace hoy y lo que la mayoria
de la doc describe.

Superficie MEDIDA en vivo por este Manager desde la worktree-dev
(2026-07-06): 24 archivos en `prompts/*.md`, 36 directorios en `skills/`
(incl. `skills/_shared`), y los scripts candidatos declarados por la ficha:
`scripts/install_agent_system.py`, `scripts/destination_context.py`,
`scripts/validate_authority.py`, `scripts/update_project_map.py`,
`.agent/session_tracker.py`, `.agent/agent_controller.py`,
`scripts/setup_dev_worktree.ps1`.

## Decision Arquitectonica

Ejecutar el ticket en DOS FASES SECUENCIALES con gate F1-antes-de-F2, tal
como exige la ficha del backlog:

- **FASE 1 (auditoria + inventario, NO editar nada):** producir
  `docs/audit/worktree_topology_surface_inventory.md` clasificando CADA uno
  de los 24 prompts, cada skill (o el conjunto `skills/` si se declara
  homogeneo con justificacion explicita por subdirectorio), cada script
  candidato, y la superficie destino roles/backends (como llega
  `agents.json` al destino via `install_agent_system.py --sync`: respeta o
  pisa la config local del destino; que prompts de destino
  -`orchestrator_destination_bootstrap.md`,
  `orchestrator_destination_batch.md`- citan roles/backends; el gap de
  configuracion-de-roles-por-destino que alimenta a WOT-2026-019t) en uno
  de tres veredictos: `OK-agnostico`, `DESFASADO` (citando el marcador
  concreto: cwd=principal, main-en-principal, `pull --ff-only`, o worktree
  ausente) o `N/A`. Cada entrada DESFASADO lleva linea/seccion exacta del
  artefacto y el cambio propuesto en prosa (sin aplicarlo aun).
- **FASE 2 (actualizacion, solo lo marcado DESFASADO):** editar
  EXCLUSIVAMENTE los artefactos que Fase 1 marco `DESFASADO`, aplicando el
  cambio propuesto en el inventario, de forma coherente con
  `scripts/setup_dev_worktree.ps1` y `QUICKSTART.md` seccion "0d". Ningun
  artefacto `OK-agnostico` o `N/A` se toca en Fase 2.

Razon de la secuencia: editar sin inventariar primero arriesga (a) dejar
artefactos DESFASADO sin detectar (cobertura parcial) y (b) re-clasificar
como OK-agnostico un artefacto que en realidad cita el modelo viejo, porque la
edicion se hace a la vez que el analisis en vez de despues. El gate
F1-antes-de-F2 fuerza que el inventario completo exista y sea revisable
ANTES de que ningun archivo cambie.

## Superficie tocada (topologia verificada)

- Fase 1 SOLO crea `docs/audit/worktree_topology_surface_inventory.md`.
  No modifica ningun prompt, skill ni script.
- Fase 2 modifica UNICAMENTE los artefactos que el inventario de Fase 1
  liste con veredicto `DESFASADO`. La lista concreta de archivos a editar
  en Fase 2 NO se fija de antemano en este plan: sale directamente del
  inventario producido en Fase 1 (ver seccion de superficie potencial para
  la lista candidata completa).
- Si el inventario de Fase 1 revela una ruta o rama hardcodeada ROTA dentro
  de un script (no solo desactualizada en prosa/comentario), ese hallazgo
  se documenta como sub-ticket nuevo en `backlog.md` y NO se corrige dentro
  de este ticket (non-goal explicito).

## Plan de Implementacion

### Tipos de Tareas
| Icono | Tipo | Ejecutor |
|-------|------|----------|
| BOT | TAREA AGENTE | Builder |

### Fase 1: Auditoria e inventario de superficie (NO editar)

#### 1.1: BOT Inventariar los 24 prompts
- **Tipo:** TAREA AGENTE
- **Accion:** Crear (unico archivo nuevo de esta fase)
- **Descripcion:** Leer completos los 24 archivos de `prompts/*.md`
  (`audit_agent_output.md`, `audit_bus.md`, `audit_cf_plan_graph.md`,
  `audit_cf_repo_charter.md`, `audit_cf_ticket_contract.md`,
  `audit_complete_motor_destination.md`, `audit_git_publication.md`,
  `audit_goal_completion.md`, `audit_pipeline.md`,
  `audit_portability_legacy_surface.md`,
  `audit_post_change_system_health.md`, `audit_ticket_contract.md`,
  `contract_formation_pipeline.md`, `hermes_soul.md`, `manager_review.md`,
  `memory_upload.md`, `orchestrator_destination_batch.md`,
  `orchestrator_destination_bootstrap.md`,
  `orchestrator_launch_builder.md`, `orchestrator_pipeline.md`,
  `orchestrator_refactor_bootstrap.md`,
  `orchestrator_session_bootstrap.md`,
  `orchestrator_session_close_chat.md`,
  `orchestrator_session_close_full_audit.md`). Para cada uno, buscar
  explicitamente los 4 marcadores del modelo viejo (cwd de arranque = el
  principal, main vive en el principal, `git pull --ff-only` como paso de
  cierre, ausencia de mencion a la worktree cuando el prompt describe un
  flujo de arranque o cierre que la topologia nueva afecta) y escribir en
  `docs/audit/worktree_topology_surface_inventory.md` una fila por prompt
  con: nombre de archivo, veredicto (`OK-agnostico` / `DESFASADO` / `N/A`),
  linea o seccion exacta citada, y cambio propuesto (si DESFASADO). Ningun
  prompt puede quedar sin fila.
- **Riesgo:** BAJO (solo lectura + redaccion de un documento nuevo)
- **Criterio de Aceptacion:** El inventario contiene exactamente 24 filas
  bajo la seccion de prompts, una por cada archivo listado arriba, cada
  fila con los 4 campos (archivo, veredicto, linea/seccion, cambio
  propuesto) rellenos.

#### 1.2: BOT Inventariar skills y scripts candidatos
- **Tipo:** TAREA AGENTE
- **Archivo:** `docs/audit/worktree_topology_surface_inventory.md`
  (continuacion del mismo archivo creado en 1.1)
- **Accion:** Modificar (anadir secciones nuevas al archivo creado en 1.1;
  no se crea un segundo archivo)
- **Descripcion:** Anadir al inventario: (a) una seccion `skills/` que
  recorra los subdirectorios de `skills/` y clasifique cada uno (o declare
  explicitamente por que un subconjunto se agrupa bajo un mismo veredicto,
  citando la razon concreta por subdirectorio agrupado, nunca un veredicto
  global sin desglose); (b) una seccion de scripts candidatos que
  clasifique, con veredicto+linea+cambio propuesto, cada uno de:
  `scripts/install_agent_system.py`, `scripts/destination_context.py`,
  `scripts/validate_authority.py`, `scripts/update_project_map.py`,
  `.agent/session_tracker.py`, `.agent/agent_controller.py`,
  `scripts/setup_dev_worktree.ps1` -- para los scripts, el foco es
  documentacion/comentarios/docstrings que citen el modelo viejo, no
  refactor de logica (ver Non-goals); si aparece una ruta o rama
  hardcodeada ROTA (no solo un comentario desactualizado), documentarla
  como hallazgo aparte para sub-ticket, sin corregirla aqui.
- **Riesgo:** BAJO
- **Criterio de Aceptacion:** El inventario clasifica el 100% de los
  subdirectorios de `skills/` (con desglose o agrupacion justificada
  explicitamente) y las 7 rutas de script listadas arriba, cada una con
  veredicto+linea/seccion+cambio propuesto.

#### 1.3: BOT Inventariar la superficie destino roles/backends
- **Tipo:** TAREA AGENTE
- **Archivo:** `docs/audit/worktree_topology_surface_inventory.md`
  (continuacion)
- **Accion:** Modificar
- **Descripcion:** Anadir una seccion "Superficie destino: roles/backends"
  que documente, con evidencia literal (linea de codigo o de prompt): (a)
  como `install_agent_system.py --sync` trata `agents.json`/config de
  roles-backends del destino -- si el mecanismo de sync respeta un
  `agents.local.json` (o equivalente) ya existente en el destino o lo
  sobreescribe; citar la funcion y linea exacta que decide; (b) que
  prompts de destino citan roles/backends explicitamente
  (`orchestrator_destination_bootstrap.md`,
  `orchestrator_destination_batch.md`, y cualquier otro que aparezca en la
  busqueda de 1.1); (c) el gap de configuracion-de-roles-por-destino tal
  como lo describe la ficha WOT-2026-019r del backlog (alimenta
  WOT-2026-019t, no se resuelve aqui). Cada uno de los 3 puntos (a/b/c)
  debe tener su propio veredicto `OK-agnostico`/`DESFASADO`/`N/A` con
  linea/seccion citada.
- **Riesgo:** BAJO
- **Criterio de Aceptacion:** Los 3 puntos (a/b/c) aparecen en el
  inventario con veredicto y evidencia literal (nombre de funcion + numero
  de linea, o nombre de prompt + seccion) cada uno.

#### 1.4 (GATE F1 a F2): BOT Verificar cobertura completa del inventario
- **Tipo:** TAREA AGENTE
- **Archivo:** `docs/audit/worktree_topology_surface_inventory.md`
- **Accion:** Verificar (no crea archivo nuevo)
- **Descripcion:** Antes de iniciar cualquier tarea de Fase 2, contar
  filas/entradas del inventario y confirmar: 24 prompts clasificados, 100%
  de subdirectorios de `skills/` clasificados (agrupados o no), 7 scripts
  candidatos clasificados, 3 puntos de la superficie destino
  roles/backends clasificados. Si falta una sola entrada, completar el
  inventario antes de continuar (no se avanza a Fase 2 con inventario
  parcial). Documentar el conteo final en `execution_log.md`.
- **Riesgo:** BAJO
- **Criterio de Aceptacion:** `execution_log.md` registra el conteo
  (24/24 prompts, N/N subdirectorios de skills, 7/7 scripts, 3/3 puntos de
  superficie destino) con 0 pendientes antes de que arranque la Fase 2.

### Fase 2: Actualizar SOLO los artefactos marcados DESFASADO

#### 2.1: BOT Actualizar prompts marcados DESFASADO
- **Tipo:** TAREA AGENTE
- **Archivo:** el subconjunto de `prompts/*.md` que el inventario de Fase 1
  liste como `DESFASADO` (superficie candidata completa: los 24 prompts
  listados en 1.1; el subconjunto real a editar lo determina el inventario,
  no este plan)
- **Accion:** Modificar
- **Descripcion:** Para cada prompt marcado `DESFASADO`, aplicar
  exactamente el cambio propuesto que el inventario documento en Fase 1,
  reemplazando la referencia al modelo viejo (cwd=principal,
  main-en-principal, `pull --ff-only`, worktree ausente) por el modelo
  nuevo: arranque con cwd=`orquestador_de_agentes_dev` para evolucion del
  motor; cierre = fetch + `git checkout --detach origin/main` en el
  principal; el destino sigue consumiendo el checkout principal detached
  via `motor_destination_link.json` SIN cambios en ese mecanismo de
  consumo. Ningun prompt marcado `OK-agnostico` o `N/A` se edita. No se
  anade contenido nuevo mas alla de lo necesario para corregir la
  referencia de topologia (no se optimiza redaccion general del prompt).
- **Riesgo:** MEDIO (superficie de prompts operativos que gobiernan el
  arranque/cierre de sesiones reales)
- **Criterio de Aceptacion:** Cada prompt editado ya no contiene el
  marcador DESFASADO citado en el inventario; una relectura del prompt
  editado es coherente con `QUICKSTART.md` seccion "0d. Motor dev
  worktree" y con `scripts/setup_dev_worktree.ps1`.

#### 2.2: BOT Actualizar skills y scripts marcados DESFASADO
- **Tipo:** TAREA AGENTE
- **Archivo:** el subconjunto de skills/scripts que el inventario marque
  `DESFASADO` (superficie candidata: subdirectorios de `skills/` y los 7
  scripts listados en 1.2)
- **Accion:** Modificar
- **Descripcion:** Aplicar el cambio propuesto del inventario a cada
  skill/script marcado `DESFASADO`. Si el hallazgo es una ruta o rama
  hardcodeada ROTA en un script (no solo documentacion/comentario
  desactualizado), NO corregir la logica aqui: registrar el hallazgo en
  `execution_log.md` con archivo+linea y crear la entrada de sub-ticket en
  `backlog.md` (ver Non-goals). Solo se edita documentacion/comentarios/
  docstrings que citen el modelo viejo.
- **Riesgo:** MEDIO
- **Criterio de Aceptacion:** Cada skill/script editado ya no contiene el
  marcador DESFASADO citado en el inventario. Si se detecto una ruta/rama
  rota, existe una fila nueva en `backlog.md` describiendola (evidencia:
  diff de `backlog.md` en `execution_log.md`) y el ticket 019r NO modifica
  esa logica.
- **Si falla:** si el cambio propuesto en el inventario resulta insuficiente
  o ambiguo al aplicarlo, detener la edicion de ese artefacto especifico,
  documentar la ambiguedad en `execution_log.md` y escalar al Manager antes
  de improvisar una correccion distinta a la del inventario.

#### 2.3: BOT Verificacion de coherencia y quality gates
- **Tipo:** TAREA AGENTE
- **Archivo:** N/A (comandos) + `docs/audit/worktree_topology_surface_inventory.md`
  (posible nota de cierre)
- **Accion:** Verificar
- **Descripcion:** Ejecutar, desde
  `C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev`:
  1. `.venv\Scripts\python.exe .agent\agent_controller.py --validate --json --project-root .`
     debe dar 0 errores y 0 warnings.
  2. El guard de encoding (el mismo mecanismo que ya corre en el
     pre-commit/CI del repo para detectar caracteres no-ASCII o mojibake)
     sobre `docs/audit/worktree_topology_surface_inventory.md` y sobre
     cada archivo editado en Fase 2.1/2.2 debe dar verde.
  3. Si Fase 2 modifico algun archivo `.py`, ejecutar `ruff check .` y
     confirmar exit code 0 (no se espera tocar `.py` salvo
     docstrings/comentarios; si no se toco ningun `.py`, este paso se
     omite y se documenta esa omision explicitamente en
     `execution_log.md`).
  4. Confirmar manualmente (checklist en `execution_log.md`) que un lector
     nuevo, siguiendo solo `QUICKSTART.md` seccion "0d" mas los prompts
     actualizados, puede identificar sin ambiguedad: donde arrancar
     (cwd=`orquestador_de_agentes_dev`), como cerrar (fetch + checkout
     --detach en el principal), y que el destino no cambia su forma de
     consumo.
- **Riesgo:** BAJO
- **Criterio de Aceptacion:** `--validate --json` exit 0 con
  `errors: 0, warnings: 0`; encoding guard verde sobre el inventario y
  sobre todo archivo editado en Fase 2; si se toco algun `.py`,
  `ruff check .` exit 0; checklist de lectura-nueva documentado en
  `execution_log.md`.

## Non-goals

- No cambiar el modelo de ramas ya decidido en WOT-2026-019m (worktree-dev
  lleva `main`, principal queda detached).
- No reescribir el contenido de los prompts mas alla de la correccion de
  topologia worktree-dev (no se cambia prosa, ejemplos ni estructura salvo
  el marcador DESFASADO concreto).
- No promover ningun aprendizaje a memoria portable hasta verificar el
  flujo completo con un ticket real ejecutado desde la worktree-dev.
- No corregir rutas o ramas hardcodeadas ROTAS que aparezcan en scripts:
  si el inventario de Fase 1 encuentra una, se abre un sub-ticket nuevo en
  `backlog.md`; este ticket NO mezcla ese fix.
- No editar en Fase 2 ningun artefacto que Fase 1 haya clasificado
  `OK-agnostico` o `N/A`.
- No tocar la logica de scripts (`.py`/`.ps1`) salvo comentarios/docstrings
  que citen el modelo viejo; ninguna funcion cambia de comportamiento en
  este ticket.
- No resolver el gap de configuracion-de-roles-por-destino: este ticket
  solo lo INVENTARIA para alimentar WOT-2026-019t; la implementacion vive
  en ese ticket, fuera de scope aqui.

## Files Likely Touched

Unico archivo que Fase 1 crea:
- `docs/audit/worktree_topology_surface_inventory.md` (nuevo)

Politica de superficie para Fase 2: solo se editan los archivos que el
inventario anterior marque con veredicto DESFASADO; la lista CONCRETA sale
del inventario producido en Fase 1, no de este plan. La superficie
candidata completa de inspeccion (24 prompts, skills, scripts, backlog)
esta en la seccion siguiente, no aqui: son fuentes a leer/clasificar en
Fase 1, no entregables de Fase 1.

## Read/inspect only

Superficie de INSPECCION obligatoria en Fase 1 (clasificar cada uno con
veredicto+linea/seccion+cambio propuesto en el inventario). En Fase 2 se
edita CONDICIONALMENTE solo el subconjunto que el inventario marque
`DESFASADO` -- para los scripts, unicamente en su documentacion/
comentarios/docstrings, nunca en su logica (ver Non-goals):

- `prompts/audit_agent_output.md`
- `prompts/audit_bus.md`
- `prompts/audit_cf_plan_graph.md`
- `prompts/audit_cf_repo_charter.md`
- `prompts/audit_cf_ticket_contract.md`
- `prompts/audit_complete_motor_destination.md`
- `prompts/audit_git_publication.md`
- `prompts/audit_goal_completion.md`
- `prompts/audit_pipeline.md`
- `prompts/audit_portability_legacy_surface.md`
- `prompts/audit_post_change_system_health.md`
- `prompts/audit_ticket_contract.md`
- `prompts/contract_formation_pipeline.md`
- `prompts/hermes_soul.md`
- `prompts/manager_review.md`
- `prompts/memory_upload.md`
- `prompts/orchestrator_destination_batch.md`
- `prompts/orchestrator_destination_bootstrap.md`
- `prompts/orchestrator_launch_builder.md`
- `prompts/orchestrator_pipeline.md`
- `prompts/orchestrator_refactor_bootstrap.md`
- `prompts/orchestrator_session_bootstrap.md`
- `prompts/orchestrator_session_close_chat.md`
- `prompts/orchestrator_session_close_full_audit.md`
- `skills/` (subdirectorios, clasificados individualmente o agrupados con
  justificacion explicita por grupo)
- `backlog.md` (en el workspace, solo si Fase 1/2.2 detecta una ruta/rama
  rota que exige sub-ticket; append de una fila nueva, no edicion de
  filas existentes)
- `scripts/install_agent_system.py`
- `scripts/destination_context.py`
- `scripts/validate_authority.py`
- `scripts/update_project_map.py`
- `.agent/session_tracker.py`
- `.agent/agent_controller.py`
- `scripts/setup_dev_worktree.ps1` (referencia de coherencia para Fase 2;
  se edita SOLO si el inventario lo marca DESFASADO, y solo en comentarios)

## Trade-offs Considerados
| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Dos fases (inventario completo, luego edicion) | Cobertura garantizada antes de editar; evita re-clasificar a la ligera; auditable en Fase 1 antes de tocar nada | Mas lento que editar sobre la marcha | Elegida |
| Editar en una sola pasada (auditar y corregir a la vez) | Mas rapido | Riesgo de dejar artefactos sin clasificar o de reclasificar erroneamente bajo presion de "ya que estoy aqui"; sin gate de cobertura | Descartada |
| Corregir tambien rutas/ramas rotas encontradas en scripts | Resuelve el problema en un solo ticket | Mezcla superficie documental (bajo riesgo) con cambio de logica (riesgo mayor, requiere su propio TDD/mutation-verify); viola el non-goal explicito de la ficha | Descartada |

## Guia de Riesgos
| Nivel | Significado | Accion del Builder |
|-------|-------------|-------------------|
| Bajo | Rutinaria | Intentar 3 veces antes de escalar |
| Medio | Requiere atencion | Intentar 2 veces, escalar si dudas |
| Alto | Critica | Escalar al primer fallo |

## Calidad

- `.venv\Scripts\python.exe .agent\agent_controller.py --validate --json --project-root .`
  -> exit 0, `errors: 0, warnings: 0` (Fase 2.3).
- Guard de encoding verde sobre
  `docs/audit/worktree_topology_surface_inventory.md` y sobre cada archivo
  editado en Fase 2.1/2.2 (Fase 2.3).
- `ruff check .` -> exit 0, SOLO si Fase 2 modifico algun archivo `.py`; si
  no se toco ningun `.py`, se documenta la omision en `execution_log.md`
  (Fase 2.3).
- Gate de cobertura F1 a F2 (Fase 1.4): 24/24 prompts, N/N subdirectorios de
  skills, 7/7 scripts, 3/3 puntos de superficie destino clasificados antes
  de iniciar Fase 2.

## Criterios de Aceptacion Global

- [ ] `docs/audit/worktree_topology_surface_inventory.md` existe y clasifica
      los 24 prompts + skills + los 7 scripts candidatos + los 3 puntos de
      superficie destino roles/backends, cada uno con
      veredicto+linea/seccion+cambio propuesto; 0 artefactos sin clasificar.
- [ ] Cada artefacto marcado `DESFASADO` en el inventario queda actualizado
      y coherente con `scripts/setup_dev_worktree.ps1` y `QUICKSTART.md`
      seccion "0d"; un lector nuevo puede arrancar en la worktree-dev
      siguiendo solo la documentacion actualizada.
- [ ] Ningun artefacto marcado `OK-agnostico` o `N/A` fue editado en Fase 2.
- [ ] `--validate --json` exit 0 con `errors: 0, warnings: 0`.
- [ ] Encoding guard verde sobre el inventario y sobre todo archivo editado.
- [ ] No se toco logica de scripts salvo que el inventario probara una
      ruta/rama hardcodeada ROTA, en cuyo caso existe una fila de
      sub-ticket nueva en `backlog.md` y NO se mezclo el fix en este
      ticket.

## Handoff

### 2026-07-06 Handoff: Manager -> Builder
**Plan:** WOT-2026-019r
**Accion requerida:** Implementar segun work_plan.md (Fase 1 completa +
gate 1.4 antes de iniciar Fase 2).
**Estado:** PENDING
