# Execution Log: WOT-2026-021i

**Estado:** COMPLETED

## Bitacora

### 2026-07-10 - Manager - Plan aprobado
- work_plan.md APPROVED (code, delivery_authority repo_motor). STRATEGY + AUDIT (TP).
- Premisa CONFIRMADA in-vivo 2026-07-10: `scripts/backlog_reconcile.py` NO existe (find +
  `git log --all --grep` vacio); dependencia 021h CERRADA (`a641117`, capacidad
  /backlog-triage); el consumidor (prompt backlog_triage.md Fase 0 + skill backlog-triage)
  ya esta desplegado. El script se nombra como follow-up 021i en el prompt (l.74-76).
- SUPERFICIE MAPEADA por workflow de 4 exploradores paralelos (prompt-contract /
  collector-pattern / backlog-format / reconcile-evidence) + verificacion manual del
  orquestador: parser `## Vista rapida` (utf-8-sig, 8 col, ticket=cells[1]/scope=cells[3]/
  status=cells[4]); reutilizar la logica de check_backlog_contract (no duplicar el gate);
  senales justificadas por evidencia historica (019e/020j/020m/020s cada uno uso una senal
  distinta pero todas caen en git log --grep / git ls-files / git grep -i / last-run.json);
  patron = collect_system_health; topologia por motor_destination_link.json.

### 2026-07-10 - Plan-audit adversarial - 2 BLOCKER (CONFIRMADOS in-vivo) + concerns
- BLOCKER 1: las senales git deben correr contra el repo CORRECTO por scope. El reconcile
  set de hoy tiene 19 tickets, ~12 con scope `motor/*` cuyo codigo vive en el MOTOR.
  CONFIRMADO: 020i (motor/skip-gates) -> `git ls-files scripts/run_pytest_safe.py` VACIO en
  workspace, TRACKED en motor. Grepear solo el workspace = false-PENDING masivo. Fix:
  enrutar por prefijo de scope (motor/* -> motor; destinos/* -> destino; system/infra ->
  n/a sin grep forzado). El plan v1 heredaba la barrera anti-021k (no ascender al motor)
  que es correcta para HERMETICIDAD pero ERRONEA para recoleccion de senales.
- BLOCKER 2: `last-run.json` es per-REPO (sin campo ticket) -> emitir `repos_last_run`
  {motor,destino} a nivel top-level, NO copiado por ticket. stale por el HEAD de ESE repo
  (no cross-repo; eje de 021c/021n).
- Concerns incorporados: `git log --all` (detached HEAD del principal -confirmado: sin
  --all la ancestry no ve el commit-); `--fixed-strings`; exit 1 = SOLO self-failure de
  recoleccion, nunca ticket-level. Plan REVISADO.
- Distribucion de scopes verificada: motor/* ~12, destinos/* 5, system/* 1, infra/* 1.

### 2026-07-10 - Implementacion (orquestador directo) + gates
- Creado `scripts/backlog_reconcile.py` (espejo de collect_system_health: CLI, _run,
  _relativize, _unique_out_dir, findings JSON + nota [RELATO]). Enrutado por scope
  (_scope_repo), 3 senales por ticket (log --all -F --grep / ls-files+status / grep -n -i),
  repos_last_run per-repo, extraccion de terminos con regex anclada. main C901 resuelto
  extrayendo `_collect_all` (no noqa).
- PRUEBA FUNCIONAL EN VIVO (el caso real): run contra el backlog vivo -> 19 tickets, 2
  warnings (system/infra -> n/a), exit 0. Cazo 1 fallo REAL que el diseno teorico no
  anticipo: las LINEAS de git grep traian `C:/Users` de ficheros de TERCEROS (PII que
  _relativize NO cubre porque no es la raiz del repo). FIX: el findings solo lleva `hits`;
  las lineas van a `raw/grep_hits.txt` (gitignored). Verificado: 0 PII en findings.json.
- 18 tests (parser, routing, 3 senales, repos_last_run per-repo, no-verdict, PII, exit
  codes, read-only, topologia via link). MUTATION-VERIFY x4 (todas restauradas
  md5-identico): romper routing -> falla test motor; quitar -i -> falla test grep;
  inyectar campo de veredicto -> falla test no-verdict; filtrar lines al findings -> falla
  test PII. Barreras con dientes.
- Gates: py_compile + ruff + ASCII limpios (ambos ficheros). Modulo 18 passed / 0 failed.
- Suite `run_pytest_safe --level all`: 3661 passed / 47 skipped / **6 failed**. Los 6
  fallos (test_review_bridge.py + test_manager_review_bridge.py) son PRE-EXISTENTES de
  WOT-2026-020r (evidence-gate NO hermetico: lee el estado git VIVO del arbol; con mis 5
  ficheros sin commitear el gate rechaza el fixture WP-2026-072 "all changes are
  collaboration-only"). VERIFICADO: (1) los 6 NO importan backlog_reconcile (grep vacio);
  (2) con el arbol LIMPIO (stash) los 6 PASAN; (3) stderr = "[evidence-gate] REJECTED".
  NO es regresion de 021i. La regla de cierre duro (re-suite tras commit, arbol limpio)
  los devuelve a verde. NOTA propia: use `git stash -u` para probar la tesis y lo recupere
  con `stash pop` sin conflicto -innecesario, la tesis ya estaba probada por (1)+(3)-.

### 2026-07-10 - Review 2 fresh-context - APPROVE-WITH-NITS -> nits resueltos
- Review 2 (fresh-context, muta produccion): APPROVE. 4 barreras mutation-proven
  (routing / -i / no-verdict / PII), todas restauradas md5-identico; run funcional sano
  (19 tickets, motor-scoped repo=motor, 0 PII en findings); modulo verde.
- 2 NITS incorporados: (1) raw/grep_hits.txt ~30MB por terminos de scope genericos ->
  _harvest_terms ahora descarta el PREFIJO de scope (motor/destinos/system, el eje de
  routing) + tokens <5 chars; y _signal_grep capea el raw a 50 lineas/termino (el count
  completo sigue en findings). Resultado: raw ~600KB. (2) test_unreadable_backlog_exits_1
  anadido (exit 1 = self-failure). 19 tests. Barreras re-verificadas con dientes tras los
  nits (mut routing -> 2 fallos; mut -i -> 1 fallo), restaurado md5-identico.

### 2026-07-10 - Cierre commit-directo (021i SOLO, aislado de 021k)
- Estado COMPLETED. Commit con ID + PATH venv para hooks. REGLA DE CIERRE DURO: re-suite
  tras el commit (arbol limpio) para tested_commit_sha == HEAD; la re-suite ademas DEBE
  devolver los 6 tests de 020r a verde (confirma que eran por arbol sucio, no regresion).
