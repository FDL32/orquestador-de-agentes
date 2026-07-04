# Work Plan - WOT-2026-015m

## Metadata
- **ID:** WOT-2026-015m
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Acortar el nombre de carpeta generado por ProjectTmpPathFactory.mktemp para
  evitar cruzar MAX_PATH de Windows bajo la suite completa (tests/conftest.py).
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Corregir ProjectTmpPathFactory.mktemp en tests/conftest.py (linea 40-48) para que el
nombre de carpeta que genera a partir de request.node.name (usado por la fixture tmp_path,
linea 173-178) quede acotado a una longitud corta y constante, en vez de usar el nombre
completo del test (hasta 88+ caracteres reales en este repo, mas sufijos de parametrizacion
[param]). El objetivo es eliminar el NotADirectoryError [WinError 267] intermitente que
sufre tests/test_classify_publication.py::test_allowlist_is_per_named_path_not_an_evasion
bajo la suite completa (no en aislado) cuando ese test crea un repo git real dentro de
tmp_path y los paths internos de git (.git/objects/..., index.lock, refs) cruzan el
limite de 260 caracteres de Windows sobre una base ya profunda
(tests/sandbox/test_runtime/session_PID/factory/..., ~92-101 chars) mas un counter
alto bajo suite completa.

Verificacion del objetivo (comando literal):
.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider no reproduce el
WinError 267 en ninguna corrida de 3 repeticiones consecutivas (ver Criterios de Aceptacion
6), y el nuevo test de barrera en tests/test_conftest_sandbox.py pasa.

## Contexto (diagnostico de Fase 0, confirmado en codigo por el Manager)

- tests/conftest.py:167-178 -- el fixture tmp_path_factory (scope session) instancia
  ProjectTmpPathFactory(SESSION_RUNTIME_ROOT / "factory"); el fixture tmp_path (function
  scope) llama tmp_path_factory.mktemp(request.node.name, numbered=True). SESSION_RUNTIME_ROOT
  es PROJECT_ROOT / "tests" / "sandbox" / "test_runtime" / f"session_{os.getpid()}" (linea
  16-19): con el PROJECT_ROOT real de este repo, la base
  .../factory/ mide 101 caracteres (medido: PID de 5 digitos tipico en esta maquina).
- tests/conftest.py:32-48 -- ProjectTmpPathFactory.mktemp:

      def mktemp(self, name: str, numbered: bool = True) -> Path:
          safe_name = name.replace("/", "_").replace("\\", "_")
          if numbered:
              self._counter += 1
              path = self.base_dir / f"{safe_name}{self._counter:04d}"
          else:
              path = self.base_dir / safe_name
          path.mkdir(parents=True, exist_ok=True)
          return path

  safe_name es el nombre COMPLETO del nodo pytest (request.node.name), sin acotar. Medido
  en este repo: el nombre de test mas largo real es
  test_build_review_prompt_includes_manager_learnings_for_code_and_preserves_static_rubric
  (88 caracteres); con parametrizacion (pytest.mark.parametrize, usada junto a tmp_path
  en tests/test_check_hook_interpreter.py, tests/test_encoding_integrity.py,
  tests/test_launcher_state_from_bus.py, tests/unit/test_encoding_guard_c1.py) el
  request.node.name real puede ser aun mas largo (incluye el sufijo [param]).
- tests/test_classify_publication.py:556-584 --
  test_allowlist_is_per_named_path_not_an_evasion(tmp_path) crea
  repo = tmp_path / "repo", ejecuta _init_repo(repo) (git init real via subprocess) y dos
  commits reales (_git(repo, "add", ...), _git(repo, "commit", ...)). Los objetos internos
  de git (.git/objects/2-hex/38-hex o packs pack-40-hex.pack, index.lock, refs)
  se crean bajo tmp_path/repo/.git/..., heredando la profundidad de tmp_path.
- Medicion cuantitativa (peor caso real, PID de 5 digitos, nombre de test mas largo real de
  este repo, counter de 2 digitos, path interno de git de 73 caracteres
  repo\.git\objects\pack\pack-40hex.pack): el path resultante mide 227-236
  caracteres dependiendo del test -- ya cerca del limite de 260, y CUALQUIER incremento
  (PID de 6 digitos, counter de 4 digitos bajo suite completa con miles de tests, o un path
  interno de git ligeramente mas largo, p.ej. loose objects en subdirectorios adicionales)
  cruza el limite. Esto es determinista-en-condiciones (profundidad + nombre largo + counter
  alto bajo suite completa), no aleatorio.
