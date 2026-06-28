# Varianza de Suite y Regla Foreground/Background — WOT-2026-010p

> Origen: durante `WOT-2026-010o` se confundio tiempo de espera operativa del
> agente en modo background con tiempo real de pytest. Este reporte mide la
> varianza real entre corridas consecutivas y establece la regla operacional.

## Comando exacto

```
python scripts/run_pytest_safe.py --level all -- --durations=50
```

Ejecutado desde `repo_motor`.
Arbol limpio al momento de medir (HEAD `849e7d52`, post-cierre de
`WOT-2026-010q`). Corridas consecutivas sin concurrencia externa conocida.

## Corrida 1

- **Wall-clock total:** `5m34s` (`334.29s` reportados por pytest)
- **Resultado pytest:** `2913 passed, 20 skipped`
- **exit_code:** `0`
- **tested_commit_sha:** `849e7d52d4153a4904beb812f171c3281acccabb`
- **level:** `all`
- **args_mode:** `default_discovery`

### Top slowest durations (Corrida 1)

| Rank | Duracion | Test |
|------|----------|------|
| 1 | 73.96s | `test_project_scanner.py::TestScanProjectRealProject::test_scan_current_project` |
| 2 | 69.79s | `test_detect_version.py::TestVersionDetection::test_upgrade_path_suggestion` |
| 3 | 25.80s | `test_project_map_freshness.py::TestUpdateScriptExecution::test_script_runs_cleanly` |
| 4 | 23.61s | `test_no_inline_ticket_regex.py::test_no_inline_ticket_regex` |
| 5 | 20.03s | `test_supervisor.py::test_relaunch_uses_resume_flag` |
| 6 | 20.03s | `test_supervisor.py::test_relaunch_seam_allows_monkeypatch_without_pytest_check` |
| 7 | 3.65s (teardown) | `test_work_plan_schema.py::test_deliverable_type_with_extra_spaces` |

**Top-6 outliers (excluyendo teardown):**
`73.96 + 69.79 + 25.80 + 23.61 + 20.03 + 20.03 = 233.22s` de `334.29s`
totales → **~69.8%** del tiempo en **6 de 2933 tests (0.20% de la suite)**.

## Decision: segunda corrida

Primera corrida: `5m34s` → **bajo 10 minutos** → se ejecuta segunda corrida.

## Corrida 2

- **Wall-clock total:** `5m29s` (`329.30s` reportados por pytest)
- **Resultado pytest:** `2913 passed, 20 skipped`
- **exit_code:** `0`
- **tested_commit_sha:** `849e7d52d4153a4904beb812f171c3281acccabb`
- **level:** `all`
- **args_mode:** `default_discovery`

### Top slowest durations (Corrida 2)

| Rank | Duracion | Test |
|------|----------|------|
| 1 | 74.48s | `test_project_scanner.py::TestScanProjectRealProject::test_scan_current_project` |
| 2 | 67.91s | `test_detect_version.py::TestVersionDetection::test_upgrade_path_suggestion` |
| 3 | 27.12s | `test_project_map_freshness.py::TestUpdateScriptExecution::test_script_runs_cleanly` |
| 4 | 23.51s | `test_no_inline_ticket_regex.py::test_no_inline_ticket_regex` |
| 5 | 20.03s | `test_supervisor.py::test_relaunch_seam_allows_monkeypatch_without_pytest_check` |
| 6 | 20.03s | `test_supervisor.py::test_relaunch_uses_resume_flag` |
| 7 | 3.73s (teardown) | `test_work_plan_schema.py::test_deliverable_type_with_extra_spaces` |

## Comparacion entre corridas

| Metrica | Corrida 1 | Corrida 2 | Delta absoluto | Delta % |
|---------|-----------|-----------|----------------|---------|
| Wall-clock total | 5m34s (334.29s) | 5m29s (329.30s) | -4.99s | -1.5% |
| Tests pasados | 2913 | 2913 | 0 | 0% |
| Tests saltados | 20 | 20 | 0 | 0% |

### Comparacion de top outliers

| Test | C1 | C2 | Delta |
|------|----|----|-------|
| `test_scan_current_project` | 73.96s | 74.48s | +0.52s (+0.7%) |
| `test_upgrade_path_suggestion` | 69.79s | 67.91s | -1.88s (-2.7%) |
| `test_script_runs_cleanly` | 25.80s | 27.12s | +1.32s (+5.1%) |
| `test_no_inline_ticket_regex` | 23.61s | 23.51s | -0.10s (-0.4%) |
| `test_relaunch_uses_resume_flag` | 20.03s | 20.03s | 0.00s (0%) |
| `test_relaunch_seam_*` | 20.03s | 20.03s | 0.00s (0%) |

## Comparacion con baseline WOT-2026-010j

| Metrica | 010j (baseline) | 010p C1 | 010p C2 |
|---------|----------------|---------|---------|
| Wall-clock total | 8m1s (479.12s) | 5m34s (334.29s) | 5m29s (329.30s) |
| Tests recolectados | 2922 | 2933 | 2933 |
| Top outlier #1 | 162.29s | 73.96s | 74.48s |
| Top outlier #2 | 61.99s | 69.79s | 67.91s |

La reduccion de ~8min a ~5m30s entre 010j y 010p se explica principalmente
por la caida del outlier #1 de 162.29s a ~74s. Esta es una mejora de ~88s
en un solo test. No se introdujo ninguna optimizacion de suite en este
intervalo: el cambio es probable mejora de estado del sistema operativo/cache
de disco entre sesiones, o varianza natural de un test que hace escaneo real
del arbol de archivos.

## Clasificacion de la conclusion

**Categoria: `entorno/I-O`**

Justificacion:
- Los 6 outliers principales son estables entre corridas consecutivas (delta
  <5% en todos los casos).
- El coste dominante sigue siendo escaneo de arbol de archivos real:
  `test_scan_current_project` (~74s) y `test_upgrade_path_suggestion` (~68s)
  suman ~142s de ~330s totales (~43% del tiempo en 2 tests de 2933).
- La varianza de total entre C1 y C2 es de solo 4.99s (-1.5%), lo que indica
  suite estable en condiciones de foreground consecutivo.
- No hay tests inestables visibles (ninguno aparece fuera del top-6 en C1 y
  desaparece en C2 o viceversa).
- La diferencia C1/C2 entra dentro del ruido normal de I/O del sistema
  operativo; no hay hotspot nuevo ni regresion.

## Nota sobre el incidente WOT-2026-010o (background vs foreground)

Durante `010o` se observo una duracion aparente de ~43 minutos para la suite.
La causa fue que la herramienta se ejecuto en modo background (`run_in_background`)
y solo reporta la salida al completarse; el agente interpreta el tiempo de
espera como duracion de pytest. El tiempo real de la suite es ~5m30s, como
confirman las dos corridas de este ticket.

Regla operacional documentada en `INTERACTION_MODES.md`:
suites con duracion esperada menor de 10 minutos van en foreground;
background solo se usa con progreso verificable (p.ej. Monitor task o
archivo de salida explicito).
