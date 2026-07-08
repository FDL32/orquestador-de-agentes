# Inventario PII / Rutas locales en repos publicados

- **Ticket:** WOT-2026-020u
- **deliverable_type:** analysis
- **Fecha:** 2026-07-08
- **Scope:** Censo READ-ONLY de rutas `C:\Users\<user>\` (username en path) en HEAD + historia de 7 repos. No muta.
- **Metodologia:** `git grep -I -n -E "Users[\\/]+<user>" HEAD` (HEAD) + `git log -E -G "Users[\\/]+<user>" --all --name-only` (historia) + barrido email/secret (`[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}` en `*.py *.json *.md`).
- **Criterio de severidad:**
  - **PII baja:** username en ruta local (`C:\Users\<user>\...`). No secreto critico. Redaccion no urgente.
  - **PII ALTA:** token / email real / password / key. Escalar inmediatamente. **Ninguna encontrada en este censo** (verificado: los unicos emails son `test@example.com`, `persona@dominioprivado.es` y `noreply@github.com`, todos fixtures de test o docs).
- **Username:** `<user>` (GitHub: FDL32).

---

## Resumen ejecutivo

| # | Repo | Remote | HEAD ficheros | Historia commits | Severidad | Fix going-forward | Fix historia |
|---|------|--------|---------------|------------------|-----------|-------------------|--------------|
| 1 | Crear_Texto_LLM | github.com/FDL32/Crear_Texto_LLM | 8 | 4 | baja | redactar docs + legacy scripts | 020v (HUMAN_GATE) |
| 2 | CTL_BACKUP (bare) | local (no GitHub) | 7 | 2 | baja | N/A (backup, no publicado) | N/A |
| 3 | orquestador_de_agentes (motor/dev) | github.com/FDL32/orquestador-de-agentes | 5 (test fixtures) | ~18 | baja | N/A (test fixtures aceptables) | 020v (HUMAN_GATE, blast alto) |
| 4 | orquestador_de_agentes_workspace | github.com/FDL32/orquestador-de-agentes-workspace | 2 | 6 | baja | redactar backlog (opcional) | 020v (HUMAN_GATE) |
| 5 | Extractor_Facturas_PDF_Seguro | github.com/FDL32/Extracto_facturas_pdf | 0 (cerrado 020t) | 7 | baja | CERRADO por 020t | 020v (HUMAN_GATE) |
| 6 | lea_libreria | sin remote (no publicado) | 9 | 10 | baja | destrack context (BUG-1) | 020v solo si se publica |

**Total:** 31 ficheros en HEAD (excluyendo EXF ya cerrado), ~47 commits en historia. **0 secretos/emails reales.**

---

## 1. Crear_Texto_LLM (CTL) — PUBLICADO

- **Path:** `C:\Users\<user>\Proyectos_Python\Crear_Texto_LLM`
- **Remote:** `https://github.com/FDL32/Crear_Texto_LLM.git`

### HEAD (8 ficheros, 13 lineas)

| Fichero | Linea | Categoria | Snippet |
|---------|-------|----------|---------|
| `.agent/planning/HANDOFF_CTL-2026-008.md` | 31 | doc planning | `cwd = repo_destino (C:\Users\<user>\Proyectos_Python\Crear_Texto_LLM)` |
| `.agent/planning/contract_gaps/CG-CTL-2026-007b.md` | 26 | doc planning | ruta abs del destino `C:\Users\<user>\...` |
| `.agent/planning/ctl_chat_content_pipeline_2026-06-24/AUDIT_CTL-2026-007b.md` | 32,36,39 | doc planning | `cd C:\Users\<user>\...` (3 lineas) |
| `.agent/planning/ctl_chat_content_pipeline_2026-06-24/README.md` | 9 | doc planning | `repo_destino: C:\Users\<user>\...` |
| `docs/pipeline/next_session_notebooklm_pipeline.md` | 7,13,16,19 | doc pipeline | `C:\Users\<user>\...` (4 lineas) |
| `tools/scripts/setup_agent_system.py` | 78 | **legacy script** | `Path("C:/Users/<user>/Proyectos_Python/z_scripts/orquestacion_agentes")` |
| `tools/scripts/sync_agent_core.py` | 138 | **legacy script** | `Path("C:/Users/<user>/Proyectos_Python/z_scripts/orquestacion_agentes")` |
| `tools/scripts/sync_to_portable.py` | 31 | **legacy script** | `DEST_ROOT = Path("C:/Users/<user>/Proyectos_Python/z_scripts/orquestacion_agentes")` |

