# PLAN - WOT-2026-019c

Ticket: WOT-2026-019c - test flaky en CI shallow clone
(test_loose_pattern_chunks_many_revs, exit 128 de git rev-list --all).
Estado: APPROVED
delivery_authority: repo_motor | deliverable_type: code

Este documento es la estrategia tecnica breve del ticket; el contrato
completo (Files Likely Touched, DoD por paso, STOP conditions, Criterios de
Aceptacion Global) vive en work_plan.md. Si algo difiere entre ambos,
work_plan.md manda.

## Resumen del problema

CI (`Quality Gates`, job `quality-gates (3.11)`) fallo dos veces
(2026-07-04 run 28692691463, 2026-07-05 run 28755232843) con traceback
identico:
`subprocess.CalledProcessError: Command ['/usr/bin/git', 'rev-list', '--all']
returned non-zero exit status 128`, `stderr`: `error: Could not read
8c5ad02d1e80a65e407934c4035d5c17b704bb0b` / `fatal: Failed to traverse
parents of commit 8ed1dbf116f0ee3a361da7fedd0096fd5ded8b3f`. El traceback
real (obtenido con `gh run view <id> --log-failed`) ubica el fallo en
`scripts/classify_publication.py:482` (`_collect_history_blob_paths`),
llamado desde `check_classify` (`scripts/check_publication_gate.py:89`),
NO en `check_loose_pattern` como sospechaba la ficha original. El `cwd` del
proceso fallido es el repo fixture ANIDADO creado por
`_make_repo(tmp_path, "repo_grande")` dentro de
`test_loose_pattern_chunks_many_revs` (485 commits en bucle), no el
checkout del runner.

## Decision de diseno elegida: Opcion (B), descartada Opcion (A)

**Opcion (A) descartada** (`fetch-depth: 0` en `quality-gates.yml`):
reproduccion local de un clon `--depth=1` del propio motor con
`tmp_path` de longitud normal -> `8 passed in 23.60s`, CERO fallos. El
`cwd` del proceso que falla en CI es el repo fixture (no el checkout
padre); `_run_git`/`_git_lines` corren con `cwd=repo_root` explicito sin
heredar working-tree del padre; ningun workflow invoca estos scripts sobre
el checkout real de CI. `fetch-depth: 0` no tiene ningun camino de codigo
que pueda tocar este bug.

**Opcion (B) elegida**: la causa real, consistente con la evidencia (un
SHA que `rev-list --all` lista en su propio stdout resulta ilegible acto
seguido, "Could not read"), es una condicion de carrera con `git gc --auto`
(disparado en background por defecto en Linux, `gc.autoDetach=true`)
durante los 485 `git commit -q` en bucle del test, solapandose con las 2
lecturas de historial completo (`check_classify`, `check_loose_pattern`)
que corren justo despues. El fix anade `_git(repo, "config", "gc.auto",
"0")` en `_make_repo` (`tests/test_check_publication_gate.py`)
inmediatamente tras `git init`, cerrando la ventana de carrera de forma
hermetica (no depende de shallow/fetch-depth ni de la ubicacion del
checkout padre).

## Estrategia (2 pasos IMPLEMENT + 1 VERIFY)

1. `tests/test_check_publication_gate.py::_make_repo`: anadir
   `_git(repo, "config", "gc.auto", "0")` tras `git init`. Los 7 tests
   existentes que usan el helper heredan el fix sin cambiar su codigo.
2. Anadir `test_make_repo_disables_autogc` (test determinista que verifica
   el MECANISMO del fix -- `git config --get gc.auto` devuelve `"0"` en el
   repo creado -- no el sintoma de CI, que es irreproducible localmente).
   Mutation check: comentar la linea del fix, confirmar que el test nuevo
   FALLA; restaurar y confirmar que pasa.
3. Verificacion: pytest del archivo completo (9 tests), ruff
   check/format --check, suite canonica `run_pytest_safe.py`. El cierre
   real (barrera CI-only, PENDIENTE-POST-PUSH) es que el siguiente run de
   `Quality Gates` en GitHub Actions termine en `conclusion: success` tras
   el push.

## Archivos tocados

- `tests/test_check_publication_gate.py` (`_make_repo`: `gc.auto=0`; test
  nuevo `test_make_repo_disables_autogc`)

## Read/inspect only

`scripts/check_publication_gate.py` y `scripts/classify_publication.py`
(fuente de los checks que fallan; NO se tocan, el fix es solo del
fixture de test), `tests/conftest.py` (fuente de `tmp_path`
anidado/`ProjectTmpPathFactory`; confirma el path de CI pero NO se
modifica), `.github/workflows/quality-gates.yml` y
`.github/workflows/security-audit.yml` (Opcion A descartada, NO se
tocan).

## Criterios de cierre

Identicos a work_plan.md seccion "Criterios de Aceptacion Global". No
duplicados aqui para evitar deriva; ver work_plan.md como fuente unica de
los comandos exactos. Incluye el criterio PENDIENTE-POST-PUSH (run verde
de CI tras el push).