- LongPathsEnabled=1 esta activo en el registro de Windows de esta maquina, pero
  git config core.longpaths NO esta seteado (ni --global ni --system): git en si mismo
  no usa el soporte de rutas largas de Windows aunque el SO lo permita. Este dato descarta
  "ya esta activado en el registro" como explicacion de por que no falla siempre, y confirma
  que activar unicamente el flag del registro (sin core.longpaths) no resuelve nada -- el
  ticket NO habilita core.longpaths como fix (ver Non-goals); el fix elegido es acortar el
  nombre de carpeta.

## Alcance (cambio minimo)

Modificar UNICAMENTE ProjectTmpPathFactory.mktemp en tests/conftest.py para que el
safe_name usado como nombre de carpeta sea corto y de longitud constante, independiente de
la longitud de name de entrada, manteniendo unicidad garantizada por el counter ya
existente (no por el nombre).

### Diseno exacto

Anadir una funcion auxiliar _shorten_tmp_name(name: str) -> str (o logica equivalente
inline en mktemp) que, a partir del safe_name ya normalizado (tras
.replace("/", "_").replace("\\", "_")), produzca:

    shortened = safe_name[:16] + "_" + hashlib.sha1(safe_name.encode("utf-8")).hexdigest()[:8]

- Prefijo (16 chars): los primeros 16 caracteres del nombre normalizado, preservados para
  legibilidad de debug (permite identificar a simple vista que test genero la carpeta
  huerfana, requisito explicito del diseno de purga de huerfanos 013d/013i). El slicing
  [:16] de Python es seguro para nombres mas cortos que 16 (devuelve el string completo sin
  error): un test corto como test_foo produce prefijo test_foo (8 chars), no un error ni
  padding.
- Separador: un guion bajo literal, para legibilidad y para que el hash no se confunda
  visualmente con el prefijo.
- Hash (8 hex chars): hashlib.sha1(safe_name...).hexdigest()[:8] sobre el nombre
  COMPLETO normalizado (no solo el prefijo), para mantener unicidad "visual" incluso entre
  tests que comparten el mismo prefijo de 16 caracteres. Medido en este repo: 40 tests
  distintos comparten el prefijo test_resolve_mot, 30 comparten test_supervisor_, hasta 18
  tests comparten otros prefijos de 16 chars -- el hash diferencia esos casos para quien
  inspeccione una carpeta huerfana, aunque el counter YA garantiza que el path en si nunca
  colisiona (no es un requisito de correctitud, es una mejora de legibilidad de debug).
- Counter (sin cambios): el sufijo {self._counter:04d} ya existente sigue
  garantizando unicidad del path final; no cambia su formato ni su rol.

Resultado: la carpeta generada mide 16 + 1 + 8 + 4 = 29 caracteres en el peor caso (nombre
de test largo), o menos si el nombre de entrada es mas corto que 16 chars. Esto ahorra
hasta 63 caracteres frente al peor caso actual medido en este repo (92 chars: 88 del
nombre de test real mas largo + 4 del counter). Con el path base medido de 101 caracteres
(.../test_runtime/session_PID-5-digitos/factory) y un path interno de git de 73
caracteres (repo\.git\objects\pack\pack-40hex.pack, uno de los mas largos posibles
dentro de .git), el path total resultante mide 205 caracteres (medido con
hashlib.sha1 real sobre el nombre de test mas largo de este repo) -- 55 caracteres de
margen bajo el limite de 260, incluso con paths git-internos largos y sin depender de la
longitud del nombre del test de entrada. Verificado en consola durante el diagnostico Fase 0
(ver Riesgos para el detalle de la medicion).

## Non-goals

(scope cerrado, no ampliar)

- NO modificar tests/test_classify_publication.py::test_allowlist_is_per_named_path_not_an_evasion
  ni ningun otro test que use tmp_path: el test es correcto, el bug es de la infraestructura
  de sandbox.
