# Execution Log - WOT-2026-015m

**Ticket:** WOT-2026-015m - Acortar el nombre de carpeta de ProjectTmpPathFactory.mktemp para
evitar MAX_PATH intermitente bajo la suite completa.
**Estado:** COMPLETED

## Bitacora

- Plan creado y aprobado por el Manager. Diagnostico de Fase 0 confirmado en codigo
  (tests/conftest.py:32-48, 167-178; tests/test_classify_publication.py:556-584).
  Medicion cuantitativa realizada: peor caso actual 92 caracteres de carpeta, shortening
  propuesto reduce a 29 caracteres constantes (ahorro de 63 caracteres), dejando 55
  caracteres de margen bajo MAX_PATH (260) con paths git-internos largos incluidos.
- Handoff al Builder pendiente de --bootstrap-ticket y --validate.

## Fase 0 (Builder) - diagnostico confirmado antes de tocar codigo

- Preflight: `--validate --json` = 0 errors / 0 warnings. STATE.md = WOT-2026-015m/IN_PROGRESS,
  TURN.md = BUILDER/IMPLEMENT, work_plan.md Estado=APPROVED, ID activo = WOT-2026-015m. Nota:
  `.agent_common_rules.md` y `.builder_rules` NO existen en este repo (ni en raiz ni en ningun
  subdirectorio via glob) -- se procede solo con work_plan.md + el prompt del Orquestador, que
  es autocontenido.
- `ProjectTmpPathFactory` completa (tests/conftest.py:32-48) leida. Confirmado que `mktemp`
  (l.40-48) es el UNICO punto a tocar: `__init__` (l.35-38) crea `base_dir` y `_counter = 0` y
  no requiere cambios.
- `hashlib` NO estaba importado en conftest.py (imports actuales: importlib, os, shutil, stat,
  sys, tempfile, pathlib.Path, pytest). Se anade en el bloque de imports estandar.
- Por que el counter garantiza unicidad (y el hash no es necesario para eso): `self._counter`
  es un entero de instancia que se incrementa (`self._counter += 1`, l.43) en CADA llamada a
  `mktemp(numbered=True)`, monotonicamente, sobre la MISMA instancia de
  `ProjectTmpPathFactory` (una por sesion de pytest, ver fixture `tmp_path_factory` scope=session
  l.167-170). Como el sufijo `{self._counter:04d}` se concatena siempre al final del path
  (l.44) y nunca se reinicia ni se comparte entre instancias dentro de una sesion, dos llamadas
  a `mktemp(same_name)` producen SIEMPRE paths distintos independientemente de que `safe_name`
  sea identico, truncado, o incluso vacio -- la unicidad depende exclusivamente del contador,
  no del contenido de `name`. El shortening (prefijo+hash) es ortogonal a esta garantia: solo
  mejora la legibilidad visual del nombre, no participa en la unicidad.
- No-regresion confirmada por grep: `grep -rn "mktemp("` en tests/ da un unico resultado
  (tests/conftest.py, la propia fixture `tmp_path` l.178); `grep -rn "tmp_path\.name|safe_name"`
  en tests/ da un unico archivo (tests/conftest.py) -- ningun test fuera de conftest.py depende
  del nombre completo de la carpeta generada.

## Fase 1 (Builder) - implementacion

- Cambio minimo en `mktemp` (tests/conftest.py): tras `safe_name = name.replace("/", "_").replace("\\", "_")`,
  se anade `safe_name = safe_name[:16] + "_" + hashlib.sha1(safe_name.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]`.
  Se anadio `import hashlib` al bloque de imports estandar. No se toco nada mas de `mktemp`
  ni de la clase `ProjectTmpPathFactory`.
- Desviacion menor documentada (fiel al diseno aprobado, no cambia el algoritmo): se anadio
  el kwarg `usedforsecurity=False` a `hashlib.sha1(...)` porque `ruff check` (regla S324,
  "Probable use of insecure hash functions in hashlib") bloqueaba el gate sin el. El plan
  especifica `hashlib.sha1(safe_name.encode("utf-8")).hexdigest()[:8]` sin ese kwarg; el uso
  aqui es explicitamente NO criptografico (solo desambiguacion visual para debug de huerfanos,
  el counter es la unica garantia de unicidad real, ver Fase 0) por lo que `usedforsecurity=False`
  es la forma correcta y estandar (soportada desde Python 3.9, este repo usa 3.10.19) de declarar
  esa intencion sin silenciar el linter con un noqa ciego. No cambia el algoritmo de shortening
  ni la longitud resultante (sigue siendo prefijo(16)+"_"+hash(8) = 25 chars sin counter, 29 con).
