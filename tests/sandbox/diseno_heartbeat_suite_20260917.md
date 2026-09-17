# DISENO: captura incremental del estado de la suite (INSTR-LOG, ampliado)

Fecha: 2026-09-17. Motor `_dev` HEAD `5c2eefc`. Estado: DISENO con probe ejecutado.
Origen: peticion del operador -- *"que la suite vaya guardando la evolucion cada poco
espacio en lugar de hacerlo todo al final"*.

---

## 0. EL PROBLEMA, EN UNA LINEA

Todo lo que la suite sabe de si misma se escribe **al final**, y las corridas que nos
interesan **no llegan al final**.

Medido hoy:
- `last-run.log`: UNA sola `write_text` en un `finally` (`stream_pytest:975`). Tras matar dos
  corridas de ~19 min de CPU, el log seguia intacto: **1372 bytes de un focal anterior**.
- `tests/conftest.py`: su unico hook de sesion es `pytest_sessionfinish` (`:296`) -- el hook
  que por definicion no corre cuando el proceso muere.
- Las 9 filas `aborted` traen `top_slowest: []`, `passed: None`, `errors: None`. **Cero nodeids.**

Resultado: 6+ muertes de `--level all` sin **una sola linea** de que test se ejecutaba.

---

## 1. POR QUE NO BASTA "escribir el log incremental"

Es el primer instinto y es insuficiente. Medido:

- Con `-q` (lo que usa el runner hoy) cada test es **un punto sin nombre**: aunque volcaramos
  el stdout linea a linea, no sabriamos QUE test corria.
- Con `-v` hay nodeid, pero la linea se emite **cuando el test TERMINA** (`... PASSED`). El
  test que empieza y muere **no aparece nunca**. Es justo el que buscamos.

**Corolario (GLM5.2-H5): un log incremental que solo registre FINALES pasa un DoD ingenuo y
sigue perdiendo al culpable.** Hay que registrar el **INICIO**.

---

## 2. EL MECANISMO: hooks de protocolo de pytest + heartbeat append-only

Tres hooks, todos en `tests/conftest.py`, escribiendo NDJSON con `flush()` + `os.fsync()`:

| hook | cuando corre | que ancla |
|---|---|---|
| `pytest_collection_finish` | tras recolectar, ANTES del 1er test | denominador real + marcador de arranque |
| `pytest_runtest_logstart` | **ANTES** de cada test | el nodeid en curso (**el culpable**) |
| `pytest_runtest_logreport` | al terminar cada fase | outcome + duracion por test |

**El discriminante es estructural, no heuristico:** el ultimo nodeid con `start` y **sin**
`end` es el test en el que murio la corrida.

### PROBE EJECUTADO (control positivo, no diseno teorico)
Fixture con dos tests; el segundo duerme 30 s; se mata pytest a los 8 s (`timeout 8`).
`command:` `timeout 8 python -m pytest tests -q -p no:cacheprovider` -> matado.
Heartbeat resultante, LITERAL:
```json
{"ev":"collected","n":2,"t":1789677380.468}
{"ev":"start","nodeid":"tests/test_probe.py::test_rapido","t":1789677380.469}
{"ev":"end","nodeid":"tests/test_probe.py::test_rapido","outcome":"passed","dur":0.000}
{"ev":"start","nodeid":"tests/test_probe.py::test_lento_que_moriria","t":1789677380.474}
```
**El culpable queda senalado por AUSENCIA de su `end`.** Esto es exactamente lo que hoy falta.

---

## 3. TRES CANALES, NO UNO (el log es solo el DONDE)

El log dice DONDE murio. No dice POR QUE ni QUIEN. Canales complementarios:

### C1 -- Heartbeat de tests (seccion 2). Responde: **DONDE**.
### C2 -- Muestreo de entorno periodico. Responde: **EN QUE CONDICIONES**.
Un hilo demonio que cada ~30 s anexa al mismo NDJSON: RAM libre, nº de procesos, entradas
del arbol, PID vivo. Hoy `environment_at_start` existe pero es **una sola foto al arrancar**
(22 de 500 filas la tienen): no puede mostrar una tendencia hacia la muerte.
### C3 -- Los 4 campos de Pieza B. Responde: **QUIEN/COMO** (y permite contar las muertes).
`reconciled_at`, `reconciled_reason`, `lock_pid`, `assumed_dead` existen en codigo y no se
pueblan (**0 de 9 filas**). Sin ellos **el conteo de muertes no es re-derivable**, y hay un
fantasma PROBADO: la fila de 15:18:35 declara muerta una corrida cuyo pid siguio vivo ~90 min.

---

## 4. LO QUE YA MEDIMOS Y ORIENTA EL DISENO

- **Exit codes**: `0x40010004` = `DBG_TERMINATE_PROCESS` (terminado por un DEPURADOR) en 3
  corridas `all` (27-ago, 3-sep, 6-sep). **El forense nunca lo analizo** (0 hits en sus 250
  lineas). El heartbeat debe registrar el exit code CRUDO, sin normalizar a 0..5.
- **WER/Event Viewer**: 0 eventos en la ventana de las muertes. Ausencia informativa: un crash
  nativo habria dejado entrada. Coherente con terminacion externa limpia.

---

## 5. COSTE Y RIESGOS (declarados, no minimizados)

- **Coste de I/O**: 3 escrituras pequenas por test x 6495 tests. `flush()` siempre; `fsync()`
  solo en `collection_finish` y cada N tests -- un `fsync` por test sobre 6495 es medible y
  debe barrerse ANTES de adoptar, contra la mediana de 704 s.
- **Path por corrida (sufijo PID), no por repo**: con `--force-unlock` sin arreglar, dos
  corridas vivas son el modo OPERATIVO esperado; un fichero compartido se entrelaza.
- **Muerte en fase de coleccion**: la cubre `pytest_collection_finish`; sin ese marcador el
  heartbeat quedaria vacio y seria indistinguible de "no arranco".
- **NO sustituye a `last-run.log`**: es un canal nuevo, append-only. No se toca el existente.

## 6. DoD (invariantes, no mediciones)
1. Matar una corrida viva -> el heartbeat contiene un nodeid con `start` y sin `end`.
2. Matar durante la coleccion -> el heartbeat contiene el marcador de coleccion.
3. Dos corridas vivas simultaneas -> cada una deja su heartbeat integro, sin entrelazar.
4. El exit code crudo queda registrado sin normalizar.
5. Delta de duracion sobre la suite completa, medido y declarado antes de adoptar.
