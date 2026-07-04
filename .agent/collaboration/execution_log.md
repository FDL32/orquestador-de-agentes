# Execution Log - WOT-2026-019b

Ticket: WOT-2026-019b - Fuga PII en el detail de "stamp ilegible" de
_read_pytest_safe_verdict (OSError vuelca ruta absoluta con username).
**Estado:** COMPLETED

## Bitacora

- Plan creado y aprobado por el Manager. Fase 0 (Orquestador) verifico la premisa
  del ticket contra el estado real del repo antes de bootstrapear:
  - .agent/agent_controller.py lineas 2038-2039 confirmadas: except (OSError,
    json.JSONDecodeError) as exc con f-string "stamp ilegible: {exc}" literal.
  - str(OSError(...)) con filename seteado concatena strerror + errno + la ruta
    absoluta -- demostrado en vivo, no solo inferido.
  - Correccion clave a la premisa original de la ficha: _relativize_scope_path NO
    vive en agent_controller.py, vive en .agent/scope_gate.py linea 539. Ya
    importado (linea 52, import scope_gate) y ya usado con el patron
    scope_gate.<funcion>(...) en 14 sitios existentes.
  - El helper toma un path (str), no una excepcion -- el fix debe extraer
    exc.filename en el sitio de uso, no cambiar la firma del helper.
  - json.JSONDecodeError no hereda de OSError (hereda de ValueError), su str(exc)
    es seguro y no debe tocarse.
  - grep confirmo 0 tests existentes cubriendo esta rama de error en
    tests/test_agent_controller.py (clase TestRunQualityGates, lineas 324-509).


## Nota del Orquestador (pre-Builder) - warning de prosa aceptado