- NO tocar el mecanismo de purga de huerfanos (_purge_orphan_session_dirs,
  _rmtree_robust, _force_remove_readonly, WOT-2026-013d/013i) ni el anclaje de
  SESSION_RUNTIME_ROOT dentro del proyecto: es deliberado y no forma parte de este bug.
- NO habilitar git config core.longpaths como fix principal ni como parte de este ticket
  (el humano eligio acortar el basetemp; core.longpaths puede proponerse como follow-up
  separado, no como sustituto de este cambio).
- NO cambiar la firma publica de mktemp (name: str, numbered: bool = True) ni el
  comportamiento cuando numbered=False: el shortening se aplica igual en ambos casos (ver
  Fase 1 abajo), sin anadir un parametro nuevo.
- NO tocar ninguna otra fixture de tests/conftest.py (_project_temp_environment,
  _restore_cwd, _isolate_controller_event_bus, _clear_runtime_project_root_cache) mas
  alla de ProjectTmpPathFactory.mktemp.

## Files Likely Touched

### repo_motor

- tests/conftest.py
- tests/test_conftest_sandbox.py (nuevo)

## Tests Esperados

1. Nuevo archivo tests/test_conftest_sandbox.py con al menos estos tests (cargando
   tests/conftest.py via importlib.util.spec_from_file_location -- un import conftest
   directo NO funciona en este repo porque pytest no inserta tests/ en sys.path bajo la
   configuracion actual; verificado en el diagnostico de Fase 0: import conftest falla con
   ModuleNotFoundError, mientras que importlib.util.spec_from_file_location("conftest_x",
   Path(__file__).resolve().parent / "conftest.py") + module_from_spec +
   spec.loader.exec_module carga el modulo correctamente -- mismo patron ya usado en
   .agent/agent_controller.py::_auto_archive_closed_artifacts):

   - test_mktemp_folder_name_is_short_for_long_test_name: instancia
     ProjectTmpPathFactory sobre un tmp_path de pytest nativo (no el tmp_path del propio
     proyecto, para no acoplar el test de la barrera al mecanismo que prueba), llama
     .mktemp(name) con un nombre de 88+ caracteres (usar literalmente
     "test_build_review_prompt_includes_manager_learnings_for_code_and_preserves_static_rubric"
     o un nombre sintetico igual de largo), y afirma que path.name tiene
     len(path.name) <= 29 (umbral concreto: 16 prefijo + 1 separador + 8 hash = 25
     caracteres sin counter, + 4 del sufijo {counter:04d} = 29 con counter; medir
     path.name completo, que YA incluye el counter, contra el umbral 29).
   - test_mktemp_preserves_uniqueness_via_counter: dos llamadas a .mktemp(same_name) con
     numbered=True sobre la MISMA instancia de factory producen dos paths DISTINTOS (unicidad
     via counter, no rota por el shortening).
   - test_mktemp_short_name_not_padded_or_broken: un nombre corto ("test_foo", 8
     caracteres) produce un safe_name valido y usable como carpeta (no lanza excepcion, no
     queda vacio, path.mkdir() no falla).
2. No-regresion: la suite existente de tests/ (en particular cualquier test que dependa de
   tmp_path) sigue verde tras el cambio (ningun test depende del nombre completo de la
   carpeta; confirmado en Fase 0: grep -rn "tmp_path.name" y grep -rn "safe_name" tests/ no
   encuentra ningun assert sobre el nombre generado fuera de conftest.py mismo).
3. MUTATION (documentado en execution_log.md, no como test pytest nuevo separado): revertir
   temporalmente el shortening en mktemp (volver a safe_name = name.replace(...) sin el
   prefijo+hash) y confirmar que test_mktemp_folder_name_is_short_for_long_test_name FALLA
   (el nombre de carpeta vuelve a ser largo); restaurar el fix y confirmar que el mismo test
   PASA. Usar el patron ya establecido en el repo (worktree/checkout parcial con
   git status --short limpio antes y despues, o edicion temporal + git diff para confirmar
   revertido 100% al estado post-fix); ver prompts/orchestrator_launch_builder.md, seccion
   "Verificacion del test de regresion".

## Criterios de Aceptacion (binarios)

