# Execution Log - WOT-2026-019d

Ticket: WOT-2026-019d - Inventario y correccion de los ~18 usos de
str(exc)/{exc}/{e} en .agent/agent_controller.py con clasificacion PII
(follow-up de WOT-2026-019b).
**Estado:** COMPLETED

## Bitacora

- Plan creado y aprobado por el Manager. Fase 0 (Orquestador) verifico la
  premisa del ticket contra el estado real del repo antes de bootstrapear:
  - grep -nE del patron str(exc)/{exc}/{e}/str(e) en
    .agent/agent_controller.py confirma 18 lineas: 894, 900, 1007, 1041,
    1085, 1614, 1688, 1888, 1910, 2039 (comentario), 2049 (ya corregida por
    019b), 2219, 2890, 2891, 3459, 5342, 5895, 5925.
  - Clasificacion definitiva (leyendo cada bloque try/except completo, no
    solo la tabla preliminar de la ficha): 12 PII-riesgo (900, 1007, 1041,
    1085, 1888, 1910, 2219, 2890, 2891, 5342, 5895, 5925) y 4 seguros (894,
    1614, 1688, 3459). Ver tabla completa en work_plan.md.
  - Correcciones a la clasificacion preliminar de la ficha: 1614
    reclasificada de RIESGO a SEGURO (extract_paths_from_work_plan es
    parsing puro de string); 1910 identificada como RIESGO adicional no
    cubierto por la ficha original (Path.exists() puede re-lanzar OSError
    segun _ignore_error de pathlib).

## Implementacion (Builder + correcciones del Orquestador)

- Builder aplico el patron de 019b a los 12 sitios PII-riesgo de
  .agent/agent_controller.py: separar `except OSError as exc` ANTES del
  `except Exception` existente, componer el detail a mano con
  `exc.strerror + exc.errno + scope_gate._relativize_scope_path(exc.filename,
  PROJECT_ROOT)` (guard para filename=None), preservando el prefijo original
  del mensaje. 2890/2891 comparten un unico bloque OSError. Los 4 sitios
  SEGURO (894, 1614, 1688, 3459) llevan un comentario de una linea citando
  WOT-2026-019d. 11 bloques `except OSError` fisicos cubren los 12 sitios.
- Builder anadio 11 tests de regresion en tests/test_agent_controller.py,
  clase `TestPiiSafeExceptionSites` (2890/2891 comparten un test, documentado).
  Cada test monkeypatchea el I/O concreto del sitio para lanzar OSError con
  exc.filename = ruta absoluta bajo tmp_path y asegura via helper
  `_assert_no_pii_leak` que el output no filtra la ruta ni el username.

## Hallazgos del Orquestador en la verificacion (regla dura: re-mutation propia)

- HALLAZGO 1 (false-green corregido): la primera version de las aserciones
  (`assert absolute_path_str not in output`) era FALSE-GREEN en Windows:
  `str(OSError(errno, strerror, filename))` renderiza el filename con
  backslashes DOBLES, asi que la comparacion literal contra la ruta de
  backslash-simple no matcheaba AUNQUE la ruta con username SI estuviera en el
  output. Verificado mutando 2 sitios: sus tests seguian pasando sin el fix.
  Devuelto al Builder; corregido con el helper `_assert_no_pii_leak`, que (a)
  normaliza `output.replace(backslash-doble, backslash-simple)` antes de
  comparar la ruta y (b) asegura ademas que el `marker` sin separadores
  (tmp_path.name, equivalente al username) no aparece -> inmune al
  doble-backslash.
- HALLAZGO 2 (BUG REAL de codigo destapado por la barrera corregida): el sitio
  1888 (_validate_contract_gap_coherence, bus read) tenia
  `except ZeroDivisionError as exc` en vez de `except OSError as exc` (typo del
  Builder). Con ese typo, el OSError real NO entraba en la rama segura y caia
  al `except Exception` generico que emitia `str(exc)` con ruta+username. El
  test de ese sitio (barrera ya valida) FALLABA correctamente destapandolo.
  Corregido por el Orquestador (una palabra: ZeroDivisionError -> OSError).
  Auditados los otros 10 bloques: sin mas typos de clase de excepcion.

## Mutation-verify (re-corrido por el Orquestador, no por el reporte del Builder)

- Mutation masivo: deshabilitar TODAS las ramas OSError anadidas
  (`except OSError` -> `except (ValueError,)`, que no captura OSError) hace que
  los 11 tests de `TestPiiSafeExceptionSites` FALLEN (11 failed). Restaurado el
  codigo -> 11 passed. Barreras validas (matan la mutacion).
  - Comando: `python -m pytest tests/test_agent_controller.py -k PiiSafe`
  - Sin fix (OSError deshabilitado): 11 failed. Con fix: 11 passed.
- Gates: `ruff check` -> All checks passed. `ruff format` aplicado (1 file
  reformatted). Encoding: 0 caracteres no-ASCII en lineas nuevas (verificado
  por script Python sobre el diff).


Scope override: Over-captura de artefactos de tickets YA CERRADOS (015p/016y/016z/019b AUDIT/PLAN, docs de 015p, observations archive). Verificado con git show --name-only 6a4469c bb74854: 019d solo toco agent_controller.py + tests/test_agent_controller.py + sus propios artefactos + archivado de PLAN/AUDIT de 019b (churn de cierre). Ninguno de los 10 archivos ajenos esta en mis commits (0 hits).. Affected files: <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-015p.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016y.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-016z.md, <REPO_ROOT>/.agent/collaboration/AUDIT_WOT-2026-019b.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-015p.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-016y.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-016z.md, <REPO_ROOT>/.agent/collaboration/PLAN_WOT-2026-019b.md, <REPO_ROOT>/.agent/runtime/memory/archive/observations.2026-07.jsonl, <REPO_ROOT>/.claude/rules/01-security-architecture.md, <REPO_ROOT>/prompts/audit_agent_output.md, <REPO_ROOT>/skills/secure-existing-project/SKILL.md

Manager approved canonical closeout for WOT-2026-019d