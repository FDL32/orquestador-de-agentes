# AUDIT - WOT-2026-015m

**Ticket:** WOT-2026-015m - Acortar el nombre de carpeta de ProjectTmpPathFactory.mktemp para
evitar MAX_PATH intermitente bajo la suite completa.
**Estado del plan:** APPROVED

## TP Check

- TP-01: verificado - las fases del PLAN son secuenciales sin contradiccion: confirmar
  sintoma -> aplicar shortening en mktemp -> crear tests nuevos -> mutation -> gates ->
  commit/mark-ready. La unica reversion es la barrera de mutation, documentada como
  transitoria y restaurada de inmediato, no una contradiccion de alcance.
- TP-02: verificado - cada criterio de aceptacion del work_plan.md cita un comando o
  asercion exacta: len(path.name) <= 29 para el criterio 1, dos paths distintos para el
  criterio 2, ausencia de excepcion para el criterio 3, FAIL-sin-fix/PASS-con-fix literal
  para el criterio 4, comando pytest exacto para el criterio 5, tres corridas completas de
  tests/ sin WinError 267 para el criterio 6, comandos ruff exactos para 7 y 8, los 4 campos
  exactos del last-run.json para el criterio 9.
- TP-03: verificado - Files Likely Touched enumera exactamente 2 archivos concretos, cada
  bullet con una unica ruta parseable. Los Non-goals delimitan explicitamente que NO se toca
  el test test_allowlist_is_per_named_path_not_an_evasion, ni el mecanismo de purga de
  huerfanos (013d/013i), ni se habilita core.longpaths, para que el Builder no derive scope.
- TP-04: verificado - no aparece lenguaje blando tipo si procede u opcionalmente en el
  flujo critico del work_plan.md. La honestidad epistemica del Criterio 6 (tres corridas
  como evidencia empirica, no prueba formal) esta explicitamente acotada y no delega
  decision de alcance al Builder: el criterio sigue siendo binario.
- TP-05: verificado - work_plan.md, PLAN_WOT-2026-015m.md y este AUDIT describen la misma
  secuencia, los mismos 2 archivos de Files Likely Touched y los mismos 10 criterios de
  cierre. Los Blockers de este AUDIT usan los mismos verbos que las Fases del PLAN.
- TP-06: no aplica como anti-patron (este propio TP Check usa la forma canonica
  TP-01..TP-07, no criterios de diseno del entregable).
- TP-07: verificado - no aparecen clausulas de alcance condicional que dejen una decision
  abierta en Objetivo, Fases, Criterios ni Decision Arquitectonica del work_plan.md. La
  unica condicional tecnica (sustituir uv por venv si uv esta roto) esta acotada a un gate
  de tooling ya con precedente en WOT-2026-016c, no a la decision de alcance del ticket.

## Diagnostico Fase 0 confirmado (no inferido)

El diagnostico de Fase 0 del Orquestador fue verificado directamente en codigo por el
Manager antes de aprobar este plan:

- tests/conftest.py:32-48 (clase ProjectTmpPathFactory, metodo mktemp) leido literal:
  confirma que safe_name es el nombre completo normalizado del test, sin acotar.
- tests/conftest.py:167-178 (fixtures tmp_path_factory y tmp_path) leido literal: confirma
  el anclaje dentro del proyecto (SESSION_RUNTIME_ROOT / factory) y la llamada
  tmp_path_factory.mktemp(request.node.name, numbered=True).
- tests/test_classify_publication.py:556-584 leido literal: confirma que el test crea un
  repo git real con _init_repo y dos commits reales via subprocess, generando artefactos
  internos de git bajo tmp_path/repo/.git/.
- Medicion cuantitativa ejecutada por el Manager (no asumida): el nombre de test mas largo
  real de este repo mide 88 caracteres
  (test_build_review_prompt_includes_manager_learnings_for_code_and_preserves_static_rubric,
  confirmado con grep sobre todo tests/); el peor-caso actual (nombre+counter) mide 92
  caracteres de carpeta; con el shortening propuesto (prefijo 16 + separador 1 + hash 8 +
  counter 4) la carpeta mide 29 caracteres constantes, un ahorro de 63 caracteres en el
  peor caso medido.