- `ruff format` reformateo automaticamente la expresion de `safe_name` (la parentiza en
  multiples lineas por longitud >88 chars); no cambia la logica, solo el estilo de wrapping.

## Fase 2 (Builder) - tests nuevos + mutation-verify

- Creado tests/test_conftest_sandbox.py con los 3 tests especificados en el plan, cargando
  tests/conftest.py via `importlib.util.spec_from_file_location` (no `import conftest`, que
  falla en este repo segun diagnostico del Manager). Los 3 tests instancian
  `ProjectTmpPathFactory` sobre un `tmp_path / "factory_base"` (el `tmp_path` aqui es el fixture
  del propio proyecto, ya que `tests/conftest.py` lo sobreescribe globalmente para todo el
  repo) -- no se crean repos git reales.
- `.venv/Scripts/python.exe -m pytest tests/test_conftest_sandbox.py -v` -> 3 passed en 0.07s-0.08s
  (corrido 2 veces, antes y despues del reformat de ruff sobre el propio archivo de test).

### MUTATION-VERIFY (obligatorio, los 4 exit codes)

1. Backup de tests/conftest.py guardado en el scratchpad de la sesion
   (`conftest.py.backup_015m`) antes de mutar.
2. Reversion temporal: se edito `mktemp` para volver a
   `safe_name = name.replace("/", "_").replace("\\", "_")` SIN el shortening (se dejo el
   `import hashlib` sin usar, irrelevante para el resultado del test). `git diff tests/conftest.py`
   confirmo que el UNICO cambio residual frente a HEAD era el import huerfano de hashlib
   (la logica de `mktemp` quedo identica a la version pre-fix).
   - (a) Comando: `.venv/Scripts/python.exe -m pytest tests/test_conftest_sandbox.py::test_mktemp_folder_name_is_short_for_long_test_name -v`
   - (b) Resultado SIN fix: **FAILED**, `EXIT_CODE_SIN_FIX=1`. Output relevante:
     `AssertionError: mktemp('test_build_review_prompt_includes_manager_learnings_for_code_and_preserves_static_rubric')
     produced folder name '...rubric0001' (92 chars), expected <= 29` -- el 92 coincide
     exactamente con la medicion del plan (peor caso actual).
3. Restauracion: `cp` del backup de vuelta a tests/conftest.py. `git diff tests/conftest.py`
   tras restaurar mostro EXACTAMENTE el diff esperado del fix (8 lineas insertadas: el
   `import hashlib` + las 7 lineas de la expresion de shortening con `usedforsecurity=False`),
   sin residuos de la mutacion.
   - (c) Comando: mismo test, mismo comando.
   - (d) Resultado CON fix: **PASSED**, `EXIT_CODE_CON_FIX=0`.
- Arbol restaurado y limpio confirmado (`git diff --stat tests/conftest.py` = 1 file changed,
  8 insertions(+), 0 deletions -- el diff acumulado esperado del ticket, no residuo de la mutacion).


Scope override: Over-captura del scope gate sobre tickets CERRADOS. Verificado con 'git show --name-only HEAD': el commit 2d293ec de 015m toca como PRODUCTIVO solo tests/conftest.py + tests/test_conftest_sandbox.py (dentro del FLT). AUDIT_016w/PLAN_016w aparecen como BORRADOS (D) por el archivador al bootstrapear 015m (trampa heredada). Las 7 rutas restantes (agent_controller.py, AUDIT_016c/016s/016t, check_deliverables_exist.py, test_agent_controller.py, test_check_deliverables_exist.py) NO estan en el commit de 015m: pertenecen a tickets cerrados 016c/016w.. Affected files: <REPO_ROOT>/.agent/agent_controller.py, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016c.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016s.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016t.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016w.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-016w.md, <REPO_ROOT>/scripts/check_deliverables_exist.py, <REPO_ROOT>/tests/test_agent_controller.py, <REPO_ROOT>/tests/unit/test_check_deliverables_exist.py

Manager approved canonical closeout for WOT-2026-015m