1. ProjectTmpPathFactory.mktemp genera nombres de carpeta acotados a <= 29 caracteres
   totales (incluyendo el sufijo {counter:04d}), para CUALQUIER name de entrada,
   verificado por test_mktemp_folder_name_is_short_for_long_test_name con el nombre de test
   mas largo real de este repo (88 caracteres) y con un nombre sintetico aun mas largo (150+
   caracteres) para cubrir el caso de parametrizacion.
2. La unicidad de paths generados por llamadas sucesivas sigue garantizada por el counter
   existente, no por el nombre: verificado por test_mktemp_preserves_uniqueness_via_counter.
3. Un nombre de test corto ("test_foo") sigue produciendo una carpeta valida, sin excepcion
   ni comportamiento degenerado: verificado por test_mktemp_short_name_not_padded_or_broken.
4. MUTATION: revertir el shortening hace que
   test_mktemp_folder_name_is_short_for_long_test_name FALLE; con el fix restaurado, el
   mismo test PASA. Ambos resultados (FAIL-sin-fix, PASS-con-fix) quedan registrados
   literalmente en execution_log.md con el comando exacto y el output relevante (no basta
   con narrar "se verifico").
5. Suite completa de tests/test_conftest_sandbox.py verde: los 3 tests nuevos pasan, 0
   failed.
6. test_allowlist_is_per_named_path_not_an_evasion deja de fallar de forma intermitente bajo
   la suite completa: correr
   .venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider TRES VECES
   consecutivas (no una sola) y confirmar 0 WinError 267 / 0 NotADirectoryError en las
   tres corridas. Nota de honestidad epistemica: esto NO prueba matematicamente que el bug
   nunca puede volver a ocurrir (el fenomeno era condicional a profundidad+contador, no
   puramente aleatorio) -- es evidencia empirica de que el margen de 55 caracteres bajo
   MAX_PATH (ver Contexto) elimina la condicion determinista observada. Si CUALQUIERA de las
   tres corridas reproduce el error, este criterio FALLA y el ticket no cierra.
7. ruff check tests/conftest.py tests/test_conftest_sandbox.py -> exit code 0.
8. uv run ruff format --check tests/conftest.py tests/test_conftest_sandbox.py -> exit
   code 0 (si uv no arranca en este entorno segun el diagnostico de WOT-2026-016c, usar
   .venv/Scripts/python.exe -m ruff format --check <paths> como equivalente y documentar la
   sustitucion en execution_log.md; no declarar el gate como "no aplica" sin evidencia).
9. Suite canonica: python scripts/run_pytest_safe.py --level all con last-run.json en
   status=finished, exit_code=0, level=all, args_mode=default_discovery y
   tested_commit_sha == HEAD del commit que se entrega.
10. validate (Manager gate, ver abajo) en 0 errors / 0 warnings.

## Quality Gates

- Builder ejecuta:
  - .venv/Scripts/python.exe -m pytest tests/test_conftest_sandbox.py -v
  - .venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider (x3 consecutivas, ver
    Criterio 6)
  - ruff check tests/conftest.py tests/test_conftest_sandbox.py
  - uv run ruff format --check tests/conftest.py tests/test_conftest_sandbox.py
  - .venv/Scripts/python.exe scripts/run_pytest_safe.py --level all
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - .venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .

## STOP conditions

- Si el shortening rompe algun test existente que dependa (aunque sea implicitamente) del
  nombre completo de la carpeta tmp: DETENTE, documenta el hallazgo en execution_log.md y
  no relajes ese test para forzar verde; escala al Manager.
- Si test_mktemp_preserves_uniqueness_via_counter falla (dos llamadas producen el MISMO
  path): DETENTE, el shortening rompio la garantia de unicidad; no es un cambio menor, revisa
  el diseno antes de continuar.
- Si alguna de las tres corridas del Criterio 6 reproduce WinError 267 /
  NotADirectoryError: DETENTE, no declares el ticket resuelto; documenta la corrida exacta
  que fallo (semilla, orden de tests, output completo) y escala al Manager -- puede indicar
  que el shortening no es suficiente o que hay una causa adicional no diagnosticada.
