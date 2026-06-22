# Coste anomalo de `test_upgrade_path_suggestion` -- WOT-2026-013g

> Diagnostico reproducible del unico hotspot `unknown` del inventario de suite
> (`WOT-2026-013e`). Ticket `analysis`: NO toca el test, el producto, el runner
> ni `pytest.ini`. La salida es este reporte + una recomendacion binaria.

## Pregunta

`tests/unit/test_detect_version.py::TestVersionDetection::test_upgrade_path_suggestion`
aparecio como outlier #2-#3 (~59-70s) en las baselines `010j` y `010p`, pese a
tener un cuerpo trivial (instanciar un detector + 6 llamadas a
`suggest_upgrade_path`, una operacion de string pura). `013e` lo dejo como
`unknown`. Aqui se mide para atribuir el coste.

## Anclaje

- **repo_motor HEAD:** `bc658f8` (medicion fresca, no historica).
- **Metodo:** pytest focal con `--durations` + micro-bench directo del seam con
  `time.perf_counter`, en foreground, comandos reproducibles abajo.

## VERIFICADO: el coste esta en `setup`, no en el cuerpo

Medicion 1 -- test focal aislado:

```
python -m pytest tests/unit/test_detect_version.py::TestVersionDetection::test_upgrade_path_suggestion -q --durations=10 -p no:cacheprovider
```

Resultado literal:

```
53.51s setup    ...::test_upgrade_path_suggestion
0.10s  call     ...::test_upgrade_path_suggestion
1 passed in 53.68s
```

**[V]** El cuerpo del test (`call`) cuesta **0.10s**. El coste (~53s) esta
integramente en la fase `setup`, no en la logica del test.

## VERIFICADO: el cuerpo y el constructor del detector son baratos

Medicion 2 -- micro-bench directo (sin pytest):

```
python -c "import time,sys; sys.path.insert(0,'agent_system'); from scripts.detect_version import AgentSystemDetector; \
t0=time.perf_counter(); d=AgentSystemDetector('.'); t1=time.perf_counter(); print(t1-t0); \
t2=time.perf_counter(); [d.suggest_upgrade_path(v) for v in ['v8.x','v9.0-v9.1','v9.2','v9.2.1+','v9.5','v9.6']]; t3=time.perf_counter(); print(t3-t2)"
```

Resultado literal:

- `AgentSystemDetector(".")` `__init__`: **0.048s**
- 6x `suggest_upgrade_path` (el cuerpo del test): **0.0000s**

**[V]** Ni el constructor del detector (que internamente resuelve rutas via
`ProjectPathsResolver`) ni las 6 llamadas del cuerpo explican el coste. La
hipotesis inicial de que `project_dir="."` disparaba un `os.walk` caro del repo
en el constructor queda **REFUTADA**: ese walk existe pero cuesta ~0.05s, no 53s.

## VERIFICADO: el coste se atribuye al PRIMER test de la sesion, no a este test

Medicion 3 -- archivo completo:

```
python -m pytest tests/unit/test_detect_version.py -q --durations=15 -p no:cacheprovider
```

Resultado literal (top):

```
43.90s setup    ...::TestVersionDetection::test_detect_v8x_structures
0.07s  call     ...::test_upgrade_path_suggestion
0.01s  call     ...::test_detect_v8x_structures
... (resto < 0.02s)
15 passed in 44.17s
```

**[V]** Cuando el archivo corre completo, el setup caro (~44s) se atribuye al
**primer test ejecutado** (`test_detect_v8x_structures`), NO a
`test_upgrade_path_suggestion` (cuyo `call` es 0.07s). El test focal solo
aparecia como outlier en `010j`/`010p` porque, en el orden/shard de aquellas
corridas, fue el primer test que materializo el setup de sesion. **No tiene
coste propio.**

## VERIFICADO: la fuente del coste es la purga de sandbox huerfano en conftest

`tests/conftest.py` define un fixture `scope="session", autouse=True`
(`_project_temp_environment`, l.81-85) que en `sessionstart` llama
`_purge_orphan_session_dirs(os.getpid())` (l.57-76, introducido por
`WOT-2026-013d`). Ese helper hace `shutil.rmtree(...)` de cada directorio
`session_<PID>` huerfano bajo `tests/sandbox/test_runtime/`.

