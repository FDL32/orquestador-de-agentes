# Follow-up de Performance de Suite — WOT-2026-010k

> Origen: `WOT-2026-010j` midio la suite real y confirmo dos hotspots
> dominantes de filesystem real (no `git/subprocess`): `test_scan_current_project`
> (`162.29s`) y `test_repo_has_no_live_retired_topology_terms` (`61.99s`),
> ~46.8% del tiempo total. Este ticket ataca esos dos hotspots con cambios
> locales y conservadores, sin tocar runner, CI, cache, selector focal ni
> politica de gates.

## Hotspot 1 — `test_scan_current_project`

### Diagnostico

`scan_project(project_root)` se invocaba **dos veces completas** sobre el
arbol real solo para comparar `result == result2` y confirmar determinismo
(`tests/unit/test_project_scanner.py`, linea 507 antes del fix). Esa
propiedad de determinismo ya esta cubierta de forma barata por
`test_scan_project_deterministic` (linea 397), que la verifica contra una
fixture sintetica de 3 archivos en `tmp_path`. Repetir el escaneo real
completo en `test_scan_current_project` duplicaba el coste de I/O sin anadir
cobertura nueva.

### Cambio

- Se elimino la segunda llamada `scan_project(project_root)` y la
  comparacion `result == result2` de `test_scan_current_project`.
- Se preservaron intactas todas las aserciones de contenido real (numero de
  archivos, categorias, `importMap`), que son el contrato observable real
  del test: que el escaneo del repo real produce un resultado con sentido.
- No se toco `scan_project` ni `scripts/project_scanner.py`: el cambio es
  estrictamente del test.

### Medicion before/after

Comando exacto (mismo entorno local, mismo commit base salvo el diff del
ticket):

```
python -m pytest tests/unit/test_project_scanner.py::TestScanProjectRealProject::test_scan_current_project -v -m slow
```

| Momento | Tiempo |
|---------|--------|
| Before | `133.36s` |
| After | `52.73s` |
| Delta | `-80.63s` (`-60.5%`) |

## Hotspot 2 — `test_repo_has_no_live_retired_topology_terms`

### Diagnostico

El test usaba `PROJECT_ROOT.rglob("*")` y filtraba por `_is_excluded`
**despues** de enumerar cada entrada. `Path.rglob` no soporta poda: aunque
`EXCLUDED_PARTS` incluye `"sandbox"`, `rglob` igual desciende y enumera
`tests/sandbox/test_runtime/` completo antes de descartarlo. Medicion
aislada confirmo que ese subarbol por si solo contiene **383,706 entradas**
acumuladas de sesiones de test previas, contra solo **518 archivos** reales
que sobreviven el filtro — es decir, >99.8% del trabajo de enumeracion se
descartaba sin usarse.

### Cambio

- Se sustituyo `PROJECT_ROOT.rglob("*")` por un nuevo helper
  `_iter_candidate_files(root)` basado en `os.walk` con poda in-place
  (`dirnames[:] = [d for d in dirnames if d not in EXCLUDED_PARTS]`), que
  evita descender a los directorios excluidos en vez de enumerarlos y
  descartarlos despues.
- `_is_excluded(relative_path)` se mantiene como segundo filtro tras la
  poda, porque cubre `EXCLUDED_PATHS` (archivos exactos como
  `CHANGELOG.md`), que no es podable a nivel de directorio.
- El resto del contrato (extensiones binarias excluidas, lectura de
  contenido real, regex `LEGACY_PATTERN`, mensaje de asercion) no cambio.

### Tests anadidos (smoke sin shortcut)

- `test_iter_candidate_files_smoke_no_shortcut`: compara el resultado de
  `_iter_candidate_files` contra un `rglob("*")` sin poda + filtro
  `_is_excluded` sobre el mismo arbol sintetico, y exige que produzcan
  exactamente el mismo conjunto de archivos. Prueba que la poda es una
  optimizacion de rendimiento, no un cambio de comportamiento.
- `test_iter_candidate_files_does_not_descend_into_excluded_dirs`: usa
  `monkeypatch` para vaciar `EXCLUDED_PARTS` y confirma que, sin la poda,
  el archivo dentro del directorio excluido SI aparece — es decir, prueba
  que la poda (y no otra cosa) es la que mantiene el archivo fuera del
  resultado real.

### Medicion before/after

Comando exacto (mismo entorno local, mismo commit base salvo el diff del
ticket):

```
python -m pytest tests/unit/test_no_legacy_topology_terms.py::test_repo_has_no_live_retired_topology_terms -v
```

| Momento | Tiempo |
|---------|--------|
| Before | `50.01s` |
| After | `0.22s` |
| Delta | `-49.79s` (`-99.6%`) |

## Resumen de impacto combinado

| Test | Before | After | Delta |
|------|--------|-------|-------|
| `test_scan_current_project` | `133.36s` | `52.73s` | `-80.63s` |
| `test_repo_has_no_live_retired_topology_terms` | `50.01s` | `0.22s` | `-49.79s` |
| **Total ambos tests** | `183.37s` | `52.95s` | `-130.42s` (`-71.1%`) |

## No-goals respetados

- No se reabrio la hipotesis `git/subprocess`: ninguno de los dos cambios
  toca codigo de subprocess; ambos eran costes reales de filesystem
  (escaneo redundante y enumeracion sin poda), tal como `010j` ya habia
  caracterizado.
- No se toco `run_gates_dispatch.py`, politica Builder/Manager, cache de
  pytest, selector focal ni paralelizacion/xdist.
- No se relajo cobertura semantica: el mismo conjunto de archivos se analiza
  (verificado por el smoke test), y el escaneo real del repo sigue
  ejecutandose al menos una vez con las mismas aserciones de contenido.