Validate = total_errors: 0, total_warnings: 1 (TP-PROSE-04 "extremos-lazy").
El Orquestador redujo de 2->1 corrigiendo las 2 frases genuinamente vagas del
work_plan (L78 "todos los usos" -> "las 9 referencias"; L221 "todo verde" ->
"exit 0"). El warning residual (sin linea del checker) ancla en prosa TECNICA
precisa (distincion OSError/JSONDecodeError por MRO: "ambos excepts siguen
disparando cada uno para su tipo").

DECISION (con OK del humano): warning ACEPTADO como falso positivo lexico. NO se
reescribe la frase tecnica para no deformar la distincion. No bloquea:
total_errors: 0, plan APPROVED, bus correcto (ACTIVE=WOT-2026-019b, ROL=BUILDER),
criterios binarios definidos. Seguimiento higiene de prosa -> no amerita ticket.

## Builder - Implementacion (PASO 1 + PASO 2)

### PASO 1 - `.agent/agent_controller.py` (fix)

Diff aplicado (lineas ~2036-2039 de `_read_pytest_safe_verdict`), diff minimo,
no toca ninguna otra rama de la funcion:

```
     try:
         stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
-    except (OSError, json.JSONDecodeError) as exc:
+    except OSError as exc:
+        # WOT-2026-019b: str(exc) de un OSError concatena la ruta absoluta
+        # (exc.filename), que bajo PROJECT_ROOT arrastra el username local.
+        # Componer el detail a mano sin exponer nunca la ruta cruda.
+        if exc.filename:
+            where = scope_gate._relativize_scope_path(exc.filename, PROJECT_ROOT)
+            detail = f"stamp ilegible: {exc.strerror} (errno {exc.errno}) en {where}"
+        else:
+            detail = f"stamp ilegible: {exc.strerror} (errno {exc.errno})"
+        return {"verdict": "inconclusive", "detail": detail}
+    except json.JSONDecodeError as exc:
         return {"verdict": "inconclusive", "detail": f"stamp ilegible: {exc}"}
```

`except OSError` compone el detail con `exc.strerror` + `exc.errno` y, solo si
`exc.filename` no es `None`, adjunta `scope_gate._relativize_scope_path(exc.filename,
PROJECT_ROOT)`. `except json.JSONDecodeError` queda identico al original
(`f"stamp ilegible: {exc}"`), sin cambios de fondo. `scope_gate.py` NO se toco
(solo se llama, patron ya existente en 14 sitios previos del archivo).

### PASO 2 - `tests/test_agent_controller.py` (tests nuevos en `TestRunQualityGates`)

3 tests nuevos anadidos inmediatamente despues de
`test_read_pytest_safe_verdict_partial_coverage_is_inconclusive`:

1. `test_read_pytest_safe_verdict_oserror_detail_has_no_absolute_path` (test de
   REGRESION principal): monkeypatchea `ac.PROJECT_ROOT` a `tmp_path`, crea el
   stamp real (`stamp_path.write_text("{}", ...)` para que `stamp_path.exists()`
   sea `True` y se llegue al `try/except`), y monkeypatchea `pathlib.Path.read_text`
   a nivel de clase para que, SOLO cuando `self == stamp_path`, lance
   `OSError(13, "Permission denied", absolute_path_str)` (delegando al
   `real_read_text` guardado para cualquier otra instancia, evitando romper el
   resto del test runner). Asserta que ni la ruta absoluta simulada completa, ni
   `str(tmp_path)`, ni `str(Path.home())` (username real de quien ejecuta el test)
   aparecen en `detail`; y que SI aparecen `<REPO_ROOT>`, el basename
   `last-run.json`, y la info de diagnostico (`Permission denied`, `13`).
2. `test_read_pytest_safe_verdict_oserror_without_filename_is_safe`: mismo patron
   pero `OSError("boom sin filename")` (sin `.filename`, cae en el `else` que NO
   llama al helper con `None`). Asserta que `str(tmp_path)` no aparece en `detail`.
3. `test_read_pytest_safe_verdict_jsondecodeerror_detail_unchanged` (PARIDAD):
   escribe un `last-run.json` con contenido no-JSON real (sin monkeypatch de
   `read_text`, para forzar el `json.JSONDecodeError` real de `json.loads`).
   Asserta `detail` empieza por `"stamp ilegible: "` (sin cambios de fondo) y que
   `str(tmp_path)` no aparece (confirma que `JSONDecodeError` nunca tuvo el
   problema, no que se le aplico el mismo tratamiento).

Punto de monkeypatch: `pathlib.Path.read_text` a nivel de CLASE (no
`stamp_path.read_text` de instancia, que no es monkeypatcheable directamente sin
resultar en un bind roto) filtrando por identidad del objeto `stamp_path`
concreto. Confirmado que SI se llega al except (no es una hipotesis): el test
paso en verde con el fix, y en el mutation check de abajo el detail cambio
exactamente como predice el diagnostico (ruta absoluta con username `fdl`
reapareciendo integra), lo cual demuestra que el except se ejercito de verdad.

### PASO 3 - Verificacion

Comando: `.venv\Scripts\python.exe -m pytest tests/test_agent_controller.py -k "TestRunQualityGates" -v`

Salida literal (CON el fix, ANTES del mutation check):

```
collecting ... collected 129 items / 119 deselected / 10 selected

tests/test_agent_controller.py::TestRunQualityGates::test_run_quality_gates_returns_dict PASSED [ 10%]
tests/test_agent_controller.py::TestRunQualityGates::test_run_quality_gates_does_not_rerun_pytest_with_timeout PASSED [ 20%]
tests/test_agent_controller.py::TestRunQualityGates::test_run_quality_gates_pytest_green_from_stamp PASSED [ 30%]
tests/test_agent_controller.py::TestRunQualityGates::test_run_quality_gates_real_failure_is_not_masked PASSED [ 40%]
tests/test_agent_controller.py::TestRunQualityGates::test_run_quality_gates_inconclusive_stamp_does_not_fake_pass PASSED [ 50%]
tests/test_agent_controller.py::TestRunQualityGates::test_run_quality_gates_inconclusive_stamp_prints_warning_to_operator PASSED [ 60%]
tests/test_agent_controller.py::TestRunQualityGates::test_read_pytest_safe_verdict_partial_coverage_is_inconclusive PASSED [ 70%]
tests/test_agent_controller.py::TestRunQualityGates::test_read_pytest_safe_verdict_oserror_detail_has_no_absolute_path PASSED [ 80%]
tests/test_agent_controller.py::TestRunQualityGates::test_read_pytest_safe_verdict_oserror_without_filename_is_safe PASSED [ 90%]
tests/test_agent_controller.py::TestRunQualityGates::test_read_pytest_safe_verdict_jsondecodeerror_detail_unchanged PASSED [100%]

===================== 10 passed, 119 deselected in 0.45s ======================
```

### Verificacion MUTATION (obligatoria)

Se guardo copia del archivo con el fix, se revirtio temporalmente
`.agent/agent_controller.py` al except combinado original (`except (OSError,
json.JSONDecodeError) as exc: ... f"stamp ilegible: {exc}"`), y se corrio de nuevo
el mismo comando. Salida literal (SIN el fix, FAIL esperado y confirmado):

```
        assert result["verdict"] == "inconclusive"
        detail = result["detail"]
        # La ruta absoluta simulada (que vive bajo tmp_path, con o sin
        # segmento de usuario real de esta maquina) no debe aparecer entera.
        assert absolute_path_str not in detail
        assert str(tmp_path) not in detail
        # El username real de quien ejecuta el test tampoco debe colarse.
        assert str(Path.home()) not in detail
        # Debe relativizar a <REPO_ROOT> (stamp_path esta dentro de PROJECT_ROOT).
>       assert "<REPO_ROOT>" in detail
E       assert '<REPO_ROOT>' in "stamp ilegible: [Errno 13] Permission denied: 'C:\\\\Users\\\\fdl\\\\Proyectos_Python\\\\orquestador_de_agentes\\\\tests\\\\sandbox\\\\test_runtime\\\\session_24700\\\\factory\\\\test_read_pytest_242c851d0002\\\\.agent\\\\runtime\\\\pytest-safe\\\\last-run.json'"

tests\test_agent_controller.py:550: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_agent_controller.py::TestRunQualityGates::test_read_pytest_safe_verdict_oserror_detail_has_no_absolute_path
================= 1 failed, 9 passed, 119 deselected in 0.45s ======================
```

Confirmado: sin el fix, la ruta absoluta completa (incluyendo el username real
`fdl` de esta maquina, arrastrado por `Path.home()` via el tmp_path del sandbox
de pytest) reaparece integra en `detail`. El test de regresion NO es un placebo:
distingue correctamente el codigo roto del codigo arreglado.

Se restauro el fix (`.agent/agent_controller.py` identico al diff citado en PASO
1) y se corrio el mismo comando una tercera vez. Salida literal (CON el fix
restaurado, PASS confirmado):

```
tests/test_agent_controller.py::TestRunQualityGates::test_read_pytest_safe_verdict_oserror_detail_has_no_absolute_path PASSED [ 80%]
tests/test_agent_controller.py::TestRunQualityGates::test_read_pytest_safe_verdict_oserror_without_filename_is_safe PASSED [ 90%]
tests/test_agent_controller.py::TestRunQualityGates::test_read_pytest_safe_verdict_jsondecodeerror_detail_unchanged PASSED [100%]

===================== 10 passed, 119 deselected in 0.37s ======================
```

Los 7 tests YA existentes de `TestRunQualityGates` (incluyendo
`test_read_pytest_safe_verdict_partial_coverage_is_inconclusive`) siguen en
verde en las 3 corridas: el cambio no rompio nada preexistente.

### Gates de calidad (post-restauracion del fix)

`.venv\Scripts\python.exe -m ruff check .agent/agent_controller.py tests/test_agent_controller.py`:

```
All checks passed!
```

Exit: 0

`.venv\Scripts\python.exe -m ruff format --check .agent/agent_controller.py tests/test_agent_controller.py`:

```
2 files already formatted
```

Exit: 0

`.venv\Scripts\python.exe .agent/agent_controller.py --validate --json --project-root .`
(diagnostico local, no es gate del Builder): `total_errors: 0, total_warnings: 1`
(el mismo TP-PROSE-04 ya aceptado; sin cambios).

### Pendiente (fuera de este turno del Builder, segun instrucciones explicitas)

NO se ejecuto `scripts/run_pytest_safe.py` (suite canonica completa) ni
`--pre-handoff`/`--mark-ready`: las instrucciones de este turno indican
explicitamente que la suite completa la coordina el Orquestador en el cierre
tras la Review, y que el commit lo decide el Orquestador. Cambios dejados
STAGED (no commiteados): `.agent/agent_controller.py`,
`tests/test_agent_controller.py`.

**Estado:** READY_FOR_REVIEW (Builder)


Scope override: Over-captura del scope gate por baseline anterior. Los AUDIT/PLAN de 015p aparecen porque el commit de cierre del bus c687e38 los BORRA (archivados a _archive gitignored), no son contenido de 019b. Los otros 10 paths (016y/016z AUDIT/PLAN, archive/observations.2026-07.jsonl, los 3 targets de 015p ya en 5df5c5b, conftest, test_motor_git_identity_barrier) son de tickets ya cerrados en sesiones/commits previos, verificado con git show --name-only b0d8d7b c687e38: NO estan en los 2 commits de 019b. El unico codigo productivo de 019b es agent_controller.py (fix del except) + tests/test_agent_controller.py. 'missing: json.JSONDecodeError' es el bug de parser FLT (texto del work_plan leido como path), inofensivo.. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-015p.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016y.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016z.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-015p.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-016y.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-016z.md, <REPO_ROOT>/.agent/runtime/memory/archive/observations.2026-07.jsonl, <REPO_ROOT>/.claude/rules/01-security-architecture.md, <REPO_ROOT>/json.JSONDecodeError, <REPO_ROOT>/prompts/audit_agent_output.md, <REPO_ROOT>/skills/secure-existing-project/SKILL.md, <REPO_ROOT>/tests/conftest.py, <REPO_ROOT>/tests/unit/test_motor_git_identity_barrier.py

Manager approved canonical closeout for WOT-2026-019b