- Confirmado que 40 tests distintos comparten el prefijo de 16 caracteres
  test_resolve_mot y 30 comparten test_supervisor_ (grep + cut + sort + uniq -c sobre
  todo tests/): esto justifica por que el diseno no usa solo un prefijo truncado (perderia
  legibilidad diferenciadora) sino prefijo+hash.
- Confirmado con un experimento de import real (ejecutado y luego revertido, sin dejar
  artefactos en el repo) que import conftest directo falla con ModuleNotFoundError en este
  repo, mientras que importlib.util.spec_from_file_location mas module_from_spec mas
  spec.loader.exec_module carga tests/conftest.py correctamente y permite instanciar
  ProjectTmpPathFactory y llamar mktemp sobre una instancia de prueba. Este es el mecanismo
  que el Builder debe usar en tests/test_conftest_sandbox.py.
- Confirmado con grep que mktemp tiene un unico caller (tests/conftest.py:178, la propia
  fixture tmp_path): el cambio no tiene superficie de impacto oculta.
- Confirmado con grep que ningun test en tests/ hace assert sobre tmp_path.name o
  safe_name fuera de conftest.py mismo: el shortening no rompe ninguna asercion existente
  sobre el nombre de carpeta.

La premisa de Fase 0 es CORRECTA: el sintoma es determinista-en-condiciones (profundidad
mas nombre largo mas counter alto bajo suite completa), no aleatorio, y es cerrable con la
barrera de acortamiento propuesta.

## Blockers (para el Manager en review)

- Si ProjectTmpPathFactory.mktemp sigue usando el nombre completo del test (sin el
  prefijo de 16 mas hash de 8) tras el commit del Builder: BLOCKER, el fix no fue aplicado.
- Si test_mktemp_folder_name_is_short_for_long_test_name no verifica un umbral concreto
  (29 caracteres o menos) sino una asercion vaga: BLOCKER, criterio no verificable (TP-02).
- Si test_mktemp_preserves_uniqueness_via_counter falla o fue relajado: BLOCKER, la unicidad
  del path dejo de estar garantizada.
- Si no hay evidencia literal (comando mas output) de FAIL-sin-fix / PASS-con-fix para el
  test de mutation: BLOCKER, el criterio de aceptacion 4 no esta satisfecho.
- Si alguna de las tres corridas completas de tests/ (Criterio 6) reprodujo WinError 267 y
  el Builder no lo reporto como hallazgo explicito: BLOCKER, evidencia ocultada o
  redondeada a verde en violacion directa de las reglas de
  prompts/orchestrator_launch_builder.md.
- Si tests/test_classify_publication.py o el mecanismo de purga de huerfanos
  (_purge_orphan_session_dirs, _rmtree_robust, _force_remove_readonly) aparecen tocados en
  el diff: BLOCKER, fuera de scope (Non-goals).
- Si git config core.longpaths aparece configurado como parte de este ticket: BLOCKER,
  fuera de scope (Non-goals); el fix elegido es el acortamiento, no longpaths.
- Si la suite canonica (run_pytest_safe.py --level all) no tiene tested_commit_sha igual a
  HEAD del commit final: BLOCKER, no es cierre canonico.

## Evidencia esperada en execution_log.md

- Cita literal de ProjectTmpPathFactory.mktemp antes y despues del cambio (diff o snippet).
- Salida literal de: pytest tests/test_conftest_sandbox.py -v (3 passed).
- Salida literal de mutation: FAIL-sin-fix (comando mas output) y PASS-con-fix (comando mas
  output) para test_mktemp_folder_name_is_short_for_long_test_name.
- Salida literal de las TRES corridas completas de
  .venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider, cada una con su
  resultado final (N passed, 0 failed, ausencia explicita de WinError 267 o
  NotADirectoryError).
- Salida literal de ruff check y ruff format --check (o su sustituto documentado).
- Salida literal (o referencia a last-run.json) de la suite canonica con los 4 campos
  exactos y tested_commit_sha igual a HEAD.
- Commit sha del repo_motor que contiene el fix, citado con WOT-2026-015m en el mensaje.
