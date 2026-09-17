# PROPUESTA DE IMPLEMENTACION: observabilidad de la suite

Fecha: 2026-09-17. Motor `_dev` HEAD `5c2eefc`. Estado: PROPUESTA con probes ejecutados.
Contexto: 6+ muertes de `--level all` en un dia, causa SIN DETERMINAR tras un forense de 250
lineas que refuto 4 hipotesis. La observabilidad esta rota y confirmada en vivo.

**Nomenclatura: `P-B` se renombra a `C1-HEARTBEAT`.** Colisionaba con `Pieza B`
(`_reconcile_dead_run` de WOT-2026-062e), y ambos iban a un Builder en la misma sesion.

---

## 0. EL DEFECTO RAIZ, MEDIDO

Todo lo que la suite sabe de si misma se escribe **al final**, y las corridas que interesan
**no llegan al final**.

- `last-run.log`: UNA `write_text` en un `finally` (`stream_pytest:975`). Tras matar dos
  corridas de ~19 min de CPU, seguia intacto: **1372 bytes de un focal anterior**.
- `tests/conftest.py`: su unico hook de sesion es `pytest_sessionfinish` (`:296`).
- Las 9 filas `aborted`: `top_slowest: []`, `passed: None`, `errors: None`. **Cero nodeids.**
- `atexit` y `finally` **no corren ante TerminateProcess** (probe: confirmado).

---

## 1. POR QUE "escribir el log incremental" NO BASTA (medido)

- Con `-q` (lo que usa el runner) cada test es **un punto sin nombre**: volcar stdout linea a
  linea NO dice que test corria.
- Con `-v` hay nodeid, pero la linea se emite **cuando el test TERMINA**. El test que empieza
  y muere **no aparece nunca**: es justo el que buscamos.

**Corolario: hay que registrar el INICIO, no el final.**

---

## 2. CANALES PROPUESTOS (5, independientes, por orden de valor/coste)

### C1-HEARTBEAT -- hooks de protocolo de pytest [PROBADO]
Tres hooks en `conftest.py`, NDJSON append-only con `flush()`:
| hook | corre | ancla |
|---|---|---|
| `pytest_collection_finish` | antes del 1er test | denominador real + marcador de arranque |
| `pytest_runtest_logstart` | **ANTES** de cada test | **el culpable** |
| `pytest_runtest_logreport` | al terminar cada fase | outcome + duracion |

Discriminante **estructural, no heuristico**: el ultimo nodeid con `start` y sin `end` es
donde murio.

**PROBE CON CONTROL POSITIVO (ejecutado):** fixture de 6 tests, matado a los 3 s.
`command:` `timeout 3 python -m pytest tests -q -p no:cacheprovider`
Heartbeat resultante: 11 eventos; `test_e` registrado `failed`; `test_f` con `start` y **sin
`end`**. El culpable queda senalado por AUSENCIA. Hoy eso no existe.

### C2-FAULTHANDLER -- volcado de stack ante cuelgue [PROBADO]
`faulthandler.dump_traceback_later(N, repeat=True, file=<fichero>)`: si pasan N segundos sin
que el proceso avance, vuelca el stack de **todos los hilos** a disco. No depende de `finally`,
`atexit` ni de que nadie limpie.

**PROBE (ejecutado):** funcion que duerme 10 s con watchdog a 2 s ->
```
Timeout (0:00:02)!
Thread 0x0000229c (most recent call first):
  File "...probe.py", line 5 in funcion_que_cuelga
  File "...probe.py", line 6 in <module>
```
**Complementa a C1 y no lo duplica:** C1 dice QUE TEST; C2 dice **EN QUE LINEA** estaba, con
el stack completo. Para un cuelgue (no una muerte) es el unico canal que da causa.
Limite medido: `faulthandler.register()` **no existe en Windows**, asi que no se puede
enganchar a senales arbitrarias; `dump_traceback_later` si funciona.

### C3-ENTORNO -- muestreo periodico [NO PROBADO]
Hilo demonio que cada ~30 s anexa: RAM libre, nº procesos, entradas del arbol, PID vivo.
Hoy `environment_at_start` es **una sola foto al arrancar** (22 de 500 filas la tienen): no
puede mostrar una TENDENCIA hacia la muerte. Sin serie temporal no hay correlacion posible.