**[V]** Estado del sandbox al momento de medir:

```
ls -d tests/sandbox/test_runtime/session_* | wc -l   ->   568
```

568 sandboxes huerfanos de corridas previas. Borrar ese arbol en Windows
(`shutil.rmtree` sobre cientos de miles de entradas acumuladas -- `010k`
ya midio 383,706 entradas en un estado similar) es lo que cuesta ~44-53s, y
pytest lo carga al `setup` del primer test de la sesion.

## Atribucion final

| Componente | Coste | Evidencia |
|------------|-------|-----------|
| Cuerpo del test (`call`) | 0.07-0.10s | [V] M1, M3 |
| `AgentSystemDetector(".")` ctor | 0.048s | [V] M2 |
| Purga de sandbox huerfano (`sessionstart`) | ~44-53s | [V] M1/M3 setup + conteo 568 dirs |

**[V]** >99% del coste observado es la purga de sandbox de `conftest`, una
operacion **de sesion unica** (no por-test), de coste **variable** segun cuanto
sandbox huerfano se haya acumulado. **[I]** El coste es por tanto no
determinista entre maquinas/sesiones: una suite con sandbox limpio no veria este
outlier; una con mucho huerfano acumulado lo veria mayor. Esto explica la
varianza 162s (`010j`) -> ~70s (`010p`) que `010p` atribuyo a "entorno/I-O" sin
identificar la causa: era el volumen de sandbox huerfano pendiente de purga.

## Conclusion binaria: SIN OPTIMIZACION SEGURA en este ticket

**No hay optimizacion local segura aplicable a `test_upgrade_path_suggestion` ni
a `detect_version.py` en esta ronda**, por las siguientes razones [V]:

1. El test no tiene coste propio (0.07s). Optimizarlo no reduce nada.
2. El coste real es la purga de sandbox de `conftest.py`, que es **producto del
   runner/harness** y esta en `Forbidden Surfaces` de este ticket. Tocarla seria
   drift de scope a un ticket de runner.
3. La purga es una **barrera deliberada de `013d`** (higiene de sandbox para
   evitar el crash de escaneo concurrente). Eliminarla o moverla reabriria una
   frontera ya cerrada; no es decision de un follow-up analitico.
4. El coste es de **sesion unica**, no por-test: su peso relativo en la suite
   completa (~44s de ~330-480s) es real pero no recurrente por test, y desaparece
   en una sesion con sandbox ya limpio.

## Recomendacion (follow-up, fuera de 013g)

Si se quisiera atacar este coste, el ticket correcto seria de **higiene de
runner/sandbox**, NO de este test:

- **Candidato [I]:** hacer que `_purge_orphan_session_dirs` sea incremental o
  perezoso (p.ej. limitar cuantos dirs purga por sesion, o purgar en background),
  o programar una limpieza periodica del sandbox fuera del `sessionstart`.
- **Riesgo:** toca `tests/conftest.py` (barrera de `013d`) y la semantica del
  runner Windows-safe. Exige su propio contrato, medicion before/after y respeto
  a la invariante de `tests/unit/test_windows_safe_temp_runtime.py`.
- **Mientras tanto:** correr `python scripts/run_pytest_safe.py --cleanup-only`
  (documentado en `tests/README.md`) antes de medir reduce el outlier sin tocar
  codigo.

`013g` cierra como **`sin optimizacion segura`**: el "outlier" es un artefacto de
atribucion de un coste de higiene de sesion, no un defecto del test ni del
producto. El inventario de `013e` puede reclasificar este `unknown` como
**`structural gate` / coste-de-harness explicado**, no como candidato a poda u
optimizacion de test.

## Reproducibilidad

Todas las mediciones son foreground, con los comandos literales citados arriba,
sobre HEAD `bc658f8`. El conteo de sandbox (`568`) es el estado al medir; al ser
la variable que mueve el coste, una reproduccion exacta del tiempo requiere el
mismo volumen de sandbox huerfano (de ahi la conclusion de no-determinismo).

- Existencia y encoding del artefacto: verificado por lectura tras escritura;
  `check_encoding_guard.py` y `validate` -> ver `execution_log.md` de `013g`.