- Si "uv run ruff format --check" no arranca en este entorno (mismo sintoma documentado en
  WOT-2026-016c: uv desalineado del .venv), no lo declares "no aplica": usa
  .venv/Scripts/python.exe -m ruff format --check <paths> como equivalente y documenta la
  sustitucion con el output literal en execution_log.md.
- Si run_pytest_safe.py --level all no cierra con tested_commit_sha == HEAD del commit
  final: no reportes cierre canonico; re-corre tras el commit final antes de --mark-ready.

## Riesgos

- Bajo: cambio de una funcion aislada (mktemp), sin caller externo mas alla de la fixture
  tmp_path (confirmado: grep -rn "mktemp(" tests/ da un unico resultado, la propia
  fixture en tests/conftest.py:178).
- Medio: el shortening reduce la legibilidad del nombre de carpeta para debug de huerfanos;
  mitigado explicitamente con el prefijo de 16 caracteres + hash corto (en vez de un hash
  puro opaco), que preserva identificabilidad aproximada del test de origen.
- Medio: el Criterio 6 (tres corridas completas de la suite) es una prueba empirica, no una
  demostracion formal de ausencia del bug; documentado explicitamente como tal en el propio
  criterio para no sobre-prometer certeza matematica donde solo hay evidencia estadistica
  fuerte (el margen de 55 caracteres bajo MAX_PATH reduce drasticamente la probabilidad, no
  la elimina en el limite teorico absoluto si un name de entrada fuese absurdamente
  patologico -- fuera del rango observado en este repo).

## Decision Arquitectonica

Por que prefijo truncado + hash corto en vez de: (a) hash puro opaco, (b) contador puro sin
nombre, o (c) un numbered=False mas agresivo. El hash puro pierde toda legibilidad
para quien inspeccione manualmente una carpeta huerfana bajo tests/sandbox/test_runtime/
(requisito explicito del diseno 013d/013i de purga de huerfanos: la carpeta debe ser
identificable). El contador puro (sin nombre ni hash) ya es la unica fuente de unicidad
garantizada, pero por si solo no aporta ninguna pista de que test la genero. La combinacion
prefijo(16)+hash(8) da longitud CONSTANTE (25 chars sin counter, 29 con counter),
independiente de la longitud de entrada, con legibilidad aproximada (primeros 16 caracteres
del nombre real) y diferenciacion adicional entre nombres que comparten prefijo (via hash),
sin depender de que el hash por si solo sea la unica garantia de unicidad (esa garantia sigue
siendo el counter, no el hash).

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Prefijo(16) + hash(8) + counter | Longitud constante y corta; legibilidad aproximada para debug; unicidad garantizada por counter (no por hash) | Trunca informacion del nombre completo (aceptable: el nombre completo sigue disponible en el output de pytest) | Elegida |
| Hash puro (sin prefijo) | Mas corto aun (8-12 chars) | Cero legibilidad para debug de huerfanos; viola el requisito explicito de 013d/013i | Descartada |
| Solo counter (sin nombre ni hash) | Mas simple | Cero trazabilidad de que test genero la carpeta; regresion de UX para debug | Descartada |
| Habilitar git config core.longpaths | Resuelve el sintoma sin tocar tests/conftest.py | El humano decidio explicitamente NO usar esta via como fix principal (ver Non-goals); ademas no soluciona el problema de raiz (rutas profundas siguen siendo fragiles para otras herramientas no-git que no respeten longpaths) | Descartada para este ticket (posible follow-up) |

## Criterios de Aceptacion Global
- [ ] mktemp genera nombres <= 29 caracteres (con counter) para cualquier name de entrada
- [ ] Unicidad garantizada por counter, no por nombre/hash (test dedicado)
- [ ] Nombres cortos no rotos ni degenerados (test dedicado)
- [ ] Mutation FAIL-sin-fix / PASS-con-fix documentado en execution_log.md
- [ ] tests/test_conftest_sandbox.py: 3 tests nuevos, 0 failed
- [ ] Suite completa tests/ x3 corridas consecutivas sin WinError 267 / NotADirectoryError
- [ ] ruff check + ruff format --check en verde
- [ ] Suite canonica run_pytest_safe.py --level all verde con tested_commit_sha == HEAD
- [ ] validate --json 0 errors / 0 warnings (Manager gate)
