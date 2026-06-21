# Baseline de Performance de Suite — WOT-2026-010j

> Origen: la suite canonica del motor tiene latencia suficiente para degradar
> el feedback Builder/Manager y no existia baseline reproducible. Este reporte
> mide antes de cambiar gates, selector focal o paralelizacion.

## Comando exacto y contexto de ejecucion

```
python scripts/run_pytest_safe.py --level all -- --durations=50
```

- Ejecutado desde `repo_motor` (`C:\Users\***REDACTED***\Proyectos_Python\orquestador_de_agentes`).
- Arbol limpio al momento de medir (sin cambios productivos en curso fuera del
  packet de `010j`).
- Suite corrida sola, sin concurrencia externa conocida.

## VERIFICADO: resultado de la corrida

- **Exit code real:** `0` (leido de `.agent/runtime/pytest-safe/last-run.json`,
  campo `exit_code`; no tomado del pipe de consola, que puede enmascarar el
  codigo real de pytest).
- **Estado:** `status: finished`, `level: all`.
- **Resultado pytest:** `2902 passed, 20 skipped in 479.12s (0:07:59)`.
- **Tiempo total wall-clock:** `8m0.606s` (medido con `time`; incluye overhead
  del wrapper `run_pytest_safe.py` sobre los `479.12s` reportados por pytest).
- **Tests recolectados:** `2922` (2902 passed + 20 skipped).

## VERIFICADO: top tests mas lentos (de `--durations=50`)

| Rank | Duracion | Test | Tipo de coste |
|------|----------|------|----------------|
| 1 | 162.29s | `test_project_scanner.py::TestScanProjectRealProject::test_scan_current_project` | Escaneo de arbol de archivos real (`scan_project` sobre el repo completo). Docstring propia: "Marked as slow because it scans the entire project tree." |
| 2 | 61.99s | `test_no_legacy_topology_terms.py::test_repo_has_no_live_retired_topology_terms` | `Path.rglob("*")` sobre todo `PROJECT_ROOT` + lectura de contenido por archivo. Filesystem real, no subprocess. |
| 3 | 59.22s | `test_detect_version.py::TestVersionDetection::test_upgrade_path_suggestion` | Cuerpo del test es trivial (3 asserts sobre `suggest_upgrade_path`); el coste no es atribuible a logica propia visible. Inferencia: setup costoso de la clase/modulo atribuido por pytest al primer test que lo dispara, o ruido de medicion de una sola corrida. No confirmado con `--durations` por test aislado; queda como observacion abierta, no como hallazgo cerrado. |
| 4 | 27.34s | `test_project_map_freshness.py::TestUpdateScriptExecution::test_script_runs_cleanly` | Usa `subprocess` (2 ocurrencias en el archivo) — candidato real a coste subprocess. |
| 5 | 26.34s | `test_no_inline_ticket_regex.py::test_no_inline_ticket_regex` | Escaneo de texto/regex sobre arbol de archivos, sin subprocess. |
| 6 | 20.04s | `test_supervisor.py::test_relaunch_seam_allows_monkeypatch_without_pytest_check` | Archivo usa `subprocess` (23 ocurrencias) — candidato real a coste subprocess, aunque el test puntual podria estar mockeado. |
| 7 | 20.03s | `test_supervisor.py::test_relaunch_uses_resume_flag` | Mismo archivo que (6); mismo candidato. |

**Resto de la suite (2895 tests restantes del top-50 hacia abajo):** todos
`<1s` por test; el test mas lento fuera del top-7 es `4.48s`
(`test_work_plan_schema.py::test_deliverable_type_with_extra_spaces`, fase
`teardown`).

## VERIFICADO: distribucion de tiempo

- **Top-7 outliers:** `162.29 + 61.99 + 59.22 + 27.34 + 26.34 + 20.04 + 20.03 =
  377.25s` de `479.12s` totales reportados por pytest -> **~78.7%** del tiempo
  de ejecucion concentrado en **7 de 2922 tests (0.24% de la suite)**.
- **Resto de la suite (2915 tests):** `~101.87s` (~21.3% del tiempo) repartido
  de forma difusa, ningun test individual por encima de `4.48s`.

## VERIFICADO: conteos auxiliares (grep sobre `tests/*.py`)

| Categoria | Archivos que la referencian | Metodo |
|-----------|------------------------------|--------|
| `subprocess` | 53 / ~173 archivos de test | `grep -rl "subprocess" tests/ --include="*.py"` |
| `git` (`git`, `git_init`, `GIT_DIR`) | 32 archivos | `grep -rl "\bgit\b\|git_init\|GIT_DIR" tests/ --include="*.py"` |
| Filesystem real (`tmp_path`/`tmpdir`) | 119 archivos | `grep -rl "tmp_path\|tmpdir" tests/ --include="*.py"` |
| Controller/bus (`agent_controller`, `bus`) | 185 archivos | `grep -rl "agent_controller\|from bus\|import bus" tests/ --include="*.py"` |
| Marca `integration` | 5 / 2922 tests | `pytest --collect-only -q -m "integration"` |
| Marca `slow` | 1 / 2922 tests | `pytest --collect-only -q -m "slow"` |

Nota de metodo: los conteos de `subprocess`/`git`/filesystem/controller son
**conteo de archivos que contienen la referencia textual**, no de tests
individuales ni de tiempo de ejecucion atribuido. Es un proxy estructural, no
una medicion de coste. Se etiqueta como tal para evitar cristalizar un grep
parcial como hecho de performance.