### C4-FORENSE -- que Pieza B escriba sus 4 campos [diagnosticado, no implementado]
`reconciled_at`, `reconciled_reason`, `lock_pid`, `assumed_dead` existen en codigo y **no se
pueblan (0 de 9 filas)**. Consecuencia medida hoy: **el conteo de muertes NO es re-derivable**,
y hay un FANTASMA PROBADO -- la fila de 15:18:35 declara muerta una corrida cuyo pid 45232
siguio vivo ~90 min. Sin C4, no sabemos ni cuantas muertes hubo.

### C5-EXITCODE CRUDO -- no normalizar a 0..5 [hallazgo de hoy]
Decodificando los 48 exit codes anomalos aparecio **`0x40010004` = `DBG_TERMINATE_PROCESS`**
("terminado por un DEPURADOR") en 3 corridas `all` (27-ago, 3-sep, 6-sep). **El forense
analizo `0xFFFFFFFF` y NUNCA vio este** (0 hits en sus 250 lineas). Si el runner normalizara
el codigo, esa pista se habria perdido. **Registrar el crudo es coste cero.**

---

## 3. VISUALIZACION EN CHAT [PROTOTIPO EJECUTADO]

Render del NDJSON a markdown. Salida REAL del probe de C1 (corrida matada a los 3 s):
```
`█████████████████████░░░░░░░░░░░` ** 66.7%**   4/6 tests
| passed | failed | skipped | transcurrido |
| 3 | 1 | 0 | 1s |
mas lentos: test_d 0.60s, test_b 0.30s
fallos: tests/test_demo.py::test_e
> EN VUELO / ULTIMO ANTES DE MORIR: tests/test_demo.py::test_f
```
Consultable DURANTE la corrida o POST-MORTEM, desde cualquier sesion, porque vive en disco.
**Estado: prototipo en `/tmp`, NO codigo del repo.** Falta decidir donde vive.

---

## 4. LO QUE YA SE DESCARTO (no re-proponer)
- **WER / Event Viewer**: 0 eventos en la ventana de las 6 muertes. Ausencia informativa (un
  crash nativo habria dejado entrada), pero **no es un canal**: ya se consulto y esta vacio.
- **`pytest-timeout`**: dependencia nueva -> requiere aprobacion por regla del repo. C2 cubre
  el caso de cuelgue **sin anadir dependencia** (faulthandler es stdlib).
- Optimizar tests concretos, xdist, umbral de RAM: refutados o con dueno ajeno.

## 5. COSTE Y RIESGOS (declarados)
- **I/O de C1**: 3 escrituras pequenas x 6495 tests. `flush()` siempre; `fsync()` solo en
  `collection_finish` y cada N. Un `fsync` por test es medible: **barrer ANTES de adoptar**
  contra la mediana de 704 s.
- **Path por corrida (sufijo PID)**: con `--force-unlock` sin arreglar, dos corridas vivas son
  el modo OPERATIVO esperado; un fichero compartido se entrelaza.
- **C2 y el ruido**: `repeat=True` sobre una suite con tests legitimamente lentos (hay uno de
  162 s documentado) generaria volcados espurios. El umbral N debe salir de un barrido, no
  elegirse a ojo -- y si cae en una meseta, declararlo.
- **Ninguno sustituye a `last-run.log`**: son canales nuevos, append-only.

## 6. DoD (invariantes)
1. Matar una corrida viva -> el heartbeat contiene un nodeid con `start` y sin `end`.
2. Matar durante la coleccion -> contiene el marcador de coleccion.
3. Dos corridas vivas -> cada una deja su heartbeat integro, sin entrelazar.
4. Colgar un test mas de N s -> existe volcado de stack con la linea exacta.
5. El exit code crudo queda registrado sin normalizar.
6. Delta de duracion sobre la suite completa medido y declarado antes de adoptar.

## 7. PREGUNTAS PARA LAS LENTES
1. ¿Que canal de causa NO esta en la lista y se puede capturar barato en Windows?
2. ¿C2 (faulthandler) aporta sobre C1 o es redundante? ¿Como se elige N sin inventarlo?
3. ¿El orden C1 > C2 > C3 > C4 > C5 es correcto por valor/coste, o hay uno infravalorado?
4. ¿Que riesgo tiene anadir 3 hooks al `conftest.py` de una suite que ya muere sola?
5. ¿Hay algo aqui que re-proponga una hipotesis ya refutada por el forense?
