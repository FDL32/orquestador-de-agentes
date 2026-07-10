# Plan de Trabajo: backlog_reconcile.py (recolector de senales de Fase 0)

## Metadata
- **ID:** WOT-2026-021i
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-10
- **delivery_authority:** repo_motor
- **Prioridad:** BAJA
- **Asignado a:** Builder

## Objetivo
Crear `scripts/backlog_reconcile.py`: un RECOLECTOR read-only de senales de git que
automatiza la **Fase 0 (Reconciliacion)** de `/backlog-triage` (prompt
`prompts/backlog_triage.md`, l.63-88; el script se nombra como follow-up 021i en l.74).
Por cada ticket vivo del backlog emite senales git con evidencia y NO EMITE VEREDICTO:
el AGENTE juzga LIKELY_DONE/LIKELY_PENDING/NEEDS_HUMAN_VERIFY. Patron =
`collect_system_health.py` (recolector testigo: "Collector output is [RELATO]; the agent
produces the verdict").

## Contexto
Follow-up de WOT-2026-021h (`a641117`, capacidad `/backlog-triage`; dependencia CERRADA).
Hasta hoy la Fase 0 se hace a mano (prompt l.73-76). El consumidor (prompt + skill
`skills/backlog-triage/`) ya esta desplegado. `backlog_reconcile.py` NO existe (verificado
`find` + `git log --grep` vacio). Superficie mapeada por workflow de 4 exploradores +
verificacion manual.

## Configuracion Privada Requerida
Ninguna.

## BLOCKERS del plan-audit adversarial (CONFIRMADOS in-vivo) -> plan REVISADO

### BLOCKER 1: las senales git deben correr contra el repo CORRECTO por SCOPE
La v1 del plan hardcodeaba todas las senales contra el WORKSPACE. ERROR confirmado
in-vivo: el reconcile set de HOY tiene 19 tickets, ~12 con scope `motor/*` cuyo codigo
vive en el MOTOR, no en el workspace. Prueba: 020i (`motor/skip-gates-not-forwarded`,
evidencia agent_controller.py:6022) -> `git ls-files scripts/run_pytest_safe.py` es VACIO
en el workspace y TRACKED en el motor `_dev`. Grepear solo el workspace daria
`tracked=false/hits~0` para los 12 motor-tickets cuyo codigo SI existe -> senal falsa
masiva (false LIKELY_PENDING). La barrera "no ascender al motor" (familia flaky 021k) es
correcta para HERMETICIDAD de sandbox pero ERRONEA para recoleccion de senales: aqui
queremos el repo del ticket. Fix: ENRUTAR por prefijo de scope.

### BLOCKER 2: `last-run.json` es per-REPO, no per-ticket
Confirmado in-vivo: cada repo tiene UN solo `.agent/runtime/pytest-safe/last-run.json`
SIN campo `ticket`. Copiar el mismo estado de suite a los 19 records por-ticket es
enganoso. Ademas `stale` exige el eje `delivery_authority` (BLOCKER de 021c/021n: leer el
repo/HEAD equivocado da false-green/false-stale). Fix: emitir `last_run` a nivel de REPO
(uno por motor, uno por destino), NO copiado por ticket.

## Justificacion del conjunto de senales (evidencia historica)
Cada reconciliacion "ya-hecho" real uso una senal distinta, PERO todas caen en familias
genericas (backlog_done.md): 019e (git log --grep + git ls-files), 020j (git ls-files 243
+ git status), 020m (git ls-files 3 paths + git grep consumidores=0), 020s (git ls-files
.example). => NO es viable un check-DoD-generico (sistema experto); SI es viable emitir
senales genericas y que el agente juzgue.

## Alcance EXACTO (REVISADO tras plan-audit)

### CREAR (`scripts/backlog_reconcile.py`) - espeja collect_system_health.py
- **CLI** (espejo `collect_system_health.py:218-248`): `main(argv=None) -> int` via
  `sys.exit(main())`. Args: `--motor-root` REQUIRED (marker `MANIFEST.distribute`; root
  malo -> exit 2); `--project-root` opcional (default None; el workspace/destino);
  `--out` opcional (`_unique_out_dir` inmutable). Docstring: strictly read-only.
- **Helpers espejo** (copiar el patron, NO importar de collect): `_run` (read-only, nunca
  raise, timeout, encoding utf-8/replace, dict `{cmd,exit_code,stdout,stderr,ok}`);
  `_git_head`; `_relativize(text, roots)` con `roots={MOTOR_ROOT, DESTINO_ROOT}`;
  `_unique_out_dir`.
- **Resolucion de topologia (NO hardcodear)**: si `--project-root` ausente, leer
  `<workspace>/.agent/config/motor_destination_link.json` -> `destination_root` -> backlog
  en `<destination_root>/.agent/collaboration/backlog.md` (prompt l.30-38). Link
  gitignored/machine-specific -> resolver runtime; ausente -> degradar (warning + exit 3),
  NO petar.
- **Parser del backlog** (reutilizar la LOGICA de `check_backlog_contract.py`, sin
  duplicar sus checks): leer `encoding='utf-8-sig'`; localizar `## Vista rapida`; header
  `| Prioridad`; saltar separador; filas hasta blank o `## `. Split
  `cells=[c.strip() for c in row.strip().strip('|').split('|')]`, len==8. Indices:
  `ticket=cells[1]`, `titulo=cells[2]`, `scope=cells[3]`, `status=cells[4]`. Reconcile set
  = `status in {pending, deferred, completed-partial}` (prompt l.65; NO solo pending).
  Enumerar SOLO de la TABLA, nunca de `### ` fichas.
- **ENRUTADO POR SCOPE (BLOCKER 1)**: por cada ticket, resolver el repo de sus senales por
  el prefijo de `scope`:
  - `motor/*` -> `git -C <motor-root>` (el codigo del motor).
  - `destinos/*` (o destino generico) -> `git -C <workspace/destino>`.
  - `system/*`, `infra/*` (016v es infra local, no-git) -> repo INDETERMINADO: emitir
    `repo: "n/a"` + warning, senales de archivo/grep OMITIDAS (no forzar un grep del
    workspace). El agente juzga con eso.
  Emitir el `repo` elegido ("motor"|"destino"|"n/a") en cada record como EVIDENCIA (no es
  veredicto; es de-donde-se-miro).
- **Senales por ticket** (RAW, sin veredicto), corridas contra el repo enrutado:
  1. `git log --all --fixed-strings --grep <ID>` (commits que mencionan el ticket; ID
     COMPLETO con prefijo; `--all` por el detached HEAD del principal -confirmado in-vivo:
     sin --all la ancestry del detached no ve main-; `-F`/fixed-strings por robustez aunque
     los IDs no tengan metachars). Emite `[{sha,subject,date}]` (lista vacia si 0).
  2. `git ls-files <path>` + `git status --short <path>` (presencia/tracking de archivos
     del scope; emitir AS WRITTEN -leccion 020s-, no adivinar). `[{path,tracked,present,status}]`.
  3. `git grep -n -i <term>` (terminos del DoD; **`-i` OBLIGATORIO** -leccion 021d-; hits
     RAW, presencia Y ausencia). `[{term,hits,lines}]`.
- **Senal de repo (BLOCKER 2)**: `last_run` a nivel de REPO, NO por ticket. Bloque
  top-level `repos_last_run: {motor: {...}, destino: {...}}` leyendo el
  `last-run.json` de cada repo (exit_code + tested_sha + stale RAW; stale por comparacion
  con el HEAD DE ESE repo -no cross-repo-). El agente cruza el `repo` del ticket con este
  bloque. NO se copia por ticket.
- **Extraccion de terminos por ticket** (el cell es OPACO -split solo la FILA por `|`-):
  (a) `cells[1]` verbatim -> `git log --grep`; (b) tokenizar `scope` por `/` y `-`;
  (c) regex-cosechar filepaths/file:line del `titulo` (`[\w./-]+\.py(?::\d+(?:-\d+)?)?` +
  backticks) Y de la ficha `### <ID>` si existe. No toda ficha existe -> titulo garantizado;
  titulo-only sin petar; regex ANCLADA (sin catastrophic backtracking, verificado in-vivo
  1.8s sobre 30K no-match).
- **Salida** (espejo `collect_system_health.py:425-448`): `SCHEMA_VERSION =
  "backlog-reconcile-collector/v0"`; findings dict con `schema`, `generated_at`
  (`datetime.now(timezone.utc).isoformat()`), `tickets` (records por ticket),
  `repos_last_run` (bloque per-repo), `automatic_warnings`, `automatic_criticals` (SOLO
  fallos de RECOLECCION del propio script -backlog ilegible, git ausente-, NUNCA
  ticket-level), y la nota fija `"Collector output is [RELATO]; the agent produces the
  verdict."`. Record por ticket (SOLO senales, CERO campos de juicio):
  `{ticket_id, status, scope_slug, repo, grep_commits:[...], scope_paths:[...],
    dod_terms:[...]}`. Escribir `raw/` con `.gitignore` (`raw/\n`) para volcados git
  crudos (PII); findings.json RELATIVIZADO. Exit: 0 ok / 1 self-failure de recoleccion /
  2 error de args / 3 topologia degradada.

### CONSERVAR / NO TOCAR
- `check_backlog_contract.py` (gate sintactico; 021i es el recolector semantico, disjunto).
- `collect_system_health.py` (patron, no se importa ni se modifica).
- El prompt `backlog_triage.md` y la skill (ya desplegados).

## Definition of Done (DoD)
- (a) `main([--motor-root fake, --project-root fake_ws, --out tmp])` -> 0 en workspace
  limpio; findings JSON con `schema`, `generated_at`, `tickets`, `repos_last_run`,
  `automatic_warnings`, `automatic_criticals` + la nota exacta.
- (b) PARSE: fixture con estados mezclados -> `tickets[]` = exactamente las filas con
  `status in {pending,deferred,completed-partial}`; excluye blocked/terminal y IDs
  solo-ficha. `ticket_id` = ID COMPLETO de `cells[1]`.
- (c) ENRUTADO (BLOCKER 1): fixture con un ticket `motor/*` y otro `destinos/*` -> el
  `motor/*` corre sus senales contra motor-root (record `repo=="motor"`), el `destinos/*`
  contra el destino (`repo=="destino"`); un `infra/*`/`system/*` -> `repo=="n/a"` +
  warning, sin grep forzado. Mutation: enrutar todo al workspace -> el test del
  motor-ticket falla (senales vacias).
- (d) SENALES: cada record tiene grep_commits/scope_paths/dod_terms RAW; **NINGUNA clave
  de veredicto/clasificacion/evidence_label en toda la salida** (assert de AUSENCIA en el
  JSON completo).
- (e) last_run PER-REPO (BLOCKER 2): `repos_last_run` tiene bloques motor/destino con
  exit_code+tested_sha+stale; NINGUN record de ticket lleva `last_run`.
- (f) GREP `-i`: fixture con termino que difiere solo en mayuscula -> `dod_terms[]` con
  hits > 0.
- (g) RELATIVIZACION: ni `C:/Users/fdl` ni `C:\Users\fdl` sobrevive en el JSON escrito.
- (h) EXIT: root malo -> 2; link no resoluble con run completo -> 3; self-failure de
  recoleccion (p.ej. backlog ilegible) -> 1.
- (i) READ-ONLY: tras un run, backlog.md y ambos arboles byte-identicos.
- (j) TOPOLOGIA: con solo el link (sin --project-root) resuelve destination_root; link
  ausente -> degrada (exit 3/warning) sin petar.
- (k) `git log` usa `--all` (barrera del detached HEAD; test que verifica el flag en el cmd).
- (l) Tests espejo `test_collect_system_health.py` (importlib, monkeypatch `_run` con
  `_fake_run_factory` por comando incl. routing por cwd, `_fake_workspace(tmp_path)`, NO
  git real) + mutation-verify (quitar `-i` -> falla f; meter un campo de veredicto -> falla
  d; enrutar todo al workspace -> falla c; romper relativize -> falla g).
- (m) py_compile + ruff + ASCII (encoding-guard scope `scripts/**/*.py`).
- (n) Suite `run_pytest_safe --level all` -> "N passed / 0 failed"; tested_sha==HEAD.

## Riesgos y barreras (para el plan-audit)
- (BLOCKER 1) Enrutar senales por scope; motor-scoped al motor. Barrera: DoD-c + mutation.
- (BLOCKER 2) last_run per-repo, no per-ticket; stale sin cross-repo. Barrera: DoD-e.
- Detached HEAD -> `git log --all`. Barrera: DoD-k.
- Frontera "collector, not judge": CERO campos de veredicto. Barrera: DoD-d (ausencia).
- PII: todo string por `_relativize`; volcados crudos a `raw/` gitignored. Barrera: DoD-g.
- Extractor: cell opaco (split solo la fila); regex anclada; titulo-only sin petar.
- exit 1 = SOLO self-failure de recoleccion (nunca ticket-level "critical"). Documentado
  en el docstring.
- `_run` con guard `not in (0, None)` (herramienta ausente NO es pass silencioso).
- NO agrupar con 021k (otra familia). Cierre 021i SOLO.