### Historia (4 commits)

| Commit | Mensaje | Ficheros |
|--------|---------|----------|
| `0a3c8ea` | docs(notebooklm): preparar scope y arranque de pipeline | docs/pipeline/next_session_notebooklm_pipeline.md |
| `abad7f5` | CTL-2026-009b: retirar exclusiones ruff legacy | tests/sandbox/audit_agent_directory.py |
| `af21d03` | CTL-2026-008: contrato de formacion versionado | .agent/planning/* (4 ficheros) |
| `e827f30` | chore: initial commit - pre-publication baseline | tests/sandbox + tools/scripts/* (4 ficheros) |

### Fix recomendado
- **Going-forward:** Los `tools/scripts/*` son scripts legacy pre-motor-portable con paths hardcodeados. Redaccion: reemplazar `C:/Users/<user>/...` por `Path.home() / "Proyectos_Python" / ...` o eliminar si ya no se usan. Los `.agent/planning/` y `docs/` son documentacion regenerable; redactar o destrackear segun criterio del destino.
- **Historia (020v):** 4 commits. `filter-repo` reemplazando `C:\Users\<user>\Proyectos_Python` -> `<PROJECTS_ROOT>`. HUMAN_GATE requerido (repo publico).

---

## 2. CTL_BACKUP (bare backup) — NO PUBLICADO a GitHub

- **Path:** `C:\Users\<user>\Proyectos_Python\Crear_Texto_LLM_BACKUP_pre-filter-repo_20260624_012226.git`
- **Remote:** `origin = C:/Users/<user>/Proyectos_Python/Crear_Texto_LLM` (path LOCAL, no GitHub)

### HEAD (7 ficheros)

| Fichero | Categoria |
|---------|-----------|
| `.agent/collaboration/AUDIT_CTL-2026-001a.md` | collaboration |
| `.agent/collaboration/PLAN_CTL-2026-001a.md` | collaboration |
| `.agent/collaboration/work_plan.md` | collaboration |
| `tests/sandbox/audit_agent_directory.py` | sandbox test |
| `tools/scripts/setup_agent_system.py` | legacy script |
| `tools/scripts/sync_agent_core.py` | legacy script |
| `tools/scripts/sync_to_portable.py` | legacy script |

### Historia (2 commits)

| Commit | Mensaje | Ficheros |
|--------|---------|----------|
| `6bf3eb4` | refactor: retire embedded legacy engine | orquestacion_agentes/* (16 ficheros legacy) |
| `337d5bc` | chore: initial commit - pre-publication baseline | .agent/collaboration + orquestacion_agentes + tools/scripts (24 ficheros) |

### Fix recomendado
- **N/A.** Es un backup bare pre-filter-repo (snapshot del 2026-06-24). Su proposito es preservar historia pre-redaccion. No esta publicado a GitHub (remote apunta a path local). Redactarlo destruiria su utilidad como backup. **No requiere 020v.** Si el backup ya no es necesario, eliminarlo; si se conserva, mantenerlo local (no push a publico).

---

## 3. orquestador_de_agentes (motor) / _dev — PUBLICADO

- **Path:** `C:\Users\<user>\Proyectos_Python\orquestador_de_agentes` (PRINCIPAL, detached) + `_dev` (worktree, main)
- **Remote:** `https://github.com/FDL32/orquestador-de-agentes.git`
- **Nota:** motor y dev son el MISMO repo git (worktrees). Misma historia. Auditado una vez.

### HEAD (5 ficheros — TODOS test fixtures)

| Fichero | Lineas | Categoria | Nota |
|---------|--------|----------|------|
| `tests/test_classify_publication.py` | 312,678,728,976,1015 | **test fixture** | Datos de test para el clasificador de publicacion (`C:\\Users\\<user>\\private\\note.txt`) |
| `tests/test_persistence_redaction.py` | 112,120,312,318 | **test fixture** | Verifica que la redaccion elimina `C:\Users\<user>` |
| `tests/test_redact.py` | 30,47 | **test fixture** | Test de logica de redaccion |
| `tests/unit/test_collect_system_health.py` | 28,29,31,33,34 | **test fixture** | Fixtures con `C:/Users/<user>/motor` |
| `tests/unit/test_project_root_resolution.py` | 252,263 | **test fixture** | Fixtures con ruta real |

**Veredicto HEAD:** ACEPTABLE. Los 5 ficheros son fixtures de test deliberados que ejercitan la logica de redaccion/resolucion de rutas. Eliminarlos romperia cobertura. **No requieren fix.**

### Historia (~18 commits) — dos categorias

**(a) Artefactos collaboration del motor (dogfooding) — paths en commits viejos, ya redactados going-forward:**

| Commit | Mensaje | Fichero |
|--------|---------|---------|
| `f1307b1` | WOT-2026-020e: limpiar artefactos contaminados | execution_log_WOT-2026-019b.md, execution_log_WOT-2026-019k.md |
| `162ed55` / `642b46c` | bootstrap 019l collaboration | execution_log.md, execution_log_WOT-2026-019k.md |
| `8c8f380` / `c471b8e` | WOT-2026-019k | execution_log.md |
| `aa156dc` / `43a43d2` | WOT-2026-019u | work_plan.md |
| `f8541f8` | WOT-2026-019r | work_plan.md |
| `d7d15db` / `9027e10` | WOT-2026-019q | work_plan.md |
| `45c1982` | WOT-2026-019m | work_plan.md |
| `6a4469c` | WOT-2026-019d | execution_log.md, execution_log_WOT-2026-019b.md |
| `b0d8d7b` | WOT-2026-019b | execution_log.md |
| `b8fd623` / `1772f90` | WOT-2026-016c (anonimizar username) | execution_log.md |

Estos commits contienen `C:\Users\<user>` en execution_log/work_plan (superficies collaboration que el motor versiona por dogfooding). Los commits posteriores (016c, 019b, 020e) redactaron going-forward, pero la HISTORIA conserva los paths.

**(b) Test fixtures (mismos de HEAD) — anadidos en commits de feature:**

| Commit | Mensaje | Fichero |
|--------|---------|---------|
| `8b2b20a` | initial commit | tests/test_redact.py |
| `1758a89` | WT-2026-248b: git publication audit | tests/test_classify_publication.py |
| `a09c1cd` | WT-2026-193: wire redaction into persistence | tests/test_persistence_redaction.py |
| `5cfecc4` | system-health-audit protocol v0 | tests/unit/test_collect_system_health.py |
| `447bbb5` | CTL-2026-007b: path-mangling guard | tests/unit/test_project_root_resolution.py |
| `7a6a419` | WOT-2026-015e: publication-gate | tests/test_classify_publication.py |

### Fix recomendado
- **HEAD:** No fix (test fixtures aceptables; collaboration surfaces limpias en HEAD actual).
- **Historia (020v):** BLAST RADIUS ALTO — es el repo del motor, publico, ~18 commits. `filter-repo` deberia EXCLUIR los test files (legitimos) y solo redactar `.agent/collaboration/execution_log*.md` y `work_plan.md`. HUMAN_GATE obligatorio. **Prioridad BAJA** (username en dogfooding logs del propio motor, no secreto).

---

## 4. orquestador_de_agentes_workspace (WS) — PUBLICADO

- **Path:** `C:\Users\<user>\Proyectos_Python\orquestador_de_agentes_workspace`
- **Remote:** `https://github.com/FDL32/orquestador-de-agentes-workspace.git`

### HEAD (2 ficheros)

| Fichero | Lineas | Categoria | Nota |
|---------|--------|----------|------|
| `.agent/collaboration/_archive/backlog_done.md` | 3268 | doc meta (archivado) | Menciona `Users\<user>` en contexto de WOT-2026-016u cerrado |
| `.agent/collaboration/backlog.md` | 30,138,139,141,142,148,152 | doc meta (backlog vivo) | Describe el propio issue 016v/020t (higiene PII) |

**Veredicto HEAD:** Documentacion meta. El backlog documenta los paths como parte de describir el issue que se esta corrigiendo. PII baja.

### Historia (6 commits)

| Commit | Mensaje | Fichero |
|--------|---------|---------|
| `d97f790` | docs(backlog): reconciliar 015p + 019b | backlog.md |
| `c9d26be` | docs(backlog): follow-ups cierre CTL-009 | backlog.md |
| `68353a2` | backlog: mover 7 tickets cerrados a done | backlog_done.md, backlog.md |
| `bef7ce3` | cerrar sesion 2026-07-03 | backlog.md |
| `40808d7` | WT-2026-250b: rotate review_queue | review_queue.md |
| `bc10ccc` | primer commit del workspace | review_queue.md |

### Fix recomendado
- **Going-forward (opcional):** Redactar `C:\Users\<user>` -> `<USERPROFILE>` o `<user>` en backlog.md. Es documentacion meta; baja prioridad.
- **Historia (020v):** 6 commits. `filter-repo` en backlog.md + review_queue.md. HUMAN_GATE. Prioridad BAJA.

---

## 5. Extractor_Facturas_PDF_Seguro (EXF) — PUBLICADO

- **Path:** `C:\Users\<user>\Proyectos_Python\Extractor_Facturas_PDF_Seguro`
- **Remote:** `https://github.com/FDL32/Extracto_facturas_pdf.git`

### HEAD (0 ficheros — CERRADO por 020t)

**Fuga viva en HEAD cerrada por WOT-2026-020t** (commit `d9ec124`): destrack de `motor_destination_link.json` + 6 ficheros de `.agent/collaboration/` + bloque managed en `.gitignore`. Verificado: `git ls-files` link+collaboration = vacio.

### Historia (7 commits)

| Commit | Mensaje | Ficheros |
|--------|---------|----------|
| `d9ec124` | WOT-2026-020t: destrack (este commit) | execution_log.md, motor_destination_link.json |
| `87dd568` | EXF-2026-010a: fallback LLM | execution_log.md |
| `f45f78a` | redact personal PII + untrack context | destination_map.md, project-map.json, run.bat, test_dropbox_paths.py |
| `d065777` | EXF-2026-003a: flatten structure | work_plan.md |
| `4409036` | EXF-2026-002a: startup guard | publica/repo/run.bat |
| `02a2c54` | EXF-2026-002a: faster startup | work_plan.md |
| `cb97f17` | migrate to portable engine v9.17.1 | motor_destination_link.json, context/*, test_dropbox_paths.py |

### Fix recomendado
- **Going-forward:** CERRADO por 020t.
- **Historia (020v):** 7 commits. `filter-repo` reemplazando `C:\Users\<user>\Proyectos_Python` -> `<PROJECTS_ROOT>`. El commit `f45f78a` ya hizo redaccion parcial going-forward pero la historia pre-`f45f78a` conserva paths. HUMAN_GATE. **Prioridad MEDIA** (repo publico, pero PII baja).

---

## 6. lea_libreria (LEA) — NO PUBLICADO

- **Path:** `C:\Users\<user>\Proyectos_Python\lea_libreria`
- **Remote:** sin remote (no publicado)

### HEAD (9 ficheros, ~35 lineas)

| Fichero | Lineas | Categoria | Nota |
|---------|--------|----------|------|
| `.agent/context/destination_map.md` | 4,5,45 | context (regenerable) | **BUG-1: tracked antes de gitignore** |
| `.agent/context/project-map.json` | 4 | context (regenerable) | **BUG-1: tracked antes de gitignore** |
| `.agent/planning/decisions.md` | 9 | planning | decision con rutas abs |
| `.agent/planning/diagnostics/LEA-2026-001a_premise_validation.md` | 130,132 | planning | diagnostico con `C:\Users\<user>` |
| `.agent/planning/evidence_catalog.md` | 5,13,21,29 | planning | catalogo con rutas abs (4 lineas) |
| `.agent/planning/ticket_contracts.md` | 18,27,28,99,175 | planning | contratos con rutas abs (5 lineas) |
| `PROJECT.md` | 11,37,39,41 | project doc | rutas abs (4 lineas) |
| `orchestrator_pipeline/launch_builder_LEA-2026-001a.md` | 6,12,15,16,17,18,42,45 | pipeline | rutas abs (8 lineas) |
| `orchestrator_pipeline/pipeline_autonomo_implantacion_LEA.md` | 6,8,14,31,34,35,36 | pipeline | rutas abs (7 lineas) |

**Hallazgo BUG-1 (context):** `.agent/context/destination_map.md` y `project-map.json` estan en `PROJECTIONS_GITIGNORE_ENTRIES` (installer), pero LEA los commiteo antes de la entrada gitignore -> quedan tracked (mismo patron que el link en 020t). El fix de 020t anadio el bloque managed al `.gitignore` de LEA (incluye estas entradas), pero gitignore NO destrackea lo ya-tracked.

### Historia (10 commits)

`53b78e0`, `a3f1d63`, `fe82aef`, `c3d8ac2`, `efcb547`, `30b623b`, `d40990b`, `9bf6691`, `536bfc3`, `70382ec` — collaboration/work_plan/context/planning/PROJECT/orchestrator_pipeline.

### Fix recomendado
- **Going-forward:** Destrack `.agent/context/destination_map.md` + `project-map.json` (`git rm --cached` — mismo patron 020t). Evaluar `.agent/planning/` y `orchestrator_pipeline/` (paths en docs; redactar o destrack segun criterio). **No urgente** (no publicado).
- **Historia (020v):** Solo si LEA se publica en el futuro. No expuesto actualmente.

---

## Verificacion de severidad (barrido secretos/emails)

Patron buscado en HEAD (`*.py *.json *.md`): `[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}`

| Repo | Emails encontrados | Tipo | Severidad |
|------|-------------------|------|-----------|
| orq_motor | `test@example.com`, `t@e.com`, `persona@dominioprivado.es`, `123+bot@users.noreply.github.com`, `cliente@example.com` | todos fixtures de test o docs | NINGUNA (no real) |
| CTL | 0 | - | NINGUNA |
| demas repos | no barridos (handoff ya verifico: solo username) | - | NINGUNA |

**Conclusion:** 0 secretos/emails reales en ningun repo. Todas las finding son username-en-ruta = PII baja.

---

## Encadenamiento con la cola

| Ticket | Accion derivada de este inventario |
|--------|-------------------------------------|
| **020t (cerrado)** | Cerro fuga viva EXF en HEAD. Confirmado: EXF HEAD = 0. |
| **020v (pendiente)** | Redaccion de historia. Prioridad por repo: EXF (7 commits, publicado, MED) > CTL (4 commits, publicado, BAJA) > orq_ws (6 commits, publicado, BAJA) > orq_motor (~18 commits, publicado, blast alto, BAJA). LEA y CTL_BACKUP: solo si se publican. HUMAN_GATE POR REPO. Excluir test files del filter-repo del motor. |
| **LEA BUG-1 (context)** | Nuevo hallazgo: `.agent/context/` tracked en LEA (mismo patron 020t). No bloquea la cola; derivar a ticket futuro o incluir en 020v si LEA se publica. |

---

## Comandos de verificacion (re-ejecutables)

```powershell
# HEAD census (por repo)
git -C <REPO> grep -I -n -E "Users[\\/]+<user>" HEAD

# Historia (por repo)
git -C <REPO> log -E -G "Users[\\/]+<user>" --all --name-only --format="COMMIT:%h|%s"

# Barrido emails (por repo)
git -C <REPO> grep -I -n -E "[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}" HEAD -- "*.py" "*.json" "*.md"

# Verificar EXF cerrado (debe ser vacio)
git -C C:\Users\<user>\Proyectos_Python\Extractor_Facturas_PDF_Seguro ls-files ".agent/collaboration/" ".agent/config/motor_destination_link.json"
```