## Hipotesis subprocess/git: REFUTADA como causa dominante

La hipotesis previa al ticket (coste dominante en `subprocess`/`git`) **no se
sostiene** contra la medicion real:

- El test mas lento (`test_scan_current_project`, 162s, 33.9% del tiempo
  total) es escaneo de filesystem, no subprocess ni git.
- El segundo mas lento (`test_repo_has_no_live_retired_topology_terms`, 62s)
  es `rglob` + lectura de archivos, no subprocess ni git.
- Solo 2 de los 7 outliers (`test_project_map_freshness.py`,
  `test_supervisor.py`) referencian `subprocess` en su archivo, y aportan
  juntos `27.34 + 20.04 + 20.03 = 67.41s` (~14% del tiempo total) — bastante
  menos que el escaneo de filesystem real (`162.29 + 61.99 = 224.28s`, ~46.8%).
- 53 archivos contienen la palabra `subprocess`, pero eso es proxy estructural
  (cuantos archivos la usan), no evidencia de que el tiempo de ejecucion este
  ahi. La medicion real muestra lo contrario: el coste esta concentrado en
  **escaneo de arbol de archivos** (`scan_project`, `rglob`), no en llamadas a
  `git`/`subprocess`.

**Conclusion verificada:** el cuello de botella dominante de la suite es
**escaneo de filesystem real sobre el repo completo en 2-3 tests
especificos**, no `subprocess`/`git` de forma difusa. La sospecha original
(documentada como INFERENCIA en `work_plan.md`) queda **refutada** como causa
principal; sigue siendo un contribuyente menor (~14%) pero no el dominante.

## Clasificacion de propuestas

| Categoria | Aplicable aqui | Evidencia |
|-----------|-----------------|-----------|
| Quick win de test puntual | **Si** — marcar/optimizar los 2-3 tests de escaneo de filesystem (162s + 62s + posiblemente 59s sin explicar) | Top-3 ya suma ~284s de 479s (~59%) |
| Cambio de fixtures | Parcial — los 2 tests de `subprocess` en `test_supervisor.py`/`test_project_map_freshness.py` podrian usar fixtures mas baratas si no validan subprocess real como contrato | 67.41s en 3 tests |
| Cambio de politica de gates | No recomendado todavia — el coste no esta en `integration`/`slow` (solo 6 tests combinados); excluirlos no resuelve el cuello real | 5+1 de 2922 tests marcados |
| Paralelizacion/CI | Posible pero de bajo impacto si no se resuelve antes el top-3, que es secuencial por naturaleza (un solo `rglob` no se beneficia de xdist salvo que se paralelice entre tests, no dentro del test) | Top-3 = 1 test cada uno, no se dividen con xdist |

## Recomendacion del siguiente ticket ejecutable

**Hipotesis evaluada:** "el coste dominante de la suite es subprocess/git" ->
**REFUTADA**. El coste dominante real es escaneo de filesystem en 2-3 tests
puntuales (`test_scan_current_project`, `test_repo_has_no_live_retired_topology_terms`,
posiblemente `test_upgrade_path_suggestion`).

**Metrica observada:** top-3 tests = ~284s de 479s totales (~59% del tiempo en
3 de 2922 tests, 0.1% de la suite).

**Criterio de prioridad:** porcentaje de tiempo total atribuible al hotspot
verificado (no a proxy estructural de archivos) y reversibilidad del cambio
propuesto.

**Decision:**

- **WOT-2026-010k** (tal como esta redactado hoy, "reducir coste de tests
  git/subprocess") **se re-scopea**: su premisa de origen ("muchos tests
  unitarios pagan coste de subprocess.run(['git', ...])") no es el hotspot
  dominante segun esta medicion. Antes de ejecutarlo, debe ampliarse o
  redirigirse para cubrir tambien (o principalmente) el coste de escaneo de
  filesystem real (`test_scan_current_project`,
  `test_repo_has_no_live_retired_topology_terms`), que es ~3.3x mayor que el
  coste de subprocess/git verificado (224.28s vs 67.41s).
- **WOT-2026-010l** (selector focal por diff) sigue siendo razonable como
  paso siguiente independiente: no depende de si el coste es git o
  filesystem, ataca "ejecutar menos tests por iteracion", que beneficia
  cualquier hotspot. Prioridad media, no bloqueado por este hallazgo.
- **WOT-2026-010m** (piloto xdist) se mantiene en prioridad baja: el top-3
  hotspot es de un solo test pesado cada uno, no se beneficia de
  paralelizacion intra-test: xdist solo ayudaria si se distribuyen tests
  *entre si*, lo cual no resuelve que un test individual tarde 162s.
- **No se descarta ningun ticket**, pero **WOT-2026-010k requiere ajuste de
  alcance antes de arrancar** para no optimizar un hotspot secundario
  mientras el dominante (filesystem real, 2-3 tests) queda sin tocar.

## Existencia y encoding del artefacto

- Verificado por lectura directa del archivo tras escritura (este mismo
  documento, confirmado via herramienta de lectura del agente).
- `check_encoding_guard.py` ejecutado sobre este archivo: ver `execution_log.md`
  de `WOT-2026-010j` en `repo_destino` para el exit code literal.
