# PLAN - WOT-2026-015m

**Ticket:** WOT-2026-015m - Acortar el nombre de carpeta de ProjectTmpPathFactory.mktemp para
evitar MAX_PATH intermitente bajo la suite completa.
**Estado:** APPROVED
**delivery_authority:** repo_motor | **deliverable_type:** code

Este documento es la estrategia tecnica breve del ticket; el contrato completo (diagnostico
detallado, criterios, gates, STOP conditions) vive en work_plan.md. Si algo difiere entre
ambos, work_plan.md manda.

## Resumen del problema

tests/conftest.py, clase ProjectTmpPathFactory, metodo mktemp (linea 40-48), usa el nombre
COMPLETO del test (request.node.name, hasta 88+ caracteres reales en este repo, mas
sufijos de parametrizacion) como nombre de carpeta bajo el sandbox de tests
(tests/sandbox/test_runtime/session_PID/factory/, ~101 caracteres de base). Cuando un test
como test_allowlist_is_per_named_path_not_an_evasion
(tests/test_classify_publication.py:556) crea un repo git real dentro de tmp_path y corre
git init/add/commit por subprocess, los paths internos de git
(.git/objects/..., index.lock, refs, packs) heredan esa profundidad y bajo la suite completa
(contador alto, PID variable) pueden cruzar el limite de 260 caracteres de Windows,
produciendo NotADirectoryError [WinError 267] de forma intermitente (no en aislado). git
config core.longpaths no esta activo en esta maquina, asi que git no usa el soporte de rutas
largas del registro aunque LongPathsEnabled=1 este puesto.

## Estrategia (cambio minimo)

1. Confirmar en codigo (ya hecho en Fase 0 del Manager) que ProjectTmpPathFactory.mktemp usa
   el nombre completo del test sin acotar, y que ningun otro caller depende de ese nombre
   completo (unico caller: la fixture tmp_path en la linea 178).
2. Anadir shortening en mktemp: tomar los primeros 16 caracteres del safe_name ya
   normalizado, anadir un guion bajo y los primeros 8 caracteres hex de
   hashlib.sha1(safe_name).hexdigest() sobre el nombre COMPLETO normalizado. El sufijo
   {counter:04d} existente no cambia y sigue siendo la unica garantia de unicidad del path
   final.
3. Crear tests/test_conftest_sandbox.py (nuevo) que cargue tests/conftest.py via
   importlib.util.spec_from_file_location (un import conftest directo no funciona en este
   repo, verificado en Fase 0) y pruebe: (a) un nombre de test largo produce una carpeta
   <= 29 caracteres, (b) la unicidad sigue garantizada por el counter con nombres repetidos,
   (c) un nombre corto no rompe ni degenera.
4. Ejercer mutation: revertir el shortening, confirmar que el test (a) falla; restaurar,
   confirmar que pasa. Registrar ambos resultados literales en execution_log.md.
5. Correr gates: pytest focal del archivo nuevo, ruff check, ruff format --check (o su
   equivalente .venv si uv esta roto en este entorno), la suite completa de tests/ TRES
   veces consecutivas para confirmar ausencia empirica del WinError 267, y la suite canonica
   run_pytest_safe.py --level all.
6. Commitear en repo_motor con WOT-2026-015m en el mensaje, mark-ready, esperar review del
   Manager (validate es Manager gate).

## Archivos tocados

- tests/conftest.py (funcion mktemp de ProjectTmpPathFactory unicamente)
- tests/test_conftest_sandbox.py (nuevo, 3 tests)

## Criterios de cierre

Identicos a work_plan.md seccion "Criterios de Aceptacion (binarios)" items 1-10. No
duplicados aqui para evitar deriva; ver work_plan.md como fuente unica de los comandos
exactos.
